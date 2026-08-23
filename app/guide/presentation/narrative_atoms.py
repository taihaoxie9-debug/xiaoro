from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from app.guide.presentation.copywriter_contracts import ApprovedSoftFact
from app.guide.presentation.copywriter_validation import (
    is_safe_soft_fact_text,
)
from app.guide.presentation.fact_admission import (
    presentation_fact_role,
)


MAX_NARRATIVE_ATOMS = 8

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
    "longevity": 6,
    "product_form": 7,
    "suitable_skin": 8,
    "application_area": 9,
    "efficacy": 10,
    "ingredients_present": 11,
    "claimed_ingredients": 12,
    "skin_concern": 13,
    "coverage": 14,
    "mask_material": 15,
    "concentration": 16,
    "color_family": 17,
    "color_payoff": 18,
    "shade": 19,
    "makeup_style": 20,
    "fragrance_description": 21,
    "fragrance_family": 22,
    "cleansing_power": 23,
    "rinse_behavior": 24,
    "cleansing_requirement": 25,
    "double_cleanse": 26,
    "surfactant_type": 27,
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
            presentation_fact_role(fact.field_key) != "narrative"
            or not is_safe_soft_fact_text(
                fact.plain_meaning,
                attribution=fact.attribution,
                field_key=fact.field_key,
            )
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
        dimension_ids=tuple(
            dict.fromkeys(
                _normalize_dimension_id(
                    dimension_id,
                    source_field=item.field_key,
                    target_field=field_key,
                )
                for item in ordered
                for dimension_id in item.dimension_ids
            )
        ),
        plain_meaning="；".join(values),
        attribution=ordered[0].attribution,
        source_refs=tuple(sorted({
            ref
            for item in ordered
            for ref in item.source_refs
        })),
        generic_copy_allowed=all(
            item.generic_copy_allowed
            for item in ordered
        ),
    )


def _normalize_dimension_id(
    dimension_id: str,
    *,
    source_field: str,
    target_field: str,
) -> str:
    if source_field == target_field:
        return dimension_id
    suffix = dimension_id.removeprefix(source_field)
    return f"{target_field}{suffix}"


__all__ = ["MAX_NARRATIVE_ATOMS", "build_narrative_atoms"]
