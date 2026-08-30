from __future__ import annotations

from typing import Literal, Protocol

from app.guide.application.execution_contracts import (
    AuthorizedImageInput,
    ClarificationLaneState,
    ClarificationTerminal,
    ConversationStateDelta,
    ErrorTerminal,
    ExecutionResult,
    ImageEvidenceRequest,
    ImageRoutingEvidence,
    ImageLaneState,
    LaneMutation,
    PersistedImageRoutingEvidence,
    PresentationTerminal,
    ProcessorExecutionInput,
    notify_processor_entry,
)
from app.guide.application.image_compare_gate import TwoImageCompareGate
from app.guide.application.image_bundle_service import (
    ImageBundleService,
)
from app.guide.application.image_bundle_state import ImageBundlePayload
from app.guide.application.image_reference_resolution import (
    MultiImageContextResult,
    build_multi_image_context,
)
from app.guide.application.multi_image_compare_gate import (
    ThreeToFourImageCompareGate,
)
from app.guide.application.recommendation_terminal import (
    require_fit_presentation_facts,
)
from app.guide.decision.image_compare import (
    ImageCompareDecisionFoundation,
)
from app.guide.decision.image_compare_contracts import (
    ImageCompareDecisionResult,
)
from app.guide.decision.multi_image_compare import (
    MultiImageCompareDecisionFoundation,
)
from app.guide.decision.multi_image_compare_contracts import (
    MultiImageCompareDecisionResult,
)
from app.guide.decision.ports import DecisionFactPort
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    PendingClarificationSlot,
)
from app.guide.feedback.focus_state import ConfirmedImageProductRef
from app.guide.intent.responsibility_matrix import (
    Responsibility,
)
from app.guide.intent.unified_turn_router import (
    UnifiedRouteDecision,
)
from app.guide.presentation.card_display import (
    comparison_card_display,
    recommendation_card_display,
    single_product_card_display,
)
from app.guide.presentation.contracts import (
    CardDisplayContract,
    ProductCard,
)
from app.guide.presentation.copywriter_contracts import PresentationMode
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
)
from app.guide.presentation.sse_events import (
    AnswerContractData,
    AnswerContractEvent,
    CardDisplayContractEvent,
    ClarifyData,
    DecisionProcessData,
    DecisionProcessEvent,
    ErrorData,
    ErrorEvent,
    ImageComparisonData,
    ImageComparisonPriceFactData,
    ImageComparisonReferenceData,
    IntentData,
    IntentEvent,
    ProductsData,
    ProductsEvent,
    PresentationContractEvent,
    SseEvent,
    StageData,
    StageEvent,
    image_citations_event,
    image_observation_events,
)
from app.guide.retrieval.category_taxonomy import (
    canonical_categories_for,
)
from app.guide.retrieval.image_contracts import ImageRetrievalRequest
from app.guide.retrieval.ports import (
    CategoryCatalogPort,
)
from app.guide.retrieval.review_reader import ReviewEvidenceReader
from app.guide.retrieval.review_summary import build_review_summary
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.image_contracts import (
    IdentityState,
    ImageIdentityObservation,
    ImageIdentityTrace,
)
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.turn_meaning_contracts import RecommendationMode


class ImageIdentityObserverPort(Protocol):
    def observe(
        self,
        request: ImageRetrievalRequest,
    ) -> ImageIdentityObservation: ...

    def observe_with_trace(
        self,
        request: ImageRetrievalRequest,
    ) -> tuple[ImageIdentityObservation, ImageIdentityTrace]: ...


class ImageRoutingEvidenceCollector:
    def __init__(
        self,
        *,
        image_bundles: ImageBundleService,
        identity_observer: ImageIdentityObserverPort,
        category_catalog: CategoryCatalogPort,
        max_results: int = 10,
    ) -> None:
        if not 2 <= max_results <= 100:
            raise ValueError("max_results must be between 2 and 100")
        self._image_bundles = image_bundles
        self._identity_observer = identity_observer
        self._category_catalog = category_catalog
        self._max_results = max_results

    def authorize_routing_request(
        self,
        request: ImageEvidenceRequest,
    ) -> AuthorizedImageInput:
        if type(request) is not ImageEvidenceRequest:
            raise TypeError(
                "request must be an exact ImageEvidenceRequest"
            )
        bundle, payloads = self._image_bundles.authorize_bundle_payloads(
            bundle_id=request.bundle_id,
            version=request.bundle_version,
            session_id=request.turn_identity.session_id,
            owner_token=request.bundle_token,
        )
        return AuthorizedImageInput(
            bundle=bundle,
            payloads=payloads,
        )

    def prepare_routing_evidence(
        self,
        authorized_input: AuthorizedImageInput,
    ) -> ImageRoutingEvidence:
        if type(authorized_input) is not AuthorizedImageInput:
            raise TypeError(
                "authorized_input must be an exact AuthorizedImageInput"
            )
        bundle = authorized_input.bundle
        payloads = authorized_input.payloads
        observations = tuple(
            self._observe(payload)
            for payload in payloads
        )
        anchor_topic = None
        if len(observations) == 1:
            observation = observations[0]
            if (
                observation.identity_state is IdentityState.CONFIRMED
                and observation.confirmed_product_id is not None
            ):
                category_record = next(
                    (
                        record
                        for record
                        in self._category_catalog.iter_category_records()
                        if (
                            record.product_id
                            == observation.confirmed_product_id
                        )
                    ),
                    None,
                )
                anchor_topic = _topic_for_record(category_record)
        return ImageRoutingEvidence(
            bundle=bundle,
            payloads=payloads,
            observations=observations,
            anchor_topic=anchor_topic,
        )

    def trace_identity_request(
        self,
        request: ImageRetrievalRequest,
    ) -> tuple[ImageIdentityObservation, ImageIdentityTrace]:
        return self._identity_observer.observe_with_trace(request)

    def _observe(
        self,
        payload: ImageBundlePayload,
    ) -> ImageIdentityObservation:
        return self._identity_observer.observe(
            ImageRetrievalRequest(
                image_id=payload.image_id,
                content_sha256=payload.content_sha256,
                content=payload.content,
                max_results=self._max_results,
            )
        )


class ImageRecommendationOrchestrator:
    def __init__(
        self,
        *,
        category_catalog: CategoryCatalogPort,
        decision_facts: DecisionFactPort,
        presentation_facts: PresentationFactPort,
        review_evidence: ReviewEvidenceReader | None = None,
        presentation_compiler: PresentationCompiler | None = None,
        max_results: int = 10,
        execution_observer=None,
    ) -> None:
        if not 2 <= max_results <= 100:
            raise ValueError("max_results must be between 2 and 100")
        self._category_catalog = category_catalog
        self._decision_facts = decision_facts
        self._presentation_facts = presentation_facts
        self._review_evidence = review_evidence
        self._presentation_compiler = (
            presentation_compiler
            if presentation_compiler is not None
            else PresentationCompiler(copywriter=None)
        )
        self._two_image_compare = TwoImageCompareGate(
            category_catalog=category_catalog,
            decision_facts=decision_facts,
            decision=ImageCompareDecisionFoundation(),
        )
        self._multi_image_compare = ThreeToFourImageCompareGate(
            category_catalog=category_catalog,
            decision_facts=decision_facts,
            decision=MultiImageCompareDecisionFoundation(),
        )
        self._max_results = max_results
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
        snapshot = execution_input.current_snapshot
        route_decision = execution_input.decision
        evidence = execution_input.routing_evidence
        routing_evidence = evidence.image
        if routing_evidence is None:
            raise ValueError("image execution requires image evidence")
        profile_owner = evidence.profile_owner
        query = evidence.query.value
        if (
            snapshot is not None
            and type(snapshot) is not ConversationSnapshot
        ):
            raise TypeError(
                "snapshot must be a ConversationSnapshot or None"
            )
        if type(route_decision) is not UnifiedRouteDecision:
            raise TypeError(
                "route_decision must be UnifiedRouteDecision"
            )
        if route_decision.processor not in {
            "image_identity",
            "image_comparison",
        }:
            raise ValueError(
                "image processor cannot execute "
                f"{route_decision.processor}"
            )
        if type(routing_evidence) not in {
            ImageRoutingEvidence,
            PersistedImageRoutingEvidence,
        }:
            raise TypeError(
                "routing_evidence must be current or persisted image "
                "evidence"
            )
        observations = (
            routing_evidence.observations
            if type(routing_evidence) is ImageRoutingEvidence
            else ()
        )
        audit_events: list[SseEvent] = (
            [
                StageEvent(
                    data=StageData(
                        stage="image_observation",
                        summary=(
                            "正在确认图片中的商品信息。"
                            if len(observations) == 1
                            else (
                                f"正在确认 {len(observations)} "
                                "张图片中的商品。"
                            )
                        ),
                    )
                ),
                *image_observation_events(observations),
            ]
            if observations
            else []
        )
        if any(
            observation.identity_state
            is IdentityState.VISUAL_UNAVAILABLE
            for observation in observations
        ):
            return ExecutionResult(
                decision=route_decision,
                state_delta=ConversationStateDelta(
                    profile_owner=profile_owner,
                ),
                terminal=ErrorTerminal(
                    data=_error_event(
                        "IMAGE_RETRIEVAL_UNAVAILABLE"
                    ).data
                ),
                audit_events=tuple(audit_events),
            )
        if any(
            observation.identity_state is not IdentityState.CONFIRMED
            or observation.confirmed_product_id is None
            for observation in observations
        ):
            return ExecutionResult(
                decision=route_decision,
                state_delta=ConversationStateDelta(
                    profile_owner=profile_owner,
                ),
                terminal=ErrorTerminal(
                    data=_error_event(
                        "IMAGE_IDENTITY_UNCONFIRMED"
                    ).data
                ),
                audit_events=tuple(audit_events),
            )
        if route_decision.processor == "image_comparison":
            return self._execute_image_comparison(
                execution_input,
                routing_evidence=routing_evidence,
                route_decision=route_decision,
                audit_events=audit_events,
                snapshot=snapshot,
            )
        if type(routing_evidence) is PersistedImageRoutingEvidence:
            return ExecutionResult(
                decision=route_decision,
                state_delta=ConversationStateDelta(
                    profile_owner=profile_owner,
                ),
                terminal=ErrorTerminal(
                    data=_error_event(
                        "IMAGE_IDENTITY_UNCONFIRMED"
                    ).data
                ),
                audit_events=tuple(audit_events),
            )
        if route_decision.processor != "image_identity":
            raise NotImplementedError(
                f"{route_decision.processor} image execution "
                "is not migrated"
            )

        product_ids = tuple(
            dict.fromkeys(
                binding.product_id
                for binding in route_decision.product_bindings
            )
        )
        cards = self._cards_for_product_ids(product_ids)
        card_display = (
            single_product_card_display(cards[0])
            if len(cards) == 1
            else recommendation_card_display(cards)
        )
        presentation = self._presentation_event(
            mode="image_identity",
            route_decision=route_decision,
            user_need_summary=query,
            winner_status="NOT_APPLICABLE",
            card_display=card_display,
            cards=cards,
        ).data
        audit_events.extend(
            [
                IntentEvent(
                    data=IntentData(
                        mode=route_decision.public_intent_mode
                    )
                ),
                StageEvent(
                    data=StageData(
                        stage="decision",
                        summary="已经确认图片中的商品。",
                    )
                ),
                AnswerContractEvent(
                    data=AnswerContractData(
                        product_count=len(cards),
                        winner_status="NOT_APPLICABLE",
                        has_unknown_skin=True,
                    )
                ),
                CardDisplayContractEvent(data=card_display),
                ProductsEvent(data=ProductsData(cards=cards)),
                image_citations_event(
                    observations=observations,
                    product_ids=tuple(
                        card.product_id for card in cards
                    ),
                ),
            ]
        )
        return ExecutionResult(
            decision=route_decision,
            state_delta=ConversationStateDelta(
                profile_owner=profile_owner,
                image=LaneMutation[ImageLaneState](
                    action="replace",
                    value=ImageLaneState(
                        confirmed_products=(
                            routing_evidence.confirmed_products
                        ),
                        mutation_source="current_upload",
                    ),
                ),
                clarification=LaneMutation[ClarificationLaneState](
                    action="clear",
                    reason="resolved by image identity",
                ),
            ),
            terminal=PresentationTerminal(data=presentation),
            audit_events=tuple(audit_events),
        )

    def _execute_image_comparison(
        self,
        execution_input: ProcessorExecutionInput,
        *,
        routing_evidence: (
            ImageRoutingEvidence | PersistedImageRoutingEvidence
        ),
        route_decision: UnifiedRouteDecision,
        audit_events: list[SseEvent],
        snapshot: ConversationSnapshot | None,
    ) -> ExecutionResult:
        evidence = execution_input.routing_evidence
        profile_owner = evidence.profile_owner
        query = evidence.query.value
        observations = (
            routing_evidence.observations
            if type(routing_evidence) is ImageRoutingEvidence
            else ()
        )
        context_result = (
            _persisted_comparison_context(routing_evidence)
            if type(routing_evidence)
            is PersistedImageRoutingEvidence
            else build_multi_image_context(
                mode="compare",
                bundle=routing_evidence.bundle,
                identity_observations=observations,
            )
        )
        if context_result.kind == "clarification":
            clarification = ClarifyData(
                question=context_result.message,
                clarification_code=ClarificationCode.REFERENCE,
            )
            return self._clarification_execution_result(
                route_decision=route_decision,
                snapshot=snapshot,
                clarification=clarification,
                audit_events=(
                    *audit_events,
                    IntentEvent(
                        data=IntentData(
                            mode=route_decision.public_intent_mode
                        )
                    ),
                ),
                profile_owner=profile_owner,
            )
        if context_result.kind != "ready":
            return ExecutionResult(
                decision=route_decision,
                state_delta=ConversationStateDelta(
                    profile_owner=profile_owner,
                ),
                terminal=ErrorTerminal(
                    data=_error_event("GUIDE_INTERNAL_ERROR").data
                ),
                audit_events=tuple(audit_events),
            )
        assert context_result.context is not None
        comparison_count = routing_evidence.image_count
        if comparison_count == 2:
            preparation = self._two_image_compare.prepare(
                context_result.context
            )
        elif type(routing_evidence) is PersistedImageRoutingEvidence:
            preparation = self._multi_image_compare.prepare_confirmed_context(
                context_result.context
            )
        else:
            preparation = self._multi_image_compare.prepare(
                context_result.context,
                authorized_bundle=routing_evidence.bundle,
            )
        if preparation.kind == "clarification":
            clarification = ClarifyData(
                question=preparation.message,
                clarification_code=(
                    ClarificationCode.TOPIC
                    if preparation.code
                    in {
                        "canonical_category_unavailable",
                        "cross_category_products",
                    }
                    else ClarificationCode.REFERENCE
                ),
            )
            return self._clarification_execution_result(
                route_decision=route_decision,
                snapshot=snapshot,
                clarification=clarification,
                audit_events=(
                    *audit_events,
                    IntentEvent(
                        data=IntentData(
                            mode=route_decision.public_intent_mode
                        )
                    ),
                ),
                image_products=(
                    routing_evidence.confirmed_products
                    if type(routing_evidence) is ImageRoutingEvidence
                    else ()
                ),
                profile_owner=profile_owner,
            )
        if preparation.kind != "ready":
            return ExecutionResult(
                decision=route_decision,
                state_delta=ConversationStateDelta(
                    profile_owner=profile_owner,
                ),
                terminal=ErrorTerminal(
                    data=_error_event("GUIDE_INTERNAL_ERROR").data
                ),
                audit_events=tuple(audit_events),
            )

        result = preparation.decision_result
        if result is None:
            raise RuntimeError(
                "ready image comparison requires decision result"
            )
        cards = self._comparison_cards(result)
        comparison_data = _comparison_data(
            result,
            context_source=(
                "confirmed_session"
                if type(routing_evidence)
                is PersistedImageRoutingEvidence
                else "current_upload"
            ),
        )
        card_display = comparison_card_display(cards)
        presentation = self._presentation_event(
            mode="comparison",
            route_decision=route_decision,
            user_need_summary=query,
            winner_status=result.outcome.status,
            card_display=card_display,
            cards=cards,
            winner_product_id=(
                result.outcome.winner_reference.product_id
                if result.outcome.winner_reference is not None
                else None
            ),
            winner_tie_reason=result.outcome.tie_reason,
        ).data
        if presentation.winner is None:
            raise ValueError(
                "image comparison presentation requires winner outcome"
            )
        public_winner_status = {
            "selected": "winner",
            "tied": "tie",
            "insufficient": "insufficient_evidence",
            "not_applicable": "insufficient_evidence",
        }[presentation.winner.status]
        if public_winner_status != comparison_data.status:
            comparison_data = comparison_data.model_copy(
                update={
                    "status": public_winner_status,
                    "winner_reference": None,
                    "tie_reason": None,
                },
                deep=True,
            )
        comparison_events: list[SseEvent] = [
                IntentEvent(
                    data=IntentData(
                        mode=route_decision.public_intent_mode
                    )
                ),
                StageEvent(
                    data=StageData(
                        stage="decision",
                        summary=(
                            "正在比较两款商品的参考价格。"
                            if comparison_count == 2
                            else (
                                f"正在比较这 {comparison_count} 款商品"
                                "的参考价格。"
                            )
                        ),
                    )
                ),
                DecisionProcessEvent(
                    data=DecisionProcessData(
                        ordered_product_ids=list(
                            result.ordered_product_ids
                        ),
                        winner_status=public_winner_status,
                        evidence_refs=list(
                            result.outcome.evidence_refs
                        ),
                        comparison_data=comparison_data,
                    )
                ),
                AnswerContractEvent(
                    data=AnswerContractData(
                        product_count=comparison_count,
                        winner_status=public_winner_status,
                        has_unknown_skin=True,
                    )
                ),
                CardDisplayContractEvent(data=card_display),
                ProductsEvent(data=ProductsData(cards=cards)),
            ]
        if observations:
            comparison_events.append(
                image_citations_event(
                    observations=observations,
                    product_ids=tuple(
                        card.product_id for card in cards
                    ),
                )
            )
        audit_events.extend(comparison_events)
        return ExecutionResult(
            decision=route_decision,
            state_delta=ConversationStateDelta(
                profile_owner=profile_owner,
                image=(
                    LaneMutation[ImageLaneState](
                        action="replace",
                        value=ImageLaneState(
                            confirmed_products=(
                                routing_evidence.confirmed_products
                            ),
                            mutation_source="current_upload",
                        ),
                    )
                    if type(routing_evidence) is ImageRoutingEvidence
                    else LaneMutation[ImageLaneState](
                        action="preserve",
                    )
                ),
                clarification=LaneMutation[ClarificationLaneState](
                    action="clear",
                    reason="resolved by image comparison",
                ),
            ),
            terminal=PresentationTerminal(data=presentation),
            audit_events=tuple(audit_events),
        )

    @staticmethod
    def _clarification_execution_result(
        *,
        route_decision: UnifiedRouteDecision,
        snapshot: ConversationSnapshot | None,
        clarification: ClarifyData,
        audit_events: tuple[SseEvent, ...],
        profile_owner,
        image_products: tuple[ConfirmedImageProductRef, ...] = (),
    ) -> ExecutionResult:
        previous = (
            snapshot.reply_slot.value
            if snapshot is not None
            and isinstance(
                snapshot.reply_slot,
                PendingClarificationSlot,
            )
            else None
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
        return ExecutionResult(
            decision=route_decision,
            state_delta=ConversationStateDelta(
                profile_owner=profile_owner,
                image=(
                    LaneMutation[ImageLaneState](
                        action="replace",
                        value=ImageLaneState(
                            confirmed_products=image_products,
                            mutation_source="current_upload",
                        ),
                    )
                    if image_products
                    else LaneMutation[ImageLaneState](
                        action="preserve"
                    )
                ),
                clarification=LaneMutation[
                    ClarificationLaneState
                ](
                    action="replace",
                    value=ClarificationLaneState(
                        progress=ClarificationProgress(
                            gap=clarification.clarification_code,
                            attempts=attempts,
                        ),
                    ),
                ),
            ),
            terminal=ClarificationTerminal(data=clarification),
            audit_events=audit_events,
        )

    def _comparison_cards(
        self,
        result: ImageCompareDecisionResult
        | MultiImageCompareDecisionResult,
    ) -> list[ProductCard]:
        return self._cards_for_product_ids(result.ordered_product_ids)

    def _cards_for_product_ids(
        self,
        product_ids,
    ) -> list[ProductCard]:
        cards: list[ProductCard] = []
        for product_id in dict.fromkeys(product_ids):
            facts = self._presentation_facts.get_presentation_facts(
                product_id
            )
            cards.append(
                build_product_card(
                    facts,
                    skin_match="unknown",
                )
            )
        return cards

    def _presentation_event(
        self,
        *,
        mode: PresentationMode,
        route_decision: UnifiedRouteDecision,
        user_need_summary: str,
        winner_status: str | None,
        recommendation_mode: RecommendationMode | None = None,
        card_display: CardDisplayContract,
        cards: tuple[ProductCard, ...] | list[ProductCard],
        winner_product_id: int | None = None,
        winner_tie_reason: str | None = None,
    ) -> PresentationContractEvent:
        responsibility = route_decision.responsibility
        if responsibility is Responsibility.RECOMMENDATION:
            if recommendation_mode == "explore":
                winner_status = "NOT_APPLICABLE"
                winner_product_id = None
                winner_tie_reason = None
        review_summaries = (
            tuple(
                summary
                for card in cards
                if (
                    summary := build_review_summary(
                        self._review_evidence.read(
                            product_id=card.product_id
                        )
                    )
                ) is not None
            )
            if self._review_evidence is not None
            else ()
        )
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
            requested_dimensions=(
                route_decision.task_plan
                .requested_comparison_dimensions
            ),
            selection_slots=(),
            concept_slots=(),
            merchant_claims=(),
            review_summaries=review_summaries,
            pitfalls=(),
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
                )
            )
        )

def _topic_for_record(record) -> TopicCode | None:
    if (
        record is None
        or record.state != "known"
        or record.value is None
    ):
        return None
    return next(
        (
            topic
            for topic in TopicCode
            if record.value in canonical_categories_for(topic)
        ),
        None,
    )


def _persisted_comparison_context(
    evidence: PersistedImageRoutingEvidence,
) -> MultiImageContextResult:
    if not evidence.source_identity_complete:
        return MultiImageContextResult(
            kind="clarification",
            code="no_current_bundle",
            message="请重新上传要比较的图片后再继续比较。",
        )
    bundle_ids = {
        item.source_bundle_id
        for item in evidence.confirmed_products
    }
    if len(bundle_ids) != 1 or None in bundle_ids:
        return MultiImageContextResult(
            kind="error",
            code="identity_record_bundle_mismatch",
            message="已确认图片的来源批次不一致。",
        )
    bundle_id = next(iter(bundle_ids))
    assert bundle_id is not None
    return MultiImageContextResult(
        kind="ready",
        context=MultiImageTaskContext(
            mode="compare",
            bundle_id=bundle_id,
            references=[
                ImageTaskReference(
                    image_id=item.source_image_id,
                    ordinal=item.image_ordinal,
                    identity_state=IdentityState.CONFIRMED,
                    confirmed_product_id=item.product_id,
                )
                for item in evidence.confirmed_products
                if item.source_image_id is not None
            ],
        ),
    )


def _comparison_data(
    result: ImageCompareDecisionResult
    | MultiImageCompareDecisionResult,
    *,
    context_source: Literal[
        "current_upload",
        "confirmed_session",
    ] = "current_upload",
) -> ImageComparisonData:
    references = [
        _comparison_reference(reference)
        for reference in result.references
    ]
    winner_reference = (
        _comparison_reference(result.outcome.winner_reference)
        if result.outcome.winner_reference is not None
        else None
    )
    return ImageComparisonData(
        context_source=context_source,
        status=result.outcome.status,
        references=references,
        winner_reference=winner_reference,
        tie_reason=result.outcome.tie_reason,
        comparison_dimensions=list(result.comparison_dimensions),
        evidence_refs=list(result.outcome.evidence_refs),
        evaluated_price_facts=[
            ImageComparisonPriceFactData(
                reference=_comparison_reference(fact.reference),
                state=fact.state.value,
                value=fact.value,
                source_refs=list(fact.source_refs),
            )
            for fact in result.outcome.evaluated_price_facts
        ],
    )


def _comparison_reference(
    reference,
) -> ImageComparisonReferenceData:
    return ImageComparisonReferenceData(
        ordinal=reference.ordinal,
        image_id=reference.image_id,
        product_id=reference.product_id,
    )


def _error_event(code: str) -> ErrorEvent:
    messages = {
        "GUIDE_INTERNAL_ERROR": "推荐暂时不可用，请稍后重试。",
        "IMAGE_BUNDLE_UNAVAILABLE": "图片引用不可用，请重新上传。",
        "IMAGE_SINGLE_REQUIRED": "当前单图识别一次只支持 1 张图片。",
        "IMAGE_COUNT_UNSUPPORTED": (
            "当前只支持 1 到 4 张图片的识别、适配或商品比较。"
        ),
        "IMAGE_RETRIEVAL_UNAVAILABLE": "图片检索暂时不可用，请稍后重试。",
        "IMAGE_IDENTITY_UNCONFIRMED": (
            "图片信息还不足以确认具体商品，请换一张更清晰的正面图。"
        ),
        "IMAGE_CATEGORY_UNSUPPORTED": (
            "当前图片商品不在已开放的防晒或修护精华范围内。"
        ),
    }
    return ErrorEvent(data=ErrorData(code=code, message=messages[code]))
