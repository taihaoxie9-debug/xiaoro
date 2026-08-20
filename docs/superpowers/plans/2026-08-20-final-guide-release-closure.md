# XiaoRo Final Guide Release Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不增加句子补丁、商品 ID 特判或第三个模型的前提下，统一小 ro 导购的职责裁决、事实准入、润写依据和前端渲染，补齐 79 款商品的人工审核内容资产，并以真实 DeepSeek、真实后端和真实浏览器门禁完成上线收口。

**Architecture:** 先按品类采集 79 款商品的真实原始资料，由主 Agent 逐商品、逐长图人工审核，并发布 `map / leave_free / reject`、SKU/规格/价格和父子概念资产；之后 TurnMeaning 继续作为唯一开放语言翻译层，自然语言操作归一到 `职责 × 对象数量 × 对象类型 × 当前状态` 真值表，再产生唯一 `PresentationContract`。后端负责决定公开区块、比较维度、商品事实、底部 Tag 和事实依据；润写模型只改写后端批准的公开事实并回传依据 ID；前端只渲染合同，不再自行拼推荐理由、适配状态、完整功效或原始证据。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLite CAS state、typed SSE、DeepSeek V4 Pro、Playwright Chromium、pytest、SMZDM Wiki raw capture、人工事实审核、SelectionConceptProjection。

---

## 0. Working Boundary And Release Invariants

### 0.1 Repository boundary

实现仓库：

```text
/Users/bytedance/Desktop/xiaoro-fresh
```

参考仓库：

```text
/Users/bytedance/Desktop/xiaoro-shopping-master
```

所有代码、测试、数据资产与发布操作只发生在 `xiaoro-fresh`。参考仓库不得被当作实现目标，也不得把参考仓库的未审计数据复制进正式资产。

### 0.2 Current evidence

当前已经确认：

```text
typed router:
  36 条有向边
  216 条三段路径
  8 条长链
  ordinary_path_pollution = 0

现有父子概念：
  concept_count = 50
  projection_count = 188
  map = 188
  leave_free = 3

SMZDM：
  正式抓取范围 = 79 款
  raw_pages = 79
  human_reviews = 79
  terminal_reviews = 79
  human_review_complete = 70
  no_promotion = 9
  approved facts = 264
  rejected facts = 72
  manually inspected detail images = 437

正式分类事实：
  total facts = 508
  reviewed promoted fields = 259
  map field groups = 101
  leave_free field groups = 158

真实 5×4 小灶历史：
  copy_source=model = 21
  copy_source=fallback = 24
  validation:hard_fact = 18
  validation:attribution = 3
  medical_escalation = 3
```

### 0.3 Hard rules

以下规则不可通过配置、演示开关或人工口径绕过：

```text
1. 严禁按失败原句增加关键词、同义词、正则或 Prompt 特判。
2. 严禁按商品 ID 增加路由、比较、润写或展示特判。
3. 严禁用正则扫描数字/成分作为事实权限的主要裁判。
4. 严禁把 SMZDM 整页、OCR 原文、用户口碑或 AIGC 建议直接提升为正式事实。
5. 严禁未对齐 SKU/规格时把抓取价格和规格组合展示。
6. 严禁 SKU/规格未对齐时把带规格的卖点整句作为通用商品推荐理由；此类事实只能使用已审核的结构化投影，规格字段必须等 SKU 对齐后单独展示。
7. 严禁前端根据 category_facts、description 或 rerank_reason 自行拼业务文案。
8. 严禁 PresentationContract 存在时再把 MessageEvent 当作第二份公开正文。
9. 严禁 GUIDE_DEMO_RELAX_COPYWRITER_VALIDATION 冒充生产通过。
10. 任何真实题失败必须先定位最早错误层，再修改共享职责。
11. 关键架构、事实批准、失败定层和最终发布由主 Agent 复核；子 Agent 可并行收集证据、跑独立测试和整理候选，但不得独立批准事实或决定生产修复。
12. 所有“真实”门禁必须与计划上线的生产配置同构：同一 DeepSeek 模型、同一 Prompt、零格式修复、零重试、同一职责矩阵、同一数据资产、同一 SSE、同一前端构建和同一浏览器入口。不得用 FrozenUnderstanding、mock provider、手工注入 TurnMeaning、关闭 copywriter、放宽校验或零 API 回放替代最终真实结论。
13. 首批 48 个真实模型/后端回合只是最小门槛，不是测试上限。若出现低分或严重错误，必须完成最早错误层审计和共享修复，再追加新的、未见过的 48 回合生产同构批次；可重复追加，直到严重错误归零、关键轨迹全通过且主 Agent 能给出明确上线判断。
14. 真实模型调用是受控成本，不得用连续改 Prompt 后重跑来探索问题。任一真实调用出现硬失败、copywriter fallback 或门禁合同矛盾时，立即停止后续 API 调用，保存证据；但不得停工等待。主 Agent 必须继续完成最早错误层审计、共享结构修复、局部测试和零 API 回放，并在正常进度更新中写明：失败样本、最早错误层、现有合同为何不一致、拟修改的共享 owner、零 API 验证结果和下次调用上限。只有完成这些本地证明后才能发起下一批真实调用。
15. Prompt 只能表达已经由后端类型合同决定的结构，不能承担修复职责。不得以“再加一句 Prompt”处理事实位置、区块存在性、覆盖率、归因范围、责任路由或展示所有权问题；这些必须先修改后端合同、编译器或校验器。
16. 后端合同改变后可以同步更新 Prompt，使模型按该合同返回格式；这不是补丁。真实输出若仍与合同矛盾，先审计合同、编译器、校验器和事实边界，严禁再次改 Prompt 试探。只有完成本地审计后仍无法定位唯一最早 owner，或发现两个已发布合同彼此冲突时，才暂停并与用户讨论。
```

### 0.4 Failure-layer protocol

每个真实失败必须保存：

```json
{
  "message": "原始用户输入",
  "turn_meaning": {},
  "object_cardinality": "two_or_three",
  "object_type": "candidate_ordinals",
  "starting_state": "recommendation_batch",
  "references": [],
  "bindings": [],
  "processor": "comparison",
  "presentation_mode": "comparison",
  "presentation_contract": {},
  "final_dom_audit": {},
  "earliest_failure_layer": "semantic_admission"
}
```

允许的最早错误层：

```text
model_translation
semantic_admission
identity_binding
responsibility_resolution
state_transition
decision_execution
data_coverage
copy_evidence_validation
presentation_contract
frontend_rendering
```

只有定位到最早错误层后才能修复。修复必须覆盖：

```text
至少两个不同说法
至少一个反例
至少一个不同当前状态
provider-parser 隔离
零 API 回放
```

### 0.5 Copywriter contract and cost-control amendment

当前公开展示路径已经收束为：

```text
PublicPresentationContract
→ sections / comparison_rows / compact_tags / card_display
→ Guide 前端纯合同渲染
```

前端不得从旧业务字段补写内容；该边界已完成。当前未收口的是**后端
内部的 copywriter 输入输出合同**：旧 `CopywriterDraft` 固定要求
`summary_copy + product_copy + closing_copy`，但最终 `section_order`
在 comparison、single_product_suitability、product_knowledge、image_identity
等职责下并不展示这些通用作文区块。不得再通过 Prompt 增补规则维持该旧形状。

门禁判定必须区分三类情况：

```text
必须继续严格：
  事实 ID 不存在、跨商品引用、事实出现在未授权公开位置、
  SKU 未对齐事实进入通用推荐、归因丢失、内部语言、硬事实泄漏、
  错误职责、错误比较维度、错误展示合同。

已确认的过严规则，必须删除：
  1. 最终 section_order 没有 closing，却要求模型返回 closing。
  2. 把同一个公开商品项的 positioning 和 advisor_reason 拆开，
     分别要求重复 merchant/consumer 归因。
  3. 把所有 allowed_soft_fact_ids 当成“本轮必须说完”的覆盖率分母。

正确覆盖率：
  allowed facts = 本轮允许引用的事实全集；
  required dimensions = 当前职责和用户问题要求公开回答的维度；
  只校验最终可见 section 对 required dimensions 的最小覆盖，
  不要求模型罗列所有允许事实，不为凑覆盖率堆料。

compact tags 的职责：
  compact_tag_evidence -> 后端最多三个短 Tag -> 底部通用商品卡；
  它只负责 UI 索引、展示上限和事实 ID 可追溯性；
  每个 Tag 必须恰为 2-4 个字符；不截断、不缩写营销长句，
  找不到合格短标签时宁可少于三个；
  它不是模型输入，也不是模型文案的事实全集或覆盖率分母。
  模型文案必须按完整 approved_soft_facts + required dimensions 裁判；
  比较表可复用同一批准事实，但比较维度仍由后端决定。
```

本次已经发生的真实 copywriter 调用只可作为失败证据，不得冒充通过：

```text
v3 = 20 calls
v4 = 20 calls
v5 = 12 calls before user interruption
```

从本 amendment 生效起，禁止继续对同一问题做 Prompt-only 真实重跑。
现有未提交的 v10-v12 prompt wording 仅作为诊断记录；最终实现必须由
下方 Task 12.5 的 typed contract 取代它们。仅保留已证明为合同正确性的
两项机械修正：closing 要求从 section_order 派生；同一商品公开项的归因
按整个项而非其内部两个字段分别判断。

### 0.6 Authoritative data-first execution order

任务章节的数字用于稳定引用，**不代表执行顺序**。实现必须严格按以下阶段推进：

```text
Phase A  Task 1
  冻结脏工作树基线与反补丁门禁

Phase B  Task 9
  先定义每个品类该抓什么、什么能审核、什么必须拒绝

Phase C  Task 10
  采集 79 款 SMZDM 原始资料并由主 Agent 人工审核
  有长图：逐图查看并拆 3-5 条候选
  无长图：如实记录，转参数/商品介绍，不伪造缺失内容

Phase D  Task 11
  提升人工批准的商品事实
  完成 SKU/规格/参考价分离
  完成 map / leave_free / reject
  发布父概念/子概念资产与定向召回

Phase E  Task 2
  在已发布真实概念资产上实现四维职责真值表

Phase F  Tasks 3-8
  实现唯一公开展示合同、比较维度、compact tags、
  依据 ID 校验、单一公开文案路径和纯合同前端

Phase G  Tasks 12-16
  focused 机械门禁
  Task 12.5：模型润写合同按唯一展示合同收口
  本地证明与 cost preflight 后的一次有上限 smoke
  真实 DeepSeek
  真实后端 SSE
  真实桌面/移动浏览器
  最终一次全量回归与发布
```

强制依赖：

```text
Task 9 -> Task 10 -> Task 11 -> Task 2 -> Tasks 3-8
```

在 Task 11 发布审核后的真实事实与概念资产之前：

```text
允许：
  只读审计职责矩阵、展示合同和前端现状
  设计测试夹具
  收集失败证据

禁止：
  用当前薄数据拍脑袋固化比较行
  用临时文案固化 compact tags
  为缺数据增加 fallback 句子或商品 ID 特判
  提前修改生产职责、润写权限和前端展示逻辑
```

这样保证后续矩阵、比较维度、Tag 和润写依据消费真实审核资产，
而不是先造一套薄数据合同，再由前端和模型各自补一轮。

---

## 1. Locked Public Responsibilities

### 1.1 Open-language operations vs terminal responsibilities

自然语言操作可继续包含：

```text
recommendation
comparison
suitability
knowledge
assessment
followup
image_identity
image_similarity
clarification
```

最终渲染职责只保留：

```text
recommendation
comparison
single_product_suitability
product_knowledge
general_knowledge
consultation
image_identity
clarification_or_error
```

归一规则：

```text
image_similarity  -> recommendation
image_comparison  -> comparison
image_suitability -> single_product_suitability
budget/skin revision -> recommendation
followup -> 根据对象与问题目标落到 recommendation / comparison /
            single_product_suitability / product_knowledge /
            general_knowledge / consultation
```

前端不得重新执行这些归一规则。

### 1.2 Locked rendering format

#### Recommendation

```text
摘要
→ 每款嵌入卡与商品说明
→ 小 ro 推荐理由
→ 综合选择建议
→ 本轮提到的商品
```

#### Comparison

```text
摘要
→ 对比表
→ 本轮提到的商品
```

比较页禁止：

```text
对比表后重复两张嵌入商品卡
对比表后重复综合推荐长段
底部通用卡重复推荐理由
```

比较表规则：

```text
第一行固定：品牌主打
中间行：本轮明确比较的受控维度
最后一行固定：参考价
```

示例：

```text
“质地、修护方向和价格”
-> 品牌主打 / 修护方向 / 质地 / 参考价

“白天通勤怕闷，哪个适合”
-> “怕闷”映射到 texture.refreshing
-> 品牌主打 / 清爽 / 参考价
```

#### Single-product suitability

```text
摘要一句
→ 使用判断一句
→ 本轮提到的商品
```

禁止嵌入商品大卡和“小 ro 推荐理由”。

#### Product knowledge

```text
直接回答一句
→ 商品资料一句
→ 本轮提到的商品
```

禁止嵌入商品大卡、推荐理由、适配结论和原始证据。

#### General knowledge / Consultation / Clarification

没有绑定商品时不显示商品卡。

### 1.3 Locked compact product shelf

所有有商品的底部货架统一标题：

```text
本轮提到的商品
```

每张通用卡只允许：

```text
display_name
reference_price + specification
0-3 个 compact_tags
商品图
收藏
商品链接
```

禁止：

```text
推荐理由
适配待确认
匹配分
完整功效列表
description
rerank_reason
前端生成的肤感/成分/功效句
```

### 1.4 Public-language rule

用户可见正文禁止以下内部机械语言：

```text
当前资料
已审核
已核验
页面
证据
原文
商家宣传
营销长图
没有可核验
内部规则
候选 ID
事实 ID
```

自然缺失表达：

```text
“这款没有明确的质地描述，暂不判断。”
“这款没有明确的用法说明，暂不补充使用步骤。”
```

`品牌主打` 可作为公开商品标签；不得再叠加“品牌宣称”“未经独立核实”等后台审计口径。

---

## 2. File Responsibility Map

### New files

```text
app/guide/intent/responsibility_matrix.py
  四维职责真值表与 terminal responsibility 解析。

app/guide/presentation/public_contracts.py
  唯一公开展示合同：职责、比较行、compact tags、公开 copy block。

app/guide/presentation/public_language_policy.py
  公开机械语言拦截；不承担数字/事实权限判断。

app/guide/presentation/copy_evidence_validation.py
  基于事实 ID、商品归属和展示位置的润写依据校验。

app/guide/presentation/comparison_planning.py
  将用户比较维度、概念约束和商品事实投影成稳定对比行。

app/guide/presentation/compact_tag_planning.py
  由后端生成最多三个有事实依据的底部 Tag。

tools/guide_data/smzdm_category_policy.py
  六个品类的抓取字段与审核准入规则。

tools/guide_data/review_smzdm_product.py
  生成单商品人工审核包；不自动批准。

tools/guide_data/promote_reviewed_product_facts.py
  只提升主 Agent 人工批准的事实。

tools/guide_data/publish_selection_parent_concepts.py
  读取人工 review，调用 hash-locked concept publisher。

tools/guide_gates/build_responsibility_matrix.py
  生成职责 × 数量 × 类型 × 状态的机械夹具。

tools/guide_gates/run_final_release_gate.py
  聚合 focused、真实模型、后端和浏览器发布门禁。

tests/fixtures/guide/responsibility_matrix/
  四维真值表、反例和长链夹具。

docs/audits/final-release/
  真实后端、浏览器、失败定层和发布总结。
```

### Modified files

```text
app/guide/understanding/exact_parsing.py
  多个合法序号保留为对象集合，不在解析层过早判歧义。

app/guide/intent/executable_intent_compiler.py
  把引用集合交给职责矩阵，不按 operation 单独消歧。

app/guide/intent/unified_turn_router.py
  只消费职责矩阵结果；删除对象基数的散落分支。

app/guide/application/unified_guide_flow.py
  把 TurnMeaning、bindings、state 交给职责矩阵。

app/guide/application/text_recommendation_flow.py
app/guide/application/image_recommendation_flow.py
  统一构建 PublicPresentationContract，不再输出第二份公开答案。

app/guide/presentation/contracts.py
  ProductCard 增加 display_name、specification 和 compact_tags。

app/guide/presentation/copywriter_contracts.py
  每个公开文本块携带 used_fact_ids / used_constraint_ids。

app/guide/presentation/copywriter_prompt.py
  输出带依据小票的严格 JSON；不再让模型决定展示布局。

app/guide/presentation/presentation_packet.py
  只向模型投放当前职责允许的事实。

app/guide/presentation/presentation_compiler.py
  编译唯一展示合同；失败时使用同一结构 fallback。

app/guide/presentation/copywriter_validation.py
  保留 markup、安全承诺和内部语言检查；移除数字猜测式权限裁决。

app/guide/application/product_evidence_answer.py
app/guide/application/general_knowledge_answer.py
  不再把 exact_text 作为公开正文。

app/static/guide-presentation.js
  只渲染 PublicPresentationContract。

app/static/chat.html
  底部卡不再自行拼推荐理由、适配状态或完整字段。
```

### Focused tests

```text
tests/guide/intent/test_responsibility_matrix.py
tests/guide/intent/test_executable_intent_compiler.py
tests/guide/intent/test_unified_turn_router.py
tests/guide/presentation/test_public_contracts.py
tests/guide/presentation/test_comparison_planning.py
tests/guide/presentation/test_compact_tag_planning.py
tests/guide/presentation/test_copy_evidence_validation.py
tests/guide/application/test_text_presentation_integration.py
tests/guide/application/test_image_presentation_integration.py
tests/guide/runtime/test_frontend_mode_matrix.py
tests/guide/runtime/test_frontend_presentation_stream.py
tests/guide/runtime/test_frontend_card_binding.py
tests/guide/data/test_smzdm_category_policy.py
tests/guide/data/test_smzdm_review_candidates.py
tests/guide/data/test_selection_parent_concept_assets.py
tests/guide/tools/test_final_release_gate.py
```

---

## Task 1 (Phase A): Freeze Baseline And Add Anti-Patch Gates

**Files:**
- Create: `tests/guide/tools/test_no_sentence_patch.py`
- Create: `docs/audits/final-release/baseline-v1.json`
- Modify: `docs/superpowers/plans/2026-08-20-final-guide-release-closure.md`

- [x] **Step 1: Record the dirty baseline without reverting user work**

Run:

```bash
cd /Users/bytedance/Desktop/xiaoro-fresh
git status --short
git diff --stat
git rev-parse HEAD
```

Write `baseline-v1.json` with:

```json
{
  "head": "9e992b6cf7badc2b5eb1cbc22771bfa19dcbf1a0",
  "branch": "mixed-chain-experience-20260819",
  "protected_user_changes": true,
  "implementation_scope": [
    "responsibility_matrix",
    "presentation_contract",
    "copy_evidence",
    "smzdm_reviewed_facts",
    "release_gates"
  ]
}
```

- [x] **Step 2: Add a test that blocks new sentence patches**

Create:

```python
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = (
    "app/guide/intent",
    "app/guide/application",
)


def test_release_change_does_not_add_sentence_owned_action_rules() -> None:
    diff = subprocess.run(
        ["git", "diff", "-U0", "HEAD", "--", *PRODUCTION],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    prohibited = (
        "第一款和第二款",
        "第一张和第二张",
        "哪个更适合",
        "product_id ==",
    )
    added = "\n".join(
        line[1:] for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    assert not any(token in added for token in prohibited)
```

- [x] **Step 3: Run the anti-patch gate**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/tools/test_no_sentence_patch.py -q
```

Expected: PASS before and after every shared-layer repair.

- [x] **Step 4: Commit the baseline gate**

```bash
git add \
  tests/guide/tools/test_no_sentence_patch.py \
  docs/audits/final-release/baseline-v1.json \
  docs/superpowers/plans/2026-08-20-final-guide-release-closure.md
git commit -m "test(guide): freeze final release repair boundaries"
```

---

## Task 2 (Phase E): Create The Four-Dimensional Responsibility Matrix

> **Data dependency:** 仅在 Tasks 9-11 完成并发布审核后的事实与概念资产后实施。本任务可提前只读审计，但不得提前修改生产职责代码。

**Files:**
- Create: `app/guide/intent/responsibility_matrix.py`
- Create: `tests/guide/intent/test_responsibility_matrix.py`
- Create: `tools/guide_gates/build_responsibility_matrix.py`
- Create: `tests/guide/tools/test_responsibility_matrix.py`
- Create: `tests/fixtures/guide/responsibility_matrix/truth.jsonl`
- Modify: `app/guide/understanding/exact_parsing.py`
- Modify: `app/guide/intent/executable_intent_compiler.py`
- Modify: `app/guide/intent/unified_turn_router.py`

- [x] **Step 1: Write the matrix contracts**

Create:

```python
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict


class Responsibility(str, Enum):
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    SINGLE_PRODUCT_SUITABILITY = "single_product_suitability"
    PRODUCT_KNOWLEDGE = "product_knowledge"
    GENERAL_KNOWLEDGE = "general_knowledge"
    CONSULTATION = "consultation"
    IMAGE_IDENTITY = "image_identity"
    CLARIFICATION = "clarification"
    SAFETY_ESCALATION = "safety_escalation"


ObjectCardinality = Literal[
    "zero",
    "one",
    "two_or_three",
    "over_limit",
    "unresolved",
]
ObjectType = Literal[
    "none",
    "candidate_ordinals",
    "current_batch",
    "current_product",
    "explicit_products",
    "image_ordinals",
    "confirmed_images",
    "topic",
]
DialogueState = Literal[
    "empty",
    "recommendation_batch",
    "single_product_focus",
    "comparison_batch",
    "consultation",
    "general_knowledge",
    "confirmed_image_product",
    "pending_clarification",
    "safety_escalation",
]


class ResponsibilityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    responsibility: Responsibility
    processor: str
    presentation_mode: str
    preserve_product_order: bool
    clarification_code: str | None = None
```

- [x] **Step 2: Write failing rows for the known gap**

```python
def test_two_candidate_ordinals_plus_suitability_resolves_comparison():
    result = resolve_responsibility(
        operation="suitability",
        cardinality="two_or_three",
        object_type="candidate_ordinals",
        dialogue_state="recommendation_batch",
        safety=False,
    )
    assert result.responsibility is Responsibility.COMPARISON


def test_two_image_ordinals_plus_suitability_resolves_comparison():
    result = resolve_responsibility(
        operation="suitability",
        cardinality="two_or_three",
        object_type="image_ordinals",
        dialogue_state="confirmed_image_product",
        safety=False,
    )
    assert result.responsibility is Responsibility.COMPARISON


def test_one_candidate_plus_suitability_remains_single_product():
    result = resolve_responsibility(
        operation="suitability",
        cardinality="one",
        object_type="candidate_ordinals",
        dialogue_state="recommendation_batch",
        safety=False,
    )
    assert result.responsibility is Responsibility.SINGLE_PRODUCT_SUITABILITY
```

- [x] **Step 3: Run the tests and verify RED**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/intent/test_responsibility_matrix.py -q
```

Expected: FAIL because `resolve_responsibility` is not implemented.

- [x] **Step 4: Implement table-driven responsibility resolution**

The implementation must use typed keys:

```python
_RULES = {
    ("suitability", "one"): Responsibility.SINGLE_PRODUCT_SUITABILITY,
    ("suitability", "two_or_three"): Responsibility.COMPARISON,
    ("comparison", "two_or_three"): Responsibility.COMPARISON,
    ("knowledge", "one"): Responsibility.PRODUCT_KNOWLEDGE,
    ("knowledge", "zero"): Responsibility.GENERAL_KNOWLEDGE,
    ("assessment", "zero"): Responsibility.CONSULTATION,
    ("image_identity", "one"): Responsibility.IMAGE_IDENTITY,
}
```

Safety escalation is evaluated before `_RULES`. `over_limit` and `unresolved` return clarification. `followup` must be normalized from its bound object set and question goal before table lookup; it must not become a ninth rendering responsibility.

- [x] **Step 5: Preserve multiple ordinal references in exact parsing**

Change `_parse_ordinal_references` so that:

```text
one ordinal       -> one ReferenceDraft
two/three ordinals -> ordered ReferenceDraft values
four or more       -> over-limit issue
out-of-range       -> reference issue
```

Do not emit `ambiguous_candidate_reference` merely because there are two distinct valid ordinals.

Add:

```python
def test_exact_parser_preserves_two_candidate_ordinals():
    constraints, issues = parse_exact_constraints(
        "第一款和第二款哪个更适合我"
    )
    refs = [
        item for item in constraints
        if isinstance(item, ReferenceDraft)
    ]
    assert [(item.kind, item.ordinal) for item in refs] == [
        ("candidate_ordinal", 1),
        ("candidate_ordinal", 2),
    ]
    assert not issues
```

- [x] **Step 6: Generate the full legal truth table**

`build_responsibility_matrix.py` must generate rows over:

```text
operation × cardinality × object_type × dialogue_state × safety
```

Invalid combinations must be explicitly marked `invalid_input`; do not silently omit them.

Required coverage assertions:

```python
assert all(row["expected_responsibility"] for row in legal_rows)
assert any(
    row["operation"] == "suitability"
    and row["object_type"] == "candidate_ordinals"
    and row["cardinality"] == "two_or_three"
    for row in legal_rows
)
assert any(
    row["operation"] == "suitability"
    and row["object_type"] == "image_ordinals"
    and row["cardinality"] == "two_or_three"
    for row in legal_rows
)
```

- [x] **Step 7: Preserve objects in compiler; resolve once in router**

`compile_turn_meaning()` 没有绑定结果和当前对话状态，因此只负责完整保留
typed object set。`route_unified_turn()` 在 identity binding 完成后把
operation、cardinality、object type、dialogue state 和 safety 一次性交给
共享矩阵，并把 terminal responsibility 与 presentation mode 写入
`UnifiedRouteDecision`。应用层只校验/消费该结果，不再根据
`UnderstandingGoal` 二次裁决。

Remove scattered object-count branches such as:

```python
if operation == "suitability" and len(bindings) >= 2:
    return "comparison"
```

The router receives `ResponsibilityDecision` and only verifies the required binding count and safety invariants.

- [x] **Step 8: Run focused matrix tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/understanding/test_exact_parsing.py \
  tests/guide/intent/test_executable_intent_compiler.py \
  tests/guide/intent/test_responsibility_matrix.py \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/tools/test_responsibility_matrix.py -q
```

Expected: PASS.

- [x] **Step 9: Commit the matrix**

```bash
git add \
  app/guide/intent/responsibility_matrix.py \
  app/guide/understanding/exact_parsing.py \
  app/guide/intent/executable_intent_compiler.py \
  app/guide/intent/unified_turn_router.py \
  tools/guide_gates/build_responsibility_matrix.py \
  tests/fixtures/guide/responsibility_matrix \
  tests/guide/understanding/test_exact_parsing.py \
  tests/guide/intent/test_executable_intent_compiler.py \
  tests/guide/intent/test_responsibility_matrix.py \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/tools/test_responsibility_matrix.py
git commit -m "feat(guide): resolve turns through responsibility matrix"
```

---

## Task 3 (Phase F): Define The Unique Public Presentation Contract

**Files:**
- Create: `app/guide/presentation/public_contracts.py`
- Create: `app/guide/retrieval/product_display_assets.py`
- Create: `tools/guide_data/publish_reviewed_product_displays.py`
- Create: `docs/audits/smzdm-data/reviewed-product-displays-v1.jsonl`
- Create: `data/guide_product_display_bindings/v1/*`
- Create: `tests/guide/presentation/test_public_contracts.py`
- Create: `tests/guide/data/test_product_display_assets.py`
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/presentation_compiler.py`

- [x] **Step 1: Define comparison rows and compact tags**

```python
class FactRef(BaseModel):
    fact_id: str
    product_id: int | None
    source_refs: tuple[str, ...]


class ComparisonCell(BaseModel):
    product_id: int
    value: str
    fact_ids: tuple[str, ...]
    state: Literal["known", "unknown", "conflict"]


class ComparisonRow(BaseModel):
    dimension_id: str
    label: str
    cells: tuple[ComparisonCell, ...]


class CompactTag(BaseModel):
    product_id: int
    label: str
    fact_ids: tuple[str, ...]


class PublicPresentationContract(BaseModel):
    responsibility: Responsibility
    mode: PresentationMode
    sections: tuple[PresentationSection, ...]
    comparison_rows: tuple[ComparisonRow, ...] = ()
    visible_product_ids: tuple[int, ...] = ()
    compact_tags: tuple[CompactTag, ...] = ()
    telemetry: CopywriterTelemetry
```

Validators:

```text
comparison -> summary + comparison rows + full_cards
single_product_suitability -> summary + judgement + full_cards
product_knowledge -> summary + answer + full_cards
recommendation -> summary + product sections + closing + full_cards
compact_tags <= 3 per visible product
comparison rows preserve visible product order
```

- [x] **Step 2: Add RED tests for locked layouts**

```python
def test_comparison_forbids_product_sections_after_table():
    with pytest.raises(ValueError):
        PublicPresentationContract(
            responsibility="comparison",
            mode="comparison",
            sections=(
                summary_section(),
                comparison_section(),
                product_section(product_id=38),
                full_cards_section(),
            ),
            ...
        )


def test_product_knowledge_forbids_advisor_reason():
    with pytest.raises(ValueError):
        PublicPresentationContract(
            responsibility="product_knowledge",
            sections=(
                summary_section(),
                answer_section(advisor_reason="推荐它"),
                full_cards_section(),
            ),
            ...
        )
```

- [x] **Step 3: Split display name from specification**

Add `display_name` and `compact_tags` to `ProductCard`.

Hard rule:

```text
ProductCard.display_name must not be derived in JavaScript.
ProductCard.specification remains a separate typed field.
Price formatting combines price + specification.
```

For product 91, audit the SKU binding before publishing:

```text
If ¥88 is proven to belong to 50ml -> display ¥88 / 50ml.
If not proven -> do not combine ¥88 and 50ml.
```

No regex stripping of `50ml` is allowed in the frontend. The canonical display record must supply:

```json
{
  "display_name": "玉泽皮肤屏障修护精华乳",
  "specification": "50ml"
}
```

The 79 public names and display specifications are reviewed separately in
`reviewed-product-displays-v1.jsonl`. The publisher requires exact product
coverage and verifies every source review SHA before producing the
hash-locked runtime sidecar. It performs no name-cleaning inference.

- [x] **Step 4: Change section order by terminal responsibility**

```python
_SECTIONS_BY_RESPONSIBILITY = {
    Responsibility.RECOMMENDATION: (
        "summary", "product*", "closing", "full_cards"
    ),
    Responsibility.COMPARISON: (
        "summary", "comparison", "full_cards"
    ),
    Responsibility.SINGLE_PRODUCT_SUITABILITY: (
        "summary", "judgement", "full_cards"
    ),
    Responsibility.PRODUCT_KNOWLEDGE: (
        "summary", "answer", "full_cards"
    ),
    Responsibility.GENERAL_KNOWLEDGE: ("general_knowledge",),
    Responsibility.CONSULTATION: ("observation", "summary"),
    Responsibility.IMAGE_IDENTITY: ("observation", "full_cards"),
    Responsibility.CLARIFICATION: ("question",),
}
```

- [x] **Step 5: Compile exactly one public contract**

`PresentationCompiler.compile()` returns only `PublicPresentationContract`.

`MessageEvent` remains a transport compatibility field for non-Guide consumers, but Guide frontend must not render it when a valid public contract exists.

- [x] **Step 6: Run focused contract tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/presentation/test_public_contracts.py \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/presentation/test_presentation_compiler.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py -q
```

Expected: PASS.

- [x] **Step 7: Commit the public contract**

```bash
git add \
  app/guide/presentation/public_contracts.py \
  app/guide/presentation/contracts.py \
  app/guide/presentation/copywriter_contracts.py \
  app/guide/presentation/presentation_packet.py \
  app/guide/presentation/presentation_compiler.py \
  tests/guide/presentation/test_public_contracts.py \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/presentation/test_presentation_compiler.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py
git commit -m "feat(presentation): add single public presentation contract"
```

---

## Task 4 (Phase F): Plan Comparison Rows From Requested Concepts

**Files:**
- Create: `app/guide/presentation/comparison_planning.py`
- Create: `tests/guide/presentation/test_comparison_planning.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/image_recommendation_flow.py`

- [x] **Step 1: Write RED tests for requested dimensions**

```python
def test_explicit_dimensions_build_brand_repair_texture_price_rows():
    rows = plan_comparison_rows(
        requested_dimensions=("efficacy.repair", "texture", "reference_price"),
        product_ids=(91, 38),
        ...
    )
    assert [row.label for row in rows] == [
        "品牌主打",
        "修护方向",
        "质地",
        "参考价",
    ]


def test_stuffy_commute_maps_to_refreshing_row():
    rows = plan_comparison_rows(
        requested_dimensions=("texture.refreshing",),
        product_ids=(91, 38),
        ...
    )
    assert [row.label for row in rows] == [
        "品牌主打",
        "清爽",
        "参考价",
    ]
```

- [x] **Step 2: Use concept IDs, not user words, as dimension keys**

Dimension policy:

```python
_DIMENSION_LABELS = {
    "efficacy.repair": "修护方向",
    "texture.refreshing": "清爽",
    "texture": "质地",
    "reference_price": "参考价",
}
```

The model may translate “怕闷” to `texture.refreshing`; it may not invent the row label or values.

- [x] **Step 3: Build cells from typed facts**

Known value:

```python
ComparisonCell(
    product_id=91,
    value="轻盈乳液、易吸收",
    fact_ids=("selection:...",),
    state="known",
)
```

Unknown value:

```python
ComparisonCell(
    product_id=38,
    value="暂无明确描述",
    fact_ids=(),
    state="unknown",
)
```

Do not use `product_section.copy_text` as a comparison cell.

- [x] **Step 4: Always order rows deterministically**

```text
品牌主打
→ requested dimensions in request order
→ 参考价
```

Deduplicate when a requested dimension is already `品牌主打` or `参考价`.

- [x] **Step 5: Run comparison tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/presentation/test_comparison_planning.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py -q
```

Expected: PASS.

- [x] **Step 6: Commit comparison planning**

```bash
git add \
  app/guide/presentation/comparison_planning.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/image_recommendation_flow.py \
  tests/guide/presentation/test_comparison_planning.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py
git commit -m "feat(presentation): plan comparisons from typed dimensions"
```

---

## Task 5 (Phase F): Generate Backend-Owned Compact Tags

**Files:**
- Create: `app/guide/presentation/compact_tag_planning.py`
- Create: `tests/guide/presentation/test_compact_tag_planning.py`
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/image_recommendation_flow.py`

- [x] **Step 1: Write RED tests**

```python
def test_compact_tags_are_bounded_and_evidence_backed():
    tags = plan_compact_tags(
        responsibility=Responsibility.RECOMMENDATION,
        product_id=38,
        requested_concepts=("efficacy.repair",),
        ...
    )
    assert 0 < len(tags) <= 3
    assert all(tag.fact_ids for tag in tags)


def test_product_knowledge_tags_do_not_include_fit_status():
    tags = plan_compact_tags(
        responsibility=Responsibility.PRODUCT_KNOWLEDGE,
        product_id=38,
        ...
    )
    assert "适配待确认" not in {tag.label for tag in tags}
```

- [x] **Step 2: Implement responsibility-specific priority**

```text
recommendation:
  matched concept -> product differentiator -> approved ingredient

comparison:
  requested comparison concept -> differentiator -> price-band tag only
  when price is already visible, avoid repeating the exact price as a Tag

single_product_suitability:
  matched need -> relevant product fact -> ingredient

product_knowledge:
  facts relevant to the current question -> stable differentiator

image_identity:
  category -> identity confirmed
```

Each compact Tag must be 2-4 characters. The planner rejects one-character
labels and labels longer than four characters instead of truncating or
compressing them. Fewer than three Tags is valid when the reviewed facts do
not supply enough compliant labels.

No tag may be generated from:

```text
description
rerank_reason
raw exact_text
unreviewed OCR
unknown state
```

- [x] **Step 3: Run focused Tag tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/presentation/test_compact_tag_planning.py \
  tests/guide/presentation/test_public_contracts.py -q
```

Expected: PASS.

- [x] **Step 4: Commit compact tags**

```bash
git add \
  app/guide/presentation/compact_tag_planning.py \
  app/guide/presentation/contracts.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/image_recommendation_flow.py \
  tests/guide/presentation/test_compact_tag_planning.py \
  tests/guide/presentation/test_public_contracts.py
git commit -m "feat(presentation): publish backend-owned compact product tags"
```

---

## Task 6 (Phase F): Add Evidence IDs To Every Rewritten Copy Block

**Files:**
- Create: `app/guide/presentation/copy_evidence_validation.py`
- Create: `tests/guide/presentation/test_copy_evidence_validation.py`
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/copywriter_prompt.py`
- Modify: `app/guide/presentation/copywriter_validation.py`
- Modify: `app/guide/presentation/copywriter_fallback.py`
- Modify: `app/guide/presentation/presentation_compiler.py`

- [x] **Step 1: Replace plain strings with source-tagged copy**

```python
class SourceTaggedCopy(BaseModel):
    text: str
    used_fact_ids: tuple[str, ...] = ()
    used_constraint_ids: tuple[str, ...] = ()


class ProductCopy(BaseModel):
    slot_id: str
    positioning: SourceTaggedCopy
    advisor_reason: SourceTaggedCopy | None
```

`summary_copy` and `closing_copy` also become `SourceTaggedCopy`.

- [x] **Step 2: Add location permissions**

```python
_ALLOWED_FACT_LOCATIONS = {
    "recommendation.summary": {"user_constraint", "generic_choice"},
    "recommendation.product": {"slot_fact"},
    "recommendation.advisor_reason": {
        "user_constraint", "slot_fact"
    },
    "comparison.summary": {"user_constraint", "generic_choice"},
    "single_product_suitability.summary": {
        "user_constraint", "slot_fact"
    },
    "single_product_suitability.judgement": {
        "slot_fact", "safety_caution"
    },
    "product_knowledge.summary": {"slot_fact"},
    "product_knowledge.answer": {"slot_fact"},
}
```

- [x] **Step 3: Write RED validation tests**

```python
def test_product_fact_cannot_enter_multi_product_summary():
    with pytest.raises(CopyEvidenceError, match="location"):
        validate_copy_evidence(
            location="comparison.summary",
            used_fact_ids=("product:38:ingredient:b5",),
            ...
        )


def test_product_38_fact_cannot_enter_product_91_block():
    with pytest.raises(CopyEvidenceError, match="ownership"):
        validate_copy_evidence(
            location="recommendation.product",
            slot_product_id=91,
            used_fact_ids=("product:38:ingredient:b5",),
            ...
        )


def test_budget_constraint_can_enter_recommendation_summary():
    validate_copy_evidence(
        location="recommendation.summary",
        used_constraint_ids=("turn:budget_max:300",),
        ...
    )
```

- [x] **Step 4: Change the prompt schema**

The copywriter returns:

```json
{
  "mode": "recommendation",
  "summary_copy": {
    "text": "两款都在预算内，路线不同。",
    "used_fact_ids": [],
    "used_constraint_ids": ["turn:budget_max:300"]
  },
  "product_copy": [
    {
      "slot_id": "p1",
      "positioning": {
        "text": "品牌主打屏障修护，质地轻盈。",
        "used_fact_ids": [
          "product:91:efficacy:barrier_repair",
          "product:91:texture:lightweight"
        ],
        "used_constraint_ids": []
      },
      "advisor_reason": {
        "text": "更符合白天通勤怕闷的需求。",
        "used_fact_ids": ["product:91:texture:lightweight"],
        "used_constraint_ids": ["turn:texture:refreshing"]
      }
    }
  ],
  "closing_copy": {
    "text": "更怕闷可优先第一款。",
    "used_fact_ids": ["product:91:texture:lightweight"],
    "used_constraint_ids": ["turn:texture:refreshing"]
  }
}
```

- [x] **Step 5: Remove regex-based fact permission**

`copywriter_validation.py` may keep:

```text
markup rejection
safety guarantee rejection
product-name leakage
internal public language rejection
length limits
mode/slot shape
```

It must stop using number/ingredient regexes as the primary permission check. Fact permission comes from IDs and location ownership.

- [x] **Step 6: Make fallback use the same IDs**

Fallback output must be created from `ApprovedSoftFact` values and carry their IDs. It must not use `exact_text`, full category dumps or internal phrases.

- [x] **Step 7: Disable demo validation bypass in release runtime**

Add a startup assertion:

```python
if production_release and _demo_relaxes_copywriter_validation():
    raise RuntimeError(
        "GUIDE_DEMO_RELAX_COPYWRITER_VALIDATION is forbidden in release"
    )
```

- [x] **Step 8: Run focused copy tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/presentation/test_copy_evidence_validation.py \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copywriter_fallback.py \
  tests/guide/presentation/test_presentation_compiler.py -q
```

Expected: PASS.

- [x] **Step 9: Commit evidence-tagged copy**

```bash
git add \
  app/guide/presentation/copy_evidence_validation.py \
  app/guide/presentation/copywriter_contracts.py \
  app/guide/presentation/copywriter_prompt.py \
  app/guide/presentation/copywriter_validation.py \
  app/guide/presentation/copywriter_fallback.py \
  app/guide/presentation/presentation_compiler.py \
  tests/guide/presentation/test_copy_evidence_validation.py \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copywriter_fallback.py \
  tests/guide/presentation/test_presentation_compiler.py
git commit -m "feat(presentation): validate copy by evidence ownership"
```

---

## Task 7 (Phase F): Remove Parallel Public-Text Paths

**Files:**
- Create: `app/guide/presentation/public_language_policy.py`
- Create: `tests/guide/presentation/test_public_language_policy.py`
- Modify: `app/guide/application/product_evidence_answer.py`
- Modify: `app/guide/application/general_knowledge_answer.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/image_recommendation_flow.py`
- Modify: `app/guide/application/chat_api_adapter.py`

- [x] **Step 1: Add RED tests for internal language**

```python
@pytest.mark.parametrize("text", [
    "当前资料没有覆盖质地",
    "已审核商品记录显示",
    "页面主打修护",
    "商家宣传改善泛红",
    "原文为一抹灭火",
    "没有可核验数据",
])
def test_internal_mechanical_language_is_not_public(text):
    with pytest.raises(PublicLanguageError):
        validate_final_public_text(text)
```

`品牌主打改善泛红` remains allowed.

- [x] **Step 2: Stop rendering ProductEvidence exact_text**

`product_evidence_answer.py` may use:

```text
plain_meaning
reviewed public_text
qualifier-derived safety caution
```

It must not use:

```python
block.exact_text
```

in any public answer.

- [x] **Step 3: Stop treating MessageEvent as Guide direct answer**

When a valid `presentation_contract` exists:

```text
MessageEvent is not appended to the visible Guide DOM.
MessageEvent is not serialized as directAnswer.
PresentationContract is the only visible answer source.
```

- [x] **Step 4: Validate final compiled contract**

Run `validate_final_public_text` over every visible section and compact tag after model/fallback compilation, not only over model output.

- [x] **Step 5: Run focused integration tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/presentation/test_public_language_policy.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py -q
```

Expected: PASS.

- [x] **Step 6: Commit the single public text path**

```bash
git add \
  app/guide/presentation/public_language_policy.py \
  app/guide/application/product_evidence_answer.py \
  app/guide/application/general_knowledge_answer.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/image_recommendation_flow.py \
  app/guide/application/chat_api_adapter.py \
  tests/guide/presentation/test_public_language_policy.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py
git commit -m "fix(presentation): remove parallel public answer paths"
```

---

## Task 8 (Phase F): Make Frontend A Pure Contract Renderer

**Files:**
- Modify: `app/static/guide-presentation.js`
- Modify: `app/static/chat.html`
- Modify: `tests/fixtures/guide/presentation/frontend_mode_matrix_v2.jsonl`
- Modify: `tests/guide/runtime/test_frontend_mode_matrix.py`
- Modify: `tests/guide/runtime/test_frontend_presentation_stream.py`
- Modify: `tests/guide/runtime/test_frontend_card_binding.py`
- Modify: `tests/guide/runtime/test_frontend_evidence_rendering.py`

- [x] **Step 1: Update frontend mode truth**

Expected layouts:

```python
EXPECTED_SECTIONS = {
    "recommendation": [
        "summary", "product:*", "closing", "full_cards"
    ],
    "comparison": [
        "summary", "comparison", "full_cards"
    ],
    "single_product": [
        "summary", "judgement", "full_cards"
    ],
    "product_knowledge": [
        "summary", "answer", "full_cards"
    ],
}
```

The fixture must no longer assert inline cards for comparison, suitability or product knowledge.

- [x] **Step 2: Remove frontend business copy**

Delete public usage of:

```javascript
buildDetailedProductReason()
getSkinEvidenceLabel()
p.rerank_reason
p.description
full category_facts fallback
```

- [x] **Step 3: Render compact tags verbatim**

```javascript
const tags = Array.isArray(product.compact_tags)
    ? product.compact_tags.slice(0, 3)
    : [];
```

No JavaScript fallback creates tags.

- [x] **Step 4: Use one shelf title**

Every product-bearing responsibility uses:

```text
本轮提到的商品
```

- [x] **Step 5: Render comparison rows from the contract**

`createComparisonTable()` reads `presentation.comparison_rows`.

It must not derive rows from:

```text
product sections
direct_facts of the first product
copy_text
```

- [x] **Step 6: Render display_name and price/spec separately**

```javascript
nameNode.textContent = product.display_name;
priceNode.textContent = formatCurrency(product.price)
    + (product.specification ? ` / ${product.specification}` : "");
```

- [x] **Step 7: Add DOM assertions**

```python
assert page.locator(".recommendation-reason").count() == 0
assert page.locator("text=适配待确认").count() == 0
assert page.locator(".recommendation-card .recommendation-chip").count() <= (
    3 * visible_product_count
)
assert page.locator(
    '[data-presentation-mode="comparison"] [data-guide-card-form="inline"]'
).count() == 0
```

- [x] **Step 8: Run frontend focused tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/runtime/test_frontend_mode_matrix.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_evidence_rendering.py -q
```

Expected: PASS.

- [x] **Step 9: Commit frontend rendering**

```bash
git add \
  app/static/guide-presentation.js \
  app/static/chat.html \
  tests/fixtures/guide/presentation/frontend_mode_matrix_v2.jsonl \
  tests/guide/runtime/test_frontend_mode_matrix.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_evidence_rendering.py
git commit -m "fix(frontend): render only the public presentation contract"
```

---

## Task 9 (Phase B): Define Category-Specific SMZDM Review Policies

> **Execution start after baseline:** 这是 Task 1 后的第一个业务阶段。完成本任务前不得开始 Tasks 2-8 的生产实现。

**Files:**
- Create: `tools/guide_data/smzdm_category_policy.py`
- Create: `tests/guide/data/test_smzdm_category_policy.py`
- Modify: `tools/guide_data/crawl_smzdm_wiki_pages.py`
- Modify: `tools/guide_data/build_smzdm_review_candidates.py`

- [x] **Step 1: Encode category review fields**

```python
CATEGORY_REVIEW_FIELDS = {
    "skincare": (
        "net_content",
        "ingredients_present",
        "texture",
        "efficacy",
        "usage",
    ),
    "suncare": (
        "net_content",
        "spf_pa",
        "texture",
        "film_speed",
        "water_resistance",
        "reapplication",
        "cleansing_requirement",
    ),
    "cleanser": (
        "net_content",
        "surfactant_type",
        "cleansing_power",
        "rinse_behavior",
        "texture",
    ),
    "base_makeup": (
        "net_content",
        "shade",
        "finish",
        "coverage",
        "longevity",
        "texture",
    ),
    "color_makeup": (
        "shade",
        "color_family",
        "finish",
        "color_payoff",
        "longevity",
    ),
    "fragrance": (
        "net_content",
        "concentration",
        "fragrance_family",
        "top_notes",
        "heart_notes",
        "base_notes",
        "longevity",
        "sillage",
    ),
}
```

- [x] **Step 2: Record long-image availability without treating absence as failure**

Every raw capture records:

```json
{
  "detail_image_count": 0,
  "detail_image_status": "absent",
  "review_sources": ["parameter_table", "product_introduction"]
}
```

or:

```json
{
  "detail_image_count": 18,
  "detail_image_status": "present",
  "review_sources": [
    "parameter_table",
    "product_introduction",
    "detail_images"
  ]
}
```

Rules:

```text
有长图：
  主 Agent 逐图查看，记录 image ordinal 和候选事实。

无长图：
  只审核参数表和商品介绍。
  不伪造 detail image，也不因无长图自动判无价值。

参数/介绍/长图均无高价值事实：
  记录 no_promotion，不为凑数量降低标准。
```

- [x] **Step 3: Keep automation review-only**

Crawler may:

```text
download raw page
save hashes
save parameter text
save introduction text
save long images
assemble a review packet
```

Crawler may not:

```text
approve facts
write public_text
decide map/leave_free
update Canonical
update selection concepts
replace price/specification
```

- [x] **Step 4: Add policy tests**

```python
def test_skincare_review_does_not_extract_suncare_fields():
    assert "spf_pa" not in fields_for_profile("skincare")


def test_absent_detail_images_remain_a_valid_review_packet():
    packet = build_review_packet(
        parameter_text="净含量 50ml",
        introduction_text="柔润乳液质地",
        detail_images=(),
    )
    assert packet.detail_image_status == "absent"
    assert packet.review_sources == (
        "parameter_table",
        "product_introduction",
    )
```

- [x] **Step 5: Run focused data policy tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/data/test_smzdm_wiki_crawl.py \
  tests/guide/data/test_smzdm_review_candidates.py \
  tests/guide/data/test_smzdm_category_policy.py -q
```

Expected: PASS.

- [x] **Step 6: Commit category policy**

```bash
git add \
  tools/guide_data/smzdm_category_policy.py \
  tools/guide_data/crawl_smzdm_wiki_pages.py \
  tools/guide_data/build_smzdm_review_candidates.py \
  tests/guide/data/test_smzdm_wiki_crawl.py \
  tests/guide/data/test_smzdm_review_candidates.py \
  tests/guide/data/test_smzdm_category_policy.py
git commit -m "feat(data): add category-specific smzdm review policy"
```

---

## Task 10 (Phase C): Manually Review The 79-Product SMZDM Queue

**Files:**
- Create: `tools/guide_data/review_smzdm_product.py`
- Create: `docs/audits/smzdm-data/reviewed-products/*.json`
- Modify: `data/guide_merchant_claims/smzdm_crawl_v1/raw_pages.jsonl`
- Modify: `data/guide_merchant_claims/smzdm_crawl_v1/human_reviews.jsonl`
- Modify: `data/guide_merchant_claims/smzdm_crawl_v1/review_candidates.jsonl`
- Test: `tests/guide/data/test_smzdm_review_candidates.py`

- [x] **Step 1: Process the queue in category batches**

Order:

```text
skincare high-gap pilot 10
remaining skincare
suncare
cleanser
base_makeup
color_makeup
fragrance
```

Use low-frequency wiki capture. On challenge:

```text
status = capture_blocked
no raw write
no fact candidate
manual browser queue
```

- [x] **Step 2: Build one review packet per product**

Each packet contains:

```json
{
  "product_id": 46,
  "canonical_identity": "...",
  "canonical_specification": "40ml",
  "source_url": "https://wiki.smzdm.com/p/...",
  "source_match": "exact|family|variant_review",
  "parameter_text": "...",
  "introduction_text": "...",
  "detail_image_status": "present",
  "detail_images": [
    {
      "ordinal": 1,
      "local_path": "...",
      "sha256": "..."
    }
  ],
  "candidate_facts": []
}
```

- [x] **Step 3: Main Agent reviews every candidate**

Sub Agents may collect candidate evidence for different products, but the main Agent must personally decide every promoted fact:

```json
{
  "fact_id": "reviewed:product:46:texture:...",
  "field_key": "texture",
  "public_text": "柔润乳霜质地",
  "source_kind": "detail_image",
  "source_ordinal": 7,
  "sku_status": "exact",
  "decision": "map",
  "concept_id": "texture.rich_cream",
  "allowed_uses": [
    "product_knowledge",
    "recommendation",
    "comparison",
    "compact_tag"
  ],
  "review_rationale": "..."
}
```

Allowed decisions:

```text
map
leave_free
reject
```

- [x] **Step 4: Limit approved facts to meaningful density**

Target:

```text
3-5 approved high-value facts per product when source quality supports it
0-2 when the source is sparse
no_promotion when no safe useful fact exists
```

Do not force five facts for every product.

- [x] **Step 5: Audit identity, specification and price separately**

For every product:

```text
identity status
source SKU
canonical SKU
reference-price SKU
display specification
```

Price and specification may be combined only when all five are aligned.
When a fact sentence contains a SKU/specification token but any SKU field is
`unresolved` or `conflict`, the sentence must not be reused as generic public
recommendation copy. Only reviewed projections such as efficacy, texture,
ingredient or mechanism concepts may flow forward; the specification itself
remains hidden until SKU alignment is resolved.

- [x] **Step 6: Run data review integrity tests after each category batch**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/data/test_smzdm_assets.py \
  tests/guide/data/test_smzdm_review_candidates.py \
  tests/guide/data/test_product_evidence_production_assets.py \
  tests/guide/data/test_merchant_claim_production_assets.py -q
```

Expected: PASS.

- [x] **Step 7: Commit each reviewed category separately**

Example:

```bash
git add \
  data/guide_merchant_claims/smzdm_crawl_v1 \
  docs/audits/smzdm-data/reviewed-products
git commit -m "data(skincare): add reviewed smzdm product facts"
```

Do not combine all six categories into one unreviewable commit.

---

## Task 11 (Phase D): Promote Reviewed Facts And Rebuild Concepts

**Files:**
- Create: `tools/guide_data/promote_reviewed_product_facts.py`
- Create: `tools/guide_data/publish_selection_parent_concepts.py`
- Create: `tests/guide/data/test_promote_reviewed_product_facts.py`
- Modify: `app/guide/retrieval/category_fact_assets.py`
- Modify: `app/guide/retrieval/category_fact_reader.py`
- Modify: `app/guide/retrieval/selection_parent_concept_contracts.py`
- Modify: `app/guide_runtime/composition.py`
- Modify: `data/guide_category_facts/*`
- Modify: `docs/audits/selection-concepts/*`
- Modify: `data/guide_selection_concepts/*`
- Test: `tests/guide/retrieval/test_selection_parent_concept_assets.py`

人工终审的字段事实发布到 `guide_category_facts`；`map` 通过 capability
进入 selection facts，`leave_free` 只保留 answer/display 权限。不得把同一
事实再复制进 merchant claims 或 product evidence 形成平行真值源。

- [x] **Step 1: Reject unreviewed promotion**

```python
def test_promotion_requires_main_agent_review():
    candidate = candidate_fact(reviewed_by=None)
    with pytest.raises(PromotionError):
        promote(candidate)
```

- [x] **Step 2: Route decisions**

```text
map:
  publish product evidence
  publish selection fact
  include in parent/child concept review
  allow recommendation/comparison/compact_tag

leave_free:
  publish product evidence with answer/display permissions
  do not publish selection projection
  allow product knowledge and bounded copy

reject:
  preserve audit record only
```

- [x] **Step 3: Rebuild parent-concept inventory**

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_data/audit_selection_parent_concepts.py \
  --repo-root . \
  --output-dir docs/audits/selection-concepts/review-v2
```

Every new candidate requires a manual `map` or `leave_free` decision.

- [x] **Step 4: Publish hash-locked concept assets**

Create the CLI as a thin wrapper over the existing publisher:

```python
from pathlib import Path

from app.guide.retrieval.selection_parent_concept_assets import (
    publish_selection_concept_assets,
)
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptReview,
)


def publish_from_paths(
    *,
    inventory: Path,
    reviews: Path,
    output_dir: Path,
) -> Path:
    rows = tuple(
        SelectionConceptReview.model_validate_json(line, strict=True)
        for line in reviews.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return publish_selection_concept_assets(
        reviews=rows,
        inventory_path=inventory,
        review_path=reviews,
        output_dir=output_dir,
    )
```

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_data/publish_selection_parent_concepts.py \
  --inventory docs/audits/selection-concepts/review-v2/inventory.json \
  --reviews docs/audits/selection-concepts/review-v2/reviews.jsonl \
  --output-dir data/guide_selection_concepts/v2
```

- [x] **Step 5: Run concept and targeted recall tests**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/data/test_promote_reviewed_product_facts.py \
  tests/guide/retrieval/test_selection_parent_concept_assets.py \
  tests/guide/intent/test_concept_preferences.py \
  tests/guide/retrieval/test_selection_parent_concept_reader.py \
  tests/guide/decision/test_recommendation.py -q
```

Expected: PASS.

- [x] **Step 5a: Enforce SKU-bound public-copy permissions**

When a product display binding is `unresolved` or `conflict`, additional
product-evidence facts may remain available for product-specific knowledge,
but they cannot enter generic recommendation/comparison copy. Merchant claims
must prefer their reviewed `normalized_value` over long OCR `display_claim`
text. When a task already has a typed requested field, the packet must not
fall back to the full category-fact list for that field.

The guard is structural:

```text
display binding status
→ ProductCard
→ PresentationPacket fact permission
→ evidence-ID location validation / deterministic fallback
```

No SKU token regex, sentence exception, product-ID exception or prompt rule
is allowed.

- [x] **Step 6: Commit reviewed promotion**

```bash
git add \
  tools/guide_data/promote_reviewed_product_facts.py \
  tools/guide_data/publish_selection_parent_concepts.py \
  data/guide_product_evidence \
  data/guide_merchant_claims \
  docs/audits/selection-concepts \
  data/guide_selection_concepts \
  tests/guide/data/test_promote_reviewed_product_facts.py \
  tests/guide/retrieval/test_selection_parent_concept_assets.py \
  tests/guide/intent/test_concept_preferences.py \
  tests/guide/retrieval/test_selection_parent_concept_reader.py \
  tests/guide/decision/test_recommendation.py
git commit -m "data(guide): promote reviewed facts and concepts"
```

---

## Task 12 (Phase G): Run Focused Mechanical Gates

**Files:**
- Create: `tools/guide_gates/run_final_release_gate.py`
- Create: `tests/guide/tools/test_final_release_gate.py`
- Create: `docs/audits/final-release/focused-summary.json`

- [x] **Step 1: Run responsibility and presentation gates**

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/guide/understanding/test_exact_parsing.py \
  tests/guide/intent/test_executable_intent_compiler.py \
  tests/guide/intent/test_responsibility_matrix.py \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/presentation/test_public_contracts.py \
  tests/guide/presentation/test_comparison_planning.py \
  tests/guide/presentation/test_compact_tag_planning.py \
  tests/guide/presentation/test_copy_evidence_validation.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/runtime/test_frontend_mode_matrix.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_card_binding.py -q
```

Expected: PASS.

- [x] **Step 2: Run generated responsibility matrix**

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_responsibility_matrix.py \
  --output-dir /tmp/xiaoro-responsibility-matrix

PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_release_gate.py \
  --responsibility-matrix /tmp/xiaoro-responsibility-matrix \
  --output docs/audits/final-release/focused-summary.json
```

Required:

```text
legal_row_failures = 0
wrong_binding_count = 0
wrong_processor_count = 0
wrong_presentation_count = 0
forbidden_public_text_count = 0
```

- [x] **Step 3: Do not run full regression yet**

At this stage, do not run the entire suite. Focused gates provide faster evidence and avoid wasting time before real-model failures are known.

- [x] **Step 4: Commit the focused gate**

```bash
git add \
  tools/guide_gates/run_final_release_gate.py \
  tests/guide/tools/test_final_release_gate.py \
  docs/audits/final-release/focused-summary.json
git commit -m "test(guide): add focused final release gate"
```

---

## Task 12.5 (Phase G): Derive Copywriter I/O From The Public Presentation Contract

**Status:** Required before any further real copywriter, backend or browser
API gate. This task supersedes prompt-only v10-v12 iteration.

**Problem being repaired:**

```text
Current public contract is responsibility-specific.
Current copywriter draft is one generic essay shape.
The compiler silently discards parts of that generic draft for several modes.
The validator and copy gate can then reject unseen text or demand a nonexistent
closing section. This is an internal backend contract mismatch, not a frontend
rendering problem and not a product-data problem.
```

**Files:**
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/copywriter_prompt.py`
- Modify: `app/guide/presentation/copy_evidence_validation.py`
- Modify: `app/guide/presentation/copywriter_validation.py`
- Modify: `app/guide/presentation/copywriter_fallback.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Modify: `tools/guide_gates/presentation_copy_gate.py`
- Modify: `tools/guide_gates/run_real_presentation_copy_gate.py`
- Create: `tests/guide/presentation/test_copywriter_section_contract.py`
- Modify: `tests/guide/presentation/test_copywriter_prompt.py`
- Modify: `tests/guide/presentation/test_copywriter_validation.py`
- Modify: `tests/guide/presentation/test_copywriter_fallback.py`
- Modify: `tests/guide/presentation/test_presentation_compiler.py`
- Modify: `tests/guide/tools/test_presentation_copy_gate.py`
- Create: `docs/audits/final-release/copywriter-contract-preflight.json`

- [x] **Step 1: Write failing tests for section-derived writer scope**

The tests must prove that the model can only receive and return text blocks
which the final `PresentationPacket.section_order` will render:

```text
recommendation / followup / revision / image_recommendation:
  summary + product positioning/reason per slot + closing

comparison / image_comparison:
  summary only
  comparison rows remain backend-owned and are never model prose

single_product_suitability / image_suitability:
  summary + judgement

product_knowledge:
  answer only; any fixed orienting summary is backend-owned

image_identity:
  identity observation is backend-owned; no model product marketing copy

general_knowledge / consultation:
  only their visible body block

clarification / error / safety deterministic policy:
  no copywriter call
```

At least one test must prove that supplying a non-rendered block is rejected
before compilation. At least one test must prove that a valid comparison draft
cannot contain `product_copy` or `closing_copy`.

- [x] **Step 2: Replace universal `CopywriterDraft` with typed writable sections**

Define a typed writer request/draft derived from the packet, conceptually:

```python
class WritableSectionSpec(_StrictFrozen):
    section_kind: Literal[
        "summary",
        "product",
        "judgement",
        "answer",
        "general_knowledge",
        "consultation_body",
    ]
    slot_id: str | None
    allowed_fact_ids: tuple[str, ...]
    required_dimension_ids: tuple[str, ...]
    allowed_constraint_ids: tuple[str, ...]
    copy_budget: int


class SectionTaggedCopy(_StrictFrozen):
    section_kind: str
    slot_id: str | None
    text: str
    used_fact_ids: tuple[str, ...]
    used_constraint_ids: tuple[str, ...]
```

`WritableSectionSpec` must be produced only from `PresentationPacket` and its
terminal responsibility. It may not be assembled by frontend code or Prompt
conditionals. Product sections may retain an explicit `advisor_reason` child
only where the final public `product` section renders it.

- [x] **Step 3: Make `section_order` the sole source of writer work**

`presentation_packet.py` must emit the exact writable section specs. The
copywriter prompt serializes those specs verbatim and asks for no other keys.
`presentation_compiler.py` compiles returned sections by section identity, not
by generic `summary_copy/product_copy/closing_copy` fallback branches.

No final presentation section may be omitted from the writer request if it is
model-owned. No writer output may be silently discarded.

- [x] **Step 4: Keep the hard evidence gate; correct only its scope**

Continue rejecting:

```text
unknown fact IDs
cross-product fact IDs
facts in forbidden sections
variant-restricted facts in generic copy
missing merchant/consumer attribution in the public block that uses it
internal language
raw exact_text / price / specification leakage
unsupported winner or safety language
```

Replace the old coverage calculation:

```text
wrong: used facts / every allowed_soft_fact_id
```

with:

```text
correct: covered required_dimension_ids /
         required_dimension_ids for final visible model-owned sections
```

`allowed_fact_ids` grants permission only. It is never a demand to enumerate
all facts. A request for texture must not fail because an allowed fragrance,
usage-context or secondary merchant fact is not repeated.

- [x] **Step 5: Preserve only the two already-proven mechanical corrections**

```text
1. closing is required if and only if section_order contains closing.
2. merchant/consumer attribution is checked across the whole visible product
   item, not separately for its positioning and advisor_reason children.
```

All other v10-v12 prompt-only changes must be removed or regenerated from the
new typed writer contract. Do not carry them forward as accumulated rules.

- [x] **Step 6: Complete local proof before any real API call**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/presentation/test_copywriter_section_contract.py \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/presentation/test_copy_evidence_validation.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copywriter_fallback.py \
  tests/guide/presentation/test_presentation_compiler.py \
  tests/guide/tools/test_presentation_copy_gate.py
```

Then replay every stored v1-v4 real copywriter raw response through the new
parser, validation and compiler with **zero API calls**. The replay report must
separate:

```text
historical prompt-shape failures
old generic-contract failures
real fact/attribution/public-language failures
```

- [x] **Step 7: Write the cost preflight and continue local work**

Create `docs/audits/final-release/copywriter-contract-preflight.json` with:

```text
old_contract_hash
new_contract_hash
affected responsibilities
local test command and result
zero-API replay hashes
remaining known risks
requested real-call count
reason that no Prompt-only retry is proposed
```

At this point the agent reports the preflight in its normal progress update.
It continues local work without waiting. A real request remains forbidden until
this preflight exists and all Step 6 local proof is green.

- [x] **Step 8: One bounded real copywriter smoke after local proof**

Use a frozen 20-case responsibility-diverse fixture and the exact production
DeepSeek configuration. This is one named batch, not an iterative Prompt
experiment.

```text
If a hard failure occurs:
  stop immediately;
  do not spend the remaining calls;
  preserve partial output;
  report in the next progress update;
  return autonomously to Step 1 with the earliest owner.

If the batch clears:
  proceed to Task 13 and Task 14.
```

The smoke may not be counted as release success. It only proves that the
copywriter contract is safe to include in the final production-equivalent
backend and browser gates.

---

## Task 12.75 (Phase G): Add The Typed TurnMeaning Semantic-Equivalence Matrix

**Status:** Required before resuming Task 13 real translation calls.

**Why this task exists:**

```text
The four-dimensional responsibility matrix starts after TurnMeaning has been
accepted. It correctly decides processor, binding and public presentation from
the typed decision.

The current real translation gate still judges some turns too early by the
single operation_hint value. It can reject a legitimate typed result such as:

  product reference + question meaning + followup

when the frozen case happened to name the operation knowledge, even though both
compile into the same product-knowledge responsibility.

It can also reject:

  budget/constraint revision + recommendation

when the same typed change legitimately compiles into recommendation revision.

The inverse must remain rejected:

  single product reference + product question
  -> recommendation task

This is not interchangeable with product knowledge merely because both mention
the same product. It changes the user-visible responsibility.
```

This task creates a shared **semantic-equivalence matrix** between model
translation and the existing four-dimensional responsibility matrix. It must
not add phrase exceptions, Prompt instructions, regexes or product-ID branches.

**Files:**
- Create: `app/guide/understanding/semantic_equivalence.py`
- Modify: `app/guide/understanding/turn_meaning_contracts.py`
- Modify: `app/guide/intent/executable_intent_compiler.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `tools/guide_gates/turn_meaning_gate.py`
- Modify: `tools/guide_gates/run_final_real_translation.py`
- Modify: `tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl`
- Modify: `tests/fixtures/guide/final_release/real_translation_12x4.jsonl`
- Create: `tests/guide/understanding/test_semantic_equivalence.py`
- Modify: `tests/guide/tools/test_turn_meaning_gate.py`
- Modify: `tests/guide/tools/test_final_real_translation.py`
- Create: `docs/audits/final-release/semantic-equivalence-matrix.json`
- Create: `docs/audits/final-release/real-translation/semantic-equivalence-replay.json`

- [ ] **Step 1: Write failing matrix tests before changing translation acceptance**

Define test cases by typed semantic shape, not by Chinese sentence:

```python
def test_product_knowledge_accepts_knowledge_or_referenced_followup() -> None:
    expected = SemanticOutcomeContract(
        responsibility="product_knowledge",
        reference_shape="one_product",
        question_required=True,
    )
    assert is_semantically_equivalent(
        expected=expected,
        actual=_meaning(operation="knowledge", reference="p2"),
    )
    assert is_semantically_equivalent(
        expected=expected,
        actual=_meaning(operation="followup", reference="p2"),
    )


def test_product_knowledge_rejects_recommendation_even_with_same_reference() -> None:
    expected = SemanticOutcomeContract(
        responsibility="product_knowledge",
        reference_shape="one_product",
        question_required=True,
    )
    assert not is_semantically_equivalent(
        expected=expected,
        actual=_meaning(
            operation="recommendation",
            reference="p2",
            constraint="ingredient_exclusion",
        ),
    )


def test_recommendation_revision_accepts_followup_or_recommendation() -> None:
    expected = SemanticOutcomeContract(
        responsibility="recommendation",
        reference_shape="none",
        revision_required=True,
    )
    assert is_semantically_equivalent(
        expected=expected,
        actual=_meaning(operation="followup", budget="300"),
    )
    assert is_semantically_equivalent(
        expected=expected,
        actual=_meaning(operation="recommendation", budget="300"),
    )
```

Add equivalent tests for:

```text
single-product suitability
comparison
image identity
image similarity recommendation
general knowledge
clarification
consultation
safety escalation
```

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/understanding/test_semantic_equivalence.py \
  tests/guide/tools/test_turn_meaning_gate.py
```

Expected: fail because no shared equivalence contract exists.

- [ ] **Step 2: Define the semantic outcome contract**

Create an immutable typed contract with these decision-bearing fields:

```python
class SemanticOutcomeContract(_StrictFrozen):
    responsibility: ResponsibilityClass
    reference_shape: Literal[
        "none",
        "one_product",
        "product_batch",
        "one_image",
        "image_batch",
    ]
    required_atoms: tuple[SemanticAtomRequirement, ...]
    question_required: bool
    revision_required: bool
    safety_required: bool
    allowed_task_modes: tuple[TaskMode, ...]
```

`SemanticAtomRequirement` must describe typed facts such as:

```text
budget candidate
constraint change
product reference
image reference
comparison cardinality
observation code
question meaning
```

It must not contain raw user sentences, Prompt versions, product IDs or regex
patterns.

- [ ] **Step 3: Derive expected outcomes from the existing responsibility owner**

Add one pure function:

```python
def derive_semantic_outcome(
    *,
    expected_case: TurnMeaningGateCase,
) -> SemanticOutcomeContract:
    ...
```

The function must derive the outcome from the existing typed case expectation,
compiled reference requirements, expected task mode and route responsibility.
It must not infer from a model response.

The implementation must reject inconsistent fixture declarations, including:

```text
product_knowledge with no product reference requirement
comparison with fewer than two typed objects
revision with neither a budget nor a typed constraint change
safety escalation without a safety observation contract
```

- [ ] **Step 4: Implement the matrix as explicit responsibility rows**

The matrix must compare:

```text
expected semantic outcome
against
actual TurnMeaning + compiled references + planned task mode
```

Required rows:

```text
product_knowledge:
  knowledge OR followup only when one typed product/image reference and
  question_meaning produce product knowledge/followup task ownership.

recommendation_revision:
  recommendation OR followup only when typed budget/constraint revision has
  no narrower product-reference obligation and compiles to recommendation.

single_product_suitability:
  suitability OR assessment only when one typed product/image reference is
  retained and compiles to suitability ownership.

comparison:
  comparison only when the typed object cardinality is exactly the requested
  pair/batch; do not accept recommendation.

image_identity:
  image_identity only with image references; do not accept generic knowledge.

image_recommendation:
  image_similarity OR recommendation only with an image anchor and a
  recommendation task.

general_knowledge:
  knowledge only with question_meaning and no required product ownership.

clarification:
  clarification only when required missing/ambiguous references remain
  unresolved.

consultation:
  assessment OR followup only with required observation atoms and consultation
  task ownership.

safety_escalation:
  assessment only with the required high-risk observation atoms and safety
  outcome. Never accept ordinary recommendation.
```

The matrix must return an explainable decision:

```python
class SemanticEquivalenceDecision(_StrictFrozen):
    passed: bool
    expected_outcome: SemanticOutcomeContract
    actual_outcome: SemanticOutcomeContract
    mismatch_code: SemanticEquivalenceMismatchCode | None
```

- [ ] **Step 5: Replace operation-hint exceptions in the translation gate**

Remove ad hoc `operation_hint` compatibility branches from
`tools/guide_gates/turn_meaning_gate.py`.

`evaluate_gate_case()` must:

```text
1. validate raw atom grounding,
2. compile TurnMeaning using the production compiler,
3. derive the planned task,
4. evaluate the shared semantic-equivalence decision,
5. expose mismatch_code and the expected/actual outcome in its result.
```

The gate must not mark a model answer as correct merely because its
`operation_hint` has been added to a tuple. It must prove the same typed
responsibility, object cardinality and task ownership.

- [ ] **Step 6: Audit all existing turn-meaning fixture rows**

For every row in:

```text
tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl
```

derive and serialize its expected semantic outcome into:

```text
docs/audits/final-release/semantic-equivalence-matrix.json
```

The audit must include:

```text
case_id
expected responsibility
required reference shape
allowed model operation family
allowed task modes
required typed atoms
explicitly rejected competing responsibilities
```

The matrix must cover all 128 existing gate cases. Any case whose current
truth cannot be converted without ambiguity is a fixture/truth defect and must
be corrected before real calls resume.

- [ ] **Step 7: Replay all frozen real translation output with zero API calls**

Replay every already-captured Task 13 run, including v1-v4 partial artifacts:

```text
docs/audits/final-release/real-translation/
docs/audits/final-release/real-translation-v2/
docs/audits/final-release/real-translation-v3/
docs/audits/final-release/real-translation-v4/
```

Write:

```text
docs/audits/final-release/real-translation/semantic-equivalence-replay.json
```

Classify every prior failure as exactly one of:

```text
fixture_truth_too_narrow
shared_gate_contract_missing
model_translation_wrong_responsibility
model_translation_wrong_binding
model_translation_unsafe
provider_or_schema_failure
```

The replay must prove:

```text
- the first three accepted shared-contract cases now pass without a provider;
- the referenced-product-to-recommendation case remains rejected;
- no prior wrong binding or unsafe downgrade becomes accepted;
- provider_call_count = 0.
```

- [ ] **Step 8: Reissue a cost preflight before another real batch**

Create:

```text
docs/audits/final-release/real-translation/semantic-equivalence-preflight.json
```

It must include:

```text
matrix source hashes
fixture hash
local test command and result
zero-API replay hash
all prior real-call counts
the next 48-call limit
the explicit statement that no Prompt-only retry is proposed
```

No new DeepSeek call is permitted until the matrix test suite, the 128-case
audit and all zero-API replays are green.

- [ ] **Step 9: Add one unseen 12x4 fixture and resume Task 13**

The next fixture must not reuse wording from any rejected prior turn. It must
include one deliberate negative counterexample:

```text
referenced product + typed constraint
-> recommendation task
```

The negative counterexample must remain rejected by the semantic-equivalence
matrix; it is evidence against over-broad acceptance.

---

## Task 13 (Phase G): Run 48 Real DeepSeek Translation Turns

**Prerequisite:** Task 12.5 Steps 1-8 and Task 12.75 are complete, the named
copywriter smoke has passed, and no copywriter or semantic-equivalence contract
mismatch is open.

**Files:**
- Create: `tests/fixtures/guide/final_release/real_translation_12x4.jsonl`
- Create: `tools/guide_gates/run_final_real_translation.py`
- Create: `docs/audits/final-release/real-translation/*`
- Test: `tests/guide/tools/test_final_real_translation.py`

- [ ] **Step 1: Author 12 four-turn trajectories**

Required families:

```text
1. recommendation -> two candidate ordinals suitability -> comparison
2. recommendation -> product knowledge -> comparison return
3. recommendation -> consultation -> batch suitability return
4. recommendation -> budget revision -> product followup
5. product knowledge -> general knowledge -> return product
6. two explicit products -> comparison -> single product knowledge
7. image identity -> image suitability
8. two images -> image comparison with refreshing concept
9. image identity -> image similarity recommendation -> product knowledge
10. ambiguous reference -> clarification -> supplement -> resume
11. ordinary consultation -> profile confirmation -> recommendation
12. safety escalation -> no ordinary recommendation downgrade
```

Each trajectory has four turns and a sealed truth file.

- [ ] **Step 2: Call DeepSeek exactly once per turn**

Rules:

```text
model = deepseek-v4-pro
format repair attempts = 0
retry count = 0
copywriter calls = 0
```

- [ ] **Step 3: Save every layer**

For all 48 turns save:

```text
input
semantic context
raw provider output
TurnMeaning
compiled references
object cardinality/type
responsibility decision
bindings
processor
presentation mode
earliest failure layer
token usage
latency
hashes
```

- [ ] **Step 4: Apply release thresholds**

```text
critical trajectory complete rate = 100%
overall correct turns >= 46 / 48
wrong product/image binding = 0
unsafe downgrade = 0
internal public language = 0
```

Any failed turn requires a written root-cause record before proceeding.

- [ ] **Step 5: Root-cause failures; do not patch phrases**

For every failure:

```text
identify earliest layer
add a typed counterexample
repair the shared semantic-equivalence contract or the true earliest owner
run focused tests
replay all 48 with zero API
write a cost preflight into the audit record
run the next real-model batch only after the structural repair and local proof
```

If the same failure remains after shared-layer repair, stop release work and update the plan rather than adding a phrase exception.

- [ ] **Step 6: Add unseen 48-turn production batches when needed**

If the first 48 turns do not satisfy the threshold:

```text
1. Freeze the failed inputs and raw outputs as evidence.
2. Identify the earliest failure layer.
3. Add typed counterexamples and repair only the shared owner.
4. Run focused tests and zero-API replay of all prior real outputs.
5. Write the new batch scope and call count into the cost preflight.
6. Author a new 12×4 sheet that does not reuse the failed wording and run
   another 48 real DeepSeek calls only after the structural repair and local
   proof are complete.
7. Repeat until critical trajectories are 100%, wrong binding and unsafe
   downgrade remain zero, and overall accuracy clears the release threshold.
```

Do not average a serious failure away across larger batches. Any serious
wrong binding, unsafe downgrade, cross-session leak, raw-ad leak or wrong
responsibility blocks release even if the aggregate score is high.

- [ ] **Step 7: Commit real translation evidence**

```bash
git add \
  tests/fixtures/guide/final_release/real_translation_12x4.jsonl \
  tools/guide_gates/run_final_real_translation.py \
  tests/guide/tools/test_final_real_translation.py \
  docs/audits/final-release/real-translation
git commit -m "test(guide): validate final real translation trajectories"
```

---

## Task 14 (Phase G): Run 12×4 Real Backend End-To-End

**Prerequisite:** Task 12.5 is complete and its approved smoke has no hard
copywriter-contract failure. A deterministic fallback caused by copywriter
validation is a blocker, not a successful backend response.

**Files:**
- Create: `tools/guide_gates/run_final_real_backend.py`
- Create: `docs/audits/final-release/real-backend/*`
- Test: `tests/guide/tools/test_final_real_backend.py`

- [ ] **Step 1: Start the real runtime**

```bash
GUIDE_LLM_API_KEY="$(cat /Users/bytedance/Desktop/deepseek-key.txt)" \
GUIDE_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_LLM_MODEL=deepseek-v4-pro \
GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS=0 \
GUIDE_COPY_LLM_API_KEY="$(cat /Users/bytedance/Desktop/deepseek-key.txt)" \
GUIDE_COPY_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_COPY_LLM_MODEL=deepseek-v4-pro \
GUIDE_COPY_LLM_TEMPERATURE=0.3 \
XIAORO_GUIDE_STATE_DIR=/tmp/xiaoro-final-real-backend \
.venv/bin/uvicorn app.guide_runtime.app:app \
  --host 127.0.0.1 \
  --port 8810
```

`GUIDE_DEMO_RELAX_COPYWRITER_VALIDATION` must be absent.

- [ ] **Step 2: Execute all 48 turns with cookie ownership**

The runner must retain:

```text
session cookie
session_id
conversation_version
image bundle ownership
```

- [ ] **Step 3: Assert each SSE contract**

```text
start is first
end is last
one presentation_contract
presentation before message
visible IDs equal bound product IDs
compact tags <= 3 per product
no exact_text in public sections
no second direct answer
no internal language
```

- [ ] **Step 4: Apply backend thresholds**

```text
critical end-to-end trajectories = 12 / 12
completed turns = 48 / 48
wrong binding = 0
wrong responsibility = 0
wrong presentation = 0
raw-ad leakage = 0
fallback due to hard_fact/attribution = 0
medical escalation fallback allowed only in the safety trajectory
provider failure may not be reported as functional success
```

- [ ] **Step 5: Repeat with unseen production-equivalent backend batches**

When any functional threshold fails:

```text
root-cause the earliest layer
repair the shared contract
replay all prior captured outputs with zero API
write a cost preflight
run a new unseen 12×4 real backend batch only after the structural repair and
local proof are complete
```

Continue in 48-turn increments until:

```text
all critical trajectories pass
serious failures = 0
wrong binding = 0
wrong responsibility = 0
wrong presentation = 0
raw/internal language leaks = 0
copy validation false fallback = 0
```

The final report must list every real batch, its model/config hash, result
hash, failures, repairs and the exact batch used for the go/no-go decision.

- [ ] **Step 6: Commit backend evidence**

```bash
git add \
  tools/guide_gates/run_final_real_backend.py \
  tests/guide/tools/test_final_real_backend.py \
  docs/audits/final-release/real-backend
git commit -m "test(guide): pass final real backend trajectories"
```

---

## Task 15 (Phase G): Run 8 Real Browser Trajectories On Desktop And Mobile

**Prerequisite:** Task 14 has passed with the real copywriter provider. Browser
screenshots must never be used to hide or bypass a backend copywriter fallback.

**Files:**
- Modify: `tools/guide_gates/run_real_continuous_conversation_browser_audit.py`
- Create: `docs/audits/final-release/browser/*`
- Modify: `tests/guide/tools/test_run_real_continuous_conversation_browser_audit.py`
- Modify: `tests/guide/runtime/test_frontend_browser_contract.py`

- [ ] **Step 1: Replace the obsolete DOM selectors**

Current historical audit incorrectly searches `.guide-presentation`; the real renderer uses `.guide-presentation-root`.

Use:

```javascript
const roots = Array.from(
  document.querySelectorAll('.guide-presentation-root')
);
const sections = Array.from(
  last.querySelectorAll('[data-section-kind]')
);
```

- [ ] **Step 2: Define eight critical browser chains**

```text
1. recommendation -> multiple ordinal suitability -> comparison
2. recommendation -> second product knowledge
3. recommendation -> single-product suitability
4. recommendation -> consultation -> batch comparison return
5. two real images -> image comparison by refreshing concept
6. image identity -> image similarity recommendation -> product knowledge
7. budget revision -> new recommendation -> product followup
8. ambiguous reference -> clarification and safety escalation
```

- [ ] **Step 3: Run desktop and mobile**

Viewports:

```text
desktop: 1440 × 900
mobile: 390 × 844
```

For every turn save:

```text
SSE JSON
final DOM summary
full-page screenshot
console errors
network failures
image failures
layout metrics
```

- [ ] **Step 3a: Use the exact production path**

The browser gate must open the same `/chat` entry and consume the same
`/api/v1/chat/stream` responses intended for production. It must not route,
stub or rewrite Guide SSE responses. Only the external icon CDN may be
fulfilled locally to remove irrelevant network variance.

For every browser turn, assert that the captured SSE model and copywriter
telemetry match the production configuration used by the backend gate.

- [ ] **Step 4: Assert locked rendering**

```python
assert raw_ad_count == 0
assert internal_language_count == 0
assert compact_tag_overflow_count == 0
assert full_card_recommendation_reason_count == 0
assert fit_pending_count == 0
assert product_name_contains_specification_count == 0
assert comparison_inline_card_count == 0
assert comparison_rows_match_requested_dimensions is True
assert product_knowledge_inline_card_count == 0
assert suitability_inline_card_count == 0
assert horizontal_overflow_count == 0
assert overlap_count == 0
assert clipped_text_count == 0
assert unloaded_image_count == 0
assert console_error_count == 0
```

- [ ] **Step 5: Inspect all 16 terminal screenshots**

The main Agent must visually inspect:

```text
8 desktop terminal screenshots
8 mobile terminal screenshots
```

Automated metrics do not replace visual inspection.

- [ ] **Step 6: Add browser trajectories after any discovered boundary**

If a real browser trajectory reveals a new responsibility, data or rendering
boundary:

```text
record the failing SSE, DOM and screenshots
identify the earliest failure layer
repair the shared owner
add a new unseen browser trajectory covering the same typed family
write the required next real-call scope into the audit
rerun desktop and mobile only after the structural repair and local proof are
complete
```

Do not close the browser gate merely because the original eight trajectories
pass after a fix. The new unseen trajectory must pass too.

- [ ] **Step 7: Commit browser evidence**

```bash
git add \
  tools/guide_gates/run_real_continuous_conversation_browser_audit.py \
  tests/guide/tools/test_run_real_continuous_conversation_browser_audit.py \
  tests/guide/runtime/test_frontend_browser_contract.py \
  docs/audits/final-release/browser
git commit -m "test(frontend): pass final real browser trajectories"
```

---

## Task 16 (Phase G): Run One Final Full Regression And Release

**Files:**
- Create: `docs/audits/final-release/release-summary.json`
- Modify: only files already listed in this plan

- [ ] **Step 1: Run static checks**

```bash
git diff --check
PYTHONPATH=. .venv/bin/python -m compileall -q app tools tests
```

Expected: no errors.

- [ ] **Step 2: Run the final full suite exactly once**

Do not repeatedly run the full suite during implementation. Run it once after all shared contracts, data assets and browser fixes are complete:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

Expected: PASS. Existing documented deprecation warnings may remain; new warnings fail release.

- [ ] **Step 3: Re-run only the final release aggregator**

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_release_gate.py \
  --focused docs/audits/final-release/focused-summary.json \
  --translation docs/audits/final-release/real-translation/summary.json \
  --backend docs/audits/final-release/real-backend/summary.json \
  --browser docs/audits/final-release/browser/summary.json \
  --output docs/audits/final-release/release-summary.json
```

Required:

```json
{
  "passed": true,
  "serious_failure_count": 0,
  "wrong_binding_count": 0,
  "unsafe_downgrade_count": 0,
  "raw_ad_leak_count": 0,
  "internal_language_count": 0,
  "frontend_contract_violation_count": 0
}
```

- [ ] **Step 4: Audit the staged allowlist**

```bash
git status --short
git diff --cached --name-only
git diff --cached -U0 -- app/guide \
  | rg '^\+.*(第一款和第二款|第一张和第二张|哪个更适合|product_id\s*==)'
```

Expected: no sentence patch or product-ID patch.

- [ ] **Step 5: Create the release commit**

```bash
git add \
  app/guide \
  app/guide_runtime \
  app/static/chat.html \
  app/static/guide-presentation.js \
  data/guide_product_evidence \
  data/guide_merchant_claims \
  data/guide_selection_concepts \
  tools/guide_data \
  tools/guide_gates \
  tests/guide \
  tests/fixtures/guide \
  docs/audits/final-release \
  docs/audits/smzdm-data/reviewed-products \
  docs/audits/selection-concepts \
  docs/superpowers/plans/2026-08-20-final-guide-release-closure.md

git commit -m "feat(guide): close final data intent copy and presentation gates"
```

- [ ] **Step 6: Push only after the release summary passes**

```bash
git push -u origin final-guide-release-20260820
git ls-remote --heads origin final-guide-release-20260820
```

No force push.

---

## 3. Release Acceptance Summary

上线必须同时满足：

```text
Responsibilities:
  four-dimensional legal rows pass
  multiple candidate/image ordinals route correctly
  no sentence patches

Data:
  79-product queue processed or explicitly blocked/no-promotion
  every promoted fact manually approved
  long images manually inspected when present
  no long image recorded honestly when absent
  SKU/price/spec aligned
  map/leave_free/reject complete

Copy:
  every rewritten block carries fact/constraint IDs
  no hard_fact/attribution false fallback in real backend
  no raw exact_text in public contract
  no internal mechanical language

Frontend:
  one public presentation contract
  comparison = summary + table + shelf
  suitability = summary + judgement + shelf
  product knowledge = answer + product info + shelf
  compact shelf has <= 3 backend-owned tags
  no recommendation reason or fit-pending text in shelf cards

Real gates:
  translation critical trajectories 100%
  overall real translation >= 46/48
  additional unseen 48-turn batches pass whenever the first batch exposes
    a release-blocking defect
  real backend 48/48 complete
  real browser 8/8 desktop and 8/8 mobile
  final go/no-go evidence uses production-equivalent model, prompt, data,
    SSE, frontend build and browser path
  all terminal screenshots manually inspected
  serious failure count = 0
```

## 4. Semantic Accuracy Position

当前语义层的客观结论：

```text
可以依赖的部分：
  常见推荐、比较、单品适配、单品知识、通用知识、
  问诊、预算/肤质修订、图片身份与回切，
  在模型已经输出正确 typed operation/reference 后，
  绑定、路由和状态链整体稳定。

尚不能声称全面兜住的部分：
  多个独立候选序号 + suitability
  多个独立图片序号 + suitability
  同一对象结构在不同职责间的交叉组合
  自然语言到受控比较维度的完整投影
```

因此当前不是“语义识别已经百分百”，也不是“语义链全面不可靠”。准确口径是：

```text
核心常见语义已经可用；
typed 后链路稳定；
自然语言交叉边界需要由四维职责矩阵和 48 条真实模型门禁完成最后收口。
```

达到本计划的真实门禁后，才允许对外表述为：

```text
核心上线语义已通过真实模型、真实后端和真实浏览器验收。
```
