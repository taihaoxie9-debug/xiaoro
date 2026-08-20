from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.guide.adapters.state import (
    InMemoryConversationState,
    InMemorySessionLocks,
)
from app.guide.adapters.state.sqlite_profile_state import (
    SqliteProfileState,
)
from app.guide.application.contracts import UserTurn
from app.guide.application.consultation_coordinator import (
    ConsultationApplicationCoordinator,
)
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.feedback.ports import ConversationStateConflict
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


_OWNER = ProfileOwnerRef(
    scope="anonymous_browser",
    subject_id="profile_consultation_flow_0123456789",
)


def _flow(tmp_path: Path):
    from app.guide.application.consultation_chat_flow import (
        ConsultationChatFlow,
    )

    conversation_state = InMemoryConversationState()
    state_root = tmp_path / "state"
    profile_state = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=profile_state,
    )
    return (
        ConsultationChatFlow(
            coordinator=coordinator,
            conversation_state=conversation_state,
            session_locks=InMemorySessionLocks(),
            clock=lambda: datetime(2026, 8, 9, 10, 0, tzinfo=UTC),
        ),
        conversation_state,
        profile_state,
    )


def _turn(
    message: str,
    *,
    version: int,
    session_id: str = "consultation-chat-flow",
) -> UserTurn:
    return UserTurn(
        session_id=session_id,
        message=message,
        profile_owner=_OWNER,
        conversation_version=version,
    )


def _events(flow, message: str, *, version: int):
    return list(flow.stream(_turn(message, version=version)))


def _dynamic_meaning() -> TurnMeaning:
    return TurnMeaning.model_validate(
        {
            "operation_hint": "assessment",
            "topic_hint": "skincare",
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [
                {
                    "observation_id": "obs_oil",
                    "code": "oiliness",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "一会油",
                    "location": None,
                    "trigger": None,
                    "duration": None,
                    "severity": None,
                },
                {
                    "observation_id": "obs_dry",
                    "code": "dryness",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "一会干",
                    "location": None,
                    "trigger": None,
                    "duration": None,
                    "severity": None,
                },
                {
                    "observation_id": "obs_red",
                    "code": "redness",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "换季还红",
                    "location": None,
                    "trigger": "seasonal",
                    "duration": None,
                    "severity": None,
                },
            ],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": {
                "base_skin_direction": "combination",
                "stable_tendencies": ["seasonal_redness"],
                "current_conditions": ["redness"],
                "supporting_observation_ids": [
                    "obs_oil",
                    "obs_dry",
                    "obs_red",
                ],
            },
            "next_observation_gap": "location",
            "question_meaning": "动态轻问诊",
            "safety_language": "ordinary",
        },
        strict=True,
    )


def _names(events) -> list[str]:
    return [event.event for event in events]


def test_has_authority_requires_real_snapshot_owner_and_version(
    tmp_path: Path,
) -> None:
    flow, state, _ = _flow(tmp_path)
    state.save(
        ConversationSnapshot(
            session_id="owned-guide-session",
            version=1,
            profile_owner=_OWNER,
            query_context=RecommendationQueryContext(
                category="sunscreen",
                budget_minimum=None,
                budget_maximum=Decimal("500"),
                skin=None,
                efficacy=None,
                exclusions=(),
            ),
            candidates=(
                DisplayedCandidateRef(
                    product_id=53,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
        ),
        expected_version=0,
    )

    assert flow.has_authority(
        _turn(
            "它怎么样",
            version=1,
            session_id="owned-guide-session",
        )
    )
    assert not flow.has_authority(
        _turn("它怎么样", version=0, session_id="missing-guide-session")
    )
    with pytest.raises(ConversationStateConflict):
        flow.has_authority(
            _turn(
                "它怎么样",
                version=0,
                session_id="owned-guide-session",
            )
        )


def test_entry_emits_typed_question_and_zero_card_contract(
    tmp_path: Path,
) -> None:
    flow, _, profile_state = _flow(tmp_path)

    events = _events(
        flow,
        "我不知道自己是什么肤质",
        version=0,
    )

    assert _names(events) == [
        "start",
        "stage",
        "intent",
        "consultation_observation",
        "answer_contract",
        "card_display_contract",
        "presentation_contract",
        "message",
        "end",
    ]
    observation = events[3].data
    assert observation.conversation_version == 1
    assert observation.observations == []
    assert observation.next_question is not None
    assert observation.next_question.code == "post_cleanse_tightness"
    assert events[4].data.product_count == 0
    assert events[5].data.model_dump(mode="json") == {
        "mode": "none",
        "visible_product_ids": [],
        "max_cards": 0,
        "reason": None,
    }
    assert events[-1].data.conversation_version == 1
    assert profile_state.load(_OWNER) is None


def test_dynamic_meaning_persists_all_observations_in_one_turn(
    tmp_path: Path,
) -> None:
    flow, conversation_state, profile_state = _flow(tmp_path)
    turn = _turn(
        "一会油一会干，换季还红",
        version=0,
    )

    events = list(
        flow.stream_meaning(
            turn,
            meaning=_dynamic_meaning(),
        )
    )

    assert _names(events) == [
        "start",
        "stage",
        "intent",
        "consultation_observation",
        "answer_contract",
        "card_display_contract",
        "presentation_contract",
        "message",
        "end",
    ]
    assert events[2].data.mode == "consultation_answer"
    observation = events[3].data
    assert observation.conversation_version == 1
    assert [
        item.dimension for item in observation.observations
    ] == ["oiliness", "dryness", "redness"]
    assert observation.next_question is not None
    assert observation.next_question.code == "location"
    stored = conversation_state.load("consultation-chat-flow")
    assert stored is not None
    assert stored.version == 1
    assert stored.consultation is not None
    assert stored.consultation.observations == tuple(
        observation.observations
    )
    assert profile_state.load(_OWNER) is None


def test_has_dynamic_session_detects_source_bound_observations(
    tmp_path: Path,
) -> None:
    flow, _, _ = _flow(tmp_path)
    turn = _turn(
        "一会油一会干，换季还红",
        version=0,
    )
    events = list(
        flow.stream_meaning(
            turn,
            meaning=_dynamic_meaning(),
        )
    )
    version = events[-1].data.conversation_version

    assert flow.has_dynamic_session(
        _turn("对，就是这样", version=version)
    )
    assert not flow.has_dynamic_session(
        _turn(
            "对，就是这样",
            version=0,
            session_id="missing-dynamic-session",
        )
    )


def test_answers_end_in_typed_provisional_without_profile_write(
    tmp_path: Path,
) -> None:
    flow, _, profile_state = _flow(tmp_path)
    version = 0
    for message in (
        "我不知道自己是什么肤质",
        "会",
        "不会",
        "不会",
        "不会",
    ):
        events = _events(flow, message, version=version)
        assert "consultation_observation" in _names(events)
        version = events[-1].data.conversation_version

    events = _events(flow, "不会", version=version)

    assert _names(events) == [
        "start",
        "stage",
        "intent",
        "consultation_provisional",
        "answer_contract",
        "card_display_contract",
        "presentation_contract",
        "message",
        "end",
    ]
    provisional = events[3].data
    assert provisional.conversation_version == 7
    assert provisional.conclusion.skin_target == "dry"
    assert provisional.conclusion.evidence == (
        "post_cleanse_tightness",
    )
    assert provisional.conclusion.uncertainties == ()
    assert provisional.conclusion.confidence == "medium"
    assert provisional.conclusion.confirmed_by_user is False
    assert profile_state.load(_OWNER) is None


def test_confirmation_emits_session_profile_without_long_term_write(
    tmp_path: Path,
) -> None:
    flow, conversation_state, profile_state = _flow(tmp_path)
    version = 0
    for message in (
        "我不知道自己是什么肤质",
        "会",
        "不会",
        "不会",
        "不会",
        "不会",
    ):
        events = _events(flow, message, version=version)
        version = events[-1].data.conversation_version

    events = _events(flow, "我确认是干皮", version=version)

    assert _names(events) == [
        "start",
        "stage",
        "intent",
        "profile_confirmation",
        "answer_contract",
        "card_display_contract",
        "presentation_contract",
        "message",
        "end",
    ]
    confirmation = events[3].data
    assert confirmation.conversation_version == 8
    assert confirmation.conclusion.confirmed_by_user is True
    assert confirmation.profile_persistence is None
    assert confirmation.session_profile.base_skin is not None
    assert confirmation.session_profile.base_skin.value == "dry"
    stored = conversation_state.load("consultation-chat-flow")
    assert stored is not None
    assert stored.session_profile == confirmation.session_profile
    assert profile_state.load(_OWNER) is None


def test_medical_red_flag_emits_terminal_typed_event_and_no_cards(
    tmp_path: Path,
) -> None:
    flow, _, profile_state = _flow(tmp_path)
    entered = _events(
        flow,
        "我不知道自己是什么肤质",
        version=0,
    )

    events = _events(
        flow,
        "会，而且明显疼痛",
        version=entered[-1].data.conversation_version,
    )

    assert _names(events) == [
        "start",
        "stage",
        "intent",
        "medical_escalation",
        "answer_contract",
        "card_display_contract",
        "presentation_contract",
        "message",
        "end",
    ]
    escalation = events[3].data
    assert escalation.stop_skincare_advice is True
    assert [item.code for item in escalation.escalation_triggers] == [
        "pain"
    ]
    assert escalation.conclusion.confirmed_by_user is False
    assert events[5].data.max_cards == 0
    assert profile_state.load(_OWNER) is None


def test_claims_only_entry_or_active_consultation_turns(
    tmp_path: Path,
) -> None:
    flow, _, _ = _flow(tmp_path)

    assert flow.claims(_turn(
        "我不知道自己是什么肤质",
        version=0,
    ))
    assert not flow.claims(_turn("500元内防晒", version=0))

    entered = _events(
        flow,
        "我不知道自己是什么肤质",
        version=0,
    )
    version = entered[-1].data.conversation_version
    assert flow.claims(_turn("会", version=version))
