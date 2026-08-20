from __future__ import annotations

from collections.abc import Sequence

from app.guide.presentation.copywriter_contracts import (
    CompactTagEvidence,
    CopySlot,
    LockedFact,
)
from app.guide.presentation.public_contracts import (
    ComparisonCell,
    ComparisonRow,
)


_DIMENSION_LABELS = {
    "brand_focus": "品牌主打",
    "efficacy": "功效方向",
    "efficacy.repair": "修护方向",
    "efficacy.barrier_repair": "屏障修护",
    "efficacy.hydration": "保湿方向",
    "texture": "质地",
    "texture.refreshing": "清爽",
    "finish": "妆效",
    "coverage": "遮瑕",
    "longevity": "持妆",
    "film_speed": "成膜速度",
    "water_resistance": "防水",
    "reference_price": "参考价",
}


def plan_comparison_rows(
    *,
    requested_dimensions: Sequence[str],
    slots: Sequence[CopySlot],
) -> tuple[ComparisonRow, ...]:
    normalized_slots = tuple(slots)
    if not 2 <= len(normalized_slots) <= 3:
        raise ValueError("comparison rows require two or three slots")
    if any(not isinstance(slot, CopySlot) for slot in normalized_slots):
        raise TypeError("slots must contain CopySlot values")
    dimensions = _ordered_dimensions(requested_dimensions)
    return tuple(
        _row_for_dimension(
            dimension_id=dimension_id,
            slots=normalized_slots,
        )
        for dimension_id in (
            "brand_focus",
            *dimensions,
            "reference_price",
        )
    )


def _ordered_dimensions(
    requested_dimensions: Sequence[str],
) -> tuple[str, ...]:
    if isinstance(requested_dimensions, (str, bytes)):
        raise TypeError("requested dimensions must be a sequence")
    output = []
    seen = {"brand_focus", "reference_price"}
    for value in requested_dimensions:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "requested dimensions must be nonempty strings"
            )
        dimension_id = value.strip()
        if dimension_id in seen:
            continue
        seen.add(dimension_id)
        output.append(dimension_id)
    return tuple(output)


def _row_for_dimension(
    *,
    dimension_id: str,
    slots: tuple[CopySlot, ...],
) -> ComparisonRow:
    return ComparisonRow(
        dimension_id=dimension_id,
        label=_DIMENSION_LABELS.get(
            dimension_id,
            _field_label(dimension_id),
        ),
        cells=tuple(
            _cell_for_dimension(
                slot=slot,
                dimension_id=dimension_id,
            )
            for slot in slots
        ),
    )


def _cell_for_dimension(
    *,
    slot: CopySlot,
    dimension_id: str,
) -> ComparisonCell:
    if dimension_id == "reference_price":
        price = next(
            (
                fact
                for fact in slot.locked_facts
                if fact.kind == "price"
            ),
            None,
        )
        return _locked_cell(slot.product_id, price)
    if "." in dimension_id:
        evidence = next(
            (
                item
                for item in slot.comparison_evidence
                if item.dimension_id == dimension_id
            ),
            None,
        )
        if evidence is None or evidence.match_status == "unknown":
            return _unknown_cell(slot.product_id)
        value = evidence.display_value
        if value is None:
            raise AssertionError(
                "known comparison evidence requires display value"
            )
        return ComparisonCell(
            product_id=slot.product_id,
            value=(
                f"不符合：{value}"
                if evidence.match_status == "mismatch"
                else value
            ),
            fact_ids=evidence.fact_ids,
            state="known",
        )
    fact = (
        _brand_focus_fact(slot)
        if dimension_id == "brand_focus"
        else _dimension_fact(slot, dimension_id)
    )
    if fact is None:
        return _unknown_cell(slot.product_id)
    return ComparisonCell(
        product_id=slot.product_id,
        value=fact.label,
        fact_ids=(fact.fact_id,),
        state="known",
    )


def _unknown_cell(product_id: int) -> ComparisonCell:
    return ComparisonCell(
        product_id=product_id,
        value="暂无明确描述",
        fact_ids=(),
        state="unknown",
    )


def _brand_focus_fact(slot: CopySlot) -> CompactTagEvidence | None:
    for field_key in (
        "efficacy",
        "coverage",
        "finish",
        "cleansing_power",
        "film_speed",
        "texture",
    ):
        fact = next(
            (
                item
                for item in slot.compact_tag_evidence
                if item.field_key == field_key
            ),
            None,
        )
        if fact is not None:
            return fact
    return (
        slot.compact_tag_evidence[0]
        if slot.compact_tag_evidence
        else None
    )


def _dimension_fact(
    slot: CopySlot,
    dimension_id: str,
) -> CompactTagEvidence | None:
    field_key = dimension_id.split(".", 1)[0]
    return next(
        (
            item
            for item in slot.compact_tag_evidence
            if item.field_key == field_key
        ),
        None,
    )


def _locked_cell(
    product_id: int,
    fact: LockedFact | None,
) -> ComparisonCell:
    if fact is None:
        return ComparisonCell(
            product_id=product_id,
            value="暂无明确价格",
            fact_ids=(),
            state="unknown",
        )
    return ComparisonCell(
        product_id=product_id,
        value=fact.display_value,
        fact_ids=(fact.fact_id,),
        state="known",
    )

def _field_label(dimension_id: str) -> str:
    field_key = dimension_id.split(".", 1)[0]
    return {
        "efficacy": "功效方向",
        "texture": "质地",
        "finish": "妆效",
        "coverage": "遮瑕",
        "longevity": "持妆",
    }.get(field_key, field_key)


__all__ = ["plan_comparison_rows"]
