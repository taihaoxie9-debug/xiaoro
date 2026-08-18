# Slice 1.5 预算修改追问设计

状态：设计已通过，等待实施计划
日期：2026-08-07
实现工作区：`/Users/bytedance/Desktop/xiaoro-fresh`
分支：`rebuild`

## 1. 背景

当前干净文本护肤运行时已经具备：

- 防晒和修护精华两条真实推荐纵切；
- 服务端最近候选快照；
- `第二款呢` 和 `哪个更便宜` 两类候选集内追问；
- compare-and-set 会话版本和前端按 session 回传版本；
- 独立 FastAPI runtime、真实商品资产和 Playwright 门禁。

这解决了“上一轮页面展示了哪些商品”，但还没有保存“上一轮为什么筛出这些
商品”。因此系统可以回答“第二款呢”，却不能可靠处理：

```text
500 元内敏感肌修护精华
预算降到 100 元呢
```

第二句话没有重复品类、肤质和功效。当前单轮规划会因为缺少品类而澄清；如果
从聊天文案反推，又会重新引入旧系统的文本解析污染。

本 Slice 的目标是建立最小的结构化查询上下文，只开放预算上限修改。它是从
“记得桌上有哪些商品”走向“记得上一轮筛选条件”的第一步。

## 2. 方向决策

采用服务端权威的强类型查询上下文，不采用：

1. 从 assistant 文案反推条件。展示文本不是事实合同，可能被截断、改写或隐藏。
2. 由前端回传完整旧条件。客户端可能丢失或篡改条件，不能成为决策事实源。
3. 直接搬运旧 Agent、TurnParser 或 session 字典。旧链路包含 LLM/BGE 和多种
   模糊继承规则，不符合当前确定性、fail-closed 的地基。

查询上下文与候选快照一起保存在现有 `ConversationStatePort` 后面。进程内
adapter 仍只提供临时状态；本 Slice 不引入数据库或长期画像。

## 3. 目标

只支持修改最近一次成功推荐的预算上限，并继承其余结构化条件后重新执行完整
推荐链：

```text
第 1 轮：500 元内敏感肌修护精华
-> 商品 [91, 38]
-> conversation_version = 1

第 2 轮：预算降到 100 元呢
-> 继承：敏感肌 + 修护 + 精华
-> 替换：预算上限 500 -> 100
-> 重新执行 retrieval -> decision -> presentation
-> 商品 [91]
-> winner_status = INSUFFICIENT_FOR_WINNER
-> conversation_version = 2
```

当前 Canonical 和决策链已用完整查询
`100 元内敏感肌修护精华` 验证结果为 `[91]`，不是为设计假造数据。

## 4. 非目标

本 Slice 不实现：

- 修改肤质、功效、品类或成分排除；
- “便宜一点”等没有明确金额的相对预算；
- 预算下限、预算区间或比例变化；
- 裸数字、模糊代词或开放式条件继承；
- “换一批”、更多选项或跳回更早轮次；
- 跨进程、跨设备或数据库持久化；
- 长期用户画像；
- 图片追问、OCR 或图片向量检索；
- LLM/BGE 意图识别、条件合并或排序；
- 旧 Agent、Presenter、TurnParser 或 session 实现迁入。

## 5. 输入边界与优先级

### 5.1 支持表达

第一版只接受带明确修改动词和阿拉伯数字上限的表达：

- `预算降到100元呢`
- `预算改成100元`
- `改成100元以内`
- `控制在100元以内`

这些表达一律解释为新的预算上限。金额后必须出现“元”或“块”，中间可有空格；
金额必须是大于 0 的有限数字。

### 5.2 明确不猜

以下输入不进入预算修改：

- `100呢`
- `便宜一点`
- `预算再低点`
- `预算改成100`
- `一百元以内`
- `预算改成100到200`
- `预算改成0元`

裸数字和相对描述缺少稳定边界；中文数字、区间和非法金额返回明确澄清，不继承
后继续猜。

### 5.3 解析优先级

必须按以下顺序分流：

1. 显式包含受支持品类的输入按新的完整查询处理；
2. `第二款呢`、`哪个更便宜` 等最近候选追问按 Slice 1.4 处理；
3. 明确预算修改表达按本 Slice 处理；
4. 其余输入进入现有单轮理解与澄清。

因此：

- `100 元内敏感肌修护精华` 是完整新查询；
- `预算降到100元呢` 是预算修改；
- `第二款呢` 仍是候选集内追问；
- `100元呢` 不因历史中有预算而被擅自解释。

## 6. 状态合同

### 6.1 查询上下文

在 feedback 层新增最小强类型状态合同：

```text
RecommendationQueryContext
  category: sunscreen | serum
  budget_minimum?
  budget_maximum?
  skin?
  efficacy?
  exclusions[]
```

该合同只保存已进入决策的规范化条件，不保存：

- 用户原文；
- assistant 文案；
- 商品事实、价格或营销描述；
- 语义推断结果；
- 长期用户偏好。

`category` 必填，因为当前 retrieval 必须有明确品类。其他字段按实际
`TaskPlan` 保存；没有预算的完整查询允许两个 budget 字段同时为空，存在的
budget 字段必须是正有限 Decimal。`exclusions` 去重并保持稳定顺序。

feedback 层不导入 intent 的 Pydantic 对象。状态合同使用受控字面值，application
负责在 `TaskPlan` 与 `RecommendationQueryContext` 之间显式转换。转换必须有
双向合同测试，避免两个层级暗中共享可变对象。

### 6.2 扩展会话快照

现有快照扩展为：

```text
ConversationSnapshot
  session_id
  version
  query_context
  candidates[1..3]
```

候选仍只对应页面最近一次实际展示的最多 3 款。查询上下文对应产生这些候选的
完整规范化条件。

当前 state adapter 不持久化，因此不设计旧快照迁移。所有构造
`ConversationSnapshot` 的路径和公共合同 fixture 必须同步升级。

### 6.3 状态保持规则

- 完整新推荐成功：覆盖 query context 和 candidates，版本加 1；
- 预算修改成功且有候选：原子覆盖两者，版本加 1；
- `第二款呢` 或最低价追问成功：保留 query context，只增加版本；
- 澄清、非法预算、stale version：不改状态；
- 预算修改得到零候选：不改状态、不增加版本；
- terminal error：不改状态、不发 `end`。

零候选不写入是本 Slice 的明确取舍。它保留最近一次有实际展示商品的可靠快照，
也避免放宽 `candidates[1..3]` 合同。用户随后可基于原成功条件再次给出明确预算。

## 7. 层级设计

### 7.1 Understanding

新增确定性预算修改草稿：

```text
BudgetRevisionDraft
  maximum?
  issue?
```

解析器只判断“用户是否明确提出预算上限修改”并抽取金额，不读取会话状态，不做
条件继承。

金额验证复用现有预算规范：

- 必须使用阿拉伯数字；
- 必须大于 0；
- 必须是有限 Decimal；
- 本 Slice 只允许 maximum；
- 非法或未支持格式产生受控 issue。

显式品类检测必须先于预算修改检测，防止完整查询被误判成追问。

### 7.2 Intent

新增预算修改计划：

```text
BudgetRevisionPlan
  mode: revise | clarify
  constraints[]
  clarification?
```

进入 `revise` 必须同时满足：

- 输入是受支持预算修改；
- session 存在最近成功快照；
- 请求版本与快照版本一致；
- snapshot 含合法 query context；
- 新预算通过严格验证。

合并规则是“按 constraint kind 替换”：

1. 从 query context 重建完整 `TaskConstraint`；
2. 删除旧 `BudgetConstraint`，包括旧 minimum 和 maximum；
3. 插入新的 maximum budget；
4. 保留 category、skin、efficacy 和 exclusions；
5. 重新执行 `TaskPlan` 的完整合同校验；
6. 保证结果中最多一个预算约束。

Intent 不读取商品，不判断候选，不直接调用 retrieval。

### 7.3 Retrieval

预算修改与候选集内追问不同，必须重新执行 retrieval。

retrieval 只接收继承后的 category：

- 精华预算修改仍只召回 serum；
- 防晒预算修改仍只召回 sunscreen；
- 不允许根据旧 candidates 限制新结果；
- 不允许加入其他品类；
- 不修改 Canonical reader 或召回排序。

测试必须证明预算修改调用 retrieval，且 category 与 query context 一致。

### 7.4 Decision

复用现有 `decide_recommendation`：

- 新预算继续作为硬约束；
- 价格 unknown/conflict 继续 fail-closed；
- 敏感肌 A2 规则不变；
- 修护功效必须有审核证据；
- deterministic ranking 内核不修改。

本 Slice 不新增预算专用打分，也不因候选变少强行指定 winner。

真实验收中商品 91 的敏感肌适配证据仍不足，因此
`winner_status` 必须保持 `INSUFFICIENT_FOR_WINNER`。

### 7.5 Presentation

预算修改是一次完整重新推荐，因此继续发：

- `DecisionProcessEvent`
- `AnswerContractEvent`
- `ProductsEvent`
- `MessageEvent`

文案必须先确认继承和修改，再陈述证据结论，例如：

```text
已沿用“敏感肌修护精华”，把预算上限调整为 ¥100。
现有审核事实下剩余 1 款，但敏感肌适配证据仍不足，
暂不把它表述为唯一最适合。
```

不得写成“更适合”“最佳”或“综合 winner”。展示层不能从用户原文重新解析条件，
只能消费 intent 产出的合并计划和 decision 结果。

### 7.6 Feedback 与 State Adapter

继续复用：

- `ConversationStatePort.load`
- `ConversationStatePort.save(expected_version=...)`
- `InMemoryConversationState`
- 30 分钟 TTL；
- 512 session 容量；
- 最久未更新淘汰；
- 深复制隔离；
- app 实例间状态不共享。

预算修改不新增第二套 session store。query context 与 candidates 必须由同一个
snapshot、同一次 CAS 写入，不能出现“预算已更新但候选仍是旧结果”的半写状态。

## 8. Application 数据流

正常两轮流程：

```text
request
-> load ConversationSnapshot
-> parse candidate follow-up
-> parse budget revision
-> validate snapshot/version
-> rebuild full constraints from query_context
-> replace BudgetConstraint
-> retrieval(category)
-> decision(merged constraints)
-> presentation
-> feedback boundary check
-> CAS save(query_context + visible candidates)
-> end(new conversation_version)
```

建议把现有完整推荐路径提取为 application 内部私有 helper，使完整新查询和预算
修改共用 retrieval、decision、presentation、feedback 和 snapshot 写入顺序。
这是服务于本 Slice 的定向整理，不扩成通用工作流框架。

写状态必须晚于：

- 理解与计划成功；
- retrieval 和 decision 成功；
- 商品展示事实读取成功；
- response plan 构建成功；
- feedback 返回预期 skip 状态。

任一环节异常都不能提前污染 query context。

## 9. SSE 与 Runtime

`IntentData.mode` 增加：

```text
revise
```

预算修改成功事件顺序：

```text
start
-> stage(state)
-> intent(revise)
-> stage(retrieval)
-> stage(decision)
-> decision_process
-> answer_contract
-> products
-> message
-> end(conversation_version)
```

与候选追问的区别：

- 候选追问不重新检索，也不发 winner 事件；
- 预算修改重新执行完整推荐，所以必须发真实决策与回答合同。

`/health` capability 增加：

```text
budget_revision_followup
```

`conversation_state` 仍是 `process_local`。前端协议无需新增字段，继续使用现有
`session_id` 和 `conversation_version`。

## 10. 错误与澄清

- 无 snapshot：
  `我找不到可继承的最近筛选条件，请先发起一次完整推荐。`
- stale version：
  `会话状态已变化，请基于最新结果重试。`
- 非法金额：
  `预算必须是大于 0 的阿拉伯数字。`
- 未支持区间：
  `当前预算追问先支持明确上限，例如“预算改成100元以内”。`
- 模糊相对预算：
  `请给出明确预算上限，例如“预算降到100元”。`
- 零候选：
  `按 ¥N 上限重新筛选后暂无符合硬条件的商品，已保留上一轮有效结果。`
- CAS 冲突：
  返回服务端当前版本，不覆盖新状态。
- 内部异常：
  terminal `GUIDE_INTERNAL_ERROR`，不泄漏异常详情，不发 `end`。

所有正常澄清都不增加版本。预算修改产生零候选时返回当前权威版本。

## 11. 测试与门禁

### 11.1 合同

- `RecommendationQueryContext` extra 字段拒绝；
- category 为受控值且必填；
- budget 为正有限 Decimal；
- exclusions 去重、长度受限；
- snapshot 必须同时包含 query context 和 1..3 个候选；
- public contract gate 覆盖新增合同；
- TaskPlan 与 query context 转换不共享可变对象。

### 11.2 Understanding

- 支持四种明确预算修改表达；
- 空格和“元/块”变体；
- 显式完整品类查询优先；
- 中文数字、零、负数、区间、裸数字和相对描述不猜；
- 缺少“元/块”单位的金额不猜；
- `第二款呢`、`哪个更便宜` 不被预算解析器截获。

### 11.3 Intent

- 只替换旧预算，其他约束完全保留；
- 合并后恰好一个预算约束；
- 无 snapshot 和 stale version 澄清；
- context 还原后的完整计划继续通过 serum repair 规则；
- 输入对象和 snapshot 不被原地修改。

### 11.4 Application

- 完整推荐写入 query context；
- 防晒和精华 context 分别准确；
- 候选追问升级版本时保留 context；
- 预算修改重新调用 retrieval；
- 预算修改沿用原 category、skin、efficacy 和 exclusions；
- 成功结果原子覆盖 context 与 visible candidates；
- 零候选、澄清、CAS 冲突和 terminal error 不写状态；
- 新完整查询覆盖旧 context；
- 原 `第二款呢` 和 `哪个更便宜` 行为不变。

### 11.5 真实数据

后端与 HTTP 两轮门禁必须锁定：

```text
500 元内敏感肌修护精华
-> [91, 38]
-> version 1

预算降到 100 元呢
-> [91]
-> INSUFFICIENT_FOR_WINNER
-> version 2
```

并增加对抗用例：

- stale version 不执行 retrieval；
- `100元呢` 澄清；
- `100元内防晒` 按完整新查询处理；
- 零候选不覆盖上一轮 `[91, 38]`；
- 第二轮后 `第二款呢` 因最新页面只有 1 款而越界澄清。

### 11.6 浏览器

Playwright 在同一个 session 内验证：

1. 首轮显示两张修护精华卡；
2. 输入 `预算降到 100 元呢`；
3. 第二轮只显示商品 91；
4. 回答明确预算已调整且未夸大敏感肌适配；
5. localStorage 当前 session version 为 2；
6. 无 page error、无失败图片、无反馈按钮；
7. 防晒、修护精华和候选追问原浏览器断言继续通过。

### 11.7 回归与保护

- 全量 guide gate 通过；
- runtime gate 通过；
- 双 boundary checker 通过；
- Canonical 和图片资产不修改；
- 旧仓库不修改；
- 旧 API、旧 services、数据库不接回；
- 排序内核 SHA 保持：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`。

## 12. 保护范围

不得修改：

- `/Users/bytedance/Desktop/xiaoro-shopping-master`
- `app/main.py`
- `app/api/v1/chat.py`
- `app/services/**`
- `app/database/**`
- `data/canonical/**`
- `app/guide/decision/deterministic_ranking.py`

允许修改：

- `app/guide/understanding/**`
- `app/guide/intent/**`
- `app/guide/feedback/**`
- `app/guide/application/**`
- `app/guide/presentation/**`
- `app/guide_runtime/**`
- `app/static/chat.html`，仅必要的兼容接线
- 对应 tests、gates 和文档

retrieval 与 decision 只允许为接线或合同适配做最小修改，不新增排序规则。

## 13. 验收标准

- 服务端保存最近成功推荐的规范化 query context；
- 前端不能提供或覆盖服务端 query context；
- 明确预算修改只替换预算上限；
- 品类、肤质、功效和排除项完整继承；
- 预算修改重新执行 retrieval 和现有决策；
- 真实两轮结果锁定为 `[91, 38] -> [91]`；
- 成功版本锁定为 `1 -> 2`；
- 商品 91 不被错误声明为敏感肌唯一最佳；
- 无 snapshot、stale、非法或模糊预算全部澄清；
- 零候选不覆盖最近有效状态；
- 候选集内追问和单轮推荐无回归；
- runtime 如实声明 process-local 与预算修改能力；
- 全量测试、双边界和正式 Playwright 门禁通过；
- 受保护路径和排序 SHA 无漂移。

## 14. 后续顺序

完成本 Slice 后，按同一 query context 合同依次推进：

1. 修改肤质；
2. 增加 verified-absence 成分排除；
3. 再评估图片识别输入。

不得在本 Slice 顺带实现这三项。每项都需要独立设计、真实数据验收和浏览器门禁。
