from __future__ import annotations

from copy import deepcopy
from threading import RLock
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .model import (
    ApprovalRecord, AuthorizedActionSpec, BusinessValue, Event, RuntimeEnvelope, ToolRequest,
    TrustedAuthorizationContext, canonical, digest,
)


@dataclass(frozen=True)
class Endorsement:
    principal: str
    action_digest: str
    task_id: str
    scope: str
    epoch: int
    nonce: str
    event_id: str


class TrustedRuntime:
    """Trusted, deterministic ledger. Agent payload cannot mint any ledger fact."""

    def __init__(self, run_id: str, scenario_family: str):
        self.run_id = run_id
        self.__scenario_family = scenario_family

        self.__lock = RLock()
        self.__events: list[Event] = []
        self.__contexts: dict[str, TrustedAuthorizationContext] = {}
        self.__values: dict[str, BusinessValue] = {}
        self.__envelopes: dict[str, RuntimeEnvelope] = {}
        self.__parents: dict[str, tuple[str, ...]] = {}
        self.__transforms: dict[str, str | None] = {}
        self.__witnesses: dict[str, str] = {}
        self.__sources: dict[str, str] = {}
        self.__endorsements: list[Endorsement] = []
        self.__consumed: set[str] = set()
        self.__epoch: dict[str, int] = {}
        self.__revoked: set[str] = set()
        self.__capabilities: dict[str, tuple[str, frozenset[str]]] = {}
        self.__authorized_action_spec: AuthorizedActionSpec | None = None
        self.__issuer_authority: dict[str, dict[str, frozenset[str]]] = {}
        self.__approvals: dict[str, ApprovalRecord] = {}
        self.__approval_version = 0
        self.__memory: dict[str, str] = {}
        self.__value_counter = 0
        self.__context_counter = 0

    @property
    def scenario_family(self) -> str:
        return self.__scenario_family

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self.__events)

    def event(self, kind: str, **data: Any) -> Event:
        with self.__lock:
            event = Event(f"e{len(self.__events)+1:04d}",
                          kind, tuple(sorted(data.items())))
            self.__events.append(event)
            return event

    def observe_boundary(self, boundary: str, value_id_before: str,
                         value_id_after: str | None, represented_fields=(),
                         enforced_fields=(), context_ref: str | None = None) -> Event:
        return self.event("BoundaryObserve", boundary=boundary,
                          value_id_before=value_id_before,
                          value_id_after=value_id_after,
                          represented_fields=tuple(represented_fields),
                          enforced_fields=tuple(enforced_fields),
                          context_ref=context_ref)

    def canonical_log_digest(self) -> str:
        return digest([event.as_dict() for event in self.__events])

    def begin_task(self, principal: str, task_id: str, branch_id: str,
                   purpose: str, epoch: int, allowed_sinks: Iterable[str]) -> str:
        self.__context_counter += 1
        ref = f"c{self.__context_counter:04d}"
        self.__contexts[ref] = TrustedAuthorizationContext(
            principal, task_id, branch_id, purpose, epoch, frozenset(allowed_sinks)
        )
        self.__epoch.setdefault(task_id, epoch)
        self.event("TaskStart", task_id=task_id, principal=principal,
                   purpose=purpose, epoch=epoch, branch_id=branch_id,
                   context_ref=ref, allowed_sinks=tuple(sorted(allowed_sinks)))
        return ref

    def context(self, ref: str) -> TrustedAuthorizationContext | None:
        return self.__contexts.get(ref)

    def current_epoch(self, task_id: str) -> int | None:
        return self.__epoch.get(task_id)

    def bind_authorized_action(self, spec: AuthorizedActionSpec) -> None:
        if self.__authorized_action_spec is not None:
            raise ValueError("Authorized action already bound")
        self.__authorized_action_spec = spec
        self.event("AuthorizationSpecBound", spec_digest=spec.binding_digest())

    @property
    def authorized_action_spec(self) -> AuthorizedActionSpec | None:
        return self.__authorized_action_spec

    def grant_issuer_authority(
        self, issuer: str, tool_resources: Mapping[str, Iterable[str]]
    ) -> None:
        granted = {tool: frozenset(resources)
                   for tool, resources in tool_resources.items()}
        self.__issuer_authority[issuer] = granted
        self.__approval_version += 1
        self.event("IssuerAuthorityGrant", issuer=issuer,
                   tool_resources={tool: tuple(sorted(resources))
                                   for tool, resources in granted.items()},
                   ledger_version=self.__approval_version)

    def register_approval(self, record: ApprovalRecord) -> None:
        if record.approval_id in self.__approvals:
            raise ValueError("Duplicate approval ID")
        self.__approvals[record.approval_id] = deepcopy(record)
        self.__approval_version += 1
        self.event("ApprovalRegistered",
                   approval_id=record.approval_id,
                   issuer=record.issuer, executor=record.executor_id,
                   task_id=record.task_id,
                   action_digest=record.action_spec.binding_digest(),
                   active=record.active,
                   ledger_version=self.__approval_version)

    @property
    def has_approval_ledger(self) -> bool:
        return bool(self.__approvals)

    def approval_record(self, approval_id: str) -> ApprovalRecord | None:
        record = self.__approvals.get(approval_id)
        return deepcopy(record) if record is not None else None

    def approval_records(self) -> tuple[ApprovalRecord, ...]:
        return tuple(deepcopy(self.__approvals[key])
                     for key in sorted(self.__approvals))

    def approval_relation(self, request: ToolRequest) -> dict[str, Any]:
        """Read-only, uniform relation for the stateful workflow."""
        record = self.__approvals.get(request.approval_ref or "")
        context = self.context(request.runtime_context_ref)
        proposal_value = self.value(request.value_id)
        payload = proposal_value.payload if proposal_value else None
        parents = self.parents(request.value_id) or ()
        joined_value = self.value(parents[0]) if len(parents) == 1 else None
        joined_payload = joined_value.payload if joined_value else None
        join_ref_match = (
            isinstance(joined_payload, Mapping)
            and joined_payload.get("approval_ref") == request.approval_ref
        )
        joined_parents = self.parents(joined_value.value_id) if joined_value else None
        approval_parent = (
            self.value(joined_parents[1])
            if joined_parents is not None and len(joined_parents) == 2
            else None
        )
        approval_items = approval_parent.payload if approval_parent else None
        approval_branch_match = bool(
            record and joined_value
            and self.transform(joined_value.value_id) in {"join", "identity-transport"}
            and joined_parents is not None and len(joined_parents) == 2
            and self.source(joined_parents[1]) == "trusted_approval_ledger"
            and isinstance(approval_items, list)
            and isinstance(joined_payload, Mapping)
            and isinstance(joined_payload.get("approval_record"), Mapping)
            and any(
                isinstance(item, Mapping)
                and item.get("approval_id") == request.approval_ref
                and item.get("issuer") == record.issuer
                and item.get("executor_id") == record.executor_id
                and item.get("task_id") == record.task_id
                and item.get("active") == record.active
                and item.get("action_digest") == record.action_spec.binding_digest()
                and canonical(item) == canonical(joined_payload["approval_record"])
                for item in approval_items
            )
        )
        linked = (
            isinstance(payload, Mapping)
            and payload.get("approval_ref") == request.approval_ref
            and payload.get("tool_name") == request.tool_name
            and canonical(payload.get("arguments")) == canonical(request.arguments)
        )
        facts = {
            "ledger_version": self.__approval_version,
            "approval_ref": request.approval_ref,
            "approval_exists": record is not None,
            "approval_id": record.approval_id if record else None,
            "issuer": record.issuer if record else None,
            "approved_executor_id": record.executor_id if record else None,
            "approved_task_id": record.task_id if record else None,
            "approved_tool_name": record.action_spec.tool_name if record else None,
            "approved_arguments": (
                {key: choices[0] for key, choices in
                 record.action_spec.allowed_arguments.items()}
                if record and all(len(choices) == 1 for choices in
                                  record.action_spec.allowed_arguments.values())
                else None
            ),
            "issuer_allowed_resources": tuple(sorted(
                self.__issuer_authority.get(record.issuer, {}).get(
                    record.action_spec.tool_name, frozenset()
                ))) if record else (),
            "issuer_authorized": bool(
                record and isinstance(request.arguments.get("account"), str)
                and request.arguments.get("account") in
                self.__issuer_authority.get(record.issuer, {}).get(
                    record.action_spec.tool_name, frozenset())),
            "executor_match": bool(record and
                                   record.executor_id == request.executor_id),
            "task_match": bool(record and context and
                               record.task_id == context.task_id),
            "action_match": bool(record and record.action_spec.permits(request)),
            "active": bool(record and record.active),
            "request_linked": linked,
            "join_ref_match": join_ref_match,
            "approval_branch_match": approval_branch_match,
            "record_digest": digest({
                "approval_id": record.approval_id,
                "issuer": record.issuer,
                "executor": record.executor_id,
                "task": record.task_id,
                "action": record.action_spec.binding_digest(),
                "active": record.active,
            }) if record else None,
        }
        facts["matched"] = all((
            facts["approval_exists"], facts["issuer_authorized"],
            facts["executor_match"], facts["task_match"],
            facts["action_match"], facts["active"], facts["request_linked"],
            facts["join_ref_match"], facts["approval_branch_match"],
        ))
        return facts

    def grant_capability(self, capability_id: str, executor_id: str,
                         tools: Iterable[str]) -> None:
        self.__capabilities[capability_id] = (executor_id, frozenset(tools))

    def capability_valid(self, request: ToolRequest) -> bool:
        cap = self.__capabilities.get(request.capability_id)
        return cap is not None and cap[0] == request.executor_id and request.tool_name in cap[1]

    def seed_value(self, payload: Any, source: str, context_ref: str) -> RuntimeEnvelope:
        with self.__lock:
            return self._seed_value_locked(payload, source, context_ref)

    def _seed_value_locked(self, payload: Any, source: str,
                           context_ref: str) -> RuntimeEnvelope:
        if context_ref not in self.__contexts:
            raise ValueError("Unknown trusted context")
        self.__value_counter += 1
        value_id = f"v{self.__value_counter:04d}"
        value = BusinessValue(value_id, deepcopy(payload))
        self.__values[value_id] = value
        self.__sources[value_id] = source
        read = self.event("Read", source=source, value_id=value_id, payload_digest=digest(value.payload))
        env = RuntimeEnvelope(value_id, context_ref, read.event_id)
        self.__envelopes[value_id] = env
        self.__parents[value_id] = ()
        self.__transforms[value_id] = None
        self.__witnesses[value_id] = read.event_id
        return env

    def derive(self, input_ids: Iterable[str], payload: Any, transform_id: str,
               context_ref: str) -> RuntimeEnvelope:
        with self.__lock:
            return self._derive_locked(input_ids, payload, transform_id, context_ref)

    def _derive_locked(self, input_ids: Iterable[str], payload: Any, transform_id: str,
               context_ref: str) -> RuntimeEnvelope:
        parents = tuple(input_ids)
        if not parents or any(p not in self.__values for p in parents):
            raise ValueError("Missing input value")
        if context_ref not in self.__contexts:
            raise ValueError("Unknown trusted context")
        self.__value_counter += 1
        value_id = f"v{self.__value_counter:04d}"
        self.__values[value_id] = BusinessValue(value_id, deepcopy(payload))
        event = self.event("Derive", output_id=value_id, input_ids=parents,
                           transform_id=transform_id,
                           payload_digest=digest(self.__values[value_id].payload))
        env = RuntimeEnvelope(value_id, context_ref, event.event_id)
        self.__envelopes[value_id] = env
        self.__parents[value_id] = parents
        self.__transforms[value_id] = transform_id
        self.__witnesses[value_id] = event.event_id
        return env

    def send(self, sender: str, receiver: str, value_id: str) -> Event:
        self._require_value(value_id)
        event = self.event("Send", sender=sender, receiver=receiver, value_id=value_id)
        self.observe_boundary("message", value_id, value_id)
        return event

    def spawn(self, parent: str, child: str, branch_id: str) -> Event:
        return self.event("Spawn", parent=parent, child=child, branch_id=branch_id)

    def memory_write(self, key: str, value_id: str) -> Event:
        self._require_value(value_id)
        self.__memory[key] = value_id
        event = self.event("MemoryWrite", key=key, value_id=value_id)
        self.observe_boundary("memory", value_id, value_id)
        return event

    def memory_read(self, key: str) -> str:
        value_id = self.__memory[key]
        self.event("MemoryRead", key=key, value_id=value_id)
        self.observe_boundary("memory", value_id, value_id)
        return value_id

    def join(self, joiner: str, input_ids: Iterable[str], payload: Any,
             context_ref: str) -> RuntimeEnvelope:
        parents = tuple(input_ids)
        result = self.derive(parents, payload, "join", context_ref)
        self.event("Join", joiner=joiner, input_ids=parents, output_id=result.value_id)
        return result

    def endorse(self, principal: str, action_digest: str, task_id: str,
                scope: str, epoch: int) -> Endorsement:
        nonce = f"n{len(self.__endorsements)+1:04d}"
        event = self.event("Endorse", principal=principal, action_digest=action_digest,
                           scope=scope, epoch=epoch, nonce=nonce, task_id=task_id)
        item = Endorsement(principal, action_digest, task_id, scope, epoch, nonce, event.event_id)
        self.__endorsements.append(item)
        return item

    def valid_endorsement(self, request: ToolRequest, scope: str) -> Endorsement | None:
        context = self.context(request.runtime_context_ref)
        if context is None or scope in self.__revoked:
            return None
        spec = self.__authorized_action_spec
        if spec is None or not spec.permits(request):
            return None
        action = spec.binding_digest()
        for item in reversed(self.__endorsements):
            if (item.principal == context.principal and item.task_id == context.task_id
                    and item.epoch == context.epoch and item.scope == scope
                    and item.action_digest == action and item.nonce not in self.__consumed):
                return item
        return None

    def consume_endorsement(self, nonce: str) -> None:
        if nonce in self.__consumed:
            raise ValueError("Endorsement already consumed")
        if not any(item.nonce == nonce for item in self.__endorsements):
            raise ValueError("Unknown endorsement")
        self.__consumed.add(nonce)

    def revoke(self, scope: str) -> None:
        self.__revoked.add(scope)
        self.event("Revoke", scope=scope)

    def advance_epoch(self, task_id: str, scope: str) -> int:
        self.__epoch[task_id] = self.__epoch.get(task_id, 0) + 1
        self.__revoked.discard(scope)
        self.event("AdvanceEpoch", scope=scope, task_id=task_id, epoch=self.__epoch[task_id])
        return self.__epoch[task_id]

    def _require_value(self, value_id: str) -> None:
        if value_id not in self.__values:
            raise ValueError("Unknown value")

    def value(self, value_id: str) -> BusinessValue | None:
        value = self.__values.get(value_id)
        return BusinessValue(value.value_id, deepcopy(value.payload)) if value else None

    def envelope(self, value_id: str) -> RuntimeEnvelope | None:
        return self.__envelopes.get(value_id)

    def provenance_valid(self, value_id: str) -> bool:
        # A shared ancestor is valid in a DAG; only a node on the active
        # recursion path indicates a cycle.
        memo: dict[str, bool] = {}
        active: set[str] = set()
        event_by_id = {event.event_id: event for event in self.__events}

        def check(current: str) -> bool:
            if current in memo:
                return memo[current]
            if current in active or current not in self.__values:
                return False
            parents = self.__parents.get(current)
            if parents is None:
                return False
            witness = event_by_id.get(self.__witnesses.get(current, ""))
            if witness is None or dict(witness.data).get("payload_digest") != digest(
                self.__values[current].payload
            ):
                memo[current] = False
                return False
            if parents and not (
                witness.kind == "Derive"
                and dict(witness.data).get("output_id") == current
                and tuple(dict(witness.data).get("input_ids", ())) == parents
            ):
                memo[current] = False
                return False
            active.add(current)
            valid = all(check(parent) for parent in parents)
            active.remove(current)
            memo[current] = valid
            return valid

        return check(value_id)

    def roots(self, value_id: str) -> tuple[str, ...]:
        result: list[str] = []
        def walk(v: str) -> None:
            if v not in self.__parents:
                return
            if not self.__parents[v]:
                result.append(v)
            else:
                for p in self.__parents[v]:
                    walk(p)
        walk(value_id)
        return tuple(result)

    def source(self, value_id: str) -> str | None:
        return self.__sources.get(value_id)

    def parents(self, value_id: str) -> tuple[str, ...] | None:
        return self.__parents.get(value_id)

    def transform(self, value_id: str) -> str | None:
        return self.__transforms.get(value_id)

    def has_join_ancestor(self, value_id: str) -> bool:
        if self.__transforms.get(value_id) == "join":
            return len(self.__parents.get(value_id, ())) == 2
        return any(self.has_join_ancestor(parent)
                   for parent in self.__parents.get(value_id, ()))


    def make_request(self, tool_name: str, arguments: Mapping[str, Any],
                     executor_id: str, capability_id: str, callsite_id: str,
                     context_ref: str, value_id: str,
                     approval_ref: str | None = None) -> ToolRequest:
        return ToolRequest(tool_name, deepcopy(dict(arguments)), executor_id, capability_id,
                           callsite_id, context_ref, value_id, approval_ref)

    def _corrupt_provenance_for_test(self, value_id: str) -> None:
        """Mutation-test hook; never used by runner or adapter."""
        self.__witnesses.pop(value_id, None)
