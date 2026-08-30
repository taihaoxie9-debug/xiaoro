from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import ActiveFocus
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousRuntimeTurnResult,
    ContinuousTrajectoryExecutionError,
    ContinuousTrajectory,
    execute_continuous_trajectory,
)


def _turn(index: int) -> dict[str, object]:
    return {
        "turn_id": f"continuous-demo-t{index}",
        "message": f"第{index}轮自然问题",
        "acceptable_semantic": {
            "operation_hints": ["recommendation"],
            "topic_hints": ["serum"],
            "continuity_hints": ["new_task"],
            "subject_scope_hints": ["self"],
        },
        "expected_bindings": [],
        "expected_route": {
            "processor": "recommendation",
            "continuity": "replace_task",
            "focus_source": "none",
        },
        "expected_snapshot_subset": {
            "active_owner": "recommendation",
            "active_focus": {"slot": "recommendation"},
        },
        "expected_task_plan_subset": {"mode": "recommend"},
        "expected_card_ids": [],
        "expected_safety": False,
        "expected_clarification": False,
        "expected_presentation_mode": "recommendation",
        "public_answer_policy": "recommendation",
    }


def _trajectory_payload() -> dict[str, object]:
    return {
        "schema_version": "guide-continuous-trajectory-v1",
        "trajectory_id": "continuous-demo",
        "subject_scope": "self",
        "route_families": [
            "recommendation_revision",
        ],
        "turns": [_turn(index) for index in range(1, 6)],
    }


def test_trajectory_requires_exactly_five_turns() -> None:
    payload = _trajectory_payload()
    payload["turns"] = payload["turns"][:4]

    with pytest.raises(ValidationError):
        ContinuousTrajectory.model_validate(payload, strict=True)


def test_trajectory_starts_from_empty_version_zero() -> None:
    payload = _trajectory_payload()
    payload["starting_snapshot"] = {
        "session_id": "preloaded",
        "version": 1,
    }

    with pytest.raises(ValidationError):
        ContinuousTrajectory.model_validate(payload, strict=True)


def test_trajectory_turn_ids_are_unique_and_scoped() -> None:
    payload = _trajectory_payload()
    payload["turns"][4]["turn_id"] = "continuous-demo-t4"

    with pytest.raises(
        ValidationError,
        match="turn IDs must be unique",
    ):
        ContinuousTrajectory.model_validate(payload, strict=True)


def test_image_identity_turn_requires_a_typed_image_fixture() -> None:
    payload = _trajectory_payload()
    turn = payload["turns"][0]
    turn["expected_route"] = {
        "processor": "image_identity",
        "continuity": "replace_task",
        "focus_source": "confirmed_image",
    }
    turn["expected_presentation_mode"] = "image_identity"

    with pytest.raises(
        ValidationError,
        match="image identity requires image fixtures",
    ):
        ContinuousTrajectory.model_validate(payload, strict=True)

    turn["image_fixture_ids"] = ["product-53-front"]
    trajectory = ContinuousTrajectory.model_validate(
        payload,
        strict=True,
    )

    assert trajectory.turns[0].image_fixture_ids == (
        "product-53-front",
    )


def _meaning() -> TurnMeaning:
    return TurnMeaning.model_validate(
        {
            "operation_hint": "recommendation",
            "recommendation_mode": "explore",
            "recommendation_mode_basis": {
                "basis": "broad_exploration",
                "source_text": "推荐",
            },
            "topic_hint": "serum",
            "continuity_hint": "new_task",
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "推荐精华",
            "safety_language": "ordinary",
        },
        strict=True,
    )


class _RecordingRuntime:
    def __init__(
        self,
        *,
        interrupt_turn: int | None = None,
        actual_processor: str = "recommendation",
    ) -> None:
        self._interrupt_turn = interrupt_turn
        self._actual_processor = actual_processor
        self._current: ConversationSnapshot | None = None
        self.execute_count = 0
        self.loaded_session_ids: list[str] = []
        self.received_image_fixture_ids: list[
            tuple[str, ...]
        ] = []

    def execute(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        meaning: TurnMeaning,
        image_fixture_ids: tuple[str, ...],
    ) -> ContinuousRuntimeTurnResult:
        del message, meaning
        self.execute_count += 1
        self.received_image_fixture_ids.append(
            image_fixture_ids
        )
        current_version = (
            self._current.version
            if self._current is not None
            else 0
        )
        assert conversation_version == current_version
        replacement = ConversationSnapshot(
            session_id=session_id,
            version=conversation_version + 1,
            active_owner=Responsibility.RECOMMENDATION,
            active_focus=ActiveFocus(slot="recommendation"),
            recommendation_slot=RecommendationSlotState(
                query_context=RecommendationQueryContext(
                    category="serum",
                    recommendation_mode="explore",
                    recommendation_mode_basis="broad_exploration",
                    recommendation_count=3,
                ),
                empty_result=True,
            ),
        )
        events: list[tuple[str, dict[str, object]]] = [
            ("start", {"session_id": session_id}),
            ("intent", {"intent": "recommend"}),
            ("message", {"content": "本轮回答", "done": False}),
        ]
        if self.execute_count != self._interrupt_turn:
            events.append((
                "end",
                {
                    "conversation_version": (
                        conversation_version + 1
                    )
                },
            ))
            self._current = replacement
        return ContinuousRuntimeTurnResult(
            events=tuple(events),
            semantic_admission_passed=True,
            bindings=(),
            route={
                "processor": self._actual_processor,
                "continuity": "replace_task",
                "focus_source": "none",
            },
            task_plan={"mode": "recommend"},
            safety=False,
            clarification=False,
            presentation_mode="recommendation",
            hard_condition_override=False,
            cross_session_leak=False,
        )

    def load_snapshot(
        self,
        session_id: str,
    ) -> ConversationSnapshot:
        self.loaded_session_ids.append(session_id)
        assert self._current is not None
        assert self._current.session_id == session_id
        return self._current


def _trajectory() -> ContinuousTrajectory:
    return ContinuousTrajectory.model_validate(
        _trajectory_payload(),
        strict=True,
    )


def test_each_turn_consumes_previous_terminal_snapshot() -> None:
    runtime = _RecordingRuntime()

    trace = execute_continuous_trajectory(
        _trajectory(),
        runtime=runtime,
        meanings=tuple(_meaning() for _ in range(5)),
    )

    assert [
        turn.starting_version for turn in trace.turns
    ] == [0, 1, 2, 3, 4]
    assert [
        turn.terminal_version for turn in trace.turns
    ] == [1, 2, 3, 4, 5]
    assert runtime.loaded_session_ids == [
        "continuous-demo",
    ] * 5
    assert runtime.received_image_fixture_ids == [()] * 5


def test_interrupted_turn_does_not_feed_next_turn() -> None:
    runtime = _RecordingRuntime(interrupt_turn=3)

    with pytest.raises(
        ContinuousTrajectoryExecutionError,
        match="terminal end",
    ):
        execute_continuous_trajectory(
            _trajectory(),
            runtime=runtime,
            meanings=tuple(_meaning() for _ in range(5)),
        )

    stored = runtime.load_snapshot("continuous-demo")
    assert stored.version == 2


def test_trace_records_actual_runtime_route_not_expected_route() -> None:
    runtime = _RecordingRuntime(
        actual_processor="general_knowledge",
    )

    trace = execute_continuous_trajectory(
        _trajectory(),
        runtime=runtime,
        meanings=tuple(_meaning() for _ in range(5)),
    )

    assert trace.turns[0].route.processor == "general_knowledge"
