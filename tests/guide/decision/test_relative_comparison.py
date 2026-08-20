from __future__ import annotations

from decimal import Decimal

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.decision.recommendation import decide_recommendation
from app.guide.decision.relative_comparison import (
    compare_relative_candidate,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.intent.contracts import (
    CategoryConstraint,
    RelativeRequirement,
)
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.retrieval.selection_fact_contracts import SelectionFact
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptProjection,
    candidate_id_for,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)
from app.guide.understanding.contracts import ReferenceDraft, TopicCode


def _fact(
    product_id: int,
    *,
    field_key: str,
    value: str,
    strength: int,
    source_ref: str,
) -> SelectionFact:
    return SelectionFact.model_validate(
        {
            "product_id": product_id,
            "category_profile": "skincare",
            "subject_scope": "exact_product",
            "variant_scope": None,
            "field_key": field_key,
            "normalized_value": value,
            "rank_strength": strength,
            "safety_role": "ordinary",
            "capabilities": ["compare", "soft_rank"],
            "source_refs": [source_ref],
            "attributions": ["merchant_claim"],
        },
        strict=True,
    )


def _product(
    product_id: int,
    *,
    price: str | None,
    price_refs: tuple[str, ...] = (),
    selection_facts: tuple[SelectionFact, ...] = (),
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SKINCARE,
        category_fields=(),
        price=Decimal(price) if price is not None else None,
        price_state=(
            FactState.KNOWN if price is not None else FactState.UNKNOWN
        ),
        efficacy=None,
        efficacy_state=FactState.UNKNOWN,
        suitable_skin=None,
        suitable_skin_state=FactState.UNKNOWN,
        ingredients_present=None,
        ingredients_present_state=FactState.UNKNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
        price_source_refs=price_refs,
        selection_facts=tuple(
            sorted(
                selection_facts,
                key=lambda item: (
                    item.field_key,
                    item.normalized_value.casefold(),
                ),
            )
        ),
    )


def _projection(
    *,
    field_key: str,
    value: str,
    concept_id: str,
    source_refs: tuple[str, ...],
    comparability: str = "binary",
    order_value: int | None = None,
) -> SelectionConceptProjection:
    return SelectionConceptProjection.model_validate(
        {
            "candidate_id": candidate_id_for(
                profile="skincare",
                field_key=field_key,
                normalized_value=value,
                product_ids=(1, 2),
                rank_strengths=(1, 2),
                source_refs=source_refs,
            ),
            "profile": "skincare",
            "field_key": field_key,
            "normalized_value": value,
            "product_ids": [1, 2],
            "rank_strengths": [1, 2],
            "source_refs": list(source_refs),
            "concept_id": concept_id,
            "stance": "supports",
            "comparability": comparability,
            "order_value": order_value,
            "rationale": "用于验证有边界的相对比较合同。",
        },
        strict=True,
    )


def test_lower_price_uses_numeric_comparison() -> None:
    result = compare_relative_candidate(
        candidate=_product(
            1,
            price="100",
            price_refs=("price-1",),
        ),
        baseline=_product(
            2,
            price="200",
            price_refs=("price-2",),
        ),
        field_key="price",
        concept_id=None,
        direction="lower",
        reader=None,
    )

    assert result.status == "better"
    assert result.relation_kind == "numeric"
    assert result.source_refs == ("price-1", "price-2")
    assert result.effect_claim_supported


def test_binary_support_over_unknown_is_better_preference_match() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                field_key="texture",
                value="清爽",
                concept_id="texture.refreshing",
                source_refs=("source-1",),
            ),
        )
    )
    result = compare_relative_candidate(
        candidate=_product(
            1,
            price="100",
            selection_facts=(
                _fact(
                    1,
                    field_key="texture",
                    value="清爽",
                    strength=1,
                    source_ref="source-1",
                ),
            ),
        ),
        baseline=_product(2, price="100"),
        field_key="texture",
        concept_id="texture.refreshing",
        direction="higher",
        reader=reader,
    )

    assert result.status == "better"
    assert result.relation_kind == "better_preference_match"
    assert not result.effect_claim_supported


def test_stronger_binary_evidence_is_not_stronger_effect() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                field_key="efficacy",
                value="舒缓",
                concept_id="efficacy.soothing",
                source_refs=("source-1", "source-2"),
            ),
        )
    )
    result = compare_relative_candidate(
        candidate=_product(
            1,
            price="100",
            selection_facts=(
                _fact(
                    1,
                    field_key="efficacy",
                    value="舒缓",
                    strength=2,
                    source_ref="source-1",
                ),
            ),
        ),
        baseline=_product(
            2,
            price="100",
            selection_facts=(
                _fact(
                    2,
                    field_key="efficacy",
                    value="舒缓",
                    strength=1,
                    source_ref="source-2",
                ),
            ),
        ),
        field_key="efficacy",
        concept_id="efficacy.soothing",
        direction="higher",
        reader=reader,
    )

    assert result.status == "better"
    assert result.relation_kind == "better_evidence_support"
    assert not result.effect_claim_supported


def test_ordered_values_support_directional_comparison() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                field_key="texture",
                value="厚重",
                concept_id="texture.richness",
                source_refs=("source-1",),
                comparability="ordered",
                order_value=3,
            ),
            _projection(
                field_key="texture",
                value="轻薄",
                concept_id="texture.richness",
                source_refs=("source-2",),
                comparability="ordered",
                order_value=2,
            ),
        )
    )
    result = compare_relative_candidate(
        candidate=_product(
            1,
            price="100",
            selection_facts=(
                _fact(
                    1,
                    field_key="texture",
                    value="厚重",
                    strength=1,
                    source_ref="source-1",
                ),
            ),
        ),
        baseline=_product(
            2,
            price="100",
            selection_facts=(
                _fact(
                    2,
                    field_key="texture",
                    value="轻薄",
                    strength=1,
                    source_ref="source-2",
                ),
            ),
        ),
        field_key="texture",
        concept_id="texture.richness",
        direction="higher",
        reader=reader,
    )

    assert result.status == "better"
    assert result.relation_kind == "ordered"
    assert result.effect_claim_supported


def test_unsupported_dimension_returns_evidence_gap() -> None:
    result = compare_relative_candidate(
        candidate=_product(1, price="100"),
        baseline=_product(2, price="100"),
        field_key="fragrance_description",
        concept_id=None,
        direction="higher",
        reader=None,
    )

    assert result.status == "evidence_gap"
    assert result.relation_kind == "unsupported"
    assert result.source_refs == ()


def test_recommendation_prioritizes_candidates_better_than_baseline() -> None:
    products = {
        1: _product(1, price="100"),
        2: _product(2, price="200"),
        3: _product(3, price="300"),
    }

    class MemoryFacts:
        def get_decision_facts(
            self,
            product_id: int,
        ) -> DecisionProductFacts:
            return products[product_id]

    result = decide_recommendation(
        MemoryFacts(),
        RetrievalResult(
            candidates=[
                CandidateRef(
                    product_id=product_id,
                    source="canonical",
                    canonical_category="面霜",
                    retrieval_reason="test",
                )
                for product_id in products
            ],
            knowledge_evidence=[],
            review_evidence=[],
            memory_evidence=[],
            missing_sources=[],
        ),
        constraints=[
            CategoryConstraint(value=TopicCode.SKINCARE),
        ],
        relative_requirement=RelativeRequirement(
            field_key="price",
            concept_id=None,
            direction="lower",
            baseline=ReferenceDraft(
                kind="candidate_ordinal",
                ordinal=2,
            ),
        ),
        baseline_product_id=2,
    )

    assert result.ordered_product_ids == [1, 2, 3]
    assert "relative:price:lower" in result.comparison_dimensions
