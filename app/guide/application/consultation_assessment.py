from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.feedback.consultation_state import (
    ConfirmableConsultationAssessment,
    ConsultationSubstate,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationInput,
    ConsultationEscalationTrigger,
)
from app.guide.understanding.consultation_questions import (
    observable_questions,
)


SkinTargetValue = Literal[
    "oily_sensitive",
    "oily",
    "dry",
    "combination",
    "sensitive",
    "normal",
]

_DRY_CODES = frozenset({"post_cleanse_tightness", "flaking"})
_SENSITIVE_CODES = frozenset({"recurrent_redness", "stinging"})
_POSITIVE_ANSWERS = frozenset({"yes", "sometimes"})
_ESCALATION_ORDER = {
    "persistent_swelling": 0,
    "persistent_burning": 1,
    "pain": 2,
    "broken_skin": 3,
    "oozing": 4,
}
_ESCALATION_LABELS = {
    "persistent_swelling": "持续红肿",
    "persistent_burning": "持续灼痛",
    "pain": "明显疼痛",
    "broken_skin": "破皮",
    "oozing": "渗出",
}
_DEFAULT_ESCALATION = (
    "如出现持续红肿、明显疼痛、渗出或症状快速加重，"
    "请停止尝试新护肤品并及时就医。"
)


class ConsultationAssessmentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    mode: Literal["consultation_provisional"] = "consultation_provisional"
    conversation_version: int = Field(ge=1)
    confirmable_assessment: ConfirmableConsultationAssessment
    visible_product_ids: list[int] = Field(
        default_factory=list,
        max_length=0,
    )


def assess_consultation(
    consultation: ConsultationSubstate,
    *,
    current_conversation_version: int,
    conclusion_source_turn_id: str,
    escalation: ConsultationEscalationInput | None = None,
) -> ConsultationAssessmentResult:
    observations = [
        item.model_copy(deep=True)
        for item in consultation.observations
    ]
    evidence = _evidence_codes(observations)
    target = _skin_target(
        observations,
        evidence=evidence,
    )
    if not evidence:
        evidence = [
            "all_observations_negative"
            if target == "normal"
            else "no_positive_observation_yet"
        ]
    uncertainties = _uncertainties(
        observations,
        target=target,
        evidence=evidence,
    )
    triggers = _ordered_triggers(escalation)
    return ConsultationAssessmentResult(
        conversation_version=current_conversation_version,
        confirmable_assessment=ConfirmableConsultationAssessment(
            assessment_kind=(
                "medical_escalation"
                if triggers
                else "provisional"
            ),
            observation_set_version=current_conversation_version,
            observations=observations,
            conclusion=ProvisionalConsultationConclusion(
                skin_target=target,
                confidence=_confidence(
                    observations,
                    target=target,
                    evidence=evidence,
                    uncertainties=uncertainties,
                ),
                evidence=evidence,
                uncertainties=uncertainties,
                escalation=_escalation_copy(triggers),
                confirmed_by_user=False,
            ),
            conclusion_source_turn_id=conclusion_source_turn_id,
            escalation_triggers=triggers,
            stop_skincare_advice=bool(triggers),
        ),
    )


def _evidence_codes(
    observations: Sequence[ConsultationObservation],
) -> list[str]:
    return [
        observation.code
        for observation in observations
        if observation.answer in _POSITIVE_ANSWERS
    ]


def _skin_target(
    observations: Sequence[ConsultationObservation],
    *,
    evidence: Sequence[str],
) -> SkinTargetValue | None:
    evidence_codes = set(evidence)
    has_dryness = bool(evidence_codes & _DRY_CODES)
    has_oiliness = "t_zone_oiliness" in evidence_codes
    has_sensitivity = bool(evidence_codes & _SENSITIVE_CODES)

    if has_oiliness and has_sensitivity:
        return "oily_sensitive"
    if has_oiliness and has_dryness:
        return "combination"
    if has_sensitivity:
        return "sensitive"
    if has_oiliness:
        return "oily"
    if has_dryness:
        return "dry"
    if len(observations) == len(observable_questions()) and all(
        observation.answer == "no" for observation in observations
    ):
        return "normal"
    return None


def _uncertainties(
    observations: Sequence[ConsultationObservation],
    *,
    target: SkinTargetValue | None,
    evidence: Sequence[str],
) -> list[str]:
    answers = {
        observation.code: observation.answer
        for observation in observations
    }
    uncertainties = []
    for question in observable_questions():
        answer = answers.get(question.code)
        if answer is None:
            uncertainties.append(f"{question.code}_unanswered")
        elif answer == "unknown":
            uncertainties.append(f"{question.code}_unknown")

    if target == "oily_sensitive" and set(evidence) & _DRY_CODES:
        uncertainties.append(
            "dryness_signals_overlap_oily_sensitive"
        )
    return uncertainties


def _confidence(
    observations: Sequence[ConsultationObservation],
    *,
    target: SkinTargetValue | None,
    evidence: Sequence[str],
    uncertainties: Sequence[str],
) -> Literal["low", "medium", "high"]:
    if any(
        item.endswith(("_unknown", "_unanswered"))
        for item in uncertainties
    ):
        return "low"
    if target is None:
        return "low"
    if target == "normal":
        return "medium"
    if any(
        observation.answer == "sometimes"
        for observation in observations
        if observation.code in evidence
    ):
        return "medium"
    if uncertainties:
        return "medium"
    return "high" if len(evidence) >= 2 else "medium"


def _ordered_triggers(
    escalation: ConsultationEscalationInput | None,
) -> list[ConsultationEscalationTrigger]:
    if escalation is None:
        return []
    return sorted(
        escalation.triggers,
        key=lambda trigger: _ESCALATION_ORDER[trigger.code],
    )


def _escalation_copy(
    triggers: Sequence[ConsultationEscalationTrigger],
) -> str:
    if not triggers:
        return _DEFAULT_ESCALATION
    labels = "、".join(_ESCALATION_LABELS[item.code] for item in triggers)
    return f"已记录{labels}，请停止护肤建议并及时就医。"
