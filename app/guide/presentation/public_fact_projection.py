from __future__ import annotations

from collections.abc import Collection, Sequence
import re
import unicodedata

from app.guide.presentation.contracts import ProductCard
from app.guide.presentation.copywriter_contracts import ApprovedSoftFact
from app.guide.presentation.public_fact_contracts import (
    ProductPublicFactProjection,
    ProjectedPublicFact,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)


_SPACE = re.compile(r"\s+")
_LABEL_OVERRIDES = {
    "brand_main": "品牌主打",
    "ingredients_present": "核心成分",
    "suitable_skin": "适合肤质",
    "efficacy": "功效方向",
    "usage": "使用方式",
    "usage_context": "使用场景",
    "consumer_report": "使用反馈",
    "faq": "使用问答",
    "merchant_test": "品牌测试",
    "packaging_information": "包装信息",
    "product_information": "商品信息",
    "safety_information": "使用提醒",
}
_FIELD_PRIORITY = (
    "brand_main",
    "ingredients_present",
    "texture",
    "efficacy",
    "usage",
    "suitable_skin",
    "usage_context",
)


def project_public_facts(
    *,
    card: ProductCard,
    approved_soft_facts: Sequence[ApprovedSoftFact],
    requested_dimensions: Collection[str],
) -> ProductPublicFactProjection:
    if not isinstance(card, ProductCard):
        raise TypeError("card must be ProductCard")
    approved = tuple(approved_soft_facts)
    if any(not isinstance(fact, ApprovedSoftFact) for fact in approved):
        raise TypeError(
            "approved_soft_facts must contain ApprovedSoftFact values"
        )
    if any(fact.product_id != card.product_id for fact in approved):
        raise ValueError(
            "approved soft facts must belong to projection product"
        )
    requested = _requested_parent_fields(requested_dimensions)
    brand_source = next(
        (
            fact
            for fact in approved
            if fact.field_key == "brand_main"
        ),
        None,
    )
    if brand_source is None:
        brand_source = next(
            (
                fact
                for fact in approved
                if fact.attribution == "merchant_claim"
            ),
            None,
        )

    candidates: list[ProjectedPublicFact] = []
    for fact in approved:
        if _is_category_derived_soft_fact(fact):
            continue
        field_key = (
            "brand_main"
            if fact is brand_source
            else fact.field_key
        )
        label = _field_label(field_key)
        candidates.append(
            ProjectedPublicFact(
                fact_id=fact.fact_id,
                product_id=fact.product_id,
                field_key=field_key,
                label=label,
                display_value=_soft_display_value(
                    fact,
                    label=label,
                    field_key=field_key,
                ),
                source_refs=fact.source_refs,
                source_kind=_soft_source_kind(fact),
                attribution=fact.attribution,
            )
        )

    for fact in card.category_facts:
        if fact.state != "known" or fact.value is None:
            continue
        candidates.append(
            ProjectedPublicFact(
                fact_id=(
                    f"category:{card.product_id}:{fact.field_key}"
                ),
                product_id=card.product_id,
                field_key=fact.field_key,
                label=_field_label(
                    fact.field_key,
                    fallback=fact.label,
                ),
                display_value=_display_value(fact.value),
                source_refs=(
                    f"card:{card.product_id}:{fact.field_key}",
                ),
                source_kind="category",
                attribution="verified_fact",
            )
        )

    deduplicated: list[ProjectedPublicFact] = []
    seen: set[tuple[int, str, str]] = set()
    for fact in candidates:
        identity = (
            fact.product_id,
            fact.field_key,
            _normalized_identity(fact.display_value),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(fact)

    order = tuple(dict.fromkeys((
        "brand_main",
        *requested,
        *_FIELD_PRIORITY,
        *(fact.field_key for fact in deduplicated),
    )))
    rank = {
        field_key: index
        for index, field_key in enumerate(order)
    }
    positioned = {
        id(fact): index
        for index, fact in enumerate(deduplicated)
    }
    return ProductPublicFactProjection(
        product_id=card.product_id,
        facts=tuple(sorted(
            deduplicated,
            key=lambda fact: (
                (
                    0
                    if fact.fact_id.startswith("evidence:")
                    else 1
                ),
                (
                    positioned[id(fact)]
                    if fact.fact_id.startswith("evidence:")
                    else rank[fact.field_key]
                ),
                positioned[id(fact)],
            ),
        )),
    )


def projected_fact_to_soft_fact(
    fact: ProjectedPublicFact,
) -> ApprovedSoftFact:
    if not isinstance(fact, ProjectedPublicFact):
        raise TypeError("fact must be ProjectedPublicFact")
    return ApprovedSoftFact(
        fact_id=fact.fact_id,
        product_id=fact.product_id,
        field_key=fact.field_key,
        plain_meaning=f"{fact.label}：{fact.display_value}",
        attribution=fact.attribution,
        source_refs=fact.source_refs,
        generic_copy_allowed=fact.source_kind != "category",
    )


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


def _field_label(
    field_key: str,
    *,
    fallback: str | None = None,
) -> str:
    if field_key in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[field_key]
    definitions = {
        definition.key: definition.label
        for definition in category_field_registry().definitions
    }
    return definitions.get(field_key, fallback or field_key)


def _soft_display_value(
    fact: ApprovedSoftFact,
    *,
    label: str,
    field_key: str,
) -> str:
    value = fact.plain_meaning.strip()
    if (
        field_key == "brand_main"
        and fact.attribution == "merchant_claim"
    ):
        value = value.removeprefix("品牌主打：")
        value = value.replace("；品牌主打：", "；")
    prefixes = [f"{label}："]
    if (
        field_key == "brand_main"
        and fact.attribution == "merchant_claim"
    ):
        prefixes.insert(0, "品牌主打：")
    for prefix in prefixes:
        if value.startswith(prefix):
            stripped = value[len(prefix):].strip()
            if stripped:
                return stripped
    return value


def _soft_source_kind(fact: ApprovedSoftFact) -> str:
    if fact.attribution == "merchant_claim":
        return "merchant"
    if fact.attribution == "consumer_report":
        return "review"
    return "evidence"


def _is_category_derived_soft_fact(
    fact: ApprovedSoftFact,
) -> bool:
    source_prefix = f"card:{fact.product_id}:"
    return (
        fact.attribution == "verified_fact"
        and bool(fact.source_refs)
        and all(
            source_ref.startswith(source_prefix)
            for source_ref in fact.source_refs
        )
    )


def _display_value(value: object) -> str:
    if isinstance(value, tuple):
        output = "、".join(str(item) for item in value)
    else:
        output = str(value)
    normalized = _SPACE.sub(" ", output).strip()
    if not normalized:
        raise ValueError("projected public display value is empty")
    return normalized[:512]


def _normalized_identity(value: str) -> str:
    return _SPACE.sub(
        " ",
        unicodedata.normalize("NFKC", value).casefold(),
    ).strip()


__all__ = [
    "project_public_facts",
    "projected_fact_to_soft_fact",
]
