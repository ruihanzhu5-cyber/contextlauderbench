# GroundTruthOracle / AdmissionPolicy / MockEndpoint 职责审计

日期：2026-09-25。范围：E0–E3-mini；E4 保持暂停。

## 审计发现

修复前的 UnifiedMockEndpoint.invoke 直接调用 AuthorizationOracle.decide，再用该结果决定 ToolCommit/ToolReject。D0–D3 仅由 evaluate_baselines 事后写入 baselines.json，没有作为实际门禁进入 endpoint。旧 E3 报告的“48 attacks denied / 0 unsafe commits”因此是 ground truth 被误用作防御的结果，不是 D0–D3 的测量值。旧结果已由重新执行的报告覆盖。

## 修复后的职责

1. GroundTruthOracle.authorized 只读取可信运行时事实并返回 bool，不写事件、不返回 admission decision。
2. policies.py 中的 D0 AllowAllPolicy、D1 ToolAllowlistPolicy、D2 ExecutorCapabilityPolicy、D3 CombinedPolicy 是实际 admission gate。E1–E3 只能按这四个 ID 选策略。
3. GroundTruthEnforcingPolicy 只由 run_e0 / prepare_e0_scenario 用于 E0 基础设施验证；E1–E3 的 policy_from_id 拒绝它。
4. UnifiedMockEndpoint.invoke 只调用当前 AdmissionPolicy，并据其 ALLOW/DENY 写 ToolCommit/ToolReject。内部 commit 仍需一次性 prepare token。
5. runner 在 endpoint 产生 commit/reject 后调用 GroundTruthOracle，写 OutcomeEvaluated。UnsafeCommit = committed and not ground_truth_authorized。匹配的 endorsement 在这次评估后消费。
6. E2 的 endpoint 记录以实际选定策略标注执行字段。D0 不执行安全字段；D1/D2/D3 只执行 allowlist/capability，不把 provenance/approval binding 误标为已执行。

## E1 LangGraph 重新运行

每个策略对 4 对 golden twins 执行 8 条轨迹。四对的最终工具、业务参数、executor、capability、callsite 相同。

| Admission policy | 轨迹 | Ground truth unauthorized | Admission ALLOW | Commit | UnsafeCommit |
|---|---:|---:|---:|---:|---:|
| D0 AllowAll | 8 | 4 | 8 | 8 | 4 |
| D1 ToolAllowlist | 8 | 4 | 8 | 8 | 4 |
| D2 ExecutorCapability | 8 | 4 | 8 | 8 | 4 |
| D3 Combined | 8 | 4 | 8 | 8 | 4 |

D0 的四条 attack 轨迹都到达 ToolCommit。D1–D3 也允许这些 matched calls，因为工具和 executor/capability 与 legal twin 完全相同；它们没有检查决定真值的来源、任务/epoch 批准绑定和 fork–join 关系。逐条证据在 reports/golden/admission_traces.csv、results.json 和 baselines.json。

## E2 / E3-mini 重新运行

E2 的五个边界仍有 event ID 证据；boundary_matrix.md 的 Enforcement 列依据实际 policy 标注。

E3-mini 保留 48 个独特生成 case。两种 adapter × D0–D3 共 384 次执行：192 次 ground truth 未授权，384 次 admission ALLOW/ToolCommit，192 次 UnsafeCommit。D0–D3 每种策略各有 48 次 UnsafeCommit。结果在 reports/latest。

## 回归证据

完整 unittest 套件 20 项通过。关键测试证明：oracle 只返回 bool 且无事件副作用；E0 四对通过专用 enforcing policy；E1–E3 不接受该 policy；D0 对 ground truth 未授权调用可提交；D1/D2/D3 的门禁真的运行；把 GroundTruthOracle.authorized 替换为抛异常后，D0–D3 endpoint 仍可正常执行；OutcomeEvaluated 在 ToolCommit 后；E3 两种 adapter 共用统一 endpoint。

## 剩余边界

当前仍只使用 scripted 输入、LangGraph 一个框架和 mock 工具。样本规模只适合架构验证。Python 进程被任意代码控制不属于 agent-data 威胁模型。未开始 E4。
