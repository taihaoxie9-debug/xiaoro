from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from app.guide.presentation.copywriter_contracts import ApprovedSoftFact
from app.guide.presentation.copywriter_validation import (
    is_safe_soft_fact_text,
)


MAX_NARRATIVE_ATOMS = 8

_ALLOWED_FIELDS = frozenset({
    "texture",
    "finish",
    "tone_effect",
    "film_speed",
    "makeup_compatibility",
    "water_resistance",
    "friction_resistance",
    "usage_context",
    "usage_scenario",
    "efficacy",
    "suitable_skin",
    "skin_concern",
    "target_audience",
    "coverage",
    "color_family",
    "color_payoff",
    "shade",
    "makeup_effect",
    "makeup_style",
    "fragrance_description",
    "fragrance_family",
    "fragrance_notes",
    "top_notes",
    "heart_notes",
    "cleansing_power",
    "rinse_behavior",
    "cleansing_requirement",
    "double_cleanse",
    "surfactant_type",
})

_FIELD_GROUP = {
    "tone_effect": "finish",
    "makeup_effect": "finish",
    "makeup_compatibility": "finish",
    "usage_scenario": "usage_context",
    "target_audience": "suitable_skin",
    "fragrance_notes": "fragrance_description",
    "top_notes": "fragrance_description",
    "heart_notes": "fragrance_description",
}

_FIELD_PRIORITY = {
    "texture": 0,
    "finish": 1,
    "film_speed": 2,
    "usage_context": 3,
    "water_resistance": 4,
    "friction_resistance": 5,
    "suitable_skin": 6,
    "efficacy": 7,
    "skin_concern": 8,
    "coverage": 9,
    "color_family": 10,
    "color_payoff": 11,
    "shade": 12,
    "makeup_style": 13,
    "fragrance_description": 14,
    "fragrance_family": 15,
    "cleansing_power": 16,
    "rinse_behavior": 17,
    "cleansing_requirement": 18,
    "double_cleanse": 19,
    "surfactant_type": 20,
}

_ATTRIBUTION_PRIORITY = {
    "verified_fact": 0,
    "consumer_report": 1,
    "merchant_claim": 2,
}


def build_narrative_atoms(
    facts: tuple[ApprovedSoftFact, ...],
    *,
    preferred_fields: set[str],
    distinctive_fields: set[str],
) -> tuple[ApprovedSoftFact, ...]:
    preferred = {
        _FIELD_GROUP.get(field, field)
        for field in preferred_fields
    }
    distinctive = {
        _FIELD_GROUP.get(field, field)
        for field in distinctive_fields
    }
    grouped: dict[
        tuple[int, str, str],
        list[ApprovedSoftFact],
    ] = defaultdict(list)
    for fact in facts:
        if (
            fact.field_key not in _ALLOWED_FIELDS
            or not is_safe_soft_fact_text(fact.plain_meaning)
        ):
            continue
        field = _FIELD_GROUP.get(fact.field_key, fact.field_key)
        grouped[(fact.product_id, field, fact.attribution)].append(fact)

    atoms = [
        _merge(group, field_key=key[1])
        for key, group in sorted(
            grouped.items(),
            key=lambda item: (
                item[0][1] not in preferred,
                item[0][1] not in distinctive,
                _FIELD_PRIORITY.get(item[0][1], 99),
                _ATTRIBUTION_PRIORITY[item[0][2]],
                item[0][0],
            ),
        )
    ]
    return tuple(atoms[:MAX_NARRATIVE_ATOMS])


def _merge(
    facts: list[ApprovedSoftFact],
    *,
    field_key: str,
) -> ApprovedSoftFact:
    ordered = sorted(facts, key=lambda item: item.fact_id)
    values = tuple(dict.fromkeys(
        item.plain_meaning for item in ordered
    ))
    payload = "|".join(
        item.fact_id for item in ordered
    ).encode("utf-8")
    return ApprovedSoftFact(
        fact_id=f"atom:{sha256(payload).hexdigest()}",
        product_id=ordered[0].product_id,
        field_key=field_key,
        plain_meaning="；".join(values),
        attribution=ordered[0].attribution,
        source_refs=tuple(sorted({
            ref
            for item in ordered
            for ref in item.source_refs
        })),
    )


__all__ = ["MAX_NARRATIVE_ATOMS", "build_narrative_atoms"]
