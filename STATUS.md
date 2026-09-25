# Status

Date: 2026-09-25
Current scope: E0–E3-mini audited and repaired. E4 paused at user request.

| Phase | Corrected gate | Evidence | Status |
|---|---|---|---|
| E0 | Framework-free oracle/runtime/endpoint validated with dedicated GroundTruthEnforcingPolicy | 4 attack DENY, 4 legal ALLOW; matched calls; mutation, bypass, replay, purity tests | PASS |
| E1 | LangGraph golden pairs under active D0–D3 policies | 32 traces; each policy 8 commits, including 4 UnsafeCommits | PASS |
| E2 | Five boundaries and five-kind schema with actual policy enforcement labels | JSON/CSV/Markdown matrix and event IDs; D0 context present but unenforced | PASS |
| E3-mini | 8 templates × 3 channels × twins; both adapters × D0–D3 | 48 unique cases, 384 runs, 192 UnsafeCommits | PASS |

Full unittest suite: 20 tests passed. Reports were regenerated after the responsibility fix. See AUDIT_GROUND_TRUTH_ADMISSION.md for the original defect, corrected design, per-policy counts and evidence.

## Deliverables

- reports/golden/admission_traces.csv and baselines.json: every E1 LangGraph D0–D3 trajectory with ground_truth_authorized, admission_policy, admission_decision, committed and unsafe_commit.
- reports/latest: E3-mini results, summary, discontinuities and boundary matrix.
- requirements.lock: pinned LangGraph 1.2.12 environment.
- SPEC.md, DECISIONS.md, README.md and AGENTS.md: corrected architecture and operating rules.

## Remaining limits

Only scripted input and mock effects are included. The eight-template sample is architecture validation, not a statistical result. There is no LLM, second framework, real external effect, concurrent revocation study or E4 defense. Arbitrary Python process compromise is outside the agent-data threat model.
