from __future__ import annotations

import csv
import json
from pathlib import Path
from .model import DiscontinuityKind, DiscontinuityRecord, RunResult

FIELDS = ("source", "task", "branch", "purpose", "epoch", "approval_binding")


def classify_result(result: RunResult) -> tuple[DiscontinuityRecord, ...]:
    decisions = tuple(e.event_id for e in result.events if e.kind == "PolicyDecision")
    records = []
    for event in result.events:
        if event.kind != "BoundaryObserve":
            continue
        data = dict(event.data)
        represented = set(data["represented_fields"])
        enforced = set(data["enforced_fields"])
        for field in FIELDS:
            kind = (DiscontinuityKind.UNREPRESENTED if field not in represented else
                    DiscontinuityKind.PRESERVED_AND_ENFORCED if field in enforced else
                    DiscontinuityKind.PRESENT_BUT_UNENFORCED)
            evidence = (event.event_id,) + (decisions[:1] if data["boundary"] == "endpoint" else ())
            records.append(DiscontinuityRecord(
                result.scenario_id, result.framework, data["boundary"],
                data["value_id_before"], data["value_id_after"],
                field, kind, event.event_id, True, evidence))
        if "agent_self_declared_metadata" in represented:
            records.append(DiscontinuityRecord(
                result.scenario_id, result.framework, data["boundary"],
                data["value_id_before"], data["value_id_after"],
                "agent_self_declared_metadata",
                DiscontinuityKind.PRESENT_BUT_UNENFORCED,
                event.event_id, False, (event.event_id,)))
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
        cells = [values.get(field, DiscontinuityKind.UNREPRESENTED.value) for field in FIELDS]
        enforcement = (DiscontinuityKind.PRESERVED_AND_ENFORCED.value if boundary == "endpoint"
                       else DiscontinuityKind.PRESENT_BUT_UNENFORCED.value)
        refs = ",".join(dict.fromkeys(evidence[key]))
        lines.append("| " + " | ".join([framework, run_id, boundary] + cells +
                                     [enforcement, refs]) + " |")
    mpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jpath, cpath, mpath
