# Guide Presentation Final Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved XiaoRo presentation design across ranking, copy contracts, structured streaming, mode rendering, and local browser acceptance without changing the established visual shell or deploying production.

**Architecture:** Keep the two-call boundary unchanged: `TurnMeaning` translates, code owns decisions and facts, and the blind copywriter writes only approved narrative. Add a deterministic narrative-atom projection between evidence and `PresentationPacket`, keep hard facts in structured components, and replace the generic final renderer with mode-specific views plus a structured local typewriter that inserts the inline card immediately after each product title.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2 strict/frozen models, vanilla JavaScript, typed SSE, Node contract tests, pytest, Playwright/browser audit tools.

---

## Execution Context

Execute in the existing `/Users/bytedance/Desktop/xiaoro-fresh` `rebuild`
worktree.

The worktree is intentionally dirty. Never revert, overwrite, or stage
unrelated changes. Every commit command in this plan names its exact files.

This plan supersedes:

- `docs/superpowers/plans/2026-08-16-double-blind-copywriter-frontend-integration.md`
  where it conflicts with the final design;
- the old frontend matrix assumptions that revision is zero-card;
- the old visible evidence-wall and section-order assumptions.

## File Responsibility Map

### Decision

- `app/guide/decision/recommendation.py`
  - keep hard eligibility and fit ordering;
  - add explicit-maximum budget proximity as the final soft key.
- `tests/guide/decision/test_recommendation.py`
  - lock budget proximity and stronger-fit precedence.

### Narrative fact projection

- Create `app/guide/presentation/narrative_atoms.py`
  - merge repeated approved soft facts into bounded narrative atoms;
  - rank atoms by need relevance, product distinctiveness, evidence strength,
    and stable keys.
- Create `tests/guide/presentation/test_narrative_atoms.py`
  - lock merging, attribution isolation, stable ordering, and bounds.

### Copy contracts and compilation

- `app/guide/presentation/copywriter_contracts.py`
  - raise the bounded soft-fact capacity;
  - add validation-safe coverage limits and expanded copy budgets.
- `app/guide/presentation/presentation_packet.py`
  - use narrative atoms;
  - curate direct facts;
  - combine price and exact specification;
  - change section order.
- `app/guide/presentation/copywriter_prompt.py`
  - require broad atom coverage and longer advisor copy;
  - forbid internal ranking explanations.
- `app/guide/presentation/copywriter_validation.py`
  - enforce minimum used-fact coverage.
- `app/guide/presentation/copywriter_fallback.py`
  - cover enough atoms without a retry.
- `app/guide/presentation/presentation_compiler.py`
  - compile the approved product section shape and final section order.
- `tests/guide/presentation/test_copywriter_contracts.py`
- `tests/guide/presentation/test_copywriter_prompt.py`
- `tests/guide/presentation/test_copywriter_validation.py`
- `tests/guide/presentation/test_copywriter_fallback.py`
- `tests/guide/presentation/test_presentation_packet.py`
- `tests/guide/presentation/test_presentation_compiler.py`

### Application projection and mode behavior

- `app/guide/application/text_recommendation_flow.py`
  - stop truncating ordinary claims to two;
  - preserve complete revision products;
  - stop appending visible source walls to compatibility copy.
- `app/guide/application/image_recommendation_flow.py`
  - preserve confirmed-only card binding;
  - keep unconfirmed identity zero-card and actionable.
- `tests/guide/application/test_text_recommendation_flow.py`
- `tests/guide/application/test_text_presentation_integration.py`
- `tests/guide/application/test_image_recommendation_flow.py`
- `tests/guide/application/test_image_presentation_integration.py`

### Frontend structured streaming

- `app/static/guide-presentation.js`
  - expose mode-specific view builders;
  - render title, inline card, copy, facts in approved order;
  - add a structured presentation stream controller;
  - keep one inline and one full card per visible product.
- `app/static/chat.html`
  - consume the stream controller;
  - remove visible merchant/review/product-evidence walls;
  - render full shelf before pitfalls;
  - keep the thinking panel transient and remove legacy timeline residue;
  - remove green change-summary chips.
- `tests/guide/runtime/test_frontend_mode_rendering.py`
- `tests/guide/runtime/test_frontend_card_binding.py`
- `tests/guide/runtime/test_frontend_presentation_reducer.py`
- `tests/guide/runtime/test_frontend_presentation_history.py`
- `tests/guide/runtime/test_frontend_presentation_xss.py`
- `tests/guide/runtime/test_frontend_thinking_panel.py`
- `tests/guide/runtime/test_frontend_evidence_rendering.py`

### Mode matrix and browser gates

- `tests/fixtures/guide/presentation/frontend_mode_matrix_v1.jsonl`
  - replace the old 18-row assumptions with the approved 20 scenarios.
- `tests/guide/runtime/test_frontend_gate_matrix.py`
- `tests/guide/runtime/test_backend_handoff_matrix.py`
- `tests/guide/runtime/test_frontend_browser_contract.py`
- `tools/guide_gates/frontend_presentation_browser_audit.py`
- `tools/guide_gates/presentation_copy_gate.py`
- `tests/guide/tools/test_presentation_copy_gate.py`
- `docs/audits/frontend-integration/old_frontend_behavior.md`
  - mark superseded presentation conclusions.

## Task 1: Add Explicit-Maximum Budget Proximity

**Files:**
- Modify: `tests/guide/decision/test_recommendation.py`
- Modify: `app/guide/decision/recommendation.py`

- [ ] **Step 1: Add a failing same-fit budget-proximity test**

Add:

```python
def test_explicit_budget_max_prefers_closer_eligible_prices() -> None:
    products = [
        _color_makeup_facts(10, price=Decimal("100")),
        _color_makeup_facts(20, price=Decimal("199")),
        _color_makeup_facts(30, price=Decimal("299")),
    ]

    result = _decide_color_makeup(
        products,
        facet=None,
        budget_maximum=Decimal("300"),
    )

    assert result.ordered_product_ids == [30, 20, 10]
```

Extend `_decide_color_makeup` with:

```python
def _decide_color_makeup(
    products: list[DecisionProductFacts],
    *,
    facet: FacetConstraint | None,
    exclude: str | None = None,
    budget_maximum: Decimal = Decimal("500"),
) -> DecisionResult:
    constraints = [
        CategoryConstraint(value=TopicCode.COLOR_MAKEUP),
        BudgetConstraint(minimum=None, maximum=budget_maximum),
    ]
```

- [ ] **Step 2: Add a failing stronger-fit precedence test**

```python
def test_soft_match_remains_ahead_of_budget_proximity() -> None:
    products = [
        _color_makeup_facts(
            10,
            price=Decimal("100"),
            selection_facts=(
                _selection_fact(
                    product_id=10,
                    field_key="finish",
                    value="自然",
                    strength=2,
                ),
            ),
        ),
        _color_makeup_facts(20, price=Decimal("299")),
    ]

    result = _decide_color_makeup(
        products,
        facet=FacetConstraint(field_key="finish", value="自然"),
        budget_maximum=Decimal("300"),
    )

    assert result.ordered_product_ids == [10, 20]
```

- [ ] **Step 3: Run the narrow tests and verify RED**

Run:

```bash
python3 -m pytest \
  tests/guide/decision/test_recommendation.py::test_explicit_budget_max_prefers_closer_eligible_prices \
  tests/guide/decision/test_recommendation.py::test_soft_match_remains_ahead_of_budget_proximity \
  -q
```

Expected: the same-fit test fails with ascending price order.

- [ ] **Step 4: Add one budget key helper**

In `recommendation.py`:

```python
def _price_order_key(
    price: Decimal,
    budget: BudgetConstraint | None,
) -> Decimal:
    if budget is not None and budget.maximum is not None:
        return budget.maximum - price
    return price
```

When building each eligible row:

```python
"price_order_key": _price_order_key(product.price, budget),
```

Replace the final `row["price"]` sort fields with
`row["price_order_key"]`, keep direction `"asc"`, and rename the business
key to `"budget_proximity"` when an explicit maximum exists, otherwise
`"price"`.

- [ ] **Step 5: Update existing price-order expectations**

Update existing tests whose helper includes an explicit maximum. Same-fit
eligible candidates should now use descending price toward the maximum.
Tests with stronger soft matches keep their current match-first order.

- [ ] **Step 6: Run decision tests and verify GREEN**

Run:

```bash
python3 -m pytest tests/guide/decision/test_recommendation.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the decision change**

```bash
git add app/guide/decision/recommendation.py tests/guide/decision/test_recommendation.py
git commit -m "feat(guide): rank equal fits near budget maximum"
```

## Task 2: Introduce Deterministic Narrative Atoms

**Files:**
- Create: `app/guide/presentation/narrative_atoms.py`
- Create: `tests/guide/presentation/test_narrative_atoms.py`

- [ ] **Step 1: Write failing merge and attribution tests**

```python
from app.guide.presentation.copywriter_contracts import ApprovedSoftFact
from app.guide.presentation.narrative_atoms import build_narrative_atoms


def _fact(
    fact_id: str,
    field_key: str,
    meaning: str,
    attribution: str,
) -> ApprovedSoftFact:
    return ApprovedSoftFact(
        fact_id=fact_id,
        product_id=55,
        field_key=field_key,
        plain_meaning=meaning,
        attribution=attribution,
        source_refs=(f"source:{fact_id}",),
    )


def test_same_field_and_attribution_merge_into_one_atom() -> None:
    facts = (
        _fact("a", "texture", "轻薄", "merchant_claim"),
        _fact("b", "texture", "清爽不油腻", "merchant_claim"),
    )

    atoms = build_narrative_atoms(
        facts,
        preferred_fields={"texture"},
        distinctive_fields={"texture"},
    )

    assert len(atoms) == 1
    assert atoms[0].field_key == "texture"
    assert "轻薄" in atoms[0].plain_meaning
    assert "清爽不油腻" in atoms[0].plain_meaning
    assert atoms[0].source_refs == ("source:a", "source:b")


def test_different_attributions_never_merge() -> None:
    facts = (
        _fact("a", "texture", "轻薄", "merchant_claim"),
        _fact("b", "texture", "清爽", "consumer_report"),
    )

    atoms = build_narrative_atoms(
        facts,
        preferred_fields={"texture"},
        distinctive_fields=set(),
    )

    assert [item.attribution for item in atoms] == [
        "consumer_report",
        "merchant_claim",
    ]
```

- [ ] **Step 2: Write failing ordering and bound tests**

```python
def test_atoms_prioritize_need_then_distinctive_fields_stably() -> None:
    atoms = build_narrative_atoms(
        (
            _fact("finish", "finish", "自然哑光", "merchant_claim"),
            _fact("texture", "texture", "清爽", "merchant_claim"),
            _fact("usage", "usage", "早晚使用", "merchant_claim"),
        ),
        preferred_fields={"texture"},
        distinctive_fields={"finish"},
    )

    assert [item.field_key for item in atoms] == ["texture", "finish"]
    assert len(atoms) <= 8
```

- [ ] **Step 3: Run the new tests and verify RED**

```bash
python3 -m pytest tests/guide/presentation/test_narrative_atoms.py -q
```

Expected: import failure for `narrative_atoms`.

- [ ] **Step 4: Implement the focused module**

Create:

```python
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from app.guide.presentation.copywriter_contracts import ApprovedSoftFact
from app.guide.presentation.copywriter_validation import (
    is_safe_soft_fact_text,
)


MAX_NARRATIVE_ATOMS = 8
_ALLOWED_FIELDS = frozenset({
    "texture",
    "finish",
    "tone_effect",
    "film_speed",
    "makeup_compatibility",
    "water_resistance",
    "friction_resistance",
    "usage_context",
    "usage_scenario",
    "efficacy",
    "suitable_skin",
    "skin_concern",
    "target_audience",
    "coverage",
    "color_family",
    "color_payoff",
    "shade",
    "makeup_effect",
    "makeup_style",
    "fragrance_description",
    "fragrance_family",
    "fragrance_notes",
    "top_notes",
    "heart_notes",
    "cleansing_power",
    "rinse_behavior",
    "cleansing_requirement",
    "double_cleanse",
    "surfactant_type",
})
_FIELD_GROUP = {
    "tone_effect": "finish",
    "makeup_effect": "finish",
    "makeup_compatibility": "finish",
    "usage_scenario": "usage_context",
    "target_audience": "suitable_skin",
    "fragrance_notes": "fragrance_description",
    "top_notes": "fragrance_description",
    "heart_notes": "fragrance_description",
}
_FIELD_PRIORITY = {
    "texture": 0,
    "finish": 1,
    "film_speed": 2,
    "usage_context": 3,
    "water_resistance": 4,
    "friction_resistance": 5,
    "suitable_skin": 6,
    "efficacy": 7,
    "skin_concern": 8,
    "coverage": 9,
    "color_family": 10,
    "color_payoff": 11,
    "shade": 12,
    "makeup_style": 13,
    "fragrance_description": 14,
    "fragrance_family": 15,
    "cleansing_power": 16,
    "rinse_behavior": 17,
    "cleansing_requirement": 18,
    "double_cleanse": 19,
    "surfactant_type": 20,
}
_ATTRIBUTION_PRIORITY = {
    "verified_fact": 0,
    "consumer_report": 1,
    "merchant_claim": 2,
}


def build_narrative_atoms(
    facts: tuple[ApprovedSoftFact, ...],
    *,
    preferred_fields: set[str],
    distinctive_fields: set[str],
) -> tuple[ApprovedSoftFact, ...]:
    grouped: dict[tuple[int, str, str], list[ApprovedSoftFact]] = defaultdict(list)
    for fact in facts:
        if (
            fact.field_key not in _ALLOWED_FIELDS
            or not is_safe_soft_fact_text(fact.plain_meaning)
        ):
            continue
        field = _FIELD_GROUP.get(fact.field_key, fact.field_key)
        grouped[(fact.product_id, field, fact.attribution)].append(fact)

    atoms = [
        _merge(group)
        for _, group in sorted(
            grouped.items(),
            key=lambda item: (
                item[0][1] not in preferred_fields,
                item[0][1] not in distinctive_fields,
                _FIELD_PRIORITY.get(item[0][1], 99),
                _ATTRIBUTION_PRIORITY[item[0][2]],
                item[0][0],
            ),
        )
    ]
    return tuple(atoms[:MAX_NARRATIVE_ATOMS])


def _merge(facts: list[ApprovedSoftFact]) -> ApprovedSoftFact:
    ordered = sorted(facts, key=lambda item: item.fact_id)
    values = tuple(dict.fromkeys(item.plain_meaning for item in ordered))
    payload = "|".join(item.fact_id for item in ordered).encode("utf-8")
    return ApprovedSoftFact(
        fact_id=f"atom:{sha256(payload).hexdigest()}",
        product_id=ordered[0].product_id,
        field_key=_FIELD_GROUP.get(ordered[0].field_key, ordered[0].field_key),
        plain_meaning="；".join(values),
        attribution=ordered[0].attribution,
        source_refs=tuple(sorted({
            ref for item in ordered for ref in item.source_refs
        })),
    )
```

- [ ] **Step 5: Run the new tests and verify GREEN**

```bash
python3 -m pytest tests/guide/presentation/test_narrative_atoms.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the narrative atom module**

```bash
git add app/guide/presentation/narrative_atoms.py tests/guide/presentation/test_narrative_atoms.py
git commit -m "feat(guide): merge approved narrative atoms"
```

## Task 3: Expand Copy Fact Coverage Without a Third Call

**Files:**
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/copywriter_prompt.py`
- Modify: `app/guide/presentation/copywriter_validation.py`
- Modify: `app/guide/presentation/copywriter_fallback.py`
- Modify: `tests/guide/presentation/test_copywriter_contracts.py`
- Modify: `tests/guide/presentation/test_copywriter_prompt.py`
- Modify: `tests/guide/presentation/test_copywriter_validation.py`
- Modify: `tests/guide/presentation/test_copywriter_fallback.py`

- [ ] **Step 1: Write a failing capacity test**

```python
def test_copy_slot_accepts_eight_bounded_soft_facts() -> None:
    facts = tuple(
        _soft_fact(f"fact-{index}")
        for index in range(8)
    )
    slot = _slot().model_copy(
        update={"approved_soft_facts": facts}
    )
    assert len(slot.approved_soft_facts) == 8
```

- [ ] **Step 2: Write a failing 80-percent coverage test**

```python
def test_validator_requires_eighty_percent_soft_fact_coverage() -> None:
    facts = tuple(
        _soft_fact(f"fact-{index}")
        for index in range(5)
    )
    packet = _packet(soft_facts=facts)
    draft = _draft(used_fact_ids=("fact-0", "fact-1", "fact-2"))

    with pytest.raises(CopywriterValidationError) as error:
        validate_copywriter_draft(packet, draft)

    assert error.value.code is CopywriterValidationErrorCode.FACT_COVERAGE
```

- [ ] **Step 3: Run focused tests and verify RED**

```bash
python3 -m pytest \
  tests/guide/presentation/test_copywriter_contracts.py \
  tests/guide/presentation/test_copywriter_validation.py \
  -q
```

Expected: capacity or missing enum failures.

- [ ] **Step 4: Expand the strict contracts**

Change:

```python
approved_soft_facts: tuple[ApprovedSoftFact, ...] = Field(
    default_factory=tuple,
    max_length=8,
)
```

Use the approved maximums:

```python
class CopyLengthBudget(_StrictFrozen):
    summary_max_chars: int = Field(ge=40, le=400)
    positioning_max_chars: int = Field(ge=30, le=200)
    advisor_reason_max_chars: int = Field(ge=30, le=240)
    closing_max_chars: int = Field(ge=40, le=400)
```

The packet builder will set recommendation limits to
`260 / 150 / 110 / 200`.

- [ ] **Step 5: Add coverage validation**

Add the enum member and import:

```python
import math

class CopywriterValidationErrorCode(str, Enum):
    MODE_MISMATCH = "mode_mismatch"
    SLOT_MISMATCH = "slot_mismatch"
    FACT_ID_MISMATCH = "fact_id_mismatch"
    FACT_COVERAGE = "fact_coverage"
    HARD_FACT = "hard_fact"
    INGREDIENT = "ingredient"
    PRODUCT_NAME = "product_name"
    WINNER_LANGUAGE = "winner_language"
    SAFETY_GUARANTEE = "safety_guarantee"
    MARKUP = "markup"
    ATTRIBUTION = "attribution"
    LENGTH = "length"
    REQUIRED_COPY = "required_copy"
```

and:

```python
required_count = math.ceil(len(slot.approved_soft_facts) * 0.8)
if len(item.used_soft_fact_ids) < required_count:
    _reject(CopywriterValidationErrorCode.FACT_COVERAGE)
```

Coverage is computed after narrative merging. Zero facts require zero IDs.

- [ ] **Step 6: Update the prompt to version 3**

Set:

```python
PRESENTATION_COPY_PROMPT_VERSION = "guide-presentation-copy-prompt-v3"
```

Replace the old "need not repeat all facts" rule with:

```text
每个商品必须自然覆盖至少 80% 的 approved_soft_facts。
同一句可以合并多个互补事实，但不得机械逐条抄写。
不得解释排序层级、预算利用算法、约束优先级或内部处理过程。
摘要需要给出完整判断；综合建议需要明确首选、备选和场景切换。
```

- [ ] **Step 7: Make fallback satisfy coverage**

Replace the first-two-facts behavior with:

```python
safe_facts = tuple(
    fact
    for fact in slot.approved_soft_facts
    if is_safe_soft_fact_text(fact.plain_meaning)
)
required = math.ceil(len(slot.approved_soft_facts) * 0.8)
facts = safe_facts[:required]
positioning_facts = facts[: max(1, len(facts) // 2)]
reason_facts = facts[len(positioning_facts):]
```

Join each group with attributed semicolons and bound it to the copy budget.
If a fact is validator-safe but length truncation would remove its meaning,
exclude its ID from `used_soft_fact_ids`.

- [ ] **Step 8: Run focused tests and verify GREEN**

```bash
python3 -m pytest \
  tests/guide/presentation/test_copywriter_contracts.py \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copywriter_fallback.py \
  -q
```

Expected: PASS.

- [ ] **Step 9: Commit copy contract changes**

```bash
git add \
  app/guide/presentation/copywriter_contracts.py \
  app/guide/presentation/copywriter_prompt.py \
  app/guide/presentation/copywriter_validation.py \
  app/guide/presentation/copywriter_fallback.py \
  tests/guide/presentation/test_copywriter_contracts.py \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copywriter_fallback.py
git commit -m "feat(guide): require rich grounded presentation copy"
```

## Task 4: Build the Final Presentation Packet Shape

**Files:**
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Modify: `tests/guide/presentation/test_presentation_packet.py`
- Modify: `tests/guide/presentation/test_presentation_compiler.py`

- [ ] **Step 1: Write failing atom projection tests**

First extend the existing helpers in
`tests/guide/presentation/test_presentation_packet.py`:

```python
def _card(
    product_id: int,
    *,
    name: str,
    price: str,
    texture_state: str = "known",
    category_facts: tuple[DisplayCategoryFact, ...] | None = None,
) -> ProductCard:
    return ProductCard(
        product_id=product_id,
        category_profile=CategoryProfile.SUNCARE,
        category_facts=(
            category_facts
            if category_facts is not None
            else (
                DisplayCategoryFact(
                    field_key="spf_pa",
                    label="防晒指数",
                    value="SPF50 PA++++",
                    state="known",
                ),
                DisplayCategoryFact(
                    field_key="texture",
                    label="质地",
                    value=(
                        ("轻薄清透", "不黏腻")
                        if texture_state == "known"
                        else None
                    ),
                    state=texture_state,
                ),
            )
        ),
        name=name,
        brand="测试品牌",
        category="防晒",
        price=Decimal(price),
        image_url=f"/static/images/products/{product_id}.png",
        detail_url=f"https://example.com/{product_id}",
        platform="天猫",
        skin_match="unknown",
        matched_efficacies=[],
        fact_warnings=[],
    )


def _claim(
    product_id: int,
    *,
    field_key: str = "film_speed",
    text: str = "一抹速成膜",
) -> MerchantClaimEvidenceData:
    seed = f"{product_id}:{field_key}:{text}".encode("utf-8")
    return MerchantClaimEvidenceData(
        claim_id=sha256(seed).hexdigest(),
        product_id=product_id,
        field_key=field_key,
        display_claim=text,
        claim_scope="ordinary",
        allowed_use="soft_rank_and_display",
        source_locator=(
            f"urn:merchant:{product_id}:{sha256(seed).hexdigest()}"
        ),
    )


def _display_fact(
    field_key: str,
    label: str,
    value: tuple[str, ...],
) -> DisplayCategoryFact:
    return DisplayCategoryFact(
        field_key=field_key,
        label=label,
        value=value,
        state="known",
    )
```

Add `from hashlib import sha256` to the test imports.

Then add a packet fixture with five merchant facts:

```python
packet = build_presentation_packet(
    mode="recommendation",
    user_need_summary="300元内清爽通勤防晒",
    winner_status="SELECTED",
    card_display=recommendation_card_display((card,)),
    cards=(card,),
    selection_slots=(_selection(55),),
    concept_slots=(_concept(55),),
    merchant_claims=tuple(
        _claim(55, field_key=field, text=text)
        for field, text in (
            ("texture", "轻薄清透"),
            ("finish", "透气贴妆"),
            ("film_speed", "快速成膜"),
            ("usage_context", "日常通勤"),
            ("usage", "早晚使用"),
        )
    ),
    pitfalls=(),
)

assert 4 <= len(packet.slots[0].approved_soft_facts) <= 8
assert all(
    fact.field_key != "usage"
    for fact in packet.slots[0].approved_soft_facts
)
```

- [ ] **Step 2: Write failing direct-fact omission and price/spec tests**

```python
def test_locked_facts_combine_reference_price_and_exact_spec() -> None:
    card = _card(
        52,
        name="兰蔻菁纯臻颜防晒隔离乳",
        price="299",
        category_facts=(
            _display_fact("net_content", "净含量", ("30ml",)),
        ),
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="300元内清爽通勤防晒",
        winner_status="SELECTED",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
    )

    assert [
        (fact.label, fact.display_value)
        for fact in packet.slots[0].locked_facts
    ][0] == ("参考价", "¥299 / 30ml")


def test_missing_ingredients_do_not_create_placeholder_fact() -> None:
    card = _card(
        52,
        name="兰蔻菁纯臻颜防晒隔离乳",
        price="299",
        category_facts=(),
    )
    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="300元内清爽通勤防晒",
        winner_status="SELECTED",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
    )
    assert all(
        fact.label != "核心成分"
        for fact in packet.slots[0].locked_facts
    )
```

- [ ] **Step 3: Write a failing numeric proof-point test**

Pass one already-formatted, code-owned locked component:

```python
proof_point = LockedFact(
    fact_id="evidence:" + "a" * 64,
    product_id=52,
    kind="numeric",
    label="用户测试",
    display_value=(
        "商家引用：62名中国消费者连续使用两周后，"
        "通过消费者自评，"
        "100%的受试者认同轻薄不厚重、清爽不油腻"
    ),
    source_refs=("urn:xiaoro:test:proof-point",),
)
packet = build_presentation_packet(
    mode="recommendation",
    user_need_summary="300元内清爽通勤防晒",
    winner_status="SELECTED",
    card_display=recommendation_card_display((card,)),
    cards=(card,),
    selection_slots=(),
    concept_slots=(),
    merchant_claims=(),
    pitfalls=(),
    proof_points=(proof_point,),
)

numeric = [
    fact
    for fact in packet.slots[0].locked_facts
    if fact.kind == "numeric"
]
assert len(numeric) == 1
assert numeric[0].display_value == (
    "商家引用：62名中国消费者连续使用两周后，"
    "通过消费者自评，"
    "100%的受试者认同轻薄不厚重、清爽不油腻"
)
```

Add a second test with two numeric points for one product and assert
`build_presentation_packet` raises `ValueError` rather than choosing
silently.

- [ ] **Step 4: Write a failing section-order test**

```python
assert [section.kind for section in packet.section_order] == [
    "summary",
    "product",
    "closing",
    "full_cards",
    "pitfalls",
]
```

- [ ] **Step 5: Write a failing product-copy separation test**

In `test_presentation_compiler.py`:

```python
product = next(
    section
    for section in contract.sections
    if section.kind == "product"
)
assert product.copy_text == draft.product_copy[0].positioning
assert product.advisor_reason == draft.product_copy[0].advisor_reason
```

- [ ] **Step 6: Run focused tests and verify RED**

```bash
python3 -m pytest \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/presentation/test_presentation_compiler.py \
  -q
```

Expected: old four-fact truncation and old section order fail.

- [ ] **Step 7: Project narrative atoms in `_build_slot`**

Before building slots, compute fields whose approved values differ across the
visible products:

```python
claim_values_by_field: dict[str, set[str]] = {}
for claim in merchant_claims:
    if claim.product_id not in visible_ids or claim.claim_scope != "ordinary":
        continue
    claim_values_by_field.setdefault(claim.field_key, set()).add(
        claim.display_claim.casefold()
    )
distinctive_fields = {
    field_key
    for field_key, values in claim_values_by_field.items()
    if len(values) > 1
}
```

Pass `distinctive_fields` into `_build_slot`. After collecting source facts:

```python
preferred_fields = {
    item.field_key for item in selection_slots
}.union(item.field_key for item in concept_slots)
narrative_atoms = build_narrative_atoms(
    _deduplicate_soft_facts(soft_facts),
    preferred_fields=preferred_fields,
    distinctive_fields=distinctive_fields,
)
```

Set:

```python
approved_soft_facts=narrative_atoms,
```

- [ ] **Step 8: Curate locked facts**

Add:

```python
_DIRECT_FACT_FIELDS = (
    "net_content",
    "ingredients_present",
    "suitable_skin",
)
```

Build price/spec first:

```python
spec = next(
    (
        _category_fact_text(fact)
        for fact in card.category_facts
        if fact.field_key == "net_content" and fact.state == "known"
    ),
    "",
)
if card.price is not None:
    price = f"¥{_decimal_text(card.price)}"
    display = f"{price} / {spec}" if spec else price
    facts.append(
        LockedFact(
            fact_id=f"card:{card.product_id}:reference_price",
            product_id=card.product_id,
            kind="price",
            label="参考价",
            display_value=display,
            numeric_value=card.price,
            source_refs=(f"card:{card.product_id}:price",),
        )
    )
```

Then add only known exact ingredient and suitable-skin facts. Normalize their
labels to `核心成分` and `适用人群`. Do not emit unavailable or conflict
placeholders, and do not repeat `net_content` after it is consumed by the
price row.

- [ ] **Step 9: Add one code-owned numeric proof point**

Add `proof_points: Sequence[LockedFact] = ()` to
`build_presentation_packet`. Validate that every point has `kind="numeric"`,
that all product IDs are visible, and that each product owns at most one
point. Group them by product and pass the owned tuple to `_build_slot`.

In `_locked_facts`, append the validated point:

```python
facts.extend(proof_points)
```

The copywriter packet contains the locked component but the prompt payload
continues to omit locked fact values.

- [ ] **Step 10: Separate positioning and advisor reason**

Add to `PresentationSection`:

```python
advisor_reason: str | None = Field(default=None, max_length=400)
```

Require it for `kind="product"` and forbid it for all other kinds.

Compile product sections with:

```python
PresentationSection(
    kind="product",
    copy_text=item.positioning,
    advisor_reason=item.advisor_reason,
    slot_id=slot.slot_id,
    product_id=slot.product_id,
    direct_facts=tuple(
        DirectFactComponent(
            fact_id=fact.fact_id,
            label=fact.label,
            display_value=fact.display_value,
        )
        for fact in slot.locked_facts
    ),
)
```

- [ ] **Step 11: Change section order**

For product-bearing modes:

```python
sections.extend((
    PresentationSectionSpec(kind="closing"),
    PresentationSectionSpec(kind="full_cards"),
    PresentationSectionSpec(kind="pitfalls"),
))
```

Remove default visible `evidence`.

For zero-slot general knowledge:

```python
return (
    PresentationSectionSpec(kind="summary"),
    PresentationSectionSpec(kind="closing"),
)
```

- [ ] **Step 12: Reverse the contract ordering invariant**

In `_PresentationBase.validate_card_sections`, require:

```python
if (
    pitfall_positions
    and full_card_positions
    and pitfall_positions[0] <= max(full_card_positions)
):
    raise ValueError("pitfalls must follow the full card shelf")
```

- [ ] **Step 13: Expand recommendation copy budgets**

Return:

```python
return CopyLengthBudget(
    summary_max_chars=260,
    positioning_max_chars=150,
    advisor_reason_max_chars=110,
    closing_max_chars=200,
)
```

Keep knowledge and consultation mode-specific bounds explicit.

- [ ] **Step 14: Run focused tests and verify GREEN**

```bash
python3 -m pytest \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/presentation/test_presentation_compiler.py \
  -q
```

Expected: PASS.

- [ ] **Step 15: Commit packet changes**

```bash
git add \
  app/guide/presentation/presentation_packet.py \
  app/guide/presentation/copywriter_contracts.py \
  app/guide/presentation/presentation_compiler.py \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/presentation/test_presentation_compiler.py
git commit -m "feat(guide): compile final presentation structure"
```

## Task 5: Feed All Eligible Claims Into Packet Projection

**Files:**
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`
- Modify: `tests/guide/application/test_text_presentation_integration.py`

- [ ] **Step 1: Write a failing claim projection test**

```python
def test_merchant_projection_keeps_all_reviewed_ordinary_dimensions(
    real_reader,
) -> None:
    root = Path(__file__).resolve().parents[3]
    category_facts = build_category_fact_reader(
        real_reader,
        repo_root=root,
    )

    projected = _project_merchant_claims(
        category_facts.claims,
        product_ids=(52,),
        constraints=[],
    )
    ordinary = [
        item for item in projected if item.claim_scope == "ordinary"
    ]

    assert len(ordinary) >= 5
    assert {
        item.field_key for item in ordinary
    } >= {
        "texture",
        "film_speed",
        "tone_effect",
    }
```

- [ ] **Step 2: Write a failing proof-point projection test**

Use the real product-evidence reader and assert:

```python
product_evidence_event = flow._build_post_decision_evidence_event(
    turn,
    task=task,
    product_ids=(58,),
)
proof_points = _presentation_proof_points(product_evidence_event)

assert len(proof_points) <= 1
assert all(
    point.kind == "numeric"
    and point.label == "用户测试"
    and point.display_value.startswith("商家引用：")
    for point in proof_points
)
```

- [ ] **Step 3: Write a failing revision integration test**

```python
def test_budget_revision_emits_full_revision_with_products() -> None:
    events = list(
        flow.stream(
            _turn(
                session_id="revision-full",
                message="预算改成300，还是想要清爽通勤",
                conversation_version=1,
            )
        )
    )

    presentation = next(
        event.data
        for event in events
        if event.event == "presentation_contract"
    )
    products = next(
        event.data.cards
        for event in events
        if event.event == "products"
    )

    assert presentation.mode == "revision"
    assert len(products) == len(presentation.card_display.visible_product_ids)
    assert len(products) >= 1
```

- [ ] **Step 4: Run focused tests and verify RED**

```bash
python3 -m pytest \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_text_presentation_integration.py \
  -q
```

Expected: ordinary claims are truncated to two or old revision fixtures fail.

- [ ] **Step 5: Remove the two-claim truncation**

Replace:

```python
ordinary = sorted(
    (
        claim
        for claim in deduplicated.values()
        if claim.claim_scope == "ordinary"
    ),
    key=lambda claim: (
        claim.field_key not in preferred_fields,
        "soft_rank" not in claim.capabilities,
        claim.field_key,
        claim.claim_id,
    ),
)[:2]
```

with:

```python
ordinary = sorted(
    (
        claim
        for claim in deduplicated.values()
        if claim.claim_scope == "ordinary"
    ),
    key=lambda claim: (
        claim.field_key not in preferred_fields,
        "soft_rank" not in claim.capabilities,
        claim.field_key,
        claim.claim_id,
    ),
)
```

Keep one bounded safety transcript because warnings are code-owned.

- [ ] **Step 6: Project complete numeric proof points**

Add:

```python
def _presentation_proof_points(
    event: ProductEvidenceEvent | None,
) -> tuple[LockedFact, ...]:
    if event is None:
        return ()
    selected = sorted(
        (
            item.evidence
            for item in event.data.packet.selected
            if (
                item.evidence.management_label
                == "consumer_self_report"
                and item.evidence.qualifiers.sample_size is not None
                and item.evidence.qualifiers.population is not None
                and item.evidence.qualifiers.method is not None
                and item.evidence.qualifiers.duration is not None
                and re.search(
                    r"(?:\d+(?:\.\d+)?%|百分之)",
                    item.evidence.exact_text,
                )
            )
        ),
        key=lambda point: (point.product_id, point.evidence_id),
    )
    first_by_product: dict[int, ProductEvidenceBlock] = {}
    for point in selected:
        first_by_product.setdefault(point.product_id, point)
    return tuple(
        LockedFact(
            fact_id=f"evidence:{point.evidence_id}",
            product_id=point.product_id,
            kind="numeric",
            label="用户测试",
            display_value=(
                f"商家引用：{point.qualifiers.sample_size}名"
                f"{point.qualifiers.population}{point.qualifiers.duration}，"
                f"通过{point.qualifiers.method}，{point.exact_text}"
            ),
            source_refs=(point.source.source_locator,),
        )
        for point in first_by_product.values()
    )
```

Pass:

```python
proof_points=_presentation_proof_points(product_evidence_event),
```

through `_presentation_event` to `build_presentation_packet`.

- [ ] **Step 7: Remove visible source-quote compatibility copy**

Stop calling `_append_source_quotes` for guide-owned presentation responses.
Keep evidence IDs in typed events for audit, but do not append merchant,
review, or source-wall prose to `MessageEvent`.

- [ ] **Step 8: Run focused application tests and verify GREEN**

```bash
python3 -m pytest \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_text_presentation_integration.py \
  -q
```

Expected: PASS.

- [ ] **Step 9: Commit application projection changes**

```bash
git add \
  app/guide/application/text_recommendation_flow.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_text_presentation_integration.py
git commit -m "feat(guide): preserve rich approved product claims"
```

## Task 6: Lock Image Identity Success and Failure Presentation

**Files:**
- Modify: `tests/guide/application/test_image_recommendation_flow.py`
- Modify: `tests/guide/application/test_image_presentation_integration.py`
- Modify only if tests expose a gap:
  `app/guide/application/image_recommendation_flow.py`

- [ ] **Step 1: Add a confirmed identity contract test**

```python
def test_confirmed_identity_emits_one_bound_product_contract() -> None:
    events = list(flow.stream(_turn(receipt, "识别这张图")))

    contract = next(
        event.data
        for event in events
        if event.event == "presentation_contract"
    )

    assert contract.mode == "image_identity"
    assert contract.card_display.mode == "single"
    assert len(contract.card_display.visible_product_ids) == 1
```

- [ ] **Step 2: Add parameterized fail-closed tests**

```python
@pytest.mark.parametrize(
    "state",
    (
        IdentityState.LOW_CONFIDENCE,
        IdentityState.AMBIGUOUS_CANDIDATES,
        IdentityState.OCR_CONFLICT,
        IdentityState.VISUAL_UNAVAILABLE,
    ),
)
def test_unconfirmed_identity_emits_zero_cards(state: IdentityState) -> None:
    events = list(_flow_with_identity(state).stream(_turn(receipt, "识别这张图")))

    assert not any(event.event == "products" for event in events)
    error = next(event for event in events if event.event == "error")
    assert error.data.code in {
        "IMAGE_IDENTITY_UNCONFIRMED",
        "IMAGE_RETRIEVAL_UNAVAILABLE",
    }
```

- [ ] **Step 3: Run image tests**

```bash
python3 -m pytest \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_image_presentation_integration.py \
  -q
```

Expected: PASS or one focused presentation-shape failure.

- [ ] **Step 4: Preserve existing thresholds**

Do not change:

```python
IdentityBindingPolicy(
    minimum_similarity=0.8,
    minimum_margin=0.1,
)
```

If a presentation gap appears, fix only the typed zero-card response. Do not
lower confidence or margin thresholds.

- [ ] **Step 5: Commit image contract tests**

```bash
git add \
  app/guide/application/image_recommendation_flow.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_image_presentation_integration.py
git commit -m "test(guide): lock image identity fail-closed states"
```

## Task 7: Render the Approved Product Section Order

**Files:**
- Modify: `app/static/guide-presentation.js`
- Modify: `tests/guide/runtime/test_frontend_mode_rendering.py`
- Modify: `tests/guide/runtime/test_frontend_card_binding.py`
- Modify: `tests/guide/runtime/test_frontend_presentation_xss.py`

- [ ] **Step 1: Write a failing DOM-order contract test**

Use the Node DOM harness to render one product section, then assert:

```javascript
const children = Array.from(
  productSection.children
).map(node => node.matches('h3')
  ? 'title'
  : node.matches('.inline-product-image')
    ? 'inline_card'
    : node.matches('.guide-product-advisor-reason')
      ? 'advisor_reason'
    : node.matches('p')
      ? 'copy'
      : node.matches('dl')
        ? 'facts'
        : 'other'
);

assert.deepStrictEqual(children, [
  'title',
  'inline_card',
  'copy',
  'facts',
  'advisor_reason',
]);
```

- [ ] **Step 2: Write failing duplicate-card tests**

```javascript
assert.strictEqual(
  root.querySelectorAll('[data-guide-card-form="inline"]').length,
  visibleIds.length
);
assert.deepStrictEqual(
  Array.from(
    root.querySelectorAll('[data-guide-card-form="inline"]')
  ).map(node => Number(node.dataset.guideProductId)),
  visibleIds
);
```

Repeated product references must create `.guide-product-ref` buttons, not a
new inline card.

- [ ] **Step 3: Run frontend Node tests and verify RED**

```bash
python3 -m pytest \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_presentation_xss.py \
  -q
```

Expected: inline card currently appears after direct facts.

- [ ] **Step 4: Reorder product rendering**

In `renderPresentation`, build product sections in this exact order:

```javascript
if (section.kind === 'product') {
  const product = productsById.get(section.product_id);
  const title = documentRef.createElement('h3');
  title.textContent = product.name || `候选 ${index + 1}`;
  sectionNode.append(
    title,
    createInlineProductCard(documentRef, product, helpers)
  );
}

if (section.copy_text) {
  const copy = documentRef.createElement('p');
  appendCopyTokens(copy, section.copy_text, slots, productsById);
  sectionNode.appendChild(copy);
}

if (section.kind === 'product') {
  const facts = createDirectFacts(documentRef, section.direct_facts);
  if (facts.childNodes.length) sectionNode.appendChild(facts);
  const reason = documentRef.createElement('p');
  reason.className = 'guide-product-advisor-reason';
  const label = documentRef.createElement('strong');
  label.textContent = '小 ro 的推荐理由：';
  reason.append(label, documentRef.createTextNode(
    section.advisor_reason
  ));
  sectionNode.appendChild(reason);
}
```

Extract `createDirectFacts` as a pure local helper.

```javascript
function createDirectFacts(documentRef, directFacts) {
  const facts = documentRef.createElement('dl');
  (Array.isArray(directFacts) ? directFacts : []).forEach(fact => {
    if (!fact?.display_value) return;
    const row = documentRef.createElement('div');
    row.className = 'guide-direct-fact';
    const label = documentRef.createElement('dt');
    label.textContent = fact.label || '已核对';
    const value = documentRef.createElement('dd');
    value.textContent = fact.display_value;
    row.append(label, value);
    facts.appendChild(row);
  });
  return facts;
}
```

- [ ] **Step 5: Keep DOM-safe APIs**

Do not introduce `innerHTML` for model or fact content. Continue using
`textContent`, `createTextNode`, and validated URLs.

- [ ] **Step 6: Run frontend Node tests and verify GREEN**

```bash
python3 -m pytest \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_presentation_xss.py \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit renderer ordering**

```bash
git add \
  app/static/guide-presentation.js \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_presentation_xss.py
git commit -m "feat(frontend): place inline cards below product titles"
```

## Task 8: Add Structured Local Streaming

**Files:**
- Modify: `app/static/guide-presentation.js`
- Modify: `app/static/chat.html`
- Create: `tests/guide/runtime/test_frontend_presentation_stream.py`
- Modify: `tests/guide/runtime/test_frontend_thinking_panel.py`

- [ ] **Step 1: Write a failing stream-controller test**

The Node harness should:

```javascript
const events = [];
await guide.streamPresentation(container, state, {
  characterDelayMs: 0,
  onFirstCharacter: () => events.push('first_character'),
  onInlineCard: productId => events.push(`card:${productId}`),
});

assert.strictEqual(events[0], 'first_character');
assert(events.indexOf('card:52') > events.indexOf('first_character'));
assert.strictEqual(
  container.querySelector(
    '[data-guide-card-form="inline"][data-guide-product-id="52"] img'
  ).src,
  expectedImageUrl
);
```

- [ ] **Step 2: Write a failing first-character dismissal test**

```javascript
assert.strictEqual(thinkingController.element, null);
assert.strictEqual(
  container.querySelector('.guide-thinking-pipeline'),
  null
);
assert(
  container.textContent.startsWith('先说我的判断')
);
```

- [ ] **Step 3: Run stream tests and verify RED**

```bash
python3 -m pytest \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_thinking_panel.py \
  -q
```

Expected: `streamPresentation` is missing.

- [ ] **Step 4: Implement `streamPresentation`**

Expose:

```javascript
async function streamPresentation(
  container,
  state,
  options = {}
) {
  const view = presentationViewForState(state);
  const documentRef = container.ownerDocument;
  const rootNode = documentRef.createElement('div');
  rootNode.className = 'guide-presentation-root';
  rootNode.dataset.presentationMode = view.mode;
  container.replaceChildren(rootNode);

  const productsById = new Map(
    view.products.map(product => [product.id, product])
  );
  const slots = view.sections
    .filter(section => section.kind === 'product')
    .map(section => ({
      slot_id: section.slot_id,
      product_id: section.product_id,
    }));
  const delay = Number(options.characterDelayMs ?? 28);
  const sleep = options.sleep || (
    milliseconds => new Promise(
      resolve => setTimeout(resolve, milliseconds)
    )
  );
  let emittedFirstCharacter = false;

  const emitCopy = async (parent, text) => {
    for (const character of String(text || '')) {
      parent.appendChild(
        parent.ownerDocument.createTextNode(character)
      );
      if (!emittedFirstCharacter) {
        emittedFirstCharacter = true;
        options.onFirstCharacter?.();
      }
      if (delay > 0) await sleep(delay);
    }
  };

  for (const [index, section] of view.sections.entries()) {
    if (['full_cards', 'pitfalls', 'evidence'].includes(section.kind)) {
      continue;
    }
    const sectionNode = documentRef.createElement('section');
    sectionNode.className = (
      `guide-presentation-section guide-presentation-${section.kind}`
    );
    sectionNode.dataset.sectionKind = section.kind;

    if (section.kind === 'product') {
      const product = productsById.get(section.product_id);
      if (!product) throw new Error('PRESENTATION_PRODUCT_MISSING');
      sectionNode.id = `guide-product-${section.product_id}`;
      sectionNode.dataset.guideProductId = String(section.product_id);

      const title = documentRef.createElement('h3');
      title.textContent = product.name || `候选 ${index + 1}`;
      const card = createInlineProductCard(
        documentRef,
        product,
        options
      );
      sectionNode.append(title, card);
      options.onInlineCard?.(section.product_id);
    } else {
      const titleByKind = {
        closing: '综合推荐',
        comparison: '对比结论',
        observation: '当前观察',
      };
      const titleText = titleByKind[section.kind];
      if (titleText) {
        const title = documentRef.createElement('h3');
        title.textContent = titleText;
        sectionNode.appendChild(title);
      }
    }

    rootNode.appendChild(sectionNode);

    if (section.copy_text) {
      const copy = documentRef.createElement('p');
      sectionNode.appendChild(copy);
      await emitCopy(copy, section.copy_text);
      substituteProductSlots(section.copy_text, slots)
        .filter(token => token.type === 'product_ref')
        .forEach(token => {
          copy.dataset.containsProductReference = 'true';
          copy.dataset.lastProductReference = String(token.product_id);
        });
    }

    if (section.kind === 'product') {
      const facts = createDirectFacts(
        documentRef,
        section.direct_facts
      );
      if (facts.childNodes.length) sectionNode.appendChild(facts);
      const reason = documentRef.createElement('p');
      reason.className = 'guide-product-advisor-reason';
      const label = documentRef.createElement('strong');
      label.textContent = '小 ro 的推荐理由：';
      reason.appendChild(label);
      sectionNode.appendChild(reason);
      await emitCopy(reason, section.advisor_reason);
    }
  }
  return view;
}
```

Do not stream hard facts character by character. Insert fact rows as complete
structured nodes after narrative copy.

- [ ] **Step 5: Wire chat to the structured stream**

On `presentation_contract`:

```javascript
await XiaoRoPresentation.streamPresentation(
  aiBubble,
  guideTurnState,
  {
    onFirstCharacter: () => {
      XiaoRoPresentation.dismissThinkingPipeline(
        guideThinkingPipeline,
        { firstCharacter: true }
      );
    },
    onInlineCard: productId => {
      renderedInlineProductIds.add(productId);
    },
    getImageUrl: getProductImageSrc,
    getDetailUrl: product => getSafeDetailUrl(product.detail_url),
    formatPrice: product => formatProductPrice(product, true),
  }
);
```

For guide-owned presentation turns, `MessageEvent` remains compatibility
data and must not start a second Markdown typewriter.

- [ ] **Step 6: Remove legacy thinking-timeline competition**

When `guideThinkingPipeline` exists, do not create or advance
`liveDecisionProcess`. Keep one transient thinking component only.

- [ ] **Step 7: Run stream and thinking tests**

```bash
python3 -m pytest \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_thinking_panel.py \
  tests/guide/runtime/test_frontend_presentation_history.py \
  -q
```

Expected: PASS.

- [ ] **Step 8: Commit structured streaming**

```bash
git add \
  app/static/guide-presentation.js \
  app/static/chat.html \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_thinking_panel.py \
  tests/guide/runtime/test_frontend_presentation_history.py
git commit -m "feat(frontend): stream structured guide presentations"
```

## Task 9: Remove Visible Evidence Walls and Fix Final Panel Order

**Files:**
- Modify: `app/static/chat.html`
- Modify: `tests/guide/runtime/test_frontend_evidence_rendering.py`
- Modify: `tests/guide/runtime/test_frontend_mode_rendering.py`

- [ ] **Step 1: Write failing ordinary-answer suppression tests**

Assert that guide-owned recommendation clears these deferred payloads before
the visible panel flush:

```javascript
assert.strictEqual(deferredPanels.merchantClaims, null);
assert.strictEqual(deferredPanels.productEvidence, null);
assert.strictEqual(deferredPanels.reviewEvidence, null);
assert.deepStrictEqual(deferredPanels.citations, []);
```

for guide-owned ordinary answers.

Product-knowledge copy remains in the structured answer; it does not use an
evidence wall.

- [ ] **Step 2: Write a failing final-order test**

In the DOM harness:

```javascript
assert.deepStrictEqual(
  Array.from(message.querySelectorAll(
    '[data-guide-panel]'
  )).map(node => node.dataset.guidePanel),
  ['full_cards', 'pitfalls']
);
```

- [ ] **Step 3: Write failing full-card density tests**

Render three full cards and assert:

```javascript
assert.strictEqual(
  message.querySelectorAll('.category-facts').length,
  0
);
message.querySelectorAll('.recommendation-card').forEach(card => {
  assert(
    card.querySelectorAll('.recommendation-efficacies .recommendation-chip')
      .length <= 2
  );
});
assert.strictEqual(
  message.querySelectorAll('[data-match-percentage]').length,
  0
);
```

- [ ] **Step 4: Run tests and verify RED**

```bash
python3 -m pytest \
  tests/guide/runtime/test_frontend_evidence_rendering.py \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  -q
```

Expected: visible evidence calls or old pitfall order fail.

- [ ] **Step 5: Gate deferred evidence panels**

For guide-owned presentation turns:

```javascript
deferredPanels.merchantClaims = null;
deferredPanels.productEvidence = null;
deferredPanels.reviewEvidence = null;
deferredPanels.citations = [];
```

Keep typed evidence in the reducer's audit state and never append it to the
visible ordinary-answer DOM.

- [ ] **Step 6: Render full cards before pitfalls**

After structured answer streaming completes:

```javascript
displayProducts(finalProducts, feedbackTarget, cardDisplay, categoryProfile);
displayPitfalls(deferredPanels.pitfalls, options);
```

Do not render category fact tables inside full cards.

- [ ] **Step 7: Bound full-card labels**

Remove `categoryFactsHtml` from the recommendation-card template and use:

```javascript
const matchedEfficacies = Array.isArray(p.matched_efficacies)
  ? p.matched_efficacies.filter(Boolean).slice(0, 2)
  : [];
```

Keep brand, category, and platform as metadata. Keep the real evidence label
and do not add a percentage field.

- [ ] **Step 8: Remove change-summary chips**

Delete any visible revision or relative-follow-up chip rendering. Keep
differences in prose and comparison rows.

- [ ] **Step 9: Run tests and verify GREEN**

```bash
python3 -m pytest \
  tests/guide/runtime/test_frontend_evidence_rendering.py \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  -q
```

Expected: PASS.

- [ ] **Step 10: Commit panel cleanup**

```bash
git add \
  app/static/chat.html \
  tests/guide/runtime/test_frontend_evidence_rendering.py \
  tests/guide/runtime/test_frontend_mode_rendering.py
git commit -m "fix(frontend): keep evidence out of guide answers"
```

## Task 10: Lock All 20 User-Visible Scenarios

**Files:**
- Modify: `tests/fixtures/guide/presentation/frontend_mode_matrix_v1.jsonl`
- Modify: `tests/guide/runtime/test_frontend_gate_matrix.py`
- Modify: `tests/guide/runtime/test_backend_handoff_matrix.py`
- Modify: `tests/guide/runtime/test_frontend_browser_contract.py`

- [ ] **Step 1: Replace the fixture with 20 rows**

Use these exact IDs:

```text
recommend-three
compare-two
suitability-one
followup-product-one
followup-relative
revision-products
followup-state-zero
knowledge-product-one
knowledge-general-zero
image-identity-one
image-recommend-three
image-suitability-one
image-compare-two
consultation-entry-zero
consultation-provisional-zero
consultation-confirmation-zero
consultation-medical-zero
clarify-zero
no-match-zero
error-zero
```

Product-bearing section order is:

```json
[
  "summary",
  "product:p1",
  "closing",
  "full_cards",
  "pitfalls"
]
```

Add `comparison` after summary where required and additional product slots in
visible order.

- [ ] **Step 2: Encode corrected card counts**

Lock:

```text
recommendation: 1-3
comparison: 2-4
single/focused/product knowledge/image identity/image suitability: 1
relative follow-up and revision: 1-3
general knowledge/consultation/clarify/no-match/error/state-only: 0
```

- [ ] **Step 3: Run matrix tests and verify RED**

```bash
python3 -m pytest \
  tests/guide/runtime/test_frontend_gate_matrix.py \
  tests/guide/runtime/test_backend_handoff_matrix.py \
  tests/guide/runtime/test_frontend_browser_contract.py \
  -q
```

Expected: tests that hard-code 18 rows fail.

- [ ] **Step 4: Update matrix validators and outcomes**

Require 20 unique IDs and assert:

- exact section order;
- exact visible IDs;
- zero stale cards;
- revision has product slots;
- image unconfirmed is zero-card;
- consultation and medical escalation are zero-card.

- [ ] **Step 5: Run matrix tests and verify GREEN**

```bash
python3 -m pytest \
  tests/guide/runtime/test_frontend_gate_matrix.py \
  tests/guide/runtime/test_backend_handoff_matrix.py \
  tests/guide/runtime/test_frontend_browser_contract.py \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit matrix truth**

```bash
git add \
  tests/fixtures/guide/presentation/frontend_mode_matrix_v1.jsonl \
  tests/guide/runtime/test_frontend_gate_matrix.py \
  tests/guide/runtime/test_backend_handoff_matrix.py \
  tests/guide/runtime/test_frontend_browser_contract.py
git commit -m "test(frontend): lock twenty presentation scenarios"
```

## Task 11: Update Copywriter Gates

**Files:**
- Modify: `tests/fixtures/guide/presentation/copy_gate_v1.jsonl`
- Modify: `tools/guide_gates/presentation_copy_gate.py`
- Modify: `tests/guide/tools/test_presentation_copy_gate.py`

- [ ] **Step 1: Add rich recommendation and revision fixtures**

Each product slot should carry 5 merged facts. The accepted draft must use at
least 4 fact IDs.

Add a rejection fixture that uses only 3 of 5 facts and expects:

```json
{"validation_error_code":"fact_coverage"}
```

- [ ] **Step 2: Add internal-language rejection fixtures**

Reject copy containing:

```text
同档排序
预算利用度
约束优先级
内部候选集
```

- [ ] **Step 3: Run copy gate unit tests and verify RED**

```bash
python3 -m pytest tests/guide/tools/test_presentation_copy_gate.py -q
```

- [ ] **Step 4: Extend gate evaluation**

Record:

```python
fact_coverage_passed: bool
minimum_fact_coverage: float
internal_language_passed: bool
```

The gate passes only when both are true.

- [ ] **Step 5: Run copy gate unit tests and verify GREEN**

```bash
python3 -m pytest tests/guide/tools/test_presentation_copy_gate.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit copy gate changes**

```bash
git add \
  tests/fixtures/guide/presentation/copy_gate_v1.jsonl \
  tools/guide_gates/presentation_copy_gate.py \
  tests/guide/tools/test_presentation_copy_gate.py
git commit -m "test(guide): gate rich presentation copy"
```

## Task 12: Focused Regression and Architecture Checkpoint

**Files:**
- Create only after two consecutive same-layer failures:
  `docs/audits/frontend-integration/final-alignment-architecture-checkpoint.md`

- [ ] **Step 1: Run the focused Python suite**

```bash
python3 -m pytest \
  tests/guide/decision/test_recommendation.py \
  tests/guide/presentation \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_presentation_history.py \
  tests/guide/runtime/test_frontend_presentation_xss.py \
  tests/guide/runtime/test_frontend_thinking_panel.py \
  tests/guide/runtime/test_frontend_evidence_rendering.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Apply the checkpoint rule when triggered**

If the same layer fails twice consecutively, stop patching and write:

```markdown
# Final Alignment Architecture Checkpoint

## Failing Layer

## Reproduction Command

## Actual Output

## Expected Contract

## Classification

- truth error
- packet missing facts
- validator too strict
- responsibility overload
- schema instability

## Minimal Boundary Fix
```

Do not add sentence-specific prompt patches.

- [ ] **Step 3: Run copy gates offline**

```bash
python3 -m pytest \
  tests/guide/tools/test_presentation_copy_gate.py \
  tests/guide/runtime/test_composition_copywriter.py \
  -q
```

Expected: PASS.

## Task 13: Full Test Suite

**Files:** none unless a regression is directly caused by this plan.

- [ ] **Step 1: Run all tests**

```bash
python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Classify any unrelated dirty-worktree failure**

For each failure, record:

```text
test node ID
whether the touched files can affect it
reproduction command
fix or explicit unrelated classification
```

Do not revert unrelated user changes.

- [ ] **Step 3: Run three official copywriter gates**

Use the repository's real gate command with three distinct run IDs:

```bash
python3 tools/guide_gates/run_real_presentation_copy_gate.py \
  --run-id final-alignment-1
python3 tools/guide_gates/run_real_presentation_copy_gate.py \
  --run-id final-alignment-2
python3 tools/guide_gates/run_real_presentation_copy_gate.py \
  --run-id final-alignment-3
```

Expected for each:

```text
provider_call_count == case_count
schema_valid_rate == 1.0
hard_atom_violation_count == 0
attribution_violation_count == 0
fact_coverage_rate == 1.0
passed == true
```

If network or credentials are unavailable, report the exact blocker. Do not
replace official gates with an offline claim.

## Task 14: Local Browser Acceptance

**Files:**
- Modify: `tools/guide_gates/frontend_presentation_browser_audit.py`
- Modify: `tests/guide/tools/test_audit_frontend_product_images.py`
- Create: `docs/audits/frontend-integration/final-alignment-browser-v1.json`
- Create: `docs/audits/frontend-integration/final-alignment-browser.md`
- Create screenshots under:
  `docs/audits/frontend-integration/screenshots/final-alignment/`

- [ ] **Step 1: Start the local application**

Use an unused port:

```bash
XIAORO_GUIDE_STATE_DIR=/tmp/xiaoro-final-alignment-state \
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8780
```

If `8780` is occupied, use the next free port and record it.

- [ ] **Step 2: Audit all 20 desktop scenarios**

Viewport:

```text
1440x900
```

For each scenario capture:

- screenshot;
- presentation mode;
- visible product IDs;
- inline card IDs;
- full card IDs;
- section order;
- thinking panel lifecycle;
- console errors;
- failed network requests;
- image failures;
- overlap and horizontal overflow.

- [ ] **Step 3: Audit all 20 mobile scenarios**

Viewport:

```text
390x844
```

Apply the same assertions. Tables may scroll internally; the page must not
have horizontal overflow.

- [ ] **Step 4: Verify streaming timing**

For recommendation and revision:

```text
before first character:
  thinking panel exists
  answer body hidden

after first character:
  thinking panel has is-leaving
  answer body visible

after 320ms:
  thinking panel absent

after product title:
  inline card exists and image naturalWidth > 0

after completion:
  one inline and one full card per visible product
  full shelf precedes pitfalls
```

- [ ] **Step 5: Verify image identity states**

Confirmed:

```text
one bound product card
```

Low confidence, ambiguous, or OCR conflict:

```text
zero cards
actionable clearer-image message
```

- [ ] **Step 6: Run product image inventory**

```bash
python3 tools/guide_data/audit_frontend_product_images.py
```

Expected:

```text
missing assets: 0
identity mismatches: 0
decode failures: 0
```

- [ ] **Step 7: Write browser evidence**

The Markdown report must include:

- tested URL and port;
- desktop and mobile counts;
- screenshot directory;
- image result;
- SSE/card/section assertions;
- console and network result;
- any residual risk.

- [ ] **Step 8: Commit browser audit artifacts**

```bash
git add \
  tools/guide_gates/frontend_presentation_browser_audit.py \
  tests/guide/tools/test_audit_frontend_product_images.py \
  docs/audits/frontend-integration/final-alignment-browser-v1.json \
  docs/audits/frontend-integration/final-alignment-browser.md \
  docs/audits/frontend-integration/screenshots/final-alignment
git commit -m "test(frontend): close final presentation browser audit"
```

## Task 15: Correct Historical Presentation Documentation

**Files:**
- Modify: `docs/audits/frontend-integration/old_frontend_behavior.md`
- Modify: `docs/audits/frontend-integration/closure_report.md`
- Create: `docs/audits/frontend-integration/final-alignment-closure.md`

- [ ] **Step 1: Mark superseded conclusions**

Document:

```text
The previous closure verified the old contract rather than the final
user-approved product behavior.
```

Correct:

- revision is product-bearing after reranking;
- ordinary evidence walls are hidden;
- full cards precede pitfalls;
- inline cards appear below product titles;
- narrative facts are merged and broadly covered;
- no green change-summary chips remain.

- [ ] **Step 2: Write final closure evidence**

Include:

```text
focused test result
full test result
three official copy gate run IDs
20 desktop screenshots
20 mobile screenshots
image inventory result
local URL
no deployment statement
```

- [ ] **Step 3: Commit documentation**

```bash
git add \
  docs/audits/frontend-integration/old_frontend_behavior.md \
  docs/audits/frontend-integration/closure_report.md \
  docs/audits/frontend-integration/final-alignment-closure.md
git commit -m "docs(frontend): record final alignment closure"
```

## Final Verification Checklist

- [ ] `translator` calls per semantic turn are at most 1.
- [ ] `copywriter` calls per eligible turn are at most 1.
- [ ] No reviewer, repair, retry, or third model call exists.
- [ ] Code owns selection, state, safety, order, and hard facts.
- [ ] Otherwise-equal candidates use budget proximity only when a maximum is
      explicit.
- [ ] Narrative atom coverage is at least 80%.
- [ ] Missing fields disappear rather than showing placeholders.
- [ ] Recommendation and revision use the full approved product structure.
- [ ] All 20 scenarios have correct cards and section order.
- [ ] Inline images appear immediately below product titles during the local
      structured stream.
- [ ] The thinking panel disappears on first answer character and leaves no
      timeline.
- [ ] Full cards precede compact pitfalls.
- [ ] Ordinary evidence walls are absent.
- [ ] Unconfirmed image identity renders zero cards.
- [ ] Desktop and mobile browser checks have no overlap or page overflow.
- [ ] Product image audit has no failures.
- [ ] Full tests pass.
- [ ] Three official copywriter gates pass.
- [ ] Work remains local; no production deployment occurs.
