from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
from types import ModuleType

import pytest

from app.guide.application.contracts import UserTurn
from app.guide.adapters.llm.contracts import (
    SemanticProviderFailureCode,
)
from app.guide.intent.contracts import ExclusionConstraint
from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.intent.task_planning import plan_task
from app.guide.intent.transition_planning import (
    plan_code_owned_transitions,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.sse_events import (
    CardDisplayContractEvent,
    ClarifyData,
    ClarifyEvent,
    EndData,
    EndEvent,
    IntentData,
    IntentEvent,
    StartData,
    StartEvent,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_revision_confirmations,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    SemanticLaneDisposition,
    SemanticIntentProposal,
)
from app.guide_runtime.composition import build_runtime_orchestrator
from tools.guide_gates import guide_pipeline_evaluator
from tools.guide_gates.guide_pipeline_evaluator import (
    ModelVerticalEvaluator,
)
from tools.guide_gates.intent_model_ab import (
    IntentCase,
    MinimalTaskPlanEvaluator,
    PipelineEvaluationFailure,
    PipelineEvaluationFailureCode,
    PipelineEvaluationRequest,
    PipelineExactInput,
    load_cases,
    run_ab,
)


CASES_PATH = Path(
    "tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl"
)
FLASH_MODEL = "deepseek-ai/DeepSeek-V4-Flash"


def _proposal_for(case: IntentCase) -> SemanticIntentProposal:
    return SemanticIntentProposal.model_validate_json(
        json.dumps(
            {
                "goal": case.expected.goal.value,
                "topic": (
                    case.expected.topic.value
                    if case.expected.topic is not None
                    else None
                ),
                "concerns": [
                    value.value for value in case.expected.concerns
                ],
                "observations": [
                    value.model_dump(mode="json")
                    for value in case.expected.observations
                ],
                "references": [
                    value.model_dump(mode="json")
                    for value in case.expected.references
                ],
                "confidence": 0.99,
                "clarification_hint": (
                    ClarificationCode.GOAL.value
                    if case.expected.must_clarify
                    else None
                ),
            },
            ensure_ascii=False,
        ),
        strict=True,
    )


def _request(case: IntentCase) -> PipelineEvaluationRequest:
    proposal = _proposal_for(case)
    constraints, issues = parse_exact_constraints(case.message)
    exact = PipelineExactInput(
        constraints=tuple(constraints),
        issues=tuple(issues),
        revision_confirmations=tuple(
            parse_exact_revision_confirmations(case.message)
        ),
    )
    merged = merge_intent_signals(
        message=case.message,
        exact_constraints=exact.constraints,
        exact_issues=exact.issues,
        exact_revision_confirmations=exact.revision_confirmations,
        semantic=proposal,
        context=case.context,
    )
    transition_plan = plan_code_owned_transitions(
        message=case.message,
        understanding=merged,
        task=plan_task(merged),
        previous=case.before_state,
    )
    return PipelineEvaluationRequest(
        case_id=case.case_id,
        model=FLASH_MODEL,
        message=case.message,
        context=case.context,
        proposal=proposal,
        exact=exact,
        merged=merged,
        task_plan=transition_plan.task_plan,
        transitions=(
            transition_plan.transition_result.transitions
            if transition_plan.transition_result is not None
            else ()
        ),
        before_state=case.before_state,
        expected=case.expected,
    )


def _failure_request(case: IntentCase) -> PipelineEvaluationRequest:
    constraints, issues = parse_exact_constraints(case.message)
    exact = PipelineExactInput(
        constraints=tuple(constraints),
        issues=tuple(issues),
        revision_confirmations=tuple(
            parse_exact_revision_confirmations(case.message)
        ),
    )
    merged = merge_intent_signals(
        message=case.message,
        exact_constraints=exact.constraints,
        exact_issues=exact.issues,
        exact_revision_confirmations=exact.revision_confirmations,
        semantic=None,
        semantic_disposition=SemanticLaneDisposition.UNAVAILABLE,
        context=case.context,
    )
    transition_plan = plan_code_owned_transitions(
        message=case.message,
        understanding=merged,
        task=plan_task(merged),
        previous=case.before_state,
    )
    return PipelineEvaluationRequest(
        case_id=case.case_id,
        model=FLASH_MODEL,
        message=case.message,
        context=case.context,
        proposal=None,
        semantic_failure_code=(
            SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
        ),
        exact=exact,
        merged=merged,
        task_plan=transition_plan.task_plan,
        transitions=(
            transition_plan.transition_result.transitions
            if transition_plan.transition_result is not None
            else ()
        ),
        before_state=case.before_state,
        expected=case.expected,
    )


def _case(case_id: str) -> IntentCase:
    return next(
        case for case in load_cases(CASES_PATH)
        if case.case_id == case_id
    )


class ExpectedProposalAdapter:
    provider = "offline-fake"
    model = FLASH_MODEL
    prompt_version = "offline-fake-prompt-v1"

    def __init__(self, cases: tuple[IntentCase, ...]) -> None:
        self._cases = {case.message: case for case in cases}

    def propose(self, message, context):
        case = self._cases[message]
        assert context == case.context
        return _proposal_for(case)


def test_model_vertical_consumes_all_128_proposals_once(
    tmp_path: Path,
) -> None:
    cases = load_cases(CASES_PATH)
    semantic_ports: list[object] = []

    def recording_factory(*, state_dir, semantic_intent):
        semantic_ports.append(semantic_intent)
        return build_runtime_orchestrator(
            state_dir=state_dir,
            semantic_intent=semantic_intent,
        )

    report = run_ab(
        cases=cases,
        adapters={FLASH_MODEL: ExpectedProposalAdapter(cases)},
        evaluator=ModelVerticalEvaluator(
            orchestrator_factory=recording_factory,
        ),
        output_dir=tmp_path / "model-vertical",
    )

    hard_gates = report.model_summaries[FLASH_MODEL].hard_gates
    assert report.exit_code == 0
    assert len(semantic_ports) == 128
    assert all(port.invocation_count == 1 for port in semantic_ports)
    assert hard_gates.pipeline_status == "AVAILABLE"
    assert hard_gates.wrong_product_selection_count == 0
    assert hard_gates.legacy_fallback_count == 0


class _ConsumingOrchestrator:
    def __init__(self, semantic, context, events) -> None:
        self._semantic = semantic
        self._context = context
        self._events = events

    def stream(self, turn: UserTurn):
        raise AssertionError("model vertical must not call production stream")

    def stream_text_vertical(
        self,
        turn: UserTurn,
        *,
        semantic_context=None,
    ):
        assert semantic_context == self._context
        self._semantic.propose(turn.message, self._context)
        yield from self._events(turn)


def _clarify_events(turn: UserTurn):
    yield StartEvent(data=StartData(session_id=turn.session_id))
    yield IntentEvent(data=IntentData(mode="clarify"))
    yield ClarifyEvent(
        data=ClarifyData(
            question="请确认要找的商品。",
            clarification_code=ClarificationCode.TOPIC,
        )
    )
    yield EndEvent(
        data=EndData(conversation_version=turn.conversation_version)
    )


def test_model_vertical_is_explicitly_isolated_from_production_stream() -> None:
    request = _request(_case("clar-002-low-info-recommend"))
    observed = ModelVerticalEvaluator(
        orchestrator_factory=lambda **kwargs: _ConsumingOrchestrator(
            kwargs["semantic_intent"],
            request.context,
            _clarify_events,
        )
    ).evaluate(request)

    assert not isinstance(observed, PipelineEvaluationFailure)


def test_model_vertical_observes_typed_semantic_failure_path() -> None:
    request = _failure_request(_case("clar-002-low-info-recommend"))

    observed = ModelVerticalEvaluator().evaluate(request)

    assert not isinstance(observed, PipelineEvaluationFailure)
    assert observed.hard_constraint_override_count == 0
    assert observed.product_selection_invocation_count == 0
    assert observed.wrong_product_selection_count == 0
    assert observed.legacy_fallback_count == 0


def test_final_state_gate_rejects_unmentioned_constraint_removal() -> None:
    request = _request(_case("follow-009-budget-revision"))
    corrupted = request.model_copy(
        update={
            "task_plan": request.task_plan.model_copy(
                update={
                    "constraints": [
                        item
                        for item in request.task_plan.constraints
                        if not isinstance(item, ExclusionConstraint)
                    ]
                },
                deep=True,
            )
        },
        deep=True,
    )

    observed = MinimalTaskPlanEvaluator().evaluate(corrupted)

    assert observed.unauthorized_constraint_transition_count == 1


def test_clarify_card_display_counts_as_wrong_selection() -> None:
    request = _request(_case("clar-002-low-info-recommend"))

    def events(turn: UserTurn):
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question="请确认要找的商品。",
                clarification_code=ClarificationCode.TOPIC,
            )
        )
        yield CardDisplayContractEvent(
            data=CardDisplayContract(
                mode="none",
                visible_product_ids=(),
                max_cards=0,
                reason=None,
            )
        )
        yield EndEvent(
            data=EndData(conversation_version=turn.conversation_version)
        )

    observed = ModelVerticalEvaluator(
        orchestrator_factory=lambda **kwargs: _ConsumingOrchestrator(
            kwargs["semantic_intent"],
            request.context,
            events,
        )
    ).evaluate(request)

    assert not isinstance(observed, PipelineEvaluationFailure)
    assert observed.product_selection_invocation_count == 1
    assert observed.wrong_product_selection_count == 1
    assert observed.task_plan_mismatch_count == 1


def test_real_model_vertical_handles_no_candidate_without_false_winner() -> None:
    case = _case("rec-014-budget-sunscreen").model_copy(
        update={
            "case_id": "rec-no-candidate",
            "message": "预算1元以内，推荐防晒",
        }
    )

    observed = ModelVerticalEvaluator().evaluate(_request(case))

    assert not isinstance(observed, PipelineEvaluationFailure)
    assert observed.product_selection_invocation_count == 1
    assert observed.wrong_product_selection_count == 0


def test_bad_event_stream_fails_closed() -> None:
    request = _request(_case("clar-002-low-info-recommend"))

    def bad_events(turn: UserTurn):
        del turn
        yield {"event": "unknown", "data": {}}

    observed = ModelVerticalEvaluator(
        orchestrator_factory=lambda **kwargs: _ConsumingOrchestrator(
            kwargs["semantic_intent"],
            request.context,
            bad_events,
        )
    ).evaluate(request)

    assert observed == PipelineEvaluationFailure(
        code=PipelineEvaluationFailureCode.INVALID_EVENT_STREAM
    )


class _ThreadCallingOrchestrator(_ConsumingOrchestrator):
    def __init__(self, semantic, context, legacy_call) -> None:
        super().__init__(semantic, context, _clarify_events)
        self._legacy_call = legacy_call

    def stream_text_vertical(
        self,
        turn: UserTurn,
        *,
        semantic_context=None,
    ):
        assert semantic_context == self._context
        self._semantic.propose(turn.message, self._context)
        worker = threading.Thread(target=self._legacy_call)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        yield from _clarify_events(turn)


@pytest.mark.parametrize(
    "module_name",
    (
        "app.services.thread_probe",
        ".".join(("app", "api", "v1", "chat")),
    ),
)
def test_legacy_observer_counts_preloaded_call_in_new_thread(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    module = ModuleType(module_name)
    exec(
        compile(
            "def actual_call():\n    return 'called'\n",
            f"<{module_name}>",
            "exec",
        ),
        module.__dict__,
    )
    monkeypatch.setitem(sys.modules, module_name, module)
    request = _request(_case("clar-002-low-info-recommend"))

    observed = ModelVerticalEvaluator(
        orchestrator_factory=lambda **kwargs: _ThreadCallingOrchestrator(
            kwargs["semantic_intent"],
            request.context,
            module.actual_call,
        )
    ).evaluate(request)

    assert not isinstance(observed, PipelineEvaluationFailure)
    assert observed.legacy_fallback_count == 1


def test_concurrent_observers_restore_sys_and_thread_profiles() -> None:
    request = _request(_case("clar-002-low-info-recommend"))
    previous_sys = sys.getprofile()
    previous_thread = threading.getprofile()

    def evaluate_once():
        return ModelVerticalEvaluator(
            orchestrator_factory=lambda **kwargs: _ConsumingOrchestrator(
                kwargs["semantic_intent"],
                request.context,
                _clarify_events,
            )
        ).evaluate(request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        observed = tuple(pool.map(lambda _: evaluate_once(), range(2)))

    assert all(
        not isinstance(item, PipelineEvaluationFailure)
        for item in observed
    )
    assert sys.getprofile() is previous_sys
    assert threading.getprofile() is previous_thread


def test_observer_restores_hooks_on_partial_install_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_meta_path = tuple(sys.meta_path)
    previous_sys = sys.getprofile()
    previous_thread = threading.getprofile()
    real_setprofile = threading.setprofile

    def fail_after_install(profile) -> None:
        real_setprofile(profile)
        if profile is not previous_thread:
            raise RuntimeError("thread profile installation unavailable")

    monkeypatch.setattr(threading, "setprofile", fail_after_install)

    with pytest.raises(
        RuntimeError,
        match="thread profile installation unavailable",
    ):
        with guide_pipeline_evaluator._observe_legacy_execution():
            pytest.fail("observer context must not be entered")

    assert tuple(sys.meta_path) == previous_meta_path
    assert sys.getprofile() is previous_sys
    assert threading.getprofile() is previous_thread
