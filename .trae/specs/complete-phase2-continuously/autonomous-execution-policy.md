# 二期自治执行、动态并发、审计与遥测政策

## 1. 文档地位

本文档定义完整二期在长时间、无人值守执行时的治理规则。它补充主规格、
任务清单、验收清单和连续执行计划，不替代任何产品合同或质量门禁。

本文档解决四个问题：

1. 在效率与错误风险之间动态调整并发，而不是固定使用同一个 agent 数量。
2. 明确哪些问题由执行系统自行解决，哪些问题必须升级给用户。
3. 防止“自己实现、自己证明正确”造成审计偏差。
4. 统一 Token 消耗和缓存命中的采集、计算与缺失数据表达。

除非用户明确修改本政策，施工期间不因普通实现问题反复请求用户拍板。

## 2. 不可变约束

下列约束不受并发模式影响：

- 主 integration worktree 同一时刻只能有一个 writer。
- 每个独立 worktree 同一时刻只能有一个 writer。
- `app/services`、`app/database`、`data/canonical` 和排序内核属于保护路径。
- 新 Guide 代码不得 import `app.services`。
- Canonical 数据、排序结果和后端权威卡片合同不得由前端、OCR 或模型覆盖。
- 内部错误不得静默回退旧 V2。
- 不 push、不部署、不切流量，除非用户另行明确授权。
- 单品/适配严格 1 卡，推荐 1–3 卡，比较 2–4 卡。
- 知识、问诊收集、澄清和错误严格 0 卡。
- 只有完整任务、真实纵向链、全量测试、浏览器矩阵和独立审查全部通过，
  才能声明完整二期完成。

## 3. 角色与职责

### 3.1 Root orchestrator

Root orchestrator 负责：

- 评估风险并选择并发模式。
- 分配 worktree、文件所有权和唯一写入者。
- 监控冲突、测试、浏览器、端口、状态目录和资源争用。
- 在小问题上自动决策。
- 在出现风险信号时立即降低并发。
- 在冻结 SHA 上安排独立审计。
- 汇总 checkpoint、证据、Token 遥测和未决风险。

Root orchestrator 可以持续做过程审计，但不能把自己的过程审计当作最终独立审查。

### 3.2 Integration owner

Integration owner 是主 integration worktree 的唯一 writer，负责：

- stable patch-id 和 blob manifest 去重。
- 串行集成已经冻结的绿色提交。
- 对共享文件做加法式冲突解决。
- 保留所有已存在的 authority 和安全合同。
- 在每个正式 checkpoint 更新 tasks、checklist、progress 和 ledgers。

Integration owner 不执行无边界的 full-file audit。

### 3.3 Domain writer

Domain writer 只能写自己被分配的 worktree 和文件域。其提交必须：

- 范围单一。
- 可独立测试。
- 不包含其他线路的状态文档。
- 不通过整文件覆盖解决共享文件冲突。
- 提供来源提交、stable patch-id、production blob manifest 和测试证据。

### 3.4 Independent auditor

Independent auditor 默认只读，审查冻结的 commit SHA。其职责是：

- 检查合同、边界、故障语义、安全性和遗漏测试。
- 按严重程度输出 findings。
- 对同一个 audit key 只做一次真实审计。
- 不修改被审计 worktree。

若审计发现问题，修复由单独 writer 完成，之后审计新的 audit key。

### 3.5 Verifier

Verifier 负责只读门禁，可以按 focused、full、runtime、boundary、normal browser
和 adversarial browser 分片。Verifier 不在测试失败时直接修改代码，而是提交最小复现、
日志、证据路径和失败分类。

## 4. 自适应并发状态机

### 4.1 硬上限

- 活跃 agent 总数：2–8。
- 并发代码 writer：0–4。
- Integration writer：固定最多 1。
- 同一文件域 writer：固定最多 1。
- Independent auditor：至少 1 个冻结 SHA 审计槽位。

增加 read-only verifier 的风险通常低于增加 writer。需要提速时，优先增加验证分片，
而不是增加共享文件 writer。

### 4.2 模式

| 模式 | 总 agent | writer | 适用情况 |
|---|---:|---:|---|
| `PAUSED` | 0 | 0 | 用户暂停、等待重大决策或外部状态 |
| `INCIDENT` | 2–3 | 1 | 保护合同异常、数据风险、重复回归 |
| `HIGH_RISK` | 3–5 | 1–2 | integration、共享 API/SSE/runtime/frontend 冲突 |
| `NORMAL` | 5–7 | 2–4 | 文件域独立、测试稳定、证据完整 |
| `LOW_RISK_PARALLEL` | 6–8 | 1–3 | 只读审计、测试、浏览器和文档核验为主 |

并发数量不是进度指标。关键路径没有缩短时，不得为了“满并发”创建无所有权的任务。

### 4.3 升并发条件

同时满足以下条件时，才允许增加一个 agent：

1. 最近两个正式 checkpoint 为绿色。
2. 新任务与现有 writer 的 production 文件集合无交集。
3. 没有未解决的 merge conflict、cherry-pick 状态或脏 integration worktree。
4. 最近的测试失败均已分类且没有未解释的 flaky。
5. 浏览器端口和状态目录可独立分配。
6. 新 agent 有明确交付物、停止条件和唯一 owner。

每次最多增加一个 agent。增加后至少观察一个 checkpoint，避免并发抖动。

### 4.4 降并发条件

出现任意一项时立即降低并发，不等待当前批次全部结束：

- 两个 writer 修改同一 production 文件或同一个 authority。
- integration 出现需要语义判断的冲突。
- stable patch-id 或 blob manifest 显示重复集成风险。
- focused、full、boundary 或 browser 出现无法立即解释的回归。
- 同一测试在隔离环境中重复失败。
- 端口、SQLite 状态目录、截图或浏览器上下文发生串扰。
- 独立审计提出高严重度 finding。
- 测试进程争用导致总墙钟时间增加，而不是下降。
- agent 丢失上下文、静默结束或无法提供提交与证据映射。

降并发时优先停止受影响线路，独立且绿色的线路可以继续。

### 4.5 进入 INCIDENT 的条件

下列情况进入 `INCIDENT`：

- 保护路径发生非授权变更。
- Canonical ID、排序 SHA 或卡片权威发生漂移。
- OCR、前端或模型覆盖 Canonical 事实。
- 内部错误回退到旧 V2。
- 跨会话状态泄漏、反馈对象越权或幂等性破坏。
- 数据损坏、凭证泄露或不可逆操作风险。
- 同一阻塞在隔离后连续出现三次。

`INCIDENT` 默认配置为一个 fixer、一个 verifier，必要时增加一个独立 auditor。

## 5. 无人值守自治边界

### 5.1 自动处理的小问题

以下问题由执行系统自行解决，不请求用户：

- 确定性的 import、类型、格式、lint 和测试 fixture 问题。
- 独占测试端口冲突和临时状态目录污染。
- 已证明等价的重复 patch，按 stable patch-id 跳过。
- 只包含旧 checkpoint 的重复 docs commit。
- CSV、owner matrix、任务文档中的加法式非语义冲突。
- 浏览器截图目录、临时 SQLite 和进程清理。
- 可由现有合同唯一确定的 SSE 事件顺序或序列化修复。
- 可由 RED 测试明确证明的局部回归。
- OCR 不可用时按既有合同返回 `unavailable`，而不是扩大信任边界。
- 一个 agent 静默结束后，在冻结的干净 checkpoint 上续派替代 agent。

自动修复必须留下最小测试、提交和 progress 证据。

### 5.2 自动处理但必须降并发的问题

以下问题无需立即请求用户，但必须降低到 `HIGH_RISK` 或 `INCIDENT`：

- 共享 API、SSE、runtime composition 或 frontend 的语义冲突。
- 跨模块合同不一致。
- 同一能力的两个实现都看似有效但 authority 不清晰。
- 一次独立审计高严重度 finding。
- 隔离环境中可复现的 flaky 或时序回归。
- 全量测试与 focused 测试结论不一致。

处理流程固定为：冻结现场、最小复现、写 RED、单 writer 修复、独立验证。

### 5.3 必须升级给用户的问题

只有以下问题需要等待用户决策：

- 产品语义存在多个合理答案，现有规格无法唯一决定。
- 需要改变用户可见行为、验收标准或范围。
- 需要修改保护路径、Canonical 数据或排序规则。
- 需要 destructive migration、删除用户数据或不可逆操作。
- 需要 push、部署、切流量、购买服务或使用新的外部凭证。
- 涉及隐私、合规、法律或安全政策选择。
- 同一硬阻塞在隔离和替代方案后连续出现三次。
- 所有剩余任务共享同一个外部决策阻塞。

升级请求必须包含：问题、证据、已尝试方案、推荐选项、替代选项和不决策的影响。

用户不在线时，受阻线路暂停，其他独立线路继续。

## 6. 共享文件与集成冲突政策

当前高冲突文件域包括但不限于：

- `app/api/v1/chat.py`
- `app/guide/application/chat_api_adapter.py`
- `app/guide/application/image_recommendation_flow.py`
- `app/guide/presentation/sse_events.py`
- `app/guide_runtime/app.py`
- `app/guide_runtime/composition.py`
- `app/guide_runtime/sse.py`
- `app/static/chat.html`
- owner matrix、tasks、checklist、progress 和 ledgers

处理规则：

1. Domain writer 优先新增领域模块和测试，最小化共享接线。
2. 共享接线提交必须独立，便于 integration owner 人工合并。
3. 冲突解决必须保留两侧 authority，不得使用整文件 `ours` 或 `theirs`。
4. tasks/checklist/progress 的历史 checkpoint 不从 domain branch 重放。
5. 状态文档只由 integration owner 在正式 checkpoint 统一更新。
6. 冲突解决后必须重跑受影响的 focused、正式 HTTP、runtime 和 frontend 测试。

## 7. 去重与证据政策

### 7.1 代码去重

每个候选提交必须检查：

- source commit SHA
- stable patch-id
- production blob manifest
- integration base SHA
- 受影响文件集合

commit SHA 不同不代表实现不同。stable patch-id 已存在时默认跳过；若 patch-id 因加法式
冲突解决而变化，必须比较 production blob 和行为测试。

### 7.2 审计去重

审计键必须至少包含：

- audit profile
- 冻结 base/integration SHA
- 排序后的 production scope
- scope manifest

相同 audit key 只能有一次真实审计调用。后续引用写 `REUSED_PASS` 或
`REUSED_FINDINGS`，不得重复消耗审计资源。

### 7.3 证据最低要求

每个能力 checkpoint 至少记录：

- 来源提交与集成提交映射
- stable patch-id 或等价说明
- production blob manifest
- focused 和 full 测试数字
- boundary、compile 和 diff check
- 浏览器 normal/adversarial 结果
- 截图或结构化浏览器证据路径
- 保护路径和排序 SHA
- 服务端口与临时状态清理结果
- audit key、真实 invocation 数和复用状态
- Token 遥测状态

## 8. 测试与浏览器调度

### 8.1 测试分片

推荐分片：

- Domain focused
- Formal HTTP/API
- Runtime
- Frontend static/contract
- Guide full
- 双 boundary
- compileall 和 diff check

测试分片可以并行，但必须使用同一个冻结 SHA。主 integration worktree 在验证期间不得继续
变化；需要继续集成时，应从冻结 SHA 创建验证 worktree。

### 8.2 浏览器分片

推荐分片：

- Normal browser
- Adversarial browser
- Consultation/profile vertical
- Single/two/four-image vertical
- Feedback vertical

每个浏览器分片必须使用独立端口、状态目录和截图路径。测试结束必须清理 uvicorn、
浏览器上下文和临时 SQLite。

### 8.3 失败分类

失败分为：

- `PRODUCT_REGRESSION`
- `CONTRACT_REGRESSION`
- `TEST_DEFECT`
- `ENVIRONMENT`
- `RESOURCE_CONTENTION`
- `FLAKY_UNEXPLAINED`
- `TELEMETRY_FAILURE`

未知失败不得通过无条件重跑变绿。第一次重跑只用于确认可复现性，第二次仍不稳定时必须
降并发并隔离根因。

## 9. 当前项目已知卡点

### 9.1 共享接线冲突

问诊、图片和反馈都会触碰 chat API、SSE、runtime 和 frontend。风险是某条线通过整文件
选择覆盖其他 authority。

处置：单 integration writer、接线独立提交、加法式合并、共享层 focused 回归。

### 9.2 重复 patch 与历史分支漂移

多个来源分支可能包含等价实现但 SHA 不同。

处置：stable patch-id 优先，production blob 和行为测试补充；禁止仅按 SHA 判断。

### 9.3 状态文档重复与冲突

Domain branch 中的旧 tasks/checklist/progress 会覆盖较新的 checkpoint。

处置：domain docs commit 默认不移植；integration owner 在当前 HEAD 统一写一次。

### 9.4 SSE 顺序、迟到响应和重复终态

异步事件可能产生顺序漂移、重复终态、迟到响应覆盖当前页面或异常卡片泄漏。

处置：typed event、单终态、request/session 相关性、迟到响应 `ignored=true`、正式 HTTP
和真实浏览器共同验证。

### 9.5 画像时序与 CAS

暂定结论、确认画像、本轮输入和历史画像可能互相污染或发生并发覆盖。

处置：未确认不持久化、owner/source/time/version 完整、CAS 更新、本轮输入优先、
临时信息不污染持久画像。

### 9.6 OCR 信任边界

OCR 可能误识别标签，或被错误当作 Canonical 商品事实。

处置：OCR 只作为 observation；解析失败为 `unavailable`；不得改 Canonical ID、排序、
winner 或卡片数量。

### 9.7 反馈对象权威与会话隔离

前端可能提交伪造 card/product，跨会话引用或重复反馈。

处置：只接受已交付 trusted target；跨会话 404；idempotency key 重放相同 event ID；
迟到响应忽略。

### 9.8 SQLite、端口与浏览器资源串扰

并发测试可能共享默认状态目录、端口或遗留 uvicorn。

处置：每个 verifier 分配独立临时目录和端口；结束执行监听检查和进程清理。

### 9.9 全量测试资源争用

多个 full suite 同时运行可能使总耗时增加并制造时序噪声。

处置：同机最多一个 Guide full；runtime/boundary 可与其并行；浏览器根据 CPU/IO 实测
决定是否并发。若墙钟时间连续恶化，减少 verifier。

### 9.10 Agent 静默结束或上下文丢失

长任务可能在中间 checkpoint 结束但未返回完整结果。

处置：以 git SHA 和干净工作区为事实来源；从最后冻结 SHA 续派，不重做已证明提交。

### 9.11 工具宿主或命令通道不可用

命令通道可能返回 connection refused，导致无法读取工作区、日志或本机遥测。

处置：

1. 不把“无法读取”解释为“没有问题”。
2. 停止写业务代码，保留当前冻结 SHA。
3. 使用仍可用的只读控制面确认 agent/goal 状态。
4. 恢复后先检查 git status、进程、端口和未完成 cherry-pick。
5. 在恢复验证前不声明 checkpoint 完成。

### 9.12 Token 与缓存遥测缺失

当前 goal 控制面可能返回 `tokens_used=0`、`time_used_seconds=0`，但没有任何原始 usage
字段。这是采集缺失，不能解释为真实消耗为零。

处置见第 10 节。

## 10. Token 与缓存遥测合同

### 10.1 必须采集的原始字段

每个 root turn 和 subagent run 至少需要：

- `run_id`
- `parent_run_id`
- `started_at`
- `finished_at`
- `input_tokens_total`
- `cached_input_tokens`
- `output_tokens`
- `usage_source`
- `usage_status`

模型名称和价格不是本项目计算 Token 与缓存命中的必需字段。

### 10.2 计算口径

若 provider 的 `input_tokens_total` 已包含缓存命中：

```text
uncached_input_tokens = input_tokens_total - cached_input_tokens
consumed_tokens = input_tokens_total + output_tokens
cache_hit_rate = cached_input_tokens / input_tokens_total
```

若 provider 分别返回 uncached 与 cached input：

```text
input_tokens_total = uncached_input_tokens + cached_input_tokens
consumed_tokens = input_tokens_total + output_tokens
cache_hit_rate = cached_input_tokens / input_tokens_total
```

当 `input_tokens_total = 0` 且 provider 明确报告了真实零调用时，命中率记为 `N/A`，
不得除零。

### 10.3 聚合口径

项目累计值必须覆盖 root 与所有 descendants：

```text
project_consumed_tokens = sum(run.consumed_tokens)
project_cached_input_tokens = sum(run.cached_input_tokens)
project_input_tokens = sum(run.input_tokens_total)
project_cache_hit_rate = project_cached_input_tokens / project_input_tokens
```

不能把 agent 数、turn 数、工具调用数或上下文文件大小换算成准确 Token。

### 10.4 缺失数据规则

满足任一条件时，状态必须为 `UNAVAILABLE`：

- usage envelope 没有 token 字段。
- 只返回默认 `0`，但没有 `measurement_complete=true`。
- root 有数据但 descendants 缺失。
- 缓存字段未暴露。
- 本机日志无法证明计数覆盖完整执行。

缺失时：

- 不填伪造估算值。
- 不把 0 当作真实值。
- ledger 写明缺失字段、来源和最后检查时间。
- checkpoint 可以继续，但最终成本报告保持不完整。

### 10.5 当前已知状态

当前可用 goal 遥测报告：

```text
tokens_used = 0
time_used_seconds = 0
status = paused
```

当前控制面没有返回：

- input tokens
- cached input tokens
- output tokens
- descendants usage
- cache hit rate
- measurement completeness

因此当前项目截至本 checkpoint 的准确 Token 消耗和缓存命中率均为：

```text
UNAVAILABLE
```

这不是计算方法问题，而是原始测量数据没有被控制面采集或暴露。没有原始缓存计数时，
无法从对话文本或工具调用数重建真实缓存命中。

### 10.6 后续补采要求

恢复执行前，若运行平台提供 usage envelope，应在每个 subagent 完成事件和 root checkpoint：

1. 读取原始 usage。
2. 按 `run_id` 去重。
3. 写入不可变 ledger。
4. 计算累计 consumed tokens 和 cache hit rate。
5. 对缺失 descendants 标记 `PARTIAL_TELEMETRY`。

若平台仍不暴露字段，继续明确报告 `UNAVAILABLE`，不得承诺具体数字。

### 10.7 遥测校准记录与 Trae CN 本地采集方法

本项目已经执行一次控制面校准：

1. 试运行前读取 `get_goal`，返回 `tokens_used=0`、`time_used_seconds=0`。
2. 执行多次 WebSearch、WebFetch、文档分析和独立调查任务。
3. 试运行后再次读取 `get_goal`，结果仍为相同的 `0/0`。
4. 返回结构没有缓存、输入、输出、descendants 或采集完整性字段。

结论：`get_goal` 的当前 Token 字段是未接入的默认值，不能再用于本项目 Token 统计。

公开实现核对还确认：

- 国际版 Trae 的账号级 usage API 不支持 Trae CN。
- Trae CN 的本地 `chat_turn` usage 可以包含 prompt、completion、cache-read 和
  cache-creation 字段。
- macOS Trae CN 的会话数据库位于
  `~/Library/Application Support/Trae CN/ModularData/ai-agent/database.db`，
  但该数据库使用 SQLCipher，不应为了普通统计扫描进程内存或提取密钥。
- `@aiusage/cli` 提供 Trae CN 本地模式，通过 Trae 官方 `ai-agent` RPC 读取历史，
  不直接打开 SQLCipher。

批准的安全采集命令为：

```bash
npx --yes @aiusage/cli@1.7.10 trae sync \
  --edition cn \
  --port 9230 \
  --no-launch
npx --yes @aiusage/cli@1.7.10 report \
  --tool trae-cn \
  --range all \
  --detail \
  --json
```

执行限制：

- 只能使用 `aiusage trae sync` 和本地 `report`。
- 禁止执行会上传到 Worker 的普通 `aiusage sync`。
- 禁止配置 Worker、schedule、enroll 或第三方 dashboard。
- 禁止打印凭证、会话正文或 SQLCipher 密钥。
- 禁止扫描 Trae 进程内存。
- 开工前在安全维护窗口将 Trae CN 以 `--remote-debugging-port=9230` 启动。
- 执行期间只使用 `--port 9230 --no-launch` 连接当前实例。
- 禁止在共享用户数据目录上启动第二个 Trae 实例。
- 若 Trae 正在运行但没有调试端口，不强杀用户主 IDE；等待安全维护窗口重启。

Trae CN RPC 记录预期提供：

```text
input_token
output_token
cache_read_token
cache_write_token
session_id
usage_time
```

在第一次真实采样时，必须先用原始记录中的 total 字段或工具自带聚合结果确认
`input_token` 是否已经包含缓存 Token，再选择第 10.2 节对应公式。不得在字段语义未核对时
重复加总缓存 Token。

本次校准尚未产生具体数字，直接阻断点是本机命令执行宿主在启动任何命令前持续返回
`connection refused`。root 与独立调查任务均可复现，甚至 `date` 也无法启动，因此失败点
早于 npm、Trae RPC 或数据解析。命令宿主恢复后，以上两条本地命令是第一优先验证路径。

## 11. 长时间运行政策

在用户可能数小时不在线时：

- 小问题自动解决并记录。
- 中等问题自动降并发、隔离、写 RED、修复和复验。
- 一条线阻塞时继续其他独立线路。
- 不因等待用户而停止全部项目，除非所有剩余任务共享同一个硬阻塞。
- 不反复发送相同问题。
- 同一硬阻塞连续出现三次后才标记 blocked。
- 每个能力完成后形成冻结 SHA 和正式 checkpoint。
- 未达到完整二期标准时不得声明总体完成。

## 12. 当前阶段建议

当前项目处于多条纵向能力向主 integration 收口的高冲突阶段。恢复时默认进入
`HIGH_RISK`，建议 5–6 个 agent：

1. 一个 integration writer。
2. 一个独立 auditor。
3. 一个 focused/Guide verifier。
4. 一个 runtime/boundary verifier。
5. 一个 normal browser verifier。
6. 一个 adversarial browser verifier。

连续两个绿色 integration checkpoint 后，可以升到 6–8 个 agent；新增槽位优先用于
只读验证或下一个完全独立的 domain worktree，不增加 integration writer。

## 13. 完成标准

本政策执行有效的标准是：

- 用户不需要为普通实现问题持续在线。
- 并发会根据可观察风险自动升降。
- 每个 production 文件域有唯一 writer。
- 所有审计针对冻结 SHA 且可按 audit key 去重。
- 小问题有证据地自动解决。
- 重大问题只在规定条件下升级。
- Token 与缓存数据有原始来源；缺失时明确为 `UNAVAILABLE`。
- 不再把默认 0、工具调用数或估算值冒充准确 Token 统计。
