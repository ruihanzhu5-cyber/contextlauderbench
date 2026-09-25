from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model import Decision, ToolRequest, digest
from .oracle import AuthorizationOracle
from .runtime import TrustedRuntime


@dataclass(frozen=True)
class EndpointOutcome:
    decision: Decision
    committed: bool
    reason_code: str
    effect_id: str | None


class UnifiedMockEndpoint:
    """Only writer of mock effects. Prepare tokens are live for one decision only."""

    def __init__(self, runtime: TrustedRuntime, oracle: AuthorizationOracle):
        self.__runtime = runtime
        self.__oracle = oracle
        self.__effects: list[tuple[str, str, str]] = []
        self.__secret = object()
        self.__live_tokens: set[object] = set()
        self.__last_token: object | None = None

    @property
    def effects(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(self.__effects)

    def invoke(self, request: ToolRequest, family: str) -> EndpointOutcome:
        token = object()
        self.__live_tokens.add(token)
        self.__last_token = token
        args_digest = digest(request.arguments)
        represented = ("source", "task", "branch", "purpose", "epoch", "approval_binding")
        self.__runtime.observe_boundary("endpoint", request.value_id, request.value_id,
            represented_fields=represented,
            enforced_fields=represented if self.__runtime.policy_family != "sibling" else represented[:-1])
        self.__runtime.event("ToolPrepare", tool=request.tool_name, args_digest=args_digest,
                             executor=request.executor_id, callsite=request.callsite_id,
                             capability=request.capability_id)
        outcome = self.__oracle.decide(self.__runtime, request)
        self.__runtime.event("PolicyDecision", decision=outcome.decision.value,
                             reason_code=outcome.reason_code)
        if outcome.decision is Decision.DENY:
            self.__live_tokens.discard(token)
            self.__runtime.event("ToolReject", reason_code=outcome.reason_code)
            return EndpointOutcome(outcome.decision, False, outcome.reason_code, None)
        if outcome.endorsement_nonce:
            self.__runtime.consume_endorsement(outcome.endorsement_nonce)
        effect_id = self.__commit(token, self.__secret, request)
        return EndpointOutcome(outcome.decision, True, outcome.reason_code, effect_id)

    def __commit(self, token: object, secret: object, request: ToolRequest) -> str:
        if secret is not self.__secret or token not in self.__live_tokens:
            raise PermissionError("No live authorized prepare token")
        self.__live_tokens.remove(token)
        effect_id = f"effect-{len(self.__effects)+1:04d}"
        self.__effects.append((effect_id, request.tool_name, digest(request.arguments)))
        self.__runtime.event("ToolCommit", effect_id=effect_id)
        return effect_id

    def _bypass_attempt_for_test(self, request: ToolRequest) -> None:
        """Exercise the inaccessible commit gate without making an effect."""
        self.__commit(object(), object(), request)

    def _replay_attempt_for_test(self, request: ToolRequest) -> None:
        self.__commit(self.__last_token, self.__secret, request)
