# Status

Date: 2026-09-25
Current phase: E0–E3-mini complete

| Phase | Content | Tests and gate | Issues | Next |
|---|---|---|---|---|
| E0 | Framework-free immutable models, trusted runtime/provenance/approvals, oracle, sole mock endpoint, four golden pairs | PASS: 4 attack DENY, 4 legal ALLOW; terminal equality; metadata, missing provenance, forged context/family, bypass, replay, unknown capability and business-argument mutation checks | Windows sandbox helper initialization failed; WSL path works | Complete |
| E1 | LangGraph 1.2.12 native messages, shared state, InMemorySaver checkpoint, task switch and fork–join; same oracle/endpoint; D0–D3 sanity admission report | PASS: 4 pairs through graph, 8 LangGraph golden results with prepare/decision/commit-or-reject events; requirements.lock pinned | None | Complete |
| E2 | Message/shared-state/memory/task-switch/endpoint observations; five-kind DiscontinuityRecord and trace-linked JSON/CSV/Markdown matrix | PASS: all five boundaries and evidence references validated | Observations describe this integration, not framework-wide security behavior | Complete |
| E3-mini | 8 validated templates, generated twins and 3 channels, fixed-seed grouped split, both scripted runners | PASS: 48 generated cases; 96 adapter runs, 48 attacks denied, 48 legal allowed, 0 unsafe commits; full suite 15 tests | Dataset is architecture validation only | Complete |

## Deliverables

- reports/golden: E1 golden results, D0–D3 admission baselines, traces, E2 discontinuities and matrix.
- reports/latest: E3-mini results, split, version/lock/commit metadata, discontinuities and matrix.
- requirements.in and requirements.lock: exact LangGraph version and resolved dependencies.
- README.md: install, test, and run instructions.

## Remaining limits

Only scripted inputs and mock side effects were tested. No LLM, second framework, E4+ defense, concurrent revocation, large-scale statistics, or real external tool is included. Python process compromise and arbitrary adapter code execution are outside the agent-data threat model. The current eight-template sample should not be used for statistical claims. The five-category E2 schema is ready, but this small integration does not produce every category (for example, it has no summary transformation).
