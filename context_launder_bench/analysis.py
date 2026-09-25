from __future__ import annotations

import csv
import json
from pathlib import Path
from .model import DiscontinuityKind, DiscontinuityRecord, RunResult

AUTH_FIELDS = ("source", "task", "branch", "purpose", "epoch", "approval_binding")
OBSERVED_FIELDS = AUTH_FIELDS + ("tool_allowlist", "executor_capability")


def classify_result(result: RunResult) -> tuple[DiscontinuityRecord, ...]:
    """Classify only facts supported by runtime events and native value mapping."""
    events = tuple(result.events)
    by_kind: dict[str, list] = {}
    for item in events:
        by_kind.setdefault(item.kind, []).append(item)
    derive_parents = {
        dict(item.data)["output_id"]: tuple(dict(item.data)["input_ids"])
        for item in by_kind.get("Derive", ())
    }
    native_value_ids = set(result.native_mapping.values())

    def witnessed_path(before: str, after: str) -> bool:
        visited: set[str] = set()

        def walk(value_id: str) -> bool:
            if value_id == before:
                return True
            if value_id in visited:
                return False
            visited.add(value_id)
            return any(walk(parent) for parent in derive_parents.get(value_id, ()))

        return walk(after)

    def read_witness(value_id: str):
        visited: set[str] = set()

        def walk(current: str):
            if current in visited:
                return None
            visited.add(current)
            for item in by_kind.get("Read", ()):
                if dict(item.data).get("value_id") == current:
                    return item
            for parent in derive_parents.get(current, ()):
                found = walk(parent)
                if found is not None:
                    return found
            return None

        return walk(value_id)

    policy_event = next(iter(by_kind.get("PolicyDecision", ())), None)
    enforced: set[str] = set()
    if policy_event is not None:
        from .policies import GroundTruthEnforcingPolicy, policy_from_id
        policy_id = dict(policy_event.data)["admission_policy"]
        policy = (GroundTruthEnforcingPolicy() if policy_id ==
                  GroundTruthEnforcingPolicy.policy_id
                  else policy_from_id(policy_id))
        enforced = set(policy.enforced_fields)

    records: list[DiscontinuityRecord] = []
    for event in by_kind.get("BoundaryObserve", ()):
        data = dict(event.data)
        boundary = data["boundary"]
        before = data["value_id_before"]
        after = data["value_id_after"]
        represented: dict[str, tuple[str, ...]] = {}

        if boundary == "endpoint":
            source = read_witness(before)
            if source is not None:
                represented["source"] = (source.event_id,)
            context = next((
                item for item in by_kind.get("TaskStart", ())
                if dict(item.data).get("context_ref") == data.get("context_ref")
            ), None)
            if context is not None:
                for field in ("task", "branch", "purpose", "epoch", "tool_allowlist"):
                    represented[field] = (context.event_id,)
            spec = next(iter(by_kind.get("AuthorizationSpecBound", ())), None)
            if spec is not None:
                represented["approval_binding"] = (spec.event_id,)
            prepare = next(iter(by_kind.get("ToolPrepare", ())), None)
            if prepare is not None:
                represented["executor_capability"] = (prepare.event_id,)
        elif boundary == "task-switch":
            switch = next(iter(by_kind.get("TaskSwitch", ())), None)
            if switch is not None:
                represented["task"] = (switch.event_id,)

        for field in OBSERVED_FIELDS:
            supports = represented.get(field, ())
            kind = (
                DiscontinuityKind.UNREPRESENTED if not supports else
                DiscontinuityKind.PRESERVED_AND_ENFORCED
                if boundary == "endpoint" and field in enforced
                else DiscontinuityKind.PRESENT_BUT_UNENFORCED
            )
            evidence = (event.event_id,) + supports
            if kind is DiscontinuityKind.PRESERVED_AND_ENFORCED and policy_event:
                evidence += (policy_event.event_id,)
            records.append(DiscontinuityRecord(
                result.scenario_id, result.framework, boundary,
                before, after, field, kind, event.event_id, True,
                tuple(dict.fromkeys(evidence)),
            ))

        if boundary == "message" and by_kind.get("AgentText"):
            agent_text = by_kind["AgentText"][0]
            records.append(DiscontinuityRecord(
                result.scenario_id, result.framework, boundary,
                before, after, "agent_self_declared_metadata",
                DiscontinuityKind.PRESENT_BUT_UNENFORCED,
                event.event_id, False, (event.event_id, agent_text.event_id),
            ))

        lineage_kind = None
        if after is None:
            lineage_kind = DiscontinuityKind.DROPPED
        elif before != after and not witnessed_path(before, after):
            # Native mapping can corroborate the after-value. A value ID alone
            # never supplies a missing Derive witness.
            lineage_kind = DiscontinuityKind.TRANSFORMED_WITHOUT_WITNESS
        if lineage_kind is not None:
            evidence = [event.event_id]
            if after in native_value_ids:
                evidence.extend(item.event_id for item in by_kind.get("Derive", ())
                                if dict(item.data).get("output_id") == after)
            records.append(DiscontinuityRecord(
                result.scenario_id, result.framework, boundary,
                before, after, "value_lineage", lineage_kind,
                event.event_id, True, tuple(dict.fromkeys(evidence)),
            ))
    return tuple(records)

def export_boundaries(results, output_dir):
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    rows = [{**r.__dict__, "kind": r.kind.value,
             "evidence_refs": list(r.evidence_refs)}
            for result in results for r in result.discontinuities]
    jpath = root / "discontinuities.json"
    cpath = root / "discontinuities.csv"
    mpath = root / "boundary_matrix.md"
    jpath.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    with cpath.open("w", newline="", encoding="utf-8") as handle:
        fields = ("run_id", "framework", "boundary", "value_id_before",
                  "value_id_after", "field_or_relation", "kind", "first_event_id",
                  "affects_authorization", "evidence_refs")
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "evidence_refs": ";".join(row["evidence_refs"])})
    matrix = {}
    evidence = {}
    for row in rows:
        key = (row["framework"], row["run_id"], row["boundary"])
        matrix.setdefault(key, {})[row["field_or_relation"]] = row["kind"]
        evidence.setdefault(key, []).extend(row["evidence_refs"])
    lines = [
        "# Boundary matrix", "",
        "Each cell uses one of the five discontinuity kinds. Trace IDs resolve in results.json.", "",
        "| Framework | Run | Boundary | Source | Task | Branch | Purpose | Epoch | Approval binding | Enforcement | Trace evidence |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, values in sorted(matrix.items()):
        framework, run_id, boundary = key
        cells = [values.get(field, DiscontinuityKind.UNREPRESENTED.value) for field in AUTH_FIELDS]
        enforcement = (
            DiscontinuityKind.PRESERVED_AND_ENFORCED.value
            if any(value == DiscontinuityKind.PRESERVED_AND_ENFORCED.value
                   for value in values.values())
            else DiscontinuityKind.PRESENT_BUT_UNENFORCED.value
        )
        refs = ",".join(dict.fromkeys(evidence[key]))
        lineage = values.get("value_lineage", "-")
        lines.append("| " + " | ".join([framework, run_id, boundary] + cells +
                                     [lineage, enforcement, refs]) + " |")
    mpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jpath, cpath, mpath
