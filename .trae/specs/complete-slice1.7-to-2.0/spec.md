# Slice 1.7 至 2.0 连续收口规格

## Why

Slice 1.6 已完成文本主链收口，但肤质修改、可审计成分排除、安全图片输入和真实单图检索仍未交付。后续必须以 Slice 2.0 真实浏览器闭环为唯一完成条件，避免再次把中间 Slice 的 PASS 误判为全局完成。

## What Changes

- 先固化 Slice 1.6 Round 4 评审记录，并建立跨 Slice 的 token 使用台账。
- Slice 1.7 支持六种明确肤质修改，继承已有条件后重新执行完整推荐链。
- Slice 1.8 审计 verified-absence 事实，并在用户批准 GO 或 NO-GO 后继续。
- Slice 1.9 建立 1..4 图安全输入、会话归属和可复现索引合同。
- Slice 2.0 使用用户批准的模型和权重，完成真实单图识别、相似召回、Canonical 身份绑定、硬条件决策、SSE、商品卡和浏览器闭环。
- 每个 Slice 记录独立 token 增量；模型切换不得重置同一 Goal 的累计计数。
- 中间 Slice 完成后自动继续，只有两个硬决策门允许暂停。

## Impact

- Affected specs: 多轮条件修改、成分事实、图片上传、图片检索、会话状态、SSE、商品卡、运行时健康、发布门禁、token 计量。
- Affected code:
  - `app/guide/**`
  - `app/guide_runtime/**`
  - `app/api/v1/chat.py` 的干净接线
  - `app/static/chat.html` 的干净运行时分支
  - `tests/guide/**`
  - `tools/guide_gates/**`
  - `docs/audits/slice1.7-to-2.0/**`
  - 经用户批准后才可修改的 `data/canonical/**`

## ADDED Requirements

### Requirement: 全局完成边界

系统 SHALL 只在 Slice 1.7、1.8、1.9、2.0 全部达到各自退出门槛，且 Slice 2.0 真实浏览器闭环通过后宣布 COMPLETE。任何中间阶段的 PASS 不得缩小或替代总目标。

#### Scenario: 中间 Slice 通过
- **WHEN** Slice 1.7、1.8 或 1.9 的测试和审查全部通过
- **THEN** 系统记录阶段检查点并自动进入下一 Slice，不宣布全局完成

#### Scenario: 第 20 轮仍未收口
- **WHEN** Ralph Loop 到达第 20 轮但 Slice 2.0 尚未满足最终门禁
- **THEN** 系统保持未完成状态，生成精确续跑指令和 handoff，不伪造 COMPLETE

### Requirement: Slice 1.7 肤质修改重筛

系统 SHALL 支持敏感肌、油皮、干皮、混合肌、中性肌、油敏肌六种明确肤质修改。修改 SHALL 只替换服务端 `RecommendationQueryContext` 中的 skin，继承品类、预算、功效和排除项，并重新执行 retrieval、decision、presentation。

#### Scenario: 明确修改肤质
- **WHEN** version 1 快照来自“500 元内修护精华”，用户发送“改成敏感肌呢”
- **THEN** 系统保留原品类、预算和功效，返回 `[91, 38]`，winner 变为 `INSUFFICIENT_FOR_WINNER`，版本升为 2

#### Scenario: 修改后继续序号追问
- **WHEN** 肤质修改已成功保存 version 2，用户发送“第二款呢”
- **THEN** 系统只使用 version 2 最近展示候选，不重新召回旧条件

#### Scenario: 模糊或复合修改
- **WHEN** 用户只说“换个肤质”或同轮同时修改预算和肤质
- **THEN** 系统返回明确 clarify，保持最近有效快照和版本不变

#### Scenario: 状态异常
- **WHEN** snapshot 缺失、version stale、presentation 失败或 CAS 冲突
- **THEN** 系统 fail-closed，不覆盖最近有效 query context 或 candidates

### Requirement: Slice 1.8 verified-absence 事实门

系统 SHALL 先审计正式来源，再决定是否开放成分排除成功能力。“成分表未出现某项”不得推导为 verified absence。

#### Scenario: 存在合格 absence 事实
- **WHEN** 正式来源明确声明“不含/无添加/free from”，且具备 product ID、规范化物质名、原文、来源、时间、审核记录和内容 SHA
- **THEN** 系统进入 Canonical 硬决策门；只有用户批准具体事实后才可更新 Canonical 和实现排除链

#### Scenario: 不存在合格事实
- **WHEN** 审计未找到满足准入条件的正式来源
- **THEN** 系统生成 NO-GO 证据，不修改 Canonical、不开放假成功，并等待用户确认 NO-GO

#### Scenario: 批准后的排除决策
- **WHEN** 用户基于批准事实发送单个明确成分排除修改
- **THEN** known present 商品被排除、verified absence known 商品保留、unknown/conflict 继续 fail-closed

### Requirement: Slice 1.9 安全图片输入

系统 SHALL 接受 1..4 张 JPEG、PNG 或 WebP，并在任何视觉推理前校验声明 MIME、magic bytes、真实解码、动画、尺寸、像素和体量边界。

#### Scenario: 合法图片 bundle
- **WHEN** 用户上传 1..4 张合法图片，单图不超过 8 MB、总大小不超过 20 MB、单图不超过 2000 万像素
- **THEN** 系统按稳定顺序创建强类型 `ImageBundle` 和 `ImageObservation`，分配不可猜测 ID 并绑定 session owner token

#### Scenario: 伪装或危险图片
- **WHEN** 扩展名、MIME、magic 或解码结果不一致，图片为动画、超像素或疑似解压炸弹
- **THEN** 系统在创建可用 bundle 前拒绝输入，不进入 OCR、向量化或推荐

#### Scenario: 跨会话引用
- **WHEN** 请求只知道他人的 bundle ID，或 session/token/版本/TTL 任一不匹配
- **THEN** 系统 fail-closed，不返回观察结果、不允许聊天请求引用该 bundle

#### Scenario: 未批准模型
- **WHEN** 索引构建没有用户批准的模型、权重和 SHA
- **THEN** 构建命令明确失败，不生成零向量、placeholder index 或假相似商品

### Requirement: Slice 1.9 可复现索引合同

系统 SHALL 定义 `ImageRetrievalPort` 和本地索引 manifest。manifest SHALL 记录 product ID、源图 SHA、模型名、权重 SHA、预处理版本、向量维度、向量 SHA 和索引 SHA。

#### Scenario: 103 张源图预检
- **WHEN** 索引构建进入源图预检
- **THEN** 103/103 图片均存在，且路径、字节数和 SHA 与 Canonical 图片 manifest 一致

#### Scenario: 索引漂移
- **WHEN** 任一源图、向量、预处理版本或索引 SHA 与 manifest 不一致
- **THEN** 运行时健康检查失败，检索接口不得返回成功

### Requirement: Slice 2.0 模型硬决策门

系统 SHALL 在真实向量构建前提供模型家族、权重来源、许可证、权重 SHA、下载需求、CPU 延迟和可选 GPU 加速信息，并等待用户批准。

#### Scenario: 未获模型批准
- **WHEN** 模型或权重尚未得到用户明确批准
- **THEN** 系统保持 `WAITING_FOR_USER_DECISION`，可完成不依赖模型的审计和合同，但不得构建真实索引或宣布 Slice 2.0 完成

### Requirement: Slice 2.0 真实单图闭环

系统 SHALL 使用批准模型跑通真实上传、安全解码、OCR/视觉观察、本地向量召回、Canonical 身份绑定、硬条件决策、SSE、商品卡和浏览器展示。

#### Scenario: 索引内真实图
- **WHEN** 使用索引内真实商品图查询
- **THEN** top-1 命中自身 product ID，并展示真实商品图和详情链接

#### Scenario: 重编码查询图
- **WHEN** 同一商品图经过受控缩放或重新编码
- **THEN** top-3 包含自身 product ID，且重复运行排序稳定

#### Scenario: 图片叠加文本硬条件
- **WHEN** 图片请求同时带有明确预算、品类或排除条件
- **THEN** 相似度只负责召回，文本硬条件仍由确定性决策层执行

#### Scenario: 低置信或冲突
- **WHEN** 多个候选分数接近、身份未确认、OCR 与 Canonical 冲突或没有候选
- **THEN** 系统请求确认或返回明确无结果，不覆盖 Canonical、不产生 winner、不回退假算法

#### Scenario: 模型或索引故障
- **WHEN** 模型不可用、索引缺失或 manifest/SHA 损坏
- **THEN** `/health` 非 healthy，客户端收到脱敏错误，不返回空成功

### Requirement: Goal token 计量

系统 SHALL 使用同一 Goal 的累计 `tokens_used` 记录 Slice 1.7 至 2.0 的实际消耗，并按检查点计算阶段增量。模型切换不得重置同一 `goal_id` 的计数。

#### Scenario: Goal 启动
- **WHEN** Ralph Loop 开始
- **THEN** 系统记录 `goal_id=6a76acf2a50b6afe00c97e8c`、起始累计 token、时间和 HEAD

#### Scenario: 阶段检查点
- **WHEN** Slice 开始、完成或进入硬决策门
- **THEN** 系统追加 timestamp、goal ID、stage、event、累计 token、相对上一检查点增量、HEAD 和状态

#### Scenario: Goal 被中断并重建
- **WHEN** 新 Goal 使用不同 `goal_id`
- **THEN** 系统创建新 segment，最终总消耗为各 segment 实际消耗之和，不跨 goal ID 直接相减累计值

#### Scenario: 最终完成
- **WHEN** Slice 2.0 与最终审计全部通过
- **THEN** 系统生成各 Slice、硬门、测试/Review、Goal segment、起止 HEAD 和耗时汇总，再以 `update_goal(status="complete")` 返回值报告最终 token

### Requirement: 每阶段统一门禁

每个 Slice SHALL 通过 focused tests、Guide 全量、runtime 全量、双 boundary、compileall、diff check、排序 SHA、真实数据 case matrix、正式/runtime HTTP、正常及对抗 Playwright、full-file review、本地提交和阶段 handoff。

#### Scenario: 任一门禁失败
- **WHEN** 当前 Slice 任一必须门禁失败或存在未解决 P0-P2
- **THEN** 当前 Slice 保持未完成，先新增修复任务并复验，不进入下一 Slice

## MODIFIED Requirements

### Requirement: 最近候选状态

最近候选快照 SHALL 同时保存本轮实际 query context，并只在首个 post-start 成功事件可见前原子提交。肤质修改和获批准的成分排除修改 SHALL 基于该服务端 context 替换单一约束；序号/最低价追问 SHALL 继续只读取最近实际展示候选。

### Requirement: 正式 API 多轮所有权

完整 CategoryDraft 始终由 Guide 路由。候选追问、预算修改、肤质修改和获批准的成分排除修改仅在正 conversation version 且服务端存在对应 Guide 状态时由 Guide 路由。图片请求只允许引用服务端签发且归属匹配的 bundle ID。

### Requirement: 真实展示

前端 SHALL 只展示后端真实提供的离散肤质证据、审核成分事实、图片身份状态、模型版本和索引版本。不得展示无来源百分比、假工具阶段、假识别成功、假安全结论或旧会话迟到响应。

## Constraints

- 严禁修改 `/Users/bytedance/Desktop/xiaoro-shopping-master`。
- 严禁修改 `app/guide/decision/deterministic_ranking.py`；SHA 必须保持 `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`。
- 新主链不得 import `app.services`、旧 V1/V2 Agent、旧图片服务或默认 Milvus 链。
- 默认不修改 `app/services/**`、`app/database/**`。
- 未经用户批准不得修改 `data/canonical/**`。
- 未经用户批准不得联网、下载、选择或更换模型和权重。
- 不 push、不发布、不部署、不切生产流量。
- 不使用假商品、假图、假向量、假 success 或宽松降级通过门禁。
- 4 个 `/private/tmp/xiaoro-slice16-*` worktree 不继续开发、不擅自删除。

## Hard Decision Gates

只有以下两类事项允许暂停自动执行：

1. 新增或修改 Canonical，以及批准 verified-absence 或确认 NO-GO。
2. 选择、下载或授权模型与权重。

在硬门前 SHALL 完成所有不依赖用户决策的审计、合同、测试和候选方案。硬门不得被标记为 PASS、FAIL 或 COMPLETE。
