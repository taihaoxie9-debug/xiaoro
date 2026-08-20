from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    PresentationPacket,
    SourceTaggedCopy,
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


def validate_copywriter_evidence(
    packet: PresentationPacket,
    draft: CopywriterDraft,
) -> None:
    if not isinstance(packet, PresentationPacket):
        raise TypeError("packet must be PresentationPacket")
    if not isinstance(draft, CopywriterDraft):
        raise TypeError("draft must be CopywriterDraft")
    responsibility = packet.responsibility
    if responsibility is None:
        raise CopyEvidenceError(
            "presentation packet has no responsibility"
        )
    summary_location = {
        Responsibility.RECOMMENDATION: "recommendation.summary",
        Responsibility.COMPARISON: "comparison.summary",
        Responsibility.SINGLE_PRODUCT_SUITABILITY: (
            "single_product_suitability.summary"
        ),
        Responsibility.PRODUCT_KNOWLEDGE: "product_knowledge.summary",
        Responsibility.GENERAL_KNOWLEDGE: "general_knowledge.body",
        Responsibility.CONSULTATION: "consultation.summary",
        Responsibility.IMAGE_IDENTITY: "image_identity.observation",
        Responsibility.CLARIFICATION: "clarification.question",
        Responsibility.SAFETY_ESCALATION: (
            "safety_escalation.summary"
        ),
    }[responsibility]
    _validate_block(
        packet,
        location=summary_location,
        block=draft.summary_copy,
    )
    slot_by_id = {slot.slot_id: slot for slot in packet.slots}
    for item in draft.product_copy:
        slot = slot_by_id[item.slot_id]
        if responsibility is Responsibility.RECOMMENDATION:
            positioning_location = "recommendation.product"
            advisor_location = "recommendation.advisor_reason"
        elif responsibility is Responsibility.COMPARISON:
            positioning_location = "comparison.product"
            advisor_location = "comparison.advisor_reason"
        elif (
            responsibility
            is Responsibility.SINGLE_PRODUCT_SUITABILITY
        ):
            positioning_location = "single_product_suitability.product"
            advisor_location = "single_product_suitability.judgement"
        elif responsibility is Responsibility.PRODUCT_KNOWLEDGE:
            positioning_location = "product_knowledge.answer"
            advisor_location = "product_knowledge.advisor_reason"
        else:
            positioning_location = "recommendation.product"
            advisor_location = "recommendation.advisor_reason"
        _validate_block(
            packet,
            location=positioning_location,
            block=item.positioning,
            slot_product_id=slot.product_id,
        )
        _validate_block(
            packet,
            location=advisor_location,
            block=item.advisor_reason,
            slot_product_id=slot.product_id,
        )
    if draft.closing_copy is not None:
        _validate_block(
            packet,
            location="recommendation.closing",
            block=draft.closing_copy,
        )


def _validate_block(
    packet: PresentationPacket,
    *,
    location: str,
    block: SourceTaggedCopy,
    slot_product_id: int | None = None,
) -> None:
    validate_copy_evidence(
        packet=packet,
        location=location,
        slot_product_id=slot_product_id,
        used_fact_ids=block.used_fact_ids,
        used_constraint_ids=block.used_constraint_ids,
    )


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
    "validate_copywriter_evidence",
]
