from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType

from app.guide.application.contracts import UserTurn
from app.guide.application.conversation_state_reducer import (
    reduce_conversation_state,
)
from app.guide.application.dynamic_consultation import (
    prepare_dynamic_consultation_evidence,
)
from app.guide.application.execution_contracts import (
    ErrorTerminal,
    ExecutionResult,
    ImageEvidenceRequest,
    ImageRoutingEvidence,
    OpaqueRetrievalQuery,
    PersistedImageRoutingEvidence,
    PreRoutingEvidence,
    PresentationTerminal,
    ProcessorExecutionInput,
    materialize_execution_envelope,
)
from app.guide.application.image_bundle_service import (
    ImageBundleServiceError,
)
from app.guide.application.pending_turn import (
    build_pending_turn,
    resolve_semantic_pending_reply,
    resume_pending_recommendation,
)
from app.guide.application.product_evidence_answer import (
    resolve_product_knowledge_dimensions,
)
from app.guide.application.product_resolution import (
    PreRoutingProductResolution,
)
from app.guide.application.public_event_envelope import (
    materialize_error_frames,
)
from app.guide.application.scenario_inputs import build_scenario_inputs
from app.guide.application.session_profile_resolution import (
    resolve_session_profile_context,
)
from app.guide.application.task_plan_enrichment import (
    PreRoutingTaskPlan,
    PreRoutingTaskPlanEnricher,
    promote_single_image_similarity_task,
)
from app.guide.application.query_context import (
    apply_session_profile_to_task,
)
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    PendingReplySlot,
)
from app.guide.feedback.focus_state import ConfirmedImageProductRef
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStatePort,
)
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.intent.responsibility_matrix import (
    ProcessorKind,
)
from app.guide.intent.contracts import TaskPlan, revalidate_task_plan
from app.guide.intent.task_planning import plan_task
from app.guide.intent.transition_planning import (
    plan_code_owned_transitions,
)
from app.guide.intent.unified_turn_router import (
    UnifiedRouteDecision,
    reconcile_product_resolution_issue,
    route_unified_turn,
)
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
)
from app.guide.retrieval.product_evidence_retrieval import (
    prepare_evidence_search,
)
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.contracts import (
    StructuredUnderstanding,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.ports import UnifiedUnderstandingPort
from app.guide.understanding.safety_admission import (
    admit_safety_signal,
)
from app.guide.understanding.scenario_parsing import parse_scenarios
from app.guide.understanding.typed_image_action import (
    turn_meaning_for_image_action,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


class UnifiedUnderstandingAdapter:
    def __init__(self, understanding) -> None:
        if not callable(getattr(understanding, "translate", None)):
            raise TypeError("understanding must expose translate")
        self._understanding = understanding

    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> TurnMeaning:
        meaning = self._understanding.translate(
            message,
            context=context,
        )
        if type(meaning) is not TurnMeaning:
            raise TypeError("translator must return TurnMeaning")
        return meaning

    @property
    def concept_catalog(self):
        return getattr(self._understanding, "concept_catalog", None)


class UnifiedGuideFlow:
    def __init__(
        self,
        *,
        understanding: UnifiedUnderstandingPort,
        product_resolution_collector,
        text_processor,
        consultation_processor,
        image_processor=None,
        image_evidence_collector=None,
        conversation_state: ConversationStatePort,
        task_plan_enricher: PreRoutingTaskPlanEnricher | None = None,
        observer=None,
    ) -> None:
        if not callable(getattr(understanding, "translate", None)):
            raise TypeError("understanding must expose translate")
        if not callable(
            getattr(product_resolution_collector, "collect", None)
        ):
            raise TypeError(
                "product resolution collector must expose collect"
            )
        if not callable(
            getattr(text_processor, "execute", None)
        ):
            raise TypeError("text processor must expose execute")
        if not callable(
            getattr(consultation_processor, "execute", None)
        ):
            raise TypeError("consultation processor must expose execute")
        if image_processor is not None and not callable(
            getattr(image_processor, "execute", None)
        ):
            raise TypeError("image processor must expose execute")
        if (
            image_evidence_collector is not None
            and (
                not callable(
                    getattr(
                        image_evidence_collector,
                        "authorize_routing_request",
                        None,
                    )
                )
                or not callable(
                    getattr(
                        image_evidence_collector,
                        "prepare_routing_evidence",
                        None,
                    )
                )
            )
        ):
            raise TypeError(
                "image evidence collector must expose authorization "
                "and evidence preparation"
            )
        if (image_processor is None) != (
            image_evidence_collector is None
        ):
            raise TypeError(
                "image processor and evidence collector must be "
                "configured together"
            )
        if (
            image_processor is not None
            and image_processor is image_evidence_collector
        ):
            raise TypeError(
                "image processor and evidence collector must be distinct"
            )
        self._understanding = understanding
        self._product_resolution_collector = (
            product_resolution_collector
        )
        self._text_processor = text_processor
        self._consultation_processor = consultation_processor
        self._processor_registry: Mapping[ProcessorKind, object] = (
            MappingProxyType(
                {
                    "recommendation": text_processor,
                    "comparison": text_processor,
                    "product_knowledge": text_processor,
                    "general_knowledge": text_processor,
                    "clarification": text_processor,
                    "consultation": consultation_processor,
                    "safety_escalation": consultation_processor,
                    "image_identity": image_processor,
                    "image_comparison": image_processor,
                }
            )
            if image_processor is not None
            else MappingProxyType(
                {
                    "recommendation": text_processor,
                    "comparison": text_processor,
                    "product_knowledge": text_processor,
                    "general_knowledge": text_processor,
                    "clarification": text_processor,
                    "consultation": consultation_processor,
                    "safety_escalation": consultation_processor,
                }
            )
        )
        self._image_evidence_collector = image_evidence_collector
        self._conversation_state = conversation_state
        self._task_plan_enricher = task_plan_enricher
        self._observer = observer

    def stream(self, turn: UserTurn) -> Iterator[bytes]:
        try:
            yield from self._stream_unchecked(turn)
        except Exception as error:
            yield from self._failure_frames(turn, error)

    def _stream_unchecked(
        self,
        turn: UserTurn,
    ) -> Iterator[bytes]:
        if type(turn) is not UserTurn:
            raise TypeError("turn must be an exact UserTurn")
        snapshot = self._conversation_state.load(turn.session_id)
        self._validate_owner(snapshot, turn)
        profile_context = resolve_session_profile_context(snapshot)
        authorized_image_input = None
        if turn.image_bundle_id is not None:
            image_evidence_collector = self._image_evidence_collector
            if image_evidence_collector is None:
                raise ValueError("image evidence collector is unavailable")
            authorized_image_input = (
                image_evidence_collector.authorize_routing_request(
                    ImageEvidenceRequest(
                        turn_identity=turn.identity,
                        bundle_id=turn.image_bundle_id,
                        bundle_version=turn.image_bundle_version,
                        bundle_token=turn.image_bundle_token,
                    )
                )
            )
            image_count = authorized_image_input.image_count
            if type(image_count) is not int or not 0 <= image_count <= 4:
                raise ValueError(
                    "semantic image count must be between zero and four"
                )
        else:
            image_count = 0
        context = resolve_semantic_context(
            conversation_version=turn.conversation_version,
            snapshot=snapshot,
            profile_context=profile_context,
            image_bundle=(
                authorized_image_input.bundle
                if authorized_image_input is not None
                else None
            ),
        )
        if turn.image_action is None:
            meaning = self._understanding.translate(
                turn.message,
                context=context,
            )
            meaning_source = "provider"
        else:
            meaning = turn_meaning_for_image_action(
                action=turn.image_action,
                image_count=image_count,
                question_summary=turn.question_summary,
            )
            meaning_source = "typed_image_action"
        self._observe(
            "turn_meaning_supplied",
            turn=turn,
            meaning=meaning,
            source=meaning_source,
        )
        understanding = self._compile(
            message=turn.question_summary,
            meaning=meaning,
            context=context,
        )
        self._observe(
            "compiled",
            turn=turn,
            meaning=meaning,
            understanding=understanding,
        )
        current_image_evidence = None
        if authorized_image_input is not None:
            current_image_evidence = (
                self._image_evidence_collector.prepare_routing_evidence(
                    authorized_image_input
                )
            )
            if type(current_image_evidence) is not ImageRoutingEvidence:
                raise TypeError(
                    "image evidence collector must return "
                    "ImageRoutingEvidence"
                )
        collected_product_resolution = (
            self._product_resolution_collector.collect(
                message=turn.question_summary,
                understanding=understanding,
                snapshot=snapshot,
            )
        )
        if (
            type(collected_product_resolution)
            is not PreRoutingProductResolution
        ):
            raise TypeError(
                "product resolution collector must return "
                "PreRoutingProductResolution"
            )
        product_resolution = collected_product_resolution.resolution
        if type(product_resolution) is not ProductMentionResolution:
            raise TypeError(
                "product resolution collector must return "
                "ProductMentionResolution evidence"
            )
        router_product_bindings = (
            collected_product_resolution.explicit_bindings
        )
        product_resolution_issue = reconcile_product_resolution_issue(
            understanding=understanding,
            issue=product_resolution.issue,
            continuity_hint=meaning.continuity_hint,
        )
        product_bindings = product_resolution.bindings
        all_current_image_products = (
            current_image_evidence.confirmed_products
            if current_image_evidence is not None
            else ()
        )
        current_image_products = _select_current_image_products(
            understanding=understanding,
            current_image_products=all_current_image_products,
        )
        current_image_product_ids = tuple(
            item.product_id for item in current_image_products
        )
        similarity_anchor_product_id = (
            _similarity_anchor_product_id(
                snapshot,
                understanding=understanding,
                current_image_products=current_image_products,
            )
        )
        resolved_product_ids = tuple(
            dict.fromkeys(
                (
                    *product_resolution.product_ids,
                    *current_image_product_ids,
                )
            )
        )
        pending_reply = None
        pending_turn = (
            snapshot.reply_slot.value
            if snapshot is not None
            and isinstance(snapshot.reply_slot, PendingReplySlot)
            else None
        )
        if pending_turn is not None:
            pending_reply = resolve_semantic_pending_reply(
                meaning=meaning,
                understanding=understanding,
                pending=pending_turn,
            )
        pending_reply_kind = (
            pending_reply.kind
            if pending_reply is not None
            else None
        )
        planning_product_ids = resolved_product_ids
        if (
            not planning_product_ids
            and understanding.goal.value == "image_similarity"
            and similarity_anchor_product_id is not None
        ):
            planning_product_ids = (
                similarity_anchor_product_id,
            )
        task_plan = plan_task(
            understanding,
            resolved_product_ids=planning_product_ids,
            product_resolution_issue=product_resolution_issue,
            message=turn.question_summary,
        )
        transition_plan = plan_code_owned_transitions(
            message=turn.question_summary,
            understanding=understanding,
            task=task_plan,
            previous=(
                snapshot.recommendation_slot.query_context
                if snapshot is not None
                and snapshot.recommendation_slot is not None
                else None
            ),
            continuation_requested=meaning.continuity_hint == "continue",
        )
        task_plan = transition_plan.task_plan
        if (
            pending_turn is not None
            and pending_reply is not None
            and pending_reply.kind
            in {"affirm", "correct", "supplement"}
        ):
            task_plan = resume_pending_recommendation(
                pending=pending_turn,
                reply=pending_reply,
            )
        if snapshot is not None and snapshot.session_profile is not None:
            task_plan = apply_session_profile_to_task(
                task_plan,
                snapshot.session_profile,
            )
        transition_operations = (
            tuple(
                item.operation
                for item in transition_plan.transition_result.transitions
            )
            if transition_plan.transition_result is not None
            else ()
        )
        consultation_evidence = prepare_dynamic_consultation_evidence(
            message=turn.question_summary,
            meaning=meaning,
            source_turn_id=turn.identity.turn_id,
            expected_skin_target=_confirmation_skin_target(snapshot),
        )
        scenario_observations = tuple(
            parse_scenarios(turn.question_summary)
        )
        pre_routing_task = self._prepare_routing_task(
            task_plan,
            scenario_observations=scenario_observations,
            topic=understanding.topic,
            context_product_ids=(
                resolved_product_ids
                or _confirmed_image_product_ids(snapshot)
            ),
            similarity_anchor_product_id=(
                (
                    current_image_product_ids[0]
                    if len(current_image_product_ids) == 1
                    else similarity_anchor_product_id
                )
                if (
                    understanding.goal.value == "image_similarity"
                )
                else None
            ),
        )
        task_plan = pre_routing_task.task_plan
        prepared_pending_turn = build_pending_turn(
            message=turn.question_summary,
            source_conversation_version=turn.conversation_version,
            task=task_plan,
        )
        retrieval_query = _retrieval_query_for_task(task_plan)
        product_knowledge_dimensions = (
            resolve_product_knowledge_dimensions(
                retrieval_query.value
            )
        )
        product_evidence_search = prepare_evidence_search(
            source_text=turn.question_summary,
            question_meaning=retrieval_query.value,
            product_mention_spans=tuple(
                sorted(
                    (
                        mention.source_span.start,
                        mention.source_span.end,
                    )
                    for mention in task_plan.product_mentions
                )
            ),
        )
        image_evidence = (
            current_image_evidence
            if current_image_evidence is not None
            else _persisted_image_routing_evidence(
                snapshot,
                anchor_topic=understanding.topic,
            )
        )
        route = self._route(
            meaning=meaning,
            understanding=understanding,
            snapshot=snapshot,
            product_bindings=router_product_bindings,
            current_image_products=current_image_products,
            product_resolution_issue=product_resolution_issue,
            pending_reply_kind=pending_reply_kind,
            transition_operations=transition_operations,
            safety_signal=admit_safety_signal(
                message=turn.question_summary,
                candidates=meaning.observation_candidates,
            ),
            task_plan=task_plan,
        )
        self._observe("routed", turn=turn, decision=route)
        task_plan = route.task_plan
        if task_plan is None:
            raise RuntimeError("router omitted the executable task plan")
        scenario_inputs = (
            pre_routing_task.scenario_inputs
            if task_plan.mode == "recommend"
            else None
        )
        result = self._dispatch(
            processor_registry=self._processor_registry,
            execution_input=ProcessorExecutionInput(
                turn_identity=turn.identity,
                understanding=understanding,
                decision=route,
                current_snapshot=snapshot,
                routing_evidence=PreRoutingEvidence(
                    query=(
                        OpaqueRetrievalQuery(
                            value=turn.question_summary.strip()
                        )
                        if route.processor == "general_knowledge"
                        else retrieval_query
                    ),
                    product_evidence_search=product_evidence_search,
                    prepared_pending_turn=prepared_pending_turn,
                    conversation_version=turn.conversation_version,
                    profile_owner=turn.profile_owner,
                    profile_context=profile_context,
                    product_resolution=product_resolution,
                    pending_reply=pending_reply,
                    scenario_inputs=scenario_inputs,
                    product_knowledge_dimensions=(
                        product_knowledge_dimensions
                    ),
                    consultation=consultation_evidence,
                    image=image_evidence,
                    candidate_product_ids=(
                        tuple(
                            dict.fromkeys(
                                product_id
                                for observation
                                in current_image_evidence.observations
                                for product_id
                                in observation.candidate_product_ids
                            )
                        )[:16]
                        if current_image_evidence is not None
                        else ()
                    ),
                    scenario_observations=scenario_observations,
                    transition_operations=transition_operations,
                ),
            ),
        )
        yield from self._commit_execution_result(
            turn=turn,
            current=snapshot,
            decision=route,
            result=result,
        )

    def _compile(
        self,
        *,
        message: str,
        meaning: TurnMeaning,
        context: SemanticContext,
    ) -> StructuredUnderstanding:
        if type(meaning) is not TurnMeaning:
            raise TypeError("translator must return TurnMeaning")
        self._observe(
            "compiler_invoked",
            meaning=meaning,
        )
        understanding = compile_turn_meaning(
            message=message,
            meaning=meaning,
            context=context,
            concept_catalog=getattr(
                self._understanding,
                "concept_catalog",
                None,
            ),
        )
        if type(understanding) is not StructuredUnderstanding:
            raise TypeError(
                "compiler must return StructuredUnderstanding"
            )
        return understanding

    def _route(
        self,
        *,
        meaning: TurnMeaning,
        understanding: StructuredUnderstanding,
        snapshot: ConversationSnapshot | None,
        **evidence,
    ) -> UnifiedRouteDecision:
        self._observe(
            "router_invoked",
            meaning=meaning,
            understanding=understanding,
        )
        return route_unified_turn(
            meaning=meaning,
            understanding=understanding,
            snapshot=snapshot,
            **evidence,
        )

    def _dispatch(
        self,
        *,
        processor_registry: Mapping[ProcessorKind, object],
        execution_input: ProcessorExecutionInput,
    ) -> ExecutionResult:
        try:
            processor_name = execution_input.decision.processor
            processor = processor_registry[processor_name]
        except KeyError as exc:
            raise ValueError(
                "no processor registered for "
                f"{execution_input.decision.processor}"
            ) from exc
        return processor.execute(execution_input)

    def _commit_execution_result(
        self,
        *,
        turn: UserTurn,
        current: ConversationSnapshot | None,
        decision: UnifiedRouteDecision,
        result: ExecutionResult,
    ) -> tuple[bytes, ...]:
        if type(result) is not ExecutionResult:
            raise TypeError(
                "processor must return an exact ExecutionResult"
            )
        if result.decision is not decision:
            raise ValueError(
                "processor must return the exact route decision"
            )
        self._observe(
            "result_received",
            turn=turn,
            result=result,
        )
        current_version = current.version if current is not None else 0
        if isinstance(result.terminal, ErrorTerminal):
            replacement = None
        else:
            self._observe(
                "reducer_invoked",
                turn=turn,
                decision=decision,
                delta=result.state_delta,
            )
            replacement = reduce_conversation_state(
                current=current,
                turn_identity=turn.identity,
                decision=decision,
                delta=result.state_delta,
                card_display=(
                    result.terminal.data.card_display
                    if isinstance(result.terminal, PresentationTerminal)
                    else None
                ),
            )
        if replacement is not None:
            self._observe(
                "state_reduced",
                turn=turn,
                snapshot=replacement,
            )
        envelope = materialize_execution_envelope(
            result,
            session_id=turn.session_id,
            conversation_version=(
                replacement.version
                if replacement is not None
                else current_version
            ),
        )
        self._observe(
            "envelope_materialized",
            turn=turn,
            envelope=envelope,
        )
        if replacement is None:
            return envelope.frames
        self._observe(
            "state_save_invoked",
            turn=turn,
            snapshot=replacement,
        )
        saved = self._conversation_state.save(
            replacement,
            expected_version=current_version,
        )
        if saved != replacement:
            raise RuntimeError(
                "conversation state store changed validated snapshot"
            )
        self._observe(
            "state_saved",
            turn=turn,
            snapshot=saved,
        )
        return envelope.frames

    def _prepare_routing_task(
        self,
        task_plan,
        *,
        scenario_observations,
        topic=None,
        context_product_ids=(),
        similarity_anchor_product_id=None,
    ) -> PreRoutingTaskPlan:
        if self._task_plan_enricher is not None:
            return self._task_plan_enricher.enrich(
                task_plan,
                scenarios=scenario_observations,
                context_product_ids=context_product_ids,
                similarity_anchor_product_id=(
                    similarity_anchor_product_id
                ),
            )
        task_plan = promote_single_image_similarity_task(
            task_plan,
            similarity_anchor_product_id=similarity_anchor_product_id,
            topic=topic,
        )
        if task_plan.mode != "recommend":
            return PreRoutingTaskPlan(
                task_plan=task_plan,
                scenario_inputs=None,
            )
        scenario_inputs = build_scenario_inputs(
            task_plan,
            scenarios=scenario_observations,
        )
        return PreRoutingTaskPlan(
            task_plan=revalidate_task_plan(
                task_plan,
                update={
                    "constraints": (
                        scenario_inputs.decision.constraints
                    ),
                },
            ),
            scenario_inputs=scenario_inputs,
        )

    def _observe(self, event: str, **values) -> None:
        callback = getattr(self._observer, event, None)
        if not callable(callback):
            return
        try:
            callback(**values)
        except Exception:
            return

    @staticmethod
    def _failure_frames(
        turn: UserTurn,
        error: Exception,
    ) -> tuple[bytes, bytes]:
        if isinstance(error, ImageBundleServiceError):
            return materialize_error_frames(
                session_id=turn.session_id,
                code=error.error.code.name,
                message=error.error.message,
            )
        return materialize_error_frames(
            session_id=turn.session_id,
            code="GUIDE_INTERNAL_ERROR",
            message="推荐暂时不可用，请稍后重试。",
        )

    @staticmethod
    def _validate_owner(
        snapshot: ConversationSnapshot | None,
        turn: UserTurn,
    ) -> None:
        current_version = snapshot.version if snapshot is not None else 0
        if (
            turn.conversation_version != current_version
            or (
                snapshot is not None
                and snapshot.profile_owner != turn.profile_owner
            )
        ):
            raise ConversationStateConflict(turn.session_id)


__all__ = [
    "UnifiedGuideFlow",
    "UnifiedUnderstandingAdapter",
    "UnifiedUnderstandingPort",
]


def _confirmation_skin_target(
    snapshot: ConversationSnapshot | None,
):
    if snapshot is None or snapshot.consultation_slot is None:
        return None
    assessment = (
        snapshot.consultation_slot.state.confirmable_assessment
    )
    if assessment is None:
        return None
    return assessment.conclusion.skin_target


def _confirmed_image_product_ids(
    snapshot: ConversationSnapshot | None,
) -> tuple[int, ...]:
    if snapshot is None or snapshot.image_slot is None:
        return ()
    return tuple(
        dict.fromkeys(
            item.product_id
            for item in snapshot.image_slot.confirmed_products
        )
    )


def _persisted_image_routing_evidence(
    snapshot: ConversationSnapshot | None,
    *,
    anchor_topic,
) -> PersistedImageRoutingEvidence | None:
    if snapshot is None or snapshot.image_slot is None:
        return None
    return PersistedImageRoutingEvidence(
        confirmed_products=snapshot.image_slot.confirmed_products,
        anchor_topic=anchor_topic,
    )


def _single_confirmed_image_product_id(
    snapshot: ConversationSnapshot | None,
) -> int | None:
    product_ids = _confirmed_image_product_ids(snapshot)
    return product_ids[0] if len(product_ids) == 1 else None


def _select_current_image_products(
    *,
    understanding: StructuredUnderstanding,
    current_image_products: tuple[ConfirmedImageProductRef, ...],
) -> tuple[ConfirmedImageProductRef, ...]:
    referenced_ordinals = tuple(
        reference.ordinal
        for reference in understanding.references
        if (
            reference.kind == "image_ordinal"
            and reference.ordinal is not None
        )
    )
    if not referenced_ordinals:
        return current_image_products
    by_ordinal = {
        item.image_ordinal: item for item in current_image_products
    }
    return tuple(
        by_ordinal[ordinal]
        for ordinal in dict.fromkeys(referenced_ordinals)
        if ordinal in by_ordinal
    )


def _similarity_anchor_product_id(
    snapshot: ConversationSnapshot | None,
    *,
    understanding: StructuredUnderstanding,
    current_image_products=(),
) -> int | None:
    confirmed_products = (
        tuple(current_image_products)
        if current_image_products
        else (
            snapshot.image_slot.confirmed_products
            if snapshot is not None and snapshot.image_slot is not None
            else ()
        )
    )
    if not confirmed_products:
        return None
    image_references = tuple(
        reference
        for reference in understanding.references
        if reference.kind == "image_ordinal"
    )
    if len(image_references) == 1:
        ordinal = image_references[0].ordinal
        if ordinal is not None:
            return next(
                (
                    item.product_id
                    for item in confirmed_products
                    if item.image_ordinal == ordinal
                ),
                None,
            )
    product_ids = tuple(
        dict.fromkeys(
            item.product_id for item in confirmed_products
        )
    )
    return product_ids[0] if len(product_ids) == 1 else None


def _retrieval_query_for_task(
    task_plan: TaskPlan,
) -> OpaqueRetrievalQuery:
    value = task_plan.question_meaning
    if value is None or not value.strip():
        value = {
            "recommend": "按当前条件推荐商品",
            "comparison": "比较当前商品",
            "suitability": "判断当前商品适配性",
            "single_product": "查询当前商品",
            "followup": "继续当前商品问题",
            "revision": "调整当前推荐条件",
            "knowledge": "查询当前主题知识",
            "consultation": "继续当前肤况咨询",
            "clarify": "澄清当前请求",
        }[task_plan.mode]
    return OpaqueRetrievalQuery(value=value)
