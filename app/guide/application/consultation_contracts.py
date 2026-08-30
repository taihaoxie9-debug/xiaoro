from __future__ import annotations

from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.feedback.profile_policy import (
    ProfilePersistencePlan,
    ProfilePersistenceRetry,
)
from app.guide.feedback.session_profile import SessionProfile
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationTrigger,
)
from app.guide.understanding.consultation_questions import (
    ConsultationQuestion,
)


ConsultationApplicationIntent = Literal[
    "consultation_entry",
    "consultation_answer",
    "consultation_clarification",
    "consultation_provisional",
    "consultation_confirmation",
    "consultation_rejection",
    "consultation_medical_escalation",
]
ConsultationApplicationReason = Literal[
    "answer_required",
    "confirmation_required",
    "rejected_by_user",
]


class ConsultationApplicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    intent: ConsultationApplicationIntent
    conversation_version: int = Field(ge=1)
    observations: tuple[ConsultationObservation, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    next_question: ConsultationQuestion | None = None
    conclusion: ProvisionalConsultationConclusion | None = None
    escalation_triggers: tuple[
        ConsultationEscalationTrigger,
        ...,
    ] = Field(
        default_factory=tuple,
        max_length=3,
    )
    stop_skincare_advice: bool = False
    reason: ConsultationApplicationReason | None = None
    session_profile: SessionProfile | None = None
    profile_persistence: (
        ProfilePersistencePlan | ProfilePersistenceRetry | None
    ) = None
    card_display_contract: CardDisplayContract

    @field_validator(
        "observations",
        "escalation_triggers",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_output_shape(self) -> Self:
        cards = self.card_display_contract
        if (
            cards.mode != "none"
            or cards.visible_product_ids
            or cards.max_cards != 0
            or cards.reason is not None
        ):
            raise ValueError("consultation outputs must be zero-card")
        if self.intent in {
            "consultation_provisional",
            "consultation_confirmation",
            "consultation_medical_escalation",
        }:
            if self.conclusion is None:
                raise ValueError(
                    "assessment outputs require a conclusion"
                )
        elif self.conclusion is not None:
            raise ValueError(
                "non-assessment outputs cannot carry a conclusion"
            )
        if self.intent == "consultation_confirmation":
            if (
                not self.conclusion.confirmed_by_user
                or self.session_profile is None
            ):
                raise ValueError(
                    "confirmation output requires a session profile"
                )
        elif (
            self.session_profile is not None
            or self.profile_persistence is not None
        ):
            raise ValueError(
                "only confirmation output carries profile state"
            )
        if self.intent == "consultation_medical_escalation":
            if (
                not self.escalation_triggers
                or not self.stop_skincare_advice
                or self.conclusion.confirmed_by_user
            ):
                raise ValueError(
                    "medical escalation output must be terminal"
                )
        if (self.intent in {
            "consultation_clarification",
            "consultation_rejection",
        }) != (self.reason is not None):
            raise ValueError(
                "clarification and rejection outputs require a reason"
            )
        return self


__all__ = [
    "ConsultationApplicationIntent",
    "ConsultationApplicationReason",
    "ConsultationApplicationResult",
]
