# Architecture decisions

## D1: Trusted registration and runtime references
Trusted scenario setup registers contexts, values, capabilities, and endorsements. Agent output is plain payload and cannot mint runtime references. Provenance uses runtime-created value/event IDs.

## D2: Endpoint as the only commit writer
The endpoint keeps a private effect ledger. It issues a one-use prepare token, calls the oracle, then commits or rejects. Its internal commit gate checks an unforgeable object secret and live token. Python introspection is outside the agent-output threat model.

## D3: Business-only tool arguments
Terminal calls carry the same tool name and concrete business arguments in both twins. Identity, purpose, approval, epoch, and provenance travel in trusted runtime state.

## D4: Scripted execution first
The benchmark tests authorization and framework transport, without LLM randomness or model SDKs.

## D5: Policy family is runtime-owned
The trusted scenario registration fixes the policy family in TrustedRuntime. Endpoint ignores any adapter-supplied family hint when choosing an oracle branch. A regression test tries to present a cross-task attack as a sibling case and confirms DENY.

## D6: Boundary records describe integration observations
The adapter emits boundary observations through the trusted runtime. The classifier uses the fixed five-kind enum and ties each record to canonical event IDs. Native graph state does not itself carry trusted security fields; the runtime sidecar supplies them at the endpoint. The matrix describes this benchmark integration, not a general LangGraph vulnerability.
