from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.selection_fact_contracts import (
    SelectionFact,
    merge_selection_facts,
)


def _fact(
    *,
    normalized_value: str = "保湿",
    rank_strength: int | None = 1,
    safety_role: str = "ordinary",
    capabilities: tuple[str, ...] = ("compare", "soft_rank"),
    source_refs: tuple[str, ...] = ("source-a",),
    subject_scope: str = "exact_product",
    variant_scope: str | None = None,
    attributions: tuple[str, ...] = ("merchant_claim",),
) -> SelectionFact:
    return SelectionFact.model_validate(
        {
            "product_id": 78,
            "category_profile": "skincare",
            "subject_scope": subject_scope,
            "variant_scope": variant_scope,
            "field_key": "efficacy",
            "normalized_value": normalized_value,
            "rank_strength": rank_strength,
            "safety_role": safety_role,
            "capabilities": list(capabilities),
            "source_refs": list(source_refs),
            "attributions": list(attributions),
        },
        strict=True,
    )


def test_selection_key_is_product_scope_field_and_value() -> None:
    fact = _fact(normalized_value="保湿")

    assert fact.category_profile is CategoryProfile.SKINCARE
    assert fact.selection_key == (
        78,
        "exact_product",
        None,
        "efficacy",
        "保湿",
    )


def test_duplicate_selection_facts_take_maximum_strength_once() -> None:
    merged = merge_selection_facts(
        (
            _fact(
                rank_strength=1,
                source_refs=("claim",),
                attributions=("merchant_claim",),
            ),
            _fact(
                rank_strength=2,
                source_refs=("package",),
                attributions=("verified_fact",),
            ),
            _fact(
                rank_strength=1,
                source_refs=("second-image",),
                attributions=("consumer_report",),
            ),
        )
    )

    assert len(merged) == 1
    assert merged[0].rank_strength == 2
    assert merged[0].source_refs == (
        "claim",
        "package",
        "second-image",
    )
    assert merged[0].attributions == frozenset({
        "consumer_report",
        "merchant_claim",
        "verified_fact",
    })


def test_distinct_normalized_values_remain_distinct_slots() -> None:
    merged = merge_selection_facts(
        (
            _fact(normalized_value="保湿"),
            _fact(normalized_value="舒缓"),
        )
    )

    assert [item.normalized_value for item in merged] == [
        "保湿",
        "舒缓",
    ]


def test_verified_fact_prevents_merchant_safety_suppression() -> None:
    merged = merge_selection_facts(
        (
            _fact(
                safety_role="merchant_positive_safety",
                source_refs=("merchant",),
            ),
            _fact(
                rank_strength=2,
                safety_role="ordinary",
                source_refs=("verified",),
            ),
        )
    )

    assert len(merged) == 1
    assert merged[0].safety_role == "ordinary"
    assert merged[0].rank_strength == 2


def test_soft_rank_requires_strength() -> None:
    with pytest.raises(
        ValidationError,
        match="soft rank requires rank strength",
    ):
        _fact(rank_strength=None)


def test_non_soft_fact_forbids_strength() -> None:
    with pytest.raises(
        ValidationError,
        match="rank strength requires soft rank",
    ):
        _fact(
            rank_strength=1,
            capabilities=("compare",),
        )


def test_product_and_bundle_facts_preserve_variant_boundaries() -> None:
    product = _fact(variant_scope="第三代50ml")
    bundle = _fact(
        subject_scope="bundle",
        variant_scope="蓝丸2.0与绿丸2.0组合",
    )

    assert product.selection_key[2] == "第三代50ml"
    assert bundle.selection_key[1:3] == (
        "bundle",
        "蓝丸2.0与绿丸2.0组合",
    )


def test_exact_variant_requires_variant_scope() -> None:
    with pytest.raises(
        ValidationError,
        match="exact variant selection requires variant scope",
    ):
        _fact(subject_scope="exact_variant")


def test_selection_fact_preserves_approved_long_variant_value() -> None:
    value = "规格" * 169

    fact = _fact(normalized_value=value)

    assert fact.normalized_value == value
