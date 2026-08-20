from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path

import httpx

from app.guide.adapters.llm.siliconflow_two_stage_intent import (
    SiliconFlowTwoStageIntentAdapter,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from tools.guide_gates.two_stage_intent_gate import (
    TwoStageGateRow,
    summarize_smoke,
)


_FIXTURE = Path(
    "tests/fixtures/guide/intent/two_stage_smoke_v1.jsonl"
)
_STAGE_BY_GOAL = {
    "recommendation": "recommendation",
    "comparison": "comparison",
    "suitability": "assessment",
    "assessment": "assessment",
    "followup": "followup",
    "knowledge": "knowledge",
    "image_similarity": "image",
    "clarification": "none",
}


class _SequenceTransport(httpx.BaseTransport):
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self._payloads = iter(payloads)
        self.request_count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        del request
        self.request_count += 1
        payload = next(self._payloads)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                payload,
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )


def _route_payload(expected: dict[str, object]) -> dict[str, object]:
    goal = expected["goal"]
    assert isinstance(goal, str)
    return {
        "goal": goal,
        "topic": expected["topic"],
        "detail_stage": _STAGE_BY_GOAL[goal],
        "confidence": 0.99,
        "clarification_hint": (
            "goal" if goal == "clarification" else None
        ),
    }


def _detail_payload(expected: dict[str, object]) -> dict[str, object]:
    stage = _STAGE_BY_GOAL[str(expected["goal"])]
    fields_by_stage = {
        "recommendation": ("concerns", "observations"),
        "assessment": ("concerns", "observations"),
        "comparison": ("references",),
        "followup": ("references",),
        "knowledge": ("concerns",),
        "image": ("references", "observations"),
    }
    return {
        field: expected.get(field, [])
        for field in fields_by_stage[stage]
    }


def _canonical(value: object) -> object:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def test_32_case_offline_mock_smoke_passes_route_and_detail_gates() -> None:
    cases = [
        json.loads(line)
        for line in _FIXTURE.read_text(encoding="utf-8").splitlines()
    ]
    rows: list[TwoStageGateRow] = []
    request_count = 0

    for case in cases:
        expected = case["expected"]
        payloads = [_route_payload(expected)]
        if expected["goal"] != "clarification":
            payloads.append(_detail_payload(expected))
        transport = _SequenceTransport(payloads)
        context = SemanticContext.model_validate_json(
            json.dumps(case["context"]),
            strict=True,
        )
        adapter = SiliconFlowTwoStageIntentAdapter(
            api_key="offline-smoke-test-key-not-real",
            base_url="https://example.invalid/v1",
            model="offline/mock",
            timeout_seconds=1.0,
            max_tokens=128,
            enable_thinking=False,
            format_repair_attempts=1,
            daily_budget_cny=Decimal("1"),
            daily_call_cap=3,
            transport=transport,
            clock=lambda: datetime(2026, 8, 13, tzinfo=UTC),
        )
        proposal = adapter.propose(case["message"], context)
        request_count += transport.request_count
        actual_topic = (
            proposal.topic.value
            if proposal.topic is not None
            else None
        )
        route_match = (
            proposal.goal.value == expected["goal"]
            and actual_topic == expected["topic"]
            and (
                proposal.goal.value == "clarification"
            ) == expected["must_clarify"]
        )
        if proposal.goal.value == "clarification":
            detail_match = None
            detail_schema_valid = None
        else:
            proposal_payload = proposal.model_dump(mode="json")
            actual_detail = {
                "concerns": proposal_payload["concerns"],
                "observations": proposal_payload["observations"],
                "references": proposal_payload["references"],
            }
            expected_detail = {
                "concerns": expected.get("concerns", []),
                "observations": expected.get("observations", []),
                "references": expected.get("references", []),
            }
            detail_match = _canonical(actual_detail) == _canonical(
                expected_detail
            )
            detail_schema_valid = True
        rows.append(
            TwoStageGateRow(
                case_id=case["case_id"],
                model="offline/mock",
                route_schema_valid=True,
                route_critical_match=route_match,
                detail_schema_valid=detail_schema_valid,
                detail_key_match=detail_match,
                fail_closed_clarification=False,
                safe_clarification_mismatch_count=0,
                unsafe_task_plan_mismatch_count=0,
                hard_constraint_override_count=0,
                unauthorized_constraint_transition_count=0,
                forbidden_field_acceptance_count=0,
                invalid_output_task_plan_invocation_count=0,
                wrong_product_selection_count=0,
                legacy_fallback_count=0,
            )
        )

    summary = summarize_smoke(rows)

    assert request_count == 58
    assert summary.case_count == 32
    assert summary.route_critical_match_count == 32
    assert summary.route_critical_rate == 1.0
    assert summary.detail_evaluated_count == 26
    assert summary.detail_key_match_count == 26
    assert summary.detail_key_rate == 1.0
    assert summary.hard_gates_passed is True
    assert summary.passed is True
