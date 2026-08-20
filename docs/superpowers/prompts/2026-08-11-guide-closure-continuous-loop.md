# Guide 意图闭环、唯一入口和数据恢复连续循环 Prompt

以下内容可直接用于目标模式/循环模式。

```text
/ralph-loop

在以下仓库连续完成 Guide 意图闭环、唯一入口、务实数据恢复和旧链物理清理：

/Users/bytedance/Desktop/xiaoro-fresh

目标分支：

rebuild

必须存在的规划基线祖先：

c677d7fd50e5697700e1fde65a6540ab99da98d2

开始前先运行：

git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor \
  c677d7fd50e5697700e1fde65a6540ab99da98d2 HEAD

要求：

- 工作区必须干净。
- 当前 HEAD 必须包含上述规划基线和本 Prompt。
- 不得 reset、restore、checkout、stash、clean 或覆盖用户变更。
- 若现场与预期不同，先冻结并解释差异；不要自行回退历史。

## 一、权威文档和冲突优先级

必须按以下顺序读取完整文件：

1. docs/superpowers/specs/2026-08-10-guide-intent-cutover-and-pragmatic-data-recovery-design.md
2. docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md
3. docs/superpowers/plans/2026-08-11-guide-intent-cutover-closure.md
4. docs/superpowers/plans/2026-08-11-pragmatic-data-recovery.md
5. .trae/specs/complete-phase2-continuously/**
6. .trae/specs/complete-category-aware-guide-data-foundation/**
7. 两个项目的 autonomous-execution-policy.md

冲突处理必须使用下列固定裁决，不得折中叠补丁：

- 2026-08-10 新设计覆盖旧的整体 COMPLETE 口径；当前整体终态是 INCOMPLETE。
- 二期业务纵向矩阵完成事实保留，不重复实现已完成能力。
- 旧文档中的 `unsupported -> legacy` 被新设计的
  `Guide 追问 1–2 句 -> 说明范围` 覆盖。
- 本项目整个执行期只做一次开场正式全范围独立审计。
- 不做每 capability full-file audit，不做最终第二次 full-file audit。
- 旧文档中的 no-LLM 是历史 slice 离线门禁，不覆盖本项目真实模型 A/B。
- `app/services/**` 在旧链物理删除阶段前仍是保护路径。
- 只有核心计划 Task 9/设计 Phase G 可以删除已证明不可达的旧聊天模块；
  禁止修补、包装或搬迁这些旧模块。
- `data/canonical/**` 和
  `app/guide/decision/deterministic_ranking.py` 全程不可修改。
- HTML/OCR/评论候选不得自动批准或 promotion。
- 不 push、不部署、不切流量。

废弃草案和旧执行 Prompt 只作历史证据，不得恢复其执行顺序：

- rebuild/ARCHITECTURE.md
- rebuild/MIGRATION_CHECKLIST.md
- rebuild/EXECUTION_PLAN.md
- 旧 Phase 2 resume Prompt 中的 per-capability/final audit 规则

## 二、最终目标

必须同时完成：

1. 三路并行意图：
   - 精确代码路负责数字、预算方向、明确否定、成分有无和 source span；
   - 受限 LLM 路负责 goal、topic、观察、指代和置信度；
   - 会话/画像路只补空；
   - 唯一 IntentSignalMerger 交叉验证。
2. SiliconFlow：
   - V4-Flash 与 V3.2 同题真实 A/B；
   - 禁止字段、低置信、冲突和非法 JSON fail-closed；
   - 模型不接触商品事实、候选 ID、score、winner、SQL。
3. 普通文本使用共享 SQLite CAS，跨 2/4 worker 不丢追问状态。
4. Docker、start、README、DEPLOY 默认启动
   `app.guide_runtime.app:app`。
5. 公开 chat/message 与 chat/stream 只走 Guide，不再 fallback 旧 V1/V2。
6. Guide-only 全门禁通过后，物理删除旧 Agent、Presenter、旧意图链和旧入口专属依赖。
7. 只读盘点现有 HTML/OCR/图片来源，为 12 个品类试点和商品 42/49/55
   生成 pending/quarantine。
8. 找不到来源时舍弃字段/证据并保持 unknown；核心身份可信时保留商品。
9. 不自动批准，不修改生产 category/review assets。

## 三、API Key 安全

开始时只检查以下环境变量是否存在，不得打印值：

GUIDE_LLM_API_KEY
GUIDE_LLM_BASE_URL

检查方式：

python3 - <<'PY'
import os
print("GUIDE_LLM_API_KEY_PRESENT=" + str(bool(
    os.environ.get("GUIDE_LLM_API_KEY", "").strip()
)))
print("GUIDE_LLM_BASE_URL_PRESENT=" + str(bool(
    os.environ.get("GUIDE_LLM_BASE_URL", "").strip()
)))
PY

硬规则：

- 不得 echo、cat、repr、日志打印或报告 Key。
- 不得把 Key 放进命令参数、代码、测试、fixture、缓存键、截图或 Git。
- 不得扫描 shell history 或旧聊天记录寻找 Key。
- 若 Key 不存在，继续完成离线合同、merger、数据盘点、状态和测试工作；
  只有真实 A/B 和 cutover 仍是唯一剩余硬门时才暂停并报告。
- 曾公开过的旧 Key 视为无效，不得使用。

## 四、动态 Agent 调度

硬上限：

active agents: 2–8
concurrent code writers: 0–4
integration writers: exactly 1 maximum
writers per file authority: exactly 1 maximum
independent read-only auditor/verifier: at least 1

从 HIGH_RISK 启动，初始 5 个角色：

1. Root Orchestrator
   - 只负责风险、任务、证据、并发升降和停止条件。
2. Integration Writer
   - 唯一写 integration branch、共享合同、composition、公开入口和状态文档。
3. Intent Writer
   - semantic contracts、provider port、merger 独立文件域。
4. Evaluation/Data Writer
   - 模型 A/B runner 或数据 inventory，按文件域拆分时可扩成两个 writer。
5. Independent Auditor/Verifier
   - 冻结 SHA 只读审查和验证，不修改被审计 worktree。

意图合同冻结且连续两个 checkpoint 绿色后，可逐次升到 6–7 个 Agent：

- 增加跨 worker verifier；
- 增加 runtime/full verifier；
- 增加 normal/adversarial browser verifier；
- 优先增加只读 verifier，不为占满并发增加 writer。

出现任一条件立即降到 INCIDENT：

- 两个 writer 修改同一文件或同一 authority；
- 共享合同冲突；
- 模型覆盖硬约束；
- 旧 V1/V2 fallback 被触发；
- Canonical、排序、卡片权威或批准资产漂移；
- 跨 worker/session 泄漏；
- focused/full/browser 结论不一致；
- 同一测试隔离后重复失败；
- Agent 无法提供提交、测试和证据映射。

INCIDENT 默认：

1 fixer + 1 verifier

必要时增加 1 个只读 auditor。不要让多个 Agent 同时修同一个失败。

## 五、Worktree 和文件所有权

创建唯一 integration worktree，若已存在则先验证状态：

/private/tmp/xiaoro-guide-closure-integration

每条 writer 线使用独立 worktree。共享文件只由 Integration Writer 写：

- app/guide/understanding/contracts.py
- app/guide/understanding/ports.py
- app/guide/application/text_recommendation_flow.py
- app/guide/application/chat_api_adapter.py
- app/guide_runtime/composition.py
- app/guide_runtime/sse.py
- app/guide_runtime/app.py
- Dockerfile
- docker-compose*.yml
- start.sh
- README.md
- DEPLOY.md
- docs/audits/guide-closure/**

Intent Writer 独占：

- app/guide/understanding/semantic_contracts.py
- app/guide/understanding/parallel_understanding.py
- app/guide/intent/signal_merger.py
- app/guide/adapters/llm/**
- 对应 focused tests

Data Writer 独占：

- tools/guide_data/inventory_local_sources.py
- tools/guide_data/find_locked_review_sources.py
- tools/guide_data/report_pilot_field_coverage.py
- 对应 data-tool tests

Evaluation Writer 独占：

- tests/fixtures/guide/intent/**
- tools/guide_gates/intent_model_ab.py
- tests/guide/tools/test_intent_model_ab.py

Verifier 只读。测试必须在冻结 SHA 的独立 worktree 运行；测试期间被测 HEAD 不得漂移。

## 六、唯一正式审计

核心计划 Task 0 必须先执行。

开场冻结：

- base SHA；
- production scope；
- audit profile = guide-closure-full-file-v1；
- scope manifest；
- audit key。

整个项目只允许：

formal_full_file_audit_invocations=1

禁止：

- 第二次开场审计；
- 每个 capability 单独 full-file audit；
- 因 commit/worktree/session 变化创建新 audit key；
- finding 修复后重复 full-file audit；
- 最终再做一次 full-file audit。

开场 finding 处理：

finding -> 最早失败层 -> RED -> 单 writer fix -> targeted verifier

后续只允许：

- 主线程有界静态检查；
- 独立只读 targeted verification；
- focused/full/runtime；
- boundary/compile/diff；
- 跨 worker；
- normal/adversarial browser；
- dependency/blob manifest。

这些不是新的正式 full-file audit，不得记作 audit invocation。

不因普通 checkpoint 要求用户复核或批准。

## 七、禁止补丁式修复

每个失败必须按以下流程：

1. 冻结失败输入和当前输出。
2. 依次记录：
   - exact understanding；
   - semantic proposal；
   - merger trace；
   - TaskPlan；
   - RetrievalResult；
   - DecisionResult；
   - ResponsePlan/SSE；
   - conversation state。
3. 找到第一处与合同不符的输出。
4. 只在该责任层写 RED。
5. 单 writer 做最小通用修复。
6. 跑该层、上下游和浏览器门禁。

责任表：

- 数字/预算/明确否定 -> understanding exact
- goal/topic/观察/指代 -> semantic adapter/prompt/model gate
- 信号冲突 -> intent merger
- 正确 TaskPlan 找错商品 -> retrieval/data
- 正确候选过滤/排序错 -> decision
- 正确 DecisionResult 展示错 -> presentation
- 丢上下文/串会话 -> state/feedback
- 进入旧链 -> composition/transport

禁止：

- 为单个句子在全句正则中加关键词；
- 在 API、Presenter、前端重解释意图；
- retrieval/presentation 二次过滤、打分、选 winner；
- 为让测试变绿更新 Golden 掩盖行为漂移；
- 模型失败时回旧系统；
- 把旧函数复制进新 Guide。

若两个候选模型都不能稳定理解：

- 先检查 prompt/schema/context/merger；
- 增加可泛化 RED；
- 仍不确定则追问 1–2 句；
- 超出范围或两轮仍不明确时说明产品边界；
- 不继续堆句式补丁。

## 八、执行顺序

严格执行：

1. 核心计划 Task 0：基线和唯一审计。
2. 核心计划 Task 1–5：合同、adapter、merger、parallel understanding、composition。
3. 数据计划 Task 1–3 可与核心 Task 1–5 在独立文件域并行。
4. 核心 Task 6：真实 V4-Flash/V3.2 A/B。
5. 核心 Task 7：跨 worker SQLite 状态。
6. 核心 Task 8：Guide-only 默认入口。
7. 数据计划 Task 4–5：候选队列和零 promotion 证明。
8. 核心 Task 9：依赖证明和旧链物理删除。
9. 核心 Task 10：完整机械、模型、状态和浏览器收口。

不得在 Task 6 真实模型门禁通过前执行 Task 8 cutover。
不得在 Task 8 全门禁通过前执行 Task 9 删除。

## 九、数据恢复纪律

目标商品：

38,91,53,57,79,80,86,114,69,103,120,121,42,49,55

只读来源根：

- /Users/bytedance/Desktop/xiaoro-shopping-master/.tmp_user_download_audit
- /Users/bytedance/Desktop/xiaoro-shopping-master/data
- /Users/bytedance/Desktop/xiaoro-fresh/tests/fixtures/guide

先按 SHA inventory，不解析内容。再查三份历史 HTML hash。

字段级处置：

- 核心身份/品牌/品类/价格可信 -> 保留商品；
- 扩展字段无来源 -> 删除字段候选，保持 unknown；
- 评论无原始 locator -> 删除评论证据；
- SKU 串货/身份无法绑定/核心身份冲突 -> 整件商品 quarantine。

HTML 评论走 DOM 解析；包装图、成分表和详情长图才走 OCR。

允许：

- source inventory；
- hash manifest；
- PII 脱敏；
- pending/quarantine；
- 聚合复核报告。

禁止：

- 自动 reviewer；
- 自动 approved_fact；
- 自动 promotion；
- Agent/LLM 自批；
- OCR/评论覆盖 Canonical；
- 从旧聚合文本反向伪造原始来源；
- 把 291 当 HTML 数；
- 找不到三份原始 HTML 时宣称重跑 336/111。

## 十、提交和集成

每个绿色任务：

1. source worktree 提交；
2. 记录 source SHA；
3. 计算 stable patch ID；
4. 计算 production blob manifest；
5. 运行指定 focused；
6. Integration Writer 检查等价 patch；
7. 只集成非重复绿色提交；
8. 冲突做加法式语义合并，禁止 ours/theirs 整文件覆盖；
9. 更新 progress 后立即继续下一任务。

普通 checkpoint 不等待用户。

不要重复 cherry-pick 等价 patch。
不要为制造新 SHA 重写相同内容。

## 十一、验证链

每次相关变更至少运行计划指定 focused。

每个 integration checkpoint 运行：

- compileall；
- app/guide boundary；
- app/guide_runtime import boundary；
- git diff --check；
- 保护路径 diff；
- 排序 SHA。

模型 checkpoint 运行：

- offline schema/forbidden/conflict；
- frozen A/B cases；
- usage/latency/cost；
- hard override = 0；
- legacy fallback = 0。

状态 checkpoint 运行：

- two orchestrators/processes；
- A worker 首轮，B worker 追问；
- text -> image；
- image -> text；
- restart recovery；
- stale/CAS。

cutover checkpoint 运行：

- default Docker start；
- message/stream；
- normal browser；
- adversarial/XSS；
- session switch/late events；
- zero old-service imports。

删除 checkpoint 运行：

- legacy dependency inventory；
- whole tests/；
- Guide full；
- runtime full；
- browser full。

## 十二、停止和升级条件

只有以下情况暂停并找用户：

- 最新规格无法唯一决定产品语义；
- 需要新的付费、凭证或服务购买；
- 需要批准新事实或评论；
- destructive data migration；
- push、部署或切流；
- 隐私、法律、合规或安全政策选择；
- 同一硬阻塞在隔离处理后连续出现 3 次；
- fresh GUIDE_LLM_API_KEY 缺失且真实 A/B 是唯一剩余硬门。

用户睡眠、未回复普通 checkpoint、普通测试失败、import/type/fixture 问题不是停止条件。

一条线阻塞时继续其他独立线。

## 十三、每个 checkpoint 报告

- phase/task/step
- active agents / writers / mode
- source SHA / integration SHA
- stable patch ID / blob manifest
- opening audit key
- formal audit invocations（全项目只能为 1）
- RED/GREEN
- focused/full/runtime/boundary/browser
- model/provider/prompt/schema
- token/latency/cost，真实不可得写 UNAVAILABLE
- source inventory / pending / quarantine / approvals
- protected hashes
- remaining blockers
- 下一项立即执行任务

## 十四、完成条件

只有以下全部成立才标记 COMPLETE：

- 三路意图和唯一 merger 已接入真实主链；
- V4-Flash/V3.2 A/B 已选择通过模型；
- 旧公开 Key 已撤销，当前 Key 未泄漏；
- 模型硬约束覆盖 0；
- 模型失败 fallback 旧链 0；
- 文本状态跨 2/4 worker；
- 默认入口为 Guide runtime；
- 公开聊天 legacy owner 0；
- 旧 Agent、Presenter、旧意图链和旧入口专属依赖已物理删除；
- 不支持请求只追问或说明范围；
- 103 Canonical、排序和 6 条批准评论无漂移；
- 数据缺失保持 unknown；
- 自动批准 0；
- 唯一正式 full-file audit invocation = 1；
- repeat full-file audit invocation = 0；
- 全量、runtime、boundary、跨 worker、模型和浏览器门禁全部通过；
- 工作区干净；
- 未 push、未部署、未切流。

现在从核心计划 Task 0 开始。不要重新讨论设计，不要重新生成平行计划，
不要重复已完成 Phase 2/Phase 3A，普通 checkpoint 不等待用户。
```
