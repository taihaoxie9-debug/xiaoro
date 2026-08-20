from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tools.guide_gates.two_stage_intent_gate import (
    TwoStageGateRow,
    summarize,
    summarize_smoke,
)


_FIXTURE_ROOT = Path("tests/fixtures/guide/intent")


def _row(
    case_id: str,
    *,
    route_critical_match: bool = True,
    detail_key_match: bool | None = True,
    fail_closed_clarification: bool = False,
    safe_clarification_mismatch_count: int = 0,
    unsafe_task_plan_mismatch_count: int = 0,
    hard_constraint_override_count: int = 0,
    unauthorized_constraint_transition_count: int = 0,
    forbidden_field_acceptance_count: int = 0,
    invalid_output_task_plan_invocation_count: int = 0,
    wrong_product_selection_count: int = 0,
    legacy_fallback_count: int = 0,
) -> TwoStageGateRow:
    return TwoStageGateRow(
        case_id=case_id,
        model="offline/mock",
        route_schema_valid=route_critical_match,
        route_critical_match=route_critical_match,
        detail_schema_valid=(
            None if detail_key_match is None else detail_key_match
        ),
        detail_key_match=detail_key_match,
        fail_closed_clarification=fail_closed_clarification,
        safe_clarification_mismatch_count=(
            safe_clarification_mismatch_count
        ),
        unsafe_task_plan_mismatch_count=(
            unsafe_task_plan_mismatch_count
        ),
        hard_constraint_override_count=hard_constraint_override_count,
        unauthorized_constraint_transition_count=(
            unauthorized_constraint_transition_count
        ),
        forbidden_field_acceptance_count=(
            forbidden_field_acceptance_count
        ),
        invalid_output_task_plan_invocation_count=(
            invalid_output_task_plan_invocation_count
        ),
        wrong_product_selection_count=wrong_product_selection_count,
        legacy_fallback_count=legacy_fallback_count,
    )


def test_optional_detail_difference_does_not_fail_hard_gates() -> None:
    rows = [_row(f"case-{index:03d}") for index in range(128)]
    rows[0] = _row("case-000", detail_key_match=False)

    summary = summarize(rows)

    assert summary.route_critical_rate == 1.0
    assert summary.hard_gates_passed is True
    assert summary.detail_key_rate > 0.90
    assert summary.passed is True
    assert summary.stop_reason is None


def test_wrong_task_plan_is_always_hard_failure() -> None:
    rows = [_row(f"case-{index:03d}") for index in range(128)]
    rows[0] = _row(
        "case-000",
        unsafe_task_plan_mismatch_count=1,
    )

    summary = summarize(rows)

    assert summary.unsafe_task_plan_mismatch_count == 1
    assert summary.hard_gates_passed is False
    assert summary.passed is False


def test_unauthorized_constraint_transition_is_hard_failure() -> None:
    rows = [_row(f"case-{index:03d}") for index in range(128)]
    rows[0] = _row(
        "case-000",
        unauthorized_constraint_transition_count=1,
    )

    summary = summarize(rows)

    assert summary.unauthorized_constraint_transition_count == 1
    assert summary.hard_gates_passed is False
    assert summary.passed is False


@pytest.mark.parametrize(
    "updates",
    [
        {
            "route_schema_valid": False,
            "route_critical_match": True,
        },
        {
            "detail_schema_valid": False,
            "detail_key_match": True,
        },
        {
            "fail_closed_clarification": False,
            "safe_clarification_mismatch_count": 1,
        },
        {
            "fail_closed_clarification": True,
            "unsafe_task_plan_mismatch_count": 1,
        },
    ],
)
def test_gate_row_rejects_internally_inconsistent_evidence(
    updates: dict[str, object],
) -> None:
    payload = _row("case-000").model_dump(mode="python")
    payload.update(updates)

    with pytest.raises(ValidationError):
        TwoStageGateRow.model_validate(payload, strict=True)


def test_128_gate_allows_quality_mismatches_only_when_fail_closed() -> None:
    rows = [_row(f"case-{index:03d}") for index in range(128)]
    for index in range(6):
        rows[index] = _row(
            f"case-{index:03d}",
            route_critical_match=False,
            detail_key_match=None,
            fail_closed_clarification=True,
            safe_clarification_mismatch_count=1,
        )
    for index in range(6, 18):
        rows[index] = _row(
            f"case-{index:03d}",
            detail_key_match=False,
            fail_closed_clarification=True,
            safe_clarification_mismatch_count=1,
        )

    summary = summarize(rows)

    assert summary.route_critical_rate == 122 / 128
    assert summary.detail_key_rate == 110 / 122
    assert summary.safe_clarification_mismatch_count == 18
    assert summary.all_failed_cases_fail_closed is True
    assert summary.passed is True


def test_128_gate_enforces_route_and_detail_quality_thresholds() -> None:
    route_rows = [_row(f"route-{index:03d}") for index in range(128)]
    for index in range(7):
        route_rows[index] = _row(
            f"route-{index:03d}",
            route_critical_match=False,
            detail_key_match=None,
            fail_closed_clarification=True,
            safe_clarification_mismatch_count=1,
        )
    assert summarize(route_rows).stop_reason == "route_quality"

    detail_rows = [_row(f"detail-{index:03d}") for index in range(128)]
    for index in range(13):
        detail_rows[index] = _row(
            f"detail-{index:03d}",
            detail_key_match=False,
            fail_closed_clarification=True,
            safe_clarification_mismatch_count=1,
        )
    assert summarize(detail_rows).stop_reason == "detail_quality"


def test_smoke_stops_below_85_percent_and_allows_safe_clarification() -> None:
    passing = [_row(f"case-{index:03d}") for index in range(32)]
    for index in range(4):
        passing[index] = _row(
            f"case-{index:03d}",
            route_critical_match=False,
            detail_key_match=None,
            fail_closed_clarification=True,
            safe_clarification_mismatch_count=1,
        )
    passing_summary = summarize_smoke(passing)
    assert passing_summary.route_critical_rate == 0.875
    assert passing_summary.passed is True

    failing = list(passing)
    failing[4] = _row(
        "case-004",
        route_critical_match=False,
        detail_key_match=None,
        fail_closed_clarification=True,
        safe_clarification_mismatch_count=1,
    )
    failing_summary = summarize_smoke(failing)
    assert failing_summary.route_critical_rate == 0.84375
    assert failing_summary.passed is False
    assert failing_summary.stop_reason == "route_quality"


def test_smoke_stops_on_any_hard_gate_failure() -> None:
    rows = [_row(f"case-{index:03d}") for index in range(32)]
    rows[0] = _row(
        "case-000",
        legacy_fallback_count=1,
    )

    summary = summarize_smoke(rows)

    assert summary.hard_gates_passed is False
    assert summary.passed is False
    assert summary.stop_reason == "hard_gate"


def test_frozen_smoke_manifest_matches_32_unique_fixture_rows() -> None:
    fixture_path = _FIXTURE_ROOT / "two_stage_smoke_v1.jsonl"
    manifest_path = (
        _FIXTURE_ROOT / "two_stage_smoke_v1_manifest.json"
    )
    fixture_bytes = fixture_path.read_bytes()
    rows = [
        json.loads(line)
        for line in fixture_bytes.decode("utf-8").splitlines()
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_ids = [row["case_id"] for row in rows]
    source_path = _FIXTURE_ROOT / manifest["source_fixture"]
    source_bytes = source_path.read_bytes()
    source_by_id = {
        row["case_id"]: row
        for row in (
            json.loads(line)
            for line in source_bytes.decode("utf-8").splitlines()
        )
    }

    assert len(rows) == 32
    assert len(case_ids) == len(set(case_ids))
    assert manifest["case_ids"] == case_ids
    assert manifest["smoke_sha256"] == hashlib.sha256(
        fixture_bytes
    ).hexdigest()
    assert manifest["source_sha256"] == hashlib.sha256(
        source_bytes
    ).hexdigest()
    assert rows == [source_by_id[case_id] for case_id in case_ids]
