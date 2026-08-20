# Tasks

- [x] Task 0: 固化起点并建立总控台账
  - [x] SubTask 0.1: 确认分支为 `rebuild`、HEAD 为 `51e1fbb`，且现有 diff 仅为 Slice 1.6 Round 4 PASS 记录
  - [x] SubTask 0.2: 为 Round 4 记录创建独立本地提交，不覆盖其他用户改动
  - [x] SubTask 0.3: 记录 Goal 起始 `goal_id`、累计 token、时间、HEAD 和排序 SHA
  - [x] SubTask 0.4: 创建 append-only token usage CSV，并记录 `GOAL_START`、`SLICE_1_7_START`
  - [x] SubTask 0.5: 复验 Slice 1.6 保护值，确认 1.7 的权威起点

- [x] Task 1: 定义 Slice 1.7 肤质修改理解与规划合同
  - [x] SubTask 1.1: 为六种明确肤质、模糊表达、复合修改和完整品类优先级补 RED 合同测试
  - [x] SubTask 1.2: 实现 `SkinRevisionDraft` 和精确肤质修改解析，不从临时症状推断肤质
  - [x] SubTask 1.3: 实现 `SkinRevisionPlan`，只替换 skin 并继承 category、budget、efficacy、exclusions
  - [x] SubTask 1.4: 运行 understanding/intent focused tests、双 boundary 和排序 SHA
  - [x] SubTask 1.5: 创建本地单一职责提交

- [x] Task 2: 接入 Slice 1.7 完整重筛与状态提交
  - [x] SubTask 2.1: 为 missing snapshot、stale version、零候选、presentation error 和 CAS conflict 补 RED 测试
  - [x] SubTask 2.2: 在 orchestrator 中接入肤质修改，重新执行 retrieval、decision、presentation
  - [x] SubTask 2.3: 只在成功可见结果前 CAS 保存新 query context 和实际展示 candidates
  - [x] SubTask 2.4: 验证后续“第二款呢”使用新快照且不重新召回
  - [x] SubTask 2.5: 创建本地单一职责提交

- [x] Task 3: 完成 Slice 1.7 正式 API、浏览器和阶段门禁
  - [x] SubTask 3.1: 扩展 Guide owner 路由和 HTTP case matrix，保留 version 0 旧会话边界
  - [x] SubTask 3.2: 新增真实两轮 Playwright：修护精华 → 改成敏感肌 → 第二款
  - [x] SubTask 3.3: 运行 focused、Guide 全量、runtime、双 boundary、compileall、backend、正常/对抗 Playwright
  - [x] SubTask 3.4: 对 Slice 1.7 生产文件执行 full-file review，修复全部确认 P0-P2
  - [x] SubTask 3.5: 生成 Slice 1.7 handoff，记录 `SLICE_1_7_COMPLETE`、`SLICE_1_8_START` token 检查点
  - [x] SubTask 3.6: 创建阶段收口提交并自动进入 Slice 1.8

- [x] Task 4: 执行 Slice 1.8 verified-absence 事实审计
  - [x] SubTask 4.1: 只读盘点 Canonical、审核决定和现有正式来源标识，不修改商品事实
  - [x] SubTask 4.2: 验证每条候选是否具备明确“不含/无添加/free from”原文、来源、时间、审核记录和内容 SHA
  - [x] SubTask 4.3: 生成结构化候选事实或 NO-GO 证据，并加入可机械复验的来源完整性测试
  - [x] SubTask 4.4: 运行只读审计回归、双 boundary、保护路径和排序 SHA
  - [x] SubTask 4.5: 记录 `SLICE_1_8_DECISION_GATE` token 检查点
  - [x] SubTask 4.6: 用户已明确批准 NO-GO；Canonical 保持不变，继续进入 Slice 1.9

- [x] Task 5: 落实用户批准的 Slice 1.8 NO-GO 分支
  - [x] SubTask 5.1: N/A（GO 分支不适用）；未写入 verified-absence 事实，未重建 Canonical manifest/SHA
  - [x] SubTask 5.2: NO-GO 已确认；Canonical 保持不变并固化事实阻塞合同
  - [x] SubTask 5.3: N/A（GO 分支不适用）；未实现单项成分排除成功能力
  - [x] SubTask 5.4: N/A（GO 分支不适用）；未新增两轮成分排除成功链或越权文案
  - [x] SubTask 5.5: 运行全阶段统一门禁与 full-file review，全部确认 P0-P2 已清零
  - [x] SubTask 5.6: 生成 Slice 1.8 handoff，记录 `SLICE_1_8_COMPLETE_OR_CONFIRMED_NO_GO` token 检查点
  - [x] SubTask 5.7: 创建阶段收口提交并自动进入 Slice 1.9

- [x] Task 6: 建立 Slice 1.9 安全图片输入合同
  - [x] SubTask 6.1: 为 JPEG/PNG/WebP、MIME/magic/解码一致性、体量、像素、动画和解压炸弹补 RED 测试
  - [x] SubTask 6.2: 实现 1..4 图安全解码与单图 8 MB、总量 20 MB、2000 万像素上限
  - [x] SubTask 6.3: 实现全局最多两个图片推理任务的有界并发合同
  - [x] SubTask 6.4: 验证拒绝路径不产生 bundle、观察、索引或聊天成功
  - [x] SubTask 6.5: 创建本地单一职责提交

- [x] Task 6A: 修复单主机跨进程图片推理并发上限
  - [x] SubTask 6A.1: 新增真实 multiprocessing RED 测试，证明三个以上 worker 的峰值可突破 2（旧实现实测峰值 4）
  - [x] SubTask 6A.2: 以可注入锁目录的 `fcntl` 文件锁槽位实现跨进程与线程共享上限，并保留简单 API
  - [x] SubTask 6A.3: 固化阻塞/超时、异常释放、锁文件权限和单主机部署边界合同
  - [x] SubTask 6A.4: focused 12、图片 Guide 35、Guide 全量 570、双 boundary、compileall、diff check、排序 SHA 和 self review 均通过

- [x] Task 7: 建立 ImageBundle 状态、归属与 API
  - [x] SubTask 7.1: 定义强类型 `ImageBundle`、`ImageObservation` 和公开错误合同
  - [x] SubTask 7.2: 实现不可猜测 bundle/image ID、owner token hash、TTL、版本和删除语义
  - [x] SubTask 7.3: 为跨 session/token、过期、删除和只知 bundle ID 的攻击补对抗测试
  - [x] SubTask 7.4: 接入上传 API 与聊天 `bundle_id` 引用，拒绝前端提交候选事实
  - [x] SubTask 7.5: 前端支持 1..4 图预览、取消和错误展示，不显示假识别结果
  - [x] SubTask 7.6: 创建本地单一职责提交

- [x] Task 7A: 修复 ImageBundle 上传生命周期独立审查问题
  - [x] SubTask 7A.1: 在 FastAPI multipart 解析前执行声明/流式总量、字段、文件名和 header 硬限，并关闭已创建的 spooled files
  - [x] SubTask 7A.2: 在解析和 bundle 创建前执行同机跨 worker 上传并发 admission 与客户端速率限制
  - [x] SubTask 7A.3: 以私有 SQLite 状态实现同机跨 worker 的 bundle 共享、TTL、归属、删除和原子 CAS
  - [x] SubTask 7A.4: 正式 API、runtime、Guide 合同和上传表单统一使用 strip 后 1..100 字符 `SessionId`
  - [x] SubTask 7A.5: 前端按会话隔离图片草稿，切换/删除会话时 abort 请求并撤销未使用 bundle
  - [x] SubTask 7A.6: 将上传与聊天文案校准为“安全接收、识别尚未启用”，不暗示已识别或绝对安全
  - [x] SubTask 7A.7: focused 341、Guide 718、runtime 70、双 boundary、compileall、diff check、排序 SHA、103/103 预检和双 Playwright 均通过

- [x] Task 7B: 修复 HEAD `962b565` 独立复验的 limiter、路径和页头问题
  - [x] SubTask 7B.1: 以 RED 复现推理域占满导致独立上传域 busy，并按 canonical lock directory 分域共享进程内 capacity
  - [x] SubTask 7B.2: 以线程安全引用计数 registry 拒绝同域 capacity 冲突，并在最后一个调用退出后回收 domain
  - [x] SubTask 7B.3: 配置边界 canonicalize 可信符号链接父路径，保留最终目录/锁文件 owner、mode、symlink、regular-file 校验，非法配置返回受控 503
  - [x] SubTask 7B.4: clean runtime 页头改为“图片安全接收”，并增加静态与双 Playwright 断言
  - [x] SubTask 7B.5: 原复验 probe、focused 180、Guide 730、runtime 76、双 boundary、compileall、diff check、排序 SHA、103/103 预检、双 Playwright 和 full-file self review 均通过

- [x] Task 7C: 修复 HEAD `d442011` 最终独立复验的共享限速、状态上界和图片文案问题
  - [x] SubTask 7C.1: 以独立评审的两个真实 worker 各自放行 12 次为 RED 证据，先补双 worker 合计上限和重启共享合同测试
  - [x] SubTask 7C.2: 以独立私有 SQLite fixed-window 状态和 `BEGIN IMMEDIATE` 实现同机跨 worker 原子限速，client key 只存 SHA-256，配置或 DB 故障受控返回 503
  - [x] SubTask 7C.3: 增加 120 秒 TTL 清理、512 client 硬容量和确定性最旧项淘汰，覆盖并发、窗口翻转、1000 client、淘汰与重启共享
  - [x] SubTask 7C.4: 将共享 `chat.html` 的 header、onboarding、status、错误和 legacy JS 文案统一为中性“图片处理/安全接收”，静态、raw `/chat` 和可见 DOM 全页禁词断言通过
  - [x] SubTask 7C.5: focused 50、Guide 738、runtime 86、双 boundary、compileall、diff check、排序 SHA、103/103 预检、双 Playwright、两 worker 探针和 full-file self review 均通过

- [x] Task 8: 建立可复现图片索引地基
  - [x] SubTask 8.1: 定义 `ImageRetrievalPort`、构建输入输出和索引 manifest 模型
  - [x] SubTask 8.2: 为 103/103 源图路径、字节数、SHA 和稳定顺序补预检
  - [x] SubTask 8.3: 未批准模型时构建命令明确 NO-GO，禁止零向量或 placeholder index
  - [x] SubTask 8.4: 为向量、预处理版本和索引 SHA 漂移补健康检查失败测试
  - [x] SubTask 8.5: 运行 Slice 1.9 HTTP 与浏览器门禁，验证预览可用但无假候选
  - [x] SubTask 8.6: 创建本地单一职责提交

- [x] Task 8A: 修复 Slice 1.9 index/core 独立审查 P1/P2
  - [x] SubTask 8A.1: 以 RED 证明 102/104 自洽索引会误判健康，固定 runtime canonical count=103，并阻断少/多/重复索引检索
  - [x] SubTask 8A.2: 以 symlink、owner、权限、非 regular file、open 竞态和持锁 inode 替换攻击 RED 加固 inference limiter，保持真实多进程峰值不超过 2
  - [x] SubTask 8A.3: 将 source root resolve、symlink loop、`OSError`/`RuntimeError` 统一转为脱敏 unhealthy
  - [x] SubTask 8A.4: 校验 `ImageRetrievalRequest.content_sha256` 与 content 真实 SHA-256 一致
  - [x] SubTask 8A.5: 建立 staging 安全清理边界与 `index_cleanup_failed` 显式残留错误合同
  - [x] SubTask 8A.6: focused 69、Guide 634、runtime 49、双 boundary、compileall、diff check、排序 SHA 和 full-file self review 均通过

- [x] Task 9: 完成 Slice 1.9 发布门禁
  - [x] SubTask 9.1: 运行 focused、Guide 全量、runtime、双 boundary、compileall、真实图片 case matrix 和双 Playwright
  - [x] SubTask 9.2: 对 Slice 1.9 生产文件执行 full-file review，修复全部确认 P0-P2
  - [x] SubTask 9.3: 生成 Slice 1.9 handoff，记录 `SLICE_1_9_COMPLETE`、`SLICE_2_0_MODEL_GATE` token 检查点
  - [x] SubTask 9.4: 创建阶段收口提交并进入模型硬决策门

- [x] Task 10: 准备并通过 Slice 2.0 模型硬决策门
  - [x] SubTask 10.1: 只读盘点本地可用模型/权重，不联网、不下载
  - [x] SubTask 10.2: 为候选模型整理家族、来源、许可证、权重 SHA、维度、预处理、CPU 延迟和 GPU 可选性
  - [x] SubTask 10.3: 用户明确批准固定 OpenCLIP 模型、safetensors SHA、独立依赖安装和受限 PyPI wheel 联网
  - [x] SubTask 10.4: 用户以 `WEIGHT_LICENSE_RISK_EXCEPTION_APPROVE` 接受无独立权重 LICENSE 风险；模型锁、依赖验收和 `SLICE_2_0_START` 已记录，且仅限本地内部开发/验收

- [x] Task 11: 使用批准模型构建 103/103 本地索引
  - [x] SubTask 11.1: 实现批准模型 adapter 和确定性预处理，不引入旧图片链或默认 Milvus
  - [x] SubTask 11.2: 构建 103/103 向量及 manifest，记录权重、向量和索引 SHA
  - [x] SubTask 11.3: 实现 `LocalNumpyImageIndex` 稳定检索和 numeric product ID 平局顺序
  - [x] SubTask 11.4: 验证索引内图 top-1 自命中、重编码图 top-3 自命中和重复运行稳定
  - [x] SubTask 11.5: 创建本地单一职责提交

- [x] Task 12: 建立 OCR/视觉观察和 Canonical 身份绑定
  - [x] SubTask 12.1: 定义 OCR/视觉观察 adapter 端口和身份状态，不信任 raw OCR
  - [x] SubTask 12.2: 实现视觉候选与 Canonical ID 绑定，冲突时 Canonical 保持权威
  - [x] SubTask 12.3: 覆盖低置信、多候选接近、OCR 冲突和无候选 fail-closed
  - [x] SubTask 12.4: 创建本地单一职责提交

- [x] Task 13: 跑通 Slice 2.0 决策、SSE、商品卡和浏览器
  - [x] SubTask 13.1: 将图片召回接入干净 orchestrator，相似度只负责召回
  - [x] SubTask 13.2: 叠加预算、品类和排除项硬条件，并禁止未确认身份产生 winner
  - [x] SubTask 13.3: 扩展 typed SSE、公开错误、模型/索引版本和真实商品卡
  - [x] SubTask 13.4: 完成真实单图上传与找相似 Playwright，验证图片、链接、版本和错误路径
  - [x] SubTask 13.5: 创建本地单一职责提交

- [x] Task 14A: 修复最终 full-file review 的确认 P1/P2
  - [x] SubTask 14A.1: 修复限速容量淘汰、上传 close 全释放、SQLite bundle corruption 映射
  - [x] SubTask 14A.2: 修复索引发布事务、provenance 漏项和 no-clobber
  - [x] SubTask 14A.3: 修复正式非流式文本 Guide 分发及文本 async SSE 线程桥
  - [x] SubTask 14A.4: 修复 Data URL 持久化、详情 URL XSS、多图发送前拒绝和 DELETE mock
  - [x] SubTask 14A.5: 独立复验并重跑 focused/full/static/browser/index gates

- [x] Task 14B: 修复 Task14A 独立复验缺陷
  - [x] SubTask 14B.1: 补齐索引完整 import closure 并保留 rollback 主异常
  - [x] SubTask 14B.2: 更新正式 API 静态接线测试识别 threadpool callable
  - [x] SubTask 14B.3: 修复所有商品 image URL 属性 XSS 与 renderProductShelf inline handler，并加强门禁
  - [x] SubTask 14B.4: 独立复验所有 12+新增 finding

- [x] Task 14: 完成 Slice 2.0 与全局最终审计
  - [x] SubTask 14.1: 运行所有 focused、Guide 全量、runtime 全量、双 boundary、compileall、diff check、排序 SHA
  - [x] SubTask 14.2: 运行 103/103 索引完整性、真实图片 case matrix、正式/runtime HTTP、正常与对抗 Playwright
  - [x] SubTask 14.3: 对 1.7→2.0 全部生产文件执行 full-file review，修复所有确认 P0-P2 后重跑门禁
  - [x] SubTask 14.4: 确认工作区干净、无残留 Uvicorn/pytest/Playwright、无 push/发布/部署
  - [x] SubTask 14.5: 记录 `SLICE_2_0_COMPLETE`、`FINAL_AUDIT_COMPLETE` token 检查点
  - [x] SubTask 14.6: 生成 token usage summary 和最终 `morning_handoff.md`
  - [x] SubTask 14.7: 创建最终收口提交；仅在全部 checklist 通过后调用 `update_goal(status="complete")`

# Task Dependencies

- Task 1 depends on Task 0.
- Task 2 depends on Task 1.
- Task 3 depends on Task 2.
- Task 4 depends on Task 3.
- Task 5 depends on Task 4 and the verified-absence hard decision.
- Task 6 depends on Task 5.
- Task 7 depends on Task 6.
- Task 8 depends on Task 6; its contract and source-image precheck may run in parallel with Task 7.
- Task 8A depends on Task 8 and its independent review report.
- Task 9 depends on Tasks 7, 8, and 8A.
- Task 10 depends on Task 9 and the model hard decision.
- Task 11 depends on Task 10.
- Task 12 depends on Task 10; observation contracts may run in parallel with Task 11.
- Task 13 depends on Tasks 11 and 12.
- Task 14A depends on Tasks 1 through 13.
- Task 14B depends on Task 14A.
- Task 14 depends on Task 14B.

# Parallelizable Work

- Task 7 的 bundle 状态/API 与 Task 8 的索引合同/源图预检可由不同子代理并行，但不得越过 Slice 1.9 阶段边界。
- Task 11 的向量索引实现与 Task 12 的观察/身份合同可在模型批准后并行。
- 每个阶段的 full-file review 必须由未实施该阶段代码的独立验证子代理执行。
