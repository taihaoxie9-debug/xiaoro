# Slice 1.4 最近候选追问设计

状态：对话设计已确认，等待书面复核
日期：2026-08-07
实现工作区：`/Users/bytedance/Desktop/xiaoro-fresh`
分支：`rebuild`

## 1. 背景

当前干净主链已经完成两条真实文本导购纵切：

- 防晒：预算、肤质、成分排除、稳定排序和商品卡闭环；
- 修护精华：功效硬证据、敏感肌 A2 和证据展示闭环。

这证明六层架构可以扩展不同业务规则，但运行时仍是单轮无状态：

- `session_id` 只在请求和 `start` 事件中透传；
- `conversation_version` 在运行时被固定为 `0`；
- 服务端不保存页面上一轮实际展示的商品；
- 用户追问“第二款呢”时，系统无法可信地知道第二款是谁。

旧仓库多轮设计对根因的判断仍可参考：不能靠解析 assistant 文本重建候选集。
但旧 Agent、Presenter、TurnParser、BGE、LLM 仲裁和 session 字典实现不得迁入。

## 2. 目标

建立最近一次商品轮的服务端强类型候选快照，并支持两个零 LLM、零重新召回的
候选集内追问：

1. 序号指代：`第二款呢`
2. 价格比较：`哪个更便宜`

核心验收链：

```text
500 元内敏感肌修护精华
-> 页面展示 [91, 38]
-> conversation_version = 1

第二款呢
-> 只返回 [38]
-> conversation_version = 2
-> retrieval 调用次数不增加
```

独立价格验收链：

```text
500 元内敏感肌修护精华
-> 页面展示 [91, 38]

哪个更便宜
-> 只返回 [91]
-> 明确说明价格最低不代表综合适配更好
```

## 3. 非目标

本 Slice 不实现：

- 改预算、改肤质、增加成分排除等条件继承；
- “换一批”、更多选项或跳出候选集重新搜索；
- 跳回更早商品轮；
- 跨进程、跨设备或数据库持久化；
- 长期用户画像；
- 图片追问、OCR 或图片向量检索；
- LLM/BGE 跟进意图识别或排序；
- 任意开放式商品问答；
- 旧多轮代码、旧 Presenter 或旧 session 结构迁入。

## 4. 方案选择

采用服务端强类型快照，不采用：

1. 前端回传上一轮商品事实。该方案允许客户端篡改商品、价格和顺序。
2. 解析历史回答文本。该方案会重演同品牌、重名和截断文本导致的错绑。
3. 重新执行召回。该方案可能跳出用户眼前候选，无法保证“第二款”身份。

当前运行时使用进程内 adapter，但业务层只依赖
`ConversationStatePort`。未来接持久化时替换 adapter，不改追问业务合同。

## 5. 候选边界

### 5.1 严格最近商品轮

“第二款、这两个、哪个”只指向最近一次成功写入 `products` 的商品轮。

新完整推荐成功后，旧快照被整体覆盖。系统不累积本会话所有商品，也不自动
回看更早轮次。

### 5.2 页面实际展示

快照必须对应用户实际看到的卡片：

- 防晒后端可产生 11 个合格候选，但页面只展示前 3 个，快照只存前 3 个；
- 修护精华展示 `[91, 38]`，快照存两项；
- 最大候选数固定为 3，与当前页面 `visibleProducts.slice(0, 3)` 对齐。

后端全量决策结果仍保留原合同，不能为了多轮把防晒结果缩成 3 个。

### 5.3 最小可信快照

状态不保存整张商品卡和商品营销文案，只保存：

```text
DisplayedCandidateRef
  product_id
  ordinal
  skin_match
  matched_efficacies[]

ConversationSnapshot
  session_id
  version
  candidates[1..3]
```

商品身份、品牌、类目、价格、图片和链接在追问时继续从授权事实端口读取。
这样不会在会话状态中复制或长期持有可能变化的商品事实。

## 6. 层级设计

### 6.1 Understanding

新增确定性追问草稿：

```text
FollowupDraft
  action: ordinal_reference | cheapest
  ordinal?
```

支持的明确表达：

- `第一款/第二款/第三款`
- `第1款/第2款/第3款`
- `哪个更便宜/哪款最便宜`

显式出现已支持完整类目与约束时，优先按新推荐处理，不误判成追问。

不识别模糊代词“它、那个”或开放式“哪个好”，避免无证据猜指代和比较维度。

### 6.2 Intent

新增 `FollowupPlan`：

```text
mode: followup | clarify
action
ordinal?
clarification?
```

只有同时满足以下条件才进入 `followup`：

- 输入匹配受支持追问表达；
- session 存在最近候选快照；
- 请求版本与快照版本一致；
- 序号在快照候选范围内。

缺任一条件都转成可见澄清，不默认第一款，不回退旧 Agent。

### 6.3 Retrieval

候选集内追问禁止调用 retrieval。

测试必须使用 spy/raising catalog 证明：

- `第二款呢` 不调用 `retrieve_candidates`；
- `哪个更便宜` 不调用 `retrieve_candidates`。

商品事实仍可通过已授权的 decision/presentation fact ports 按 snapshot ID 读取。
这不是重新召回，也不得加入 snapshot 之外的新 ID。

### 6.4 Decision

新增候选追问结果合同，不伪装成推荐 winner：

```text
FollowupDecisionResult
  action
  ordinal?
  source_candidate_ids[]
  selected_product_ids[]
  evidence_refs[]
```

序号指代：

- 按 snapshot 的 `ordinal` 精确选择；
- 不排序、不打分、不声明综合 winner。

最低价比较：

- 只读取 snapshot 内候选的审核价格；
- 价格 unknown/conflict 的候选不能参与最低价结论；
- 全部价格不可用时澄清证据不足；
- 相同最低价保留平局，不用 product ID 伪造业务 winner；
- 价格只代表审核参考价，不代表适配或质量更好。

### 6.5 Presentation

展示层使用 `FollowupDecisionResult`、snapshot 中的上一轮适配标签和当前授权
展示事实构建商品卡。

序号文案：

```text
你问的是第二款：<商品名>。这是上一轮展示顺序中的第 2 款。
```

最低价文案：

```text
这几款里，<商品名> 的审核参考价最低；这只代表价格维度，
不代表综合适配更好。
```

如果最低价平局，明确列出并列商品，不强选一个。

### 6.6 Feedback

会话状态归 feedback 层拥有：

- `ConversationStatePort.load(session_id)`
- `ConversationStatePort.save(snapshot, expected_version)`

`save` 必须执行 compare-and-set。版本不一致时返回明确冲突，不能覆盖较新的
snapshot。

进程内 adapter 的边界：

- 最大 512 个 session；
- TTL 30 分钟；
- 写入前清理过期项；
- 容量满时淘汰最久未更新项；
- 时钟可注入，测试不真实等待；
- 多个 FastAPI app 实例之间不共享状态；
- 进程重启后状态丢失。

`FeedbackPort.record_turn` 仍保持 `SKIPPED_SLICE_SCOPE`。候选快照是会话状态，
不是用户反馈或长期画像，不得伪装成反馈落库。

## 7. 会话版本

### 7.1 请求

`ChatStreamRequest` 增加：

```text
conversation_version: integer >= 0, default 0
```

`app.guide_runtime.sse` 不再把 `UserTurn.conversation_version` 写死为 0。

### 7.2 成功响应

正常推荐或正常追问成功后：

1. 以请求版本为 expected version 写入/更新状态；
2. 成功后版本加 1；
3. `end` 事件返回新 `conversation_version`；
4. 前端按当前 session 保存新版本；
5. 下一请求带回该版本。

`end` 始终返回服务端权威版本：

- 成功写入后返回新版本；
- 澄清且 snapshot 存在时返回当前 snapshot 版本；
- 服务端没有 snapshot 时返回 0。

terminal error 不发 `end`，不更新版本。

### 7.3 进程重启

如果前端持有大于 0 的版本，但服务端已经没有 snapshot：

- 完整、自包含的新推荐允许作为新会话重新开始；
- 候选追问必须澄清“最近候选已失效，请重新发起推荐”；
- 系统不得根据浏览器历史消息重建 snapshot。

### 7.4 冲突

服务端 snapshot 存在但请求版本不一致时：

- 不执行追问；
- 不覆盖 snapshot；
- 返回“会话状态已变化，请基于最新结果重试”；
- 事件按正常澄清结束，`end` 返回服务端当前版本供前端恢复；
- 不泄漏 snapshot 内容或内部存储对象。

## 8. SSE 合同

`IntentData.mode` 增加 `followup`。

`StageData.stage` 增加 `state`，用于公开表示“已读取最近候选”，但不泄漏内部
存储细节。

`EndData` 替换当前空数据：

```text
EndData
  conversation_version
```

追问成功事件顺序：

```text
start
-> stage(state)
-> intent(followup)
-> products
-> message
-> end(conversation_version)
```

追问不发 `DecisionProcessEvent` 和 `AnswerContractEvent`，避免把用户指代或价格
比较伪装成推荐 winner。

兼容 adapter 把 `end.data.conversation_version` 传给当前前端。既有前端不识别
该字段时仍可结束；升级后前端保存版本。

## 9. Runtime 与前端

`/health` 保持 `slice1_text_skincare`，capabilities 增加：

```text
recent_candidate_followup
```

并明确：

```text
conversation_state = process_local
```

前端新增当前会话版本存储：

```text
lumi_conversation_versions_v1
```

发送请求时按 `session_id` 读取版本；收到 `end` 时写回。清空或新建会话时从
版本 0 开始。

页面不新增复杂控件。用户直接在现有输入框追问，商品卡复用现有渲染。

## 10. 错误与澄清

- 没有 snapshot：`我找不到最近一轮候选，请先重新发起推荐。`
- 序号越界：`上一轮只展示了 N 款，没有第 M 款。`
- 请求版本冲突：`会话状态已变化，请基于最新结果重试。`
- 价格全部缺失：`这些候选缺少可比较的审核价格，暂时无法判断哪款更便宜。`
- 最低价平局：返回并列结果，不报错；
- store 内部异常：terminal `GUIDE_INTERNAL_ERROR`，不泄漏异常详情；
- 未支持的模糊追问：明确澄清当前只支持序号和最低价比较。

所有澄清都不调用旧 Agent，不清除有效 snapshot，不增加会话版本；`end` 只返回
服务端权威版本。

## 11. 测试与门禁

### 11.1 合同

- snapshot 候选 1..3、序号连续且唯一；
- product ID 唯一；
- conversation version 非负；
- followup action 为受控枚举；
- extra 字段拒绝；
- `EndData` 必须携带版本。

### 11.2 Store

- compare-and-set 成功和版本冲突；
- TTL 到期；
- 容量 512 和最久未更新淘汰；
- app 实例间状态隔离；
- fake clock 可复现。

### 11.3 Understanding 与 Intent

- 中文序号和阿拉伯数字序号；
- 最低价表达；
- 显式完整新查询优先；
- 模糊代词不猜；
- 无 snapshot、越界和版本冲突澄清。

### 11.4 Application

- 首轮成功只保存页面可见候选；
- 防晒 snapshot 只含前三个 ID；
- 精华 snapshot 为 `[91, 38]`；
- `第二款呢` 返回 `[38]`；
- `哪个更便宜` 返回 `[91]`；
- 两类追问都不调用 retrieval；
- 新完整推荐覆盖旧 snapshot；
- terminal error 不更新 snapshot。

### 11.5 HTTP 与浏览器

- request/response conversation version 往返；
- 相同 session 连续两轮；
- 页面首轮显示两张精华卡，第二轮显示商品 38 单卡；
- stale version 和越界提示可见；
- 页面刷新后进程未重启时仍可继续追问；
- `/health` 如实声明 process-local 状态；
- 无 page error、无失败图片请求、无反馈按钮。

### 11.6 回归与保护

- 防晒锁定 11 个 ID 不变；
- 修护精华锁定 `[91, 38]` 和
  `INSUFFICIENT_FOR_WINNER` 不变；
- 全量 guide gate 通过；
- 双 boundary checker 通过；
- Canonical 和图片资产不修改；
- 旧仓库不修改；
- 排序内核 SHA 保持：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`。

## 12. 保护范围

不得修改：

- `/Users/bytedance/Desktop/xiaoro-shopping-master`
- `app/main.py`
- `app/services/**`
- `app/database/**`
- `data/canonical/**`
- `app/guide/decision/deterministic_ranking.py`

允许修改：

- `app/guide/understanding/**`
- `app/guide/intent/**`
- `app/guide/decision/**`，但不含锁定排序内核
- `app/guide/presentation/**`
- `app/guide/feedback/**`
- 新增进程内 state adapter
- `app/guide/application/**`
- `app/guide_runtime/**`
- `app/static/chat.html`
- 对应 tests、gates 和文档

## 13. 验收标准

- 最近候选只对应页面最近一次实际展示的最多 3 款；
- 首轮精华 `[91, 38]` 后“第二款呢”只返回 `[38]`；
- “哪个更便宜”只在 `[91, 38]` 内返回 `[91]`；
- 两种追问均不执行 retrieval；
- 缺 snapshot、越界、stale version 全部澄清；
- 新完整查询覆盖旧 snapshot；
- 请求与 `end` 事件正确往返 conversation version；
- 进程内 store 有 TTL、容量和确定性淘汰；
- `/health` 如实声明状态不跨进程持久化；
- 防晒和修护精华单轮链路无回归；
- 保护文件和排序 SHA 无漂移；
- 正式 Uvicorn 与 Playwright 两轮门禁通过；
- 完成后停止，不顺带实现条件继承、图片或长期画像。

完成本 Slice 后，下一阶段是“改条件再筛选”，再之后才进入图片识别。
