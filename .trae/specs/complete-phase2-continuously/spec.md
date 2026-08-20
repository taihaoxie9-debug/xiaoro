# 连续完成完整二期 Spec

## Why

Day 1 共享地基只是完整二期的第一个检查点。若每个阶段完成后停止等待用户再次启动，会浪费无人值守时间，也无法在十天期限内完成轻问诊、画像、多图、OCR、场景、评论和反馈闭环。

## What Changes

- 将一个连续 Ralph Goal 作为完整二期唯一执行容器。
- Day 1 稳定化通过后自动启动 consultation-profile、multi-image-ocr、scenario-feedback 三条 worktree。
- 三条线按可独立验证的纵向能力持续提交，集成 owner 小步合并、接线和浏览器复验。
- 已迁能力通过 owner matrix 归 Guide，内部错误不得回退旧 V2。
- 每个阶段只记录 checkpoint，不标记总体 COMPLETE。
- 最终以十项二期能力矩阵、四条真实纵向链和全量审计作为完成条件。
- 不 push、不部署、不切流量，不修改保护路径。

## Impact

- Affected specs: Phase 2 共享地基、轻问诊、长期画像、图片比较、单图适配、OCR、场景导购、评论总结、避坑、反馈、SSE、商品卡、owner matrix。
- Affected code:
  - `app/guide/**`
  - `app/guide_runtime/**`
  - `app/api/v1/chat.py`
  - `app/static/chat.html`
  - `tests/guide/**`
  - `tools/guide_gates/**`
  - `docs/audits/phase2-*/**`

## ADDED Requirements

### Requirement: 连续里程碑执行

系统 SHALL 在一个 Ralph Goal 中连续执行共享稳定化、三线并行、增量集成、总体验收和最终审计。

#### Scenario: Day 1 稳定化通过
- **WHEN** 五个 P1、商品卡合同、owner matrix 和共享合同全部通过门禁
- **THEN** 系统记录 checkpoint 并立即启动三条下一阶段 worktree，不标记总体 COMPLETE

#### Scenario: 单条工作线完成一个纵向能力
- **WHEN** focused、boundary、HTTP 和真实浏览器证据通过
- **THEN** 集成 owner 小步合并该能力、接入共享 SSE/前端、复验并继续下一能力

#### Scenario: 一条工作线阻塞
- **WHEN** 该线等待独立模型、事实或用户决策
- **THEN** 其他不依赖该阻塞的工作线继续运行

#### Scenario: 用户睡醒
- **WHEN** 用户未主动要求暂停
- **THEN** 系统继续执行可运行任务

### Requirement: 审计幂等与单轮唯一审计

每个能力循环 SHALL 只在开头执行一次 full-file audit。审计身份 SHALL
由 audit profile version 和排序后的 scope file blob SHA-256 决定，不得由
commit SHA、branch、worktree 或会话 ID 决定。

#### Scenario: 相同内容已审计通过
- **WHEN** 当前 scope manifest 与已有 PASS 的 audit key 相同
- **THEN** 记录 REUSED_PASS，不再调用审计器

#### Scenario: 审计发现问题
- **WHEN** 开头审计产生确认 finding
- **THEN** 先建立 RED，再修复并运行 focused/boundary/HTTP/browser 门禁；同一循环不得再次 full-file audit

#### Scenario: 审计器不可用
- **WHEN** 独立审计器失败、超时或不可用
- **THEN** 同一 audit key 只记录一次 LOCAL_BASELINE_ONLY，主线程完成一次有界基线检查并继续所有可运行任务，不等待用户在线

#### Scenario: 最终收口
- **WHEN** 全部能力已集成并进入最终收口
- **THEN** 建立唯一 FINAL-PHASE2-AUDIT 循环并执行一次独立 full-file audit

### Requirement: 等价提交去重

集成前 SHALL 比较 stable patch ID 与最终 production blob manifest。已集成
的等价 patch/blob SHALL 记录 INTEGRATION_REUSED，不得再次 cherry-pick、
amend 或创建语义等价提交。

### Requirement: Agent Token 缓存与成本遥测

每个 checkpoint SHALL 记录平台真实提供的 cumulative、prompt、output、
cache read 和 cache write tokens。只有模型、usage 语义和价格快照齐全时
才计算命中率与成本；缺失字段 SHALL 写 UNAVAILABLE，不得估算或反推。

历史 Slice 1.7-2.0 的 26,788,605 tokens 保持权威总量，其缓存与成本拆分
SHALL 标记 UNAVAILABLE。

### Requirement: 完整二期能力矩阵

系统 SHALL 完成以下十项能力：

1. 用户画像与偏好记忆；
2. 场景导购；
3. 商品对比和避坑；
4. 评论总结；
5. 护肤轻问诊；
6. 单图商品识别；
7. 单图适配判断；
8. 两图商品对比；
9. 三到四图候选比较；
10. 商品包装和成分表 OCR。

#### Scenario: 单项能力只有单测
- **WHEN** 能力没有真实 HTTP 与浏览器闭环
- **THEN** 该能力不得勾选完成

#### Scenario: 单图识别通过
- **WHEN** 仅单图识别和找相似通过
- **THEN** 不得宣称完整二期完成

### Requirement: 轻问诊与画像

系统 SHALL 通过可观察现象形成暂定结论，并且只有用户确认的稳定信息可以进入长期画像。

#### Scenario: 用户不知道肤质
- **WHEN** 用户无法提供专业肤质标签
- **THEN** 系统询问洗脸后紧绷、T 区出油、反复泛红、刺痛和脱屑等现象，信息收集阶段展示 0 张商品卡

#### Scenario: 暂定结论
- **WHEN** 已收集足够 observations
- **THEN** 返回依据、不确定项、置信等级和停止护肤建议/就医边界

#### Scenario: 未确认结论
- **WHEN** 用户尚未确认暂定结论
- **THEN** 不写入长期画像

#### Scenario: 新一轮明确输入
- **WHEN** 本轮用户明确表达与画像冲突
- **THEN** 本轮输入优先，画像只补空且不被静默覆盖

### Requirement: 多图与 OCR

系统 SHALL 支持一到四张商品相关图片的稳定 ordinal、身份确认、适配和比较。

#### Scenario: 两图比较
- **WHEN** 两张图片均确认 Canonical 商品身份
- **THEN** 输出两张比较卡以及 winner、平局或证据不足

#### Scenario: 任一身份未确认
- **WHEN** 两图或多图中任一图片身份不确定
- **THEN** 停止比较并澄清

#### Scenario: 单图适配
- **WHEN** 图片身份确认且存在本轮、会话或画像适配上下文
- **THEN** 只展示该商品的一张卡和基于 Canonical 的适配结论

#### Scenario: OCR 观察
- **WHEN** 输入为包装或成分表
- **THEN** OCR 结果作为观察和一致性证据，不覆盖 Canonical，不增加隐藏排序分

#### Scenario: 三到四图比较
- **WHEN** 三到四张图片身份均确认
- **THEN** 按 ordinal 和确定性比较输出精确 3–4 张卡

### Requirement: 场景、评论、避坑和反馈

系统 SHALL 只使用可审计来源生成场景约束、评论摘要和避坑，并记录幂等反馈事件。

#### Scenario: 评论来源缺失
- **WHEN** 没有可审计评论 source ID
- **THEN** 不生成假评论总结

#### Scenario: 避坑
- **WHEN** 输出高/中/低风险提醒
- **THEN** 保留 severity 和 evidence refs，不推导无来源安全结论

#### Scenario: 反馈重放
- **WHEN** 同一反馈 idempotency key 重复提交
- **THEN** 只记录一次，且不直接修改商品事实或排序

### Requirement: 后端权威商品卡

系统 SHALL 通过 `CardDisplayContract` 精确决定卡片数量和顺序。

#### Scenario: 单品或适配
- **WHEN** 本轮只判断一个商品
- **THEN** 展示 1 张卡

#### Scenario: 普通推荐
- **WHEN** 本轮推荐 1–3 个商品
- **THEN** 展示后端提供的精确 1–3 张，不补卡

#### Scenario: 比较
- **WHEN** 比较 2–4 个已确认商品
- **THEN** 展示精确 2–4 张比较卡

#### Scenario: 知识、轻问诊收集、澄清或错误
- **WHEN** 本轮没有商品展示合同
- **THEN** 展示 0 张卡

### Requirement: Guide 所有权收口

系统 SHALL 只在能力实现且真实浏览器通过后将其 owner 切换为 Guide。

#### Scenario: 已迁能力内部失败
- **WHEN** Guide 已拥有的能力发生内部错误
- **THEN** 返回脱敏错误并终止，不回退旧 V2

#### Scenario: 未支持文本
- **WHEN** 输入不属于已迁能力
- **THEN** 保持 legacy owner，直到单独迁移

### Requirement: 四条真实纵向门禁

系统 SHALL 通过文本、图片、多轮和 clean runtime 四条真实纵向链。

#### Scenario: Mock 通过但浏览器失败
- **WHEN** 局部测试通过但真实 SSE、商品卡或浏览器交互失败
- **THEN** 总体保持未完成

## MODIFIED Requirements

### Requirement: Day 1 共享地基

Day 1 SHALL 继续严格执行
`docs/superpowers/plans/2026-08-09-phase2-day1-stabilization.md`，但其完成仅为 checkpoint。

#### Scenario: Day 1 全部门禁通过
- **WHEN** Day 1 子计划全部完成
- **THEN** 返回连续总控计划并立即启动三条工作线

## REMOVED Requirements

### Requirement: Day 1 完成后停止

**Reason**: 该终止点无法满足无人值守连续推进和十天完整二期目标。

**Migration**: Day 1 handoff 保留为阶段证据；总体完成状态由本规格完整 tasks/checklist 决定。
