# Phase 2 Main Chain And Data Overnight Loop Prompt

```text
/ralph-loop

从当前 checkpoint 连续执行，直到 MAIN_CHAIN_GREEN + DATA_GREEN，或者某条工作线满足
明确止损条件。普通 checkpoint、单测失败、环境修正、提交、verifier 和集成不等待用户。

本轮只完成两件事：

1. 文字主链路
2. 103 商品分品类数据闭环

图片、画像、反馈等已存在能力只做防回归，不扩功能。前端视觉、128 条正式模型门禁、
push、部署和切流全部留到后续。

## 0. Repository Authority

唯一实施仓库：

/Users/bytedance/Desktop/xiaoro-fresh

分支：

rebuild

启动 HEAD：

5fdf2e3b2aba34e63cba4b6c07fe067fcd2724ff

允许 HEAD 是该提交的已审查后继。每个 Agent、worktree、命令开始前必须验证：

pwd
git rev-parse --show-toplevel
git branch --show-current
git merge-base --is-ancestor \
  5fdf2e3b2aba34e63cba4b6c07fe067fcd2724ff HEAD

任何路径不是 `/Users/bytedance/Desktop/xiaoro-fresh` 或其从上述 HEAD 创建的明确
隔离 worktree，立即停止该进程。

绝对禁止进入、读取代码、运行解释器或写入：

/Users/bytedance/Desktop/xiaoro-shopping-master

IDE 当前打开什么文件不构成仓库权威。

不得 reset、restore、checkout、clean、覆盖或删除用户已有变更。

启动时已知未跟踪文件：

docs/superpowers/plans/2026-08-14-phase2-guide-night-closure.md
tools/guide_gates/run_official_deepseek_smoke.py
本 Prompt 文件

先核对内容，不得删除。smoke 入口通过现有 focused tests 后单独提交；计划和 Prompt
作为本轮冻结文档提交。提交前不得把 Key、原始 HTML、候选正文或私有路径加入 Git。

## 1. Mandatory Reading

执行前完整读取：

1. `/Users/bytedance/Desktop/xiaoro-fresh/docs/superpowers/plans/2026-08-14-phase2-guide-night-closure.md`
2. `.trae/specs/complete-guide-closure-continuously/spec.md`
3. `.trae/specs/complete-guide-closure-continuously/tasks.md`
4. `.trae/specs/complete-guide-closure-continuously/checklist.md`
5. `.trae/specs/complete-guide-closure-continuously/progress.md`
6. 本 Prompt

冻结计划 SHA-256：

2e793cfdd31c991a2cd29d0a5b0a7eebbeb7e77646986f016048d531ac467f3b

若计划 SHA 不一致，先阅读 diff。只有本次对话明确补充的 HTML 扫描事实、来源策略、
并行工作线和状态证据可作为合法后继；无法解释的漂移停止文档消费，不停止独立代码
事实检查。

产品决定以计划文档和本 Prompt 为准：

- 直接表达、正常口语、稍微绕一点都应继续执行。
- 只有真实缺对象、硬条件矛盾、模糊数字、无法唯一绑定或极端对抗才澄清。
- 用户可以直接说 2–4 个目录商品名进行比较，不要求先推荐。
- 商家宣称可以用于普通推荐、展示、对比和 soft rank，但必须保留来源。
- 酒精过敏、成分排除、无添加和安全风险必须使用备案、完整成分表或明确包装证据。
- 用户评价只拥有体验事实，不能证明成分、安全或无添加。

## 2. Current Verified Facts

不要重做以下只读盘点：

### 2.1 Main Chain

- 当前生产 browser normal 为 RED。
- “500 内适合油敏肌的防晒”返回 typed GOAL clarification，没有商品卡。
- “500 元内敏感肌修护精华”同样被错误澄清。
- DeepSeek raw proposal 对普通请求通常已有合法 goal/topic；已知最早公共嫌疑层为
  `IntentSignalMerger` / `task_planning` / typed dispatch。
- 当前 exact parser 会把中文预算标成 `unsupported_budget_format`。

### 2.2 Phase 2 Regression Baseline

- 当前 focused 纵向：`162 passed`。
- `/health` 实测 200。
- image runtime healthy。
- OpenCLIP：103 entries，512 维，index SHA
  `f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340`。
- 当前 combined 1/2/4 image browser：PASS。
- consultation 七轮确认和 SQLite profile write：PASS。
- consultation 后续普通推荐：被主链 RED 阻断。
- feedback domain/SQLite/idempotency focused：PASS。
- feedback browser：第一张普通推荐卡被主链 RED 阻断。
- 批准评论来源：6 条，覆盖 3 商品。
- category sidecar production fact count：0。

不要修改 image/profile/feedback 来隐藏主链错误。

### 2.3 HTML And Data

现有 inventory：

file_count=64449
inventory_sha256=1e26747208d3f83c01f4137a9f1faa06a5e2384fc78594c808f23e014e51a0c5
html_count=336
top_level_saved_pages=118

顶层商品页：

jd=73
tmall=36
taobao=2
other=7

现有 `extract_saved_page_evidence.py` 只读结果：

parsed=109/118
pages_with_parameters=106
pages_with_reviews=33
parameter_occurrences=803
review_rows=64
exact_item_bound_products=98/103
ambiguous_item_bindings=0

六品类精确绑定覆盖：

skincare=48/51
suncare=11/12
base_makeup=19/19
color_makeup=6/6
cleanser=11/12
fragrance=3/3

缺少 exact item 绑定的 Canonical product IDs：

36,53,70,106,144

旧搬运瓶颈：

unique_parameter_names=116
old_map_recognized_names=8
old_map_unrecognized_names=108
mapped_parameter_occurrences=61/803
silently_skipped_parameter_occurrences=742/803

结论：不是缺 HTML，也不是先做 OCR 才能继续。主要工作是放开 3 页 manifest、扩展到
98 个精确绑定商品、建立六品类参数 registry，并给 803 组参数全部明确去向。

## 3. Execution Topology

从同一冻结 HEAD 创建两个隔离 worktree：

### Response Track

只拥有：

- `app/guide/understanding/**`
- `app/guide/intent/**`
- 必要的 `app/guide/application/text_recommendation_flow.py`
- 必要的目录商品名称 resolver
- 对应 focused tests

### Data Track

只拥有：

- `tools/guide_data/**`
- 必要的 `app/guide/retrieval/category_*` 合同
- `tests/guide/data/**`
- 私有 `/private/tmp` 候选和 evidence 输出

### Integration Writer

主仓库同一时间只能一个 Integration Writer。它独占：

- `app/guide_runtime/composition.py`
- `.trae/specs/**`
- `docs/audits/**`
- `data/guide_category_facts/**`
- 共享最终测试和 browser gate

规则：

- 一个 worktree 同时一个 writer。
- 同一文件 authority 不能跨 track。
- verifier 只读，不得修改被验 worktree。
- 每个 track 小提交、focused GREEN、独立 verifier PASS 后才集成。
- 任何 Agent 漂移到旧仓库，立即关闭，不采纳结论。

## 4. Response Track

### 4.1 Freeze One End-To-End RED Matrix

先记录：

exact
-> semantic proposal
-> merger trace
-> TaskPlan
-> RetrievalResult
-> DecisionResult
-> Response/SSE
-> terminal event
-> product IDs

冻结至少：

直接：

- `500 内适合油敏肌的防晒`
- `不要含酒精的爽肤水`
- `想要保湿的精华`

正常口语：

- `最近脸挺油的，又怕闷，三百左右有没有通勤防晒`
- `再便宜点，两百以内`

稍微绕一点：

- `我平时就上下班用，不想下午糊脸，也别太贵，油皮能用的防晒看看`

比较/适配：

- `对比理肤泉特护清盈防晒乳和清透防晒乳`
- `敏感肌用理肤泉特护清盈防晒乳会不会闷痘`

合法澄清：

- `百来块的`
- 无当前商品时 `帮我对比一下`
- `预算最高 200，但最低也要 500`

### 4.2 Fix Resolved-Slot Over-Clarification

只在对应槽位最终未解析时接纳 clarification hint：

- GOAL：merged goal 仍不明确
- TOPIC：merged topic 为空
- REFERENCE：该 goal 需要 reference 且 context/商品名均未解析
- BUDGET：用户提出预算但无合法 bound
- CONCERN：该能力真实要求 concern 且没有

goal/topic/reference 已合法时，过时 hint 或 unclear observation 不得重新制造 uncertainty。

继续 fail-closed：

- 低置信
- exact/semantic 硬冲突
- 多个正向品类冲突
- 非法/矛盾数字
- 越界指代
- provider unavailable 且无协议闭合任务

禁止：

- 单句全文关键词补丁
- API/前端重新识别意图
- 改 expected 掩盖错误
- 恢复旧 V2

### 4.3 Direct Product Names

模型最多提名 4 个原文商品 mention：

- source_text
- source_span

禁止模型输出 product ID。

代码只在 103 Canonical 目录内绑定：

- 完整商品身份
- 受控品牌/商品别名
- 唯一命中才产生 Canonical ID
- 0 命中返回目录无数据
- 多命中返回 REFERENCE clarification

comparison：必须唯一绑定 2–4 个不同商品。
suitability：必须唯一绑定 1 个商品。

复用现有 comparison/suitability/review/pitfall 决策，不重写算法。

### 4.4 Natural-Language Numbers

模型负责提名：

- budget relation
- minimum/maximum
- source_text
- source_span
- confidence

代码必须验证：

- span 与原文逐字一致
- Decimal 有限且 >0
- minimum <= maximum
- 方向与原文一致
- 不覆盖 exact 阿拉伯数字
- 不与其他已消费 span 冲突

直接接纳：

- 三百以内 -> max 300
- 两百五以内 -> max 250
- 三百到五百 -> 300–500

确认：

- 百来块
- 几百上下
- 250 左右
- 三张以内

不再要求用户改打阿拉伯数字。首轮预算和 revision 必须复用同一 validator。

### 4.5 Common Efficacy

使用现有批准词表：

- 保湿/补水 -> hydration
- 舒缓 -> soothing
- 修护/屏障 -> repair
- 紧致/抗皱/淡纹 -> anti_aging
- 美白/提亮/淡斑 -> brightening
- 控油 -> oil_control
- 祛痘/抗痘 -> acne_care

只有 Canonical efficacy known 才声称匹配。移除“所有精华都必须追问是否修护”的早期窄纵切。

### 4.6 Response Acceptance

本地冻结集至少：

direct=12
colloquial=12
moderately_indirect=12
adversarial_or_contradictory=12

准入：

- direct + colloquial + moderately_indirect core route >=90%
- ordinary false clarification <=10%
- hard constraint override=0
- forbidden field acceptance=0
- unsafe TaskPlan=0
- wrong product selection=0
- legacy fallback=0
- message/stream parity
- 单终态

本地 GREEN 后才允许最多 16 条真实 DeepSeek V4-Pro probe：

- max_tokens=256
- temperature=0
- thinking disabled
- max repair=1
- 不跑 Flash
- 不跑两阶段
- 不跑正式 128 条

Key 只从 `/private/tmp/xiaoro-deepseek-api-key` 安全读取。必须普通文件、0600、非
symlink。Key 不进入 argv、日志、报告、cache、Git 或异常。

最终必须重跑真实 normal browser：

`500 内适合油敏肌的防晒`

必须产生 1–3 张卡，不得 clarification。

## 5. Data Track

### 5.1 Reuse Inventory

若 inventory SHA 与冻结值一致，不重新扫描 64,449 文件。直接从 inventory 生成
118 个顶层保存页 manifest。

使用现有：

- `tools/guide_data/extract_saved_page_evidence.py`
- `data/seed_dump.sql` detail_url
- `data/canonical/seed_product_images_v1.jsonl` 平台 item identity

绑定只能使用：

- exact platform item ID
- exact SKU
- full HTML SHA-256
- approved root ID

文件名和模糊商品名只能帮助人工定位，不能自动绑定生产事实。

98 个 exact-bound products 自动进入候选。

IDs `36,53,70,106,144`：

- 查找现有同款 alternate listing；
- 核对容量/色号/规格/商品身份；
- 只有两个 verifier 均确认等价时建立新 binding；
- 否则保持 source gap，不阻塞其他 98 商品。

### 5.2 Source Classification

每个候选必须包含：

- source_sha256
- source_locator
- source_class
- item_id
- sku_id
- raw_value_sha256
- normalized_value_sha256

source class：

1. `official_registration`
   - 备案、SPF/PA 等强结构化字段
2. `merchant_parameter`
   - 商家参数
3. `merchant_title_claim`
   - 京东标题中的明确商品宣称
4. `merchant_description`
   - 商家详情文字
5. `merchant_description_ocr`
   - 页面绑定长图 OCR，必须有 page SHA + image SHA + item/SKU
6. `consumer_review`
   - 用户体验评价
7. `package_ocr`
   - 包装/成分表 OCR
8. `qa`
   - 问答，quarantine
9. `promotion_or_recommendation_block`
   - 活动、榜单、代言，quarantine

来源由 DOM/嵌入 JSON 路径机械判断，不让 LLM 猜来源身份。

### 5.3 Category-Specific Parameter Registry

删除小型通用 `_PARAMETER_FIELD_MAP` 的 authority，改为按 CategoryProfile 路由：

skincare：
- 功效/核心功效 -> efficacy
- 适合/适用肤质 -> suitable_skin
- 质地 -> texture
- 原料/核心/主要成分 -> ingredients_present

suncare：
- SPF/PA/防晒指数/标准 -> spf_pa
- 防水/耐水 -> water_resistance
- 成膜速度 -> texture
- 使用场景 -> usage

base_makeup：
- 色号/颜色 -> shade
- 妆效 -> finish
- 遮瑕 -> coverage
- 持妆/持久 -> longevity

color_makeup：
- 色号/颜色 -> shade
- 哑光/水润/妆效 -> finish
- 持久 -> longevity

cleanser：
- 洁面/卸妆分类 -> cleansing_form
- 清洁/卸妆力 -> cleansing_power
- 核心/原料成分 -> surfactant_type 或 ingredients_present
- 起泡/冲洗/洗后感 -> rinse_behavior

fragrance：
- 香调 -> fragrance_family
- 前/中/后调 -> top_notes/heart_notes/base_notes
- 留香 -> longevity
- 扩香 -> sillage

803 组参数每一组必须分类为：

- mapped_to_field
- identity_metadata
- ignored_non_fact
- quarantine
- unsupported_with_reason

`silently_skipped=0`。

同一参数名在不同 profile 可映射到不同字段。目标字段必须适用于该 profile。

### 5.4 Pragmatic Evidence Policy

允许：

- merchant structured parameter -> compare/rank/display
- merchant title/description/description OCR -> evidence/display/compare/soft_rank
- approved consumer review -> experiential evidence/display/soft_rank
- official registration -> 获准 hard_filter/compare/rank
- package OCR/full ingredient list -> 按字段 policy 升级

严格：

- 普通功效、肤感、持妆、遮瑕、香调可用商家宣称。
- 用户评价可用于质地、黏腻、持久、清洁感、扩香和避坑。
- 酒精过敏、成分排除、安全风险不能只用商家宣称或用户评价。
- 成分硬排除必须有完整成分表、备案或明确包装证据。
- `verified_absences` 必须有明确“不含/未添加”证据。
- 没写不等于没有。
- 不适用字段必须 `not_applicable`，不能伪装 unknown。

不确定且 HTML 结构化参数不足时，优先：

1. 绑定商家详情文字；
2. 绑定详情长图 OCR；
3. 绑定包装/成分表 OCR；
4. 保留 unknown。

不得回到无来源 OCR dump。

### 5.5 Full 103 Matrix

按六 profile 为 103 商品生成所有 applicable fields：

- known
- pending
- quarantine
- unknown
- not_applicable

每商品生成：

- IDENTITY_READY
- RECOMMEND_READY
- COMPARE_READY
- SUITABILITY_READY
- FULL_READY
- BLOCKED

unknown 不是齐全。

### 5.6 Verification And Promotion

每个 pending 候选必须两个独立只读 verifier：

- 同一 frozen SHA
- product/item/SKU/field/value/source/capability 逐项核对
- 不共享中间结论
- 不写 production

PASS + PASS 才生成：

- reviewer
- reviewed_at
- decision
- reason
- detached HMAC signature

然后运行现有原子 promotion：

`tools/guide_data/promote_approved_category_facts.py`

HMAC key 只在临时环境变量中，至少 32 bytes，不打印、不提交。

promotion 后：

- 重读 manifest/facts；
- 重算 103 coverage/readiness；
- 未批准候选不得改变 cards/winner/ranking；
- Canonical core、排序 SHA、6 条批准评论不漂移。

DATA_GREEN 必须同时满足：

- 103 商品矩阵已生成
- 98 exact-bound products 全部进入分类
- 803 参数 `silently_skipped=0`
- 来源分类完整
- 双 verifier 完成
- `promotion_invocations > 0`
- `production_fact_count > 0`
- coverage/readiness 相比基线有真实提升
- 5 个 source gaps 有明确状态

不能以“没有共同 PASS，所以 fact_count=0”标记 DATA_GREEN。

## 6. Smart Failure Handling

任何失败先分类：

1. ENVIRONMENT
   - PYTHONPATH、解释器、依赖、输出目录、权限、端口、浏览器
2. HARNESS
   - fixture、runner、字段读取、错误结果列
3. RESPONSE
   - semantic contract、exact、merger、TaskPlan、dispatch
4. DATA
   - inventory、parser、binding、field registry、source policy、verifier、promotion
5. REGRESSION
   - image/profile/feedback 等已绿能力被改坏

规则：

- 先冻结输入和最早失败层。
- 写一个泛化 RED。
- 最小修复。
- 跑最小 GREEN。
- 再扩大门禁。
- 同一最早失败层连续两次修复失败，停止该路径，记录 BLOCKED，继续另一条独立工作线。
- 环境错误不得通过修改业务代码绕过。
- 输出字段读错、CLI argv 丢失、目录预创建等乌龙必须先修 harness，不能改生产行为。
- 不重复正式 full-file audit。
- 不为了数字好看降低安全硬门。

## 7. Long Command Supervision

所有超过 30 秒的命令：

- start_new_session/process group
- 30 秒 heartbeat
- stage-specific hard timeout
- timeout 后 TERM，等待，再 KILL
- 结束后 wait
- 检查 pytest/Uvicorn/Playwright/DeepSeek runner 残留

同一时间最多一个 heavy test/browser/model command。数据机械解析可以与 Response
focused 单测并行，但不得与 OpenCLIP/browser 同时抢占资源。

## 8. Testing Order

不要一失败就跑全量。

Response：

1. contract/exact/merger/task focused
2. text application focused
3. runtime HTTP message/stream parity
4. 最多 16 条 Pro
5. normal browser

Data：

1. saved-page parser fixtures
2. category mapping focused
3. source classification focused
4. 103 candidate determinism
5. verifier/promotion atomicity
6. post-promotion card/decision focused

两条都 GREEN 后：

1. changed-files tests
2. Guide full
3. runtime focused
4. normal browser
5. compileall/boundary/diff

不运行整个 `tests/`、完整 Phase 2 browser、128 模型门禁或前端重构。

## 9. Documentation

只根据真实证据更新：

- `.trae/specs/complete-guide-closure-continuously/progress.md`
- `.trae/specs/complete-guide-closure-continuously/tasks.md`
- `.trae/specs/complete-guide-closure-continuously/checklist.md`
- `docs/audits/guide-closure/final_handoff.md`
- `docs/audits/guide-closure/data/source_inventory_summary.md`
- `docs/audits/guide-closure/data/candidate_queue_summary.json`

不得把：

- 代码存在
- 单测存在
- 历史 PASS
- inventory 数量
- candidate 数量
- unknown 状态

写成当前生产完成。

每个 checkpoint 仅报告：

- completed
- current blocker
- remaining
- ETA
- tests
- browser
- model/usage/latency/cost
- data known/pending/quarantine/unknown/not_applicable
- readiness
- promotion count
- production fact count
- evidence hashes
- residual processes

## 10. Final State

允许终态：

MAIN_CHAIN_GREEN + DATA_GREEN

或：

PARTIAL
- 一条 GREEN
- 一条满足止损并有明确最早失败层

或：

BLOCKED
- 两条都满足止损，且没有可继续的独立工作

只有 MAIN_CHAIN_GREEN + DATA_GREEN 才结束本轮并报告成功。

成功前必须证明：

- 普通文字真实 browser 出卡
- 直接商品名比较可执行
- 中文预算可执行
- 正常/口语/稍绕语句不乱澄清
- hard safety gates=0
- 103 数据矩阵完成
- 803 参数无静默丢弃
- production category fact count >0
- 画像、图片、反馈 focused 没有回归
- legacy fallback=0
- 工作区无意外变更
- 无残留进程
- 未 push、未部署、未切流
```
