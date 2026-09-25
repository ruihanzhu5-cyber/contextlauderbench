from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from importlib.metadata import version
from pathlib import Path

from .adapters.langgraph_adapter import LangGraphAdapter
from .analysis import export_boundaries
from .generator import split_generator, validate_dataset
from .model import Decision
from .policies import POLICY_IDS
from .runner import run_free
from .scenarios import flatten_pairs, golden_pairs, validate_pair


def _run_pairs(pairs, adapters, policies=POLICY_IDS):
    output = []
    langgraph = LangGraphAdapter() if "langgraph" in adapters else None
    for attack, legal in pairs:
        validate_pair(attack, legal)
        for adapter in adapters:
            runner = run_free if adapter == "free" else langgraph.run
            for policy_id in policies:
                for scenario in (attack, legal):
                    result = runner(scenario, policy_id)
                    if result.ground_truth_authorized != scenario.legal:
                        raise AssertionError(f"Ground truth disagrees with fixture: {scenario.scenario_id}")
                    if result.committed != (result.admission_decision is Decision.ALLOW):
                        raise AssertionError("Admission/commit inconsistency")
                    output.append(result)
    return tuple(output)


def run_golden(output_dir, adapters=("free", "langgraph"), policies=POLICY_IDS):
    pairs = golden_pairs()
    results = _run_pairs(pairs, adapters, policies)
    write_results(results, output_dir, {
        "golden": [s.scenario_id for s in flatten_pairs(pairs)]
    })
    rows = [trace_row(r) for r in results]
    (Path(output_dir) / "baselines.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8")
    return results


def run_benchmark(output_dir, seed=20260925, adapters=("free", "langgraph"),
                  policies=POLICY_IDS):
    dataset = split_generator(seed=seed)
    validate_dataset(dataset)
    results = []
    assignment = {}
    for split, pairs in dataset.items():
        assignment[split] = [s.scenario_id for s in flatten_pairs(pairs)]
        results.extend(_run_pairs(pairs, adapters, policies))
    write_results(results, output_dir, assignment, seed)
    return tuple(results)


def trace_row(result):
    return {
        "scenario_id": result.scenario_id,
        "framework": result.framework,
        "ground_truth_authorized": result.ground_truth_authorized,
        "admission_policy": result.admission_policy,
        "admission_decision": result.admission_decision.value,
        "committed": result.committed,
        "unsafe_commit": result.unsafe_commit,
        "reason_code": result.reason_code,
        "canonical_log_digest": result.canonical_log_digest,
    }


def write_results(results, output_dir, assignment, seed=None):
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    results = tuple(results)
    (root / "results.json").write_text(
        json.dumps([r.as_dict() for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8")
    with (root / "admission_traces.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = tuple(trace_row(results[0]))
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(trace_row(r) for r in results)
    export_boundaries(results, root)
    project_root = Path(__file__).resolve().parent.parent
    try:
        code_commit = subprocess.check_output(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        code_commit = None
    lock = project_root / "requirements.lock"
    lock_sha256 = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None
    by_policy = {}
    for policy in sorted({r.admission_policy for r in results}):
        group = [r for r in results if r.admission_policy == policy]
        by_policy[policy] = {
            "runs": len(group),
            "admission_allowed": sum(r.admission_decision is Decision.ALLOW for r in group),
            "admission_denied": sum(r.admission_decision is Decision.DENY for r in group),
            "committed": sum(r.committed for r in group),
            "unsafe_commits": sum(r.unsafe_commit for r in group),
        }
    summary = {
        "code_commit": code_commit,
        "dependency_lock_sha256": lock_sha256,
        "seed": seed,
        "langgraph_version": version("langgraph") if any(
            r.framework == "LangGraph" for r in results) else None,
        "cases": len(results),
        "unique_scenarios": len({r.scenario_id for r in results}),
        "ground_truth_authorized": sum(r.ground_truth_authorized for r in results),
        "ground_truth_unauthorized": sum(not r.ground_truth_authorized for r in results),
        "admission_allowed": sum(r.admission_decision is Decision.ALLOW for r in results),
        "admission_denied": sum(r.admission_decision is Decision.DENY for r in results),
        "committed": sum(r.committed for r in results),
        "unsafe_commits": sum(r.unsafe_commit for r in results),
        "by_policy": by_policy,
        "splits": assignment,
        "dataset_scope": "architecture validation; no inferential statistics",
    }
    (root / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
