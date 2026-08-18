from __future__ import annotations

from decimal import Decimal

import pytest

import app.guide.intent.contracts as intent_contracts
from app.guide.decision.contracts import (
    CandidateEvaluation,
    DecisionProductFacts,
    DecisionResult,
    FactState,
    WinnerStatus,
)
from app.guide.decision.facet_ranking import rank_soft_facets
from app.guide.decision.recommendation import decide_recommendation
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    FacetConstraint,
    SkinConstraint,
)
from app.guide.intent.task_planning import plan_task
from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.retrieval.selection_fact_contracts import SelectionFact
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
    TopicCode,
)
from app.guide.understanding.text_understanding import understand_text


_TASK32_OUTER_EXCLUSION_CUES = (
    "避开",
    "不要",
    "不想要",
    "排除",
    "拒绝",
    "不要有",
)
_TASK32_INNER_ABSENCE_CUES = ("不含", "无")
_TASK32_INGREDIENTS = ("酒精", "香精")
_TASK32_CATEGORIES = (("香水", TopicCode.FRAGRANCE),)


def test_facet_constraint_is_available_as_strict_typed_constraint() -> None:
    assert hasattr(intent_contracts, "FacetConstraint")

    constraint = intent_contracts.FacetConstraint(
        field_key="finish",
        value="自然裸妆",
    )

    assert constraint.kind == "facet"
    assert constraint.field_key == "finish"
    assert constraint.value == "自然裸妆"


class MemoryFacts:
    def __init__(self, products: list[DecisionProductFacts]) -> None:
        self._products = {item.product_id: item for item in products}

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        return self._products[product_id].model_copy(deep=True)


def facts(
    product_id: int,
    *,
    category_profile: CategoryProfile,
    category_fields: tuple[AuthorizedCategoryFact, ...],
    price: Decimal | None = Decimal("100"),
    price_state: FactState = FactState.KNOWN,
    efficacy: tuple[str, ...] | None = None,
    efficacy_state: FactState = FactState.UNKNOWN,
    skin: tuple[str, ...] | None = ("油敏",),
    skin_state: FactState = FactState.KNOWN,
    ingredients: tuple[str, ...] | None = ("水",),
    ingredients_state: FactState = FactState.KNOWN,
    absences: tuple[str, ...] | None = ("酒精",),
    absences_state: FactState = FactState.KNOWN,
    selection_facts: tuple[SelectionFact, ...] = (),
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=category_profile,
        category_fields=category_fields,
        price=price,
        price_state=price_state,
        efficacy=efficacy,
        efficacy_state=efficacy_state,
        suitable_skin=skin,
        suitable_skin_state=skin_state,
        ingredients_present=ingredients,
        ingredients_present_state=ingredients_state,
        verified_absences=absences,
        verified_absences_state=absences_state,
        selection_facts=selection_facts,
    )


def _suncare_facts(
    product_id: int,
    **overrides,
) -> DecisionProductFacts:
    return facts(
        product_id,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        **overrides,
    )


def _skincare_facts(
    product_id: int,
    **overrides,
) -> DecisionProductFacts:
    return facts(
        product_id,
        category_profile=CategoryProfile.SKINCARE,
        category_fields=(),
        **overrides,
    )


def _finish_fact(
    value: tuple[str, ...],
    *,
    soft_rank: bool = True,
) -> AuthorizedCategoryFact:
    return AuthorizedCategoryFact(
        category_profile=CategoryProfile.COLOR_MAKEUP,
        field_key="finish",
        value=value,
        resolved_state="known",
        source_classes=(
            SourceClass.MERCHANT_PARAMETER
            if soft_rank
            else SourceClass.OFFICIAL_PACKAGING,
        ),
        source_refs=("urn:test:finish",),
        capabilities=(
            frozenset({
                "evidence",
                "display",
                "compare",
                "soft_rank",
            })
            if soft_rank
            else frozenset({"evidence", "display", "compare"})
        ),
    )


def _selection_fact(
    *,
    product_id: int,
    field_key: str,
    value: str,
    strength: int | None,
    profile: CategoryProfile = CategoryProfile.COLOR_MAKEUP,
    safety_role: str = "ordinary",
    subject_scope: str = "exact_product",
    variant_scope: str | None = None,
    source_refs: tuple[str, ...] = ("source-a",),
    capabilities: tuple[str, ...] = ("compare", "soft_rank"),
    attributions: tuple[str, ...] = ("merchant_claim",),
) -> SelectionFact:
    return SelectionFact.model_validate(
        {
            "product_id": product_id,
            "category_profile": profile.value,
            "subject_scope": subject_scope,
            "variant_scope": variant_scope,
            "field_key": field_key,
            "normalized_value": value,
            "rank_strength": strength,
            "safety_role": safety_role,
            "capabilities": list(capabilities),
            "source_refs": list(source_refs),
            "attributions": list(attributions),
        },
        strict=True,
    )


def _color_makeup_facts(
    product_id: int,
    *,
    price: Decimal,
    category_fields: tuple[AuthorizedCategoryFact, ...] = (),
    selection_facts: tuple[SelectionFact, ...] = (),
) -> DecisionProductFacts:
    if not selection_facts:
        projected: list[SelectionFact] = []
        for fact in category_fields:
            if (
                fact.resolved_state != "known"
                or "soft_rank" not in fact.capabilities
            ):
                continue
            values = (
                (fact.value,)
                if isinstance(fact.value, str)
                else fact.value
            )
            if not isinstance(values, tuple):
                continue
            projected.extend(
                _selection_fact(
                    product_id=product_id,
                    field_key=fact.field_key,
                    value=value,
                    strength=1,
                    source_refs=fact.source_refs,
                )
                for value in values
            )
        selection_facts = tuple(
            sorted(
                projected,
                key=lambda item: (
                    item.field_key,
                    item.normalized_value.casefold(),
                ),
            )
        )
    return facts(
        product_id,
        category_profile=CategoryProfile.COLOR_MAKEUP,
        category_fields=category_fields,
        price=price,
        selection_facts=selection_facts,
    )


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
    if facet is not None:
        constraints.append(facet)
    if exclude is not None:
        constraints.append(ExclusionConstraint(value=exclude))
    retrieval = RetrievalResult(
        candidates=[
            CandidateRef(
                product_id=item.product_id,
                source="canonical",
                canonical_category="口红",
                retrieval_reason="test",
            )
            for item in products
        ],
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[],
    )
    return decide_recommendation(
        MemoryFacts(products),
        retrieval,
        constraints=constraints,
    )


def decide_with(
    products: list[DecisionProductFacts],
    *,
    include_skin: bool = True,
    exclude: str | None = None,
    topic: TopicCode = TopicCode.SUNSCREEN,
    efficacy: EfficacyTarget | None = None,
    skin_target: SkinTarget = SkinTarget.OILY_SENSITIVE,
    include: str | None = None,
) -> DecisionResult:
    constraints = [
        CategoryConstraint(value=topic),
        BudgetConstraint(minimum=None, maximum=Decimal("500")),
    ]
    if include_skin:
        constraints.append(SkinConstraint(value=skin_target))
    if efficacy is not None:
        constraints.append(EfficacyConstraint(value=efficacy))
    if exclude is not None:
        constraints.append(ExclusionConstraint(value=exclude))
    if include is not None:
        constraints.append(
            intent_contracts.InclusionConstraint(value=include)
        )
    canonical_category = (
        "精华" if topic is TopicCode.SERUM else "防晒"
    )
    retrieval = RetrievalResult(
        candidates=[
            CandidateRef(
                product_id=item.product_id,
                source="canonical",
                canonical_category=canonical_category,
                retrieval_reason="test",
            )
            for item in products
        ],
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[],
    )
    return decide_recommendation(
        MemoryFacts(products),
        retrieval,
        constraints=constraints,
    )


def evaluation(
    result: DecisionResult,
    product_id: int,
) -> CandidateEvaluation:
    return next(
        item
        for item in result.evaluations
        if item.product_id == product_id
    )


def test_finish_soft_rank_orders_match_then_unknowns_by_budget_proximity() -> None:
    products = [
        _color_makeup_facts(
            10,
            price=Decimal("100"),
            category_fields=(_finish_fact(("哑光",)),),
        ),
        _color_makeup_facts(20, price=Decimal("200")),
        _color_makeup_facts(
            30,
            price=Decimal("300"),
            category_fields=(_finish_fact(("自然裸妆",)),),
        ),
    ]

    result = _decide_color_makeup(
        products,
        facet=FacetConstraint(
            field_key="finish",
            value="自然裸妆",
        ),
    )

    assert result.ordered_product_ids == [30, 20, 10]
    assert all(
        item.disposition == "eligible"
        for item in result.evaluations
    )
    assert "facet:finish" in result.comparison_dimensions


def test_weighted_soft_rank_orders_matches_then_unknowns_by_budget_proximity() -> None:
    products = [
        _color_makeup_facts(
            10,
            price=Decimal("100"),
            selection_facts=(
                _selection_fact(
                    product_id=10,
                    field_key="finish",
                    value="自然",
                    strength=1,
                ),
            ),
        ),
        _color_makeup_facts(
            20,
            price=Decimal("300"),
            selection_facts=(
                _selection_fact(
                    product_id=20,
                    field_key="finish",
                    value="自然",
                    strength=2,
                ),
            ),
        ),
        _color_makeup_facts(30, price=Decimal("50")),
        _color_makeup_facts(
            40,
            price=Decimal("10"),
            selection_facts=(
                _selection_fact(
                    product_id=40,
                    field_key="finish",
                    value="哑光",
                    strength=2,
                ),
            ),
        ),
    ]

    result = _decide_color_makeup(
        products,
        facet=FacetConstraint(field_key="finish", value="自然"),
    )

    assert result.ordered_product_ids == [20, 10, 30, 40]


def test_repeated_sources_fill_one_requested_slot_once() -> None:
    product = _color_makeup_facts(
        10,
        price=Decimal("100"),
        selection_facts=(
            _selection_fact(
                product_id=10,
                field_key="finish",
                value="自然",
                strength=1,
                source_refs=(
                    "claim-a",
                    "claim-b",
                    "claim-c",
                    "image-a",
                    "image-b",
                ),
            ),
        ),
    )

    ranking = rank_soft_facets(
        product,
        (FacetConstraint(field_key="finish", value="自然"),),
    )

    assert ranking.weighted_match_score == 1
    assert ranking.matched_slot_count == 1
    assert ranking.matched_source_refs == (
        "claim-a",
        "claim-b",
        "claim-c",
        "image-a",
        "image-b",
    )
    assert len(ranking.slots) == 1
    assert ranking.slots[0].match_status == "matched"
    assert ranking.slots[0].rank_strength == 1
    assert ranking.slots[0].attribution == "merchant_claim"


def test_two_requested_values_score_as_two_independent_slots() -> None:
    product = facts(
        10,
        category_profile=CategoryProfile.SKINCARE,
        category_fields=(),
        selection_facts=(
            _selection_fact(
                product_id=10,
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                value="保湿",
                strength=2,
            ),
            _selection_fact(
                product_id=10,
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                value="舒缓",
                strength=1,
                source_refs=("source-b",),
            ),
        ),
    )

    ranking = rank_soft_facets(
        product,
        (
            FacetConstraint(field_key="efficacy", value="保湿"),
            FacetConstraint(field_key="efficacy", value="舒缓"),
        ),
    )

    assert ranking.weighted_match_score == 3
    assert ranking.matched_slot_count == 2
    assert ranking.mismatch_count == 0
    assert ranking.unknown_count == 0


def test_variant_fact_does_not_leak_into_product_rank() -> None:
    product = _color_makeup_facts(
        10,
        price=Decimal("100"),
        selection_facts=(
            _selection_fact(
                product_id=10,
                field_key="finish",
                value="自然",
                strength=2,
                subject_scope="exact_variant",
                variant_scope="限定版",
            ),
        ),
    )

    ranking = rank_soft_facets(
        product,
        (FacetConstraint(field_key="finish", value="自然"),),
    )

    assert ranking.weighted_match_score == 0
    assert ranking.matched_slot_count == 0
    assert ranking.unknown_count == 1


def test_merchant_positive_safety_only_scores_ordinary_preference() -> None:
    product = facts(
        10,
        category_profile=CategoryProfile.SKINCARE,
        category_fields=(),
        selection_facts=(
            _selection_fact(
                product_id=10,
                profile=CategoryProfile.SKINCARE,
                field_key="suitable_skin",
                value="敏感肌",
                strength=1,
                safety_role="merchant_positive_safety",
            ),
        ),
    )
    constraints = (
        FacetConstraint(field_key="suitable_skin", value="敏感肌"),
    )

    ordinary = rank_soft_facets(product, constraints)
    serious = rank_soft_facets(
        product,
        constraints,
        safety_sensitive=True,
    )

    assert ordinary.weighted_match_score == 1
    assert serious.weighted_match_score == 0
    assert serious.unknown_count == 1


def test_decision_facts_reject_duplicate_selection_identities() -> None:
    with pytest.raises(
        ValueError,
        match="selection facts must have unique identities",
    ):
        _color_makeup_facts(
            10,
            price=Decimal("100"),
            selection_facts=(
                _selection_fact(
                    product_id=10,
                    field_key="finish",
                    value="自然",
                    strength=1,
                ),
                _selection_fact(
                    product_id=10,
                    field_key="finish",
                    value="自然",
                    strength=2,
                    source_refs=("source-b",),
                ),
            ),
        )


def test_decision_facts_require_sorted_selection_facts() -> None:
    with pytest.raises(
        ValueError,
        match="selection facts must be sorted",
    ):
        _color_makeup_facts(
            10,
            price=Decimal("100"),
            selection_facts=(
                _selection_fact(
                    product_id=10,
                    field_key="finish",
                    value="自然",
                    strength=1,
                ),
                _selection_fact(
                    product_id=10,
                    field_key="finish",
                    value="哑光",
                    strength=1,
                    source_refs=("source-b",),
                ),
            ),
        )


def test_hard_inclusion_requires_verified_hard_filter_fact() -> None:
    verified = _skincare_facts(
        1,
        selection_facts=(
            _selection_fact(
                product_id=1,
                profile=CategoryProfile.SKINCARE,
                field_key="ingredients_present",
                value="烟酰胺",
                strength=2,
                capabilities=(
                    "compare",
                    "soft_rank",
                    "hard_filter",
                ),
            ),
        ),
    )
    claimed = _skincare_facts(
        2,
        selection_facts=(
            _selection_fact(
                product_id=2,
                profile=CategoryProfile.SKINCARE,
                field_key="claimed_ingredients",
                value="烟酰胺",
                strength=1,
            ),
        ),
    )

    result = decide_with(
        [claimed, verified],
        topic=TopicCode.SERUM,
        include_skin=False,
        include="烟酰胺",
    )

    assert result.ordered_product_ids == [1]
    assert evaluation(result, 1).disposition == "eligible"
    assert evaluation(result, 2).disposition == (
        "excluded_evidence_unknown"
    )


@pytest.mark.parametrize(
    ("fact_field", "requested_field"),
    (
        ("claimed_ingredients", "ingredients_present"),
        ("claimed_absences", "verified_absences"),
    ),
)
def test_ordinary_ingredient_slot_accepts_weak_claim_alias(
    fact_field: str,
    requested_field: str,
) -> None:
    product = _skincare_facts(
        1,
        selection_facts=(
            _selection_fact(
                product_id=1,
                profile=CategoryProfile.SKINCARE,
                field_key=fact_field,
                value="酒精",
                strength=1,
            ),
        ),
    )

    ranking = rank_soft_facets(
        product,
        (
            FacetConstraint(
                field_key=requested_field,
                value="酒精",
            ),
        ),
    )

    assert ranking.weighted_match_score == 1
    assert ranking.matched_slot_count == 1


def test_finish_soft_rank_matches_canonical_value_inside_fact_phrase() -> None:
    products = [
        _color_makeup_facts(
            10,
            price=Decimal("100"),
            category_fields=(_finish_fact(("哑光柔雾肌",)),),
        ),
        _color_makeup_facts(20, price=Decimal("200")),
        _color_makeup_facts(
            30,
            price=Decimal("300"),
            category_fields=(_finish_fact(("自然裸妆",)),),
        ),
    ]

    result = _decide_color_makeup(
        products,
        facet=FacetConstraint(
            field_key="finish",
            value="哑光",
        ),
    )

    assert result.ordered_product_ids == [10, 30, 20]


def test_finish_without_soft_rank_capability_cannot_change_order() -> None:
    products = [
        _color_makeup_facts(10, price=Decimal("100")),
        _color_makeup_facts(
            20,
            price=Decimal("200"),
            category_fields=(
                _finish_fact(("自然裸妆",), soft_rank=False),
            ),
        ),
    ]

    result = _decide_color_makeup(
        products,
        facet=FacetConstraint(
            field_key="finish",
            value="自然裸妆",
        ),
    )

    assert result.ordered_product_ids == [20, 10]
    assert all(
        item.disposition == "eligible"
        for item in result.evaluations
    )


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


def test_without_explicit_maximum_keeps_existing_price_order() -> None:
    products = [
        _color_makeup_facts(
            10,
            price=Decimal("100"),
            category_fields=(_finish_fact(("哑光",)),),
        ),
        _color_makeup_facts(20, price=Decimal("200")),
        _color_makeup_facts(
            30,
            price=Decimal("300"),
            category_fields=(_finish_fact(("自然裸妆",)),),
        ),
    ]

    constraints = [
        CategoryConstraint(value=TopicCode.COLOR_MAKEUP),
    ]
    retrieval = RetrievalResult(
        candidates=[
            CandidateRef(
                product_id=item.product_id,
                source="canonical",
                canonical_category="口红",
                retrieval_reason="test",
            )
            for item in products
        ],
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[],
    )
    result = decide_recommendation(
        MemoryFacts(products),
        retrieval,
        constraints=constraints,
    )

    assert result.ordered_product_ids == [10, 20, 30]
    assert result.winner_status is WinnerStatus.SELECTED
    assert result.winner_product_id == 10
    assert result.comparison_dimensions == ["price"]
    assert result.evidence_refs == [
        "category=color_makeup",
    ]
    assert all(
        item.disposition == "eligible"
        for item in result.evaluations
    )


def test_hard_exclusion_dominates_matching_soft_facet() -> None:
    products = [
        facts(
            10,
            category_profile=CategoryProfile.COLOR_MAKEUP,
            category_fields=(_finish_fact(("哑光柔雾肌",)),),
            price=Decimal("100"),
            ingredients=("水", "酒精"),
            absences=(),
        ),
        facts(
            20,
            category_profile=CategoryProfile.COLOR_MAKEUP,
            category_fields=(_finish_fact(("自然裸妆",)),),
            price=Decimal("200"),
            ingredients=("水",),
            absences=("酒精",),
        ),
    ]

    result = _decide_color_makeup(
        products,
        facet=FacetConstraint(field_key="finish", value="哑光"),
        exclude="酒精",
    )

    assert result.ordered_product_ids == [20]
    assert evaluation(result, 10).disposition == (
        "excluded_exclusion_match"
    )
    assert evaluation(result, 20).disposition == "eligible"


def test_category_constraint_filters_cross_category_image_recall() -> None:
    products = [
        _suncare_facts(1),
        _suncare_facts(2, price=Decimal("50")),
    ]
    retrieval = RetrievalResult(
        candidates=[
            CandidateRef(
                product_id=1,
                source="image_index",
                canonical_category="防晒乳",
                retrieval_reason="visual_rank=1",
            ),
            CandidateRef(
                product_id=2,
                source="image_index",
                canonical_category="面霜",
                retrieval_reason="visual_rank=2",
            ),
        ],
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[],
    )

    result = decide_recommendation(
        MemoryFacts(products),
        retrieval,
        constraints=[
            CategoryConstraint(value=TopicCode.SUNSCREEN),
            BudgetConstraint(
                minimum=None,
                maximum=Decimal("500"),
            ),
        ],
    )

    assert result.ordered_product_ids == [1]
    assert evaluation(result, 2).disposition == (
        "excluded_category_mismatch"
    )
    assert "category=sunscreen" in result.evidence_refs


def test_category_conflict_is_fail_closed_and_recorded() -> None:
    product = _suncare_facts(1)
    retrieval = RetrievalResult(
        candidates=[
            CandidateRef(
                product_id=1,
                source="image_index",
                canonical_category="",
                canonical_category_state="conflict",
                retrieval_reason="visual_rank=1",
            )
        ],
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[],
    )

    result = decide_recommendation(
        MemoryFacts([product]),
        retrieval,
        constraints=[
            CategoryConstraint(value=TopicCode.SUNSCREEN),
        ],
    )

    assert result.ordered_product_ids == []
    assert evaluation(result, 1).disposition == (
        "excluded_category_unknown"
    )
    assert evaluation(result, 1).reasons == [
        "canonical_category_state=conflict"
    ]
    assert result.risk_findings[0].kind == "canonical_fact_conflict"


@pytest.mark.parametrize(
    "generic_claim",
    (
        "多种肤质适用",
        "全肤质适用",
        "通用",
    ),
)
@pytest.mark.parametrize(
    "target",
    (
        SkinTarget.OILY_SENSITIVE,
        SkinTarget.OILY,
        SkinTarget.DRY,
        SkinTarget.COMBINATION,
        SkinTarget.SENSITIVE,
        SkinTarget.NORMAL,
    ),
)
def test_generic_skin_claim_is_unknown_for_every_target(
    target: SkinTarget,
    generic_claim: str,
) -> None:
    result = decide_with(
        [
            _skincare_facts(
                1,
                skin=(generic_claim,),
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            )
        ],
        topic=TopicCode.SERUM,
        efficacy=EfficacyTarget.REPAIR,
        skin_target=target,
    )

    assert result.ordered_product_ids == [1]
    assert evaluation(result, 1).skin_match == "unknown"
    assert result.winner_status is WinnerStatus.INSUFFICIENT_FOR_WINNER


@pytest.mark.parametrize(
    ("target", "known_claim"),
    (
        (EfficacyTarget.HYDRATION, "长效保湿"),
        (EfficacyTarget.SOOTHING, "舒缓泛红"),
        (EfficacyTarget.REPAIR, "屏障修护"),
        (EfficacyTarget.ANTI_AGING, "抗老淡纹"),
        (EfficacyTarget.BRIGHTENING, "提亮肤色"),
        (EfficacyTarget.OIL_CONTROL, "控油"),
        (EfficacyTarget.ACNE_CARE, "祛痘护理"),
    ),
)
def test_closed_efficacy_matches_only_known_canonical_claim(
    target: EfficacyTarget,
    known_claim: str,
) -> None:
    known = decide_with(
        [
            _skincare_facts(
                1,
                efficacy=(known_claim,),
                efficacy_state=FactState.KNOWN,
            )
        ],
        topic=TopicCode.SERUM,
        efficacy=target,
    )
    unknown = decide_with(
        [
            _skincare_facts(
                2,
                efficacy=None,
                efficacy_state=FactState.UNKNOWN,
            )
        ],
        topic=TopicCode.SERUM,
        efficacy=target,
    )

    assert known.ordered_product_ids == [1]
    assert evaluation(known, 1).efficacy_match == "matched"
    assert unknown.ordered_product_ids == []
    assert evaluation(unknown, 2).efficacy_match == "unknown"


@pytest.mark.parametrize(
    ("target", "explicit_other_skin"),
    (
        (SkinTarget.OILY_SENSITIVE, "干性肌肤适用"),
        (SkinTarget.OILY, "干性肌肤适用"),
        (SkinTarget.DRY, "油性肌肤适用"),
        (SkinTarget.COMBINATION, "中性肌肤适用"),
        (SkinTarget.SENSITIVE, "干性肌肤适用"),
        (SkinTarget.NORMAL, "干性肌肤适用"),
    ),
)
def test_explicit_other_skin_is_mismatch(
    target: SkinTarget,
    explicit_other_skin: str,
) -> None:
    result = decide_with(
        [_suncare_facts(1, skin=(explicit_other_skin,))],
        skin_target=target,
    )

    assert result.ordered_product_ids == []
    assert evaluation(result, 1).skin_match == "mismatch"


def test_price_unknown_and_boolean_conflict_are_excluded() -> None:
    result = decide_with([
        _suncare_facts(
            1,
            price=None,
            price_state=FactState.UNKNOWN,
        ),
        _suncare_facts(
            2,
            price=None,
            price_state=FactState.CONFLICT,
        ),
        _suncare_facts(
            3,
            price=Decimal("100"),
            price_state=FactState.KNOWN,
        ),
    ])
    assert result.ordered_product_ids == [3]


def test_a2_keeps_unknown_but_excludes_known_mismatch() -> None:
    result = decide_with([
        _suncare_facts(
            1,
            skin=("油敏",),
            skin_state=FactState.KNOWN,
        ),
        _suncare_facts(
            2,
            skin=None,
            skin_state=FactState.UNKNOWN,
        ),
        _suncare_facts(
            3,
            skin=("干性",),
            skin_state=FactState.KNOWN,
        ),
    ])
    assert result.ordered_product_ids == [1, 2]
    assert evaluation(result, 1).skin_match == "matched"
    assert evaluation(result, 2).skin_match == "unknown"
    assert evaluation(result, 3).disposition == "excluded_skin_mismatch"


def test_repair_is_hard_evidence_constraint() -> None:
    result = decide_with(
        [
            _skincare_facts(
                1,
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            ),
            _skincare_facts(
                2,
                efficacy=("美白",),
                efficacy_state=FactState.KNOWN,
            ),
            _skincare_facts(
                3,
                efficacy=None,
                efficacy_state=FactState.UNKNOWN,
            ),
        ],
        topic=TopicCode.SERUM,
        efficacy=EfficacyTarget.REPAIR,
        include_skin=False,
    )

    assert result.ordered_product_ids == [1]
    assert evaluation(result, 1).efficacy_match == "matched"
    assert evaluation(result, 1).matched_efficacies == ["修护"]
    assert evaluation(result, 2).disposition == (
        "excluded_efficacy_mismatch"
    )
    assert evaluation(result, 3).disposition == (
        "excluded_efficacy_unknown"
    )


def test_efficacy_conflict_is_fail_closed_and_recorded() -> None:
    result = decide_with(
        [
            _skincare_facts(
                1,
                efficacy=None,
                efficacy_state=FactState.CONFLICT,
            )
        ],
        topic=TopicCode.SERUM,
        efficacy=EfficacyTarget.REPAIR,
        include_skin=False,
    )

    assert result.ordered_product_ids == []
    assert evaluation(result, 1).disposition == (
        "excluded_efficacy_unknown"
    )
    assert result.risk_findings[0].kind == "canonical_fact_conflict"


def test_sensitive_skin_generic_claim_is_unknown_not_mismatch() -> None:
    result = decide_with(
        [
            _skincare_facts(
                1,
                price=Decimal("200"),
                skin=("敏感肌适用",),
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            ),
            _skincare_facts(
                2,
                price=Decimal("100"),
                skin=("多种肤质适用",),
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            ),
            _skincare_facts(
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
    assert evaluation(result, 3).disposition == (
        "excluded_skin_mismatch"
    )


def test_all_unknown_sensitive_matches_do_not_create_winner() -> None:
    result = decide_with(
        [
            _skincare_facts(
                38,
                price=Decimal("294"),
                skin=("多种肤质适用",),
                efficacy=("修护",),
                efficacy_state=FactState.KNOWN,
            ),
            _skincare_facts(
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

    assert result.ordered_product_ids == [38, 91]
    assert result.winner_status is WinnerStatus.INSUFFICIENT_FOR_WINNER
    assert result.winner_product_id is None


def test_no_skin_constraint_is_not_applicable() -> None:
    result = decide_with(
        [
            _suncare_facts(
                1,
                skin=None,
                skin_state=FactState.UNKNOWN,
            )
        ],
        include_skin=False,
    )
    assert evaluation(result, 1).skin_match == "not_applicable"
    assert result.risk_findings == []


def test_exclusion_unknown_is_fail_closed() -> None:
    result = decide_with([
        _suncare_facts(
            1,
            ingredients=None,
            ingredients_state=FactState.UNKNOWN,
            absences=None,
            absences_state=FactState.UNKNOWN,
        )
    ], exclude="酒精")
    assert result.ordered_product_ids == []
    assert evaluation(result, 1).disposition == "excluded_evidence_unknown"


def test_arbitrary_exclusion_unknown_is_fail_closed() -> None:
    result = decide_with([
        _suncare_facts(
            1,
            ingredients=None,
            ingredients_state=FactState.UNKNOWN,
            absences=None,
            absences_state=FactState.UNKNOWN,
        )
    ], exclude="矿物油")

    assert result.ordered_product_ids == []
    assert evaluation(result, 1).disposition == "excluded_evidence_unknown"


def test_exclusion_conflict_is_fail_closed_and_recorded() -> None:
    result = decide_with(
        [
            _suncare_facts(
                1,
                ingredients=None,
                ingredients_state=FactState.CONFLICT,
                absences=("酒精",),
                absences_state=FactState.KNOWN,
            )
        ],
        exclude="酒精",
    )

    assert result.ordered_product_ids == []
    assert evaluation(result, 1).disposition == "excluded_evidence_unknown"
    assert result.risk_findings[0].kind == "canonical_fact_conflict"
    assert result.risk_findings[0].detail == (
        "排除项成分事实冲突，已按 fail-closed 排除"
    )


def test_exclusion_known_present_is_excluded() -> None:
    result = decide_with([
        _suncare_facts(
            1,
            ingredients=("水", "酒精"),
            absences=(),
        )
    ], exclude="酒精")
    assert result.ordered_product_ids == []
    assert evaluation(result, 1).disposition == "excluded_exclusion_match"


@pytest.mark.parametrize(
    "cue",
    ["不要有", "不要含", "不含", "不能有", "无"],
)
@pytest.mark.parametrize("ingredient", ["酒精", "香精"])
def test_task31_parsed_exclusion_matches_present_ingredient(
    cue: str,
    ingredient: str,
) -> None:
    task = plan_task(
        understand_text(f"{cue}{ingredient}的香水")
    )
    exclusions = [
        item.value
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    product = facts(
        1,
        category_profile=CategoryProfile.FRAGRANCE,
        category_fields=(),
        ingredients=("水", ingredient),
        absences=(),
    )
    retrieval = RetrievalResult(
        candidates=[
            CandidateRef(
                product_id=1,
                source="canonical",
                canonical_category="香水",
                retrieval_reason="test",
            )
        ],
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[],
    )

    result = decide_recommendation(
        MemoryFacts([product]),
        retrieval,
        constraints=task.constraints,
    )

    assert result.ordered_product_ids == []
    assert evaluation(result, 1).disposition == (
        "excluded_exclusion_match"
    )
    assert exclusions == [ingredient]


@pytest.mark.parametrize("outer_cue", _TASK32_OUTER_EXCLUSION_CUES)
@pytest.mark.parametrize("inner_cue", _TASK32_INNER_ABSENCE_CUES)
@pytest.mark.parametrize("ingredient", _TASK32_INGREDIENTS)
@pytest.mark.parametrize(("category", "topic"), _TASK32_CATEGORIES)
def test_task32_nested_absence_does_not_feed_reversed_exclusion_to_decision(
    outer_cue: str,
    inner_cue: str,
    ingredient: str,
    category: str,
    topic: TopicCode,
) -> None:
    task = plan_task(
        understand_text(f"{outer_cue}{inner_cue}{ingredient}的{category}")
    )

    categories = [
        item.value
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    ]
    exclusions = [
        item.value
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    assert task.mode == "clarify"
    assert categories == [topic]
    assert exclusions == []
    assert task.required_evidence == []


def test_verified_absence_satisfies_exclusion() -> None:
    result = decide_with([
        _suncare_facts(
            1,
            ingredients=("水",),
            absences=("酒精",),
        )
    ], exclude="酒精")
    assert result.ordered_product_ids == [1]


def test_business_tie_does_not_select_product_id_winner() -> None:
    result = decide_with([
        _suncare_facts(
            1,
            price=Decimal("100"),
            skin=("油敏",),
        ),
        _suncare_facts(
            2,
            price=Decimal("100"),
            skin=("油敏",),
        ),
    ])
    assert result.winner_status is WinnerStatus.TIED_BY_BUSINESS_EVIDENCE
    assert result.winner_product_id is None
    assert result.tie_reason is not None


@pytest.mark.parametrize(
    "category_fact",
    (
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.SUNCARE,
            field_key="water_resistance",
            value=None,
            resolved_state="unknown",
            source_classes=(SourceClass.UNKNOWN,),
            source_refs=(),
            capabilities=frozenset({"evidence"}),
        ),
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.SUNCARE,
            field_key="water_resistance",
            value=None,
            resolved_state="conflict",
            source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
            source_refs=("urn:task9:conflict",),
            capabilities=frozenset({"evidence"}),
        ),
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.SUNCARE,
            field_key="water_resistance",
            value="authorized rank fact",
            resolved_state="known",
            source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
            source_refs=("urn:task9:authorized-rank",),
            capabilities=frozenset(
                {"evidence", "hard_filter", "soft_rank"}
            ),
        ),
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.SUNCARE,
            field_key="water_resistance",
            value="display only",
            resolved_state="known",
            source_classes=(SourceClass.OFFICIAL_DESCRIPTION,),
            source_refs=("urn:task9:display-only",),
            capabilities=frozenset({"evidence", "display"}),
        ),
        AuthorizedCategoryFact(
            category_profile=CategoryProfile.SUNCARE,
            field_key="water_resistance",
            value="compare only",
            resolved_state="known",
            source_classes=(SourceClass.OFFICIAL_PACKAGING,),
            source_refs=("urn:task9:compare-only",),
            capabilities=frozenset({"evidence", "compare"}),
        ),
    ),
)
def test_category_facts_do_not_change_current_recommendation_policy(
    category_fact: AuthorizedCategoryFact,
) -> None:
    baseline = decide_with(
        [
            _suncare_facts(1, price=Decimal("100")),
            _suncare_facts(2, price=Decimal("100")),
        ]
    )
    poisoned = decide_with(
        [
            _suncare_facts(1, price=Decimal("100")),
            facts(
                2,
                category_profile=CategoryProfile.SUNCARE,
                category_fields=(category_fact,),
                price=Decimal("100"),
            ),
        ]
    )

    assert poisoned.model_dump(mode="json") == baseline.model_dump(
        mode="json"
    )


def test_evidence_uses_actual_category_constraint() -> None:
    result = decide_with([_suncare_facts(1)])
    assert "category=sunscreen" in result.evidence_refs
    assert all("category=防晒" not in ref for ref in result.evidence_refs)
