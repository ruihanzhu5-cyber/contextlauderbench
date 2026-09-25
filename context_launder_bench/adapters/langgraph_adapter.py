from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph, add_messages

from ..model import RunResult, Scenario, canonical
from ..runner import ExecutionState, finish_scenario, prepare_scenario


class GraphState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    payload: dict[str, Any]
    value_id: str
    task: str
    pieces: Annotated[list[str], operator.add]


class LangGraphAdapter:
    """Native graph transport; all security facts remain in TrustedRuntime."""

    def run(self, scenario: Scenario) -> RunResult:
        state = prepare_scenario(scenario)
        mapping: dict[str, str] = {}
        builder = StateGraph(GraphState)
        message_id = f"message-{scenario.scenario_id}"

        if scenario.channel == "DIRECT_OR_MESSAGE":
            def source(graph_state: GraphState) -> GraphState:
                message = HumanMessage(
                    content=canonical({"arguments": graph_state["payload"],
                                       "metadata": dict(scenario.metadata)}),
                    id=message_id,
                )
                return {"messages": [message]}
            def receive(graph_state: GraphState) -> GraphState:
                assert graph_state["messages"][-1].id == message_id
                state.runtime.send("source-node", "receive-node", graph_state["value_id"])
                mapping[message_id] = graph_state["value_id"]
                return {"payload": graph_state["payload"]}
            builder.add_node("source", source)
            builder.add_node("receive", receive)
            builder.add_edge(START, "source")
            builder.add_edge("source", "receive")
            tail = "receive"
        elif scenario.channel == "SHARED_STATE_OR_MEMORY":
            def source(graph_state: GraphState) -> GraphState:
                return {"payload": dict(graph_state["payload"]),
                        "value_id": graph_state["value_id"]}
            def memory(graph_state: GraphState) -> GraphState:
                state.runtime.observe_boundary("shared-state", graph_state["value_id"], graph_state["value_id"])
                state.runtime.memory_write("langgraph-state", graph_state["value_id"])
                value_id = state.runtime.memory_read("langgraph-state")
                mapping["shared-state"] = value_id
                return {"value_id": value_id}
            builder.add_node("source", source)
            builder.add_node("memory", memory)
            builder.add_edge(START, "source")
            builder.add_edge("source", "memory")
            tail = "memory"
        elif scenario.channel == "SPLIT_TRANSFORM_JOIN":
            def branch_a(graph_state: GraphState) -> GraphState:
                return {"pieces": ["target"]}
            def branch_b(graph_state: GraphState) -> GraphState:
                return {"pieces": ["authority"]}
            def join(graph_state: GraphState) -> GraphState:
                assert set(graph_state["pieces"]) == {"target", "authority"}
                mapping["join-state"] = graph_state["value_id"]
                return {"payload": dict(graph_state["payload"])}
            builder.add_node("branch_a", branch_a)
            builder.add_node("branch_b", branch_b)
            builder.add_node("join", join)
            builder.add_edge(START, "branch_a")
            builder.add_edge(START, "branch_b")
            builder.add_edge(["branch_a", "branch_b"], "join")
            tail = "join"
        else:
            raise ValueError(f"Unknown channel {scenario.channel}")

        if scenario.family == "cross_task":
            def task_switch(graph_state: GraphState) -> GraphState:
                mapping["task-switch-state"] = graph_state["value_id"]
                state.runtime.observe_boundary("task-switch", graph_state["value_id"], graph_state["value_id"], represented_fields=("task",))
                return {"task": "T2"}
            builder.add_node("task_switch", task_switch)
            builder.add_edge(tail, "task_switch")
            tail = "task_switch"

        builder.add_edge(tail, END)
        checkpointer = InMemorySaver()
        graph = builder.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": scenario.scenario_id}}
        output = graph.invoke(
            {"payload": dict(scenario.arguments), "value_id": state.value_id,
             "task": "T1" if scenario.family == "cross_task" else "T2",
             "pieces": [], "messages": []},
            config,
        )
        snapshot = graph.get_state(config)
        if output["value_id"] != state.value_id:
            raise AssertionError("Graph changed trusted value mapping")
        mapping["checkpoint"] = snapshot.values["value_id"]
        if scenario.channel == "SHARED_STATE_OR_MEMORY":
            state.value_id = snapshot.values["value_id"]
        return finish_scenario(scenario, state, "LangGraph", mapping)
