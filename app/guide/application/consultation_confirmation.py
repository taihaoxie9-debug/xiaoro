from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.feedback.consultation_state import (
    ConfirmableConsultationAssessment,
    ConsultationSourceTurnId,
    ConsultationSubstate,
    RecordedMedicalEscalation,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationTrigger,
)
from app.guide.understanding.consultation_parsing import (
    is_explicit_consultation_confirmation,
)


SkinTargetValue = Literal[
    "oily_sensitive",
    "oily",
    "dry",
    "combination",
    "sensitive",
    "normal",
]
ConfirmationRejectionCode = Literal[
    "missing_provisional",
    "inconclusive_provisional",
    "already_confirmed",
    "provisional_already_recorded",
    "stale_assessment",
    "mismatched_source_turn",
    "mismatched_confirmation",
    "ambiguous_confirmation",
    "non_affirmative",
    "escalation_stop",
]

_TARGET_ALIASES: dict[SkinTargetValue, tuple[str, ...]] = {
    "oily_sensitive": ("油敏肌", "油性敏感肌", "oily_sensitive"),
    "oily": ("油性肤质", "油皮", "oily"),
    "dry": ("干性肤质", "干皮", "dry"),
    "combination": ("混合性肤质", "混合皮", "combination"),
    "sensitive": ("敏感性肤质", "敏感肌", "sensitive"),
    "normal": ("中性肤质", "中性皮", "normal"),
}
_TARGET_CONFIRMATIONS = {
    template.format(target=alias): target
    for target, aliases in _TARGET_ALIASES.items()
    for alias in aliases
    for template in (
        "确认是{target}",
        "我确认是{target}",
        "确认我是{target}",
        "我确认我是{target}",
        "是的我是{target}",
    )
}
_NEGATIVE_CONFIRMATIONS = frozenset(
    {"不确认", "我不确认", "不是", "否", "no", "否认"}
)
_AMBIGUITY_MARKERS = (
    "不确定",
    "也许",
    "可能",
    "或许",
    "还是",
    "但",
    "不过",
    "不是",
)
_AFFIRMATIVE_MARKERS = ("确认", "是的", "对", "yes", "confirm")


class ConsultationProvisionalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    mode: Literal["consultation_provisional"] = "consultation_provisional"
    conversation_version: int = Field(ge=1)
    conclusion: ProvisionalConsultationConclusion
    conclusion_source_turn_id: ConsultationSourceTurnId
    escalation_triggers: list[ConsultationEscalationTrigger] = Field(
        max_length=3,
    )
    stop_skincare_advice: bool
    visible_product_ids: list[int] = Field(
        default_factory=list,
        max_length=0,
    )


class ConsultationConfirmationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    mode: Literal["consultation_confirmation"] = "consultation_confirmation"
    conversation_version: int = Field(ge=1)
    conclusion: ProvisionalConsultationConclusion
    conclusion_source_turn_id: ConsultationSourceTurnId
    confirmation_source_turn_id: ConsultationSourceTurnId
    escalation_triggers: list[ConsultationEscalationTrigger] = Field(
        max_length=3,
    )
    stop_skincare_advice: bool
    visible_product_ids: list[int] = Field(
        default_factory=list,
        max_length=0,
    )


class ConsultationMedicalEscalationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    mode: Literal[
        "consultation_medical_escalation"
    ] = "consultation_medical_escalation"
    conversation_version: int = Field(ge=1)
    conclusion: ProvisionalConsultationConclusion
    conclusion_source_turn_id: ConsultationSourceTurnId
    escalation_triggers: list[ConsultationEscalationTrigger] = Field(
        min_length=1,
        max_length=3,
    )
    stop_skincare_advice: Literal[True] = True
    visible_product_ids: list[int] = Field(
        default_factory=list,
        max_length=0,
    )


class ConsultationProvisionalTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    expected_conversation_version: int = Field(ge=1)
    next_consultation: ConsultationSubstate
    output: ConsultationProvisionalResult


class ConsultationConfirmationTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    expected_conversation_version: int = Field(ge=1)
    next_consultation: ConsultationSubstate
    output: ConsultationConfirmationResult


class ConsultationMedicalEscalationTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    expected_conversation_version: int = Field(ge=1)
    next_consultation: ConsultationSubstate
    output: ConsultationMedicalEscalationResult


class ConsultationConfirmationRejected(RuntimeError):
    def __init__(self, code: ConfirmationRejectionCode) -> None:
        self.code = code
        super().__init__(code)


def validate_explicit_confirmation(
    message: str,
    *,
    expected_skin_target: SkinTargetValue,
) -> None:
    _require_explicit_confirmation(
        message,
        expected_target=expected_skin_target,
    )


def record_provisional_conclusion(
    consultation: ConsultationSubstate,
    *,
    current_conversation_version: int,
    assessment: ConfirmableConsultationAssessment,
) -> ConsultationProvisionalTransition:
    if consultation.medical_escalation is not None:
        raise ConsultationConfirmationRejected("escalation_stop")
    if assessment.conclusion.confirmed_by_user:
        raise ConsultationConfirmationRejected("already_confirmed")
    if assessment.assessment_kind == "medical_escalation":
        raise ConsultationConfirmationRejected("escalation_stop")
    if assessment.conclusion.skin_target is None:
        raise ConsultationConfirmationRejected(
            "inconclusive_provisional"
        )
    current_assessment = consultation.confirmable_assessment
    if current_assessment is not None:
        code: ConfirmationRejectionCode = (
            "already_confirmed"
            if current_assessment.conclusion.confirmed_by_user
            else "provisional_already_recorded"
        )
        raise ConsultationConfirmationRejected(code)
    if (
        assessment.observation_set_version
        != current_conversation_version
        or assessment.observations != consultation.observations
    ):
        raise ConsultationConfirmationRejected("stale_assessment")

    stored_assessment = assessment.model_copy(deep=True)
    replacement = ConsultationSubstate(
        started_at_conversation_version=(
            consultation.started_at_conversation_version
        ),
        observations=_copy_observations(consultation),
        confirmable_assessment=stored_assessment,
        medical_escalation=consultation.medical_escalation,
    )
    next_version = current_conversation_version + 1
    output = ConsultationProvisionalResult(
        conversation_version=next_version,
        conclusion=stored_assessment.conclusion.model_copy(deep=True),
        conclusion_source_turn_id=(
            stored_assessment.conclusion_source_turn_id
        ),
        escalation_triggers=[
            item.model_copy(deep=True)
            for item in stored_assessment.escalation_triggers
        ],
        stop_skincare_advice=(
            stored_assessment.stop_skincare_advice
        ),
    )
    return ConsultationProvisionalTransition(
        expected_conversation_version=current_conversation_version,
        next_consultation=replacement,
        output=output,
    )


def record_medical_escalation(
    consultation: ConsultationSubstate,
    *,
    current_conversation_version: int,
    assessment: ConfirmableConsultationAssessment,
) -> ConsultationMedicalEscalationTransition:
    if (
        assessment.assessment_kind != "medical_escalation"
        or not assessment.escalation_triggers
        or not assessment.stop_skincare_advice
        or assessment.conclusion.confirmed_by_user
    ):
        raise ConsultationConfirmationRejected("escalation_stop")
    if consultation.medical_escalation is not None:
        raise ConsultationConfirmationRejected("escalation_stop")
    if (
        assessment.observation_set_version
        != current_conversation_version
        or assessment.observations != consultation.observations
    ):
        raise ConsultationConfirmationRejected("stale_assessment")

    stored_assessment = assessment.model_copy(deep=True)
    next_version = current_conversation_version + 1
    recorded_escalation = RecordedMedicalEscalation(
        recorded_at_conversation_version=next_version,
        assessment=stored_assessment,
    )
    replacement = ConsultationSubstate(
        started_at_conversation_version=(
            consultation.started_at_conversation_version
        ),
        observations=_copy_observations(consultation),
        confirmable_assessment=(
            consultation.confirmable_assessment or stored_assessment
        ),
        medical_escalation=recorded_escalation,
        confirmation_source_turn_id=(
            consultation.confirmation_source_turn_id
        ),
    )
    output = ConsultationMedicalEscalationResult(
        conversation_version=next_version,
        conclusion=stored_assessment.conclusion.model_copy(deep=True),
        conclusion_source_turn_id=(
            stored_assessment.conclusion_source_turn_id
        ),
        escalation_triggers=[
            item.model_copy(deep=True)
            for item in stored_assessment.escalation_triggers
        ],
    )
    return ConsultationMedicalEscalationTransition(
        expected_conversation_version=current_conversation_version,
        next_consultation=replacement,
        output=output,
    )


def confirm_provisional_conclusion(
    consultation: ConsultationSubstate,
    *,
    current_conversation_version: int,
    message: str,
    source_turn_id: str,
    expected_skin_target: SkinTargetValue,
    expected_conclusion_source_turn_id: str,
) -> ConsultationConfirmationTransition:
    assessment = consultation.confirmable_assessment
    if assessment is None:
        raise ConsultationConfirmationRejected("missing_provisional")
    conclusion = assessment.conclusion
    if conclusion.skin_target is None:
        raise ConsultationConfirmationRejected(
            "inconclusive_provisional"
        )
    if conclusion.confirmed_by_user:
        raise ConsultationConfirmationRejected("already_confirmed")
    if (
        consultation.medical_escalation is not None
        or assessment.stop_skincare_advice
        or assessment.escalation_triggers
    ):
        raise ConsultationConfirmationRejected("escalation_stop")
    if (
        expected_conclusion_source_turn_id
        != assessment.conclusion_source_turn_id
    ):
        raise ConsultationConfirmationRejected(
            "mismatched_source_turn"
        )
    if expected_skin_target != conclusion.skin_target:
        raise ConsultationConfirmationRejected(
            "mismatched_confirmation"
        )
    validate_explicit_confirmation(
        message,
        expected_skin_target=conclusion.skin_target,
    )

    confirmed_conclusion = ProvisionalConsultationConclusion(
        **{
            **conclusion.model_dump(),
            "confirmed_by_user": True,
        }
    )
    confirmed_assessment = ConfirmableConsultationAssessment(
        assessment_kind=assessment.assessment_kind,
        observation_set_version=assessment.observation_set_version,
        observations=[
            item.model_copy(deep=True)
            for item in assessment.observations
        ],
        conclusion=confirmed_conclusion,
        conclusion_source_turn_id=(
            assessment.conclusion_source_turn_id
        ),
        escalation_triggers=[
            item.model_copy(deep=True)
            for item in assessment.escalation_triggers
        ],
        stop_skincare_advice=assessment.stop_skincare_advice,
    )
    replacement = ConsultationSubstate(
        started_at_conversation_version=(
            consultation.started_at_conversation_version
        ),
        observations=_copy_observations(consultation),
        confirmable_assessment=confirmed_assessment,
        medical_escalation=consultation.medical_escalation,
        confirmation_source_turn_id=source_turn_id,
    )
    next_version = current_conversation_version + 1
    output = ConsultationConfirmationResult(
        conversation_version=next_version,
        conclusion=confirmed_conclusion.model_copy(deep=True),
        conclusion_source_turn_id=(
            confirmed_assessment.conclusion_source_turn_id
        ),
        confirmation_source_turn_id=source_turn_id,
        escalation_triggers=[],
        stop_skincare_advice=False,
    )
    return ConsultationConfirmationTransition(
        expected_conversation_version=current_conversation_version,
        next_consultation=replacement,
        output=output,
    )


def _copy_observations(
    consultation: ConsultationSubstate,
) -> list[ConsultationObservation]:
    return [
        item.model_copy(deep=True)
        for item in consultation.observations
    ]


def _require_explicit_confirmation(
    message: str,
    *,
    expected_target: SkinTargetValue,
) -> None:
    if not isinstance(message, str):
        raise ConsultationConfirmationRejected("non_affirmative")
    if "?" in message or "？" in message:
        raise ConsultationConfirmationRejected(
            "ambiguous_confirmation"
        )
    normalized = re.sub(
        r"[\s,，。.!！:：;；]",
        "",
        message,
    ).casefold()
    if normalized in _NEGATIVE_CONFIRMATIONS:
        raise ConsultationConfirmationRejected("non_affirmative")
    has_ambiguity = any(
        marker in normalized for marker in _AMBIGUITY_MARKERS
    )
    has_affirmation = any(
        marker in normalized for marker in _AFFIRMATIVE_MARKERS
    )
    if has_ambiguity:
        code: ConfirmationRejectionCode = (
            "ambiguous_confirmation"
            if has_affirmation
            else "non_affirmative"
        )
        raise ConsultationConfirmationRejected(code)
    stated_target = _TARGET_CONFIRMATIONS.get(normalized)
    if stated_target is not None:
        if stated_target != expected_target:
            raise ConsultationConfirmationRejected(
                "mismatched_confirmation"
            )
        return
    if is_explicit_consultation_confirmation(message):
        return
    raise ConsultationConfirmationRejected("non_affirmative")
