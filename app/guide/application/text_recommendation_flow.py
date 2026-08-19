"""Slice 1 文本推荐编排。

应用层只负责串联六层、产出 typed SSE 事件，不持有词表、
商品过滤、排序或文案推理规则。
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
import logging
import re
from typing import Literal

from app.guide.application.contracts import UserTurn
from app.guide.application.product_evidence_answer import (
    render_product_evidence_answer,
)
from app.guide.application.general_knowledge_answer import (
    render_general_knowledge_answer,
)
from app.guide.application.image_alternative_count import (
    requested_recommendation_result_count,
)
from app.guide.application.query_context import (
    apply_session_profile_to_task,
    query_context_to_constraints,
    task_plan_to_query_context,
)
from app.guide.application.pending_turn import (
    PendingReply,
    build_pending_turn,
    classify_pending_reply,
    resume_pending_recommendation,
)
from app.guide.application.scenario_inputs import build_scenario_inputs
from app.guide.decision.contracts import (
    DecisionResult,
    RelativeComparisonResult,
    WinnerStatus,
)
from app.guide.decision.followup import decide_followup
from app.guide.decision.concept_ranking import rank_common_concepts
from app.guide.decision.facet_ranking import rank_soft_facets
from app.guide.decision.ports import DecisionFactPort
from app.guide.decision.recommendation import decide_recommendation
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
)
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStatePort,
    FeedbackPort,
    FeedbackWriteStatus,
    SessionLockPort,
)
from app.guide.feedback.profile_policy import ResolvedProfileContext
from app.guide.intent.contracts import (
    BudgetRevisionPlan,
    CategoryConstraint,
    ConceptConstraint,
    FacetConstraint,
    FollowupPlan,
    RelativeRequirement,
    SkinRevisionPlan,
    TaskPlan,
)
from app.guide.intent.budget_revision_planning import (
    plan_budget_revision,
)
from app.guide.intent.followup_planning import plan_followup
from app.guide.intent.signal_merger import merge_context_signals
from app.guide.intent.skin_revision_planning import plan_skin_revision
from app.guide.intent.task_planning import plan_task
from app.guide.intent.transition_planning import (
    plan_code_owned_transitions,
)
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.presentation.budget_revision_response import (
    build_budget_revision_message,
)
from app.guide.presentation.card_display import (
    comparison_card_display,
    recommendation_card_display,
    single_product_card_display,
)
from app.guide.presentation.contracts import (
    CardDisplayContract,
    ProductCard,
    ProductCardFacts,
    ResponsePlan,
)
from app.guide.presentation.copywriter_contracts import (
    LockedFact,
    PresentationMode,
)
from app.guide.presentation.followup_response import (
    build_followup_cards,
    build_followup_message,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompileInputs,
    PresentationCompiler,
)
from app.guide.presentation.presentation_packet import (
    build_presentation_packet,
)
from app.guide.presentation.ports import PresentationFactPort
from app.guide.presentation.response_planning import (
    build_product_card,
    build_response_plan,
)
from app.guide.presentation.skin_revision_response import (
    build_skin_revision_message,
)
from app.guide.presentation.sse_events import (
    AnswerContractData,
    AnswerContractEvent,
    CardDisplayContractEvent,
    ClarifyData,
    ClarifyEvent,
    ConceptSlotData,
    DecisionProcessData,
    DecisionProcessEvent,
    EndData,
    EndEvent,
    ErrorData,
    ErrorEvent,
    GeneralKnowledgeEvent,
    IntentData,
    IntentEvent,
    MessageData,
    MessageEvent,
    MerchantClaimEvidenceData,
    MerchantClaimsData,
    MerchantClaimsEvent,
    PitfallsData,
    PitfallsEvent,
    ProductsData,
    ProductsEvent,
    ProductEvidenceData,
    ProductEvidenceEvent,
    PresentationContractEvent,
    ReviewEvidenceData,
    ReviewEvidenceEvent,
    ScenarioEvidenceData,
    ScenarioEvidenceEvent,
    SelectionSlotData,
    SseEvent,
    StageData,
    StageEvent,
    StartData,
    StartEvent,
)
from app.guide.retrieval.canonical_retrieval import retrieve_candidates
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.retrieval.category_taxonomy import (
    canonical_categories_for,
    category_profile_for_topic,
)
from app.guide.retrieval.ports import (
    CategoryCatalogPort,
    ScenarioEvidencePort,
)
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
    ProductResolutionIssue,
    ProductNameResolver,
    ResolvedProductBinding,
    merge_batch_and_specific_bindings,
)
from app.guide.retrieval.pitfall_contracts import TypedPitfall
from app.guide.retrieval.product_evidence_retrieval import (
    EvidenceQuery,
    ProductEvidenceRetriever,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)
from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeQuery,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from app.guide.retrieval.review_reader import ReviewEvidenceReader
from app.guide.retrieval.merchant_claim_reader import MerchantClaimReader
from app.guide.retrieval.review_summary import build_review_summary
from app.guide.retrieval.review_summary_contracts import (
    ReviewSummaryResult,
)
from app.guide.retrieval.scenario_pitfalls import (
    project_scenario_pitfalls,
)
from app.guide.understanding.budget_revision_parsing import (
    parse_budget_revision,
)
from app.guide.understanding.context_resolver import (
    resolve_context_constraint_signals,
    resolve_semantic_context,
)
from app.guide.understanding.followup_parsing import parse_followup
from app.guide.understanding.ports import TextUnderstandingPort
from app.guide.understanding.contracts import (
    ExactRevisionTarget,
    ProductMentionDraft,
    ReferenceDraft,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_revision_confirmations,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    SemanticContext,
    SemanticProductMention,
)
from app.guide.understanding.skin_revision_parsing import (
    parse_skin_revision,
)
from app.guide.understanding.text_understanding import (
    ExactOnlyTextUnderstanding,
)

logger = logging.getLogger(__name__)

RevisionKind = Literal["budget", "skin", "context"]


class TextRecommendationOrchestrator:
    def __init__(
        self,
        *,
        category_catalog: CategoryCatalogPort,
        scenario_evidence: ScenarioEvidencePort,
        decision_facts: DecisionFactPort,
        presentation_facts: PresentationFactPort,
        review_evidence: ReviewEvidenceReader,
        merchant_claims: MerchantClaimReader | None = None,
        product_evidence: ProductEvidenceRetriever | None = None,
        general_knowledge: GeneralKnowledgeRetriever | None = None,
        concept_reader: SelectionParentConceptReader | None = None,
        feedback: FeedbackPort,
        conversation_state: ConversationStatePort,
        session_locks: SessionLockPort,
        understanding: TextUnderstandingPort | None = None,
        product_name_resolver: ProductNameResolver | None = None,
        presentation_compiler: PresentationCompiler | None = None,
        profile_resolver: (
            Callable[..., ResolvedProfileContext] | None
        ) = None,
    ) -> None:
        self._category_catalog = category_catalog
        self._scenario_evidence = scenario_evidence
        self._decision_facts = decision_facts
        self._presentation_facts = presentation_facts
        self._review_evidence = review_evidence
        self._merchant_claims = merchant_claims
        self._product_evidence = product_evidence
        self._general_knowledge = general_knowledge
        self._concept_reader = concept_reader
        self._feedback = feedback
        self._conversation_state = conversation_state
        self._session_locks = session_locks
        self._understanding = (
            understanding
            if understanding is not None
            else ExactOnlyTextUnderstanding()
        )
        self._product_name_resolver = product_name_resolver
        self._presentation_compiler = (
            presentation_compiler
            if presentation_compiler is not None
            else PresentationCompiler(copywriter=None)
        )
        self._profile_resolver = profile_resolver

    def orchestrate(self, turn: UserTurn) -> ResponsePlan:
        snapshot = self._conversation_state.load(turn.session_id)
        profile_context = self._resolve_profile_context(turn)
        understanding = self._understanding.understand(
            turn.message,
            context=resolve_semantic_context(
                conversation_version=turn.conversation_version,
                snapshot=snapshot,
                profile_context=profile_context,
            ),
        )
        understanding = merge_context_signals(
            understanding,
            signals=resolve_context_constraint_signals(
                snapshot=snapshot,
                profile_context=profile_context,
            ),
        )
        understanding = self._recover_explicit_product_mentions(
            turn.message,
            understanding,
        )
        product_resolution = (
            self._resolve_product_mentions_or_references(
                turn.message,
                understanding,
                snapshot=snapshot,
            )
        )
        task = plan_task(
            understanding,
            resolved_product_ids=product_resolution.product_ids,
            product_resolution_issue=product_resolution.issue,
            message=turn.message,
        )
        task = self._prepare_image_similarity_task(task)
        task = plan_code_owned_transitions(
            message=turn.message,
            understanding=understanding,
            task=task,
            previous=(
                snapshot.query_context
                if snapshot is not None
                else None
            ),
        ).task_plan
        if snapshot is not None and snapshot.session_profile is not None:
            task = apply_session_profile_to_task(
                task,
                snapshot.session_profile,
            )
        if task.mode == "clarify":
            raise ValueError("clarification has no recommendation plan")
        if task.mode != "recommend":
            raise ValueError(
                "orchestrate only supports recommendation plans"
            )
        scenario_inputs = build_scenario_inputs(
            task,
            message=turn.message,
        )
        effective_task = task.model_copy(
            update={
                "constraints": scenario_inputs.decision.constraints,
            },
            deep=True,
        )
        category = _category_constraint(effective_task.constraints)
        retrieval = retrieve_candidates(
            self._category_catalog,
            category=category.value,
        )
        decision = decide_recommendation(
            self._decision_facts,
            retrieval,
            constraints=effective_task.constraints,
            safety_sensitive=effective_task.safety_sensitive,
            concept_reader=self._concept_reader,
        )
        return self._build_plan(decision)

    def stream(self, turn: UserTurn) -> Iterator[SseEvent]:
        yield from self._stream_entry(turn, self._stream_locked)

    def stream_pending_reply(
        self,
        turn: UserTurn,
        *,
        reply: PendingReply,
    ) -> Iterator[SseEvent]:
        if type(reply) is not PendingReply:
            raise TypeError("reply must be an exact PendingReply")
        yield from self._stream_entry(
            turn,
            lambda locked_turn: self._stream_pending_reply_locked(
                locked_turn,
                reply=reply,
            ),
        )

    def stream_text_vertical(
        self,
        turn: UserTurn,
        *,
        semantic_context: SemanticContext | None = None,
    ) -> Iterator[SseEvent]:
        """Run model-isolation text vertical; this is not public routing."""
        if semantic_context is not None and not isinstance(
            semantic_context,
            SemanticContext,
        ):
            raise TypeError(
                "semantic_context must be SemanticContext or None"
            )
        yield from self._stream_entry(
            turn,
            lambda locked_turn: self._stream_text_vertical_locked(
                locked_turn,
                semantic_context=semantic_context,
            ),
        )

    def resolve_product_bindings(
        self,
        *,
        message: str,
        understanding: StructuredUnderstanding,
        snapshot: ConversationSnapshot | None,
    ) -> tuple[ResolvedProductBinding, ...]:
        return self.resolve_product_resolution(
            message=message,
            understanding=understanding,
            snapshot=snapshot,
        ).bindings

    def resolve_product_resolution(
        self,
        *,
        message: str,
        understanding: StructuredUnderstanding,
        snapshot: ConversationSnapshot | None,
    ) -> ProductMentionResolution:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be nonempty")
        if type(understanding) is not StructuredUnderstanding:
            raise TypeError(
                "understanding must be an exact StructuredUnderstanding"
            )
        if (
            snapshot is not None
            and type(snapshot) is not ConversationSnapshot
        ):
            raise TypeError(
                "snapshot must be an exact ConversationSnapshot or None"
            )
        recovered = self._recover_explicit_product_mentions(
            message,
            understanding,
        )
        return self._resolve_product_mentions_or_references(
            message,
            recovered,
            snapshot=snapshot,
        )

    def stream_understanding(
        self,
        turn: UserTurn,
        *,
        understanding: StructuredUnderstanding,
        route_decision: UnifiedRouteDecision,
        product_bindings: tuple[ResolvedProductBinding, ...],
        product_resolution_issue: ProductResolutionIssue | None = None,
    ) -> Iterator[SseEvent]:
        if type(understanding) is not StructuredUnderstanding:
            raise TypeError(
                "understanding must be an exact StructuredUnderstanding"
            )
        if type(route_decision) is not UnifiedRouteDecision:
            raise TypeError(
                "route_decision must be an exact UnifiedRouteDecision"
            )
        if any(
            not isinstance(item, ResolvedProductBinding)
            for item in product_bindings
        ):
            raise TypeError(
                "product_bindings must contain resolved bindings"
            )
        yield from self._stream_entry(
            turn,
            lambda locked_turn: self._stream_preunderstood_locked(
                locked_turn,
                understanding=understanding,
                route_decision=route_decision,
                product_bindings=product_bindings,
                product_resolution_issue=product_resolution_issue,
            ),
        )

    def stream_understanding_body(
        self,
        turn: UserTurn,
        *,
        understanding: StructuredUnderstanding,
        route_decision: UnifiedRouteDecision,
        product_bindings: tuple[ResolvedProductBinding, ...],
        product_resolution_issue: ProductResolutionIssue | None = None,
    ) -> Iterator[SseEvent]:
        """Run a pretranslated turn while an outer flow owns the lock."""
        if type(understanding) is not StructuredUnderstanding:
            raise TypeError(
                "understanding must be an exact StructuredUnderstanding"
            )
        if type(route_decision) is not UnifiedRouteDecision:
            raise TypeError(
                "route_decision must be an exact UnifiedRouteDecision"
            )
        if any(
            not isinstance(item, ResolvedProductBinding)
            for item in product_bindings
        ):
            raise TypeError(
                "product_bindings must contain resolved bindings"
            )
        yield from self._stream_preunderstood_locked(
            turn,
            understanding=understanding,
            route_decision=route_decision,
            product_bindings=product_bindings,
            product_resolution_issue=product_resolution_issue,
        )

    def _stream_preunderstood_locked(
        self,
        turn: UserTurn,
        *,
        understanding: StructuredUnderstanding,
        route_decision: UnifiedRouteDecision,
        product_bindings: tuple[ResolvedProductBinding, ...],
        product_resolution_issue: ProductResolutionIssue | None = None,
    ) -> Iterator[SseEvent]:
        snapshot = self._conversation_state.load(turn.session_id)
        if (
            snapshot is not None
            and snapshot.profile_owner != turn.profile_owner
        ):
            raise ConversationStateConflict(turn.session_id)
        yield from self._stream_planned_text_or_stale(
            turn,
            snapshot=snapshot,
            understanding_override=understanding,
            product_bindings_override=product_bindings,
            product_resolution_issue=product_resolution_issue,
            route_decision=route_decision,
        )

    def _stream_entry(
        self,
        turn: UserTurn,
        stream_locked: Callable[[UserTurn], Iterator[SseEvent]],
    ) -> Iterator[SseEvent]:
        yield StartEvent(data=StartData(session_id=turn.session_id))
        with self._session_locks.hold(turn.session_id):
            try:
                buffered_events = list(stream_locked(turn))
            except ConversationStateConflict:
                latest = self._conversation_state.load(turn.session_id)
                buffered_events = [
                    IntentEvent(data=IntentData(mode="clarify")),
                    ClarifyEvent(
                        data=ClarifyData(
                            question=(
                                "会话状态已变化，请基于最新结果重试。"
                            ),
                            clarification_code=(
                                ClarificationCode.REFERENCE
                            ),
                        )
                    ),
                    EndEvent(
                        data=EndData(
                            conversation_version=self._snapshot_version(
                                latest
                            )
                        )
                    ),
                ]
            except Exception:
                logger.exception(
                    "slice 1 recommendation failed for session_id=%s",
                    turn.session_id,
                )
                buffered_events = [
                    ErrorEvent(
                        data=ErrorData(
                            code="GUIDE_INTERNAL_ERROR",
                            message="推荐暂时不可用，请稍后重试。",
                        )
                    )
                ]
        yield from buffered_events

    def _stream_text_vertical_locked(
        self,
        turn: UserTurn,
        *,
        semantic_context: SemanticContext | None,
    ) -> Iterator[SseEvent]:
        """Bypass closed-operation dispatch for model gate isolation only."""
        snapshot = self._conversation_state.load(turn.session_id)
        if (
            snapshot is not None
            and snapshot.profile_owner != turn.profile_owner
        ):
            raise ConversationStateConflict(turn.session_id)
        yield from self._stream_planned_text_or_stale(
            turn,
            snapshot=snapshot,
            allow_unbound_references=True,
            semantic_context=semantic_context,
        )

    def _stream_locked(self, turn: UserTurn) -> Iterator[SseEvent]:
        snapshot = self._conversation_state.load(turn.session_id)
        if (
            snapshot is not None
            and snapshot.profile_owner != turn.profile_owner
        ):
            raise ConversationStateConflict(turn.session_id)
        if (
            snapshot is not None
            and snapshot.pending_turn is not None
        ):
            if turn.conversation_version != snapshot.version:
                yield from self._stream_planned_text_or_stale(
                    turn,
                    snapshot=snapshot,
                )
                return
            pending_reply = classify_pending_reply(
                message=turn.message,
                pending=snapshot.pending_turn,
            )
            yield from self._stream_pending_reply_or_replace(
                turn,
                snapshot=snapshot,
                reply=pending_reply,
            )
            return
        followup_draft = parse_followup(turn.message)
        followup_task = plan_followup(
            followup_draft,
            snapshot=snapshot,
            request_version=turn.conversation_version,
        )
        if followup_task is not None:
            yield from self._stream_followup(
                turn,
                snapshot=snapshot,
                plan=followup_task,
            )
            return
        revision_confirmations = tuple(
            parse_exact_revision_confirmations(turn.message)
        )
        skin_draft = parse_skin_revision(turn.message)
        skin_plan = plan_skin_revision(
            skin_draft,
            query_context=(
                snapshot.query_context
                if snapshot is not None
                else None
            ),
            request_version=turn.conversation_version,
            snapshot_version=(
                snapshot.version
                if snapshot is not None
                else None
            ),
            revision_confirmation=next(
                (
                    proof
                    for proof in revision_confirmations
                    if proof.target is ExactRevisionTarget.SKIN
                ),
                None,
            ),
        )
        if skin_plan is not None:
            yield from self._stream_skin_revision(
                turn,
                snapshot=snapshot,
                plan=skin_plan,
            )
            return
        budget_draft = parse_budget_revision(turn.message)
        budget_plan = plan_budget_revision(
            budget_draft,
            query_context=(
                snapshot.query_context
                if snapshot is not None
                else None
            ),
            request_version=turn.conversation_version,
            snapshot_version=(
                snapshot.version
                if snapshot is not None
                else None
            ),
            revision_confirmation=next(
                (
                    proof
                    for proof in revision_confirmations
                    if proof.target is ExactRevisionTarget.BUDGET
                ),
                None,
            ),
        )
        if budget_plan is not None:
            yield from self._stream_budget_revision(
                turn,
                snapshot=snapshot,
                plan=budget_plan,
            )
            return
        yield from self._stream_planned_text_or_stale(
            turn,
            snapshot=snapshot,
        )

    def _stream_pending_reply_locked(
        self,
        turn: UserTurn,
        *,
        reply: PendingReply,
    ) -> Iterator[SseEvent]:
        snapshot = self._conversation_state.load(turn.session_id)
        if (
            snapshot is None
            or snapshot.pending_turn is None
            or turn.conversation_version != snapshot.version
        ):
            yield from self._stream_planned_text_or_stale(
                turn,
                snapshot=snapshot,
            )
            return
        if snapshot.profile_owner != turn.profile_owner:
            raise ConversationStateConflict(turn.session_id)
        yield from self._stream_pending_reply_or_replace(
            turn,
            snapshot=snapshot,
            reply=reply,
        )

    def _stream_pending_reply_or_replace(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot,
        reply: PendingReply,
    ) -> Iterator[SseEvent]:
        if reply.kind == "replace_task":
            assert reply.replacement_category is not None
            replacement_task = TaskPlan(
                mode="recommend",
                referenced_image_ids=[],
                constraints=[
                    CategoryConstraint(
                        value=TopicCode(
                            reply.replacement_category
                        )
                    )
                ],
                references=[],
                product_mentions=[],
                product_ids=[],
                required_evidence=["canonical_product"],
                question_meaning=turn.message,
            )
            yield StageEvent(
                data=StageData(
                    stage="understanding",
                    summary="已取消上一轮待确认任务并切换品类。",
                )
            )
            yield IntentEvent(
                data=IntentData(
                    mode="recommend",
                    category_profile=_task_category_profile(
                        replacement_task
                    ),
                )
            )
            yield from self._stream_recommendation(
                turn,
                snapshot=snapshot,
                task=replacement_task,
                revision_kind=None,
            )
            return
        yield from self._stream_pending_reply(
            turn,
            snapshot=snapshot,
            reply=reply,
        )

    def _stream_pending_reply(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot,
        reply,
    ) -> Iterator[SseEvent]:
        pending = snapshot.pending_turn
        assert pending is not None
        if reply.kind in {"affirm", "correct", "supplement"}:
            task = resume_pending_recommendation(
                pending=pending,
                reply=reply,
            )
            yield StageEvent(
                data=StageData(
                    stage="understanding",
                    summary="已确认上一轮预算并恢复原导购任务。",
                )
            )
            yield IntentEvent(
                data=IntentData(
                    mode="recommend",
                    category_profile=_task_category_profile(task),
                )
            )
            yield from self._stream_recommendation(
                turn,
                snapshot=snapshot,
                task=task,
                revision_kind=None,
            )
            return

        attempts = min(pending.attempts + 1, 2)
        if reply.kind == "reject":
            next_pending = pending.model_copy(
                update={
                    "attempts": attempts,
                    "expected_response": "supply_value",
                    "proposed_budget": None,
                },
                deep=True,
            )
            question = "请直接告诉我预算下限和上限，例如800到1000元。"
        else:
            next_pending = pending.model_copy(
                update={"attempts": attempts},
                deep=True,
            )
            question = (
                "请回答“是”或“不是”，也可以直接给出预算范围。"
                if pending.proposed_budget is not None
                else "请直接告诉我预算下限和上限。"
            )
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question=question,
                clarification_code=pending.gap,
                pending_turn=next_pending,
            )
        )
        yield EndEvent(
            data=EndData(conversation_version=snapshot.version)
        )

    def _stream_planned_text_or_stale(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        allow_unbound_references: bool = False,
        semantic_context: SemanticContext | None = None,
        understanding_override: StructuredUnderstanding | None = None,
        product_bindings_override: (
            tuple[ResolvedProductBinding, ...] | None
        ) = None,
        product_resolution_issue: ProductResolutionIssue | None = None,
        route_decision: UnifiedRouteDecision | None = None,
    ) -> Iterator[SseEvent]:
        if (
            snapshot is not None
            and turn.conversation_version != snapshot.version
        ):
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=(
                        "会话状态已变化，请基于最新结果重试。"
                    ),
                    clarification_code=ClarificationCode.REFERENCE,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=snapshot.version
                )
            )
            return

        yield from self._stream_planned_text(
            turn,
            snapshot=snapshot,
            allow_unbound_references=allow_unbound_references,
            semantic_context=semantic_context,
            understanding_override=understanding_override,
            product_bindings_override=product_bindings_override,
            product_resolution_issue=product_resolution_issue,
            route_decision=route_decision,
        )

    def _stream_planned_text(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        allow_unbound_references: bool = False,
        semantic_context: SemanticContext | None = None,
        understanding_override: StructuredUnderstanding | None = None,
        product_bindings_override: (
            tuple[ResolvedProductBinding, ...] | None
        ) = None,
        product_resolution_issue: ProductResolutionIssue | None = None,
        route_decision: UnifiedRouteDecision | None = None,
    ) -> Iterator[SseEvent]:
        profile_context = self._resolve_profile_context(turn)
        understanding = (
            understanding_override
            if understanding_override is not None
            else self._understanding.understand(
                turn.message,
                context=(
                    semantic_context
                    or resolve_semantic_context(
                        conversation_version=turn.conversation_version,
                        snapshot=snapshot,
                        profile_context=profile_context,
                    )
                ),
            )
        )
        understanding = merge_context_signals(
            understanding,
            signals=resolve_context_constraint_signals(
                snapshot=snapshot,
                profile_context=profile_context,
            ),
        )
        understanding = self._recover_explicit_product_mentions(
            turn.message,
            understanding,
        )
        yield StageEvent(
            data=StageData(
                stage="understanding",
                summary="已提取明确预算、品类和适配条件。",
            )
        )
        product_resolution = (
            ProductMentionResolution(
                bindings=product_bindings_override,
                issue=product_resolution_issue,
            )
            if product_bindings_override is not None
            else self._resolve_product_mentions_or_references(
                turn.message,
                understanding,
                snapshot=snapshot,
            )
        )
        if (
            product_bindings_override is None
            and allow_unbound_references
            and snapshot is None
            and not understanding.product_mentions
        ):
            product_resolution = ProductMentionResolution(
                bindings=(),
                issue=None,
            )
        if (
            route_decision is not None
            and route_decision.processor != "clarification"
        ):
            expected_route_modes = {
                "recommendation": {
                    "recommendation",
                    "image_similarity",
                },
                "comparison": {"comparison", "suitability"},
                "product_knowledge": {
                    "knowledge",
                    "followup",
                    "suitability",
                },
                "general_knowledge": {"knowledge", "followup"},
                "clarification": {"clarification"},
            }.get(route_decision.processor)
            if (
                expected_route_modes is not None
                and understanding.goal.value
                not in expected_route_modes
                and not (
                    route_decision.processor == "recommendation"
                    and understanding.goal.value == "followup"
                    and route_decision.continuity
                    in {"supplement", "correct", "withdraw"}
                )
                and not (
                    route_decision.processor == "clarification"
                    and product_resolution_issue is not None
                )
            ):
                raise ValueError(
                    "route processor and understanding goal disagree"
                )
        planning_understanding = understanding
        if (
            route_decision is not None
            and route_decision.processor == "comparison"
            and understanding.goal is UnderstandingGoal.SUITABILITY
            and 2 <= len(product_resolution.product_ids) <= 3
        ):
            planning_understanding = understanding.model_copy(
                update={"goal": UnderstandingGoal.COMPARISON},
                deep=True,
            )
        task = plan_task(
            planning_understanding,
            resolved_product_ids=product_resolution.product_ids,
            product_resolution_issue=product_resolution.issue,
            message=turn.message,
        )
        task = self._prepare_image_similarity_task(task)
        transition_planning = plan_code_owned_transitions(
            message=turn.message,
            understanding=planning_understanding,
            task=task,
            previous=(
                snapshot.query_context
                if snapshot is not None
                else None
            ),
            continuation_requested=(
                route_decision is not None
                and route_decision.continuity
                in {"supplement", "correct", "withdraw"}
            ),
        )
        task = transition_planning.task_plan
        if snapshot is not None and snapshot.session_profile is not None:
            task = apply_session_profile_to_task(
                task,
                snapshot.session_profile,
            )
        if (
            route_decision is not None
            and route_decision.processor == "clarification"
        ):
            pending_turn = (
                build_pending_turn(
                    message=turn.message,
                    source_conversation_version=(
                        turn.conversation_version
                    ),
                    task=task,
                )
                if task.mode == "clarify"
                else None
            )
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=(
                        route_decision.clarification
                        or (
                            task.clarification
                            if task.mode == "clarify"
                            else None
                        )
                        or "请明确这次要查看的商品或任务。"
                    ),
                    clarification_code=(
                        route_decision.clarification_code
                        or (
                            task.clarification_code
                            if task.mode == "clarify"
                            else None
                        )
                        or ClarificationCode.REFERENCE
                    ),
                    pending_turn=pending_turn,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=self._snapshot_version(
                        snapshot
                    )
                )
            )
            return
        revision_kind: RevisionKind | None = None
        if (
            route_decision is not None
            and route_decision.continuity == "correct"
            and transition_planning.transition_result is not None
        ):
            replaced_targets = {
                item.target
                for item in (
                    transition_planning.transition_result.transitions
                )
                if item.operation == "replace"
            }
            if replaced_targets == {"budget"}:
                revision_kind = "budget"
            elif replaced_targets == {"skin"}:
                revision_kind = "skin"
        if (
            revision_kind is None
            and snapshot is not None
            and snapshot.query_context is not None
            and route_decision is not None
            and route_decision.processor == "recommendation"
            and route_decision.continuity in {"supplement", "correct"}
            and task.similarity_anchor_product_id is None
        ):
            revision_kind = "context"
        yield IntentEvent(
            data=IntentData(
                mode=(
                    "image_recommend"
                    if task.similarity_anchor_product_id is not None
                    else (
                        "revise"
                        if revision_kind is not None
                        else task.mode
                    )
                ),
                category_profile=_task_category_profile(task),
            )
        )
        if task.mode == "clarify":
            assert task.clarification_code is not None
            pending_turn = build_pending_turn(
                message=turn.message,
                source_conversation_version=turn.conversation_version,
                task=task,
            )
            yield ClarifyEvent(
                data=ClarifyData(
                    question=task.clarification,
                    clarification_code=task.clarification_code,
                    pending_turn=pending_turn,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=self._snapshot_version(
                        snapshot
                    )
                )
            )
            return

        if task.mode == "comparison" and task.product_ids:
            yield from self._stream_direct_product_task(
                turn,
                snapshot=snapshot,
                task=task,
                product_resolution=product_resolution,
            )
            return
        if task.mode == "comparison":
            yield MessageEvent(
                data=MessageData(
                    content=(
                        "我知道你想比较商品，但还没有确认具体是哪几款。"
                        "请补充完整商品名。"
                    )
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=self._snapshot_version(
                        snapshot
                    )
                )
            )
            return
        if task.mode == "suitability" and task.product_ids:
            yield from self._stream_direct_product_task(
                turn,
                snapshot=snapshot,
                task=task,
                product_resolution=product_resolution,
            )
            return
        if task.mode == "suitability":
            yield from self._stream_recommendation(
                turn,
                snapshot=snapshot,
                task=task.model_copy(
                    update={"mode": "recommend"},
                    deep=True,
                ),
                revision_kind=None,
            )
            return
        if task.mode == "followup" and task.relative_requirements:
            baseline_product_id = _relative_baseline_product_id(
                snapshot,
                task.relative_requirements[0],
            )
            if (
                snapshot is None
                or snapshot.query_context is None
                or baseline_product_id is None
            ):
                yield ClarifyEvent(
                    data=ClarifyData(
                        question=(
                            "相对需求缺少可用的基准商品，"
                            "请先明确要和哪一款比较。"
                        ),
                        clarification_code=ClarificationCode.REFERENCE,
                    )
                )
                yield EndEvent(
                    data=EndData(
                        conversation_version=self._snapshot_version(
                            snapshot
                        )
                    )
                )
                return
            relative_task = task.model_copy(
                update={
                    "mode": "recommend",
                    "constraints": query_context_to_constraints(
                        snapshot.query_context
                    ),
                    "product_ids": [],
                    "required_evidence": ["canonical_product"],
                },
                deep=True,
            )
            yield from self._stream_recommendation(
                turn,
                snapshot=snapshot,
                task=relative_task,
                revision_kind=None,
                relative_baseline_product_id=baseline_product_id,
            )
            return
        if (
            task.mode in {"knowledge", "followup"}
            and task.product_ids
            and self._product_evidence is not None
        ):
            yield from self._stream_product_evidence_task(
                turn,
                snapshot=snapshot,
                task=task,
                product_resolution=product_resolution,
            )
            return
        if (
            self._general_knowledge is not None
            and (
                task.mode == "knowledge"
                or (
                    task.mode == "followup"
                    and snapshot is not None
                    and (
                        snapshot.last_general_knowledge_question
                        is not None
                    )
                )
            )
        ):
            yield from self._stream_general_knowledge_task(
                turn,
                snapshot=snapshot,
                task=task,
            )
            return
        if task.mode == "knowledge":
            yield MessageEvent(
                data=MessageData(
                    content=(
                        "当前资料还不足以回答这个知识问题，"
                        "这里先不凭商品信息猜测结论。"
                    )
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=self._snapshot_version(
                        snapshot
                    )
                )
            )
            return
        if task.mode == "followup":
            yield MessageEvent(
                data=MessageData(
                    content=(
                        "我知道你在继续问前面的商品，但还不确定你想看"
                        "价格、用法还是注意事项。可以再说具体一点。"
                    )
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=self._snapshot_version(
                        snapshot
                    )
                )
            )
            return

        yield from self._stream_recommendation(
            turn,
            snapshot=snapshot,
            task=task,
            revision_kind=revision_kind,
            suppressed_constraint_parents=frozenset(
                item.parent_concept
                for item in understanding.constraint_changes
                if (
                    item.requested_change == "remove"
                    and item.parent_concept in {"efficacy", "skin"}
                )
            ),
        )

    def _stream_general_knowledge_task(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
    ) -> Iterator[SseEvent]:
        assert self._general_knowledge is not None
        topic = next(
            (
                constraint.value
                for constraint in task.constraints
                if isinstance(constraint, CategoryConstraint)
            ),
            None,
        )
        query = GeneralKnowledgeQuery(
            raw_question=turn.message.strip(),
            question_meaning=(
                task.question_meaning or turn.message.strip()
            ),
            topic=topic,
            safety_sensitive=task.safety_sensitive,
            prior_knowledge_ids=(
                snapshot.focused_general_knowledge_ids
                if (
                    task.mode == "followup"
                    and snapshot is not None
                )
                else ()
            ),
            top_k=3,
        )
        packet = self._general_knowledge.retrieve(query)
        rendered = render_general_knowledge_answer(packet)
        presentation_event = self._presentation_event(
            mode="general_knowledge",
            user_need_summary=(
                task.question_meaning or turn.message.strip()
            ),
            winner_status="NOT_APPLICABLE",
            card_display=CardDisplayContract(
                mode="none",
                visible_product_ids=(),
                max_cards=0,
                reason=None,
            ),
            cards=(),
            copywriter_policy=(
                "medical_escalation"
                if rendered.data.medical_escalation
                else "eligible"
            ),
        )
        expected_version = self._snapshot_version(snapshot)
        knowledge_ids = tuple(
            sorted(
                hit.block.knowledge_id
                for hit in packet.hits
            )
        )
        values = {
            "version": expected_version + 1,
            "focused_general_knowledge_ids": knowledge_ids,
            "last_general_knowledge_question": turn.message.strip(),
            "clarification": None,
        }
        if snapshot is None:
            next_snapshot = ConversationSnapshot(
                session_id=turn.session_id,
                profile_owner=turn.profile_owner,
                **values,
            )
        else:
            next_snapshot = snapshot.model_copy(
                update=values,
                deep=True,
            )
        saved = self._conversation_state.save(
            next_snapshot,
            expected_version=expected_version,
        )
        yield StageEvent(
            data=StageData(
                stage="retrieval",
                summary="已检索审核过的通用知识资料。",
            )
        )
        yield GeneralKnowledgeEvent(data=rendered.data)
        yield presentation_event
        yield MessageEvent(data=MessageData(content=rendered.message))
        yield EndEvent(
            data=EndData(conversation_version=saved.version)
        )

    def _stream_product_evidence_task(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
        product_resolution: ProductMentionResolution,
    ) -> Iterator[SseEvent]:
        assert self._product_evidence is not None
        task = self._task_with_inferred_product_category(task)
        query = EvidenceQuery(
            product_ids=tuple(task.product_ids),
            raw_question=turn.message,
            question_meaning=(
                task.question_meaning or turn.message.strip()
            ),
            safety_sensitive=task.safety_sensitive,
            product_identity_names=self._product_identity_names(
                task.product_ids
            ),
            product_mention_spans=tuple(
                sorted(
                    (
                        mention.source_span.start,
                        mention.source_span.end,
                    )
                    for mention in task.product_mentions
                )
            ),
        )
        packet = self._product_evidence.retrieve(query)
        product_names: dict[int, str] = {}
        for product_id in task.product_ids:
            variant_scope = product_resolution.variant_scope_for(
                product_id
            )
            facts = (
                self._presentation_facts.get_presentation_facts(
                    product_id,
                    variant_scope=variant_scope,
                )
                if variant_scope is not None
                else self._presentation_facts.get_presentation_facts(
                    product_id
                )
            )
            product_names[product_id] = (
                facts.name or f"商品{product_id}"
            )
        message = render_product_evidence_answer(
            packet,
            product_names=product_names,
        )
        cards = self._cards_for_product_ids(
            task.product_ids,
            product_resolution=product_resolution,
        )
        if len(cards) == 1:
            card_display = single_product_card_display(cards[0])
            presentation_mode: PresentationMode = "product_knowledge"
        else:
            card_display = comparison_card_display(cards)
            presentation_mode = "comparison"
        merchant_claims = _project_merchant_claims(
            self._merchant_claims,
            product_ids=tuple(task.product_ids),
            constraints=task.constraints,
        )
        review_summaries = tuple(
            summary
            for product_id in task.product_ids
            if (
                summary := build_review_summary(
                    self._review_evidence.read(
                        product_id=product_id
                    )
                )
            ) is not None
        )
        product_evidence_event = ProductEvidenceEvent(
            data=ProductEvidenceData(packet=packet)
        )
        presentation_event = self._presentation_event(
            mode=presentation_mode,
            user_need_summary=(
                task.question_meaning or turn.message.strip()
            ),
            winner_status="NOT_APPLICABLE",
            card_display=card_display,
            cards=cards,
            merchant_claims=merchant_claims,
            review_summaries=review_summaries,
            proof_points=_presentation_proof_points(
                product_evidence_event
            ),
        )
        expected_version = self._snapshot_version(snapshot)
        saved = self._conversation_state.save(
            self._product_evidence_snapshot(
                turn,
                snapshot=snapshot,
                task=task,
                product_ids=tuple(task.product_ids),
                evidence_ids=tuple(
                    item.evidence.evidence_id
                    for item in packet.selected
                ),
                version=expected_version + 1,
            ),
            expected_version=expected_version,
        )
        yield StageEvent(
            data=StageData(
                stage="retrieval",
                summary="已在当前商品的审核证据中检索相关资料。",
            )
        )
        yield AnswerContractEvent(
            data=AnswerContractData(
                product_count=len(cards),
                winner_status="NOT_APPLICABLE",
                has_unknown_skin=True,
            )
        )
        yield CardDisplayContractEvent(data=card_display)
        yield ProductsEvent(data=ProductsData(cards=cards))
        yield product_evidence_event
        yield presentation_event
        yield MessageEvent(data=MessageData(content=message))
        yield EndEvent(
            data=EndData(
                conversation_version=saved.version
            )
        )

    @staticmethod
    def _product_evidence_snapshot(
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
        product_ids: tuple[int, ...],
        evidence_ids: tuple[str, ...],
        version: int,
    ) -> ConversationSnapshot:
        preserve_recommendation_batch = (
            snapshot is not None
            and snapshot.query_context is not None
            and bool(snapshot.candidates)
            and set(product_ids).issubset(
                {
                    item.product_id
                    for item in snapshot.candidates
                }
            )
        )
        snapshot_task = task.model_copy(
            update={"mode": "recommend"},
            deep=True,
        )
        if preserve_recommendation_batch:
            assert snapshot is not None
            assert snapshot.query_context is not None
            query_context = snapshot.query_context
            candidates = snapshot.candidates
            focused_ordinal = next(
                (
                    item.ordinal
                    for item in candidates
                    if (
                        len(product_ids) == 1
                        and item.product_id == product_ids[0]
                    )
                ),
                snapshot.focused_candidate_ordinal,
            )
        else:
            candidates = tuple(
                DisplayedCandidateRef(
                    product_id=product_id,
                    ordinal=ordinal,
                    skin_match="unknown",
                    matched_efficacies=(),
                )
                for ordinal, product_id in enumerate(
                    product_ids,
                    start=1,
                )
            )
            focused_ordinal = 1 if len(candidates) == 1 else None
            try:
                query_context = task_plan_to_query_context(snapshot_task)
            except ValueError:
                if snapshot is None or snapshot.query_context is None:
                    raise
                query_context = snapshot.query_context
        values = {
            "version": version,
            "query_context": query_context,
            "candidates": candidates,
            "focused_candidate_ordinal": focused_ordinal,
            "focused_evidence_ids": evidence_ids,
            "focused_general_knowledge_ids": (),
            "last_general_knowledge_question": None,
        }
        if snapshot is None:
            return ConversationSnapshot(
                session_id=turn.session_id,
                profile_owner=turn.profile_owner,
                **values,
            )
        return snapshot.model_copy(update=values, deep=True)

    def _build_post_decision_evidence_event(
        self,
        turn: UserTurn,
        *,
        task: TaskPlan,
        product_ids: tuple[int, ...],
    ) -> ProductEvidenceEvent | None:
        if self._product_evidence is None or not product_ids:
            return None
        packet = self._product_evidence.retrieve(
            EvidenceQuery(
                product_ids=product_ids,
                raw_question=turn.message,
                question_meaning=(
                    task.question_meaning or turn.message.strip()
                ),
                safety_sensitive=task.safety_sensitive,
                product_identity_names=self._product_identity_names(
                    product_ids
                ),
                product_mention_spans=tuple(
                    sorted(
                        (
                            mention.source_span.start,
                            mention.source_span.end,
                        )
                        for mention in task.product_mentions
                    )
                ),
            )
        )
        return ProductEvidenceEvent(
            data=ProductEvidenceData(packet=packet)
        )

    def _product_identity_names(
        self,
        product_ids: Sequence[int],
    ) -> tuple[str, ...]:
        if self._product_name_resolver is None:
            return ()
        return self._product_name_resolver.product_names(product_ids)

    def _resolve_product_mentions(
        self,
        message: str,
        mentions: Sequence[ProductMentionDraft],
    ) -> ProductMentionResolution:
        if not mentions:
            return ProductMentionResolution(bindings=(), issue=None)
        if self._product_name_resolver is None:
            return ProductMentionResolution(
                bindings=(),
                issue="missing_reference",
            )
        semantic_mentions = tuple(
            SemanticProductMention(
                text=mention.text,
                start=mention.source_span.start,
                end=mention.source_span.end,
            )
            for mention in mentions
        )
        return self._product_name_resolver.resolve(
            message=message,
            mentions=semantic_mentions,
        )

    def _resolve_product_mentions_or_references(
        self,
        message: str,
        understanding: StructuredUnderstanding,
        *,
        snapshot: ConversationSnapshot | None,
    ) -> ProductMentionResolution:
        mention_resolution = self._resolve_product_mentions(
            message,
            understanding.product_mentions,
        )
        reference_resolution = self._resolve_reference_products(
            understanding.references,
            snapshot=snapshot,
        )
        if not understanding.product_mentions:
            return reference_resolution
        if (
            mention_resolution.issue is not None
            and reference_resolution.bindings
        ):
            return reference_resolution
        return mention_resolution

    def _recover_explicit_product_mentions(
        self,
        message: str,
        understanding: StructuredUnderstanding,
    ) -> StructuredUnderstanding:
        if (
            understanding.product_mentions
            or self._product_name_resolver is None
        ):
            return understanding
        recovered = self._product_name_resolver.find_explicit_mentions(
            message
        )
        if not recovered:
            return understanding
        return understanding.model_copy(
            update={
                "product_mentions": [
                    ProductMentionDraft(
                        text=mention.text,
                        source_span=SourceSpan(
                            start=mention.start,
                            end=mention.end,
                        ),
                    )
                    for mention in recovered
                ],
            },
            deep=True,
        )

    @staticmethod
    def _resolve_reference_products(
        references: Sequence[ReferenceDraft],
        *,
        snapshot: ConversationSnapshot | None,
    ) -> ProductMentionResolution:
        product_references = [
            reference
            for reference in references
            if reference.kind
            in {
                "current_item",
                "current_batch",
                "candidate_ordinal",
            }
        ]
        if not product_references:
            return ProductMentionResolution(
                bindings=(),
                issue=None,
            )
        if snapshot is None or not snapshot.candidates:
            return ProductMentionResolution(
                bindings=(),
                issue="missing_reference",
            )
        candidate_by_ordinal = {
            candidate.ordinal: candidate.product_id
            for candidate in snapshot.candidates
        }
        focused_ordinal = snapshot.focused_candidate_ordinal
        if (
            focused_ordinal is None
            and snapshot.focus_state is not None
            and snapshot.focus_state.current_product_id is not None
        ):
            focused_ordinals = [
                candidate.ordinal
                for candidate in snapshot.candidates
                if (
                    candidate.product_id
                    == snapshot.focus_state.current_product_id
                )
            ]
            if len(focused_ordinals) == 1:
                focused_ordinal = focused_ordinals[0]
        batch_bindings: list[ResolvedProductBinding] = []
        specific_bindings: list[ResolvedProductBinding] = []
        for reference in product_references:
            if reference.kind == "current_batch":
                batch_bindings.extend(
                    ResolvedProductBinding(
                        product_id=candidate.product_id,
                        source_text="current_batch",
                    )
                    for candidate in snapshot.candidates
                )
                continue
            ordinal = (
                (
                    focused_ordinal
                    or (
                        snapshot.candidates[0].ordinal
                        if len(snapshot.candidates) == 1
                        else None
                    )
                )
                if reference.kind == "current_item"
                else reference.ordinal
            )
            if ordinal is None or ordinal not in candidate_by_ordinal:
                return ProductMentionResolution(
                    bindings=(),
                    issue="missing_reference",
                )
            specific_bindings.append(
                ResolvedProductBinding(
                    product_id=candidate_by_ordinal[ordinal],
                    source_text=(
                        f"{reference.kind}:{ordinal}"
                    ),
                )
            )
        return ProductMentionResolution(
            bindings=merge_batch_and_specific_bindings(
                batch_bindings,
                specific_bindings,
            )
        )

    def _task_with_inferred_product_category(
        self,
        task: TaskPlan,
    ) -> TaskPlan:
        if any(
            isinstance(item, CategoryConstraint)
            for item in task.constraints
        ):
            return task
        records = {
            record.product_id: record
            for record in self._category_catalog.iter_category_records()
        }
        product_ids = (
            task.product_ids
            if task.product_ids
            else (
                [task.similarity_anchor_product_id]
                if task.similarity_anchor_product_id is not None
                else []
            )
        )
        canonical_categories = {
            records[product_id].value
            for product_id in product_ids
            if (
                product_id in records
                and records[product_id].state == "known"
                and records[product_id].value
            )
        }
        matching_topics = tuple(
            topic
            for topic in TopicCode
            if (
                canonical_categories
                and canonical_categories
                <= canonical_categories_for(topic)
            )
        )
        if not matching_topics:
            raise ValueError(
                "bound product category cannot be resolved"
            )
        inferred_topic = min(
            matching_topics,
            key=lambda topic: (
                len(canonical_categories_for(topic)),
                topic.value,
            ),
        )
        return task.model_copy(
            update={
                "constraints": [
                    *task.constraints,
                    CategoryConstraint(value=inferred_topic),
                ]
            },
            deep=True,
        )

    def _prepare_image_similarity_task(
        self,
        task: TaskPlan,
    ) -> TaskPlan:
        anchor_product_id = task.similarity_anchor_product_id
        if anchor_product_id is None:
            return task
        task = self._task_with_inferred_product_category(task)
        if self._concept_reader is None:
            return task

        anchor = self._decision_facts.get_decision_facts(
            anchor_product_id
        )
        if anchor.product_id != anchor_product_id:
            raise ValueError(
                "similarity anchor decision facts product mismatch"
            )
        source_facts = tuple(
            fact
            for fact in anchor.selection_facts
            if not (
                task.safety_sensitive
                and fact.safety_role
                == "merchant_positive_safety"
            )
        )
        projected = sorted(
            self._concept_reader.project(source_facts),
            key=lambda item: (
                -item.rank_strength,
                item.field_key,
                item.concept_id,
            ),
        )
        existing_concepts = {
            (constraint.field_key, constraint.concept_id)
            for constraint in task.constraints
            if isinstance(constraint, ConceptConstraint)
        }
        concept_count = len(existing_concepts)
        similarity_concepts: list[ConceptConstraint] = []
        for fact in projected:
            key = (fact.field_key, fact.concept_id)
            if key in existing_concepts or concept_count >= 16:
                continue
            similarity_concepts.append(
                ConceptConstraint(
                    field_key=fact.field_key,
                    concept_id=fact.concept_id,
                    polarity=(
                        "prefer"
                        if fact.stance == "supports"
                        else "avoid"
                    ),
                )
            )
            existing_concepts.add(key)
            concept_count += 1
        if not similarity_concepts:
            return task
        return task.model_copy(
            update={
                "constraints": [
                    *task.constraints,
                    *similarity_concepts,
                ]
            },
            deep=True,
        )

    def _stream_direct_product_task(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
        product_resolution: ProductMentionResolution,
    ) -> Iterator[SseEvent]:
        task = self._task_with_inferred_product_category(task)
        records = {
            record.product_id: record
            for record in self._category_catalog.iter_category_records()
        }
        retrieval = RetrievalResult(
            candidates=[
                CandidateRef(
                    product_id=product_id,
                    source="canonical_product_name",
                    canonical_category=(
                        records[product_id].value or ""
                    ),
                    canonical_category_state=records[product_id].state,
                    retrieval_reason="exact_product_name",
                )
                for product_id in task.product_ids
            ],
            knowledge_evidence=[],
            review_evidence=[],
            memory_evidence=[],
            missing_sources=[],
        )
        decision_constraints = list(task.constraints)
        eligibility_constraints = (
            [_category_constraint(decision_constraints)]
            if task.mode == "comparison"
            else decision_constraints
        )
        decision = decide_recommendation(
            self._decision_facts,
            retrieval,
            constraints=eligibility_constraints,
            safety_sensitive=task.safety_sensitive,
            concept_reader=self._concept_reader,
        )
        if task.mode == "comparison":
            eligible = set(decision.ordered_product_ids)
            decision = decision.model_copy(
                update={
                    "ordered_product_ids": [
                        product_id
                        for product_id in task.product_ids
                        if product_id in eligible
                    ],
                },
                deep=True,
            )
        if (
            task.mode == "suitability"
            and not decision.ordered_product_ids
        ):
            identity_decision = decide_recommendation(
                self._decision_facts,
                retrieval,
                constraints=[
                    _category_constraint(decision_constraints),
                ],
                safety_sensitive=task.safety_sensitive,
                concept_reader=self._concept_reader,
            )
            decision = identity_decision.model_copy(
                update={
                    "winner_status": (
                        WinnerStatus.INSUFFICIENT_FOR_WINNER
                    ),
                    "winner_product_id": None,
                    "risk_findings": decision.risk_findings,
                    "evidence_refs": list(
                        dict.fromkeys(
                            [
                                *decision.evidence_refs,
                                *identity_decision.evidence_refs,
                            ]
                        )
                    ),
                },
                deep=True,
            )
        response = self._build_plan(
            decision,
            product_resolution=product_resolution,
        )
        cards = list(response.structured_events)
        if task.mode == "comparison":
            card_display = comparison_card_display(cards)
            message = (
                "下面只比较这几款现有资料能够确认的差异；"
                "资料没有覆盖的部分不会被当作优势或适配结论。"
            )
        else:
            if len(cards) != 1:
                raise ValueError(
                    "direct suitability requires exactly one card"
                )
            card_display = single_product_card_display(cards[0])
            message = (
                "现有资料还不足以判断它一定适合你现在的状态；"
                "没有覆盖的肤质或功效信息不会被当作适合结论。"
            )
        product_evidence_event = (
            self._build_post_decision_evidence_event(
                turn,
                task=task,
                product_ids=tuple(
                    card.product_id for card in cards
                ),
            )
        )
        product_ids = tuple(card.product_id for card in cards)
        selection_slots = _selection_slot_data(
            self._decision_facts,
            product_ids=product_ids,
            constraints=task.constraints,
            safety_sensitive=task.safety_sensitive,
        )
        concept_slots = _concept_slot_data(
            self._decision_facts,
            reader=self._concept_reader,
            product_ids=product_ids,
            constraints=task.constraints,
            safety_sensitive=task.safety_sensitive,
        )
        merchant_claims = _project_merchant_claims(
            self._merchant_claims,
            product_ids=product_ids,
            constraints=task.constraints,
        )
        review_summaries = tuple(
            summary
            for product_id in product_ids
            if (
                summary := build_review_summary(
                    self._review_evidence.read(
                        product_id=product_id
                    )
                )
            ) is not None
        )
        presentation_event = self._presentation_event(
            mode=(
                "comparison"
                if task.mode == "comparison"
                else "single_product"
            ),
            user_need_summary=(
                task.question_meaning or turn.message.strip()
            ),
            winner_status=decision.winner_status.value,
            card_display=card_display,
            cards=cards,
            selection_slots=selection_slots,
            concept_slots=concept_slots,
            merchant_claims=merchant_claims,
            review_summaries=review_summaries,
            proof_points=_presentation_proof_points(
                product_evidence_event
            ),
        )
        message = _presentation_compatibility_message(
            presentation_event,
            default=message,
        )

        status = self._feedback.record_turn(turn)
        if status is not FeedbackWriteStatus.SKIPPED_SLICE_SCOPE:
            raise RuntimeError("unexpected feedback write status")
        expected_version = self._snapshot_version(snapshot)
        snapshot_task = task.model_copy(
            update={
                "mode": "recommend",
                "constraints": decision_constraints,
            },
            deep=True,
        )
        next_snapshot = (
            self._product_evidence_snapshot(
                turn,
                snapshot=snapshot,
                task=task,
                product_ids=product_ids,
                evidence_ids=(
                    tuple(
                        item.evidence.evidence_id
                        for item in (
                            product_evidence_event.data.packet.selected
                        )
                    )
                    if product_evidence_event is not None
                    else ()
                ),
                version=expected_version + 1,
            )
            if task.mode == "suitability"
            else self._visible_snapshot(
                turn,
                cards,
                snapshot=snapshot,
                task=snapshot_task,
                version=expected_version + 1,
            )
        )
        saved = self._conversation_state.save(
            next_snapshot,
            expected_version=expected_version,
        )
        yield StageEvent(
            data=StageData(
                stage="retrieval",
                summary="已按商品名称绑定 Canonical 目录。",
            )
        )
        yield StageEvent(
            data=StageData(
                stage="decision",
                summary="已执行同一套事实状态和硬约束判断。",
            )
        )
        yield DecisionProcessEvent(
            data=DecisionProcessData(
                ordered_product_ids=list(decision.ordered_product_ids),
                winner_status=decision.winner_status.value,
                evidence_refs=list(decision.evidence_refs),
                selection_slots=selection_slots,
                concept_slots=concept_slots,
                relative_comparisons=list(
                    decision.relative_comparisons
                ),
            )
        )
        yield AnswerContractEvent(
            data=AnswerContractData(
                product_count=len(cards),
                winner_status=decision.winner_status.value,
                has_unknown_skin=any(
                    card.skin_match == "unknown"
                    for card in cards
                ),
            )
        )
        yield CardDisplayContractEvent(data=card_display)
        yield ProductsEvent(data=ProductsData(cards=cards))
        if product_evidence_event is not None:
            yield product_evidence_event
        yield presentation_event
        yield MessageEvent(data=MessageData(content=message))
        yield EndEvent(
            data=EndData(conversation_version=saved.version)
        )

    def _resolve_profile_context(
        self,
        turn: UserTurn,
    ) -> ResolvedProfileContext | None:
        if self._profile_resolver is None or turn.profile_owner is None:
            return None
        return self._profile_resolver(
            session_id=turn.session_id,
            profile_owner=turn.profile_owner,
        )

    def _stream_recommendation(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
        revision_kind: RevisionKind | None,
        relative_baseline_product_id: int | None = None,
        suppressed_constraint_parents: frozenset[str] = frozenset(),
    ) -> Iterator[SseEvent]:
        scenario_inputs = build_scenario_inputs(
            task,
            message=turn.message,
            suppressed_constraint_parents=suppressed_constraint_parents,
        )
        effective_task = task.model_copy(
            update={
                "constraints": scenario_inputs.decision.constraints,
            },
            deep=True,
        )
        category = _category_constraint(effective_task.constraints)
        retrieval = retrieve_candidates(
            self._category_catalog,
            category=category.value,
        )
        if effective_task.similarity_anchor_product_id is not None:
            retrieval = retrieval.model_copy(
                update={
                    "candidates": [
                        candidate
                        for candidate in retrieval.candidates
                        if candidate.product_id
                        != effective_task.similarity_anchor_product_id
                    ]
                },
                deep=True,
            )
        decision = decide_recommendation(
            self._decision_facts,
            retrieval,
            constraints=effective_task.constraints,
            safety_sensitive=effective_task.safety_sensitive,
            concept_reader=self._concept_reader,
            relative_requirement=(
                effective_task.relative_requirements[0]
                if effective_task.relative_requirements
                else None
            ),
            baseline_product_id=relative_baseline_product_id,
        )
        visible_limit = requested_recommendation_result_count(
            None,
            message=turn.message,
        )
        visible_decision = decision.model_copy(
            update={
                "ordered_product_ids": (
                    decision.ordered_product_ids[:visible_limit]
                ),
                "relative_comparisons": [
                    item
                    for item in decision.relative_comparisons
                    if item.candidate_product_id
                    in decision.ordered_product_ids[:visible_limit]
                ],
            },
            deep=True,
        )
        response = self._build_plan(visible_decision)
        cards = list(response.structured_events)
        card_display = recommendation_card_display(cards)
        concept_slots = _concept_slot_data(
            self._decision_facts,
            reader=self._concept_reader,
            product_ids=tuple(
                visible_decision.ordered_product_ids
            ),
            constraints=effective_task.constraints,
            safety_sensitive=effective_task.safety_sensitive,
        )
        if revision_kind == "budget":
            message = build_budget_revision_message(
                effective_task,
                visible_decision,
            )
        elif revision_kind == "skin":
            message = build_skin_revision_message(
                effective_task,
                visible_decision,
            )
        else:
            message = _summary_fragment(visible_decision)
        message = _append_concept_rank_reason(
            message,
            cards=cards,
            concept_slots=concept_slots,
        )
        message = _append_relative_rank_reason(
            message,
            cards=cards,
            comparisons=visible_decision.relative_comparisons,
            requirement=(
                effective_task.relative_requirements[0]
                if effective_task.relative_requirements
                else None
            ),
        )
        merchant_claims = _project_merchant_claims(
            self._merchant_claims,
            product_ids=visible_decision.ordered_product_ids,
            constraints=effective_task.constraints,
        )
        review_results = [
            self._review_evidence.read(product_id=product_id)
            for product_id in visible_decision.ordered_product_ids
        ]
        review_summaries = [
            summary
            for result in review_results
            if (
                summary := build_review_summary(result)
            ) is not None
        ]
        has_review_evidence = any(
            result.evidence for result in review_results
        )
        product_evidence_event = (
            self._build_post_decision_evidence_event(
                turn,
                task=effective_task,
                product_ids=tuple(
                    card.product_id for card in cards
                ),
            )
        )
        status = self._feedback.record_turn(turn)
        if status is not FeedbackWriteStatus.SKIPPED_SLICE_SCOPE:
            raise RuntimeError("unexpected feedback write status")
        expected_version = self._snapshot_version(snapshot)
        response_version = expected_version

        has_unknown_skin = any(
            item.kind == "skin_match_unknown"
            for item in visible_decision.risk_findings
        )
        selection_slots = _selection_slot_data(
            self._decision_facts,
            product_ids=tuple(
                visible_decision.ordered_product_ids
            ),
            constraints=effective_task.constraints,
            safety_sensitive=effective_task.safety_sensitive,
        )
        scenario_records = []
        pitfalls: list[TypedPitfall] = []
        success_events: list[SseEvent] = [
            StageEvent(
                data=StageData(
                    stage="retrieval",
                    summary="正在读取已审核的 Canonical 商品事实。",
                )
            ),
            StageEvent(
                data=StageData(
                    stage="decision",
                    summary="正在执行预算、排除项和肤质证据规则。",
                )
            ),
        ]
        if (
            scenario_inputs.decision.evidence_requirements
            and cards
        ):
            scenario_records = [
                record
                for product_id in visible_decision.ordered_product_ids
                for record in self._scenario_evidence.get_scenario_evidence(
                    product_id,
                    scenario_inputs.decision.evidence_requirements,
                )
            ]
        if scenario_records:
            success_events.extend(
                [
                    ScenarioEvidenceEvent(
                        data=ScenarioEvidenceData(
                            records=scenario_records,
                        )
                    ),
                ]
            )
        if merchant_claims:
            success_events.append(
                MerchantClaimsEvent(
                    data=MerchantClaimsData(claims=merchant_claims)
                )
            )
        if (
            review_results
            and (
                scenario_records
                or has_review_evidence
            )
        ):
            success_events.append(
                ReviewEvidenceEvent(
                    data=ReviewEvidenceData(
                        approved_source_count=(
                            self._review_evidence.approved_source_count
                        ),
                        results=review_results,
                        summaries=review_summaries,
                    )
                )
            )
        if scenario_records:
            pitfalls = project_scenario_pitfalls(scenario_records)
            success_events.append(
                PitfallsEvent(
                    data=PitfallsData(pitfalls=pitfalls)
                )
            )
        success_events.extend(
            [
                DecisionProcessEvent(
                    data=DecisionProcessData(
                        ordered_product_ids=list(
                            visible_decision.ordered_product_ids
                        ),
                        winner_status=(
                            visible_decision.winner_status.value
                        ),
                        evidence_refs=list(
                            visible_decision.evidence_refs
                        ),
                        selection_slots=selection_slots,
                        concept_slots=concept_slots,
                        relative_comparisons=list(
                            visible_decision.relative_comparisons
                        ),
                    )
                ),
                AnswerContractEvent(
                    data=AnswerContractData(
                        product_count=len(cards),
                        winner_status=(
                            visible_decision.winner_status.value
                        ),
                        has_unknown_skin=has_unknown_skin,
                    )
                ),
                CardDisplayContractEvent(data=card_display),
                ProductsEvent(data=ProductsData(cards=cards)),
            ]
        )
        if product_evidence_event is not None:
            success_events.append(product_evidence_event)
        presentation_event = self._presentation_event(
            mode=(
                "image_recommendation"
                if effective_task.similarity_anchor_product_id is not None
                else (
                    "revision"
                    if revision_kind is not None
                    else (
                        "followup"
                        if relative_baseline_product_id is not None
                        else "recommendation"
                    )
                )
            ),
            user_need_summary=(
                effective_task.question_meaning
                or turn.message.strip()
            ),
            winner_status=visible_decision.winner_status.value,
            card_display=card_display,
            cards=cards,
            selection_slots=selection_slots,
            concept_slots=concept_slots,
            merchant_claims=merchant_claims,
            review_summaries=review_summaries,
            pitfalls=pitfalls,
            proof_points=_presentation_proof_points(
                product_evidence_event
            ),
        )
        success_events.append(presentation_event)
        message = _presentation_compatibility_message(
            presentation_event,
            default=message,
        )
        success_events.append(
            MessageEvent(data=MessageData(content=message))
        )
        if cards or revision_kind is None:
            saved_snapshot = self._conversation_state.save(
                self._visible_snapshot(
                    turn,
                    cards,
                    snapshot=snapshot,
                    task=effective_task,
                    version=expected_version + 1,
                ),
                expected_version=expected_version,
            )
            response_version = saved_snapshot.version
        success_events.append(
            EndEvent(
                data=EndData(conversation_version=response_version)
            )
        )
        yield from success_events

    def _stream_budget_revision(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        plan: BudgetRevisionPlan,
    ) -> Iterator[SseEvent]:
        authoritative_version = self._snapshot_version(snapshot)
        if plan.mode == "clarify":
            assert plan.clarification is not None
            assert plan.clarification_code is not None
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=plan.clarification,
                    clarification_code=plan.clarification_code,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=authoritative_version
                )
            )
            return

        assert snapshot is not None
        task = TaskPlan(
            mode="recommend",
            referenced_image_ids=[],
            constraints=[
                item.model_copy(deep=True)
                for item in plan.constraints
            ],
            required_evidence=["canonical_product"],
            clarification=None,
        )
        yield StageEvent(
            data=StageData(
                stage="state",
                summary=(
                    "已读取最近一次成功筛选的结构化条件。"
                ),
            )
        )
        yield IntentEvent(data=IntentData(mode="revise"))
        yield from self._stream_recommendation(
            turn,
            snapshot=snapshot,
            task=task,
            revision_kind="budget",
        )

    def _stream_skin_revision(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        plan: SkinRevisionPlan,
    ) -> Iterator[SseEvent]:
        authoritative_version = self._snapshot_version(snapshot)
        if plan.mode == "clarify":
            assert plan.clarification is not None
            assert plan.clarification_code is not None
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=plan.clarification,
                    clarification_code=plan.clarification_code,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=authoritative_version
                )
            )
            return

        assert snapshot is not None
        task = TaskPlan(
            mode="recommend",
            referenced_image_ids=[],
            constraints=[
                item.model_copy(deep=True)
                for item in plan.constraints
            ],
            required_evidence=["canonical_product"],
            clarification=None,
        )
        yield StageEvent(
            data=StageData(
                stage="state",
                summary=(
                    "已读取最近一次成功筛选的结构化条件。"
                ),
            )
        )
        yield IntentEvent(data=IntentData(mode="revise"))
        yield from self._stream_recommendation(
            turn,
            snapshot=snapshot,
            task=task,
            revision_kind="skin",
        )

    def _stream_followup(
        self,
        turn: UserTurn,
        *,
        snapshot: ConversationSnapshot | None,
        plan: FollowupPlan,
    ) -> Iterator[SseEvent]:
        authoritative_version = self._snapshot_version(snapshot)
        if plan.mode == "clarify":
            assert plan.clarification is not None
            assert plan.clarification_code is not None
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=plan.clarification,
                    clarification_code=plan.clarification_code,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=authoritative_version
                )
            )
            return

        assert snapshot is not None
        result = decide_followup(
            self._decision_facts,
            snapshot,
            plan,
        )
        if result.status == "insufficient_evidence":
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=(
                        "这几款暂时缺少可直接比较的价格，"
                        "先不勉强判断哪款更便宜。"
                    ),
                    clarification_code=ClarificationCode.CONCERN,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=authoritative_version
                )
            )
            return

        facts = {
            product_id: self._presentation_facts.get_presentation_facts(
                product_id
            )
            for product_id in result.selected_product_ids
        }
        cards = build_followup_cards(
            result,
            snapshot=snapshot,
            product_facts=facts,
        )
        message = build_followup_message(
            result,
            product_facts=facts,
        )
        card_display = recommendation_card_display(cards)
        constraints = query_context_to_constraints(
            snapshot.query_context
        )
        selection_slots = _selection_slot_data(
            self._decision_facts,
            product_ids=tuple(result.selected_product_ids),
            constraints=constraints,
            safety_sensitive=snapshot.query_context.safety_sensitive,
        )
        concept_slots = _concept_slot_data(
            self._decision_facts,
            reader=self._concept_reader,
            product_ids=tuple(result.selected_product_ids),
            constraints=constraints,
            safety_sensitive=snapshot.query_context.safety_sensitive,
        )
        merchant_claims = _project_merchant_claims(
            self._merchant_claims,
            product_ids=tuple(result.selected_product_ids),
            constraints=constraints,
        )
        presentation_event = self._presentation_event(
            mode="followup",
            user_need_summary=turn.message.strip(),
            winner_status=result.status.upper(),
            card_display=card_display,
            cards=cards,
            selection_slots=selection_slots,
            concept_slots=concept_slots,
            merchant_claims=merchant_claims,
        )
        message = _presentation_compatibility_message(
            presentation_event,
            default=message,
        )
        status = self._feedback.record_turn(turn)
        if status is not FeedbackWriteStatus.SKIPPED_SLICE_SCOPE:
            raise RuntimeError("unexpected feedback write status")
        next_snapshot = snapshot.model_copy(
            update={
                "version": snapshot.version + 1,
                "focused_candidate_ordinal": (
                    result.ordinal
                    if result.ordinal is not None
                    else snapshot.focused_candidate_ordinal
                ),
                "focused_general_knowledge_ids": (),
                "last_general_knowledge_question": None,
            },
            deep=True,
        )
        success_events: list[SseEvent] = [
            StageEvent(
                data=StageData(
                    stage="state",
                    summary="已经找到你前面提到的商品。",
                )
            ),
            IntentEvent(data=IntentData(mode="followup")),
            DecisionProcessEvent(
                data=DecisionProcessData(
                    ordered_product_ids=list(
                        result.selected_product_ids
                    ),
                    winner_status=result.status.upper(),
                    evidence_refs=list(result.evidence_refs),
                    selection_slots=selection_slots,
                    concept_slots=concept_slots,
                    relative_comparisons=[],
                )
            ),
            AnswerContractEvent(
                data=AnswerContractData(
                    product_count=len(cards),
                    winner_status=result.status.upper(),
                    has_unknown_skin=any(
                        card.skin_match == "unknown"
                        for card in cards
                    ),
                )
            ),
            CardDisplayContractEvent(data=card_display),
            ProductsEvent(data=ProductsData(cards=cards)),
            presentation_event,
            MessageEvent(data=MessageData(content=message)),
        ]
        saved = self._conversation_state.save(
            next_snapshot,
            expected_version=snapshot.version,
        )
        success_events.append(
            EndEvent(
                data=EndData(conversation_version=saved.version)
            )
        )
        yield from success_events

    @staticmethod
    def _snapshot_version(
        snapshot: ConversationSnapshot | None,
    ) -> int:
        return snapshot.version if snapshot is not None else 0

    @staticmethod
    def _visible_snapshot(
        turn: UserTurn,
        cards: list[ProductCard],
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
        version: int,
    ) -> ConversationSnapshot:
        query_context = task_plan_to_query_context(task)
        candidate_limit = 4 if task.product_ids else 3
        candidates = tuple(
            DisplayedCandidateRef(
                product_id=card.product_id,
                ordinal=index,
                skin_match=card.skin_match,
                matched_efficacies=list(
                    card.matched_efficacies
                ),
            )
            for index, card in enumerate(
                cards[:candidate_limit],
                start=1,
            )
        )
        if snapshot is None:
            return ConversationSnapshot(
                session_id=turn.session_id,
                version=version,
                profile_owner=turn.profile_owner,
                query_context=query_context,
                empty_result=not candidates,
                candidates=candidates,
            )
        return snapshot.model_copy(
            update={
                "version": version,
                "query_context": query_context,
                "empty_result": not candidates,
                "candidates": candidates,
                "focused_candidate_ordinal": None,
                "focused_general_knowledge_ids": (),
                "last_general_knowledge_question": None,
            },
            deep=True,
        )

    def _build_plan(
        self,
        decision: DecisionResult,
        *,
        product_resolution: ProductMentionResolution | None = None,
    ) -> ResponsePlan:
        product_facts: dict[int, ProductCardFacts] = {}
        for product_id in decision.ordered_product_ids:
            variant_scope = (
                product_resolution.variant_scope_for(product_id)
                if product_resolution is not None
                else None
            )
            product_facts[product_id] = (
                self._presentation_facts.get_presentation_facts(
                    product_id,
                    variant_scope=variant_scope,
                )
                if variant_scope is not None
                else self._presentation_facts.get_presentation_facts(
                    product_id
                )
            )
        return build_response_plan(
            decision,
            product_facts=product_facts,
        )

    def _presentation_event(
        self,
        *,
        mode: PresentationMode,
        user_need_summary: str,
        winner_status: str | None,
        card_display: CardDisplayContract,
        cards: Sequence[ProductCard],
        selection_slots: Sequence[SelectionSlotData] = (),
        concept_slots: Sequence[ConceptSlotData] = (),
        merchant_claims: Sequence[
            MerchantClaimEvidenceData
        ] = (),
        review_summaries: Sequence[ReviewSummaryResult] = (),
        pitfalls: Sequence[TypedPitfall] = (),
        proof_points: Sequence[LockedFact] = (),
        copywriter_policy: Literal[
            "eligible",
            "medical_escalation",
            "evidence_gap",
        ] = "eligible",
    ) -> PresentationContractEvent:
        packet = build_presentation_packet(
            mode=mode,
            user_need_summary=user_need_summary,
            winner_status=winner_status,
            card_display=card_display,
            cards=cards,
            selection_slots=selection_slots,
            concept_slots=concept_slots,
            merchant_claims=merchant_claims,
            review_summaries=review_summaries,
            pitfalls=pitfalls,
            proof_points=proof_points,
        )
        return PresentationContractEvent(
            data=self._presentation_compiler.compile(
                PresentationCompileInputs(
                    packet=packet,
                    card_display=card_display,
                    copywriter_policy=copywriter_policy,
                )
            )
        )

    def _cards_for_product_ids(
        self,
        product_ids: Sequence[int],
        *,
        product_resolution: ProductMentionResolution | None = None,
    ) -> list[ProductCard]:
        cards: list[ProductCard] = []
        for product_id in product_ids:
            variant_scope = (
                product_resolution.variant_scope_for(product_id)
                if product_resolution is not None
                else None
            )
            facts = (
                self._presentation_facts.get_presentation_facts(
                    product_id,
                    variant_scope=variant_scope,
                )
                if variant_scope is not None
                else self._presentation_facts.get_presentation_facts(
                    product_id
                )
            )
            cards.append(
                build_product_card(
                    facts,
                    skin_match="unknown",
                )
            )
        return cards


def _category_constraint(
    constraints: list[object],
) -> CategoryConstraint:
    return next(
        item
        for item in constraints
        if isinstance(item, CategoryConstraint)
    )


def _selection_slot_data(
    facts: DecisionFactPort,
    *,
    product_ids: tuple[int, ...],
    constraints: list[object],
    safety_sensitive: bool,
) -> list[SelectionSlotData]:
    facets = tuple(
        item
        for item in constraints
        if isinstance(item, FacetConstraint)
    )
    if not facets:
        return []
    slots: list[SelectionSlotData] = []
    for product_id in product_ids:
        ranking = rank_soft_facets(
            facts.get_decision_facts(product_id),
            facets,
            safety_sensitive=safety_sensitive,
        )
        slots.extend(
            SelectionSlotData(
                product_id=item.product_id,
                field_key=item.field_key,
                requested_value=item.requested_value,
                matched_value=item.matched_value,
                match_status=item.match_status,
                rank_strength=item.rank_strength,
                source_refs=list(item.source_refs),
                attribution=item.attribution,
            )
            for item in ranking.slots
        )
    return slots


def _concept_slot_data(
    facts: DecisionFactPort,
    *,
    reader: SelectionParentConceptReader | None,
    product_ids: tuple[int, ...],
    constraints: list[object],
    safety_sensitive: bool,
) -> list[ConceptSlotData]:
    concepts = tuple(
        item
        for item in constraints
        if isinstance(item, ConceptConstraint)
    )
    if not concepts:
        return []
    if reader is None:
        raise ValueError(
            "concept slots require parent concept reader"
        )
    slots: list[ConceptSlotData] = []
    for product_id in product_ids:
        ranking = rank_common_concepts(
            facts.get_decision_facts(product_id),
            concepts,
            reader=reader,
            safety_sensitive=safety_sensitive,
        )
        slots.extend(
            ConceptSlotData(
                product_id=item.product_id,
                field_key=item.field_key,
                concept_id=item.concept_id,
                polarity=item.polarity,
                match_status=item.match_status,
                stance=item.stance,
                rank_strength=item.rank_strength,
                source_values=list(item.source_values),
                source_refs=list(item.source_refs),
                attribution=item.attribution,
            )
            for item in ranking.slots
        )
    return slots


def _append_concept_rank_reason(
    message: str,
    *,
    cards: list[ProductCard],
    concept_slots: list[ConceptSlotData],
) -> str:
    if not cards:
        return message
    first_product_id = cards[0].product_id
    matched = next(
        (
            slot
            for slot in concept_slots
            if (
                slot.product_id == first_product_id
                and slot.match_status == "matched"
                and slot.source_refs
            )
        ),
        None,
    )
    if matched is None:
        return message
    meaning = "、".join(matched.source_values[:2])
    if not meaning:
        return message
    return (
        f"{message}\n从现有资料看，第一款更贴近你要的"
        f"「{meaning}」方向；这表示需求匹配度更高，"
        "不代表效果更强。"
    )


def _append_relative_rank_reason(
    message: str,
    *,
    cards: list[ProductCard],
    comparisons: list[RelativeComparisonResult],
    requirement: RelativeRequirement | None,
) -> str:
    if not cards or requirement is None:
        return message
    first_product_id = cards[0].product_id
    comparison = next(
        (
            item
            for item in comparisons
            if (
                item.candidate_product_id == first_product_id
                and item.status == "better"
            )
        ),
        None,
    )
    if comparison is None:
        return message
    name = cards[0].name or f"商品 {first_product_id}"
    if comparison.relation_kind == "numeric":
        direction = (
            "更低" if requirement.direction == "lower" else "更高"
        )
        reason = f"{name}相对基准商品的审核价格{direction}。"
    elif comparison.relation_kind == "ordered":
        direction = (
            "更低" if requirement.direction == "lower" else "更高"
        )
        reason = (
            f"{name}有可比较的顺序证据支持{direction}。"
        )
    elif comparison.relation_kind == "better_evidence_support":
        reason = (
            f"{name}相对基准商品的证据支持更强；"
            "证据更强不代表效果更强。"
        )
    else:
        reason = (
            f"{name}相对基准商品更符合当前偏好；"
            "这不代表产品效果更强。"
        )
    return f"{message}\n{reason}"


def _task_category_profile(task: TaskPlan):
    category = next(
        (
            item
            for item in task.constraints
            if isinstance(item, CategoryConstraint)
        ),
        None,
    )
    return (
        category_profile_for_topic(category.value)
        if category is not None
        else None
    )


def _relative_baseline_product_id(
    snapshot: ConversationSnapshot | None,
    requirement: RelativeRequirement,
) -> int | None:
    if snapshot is None:
        return None
    if requirement.baseline.kind == "candidate_ordinal":
        ordinal = requirement.baseline.ordinal
    elif requirement.baseline.kind == "current_item":
        ordinal = snapshot.focused_candidate_ordinal
    else:
        return None
    if ordinal is None or ordinal > len(snapshot.candidates):
        return None
    return snapshot.candidates[ordinal - 1].product_id


def _project_merchant_claims(
    reader: MerchantClaimReader | None,
    *,
    product_ids: tuple[int, ...],
    constraints: list[object],
) -> list[MerchantClaimEvidenceData]:
    if reader is None:
        return []
    preferred_fields = {
        item.field_key
        for item in constraints
        if isinstance(item, FacetConstraint)
    }
    projected: list[MerchantClaimEvidenceData] = []
    for product_id in product_ids:
        deduplicated = {}
        for claim in reader.read(product_id=product_id):
            key = (
                claim.field_key,
                claim.display_claim,
                claim.claim_scope,
            )
            previous = deduplicated.get(key)
            if previous is None or claim.claim_id < previous.claim_id:
                deduplicated[key] = claim
        ordinary = sorted(
            (
                claim
                for claim in deduplicated.values()
                if claim.claim_scope == "ordinary"
            ),
            key=lambda claim: (
                claim.field_key not in preferred_fields,
                "soft_rank" not in claim.capabilities,
                claim.field_key,
                claim.claim_id,
            ),
        )
        safety = sorted(
            (
                claim
                for claim in deduplicated.values()
                if claim.claim_scope == "safety_transcript"
            ),
            key=lambda claim: claim.claim_id,
        )[:1]
        for claim in (*ordinary, *safety):
            projected.append(
                MerchantClaimEvidenceData(
                    claim_id=claim.claim_id,
                    product_id=claim.product_id,
                    field_key=claim.field_key,
                    normalized_value=claim.normalized_value,
                    display_claim=claim.display_claim,
                    claim_scope=claim.claim_scope,
                    allowed_use=(
                        "soft_rank_and_display"
                        if "soft_rank" in claim.capabilities
                        else "display_only"
                    ),
                    source_locator=claim.source_locator,
                )
            )
    return projected


def _presentation_proof_points(
    event: ProductEvidenceEvent | None,
) -> tuple[LockedFact, ...]:
    if event is None:
        return ()
    candidates = sorted(
        (
            item.evidence
            for item in event.data.packet.selected
            if (
                item.evidence.management_label
                == "consumer_self_report"
                and item.evidence.qualifiers.sample_size is not None
                and item.evidence.qualifiers.population is not None
                and item.evidence.qualifiers.method is not None
                and item.evidence.qualifiers.duration is not None
                and re.search(
                    r"(?:\d+(?:\.\d+)?%|百分之)",
                    item.evidence.exact_text,
                )
            )
        ),
        key=lambda point: (point.product_id, point.evidence_id),
    )
    first_by_product = {}
    for point in candidates:
        first_by_product.setdefault(point.product_id, point)

    proof_points: list[LockedFact] = []
    for point in first_by_product.values():
        qualifiers = point.qualifiers
        assert qualifiers.sample_size is not None
        assert qualifiers.population is not None
        assert qualifiers.method is not None
        assert qualifiers.duration is not None
        conditions = (
            f"{qualifiers.sample_size}名"
            f"{qualifiers.population}{qualifiers.duration}"
        )
        exact_text = point.exact_text.strip()
        body = (
            exact_text
            if conditions in exact_text
            else f"{conditions}，{exact_text}"
        )
        if qualifiers.method not in body:
            body = f"{body}；测试方法：{qualifiers.method}"
        display_value = f"商家引用：{body}"
        if len(display_value) > 512:
            continue
        proof_points.append(
            LockedFact(
                fact_id=f"evidence:{point.evidence_id}",
                product_id=point.product_id,
                kind="numeric",
                label="用户测试",
                display_value=display_value,
                source_refs=(point.source.source_locator,),
            )
        )
    return tuple(proof_points)


def _append_source_quotes(
    message: str,
    *,
    cards: list[ProductCard],
    merchant_claims: list[MerchantClaimEvidenceData],
    review_results: list[object],
) -> str:
    names = {
        card.product_id: card.name or f"商品 {card.product_id}"
        for card in cards
    }
    sections = [message]
    ordinary_by_product: dict[int, MerchantClaimEvidenceData] = {}
    for claim in merchant_claims:
        if claim.claim_scope == "ordinary":
            ordinary_by_product.setdefault(claim.product_id, claim)
    if ordinary_by_product:
        quotes = [
            (
                f"{names.get(product_id, f'商品 {product_id}')}："
                f"商家宣称「{claim.display_claim}」"
            )
            for product_id, claim in ordinary_by_product.items()
        ]
        sections.append(
            "商家宣称参考（未经独立核实）："
            + "；".join(quotes)
            + "。"
        )
    if any(
        claim.claim_scope == "safety_transcript"
        for claim in merchant_claims
    ):
        sections.append(
            "安全类商家宣称仅作原文转录，未经独立核实，"
            "不作为安全硬筛依据。"
        )
    review_quotes: list[str] = []
    review_count = 0
    for result in review_results:
        evidence = getattr(result, "evidence", ())
        review_count += len(evidence)
        if evidence:
            review_quotes.append(
                (
                    f"{names.get(result.product_id, f'商品 {result.product_id}')}："
                    f"「{evidence[0].content}」"
                )
            )
    if review_quotes:
        sections.append(
            (
                "已批准评论原文"
                f"（当前命中 {review_count} 条，逐商品展示 1 条）："
            )
            + "；".join(review_quotes)
            + "。"
        )
    return "\n".join(sections)


def _presentation_compatibility_message(
    event: PresentationContractEvent,
    *,
    default: str,
) -> str:
    if event.data.copy_source == "fallback":
        return default
    copy_parts = tuple(
        section.copy_text.strip()
        for section in event.data.sections
        if section.kind in {"summary", "product", "closing"}
        and section.copy_text is not None
        and section.copy_text.strip()
    )
    return "\n".join(copy_parts) if copy_parts else default


def _summary_fragment(decision: DecisionResult) -> str:
    if decision.winner_status is WinnerStatus.NO_CANDIDATE:
        return "暂时没有找到能同时满足你这些要求的商品。"
    if (
        decision.winner_status is WinnerStatus.INSUFFICIENT_FOR_WINNER
        and "efficacy=repair" in decision.evidence_refs
    ):
        return (
            "已经找到符合预算、主打修护的商品，但敏感肌适配信息"
            "还不够完整，所以先不替你定下唯一一款。"
        )
    if decision.winner_status is WinnerStatus.INSUFFICIENT_FOR_WINNER:
        return (
            "已经找到预算内的商品，但肤质适配信息还不够完整，"
            "所以先不替你定下唯一一款。"
        )
    if decision.winner_status is WinnerStatus.TIED_BY_BUSINESS_EVIDENCE:
        return (
            "前几款目前各有取舍，先结合下方信息比较，"
            "不替你定死唯一一款。"
        )
    return "已经按你说的需求重新整理，下面先看更贴近的几款。"
