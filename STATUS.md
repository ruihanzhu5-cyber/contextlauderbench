# Status

Date: 2026-09-25
Scope: E0–E3-mini architecture repair before real LLM experiments. E4 remains paused.

| Area | Current state |
|---|---|
| Ground truth | Trusted `AuthorizedActionSpec` is separate from scripted fixture arguments; oracle evaluates actual requests. |
| LangGraph transport | Model receives a native HumanMessage, checkpoint state or joined graph state. |
| Fork/join | Branch values derive inside graph nodes; TrustedRuntime records shared-ancestor DAG and join lineage. |
| E2 evidence | Classifier derives representation and enforcement from events; dropped/unwitnessed changes need value evidence. |
| Reports | Mixed model outcomes and their denominators are supported; scripted columns/counts remain compatible. |
| LLM adapter | Unified AgentInput/ToolAttempt interface; DeepSeek config and HTTP transport with fake-client tests. |

E0–E3 scripted case counts remain 4 golden pairs and 48 E3-mini unique cases. The existing scripted reports under `reports/` predate these uncommitted architecture changes; tests re-execute the benchmark and check its counts. No external LLM request or real tool effect was made.

Full unittest suite: 36 tests passed. See README.md for the DeepSeek entry and limits.
