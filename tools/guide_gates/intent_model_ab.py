"""Deterministic, adapter-injected semantic intent A/B gate."""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from threading import Lock, Thread
import time
from types import TracebackType
from typing import Literal, Mapping, Protocol, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticSchemaDiagnostic,
    SemanticSchemaDiagnosticStage,
    SemanticSchemaRepairOutcome,
    build_semantic_schema_diagnostic,
)
from app.guide.application.query_context import (
    query_context_to_constraints,
    task_plan_to_query_context,
)
from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.constraint_transitions import ConstraintTransition
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    InclusionConstraint,
    SkinConstraint,
    TaskPlan,
)
from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.intent.task_planning import (
    compile_task_constraints,
    plan_task,
)
from app.guide.intent.transition_planning import (
    plan_code_owned_transitions,
)
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    EfficacyDraft,
    ExactConstraintDraft,
    ExactRevisionConfirmation,
    ExclusionDraft,
    InclusionDraft,
    SkinDraft,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
    UnderstandingIssue,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_revision_confirmations,
)
from app.guide.understanding.semantic_contracts import (
    ConcernCode,
    SemanticContext,
    SemanticIntentProposal,
    SemanticLaneDisposition,
    SemanticObservation,
    SemanticReference,
)


_CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{1,47}$")
_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_MINIMUM_CASE_COUNT = 120
_HELPER_JOIN_POLL_SECONDS = 0.05
_HELPER_CANCEL_GRACE_SECONDS = 0.1
_RUNNER_SCHEMA_VERSION = "guide-intent-model-ab-v3"
_SUMMARY_SCHEMA_VERSION = "guide-intent-model-ab-summary-v1"
_FLASH_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
_BASELINE_MODEL = "deepseek-ai/DeepSeek-V3.2"
_APPROVED_MODELS = frozenset({_FLASH_MODEL, _BASELINE_MODEL})
_NORMALIZED_RESULTS_NAME = "normalized_results.jsonl"
_RUNTIME_METRICS_NAME = "runtime_metrics.json"
_SUMMARY_NAME = "summary.json"
_SUMS_NAME = "SHA256SUMS"
_RUNTIME_SCHEMA_VERSION = "guide-intent-model-ab-runtime-v1"
_EXACT_HARD_CONSTRAINT_TYPES = (
    BudgetDraft,
    CategoryDraft,
    SkinDraft,
    ExclusionDraft,
    InclusionDraft,
    EfficacyDraft,
)


class NormalizedProviderFailureCode(str, Enum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    EMPTY = "empty"
    INVALID = "invalid"
    FORBIDDEN = "forbidden"
    BUDGET = "budget"
    CALL_CAP = "call_cap"


class EarliestFailureLayer(str, Enum):
    NONE = "none"
    PROVIDER_TRANSPORT = "provider_transport"
    SEMANTIC_SCHEMA = "semantic_schema"
    ADAPTER = "adapter"
    SEMANTIC_PROPOSAL = "semantic_proposal"
    PIPELINE = "pipeline"
    TASK_PLAN = "task_plan"
    RETRIEVAL_DECISION = "retrieval_decision"
    PUBLIC_ROUTING = "public_routing"


class IntentCaseError(ValueError):
    """Raised when the frozen A/B case set is malformed."""


class IntentAbConfigurationError(ValueError):
    """Raised when adapters or output configuration are invalid."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class IntentExpected(_StrictModel):
    goal: UnderstandingGoal
    topic: TopicCode | None
    concerns: tuple[ConcernCode, ...] = Field(max_length=16)
    observations: tuple[SemanticObservation, ...] = Field(max_length=16)
    references: tuple[SemanticReference, ...] = Field(max_length=4)
    must_clarify: bool
    expected_task_mode: Literal[
        "recommend",
        "comparison",
        "suitability",
        "knowledge",
        "followup",
        "clarify",
    ] | None = None
    final_state: RecommendationQueryContext | None = None
    transitions: tuple["ExpectedConstraintTransition", ...] = Field(
        default_factory=tuple,
        max_length=16,
    )

    @model_validator(mode="after")
    def validate_clarification_contract(self) -> IntentExpected:
        if self.must_clarify != (
            self.goal is UnderstandingGoal.CLARIFICATION
        ):
            raise ValueError(
                "must_clarify must match the clarification goal"
            )
        if len(self.concerns) != len(set(self.concerns)):
            raise ValueError("expected concerns must be unique")
        observation_keys = {
            _typed_record_bytes(observation)
            for observation in self.observations
        }
        if len(observation_keys) != len(self.observations):
            raise ValueError("expected observations must be unique")
        return self


class ExpectedConstraintTransition(_StrictModel):
    target: str = Field(min_length=1, max_length=256)
    operation: Literal["add", "retain", "replace", "remove"]


class IntentCase(_StrictModel):
    case_id: str
    message: str = Field(min_length=1, max_length=4000)
    context: SemanticContext
    expected: IntentExpected
    before_state: RecommendationQueryContext | None = None
    critical: bool
    tags: tuple[str, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_state_expectation(self) -> IntentCase:
        has_before = self.before_state is not None
        has_final = self.expected.final_state is not None
        if has_before != has_final:
            raise ValueError(
                "before_state and expected final_state must appear together"
            )
        if not has_final and self.expected.transitions:
            raise ValueError(
                "transition expectations require final_state"
            )
        return self


class AdapterUsage(_StrictModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    cost_cny: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_cost(self) -> AdapterUsage:
        if self.cost_cny is not None and not self.cost_cny.is_finite():
            raise ValueError("cost_cny must be finite")
        return self


class AbInvocation(_StrictModel):
    proposal: object
    usage: AdapterUsage = Field(default_factory=AdapterUsage)
    hard_constraint_override_count: int | None = Field(
        default=None,
        ge=0,
    )
    invalid_output_task_plan_invocation_count: int | None = Field(
        default=None,
        ge=0,
    )
    product_selection_invocation_count: int | None = Field(
        default=None,
        ge=0,
    )
    wrong_product_selection_count: int | None = Field(
        default=None,
        ge=0,
    )
    legacy_fallback_count: int | None = Field(
        default=None,
        ge=0,
    )


AdapterResult = AbInvocation


class IntentAdapter(Protocol):
    provider: str
    model: str
    prompt_version: str

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal | AbInvocation: ...


class LatencySummary(_StrictModel):
    p50: float = Field(ge=0.0, allow_inf_nan=False)
    p95: float = Field(ge=0.0, allow_inf_nan=False)


class UsageSummary(_StrictModel):
    availability: Literal["AVAILABLE", "UNAVAILABLE"]
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    cost_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    actual_cost_cny: Literal["UNAVAILABLE"] = "UNAVAILABLE"


class HardGateSummary(_StrictModel):
    passed: bool
    critical_failure_count: int = Field(ge=0)
    pipeline_status: Literal["AVAILABLE", "UNAVAILABLE"]
    merger_invocation_count: int | None = Field(default=None, ge=0)
    hard_constraint_override_count: int | None = Field(
        default=None,
        ge=0,
    )
    unauthorized_constraint_transition_count: int | None = Field(
        default=None,
        ge=0,
    )
    forbidden_field_acceptance_count: int = Field(ge=0)
    invalid_output_task_plan_invocation_count: int = Field(ge=0)
    untyped_failure_count: int = Field(ge=0)
    evaluator_failure_count: int = Field(ge=0)
    task_plan_invocation_count: int | None = Field(default=None, ge=0)
    task_plan_mismatch_count: int | None = Field(default=None, ge=0)
    product_selection_status: Literal["AVAILABLE", "UNAVAILABLE"]
    product_selection_invocation_count: int | None = Field(
        default=None,
        ge=0,
    )
    wrong_product_selection_count: int | None = Field(
        default=None,
        ge=0,
    )
    legacy_fallback_status: Literal["AVAILABLE", "UNAVAILABLE"]
    legacy_fallback_count: int | None = Field(default=None, ge=0)


class IntentModelSummary(_StrictModel):
    passed: bool
    case_count: int = Field(ge=0)
    schema_valid_count: int = Field(ge=0)
    goal_correct_count: int = Field(ge=0)
    topic_correct_count: int = Field(ge=0)
    concern_correct_count: int = Field(ge=0)
    observation_correct_count: int = Field(ge=0)
    reference_correct_count: int = Field(ge=0)
    critical_failure_count: int = Field(ge=0)
    schema_valid_rate: float = Field(ge=0.0, le=1.0)
    goal_accuracy: float = Field(ge=0.0, le=1.0)
    topic_accuracy: float = Field(ge=0.0, le=1.0)
    concern_accuracy: float = Field(ge=0.0, le=1.0)
    observation_accuracy: float = Field(ge=0.0, le=1.0)
    reference_accuracy: float = Field(ge=0.0, le=1.0)
    hard_gates: HardGateSummary


class IntentRuntimeSummary(_StrictModel):
    latency_ms: LatencySummary
    usage: UsageSummary


class IntentAbReport(_StrictModel):
    case_count: int = Field(ge=0)
    selected_model: str | None
    exit_code: Literal[0, 3]
    case_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_metrics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_summaries: dict[str, IntentModelSummary]
    runtime_metrics: dict[str, IntentRuntimeSummary]


class _ModelIdentity(_StrictModel):
    label: str
    provider: str
    model: str
    prompt_version: str


class PipelineExactInput(_StrictModel):
    constraints: tuple[ExactConstraintDraft, ...]
    issues: tuple[UnderstandingIssue, ...]
    revision_confirmations: tuple[
        ExactRevisionConfirmation,
        ...,
    ]


class PipelineEvaluationRequest(_StrictModel):
    case_id: str
    model: str
    message: str = Field(min_length=1, max_length=4000)
    context: SemanticContext
    proposal: SemanticIntentProposal | None
    semantic_failure_code: SemanticProviderFailureCode | None = None
    exact: PipelineExactInput
    merged: StructuredUnderstanding
    task_plan: TaskPlan
    transitions: tuple[ConstraintTransition, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    before_state: RecommendationQueryContext | None = None
    expected: IntentExpected

    @model_validator(mode="after")
    def validate_semantic_outcome(self) -> PipelineEvaluationRequest:
        if (self.proposal is None) == (
            self.semantic_failure_code is None
        ):
            raise ValueError(
                "pipeline request requires proposal or typed failure"
            )
        return self


class PipelineEvaluation(_StrictModel):
    task_plan_mismatch_count: int = Field(ge=0, le=1)
    hard_constraint_override_count: int = Field(ge=0, le=1)
    unauthorized_constraint_transition_count: int = Field(
        default=0,
        ge=0,
        le=1,
    )
    product_selection_invocation_count: int | None = Field(
        default=None,
        ge=0,
    )
    wrong_product_selection_count: int | None = Field(
        default=None,
        ge=0,
    )
    legacy_fallback_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_observation_completeness(self) -> PipelineEvaluation:
        selection_values = (
            self.product_selection_invocation_count,
            self.wrong_product_selection_count,
        )
        if (selection_values[0] is None) != (
            selection_values[1] is None
        ):
            raise ValueError(
                "selection observation must be complete"
            )
        if (
            selection_values[0] is not None
            and selection_values[1] is not None
            and selection_values[1] > selection_values[0]
        ):
            raise ValueError(
                "wrong selections cannot exceed invocations"
            )
        return self


class PipelineEvaluationFailureCode(str, Enum):
    RUNTIME_BUILD_FAILED = "runtime_build_failed"
    STREAM_FAILED = "stream_failed"
    INVALID_EVENT_STREAM = "invalid_event_stream"


class PipelineEvaluationFailure(_StrictModel):
    code: PipelineEvaluationFailureCode
    legacy_fallback_count: int | None = Field(default=None, ge=0)


class PipelineEvaluator(Protocol):
    def evaluate(
        self,
        request: PipelineEvaluationRequest,
    ) -> PipelineEvaluation | PipelineEvaluationFailure: ...


class _LockedPipelineEvaluator:
    def __init__(self, evaluator: PipelineEvaluator) -> None:
        self._evaluator = evaluator
        self._lock = Lock()

    def evaluate(
        self,
        request: PipelineEvaluationRequest,
    ) -> PipelineEvaluation | PipelineEvaluationFailure:
        with self._lock:
            return self._evaluator.evaluate(request)


class MinimalTaskPlanEvaluator:
    """Observe planning only; retrieval and legacy remain unavailable."""

    def evaluate(
        self,
        request: PipelineEvaluationRequest,
    ) -> PipelineEvaluation:
        expected_constraints = (
            query_context_to_constraints(
                request.expected.final_state
            )
            if request.expected.final_state is not None
            else _compile_expected_task_constraints(request.merged)
        )
        actual_constraints = request.task_plan.constraints
        if request.semantic_failure_code is None:
            expected_mode = (
                request.expected.expected_task_mode
                or _expected_task_mode(
                    request=request,
                    expected_constraints=expected_constraints,
                )
            )
            topic_matches = _task_topic_matches_expected(
                request=request,
                expected_constraints=expected_constraints,
            )
        else:
            expected_mode = request.task_plan.mode
            topic_matches = True
        constraints_match = _typed_records_match_exactly(
            expected_constraints,
            actual_constraints,
        )
        unauthorized_transition = _unauthorized_transition_count(
            request
        )
        return PipelineEvaluation(
            task_plan_mismatch_count=int(
                request.task_plan.mode != expected_mode
                or not topic_matches
                or not constraints_match
            ),
            hard_constraint_override_count=(
                _hard_constraint_override_count(
                    exact_constraints=request.exact.constraints,
                    merged=request.merged,
                    task_constraints=request.task_plan.constraints,
                )
            ),
            unauthorized_constraint_transition_count=(
                unauthorized_transition
            ),
        )


class _PipelineObservation(_StrictModel):
    task_plan_mismatch_count: int | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    hard_constraint_override_count: int | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    unauthorized_constraint_transition_count: int | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    product_selection_invocation_count: int | None = Field(
        default=None,
        ge=0,
    )
    wrong_product_selection_count: int | None = Field(
        default=None,
        ge=0,
    )
    legacy_fallback_count: int | None = Field(default=None, ge=0)
    evaluator_failure_code: PipelineEvaluationFailureCode | None = None
    strict_validation_passed: bool
    merger_invocation_count: int | None = Field(default=None, ge=0)
    task_plan_invocation_count: int | None = Field(
        default=None,
        ge=0,
    )
    forbidden_field_acceptance_count: int = Field(ge=0)
    invalid_output_task_plan_invocation_count: int = Field(ge=0)


class _NormalizedResult(_StrictModel):
    case_id: str
    model: str
    status: Literal[
        "ok",
        "schema_invalid",
        "provider_failure",
        "adapter_error",
        "pipeline_error",
    ]
    provider_failure_code: NormalizedProviderFailureCode | None
    schema_diagnostic: SemanticSchemaDiagnostic | None
    earliest_failure_layer: EarliestFailureLayer
    schema_valid: bool
    goal_correct: bool
    topic_correct: bool
    concern_correct: bool
    observation_correct: bool
    reference_correct: bool
    critical_failure: bool
    actual: dict[str, object] | None
    pipeline: _PipelineObservation


class _RuntimeResult(_StrictModel):
    case_id: str
    model: str
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    usage: dict[str, object]


class _ModelExecution(_StrictModel):
    rows: tuple[_NormalizedResult, ...]
    runtime_rows: tuple[_RuntimeResult, ...]
    summary: IntentModelSummary
    runtime: IntentRuntimeSummary


def load_cases(path: str | Path) -> tuple[IntentCase, ...]:
    """Load and strictly validate the committed human-labelled JSONL."""

    case_path = Path(path)
    try:
        content = case_path.read_bytes()
    except OSError as exc:
        raise IntentCaseError("intent case file is unavailable") from exc
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntentCaseError("intent case file must be UTF-8") from exc

    cases: list[IntentCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise IntentCaseError(
                f"intent case row {line_number} is blank"
            )
        try:
            case = IntentCase.model_validate_json(line, strict=True)
        except ValidationError as exc:
            raise IntentCaseError(
                f"intent case row {line_number} is invalid"
            ) from exc
        _validate_case_identifiers(case, line_number=line_number)
        cases.append(case)

    if len(cases) < _MINIMUM_CASE_COUNT:
        raise IntentCaseError(
            f"intent case set requires at least {_MINIMUM_CASE_COUNT} rows"
        )
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise IntentCaseError("intent case IDs must be unique")
    return tuple(sorted(cases, key=lambda case: case.case_id))


def run_ab(
    *,
    cases: Sequence[IntentCase],
    adapters: Mapping[str, IntentAdapter],
    evaluator: PipelineEvaluator | None = None,
    output_dir: str | Path,
) -> IntentAbReport:
    """Run one frozen case set through injected, preconfigured adapters."""

    normalized_cases = _validate_cases(cases)
    identities = _validate_adapters(adapters)
    pipeline_evaluator = _LockedPipelineEvaluator(
        _validate_evaluator(evaluator)
    )
    destination = _prepare_output_directory(Path(output_dir))
    case_manifest_sha256 = _case_manifest_sha256(normalized_cases)

    rows: list[_NormalizedResult] = []
    runtime_rows: list[_RuntimeResult] = []
    model_summaries: dict[str, IntentModelSummary] = {}
    runtime_metrics: dict[str, IntentRuntimeSummary] = {}
    executions = _run_models(
        identities=identities,
        cases=normalized_cases,
        adapters=adapters,
        evaluator=pipeline_evaluator,
    )
    for model in sorted(executions):
        execution = executions[model]
        rows.extend(execution.rows)
        runtime_rows.extend(execution.runtime_rows)
        model_summaries[model] = execution.summary
        runtime_metrics[model] = execution.runtime

    selected_model = _select_model(model_summaries)
    exit_code: Literal[0, 3] = 0 if selected_model is not None else 3
    normalized_bytes = b"".join(
        _canonical_json_bytes(row.model_dump(mode="json")) + b"\n"
        for row in sorted(
            rows,
            key=lambda row: (row.model, row.case_id),
        )
    )
    normalized_sha256 = hashlib.sha256(normalized_bytes).hexdigest()
    summary_payload = {
        "schema_version": _SUMMARY_SCHEMA_VERSION,
        "identity": {
            "runner_schema_version": _RUNNER_SCHEMA_VERSION,
            "semantic_schema_version": (
                SemanticIntentProposal.schema_version
            ),
            "case_manifest_sha256": case_manifest_sha256,
            "model_identities": [
                identity.model_dump(mode="json")
                for identity in identities
            ],
        },
        "case_count": len(normalized_cases),
        "selected_model": selected_model,
        "exit_code": exit_code,
        "normalized_results_sha256": normalized_sha256,
        "stable_evidence_sha256": normalized_sha256,
        "models": {
            model: summary.model_dump(mode="json")
            for model, summary in sorted(model_summaries.items())
        },
    }
    summary_bytes = _canonical_json_bytes(summary_payload) + b"\n"
    summary_sha256 = hashlib.sha256(summary_bytes).hexdigest()
    runtime_payload = {
        "schema_version": _RUNTIME_SCHEMA_VERSION,
        "models": {
            model: metrics.model_dump(mode="json")
            for model, metrics in sorted(runtime_metrics.items())
        },
        "rows": [
            row.model_dump(mode="json")
            for row in sorted(
                runtime_rows,
                key=lambda row: (row.model, row.case_id),
            )
        ],
    }
    runtime_bytes = _canonical_json_bytes(runtime_payload) + b"\n"
    runtime_sha256 = hashlib.sha256(runtime_bytes).hexdigest()
    sums_bytes = (
        f"{normalized_sha256}  {_NORMALIZED_RESULTS_NAME}\n"
        f"{runtime_sha256}  {_RUNTIME_METRICS_NAME}\n"
        f"{summary_sha256}  {_SUMMARY_NAME}\n"
    ).encode("ascii")

    _atomic_write(destination / _NORMALIZED_RESULTS_NAME, normalized_bytes)
    _atomic_write(destination / _RUNTIME_METRICS_NAME, runtime_bytes)
    _atomic_write(destination / _SUMMARY_NAME, summary_bytes)
    _atomic_write(destination / _SUMS_NAME, sums_bytes)
    return IntentAbReport(
        case_count=len(normalized_cases),
        selected_model=selected_model,
        exit_code=exit_code,
        case_manifest_sha256=case_manifest_sha256,
        normalized_results_sha256=normalized_sha256,
        summary_sha256=summary_sha256,
        runtime_metrics_sha256=runtime_sha256,
        model_summaries=model_summaries,
        runtime_metrics=runtime_metrics,
    )


def _run_models(
    *,
    identities: Sequence[_ModelIdentity],
    cases: Sequence[IntentCase],
    adapters: Mapping[str, IntentAdapter],
    evaluator: PipelineEvaluator,
) -> dict[str, _ModelExecution]:
    executions: dict[str, _ModelExecution] = {}
    failures: dict[
        str,
        tuple[BaseException, TracebackType | None],
    ] = {}
    result_lock = Lock()

    def execute(
        identity: _ModelIdentity,
        *,
        is_helper: bool = False,
    ) -> None:
        try:
            execution = _run_model(
                identity=identity,
                cases=cases,
                adapter=adapters[identity.label],
                evaluator=evaluator,
            )
        except BaseException as error:
            if not is_helper and not isinstance(error, Exception):
                raise
            with result_lock:
                failures[identity.label] = (
                    error,
                    error.__traceback__,
                )
        else:
            with result_lock:
                executions[identity.label] = execution

    if len(identities) == 1:
        execute(identities[0])
    else:
        caller_identity, helper_identity = identities
        helper = Thread(
            target=execute,
            args=(helper_identity,),
            kwargs={"is_helper": True},
            name="guide-intent-ab-model-helper",
            daemon=True,
        )
        helper.start()
        try:
            execute(caller_identity)
            while helper.is_alive():
                helper.join(timeout=_HELPER_JOIN_POLL_SECONDS)
        except (KeyboardInterrupt, SystemExit):
            helper.join(timeout=_HELPER_CANCEL_GRACE_SECONDS)
            raise

    if failures:
        fatal_failures = {
            model
            for model, (error, _) in failures.items()
            if not isinstance(error, Exception)
        }
        failed_model = min(fatal_failures or failures.keys())
        error, traceback = failures[failed_model]
        raise error.with_traceback(traceback)
    return executions


def _run_model(
    *,
    identity: _ModelIdentity,
    cases: Sequence[IntentCase],
    adapter: IntentAdapter,
    evaluator: PipelineEvaluator,
) -> _ModelExecution:
    case_results = [
        _run_case(
            case=case,
            model=identity.label,
            adapter=adapter,
            evaluator=evaluator,
        )
        for case in cases
    ]
    rows = tuple(result[0] for result in case_results)
    runtime_rows = tuple(result[1] for result in case_results)
    return _ModelExecution(
        rows=rows,
        runtime_rows=runtime_rows,
        summary=_summarize_model(rows),
        runtime=_summarize_runtime(runtime_rows),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    adapters: Mapping[str, IntentAdapter] | None = None,
    evaluator: PipelineEvaluator | None = None,
) -> int:
    """Run the offline gate; callers must inject configured adapters."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen Guide semantic intent gate with "
            "caller-injected adapters."
        )
    )
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output-dir", required=True)
    arguments = parser.parse_args(argv)
    if not adapters:
        return 2
    try:
        cases = load_cases(arguments.cases)
        report = run_ab(
            cases=cases,
            adapters=adapters,
            evaluator=evaluator,
            output_dir=arguments.output_dir,
        )
    except (IntentCaseError, IntentAbConfigurationError):
        return 2
    return report.exit_code


def _validate_case_identifiers(
    case: IntentCase,
    *,
    line_number: int,
) -> None:
    if not _CASE_ID_PATTERN.fullmatch(case.case_id):
        raise IntentCaseError(
            f"intent case row {line_number} has an invalid case ID"
        )
    if len(case.tags) != len(set(case.tags)) or any(
        not _TAG_PATTERN.fullmatch(tag)
        for tag in case.tags
    ):
        raise IntentCaseError(
            f"intent case row {line_number} has invalid tags"
        )


def _validate_cases(
    cases: Sequence[IntentCase],
) -> tuple[IntentCase, ...]:
    values = tuple(cases)
    if (
        len(values) < _MINIMUM_CASE_COUNT
        or any(not isinstance(case, IntentCase) for case in values)
    ):
        raise IntentAbConfigurationError(
            "A/B cases must contain at least 120 validated rows"
        )
    case_ids = [case.case_id for case in values]
    if len(case_ids) != len(set(case_ids)):
        raise IntentAbConfigurationError("A/B case IDs must be unique")
    return tuple(sorted(values, key=lambda case: case.case_id))


def _validate_adapters(
    adapters: Mapping[str, IntentAdapter],
) -> tuple[_ModelIdentity, ...]:
    if not isinstance(adapters, Mapping) or not adapters:
        raise IntentAbConfigurationError(
            "at least one injected adapter is required"
        )
    identities: list[_ModelIdentity] = []
    for label in sorted(adapters):
        if label not in _APPROVED_MODELS:
            raise IntentAbConfigurationError(
                "adapter model is not approved for this frozen A/B"
            )
        adapter = adapters[label]
        provider = getattr(adapter, "provider", None)
        model = getattr(adapter, "model", None)
        prompt_version = getattr(adapter, "prompt_version", None)
        identity_values = (label, provider, model, prompt_version)
        if (
            any(
                not isinstance(value, str)
                or not _IDENTITY_PATTERN.fullmatch(value)
                for value in identity_values
            )
            or model != label
            or not callable(getattr(adapter, "propose", None))
        ):
            raise IntentAbConfigurationError(
                "injected adapter identity is invalid"
            )
        identities.append(
            _ModelIdentity(
                label=label,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
            )
        )
    return tuple(identities)


def _validate_evaluator(
    evaluator: PipelineEvaluator | None,
) -> PipelineEvaluator:
    if evaluator is None:
        return MinimalTaskPlanEvaluator()
    if not callable(getattr(evaluator, "evaluate", None)):
        raise IntentAbConfigurationError(
            "pipeline evaluator must expose evaluate"
        )
    return evaluator


def _prepare_output_directory(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    if absolute.exists() and (
        absolute.is_symlink() or not absolute.is_dir()
    ):
        raise IntentAbConfigurationError(
            "A/B output directory is invalid"
        )
    try:
        absolute.mkdir(parents=True, exist_ok=True, mode=0o700)
        if any(absolute.iterdir()):
            raise IntentAbConfigurationError(
                "A/B output directory must be empty"
            )
    except OSError as exc:
        raise IntentAbConfigurationError(
            "A/B output directory is unavailable"
        ) from exc
    return absolute


def _case_manifest_sha256(cases: Sequence[IntentCase]) -> str:
    content = b"".join(
        _canonical_json_bytes(_legacy_v2_case_payload(case)) + b"\n"
        for case in cases
    )
    return hashlib.sha256(content).hexdigest()


def _legacy_v2_case_payload(case: IntentCase) -> dict[str, object]:
    payload = case.model_dump(mode="json")
    before = payload.get("before_state")
    if isinstance(before, dict):
        before.pop("concepts", None)
    expected = payload.get("expected")
    if isinstance(expected, dict):
        final_state = expected.get("final_state")
        if isinstance(final_state, dict):
            final_state.pop("concepts", None)
    return payload


def _run_case(
    *,
    case: IntentCase,
    model: str,
    adapter: IntentAdapter,
    evaluator: PipelineEvaluator,
) -> tuple[_NormalizedResult, _RuntimeResult]:
    started = time.perf_counter_ns()
    status: Literal[
        "ok",
        "schema_invalid",
        "provider_failure",
        "adapter_error",
        "pipeline_error",
    ] = "ok"
    proposal: SemanticIntentProposal | None = None
    usage = AdapterUsage()
    raw_proposal: object | None = None
    merger_invocation_count: int | None = 0
    task_plan_invocation_count: int | None = 0
    evaluation: PipelineEvaluation | None = None
    evaluation_failure: PipelineEvaluationFailure | None = None
    provider_failure_code: NormalizedProviderFailureCode | None = None
    semantic_failure_code: SemanticProviderFailureCode | None = None
    schema_diagnostic: SemanticSchemaDiagnostic | None = None
    initial_failure_layer: EarliestFailureLayer | None = None
    try:
        raw_result = adapter.propose(case.message, case.context)
        if isinstance(raw_result, AbInvocation):
            raw_proposal = raw_result.proposal
            usage = raw_result.usage
        else:
            raw_proposal = raw_result
        proposal = _validate_proposal(raw_proposal)
    except ValidationError as error:
        status = "schema_invalid"
        semantic_failure_code = _semantic_validation_failure_code(
            error
        )
        schema_diagnostic = build_semantic_schema_diagnostic(
            error,
            stage=SemanticSchemaDiagnosticStage.PRIMARY,
            repair_outcome=(
                SemanticSchemaRepairOutcome.NOT_ATTEMPTED
            ),
        )
        initial_failure_layer = EarliestFailureLayer.SEMANTIC_SCHEMA
    except SemanticProviderFailure as failure:
        semantic_failure_code = failure.code
        if failure.code in {
            SemanticProviderFailureCode.INVALID_OUTPUT,
            SemanticProviderFailureCode.FORBIDDEN_OUTPUT,
        }:
            status = "schema_invalid"
            schema_diagnostic = failure.diagnostic
            initial_failure_layer = (
                EarliestFailureLayer.SEMANTIC_SCHEMA
            )
        else:
            status = "provider_failure"
            provider_failure_code = _redacted_provider_failure_code(
                failure.code
            )
            initial_failure_layer = (
                EarliestFailureLayer.PROVIDER_TRANSPORT
            )
    except Exception:
        status = "adapter_error"
    if proposal is not None or semantic_failure_code is not None:
        merger_invocation_count = None
        task_plan_invocation_count = None
        try:
            (
                merger_invocation_count,
                task_plan_invocation_count,
                pipeline_result,
            ) = _run_task5_pipeline(
                case=case,
                model=model,
                proposal=proposal,
                semantic_failure_code=semantic_failure_code,
                evaluator=evaluator,
            )
            if isinstance(
                pipeline_result,
                PipelineEvaluationFailure,
            ):
                status = "pipeline_error"
                evaluation_failure = pipeline_result
            else:
                evaluation = pipeline_result
        except Exception:
            status = "pipeline_error"
    latency_ms = max(
        0.0,
        round((time.perf_counter_ns() - started) / 1_000_000, 6),
    )

    schema_valid = proposal is not None
    goal_correct = bool(
        proposal is not None
        and proposal.goal is case.expected.goal
        and (
            proposal.goal is UnderstandingGoal.CLARIFICATION
        )
        == case.expected.must_clarify
    )
    topic_correct = bool(
        proposal is not None
        and proposal.topic is case.expected.topic
    )
    concern_correct = bool(
        proposal is not None
        and _typed_records_match_exactly(
            proposal.concerns,
            case.expected.concerns,
        )
    )
    observation_correct = bool(
        proposal is not None
        and _typed_records_match_exactly(
            proposal.observations,
            case.expected.observations,
        )
    )
    reference_correct = bool(
        proposal is not None
        and proposal.references == case.expected.references
    )
    critical_failure = bool(
        case.critical
        and not (
            schema_valid
            and goal_correct
            and topic_correct
            and concern_correct
            and observation_correct
            and reference_correct
        )
    )
    normalized = _NormalizedResult(
        case_id=case.case_id,
        model=model,
        status=status,
        provider_failure_code=provider_failure_code,
        schema_diagnostic=schema_diagnostic,
        earliest_failure_layer=_earliest_failure_layer(
            status=status,
            initial=initial_failure_layer,
            goal_correct=goal_correct,
            topic_correct=topic_correct,
            concern_correct=concern_correct,
            observation_correct=observation_correct,
            reference_correct=reference_correct,
            evaluation=evaluation,
            evaluation_failure=evaluation_failure,
        ),
        schema_valid=schema_valid,
        goal_correct=goal_correct,
        topic_correct=topic_correct,
        concern_correct=concern_correct,
        observation_correct=observation_correct,
        reference_correct=reference_correct,
        critical_failure=critical_failure,
        actual=(
            proposal.model_dump(mode="json")
            if proposal is not None
            else None
        ),
        pipeline=_PipelineObservation(
            strict_validation_passed=schema_valid,
            merger_invocation_count=merger_invocation_count,
            task_plan_invocation_count=task_plan_invocation_count,
            hard_constraint_override_count=(
                evaluation.hard_constraint_override_count
                if evaluation is not None
                else None
            ),
            unauthorized_constraint_transition_count=(
                evaluation.unauthorized_constraint_transition_count
                if evaluation is not None
                else None
            ),
            task_plan_mismatch_count=(
                evaluation.task_plan_mismatch_count
                if evaluation is not None
                else None
            ),
            forbidden_field_acceptance_count=int(
                _contains_forbidden_fields(raw_proposal)
                and schema_valid
            ),
            invalid_output_task_plan_invocation_count=(
                int(
                    not schema_valid
                    and proposal is not None
                    and task_plan_invocation_count is not None
                    and task_plan_invocation_count > 0
                )
            ),
            evaluator_failure_code=(
                evaluation_failure.code
                if evaluation_failure is not None
                else None
            ),
            product_selection_invocation_count=(
                evaluation.product_selection_invocation_count
                if evaluation is not None
                else None
            ),
            wrong_product_selection_count=(
                evaluation.wrong_product_selection_count
                if evaluation is not None
                else None
            ),
            legacy_fallback_count=(
                evaluation.legacy_fallback_count
                if evaluation is not None
                else (
                    evaluation_failure.legacy_fallback_count
                    if evaluation_failure is not None
                    else None
                )
            ),
        ),
    )
    runtime = _RuntimeResult(
        case_id=case.case_id,
        model=model,
        latency_ms=latency_ms,
        usage=_usage_payload(usage),
    )
    return normalized, runtime


def _run_task5_pipeline(
    *,
    case: IntentCase,
    model: str,
    proposal: SemanticIntentProposal | None,
    semantic_failure_code: SemanticProviderFailureCode | None,
    evaluator: PipelineEvaluator,
) -> tuple[
    int | None,
    int | None,
    PipelineEvaluation | PipelineEvaluationFailure,
]:
    exact_constraints, exact_issues = parse_exact_constraints(
        case.message
    )
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
    base_task = plan_task(validated_merged)
    transition_plan = plan_code_owned_transitions(
        message=case.message,
        understanding=validated_merged,
        task=base_task,
        previous=case.before_state,
    )
    task = transition_plan.task_plan
    validated_task = TaskPlan.model_validate(
        task.model_dump(
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
        task_plan=validated_task,
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
        validated_failure = PipelineEvaluationFailure.model_validate(
            observed.model_dump(
                mode="python",
                round_trip=True,
                warnings=False,
            ),
            strict=True,
        )
        return (None, None, validated_failure)
    if not isinstance(observed, PipelineEvaluation):
        raise TypeError(
            "pipeline evaluator must return a typed evaluation result"
        )
    validated_observation = PipelineEvaluation.model_validate(
        observed.model_dump(
            mode="python",
            round_trip=True,
            warnings=False,
        ),
        strict=True,
    )
    return (
        int(proposal is not None),
        int(proposal is not None),
        validated_observation,
    )


def _compile_expected_task_constraints(
    merged: StructuredUnderstanding,
) -> list[object]:
    return list(compile_task_constraints(merged))


def _expected_task_mode(
    *,
    request: PipelineEvaluationRequest,
    expected_constraints: Sequence[object],
) -> Literal[
    "recommend",
    "comparison",
    "suitability",
    "knowledge",
    "followup",
    "clarify",
]:
    if request.expected.must_clarify or request.merged.uncertainties:
        return "clarify"
    goal_mode = {
        UnderstandingGoal.COMPARISON: "comparison",
        UnderstandingGoal.SUITABILITY: "suitability",
        UnderstandingGoal.KNOWLEDGE: "knowledge",
        UnderstandingGoal.FOLLOWUP: "followup",
    }.get(request.expected.goal)
    if goal_mode is not None:
        return goal_mode
    if request.expected.goal is not UnderstandingGoal.RECOMMENDATION:
        return "clarify"
    category = next(
        (
            item
            for item in expected_constraints
            if isinstance(item, CategoryConstraint)
        ),
        None,
    )
    if category is None:
        return "clarify"
    return "recommend"


def _task_topic_matches_expected(
    *,
    request: PipelineEvaluationRequest,
    expected_constraints: Sequence[object],
) -> bool:
    expected_topics = [
        item.value
        for item in expected_constraints
        if isinstance(item, CategoryConstraint)
    ]
    actual_topics = [
        item.value
        for item in request.task_plan.constraints
        if isinstance(item, CategoryConstraint)
    ]
    if actual_topics != expected_topics:
        return False
    if request.merged.uncertainties:
        return True
    return request.merged.topic is request.expected.topic


def _typed_records_match_exactly(
    expected: Sequence[object],
    actual: Sequence[object],
) -> bool:
    return Counter(_record_bytes(item) for item in expected) == Counter(
        _record_bytes(item)
        for item in actual
    )


def _record_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _canonical_json_bytes(value)


def _hard_constraint_override_count(
    *,
    exact_constraints: Sequence[object],
    merged: StructuredUnderstanding,
    task_constraints: Sequence[object],
) -> int:
    expected = [
        item
        for item in exact_constraints
        if isinstance(item, _EXACT_HARD_CONSTRAINT_TYPES)
    ]
    merged_hard = [
        item
        for item in merged.exact_constraints
        if isinstance(item, _EXACT_HARD_CONSTRAINT_TYPES)
    ]
    return int(
        not _contains_all_typed_records(expected, merged_hard)
        or not _contains_all_typed_records(
            expected,
            task_constraints,
        )
    )


def _unauthorized_transition_count(
    request: PipelineEvaluationRequest,
) -> int:
    expected_state = request.expected.final_state
    if expected_state is None:
        return 0
    if request.task_plan.mode != "recommend":
        return 0
    try:
        actual_state = task_plan_to_query_context(
            request.task_plan
        )
    except ValueError:
        return 1
    expected_transitions = tuple(
        (item.target, item.operation)
        for item in request.expected.transitions
    )
    actual_transitions = tuple(
        (item.target, item.operation)
        for item in request.transitions
    )
    return int(
        actual_state != expected_state
        or actual_transitions != expected_transitions
    )


def _contains_all_typed_records(
    expected: Sequence[object],
    actual: Sequence[object],
) -> bool:
    expected_counts = Counter(
        _typed_record_bytes(item)
        for item in expected
    )
    actual_counts = Counter(
        _typed_record_bytes(item)
        for item in actual
    )
    return all(
        actual_counts[record] >= count
        for record, count in expected_counts.items()
    )


def _typed_record_bytes(value: object) -> bytes:
    if not isinstance(value, BaseModel):
        raise TypeError("pipeline records must be typed models")
    return _canonical_json_bytes(value.model_dump(mode="json"))


def _contains_forbidden_fields(value: object) -> bool:
    payload: object = value
    if isinstance(value, (str, bytes, bytearray)):
        try:
            payload = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError):
            return False
    if not isinstance(payload, Mapping):
        return False
    return not set(payload).issubset(
        SemanticIntentProposal.model_fields
    )


def _validate_proposal(value: object) -> SemanticIntentProposal:
    if isinstance(value, SemanticIntentProposal):
        payload = value.model_dump(
            mode="python",
            round_trip=True,
            warnings=False,
        )
        return SemanticIntentProposal.model_validate(
            payload,
            strict=True,
        )
    if isinstance(value, (str, bytes, bytearray)):
        return SemanticIntentProposal.model_validate_json(
            value,
            strict=True,
        )
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise _invalid_proposal_error()
    return SemanticIntentProposal.model_validate_json(
        encoded,
        strict=True,
    )


def _redacted_validation_failure_code(
    error: ValidationError,
) -> NormalizedProviderFailureCode:
    if any(item["type"] == "extra_forbidden" for item in error.errors()):
        return NormalizedProviderFailureCode.FORBIDDEN
    return NormalizedProviderFailureCode.INVALID


def _semantic_validation_failure_code(
    error: ValidationError,
) -> SemanticProviderFailureCode:
    if any(item["type"] == "extra_forbidden" for item in error.errors()):
        return SemanticProviderFailureCode.FORBIDDEN_OUTPUT
    return SemanticProviderFailureCode.INVALID_OUTPUT


def _redacted_provider_failure_code(
    code: SemanticProviderFailureCode,
) -> NormalizedProviderFailureCode:
    return {
        SemanticProviderFailureCode.AUTHENTICATION_FAILED: (
            NormalizedProviderFailureCode.AUTHENTICATION
        ),
        SemanticProviderFailureCode.RATE_LIMITED: (
            NormalizedProviderFailureCode.RATE_LIMIT
        ),
        SemanticProviderFailureCode.PROVIDER_UNAVAILABLE: (
            NormalizedProviderFailureCode.UNAVAILABLE
        ),
        SemanticProviderFailureCode.PROVIDER_REJECTED: (
            NormalizedProviderFailureCode.REJECTED
        ),
        SemanticProviderFailureCode.TIMEOUT: (
            NormalizedProviderFailureCode.TIMEOUT
        ),
        SemanticProviderFailureCode.EMPTY_RESPONSE: (
            NormalizedProviderFailureCode.EMPTY
        ),
        SemanticProviderFailureCode.INVALID_RESPONSE: (
            NormalizedProviderFailureCode.INVALID
        ),
        SemanticProviderFailureCode.INVALID_OUTPUT: (
            NormalizedProviderFailureCode.INVALID
        ),
        SemanticProviderFailureCode.FORBIDDEN_OUTPUT: (
            NormalizedProviderFailureCode.FORBIDDEN
        ),
        SemanticProviderFailureCode.DAILY_BUDGET_EXCEEDED: (
            NormalizedProviderFailureCode.BUDGET
        ),
        SemanticProviderFailureCode.DAILY_CALL_CAP_EXCEEDED: (
            NormalizedProviderFailureCode.CALL_CAP
        ),
    }[code]


def _earliest_failure_layer(
    *,
    status: str,
    initial: EarliestFailureLayer | None,
    goal_correct: bool,
    topic_correct: bool,
    concern_correct: bool,
    observation_correct: bool,
    reference_correct: bool,
    evaluation: PipelineEvaluation | None,
    evaluation_failure: PipelineEvaluationFailure | None,
) -> EarliestFailureLayer:
    if initial is not None:
        return initial
    if status == "adapter_error":
        return EarliestFailureLayer.ADAPTER
    if not (
        goal_correct
        and topic_correct
        and concern_correct
        and observation_correct
        and reference_correct
    ):
        return EarliestFailureLayer.SEMANTIC_PROPOSAL
    if (
        status == "pipeline_error"
        or evaluation_failure is not None
    ):
        return EarliestFailureLayer.PIPELINE
    if evaluation is None:
        return EarliestFailureLayer.PIPELINE
    if (
        evaluation.task_plan_mismatch_count
        or evaluation.hard_constraint_override_count
        or evaluation.unauthorized_constraint_transition_count
    ):
        return EarliestFailureLayer.TASK_PLAN
    if evaluation.wrong_product_selection_count:
        return EarliestFailureLayer.RETRIEVAL_DECISION
    if evaluation.legacy_fallback_count:
        return EarliestFailureLayer.PUBLIC_ROUTING
    if (
        evaluation.product_selection_invocation_count is None
        or evaluation.wrong_product_selection_count is None
        or evaluation.legacy_fallback_count is None
    ):
        return EarliestFailureLayer.PIPELINE
    return EarliestFailureLayer.NONE


def _invalid_proposal_error() -> ValidationError:
    return ValidationError.from_exception_data(
        "SemanticIntentProposal",
        [
            {
                "type": "model_type",
                "loc": (),
                "input": None,
                "ctx": {"class_name": "SemanticIntentProposal"},
            }
        ],
    )


def _usage_payload(usage: AdapterUsage) -> dict[str, object]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "cached_tokens": usage.cached_tokens,
    }


def _summarize_model(
    rows: Sequence[_NormalizedResult],
) -> IntentModelSummary:
    case_count = len(rows)
    schema_valid_count = sum(row.schema_valid for row in rows)
    goal_correct_count = sum(row.goal_correct for row in rows)
    topic_correct_count = sum(row.topic_correct for row in rows)
    concern_correct_count = sum(
        row.concern_correct for row in rows
    )
    observation_correct_count = sum(
        row.observation_correct for row in rows
    )
    reference_correct_count = sum(
        row.reference_correct for row in rows
    )
    critical_failure_count = sum(
        row.critical_failure for row in rows
    )
    hard_gates = _hard_gate_summary(
        rows,
        critical_failure_count=critical_failure_count,
    )
    return IntentModelSummary(
        passed=bool(
            case_count >= _MINIMUM_CASE_COUNT
            and schema_valid_count == case_count
            and goal_correct_count == case_count
            and topic_correct_count == case_count
            and concern_correct_count == case_count
            and observation_correct_count == case_count
            and reference_correct_count == case_count
            and critical_failure_count == 0
            and hard_gates.passed
        ),
        case_count=case_count,
        schema_valid_count=schema_valid_count,
        goal_correct_count=goal_correct_count,
        topic_correct_count=topic_correct_count,
        concern_correct_count=concern_correct_count,
        observation_correct_count=observation_correct_count,
        reference_correct_count=reference_correct_count,
        critical_failure_count=critical_failure_count,
        schema_valid_rate=_rate(schema_valid_count, case_count),
        goal_accuracy=_rate(goal_correct_count, case_count),
        topic_accuracy=_rate(topic_correct_count, case_count),
        concern_accuracy=_rate(concern_correct_count, case_count),
        observation_accuracy=_rate(
            observation_correct_count,
            case_count,
        ),
        reference_accuracy=_rate(
            reference_correct_count,
            case_count,
        ),
        hard_gates=hard_gates,
    )


def _hard_gate_summary(
    rows: Sequence[_NormalizedResult],
    *,
    critical_failure_count: int,
) -> HardGateSummary:
    forbidden_field_acceptance_count = sum(
        row.pipeline.forbidden_field_acceptance_count
        for row in rows
    )
    invalid_output_task_plan_invocation_count = sum(
        row.pipeline.invalid_output_task_plan_invocation_count
        for row in rows
    )
    untyped_failure_count = sum(
        row.status == "adapter_error"
        or (
            row.status == "pipeline_error"
            and row.pipeline.evaluator_failure_code is None
        )
        for row in rows
    )
    evaluator_failure_count = sum(
        row.pipeline.evaluator_failure_code is not None
        for row in rows
    )
    pipeline_available = bool(rows) and all(
        row.pipeline.merger_invocation_count is not None
        and row.pipeline.task_plan_invocation_count is not None
        and row.pipeline.task_plan_mismatch_count is not None
        and row.pipeline.hard_constraint_override_count is not None
        and (
            row.pipeline.unauthorized_constraint_transition_count
            is not None
        )
        for row in rows
    )
    merger_invocation_count = (
        sum(
            row.pipeline.merger_invocation_count or 0
            for row in rows
        )
        if pipeline_available
        else None
    )
    task_plan_invocation_count = (
        sum(
            row.pipeline.task_plan_invocation_count or 0
            for row in rows
        )
        if pipeline_available
        else None
    )
    task_plan_mismatch_count = (
        sum(
            row.pipeline.task_plan_mismatch_count or 0
            for row in rows
        )
        if pipeline_available
        else None
    )
    hard_constraint_override_count = (
        sum(
            row.pipeline.hard_constraint_override_count or 0
            for row in rows
        )
        if pipeline_available
        else None
    )
    unauthorized_constraint_transition_count = (
        sum(
            (
                row.pipeline
                .unauthorized_constraint_transition_count
                or 0
            )
            for row in rows
        )
        if pipeline_available
        else None
    )
    product_selection_available = bool(rows) and all(
        row.pipeline.product_selection_invocation_count is not None
        and row.pipeline.wrong_product_selection_count is not None
        for row in rows
    )
    product_selection_invocation_count = (
        sum(
            row.pipeline.product_selection_invocation_count or 0
            for row in rows
        )
        if product_selection_available
        else None
    )
    wrong_product_selection_count = (
        sum(
            row.pipeline.wrong_product_selection_count or 0
            for row in rows
        )
        if product_selection_available
        else None
    )
    legacy_fallback_available = bool(rows) and all(
        row.pipeline.legacy_fallback_count is not None
        for row in rows
    )
    legacy_fallback_count = (
        sum(
            row.pipeline.legacy_fallback_count or 0
            for row in rows
        )
        if legacy_fallback_available
        else None
    )
    passed = (
        critical_failure_count == 0
        and pipeline_available
        and hard_constraint_override_count == 0
        and unauthorized_constraint_transition_count == 0
        and forbidden_field_acceptance_count == 0
        and invalid_output_task_plan_invocation_count == 0
        and task_plan_mismatch_count == 0
        and untyped_failure_count == 0
        and evaluator_failure_count == 0
        and product_selection_available
        and wrong_product_selection_count == 0
        and legacy_fallback_available
        and legacy_fallback_count == 0
    )
    return HardGateSummary(
        passed=passed,
        critical_failure_count=critical_failure_count,
        pipeline_status=(
            "AVAILABLE" if pipeline_available else "UNAVAILABLE"
        ),
        merger_invocation_count=merger_invocation_count,
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
        untyped_failure_count=untyped_failure_count,
        evaluator_failure_count=evaluator_failure_count,
        task_plan_invocation_count=task_plan_invocation_count,
        task_plan_mismatch_count=task_plan_mismatch_count,
        product_selection_status=(
            "AVAILABLE"
            if product_selection_available
            else "UNAVAILABLE"
        ),
        product_selection_invocation_count=(
            product_selection_invocation_count
        ),
        wrong_product_selection_count=wrong_product_selection_count,
        legacy_fallback_status=(
            "AVAILABLE"
            if legacy_fallback_available
            else "UNAVAILABLE"
        ),
        legacy_fallback_count=legacy_fallback_count,
    )


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _latency_summary(values: Sequence[float]) -> LatencySummary:
    ordered = sorted(values)
    return LatencySummary(
        p50=_nearest_rank(ordered, 0.50),
        p95=_nearest_rank(ordered, 0.95),
    )


def _nearest_rank(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = max(0, math.ceil(len(values) * quantile) - 1)
    return values[index]


def _summarize_runtime(
    rows: Sequence[_RuntimeResult],
) -> IntentRuntimeSummary:
    return IntentRuntimeSummary(
        latency_ms=_latency_summary(
            [row.latency_ms for row in rows]
        ),
        usage=_usage_summary(rows),
    )


def _usage_summary(
    rows: Sequence[_RuntimeResult],
) -> UsageSummary:
    token_names = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
    )
    totals: dict[str, int | None] = {}
    for name in token_names:
        values = [row.usage[name] for row in rows]
        if values and all(
            isinstance(value, int)
            and not isinstance(value, bool)
            for value in values
        ):
            totals[name] = sum(
                int(value)
                for value in values
            )
        else:
            totals[name] = None
    availability = (
        "AVAILABLE"
        if all(totals[name] is not None for name in token_names)
        else "UNAVAILABLE"
    )
    return UsageSummary(
        availability=availability,
        **totals,
    )


def _select_model(
    summaries: Mapping[str, IntentModelSummary],
) -> str | None:
    passing = {
        model
        for model, summary in summaries.items()
        if summary.passed
    }
    for preferred in (_FLASH_MODEL, _BASELINE_MODEL):
        if preferred in passing:
            return preferred
    return min(passing) if passing else None


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor = -1
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as temporary:
            descriptor = -1
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    except OSError as exc:
        raise IntentAbConfigurationError(
            "A/B evidence could not be written"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
