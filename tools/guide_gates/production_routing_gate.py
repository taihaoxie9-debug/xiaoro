"""Trusted production-routing gate for the Guide text orchestrator.

Unlike the model vertical evaluator, this gate always calls the real
``TextRecommendationOrchestrator.stream`` entrypoint. Fixture context is
materialized through the production SQLite state contract with real Canonical
candidate IDs; no expected winner or product fact is injected.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import threading

from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.adapters.state.sqlite_conversation_state import (
    SqliteConversationState,
)
from app.guide.application.contracts import UserTurn
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.intent.task_planning import plan_task
from app.guide.presentation.sse_events import (
    CardDisplayContractEvent,
    DecisionProcessEvent,
    EndEvent,
    ErrorEvent,
    IntentEvent,
    ProductsEvent,
    SseEvent,
    StartEvent,
)
from app.guide.retrieval.canonical_retrieval import retrieve_candidates
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_revision_confirmations,
)
from app.guide.understanding.followup_parsing import parse_followup
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import (
    ActiveConstraintKind,
    ConfirmedProfileField,
    SemanticContext,
    SemanticIntentProposal,
)
from app.guide_runtime.composition import REPO_ROOT, build_runtime_orchestrator
from tools.guide_gates.guide_pipeline_evaluator import (
    _legacy_count,
    _loaded_legacy_modules,
    _observe_legacy_execution,
    _validated_events,
)
from tools.guide_gates.intent_model_ab import IntentCase


OPEN_SEMANTIC_CASE_IDS = (
    "assess-011-candidate-ordinal",
    "assess-013-pronoun-current",
    "clar-015-revision-missing-target",
    "cmp-010-candidate-ordinals",
    "cmp-012-pronoun-second",
    "follow-007-pronoun-it",
    "follow-009-budget-revision",
    "follow-011-skin-revision",
    "follow-012-alcohol-followup",
    "follow-015-injection-winner",
    "know-012-candidate-reference",
    "suit-009-budget-fit",
    "suit-011-candidate-ordinal",
    "suit-014-revision-skin",
)
WRONG_CARD_CASE_IDS = (
    "assess-011-candidate-ordinal",
    "cmp-010-candidate-ordinals",
    "follow-012-alcohol-followup",
    "follow-015-injection-winner",
    "know-012-candidate-reference",
)
CLOSED_OPERATION_CASE_IDS = (
    "follow-001-second-candidate",
    "follow-002-first-candidate",
)


@dataclass(frozen=True, slots=True)
class FixtureSnapshotResult:
    status: str
    reason: str | None
    snapshot: ConversationSnapshot | None
    semantic_context: SemanticContext
    canonical_product_ids: tuple[int, ...]
    profile_owner: ProfileOwnerRef


@dataclass(frozen=True, slots=True)
class ProductionRoutingObservation:
    case_id: str
    message: str
    entrypoint: str
    snapshot_status: str
    snapshot_before: ConversationSnapshot | None
    snapshot_after: ConversationSnapshot | None
    semantic_invocation_count: int
    event_types: tuple[str, ...]
    product_event_ids: tuple[int, ...]
    terminal_event: str | None
    selection_event_count: int
    legacy_fallback_count: int
    operation_source_span: tuple[int, int] | None
    exact_summary: tuple[str, ...]
    semantic_goal: str | None
    merger_trace: tuple[str, ...]
    task_plan_mode: str | None
    retrieval_status: str
    decision_status: str


class _BoundSemanticPort:
    def __init__(
        self,
        *,
        proposal: SemanticIntentProposal,
        expected_context: SemanticContext,
    ) -> None:
        self._proposal = proposal.model_copy(deep=True)
        self._expected_context = expected_context.model_copy(deep=True)
        self.invocation_count = 0
        self._lock = threading.Lock()

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if context != self._expected_context:
            raise ValueError("production semantic context mismatch")
        with self._lock:
            self.invocation_count += 1
        return self._proposal.model_copy(deep=True)


class ProductionRoutingGate:
    """Evaluate fixture routing through the production ``stream`` method."""

    def __init__(self, *, orchestrator_factory=build_runtime_orchestrator):
        if not callable(orchestrator_factory):
            raise TypeError("orchestrator_factory must be callable")
        self._orchestrator_factory = orchestrator_factory

    def evaluate(
        self,
        *,
        case: IntentCase,
        state_dir: str | Path,
        proposal: SemanticIntentProposal | None = None,
        semantic_port: object | None = None,
    ) -> ProductionRoutingObservation:
        if not isinstance(case, IntentCase):
            raise TypeError("case must be IntentCase")
        if (proposal is None) == (semantic_port is None):
            raise ValueError(
                "supply exactly one proposal or semantic_port"
            )
        state_root = Path(state_dir).expanduser().absolute()
        session_id = f"task6-{case.case_id}"
        fixture = build_fixture_snapshot(
            case=case,
            state_dir=state_root,
            session_id=session_id,
        )
        if fixture.status == "UNCONSTRUCTIBLE":
            raise ValueError(fixture.reason or "fixture is unconstructible")

        active_semantic = semantic_port
        if proposal is not None:
            runtime_context = resolve_semantic_context(
                conversation_version=case.context.conversation_version,
                snapshot=fixture.snapshot,
            )
            active_semantic = _BoundSemanticPort(
                proposal=proposal,
                expected_context=runtime_context,
            )
        if active_semantic is None:
            raise AssertionError("semantic port is unavailable")

        turn = UserTurn(
            session_id=session_id,
            message=case.message,
            profile_owner=fixture.profile_owner,
            conversation_version=case.context.conversation_version,
        )
        legacy_before = _loaded_legacy_modules()
        with _observe_legacy_execution() as (
            import_observer,
            execution_observer,
        ):
            orchestrator = self._orchestrator_factory(
                state_dir=state_root,
                semantic_intent=active_semantic,
            )
            events = tuple(
                _validated_events(orchestrator.stream(turn))
            )
            _validate_production_events(
                events,
                session_id=session_id,
            )
        legacy_fallback_count = _legacy_count(
            before=legacy_before,
            import_observer=import_observer,
            execution_observer=execution_observer,
            events=events,
        )
        state = SqliteConversationState(
            state_root / "conversations.sqlite3",
            trusted_state_root=state_root,
        )
        snapshot_after = state.load(session_id)
        return _observation(
            case=case,
            proposal=proposal,
            fixture=fixture,
            semantic_port=active_semantic,
            events=events,
            snapshot_after=snapshot_after,
            legacy_fallback_count=legacy_fallback_count,
        )


def build_fixture_snapshot(
    *,
    case: IntentCase,
    state_dir: str | Path,
    session_id: str,
    repo_root: Path = REPO_ROOT,
) -> FixtureSnapshotResult:
    """Materialize a legal snapshot from typed fixture context."""
    context = case.context
    state_root = Path(state_dir).expanduser().absolute()
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner = _fixture_profile_owner(case.case_id)
    empty_context = resolve_semantic_context(
        conversation_version=context.conversation_version,
        snapshot=None,
    )
    if context.conversation_version == 0:
        if context != empty_context:
            return FixtureSnapshotResult(
                status="UNCONSTRUCTIBLE",
                reason="zero_version_context_requires_empty_state",
                snapshot=None,
                semantic_context=empty_context,
                canonical_product_ids=(),
                profile_owner=owner,
            )
        return FixtureSnapshotResult(
            status="EMPTY",
            reason=None,
            snapshot=None,
            semantic_context=empty_context,
            canonical_product_ids=(),
            profile_owner=owner,
        )
    if context.visible_candidate_count > 4:
        return FixtureSnapshotResult(
            status="UNCONSTRUCTIBLE",
            reason="candidate_count_exceeds_snapshot_contract",
            snapshot=None,
            semantic_context=empty_context,
            canonical_product_ids=(),
            profile_owner=owner,
        )
    if (
        context.active_topic is None
        or context.visible_candidate_count == 0
    ):
        return FixtureSnapshotResult(
            status="UNCONSTRUCTIBLE",
            reason="text_snapshot_requires_topic_and_candidates",
            snapshot=None,
            semantic_context=empty_context,
            canonical_product_ids=(),
            profile_owner=owner,
        )

    unsupported_profile_fields = set(
        context.confirmed_profile_fields
    ) - {
        ConfirmedProfileField.SKIN_TYPE,
        ConfirmedProfileField.INGREDIENT_EXCLUSION,
    }
    if unsupported_profile_fields:
        return FixtureSnapshotResult(
            status="UNCONSTRUCTIBLE",
            reason="profile_field_requires_unavailable_fixture_value",
            snapshot=None,
            semantic_context=empty_context,
            canonical_product_ids=(),
            profile_owner=owner,
        )

    canonical = repo_root / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    retrieval = retrieve_candidates(
        CanonicalGuideCatalog(reader),
        category=context.active_topic,
    )
    product_ids = tuple(
        candidate.product_id
        for candidate in retrieval.candidates[
            : context.visible_candidate_count
        ]
    )
    if len(product_ids) != context.visible_candidate_count:
        return FixtureSnapshotResult(
            status="UNCONSTRUCTIBLE",
            reason="canonical_candidates_unavailable",
            snapshot=None,
            semantic_context=empty_context,
            canonical_product_ids=(),
            profile_owner=owner,
        )

    query_context = RecommendationQueryContext(
        category=context.active_topic.value,
        budget_minimum=(
            None
            if ActiveConstraintKind.BUDGET
            not in context.active_constraint_kinds
            else Decimal("1")
        ),
        budget_maximum=(
            None
            if ActiveConstraintKind.BUDGET
            not in context.active_constraint_kinds
            else Decimal("500")
        ),
        skin=(
            "sensitive"
            if ActiveConstraintKind.SKIN
            in context.active_constraint_kinds
            else None
        ),
        efficacy=(
            "repair"
            if ActiveConstraintKind.EFFICACY
            in context.active_constraint_kinds
            and context.active_topic is TopicCode.SERUM
            else None
        ),
        exclusions=(
            ("酒精",)
            if ActiveConstraintKind.INGREDIENT_EXCLUSION
            in context.active_constraint_kinds
            else ()
        ),
    )
    candidates = tuple(
        DisplayedCandidateRef(
            product_id=product_id,
            ordinal=ordinal,
            skin_match="unknown",
            matched_efficacies=(),
        )
        for ordinal, product_id in enumerate(product_ids, start=1)
    )
    state = SqliteConversationState(
        state_root / "conversations.sqlite3",
        trusted_state_root=state_root,
    )
    snapshot: ConversationSnapshot | None = None
    for version in range(1, context.conversation_version + 1):
        snapshot = state.save(
            ConversationSnapshot(
                session_id=session_id,
                version=version,
                profile_owner=owner,
                query_context=query_context,
                candidates=candidates,
                focused_candidate_ordinal=(
                    context.focused_candidate_ordinal
                ),
            ),
            expected_version=version - 1,
        )
    if snapshot is None:
        raise AssertionError("fixture snapshot was not persisted")
    semantic_context = resolve_semantic_context(
        conversation_version=context.conversation_version,
        snapshot=snapshot,
    )
    expected_context = context
    if context.active_dialogue is None:
        expected_context = context.model_copy(
            update={
                "active_dialogue": semantic_context.active_dialogue,
            },
            deep=True,
        )
    if semantic_context != expected_context:
        return FixtureSnapshotResult(
            status="UNCONSTRUCTIBLE",
            reason="fixture_context_does_not_round_trip",
            snapshot=None,
            semantic_context=semantic_context,
            canonical_product_ids=product_ids,
            profile_owner=owner,
        )
    return FixtureSnapshotResult(
        status="BUILT",
        reason=None,
        snapshot=snapshot,
        semantic_context=context,
        canonical_product_ids=product_ids,
        profile_owner=owner,
    )


def _fixture_profile_owner(case_id: str) -> ProfileOwnerRef:
    digest = sha256(
        f"task6-production-routing\0{case_id}".encode("utf-8")
    ).hexdigest()
    return ProfileOwnerRef(
        scope="local_demo",
        subject_id=f"task6_fixture_{digest}",
    )


def _validate_production_events(
    events: tuple[SseEvent, ...],
    *,
    session_id: str,
) -> None:
    if not events or not isinstance(events[0], StartEvent):
        raise ValueError("production stream requires one leading start")
    if events[0].data.session_id != session_id:
        raise ValueError("production start session mismatch")
    if not isinstance(events[-1], EndEvent):
        raise ValueError("production stream requires one trailing end")
    if sum(isinstance(event, StartEvent) for event in events) != 1:
        raise ValueError("production stream requires exactly one start")
    if sum(isinstance(event, EndEvent) for event in events) != 1:
        raise ValueError("production stream requires exactly one end")
    if sum(isinstance(event, IntentEvent) for event in events) != 1:
        raise ValueError("production stream requires exactly one intent")
    if any(isinstance(event, ErrorEvent) for event in events):
        raise ValueError("production routing gate rejects error events")


def _observation(
    *,
    case: IntentCase,
    proposal: SemanticIntentProposal | None,
    fixture: FixtureSnapshotResult,
    semantic_port: object,
    events: tuple[SseEvent, ...],
    snapshot_after: ConversationSnapshot | None,
    legacy_fallback_count: int,
) -> ProductionRoutingObservation:
    followup = parse_followup(case.message)
    operation_source_span = (
        (
            followup.source_span.start,
            followup.source_span.end,
        )
        if followup is not None and followup.source_span is not None
        else None
    )
    exact_constraints, exact_issues = parse_exact_constraints(case.message)
    exact_summary = tuple(
        type(item).__name__ for item in exact_constraints
    ) + tuple(f"issue:{item.code}" for item in exact_issues)
    merger_trace: tuple[str, ...] = ()
    task_plan_mode: str | None = None
    if proposal is not None and operation_source_span is None:
        merged = merge_intent_signals(
            message=case.message,
            exact_constraints=exact_constraints,
            exact_issues=exact_issues,
            exact_revision_confirmations=(
                parse_exact_revision_confirmations(case.message)
            ),
            semantic=proposal,
            context=case.context,
        )
        merger_trace = tuple(
            f"{item.field}:{item.resolution}"
            for item in merged.signal_trace
        )
        task_plan_mode = plan_task(merged).mode

    selection_event_count = max(
        sum(isinstance(event, ProductsEvent) for event in events),
        sum(
            isinstance(event, DecisionProcessEvent)
            for event in events
        ),
        sum(
            isinstance(event, CardDisplayContractEvent)
            for event in events
        ),
    )
    return ProductionRoutingObservation(
        case_id=case.case_id,
        message=case.message,
        entrypoint="stream",
        snapshot_status=fixture.status,
        snapshot_before=fixture.snapshot,
        snapshot_after=snapshot_after,
        semantic_invocation_count=int(
            getattr(semantic_port, "invocation_count", -1)
        ),
        event_types=tuple(event.event for event in events),
        product_event_ids=tuple(
            card.product_id
            for event in events
            if isinstance(event, ProductsEvent)
            for card in event.data.cards
        ),
        terminal_event=(
            events[-1].event
            if events and isinstance(events[-1], EndEvent)
            else None
        ),
        selection_event_count=selection_event_count,
        legacy_fallback_count=legacy_fallback_count,
        operation_source_span=operation_source_span,
        exact_summary=exact_summary,
        semantic_goal=proposal.goal.value if proposal is not None else None,
        merger_trace=merger_trace,
        task_plan_mode=task_plan_mode,
        retrieval_status=(
            "OBSERVED_SELECTION"
            if selection_event_count
            else "NOT_INVOKED_OR_NO_SELECTION"
        ),
        decision_status=(
            "OBSERVED"
            if any(
                isinstance(event, DecisionProcessEvent)
                for event in events
            )
            else "NOT_INVOKED"
        ),
    )


__all__ = [
    "CLOSED_OPERATION_CASE_IDS",
    "OPEN_SEMANTIC_CASE_IDS",
    "WRONG_CARD_CASE_IDS",
    "FixtureSnapshotResult",
    "ProductionRoutingGate",
    "ProductionRoutingObservation",
    "build_fixture_snapshot",
]
