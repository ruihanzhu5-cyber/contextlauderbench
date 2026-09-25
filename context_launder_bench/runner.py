from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .backends import ScriptedBackend
from .endpoint import UnifiedMockEndpoint
from .model import Decision, RunResult, Scenario, digest
from .oracle import GroundTruthOracle
from .policies import AdmissionPolicy, GroundTruthEnforcingPolicy, policy_from_id
from .runtime import TrustedRuntime


@dataclass
class ExecutionState:
    runtime: TrustedRuntime
    endpoint: UnifiedMockEndpoint
    context_ref: str
    value_id: str
    native_mapping: dict[str, str] = field(default_factory=dict)


def prepare_scenario(scenario: Scenario, policy_id: str = "D0") -> ExecutionState:
    return _prepare_scenario(scenario, policy_from_id(policy_id))


def prepare_e0_scenario(scenario: Scenario) -> ExecutionState:
    return _prepare_scenario(scenario, GroundTruthEnforcingPolicy())


def _prepare_scenario(scenario: Scenario, admission_policy: AdmissionPolicy) -> ExecutionState:
    runtime = TrustedRuntime(scenario.scenario_id, scenario.family)
    endpoint = UnifiedMockEndpoint(runtime, admission_policy)
    runtime.grant_capability(scenario.capability_id, scenario.executor_id, [scenario.tool_name])
    action = digest({"tool": scenario.tool_name, "arguments": scenario.arguments})
    context_ref = runtime.begin_task("user-A", "T2", "main", "execute-request",
                                     1, [scenario.tool_name])
    if scenario.family == "sibling":
        runtime.spawn("main", "reader", "reader-branch")
        source_ref = runtime.begin_task("user-A", "T2", "reader-branch",
                                        "read-target", 1, [scenario.tool_name])
        source = "trusted_user" if scenario.legal else "untrusted_reader"
        env = runtime.seed_value(dict(scenario.arguments), source, source_ref)
        value_id = env.value_id
    elif scenario.family == "cross_task":
        old_ref = runtime.begin_task("user-A", "T1", "prior", "old-task", 1,
                                     [scenario.tool_name])
        env = runtime.seed_value(dict(scenario.arguments), "trusted_workflow", context_ref)
        value_id = env.value_id
        approval_task = "T2" if scenario.legal else "T1"
        runtime.endorse("user-A", action, approval_task, "cross_task", 1)
        runtime.event("TaskSwitch", from_task="T1", to_task="T2",
                      context_before=old_ref, context_after=context_ref)
        runtime.observe_boundary("task-switch", value_id, value_id,
                                 represented_fields=("task",))
    elif scenario.family == "cross_epoch":
        env = runtime.seed_value(dict(scenario.arguments), "trusted_user", context_ref)
        runtime.memory_write("target", env.value_id)
        runtime.endorse("user-A", action, "T2", "cross_epoch", 1)
        runtime.revoke("cross_epoch")
        epoch = runtime.advance_epoch("T2", "cross_epoch")
        context_ref = runtime.begin_task("user-A", "T2", "main", "execute-request",
                                         epoch, [scenario.tool_name])
        value_id = runtime.memory_read("target")
        if scenario.legal:
            runtime.endorse("user-A", action, "T2", "cross_epoch", epoch)
    elif scenario.family == "fork_join":
        runtime.spawn("main", "A", "branch-A")
        runtime.spawn("main", "B", "branch-B")
        a_ref = runtime.begin_task("user-A", "T2", "branch-A", "target", 1,
                                   [scenario.tool_name])
        b_ref = runtime.begin_task("user-A", "T2", "branch-B", "approval", 1,
                                   [scenario.tool_name])
        target = runtime.seed_value(scenario.arguments.get("account"),
                                    "trusted_workflow", a_ref)
        marker = runtime.seed_value("approval-marker", "trusted_workflow", b_ref)
        value_id = runtime.join("main", (target.value_id, marker.value_id),
                                dict(scenario.arguments), context_ref).value_id
        binding = action if scenario.legal else digest({"scope": "general-payment"})
        runtime.endorse("user-A", binding, "T2", "fork_join", 1)
    else:
        raise ValueError(f"Unknown family: {scenario.family}")
    return ExecutionState(runtime, endpoint, context_ref, value_id)


def apply_channel(state: ExecutionState, scenario: Scenario) -> None:
    rt = state.runtime
    if scenario.channel == "DIRECT_OR_MESSAGE":
        rt.send("scripted-source", "executor-main", state.value_id)
    elif scenario.channel == "SHARED_STATE_OR_MEMORY":
        rt.observe_boundary("shared-state", state.value_id, state.value_id)
        rt.memory_write("channel-value", state.value_id)
        state.value_id = rt.memory_read("channel-value")
    elif scenario.channel == "SPLIT_TRANSFORM_JOIN":
        if scenario.family == "fork_join":
            return
        rt.spawn("executor-main", "aux", "aux-branch")
        aux = rt.seed_value("channel-witness", "trusted_workflow", state.context_ref)
        state.value_id = rt.join("executor-main", (state.value_id, aux.value_id),
                                 dict(scenario.arguments), state.context_ref).value_id
    else:
        raise ValueError(f"Unknown channel: {scenario.channel}")


def finish_scenario(scenario: Scenario, state: ExecutionState,
                    framework: str, native_mapping: dict[str, str] | None = None) -> RunResult:
    intent = ScriptedBackend().run(scenario)
    # All self-declared fields are inert text, even when they resemble trusted metadata.
    if intent.self_declared_metadata:
        state.runtime.event("AgentText", payload_digest=digest(intent.self_declared_metadata))
    request = state.runtime.make_request(
        scenario.tool_name, intent.arguments, scenario.executor_id,
        scenario.capability_id, scenario.callsite_id, state.context_ref, state.value_id
    )
    outcome = state.endpoint.invoke(request)
    ground_truth_authorized = GroundTruthOracle().authorized(state.runtime, request)
    state.runtime.event(
        "OutcomeEvaluated",
        ground_truth_authorized=ground_truth_authorized,
        unsafe_commit=outcome.committed and not ground_truth_authorized,
    )
    if outcome.committed:
        endorsement = state.runtime.valid_endorsement(
            request, state.runtime.scenario_family
        )
        if endorsement is not None:
            state.runtime.consume_endorsement(endorsement.nonce)
    from .analysis import classify_result
    result = RunResult(
        scenario.scenario_id, framework, outcome.admission_policy,
        outcome.admission_decision, outcome.committed, outcome.reason_code,
        ground_truth_authorized, state.runtime.events,
        state.runtime.canonical_log_digest(), native_mapping or {},
        terminal_signature=scenario.terminal_signature()
    )
    from dataclasses import replace
    return replace(result, discontinuities=classify_result(result))


def run_free(scenario: Scenario, policy_id: str = "D0") -> RunResult:
    state = prepare_scenario(scenario, policy_id)
    apply_channel(state, scenario)
    return finish_scenario(scenario, state, "framework-free")


def run_e0(scenario: Scenario) -> RunResult:
    state = prepare_e0_scenario(scenario)
    apply_channel(state, scenario)
    return finish_scenario(scenario, state, "framework-free")
