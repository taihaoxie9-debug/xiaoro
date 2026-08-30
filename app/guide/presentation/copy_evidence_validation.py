from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from app.guide.presentation.copywriter_contracts import (
    PresentationPacket,
)


FactScope = Literal["forbidden", "slot", "single", "visible"]

_FACT_SCOPE_BY_LOCATION: dict[str, FactScope] = {
    "recommendation.summary": "forbidden",
    "recommendation.product": "slot",
    "recommendation.advisor_reason": "slot",
    "recommendation.closing": "visible",
    "comparison.summary": "forbidden",
    "comparison.product": "slot",
    "comparison.advisor_reason": "slot",
    "single_product_suitability.summary": "single",
    "single_product_suitability.product": "slot",
    "single_product_suitability.judgement": "single",
    "product_knowledge.summary": "single",
    "product_knowledge.answer": "single",
    "product_knowledge.advisor_reason": "slot",
    "general_knowledge.body": "forbidden",
    "consultation.observation": "forbidden",
    "consultation.summary": "forbidden",
    "image_identity.observation": "forbidden",
    "clarification.question": "forbidden",
    "clarification.error": "forbidden",
    "safety_escalation.observation": "forbidden",
    "safety_escalation.summary": "forbidden",
}
_GENERIC_COPY_LOCATIONS = frozenset({
    "recommendation.product",
    "recommendation.advisor_reason",
    "recommendation.closing",
    "comparison.product",
    "comparison.advisor_reason",
})


class CopyEvidenceError(ValueError):
    pass


def validate_copy_evidence(
    *,
    packet: PresentationPacket,
    location: str,
    used_fact_ids: Sequence[str],
    used_constraint_ids: Sequence[str],
    slot_product_id: int | None = None,
) -> None:
    if not isinstance(packet, PresentationPacket):
        raise TypeError("packet must be PresentationPacket")
    scope = _FACT_SCOPE_BY_LOCATION.get(location)
    if scope is None:
        raise CopyEvidenceError(
            f"unknown copy evidence location: {location}"
        )
    fact_ids = _ordered_ids(used_fact_ids, label="fact")
    constraint_ids = _ordered_ids(
        used_constraint_ids,
        label="constraint",
    )
    fact_owner = {}
    fact_by_id = {}
    for slot in packet.slots:
        for fact in slot.approved_soft_facts:
            if fact.fact_id in fact_owner:
                raise CopyEvidenceError(
                    "fact authority contains duplicate IDs"
                )
            fact_owner[fact.fact_id] = slot.product_id
            fact_by_id[fact.fact_id] = fact
    unknown_facts = set(fact_ids) - set(fact_owner)
    if unknown_facts:
        raise CopyEvidenceError(
            "fact authority does not contain used IDs"
        )
    approved_constraint_ids = {
        item.constraint_id for item in packet.approved_constraints
    }
    if set(constraint_ids) - approved_constraint_ids:
        raise CopyEvidenceError(
            "constraint authority does not contain used IDs"
        )
    if not fact_ids:
        return
    if (
        location in _GENERIC_COPY_LOCATIONS
        and any(
            not fact_by_id[fact_id].generic_copy_allowed
            for fact_id in fact_ids
        )
    ):
        raise CopyEvidenceError(
            "variant-restricted fact is forbidden in generic recommendation copy"
        )
    if scope == "forbidden":
        raise CopyEvidenceError(
            "fact location does not permit product facts"
        )
    visible_ids = tuple(slot.product_id for slot in packet.slots)
    owners = tuple(fact_owner[fact_id] for fact_id in fact_ids)
    if scope == "slot":
        if slot_product_id is None:
            raise CopyEvidenceError(
                "slot location requires product ownership"
            )
        if any(owner != slot_product_id for owner in owners):
            raise CopyEvidenceError(
                "fact ownership does not match copy slot"
            )
    elif scope == "single":
        if len(visible_ids) != 1:
            raise CopyEvidenceError(
                "single-product location requires one visible product"
            )
        if any(owner != visible_ids[0] for owner in owners):
            raise CopyEvidenceError(
                "fact ownership does not match visible product"
            )
    elif any(owner not in visible_ids for owner in owners):
        raise CopyEvidenceError(
            "fact ownership is outside visible products"
        )


def _ordered_ids(
    values: Sequence[str],
    *,
    label: str,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"used {label} IDs must be a sequence")
    normalized = tuple(values)
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        for value in normalized
    ):
        raise ValueError(f"used {label} IDs must be nonempty strings")
    if len(normalized) != len(set(normalized)):
        raise CopyEvidenceError(
            f"used {label} IDs must be unique"
        )
    return normalized


__all__ = [
    "CopyEvidenceError",
    "validate_copy_evidence",
]
