from __future__ import annotations

import ast
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from threading import Event, Lock, current_thread
from threading import enumerate as enumerate_threads
import time

import pytest

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticSchemaDiagnostic,
    SemanticSchemaDiagnosticKind,
    SemanticSchemaDiagnosticPath,
    SemanticSchemaDiagnosticStage,
    SemanticSchemaRepairOutcome,
)
from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    SemanticIntentProposal,
    SemanticPreferenceCandidate,
    SemanticPreferenceField,
    SemanticPreferenceStrength,
)
from tools.guide_gates import intent_model_ab
from tools.guide_gates.intent_model_ab import (
    AbInvocation,
    AdapterResult,
    AdapterUsage,
    IntentAbConfigurationError,
    IntentCase,
    IntentCaseError,
    IntentExpected,
    PipelineEvaluation,
    PipelineEvaluationFailure,
    PipelineEvaluationFailureCode,
    load_cases,
    main,
    run_ab,
)


HISTORICAL_CASES_PATH = Path(
    "tests/fixtures/guide/intent/semantic_intent_ab_v1.jsonl"
)
CASES_PATH = Path(
    "tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl"
)
FLASH_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
BASELINE_MODEL = "deepseek-ai/DeepSeek-V3.2"
FAKE_KEY = "fake-secret-key-must-never-be-persisted"
FAKE_AUTHORIZATION = "Bearer fake-full-authorization-must-not-leak"
FAKE_PROFILE = "profile-secret-value-must-not-leak"
FAKE_PRODUCT_FACT = "product-secret-fact"


def test_gate_contract_evaluates_final_state_not_model_acts() -> None:
    assert "acts" not in IntentExpected.model_fields
    assert (
        "unauthorized_constraint_transition_count"
        in PipelineEvaluation.model_fields
    )


def _proposal_for(case: IntentCase) -> SemanticIntentProposal:
    payload = {
        "goal": case.expected.goal.value,
        "topic": (
            case.expected.topic.value
            if case.expected.topic is not None
            else None
        ),
        "concerns": [
            concern.value
            for concern in case.expected.concerns
        ],
        "observations": [
            observation.model_dump(mode="json")
            for observation in case.expected.observations
        ],
        "references": [
            reference.model_dump(mode="json")
            for reference in case.expected.references
        ],
        "confidence": 0.99,
        "clarification_hint": (
            ClarificationCode.GOAL.value
            if case.expected.must_clarify
            else None
        ),
    }
    return SemanticIntentProposal.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )


class StaticIntentAdapter:
    provider = "offline-fake"
    prompt_version = "offline-fake-prompt-v1"

    def __init__(
        self,
        *,
        cases: tuple[IntentCase, ...],
        model: str,
    ) -> None:
        self.model = model
        self._by_message = {case.message: case for case in cases}
        self.api_key_marker = FAKE_KEY
        self.authorization = FAKE_AUTHORIZATION
        self.full_profile = FAKE_PROFILE
        self.product_facts = FAKE_PRODUCT_FACT

    def propose(self, message, context):
        case = self._by_message[message]
        assert context == case.context
        return AbInvocation(
            proposal=_proposal_for(case),
            usage=AdapterUsage(
                prompt_tokens=11,
                completion_tokens=7,
                total_tokens=18,
                cached_tokens=3,
                cost_cny=Decimal("0.001"),
            ),
            product_selection_invocation_count=0,
            wrong_product_selection_count=0,
            legacy_fallback_count=0,
        )


class InvalidOutputAdapter(StaticIntentAdapter):
    def propose(self, message, context):
        result = super().propose(message, context)
        payload = result.proposal.model_dump(mode="json")
        payload["product_ids"] = [42]
        payload["product_facts"] = FAKE_PRODUCT_FACT
        return AdapterResult(
            proposal=payload,
            usage=result.usage,
        )


class InvalidActsAdapter(StaticIntentAdapter):
    def propose(self, message, context):
        result = super().propose(message, context)
        payload = result.proposal.model_dump(mode="json")
        payload["acts"] = [
            {
                "kind": "withdraw_constraint",
                "target": "product_42",
            }
        ]
        return AdapterResult(
            proposal=payload,
            usage=result.usage,
        )


class MalformedJsonAdapter(StaticIntentAdapter):
    def propose(self, message, context):
        result = super().propose(message, context)
        return AdapterResult(
            proposal=b'{"goal":',
            usage=result.usage,
        )


class FailingIntentAdapter(StaticIntentAdapter):
    def propose(self, message, context):
        del message, context
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
        )


class FailureMatrixIntentAdapter(StaticIntentAdapter):
    def __init__(
        self,
        *,
        cases: tuple[IntentCase, ...],
        model: str,
        failure_codes: tuple[SemanticProviderFailureCode, ...],
    ) -> None:
        super().__init__(cases=cases, model=model)
        self._failure_by_message = {
            case.message: failure_codes[index % len(failure_codes)]
            for index, case in enumerate(cases)
        }

    def propose(self, message, context):
        del context
        raise SemanticProviderFailure(
            self._failure_by_message[message],
            status_code=599,
        )


class DiagnosticFailureAdapter(StaticIntentAdapter):
    def propose(self, message, context):
        del message, context
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_OUTPUT,
            diagnostic=SemanticSchemaDiagnostic(
                stage=SemanticSchemaDiagnosticStage.REPAIR,
                kind=SemanticSchemaDiagnosticKind.ENUM,
                path=SemanticSchemaDiagnosticPath.GOAL,
                count=2,
                truncated=False,
                repair_outcome=SemanticSchemaRepairOutcome.FAILED,
            ),
        )


class UninstrumentedIntentAdapter(StaticIntentAdapter):
    def propose(self, message, context):
        result = super().propose(message, context)
        return AbInvocation(
            proposal=result.proposal,
            usage=result.usage,
        )


class UnknownUsageAdapter(StaticIntentAdapter):
    def propose(self, message, context):
        result = super().propose(message, context)
        return AbInvocation(
            proposal=result.proposal,
            usage=AdapterUsage(),
            product_selection_invocation_count=0,
            wrong_product_selection_count=0,
            legacy_fallback_count=0,
        )


class InjectedGateFailureAdapter(StaticIntentAdapter):
    def __init__(
        self,
        *,
        cases: tuple[IntentCase, ...],
        model: str,
        injected: dict[str, int],
    ) -> None:
        super().__init__(cases=cases, model=model)
        self._injected = injected

    def propose(self, message, context):
        result = super().propose(message, context)
        instrumentation = {
            "product_selection_invocation_count": (
                result.product_selection_invocation_count
            ),
            "wrong_product_selection_count": (
                result.wrong_product_selection_count
            ),
            "legacy_fallback_count": result.legacy_fallback_count,
            **self._injected,
        }
        return AbInvocation(
            proposal=result.proposal,
            usage=result.usage,
            **instrumentation,
        )


class InjectedSemanticFieldsAdapter(StaticIntentAdapter):
    def propose(self, message, context):
        result = super().propose(message, context)
        payload = result.proposal.model_dump(mode="json")
        payload["concerns"].append("price")
        payload["observations"].append(
            {
                "code": "redness",
                "present": True,
                "qualifier": None,
            }
        )
        return AbInvocation(
            proposal=payload,
            usage=result.usage,
            product_selection_invocation_count=0,
            wrong_product_selection_count=0,
            legacy_fallback_count=0,
        )


class MissingSemanticFieldsAdapter(StaticIntentAdapter):
    def propose(self, message, context):
        result = super().propose(message, context)
        payload = result.proposal.model_dump(mode="json")
        payload["concerns"] = []
        payload["observations"] = []
        return AbInvocation(
            proposal=payload,
            usage=result.usage,
        )


class TrustedPipelineEvaluator:
    def __init__(
        self,
        *,
        wrong_product_selection_count: int = 0,
        legacy_fallback_count: int = 0,
    ) -> None:
        self.requests = []
        self._wrong_product_selection_count = (
            wrong_product_selection_count
        )
        self._legacy_fallback_count = legacy_fallback_count

    def evaluate(self, request):
        from tools.guide_gates.intent_model_ab import (
            MinimalTaskPlanEvaluator,
        )

        self.requests.append(request)
        minimal = MinimalTaskPlanEvaluator().evaluate(request)
        return minimal.model_copy(
            update={
                "product_selection_invocation_count": (
                    self._wrong_product_selection_count
                ),
                "wrong_product_selection_count": (
                    self._wrong_product_selection_count
                ),
                "legacy_fallback_count": self._legacy_fallback_count,
            }
        )


class UntypedPipelineEvaluator:
    def evaluate(self, request):
        del request
        return {
            "task_plan_mismatch_count": 0,
            "hard_constraint_override_count": 0,
        }


class TypedFailingPipelineEvaluator:
    def evaluate(self, request):
        del request
        return PipelineEvaluationFailure(
            code=PipelineEvaluationFailureCode.STREAM_FAILED
        )


class NonePipelineEvaluator:
    def evaluate(self, request):
        del request
        return None


class MixedAvailabilityPipelineEvaluator(TrustedPipelineEvaluator):
    def __init__(self, unavailable_case_id: str) -> None:
        super().__init__()
        self._unavailable_case_id = unavailable_case_id

    def evaluate(self, request):
        if request.case_id == self._unavailable_case_id:
            return None
        return super().evaluate(request)


class ModelConcurrencyProbe:
    def __init__(self) -> None:
        self.lock = Lock()
        self.started_models: set[str] = set()
        self.both_models_started = Event()
        self.total_inflight = 0
        self.max_total_inflight = 0
        self.model_inflight: dict[str, int] = {}
        self.max_model_inflight: dict[str, int] = {}
        self.case_ids: dict[str, list[str]] = {}
        self.thread_ids: dict[str, set[int]] = {}


class LockCheckingEvaluator(TrustedPipelineEvaluator):
    def __init__(self) -> None:
        super().__init__()
        self._lock = Lock()
        self._both_entered = Event()
        self._competition_open = True
        self._inflight = 0
        self.max_inflight = 0

    def evaluate(self, request):
        with self._lock:
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
            should_wait = self._competition_open
            if self._inflight == 2:
                self._both_entered.set()
                self._competition_open = False
        try:
            if should_wait:
                self._both_entered.wait(timeout=0.05)
                with self._lock:
                    self._competition_open = False
            return super().evaluate(request)
        finally:
            with self._lock:
                self._inflight -= 1


class ConcurrentRecordingAdapter(StaticIntentAdapter):
    def __init__(
        self,
        *,
        cases: tuple[IntentCase, ...],
        model: str,
        probe: ModelConcurrencyProbe,
    ) -> None:
        super().__init__(cases=cases, model=model)
        self._probe = probe

    def propose(self, message, context):
        case = self._by_message[message]
        thread_id = current_thread().ident
        assert thread_id is not None
        with self._probe.lock:
            self._probe.started_models.add(self.model)
            if len(self._probe.started_models) == 2:
                self._probe.both_models_started.set()
            self._probe.total_inflight += 1
            model_inflight = (
                self._probe.model_inflight.get(self.model, 0) + 1
            )
            self._probe.model_inflight[self.model] = model_inflight
            self._probe.max_total_inflight = max(
                self._probe.max_total_inflight,
                self._probe.total_inflight,
            )
            self._probe.max_model_inflight[self.model] = max(
                self._probe.max_model_inflight.get(self.model, 0),
                model_inflight,
            )
            self._probe.case_ids.setdefault(self.model, []).append(
                case.case_id
            )
            self._probe.thread_ids.setdefault(self.model, set()).add(
                thread_id
            )
        try:
            if len(self._probe.case_ids[self.model]) == 1:
                self._probe.both_models_started.wait(timeout=0.5)
            return super().propose(message, context)
        finally:
            with self._probe.lock:
                self._probe.total_inflight -= 1
                self._probe.model_inflight[self.model] -= 1


def _cli_args(output_dir: Path) -> list[str]:
    return [
        "--cases",
        str(CASES_PATH),
        "--output-dir",
        str(output_dir),
    ]


def _assert_sha256sums(output_dir: Path) -> None:
    rows = (
        output_dir / "SHA256SUMS"
    ).read_text(encoding="ascii").splitlines()
    assert len(rows) == 3
    for row in rows:
        digest, filename = row.split("  ", maxsplit=1)
        assert digest == hashlib.sha256(
            (output_dir / filename).read_bytes()
        ).hexdigest()


def test_frozen_cases_cover_required_semantic_matrix() -> None:
    raw_rows = [
        json.loads(line)
        for line in CASES_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert all(
        {"concerns", "observations"} <= set(row["expected"])
        for row in raw_rows
    )

    cases = load_cases(CASES_PATH)

    assert len(cases) == 128
    assert {case.expected.goal for case in cases} == (
        set(UnderstandingGoal) - {UnderstandingGoal.IMAGE_IDENTITY}
    )
    paraphrase_topics = {
        case.expected.topic
        for case in cases
        if "category_paraphrase" in case.tags
        and case.expected.topic is not None
    }
    assert len(paraphrase_topics) >= 6
    assert paraphrase_topics <= set(TopicCode)

    required_tags = {
        "alcohol",
        "alcohol_budget_revision",
        "assessment",
        "budget",
        "conflict",
        "low_information",
        "ordinal",
        "out_of_scope",
        "prompt_injection",
        "pronoun",
        "revision",
        "round9",
    }
    present_tags = {
        tag
        for case in cases
        for tag in case.tags
    }
    assert required_tags <= present_tags
    assert len({case.case_id for case in cases}) == len(cases)
    assert {
        reference.kind
        for case in cases
        for reference in case.expected.references
    } == {
        "current_item",
        "current_batch",
        "candidate_ordinal",
        "image_ordinal",
        "current_topic",
        "previous_constraint",
    }
    by_id = {case.case_id: case for case in cases}
    expected_reference_kinds = {
        "cmp-002-two-serums": ("current_batch",),
        "suit-001-sensitive-sunscreen": ("current_item",),
        "assess-013-pronoun-current": ("current_item",),
        "assess-014-revision-observation": ("previous_constraint",),
        "follow-010-budget-lower": ("previous_constraint",),
        "follow-016-colloquial-more": ("current_item",),
        "know-011-current-topic": ("current_topic",),
    }
    assert {
        case_id: tuple(
            reference.kind
            for reference in by_id[case_id].expected.references
        )
        for case_id in expected_reference_kinds
    } == expected_reference_kinds
    assert all("acts" not in row["expected"] for row in raw_rows)
    assessment_cases = [
        case
        for case in cases
        if "assessment" in case.tags
        and case.expected.goal is UnderstandingGoal.ASSESSMENT
    ]
    assert assessment_cases
    assert all(case.expected.concerns for case in assessment_cases)
    assert all(case.expected.observations for case in assessment_cases)


def test_v2_freeze_preserves_ids_and_limits_expected_label_changes() -> None:
    historical = [
        json.loads(line)
        for line in HISTORICAL_CASES_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    current = [
        json.loads(line)
        for line in CASES_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
    ]

    assert [row["case_id"] for row in current] == [
        row["case_id"] for row in historical
    ]
    assert len(current) == 128
    allowed_expected_changes = {
        "assess-001-post-cleanse-tight",
        "assess-004-cleanser-reaction",
        "assess-005-sunscreen-stinging",
        "assess-006-serum-redness",
        "suit-008-paraphrase-sunscreen",
        "clar-015-revision-missing-target",
        "follow-009-budget-revision",
        "follow-010-budget-lower",
        "follow-011-skin-revision",
    }
    historical_by_id = {
        row["case_id"]: row for row in historical
    }

    def without_contract_migration_fields(
        expected: dict[str, object],
    ) -> dict[str, object]:
        normalized = json.loads(json.dumps(expected))
        normalized.pop("acts", None)
        for reference in normalized.get("references", []):
            reference.pop("raw_text", None)
            reference.pop("start", None)
            reference.pop("end", None)
        return normalized

    for row in current:
        case_id = row["case_id"]
        if case_id not in allowed_expected_changes:
            assert without_contract_migration_fields(
                row["expected"]
            ) == without_contract_migration_fields(
                historical_by_id[case_id]["expected"]
            )
        assert set(row["context"]) == {
            "conversation_version",
            "active_topic",
            "visible_candidate_count",
            "focused_candidate_ordinal",
            "image_count",
            "focused_image_ordinal",
            "active_constraint_kinds",
            "confirmed_profile_fields",
        }


def test_no_pipeline_observer_cannot_pass_hard_gates(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: StaticIntentAdapter(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        output_dir=tmp_path,
    )

    hard_gates = report.model_summaries[FLASH_MODEL].hard_gates
    assert report.exit_code == 3
    assert report.selected_model is None
    assert hard_gates.product_selection_status == "UNAVAILABLE"
    assert hard_gates.wrong_product_selection_count is None
    assert hard_gates.legacy_fallback_status == "UNAVAILABLE"
    assert hard_gates.legacy_fallback_count is None


@pytest.mark.parametrize("adapter_reported_count", (0, 1))
def test_adapter_pipeline_counts_are_ignored(
    tmp_path: Path,
    adapter_reported_count: int,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: InjectedGateFailureAdapter(
                cases=cases,
                model=FLASH_MODEL,
                injected={
                    "product_selection_invocation_count": (
                        adapter_reported_count
                    ),
                    "wrong_product_selection_count": (
                        adapter_reported_count
                    ),
                    "legacy_fallback_count": adapter_reported_count,
                },
            )
        },
        output_dir=tmp_path / "unobserved",
    )

    hard_gates = report.model_summaries[FLASH_MODEL].hard_gates
    assert report.exit_code == 3
    assert hard_gates.product_selection_status == "UNAVAILABLE"
    assert hard_gates.product_selection_invocation_count is None
    assert hard_gates.wrong_product_selection_count is None
    assert hard_gates.legacy_fallback_status == "UNAVAILABLE"
    assert hard_gates.legacy_fallback_count is None

    observed = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: InjectedGateFailureAdapter(
                cases=cases,
                model=FLASH_MODEL,
                injected={
                    "product_selection_invocation_count": (
                        adapter_reported_count
                    ),
                    "wrong_product_selection_count": (
                        adapter_reported_count
                    ),
                    "legacy_fallback_count": adapter_reported_count,
                },
            )
        },
        evaluator=TrustedPipelineEvaluator(),
        output_dir=tmp_path / "observed",
    )
    observed_gates = observed.model_summaries[FLASH_MODEL].hard_gates
    assert observed.exit_code == 0
    assert observed_gates.wrong_product_selection_count == 0
    assert observed_gates.legacy_fallback_count == 0


def test_trusted_evaluator_is_called_per_case_and_can_enable_pass(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)
    evaluator = TrustedPipelineEvaluator()

    try:
        report = run_ab(
            cases=cases,
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                )
            },
            evaluator=evaluator,
            output_dir=tmp_path,
        )
    except TypeError as exc:
        pytest.fail(f"runner must accept a trusted evaluator: {exc}")

    assert report.exit_code == 0
    assert report.selected_model == FLASH_MODEL
    assert len(evaluator.requests) == len(cases)
    assert {
        request.expected
        for request in evaluator.requests
    } == {case.expected for case in cases}
    assert all(
        request.proposal is not None
        and request.exact is not None
        and request.merged is not None
        and request.task_plan is not None
        for request in evaluator.requests
    )


@pytest.mark.parametrize(
    ("wrong_product_selection_count", "legacy_fallback_count"),
    ((1, 0), (0, 1)),
)
def test_trusted_evaluator_fault_fails_hard_gate(
    tmp_path: Path,
    wrong_product_selection_count: int,
    legacy_fallback_count: int,
) -> None:
    cases = load_cases(CASES_PATH)
    evaluator = TrustedPipelineEvaluator(
        wrong_product_selection_count=(
            wrong_product_selection_count
        ),
        legacy_fallback_count=legacy_fallback_count,
    )

    try:
        report = run_ab(
            cases=cases,
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                )
            },
            evaluator=evaluator,
            output_dir=tmp_path,
        )
    except TypeError as exc:
        pytest.fail(f"runner must accept a trusted evaluator: {exc}")

    hard_gates = report.model_summaries[FLASH_MODEL].hard_gates
    assert report.exit_code == 3
    assert not hard_gates.passed
    if wrong_product_selection_count:
        assert hard_gates.wrong_product_selection_count == len(cases)
    if legacy_fallback_count:
        assert hard_gates.legacy_fallback_count == len(cases)


def test_untyped_evaluator_output_fails_closed(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: StaticIntentAdapter(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        evaluator=UntypedPipelineEvaluator(),
        output_dir=tmp_path,
    )

    summary = report.model_summaries[FLASH_MODEL]
    assert report.exit_code == 3
    assert summary.hard_gates.untyped_failure_count == len(cases)
    assert not summary.hard_gates.passed


@pytest.mark.parametrize(
    "evaluator",
    (TypedFailingPipelineEvaluator(), NonePipelineEvaluator()),
)
def test_pipeline_failure_keeps_dependent_gates_unavailable(
    tmp_path: Path,
    evaluator,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: StaticIntentAdapter(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        evaluator=evaluator,
        output_dir=tmp_path,
    )

    hard_gates = report.model_summaries[FLASH_MODEL].hard_gates
    assert report.exit_code == 3
    assert hard_gates.pipeline_status == "UNAVAILABLE"
    assert hard_gates.merger_invocation_count is None
    assert hard_gates.task_plan_invocation_count is None
    assert hard_gates.task_plan_mismatch_count is None
    assert hard_gates.hard_constraint_override_count is None
    assert not hard_gates.passed


def test_one_unavailable_row_makes_pipeline_summary_unavailable(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: StaticIntentAdapter(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        evaluator=MixedAvailabilityPipelineEvaluator(cases[0].case_id),
        output_dir=tmp_path,
    )

    hard_gates = report.model_summaries[FLASH_MODEL].hard_gates
    assert report.exit_code == 3
    assert hard_gates.pipeline_status == "UNAVAILABLE"
    assert hard_gates.merger_invocation_count is None
    assert hard_gates.task_plan_invocation_count is None
    assert hard_gates.task_plan_mismatch_count is None
    assert hard_gates.hard_constraint_override_count is None


def test_minimal_evaluator_detects_task_plan_mismatch(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)
    evaluator = TrustedPipelineEvaluator()

    try:
        run_ab(
            cases=cases,
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                )
            },
            evaluator=evaluator,
            output_dir=tmp_path,
        )
    except TypeError as exc:
        pytest.fail(f"runner must accept a trusted evaluator: {exc}")

    from tools.guide_gates.intent_model_ab import (
        MinimalTaskPlanEvaluator,
    )

    request = next(
        item
        for item in evaluator.requests
        if item.task_plan.constraints
    )
    wrong_request = request.model_copy(
        update={
            "task_plan": request.task_plan.model_copy(
                update={"constraints": []}
            )
        }
    )

    observation = MinimalTaskPlanEvaluator().evaluate(wrong_request)

    assert observation.task_plan_mismatch_count == 1


def test_minimal_evaluator_accepts_compiled_semantic_preference(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)
    evaluator = TrustedPipelineEvaluator()

    class PreferenceAdapter(StaticIntentAdapter):
        def propose(self, message, context):
            result = super().propose(message, context)
            if message != "想找一支通勤时挡紫外线又不搓泥的":
                return result
            return result.model_copy(
                update={
                    "proposal": result.proposal.model_copy(
                        update={
                            "preference_candidates": (
                                SemanticPreferenceCandidate(
                                    field=(
                                        SemanticPreferenceField
                                        .USAGE_CONTEXT
                                    ),
                                    raw_text="通勤",
                                    start=4,
                                    end=6,
                                    strength=(
                                        SemanticPreferenceStrength
                                        .PREFERENCE
                                    ),
                                ),
                            ),
                        },
                        deep=True,
                    )
                },
                deep=True,
            )

    run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: PreferenceAdapter(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        evaluator=evaluator,
        output_dir=tmp_path,
    )

    request = next(
        item
        for item in evaluator.requests
        if item.case_id == "rec-006-paraphrase-sunscreen"
    )
    assert any(
        constraint.kind == "facet"
        and constraint.field_key == "usage_context"
        and constraint.value == "通勤"
        for constraint in request.task_plan.constraints
    )
    observation = intent_model_ab.MinimalTaskPlanEvaluator().evaluate(
        request
    )
    assert observation.task_plan_mismatch_count == 0


@pytest.mark.parametrize(
    "adapter_type",
    (InjectedSemanticFieldsAdapter, MissingSemanticFieldsAdapter),
)
def test_fabricated_or_missing_semantic_sets_fail_exact_set_gate(
    tmp_path: Path,
    adapter_type,
) -> None:
    cases = load_cases(CASES_PATH)
    evaluator = TrustedPipelineEvaluator()

    try:
        report = run_ab(
            cases=cases,
            adapters={
                FLASH_MODEL: adapter_type(
                    cases=cases,
                    model=FLASH_MODEL,
                )
            },
            evaluator=evaluator,
            output_dir=tmp_path,
        )
    except TypeError as exc:
        pytest.fail(f"runner must accept a trusted evaluator: {exc}")

    summary = report.model_summaries[FLASH_MODEL]
    assert report.exit_code == 3
    assert summary.concern_correct_count < len(cases)
    assert summary.observation_correct_count < len(cases)
    assert not summary.passed


def test_load_cases_rejects_short_or_duplicate_case_sets(
    tmp_path: Path,
) -> None:
    lines = CASES_PATH.read_text(encoding="utf-8").splitlines()
    short = tmp_path / "short.jsonl"
    short.write_text(
        "\n".join(lines[:119]) + "\n",
        encoding="utf-8",
    )
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        "\n".join([lines[0], *lines[:127]]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(IntentCaseError, match="at least 120"):
        load_cases(short)
    with pytest.raises(IntentCaseError, match="unique"):
        load_cases(duplicate)


def test_run_ab_writes_normalized_private_evidence_without_secrets(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)
    adapters = {
        FLASH_MODEL: StaticIntentAdapter(
            cases=cases,
            model=FLASH_MODEL,
        ),
        BASELINE_MODEL: StaticIntentAdapter(
            cases=cases,
            model=BASELINE_MODEL,
        ),
    }

    report = run_ab(
        cases=cases,
        adapters=adapters,
        evaluator=TrustedPipelineEvaluator(),
        output_dir=tmp_path,
    )

    assert report.case_count == 128
    assert report.exit_code == 0
    assert report.selected_model == FLASH_MODEL
    assert set(report.model_summaries) == {
        FLASH_MODEL,
        BASELINE_MODEL,
    }
    assert all(
        summary.passed
        and summary.schema_valid_count == 128
        and summary.goal_correct_count == 128
        and summary.topic_correct_count == 128
        and summary.concern_correct_count == 128
        and summary.observation_correct_count == 128
        and summary.reference_correct_count == 128
        and summary.critical_failure_count == 0
        and summary.hard_gates.passed
        and summary.hard_gates.hard_constraint_override_count == 0
        and (
            summary.hard_gates
            .unauthorized_constraint_transition_count
            == 0
        )
        and summary.hard_gates.forbidden_field_acceptance_count == 0
        and (
            summary.hard_gates
            .invalid_output_task_plan_invocation_count
            == 0
        )
        and summary.hard_gates.untyped_failure_count == 0
        and summary.hard_gates.task_plan_invocation_count == 128
        and summary.hard_gates.task_plan_mismatch_count == 0
        and summary.hard_gates.product_selection_invocation_count == 0
        and summary.hard_gates.wrong_product_selection_count == 0
        and summary.hard_gates.product_selection_status == "AVAILABLE"
        and summary.hard_gates.legacy_fallback_count == 0
        and summary.hard_gates.legacy_fallback_status == "AVAILABLE"
        for summary in report.model_summaries.values()
    )
    assert set(path.name for path in tmp_path.iterdir()) == {
        "normalized_results.jsonl",
        "runtime_metrics.json",
        "summary.json",
        "SHA256SUMS",
    }

    result_rows = [
        json.loads(line)
        for line in (
            tmp_path / "normalized_results.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert len(result_rows) == 256
    assert all(
        set(row) == {
            "actual",
            "case_id",
            "critical_failure",
            "concern_correct",
            "earliest_failure_layer",
            "goal_correct",
            "model",
            "observation_correct",
            "pipeline",
            "provider_failure_code",
            "reference_correct",
            "schema_diagnostic",
            "schema_valid",
            "status",
            "topic_correct",
        }
        for row in result_rows
    )
    assert all(row["status"] == "ok" for row in result_rows)
    assert all(
        row["provider_failure_code"] is None
        and row["earliest_failure_layer"] == "none"
        for row in result_rows
    )

    summary = json.loads(
        (tmp_path / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["identity"]["runner_schema_version"] == (
        "guide-intent-model-ab-v3"
    )
    assert summary["identity"]["semantic_schema_version"] == (
        SemanticIntentProposal.schema_version
    )
    assert len(summary["identity"]["case_manifest_sha256"]) == 64
    assert summary["stable_evidence_sha256"] == (
        report.normalized_results_sha256
    )
    assert {
        item["model"]
        for item in summary["identity"]["model_identities"]
    } == {FLASH_MODEL, BASELINE_MODEL}
    assert "latency_ms" not in summary["models"][FLASH_MODEL]
    assert "usage" not in summary["models"][FLASH_MODEL]

    runtime_metrics = json.loads(
        (tmp_path / "runtime_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    assert runtime_metrics["models"][FLASH_MODEL]["usage"] == {
        "availability": "AVAILABLE",
        "cached_tokens": 384,
        "completion_tokens": 896,
        "actual_cost_cny": "UNAVAILABLE",
        "cost_status": "UNAVAILABLE",
        "prompt_tokens": 1408,
        "total_tokens": 2304,
    }
    assert (
        runtime_metrics["models"][FLASH_MODEL]["latency_ms"]["p50"]
        >= 0
    )
    assert (
        runtime_metrics["models"][FLASH_MODEL]["latency_ms"]["p95"]
        >= 0
    )
    assert summary["models"][FLASH_MODEL]["hard_gates"] == {
        "critical_failure_count": 0,
        "evaluator_failure_count": 0,
        "forbidden_field_acceptance_count": 0,
        "hard_constraint_override_count": 0,
        "unauthorized_constraint_transition_count": 0,
        "invalid_output_task_plan_invocation_count": 0,
        "legacy_fallback_count": 0,
        "legacy_fallback_status": "AVAILABLE",
        "merger_invocation_count": 128,
        "passed": True,
        "pipeline_status": "AVAILABLE",
        "product_selection_invocation_count": 0,
        "product_selection_status": "AVAILABLE",
        "task_plan_invocation_count": 128,
        "task_plan_mismatch_count": 0,
        "untyped_failure_count": 0,
        "wrong_product_selection_count": 0,
    }

    output_blob = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.iterdir()
    )
    for sensitive in (
        FAKE_KEY,
        FAKE_AUTHORIZATION,
        FAKE_PROFILE,
        FAKE_PRODUCT_FACT,
        cases[0].message,
    ):
        assert sensitive not in output_blob
    assert "adapter_reported_cost_cny" not in output_blob
    _assert_sha256sums(tmp_path)


def test_run_ab_uses_one_helper_thread_and_serial_order_per_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent_model_ab, "_MINIMUM_CASE_COUNT", 2)
    cases = load_cases(CASES_PATH)[:2]
    probe = ModelConcurrencyProbe()
    caller_thread_id = current_thread().ident

    report = run_ab(
        cases=tuple(reversed(cases)),
        adapters={
            FLASH_MODEL: ConcurrentRecordingAdapter(
                cases=cases,
                model=FLASH_MODEL,
                probe=probe,
            ),
            BASELINE_MODEL: ConcurrentRecordingAdapter(
                cases=cases,
                model=BASELINE_MODEL,
                probe=probe,
            ),
        },
        evaluator=TrustedPipelineEvaluator(),
        output_dir=tmp_path,
    )

    expected_case_ids = sorted(case.case_id for case in cases)
    assert report.exit_code == 0
    assert probe.both_models_started.is_set()
    assert probe.max_total_inflight == 2
    assert probe.max_model_inflight == {
        BASELINE_MODEL: 1,
        FLASH_MODEL: 1,
    }
    assert probe.case_ids == {
        BASELINE_MODEL: expected_case_ids,
        FLASH_MODEL: expected_case_ids,
    }
    all_thread_ids = set().union(*probe.thread_ids.values())
    assert len(all_thread_ids) == 2
    assert caller_thread_id in all_thread_ids
    assert all(len(values) == 1 for values in probe.thread_ids.values())


def test_run_ab_waits_for_both_models_and_raises_sorted_infrastructure_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent_model_ab, "_MINIMUM_CASE_COUNT", 2)
    cases = load_cases(CASES_PATH)[:2]
    both_started = Event()
    helper_finished = Event()
    started: set[str] = set()
    lock = Lock()

    def fail_model(*, case, model, adapter, evaluator):
        del case, adapter, evaluator
        with lock:
            started.add(model)
            if len(started) == 2:
                both_started.set()
        assert both_started.wait(timeout=0.5)
        if model == FLASH_MODEL:
            time.sleep(0.05)
            helper_finished.set()
        raise RuntimeError(f"infrastructure failure: {model}")

    monkeypatch.setattr(intent_model_ab, "_run_case", fail_model)

    with pytest.raises(
        RuntimeError,
        match=f"infrastructure failure: {BASELINE_MODEL}",
    ):
        run_ab(
            cases=cases,
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                ),
                BASELINE_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=BASELINE_MODEL,
                ),
            },
            evaluator=TrustedPipelineEvaluator(),
            output_dir=tmp_path,
        )

    assert started == {BASELINE_MODEL, FLASH_MODEL}
    assert helper_finished.is_set()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "failure_type",
    (KeyboardInterrupt, SystemExit),
)
def test_run_ab_reraises_helper_base_exception_without_partial_evidence(
    failure_type: type[BaseException],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent_model_ab, "_MINIMUM_CASE_COUNT", 2)
    cases = load_cases(CASES_PATH)[:2]
    failure = failure_type("helper infrastructure failure")
    original_run_case = intent_model_ab._run_case

    def fail_helper(*, case, model, adapter, evaluator):
        if model == FLASH_MODEL:
            raise failure
        return original_run_case(
            case=case,
            model=model,
            adapter=adapter,
            evaluator=evaluator,
        )

    monkeypatch.setattr(intent_model_ab, "_run_case", fail_helper)

    with pytest.raises(failure_type) as caught:
        run_ab(
            cases=cases,
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                ),
                BASELINE_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=BASELINE_MODEL,
                ),
            },
            evaluator=TrustedPipelineEvaluator(),
            output_dir=tmp_path,
        )

    assert caught.value is failure
    assert list(tmp_path.iterdir()) == []


def test_run_models_preserves_caller_keyboard_interrupt_over_sorted_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = load_cases(CASES_PATH)
    adapters = {
        FLASH_MODEL: StaticIntentAdapter(
            cases=cases,
            model=FLASH_MODEL,
        ),
        BASELINE_MODEL: StaticIntentAdapter(
            cases=cases,
            model=BASELINE_MODEL,
        ),
    }
    identities = tuple(
        reversed(intent_model_ab._validate_adapters(adapters))
    )
    both_started = Event()
    started: set[str] = set()
    lock = Lock()
    cancellation = KeyboardInterrupt("cancel verifier")

    def interrupt_caller(*, identity, cases, adapter, evaluator):
        del cases, adapter, evaluator
        with lock:
            started.add(identity.label)
            if len(started) == 2:
                both_started.set()
        assert both_started.wait(timeout=0.5)
        if identity.label == FLASH_MODEL:
            raise cancellation
        raise RuntimeError(f"infrastructure failure: {identity.label}")

    monkeypatch.setattr(
        intent_model_ab,
        "_run_model",
        interrupt_caller,
    )

    with pytest.raises(KeyboardInterrupt) as caught:
        intent_model_ab._run_models(
            identities=identities,
            cases=cases,
            adapters=adapters,
            evaluator=TrustedPipelineEvaluator(),
        )

    assert caught.value is cancellation
    assert started == {BASELINE_MODEL, FLASH_MODEL}


def test_run_ab_caller_keyboard_interrupt_has_bounded_helper_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent_model_ab, "_MINIMUM_CASE_COUNT", 2)
    cases = load_cases(CASES_PATH)[:2]
    adapters = {
        FLASH_MODEL: StaticIntentAdapter(
            cases=cases,
            model=FLASH_MODEL,
        ),
        BASELINE_MODEL: StaticIntentAdapter(
            cases=cases,
            model=BASELINE_MODEL,
        ),
    }
    helper_started = Event()
    helper_release = Event()
    helper_finished = Event()
    cancellation = KeyboardInterrupt("cancel verifier")

    def block_helper(*, case, model, adapter, evaluator):
        del case, adapter, evaluator
        if model == FLASH_MODEL:
            helper_started.set()
            try:
                helper_release.wait(timeout=2.0)
            finally:
                helper_finished.set()
            raise RuntimeError("helper stopped")
        assert helper_started.wait(timeout=0.5)
        raise cancellation

    monkeypatch.setattr(intent_model_ab, "_run_case", block_helper)

    started_at = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            run_ab(
                cases=cases,
                adapters=adapters,
                evaluator=TrustedPipelineEvaluator(),
                output_dir=tmp_path,
            )
        elapsed = time.monotonic() - started_at
        helper_threads = [
            thread
            for thread in enumerate_threads()
            if thread.name == "guide-intent-ab-model-helper"
        ]

        assert caught.value is cancellation
        assert elapsed < 0.5
        assert helper_threads
        assert all(thread.daemon for thread in helper_threads)
        assert list(tmp_path.iterdir()) == []
    finally:
        helper_release.set()
        assert helper_finished.wait(timeout=0.5)
        deadline = time.monotonic() + 0.5
        while (
            any(
                thread.name == "guide-intent-ab-model-helper"
                for thread in enumerate_threads()
            )
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert not any(
            thread.name == "guide-intent-ab-model-helper"
            for thread in enumerate_threads()
        )


def test_run_ab_serializes_shared_evaluator_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent_model_ab, "_MINIMUM_CASE_COUNT", 2)
    cases = load_cases(CASES_PATH)[:2]
    adapter_probe = ModelConcurrencyProbe()
    evaluator = LockCheckingEvaluator()

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: ConcurrentRecordingAdapter(
                cases=cases,
                model=FLASH_MODEL,
                probe=adapter_probe,
            ),
            BASELINE_MODEL: ConcurrentRecordingAdapter(
                cases=cases,
                model=BASELINE_MODEL,
                probe=adapter_probe,
            ),
        },
        evaluator=evaluator,
        output_dir=tmp_path,
    )

    assert report.exit_code == 0
    assert adapter_probe.max_total_inflight == 2
    assert evaluator.max_inflight == 1
    assert len(evaluator.requests) == len(cases) * 2


def test_runner_persists_only_closed_schema_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent_model_ab, "_MINIMUM_CASE_COUNT", 2)
    cases = load_cases(CASES_PATH)[:2]

    run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: DiagnosticFailureAdapter(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        output_dir=tmp_path,
    )

    rows = [
        json.loads(line)
        for line in (
            tmp_path / "normalized_results.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert all(
        row["status"] == "schema_invalid"
        and row["provider_failure_code"] is None
        and row["schema_diagnostic"]
        == {
            "stage": "repair",
            "kind": "enum",
            "path": "goal",
            "count": 2,
            "truncated": False,
            "repair_outcome": "failed",
        }
        for row in rows
    )
    evidence = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.iterdir()
    )
    assert all(case.message not in evidence for case in cases)
    assert FAKE_KEY not in evidence
    assert FAKE_AUTHORIZATION not in evidence
    assert all(
        forbidden not in evidence
        for forbidden in ('"input"', '"msg"', '"ctx"', '"key"')
    )


def test_normalized_rows_close_redacted_failure_and_earliest_layer(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)
    assert hasattr(SemanticProviderFailureCode, "INVALID_OUTPUT")
    invalid_output = SemanticProviderFailureCode("invalid_output")
    failure_codes = (
        SemanticProviderFailureCode.AUTHENTICATION_FAILED,
        SemanticProviderFailureCode.RATE_LIMITED,
        SemanticProviderFailureCode.PROVIDER_UNAVAILABLE,
        SemanticProviderFailureCode.PROVIDER_REJECTED,
        SemanticProviderFailureCode.TIMEOUT,
        SemanticProviderFailureCode.EMPTY_RESPONSE,
        SemanticProviderFailureCode.INVALID_RESPONSE,
        invalid_output,
        SemanticProviderFailureCode.FORBIDDEN_OUTPUT,
        SemanticProviderFailureCode.DAILY_BUDGET_EXCEEDED,
        SemanticProviderFailureCode.DAILY_CALL_CAP_EXCEEDED,
    )
    expected = {
        SemanticProviderFailureCode.AUTHENTICATION_FAILED: (
            "provider_failure",
            "authentication",
            "provider_transport",
        ),
        SemanticProviderFailureCode.RATE_LIMITED: (
            "provider_failure",
            "rate_limit",
            "provider_transport",
        ),
        SemanticProviderFailureCode.PROVIDER_UNAVAILABLE: (
            "provider_failure",
            "unavailable",
            "provider_transport",
        ),
        SemanticProviderFailureCode.PROVIDER_REJECTED: (
            "provider_failure",
            "rejected",
            "provider_transport",
        ),
        SemanticProviderFailureCode.TIMEOUT: (
            "provider_failure",
            "timeout",
            "provider_transport",
        ),
        SemanticProviderFailureCode.EMPTY_RESPONSE: (
            "provider_failure",
            "empty",
            "provider_transport",
        ),
        SemanticProviderFailureCode.INVALID_RESPONSE: (
            "provider_failure",
            "invalid",
            "provider_transport",
        ),
        invalid_output: (
            "schema_invalid",
            None,
            "semantic_schema",
        ),
        SemanticProviderFailureCode.FORBIDDEN_OUTPUT: (
            "schema_invalid",
            None,
            "semantic_schema",
        ),
        SemanticProviderFailureCode.DAILY_BUDGET_EXCEEDED: (
            "provider_failure",
            "budget",
            "provider_transport",
        ),
        SemanticProviderFailureCode.DAILY_CALL_CAP_EXCEEDED: (
            "provider_failure",
            "call_cap",
            "provider_transport",
        ),
    }

    run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: FailureMatrixIntentAdapter(
                cases=cases,
                model=FLASH_MODEL,
                failure_codes=failure_codes,
            )
        },
        output_dir=tmp_path,
    )

    rows = [
        json.loads(line)
        for line in (
            tmp_path / "normalized_results.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    by_case_id = {case.case_id: case for case in cases}
    by_message = {
        case.message: failure_codes[index % len(failure_codes)]
        for index, case in enumerate(cases)
    }
    for row in rows:
        raw_code = by_message[by_case_id[row["case_id"]].message]
        status, redacted_code, earliest_layer = expected[raw_code]
        assert row["status"] == status
        assert row["provider_failure_code"] == redacted_code
        assert row["earliest_failure_layer"] == earliest_layer

    evidence = (tmp_path / "normalized_results.jsonl").read_text(
        encoding="utf-8"
    )
    assert "599" not in evidence
    assert FAKE_KEY not in evidence
    assert FAKE_AUTHORIZATION not in evidence
    assert all(case.message not in evidence for case in cases)


def test_unobservable_selection_and_legacy_gates_are_unavailable(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: UninstrumentedIntentAdapter(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        output_dir=tmp_path,
    )

    hard_gates = report.model_summaries[FLASH_MODEL].hard_gates
    assert report.exit_code == 3
    assert not hard_gates.passed
    assert hard_gates.product_selection_status == "UNAVAILABLE"
    assert hard_gates.product_selection_invocation_count is None
    assert hard_gates.wrong_product_selection_count is None
    assert hard_gates.legacy_fallback_status == "UNAVAILABLE"
    assert hard_gates.legacy_fallback_count is None


def test_typed_provider_failures_keep_all_downstream_gates_observable(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: FailingIntentAdapter(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        evaluator=TrustedPipelineEvaluator(),
        output_dir=tmp_path,
    )

    hard_gates = report.model_summaries[FLASH_MODEL].hard_gates
    assert report.exit_code == 3
    assert hard_gates.pipeline_status == "AVAILABLE"
    assert hard_gates.merger_invocation_count == 0
    assert hard_gates.task_plan_invocation_count == 0
    assert hard_gates.hard_constraint_override_count == 0
    assert hard_gates.invalid_output_task_plan_invocation_count == 0
    assert hard_gates.product_selection_status == "AVAILABLE"
    assert hard_gates.wrong_product_selection_count == 0
    assert hard_gates.legacy_fallback_status == "AVAILABLE"
    assert hard_gates.legacy_fallback_count == 0


def test_semantic_evidence_hash_is_stable_across_latency_and_case_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = load_cases(CASES_PATH)
    clock_value = 0

    def fast_clock() -> int:
        nonlocal clock_value
        clock_value += 1
        return clock_value

    monkeypatch.setattr(
        "tools.guide_gates.intent_model_ab.time.perf_counter_ns",
        fast_clock,
    )
    first = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: StaticIntentAdapter(
                cases=cases,
                model=FLASH_MODEL,
            ),
            BASELINE_MODEL: StaticIntentAdapter(
                cases=cases,
                model=BASELINE_MODEL,
            ),
        },
        evaluator=TrustedPipelineEvaluator(),
        output_dir=tmp_path / "first",
    )

    clock_value = 0

    def slow_clock() -> int:
        nonlocal clock_value
        clock_value += 10_000_000
        return clock_value

    monkeypatch.setattr(
        "tools.guide_gates.intent_model_ab.time.perf_counter_ns",
        slow_clock,
    )
    second = run_ab(
        cases=tuple(reversed(cases)),
        adapters={
            BASELINE_MODEL: StaticIntentAdapter(
                cases=cases,
                model=BASELINE_MODEL,
            ),
            FLASH_MODEL: StaticIntentAdapter(
                cases=cases,
                model=FLASH_MODEL,
            ),
        },
        evaluator=TrustedPipelineEvaluator(),
        output_dir=tmp_path / "second",
    )

    assert first.case_manifest_sha256 == second.case_manifest_sha256
    assert (
        first.normalized_results_sha256
        == second.normalized_results_sha256
    )
    assert first.summary_sha256 == second.summary_sha256
    assert (
        tmp_path / "first" / "normalized_results.jsonl"
    ).read_bytes() == (
        tmp_path / "second" / "normalized_results.jsonl"
    ).read_bytes()
    assert (tmp_path / "first" / "summary.json").read_bytes() == (
        tmp_path / "second" / "summary.json"
    ).read_bytes()
    assert (tmp_path / "first" / "runtime_metrics.json").read_bytes() != (
        tmp_path / "second" / "runtime_metrics.json"
    ).read_bytes()
    _assert_sha256sums(tmp_path / "first")
    _assert_sha256sums(tmp_path / "second")


def test_unknown_usage_remains_null_and_adapter_cost_is_not_billing(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: UnknownUsageAdapter(
                cases=cases,
                model=FLASH_MODEL,
            ),
            BASELINE_MODEL: StaticIntentAdapter(
                cases=cases,
                model=BASELINE_MODEL,
            ),
        },
        output_dir=tmp_path,
    )

    metrics = json.loads(
        (tmp_path / "runtime_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    unknown = metrics["models"][FLASH_MODEL]["usage"]
    assert unknown == {
        "availability": "UNAVAILABLE",
        "cached_tokens": None,
        "completion_tokens": None,
        "actual_cost_cny": "UNAVAILABLE",
        "cost_status": "UNAVAILABLE",
        "prompt_tokens": None,
        "total_tokens": None,
    }
    assert (
        metrics["models"][BASELINE_MODEL]["usage"][
            "actual_cost_cny"
        ]
        == "UNAVAILABLE"
    )


def test_caller_cannot_self_verify_billing_cost(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    with pytest.raises(TypeError, match="billing_evidence"):
        run_ab(
            cases=cases,
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                )
            },
            billing_evidence={
                FLASH_MODEL: {
                    "source": "caller-asserted-export",
                    "verified": True,
                    "actual_cost_cny": Decimal("0.128"),
                }
            },
            output_dir=tmp_path,
        )


def test_run_ab_selects_baseline_when_flash_fails_schema_gate(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: InvalidOutputAdapter(
                cases=cases,
                model=FLASH_MODEL,
            ),
            BASELINE_MODEL: StaticIntentAdapter(
                cases=cases,
                model=BASELINE_MODEL,
            ),
        },
        evaluator=TrustedPipelineEvaluator(),
        output_dir=tmp_path,
    )

    assert report.exit_code == 0
    assert report.selected_model == BASELINE_MODEL
    assert not report.model_summaries[FLASH_MODEL].passed
    assert (
        report.model_summaries[FLASH_MODEL].schema_valid_count
        == 0
    )
    assert report.model_summaries[BASELINE_MODEL].passed


def test_forbidden_proposal_is_blocked_before_merger_and_task_plan(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: InvalidOutputAdapter(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        evaluator=TrustedPipelineEvaluator(),
        output_dir=tmp_path,
    )

    rows = [
        json.loads(line)
        for line in (
            tmp_path / "normalized_results.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert report.exit_code == 3
    assert all(
        row["status"] == "schema_invalid"
        and row["provider_failure_code"] is None
        and row["earliest_failure_layer"] == "semantic_schema"
        and not row["pipeline"]["strict_validation_passed"]
        and row["pipeline"]["merger_invocation_count"] == 0
        and row["pipeline"]["task_plan_invocation_count"] == 0
        and (
            row["pipeline"][
                "invalid_output_task_plan_invocation_count"
            ]
            == 0
        )
        and row["pipeline"]["forbidden_field_acceptance_count"] == 0
        for row in rows
    )


@pytest.mark.parametrize(
    "adapter_type",
    (
        InvalidActsAdapter,
        InvalidOutputAdapter,
        MalformedJsonAdapter,
        FailingIntentAdapter,
    ),
)
def test_run_ab_returns_exit_three_when_no_model_passes(
    tmp_path: Path,
    adapter_type,
) -> None:
    cases = load_cases(CASES_PATH)

    report = run_ab(
        cases=cases,
        adapters={
            FLASH_MODEL: adapter_type(
                cases=cases,
                model=FLASH_MODEL,
            )
        },
        output_dir=tmp_path,
    )

    assert report.exit_code == 3
    assert report.selected_model is None
    assert not report.model_summaries[FLASH_MODEL].passed
    result_blob = (
        tmp_path / "normalized_results.jsonl"
    ).read_text(encoding="utf-8")
    assert FAKE_PRODUCT_FACT not in result_blob
    assert "provider unavailable" not in result_blob.casefold()
    _assert_sha256sums(tmp_path)


def test_run_ab_rejects_mislabeled_adapter_identity(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    with pytest.raises(
        IntentAbConfigurationError,
        match="identity",
    ):
        run_ab(
            cases=cases,
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=BASELINE_MODEL,
                )
            },
            output_dir=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_run_ab_rejects_unapproved_model_identity(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)

    with pytest.raises(
        IntentAbConfigurationError,
        match="approved",
    ):
        run_ab(
            cases=cases,
            adapters={
                "unverified/model": StaticIntentAdapter(
                    cases=cases,
                    model="unverified/model",
                )
            },
            output_dir=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_run_ab_rejects_nonempty_evidence_directory(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)
    stale = tmp_path / "stale-secret.txt"
    stale.write_text(FAKE_KEY, encoding="utf-8")

    with pytest.raises(
        IntentAbConfigurationError,
        match="empty",
    ):
        run_ab(
            cases=cases,
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                )
            },
            output_dir=tmp_path,
        )

    assert list(tmp_path.iterdir()) == [stale]
    assert stale.read_text(encoding="utf-8") == FAKE_KEY


def test_runner_imports_no_network_client_or_legacy_services() -> None:
    runner_path = Path("tools/guide_gates/intent_model_ab.py")
    tree = ast.parse(
        runner_path.read_text(encoding="utf-8"),
        filename=str(runner_path),
    )
    imported_roots = {
        alias.name.split(".", maxsplit=1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
    }

    assert imported_roots.isdisjoint(
        {"httpx", "requests", "socket", "urllib"}
    )
    assert not any(
        module == "app.services"
        or module.startswith("app.services.")
        for module in imported_modules
    )
    assert not any(
        module == blocked
        or module.startswith(f"{blocked}.")
        for module in imported_modules
        for blocked in (
            "app.guide.retrieval",
            "app.guide.decision",
            "app.guide.presentation",
        )
    )

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys;"
                "import tools.guide_gates.intent_model_ab;"
                "blocked=('app.services','httpx','requests');"
                "print(json.dumps(sorted(name for name in sys.modules "
                "if any(name == root or name.startswith(root + '.') "
                "for root in blocked))))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(probe.stdout) == []


def test_main_uses_only_injected_adapters_and_returns_zero_two_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    cases = load_cases(CASES_PATH)

    assert main(_cli_args(tmp_path / "missing"), adapters=None) == 2
    assert not (tmp_path / "missing").exists()
    assert (
        main(
            _cli_args(tmp_path / "unobserved"),
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                )
            },
        )
        == 3
    )
    assert (
        main(
            _cli_args(tmp_path / "pass"),
            adapters={
                FLASH_MODEL: StaticIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                )
            },
            evaluator=TrustedPipelineEvaluator(),
        )
        == 0
    )
    assert (
        main(
            _cli_args(tmp_path / "fail"),
            adapters={
                FLASH_MODEL: FailingIntentAdapter(
                    cases=cases,
                    model=FLASH_MODEL,
                )
            },
        )
        == 3
    )
