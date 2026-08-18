from __future__ import annotations

from decimal import Decimal

import pytest

from app.guide.adapters.state import InMemoryConversationState
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.feedback.consultation_state import ConsultationSubstate


def _collector(
    state: InMemoryConversationState,
):
    from app.guide.application.consultation_collection import (
        ConsultationCollectionService,
    )

    return ConsultationCollectionService(conversation_state=state)


def _recommendation_snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="consultation-lifecycle",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
            budget_minimum=None,
            budget_maximum=Decimal("500"),
            skin=None,
            efficacy="repair",
            exclusions=[],
        ),
        candidates=[
            DisplayedCandidateRef(
                product_id=91,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=["repair"],
            )
        ],
    )


def test_explicit_entry_persists_active_state_before_first_answer() -> None:
    state = InMemoryConversationState()

    output = _collector(state).begin(
        session_id="consultation-lifecycle",
        conversation_version=0,
        skin_target=None,
    )

    stored = state.load("consultation-lifecycle")
    assert output is not None
    assert output.conversation_version == 1
    assert output.observations == []
    assert output.next_question is not None
    assert output.next_question.code == "post_cleanse_tightness"
    assert stored is not None
    assert stored.version == 1
    assert stored.consultation == ConsultationSubstate(
        started_at_conversation_version=1,
        observations=[],
    )
    assert stored.model_dump(mode="json")["consultation"][
        "observations"
    ] == []


def test_answer_requires_a_persisted_active_consultation() -> None:
    from app.guide.application.consultation_collection import (
        ConsultationNotActive,
    )

    state = InMemoryConversationState()

    with pytest.raises(ConsultationNotActive):
        _collector(state).answer(
            session_id="consultation-lifecycle",
            conversation_version=0,
            answer="yes",
            source_turn_id="turn_answer_000000001",
        )

    assert state.load("consultation-lifecycle") is None


def test_entry_preserves_existing_recommendation_in_same_snapshot() -> None:
    state = InMemoryConversationState()
    current = state.save(
        _recommendation_snapshot(),
        expected_version=0,
    )

    output = _collector(state).begin(
        session_id=current.session_id,
        conversation_version=current.version,
        skin_target=None,
    )

    stored = state.load(current.session_id)
    assert output is not None
    assert output.conversation_version == 2
    assert stored is not None
    assert stored.query_context == current.query_context
    assert stored.candidates == current.candidates
    assert stored.consultation is not None
    assert stored.consultation.started_at_conversation_version == 2
    assert stored.consultation.observations == ()


def test_repeated_entry_is_read_only_and_cannot_restart_consultation() -> None:
    state = InMemoryConversationState()
    collector = _collector(state)
    first = collector.begin(
        session_id="consultation-lifecycle",
        conversation_version=0,
        skin_target=None,
    )
    assert first is not None
    before = state.load("consultation-lifecycle")

    repeated = collector.begin(
        session_id="consultation-lifecycle",
        conversation_version=1,
        skin_target=None,
    )

    assert repeated is not None
    assert repeated.conversation_version == 1
    assert state.load("consultation-lifecycle") == before


@pytest.mark.parametrize("replacement_marker", [2, 3])
def test_active_start_marker_cannot_be_rewritten(
    replacement_marker: int,
) -> None:
    state = InMemoryConversationState()
    collector = _collector(state)
    collector.begin(
        session_id="consultation-lifecycle",
        conversation_version=0,
        skin_target=None,
    )
    current = state.load("consultation-lifecycle")
    assert current is not None
    assert current.consultation is not None
    replacement = current.model_copy(
        update={
            "version": 2,
            "consultation": current.consultation.model_copy(
                update={
                    "started_at_conversation_version": replacement_marker
                }
            ),
        },
        deep=True,
    )

    with pytest.raises(ValueError, match="start marker is immutable"):
        state.save(replacement, expected_version=1)

    assert state.load("consultation-lifecycle") == current
