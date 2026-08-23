from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.guide.application.unified_guide_flow as unified_flow_module
from app.guide.adapters.state import InMemoryConversationState
from app.guide.application.contracts import UserTurn
from app.guide.application.execution_contracts import (
    ClarificationLaneState,
    ClarificationTerminal,
    ConversationStateDelta,
    ExecutionResult,
    ImageRoutingEvidence,
    LaneMutation,
    ProcessorExecutionInput,
    TurnIdentity,
)
from app.guide.application.image_bundle_state import ImageBundlePayload
from app.guide.application.unified_guide_flow import (
    UnifiedGuideFlow,
    UnifiedUnderstandingAdapter,
)
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConsultationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    KnowledgeSlotState,
    PendingBudgetRange,
    PendingRecommendationContext,
    PendingReplySlot,
    PendingTurn,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.consultation_state import (
    ConsultationSubstate,
)
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.session_profile import (
    BaseSkinUpdate,
    SessionProfile,
    reduce_session_profile,
)
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
    ResolvedProductBinding,
)
from app.guide.presentation.sse_events import (
    ClarifyData,
    ClarifyEvent,
    EndData,
    EndEvent,
    IntentData,
    IntentEvent,
    MessageData,
    MessageEvent,
    StartData,
    StartEvent,
)
from app.guide.presentation.terminal_contract_guard import (
    GuideTerminalContractError,
)
from app.guide.understanding.contracts import (
    ImageBundle,
    ImageObservation,
    ProductMentionDraft,
    ReferenceDraft,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.image_contracts import (
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ObservationState,
    OcrObservationState,
    VisualObservationState,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    SemanticContext,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide.understanding import typed_image_action
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
    compose_text_recommendation_orchestrator,
)


def _meaning(
    operation: str,
    *,
    continuity: str = "new_task",
    next_gap: str | None = None,
    pending_response: str = "unknown",
):
    return TurnMeaning.model_validate(
        {
            "operation_hint": operation,
            "recommendation_mode": (
                "explore"
                if operation in {"recommendation", "image_similarity"}
                else None
            ),
            "recommendation_count": None,
            "recommendation_mode_basis": (
                {
                    "basis": (
                        "similar_alternatives"
                        if operation == "image_similarity"
                        else "broad_exploration"
                    ),
                    "source_text": (
                        "相似"
                        if operation == "image_similarity"
                        else "推荐"
                    ),
                }
                if operation in {"recommendation", "image_similarity"}
                else None
            ),
            "topic_hint": "sunscreen",
            "continuity_hint": continuity,
            "subject_scope_hint": "self",
            "pending_response_hint": pending_response,
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": next_gap,
            "question_meaning": "当前问题",
            "safety_language": "ordinary",
        },
        strict=True,
    )


def _safety_meaning(
    *,
    pending_response: str = "unknown",
) -> TurnMeaning:
    payload = _meaning(
        "assessment",
        continuity="continue",
        pending_response=pending_response,
    ).model_dump(mode="python")
    payload.update(
        {
            "recommendation_mode": None,
            "recommendation_count": None,
            "recommendation_mode_basis": None,
            "observation_candidates": [
                {
                    "observation_id": "obs_damage",
                    "code": "broken_skin",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "已经破皮",
                    "location": None,
                    "trigger": None,
                    "duration": "current",
                    "severity": "severe",
                }
            ],
            "question_meaning": "当前皮肤已经破皮",
        }
    )
    return TurnMeaning.model_validate(payload, strict=True)


def _understanding(goal: UnderstandingGoal):
    return StructuredUnderstanding(
        goal=goal,
        recommendation_mode=(
            "explore"
            if goal
            in {
                UnderstandingGoal.RECOMMENDATION,
                UnderstandingGoal.IMAGE_SIMILARITY,
            }
            else None
        ),
        recommendation_mode_basis=(
            "broad_exploration"
            if goal
            in {
                UnderstandingGoal.RECOMMENDATION,
                UnderstandingGoal.IMAGE_SIMILARITY,
            }
            else None
        ),
        recommendation_count=(
            3
            if goal
            in {
                UnderstandingGoal.RECOMMENDATION,
                UnderstandingGoal.IMAGE_SIMILARITY,
            }
            else None
        ),
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        relative_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning="当前问题",
    )


class RecordingTranslator:
    def __init__(self, meaning: TurnMeaning) -> None:
        self.meaning = meaning
        self.calls = []

    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> TurnMeaning:
        self.calls.append((message, context))
        return self.meaning


class RecordingTextProcessor:
    def __init__(self) -> None:
        self.preunderstood_calls = []
        self.raw_calls = []
        self.pending_calls = []
        self.pending_route_decisions = []

    def resolve_product_bindings(self, **kwargs):
        self.binding_request = kwargs
        return ()

    def execute(self, execution_input: ProcessorExecutionInput):
        evidence = execution_input.routing_evidence
        if evidence.pending_reply is not None:
            self.pending_calls.append(
                (
                    execution_input.turn_identity,
                    evidence.pending_reply,
                )
            )
            self.pending_route_decisions.append(
                execution_input.decision
            )
        else:
            self.preunderstood_calls.append(
                (
                    execution_input.turn_identity,
                    execution_input.understanding,
                    execution_input.decision,
                    evidence.product_resolution.bindings,
                )
            )
        return _clarification_execution(
            execution_input.decision,
            question="请补充筛选条件。",
            code=ClarificationCode.CONCERN,
        )

    def stream_understanding(
        self,
        turn,
        *,
        understanding,
        route_decision,
        product_bindings,
    ):
        self.preunderstood_calls.append(
            (
                turn,
                understanding,
                route_decision,
                product_bindings,
            )
        )
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question="请补充筛选条件。",
                clarification_code=ClarificationCode.CONCERN,
            )
        )
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )

    def stream(self, turn):
        self.raw_calls.append(turn)
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question="请补充筛选条件。",
                clarification_code=ClarificationCode.CONCERN,
            )
        )
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )

    def stream_pending_reply(
        self,
        turn,
        *,
        reply,
        route_decision=None,
    ):
        self.pending_calls.append((turn, reply))
        self.pending_route_decisions.append(route_decision)
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question="请补充筛选条件。",
                clarification_code=ClarificationCode.CONCERN,
            )
        )
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )


class RecordingConsultationProcessor:
    def __init__(self, *, dynamic_session: bool = False) -> None:
        self.calls = []
        self.meaning_calls = []
        self.route_decisions = []
        self.dynamic_session = dynamic_session

    def has_dynamic_session(self, turn) -> bool:
        self.dynamic_session_turn = turn
        return self.dynamic_session

    def execute(self, execution_input: ProcessorExecutionInput):
        evidence = execution_input.routing_evidence
        consultation = evidence.consultation
        if (
            self.dynamic_session
            or consultation.observations
            or consultation.hypothesis is not None
            or consultation.next_observation_gap is not None
        ):
            self.meaning_calls.append(
                (
                    execution_input.turn_identity,
                    execution_input.understanding,
                )
            )
        else:
            self.calls.append(execution_input.turn_identity)
        self.route_decisions.append(execution_input.decision)
        return _clarification_execution(
            execution_input.decision,
            question="请补充当前肤况。",
            code=ClarificationCode.CONCERN,
        )

    def stream(self, turn, *, route_decision=None):
        self.calls.append(turn)
        self.route_decisions.append(route_decision)
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question="请补充当前肤况。",
                clarification_code=ClarificationCode.CONCERN,
            )
        )
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )

    def stream_meaning(
        self,
        turn,
        *,
        meaning,
        route_decision=None,
    ):
        self.meaning_calls.append((turn, meaning))
        self.route_decisions.append(route_decision)
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question="请补充当前肤况。",
                clarification_code=ClarificationCode.CONCERN,
            )
        )
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )


def _image_routing_evidence(
    *,
    image_count: int,
    anchor_topic: TopicCode | None,
) -> ImageRoutingEvidence:
    created_at = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    payloads = []
    images = []
    observations = []
    for ordinal in range(1, image_count + 1):
        image_id = f"image_{ordinal:032d}"
        content = f"image-{ordinal}".encode("ascii")
        digest = sha256(content).hexdigest()
        payloads.append(
            ImageBundlePayload(
                image_id=image_id,
                ordinal=ordinal,
                content_sha256=digest,
                byte_size=len(content),
                content=content,
            )
        )
        images.append(
            ImageObservation(
                image_id=image_id,
                ordinal=ordinal,
                content_sha256=digest,
                media_type="image/jpeg",
                image_format="JPEG",
                width=4,
                height=3,
                byte_size=len(content),
            )
        )
        is_confirmed = ordinal == 1
        observations.append(
            ImageIdentityObservation(
                image_id=image_id,
                observation_state=ObservationState.PARTIAL,
                visual_state=VisualObservationState.OBSERVED,
                ocr_state=(
                    OcrObservationState.NOT_CONFIGURED
                    if is_confirmed
                    else OcrObservationState.NOT_RUN
                ),
                identity_state=(
                    IdentityState.CONFIRMED
                    if is_confirmed
                    else IdentityState.NO_CANDIDATE
                ),
                confirmed_product_id=53 if is_confirmed else None,
                candidate_product_ids=(53, 55) if is_confirmed else (),
                visual_confidence=0.99 if is_confirmed else None,
                similarity_margin=0.2 if is_confirmed else None,
                model_name="test-openclip",
                weights_sha256="a" * 64,
                preprocessing_version="test-preprocess-v1",
                vector_dimension=512,
                index_sha256="b" * 64,
                ocr_brand_consistency=(
                    IdentityEvidenceConsistency.NOT_CHECKED
                ),
                ocr_product_name_consistency=(
                    IdentityEvidenceConsistency.NOT_CHECKED
                ),
            )
        )
    return ImageRoutingEvidence(
        bundle=ImageBundle(
            bundle_id="bundle_" + "a" * 32,
            session_id="unified-flow",
            owner_token_sha256="f" * 64,
            version=1,
            created_at=created_at,
            expires_at=created_at + timedelta(minutes=15),
            images=images,
            focused_image_ordinal=1 if image_count == 1 else None,
        ),
        owner_token="owner_" + "b" * 43,
        payloads=tuple(payloads),
        observations=tuple(observations),
        anchor_topic=anchor_topic,
    )


class RecordingImageProcessor:
    def __init__(
        self,
        *,
        image_count: int = 1,
        anchor_topic: TopicCode | None = None,
    ) -> None:
        self.calls = []
        self.image_count = image_count
        self.anchor_topic = anchor_topic
        self.prepare_calls = []
        self.route_decisions = []

    def prepare_routing_evidence(self, turn):
        self.prepare_calls.append(turn)
        return _image_routing_evidence(
            image_count=self.image_count,
            anchor_topic=self.anchor_topic,
        )

    def semantic_image_count(self, turn) -> int:
        self.image_count_turn = turn
        return self.image_count

    def execute(self, execution_input: ProcessorExecutionInput):
        self.calls.append(execution_input)
        self.route_decisions.append(
            (
                execution_input.decision,
                execution_input.routing_evidence.image,
            )
        )
        return _clarification_execution(
            execution_input.decision,
            question="请补充图片信息。",
            code=ClarificationCode.REFERENCE,
        )

    def stream_understanding(
        self,
        turn,
        *,
        meaning,
        understanding,
        snapshot,
        route_decision=None,
        routing_evidence=None,
    ):
        self.calls.append(
            (turn, meaning, understanding, snapshot)
        )
        self.route_decisions.append(
            (route_decision, routing_evidence)
        )
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question="请补充图片信息。",
                clarification_code=ClarificationCode.REFERENCE,
            )
        )
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )


class RecordingExecutionProcessor:
    def __init__(self) -> None:
        self.calls = []
        self.results = []

    def resolve_product_resolution(self, **kwargs):
        self.resolution_request = kwargs
        return ProductMentionResolution(bindings=())

    def execute(
        self,
        execution_input: ProcessorExecutionInput,
    ) -> ExecutionResult:
        evidence = execution_input.routing_evidence
        self.calls.append(
            {
                "turn_identity": execution_input.turn_identity,
                "understanding": execution_input.understanding,
                "snapshot": execution_input.current_snapshot,
                "route_decision": execution_input.decision,
                "product_resolution": evidence.product_resolution,
                "pending_reply": evidence.pending_reply,
                "routing_evidence": evidence,
                "profile_context": evidence.profile_context,
            }
        )
        result = ExecutionResult(
            decision=execution_input.decision,
            state_delta=ConversationStateDelta(
                clarification=LaneMutation[ClarificationLaneState](
                    action="replace",
                    value=ClarificationLaneState(
                        progress=ClarificationProgress(
                            gap=ClarificationCode.CONCERN,
                            attempts=1,
                        ),
                    ),
                )
            ),
            terminal=ClarificationTerminal(
                data=ClarifyData(
                    question="请补充筛选条件。",
                    clarification_code=ClarificationCode.CONCERN,
                )
            ),
            audit_events=(
                IntentEvent(data=IntentData(mode="clarify")),
            ),
        )
        self.results.append(result)
        return result


def _clarification_execution(
    decision: UnifiedRouteDecision,
    *,
    question: str,
    code: ClarificationCode,
) -> ExecutionResult:
    return ExecutionResult(
        decision=decision,
        state_delta=ConversationStateDelta(
            clarification=LaneMutation[ClarificationLaneState](
                action="replace",
                value=ClarificationLaneState(
                    progress=ClarificationProgress(
                        gap=code,
                        attempts=1,
                    ),
                ),
            )
        ),
        terminal=ClarificationTerminal(
            data=ClarifyData(
                question=question,
                clarification_code=code,
            )
        ),
        audit_events=(
            IntentEvent(data=IntentData(mode="clarify")),
        ),
    )


def _turn(
    message: str = "推荐防晒",
    *,
    version: int = 0,
    profile_owner: ProfileOwnerRef | None = None,
    image_action: str | None = None,
    include_image_bundle: bool = False,
) -> UserTurn:
    return UserTurn(
        identity=TurnIdentity(
            session_id="unified-flow",
            request_id=f"request_unified-flow_{version:04d}",
            turn_id=f"turn_unified-flow_{version:04d}",
        ),
        session_id="unified-flow",
        message=message,
        image_action=image_action,
        profile_owner=profile_owner,
        image_bundle_id=(
            "bundle_" + "a" * 32
            if include_image_bundle
            else None
        ),
        image_bundle_version=1 if include_image_bundle else None,
        image_bundle_token=(
            "owner_" + "b" * 43
            if include_image_bundle
            else None
        ),
        conversation_version=version,
    )


def _decode_frames(frames) -> list[tuple[str, dict]]:
    decoded = []
    for frame in frames:
        event_line, data_line, _ = frame.split(b"\n", maxsplit=2)
        decoded.append(
            (
                event_line.removeprefix(b"event: ").decode("ascii"),
                json.loads(
                    data_line.removeprefix(b"data: ").decode("utf-8")
                ),
            )
        )
    return decoded


def _decoded_events(frames) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(event=event, data=SimpleNamespace(**data))
        for event, data in _decode_frames(frames)
    ]


def test_processor_receives_exact_decision_then_flow_reduces_and_saves() -> None:
    translator = RecordingTranslator(_meaning("recommendation"))
    processor = RecordingExecutionProcessor()
    state = InMemoryConversationState()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=processor,
        consultation_processor=RecordingExecutionProcessor(),
        conversation_state=state,
    )

    events = _decoded_events(flow.stream(_turn()))

    assert [event.event for event in events] == [
        "start",
        "intent",
        "clarify",
        "end",
    ]
    call = processor.calls[0]
    result_decision = call["route_decision"]
    stored = state.load("unified-flow")
    assert stored is not None
    assert stored.version == 1
    assert stored.active_owner is Responsibility.RECOMMENDATION
    assert stored.active_focus.slot == "reply"
    assert stored.reply_slot.value.gap is ClarificationCode.CONCERN
    assert events[-1].data.conversation_version == 1
    assert result_decision.processor == "recommendation"
    assert processor.results[0].decision is result_decision


def test_flow_passes_ingress_turn_identity_to_reducer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    real_reduce = unified_flow_module.reduce_conversation_state

    def recording_reduce(**kwargs):
        captured.append(kwargs["turn_identity"])
        return real_reduce(**kwargs)

    monkeypatch.setattr(
        unified_flow_module,
        "reduce_conversation_state",
        recording_reduce,
    )
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(
            _meaning("recommendation"),
        ),
        text_processor=RecordingExecutionProcessor(),
        consultation_processor=RecordingExecutionProcessor(),
        conversation_state=InMemoryConversationState(),
    )
    turn = _turn()

    list(flow.stream(turn))

    assert captured == [turn.identity]


def test_read_only_observer_sees_each_execution_boundary_once() -> None:
    class RecordingObserver:
        def __init__(self) -> None:
            self.calls = []

        def compiled(self, **values) -> None:
            self.calls.append(("compiled", values))

        def routed(self, **values) -> None:
            self.calls.append(("routed", values))

        def result_received(self, **values) -> None:
            self.calls.append(("result", values))

        def state_reduced(self, **values) -> None:
            self.calls.append(("reduced", values))

        def envelope_materialized(self, **values) -> None:
            self.calls.append(("envelope", values))

        def state_saved(self, **values) -> None:
            self.calls.append(("saved", values))

    observer = RecordingObserver()
    processor = RecordingExecutionProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(
            _meaning("recommendation"),
        ),
        text_processor=processor,
        consultation_processor=RecordingExecutionProcessor(),
        conversation_state=InMemoryConversationState(),
        observer=observer,
    )

    list(flow.stream(_turn()))

    assert [name for name, _ in observer.calls] == [
        "compiled",
        "routed",
        "result",
        "reduced",
        "envelope",
        "saved",
    ]
    route = observer.calls[1][1]["decision"]
    assert processor.calls[0]["route_decision"] is route
    assert observer.calls[2][1]["result"].decision is route
    assert observer.calls[4][1]["envelope"].decision is route


def test_invalid_public_envelope_performs_zero_state_saves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CountingConversationState(InMemoryConversationState):
        def __init__(self) -> None:
            super().__init__()
            self.save_calls = 0

        def save(self, snapshot, *, expected_version):
            self.save_calls += 1
            return super().save(
                snapshot,
                expected_version=expected_version,
            )

    def reject_public_envelope(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("invalid public envelope")

    monkeypatch.setattr(
        unified_flow_module,
        "materialize_execution_envelope",
        reject_public_envelope,
    )
    state = CountingConversationState()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(
            _meaning("recommendation"),
        ),
        text_processor=RecordingExecutionProcessor(),
        consultation_processor=RecordingExecutionProcessor(),
        conversation_state=state,
    )

    events = _decoded_events(flow.stream(_turn()))

    assert [event.event for event in events] == ["start", "error"]
    assert state.save_calls == 0
    assert state.load("unified-flow") is None


def test_profile_context_is_derived_from_the_loaded_snapshot_once() -> None:
    owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="unified_profile_context_0001",
    )
    profile = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            BaseSkinUpdate(
                value="dry",
                confirmation="confirmed",
            ),
        ),
        subject_scope="self",
        source_turn_id="turn_unified_profile_0001",
        conversation_version=1,
    ).profile
    state = InMemoryConversationState()
    state.save(
        ConversationSnapshot(
            session_id="unified-flow",
            version=1,
            profile_owner=owner,
            session_profile=profile,
        ),
        expected_version=0,
    )
    translator = RecordingTranslator(_meaning("recommendation"))
    processor = RecordingExecutionProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=processor,
        consultation_processor=RecordingExecutionProcessor(),
        conversation_state=state,
    )

    list(
        flow.stream(
            _turn(
                version=1,
                profile_owner=owner,
            )
        )
    )

    context = processor.calls[0]["profile_context"]
    assert context is not None
    assert [(item.field, item.value) for item in context.values] == [
        ("skin_type", "dry")
    ]
    assert translator.calls[0][1].confirmed_profile_fields == (
        "skin_type",
    )


def test_stale_turn_is_rejected_before_processor_execution() -> None:
    state = InMemoryConversationState()
    state.save(
        ConversationSnapshot(
            session_id="unified-flow",
            version=1,
            active_owner=Responsibility.GENERAL_KNOWLEDGE,
            active_focus=ActiveFocus(slot="knowledge"),
            knowledge_slot=KnowledgeSlotState(
                question="视黄醇是什么",
            ),
        ),
        expected_version=0,
    )
    processor = RecordingExecutionProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(
            _meaning("recommendation"),
        ),
        text_processor=processor,
        consultation_processor=RecordingExecutionProcessor(),
        conversation_state=state,
    )

    events = _decoded_events(flow.stream(_turn(version=0)))

    assert [event.event for event in events] == ["start", "error"]
    assert processor.calls == []
    assert state.load("unified-flow").version == 1


def test_unified_flow_compiles_translated_turn_meaning_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meaning = _meaning("recommendation")
    translator = RecordingTranslator(meaning)
    compiler_calls = []
    compiled_results = []
    real_compile = unified_flow_module.compile_turn_meaning

    def recording_compile(**kwargs):
        compiler_calls.append(kwargs)
        result = real_compile(**kwargs)
        compiled_results.append(result)
        return result

    monkeypatch.setattr(
        unified_flow_module,
        "compile_turn_meaning",
        recording_compile,
    )
    text = RecordingExecutionProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=RecordingExecutionProcessor(),
        conversation_state=InMemoryConversationState(),
    )

    events = _decoded_events(flow.stream(_turn()))

    assert [event.event for event in events] == [
        "start",
        "intent",
        "clarify",
        "end",
    ]
    assert len(translator.calls) == 1
    assert len(compiler_calls) == 1
    assert compiler_calls[0]["meaning"] is meaning
    assert compiler_calls[0]["message"] == "推荐防晒"
    assert text.calls[0]["understanding"] is compiled_results[0]
    route = text.calls[0]["route_decision"]
    assert route.processor == "recommendation"


def test_unified_flow_rejects_processor_sse_output() -> None:
    class LegacyMessageTextProcessor(RecordingTextProcessor):
        def execute(self, execution_input):
            return (
                StartEvent(
                    data=StartData(
                        session_id=(
                            execution_input.turn_identity.session_id
                        )
                    )
                ),
                IntentEvent(data=IntentData(mode="recommend")),
                MessageEvent(data=MessageData(content="legacy")),
                EndEvent(
                    data=EndData(
                        conversation_version=(
                            execution_input.routing_evidence
                            .conversation_version
                        )
                    )
                ),
            )

    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(
            _meaning("recommendation"),
        ),
        text_processor=LegacyMessageTextProcessor(),
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=InMemoryConversationState(),
    )

    events = _decoded_events(flow.stream(_turn()))

    assert [event.event for event in events] == ["start", "error"]


def test_unified_flow_reconciles_return_alias_before_text_execution() -> None:
    class MissingAliasTextProcessor(RecordingTextProcessor):
        def resolve_product_resolution(self, **kwargs):
            self.resolution_request = kwargs
            return ProductMentionResolution(
                bindings=(),
                issue="missing_reference",
            )

    state = InMemoryConversationState()
    candidate = DisplayedCandidateRef(
        product_id=38,
        ordinal=1,
        skin_match="unknown",
        matched_efficacies=(),
    )
    state.save(
        ConversationSnapshot(
            session_id="unified-flow",
            version=1,
            active_owner=Responsibility.GENERAL_KNOWLEDGE,
            active_focus=ActiveFocus(slot="knowledge"),
            recommendation_slot=RecommendationSlotState(
                query_context=RecommendationQueryContext(
                    category="serum",
                    recommendation_mode_basis="broad_exploration",
                ),
                candidates=(candidate,),
            ),
            product_slot=ProductSlotState(
                products=(candidate,),
                focused_product_id=38,
            ),
            knowledge_slot=KnowledgeSlotState(
                question="烟酰胺是什么",
            ),
        ),
        expected_version=0,
    )
    message = "回到B5那瓶，它页面里的品牌主打有哪些"
    meaning = TurnMeaning(
        operation_hint="followup",
        topic_hint="serum",
        continuity_hint="return_to_focus",
        subject_scope_hint="self",
        reference_mentions=(
            {
                "raw_text": "那瓶",
                "object_family_hint": "product",
                "ordinal_hint": None,
                "plurality_hint": "single",
            },
        ),
        product_mentions=({"raw_text": "B5"},),
        question_meaning="查看B5的品牌主打",
        safety_language="ordinary",
    )
    text = MissingAliasTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )

    events = _decoded_events(
        flow.stream(
            _turn(
                message,
                version=1,
            )
        )
    )

    assert events[-1].event == "end"
    route = text.preunderstood_calls[0][2]
    assert route.processor == "product_knowledge"
    assert [item.product_id for item in route.product_bindings] == [38]


def test_unified_flow_routes_exact_budget_revision_as_correction() -> None:
    state = InMemoryConversationState()
    candidates = (
        DisplayedCandidateRef(
            product_id=38,
            ordinal=1,
            skin_match="matched",
            matched_efficacies=("修护",),
        ),
        DisplayedCandidateRef(
            product_id=91,
            ordinal=2,
            skin_match="matched",
            matched_efficacies=("修护",),
        ),
    )
    snapshot = ConversationSnapshot(
        session_id="unified-flow",
        version=1,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(slot="recommendation"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                budget_maximum=Decimal("500"),
                skin="sensitive",
                efficacy="repair",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=3,
            ),
            candidates=candidates,
        ),
    )
    state.save(snapshot, expected_version=0)
    message = "预算降到 100 元呢"
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "followup",
            "topic_hint": "serum",
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "reference_mentions": [
                {
                    "raw_text": "预算",
                    "object_family_hint": "constraint",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            "product_mentions": [],
            "budget_candidates": [
                {
                    "raw_text": "100 元",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "100",
                }
            ],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "把原推荐预算上限改为100元",
            "safety_language": "ordinary",
        },
        strict=True,
    )
    compiled = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=1,
            snapshot=snapshot,
        ),
    )
    text = RecordingTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )

    list(flow.stream(_turn(message, version=1)))

    route = text.preunderstood_calls[0][2]
    assert route.processor == "recommendation"
    assert route.continuity == "correct"


@pytest.mark.parametrize(
    ("message", "raw_text"),
    (
        ("太贵了，最多一百吧", "最多一百"),
        ("其他要求照旧，价钱上限改成100", "价钱上限改成100"),
    ),
)
def test_continuing_single_budget_replaces_existing_slot(
    message: str,
    raw_text: str,
) -> None:
    state = InMemoryConversationState()
    candidates = (
        DisplayedCandidateRef(
            product_id=38,
            ordinal=1,
            skin_match="matched",
            matched_efficacies=("修护",),
        ),
        DisplayedCandidateRef(
            product_id=91,
            ordinal=2,
            skin_match="matched",
            matched_efficacies=("修护",),
        ),
    )
    snapshot = ConversationSnapshot(
        session_id="unified-flow",
        version=1,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(slot="recommendation"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                budget_maximum=Decimal("500"),
                skin="sensitive",
                efficacy="repair",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=3,
            ),
            candidates=candidates,
        ),
    )
    state.save(snapshot, expected_version=0)
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "recommendation",
            "topic_hint": "serum",
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "recommendation_mode": "explore",
            "recommendation_mode_basis": {
                "basis": "bounded_exploration",
                "source_text": raw_text,
            },
            "recommendation_count": None,
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [
                {
                    "raw_text": raw_text,
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "100",
                }
            ],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": None,
            "safety_language": "ordinary",
        },
        strict=True,
    )
    compiled = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=1,
            snapshot=snapshot,
        ),
    )
    text = RecordingTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )

    list(flow.stream(_turn(message, version=1)))

    route = text.preunderstood_calls[0][2]
    assert route.processor == "recommendation"
    assert route.continuity == "correct"


def test_unified_flow_consultation_uses_same_translation() -> None:
    meaning = _meaning("assessment", next_gap="location")
    translator = RecordingTranslator(meaning)
    text = RecordingTextProcessor()
    consultation = RecordingConsultationProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=consultation,
        conversation_state=InMemoryConversationState(),
    )

    turn = _turn("我不知道自己是什么肤质")
    events = _decoded_events(flow.stream(turn))

    assert events[1].data.intent == "clarify"
    assert len(translator.calls) == 1
    assert consultation.calls == []
    assert len(consultation.meaning_calls) == 1
    identity, understanding = consultation.meaning_calls[0]
    assert identity == turn.identity
    assert understanding.goal is UnderstandingGoal.ASSESSMENT
    assert consultation.route_decisions[0] is not None
    assert consultation.route_decisions[0].processor == "consultation"
    assert text.preunderstood_calls == []


def test_collecting_consultation_owns_unbound_ambiguous_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = InMemoryConversationState()
    candidate = DisplayedCandidateRef(
        product_id=35,
        ordinal=1,
        skin_match="unknown",
        matched_efficacies=(),
    )
    state.save(
        ConversationSnapshot(
            session_id="unified-flow",
            version=1,
            active_owner=Responsibility.CONSULTATION,
            active_focus=ActiveFocus(slot="consultation"),
            recommendation_slot=RecommendationSlotState(
                query_context=RecommendationQueryContext(
                    category="serum",
                    recommendation_mode_basis="broad_exploration",
                ),
                candidates=(candidate,),
            ),
            product_slot=ProductSlotState(
                products=(candidate,),
                focused_product_id=35,
            ),
            consultation_slot=ConsultationSlotState(
                state=ConsultationSubstate(
                    started_at_conversation_version=1,
                    observations=(
                        ConsultationObservation(
                            observation_id="obs_redness",
                            dimension="redness",
                            state="present",
                            location="unknown",
                            trigger="seasonal",
                            duration="current",
                            severity="unknown",
                            source_text="换季泛红",
                            source_turn_id="turn_consultation_0001",
                        ),
                    ),
                ),
            ),
        ),
        expected_version=0,
    )
    translator = RecordingTranslator(
        TurnMeaning(
            operation_hint="followup",
            topic_hint=None,
            continuity_hint="continue",
            subject_scope_hint="self",
            question_meaning="确认前面的咨询",
            safety_language="ordinary",
        )
    )
    text = RecordingTextProcessor()
    consultation = RecordingConsultationProcessor(dynamic_session=True)
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=consultation,
        conversation_state=state,
    )
    route_calls = []
    real_route = unified_flow_module.route_unified_turn

    def recording_route(**kwargs):
        decision = real_route(**kwargs)
        route_calls.append((kwargs, decision))
        return decision

    monkeypatch.setattr(
        unified_flow_module,
        "route_unified_turn",
        recording_route,
    )

    events = _decoded_events(
        flow.stream(_turn("确认", version=1))
    )

    assert events[-1].event == "end"
    assert len(route_calls) == 1
    assert len(consultation.meaning_calls) == 1
    assert consultation.route_decisions[0] is route_calls[0][1]
    assert text.preunderstood_calls == []


def test_collecting_consultation_does_not_preempt_general_knowledge() -> None:
    state = InMemoryConversationState()
    state.save(
        ConversationSnapshot(
            session_id="unified-flow",
            version=1,
            active_owner=Responsibility.CONSULTATION,
            active_focus=ActiveFocus(slot="consultation"),
            consultation_slot=ConsultationSlotState(
                state=ConsultationSubstate(
                    started_at_conversation_version=1,
                    observations=(
                        ConsultationObservation(
                            observation_id="obs_redness",
                            dimension="redness",
                            state="present",
                            location="unknown",
                            trigger="seasonal",
                            duration="current",
                            severity="unknown",
                            source_text="换季泛红",
                            source_turn_id="turn_consultation_0001",
                        ),
                    ),
                ),
            ),
        ),
        expected_version=0,
    )
    meaning = _meaning("knowledge", continuity="continue")
    translator = RecordingTranslator(meaning)
    text = RecordingTextProcessor()
    consultation = RecordingConsultationProcessor(dynamic_session=True)
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=consultation,
        conversation_state=state,
    )

    events = _decoded_events(
        flow.stream(_turn("视黄醇是什么", version=1))
    )

    assert events[-1].event == "end"
    assert consultation.meaning_calls == []
    assert len(text.preunderstood_calls) == 1
    assert text.preunderstood_calls[0][2].processor == "general_knowledge"


def test_route_owned_comparison_keeps_admitted_understanding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = UnifiedRouteDecision(
        processor="comparison",
        responsibility=Responsibility.COMPARISON,
        presentation_mode="comparison",
        continuity="continue",
        focus_source="candidate_batch",
        product_bindings=(
            ResolvedProductBinding(
                product_id=38,
                source_text="candidate_ordinal:1",
            ),
            ResolvedProductBinding(
                product_id=91,
                source_text="candidate_ordinal:2",
            ),
        ),
    )
    monkeypatch.setattr(
        unified_flow_module,
        "route_unified_turn",
        lambda **kwargs: decision,
    )
    text = RecordingTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(
            _meaning("recommendation", continuity="continue"),
        ),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=InMemoryConversationState(),
    )

    list(flow.stream(_turn("推荐防晒")))

    admitted = text.preunderstood_calls[0][1]
    assert admitted.goal is UnderstandingGoal.RECOMMENDATION
    assert text.preunderstood_calls[0][2] is decision


def test_promoted_followup_routes_by_compiled_recommendation_goal() -> None:
    state = InMemoryConversationState()
    candidate = DisplayedCandidateRef(
        product_id=51,
        ordinal=1,
        skin_match="not_applicable",
        matched_efficacies=(),
    )
    snapshot = ConversationSnapshot(
        session_id="unified-flow",
        version=1,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(
            slot="product",
            object_id=51,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="fragrance",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=3,
            ),
            candidates=(candidate,),
            focused_candidate_ordinal=1,
        ),
        product_slot=ProductSlotState(
            products=(candidate,),
            focused_product_id=51,
        ),
    )
    state.save(snapshot, expected_version=0)
    meaning = _meaning("followup", continuity="continue")
    text = RecordingTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )

    list(flow.stream(_turn("换一组", version=1)))

    route = text.preunderstood_calls[0][2]
    assert (
        text.preunderstood_calls[0][1].goal
        is UnderstandingGoal.RECOMMENDATION
    )
    assert route.processor == "recommendation"


def test_unified_flow_exact_only_consultation_uses_execution_input() -> None:
    translator = RecordingTranslator(_meaning("assessment"))
    text = RecordingTextProcessor()
    consultation = RecordingConsultationProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=consultation,
        conversation_state=InMemoryConversationState(),
    )

    turn = _turn("我不知道自己是什么肤质")
    list(flow.stream(turn))

    assert len(translator.calls) == 1
    assert consultation.calls == [turn.identity]
    assert consultation.meaning_calls == []


def test_unified_flow_atomless_dynamic_reply_uses_meaning_lane() -> None:
    meaning = _meaning("assessment", continuity="continue")
    translator = RecordingTranslator(meaning)
    consultation = RecordingConsultationProcessor(
        dynamic_session=True,
    )
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=RecordingTextProcessor(),
        consultation_processor=consultation,
        conversation_state=InMemoryConversationState(),
    )
    turn = _turn("对，就是这样")

    list(flow.stream(turn))

    assert consultation.calls == []
    assert len(consultation.meaning_calls) == 1
    identity, understanding = consultation.meaning_calls[0]
    assert identity == turn.identity
    assert understanding.goal is UnderstandingGoal.ASSESSMENT


def test_typed_image_source_compiles_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TranslatorMustNotRun:
        def translate(self, message, *, context):
            del message, context
            raise AssertionError(
                "typed image action must not invoke translation"
            )

    compiler_calls = []
    compiled_results = []
    real_compile = unified_flow_module.compile_turn_meaning

    def recording_compile(**kwargs):
        compiler_calls.append(kwargs)
        result = real_compile(**kwargs)
        compiled_results.append(result)
        return result

    monkeypatch.setattr(
        unified_flow_module,
        "compile_turn_meaning",
        recording_compile,
    )
    image = RecordingImageProcessor(image_count=1)
    flow = UnifiedGuideFlow(
        understanding=TranslatorMustNotRun(),
        text_processor=RecordingTextProcessor(),
        consultation_processor=RecordingConsultationProcessor(),
        image_processor=image,
        conversation_state=InMemoryConversationState(),
    )
    turn = _turn(
        "",
        image_action="identify",
        include_image_bundle=True,
    )

    events = _decoded_events(flow.stream_image(turn))

    assert events[-1].event == "end"
    assert len(compiler_calls) == 1
    assert compiler_calls[0]["meaning"].operation_hint == "image_identity"
    assert len(image.calls) == 1
    execution_input = image.calls[0]
    assert execution_input.understanding is compiled_results[0]
    assert (
        execution_input.understanding.goal
        is UnderstandingGoal.IMAGE_IDENTITY
    )


def test_typed_image_action_returns_turn_meaning_not_understanding() -> None:
    builder = getattr(
        typed_image_action,
        "turn_meaning_for_image_action",
        None,
    )

    assert callable(builder)
    meaning = builder(
        action="identify",
        image_count=1,
        question_summary="识别上传图片中的商品",
    )
    assert type(meaning) is TurnMeaning


def test_typed_compare_action_compiles_uploaded_image_batch_reference() -> None:
    message = "比较上传图片中的商品"
    meaning = typed_image_action.turn_meaning_for_image_action(
        action="compare",
        image_count=2,
        question_summary=message,
    )

    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            image_count=2,
            focused_image_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )

    assert len(meaning.reference_mentions) == 1
    assert meaning.reference_mentions[0].object_family_hint == "image"
    assert meaning.reference_mentions[0].plurality_hint == "batch"
    assert meaning.reference_mentions[0].batch_size_hint == 2
    assert [item.ordinal for item in understanding.references] == [1, 2]
    assert not any(
        issue.code == "ambiguous_reference"
        for issue in understanding.uncertainties
    )


def test_image_identity_observation_exists_before_router_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meaning = _meaning("image_identity")
    understanding = _understanding(
        UnderstandingGoal.IMAGE_IDENTITY
    )
    image = RecordingImageProcessor(image_count=1)
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning),
        text_processor=RecordingTextProcessor(),
        consultation_processor=RecordingConsultationProcessor(),
        image_processor=image,
        conversation_state=InMemoryConversationState(),
    )
    route_calls = []
    real_route = unified_flow_module.route_unified_turn

    def recording_route(**kwargs):
        route_calls.append(kwargs)
        return real_route(**kwargs)

    monkeypatch.setattr(
        unified_flow_module,
        "route_unified_turn",
        recording_route,
    )

    list(
        flow.stream_image(
            _turn(
                "这是什么商品",
                include_image_bundle=True,
            ),
        )
    )

    assert image.prepare_calls
    assert len(route_calls) == 1
    assert route_calls[0]["current_image_products"] == (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
        ),
    )
    route_decision, routing_evidence = image.route_decisions[0]
    assert route_decision is not None
    assert route_decision == real_route(**route_calls[0])
    assert routing_evidence is not None


def test_image_evidence_does_not_mutate_compiled_understanding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler_results = []
    route_calls = []
    real_compile = unified_flow_module.compile_turn_meaning
    real_route = unified_flow_module.route_unified_turn

    def recording_compile(**kwargs):
        result = real_compile(**kwargs)
        compiler_results.append(result)
        return result

    def recording_route(**kwargs):
        route_calls.append(kwargs)
        return real_route(**kwargs)

    monkeypatch.setattr(
        unified_flow_module,
        "compile_turn_meaning",
        recording_compile,
    )
    monkeypatch.setattr(
        unified_flow_module,
        "route_unified_turn",
        recording_route,
    )
    image = RecordingImageProcessor(
        image_count=1,
        anchor_topic=TopicCode.SUNSCREEN,
    )
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(
            _meaning("image_identity")
        ),
        text_processor=RecordingExecutionProcessor(),
        consultation_processor=RecordingExecutionProcessor(),
        image_processor=image,
        conversation_state=InMemoryConversationState(),
    )
    turn = _turn(
        "",
        image_action="identify",
        include_image_bundle=True,
    )

    list(flow.stream_image(turn))

    assert len(compiler_results) == 1
    compiled = compiler_results[0]
    assert compiled.topic is None
    assert route_calls[0]["understanding"] is compiled
    assert image.calls[0].understanding is compiled


def test_image_safety_turn_dispatches_only_safety_processor(
) -> None:
    meaning = _safety_meaning()
    translator = RecordingTranslator(meaning)
    recommendation = RecordingExecutionProcessor()
    safety = RecordingExecutionProcessor()
    image = RecordingImageProcessor(image_count=1)
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=recommendation,
        consultation_processor=safety,
        image_processor=image,
        conversation_state=InMemoryConversationState(),
    )
    turn = _turn(
        "现在已经破皮",
        include_image_bundle=True,
    )

    list(flow.stream_image(turn))

    assert image.prepare_calls == [turn]
    assert recommendation.calls == []
    assert image.calls == []
    assert len(safety.calls) == 1
    assert safety.calls[0]["route_decision"].processor == (
        "safety_escalation"
    )


def test_image_recommendation_dispatches_directly_to_selected_processor(
) -> None:
    meaning = _meaning("recommendation")
    translator = RecordingTranslator(meaning)
    recommendation = RecordingExecutionProcessor()
    safety = RecordingExecutionProcessor()
    image = RecordingImageProcessor(image_count=1)
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=recommendation,
        consultation_processor=safety,
        image_processor=image,
        conversation_state=InMemoryConversationState(),
    )
    turn = _turn(
        "推荐同类防晒",
        include_image_bundle=True,
    )

    list(flow.stream_image(turn))

    assert image.prepare_calls == [turn]
    assert image.calls == []
    assert safety.calls == []
    assert len(recommendation.calls) == 1
    decision = recommendation.calls[0]["route_decision"]
    assert decision.processor == "recommendation"
    assert recommendation.results[0].decision is decision


def test_production_understanding_adapter_requires_translate() -> None:
    class UnderstandOnly:
        def understand(self, message, *, context):
            del message, context
            return _understanding(UnderstandingGoal.CLARIFICATION)

    with pytest.raises(TypeError, match="must expose translate"):
        UnifiedUnderstandingAdapter(UnderstandOnly())


def test_reverse_understanding_to_meaning_adapter_is_absent() -> None:
    source = Path(
        "app/guide/application/unified_guide_flow.py"
    ).read_text(encoding="utf-8")

    assert "_meaning_from_compilation" not in source


def test_unified_flow_image_uses_the_same_single_translation() -> None:
    meaning = _meaning("knowledge")
    translator = RecordingTranslator(meaning)
    image = RecordingImageProcessor(image_count=2)
    text = RecordingTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        image_processor=image,
        conversation_state=InMemoryConversationState(),
    )
    turn = _turn("这是什么商品", include_image_bundle=True)

    events = _decoded_events(flow.stream_image(turn))

    assert [event.event for event in events] == [
        "start",
        "intent",
        "clarify",
        "end",
    ]
    assert len(translator.calls) == 1
    assert translator.calls[0][1].image_count == 2
    assert translator.calls[0][1].focused_image_ordinal is None
    assert image.prepare_calls == [turn]
    assert image.calls == []
    assert len(text.preunderstood_calls) == 1
    assert text.preunderstood_calls[0][0] == turn.identity
    assert (
        text.preunderstood_calls[0][1].goal
        is UnderstandingGoal.KNOWLEDGE
    )
    assert (
        text.preunderstood_calls[0][2].processor
        == "product_knowledge"
    )


def test_pending_safety_turn_dispatches_only_safety_processor(
) -> None:
    state = InMemoryConversationState()
    state.save(
        ConversationSnapshot(
            session_id="unified-flow",
            version=1,
            active_owner=Responsibility.CLARIFICATION,
            active_focus=ActiveFocus(slot="reply"),
            reply_slot=PendingReplySlot(
                value=PendingTurn(
                    gap=ClarificationCode.BUDGET,
                    attempts=1,
                    source_conversation_version=0,
                    source_message="预算一千左右的精华",
                    expected_response="confirm_or_correct",
                    resume_mode="recommendation",
                    resume_context=PendingRecommendationContext(
                        category="serum",
                        recommendation_mode_basis="broad_exploration",
                    ),
                    proposed_budget=PendingBudgetRange(
                        minimum=Decimal("900"),
                        maximum=Decimal("1100"),
                    ),
                ),
            ),
        ),
        expected_version=0,
    )
    meaning = _safety_meaning(pending_response="affirm")
    translator = RecordingTranslator(meaning)
    recommendation = RecordingExecutionProcessor()
    safety = RecordingExecutionProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=recommendation,
        consultation_processor=safety,
        conversation_state=state,
    )

    list(flow.stream(_turn("是的，现在已经破皮", version=1)))

    assert recommendation.calls == []
    assert len(safety.calls) == 1
    assert safety.calls[0]["route_decision"].processor == (
        "safety_escalation"
    )


def test_pending_turn_is_translated_once_then_uses_existing_pending_processor(
) -> None:
    state = InMemoryConversationState()
    pending = PendingTurn(
        gap=ClarificationCode.BUDGET,
        attempts=1,
        source_conversation_version=0,
        source_message="预算一千左右的精华",
        expected_response="confirm_or_correct",
        resume_mode="recommendation",
        resume_context=PendingRecommendationContext(
            category="serum",
            recommendation_mode_basis="broad_exploration",
        ),
        proposed_budget=PendingBudgetRange(
            minimum=Decimal("900"),
            maximum=Decimal("1100"),
        ),
    )
    state.save(
        ConversationSnapshot(
            session_id="unified-flow",
            version=1,
            active_owner=Responsibility.CLARIFICATION,
            active_focus=ActiveFocus(slot="reply"),
            recommendation_slot=RecommendationSlotState(
                query_context=RecommendationQueryContext(
                    category="serum",
                    recommendation_mode_basis="broad_exploration",
                    budget_minimum=None,
                    budget_maximum=Decimal("1100"),
                    skin=None,
                    efficacy=None,
                    exclusions=(),
                ),
                candidates=(
                    DisplayedCandidateRef(
                        product_id=38,
                        ordinal=1,
                        skin_match="unknown",
                        matched_efficacies=(),
                    ),
                ),
            ),
            reply_slot=PendingReplySlot(
                value=pending,
            ),
        ),
        expected_version=0,
    )
    translator = RecordingTranslator(
        _meaning(
            "clarification",
            continuity="continue",
            pending_response="affirm",
        ),
    )
    text = RecordingTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )

    events = _decoded_events(
        flow.stream(_turn("是的", version=1))
    )

    assert events[2].data.question == "请补充筛选条件。"
    assert len(translator.calls) == 1
    assert text.raw_calls == []
    assert len(text.pending_calls) == 1
    assert text.pending_calls[0][1].kind == "affirm"
    assert text.pending_route_decisions[0] is not None
    assert text.pending_route_decisions[0].processor == "recommendation"
    assert text.preunderstood_calls == []


def test_real_text_processor_uses_one_translation_and_typed_sse(
    real_reader,
    real_product_assets,
) -> None:
    state = InMemoryConversationState()
    text = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        presentation_copywriter=None,
    )
    translator = RecordingTranslator(
        TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_mode_basis={
                "basis": "bounded_exploration",
                "source_text": "500 元内",
            },
            topic_hint="serum",
            continuity_hint="new_task",
            subject_scope_hint="self",
            budget_candidates=(
                {
                    "raw_text": "500 元内",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "500",
                },
            ),
            preference_candidates=(
                {
                    "field_key": "skin",
                    "concept_id": "skin.sensitive",
                    "raw_text": "敏感肌",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.repair",
                    "raw_text": "修护",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ),
            question_meaning="推荐预算内适合敏感肌的修护精华",
            safety_language="ordinary",
        )
    )
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )
    turn = _turn("500 元内敏感肌修护精华")

    events = _decode_frames(flow.stream(turn))

    assert len(translator.calls) == 1
    assert events[-1] == ("end", {"conversation_version": 1})
    products = next(
        data["products"]
        for event, data in events
        if event == "products"
    )
    assert [item["product_id"] for item in products] == [38, 91]
    stored = state.load("unified-flow")
    assert stored is not None
    assert stored.version == 1
    assert stored.active_owner is Responsibility.RECOMMENDATION
    assert stored.active_focus.slot == "recommendation"
    assert stored.recommendation_slot is not None


def test_explore_without_requested_count_uses_code_owned_default(
    real_reader,
    real_product_assets,
) -> None:
    message = "给我推荐 900 到 1100 元的精华"
    meaning = TurnMeaning.model_validate(
        {
            **_meaning("recommendation").model_dump(mode="python"),
            "recommendation_mode": "explore",
            "recommendation_count": None,
            "recommendation_mode_basis": {
                "basis": "bounded_exploration",
                "source_text": "900 到 1100 元",
            },
            "topic_hint": "serum",
            "question_meaning": "推荐预算范围内的精华",
        },
        strict=True,
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=0,
            snapshot=None,
        ),
    )
    state = InMemoryConversationState()
    text = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        presentation_copywriter=None,
    )
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )
    turn = _turn(message)

    events = _decode_frames(flow.stream(turn))

    assert not any(event == "error" for event, _ in events)
    assert events[-1] == ("end", {"conversation_version": 1})
    presentation = next(
        data
        for event, data in events
        if event == "presentation_contract"
    )
    assert presentation["recommendation_mode"] == "explore"
    assert len(presentation["visible_product_ids"]) == 3


def test_return_to_product_focus_preserves_recommendation_context(
    real_reader,
    real_product_assets,
) -> None:
    state = InMemoryConversationState()
    candidates = (
        DisplayedCandidateRef(
            product_id=38,
            ordinal=1,
            skin_match="matched",
            matched_efficacies=("修护",),
        ),
        DisplayedCandidateRef(
            product_id=91,
            ordinal=2,
            skin_match="matched",
            matched_efficacies=("修护",),
        ),
    )
    snapshot = ConversationSnapshot(
        session_id="unified-flow",
        version=1,
        active_owner=Responsibility.GENERAL_KNOWLEDGE,
        active_focus=ActiveFocus(slot="knowledge"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
                budget_maximum=Decimal("500"),
                skin="sensitive",
                efficacy="repair",
            ),
            candidates=candidates,
        ),
        product_slot=ProductSlotState(
            products=candidates,
            focused_product_id=91,
        ),
        knowledge_slot=KnowledgeSlotState(
            question="视黄醇是什么",
        ),
    )
    state.save(snapshot, expected_version=0)
    message = "恢复之前商品焦点，看看是否适合白天"
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "suitability",
            "topic_hint": "serum",
            "continuity_hint": "return_to_focus",
            "subject_scope_hint": "unknown",
            "reference_mentions": [
                {
                    "raw_text": "之前商品",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "是否适合白天使用",
            "safety_language": "ordinary",
        },
        strict=True,
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=1,
            snapshot=snapshot,
        ),
    )
    text = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        presentation_copywriter=None,
    )
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )
    turn = _turn(message, version=1)

    events = _decode_frames(flow.stream(turn))

    assert events[-1] == ("end", {"conversation_version": 2})
    stored = state.load("unified-flow")
    assert stored is not None
    assert stored.recommendation_slot == snapshot.recommendation_slot
    assert (
        stored.active_owner
        is Responsibility.SINGLE_PRODUCT_SUITABILITY
    )
    assert stored.active_focus == ActiveFocus(
        slot="product",
        object_id=91,
    )
    assert stored.product_slot is not None
    assert stored.product_slot.focused_product_id == 91


def test_multi_product_knowledge_routes_comparison_without_internal_error(
    tmp_path: Path,
) -> None:
    message = "B5精华、CE精华分别适合哪些使用场景"
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "knowledge",
            "topic_hint": "serum",
            "continuity_hint": "new_task",
            "subject_scope_hint": "unknown",
            "reference_mentions": [],
            "product_mentions": [
                {"raw_text": "B5精华"},
                {"raw_text": "CE精华"},
            ],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "两款精华分别适合哪些使用场景",
            "safety_language": "unknown",
        },
        strict=True,
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=0,
            snapshot=None,
        ),
    )
    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "router-clarification",
    )
    vertical.unified._understanding = RecordingTranslator(
        meaning,
    )
    turn = _turn(
        message,
        profile_owner=vertical.profile_owner("unified-flow"),
    )

    events = _decode_frames(vertical.unified.stream(turn))

    assert events[-1] == ("end", {"conversation_version": 1})
    assert not any(event == "error" for event, _ in events)
    intent = next(
        data["intent"]
        for event, data in events
        if event == "intent"
    )
    products = next(
        data["products"]
        for event, data in events
        if event == "products"
    )
    assert intent == "comparison"
    assert [item["product_id"] for item in products] == [38, 34]


def test_explicit_comparison_dimension_does_not_filter_named_products(
    tmp_path: Path,
) -> None:
    message = "把B5精华和CE精华按修护重点、肤感、使用时段做对照"
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "comparison",
            "topic_hint": "serum",
            "continuity_hint": "new_task",
            "subject_scope_hint": "unknown",
            "reference_mentions": [
                {
                    "raw_text": "B5精华",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
                {
                    "raw_text": "CE精华",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
            ],
            "product_mentions": [
                {"raw_text": "B5精华"},
                {"raw_text": "CE精华"},
            ],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "按修护重点、肤感和使用时段比较两款精华",
            "safety_language": "unknown",
        },
        strict=True,
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=0,
            snapshot=None,
        ),
    )
    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "explicit-comparison",
    )
    vertical.unified._understanding = RecordingTranslator(
        meaning,
    )
    turn = _turn(
        message,
        profile_owner=vertical.profile_owner("unified-flow"),
    )

    events = _decode_frames(vertical.unified.stream(turn))

    assert events[-1] == ("end", {"conversation_version": 1})
    products = next(
        data["products"]
        for event, data in events
        if event == "products"
    )
    assert [item["product_id"] for item in products] == [38, 34]
