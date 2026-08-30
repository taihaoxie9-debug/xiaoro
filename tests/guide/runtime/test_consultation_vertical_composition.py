from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


class ConsultationTurnMeaningPort:
    def __init__(self) -> None:
        self.calls = 0

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> TurnMeaning:
        self.calls += 1
        if context.conversation_version == 0:
            return TurnMeaning(
                operation_hint="assessment",
                topic_hint="skincare",
                continuity_hint="new_task",
                subject_scope_hint="self",
                observation_candidates=(
                    {
                        "observation_id": "obs_dry_cheeks",
                        "code": "dryness",
                        "present": True,
                        "qualifier": None,
                        "raw_text": "两颊干燥",
                        "location": "cheeks",
                        "trigger": None,
                        "duration": None,
                        "severity": None,
                    },
                    {
                        "observation_id": "obs_no_oil",
                        "code": "oiliness",
                        "present": False,
                        "qualifier": None,
                        "raw_text": "T区不油",
                        "location": "t_zone",
                        "trigger": None,
                        "duration": None,
                        "severity": None,
                    },
                    {
                        "observation_id": "obs_seasonal_redness",
                        "code": "redness",
                        "present": True,
                        "qualifier": None,
                        "raw_text": "换季泛红",
                        "location": None,
                        "trigger": "seasonal",
                        "duration": None,
                        "severity": None,
                    },
                    {
                        "observation_id": "obs_tolerance",
                        "code": "product_tolerance",
                        "present": True,
                        "qualifier": None,
                        "raw_text": "平时保湿不刺痛",
                        "location": None,
                        "trigger": "ordinary_skincare",
                        "duration": None,
                        "severity": None,
                    },
                    {
                        "observation_id": "obs_no_pain",
                        "code": "pain",
                        "present": False,
                        "qualifier": None,
                        "raw_text": "现在也不疼",
                        "location": None,
                        "trigger": None,
                        "duration": "current",
                        "severity": None,
                    },
                ),
                consultation_hypothesis={
                    "base_skin_direction": "dry",
                    "stable_tendencies": ("seasonal_redness",),
                    "current_conditions": ("redness",),
                    "supporting_observation_ids": (
                        "obs_dry_cheeks",
                        "obs_no_oil",
                        "obs_seasonal_redness",
                        "obs_tolerance",
                        "obs_no_pain",
                    ),
                },
                next_observation_gap="confirmation",
                question_meaning="根据完整观察形成待确认肤质结论",
                safety_language="ordinary",
            )
        if context.conversation_version == 1:
            return TurnMeaning(
                operation_hint="assessment",
                topic_hint="skincare",
                continuity_hint="continue",
                subject_scope_hint="self",
                pending_response_hint="affirm",
                preference_candidates=(
                    {
                        "field_key": "skin",
                        "concept_id": "skin.dry",
                        "raw_text": "干皮",
                        "polarity": "prefer",
                        "strength": "ordinary",
                    },
                ),
                question_meaning="确认干性肤质结论",
                safety_language="ordinary",
            )
        return self._recommendation_meaning(message)

    @staticmethod
    def _recommendation_meaning(message: str) -> TurnMeaning:
        skin_preferences = (
            (
                {
                    "field_key": "skin",
                    "concept_id": "skin.oily",
                    "raw_text": "油性",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            )
            if "油性" in message
            else ()
        )
        return TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_mode_basis={
                "basis": "bounded_exploration",
                "source_text": message,
            },
            topic_hint="sunscreen",
            continuity_hint="new_task",
            subject_scope_hint="self",
            budget_candidates=(
                (
                    {
                        "raw_text": "500元内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "500",
                    },
                )
                if "500" in message
                else ()
            ),
            preference_candidates=skin_preferences,
            question_meaning="推荐适合当前条件的防晒",
            safety_language="ordinary",
        )


class StaticSemanticPort(ConsultationTurnMeaningPort):
    pass


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
            else ConsultationTurnMeaningPort()
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
        identity=TurnIdentity(
            session_id=session_id,
            request_id=f"request_{session_id}_{version:04d}",
            turn_id=f"turn_{session_id}_{version:04d}",
        ),
        session_id=session_id,
        message=message,
        profile_owner=runtime.profile_owner(session_id),
        conversation_version=version,
    )


def _namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(
            **{key: _namespace(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return [_namespace(item) for item in value]
    return value


def _decode_events(frames):
    events = []
    for frame in frames:
        lines = frame.decode("utf-8").splitlines()
        name = next(
            line.removeprefix("event: ")
            for line in lines
            if line.startswith("event: ")
        )
        payload = "".join(
            line.removeprefix("data: ")
            for line in lines
            if line.startswith("data: ")
        )
        events.append(
            SimpleNamespace(
                event=name,
                data=_namespace(json.loads(payload)),
            )
        )
    return events


def _consult(
    runtime,
    message: str,
    *,
    version: int,
    session_id: str,
):
    return _decode_events(
        runtime.unified.stream(
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
        "两颊干燥，T区不油，换季泛红，平时保湿不刺痛，现在也不疼",
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

    assert version == 2
    assert runtime.conversation_state.database_path == (
        tmp_path / "state" / "conversations.sqlite3"
    )
    stored = runtime.conversation_state.load(session_id)
    assert stored is not None
    profile = stored.session_profile
    assert profile is not None
    assert profile.base_skin is not None
    assert profile.base_skin.value == "dry"
    restarted = _runtime(tmp_path)
    restarted_snapshot = restarted.conversation_state.load(session_id)
    assert restarted_snapshot is not None
    assert restarted_snapshot.session_profile == profile
    assert restarted_snapshot.profile_owner == owner


def test_confirmed_profile_only_fills_missing_recommendation_skin(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    session_id = "consultation-profile-fill-session"
    version = _confirm_dry_profile(runtime, session_id=session_id)

    events = _decode_events(
        runtime.unified.stream(
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
    assert stored.recommendation_slot is not None
    assert stored.recommendation_slot.query_context.skin == "dry"


def test_current_explicit_skin_wins_without_overwriting_profile(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    session_id = "consultation-explicit-wins-session"
    version = _confirm_dry_profile(runtime, session_id=session_id)
    before_snapshot = runtime.conversation_state.load(session_id)
    assert before_snapshot is not None
    before = before_snapshot.session_profile
    assert before is not None

    events = _decode_events(
        runtime.unified.stream(
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
    assert stored.recommendation_slot is not None
    assert stored.recommendation_slot.query_context.skin == "oily"
    assert stored.session_profile == before


def test_consultation_followup_ordinary_text_uses_semantic_port(
    tmp_path: Path,
) -> None:
    semantic = StaticSemanticPort()
    runtime = _runtime(tmp_path, semantic_intent=semantic)
    session_id = "consultation-semantic-followup-session"
    version = _confirm_dry_profile(runtime, session_id=session_id)

    events = _decode_events(
        runtime.unified.stream(
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
    assert intent.data.intent == "recommend"
    assert intent.data.category_profile == "suncare"
    assert products.data.cards
    assert semantic.calls == 3


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
