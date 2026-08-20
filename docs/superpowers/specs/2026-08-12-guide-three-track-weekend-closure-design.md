# Guide 三条主线周末收口设计

## 1. 目标和期限

目标是在 2026-08-16（周日）前完成以下三条主线的可验证收口：

1. 所有公开聊天请求只进入 Guide，不再回退 V1/V2。
2. 以旧数据库为主、原始 HTML 为核验来源，完成 15 个试点商品的数据闭环。
3. 将意图理解改为“两步语义理解”，在保留语义能力的同时通过实用生产门禁。

本设计不重复正式 full-file audit。现有唯一正式审计调用保持为 1，后续只运行
targeted、focused、full、runtime、boundary、跨 worker 和浏览器门禁。

## 2. 当前审计结论

### 2.1 统一入口

- Guide runtime 已存在，Dockerfile 已启动 `app.guide_runtime.app:app`。
- Compose、生产 Compose、`start.sh`、README 和 DEPLOY 仍指向 `app.main:app`。
- 公开 chat owner 仍可能返回 `ChatOwner.LEGACY`。
- 旧聊天链包含 14 个核心源码文件、约 11612 行。
- 活动代码中仍有 7 个 runtime importer、7 个 test importer 和 8 个 script importer。

结论：Guide 能运行，但公开系统仍是双主链。

### 2.2 数据来源

- Downloads 中存在 118 个顶层商品 HTML，约 268.8 MB：
  - 天猫 36 个；
  - 京东 73 个；
  - 淘宝 2 个；
  - 其他 7 个。
- 三份历史天猫评论 HTML 均存在，且 SHA-256 与锁定值完全一致：
  - 商品 42：`b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4`
  - 商品 49：`55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44`
  - 商品 55：`56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783`
- `data/seed_dump.sql` 包含 103 个商品，并保留 `specifications` 和
  `skincare_info` JSONB 数据。
- 数据库字段混合了官方参数、详情页 OCR、营销文案、评论和问答，不能整体视为同一
  权威来源。
- 旧盘点报告中“三份 HTML 全部缺失”的结论已被本次精确 SHA 核对推翻。
- 依赖“HTML 全部缺失”得出的 Task 9.3、10.5 和恢复汇总证据必须重新生成，不能复用
  现有完成标记。

结论：数据没有丢失，问题是来源分层和字段核对，不是重新从零采集。

### 2.3 意图理解

- 三路合同、唯一 merger、严格 schema、缓存和 SQLite 状态已经存在。
- 现有模型一次输出八类语义字段，系统 prompt 约 13 KB，包含七组决策矩阵。
- 第三次真实 A/B：
  - V4-Flash：127 行可用，67 行全部字段一致；
  - V3.2：120 行可用，73 行全部字段一致。
- 主要失败是语义标签不一致，不是 JSON 格式失败：
  - concern 错误分别为 32/30；
  - reference 错误分别为 22/24；
  - goal 错误分别为 21/18。
- 模型硬约束覆盖、禁止字段进入 TaskPlan、错误选品和 legacy fallback 均为 0。

结论：安全边界已经有效，主要问题是单次模型任务过重和门禁把非关键差异也当成发布
阻塞。

## 3. 总体设计

三条主线并行实施，不再互相串行阻塞：

```text
Track A: Guide 唯一入口 ───────────────┐
Track B: 数据库优先 + HTML 核对 ───────┼─> 最终集成和验收
Track C: 两步语义理解 + 实用门禁 ──────┘
```

Track A 不再依赖模型达到 128/128。模型不可用或低置信时，Guide 自己追问或说明支持
范围，不调用旧链。

### 3.1 并行所有权

- Track A writer 只修改公开 API、Guide runtime、会话状态和启动文件。
- Track B writer 只修改数据工具、来源 manifest、候选队列和数据报告。
- Track C writer 只修改 understanding、intent、LLM adapter 和模型门禁。
- `composition.py`、共享合同、tasks/checklist/progress 只由 Integration Writer 修改。
- 同一文件同时最多一个 writer；每个 track 的提交先通过本 track focused gate，再交
  Integration Writer 集成。

## 4. Track A：Guide 唯一入口

### 4.1 公开入口

- Docker、Compose、生产 Compose、`start.sh`、README 和 DEPLOY 统一指向
  `app.guide_runtime.app:app`。
- `/api/v1/chat/message` 和 `/api/v1/chat/stream` 只调用 Guide。
- 删除公开 `ChatOwner.LEGACY` 分支。
- 旧图片 payload 返回明确迁移错误，不调用旧 Agent。

### 4.2 澄清闭环

会话状态增加 typed 澄清进度：

- 第一次无法理解：返回针对当前缺口的问题。
- 第二次仍不明确：返回第二次澄清。
- 第三次仍不明确：返回明确支持范围，不自由回答。
- 成功理解后原子清零澄清进度。
- clarify、error、断流和 stale 请求不得污染最近有效推荐状态。

### 4.3 旧链删除

Guide-only focused 门禁通过后：

- 将 `app/main.py` 收缩为 Guide app 的兼容导出。
- 清除 config、Celery worker/beat、prompts 中的旧聊天开关和 importer。
- 使用 `git rm` 删除旧 V1/V2 Agent、Intent、Presenter 和专属测试/脚本。
- 删除后 runtime importer 必须为 0。
- 不创建新的 `legacy/` 或 archive 目录。

### 4.4 完成标准

- 所有默认启动方式行为一致。
- message/stream 都只经过 Guide。
- provider 失败、低置信和未支持输入均不会进入 V1/V2。
- 新进程 import 默认 runtime 后不加载 `app.services`、`app.database`、Redis、
  pymilvus 或旧 Agent。

## 5. Track B：数据库优先、HTML 核对

### 5.1 固定范围

周日前只闭环 15 个商品：

```text
38, 42, 49, 53, 55, 57, 69, 79, 80, 86, 91, 103, 114, 120, 121
```

其中包括六品类 12 个试点和评论商品 42、49、55。其余 88 个商品只保留已有
Canonical 数据和 `unknown`，不在本轮补齐全部字段。

### 5.2 来源优先级

1. Canonical 已批准核心事实：
   - 商品身份、品牌、品类、价格；
   - 继续作为最高权威，任何其他来源不能覆盖。
2. 旧数据库结构化字段：
   - `specifications`、结构化 `skincare_info` 和明确 source tag；
   - 作为候选来源，不直接自动批准。
3. 原始 HTML 官方参数：
   - item/SKU、参数表、备案号、SPF、色号、规格、适用肤质、使用方法；
   - 与数据库一致时可形成 source-backed pending。
4. 包装和成分表 OCR：
   - 只作为成分存在、安全提示和包装观察证据；
   - 不能单独证明 verified absence、功效或安全结论。
5. 消费者评论：
   - 只用于质地、妆效、持久度、清洁感和评论摘要；
   - 不能用于配方、安全、硬过滤或 winner。

### 5.3 核对流程

```text
旧数据库字段
  -> 识别字段来源和品类适用性
  -> 绑定 product ID + item/SKU + HTML SHA
  -> 与 HTML 官方参数或包装证据核对
  -> 一致：pending
  -> 冲突/营销/Q&A/跨 SKU/无定位：quarantine
  -> 无来源：unknown
```

现有 `category_field_registry()` 继续定义六个品类的适用字段，不使用一套统一字段强塞
所有品类。

### 5.4 历史评论恢复

- 重新将 Downloads 纳入受信只读来源根。
- 使用三份锁定 HTML 重放历史评论解析。
- 重新核对 historical `336 -> 111 -> 6` 链路。
- 原始 HTML 和候选正文保持本地，不提交 Git。

### 5.5 批准边界

- 自动化只生成 pending/quarantine 和差异报告。
- 新字段进入生产前必须有明确 review decision。
- 周日前输出一份 15 商品的简短审核矩阵，用户只需确认有来源的字段，不阅读原始全文。
- 未批准字段保持 unknown，不阻塞商品继续使用。

### 5.6 完成标准

- 三份历史 HTML 状态从 missing 修正为 found，SHA 完全一致。
- 15 个商品每个适用字段都有 known/pending/quarantine/unknown 明确状态。
- 数据库已有可信字段被复用，不重复从 HTML 全量重挖。
- 不把营销、问答、评论或 OCR 误当硬事实。
- promotion 只接受明确批准的决定。

## 6. Track C：两步语义理解

### 6.1 第一步：路由语义

第一步模型只回答：

- 用户目标：推荐、对比、适配评估、图片相似、知识咨询、问诊、追问或澄清；
- 支持的品类；
- 是否存在需要进一步解析的指代或场景语义；
- confidence 和 clarification hint。

精确代码路与第一步并行运行。金额、数字方向、范围、否定、成分排除和显式 ordinal
继续由代码独占。

### 6.2 第二步：场景语义

第二步只在需要时调用对应场景 extractor：

- recommendation：偏好、肤质、诉求；
- assessment：症状、状态和场景；
- comparison：比较对象和比较范围；
- followup：当前商品/批次/品类/既有约束的指代和修改动作；
- knowledge：知识主题，不生成商品事实；
- image：图片 ordinal 和图片任务类型。

不同场景使用不同的严格 schema。模型不再为不相关字段输出空列表或猜测值。

### 6.3 调用、缓存和失败预算

- 每轮最多一次路由调用和一次场景调用。
- 全轮最多共享一次 schema format repair，最坏不超过三次 provider 请求。
- 每个阶段只缓存 strict validation 成功的结果，缓存身份包含 stage、schema、prompt、
  provider、model、参数和 typed context。
- 正常未命中缓存的文本请求总 p95 目标不超过 12 秒。
- 路由阶段失败时，协议闭合的精确操作可以继续；其他请求返回 Guide clarification。
- 路由成功但场景提取失败时，不带着半份语义进入 TaskPlan；需要该场景语义的请求返回
  clarification。
- 不执行 transport retry，不在 provider 不稳定时用重试掩盖失败。

### 6.4 唯一合并

所有结果仍进入唯一 `IntentSignalMerger`：

```text
本轮精确输入 > 会话确认 > 长期画像 > 模型开放语义 > 默认
```

- 模型不能覆盖硬约束。
- 模型不能输出 product ID、candidate ID、商品事实、score、winner、SQL 或画像写入。
- 低置信、冲突和 provider 失败统一进入 typed clarification。
- 只有 merger 输出的 `StructuredUnderstanding` 可以进入 `TaskPlan`。

### 6.5 模型选择

- 先用现有 V4-Flash 和 V3.2 验证新设计。
- 只有新设计仍无法通过实用门禁时，才评估更强模型。
- 不再通过不停增加 prompt 规则追逐单句 expected。
- provider unavailable 超过前 20 条的 10% 时立即停止网络 A/B，不继续消耗配额。

### 6.6 实用生产门禁

硬门仍为零容忍：

- hard constraint override = 0；
- forbidden field acceptance = 0；
- invalid output TaskPlan invocation = 0；
- wrong product selection = 0；
- legacy fallback = 0；
- critical route error = 0。

质量门改为分层：

- route-critical 完整匹配率至少 95%；
- 剩余不确定 case 必须 fail-closed clarification，不能走错 TaskPlan；
- 场景 extractor 的关键字段匹配率至少 90%；
- concern/observation 的非关键措辞差异若不改变 TaskPlan、选品和展示事实，不阻塞发布。

## 7. 四天排期

### 2026-08-13：入口和来源基线

- 完成 Guide-only message/stream 和默认启动切换。
- 增加澄清次数状态。
- 将 Downloads 纳入只读来源 inventory。
- 冻结 15 商品数据库字段和 HTML 对照清单。
- 建立第一步路由语义 RED。

### 2026-08-14：数据和意图并行实现

- 完成数据库字段分层、HTML 核对和三份评论 HTML 重放。
- 生成 15 商品 pending/quarantine/unknown 审核矩阵。
- 完成路由语义和场景 extractor。
- 运行 32 条分层 smoke gate；通过后才运行 128 条离线门禁。

### 2026-08-15：集成和旧链删除

- 完成 128 条模型门禁和模型选择。
- 修复最早失败层，不在 API/Presenter 添加语义补丁。
- 完成 importer inventory。
- 删除旧 V1/V2 聊天链和专属依赖。

### 2026-08-16：最终验收

- focused、Guide full、runtime full。
- compileall、双 boundary、dependency inventory、diff check。
- 2/4 worker、重启、stale/CAS、terminal delivery。
- normal、adversarial、XSS、session switch、late-event 和图片浏览器矩阵。
- 核对 Canonical、排序 SHA、6 条批准评论和零自动批准。
- tasks/checklist/progress 最终收口。

## 8. 止损和汇报规则

### 8.1 已知坑点和禁止走法

以下不是理论风险，而是本轮审计已经确认的具体坑点。后续执行必须逐条规避：

1. **仓库混淆**
   - 当前实现仓库是 `/Users/bytedance/Desktop/xiaoro-fresh`；
   - IDE 常打开的 `/Users/bytedance/Desktop/xiaoro-shopping-master` 是旧仓库；
   - 在旧仓库修改 `app/services/v2/presenter.py` 不会完成新 Guide 收口。
2. **来源根漏扫**
   - 旧数据报告扫描了 515 个文件，却没有覆盖 Downloads 中的真实保存页；
   - 三份被报告为 missing 的 HTML 实际都在 Downloads，且 SHA 完全匹配；
   - 后续不能只看 inventory 数量，必须核对批准来源根清单和三份锁定 hash。
3. **测试 parser 不等于真实 parser**
   - 现有 category HTML parser 只识别人工添加的 `data-guide-field`；
   - 现有 review parser 只识别 fixture 的 `data-review-candidate`；
   - 真实天猫页的数据在嵌入 JSON 中，直接把真实 HTML 交给旧 parser 会得到 0 条，
     不能据此判断源数据为空。
4. **历史 336/111 不能硬凑**
   - 三份真实页当前显式包含 6 条评论；
   - 精确 SHA 证明来源已找回，但不自动证明历史 336/111 中间计数可重现；
   - 若新 parser 不能自然重现 336/111，应记录为历史 provenance，不得复制旧聚合文本
     或伪造候选数量。
5. **SQL dump 不能按行号或 ID 文本搜索**
   - `seed_dump.sql` 包含多个表的 `COPY` 区段，相同首列数字可能属于知识文档等其他表；
   - 必须只解析精确的 `COPY public.products (...) FROM stdin;` 区段；
   - 直接 `rg "^80\t"` 或简单 `split("\t")` 会把其他表或 COPY 转义解析错。
6. **旧数据库字段不是同一权威**
   - `skincare_info` 同时含官方参数、OCR、营销文案、评论和问答；
   - `concerns`、`pitfalls`、`claim_notes` 不能直接提升为硬事实；
   - `verified_absence`、安全和成分过滤必须有官方结构化或包装来源。
7. **Docker 已局部提前切换**
   - Dockerfile 走 Guide，但 Compose 会覆盖 CMD 并走 `app.main`；
   - 只验证 Dockerfile 会得到假阳性，六种默认启动方式必须一起检查。
8. **澄清当前没有可持久化状态**
   - 现有 `ConversationSnapshot` 不接受纯 clarification；
   - 现有 clarify 分支不提交状态；
   - 只改回复文案无法实现两轮上限，必须改 typed snapshot + SQLite CAS + terminal
     delivery。
9. **旧链不能先删后查**
   - 当前 API、Celery、tests、scripts 仍有旧 importer；
   - 未先生成 importer inventory 就 `git rm app/services/**` 会造成启动或收集失败；
   - 删除顺序必须是入口迁移 -> importer 清零 -> 物理删除。
10. **不能继续扩大单次 Prompt**
    - 当前 Prompt 约 13 KB，七组矩阵、八类字段；
    - 再加单句规则会继续增加字段互相污染；
    - 同一失败簇第二次修复仍失败时，必须回到路由/场景拆分，不允许第三次追加句式。
11. **不能只调低门禁冒充成功**
    - concern/observation 非关键差异可以降级为质量指标；
    - goal/topic/reference/act 导致错误 TaskPlan、错误选品或旧 fallback 时仍为硬失败；
    - 调阈值前必须证明错误 case fail-closed clarification。
12. **两步模型有调用和延迟风险**
    - 两阶段不能各自无限 repair/retry；
    - 每轮最多两次正常调用、共享一次 repair；
    - 总 p95 超过 12 秒或前 20 条 provider 失败超过 10% 时立即停止。
13. **不能用更多 Agent 掩盖文件冲突**
    - 同一文件同时只能有一个 writer；
    - `composition.py`、共享合同和任务文档只允许 Integration Writer 修改；
    - Agent 数量增加不代表进度，只有冻结提交和独立 verifier 结果算完成。
14. **不能跑无监管长任务**
    - 测试或网络任务必须有心跳、硬超时和进程组 TERM/KILL；
    - 10 分钟无输出且无可解释进展时立即审计进程；
    - 不允许留下 runner、pytest、Uvicorn 或 Playwright 后台进程。
15. **不能重复正式审计**
    - 唯一 formal full-file audit 已调用 1 次；
    - 后续“复审”“最终审计”不能换名字重复调用；
    - 只允许 targeted review 和机械门禁。

### 8.2 立即停止并讨论

出现以下任一情况，不继续盲试：

- 同一最早失败层连续两次修复后仍失败；
- 32 条 smoke gate 未达到 85% route-critical 匹配；
- provider 前 20 条请求中 unavailable/timeout 超过 10%；
- 数据无法绑定 product ID、item/SKU 和 source SHA；
- 新入口重新出现 legacy fallback；
- 测试或网络进程 10 分钟无输出且无可解释进展；
- 预计完成时间偏离超过半天。

### 8.3 固定汇报格式

每个 checkpoint 只汇报四项：

```text
已完成：
当前卡点：
剩余工作：
预计完成：
```

发生止损条件时立即汇报，不等待下一轮任务结束。

## 9. 最终完成定义

周日只有同时满足以下条件才称为完成：

1. 所有公开聊天只走 Guide，旧 fallback 为 0。
2. 旧 V1/V2 Agent、Intent、Presenter 和专属 importer 已删除。
3. 15 个试点的数据状态可追溯，三份锁定 HTML 已正确恢复。
4. 已批准字段进入生产，未批准字段保持 unknown。
5. 两步语义理解通过硬门和分层质量门。
6. provider 失败只产生 Guide clarification，不影响统一入口。
7. 全量、跨 worker、boundary 和浏览器门禁通过。
8. 唯一正式审计调用仍为 1，未重复。
9. 工作区干净，未 push、未部署、未切生产流量。
