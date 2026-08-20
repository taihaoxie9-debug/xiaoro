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
    "real_translation_12x4.jsonl"
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
