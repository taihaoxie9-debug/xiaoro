import json
from pathlib import Path

import pytest

from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
)

CASES = json.loads(
    Path("tests/fixtures/guide/slice1_backend_cases.json").read_text(
        encoding="utf-8"
    )
)


class _FollowupMeaningPort:
    def propose(self, message, context):
        del context
        if message == "500 元内敏感肌修护精华":
            return TurnMeaning(
                operation_hint="recommendation",
                recommendation_mode="explore",
                recommendation_mode_basis={
                    "basis": "bounded_exploration",
                    "source_text": "500 元内",
                },
                topic_hint="serum",
                continuity_hint="new_task",
                subject_scope_hint="self",
                budget_candidates=(
                    {
                        "raw_text": "500 元内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "500",
                    },
                ),
                question_meaning=message,
                safety_language="ordinary",
            )
        if message == "第二款呢":
            return TurnMeaning(
                operation_hint="followup",
                topic_hint=None,
                continuity_hint="continue",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "第二款",
                        "object_family_hint": "product",
                        "ordinal_hint": 2,
                        "plurality_hint": "single",
                    },
                ),
                question_meaning=message,
                safety_language="ordinary",
            )
        return TurnMeaning(
            operation_hint="followup",
            topic_hint=None,
            continuity_hint="continue",
            subject_scope_hint="self",
            reference_mentions=(
                {
                    "raw_text": "预算",
                    "object_family_hint": "constraint",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
            ),
            budget_candidates=(
                {
                    "raw_text": "100元",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "100",
                },
            ),
            question_meaning=message,
            safety_language="ordinary",
        )


def _orchestrator(tmp_path: Path):
    return build_consultation_vertical_runtime(
        state_dir=tmp_path,
        semantic_intent=_FollowupMeaningPort(),
    ).unified


def _turn(
    *,
    session_id: str,
    message: str,
    version: int,
) -> UserTurn:
    return UserTurn(
        identity=TurnIdentity(
            session_id=session_id,
            request_id=(
                f"request_identity_{session_id}_{version:04d}"
            ),
            turn_id=f"turn_identity_{session_id}_{version:04d}",
        ),
        session_id=session_id,
        message=message,
        image_bundle_id=None,
        conversation_version=version,
    )


def _decode_frames(frames) -> list[tuple[str, dict]]:
    events = []
    for frame in frames:
        event_line, data_line, _ = frame.split(b"\n", maxsplit=2)
        events.append(
            (
                event_line.removeprefix(b"event: ").decode("ascii"),
                json.loads(
                    data_line.removeprefix(b"data: ").decode("utf-8")
                ),
            )
        )
    return events


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_slice1_backend_case(case, orchestrator) -> None:
    session_id = f"gate-{case['case_id']}"
    events = _decode_frames(
        orchestrator.stream(
            _turn(
                session_id=session_id,
                message=case["message"],
                version=0,
            )
        )
    )
    assert events[-1][0] == case["terminal_event"]
    products = next(
        (data for event, data in events if event == "products"),
        None,
    )
    actual_ids = (
        [card["product_id"] for card in products["cards"]]
        if products is not None
        else []
    )
    assert actual_ids == case["product_ids"]
    decision = next(
        (
            data
            for event, data in events
            if event == "decision_process"
        ),
        None,
    )
    actual_status = (
        decision["winner_status"] if decision is not None else None
    )
    assert actual_status == case["winner_status"]


def test_recent_candidate_followup_gate(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path / "candidate-followup")
    first = _decode_frames(
        orchestrator.stream(
            _turn(
                session_id="gate-followup",
                message="500 元内敏感肌修护精华",
                version=0,
            )
        )
    )
    assert first[-1][1]["conversation_version"] == 1

    second = _decode_frames(
        orchestrator.stream(
            _turn(
                session_id="gate-followup",
                message="第二款呢",
                version=1,
            )
        )
    )
    products = next(
        data for event, data in second if event == "products"
    )
    assert [card["product_id"] for card in products["cards"]] == [91]
    assert second[-1][1]["conversation_version"] == 2


def test_budget_revision_followup_gate(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path / "budget-revision")
    first = _decode_frames(
        orchestrator.stream(
            _turn(
                session_id="gate-budget-revision",
                message="500 元内敏感肌修护精华",
                version=0,
            )
        )
    )
    second = _decode_frames(
        orchestrator.stream(
            _turn(
                session_id="gate-budget-revision",
                message="预算降到100元呢",
                version=1,
            )
        )
    )

    assert first[-1][1]["conversation_version"] == 1
    products = next(
        data for event, data in second if event == "products"
    )
    decision = next(
        data
        for event, data in second
        if event == "decision_process"
    )
    assert [card["product_id"] for card in products["cards"]] == [91]
    assert decision["winner_status"] == "INSUFFICIENT_FOR_WINNER"
    assert second[-1][1]["conversation_version"] == 2
