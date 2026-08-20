from __future__ import annotations

from collections.abc import Sequence

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.copywriter_contracts import (
    CompactTagEvidence,
    CopySlot,
)
from app.guide.presentation.public_contracts import CompactTag


_DEFAULT_PRIORITY = (
    "efficacy",
    "texture",
    "finish",
    "coverage",
    "cleansing_power",
    "film_speed",
    "water_resistance",
    "claimed_ingredients",
    "ingredients_present",
    "usage",
)
_MIN_COMPACT_TAG_CHARS = 2
_MAX_COMPACT_TAG_CHARS = 4


def plan_compact_tags(
    *,
    responsibility: Responsibility,
    slot: CopySlot,
    requested_concepts: Sequence[str],
) -> tuple[CompactTag, ...]:
    if not isinstance(responsibility, Responsibility):
        raise TypeError("responsibility must be Responsibility")
    if not isinstance(slot, CopySlot):
        raise TypeError("slot must be CopySlot")
    requested_fields = _requested_fields(requested_concepts)
    priority = _priority_for(
        responsibility,
        requested_fields=requested_fields,
    )
    facts = sorted(
        slot.compact_tag_evidence,
        key=lambda item: (
            _priority_index(item, priority),
            item.fact_id,
        ),
    )
    tags = []
    seen_labels: set[str] = set()
    for fact in facts:
        label = fact.label
        if (
            not (
                _MIN_COMPACT_TAG_CHARS
                <= len(label)
                <= _MAX_COMPACT_TAG_CHARS
            )
            or label in {"适配待确认", "推荐理由"}
            or label.casefold() in seen_labels
        ):
            continue
        seen_labels.add(label.casefold())
        tags.append(
            CompactTag(
                product_id=slot.product_id,
                label=label,
                fact_ids=(fact.fact_id,),
            )
        )
        if len(tags) == 3:
            break
    return tuple(tags)


def _requested_fields(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("requested concepts must be a sequence")
    fields = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "requested concepts must be nonempty strings"
            )
        field_key = value.split(".", 1)[0]
        if field_key not in fields:
            fields.append(field_key)
    return tuple(fields)


def _priority_for(
    responsibility: Responsibility,
    *,
    requested_fields: tuple[str, ...],
) -> tuple[str, ...]:
    if responsibility is Responsibility.PRODUCT_KNOWLEDGE:
        base = (
            *requested_fields,
            "texture",
            "efficacy",
            "claimed_ingredients",
            "ingredients_present",
            "usage",
        )
    elif responsibility is Responsibility.COMPARISON:
        base = (
            *requested_fields,
            "texture",
            "efficacy",
            "finish",
            "coverage",
        )
    else:
        base = (*requested_fields, *_DEFAULT_PRIORITY)
    return tuple(dict.fromkeys(base))


def _priority_index(
    fact: CompactTagEvidence,
    priority: tuple[str, ...],
) -> int:
    try:
        return priority.index(fact.field_key)
    except ValueError:
        return len(priority)


__all__ = ["plan_compact_tags"]
