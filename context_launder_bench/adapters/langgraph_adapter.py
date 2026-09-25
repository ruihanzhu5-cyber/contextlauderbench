from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph, add_messages

from ..backends import AgentBackend, AgentInput, ToolAttempt
from ..model import RunResult, Scenario, canonical, digest
from ..runner import finish_scenario, prepare_scenario


class GraphState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    payload: Any
    value_id: str
    task: str
    pieces: Annotated[list[str], operator.add]
    attempt: dict[str, Any]
    memory_value_id: str
    join_value_id: str
    branch_a_value_id: str
    branch_b_value_id: str


class LangGraphAdapter:
    """Native graph transport; all security facts remain in TrustedRuntime."""

    def run(self, scenario: Scenario, policy_id: str = "D0",
            backend: AgentBackend | None = None,
            upstream_output: Any = None) -> RunResult:
        model_mode = backend is not None
        if model_mode and (not scenario.task_text or upstream_output is None):
            raise ValueError("Model path requires task_text and upstream_output")
        state = prepare_scenario(
            scenario, policy_id,
            source_payload=upstream_output if model_mode else None,
            defer_fork_join=scenario.family == "fork_join",
        )
        mapping: dict[str, str] = {}
        builder = StateGraph(GraphState)
        message_id = f"message-{scenario.scenario_id}"

        if scenario.channel == "DIRECT_OR_MESSAGE":
            def source(graph_state: GraphState) -> GraphState:
                message = HumanMessage(
                    content=canonical({
                        "upstream_output": graph_state["payload"],
                        "metadata": dict(scenario.metadata),
                    }),
                    id=message_id,
                )
                return {"messages": [message]}

            def receive(graph_state: GraphState) -> GraphState:
                message = graph_state["messages"][-1]
                assert message.id == message_id
                received = json.loads(message.content)["upstream_output"]
                before = graph_state["value_id"]
                state.runtime.send("source-node", "receive-node", before)
                source_value = state.runtime.value(before)
                if source_value is None:
                    raise ValueError("Missing sent value")
                after = before
                if canonical(source_value.payload) != canonical(received):
                    after = state.runtime.derive(
                        (before,), received, "message-decode", state.context_ref,
                    ).value_id
                    state.runtime.observe_boundary("message-decode", before, after)
                mapping[message_id] = after
                return {"payload": received, "value_id": after}

            builder.add_node("source", source)
            builder.add_node("receive", receive)
            builder.add_edge(START, "source")
            builder.add_edge("source", "receive")
            tail = "receive"
        elif scenario.channel == "SHARED_STATE_OR_MEMORY":
            def source(graph_state: GraphState) -> GraphState:
                return {"payload": graph_state["payload"],
                        "value_id": graph_state["value_id"]}

            def memory(graph_state: GraphState) -> GraphState:
                value_id = graph_state["value_id"]
                state.runtime.observe_boundary("shared-state", value_id, value_id)
                state.runtime.memory_write("langgraph-state", value_id)
                restored_id = state.runtime.memory_read("langgraph-state")
                mapping["shared-state"] = restored_id
                return {
                    "value_id": restored_id,
                    "memory_value_id": restored_id,
                    "payload": graph_state["payload"],
                }

            builder.add_node("source", source)
            builder.add_node("memory", memory)
            builder.add_edge(START, "source")
            builder.add_edge("source", "memory")
            tail = "memory"
        elif scenario.channel == "SPLIT_TRANSFORM_JOIN":
            if scenario.family == "fork_join":
                tail = START
            else:
                def branch_a(graph_state: GraphState) -> GraphState:
                    value_id = state.runtime.derive(
                        (graph_state["value_id"],), graph_state["payload"],
                        "langgraph-channel-branch-A", state.context_ref,
                    ).value_id
                    mapping["branch-A"] = value_id
                    return {"pieces": ["target"], "branch_a_value_id": value_id}

                def branch_b(graph_state: GraphState) -> GraphState:
                    value_id = state.runtime.derive(
                        (graph_state["value_id"],), "channel-witness",
                        "langgraph-channel-branch-B", state.context_ref,
                    ).value_id
                    mapping["branch-B"] = value_id
                    return {"pieces": ["authority"], "branch_b_value_id": value_id}

                def join(graph_state: GraphState) -> GraphState:
                    assert set(graph_state["pieces"]) == {"target", "authority"}
                    joined = state.runtime.join(
                        "executor-main",
                        (graph_state["branch_a_value_id"],
                         graph_state["branch_b_value_id"]),
                        graph_state["payload"], state.context_ref,
                    )
                    mapping["join-state"] = joined.value_id
                    return {
                        "payload": graph_state["payload"],
                        "value_id": joined.value_id,
                        "join_value_id": joined.value_id,
                    }

                builder.add_node("branch_a", branch_a)
                builder.add_node("branch_b", branch_b)
                builder.add_node("join", join)
                builder.add_edge(START, "branch_a")
                builder.add_edge(START, "branch_b")
                builder.add_edge(["branch_a", "branch_b"], "join")
                tail = "join"
        else:
            raise ValueError(f"Unknown channel {scenario.channel}")

        if scenario.family == "fork_join":
            parent = tail

            def branch_a(graph_state: GraphState) -> GraphState:
                payload = graph_state["payload"]
                target = payload.get("account") if isinstance(payload, dict) else payload
                value_id = state.runtime.derive(
                    (graph_state["value_id"],), target,
                    "langgraph-branch-A", state.branch_contexts["A"],
                ).value_id
                mapping["branch-A"] = value_id
                return {"pieces": ["target"], "branch_a_value_id": value_id}

            def branch_b(graph_state: GraphState) -> GraphState:
                value_id = state.runtime.derive(
                    (graph_state["value_id"],), "approval-marker",
                    "langgraph-branch-B", state.branch_contexts["B"],
                ).value_id
                mapping["branch-B"] = value_id
                return {"pieces": ["authority"], "branch_b_value_id": value_id}

            def join(graph_state: GraphState) -> GraphState:
                assert set(graph_state["pieces"]) == {"target", "authority"}
                joined = state.runtime.join(
                    "main",
                    (graph_state["branch_a_value_id"],
                     graph_state["branch_b_value_id"]),
                    graph_state["payload"], state.context_ref,
                )
                mapping["join-state"] = joined.value_id
                return {
                    "payload": graph_state["payload"],
                    "value_id": joined.value_id,
                    "join_value_id": joined.value_id,
                }

            builder.add_node("branch_a", branch_a)
            builder.add_node("branch_b", branch_b)
            builder.add_node("join", join)
            builder.add_edge(parent, "branch_a")
            builder.add_edge(parent, "branch_b")
            builder.add_edge(["branch_a", "branch_b"], "join")
            tail = "join"

        if scenario.family == "cross_task":
            def task_switch(graph_state: GraphState) -> GraphState:
                mapping["task-switch-state"] = graph_state["value_id"]
                state.runtime.observe_boundary(
                    "task-switch", graph_state["value_id"],
                    graph_state["value_id"],
                )
                return {"task": "T2"}

            builder.add_node("task_switch", task_switch)
            builder.add_edge(tail, "task_switch")
            tail = "task_switch"

        if backend is not None:
            def agent(graph_state: GraphState) -> GraphState:
                if scenario.channel == "DIRECT_OR_MESSAGE":
                    native_input = deepcopy(graph_state["messages"][-1])
                    native_kind = "HumanMessage"
                    native_digest = digest(native_input.model_dump())
                else:
                    native_input = deepcopy(dict(graph_state))
                    native_kind = ("checkpoint_state" if scenario.channel ==
                                   "SHARED_STATE_OR_MEMORY" else "joined_graph_state")
                    native_digest = digest(native_input)
                state.runtime.event(
                    "ModelInput", task_digest=digest(scenario.task_text),
                    value_id=graph_state["value_id"],
                    payload_digest=digest(graph_state["payload"]),
                    native_kind=native_kind,
                    native_input_digest=native_digest,
                )
                attempt = backend.run(AgentInput(scenario.task_text, native_input))
                state.runtime.event(
                    "ModelOutput", status=attempt.status,
                    tool_call_digest=digest({
                        "tool_name": attempt.tool_name,
                        "arguments": attempt.arguments,
                    }) if attempt.status == "tool_call" else None,
                )
                return {"attempt": {
                    "status": attempt.status, "tool_name": attempt.tool_name,
                    "arguments": (dict(attempt.arguments)
                                  if attempt.arguments is not None else None),
                    "error": attempt.error,
                    "provider_response_id": attempt.provider_response_id,
                    "finish_reason": attempt.finish_reason,
                    "prompt_digest": attempt.prompt_digest,
                }}

            builder.add_node("agent", agent)
            builder.add_edge(tail, "agent")
            tail = "agent"

        builder.add_edge(tail, END)
        graph = builder.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": scenario.scenario_id}}
        initial_payload = (
            upstream_output if model_mode else dict(scenario.arguments)
        )
        output = graph.invoke(
            {"payload": initial_payload, "value_id": state.value_id,
             "task": "T1" if scenario.family == "cross_task" else "T2",
             "pieces": [], "messages": []},
            config,
        )
        snapshot = graph.get_state(config)
        if state.runtime.value(output["value_id"]) is None:
            raise AssertionError("Graph value has no runtime lineage")
        mapping["checkpoint"] = snapshot.values["value_id"]
        state.value_id = snapshot.values["value_id"]
        result = finish_scenario(
            scenario, state, "LangGraph", mapping,
            attempt=ToolAttempt(**output["attempt"]) if model_mode else None,
            observed_payload=output["payload"] if model_mode else None,
        )
        if not model_mode:
            return result
        source_metadata = (backend.experiment_metadata()
                           if hasattr(backend, "experiment_metadata") else
                           {"provider": "custom",
                            "model": type(backend).__name__, "model_config": {}})
        return replace(result, experiment_metadata={
            **source_metadata,
            "framework": "LangGraph",
            "scenario_id": scenario.scenario_id,
            "upstream_input_digest": digest(upstream_output),
            "task_digest": digest(scenario.task_text),
            "prompt_digest": output["attempt"].get("prompt_digest"),
            "provider_response_id": output["attempt"].get("provider_response_id"),
            "finish_reason": output["attempt"].get("finish_reason"),
        })
