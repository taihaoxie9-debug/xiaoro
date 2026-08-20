# 完整二期自适应恢复 Prompt

以下内容可直接作为新的 Goal / Ralph Loop 启动提示。

---

在 `/Users/bytedance/Desktop/xiaoro-fresh` 连续完成完整二期。执行期间采用自适应并发，
由 root orchestrator 根据风险、冲突、测试和资源状态自动在 2–8 个 agent 之间升降，
不要求用户逐次批准普通实现决策。

## 权威文档

开始前必须读取：

```text
.trae/specs/complete-phase2-continuously/spec.md
.trae/specs/complete-phase2-continuously/tasks.md
.trae/specs/complete-phase2-continuously/checklist.md
.trae/specs/complete-phase2-continuously/progress.md
.trae/specs/complete-phase2-continuously/autonomous-execution-policy.md
docs/superpowers/plans/2026-08-09-phase2-continuous-ralph.md
docs/superpowers/plans/2026-08-09-phase2-day1-stabilization.md
docs/audits/phase2-continuous/audit_ledger.csv
docs/audits/phase2-continuous/agent_token_usage.csv
```

`autonomous-execution-policy.md` 是并发、自治、审计、升级和遥测的权威治理文档。
若本 Prompt 与该文档冲突，以保护性更强的规则为准。

## 当前冻结状态

恢复前先机械核验，不得只相信文字：

```text
integration worktree: /private/tmp/xiaoro-phase2-integration
expected branch: phase2-integration
expected Round 13 code HEAD: 96cc7abe94cb6eff53674602f52086acbe1050c8
expected branch tip: the code HEAD above plus one Round 13 docs-only checkpoint commit
expected ranking SHA:
4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
```

当前已知状态：

- Day 1 共享地基已完成。
- consultation/profile 正式纵向已集成并在 Round 12 完成测试、浏览器和状态文档。
- 完整图片堆栈已在 Round 13 完成集成、唯一开场审计、5 个 P1 的 RED/GREEN 修复、
  全量验证、1/2/4 图与 consultation 浏览器矩阵和状态文档 checkpoint；代码完成点为
  `96cc7ab`。
- Round 13 唯一图片审计 key 为
  `de99b6096b1a476a5d515ff9ac6a4d0d0b9a1a6ed4635c5ef4cccdb41804afc4`，
  invocation 总数为 1；修复后未重复 full-file audit，post-fix key 只作 provenance，
  不声明 audit PASS。
- feedback 正式纵向已在独立 worktree 绿色完成：
  `/private/tmp/xiaoro-phase2-feedback-vertical`，源 HEAD `ad4251a`。
- 完整二期尚未完成，不得标记 `COMPLETE`。
- 未 push、未部署、未切流量。

如果实际 HEAD 或工作区与预期不同：

1. 先检查 `git status`、cherry-pick/rebase 状态和最近提交。
2. 不重置、不 checkout 覆盖、不删除用户变更。
3. 以最后一个干净冻结 SHA 为恢复点。
4. 对差异做 stable patch-id、blob manifest 和行为证据核对。

## 自适应并发政策

硬限制：

```text
active agents: 2–8
concurrent code writers: 0–4
integration writers: exactly 1 maximum
writers per file authority: exactly 1 maximum
```

默认模式：

| 模式 | Agent 数 | Writer 数 | 用途 |
|---|---:|---:|---|
| INCIDENT | 2–3 | 1 | 保护合同、数据、重复回归 |
| HIGH_RISK | 3–5 | 1–2 | integration 和共享文件冲突 |
| NORMAL | 5–7 | 2–4 | 独立 worktree 能力开发 |
| LOW_RISK_PARALLEL | 6–8 | 1–3 | 测试、浏览器、审计、文档核验 |

恢复时从 `HIGH_RISK` 开始，因为当前处于 feedback 向共享 API/SSE/runtime/frontend 收口阶段。

推荐初始角色：

1. 一个 integration owner，唯一写 `/private/tmp/xiaoro-phase2-integration`。
2. 一个只读 independent auditor，审查冻结 SHA。
3. 一个 focused/Guide verifier。
4. 一个 runtime/boundary verifier。
5. 一个 normal browser verifier。
6. 一个 adversarial browser verifier。

验证 agent 必须从冻结 SHA 创建只读验证 worktree，不能在测试期间让被测 HEAD 漂移。

### 自动升并发

最近两个 checkpoint 绿色、文件域无交集、integration 干净、没有未解释 flaky、
端口和状态目录隔离时，每次增加一个 agent；增加后观察至少一个 checkpoint。

### 自动降并发

发生同文件 writer 冲突、语义 merge conflict、重复 patch 风险、未知测试回归、浏览器串扰、
资源争用或高严重度 audit finding 时，立即减到 3–5；保护路径、Canonical、排序、反馈越权、
跨会话泄漏或旧 V2 fallback 异常时进入 `INCIDENT`，只保留一个 fixer 和一个 verifier。

不为追求 agent 数量创建无所有权任务。

## 自治与升级

以下问题自行解决并记录，不请求用户：

- import、类型、格式、fixture 和确定性局部回归。
- 测试端口冲突、临时 SQLite、浏览器状态和遗留进程。
- stable patch-id 已存在的重复提交。
- domain branch 中重复的旧 tasks/checklist/progress commit。
- owner matrix、CSV 和状态文档的纯加法冲突。
- 一个 agent 静默结束后，从最后干净 SHA 续派。
- 可由现有合同唯一决定的 API/SSE/frontend 合并。

共享合同冲突、重复 flaky 或审计 finding 自动降并发，按：

```text
freeze -> reproduce -> RED -> single-writer fix -> independent verify
```

只有以下情况升级给用户：

- 规格无法唯一决定产品语义。
- 需要改变范围、用户可见验收或保护路径。
- destructive migration、删除数据或不可逆操作。
- push、部署、切流量、购买服务或新增外部凭证。
- 隐私、法律、合规或安全政策选择。
- 同一硬阻塞在隔离后连续出现三次。
- 所有剩余任务共享同一个外部决策。

用户不在线时，暂停受阻线路并继续其他独立工作；不要反复询问同一问题。

## 不可变实现合同

- 新 Guide 禁止 import `app.services`。
- 不修改 `app/services/**`、`app/database/**`、`data/canonical/**` 和排序内核。
- OCR 只能产生 observation，不得覆盖 Canonical、winner 或排序。
- 内部错误不得静默回退旧 V2。
- 单品/适配严格 1 卡。
- 推荐严格 1–3 卡。
- 比较严格 2–4 卡。
- 知识、问诊收集、澄清和错误严格 0 卡。
- 共享 API、SSE、runtime composition、frontend 和状态文档只由 integration owner 写。

## 第一阶段：机械核验已完成的图片集成 checkpoint

不要重复 cherry-pick、审计或重跑已完成的 Round 13 图片工作。恢复时只核对：

```text
code HEAD: 96cc7abe94cb6eff53674602f52086acbe1050c8
opening scope manifest: 50661797490edba692d95e3886b7ecacac3c0eeb3b36d8094b8569f95eb2620e
audit invocation: 1
audit findings: P0=0 / P1=5 / P2=0
RED/fix/lazy-fix: 15c6168 / 7939494 / 96cc7ab
post-fix: targeted 367 + boundary 23, runtime 133, Guide 1801, static findings 0
single-image suitability: exactly 1 card or 0-card clarification
two-image compare: exactly 2 ordered cards
four-image compare: exactly 4 ordered cards
ordinal: stable and bundle-local
outcome: winner/tie/insufficient evidence
OCR: observed/unavailable only
OCR: no Canonical/ranking/card-count mutation
page/SSE/product-image errors: 0
```

对应 tasks/checklist、`Round 13`、audit ledger 的
`FINDINGS -> FINDINGS_CLEARED` 和 `IMAGE_VERTICAL_COMPLETE` Token row 已记录。
正向 tie 因 Canonical 没有受支持同品类同价样本记为 `N/A`，unit tie 与 adversarial
拒绝已通过，未修改数据。机械核验一致后直接进入 feedback 集成；若不一致，冻结现场，
不得重做审计或重复移植整个图片分支。

## 第二阶段：集成 feedback 正式纵向

先确认源 worktree 干净，并逐个比较 stable patch-id。源提交顺序：

```text
53a0ce5
bbe1abc
1f01991
06baa0c
d5549ac
6212104
c3217ad
4771e3b
ad4251a
```

`3060b63` 和 `67678bf` 已在旧基线存在，禁止重复移植。

冲突必须加法保留：

- consultation/profile authority
- single/two/four-image authority
- scenario/review/pitfall authority
- CardDisplayContract
- typed SSE 单终态
- session isolation、AbortController 和迟到响应忽略

必须验证：

```text
trusted delivered feedback target only
cross-session target -> 404
same idempotency key -> same event ID
late response -> ignored=true
feedback never mutates product facts or ranking
normal/adversarial feedback browser -> pass
page/SSE/product-image errors -> 0
```

集成后运行 feedback focused、正式 HTTP、frontend、runtime、Guide full、runtime full、
双 boundary、compileall、diff check、保护路径和排序 SHA。全部通过后更新 Task 4.3、
4.5–4.8、6.3 以及对应 checklist，并 append `Round 14` 和 Token checkpoint。

Task 4.3 只有在真实批准评论来源存在并通过正向 HTTP/browser summary 时才能勾选；
若批准来源仍为 0，只保留 verified absence，不伪造正向评论总结。

## 第三阶段：完整联合验证

所有能力集成后，冻结一个候选 SHA，在独立验证 worktree 并行运行：

1. 全部 focused 套件。
2. Guide full 和 runtime full。
3. compileall、双 boundary、diff check。
4. 保护路径树和排序 SHA。
5. normal browser 全矩阵。
6. adversarial browser 全矩阵。
7. 四条真实纵向：

```text
natural text -> constraints -> retrieval -> decision -> exact cards -> browser
1/2/4 images -> bundle -> OpenCLIP/OCR -> identity -> suitability/compare -> browser
knowledge -> consultation -> confirmation -> profile fill -> later recommendation
clean runtime -> health -> text/image/multi-turn/feedback -> zero old-service import
```

导出输入、图片 ID、候选、最终 ID、状态、失败原因、延迟和模型/索引版本证据。

## 第四阶段：唯一最终审计

只在联合验证全部绿色后创建不同的：

```text
capability_key = FINAL-PHASE2-AUDIT
```

对最终冻结 production scope 执行一次独立 full-file review：

- findings 按 P0、P1、P2 排序。
- finding 必须有文件和行号。
- 确认 finding 先写 RED 再修复。
- 修复后重跑正常质量门禁。
- 同一个 FINAL audit key 不得调用第二次 full-file review。

相同 audit profile + production blob manifest 必须复用已有 PASS。commit SHA、worktree、
rebase 或重启不构成新 audit key。

## Token 与缓存遥测

`get_goal.tokens_used=0` 已经校准为未接入默认值，禁止再当作真实 Token。

当前禁止运行 Trae CN 全历史 RPC 扫描。实测约 7GB 历史数据库会令
`Runtime.evaluate` 超时并触发 workbench renderer 重建。不得为了 Token 统计重启 Trae、
打开调试端口、启动第二实例、遍历 SQLCipher、扫描进程内存或调用第三方上传服务。

只有平台后续直接暴露当前 root 与 descendants 的有界 usage envelope，或有经过隔离验证的
当前会话增量 API 时，才恢复精确采集。遥测故障不得阻塞业务施工，也不得把采样失败写成 0。

每个正式 checkpoint 记录：

```text
input tokens
cache-read tokens
cache-write tokens
output tokens
reasoning tokens
total tokens
cache hit rate
source/session coverage
```

按 session/event ID 去重。字段缺失写 `UNAVAILABLE`，不得填默认 0 或估算值。

## 连续执行与完成条件

每个能力：

```text
RED -> implementation -> focused -> integration -> full -> browser
-> tasks/checklist -> progress -> audit ledger -> token ledger -> continue
```

普通 checkpoint 不等待用户确认。只有以下情况停止：

- 用户明确暂停。
- 所有剩余任务共享一个重大决策。
- 同一硬阻塞连续出现三次。
- 完整二期真正完成。

只有 tasks/checklist 全部勾选、十项能力有机械证据、四条真实纵向通过、全量和双浏览器
通过、唯一 FINAL audit 无未解决 P0–P2、保护路径和排序不变、工作区干净后，才允许标记
`COMPLETE`。

始终保持：

```text
no push
no deployment
no traffic switch
```
