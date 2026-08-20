# Phase 2 Continuous Resume Prompt

Use this prompt to resume the currently paused Phase 2 Goal. Do not create a
second Goal when the existing Goal can be resumed.

```text
/ralph-loop

继续当前已暂停的完整二期 Goal，目标仓库：
/Users/bytedance/Desktop/xiaoro-fresh

权威规格与执行标准：
- .trae/specs/complete-phase2-continuously/spec.md
- .trae/specs/complete-phase2-continuously/tasks.md
- .trae/specs/complete-phase2-continuously/checklist.md
- docs/superpowers/plans/2026-08-09-phase2-continuous-ralph.md
- docs/superpowers/specs/2026-08-09-phase2-audit-idempotency-and-token-telemetry-design.md

当前现场必须保留：
- rebuild 是干净权威基线，不得回退。
- /private/tmp/xiaoro-phase2-integration 存在 4 个未提交文件：
  app/guide/application/consultation_coordinator.py
  app/guide/feedback/ports.py
  tests/guide/adapters/state/test_in_memory_conversation_state.py
  tests/guide/application/test_consultation_coordinator.py
- 不得 reset、restore、checkout、stash 或覆盖这 4 个文件。
- 其他已完成 worktree/branch 必须先按 stable patch ID 和最终 blob manifest
  判断是否已集成，不得重复 cherry-pick 或制造等价提交。

恢复顺序：
1. 先从 rebuild 读取上述权威标准；若 phase2-integration 尚未包含标准提交，
   只读使用 rebuild 版本。
2. 当前 consultation-profile capability loop 已经做过开头审计，并因 finding
   进入修复。不得再次 full-file audit。把既有 review evidence 迁移登记为
   audit ledger 的 PASS/REUSED_PASS，当前 4 文件修复只用 RED/GREEN、
   focused、双 boundary、HTTP 和浏览器门禁验证。
3. 先收口并提交当前 4 文件；只有测试和门禁通过才提交，不得创建无验证 WIP
   提交。
4. 当前 WIP 形成绿色提交后，将 rebuild 合入 phase2-integration，使审计幂等
   标准、双台账和本 Prompt 进入执行分支。
5. 按真实完成度继续增量集成：
   consultation/profile
   -> two-image vertical
   -> single-image suitability
   -> OCR observations
   -> three/four-image compare
   -> trusted feedback targets/events
   -> remaining frontend and four vertical gates。
6. 每个能力形成绿色纵向提交后立即集成，不等待整条线结束。

审计唯一性硬规则：
- 每个 capability loop 只允许开头一次真实 full-file audit invocation。
- audit key = audit profile version + 排序后的 scope path/blob SHA-256。
- 相同 audit key 已 PASS 时只记录 REUSED_PASS，不调用审计器。
- commit SHA、branch、worktree、上下文压缩或会话恢复不得触发重复审计。
- finding 修复必须写 RED 并跑正常门禁，同一循环禁止第二次 full-file audit。
- 审计器失败、超时或不可用时，同一 audit key 只记录一次
  LOCAL_BASELINE_ONLY；主线程完成一次有界基线检查，然后继续其他可运行任务。
- 用户不在线、睡眠或未回复普通 checkpoint 不是停止条件。
- 全部能力集成后只建立一个 FINAL-PHASE2-AUDIT，执行一次独立 full-file
  audit；修复 finding 后只重跑测试和完整门禁，不再次 full-file audit。

重复提交硬规则：
- cherry-pick/merge 前计算 stable patch ID 和最终 production blob manifest。
- patch ID 或最终 blob 已等价集成时，记录 INTEGRATION_REUSED 并跳过。
- 不得为了生成新 SHA 而重复 cherry-pick、amend 或重写相同内容。
- progress 只追加新证据，不得用新提交重复陈述旧 checkpoint。

Agent Token 缓存与成本统计：
- 每个 checkpoint 调用可用 Goal/provider usage telemetry。
- 每个 checkpoint 向
  docs/audits/phase2-continuous/agent_token_usage.csv
  追加一行。
- 记录 cumulative_tokens、prompt_tokens_total、prompt_uncached_tokens、
  cache_read_tokens、cache_write_tokens、output_tokens、model 和 telemetry_source。
- 只有 cache_read 与 uncached prompt 同源可用时才计算 cache_hit_rate。
- 只有准确模型、usage 语义和带日期价格快照齐全时才计算 estimated_cost。
- 平台未暴露的字段写 UNAVAILABLE，不得估算、反推或把总 Token 当缓存命中。
- 历史 26,788,605 Token 的缓存拆分保持 UNAVAILABLE。
- audit ledger 仅在真实调用、复用或状态变化时追加，不在每个 checkpoint
  重复写相同事件。

持续运行要求：
- 一条线阻塞时继续其他独立线。
- 普通 review/checkpoint 不等待用户批准。
- 只有完整二期全部完成、所有剩余任务共享同一硬决策阻塞、达到 Ralph 轮次
  上限，或用户明确暂停时才停止。
- 不 push、不部署、不切流量。
- 不修改 app/services、app/database、data/canonical 或排序内核。
- 新 Guide 严禁 import app.services。
- 已迁能力内部失败必须 fail-closed，不回退旧 V2。
- 后端继续权威决定商品卡：单品/适配 1 卡、推荐 1–3 卡、比较 2–4 卡、
  知识/问诊收集/澄清/错误 0 卡。

每个 checkpoint 必须报告：
- capability_key / iteration_id
- audit_key 与 PASS/REUSED_PASS/LOCAL_BASELINE_ONLY 状态
- 是否发生真实 audit invocation（只能是 0 或 1）
- source commit、stable patch ID、最终 blob manifest
- focused/full/runtime/boundary/HTTP/browser 结果
- cumulative/input/output/cache-read/cache-write tokens
- cache hit rate、模型、价格快照、成本；不可得时明确 UNAVAILABLE
- 下一项立即执行的任务

现在从 phase2-integration 的 4 个未提交文件继续，不重新审计，不等待普通确认。
```
