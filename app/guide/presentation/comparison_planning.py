from __future__ import annotations

from collections.abc import Sequence

from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CompactTagEvidence,
    CopySlot,
    LockedFact,
)
from app.guide.presentation.public_contracts import (
    ComparisonCell,
    ComparisonRow,
)


_DIMENSION_LABELS = {
    "brand_main": "品牌主打",
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
    "spf_pa": "防晒指数",
    "suitable_skin": "适用肤质",
    "ingredients_present": "核心成分",
    "cleansing_power": "清洁力",
    "fragrance_family": "香调",
    "concentration": "香水浓度",
    "reference_price": "参考价",
    "profile_match": "当前画像匹配",
}

_DEFAULT_DIMENSIONS = {
    "skincare": ("efficacy", "texture", "reference_price"),
    "suncare": (
        "spf_pa",
        "texture",
        "water_resistance",
        "reference_price",
    ),
    "base_makeup": (
        "finish",
        "coverage",
        "longevity",
        "texture",
        "reference_price",
    ),
    "color_makeup": (
        "finish",
        "coverage",
        "texture",
        "reference_price",
    ),
    "cleanser": (
        "cleansing_power",
        "texture",
        "suitable_skin",
        "reference_price",
    ),
    "fragrance": (
        "fragrance_family",
        "concentration",
        "longevity",
        "reference_price",
    ),
}

_MIXED_CATEGORY_DIMENSIONS = (
    "efficacy",
    "texture",
    "suitable_skin",
    "reference_price",
)


def plan_comparison_rows(
    *,
    requested_dimensions: Sequence[str],
    slots: Sequence[CopySlot],
) -> tuple[ComparisonRow, ...]:
    normalized_slots = tuple(slots)
    if not 2 <= len(normalized_slots) <= 4:
        raise ValueError("comparison rows require two to four slots")
    if any(not isinstance(slot, CopySlot) for slot in normalized_slots):
        raise TypeError("slots must contain CopySlot values")
    explicit_dimensions = _ordered_dimensions(requested_dimensions)
    dimensions = (
        explicit_dimensions
        if explicit_dimensions
        else _default_dimensions(normalized_slots)
    )
    row_dimensions = [
        *(
            ("brand_main",)
            if _dimension_has_known_value(
                slots=normalized_slots,
                dimension_id="brand_main",
            )
            else ()
        ),
        *dimensions,
        *(
            ("profile_match",)
            if _dimension_has_known_value(
                slots=normalized_slots,
                dimension_id="profile_match",
            )
            else ()
        ),
    ]
    return tuple(
        _row_for_dimension(
            dimension_id=dimension_id,
            slots=normalized_slots,
        )
        for dimension_id in row_dimensions
    )


def _default_dimensions(
    slots: tuple[CopySlot, ...],
) -> tuple[str, ...]:
    category_profiles = {
        slot.category_profile for slot in slots
    }
    priority = (
        _DEFAULT_DIMENSIONS[next(iter(category_profiles))]
        if len(category_profiles) == 1
        else _MIXED_CATEGORY_DIMENSIONS
    )
    return tuple(
        dimension_id
        for dimension_id in priority
        if _dimension_is_known_for_all(
            slots=slots,
            dimension_id=dimension_id,
        )
    )[:3]


def _dimension_is_known_for_all(
    *,
    slots: tuple[CopySlot, ...],
    dimension_id: str,
) -> bool:
    return all(
        (
            cell := _cell_for_dimension(
                slot=slot,
                dimension_id=dimension_id,
            )
        ).state == "known"
        and bool(cell.fact_ids)
        for slot in slots
    )


def _dimension_has_known_value(
    *,
    slots: tuple[CopySlot, ...],
    dimension_id: str,
) -> bool:
    return any(
        (
            cell := _cell_for_dimension(
                slot=slot,
                dimension_id=dimension_id,
            )
        ).state == "known"
        and bool(cell.fact_ids)
        for slot in slots
    )


def _ordered_dimensions(
    requested_dimensions: Sequence[str],
) -> tuple[str, ...]:
    if isinstance(requested_dimensions, (str, bytes)):
        raise TypeError("requested dimensions must be a sequence")
    output = []
    seen = {"brand_main", "profile_match"}
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
    evidence = next(
        (
            item
            for item in slot.comparison_evidence
            if item.dimension_id == dimension_id
        ),
        None,
    )
    if evidence is not None:
        if evidence.match_status == "unknown":
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
    if "." in dimension_id or dimension_id == "profile_match":
        return _unknown_cell(slot.product_id)
    fact = (
        _brand_main_fact(slot)
        if dimension_id == "brand_main"
        else _dimension_fact(slot, dimension_id)
    )
    if fact is None:
        return _unknown_cell(slot.product_id)
    if isinstance(fact, ApprovedSoftFact):
        value = _soft_fact_value(fact)
    else:
        value = fact.label
    return ComparisonCell(
        product_id=slot.product_id,
        value=value,
        fact_ids=(fact.fact_id,),
        state="known",
    )


def _unknown_cell(product_id: int) -> ComparisonCell:
    return ComparisonCell(
        product_id=product_id,
        value="尚未确认",
        fact_ids=(),
        state="unknown",
    )


def _brand_main_fact(slot: CopySlot) -> ApprovedSoftFact | None:
    return next(
        (
            fact
            for fact in slot.approved_soft_facts
            if fact.field_key == "brand_main"
        ),
        None,
    )


def _soft_fact_value(fact: ApprovedSoftFact) -> str:
    value = fact.plain_meaning
    for prefix in ("品牌主打：", "使用反馈："):
        if value.startswith(prefix):
            return value.removeprefix(prefix).strip()
    return value


def _dimension_fact(
    slot: CopySlot,
    dimension_id: str,
) -> ApprovedSoftFact | CompactTagEvidence | None:
    field_key = dimension_id.split(".", 1)[0]
    compact = next(
        (
            item
            for item in slot.compact_tag_evidence
            if item.field_key == field_key
        ),
        None,
    )
    if compact is not None:
        return compact
    return next(
        (
            item
            for item in slot.approved_soft_facts
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
