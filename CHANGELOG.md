# Change log

Each entry describes a repository version. The linked Git commits contain the exact file-level diff. Add an entry when publishing the next version.

## 2026-09-25: LLM pilot preparation

This entry is published with the pilot-preparation commit; see its GitHub diff for the exact files.

- Corrected the E2 boundary matrix header and added a column-count test.
- Matched LangGraph and framework-free split/join runtime lineage while preserving scripted verdicts.
- Made DeepSeek thinking, reasoning effort, sampling and output cap explicit; recorded safe model-run metadata.
- Added provider-error outcomes and rates without endpoint calls or hidden retries.
- Added Python 3.11 GitHub Actions tests and updated pilot documentation.

## 2026-09-25: Model execution architecture repair

[Commit d6bd366](https://github.com/ruihanzhu5-cyber/contextlauderbench/commit/d6bd36678110a57b49393ee1cba949009fab9e41)

- Separated trusted authorized-action rules from scripted fixture arguments.
- Passed native LangGraph channel data to model backends and moved fork/join lineage into graph nodes.
- Added mixed model-outcome reporting, evidence-based E2 classification and a DeepSeek adapter tested with fake clients.

## Earlier repository versions

- [aedc095](https://github.com/ruihanzhu5-cyber/contextlauderbench/commit/aedc0951afdb9ef29cb30e435043ba643fd5c5f4): routed model tool calls through LangGraph runtime data flow.
- [57c3238](https://github.com/ruihanzhu5-cyber/contextlauderbench/commit/57c3238): merged repository history.
- [6b02f8c](https://github.com/ruihanzhu5-cyber/contextlauderbench/commit/6b02f8c9fb6d34ad28c71f8e08dc82ff71174d6c): separated ground truth from E1-E3 admission policies.
- [4898db4](https://github.com/ruihanzhu5-cyber/contextlauderbench/commit/4898db4e44345579a9a4b09038da903708dd6186): implemented E0 through E3-mini infrastructure.
- [67a1363](https://github.com/ruihanzhu5-cyber/contextlauderbench/commit/67a1363): initial repository commit.
