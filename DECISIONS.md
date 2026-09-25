# Architecture decisions

## D1: Trusted runtime facts
Trusted setup registers contexts, an independent `AuthorizedActionSpec`, values, endorsements and capabilities. Agent text cannot mint these facts. Provenance uses runtime-created value/event IDs.

## D2: Ground truth, admission and effect separation
GroundTruthOracle returns a Boolean from trusted facts and the actual request. E1–E3 use only D0–D3 AdmissionPolicy choices. UnifiedMockEndpoint follows the selected policy and alone records mock effects. UnsafeCommit is calculated after commit/reject.

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
The E2 classifier uses TaskStart/context, value Read/Derive, policy and native mapping evidence rather than caller-supplied represented-field labels. It emits dropped or transformed-without-witness only for observed value loss or unwitnessed change. The matrix describes this integration, not a general framework vulnerability.

## D9: Model result denominators
No-attempt, parse-error and provider-error runs do not receive fabricated admission or ground-truth values. Reports state total runs, per-status counts/rates, commits, unsafe commits and unsafe commits per tool attempt while preserving scripted summary keys.

## D10: Pilot reproducibility
DeepSeek model IDs are caller-supplied. Thinking, reasoning effort, temperature, top-p and max tokens are explicit request settings; thinking mode omits temperature because it has no effect. Per-run reports carry configuration and input/prompt digests plus response ID and finish reason when available. Provider failures are individual results with no implicit retries. No full prompt or key is stored in report metadata.
