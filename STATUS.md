# Status

Date: 2026-09-25
Scope: E0–E3-mini architecture repair before real LLM experiments. E4 remains paused.

| Area | Current state |
|---|---|
| Ground truth | Trusted `AuthorizedActionSpec` is separate from scripted fixture arguments; oracle evaluates actual requests. |
| LangGraph transport | Model receives a native HumanMessage, checkpoint state or joined graph state. |
| Split/join | LangGraph branches have runtime Derive/Join witnesses for every family using this channel; the true fork/join family keeps graph-node lineage. |
| E2 evidence | Classifier derives representation and enforcement from events; dropped/unwitnessed changes need value evidence. |
| Reports | Four attempt statuses, explicit denominators and safe model metadata are supported; scripted columns/counts remain compatible. |
| LLM adapter | Unified AgentInput/ToolAttempt interface; DeepSeek request parameters are explicit and covered by fake-client tests. |

The scripted validation remains four golden pairs and 48 E3-mini unique cases. Existing files under reports/ are historical scripted outputs; rerun the documented commands for reports from the current code. The opt-in model path and DeepSeek adapter have fake-client test evidence only. No real external LLM experiment or real tool effect has been run.

See README.md for the one-case DeepSeek pilot entry and current limits.
