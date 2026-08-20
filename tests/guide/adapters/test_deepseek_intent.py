from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
import json

import httpx
import pytest

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import SemanticContext


_API_KEY = "deepseek-official-test-key-not-real"
_MODEL = "deepseek-v4-pro"
_MESSAGE = "推荐防晒"


def _adapter_type():
    try:
        module = import_module(
            "app.guide.adapters.llm.deepseek_intent"
        )
    except ModuleNotFoundError:
        pytest.fail("DeepSeek official intent adapter is missing", pytrace=False)
    return module.DeepSeekIntentAdapter


def _context() -> SemanticContext:
    return SemanticContext(
        conversation_version=2,
        active_topic=TopicCode.SUNSCREEN,
        visible_candidate_count=2,
        focused_candidate_ordinal=1,
        confirmed_profile_fields=(),
    )


def _proposal_payload() -> dict[str, object]:
    return {
        "goal": "recommendation",
        "topic": "sunscreen",
        "concerns": ["sun_protection"],
        "observations": [],
        "references": [],
        "confidence": 0.97,
        "clarification_hint": None,
    }


def _response(content: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": content or json.dumps(_proposal_payload())
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
            },
        },
    )


class SequenceTransport(httpx.BaseTransport):
    def __init__(
        self,
        responses: Sequence[httpx.Response | BaseException],
    ) -> None:
        self._responses = iter(responses)
        self.request_count = 0
        self.request_urls: list[str] = []
        self.request_bodies: list[dict[str, object]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        self.request_urls.append(str(request.url))
        self.request_bodies.append(json.loads(request.read()))
        try:
            response = next(self._responses)
        except StopIteration:
            raise AssertionError("unexpected provider request") from None
        if isinstance(response, BaseException):
            raise response
        return response


def _adapter(transport: httpx.BaseTransport, **updates: object):
    parameters: dict[str, object] = {
        "api_key": _API_KEY,
        "model": _MODEL,
        "timeout_seconds": 2.0,
        "format_repair_attempts": 0,
        "daily_budget_cny": Decimal("1"),
        "daily_call_cap": 100,
        "transport": transport,
        "clock": lambda: datetime(2026, 8, 13, tzinfo=UTC),
    }
    parameters.update(updates)
    return _adapter_type()(**parameters)


def test_single_stage_posts_exact_official_non_thinking_body() -> None:
    transport = SequenceTransport([_response()])
    adapter = _adapter(transport)

    proposal = adapter.propose(_MESSAGE, _context())

    assert proposal.topic is TopicCode.SUNSCREEN
    assert adapter.provider == "deepseek_official"
    assert adapter.base_url == "https://api.deepseek.com"
    assert transport.request_urls == [
        "https://api.deepseek.com/chat/completions"
    ]
    body = transport.request_bodies[0]
    assert set(body) == {
        "model",
        "messages",
        "response_format",
        "temperature",
        "max_tokens",
        "thinking",
        "stream",
    }
    assert body["model"] == _MODEL
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0
    assert body["max_tokens"] == 256
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False
    assert "enable_thinking" not in body
    assert "thinking_budget" not in body


def test_single_stage_is_v4_pro_control_only() -> None:
    with pytest.raises(ValueError, match="V4-Pro"):
        _adapter(
            SequenceTransport([]),
            model="deepseek-v4-flash",
        )


def test_deepseek_adapter_does_not_inherit_siliconflow() -> None:
    adapter_type = _adapter_type()

    assert [base.__name__ for base in adapter_type.__mro__] == [
        "DeepSeekIntentAdapter",
        "object",
    ]


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            httpx.Response(401, json={"error": "private"}),
            SemanticProviderFailureCode.AUTHENTICATION_FAILED,
        ),
        (
            httpx.Response(429, json={"error": "private"}),
            SemanticProviderFailureCode.RATE_LIMITED,
        ),
        (
            httpx.Response(503, json={"error": "private"}),
            SemanticProviderFailureCode.PROVIDER_UNAVAILABLE,
        ),
        (
            httpx.Response(200, content=b""),
            SemanticProviderFailureCode.EMPTY_RESPONSE,
        ),
        (
            httpx.Response(
                200,
                content=b"not-json",
                headers={"content-type": "application/json"},
            ),
            SemanticProviderFailureCode.INVALID_RESPONSE,
        ),
        (
            _response("{not-json"),
            SemanticProviderFailureCode.INVALID_OUTPUT,
        ),
    ],
)
def test_single_stage_maps_provider_failures(
    response: httpx.Response,
    expected_code: SemanticProviderFailureCode,
) -> None:
    with pytest.raises(SemanticProviderFailure) as caught:
        _adapter(SequenceTransport([response])).propose(
            _MESSAGE,
            _context(),
        )

    assert caught.value.code is expected_code
    assert "private" not in str(caught.value)


def test_single_stage_maps_timeout_to_typed_failure() -> None:
    timeout = httpx.ReadTimeout("private timeout")

    with pytest.raises(SemanticProviderFailure) as caught:
        _adapter(SequenceTransport([timeout])).propose(
            _MESSAGE,
            _context(),
        )

    assert caught.value.code is SemanticProviderFailureCode.TIMEOUT
    assert "private timeout" not in str(caught.value)
