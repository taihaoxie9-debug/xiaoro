# Slice 1.7 至 2.0 总验收清单

## 起点与保护

- [x] 当前分支为 `rebuild`，起始 HEAD `51e1fbb` 已记录
- [x] Slice 1.6 Round 4 diff 已核实并独立提交
- [x] 旧仓库未被修改
- [x] `app/guide/decision/deterministic_ranking.py` SHA 始终为 `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- [x] 新主链没有 import `app.services`、旧 V1/V2 Agent 或旧图片链
- [x] 未经批准没有修改 `data/canonical/**`
- [x] 未 push、发布、部署或切换生产流量
- [x] 4 个遗留 Slice 1.6 worktree 未被继续开发或擅自删除

## Token 计量

- [x] token ledger 记录 `goal_id=6a76acf2a50b6afe00c97e8c` 的 GOAL_START
- [x] token ledger 字段包含时间、goal ID、stage、event、累计 token、阶段增量、HEAD、状态
- [x] Slice 1.7 开始和完成检查点已记录
- [x] Slice 1.8 开始、硬门和完成/确认 NO-GO 检查点已记录
- [x] Slice 1.9 开始检查点已记录
- [x] Slice 1.9 完成检查点已记录
- [x] Slice 2.0 模型门、开始和完成检查点已记录
- [x] FINAL_AUDIT_COMPLETE 检查点已记录
- [x] N/A（仅一个 goal ID）：未跨 goal 直接相减累计值
- [x] token summary 按 Slice、硬门、测试/Review、Goal segment 汇总可观测真实消耗，并披露早期计量盲区

## Slice 1.7

- [x] 六种明确肤质修改均有解析和规划合同测试
- [x] 模糊肤质、临时症状和同轮预算+肤质复合修改返回 clarify
- [x] 完整品类查询优先于肤质修改解析
- [x] 肤质修改只替换 skin，继承 category、budget、efficacy、exclusions
- [x] 肤质修改重新执行 retrieval、decision、presentation
- [x] 成功结果以 CAS 保存新 query context 和实际展示候选
- [x] missing snapshot、stale version、零候选、presentation error、CAS conflict 不污染快照
- [x] “500 元内修护精华 → 改成敏感肌呢”返回 `[91, 38]`，winner 和 version 正确变化
- [x] 修改后“第二款呢”只使用新快照且不重新召回
- [x] 正式 API 与 runtime 共用肤质修改 HTTP case matrix
- [x] 真实两轮 Playwright 通过且无 page error、失败图片或旧会话污染
- [x] Slice 1.7 full-file review 无未解决 P0-P2
- [x] Slice 1.7 阶段 handoff 和本地提交完成

## Slice 1.8

- [x] verified-absence 审计只读取真实 Canonical、审核记录和正式来源
- [x] “成分表未出现”没有被推导为“不含”
- [x] N/A（NO-GO）：0 条合格事实；14 条候选逐条记录缺失字段和拒绝原因
- [x] N/A（GO 分支）：不存在可供逐条批准并写入 Canonical 的合格事实
- [x] 不存在合格事实时，完整 NO-GO 证据已生成并获得用户确认
- [x] 未获批准时 Canonical 保持不变，成分排除没有假成功
- [x] N/A（GO 分支）：未实现 known present 排除或 verified absence 保留
- [x] N/A（GO 分支）：未开放 absence unknown/conflict 的成分排除成功链
- [x] N/A（GO 分支）：未实现单项成分排除修改或 query context 继承
- [x] 前端未新增“绝对安全”“零刺激”等越权文案，现有正常及对抗浏览器门禁通过
- [x] Slice 1.8 full-file review 无未解决 P0-P2
- [x] Slice 1.8 阶段 handoff 和本地提交完成

## Slice 1.9

- [x] 仅接受 1..4 张 JPEG、PNG、WebP
- [x] 单图 8 MB、总量 20 MB、单图 2000 万像素上限可执行
- [x] MIME、magic bytes、扩展名和真实解码结果一致性被验证
- [x] 动画图片、超像素和解压炸弹被拒绝
- [x] 同时最多两个图片推理任务
- [x] 非法输入不产生可用 bundle、观察、索引或聊天成功
- [x] `ImageBundle`、`ImageObservation` 和公开错误为强类型合同
- [x] bundle/image ID 不可猜测，owner token 只存 hash
- [x] session、token、版本、TTL、删除任一不匹配均 fail-closed
- [x] 聊天只引用 bundle ID，不信任前端候选事实
- [x] 前端支持 1..4 图预览、取消和公开错误，不显示假识别结果
- [x] multipart 在解析前执行总量、结构和 header 硬限，拒绝路径关闭临时文件且不创建 bundle
- [x] 上传在解析前执行同机跨 worker admission 和客户端速率限制
- [x] bundle 状态使用私有 SQLite 在同机 worker 间共享，归属、TTL、删除和 CAS 保持原子
- [x] 正式 API、runtime、Guide 合同和上传表单统一为 strip 后 1..100 字符 `SessionId`
- [x] 前端图片草稿按会话隔离，切换/删除会话会 abort 上传并撤销未使用 bundle
- [x] 图片文案只声明安全接收和识别尚未启用，不暗示已识别或绝对安全
- [x] Task 7A focused、Guide/runtime 全量、静态门禁、103/103 预检和双 Playwright 通过
- [x] 进程内 admission 按 canonical lock directory 分域；同域共享 capacity，不同上传/推理域互不 busy
- [x] admission registry 线程安全、同域 capacity 冲突明确失败，且 inactive domain 会被回收
- [x] `/tmp` 等可信父路径别名先 canonicalize；最终目录和锁文件安全校验保留，非法配置受控为 503
- [x] clean runtime 页头只声明“图片安全接收”，静态和双 Playwright 均有断言
- [x] Task 7B 原复验 probe、focused 180、Guide 730、runtime 76、静态门禁、103/103 预检、双 Playwright 和 full-file self review 通过
- [x] 上传 per-client 限速使用独立私有 SQLite fixed-window 状态，同机两个真实 worker 合计最多放行 12 次，worker 重启继续共享
- [x] 限速检查和计数在 `BEGIN IMMEDIATE` 中原子完成，数据库只保存 client key 的 SHA-256；配置和 DB 故障返回脱敏 503
- [x] 限速 registry 具备 120 秒 TTL、512 client 硬上限；只清理过期窗口，满容量新 key fail-closed，不淘汰活跃限速状态
- [x] 共享 `chat.html`、runtime raw `/chat` 和可见 DOM 全页不含未启用的图片识别或品牌/品类识别承诺，legacy 控制流仅保留中性图片处理文案
- [x] Task 7C focused 50、Guide 738、runtime 86、双 boundary、compileall、diff check、排序 SHA、103/103 预检、双 Playwright、两 worker 探针和 full-file self review 通过
- [x] `ImageRetrievalPort` 和索引 manifest 合同完整
- [x] 103/103 源图路径、字节数和 SHA 预检通过
- [x] runtime 固定 canonical expected count=103，少/多/重复索引均 unhealthy 且检索被阻断
- [x] 未批准模型时构建明确 NO-GO，不生成零向量或 placeholder index
- [x] 向量、预处理或索引 SHA 漂移导致健康检查失败
- [x] inference limiter 拒绝不安全目录/锁文件及 inode 替换攻击，正常多进程峰值不超过 2
- [x] source root 解析、symlink loop 和文件系统异常只返回脱敏 unhealthy
- [x] 图片检索请求的声明 SHA-256 与 content 真实摘要一致
- [x] staging 清理失败显式返回残留错误，且不会删除输出父目录外路径
- [x] Slice 1.9 正常及对抗 Playwright 通过
- [x] Slice 1.9 full-file review 无未解决 P0-P2
- [x] Slice 1.9 阶段 handoff 和本地提交完成

## Slice 2.0

- [x] 模型候选包含家族、来源、许可证、权重 SHA、维度、预处理、CPU 延迟和 GPU 可选性
- [x] 模型、权重和下载权限已获用户明确批准（无独立权重 LICENSE 风险例外仅限本地内部开发/验收）
- [x] 批准模型与权重 SHA 被锁定
- [x] 103/103 真实商品图向量及索引 manifest 构建成功
- [x] 查询与索引使用相同模型、权重和预处理版本
- [x] 本地索引重复运行顺序稳定，平局按 numeric product ID 升序
- [x] 索引内真实图 top-1 命中自身 product ID
- [x] 受控缩放/重编码图 top-3 包含自身 product ID
- [x] OCR/视觉观察不覆盖 Canonical
- [x] 低置信、多候选接近、OCR 冲突和无候选均 fail-closed
- [x] 图片相似度只负责召回，预算、品类、排除项由确定性决策执行
- [x] 未确认身份不能进入适配、比较或 winner
- [x] typed SSE 输出真实观察、候选、公开错误、模型和索引版本
- [x] 浏览器真实上传后显示真实候选、商品图和详情链接
- [x] 页面不显示“百分百识别”或其他无来源精确结论
- [x] 缺索引、坏 SHA 或模型不可用时 `/health` 非 healthy
- [x] 全链不 import 旧图片服务或默认启动 Milvus
- [x] Slice 2.0 full-file review 无未解决 P0-P2

## 最终发布门禁

- [x] 所有 focused tests 通过
- [x] Guide 全量测试通过
- [x] Runtime 全量测试通过
- [x] `app/guide` 与 `app/guide_runtime` 双 boundary 通过
- [x] `compileall` 和 `git diff --check` 通过
- [x] 排序内核 SHA 未变化
- [x] 真实数据与 103/103 索引 case matrix 通过
- [x] 正式 API 与 runtime HTTP 门禁通过
- [x] 正常及对抗 Playwright 通过
- [x] 1.7→2.0 全文件最终 review 无未解决 P0-P2
- [x] 工作区干净
- [x] 无残留 Uvicorn、pytest 或 Playwright 进程
- [x] 最终 `morning_handoff.md` 记录提交、测试、浏览器证据、模型/索引版本、风险和保护值
- [x] Slice 2.0 真实闭环完成前没有宣布 COMPLETE
