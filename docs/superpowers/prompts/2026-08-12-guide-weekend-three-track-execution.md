# Guide 三条主线周末收口续跑 Prompt

把本文件完整内容作为新会话 Prompt 使用。收到本 Prompt 后才开始执行；创建本文件的
当前会话只负责审计和规划，不执行实现。

## 1. 唯一工作区

```text
/Users/bytedance/Desktop/xiaoro-fresh
```

分支必须是：

```text
rebuild
```

执行前必须证明 HEAD 包含计划冻结提交：

```text
690d8bd
```

`/Users/bytedance/Desktop/xiaoro-shopping-master` 是旧仓库。用户 IDE 可能打开其中的
`app/services/v2/presenter.py`，不得在旧仓库修补 Presenter 或实现本任务。

## 2. 权威文档

必须由主线程完整读取：

1. `docs/superpowers/specs/2026-08-12-guide-three-track-weekend-closure-design.md`
2. `docs/superpowers/plans/2026-08-12-guide-only-entry-implementation.md`
3. `docs/superpowers/plans/2026-08-12-pilot-data-recovery-implementation.md`
4. `docs/superpowers/plans/2026-08-12-two-stage-intent-implementation.md`
5. `docs/superpowers/plans/2026-08-12-weekend-integration-closure-implementation.md`
6. `.trae/specs/complete-guide-closure-continuously/spec.md`
7. `.trae/specs/complete-guide-closure-continuously/tasks.md`
8. `.trae/specs/complete-guide-closure-continuously/checklist.md`
9. `.trae/specs/complete-guide-closure-continuously/progress.md`

若旧 spec/tasks 的依赖与 2026-08-12 周末收口设计冲突，以用户已批准的新设计为准。
特别是：

- Guide 唯一入口不再等待模型 128/128；
- 模型失败由 Guide fail-closed clarification，不回旧 V1/V2；
- 数据采用数据库优先、HTML 核对，不从零重挖 103 商品；
- 意图采用两步语义理解和分层生产门禁。

## 3. 用户已确认的范围

### Track A：Guide 唯一入口

- 所有公开 message/stream 只进入 Guide。
- 未支持、低置信或 provider 失败由 Guide 追问/说明范围。
- 永不回退 V1/V2。
- 澄清同一 gap 最多两轮，第三轮返回 scope notice。
- 成功理解后原子清零澄清进度。

### Track B：15 商品数据闭环

固定商品：

```text
38,42,49,53,55,57,69,79,80,86,91,103,114,120,121
```

- 复用 `data/seed_dump.sql` 中已有字段。
- HTML 只核对关键字段和补缺。
- 用户已批准只读来源根：

```text
/Users/bytedance/Downloads
/Users/bytedance/Desktop/xiaoro-fresh/data
```

- 三份历史 HTML 已确认存在且 SHA 匹配：

```text
b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4
55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44
56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783
```

- 自动化只生成 pending/quarantine/unknown，writer 不得自行批准或 promotion。
- 每个可批准候选由两个未参与生成的只读 verifier 独立核对，只有 2/2 对来源、SKU、
  字段适用性、权限和值达成一致才形成共识。
- 独立 signer 只为 2/2 共识生成
  `reviewer=agent_verifier_consensus_v1` 的签名 review decision。
- 只有 Integration Writer 可验证签名决定并调用既有 promotion 工具。

### Track C：两步语义理解

- 第一步判断 goal/topic/detail stage。
- 第二步只提取当前场景需要的语义字段。
- exact code 独占金额、范围、数字方向、否定、成分排除和显式 ordinal。
- 两步结果仍投影到唯一 `SemanticIntentProposal`，进入唯一 merger。
- 先用 V4-Flash/V3.2；只有新设计仍失败才讨论换模型。

## 4. 不得重复的工作

- 不重跑 Task 0 或任何正式 full-file audit。
- 唯一 audit key 固定：

```text
b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da
```

- formal invocation 必须保持 1，repeat 必须保持 0。
- 不重新实现 Phase 2 或 Phase 3A。
- 不修改 Canonical 商品身份、品牌、品类、价格。
- 不修改 deterministic ranking 逻辑。
- 不伪造历史 336/111。
- 不用旧聚合文本反向伪造 HTML。
- 不在 API、Presenter、retrieval、presentation 添加语义补丁。
- 不创建新的 legacy/archive 代码目录。

## 5. Agent 和文件所有权

用户明确允许使用多个子代理。采用：

- 1 个 Track A writer；
- 1 个 Track B writer；
- 1 个 Track C writer；
- 1 个 Integration Writer；
- 2–3 个只读 verifier；
- 1 个独立 signer；
- 总数 2–8，同一时间最多 4 个 writer。

固定所有权：

```text
Track A:
  public API / guide runtime / clarification state / startup files

Track B:
  tools/guide_data / data-only tests / local recovery reports
  pending / quarantine / review matrix generation only

Track C:
  understanding / intent LLM adapters / model gates

Integration Writer only:
  app/guide_runtime/composition.py
  shared contracts touched by multiple tracks
  app/main.py
  app/config.py
  app/tasks/worker.py
  physical git rm
  tasks/checklist/progress
  signed decision validation
  promotion command invocation and promoted production outputs

Read-only verifier:
  no repository file modification
  targeted code/gate verdict or candidate evidence verdict only

Signer:
  signed review decision artifact only after matching verifier 2/2 verdicts
  no candidate mutation, promotion, or production data write
```

同一文件同时最多一个 writer。每个 track 必须先在独立 worktree 提交并通过 focused
gate；每个冻结 writer commit 还必须由至少一个未参与该提交的 verifier 定向检查代码、
测试、边界和证据并给出 PASS，Integration Writer 才能集成。verifier FAIL 的提交不得
cherry-pick、复制或手工绕过。

建议 worktree：

```text
/private/tmp/xiaoro-weekend-entry
/private/tmp/xiaoro-weekend-data
/private/tmp/xiaoro-weekend-intent
```

## 6. 执行顺序

### Phase 0：有界预检

只做：

```bash
git status --short --branch
git merge-base --is-ancestor 690d8bd HEAD
wc -l docs/audits/guide-closure/audit_ledger.csv
ps process audit
```

不得运行测试、网络或 formal audit。

### Phase 0.5：自动循环协议

每条路径固定执行以下闭环，不等待逐文件用户审核：

```text
writer RED/GREEN -> frozen commit -> independent verifier
  -> PASS: Integration Writer 受控集成
  -> FAIL: 记录最早失败层和 RED，返回原 writer 一次定向修复
```

- 同一最早失败层第一次 FAIL 后只允许一次定向修复。
- 修复后第二次 FAIL 立即停止该路径，记录卡点并回到设计层裁决；禁止第三次盲修。
- 每个 frozen commit、verifier verdict、集成结果和 gate 结果都必须写固定 checkpoint。
- 无止损条件时，checkpoint 是自动记录点，不是用户 approval gate。

### Phase 1：三个 track 并行

严格按对应 implementation plan 的任务和提交点执行：

- Track A 先完成澄清状态和 Guide-only 默认入口。
- Track B 先修正来源根，再读 products COPY，再做数据库候选和真实保存页 parser。
- Track C 先做 route/detail 合同和离线 smoke gate，不先跑真实 A/B。

### Phase 2：第一次集成

集成 A/B/C 已通过 focused gate 和独立 verifier PASS 的提交，然后：

- composition 切到两步 adapter；
- Guide-only import boundary；
- 数据报告修正为 found=3/missing=0；
- 32 条 smoke gate。

### Phase 3：真实 A/B

只有以下同时满足才运行：

- 32 条 smoke route-critical >= 85%；
- 所有安全硬门为 0；
- `GUIDE_LLM_API_KEY` 环境变量存在；
- Key 不进入 argv/log/report/Git。

真实 A/B：

- 每 30 秒心跳；
- 前 20 条 unavailable/timeout > 10% 立即停止；
- 45 分钟总硬超时；
- TERM 后 5 秒仍存活则 KILL；
- 结束后审计无残留。

### Phase 4：旧链删除

必须先完成 importer inventory，再按计划：

- 收缩 `app.main`；
- 清除 config/Celery old chat importer；
- 删除旧 API、V1/V2 Agent、Intent、Presenter；
- 删除旧专属 tests/scripts；
- importer after 必须为 0。

不得为了通过收集而恢复空壳旧模块。

### Phase 5：最终门禁

使用 `tools/guide_gates/run_bounded_command.py`，固定 30 秒心跳，并为每个命令设置计划
给出的硬超时。超时时先向整个进程组 TERM，5 秒后仍存活则 KILL；runner 返回后必须核对
summary 和无残留进程。禁止直接绕过 runner 执行长 gate：

1. focused；
2. Guide full；
3. remaining tests；
4. compileall；
5. 双 boundary；
6. dependency inventory；
7. 2/4 worker、restart、stale/CAS、terminal delivery；
8. normal/adversarial browser；
9. protected asset hash；
10. worktree/process audit。

## 7. 安全硬门和质量门

以下始终零容忍：

```text
hard_constraint_override_count = 0
forbidden_field_acceptance_count = 0
invalid_output_task_plan_invocation_count = 0
unsafe_task_plan_mismatch_count = 0
wrong_product_selection_count = 0
legacy_fallback_count = 0
critical_route_error_count = 0
```

质量门：

```text
route-critical >= 95%
scenario detail key fields >= 90%
remaining uncertain cases => fail-closed clarification
```

安全地多问一句计为 `safe_clarification_mismatch`，进入质量统计但不是硬失败。错误执行
mode、错误约束、错误指代或错误选品仍是硬失败。

## 8. 已知坑点

执行前必须重读设计文档 8.1。特别注意：

- 不要进入旧仓库；
- inventory 数量大不代表覆盖 Downloads；
- fixture parser 不能解析真实天猫页；
- SQL dump 只能解析 `COPY public.products` 区段；
- 三份页当前显式只有 6 条评论，不能硬凑 336/111；
- Compose 会覆盖 Docker CMD；
- clarification 当前没有持久状态；
- importer 未清零前不能删旧链；
- 不能继续扩大 13 KB Prompt；
- 不能只降阈值；
- 两阶段共享一次 repair，最多三次 provider 请求；
- 更多 Agent 不能掩盖文件冲突；
- 禁止无监管长测试；
- 禁止第二次正式审计。

## 9. 止损规则

出现任一情况立即停止当前路径并记录止损 checkpoint：

- 同一最早失败层连续第二次失败；
- 32 条 smoke route-critical < 85%；
- provider 前 20 条失败 > 10%；
- product/item/SKU/source SHA 无法绑定；
- 新入口出现任意 legacy fallback；
- 长任务 10 分钟无输出且无法解释；
- 预计完成偏离超过半天；
- writer 文件域冲突；
- 任何保护资产未授权漂移。

最早失败层计数固定为：

- 第一次 FAIL：`consecutive_failures=1`，写 RED，只允许一次定向修复；
- 第二次连续 FAIL：`consecutive_failures=2`，自动停止该路径并回到设计层；
- 只有设计裁决改变失败层、合同或证据后才可清零；通过重跑、换措辞或换 Agent 不得清零。

停止后不要启动新的代理或第三轮盲修，立即记录并向用户说明：

```text
已完成：
当前卡点：
为什么当前方向可能不对：
可选修正方向：
剩余工作：
预计完成：
```

## 10. 固定 checkpoint 汇报

以下事件必须自动追加 checkpoint：每个 frozen writer commit、每个 verifier verdict、每次
Integration Writer 集成或 promotion、每个 gate 结束，以及任何止损触发。不得等用户逐
文件确认，也不得把 checkpoint 当作人工 promotion gate。

每个 checkpoint 固定只记录：

```text
已完成：
当前卡点：
剩余工作：
预计完成：
```

`当前卡点` 必须包含 `earliest_failure_layer` 和 `consecutive_failures=0|1|2`；无卡点时
明确写无。checkpoint 写完后，无止损条件的路径自动继续。

## 11. 双 verifier 与受控 promotion

生成 `pilot_review_matrix.md` 后按候选执行以下自动闭环：

1. 冻结 candidate、quarantine、来源证据和各自 SHA。
2. verifier A 和 verifier B 从相同冻结输入独立核对
   `product_id/profile/field/normalized value/source class/source hash`，以及
   item/SKU 绑定、字段适用性、来源权限和保护资产边界；二者不得读取或修改对方 verdict。
3. 只有两个 verdict 均为 PASS 且候选值、证据身份完全一致，才视为 2/2 共识。
4. 任一 REJECT、无法绑定、权限不足或 verdict 分歧时，不生成批准决定；冲突项进入
   quarantine，其余保持 pending/unknown。
5. 独立 signer 校验两个 verifier 身份、冻结 SHA 和 2/2 共识后，生成包含
   `reviewer=agent_verifier_consensus_v1` 的 HMAC 签名 review decision。
6. Integration Writer 是唯一可验证 candidate、quarantine、decision SHA 与 HMAC，并
   调用既有 promotion 工具的角色。

Track B writer、verifier 和 signer 均不得直接 promotion。任何缺失的 verifier verdict、
签名或 SHA 校验都必须 fail closed，字段保持 pending/unknown；不得转为逐文件用户审核或
人工 approval gate。

## 12. 最终交付边界

只有全部满足才标 COMPLETE：

- 所有公开聊天只走 Guide；
- 旧聊天链物理删除；
- 15 商品状态可追溯，promoted 字段均有 verifier 2/2 共识和签名决定；
- 三份历史 HTML found=3；
- 两步意图通过硬门和质量门；
- provider 失败只触发 Guide clarification；
- focused/full/runtime/browser/cross-worker 全绿；
- importer 0；
- audit invocation=1/repeat=0；
- worktree clean；
- 无残留进程；
- 未 push；
- 未 deploy；
- 未切生产流量。

若截至周日仍有未满足项，必须明确标 INCOMPLETE 并列出实际剩余项，禁止为了期限勾选。
