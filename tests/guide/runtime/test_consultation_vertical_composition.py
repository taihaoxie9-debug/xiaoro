from __future__ import annotations

from pathlib import Path

from app.guide.application.contracts import UserTurn
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
)
from tests.guide.semantic_test_port import ExactEchoSemanticPort


class StaticSemanticPort:
    def __init__(self) -> None:
        self.calls = 0

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del message, context
        self.calls += 1
        return SemanticIntentProposal(
            goal=SemanticGoal.RECOMMENDATION,
            topic=TopicCode.SUNSCREEN,
            concerns=(),
            observations=(),
            references=(),
            confidence=0.99,
            clarification_hint=None,
        )


def _runtime(
    tmp_path: Path,
    *,
    semantic_intent=None,
):
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    return build_consultation_vertical_runtime(
        state_dir=tmp_path / "state",
        semantic_intent=(
            semantic_intent
            if semantic_intent is not None
            else ExactEchoSemanticPort()
        ),
    )


def _turn(
    runtime,
    message: str,
    *,
    version: int,
    session_id: str,
) -> UserTurn:
    return UserTurn(
        session_id=session_id,
        message=message,
        profile_owner=runtime.profile_owner(session_id),
        conversation_version=version,
    )


def _consult(
    runtime,
    message: str,
    *,
    version: int,
    session_id: str,
):
    return list(
        runtime.consultation.stream(
            _turn(
                runtime,
                message,
                version=version,
                session_id=session_id,
            )
        )
    )


def _confirm_dry_profile(runtime, *, session_id: str) -> int:
    version = 0
    for message in (
        "我不知道自己是什么肤质",
        "会",
        "不会",
        "不会",
        "不会",
        "不会",
        "我确认是干皮",
    ):
        events = _consult(
            runtime,
            message,
            version=version,
            session_id=session_id,
        )
        assert events[-1].event == "end"
        version = events[-1].data.conversation_version
    return version


def test_composition_uses_durable_owner_bound_sqlite_state(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    session_id = "consultation-durable-session"
    owner = runtime.profile_owner(session_id)

    version = _confirm_dry_profile(runtime, session_id=session_id)

    assert version == 8
    assert runtime.conversation_state.database_path == (
        tmp_path / "state" / "conversations.sqlite3"
    )
    assert runtime.profile_state.database_path == (
        tmp_path / "state" / "profiles.sqlite3"
    )
    stored = runtime.conversation_state.load(session_id)
    assert stored is not None
    profile = stored.session_profile
    assert profile is not None
    assert profile.base_skin is not None
    assert profile.base_skin.value == "dry"
    assert runtime.profile_state.load(owner) is None

    restarted = _runtime(tmp_path)
    restarted_turn = _turn(
        restarted,
        "500元内防晒",
        version=version,
        session_id=session_id,
    )
    assert restarted.consultation.has_session(restarted_turn)
    restarted_snapshot = restarted.conversation_state.load(session_id)
    assert restarted_snapshot is not None
    assert restarted_snapshot.session_profile == profile
    assert restarted.profile_state.load(owner) is None


def test_confirmed_profile_only_fills_missing_recommendation_skin(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    session_id = "consultation-profile-fill-session"
    version = _confirm_dry_profile(runtime, session_id=session_id)

    events = list(
        runtime.recommendation.stream(
            _turn(
                runtime,
                "500元内防晒",
                version=version,
                session_id=session_id,
            )
        )
    )

    assert events[-1].event == "end"
    assert not any(event.event == "error" for event in events)
    stored = runtime.conversation_state.load(session_id)
    assert stored is not None
    assert stored.query_context is not None
    assert stored.query_context.skin == "dry"


def test_current_explicit_skin_wins_without_overwriting_profile(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    session_id = "consultation-explicit-wins-session"
    version = _confirm_dry_profile(runtime, session_id=session_id)
    owner = runtime.profile_owner(session_id)
    before_snapshot = runtime.conversation_state.load(session_id)
    assert before_snapshot is not None
    before = before_snapshot.session_profile
    assert before is not None

    events = list(
        runtime.recommendation.stream(
            _turn(
                runtime,
                "500元内油性防晒",
                version=version,
                session_id=session_id,
            )
        )
    )

    assert events[-1].event == "end"
    assert not any(event.event == "error" for event in events)
    stored = runtime.conversation_state.load(session_id)
    assert stored is not None
    assert stored.query_context is not None
    assert stored.query_context.skin == "oily"
    assert stored.session_profile == before
    assert runtime.profile_state.load(owner) is None


def test_consultation_followup_ordinary_text_uses_semantic_port(
    tmp_path: Path,
) -> None:
    semantic = StaticSemanticPort()
    runtime = _runtime(tmp_path, semantic_intent=semantic)
    session_id = "consultation-semantic-followup-session"
    version = _confirm_dry_profile(runtime, session_id=session_id)

    events = list(
        runtime.recommendation.stream(
            _turn(
                runtime,
                "夏天涂着不容易晒黑的东西",
                version=version,
                session_id=session_id,
            )
        )
    )

    intent = next(event for event in events if event.event == "intent")
    products = next(event for event in events if event.event == "products")
    assert intent.data.mode == "recommend"
    assert intent.data.category_profile.value == "suncare"
    assert products.data.cards
    assert semantic.calls == 1


def test_profile_owner_is_server_composed_and_session_bound(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)

    first = runtime.profile_owner("session-owner-one")
    replay = runtime.profile_owner("session-owner-one")
    second = runtime.profile_owner("session-owner-two")

    assert first == replay
    assert first != second
    assert first.scope == "anonymous_browser"
    assert first.subject_id.startswith("profile_")
    assert "session-owner-one" not in first.subject_id
