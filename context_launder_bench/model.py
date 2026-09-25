from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class DiscontinuityKind(str, Enum):
    UNREPRESENTED = "unrepresented"
    DROPPED = "dropped"
    TRANSFORMED_WITHOUT_WITNESS = "transformed_without_witness"
    PRESENT_BUT_UNENFORCED = "present_but_unenforced"
    PRESERVED_AND_ENFORCED = "preserved_and_enforced"


@dataclass(frozen=True)
class TrustedAuthorizationContext:
    principal: str
    task_id: str
    branch_id: str
    purpose: str
    epoch: int
    allowed_sinks: frozenset[str]


@dataclass(frozen=True)
class BusinessValue:
    value_id: str
    payload: Any


@dataclass(frozen=True)
class RuntimeEnvelope:
    value_id: str
    context_ref: str
    provenance_ref: str


@dataclass(frozen=True)
class ToolRequest:
    tool_name: str
    arguments: Mapping[str, Any]
    executor_id: str
    capability_id: str
    callsite_id: str
    runtime_context_ref: str
    value_id: str


@dataclass(frozen=True)
class AuthorizedActionSpec:
    """Trusted rule for real tool requests, independent of scripted arguments."""

    tool_name: str
    allowed_arguments: Mapping[str, tuple[Any, ...]]

    @classmethod
    def exact(cls, tool_name: str, arguments: Mapping[str, Any]) -> "AuthorizedActionSpec":
        return cls(tool_name, {key: (value,) for key, value in arguments.items()})

    def permits(self, request: ToolRequest) -> bool:
        return (
            request.tool_name == self.tool_name
            and set(request.arguments) == set(self.allowed_arguments)
            and all(
                any(canonical(request.arguments[key]) == canonical(allowed)
                    for allowed in choices)
                for key, choices in self.allowed_arguments.items()
            )
        )

    def binding_digest(self) -> str:
        return digest({
            "tool_name": self.tool_name,
            "allowed_arguments": self.allowed_arguments,
        })


@dataclass(frozen=True)
class Event:
    event_id: str
    kind: str
    data: tuple[tuple[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "kind": self.kind, "data": dict(self.data)}


@dataclass(frozen=True)
class DiscontinuityRecord:
    run_id: str
    framework: str
    boundary: str
    value_id_before: str
    value_id_after: str | None
    field_or_relation: str
    kind: DiscontinuityKind
    first_event_id: str
    affects_authorization: bool
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    template_id: str
    family: str
    channel: str
    legal: bool
    arguments: Mapping[str, Any]
    tool_name: str
    executor_id: str = "executor-main"
    capability_id: str = "cap-main"
    callsite_id: str = "terminal-callsite"
    framework_configuration: str = "scripted-default"
    scheduler_template: str = "deterministic"
    variant: str = "base"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    task_text: str = ""
    authorized_action_spec: AuthorizedActionSpec | None = None

    def terminal_signature(self) -> tuple[Any, ...]:
        return (
            self.tool_name, canonical(self.arguments), self.executor_id,
            self.capability_id, self.callsite_id,
            self.framework_configuration, self.scheduler_template,
        )


@dataclass(frozen=True)
class RunResult:
    scenario_id: str
    framework: str
    admission_policy: str
    admission_decision: Decision | None
    committed: bool
    reason_code: str
    ground_truth_authorized: bool | None
    events: tuple[Event, ...]
    canonical_log_digest: str
    native_mapping: Mapping[str, str] = field(default_factory=dict)
    discontinuities: tuple[DiscontinuityRecord, ...] = ()
    terminal_signature: tuple[Any, ...] = ()
    attempt_status: str = "tool_call"
    tool_name: str | None = None
    tool_arguments: Mapping[str, Any] | None = None
    experiment_metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def unsafe_commit(self) -> bool:
        return self.committed and self.ground_truth_authorized is False

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "framework": self.framework,
            "ground_truth_authorized": self.ground_truth_authorized,
            "admission_policy": self.admission_policy,
            "admission_decision": (self.admission_decision.value
                                   if self.admission_decision is not None else None),
            "committed": self.committed,
            "unsafe_commit": self.unsafe_commit,
            "attempt_status": self.attempt_status,
            "tool_name": self.tool_name,
            "tool_arguments": (dict(self.tool_arguments)
                               if self.tool_arguments is not None else None),
            "reason_code": self.reason_code,
            "terminal_signature": list(self.terminal_signature),
            "canonical_log_digest": self.canonical_log_digest,
            "events": [e.as_dict() for e in self.events],
            "native_mapping": dict(self.native_mapping),
            "experiment_metadata": dict(self.experiment_metadata),
            "discontinuities": [
                {**r.__dict__, "kind": r.kind.value, "evidence_refs": list(r.evidence_refs)}
                for r in self.discontinuities
            ],
        }
