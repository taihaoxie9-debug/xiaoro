# 连续完成 Guide 分品类数据地基 Spec

## Why

Phase 2 已完成十项能力闭环，但正式文字 Guide 只支持防晒和修护精华。Canonical
实际包含 103 个商品、39 种原始品类，而底妆、彩妆、洁面、香水等仍缺少正式
TopicCode、品类专属字段和可重复数据构建链。

当前评论来源链能验证 6 条批准评论，却没有从原始 HTML 重建 336 个候选、111 个严格
候选和人工审核队列的正式工具。继续手工改 JSONL、manifest 和审计文档会导致漂移。

## What Changes

- 新增 `skincare`、`suncare`、`base_makeup`、`color_makeup`、
  `cleanser`、`fragrance` 六个严格品类画像。
- 将 39 种 Canonical 原始品类完整且唯一映射到六个画像。
- 为每个画像定义通用字段、专属字段、不适用字段、来源政策和 capability。
- 扩展 Guide 理解、任务规划、召回、事实投影、展示和 owner 路由。
- 选定 12 个 Canonical 商品做真实试点，每个画像两个同类商品。
- 新增品类事实候选构建、人工决策 promotion 和批准资产加载链。
- 新增评论 HTML 候选构建和批准资产原子 promotion 工具。
- 未批准、缺失或冲突值保持 unknown/conflict，不产生 winner 或隐藏排序分。

## Impact

- Affected code:
  - `app/guide/understanding/**`
  - `app/guide/intent/**`
  - `app/guide/retrieval/**`
  - `app/guide/adapters/catalog/**`
  - `app/guide/decision/contracts.py`
  - `app/guide/presentation/**`
  - `app/guide/application/**`
  - `app/guide_runtime/composition.py`
  - `app/api/v1/chat.py`
  - `app/static/chat.html`
  - `tools/guide_data/**`
  - `tools/guide_gates/**`
  - `tests/guide/**`
  - `data/guide_category_facts/**`
  - `docs/audits/category-data-foundation/**`
- Protected and unchanged:
  - `app/services/**`
  - `app/database/**`
  - `data/canonical/**`
  - `app/guide/decision/deterministic_ranking.py`

## ADDED Requirements

### Requirement: 六个品类画像

系统 SHALL 定义且只定义以下正式画像：

```text
skincare
suncare
base_makeup
color_makeup
cleanser
fragrance
```

#### Scenario: 当前 Canonical 品类
- **WHEN** 加载 `data/canonical/core_products_v1.jsonl`
- **THEN** 39 种原始品类全部且仅映射到一个画像

#### Scenario: 新品类未注册
- **WHEN** Canonical 出现未映射的新原始品类
- **THEN** 构建和门禁失败，不静默回退 skincare

### Requirement: 品类字段适用性

系统 SHALL 区分通用字段、专属字段和不适用字段。

#### Scenario: 底妆字段
- **WHEN** 画像为 base_makeup
- **THEN** shade、finish、coverage、longevity、texture 可适用，香水专属字段不可适用

#### Scenario: 香水字段
- **WHEN** 画像为 fragrance
- **THEN** fragrance_family、top_notes、heart_notes、base_notes、longevity、sillage 可适用

#### Scenario: 洁面字段
- **WHEN** 画像为 cleanser
- **THEN** cleansing_form、cleansing_power、surfactant_type、rinse_behavior、double_cleanse、texture、suitable_skin 可适用

### Requirement: 字段权力边界

系统 SHALL 为每个字段声明 evidence、display、compare、hard_filter 和 soft_rank
capability。

#### Scenario: 未批准来源
- **WHEN** 字段来自 unknown、raw OCR、未批准评论或未审核营销文案
- **THEN** 该字段不得获得 display、compare、hard_filter 或 soft_rank

#### Scenario: 缺失或冲突
- **WHEN** 字段为 unknown、conflict 或 not_applicable
- **THEN** 该字段不生成值、winner、过滤结果或排序贡献

### Requirement: Canonical v1 只读

系统 SHALL 保持 Canonical v1 和确定性排序内核不变。

#### Scenario: 品类专属事实
- **WHEN** 新增批准品类事实
- **THEN** 写入 Guide 自有内容寻址 sidecar，不覆盖 Canonical identity、brand、category 或 price

### Requirement: 十二个试点

系统 SHALL 固定以下试点：

```text
skincare: 38, 91
suncare: 53, 57
base_makeup: 79, 80
color_makeup: 86, 114
cleanser: 69, 103
fragrance: 120, 121
```

#### Scenario: 试点字段没有批准来源
- **WHEN** 某个适用字段没有独立批准事实
- **THEN** 覆盖报告记录 unknown，不为完成率生成值

### Requirement: 品类事实候选构建

系统 SHALL 从 source manifest、HTML、OCR JSON 或官方结构化资料生成确定性 pending
候选。

#### Scenario: 重复执行
- **WHEN** 输入内容相同但文件顺序不同
- **THEN** candidate JSONL 字节和 SHA-256 完全相同

#### Scenario: 自动化执行
- **WHEN** 候选构建完成
- **THEN** 所有候选状态为 pending 或 quarantine，不得出现 approved_fact

### Requirement: 人工批准与原子 promotion

系统 SHALL 只接受带 reviewer、timezone-aware reviewed_at、decision 和 reason 的显式
审核决定。

#### Scenario: 决策不完整
- **WHEN** 审核决定缺少 reviewer、时间或原因
- **THEN** promotion 失败且旧生产资产不变

#### Scenario: promotion 成功
- **WHEN** candidate、decision、产品归属、字段适用性和 hash 全部有效
- **THEN** 原子生成 facts JSONL 和 manifest，并通过生产 loader 自校验

#### Scenario: 没有新人工批准
- **WHEN** 12 个试点没有新的完整人工批准决定
- **THEN** 生成 `fact_count=0` 的合法 manifest，reader 正常加载，专属字段保持 unknown

### Requirement: 评论候选重建

系统 SHALL 提供从原始 HTML 重建评论 pending/quarantine 候选的离线工具。

#### Scenario: 当前批准来源复验
- **WHEN** 使用提交的脱敏 fixture 和既有批准资产
- **THEN** 构建器结果字节稳定，且现有 6 条批准资产完全不变

#### Scenario: 历史原始 HTML 不可用
- **WHEN** 当前环境没有 hash 锁定的三份原始 HTML
- **THEN** 336/111 只保留为历史审计 provenance，不得宣称本轮已真实重跑

#### Scenario: 自动批准
- **WHEN** 只有 HTML 候选、没有显式人工决定
- **THEN** 工具不得产生批准评论

### Requirement: 六类正式 Guide 行为

系统 SHALL 让六类自然语言请求进入 Guide 正式链。

#### Scenario: 正常推荐
- **WHEN** 用户请求六类中任一品类
- **THEN** 返回 Guide typed SSE、后端权威 1–3 卡和明确字段缺失状态

#### Scenario: Guide 内部错误
- **WHEN** 已迁品类内部失败
- **THEN** 返回脱敏单终态错误，不回退 legacy

### Requirement: 连续动态并发执行

系统 SHALL 使用 2–8 个 Agent 自适应并发、单 Integration Writer 和独立只读审计。

#### Scenario: 文件域独立且门禁稳定
- **WHEN** 最近两个 checkpoint 绿色且 worktree 文件域不重叠
- **THEN** 可逐个增加 Agent，最多 8 个

#### Scenario: 共享冲突或未知回归
- **WHEN** 共享文件冲突、未知测试失败或审计 finding 出现
- **THEN** 降至 2–3 个 Agent，执行 freeze、RED、单 writer fix、独立验证

### Requirement: 唯一最终审计

系统 SHALL 在所有能力集成后执行一次 `FINAL-CATEGORY-DATA-AUDIT`。

#### Scenario: 确认 finding
- **WHEN** 最终审计发现 P0–P2
- **THEN** 先增加 RED，再由独立 writer 修复并重跑正常门禁；同一 audit key 不重复 full-file audit

## MODIFIED Requirements

### Requirement: Guide 文本品类所有权

原来只支持 sunscreen 和 serum。修改后，六个画像均在正式 HTTP/SSE 和浏览器中由 Guide
拥有。

### Requirement: 评论批准资产

原来只有严格 loader。修改后增加 pending 构建与显式 promotion，但现有 6 条批准评论和
稳定 source ID 语义保持不变。

## REMOVED Requirements

### Requirement: 未知品类默认 skincare

**Reason**: 这会把香水、彩妆和清洁字段错误套入护肤语义。

**Migration**: 所有当前 Canonical 品类进入显式映射；未来未映射品类在构建期失败。

## Completion Boundary

Phase 3A 只有在以下条件全部满足时完成：

1. 六画像和 39/39 映射通过；
2. 字段来源与 capability 门禁通过；
3. 12 个试点 approved/unknown/conflict 可复验；
4. 品类事实和评论候选均可重复构建并原子 promotion；
5. 六类正式 HTTP/SSE/browser 行为通过；
6. Guide full、runtime full、双 boundary、compileall 和 diff check 通过；
7. 保护路径无差异且排序 SHA 不变；
8. 唯一最终审计无未解决 P0–P2；
9. tasks/checklist 全勾选、工作区干净；
10. 未 push、未部署、未切流。
