from __future__ import annotations

from collections.abc import Collection

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.public_fact_contracts import (
    ProductPublicFactProjection,
    ProjectedPublicFact,
)


_DETAIL_PRIORITY = (
    "brand_main",
    "ingredients_present",
    "texture",
    "efficacy",
    "usage",
    "suitable_skin",
)
_IMAGE_IDENTITY_SAFE_FIELDS = (
    "ingredients_present",
    "texture",
    "efficacy",
    "product_form",
    "category",
)
_RECOMMENDATION_DETAIL_FORBIDDEN_FIELDS = frozenset({
    "price",
    "reference_price",
    "specification",
    "net_content",
})


def select_product_detail_facts(
    *,
    projection: ProductPublicFactProjection,
    responsibility: Responsibility,
    requested_dimensions: Collection[str],
) -> tuple[ProjectedPublicFact, ...]:
    if not isinstance(projection, ProductPublicFactProjection):
        raise TypeError(
            "projection must be ProductPublicFactProjection"
        )
    if not isinstance(responsibility, Responsibility):
        raise TypeError("responsibility must be Responsibility")
    requested = _requested_parent_fields(requested_dimensions)
    if responsibility is Responsibility.COMPARISON:
        return ()
    if responsibility is Responsibility.IMAGE_IDENTITY:
        return _select_image_identity_facts(projection)

    if responsibility is Responsibility.PRODUCT_KNOWLEDGE:
        return _select_product_knowledge_facts(
            projection,
            requested=requested,
        )
    else:
        eligible_facts = tuple(
            fact
            for fact in projection.facts
            if (
                fact.field_key
                not in _RECOMMENDATION_DETAIL_FORBIDDEN_FIELDS
            )
        )
        order = tuple(dict.fromkeys((
            "brand_main",
            *requested,
            *_DETAIL_PRIORITY,
            *(fact.field_key for fact in eligible_facts),
        )))
    return _select_by_field_order(
        eligible_facts,
        field_order=order,
        limit=3,
    )


def _select_image_identity_facts(
    projection: ProductPublicFactProjection,
) -> tuple[ProjectedPublicFact, ...]:
    selected: list[ProjectedPublicFact] = []
    brand_main = next(
        (
            fact
            for fact in projection.facts
            if fact.field_key == "brand_main"
        ),
        None,
    )
    if brand_main is not None:
        selected.append(brand_main)
    category_facts = tuple(
        fact
        for fact in projection.facts
        if (
            fact.source_kind == "category"
            and fact.field_key in _IMAGE_IDENTITY_SAFE_FIELDS
        )
    )
    selected.extend(
        _select_by_field_order(
            category_facts,
            field_order=_IMAGE_IDENTITY_SAFE_FIELDS,
            limit=2,
        )
    )
    return tuple(selected[:3])


def _select_product_knowledge_facts(
    projection: ProductPublicFactProjection,
    *,
    requested: tuple[str, ...],
) -> tuple[ProjectedPublicFact, ...]:
    facts = projection.facts
    selected_evidence = next(
        (
            fact
            for fact in facts
            if fact.fact_id.startswith("evidence:")
        ),
        None,
    )
    has_requested_fact = any(
        fact.field_key in requested for fact in facts
    )
    if selected_evidence is None and (
        not requested or not has_requested_fact
    ):
        return ()

    selected: list[ProjectedPublicFact] = []
    if selected_evidence is not None:
        selected.append(selected_evidence)
    used_ids = {fact.fact_id for fact in selected}
    used_fields = {fact.field_key for fact in selected}
    order = tuple(dict.fromkeys((
        *requested,
        *_DETAIL_PRIORITY,
        *(fact.field_key for fact in facts),
    )))
    for field_key in order:
        if field_key in used_fields:
            continue
        fact = next(
            (
                item
                for item in facts
                if (
                    item.field_key == field_key
                    and item.fact_id not in used_ids
                )
            ),
            None,
        )
        if fact is None:
            continue
        selected.append(fact)
        used_ids.add(fact.fact_id)
        used_fields.add(fact.field_key)
        if len(selected) == 3:
            break
    return tuple(selected)


def _select_by_field_order(
    facts: tuple[ProjectedPublicFact, ...],
    *,
    field_order: tuple[str, ...],
    limit: int,
) -> tuple[ProjectedPublicFact, ...]:
    output: list[ProjectedPublicFact] = []
    used_ids: set[str] = set()
    for field_key in field_order:
        fact = next(
            (
                item
                for item in facts
                if (
                    item.field_key == field_key
                    and item.fact_id not in used_ids
                )
            ),
            None,
        )
        if fact is None:
            continue
        output.append(fact)
        used_ids.add(fact.fact_id)
        if len(output) == limit:
            break
    return tuple(output)


def _requested_parent_fields(
    values: Collection[str],
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("requested_dimensions must be a collection")
    requested = tuple(values)
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        for value in requested
    ):
        raise ValueError(
            "requested dimensions must be nonempty strings"
        )
    return tuple(dict.fromkeys(
        value.split(".", 1)[0]
        for value in requested
    ))


__all__ = ["select_product_detail_facts"]
