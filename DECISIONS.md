# Architecture decisions

## D1: Trusted runtime facts
Trusted setup registers contexts, an independent `AuthorizedActionSpec`, values, endorsements and capabilities. Agent text cannot mint these facts. Provenance uses runtime-created value/event IDs.

## D2: Ground truth, admission and effect separation
GroundTruthOracle returns a Boolean from trusted facts and the actual request. E1–E3 use only D0–D3 AdmissionPolicy choices. UnifiedMockEndpoint follows the selected policy and alone writes effects: mock records for E0-E3 and local sandbox balance changes for 2A. UnsafeCommit is calculated after commit/reject.

## D3: Scripted and model inputs
Scripted fixture arguments produce deterministic E0–E3 calls. They never fill or replace a model call. The trusted action rule may authorize a different target or an allowed set of targets. In scripted matched pairs the terminal business call remains comparable; model attempts can differ.

## D4: Unified backend contract
`AgentInput -> ToolAttempt` is shared by ScriptedBackend, generic ModelBackend and DeepSeekBackend. The provider adapter receives task plus framework-native data and returns a parsed tool attempt. It does not evaluate authorization. Tests use fake clients and require no external API.

## D5: LangGraph and fork/join
LangGraph passes native message/checkpoint/join state to the model node. For every split/join channel, graph branch nodes derive runtime values from a shared ancestor and the graph join node asks TrustedRuntime to record the join. Provenance validation accepts DAG reuse and rejects active-path cycles.

## D6: E0-only enforcement
GroundTruthEnforcingPolicy wraps the Boolean oracle only for E0 validation. Public E1–E3 policy selection accepts D0–D3.

## D7: Active admission baselines
D0 permits every reached call. D1 checks the tool allowlist. D2 checks executor capability. D3 checks both. They do not check provenance or approval binding, so matched attacks can commit.

## D8: Boundary classification
The E2 classifier uses TaskStart/context, value Read/Derive, policy and native mapping evidence rather than caller-supplied represented-field labels. It emits dropped or transformed-without-witness only for observed value loss or unwitnessed change. Missing evidence is unobserved. Business value continuity cannot prove authorization qualifier continuity. Generic E2 authorization causality remains unknown until paired verification. The matrix uses schema v2 and describes this integration, not a general framework vulnerability.

## D9: Model result denominators
No-attempt, parse-error and provider-error runs do not receive fabricated admission or ground-truth values. Reports state total runs, per-status counts/rates, commits, unsafe commits and unsafe commits per tool attempt while preserving scripted summary keys.

## D10: Pilot reproducibility
DeepSeek model IDs are caller-supplied. Thinking, reasoning effort, temperature, top-p and max tokens are explicit request settings; thinking mode omits temperature because it has no effect. Per-run reports carry configuration and input/prompt digests plus response ID and finish reason when available. Provider failures are individual results with no implicit retries. No full prompt or key is stored in report metadata.

## D11: Joint actions and independent approvals

`AuthorizedActionSpec.allowed_arguments` remains the legacy independent-field rule. Its cross-product semantics are a design limit when a task requires coupled fields, not evidence of a bug in exact legacy cases. `AuthorizedActionSpec.one_of` binds complete action alternatives for 2A. Structured approval records and issuer resource authority live only in TrustedRuntime; neither an invoice claim nor a fixture label mints them. The oracle applies one read-only approval relation to the actual request, including joined approval reference, trusted approval-branch witness, issuer, executor, task, exact action and active status. This permits an external business input with an independent exact approval without relabeling its source.

## D12: Local effect and commit-time evidence

The 2A LangGraph graph has invoice and approval branches and a real join. A controlled scripted executor reads its joined state. Faults are explicitly injected in the join node; a native before/after event and TrustedRuntime value IDs witness the change. The endpoint receives a local in-memory payment ledger callback; only its admitted commit path can invoke the callback. A commit changes treasury and supplier balances and returns a receipt; denial does not change business state. An AuthorizationSnapshot event before admission records request digest, approval relation, ledger version and Boolean oracle result. The run is single-threaded and deterministic, without concurrent revocation or distributed exactly-once semantics.

## D13: Scope of paired 2A claims and 2B boundary

The same-request legal/wrong-approval pair can establish whether D0-D3 admission distinguishes approval history; it cannot measure natural LLM behavior. The fault/repair pair can establish a proposal difference under the same scripted executor rule, input and ledger. It cannot claim that restoring a qualifier makes D0-D3 reject a forced call. The 12 conditions are mechanism coverage. 2B would replace the scripted executor with a model over joined native state, retain approval/oracle/admission/effect separation, and begin with one explicitly configured case. No external API call is part of 2A.
