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
    _strict_turn_meaning_schema,
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
        "recommendation_mode": "explore",
        "recommendation_count": 3,
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
        "constraint_changes": [],
        "relative_candidates": [],
        "consultation_hypothesis": None,
        "next_observation_gap": None,
        "question_meaning": "推荐清爽防晒",
        "safety_language": "ordinary",
    }
    payload.update(updates)
    return payload


def _response(content: str | None = None) -> httpx.Response:
    arguments = content or json.dumps(_payload())
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_turn_meaning",
                                "type": "function",
                                "function": {
                                    "name": "emit_turn_meaning",
                                    "arguments": arguments,
                                },
                            }
                        ]
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
    assert "response_format" not in body
    assert body["tool_choice"] == {
        "type": "function",
        "function": {"name": "emit_turn_meaning"},
    }
    assert body["stream"] is False
    assert len(body["messages"]) == 2


def test_deepseek_turn_meaning_uses_strict_tool_arguments_contract() -> None:
    content = json.dumps(_payload(), ensure_ascii=False)
    transport = SequenceTransport([
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_turn_meaning",
                                    "type": "function",
                                    "function": {
                                        "name": "emit_turn_meaning",
                                        "arguments": content,
                                    },
                                }
                            ]
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
    ])
    adapter = _adapter(transport)

    result = adapter.propose_with_result(
        "推荐清爽防晒",
        _context(),
    )

    assert result.meaning.recommendation_mode == "explore"
    body = transport.bodies[0]
    assert "response_format" not in body
    assert body["tool_choice"] == {
        "type": "function",
        "function": {"name": "emit_turn_meaning"},
    }
    tool = body["tools"][0]["function"]
    assert tool["name"] == "emit_turn_meaning"
    assert tool["strict"] is True
    parameters = tool["parameters"]
    assert parameters["type"] == "object"
    assert parameters["additionalProperties"] is False
    variants = parameters["anyOf"]
    assert len(variants) == 4
    fit_variant = next(
        variant
        for variant in variants
        if variant["properties"]["recommendation_mode"].get("enum")
        == ["fit"]
    )
    assert fit_variant["properties"]["recommendation_count"] == {
        "enum": [1],
        "type": "integer",
    }
    assert set(
        fit_variant["properties"]["recommendation_mode_basis"][
            "properties"
        ]["basis"]["enum"]
    ) == {
        "single_best_request",
        "personal_suitability",
        "profile_match_choice",
        "best_among_candidates",
    }


def test_strict_tool_schema_scopes_image_similarity_explore_basis() -> None:
    schema = _strict_turn_meaning_schema()
    image_variants = [
        item
        for item in schema["anyOf"]
        if item["properties"].get("operation_hint", {}).get("enum")
        == ["image_similarity"]
        and item["properties"]["recommendation_mode"].get("enum")
        == ["explore"]
    ]

    assert len(image_variants) == 1
    assert image_variants[0]["properties"][
        "recommendation_mode_basis"
    ]["properties"]["basis"]["enum"] == ["similar_alternatives"]


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
        json.dumps({
            key: value
            for key, value in _payload().items()
            if key != "recommendation_mode"
        }),
        json.dumps({
            key: value
            for key, value in _payload().items()
            if key != "next_observation_gap"
        }),
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


def test_deepseek_rejects_ungrounded_recommendation_mode_basis() -> None:
    content = json.dumps(
        _payload(
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": "single_best_request",
                "source_text": "唯一最适合",
            },
        )
    )
    transport = SequenceTransport([_response(content)])
    adapter = _adapter(transport)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(
            "给我推荐 500 内的防晒",
            _context(),
        )

    assert (
        caught.value.code
        is SemanticProviderFailureCode.INVALID_OUTPUT
    )
    assert transport.request_count == 1


def test_deepseek_normalizes_unsupported_fit_to_explore_basis() -> None:
    content = json.dumps(
        _payload(
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": "single_best_request",
                "source_text": "给我推荐",
            },
            preference_candidates=[],
        )
    )
    transport = SequenceTransport([_response(content)])
    adapter = _adapter(transport)

    meaning = adapter.propose(
        "给我推荐 500 内的防晒",
        _context(),
    )

    assert meaning.recommendation_mode == "explore"
    assert meaning.recommendation_count is None
    assert meaning.recommendation_mode_basis is not None
    assert meaning.recommendation_mode_basis.basis == (
        "broad_exploration"
    )
    assert meaning.recommendation_mode_basis.source_text == "给我推荐"
    assert transport.request_count == 1


def test_deepseek_normalizes_fit_with_generic_recommendation_evidence() -> None:
    content = json.dumps(
        _payload(
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": "single_best_request",
                "source_text": "推荐",
            },
        )
    )
    transport = SequenceTransport([_response(content)])
    adapter = _adapter(transport)

    meaning = adapter.propose(
        "推荐清爽防晒",
        _context(),
    )

    assert meaning.recommendation_mode == "explore"
    assert meaning.recommendation_count is None
    assert meaning.recommendation_mode_basis is not None
    assert meaning.recommendation_mode_basis.basis == (
        "broad_exploration"
    )


def test_deepseek_normalizes_fit_when_basis_reuses_preference_evidence() -> None:
    content = json.dumps(
        _payload(
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": "single_best_request",
                "source_text": "推荐清爽",
            },
        )
    )
    transport = SequenceTransport([_response(content)])
    adapter = _adapter(transport)

    meaning = adapter.propose(
        "推荐清爽防晒",
        _context(),
    )

    assert meaning.recommendation_mode == "explore"
    assert meaning.recommendation_count is None
    assert meaning.recommendation_mode_basis is not None
    assert meaning.recommendation_mode_basis.basis == (
        "broad_exploration"
    )


@pytest.mark.parametrize(
    "basis",
    (
        "personal_suitability",
        "profile_match_choice",
        "best_among_candidates",
    ),
)
def test_deepseek_normalizes_fit_children_without_single_selection_evidence(
    basis: str,
) -> None:
    content = json.dumps(
        _payload(
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": basis,
                "source_text": "适合我用",
            },
        ),
        ensure_ascii=False,
    )
    transport = SequenceTransport([_response(content)])
    adapter = _adapter(transport)

    meaning = adapter.propose(
        "推荐清爽防晒，适合我用",
        _context(),
    )

    assert meaning.recommendation_mode == "explore"
    assert meaning.recommendation_count is None
    assert meaning.recommendation_mode_basis is not None
    assert meaning.recommendation_mode_basis.basis == (
        "broad_exploration"
    )


@pytest.mark.parametrize(
    ("source_text", "message"),
    (
        ("给我推荐", "给我推荐清爽防晒"),
        ("500", "预算500，给我推荐清爽防晒"),
        ("二款", "给我推荐二款清爽防晒"),
        ("٢款", "给我推荐٢款清爽防晒"),
        ("②款", "给我推荐②款清爽防晒"),
        ("四款", "给我推荐四款清爽防晒"),
    ),
)
def test_deepseek_normalizes_single_best_without_single_cardinality_evidence(
    source_text: str,
    message: str,
) -> None:
    content = json.dumps(
        _payload(
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": "single_best_request",
                "source_text": source_text,
            },
        )
    )
    transport = SequenceTransport([_response(content)])
    adapter = _adapter(transport)

    meaning = adapter.propose(
        message,
        _context(),
    )

    assert meaning.recommendation_mode == "explore"
    assert meaning.recommendation_count is None
    assert meaning.recommendation_mode_basis is not None
    assert meaning.recommendation_mode_basis.basis == (
        "broad_exploration"
    )


@pytest.mark.parametrize("source_text", ("一款", "１款"))
def test_deepseek_accepts_source_grounded_fit_with_usable_signal(
    source_text: str,
) -> None:
    content = json.dumps(
        _payload(
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": "single_best_request",
                "source_text": source_text,
            },
        )
    )
    transport = SequenceTransport([_response(content)])
    adapter = _adapter(transport)

    meaning = adapter.propose(
        f"给我推荐{source_text}最适合清爽肤感的防晒",
        _context(),
    )

    assert meaning.recommendation_mode == "fit"
    assert meaning.recommendation_mode_basis is not None
    assert meaning.recommendation_mode_basis.basis == (
        "single_best_request"
    )
    assert meaning.recommendation_mode_basis.source_text == source_text
    assert transport.request_count == 1
