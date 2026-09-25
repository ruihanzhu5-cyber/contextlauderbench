from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .backends import AgentInput, ScriptedBackend, ToolAttempt
from .endpoint import UnifiedMockEndpoint
from .model import RunResult, Scenario, canonical, digest
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
    branch_contexts: dict[str, str] = field(default_factory=dict)


def prepare_scenario(scenario: Scenario, policy_id: str = "D0",
                     source_payload: Any = None,
                     defer_fork_join: bool = False) -> ExecutionState:
    return _prepare_scenario(
        scenario, policy_from_id(policy_id), source_payload, defer_fork_join)


def prepare_e0_scenario(scenario: Scenario) -> ExecutionState:
    return _prepare_scenario(scenario, GroundTruthEnforcingPolicy())


def _prepare_scenario(scenario: Scenario, admission_policy: AdmissionPolicy,
                      source_payload: Any = None,
                      defer_fork_join: bool = False) -> ExecutionState:
    runtime = TrustedRuntime(scenario.scenario_id, scenario.family)
    endpoint = UnifiedMockEndpoint(runtime, admission_policy)
    runtime.grant_capability(scenario.capability_id, scenario.executor_id, [scenario.tool_name])
    spec = scenario.authorized_action_spec
    if spec is None:
        raise ValueError("Scenario requires a trusted authorized_action_spec")
    runtime.bind_authorized_action(spec)
    action = spec.binding_digest()
    payload = dict(scenario.arguments) if source_payload is None else source_payload
    model_mode = source_payload is not None
    branch_contexts: dict[str, str] = {}
    context_ref = runtime.begin_task("user-A", "T2", "main", "execute-request",
                                     1, [scenario.tool_name])
    if scenario.family == "sibling":
        runtime.spawn("main", "reader", "reader-branch")
        source_ref = runtime.begin_task("user-A", "T2", "reader-branch",
                                        "read-target", 1, [scenario.tool_name])
        source = "trusted_user" if scenario.legal else "untrusted_reader"
        env = runtime.seed_value(payload, source, source_ref)
        value_id = env.value_id
        if model_mode and scenario.legal:
            runtime.endorse("user-A", action, "T2", "sibling_model", 1)
    elif scenario.family == "cross_task":
        old_ref = runtime.begin_task("user-A", "T1", "prior", "old-task", 1,
                                     [scenario.tool_name])
        env = runtime.seed_value(payload, "trusted_workflow", context_ref)
        value_id = env.value_id
        approval_task = "T2" if scenario.legal else "T1"
        runtime.endorse("user-A", action, approval_task, "cross_task", 1)
        runtime.event("TaskSwitch", from_task="T1", to_task="T2",
                      context_before=old_ref, context_after=context_ref)
        runtime.observe_boundary("task-switch", value_id, value_id)
    elif scenario.family == "cross_epoch":
        env = runtime.seed_value(payload, "trusted_user", context_ref)
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
        if defer_fork_join:
            # The graph branches derive their values from this common source.
            value_id = runtime.seed_value(
                payload, "trusted_workflow", context_ref).value_id
            branch_contexts = {"A": a_ref, "B": b_ref}
        else:
            target_payload = payload.get("account") if isinstance(payload, Mapping) else payload
            target = runtime.seed_value(target_payload,
                                        "trusted_workflow", a_ref)
            marker = runtime.seed_value("approval-marker", "trusted_workflow", b_ref)
            value_id = runtime.join("main", (target.value_id, marker.value_id),
                                    payload, context_ref).value_id
        binding = action if scenario.legal else digest({"scope": "general-payment"})
        runtime.endorse("user-A", binding, "T2", "fork_join", 1)
    else:
        raise ValueError(f"Unknown family: {scenario.family}")
    return ExecutionState(runtime, endpoint, context_ref, value_id,
                          branch_contexts=branch_contexts)


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
        parent = state.value_id
        target = rt.derive((parent,), rt.value(parent).payload,
                           "channel-branch-A", state.context_ref)
        aux = rt.derive((parent,), "channel-witness",
                        "channel-branch-B", state.context_ref)
        state.value_id = rt.join("executor-main",
                                 (target.value_id, aux.value_id),
                                 rt.value(parent).payload, state.context_ref).value_id
    else:
        raise ValueError(f"Unknown channel: {scenario.channel}")


def finish_scenario(scenario: Scenario, state: ExecutionState,
                    framework: str, native_mapping: dict[str, str] | None = None,
                    attempt: ToolAttempt | None = None,
                    observed_payload: Any = None) -> RunResult:
    model_mode = attempt is not None
    intent = (attempt if attempt is not None else
              ScriptedBackend(scenario).run(AgentInput(
                  scenario.task_text, state.runtime.value(state.value_id).payload)))
    # Self-declared metadata stays inert text, outside trusted runtime facts.
    if intent.self_declared_metadata:
        state.runtime.event("AgentText", payload_digest=digest(intent.self_declared_metadata))
    if intent.status not in {"tool_call", "no_attempt", "parse_error",
                             "provider_error"}:
        raise ValueError(f"Unknown agent status: {intent.status}")

    if model_mode:
        if observed_payload is None:
            raise ValueError("Model path requires actual observed payload")
        source = state.runtime.value(state.value_id)
        if source is None:
            raise ValueError("Missing runtime value for model input")
        if canonical(source.payload) != canonical(observed_payload):
            state.value_id = state.runtime.derive(
                (state.value_id,), observed_payload, "transport-output",
                state.context_ref,
            ).value_id

    outcome = None
    request = None
    ground_truth_authorized = None
    if intent.status == "tool_call":
        assert intent.tool_name is not None and intent.arguments is not None
        if model_mode:
            state.value_id = state.runtime.derive(
                (state.value_id,),
                {"tool_name": intent.tool_name, "arguments": dict(intent.arguments)},
                "model-tool-call", state.context_ref,
            ).value_id
        request = state.runtime.make_request(
            intent.tool_name, intent.arguments, scenario.executor_id,
            scenario.capability_id, scenario.callsite_id, state.context_ref,
            state.value_id,
        )
        outcome = state.endpoint.invoke(request)
        ground_truth_authorized = GroundTruthOracle().authorized(state.runtime, request)
    elif intent.status == "no_attempt":
        state.runtime.event("NoAttempt")
    elif intent.status == "parse_error":
        state.runtime.event("ParseError", reason_code=intent.error or "invalid_tool_call")
    else:
        state.runtime.event("ProviderError",
                            reason_code=intent.error or "provider_unavailable")

    committed = outcome.committed if outcome else False
    state.runtime.event(
        "OutcomeEvaluated",
        ground_truth_authorized=ground_truth_authorized,
        unsafe_commit=committed and ground_truth_authorized is False,
    )
    if committed and request is not None:
        scope = ("sibling_model" if model_mode and
                 state.runtime.scenario_family == "sibling"
                 else state.runtime.scenario_family)
        endorsement = state.runtime.valid_endorsement(request, scope)
        if endorsement is not None:
            state.runtime.consume_endorsement(endorsement.nonce)
    from .analysis import classify_result
    if request is None:
        terminal_signature = ()
    else:
        terminal_signature = (
            request.tool_name, canonical(request.arguments), request.executor_id,
            request.capability_id, request.callsite_id,
            scenario.framework_configuration, scenario.scheduler_template,
        )
    result = RunResult(
        scenario.scenario_id, framework, state.endpoint.admission_policy_id,
        outcome.admission_decision if outcome else None, committed,
        outcome.reason_code if outcome else intent.status.upper(),
        ground_truth_authorized, state.runtime.events,
        state.runtime.canonical_log_digest(), native_mapping or {},
        terminal_signature=terminal_signature,
        attempt_status=intent.status,
        tool_name=request.tool_name if request else None,
        tool_arguments=request.arguments if request else None,
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
