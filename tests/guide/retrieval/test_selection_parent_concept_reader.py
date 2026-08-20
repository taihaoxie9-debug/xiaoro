from __future__ import annotations

import pytest

from app.guide.retrieval.selection_fact_contracts import SelectionFact
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptCandidate,
    SelectionConceptProjection,
    SelectionConceptReview,
    candidate_id_for,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)


def _fact(
    *,
    value: str,
    strength: int,
    source: str,
    attribution: str,
    subject_scope: str = "exact_product",
    variant_scope: str | None = None,
) -> SelectionFact:
    return SelectionFact.model_validate(
        {
            "product_id": 1,
            "category_profile": "skincare",
            "subject_scope": subject_scope,
            "variant_scope": variant_scope,
            "field_key": "efficacy",
            "normalized_value": value,
            "rank_strength": strength,
            "safety_role": "ordinary",
            "capabilities": ["compare", "soft_rank"],
            "source_refs": [source],
            "attributions": [attribution],
        },
        strict=True,
    )


def _projection(
    *,
    value: str,
    strength: int,
    source: str,
    stance: str = "supports",
) -> SelectionConceptProjection:
    candidate = SelectionConceptCandidate(
        candidate_id=candidate_id_for(
            profile="skincare",
            field_key="efficacy",
            normalized_value=value,
            product_ids=(1, 2),
            rank_strengths=(strength,),
            source_refs=(source,),
        ),
        profile="skincare",
        field_key="efficacy",
        normalized_value=value,
        product_ids=(1, 2),
        rank_strengths=(strength,),
        source_refs=(source,),
    )
    review = SelectionConceptReview.model_validate(
        {
            **candidate.model_dump(mode="python"),
            "decision": "map",
            "concept_id": "efficacy.soothing",
            "stance": stance,
            "comparability": "binary",
            "order_value": None,
            "rationale": "测试稳定父概念投影。",
        },
        strict=True,
    )
    return SelectionConceptProjection.from_review(review)


def test_reader_merges_same_concept_by_max_strength_once() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                value="舒缓",
                strength=1,
                source="merchant:a",
            ),
            _projection(
                value="舒缓泛红",
                strength=2,
                source="evidence:b",
            ),
        )
    )

    result = reader.project(
        (
            _fact(
                value="舒缓",
                strength=1,
                source="merchant:a",
                attribution="merchant_claim",
            ),
            _fact(
                value="舒缓泛红",
                strength=2,
                source="evidence:b",
                attribution="verified_fact",
            ),
        )
    )

    assert len(result) == 1
    assert result[0].concept_id == "efficacy.soothing"
    assert result[0].rank_strength == 2
    assert result[0].source_refs == ("evidence:b", "merchant:a")
    assert result[0].attributions == frozenset({
        "merchant_claim",
        "verified_fact",
    })
    assert result[0].source_values == ("舒缓", "舒缓泛红")


def test_reader_ignores_free_or_variant_scoped_facts() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                value="舒缓",
                strength=1,
                source="merchant:a",
            ),
        )
    )

    result = reader.project(
        (
            _fact(
                value="雨后木头感",
                strength=1,
                source="merchant:free",
                attribution="merchant_claim",
            ),
            _fact(
                value="舒缓",
                strength=1,
                source="merchant:a",
                attribution="merchant_claim",
                subject_scope="exact_variant",
                variant_scope="01",
            ),
        )
    )

    assert result == ()


def test_reader_rejects_conflicting_stance_for_same_product_concept() -> None:
    reader = SelectionParentConceptReader(
        (
            _projection(
                value="舒缓",
                strength=1,
                source="merchant:a",
            ),
            _projection(
                value="不支持舒缓",
                strength=1,
                source="merchant:b",
                stance="opposes",
            ),
        )
    )

    with pytest.raises(ValueError, match="conflicting concept stance"):
        reader.project(
            (
                _fact(
                    value="舒缓",
                    strength=1,
                    source="merchant:a",
                    attribution="merchant_claim",
                ),
                _fact(
                    value="不支持舒缓",
                    strength=1,
                    source="merchant:b",
                    attribution="merchant_claim",
                ),
            )
        )
