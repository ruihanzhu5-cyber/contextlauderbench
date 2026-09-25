# Architecture decisions

## D1: Trusted registration and runtime references
Trusted scenario setup registers contexts, values, capabilities, and endorsements. Agent output is plain payload and cannot mint runtime references. Provenance uses runtime-created value/event IDs.

## D2: Oracle, policy, and endpoint separation
GroundTruthOracle returns only a Boolean from trusted facts. E1–E3 select an AdmissionPolicy from D0–D3. UnifiedMockEndpoint applies that policy and alone writes the mock effect ledger. It never calls GroundTruthOracle in E1–E3. The result computes UnsafeCommit from the completed commit state and independent ground truth. A one-use prepare token protects the internal commit method.

## D3: Business-only tool arguments
Terminal calls carry identical tool name and concrete business arguments in attack/legal twins. Identity, purpose, approval, epoch, and provenance travel in trusted runtime state.

## D4: Scripted execution first
The benchmark tests authorization and framework transport without LLM randomness or model SDKs.

## D5: Scenario family is runtime-owned
Trusted scenario registration fixes the family in TrustedRuntime. The adapter cannot pass a family hint to select a different oracle branch.

## D6: E0 enforcement is a validation fixture
GroundTruthEnforcingPolicy wraps the Boolean oracle only for E0 golden-pair and mutation tests. Public E1–E3 runner policy selection accepts D0–D3 only.

## D7: D0–D3 are active admission baselines
D0 permits every reached tool request. D1 checks the tool allowlist. D2 checks the executor capability. D3 requires both. These policies inspect neither provenance nor approval binding; matched attacks can therefore commit. Earlier report-only baseline booleans were removed.

## D8: Boundary records describe integration observations
The classifier uses the five specified kinds and canonical event evidence. At the endpoint, D0 represents security context without enforcing it. D1–D3 enforce their explicit allowlist/capability gates; they do not enforce provenance or approval binding. This matrix describes the benchmark integration, not a general LangGraph vulnerability.
