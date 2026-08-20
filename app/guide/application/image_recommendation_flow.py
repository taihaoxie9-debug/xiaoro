from __future__ import annotations

from collections.abc import Callable, Iterator
import logging
from threading import Lock
from typing import Protocol

from app.guide.application.scenario_inputs import build_scenario_inputs
from app.guide.application.contracts import UserTurn
from app.guide.application.image_alternative_count import (
    requested_image_alternative_count,
)
from app.guide.application.image_compare_gate import TwoImageCompareGate
from app.guide.application.image_bundle_service import (
    ImageBundleService,
    ImageBundleServiceError,
)
from app.guide.application.image_bundle_state import ImageBundlePayload
from app.guide.application.image_reference_resolution import (
    build_multi_image_context,
)
from app.guide.application.image_suitability_gate import (
    SingleImageSuitabilityGate,
    SuitabilityAuthoritativeInputs,
    SuitabilityAuthoritativeProfile,
)
from app.guide.application.multi_image_compare_gate import (
    MultiImageCompareBundleAuthorizationRequest,
    ThreeToFourImageCompareGate,
)
from app.guide.application.scenario_contracts import ScenarioInputBundle
from app.guide.decision.contracts import DecisionResult, WinnerStatus
from app.guide.decision.image_compare import (
    ImageCompareDecisionFoundation,
)
from app.guide.decision.image_compare_contracts import (
    ImageCompareDecisionResult,
)
from app.guide.decision.image_suitability import (
    ImageSuitabilityDecisionFoundation,
)
from app.guide.decision.image_suitability_contracts import (
    ImageSuitabilityDecisionResult,
    SuitabilityContextClaim,
    SuitabilityContextClaims,
    SuitabilityContextProvenance,
    SuitabilityContextSource,
)
from app.guide.decision.multi_image_compare import (
    MultiImageCompareDecisionFoundation,
)
from app.guide.decision.multi_image_compare_contracts import (
    MultiImageCompareDecisionResult,
)
from app.guide.decision.ports import DecisionFactPort
from app.guide.decision.recommendation import decide_recommendation
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.focus_state import ConfirmedImageProductRef
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStatePort,
    SessionLockPort,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.profile_policy import ResolvedProfileContext
from app.guide.intent.contracts import CategoryConstraint, TaskPlan
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import (
    UnifiedRouteDecision,
    route_unified_turn,
)
from app.guide.presentation.card_display import (
    comparison_card_display,
    recommendation_card_display,
    single_product_card_display,
)
from app.guide.presentation.contracts import (
    CardDisplayContract,
    ProductCard,
    ResponsePlan,
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
    build_response_plan,
)
from app.guide.presentation.sse_events import (
    AnswerContractData,
    AnswerContractEvent,
    CardDisplayContractEvent,
    CitationData,
    CitationsData,
    CitationsEvent,
    ClarifyData,
    ClarifyEvent,
    DecisionProcessData,
    DecisionProcessEvent,
    EndData,
    EndEvent,
    ErrorData,
    ErrorEvent,
    ImageObservationData,
    ImageObservationEvent,
    ImageComparisonData,
    ImageComparisonPriceFactData,
    ImageComparisonReferenceData,
    ImageSuitabilityData,
    ImageSuitabilityFactData,
    ImageSuitabilityReferenceData,
    IntentData,
    IntentEvent,
    MessageData,
    MessageEvent,
    ProductsData,
    ProductsEvent,
    PitfallsData,
    PitfallsEvent,
    PresentationContractEvent,
    ReviewEvidenceData,
    ReviewEvidenceEvent,
    ScenarioEvidenceData,
    ScenarioEvidenceEvent,
    SseEvent,
    StageData,
    StageEvent,
    StartData,
    StartEvent,
)
from app.guide.retrieval.category_taxonomy import (
    canonical_categories_for,
)
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.retrieval.image_contracts import ImageRetrievalRequest
from app.guide.retrieval.ports import (
    CategoryCatalogPort,
    CategoryRecord,
    ScenarioEvidencePort,
)
from app.guide.retrieval.review_reader import ReviewEvidenceReader
from app.guide.retrieval.review_summary import build_review_summary
from app.guide.retrieval.scenario_pitfalls import (
    project_scenario_pitfalls,
)
from app.guide.understanding.contracts import (
    CategoryDraft,
    SkinDraft,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.contracts import ImageBundle
from app.guide.understanding.image_contracts import (
    IdentityState,
    ImageIdentityObservation,
)
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.safety_admission import (
    admit_safety_signal,
)
from app.guide.understanding.text_understanding import understand_text
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


logger = logging.getLogger(__name__)

class ImageIdentityObserverPort(Protocol):
    def observe(
        self,
        request: ImageRetrievalRequest,
    ) -> ImageIdentityObservation: ...


class ImageRecommendationOrchestrator:
    def __init__(
        self,
        *,
        image_bundles: ImageBundleService,
        identity_observer: ImageIdentityObserverPort,
        category_catalog: CategoryCatalogPort,
        scenario_evidence: ScenarioEvidencePort | None = None,
        decision_facts: DecisionFactPort,
        presentation_facts: PresentationFactPort,
        review_evidence: ReviewEvidenceReader | None = None,
        profile_owner_factory: (
            Callable[[str], ProfileOwnerRef] | None
        ) = None,
        profile_resolver: (
            Callable[..., ResolvedProfileContext] | None
        ) = None,
        conversation_state: ConversationStatePort | None = None,
        session_locks: SessionLockPort | None = None,
        standard_processor=None,
        presentation_compiler: PresentationCompiler | None = None,
        max_results: int = 10,
    ) -> None:
        if not 2 <= max_results <= 100:
            raise ValueError("max_results must be between 2 and 100")
        self._image_bundles = image_bundles
        self._identity_observer = identity_observer
        self._category_catalog = category_catalog
        self._scenario_evidence = scenario_evidence
        self._decision_facts = decision_facts
        self._presentation_facts = presentation_facts
        self._review_evidence = review_evidence
        self._profile_owner_factory = profile_owner_factory
        self._profile_resolver = profile_resolver
        self._conversation_state = conversation_state
        self._session_locks = session_locks
        if (
            standard_processor is not None
            and not callable(
                getattr(
                    standard_processor,
                    "stream_understanding_body",
                    None,
                )
            )
        ):
            raise TypeError(
                "standard processor must expose "
                "stream_understanding_body"
            )
        self._standard_processor = standard_processor
        self._presentation_compiler = (
            presentation_compiler
            if presentation_compiler is not None
            else PresentationCompiler(copywriter=None)
        )
        self._delivery_versions: dict[
            tuple[str, str, str],
            int,
        ] = {}
        self._delivery_versions_lock = Lock()
        self._two_image_compare = TwoImageCompareGate(
            category_catalog=category_catalog,
            decision_facts=decision_facts,
            decision=ImageCompareDecisionFoundation(),
        )
        self._single_image_suitability = SingleImageSuitabilityGate(
            decision_facts=decision_facts,
            decision=ImageSuitabilityDecisionFoundation(),
        )
        self._multi_image_compare = ThreeToFourImageCompareGate(
            bundle_authorizer=image_bundles,
            category_catalog=category_catalog,
            decision_facts=decision_facts,
            decision=MultiImageCompareDecisionFoundation(),
        )
        self._max_results = max_results

    def semantic_image_count(self, turn: UserTurn) -> int:
        if type(turn) is not UserTurn:
            raise TypeError("turn must be an exact UserTurn")
        if (
            turn.image_bundle_id is None
            or turn.image_bundle_version is None
            or turn.image_bundle_token is None
        ):
            return 0
        try:
            _, payloads = self._image_bundles.authorize_bundle_payloads(
                bundle_id=turn.image_bundle_id,
                version=turn.image_bundle_version,
                session_id=turn.session_id,
                owner_token=turn.image_bundle_token,
            )
        except ImageBundleServiceError:
            return 0
        return len(payloads)

    def stream(self, turn: UserTurn) -> Iterator[SseEvent]:
        yield StartEvent(data=StartData(session_id=turn.session_id))
        try:
            if self._session_locks is None:
                buffered_events = list(self._stream_image(turn))
            else:
                with self._session_locks.hold(turn.session_id):
                    buffered_events = list(self._stream_image(turn))
        except ImageBundleServiceError:
            yield _error_event("IMAGE_BUNDLE_UNAVAILABLE")
        except Exception:
            logger.exception(
                "image recommendation failed for session_id=%s",
                turn.session_id,
            )
            yield _error_event("GUIDE_INTERNAL_ERROR")
        else:
            yield from buffered_events

    def stream_understanding(
        self,
        turn: UserTurn,
        *,
        meaning: TurnMeaning,
        understanding: StructuredUnderstanding,
        snapshot: ConversationSnapshot | None,
    ) -> Iterator[SseEvent]:
        if type(turn) is not UserTurn:
            raise TypeError("turn must be an exact UserTurn")
        if type(meaning) is not TurnMeaning:
            raise TypeError("meaning must be an exact TurnMeaning")
        if type(understanding) is not StructuredUnderstanding:
            raise TypeError(
                "understanding must be an exact StructuredUnderstanding"
            )
        if (
            snapshot is not None
            and type(snapshot) is not ConversationSnapshot
        ):
            raise TypeError(
                "snapshot must be a ConversationSnapshot or None"
            )
        yield StartEvent(data=StartData(session_id=turn.session_id))
        try:
            if self._session_locks is None:
                buffered_events = list(
                    self._stream_image(
                        turn,
                        meaning=meaning,
                        understanding=understanding,
                        snapshot=snapshot,
                    )
                )
            else:
                with self._session_locks.hold(turn.session_id):
                    buffered_events = list(
                        self._stream_image(
                            turn,
                            meaning=meaning,
                            understanding=understanding,
                            snapshot=snapshot,
                        )
                    )
        except ImageBundleServiceError:
            yield _error_event("IMAGE_BUNDLE_UNAVAILABLE")
        except Exception:
            logger.exception(
                "unified image flow failed for session_id=%s",
                turn.session_id,
            )
            yield _error_event("GUIDE_INTERNAL_ERROR")
        else:
            yield from buffered_events

    def _stream_image(
        self,
        turn: UserTurn,
        *,
        meaning: TurnMeaning | None = None,
        understanding: StructuredUnderstanding | None = None,
        snapshot: ConversationSnapshot | None = None,
    ) -> Iterator[SseEvent]:
        if (
            turn.image_bundle_id is None
            or turn.image_bundle_version is None
            or turn.image_bundle_token is None
        ):
            yield _error_event("IMAGE_BUNDLE_UNAVAILABLE")
            return
        bundle, payloads = self._image_bundles.authorize_bundle_payloads(
            bundle_id=turn.image_bundle_id,
            version=turn.image_bundle_version,
            session_id=turn.session_id,
            owner_token=turn.image_bundle_token,
        )
        if len(payloads) == 1:
            yield from self._stream_single_image(
                turn,
                bundle,
                payloads[0],
                meaning=meaning,
                understanding=understanding,
                snapshot=snapshot,
            )
            return
        if len(payloads) == 2:
            yield from self._stream_two_image_compare(
                turn,
                bundle,
                payloads,
                meaning=meaning,
                understanding=understanding,
                snapshot=snapshot,
            )
            return
        if len(payloads) == 3:
            yield from self._stream_multi_image_compare(
                turn,
                bundle,
                payloads,
                meaning=meaning,
                understanding=understanding,
                snapshot=snapshot,
            )
            return
        if len(payloads) == 4:
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=(
                        "一次最多比较三款，请保留最想看的三张图片。"
                    ),
                    clarification_code=ClarificationCode.REFERENCE,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )
            return
        yield _error_event("IMAGE_COUNT_UNSUPPORTED")

    def _stream_single_image(
        self,
        turn: UserTurn,
        bundle: ImageBundle,
        payload: ImageBundlePayload,
        *,
        meaning: TurnMeaning | None = None,
        understanding: StructuredUnderstanding | None = None,
        snapshot: ConversationSnapshot | None = None,
    ) -> Iterator[SseEvent]:
        yield StageEvent(
            data=StageData(
                stage="image_observation",
                summary="正在确认图片中的商品信息。",
            )
        )
        observation = self._observe(payload)
        yield ImageObservationEvent(
            data=ImageObservationData(observation=observation)
        )
        if observation.identity_state is IdentityState.VISUAL_UNAVAILABLE:
            yield _error_event("IMAGE_RETRIEVAL_UNAVAILABLE")
            return
        if observation.identity_state is not IdentityState.CONFIRMED:
            yield _error_event("IMAGE_IDENTITY_UNCONFIRMED")
            return
        assert observation.confirmed_product_id is not None
        category_records = {
            record.product_id: record
            for record in self._category_catalog.iter_category_records()
        }
        anchor_record = category_records.get(
            observation.confirmed_product_id
        )
        anchor_topic = _topic_for_record(anchor_record)
        unified_route = None
        if meaning is not None and understanding is not None:
            unified_route = route_unified_turn(
                meaning=meaning,
                understanding=understanding,
                snapshot=snapshot,
                current_image_products=(
                    ConfirmedImageProductRef(
                        image_ordinal=1,
                        product_id=observation.confirmed_product_id,
                    ),
                ),
                safety_signal=admit_safety_signal(
                    message=turn.message,
                    candidates=meaning.observation_candidates,
                ),
            )
            if unified_route.processor == "clarification":
                if (
                    unified_route.clarification_code
                    is ClarificationCode.TOPIC
                    and anchor_topic is not None
                ):
                    unified_route = None
                else:
                    assert unified_route.clarification is not None
                    assert unified_route.clarification_code is not None
                    yield IntentEvent(data=IntentData(mode="clarify"))
                    yield ClarifyEvent(
                        data=ClarifyData(
                            question=unified_route.clarification,
                            clarification_code=(
                                unified_route.clarification_code
                            ),
                        )
                    )
                    yield EndEvent(
                        data=EndData(
                            conversation_version=turn.conversation_version
                        )
                    )
                    return
            if (
                unified_route is not None
                and unified_route.processor == "safety_escalation"
            ):
                yield IntentEvent(data=IntentData(mode="clarify"))
                yield ClarifyEvent(
                    data=ClarifyData(
                        question=(
                            "先暂停新产品和刺激性护肤；"
                            "如果破皮、渗出或疼痛持续，请尽快就医。"
                        ),
                        clarification_code=ClarificationCode.CONCERN,
                    )
                )
                yield EndEvent(
                    data=EndData(
                        conversation_version=turn.conversation_version
                    )
                )
                return
        identity_route = (
            unified_route is not None
            and unified_route.processor in {
                "image_identity",
                "product_knowledge",
            }
            and meaning is not None
            and meaning.operation_hint != "suitability"
        )
        standard_knowledge_route = (
            unified_route is not None
            and unified_route.processor == "product_knowledge"
            and meaning is not None
            and meaning.operation_hint == "knowledge"
            and not _is_identity_request(turn.message)
            and self._standard_processor is not None
            and understanding is not None
        )
        if standard_knowledge_route:
            yield from self._stream_standard_processor(
                turn,
                understanding=understanding,
                route_decision=unified_route,
                observations=[observation],
            )
            return
        if identity_route or (
            unified_route is None
            and _is_identity_request(turn.message)
        ):
            yield from self._stream_confirmed_image_identities(
                turn,
                [observation],
            )
            return
        standard_route = (
            unified_route is not None
            and unified_route.processor
            in {"recommendation", "comparison", "product_knowledge"}
            and self._standard_processor is not None
            and understanding is not None
        )
        if standard_route:
            yield from self._stream_standard_processor(
                turn,
                understanding=understanding,
                route_decision=unified_route,
                observations=[observation],
            )
            return
        suitability_route = (
            unified_route is not None
            and unified_route.processor == "product_knowledge"
            and meaning is not None
            and meaning.operation_hint == "suitability"
        )
        if suitability_route or (
            unified_route is None
            and _is_suitability_request(turn.message)
        ):
            yield from self._stream_single_image_suitability(
                turn,
                bundle,
                observation,
            )
            return
        if (
            unified_route is not None
            and unified_route.processor != "recommendation"
        ):
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question="请说明想识别商品、判断适配，还是找相似款。",
                    clarification_code=ClarificationCode.GOAL,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )
            return

        if (
            unified_route is not None
            and unified_route.processor == "recommendation"
            and meaning is not None
            and meaning.operation_hint
            in {"comparison", "image_similarity"}
            and understanding is not None
        ):
            understanding = understanding.model_copy(
                update={
                    "goal": UnderstandingGoal.RECOMMENDATION,
                    "references": [],
                },
                deep=True,
            )

        if anchor_topic is None:
            yield _error_event("IMAGE_CATEGORY_UNSUPPORTED")
            return

        understanding = (
            understanding
            if understanding is not None
            else understand_text(turn.message)
        )
        explicit_topics = [
            item.value
            for item in understanding.exact_constraints
            if isinstance(item, CategoryDraft)
        ]
        if explicit_topics and explicit_topics[0] is not anchor_topic:
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=(
                        "图片商品品类与文字指定品类不一致。"
                        "请确认要找图片同品类商品，还是按文字品类推荐。"
                    ),
                    clarification_code=ClarificationCode.TOPIC,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )
            return
        if not explicit_topics:
            understanding = understanding.model_copy(
                update={
                    "topic": anchor_topic,
                    "exact_constraints": [
                        *understanding.exact_constraints,
                        CategoryDraft(value=anchor_topic),
                    ],
                    "uncertainties": [
                        issue
                        for issue in understanding.uncertainties
                        if issue.code != "missing_category"
                    ],
                },
                deep=True,
            )
        task = plan_task(understanding).model_copy(
            update={"referenced_image_ids": [payload.image_id]},
            deep=True,
        )
        yield StageEvent(
            data=StageData(
                stage="understanding",
                summary="已提取图片请求中的预算、品类和排除条件。",
            )
        )
        if task.mode == "clarify":
            yield IntentEvent(data=IntentData(mode="clarify"))
            assert task.clarification is not None
            assert task.clarification_code is not None
            yield ClarifyEvent(
                data=ClarifyData(
                    question=task.clarification,
                    clarification_code=task.clarification_code,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )
            return

        yield IntentEvent(data=IntentData(mode="image_recommend"))
        retrieval = _image_retrieval_result(
            observation,
            category_records=category_records,
            exclude_product_id=observation.confirmed_product_id,
        )
        scenario_inputs = build_scenario_inputs(
            task,
            message=turn.message,
        )
        yield StageEvent(
            data=StageData(
                stage="retrieval",
                summary="已经找到与图片相近的商品。",
            )
        )
        yield StageEvent(
            data=StageData(
                stage="decision",
                summary="正在结合品类、预算、排除项和肤质继续整理。",
            )
        )
        decision = decide_recommendation(
            self._decision_facts,
            retrieval,
            constraints=scenario_inputs.decision.constraints,
        )
        alternative_limit = requested_image_alternative_count(
            meaning,
            message=turn.message,
        )
        visible_decision = decision.model_copy(
            update={
                "ordered_product_ids": (
                    decision.ordered_product_ids[:alternative_limit]
                ),
            },
            deep=True,
        )
        response = self._build_plan(visible_decision)
        cards = list(response.structured_events)
        card_display = recommendation_card_display(cards)
        presentation_event = self._presentation_event(
            mode="recommendation",
            user_need_summary=turn.message.strip(),
            winner_status=visible_decision.winner_status.value,
            card_display=card_display,
            cards=cards,
        )
        message = _presentation_compatibility_message(
            presentation_event,
            default=_summary_fragment(visible_decision),
        )
        yield from self._scenario_events(
            scenario_inputs=scenario_inputs,
            product_ids=list(visible_decision.ordered_product_ids),
        )
        yield DecisionProcessEvent(
            data=DecisionProcessData(
                ordered_product_ids=list(
                    visible_decision.ordered_product_ids
                ),
                winner_status=visible_decision.winner_status.value,
                evidence_refs=list(visible_decision.evidence_refs),
            )
        )
        yield AnswerContractEvent(
            data=AnswerContractData(
                product_count=len(cards),
                winner_status=visible_decision.winner_status.value,
                has_unknown_skin=any(
                    item.kind == "skin_match_unknown"
                    for item in visible_decision.risk_findings
                ),
            )
        )
        yield CardDisplayContractEvent(data=card_display)
        yield ProductsEvent(data=ProductsData(cards=cards))
        yield _image_citations_event(
            observations=[observation],
            product_ids=[card.product_id for card in cards],
        )
        yield presentation_event
        yield MessageEvent(data=MessageData(content=message))
        yield self._success_end(turn)

    def _stream_confirmed_image_identities(
        self,
        turn: UserTurn,
        observations: list[ImageIdentityObservation],
    ) -> Iterator[SseEvent]:
        product_ids = [
            observation.confirmed_product_id
            for observation in observations
            if observation.confirmed_product_id is not None
        ]
        if len(product_ids) != len(observations) or not 1 <= len(
            product_ids
        ) <= 3:
            raise ValueError(
                "confirmed image identity requires one to three products"
            )
        cards = self._cards_for_product_ids(product_ids)
        card_display = (
            single_product_card_display(cards[0])
            if len(cards) == 1
            else recommendation_card_display(cards)
        )
        presentation_event = self._presentation_event(
            mode="image_identity",
            user_need_summary=turn.message.strip(),
            winner_status="NOT_APPLICABLE",
            card_display=card_display,
            cards=cards,
        )
        message = _presentation_compatibility_message(
            presentation_event,
            default=(
                "已按图片顺序确认对应商品，"
                "具体事实见下方商品卡。"
            ),
        )

        yield IntentEvent(data=IntentData(mode="image_identity"))
        yield StageEvent(
            data=StageData(
                stage="decision",
                summary="已经确认图片中的商品。",
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
        yield _image_citations_event(
            observations=observations,
            product_ids=[card.product_id for card in cards],
        )
        yield presentation_event
        yield MessageEvent(data=MessageData(content=message))
        yield self._success_end(turn)

    def _stream_single_image_suitability(
        self,
        turn: UserTurn,
        bundle: ImageBundle,
        observation: ImageIdentityObservation,
    ) -> Iterator[SseEvent]:
        context_result = build_multi_image_context(
            mode="suitability",
            bundle=bundle,
            identity_observations=[observation],
        )
        if context_result.kind != "ready":
            yield _error_event("GUIDE_INTERNAL_ERROR")
            return
        assert context_result.context is not None
        claims, profile = self._resolve_suitability_context(
            turn,
            observation,
        )
        preparation = self._single_image_suitability.prepare(
            context_result.context,
            context_claims=claims,
            authority=SuitabilityAuthoritativeInputs(
                current_bundle_id=bundle.bundle_id,
                current_image_id=observation.image_id,
                current_ordinal=1,
                identity_state=observation.identity_state,
                confirmed_product_id=observation.confirmed_product_id,
                session_id=turn.session_id,
                conversation_version=turn.conversation_version,
                authoritative_context_claims=claims,
                profile=profile,
            ),
        )
        if preparation.kind == "clarification":
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=preparation.message,
                    clarification_code=(
                        ClarificationCode.CONCERN
                        if preparation.code
                        in {
                            "suitability_context_required",
                            "suitability_context_unsupported",
                        }
                        else ClarificationCode.REFERENCE
                    ),
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )
            return
        if preparation.kind != "assessed":
            yield _error_event("GUIDE_INTERNAL_ERROR")
            return

        result = preparation.decision_result
        assert observation.confirmed_product_id is not None
        facts = self._presentation_facts.get_presentation_facts(
            observation.confirmed_product_id
        )
        card = build_product_card(
            facts,
            skin_match={
                "suitable": "matched",
                "not_suitable": "not_applicable",
                "insufficient_evidence": "unknown",
            }[result.status],
        )
        suitability_data = _suitability_data(result)
        card_display = single_product_card_display(card)
        presentation_event = self._presentation_event(
            mode="product_knowledge",
            user_need_summary=turn.message.strip(),
            winner_status=result.status,
            card_display=card_display,
            cards=(card,),
        )
        message = _presentation_compatibility_message(
            presentation_event,
            default=_suitability_summary(result),
        )

        yield IntentEvent(data=IntentData(mode="image_suitability"))
        yield StageEvent(
            data=StageData(
                stage="decision",
                summary="正在结合商品信息判断是否适合你的肤质。",
            )
        )
        yield DecisionProcessEvent(
            data=DecisionProcessData(
                ordered_product_ids=[card.product_id],
                winner_status=result.status,
                evidence_refs=list(result.evidence_refs),
                suitability_data=suitability_data,
            )
        )
        yield AnswerContractEvent(
            data=AnswerContractData(
                product_count=1,
                winner_status=result.status,
                has_unknown_skin=(
                    result.status == "insufficient_evidence"
                ),
            )
        )
        yield CardDisplayContractEvent(data=card_display)
        yield ProductsEvent(data=ProductsData(cards=[card]))
        yield _image_citations_event(
            observations=[observation],
            product_ids=[card.product_id],
        )
        yield presentation_event
        yield MessageEvent(data=MessageData(content=message))
        yield self._success_end(turn)

    def _resolve_suitability_context(
        self,
        turn: UserTurn,
        observation: ImageIdentityObservation,
    ) -> tuple[
        SuitabilityContextClaims,
        SuitabilityAuthoritativeProfile | None,
    ]:
        explicit = _explicit_suitability_claims(turn, observation)
        if explicit.claims:
            return explicit, None
        if self._profile_resolver is None:
            return explicit, None

        owner = turn.profile_owner
        if owner is None:
            if self._profile_owner_factory is None:
                return explicit, None
            owner = self._profile_owner_factory(turn.session_id)
        resolved = self._profile_resolver(
            session_id=turn.session_id,
            profile_owner=owner,
        )
        skin = next(
            (
                item
                for item in resolved.values
                if item.field == "skin_type"
            ),
            None,
        )
        if skin is None:
            return explicit, None
        source = {
            "confirmed_session_fact": (
                SuitabilityContextSource.CONFIRMED_SESSION
            ),
            "long_term_profile": (
                SuitabilityContextSource.LONG_TERM_PROFILE
            ),
        }.get(skin.source)
        if source is None:
            return explicit, None

        provenance = skin.provenance
        assert provenance.source_turn_id is not None
        profile_version = provenance.profile_version
        profile = None
        profile_fields = {}
        if source is SuitabilityContextSource.LONG_TERM_PROFILE:
            assert profile_version is not None
            profile = SuitabilityAuthoritativeProfile(
                owner=owner,
                profile_version=profile_version,
                confirmed=True,
            )
            profile_fields = {
                "profile_owner": owner,
                "profile_version": profile_version,
                "profile_confirmed": True,
            }
        assert turn.image_bundle_id is not None
        claim = SuitabilityContextClaim(
            skin_target=skin.value,
            provenance=SuitabilityContextProvenance(
                current_bundle_id=turn.image_bundle_id,
                current_image_id=observation.image_id,
                session_id=turn.session_id,
                conversation_version=turn.conversation_version,
                source_kind=source,
                evidence_ref=(
                    f"profile-context:{source.value}:"
                    f"{provenance.source_turn_id}:skin"
                ),
                **profile_fields,
            ),
        )
        return SuitabilityContextClaims(claims=(claim,)), profile

    def _stream_standard_processor(
        self,
        turn: UserTurn,
        *,
        understanding: StructuredUnderstanding,
        route_decision: UnifiedRouteDecision,
        observations: list[ImageIdentityObservation],
    ) -> Iterator[SseEvent]:
        assert self._standard_processor is not None
        if route_decision.processor == "recommendation":
            expected_goal = (
                UnderstandingGoal.IMAGE_SIMILARITY
                if route_decision.product_bindings
                else UnderstandingGoal.RECOMMENDATION
            )
        elif route_decision.processor == "comparison":
            expected_goal = UnderstandingGoal.COMPARISON
        elif route_decision.processor == "product_knowledge":
            expected_goal = (
                understanding.goal
                if understanding.goal
                in {
                    UnderstandingGoal.KNOWLEDGE,
                    UnderstandingGoal.FOLLOWUP,
                    UnderstandingGoal.SUITABILITY,
                }
                else UnderstandingGoal.KNOWLEDGE
            )
        else:
            expected_goal = None
        if expected_goal is None:
            raise ValueError(
                "standard image delegation requires a standard route"
            )
        delegated_understanding = understanding
        if understanding.goal is not expected_goal:
            delegated_understanding = understanding.model_copy(
                update={
                    "goal": expected_goal,
                    "uncertainties": [],
                },
                deep=True,
            )
        if (
            route_decision.processor == "comparison"
            and delegated_understanding.topic is None
        ):
            records = {
                item.product_id: item
                for item in self._category_catalog.iter_category_records()
            }
            topics = {
                topic
                for binding in route_decision.product_bindings
                if (
                    topic := _topic_for_record(
                        records.get(binding.product_id)
                    )
                )
                is not None
            }
            if len(topics) != 1:
                yield from _stream_noncomparison_image_route(
                    UnifiedRouteDecision(
                        processor="clarification",
                        responsibility=Responsibility.CLARIFICATION,
                        presentation_mode="clarification",
                        continuity=route_decision.continuity,
                        focus_source="none",
                        clarification=(
                            "这些图片对应的商品不在同一品类，"
                            "请先确认这次想比较哪个使用方向。"
                        ),
                        clarification_code=ClarificationCode.TOPIC,
                    ),
                    turn=turn,
                )
                return
            topic = next(iter(topics))
            delegated_understanding = delegated_understanding.model_copy(
                update={
                    "topic": topic,
                    "exact_constraints": [
                        *delegated_understanding.exact_constraints,
                        CategoryDraft(value=topic),
                    ],
                },
                deep=True,
            )
        events = list(
            self._standard_processor.stream_understanding_body(
                turn,
                understanding=delegated_understanding,
                route_decision=route_decision,
                product_bindings=route_decision.product_bindings,
            )
        )
        citation = _image_citations_event(
            observations=observations,
            product_ids=[
                item.product_id
                for item in route_decision.product_bindings
            ],
        )
        inserted_citations = False
        for event in events:
            if (
                not inserted_citations
                and event.event in {"presentation_contract", "message"}
            ):
                yield citation
                inserted_citations = True
            yield event

    def _scenario_events(
        self,
        *,
        scenario_inputs: ScenarioInputBundle,
        product_ids: list[int],
    ) -> Iterator[SseEvent]:
        if (
            not scenario_inputs.query.scenarios
            or not product_ids
            or self._scenario_evidence is None
            or self._review_evidence is None
        ):
            return
        scenario_records = [
            record
            for product_id in product_ids
            for record in self._scenario_evidence.get_scenario_evidence(
                product_id,
                scenario_inputs.decision.evidence_requirements,
            )
        ]
        review_results = [
            self._review_evidence.read(product_id=product_id)
            for product_id in product_ids
        ]
        review_summaries = [
            summary
            for result in review_results
            if (
                summary := build_review_summary(result)
            ) is not None
        ]
        yield ScenarioEvidenceEvent(
            data=ScenarioEvidenceData(records=scenario_records)
        )
        yield ReviewEvidenceEvent(
            data=ReviewEvidenceData(
                approved_source_count=(
                    self._review_evidence.approved_source_count
                ),
                results=review_results,
                summaries=review_summaries,
            )
        )
        yield PitfallsEvent(
            data=PitfallsData(
                pitfalls=project_scenario_pitfalls(
                    scenario_records
                )
            )
        )

    def _stream_two_image_compare(
        self,
        turn: UserTurn,
        bundle: ImageBundle,
        payloads: tuple[ImageBundlePayload, ...],
        *,
        meaning: TurnMeaning | None = None,
        understanding: StructuredUnderstanding | None = None,
        snapshot: ConversationSnapshot | None = None,
    ) -> Iterator[SseEvent]:
        yield StageEvent(
            data=StageData(
                stage="image_observation",
                summary="正在确认两张图片中的商品。",
            )
        )
        observations: list[ImageIdentityObservation] = []
        for payload in payloads:
            observation = self._observe(payload)
            observations.append(observation)
            yield ImageObservationEvent(
                data=ImageObservationData(observation=observation)
            )
        if meaning is not None and understanding is not None:
            route = _route_confirmed_images(
                message=turn.message,
                meaning=meaning,
                understanding=understanding,
                snapshot=snapshot,
                observations=observations,
            )
            if route.processor == "image_identity":
                yield from self._stream_confirmed_image_identities(
                    turn,
                    observations,
                )
                return
            if (
                route.processor
                in {"recommendation", "comparison", "product_knowledge"}
                and self._standard_processor is not None
            ):
                yield from self._stream_standard_processor(
                    turn,
                    understanding=understanding,
                    route_decision=route,
                    observations=observations,
                )
                return
            if route.processor != "comparison":
                yield from _stream_noncomparison_image_route(
                    route,
                    turn=turn,
                )
                return

        context_result = build_multi_image_context(
            mode="compare",
            bundle=bundle,
            identity_observations=observations,
        )
        if context_result.kind != "ready":
            yield _error_event("GUIDE_INTERNAL_ERROR")
            return
        assert context_result.context is not None
        preparation = self._two_image_compare.prepare(
            context_result.context
        )
        if preparation.kind == "clarification":
            yield IntentEvent(data=IntentData(mode="clarify"))
            assert preparation.message is not None
            assert preparation.code is not None
            yield ClarifyEvent(
                data=ClarifyData(
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
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )
            return
        if preparation.kind != "ready":
            yield _error_event("GUIDE_INTERNAL_ERROR")
            return
        assert preparation.decision_result is not None
        result = preparation.decision_result
        cards = self._comparison_cards(result)
        comparison_data = _comparison_data(result)
        card_display = comparison_card_display(cards)
        presentation_event = self._presentation_event(
            mode="comparison",
            user_need_summary=turn.message.strip(),
            winner_status=result.outcome.status,
            card_display=card_display,
            cards=cards,
            winner_product_id=(
                result.outcome.winner_reference.product_id
                if result.outcome.winner_reference is not None
                else None
            ),
            winner_tie_reason=result.outcome.tie_reason,
        )
        message = _presentation_compatibility_message(
            presentation_event,
            default=_comparison_summary(result),
        )

        yield IntentEvent(data=IntentData(mode="image_compare"))
        yield StageEvent(
            data=StageData(
                stage="decision",
                summary="正在比较两款商品的参考价格。",
            )
        )
        yield DecisionProcessEvent(
            data=DecisionProcessData(
                ordered_product_ids=list(result.ordered_product_ids),
                winner_status=result.outcome.status,
                evidence_refs=list(result.outcome.evidence_refs),
                comparison_data=comparison_data,
            )
        )
        yield AnswerContractEvent(
            data=AnswerContractData(
                product_count=2,
                winner_status=result.outcome.status,
                has_unknown_skin=True,
            )
        )
        yield CardDisplayContractEvent(data=card_display)
        yield ProductsEvent(data=ProductsData(cards=cards))
        yield _image_citations_event(
            observations=observations,
            product_ids=[card.product_id for card in cards],
        )
        yield presentation_event
        yield MessageEvent(data=MessageData(content=message))
        yield self._success_end(turn)

    def _stream_multi_image_compare(
        self,
        turn: UserTurn,
        bundle: ImageBundle,
        payloads: tuple[ImageBundlePayload, ...],
        *,
        meaning: TurnMeaning | None = None,
        understanding: StructuredUnderstanding | None = None,
        snapshot: ConversationSnapshot | None = None,
    ) -> Iterator[SseEvent]:
        image_count = len(payloads)
        yield StageEvent(
            data=StageData(
                stage="image_observation",
                summary=f"正在确认 {image_count} 张图片中的商品。",
            )
        )
        observations: list[ImageIdentityObservation] = []
        for payload in payloads:
            observation = self._observe(payload)
            observations.append(observation)
            yield ImageObservationEvent(
                data=ImageObservationData(observation=observation)
            )
        if meaning is not None and understanding is not None:
            route = _route_confirmed_images(
                message=turn.message,
                meaning=meaning,
                understanding=understanding,
                snapshot=snapshot,
                observations=observations,
            )
            if route.processor == "image_identity":
                yield from self._stream_confirmed_image_identities(
                    turn,
                    observations,
                )
                return
            if (
                route.processor
                in {"recommendation", "comparison", "product_knowledge"}
                and self._standard_processor is not None
            ):
                yield from self._stream_standard_processor(
                    turn,
                    understanding=understanding,
                    route_decision=route,
                    observations=observations,
                )
                return
            if route.processor != "comparison":
                yield from _stream_noncomparison_image_route(
                    route,
                    turn=turn,
                )
                return

        context_result = build_multi_image_context(
            mode="compare",
            bundle=bundle,
            identity_observations=observations,
        )
        if context_result.kind != "ready":
            yield _error_event("GUIDE_INTERNAL_ERROR")
            return
        assert context_result.context is not None
        preparation = self._multi_image_compare.prepare(
            context_result.context,
            authorization=(
                MultiImageCompareBundleAuthorizationRequest.from_user_turn(
                    turn
                )
            ),
        )
        if preparation.kind == "clarification":
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
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
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )
            return
        if preparation.kind != "ready":
            yield _error_event("GUIDE_INTERNAL_ERROR")
            return

        result = preparation.decision_result
        cards = self._comparison_cards(result)
        comparison_data = _comparison_data(result)
        card_display = comparison_card_display(cards)
        presentation_event = self._presentation_event(
            mode="comparison",
            user_need_summary=turn.message.strip(),
            winner_status=result.outcome.status,
            card_display=card_display,
            cards=cards,
            winner_product_id=(
                result.outcome.winner_reference.product_id
                if result.outcome.winner_reference is not None
                else None
            ),
            winner_tie_reason=result.outcome.tie_reason,
        )
        message = _presentation_compatibility_message(
            presentation_event,
            default=_comparison_summary(result),
        )
        yield IntentEvent(data=IntentData(mode="image_compare"))
        yield StageEvent(
            data=StageData(
                stage="decision",
                summary=(
                    f"正在比较这 {image_count} 款商品的参考价格。"
                ),
            )
        )
        yield DecisionProcessEvent(
            data=DecisionProcessData(
                ordered_product_ids=list(result.ordered_product_ids),
                winner_status=result.outcome.status,
                evidence_refs=list(result.outcome.evidence_refs),
                comparison_data=comparison_data,
            )
        )
        yield AnswerContractEvent(
            data=AnswerContractData(
                product_count=image_count,
                winner_status=result.outcome.status,
                has_unknown_skin=True,
            )
        )
        yield CardDisplayContractEvent(data=card_display)
        yield ProductsEvent(data=ProductsData(cards=cards))
        yield _image_citations_event(
            observations=observations,
            product_ids=[card.product_id for card in cards],
        )
        yield presentation_event
        yield MessageEvent(data=MessageData(content=message))
        yield self._success_end(turn)

    def _success_end(self, turn: UserTurn) -> EndEvent:
        if self._conversation_state is not None:
            current = self._conversation_state.load(turn.session_id)
            if (
                current is not None
                and current.profile_owner != turn.profile_owner
            ):
                raise ConversationStateConflict(turn.session_id)
            authoritative_version = (
                current.version if current is not None else 0
            )
            if turn.conversation_version != authoritative_version:
                raise ConversationStateConflict(turn.session_id)
            if current is None:
                replacement = ConversationSnapshot(
                    session_id=turn.session_id,
                    version=1,
                    profile_owner=turn.profile_owner,
                    has_image_delivery=True,
                )
            else:
                replacement = current.model_copy(
                    update={
                        "version": authoritative_version + 1,
                        "has_image_delivery": True,
                    },
                    deep=True,
                )
            saved = self._conversation_state.save(
                replacement,
                expected_version=authoritative_version,
            )
            return EndEvent(
                data=EndData(conversation_version=saved.version)
            )

        owner = turn.profile_owner
        key = (
            owner.scope if owner is not None else "",
            owner.subject_id if owner is not None else "",
            turn.session_id,
        )
        with self._delivery_versions_lock:
            version = max(
                turn.conversation_version,
                self._delivery_versions.get(key, 0),
            ) + 1
            self._delivery_versions[key] = version
        return EndEvent(
            data=EndData(conversation_version=version)
        )

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
        for product_id in product_ids:
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
        user_need_summary: str,
        winner_status: str | None,
        card_display: CardDisplayContract,
        cards: tuple[ProductCard, ...] | list[ProductCard],
        winner_product_id: int | None = None,
        winner_tie_reason: str | None = None,
    ) -> PresentationContractEvent:
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
            user_need_summary=user_need_summary,
            winner_status=winner_status,
            winner_product_id=winner_product_id,
            winner_tie_reason=winner_tie_reason,
            card_display=card_display,
            cards=cards,
            selection_slots=(),
            concept_slots=(),
            merchant_claims=(),
            review_summaries=review_summaries,
            pitfalls=(),
        )
        return PresentationContractEvent(
            data=self._presentation_compiler.compile(
                PresentationCompileInputs(
                    packet=packet,
                    card_display=card_display,
                )
            )
        )

    def _build_plan(self, decision: DecisionResult) -> ResponsePlan:
        return build_response_plan(
            decision,
            product_facts={
                product_id: (
                    self._presentation_facts.get_presentation_facts(
                        product_id
                    )
                )
                for product_id in decision.ordered_product_ids
            },
        )


def _route_confirmed_images(
    *,
    message: str,
    meaning: TurnMeaning,
    understanding: StructuredUnderstanding,
    snapshot: ConversationSnapshot | None,
    observations: list[ImageIdentityObservation],
) -> UnifiedRouteDecision:
    references: list[ConfirmedImageProductRef] = []
    for ordinal, observation in enumerate(observations, start=1):
        if (
            observation.identity_state is not IdentityState.CONFIRMED
            or observation.confirmed_product_id is None
        ):
            return UnifiedRouteDecision(
                processor="clarification",
                responsibility=Responsibility.CLARIFICATION,
                presentation_mode="clarification",
                continuity="continue",
                focus_source="none",
                clarification=(
                    "图片信息还不足以确认全部商品，请换更清晰的正面图。"
                ),
                clarification_code=ClarificationCode.REFERENCE,
            )
        references.append(
            ConfirmedImageProductRef(
                image_ordinal=ordinal,
                product_id=observation.confirmed_product_id,
            )
        )
    return route_unified_turn(
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        current_image_products=tuple(references),
        safety_signal=admit_safety_signal(
            message=message,
            candidates=meaning.observation_candidates,
        ),
    )


def _stream_noncomparison_image_route(
    route: UnifiedRouteDecision,
    *,
    turn: UserTurn,
) -> Iterator[SseEvent]:
    if route.processor == "safety_escalation":
        question = (
            "先暂停新产品和刺激性护肤；"
            "如果破皮、渗出或疼痛持续，请尽快就医。"
        )
        code = ClarificationCode.CONCERN
    elif route.processor == "clarification":
        assert route.clarification is not None
        assert route.clarification_code is not None
        question = route.clarification
        code = route.clarification_code
    else:
        question = "多张图片会按商品对比处理，请确认是否继续比较。"
        code = ClarificationCode.GOAL
    yield IntentEvent(data=IntentData(mode="clarify"))
    yield ClarifyEvent(
        data=ClarifyData(
            question=question,
            clarification_code=code,
        )
    )
    yield EndEvent(
        data=EndData(
            conversation_version=turn.conversation_version
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


_OCR_STATE_PUBLIC = {
    "not_run": "未运行包装文字核对",
    "not_configured": "当前未配置包装文字核对",
    "unavailable": "未提取到有效包装文字",
    "observed": "已完成包装文字核对",
}
_OCR_CONSISTENCY_PUBLIC = {
    "not_checked": "未核对",
    "consistent": "与候选商品一致",
    "conflict": "与候选商品不一致",
    "indeterminate": "暂未完整确认",
}


def _image_citations_event(
    *,
    observations: list[ImageIdentityObservation],
    product_ids: list[int],
) -> CitationsEvent:
    citations: list[CitationData] = []
    for observation in observations:
        confidence = observation.visual_confidence
        citations.append(
            CitationData(
                id=f"visual:{observation.image_id}",
                title="图片匹配依据",
                snippet="图片相似度匹配已完成，结果由本次上传图片生成。",
                confidence=(
                    max(0.0, min(1.0, confidence))
                    if confidence is not None
                    else None
                ),
                source_kind="visual_model",
            )
        )
        ocr_state_label = _OCR_STATE_PUBLIC[
            observation.ocr_state.value
        ]
        brand_label = _OCR_CONSISTENCY_PUBLIC[
            observation.ocr_brand_consistency.value
        ]
        product_name_label = _OCR_CONSISTENCY_PUBLIC[
            observation.ocr_product_name_consistency.value
        ]
        citations.append(
            CitationData(
                id=f"ocr:{observation.image_id}",
                title="包装文字核对",
                snippet=(
                    f"{ocr_state_label}；"
                    f"品牌信息{brand_label}；"
                    f"商品名称{product_name_label}。"
                    "包装文字只用于辅助确认，不参与商品排序。"
                ),
                source_kind="ocr_observation",
            )
        )
    for product_id in dict.fromkeys(product_ids):
        citations.append(
            CitationData(
                id=f"product:{product_id}",
                title="商品资料",
                snippet="商品身份和卡片信息以已审核的商品资料为准。",
                source_kind="canonical",
            )
        )
    return CitationsEvent(data=CitationsData(citations=citations))


def _image_retrieval_result(
    observation: ImageIdentityObservation,
    *,
    category_records: dict[int, CategoryRecord],
    exclude_product_id: int | None = None,
) -> RetrievalResult:
    candidates: list[CandidateRef] = []
    for rank, product_id in enumerate(
        observation.candidate_product_ids,
        start=1,
    ):
        if product_id == exclude_product_id:
            continue
        record = category_records.get(product_id)
        category_state = (
            record.state if record is not None else "unknown"
        )
        category = (
            record.value
            if record is not None
            and record.state == "known"
            and record.value is not None
            else ""
        )
        candidates.append(
            CandidateRef(
                product_id=product_id,
                source="image_index",
                canonical_category=category,
                canonical_category_state=category_state,
                retrieval_reason=f"image_similarity_rank={rank}",
            )
        )
    return RetrievalResult(
        candidates=candidates,
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[] if candidates else ["image_index"],
    )


def _summary_fragment(decision: DecisionResult) -> str:
    if decision.winner_status is WinnerStatus.NO_CANDIDATE:
        return (
            "已经确认图片中的商品，但暂时没有找到"
            "同时符合你要求的相似款。"
        )
    if decision.winner_status is WinnerStatus.INSUFFICIENT_FOR_WINNER:
        return (
            "相似点是都在图片商品的同品类范围内；"
            "不同点主要看参考价、品牌主打和使用感路线。"
            "现有信息还不足以替你定下唯一一款。"
        )
    if decision.winner_status is WinnerStatus.TIED_BY_BUSINESS_EVIDENCE:
        return (
            "相似点是都在图片商品的同品类范围内；"
            "不同点主要看参考价、品牌主打和使用感路线。"
            "这几款目前各有取舍，先不替你定死唯一一款。"
        )
    return (
        "相似点是都在图片商品的同品类范围内；"
        "不同点主要看参考价、品牌主打和使用感路线。"
        "下面这些更贴近你补充的要求。"
    )


def _is_identity_request(message: str) -> bool:
    normalized = message.casefold()
    return any(
        marker in normalized
        for marker in (
            "这是什么",
            "什么商品",
            "哪款商品",
            "帮我识别",
            "识别一下",
            "identify",
        )
    )


def _is_suitability_request(message: str) -> bool:
    normalized = message.casefold()
    return any(
        marker in normalized
        for marker in (
            "适合",
            "适不适合",
            "适配",
            "能用吗",
            "可以用吗",
            "suitable",
        )
    )


def _presentation_compatibility_message(
    event: PresentationContractEvent,
    *,
    default: str,
) -> str:
    if event.data.copy_source == "fallback":
        return default
    parts = tuple(
        section.copy_text.strip()
        for section in event.data.sections
        if section.kind in {"summary", "product", "closing"}
        and section.copy_text is not None
        and section.copy_text.strip()
    )
    return "\n".join(parts) if parts else default


def _explicit_suitability_claims(
    turn: UserTurn,
    observation: ImageIdentityObservation,
) -> SuitabilityContextClaims:
    understanding = understand_text(turn.message)
    skin_target = next(
        (
            item.value
            for item in understanding.exact_constraints
            if isinstance(item, SkinDraft)
        ),
        None,
    )
    if skin_target is None:
        return SuitabilityContextClaims(claims=())
    assert turn.image_bundle_id is not None
    return SuitabilityContextClaims(
        claims=(
            SuitabilityContextClaim(
                skin_target=skin_target.value,
                provenance=SuitabilityContextProvenance(
                    current_bundle_id=turn.image_bundle_id,
                    current_image_id=observation.image_id,
                    session_id=turn.session_id,
                    conversation_version=turn.conversation_version,
                    source_kind=(
                        SuitabilityContextSource.CURRENT_EXPLICIT_INPUT
                    ),
                    evidence_ref=(
                        f"conversation:{turn.session_id}:"
                        f"version:{turn.conversation_version}:skin"
                    ),
                ),
            ),
        )
    )


def _suitability_data(
    result: ImageSuitabilityDecisionResult,
) -> ImageSuitabilityData:
    return ImageSuitabilityData(
        status=result.status,
        reason=result.reason,
        reference=ImageSuitabilityReferenceData(
            ordinal=result.reference.ordinal,
            image_id=result.reference.image_id,
            product_id=result.reference.product_id,
        ),
        context_source=result.context.source.value,
        skin_target=result.context.skin_target.value,
        evaluated_skin_fact=ImageSuitabilityFactData(
            state=result.evaluated_skin_fact.state.value,
            values=(
                list(result.evaluated_skin_fact.values)
                if result.evaluated_skin_fact.values is not None
                else None
            ),
            source_refs=list(
                result.evaluated_skin_fact.source_refs
            ),
        ),
        evidence_refs=list(result.evidence_refs),
    )


def _suitability_summary(
    result: ImageSuitabilityDecisionResult,
) -> str:
    if result.status == "suitable":
        return (
            "现有商品资料支持它用于你刚说明的肤质，"
            "实际耐受仍要结合使用后的肤感判断。"
        )
    if result.status == "not_suitable":
        return (
            "现有商品资料与刚说明的肤质并不匹配，"
            "先不要把它作为优先选择。"
        )
    return (
        "已经确认图片中的商品，但现有肤质资料不足，"
        "暂时不能判断它适合或不适合。"
    )


def _comparison_data(
    result: ImageCompareDecisionResult
    | MultiImageCompareDecisionResult,
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


def _comparison_summary(
    result: ImageCompareDecisionResult
    | MultiImageCompareDecisionResult,
) -> str:
    outcome = result.outcome
    image_count = len(result.references)
    count_label = f"{image_count} 张"
    if outcome.status == "winner":
        assert outcome.winner_reference is not None
        label = ("第一张", "第二张", "第三张", "第四张")[
            outcome.winner_reference.ordinal - 1
        ]
        return (
            f"按当前可审计价格证据，{label}对应商品价格更低。"
            f"{count_label}商品卡按上传顺序展示；"
            "未评估肤质或功效优劣。"
        )
    if outcome.status == "tie":
        return (
            f"{count_label}图片中最低可审计价格相同，当前结论为平局。"
            "商品卡按上传顺序展示；未评估肤质或功效优劣。"
        )
    return (
        f"{count_label}图片已确认商品身份，但当前可审计价格证据不足，"
        "不能指定胜出商品。商品卡仍按上传顺序展示。"
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
