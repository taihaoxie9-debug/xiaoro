from __future__ import annotations

from decimal import Decimal

from app.guide.decision.concept_ranking import rank_common_concepts
from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.decision.facet_ranking import rank_soft_facets
from app.guide.decision.recommendation import decide_recommendation
from app.guide.intent.contracts import (
    CategoryConstraint,
    ConceptConstraint,
    FacetConstraint,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.retrieval.selection_fact_contracts import SelectionFact
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptProjection,
    candidate_id_for,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)
from app.guide.understanding.contracts import TopicCode


def _projection(
    *,
    value: str,
    concept_id: str,
    source_refs: tuple[str, ...],
    stance: str = "supports",
    strengths: tuple[int, ...] = (1, 2),
    field_key: str | None = None,
) -> SelectionConceptProjection:
    product_ids = (1, 2)
    scoped_field = field_key or concept_id.split(".", 1)[0]
    return SelectionConceptProjection.model_validate(
        {
            "candidate_id": candidate_id_for(
                profile="skincare",
                field_key=scoped_field,
                normalized_value=value,
                product_ids=product_ids,
                rank_strengths=strengths,
                source_refs=source_refs,
            ),
            "profile": "skincare",
            "field_key": scoped_field,
            "normalized_value": value,
            "product_ids": list(product_ids),
            "rank_strengths": list(strengths),
            "source_refs": list(source_refs),
            "concept_id": concept_id,
            "stance": stance,
            "comparability": "binary",
            "order_value": None,
            "rationale": "用于验证父概念排序合同的稳定审核映射。",
        },
        strict=True,
    )


def _fact(
    *,
    value: str,
    strength: int,
    source_ref: str,
    field_key: str = "efficacy",
    safety_role: str = "ordinary",
    product_id: int = 1,
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
            "safety_role": safety_role,
            "capabilities": ["compare", "soft_rank"],
            "source_refs": [source_ref],
            "attributions": ["merchant_claim"],
        },
        strict=True,
    )


def _product(
    facts: tuple[SelectionFact, ...],
    *,
    product_id: int = 1,
    price: str = "100",
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SKINCARE,
        category_fields=(),
        price=Decimal(price),
        price_state=FactState.KNOWN,
        efficacy=None,
        efficacy_state=FactState.UNKNOWN,
        suitable_skin=None,
        suitable_skin_state=FactState.UNKNOWN,
        ingredients_present=None,
        ingredients_present_state=FactState.UNKNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
        selection_facts=tuple(
            sorted(
                facts,
                key=lambda item: (
                    item.field_key,
                    item.normalized_value.casefold(),
                ),
            )
        ),
    )


def test_same_concept_multiple_sources_scores_max_strength_once() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                value="舒缓",
                concept_id="efficacy.soothing",
                source_refs=("source-a",),
            ),
            _projection(
                value="舒缓泛红",
                concept_id="efficacy.soothing",
                source_refs=("source-b",),
            ),
        )
    )
    product = _product(
        (
            _fact(value="舒缓", strength=1, source_ref="source-a"),
            _fact(
                value="舒缓泛红",
                strength=2,
                source_ref="source-b",
            ),
        )
    )

    ranking = rank_common_concepts(
        product,
        (
            ConceptConstraint(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                polarity="prefer",
            ),
        ),
        reader=reader,
    )

    assert ranking.weighted_match_score == 2
    assert ranking.matched_slot_count == 1
    assert ranking.mismatch_count == 0
    assert ranking.unknown_count == 0
    assert ranking.slots[0].source_refs == ("source-a", "source-b")
    assert ranking.slots[0].source_values == ("舒缓", "舒缓泛红")


def test_other_positive_concept_is_unknown_not_mismatch() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                value="保湿",
                concept_id="efficacy.hydration",
                source_refs=("source-a",),
            ),
        )
    )

    ranking = rank_common_concepts(
        _product(
            (
                _fact(
                    value="保湿",
                    strength=2,
                    source_ref="source-a",
                ),
            )
        ),
        (
            ConceptConstraint(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                polarity="prefer",
            ),
        ),
        reader=reader,
    )

    assert ranking.mismatch_count == 0
    assert ranking.unknown_count == 1
    assert ranking.slots[0].match_status == "unknown"


def test_explicit_opposing_projection_is_mismatch_with_evidence() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                value="厚重",
                concept_id="texture.refreshing",
                field_key="texture",
                source_refs=("source-a",),
                stance="opposes",
            ),
        )
    )
    product = _product(
        (
            _fact(
                value="厚重",
                strength=2,
                source_ref="source-a",
                field_key="texture",
            ),
        )
    )

    ranking = rank_common_concepts(
        product,
        (
            ConceptConstraint(
                field_key="texture",
                concept_id="texture.refreshing",
                polarity="prefer",
            ),
        ),
        reader=reader,
    )

    assert ranking.mismatch_count == 1
    assert ranking.slots[0].match_status == "mismatch"
    assert ranking.slots[0].source_refs == ("source-a",)


def test_avoid_polarity_inverts_explicit_support_and_opposition() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                value="厚重",
                concept_id="texture.refreshing",
                field_key="texture",
                source_refs=("source-a",),
                stance="opposes",
            ),
        )
    )

    ranking = rank_common_concepts(
        _product(
            (
                _fact(
                    value="厚重",
                    strength=1,
                    source_ref="source-a",
                    field_key="texture",
                ),
            )
        ),
        (
            ConceptConstraint(
                field_key="texture",
                concept_id="texture.refreshing",
                polarity="avoid",
            ),
        ),
        reader=reader,
    )

    assert ranking.matched_slot_count == 1
    assert ranking.slots[0].match_status == "matched"


def test_merchant_positive_safety_is_unknown_in_serious_mode() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                value="敏感肌",
                concept_id="suitable_skin.sensitive",
                field_key="suitable_skin",
                source_refs=("source-a",),
                strengths=(1,),
            ),
        )
    )

    ranking = rank_common_concepts(
        _product(
            (
                _fact(
                    value="敏感肌",
                    strength=1,
                    source_ref="source-a",
                    field_key="suitable_skin",
                    safety_role="merchant_positive_safety",
                ),
            )
        ),
        (
            ConceptConstraint(
                field_key="suitable_skin",
                concept_id="suitable_skin.sensitive",
                polarity="prefer",
            ),
        ),
        reader=reader,
        safety_sensitive=True,
    )

    assert ranking.weighted_match_score == 0
    assert ranking.unknown_count == 1


def test_recommendation_orders_concept_match_before_unknown_and_price() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                value="舒缓",
                concept_id="efficacy.soothing",
                source_refs=("source-a",),
            ),
        )
    )
    matched = _product(
        (
            _fact(
                value="舒缓",
                strength=1,
                source_ref="source-a",
            ),
        ),
        product_id=1,
        price="200",
    )
    unknown = _product((), product_id=2, price="100")

    class MemoryFacts:
        def get_decision_facts(
            self,
            product_id: int,
        ) -> DecisionProductFacts:
            return {1: matched, 2: unknown}[product_id]

    result = decide_recommendation(
        MemoryFacts(),
        RetrievalResult(
            candidates=[
                CandidateRef(
                    product_id=1,
                    source="canonical",
                    canonical_category="面霜",
                    retrieval_reason="test",
                ),
                CandidateRef(
                    product_id=2,
                    source="canonical",
                    canonical_category="面霜",
                    retrieval_reason="test",
                ),
            ],
            knowledge_evidence=[],
            review_evidence=[],
            memory_evidence=[],
            missing_sources=[],
        ),
        constraints=[
            CategoryConstraint(value=TopicCode.SKINCARE),
            ConceptConstraint(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                polarity="prefer",
            ),
        ],
        concept_reader=reader,
    )

    assert result.ordered_product_ids == [1, 2]
    assert "concept:efficacy" in result.comparison_dimensions
    assert "source-a" in result.evidence_refs


def test_unmatched_legacy_positive_fact_is_unknown_without_opposition() -> None:
    ranking = rank_soft_facets(
        _product(
            (
                _fact(
                    value="保湿",
                    strength=2,
                    source_ref="source-a",
                ),
            )
        ),
        (
            FacetConstraint(
                field_key="efficacy",
                value="舒缓",
            ),
        ),
    )

    assert ranking.mismatch_count == 0
    assert ranking.unknown_count == 1
    assert ranking.slots[0].match_status == "unknown"
