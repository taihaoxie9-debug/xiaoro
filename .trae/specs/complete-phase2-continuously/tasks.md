# Tasks

- [x] Task 1: 完成共享地基冻结 checkpoint
  - [x] SubTask 1.1: 严格执行 `2026-08-09-phase2-day1-stabilization.md`
  - [x] SubTask 1.2: 修复五个确认 P1 并通过 RED-first 回归
  - [x] SubTask 1.3: 冻结后端商品卡、owner matrix、轻问诊/画像/多图合同
  - [x] SubTask 1.4: 删除前端文本推断和补足三卡
  - [x] SubTask 1.5: 运行全量、runtime、双 boundary 和双浏览器门禁
  - [x] SubTask 1.6: fast-forward 回 `rebuild` 并创建三条同基线 worktree
  - [x] SubTask 1.7: 追加 checkpoint 后立即进入 Task 2，不标记总体完成

- [x] Task 2: 并行实现轻问诊与长期画像
  - [x] SubTask 2.1: RED-first 实现可观察现象问答和会话版本
  - [x] SubTask 2.2: RED-first 实现确定性暂定结论、依据、不确定项和就医边界
  - [x] SubTask 2.3: RED-first 实现用户确认流，信息收集和未确认结论均为 0 卡
  - [x] SubTask 2.4: RED-first 实现画像 owner、来源、确认时间和 CAS version
  - [x] SubTask 2.5: 实现本轮明确输入 > 会话确认 > 长期画像 > 默认的优先级
  - [x] SubTask 2.6: 阻止临时预算、短期症状和未确认推断进入画像
  - [x] SubTask 2.7: 每个纵向行为小步提交并提供 focused/HTTP 证据

- [x] Task 3: 并行实现多图、适配与 OCR
  - [x] SubTask 3.1: RED-first 实现 1–4 图连续 ordinal 和当前 Bundle 指代
  - [x] SubTask 3.2: RED-first 实现两图身份门、Canonical 比较和精确 2 卡
  - [x] SubTask 3.3: 实现 winner、tie、insufficient evidence 三态
  - [x] SubTask 3.4: RED-first 实现单图适配和精确 1 卡/澄清
  - [x] SubTask 3.5: 接入批准 OCR adapter，包装/成分表只产生观察
  - [x] SubTask 3.6: OCR unavailable/conflict fail-closed，不覆盖 Canonical
  - [x] SubTask 3.7: RED-first 实现三到四图比较和精确 3–4 卡
  - [x] SubTask 3.8: 每个纵向行为小步提交并提供 focused/HTTP 证据
  - [x] SubTask 3.9: 修复Round13图片集成审计P1并通过复验

- [x] Task 4: 并行实现场景、评论、避坑与反馈
  - [x] SubTask 4.1: RED-first 实现通勤、旅行、户外、修护、敏感期场景约束
  - [x] SubTask 4.2: RED-first 实现可审计 review evidence reader
  - [x] SubTask 4.3: 评论总结区分来源事实与综合文案，缺来源不生成
  - [x] SubTask 4.4: 避坑保留 severity 和 evidence refs，不生成假安全结论
  - [x] SubTask 4.5: 实现点击、收藏、比较和负反馈 typed events
  - [x] SubTask 4.6: 实现反馈 owner、时间、会话/画像引用和幂等键
  - [x] SubTask 4.7: 保证反馈不直接修改商品事实或排序
  - [x] SubTask 4.8: 每个纵向行为小步提交并提供 focused/HTTP 证据
  - [x] SubTask 4.9: 修复反馈集成共享身份与合同冲突

- [x] Task 5: 持续增量集成三条工作线
  - [x] SubTask 5.1: 集成 owner 审查每个绿色 domain commit
  - [x] SubTask 5.2: 按轻问诊→画像→两图→适配→OCR→多图→场景→评论/避坑→反馈顺序小步合并
  - [x] SubTask 5.3: 共享 API/SSE/前端仅由集成 owner 修改
  - [x] SubTask 5.4: 每次集成运行 focused、双 boundary 和一条真实浏览器链
  - [x] SubTask 5.5: 通过真实门禁后扩展 owner matrix，失败不回退旧 V2
  - [x] SubTask 5.6: 每次集成追加 progress 并继续，不等待普通确认
  - [x] SubTask 5.7: 每个 capability loop 冻结 capability_key、iteration_id、scope manifest 和 audit profile
  - [x] SubTask 5.8: 开头最多调用一次 full-file audit；相同 audit key 复用 PASS
  - [x] SubTask 5.9: finding 修复只用 RED/GREEN 与正常门禁验证，不在同一循环重复审计
  - [x] SubTask 5.10: cherry-pick 前比较 stable patch ID 和 final blob manifest，跳过等价提交
  - [x] SubTask 5.11: 审计器不可用只记录一次并继续其他独立工作
  - [x] SubTask 5.12: 每个 checkpoint 追加 Agent token ledger；audit ledger 仅在首次调用、复用或状态变化时追加

- [x] Task 6: 完成前端二期展示
  - [x] SubTask 6.1: 接入 consultation observation 和 profile confirmation
  - [x] SubTask 6.2: 接入单图适配和两到四图比较区
  - [x] SubTask 6.3: 接入 OCR observation、citations、pitfalls 和 feedback
  - [x] SubTask 6.4: 验证单品 1 卡、推荐 1–3 卡、比较 2–4 卡、知识/问诊收集/澄清/错误 0 卡
  - [x] SubTask 6.5: 保持会话切换、AbortController、迟到响应和快照清洗安全
  - [x] SubTask 6.6: 正常和对抗浏览器均无 page error、SSE parse error 或失败商品图

- [x] Task 7: 运行四条真实纵向门禁
  - [x] SubTask 7.1: 文本自然语言→约束→召回→决策→精确卡片→浏览器
  - [x] SubTask 7.2: 单/双/四图→安全 Bundle→OpenCLIP/OCR→身份→推荐/比较→浏览器
  - [x] SubTask 7.3: 知识→轻问诊→确认→画像补空→后续推荐
  - [x] SubTask 7.4: clean runtime→健康检查→文本/图片/多轮浏览器→零旧服务 import
  - [x] SubTask 7.5: 导出输入、图片 ID、候选、最终 ID、状态、失败原因、延迟、模型/索引版本证据

- [x] Task 8: 完成全量验证与独立审查
  - [x] SubTask 8.1: 运行所有 focused 套件
  - [x] SubTask 8.2: 运行 Guide 全量和 runtime 全量
  - [x] SubTask 8.3: 运行 compileall、双 boundary、diff check、保护路径和排序 SHA
  - [x] SubTask 8.4: 运行完整正常与对抗浏览器矩阵
  - [x] SubTask 8.5: 在唯一 FINAL-PHASE2-AUDIT 循环对最终生产文件执行一次独立 full-file review
  - [x] SubTask 8.6: 为确认 P0–P2 增加 RED 测试并修复
  - [x] SubTask 8.7: 修复后重新执行 SubTask 8.1–8.4，不重复 full-file review

- [x] Task 9: 最终收口
  - [x] SubTask 9.1: 核对完整二期十项能力矩阵全部有真实证据
  - [x] SubTask 9.2: 核对所有已迁能力不再回退旧 V2
  - [x] SubTask 9.3: 确认 `app.services`、`app.database`、Canonical 和排序内核无越界修改
  - [x] SubTask 9.4: 完成最终 handoff、测试证据和生产部署剩余清单
  - [x] SubTask 9.5: 确认未 push、未部署、未切流量
  - [x] SubTask 9.6: 确认共享工作区和所有已集成 worktree 干净
  - [x] SubTask 9.7: 只有 tasks/checklist 全勾选后标记总体 COMPLETE

- [x] Task 10: 修复 Phase 2 场景评论来源审计定位器语义漂移
  - [x] SubTask 10.1: 更新 `docs/audits/phase2-scenario-feedback/review_source_audit.md` 的当前审计结论为 approved=6、覆盖 3 个商品，并保留 approved=0 的历史来源基线说明
  - [x] SubTask 10.2: 核对 manifest 中的 audit locator 与 catalog，确保定位器指向的审计语义、批准来源集合和商品覆盖一致
  - [x] SubTask 10.3: 增加机械测试或检查，校验审计文档与 manifest 的 approved count/hash，防止两者再次漂移
  - [x] SubTask 10.4: 完成修复后复验 checkpoint，记录来源审计、manifest、catalog 和机械检查一致通过的证据

- [x] Task 11: 按规定重建稳定评论来源 ID: 当前 loader、资产和测试仅使用 Tmall feed ID；需按平台 item ID、原始 HTML SHA-256 和页面内评论序号确定性生成并验证 `source_id`。

# Task Dependencies

- Task 1 是所有后续任务的前置条件。
- Task 2、Task 3、Task 4 在 Task 1 后并行执行，分别由独立 sub-agent/worktree 拥有。
- Task 5 在 Task 2–4 任一纵向能力形成绿色提交时立即增量执行，不等待整个工作线结束。
- Task 6 随 Task 5 的能力集成逐项推进，共享前端仅由集成 owner 修改。
- Task 7 依赖 Task 2–6 全部能力集成完成。
- Task 8 依赖 Task 7 通过。
- Task 10 依赖 Task 8 最终复验通过。
- Task 9 的最终完成依赖 Task 10 修复和 checkpoint 复验通过。
- Task 11 完成并复验通过后，才能重新确认 Task 9.7 和总体 COMPLETE。
