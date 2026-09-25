# Implementation plan

1. E0: immutable scenario/event models; runtime-owned IDs, provenance edges, task contexts, approvals, capabilities, and events; pure oracle; unified mock endpoint; scripted golden pair runner; unit and mutation tests.
2. E1: pin LangGraph and transitive dependencies; map scripted values to LangGraph StateGraph messages/state/checkpoint memory/fork–join; route every terminal call through the E0 endpoint; retain canonical events and native-object mapping.
3. E2: add boundary snapshots and DiscontinuityRecord classification; export trace-backed machine-readable and Markdown matrix.
4. E3-mini: parameterized template, twin, channel, and split generators; automatic equality validation; run both adapters and save results.

Each gate updates STATUS.md after passing. Only then begin the next phase.
