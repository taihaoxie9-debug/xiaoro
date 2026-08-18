from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.guide.adapters.state import InMemoryConversationState
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.ports import ConversationStateConflict
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)


class CountingConversationState:
    def __init__(self) -> None:
        self._state = InMemoryConversationState()
        self.load_calls = 0
        self.save_calls = 0

    def load(self, session_id: str) -> ConversationSnapshot | None:
        self.load_calls += 1
        return self._state.load(session_id)

    def save(
        self,
        snapshot: ConversationSnapshot,
        *,
        expected_version: int,
    ) -> ConversationSnapshot:
        self.save_calls += 1
        return self._state.save(
            snapshot,
            expected_version=expected_version,
        )


def _collector():
    from app.guide.application.consultation_collection import (
        ConsultationCollectionService,
    )

    state = CountingConversationState()
    return (
        ConsultationCollectionService(conversation_state=state),
        state,
    )


def _profile_owner(subject_id: str) -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope="authenticated_user",
        subject_id=subject_id,
    )


def _recommendation_snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="consultation-session",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
            budget_minimum=None,
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair",
            exclusions=[],
        ),
        candidates=[
            DisplayedCandidateRef(
                product_id=91,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=["修护"],
            )
        ],
    )


def _consultation_phase_snapshots(
) -> tuple[
    ConversationSnapshot,
    ConversationSnapshot,
    ConversationSnapshot,
    ConversationSnapshot,
]:
    from app.guide.application.consultation_assessment import (
        assess_consultation,
    )
    from app.guide.application.consultation_confirmation import (
        confirm_provisional_conclusion,
        record_provisional_conclusion,
    )

    collecting = ConsultationSubstate(
        started_at_conversation_version=1,
        observations=(
            ConsultationObservation(
                code="post_cleanse_tightness",
                answer="yes",
                source_turn_id="turn_collect_00000001",
            ),
        ),
    )
    assessment = assess_consultation(
        collecting,
        current_conversation_version=2,
        conclusion_source_turn_id="turn_assessment_000001",
    )
    provisional = record_provisional_conclusion(
        collecting,
        current_conversation_version=2,
        assessment=assessment.confirmable_assessment,
    )
    confirmed = confirm_provisional_conclusion(
        provisional.next_consultation,
        current_conversation_version=3,
        message="我确认是干性肤质",
        source_turn_id="turn_confirm_00000001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id="turn_assessment_000001",
    )
    return (
        ConversationSnapshot(
            session_id="consultation-session",
            version=1,
            consultation=ConsultationSubstate(
                started_at_conversation_version=1,
                observations=[],
            ),
        ),
        ConversationSnapshot(
            session_id="consultation-session",
            version=2,
            consultation=collecting,
        ),
        ConversationSnapshot(
            session_id="consultation-session",
            version=3,
            consultation=provisional.next_consultation,
        ),
        ConversationSnapshot(
            session_id="consultation-session",
            version=4,
            consultation=confirmed.next_consultation,
        ),
    )


def _save_snapshot_history(
    state: CountingConversationState,
    *snapshots: ConversationSnapshot,
) -> ConversationSnapshot:
    saved = None
    for expected_version, snapshot in enumerate(snapshots):
        saved = state.save(
            snapshot,
            expected_version=expected_version,
        )
    assert saved is not None
    return saved


def test_unknown_skin_starts_consultation_collection_with_first_question(
) -> None:
    collector, state = _collector()

    result = collector.begin(
        session_id="consultation-session",
        conversation_version=0,
        skin_target=None,
    )

    assert result is not None
    assert result.mode == "consultation_collection"
    assert result.conversation_version == 1
    assert result.observations == []
    assert result.next_question is not None
    assert result.next_question.code == "post_cleanse_tightness"
    assert result.visible_product_ids == []
    assert state.load_calls == 1
    assert state.save_calls == 1


def test_observable_questions_have_fixed_auditable_order() -> None:
    from app.guide.understanding.consultation_questions import (
        observable_questions,
    )

    questions = observable_questions()

    assert tuple(question.code for question in questions) == (
        "post_cleanse_tightness",
        "t_zone_oiliness",
        "recurrent_redness",
        "stinging",
        "flaking",
    )
    assert all(question.prompt.strip() for question in questions)


@pytest.mark.parametrize(
    "answer",
    ["yes", "no", "sometimes", "unknown"],
)
def test_legal_answer_records_source_turn_and_returns_next_question(
    answer: str,
) -> None:
    collector, state = _collector()
    entered = collector.begin(
        session_id="consultation-session",
        conversation_version=0,
        skin_target=None,
    )
    assert entered is not None

    result = collector.answer(
        session_id="consultation-session",
        conversation_version=entered.conversation_version,
        answer=answer,
        source_turn_id="turn_0123456789abcdef",
    )

    snapshot = state.load("consultation-session")
    assert snapshot is not None
    assert snapshot.consultation is not None
    assert snapshot.query_context is None
    assert snapshot.candidates == ()
    assert snapshot.consultation.observations[0].answer == answer
    assert snapshot.consultation.observations[0].source_turn_id == (
        "turn_0123456789abcdef"
    )
    assert result.mode == "consultation_collection"
    assert result.conversation_version == 2
    assert result.visible_product_ids == []
    assert result.next_question is not None
    assert result.next_question.code == "t_zone_oiliness"
    assert state.save_calls == 2


def test_consultation_first_binds_trusted_owner_on_initial_snapshot() -> None:
    collector, state = _collector()
    owner = _profile_owner("profile_consultation_0001")

    entered = collector.begin(
        session_id="consultation-session",
        conversation_version=0,
        skin_target=None,
        profile_owner=owner,
    )
    assert entered is not None
    collector.answer(
        session_id="consultation-session",
        conversation_version=entered.conversation_version,
        answer="yes",
        source_turn_id="turn_0123456789abcdef",
        profile_owner=owner,
    )

    stored = state.load("consultation-session")
    assert stored is not None
    assert stored.profile_owner == owner


@pytest.mark.parametrize(
    "first_owner",
    [None, _profile_owner("profile_consultation_0001")],
    ids=["ownerless-cannot-be-claimed", "owner-mismatch"],
)
def test_consultation_owner_change_fails_closed_without_owner_leak(
    first_owner: ProfileOwnerRef | None,
) -> None:
    collector, state = _collector()
    requested_owner = _profile_owner("profile_consultation_0002")
    entered = collector.begin(
        session_id="consultation-session",
        conversation_version=0,
        skin_target=None,
        profile_owner=first_owner,
    )
    assert entered is not None
    collector.answer(
        session_id="consultation-session",
        conversation_version=entered.conversation_version,
        answer="yes",
        source_turn_id="turn_0123456789abcdef",
        profile_owner=first_owner,
    )
    before = state.load("consultation-session")

    with pytest.raises(ConversationStateConflict) as captured:
        collector.answer(
            session_id="consultation-session",
            conversation_version=2,
            answer="no",
            source_turn_id="turn_0000000000000002",
            profile_owner=requested_owner,
        )

    assert state.load("consultation-session") == before
    assert requested_owner.subject_id not in str(captured.value)
    if first_owner is not None:
        assert first_owner.subject_id not in str(captured.value)


def test_consultation_begin_owner_mismatch_reveals_no_observations() -> None:
    collector, state = _collector()
    owner = _profile_owner("profile_consultation_0001")
    other = _profile_owner("profile_consultation_0002")
    entered = collector.begin(
        session_id="consultation-session",
        conversation_version=0,
        skin_target=None,
        profile_owner=owner,
    )
    assert entered is not None
    collector.answer(
        session_id="consultation-session",
        conversation_version=entered.conversation_version,
        answer="yes",
        source_turn_id="turn_0123456789abcdef",
        profile_owner=owner,
    )
    before = state.load("consultation-session")

    with pytest.raises(ConversationStateConflict) as captured:
        collector.begin(
            session_id="consultation-session",
            conversation_version=2,
            skin_target=None,
            profile_owner=other,
        )

    assert state.load("consultation-session") == before
    assert owner.subject_id not in str(captured.value)
    assert other.subject_id not in str(captured.value)


def test_each_successful_answer_increments_conversation_version() -> None:
    collector, state = _collector()
    entered = collector.begin(
        session_id="consultation-session",
        conversation_version=0,
        skin_target=None,
    )
    assert entered is not None

    first = collector.answer(
        session_id="consultation-session",
        conversation_version=entered.conversation_version,
        answer="sometimes",
        source_turn_id="turn_0000000000000001",
    )
    second = collector.answer(
        session_id="consultation-session",
        conversation_version=first.conversation_version,
        answer="yes",
        source_turn_id="turn_0000000000000002",
    )

    assert first.conversation_version == 2
    assert second.conversation_version == 3
    assert second.next_question is not None
    assert second.next_question.code == "recurrent_redness"
    snapshot = state.load("consultation-session")
    assert snapshot is not None
    assert snapshot.version == 3
    assert snapshot.consultation is not None
    assert len(snapshot.consultation.observations) == 2
    assert state.save_calls == 3


def test_stale_answer_conflicts_without_overwriting_observations() -> None:
    collector, state = _collector()
    entered = collector.begin(
        session_id="consultation-session",
        conversation_version=0,
        skin_target=None,
    )
    assert entered is not None
    collector.answer(
        session_id="consultation-session",
        conversation_version=entered.conversation_version,
        answer="no",
        source_turn_id="turn_0000000000000001",
    )
    before = state.load("consultation-session")
    save_calls_before = state.save_calls

    with pytest.raises(ConversationStateConflict):
        collector.answer(
            session_id="consultation-session",
            conversation_version=entered.conversation_version,
            answer="yes",
            source_turn_id="turn_0000000000000002",
        )

    assert state.load("consultation-session") == before
    assert state.save_calls == save_calls_before


def test_provisional_assessment_rejects_further_collection_without_save(
) -> None:
    from app.guide.application.consultation_collection import (
        ConsultationCollectionComplete,
    )

    collector, state = _collector()
    active, collecting, provisional, _ = _consultation_phase_snapshots()
    before = _save_snapshot_history(
        state,
        active,
        collecting,
        provisional,
    )
    assert before.consultation is not None
    assessment_before = before.consultation.confirmable_assessment
    save_calls_before = state.save_calls

    with pytest.raises(ConsultationCollectionComplete):
        collector.answer(
            session_id=before.session_id,
            conversation_version=before.version,
            answer="yes",
            source_turn_id="turn_collect_00000003",
        )

    after = state.load(before.session_id)
    assert after == before
    assert after is not None
    assert after.version == before.version
    assert after.consultation is not None
    assert after.consultation.confirmable_assessment == assessment_before
    assert after.consultation.confirmation_source_turn_id is None
    assert state.save_calls == save_calls_before


def test_confirmed_consultation_rejects_further_collection_without_save(
) -> None:
    from app.guide.application.consultation_collection import (
        ConsultationCollectionComplete,
    )

    collector, state = _collector()
    snapshots = _consultation_phase_snapshots()
    before = _save_snapshot_history(state, *snapshots)
    assert before.consultation is not None
    assessment_before = before.consultation.confirmable_assessment
    confirmation_turn_before = (
        before.consultation.confirmation_source_turn_id
    )
    save_calls_before = state.save_calls

    with pytest.raises(ConsultationCollectionComplete):
        collector.answer(
            session_id=before.session_id,
            conversation_version=before.version,
            answer="yes",
            source_turn_id="turn_collect_00000003",
        )

    after = state.load(before.session_id)
    assert after == before
    assert after is not None
    assert after.version == before.version
    assert after.consultation is not None
    assert after.consultation.confirmable_assessment == assessment_before
    assert (
        after.consultation.confirmation_source_turn_id
        == confirmation_turn_before
    )
    assert state.save_calls == save_calls_before


@pytest.mark.parametrize("phase_index", [2, 3], ids=["provisional", "confirmed"])
def test_begin_reports_assessed_collection_complete_without_save(
    phase_index: int,
) -> None:
    collector, state = _collector()
    snapshots = _consultation_phase_snapshots()
    before = _save_snapshot_history(
        state,
        *snapshots[: phase_index + 1],
    )
    save_calls_before = state.save_calls

    result = collector.begin(
        session_id=before.session_id,
        conversation_version=before.version,
        skin_target=None,
    )

    assert result is not None
    assert result.conversation_version == before.version
    assert result.observations == list(
        before.consultation.observations
    )
    assert result.next_question is None
    assert state.load(before.session_id) == before
    assert state.save_calls == save_calls_before


def test_existing_recommendation_enters_consultation_without_state_loss(
) -> None:
    collector, state = _collector()
    existing = state.save(
        _recommendation_snapshot(),
        expected_version=0,
    )

    begun = collector.begin(
        session_id=existing.session_id,
        conversation_version=existing.version,
        skin_target=None,
    )
    assert begun is not None
    answered = collector.answer(
        session_id=existing.session_id,
        conversation_version=begun.conversation_version,
        answer="sometimes",
        source_turn_id="turn_0000000000000001",
    )

    stored = state.load(existing.session_id)
    assert begun is not None
    assert begun.visible_product_ids == []
    assert answered.visible_product_ids == []
    assert stored is not None
    assert stored.version == existing.version + 2
    assert stored.query_context == existing.query_context
    assert stored.candidates == existing.candidates
    assert stored.consultation is not None
    assert len(stored.consultation.observations) == 1
    assert state.save_calls == 3


def test_collection_has_no_second_consultation_state_authority() -> None:
    from app.guide.application import consultation_collection

    source = Path(consultation_collection.__file__).read_text(
        encoding="utf-8"
    )

    assert "ConversationStatePort" in source
    assert "ConsultationStatePort" not in source
    assert "ConsultationSnapshot" not in source
    assert "InMemoryConsultationState" not in source
