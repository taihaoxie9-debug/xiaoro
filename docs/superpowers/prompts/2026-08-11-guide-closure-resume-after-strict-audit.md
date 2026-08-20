# Guide Closure Strict-Audit Resume Prompt

以下内容用于从 2026-08-11 严格审计后的真实 checkpoint 继续长循环。
它取代旧 Prompt 中“从 Task 0 开始”的恢复指令，但不修改既有设计、计划或历史证据。

```text
/ralph-loop

在以下唯一实施仓库连续完成 Guide closure：

/Users/bytedance/Desktop/xiaoro-fresh

目标分支：

rebuild

不要把 /Users/bytedance/Desktop/xiaoro-shopping-master 当作实施仓库。它是旧且脏的
main 工作区，只允许按既有数据恢复计划做受限只读来源扫描。

## 0. 当前恢复事实

开始时核对而不是重做：

- 预期主线 checkpoint：b20a714c0bde21bd500228b94bcb67c79f5c52fe
  或其严格后继提交。
- 工作区必须 clean。
- Phase 2 十天业务矩阵已经 COMPLETE，不得重复实现。
- Guide closure Tasks 1–5、7、9、10 已完成。
- Task 6 仅完成 6.1–6.4；6.5–6.7 未完成。
- Tasks 8、11、12、13 未完成。
- 正式 full-file audit 已经真实执行且只允许这一次：
  - profile: guide-closure-full-file-v1
  - audit key:
    b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da
  - real invocations: 1
  - authoritative ledger:
    docs/audits/guide-closure/audit_ledger.csv
- baseline_manifest.json 中 PLANNED/real_invocations=0 是审计调用前的冻结快照，
  不得据此重新执行 Task 0；审计调用事实以 append-only ledger 为准。
- 候选 worktree /private/tmp/xiaoro-guide-task6-real-gate 的 e3e123a
  尚未集成，不得当作主线完成事实，也不得整栈盲目 cherry-pick。
- GUIDE_LLM_API_KEY 可能缺失。只检查 PRESENT/MISSING，不读取或打印值。

如果 HEAD 不是 b20a714 或其后继，先用 git log、merge-base、tasks/checklist 和
audit ledger 判断是否为合法后续集成。不得 reset、restore、checkout、stash、clean
或覆盖用户变更。

## 1. 权威文档

完整读取并按以下优先级执行：

1. docs/superpowers/specs/2026-08-10-guide-intent-cutover-and-pragmatic-data-recovery-design.md
2. docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md
3. docs/superpowers/plans/2026-08-11-guide-intent-cutover-closure.md
4. docs/superpowers/plans/2026-08-11-pragmatic-data-recovery.md
5. .trae/specs/complete-guide-closure-continuously/spec.md
6. .trae/specs/complete-guide-closure-continuously/tasks.md
7. .trae/specs/complete-guide-closure-continuously/checklist.md
8. 本 Prompt

不要恢复旧 Phase 2 的 capability/final audit 规则。不要执行旧 Prompt 最后一行的
“从 Task 0 开始”。

## 2. 本轮硬规则

### 2.1 禁止无意义补丁

每个失败先冻结输入，并依次记录：

exact
-> semantic proposal
-> merger trace
-> TaskPlan
-> RetrievalResult
-> DecisionResult
-> ResponsePlan/SSE
-> conversation state

第一处违反 typed contract 的层才是责任层。只在该层写 RED 和通用修复。

禁止：

- 为单句或单个 fixture 增加全句关键词/正则；
- 在 API、Presenter、前端重解释意图；
- retrieval/presentation 二次过滤、打分或选 winner；
- 修改 Golden/expected 掩盖行为漂移；
- 新增“测试专用生产旁路”后把旁路结果冒充公开主链结果；
- 把旧 V1/V2 函数复制、包装或搬迁到 Guide；
- 修补即将删除的 app/services 旧聊天模块；
- 用 UNAVAILABLE、None 或常量 0 冒充 hard gate PASS。

责任层固定：

- 数字、预算、明确否定、成分有无、source span：exact understanding；
- goal、topic、观察、指代：semantic prompt/schema/adapter；
- 信号冲突和低置信：IntentSignalMerger；
- 闭合操作是否允许跳过模型：operation authorization/application orchestration；
- TaskPlan 正确但候选错误：retrieval/data；
- 候选正确但过滤/排序错误：decision；
- DecisionResult 正确但展示错误：presentation；
- 串会话、丢状态、CAS/version：state；
- 进入旧链：composition/transport。

### 2.2 唯一正式审计

formal_full_file_audit_invocations 必须永久保持 1。

从现在起禁止：

- 调用任何新的正式 full-file audit；
- 创建新 audit key；
- capability audit；
- final audit；
- 以“复审”“再审”“独立审计”换名重复调用。

后续角色统一称 verifier，不称 auditor。允许且必须自动执行：

- changed-files targeted review；
- RED/GREEN；
- focused/full/runtime；
- compileall、双 boundary、diff-check；
- frozen SHA verifier；
- cross-worker、browser、dependency inventory。

这些都不是正式 audit，不需要用户批准。

### 2.3 不等待用户

普通 checkpoint、测试失败、import/type/fixture 问题、Agent 完成、提交集成和
门禁复跑都自动继续。不要调用 AskUserQuestion 或 NotifyUser 请求计划/阶段批准。

只有以下情况可以暂停：

- 新 Key、付费服务或外部凭证是唯一剩余硬门；
- push、deploy、生产流量切换；
- 新事实/评论批准；
- destructive data migration；
- 现有规格无法唯一裁决产品语义；
- 同一外部阻塞在隔离处理后连续出现 3 次。

一条线阻塞时继续所有不依赖它的工作。

## 3. 动态 Agent 策略

当前从 INCIDENT 模式开始，因为 A/B vertical 与真实生产路由证据仍混淆：

- Root Orchestrator：1
- Fixer/Writer：1
- Independent read-only verifier：1
- 同一时刻最多一个 Integration Writer
- 同一文件 authority 最多一个 writer

同一冻结 SHA、同一文件范围只能有一个权威 verifier。禁止并发启动两个重叠
“final verifier”。若两个 verifier 结论冲突，PASS 立即失效，降回 INCIDENT，
冻结同一 SHA 后由一个权威 verifier 重跑。

Agent 完成后立即收集结论并关闭，不允许已完成 Agent 长期显示 running/pending。
不得让 verifier 修改被验 worktree。

连续两个 checkpoint 全绿、无共享文件冲突、无未知 flaky 后，按任务机械程度逐次扩容：

- 机械 inventory、互不相交测试、browser/runtime 可升到 4–6 active agents；
- 最多 8 active agents、最多 4 writers；
- 优先增加只读 verifier，不为占满并发增加 writer；
- 出现合同冲突、旧链触发、状态泄漏、保护资产漂移或门禁结论冲突时，
  立即降回 1 fixer + 1 verifier。

## 4. 第一阶段：修正证据边界并收敛候选 e3e123a

不要先改代码。先由唯一 verifier 对 b20a714..e3e123a 做 changed-files review。

必须把两个门禁拆开：

1. Model vertical gate
   - 目的：判断同一 validated semantic proposal 经 exact + merger + TaskPlan +
     real Guide retrieval/decision/presentation 后是否违反硬门；
   - 可隔离顶层 followup dispatcher，但必须明确命名为 model vertical，
     不得声称代表公开生产路由。
2. Production routing gate
   - 必须调用真实公开 TextRecommendationOrchestrator.stream 或最终公开 HTTP；
   - fixture context 中 visible_candidate_count、active_topic、conversation_version
     必须由可信测试状态构造，不能用空 SQLite 状态代替；
   - 证明只有具备消息绑定、协议闭合 typed proof 的 operation 才跳过 semantic；
   - 普通自然语言必须走 parallel understanding；
   - provider failure 不得进入 V1/V2；
   - legacy fallback 和错误选品均为 0。

已知 RED 证据中 21/128 semantic 调用为 0，但不得直接把 21 全部定性为生产缺陷：

- ordinal/followup 中可能存在合法闭合操作；
- 原 evaluator 没有按 fixture context 构造候选快照；
- e3e123a 的 stream_text_vertical 又绕过了生产 pre-router。

先按每 case 的 typed proof 和可信 snapshot 分类：

- 合法闭合操作：允许 semantic=0，但必须有可复算 proof；
- 普通/开放语义：semantic 必须恰好调用 1 次；
- 缺失状态：typed clarification，不得伪造候选；
- evaluator 自身状态不真实：修 gate，不修生产行为。

如果确认生产 operation authorization 错误，修复必须落在
TextRecommendationOrchestrator/operation authorization 责任层，复用已有
ParallelUnderstanding 的 closed-proof 合同。不得保留测试旁路来掩盖真实 stream。

候选中的 typed usage、stable evidence、UNAVAILABLE cost、legacy observer 等提交
只能逐提交验收并集成。集成前记录 source SHA、patch ID、diff scope、focused
和唯一 verifier 结论。

## 5. 第二阶段：真实模型 A/B

先完成全部不依赖 Key 的 gate 和文档证据，再检查：

GUIDE_LLM_API_KEY=PRESENT/MISSING

Key 安全：

- 只从环境读取；
- 不打印、不 repr、不写日志/命令参数/报告/cache/Git；
- 不扫描 shell history、旧聊天或文件寻找 Key；
- 曾公开的旧 Key 视为无效。

若 PRESENT：

- 使用同一 128 cases、同一 prompt/schema、temperature=0、同参数；
- 显式运行：
  deepseek-ai/DeepSeek-V4-Flash
  deepseek-ai/DeepSeek-V3.2
- 每模型每 case 只发一次正常请求；最多一次规格允许的格式修复重试；
- usage 来自同一 provider response；
- latency 单独记录，不进入 stable semantic evidence hash；
- actual cost 无可核验账单时写 UNAVAILABLE，不估算；
- 输出不得含 Key、Authorization、完整画像、商品事实或 raw provider body；
- hard constraint override、forbidden-to-TaskPlan、wrong selection、
  legacy fallback 必须真实 AVAILABLE 且均为 0。

选择：

- 两者通过：选 V4-Flash；
- 仅 V3.2 通过：选 V3.2；
- 两者失败：禁止 cutover；先修 prompt/schema/context/merger 的通用问题，
  每个 finding 有泛化 RED，最多 3 个连续修复循环；
- 仍失败：保持 typed clarification，记录 NO-GO，不加句式补丁。

生成 docs/audits/guide-closure/model_selection.md，记录 evidence hash、模型、
prompt/schema、usage、latency、cost status 和 hard gates。

若 MISSING：

- 完成所有离线候选收敛、production routing gate 和进度证据；
- 当真实 A/B 成为唯一剩余前置条件时暂停；
- 只报告“需要 fresh GUIDE_LLM_API_KEY”，不得继续 Task 8。

## 6. 第三阶段：依赖顺序

真实 A/B 至少一个模型全部 hard gates 通过后，才按顺序执行：

1. Task 8 Guide-only cutover
   - Dockerfile、Compose、start、README、DEPLOY 默认 Guide runtime；
   - message/stream 只走 Guide；
   - 删除公开 ChatOwner.LEGACY fallback；
   - unresolved clarification count 持久化；
   - 1–2 轮澄清后明确 scope；
   - 默认 runtime import 零旧 services/database/Redis/Milvus/Agent；
   - HTTP/SSE 单终态、错误脱敏、normal/adversarial browser。
2. Task 11 旧链删除
   - 先做 AST + dynamic-string + runtime/test/script/background inventory；
   - runtime importers 非 0 时先迁移入口，不得提前删除；
   - app/main.py 收缩为 Guide compatibility export；
   - 清除 config/Celery/prompts 旧聊天注册；
   - 只用 git rm 删除已证明不可达的 app/services/v2、agent、intent、
     Presenter 和专属测试/脚本；
   - 不编辑、修补、复制旧模块；
   - 删除后 runtime importer=0，活动代码树无 legacy/archive。
3. Task 12 最终机械/模型/状态/browser 收口
   - focused、Guide full、runtime full、整个剩余 tests；
   - compileall、双 boundary、diff-check、dependency inventory；
   - 真实 A/B replay；
   - 2/4 worker、restart、stale/CAS、terminal delivery；
   - normal/adversarial/XSS/session-switch/late-event/image browser；
   - Canonical 103、排序 SHA、6 条批准评论无漂移。
4. Task 13 状态收口
   - audit invocation=1、repeat=0；
   - tasks/checklist 只勾真实完成项；
   - 写 final_handoff；
   - append progress summary；
   - 工作区 clean；
   - 未 push、未 deploy、未切流。

## 7. 进度证据修复

当前 .trae/specs/complete-guide-closure-continuously/progress.md 为空，
而 tasks/checklist 已有大量完成项。先从 Git commits、audit ledger、冻结报告和
真实测试输出重建 append-only checkpoint 摘要：

- 不补写不存在的测试；
- 不把 worktree 候选当主线；
- 不把历史 Agent 自报 PASS 当成权威 verifier；
- 不修改 opening audit 次数；
- 不重写历史，只追加可追溯 checkpoint；
- 记录 b20a714 主线状态、e3e123a 候选状态和当前 blocker。

这属于文档 provenance 修复，不是新的正式审计。

## 8. 每个 checkpoint

每个 checkpoint 自动提交并继续，报告：

- task/subtask；
- mode、active agents、writers；
- source/integration SHA；
- 唯一 authoritative verifier SHA/结论；
- RED/GREEN 与最早责任层；
- focused/full/runtime/boundary/browser；
- model/prompt/schema/usage/latency/cost status；
- audit key 固定值、formal invocation=1、repeat=0；
- protected hashes；
- 未完成依赖和下一任务。

不要让状态文档领先于代码和证据。

## 9. 完成条件

只有 tasks/checklist 全部有真实证据，且以下全部成立才标 COMPLETE：

- 三路意图接入真实公开主链；
- 闭合 operation skip 有消息绑定 typed proof；
- 双模型真实 A/B 已选择默认模型；
- hard override/forbidden/wrong selection/legacy fallback 均为 0；
- Guide-only 默认启动和公开 API；
- 旧 Agent、Presenter、旧意图链物理删除；
- 2/4 worker 状态通过；
- full/runtime/all tests/browser 全绿；
- Canonical、排序、批准数据无漂移；
- formal audit invocation=1、repeat=0；
- 工作区 clean；
- 未 push、未 deploy、未切流。

现在从“进度证据修复 + e3e123a 单一权威 verifier”开始，不重新执行 Task 0，
不重新讨论已批准设计，不等待普通用户确认。
```
