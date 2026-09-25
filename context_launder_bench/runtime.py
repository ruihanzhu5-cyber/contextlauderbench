from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .model import (
    BusinessValue, Event, RuntimeEnvelope, ToolRequest,
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

        self.__events: list[Event] = []
        self.__contexts: dict[str, TrustedAuthorizationContext] = {}
        self.__values: dict[str, BusinessValue] = {}
        self.__envelopes: dict[str, RuntimeEnvelope] = {}
        self.__parents: dict[str, tuple[str, ...]] = {}
        self.__witnesses: dict[str, str] = {}
        self.__sources: dict[str, str] = {}
        self.__endorsements: list[Endorsement] = []
        self.__consumed: set[str] = set()
        self.__epoch: dict[str, int] = {}
        self.__revoked: set[str] = set()
        self.__capabilities: dict[str, tuple[str, frozenset[str]]] = {}
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
        event = Event(f"e{len(self.__events)+1:04d}", kind, tuple(sorted(data.items())))
        self.__events.append(event)
        return event

    def observe_boundary(self, boundary: str, value_id_before: str,
                         value_id_after: str | None, represented_fields=(),
                         enforced_fields=()) -> Event:
        return self.event("BoundaryObserve", boundary=boundary,
                          value_id_before=value_id_before,
                          value_id_after=value_id_after,
                          represented_fields=tuple(represented_fields),
                          enforced_fields=tuple(enforced_fields))

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
                   purpose=purpose, epoch=epoch, branch_id=branch_id)
        return ref

    def context(self, ref: str) -> TrustedAuthorizationContext | None:
        return self.__contexts.get(ref)

    def current_epoch(self, task_id: str) -> int | None:
        return self.__epoch.get(task_id)

    def grant_capability(self, capability_id: str, executor_id: str,
                         tools: Iterable[str]) -> None:
        self.__capabilities[capability_id] = (executor_id, frozenset(tools))

    def capability_valid(self, request: ToolRequest) -> bool:
        cap = self.__capabilities.get(request.capability_id)
        return cap is not None and cap[0] == request.executor_id and request.tool_name in cap[1]

    def seed_value(self, payload: Any, source: str, context_ref: str) -> RuntimeEnvelope:
        if context_ref not in self.__contexts:
            raise ValueError("Unknown trusted context")
        self.__value_counter += 1
        value_id = f"v{self.__value_counter:04d}"
        value = BusinessValue(value_id, payload)
        self.__values[value_id] = value
        self.__sources[value_id] = source
        read = self.event("Read", source=source, value_id=value_id, payload_digest=digest(payload))
        env = RuntimeEnvelope(value_id, context_ref, read.event_id)
        self.__envelopes[value_id] = env
        self.__parents[value_id] = ()
        self.__witnesses[value_id] = read.event_id
        return env

    def derive(self, input_ids: Iterable[str], payload: Any, transform_id: str,
               context_ref: str) -> RuntimeEnvelope:
        parents = tuple(input_ids)
        if not parents or any(p not in self.__values for p in parents):
            raise ValueError("Missing input value")
        if context_ref not in self.__contexts:
            raise ValueError("Unknown trusted context")
        self.__value_counter += 1
        value_id = f"v{self.__value_counter:04d}"
        self.__values[value_id] = BusinessValue(value_id, payload)
        event = self.event("Derive", output_id=value_id, input_ids=parents,
                           transform_id=transform_id, payload_digest=digest(payload))
        env = RuntimeEnvelope(value_id, context_ref, event.event_id)
        self.__envelopes[value_id] = env
        self.__parents[value_id] = parents
        self.__witnesses[value_id] = event.event_id
        return env

    def send(self, sender: str, receiver: str, value_id: str) -> Event:
        self._require_value(value_id)
        event = self.event("Send", sender=sender, receiver=receiver, value_id=value_id)
        self.observe_boundary("message", value_id, value_id, represented_fields=("agent_self_declared_metadata",))
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
        action = digest({"tool": request.tool_name, "arguments": request.arguments})
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
        return self.__values.get(value_id)

    def envelope(self, value_id: str) -> RuntimeEnvelope | None:
        return self.__envelopes.get(value_id)

    def provenance_valid(self, value_id: str) -> bool:
        seen: set[str] = set()
        def check(v: str) -> bool:
            if v in seen or v not in self.__values or v not in self.__parents:
                return False
            seen.add(v)
            witness = self.__witnesses.get(v)
            if witness is None or not any(e.event_id == witness for e in self.__events):
                return False
            parents = self.__parents[v]
            if parents and not any(e.kind == "Derive" and
                dict(e.data).get("output_id") == v and
                tuple(dict(e.data).get("input_ids", ())) == parents for e in self.__events):
                return False
            return all(check(p) for p in parents)
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

    def make_request(self, tool_name: str, arguments: Mapping[str, Any],
                     executor_id: str, capability_id: str, callsite_id: str,
                     context_ref: str, value_id: str) -> ToolRequest:
        return ToolRequest(tool_name, dict(arguments), executor_id, capability_id,
                           callsite_id, context_ref, value_id)

    def _corrupt_provenance_for_test(self, value_id: str) -> None:
        """Mutation-test hook; never used by runner or adapter."""
        self.__witnesses.pop(value_id, None)
