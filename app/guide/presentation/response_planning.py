"""Slice 1 展示层：把 DecisionResult 转成 ResponsePlan。

原则：严格按 DecisionResult.ordered_product_ids 顺序生成商品卡，
不重排、不改分、不补造缺失事实。商品事实由入参提供，
展示层不读取 Canonical、不 import 具体 adapter。
"""
from __future__ import annotations

from app.guide.decision.contracts import DecisionResult
from app.guide.presentation.contracts import (
    DisplayCategoryFact,
    ProductCard,
    ProductCardFacts,
    ResponsePlan,
)
from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    category_field_registry,
    filter_category_facts_by_capability,
    revalidate_authorized_category_fact,
)


class MissingProductFactsError(LookupError):
    pass


def project_display_category_facts(
    facts: tuple[AuthorizedCategoryFact, ...],
) -> tuple[AuthorizedCategoryFact, ...]:
    return tuple(
        fact
        for fact in filter_category_facts_by_capability(
            facts,
            "display",
        )
        if fact.resolved_state == "known"
    )


def project_public_category_facts(
    facts: tuple[AuthorizedCategoryFact, ...],
) -> tuple[DisplayCategoryFact, ...]:
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    projected: list[DisplayCategoryFact] = []
    for candidate in facts:
        fact = revalidate_authorized_category_fact(candidate)
        definition = definitions[fact.field_key]
        if (
            fact.resolved_state == "known"
            and "display" in fact.capabilities
        ):
            state = "known"
            value = fact.value
        elif fact.resolved_state == "conflict":
            state = "conflict"
            value = None
        else:
            state = "unavailable"
            value = None
        projected.append(
            DisplayCategoryFact(
                field_key=fact.field_key,
                label=definition.label,
                value=value,
                state=state,
            )
        )
    return tuple(projected)


def _merge_direct_display_facts(
    projected: tuple[DisplayCategoryFact, ...],
    facts: ProductCardFacts,
) -> tuple[DisplayCategoryFact, ...]:
    by_key = {fact.field_key: fact for fact in projected}
    direct_values = (
        (
            "efficacy",
            "功效",
            facts.efficacy,
            facts.efficacy_state,
        ),
        (
            "ingredients_present",
            "确认含有成分",
            facts.ingredients_present,
            facts.ingredients_present_state,
        ),
        (
            "suitable_skin",
            "适用肤质",
            facts.suitable_skin,
            facts.suitable_skin_state,
        ),
    )
    for field_key, label, value, state in direct_values:
        current = by_key.get(field_key)
        if state == "known" and value is not None:
            if current is not None and current.state == "known":
                merged = _merge_display_values(current.value, value)
                by_key[field_key] = DisplayCategoryFact(
                    field_key=field_key,
                    label=current.label,
                    value=merged,
                    state="known",
                )
                continue
            by_key[field_key] = DisplayCategoryFact(
                field_key=field_key,
                label=label,
                value=value,
                state="known",
            )
    return tuple(
        by_key[field_key]
        for field_key in sorted(by_key)
    )


def _merge_display_values(
    first,
    second,
):
    values: list[str] = []
    for value in (first, second):
        items = value if isinstance(value, tuple) else (value,)
        for item in items:
            if isinstance(item, str) and item not in values:
                values.append(item)
    return tuple(values) if values else first


def build_response_plan(
    decision: DecisionResult,
    *,
    product_facts: dict[int, ProductCardFacts],
) -> ResponsePlan:
    evaluations = {
        item.product_id: item
        for item in decision.evaluations
        if item.disposition == "eligible"
    }
    cards: list[ProductCard] = []
    for product_id in decision.ordered_product_ids:
        try:
            facts = product_facts[product_id]
            evaluation = evaluations[product_id]
        except KeyError as exc:
            raise MissingProductFactsError(
                f"missing presentation facts for product_id {product_id}"
            ) from exc
        cards.append(
            ProductCard(
                product_id=product_id,
                category_profile=facts.category_profile,
                category_facts=_merge_direct_display_facts(
                    project_public_category_facts(
                        facts.category_fields
                    ),
                    facts,
                ),
                variant_scope=facts.variant_scope,
                specification=facts.specification,
                name=facts.name,
                brand=facts.brand,
                category=facts.category,
                price=facts.price,
                image_url=facts.image_url,
                detail_url=facts.detail_url,
                platform=facts.platform,
                image_source_sha256=facts.image_source_sha256,
                skin_match=evaluation.skin_match,
                matched_efficacies=list(
                    evaluation.matched_efficacies
                ),
                fact_warnings=list(facts.fact_warnings),
            )
        )

    return ResponsePlan(
        sections=["recommendation"],
        structured_events=cards,
        text_generation_context={
            "winner_status": decision.winner_status.value,
            "evidence_refs": list(decision.evidence_refs),
            "comparison_dimensions": list(decision.comparison_dimensions),
            "risk_findings": [
                item.model_dump(mode="json")
                for item in decision.risk_findings
            ],
        },
        followup_actions=[],
    )
