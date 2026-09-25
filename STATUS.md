# Status

Date: 2026-09-25
Scope: E0-E3-mini scripted validation plus 2A deterministic payment workflow. E4 remains paused.

| Area | Current state |
|---|---|
| Ground truth | Trusted `AuthorizedActionSpec` is separate from scripted fixture arguments; oracle evaluates actual requests. |
| LangGraph transport | Model receives a native HumanMessage, checkpoint state or joined graph state. |
| Split/join | LangGraph branches have runtime Derive/Join witnesses for every family using this channel; the true fork/join family keeps graph-node lineage. |
| E2 evidence | Schema v3 reports unobserved when evidence is missing, separates business lineage from authorization qualifiers, and leaves generic causal effect unknown. |
| Reports | Four attempt statuses, explicit denominators and safe model metadata are supported; scripted columns/counts remain compatible. |
| LLM adapter | Unified AgentInput/ToolAttempt interface; DeepSeek request parameters are explicit and covered by fake-client tests. |
| 2A payment workflow | Real LangGraph invoice/approval branches and join, controlled scripted executor, trusted approval relation, and endpoint-only local balance changes with receipts. Twelve controlled cases pass; backend injection and failure handling are verified offline. |

The scripted validation remains four golden pairs and 48 E3-mini unique cases. Existing files under reports/ are historical scripted outputs; rerun the documented commands for reports from the current code. The opt-in model path and DeepSeek adapter have fake-client test evidence only. No real external LLM experiment or external business effect has been run.

See README.md for the one-case DeepSeek pilot entry and current limits.

The 2A suite includes a same-payment legal/wrong-approval pair, explicit join misbinding and drop faults, repair and identity controls, independently approved external input, invalid/inactive approvals, a second resource, and a D2 admission denial. Faults are injected deliberately at the join. The cases provide mechanism coverage, not independent samples or a natural LLM attack rate. The approval relation checks issuer resource authority, executor, task, exact action, active record and the selected record's trusted approval-branch witness carried through the join. A precommit authorization snapshot records the request and ledger version; business changes are local in-memory balances and receipts.

The legacy independent `allowed_arguments` ranges were a design choice, not by themselves a demonstrated bug. Joint alternatives are now available for the payment workflow. Historical E2 output predates schema v3 and should be regenerated if compared with current classifier output. The workflow uses a deterministic single-run execution; true checkpoint restore, multilevel delegation, concurrent revocation and distributed transaction semantics remain untested. 2B external LLM validation has not started and requires a separate request. No API key was read or requested.

Payment backend wiring is now available via workflow2a.run_case/run_suite, with post-boundary-only input isolation, safe model metadata, and distinct expected execution failures. DeepSeek integration was exercised with a fake client only. No API key was read and no real provider call was made. Generic E2 value_lineage denotes a witnessed derivation path, not unchanged business content.
