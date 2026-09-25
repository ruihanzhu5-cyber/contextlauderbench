# ContextLaunderBench

A scripted architecture validation benchmark for authorization context continuity across agent framework boundaries. The first phase contains E0, LangGraph E1, E2, and E3-mini. All tool effects are in-memory mock records. No LLM API or model SDK is used.

## Installation

Use Python 3.11+ in this directory. Create a virtual environment and install the exact lock:

    python -m venv .venv
    .venv/Scripts/python -m pip install -r requirements.lock

On Linux/WSL, use .venv/bin/python instead. The pinned direct dependency is LangGraph 1.2.12 from PyPI; requirements.lock records the full resolved environment used for this run.

## Tests

    .venv/Scripts/python -m unittest discover -s tests -v

E0 itself uses the standard library and does not import LangGraph. The full suite exercises all phases.

## Runs

    .venv/Scripts/python -m context_launder_bench.cli golden --output reports/golden
    .venv/Scripts/python -m context_launder_bench.cli benchmark --adapter both --output reports/latest --seed 20260925

The golden command runs four matched pairs through both framework-free and LangGraph paths. Its baselines.json contains D0 framework default, D1 allowlist, D2 capability, and D3 combined admission gates; the oracle is mandatory for every commit under all conditions.

The benchmark command generates eight templates across four families, three channels, and attack/legal twins, giving 48 unique cases. Both adapters produce 96 case runs. The split is grouped by template: 12 dev, 12 validation, 24 test cases (25/25/50). All four held-out parameter templates are in test. This is an architecture validation dataset, not a statistical paper result.

Each run directory contains results.json with canonical traces and verdicts, summary.json with version, code commit, lock hash and counts, discontinuities.json/csv, and boundary_matrix.md with event evidence references.

## Project layout

- context_launder_bench/model.py: immutable scenario, event, result, and discontinuity models.
- context_launder_bench/runtime.py: trusted contexts, values, provenance, endorsements, capabilities, and canonical events.
- context_launder_bench/oracle.py and endpoint.py: authorization and sole mock effect commit path.
- context_launder_bench/adapters/langgraph_adapter.py: native LangGraph message, state, checkpoint memory, task switch, and join transport.
- context_launder_bench/generator.py and benchmark.py: generated pairs, splits, and deterministic runners.
- tests/: phase gates and mutation checks.

The trust boundary assumes agent-controlled data, not arbitrary Python code execution. Only the scripted backend is implemented.
