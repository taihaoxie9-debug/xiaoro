from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
import json

import httpx
import pytest

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    TurnMeaningCallResult,
)
from app.guide.adapters.llm.deepseek_turn_meaning import (
    DeepSeekTurnMeaningAdapter,
)
from app.guide.understanding.semantic_contracts import SemanticContext


class SequenceTransport(httpx.BaseTransport):
    def __init__(
        self,
        responses: Sequence[httpx.Response | BaseException],
    ) -> None:
        self.responses = iter(responses)
        self.request_count = 0
        self.bodies: list[dict[str, object]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        self.bodies.append(json.loads(request.read()))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


def _payload(**updates) -> dict[str, object]:
    payload = {
        "operation_hint": "recommendation",
        "topic_hint": "sunscreen",
        "reference_mentions": [],
        "product_mentions": [],
        "budget_candidates": [],
        "observation_candidates": [],
        "preference_candidates": [
            {
                "field_key": "texture",
                "concept_id": "texture.refreshing",
                "raw_text": "清爽",
                "polarity": "prefer",
                "strength": "ordinary",
            }
        ],
        "relative_candidates": [],
        "question_meaning": "推荐清爽防晒",
        "safety_language": "ordinary",
    }
    payload.update(updates)
    return payload


def _response(content: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": content or json.dumps(_payload())
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        },
    )


def _adapter(transport: httpx.BaseTransport):
    return DeepSeekTurnMeaningAdapter(
        api_key="not-a-real-key",
        model="deepseek-v4-pro",
        timeout_seconds=2.0,
        max_tokens=256,
        concept_catalog=(
            "efficacy.soothing",
            "texture.refreshing",
        ),
        daily_budget_cny=Decimal("1"),
        daily_call_cap=100,
        transport=transport,
        clock=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )


def _context() -> SemanticContext:
    return SemanticContext(
        conversation_version=0,
        active_topic=None,
        visible_candidate_count=0,
        confirmed_profile_fields=(),
    )


def test_deepseek_turn_meaning_uses_exactly_one_request() -> None:
    raw_content = json.dumps(
        _payload(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    transport = SequenceTransport([_response(raw_content)])
    adapter = _adapter(transport)

    result = adapter.propose_with_result(
        "推荐清爽防晒",
        _context(),
    )

    assert isinstance(result, TurnMeaningCallResult)
    assert result.meaning.topic_hint == "sunscreen"
    assert result.usage.total_tokens == 30
    assert result.raw_content == raw_content
    assert result.trace_id == "unavailable"
    assert transport.request_count == 1
    body = transport.bodies[0]
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False
    assert len(body["messages"]) == 2


def test_deepseek_turn_meaning_allows_multi_observation_output_budget(
) -> None:
    transport = SequenceTransport([_response()])
    adapter = DeepSeekTurnMeaningAdapter(
        api_key="not-a-real-key",
        model="deepseek-v4-pro",
        timeout_seconds=2.0,
        max_tokens=1024,
        concept_catalog=(
            "efficacy.soothing",
            "texture.refreshing",
        ),
        daily_budget_cny=Decimal("1"),
        daily_call_cap=100,
        transport=transport,
        clock=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )

    adapter.propose_with_result("推荐清爽防晒", _context())

    assert transport.bodies[0]["max_tokens"] == 1024


@pytest.mark.parametrize(
    "content",
    [
        "{not-json",
        json.dumps({**_payload(), "product_id": 55}),
    ],
)
def test_deepseek_invalid_output_fails_without_repair(
    content: str,
) -> None:
    transport = SequenceTransport([_response(content)])
    adapter = _adapter(transport)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(
            "推荐清爽防晒",
            _context(),
        )

    assert caught.value.code in {
        SemanticProviderFailureCode.INVALID_OUTPUT,
        SemanticProviderFailureCode.FORBIDDEN_OUTPUT,
    }
    assert caught.value.raw_content == content
    assert caught.value.trace_id == "unavailable"
    assert caught.value.usage is not None
    assert caught.value.usage.total_tokens == 30
    assert transport.request_count == 1
