from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict


ProcessorKind = Literal[
    "recommendation",
    "comparison",
    "image_comparison",
    "product_knowledge",
    "general_knowledge",
    "image_identity",
    "consultation",
    "clarification",
    "safety_escalation",
]


class Responsibility(str, Enum):
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    SINGLE_PRODUCT_SUITABILITY = "single_product_suitability"
    PRODUCT_KNOWLEDGE = "product_knowledge"
    GENERAL_KNOWLEDGE = "general_knowledge"
    CONSULTATION = "consultation"
    IMAGE_IDENTITY = "image_identity"
    CLARIFICATION = "clarification"
    SAFETY_ESCALATION = "safety_escalation"


Operation = Literal[
    "recommendation",
    "comparison",
    "suitability",
    "image_identity",
    "image_similarity",
    "knowledge",
    "assessment",
    "followup",
    "clarification",
]
ObjectCardinality = Literal[
    "zero",
    "one",
    "two_or_three",
    "over_limit",
    "unresolved",
]
ObjectType = Literal[
    "none",
    "candidate_ordinals",
    "current_batch",
    "current_product",
    "explicit_products",
    "image_ordinals",
    "confirmed_images",
    "topic",
]
DialogueState = Literal[
    "empty",
    "recommendation_batch",
    "single_product_focus",
    "comparison_batch",
    "consultation",
    "general_knowledge",
    "confirmed_image_product",
    "pending_clarification",
    "safety_escalation",
]
ResponsibilityPresentationMode = Literal[
    "recommendation",
    "comparison",
    "single_product",
    "product_knowledge",
    "general_knowledge",
    "consultation",
    "image_identity",
    "clarification",
]


OPERATIONS: tuple[Operation, ...] = (
    "recommendation",
    "comparison",
    "suitability",
    "image_identity",
    "image_similarity",
    "knowledge",
    "assessment",
    "followup",
    "clarification",
)
OBJECT_CARDINALITIES: tuple[ObjectCardinality, ...] = (
    "zero",
    "one",
    "two_or_three",
    "over_limit",
    "unresolved",
)
OBJECT_TYPES: tuple[ObjectType, ...] = (
    "none",
    "candidate_ordinals",
    "current_batch",
    "current_product",
    "explicit_products",
    "image_ordinals",
    "confirmed_images",
    "topic",
)
DIALOGUE_STATES: tuple[DialogueState, ...] = (
    "empty",
    "recommendation_batch",
    "single_product_focus",
    "comparison_batch",
    "consultation",
    "general_knowledge",
    "confirmed_image_product",
    "pending_clarification",
    "safety_escalation",
)


class ResponsibilityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    responsibility: Responsibility
    processor: ProcessorKind
    presentation_mode: ResponsibilityPresentationMode
    preserve_product_order: bool
    clarification_code: str | None = None


_RESPONSIBILITY_SHAPES: dict[
    Responsibility,
    tuple[ProcessorKind, ResponsibilityPresentationMode, bool],
] = {
    Responsibility.RECOMMENDATION: (
        "recommendation",
        "recommendation",
        True,
    ),
    Responsibility.COMPARISON: (
        "comparison",
        "comparison",
        True,
    ),
    Responsibility.SINGLE_PRODUCT_SUITABILITY: (
        "product_knowledge",
        "single_product",
        True,
    ),
    Responsibility.PRODUCT_KNOWLEDGE: (
        "product_knowledge",
        "product_knowledge",
        True,
    ),
    Responsibility.GENERAL_KNOWLEDGE: (
        "general_knowledge",
        "general_knowledge",
        False,
    ),
    Responsibility.CONSULTATION: (
        "consultation",
        "consultation",
        False,
    ),
    Responsibility.IMAGE_IDENTITY: (
        "image_identity",
        "image_identity",
        True,
    ),
    Responsibility.CLARIFICATION: (
        "clarification",
        "clarification",
        False,
    ),
    Responsibility.SAFETY_ESCALATION: (
        "safety_escalation",
        "consultation",
        False,
    ),
}

_DIRECT_RULES: dict[
    tuple[Operation, ObjectCardinality],
    Responsibility,
] = {
    ("recommendation", "zero"): Responsibility.RECOMMENDATION,
    ("recommendation", "one"): Responsibility.RECOMMENDATION,
    ("recommendation", "two_or_three"): Responsibility.RECOMMENDATION,
    ("image_similarity", "zero"): Responsibility.CLARIFICATION,
    ("image_similarity", "one"): Responsibility.RECOMMENDATION,
    ("image_similarity", "two_or_three"): Responsibility.RECOMMENDATION,
    ("comparison", "zero"): Responsibility.CLARIFICATION,
    ("comparison", "two_or_three"): Responsibility.COMPARISON,
    ("suitability", "zero"): Responsibility.CLARIFICATION,
    (
        "suitability",
        "one",
    ): Responsibility.SINGLE_PRODUCT_SUITABILITY,
    ("suitability", "two_or_three"): Responsibility.COMPARISON,
    ("knowledge", "zero"): Responsibility.GENERAL_KNOWLEDGE,
    ("knowledge", "one"): Responsibility.PRODUCT_KNOWLEDGE,
    ("knowledge", "two_or_three"): Responsibility.COMPARISON,
    ("assessment", "zero"): Responsibility.CONSULTATION,
    (
        "assessment",
        "one",
    ): Responsibility.SINGLE_PRODUCT_SUITABILITY,
    ("assessment", "two_or_three"): Responsibility.COMPARISON,
    ("image_identity", "zero"): Responsibility.CLARIFICATION,
    ("image_identity", "one"): Responsibility.IMAGE_IDENTITY,
    (
        "image_identity",
        "two_or_three",
    ): Responsibility.IMAGE_IDENTITY,
    ("clarification", "zero"): Responsibility.CLARIFICATION,
    ("clarification", "one"): Responsibility.PRODUCT_KNOWLEDGE,
    (
        "clarification",
        "two_or_three",
    ): Responsibility.CLARIFICATION,
}

_UNBOUND_FOLLOWUP_RULES: dict[DialogueState, Responsibility] = {
    "recommendation_batch": Responsibility.RECOMMENDATION,
    "general_knowledge": Responsibility.GENERAL_KNOWLEDGE,
    "consultation": Responsibility.CONSULTATION,
}


def resolve_responsibility(
    *,
    operation: Operation,
    cardinality: ObjectCardinality,
    object_type: ObjectType,
    dialogue_state: DialogueState,
    safety: bool,
) -> ResponsibilityDecision:
    _validate_inputs(
        operation=operation,
        cardinality=cardinality,
        object_type=object_type,
        dialogue_state=dialogue_state,
        safety=safety,
    )
    if safety:
        return decision_for_responsibility(
            Responsibility.SAFETY_ESCALATION
        )
    if cardinality == "over_limit":
        return decision_for_responsibility(
            Responsibility.CLARIFICATION,
            clarification_code="reference_over_limit",
        )
    if cardinality == "unresolved":
        return decision_for_responsibility(
            Responsibility.CLARIFICATION,
            clarification_code="reference_unresolved",
        )
    if operation == "comparison" and cardinality == "one":
        if object_type == "confirmed_images":
            return decision_for_responsibility(
                Responsibility.RECOMMENDATION
            )
        return decision_for_responsibility(
            Responsibility.CLARIFICATION,
            clarification_code="comparison_requires_multiple",
        )
    if operation == "followup":
        if cardinality == "one":
            return decision_for_responsibility(
                Responsibility.PRODUCT_KNOWLEDGE
            )
        if cardinality == "two_or_three":
            return decision_for_responsibility(
                Responsibility.COMPARISON
            )
        return decision_for_responsibility(
            _UNBOUND_FOLLOWUP_RULES.get(
                dialogue_state,
                Responsibility.CLARIFICATION,
            ),
            clarification_code=(
                "reference_unresolved"
                if dialogue_state
                not in _UNBOUND_FOLLOWUP_RULES
                else None
            ),
        )
    if (
        operation == "clarification"
        and cardinality == "zero"
        and dialogue_state == "consultation"
    ):
        return decision_for_responsibility(
            Responsibility.CONSULTATION
        )
    responsibility = _DIRECT_RULES[(operation, cardinality)]
    return decision_for_responsibility(
        responsibility,
        clarification_code=(
            "reference_unresolved"
            if responsibility is Responsibility.CLARIFICATION
            else None
        ),
    )


def is_legal_matrix_input(
    *,
    operation: object,
    cardinality: object,
    object_type: object,
    dialogue_state: object,
    safety: object,
) -> bool:
    if (
        operation not in OPERATIONS
        or cardinality not in OBJECT_CARDINALITIES
        or object_type not in OBJECT_TYPES
        or dialogue_state not in DIALOGUE_STATES
        or type(safety) is not bool
    ):
        return False
    allowed_types = {
        "zero": {"none", "topic"},
        "one": {
            "candidate_ordinals",
            "current_batch",
            "current_product",
            "explicit_products",
            "image_ordinals",
            "confirmed_images",
        },
        "two_or_three": {
            "candidate_ordinals",
            "current_batch",
            "explicit_products",
            "image_ordinals",
            "confirmed_images",
        },
        "over_limit": {
            "candidate_ordinals",
            "current_batch",
            "explicit_products",
            "image_ordinals",
            "confirmed_images",
        },
        "unresolved": {
            "candidate_ordinals",
            "current_batch",
            "current_product",
            "explicit_products",
            "image_ordinals",
            "confirmed_images",
        },
    }
    return object_type in allowed_types[cardinality]


def _validate_inputs(
    *,
    operation: object,
    cardinality: object,
    object_type: object,
    dialogue_state: object,
    safety: object,
) -> None:
    if not is_legal_matrix_input(
        operation=operation,
        cardinality=cardinality,
        object_type=object_type,
        dialogue_state=dialogue_state,
        safety=safety,
    ):
        raise ValueError("invalid responsibility matrix object shape")


def decision_for_responsibility(
    responsibility: Responsibility,
    *,
    clarification_code: str | None = None,
) -> ResponsibilityDecision:
    processor, presentation_mode, preserve_order = (
        _RESPONSIBILITY_SHAPES[responsibility]
    )
    return ResponsibilityDecision(
        responsibility=responsibility,
        processor=processor,
        presentation_mode=presentation_mode,
        preserve_product_order=preserve_order,
        clarification_code=clarification_code,
    )


__all__ = [
    "DIALOGUE_STATES",
    "DialogueState",
    "OBJECT_CARDINALITIES",
    "OBJECT_TYPES",
    "OPERATIONS",
    "ObjectCardinality",
    "ObjectType",
    "Operation",
    "Responsibility",
    "ResponsibilityDecision",
    "ResponsibilityPresentationMode",
    "decision_for_responsibility",
    "is_legal_matrix_input",
    "resolve_responsibility",
]
