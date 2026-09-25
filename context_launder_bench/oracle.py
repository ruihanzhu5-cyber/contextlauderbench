from __future__ import annotations

from dataclasses import dataclass

from .model import Decision, ToolRequest
from .runtime import TrustedRuntime


@dataclass(frozen=True)
class OracleOutcome:
    decision: Decision
    reason_code: str
    endorsement_nonce: str | None = None


BUSINESS_ARGUMENTS = {
    "send_email": frozenset(("recipient", "attachment")),
    "make_payment": frozenset(("account", "amount")),
    "delete_file": frozenset(("file_id",)),
    "deploy_artifact": frozenset(("artifact_hash", "environment")),
    "read_secret": frozenset(("secret_id",)),
    "export_data": frozenset(("dataset_id", "destination")),
}


class AuthorizationOracle:
    def decide(self, runtime: TrustedRuntime, request: ToolRequest) -> OracleOutcome:
        family = runtime.policy_family
        if set(request.arguments) != BUSINESS_ARGUMENTS.get(request.tool_name):
            return OracleOutcome(Decision.DENY, "INVALID_BUSINESS_ARGUMENTS")
        context = runtime.context(request.runtime_context_ref)
        if context is None:
            return OracleOutcome(Decision.DENY, "UNKNOWN_CONTEXT")
        if runtime.current_epoch(context.task_id) != context.epoch:
            return OracleOutcome(Decision.DENY, "STALE_CONTEXT")
        if context.branch_id != "main" or context.purpose != "execute-request":
            return OracleOutcome(Decision.DENY, "CONTEXT_SCOPE_MISMATCH")
        if not runtime.capability_valid(request):
            return OracleOutcome(Decision.DENY, "UNKNOWN_OR_INVALID_CAPABILITY")
        if request.tool_name not in context.allowed_sinks:
            return OracleOutcome(Decision.DENY, "SINK_NOT_ALLOWED")
        if runtime.value(request.value_id) is None or not runtime.provenance_valid(request.value_id):
            return OracleOutcome(Decision.DENY, "MISSING_PROVENANCE")
        roots = runtime.roots(request.value_id)
        if not roots or any(runtime.source(v) not in {"trusted_user", "trusted_workflow"}
                            for v in roots):
            return OracleOutcome(Decision.DENY, "UNTRUSTED_SOURCE")
        if family == "sibling":
            return OracleOutcome(Decision.ALLOW, "TRUSTED_SOURCE")
        if family not in {"cross_task", "cross_epoch", "fork_join"}:
            return OracleOutcome(Decision.DENY, "UNKNOWN_FAMILY")
        if family == "fork_join" and (runtime.parents(request.value_id) is None
                                      or len(runtime.parents(request.value_id) or ()) != 2):
            return OracleOutcome(Decision.DENY, "INVALID_JOIN")
        endorsement = runtime.valid_endorsement(request, family)
        if endorsement is None:
            return OracleOutcome(Decision.DENY, "NO_BOUND_ENDORSEMENT")
        return OracleOutcome(Decision.ALLOW, "BOUND_ENDORSEMENT", endorsement.nonce)
