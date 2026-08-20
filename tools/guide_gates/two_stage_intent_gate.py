from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class TwoStageGateRow(_StrictModel):
    case_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    route_schema_valid: bool
    route_critical_match: bool
    detail_schema_valid: bool | None
    detail_key_match: bool | None
    fail_closed_clarification: bool
    safe_clarification_mismatch_count: int = Field(ge=0)
    unsafe_task_plan_mismatch_count: int = Field(ge=0)
    hard_constraint_override_count: int = Field(ge=0)
    unauthorized_constraint_transition_count: int = Field(ge=0)
    forbidden_field_acceptance_count: int = Field(ge=0)
    invalid_output_task_plan_invocation_count: int = Field(ge=0)
    wrong_product_selection_count: int = Field(ge=0)
    legacy_fallback_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_evidence_consistency(self) -> Self:
        if self.route_critical_match and not self.route_schema_valid:
            raise ValueError("route match requires a valid route schema")
        if (self.detail_schema_valid is None) != (
            self.detail_key_match is None
        ):
            raise ValueError(
                "detail schema and key evidence must be jointly available"
            )
        if (
            self.detail_key_match is True
            and self.detail_schema_valid is not True
        ):
            raise ValueError(
                "detail match requires a valid detail schema"
            )
        if self.safe_clarification_mismatch_count > 0 and (
            not self.fail_closed_clarification
            or self.unsafe_task_plan_mismatch_count > 0
        ):
            raise ValueError(
                "safe mismatch requires fail-closed clarification"
            )
        if self.unsafe_task_plan_mismatch_count > 0 and (
            self.fail_closed_clarification
            or self.safe_clarification_mismatch_count > 0
        ):
            raise ValueError(
                "unsafe TaskPlan mismatch cannot be fail-closed"
            )
        return self


class TwoStageGateSummary(_StrictModel):
    case_count: int = Field(ge=0)
    route_critical_match_count: int = Field(ge=0)
    route_critical_rate: float = Field(ge=0.0, le=1.0)
    detail_evaluated_count: int = Field(ge=0)
    detail_key_match_count: int = Field(ge=0)
    detail_key_rate: float = Field(ge=0.0, le=1.0)
    all_failed_cases_fail_closed: bool
    safe_clarification_mismatch_count: int = Field(ge=0)
    unsafe_task_plan_mismatch_count: int = Field(ge=0)
    hard_constraint_override_count: int = Field(ge=0)
    unauthorized_constraint_transition_count: int = Field(ge=0)
    forbidden_field_acceptance_count: int = Field(ge=0)
    invalid_output_task_plan_invocation_count: int = Field(ge=0)
    wrong_product_selection_count: int = Field(ge=0)
    legacy_fallback_count: int = Field(ge=0)
    hard_gates_passed: bool
    passed: bool
    stop_reason: Literal[
        "case_count",
        "hard_gate",
        "unsafe_failure",
        "route_quality",
        "detail_quality",
    ] | None


def summarize(
    rows: Sequence[TwoStageGateRow],
) -> TwoStageGateSummary:
    return _summarize(
        rows,
        expected_case_count=None,
        minimum_case_count=120,
        route_threshold=0.95,
        detail_threshold=0.90,
        require_detail_quality=True,
    )


def summarize_smoke(
    rows: Sequence[TwoStageGateRow],
) -> TwoStageGateSummary:
    return _summarize(
        rows,
        expected_case_count=32,
        minimum_case_count=32,
        route_threshold=0.85,
        detail_threshold=0.0,
        require_detail_quality=False,
    )


def _summarize(
    rows: Sequence[TwoStageGateRow],
    *,
    expected_case_count: int | None,
    minimum_case_count: int,
    route_threshold: float,
    detail_threshold: float,
    require_detail_quality: bool,
) -> TwoStageGateSummary:
    normalized = tuple(rows)
    if any(not isinstance(row, TwoStageGateRow) for row in normalized):
        raise TypeError("rows must contain TwoStageGateRow values")
    case_ids = [row.case_id for row in normalized]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("gate case IDs must be unique")

    case_count = len(normalized)
    route_match_count = sum(
        int(row.route_critical_match)
        for row in normalized
    )
    route_rate = _rate(route_match_count, case_count)
    detail_rows = [
        row
        for row in normalized
        if row.detail_key_match is not None
    ]
    detail_match_count = sum(
        int(row.detail_key_match is True)
        for row in detail_rows
    )
    detail_rate = _rate(detail_match_count, len(detail_rows))
    failed_rows = [
        row
        for row in normalized
        if row.safe_clarification_mismatch_count > 0
        or row.unsafe_task_plan_mismatch_count > 0
    ]
    all_failed_cases_fail_closed = all(
        row.fail_closed_clarification
        and row.safe_clarification_mismatch_count > 0
        and row.unsafe_task_plan_mismatch_count == 0
        for row in failed_rows
    )

    totals = {
        field_name: sum(
            getattr(row, field_name)
            for row in normalized
        )
        for field_name in (
            "safe_clarification_mismatch_count",
            "unsafe_task_plan_mismatch_count",
            "hard_constraint_override_count",
            "unauthorized_constraint_transition_count",
            "forbidden_field_acceptance_count",
            "invalid_output_task_plan_invocation_count",
            "wrong_product_selection_count",
            "legacy_fallback_count",
        )
    }
    hard_gates_passed = all(
        totals[field_name] == 0
        for field_name in (
            "unsafe_task_plan_mismatch_count",
            "hard_constraint_override_count",
            "unauthorized_constraint_transition_count",
            "forbidden_field_acceptance_count",
            "invalid_output_task_plan_invocation_count",
            "wrong_product_selection_count",
            "legacy_fallback_count",
        )
    )
    count_passed = (
        case_count >= minimum_case_count
        and (
            expected_case_count is None
            or case_count == expected_case_count
        )
    )
    route_passed = route_rate >= route_threshold
    detail_passed = (
        not require_detail_quality
        or detail_rate >= detail_threshold
    )
    passed = (
        count_passed
        and hard_gates_passed
        and all_failed_cases_fail_closed
        and route_passed
        and detail_passed
    )
    stop_reason = None
    if not count_passed:
        stop_reason = "case_count"
    elif not hard_gates_passed:
        stop_reason = "hard_gate"
    elif not all_failed_cases_fail_closed:
        stop_reason = "unsafe_failure"
    elif not route_passed:
        stop_reason = "route_quality"
    elif not detail_passed:
        stop_reason = "detail_quality"

    return TwoStageGateSummary(
        case_count=case_count,
        route_critical_match_count=route_match_count,
        route_critical_rate=route_rate,
        detail_evaluated_count=len(detail_rows),
        detail_key_match_count=detail_match_count,
        detail_key_rate=detail_rate,
        all_failed_cases_fail_closed=all_failed_cases_fail_closed,
        hard_gates_passed=hard_gates_passed,
        passed=passed,
        stop_reason=stop_reason,
        **totals,
    )


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


__all__ = [
    "TwoStageGateRow",
    "TwoStageGateSummary",
    "summarize",
    "summarize_smoke",
]
