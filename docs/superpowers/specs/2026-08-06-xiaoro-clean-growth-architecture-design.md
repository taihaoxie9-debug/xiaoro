# 小 Ro 干净重建与多图导购架构设计

状态：设计已在对话中逐段确认，等待用户复核书面版本
日期：2026-08-06
最高产品事实源：飞书文档 revision 34
旧实现参考仓库：`/Users/bytedance/Desktop/xiaoro-shopping-master`
新实现工作区：`/Users/bytedance/Desktop/xiaoro-fresh` 的 `rebuild` 分支

## 1. 决策摘要

本项目不再把旧 V1/V2 后端模块搬进新仓库继续修补。

采用的唯一路线是：

1. 原样迁入不可再生数据、真实图片和经验证的产品资产。
2. 封存少量真正独立的纯内核与离线审核资产。
3. 从新合同出发，按纵向端到端闭环生长六层实现。
4. 旧 Agent、Presenter、意图链和图片链只作为问题档案与业务经验来源。
5. 每条能力必须经过真实前端、真实数据和真实模型/索引验证，不能用 mock 单测代替产品可运行性。

一期和二期完整实现。三期只定义稳定接口，不写假实现。

## 2. 范围

### 2.1 一期完整能力

- 文本导购
- 图片找相似
- 图文联合筛选
- 商品对比
- 一轮关键追问
- 商品卡、比较区、风险提示和 SSE 流式展示

### 2.2 二期完整能力

- 用户画像与偏好记忆
- 场景导购
- 商品对比和避坑
- 评论总结
- 护肤轻问诊
- 单图商品识别
- 单图适配判断
- 两图商品对比
- 三到四图候选比较
- 商品包装和成分表 OCR

### 2.3 三期只留接口

- 视频理解和视频找同款
- 达人内容与短视频内容
- 更复杂的整套搭配
- 实时反馈学习

三期接口必须可被替换实现，但二期不创建空服务、不返回假成功。

### 2.4 明确不做

- 根据人脸或皮肤照片诊断肤质
- 医疗诊断或治疗建议
- 让 LLM 编商品事实、候选 ID、评分或 winner
- 用图片颜色直方图冒充图像语义检索
- 用向量判断预算上下限、否定词和精确数字方向

## 3. 术语

### 3.1 资产迁入

把不可再生或已经验证的资产带到新工作区，包括数据、图片、审核决定、前端体验和少量纯内核。

### 3.2 新代码生长

从新合同和新边界出发实现业务模块。新运行时不得依赖旧 V1/V2 生产模块。

### 3.3 旧实现参考

旧代码可用于查业务不变量、失败案例和测试场景，但不得通过 import、包装器或兼容分支进入新主链。

## 4. 六层架构

六层是业务职责，不是目录数量。编排器和外部适配器不算新的业务层。

```text
用户输入：文字 + 0..4 张商品相关图片
        |
        v
[1] understanding  多模态理解
        |
        v
[2] intent         意图识别与任务拆解
        |
        v
[3] retrieval      多源 RAG 召回
        |
        v
[4] decision       确定性决策
        |
        v
[5] presentation   响应计划与展示
        |
        v
[6] feedback       会话、画像与反馈
```

建议物理结构：

```text
app/guide/
  understanding/
  intent/
  retrieval/
  decision/
  presentation/
  feedback/
  application/
    orchestrator.py
  adapters/
    llm/
    image/
    catalog/
    persistence/
```

`application/` 和 `adapters/` 是薄外壳，不拥有业务规则。

### 4.1 多模态理解层

负责：

- 文本结构化理解草稿
- 图片安全校验、解码、OCR、固定模型编码
- 每张图片的稳定身份和证据
- 图文指代对齐

禁止：

- 读取商品营销文案后直接下结论
- 排序、过滤或选择 winner
- 把 OCR 文本当成已确认商品事实

### 4.2 意图识别与任务拆解层

负责：

- 判断推荐、对比、适配、找相似、知识咨询、轻问诊、澄清
- 编译预算、肤质、成分排除、场景等约束
- 判断信息是否足够
- 决定是否追问 1 到 2 个关键问题

禁止：

- 读取商品详情
- 召回商品
- 计算商品分数
- 生成 winner

### 4.3 RAG 召回层

负责：

- 从 Canonical 商品库读取商品事实
- 从知识库、评论库和用户记忆库读取被授权内容
- 文本、图片和结构化条件的多路召回
- 返回候选及来源证据

禁止：

- 根据业务偏好决定 winner
- 把未知字段补成默认事实
- 让图片相似度替代硬条件

### 4.4 决策层

负责：

- 硬条件过滤
- 软条件评分
- 适配判断
- 商品比较
- 稳定排序和 product ID tie-break
- winner、平局或证据不足状态
- 每项结论的证据链

禁止：

- 读取 raw 描述、营销词、评论原文和 raw OCR
- 调用 LLM 决定商品事实或 winner
- 在字段未知时偷偷放宽硬条件

### 4.5 展示层

负责：

- `ResponsePlan`
- 推荐摘要、理由、差异、风险和下一步动作
- 商品卡、比较区、轻问诊说明
- SSE 事件和增量文本

禁止：

- 选品、改序、重新打分
- 推翻 `DecisionResult`
- 用文案补造缺失事实

### 4.6 反馈层

负责：

- 当前会话状态
- 用户明确确认后的稳定画像
- 点击、收藏、对比、负反馈等事件
- 画像版本和来源

优先级：

```text
用户本轮明确表达
> 当前会话已确认信息
> 用户长期画像
> 系统默认值
```

画像只能补空，不能覆盖本轮明确表达。

## 5. 编排器与依赖规则

`orchestrator.py` 只执行以下顺序：

```text
understand
-> plan task
-> retrieve
-> decide
-> build response plan
-> present
-> persist feedback
```

编排器不得实现：

- 词表
- 预算解析
- 商品过滤
- 商品评分
- 文案模板规则

层之间只通过拥有者定义的公开数据合同通信。禁止使用一个跨层的 `CanonicalTurn` 上帝对象。

边界检查器必须阻断：

- 新代码 import `app.services.v2`
- presentation import 具体 retrieval 实现
- decision 读取 raw 描述、评论或 OCR
- retrieval 判 winner
- orchestrator 定义评分或语义词表

## 6. 核心数据合同

### 6.1 输入合同

```text
UserTurn
  session_id
  message
  image_bundle_id?
  conversation_version
```

前端不得把候选商品事实作为可信输入直接送入决策链。

### 6.2 结构化理解

```text
StructuredUnderstanding
  goal
  topic
  observations[]
  exact_constraints[]
  semantic_proposals[]
  image_references[]
  uncertainties[]
  confidence
```

LLM 可以提出受约束的语义草稿，但不能包含：

- `candidate_ids`
- `product_facts`
- `score`
- `winner`
- `sql`

### 6.3 图片合同

```text
ImageBundle
  bundle_id
  session_id
  images[1..4]

ImageObservation
  image_id
  ordinal
  content_sha256
  media_type
  image_kind
  ocr_evidence
  visual_candidates
  identity_status
  confidence
  errors[]
```

`image_id` 和 `ordinal` 在一次会话中稳定。所有“第一张、第二张、这两张”的指代都绑定该合同。

### 6.4 任务计划

```text
TaskPlan
  mode
  referenced_image_ids[]
  constraints[]
  required_evidence[]
  clarification?
```

### 6.5 召回输出

```text
RetrievalResult
  candidates[]
  knowledge_evidence[]
  review_evidence[]
  memory_evidence[]
  missing_sources[]
```

候选必须绑定 `product_id`、来源和召回原因。

### 6.6 决策输出

```text
DecisionResult
  ordered_product_ids[]
  winner_status
  winner_product_id?
  evaluations[]
  comparison_dimensions[]
  risk_findings[]
  evidence_refs[]
  tie_reason?
```

`winner_status` 只允许：

- `SELECTED`
- `TIED_BY_BUSINESS_EVIDENCE`
- `INSUFFICIENT_FOR_WINNER`
- `NO_CANDIDATE`

### 6.7 展示输出

```text
ResponsePlan
  sections[]
  structured_events[]
  text_generation_context
  followup_actions[]
```

展示层只能使用被授权的 `DecisionResult` 和证据摘要。

## 7. LLM 与代码的分工

### 7.1 LLM 负责

- 无限自然语言的任务目标
- 小白用户的现象表达
- 指代和上下文语义
- 轻问诊观察草稿
- 有限枚举和受约束 JSON

### 7.2 代码负责

- 数字、单位、上下限和否定
- JSON Schema 与枚举校验
- 字段授权
- 信号合并和冲突检测
- 商品读取、过滤、排序和 winner
- 安全边界

### 7.3 信号合并

精确数字和方向由代码拥有最终解释权。模型不能覆盖明确的 `300 以上`、`300 以下`、区间和否定。

其他语义信号采用：

```text
本轮用户明确表达
> 当前会话已确认信息
> 长期画像
> 默认
```

本轮内部，精确解析器拥有数字、方向、单位和否定；LLM 负责任务目标、观察和指代。非精确语义信号在同一层级冲突时进入一次澄清。低置信模型提案自动降级为澄清，不进入商品决策。

### 7.4 成本控制

- 精确、无歧义的简单任务可不调用 LLM。
- 模糊表达一次调用同时返回 goal、observations、references 和 proposals。
- 只缓存结构化成功结果。
- 缓存键必须包含 provider、model、prompt/schema 版本、上下文摘要和生成参数。
- fallback 结果必须记录真实 provider/model/status。
- 当前旧 LLM cache 专项为 7 failed / 4 passed，旧实现不得迁入。

## 8. 多图设计

### 8.1 范围

- 一次最多 4 张商品相关图片。
- 支持商品正面、包装、成分表和多商品候选。
- 超过 4 张要求用户分批。
- 二期不分析皮肤照片。

### 8.2 文件限制

- 允许 JPEG、PNG、WebP。
- 单图最大 8 MB。
- 单次总大小最大 20 MB。
- 单图最大 20 百万像素。
- 同时最多执行 2 个图片推理任务。
- MIME、magic bytes 和真实解码结果必须一致。
- 拒绝动画图片和解压炸弹。

### 8.3 上传与会话

前端调用多图分析端口，服务端生成 `bundle_id` 和每张图的 `image_id`。聊天请求只引用 `bundle_id`，不信任前端提交的候选商品事实。

图片分析结果保存在短期会话状态中。移除图片、切换会话或过期后，旧 bundle 不得继续被引用。

### 8.4 权威边界

```text
文字决定：用户想做什么和明确约束
图片决定：用户指向哪些对象并提供视觉/OCR证据
Canonical 决定：商品事实是什么
画像决定：补充用户适配上下文
Decision 决定：适配、比较和 winner
```

不存在全局的“图片优先”或“文字优先”。

### 8.5 典型流程

`这两张哪个好`：

- 文字生成 `COMPARE`
- `image_1`、`image_2` 各自绑定商品
- Canonical 提供可比较事实
- Decision 输出差异、风险和 winner 状态

`第一张适合我吗`：

- 文字生成 `SUITABILITY`
- `image_1` 提供商品身份
- 会话和画像补充肤质、诉求与禁忌
- Canonical 与 Decision 给出适配结论

`找第二张的平替，300 内`：

- 图片 2 是视觉锚点
- 图片相似度负责召回
- 预算由精确解析器形成硬过滤
- Decision 决定最终顺序

只有图片、没有文字：

- 默认执行识别，不擅自推荐
- 返回候选和“找相似、看适配、做对比”动作

### 8.6 冲突

- 文字指定 A，但图片高置信识别为 B：请求确认。
- 图片低置信或多个候选接近：请求确认。
- 两图对比中任一引用图未确认商品身份：停止比较。
- 原始 OCR 与 Canonical 冲突：Canonical 不被覆盖，冲突作为证据问题展示。

## 9. 图片检索与索引

定义统一 `ImageRetrievalPort`。

二期默认实现：

```text
LocalNumpyImageIndex
```

可选扩展：

```text
MilvusImageIndex
```

两个实现必须通过相同合同测试。Milvus 不参与默认启动，不得成为 clean clone 的外部依赖。

本地索引必须覆盖 103/103 商品，并生成 manifest：

```text
product_id
source_image_sha256
model_name
model_weights_sha256
preprocess_version
vector_dimension
vector_sha256
index_sha256
```

现有 100 条 numpy 索引必须废弃并从真实图片重建。

OCR 只用于身份过滤和证据提取，不增加隐藏排序 bonus。图片相似分数相同时使用 numeric product ID 升序作为最终 tie-break。

PIL、OCR、CLIP、numpy 和 Milvus 调用必须在受控 worker 中执行，不阻塞请求事件循环。

## 10. 轻问诊与画像

轻问诊不是新增架构层，而是 intent 和 application 中的一条工作流：

```text
知识咨询
-> 询问可观察现象
-> 结构化 observations
-> 确定性评估规则
-> 暂定结论 + 置信度 + 依据
-> 用户确认
-> 可选进入商品推荐
```

用户不知道肤质时，系统询问“洗脸后是否紧绷、T 区是否出油、是否反复泛红”等可观察现象，不要求用户先提供专业标签。

暂定结论必须说明：

- 依据
- 不确定项
- 置信度
- 何时应停止护肤建议并建议就医

只有用户确认的稳定信息可进入长期画像。临时泛红、一次性预算和未确认推断只保存在当前会话。

## 11. 资产清单

### 11.1 原样迁入的不可再生资产

- `data/canonical/core_products_v1.jsonl`，103 行
- `data/canonical/core_products_v1_manifest.json`
- `review_decisions.jsonl`，1234 行
- `review_decisions_manifest.json`
- 103 张真实商品图片
- 新版前端视觉和交互基线

`data/seed_dump.sql` 只作来源核对，不作为新运行时建表脚本。

### 11.2 原样保留的纯内核

- `app/services/deterministic_ranking.py`
  - SHA-256: `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`

`numeric_boundaries.py` 不作为独立资产文件迁入；新决策模块只按实际需要实现其两个小函数，并迁入零预算边界测试。

### 11.3 删除的机械迁移审核工具

旧 `shadow_evidence/` 曾机械迁入 `tools/evidence_audit/` 并配套 parity
tests。后续逻辑审计确认该实现继承旧仓库缺陷，测试只能证明“搬得一样”，
不能证明审核逻辑正确，因此已删除迁入实现和对应 parity tests。

当前保留：

- 来源 manifest 与 SHA 记录
- shadow evidence fixtures
- 删除原因文档
  `docs/audits/slice0-foundation/evidence_audit_removal.md`
- `app/guide/` 运行时不得 import `tools.evidence_audit` 的边界护栏

未来如需恢复离线审核工具，必须从已批准的新合同、人工审核规则和
fail-closed 语义重新设计；不得恢复或包装已删除的机械迁移实现。

### 11.4 拆后重生的高价值资产

保留不变量和测试，不保留旧依赖形状：

- `IntentConstraintCompiler`
  - 模型提案白名单
  - 禁止 winner、score、SQL、product facts
  - 用户确认、会话、规则、模型的优先级
  - 冲突转澄清
- `decision_contracts`
  - known、unknown、conflict、not applicable
  - hard、soft、clarify
  - winner 状态和决策 trace
- `decision_fields` 与 `candidate_evaluator`
  - 字段能力授权
  - approved fact 决策权
  - hard unknown fail-closed
  - soft unknown neutral
- `canonical_product_reader`
  - manifest/SHA
  - duplicate ID
  - unknown ID fail-closed
- `ingredient_provenance`
  - 来源等级和冲突
- `MonotonicTTLCache`
- `SessionLockRegistry`
- RapidOCR 多版本结果纯解析器
- 会话归属、匿名令牌、公开错误脱敏和 SSE 传输合同

### 11.5 只保留合同、领域知识和测试

- 预算方向、范围和不可偷偷放宽
- 安全风险 cues，只作为高精度安全兜底
- facet 字段授权、来源优先级和冲突
- 评论信号清洗
- 图片主键、upsert、无占位向量和稳定排序
- LLM cache 身份与成功状态
- API/SSE 事件顺序

### 11.6 隔离待审核

22 篇知识文档共 1135 行进入候选知识区，不直接进入生产 RAG。

每条知识必须补齐：

- source URL 或正式资料标识
- 抓取/审核时间
- 适用范围
- 医疗边界
- 审核状态

具体品牌成分、浓度、适用人群和安全结论必须独立核验。

### 11.7 只作历史参考

- V1/V2 Agent
- Presenter
- TurnParser
- followup 全族
- 旧 Retriever 和旧 Ranker
- `semantic_intent_retriever`
- `semantic_embedding_intent`
- 旧图片预处理、embedding、vector service
- 旧 LLM cache
- 旧 Milvus 默认启动和索引脚本
- `v1_freeze_contract.py`

## 12. 前端与 SSE 合同

保留新版前端的：

- 流式增量文本
- 阶段思考展示
- 决策过程
- 商品卡
- 比较区
- 避坑提示
- 追问 chips
- 多图预览
- 会话快照
- XSS 和 URL 安全处理

关键 SSE 事件：

```text
start
stage
intent
decision_process
answer_contract
clarify
chips
skincare_plan
routine_plan
products
comparison
routine
citations
pitfalls
message
error
end
```

规则：

- `start` 携带 `session_id`，匿名会话同时携带 `session_token`。
- `decision_process` 和 `answer_contract` 在 `products` 前发送。
- `message.content` 是增量片段。
- `end` 是唯一正常终止信号。
- error 后不得继续发送新的业务结果。
- 未知事件前端静默忽略。

现有前端已经能选择多图，但会逐张分析后把候选摊平成一个列表。新实现必须改为保留 `image_id` 和上传顺序，不能继续使用扁平 `image_results` 作为可信合同。

## 13. 纵向生长顺序

### Slice 0：资产与合同地基

- 带 SHA 的资产总账
- 新六层目录
- 边界检查
- 公开合同
- 前端行为基线
- 禁止旧 V1/V2 import

### Slice 1：文本推荐

真实问题：

```text
500 内适合油敏肌的防晒
```

必须走完理解、约束、Canonical 召回、决策、SSE 和商品卡。

### Slice 2：单图识别与找相似

- 从零构建 103/103 本地索引
- 真实上传
- OCR 和视觉召回
- Canonical 绑定
- 商品卡

### Slice 3：两图对比

- 图片身份稳定
- 第一张/第二张指代
- 比较维度
- winner、平局或证据不足

### Slice 4：知识咨询与轻问诊

- 小白知识问答
- 观察式追问
- 暂定结论
- 多轮会话状态

### Slice 5：单图适配与三到四图比较

- 画像补空
- 包装和成分表
- 图文冲突确认
- 多候选比较

### Slice 6：补齐二期

- 长期画像
- 场景导购
- 评论总结
- 对比避坑
- 反馈事件

### Slice 7：三期 ports

- 视频
- 达人内容
- 实时学习

每个 slice 必须独立通过端到端门禁后才能开始下一条。

本总设计是架构总纲，不生成一个覆盖 Slice 0 到 Slice 7 的大爆炸实施计划。每个 slice 单独形成实施计划、验收证据和收口点。

## 14. 失败与降级

- 图片解码失败：标记具体 `image_id`，不返回原图作为成功结果。
- 图片身份不确定：返回候选并请求确认。
- 对比缺少任一引用商品：停止比较。
- LLM JSON 非法：丢弃模型提案，使用精确结果或追问。
- 精确约束与模型冲突：精确约束不被覆盖，并记录冲突。
- Canonical 字段未知：按字段策略排除、保持中立或追问。
- 索引 manifest 不一致：健康检查失败，禁止返回空搜索伪装正常。
- 外部 adapter 不可用：返回公开、脱敏的错误。
- 任何失败都不得写 placeholder vector、零向量或假 `success: true`。

## 15. 验收门禁

### 15.1 单元和合同测试

- 每层独立测试
- Local numpy 与 Milvus adapter 通过同一合同测试
- 模型提案非法字段和越权字段测试
- 精确数字、否定和方向测试
- 多图顺序、引用和冲突测试
- 会话所有权和并发测试

### 15.2 四条真实纵向链

1. 文本链

   自然语言改写 -> 意图/约束 -> 召回 -> 决策 -> SSE/前端

2. 图片链

   单图、两图、四图 -> 真实 OCR/固定模型/真实索引 -> 商品卡/比较

3. 多轮链

   知识咨询 -> 轻问诊 -> 会话状态 -> 用户确认 -> 画像补空

4. Clean clone

   从零安装 -> 构建 103/103 索引 -> 启动 -> 浏览器完成前三条流程

### 15.3 LLM 验收

- 无密钥 clean clone 必须能启动并 fail-closed。
- 配置真实 provider 后，必须运行自然语言改写集。
- 真实模型门禁和离线合同门禁都通过后，才可宣称意图能力完成。

### 15.4 证据

每次纵向门禁导出本地 CSV，至少包含：

- case ID
- 输入文本
- image IDs
- 识别候选
- 最终商品 IDs
- 决策状态
- 失败原因
- 各阶段延迟
- 模型与索引版本

Mock 测试只能证明局部逻辑，不能代替发布门禁。

## 16. 当前审计证据

- 决策、字段授权、Canonical 和审核工具专项：300 passed
- 会话缓存、并发和 OCR 解析专项：64 passed
- 会话归属、SSE、公开错误和图片上下文专项：69 passed
- Token 与图片向量存储合同专项：73 passed
- 数据生产脚本专项：44 passed
- 意图约束编译专项：80 passed
- 前端与 XSS 专项：173 passed，另有 5 个 subtests
- LLM cache 专项：7 failed / 4 passed
- 旧 numpy 图片索引：100/103，必须重建

这些结果只用于资产分档，不代表旧系统已达到发布状态。

## 17. 已冻结决策

- 六层业务架构不增加新业务层。
- 编排器不是业务层。
- 新运行时禁止 import 旧 V1/V2。
- 采用合同先行、纵向生长。
- 二期一次最多 4 张商品相关图片。
- 两图对比是第一条多图闭环。
- 文字、图片、Canonical、画像按职责分别拥有权威。
- 默认使用本地 numpy 图片索引。
- Milvus 是可选 adapter。
- 二期不做皮肤照片诊断。
- 数据原样迁入，旧后端按分档保留。
- 少量纯内核可原样保留。
- 高价值业务代码保留不变量和测试，按新合同拆后重生。
- 22 篇知识文档隔离待审核。
- 四条真实纵向链是最终交付门禁。

## 18. 被替代的旧草案

以下本地草案使用了已经废弃的“按层搬文件”和“LLM 只输出意图枚举”方案，不能继续执行：

- `rebuild/ARCHITECTURE.md`
- `rebuild/MIGRATION_CHECKLIST.md`
- `rebuild/EXECUTION_PLAN.md`

正式实施计划只能在本设计完成用户书面复核后生成。
