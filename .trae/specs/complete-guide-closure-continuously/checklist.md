# Checklist

## 基线与执行纪律

- [x] `rebuild` 包含起始基线 `6d0f2d422f94ccf26f3132d54ac5080beb76ec80`
- [x] 开始实施时工作区干净且未覆盖用户变更
- [x] Phase 2 十项能力和 Phase 3A 六画像不被重复实现
- [x] 唯一 Integration Writer 写共享合同、composition 和公开入口
- [x] 同一文件域同时最多一个 writer
- [x] verifier 在冻结 SHA 的独立 worktree 只读运行
- [x] 动态 Agent 数保持在 2–8
- [x] Incident 时降为 1 fixer + 1 verifier
- [x] 普通 checkpoint 不等待用户

## 唯一正式审计

- [x] base SHA、production scope、profile 和 blob manifest 已冻结
- [x] 唯一 audit key 已记录
- [x] 正式 full-file audit 真实调用总数严格为 1
- [x] 每个确认 finding 均映射到最早失败合同并有 RED
- [x] finding 修复由非审计 writer 完成
- [x] finding 只通过 targeted verification 和正常门禁清除
- [x] capability 阶段没有创建新正式 audit key
- [x] 最终收口没有第二次正式 full-file audit
- [x] repeat formal audit invocation 为 0

## 三路意图合同

- [x] `UnderstandingGoal` 是有限稳定枚举
- [x] `SemanticIntentProposal` strict validation 且 extra-forbid
- [x] Semantic proposal schema 有明确版本
- [x] concerns 只接受覆盖六品类语义维度的闭合 `ConcernCode`
- [x] observations 只接受闭合 code、bool 和有限 qualifier
- [x] clarification hint 只接受闭合 code
- [x] references 完整区分 `current_item`、`current_batch`、`candidate_ordinal`、`image_ordinal`、`current_topic` 和 `previous_constraint`
- [x] semantic contracts 不包含自由文本 denylist
- [x] `SemanticContext` 只包含最小化 typed 会话摘要
- [x] `SemanticContext.confirmed_profile_fields` 只暴露闭合字段名且不携带任意 value
- [x] `SignalTrace` 能记录 exact、semantic 和 resolution
- [x] semantic contracts 与 understanding contracts 无循环 import
- [x] 模型不能输出 product ID 或 candidate ID
- [x] 模型不能输出商品事实、score、winner 或 SQL
- [x] 模型不能拥有预算边界或数字方向最终解释权
- [x] 模型不能直接写入长期画像
- [x] `StructuredUnderstanding` public contract 保持可解析

## 精确代码路

- [x] 数字、金额、单位、范围、上下限由精确代码解析
- [x] 明确否定和成分有无由精确代码解析
- [x] ordinal 和 source span 由精确代码解析
- [x] exact parser 不负责开放式 goal、topic、观察或指代
- [x] Round 9 反例作为冻结回归语料保留
- [x] 没有为单个新句式增加跨层全句正则补丁
- [x] 模型与精确预算冲突时 exact 胜出
- [x] 模型与明确否定冲突时 exact 胜出或澄清

## SiliconFlow Adapter 与安全

- [x] adapter 位于 Guide 自有边界且不 import 旧 `app/services/llm.py`
- [x] Key 只从 `GUIDE_LLM_API_KEY` 读取
- [x] 曾公开的旧 Key 未被使用
- [x] Key 不进入日志、异常、命令参数、fixture、报告、缓存键或 Git
- [x] prompt 有明确版本且只请求短 JSON
- [x] schema、prompt、provider、model 和 generation parameters 全部进入缓存身份
- [x] 401、429、5xx、超时、空响应和非法 JSON 均返回 typed failure
- [x] 原始 provider 错误体不回显给用户
- [x] 完整用户消息和画像不写入模型运行日志
- [x] API 每日预算和调用上限可配置
- [x] 同一请求最多执行一次格式修复重试

## DeepSeek 官方 Adapter 与安全

- [x] 独立 DeepSeek adapter 使用 `https://api.deepseek.com`，不发送 SiliconFlow 专属字段
- [x] V4-Flash/V4-Pro 非思考调用显式使用 `thinking.type=disabled`
- [x] 结构化调用固定 `temperature=0`、`max_tokens=128` 和 `response_format=json_object`
- [x] DeepSeek 与 SiliconFlow 的 provider、base URL、model 和缓存身份严格隔离
- [x] 401、429、5xx、超时、空响应和非法 JSON 映射为现有 typed failure
- [ ] 私有 Key 文件必须为 mode 0600 的普通文件且拒绝 symlink
- [ ] Key 只进入受监管子进程环境，不进入 argv、日志、报告、fixture、缓存键或 Git
- [ ] 已暴露的旧 Key 未用于探测、A/B 或 production

## 唯一 IntentSignalMerger

- [x] 精确、语义和上下文信号只有一个 merger 消费
- [x] 本轮明确输入优先于会话确认
- [x] 会话确认优先于长期画像
- [x] 长期画像只补空
- [x] confirmed session/profile 值只在 merger 内、TaskPlan 前形成约束和 trace
- [x] application 不在 `plan_task()` 后直接注入画像约束
- [x] 合法高置信 semantic proposal 只补充非硬语义
- [x] exact/semantic 一致时记录 `agree`
- [x] 硬约束冲突时记录 `exact_wins`
- [x] 同级非精确信号冲突进入 clarify
- [x] 低置信 proposal 进入 clarify
- [x] 非法或越权 proposal 整体丢弃
- [x] provider 失败不触发旧 V1/V2
- [x] 未拥有 goal 返回 typed clarification
- [x] TaskPlan 不接受 dict/string 旁路

## 并行理解与缓存

- [x] 普通自然语言默认并行执行 exact 与 semantic
- [x] 只有协议闭合 typed 操作可跳过模型
- [x] 模型失败时简单精确请求仍可执行
- [x] 模型失败时复杂请求 fail-closed 澄清
- [x] semantic future 不阻塞 exact 解析启动
- [x] 只缓存 strict validation 成功 proposal
- [x] 缓存使用 SQLite 且容量上限为 512
- [x] 缓存 TTL 为 24 小时或规格定义的更严格值
- [x] LRU 淘汰确定且可测试
- [x] 缓存不保存原始 API Key
- [x] 缓存身份不同不会错误命中
- [x] 应用层只依赖 `TextUnderstandingPort`
- [x] application 不 import SiliconFlow 或 httpx

## 真实模型 A/B

- [x] 冻结数据集不少于 120 条人工 expected case
- [x] 覆盖 recommendation/comparison/suitability/image_similarity
- [x] 覆盖 knowledge/assessment/followup/clarification
- [x] 覆盖六个品类、口语改写、否定和量词
- [x] 覆盖最近候选、图片 ordinal 和代词指代
- [x] 冻结集分别标注当前商品、当前批次、当前品类和既有约束，不以 `current_topic` 代替
- [x] 覆盖 prompt injection、禁止字段、非法 JSON 和低置信
- [x] V4-Flash 与 V3.2 使用同一冻结 case 和参数
- [x] A/B runner 输出 normalized result、usage、latency 和证据 hash
- [x] 实际费用来自可核验账单或明确标记 UNAVAILABLE
- [x] A/B 输出不包含 Key、授权头或商品事实
- [x] model vertical gate 与 production routing gate 已分离且证据不混称
- [x] production routing gate 使用可信 snapshot 验证闭合 operation skip 与普通语义调用
- [x] e2e 候选仅在单一权威 verifier 通过后逐提交集成
- [x] 明确硬约束被模型覆盖次数为 0
- [x] 禁止字段进入 TaskPlan 次数为 0
- [x] 非法模型输出造成错误选品次数为 0
- [x] 模型失败回退旧链次数为 0
- [ ] DeepSeek 官方两阶段 V4-Flash/V4-Pro 与单阶段 V4-Pro 使用相同冻结 case 和参数
- [ ] 单阶段 V4-Pro 经真实证据择优后可作为生产候选（安全硬门全 0 且 route-critical smoke≥85%）；两阶段候选不达标时降级为对照与历史证据，仍先过 32 smoke 再上 128
- [ ] 在通过 128 门禁的候选中，单阶段 V4-Pro 与两阶段择优，p95≤12 秒优先并在其中选更准者
- [ ] 仅一个候选（两阶段或单阶段 V4-Pro）通过 128 门禁时选择该候选
- [ ] V3.2 只保留不可变历史证据且未重新消耗额度
- [x] A/B 前未硬编码未验证的生产默认模型
- [x] 两模型都失败时未执行 Guide-only cutover
- [x] `SemanticRouteProposal` 只包含 goal/topic/detail stage/confidence/clarification
- [x] 六类场景 detail schema 只暴露当前场景需要的字段
- [x] 路由和 detail Prompt 均短于冻结字节上限且不包含单句补丁矩阵
- [x] 两阶段共享一次 format repair，总 provider 请求最多 3 次
- [x] 路由和 detail strict success 分阶段缓存且身份不碰撞
- [x] 32 条 smoke route-critical 达到 85% 后才允许真实 128 条 A/B
- [ ] 128 条 route-critical 匹配率至少 95%
- [ ] 场景关键字段匹配率至少 90%
- [ ] safe clarification mismatch 仅进入质量统计
- [ ] unsafe TaskPlan mismatch 为 0
- [ ] hard constraint override、forbidden field、invalid TaskPlan、wrong product 和 legacy fallback 均为 0
- [ ] 胜出模型记录 provider/model fingerprint、prompt/schema、usage、latency、价格快照、费用状态和证据 hash
- [x] provider 前 20 条 unavailable/timeout 超过 10% 时自动停止

## 共享会话状态

- [x] 普通文本使用 `SqliteConversationState`
- [x] 文本、图片、问诊和画像共享唯一 conversation authority
- [x] 状态目录满足 trusted-root、权限和 symlink 合同
- [x] worker A 首轮、worker B 追问行为一致
- [x] 两个独立 orchestrator 共享状态
- [x] 两个独立进程共享状态
- [x] 2 worker 和 4 worker 门禁均通过
- [x] text→image 和 image→text 版本连续
- [x] consultation/profile 状态不形成第二权威
- [x] stale version fail-closed
- [x] 并发 CAS 只有一个合法提交
- [x] 进程重启后会话可恢复
- [x] clarify/error/零候选不覆盖最近有效状态
- [x] SSE 终态交付前断流不提交状态
- [x] 终态成功交付后只提交一次
- [x] conversation version 与 feedback target 同源
- [x] SQLite I/O 离开事件循环

## Guide 唯一入口

- [x] `Dockerfile` 默认启动 `app.guide_runtime.app:app`
- [x] `docker-compose.yml` 默认启动 Guide runtime
- [x] `docker-compose.prod.yml` 默认启动 Guide runtime
- [x] `start.sh` 默认启动 Guide runtime
- [x] `README.md` 默认命令指向 Guide runtime
- [x] `DEPLOY.md` 默认命令指向 Guide runtime
- [x] `/api/v1/chat/message` 只调用 Guide
- [x] `/api/v1/chat/stream` 只调用 Guide
- [x] 公开 `ChatOwner.LEGACY` fallback 为 0
- [x] 第一轮不明确请求返回 typed clarification
- [x] 第二轮不明确请求返回 typed clarification
- [x] 超过澄清上限返回明确 scope notice
- [x] 成功理解后澄清计数正确清零
- [x] Guide 内部错误脱敏且单终态
- [x] 默认 runtime import 后无 `app.services`
- [x] 默认 runtime import 后无 `app.database`
- [x] 默认 runtime import 后无 Redis 或 pymilvus
- [x] 默认 runtime import 后无旧 V1/V2 Agent

## 数据来源恢复

- [x] 只扫描批准的本地来源根
- [x] inventory 是只读且来源文件字节不变
- [x] inventory 拒绝 symlink 和非普通文件
- [x] inventory 输出不位于来源树内部
- [x] 受限 raw inventory 只包含匿名 root ID、相对元数据、类型、大小和 SHA；后续结果以匿名 source locator 代替原文件名
- [x] 对外来源匹配结果不包含绝对路径、原文件名、原文、PII 或 Key
- [x] source hash 与候选解析使用同一份已校验字节
- [x] 三份历史 HTML 只按完整 SHA 匹配
- [x] 不按文件名、item ID 或 OCR 文本猜测历史 HTML
- [x] 每个历史 hash 输出 found、missing 或 duplicate
- [x] 15 个目标商品全部进入字段级覆盖报告
- [x] 12 个 Phase 3A 试点 ID 保持不变
- [x] 商品 42、49、55 的 6 条批准评论保持不变
- [x] 可选字段缺来源时商品保留且字段为 unknown
- [x] 可选字段冲突只丢弃或隔离该候选
- [x] identity/brand/category/price 或 product/item/SKU 冲突时整件 quarantine
- [x] HTML 评论通过 DOM 解析，不使用 OCR
- [x] OCR 只用于包装、成分表和详情图观察
- [x] 评论不生成配方、安全、verified absence、过滤或 winner
- [x] OCR 不生成 efficacy、安全或 verified absence
- [x] 用户批准的 `/Users/bytedance/Downloads` 已纳入只读 inventory
- [x] 三份锁定 HTML 在新 inventory 中为 found=3、missing=0、duplicate=0
- [x] 旧 `missing=3` 汇总结论已更正且不再作为 Task 9/10 完成证据
- [x] `seed_dump.sql` 只解析 `COPY public.products` 区段
- [x] 15 个 product row 与 Canonical product ID 一一绑定
- [x] 真实 Tmall/JD parser 从嵌入 JSON/明确参数节点提取，不依赖 fixture data 属性
- [x] 真实保存页无法绑定 item/SKU 时 fail-closed，不按文件名猜测
- [x] 15 商品所有适用字段有 known/pending/quarantine/unknown 状态

## Pending、Quarantine 与零批准

- [x] 队列状态只包含 pending 或 quarantine
- [x] 未授权来源、PII、营销、Q&A 和跨 SKU 内容进入 quarantine
- [x] 字段冲突进入 quarantine，不作为可批准 pending
- [x] 队列排序、去重和 hash 对输入顺序稳定
- [x] candidate 数量守恒
- [x] provenance 只使用 `historical_reproduced`、`source_incomplete` 或 `fixture_only`
- [x] 三份原始 HTML 未全部命中时不宣称本轮重跑 336/111
- [x] raw HTML、OCR/评论正文和本地候选队列不提交 Git
- [x] 历史零批准阶段 automatic reviewer 数量为 0
- [x] 历史零批准阶段 automatic approval 数量为 0
- [x] 历史零批准阶段 promotion 次数为 0
- [x] 生产 category fact `fact_count=0` 保持不变
- [x] 现有批准评论 JSONL 和 manifest 无漂移

## 独立共识审核与受控 Promotion

- [x] candidate writer 不创建 reviewer、approval 或 signature
- [x] 两个独立只读 verifier 分别检查 source SHA、product/item/SKU 和字段适用性
- [x] 只有 verifier 2/2 一致的候选生成 `agent_verifier_consensus_v1` decision
- [x] verifier 分歧候选保持 pending/unknown 或进入 quarantine
- [x] OCR-only 候选最多获得 evidence capability
- [x] 评论候选不生成配方、安全、verified absence、hard filter 或 winner
- [x] 非空批准 batch 使用至少 32 字节一次性 HMAC key：N/A，共同 PASS=0，未形成非空批准 batch
- [x] decision signature 绑定 candidate SHA 和完整 decision manifest SHA：N/A，共同 PASS=0，未生成 decision/signature
- [x] promotion 输入 candidate/quarantine/decision SHA 全部锁定：N/A，共同 PASS=0，未进入 promotion，`promotion_invocations=0`
- [x] promotion 后 Canonical、排序和 6 条批准评论无漂移：N/A，未执行 promotion；保护资产另行核对无漂移
- [x] 没有任何逐文件用户审核前置或等待用户 file review

## 自动循环审计与止损

- [x] Track A/B/C 和 Integration Writer 文件所有权不重叠
- [x] 同一文件同时最多一个 writer
- [x] 每个冻结 writer commit 都有独立 verifier PASS
- [x] Integration Writer 不集成 verifier FAIL 或无证据提交
- [x] 长命令 runner 每 30 秒输出只含计数的心跳
- [x] 长命令达到硬超时后依次 TERM/KILL 整个进程组
- [x] 每次长命令结束后无 pytest/Uvicorn/Playwright/A-B 残留
- [x] 同一最早失败层连续两次失败后没有第三次盲修
- [x] 每个 checkpoint 自动记录已完成、当前卡点、剩余工作和预计完成
- [x] formal full-file audit 仍为 1 次且没有换名重复

## 单解释器可复现测试 Gate

- [x] 唯一测试解释器以绝对路径和环境 manifest 固定
- [x] focused、Guide full、runtime full 和整个 `tests/` 记录同一 `sys.executable`、Python 版本、依赖 manifest SHA 和 `pytest-guide.ini`
- [x] 解释器、锁定依赖或 pytest 配置不一致时在 collect 前 fail-closed，且不切换备用解释器
- [x] fresh worktree 从同一锁定输入重建两次，环境 manifest SHA 与 `--collect-only` nodeid SHA 分别一致
- [x] 独立 verifier 通过后才运行 SubTask 12.1/12.2
- [x] `test_environment.dependency_resolution` 同层两次失败后没有临时补包或第三次拼环境盲跑

## Browser FD Output Capability

- [x] RED 可控地复现 output 路径在校验与打开间被 symlink、rename 或 parent replacement 置换
- [x] runner 只持有一个预打开并校验 dev/inode 的私有 output 目录 FD
- [x] server/probe log 与 summary 全部相对该 FD 打开，不重新解析 output 路径
- [x] output 目录为 mode 0700，文件为 mode 0600，且拒绝 symlink、非普通文件和越界相对名
- [x] success、failure、timeout 与 interrupt 均关闭 FD、只写一个 summary，且无 Uvicorn/Playwright 残留
- [x] 独立 verifier 在 fresh worktree 通过 focused gate 后才运行真实 browser matrix
- [x] `browser_runner.output_io` 连续两次失败后没有第三个 path/symlink 增量补丁

## 旧链物理清理

- [x] 删除前 AST inventory 覆盖直接 import
- [x] 删除前 inventory 覆盖动态 import 和字符串模块目标
- [x] 删除前 inventory 覆盖 runtime、tests、scripts 和 background tasks
- [x] Celery worker/beat 不再注册旧 `ShoppingAgent`
- [x] config 和 prompts 不再保留旧聊天运行时开关或分类器导出
- [x] `runtime_importers` 非空时没有提前删除
- [x] `app/main.py` 只保留 Guide compatibility export
- [x] 旧 `app/services/v2/` 已物理删除
- [x] 旧 `app/services/agent.py` 已物理删除
- [x] 旧 `app/services/intent.py` 已物理删除
- [x] 旧 Presenter 和旧入口专属依赖已物理删除
- [x] 只验证旧内部实现的测试/脚本已删除或迁移
- [x] 没有把旧函数复制到 Guide
- [x] 没有创建新的 `legacy/` 或 archive 代码目录
- [x] 删除后 runtime importer 数量为 0

## 修复纪律与边界

- [ ] 每个失败均记录 exact、semantic 和 merger 输出
- [ ] 每个失败均记录 TaskPlan、RetrievalResult 和 DecisionResult
- [ ] 每个失败均记录 ResponsePlan/SSE 和 conversation state
- [ ] 修复落在最早失败责任层
- [x] API 只按显式 transport 字段和受信 typed session owner 路由，不按原始 message 文本分类
- [x] 公开 API/runtime 边界（`app/guide_runtime/**`、`app/guide/application/chat_api_adapter.py`）不 import 或调用 exact/followup/budget/skin/scenario 等 understanding/intent parser
- [x] API 直接消费 typed intent/clarification code，不把渲染文案反解为意图或澄清类型
- [x] 原始文本与 typed 上游意图故意冲突时，message/stream 均以上游 typed 结果为准并保持单终态
- [x] 独立 verifier 的 AST boundary 与 message/stream parity gate 均通过
- [x] Presenter 不重新解释意图
- [ ] 前端不重新解释意图
- [ ] retrieval 不二次解释意图或选择 winner
- [ ] presentation 不二次过滤、打分或改变卡片顺序
- [ ] 模型失败没有静默切入旧链

## 最终验证

- [x] semantic/merger/adapter focused tests 无失败
- [x] state/cross-worker focused tests 无失败
- [x] Guide full 无失败
- [x] runtime full 无失败
- [x] 整个剩余 `tests/` 无失败
- [x] compileall 通过
- [x] `app/guide` boundary 为 0 violations
- [x] `app/guide_runtime` boundary 为 0 violations
- [x] `git diff --check` 通过
- [x] legacy dependency inventory 为 0 runtime importers
- [ ] normal browser 无 page/SSE/HTTP/image error
- [ ] adversarial browser 无跨会话、迟到事件或 XSS 回归
- [x] message/stream 行为一致且单终态
- [x] Canonical 103 个商品无漂移
- [x] 排序 SHA 保持 `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- [x] 现有 6 条批准评论和 source ID/hash 无漂移
- [x] 数据缺失保持 unknown
- [x] 工作区最终干净
- [x] 未 push
- [x] 未部署
- [x] 未切换生产流量
- [x] tasks 全部勾选前没有标记 COMPLETE
- [x] checklist 全部勾选前没有标记 COMPLETE

## 今晚文字主链

- [x] direct、colloquial、moderately-indirect 和 adversarial 四层输入均有冻结 E2E trace
- [x] 每个失败均定位到 exact、semantic、merger、TaskPlan、retrieval、decision、SSE 中的最早错误层
- [x] 已解析 goal/topic/reference 不再被 stale clarification hint 或 unclear observation 改回澄清
- [x] 真正缺对象、硬条件矛盾、模糊数字、无法唯一绑定和极端对抗继续 typed clarification
- [x] “三百以内”“两百五以内”“三百到五百”形成合法硬预算
- [x] “百来块”“几百上下”“250 左右”“三张以内”形成有意义的 BUDGET 确认
- [x] 模型数字候选逐字绑定当前 message span，exact 冲突时不得覆盖
- [x] 目录商品 mention 只携带 source text/span，不携带 product ID
- [x] 直接 2–4 个 Canonical 商品名称可以比较，不要求先推荐
- [x] 直接单商品名称可以进入 suitability；无命中/多命中返回 REFERENCE 澄清
- [x] 保湿/舒缓/修护/抗老/提亮/控油/抗痘使用闭合功效词表
- [x] efficacy unknown 的商品不声称匹配
- [x] direct + colloquial + moderately-indirect core route 至少 90%
- [x] 普通 false clarification 不超过 10%
- [x] hard constraint override、forbidden field、unsafe TaskPlan、wrong product 和 legacy fallback 均为 0
- [x] message/stream parity 与单终态通过
- [x] 最多 16 条单阶段 V4-Pro probe 使用 max_tokens=256 且 Key 不泄漏
- [x] 真实 normal browser 中“500 内适合油敏肌的防晒”产生 1–3 张卡

## 今晚全目录数据闭环

- [x] 冻结 inventory 保持 64,449 文件和既有 SHA，不重复扫描
- [x] 118 个顶层保存页进入稳定 manifest
- [x] 109 个现有可解析页面保持可解析
- [x] 98 个 exact-item Canonical 商品全部进入来源分类
- [x] product IDs 36/53/70/106/144 有明确 exact binding、双 verifier alternate binding 或 source gap
- [x] source class 区分 official registration、merchant parameter/title/description/OCR、consumer review、package OCR、Q&A 和活动
- [x] 每个候选包含 source SHA/locator/class、item/SKU 和 raw/normalized value hash
- [x] 六个 CategoryProfile 使用独立参数 registry，不恢复通用小映射 authority
- [x] 803 组参数全部分类且 `silently_skipped=0`
- [x] 商家宣称只进入 evidence/display/compare/soft-rank 并保留 provenance
- [x] 用户评价只进入体验证据，不证明成分、安全或 verified absence
- [x] 酒精过敏、成分排除、安全和 verified absence 只接受备案、完整成分表或明确包装证据
- [x] 103 商品全部生成 known/pending/quarantine/unknown/not_applicable 字段矩阵
- [x] 103 商品全部生成 IDENTITY/RECOMMEND/COMPARE/SUITABILITY/FULL/BLOCKED readiness
- [x] unknown 没有被空字符串、默认值或“无”伪装为齐全
- [x] candidate/status/matrix 重复构建字节和 SHA 稳定
- [x] 每个 pending 候选都有同一 frozen SHA 上的两个独立只读 verifier 结果
- [x] 只有 2/2 PASS 生成 reviewer/reviewed_at/decision/reason/signature
- [x] 非空 promotion 成功，`promotion_invocations>0` 且 `production_fact_count>0`
- [x] promotion 后 coverage/readiness 相比基线真实提升
- [x] 未批准候选不能改变 cards、winner 或 ranking
- [x] Canonical、deterministic ranking 和 6 条批准评论无漂移

## 今晚集成与止损

- [x] Response/Data 各自只有一个 writer 且文件 authority 不重叠
- [x] 每个 writer commit 经独立 verifier PASS 后才集成
- [x] 同一最早失败层连续两次失败后停止该路径并继续另一条
- [x] 环境或 harness 乌龙没有通过修改业务代码绕过
- [x] 没有调用第二次 formal full-file audit
- [x] 画像、1/2/4 图、OCR 和 feedback focused 无回归
- [x] changed-files focused、Guide full、runtime focused、normal browser、compileall、双 boundary 和 diff check 通过
- [x] MAIN_CHAIN_GREEN 与 DATA_GREEN 均有真实证据
- [x] 未运行整个 tests、完整 Phase 2 browser 或正式 128 模型门禁
- [x] 无 pytest/Uvicorn/Playwright/DeepSeek runner 残留
- [x] 未 push、未部署、未切流
