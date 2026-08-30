"""Slice 1 文本推荐编排。

应用层只负责串联六层、产出 typed SSE 事件，不持有词表、
商品过滤、排序或文案推理规则。
"""
from __future__ import annotations

from collections.abc import Sequence

from app.guide.application.execution_contracts import (
    ClarificationLaneState,
    ClarificationTerminal,
    ConversationStateDelta,
    ExecutionResult,
    ImageLaneState,
    ImageRoutingEvidence,
    KnowledgeLaneState,
    LaneMutation,
    PersistedImageRoutingEvidence,
    PresentationTerminal,
    ProductLaneState,
    ProcessorExecutionInput,
    RecommendationLaneState,
    notify_processor_entry,
)
from app.guide.application.product_evidence_answer import (
    build_product_knowledge_answer_plan,
    render_product_evidence_fact,
)
from app.guide.application.general_knowledge_answer import (
    render_general_knowledge_answer,
)
from app.guide.application.query_context import (
    task_plan_to_query_context,
)
from app.guide.application.pending_turn import (
    PendingReply,
)
from app.guide.application.recommendation_terminal import (
    FitSelectionEvidenceGap,
    fit_selection_clarification_data,
    fit_selection_is_unresolved,
    public_recommendation_winner_status,
    require_fit_presentation_facts,
)
from app.guide.decision.contracts import (
    CandidateEvaluation,
    DecisionResult,
    RelativeComparisonResult,
    WinnerStatus,
)
from app.guide.decision.concept_ranking import rank_common_concepts
from app.guide.decision.facet_ranking import rank_soft_facets
from app.guide.decision.ports import DecisionFactPort
from app.guide.decision.recommendation import decide_recommendation
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    DisplayedCandidateRef,
    PendingClarificationSlot,
    PendingReplySlot,
)
from app.guide.feedback.focus_state import validate_confirmed_image_batch
from app.guide.feedback.profile_policy import ResolvedProfileContext
from app.guide.intent.contracts import (
    CategoryConstraint,
    ConceptConstraint,
    FacetConstraint,
    RelativeRequirement,
    TaskConstraint,
    TaskPlan,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
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
    ApprovedSoftFact,
    LockedFact,
    PresentationMode,
    SourceTaggedCopy,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompileInputs,
    PresentationCompiler,
)
from app.guide.presentation.presentation_packet import (
    build_presentation_packet,
)
from app.guide.presentation.public_fact_projection import (
    project_public_facts,
)
from app.guide.presentation.ports import PresentationFactPort
from app.guide.presentation.response_planning import (
    build_product_card,
    build_response_plan,
)
from app.guide.presentation.sse_events import (
    AnswerContractData,
    AnswerContractEvent,
    CardDisplayContractEvent,
    ClarifyData,
    ConceptSlotData,
    DecisionProcessData,
    DecisionProcessEvent,
    GeneralKnowledgeEvent,
    IntentData,
    IntentEvent,
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
    image_citations_event,
    image_observation_events,
)
from app.guide.retrieval.canonical_retrieval import retrieve_candidates
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.retrieval.category_taxonomy import (
    category_profile_for_topic,
)
from app.guide.retrieval.ports import (
    CategoryCatalogPort,
    ScenarioEvidencePort,
)
from app.guide.retrieval.product_name_resolver import ProductMentionResolution
from app.guide.retrieval.pitfall_contracts import TypedPitfall
from app.guide.retrieval.product_evidence_retrieval import (
    EvidencePacket,
    EvidenceQuery,
    ProductEvidenceRetriever,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)
from app.guide.retrieval.general_knowledge_query import (
    build_knowledge_query_spec,
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
from app.guide.understanding.contracts import (
    StructuredUnderstanding,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
)
from app.guide.understanding.ports import CanonicalIdentityCatalogPort
from app.guide.understanding.turn_meaning_contracts import RecommendationMode


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
        canonical_identities: CanonicalIdentityCatalogPort | None = None,
        presentation_compiler: PresentationCompiler | None = None,
        execution_observer=None,
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
        self._canonical_identities = canonical_identities
        self._presentation_compiler = (
            presentation_compiler
            if presentation_compiler is not None
            else PresentationCompiler(copywriter=None)
        )
        self._execution_observer = execution_observer


    def execute(
        self,
        execution_input: ProcessorExecutionInput,
    ) -> ExecutionResult:
        if type(execution_input) is not ProcessorExecutionInput:
            raise TypeError(
                "execution_input must be an exact ProcessorExecutionInput"
            )
        notify_processor_entry(
            self._execution_observer,
            execution_input=execution_input,
            implementation=type(self).__qualname__,
            processor_instance=self,
        )
        understanding = execution_input.understanding
        snapshot = execution_input.current_snapshot
        route_decision = execution_input.decision
        evidence = execution_input.routing_evidence
        product_resolution = evidence.product_resolution
        pending_reply = evidence.pending_reply
        profile_context = evidence.profile_context
        routing_evidence = evidence.image
        candidate_product_ids = evidence.candidate_product_ids
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
        if type(route_decision) is not UnifiedRouteDecision:
            raise TypeError(
                "route_decision must be an exact UnifiedRouteDecision"
            )
        if type(product_resolution) is not ProductMentionResolution:
            raise TypeError(
                "product_resolution must be ProductMentionResolution"
            )
        if type(profile_context) is not ResolvedProfileContext:
            raise TypeError(
                "profile_context must be ResolvedProfileContext"
            )
        if (
            routing_evidence is not None
            and type(routing_evidence)
            not in {
                ImageRoutingEvidence,
                PersistedImageRoutingEvidence,
            }
        ):
            raise TypeError(
                "routing_evidence must be current or persisted image "
                "evidence"
            )
        if (
            type(candidate_product_ids) is not tuple
            or any(
                not isinstance(product_id, int)
                or isinstance(product_id, bool)
                or product_id <= 0
                for product_id in candidate_product_ids
            )
            or len(candidate_product_ids)
            != len(set(candidate_product_ids))
        ):
            raise TypeError(
                "candidate_product_ids must contain unique positive integers"
            )
        if (
            pending_reply is not None
            and pending_reply.kind != "replace_task"
        ):
            if _pending_turn(snapshot) is None:
                raise ValueError(
                    "pending reply requires persisted pending turn"
                )
            return self._execute_pending_reply(
                execution_input,
                snapshot=snapshot,
                route_decision=route_decision,
                reply=pending_reply,
            )
        admitted = understanding
        effective_product_resolution = product_resolution
        if route_decision.product_bindings:
            effective_product_resolution = ProductMentionResolution(
                bindings=route_decision.product_bindings,
            )
        task = route_decision.task_plan
        if task is None:
            raise ValueError("route decision omitted executable task plan")
        if route_decision.processor == "clarification":
            pending_turn = (
                execution_input.routing_evidence.prepared_pending_turn
            )
            clarification = ClarifyData(
                question=(
                    route_decision.clarification
                    or task.clarification
                    or "请明确这次要查看的商品或任务。"
                ),
                clarification_code=(
                    route_decision.clarification_code
                    or task.clarification_code
                    or ClarificationCode.REFERENCE
                ),
                pending_turn=pending_turn,
            )
            return self._clarification_execution_result(
                execution_input=execution_input,
                route_decision=route_decision,
                snapshot=snapshot,
                clarification=clarification,
                audit_events=(
                    StageEvent(
                        data=StageData(
                            stage="understanding",
                            summary=(
                                "已提取明确预算、品类和适配条件。"
                            ),
                        )
                    ),
                    IntentEvent(
                        data=IntentData(
                            mode=route_decision.public_intent_mode
                        )
                    ),
                ),
            )
        if task.mode == "clarify":
            if task.clarification_code is None:
                raise RuntimeError(
                    "clarification task requires typed code"
                )
            return self._clarification_execution_result(
                execution_input=execution_input,
                route_decision=route_decision,
                snapshot=snapshot,
                clarification=ClarifyData(
                    question=task.clarification,
                    clarification_code=task.clarification_code,
                    pending_turn=(
                        execution_input.routing_evidence.prepared_pending_turn
                    ),
                ),
                audit_events=(
                    StageEvent(
                        data=StageData(
                            stage="understanding",
                            summary=(
                                "已提取明确预算、品类和适配条件。"
                            ),
                        )
                    ),
                    IntentEvent(
                        data=IntentData(
                            mode=route_decision.public_intent_mode
                        )
                    ),
                ),
            )
        if route_decision.processor == "general_knowledge":
            return self._execute_general_knowledge_task(
                execution_input,
                snapshot=snapshot,
                task=task,
                route_decision=route_decision,
            )
        if route_decision.processor == "recommendation":
            if task.mode != "recommend":
                raise ValueError(
                    "recommendation route requires recommendation task"
                )
            return self._execute_recommendation(
                execution_input,
                snapshot=snapshot,
                task=task,
                route_decision=route_decision,
                candidate_product_ids=candidate_product_ids,
            )
        if (
            route_decision.processor in {
                "comparison",
                "product_knowledge",
            }
            and task.mode in {"comparison", "suitability"}
            and task.product_ids
        ):
            return self._execute_direct_product_task(
                execution_input,
                snapshot=snapshot,
                task=task,
                route_decision=route_decision,
                product_resolution=effective_product_resolution,
            )
        if (
            route_decision.processor == "product_knowledge"
            and task.mode in {"knowledge", "followup"}
            and task.product_ids
            and self._product_evidence is not None
        ):
            return self._execute_product_evidence_task(
                execution_input,
                snapshot=snapshot,
                task=task,
                route_decision=route_decision,
                product_resolution=effective_product_resolution,
            )
        raise NotImplementedError(
            f"{route_decision.processor} execution is not migrated"
        )

    def _execute_pending_reply(
        self,
        execution_input: ProcessorExecutionInput,
        *,
        snapshot: ConversationSnapshot,
        route_decision: UnifiedRouteDecision,
        reply: PendingReply,
    ) -> ExecutionResult:
        pending = _pending_turn(snapshot)
        if pending is None:
            raise ValueError(
                "pending reply requires persisted pending turn"
            )
        if reply.kind in {
            "affirm",
            "correct",
            "supplement",
        }:
            task = route_decision.task_plan
            if task is None or task.mode != "recommend":
                raise ValueError(
                    "accepted pending reply requires recommendation task"
                )
            return self._execute_recommendation(
                execution_input,
                snapshot=snapshot,
                task=task,
                route_decision=route_decision,
            )
        if route_decision.processor != "clarification":
            raise ValueError(
                "unresolved pending reply requires clarification route"
            )
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
            question = (
                "请直接告诉我预算下限和上限，例如800到1000元。"
            )
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
        return self._clarification_execution_result(
            execution_input=execution_input,
            route_decision=route_decision,
            snapshot=snapshot,
            clarification=ClarifyData(
                question=question,
                clarification_code=pending.gap,
                pending_turn=next_pending,
            ),
            audit_events=(
                IntentEvent(
                    data=IntentData(
                        mode=route_decision.public_intent_mode
                    )
                ),
            ),
        )

    def _execute_general_knowledge_task(
        self,
        execution_input: ProcessorExecutionInput,
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
        route_decision: UnifiedRouteDecision,
    ) -> ExecutionResult:
        if self._general_knowledge is None:
            raise RuntimeError(
                "general knowledge retriever is unavailable"
            )
        topic = next(
            (
                constraint.value
                for constraint in task.constraints
                if isinstance(constraint, CategoryConstraint)
            ),
            None,
        )
        query = build_knowledge_query_spec(
            raw_query=(
                execution_input.routing_evidence.query.value.strip()
            ),
            question_meaning=(
                task.question_meaning or execution_input.routing_evidence.query.value.strip()
            ),
            topic=topic,
            relation_hints=task.knowledge_relation_hints,
            safety_sensitive=task.safety_sensitive,
            prior_knowledge_ids=(
                snapshot.knowledge_slot.evidence_ids
                if (
                    task.mode == "followup"
                    and snapshot is not None
                    and snapshot.knowledge_slot is not None
                )
                else ()
            ),
            top_k=3,
        )
        packet = self._general_knowledge.retrieve(query)
        rendered = render_general_knowledge_answer(packet)
        presentation = self._presentation_event(
            mode="general_knowledge",
            route_decision=route_decision,
            user_need_summary=(
                task.question_meaning or execution_input.routing_evidence.query.value.strip()
            ),
            winner_status="NOT_APPLICABLE",
            card_display=CardDisplayContract(
                mode="none",
                visible_product_ids=(),
                max_cards=0,
                reason=None,
            ),
            cards=(),
            task_constraints=task.constraints,
            copywriter_policy=(
                "medical_escalation"
                if rendered.data.medical_escalation
                else "eligible"
            ),
            authoritative_public_copy=SourceTaggedCopy(
                text=rendered.message,
            ),
        ).data
        knowledge_ids = tuple(
            sorted(hit.block.knowledge_id for hit in packet.hits)
        )
        knowledge_topic = (
            topic
            or task.question_meaning
            or execution_input.routing_evidence.query.value.strip()
        )
        return ExecutionResult(
            decision=route_decision,
            state_delta=ConversationStateDelta(
                profile_owner=(
                    execution_input.routing_evidence.profile_owner
                ),
                image=_image_lane_mutation(execution_input),
                knowledge=LaneMutation[KnowledgeLaneState](
                    action="replace",
                    value=KnowledgeLaneState(
                        focused_ids=knowledge_ids,
                        question=execution_input.routing_evidence.query.value.strip(),
                        topic=knowledge_topic[:256],
                    ),
                ),
                clarification=LaneMutation[ClarificationLaneState](
                    action="clear",
                    reason="resolved by general knowledge answer",
                ),
            ),
            terminal=PresentationTerminal(data=presentation),
            audit_events=_execution_audit_events(
                execution_input,
                (
                    StageEvent(
                        data=StageData(
                            stage="understanding",
                            summary="已提取明确预算、品类和适配条件。",
                        )
                    ),
                    IntentEvent(
                        data=IntentData(
                            mode=route_decision.public_intent_mode
                        )
                    ),
                    StageEvent(
                        data=StageData(
                            stage="retrieval",
                            summary="已检索审核过的通用知识资料。",
                        )
                    ),
                    GeneralKnowledgeEvent(data=rendered.data),
                ),
            ),
        )

    def _execute_recommendation(
        self,
        execution_input: ProcessorExecutionInput,
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
        route_decision: UnifiedRouteDecision,
        candidate_product_ids: tuple[int, ...] = (),
    ) -> ExecutionResult:
        scenario_inputs = (
            execution_input.routing_evidence.scenario_inputs
        )
        if scenario_inputs is None:
            raise ValueError(
                "recommendation execution requires scenario inputs"
            )
        if scenario_inputs.decision.constraints != task.constraints:
            raise ValueError(
                "scenario evidence differs from router-owned task"
            )
        effective_task = task
        category = _category_constraint(effective_task.constraints)
        retrieval = retrieve_candidates(
            self._category_catalog,
            category=category.value,
        )
        if candidate_product_ids:
            candidates_by_id = {
                candidate.product_id: candidate
                for candidate in retrieval.candidates
            }
            retrieval = retrieval.model_copy(
                update={
                    "candidates": [
                        candidates_by_id[product_id]
                        for product_id in candidate_product_ids
                        if product_id in candidates_by_id
                    ]
                },
                deep=True,
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
        )
        if fit_selection_is_unresolved(
            recommendation_mode=effective_task.recommendation_mode,
            decision=decision,
        ):
            clarification = fit_selection_clarification_data(
                decision=decision,
                gap_stage="decision_selection",
            )
            return self._clarification_execution_result(
                execution_input=execution_input,
                route_decision=route_decision,
                snapshot=snapshot,
                clarification=clarification,
                recommendation_task=effective_task,
                audit_events=(
                    StageEvent(
                        data=StageData(
                            stage="understanding",
                            summary=(
                                "已提取明确预算、品类和适配条件。"
                            ),
                        )
                    ),
                    IntentEvent(
                        data=IntentData(
                            mode=route_decision.public_intent_mode
                        )
                    ),
                ),
            )
        visible_limit = effective_task.recommendation_count
        if visible_limit is None:
            raise AssertionError(
                "recommend task requires recommendation count"
            )
        visible_product_ids = (
            (
                (decision.winner_product_id,)
                if decision.winner_product_id is not None
                else ()
            )
            if effective_task.recommendation_mode == "fit"
            else tuple(
                decision.ordered_product_ids[:visible_limit]
            )
        )
        visible_decision = decision.model_copy(
            update={
                "ordered_product_ids": list(visible_product_ids),
                "relative_comparisons": [
                    item
                    for item in decision.relative_comparisons
                    if item.candidate_product_id
                    in visible_product_ids
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
                execution_input,
                task=effective_task,
                product_ids=tuple(
                    card.product_id for card in cards
                ),
            )
        )
        has_unknown_skin = any(
            item.kind == "skin_match_unknown"
            for item in visible_decision.risk_findings
        )
        public_winner_status = public_recommendation_winner_status(
            recommendation_mode=effective_task.recommendation_mode,
            decision=visible_decision,
            is_constraint_revision=(
                route_decision.continuity
                in {"correct", "supplement", "withdraw"}
            ),
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
        audit_events: list[SseEvent] = [
            StageEvent(
                data=StageData(
                    stage="understanding",
                    summary="已提取明确预算、品类和适配条件。",
                )
            ),
            IntentEvent(
                data=IntentData(
                    mode=route_decision.public_intent_mode,
                    category_profile=_task_category_profile(
                        effective_task
                    ),
                )
            ),
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
            audit_events.append(
                ScenarioEvidenceEvent(
                    data=ScenarioEvidenceData(
                        records=scenario_records,
                    )
                )
            )
        if merchant_claims:
            audit_events.append(
                MerchantClaimsEvent(
                    data=MerchantClaimsData(claims=merchant_claims)
                )
            )
        if (
            review_results
            and (scenario_records or has_review_evidence)
        ):
            audit_events.append(
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
            audit_events.append(
                PitfallsEvent(
                    data=PitfallsData(pitfalls=pitfalls)
                )
            )
        audit_events.extend(
            [
                DecisionProcessEvent(
                    data=DecisionProcessData(
                        ordered_product_ids=list(
                            visible_decision.ordered_product_ids
                        ),
                        winner_status=public_winner_status,
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
                        winner_status=public_winner_status,
                        has_unknown_skin=has_unknown_skin,
                    )
                ),
                CardDisplayContractEvent(data=card_display),
                ProductsEvent(data=ProductsData(cards=cards)),
            ]
        )
        if product_evidence_event is not None:
            audit_events.append(product_evidence_event)
        try:
            presentation = self._presentation_event(
                mode=(
                    "image_recommendation"
                    if (
                        effective_task.similarity_anchor_product_id
                        is not None
                    )
                    else "recommendation"
                ),
                route_decision=route_decision,
                user_need_summary=(
                    effective_task.question_meaning
                    or execution_input.routing_evidence.query.value.strip()
                ),
                winner_status=public_winner_status,
                winner_product_id=(
                    visible_decision.winner_product_id
                    if effective_task.recommendation_mode == "fit"
                    else None
                ),
                recommendation_mode=effective_task.recommendation_mode,
                card_display=card_display,
                cards=cards,
                task_constraints=effective_task.constraints,
                selection_slots=selection_slots,
                concept_slots=concept_slots,
                merchant_claims=merchant_claims,
                review_summaries=review_summaries,
                pitfalls=pitfalls,
                proof_points=_presentation_proof_points(
                    product_evidence_event
                ),
            ).data
        except FitSelectionEvidenceGap:
            clarification = fit_selection_clarification_data(
                decision=visible_decision,
                gap_stage="public_fact_projection",
            )
            return self._clarification_execution_result(
                execution_input=execution_input,
                route_decision=route_decision,
                snapshot=snapshot,
                clarification=clarification,
                recommendation_task=effective_task,
                audit_events=tuple(audit_events),
            )
        candidates = tuple(
            DisplayedCandidateRef(
                product_id=card.product_id,
                ordinal=index,
                skin_match=card.skin_match,
                matched_efficacies=tuple(card.matched_efficacies),
            )
            for index, card in enumerate(cards, start=1)
        )
        return ExecutionResult(
            decision=route_decision,
            state_delta=ConversationStateDelta(
                profile_owner=(
                    execution_input.routing_evidence.profile_owner
                ),
                image=_image_lane_mutation(execution_input),
                recommendation=LaneMutation[
                    RecommendationLaneState
                ](
                    action="replace",
                    value=RecommendationLaneState(
                        query_context=task_plan_to_query_context(
                            effective_task
                        ),
                        candidates=candidates,
                        empty_result=not candidates,
                    ),
                ),
                clarification=LaneMutation[ClarificationLaneState](
                    action="clear",
                    reason="resolved by recommendation",
                ),
            ),
            terminal=PresentationTerminal(data=presentation),
            audit_events=_execution_audit_events(
                execution_input,
                audit_events,
            ),
        )

    def _execute_direct_product_task(
        self,
        execution_input: ProcessorExecutionInput,
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
        route_decision: UnifiedRouteDecision,
        product_resolution: ProductMentionResolution,
    ) -> ExecutionResult:
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
        profile_evaluations: tuple[CandidateEvaluation, ...] = ()
        if task.mode == "comparison":
            profile_decision = decide_recommendation(
                self._decision_facts,
                retrieval,
                constraints=decision_constraints,
                safety_sensitive=task.safety_sensitive,
                concept_reader=self._concept_reader,
            )
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
            visible_ids = set(decision.ordered_product_ids)
            profile_evaluations = tuple(
                evaluation
                for evaluation in profile_decision.evaluations
                if evaluation.product_id in visible_ids
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
        else:
            if len(cards) != 1:
                raise ValueError(
                    "direct suitability requires exactly one card"
                )
            card_display = single_product_card_display(cards[0])
        product_evidence_event = (
            self._build_post_decision_evidence_event(
                execution_input,
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
        presentation = self._presentation_event(
            mode=(
                "comparison"
                if task.mode == "comparison"
                else "single_product"
            ),
            route_decision=route_decision,
            user_need_summary=(
                task.question_meaning or execution_input.routing_evidence.query.value.strip()
            ),
            winner_status=decision.winner_status.value,
            winner_product_id=(
                decision.winner_product_id
                if task.mode == "comparison"
                else None
            ),
            winner_tie_reason=decision.tie_reason,
            card_display=card_display,
            cards=cards,
            task_constraints=task.constraints,
            selection_slots=selection_slots,
            concept_slots=concept_slots,
            merchant_claims=merchant_claims,
            review_summaries=review_summaries,
            proof_points=_presentation_proof_points(
                product_evidence_event
            ),
            requested_dimensions=(
                task.requested_comparison_dimensions
            ),
            candidate_evaluations=profile_evaluations,
        ).data
        public_winner_status = decision.winner_status.value
        if (
            presentation.responsibility
            is Responsibility.COMPARISON
        ):
            presentation_winner = presentation.winner
            if presentation_winner is None:
                raise ValueError(
                    "comparison presentation requires winner outcome"
                )
            public_winner_status = {
                "selected": WinnerStatus.SELECTED.value,
                "tied": (
                    WinnerStatus.TIED_BY_BUSINESS_EVIDENCE.value
                ),
                "insufficient": (
                    WinnerStatus.INSUFFICIENT_FOR_WINNER.value
                ),
                "not_applicable": WinnerStatus.NO_CANDIDATE.value,
            }[presentation_winner.status]
        evidence_ids = (
            tuple(
                item.evidence.evidence_id
                for item in product_evidence_event.data.packet.selected
            )
            if product_evidence_event is not None
            else ()
        )
        comparison_candidates = tuple(
            DisplayedCandidateRef(
                product_id=card.product_id,
                ordinal=index,
                skin_match=card.skin_match,
                matched_efficacies=tuple(card.matched_efficacies),
            )
            for index, card in enumerate(cards, start=1)
        )
        if task.mode == "suitability":
            product_mutation = LaneMutation[ProductLaneState](
                action="replace",
                value=ProductLaneState(
                    products=(comparison_candidates[0],),
                    focused_product_id=product_ids[0],
                    focused_evidence_ids=evidence_ids,
                ),
            )
        elif task.mode == "comparison":
            product_mutation = LaneMutation[ProductLaneState](
                action="replace",
                value=ProductLaneState(
                    products=comparison_candidates,
                    focused_evidence_ids=evidence_ids,
                ),
            )
        else:
            product_mutation = LaneMutation[ProductLaneState](
                action="preserve"
            )
        state_delta = ConversationStateDelta(
            profile_owner=(
                execution_input.routing_evidence.profile_owner
            ),
            image=_image_lane_mutation(execution_input),
            product=product_mutation,
            clarification=LaneMutation[ClarificationLaneState](
                action="clear",
                reason="resolved by direct product task",
            ),
        )
        audit_events: list[SseEvent] = [
            StageEvent(
                data=StageData(
                    stage="understanding",
                    summary="已提取明确预算、品类和适配条件。",
                )
            ),
            IntentEvent(
                data=IntentData(
                    mode=route_decision.public_intent_mode,
                    category_profile=_task_category_profile(task),
                )
            ),
            StageEvent(
                data=StageData(
                    stage="retrieval",
                    summary="已按商品名称绑定 Canonical 目录。",
                )
            ),
            StageEvent(
                data=StageData(
                    stage="decision",
                    summary="已执行同一套事实状态和硬约束判断。",
                )
            ),
            DecisionProcessEvent(
                data=DecisionProcessData(
                    ordered_product_ids=list(
                        decision.ordered_product_ids
                    ),
                    winner_status=public_winner_status,
                    evidence_refs=list(decision.evidence_refs),
                    selection_slots=selection_slots,
                    concept_slots=concept_slots,
                    relative_comparisons=list(
                        decision.relative_comparisons
                    ),
                )
            ),
            AnswerContractEvent(
                data=AnswerContractData(
                    product_count=len(cards),
                    winner_status=public_winner_status,
                    has_unknown_skin=any(
                        card.skin_match == "unknown"
                        for card in cards
                    ),
                )
            ),
            CardDisplayContractEvent(data=card_display),
            ProductsEvent(data=ProductsData(cards=cards)),
        ]
        if product_evidence_event is not None:
            audit_events.append(product_evidence_event)
        return ExecutionResult(
            decision=route_decision,
            state_delta=state_delta,
            terminal=PresentationTerminal(data=presentation),
            audit_events=_execution_audit_events(
                execution_input,
                audit_events,
            ),
        )

    def _execute_product_evidence_task(
        self,
        execution_input: ProcessorExecutionInput,
        *,
        snapshot: ConversationSnapshot | None,
        task: TaskPlan,
        route_decision: UnifiedRouteDecision,
        product_resolution: ProductMentionResolution,
    ) -> ExecutionResult:
        if self._product_evidence is None:
            raise RuntimeError(
                "product evidence retriever is unavailable"
            )
        evidence_search = (
            execution_input.routing_evidence.product_evidence_search
        )
        if evidence_search is None:
            raise ValueError(
                "product evidence execution requires prepared search"
            )
        query = EvidenceQuery(
            product_ids=tuple(task.product_ids),
            search=evidence_search,
            safety_sensitive=task.safety_sensitive,
            product_identity_names=self._product_identity_names(
                task.product_ids,
                product_resolution=product_resolution,
            ),
        )
        packet = self._product_evidence.retrieve(query)
        cards = self._cards_for_product_ids(
            task.product_ids,
            product_resolution=product_resolution,
        )
        if len(cards) != 1:
            raise ValueError(
                "product knowledge execution requires one product"
            )
        product_id = cards[0].product_id
        variant_scope = product_resolution.variant_scope_for(product_id)
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
        product_names = {
            product_id: facts.name or f"商品{product_id}"
        }
        merchant_claims = _project_merchant_claims(
            self._merchant_claims,
            product_ids=(product_id,),
            constraints=task.constraints,
        )
        review_summaries = tuple(
            summary
            for summary in (
                build_review_summary(
                    self._review_evidence.read(
                        product_id=product_id
                    )
                ),
            )
            if summary is not None
        )
        requested_dimensions = (
            execution_input.routing_evidence
            .product_knowledge_dimensions
        )
        evidence_facts = (
            *_approved_product_evidence_facts(
                packet,
                product_names=product_names,
            ),
            *_approved_merchant_claim_facts(merchant_claims),
            *_approved_review_summary_facts(review_summaries),
        )
        projection = project_public_facts(
            card=cards[0],
            approved_soft_facts=evidence_facts,
            requested_dimensions=requested_dimensions,
        )
        answer_plan = build_product_knowledge_answer_plan(
            projection=projection,
            question=execution_input.routing_evidence.query.value,
            requested_dimensions=requested_dimensions,
        )
        product_evidence_event = ProductEvidenceEvent(
            data=ProductEvidenceData(packet=packet)
        )
        card_display = single_product_card_display(cards[0])
        presentation = self._presentation_event(
            mode="product_knowledge",
            route_decision=route_decision,
            user_need_summary=(
                task.question_meaning or execution_input.routing_evidence.query.value.strip()
            ),
            winner_status="NOT_APPLICABLE",
            card_display=card_display,
            cards=cards,
            task_constraints=task.constraints,
            merchant_claims=(),
            review_summaries=(),
            proof_points=(),
            additional_soft_facts=evidence_facts,
            requested_dimensions=requested_dimensions,
            authoritative_public_copy=SourceTaggedCopy(
                text=answer_plan.answer_text,
                used_fact_ids=answer_plan.used_fact_ids,
            ),
        ).data
        evidence_ids = tuple(
            item.evidence.evidence_id
            for item in packet.selected
        )
        product_state = DisplayedCandidateRef(
            product_id=product_id,
            ordinal=1,
            skin_match=cards[0].skin_match,
            matched_efficacies=tuple(cards[0].matched_efficacies),
        )
        return ExecutionResult(
            decision=route_decision,
            state_delta=ConversationStateDelta(
                profile_owner=(
                    execution_input.routing_evidence.profile_owner
                ),
                image=_image_lane_mutation(execution_input),
                product=LaneMutation[ProductLaneState](
                    action="replace",
                    value=ProductLaneState(
                        products=(product_state,),
                        focused_product_id=product_id,
                        focused_evidence_ids=evidence_ids,
                    ),
                ),
                clarification=LaneMutation[
                    ClarificationLaneState
                ](
                    action="clear",
                    reason="resolved by product knowledge answer",
                ),
            ),
            terminal=PresentationTerminal(data=presentation),
            audit_events=_execution_audit_events(
                execution_input,
                (
                    StageEvent(
                        data=StageData(
                            stage="understanding",
                            summary="已提取明确预算、品类和适配条件。",
                        )
                    ),
                    IntentEvent(
                        data=IntentData(
                            mode=route_decision.public_intent_mode,
                            category_profile=_task_category_profile(task),
                        )
                    ),
                    StageEvent(
                        data=StageData(
                            stage="retrieval",
                            summary=(
                                "已在当前商品的审核证据中检索相关资料。"
                            ),
                        )
                    ),
                    AnswerContractEvent(
                        data=AnswerContractData(
                            product_count=1,
                            winner_status="NOT_APPLICABLE",
                            has_unknown_skin=True,
                        )
                    ),
                    CardDisplayContractEvent(data=card_display),
                    ProductsEvent(data=ProductsData(cards=cards)),
                    product_evidence_event,
                ),
            ),
        )

    @staticmethod
    def _clarification_execution_result(
        *,
        execution_input: ProcessorExecutionInput,
        route_decision: UnifiedRouteDecision,
        snapshot: ConversationSnapshot | None,
        clarification: ClarifyData,
        audit_events: tuple[SseEvent, ...],
        recommendation_task: TaskPlan | None = None,
    ) -> ExecutionResult:
        previous = (
            _clarification(snapshot)
        )
        attempts = (
            min(previous.attempts + 1, 2)
            if (
                previous is not None
                and previous.gap
                is clarification.clarification_code
            )
            else 1
        )
        pending_turn = clarification.pending_turn
        if pending_turn is not None:
            pending_turn = pending_turn.model_copy(
                update={"attempts": attempts},
                deep=True,
            )
        recommendation = (
            LaneMutation[RecommendationLaneState](
                action="replace",
                value=RecommendationLaneState(
                    query_context=task_plan_to_query_context(
                        recommendation_task
                    ),
                    candidates=(),
                    empty_result=True,
                ),
            )
            if recommendation_task is not None
            else LaneMutation[RecommendationLaneState](
                action="preserve"
            )
        )
        return ExecutionResult(
            decision=route_decision,
            state_delta=ConversationStateDelta(
                profile_owner=(
                    execution_input.routing_evidence.profile_owner
                ),
                recommendation=recommendation,
                image=_image_lane_mutation(execution_input),
                clarification=LaneMutation[
                    ClarificationLaneState
                ](
                    action="replace",
                    value=ClarificationLaneState(
                        progress=ClarificationProgress(
                            gap=clarification.clarification_code,
                            attempts=attempts,
                        ),
                        pending_turn=pending_turn,
                    ),
                )
            ),
            terminal=ClarificationTerminal(data=clarification),
            audit_events=_execution_audit_events(
                execution_input,
                audit_events,
            ),
        )





    def _build_post_decision_evidence_event(
        self,
        execution_input: ProcessorExecutionInput,
        *,
        task: TaskPlan,
        product_ids: tuple[int, ...],
    ) -> ProductEvidenceEvent | None:
        if self._product_evidence is None or not product_ids:
            return None
        evidence_search = (
            execution_input.routing_evidence.product_evidence_search
        )
        if evidence_search is None:
            raise ValueError(
                "product evidence execution requires prepared search"
            )
        packet = self._product_evidence.retrieve(
            EvidenceQuery(
                product_ids=product_ids,
                search=evidence_search,
                safety_sensitive=task.safety_sensitive,
                product_identity_names=self._product_identity_names(
                    product_ids,
                    product_resolution=(
                        execution_input.routing_evidence.product_resolution
                    ),
                ),
            )
        )
        return ProductEvidenceEvent(
            data=ProductEvidenceData(packet=packet)
        )

    def _product_identity_names(
        self,
        product_ids: Sequence[int],
        *,
        product_resolution: ProductMentionResolution,
    ) -> tuple[str, ...]:
        bindings_by_product = {
            product_id: tuple(
                binding
                for binding in product_resolution.bindings
                if binding.product_id == product_id
            )
            for product_id in product_ids
        }
        names: list[str] = []
        for product_id in product_ids:
            bindings = bindings_by_product[product_id]
            if len(bindings) == 1:
                binding = bindings[0]
                if binding.variant_scope is not None:
                    names.append(binding.variant_scope)
                    continue
            if self._canonical_identities is None:
                return ()
            identity = self._canonical_identities.get_identity(product_id)
            if identity is None or identity.product_name is None:
                return ()
            names.append(identity.product_name)
        return tuple(names)

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
        route_decision: UnifiedRouteDecision,
        user_need_summary: str,
        winner_status: str | None,
        recommendation_mode: RecommendationMode | None = None,
        card_display: CardDisplayContract,
        cards: Sequence[ProductCard],
        winner_product_id: int | None = None,
        winner_tie_reason: str | None = None,
        selection_slots: Sequence[SelectionSlotData] = (),
        concept_slots: Sequence[ConceptSlotData] = (),
        merchant_claims: Sequence[
            MerchantClaimEvidenceData
        ] = (),
        review_summaries: Sequence[ReviewSummaryResult] = (),
        pitfalls: Sequence[TypedPitfall] = (),
        proof_points: Sequence[LockedFact] = (),
        task_constraints: Sequence[TaskConstraint] = (),
        additional_soft_facts: Sequence[ApprovedSoftFact] = (),
        requested_dimensions: Sequence[str] = (),
        candidate_evaluations: Sequence[CandidateEvaluation] = (),
        copywriter_policy: Literal[
            "eligible",
            "medical_escalation",
            "evidence_gap",
        ] = "eligible",
        authoritative_public_copy: SourceTaggedCopy | None = None,
    ) -> PresentationContractEvent:
        responsibility = route_decision.responsibility
        packet = build_presentation_packet(
            mode=mode,
            responsibility=responsibility,
            recommendation_mode=recommendation_mode,
            user_need_summary=user_need_summary,
            winner_status=winner_status,
            winner_product_id=winner_product_id,
            winner_tie_reason=winner_tie_reason,
            card_display=card_display,
            cards=cards,
            selection_slots=selection_slots,
            concept_slots=concept_slots,
            merchant_claims=merchant_claims,
            review_summaries=review_summaries,
            pitfalls=pitfalls,
            proof_points=proof_points,
            task_constraints=task_constraints,
            additional_soft_facts=additional_soft_facts,
            requested_dimensions=requested_dimensions,
            candidate_evaluations=candidate_evaluations,
        )
        require_fit_presentation_facts(
            recommendation_mode=recommendation_mode,
            detail_fact_counts=tuple(
                len(slot.detail_facts)
                for slot in packet.slots
            ),
        )
        return PresentationContractEvent(
            data=self._presentation_compiler.compile(
                PresentationCompileInputs(
                    packet=packet,
                    card_display=card_display,
                    public_mode=route_decision.presentation_mode,
                    copywriter_policy=copywriter_policy,
                    authoritative_public_copy=(
                        authoritative_public_copy
                    ),
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


def _candidate_batch(
    snapshot: ConversationSnapshot | None,
) -> tuple[DisplayedCandidateRef, ...]:
    if snapshot is None:
        return ()
    if (
        snapshot.active_focus is not None
        and snapshot.active_focus.slot == "product"
        and snapshot.product_slot is not None
    ):
        return snapshot.product_slot.products
    if snapshot.recommendation_slot is not None:
        return snapshot.recommendation_slot.candidates
    if snapshot.product_slot is not None:
        return snapshot.product_slot.products
    return ()


def _focused_candidate_ordinal(
    snapshot: ConversationSnapshot | None,
) -> int | None:
    if snapshot is None or snapshot.recommendation_slot is None:
        return None
    return snapshot.recommendation_slot.focused_candidate_ordinal


def _current_product_id(
    snapshot: ConversationSnapshot | None,
) -> int | None:
    if snapshot is None:
        return None
    if (
        snapshot.product_slot is not None
        and snapshot.product_slot.focused_product_id is not None
    ):
        return snapshot.product_slot.focused_product_id
    if (
        snapshot.active_focus is not None
        and snapshot.active_focus.slot == "image"
        and isinstance(snapshot.active_focus.object_id, int)
    ):
        return snapshot.active_focus.object_id
    return None


def _pending_turn(snapshot: ConversationSnapshot | None):
    if (
        snapshot is not None
        and isinstance(snapshot.reply_slot, PendingReplySlot)
    ):
        return snapshot.reply_slot.value
    return None


def _clarification(snapshot: ConversationSnapshot | None):
    if (
        snapshot is not None
        and isinstance(snapshot.reply_slot, PendingReplySlot)
    ):
        return ClarificationProgress(
            gap=snapshot.reply_slot.value.gap,
            attempts=snapshot.reply_slot.value.attempts,
        )
    if (
        snapshot is not None
        and isinstance(
            snapshot.reply_slot,
            PendingClarificationSlot,
        )
    ):
        return snapshot.reply_slot.value
    return None


def _relative_baseline_product_id(
    snapshot: ConversationSnapshot | None,
    requirement: RelativeRequirement,
) -> int | None:
    if snapshot is None:
        return None
    if requirement.baseline.kind == "candidate_ordinal":
        ordinal = requirement.baseline.ordinal
    elif requirement.baseline.kind == "current_item":
        ordinal = _focused_candidate_ordinal(snapshot)
    else:
        return None
    candidates = _candidate_batch(snapshot)
    if ordinal is None or ordinal > len(candidates):
        return None
    return candidates[ordinal - 1].product_id


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
    numeric_relation_predicates = {
        "consumer_agrees",
        "consumer_self_report_change",
        "consumer_self_report_result",
        "consumer_self_reported_change",
    }
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
                and any(
                    relation.predicate
                    in numeric_relation_predicates
                    for relation in item.evidence.relations
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
        public_text = point.plain_meaning.strip()
        body = (
            public_text
            if conditions in public_text
            else f"{conditions}，{public_text}"
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


def _approved_product_evidence_facts(
    packet: EvidencePacket,
    *,
    product_names: dict[int, str],
) -> tuple[ApprovedSoftFact, ...]:
    attribution_by_label = {
        "consumer_self_report": "consumer_report",
        "merchant_cited_test": "merchant_claim",
        "safety_transcript": "merchant_claim",
        "merchant_claim": "merchant_claim",
        "faq": "merchant_claim",
        "brand_research": "merchant_claim",
        "packaging_information": "verified_fact",
        "usage": "verified_fact",
        "product_specification": "verified_fact",
        "unclassified": "verified_fact",
    }
    return tuple(
        ApprovedSoftFact(
            fact_id=f"evidence:{item.evidence.evidence_id}",
            product_id=item.evidence.product_id,
            field_key=_product_evidence_field_key(
                item.evidence.management_label
            ),
            plain_meaning=render_product_evidence_fact(
                item.evidence,
                product_name=product_names.get(
                    item.evidence.product_id,
                    f"商品{item.evidence.product_id}",
                ),
            ),
            attribution=attribution_by_label[
                item.evidence.management_label
            ],
            source_refs=(item.evidence.source.source_locator,),
        )
        for item in packet.selected
    )


def _product_evidence_field_key(management_label: str) -> str:
    return {
        "merchant_claim": "brand_main",
        "brand_research": "brand_main",
        "usage": "usage",
        "product_specification": "net_content",
        "packaging_information": "packaging_information",
        "faq": "faq",
        "consumer_self_report": "consumer_report",
        "merchant_cited_test": "merchant_test",
        "safety_transcript": "safety_information",
        "unclassified": "product_information",
    }[management_label]


def _approved_merchant_claim_facts(
    claims: Sequence[MerchantClaimEvidenceData],
) -> tuple[ApprovedSoftFact, ...]:
    return tuple(
        ApprovedSoftFact(
            fact_id=f"merchant:{claim.claim_id}",
            product_id=claim.product_id,
            field_key=claim.field_key,
            plain_meaning=(
                claim.normalized_value or claim.display_claim
            ),
            attribution="merchant_claim",
            source_refs=(claim.source_locator,),
        )
        for claim in claims
        if claim.claim_scope == "ordinary"
    )


def _approved_review_summary_facts(
    summaries: Sequence[ReviewSummaryResult],
) -> tuple[ApprovedSoftFact, ...]:
    return tuple(
        ApprovedSoftFact(
            fact_id=summary.synthesis.claim_id,
            product_id=summary.product_id,
            field_key="consumer_report",
            plain_meaning=summary.synthesis.text,
            attribution="consumer_report",
            source_refs=tuple(
                fact.provenance.source_locator
                for fact in summary.source_facts
            ),
        )
        for summary in summaries
    )


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


def _image_lane_mutation(
    execution_input: ProcessorExecutionInput,
) -> LaneMutation[ImageLaneState]:
    routing_evidence = execution_input.routing_evidence.image
    if (
        routing_evidence is None
        or type(routing_evidence) is PersistedImageRoutingEvidence
    ):
        return LaneMutation[ImageLaneState](action="preserve")
    try:
        validate_confirmed_image_batch(
            routing_evidence.confirmed_products
        )
    except ValueError:
        return LaneMutation[ImageLaneState](action="preserve")
    return LaneMutation[ImageLaneState](
        action="replace",
        value=ImageLaneState(
            confirmed_products=routing_evidence.confirmed_products,
            mutation_source=(
                "current_upload"
                if type(routing_evidence) is ImageRoutingEvidence
                else None
            ),
        ),
    )


def _execution_audit_events(
    execution_input: ProcessorExecutionInput,
    audit_events: Sequence[SseEvent],
) -> tuple[SseEvent, ...]:
    routing_evidence = execution_input.routing_evidence.image
    if (
        routing_evidence is None
        or type(routing_evidence) is PersistedImageRoutingEvidence
    ):
        return tuple(audit_events)
    return (
        StageEvent(
            data=StageData(
                stage="image_observation",
                summary=(
                    "正在确认图片中的商品信息。"
                    if routing_evidence.image_count == 1
                    else (
                        "正在确认 "
                        f"{routing_evidence.image_count} 张图片中的商品。"
                    )
                ),
            )
        ),
        *image_observation_events(routing_evidence.observations),
        *audit_events,
        image_citations_event(
            observations=routing_evidence.observations,
            product_ids=tuple(
                binding.product_id
                for binding in execution_input.decision.product_bindings
            ),
        ),
    )
