from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.guide.decision.contracts import DecisionProductFacts
from app.guide.intent.contracts import ConceptConstraint
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptFact,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)


@dataclass(frozen=True, slots=True)
class ConceptSlotRanking:
    product_id: int
    field_key: str
    concept_id: str
    polarity: Literal["prefer", "avoid"]
    match_status: Literal["matched", "unknown", "mismatch"]
    stance: Literal["supports", "opposes"] | None
    rank_strength: Literal[1, 2] | None
    source_values: tuple[str, ...]
    source_refs: tuple[str, ...]
    attribution: Literal[
        "verified_fact",
        "merchant_claim",
        "consumer_report",
    ] | None


@dataclass(frozen=True, slots=True)
class CommonConceptRanking:
    mismatch_count: int
    unknown_count: int
    matched_slot_count: int
    weighted_match_score: int
    matched_source_refs: tuple[str, ...]
    slots: tuple[ConceptSlotRanking, ...]


def rank_common_concepts(
    product: DecisionProductFacts,
    constraints: tuple[ConceptConstraint, ...],
    *,
    reader: SelectionParentConceptReader,
    safety_sensitive: bool = False,
) -> CommonConceptRanking:
    if not isinstance(product, DecisionProductFacts):
        raise TypeError("product must be DecisionProductFacts")
    if not isinstance(reader, SelectionParentConceptReader):
        raise TypeError(
            "reader must be SelectionParentConceptReader"
        )
    if not isinstance(safety_sensitive, bool):
        raise TypeError("safety_sensitive must be bool")
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    slot_keys: list[tuple[str, str, str]] = []
    for constraint in constraints:
        if not isinstance(constraint, ConceptConstraint):
            raise TypeError(
                "constraints must contain ConceptConstraint"
            )
        definition = definitions.get(constraint.field_key)
        if (
            definition is None
            or product.category_profile not in definition.profiles
        ):
            raise ValueError(
                "concept field is not applicable to product profile"
            )
        slot_keys.append(
            (
                constraint.field_key,
                constraint.concept_id,
                constraint.polarity,
            )
        )
    if len(slot_keys) != len(set(slot_keys)):
        raise ValueError("duplicate concept constraint")

    source_facts = tuple(
        fact
        for fact in product.selection_facts
        if not (
            safety_sensitive
            and fact.safety_role == "merchant_positive_safety"
        )
    )
    projected = {
        item.concept_id: item
        for item in reader.project(source_facts)
    }
    mismatch_count = 0
    unknown_count = 0
    matched_slot_count = 0
    weighted_match_score = 0
    matched_refs: set[str] = set()
    slots: list[ConceptSlotRanking] = []
    for constraint in constraints:
        fact = projected.get(constraint.concept_id)
        if fact is None:
            unknown_count += 1
            slots.append(
                _slot(
                    product_id=product.product_id,
                    constraint=constraint,
                    status="unknown",
                    fact=None,
                )
            )
            continue
        matching_stance = (
            "supports"
            if constraint.polarity == "prefer"
            else "opposes"
        )
        if fact.stance != matching_stance:
            mismatch_count += 1
            slots.append(
                _slot(
                    product_id=product.product_id,
                    constraint=constraint,
                    status="mismatch",
                    fact=fact,
                )
            )
            continue
        matched_slot_count += 1
        weighted_match_score += fact.rank_strength
        matched_refs.update(fact.source_refs)
        slots.append(
            _slot(
                product_id=product.product_id,
                constraint=constraint,
                status="matched",
                fact=fact,
            )
        )

    return CommonConceptRanking(
        mismatch_count=mismatch_count,
        unknown_count=unknown_count,
        matched_slot_count=matched_slot_count,
        weighted_match_score=weighted_match_score,
        matched_source_refs=tuple(sorted(matched_refs)),
        slots=tuple(slots),
    )


def _slot(
    *,
    product_id: int,
    constraint: ConceptConstraint,
    status: Literal["matched", "unknown", "mismatch"],
    fact: SelectionConceptFact | None,
) -> ConceptSlotRanking:
    return ConceptSlotRanking(
        product_id=product_id,
        field_key=constraint.field_key,
        concept_id=constraint.concept_id,
        polarity=constraint.polarity,
        match_status=status,
        stance=fact.stance if fact is not None else None,
        rank_strength=(
            fact.rank_strength if fact is not None else None
        ),
        source_values=(
            fact.source_values if fact is not None else ()
        ),
        source_refs=fact.source_refs if fact is not None else (),
        attribution=(
            _attribution(fact) if fact is not None else None
        ),
    )


def _attribution(
    fact: SelectionConceptFact,
) -> Literal[
    "verified_fact",
    "merchant_claim",
    "consumer_report",
]:
    for attribution in (
        "verified_fact",
        "consumer_report",
        "merchant_claim",
    ):
        if attribution in fact.attributions:
            return attribution
    raise ValueError("concept fact requires attribution")


__all__ = [
    "CommonConceptRanking",
    "ConceptSlotRanking",
    "rank_common_concepts",
]
