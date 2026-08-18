from __future__ import annotations

from collections.abc import Sequence

from app.guide.retrieval.selection_fact_contracts import SelectionFact


def resolve_card_specification(
    facts: Sequence[SelectionFact],
    *,
    variant_scope: str | None,
) -> str | None:
    if (
        isinstance(facts, (str, bytes))
        or not isinstance(facts, Sequence)
        or any(not isinstance(fact, SelectionFact) for fact in facts)
    ):
        raise TypeError("facts must contain SelectionFact values")
    if variant_scope is not None and (
        not isinstance(variant_scope, str)
        or not variant_scope.strip()
    ):
        raise TypeError("variant_scope must be a nonempty string or None")

    candidates = tuple(
        fact
        for fact in facts
        if (
            fact.field_key == "net_content"
            and "compare" in fact.capabilities
            and fact.safety_role == "ordinary"
            and _is_atomic_specification(fact.normalized_value)
        )
    )
    if variant_scope is not None:
        exact_values = {
            fact.normalized_value
            for fact in candidates
            if (
                fact.subject_scope == "exact_variant"
                and fact.variant_scope == variant_scope
            )
        }
        if len(exact_values) == 1:
            return next(iter(exact_values))
        if len(exact_values) > 1:
            return None
    else:
        unbound_variant_values = {
            fact.normalized_value
            for fact in candidates
            if fact.subject_scope == "exact_variant"
        }
        if len(unbound_variant_values) > 1:
            return None

    product_values = {
        fact.normalized_value
        for fact in candidates
        if (
            fact.subject_scope == "exact_product"
            and fact.variant_scope is None
        )
    }
    return (
        next(iter(product_values))
        if len(product_values) == 1
        else None
    )


def _is_atomic_specification(value: str) -> bool:
    return not any(
        character.isspace() or character in {",", "，", ";", "；"}
        for character in value
    )


__all__ = ["resolve_card_specification"]
