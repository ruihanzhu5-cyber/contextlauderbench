from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .model import Decision, ToolRequest
from .oracle import GroundTruthOracle
from .runtime import TrustedRuntime


@dataclass(frozen=True)
class AdmissionOutcome:
    decision: Decision
    reason_code: str


class AdmissionPolicy(Protocol):
    policy_id: str
    enforced_fields: tuple[str, ...]

    def decide(self, runtime: TrustedRuntime, request: ToolRequest) -> AdmissionOutcome: ...


class AllowAllPolicy:
    policy_id = "D0"
    enforced_fields: tuple[str, ...] = ()

    def decide(self, runtime: TrustedRuntime, request: ToolRequest) -> AdmissionOutcome:
        return AdmissionOutcome(Decision.ALLOW, "FRAMEWORK_DEFAULT")


class ToolAllowlistPolicy:
    policy_id = "D1"
    enforced_fields = ("tool_allowlist",)

    def decide(self, runtime: TrustedRuntime, request: ToolRequest) -> AdmissionOutcome:
        context = runtime.context(request.runtime_context_ref)
        allowed = context is not None and request.tool_name in context.allowed_sinks
        return AdmissionOutcome(Decision.ALLOW if allowed else Decision.DENY,
                                "TOOL_ALLOWLIST_PASS" if allowed else "TOOL_NOT_ALLOWLISTED")


class ExecutorCapabilityPolicy:
    policy_id = "D2"
    enforced_fields = ("executor_capability",)

    def decide(self, runtime: TrustedRuntime, request: ToolRequest) -> AdmissionOutcome:
        allowed = runtime.capability_valid(request)
        return AdmissionOutcome(Decision.ALLOW if allowed else Decision.DENY,
                                "EXECUTOR_CAPABILITY_PASS" if allowed else "NO_EXECUTOR_CAPABILITY")


class CombinedPolicy:
    policy_id = "D3"
    enforced_fields = ("tool_allowlist", "executor_capability")

    def decide(self, runtime: TrustedRuntime, request: ToolRequest) -> AdmissionOutcome:
        allowlist = ToolAllowlistPolicy().decide(runtime, request)
        if allowlist.decision is Decision.DENY:
            return allowlist
        capability = ExecutorCapabilityPolicy().decide(runtime, request)
        if capability.decision is Decision.DENY:
            return capability
        return AdmissionOutcome(Decision.ALLOW, "ALLOWLIST_AND_CAPABILITY_PASS")


class GroundTruthEnforcingPolicy:
    """E0 infrastructure validation only. E1–E3 runners never accept this policy."""

    policy_id = "E0_GROUND_TRUTH_ENFORCING"
    enforced_fields = ("source", "task", "branch", "purpose", "epoch", "approval_binding", "tool_allowlist", "executor_capability")

    def __init__(self, oracle: GroundTruthOracle | None = None):
        self._oracle = oracle or GroundTruthOracle()

    def decide(self, runtime: TrustedRuntime, request: ToolRequest) -> AdmissionOutcome:
        allowed = self._oracle.authorized(runtime, request)
        return AdmissionOutcome(Decision.ALLOW if allowed else Decision.DENY,
                                "GROUND_TRUTH_AUTHORIZED" if allowed else "GROUND_TRUTH_UNAUTHORIZED")


POLICY_IDS = ("D0", "D1", "D2", "D3")


def policy_from_id(policy_id: str) -> AdmissionPolicy:
    factories = {
        "D0": AllowAllPolicy,
        "D1": ToolAllowlistPolicy,
        "D2": ExecutorCapabilityPolicy,
        "D3": CombinedPolicy,
    }
    try:
        return factories[policy_id]()
    except KeyError as error:
        raise ValueError(f"Unsupported E1–E3 admission policy: {policy_id}") from error
