from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .model import Decision, ToolRequest, digest
from .policies import AdmissionPolicy
from .runtime import TrustedRuntime


@dataclass(frozen=True)
class EndpointOutcome:
    admission_policy: str
    admission_decision: Decision
    committed: bool
    reason_code: str
    effect_id: str | None
    receipt: Mapping[str, Any] | None = None


class UnifiedMockEndpoint:
    """The only mock-effect writer. It follows AdmissionPolicy, never ground truth."""

    def __init__(self, runtime: TrustedRuntime, admission_policy: AdmissionPolicy,
                 effect_writer: Callable[[ToolRequest, str],
                                         Mapping[str, Any]] | None = None):
        self.__runtime = runtime
        self.__policy = admission_policy
        self.__effect_writer = effect_writer
        self.__effects: list[tuple[str, str, str]] = []
        self.__secret = object()
        self.__live_tokens: set[object] = set()
        self.__last_token: object | None = None

    @property
    def effects(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(self.__effects)

    @property
    def admission_policy_id(self) -> str:
        return self.__policy.policy_id

    def invoke(self, request: ToolRequest) -> EndpointOutcome:
        token = object()
        self.__live_tokens.add(token)
        self.__last_token = token
        self.__runtime.observe_boundary(
            "endpoint", request.value_id, request.value_id,
            context_ref=request.runtime_context_ref,
        )
        prepare = {
            "tool": request.tool_name,
            "args_digest": digest(request.arguments),
            "executor": request.executor_id,
            "callsite": request.callsite_id,
            "capability": request.capability_id,
        }
        if request.approval_ref is not None:
            prepare["approval_ref"] = request.approval_ref
        self.__runtime.event("ToolPrepare", **prepare)
        admission = self.__policy.decide(self.__runtime, request)
        self.__runtime.event(
            "PolicyDecision", admission_policy=self.__policy.policy_id,
            decision=admission.decision.value, reason_code=admission.reason_code,
        )
        if admission.decision is Decision.DENY:
            self.__live_tokens.discard(token)
            self.__runtime.event("ToolReject", reason_code=admission.reason_code)
            return EndpointOutcome(
                self.__policy.policy_id, admission.decision, False,
                admission.reason_code, None,
            )
        effect_id, receipt = self.__commit(token, self.__secret, request)
        return EndpointOutcome(
            self.__policy.policy_id, admission.decision, True,
            admission.reason_code, effect_id, receipt,
        )

    def __commit(self, token: object, secret: object,
                 request: ToolRequest) -> tuple[str, Mapping[str, Any] | None]:
        if secret is not self.__secret or token not in self.__live_tokens:
            raise PermissionError("No live admitted prepare token")
        self.__live_tokens.remove(token)
        effect_id = f"effect-{len(self.__effects)+1:04d}"
        receipt = (self.__effect_writer(request, effect_id)
                   if self.__effect_writer is not None else None)
        self.__effects.append((effect_id, request.tool_name, digest(request.arguments)))
        if receipt is not None:
            self.__runtime.event(
                "BusinessStateChanged", effect_id=effect_id,
                receipt_id=receipt["receipt_id"],
                state_diff=receipt["state_diff"],
            )
            self.__runtime.event(
                "ToolCommit", effect_id=effect_id,
                receipt_id=receipt["receipt_id"],
            )
        else:
            self.__runtime.event("ToolCommit", effect_id=effect_id)
        return effect_id, receipt

    def _bypass_attempt_for_test(self, request: ToolRequest) -> None:
        self.__commit(object(), object(), request)

    def _replay_attempt_for_test(self, request: ToolRequest) -> None:
        self.__commit(self.__last_token, self.__secret, request)
