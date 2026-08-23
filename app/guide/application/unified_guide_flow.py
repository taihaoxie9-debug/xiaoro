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
    OpaqueRetrievalQuery,
    PreRoutingEvidence,
    ProcessorExecutionInput,
    materialize_execution_envelope,
)
from app.guide.application.image_bundle_service import (
    ImageBundleServiceError,
)
from app.guide.application.pending_turn import (
    resolve_semantic_pending_reply,
    resume_pending_recommendation,
)
from app.guide.application.product_evidence_answer import (
    resolve_product_knowledge_dimensions,
)
from app.guide.application.public_event_envelope import (
    materialize_error_frames,
)
from app.guide.application.scenario_inputs import build_scenario_inputs
from app.guide.application.session_profile_resolution import (
    resolve_session_profile_context,
)
from app.guide.application.query_context import (
    apply_session_profile_to_task,
)
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    PendingReplySlot,
)
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStatePort,
)
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.intent.contracts import TaskPlan
from app.guide.intent.responsibility_matrix import (
    ProcessorKind,
    Responsibility,
)
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
        text_processor,
        consultation_processor,
        image_processor=None,
        conversation_state: ConversationStatePort,
        observer=None,
    ) -> None:
        if not callable(getattr(understanding, "translate", None)):
            raise TypeError("understanding must expose translate")
        if not callable(
            getattr(text_processor, "execute", None)
        ):
            raise TypeError("text processor must expose execute")
        if not callable(
            getattr(consultation_processor, "execute", None)
        ):
            raise TypeError("consultation processor must expose execute")
        if (
            image_processor is not None
            and (
                not callable(
                    getattr(image_processor, "execute", None)
                )
                or not callable(
                    getattr(
                        image_processor,
                        "prepare_routing_evidence",
                        None,
                    )
                )
            )
        ):
            raise TypeError(
                "image processor must expose execute and "
                "prepare_routing_evidence"
            )
        self._understanding = understanding
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
        self._image_evidence_collector = image_processor
        self._conversation_state = conversation_state
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
        context = resolve_semantic_context(
            conversation_version=turn.conversation_version,
            snapshot=snapshot,
            profile_context=profile_context,
        )
        meaning = self._understanding.translate(
            turn.message,
            context=context,
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
        resolve_product_resolution = getattr(
            self._text_processor,
            "resolve_product_resolution",
            None,
        )
        if callable(resolve_product_resolution):
            product_resolution = resolve_product_resolution(
                message=turn.message,
                understanding=understanding,
                snapshot=snapshot,
            )
        else:
            product_resolution = ProductMentionResolution(
                bindings=tuple(
                    self._text_processor.resolve_product_bindings(
                        message=turn.message,
                        understanding=understanding,
                        snapshot=snapshot,
                    )
                )
            )
        product_resolution_issue = reconcile_product_resolution_issue(
            understanding=understanding,
            issue=product_resolution.issue,
            continuity_hint=meaning.continuity_hint,
        )
        product_bindings = product_resolution.bindings
        router_product_bindings = (
            product_bindings
            if understanding.product_mentions
            else ()
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
        task_plan = plan_task(
            understanding,
            resolved_product_ids=tuple(
                item.product_id
                for item in product_bindings
            ),
            product_resolution_issue=product_resolution_issue,
            message=turn.question_summary,
        )
        transition_plan = plan_code_owned_transitions(
            message=turn.message,
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
        scenario_inputs = (
            build_scenario_inputs(
                task_plan,
                scenarios=scenario_observations,
            )
            if task_plan.mode == "recommend"
            else None
        )
        product_knowledge_dimensions = (
            resolve_product_knowledge_dimensions(
                turn.question_summary
            )
        )
        route = self._route(
            meaning=meaning,
            understanding=understanding,
            snapshot=snapshot,
            product_bindings=router_product_bindings,
            product_resolution_issue=product_resolution_issue,
            pending_reply_kind=pending_reply_kind,
            transition_operations=transition_operations,
            safety_signal=admit_safety_signal(
                message=turn.message,
                candidates=meaning.observation_candidates,
            ),
        )
        self._observe("routed", turn=turn, decision=route)
        task_plan = _bind_route_products(
            task_plan=task_plan,
            decision=route,
            understanding=understanding,
            product_resolution_issue=product_resolution_issue,
        )
        result = self._dispatch(
            processor_registry=self._processor_registry,
            execution_input=ProcessorExecutionInput(
                turn_identity=turn.identity,
                understanding=understanding,
                decision=route,
                current_snapshot=snapshot,
                routing_evidence=PreRoutingEvidence(
                    query=OpaqueRetrievalQuery(
                        value=turn.question_summary
                    ),
                    conversation_version=turn.conversation_version,
                    profile_owner=turn.profile_owner,
                    profile_context=profile_context,
                    product_resolution=product_resolution,
                    pending_reply=pending_reply,
                    task_plan=task_plan,
                    scenario_inputs=scenario_inputs,
                    product_knowledge_dimensions=(
                        product_knowledge_dimensions
                    ),
                    consultation=consultation_evidence,
                    image=None,
                    candidate_product_ids=(),
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

    def stream_image(
        self,
        turn: UserTurn,
    ) -> Iterator[bytes]:
        try:
            yield from self._stream_image_unchecked(turn)
        except Exception as error:
            yield from self._failure_frames(turn, error)

    def _stream_image_unchecked(
        self,
        turn: UserTurn,
    ) -> Iterator[bytes]:
        if type(turn) is not UserTurn:
            raise TypeError("turn must be an exact UserTurn")
        image_processor = self._image_evidence_collector
        if image_processor is None:
            raise ValueError("image processor is unavailable")
        prepare_routing_evidence = getattr(
            image_processor,
            "prepare_routing_evidence",
            None,
        )
        if not callable(prepare_routing_evidence):
            raise TypeError(
                "image processor must expose prepare_routing_evidence"
            )
        snapshot = self._conversation_state.load(turn.session_id)
        self._validate_owner(snapshot, turn)
        profile_context = resolve_session_profile_context(snapshot)
        routing_evidence = prepare_routing_evidence(turn)
        image_count = routing_evidence.image_count
        if type(image_count) is not int or not 0 <= image_count <= 4:
            raise ValueError(
                "semantic image count must be between zero and four"
            )
        context = resolve_semantic_context(
            conversation_version=turn.conversation_version,
            snapshot=snapshot,
            profile_context=profile_context,
        ).model_copy(
            update={
                "image_count": image_count,
                "focused_image_ordinal": (
                    1 if image_count == 1 else None
                ),
            },
            deep=True,
        )
        if turn.image_action is None:
            meaning = self._understanding.translate(
                turn.message,
                context=context,
            )
        else:
            meaning = turn_meaning_for_image_action(
                action=turn.image_action,
                image_count=image_count,
                question_summary=turn.question_summary,
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
        product_resolution = ProductMentionResolution(bindings=())
        confirmed_product_ids = tuple(
            item.product_id
            for item in routing_evidence.confirmed_products
        )
        task_plan = plan_task(
            understanding,
            resolved_product_ids=confirmed_product_ids,
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
        scenario_inputs = (
            build_scenario_inputs(
                task_plan,
                scenarios=scenario_observations,
            )
            if task_plan.mode == "recommend"
            else None
        )
        product_knowledge_dimensions = (
            resolve_product_knowledge_dimensions(
                turn.question_summary
            )
        )
        route = self._route(
            meaning=meaning,
            understanding=understanding,
            snapshot=snapshot,
            current_image_products=(
                routing_evidence.confirmed_products
            ),
            safety_signal=admit_safety_signal(
                message=turn.question_summary,
                candidates=meaning.observation_candidates,
            ),
        )
        self._observe("routed", turn=turn, decision=route)
        task_plan = _bind_route_products(
            task_plan=task_plan,
            decision=route,
            understanding=understanding,
            product_resolution_issue=None,
        )
        result = self._dispatch(
            processor_registry=self._processor_registry,
            execution_input=ProcessorExecutionInput(
                turn_identity=turn.identity,
                understanding=understanding,
                decision=route,
                current_snapshot=snapshot,
                routing_evidence=PreRoutingEvidence(
                    query=OpaqueRetrievalQuery(
                        value=turn.question_summary
                    ),
                    conversation_version=turn.conversation_version,
                    profile_owner=turn.profile_owner,
                    profile_context=profile_context,
                    product_resolution=product_resolution,
                    pending_reply=None,
                    task_plan=task_plan,
                    scenario_inputs=scenario_inputs,
                    product_knowledge_dimensions=(
                        product_knowledge_dimensions
                    ),
                    consultation=consultation_evidence,
                    image=routing_evidence,
                    candidate_product_ids=tuple(
                        dict.fromkeys(
                            product_id
                            for observation
                            in routing_evidence.observations
                            for product_id
                            in observation.candidate_product_ids
                        )
                    )[:16],
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

    @staticmethod
    def _route(
        *,
        meaning: TurnMeaning,
        understanding: StructuredUnderstanding,
        snapshot: ConversationSnapshot | None,
        **evidence,
    ) -> UnifiedRouteDecision:
        return route_unified_turn(
            meaning=meaning,
            understanding=understanding,
            snapshot=snapshot,
            **evidence,
        )

    @staticmethod
    def _dispatch(
        *,
        processor_registry: Mapping[ProcessorKind, object],
        execution_input: ProcessorExecutionInput,
    ) -> ExecutionResult:
        try:
            return processor_registry[
                execution_input.decision.processor
            ].execute(execution_input)
        except KeyError as exc:
            raise ValueError(
                "no processor registered for "
                f"{execution_input.decision.processor}"
            ) from exc

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
        replacement = (
            None
            if isinstance(result.terminal, ErrorTerminal)
            else reduce_conversation_state(
                current=current,
                turn_identity=turn.identity,
                decision=decision,
                delta=result.state_delta,
            )
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


def _bind_route_products(
    *,
    task_plan: TaskPlan,
    decision: UnifiedRouteDecision,
    understanding: StructuredUnderstanding,
    product_resolution_issue,
) -> TaskPlan:
    product_ids = tuple(
        binding.product_id
        for binding in decision.product_bindings
    )
    if (
        decision.responsibility is Responsibility.COMPARISON
        or (
            task_plan.mode == "clarify"
            and decision.responsibility
            is not Responsibility.CLARIFICATION
        )
    ):
        return plan_task(
            understanding,
            responsibility=decision.responsibility,
            resolved_product_ids=product_ids,
            product_resolution_issue=product_resolution_issue,
        )
    if task_plan.mode == "recommend":
        return task_plan
    if not product_ids or tuple(task_plan.product_ids) == product_ids:
        return task_plan
    payload = task_plan.model_dump(mode="python")
    payload["product_ids"] = list(product_ids)
    return TaskPlan.model_validate(payload, strict=True)
