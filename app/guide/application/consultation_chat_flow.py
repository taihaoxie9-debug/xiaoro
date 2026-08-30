from __future__ import annotations

from app.guide.application.consultation_contracts import (
    ConsultationApplicationResult,
)
from app.guide.application.consultation_confirmation import (
    confirm_prevalidated_conclusion,
)
from app.guide.application.dynamic_consultation import (
    advance_dynamic_consultation,
)
from app.guide.application.execution_contracts import (
    ClarificationLaneState,
    ConversationStateDelta,
    ExecutionResult,
    LaneMutation,
    PresentationTerminal,
    ProcessorExecutionInput,
    ProfileLanePatch,
    notify_processor_entry,
)
from app.guide.feedback.consultation_state import (
    ConfirmableConsultationAssessment,
    ConsultationSubstate,
    RecordedMedicalEscalation,
)
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.ports import (
    ConversationStateConflict,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.session_profile import (
    BaseSkinUpdate,
    CurrentConditionUpdate,
    SessionProfile,
    SessionProfileUpdate,
    StableTendencyUpdate,
    reduce_session_profile,
)
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.presentation.presentation_compiler import (
    PresentationCompileInputs,
    PresentationCompiler,
)
from app.guide.presentation.presentation_packet import (
    build_presentation_packet,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.sse_events import (
    AnswerContractData,
    AnswerContractEvent,
    CardDisplayContractEvent,
    ConsultationObservationData,
    ConsultationObservationEvent,
    ConsultationProvisionalData,
    ConsultationProvisionalEvent,
    IntentData,
    IntentEvent,
    MedicalEscalationData,
    MedicalEscalationEvent,
    ProfileConfirmationData,
    ProfileConfirmationEvent,
    SseEvent,
    StageData,
    StageEvent,
)

class ConsultationChatFlow:
    def __init__(
        self,
        *,
        presentation_compiler: PresentationCompiler | None = None,
        execution_observer=None,
    ) -> None:
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
        snapshot = execution_input.current_snapshot
        route_decision = execution_input.decision
        evidence = execution_input.routing_evidence
        consultation_evidence = evidence.consultation
        conversation_version = evidence.conversation_version
        session_id = execution_input.turn_identity.session_id
        profile_owner = self._require_owner(evidence.profile_owner)
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
            "consultation",
            "safety_escalation",
        }:
            raise ValueError(
                "consultation execution requires consultation ownership"
            )
        if snapshot is not None:
            if (
                snapshot.session_id != session_id
                or snapshot.profile_owner != profile_owner
                or snapshot.version != conversation_version
            ):
                raise ConversationStateConflict(session_id)

        source_turn_id = execution_input.turn_identity.turn_id
        previous = (
            snapshot.consultation_slot.state
            if snapshot is not None
            and snapshot.consultation_slot is not None
            else None
        )
        if (
            previous is not None
            and previous.medical_escalation is not None
        ):
            assessment = previous.medical_escalation.assessment
            result = ConsultationApplicationResult(
                intent="consultation_medical_escalation",
                conversation_version=conversation_version + 1,
                observations=previous.observations,
                conclusion=assessment.conclusion,
                escalation_triggers=assessment.escalation_triggers,
                stop_skincare_advice=True,
                card_display_contract=self._zero_cards(),
            )
            return self._execution_result(
                result,
                route_decision=route_decision,
                consultation=previous,
                profile_owner=profile_owner,
                replace_consultation=False,
            )
        if (
            previous is not None
            and previous.confirmable_assessment is not None
            and previous.medical_escalation is None
            and not consultation_evidence.observations
        ):
            return self._execute_confirmation_turn(
                execution_input,
                snapshot=snapshot,
                route_decision=route_decision,
                source_turn_id=source_turn_id,
            )
        dynamic = advance_dynamic_consultation(
            previous=previous,
            evidence=consultation_evidence,
            source_turn_id=source_turn_id,
            conversation_version=conversation_version + 1,
        )
        changed = (
            previous is None
            or previous != dynamic.next_consultation
        )
        consultation = dynamic.next_consultation
        replace_consultation = True
        if (
            dynamic.stop_skincare_advice
            or dynamic.ready_for_confirmation
        ):
            conclusion = dynamic.conclusion
            if conclusion is None:
                raise RuntimeError(
                    "consultation assessment requires conclusion"
                )
            assessment = ConfirmableConsultationAssessment(
                assessment_kind=(
                    "medical_escalation"
                    if dynamic.stop_skincare_advice
                    else "provisional"
                ),
                observation_set_version=(
                    conversation_version + 1
                    if changed
                    else conversation_version
                ),
                observations=consultation.observations,
                conclusion=conclusion,
                conclusion_source_turn_id=source_turn_id,
                escalation_triggers=dynamic.escalation_triggers,
                stop_skincare_advice=dynamic.stop_skincare_advice,
            )
            if (
                dynamic.stop_skincare_advice
                and previous is not None
                and previous.confirmable_assessment is not None
                and previous.confirmable_assessment
                .conclusion.confirmed_by_user
            ):
                consultation = previous
                replace_consultation = False
            else:
                medical = (
                    RecordedMedicalEscalation(
                        recorded_at_conversation_version=(
                            conversation_version + 1
                        ),
                        assessment=assessment,
                    )
                    if dynamic.stop_skincare_advice
                    else None
                )
                consultation = ConsultationSubstate(
                    started_at_conversation_version=(
                        consultation.started_at_conversation_version
                    ),
                    observations=consultation.observations,
                    confirmable_assessment=assessment,
                    medical_escalation=medical,
                )
            result = ConsultationApplicationResult(
                intent=(
                    "consultation_medical_escalation"
                    if dynamic.stop_skincare_advice
                    else "consultation_provisional"
                ),
                conversation_version=conversation_version + 1,
                observations=consultation.observations,
                conclusion=assessment.conclusion,
                escalation_triggers=assessment.escalation_triggers,
                stop_skincare_advice=assessment.stop_skincare_advice,
                card_display_contract=self._zero_cards(),
            )
        else:
            result = ConsultationApplicationResult(
                intent=(
                    "consultation_entry"
                    if previous is None and not dynamic.observations
                    else (
                        "consultation_answer"
                        if changed
                        else "consultation_clarification"
                    )
                ),
                conversation_version=conversation_version + 1,
                observations=dynamic.observations,
                next_question=dynamic.next_question,
                reason=(
                    "answer_required"
                    if not changed and snapshot is not None
                    else None
                ),
                card_display_contract=self._zero_cards(),
            )
        return self._execution_result(
            result,
            route_decision=route_decision,
            consultation=consultation,
            profile_owner=profile_owner,
            replace_consultation=replace_consultation,
        )

    def _execute_confirmation_turn(
        self,
        execution_input: ProcessorExecutionInput,
        *,
        snapshot: ConversationSnapshot,
        route_decision: UnifiedRouteDecision,
        source_turn_id: str,
    ) -> ExecutionResult:
        evidence = execution_input.routing_evidence
        consultation_evidence = evidence.consultation
        conversation_version = evidence.conversation_version
        profile_owner = self._require_owner(evidence.profile_owner)
        consultation_slot = snapshot.consultation_slot
        if consultation_slot is None:
            raise ValueError(
                "consultation confirmation requires consultation state"
            )
        consultation = consultation_slot.state
        assessment = consultation.confirmable_assessment
        if assessment is None:
            raise ValueError(
                "consultation confirmation requires assessment"
            )
        if consultation_evidence.confirmation_status == "rejected":
            result = ConsultationApplicationResult(
                intent="consultation_rejection",
                conversation_version=conversation_version + 1,
                observations=consultation.observations,
                reason="rejected_by_user",
                card_display_contract=self._zero_cards(),
            )
            return self._execution_result(
                result,
                route_decision=route_decision,
                consultation=consultation,
                profile_owner=profile_owner,
                replace_consultation=False,
            )
        if consultation_evidence.confirmation_status != "affirmed":
            result = ConsultationApplicationResult(
                intent="consultation_clarification",
                conversation_version=conversation_version + 1,
                observations=consultation.observations,
                reason="confirmation_required",
                card_display_contract=self._zero_cards(),
            )
            return self._execution_result(
                result,
                route_decision=route_decision,
                consultation=consultation,
                profile_owner=profile_owner,
                replace_consultation=False,
            )
        skin_target = assessment.conclusion.skin_target
        if skin_target is None:
            raise ValueError(
                "consultation confirmation requires skin target"
            )
        if assessment.conclusion.confirmed_by_user:
            profile_patch = None
            profile = snapshot.session_profile
            if profile is None:
                updates = self._profile_updates_for_conclusion(
                    assessment.conclusion
                )
                profile_patch = ProfileLanePatch(
                    profile_owner=profile_owner,
                    updates=updates,
                    subject_scope="self",
                    source_turn_id=(
                        consultation.confirmation_source_turn_id
                        or source_turn_id
                    ),
                )
                profile = reduce_session_profile(
                    previous=SessionProfile(),
                    updates=profile_patch.updates,
                    subject_scope=profile_patch.subject_scope,
                    source_turn_id=profile_patch.source_turn_id,
                    conversation_version=conversation_version + 1,
                ).profile
            result = ConsultationApplicationResult(
                intent="consultation_confirmation",
                conversation_version=conversation_version + 1,
                observations=consultation.observations,
                conclusion=assessment.conclusion,
                session_profile=profile,
                card_display_contract=self._zero_cards(),
            )
            return self._execution_result(
                result,
                route_decision=route_decision,
                consultation=consultation,
                profile_owner=profile_owner,
                profile_patch=profile_patch,
                replace_consultation=False,
            )
        transition = confirm_prevalidated_conclusion(
            consultation,
            current_conversation_version=conversation_version,
            source_turn_id=source_turn_id,
            expected_skin_target=skin_target,
            expected_conclusion_source_turn_id=(
                assessment.conclusion_source_turn_id
            ),
        )
        updates = self._profile_updates_for_conclusion(
            transition.output.conclusion
        )
        profile = reduce_session_profile(
            previous=snapshot.session_profile or SessionProfile(),
            updates=updates,
            subject_scope="self",
            source_turn_id=source_turn_id,
            conversation_version=conversation_version + 1,
        ).profile
        result = ConsultationApplicationResult(
            intent="consultation_confirmation",
            conversation_version=conversation_version + 1,
            observations=transition.next_consultation.observations,
            conclusion=transition.output.conclusion,
            session_profile=profile,
            card_display_contract=self._zero_cards(),
        )
        return self._execution_result(
            result,
            route_decision=route_decision,
            consultation=transition.next_consultation,
            profile_owner=profile_owner,
            profile_patch=ProfileLanePatch(
                profile_owner=profile_owner,
                updates=updates,
                subject_scope="self",
                source_turn_id=source_turn_id,
            ),
        )








    def _execution_result(
        self,
        result: ConsultationApplicationResult,
        *,
        route_decision: UnifiedRouteDecision,
        consultation: ConsultationSubstate,
        profile_owner: ProfileOwnerRef,
        profile_patch: ProfileLanePatch | None = None,
        replace_consultation: bool = True,
    ) -> ExecutionResult:
        message = self._message(result)
        packet = build_presentation_packet(
            mode=route_decision.presentation_mode,
            responsibility=route_decision.responsibility,
            user_need_summary=message,
            winner_status="NOT_APPLICABLE",
            card_display=result.card_display_contract,
            cards=(),
            selection_slots=(),
            concept_slots=(),
            merchant_claims=(),
            pitfalls=(),
        )
        presentation = self._presentation_compiler.compile(
            PresentationCompileInputs(
                packet=packet,
                card_display=result.card_display_contract,
                public_mode=route_decision.presentation_mode,
                copywriter_policy=(
                    "medical_escalation"
                    if result.intent
                    == "consultation_medical_escalation"
                    else "eligible"
                ),
            )
        )
        return ExecutionResult(
            decision=route_decision,
            state_delta=ConversationStateDelta(
                profile_owner=profile_owner,
                consultation=(
                    LaneMutation[ConsultationSubstate](
                        action="replace",
                        value=consultation,
                    )
                    if replace_consultation
                    else LaneMutation[ConsultationSubstate](
                        action="preserve"
                    )
                ),
                clarification=LaneMutation[
                    ClarificationLaneState
                ](
                    action="clear",
                    reason="resolved by consultation",
                ),
                profile=(
                    LaneMutation[ProfileLanePatch](
                        action="replace",
                        value=profile_patch,
                    )
                    if profile_patch is not None
                    else LaneMutation[ProfileLanePatch](
                        action="preserve"
                    )
                ),
            ),
            terminal=PresentationTerminal(data=presentation),
            audit_events=(
                StageEvent(
                    data=StageData(
                        stage="state",
                        summary="已读取轻问诊观察与确认状态。",
                    )
                ),
                IntentEvent(data=IntentData(mode=result.intent)),
                self._typed_result_event(result),
                AnswerContractEvent(
                    data=AnswerContractData(
                        product_count=0,
                        winner_status="NOT_APPLICABLE",
                        has_unknown_skin=False,
                    )
                ),
                CardDisplayContractEvent(
                    data=result.card_display_contract
                ),
            ),
        )

    @staticmethod
    def _profile_updates_for_conclusion(
        conclusion,
    ) -> tuple[SessionProfileUpdate, ...]:
        skin_target = conclusion.skin_target
        if skin_target is None:
            raise ValueError(
                "confirmed consultation requires a base skin direction"
            )
        if skin_target == "oily_sensitive":
            updates: list[SessionProfileUpdate] = [
                BaseSkinUpdate(
                    value="oily",
                    confirmation="confirmed",
                ),
                StableTendencyUpdate(
                    value="sensitivity",
                    confirmation="confirmed",
                ),
            ]
        elif skin_target == "sensitive":
            updates = [
                StableTendencyUpdate(
                    value="sensitivity",
                    confirmation="confirmed",
                )
            ]
        else:
            updates = [
                BaseSkinUpdate(
                    value=skin_target,
                    confirmation="confirmed",
                )
            ]
        existing_tendencies = {
            item.value
            for item in updates
            if isinstance(item, StableTendencyUpdate)
        }
        updates.extend(
            StableTendencyUpdate(
                value=value,
                confirmation="confirmed",
            )
            for value in conclusion.stable_tendencies
            if value not in existing_tendencies
        )
        updates.extend(
            CurrentConditionUpdate(value=value)
            for value in conclusion.current_conditions
        )
        return tuple(updates)

    @staticmethod
    def _zero_cards() -> CardDisplayContract:
        return CardDisplayContract(
            mode="none",
            visible_product_ids=(),
            max_cards=0,
            reason=None,
        )

    @staticmethod
    def _typed_result_event(
        result: ConsultationApplicationResult,
    ) -> SseEvent:
        if result.intent == "consultation_provisional":
            assert result.conclusion is not None
            return ConsultationProvisionalEvent(
                data=ConsultationProvisionalData(
                    conversation_version=result.conversation_version,
                    observations=list(result.observations),
                    conclusion=result.conclusion,
                )
            )
        if result.intent == "consultation_medical_escalation":
            assert result.conclusion is not None
            return MedicalEscalationEvent(
                data=MedicalEscalationData(
                    conversation_version=result.conversation_version,
                    observations=list(result.observations),
                    conclusion=result.conclusion,
                    escalation_triggers=list(
                        result.escalation_triggers
                    ),
                )
            )
        if result.intent == "consultation_confirmation":
            assert result.conclusion is not None
            assert result.session_profile is not None
            return ProfileConfirmationEvent(
                data=ProfileConfirmationData(
                    conversation_version=result.conversation_version,
                    conclusion=result.conclusion,
                    session_profile=result.session_profile,
                    profile_persistence=result.profile_persistence,
                )
            )
        return ConsultationObservationEvent(
            data=ConsultationObservationData(
                conversation_version=result.conversation_version,
                observations=list(result.observations),
                next_question=result.next_question,
                reason=result.reason,
            )
        )

    @staticmethod
    def _message(result: ConsultationApplicationResult) -> str:
        if result.intent in {
            "consultation_entry",
            "consultation_answer",
        }:
            assert result.next_question is not None
            return result.next_question.prompt
        if result.intent == "consultation_clarification":
            if result.next_question is not None:
                return (
                    "请回答“会”“不会”“偶尔”或“不清楚”。"
                    f"{result.next_question.prompt}"
                )
            return "请明确确认或否认这项暂定结论。"
        if result.intent == "consultation_rejection":
            return "已保留观察记录，但不会更新当前会话画像。"
        if result.intent == "consultation_medical_escalation":
            assert result.conclusion is not None
            return result.conclusion.escalation
        if result.intent == "consultation_provisional":
            assert result.conclusion is not None
            conclusion = result.conclusion
            skin_labels = {
                "oily_sensitive": "油性肤质，并有敏感倾向",
                "oily": "油性肤质",
                "dry": "干性肤质",
                "combination": "混合性肤质",
                "sensitive": "敏感性肤质",
                "normal": "中性肤质",
            }
            tendency_labels = {
                "sensitivity": "容易受刺激",
                "seasonal_redness": "换季容易泛红",
                "acid_triggered_irritation": "用酸后容易不适",
                "dehydration": "缺水倾向",
                "other": "其他稳定倾向",
            }
            condition_labels = {
                "redness": "泛红",
                "stinging": "刺痛",
                "flaking": "起皮",
                "tightness": "紧绷",
                "swelling": "红肿",
                "broken_skin": "破皮",
                "oozing": "渗出",
                "persistent_pain": "持续疼痛",
            }
            skin_target = conclusion.skin_target
            assert skin_target is not None
            message = f"目前更接近{skin_labels[skin_target]}"
            if conclusion.stable_tendencies:
                message += "，同时有" + "、".join(
                    tendency_labels[item]
                    for item in conclusion.stable_tendencies
                )
            if conclusion.current_conditions:
                message += "；当前还有" + "、".join(
                    condition_labels[item]
                    for item in conclusion.current_conditions
                )
            return (
                f"{message}。你看看和自己的感受是否一致，"
                "确认后只在当前会话里使用。"
            )
        assert result.session_profile is not None
        if result.profile_persistence is None:
            return "已确认结论，这份画像只在当前会话内使用。"
        if result.profile_persistence.outcome == "retry_required":
            return (
                "已确认本次结论，但画像暂未写入；"
                "请稍后再次确认以重试。"
            )
        if result.profile_persistence.outcome == "preserved_existing":
            return (
                "已确认本次结论；长期画像已有不同值，"
                "本次不会静默覆盖。"
            )
        return "已确认结论，并按补空规则写入长期画像。"

    @staticmethod
    def _require_owner(
        profile_owner: ProfileOwnerRef | None,
    ) -> ProfileOwnerRef:
        if profile_owner is None:
            raise ValueError("consultation requires a profile owner")
        return profile_owner
