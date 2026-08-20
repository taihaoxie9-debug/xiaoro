# 连续完成 Guide 意图闭环与唯一入口 Spec

## Why

现有 Guide 已完成二期业务纵向矩阵和 Phase 3A 品类地基，但通用文本理解仍主要依赖
确定性规则，真实 LLM 语义路、三路信号合并、跨 worker 文本状态和 Guide 唯一公开入口
尚未完成。默认启动与公开路由仍可能连接旧 V1/V2，导致新旧逻辑长期并存。

本变更在不修改 Canonical、确定性排序和既有已批准数据的前提下，补齐真实语义意图，
切断旧公开入口，并以字段级 unknown 的方式务实恢复本地 HTML/OCR 来源。

## What Changes

- 新增“精确代码 + 受限 LLM + 会话/画像”三路并行意图理解。
- 新增唯一 `IntentSignalMerger`，集中处理优先级、冲突、低置信和澄清。
- 保留 Guide 自有 SiliconFlow adapter 作为历史基线，新增 DeepSeek 官方 adapter，
  使用 V4-Flash 与 V4-Pro-0813 同题真实 A/B；V3.2 不再消耗额度复跑。
- 将单次八字段长 Prompt 改为“路由语义 + 场景语义”两步理解，并使用分层生产门禁。
- 普通文本会话切换到共享 SQLite CAS，支持 2/4 worker。
- **BREAKING**：默认启动入口切换到 `app.guide_runtime.app:app`。
- **BREAKING**：公开聊天不再自动 fallback 旧 V1/V2。
- **BREAKING**：Guide-only 门禁通过后，物理删除旧 Agent、Presenter、旧意图链和旧入口专属依赖。
- 只读盘点本地 HTML/OCR/图片来源，为 12 个试点和商品 42/49/55 生成
  pending/quarantine。
- 找不到来源时舍弃字段或证据并保持 unknown；核心身份可信时保留商品。
- 数据候选由两个独立只读 verifier 逐项核对；仅 2/2 一致且满足闭合来源政策的候选
  才生成签名 review decision 并受控 promotion，分歧项保持 pending/unknown。
- 使用 2–8 个 Agent 自适应并发、唯一 Integration Writer 和冻结 SHA verifier。
- 整个变更只允许一次开场正式 full-file audit；后续只用 RED/GREEN、targeted
  verification、全量、跨 worker 和浏览器门禁。

## Impact

- Affected specs:
  - 通用意图理解
  - DeepSeek 官方模型接入与选择
  - 多轮会话与画像
  - Guide runtime 与公开 API
  - HTML/OCR/评论来源恢复
  - 旧 V1/V2 退场
  - 动态 Agent、自主执行与审计
- Affected code:
  - `app/guide/understanding/**`
  - `app/guide/intent/**`
  - `app/guide/adapters/llm/**`
  - `app/guide/application/text_recommendation_flow.py`
  - `app/guide_runtime/**`
  - `app/api/v1/chat.py`
  - `app/main.py`
  - `app/config.py`
  - `app/tasks/**`
  - `app/prompts/**`
  - `Dockerfile`
  - `docker-compose*.yml`
  - `start.sh`
  - `README.md`
  - `DEPLOY.md`
  - `tools/guide_gates/**`
  - `tools/guide_data/**`
  - `tests/guide/**`
  - 最终证明不可达的旧聊天代码、测试和脚本
- Protected and unchanged:
  - `data/canonical/**`
  - `app/guide/decision/deterministic_ranking.py`
  - 103 个 Canonical 商品身份、品牌、品类和价格
  - 现有 6 条批准评论及其 source ID/hash
  - 已完成的卡片数量、顺序、图片、问诊、画像、反馈与 SSE 合同

## Authority And Conflict Resolution

实现时按以下优先级裁决：

1. `docs/superpowers/specs/2026-08-12-guide-three-track-weekend-closure-design.md`
2. `docs/superpowers/specs/2026-08-10-guide-intent-cutover-and-pragmatic-data-recovery-design.md`
3. `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`
4. `docs/superpowers/plans/2026-08-11-guide-intent-cutover-closure.md`
5. `docs/superpowers/plans/2026-08-11-pragmatic-data-recovery.md`
6. 既有 Phase 2 与 Phase 3A 规格

固定覆盖规则：

- 既有二期业务矩阵和 Phase 3A 资产保持完成，不重复实现。
- 旧 `unsupported -> legacy` 修改为 `Guide 澄清 1–2 轮 -> 明确范围`。
- 旧 no-LLM 只作历史 slice 离线门禁，不覆盖本变更真实模型门禁。
- 旧 SiliconFlow V4-Flash/V3.2 单阶段 A/B 只保留不可变历史证据；新的生产模型选择
  以 DeepSeek 官方 V4-Flash/V4-Pro-0813 的真实 smoke 与 128 条门禁证据为准，在两阶段
  与单阶段 V4-Pro 候选间择优；两阶段候选在真实证据上不达标时降级为对照与历史证据。
- Guide 唯一公开入口与模型质量门禁解耦：模型失败由 Guide fail-closed
  clarification，禁止恢复旧链。
- 旧 per-capability/final audit 规则修改为项目级唯一开场正式审计。
- 旧 `app/services/**` 保护规则在物理删除任务前继续有效；只能删除，不得修补或搬运。
- 原“自动 reviewer/approval/promotion 永远为 0”修改为双 verifier 一致、签名决策、
  受控 promotion；无共识时仍不得 promotion。
- 废弃 `rebuild/` 三份旧草案，不恢复其执行顺序。

## ADDED Requirements

### Requirement: 三路并行意图

系统 SHALL 同时产生精确代码信号、受限 LLM 信号和会话/画像信号，并且只有唯一
`IntentSignalMerger` 可以把这些信号转换为 `StructuredUnderstanding`。

#### Scenario: 普通自然语言请求

- **WHEN** 用户发送普通文本导购请求
- **THEN** 精确路和语义路并行执行，会话/画像只补空，合并器输出 typed 结果和 trace

#### Scenario: 协议闭合操作

- **WHEN** 请求是已验证的预算 revision、图片 ordinal 等完整 typed 操作
- **THEN** 系统可跳过 LLM，但不得仅凭关键词“看起来明确”任意跳过

### Requirement: 精确约束权威

系统 SHALL 由代码独占数字、金额、单位、范围、上下限、明确否定、成分有无、显式
ordinal 和 source span。

#### Scenario: 模型与精确预算冲突

- **WHEN** 模型 proposal 与代码解析的预算方向或边界冲突
- **THEN** 精确代码结果保持权威，记录 conflict，模型不得覆盖硬约束

#### Scenario: 模型与明确否定冲突

- **WHEN** 模型把用户明确排除的成分或品类解释为正向目标
- **THEN** 合并器保留精确否定并进入澄清或精确结果，不进入错误选品

### Requirement: 受限语义模型

系统 SHALL 使用严格版本化的 `SemanticIntentProposal` 表达 goal、topic、concerns、
observations、references、confidence 和 clarification hint。

#### Scenario: 合法 proposal

- **WHEN** 模型返回符合 schema、有限枚举和置信度要求的 JSON
- **THEN** proposal 经 Pydantic strict validation 后才可进入 merger

#### Scenario: 越权字段

- **WHEN** 模型返回 product/candidate ID、商品事实、price 最终解释、score、winner、
  SQL 或画像写入指令
- **THEN** 整个 proposal 被拒绝，不进入 TaskPlan、召回或决策

#### Scenario: Provider 失败

- **WHEN** API Key 缺失、超时、429、5xx、空响应或非法 JSON
- **THEN** 精确请求继续执行；复杂请求返回澄清或脱敏失败，不回退旧系统

### Requirement: 三路信号合并

系统 SHALL 在一个模块内执行信号优先级、去重、冲突检测和澄清决策。

#### Scenario: 精确路与模型一致

- **WHEN** 两路对 goal/topic 或其他信号一致
- **THEN** 采用结果并记录双来源 `agree` trace

#### Scenario: 模型补空

- **WHEN** 精确路没有开放语义结果而模型返回合法高置信 proposal
- **THEN** 模型只补充非硬语义，不改变已有精确约束

#### Scenario: 非精确信号冲突

- **WHEN** 同级 goal/topic/reference 冲突或模型低置信
- **THEN** 系统追问 1–2 句，不继续选品

#### Scenario: 两轮仍不明确

- **WHEN** 两轮澄清后仍缺少关键语义或请求超出范围
- **THEN** 系统明确说明当前支持范围，不自由回答、不回旧系统

### Requirement: DeepSeek 官方模型接入

系统 SHALL 通过独立 DeepSeek 官方 adapter 调用 `https://api.deepseek.com`，不得把
SiliconFlow 专属请求字段、provider 身份或缓存身份复用于 DeepSeek。

#### Scenario: 非思考结构化调用

- **WHEN** 系统请求 route、detail 或单阶段对照 JSON
- **THEN** 请求使用 `thinking.type=disabled`、`temperature=0`、
  `max_tokens=128` 和 `response_format=json_object`

#### Scenario: Provider 身份隔离

- **WHEN** DeepSeek 与 SiliconFlow 使用相同 prompt/schema 或模型家族
- **THEN** provider、base URL、model、prompt/schema 和 generation parameters
  全部进入缓存身份，两个 provider 之间永不错误命中

### Requirement: DeepSeek V4 模型门禁

系统 SHALL 在同一冻结数据集和真实 smoke 上比较 DeepSeek 官方
`deepseek-v4-flash` 与 `deepseek-v4-pro` 的两阶段候选与单阶段 V4-Pro 候选；V3.2 只保留
历史基线，不再作为生产候选。当两阶段候选在真实 smoke 上不达标、而单阶段 V4-Pro 的
安全硬门全部为 0 且 route-critical smoke 至少 85% 时，系统 MAY 择优将单阶段 V4-Pro
作为生产候选进入 128 条门禁；此时两阶段候选降级为对照与历史证据。所有生产候选仍
SHALL 先通过相同 32 条 smoke 再运行 128 条正式门禁。

#### Scenario: 32 条 smoke

- **WHEN** 任一生产候选（两阶段 V4-Flash/V4-Pro 或单阶段 V4-Pro）第一次进入真实门禁
- **THEN** 先运行相同 32 条 smoke；route-critical 至少 85%、安全硬门全部为 0，
  且前 20 条 unavailable/timeout 不超过 10% 后才允许运行 128 条

#### Scenario: 候选完整 128 门禁

- **WHEN** 任一候选（两阶段或单阶段 V4-Pro）通过 smoke
- **THEN** 在 128 条上要求 route-critical 至少 95%、场景关键字段至少 90%、
  全部失败 fail-closed、所有安全硬门为 0，且端到端 p95 不超过 12 秒；该正式门槛
  对两阶段与单阶段候选完全一致，不因候选形态放宽

#### Scenario: 多候选择优

- **WHEN** 存在多个通过 128 完整门禁的候选（可含两阶段与单阶段 V4-Pro）
- **THEN** 在通过门禁的候选中择优：p95≤12 秒的候选优先，并在其中选择更准者；
  记录被选与被淘汰候选的 provider、模型版本/fingerprint、prompt/schema、usage、
  延迟、价格快照、费用状态和证据 hash

#### Scenario: 仅一个候选通过

- **WHEN** 只有一个候选（两阶段或单阶段 V4-Pro）满足完整门禁
- **THEN** 选择该候选并记录 provider、模型版本/fingerprint、prompt/schema、
  usage、延迟、价格快照、费用状态和证据 hash

#### Scenario: 两阶段不达标而单阶段 V4-Pro 更优

- **WHEN** 两阶段候选在真实 smoke 上不达标（如 route-critical 低于 85% 或存在
  `unsafe_task_plan_mismatch`），而单阶段 V4-Pro 的安全硬门全部为 0 且 route-critical
  smoke 至少 85%
- **THEN** 允许将单阶段 V4-Pro 作为生产候选进入 128 条门禁，两阶段候选降级为对照
  与历史证据；单阶段 V4-Pro 仍须先通过 32 smoke 再运行 128，128 正式门槛不变

#### Scenario: 全部候选均未通过

- **WHEN** 两阶段与单阶段 V4-Pro 候选都不能稳定通过完整门禁
- **THEN** Guide 公开入口保持唯一；只允许针对最早失败层执行一次通用修复，
  同层连续两次失败立即 NO-GO，禁止回旧链和新增单句生产正则补丁

#### Scenario: 单阶段 V4-Pro 候选资格

- **WHEN** 评估“更强模型是否足以替代任务拆分”并已有真实 smoke 证据
- **THEN** 单阶段 V4-Pro 不再是“仅对照、禁止进入生产”；经真实证据择优后 MAY 作为
  生产候选，但仍须先通过相同 32 smoke 再上 128 条完整门禁才可接生产

#### Scenario: 安全澄清与错误执行

- **WHEN** 模型不确定并安全返回 clarification
- **THEN** 记录 `safe_clarification_mismatch` 进入质量统计，但不算安全硬门失败

- **WHEN** 模型造成错误 mode、错误约束、错误指代或错误选品
- **THEN** 记录 `unsafe_task_plan_mismatch` 并使模型门禁失败

### Requirement: API Key 保密

系统 SHALL 只从 `GUIDE_LLM_API_KEY` 环境变量读取当前有效 Key。受监管门禁 MAY
从 `/private/tmp/xiaoro-deepseek-api-key` 读取 Key 后仅注入子进程环境。

#### Scenario: Key 存在

- **WHEN** 运行时加载配置
- **THEN** 只记录 Key 是否存在，不打印、不写日志、不进入命令参数、报告、缓存键或 Git

#### Scenario: 旧 Key 曾公开

- **WHEN** 检测到历史 Key 已暴露
- **THEN** 该 Key 视为无效，不得用于 A/B 或生产请求

#### Scenario: 私有 Key 文件

- **WHEN** 受监管门禁从私有文件加载 Key
- **THEN** 文件必须是 mode 0600 的普通文件且不是 symlink；Key 不进入 argv、日志、
  异常、报告、缓存键、测试 fixture 或 Git，命令结束后环境不残留

### Requirement: 跨 worker 文本状态

系统 SHALL 使用现有 `SqliteConversationState` 作为文本、图片、问诊和画像共享的唯一
会话权威。

#### Scenario: 跨 worker 追问

- **WHEN** worker A 完成首轮推荐，worker B 接收同 session/version 的“第二款呢”
- **THEN** worker B 读取相同候选快照并正确推进版本

#### Scenario: 失败与断流

- **WHEN** clarify、error、stale、零候选或终态交付前断流
- **THEN** 最近有效状态不被污染

#### Scenario: 进程重启

- **WHEN** 新进程使用相同受信状态目录启动
- **THEN** 会话版本、query context 和最近候选可恢复

### Requirement: Guide 唯一公开入口

系统 SHALL 把默认启动、公开 message 和公开 stream 统一到
`app.guide_runtime.app:app`。

#### Scenario: 默认启动

- **WHEN** 使用 Docker、Compose、start.sh、README 或 DEPLOY 中的默认命令
- **THEN** 启动 Guide runtime，不启动旧 `app.main` 依赖图

#### Scenario: 未支持请求

- **WHEN** Guide 无法可靠理解当前请求
- **THEN** Guide 自己澄清或说明范围，不调用旧 V1/V2

#### Scenario: 默认模块加载

- **WHEN** 在全新进程 import 默认 runtime
- **THEN** `sys.modules` 不包含 `app.services`、`app.database`、Redis、pymilvus 或旧 Agent

### Requirement: 旧链物理清理

系统 SHALL 在 Guide-only 完整门禁通过后删除已证明不可达的旧聊天链。

#### Scenario: 依赖仍存在

- **WHEN** 静态或运行时 inventory 发现活动 runtime importer
- **THEN** 禁止删除，先在责任边界迁移或删除 importer

#### Scenario: 依赖证明通过

- **WHEN** 默认入口、测试、工具和后台任务均不再引用旧聊天模块
- **THEN** 使用 `git rm` 删除旧 Agent、Presenter、旧意图链及旧入口专属测试/脚本

#### Scenario: 历史归档

- **WHEN** 旧源码删除完成
- **THEN** 仅通过 Git 历史保留，不创建新的 `legacy/` 或 archive 代码目录

### Requirement: 务实数据恢复

系统 SHALL 只读盘点现有本地 HTML、OCR JSON、详情图片和结构化来源，优先处理 12 个
品类试点和商品 42、49、55。

批准来源根 SHALL 包含用户明确授权的 `/Users/bytedance/Downloads` 和项目 `data`，
不得因旧 inventory 遗漏来源根而宣称原始 HTML 缺失。

#### Scenario: 来源可验证

- **WHEN** 原始文件 SHA、商品 ID、item/SKU 和字段适用性全部可绑定
- **THEN** 生成确定性 pending candidate

#### Scenario: 来源不可信

- **WHEN** 存在 PII、营销、Q&A、跨 SKU、无定位、冲突或未授权来源
- **THEN** 生成 quarantine，不进入生产事实

#### Scenario: 扩展字段缺来源

- **WHEN** 商品核心身份/品牌/品类/价格可信，但扩展字段没有 HTML、原图或官方来源
- **THEN** 舍弃该字段候选并保持 unknown，商品继续可用

#### Scenario: 核心身份冲突

- **WHEN** SKU 串货、商品身份无法绑定，或 identity/brand/category/price 核心字段冲突
- **THEN** 整件商品进入 quarantine

#### Scenario: 历史评论 HTML 缺失

- **WHEN** 未按完整 SHA 找到历史三份 HTML
- **THEN** 336/111 只保留历史 provenance，不从聚合文本伪造原始来源

#### Scenario: 历史评论 HTML 已找到

- **WHEN** 三份 HTML 在批准来源根按完整 SHA 命中
- **THEN** 状态记录为 found=3/missing=0，真实 parser 重放显式评论；不能因历史
  336/111 未自然重现而把来源重新标为 missing

### Requirement: 独立代理审核与受控 Promotion

系统 SHALL 允许自动 inventory、脱敏、pending 和 quarantine，并 SHALL 由两个独立
只读 verifier 对每个可批准候选进行来源、SKU、字段适用性和权限核对。

#### Scenario: 两个 verifier 一致

- **WHEN** 两个 verifier 均确认候选绑定正确、来源有权、字段适用且值一致
- **THEN** 独立 signer 生成包含 `reviewer=agent_verifier_consensus_v1` 的签名 review
  decision，Integration Writer 才可调用既有 promotion 工具

#### Scenario: verifier 分歧或证据不足

- **WHEN** 任一 verifier 拒绝、无法绑定或来源权限不足
- **THEN** 不生成批准决定；冲突项进入 quarantine，其余保持 pending/unknown

#### Scenario: Promotion 安全边界

- **WHEN** 执行受控 promotion
- **THEN** candidate、quarantine、decision SHA 和 HMAC signature 全部通过，
  自动化不得修改 Canonical 核心字段、排序或既有 6 条批准评论

### Requirement: 循环自主审计与止损

系统 SHALL 在开场正式审计后由独立 verifier 自主完成每个 commit 和 gate 的定向审计，
不得再要求用户逐文件审核。

#### Scenario: 正常 checkpoint

- **WHEN** writer 完成一个冻结提交
- **THEN** 独立 verifier 检查代码、测试、边界和证据，Integration Writer 仅集成
  verifier PASS 的提交

#### Scenario: 同一路径重复失败

- **WHEN** 同一最早失败层连续两次修复仍失败
- **THEN** 立即停止该路径、记录卡点并切回设计层裁决，禁止第三次盲修

#### Scenario: 长任务失去监管

- **WHEN** 测试或网络任务 10 分钟无输出且无法解释
- **THEN** 审计进程组并依次 TERM/KILL，确认无残留后才能继续

### Requirement: 最早失败层追责

系统 SHALL 逐层记录 typed 输出并在最早违反合同的责任层修复问题。

#### Scenario: 意图失败

- **WHEN** 一个自然语言用例失败
- **THEN** 依次检查 exact、semantic、merger、TaskPlan、RetrievalResult、
  DecisionResult、ResponsePlan/SSE 和 state，在第一处错误写 RED

#### Scenario: 下游补丁

- **WHEN** API、Presenter、前端、retrieval 或 presentation 试图重解释上游意图、
  二次过滤、打分或选 winner
- **THEN** 边界门禁失败，修复返回真正责任层

### Requirement: 自适应 Agent 执行

系统 SHALL 使用 2–8 个 Agent、最多 4 个代码 writer、最多 1 个 Integration Writer，
且同一文件域最多 1 个 writer。

#### Scenario: 稳定并行

- **WHEN** 连续两个 checkpoint 绿色、文件域无交集且无未知 flaky
- **THEN** 每次增加一个 Agent，优先增加只读 verifier

#### Scenario: Incident

- **WHEN** 共享合同冲突、旧 fallback、数据越权、硬约束覆盖、状态泄漏或门禁结论不一致
- **THEN** 降到 1 fixer + 1 verifier，必要时增加 1 个只读 auditor

### Requirement: 项目级唯一正式审计

系统 SHALL 在项目开始时冻结一次审计身份并真实调用一次正式 full-file audit。

#### Scenario: 开场审计

- **WHEN** 冻结 base SHA、production scope、profile 和 blob manifest
- **THEN** 生成唯一 audit key，并记录 `real_invocations=1`

#### Scenario: Finding 修复

- **WHEN** 开场审计发现 P0–P2
- **THEN** 为 finding 写 RED，由独立 writer 修复，使用 targeted verifier 和正常门禁清除

#### Scenario: 后续阶段或最终收口

- **WHEN** capability 完成、commit/worktree 变化或进入最终收口
- **THEN** 不创建新正式 audit key，不重复 full-file audit

### Requirement: 保护资产不漂移

系统 SHALL 保持 Canonical、确定性排序和现有 6 条批准评论字节与语义不变。

#### Scenario: 最终门禁

- **WHEN** 运行最终机械验证
- **THEN** 排序 SHA 保持
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`，
  Canonical 与批准数据无未授权差异

### Requirement: 正常口语与稍绕表达不得虚假澄清

系统 SHALL 让直接表达、正常口语和稍微绕一点的导购表达继续进入合法任务；只有真实
缺对象、硬条件矛盾、模糊数字、无法唯一绑定或极端对抗才进入 typed clarification。

#### Scenario: 已解析槽位带过时 hint

- **WHEN** 合法高置信 proposal 已包含 goal/topic/reference，而模型仍附带对应
  clarification hint 或 unclear observation
- **THEN** merger 只在最终槽位仍为空时接纳 hint，不得把已解析任务重新变成澄清

#### Scenario: 正常口语与稍绕场景

- **WHEN** 用户用通勤、肤感、预算和肤质组合描述需求但没有模板化关键词
- **THEN** 系统仍生成唯一合法 TaskPlan；普通 false clarification 不超过冻结门槛

### Requirement: 模型提名数字且代码最终校验

系统 SHALL 允许语义模型提名 budget relation、normalized bound、原文和值 span，但代码
SHALL 独占 span 绑定、Decimal 合法性、范围方向、冲突和最终 BudgetDraft 权威。

#### Scenario: 明确中文预算

- **WHEN** 用户说“三百以内”“两百五以内”或“三百到五百”
- **THEN** 模型候选逐字绑定当前原文并经代码验证后形成 300、250 或 300–500 的硬预算

#### Scenario: 模糊口语预算

- **WHEN** 用户说“百来块”“几百上下”“250 左右”或“三张以内”
- **THEN** 系统返回有具体候选含义的 BUDGET 确认，不要求用户改用阿拉伯数字

#### Scenario: 数字冲突或越权

- **WHEN** 模型候选与 exact 阿拉伯数字、方向或已消费 span 冲突
- **THEN** exact 胜出或 typed BUDGET 澄清，模型候选不得进入硬约束

### Requirement: 目录商品名直接比较与适配

系统 SHALL 允许用户直接给出 2–4 个 Canonical 商品名称进行比较，或给出 1 个商品名称
进行 suitability 判断，不要求先生成推荐批次。

#### Scenario: 唯一目录命中

- **WHEN** 原文商品 mention 的 source span 与 103 商品目录中的完整身份或受控别名唯一匹配
- **THEN** 代码绑定 Canonical product ID 并复用现有 comparison/suitability 决策

#### Scenario: 无命中或多命中

- **WHEN** mention 在目录中没有唯一命中
- **THEN** 系统返回 REFERENCE clarification 或目录无数据，不让模型输出或猜测 product ID

### Requirement: 全目录分品类 HTML 数据闭环

系统 SHALL 复用冻结 inventory 和跨平台保存页解析器，对 103 个 Canonical 商品按六个
CategoryProfile 生成适用字段矩阵，不再把 15 商品试点当作完整数据闭环。

#### Scenario: 全目录来源恢复

- **WHEN** 冻结 inventory 包含 118 个顶层保存页
- **THEN** 系统按 exact item/SKU/full SHA 绑定可解析页面，98 个已精确绑定商品全部进入
  分类；其余商品保持明确 source gap，不阻塞已绑定商品

#### Scenario: 分品类参数映射

- **WHEN** 保存页产生 803 组参数和 116 种参数名
- **THEN** 每组参数必须分类为 mapped、identity metadata、ignored non-fact、
  quarantine 或 unsupported-with-reason，`silently_skipped=0`

#### Scenario: 商家宣称

- **WHEN** 功效、肤感、持妆、遮瑕、香调等来自已绑定的商家参数、标题、详情或详情 OCR
- **THEN** 系统 MAY 将其用于 evidence/display/compare/soft-rank，并保留“商家宣称”
  provenance，不把它升级为成分排除、过敏或安全硬事实

#### Scenario: 用户评价与严格字段

- **WHEN** 内容来自用户评价
- **THEN** 只允许体验证据；酒精过敏、成分排除、verified absence 和安全风险仍要求备案、
  完整成分表或明确包装证据

#### Scenario: 103 商品 readiness

- **WHEN** 全目录候选完成分类
- **THEN** 每商品输出 IDENTITY/RECOMMEND/COMPARE/SUITABILITY/FULL/BLOCKED 状态；
  unknown 不得伪装为字段齐全

### Requirement: 非空共识 Promotion

系统 SHALL 对全目录 pending 候选执行两个独立只读 verifier，并在 2/2 PASS 后生成签名
决定和原子 promotion；本轮 DATA_GREEN 不接受 production fact count 继续为 0。

#### Scenario: 非空批准交集

- **WHEN** 至少一个候选通过相同 frozen SHA 上的两个 verifier
- **THEN** 生成 reviewer、reviewed_at、decision、reason 和 detached HMAC signature，
  promotion 后重算 103 商品 coverage/readiness

#### Scenario: 数据完成口径

- **WHEN** 判断本轮 DATA_GREEN
- **THEN** 103 矩阵、98 个精确绑定商品分类、803 参数零静默丢弃、来源分类、双 verifier、
  非零 promotion 和非零 production fact count 必须全部有真实证据

## MODIFIED Requirements

### Requirement: 完整二期完成口径

既有二期十项业务能力矩阵继续视为完成，但整体系统终态修改为 INCOMPLETE，直到真实
LLM 意图、Guide-only、跨 worker 状态和旧链物理清理全部通过。

两步模型未通过质量门时，系统仍保持 Guide-only 并 fail-closed clarification；不得以
恢复 V1/V2 作为完成路径。

### Requirement: 未支持文本

原来未支持文本保持 legacy owner。修改后所有公开文本都由 Guide 接收；无法可靠理解时
追问 1–2 轮，仍不明确则说明范围。

### Requirement: 审计政策

原来 Phase 2/Phase 3A 允许 capability opening audit 和最终独立 audit。修改后，本变更
整个项目只有一次开场正式 full-file audit；最终以 targeted verification 和机械门禁收口。

用户只参与首次方向审计；后续循环由 writer/verifier/Integration Writer 自主审计，
不设置逐文件用户 review gate。

### Requirement: 数据批准政策

原来要求自动 reviewer、批准和 promotion 永远为 0。修改后允许双独立 verifier 一致后
生成签名 review decision 并执行受控 promotion；任何分歧或无来源字段保持 unknown。

### Requirement: `app/services/**` 保护路径

原来禁止任何修改。修改后，在 Guide-only 全门禁通过前仍禁止修改；旧链清理阶段只允许
对已证明不可达的旧聊天模块执行物理删除，不允许修补、包装或复制。

## REMOVED Requirements

### Requirement: Unsupported 自动回退旧 V1/V2

**Reason**: 该路径让新旧系统长期并存，掩盖意图失败并恢复旧污染。

**Migration**: Guide 使用受限 LLM、typed merger 和 1–2 轮澄清收口所有公开请求。

### Requirement: 最终第二次正式 full-file audit

**Reason**: 用户要求整个项目只在开始时审计一次，后续修复由可重复的 RED/GREEN 和门禁
证明，避免重复消耗和重复确认。

**Migration**: 开场 finding 由 targeted verifier 清除；最终记录正式审计调用总数 1、
重复调用 0。

### Requirement: 活动代码树保留 legacy/archive 副本

**Reason**: 平行旧实现会重新形成双轨主链。

**Migration**: 旧实现只保留在 Git 历史；活动代码树删除不可达旧聊天模块。

## Completion Boundary

只有以下全部满足，整体终态才可标记 COMPLETE：

1. 三路意图和唯一 merger 进入真实主链；
2. 两步语义门禁满足安全硬门和分层质量门，或不确定 case 全部 fail-closed clarification；
3. 当前有效 API Key 未泄漏；
4. 硬约束被模型覆盖次数为 0；
5. 模型失败回退旧链次数为 0；
6. 文本状态跨 2/4 worker 和进程重启；
7. 默认入口和公开路由只走 Guide；
8. 旧 Agent、Presenter、旧意图链和旧入口专属依赖已物理删除；
9. 数据缺失保持 unknown，所有 promoted 字段都有双 verifier 共识和签名决策；
10. Canonical、排序和 6 条批准评论无漂移；
11. 正式 full-file audit 真实调用总数为 1，重复调用为 0；
12. focused、full、runtime、boundary、跨 worker、模型与浏览器门禁全部通过；
13. tasks/checklist 全勾选，工作区干净；
14. 未 push、未部署、未切流。
