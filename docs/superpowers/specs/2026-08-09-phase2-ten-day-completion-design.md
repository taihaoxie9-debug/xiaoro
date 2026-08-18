# 小 Ro 完整二期十天收口设计

状态：用户已批准十天目标，等待书面复核
日期：2026-08-09
实现工作区：`/Users/bytedance/Desktop/xiaoro-fresh`
分支：`rebuild`
最高架构事实源：
`docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`

## 1. 目标

十天内完成总架构定义的本地完整二期，保留真实前端、真实数据、真实模型和
真实浏览器验收，不复用旧 V1/V2 生产模块，不用 mock 代替产品闭环。

十天终点是：

- Slice 0 至 Slice 6 的本地能力全部闭环；
- 四条真实纵向链通过；
- 已迁能力不再回退旧 V2；
- 新 Guide 不 import `app.services`；
- 工作区干净，测试、浏览器、审计和 handoff 完整。

生产发布、正式切流和公网部署不属于十天终点；相关代码必须可部署，但实际
发布仍单独审批。

## 2. 当前基线

当前 `rebuild@3abf9ad` 已完成：

- Canonical 与确定性决策地基；
- 防晒、修护精华文本推荐；
- 最近候选、预算修改、肤质修改；
- SSE、真实商品卡和会话版本；
- 安全 1..4 图上传地基；
- 103/103 OpenCLIP 本地索引；
- 单图商品身份确认与找相似；
- 正常和对抗性浏览器门禁。

当前明确未完成：

- 轻问诊；
- 用户确认后的长期画像；
- 场景导购；
- 评论总结；
- 两图商品对比；
- 单图适配判断；
- 三到四图候选比较；
- 包装和成分表 OCR；
- 完整二期能力的旧 V2 退出。

当前还有五个必须先修复的 P1：

1. 文本 Guide 并发冷启动可能创建两份进程内会话状态；
2. 图文品类冲突时可能跨品类推荐；
3. 图片解码和 SQLite 写入阻塞事件循环；
4. 非流式图片响应缺少顶层 `answer_contract` 和
   `conversation_version`；
5. 历史快照恢复后推荐卡收藏按钮失效。

### 2.1 二期能力唯一矩阵

| 二期总纲能力 | 当前状态 | 十天交付点 |
| --- | --- | --- |
| 用户画像与偏好记忆 | 新 Guide 未实现 | 第 2–4 天 |
| 场景导购 | 新 Guide 未实现 | 第 5–7 天 |
| 商品对比和避坑 | 单图推荐已具备部分风险提示 | 第 2–7 天补齐 |
| 评论总结 | 新 Guide 未实现 | 第 5–7 天 |
| 护肤轻问诊 | 新 Guide 未实现 | 第 2–4 天 |
| 单图商品识别 | 已完成 | 第 9 天复验 |
| 单图适配判断 | 未完成 | 第 5–7 天 |
| 两图商品对比 | 未完成 | 第 2–4 天 |
| 三到四图候选比较 | 未完成 | 第 5–7 天 |
| 商品包装和成分表 OCR | adapter 为 `NOT_CONFIGURED` | 第 5–7 天 |

该矩阵是“完整二期”的唯一完成口径。单图识别或 Slice 2.0 通过不得再被表述
为完整二期完成。

## 3. 十天完成边界

### 3.1 必须完成

- 单品咨询、推荐、比较、知识、轻问诊的商品卡数量由后端唯一决定；
- 轻问诊通过可观察现象形成暂定结论，说明依据、不确定项、置信等级和就医
  边界；
- 只有用户明确确认的稳定信息进入长期画像；
- 本轮明确表达优先于会话确认信息，会话确认信息优先于长期画像；
- 两图比较支持第一张/第二张指代、身份确认、Canonical 比较和
  winner/平局/证据不足；
- 单图适配使用图片商品身份、会话或画像和 Canonical 事实；
- 三到四图比较只比较已确认身份的图片；
- OCR 使用真实 adapter，raw OCR 只提供观察，不覆盖 Canonical；
- 场景导购、评论总结、避坑和反馈事件使用可审计来源；
- 已迁能力不再进入旧 V2。

### 3.2 明确不做

- 皮肤照片诊断；
- 医疗诊断或治疗建议；
- 让 LLM 生成商品事实、候选 ID、分数或 winner；
- 用旧 Agent、旧 Presenter、旧 TurnParser 或旧图片链作为新 Guide
  fallback；
- 为赶时间返回空服务、假成功、假 OCR、假画像或假评论；
- 实际生产发布和流量切换。

## 4. 冻结的共享合同

所有并行开发必须先在第 1 天冻结以下合同。第 2 天后只有集成负责人可以修改
共享合同。

### 4.1 商品卡展示合同

新增后端权威的 `CardDisplayContract`：

```text
mode:
  none | single | recommendation | comparison
visible_product_ids: ordered product IDs
max_cards: 0..4
reason: product | recommendation | comparison
```

约束：

- 单品咨询：`mode=single`，严格 1 张；
- 普通推荐：`mode=recommendation`，严格展示后端提供的 1..3 张；
- 两图比较：`mode=comparison`，严格 2 张；
- 三到四图比较：`mode=comparison`，严格 3..4 张；
- 知识、澄清和轻问诊信息收集阶段：`mode=none`，0 张；
- 轻问诊转入推荐后，必须产生新的推荐合同；
- 前端不得补卡、改序、根据回答文本猜商品或从候选池填满三张；
- `products` 事件中的 ID 和顺序必须与合同完全一致。

### 4.2 会话与画像合同

当前会话保存：

- 当前任务；
- 已确认图片引用；
- 轻问诊 observations；
- 暂定结论；
- 用户确认状态；
- 最近实际展示候选；
- conversation version。

长期画像事实必须包含：

```text
field
value
source_turn_id
source_kind: explicit_user | confirmed_consultation
confirmed_at
profile_version
```

长期画像只补空，不覆盖本轮明确输入。临时泛红、一次性预算、模型推断和未确认
轻问诊结论不得进入长期画像。

### 4.3 图片引用合同

每张图保持稳定：

```text
image_id
ordinal
bundle_id
content_sha256
confirmed_product_id?
identity_state
ocr_observation
```

规则：

- “第一张/第二张”只解析为已有 ordinal；
- 两图或多图中任一身份未确认，停止比较并澄清；
- 文字品类与图片确认品类冲突，停止并澄清；
- raw OCR 与 Canonical 冲突时 Canonical 保持权威；
- 图片相似度只负责召回，预算、品类、肤质和排除项仍由确定性决策执行。

### 4.4 SSE 合同

统一事件顺序：

```text
start
stage*
intent
consultation_observation?
profile_confirmation?
image_observation*
decision_process?
answer_contract
card_display_contract
products?
citations?
pitfalls?
message*
end
```

错误路径发送 `error` 后终止，不补 `end` 或成功事件。前端只消费真实收到的
事件，不显示未执行阶段。

## 5. 并行开发边界

### 5.1 集成与前端线

所有权：

- `app/api/v1/chat.py`
- `app/static/chat.html`
- `app/guide/presentation/sse_events.py`
- 共享公开合同
- Guide/V2 owner matrix

职责：

- 修五个 P1；
- 商品卡展示合同；
- SSE 聚合；
- 前端精确渲染；
- 快照恢复；
- 最终集成。

其他工作线不得直接修改以上文件，只提交所需合同变更请求。

### 5.2 轻问诊与画像线

所有权：

- `app/guide/understanding/consultation_*`
- `app/guide/intent/consultation_*`
- `app/guide/application/consultation_*`
- `app/guide/feedback/profile_*`
- 对应测试

职责：

- 观察式追问；
- 暂定结论；
- 用户确认；
- 长期画像版本和来源；
- 画像只补空。

### 5.3 多图与 OCR 线

所有权：

- `app/guide/understanding/image_*`
- `app/guide/application/image_*`
- `app/guide/adapters/image/ocr_*`
- 图片比较和适配决策 adapter；
- 对应测试。

职责：

- 两图身份和指代；
- 两图比较；
- 单图适配；
- 真实 OCR；
- 三到四图比较；
- 图文冲突确认。

### 5.4 场景、评论与反馈线

所有权：

- `app/guide/retrieval/scenario_*`
- `app/guide/retrieval/review_*`
- `app/guide/application/scenario_*`
- `app/guide/feedback/event_*`
- 对应测试和审计数据。

职责：

- 场景导购；
- 评论摘要；
- 避坑证据；
- 点击、收藏、比较和负反馈事件。

## 6. 十天排期

### 6.0 连续执行规则

“第 1 天”“第 2–4 天”等名称表示能力里程碑和最晚排期，不表示一次 Goal 的
停止点。完整二期使用一个连续 Ralph Goal：

```text
共享地基冻结
-> 三条 worktree 并行实施
-> 按能力小步集成和复验
-> 剩余能力继续实施
-> 四条纵向链总审
-> 完整二期完成
```

每个里程碑通过后，系统 SHALL 提交代码、追加进度、同步任务状态并立即进入
下一里程碑，不请求普通确认，不把阶段 PASS 标记为 Goal COMPLETE。

只有以下情况允许停止：

1. 本文档二期能力矩阵全部完成且最终门禁通过；
2. 所有剩余工作都依赖同一个必须由用户决定的硬门；
3. Ralph 达到系统轮次上限；
4. 用户主动要求暂停。

用户睡醒后可以随时要求“暂停并汇报”；在此之前，阶段 handoff 只是检查点，
不是任务终点。

### 第 1 天：共享地基冻结

- 修复五个 P1；
- 实现商品卡展示合同；
- 删除前端补足三卡逻辑；
- 固化 owner matrix；
- 定义会话、画像、多图和 SSE 共享合同；
- 为三条并行线创建独立 worktree；
- 跑全量、runtime、正式 API 和双浏览器门禁。

退出条件：公共合同冻结，生产代码无未提交改动，三条并行线可独立开工。

### 第 2–4 天：第一并行阶段

- 轻问诊与临时会话状态；
- 两图身份、指代和比较；
- 长期画像存储、版本、来源和确认规则。

每天结束必须各自通过 focused、boundary 和至少一条真实 HTTP 链。

### 第 5–7 天：第二并行阶段

- 单图适配；
- OCR 和三到四图比较；
- 场景导购、评论总结、避坑和反馈事件。

每天结束必须生成可合并提交，不允许在 worktree 积累跨日大 diff。

### 第 8 天：统一集成

- 统一 SSE；
- 接入商品卡、比较区和轻问诊说明；
- 迁移 owner matrix；
- 对已迁能力关闭旧 V2 fallback；
- 解决跨工作线合同冲突。

### 第 9 天：真实纵向门禁

必须通过：

1. 文本推荐与多轮修改；
2. 单图识别、找相似和适配；
3. 两图与四图比较；
4. 知识咨询、轻问诊、确认和画像补空；
5. 场景导购、评论、避坑和反馈；
6. clean runtime、故障、并发和安全门禁。

### 第 10 天：最终审计

- 不新增能力；
- 修复所有确认 P0–P2；
- 全量测试和浏览器复跑；
- 核对 Canonical、排序内核和边界；
- 生成完整 handoff、能力矩阵和剩余生产部署清单。

## 7. 测试策略

每条能力遵循 RED → GREEN → review：

- 合同测试：严格类型、互斥字段、状态转换；
- 应用测试：正常、澄清、冲突、证据不足、CAS 冲突；
- HTTP 测试：流式与非流式一致；
- 前端测试：卡片数量、顺序、会话隔离、快照恢复；
- 浏览器测试：真实输入、真实 SSE、真实商品卡；
- 对抗测试：迟到响应、错误凭证、图文冲突、OCR 冲突；
- boundary：新 Guide 不 import `app.services`；
- 保护值：Canonical 和排序内核未经批准不变。

商品卡机械矩阵：

| 场景 | 卡片数 |
| --- | ---: |
| 单品咨询 | 1 |
| 推荐仅一个合格商品 | 1 |
| 推荐两个合格商品 | 2 |
| 推荐三个及以上合格商品 | 3 |
| 两图比较 | 2 |
| 三图比较 | 3 |
| 四图比较 | 4 |
| 知识问答 | 0 |
| 轻问诊信息收集 | 0 |
| 澄清或错误 | 0 |

## 8. 风险控制

- 第 1 天后冻结共享合同，避免并行工作重复修改 `chat.py` 和 `chat.html`；
- 每条线独立 worktree、独立小提交、每日集成；
- 不允许复用旧 V2 来缩短工期；
- OCR 模型或权重需要批准时，只暂停 OCR adapter，不暂停其他工作线；
- 评论缺乏可审计来源时 fail-closed，不生成假总结；
- 任何能力未通过真实浏览器门禁，不得标记完成；
- 第 10 天不接受新需求。

## 9. 第 1 天 Goal

下一轮 Goal 的唯一目标：

> 完成完整二期的共享地基冻结：修复五个 P1，建立后端权威商品卡展示合同，
> 清除前端补卡，固化 Guide/V2 owner matrix，定义并验证会话、画像、多图和
> SSE 公共合同，为三条并行能力线提供可独立开工的稳定接口。

该 Goal 不实现轻问诊、画像业务、多图比较或 OCR；这些能力在公共合同冻结后
进入并行 worktree。
