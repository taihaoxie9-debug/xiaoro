# Guide 意图闭环、唯一入口与务实数据恢复设计

状态：用户已批准方向；2026-08-11 补充语义分工、多轮追问与画像细化（见 3.6–3.11）
日期：2026-08-10（2026-08-11 细化）
工作区：`/Users/bytedance/Desktop/xiaoro-fresh`
分支：`rebuild`

最高架构事实源：

- `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`
- `.trae/specs/complete-phase2-continuously/spec.md`
- `docs/superpowers/specs/2026-08-10-category-aware-guide-data-foundation-design.md`

## 1. 决策摘要

当前系统完成了二期十项业务能力的确定性纵向链，但没有完成最高架构总纲要求的
真实 LLM 意图语义路，也没有把公开入口从旧 V1/V2 完全切换到 Guide。

因此必须区分三种完成状态：

```text
二期业务纵向矩阵：COMPLETE
通用意图架构：INCOMPLETE
Guide 唯一公开入口：INCOMPLETE
整体终态：INCOMPLETE
```

本设计采用三个有依赖关系的工作流：

1. 恢复“精确代码 + 受限 LLM + 会话/画像”三路并行意图架构。
2. 通过真实模型门禁后，把 Guide 切为唯一公开入口并断开旧 V1/V2 fallback。
3. 以小项目规模恢复现有 HTML/OCR 来源，只生成 pending/quarantine，不追求全量，
   不自动批准。

顺序为：

```text
意图合同与离线门禁
-> 真实模型 A/B
-> 跨 worker 状态修复
-> Guide-only cutover
-> 旧链依赖证明与物理删除
-> 来源恢复与候选队列持续补充
```

意图门禁未通过前不得切断旧入口。数据不全不阻塞切换，但必须保持 unknown，
不得用模型、OCR、评论或营销文案补造商品事实。

### 1.1 小项目边界

本设计不把项目扩成通用 AI 平台：

- 不新建微服务、消息队列、分布式缓存或新的数据库集群；
- 不微调模型；
- 不建立多 provider 自动路由平台；
- 不追求一晚补齐 103 个商品的所有字段；
- 不重写已经可用的候选构建和 promotion 工具；
- 只新增一个 SiliconFlow adapter、一个 typed merger，并复用现有 SQLite 状态适配器。

## 2. 当前事实

### 2.1 已完成

- `app/guide/**` 与 `app/guide_runtime/**` 不 import 旧 `app.services`。
- 103 个 Canonical 商品均有已知商品身份、品牌、原始品类和价格。
- 103/103 商品图片已建立固定 OpenCLIP 本地索引。
- 二期十项能力、四条纵向链、Guide/runtime 全量和浏览器矩阵已有绿色证据。
- 六个品类画像覆盖 39/39 个 Canonical 原始品类。
- 现有 6 条批准评论可追溯到 3 个天猫商品页面，覆盖商品 42、49、55。
- category fact 和 review candidate/promotion 工具已存在，自动化不能批准候选。

### 2.2 未完成

- `understand_text()` 只调用 `parse_exact_constraints()`。
- `semantic_proposals` 始终为空。
- `app/guide/adapters/llm/` 只有合同，没有 provider、调用器、prompt、缓存运行时和
  真实模型门禁。
- Round 9 仍在为否定、连接词、量词和嵌套作用域增加句式补丁。
- 普通文本状态使用 `InMemoryConversationState`，不能跨 2/4 worker。
- Docker、README、DEPLOY 和 start 脚本仍默认启动 `app.main:app`。
- `app/api/v1/chat.py` 仍能把公开请求送入旧 V2/V1。
- 生产 category fact sidecar 为 `fact_count=0`。

### 2.3 当前字段覆盖

103 个 Canonical 商品的已知字段覆盖：

| 字段 | 已知数 |
| --- | ---: |
| product_identity | 103 |
| brand | 103 |
| category | 103 |
| price | 103 |
| safety | 73 |
| efficacy | 41 |
| ingredients_present | 37 |
| suitable_skin | 37 |
| texture | 26 |
| usage | 15 |
| spf_pa | 10 |
| verified_absences | 0 |
| water_resistance | 0 |

结论：系统可以可靠认商品并按品类/价格筛选，但不能把缺失的肤质、质地、用法、
不含成分或防水事实写成已知。

## 3. 三路并行意图架构

### 3.1 总体数据流

```text
UserTurn
  ├─ ExactConstraintExtractor
  │    数字、单位、预算方向、明确否定、成分有无、精确来源 span
  ├─ SemanticIntentPort
  │    goal、topic/concern 枚举、观察现象、上下文指代、置信度
  └─ ContextResolver
       当前会话确认信息、长期画像，只补空
                     |
                     v
             IntentSignalMerger
                     |
                     v
          StructuredUnderstanding
                     |
                     v
                 TaskPlan
```

“并行”指三路各自拥有信号解释权，然后统一对账，不是后执行者覆盖先执行者。
精确代码执行很快，可以和异步模型请求同时启动；模型不可用时精确路仍独立可用。
普通自然语言请求默认同时产生精确和模型信号。只有协议闭合、输入 shape 已被 typed
合同完整约束的操作，例如明确的图片 ordinal 或已验证的预算 revision，才允许跳过
模型；不得用“关键词看起来很明确”作为任意跳过模型的理由。

### 3.2 精确代码路

精确代码独占：

- 阿拉伯数字和中文数字；
- 金额、单位、范围、上限、下限；
- 明确否定和成分有无；
- 显式商品序号；
- 已确认 bundle/image ordinal；
- 输入长度和枚举边界；
- source span。

精确代码不负责：

- 无限自然语言意图分类；
- 模糊品类别称的开放式推理；
- 小白现象的语义归类；
- 长距离指代；
- 自由文本知识回答。

Round 9 的 `exact_parsing.py` 必须收缩为硬槽位解析器。已确认的量词+属性、正向谓词
修饰语和后置属性否定问题先写 RED，再以结构化子句/目标解析修复；禁止继续追加无边界
全句正则。

### 3.3 LLM 语义路

新增版本化合同：

```text
SemanticIntentProposal
  schema_version
  goal
  topic?
  concerns[]
  observations[]
  references[]
  confidence
  clarification_hint?
```

`goal` 使用有限枚举，覆盖：

- recommendation
- comparison
- suitability
- image_similarity
- knowledge
- assessment
- followup
- clarification

模型禁止返回：

- candidate_ids
- product_ids
- product_facts
- price bounds 的最终解释权
- score
- winner
- SQL
- raw profile storage mutation

模型输入只包含：

- 当前用户消息；
- 最小化、脱敏、typed 的会话摘要；
- 允许的枚举和 schema；
- 必要的最近候选引用 ID 之外的 ordinal 语义，不包含商品事实正文。

不向模型发送：

- API Key；
- 完整用户画像原文；
- 原始图片；
- 原始 OCR 全文；
- 商品详情、评论原文或候选列表；
- 内部错误堆栈。

### 3.4 会话与画像路

优先级保持：

```text
本轮用户明确表达
> 当前会话已确认信息
> 长期画像
> 默认
```

画像只补空，不覆盖本轮。未确认观察、临时症状、一次性预算和模型推断不能持久化。

### 3.5 Typed 合并器

合并规则：

| 情况 | 结果 |
| --- | --- |
| 精确路与模型一致 | 接受并记录双来源 trace |
| 精确路为空、模型给出合法非硬语义 | 接受模型 proposal |
| 模型与预算/数字方向/明确否定冲突 | 精确路胜出，记录 conflict |
| 同级非精确信号冲突 | 追问 |
| 模型置信度低 | 追问 |
| 模型 JSON 非法或包含禁止字段 | 丢弃 proposal，精确结果或追问 |
| provider 超时/限流/不可用 | 精确结果或追问 |
| 两轮仍不能确定 | 说明当前支持范围，不调用旧系统 |

模型 proposal 只能经过 Pydantic strict validation 后进入 merger。任何 dict/string
旁路都必须被边界测试阻断。

### 3.6 命名与极性的所有权切分（2026-08-11 细化）

本节固定“不要酒精 / 500 以内 / 我不喜欢 300 块的香水”这类表达的责任边界。核心结论：

> 模型只负责“命名”（把人话映射到闭合 code），代码负责“极性、数字和方向”。

分工表：

| 语义维度 | 谁负责 | 说明 |
| --- | --- | --- |
| 品类/成分/诉求叫什么 | 模型 | “无酒精/酒精过敏/alcohol-free”都归一到 `alcohol` 这一闭合 code |
| 包含还是排除（极性） | 代码 | 从“不/无/不含/不要”判定，模型不得输出 `exclude_*` |
| 否定作用在哪个 span | 代码 | 保证“不要酒精”作用在 `alcohol` 而不是 `fragrance` |
| 具体数字 | 代码 | 模型完全不输出数字，`500` 只来自精确路 |
| 数字方向（以内/以上/区间） | 代码 | 方向不明时不得由模型补全 |

三条不可协商的理由：

1. 命名空间接近无限（模型强项），极性/数字空间有限且可验证（代码强项）。
2. 代价不对称：认错名字只是召回偏移，认反“要/不要”会把用户明确拒绝的东西推给他。
3. 防越权：模型只交出中立 `concern=alcohol`，没有机会输出事实、结论或过滤动作。

若某个词映射不到任何已知 code（冷门成分），代码不得把它当硬约束执行；只能忽略该维
或触发追问。这样代码无需硬编码全部成分/品类，只维护一张“真正支持的闭合 code 表”，
由模型负责把人话映射进来。

### 3.7 模型输出的业务字段（2026-08-11 细化）

3.3 的 `SemanticIntentProposal` 在实现时按以下八个业务字段落地（另加技术字段
`schema_version`）。字段数不是目标，用最小闭合集合描述“导购业务动作”才是目标：

```text
goal                最终意图（recommendation/comparison/... 八类，见 3.3）
acts[]              本句包含的 typed 语义动作（可重复），例如：
                      negative_feedback / replace_batch / revise_constraint /
                      add_preference / continue_browsing / withdraw_constraint
topic               品类闭合 code（可空）
references[]        指代类型：current_item / current_batch / candidate_ordinal /
                     image_ordinal / current_topic / previous_constraint（不含商品 ID）
concerns[]          闭合诉求 code（如 dryness/sensitive/longevity）
observations[]     闭合偏好 code（如 low_scent_intensity/lightweight/natural_finish）
confidence          模型自评是否真的理解
clarification_hint  哪里不清楚（闭合 code，不是自由问句）
```

`acts` 是把扁平字段升级为“可重复 typed 动作列表”的关键——它让“不是不要酒精，我是不
要味道太冲”这种一句话包含“修正旧约束 + 新增偏好”的表达能够被完整描述，而不必新增句
式补丁。模型对 `acts` 只做“提议”，例如 `revise_constraint(target=previous_alcohol_
exclusion)`；是否真的撤销硬约束由合并器判定（见 3.9）。

模型输出仍严格禁止 3.3 列出的越权字段（candidate/product ID、商品事实、price 最终解释、
score、winner、SQL、画像写入）。

### 3.8 多轮记忆与上下文摘要（2026-08-11 细化）

多轮与首轮走同一条三路管线，唯一区别是多轮会附带一份定长、typed、脱敏的上下文摘要：

```text
首轮：空上下文        -> 三路 -> 合并 -> 结果
多轮：上下文摘要      -> 三路 -> 合并 -> 结果
```

记忆的权威在代码侧状态（`SqliteConversationState`），不是把历史对话塞回模型。每轮只给
模型一份小摘要，例如：

```json
{
  "conversation_version": 3,
  "active_topic": "fragrance",
  "visible_candidate_count": 4,
  "confirmed_profile_fields": ["skin_type"],
  "pending_clarification": "confirm_hard_constraint_revision"
}
```

它不含商品事实、候选 ID 或原始对话。指代的真正解析（“第二个”到底是哪件商品）由状态路
用代码完成，不由模型猜。由此得到一条重要性质：**多轮不会让输入 token 随对话增长**，第
20 轮喂给模型的仍是这份定长摘要。

Token 策略据此分离，二者不冲突：

- 输入端往死里省：只给定长摘要，不给历史全文/商品数据/候选列表；prompt 固定带版本。
- 输出端求“字段齐”而非“话多”：八个 typed 字段一次判全（都是短 code，成本低）；字段缺
  失反而会触发澄清，导致用户多打一轮、系统多发一次完整请求，那才更贵。
- 三样东西再全也不许输出：自由文本解释、商品事实、数字/极性结论。
- 叠加 Task 5 的 strict-validated SQLite 缓存（512 条 / 24 小时）：同句 + 同摘要指纹命中
  即不再调用模型，多轮里“对/嗯/第二个”等高频短句常常零调用。

### 3.9 硬约束修正的确认闸门（2026-08-11 细化）

当模型 `acts` 提议 `revise_constraint` 去改一条已生效的硬约束（如撤销“排除酒精”），
合并器不得让模型静默改写。判定规则：

- 精确路也能确认这是明确修正（如“不是不要酒精”含明确否定 span）：直接更新硬约束。
- 只有模型理解出、精确路无法确认：建立 `PendingClarification`，
  `reason = confirm_hard_constraint_revision`，列出两个 typed 候选，追问确认后才更新。

即“模型可以发现修正意图，但撤销硬约束这一步必须由代码在确认后执行”。

### 3.10 纯代码追问：从结构缺口到固定问句（2026-08-11 细化）

追问不是让模型“看懂困惑”，而是合并器发现**可枚举的结构缺口**，再由 `ClarificationPlanner`
用固定模板 + 已知槽位拼出问句。缺口类型闭合：

```text
missing_topic                  有预算/偏好但无品类
ambiguous_reference            指代不到唯一商品
ambiguous_numeric_direction    有数字但方向不明
confirm_hard_constraint_revision  疑似修改硬约束（见 3.9）
conflicting_constraints        条件互相矛盾
low_confidence                 模型置信不足
unsupported_goal               当前文字流不拥有该 goal
```

以“我不喜欢 300 块的香水”为例：

```text
代码：金额=300，方向=未知，态度=否定
缺口：ambiguous_numeric_direction
槽位：number=300
候选：[不喜欢刚才那款约 300 元的, 想避开 300 价位]
输出："你是不喜欢刚才那款，还是想避开 300 元左右的价位？"
```

问句是“模板 + 槽位”拼出的，不是模型临场生成。模型最多给 `clarification_hint`（也是 code）
帮助排序问哪个缺口。因此纯代码追问不会漂，也不会因为多一种说法就加分支。

“我不喜欢 300 块的香水”默认策略：上下文能唯一绑定到某个约 300 元的当前商品时解释为
“不喜欢该商品”，否则追问；绝不让模型自行补成 `<=300` 或 `>=300`。

追问不失控的四条硬规则：

1. 一次只问一个：按优先级挑最阻塞的缺口。
2. 只有真正阻塞才问：模糊偏好（“别太贵”）不触发追问，直接作为软信号进排序。
3. 默认倾向先做：能出结果就先出，让用户看结果反应，而非先盘问。
4. 澄清预算：同一缺口最多问 1–2 次，仍不通就说明支持范围，不再反问、不回旧系统。

追问优先级（高到低）：硬约束冲突 > 指代不明 > 用户到底想做什么 > 品类不明 > 数字方向
不明 > 可选模糊偏好。

### 3.11 分层用户画像（2026-08-11 细化）

画像分三层，分层比单一画像更省事，因为它挡住了“临时反馈变永久标签”这个最恶心的 bug：

```text
长期确认画像（跨会话）：只在用户明确声明时写
    "我是干皮" / "我酒精过敏" / "以后都按敏感肌"
会话条件（本次对话）：这次预算、这次不要酒精、这次想买香水；会话结束不自动升级
本轮反馈（一次性）：不喜欢刚才那款、换一批；只影响当前候选与下一次推荐
```

存储成本很低：短期两层复用 Task 7 的 `SqliteConversationState`，长期只是一张小表。唯一
需要设计的是**写入闸门**：只有用户明确声明才升级为长期，模型的任何推断一律只做短期候选。

- “我是干皮，以后都按干皮推” → 可进长期。
- “这瓶用完感觉有点干” → 只能是一次反馈，不得据此永久认定用户是干皮。

读取顺序沿用 3.4：本轮 > 会话 > 长期 > 默认。

推荐采用保守档：长期只存“明确声明的肤质 + 明确过敏原”，其余全短期（YAGNI，bug 少）。



## 4. Provider 与模型 A/B

### 4.1 Provider 边界

新增 Guide 自有 OpenAI-compatible port 和 SiliconFlow adapter。不得 import、包装或复制
旧 `app/services/llm.py`。

环境变量：

```text
GUIDE_LLM_API_KEY
GUIDE_LLM_BASE_URL=https://api.siliconflow.cn/v1
GUIDE_LLM_MODEL
GUIDE_LLM_TIMEOUT_SECONDS
GUIDE_LLM_MAX_TOKENS
GUIDE_LLM_DAILY_BUDGET_CNY
```

Key 只允许来自运行时环境，不得写入日志、异常、测试 fixture、报告、Git 或缓存键。
任何曾出现在聊天、日志或提交中的 Key 必须撤销后重建。

### 4.2 候选模型

官方信息快照日期：2026-08-10。实时账单和模型广场是最终价格事实源。

| 模型 | 用途 |
| --- | --- |
| `deepseek-ai/DeepSeek-V4-Flash` | 主候选，成本和延迟优先 |
| `deepseek-ai/DeepSeek-V3.2` | 稳定基线，JSON mode 已明确支持 |
| `deepseek-ai/DeepSeek-V4-Pro` | 仅当前两者未过质量门禁时抽样验证 |

参考：

- <https://www.siliconflow.cn/models>
- <https://docs.siliconflow.cn/cn/api-reference/chat-completions/chat-completions>
- <https://api-docs.siliconflow.cn/docs/release-notes/overview>

不在设计阶段硬编码生产模型。真实 Key 到位后，同题 A/B 决定默认值。

### 4.3 A/B 数据集

至少覆盖：

1. 现有确定性意图和品类矩阵；
2. Round 9 否定、量词、嵌套 absence；
3. 已确认反例：
   - `不考虑防晒并非常想买香水`
   - `不考虑防晒并帮我推荐香水`
   - `不要这种太甜的香水`
   - `避开所有甜腻的香水`
   - `香水不推荐太甜的`
4. 推荐、比较、适配、找相似、知识、问诊、追问、澄清八类 goal；
5. 最近候选、第一/第二张图片、它/这款等指代；
6. 小白现象和口语改写；
7. 非法 JSON、禁止字段、prompt injection、低置信和冲突；
8. 无 Key、超时、429、5xx、空响应。

### 4.4 选择门禁

先比较：

- schema 合法率；
- goal/topic/reference 准确率；
- 反绕与否定矩阵结果；
- 禁止字段拒绝率；
- 硬约束不可覆盖率；
- 追问准确率；
- P50/P95 延迟；
- prompt/completion/cache token；
- 实际人民币费用。

硬门：

- 明确预算、数字方向、否定和安全边界被模型覆盖：0 次；
- 禁止字段进入正式 TaskPlan：0 次；
- 非法输出造成错误选品：0 次；
- 模型失败回退旧 V1/V2：0 次；
- 所有未通过结果必须公开澄清或脱敏失败。

两者都通过时选 V4-Flash；Flash 质量或 JSON 稳定性不足时选 V3.2；V4-Pro 只在两者
都不通过时进入小样本比较。

## 5. 成本和缓存

- 精确协议类请求可跳过模型；
- 需要目标、观察或指代语义的请求调用一次；
- 使用非思考/低随机设置，短 JSON，严格 `max_tokens`；
- 同一请求最多一次格式修复重试；
- 缓存只保存 strict validation 成功结果；
- 缓存键必须包含 provider、model、prompt version、schema version、typed context hash
  和 generation parameters；
- fallback 必须记录实际 provider/model/status；
- 达到单日预算或调用上限后，复杂请求改为追问，不切旧系统。

首轮 A/B 的费用只按真实 usage 和当日账单统计，不估算缓存命中或未来生产成本。

## 6. Guide 唯一入口

### 6.1 共享状态

普通文本运行时改用现有 `SqliteConversationState`，不再由
`build_runtime_orchestrator()` 注入 `InMemoryConversationState`。

要求：

- 2/4 worker 共享同一 CAS 状态；
- 首轮在 worker A、追问在 worker B 行为一致；
- session owner、conversation version、query context 和最近候选一致；
- clarify、error、stale、零候选和断流不污染最近有效状态；
- SQLite 调用离开事件循环；
- 状态目录权限和 symlink/trusted-root 合同保持现有标准。

### 6.2 默认启动入口

以下默认入口改为：

```text
app.guide_runtime.app:app
```

范围：

- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `start.sh`
- `README.md`
- `DEPLOY.md`

### 6.3 公开路由

- 公开 `/api/v1/chat/message` 与 `/api/v1/chat/stream` 只调用 Guide。
- 删除公开控制流中的 `ChatOwner.LEGACY` 自动 fallback。
- 删除默认运行时对 `app.services.agent`、`app.services.v2.agent`、旧 DB/Milvus/CLIP
  初始化的依赖。
- Guide 已拥有能力内部错误返回脱敏错误并终止。
- 无法可靠理解的请求最多追问 1–2 句。
- 两轮仍不明确时说明当前支持范围。
- 不允许模型自由回答绕过 TaskPlan、Canonical 和 DecisionResult。

旧源码不在切换前删除。Guide-only 连续通过完整门禁后，必须执行依赖证明并物理删除
旧 Agent、Presenter、旧意图链和只服务旧入口的依赖。历史由 Git 保留，不在主仓库
新建 `legacy/` 目录继续堆放旧实现。

### 6.4 机械门禁

默认运行时导入后，新增测试扫描 `sys.modules`，必须不存在：

```text
app.services
app.database
pymilvus
redis
旧 V1/V2 Agent
```

静态扫描和 AST 边界必须同时检查直接 import、动态 import 和字符串模块目标。

## 7. 务实数据恢复

### 7.1 三类数据不能混用

1. **Canonical 基础事实**
   - 商品身份、品牌、原始品类、价格；
   - 继续作为最高产品事实源。

2. **消费者评论**
   - 只用于体验事实和评论摘要；
   - 不生成配方、安全、verified absence、硬过滤或 winner。

3. **HTML/OCR/官方资料的品类事实候选**
   - 只生成 pending/quarantine；
   - 人工批准后才能进入 category fact sidecar。

HTML 评论通过 DOM 解析提取，不是 OCR。OCR 只用于包装图、成分表和详情长图观察。

### 7.2 数字口径纠正

- `291/296`：旧聚合文本的跨字段重复段，不是 HTML 文件数。
- 历史评论链：3 份原始天猫 HTML -> 336 个候选 -> 111 个严格候选 -> 6 条批准评论。
- 当前仓库和已搜索的旧工作区来源目录尚未按锁定 SHA 定位到这 3 份原始评论 HTML；
  用户确认文件未主动删除，因此 Phase F 必须继续在本地来源目录按 SHA 查找。
- 336/111 只能作为 historical provenance，不能宣称本轮重跑。
- 当前 fixture 只证明工具行为：
  - review：2 pending + 4 quarantine；
  - category fact：7 pending + 12 quarantine；
  - 都不是现实生产扩容结果。

### 7.3 小项目范围

不追求一晚覆盖 103 个商品。优先：

1. 12 个六品类试点；
2. 现有评论覆盖商品 42、49、55；
3. 每类只抽取实际用于当前卡片/比较/问答的少数字段；
4. 其余商品继续使用 Canonical 基础事实和 unknown。

舍弃以字段/证据为默认粒度，而不是整件商品：

- 核心身份、品牌、品类和价格可信：保留商品；
- 某个扩展字段无来源：删除该候选字段并保持 unknown；
- 评论无原始记录或 locator：删除该评论证据；
- SKU 串货、商品身份无法绑定、核心身份冲突：整件商品进入 quarantine；
- 不允许用旧聚合文本填回已经舍弃的字段。

不以评论数多、页面营销摘要或 OCR 文本长作为可信度。来源是否可定位、SKU 是否一致、
字段是否适用、内容是否冲突更重要。

### 7.4 来源恢复

只读盘点现有本地 HTML、OCR JSON、详情图片和 structured source：

- 按文件 SHA、item ID、SKU、product ID 建 manifest；
- 查找与三份历史 HTML hash 完全一致的文件；
- 找不到时明确 `source_missing`，不从旧聚合字段反向伪造 HTML；
- raw source 保持本地、未跟踪；
- 生产资产不包含绝对路径、raw HTML、PII 或未批准候选。

候选分类：

```text
来源完整 + SKU 一致 + 字段适用 -> pending
PII/营销/Q&A/跨 SKU/无定位/冲突 -> quarantine
```

用户睡眠期间允许：

- 来源盘点；
- hash manifest；
- PII 脱敏；
- pending/quarantine 构建；
- 候选摘要和人工复核清单。

禁止：

- 自动填写 reviewer；
- 自动生成批准决定；
- 自动 promotion；
- LLM 或 Agent 自批自己的候选；
- 把 OCR/评论提升为配方、安全或 verified absence。

## 8. 错误与安全

- API Key 不得出现在聊天、命令参数、日志、报告、fixture、commit 或 cache key。
- 曾公开的 Key 必须撤销并重建。
- 模型输入日志只记录 request ID、schema/model/prompt version 和 token 统计，不记录完整
  用户消息或画像。
- 模型输出解析失败返回 typed failure，不回显原始 provider 错误。
- Prompt injection 不能扩大 schema、工具、字段或事实权限。
- 模型不能触发网络抓取、数据库写入或 promotion。
- 数据来源恢复只读；promotion 是独立、显式、人工决定后的操作。
- 不 push、不部署、不切流量。

## 9. 测试与验收

### 9.1 离线意图门禁

- SemanticIntentProposal strict schema；
- 禁止字段；
- 数字/否定/预算冲突；
- 低置信和同级冲突；
- 无 Key、超时、429、5xx、空响应、非法 JSON；
- 一次格式修复重试上限；
- 缓存身份和 provider/model/status；
- prompt injection；
- 无模型时简单路径和复杂澄清路径。

### 9.2 真实模型门禁

- V4-Flash/V3.2 同一冻结数据集；
- 输入顺序随机但 case ID 固定；
- 原始响应只保存在受限临时证据目录；
- 导出 normalized result、usage、latency、cost 和失败分类；
- 不用模型自己给模型答案打分；
- 确定性 expected contract 和人工抽样共同评估。

### 9.3 跨 worker 门禁

- 两个独立 orchestrator/process；
- 首轮/追问交叉 worker；
- 文本->图片、图片->文本；
- consultation/profile；
- stale version 和并发 CAS；
- 进程重启后恢复。

### 9.4 Cutover 门禁

- Guide/runtime 全量；
- compileall；
- 双 boundary；
- `git diff --check`；
- 正常与对抗浏览器；
- 默认 Docker 启动；
- 默认运行时模块加载零旧服务；
- 公开 API 不存在 legacy fallback；
- 用户可见错误脱敏；
- SSE 单终态；
- XSS、跨会话、迟到事件和断流。

### 9.5 数据门禁

- 103 Canonical 和排序 SHA 不变；
- 现有 6 条批准评论和 ID/hash 不变；
- source inventory 可重复；
- candidate/approved/quarantine 数量守恒；
- 缺原始 HTML 不伪造 336/111 重跑；
- 自动化产生 0 个批准决定；
- 未批准数据不改变卡片、排序或 winner。

## 10. 分层追责与修复纪律

所有问题按“最早失败合同负责”定位。下游层不得增加兼容分支掩盖上游错误。

| 最早失败位置 | 责任层 | 允许修复范围 |
| --- | --- | --- |
| 数字、预算、明确否定抽取错误 | understanding 精确路 | span、typed hard constraint |
| goal、topic、观察、指代错误 | LLM 语义路 | prompt、schema、模型和语义评测集 |
| 三路信号冲突后仍继续决策 | intent merger | 优先级、conflict、clarification |
| TaskPlan 正确但候选错误 | retrieval/data | 来源、召回、unknown |
| 候选正确但过滤/排序错误 | decision | filter、rank、winner |
| DecisionResult 正确但输出错误 | presentation | 卡片、文案、SSE，不得改序 |
| 追问丢上下文或串会话 | state/feedback | CAS、owner、version |
| 请求进入旧 V1/V2 | composition/transport | 默认入口、owner、fallback |

修复流程固定为：

```text
冻结失败输入
-> 逐层观测 typed 输出
-> 定位最早失败合同
-> 在责任层写 RED
-> 单 writer 修复
-> focused + 上下游合同 + 浏览器复验
```

禁止：

- 为单一说法直接增加跨层关键词补丁；
- 在 API、Presenter 或前端重解释意图；
- retrieval 或 presentation 重新过滤、打分或选择 winner；
- 模型失败后静默进入旧链。

模型系统性误判、prompt/schema 不稳、上下文输入错误或 merger 接受低置信结果，仍属于
工程问题。只有用户请求超出产品范围、表达本身矛盾，或经过 1–2 轮澄清仍缺关键信息，
才属于明确产品边界。

## 11. 自适应 Agent 与唯一审计

复用项目级自治政策，但本项目将正式 full-file audit 收紧为一次。

### 11.1 动态并发

起步使用 `HIGH_RISK`：

```text
active agents: 4–5
concurrent code writers: 2 maximum
integration writers: exactly 1 maximum
writers per file authority: exactly 1 maximum
independent read-only auditor/verifier: at least 1
```

初始角色：

1. Integration Writer：唯一写共享合同、composition、公开入口和状态文档。
2. Intent Writer：拥有 semantic contract、provider port 和 merger 独立文件域。
3. Evaluation Writer：拥有改写集、模型 A/B runner 和结果归一化。
4. Data Inventory Writer：只读盘点 HTML/OCR，输出 pending/quarantine。
5. Independent Auditor/Verifier：只读审查冻结 SHA。

连续两个 checkpoint 绿色、文件域无交集、无未知 flaky 时逐次升到 6–7 个 Agent，
优先增加只读测试、runtime 和浏览器 verifier，不为凑并发增加 writer。

出现下列任一情况立即降到 `INCIDENT`：

- 两个 writer 修改同一文件或同一 authority；
- 共享合同出现语义冲突；
- 旧 V1/V2 fallback 被触发；
- Canonical、排序、卡片权威或数据批准边界漂移；
- 跨 worker/session 状态泄漏；
- 模型覆盖明确硬约束；
- focused/full/browser 结论不一致。

`INCIDENT` 默认只保留 1 个 fixer、1 个 verifier，必要时增加 1 个只读 auditor。

### 11.2 文件和集成纪律

- 每条 writer 线使用独立 worktree；
- 共享文件只由 Integration Writer 修改；
- verifier 在冻结 SHA 的独立 worktree 运行；
- 不允许测试期间被测 HEAD 漂移；
- 集成前比较 source SHA、stable patch ID、production blob manifest 和行为证据；
- 等价 patch/blob 记录复用，不重复 cherry-pick 或创建等价提交；
- 冲突只做加法式语义合并，禁止整文件 `ours`/`theirs`。

### 11.3 项目级唯一正式审计

整个本设计只允许一次正式全范围独立审计：

1. 在实施开始前冻结 base SHA、production scope、audit profile 和 scope manifest；
2. 生成唯一 audit key；
3. 对该 key 真实调用一次 full-file audit；
4. 审计发现的问题逐条建立 RED，再由独立 writer 修复；
5. 同一 key 不得再次调用 full-file audit；
6. 后续阶段不得为每个 capability 创建新的正式 full-file audit；
7. 最终收口不得执行第二次正式 full-file audit。

后续质量证明使用：

- 主线程有界静态检查；
- 独立只读 targeted verifier；
- RED/GREEN；
- focused/full/runtime；
- boundary/compile/diff；
- 跨 worker；
- 正常与对抗浏览器；
- 依赖和 blob manifest。

这些检查自动执行，不要求用户逐阶段复核。只有产品语义无法由现有规格唯一决定、
需要新付费或凭证、破坏性数据操作、push、部署或切流时才升级给用户。

## 12. 实施顺序

### Phase A：状态与合同纠正

1. 冻结起始 SHA、范围并执行唯一一次正式全范围独立审计。
2. 更新完成状态口径。
3. 冻结 SemanticIntentProposal、LLM port、merge trace 和失败合同。
4. 建立自然语言改写和越权测试集。

### Phase B：离线三路意图内核

1. 实现 ExactConstraintExtractor 收缩边界。
2. 实现 SemanticIntentPort fake/recorded adapter。
3. 实现 ContextResolver 和 IntentSignalMerger。
4. 修复已确认句式反例。
5. 完成无 Key fail-closed 门禁。

### Phase C：真实 SiliconFlow A/B

1. 用户在本地设置新 Key。
2. 验证连通性和 JSON mode。
3. V4-Flash/V3.2 同题 A/B。
4. 选择默认模型并记录价格/模型快照。
5. 冻结真实模型门禁结果。

### Phase D：共享状态

1. 普通文本切换 SqliteConversationState。
2. 增加跨 worker/process 测试。
3. 保持 terminal delivery 后提交语义。

### Phase E：Guide-only Cutover

1. 默认启动切到 `app.guide_runtime.app:app`。
2. 公开路由删除 legacy fallback。
3. 无法理解请求进入 1–2 轮澄清。
4. 运行完整测试与浏览器门禁。

### Phase F：务实数据恢复

1. 只读盘点本地来源。
2. 优先 12 个试点 + 商品 42/49/55。
3. 生成 pending/quarantine 和复核清单。
4. 不执行自动 promotion。

Phase F 可与 Phase B/D 的独立文件域并行，但不能修改 Canonical、排序或意图合同。

### Phase G：旧链物理清理

1. 生成旧模块静态和运行时依赖清单。
2. 证明默认入口、测试、工具和数据链不再引用旧实现。
3. 删除旧 Agent、Presenter、旧意图链和只服务旧入口的依赖。
4. 不建立新的 legacy/archive 代码目录。
5. 重跑完整机械和浏览器门禁。

## 13. Definition of Done

只有同时满足以下条件，整体终态才可标记 COMPLETE：

- 三路意图架构真实存在并由唯一 merger 消费；
- 真实模型 A/B 和离线合同门禁通过；
- 已公开的旧 Key 已撤销，当前有效 Key 未泄漏；
- 明确硬约束零模型覆盖；
- 模型失败零旧 V1/V2 fallback；
- 普通文本状态跨 2/4 worker；
- 默认 Docker/启动入口为 Guide runtime；
- 公开聊天零 legacy owner；
- 旧 Agent、Presenter、旧意图链和旧入口专属依赖已从活动代码树删除；
- 不支持请求只追问或说明范围；
- 103 Canonical、排序和 6 条批准评论无漂移；
- 数据不全保持 unknown；
- 唯一开场正式审计只调用一次，所有 finding 已由 RED/GREEN 和 targeted verification
  清零；
- 全量、runtime、boundary、跨 worker 和浏览器门禁无失败；
- 工作区干净；
- 未 push、未部署、未切流。

Git 历史是旧实现的唯一归档，不在活动代码树保留平行生产逻辑。
