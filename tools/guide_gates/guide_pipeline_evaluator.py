"""Model-isolation evaluator for the real Guide text vertical.

This module deliberately does not represent public production routing. The
evaluator bypasses closed-operation dispatch so each validated semantic
proposal is consumed exactly once by the real exact/merger/TaskPlan/retrieval/
decision/presentation vertical. Production routing is verified separately by
``production_routing_gate.py`` through ``TextRecommendationOrchestrator.stream``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import threading
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.guide.application.contracts import UserTurn
from app.guide.adapters.state.sqlite_conversation_state import (
    SqliteConversationState,
)
from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
)
from app.guide.intent.contracts import CategoryConstraint
from app.guide.presentation.sse_events import (
    CardDisplayContractEvent,
    ClarifyEvent,
    DecisionProcessEvent,
    EndEvent,
    ErrorEvent,
    IntentEvent,
    ProductsEvent,
    SseEvent,
    StartEvent,
)
from app.guide.retrieval.category_taxonomy import (
    category_profile_for_topic,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
)
from app.guide_runtime.composition import build_runtime_orchestrator
from tools.guide_gates.intent_model_ab import (
    MinimalTaskPlanEvaluator,
    PipelineEvaluation,
    PipelineEvaluationFailure,
    PipelineEvaluationFailureCode,
    PipelineEvaluationRequest,
)


_SSE_EVENT_ADAPTER = TypeAdapter(SseEvent)
_LEGACY_MODULE_PREFIXES = (
    "app.services",
    ".".join(("app", "api", "v1", "chat")),
)
_LEGACY_HOOK_LOCK = threading.RLock()


class _ProposalSemanticPort:
    def __init__(self, proposal: SemanticIntentProposal) -> None:
        self._proposal = SemanticIntentProposal.model_validate(
            proposal.model_dump(
                mode="python",
                round_trip=True,
                warnings=False,
            ),
            strict=True,
        )
        self.invocation_count = 0
        self._lock = threading.Lock()

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if not isinstance(context, SemanticContext):
            raise TypeError("context must be SemanticContext")
        with self._lock:
            self.invocation_count += 1
        return self._proposal.model_copy(deep=True)


class _FailingSemanticPort:
    def __init__(self, code: SemanticProviderFailureCode) -> None:
        self._code = code
        self.invocation_count = 0
        self._lock = threading.Lock()

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if not isinstance(context, SemanticContext):
            raise TypeError("context must be SemanticContext")
        with self._lock:
            self.invocation_count += 1
        raise SemanticProviderFailure(self._code)


class _LegacyImportObserver:
    def __init__(self) -> None:
        self.modules: set[str] = set()

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> None:
        del path, target
        if _is_legacy_module(fullname):
            self.modules.add(fullname)
        return None


class _LegacyExecutionObserver:
    def __init__(self) -> None:
        self.invocation_count = 0
        self._lock = threading.Lock()

    def __call__(
        self,
        frame: Any,
        event: str,
        arg: object,
    ) -> None:
        del arg
        if event != "call":
            return
        module_name = frame.f_globals.get("__name__")
        if (
            isinstance(module_name, str)
            and _is_legacy_module(module_name)
        ):
            with self._lock:
                self.invocation_count += 1


@contextmanager
def _observe_legacy_execution():
    """Observe bounded legacy imports/calls and restore all global hooks."""
    with _LEGACY_HOOK_LOCK:
        import_observer = _LegacyImportObserver()
        execution_observer = _LegacyExecutionObserver()
        previous_sys_profile = sys.getprofile()
        previous_thread_profile = threading.getprofile()

        def current_profile(
            frame: Any,
            event: str,
            arg: object,
        ) -> None:
            execution_observer(frame, event, arg)
            if previous_sys_profile is not None:
                previous_sys_profile(frame, event, arg)

        def child_profile(
            frame: Any,
            event: str,
            arg: object,
        ) -> None:
            execution_observer(frame, event, arg)
            if previous_thread_profile is not None:
                previous_thread_profile(frame, event, arg)

        sys.meta_path.insert(0, import_observer)
        try:
            sys.setprofile(current_profile)
            threading.setprofile(child_profile)
            yield import_observer, execution_observer
        finally:
            try:
                if threading.getprofile() is child_profile:
                    threading.setprofile(previous_thread_profile)
            finally:
                try:
                    if sys.getprofile() is current_profile:
                        sys.setprofile(previous_sys_profile)
                finally:
                    if import_observer in sys.meta_path:
                        sys.meta_path.remove(import_observer)


class ModelVerticalEvaluator:
    """Evaluate one proposal through the non-public model isolation API."""

    def __init__(
        self,
        *,
        orchestrator_factory: Callable[..., object] = (
            build_runtime_orchestrator
        ),
    ) -> None:
        if not callable(orchestrator_factory):
            raise TypeError("orchestrator_factory must be callable")
        self._orchestrator_factory = orchestrator_factory

    def evaluate(
        self,
        request: PipelineEvaluationRequest,
    ) -> PipelineEvaluation | PipelineEvaluationFailure:
        if not isinstance(request, PipelineEvaluationRequest):
            raise TypeError(
                "request must be PipelineEvaluationRequest"
            )
        try:
            return self._evaluate_validated(request)
        except Exception:
            return PipelineEvaluationFailure(
                code=PipelineEvaluationFailureCode.STREAM_FAILED
            )

    def _evaluate_validated(
        self,
        request: PipelineEvaluationRequest,
    ) -> PipelineEvaluation | PipelineEvaluationFailure:
        planned = MinimalTaskPlanEvaluator().evaluate(request)
        if request.proposal is not None:
            semantic = _ProposalSemanticPort(request.proposal)
        else:
            assert request.semantic_failure_code is not None
            semantic = _FailingSemanticPort(
                request.semantic_failure_code
            )
        try:
            temporary_state = tempfile.TemporaryDirectory(
                prefix="xiaoro-guide-ab-case-"
            )
        except Exception:
            return PipelineEvaluationFailure(
                code=PipelineEvaluationFailureCode.RUNTIME_BUILD_FAILED
            )

        with temporary_state as state_directory:
            _seed_before_state(
                Path(state_directory),
                request=request,
            )
            legacy_before = _loaded_legacy_modules()
            with _observe_legacy_execution() as (
                import_observer,
                execution_observer,
            ):
                try:
                    orchestrator = self._orchestrator_factory(
                        state_dir=Path(state_directory),
                        semantic_intent=semantic,
                    )
                except Exception:
                    return PipelineEvaluationFailure(
                        code=(
                            PipelineEvaluationFailureCode
                            .RUNTIME_BUILD_FAILED
                        ),
                        legacy_fallback_count=_failure_legacy_count(
                            _legacy_count(
                                before=legacy_before,
                                import_observer=import_observer,
                                execution_observer=execution_observer,
                                events=(),
                            )
                        ),
                    )

                try:
                    events = tuple(
                        _validated_events(
                            orchestrator.stream_text_vertical(
                                _turn_for(request),
                                semantic_context=request.context,
                            )
                        )
                    )
                except (AttributeError, TypeError, ValidationError):
                    return PipelineEvaluationFailure(
                        code=(
                            PipelineEvaluationFailureCode
                            .INVALID_EVENT_STREAM
                        ),
                        legacy_fallback_count=_failure_legacy_count(
                            _legacy_count(
                                before=legacy_before,
                                import_observer=import_observer,
                                execution_observer=execution_observer,
                                events=(),
                            )
                        ),
                    )
                except Exception:
                    return PipelineEvaluationFailure(
                        code=PipelineEvaluationFailureCode.STREAM_FAILED,
                        legacy_fallback_count=_failure_legacy_count(
                            _legacy_count(
                                before=legacy_before,
                                import_observer=import_observer,
                                execution_observer=execution_observer,
                                events=(),
                            )
                        ),
                    )

            legacy_fallback_count = _legacy_count(
                before=legacy_before,
                import_observer=import_observer,
                execution_observer=execution_observer,
                events=events,
            )
            failure_code = _event_stream_failure(events, request=request)
            if failure_code is not None:
                return PipelineEvaluationFailure(
                    code=failure_code,
                    legacy_fallback_count=_failure_legacy_count(
                        legacy_fallback_count
                    ),
                )
            if semantic.invocation_count != 1:
                return PipelineEvaluationFailure(
                    code=(
                        PipelineEvaluationFailureCode
                        .INVALID_EVENT_STREAM
                    ),
                    legacy_fallback_count=_failure_legacy_count(
                        legacy_fallback_count
                    ),
                )

            (
                selection_invocations,
                wrong_selections,
                runtime_plan_mismatch,
            ) = _observe_selection(events, request=request)
            return PipelineEvaluation(
                task_plan_mismatch_count=max(
                    planned.task_plan_mismatch_count,
                    runtime_plan_mismatch,
                ),
                hard_constraint_override_count=(
                    planned.hard_constraint_override_count
                ),
                unauthorized_constraint_transition_count=(
                    planned.unauthorized_constraint_transition_count
                ),
                product_selection_invocation_count=(
                    selection_invocations
                ),
                wrong_product_selection_count=wrong_selections,
                legacy_fallback_count=legacy_fallback_count,
            )


def _seed_before_state(
    state_directory: Path,
    *,
    request: PipelineEvaluationRequest,
) -> None:
    if request.before_state is None:
        return
    candidate_count = request.context.visible_candidate_count
    if candidate_count <= 0:
        raise ValueError(
            "state transition gate requires visible candidates"
        )
    state = SqliteConversationState(
        state_directory / "conversations.sqlite3",
        trusted_state_root=state_directory,
    )
    snapshot_values = {
        "session_id": f"intent-ab-{request.case_id}",
        "query_context": request.before_state,
        "candidates": tuple(
            DisplayedCandidateRef(
                product_id=ordinal,
                ordinal=ordinal,
                skin_match="unknown",
                matched_efficacies=(),
            )
            for ordinal in range(1, candidate_count + 1)
        ),
        "focused_candidate_ordinal": (
            request.context.focused_candidate_ordinal
        ),
    }
    for version in range(
        1,
        request.context.conversation_version + 1,
    ):
        state.save(
            ConversationSnapshot(
                version=version,
                **snapshot_values,
            ),
            expected_version=version - 1,
        )


def _turn_for(request: PipelineEvaluationRequest) -> UserTurn:
    return UserTurn(
        session_id=f"intent-ab-{request.case_id}",
        message=request.message,
        image_bundle_id=None,
        conversation_version=request.context.conversation_version,
    )


def _validated_events(
    events: Iterator[object],
) -> Iterator[SseEvent]:
    for event in events:
        yield _SSE_EVENT_ADAPTER.validate_python(
            event,
            strict=True,
        )


def _event_stream_failure(
    events: tuple[SseEvent, ...],
    *,
    request: PipelineEvaluationRequest,
) -> PipelineEvaluationFailureCode | None:
    if not events or not isinstance(events[0], StartEvent):
        return PipelineEvaluationFailureCode.INVALID_EVENT_STREAM
    if events[0].data.session_id != f"intent-ab-{request.case_id}":
        return PipelineEvaluationFailureCode.INVALID_EVENT_STREAM
    if any(isinstance(event, ErrorEvent) for event in events):
        return PipelineEvaluationFailureCode.STREAM_FAILED
    if not isinstance(events[-1], EndEvent):
        return PipelineEvaluationFailureCode.INVALID_EVENT_STREAM
    if sum(isinstance(event, StartEvent) for event in events) != 1:
        return PipelineEvaluationFailureCode.INVALID_EVENT_STREAM
    if sum(isinstance(event, EndEvent) for event in events) != 1:
        return PipelineEvaluationFailureCode.INVALID_EVENT_STREAM
    if sum(isinstance(event, IntentEvent) for event in events) != 1:
        return PipelineEvaluationFailureCode.INVALID_EVENT_STREAM
    return None


def _observe_selection(
    events: tuple[SseEvent, ...],
    *,
    request: PipelineEvaluationRequest,
) -> tuple[int, int, int]:
    intent = next(
        event for event in events
        if isinstance(event, IntentEvent)
    )
    products = tuple(
        event for event in events
        if isinstance(event, ProductsEvent)
    )
    decisions = tuple(
        event for event in events
        if isinstance(event, DecisionProcessEvent)
    )
    displays = tuple(
        event for event in events
        if isinstance(event, CardDisplayContractEvent)
    )
    clarifications = tuple(
        event for event in events
        if isinstance(event, ClarifyEvent)
    )
    selection_invocations = max(
        len(products),
        len(decisions),
        len(displays),
    )
    wrong_selection = 0
    runtime_plan_mismatch = 0

    if (
        request.semantic_failure_code is not None
        and selection_invocations == 0
    ):
        return (0, 0, 0)

    if request.task_plan.mode == "clarify":
        if (
            intent.data.mode != "clarify"
            or len(clarifications) != 1
            or selection_invocations > 0
        ):
            runtime_plan_mismatch = 1
        if selection_invocations:
            wrong_selection = selection_invocations
        return (
            selection_invocations,
            wrong_selection,
            runtime_plan_mismatch,
        )

    expected_mode = request.task_plan.mode
    if expected_mode in {"knowledge", "followup"}:
        runtime_plan_mismatch = int(
            intent.data.mode != expected_mode
            or bool(clarifications)
            or selection_invocations != 0
        )
        return (
            selection_invocations,
            selection_invocations,
            runtime_plan_mismatch,
        )
    if expected_mode == "comparison" and selection_invocations == 0:
        runtime_plan_mismatch = int(
            intent.data.mode != "comparison"
            or bool(clarifications)
        )
        return (0, 0, runtime_plan_mismatch)
    if intent.data.mode != expected_mode or clarifications:
        runtime_plan_mismatch = 1
    if (
        len(products) != 1
        or len(decisions) != 1
        or len(displays) != 1
    ):
        runtime_plan_mismatch = 1
        if selection_invocations:
            wrong_selection = selection_invocations
        return (
            selection_invocations,
            wrong_selection,
            runtime_plan_mismatch,
        )

    product_ids = tuple(
        card.product_id for card in products[0].data.cards
    )
    decision_ids = tuple(decisions[0].data.ordered_product_ids)
    display_ids = tuple(displays[0].data.visible_product_ids)
    expected_profile = _task_category_profile(request)
    event_positions = {
        type(event): index
        for index, event in enumerate(events)
        if isinstance(
            event,
            (
                DecisionProcessEvent,
                CardDisplayContractEvent,
                ProductsEvent,
            ),
        )
    }
    inconsistent = (
        selection_invocations != 1
        or product_ids != decision_ids
        or product_ids != display_ids
        or expected_profile is None
        or intent.data.category_profile is not expected_profile
        or any(
            card.category_profile is not expected_profile
            for card in products[0].data.cards
        )
        or not (
            event_positions[DecisionProcessEvent]
            < event_positions[CardDisplayContractEvent]
            < event_positions[ProductsEvent]
        )
    )
    if inconsistent:
        wrong_selection = selection_invocations
    return (
        selection_invocations,
        wrong_selection,
        runtime_plan_mismatch,
    )


def _task_category_profile(
    request: PipelineEvaluationRequest,
):
    categories = [
        constraint.value
        for constraint in request.task_plan.constraints
        if isinstance(constraint, CategoryConstraint)
    ]
    if len(categories) != 1:
        return None
    return category_profile_for_topic(categories[0])


def _legacy_count(
    *,
    before: set[str],
    import_observer: _LegacyImportObserver,
    execution_observer: _LegacyExecutionObserver,
    events: tuple[object, ...],
) -> int:
    imported = (
        _loaded_legacy_modules() - before
    ) | import_observer.modules
    return (
        len(imported)
        + execution_observer.invocation_count
        + sum(
            _event_has_legacy_marker(event)
            for event in events
        )
    )


def _failure_legacy_count(value: int) -> int | None:
    return value if value > 0 else None


def _loaded_legacy_modules() -> set[str]:
    return {
        name for name in sys.modules
        if _is_legacy_module(name)
    }


def _is_legacy_module(name: str) -> bool:
    return any(
        name == prefix or name.startswith(f"{prefix}.")
        for prefix in _LEGACY_MODULE_PREFIXES
    )


def _event_has_legacy_marker(event: object) -> bool:
    event_name = getattr(event, "event", None)
    if event_name in {"legacy", "legacy_fallback"}:
        return True
    data = getattr(event, "data", None)
    owner = getattr(data, "owner", None)
    owner_value: Any = getattr(owner, "value", owner)
    return owner_value == "legacy"


__all__ = ["ModelVerticalEvaluator"]
