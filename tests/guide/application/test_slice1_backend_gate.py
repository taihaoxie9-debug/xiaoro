import json
from pathlib import Path

import pytest

from app.guide.application.contracts import UserTurn

CASES = json.loads(
    Path("tests/fixtures/guide/slice1_backend_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_slice1_backend_case(case, orchestrator) -> None:
    events = list(
        orchestrator.stream(
            UserTurn(
                session_id=f"gate-{case['case_id']}",
                message=case["message"],
                image_bundle_id=None,
                conversation_version=0,
            )
        )
    )
    assert events[-1].event == case["terminal_event"]
    products = next(
        (event for event in events if event.event == "products"),
        None,
    )
    actual_ids = (
        [card.product_id for card in products.data.cards]
        if products is not None
        else []
    )
    assert actual_ids == case["product_ids"]
    decision = next(
        (
            event
            for event in events
            if event.event == "decision_process"
        ),
        None,
    )
    actual_status = (
        decision.data.winner_status if decision is not None else None
    )
    assert actual_status == case["winner_status"]


def test_recent_candidate_followup_gate(orchestrator) -> None:
    first = list(
        orchestrator.stream(
            UserTurn(
                session_id="gate-followup",
                message="500 元内敏感肌修护精华",
                image_bundle_id=None,
                conversation_version=0,
            )
        )
    )
    assert first[-1].data.conversation_version == 1

    second = list(
        orchestrator.stream(
            UserTurn(
                session_id="gate-followup",
                message="第二款呢",
                image_bundle_id=None,
                conversation_version=1,
            )
        )
    )
    products = next(
        event for event in second if event.event == "products"
    )
    assert [card.product_id for card in products.data.cards] == [91]
    assert second[-1].data.conversation_version == 2


def test_budget_revision_followup_gate(orchestrator) -> None:
    first = list(
        orchestrator.stream(
            UserTurn(
                session_id="gate-budget-revision",
                message="500 元内敏感肌修护精华",
                image_bundle_id=None,
                conversation_version=0,
            )
        )
    )
    second = list(
        orchestrator.stream(
            UserTurn(
                session_id="gate-budget-revision",
                message="预算降到100元呢",
                image_bundle_id=None,
                conversation_version=1,
            )
        )
    )

    assert first[-1].data.conversation_version == 1
    products = next(
        item for item in second if item.event == "products"
    )
    decision = next(
        item for item in second
        if item.event == "decision_process"
    )
    assert [card.product_id for card in products.data.cards] == [91]
    assert decision.data.winner_status == "INSUFFICIENT_FOR_WINNER"
    assert second[-1].data.conversation_version == 2
