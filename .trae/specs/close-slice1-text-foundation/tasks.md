# Tasks

- [x] Task 1: 收紧 application 架构门禁并移除伪契合分
  - [x] SubTask 1.1: 为真实编排器、application 适配器评分和非字面量动态导入补 RED 测试
  - [x] SubTask 1.2: 扩展 boundary visitor 覆盖所有 application 文件
  - [x] SubTask 1.3: 删除 `match_score` 和百分比契合展示，改为离散证据标签
  - [x] SubTask 1.4: 运行 focused tests、双 boundary、排序 SHA 和 diff 检查
  - [x] SubTask 1.5: 创建本地提交 `fix(guide): enforce truthful application boundaries`

- [x] Task 2: 修正 target-aware 肤质三态
  - [x] SubTask 2.1: 为六种肤质的泛化证据和明确异类证据补 RED 矩阵
  - [x] SubTask 2.2: 实现 explicit match / explicit mismatch / unknown
  - [x] SubTask 2.3: 在 decision trace 中加入规范化 skin 约束
  - [x] SubTask 2.4: 运行真实干皮修护精华、决策和 backend 回归
  - [x] SubTask 2.5: 创建本地提交 `fix(decision): preserve unknown generic skin evidence`

- [x] Task 3: 将具体 adapter 组装移出 application
  - [x] SubTask 3.1: 增加 application 不导入具体 adapter 的 RED 测试
  - [x] SubTask 3.2: 在 runtime composition 中建立可注入组装函数
  - [x] SubTask 3.3: 删除 application factory 并更新全部调用方
  - [x] SubTask 3.4: 运行 application、runtime composition 和 boundary 回归
  - [x] SubTask 3.5: 创建本地提交 `refactor(runtime): own concrete guide composition`

- [x] Task 4: 在首个 post-start 事件前提交状态并串行同 session
  - [x] SubTask 4.1: 为仅 start 断流、message 后断流和 followup 状态一致性补 RED 测试
  - [x] SubTask 4.2: 实现固定条带数量的 `InMemorySessionLocks`
  - [x] SubTask 4.3: 将 session lock port 注入 orchestrator
  - [x] SubTask 4.4: 先构造成功事件、CAS save，再公开 products/message/end
  - [x] SubTask 4.5: 运行状态、正式 async 并发/heartbeat、HTTP 和 CAS 回归
  - [x] SubTask 4.6: 创建本地提交 `fix(feedback): commit only delivered conversation turns`

- [x] Task 5: 让正式 API 保留所有已支持多轮请求
  - [x] SubTask 5.1: 为无品类词追问和 version 透传补 RED 测试
  - [x] SubTask 5.2: 使用 exact/followup/budget owner parser 替换关键词分流
  - [x] SubTask 5.3: 为 `ChatRequest` 增加并透传 `conversation_version`
  - [x] SubTask 5.4: 运行 adapter、route wiring 和 runtime HTTP 回归
  - [x] SubTask 5.5: 创建本地提交 `fix(api): preserve clean guide multi-turn routing`

- [x] Task 6: 让前端错误和在途请求绑定 session
  - [x] SubTask 6.1: 为 AbortController、request map 和错误解析结构补 RED 测试
  - [x] SubTask 6.2: 实现 per-session 在途请求注册、取消和清理
  - [x] SubTask 6.3: 分离 SSE JSON 解析错误与业务 error
  - [x] SubTask 6.4: Guide runtime 停用假工具动画并消费真实 stage
  - [x] SubTask 6.5: 新增错误可见和切换会话不串流的 Playwright 对抗门禁
  - [x] SubTask 6.6: 创建本地提交 `fix(frontend): isolate guide stream requests by session`

- [x] Task 7: 在 runtime 启动时验证图片资产
  - [x] SubTask 7.1: 为 manifest 自摘要、缺图和图片 SHA 漂移补 RED 测试
  - [x] SubTask 7.2: 验证 manifest 规范化摘要
  - [x] SubTask 7.3: 要求绝对 asset root 并验证路径、字节数和文件 SHA
  - [x] SubTask 7.4: 更新全部调用方并运行 startup regression
  - [x] SubTask 7.5: 创建本地提交 `fix(catalog): verify runtime image asset integrity`

- [x] Task 8: 固化正式与 runtime 的共享 HTTP/浏览器合同
  - [x] SubTask 8.1: 新增三类多轮请求共享 HTTP case matrix
  - [x] SubTask 8.2: 扩展 browser smoke，验证无伪分和干皮 unknown
  - [x] SubTask 8.3: 运行正常与对抗 Playwright 门禁
  - [x] SubTask 8.4: 创建本地提交 `test(guide): gate the slice 1.6 text foundation`

- [x] Task 9: 完成发布门禁、全文件审查和晨间交接
  - [x] SubTask 9.1: 运行 Guide 全量、runtime 全量、compileall、双 boundary 和排序 SHA
  - [x] SubTask 9.2: 从 `/tmp` 运行 backend CSV gate 和两类 Playwright
  - [x] SubTask 9.3: 对本次生产文件执行 full-file code review
  - [x] SubTask 9.4: 修复所有确认的 P0-P2 并重跑全部门禁
  - [x] SubTask 9.5: 生成 `test_evidence.csv` 和 `morning_handoff.md`
  - [x] SubTask 9.6: 勾选施工计划全部步骤并创建收口提交

- [x] Task 10: 修复 Slice 1.6 发布审查确认问题
  - [x] SubTask 10.1: 先公开 start，在同步 session lock 内完整缓冲其余事件，释放锁后再公开
  - [x] SubTask 10.2: 在首个 post-start 成功事件前 CAS 提交状态，冲突时只公开 clarify/end
  - [x] SubTask 10.3: 以 conversation_version 限制 followup/budget Guide owner 路由
  - [x] SubTask 10.4: 当前 session reactivation 在 DOM rehydrate 前直接 no-op
  - [x] SubTask 10.5: 补正式 async router 并发/heartbeat、断流、CAS、旧会话路由和对抗 Playwright 回归
  - [x] SubTask 10.6: 更新规格、施工计划、审查证据并记录单 worker 残余风险

- [x] Task 11: 修复最终全文件审查的正式聊天 API 发布阻断
  - [x] SubTask 11.1: 为会话归属、存储失败、异常脱敏和请求体上限补 HTTP/合同 RED 测试
  - [x] SubTask 11.2: 会话历史读取和删除强制认证，并以 `session_id + user_id` fail-closed
  - [x] SubTask 11.3: 数据库失败返回 503，删除使用 `RETURNING` 区分成功与不存在
  - [x] SubTask 11.4: 非流式与 SSE 内部异常仅写日志，对外返回稳定错误码和通用文案
  - [x] SubTask 11.5: 限制 chat 请求字节数、消息/历史/图片数量和嵌套对象体量，并启用 chat rate limit
  - [x] SubTask 11.6: 重跑 focused、Guide 全量、runtime、双 boundary、backend 和双浏览器门禁
  - [x] SubTask 11.7: 对 Task 11 生产文件复审并确认无未解决 P0-P2

# Task Dependencies

- Task 2 depends on Task 1.
- Task 3 depends on Task 1.
- Task 4 depends on Task 3.
- Task 5 depends on Task 3 and Task 4.
- Task 6 depends on Task 1 and Task 5.
- Task 7 depends on Task 3.
- Task 8 depends on Tasks 2, 4, 5, 6, and 7.
- Task 9 depends on Tasks 1 through 8.
- Task 10 depends on Tasks 1 through 8 and the Slice 1.6 release review.
- Task 11 depends on Task 10 and the final Slice 1.6 full-file review.

# Parallelizable Work

- After Task 1, Tasks 2 and 3 can be implemented independently.
- After Task 3, Task 7 can run independently of Task 4.
- Verification of backend contracts and frontend source contracts may run in parallel, but commits must preserve the dependency order above.
