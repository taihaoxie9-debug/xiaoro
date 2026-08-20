from __future__ import annotations

from copy import deepcopy

import pytest

from app.guide.application import chat_api_adapter
from app.guide.application.chat_api_adapter import (
    GuidePublicEventError,
    collect_guide_chat_response,
)
from app.guide.application.contracts import UserTurn


def _turn(message: str) -> UserTurn:
    return UserTurn(
        session_id="presentation-public",
        message=message,
        image_bundle_id=None,
        conversation_version=0,
    )


def _adapted(orchestrator, message: str):
    return [
        chat_api_adapter._adapt_guide_event(event)
        for event in orchestrator.stream(_turn(message))
    ]


def _presentation(events):
    return next(
        data
        for name, data in events
        if name == "presentation_contract"
    )


def _assert_invalid(events) -> None:
    with pytest.raises(GuidePublicEventError) as caught:
        collect_guide_chat_response(
            events,
            session_id="presentation-public",
            conversation_version=0,
        )
    assert caught.value.code == "GUIDE_EVENT_CONTRACT_INVALID"


def test_public_adapter_preserves_typed_presentation_and_aggregates_it(
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
    assert names.index("presentation_contract") < names.index(
        "message"
    )
    presentation = _presentation(events)
    assert presentation["mode"] == "recommendation"
    assert presentation["card_display"][
        "visible_product_ids"
    ] == [101, 26, 52]

    response = collect_guide_chat_response(
        events,
        session_id="presentation-public",
        conversation_version=0,
    )

    assert response["presentation_contract"] == presentation
    assert response["metadata"]["presentation_contract"] == presentation


def test_public_adapter_rejects_presentation_card_mismatch(
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


def test_public_adapter_rejects_reordered_presentation_sections(
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


def test_public_adapter_rejects_presentation_after_message(
    orchestrator,
) -> None:
    events = _adapted(
        orchestrator,
        "500 内适合油敏肌的防晒",
    )
    mutated = [
        item for item in deepcopy(events)
        if item[0] != "presentation_contract"
    ]
    end = mutated.pop()
    mutated.append(("presentation_contract", _presentation(events)))
    mutated.append(end)

    _assert_invalid(mutated)


def test_public_adapter_rejects_presentation_on_terminal_error(
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
