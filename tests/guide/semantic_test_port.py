from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.guide.feedback.consultation_state import (
    ConfirmableConsultationAssessment,
    ConsultationSubstate,
)
from app.guide.understanding.contracts import CategoryDraft, TopicCode
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationInput,
)
from app.guide.understanding.exact_parsing import parse_exact_constraints
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


class ExactEchoSemanticPort:
    """Offline semantic test double for exact-topic integration fixtures."""

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del context
        constraints, _ = parse_exact_constraints(message)
        topics = list(
            dict.fromkeys(
                item.value
                for item in constraints
                if isinstance(item, CategoryDraft)
            )
        )
        topic: TopicCode | None = topics[0] if len(topics) == 1 else None
        goal = (
            SemanticGoal.RECOMMENDATION
            if topic is not None
            else SemanticGoal.CLARIFICATION
        )
        return SemanticIntentProposal(
            goal=goal,
            topic=topic,
            concerns=(),
            observations=(),
            references=(),
            confidence=0.99,
            clarification_hint=None,
        )


class TypedExactEchoUnderstanding:
    """Offline frozen TurnMeaning provider for production-path tests."""

    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> TurnMeaning:
        constraints, _ = parse_exact_constraints(message)
        topics = list(
            dict.fromkeys(
                item.value
                for item in constraints
                if isinstance(item, CategoryDraft)
            )
        )
        topic = topics[0] if len(topics) == 1 else None
        recommendation = topic is not None
        return TurnMeaning(
            operation_hint=(
                "recommendation"
                if recommendation
                else "clarification"
            ),
            recommendation_mode=(
                "explore" if recommendation else None
            ),
            recommendation_count=None,
            recommendation_mode_basis=(
                {
                    "basis": "broad_exploration",
                    "source_text": message,
                }
                if recommendation
                else None
            ),
            topic_hint=topic.value if topic is not None else None,
            continuity_hint=(
                "new_task"
                if context.conversation_version == 0
                else "unknown"
            ),
            subject_scope_hint="self",
            reference_mentions=(),
            product_mentions=(),
            budget_candidates=(),
            observation_candidates=(),
            preference_candidates=(),
            relative_candidates=(),
            consultation_hypothesis=None,
            next_observation_gap=None,
            question_meaning=message,
            safety_language="ordinary",
        )


def exact_echo_understanding() -> TypedExactEchoUnderstanding:
    return TypedExactEchoUnderstanding()


_CONSULTATION_OBSERVATION_FIELDS = (
    (
        "tightness",
        "whole_face",
        "post_cleanse",
        "current",
        "洗脸后紧绷",
    ),
    (
        "oiliness",
        "t_zone",
        "unknown",
        "current",
        "T区出油",
    ),
    (
        "redness",
        "whole_face",
        "unknown",
        "recurrent",
        "反复泛红",
    ),
    (
        "stinging",
        "whole_face",
        "unknown",
        "current",
        "刺痛",
    ),
    (
        "flaking",
        "whole_face",
        "unknown",
        "current",
        "起皮",
    ),
)
_CONSULTATION_STATE_BY_ANSWER = {
    "yes": "present",
    "no": "absent",
    "sometimes": "sometimes",
    "unknown": "unknown",
}


@dataclass(frozen=True)
class AssessmentFixture:
    confirmable_assessment: ConfirmableConsultationAssessment


def consultation_from_answers(
    answers: Sequence[str] = ("yes", "unknown"),
) -> ConsultationSubstate:
    observations = tuple(
        ConsultationObservation(
            observation_id=f"obs_fixture_{index}",
            dimension=dimension,
            state=_CONSULTATION_STATE_BY_ANSWER[answer],
            location=location,
            trigger=trigger,
            duration=duration,
            severity="unknown",
            source_text=source_text,
            source_turn_id=f"turn_{index:016d}",
        )
        for index, (
            answer,
            (
                dimension,
                location,
                trigger,
                duration,
                source_text,
            ),
        ) in enumerate(
            zip(
                answers,
                _CONSULTATION_OBSERVATION_FIELDS,
                strict=False,
            ),
            start=1,
        )
    )
    return ConsultationSubstate(observations=observations)


def consultation_assessment_fixture(
    consultation: ConsultationSubstate,
    *,
    conversation_version: int,
    conclusion_source_turn_id: str = "turn_assessment_000001",
    escalation: ConsultationEscalationInput | None = None,
) -> AssessmentFixture:
    positive = {
        item.dimension
        for item in consultation.observations
        if item.state in {"present", "sometimes"}
    }
    dry = bool(positive & {"tightness", "flaking", "dryness"})
    oily = "oiliness" in positive
    sensitive = bool(positive & {"redness", "stinging"})
    if oily and sensitive:
        skin_target = "oily_sensitive"
    elif oily and dry:
        skin_target = "combination"
    elif sensitive:
        skin_target = "sensitive"
    elif oily:
        skin_target = "oily"
    elif dry:
        skin_target = "dry"
    elif (
        len(consultation.observations)
        == len(_CONSULTATION_OBSERVATION_FIELDS)
        and all(
            item.state == "absent"
            for item in consultation.observations
        )
    ):
        skin_target = "normal"
    else:
        skin_target = None
    evidence = tuple(
        item.source_text
        for item in consultation.observations
        if item.state in {"present", "sometimes"}
    ) or (
        (
            "all_observations_negative"
            if skin_target == "normal"
            else "no_positive_observation_yet"
        ),
    )
    triggers = tuple(escalation.triggers) if escalation is not None else ()
    assessment = ConfirmableConsultationAssessment(
        assessment_kind=(
            "medical_escalation" if triggers else "provisional"
        ),
        observation_set_version=conversation_version,
        observations=consultation.observations,
        conclusion=ProvisionalConsultationConclusion(
            skin_target=skin_target,
            confidence="medium" if skin_target is not None else "low",
            evidence=evidence,
            uncertainties=(),
            escalation=(
                "已记录明显风险，请停止护肤建议并及时就医。"
                if triggers
                else "如症状持续或加重，请及时就医。"
            ),
            confirmed_by_user=False,
        ),
        conclusion_source_turn_id=conclusion_source_turn_id,
        escalation_triggers=triggers,
        stop_skincare_advice=bool(triggers),
    )
    return AssessmentFixture(confirmable_assessment=assessment)
