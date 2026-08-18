from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.guide.adapters.llm.contracts import (
    SemanticTokenUsage,
    TurnMeaningCallResult,
)
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
    StoredConcept,
)
from app.guide.feedback.focus_state import FocusState
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide.understanding.semantic_contracts import ClarificationCode
from tools.guide_gates.continuous_conversation_fixture import (
    load_frozen_trajectories,
)
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousFailureLayer,
    ContinuousRuntimeTurnResult,
    ContinuousTrajectory,
    ContinuousTurnTrace,
)
from tools.guide_gates.run_real_continuous_conversation_gate import (
    evaluate_continuous_turn,
    replay_captured_continuous_gate,
    run_real_continuous_gate,
)


def _meaning(turn) -> TurnMeaning:
    topic = next(
        (
            topic
            for topic in turn.acceptable_semantic.topic_hints
            if topic is not None
        ),
        None,
    )
    return TurnMeaning.model_validate(
        {
            "operation_hint": (
                turn.acceptable_semantic.operation_hints[0]
            ),
            "topic_hint": topic,
            "continuity_hint": (
                turn.acceptable_semantic.continuity_hints[0]
            ),
            "subject_scope_hint": (
                turn.acceptable_semantic.subject_scope_hints[0]
            ),
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": turn.message,
            "safety_language": (
                "safety" if turn.expected_safety else "ordinary"
            ),
        },
        strict=True,
    )


class _RecordingAdapter:
    model = "offline/continuous"
    prompt_version = "offline-continuous-v1"

    def __init__(
        self,
        trajectories: tuple[ContinuousTrajectory, ...],
    ) -> None:
        self._meanings = {
            turn.message: _meaning(turn)
            for trajectory in trajectories
            for turn in trajectory.turns
        }
        self.calls: list[tuple[str, object]] = []

    def propose_with_result(self, message, context):
        self.calls.append((message, context))
        meaning = self._meanings[message]
        return TurnMeaningCallResult(
            meaning=meaning,
            usage=SemanticTokenUsage(
                prompt_tokens=9,
                completion_tokens=6,
                total_tokens=15,
                cached_tokens=0,
            ),
            raw_content=meaning.model_dump_json(),
            trace_id="sha256:continuous-test",
        )


class _InterruptingAdapter(_RecordingAdapter):
    def propose_with_result(self, message, context):
        if len(self.calls) == 2:
            raise KeyboardInterrupt
        return super().propose_with_result(message, context)


class _DurabilityAdapter(_RecordingAdapter):
    def __init__(
        self,
        trajectories: tuple[ContinuousTrajectory, ...],
        output_path: Path,
    ) -> None:
        super().__init__(trajectories)
        self._output_path = output_path

    def propose_with_result(self, message, context):
        if self.calls:
            artifact = json.loads(
                self._output_path.read_text(encoding="utf-8")
            )
            assert len(artifact["results"]) == len(self.calls)
        return super().propose_with_result(message, context)


class _ForbiddenCopywriter:
    calls = 0

    def write(self, packet):
        del packet
        self.calls += 1
        raise AssertionError("copywriter must stay disabled")


class _Runtime:
    def __init__(
        self,
        trajectory: ContinuousTrajectory,
        *,
        wrong_first_route: bool = False,
    ) -> None:
        self._turns = {
            turn.message: turn for turn in trajectory.turns
        }
        self._wrong_first_route = wrong_first_route
        self._current: ConversationSnapshot | None = None
        self._pending: ConversationSnapshot | None = None
        self._execute_count = 0

    def execute(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        meaning: TurnMeaning,
        image_fixture_ids: tuple[str, ...],
    ) -> ContinuousRuntimeTurnResult:
        del meaning
        turn = self._turns[message]
        assert image_fixture_ids == turn.image_fixture_ids
        self._execute_count += 1
        processor = turn.expected_route.processor
        if self._wrong_first_route and self._execute_count == 1:
            processor = "general_knowledge"
        expected_snapshot = turn.expected_snapshot_subset
        expected_focus = expected_snapshot.get("focus_state", {})
        focus_processor = expected_focus.get(
            "active_processor",
            processor,
        )
        expected_clarification = expected_snapshot.get(
            "clarification"
        )
        clarification = (
            ClarificationProgress(
                gap=ClarificationCode(
                    expected_clarification["gap"]
                ),
                attempts=expected_clarification["attempts"],
            )
            if isinstance(expected_clarification, dict)
            else None
        )
        expected_query = expected_snapshot.get("query_context")
        query_context = (
            RecommendationQueryContext(
                category=expected_query["category"],
                budget_minimum=(
                    Decimal(expected_query["budget_minimum"])
                    if expected_query.get("budget_minimum") is not None
                    else None
                ),
                budget_maximum=(
                    Decimal(expected_query["budget_maximum"])
                    if expected_query.get("budget_maximum") is not None
                    else None
                ),
                skin=expected_query.get("skin"),
                efficacy=expected_query.get("efficacy"),
                concepts=tuple(
                    StoredConcept(
                        field_key=item["field_key"],
                        concept_id=item["concept_id"],
                        polarity=item["polarity"],
                    )
                    for item in expected_query.get("concepts", ())
                ),
            )
            if isinstance(expected_query, dict)
            else None
        )
        current_product_id = (
            turn.expected_bindings[0].product_id
            if processor == "product_knowledge"
            and len(turn.expected_bindings) == 1
            else None
        )
        self._pending = ConversationSnapshot(
            session_id=session_id,
            version=conversation_version + 1,
            query_context=(
                query_context
                or (
                    RecommendationQueryContext(category="serum")
                    if current_product_id is not None
                    else None
                )
            ),
            candidates=(
                (
                    DisplayedCandidateRef(
                        product_id=current_product_id,
                        ordinal=1,
                        skin_match="not_applicable",
                        matched_efficacies=(),
                    ),
                )
                if current_product_id is not None
                else (
                    tuple(
                        DisplayedCandidateRef(
                            product_id=product_id,
                            ordinal=index,
                            skin_match="not_applicable",
                            matched_efficacies=(),
                        )
                        for index, product_id in enumerate(
                            turn.expected_card_ids,
                            start=1,
                        )
                    )
                    if query_context is not None
                    else ()
                )
            ),
            focus_state=FocusState(
                active_processor=focus_processor,
                current_product_id=current_product_id,
            ),
            clarification=clarification,
        )
        events: list[tuple[str, dict[str, object]]] = [
            ("start", {"session_id": session_id}),
            ("intent", {"intent": processor}),
        ]
        if turn.expected_clarification:
            events.append((
                "clarify",
                {"question": "请补充具体信息。"},
            ))
        else:
            events.append((
                "message",
                {"content": "本轮直接回答。", "done": False},
            ))
        if turn.expected_presentation_mode is not None:
            events.append((
                "presentation_contract",
                {"mode": turn.expected_presentation_mode},
            ))
        if turn.expected_card_ids:
            events.append((
                "products",
                {
                    "products": [
                        {"id": product_id}
                        for product_id in turn.expected_card_ids
                    ]
                },
            ))
        events.append((
            "end",
            {"conversation_version": conversation_version + 1},
        ))
        route = turn.expected_route.model_copy(
            update={"processor": processor},
            deep=True,
        )
        return ContinuousRuntimeTurnResult(
            events=tuple(events),
            semantic_admission_passed=True,
            bindings=turn.expected_bindings,
            route=route,
            task_plan=turn.expected_task_plan_subset,
            safety=turn.expected_safety,
            clarification=turn.expected_clarification,
            presentation_mode=turn.expected_presentation_mode,
            hard_condition_override=False,
            cross_session_leak=False,
        )

    def commit(self, terminal_event) -> None:
        assert terminal_event[0] == "end"
        assert self._pending is not None
        self._current = self._pending
        self._pending = None

    def discard(self, terminal_event) -> None:
        del terminal_event
        self._pending = None

    def load_snapshot(self, session_id: str) -> ConversationSnapshot:
        assert self._current is not None
        assert self._current.session_id == session_id
        return self._current


def _runtime_factory(
    *,
    wrong_first_route: bool = False,
):
    def build(
        trajectory: ContinuousTrajectory,
        state_root: Path,
    ) -> _Runtime:
        state_root.mkdir(parents=True, exist_ok=False)
        return _Runtime(
            trajectory,
            wrong_first_route=wrong_first_route,
        )

    return build


def _failing_runtime_factory():
    class FailingRuntime(_Runtime):
        def execute(self, **kwargs):
            del kwargs
            raise RuntimeError("state transition exploded")

        @staticmethod
        def failure_layer_for_last_error():
            return ContinuousFailureLayer.STATE_TRANSITION

    def build(
        trajectory: ContinuousTrajectory,
        state_root: Path,
    ) -> FailingRuntime:
        state_root.mkdir(parents=True, exist_ok=False)
        return FailingRuntime(trajectory)

    return build


def test_real_gate_calls_provider_once_per_turn_and_never_copywriter(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:2]
    adapter = _RecordingAdapter(trajectories)
    copywriter = _ForbiddenCopywriter()
    output_path = tmp_path / "capture.json"

    report = run_real_continuous_gate(
        trajectories=trajectories,
        adapter=adapter,
        copywriter=copywriter,
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "state",
        output_path=output_path,
    )
    artifact = json.loads(output_path.read_text(encoding="utf-8"))

    assert report.trajectory_count == 2
    assert report.turn_count == 10
    assert report.provider_call_count == 10
    assert report.copywriter_call_count == 0
    assert report.retry_count == 0
    assert len(adapter.calls) == 10
    assert copywriter.calls == 0
    assert [
        call[1].conversation_version for call in adapter.calls
    ] == [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
    assert len(artifact["results"]) == 10


def test_real_gate_persists_and_reports_progress_after_each_attempt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    trajectories = load_frozen_trajectories()[:1]
    output_path = tmp_path / "progress.json"
    adapter = _DurabilityAdapter(trajectories, output_path)

    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=adapter,
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "state",
        output_path=output_path,
    )

    progress = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("progress ")
    ]
    assert len(progress) == 5
    assert "trajectory_id=" in progress[0]
    assert "turn_id=" in progress[0]
    assert "attempted_calls=1" in progress[0]
    assert "total_tokens=15" in progress[0]
    assert all("authorization" not in line.casefold() for line in progress)
    assert all("api_key" not in line.casefold() for line in progress)


def test_captured_replay_uses_zero_provider_calls(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:2]
    capture_path = tmp_path / "capture.json"
    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "capture-state",
        output_path=capture_path,
    )

    report = replay_captured_continuous_gate(
        trajectories=trajectories,
        capture_path=capture_path,
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "replay-state",
        output_path=tmp_path / "replay.json",
    )

    assert report.provider_call_count == 0
    assert report.copywriter_call_count == 0
    assert report.replayed_turn_count == 10
    assert report.passed_turn_count == 10
    assert report.passed_trajectory_count == 2


def test_real_gate_resumes_green_global_prefix_without_recalling_provider(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:2]
    complete_capture = tmp_path / "complete-capture.json"
    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "capture-state",
        output_path=complete_capture,
    )
    artifact = json.loads(
        complete_capture.read_text(encoding="utf-8")
    )
    artifact["results"] = artifact["results"][:7]
    partial_capture = tmp_path / "partial-capture.json"
    partial_capture.write_text(
        json.dumps(artifact, ensure_ascii=False),
        encoding="utf-8",
    )
    adapter = _RecordingAdapter(trajectories)

    report = run_real_continuous_gate(
        trajectories=trajectories,
        adapter=adapter,
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "resume-state",
        output_path=tmp_path / "resumed.json",
        resume_capture_path=partial_capture,
    )

    assert len(adapter.calls) == 3
    assert report.provider_call_count == 10
    assert report.reused_provider_call_count == 7
    assert report.new_provider_call_count == 3
    assert report.passed_turn_count == 10
    assert report.passed_trajectory_count == 2


def test_real_gate_rejects_resume_prompt_drift_before_provider_call(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:1]
    capture_path = tmp_path / "capture.json"
    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "capture-state",
        output_path=capture_path,
    )
    artifact = json.loads(capture_path.read_text(encoding="utf-8"))
    artifact["summary"]["prompt_version"] = "drifted-prompt"
    capture_path.write_text(
        json.dumps(artifact, ensure_ascii=False),
        encoding="utf-8",
    )
    adapter = _RecordingAdapter(trajectories)

    with pytest.raises(ValueError, match="model or prompt"):
        run_real_continuous_gate(
            trajectories=trajectories,
            adapter=adapter,
            copywriter=_ForbiddenCopywriter(),
            runtime_factory=_runtime_factory(),
            state_root=tmp_path / "resume-state",
            output_path=tmp_path / "resumed.json",
            resume_capture_path=capture_path,
        )

    assert adapter.calls == []


def test_real_gate_rejects_non_global_resume_prefix(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:1]
    capture_path = tmp_path / "capture.json"
    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "capture-state",
        output_path=capture_path,
    )
    artifact = json.loads(capture_path.read_text(encoding="utf-8"))
    artifact["results"] = [
        artifact["results"][0],
        artifact["results"][2],
    ]
    capture_path.write_text(
        json.dumps(artifact, ensure_ascii=False),
        encoding="utf-8",
    )
    adapter = _RecordingAdapter(trajectories)

    with pytest.raises(ValueError, match="global contiguous prefix"):
        run_real_continuous_gate(
            trajectories=trajectories,
            adapter=adapter,
            copywriter=_ForbiddenCopywriter(),
            runtime_factory=_runtime_factory(),
            state_root=tmp_path / "resume-state",
            output_path=tmp_path / "resumed.json",
            resume_capture_path=capture_path,
        )

    assert adapter.calls == []


def test_replay_revalidates_raw_json_after_contract_repair(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:1]
    complete_capture = tmp_path / "complete-capture.json"
    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "capture-state",
        output_path=complete_capture,
    )
    artifact = json.loads(
        complete_capture.read_text(encoding="utf-8")
    )
    first_row = artifact["results"][0]
    raw_payload = first_row["provider_output"]
    raw_payload["consultation_hypothesis"] = {
        "base_skin_direction": "unknown",
        "stable_tendencies": [],
        "current_conditions": [],
        "supporting_observation_ids": [],
    }
    raw_output = json.dumps(
        raw_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    first_row["provider_output"] = None
    first_row["provider_output_sha256"] = sha256(b"null").hexdigest()
    first_row["provider_raw_output"] = raw_output
    first_row["provider_raw_output_sha256"] = sha256(
        raw_output.encode("utf-8")
    ).hexdigest()
    repaired_capture = tmp_path / "repaired-capture.json"
    repaired_capture.write_text(
        json.dumps(artifact, ensure_ascii=False),
        encoding="utf-8",
    )

    report = replay_captured_continuous_gate(
        trajectories=trajectories,
        capture_path=repaired_capture,
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "replay-state",
        output_path=tmp_path / "replay.json",
    )

    assert report.provider_call_count == 0
    assert report.replayed_turn_count == 5
    assert report.passed_turn_count == 5
    assert report.replay_passed is True


def test_partial_capture_replays_contiguous_captured_prefixes(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:2]
    complete_capture = tmp_path / "complete-capture.json"
    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "capture-state",
        output_path=complete_capture,
    )
    artifact = json.loads(
        complete_capture.read_text(encoding="utf-8")
    )
    artifact["results"] = [
        *artifact["results"][:5],
        *artifact["results"][5:7],
    ]
    partial_capture = tmp_path / "partial-capture.json"
    partial_capture.write_text(
        json.dumps(artifact, ensure_ascii=False),
        encoding="utf-8",
    )

    report = replay_captured_continuous_gate(
        trajectories=trajectories,
        capture_path=partial_capture,
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "replay-state",
        output_path=tmp_path / "replay.json",
        allow_partial=True,
    )

    assert report.expected_turn_count == 10
    assert report.captured_turn_count == 7
    assert report.replayed_turn_count == 7
    assert report.capture_complete is False
    assert report.replay_passed is True
    assert report.passed is False
    assert report.provider_call_count == 0


def test_partial_capture_rejects_noncontiguous_trajectory_turns(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:1]
    complete_capture = tmp_path / "complete-capture.json"
    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "capture-state",
        output_path=complete_capture,
    )
    artifact = json.loads(
        complete_capture.read_text(encoding="utf-8")
    )
    artifact["results"] = [
        artifact["results"][0],
        artifact["results"][2],
    ]
    partial_capture = tmp_path / "gapped-capture.json"
    partial_capture.write_text(
        json.dumps(artifact, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="contiguous prefix",
    ):
        replay_captured_continuous_gate(
            trajectories=trajectories,
            capture_path=partial_capture,
            runtime_factory=_runtime_factory(),
            state_root=tmp_path / "replay-state",
            output_path=tmp_path / "replay.json",
            allow_partial=True,
        )


def test_capture_rejects_duplicate_turn_identities(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:1]
    complete_capture = tmp_path / "complete-capture.json"
    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "capture-state",
        output_path=complete_capture,
    )
    artifact = json.loads(
        complete_capture.read_text(encoding="utf-8")
    )
    artifact["results"].append(artifact["results"][0])
    duplicate_capture = tmp_path / "duplicate-capture.json"
    duplicate_capture.write_text(
        json.dumps(artifact, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="duplicate capture turn identities",
    ):
        replay_captured_continuous_gate(
            trajectories=trajectories,
            capture_path=duplicate_capture,
            runtime_factory=_runtime_factory(),
            state_root=tmp_path / "replay-state",
            output_path=tmp_path / "replay.json",
            allow_partial=True,
        )


def test_capture_rejects_input_identity_drift(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:1]
    complete_capture = tmp_path / "complete-capture.json"
    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "capture-state",
        output_path=complete_capture,
    )
    artifact = json.loads(
        complete_capture.read_text(encoding="utf-8")
    )
    artifact["results"][0]["message"] = "被篡改的消息"
    drifted_capture = tmp_path / "drifted-capture.json"
    drifted_capture.write_text(
        json.dumps(artifact, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="capture input identity drifted",
    ):
        replay_captured_continuous_gate(
            trajectories=trajectories,
            capture_path=drifted_capture,
            runtime_factory=_runtime_factory(),
            state_root=tmp_path / "replay-state",
            output_path=tmp_path / "replay.json",
        )


def test_failed_turn_records_exactly_one_earliest_layer(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:1]
    output_path = tmp_path / "failed-capture.json"

    run_real_continuous_gate(
        trajectories=trajectories,
        adapter=_RecordingAdapter(trajectories),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(
            wrong_first_route=True,
        ),
        state_root=tmp_path / "failed-state",
        output_path=output_path,
    )
    rows = json.loads(
        output_path.read_text(encoding="utf-8")
    )["results"]

    assert rows[0]["evaluation"]["passed"] is False
    assert rows[0]["evaluation"]["failure_layer"] == "route_selection"
    assert sum(
        row["evaluation"]["failure_layer"] is not None
        for row in rows
    ) == 1


def test_repair_qualification_stops_after_first_evaluated_failure(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:2]
    output_path = tmp_path / "repair-stop.json"
    adapter = _RecordingAdapter(trajectories)

    report = run_real_continuous_gate(
        trajectories=trajectories,
        adapter=adapter,
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(
            wrong_first_route=True,
        ),
        state_root=tmp_path / "repair-stop-state",
        output_path=output_path,
        stop_on_first_failure=True,
    )
    rows = json.loads(
        output_path.read_text(encoding="utf-8")
    )["results"]

    assert report.provider_call_count == 1
    assert report.turn_count == 1
    assert len(adapter.calls) == 1
    assert len(rows) == 1
    assert rows[0]["evaluation"]["failure_layer"] == "route_selection"
    assert not report.passed


def test_clarification_event_is_a_complete_public_answer(
    tmp_path: Path,
) -> None:
    trajectory = next(
        item
        for item in load_frozen_trajectories()
        if item.trajectory_id == "recovery-ambiguous-product"
    )
    output_path = tmp_path / "clarification.json"

    run_real_continuous_gate(
        trajectories=(trajectory,),
        adapter=_RecordingAdapter((trajectory,)),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_runtime_factory(),
        state_root=tmp_path / "clarification-state",
        output_path=output_path,
    )
    first = json.loads(
        output_path.read_text(encoding="utf-8")
    )["results"][0]

    assert first["evaluation"]["passed"] is True
    assert first["trace"]["clarification"] is True
    assert first["trace"]["public_messages"] == []


def _crashing_runtime_factory(
    *,
    crash_turn_ordinal: int,
    crash_trajectory_id: str,
):
    class CrashingRuntime(_Runtime):
        def __init__(self, trajectory: ContinuousTrajectory) -> None:
            super().__init__(trajectory)
            self._trajectory_id = trajectory.trajectory_id

        def execute(self, **kwargs):
            self._execute_count += 1
            if (
                self._trajectory_id == crash_trajectory_id
                and self._execute_count == crash_turn_ordinal
            ):
                raise RuntimeError("state transition exploded")
            self._execute_count -= 1
            return super().execute(**kwargs)

        @staticmethod
        def failure_layer_for_last_error():
            return ContinuousFailureLayer.STATE_TRANSITION

    def build(
        trajectory: ContinuousTrajectory,
        state_root: Path,
    ) -> CrashingRuntime:
        state_root.mkdir(parents=True, exist_ok=False)
        return CrashingRuntime(trajectory)

    return build


def test_runtime_exception_records_layer_and_continues_next_trajectory(
    tmp_path: Path,
) -> None:
    trajectories = load_frozen_trajectories()[:2]
    output_path = tmp_path / "runtime-error.json"
    adapter = _RecordingAdapter(trajectories)

    report = run_real_continuous_gate(
        trajectories=trajectories,
        adapter=adapter,
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=_crashing_runtime_factory(
            crash_turn_ordinal=3,
            crash_trajectory_id=trajectories[0].trajectory_id,
        ),
        state_root=tmp_path / "runtime-error-state",
        output_path=output_path,
    )
    rows = json.loads(
        output_path.read_text(encoding="utf-8")
    )["results"]

    first_id = trajectories[0].trajectory_id
    first_rows = [r for r in rows if r["trajectory_id"] == first_id]
    crashed = first_rows[2]

    # The crashed turn keeps its captured provider output and earliest layer.
    assert crashed["provider_output"] is not None
    assert crashed["evaluation"]["failure_layer"] == "state_transition"
    # The crashed trajectory does not chain further real calls after the crash.
    assert len(first_rows) == 3
    # The next independent trajectory still runs its full five turns.
    assert report.trajectory_count == 2
    assert (
        len([r for r in rows if r["trajectory_id"] != first_id]) == 5
    )
    # Only 3 (crashed trajectory) + 5 (clean trajectory) provider calls.
    assert report.provider_call_count == 8
    assert report.passed is False


def test_runtime_failure_without_public_text_is_not_language_leak(
    tmp_path: Path,
) -> None:
    trajectory = load_frozen_trajectories()[0]
    output_path = tmp_path / "runtime-public-error.json"

    class PublicFailureRuntime(_Runtime):
        def execute(self, **kwargs):
            del kwargs
            raise RuntimeError("presentation never emitted")

        @staticmethod
        def failure_layer_for_last_error():
            return ContinuousFailureLayer.PUBLIC_PRESENTATION

    def runtime_factory(
        candidate: ContinuousTrajectory,
        state_root: Path,
    ) -> PublicFailureRuntime:
        state_root.mkdir(parents=True, exist_ok=False)
        return PublicFailureRuntime(candidate)

    report = run_real_continuous_gate(
        trajectories=(trajectory,),
        adapter=_RecordingAdapter((trajectory,)),
        copywriter=_ForbiddenCopywriter(),
        runtime_factory=runtime_factory,
        state_root=tmp_path / "runtime-public-error-state",
        output_path=output_path,
    )
    row = json.loads(
        output_path.read_text(encoding="utf-8")
    )["results"][0]

    assert row["trace"] is None
    assert row["evaluation"]["failure_layer"] == "public_presentation"
    assert (
        row["evaluation"]["internal_public_language_count"]
        == 0
    )
    assert report.internal_public_language_count == 0


def test_capture_is_persisted_after_each_completed_turn(
    tmp_path: Path,
) -> None:
    trajectory = load_frozen_trajectories()[0]
    output_path = tmp_path / "incremental.json"

    try:
        run_real_continuous_gate(
            trajectories=(trajectory,),
            adapter=_InterruptingAdapter((trajectory,)),
            copywriter=_ForbiddenCopywriter(),
            runtime_factory=_runtime_factory(),
            state_root=tmp_path / "incremental-state",
            output_path=output_path,
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("interrupting adapter must stop the gate")

    artifact = json.loads(
        output_path.read_text(encoding="utf-8")
    )
    assert artifact["summary"]["turn_count"] == 3
    assert artifact["summary"]["provider_call_count"] == 3
    assert len(artifact["results"]) == 3
    assert artifact["results"][-1]["provider_output"] is None
    assert (
        artifact["results"][-1]["evaluation"]["failure_layer"]
        == "model_translation"
    )


def _recommendation_turn_and_trace():
    trajectory = next(
        item
        for item in load_frozen_trajectories()
        if item.trajectory_id == "shop-repair-budget-return"
    )
    turn = trajectory.turns[0]  # expects cards [38, 91], recommendation
    runtime = _Runtime(trajectory)
    result = runtime.execute(
        session_id=trajectory.trajectory_id,
        conversation_version=0,
        message=turn.message,
        meaning=_meaning(turn),
        image_fixture_ids=(),
    )
    runtime.commit(result.events[-1])
    snapshot = runtime.load_snapshot(trajectory.trajectory_id)
    trace = ContinuousTurnTrace(
        turn_id=turn.turn_id,
        starting_version=0,
        terminal_version=1,
        image_fixture_ids=(),
        meaning=_meaning(turn),
        semantic_admission_passed=True,
        bindings=result.bindings,
        route=result.route,
        task_plan=result.task_plan,
        card_ids=(91, 38),  # same identity set as expected [38, 91], reordered
        public_messages=("本轮直接回答。",),
        event_names=tuple(e for e, _ in result.events),
        safety=False,
        clarification=False,
        presentation_mode="recommendation",
        hard_condition_override=False,
        cross_session_leak=False,
        final_snapshot=snapshot,
    )
    return turn, trace


def test_recommendation_card_ranking_order_is_not_a_failure() -> None:
    turn, trace = _recommendation_turn_and_trace()

    evaluation = evaluate_continuous_turn(
        trajectory_id="shop-repair-budget-return",
        turn=turn,
        meaning=trace.meaning,
        trace=trace,
    )

    assert evaluation.layer_evidence.data_coverage is True
    assert evaluation.wrong_product_or_image_binding_count == 0


def test_unexpected_extra_card_still_fails_data_coverage() -> None:
    turn, trace = _recommendation_turn_and_trace()
    trace = trace.model_copy(update={"card_ids": (38, 91, 129)}, deep=True)

    evaluation = evaluate_continuous_turn(
        trajectory_id="shop-repair-budget-return",
        turn=turn,
        meaning=trace.meaning,
        trace=trace,
    )

    assert evaluation.layer_evidence.data_coverage is False
    assert evaluation.wrong_product_or_image_binding_count == 1
