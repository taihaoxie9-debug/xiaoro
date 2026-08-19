from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path

import httpx
import pytest

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.adapters.llm.intent_cache import IntentProposalCache
from app.guide.adapters.llm.siliconflow_two_stage_intent import (
    SiliconFlowTwoStageIntentAdapter,
)
from app.guide.intent.task_planning import plan_task
from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.parallel_understanding import (
    ParallelUnderstanding,
)
from app.guide.understanding.semantic_contracts import (
    ConcernCode,
    SemanticContext,
)


_API_KEY = "two-stage-test-key-not-real"
_MODEL = "provider/two-stage-test"


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
        responses: Sequence[httpx.Response],
    ) -> None:
        self._responses = iter(responses)
        self.request_count = 0
        self.request_bodies: list[dict[str, object]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        self.request_bodies.append(json.loads(request.read()))
        try:
            response = next(self._responses)
        except StopIteration:
            raise AssertionError("unexpected provider request") from None
        return response


def _adapter(
    transport: httpx.BaseTransport,
    *,
    cache: IntentProposalCache | None = None,
    format_repair_attempts: int = 1,
) -> SiliconFlowTwoStageIntentAdapter:
    return SiliconFlowTwoStageIntentAdapter(
        api_key=_API_KEY,
        base_url="https://example.invalid/v1",
        model=_MODEL,
        timeout_seconds=2.0,
        max_tokens=128,
        enable_thinking=False,
        format_repair_attempts=format_repair_attempts,
        daily_budget_cny=Decimal("1"),
        daily_call_cap=100,
        transport=transport,
        clock=lambda: datetime(2026, 8, 13, tzinfo=UTC),
        cache=cache,
    )


def test_two_stage_adapter_projects_route_and_details_to_v3() -> None:
    transport = SequenceTransport(
        [_response(_route_payload()), _response(_detail_payload())]
    )

    result = _adapter(transport).propose_with_result(
        "推荐防晒",
        _context(),
    )

    assert result.proposal.goal is UnderstandingGoal.RECOMMENDATION
    assert result.proposal.topic is TopicCode.SUNSCREEN
    assert result.proposal.concerns == (ConcernCode.SUN_PROTECTION,)
    assert [item.stage for item in result.stage_usage] == [
        "route",
        "detail",
    ]
    assert all(not item.repair_used for item in result.stage_usage)
    assert transport.request_count == 2
    assert all(
        body["enable_thinking"] is False
        and body["temperature"] == 0
        and body["max_tokens"] == 128
        for body in transport.request_bodies
    )


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


def test_two_stages_share_one_format_repair_budget() -> None:
    transport = SequenceTransport(
        [
            _response("{invalid"),
            _response(_route_payload()),
            _response("{invalid"),
        ]
    )

    with pytest.raises(SemanticProviderFailure) as caught:
        _adapter(transport).propose("推荐防晒", _context())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT
    assert transport.request_count == 3


def test_detail_can_use_the_single_shared_repair() -> None:
    transport = SequenceTransport(
        [
            _response(_route_payload()),
            _response("{invalid"),
            _response(_detail_payload()),
        ]
    )

    result = _adapter(transport).propose_with_result(
        "推荐防晒",
        _context(),
    )

    assert transport.request_count == 3
    assert result.stage_usage[1].stage == "detail"
    assert result.stage_usage[1].repair_used is True


def test_forbidden_route_output_is_not_repaired() -> None:
    transport = SequenceTransport(
        [_response({**_route_payload(), "product_id": 7})]
    )

    with pytest.raises(SemanticProviderFailure) as caught:
        _adapter(transport).propose("推荐防晒", _context())

    assert caught.value.code is SemanticProviderFailureCode.FORBIDDEN_OUTPUT
    assert transport.request_count == 1


def test_provider_failure_reaches_task_planning_as_clarification() -> None:
    transport = SequenceTransport(
        [httpx.Response(503, json={"error": "private provider body"})]
    )

    understanding = ParallelUnderstanding(
        semantic=_adapter(transport)
    )
    result = understanding.understand(
        "推荐防晒",
        context=_context(),
    )

    assert transport.request_count == 1
    assert result.semantic_proposals == []
    assert plan_task(result).mode == "clarify"
    assert any(
        item.resolution == "semantic_unavailable"
        for item in result.signal_trace
    )


def test_validated_stages_are_cached_separately(
    tmp_path: Path,
) -> None:
    cache = IntentProposalCache(
        tmp_path / "intent.sqlite3",
        trusted_state_root=tmp_path,
    )
    transport = SequenceTransport(
        [_response(_route_payload()), _response(_detail_payload())]
    )
    adapter = _adapter(transport, cache=cache)

    first = adapter.propose("推荐防晒", _context())
    second = adapter.propose("推荐防晒", _context())

    assert first == second
    assert transport.request_count == 2
    assert cache.size() == 2


def test_failed_detail_is_not_cached_but_valid_route_is(
    tmp_path: Path,
) -> None:
    cache = IntentProposalCache(
        tmp_path / "intent.sqlite3",
        trusted_state_root=tmp_path,
    )
    failing_transport = SequenceTransport(
        [_response(_route_payload()), _response("{invalid")]
    )

    with pytest.raises(SemanticProviderFailure):
        _adapter(
            failing_transport,
            cache=cache,
            format_repair_attempts=0,
        ).propose("推荐防晒", _context())
    assert cache.size() == 1

    succeeding_transport = SequenceTransport(
        [_response(_detail_payload())]
    )
    proposal = _adapter(
        succeeding_transport,
        cache=cache,
        format_repair_attempts=0,
    ).propose("推荐防晒", _context())

    assert proposal.goal is UnderstandingGoal.RECOMMENDATION
    assert succeeding_transport.request_count == 1
    assert cache.size() == 2


def test_adapter_repr_never_contains_key() -> None:
    adapter = _adapter(SequenceTransport([]))
    assert _API_KEY not in repr(adapter)
