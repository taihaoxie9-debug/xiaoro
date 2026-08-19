# Slice 1.6 文本主链收口规格

## Why

Slice 1.5 已证明独立干净运行时可以完成防晒、修护精华、最近候选追问和预算修改，但正式聊天 API、多轮版本、前端错误处理和会话并发仍未收口。继续扩展能力会把新逻辑建在分叉且不可靠的入口上。

## What Changes

- 让架构门禁覆盖真实 application 实现和非字面量动态导入。
- 删除展示层伪造的契合百分比和未实际执行的工具步骤。
- 修正 target-aware 肤质三态，泛化肤质证据保持 `unknown`。
- 将具体 adapter 组装移到 `app.guide_runtime` composition root。
- 为同一会话增加有界串行锁，并在首个 post-start 事件前原子提交会话快照。
- 让正式 API 保留 `conversation_version`，并路由所有已支持追问。
- 让前端错误、取消和 DOM 更新绑定发起请求的 session。
- 在运行时启动阶段验证图片 manifest、实际文件、字节数和 SHA。
- 建立共享 HTTP、正常浏览器和对抗浏览器发布门禁。
- 收紧正式聊天 API 的会话归属、错误脱敏和请求体资源边界。
- 生成真实测试证据、全文件代码审查和晨间交接。

## Impact

- Affected specs: 文本推荐、候选追问、预算修改、会话状态、SSE、商品卡、运行时资产完整性。
- Affected code:
  - `app/guide/**`
  - `app/guide_runtime/**`
  - `app/api/v1/chat.py` 的干净接线
  - `app/static/chat.html` 的干净运行时分支
  - `tests/guide/**`
  - `tools/guide_gates/**`
  - `docs/audits/slice1.6/**`

## ADDED Requirements

### Requirement: 真实 application 边界

系统 SHALL 对所有 `application` 文件执行评分和语义词表边界检查，并拒绝无法静态解析目标的动态导入。

#### Scenario: 真实编排器新增评分
- **WHEN** `application/text_recommendation_flow.py` 定义评分标识符
- **THEN** boundary checker 返回 `ORCHESTRATOR_SCORING_LOGIC`

#### Scenario: 动态导入目标来自变量
- **WHEN** guide runtime 使用变量调用 `import_module` 或 `__import__`
- **THEN** boundary checker 返回 `DYNAMIC_IMPORT_NOT_ALLOWED`

### Requirement: 有界会话串行

系统 SHALL 使用固定数量的锁条带串行化同一 session 的流式请求，不按 session 数量无限增长锁对象。锁内 SHALL 完整消费并缓冲 start 之后的同步事件，释放锁后才可公开这些事件；锁不得跨任何公开 yield。

#### Scenario: 同一会话并发请求
- **WHEN** 两个请求同时处理相同 session
- **THEN** 第二个请求在第一个释放会话锁后才进入状态流程

#### Scenario: 正式异步路由保持心跳
- **WHEN** 正式 async router 并发消费两个相同 session 的 SSE 流
- **THEN** 事件循环 heartbeat 继续推进，两个请求均不会因同步锁等待而死锁

### Requirement: 运行时图片资产完整性

系统 SHALL 在 composition 阶段验证图片 manifest 自摘要、JSONL 摘要、实际文件存在性、字节数和图片 SHA。

#### Scenario: 图片文件缺失
- **WHEN** manifest 引用的实际图片不存在
- **THEN** runtime 构建失败，不得以 healthy 状态启动

#### Scenario: manifest 被篡改
- **WHEN** `manifest_sha256` 与规范化内容不一致
- **THEN** loader 抛出明确完整性异常

### Requirement: 浏览器对抗门禁

系统 SHALL 通过自动化浏览器验证公开错误可见、切换 session 会取消旧请求、旧响应不会污染新 session。

#### Scenario: 服务端发送公开错误
- **WHEN** SSE 发送 `GUIDE_INTERNAL_ERROR`
- **THEN** 页面显示脱敏 `message`，不把业务错误记录成 JSON 解析失败

#### Scenario: 流式期间切换会话
- **WHEN** session A 的请求仍在生成时用户切换到 session B
- **THEN** A 的请求被取消，A 的消息和版本不得写入 B

### Requirement: 正式会话历史归属

正式聊天 API 的会话历史读取和删除 SHALL 要求已认证用户，并同时以
`session_id` 和 `user_id` 约束数据库操作。无归属记录 SHALL fail-closed 为
`404`；数据库不可用 SHALL 返回 `503`，不得伪装为空历史或删除成功。

#### Scenario: 跨用户读取或删除
- **WHEN** 已认证用户提交不属于自己的 `session_id`
- **THEN** 查询和删除均不返回或修改该会话，并以 `404` 响应

#### Scenario: 会话存储不可用
- **WHEN** 历史查询或删除期间数据库抛出异常
- **THEN** API 返回脱敏 `503`，不得返回空历史或成功文案

### Requirement: 正式聊天错误脱敏

正式非流式和 SSE 聊天端点 SHALL 在服务端保留完整异常日志，但不得把
`str(exception)`、内部路径、SQL 或上游响应返回给客户端。

#### Scenario: 内部依赖抛出带敏感文本的异常
- **WHEN** Agent、数据库或其他内部依赖抛出异常
- **THEN** 客户端只收到稳定错误码和通用文案，响应中不包含原始异常文本

### Requirement: 正式聊天资源边界

正式聊天请求 SHALL 限制请求体字节数、消息长度、历史条数、单条历史内容、
图片数量、图片结果数量和对象键数，并应用现有 chat 专用速率限制。超出模型
合同限制 SHALL 返回 `422`，请求体字节数超限 SHALL 返回 `413`。

#### Scenario: 超大聊天请求
- **WHEN** 请求体、消息、历史或图片集合超过公开上限
- **THEN** 请求在调用 Agent、LLM 或数据库前被拒绝

## MODIFIED Requirements

### Requirement: 肤质 A2 三态

系统 SHALL 将明确覆盖映射为 `matched`、明确排除映射为 `mismatch`、泛化或未明确覆盖映射为 `unknown`。`unknown` 候选保留、排后并标注，不强行指定 winner。

#### Scenario: 多种肤质用于干皮查询
- **WHEN** 用户查询 `500元内干性修护精华`，商品事实仅为“多种肤质适用”
- **THEN** 商品 91 和 38 保留为 `unknown`，结果不是 `NO_CANDIDATE`

### Requirement: 可见快照提交

SSE 没有客户端 ACK。系统 SHALL 先构造完整成功事件，在首个 post-start 事件公开前 CAS 提交会话快照，再于锁释放后公开缓冲事件。客户端只收到 `start` 后关闭时不得升版；一旦公开任一 post-start 成功事件，状态与完整答案 SHALL 已共同确定。CAS 冲突时不得公开或缓冲 `products`/`message`，只公开 `clarify` 和 `end`。

#### Scenario: start 后立即断开
- **WHEN** 客户端收到 `start` 后关闭生成器，尚未请求首个 post-start 事件
- **THEN** 服务端没有为该轮保存快照

#### Scenario: message 后断开
- **WHEN** 客户端收到 `message` 后、`end` 前关闭连接
- **THEN** 服务端快照已经提交，版本和已公开答案保持一致

#### Scenario: CAS 冲突
- **WHEN** recommendation 或 followup 在提交快照时发生 CAS 冲突
- **THEN** 流只公开 `start`、`clarify`、`end`，不得公开 `products` 或 `message`

### Requirement: 正式 API 多轮

正式 API SHALL 接收并透传 `conversation_version`。完整 CategoryDraft 始终由 Guide 路由；序号追问、最低价追问、预算修改和受控模糊追问仅在 `conversation_version > 0` 时由 Guide 路由，避免接管 version 0 的旧系统会话。独立 Guide runtime 不受此 owner gate 限制。

#### Scenario: 不含品类词的预算修改
- **WHEN** 已有 version 1 快照，用户发送 `预算降到100元呢`
- **THEN** 正式 API 进入干净链，返回商品 91 和 version 2

#### Scenario: 旧会话追问不被接管
- **WHEN** version 0 的旧系统会话发送 `第二款呢`、`哪个好` 或 `预算降到100元呢`
- **THEN** 正式 API 不进入 Guide 路由

### Requirement: 当前会话重激活

前端 SHALL 在任何 DOM rehydrate 前检查目标 session 是否已经是当前 session。相同 session 的激活 SHALL 直接 no-op，不替换在途请求仍拥有的 DOM。

#### Scenario: 点击当前高亮历史项
- **WHEN** 当前 session 正在流式生成，用户点击当前高亮历史项
- **THEN** typing 节点保持连接，请求不取消，后续回答与版本继续写入当前 DOM

### Requirement: 真实展示

前端 SHALL 展示 `明确适配`、`适配待确认` 或 `未限定肤质`，不得把离散证据状态伪造成百分比。Guide runtime 只展示后端实际发送的 stage。

#### Scenario: 敏感肌修护精华
- **WHEN** 商品肤质证据为 `unknown`
- **THEN** 卡片显示 `适配待确认`，页面不出现 `62% 契合` 或默认 `78%`

## REMOVED Requirements

### Requirement: 兼容适配器伪造 match_score

**Reason**: `0.9/0.62/0.72` 没有决策合同或事实来源，会把证据状态伪装成精确结论。

**Migration**: 删除 `match_score` 字段，前端直接消费 `suitable_skin` 的受控证据标签。

### Requirement: Guide runtime 使用前端假工具动画

**Reason**: 当前动画声称执行知识检索和综合评分，但干净 Slice 1.6 未执行这些步骤。

**Migration**: Guide runtime 使用真实 SSE `stage` 文案；旧页面非 Guide 分支暂时保持原行为。

## Constraints

- 不修改旧仓库。
- 不修改 `app/services/**`、`app/database/**`、`data/canonical/**`。
- 不修改 `app/guide/decision/deterministic_ranking.py`。
- 不联网、不下载依赖或模型。
- 不接数据库、Redis、Milvus、LLM、BGE、OCR。
- 不 push、发布、部署或生产切流。
- 不开始 Slice 1.7。

## Residual Risk

- Guide 会话状态和锁仍是 process-local；多 worker 无法保证状态连续或跨进程 CAS。
- 本 Slice 不接数据库、不修改 compose，也未批准生产切流。部署前必须强制单 worker，直到后续 Slice 提供共享原子状态与分布式串行能力。
