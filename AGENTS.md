# Engineering rules

- Treat CONTEXTLAUNDERBENCH_EXPERIMENT_PLAN_v0.2.md as the authority for E0–E3-mini.
- Do not call any LLM API or install any model SDK.
- Do not implement E4 or later phases.
- E1 integrates LangGraph only. Do not integrate Microsoft Agent Framework or AutoGen yet.
- Agent self-declared metadata is always untrusted.
- Approval, task, purpose, epoch, principal, branch, nonce, and provenance never enter tool business arguments.
- Ground truth, authorization context, event log, and commit authority belong to the trusted runtime.
- Every side effect goes through the unified endpoint.
- Framework adapters must not own or mutate security truth.
- Do not skip failing tests.
- Do not edit expected verdicts to make tests pass.
- A crash is not a successful defense.
- E3-mini is generator-first; do not handwrite the complete task matrix.
- Preserve user files. Keep all project files under this directory.

- GroundTruthOracle is read-only and returns only a Boolean authorization label.
- E1–E3 endpoint admission must use the selected D0–D3 AdmissionPolicy, never GroundTruthEnforcingPolicy.
- D0 is AllowAll/default; an unauthorized reached call may commit. Calculate UnsafeCommit after execution.
- GroundTruthEnforcingPolicy is an E0 infrastructure validation fixture only.
- Keep ground truth, admission decision, and commit state as separate result fields.
