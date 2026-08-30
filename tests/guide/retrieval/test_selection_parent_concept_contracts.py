from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptCandidate,
    SelectionConceptProjection,
    SelectionConceptReview,
    candidate_id_for,
)


def _candidate(**updates) -> SelectionConceptCandidate:
    payload = {
        "profile": "skincare",
        "field_key": "efficacy",
        "normalized_value": "舒缓泛红",
        "product_ids": [32, 33, 38],
        "rank_strengths": [1, 2],
        "source_refs": ["evidence:a", "merchant:b"],
    }
    payload.update(updates)
    payload["candidate_id"] = candidate_id_for(
        profile=payload["profile"],
        field_key=payload["field_key"],
        normalized_value=payload["normalized_value"],
        product_ids=tuple(payload["product_ids"]),
        rank_strengths=tuple(payload["rank_strengths"]),
        source_refs=tuple(payload["source_refs"]),
    )
    return SelectionConceptCandidate.model_validate(payload, strict=True)


def test_candidate_identity_covers_source_inventory() -> None:
    candidate = _candidate()

    changed = candidate.model_dump(mode="python")
    changed["product_ids"] = [32, 33, 38, 39]

    with pytest.raises(ValidationError, match="candidate_id"):
        SelectionConceptCandidate.model_validate(changed, strict=True)


def test_single_product_child_value_can_map_to_shared_parent() -> None:
    candidate = _candidate(
        profile="base_makeup",
        field_key="texture",
        normalized_value="轻盈乳霜质地",
        product_ids=[112],
        rank_strengths=[2],
        source_refs=["reviewed:product:112:texture"],
    )
    review = SelectionConceptReview.model_validate(
        {
            **candidate.model_dump(mode="python"),
            "decision": "map",
            "concept_id": "texture.lightweight",
            "stance": "supports",
            "comparability": "binary",
            "order_value": None,
            "rationale": "单商品子值仍可映射到跨商品父概念。",
        },
        strict=True,
    )

    projection = SelectionConceptProjection.from_review(review)

    assert projection.product_ids == (112,)


def test_mapped_review_requires_field_scoped_concept() -> None:
    candidate = _candidate()
    base = {
        **candidate.model_dump(mode="python"),
        "decision": "map",
        "concept_id": "texture.soothing",
        "stance": "supports",
        "comparability": "binary",
        "order_value": None,
        "rationale": "跨商品重复的舒缓方向。",
    }

    with pytest.raises(ValidationError, match="field-scoped"):
        SelectionConceptReview.model_validate(base, strict=True)

    valid = SelectionConceptReview.model_validate(
        {**base, "concept_id": "efficacy.soothing"},
        strict=True,
    )
    assert valid.concept_id == "efficacy.soothing"


def test_leave_free_cannot_publish_concept_semantics() -> None:
    candidate = _candidate(normalized_value="水油融合微囊质地")
    payload = {
        **candidate.model_dump(mode="python"),
        "decision": "leave_free",
        "concept_id": "efficacy.soothing",
        "stance": "supports",
        "comparability": "binary",
        "order_value": None,
        "rationale": "产品特定长尾描述。",
    }

    with pytest.raises(ValidationError, match="leave_free"):
        SelectionConceptReview.model_validate(payload, strict=True)


def test_ordered_projection_requires_order_value() -> None:
    candidate = _candidate(
        profile="base_makeup",
        field_key="coverage",
        normalized_value="高遮瑕",
        product_ids=[45, 56],
        rank_strengths=[1],
        source_refs=["merchant:a", "merchant:b"],
    )
    payload = {
        **candidate.model_dump(mode="python"),
        "decision": "map",
        "concept_id": "coverage.level",
        "stance": "supports",
        "comparability": "ordered",
        "order_value": None,
        "rationale": "高遮瑕属于可比较等级。",
    }

    with pytest.raises(ValidationError, match="order_value"):
        SelectionConceptReview.model_validate(payload, strict=True)

    review = SelectionConceptReview.model_validate(
        {**payload, "order_value": 3},
        strict=True,
    )
    projection = SelectionConceptProjection.from_review(review)
    assert projection.order_value == 3
    assert projection.rank_strengths == (1,)


def test_projection_cannot_be_created_from_unmapped_review() -> None:
    candidate = _candidate()
    review = SelectionConceptReview.model_validate(
        {
            **candidate.model_dump(mode="python"),
            "decision": "leave_free",
            "concept_id": None,
            "stance": "not_comparable",
            "comparability": "none",
            "order_value": None,
            "rationale": "保留为自由描述。",
        },
        strict=True,
    )

    with pytest.raises(ValueError, match="mapped"):
        SelectionConceptProjection.from_review(review)
