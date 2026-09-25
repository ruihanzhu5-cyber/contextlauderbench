from __future__ import annotations

import csv
import json
from pathlib import Path

from .model import DiscontinuityKind, DiscontinuityRecord, RunResult

AUTH_FIELDS = ("source", "task", "branch", "purpose", "epoch", "approval_binding")
OBSERVED_FIELDS = AUTH_FIELDS + ("tool_allowlist", "executor_capability", "action_spec")


def classify_result(result: RunResult) -> tuple[DiscontinuityRecord, ...]:
    """Use witnessed runtime/native facts; missing evidence means unobserved."""
    by_kind: dict[str, list] = {}
    for event in result.events:
        by_kind.setdefault(event.kind, []).append(event)
    value_witness = {
        dict(event.data)["value_id"]: event
        for event in by_kind.get("Read", ())
    }
    value_witness.update({
        dict(event.data)["output_id"]: event
        for event in by_kind.get("Derive", ())
    })
    parents = {
        dict(event.data)["output_id"]: tuple(dict(event.data)["input_ids"])
        for event in by_kind.get("Derive", ())
    }
    policy_event = next(iter(by_kind.get("PolicyDecision", ())), None)
    enforced: set[str] = set()
    if policy_event is not None:
        from .policies import GroundTruthEnforcingPolicy, policy_from_id
        policy_id = dict(policy_event.data)["admission_policy"]
        policy = (GroundTruthEnforcingPolicy() if policy_id ==
                  GroundTruthEnforcingPolicy.policy_id
                  else policy_from_id(policy_id))
        enforced = set(policy.enforced_fields)

    def path_witnesses(before: str, after: str) -> tuple[str, ...] | None:
        if before == after:
            return ()
        def walk(current: str, active: frozenset[str]) -> tuple[str, ...] | None:
            if current == before:
                return ()
            if current in active:
                return None
            witness = value_witness.get(current)
            for parent in parents.get(current, ()):
                prior = walk(parent, active | {current})
                if prior is not None and witness is not None:
                    return prior + (witness.event_id,)
            return None

        return walk(after, frozenset())

    def native_refs(before: str, after: str | None) -> tuple[str, ...]:
        return tuple(key for key, value in result.native_mapping.items()
                     if value == before or value == after)

    records: list[DiscontinuityRecord] = []
    for boundary_event in by_kind.get("BoundaryObserve", ()):
        data = dict(boundary_event.data)
        boundary = data["boundary"]
        before = data["value_id_before"]
        after = data["value_id_after"]
        represented: dict[str, tuple[str, ...]] = {}

        if boundary == "endpoint":
            # A value DAG is business lineage, not proof that source authority
            # crossed the native boundary.
            context = next((
                event for event in by_kind.get("TaskStart", ())
                if dict(event.data).get("context_ref") == data.get("context_ref")
            ), None)
            if context is not None:
                for field in ("task", "branch", "purpose", "epoch",
                              "tool_allowlist"):
                    represented[field] = (context.event_id,)
            spec = next(iter(by_kind.get("AuthorizationSpecBound", ())), None)
            if spec is not None:
                represented["action_spec"] = (spec.event_id,)
            prepare = next(iter(by_kind.get("ToolPrepare", ())), None)
            if prepare is not None:
                represented["executor_capability"] = (prepare.event_id,)
        elif boundary == "task-switch":
            switch = next(iter(by_kind.get("TaskSwitch", ())), None)
            if switch is not None:
                represented["task"] = (switch.event_id,)

        native = native_refs(before, after)
        for field in OBSERVED_FIELDS:
            supports = represented.get(field, ())
            kind = (DiscontinuityKind.UNOBSERVED if not supports else
                    DiscontinuityKind.PRESERVED_AND_ENFORCED
                    if boundary == "endpoint" and field in enforced else
                    DiscontinuityKind.PRESENT_BUT_UNENFORCED)
            evidence = (boundary_event.event_id,) + supports
            if kind is DiscontinuityKind.PRESERVED_AND_ENFORCED and policy_event:
                evidence += (policy_event.event_id,)
            records.append(DiscontinuityRecord(
                result.scenario_id, result.framework, boundary, before, after,
                field, kind, boundary_event.event_id, None,
                tuple(dict.fromkeys(evidence)),
                authorization_relevant=True,
                native_refs=native,
            ))

        if boundary == "message" and by_kind.get("AgentText"):
            agent_text = by_kind["AgentText"][0]
            records.append(DiscontinuityRecord(
                result.scenario_id, result.framework, boundary, before, after,
                "agent_self_declared_metadata",
                DiscontinuityKind.PRESENT_BUT_UNENFORCED,
                boundary_event.event_id, None,
                (boundary_event.event_id, agent_text.event_id),
                authorization_relevant=False, native_refs=native,
            ))

        before_witness = value_witness.get(before)
        after_witness = value_witness.get(after) if after is not None else None
        path = (path_witnesses(before, after)
                if after is not None and before_witness and after_witness else None)
        if before_witness is None:
            value_kind = DiscontinuityKind.UNOBSERVED
        elif after is None:
            value_kind = DiscontinuityKind.DROPPED
        elif after_witness is None:
            value_kind = DiscontinuityKind.UNOBSERVED
        elif path is not None:
            value_kind = DiscontinuityKind.PRESERVED
        else:
            value_kind = DiscontinuityKind.TRANSFORMED_WITHOUT_WITNESS
        value_evidence = [boundary_event.event_id]
        if before_witness:
            value_evidence.append(before_witness.event_id)
        if after_witness:
            value_evidence.append(after_witness.event_id)
        if path:
            value_evidence.extend(path)
        records.append(DiscontinuityRecord(
            result.scenario_id, result.framework, boundary, before, after,
            "value_lineage", value_kind, boundary_event.event_id, None,
            tuple(dict.fromkeys(value_evidence)),
            authorization_relevant=False, native_refs=native,
        ))
    return tuple(records)


def export_boundaries(results, output_dir):
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    rows = [{**record.__dict__, "kind": record.kind.value,
             "evidence_refs": list(record.evidence_refs),
             "native_refs": list(record.native_refs)}
            for result in results for record in result.discontinuities]
    jpath = root / "discontinuities.json"
    cpath = root / "discontinuities.csv"
    mpath = root / "boundary_matrix.md"
    jpath.write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                     encoding="utf-8")
    with cpath.open("w", newline="", encoding="utf-8") as handle:
        fields = ("run_id", "framework", "boundary", "value_id_before",
                  "value_id_after", "field_or_relation", "kind",
                  "first_event_id", "authorization_relevant",
                  "affects_authorization", "evidence_refs", "native_refs")
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "evidence_refs": ";".join(row["evidence_refs"]),
                "native_refs": ";".join(row["native_refs"]),
            })
    matrix = {}
    evidence = {}
    for row in rows:
        key = (row["framework"], row["run_id"], row["boundary"])
        matrix.setdefault(key, {})[row["field_or_relation"]] = row["kind"]
        evidence.setdefault(key, []).extend(row["evidence_refs"])
    lines = [
        "# Boundary matrix (schema v3)", "",
        "Unobserved means evidence is absent, not that a qualifier was lost. "
        "Value lineage is separate from authorization qualifiers. "
        "Trace IDs resolve in results.json.", "",
        "| Framework | Run | Boundary | Source | Task | Branch | Purpose | Epoch | Approval binding | Action spec | Value lineage | Enforcement | Trace evidence |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, values in sorted(matrix.items()):
        framework, run_id, boundary = key
        cells = [values.get(field, DiscontinuityKind.UNOBSERVED.value)
                 for field in AUTH_FIELDS]
        enforcement = (
            DiscontinuityKind.PRESERVED_AND_ENFORCED.value
            if any(value == DiscontinuityKind.PRESERVED_AND_ENFORCED.value
                   for value in values.values())
            else DiscontinuityKind.UNOBSERVED.value
        )
        refs = ",".join(dict.fromkeys(evidence[key]))
        lines.append("| " + " | ".join(
            [framework, run_id, boundary] + cells +
            [values.get("action_spec", DiscontinuityKind.UNOBSERVED.value),
             values.get("value_lineage", DiscontinuityKind.UNOBSERVED.value),
             enforcement, refs]) + " |")
    mpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jpath, cpath, mpath
