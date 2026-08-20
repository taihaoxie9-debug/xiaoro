# Slice 1 全局地基审计

状态：完成
日期：2026-08-07
审计区间：`73b3481a03630a61e8ad577d13fc713c1e7ee013..0bd6925`
审计范围：`app/guide`、`app/guide_runtime`、`app/api/v1/chat.py`、
`app/static/chat.html`、`tools/guide_gates`、`pytest-guide.ini`

## 1. 结论

当前工程不是“地板推倒重来”的状态。

已经可靠成立的部分是：

- 103 个 Canonical 商品及 manifest/SHA；
- 103 张商品图及当前仓库内的实际文件完整性；
- 六层包结构、强类型合同和确定性排序内核；
- 防晒、修护精华、最近候选追问和预算修改四条独立 runtime 链；
- 预算、功效和排除项的 fail-closed 基线；
- 进程内 CAS、TTL 和容量控制；
- 独立 FastAPI runtime、真实商品卡和浏览器基线。

尚不能称为“文本 Slice 正式收口”的部分是：

- 正式聊天 API 只接通首轮，已实现的多轮能力仍只在独立 runtime 可靠；
- 前端会展示没有事实来源的精确契合百分比；
- 前端会吞掉公开 SSE 错误；
- 会话切换和流式状态提交存在竞态；
- 泛化肤质事实在多类肤质下被误判为明确不匹配；
- 架构边界检查器没有覆盖真实编排器；
- 图片资产运行时完整性弱于测试门禁。

因此后续不能直接跳到图片，也不应继续在未收口入口上增加条件追问。
下一阶段应先完成 Slice 1.6 文本主链收口。

## 2. 审计方法

### 2.1 代码范围

- Git 变更文件：117
- 排除测试、生成物和媒体后全文件审查：59
- 变更规模：`+23554 / -20`
- 六个审查组：
  - 架构合同与边界；
  - 理解、意图与会话状态；
  - Canonical 适配与召回；
  - 决策内核与事实语义；
  - 展示与应用编排；
  - API、runtime、前端与发布门禁。

### 2.2 基线命令

基线结果：

- Guide 全量测试：`368 passed`
- Runtime 专项：`20 passed`
- `app/guide` boundary：通过
- `app/guide_runtime` boundary：通过
- `compileall`：通过
- CSV backend gate：通过
- Playwright 正常链路：通过
- 排序内核 SHA：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`

这些结果证明锁定的 happy path 可运行，但不能覆盖下文的跨入口、断流和
浏览器竞态问题。

### 2.3 对抗探针

实际执行了以下额外探针：

1. 在真实编排器文件名下放入评分函数，boundary 返回 0 条违规。
2. 使用变量调用 `import_module` 导入旧服务，boundary 返回 0 条违规。
3. 消费 SSE 到 `decision_process` 后关闭生成器，服务端快照已经升版，
   但客户端尚未收到 `products`。
4. 把图片 manifest 自摘要改成全 0，运行时加载器仍接受 103 条资产。
5. 向浏览器发送 `GUIDE_INTERNAL_ERROR`，页面没有显示任何失败文案。
6. 流式回答期间切换会话，旧会话回答出现在新会话页面。
7. 真实修护精华卡片显示 `62% 契合`，但后端只有 `skin_match=unknown`。
8. 运行四类真实查询：
   - `500元内干性修护精华`
   - `500元内油性修护精华`
   - `500元内混合肌修护精华`
   - `500元内中性肌修护精华`

   四类均返回 `NO_CANDIDATE`，根因是“多种肤质适用”被当成明确 mismatch。

## 3. 缺陷清单

### P1-1 正式聊天 API 只能工作一轮

位置：

- `app/api/v1/chat.py:234-243`
- `app/guide/application/chat_api_adapter.py:21-29`

事实：

- 前端发送 `conversation_version`；
- `ChatRequest` 没有该字段，并设置 `extra="ignore"`；
- 正式 API 构造 `UserTurn` 时固定写入 `conversation_version=0`；
- 路由仅在当前消息含“防晒”或“精华”时进入新链。

结果：

- `第二款呢`
- `哪个更便宜`
- `预算降到100元呢`

都会掉回旧 Agent。再次发送完整品类虽然进入新链，但固定 version 0 会被最近
快照判为 stale。

### P1-2 泛化肤质被误判为明确不匹配

位置：`app/guide/decision/recommendation.py:397-417`

当前逻辑只有敏感肌把“多种肤质/全肤质/通用”映射为 unknown。油皮、干皮、
混合皮、中性肌和油敏肌只要没有命中目标字面 marker 就返回 mismatch。

这违反：

- soft unknown neutral；
- A2 的 known match / unknown / explicit mismatch 三态；
- “unknown 不猜”的项目约束。

### P1-3 前端展示伪精确契合度

位置：

- `app/guide/application/chat_api_adapter.py:147-178`
- `app/static/chat.html:5127-5129`

适配器把离散证据状态硬编码为：

- matched：`0.9`
- unknown：`0.62`
- not applicable：`0.72`

前端再显示成 `90%/62%/72% 契合`。这些数字没有评分合同、权重、证据或
决策含义，属于展示层补造事实。

### P1-4 浏览器吞掉 SSE error

位置：`app/static/chat.html:5020-5069`

`handleSseEvent` 在 error 分支抛异常，但外层用于捕获 JSON 解析错误的
`try/catch` 同时吞掉该业务异常，只输出 `SSE parse failed`。

用户看不到：

- 服务端脱敏错误文案；
- 通用失败提示；
- 可重试状态。

### P1-5 会话切换会串入旧响应

位置：`app/static/chat.html:4608-4883`

请求捕获了发起时的 session ID，但 DOM 渲染和最终快照保存使用全局
`chatMessages` 与当前会话。没有：

- request ID；
- AbortController；
- 当前会话归属校验；
- 重复发送锁。

真实延迟流探针已复现旧会话回答出现在新会话页面。

### P1-6 快照在页面收到商品前升版

位置：`app/guide/application/text_recommendation_flow.py:279-291`

服务端在首次 `yield decision_process/products/message` 之前执行 CAS save。
客户端中途断开时：

- 服务端认为新商品已展示；
- 浏览器仍保存旧 conversation version；
- 下一轮请求被判 stale。

这与“快照只代表页面最近实际展示候选”的合同不一致。

### P1-7 边界门禁检查了错误的编排器文件

位置：`app/guide/check_boundaries.py:392-394`

检查器只把 `application/orchestrator.py` 识别为编排器，但该文件只是 Protocol；
真实实现是 `application/text_recommendation_flow.py`。

当前 `ORCHESTRATOR_SCORING_LOGIC` 和 `ORCHESTRATOR_SEMANTIC_LEXICON`
规则不会约束真实实现。动态 import 也只拦截字面量目标。

### P2-1 图片运行时完整性弱于测试完整性

位置：`app/guide/adapters/catalog/seed_product_assets.py:61-150`

现状：

- 测试会核对 103 张实际图片、字节数和 SHA；
- runtime loader 只核对 JSONL SHA 和条数；
- 不核对 manifest 自摘要；
- 不核对实际图片路径、字节数、媒体类型和文件 SHA。

因此漏文件或篡改 manifest 的部署可健康启动，直到浏览器请求图片时才失败。

### P2-2 决策 trace 没有记录肤质约束

位置：`app/guide/decision/recommendation.py:281-298`

`evidence_refs` 记录品类、预算、排除项和功效，但没有记录 skin。结果本身仍受
skin 约束影响，但审计 trace 无法独立证明本轮用了哪个肤质。

### P2-3 应用模块仍承担具体 adapter 组装

位置：`app/guide/application/text_recommendation_flow.py:12-17,496-511`

业务编排文件直接 import 并构造 Canonical 和内存状态 adapter。当前未造成
功能错误，但会让 application 的边界检查与 clean composition root 继续混杂。
后续应把具体组装收回 `app/guide_runtime/composition.py`。

## 4. 数据能力缺口

### 4.1 肤质

- 防晒 12 个商品的 `suitable_skin` 当前全部 unknown。
- 修护精华的可用候选主要是“多种肤质适用”或字段 unknown。
- 当前数据足以验证“不强选 winner”，不足以证明多种具体肤质的差异化推荐。

### 4.2 成分排除

受支持的防晒和精华中：

- 部分 `ingredients_present` 为 known；
- `verified_absences` 没有一条 known。

因此当前只能可靠证明“明确含有时排除”和“缺 absence 证据时 fail-closed”，
不能诚实返回“不含某成分”的成功推荐。

### 4.3 图片

已有：

- 103 张真实商品图；
- 图片 manifest；
- `ImageBundle/ImageObservation` 合同骨架。

未有：

- 新主链安全上传；
- 运行时图片 bundle 状态；
- 103/103 新向量索引；
- 锁定模型与权重 SHA；
- OCR/视觉结果到 Canonical 的可信绑定；
- 单图浏览器闭环。

## 5. 当前能力地图

| 能力 | 独立 runtime | 正式 API | 真实浏览器 | 结论 |
|---|---:|---:|---:|---|
| 防晒首轮 | 是 | 是 | 是 | 可用 |
| 修护精华首轮 | 是 | 是 | 是 | 可用 |
| 第二款/最低价 | 是 | 否 | 仅独立 runtime | 未正式收口 |
| 预算修改 | 是 | 否 | 仅独立 runtime | 未正式收口 |
| 修改肤质 | 否 | 否 | 否 | 待 Slice 1.7 |
| verified-absence 排除 | 无事实 | 无事实 | 否 | 待数据审核 |
| 单图识别/找相似 | 否 | 否 | 否 | 待 Slice 1.9/2.0 |

## 6. 发布判断

当前结论：

- Slice 1.5 的锁定验收仍然成立；
- 不能把它外推为“正式文本导购已经完整收口”；
- 不应开始 2.0 图片施工；
- 先完成 1.6，清零上述 P1，并让正式页面与干净 runtime 使用同一合同。

## 7. 审计制品

本次临时制品目录：

`/tmp/xiaoro-fresh_global_audit_20260807`

其中包括：

- `review_files.md`
- `review_groups.md`
- `group/group_1.jsonl` 至 `group/group_6.jsonl`
- `comments.jsonl`
- `final_comments.json`
- `report.html`
- `report.md`
- `browser_baseline.png`
- `browser_adversarial.json`
- `browser_scores.json`
- `slice1_backend_gate.csv`

正式后续路线见：

`docs/superpowers/specs/2026-08-07-slice1.6-to-2.0-growth-design.md`
