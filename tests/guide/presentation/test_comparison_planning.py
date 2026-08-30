from __future__ import annotations

from app.guide.presentation.comparison_planning import (
    plan_comparison_rows,
)
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CompactTagEvidence,
    ComparisonDimensionEvidence,
    CopySlot,
    LockedFact,
)


def _slot(
    slot_id: str,
    product_id: int,
    *,
    repair: str | None,
    texture: str | None,
    price: str,
    brand_main: str | None = "修护维稳路线",
    profile_match: str | None = "适合当前肤质需求",
) -> CopySlot:
    soft_facts = []
    comparison_evidence = []
    compact_tag_evidence = []
    if brand_main is not None:
        soft_facts.append(
            ApprovedSoftFact(
                fact_id=f"fact:{product_id}:brand-main",
                product_id=product_id,
                field_key="brand_main",
                plain_meaning=f"品牌主打：{brand_main}",
                attribution="merchant_claim",
                source_refs=(f"source:{product_id}:brand-main",),
            )
        )
    if profile_match is not None:
        soft_facts.append(
            ApprovedSoftFact(
                fact_id=f"fact:{product_id}:profile-match",
                product_id=product_id,
                field_key="suitable_skin",
                plain_meaning=profile_match,
                attribution="verified_fact",
                source_refs=(f"source:{product_id}:profile-match",),
            )
        )
        comparison_evidence.append(
            ComparisonDimensionEvidence(
                product_id=product_id,
                dimension_id="profile_match",
                match_status="matched",
                display_value=profile_match,
                fact_ids=(f"fact:{product_id}:profile-match",),
                source_refs=(f"source:{product_id}:profile-match",),
                attribution="verified_fact",
            )
        )
    else:
        comparison_evidence.append(
            ComparisonDimensionEvidence(
                product_id=product_id,
                dimension_id="profile_match",
                match_status="unknown",
            )
        )
    if repair is not None:
        soft_facts.append(
            ApprovedSoftFact(
                fact_id=f"fact:{product_id}:repair",
                product_id=product_id,
                field_key="efficacy",
                plain_meaning=repair,
                attribution="verified_fact",
                source_refs=(f"source:{product_id}:repair",),
            )
        )
        comparison_evidence.append(
            ComparisonDimensionEvidence(
                product_id=product_id,
                dimension_id="efficacy.repair",
                match_status="matched",
                display_value=repair,
                fact_ids=(f"fact:{product_id}:repair",),
                source_refs=(f"source:{product_id}:repair",),
                attribution="verified_fact",
            )
        )
        compact_tag_evidence.append(
            CompactTagEvidence(
                product_id=product_id,
                fact_id=f"fact:{product_id}:repair",
                field_key="efficacy",
                label=repair,
                source_refs=(f"source:{product_id}:repair",),
                attribution="verified_fact",
            )
        )
    if texture is not None:
        soft_facts.append(
            ApprovedSoftFact(
                fact_id=f"fact:{product_id}:texture",
                product_id=product_id,
                field_key="texture",
                plain_meaning=texture,
                attribution="verified_fact",
                source_refs=(f"source:{product_id}:texture",),
            )
        )
        comparison_evidence.append(
            ComparisonDimensionEvidence(
                product_id=product_id,
                dimension_id="texture.refreshing",
                match_status="matched",
                display_value=texture,
                fact_ids=(f"fact:{product_id}:texture",),
                source_refs=(f"source:{product_id}:texture",),
                attribution="verified_fact",
            )
        )
        compact_tag_evidence.append(
            CompactTagEvidence(
                product_id=product_id,
                fact_id=f"fact:{product_id}:texture",
                field_key="texture",
                label=texture,
                source_refs=(f"source:{product_id}:texture",),
                attribution="verified_fact",
            )
        )
    else:
        comparison_evidence.append(
            ComparisonDimensionEvidence(
                product_id=product_id,
                dimension_id="texture.refreshing",
                match_status="unknown",
            )
        )
    return CopySlot(
        slot_id=slot_id,
        product_id=product_id,
        name=f"商品{product_id}",
        category_profile="skincare",
        approved_soft_facts=tuple(soft_facts),
        locked_facts=(
            LockedFact(
                fact_id=f"fact:{product_id}:price",
                product_id=product_id,
                kind="price",
                label="参考价",
                display_value=price,
                source_refs=(f"source:{product_id}:price",),
            ),
        ),
        required_cautions=(),
        comparison_evidence=tuple(comparison_evidence),
        compact_tag_evidence=tuple(compact_tag_evidence),
    )


def test_explicit_dimensions_build_brand_repair_texture_price_rows() -> None:
    rows = plan_comparison_rows(
        requested_dimensions=(
            "efficacy.repair",
            "texture",
            "reference_price",
        ),
        slots=(
            _slot(
                "p1",
                38,
                repair="屏障修护",
                texture="轻盈乳液",
                price="¥249 / 30ml",
            ),
            _slot(
                "p2",
                91,
                repair="保湿维稳",
                texture="柔润乳霜",
                price="¥88 / 50ml",
            ),
        ),
    )

    assert [row.label for row in rows] == [
        "品牌主打",
        "修护方向",
        "质地",
        "参考价",
        "当前画像匹配",
    ]
    assert all(
        all(cell.fact_ids for cell in row.cells)
        for row in rows
    )


def test_generic_skincare_comparison_uses_useful_default_rows() -> None:
    rows = plan_comparison_rows(
        requested_dimensions=(),
        slots=(
            _slot(
                "p1",
                129,
                repair="屏障修护、抗初老",
                texture="清透蛋清质地、不粘腻",
                price="¥519",
                brand_main=None,
                profile_match=None,
            ),
            _slot(
                "p2",
                33,
                repair="修护屏障、抗老、舒缓泛红",
                texture="清润琥珀质地、轻薄不粘腻",
                price="¥968",
                brand_main=None,
                profile_match=None,
            ),
        ),
    )

    assert [row.dimension_id for row in rows] == [
        "efficacy",
        "texture",
        "reference_price",
    ]
    assert all(
        cell.state == "known"
        for row in rows
        for cell in row.cells
    )


def test_stuffy_commute_maps_to_refreshing_row() -> None:
    rows = plan_comparison_rows(
        requested_dimensions=("texture.refreshing",),
        slots=(
            _slot(
                "p1",
                38,
                repair="屏障修护",
                texture="清爽轻薄",
                price="¥249 / 30ml",
            ),
            _slot(
                "p2",
                91,
                repair="保湿维稳",
                texture=None,
                price="¥88 / 50ml",
            ),
        ),
    )

    assert [row.label for row in rows] == [
        "品牌主打",
        "清爽",
        "当前画像匹配",
    ]
    assert rows[1].cells[0].state == "known"
    assert rows[1].cells[1].state == "unknown"
    assert rows[1].cells[1].value == "尚未确认"


def test_requested_dimension_order_is_deterministic_and_deduplicated(
) -> None:
    rows = plan_comparison_rows(
        requested_dimensions=(
            "texture",
            "efficacy.repair",
            "texture",
        ),
        slots=(
            _slot(
                "p1",
                38,
                repair="屏障修护",
                texture="清爽轻薄",
                price="¥249 / 30ml",
            ),
            _slot(
                "p2",
                91,
                repair="保湿维稳",
                texture="柔润乳霜",
                price="¥88 / 50ml",
            ),
        ),
    )

    assert [row.dimension_id for row in rows] == [
        "brand_main",
        "texture",
        "efficacy.repair",
        "profile_match",
    ]


def test_missing_brand_main_does_not_reuse_an_arbitrary_compact_tag() -> None:
    rows = plan_comparison_rows(
        requested_dimensions=("texture.refreshing",),
        slots=(
            _slot(
                "p1",
                38,
                repair="屏障修护",
                texture="清爽轻薄",
                price="¥249 / 30ml",
                brand_main=None,
            ),
            _slot(
                "p2",
                91,
                repair="保湿维稳",
                texture="柔润乳霜",
                price="¥88 / 50ml",
            ),
        ),
    )

    assert rows[0].dimension_id == "brand_main"
    assert rows[0].cells[0].state == "unknown"
    assert rows[0].cells[0].value == "尚未确认"
    assert rows[0].cells[1].state == "known"
