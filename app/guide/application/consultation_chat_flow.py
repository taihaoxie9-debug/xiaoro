from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
import logging
from uuid import uuid4

from app.guide.application.consultation_coordinator import (
    ConsultationApplicationCoordinator,
    ConsultationApplicationResult,
)
from app.guide.application.contracts import UserTurn
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStatePort,
    SessionLockPort,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompileInputs,
    PresentationCompiler,
)
from app.guide.presentation.presentation_packet import (
    build_presentation_packet,
)
from app.guide.presentation.sse_events import (
    AnswerContractData,
    AnswerContractEvent,
    CardDisplayContractEvent,
    ConsultationObservationData,
    ConsultationObservationEvent,
    ConsultationProvisionalData,
    ConsultationProvisionalEvent,
    EndData,
    EndEvent,
    ErrorData,
    ErrorEvent,
    IntentData,
    IntentEvent,
    MedicalEscalationData,
    MedicalEscalationEvent,
    MessageData,
    MessageEvent,
    ProfileConfirmationData,
    ProfileConfirmationEvent,
    PresentationContractEvent,
    SseEvent,
    StageData,
    StageEvent,
    StartData,
    StartEvent,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


logger = logging.getLogger(__name__)


class ConsultationChatFlow:
    def __init__(
        self,
        *,
        coordinator: ConsultationApplicationCoordinator,
        conversation_state: ConversationStatePort,
        session_locks: SessionLockPort,
        presentation_compiler: PresentationCompiler | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._conversation_state = conversation_state
        self._session_locks = session_locks
        self._presentation_compiler = (
            presentation_compiler
            if presentation_compiler is not None
            else PresentationCompiler(copywriter=None)
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    def claims(self, turn: UserTurn) -> bool:
        owner = turn.profile_owner
        if owner is None:
            return False
        return self._coordinator.claims_turn(
            session_id=turn.session_id,
            conversation_version=turn.conversation_version,
            message=turn.message,
            source_turn_id=self._source_turn_id(),
            profile_owner=owner,
        )

    def has_session(self, turn: UserTurn) -> bool:
        snapshot = self._conversation_state.load(turn.session_id)
        if snapshot is None:
            return False
        if snapshot.profile_owner != turn.profile_owner:
            raise ConversationStateConflict(turn.session_id)
        return snapshot.consultation is not None

    def has_dynamic_session(self, turn: UserTurn) -> bool:
        snapshot = self._conversation_state.load(turn.session_id)
        if snapshot is None:
            return False
        if snapshot.profile_owner != turn.profile_owner:
            raise ConversationStateConflict(turn.session_id)
        consultation = snapshot.consultation
        return (
            consultation is not None
            and any(
                observation.observation_id is not None
                for observation in consultation.observations
            )
        )

    def has_authority(self, turn: UserTurn) -> bool:
        """Return whether this shared Guide state owns the requested version."""
        snapshot = self._conversation_state.load(turn.session_id)
        if snapshot is None:
            return False
        if (
            snapshot.profile_owner != turn.profile_owner
            or snapshot.version != turn.conversation_version
        ):
            raise ConversationStateConflict(turn.session_id)
        return True

    def stream(self, turn: UserTurn) -> Iterator[SseEvent]:
        yield StartEvent(data=StartData(session_id=turn.session_id))
        with self._session_locks.hold(turn.session_id):
            try:
                result = self._coordinator.handle_turn(
                    session_id=turn.session_id,
                    conversation_version=turn.conversation_version,
                    message=turn.message,
                    source_turn_id=self._source_turn_id(),
                    profile_owner=self._require_owner(turn),
                    confirmed_at=self._clock(),
                )
                if result is None:
                    raise RuntimeError(
                        "consultation flow received an unowned turn"
                    )
                buffered = list(self._result_events(result))
            except ConversationStateConflict:
                latest = self._conversation_state.load(turn.session_id)
                buffered = [
                    ErrorEvent(
                        data=ErrorData(
                            code="CONSULTATION_INTERNAL_ERROR",
                            message="轻问诊暂时不可用，请稍后重试。",
                        )
                    )
                ]
                if latest is not None:
                    logger.info(
                        "consultation conversation conflict at version %s",
                        latest.version,
                    )
            except Exception:
                logger.exception("consultation flow failed closed")
                buffered = [
                    ErrorEvent(
                        data=ErrorData(
                            code="CONSULTATION_INTERNAL_ERROR",
                            message="轻问诊暂时不可用，请稍后重试。",
                        )
                    )
                ]
        yield from buffered

    def stream_meaning(
        self,
        turn: UserTurn,
        *,
        meaning: TurnMeaning,
    ) -> Iterator[SseEvent]:
        if type(meaning) is not TurnMeaning:
            raise TypeError("meaning must be an exact TurnMeaning")
        yield StartEvent(data=StartData(session_id=turn.session_id))
        with self._session_locks.hold(turn.session_id):
            try:
                result = self._coordinator.handle_dynamic_turn(
                    session_id=turn.session_id,
                    conversation_version=turn.conversation_version,
                    message=turn.message,
                    meaning=meaning,
                    source_turn_id=self._source_turn_id(),
                    profile_owner=self._require_owner(turn),
                    confirmed_at=self._clock(),
                )
                buffered = list(self._result_events(result))
            except ConversationStateConflict:
                latest = self._conversation_state.load(turn.session_id)
                buffered = [
                    ErrorEvent(
                        data=ErrorData(
                            code="CONSULTATION_INTERNAL_ERROR",
                            message="轻问诊暂时不可用，请稍后重试。",
                        )
                    )
                ]
                if latest is not None:
                    logger.info(
                        "dynamic consultation conflict at version %s",
                        latest.version,
                    )
            except Exception:
                logger.exception(
                    "dynamic consultation flow failed closed"
                )
                buffered = [
                    ErrorEvent(
                        data=ErrorData(
                            code="CONSULTATION_INTERNAL_ERROR",
                            message="轻问诊暂时不可用，请稍后重试。",
                        )
                    )
                ]
        yield from buffered

    def _result_events(
        self,
        result: ConsultationApplicationResult,
    ) -> Iterator[SseEvent]:
        message = self._message(result)
        packet = build_presentation_packet(
            mode="consultation",
            user_need_summary=message,
            winner_status="NOT_APPLICABLE",
            card_display=result.card_display_contract,
            cards=(),
            selection_slots=(),
            concept_slots=(),
            merchant_claims=(),
            pitfalls=(),
        )
        presentation_event = PresentationContractEvent(
            data=self._presentation_compiler.compile(
                PresentationCompileInputs(
                    packet=packet,
                    card_display=result.card_display_contract,
                    copywriter_policy=(
                        "medical_escalation"
                        if result.intent
                        == "consultation_medical_escalation"
                        else "eligible"
                    ),
                )
            )
        )
        yield StageEvent(
            data=StageData(
                stage="state",
                summary="已读取轻问诊观察与确认状态。",
            )
        )
        yield IntentEvent(data=IntentData(mode=result.intent))
        yield self._typed_result_event(result)
        yield AnswerContractEvent(
            data=AnswerContractData(
                product_count=0,
                winner_status="NOT_APPLICABLE",
                has_unknown_skin=False,
            )
        )
        yield CardDisplayContractEvent(
            data=result.card_display_contract
        )
        yield presentation_event
        yield MessageEvent(data=MessageData(content=message))
        yield EndEvent(
            data=EndData(
                conversation_version=result.conversation_version
            )
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
    def _source_turn_id() -> str:
        return f"turn_{uuid4().hex}"

    @staticmethod
    def _require_owner(turn: UserTurn):
        if turn.profile_owner is None:
            raise ValueError("consultation requires a profile owner")
        return turn.profile_owner
