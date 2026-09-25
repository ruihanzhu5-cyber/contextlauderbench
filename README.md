# ContextLaunderBench

A scripted architecture validation benchmark for authorization context continuity. The implementation covers E0, LangGraph E1, E2, and E3-mini. All effects are in-memory mock records. No LLM API or model SDK is used.

## Installation and tests

Use Python 3.11+ and install the pinned dependencies:

    python -m venv .venv
    .venv/Scripts/python -m pip install -r requirements.lock
    .venv/Scripts/python -m unittest discover -s tests -v

For a Linux virtual environment, use .venv/bin/python in place of .venv/Scripts/python. E0 imports no LangGraph module.

## Execution

    .venv/Scripts/python -m context_launder_bench.cli golden --adapter langgraph --output reports/golden
    .venv/Scripts/python -m context_launder_bench.cli benchmark --adapter both --output reports/latest --seed 20260925

The golden command executes the four matched pairs under D0–D3 in LangGraph: 32 trajectories. The benchmark generates eight templates, three channels, and attack/legal twins: 48 unique cases. Both adapters and four policies yield 384 trajectories. The fixed-seed split groups by template (12 dev, 12 validation, 24 test unique cases; 25/25/50), with all four held-out parameter templates in test.

D0 = allow all/default framework behavior. D1 = tool allowlist. D2 = executor capability. D3 = both. These are active admission policies inside UnifiedMockEndpoint. GroundTruthOracle independently computes a Boolean label; it does not gate E1–E3 commits. GroundTruthEnforcingPolicy is used only by E0 tests.

Each output directory contains results.json, admission_traces.csv, summary.json, discontinuities.json/csv, and boundary_matrix.md. Golden output also has baselines.json, whose rows are actual D0–D3 execution outcomes rather than report-only predictions. The five requested trace fields are ground_truth_authorized, admission_policy, admission_decision, committed, and unsafe_commit.

## Code map

- model.py: scenario, event, result, and discontinuity models.
- runtime.py: trusted contexts, values, provenance, endorsements, capabilities, and events.
- oracle.py: read-only Boolean GroundTruthOracle.
- policies.py: active D0–D3 policies and E0-only GroundTruthEnforcingPolicy.
- endpoint.py: sole mock effect commit path controlled by the selected policy.
- adapters/langgraph_adapter.py: native LangGraph message, state, checkpoint memory, task switch, and join transport.
- generator.py and benchmark.py: generated pairs, splits, execution, and reports.
- tests/: phase gates and separation regressions.

The trust boundary assumes agent-controlled data, not arbitrary Python process execution. This is a small architecture validation dataset, not a statistical result. E4 remains paused.
