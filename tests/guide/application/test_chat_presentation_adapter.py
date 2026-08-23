from __future__ import annotations

from copy import deepcopy
import json

import pytest

from app.guide.application import public_event_envelope
from app.guide.application.chat_api_adapter import (
    iter_guide_public_events,
)
from app.guide.application.public_event_envelope import (
    GuidePublicEventError,
    materialize_guide_public_events,
)
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.presentation.sse_events import (
    ClarifyData,
    ClarifyEvent,
    EndData,
    EndEvent,
    IntentData,
    IntentEvent,
    MessageData,
    MessageEvent,
    StartData,
    StartEvent,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


def _turn(message: str) -> UserTurn:
    session_id = "presentation-public"
    return UserTurn(
        identity=TurnIdentity(
            session_id=session_id,
            request_id="request_presentation_public",
            turn_id="turn_presentation_public",
        ),
        session_id=session_id,
        message=message,
        image_bundle_id=None,
        conversation_version=0,
    )


def _adapted(orchestrator, message: str):
    turn = _turn(message)
    events = []
    for frame in orchestrator.stream(turn):
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


def _presentation(events):
    return next(
        data
        for name, data in events
        if name == "presentation_contract"
    )


def _assert_invalid(events) -> None:
    with pytest.raises(GuidePublicEventError) as caught:
        public_event_envelope._validate_guide_event_sequence(
            events,
            session_id="presentation-public",
        )
    assert caught.value.code == "GUIDE_EVENT_CONTRACT_INVALID"


def test_public_envelope_preserves_typed_presentation(
    orchestrator,
) -> None:
    events = _adapted(
        orchestrator,
        "500 内适合油敏肌的防晒",
    )
    names = [name for name, _ in events]

    assert names.index("products") < names.index(
        "presentation_contract"
    )
    assert "message" not in names
    presentation = _presentation(events)
    assert presentation["mode"] == "recommendation"
    assert presentation["card_display"][
        "visible_product_ids"
    ] == [101, 26, 52]
    products = next(
        data["products"]
        for name, data in events
        if name == "products"
    )
    assert all(
        product["price_specification_alignment"]
        in {"aligned", "unresolved", "conflict"}
        for product in products
    )
    assert all(
        product["specification"] is None
        for product in products
        if product["price_specification_alignment"] != "aligned"
    )


def test_public_envelope_rejects_presentation_card_mismatch(
    orchestrator,
) -> None:
    events = _adapted(
        orchestrator,
        "500 内适合油敏肌的防晒",
    )
    mutated = deepcopy(events)
    presentation = _presentation(mutated)
    presentation["card_display"]["visible_product_ids"] = [57, 55, 54]

    _assert_invalid(mutated)


def test_public_envelope_rejects_reordered_presentation_sections(
    orchestrator,
) -> None:
    events = _adapted(
        orchestrator,
        "500 内适合油敏肌的防晒",
    )
    mutated = deepcopy(events)
    presentation = _presentation(mutated)
    presentation["sections"] = list(
        reversed(presentation["sections"])
    )

    _assert_invalid(mutated)


def test_public_envelope_rejects_message_event(
    orchestrator,
) -> None:
    events = _adapted(
        orchestrator,
        "500 内适合油敏肌的防晒",
    )
    mutated = deepcopy(events)
    end = mutated.pop()
    mutated.append(("message", {"content": "legacy body"}))
    mutated.append(end)

    _assert_invalid(mutated)


def test_public_event_boundary_rejects_typed_message_after_contract(
    orchestrator,
) -> None:
    turn = _turn("500 内适合油敏肌的防晒")
    frames = tuple(orchestrator.stream(turn))
    with pytest.raises(
        TypeError,
        match="only pre-encoded SSE bytes",
    ):
        tuple(
            iter_guide_public_events(
                (
                    *frames[:-1],
                    MessageEvent(data=MessageData(content="legacy body")),
                    frames[-1],
                ),
                session_id=turn.session_id,
            )
        )


def test_clarification_event_cannot_rewrite_prior_intent() -> None:
    typed_events = (
        StartEvent(data=StartData(session_id="presentation-public")),
        IntentEvent(data=IntentData(mode="recommend")),
        ClarifyEvent(
            data=ClarifyData(
                question="当前公开事实不足以给出唯一推荐。",
                clarification_code=ClarificationCode.GOAL,
            )
        ),
        EndEvent(data=EndData(conversation_version=0)),
    )
    events = list(
        materialize_guide_public_events(
            typed_events,
            session_id="presentation-public",
        )
    )

    assert [name for name, _ in events] == [
        "start",
        "intent",
        "clarify",
        "end",
    ]
    assert events[1][1]["intent"] == "recommend"
    assert events[1][1]["scenario_intent"] == "recommend"
    assert events[2][1] == {
        "question": "当前公开事实不足以给出唯一推荐。",
        "clarification_code": "goal",
    }


def test_public_envelope_rejects_presentation_on_terminal_error(
    orchestrator,
) -> None:
    events = _adapted(
        orchestrator,
        "500 内适合油敏肌的防晒",
    )
    presentation = deepcopy(_presentation(events))

    _assert_invalid(
        [
            ("start", {"session_id": "presentation-public"}),
            ("presentation_contract", presentation),
            (
                "error",
                {
                    "error": "GUIDE_INTERNAL_ERROR",
                    "message": "推荐暂时不可用，请稍后重试。",
                },
            ),
        ]
    )
