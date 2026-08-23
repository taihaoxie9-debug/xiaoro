from __future__ import annotations

from typing import Sequence

import pytest
from pydantic import ValidationError

from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)
from app.guide.understanding.consultation_questions import (
    ObservationAnswer,
    observable_questions,
)


def test_observable_questions_have_fixed_auditable_order() -> None:
    questions = observable_questions()

    assert tuple(question.code for question in questions) == (
        "post_cleanse_tightness",
        "t_zone_oiliness",
        "recurrent_redness",
        "stinging",
        "flaking",
    )
    assert all(question.prompt.strip() for question in questions)


def _consultation(
    answers: Sequence[ObservationAnswer],
) -> ConsultationSubstate:
    questions = observable_questions()
    return ConsultationSubstate(
        observations=[
            ConsultationObservation(
                code=question.code,
                answer=answer,
                source_turn_id=f"turn_{index:016d}",
            )
            for index, (question, answer) in enumerate(
                zip(questions, answers, strict=False),
                start=1,
            )
        ],
    )


def _assess(
    answers: Sequence[ObservationAnswer],
    *,
    escalation=None,
):
    from app.guide.application.consultation_assessment import (
        assess_consultation,
    )

    return assess_consultation(
        _consultation(answers),
        current_conversation_version=len(answers),
        conclusion_source_turn_id="turn_assessment_000001",
        escalation=escalation,
    )


@pytest.mark.parametrize(
    ("answers", "target", "evidence", "confidence"),
    [
        (
            ("yes", "no", "no", "no", "yes"),
            "dry",
            ["post_cleanse_tightness", "flaking"],
            "high",
        ),
        (
            ("no", "yes", "no", "no", "no"),
            "oily",
            ["t_zone_oiliness"],
            "medium",
        ),
        (
            ("yes", "yes", "no", "no", "no"),
            "combination",
            ["post_cleanse_tightness", "t_zone_oiliness"],
            "high",
        ),
        (
            ("no", "no", "yes", "yes", "no"),
            "sensitive",
            ["recurrent_redness", "stinging"],
            "high",
        ),
        (
            ("no", "yes", "yes", "yes", "no"),
            "oily_sensitive",
            ["t_zone_oiliness", "recurrent_redness", "stinging"],
            "high",
        ),
        (
            ("no", "no", "no", "no", "no"),
            "normal",
            ["all_observations_negative"],
            "medium",
        ),
    ],
)
def test_complete_observations_produce_stable_auditable_target(
    answers: tuple[ObservationAnswer, ...],
    target: str,
    evidence: list[str],
    confidence: str,
) -> None:
    result = _assess(answers)
    conclusion = result.confirmable_assessment.conclusion

    assert result.mode == "consultation_provisional"
    assert result.conversation_version == 5
    assert conclusion.skin_target == target
    assert conclusion.evidence == tuple(evidence)
    assert conclusion.confidence == confidence
    assert conclusion.confirmed_by_user is False
    assert result.confirmable_assessment.stop_skincare_advice is False


def test_unknown_and_unanswered_observations_are_uncertainties() -> None:
    result = _assess(("yes", "unknown"))
    conclusion = result.confirmable_assessment.conclusion

    assert conclusion.skin_target == "dry"
    assert conclusion.evidence == ("post_cleanse_tightness",)
    assert conclusion.uncertainties == (
        "t_zone_oiliness_unknown",
        "recurrent_redness_unanswered",
        "stinging_unanswered",
        "flaking_unanswered",
    )
    assert conclusion.confidence == "low"


def test_only_unknown_observation_remains_auditable_and_inconclusive() -> None:
    result = _assess(("unknown",))
    conclusion = result.confirmable_assessment.conclusion

    assert conclusion.skin_target is None
    assert conclusion.evidence == ("no_positive_observation_yet",)
    assert conclusion.confidence == "low"


def test_sometimes_is_evidence_but_cannot_produce_high_confidence() -> None:
    result = _assess(("sometimes", "no", "no", "no", "sometimes"))
    conclusion = result.confirmable_assessment.conclusion

    assert conclusion.skin_target == "dry"
    assert conclusion.evidence == (
        "post_cleanse_tightness",
        "flaking",
    )
    assert conclusion.confidence == "medium"


def test_overlapping_dryness_keeps_oily_sensitive_target_uncertain() -> None:
    result = _assess(("yes", "yes", "yes", "yes", "yes"))
    conclusion = result.confirmable_assessment.conclusion

    assert conclusion.skin_target == "oily_sensitive"
    assert conclusion.evidence == (
        "post_cleanse_tightness",
        "t_zone_oiliness",
        "recurrent_redness",
        "stinging",
        "flaking",
    )
    assert conclusion.uncertainties == (
        "dryness_signals_overlap_oily_sensitive",
    )
    assert conclusion.confidence == "medium"


def test_five_questions_do_not_invent_medical_escalation_triggers() -> None:
    result = _assess(("no", "no", "yes", "no", "no"))
    assessment = result.confirmable_assessment

    assert assessment.escalation_triggers == ()
    assert assessment.stop_skincare_advice is False
    assert assessment.conclusion.escalation.startswith("如出现")


def test_explicit_medical_red_flags_stop_skincare_advice() -> None:
    from app.guide.understanding.consultation_escalation import (
        ConsultationEscalationInput,
        ConsultationEscalationTrigger,
    )

    escalation = ConsultationEscalationInput(
        triggers=[
            ConsultationEscalationTrigger(
                code="oozing",
                source_turn_id="turn_escalation_0002",
            ),
            ConsultationEscalationTrigger(
                code="pain",
                source_turn_id="turn_escalation_0001",
            ),
        ]
    )

    result = _assess(
        ("yes", "no", "no", "no", "yes"),
        escalation=escalation,
    )
    assessment = result.confirmable_assessment

    assert [item.code for item in assessment.escalation_triggers] == [
        "pain",
        "oozing",
    ]
    assert assessment.stop_skincare_advice is True
    assert "明显疼痛" in assessment.conclusion.escalation
    assert "渗出" in assessment.conclusion.escalation
    assert assessment.conclusion.confirmed_by_user is False


def test_escalation_input_rejects_duplicate_or_untyped_triggers() -> None:
    from app.guide.understanding.consultation_escalation import (
        ConsultationEscalationInput,
    )

    duplicate = {
        "triggers": [
            {
                "code": "pain",
                "source_turn_id": "turn_escalation_0001",
            },
            {
                "code": "pain",
                "source_turn_id": "turn_escalation_0002",
            },
        ]
    }
    with pytest.raises(ValidationError, match="unique"):
        ConsultationEscalationInput.model_validate(duplicate)

    unsupported = {
        "triggers": [
            {
                "code": "recurrent_redness",
                "source_turn_id": "turn_escalation_0001",
            }
        ]
    }
    with pytest.raises(ValidationError):
        ConsultationEscalationInput.model_validate(unsupported)


def test_assessment_does_not_mutate_session_or_emit_profile_payload() -> None:
    from app.guide.application.consultation_assessment import (
        assess_consultation,
    )

    consultation = _consultation(("no", "yes", "no", "no", "no"))
    before = consultation.model_dump(mode="json")

    result = assess_consultation(
        consultation,
        current_conversation_version=31,
        conclusion_source_turn_id="turn_assessment_000001",
    )

    assert consultation.model_dump(mode="json") == before
    assert set(result.model_dump(mode="json")) == {
        "mode",
        "conversation_version",
        "confirmable_assessment",
        "visible_product_ids",
    }
    assert result.visible_product_ids == []


def test_assessment_binds_exact_observations_version_and_source_turn() -> None:
    from app.guide.application.consultation_assessment import (
        assess_consultation,
    )

    consultation = _consultation(("yes", "unknown"))
    result = assess_consultation(
        consultation,
        current_conversation_version=31,
        conclusion_source_turn_id="turn_assessment_000001",
    )

    bound = result.confirmable_assessment
    assert bound.observation_set_version == 31
    assert bound.observations == consultation.observations
    assert bound.observations is not consultation.observations
    assert bound.conclusion_source_turn_id == "turn_assessment_000001"
