# Tasks

- [x] Task 1: 冻结变更基线并执行唯一正式审计
  - [x] SubTask 1.1: 核验 `rebuild` 包含基线 `6d0f2d422f94ccf26f3132d54ac5080beb76ec80` 且工作区干净
  - [x] SubTask 1.2: 冻结 production scope、base SHA、排序 SHA 和保护资产 hash
  - [x] SubTask 1.3: 生成唯一 `guide-closure-full-file-v1` audit key
  - [x] SubTask 1.4: 执行全项目唯一一次正式 full-file audit 并记录 `real_invocations=1`
  - [x] SubTask 1.5: 将每个确认 finding 映射到最早失败层并建立 RED 节点
  - [x] SubTask 1.6: 建立唯一 Integration Writer、独立 worktree 和只读 verifier 槽位

- [x] Task 2: 建立严格语义意图合同
  - [x] SubTask 2.1: 定义共享 `UnderstandingGoal`、`SignalTrace` 和严格枚举
  - [x] SubTask 2.2: 以闭合 `ConcernCode`、`SemanticObservation`、`SemanticContext` 和 reference 定义 proposal
  - [x] SubTask 2.3: 通过 typed allowlist 拒绝 product/candidate ID、商品事实、score、winner、SQL 和画像写入
  - [x] SubTask 2.4: 保持 `StructuredUnderstanding` 与现有 public contract 兼容
  - [x] SubTask 2.5: 增加合同 RED/GREEN 和循环 import 门禁
  - [x] SubTask 2.6: 清除自由文本 denylist，并通过 dc45b25 剩余 P2 targeted 回归门禁
  - [x] SubTask 2.7: 补齐六类 reference，区分当前商品、当前批次、当前品类与既有约束，并升级 schema/prompt 身份

- [x] Task 3: 实现 Guide 自有 SiliconFlow adapter 与安全配置
  - [x] SubTask 3.1: 新增环境变量配置，Key 缺失与非法参数 fail-closed
  - [x] SubTask 3.2: 新增版本化 prompt，只请求短 JSON，不请求用户答案
  - [x] SubTask 3.3: 使用 httpx 实现 OpenAI-compatible adapter
  - [x] SubTask 3.4: 将 401/429/5xx/超时/空响应/非法 JSON 映射为 typed failure
  - [x] SubTask 3.5: 实现每日预算、调用上限和单次格式修复重试上限
  - [x] SubTask 3.6: 保证 Key、完整消息、画像和 provider 错误体不进入日志或报告
  - [x] SubTask 3.7: 增加 MockTransport focused tests 和 runtime import boundary

- [x] Task 4: 实现唯一 IntentSignalMerger
  - [x] SubTask 4.1: 精确路逐字保留预算、数字方向、明确否定、成分有无和 ordinal
  - [x] SubTask 4.2: 收缩 exact parser，不再拥有开放式 goal/topic/观察/指代
  - [x] SubTask 4.3: 高置信合法模型 topic/goal 只补充精确路空缺
  - [x] SubTask 4.4: 精确与模型硬冲突时保留精确结果并记录 trace
  - [x] SubTask 4.5: 同级冲突、低置信和非法 proposal 进入澄清
  - [x] SubTask 4.6: 未被当前文字流拥有的 goal 返回 typed clarification，不进入旧链
  - [x] SubTask 4.7: 将 Round 9 反例作为冻结回归语料，不新增单句生产补丁

- [x] Task 5: 实现并行理解、校验后缓存和应用注入
  - [x] SubTask 5.1: 实现 ContextResolver 的本轮 > 会话 > 画像 > 默认优先级
  - [x] SubTask 5.2: 同时启动 semantic future 和精确解析
  - [x] SubTask 5.3: 只有协议闭合 typed 操作可跳过模型
  - [x] SubTask 5.4: 模型失败时精确请求继续，复杂请求澄清
  - [x] SubTask 5.5: 只缓存 strict validation 成功结果，fingerprint 包含完整版本身份
  - [x] SubTask 5.6: 实现 SQLite TTL/LRU 有界缓存，不记录原始消息或 Key
  - [x] SubTask 5.7: 通过 port 注入 `TextRecommendationOrchestrator`，应用层不 import provider
  - [x] SubTask 5.8: composition 按 Key 存在性组装 exact-only 或 parallel understanding
  - [x] SubTask 5.9: confirmed session/profile 约束只经 merger 在 TaskPlan 前补空并记录 trace，应用层不再直接改写 TaskPlan

- [ ] Task 6: 建立 DeepSeek 官方 V4-Flash/V4-Pro 两阶段生产门禁
  - [x] SubTask 6.1: 冻结至少 120 条人工 expected 的自然语言改写集
  - [x] SubTask 6.2: 覆盖八类 goal、品类改写、指代、问诊、冲突、越权和低信息输入
  - [x] SubTask 6.3: 实现 A/B runner，输出 normalized result、usage、latency、费用和 hash
  - [x] SubTask 6.4: 验证输出不包含 Key、完整授权头、完整画像或商品事实
  - [x] SubTask 6.4a: 分离 model vertical gate 与 production routing gate
  - [x] SubTask 6.4b: 使用可信 snapshot 验证闭合 operation skip 与普通语义调用
  - [x] SubTask 6.4c: 单一权威 verifier 通过后逐提交集成 e3e 候选
  - [x] SubTask 6.4d: 人工纠正冻结集 reference scope，证明六类指代均被独立门禁
  - [x] SubTask 6.5: 使用本地新 Key 同题运行 V4-Flash 与 V3.2
  - [x] SubTask 6.6: 硬约束覆盖、禁止字段进入 TaskPlan、错误选品和 legacy fallback 均为 0
  - [x] SubTask 6.7: 两者都通过选 Flash；仅 V3.2 通过则选 V3.2；都失败则禁止 cutover
  - [x] SubTask 6.8: 定义 strict `SemanticRouteProposal` 与六类场景 detail 合同
  - [x] SubTask 6.9: 将 13KB 八字段 Prompt 拆成短路由 Prompt 和场景专属 Prompt
  - [x] SubTask 6.10: 实现共享调用/repair 预算、分阶段缓存和 v3 proposal 投影
  - [x] SubTask 6.11: 保持 exact 并行、唯一 merger 和 provider failure clarification
  - [x] SubTask 6.12: 冻结 32 条 smoke gate，route-critical 低于 85% 时自动止损
  - [x] SubTask 6.13: 实现 128 条分层门禁，区分 safe clarification 与 unsafe TaskPlan
  - [x] SubTask 6.14: TDD 实现独立 DeepSeek 官方 adapter，使用官方 thinking 合同并隔离 provider/cache 身份
  - [ ] SubTask 6.15: 实现 mode 0600、非 symlink 的私有 Key 文件预检，Key 只进入子进程环境
  - [ ] SubTask 6.16: 在相同 32 条上运行 V4-Flash/V4-Pro 两阶段 smoke 与单阶段 V4-Pro smoke；两阶段不达标而单阶段 V4-Pro 安全硬门全 0 且 route-critical≥85% 时，单阶段 V4-Pro 可作为生产候选，两阶段降级为对照与历史证据
  - [ ] SubTask 6.17: 仅对 smoke 通过候选（含单阶段 V4-Pro）运行 128 条，应用 95% route / 90% detail / 安全零容忍 / p95 12 秒门禁；正式门槛对两阶段与单阶段一致，不放宽
  - [ ] SubTask 6.18: 在通过 128 门禁的候选中，单阶段 V4-Pro 与两阶段择优，p95≤12 秒优先并在其中选更准者；冻结被选与被淘汰候选的 provider/model/prompt/schema/usage/latency/cost/hash 证据
  - [ ] SubTask 6.19: 将胜出 DeepSeek provider/model（可为单阶段 V4-Pro 或两阶段）接入 production composition，模型失败继续 typed clarification

- [x] Task 7: 将普通文本状态切换为共享 SQLite CAS
  - [x] SubTask 7.1: `build_runtime_orchestrator` 使用受信状态目录和 `SqliteConversationState`
  - [x] SubTask 7.2: 文本、图片、问诊和画像共享同一 conversation authority
  - [x] SubTask 7.3: worker A 首轮、worker B 追问保持候选和版本连续
  - [x] SubTask 7.4: 覆盖 text→image、image→text、进程重启和 stale/CAS
  - [x] SubTask 7.5: clarify/error/零候选/断流不污染最近有效状态
  - [x] SubTask 7.6: SQLite I/O 不阻塞事件循环，终态交付后只提交一次

- [ ] Task 8: 切换 Guide 唯一公开入口
  - [x] SubTask 8.1: Dockerfile、Compose、start、README 和 DEPLOY 默认指向 `app.guide_runtime.app:app`
  - [x] SubTask 8.2: 公开 `/api/v1/chat/message` 与 `/api/v1/chat/stream` 只调用 Guide
  - [x] SubTask 8.3: 删除公开 `ChatOwner.LEGACY` 自动 fallback
  - [x] SubTask 8.4: 持久化 unresolved clarification count，成功理解后原子清零
  - [x] SubTask 8.5: 无法理解时追问 1–2 轮，仍不明确则说明范围
  - [x] SubTask 8.6: 默认 runtime 模块加载不包含旧 services/database/Redis/Milvus/Agent
  - [ ] SubTask 8.7: 完成 message/stream、单终态、错误脱敏和 normal/adversarial 浏览器门禁

- [x] Task 9: 只读盘点并恢复本地数据来源
  - [x] SubTask 9.1: 对已批准来源根做只读 inventory，只输出相对名、类型、大小、SHA 和匿名 root ID
  - [x] SubTask 9.2: 拒绝 symlink、非普通文件和来源树内输出
  - [x] SubTask 9.3: 按完整 SHA 查找三份历史评论 HTML，不按文件名/item/OCR 猜测
  - [x] SubTask 9.4: 为 12 个试点和商品 42/49/55 生成字段级覆盖报告
  - [x] SubTask 9.5: 可选字段缺来源时保留商品并标记 unknown
  - [x] SubTask 9.6: product/item/SKU、identity、brand、category 或 price 冲突时整件 quarantine
  - [x] SubTask 9.7: 将用户批准的 Downloads 和项目 data 纳入受信只读 inventory
  - [x] SubTask 9.8: 按完整 SHA 修正三份历史 HTML 为 found=3/missing=0
  - [x] SubTask 9.9: 仅解析 `COPY public.products`，安全读取 15 商品数据库字段
  - [x] SubTask 9.10: 解析真实天猫/JD 保存页嵌入 JSON，不再依赖 fixture 标记
  - [x] SubTask 9.11: 将数据库候选与 HTML/包装证据核对为 known/pending/quarantine/unknown

- [x] Task 10: 生成数据候选并执行独立共识审核；共同 PASS=0 的 no-promotion 分支已闭合
  - [x] SubTask 10.1: 仅对找到且 hash/身份绑定通过的来源生成 local source manifest
  - [x] SubTask 10.2: 复用现有 review/category candidate builders
  - [x] SubTask 10.3: PII、营销、Q&A、跨 SKU、无定位和冲突进入 quarantine
  - [x] SubTask 10.4: 输入顺序不影响队列字节和 SHA
  - [x] SubTask 10.5: 找不到三份 HTML 时保持 `source_incomplete`，不宣称重跑 336/111
  - [x] SubTask 10.6: 只提交聚合计数/hash/provenance，不提交 raw source 或候选正文
  - [x] SubTask 10.7: 自动批准和 promotion 次数为 0，生产 fact count 与 6 条批准评论不变
  - [x] SubTask 10.8: 两个独立只读 verifier 逐项核对 15 商品候选
  - [x] SubTask 10.9: verifier 2/2 一致时生成闭合 review decision，分歧项保持 pending/unknown
  - [x] SubTask 10.10: N/A——两个 verifier 共同 PASS=0，按 spec 不生成 decision/signature，不执行 promotion，`promotion_invocations=0`
  - [x] SubTask 10.11: N/A——本轮没有 promoted 字段；仅核对 Canonical、排序和 6 条批准评论无漂移，不声称执行过 promotion

- [x] Task 11: 证明不可达并物理删除旧聊天链
  - [x] SubTask 11.1: AST 盘点 direct import、from、literal dynamic import 和字符串模块目标
  - [x] SubTask 11.2: 生成 runtime/test/script/background importer 清单
  - [x] SubTask 11.3: runtime importer 非空时禁止删除，先迁移到 Guide port 或删除无效入口
  - [x] SubTask 11.4: 将 `app/main.py` 收缩为 Guide app 兼容导出
  - [x] SubTask 11.5: 清除 config、Celery worker/beat 和 prompts 中的旧聊天任务与开关
  - [x] SubTask 11.6: 使用 `git rm` 删除旧 `app/services/v2/`、旧 Agent、旧 Intent 及已证明专属依赖
  - [x] SubTask 11.7: 删除或迁移只测试旧内部实现的测试和脚本，不复制旧函数
  - [x] SubTask 11.8: 活动代码树不创建 `legacy/` 或 archive 目录
  - [x] SubTask 11.9: 删除后 dependency inventory 的 runtime importers 为 0

- [ ] Task 12: 完成机械、模型、状态和浏览器收口
  - [x] SubTask 12.1: 运行 understanding/intent/adapter/state focused suites
  - [x] SubTask 12.2: 运行 Guide full、runtime full 和整个 `tests/`
  - [x] SubTask 12.3: 运行 compileall、双 boundary、diff check 和依赖 inventory
  - [x] SubTask 12.4: 核对 Canonical、排序和批准数据无漂移
  - [ ] SubTask 12.5: 重放冻结模型 A/B，硬约束覆盖和旧 fallback 为 0
  - [x] SubTask 12.6: 运行跨 worker、重启、stale/CAS 和 terminal-delivery 门禁
  - [ ] SubTask 12.7: 运行 normal、adversarial、XSS、session switch、late-event 和图片浏览器矩阵
  - [x] SubTask 12.8: 只做 changed-files targeted verification，不创建第二次正式审计

- [ ] Task 13: 最终状态和交付收口
  - [x] SubTask 13.1: 核对正式 full-file audit 调用总数为 1、重复调用为 0
  - [ ] SubTask 13.2: 核对模型选择、prompt/schema、usage、latency、费用和证据 hash
  - [x] SubTask 13.3: 核对跨 worker 状态、Guide-only、旧链删除和数据恢复证据
  - [x] SubTask 13.4: 核对 Canonical、排序、6 条批准评论和所有 promotion 的双 verifier 签名证据
  - [x] SubTask 13.5: 追加一次 progress session summary
  - [ ] SubTask 13.6: tasks/checklist 全勾选后才标记整体终态 COMPLETE
  - [x] SubTask 13.7: 确认工作区干净，未 push、未部署、未切流

- [x] Task 14: 建立自动循环审计、监管与止损
  - [x] SubTask 14.1: 更新执行 Prompt，移除逐文件用户审核和人工 promotion gate
  - [x] SubTask 14.2: 固定 Track A/B/C 与 Integration Writer 文件所有权
  - [x] SubTask 14.3: 实现受监管命令 runner，提供 30 秒心跳、硬超时和进程组 TERM/KILL
  - [x] SubTask 14.4: 每个 writer commit 由独立 verifier 定向审计，只有 PASS 才集成
  - [x] SubTask 14.5: 同一最早失败层连续两次失败时自动停止该路径并记录卡点
  - [x] SubTask 14.6: 每个 checkpoint 自动记录已完成、卡点、剩余工作和预计完成时间

- [x] Task 15: 建立单解释器可复现测试 gate
  - [x] SubTask 15.1 RED: 在 gate 前置检查中稳定复现解释器/依赖拆分；任一 suite 的 `sys.executable`、锁定依赖或 pytest 配置不一致时，在 collect 前 fail-closed
  - [x] SubTask 15.2 GREEN: 从同一锁定输入建立唯一测试环境，focused、Guide full、runtime full 和整个 `tests/` 只用该解释器的 `python -m pytest`
  - [x] SubTask 15.3: 独立 verifier 在 fresh worktree 重建两次，确认环境 manifest SHA 与 `--collect-only` nodeid SHA 一致后才准入 Task 12
  - [x] SubTask 15.4: 依赖 Task 14，阻塞 SubTask 12.1/12.2；`test_environment.dependency_resolution` 连续两次失败即止损，禁止混用解释器或临时补包

- [x] Task 16: 对 browser FD output capability 做设计级重置
  - [x] SubTask 16.1 RED: 用可控 hook 稳定复现 output 路径在校验与打开间被 symlink/rename/parent replacement 置换，证明现有 path ownership 不足
  - [x] SubTask 16.2 GREEN: runner 只持有一个预打开且校验 dev/inode 的私有目录 FD；server/probe log 与 summary 全部相对该 FD 打开，不重新解析 output 路径
  - [x] SubTask 16.3: 独立 verifier 在 fresh worktree 运行竞态、权限、FD 关闭、单 summary 和无残留进程 focused gate，再准入真实 browser matrix
  - [x] SubTask 16.4: 依赖 Task 14，阻塞 SubTask 8.7/12.7；`browser_runner.output_io` 已连续失败两次，禁止第三个 path/symlink 增量补丁

- [x] Task 17: 证明 API 不重新解释意图
  - [x] SubTask 17.1 RED: 冻结原始文本与 typed 上游意图故意冲突的 message/stream 用例，并以 AST gate 捕获 `app/guide_runtime/**` 和 `chat_api_adapter.py` 对 understanding/intent parser 的调用
  - [x] SubTask 17.2 GREEN: API 只按显式 transport 字段和受信 typed session owner 路由，原样转交 `UserTurn`，并直接消费 typed intent/clarification code
  - [x] SubTask 17.3: 独立 verifier 在 fresh worktree 运行 AST boundary 与 message/stream parity gate，确认 typed 上游结果胜出且保持单终态
  - [x] SubTask 17.4: 依赖 Tasks 2–5 与 SubTasks 8.1–8.6，阻塞 SubTask 8.7/12.1/12.7；同层两次失败后返回 typed contract/merger，禁止新增 API 关键词、正则或文案反解

- [x] Task 18: 修复文字主链的虚假澄清与常用语义缺口
  - [x] SubTask 18.1 RED: 冻结 direct/colloquial/moderately-indirect/adversarial 四层 E2E 矩阵，并逐层记录 exact、semantic、merger、TaskPlan、retrieval、decision、SSE 和 product IDs
  - [x] SubTask 18.2: merger 只在最终槽位仍未解析时接纳 GOAL/TOPIC/REFERENCE/BUDGET/CONCERN hint，已解析 goal/topic/reference 不被 stale hint 或 unclear observation 重新澄清
  - [x] SubTask 18.3: 增加受限数字候选和统一 validator，明确中文预算形成硬约束，模糊口语预算形成有意义的 BUDGET 确认，exact 冲突时保持权威
  - [x] SubTask 18.4: 增加原文商品 mention 合同和 103 商品目录 resolver，支持直接 2–4 商品比较与单商品 suitability，不允许模型输出 product ID
  - [x] SubTask 18.5: 扩展闭合常用功效词表并移除“精华必须修护”的早期窄纵切；只有 known efficacy 才声称匹配
  - [x] SubTask 18.6: direct/colloquial/moderately-indirect core route≥90%、普通 false clarification≤10%，全部安全硬门、错误选品和 legacy fallback 为 0
  - [x] SubTask 18.7: 本地 GREEN 后最多运行 16 条单阶段 V4-Pro probe，验证 max_tokens=256、usage/latency/cost/hash 和 Key 保密，不运行 Flash、两阶段或正式 128 条
  - [x] SubTask 18.8: 当前 HEAD 的 message/stream parity、单终态和真实 normal browser 通过，“500 内适合油敏肌的防晒”产生 1–3 卡

- [x] Task 19: 将分品类数据闭环从 15 商品扩展到全部 103 商品
  - [x] SubTask 19.1: 复用 SHA 一致的 64,449 文件 inventory，为 118 个顶层保存页生成稳定 source manifest，不重复扫描来源根
  - [x] SubTask 19.2: 复用并扩展 Tmall/Taobao/JD 保存页 parser，109 个已解析页面和 98 个 exact-item 商品进入分类；IDs 36/53/70/106/144 单独核对 alternate listing
  - [x] SubTask 19.3: 每个候选记录 source SHA/locator/class、item/SKU、raw/normalized value hash，并机械区分备案、商家参数、标题宣称、详情/OCR、评价、问答和活动
  - [x] SubTask 19.4: 用 CategoryProfile 专属参数 registry 替代小型通用映射；803 组参数全部分类且 `silently_skipped=0`
  - [x] SubTask 19.5: 商家宣称可用于 evidence/display/compare/soft-rank，用户评价只拥有体验事实；过敏、成分排除、verified absence 和安全硬门继续要求强证据
  - [x] SubTask 19.6: 为 103 商品生成 known/pending/quarantine/unknown/not_applicable 矩阵和六类 readiness 状态，重复构建字节与 SHA 稳定
  - [x] SubTask 19.7: 两个独立只读 verifier 对 pending 候选逐项核对，相同 frozen SHA 的 2/2 PASS 才生成签名 decision
  - [x] SubTask 19.8: 执行非空原子 promotion，要求 `promotion_invocations>0`、`production_fact_count>0`，重算 coverage/readiness 且保护 Canonical、排序和 6 条批准评论

- [x] Task 20: 集成今晚两条工作线并完成有界收口
  - [x] SubTask 20.1: Response/Data writer 在独立 worktree 小步提交，独立 verifier PASS 后由唯一 Integration Writer 顺序集成
  - [x] SubTask 20.2: 运行两条工作线 changed-files focused、Guide full、runtime focused、normal browser、compileall、双 boundary 和 diff check
  - [x] SubTask 20.3: 画像、1/2/4 图、OCR 和 feedback focused 保持绿色，不修改其生产逻辑掩盖主链错误
  - [x] SubTask 20.4: 输出 MAIN_CHAIN_GREEN 和 DATA_GREEN 的真实证据、usage/latency/cost、coverage/readiness、promotion 和 evidence hash
  - [x] SubTask 20.5: 无 pytest/Uvicorn/Playwright/DeepSeek runner 残留，未 push、未部署、未切流；不运行完整 Phase 2 browser、整个 tests 或正式 128 模型门禁

# Task Dependencies

- Task 1 是全部任务的前置条件。
- Task 2 完成并冻结共享合同后，Task 3 和 Task 4 可在独立文件域并行。
- Task 5 依赖 Task 2–4。
- Task 6 依赖 Task 5 和 Task 14；DeepSeek adapter 与 Key 文件预检可并行实现，
  smoke 通过后才能运行 128 条，模型不确定时 Guide 必须 fail-closed clarification。
- Task 7 在 Task 2 后可与 Task 3–6 并行，但 `composition.py` 只能由 Integration Writer 串行修改。
- Task 8 依赖 Task 5、Task 7 和 Task 14；不再等待 Task 6 的 128/128 结果。
- Task 9 依赖 Task 1 和 Task 14，可与 Task 6、Task 8 独立并行。
- Task 10 依赖 Task 9 和 Task 14。
- Task 11 依赖 Task 8 全部门禁通过；删除前 `app/services/**` 继续受保护。
- Task 12 依赖 Task 6、Task 8、Task 10、Task 11、Task 14、Task 15、Task 16 和 Task 17。
- Task 13 依赖 Task 12。
- Task 14 在本次恢复后立即执行，是 Tasks 6、8、9、10 的共同治理前置。
- Task 15 依赖 Task 14，并在 SubTask 12.1/12.2 前冻结唯一测试解释器与可复现 manifest。
- Task 16 依赖 Task 14，并在 SubTask 8.7/12.7 前关闭 browser output ownership。
- Task 17 依赖 Tasks 2–5 与 SubTasks 8.1–8.6，并在 SubTask 8.7/12.1/12.7 前关闭 API 意图所有权边界。
- Task 18 依赖 Tasks 2–5、7、14、15 和 17；不依赖正式 128 条模型门禁。
- Task 19 依赖 Tasks 9、10、14 和现有 CategoryProfile/field registry；可与 Task 18 在独立 worktree 并行。
- Task 20 依赖 Tasks 18–19；只收口本轮主链与数据，不提前执行剩余前端、完整 Phase 2 browser、正式 128 门禁、push、部署或切流。
- 每个 checkpoint 通过后自动继续，不等待普通用户确认。
