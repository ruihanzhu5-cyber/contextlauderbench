from __future__ import annotations

import json
import hashlib
import subprocess
from importlib.metadata import version
from pathlib import Path

from .adapters.langgraph_adapter import LangGraphAdapter
from .analysis import export_boundaries
from .generator import split_generator, validate_dataset
from .model import Decision, RunResult
from .runner import run_free
from .scenarios import flatten_pairs, golden_pairs, validate_pair


def _run_pairs(pairs, adapters):
    output = []
    langgraph = LangGraphAdapter() if "langgraph" in adapters else None
    for attack, legal in pairs:
        validate_pair(attack, legal)
        for adapter in adapters:
            runner = run_free if adapter == "free" else langgraph.run
            a, l = runner(attack), runner(legal)
            if (a.decision != Decision.DENY or a.committed or
                    l.decision != Decision.ALLOW or not l.committed):
                raise AssertionError(f"Incorrect verdict for {attack.template_id}/{attack.channel}")
            output.extend((a, l))
    return tuple(output)


def run_golden(output_dir, adapters=("free", "langgraph")):
    results = _run_pairs(golden_pairs(), adapters)
    write_results(results, output_dir, {"golden": [s.scenario_id for s in
                  flatten_pairs(golden_pairs())]})
    from .baselines import evaluate_baselines
    from .runner import prepare_scenario
    rows = []
    for scenario in flatten_pairs(golden_pairs()):
        state = prepare_scenario(scenario)
        request = state.runtime.make_request(
            scenario.tool_name, scenario.arguments, scenario.executor_id,
            scenario.capability_id, scenario.callsite_id,
            state.context_ref, state.value_id)
        rows.append({"scenario_id": scenario.scenario_id,
                     "ground_truth_authorized": scenario.legal,
                     "admission": evaluate_baselines(state.runtime, request)})
    (Path(output_dir) / "baselines.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8")
    return results


def run_benchmark(output_dir, seed=20260925, adapters=("free", "langgraph")):
    dataset = split_generator(seed=seed)
    validate_dataset(dataset)
    results = []
    assignment = {}
    for split, pairs in dataset.items():
        assignment[split] = [s.scenario_id for s in flatten_pairs(pairs)]
        results.extend(_run_pairs(pairs, adapters))
    write_results(results, output_dir, assignment, seed)
    return tuple(results)


def write_results(results, output_dir, assignment, seed=None):
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    results = tuple(results)
    (root / "results.json").write_text(
        json.dumps([r.as_dict() for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8")
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
    summary = {
        "code_commit": code_commit,
        "dependency_lock_sha256": lock_sha256,
        "seed": seed,
        "langgraph_version": version("langgraph") if any(
            r.framework == "LangGraph" for r in results) else None,
        "cases": len(results),
        "attacks_denied": sum(not r.ground_truth_authorized and
                              r.decision == Decision.DENY for r in results),
        "legal_allowed": sum(r.ground_truth_authorized and
                             r.decision == Decision.ALLOW for r in results),
        "unsafe_commits": sum(r.committed and not r.ground_truth_authorized
                              for r in results),
        "splits": assignment,
        "dataset_scope": "architecture validation; no inferential statistics",
    }
    (root / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
