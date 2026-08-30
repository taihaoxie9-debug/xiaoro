from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from app.guide.adapters.state import (
    InMemoryConversationState,
)
from app.guide.adapters.state.sqlite_profile_state import (
    SqliteProfileState,
)
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.application.consultation_confirmation import (
    confirm_provisional_conclusion,
    record_medical_escalation,
    record_provisional_conclusion,
)
from app.guide.application.execution_contracts import (
    ExecutionResult,
    OpaqueRetrievalQuery,
    PreRoutingEvidence,
    PresentationTerminal,
    ProcessorExecutionInput,
    ProfileLanePatch,
)
from app.guide.application.dynamic_consultation import (
    prepare_dynamic_consultation_evidence,
)
from app.guide.application.product_resolution import (
    PreRoutingProductResolution,
)
from app.guide.application.session_profile_resolution import (
    resolve_session_profile_context,
)
from app.guide.application.unified_guide_flow import UnifiedGuideFlow
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.contracts import (
    ConsultationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import ActiveFocus
from app.guide.feedback.profile_policy import ResolvedProfileContext
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
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
)
from app.guide.presentation.sse_events import (
    MedicalEscalationEvent,
    ProfileConfirmationEvent,
)
from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationInput,
    ConsultationEscalationTrigger,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from tests.guide.semantic_test_port import (
    consultation_assessment_fixture,
    consultation_from_answers,
)


_OWNER = ProfileOwnerRef(
    scope="anonymous_browser",
    subject_id="profile_consultation_flow_0123456789",
)


def _flow(tmp_path: Path):
    from app.guide.application.consultation_chat_flow import (
        ConsultationChatFlow,
    )

    conversation_state = InMemoryConversationState()
    state_root = tmp_path / "state"
    profile_state = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    return (
        ConsultationChatFlow(),
        conversation_state,
        profile_state,
    )


def _turn(
    message: str,
    *,
    version: int,
    session_id: str = "consultation-chat-flow",
) -> UserTurn:
    return UserTurn(
        identity=TurnIdentity(
            session_id=session_id,
            request_id=f"request_{session_id}_{version}",
            turn_id=f"turn_{session_id}_{version}",
        ),
        session_id=session_id,
        message=message,
        profile_owner=_OWNER,
        conversation_version=version,
    )


def _processor_input(
    turn: UserTurn,
    *,
    meaning: TurnMeaning,
    understanding,
    snapshot: ConversationSnapshot | None,
    route_decision: UnifiedRouteDecision,
) -> ProcessorExecutionInput:
    expected_skin_target = None
    if snapshot is not None and snapshot.consultation_slot is not None:
        assessment = (
            snapshot.consultation_slot.state.confirmable_assessment
        )
        if assessment is not None:
            expected_skin_target = assessment.conclusion.skin_target
    if route_decision.task_plan is None:
        route_decision = route_decision.model_copy(
            update={
                "task_plan": plan_task(
                    understanding,
                    responsibility=route_decision.responsibility,
                    message=turn.question_summary,
                )
            },
            deep=True,
        )
    return ProcessorExecutionInput(
        turn_identity=turn.identity,
        understanding=understanding,
        decision=route_decision,
        current_snapshot=snapshot,
        routing_evidence=PreRoutingEvidence(
            query=OpaqueRetrievalQuery(value=turn.question_summary),
            conversation_version=turn.conversation_version,
            profile_owner=turn.profile_owner,
            profile_context=(
                resolve_session_profile_context(snapshot)
                if snapshot is not None
                else ResolvedProfileContext(values=())
            ),
            product_resolution=ProductMentionResolution(bindings=()),
            consultation=prepare_dynamic_consultation_evidence(
                message=turn.question_summary,
                meaning=meaning,
                source_turn_id=turn.identity.turn_id,
                expected_skin_target=expected_skin_target,
            ),
        ),
    )


def _execute(
    flow,
    turn: UserTurn,
    *,
    meaning: TurnMeaning,
    understanding,
    snapshot: ConversationSnapshot | None,
    route_decision: UnifiedRouteDecision,
) -> ExecutionResult:
    return flow.execute(
        _processor_input(
            turn,
            meaning=meaning,
            understanding=understanding,
            snapshot=snapshot,
            route_decision=route_decision,
        )
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




def _dynamic_meaning() -> TurnMeaning:
    return TurnMeaning.model_validate(
        {
            "operation_hint": "assessment",
            "topic_hint": "skincare",
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [
                {
                    "observation_id": "obs_oil",
                    "code": "oiliness",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "一会油",
                    "location": None,
                    "trigger": None,
                    "duration": None,
                    "severity": None,
                },
                {
                    "observation_id": "obs_dry",
                    "code": "dryness",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "一会干",
                    "location": None,
                    "trigger": None,
                    "duration": None,
                    "severity": None,
                },
                {
                    "observation_id": "obs_red",
                    "code": "redness",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "换季还红",
                    "location": None,
                    "trigger": "seasonal",
                    "duration": None,
                    "severity": None,
                },
            ],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": {
                "base_skin_direction": "combination",
                "stable_tendencies": ["seasonal_redness"],
                "current_conditions": ["redness"],
                "supporting_observation_ids": [
                    "obs_oil",
                    "obs_dry",
                    "obs_red",
                ],
            },
            "next_observation_gap": "location",
            "question_meaning": "动态轻问诊",
            "safety_language": "ordinary",
        },
        strict=True,
    )


def _provisional_consultation() -> ConsultationSubstate:
    consultation = consultation_from_answers(("yes", "unknown"))
    assessment = consultation_assessment_fixture(
        consultation,
        conversation_version=1,
        conclusion_source_turn_id="turn_assessment_000001",
    )
    return record_provisional_conclusion(
        consultation,
        current_conversation_version=1,
        assessment=assessment.confirmable_assessment,
    ).next_consultation


def _confirmation_meaning(
    *,
    pending_response_hint: str,
) -> TurnMeaning:
    return TurnMeaning(
        operation_hint="assessment",
        topic_hint="skincare",
        continuity_hint="continue",
        subject_scope_hint="self",
        pending_response_hint=pending_response_hint,
        preference_candidates=(
            {
                "field_key": "skin",
                "concept_id": "skin.dry",
                "raw_text": "干皮",
                "polarity": "prefer",
                "strength": "ordinary",
            },
        )
        if pending_response_hint == "affirm"
        else (),
        question_meaning="确认或拒绝问诊结论",
        safety_language="ordinary",
    )


def test_dynamic_execute_returns_result_without_state_write(
    tmp_path: Path,
) -> None:
    flow, conversation_state, profile_state = _flow(tmp_path)
    turn = _turn(
        "一会油一会干，换季还红",
        version=0,
    )
    meaning = _dynamic_meaning()
    understanding = compile_turn_meaning(
        message=turn.message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            focused_image_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )
    decision = UnifiedRouteDecision(
        processor="consultation",
        responsibility=Responsibility.CONSULTATION,
        presentation_mode="consultation",
        continuity="continue",
        focus_source="none",
        task_plan=plan_task(
            understanding,
            responsibility=Responsibility.CONSULTATION,
            message=turn.question_summary,
        ),
    )

    result = _execute(
        flow,
        turn,
        meaning=meaning,
        understanding=understanding,
        snapshot=None,
        route_decision=decision,
    )

    assert type(result) is ExecutionResult
    assert result.decision is decision
    assert isinstance(result.terminal, PresentationTerminal)
    assert result.terminal.data.mode == "consultation"
    assert result.terminal.data.card_display.mode == "none"
    assert result.state_delta.consultation.action == "replace"
    assert [
        item.dimension
        for item in result.state_delta.consultation.value.observations
    ] == ["oiliness", "dryness", "redness"]
    assert conversation_state.load(turn.session_id) is None
    assert profile_state.load(_OWNER) is None


def test_consultation_processor_has_one_non_persisting_entrypoint() -> None:
    from app.guide.application.consultation_chat_flow import (
        ConsultationChatFlow,
    )

    source = inspect.getsource(ConsultationChatFlow)

    assert not hasattr(ConsultationChatFlow, "stream")
    assert not hasattr(ConsultationChatFlow, "stream_meaning")
    assert not hasattr(ConsultationChatFlow, "claims")
    assert not hasattr(ConsultationChatFlow, "has_session")
    assert not hasattr(ConsultationChatFlow, "has_dynamic_session")
    assert not hasattr(ConsultationChatFlow, "has_authority")
    assert "_conversation_state" not in source
    assert "_session_locks" not in source
    assert "_coordinator.handle_" not in source


def test_execute_enters_consultation_from_existing_recommendation_slot(
    tmp_path: Path,
) -> None:
    flow, conversation_state, _ = _flow(tmp_path)
    snapshot = ConversationSnapshot(
        session_id="consultation-chat-flow",
        version=1,
        profile_owner=_OWNER,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(
            slot="recommendation",
            ordinal=1,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=3,
            ),
            candidates=(
                DisplayedCandidateRef(
                    product_id=38,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
            focused_candidate_ordinal=1,
        ),
    )
    message = "我不知道自己是什么肤质"
    meaning = TurnMeaning(
        operation_hint="assessment",
        topic_hint="skincare",
        continuity_hint="new_task",
        subject_scope_hint="self",
        next_observation_gap="location",
        question_meaning="开始肤质问诊",
        safety_language="ordinary",
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=1,
            active_topic=None,
            visible_candidate_count=1,
            image_count=0,
            focused_image_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )
    decision = UnifiedRouteDecision(
        processor="consultation",
        responsibility=Responsibility.CONSULTATION,
        presentation_mode="consultation",
        continuity="replace_task",
        focus_source="consultation",
        task_plan=plan_task(
            understanding,
            responsibility=Responsibility.CONSULTATION,
            message=message,
        ),
    )

    result = _execute(
        flow,
        _turn(message, version=1),
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        route_decision=decision,
    )

    intent = next(
        event
        for event in result.audit_events
        if event.event == "intent"
    )
    assert intent.data.mode == "consultation_entry"
    observation = next(
        event
        for event in result.audit_events
        if event.event == "consultation_observation"
    )
    assert observation.data.next_question is not None
    assert result.terminal.data.mode == "consultation"
    assert result.terminal.data.card_display.mode == "none"
    assert result.state_delta.consultation.action == "replace"
    assert result.state_delta.recommendation.action == "preserve"
    assert conversation_state.load(snapshot.session_id) is None


def test_execute_confirmation_returns_profile_patch_without_state_write(
    tmp_path: Path,
) -> None:
    flow, conversation_state, profile_state = _flow(tmp_path)
    consultation = consultation_from_answers(("yes", "unknown"))
    assessment = consultation_assessment_fixture(
        consultation,
        conversation_version=1,
        conclusion_source_turn_id="turn_assessment_000001",
    )
    provisional = record_provisional_conclusion(
        consultation,
        current_conversation_version=1,
        assessment=assessment.confirmable_assessment,
    ).next_consultation
    snapshot = ConversationSnapshot(
        session_id="consultation-chat-flow",
        version=2,
        profile_owner=_OWNER,
        active_owner=Responsibility.CONSULTATION,
        active_focus=ActiveFocus(slot="consultation"),
        consultation_slot=ConsultationSlotState(
            state=provisional,
        ),
    )
    message = "我确认是干皮"
    meaning = TurnMeaning(
        operation_hint="assessment",
        topic_hint="skincare",
        continuity_hint="continue",
        subject_scope_hint="self",
        pending_response_hint="affirm",
        preference_candidates=(
            {
                "field_key": "skin",
                "concept_id": "skin.dry",
                "raw_text": "干皮",
                "polarity": "prefer",
                "strength": "ordinary",
            },
        ),
        question_meaning="确认问诊结论为干性肤质",
        safety_language="ordinary",
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=2,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            focused_image_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )
    decision = UnifiedRouteDecision(
        processor="consultation",
        responsibility=Responsibility.CONSULTATION,
        presentation_mode="consultation",
        continuity="continue",
        focus_source="consultation",
        task_plan=plan_task(
            understanding,
            responsibility=Responsibility.CONSULTATION,
            message=message,
        ),
    )

    result = _execute(
        flow,
        _turn(message, version=2),
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        route_decision=decision,
    )

    assert result.decision is decision
    assert result.state_delta.consultation.action == "replace"
    profile_mutation = result.state_delta.profile
    assert profile_mutation.action == "replace"
    assert isinstance(profile_mutation.value, ProfileLanePatch)
    assert any(
        update.value == "dry"
        for update in profile_mutation.value.updates
    )
    assert any(
        isinstance(event, ProfileConfirmationEvent)
        for event in result.audit_events
    )
    assert conversation_state.load(snapshot.session_id) is None
    assert profile_state.load(_OWNER) is None


def test_unified_flow_reduces_confirmation_profile_patch_once(
    tmp_path: Path,
) -> None:
    consultation_flow, conversation_state, profile_state = _flow(tmp_path)
    observations = _provisional_consultation().observations
    base = ConversationSnapshot(
        session_id="consultation-chat-flow",
        version=1,
        profile_owner=_OWNER,
        active_owner=Responsibility.CONSULTATION,
        active_focus=ActiveFocus(slot="consultation"),
        consultation_slot=ConsultationSlotState(
            state=ConsultationSubstate(),
        ),
    )
    first_observation = base.model_copy(
        update={
            "version": 2,
            "consultation_slot": ConsultationSlotState(
                state=ConsultationSubstate(
                    observations=observations[:1],
                ),
            ),
        },
        deep=True,
    )
    complete_observations = first_observation.model_copy(
        update={
            "version": 3,
            "consultation_slot": ConsultationSlotState(
                state=ConsultationSubstate(
                    observations=observations,
                ),
            ),
        },
        deep=True,
    )
    assert complete_observations.consultation_slot is not None
    complete_consultation = complete_observations.consultation_slot.state
    assessment = consultation_assessment_fixture(
        complete_consultation,
        conversation_version=3,
        conclusion_source_turn_id="turn_assessment_000003",
    )
    provisional = record_provisional_conclusion(
        complete_consultation,
        current_conversation_version=3,
        assessment=assessment.confirmable_assessment,
    ).next_consultation
    snapshot = ConversationSnapshot(
        session_id="consultation-chat-flow",
        version=4,
        profile_owner=_OWNER,
        active_owner=Responsibility.CONSULTATION,
        active_focus=ActiveFocus(slot="consultation"),
        consultation_slot=ConsultationSlotState(
            state=provisional,
        ),
    )
    conversation_state.save(base, expected_version=0)
    conversation_state.save(first_observation, expected_version=1)
    conversation_state.save(complete_observations, expected_version=2)
    conversation_state.save(snapshot, expected_version=3)
    message = "我确认是干皮"
    meaning = _confirmation_meaning(
        pending_response_hint="affirm",
    )

    class ConfirmationTranslator:
        def translate(self, candidate, *, context):
            assert candidate == message
            assert context.conversation_version == 4
            return meaning

    class UnusedTextProcessor:
        @staticmethod
        def execute(*args, **kwargs):
            raise AssertionError(
                "confirmation must use consultation processor"
            )

    class EmptyProductResolutionCollector:
        @staticmethod
        def collect(**kwargs):
            del kwargs
            return PreRoutingProductResolution(
                resolution=ProductMentionResolution(bindings=()),
            )

    unified = UnifiedGuideFlow(
        understanding=ConfirmationTranslator(),
        product_resolution_collector=(
            EmptyProductResolutionCollector()
        ),
        text_processor=UnusedTextProcessor(),
        consultation_processor=consultation_flow,
        conversation_state=conversation_state,
    )

    events = _decode_frames(
        unified.stream(_turn(message, version=4))
    )

    assert events[-1][0] == "end"
    assert events[-1][1]["conversation_version"] == 5
    stored = conversation_state.load(snapshot.session_id)
    assert stored is not None
    assert stored.version == 5
    assert stored.consultation_slot is not None
    assert (
        stored.consultation_slot.state.confirmable_assessment
        .conclusion.confirmed_by_user
    )
    assert stored.session_profile is not None
    assert stored.session_profile.base_skin is not None
    assert stored.session_profile.base_skin.value == "dry"
    assert profile_state.load(_OWNER) is None


@pytest.mark.parametrize(
    ("message", "pending_response_hint", "expected_intent"),
    (
        (
            "我不确认",
            "reject",
            "consultation_rejection",
        ),
        (
            "我还不确定",
            "unknown",
            "consultation_clarification",
        ),
    ),
)
def test_execute_unresolved_confirmation_preserves_business_lanes(
    tmp_path: Path,
    message: str,
    pending_response_hint: str,
    expected_intent: str,
) -> None:
    flow, conversation_state, profile_state = _flow(tmp_path)
    snapshot = ConversationSnapshot(
        session_id="consultation-chat-flow",
        version=2,
        profile_owner=_OWNER,
        active_owner=Responsibility.CONSULTATION,
        active_focus=ActiveFocus(slot="consultation"),
        consultation_slot=ConsultationSlotState(
            state=_provisional_consultation(),
        ),
    )
    meaning = _confirmation_meaning(
        pending_response_hint=pending_response_hint,
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=2,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            focused_image_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )
    decision = UnifiedRouteDecision(
        processor="consultation",
        responsibility=Responsibility.CONSULTATION,
        presentation_mode="consultation",
        continuity="continue",
        focus_source="consultation",
        task_plan=plan_task(
            understanding,
            responsibility=Responsibility.CONSULTATION,
            message=message,
        ),
    )

    result = _execute(
        flow,
        _turn(message, version=2),
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        route_decision=decision,
    )

    assert result.state_delta.consultation.action == "preserve"
    assert result.state_delta.profile.action == "preserve"
    intent = next(
        event
        for event in result.audit_events
        if event.event == "intent"
    )
    assert intent.data.mode == expected_intent
    assert conversation_state.load(snapshot.session_id) is None
    assert profile_state.load(_OWNER) is None


def test_execute_confirmed_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    flow, conversation_state, profile_state = _flow(tmp_path)
    provisional = _provisional_consultation()
    confirmed = confirm_provisional_conclusion(
        provisional,
        current_conversation_version=2,
        message="我确认是干皮",
        source_turn_id="turn_confirmation_0001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id=(
            provisional.confirmable_assessment.conclusion_source_turn_id
        ),
    ).next_consultation
    profile = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            BaseSkinUpdate(
                value="dry",
                confirmation="confirmed",
            ),
        ),
        subject_scope="self",
        source_turn_id="turn_confirmation_0001",
        conversation_version=3,
    ).profile
    snapshot = ConversationSnapshot(
        session_id="consultation-chat-flow",
        version=3,
        profile_owner=_OWNER,
        session_profile=profile,
        active_owner=Responsibility.CONSULTATION,
        active_focus=ActiveFocus(slot="consultation"),
        consultation_slot=ConsultationSlotState(
            state=confirmed,
        ),
    )
    message = "我确认是干皮"
    meaning = _confirmation_meaning(
        pending_response_hint="affirm",
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=3,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            focused_image_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )
    decision = UnifiedRouteDecision(
        processor="consultation",
        responsibility=Responsibility.CONSULTATION,
        presentation_mode="consultation",
        continuity="continue",
        focus_source="consultation",
        task_plan=plan_task(
            understanding,
            responsibility=Responsibility.CONSULTATION,
            message=message,
        ),
    )

    result = _execute(
        flow,
        _turn(message, version=3),
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        route_decision=decision,
    )

    assert result.state_delta.consultation.action == "preserve"
    assert result.state_delta.profile.action == "preserve"
    confirmation = next(
        event
        for event in result.audit_events
        if isinstance(event, ProfileConfirmationEvent)
    )
    assert confirmation.data.session_profile == profile
    assert conversation_state.load(snapshot.session_id) is None
    assert profile_state.load(_OWNER) is None


def test_execute_medical_escalation_replaces_provisional_assessment(
    tmp_path: Path,
) -> None:
    flow, conversation_state, profile_state = _flow(tmp_path)
    consultation = consultation_from_answers(("yes", "unknown"))
    assessment = consultation_assessment_fixture(
        consultation,
        conversation_version=1,
        conclusion_source_turn_id="turn_assessment_000001",
    )
    provisional = record_provisional_conclusion(
        consultation,
        current_conversation_version=1,
        assessment=assessment.confirmable_assessment,
    ).next_consultation
    snapshot = ConversationSnapshot(
        session_id="consultation-chat-flow",
        version=2,
        profile_owner=_OWNER,
        active_owner=Responsibility.CONSULTATION,
        active_focus=ActiveFocus(slot="consultation"),
        consultation_slot=ConsultationSlotState(
            state=provisional,
        ),
    )
    message = "现在还有明显疼痛"
    meaning = TurnMeaning(
        operation_hint="assessment",
        topic_hint="skincare",
        continuity_hint="continue",
        subject_scope_hint="self",
        observation_candidates=(
            {
                "observation_id": "obs_pain",
                "code": "pain",
                "present": True,
                "qualifier": None,
                "raw_text": "明显疼痛",
                "location": None,
                "trigger": None,
                "duration": "current",
                "severity": "severe",
            },
        ),
        question_meaning="问诊中出现明显疼痛",
        safety_language="safety",
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=2,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            focused_image_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )
    decision = UnifiedRouteDecision(
        processor="safety_escalation",
        responsibility=Responsibility.SAFETY_ESCALATION,
        presentation_mode="consultation",
        continuity="continue",
        focus_source="consultation",
        task_plan=plan_task(
            understanding,
            responsibility=Responsibility.SAFETY_ESCALATION,
            message=message,
        ),
    )

    result = _execute(
        flow,
        _turn(message, version=2),
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        route_decision=decision,
    )

    next_consultation = result.state_delta.consultation.value
    assert next_consultation is not None
    assert (
        next_consultation.confirmable_assessment.assessment_kind
        == "medical_escalation"
    )
    assert next_consultation.observations[-1].dimension == "pain"
    assert next_consultation.medical_escalation is not None
    assert (
        next_consultation.medical_escalation.assessment
        == next_consultation.confirmable_assessment
    )
    assert any(
        isinstance(event, MedicalEscalationEvent)
        for event in result.audit_events
    )
    assert conversation_state.load(snapshot.session_id) is None
    assert profile_state.load(_OWNER) is None


def test_execute_post_confirmation_escalation_is_read_only(
    tmp_path: Path,
) -> None:
    flow, conversation_state, profile_state = _flow(tmp_path)
    provisional = _provisional_consultation()
    confirmed = confirm_provisional_conclusion(
        provisional,
        current_conversation_version=2,
        message="我确认是干皮",
        source_turn_id="turn_confirmation_0001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id=(
            provisional.confirmable_assessment.conclusion_source_turn_id
        ),
    ).next_consultation
    profile = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            BaseSkinUpdate(
                value="dry",
                confirmation="confirmed",
            ),
        ),
        subject_scope="self",
        source_turn_id="turn_confirmation_0001",
        conversation_version=3,
    ).profile
    snapshot = ConversationSnapshot(
        session_id="consultation-chat-flow",
        version=3,
        profile_owner=_OWNER,
        session_profile=profile,
        active_owner=Responsibility.CONSULTATION,
        active_focus=ActiveFocus(slot="consultation"),
        consultation_slot=ConsultationSlotState(
            state=confirmed,
        ),
    )
    message = "现在还有明显疼痛"
    meaning = TurnMeaning(
        operation_hint="assessment",
        topic_hint="skincare",
        continuity_hint="continue",
        subject_scope_hint="self",
        observation_candidates=(
            {
                "observation_id": "obs_pain",
                "code": "pain",
                "present": True,
                "qualifier": None,
                "raw_text": "明显疼痛",
                "location": None,
                "trigger": None,
                "duration": "current",
                "severity": "severe",
            },
        ),
        question_meaning="确认后出现明显疼痛",
        safety_language="safety",
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=3,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            focused_image_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )
    decision = UnifiedRouteDecision(
        processor="safety_escalation",
        responsibility=Responsibility.SAFETY_ESCALATION,
        presentation_mode="consultation",
        continuity="continue",
        focus_source="consultation",
        task_plan=plan_task(
            understanding,
            responsibility=Responsibility.SAFETY_ESCALATION,
            message=message,
        ),
    )

    result = _execute(
        flow,
        _turn(message, version=3),
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        route_decision=decision,
    )

    assert result.state_delta.consultation.action == "preserve"
    assert result.state_delta.profile.action == "preserve"
    escalation = next(
        event
        for event in result.audit_events
        if isinstance(event, MedicalEscalationEvent)
    )
    assert escalation.data.stop_skincare_advice is True
    assert conversation_state.load(snapshot.session_id) is None
    assert profile_state.load(_OWNER) is None


def test_execute_recorded_medical_escalation_is_terminal_and_read_only(
    tmp_path: Path,
) -> None:
    flow, conversation_state, profile_state = _flow(tmp_path)
    provisional = _provisional_consultation()
    medical_assessment = consultation_assessment_fixture(
        provisional,
        conversation_version=2,
        conclusion_source_turn_id="turn_escalation_0001",
        escalation=ConsultationEscalationInput(
            triggers=[
                ConsultationEscalationTrigger(
                    code="pain",
                    source_turn_id="turn_escalation_0001",
                ),
            ],
        ),
    ).confirmable_assessment
    recorded = record_medical_escalation(
        provisional,
        current_conversation_version=2,
        assessment=medical_assessment,
    ).next_consultation
    snapshot = ConversationSnapshot(
        session_id="consultation-chat-flow",
        version=3,
        profile_owner=_OWNER,
        active_owner=Responsibility.SAFETY_ESCALATION,
        active_focus=ActiveFocus(slot="consultation"),
        consultation_slot=ConsultationSlotState(
            state=recorded,
        ),
    )
    message = "那我接下来怎么办"
    meaning = TurnMeaning(
        operation_hint="assessment",
        topic_hint="skincare",
        continuity_hint="continue",
        subject_scope_hint="self",
        question_meaning="医疗升级后的后续处理",
        safety_language="ordinary",
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=3,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            focused_image_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )
    decision = UnifiedRouteDecision(
        processor="safety_escalation",
        responsibility=Responsibility.SAFETY_ESCALATION,
        presentation_mode="consultation",
        continuity="continue",
        focus_source="consultation",
        task_plan=plan_task(
            understanding,
            responsibility=Responsibility.SAFETY_ESCALATION,
            message=message,
        ),
    )

    result = _execute(
        flow,
        _turn(message, version=3),
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        route_decision=decision,
    )

    assert result.state_delta.consultation.action == "preserve"
    escalation = next(
        event
        for event in result.audit_events
        if isinstance(event, MedicalEscalationEvent)
    )
    assert escalation.data.conclusion == medical_assessment.conclusion
    assert conversation_state.load(snapshot.session_id) is None
    assert profile_state.load(_OWNER) is None
