from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.guide.decision.contracts import DecisionProductFacts
from app.guide.intent.contracts import FacetConstraint
from app.guide.intent.facet_preferences import canonical_facet_values
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.selection_fact_contracts import SelectionFact


_FACT_FIELDS_BY_REQUEST = {
    "ingredients_present": frozenset({
        "ingredients_present",
        "claimed_ingredients",
    }),
    "verified_absences": frozenset({
        "verified_absences",
        "claimed_absences",
    }),
}


@dataclass(frozen=True, slots=True)
class SelectionSlotRanking:
    product_id: int
    field_key: str
    requested_value: str
    matched_value: str | None
    match_status: Literal["matched", "unknown", "mismatch"]
    rank_strength: Literal[1, 2] | None
    source_refs: tuple[str, ...]
    attribution: Literal[
        "verified_fact",
        "merchant_claim",
        "consumer_report",
    ] | None


@dataclass(frozen=True, slots=True)
class SoftFacetRanking:
    mismatch_count: int
    unknown_count: int
    matched_slot_count: int
    weighted_match_score: int
    matched_source_refs: tuple[str, ...]
    slots: tuple[SelectionSlotRanking, ...]


def rank_soft_facets(
    product: DecisionProductFacts,
    constraints: tuple[FacetConstraint, ...],
    *,
    safety_sensitive: bool = False,
) -> SoftFacetRanking:
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    slots: list[tuple[str, str]] = []
    for constraint in constraints:
        definition = definitions.get(constraint.field_key)
        if definition is None:
            raise ValueError(
                f"unknown soft facet field: {constraint.field_key}"
            )
        if product.category_profile not in definition.profiles:
            raise ValueError(
                "soft facet field is not applicable to profile: "
                f"{product.category_profile.value}.{constraint.field_key}"
            )
        slots.extend(
            (constraint.field_key, target)
            for target in sorted(
                canonical_facet_values(
                    constraint.field_key,
                    constraint.value,
                )
            )
        )
    if len(slots) != len(set(slots)):
        raise ValueError("duplicate soft facet constraint")

    mismatch_count = 0
    unknown_count = 0
    matched_slot_count = 0
    weighted_match_score = 0
    matched_source_refs: set[str] = set()
    ranked_slots: list[SelectionSlotRanking] = []
    for field_key, requested in slots:
        facts = tuple(
            fact
            for fact in product.selection_facts
            if _is_applicable_soft_fact(
                fact,
                field_key=field_key,
                safety_sensitive=safety_sensitive,
            )
        )
        if not facts:
            unknown_count += 1
            ranked_slots.append(
                SelectionSlotRanking(
                    product_id=product.product_id,
                    field_key=field_key,
                    requested_value=requested,
                    matched_value=None,
                    match_status="unknown",
                    rank_strength=None,
                    source_refs=(),
                    attribution=None,
                )
            )
            continue
        matches = tuple(
            fact
            for fact in facts
            if requested
            in canonical_facet_values(
                field_key,
                fact.normalized_value,
            )
        )
        if not matches:
            unknown_count += 1
            ranked_slots.append(
                SelectionSlotRanking(
                    product_id=product.product_id,
                    field_key=field_key,
                    requested_value=requested,
                    matched_value=None,
                    match_status="unknown",
                    rank_strength=None,
                    source_refs=(),
                    attribution=None,
                )
            )
            continue
        matched_slot_count += 1
        strength = max(
            fact.rank_strength or 0
            for fact in matches
        )
        weighted_match_score += strength
        source_refs = tuple(sorted({
            reference
            for fact in matches
            for reference in fact.source_refs
        }))
        matched_source_refs.update(source_refs)
        strongest = tuple(
            fact
            for fact in matches
            if fact.rank_strength == strength
        )
        attribution = _slot_attribution(strongest)
        ranked_slots.append(
            SelectionSlotRanking(
                product_id=product.product_id,
                field_key=field_key,
                requested_value=requested,
                matched_value=min(
                    fact.normalized_value for fact in strongest
                ),
                match_status="matched",
                rank_strength=strength,
                source_refs=source_refs,
                attribution=attribution,
            )
        )

    return SoftFacetRanking(
        mismatch_count=mismatch_count,
        unknown_count=unknown_count,
        matched_slot_count=matched_slot_count,
        weighted_match_score=weighted_match_score,
        matched_source_refs=tuple(sorted(matched_source_refs)),
        slots=tuple(ranked_slots),
    )


def _is_applicable_soft_fact(
    fact: SelectionFact,
    *,
    field_key: str,
    safety_sensitive: bool,
) -> bool:
    return (
        fact.field_key
        in _FACT_FIELDS_BY_REQUEST.get(
            field_key,
            frozenset({field_key}),
        )
        and fact.subject_scope == "exact_product"
        and fact.variant_scope is None
        and "soft_rank" in fact.capabilities
        and not (
            safety_sensitive
            and fact.safety_role == "merchant_positive_safety"
        )
    )


def _slot_attribution(
    facts: tuple[SelectionFact, ...],
) -> Literal[
    "verified_fact",
    "merchant_claim",
    "consumer_report",
]:
    attributions = {
        attribution
        for fact in facts
        for attribution in fact.attributions
    }
    for attribution in (
        "verified_fact",
        "consumer_report",
        "merchant_claim",
    ):
        if attribution in attributions:
            return attribution
    raise ValueError("matched selection slot requires attribution")
