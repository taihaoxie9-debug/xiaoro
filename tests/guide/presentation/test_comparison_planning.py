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
) -> CopySlot:
    soft_facts = []
    comparison_evidence = []
    compact_tag_evidence = []
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
    ]
    assert all(
        all(cell.fact_ids for cell in row.cells)
        for row in rows
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
        "参考价",
    ]
    assert rows[1].cells[0].state == "known"
    assert rows[1].cells[1].state == "unknown"
    assert rows[1].cells[1].value == "暂无明确描述"


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
        "brand_focus",
        "texture",
        "efficacy.repair",
        "reference_price",
    ]
