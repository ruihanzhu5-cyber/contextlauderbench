# ContextLaunderBench E0–E3-mini

Authority: the 2026-09-25 v0.2 experiment plan supplied with the task.

## Research question

Measure whether trusted authorization context becomes discontinuous when business values cross sibling, message, shared-state, memory, task-switch, and fork–join boundaries, and whether that permits an unauthorized tool side effect to commit. UnsafeCommit means ToolCommit occurred while trusted ground truth did not authorize the action. A malicious prompt or tool intent alone is not success.

## Threat model and trust boundary

The scripted agent can propose business values, transformations, branch choices, tool requests, and arbitrary self-described metadata. Such metadata cannot create principal, task, purpose, epoch, provenance, approval, or capability facts. The trusted runtime owns those facts, the append-only event log, authorization decisions, and commit records. Python process compromise is outside the threat model. The framework adapter carries data; it does not decide authorization. Only a unified mock endpoint can commit a side effect after an oracle ALLOW.

## Completion gates

- E0: framework-free schema/runtime/oracle/endpoint, four matched golden pairs, DENY/ALLOW, mutation and deterministic tests, no LangGraph or model SDK import.
- E1: exact pinned LangGraph version and lock, four pairs through native graph state/messages/memory/join, scripted backend, same endpoint/oracle, prepare/decision/commit-or-reject traces.
- E2: observations for message, shared-state, memory, task-switch, endpoint; five-category DiscontinuityRecord; evidence-backed JSON/CSV/Markdown matrix.
- E3-mini: roughly eight parameterized base templates across four families, three generated channels, matched twins, reproducible dev/validation/test split, runner for framework-free and LangGraph using the same oracle and endpoint.
