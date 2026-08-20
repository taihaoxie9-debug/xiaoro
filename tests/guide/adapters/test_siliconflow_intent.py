from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
from threading import Event, Lock, Thread, current_thread

import httpx
import pytest
from pydantic import ValidationError

from app.guide.adapters.llm.contracts import (
    SemanticIntentCallResult,
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticTokenUsage,
)
from app.guide.adapters.llm import siliconflow_intent
from app.guide.adapters.llm.intent_prompt import INTENT_PROMPT_VERSION
from app.guide.adapters.llm.siliconflow_intent import (
    SiliconFlowIntentAdapter,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import (
    ConfirmedProfileField,
    SemanticContext,
    SemanticIntentProposal,
)
from app.guide_runtime.llm_config import GuideLlmConfig


TEST_API_KEY = "adapter-test-key-not-a-real-secret"
TEST_MODEL = "provider/model-under-test"
TEST_MESSAGE = "我想找适合夏天、闻起来清爽的东西"
PROVIDER_ERROR_BODY = "provider-private-error-body"


def _context() -> SemanticContext:
    return SemanticContext(
        conversation_version=2,
        active_topic=TopicCode.FRAGRANCE,
        visible_candidate_count=2,
        confirmed_profile_fields=(
            ConfirmedProfileField.SKIN_TYPE,
            ConfirmedProfileField.PREFERRED_CATEGORY,
        ),
    )


def _proposal_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "goal": "recommendation",
        "topic": "fragrance",
        "concerns": ["fragrance", "sillage"],
        "observations": [],
        "references": [],
        "confidence": 0.97,
        "clarification_hint": None,
    }
    payload.update(updates)
    return payload


def _success_response(
    *,
    content: str | None = None,
    usage: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            content
                            if content is not None
                            else json.dumps(_proposal_payload())
                        )
                    }
                }
            ],
            "usage": usage
            or {
                "prompt_tokens": 40,
                "completion_tokens": 25,
                "total_tokens": 65,
            },
        },
        headers=headers,
    )


def _adapter(
    handler,
    *,
    model: str = TEST_MODEL,
    max_tokens: int = 256,
    format_repair_attempts: int = 1,
    daily_budget_cny: Decimal = Decimal("1"),
    daily_call_cap: int = 200,
    clock=lambda: datetime(2026, 8, 11, tzinfo=UTC),
) -> SiliconFlowIntentAdapter:
    return SiliconFlowIntentAdapter(
        api_key=TEST_API_KEY,
        base_url="https://example.invalid/v1",
        model=model,
        timeout_seconds=2.0,
        max_tokens=max_tokens,
        format_repair_attempts=format_repair_attempts,
        daily_budget_cny=daily_budget_cny,
        daily_call_cap=daily_call_cap,
        transport=httpx.MockTransport(handler),
        clock=clock,
    )


def _assert_no_sensitive_traceback_value(
    value: object,
    sensitive_values: tuple[str, ...],
) -> None:
    if isinstance(value, SiliconFlowIntentAdapter):
        pytest.fail("typed failure traceback retained adapter credentials")
    if isinstance(
        value,
        (httpx.HTTPError, httpx.Request, httpx.Response),
    ):
        pytest.fail(
            "typed failure traceback retained provider transport state"
        )
    if isinstance(value, str):
        assert all(secret not in value for secret in sensitive_values)
        return
    if isinstance(value, bytes):
        decoded = value.decode("utf-8", errors="replace")
        assert all(secret not in decoded for secret in sensitive_values)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_no_sensitive_traceback_value(key, sensitive_values)
            _assert_no_sensitive_traceback_value(item, sensitive_values)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _assert_no_sensitive_traceback_value(item, sensitive_values)


def _assert_clean_provider_failure(
    failure: SemanticProviderFailure,
    *sensitive_values: str,
) -> None:
    pending: list[BaseException] = [failure]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        assert isinstance(current, SemanticProviderFailure)
        assert all(
            secret not in str(current) and secret not in repr(current)
            for secret in sensitive_values
        )
        assert current.__context__ is None
        assert current.__cause__ is None

        traceback = current.__traceback__
        while traceback is not None:
            if traceback.tb_frame.f_globals.get("__name__") == (
                "app.guide.adapters.llm.siliconflow_intent"
            ):
                for value in traceback.tb_frame.f_locals.values():
                    _assert_no_sensitive_traceback_value(
                        value,
                        sensitive_values,
                    )
            traceback = traceback.tb_next


def test_adapter_posts_openai_compatible_compact_json_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.read())
        return _success_response(
            headers={"x-request-id": "trace-test-123"}
        )

    adapter = _adapter(handler, max_tokens=192)

    result = adapter.propose(TEST_MESSAGE, _context())

    assert result.topic is TopicCode.FRAGRANCE
    assert str(captured["url"]) == (
        "https://example.invalid/v1/chat/completions"
    )
    assert captured["authorization"] == f"Bearer {TEST_API_KEY}"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == TEST_MODEL
    assert body["temperature"] == 0
    assert body["max_tokens"] == 192
    assert body["enable_thinking"] is False
    assert "reasoning_effort" not in body
    assert "thinking_budget" not in body
    assert body["stream"] is False
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    request_blob = json.dumps(body, ensure_ascii=False)
    assert TEST_API_KEY not in request_blob
    assert "product_facts" not in request_blob
    assert "candidate_ids" not in request_blob


def test_frozen_models_share_non_thinking_generation_parameters() -> None:
    models = (
        "deepseek-ai/DeepSeek-V4-Flash",
        "deepseek-ai/DeepSeek-V3.2",
    )
    bodies: dict[str, dict[str, object]] = {}

    for model in models:
        def handler(
            request: httpx.Request,
            *,
            active_model: str = model,
        ) -> httpx.Response:
            bodies[active_model] = json.loads(request.read())
            return _success_response()

        _adapter(handler, model=model).propose(TEST_MESSAGE, _context())

    generation_parameters = [
        {
            "temperature": bodies[model]["temperature"],
            "max_tokens": bodies[model]["max_tokens"],
            "enable_thinking": bodies[model]["enable_thinking"],
        }
        for model in models
    ]
    assert generation_parameters == [
        {
            "temperature": 0,
            "max_tokens": 256,
            "enable_thinking": False,
        },
        {
            "temperature": 0,
            "max_tokens": 256,
            "enable_thinking": False,
        },
    ]
    for body in bodies.values():
        assert "reasoning_effort" not in body
        assert "thinking_budget" not in body


def test_adapter_returns_strict_usage_from_same_validated_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response(
            usage={
                "prompt_tokens": 41,
                "completion_tokens": 26,
                "total_tokens": 67,
                "cached_tokens": 9,
            }
        )

    result = _adapter(handler).propose_with_result(
        TEST_MESSAGE,
        _context(),
    )

    assert calls == 1
    assert isinstance(result, SemanticIntentCallResult)
    assert isinstance(result.proposal, SemanticIntentProposal)
    assert result.usage == SemanticTokenUsage(
        prompt_tokens=41,
        completion_tokens=26,
        total_tokens=67,
        cached_tokens=9,
    )


def test_propose_remains_proposal_only_and_uses_one_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response()

    proposal = _adapter(handler).propose(TEST_MESSAGE, _context())

    assert calls == 1
    assert isinstance(proposal, SemanticIntentProposal)


def test_semantic_call_result_rejects_coercible_or_cost_usage() -> None:
    proposal = SemanticIntentProposal.model_validate_json(
        json.dumps(_proposal_payload()),
        strict=True,
    )

    with pytest.raises(ValidationError):
        SemanticIntentCallResult(
            proposal=proposal,
            usage={
                "prompt_tokens": "41",
                "completion_tokens": 26,
                "total_tokens": 67,
                "cached_tokens": None,
            },
        )
    with pytest.raises(ValidationError):
        SemanticTokenUsage(
            prompt_tokens=41,
            completion_tokens=26,
            total_tokens=67,
            cached_tokens=None,
            cost_cny="0.01",
        )


def test_adapter_returns_translation_only_contract() -> None:
    adapter = _adapter(lambda request: _success_response())

    result = adapter.propose(TEST_MESSAGE, _context())

    assert "acts" not in type(result).model_fields


def test_adapter_exposes_versioned_identity_without_defaulting_model() -> None:
    adapter = _adapter(lambda request: _success_response())

    assert adapter.provider == "siliconflow"
    assert adapter.model == TEST_MODEL
    assert adapter.prompt_version == INTENT_PROMPT_VERSION
    assert "DeepSeek-V4-Flash" not in repr(adapter)


def test_provider_failure_contract_is_specific_and_closed() -> None:
    assert issubclass(SemanticProviderFailure, RuntimeError)
    assert not issubclass(SemanticProviderFailure, TypeError)
    assert {item.value for item in SemanticProviderFailureCode} == {
        "authentication_failed",
        "rate_limited",
        "provider_unavailable",
        "provider_rejected",
        "timeout",
        "empty_response",
        "invalid_response",
        "invalid_output",
        "forbidden_output",
        "daily_budget_exceeded",
        "daily_call_cap_exceeded",
    }


def test_programmer_type_error_is_not_mapped_to_provider_failure() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response()

    adapter = _adapter(handler)

    with pytest.raises(TypeError):
        adapter.propose(TEST_MESSAGE, object())  # type: ignore[arg-type]

    assert calls == 0


def test_programmer_validation_error_is_not_mapped_to_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError) as validation:
        SemanticContext.model_validate(
            {"conversation_version": "not-an-integer"},
            strict=True,
        )
    programmer_error = validation.value
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response()

    def fail_to_build_messages(*args: object, **kwargs: object) -> object:
        raise programmer_error

    monkeypatch.setattr(
        siliconflow_intent,
        "build_intent_messages",
        fail_to_build_messages,
    )
    adapter = _adapter(handler)

    with pytest.raises(ValidationError) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value is programmer_error
    assert calls == 0


def test_adapter_can_be_built_from_ready_environment_config() -> None:
    config = GuideLlmConfig(
        api_key=TEST_API_KEY,
        base_url="https://example.invalid/v1",
        model=TEST_MODEL,
        timeout_seconds=2.0,
        max_tokens=128,
        daily_budget_cny=Decimal("3"),
        daily_call_cap=9,
        format_repair_attempts=0,
    )

    adapter = SiliconFlowIntentAdapter.from_config(
        config,
        transport=httpx.MockTransport(
            lambda request: _success_response()
        ),
    )

    assert adapter.propose(TEST_MESSAGE, _context()).topic is TopicCode.FRAGRANCE


@pytest.mark.parametrize(
    ("status_code", "failure_code"),
    (
        (401, SemanticProviderFailureCode.AUTHENTICATION_FAILED),
        (429, SemanticProviderFailureCode.RATE_LIMITED),
        (500, SemanticProviderFailureCode.PROVIDER_UNAVAILABLE),
        (503, SemanticProviderFailureCode.PROVIDER_UNAVAILABLE),
    ),
)
def test_adapter_maps_http_failures_without_error_body(
    status_code: int,
    failure_code: SemanticProviderFailureCode,
) -> None:
    adapter = _adapter(
        lambda request: httpx.Response(
            status_code,
            json={"error": PROVIDER_ERROR_BODY},
        )
    )

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is failure_code
    assert PROVIDER_ERROR_BODY not in str(caught.value)
    assert PROVIDER_ERROR_BODY not in repr(caught.value)
    assert caught.value.__cause__ is None


def test_adapter_maps_timeout_without_exception_detail() -> None:
    timeout_detail = "transport-timeout-private-detail"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(timeout_detail, request=request)

    adapter = _adapter(handler)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.TIMEOUT
    assert timeout_detail not in str(caught.value)
    assert timeout_detail not in repr(caught.value)
    assert caught.value.__cause__ is None


def test_timeout_failure_drops_recursive_transport_state() -> None:
    timeout_detail = "transport-timeout-private-detail"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(timeout_detail, request=request)

    adapter = _adapter(handler)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.TIMEOUT
    _assert_clean_provider_failure(
        caught.value,
        TEST_API_KEY,
        TEST_MESSAGE,
        timeout_detail,
    )


def test_invalid_json_failure_drops_recursive_provider_body() -> None:
    provider_body = "provider-raw-invalid-json"
    adapter = _adapter(
        lambda request: httpx.Response(
            200,
            content=provider_body,
            headers={"content-type": "application/json"},
        )
    )

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_RESPONSE
    _assert_clean_provider_failure(
        caught.value,
        TEST_API_KEY,
        TEST_MESSAGE,
        provider_body,
    )


def test_schema_failure_drops_recursive_validation_state() -> None:
    provider_body = "provider-forbidden-output-marker"
    forbidden = _proposal_payload(product_ids=[provider_body])
    adapter = _adapter(
        lambda request: _success_response(
            content=json.dumps(forbidden),
        )
    )

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.FORBIDDEN_OUTPUT
    _assert_clean_provider_failure(
        caught.value,
        TEST_API_KEY,
        TEST_MESSAGE,
        provider_body,
    )


@pytest.mark.parametrize(
    ("content", "expected_kind", "expected_path"),
    (
        ("{not-json", "json_syntax", "root"),
        (
            json.dumps(
                {
                    key: value
                    for key, value in _proposal_payload().items()
                    if key != "goal"
                }
            ),
            "missing",
            "goal",
        ),
        (
            json.dumps(_proposal_payload(private_output_key="secret")),
            "extra",
            "root",
        ),
        (
            json.dumps(_proposal_payload(topic="not-a-topic")),
            "enum",
            "topic",
        ),
        (
            json.dumps(_proposal_payload(concerns={})),
            "type",
            "concerns",
        ),
        (
            json.dumps(
                _proposal_payload(
                    observations=[
                        {
                            "code": "not-an-observation",
                            "present": True,
                            "qualifier": None,
                        }
                    ]
                )
            ),
            "enum",
            "observations",
        ),
        (
            json.dumps(
                _proposal_payload(
                    references=[
                            {
                                "kind": "current_item",
                                "ordinal": 1,
                                "raw_text": "这款",
                                "start": 0,
                                "end": 2,
                            }
                    ]
                )
            ),
            "cross_field",
            "references",
        ),
        (
            json.dumps(_proposal_payload(confidence=2.0)),
            "bounds",
            "confidence",
        ),
        (
            json.dumps(
                _proposal_payload(
                    references=[
                            {
                                "kind": "current_item",
                                "ordinal": None,
                                "raw_text": "这款",
                                "start": 0,
                                "end": 2,
                            }
                    ]
                    * 5
                )
            ),
            "cardinality",
            "references",
        ),
        (
            json.dumps(
                _proposal_payload(
                    clarification_hint="not-a-hint"
                )
            ),
            "enum",
            "clarification_hint",
        ),
    ),
)
def test_schema_failure_exposes_only_closed_typed_diagnostic(
    content: str,
    expected_kind: str,
    expected_path: str,
) -> None:
    secret_marker = "schema-secret-value-must-not-leak"
    content = content.replace("not-a-", f"{secret_marker}-")
    adapter = _adapter(
        lambda request: _success_response(content=content),
        format_repair_attempts=0,
    )

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    failure = caught.value
    diagnostic = failure.diagnostic
    assert failure.code in {
        SemanticProviderFailureCode.INVALID_OUTPUT,
        SemanticProviderFailureCode.FORBIDDEN_OUTPUT,
    }
    assert diagnostic is not None
    assert diagnostic.stage.value == "primary"
    assert diagnostic.kind.value == expected_kind
    assert diagnostic.path.value == expected_path
    assert diagnostic.count >= 1
    assert diagnostic.truncated is False
    assert diagnostic.repair_outcome.value == "not_attempted"
    serialized = diagnostic.model_dump_json()
    assert secret_marker not in serialized
    assert "private_output_key" not in serialized
    assert all(
        forbidden not in serialized
        for forbidden in ('"input"', '"msg"', '"ctx"', '"key"')
    )
    _assert_clean_provider_failure(
        failure,
        TEST_API_KEY,
        TEST_MESSAGE,
        secret_marker,
        "private_output_key",
    )


def test_schema_diagnostic_records_failed_repair_and_truncation() -> None:
    secret_marker = "many-schema-errors-must-not-leak"
    invalid = _proposal_payload(
        observations=[
            {
                "code": secret_marker,
                "present": True,
                "qualifier": None,
            }
            for _ in range(16)
        ]
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response(content=json.dumps(invalid))

    adapter = _adapter(handler, format_repair_attempts=1)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    diagnostic = caught.value.diagnostic
    assert calls == 2
    assert diagnostic is not None
    assert diagnostic.stage.value == "repair"
    assert diagnostic.kind.value == "enum"
    assert diagnostic.path.value == "observations"
    assert diagnostic.count == 16
    assert diagnostic.truncated is True
    assert diagnostic.repair_outcome.value == "failed"
    assert secret_marker not in diagnostic.model_dump_json()


@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(200, content=b""),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": "  "}}]},
        ),
    ),
)
def test_adapter_fails_closed_on_empty_response(
    response: httpx.Response,
) -> None:
    adapter = _adapter(lambda request: response)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.EMPTY_RESPONSE


def test_invalid_json_gets_exactly_one_fresh_format_repair() -> None:
    request_bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_bodies.append(request.read().decode("utf-8"))
        if len(request_bodies) == 1:
            return _success_response(content="{invalid-json")
        return _success_response()

    adapter = _adapter(handler, format_repair_attempts=1)

    result = adapter.propose(TEST_MESSAGE, _context())

    assert result.topic is TopicCode.FRAGRANCE
    assert len(request_bodies) == 2
    assert "{invalid-json" not in request_bodies[1]
    assert "format repair" in request_bodies[1].casefold()


def test_format_repair_receives_only_closed_primary_failure_kind_and_path(
) -> None:
    private_value = "private-reference-value-must-not-leak"
    request_bodies: list[str] = []
    invalid = _proposal_payload(
        references=[
            {
                "kind": "current_item",
                "ordinal": private_value,
            }
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        request_bodies.append(request.read().decode("utf-8"))
        if len(request_bodies) == 1:
            return _success_response(content=json.dumps(invalid))
        return _success_response()

    adapter = _adapter(handler, format_repair_attempts=1)

    result = adapter.propose(TEST_MESSAGE, _context())

    repair_body = request_bodies[1]
    assert result.topic is TopicCode.FRAGRANCE
    assert "failure kind=type" in repair_body
    assert "failure path=references" in repair_body
    assert private_value not in repair_body
    assert json.dumps(invalid) not in repair_body


def test_invalid_json_after_one_repair_returns_typed_failure() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response(content="{invalid-json")

    adapter = _adapter(handler, format_repair_attempts=1)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT
    assert calls == 2


def test_format_repair_can_be_disabled() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response(content="{invalid-json")

    adapter = _adapter(handler, format_repair_attempts=0)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT
    assert calls == 1


def test_forbidden_output_is_rejected_without_format_retry() -> None:
    calls = 0
    forbidden = _proposal_payload(product_ids=[42])

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response(content=json.dumps(forbidden))

    adapter = _adapter(handler, format_repair_attempts=1)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.FORBIDDEN_OUTPUT
    assert calls == 1


def test_strict_schema_rejects_coercible_values_after_one_repair() -> None:
    calls = 0
    invalid = _proposal_payload(confidence="0.97")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response(content=json.dumps(invalid))

    adapter = _adapter(handler)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT
    assert calls == 2


def test_daily_call_cap_counts_outbound_requests() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response()

    adapter = _adapter(handler, daily_call_cap=1)
    assert adapter.propose(TEST_MESSAGE, _context()).topic is TopicCode.FRAGRANCE

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.DAILY_CALL_CAP_EXCEEDED
    assert calls == 1


def test_daily_budget_blocks_after_reported_actual_cost() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response(
            usage={
                "prompt_tokens": 40,
                "completion_tokens": 25,
                "total_tokens": 65,
                "cost_cny": "0.50",
            }
        )

    adapter = _adapter(
        handler,
        daily_budget_cny=Decimal("0.50"),
        daily_call_cap=100,
    )
    assert adapter.propose(TEST_MESSAGE, _context()).topic is TopicCode.FRAGRANCE

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert caught.value.code is SemanticProviderFailureCode.DAILY_BUDGET_EXCEEDED
    assert calls == 1


def test_actual_cost_below_reservation_releases_unused_budget() -> None:
    reported_costs = iter(("0", "0.60", "0"))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response(
            usage={
                "prompt_tokens": 40,
                "completion_tokens": 25,
                "total_tokens": 65,
                "cost_cny": next(reported_costs),
            }
        )

    adapter = _adapter(
        handler,
        daily_budget_cny=Decimal("1.00"),
        daily_call_cap=3,
    )

    results = [
        adapter.propose(TEST_MESSAGE, _context())
        for _ in range(3)
    ]

    assert [result.topic for result in results] == [
        TopicCode.FRAGRANCE,
        TopicCode.FRAGRANCE,
        TopicCode.FRAGRANCE,
    ]
    assert calls == 3


def test_daily_limits_reset_on_utc_date_change() -> None:
    now = [datetime(2026, 8, 11, 23, 59, tzinfo=UTC)]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response()

    adapter = _adapter(
        handler,
        daily_call_cap=1,
        clock=lambda: now[0],
    )
    adapter.propose(TEST_MESSAGE, _context())
    now[0] = datetime(2026, 8, 12, 0, 0, tzinfo=UTC)

    adapter.propose(TEST_MESSAGE, _context())

    assert calls == 2


def test_concurrent_budget_reservations_cannot_overspend() -> None:
    calls = 0
    calls_lock = Lock()
    first_request_entered = Event()
    concurrent_request_entered = Event()
    release_requests = Event()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_request_entered.set()
        else:
            concurrent_request_entered.set()
        release_requests.wait(timeout=2)
        return _success_response(
            usage={
                "prompt_tokens": 40,
                "completion_tokens": 25,
                "total_tokens": 65,
                "cost_cny": "0.20",
            }
        )

    adapter = _adapter(
        handler,
        daily_budget_cny=Decimal("1.00"),
        daily_call_cap=100,
    )

    def invoke() -> TopicCode | SemanticProviderFailureCode:
        try:
            return adapter.propose(TEST_MESSAGE, _context()).topic
        except SemanticProviderFailure as failure:
            return failure.code

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(invoke) for _ in range(10)]
        assert first_request_entered.wait(timeout=1)
        overlapped = concurrent_request_entered.wait(timeout=0.25)
        release_requests.set()
        outcomes = [future.result(timeout=3) for future in futures]

    assert not overlapped
    assert calls == 5
    assert outcomes.count(TopicCode.FRAGRANCE) == 5
    assert outcomes.count(
        SemanticProviderFailureCode.DAILY_BUDGET_EXCEEDED
    ) == 5


def test_stale_clock_read_cannot_roll_limiter_day_backward() -> None:
    stale_clock_entered = Event()
    release_stale_clock = Event()
    current_request_finished = Event()
    failures: list[BaseException] = []
    calls = 0
    calls_lock = Lock()

    def clock() -> datetime:
        if current_thread().name == "stale-day-reservation":
            stale_clock_entered.set()
            release_stale_clock.wait(timeout=2)
            return datetime(2026, 8, 11, 23, 59, tzinfo=UTC)
        return datetime(2026, 8, 12, 0, 0, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with calls_lock:
            calls += 1
        return _success_response()

    adapter = _adapter(handler, daily_call_cap=1, clock=clock)

    def invoke(*, mark_current_finished: bool = False) -> None:
        try:
            adapter.propose(TEST_MESSAGE, _context())
        except BaseException as error:
            failures.append(error)
        finally:
            if mark_current_finished:
                current_request_finished.set()

    stale_thread = Thread(
        target=invoke,
        name="stale-day-reservation",
    )
    current_thread_worker = Thread(
        target=lambda: invoke(mark_current_finished=True),
        name="current-day-reservation",
    )
    stale_thread.start()
    assert stale_clock_entered.wait(timeout=1)
    current_thread_worker.start()
    current_request_finished.wait(timeout=0.25)
    release_stale_clock.set()
    stale_thread.join(timeout=2)
    current_thread_worker.join(timeout=2)

    assert not stale_thread.is_alive()
    assert not current_thread_worker.is_alive()
    assert failures == []
    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(TEST_MESSAGE, _context())

    assert (
        caught.value.code
        is SemanticProviderFailureCode.DAILY_CALL_CAP_EXCEEDED
    )
    assert calls == 2


@pytest.mark.parametrize(
    "provider_trace_id",
    (
        TEST_API_KEY,
        "user-private-message",
        PROVIDER_ERROR_BODY,
    ),
)
def test_success_logs_never_echo_provider_trace_id(
    provider_trace_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _adapter(
        lambda request: _success_response(
            headers={"x-request-id": provider_trace_id},
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.guide.adapters.llm.siliconflow_intent",
    ):
        adapter.propose(TEST_MESSAGE, _context())

    assert provider_trace_id not in caplog.text
    assert "trace_id=" in caplog.text


def test_overlong_provider_trace_id_is_discarded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider_trace_id = "x" * 65
    adapter = _adapter(
        lambda request: _success_response(
            headers={"x-request-id": provider_trace_id},
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.guide.adapters.llm.siliconflow_intent",
    ):
        adapter.propose(TEST_MESSAGE, _context())

    assert provider_trace_id not in caplog.text
    assert "trace_id=unavailable" in caplog.text


def test_logs_and_failures_do_not_expose_sensitive_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_profile_marker = "sensitive-profile-value"
    private_message = f"{TEST_MESSAGE} {private_profile_marker}"
    adapter = _adapter(
        lambda request: httpx.Response(
            500,
            json={"error": PROVIDER_ERROR_BODY},
            headers={"x-request-id": "trace-private-provider-body"},
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger="app.guide.adapters.llm.siliconflow_intent",
    ):
        with pytest.raises(SemanticProviderFailure):
            adapter.propose(private_message, _context())

    log_blob = caplog.text
    assert TEST_API_KEY not in log_blob
    assert private_message not in log_blob
    assert private_profile_marker not in log_blob
    assert PROVIDER_ERROR_BODY not in log_blob
    assert "trace-private-provider-body" not in log_blob
    assert SemanticProviderFailureCode.PROVIDER_UNAVAILABLE.value in log_blob
