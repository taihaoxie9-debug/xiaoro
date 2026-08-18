# Slice 1.3 Repair Serum Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不搬运旧 Presenter、Agent 或服务代码的前提下，为干净运行时增加“500 元内敏感肌修护精华”纵切，并保持防晒全链路不回归。

**Architecture:** 沿用现有六层主链，只增加 `SERUM`、`REPAIR` 和功效证据合同。召回层拥有精华类目家族，决策层以审核功效执行硬筛并沿用 A2 肤质口径，展示层只透传决策证据；独立运行时升级为文本护肤范围。

**Tech Stack:** Python 3.11, Pydantic 2.8.0, FastAPI 0.115.0, pytest 8.0.0, Playwright, typed SSE.

---

## 0. Execution Contract

- 事实源：
  `docs/superpowers/specs/2026-08-07-slice1-repair-serum-design.md`
- 用户已确认主会话内联执行，不使用子代理。
- 每个 Task 必须执行 RED -> GREEN -> 相关回归 -> boundary -> commit。
- 不修改旧仓库 `/Users/bytedance/Desktop/xiaoro-shopping-master`。
- 不修改：
  - `app/main.py`
  - `app/services/**`
  - `app/database/**`
  - `data/canonical/**`
  - `app/guide/decision/deterministic_ranking.py`
- 排序内核 SHA 必须保持：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- 防晒锁定结果必须保持：

```text
[55, 57, 54, 51, 102, 53, 58, 56, 52, 26, 101]
```

## 1. File Map

### Modify: Contracts and Parsing

- `app/guide/understanding/contracts.py`
  - 新增 `SERUM`、`EfficacyTarget.REPAIR`、`EfficacyDraft`。
- `app/guide/understanding/exact_parsing.py`
  - 精确解析精华、修护和精华否定后缀。
- `app/guide/understanding/__init__.py`
  - 导出新增公开类型。
- `app/guide/intent/contracts.py`
  - 新增 `EfficacyConstraint`。
- `app/guide/intent/task_planning.py`
  - 编译功效约束；精华缺修护时澄清。

### Modify: Retrieval and Authorized Facts

- `app/guide/retrieval/category_taxonomy.py`
  - 新增严格精华家族。
- `app/guide/decision/contracts.py`
  - 决策事实增加 efficacy 状态。
- `app/guide/adapters/catalog/canonical_guide_catalog.py`
  - 读取审核功效；展示事实透传类目。

### Modify: Decision

- `app/guide/decision/contracts.py`
  - 增加功效匹配、排除原因和风险合同。
- `app/guide/decision/recommendation.py`
  - 实现功效硬筛和敏感肌 A2 语义。

### Modify: Presentation and Application

- `app/guide/presentation/contracts.py`
  - 商品卡增加 category 和 matched efficacies。
- `app/guide/presentation/response_planning.py`
  - 只从决策评价构造功效展示证据。
- `app/guide/application/text_recommendation_flow.py`
  - 输出修护精华证据不足摘要。
- `app/guide/application/chat_api_adapter.py`
  - 精华路由、正确类目和功效前端字段。

### Modify: Runtime and Frontend

- `app/guide_runtime/app.py`
  - scope 升级并声明 capabilities。
- `app/guide_runtime/sse.py`
  - 更新文本能力说明。
- `app/static/chat.html`
  - 更新范围文案并显示审核功效。

### Modify: Tests and Gates

- `tests/guide/understanding/test_text_understanding.py`
- `tests/guide/contracts/test_slice1_constraint_contracts.py`
- `tests/guide/intent/test_task_planning.py`
- `tests/guide/retrieval/test_category_taxonomy.py`
- `tests/guide/retrieval/test_canonical_retrieval.py`
- `tests/guide/adapters/catalog/test_canonical_guide_catalog.py`
- `tests/guide/decision/test_recommendation.py`
- `tests/guide/presentation/test_response_planning.py`
- `tests/guide/application/test_text_recommendation_flow.py`
- `tests/guide/application/test_chat_api_adapter.py`
- `tests/guide/application/test_slice1_backend_gate.py`
- `tests/guide/runtime/test_composition.py`
- `tests/guide/runtime/test_runtime_http.py`
- `tests/guide/runtime/test_frontend_scope.py`
- `tests/fixtures/guide/slice1_backend_cases.json`
- `tools/guide_gates/runtime_browser_smoke.py`

---

### Task 1: Add Typed Serum and Repair Constraints

**Files:**
- Modify: `app/guide/understanding/contracts.py`
- Modify: `app/guide/understanding/exact_parsing.py`
- Modify: `app/guide/understanding/__init__.py`
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/intent/task_planning.py`
- Test: `tests/guide/understanding/test_text_understanding.py`
- Test: `tests/guide/contracts/test_slice1_constraint_contracts.py`
- Test: `tests/guide/intent/test_task_planning.py`

- [ ] **Step 1: Write failing understanding and intent tests**

Add these imports and tests:

```python
from app.guide.intent.contracts import EfficacyConstraint
from app.guide.understanding.contracts import (
    EfficacyDraft,
    EfficacyTarget,
)


def test_repair_serum_is_typed_as_category_and_efficacy() -> None:
    result = understand()("500 元内敏感肌修护精华")

    assert result.topic is TopicCode.SERUM
    efficacy = next(
        item
        for item in result.exact_constraints
        if isinstance(item, EfficacyDraft)
    )
    assert efficacy.value is EfficacyTarget.REPAIR


def test_serum_exclusion_suffix_is_removed() -> None:
    result = understand()("不要酒精的修护精华")

    exclusions = [
        item.value
        for item in result.exact_constraints
        if isinstance(item, ExclusionDraft)
    ]
    assert exclusions == ["酒精"]


@pytest.mark.parametrize("message", ["精华水", "眼部精华"])
def test_adjacent_categories_are_not_collapsed_into_serum(
    message: str,
) -> None:
    result = understand()(message)
    assert result.topic is None


def test_repair_serum_compiles_typed_efficacy_constraint() -> None:
    task = plan()(understand_text("500 元内敏感肌修护精华"))

    assert task.mode == "recommend"
    efficacy = next(
        item
        for item in task.constraints
        if isinstance(item, EfficacyConstraint)
    )
    assert efficacy.value is EfficacyTarget.REPAIR


@pytest.mark.parametrize("message", ["精华", "美白精华", "抗老精华"])
def test_serum_without_supported_repair_goal_clarifies(
    message: str,
) -> None:
    task = plan()(understand_text(message))
    assert task.mode == "clarify"
    assert "修护" in task.clarification
```

Add this contract assertion:

```python
def test_efficacy_constraint_uses_controlled_target() -> None:
    constraint = EfficacyConstraint(value=EfficacyTarget.REPAIR)
    assert constraint.kind == "efficacy"
    assert constraint.value is EfficacyTarget.REPAIR
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/understanding/test_text_understanding.py \
  tests/guide/contracts/test_slice1_constraint_contracts.py \
  tests/guide/intent/test_task_planning.py
```

Expected: collection fails because `EfficacyDraft`, `EfficacyTarget` and
`EfficacyConstraint` do not exist.

- [ ] **Step 3: Add strict understanding contracts**

In `app/guide/understanding/contracts.py`, extend `TopicCode` and add:

```python
class TopicCode(str, Enum):
    SUNSCREEN = "sunscreen"
    SERUM = "serum"


class EfficacyTarget(str, Enum):
    REPAIR = "repair"


class EfficacyDraft(_StrictContract):
    kind: Literal["efficacy"] = "efficacy"
    value: EfficacyTarget
```

Replace `ExactConstraintDraft` with:

```python
ExactConstraintDraft = Annotated[
    BudgetDraft
    | CategoryDraft
    | SkinDraft
    | ExclusionDraft
    | EfficacyDraft,
    Field(discriminator="kind"),
]
```

Export the new public types from `app/guide/understanding/__init__.py`:

```python
from app.guide.understanding.contracts import (
    EfficacyTarget,
    ImageBundle,
    ImageObservation,
    StructuredUnderstanding,
    TopicCode,
)

__all__ = [
    "EfficacyTarget",
    "ImageBundle",
    "ImageObservation",
    "StructuredUnderstanding",
    "TopicCode",
]
```

- [ ] **Step 4: Add exact serum and repair parsing**

In `app/guide/understanding/exact_parsing.py`, import `EfficacyDraft` and
`EfficacyTarget`, then replace the category declarations with:

```python
_UNSUPPORTED_SERUM_CATEGORIES = ("精华水", "眼部精华")
_CATEGORY_ALIASES = (
    ("防晒隔离", TopicCode.SUNSCREEN),
    ("防晒乳液", TopicCode.SUNSCREEN),
    ("防晒霜", TopicCode.SUNSCREEN),
    ("防晒乳", TopicCode.SUNSCREEN),
    ("防晒", TopicCode.SUNSCREEN),
    ("精华液", TopicCode.SERUM),
    ("精华", TopicCode.SERUM),
)
_EFFICACY_ALIASES = (
    ("修护", EfficacyTarget.REPAIR),
)
```

Replace `_EXCLUSION_SUFFIX` with:

```python
_EXCLUSION_SUFFIX = re.compile(
    r"(?:的)?(?:修护)?(?:防晒隔离|防晒乳液|防晒霜|防晒乳|防晒|"
    r"精华液|精华|产品).*$"
)
```

In `parse_exact_constraints`, append efficacy after skin:

```python
    efficacy = _parse_efficacy(text)
    if efficacy is not None:
        constraints.append(EfficacyDraft(value=efficacy))
```

Replace `_parse_category` and add `_parse_efficacy`:

```python
def _parse_category(text: str) -> TopicCode | None:
    if any(value in text for value in _UNSUPPORTED_SERUM_CATEGORIES):
        return None
    for alias, code in _CATEGORY_ALIASES:
        if alias in text:
            return code
    return None


def _parse_efficacy(text: str) -> EfficacyTarget | None:
    for alias, target in _EFFICACY_ALIASES:
        if alias in text:
            return target
    return None
```

- [ ] **Step 5: Add intent contract and clarification**

In `app/guide/intent/contracts.py`, import `EfficacyTarget`, add:

```python
class EfficacyConstraint(_StrictContract):
    kind: Literal["efficacy"] = "efficacy"
    value: EfficacyTarget
```

Add it to the `TaskConstraint` discriminated union.

In `app/guide/intent/task_planning.py`, import `EfficacyConstraint`,
`EfficacyDraft` and `TopicCode`. Replace `plan_task` with:

```python
def plan_task(understanding: StructuredUnderstanding) -> TaskPlan:
    constraints = _compile_constraints(understanding)
    if understanding.uncertainties:
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            required_evidence=[],
            clarification=understanding.uncertainties[0].detail,
        )
    category = next(
        (
            item
            for item in constraints
            if isinstance(item, CategoryConstraint)
        ),
        None,
    )
    if category is None:
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            required_evidence=[],
            clarification="当前支持防晒或修护精华，请明确品类。",
        )
    efficacy = next(
        (
            item
            for item in constraints
            if isinstance(item, EfficacyConstraint)
        ),
        None,
    )
    if category.value is TopicCode.SERUM and efficacy is None:
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            required_evidence=[],
            clarification=(
                "当前精华纵切先支持修护诉求，"
                "请确认你是否在找修护精华。"
            ),
        )
    return TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=constraints,
        required_evidence=["canonical_product"],
        clarification=None,
    )
```

Add this branch to `_compile_constraints` before `assert_never`:

```python
        elif isinstance(draft, EfficacyDraft):
            compiled.append(EfficacyConstraint(value=draft.value))
```

- [ ] **Step 6: Run focused and broad tests**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/contracts
python3 app/guide/check_boundaries.py app/guide
```

Expected: all selected tests pass and boundary check reports zero violations.

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/understanding \
  app/guide/intent \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/contracts
git commit -m "feat(guide): type repair serum intent"
```

---

### Task 2: Add Serum Taxonomy and Authorized Efficacy Facts

**Files:**
- Modify: `app/guide/retrieval/category_taxonomy.py`
- Modify: `app/guide/decision/contracts.py`
- Modify: `app/guide/adapters/catalog/canonical_guide_catalog.py`
- Test: `tests/guide/retrieval/test_category_taxonomy.py`
- Test: `tests/guide/retrieval/test_canonical_retrieval.py`
- Test: `tests/guide/adapters/catalog/test_canonical_guide_catalog.py`
- Test: `tests/guide/decision/test_recommendation.py`

- [ ] **Step 1: Write failing taxonomy and fact-port tests**

Add:

```python
def test_serum_family_excludes_adjacent_categories() -> None:
    values = canonical_categories_for(TopicCode.SERUM)
    assert values == frozenset({"精华", "精华液"})
    assert "精华水" not in values
    assert "眼部精华" not in values
```

Add this retrieval test:

```python
def test_retrieves_only_serum_family_candidates() -> None:
    result = retrieve()(make_catalog(), category=TopicCode.SERUM)

    assert [item.product_id for item in result.candidates] == [
        32, 33, 34, 35, 36, 37, 38, 39,
        40, 41, 42, 59, 63, 91, 105, 129,
    ]
    assert {item.canonical_category for item in result.candidates} == {
        "精华",
        "精华液",
    }
```

Add catalog tests:

```python
def test_repair_efficacy_is_read_from_authorized_field(real_catalog) -> None:
    facts = real_catalog.get_decision_facts(38)
    assert facts.efficacy == ("修护", "补水保湿", "舒缓")
    assert facts.efficacy_state is FactState.KNOWN


def test_presentation_facts_preserve_canonical_category(real_catalog) -> None:
    facts = real_catalog.get_presentation_facts(38)
    assert facts.category == "精华"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_category_taxonomy.py \
  tests/guide/retrieval/test_canonical_retrieval.py \
  tests/guide/adapters/catalog/test_canonical_guide_catalog.py
```

Expected: SERUM taxonomy is missing and decision facts have no efficacy.

- [ ] **Step 3: Add serum taxonomy**

Replace the taxonomy declarations with:

```python
CATEGORY_TAXONOMY_VERSION = "slice1-category-v2"

_CATEGORY_FAMILIES = MappingProxyType({
    TopicCode.SUNSCREEN: frozenset({
        "防晒",
        "防晒隔离",
        "防晒乳液",
        "防晒霜",
        "防晒乳",
    }),
    TopicCode.SERUM: frozenset({
        "精华",
        "精华液",
    }),
})
```

- [ ] **Step 4: Extend decision facts**

In `DecisionProductFacts`, add:

```python
    efficacy: tuple[str, ...] | None
    efficacy_state: FactState
```

Add this pair to `validate_state_values`:

```python
            (
                self.efficacy,
                self.efficacy_state,
                "efficacy",
            ),
```

Update the `facts()` helper in
`tests/guide/decision/test_recommendation.py` with defaults:

```python
    efficacy: tuple[str, ...] | None = None,
    efficacy_state: FactState = FactState.UNKNOWN,
```

and pass both fields into `DecisionProductFacts`.

- [ ] **Step 5: Read efficacy and category through the catalog adapter**

In `get_decision_facts`, read:

```python
        efficacy, efficacy_state = _tuple_value(
            product.fields.get("efficacy")
        )
```

and pass both values into `DecisionProductFacts`.

In `get_presentation_facts`, read:

```python
        category_field = product.fields.get("category")
        category = (
            str(category_field.value)
            if category_field is not None
            and category_field.resolved_state == "known"
            else None
        )
```

Pass `category=category` into `ProductCardFacts`. Temporarily add
`category: str | None` to `ProductCardFacts`; Task 4 will propagate it to
`ProductCard`.

Update every `ProductCardFacts` constructor in presentation tests with its
explicit category, using `"防晒"` for current fixtures.

- [ ] **Step 6: Run focused tests and the existing decision suite**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/retrieval \
  tests/guide/adapters/catalog \
  tests/guide/decision/test_recommendation.py \
  tests/guide/presentation/test_response_planning.py
python3 app/guide/check_boundaries.py app/guide
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/retrieval/category_taxonomy.py \
  app/guide/decision/contracts.py \
  app/guide/adapters/catalog/canonical_guide_catalog.py \
  app/guide/presentation/contracts.py \
  tests/guide/retrieval \
  tests/guide/adapters/catalog \
  tests/guide/decision/test_recommendation.py \
  tests/guide/presentation/test_response_planning.py
git commit -m "feat(retrieval): expose serum efficacy facts"
```

---

### Task 3: Enforce Repair Evidence and Sensitive-Skin A2

**Files:**
- Modify: `app/guide/decision/contracts.py`
- Modify: `app/guide/decision/recommendation.py`
- Test: `tests/guide/decision/test_recommendation.py`
- Test: `tests/guide/presentation/test_response_planning.py`

- [ ] **Step 1: Write failing decision tests**

Extend the decision test helper so `decide_with` accepts:

```python
    topic: TopicCode = TopicCode.SUNSCREEN,
    efficacy: EfficacyTarget | None = None,
    skin_target: SkinTarget = SkinTarget.OILY_SENSITIVE,
```

Use `CategoryConstraint(value=topic)`, add an `EfficacyConstraint` when
requested, and use Canonical category `"精华"` for SERUM candidates.

Add:

```python
def test_repair_is_hard_evidence_constraint() -> None:
    result = decide_with(
        [
            facts(1, efficacy=("修护",), efficacy_state=FactState.KNOWN),
            facts(2, efficacy=("美白",), efficacy_state=FactState.KNOWN),
            facts(3, efficacy=None, efficacy_state=FactState.UNKNOWN),
        ],
        topic=TopicCode.SERUM,
        efficacy=EfficacyTarget.REPAIR,
        include_skin=False,
    )

    assert result.ordered_product_ids == [1]
    assert evaluation(result, 1).efficacy_match == "matched"
    assert evaluation(result, 1).matched_efficacies == ["修护"]
    assert evaluation(result, 2).disposition == "excluded_efficacy_mismatch"
    assert evaluation(result, 3).disposition == "excluded_efficacy_unknown"


def test_sensitive_skin_generic_claim_is_unknown_not_mismatch() -> None:
    result = decide_with(
        [
            facts(
                1,
                price=Decimal("200"),
                skin=("敏感肌适用",),
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            ),
            facts(
                2,
                price=Decimal("100"),
                skin=("多种肤质适用",),
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            ),
            facts(
                3,
                skin=("多种肤质适用（敏感肌除外）",),
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            ),
        ],
        topic=TopicCode.SERUM,
        efficacy=EfficacyTarget.REPAIR,
        skin_target=SkinTarget.SENSITIVE,
    )

    assert result.ordered_product_ids == [1, 2]
    assert evaluation(result, 1).skin_match == "matched"
    assert evaluation(result, 2).skin_match == "unknown"
    assert evaluation(result, 3).disposition == "excluded_skin_mismatch"


def test_all_unknown_sensitive_matches_do_not_create_winner() -> None:
    result = decide_with(
        [
            facts(
                38,
                price=Decimal("294"),
                skin=("多种肤质适用",),
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            ),
            facts(
                91,
                price=Decimal("88"),
                skin=("多种肤质适用",),
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            ),
        ],
        topic=TopicCode.SERUM,
        efficacy=EfficacyTarget.REPAIR,
        skin_target=SkinTarget.SENSITIVE,
    )

    assert result.ordered_product_ids == [91, 38]
    assert result.winner_status is WinnerStatus.INSUFFICIENT_FOR_WINNER
    assert result.winner_product_id is None
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/decision/test_recommendation.py
```

Expected: missing efficacy contracts and incorrect generic sensitive-skin
classification.

- [ ] **Step 3: Extend decision result contracts**

In `CandidateEvaluation`, add:

```python
    efficacy_match: Literal[
        "matched",
        "unknown",
        "mismatch",
        "not_applicable",
    ]
    matched_efficacies: list[str]
```

Add dispositions:

```python
        "excluded_efficacy_mismatch",
        "excluded_efficacy_unknown",
```

Add the risk kind:

```python
        "efficacy_evidence_unknown",
```

Update presentation-test `CandidateEvaluation` fixtures with:

```python
efficacy_match="not_applicable",
matched_efficacies=[],
```

- [ ] **Step 4: Implement efficacy filtering**

In `recommendation.py`, import `EfficacyConstraint` and
`EfficacyTarget`. Add:

```python
EfficacyMatch = Literal[
    "matched",
    "unknown",
    "mismatch",
    "not_applicable",
]

_EFFICACY_MARKERS = {
    EfficacyTarget.REPAIR: ("修护",),
}
```

Read the constraint:

```python
    efficacy = next(
        (
            item
            for item in constraints
            if isinstance(item, EfficacyConstraint)
        ),
        None,
    )
```

After budget filtering and before exclusions, evaluate:

```python
        efficacy_match, matched_efficacies = _efficacy_match(
            product,
            efficacy,
        )
        if efficacy_match == "mismatch":
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_efficacy_mismatch",
                    skin_match="not_applicable",
                    efficacy_match="mismatch",
                    matched_efficacies=[],
                    reasons=["known_efficacy_mismatch"],
                )
            )
            continue
        if efficacy_match == "unknown":
            evaluations.append(
                _evaluation(
                    product,
                    disposition="excluded_efficacy_unknown",
                    skin_match="not_applicable",
                    efficacy_match="unknown",
                    matched_efficacies=[],
                    reasons=["efficacy_evidence_unknown"],
                )
            )
            risk_findings.append(
                RiskFinding(
                    kind=(
                        "canonical_fact_conflict"
                        if product.efficacy_state is FactState.CONFLICT
                        else "efficacy_evidence_unknown"
                    ),
                    product_id=product.product_id,
                    detail="修护功效缺少可用审核证据",
                )
            )
            continue
```

Add:

```python
def _efficacy_match(
    product: DecisionProductFacts,
    constraint: EfficacyConstraint | None,
) -> tuple[EfficacyMatch, list[str]]:
    if constraint is None:
        return "not_applicable", []
    if (
        product.efficacy_state is not FactState.KNOWN
        or product.efficacy is None
    ):
        return "unknown", []
    markers = _EFFICACY_MARKERS[constraint.value]
    matches = [
        value
        for value in product.efficacy
        if any(marker in value for marker in markers)
    ]
    if not matches:
        return "mismatch", []
    return "matched", matches
```

Extend `_evaluation` to require and pass `efficacy_match` and
`matched_efficacies`. Every early price/budget branch passes
`"not_applicable", []`; every post-efficacy branch passes the computed values.

Add efficacy evidence, then replace the comparison-dimension construction:

```python
    if efficacy is not None:
        evidence_refs.append(f"efficacy={efficacy.value.value}")

    dimensions: list[str] = []
    if skin is not None:
        dimensions.append("skin_match")
    if efficacy is not None:
        dimensions.append("efficacy_match")
    dimensions.append("price")
```

- [ ] **Step 5: Correct sensitive-skin semantics**

At the beginning of known `_skin_match`, before positive matching, add:

```python
    sensitive_exclusions = (
        "敏感肌除外",
        "敏感肌不适用",
        "不适合敏感肌",
    )
    if constraint.value in {
        SkinTarget.SENSITIVE,
        SkinTarget.OILY_SENSITIVE,
    } and any(value in combined for value in sensitive_exclusions):
        return "mismatch"

    if constraint.value is SkinTarget.SENSITIVE:
        if any(
            value in combined
            for value in ("敏感肌", "敏感性肤质", "敏皮")
        ):
            return "matched"
        if any(
            value in combined
            for value in ("多种肤质", "全肤质", "任何肤质", "通用")
        ):
            return "unknown"
        return "mismatch"
```

- [ ] **Step 6: Run focused and broad decision tests**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/decision \
  tests/guide/presentation/test_response_planning.py
python3 app/guide/check_boundaries.py app/guide
shasum -a 256 app/guide/decision/deterministic_ranking.py
```

Expected: tests pass, boundary passes, SHA remains locked.

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/decision/contracts.py \
  app/guide/decision/recommendation.py \
  tests/guide/decision/test_recommendation.py \
  tests/guide/presentation/test_response_planning.py
git commit -m "feat(decision): require repair efficacy evidence"
```

---

### Task 4: Surface Repair Evidence Through Cards and SSE

**Files:**
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/presentation/response_planning.py`
- Modify: `app/guide/adapters/catalog/canonical_guide_catalog.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Test: `tests/guide/presentation/test_response_planning.py`
- Test: `tests/guide/application/test_text_recommendation_flow.py`
- Test: `tests/guide/application/test_chat_api_adapter.py`

- [ ] **Step 1: Write failing presentation and application tests**

Add:

```python
def test_repair_evidence_and_category_are_surfaced_without_inference() -> None:
    decision = DecisionResult(
        ordered_product_ids=[91],
        winner_status=WinnerStatus.INSUFFICIENT_FOR_WINNER,
        winner_product_id=None,
        evaluations=[
            CandidateEvaluation(
                product_id=91,
                disposition="eligible",
                price=Decimal("88"),
                skin_match="unknown",
                efficacy_match="matched",
                matched_efficacies=["修护"],
                reasons=["hard_constraints_passed"],
            )
        ],
        comparison_dimensions=["skin_match", "efficacy_match", "price"],
        risk_findings=[],
        evidence_refs=["category=serum", "efficacy=repair"],
        tie_reason=None,
    )
    facts = {
        91: ProductCardFacts(
            product_id=91,
            name="玉泽皮肤屏障修护精华乳50ml",
            brand="玉泽",
            category="精华",
            price=Decimal("88"),
            fact_warnings=[],
        )
    }

    card = build()[0](decision, product_facts=facts).structured_events[0]
    assert card.category == "精华"
    assert card.matched_efficacies == ["修护"]
```

Add orchestration test:

```python
def test_repair_serum_real_data_contract(orchestrator) -> None:
    events = list(
        orchestrator.stream(_turn("500 元内敏感肌修护精华"))
    )
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [91, 38]
    assert all(
        card.matched_efficacies == ["修护"]
        for card in products.data.cards
    )
    assert all(card.category == "精华" for card in products.data.cards)
    message = next(item for item in events if item.event == "message")
    assert "敏感肌适配证据不足" in message.data.content
```

Extend adapter routing and product-shape tests:

```python
def test_guide_routes_text_serum_for_visible_clarification() -> None:
    assert should_use_slice1_guide(
        message="500 元内敏感肌修护精华",
        image_results=[],
    )
    assert should_use_slice1_guide(
        message="美白精华",
        image_results=[],
    )


def test_repair_serum_frontend_shape_contains_evidence(
    real_reader,
    real_product_assets,
) -> None:
    orchestrator = build_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
    )
    events = list(
        iter_slice1_guide_legacy_sse_events(
            orchestrator,
            _turn("500 元内敏感肌修护精华"),
        )
    )
    products = next(data for name, data in events if name == "products")
    assert [item["id"] for item in products["products"]] == [91, 38]
    assert products["products"][0]["category"] == "精华"
    assert products["products"][0]["matched_efficacies"] == ["修护"]
    assert "已审核功效：修护" in products["products"][0]["description"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/presentation/test_response_planning.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_chat_api_adapter.py
```

Expected: ProductCard and adapter do not expose category or efficacy.

- [ ] **Step 3: Extend card contracts and response planning**

In `ProductCardFacts`, retain the Task 2 `category` field. In `ProductCard`,
add:

```python
    category: str | None
    matched_efficacies: list[str]
```

In `build_response_plan`, pass:

```python
                category=facts.category,
                matched_efficacies=list(evaluation.matched_efficacies),
```

No presentation code reads Canonical or computes efficacy.

- [ ] **Step 4: Update the application summary**

In `_summary_fragment`, add before the generic insufficient branch:

```python
    if (
        decision.winner_status is WinnerStatus.INSUFFICIENT_FOR_WINNER
        and "efficacy=repair" in decision.evidence_refs
    ):
        return (
            "已找到有审核修护功效且符合预算的候选，"
            "但现有敏感肌适配证据不足，暂不指定唯一推荐。"
        )
```

- [ ] **Step 5: Update the compatibility adapter**

Change `should_use_slice1_guide` to:

```python
def should_use_slice1_guide(
    *,
    message: str,
    image_results: list[dict[str, Any]] | None,
) -> bool:
    return (
        not image_results
        and any(value in message for value in ("防晒", "精华"))
    )
```

In `_card_to_frontend_product`, replace the hardcoded category and add:

```python
        "category": card.get("category"),
        "efficacy_match": (
            "matched"
            if card.get("matched_efficacies")
            else "not_applicable"
        ),
        "matched_efficacies": list(
            card.get("matched_efficacies") or []
        ),
```

Call `_product_description` with:

```python
        "description": _product_description(
            skin_match=card.get("skin_match"),
            warnings=warnings,
            matched_efficacies=list(
                card.get("matched_efficacies") or []
            ),
        ),
```

Replace its signature and opening block with:

```python
def _product_description(
    *,
    skin_match: str | None,
    warnings: list[str],
    matched_efficacies: list[str],
) -> str:
    parts: list[str] = []
    if matched_efficacies:
        parts.append(
            f"已审核功效：{'、'.join(matched_efficacies)}。"
        )
```

Keep the existing skin and warning branches after this opening block.

Update the decision-process description to:

```text
预算、品类、功效和肤质证据已按后端合同处理。
```

- [ ] **Step 6: Run presentation, application and sunscreen regression**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/presentation \
  tests/guide/application
python3 app/guide/check_boundaries.py app/guide
```

Expected: all selected tests pass, including the original sunscreen IDs.

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/presentation \
  app/guide/adapters/catalog/canonical_guide_catalog.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/chat_api_adapter.py \
  tests/guide/presentation \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_chat_api_adapter.py
git commit -m "feat(presentation): surface repair serum evidence"
```

---

### Task 5: Upgrade the Clean Runtime and Shared Page Scope

**Files:**
- Modify: `app/guide_runtime/app.py`
- Modify: `app/guide_runtime/sse.py`
- Modify: `app/static/chat.html`
- Test: `tests/guide/runtime/test_runtime_http.py`
- Test: `tests/guide/runtime/test_frontend_scope.py`

- [ ] **Step 1: Write failing runtime and frontend tests**

Change health expectations to:

```python
    assert health.json() == {
        "status": "healthy",
        "runtime": "guide",
        "scope": "slice1_text_skincare",
        "capabilities": ["sunscreen", "repair_serum"],
    }
```

Add HTTP test:

```python
def test_stream_returns_locked_repair_serum_contract() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "serum-http-test",
            "stream": True,
        },
    )
    events = _events(response)
    products = next(data for name, data in events if name == "products")

    assert [item["id"] for item in products["products"]] == [91, 38]
    assert all(
        item["matched_efficacies"] == ["修护"]
        for item in products["products"]
    )
    assert all(
        item["suitable_skin"] == "肤质数据缺失"
        for item in products["products"]
    )
```

Add frontend static assertions:

```python
    assert "slice1_text_skincare" in html
    assert "文本护肤 · 防晒/修护精华" in html
    assert "matched_efficacies" in html
    assert "recommendation-efficacies" in html
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_scope.py
```

Expected: old sunscreen-only scope and missing efficacy UI fail.

- [ ] **Step 3: Upgrade runtime scope and capabilities**

In `app/guide_runtime/app.py`, replace the scope declaration with:

```python
RUNTIME_SCOPE = "slice1_text_skincare"
RUNTIME_CAPABILITIES = ["sunscreen", "repair_serum"]
```

Change health to:

```python
    @app.get("/health")
    def health() -> dict[str, str | list[str]]:
        return {
            "status": "healthy",
            "runtime": "guide",
            "scope": RUNTIME_SCOPE,
            "capabilities": list(RUNTIME_CAPABILITIES),
        }
```

In `app/guide_runtime/sse.py`, change the image message to:

```text
当前干净运行外壳只支持文本防晒和修护精华推荐。
```

- [ ] **Step 4: Update the shared page**

Change runtime detection to:

```javascript
const GUIDE_RUNTIME_MODE =
    window.__XIAORO_RUNTIME_SCOPE__ === 'slice1_text_skincare';
```

Change the pill text to:

```javascript
runtimeStatusPill.textContent = '文本护肤 · 防晒/修护精华';
```

In `displayProducts`, derive:

```javascript
const matchedEfficacies = Array.isArray(p.matched_efficacies)
    ? p.matched_efficacies.filter(Boolean)
    : [];
```

After the existing recommendation meta block, render:

```javascript
${matchedEfficacies.length ? `
    <div class="recommendation-meta recommendation-efficacies">
        ${matchedEfficacies.map(item => `
            <span class="recommendation-chip">
                已审核${escapeHtml(item)}功效
            </span>
        `).join('')}
    </div>
` : ''}
```

- [ ] **Step 5: Run runtime, static and boundary tests**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime
python3 app/guide/check_boundaries.py app/guide
python3 app/guide/check_boundaries.py app/guide_runtime
git diff --check
```

Expected: runtime tests pass and both boundary checks report zero violations.

- [ ] **Step 6: Commit**

```bash
git add \
  app/guide_runtime/app.py \
  app/guide_runtime/sse.py \
  app/static/chat.html \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_scope.py
git commit -m "feat(runtime): expose repair serum capability"
```

---

### Task 6: Lock the Real-Data and Browser Release Gates

**Files:**
- Modify: `tests/fixtures/guide/slice1_backend_cases.json`
- Modify: `tests/guide/application/test_slice1_backend_gate.py`
- Modify: `tests/guide/runtime/test_composition.py`
- Modify: `tests/guide/test_public_contracts.py`
- Modify: `tools/guide_gates/runtime_browser_smoke.py`
- Modify: `docs/superpowers/specs/2026-08-07-slice1-repair-serum-design.md`
- Modify: `docs/superpowers/plans/2026-08-07-slice1-repair-serum.md`

- [ ] **Step 1: Add locked backend cases**

Append these fixture records:

```json
{
  "case_id": "slice1_repair_serum",
  "message": "500 元内敏感肌修护精华",
  "terminal_event": "end",
  "winner_status": "INSUFFICIENT_FOR_WINNER",
  "product_ids": [91, 38]
},
{
  "case_id": "slice1_repair_serum_exclusion_unknown",
  "message": "500 元内敏感肌不要酒精的修护精华",
  "terminal_event": "end",
  "winner_status": "NO_CANDIDATE",
  "product_ids": []
},
{
  "case_id": "slice1_serum_requires_supported_goal",
  "message": "500 元内敏感肌美白精华",
  "terminal_event": "end",
  "winner_status": null,
  "product_ids": []
}
```

Add a composition assertion using
`"500 元内敏感肌修护精华"` and expected IDs `[91, 38]` while cwd is the
pytest temporary directory.

- [ ] **Step 2: Run the backend gate and verify GREEN**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/application/test_slice1_backend_gate.py \
  tests/guide/runtime/test_composition.py
```

Expected: all old and new locked cases pass.

- [ ] **Step 3: Extend the Playwright smoke gate**

After the existing sunscreen assertions, reload `/chat`, send
`500 元内敏感肌修护精华`, and assert:

```python
        page.goto(args.url, wait_until="networkidle")
        page.fill("#chatInput", "500 元内敏感肌修护精华")
        page.click("#sendBtn")
        expect(
            page.locator(".recommendation-card").first
        ).to_be_visible(timeout=20000)
        assert page.locator(".recommendation-card").count() == 2
        expect(
            page.locator(".recommendation-efficacies").first
        ).to_contain_text("已审核修护功效")
        expect(
            page.locator(".recommendation-reason").first
        ).to_contain_text("肤质数据缺失")
```

Update the status assertion to:

```python
expect(page.locator("#runtimeStatusPill")).to_have_text(
    "文本护肤 · 防晒/修护精华"
)
```

Keep the page-error, failed-image, hidden-image-entry and no-feedback
assertions.

- [ ] **Step 4: Run the full locked test gate**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  -c pytest-guide.ini
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime
python3 app/guide/check_boundaries.py app/guide
python3 app/guide/check_boundaries.py app/guide_runtime
git diff --check
```

Expected: all tests pass and both boundary checks report zero violations.

- [ ] **Step 5: Run the formal browser gate**

Run:

```bash
python3 /Users/bytedance/.trae-cn/skills/webapp-testing/scripts/with_server.py \
  --server "cd /tmp && PYTHONPATH=/Users/bytedance/Desktop/xiaoro-fresh exec /tmp/xiaoro-guide-runtime-venv/bin/uvicorn app.guide_runtime.app:app --host 127.0.0.1 --port 8765" \
  --port 8765 \
  -- python3 tools/guide_gates/runtime_browser_smoke.py \
    --screenshot /tmp/xiaoro-guide-repair-serum.png
```

Expected: exit 0 and screenshot
`/tmp/xiaoro-guide-repair-serum.png`.

- [ ] **Step 6: Confirm protected files and hashes**

Run:

```bash
git diff --name-only ca80b10..HEAD
shasum -a 256 app/guide/decision/deterministic_ranking.py
git status --short --branch
```

Expected:

- no `app/main.py`, `app/services/**`, `app/database/**` or Canonical changes;
- ranking SHA remains locked;
- only the planned gate and documentation files remain before commit.

- [ ] **Step 7: Self-review the design correction**

Verify the design explicitly states that `ProductCardFacts` and `ProductCard`
carry Canonical category and that the adapter no longer hardcodes 防晒:

```bash
rg -n "ProductCardFacts.*category|写死成“防晒”" \
  docs/superpowers/specs/2026-08-07-slice1-repair-serum-design.md
```

Expected: both requirements are present and there are no unresolved
placeholders.

- [ ] **Step 8: Commit the release gates and documentation corrections**

```bash
git add \
  tests/fixtures/guide/slice1_backend_cases.json \
  tests/guide/application/test_slice1_backend_gate.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/test_public_contracts.py \
  tools/guide_gates/runtime_browser_smoke.py \
  docs/superpowers/specs/2026-08-07-slice1-repair-serum-design.md \
  docs/superpowers/plans/2026-08-07-slice1-repair-serum.md
git commit -m "test(guide): gate repair serum vertical slice"
```

---

## Final Acceptance Checklist

- [ ] `SERUM` and `REPAIR` are strict public contract values.
- [ ] `精华水` and `眼部精华` do not enter the serum family.
- [ ] Serum without a supported repair goal clarifies.
- [ ] Repair known match passes; mismatch/unknown/conflict fail closed.
- [ ] Sensitive explicit match, explicit exclusion and generic unknown differ.
- [ ] Ingredient exclusions remain fail-closed.
- [ ] Real result is exactly `[91, 38]`.
- [ ] Winner status is `INSUFFICIENT_FOR_WINNER`.
- [ ] Cards carry Canonical category and `matched_efficacies=["修护"]`.
- [ ] Frontend no longer hardcodes every card as 防晒.
- [ ] Runtime scope is `slice1_text_skincare`.
- [ ] Health capabilities are `sunscreen` and `repair_serum`.
- [ ] Browser renders two serum cards with real images, links and evidence.
- [ ] Original sunscreen IDs and three-card browser rendering remain unchanged.
- [ ] Canonical assets and protected legacy modules remain unchanged.
- [ ] Deterministic ranking SHA remains locked.
- [ ] Full guide gate and both architecture boundary scans pass.

## Stop Condition

本计划完成后停止，不顺带实现多轮追问、美白/抗老功效、图片识别、反馈画像或
LLM。下一阶段必须重新审计并单独设计。
