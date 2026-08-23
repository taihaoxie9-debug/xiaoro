from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from app.guide.application.consultation_assessment import (
    ConsultationAssessmentResult,
    assess_consultation,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)
from app.guide.understanding.consultation_questions import (
    ObservationAnswer,
    observable_questions,
)


def _consultation(
    answers: Sequence[ObservationAnswer] = ("yes", "unknown"),
) -> ConsultationSubstate:
    return ConsultationSubstate(
        observations=[
            ConsultationObservation(
                code=question.code,
                answer=answer,
                source_turn_id=f"turn_{index:016d}",
            )
            for index, (question, answer) in enumerate(
                zip(
                    observable_questions(),
                    answers,
                    strict=False,
                ),
                start=1,
            )
        ]
    )


def _assessment(
    consultation: ConsultationSubstate,
    *,
    conversation_version: int,
    escalation=None,
) -> ConsultationAssessmentResult:
    return assess_consultation(
        consultation,
        current_conversation_version=conversation_version,
        conclusion_source_turn_id="turn_assessment_000001",
        escalation=escalation,
    )


def _stage(
    answers: Sequence[ObservationAnswer] = ("yes", "unknown"),
    *,
    conversation_version: int = 17,
    escalation=None,
):
    from app.guide.application.consultation_confirmation import (
        record_provisional_conclusion,
    )

    consultation = _consultation(answers)
    assessment = _assessment(
        consultation,
        conversation_version=conversation_version,
        escalation=escalation,
    )
    before = consultation.model_dump(mode="json")
    transition = record_provisional_conclusion(
        consultation,
        current_conversation_version=conversation_version,
        assessment=assessment.confirmable_assessment,
    )
    assert consultation.model_dump(mode="json") == before
    return consultation, assessment, transition


def _safety_context(
    assessment: ConsultationAssessmentResult,
) -> dict[str, object]:
    payload = assessment.confirmable_assessment.conclusion.model_dump()
    payload.pop("confirmed_by_user")
    return payload


def test_confirmation_is_pure_transition_for_external_conversation_cas(
) -> None:
    from app.guide.application.consultation_confirmation import (
        confirm_provisional_conclusion,
    )

    consultation, assessment, pending = _stage()
    pending_state = pending.next_consultation
    before = pending_state.model_dump(mode="json")

    confirmed = confirm_provisional_conclusion(
        pending_state,
        current_conversation_version=pending.output.conversation_version,
        message="我确认是干性肤质",
        source_turn_id="turn_confirm_00000001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id="turn_assessment_000001",
    )

    assert pending_state.model_dump(mode="json") == before
    assert confirmed.expected_conversation_version == 18
    assert confirmed.output.conversation_version == 19
    assert confirmed.next_consultation.model_fields.keys() == {
        "started_at_conversation_version",
        "observations",
        "confirmable_assessment",
        "medical_escalation",
        "confirmation_source_turn_id",
    }
    output = confirmed.output
    assert output.mode == "consultation_confirmation"
    assert output.conclusion.confirmed_by_user is True
    assert output.conclusion_source_turn_id == (
        pending.output.conclusion_source_turn_id
    )
    assert output.confirmation_source_turn_id == (
        "turn_confirm_00000001"
    )
    assert output.escalation_triggers == []
    assert output.stop_skincare_advice is False
    assert output.visible_product_ids == []
    assert _safety_context(assessment) == {
        key: value
        for key, value in output.conclusion.model_dump().items()
        if key != "confirmed_by_user"
    }
    assert confirmed.next_consultation.observations == (
        consultation.observations
    )
    assert "profile" not in output.model_dump()


def test_prevalidated_confirmation_transition_accepts_no_message() -> None:
    from app.guide.application.consultation_confirmation import (
        confirm_prevalidated_conclusion,
    )

    _, _, pending = _stage()

    confirmed = confirm_prevalidated_conclusion(
        pending.next_consultation,
        current_conversation_version=pending.output.conversation_version,
        source_turn_id="turn_prevalidated_confirm_0001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id="turn_assessment_000001",
    )

    assert confirmed.output.conclusion.confirmed_by_user is True
    assert confirmed.output.confirmation_source_turn_id == (
        "turn_prevalidated_confirm_0001"
    )


def test_confirmation_uses_only_caller_authoritative_conversation_version(
) -> None:
    from app.guide.application.consultation_confirmation import (
        confirm_provisional_conclusion,
    )

    _, _, pending = _stage(conversation_version=41)

    assert pending.expected_conversation_version == 41
    assert pending.output.conversation_version == 42
    confirmed = confirm_provisional_conclusion(
        pending.next_consultation,
        current_conversation_version=73,
        message="确认",
        source_turn_id="turn_confirm_00000001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id="turn_assessment_000001",
    )
    assert confirmed.expected_conversation_version == 73
    assert confirmed.output.conversation_version == 74


def test_confirmation_accepts_explicit_natural_confirmation() -> None:
    from app.guide.application.consultation_confirmation import (
        confirm_provisional_conclusion,
    )

    _, _, pending = _stage(conversation_version=41)

    confirmed = confirm_provisional_conclusion(
        pending.next_consultation,
        current_conversation_version=42,
        message="对，确认这个判断",
        source_turn_id="turn_confirm_natural_0001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id="turn_assessment_000001",
    )

    assert confirmed.output.conclusion.confirmed_by_user is True


def test_confirmation_has_no_private_state_or_runtime_composition_authority(
) -> None:
    import app.guide.application.consultation_confirmation as confirmation

    confirmation_source = Path(confirmation.__file__).read_text(
        encoding="utf-8"
    )
    runtime_source = Path(
        "app/guide_runtime/composition.py"
    ).read_text(encoding="utf-8")

    assert "ConsultationStatePort" not in confirmation_source
    assert "ConsultationSnapshot" not in confirmation_source
    assert "expected_version" not in confirmation_source
    assert "next_snapshot" not in confirmation_source
    assert ".save(" not in confirmation_source
    assert "InMemoryConsultationState" not in runtime_source


def test_confirmation_requires_an_existing_unconfirmed_assessment() -> None:
    from app.guide.application.consultation_confirmation import (
        ConsultationConfirmationRejected,
        confirm_provisional_conclusion,
    )

    with pytest.raises(
        ConsultationConfirmationRejected,
        match="missing_provisional",
    ):
        confirm_provisional_conclusion(
            _consultation(),
            current_conversation_version=17,
            message="确认",
            source_turn_id="turn_confirm_00000001",
            expected_skin_target="dry",
            expected_conclusion_source_turn_id=(
                "turn_assessment_000001"
            ),
        )

    _, _, pending = _stage()
    confirmed = confirm_provisional_conclusion(
        pending.next_consultation,
        current_conversation_version=18,
        message="确认",
        source_turn_id="turn_confirm_00000001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id="turn_assessment_000001",
    )
    with pytest.raises(
        ConsultationConfirmationRejected,
        match="already_confirmed",
    ):
        confirm_provisional_conclusion(
            confirmed.next_consultation,
            current_conversation_version=19,
            message="确认",
            source_turn_id="turn_confirm_00000002",
            expected_skin_target="dry",
            expected_conclusion_source_turn_id=(
                "turn_assessment_000001"
            ),
        )


def test_inconclusive_assessment_cannot_be_recorded_for_confirmation() -> None:
    from app.guide.application.consultation_confirmation import (
        ConsultationConfirmationRejected,
        record_provisional_conclusion,
    )

    consultation = _consultation(("unknown",))
    assessment = _assessment(
        consultation,
        conversation_version=8,
    )
    assert (
        assessment.confirmable_assessment.conclusion.skin_target is None
    )
    before = consultation.model_dump(mode="json")

    with pytest.raises(
        ConsultationConfirmationRejected,
        match="inconclusive_provisional",
    ):
        record_provisional_conclusion(
            consultation,
            current_conversation_version=8,
            assessment=assessment.confirmable_assessment,
        )

    assert consultation.model_dump(mode="json") == before


def test_assessment_cannot_be_recorded_after_observations_change() -> None:
    from app.guide.application.consultation_confirmation import (
        ConsultationConfirmationRejected,
        record_provisional_conclusion,
    )

    original = _consultation(("yes", "unknown"))
    stale = _assessment(original, conversation_version=8)
    changed = _consultation(("yes", "unknown", "no"))

    with pytest.raises(
        ConsultationConfirmationRejected,
        match="stale_assessment",
    ):
        record_provisional_conclusion(
            changed,
            current_conversation_version=9,
            assessment=stale.confirmable_assessment,
        )


def test_assessment_requires_exact_observation_set_at_same_version() -> None:
    from app.guide.application.consultation_confirmation import (
        ConsultationConfirmationRejected,
        record_provisional_conclusion,
    )

    original = _consultation(("yes", "unknown"))
    stale = _assessment(original, conversation_version=8)
    changed = _consultation(("sometimes", "unknown"))

    with pytest.raises(
        ConsultationConfirmationRejected,
        match="stale_assessment",
    ):
        record_provisional_conclusion(
            changed,
            current_conversation_version=8,
            assessment=stale.confirmable_assessment,
        )


@pytest.mark.parametrize(
    ("message", "expected_skin_target"),
    [
        ("我确认是油性肤质", "dry"),
        ("我确认是干性肤质", "oily"),
    ],
)
def test_mismatched_confirmation_fails_closed_without_mutation(
    message: str,
    expected_skin_target: str,
) -> None:
    from app.guide.application.consultation_confirmation import (
        ConsultationConfirmationRejected,
        confirm_provisional_conclusion,
    )

    _, _, pending = _stage()
    current = pending.next_consultation
    before = current.model_dump(mode="json")

    with pytest.raises(
        ConsultationConfirmationRejected,
        match="mismatched_confirmation",
    ):
        confirm_provisional_conclusion(
            current,
            current_conversation_version=18,
            message=message,
            source_turn_id="turn_confirm_00000001",
            expected_skin_target=expected_skin_target,
            expected_conclusion_source_turn_id=(
                "turn_assessment_000001"
            ),
        )

    assert current.model_dump(mode="json") == before


def test_mismatched_conclusion_source_turn_fails_closed() -> None:
    from app.guide.application.consultation_confirmation import (
        ConsultationConfirmationRejected,
        confirm_provisional_conclusion,
    )

    _, _, pending = _stage()

    with pytest.raises(
        ConsultationConfirmationRejected,
        match="mismatched_source_turn",
    ):
        confirm_provisional_conclusion(
            pending.next_consultation,
            current_conversation_version=18,
            message="确认",
            source_turn_id="turn_confirm_00000001",
            expected_skin_target="dry",
            expected_conclusion_source_turn_id=(
                "turn_stale_assessment_01"
            ),
        )


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("也许是吧", "non_affirmative"),
        ("不确认", "non_affirmative"),
        ("好", "non_affirmative"),
        ("对，但我不确定", "ambiguous_confirmation"),
        ("确认，不过也可能不是", "ambiguous_confirmation"),
        ("确认？", "ambiguous_confirmation"),
        ("confirm?", "ambiguous_confirmation"),
    ],
)
def test_ambiguous_or_non_affirmative_input_fails_closed(
    message: str,
    reason: str,
) -> None:
    from app.guide.application.consultation_confirmation import (
        ConsultationConfirmationRejected,
        confirm_provisional_conclusion,
    )

    _, _, pending = _stage()
    current = pending.next_consultation
    before = current.model_dump(mode="json")

    with pytest.raises(ConsultationConfirmationRejected, match=reason):
        confirm_provisional_conclusion(
            current,
            current_conversation_version=18,
            message=message,
            source_turn_id="turn_confirm_00000001",
            expected_skin_target="dry",
            expected_conclusion_source_turn_id=(
                "turn_assessment_000001"
            ),
        )

    assert current.model_dump(mode="json") == before


def test_structured_escalation_is_preserved_and_stops_confirmation() -> None:
    from app.guide.application.consultation_confirmation import (
        ConsultationConfirmationRejected,
        confirm_provisional_conclusion,
        record_medical_escalation,
    )
    from app.guide.understanding.consultation_escalation import (
        ConsultationEscalationInput,
        ConsultationEscalationTrigger,
    )

    escalation = ConsultationEscalationInput(
        triggers=[
            ConsultationEscalationTrigger(
                code="pain",
                source_turn_id="turn_escalation_0001",
            )
        ]
    )
    consultation = _consultation()
    assessment = _assessment(
        consultation,
        conversation_version=17,
        escalation=escalation,
    )
    pending = record_medical_escalation(
        consultation,
        current_conversation_version=17,
        assessment=assessment.confirmable_assessment,
    )
    stored = pending.next_consultation.confirmable_assessment
    assert stored is not None
    assert stored.assessment_kind == "medical_escalation"
    assert stored.escalation_triggers == (
        assessment.confirmable_assessment.escalation_triggers
    )
    assert stored.stop_skincare_advice is True
    before = pending.next_consultation.model_dump(mode="json")

    with pytest.raises(
        ConsultationConfirmationRejected,
        match="escalation_stop",
    ):
        confirm_provisional_conclusion(
            pending.next_consultation,
            current_conversation_version=18,
            message="我确认是干性肤质",
            source_turn_id="turn_confirm_00000001",
            expected_skin_target="dry",
            expected_conclusion_source_turn_id=(
                "turn_assessment_000001"
            ),
        )

    assert pending.next_consultation.model_dump(mode="json") == before
