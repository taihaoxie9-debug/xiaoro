from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import json

import httpx
import pytest

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.adapters.llm.siliconflow_turn_meaning import (
    SiliconFlowTurnMeaningAdapter,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide_runtime.llm_config import GuideLlmConfig


def _payload() -> dict[str, object]:
    return {
        "operation_hint": "knowledge",
        "recommendation_mode": None,
        "recommendation_count": None,
        "recommendation_mode_basis": None,
        "topic_hint": "skincare",
        "continuity_hint": "new_task",
        "subject_scope_hint": "self",
        "pending_response_hint": "unknown",
        "reference_mentions": [],
        "product_mentions": [],
        "budget_candidates": [],
        "observation_candidates": [],
        "preference_candidates": [],
        "constraint_changes": [],
        "relative_candidates": [],
        "knowledge_relation_hints": [],
        "consultation_hypothesis": None,
        "next_observation_gap": None,
        "question_meaning": "询问烟酰胺作用",
        "safety_language": "ordinary",
    }


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
                "prompt_tokens": 30,
                "completion_tokens": 12,
                "total_tokens": 42,
            },
        },
    )


def _config() -> GuideLlmConfig:
    return GuideLlmConfig(
        api_key="not-a-real-key",
        base_url="https://example.invalid/v1",
        model="provider/model",
        timeout_seconds=2.0,
        max_tokens=256,
        daily_budget_cny=Decimal("1"),
        daily_call_cap=100,
        format_repair_attempts=0,
        enable_thinking=False,
    )


def _context() -> SemanticContext:
    return SemanticContext(
        conversation_version=0,
        active_topic=None,
        visible_candidate_count=0,
        confirmed_profile_fields=(),
    )


def test_siliconflow_from_config_uses_one_non_thinking_request() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return _response()

    adapter = SiliconFlowTurnMeaningAdapter.from_config(
        _config(),
        concept_catalog=(
            "efficacy.soothing",
            "texture.refreshing",
        ),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )

    meaning = adapter.propose(
        "烟酰胺有什么作用",
        _context(),
    )

    assert meaning.operation_hint == "knowledge"
    assert len(requests) == 1
    assert requests[0]["enable_thinking"] is False
    assert "thinking" not in requests[0]
    assert requests[0]["stream"] is False


def test_siliconflow_rejects_repair_enabled_config() -> None:
    config = replace(_config(), format_repair_attempts=1)

    with pytest.raises(ValueError, match="repair"):
        SiliconFlowTurnMeaningAdapter.from_config(
            config,
            concept_catalog=("texture.refreshing",),
        )


def test_siliconflow_invalid_json_does_not_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response("{not-json")

    adapter = SiliconFlowTurnMeaningAdapter.from_config(
        _config(),
        concept_catalog=("texture.refreshing",),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.propose(
            "烟酰胺有什么作用",
            _context(),
        )

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT
    assert calls == 1
