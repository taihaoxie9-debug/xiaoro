"""Supervised real-model A/B entrypoint for two-stage Guide intent."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import os
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticStageUsage,
    TwoStageSemanticCallResult,
)
from app.guide.adapters.llm.siliconflow_two_stage_intent import (
    SiliconFlowTwoStageIntentAdapter,
)
from app.guide.intent.contracts import TaskPlan
from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.intent.task_planning import plan_task
from app.guide.intent.transition_planning import (
    plan_code_owned_transitions,
)
from app.guide.understanding.contracts import (
    StructuredUnderstanding,
    UnderstandingGoal,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_revision_confirmations,
)
from app.guide.understanding.semantic_contracts import (
    SemanticIntentProposal,
    SemanticLaneDisposition,
)
from app.guide.understanding.semantic_detail_contracts import (
    AssessmentDetails,
    ComparisonDetails,
    FollowupDetails,
    ImageDetails,
    KnowledgeDetails,
    RecommendationDetails,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticRouteProposal,
)
from app.guide_runtime.llm_config import (
    GuideLlmConfig,
    GuideLlmConfigError,
)
from tools.guide_gates.guide_pipeline_evaluator import (
    ModelVerticalEvaluator,
)
from tools.guide_gates.intent_model_ab import (
    IntentAbConfigurationError,
    IntentCase,
    IntentCaseError,
    MinimalTaskPlanEvaluator,
    PipelineEvaluation,
    PipelineEvaluationFailure,
    PipelineEvaluationRequest,
    PipelineEvaluator,
    PipelineExactInput,
)
from tools.guide_gates.private_output_io import OutputBindingError
from tools.guide_gates.real_ab_evidence import (
    CANONICAL_INTENT_INPUTS,
    FrozenInputs,
    PrivateEvidenceWriter,
    build_evidence_bundle,
    canonical_json_bytes,
    load_frozen_inputs,
    nearest_rank,
    sum_token_fields,
)
from tools.guide_gates.two_stage_intent_gate import (
    TwoStageGateRow,
    TwoStageGateSummary,
    summarize,
    summarize_smoke,
)


FLASH_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
BASELINE_MODEL = "deepseek-ai/DeepSeek-V3.2"
FROZEN_MODELS = (FLASH_MODEL, BASELINE_MODEL)

FROZEN_CASE_COUNT = CANONICAL_INTENT_INPUTS.case_count
FROZEN_CASE_FILE_SHA256 = CANONICAL_INTENT_INPUTS.case_file_sha256
FROZEN_CASE_MANIFEST_SHA256 = (
    CANONICAL_INTENT_INPUTS.case_manifest_sha256
)
FROZEN_SMOKE_COUNT = CANONICAL_INTENT_INPUTS.smoke_count
FROZEN_SMOKE_FILE_SHA256 = CANONICAL_INTENT_INPUTS.smoke_file_sha256
FROZEN_SMOKE_MANIFEST_SHA256 = (
    CANONICAL_INTENT_INPUTS.smoke_manifest_sha256
)

FROZEN_TIMEOUT_SECONDS = 12.0
FROZEN_STAGE_MAX_TOKENS = 128
FROZEN_FORMAT_REPAIR_ATTEMPTS = 1
PROVIDER_EARLY_STOP_CASE_COUNT = 20
PROVIDER_EARLY_STOP_RATE = 0.10
_ROUTE_REQUESTS_PER_CASE = 1
_DETAIL_REQUESTS_PER_CASE = 1
_DAILY_CALL_CAP_ENV = "GUIDE_LLM_DAILY_CALL_CAP"

_RUNNER_SCHEMA_VERSION = "guide-real-two-stage-intent-ab-v1"
_SUMMARY_SCHEMA_VERSION = "guide-real-two-stage-intent-ab-summary-v1"
_RUNTIME_SCHEMA_VERSION = "guide-real-two-stage-intent-ab-runtime-v1"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SMOKE_CASES = (
    _REPOSITORY_ROOT
    / "tests/fixtures/guide/intent/two_stage_smoke_v1.jsonl"
)
_DEFAULT_SMOKE_MANIFEST = (
    _REPOSITORY_ROOT
    / "tests/fixtures/guide/intent/two_stage_smoke_v1_manifest.json"
)

AdapterFactory = Callable[[GuideLlmConfig], object]
EvaluatorFactory = Callable[[], PipelineEvaluator]
Phase = Literal["smoke", "full"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class _NormalizedGateRow(_StrictModel):
    phase: Phase
    case_id: str
    model: str
    status: Literal[
        "ok",
        "schema_invalid",
        "provider_failure",
        "adapter_error",
        "pipeline_error",
    ]
    provider_failure_code: str | None
    route_schema_valid: bool
    route_critical_match: bool
    detail_schema_valid: bool | None
    detail_key_match: bool | None
    fail_closed_clarification: bool
    safe_clarification_mismatch_count: int = Field(ge=0)
    unsafe_task_plan_mismatch_count: int = Field(ge=0)
    critical_route_error_count: int = Field(ge=0)
    hard_constraint_override_count: int = Field(ge=0)
    unauthorized_constraint_transition_count: int = Field(ge=0)
    forbidden_field_acceptance_count: int = Field(ge=0)
    invalid_output_task_plan_invocation_count: int = Field(ge=0)
    wrong_product_selection_count: int = Field(ge=0)
    legacy_fallback_count: int = Field(ge=0)
    pipeline_evidence_available: bool

    def gate_row(self) -> TwoStageGateRow:
        return TwoStageGateRow(
            case_id=self.case_id,
            model=self.model,
            route_schema_valid=self.route_schema_valid,
            route_critical_match=self.route_critical_match,
            detail_schema_valid=self.detail_schema_valid,
            detail_key_match=self.detail_key_match,
            fail_closed_clarification=self.fail_closed_clarification,
            safe_clarification_mismatch_count=(
                self.safe_clarification_mismatch_count
            ),
            unsafe_task_plan_mismatch_count=(
                self.unsafe_task_plan_mismatch_count
            ),
            hard_constraint_override_count=(
                self.hard_constraint_override_count
            ),
            unauthorized_constraint_transition_count=(
                self.unauthorized_constraint_transition_count
            ),
            forbidden_field_acceptance_count=(
                self.forbidden_field_acceptance_count
            ),
            invalid_output_task_plan_invocation_count=(
                self.invalid_output_task_plan_invocation_count
            ),
            wrong_product_selection_count=(
                self.wrong_product_selection_count
            ),
            legacy_fallback_count=self.legacy_fallback_count,
        )


class _RuntimeGateRow(_StrictModel):
    phase: Phase
    case_id: str
    model: str
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    stage_usage: tuple[SemanticStageUsage, ...]


class RealGateReport(_StrictModel):
    phase: Phase
    model: str
    requested_case_count: int = Field(ge=0)
    executed_case_count: int = Field(ge=0)
    provider_unavailable_or_timeout_count: int = Field(ge=0)
    stop_reason: str | None
    case_count: int = Field(ge=0)
    route_critical_match_count: int = Field(ge=0)
    route_critical_rate: float = Field(ge=0.0, le=1.0)
    detail_evaluated_count: int = Field(ge=0)
    detail_key_match_count: int = Field(ge=0)
    detail_key_rate: float = Field(ge=0.0, le=1.0)
    all_failed_cases_fail_closed: bool
    safe_clarification_mismatch_count: int = Field(ge=0)
    unsafe_task_plan_mismatch_count: int = Field(ge=0)
    critical_route_error_count: int = Field(ge=0)
    hard_constraint_override_count: int = Field(ge=0)
    unauthorized_constraint_transition_count: int = Field(ge=0)
    forbidden_field_acceptance_count: int = Field(ge=0)
    invalid_output_task_plan_invocation_count: int = Field(ge=0)
    wrong_product_selection_count: int = Field(ge=0)
    legacy_fallback_count: int = Field(ge=0)
    hard_gates_passed: bool
    pipeline_evidence_complete: bool
    passed: bool
    normalized_rows: tuple[_NormalizedGateRow, ...]
    runtime_rows: tuple[_RuntimeGateRow, ...]

    def summary_payload(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            exclude={"normalized_rows", "runtime_rows"},
        )


class RealTwoStageAbReport(_StrictModel):
    selected_model: str | None
    exit_code: Literal[0, 3]
    normalized_results_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    runtime_metrics_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class _ProviderRequestBudget:
    per_case: int
    per_model: int
    total: int


@dataclass(frozen=True, slots=True)
class _PipelineOutcome:
    task: TaskPlan | None
    evaluation: PipelineEvaluation | None
    failure: PipelineEvaluationFailure | None


def _calculate_provider_request_budget(
    *,
    smoke_case_count: int,
    full_case_count: int,
    model_count: int,
) -> _ProviderRequestBudget:
    if (
        smoke_case_count < 0
        or full_case_count < 0
        or model_count <= 0
    ):
        raise IntentAbConfigurationError(
            "real A/B request budget inputs are invalid"
        )
    per_case = (
        _ROUTE_REQUESTS_PER_CASE
        + _DETAIL_REQUESTS_PER_CASE
        + FROZEN_FORMAT_REPAIR_ATTEMPTS
    )
    per_model = (smoke_case_count + full_case_count) * per_case
    return _ProviderRequestBudget(
        per_case=per_case,
        per_model=per_model,
        total=per_model * model_count,
    )


def _configure_ab_call_budget(
    *,
    base_config: GuideLlmConfig,
    request_budget: _ProviderRequestBudget,
    call_cap_is_explicit: bool,
) -> GuideLlmConfig:
    if (
        call_cap_is_explicit
        and base_config.daily_call_cap < request_budget.per_model
    ):
        raise IntentAbConfigurationError(
            "configured daily call cap is below the bounded real A/B maximum"
        )
    return replace(
        base_config,
        daily_call_cap=request_budget.per_model,
    )


def build_real_adapters(
    *,
    base_config: GuideLlmConfig,
    models: Sequence[str],
    adapter_factory: AdapterFactory = (
        SiliconFlowTwoStageIntentAdapter.from_config
    ),
) -> dict[str, object]:
    requested = tuple(models)
    if (
        len(requested) != len(FROZEN_MODELS)
        or set(requested) != set(FROZEN_MODELS)
    ):
        raise IntentAbConfigurationError(
            "real two-stage A/B requires the frozen model pair"
        )
    if base_config.api_key is None:
        raise IntentAbConfigurationError(
            "Guide LLM API key is unavailable"
        )
    if not callable(adapter_factory):
        raise IntentAbConfigurationError(
            "adapter factory must be callable"
        )
    request_budget = _calculate_provider_request_budget(
        smoke_case_count=FROZEN_SMOKE_COUNT,
        full_case_count=FROZEN_CASE_COUNT,
        model_count=len(requested),
    )
    if base_config.daily_call_cap < request_budget.per_model:
        raise IntentAbConfigurationError(
            "daily call cap cannot cover the bounded real A/B maximum"
        )

    adapters: dict[str, object] = {}
    try:
        for model in requested:
            config = replace(
                base_config,
                model=model,
                timeout_seconds=FROZEN_TIMEOUT_SECONDS,
                max_tokens=FROZEN_STAGE_MAX_TOKENS,
                format_repair_attempts=(
                    FROZEN_FORMAT_REPAIR_ATTEMPTS
                ),
                daily_call_cap=request_budget.per_model,
                enable_thinking=False,
            ).require_ready()
            adapter = adapter_factory(config)
            _validate_adapter_identity(adapter, expected_model=model)
            adapters[model] = adapter
    except Exception:
        _close_adapters(adapters)
        raise
    return adapters


def run_real_gate(
    *,
    adapter: object,
    cases: Sequence[IntentCase],
    evaluator: PipelineEvaluator | None = None,
    phase: Phase = "full",
) -> RealGateReport:
    normalized_cases = tuple(cases)
    if phase not in {"smoke", "full"}:
        raise ValueError("phase must be smoke or full")
    expected_count = (
        FROZEN_SMOKE_COUNT if phase == "smoke" else FROZEN_CASE_COUNT
    )
    if (
        len(normalized_cases) != expected_count
        or any(
            not isinstance(case, IntentCase)
            for case in normalized_cases
        )
        or len({case.case_id for case in normalized_cases})
        != len(normalized_cases)
    ):
        raise IntentAbConfigurationError(
            f"{phase} gate requires {expected_count} unique cases"
        )
    model = _validate_adapter_identity(adapter)
    active_evaluator = (
        evaluator if evaluator is not None else MinimalTaskPlanEvaluator()
    )
    if not callable(getattr(active_evaluator, "evaluate", None)):
        raise IntentAbConfigurationError(
            "pipeline evaluator must expose evaluate"
        )

    normalized_rows: list[_NormalizedGateRow] = []
    runtime_rows: list[_RuntimeGateRow] = []
    provider_failure_count = 0
    stop_reason: str | None = None
    for case in normalized_cases:
        normalized, runtime = _run_case(
            case=case,
            model=model,
            adapter=adapter,
            evaluator=active_evaluator,
            phase=phase,
        )
        normalized_rows.append(normalized)
        runtime_rows.append(runtime)
        if normalized.provider_failure_code in {
            "unavailable",
            "timeout",
        }:
            provider_failure_count += 1
        attempted = len(normalized_rows)
        if (
            attempted == PROVIDER_EARLY_STOP_CASE_COUNT
            and provider_failure_count / attempted
            > PROVIDER_EARLY_STOP_RATE
        ):
            stop_reason = "provider_failure_rate"
            break

    gate_rows = tuple(row.gate_row() for row in normalized_rows)
    gate_summary = (
        summarize_smoke(gate_rows)
        if phase == "smoke"
        else summarize(gate_rows)
    )
    critical_route_errors = sum(
        row.critical_route_error_count for row in normalized_rows
    )
    pipeline_complete = bool(normalized_rows) and all(
        row.pipeline_evidence_available for row in normalized_rows
    )
    passed = bool(
        stop_reason is None
        and gate_summary.passed
        and critical_route_errors == 0
        and pipeline_complete
    )
    if stop_reason is None:
        if critical_route_errors:
            stop_reason = "critical_route_error"
        elif not pipeline_complete:
            stop_reason = "pipeline_evidence"
        else:
            stop_reason = gate_summary.stop_reason
    return _build_gate_report(
        phase=phase,
        model=model,
        requested_case_count=len(normalized_cases),
        provider_failure_count=provider_failure_count,
        stop_reason=stop_reason,
        gate_summary=gate_summary,
        critical_route_error_count=critical_route_errors,
        pipeline_evidence_complete=pipeline_complete,
        passed=passed,
        normalized_rows=tuple(normalized_rows),
        runtime_rows=tuple(runtime_rows),
    )


def _run_case(
    *,
    case: IntentCase,
    model: str,
    adapter: object,
    evaluator: PipelineEvaluator,
    phase: Phase,
) -> tuple[_NormalizedGateRow, _RuntimeGateRow]:
    started = time.perf_counter_ns()
    status: Literal[
        "ok",
        "schema_invalid",
        "provider_failure",
        "adapter_error",
        "pipeline_error",
    ] = "ok"
    proposal: SemanticIntentProposal | None = None
    semantic_failure_code: SemanticProviderFailureCode | None = None
    provider_failure_code: str | None = None
    stage_usage: tuple[SemanticStageUsage, ...] = ()
    try:
        raw_result = adapter.propose_with_result(
            case.message,
            case.context,
        )
        result = _validated_two_stage_result(raw_result)
        proposal = result.proposal
        stage_usage = result.stage_usage
    except SemanticProviderFailure as failure:
        semantic_failure_code = failure.code
        if failure.code in {
            SemanticProviderFailureCode.INVALID_OUTPUT,
            SemanticProviderFailureCode.FORBIDDEN_OUTPUT,
        }:
            status = "schema_invalid"
        else:
            status = "provider_failure"
        provider_failure_code = _redacted_failure_code(failure.code)
    except Exception:
        status = "adapter_error"

    pipeline = _PipelineOutcome(task=None, evaluation=None, failure=None)
    if proposal is not None or semantic_failure_code is not None:
        try:
            pipeline = _run_pipeline(
                case=case,
                model=model,
                proposal=proposal,
                semantic_failure_code=semantic_failure_code,
                evaluator=evaluator,
            )
            if pipeline.failure is not None:
                status = "pipeline_error"
        except Exception:
            status = "pipeline_error"

    route_schema_valid = proposal is not None
    route_match = bool(
        proposal is not None
        and proposal.goal is case.expected.goal
        and proposal.topic is case.expected.topic
        and (
            proposal.goal is UnderstandingGoal.CLARIFICATION
        )
        == case.expected.must_clarify
    )
    if proposal is None or case.expected.must_clarify:
        detail_schema_valid = None
        detail_match = None
    else:
        detail_schema_valid = True
        detail_match = _detail_matches(case, proposal)

    quality_mismatch = bool(
        not route_match
        or detail_schema_valid is False
        or detail_match is False
    )
    fail_closed = bool(
        quality_mismatch
        and pipeline.task is not None
        and pipeline.task.mode == "clarify"
    )
    safe_mismatch = int(fail_closed)
    evaluation = pipeline.evaluation
    evaluation_failure = pipeline.failure
    pipeline_available = bool(
        evaluation is not None
        and evaluation_failure is None
        and evaluation.product_selection_invocation_count is not None
        and evaluation.wrong_product_selection_count is not None
        and evaluation.legacy_fallback_count is not None
    )
    unsafe_mismatch = int(
        status in {"adapter_error", "pipeline_error"}
        or (
            evaluation is not None
            and evaluation.task_plan_mismatch_count > 0
            and not fail_closed
        )
        or (
            evaluation is not None
            and (
                evaluation
                .unauthorized_constraint_transition_count
                > 0
            )
        )
    )
    hard_constraint_override_count = (
        evaluation.hard_constraint_override_count
        if evaluation is not None
        else 0
    )
    unauthorized_constraint_transition_count = (
        evaluation.unauthorized_constraint_transition_count
        if evaluation is not None
        else 0
    )
    wrong_product_selection_count = (
        evaluation.wrong_product_selection_count
        if (
            evaluation is not None
            and evaluation.wrong_product_selection_count is not None
        )
        else 0
    )
    legacy_fallback_count = (
        evaluation.legacy_fallback_count
        if (
            evaluation is not None
            and evaluation.legacy_fallback_count is not None
        )
        else (
            evaluation_failure.legacy_fallback_count
            if (
                evaluation_failure is not None
                and evaluation_failure.legacy_fallback_count is not None
            )
            else 0
        )
    )
    latency_ms = max(
        0.0,
        round((time.perf_counter_ns() - started) / 1_000_000, 6),
    )
    normalized = _NormalizedGateRow(
        phase=phase,
        case_id=case.case_id,
        model=model,
        status=status,
        provider_failure_code=provider_failure_code,
        route_schema_valid=route_schema_valid,
        route_critical_match=route_match,
        detail_schema_valid=detail_schema_valid,
        detail_key_match=detail_match,
        fail_closed_clarification=fail_closed,
        safe_clarification_mismatch_count=safe_mismatch,
        unsafe_task_plan_mismatch_count=unsafe_mismatch,
        critical_route_error_count=int(
            case.critical
            and not route_match
            and not fail_closed
        ),
        hard_constraint_override_count=(
            hard_constraint_override_count
        ),
        unauthorized_constraint_transition_count=(
            unauthorized_constraint_transition_count
        ),
        forbidden_field_acceptance_count=0,
        invalid_output_task_plan_invocation_count=0,
        wrong_product_selection_count=wrong_product_selection_count,
        legacy_fallback_count=legacy_fallback_count,
        pipeline_evidence_available=pipeline_available,
    )
    runtime = _RuntimeGateRow(
        phase=phase,
        case_id=case.case_id,
        model=model,
        latency_ms=latency_ms,
        stage_usage=stage_usage,
    )
    return normalized, runtime


def _run_pipeline(
    *,
    case: IntentCase,
    model: str,
    proposal: SemanticIntentProposal | None,
    semantic_failure_code: SemanticProviderFailureCode | None,
    evaluator: PipelineEvaluator,
) -> _PipelineOutcome:
    exact_constraints, exact_issues = parse_exact_constraints(case.message)
    confirmations = parse_exact_revision_confirmations(case.message)
    exact = PipelineExactInput(
        constraints=tuple(exact_constraints),
        issues=tuple(exact_issues),
        revision_confirmations=tuple(confirmations),
    )
    merged = merge_intent_signals(
        message=case.message,
        exact_constraints=exact.constraints,
        exact_issues=exact.issues,
        exact_revision_confirmations=exact.revision_confirmations,
        semantic=proposal,
        semantic_disposition=(
            SemanticLaneDisposition.AVAILABLE
            if proposal is not None
            else SemanticLaneDisposition.UNAVAILABLE
        ),
        context=case.context,
    )
    validated_merged = StructuredUnderstanding.model_validate(
        merged.model_dump(
            mode="python",
            round_trip=True,
            warnings=False,
        ),
        strict=True,
    )
    transition_plan = plan_code_owned_transitions(
        message=case.message,
        understanding=validated_merged,
        task=plan_task(validated_merged),
        previous=case.before_state,
    )
    task = TaskPlan.model_validate(
        transition_plan.task_plan.model_dump(
            mode="python",
            round_trip=True,
            warnings=False,
        ),
        strict=True,
    )
    request = PipelineEvaluationRequest(
        case_id=case.case_id,
        model=model,
        message=case.message,
        context=case.context,
        proposal=proposal,
        semantic_failure_code=semantic_failure_code,
        exact=exact,
        merged=validated_merged,
        task_plan=task,
        transitions=(
            transition_plan.transition_result.transitions
            if transition_plan.transition_result is not None
            else ()
        ),
        before_state=case.before_state,
        expected=case.expected,
    )
    observed = evaluator.evaluate(request)
    if isinstance(observed, PipelineEvaluationFailure):
        failure = PipelineEvaluationFailure.model_validate(
            observed.model_dump(mode="python"),
            strict=True,
        )
        return _PipelineOutcome(
            task=task,
            evaluation=None,
            failure=failure,
        )
    if not isinstance(observed, PipelineEvaluation):
        raise TypeError(
            "pipeline evaluator must return typed evidence"
        )
    evaluation = PipelineEvaluation.model_validate(
        observed.model_dump(mode="python"),
        strict=True,
    )
    return _PipelineOutcome(
        task=task,
        evaluation=evaluation,
        failure=None,
    )


def _validated_two_stage_result(
    value: object,
) -> TwoStageSemanticCallResult:
    if not isinstance(value, TwoStageSemanticCallResult):
        raise TypeError(
            "two-stage adapter must return TwoStageSemanticCallResult"
        )
    result = TwoStageSemanticCallResult.model_validate(
        value.model_dump(
            mode="python",
            round_trip=True,
            warnings=False,
        ),
        strict=True,
    )
    expected_stages = (
        ("route",)
        if result.proposal.goal is UnderstandingGoal.CLARIFICATION
        else ("route", "detail")
    )
    if tuple(item.stage for item in result.stage_usage) != expected_stages:
        raise TypeError("two-stage usage order is invalid")
    return result


def _detail_matches(
    case: IntentCase,
    proposal: SemanticIntentProposal,
) -> bool:
    fields_by_goal = {
        UnderstandingGoal.RECOMMENDATION: (
            "concerns",
            "observations",
        ),
        UnderstandingGoal.SUITABILITY: (
            "concerns",
            "observations",
        ),
        UnderstandingGoal.ASSESSMENT: (
            "concerns",
            "observations",
        ),
        UnderstandingGoal.COMPARISON: ("references",),
        UnderstandingGoal.FOLLOWUP: ("references",),
        UnderstandingGoal.KNOWLEDGE: ("concerns",),
        UnderstandingGoal.IMAGE_SIMILARITY: (
            "references",
            "observations",
        ),
    }
    field_names = fields_by_goal.get(case.expected.goal)
    if field_names is None:
        return True
    actual = proposal.model_dump(mode="json")
    expected = case.expected.model_dump(mode="json")
    return all(
        _typed_sequences_match(
            actual.get(field_name, []),
            expected.get(field_name, []),
        )
        for field_name in field_names
    )


def _typed_sequences_match(left: object, right: object) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return left == right
    return Counter(canonical_json_bytes(item) for item in left) == Counter(
        canonical_json_bytes(item) for item in right
    )


def _build_gate_report(
    *,
    phase: Phase,
    model: str,
    requested_case_count: int,
    provider_failure_count: int,
    stop_reason: str | None,
    gate_summary: TwoStageGateSummary,
    critical_route_error_count: int,
    pipeline_evidence_complete: bool,
    passed: bool,
    normalized_rows: tuple[_NormalizedGateRow, ...],
    runtime_rows: tuple[_RuntimeGateRow, ...],
) -> RealGateReport:
    payload = gate_summary.model_dump(mode="python")
    payload.pop("stop_reason")
    payload["hard_gates_passed"] = bool(
        gate_summary.hard_gates_passed
        and critical_route_error_count == 0
    )
    payload["passed"] = passed
    return RealGateReport(
        phase=phase,
        model=model,
        requested_case_count=requested_case_count,
        executed_case_count=len(normalized_rows),
        provider_unavailable_or_timeout_count=(
            provider_failure_count
        ),
        stop_reason=stop_reason,
        critical_route_error_count=critical_route_error_count,
        pipeline_evidence_complete=pipeline_evidence_complete,
        normalized_rows=normalized_rows,
        runtime_rows=runtime_rows,
        **payload,
    )


def _validate_adapter_identity(
    adapter: object,
    *,
    expected_model: str | None = None,
) -> str:
    provider = getattr(adapter, "provider", None)
    model = getattr(adapter, "model", None)
    prompt_version = getattr(adapter, "prompt_version", None)
    if (
        not isinstance(provider, str)
        or not provider
        or not isinstance(model, str)
        or not model
        or not isinstance(prompt_version, str)
        or not prompt_version
        or not callable(getattr(adapter, "propose_with_result", None))
        or (
            expected_model is not None
            and model != expected_model
        )
    ):
        raise IntentAbConfigurationError(
            "real two-stage adapter identity is unavailable"
        )
    return model


def _redacted_failure_code(
    code: SemanticProviderFailureCode,
) -> str:
    return {
        SemanticProviderFailureCode.AUTHENTICATION_FAILED: "authentication",
        SemanticProviderFailureCode.RATE_LIMITED: "rate_limit",
        SemanticProviderFailureCode.PROVIDER_UNAVAILABLE: "unavailable",
        SemanticProviderFailureCode.PROVIDER_REJECTED: "rejected",
        SemanticProviderFailureCode.TIMEOUT: "timeout",
        SemanticProviderFailureCode.EMPTY_RESPONSE: "empty",
        SemanticProviderFailureCode.INVALID_RESPONSE: "invalid",
        SemanticProviderFailureCode.INVALID_OUTPUT: "invalid",
        SemanticProviderFailureCode.FORBIDDEN_OUTPUT: "forbidden",
        SemanticProviderFailureCode.DAILY_BUDGET_EXCEEDED: "budget",
        SemanticProviderFailureCode.DAILY_CALL_CAP_EXCEEDED: "call_cap",
    }[code]


def _runtime_summary(
    rows: Sequence[_RuntimeGateRow],
) -> dict[str, object]:
    latencies = sorted(row.latency_ms for row in rows)
    stages: dict[str, object] = {}
    for stage in ("route", "detail"):
        observed = [
            usage
            for row in rows
            for usage in row.stage_usage
            if usage.stage == stage
        ]
        token_totals = sum_token_fields(
            [item.usage for item in observed]
        )
        stages[stage] = {
            "availability": (
                "AVAILABLE"
                if observed
                and all(
                    value is not None
                    for value in token_totals.values()
                )
                else "UNAVAILABLE"
            ),
            "observed_case_count": len(observed),
            "repair_used_count": sum(
                item.repair_used for item in observed
            ),
            **token_totals,
        }
    return {
        "case_count": len(rows),
        "latency_ms": {
            "p50": nearest_rank(latencies, 0.50),
            "p95": nearest_rank(latencies, 0.95),
        },
        "stage_usage": stages,
        "cost_status": "UNAVAILABLE",
        "actual_cost_cny": "UNAVAILABLE",
    }
def _write_evidence(
    *,
    writer: PrivateEvidenceWriter,
    model_reports: Mapping[str, dict[str, object]],
    normalized_rows: Sequence[_NormalizedGateRow],
    runtime_rows: Sequence[_RuntimeGateRow],
    selected_model: str | None,
    sensitive_values: Sequence[str],
) -> RealTwoStageAbReport:
    runtime_payload = {
        "schema_version": _RUNTIME_SCHEMA_VERSION,
        "models": {
            model: {
                phase: (
                    _runtime_summary(
                        [
                            row
                            for row in runtime_rows
                            if row.model == model and row.phase == phase
                        ]
                    )
                    if report.get(phase) is not None
                    else None
                )
                for phase in ("smoke", "full")
            }
            for model, report in sorted(model_reports.items())
        },
        "rows": [
            row.model_dump(mode="json")
            for row in sorted(
                runtime_rows,
                key=lambda item: (
                    item.model,
                    item.phase,
                    item.case_id,
                ),
            )
        ],
    }
    exit_code: Literal[0, 3] = (
        0 if selected_model is not None else 3
    )
    def build_summary(
        normalized_sha256: str,
        runtime_sha256: str,
    ) -> Mapping[str, object]:
        return {
            "schema_version": _SUMMARY_SCHEMA_VERSION,
            "identity": {
                "runner_schema_version": _RUNNER_SCHEMA_VERSION,
                "route_schema_version": SemanticRouteProposal.schema_version,
                "detail_schema_versions": sorted(
                    {
                        model.schema_version
                        for model in (
                            RecommendationDetails,
                            AssessmentDetails,
                            ComparisonDetails,
                            FollowupDetails,
                            KnowledgeDetails,
                            ImageDetails,
                        )
                    }
                ),
                "semantic_schema_version": (
                    SemanticIntentProposal.schema_version
                ),
                "case_file_sha256": FROZEN_CASE_FILE_SHA256,
                "case_manifest_sha256": FROZEN_CASE_MANIFEST_SHA256,
                "smoke_file_sha256": FROZEN_SMOKE_FILE_SHA256,
                "smoke_manifest_sha256": (
                    FROZEN_SMOKE_MANIFEST_SHA256
                ),
                "models": list(FROZEN_MODELS),
                "temperature": 0,
                "enable_thinking": False,
                "stage_max_tokens": FROZEN_STAGE_MAX_TOKENS,
                "timeout_seconds": FROZEN_TIMEOUT_SECONDS,
                "shared_format_repair_attempts": (
                    FROZEN_FORMAT_REPAIR_ATTEMPTS
                ),
                "transport_retry_count": 0,
            },
            "selected_model": selected_model,
            "exit_code": exit_code,
            "normalized_results_sha256": normalized_sha256,
            "stable_evidence_sha256": normalized_sha256,
            "runtime_metrics_sha256": runtime_sha256,
            "models": {
                model: report
                for model, report in sorted(model_reports.items())
            },
        }

    bundle = build_evidence_bundle(
        normalized_rows=tuple(
            row.model_dump(mode="json")
            for row in normalized_rows
        ),
        normalized_sort_key=lambda row: (
            str(row["model"]),
            str(row["phase"]),
            str(row["case_id"]),
        ),
        runtime_payload=runtime_payload,
        summary_builder=build_summary,
    )
    writer.write(bundle, sensitive_values=sensitive_values)
    return RealTwoStageAbReport(
        selected_model=selected_model,
        exit_code=exit_code,
        normalized_results_sha256=bundle.normalized_sha256,
        runtime_metrics_sha256=bundle.runtime_sha256,
        summary_sha256=bundle.summary_sha256,
    )


def _select_model(
    model_reports: Mapping[str, dict[str, object]],
) -> str | None:
    passing = {
        model
        for model, report in model_reports.items()
        if report["passed"] is True
    }
    for preferred in FROZEN_MODELS:
        if preferred in passing:
            return preferred
    return None


def _run_ab(
    *,
    frozen: FrozenInputs,
    adapters: Mapping[str, object],
    evaluator_factory: EvaluatorFactory,
    writer: PrivateEvidenceWriter,
    sensitive_values: Sequence[str],
) -> RealTwoStageAbReport:
    model_reports: dict[str, dict[str, object]] = {}
    normalized_rows: list[_NormalizedGateRow] = []
    runtime_rows: list[_RuntimeGateRow] = []
    smoke_reports: dict[str, RealGateReport] = {}
    full_reports: dict[str, RealGateReport] = {}

    for model in FROZEN_MODELS:
        adapter = adapters[model]
        smoke = run_real_gate(
            adapter=adapter,
            cases=frozen.smoke_cases,
            evaluator=evaluator_factory(),
            phase="smoke",
        )
        smoke_reports[model] = smoke
        normalized_rows.extend(smoke.normalized_rows)
        runtime_rows.extend(smoke.runtime_rows)

    for model in FROZEN_MODELS:
        smoke = smoke_reports[model]
        if smoke.passed:
            full_reports[model] = run_real_gate(
                adapter=adapters[model],
                cases=frozen.cases,
                evaluator=evaluator_factory(),
                phase="full",
            )
            full = full_reports[model]
            normalized_rows.extend(full.normalized_rows)
            runtime_rows.extend(full.runtime_rows)

    for model in FROZEN_MODELS:
        adapter = adapters[model]
        smoke = smoke_reports[model]
        full = full_reports.get(model)
        if smoke.stop_reason == "provider_failure_rate":
            stop_reason = "provider_failure_rate"
        elif not smoke.passed:
            stop_reason = "smoke_gate"
        elif (
            full is not None
            and full.stop_reason == "provider_failure_rate"
        ):
            stop_reason = "provider_failure_rate"
        elif full is not None and not full.passed:
            stop_reason = "full_gate"
        else:
            stop_reason = None
        model_reports[model] = {
            "provider": getattr(adapter, "provider"),
            "model": model,
            "prompt_version": getattr(adapter, "prompt_version"),
            "smoke": smoke.summary_payload(),
            "full": (
                full.summary_payload() if full is not None else None
            ),
            "stop_reason": stop_reason,
            "passed": bool(full is not None and full.passed),
        }

    selected_model = _select_model(model_reports)
    return _write_evidence(
        writer=writer,
        model_reports=model_reports,
        normalized_rows=normalized_rows,
        runtime_rows=runtime_rows,
        selected_model=selected_model,
        sensitive_values=sensitive_values,
    )


def _close_adapters(adapters: Mapping[str, object]) -> None:
    for adapter in adapters.values():
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen two-stage V4-Flash/V3.2 Guide A/B."
        )
    )
    parser.add_argument("--cases", required=True)
    parser.add_argument(
        "--smoke-cases",
        default=str(_DEFAULT_SMOKE_CASES),
    )
    parser.add_argument(
        "--smoke-manifest",
        default=str(_DEFAULT_SMOKE_MANIFEST),
    )
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        dest="models",
    )
    parser.add_argument("--output-dir", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    adapter_factory: AdapterFactory = (
        SiliconFlowTwoStageIntentAdapter.from_config
    ),
    evaluator_factory: EvaluatorFactory = ModelVerticalEvaluator,
) -> int:
    arguments = _parser().parse_args(argv)
    requested_models = tuple(arguments.models)
    if (
        len(requested_models) != len(FROZEN_MODELS)
        or set(requested_models) != set(FROZEN_MODELS)
        or not callable(evaluator_factory)
    ):
        return 2

    adapters: Mapping[str, object] = {}
    writer: PrivateEvidenceWriter | None = None
    report: RealTwoStageAbReport | None = None
    try:
        frozen = load_frozen_inputs(
            cases_path=arguments.cases,
            smoke_cases_path=arguments.smoke_cases,
            smoke_manifest_path=arguments.smoke_manifest,
        )
        request_budget = _calculate_provider_request_budget(
            smoke_case_count=len(frozen.smoke_cases),
            full_case_count=len(frozen.cases),
            model_count=len(requested_models),
        )
        base_config = _configure_ab_call_budget(
            base_config=GuideLlmConfig.from_environment(),
            request_budget=request_budget,
            call_cap_is_explicit=(
                _DAILY_CALL_CAP_ENV in os.environ
            ),
        )
        if base_config.api_key is None:
            return 2
        writer = PrivateEvidenceWriter.create(arguments.output_dir)
        adapters = build_real_adapters(
            base_config=base_config,
            models=requested_models,
            adapter_factory=adapter_factory,
        )
        report = _run_ab(
            frozen=frozen,
            adapters=adapters,
            evaluator_factory=evaluator_factory,
            writer=writer,
            sensitive_values=(base_config.api_key,),
        )
    except (
        GuideLlmConfigError,
        IntentCaseError,
        IntentAbConfigurationError,
        OSError,
        OutputBindingError,
        TypeError,
        ValueError,
    ):
        return 2
    finally:
        _close_adapters(adapters)
        if writer is not None:
            writer.close(remove_if_empty=report is None)
    assert report is not None
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASELINE_MODEL",
    "FLASH_MODEL",
    "FROZEN_MODELS",
    "RealGateReport",
    "RealTwoStageAbReport",
    "build_real_adapters",
    "main",
    "run_real_gate",
]
