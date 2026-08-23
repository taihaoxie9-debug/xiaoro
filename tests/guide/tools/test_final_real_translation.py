from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from tools.guide_gates.run_final_real_translation import (
    FINAL_TRANSLATION_CASE_COUNT,
    FINAL_TRANSLATION_TURNS_PER_TRAJECTORY,
    load_final_translation_trajectories,
    replay_final_translation_gate,
    run_final_translation_gate,
)


FIXTURE = Path(
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v5.jsonl"
)
V4_FIXTURE = Path(
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v4.jsonl"
)


@dataclass(frozen=True)
class FakeCall:
    meaning: TurnMeaning
    raw_content: str
    trace_id: str
    usage: SemanticTokenUsage


class RecordingAdapter:
    model = "deepseek-v4-pro"
    prompt_version = "test-final-translation-v1"

    def __init__(self) -> None:
        self.calls = 0

    def propose_with_result(
        self,
        message: str,
        context,
    ) -> FakeCall:
        del message, context
        self.calls += 1
        meaning = TurnMeaning(
            operation_hint="clarification",
            topic_hint=None,
            continuity_hint="unknown",
            subject_scope_hint="unknown",
            pending_response_hint="unknown",
            safety_language="unknown",
        )
        return FakeCall(
            meaning=meaning,
            raw_content=meaning.model_dump_json(),
            trace_id=f"trace-{self.calls}",
            usage=SemanticTokenUsage(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
        )


class WrongRecommendationModeAdapter(RecordingAdapter):
    def propose_with_result(
        self,
        message: str,
        context,
    ) -> FakeCall:
        del message, context
        self.calls += 1
        meaning = TurnMeaning.model_validate(
            {
                "operation_hint": "recommendation",
                "recommendation_mode": "explore",
                "recommendation_count": None,
                "recommendation_mode_basis": {
                    "basis": "broad_exploration",
                    "source_text": "推荐",
                },
                "topic_hint": "sunscreen",
                "continuity_hint": "new_task",
                "subject_scope_hint": "self",
                "pending_response_hint": "unknown",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [
                    {
                        "raw_text": "三百以内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "300",
                    }
                ],
                "observation_candidates": [],
                "preference_candidates": [],
                "constraint_changes": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": None,
                "safety_language": "ordinary",
            },
            strict=True,
        )
        return FakeCall(
            meaning=meaning,
            raw_content=meaning.model_dump_json(),
            trace_id=f"trace-{self.calls}",
            usage=SemanticTokenUsage(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
        )


def test_final_translation_fixture_is_twelve_four_turn_trajectories() -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)

    assert len(trajectories) == FINAL_TRANSLATION_CASE_COUNT
    assert all(
        len(item.turns) == FINAL_TRANSLATION_TURNS_PER_TRAJECTORY
        for item in trajectories
    )
    assert len({
        turn.turn_id
        for item in trajectories
        for turn in item.turns
    }) == 48


def test_v5_fixture_preserves_v4_messages_and_seals_mode_truth() -> None:
    v4 = [
        json.loads(line)
        for line in V4_FIXTURE.read_text(encoding="utf-8").splitlines()
    ]
    v5 = [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
    ]

    assert [
        turn["case"]["message"]
        for trajectory in v5
        for turn in trajectory["turns"]
    ] == [
        turn["case"]["message"]
        for trajectory in v4
        for turn in trajectory["turns"]
    ]
    assert all(
        {
            "expected_recommendation_mode",
            "expected_recommendation_mode_basis",
        }
        <= set(turn)
        for trajectory in v5
        for turn in trajectory["turns"]
    )


def test_final_translation_gate_stops_after_first_failed_turn(
    tmp_path: Path,
) -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)
    adapter = RecordingAdapter()

    report = run_final_translation_gate(
        trajectories=trajectories,
        adapter=adapter,
        output_dir=tmp_path / "capture",
    )

    assert adapter.calls == 1
    assert report.provider_call_count == 1
    assert report.turn_count == 1
    assert not report.passed
    assert report.stopped_early


def test_final_translation_rejects_wrong_recommendation_mode_truth(
    tmp_path: Path,
) -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)
    output = tmp_path / "wrong-mode"

    report = run_final_translation_gate(
        trajectories=trajectories,
        adapter=WrongRecommendationModeAdapter(),
        output_dir=output,
    )

    row = json.loads(
        (output / "results.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert report.passed is False
    assert row["recommendation_mode_passed"] is False


def test_final_translation_replay_uses_zero_provider_calls(
    tmp_path: Path,
) -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)
    source_dir = tmp_path / "capture"
    adapter = RecordingAdapter()
    run_final_translation_gate(
        trajectories=trajectories,
        adapter=adapter,
        output_dir=source_dir,
    )

    replay = replay_final_translation_gate(
        trajectories=trajectories,
        capture_path=source_dir / "results.jsonl",
        output_dir=tmp_path / "replay",
    )

    assert replay.provider_call_count == 0
    assert replay.turn_count == 1
    assert not replay.passed
