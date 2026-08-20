from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
import json
from pathlib import Path

import httpx
import pytest

from app.guide.adapters.llm.contracts import (
    LLMThinkingContract,
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.adapters.llm.intent_cache import (
    IntentProposalCache,
    build_intent_cache_key,
)
from app.guide.adapters.llm.intent_route_prompt import ROUTE_PROMPT_VERSION
from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.semantic_route_contracts import (
    SemanticRouteProposal,
)


_API_KEY = "deepseek-official-two-stage-test-key-not-real"
_MESSAGE = "推荐防晒"


def _adapter_type():
    try:
        module = import_module(
            "app.guide.adapters.llm.deepseek_two_stage_intent"
        )
    except ModuleNotFoundError:
        pytest.fail(
            "DeepSeek official two-stage adapter is missing",
            pytrace=False,
        )
    return module.DeepSeekTwoStageIntentAdapter


def _context() -> SemanticContext:
    return SemanticContext(
        conversation_version=2,
        active_topic=TopicCode.SUNSCREEN,
        visible_candidate_count=2,
        focused_candidate_ordinal=1,
        confirmed_profile_fields=(),
    )


def _route_payload(
    *,
    goal: str = "recommendation",
    topic: str | None = "sunscreen",
    detail_stage: str = "recommendation",
    confidence: float = 0.96,
    clarification_hint: str | None = None,
) -> dict[str, object]:
    return {
        "goal": goal,
        "topic": topic,
        "detail_stage": detail_stage,
        "confidence": confidence,
        "clarification_hint": clarification_hint,
    }


def _detail_payload() -> dict[str, object]:
    return {
        "concerns": ["sun_protection"],
        "observations": [],
    }


def _response(content: str | dict[str, object]) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}}],
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


def _adapter(
    transport: httpx.BaseTransport,
    *,
    model: str = "deepseek-v4-pro",
    cache: IntentProposalCache | None = None,
    format_repair_attempts: int = 1,
):
    return _adapter_type()(
        api_key=_API_KEY,
        model=model,
        timeout_seconds=2.0,
        format_repair_attempts=format_repair_attempts,
        daily_budget_cny=Decimal("1"),
        daily_call_cap=100,
        transport=transport,
        clock=lambda: datetime(2026, 8, 13, tzinfo=UTC),
        cache=cache,
    )


@pytest.mark.parametrize(
    "model",
    ["deepseek-v4-flash", "deepseek-v4-pro"],
)
def test_two_stage_models_use_exact_official_body(model: str) -> None:
    transport = SequenceTransport(
        [_response(_route_payload()), _response(_detail_payload())]
    )

    result = _adapter(transport, model=model).propose_with_result(
        _MESSAGE,
        _context(),
    )

    assert result.proposal.goal is UnderstandingGoal.RECOMMENDATION
    assert transport.request_count == 2
    assert transport.request_urls == [
        "https://api.deepseek.com/chat/completions",
        "https://api.deepseek.com/chat/completions",
    ]
    for body in transport.request_bodies:
        assert set(body) == {
            "model",
            "messages",
            "response_format",
            "temperature",
            "max_tokens",
            "thinking",
            "stream",
        }
        assert body["model"] == model
        assert body["thinking"] == {"type": "disabled"}
        assert body["temperature"] == 0
        assert body["max_tokens"] == 256
        assert body["response_format"] == {"type": "json_object"}
        assert "enable_thinking" not in body
        assert "thinking_budget" not in body


def test_route_clarification_skips_detail_request() -> None:
    transport = SequenceTransport(
        [
            _response(
                _route_payload(
                    goal="clarification",
                    topic=None,
                    detail_stage="none",
                    confidence=0.35,
                    clarification_hint="goal",
                )
            )
        ]
    )

    proposal = _adapter(transport).propose("看看", _context())

    assert proposal.goal is UnderstandingGoal.CLARIFICATION
    assert transport.request_count == 1


def test_route_and_detail_share_one_repair_budget() -> None:
    transport = SequenceTransport(
        [
            _response("{invalid"),
            _response(_route_payload()),
            _response("{invalid"),
        ]
    )

    with pytest.raises(SemanticProviderFailure) as caught:
        _adapter(transport).propose(_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT
    assert transport.request_count == 3


def test_official_cache_identity_is_present_and_provider_isolated(
    tmp_path: Path,
) -> None:
    cache = IntentProposalCache(
        tmp_path / "intent.sqlite3",
        trusted_state_root=tmp_path,
    )
    transport = SequenceTransport(
        [_response(_route_payload()), _response(_detail_payload())]
    )
    adapter = _adapter(
        transport,
        model="deepseek-v4-pro",
        cache=cache,
    )

    first = adapter.propose(_MESSAGE, _context())
    second = adapter.propose(_MESSAGE, _context())
    route_key = build_intent_cache_key(
        stage="route",
        result_schema=SemanticRouteProposal,
        provider="deepseek_official",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        prompt_version=ROUTE_PROMPT_VERSION,
        message=_MESSAGE,
        context=_context(),
        temperature=0.0,
        max_tokens=256,
        enable_thinking=None,
        thinking=LLMThinkingContract(type="disabled"),
    )
    siliconflow_key = route_key.model_copy(
        update={
            "provider": "siliconflow",
            "base_url": "https://api.siliconflow.cn/v1",
            "generation_parameters": route_key.generation_parameters.model_copy(
                update={
                    "enable_thinking": False,
                    "thinking": None,
                }
            ),
        }
    )

    assert first == second
    assert transport.request_count == 2
    assert cache.get(route_key) is not None
    assert cache.get(siliconflow_key) is None
    assert route_key.fingerprint() != siliconflow_key.fingerprint()


def test_two_stage_does_not_inherit_siliconflow() -> None:
    adapter_type = _adapter_type()

    assert [base.__name__ for base in adapter_type.__mro__] == [
        "DeepSeekTwoStageIntentAdapter",
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
            httpx.Response(500, json={"error": "private"}),
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
    ],
)
def test_two_stage_maps_provider_failures(
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


def test_two_stage_maps_timeout_to_typed_failure() -> None:
    with pytest.raises(SemanticProviderFailure) as caught:
        _adapter(
            SequenceTransport([httpx.ReadTimeout("private timeout")])
        ).propose(_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.TIMEOUT
