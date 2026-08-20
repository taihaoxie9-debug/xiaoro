from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.application.consultation_assessment import (
    assess_consultation,
)
from app.guide.application.consultation_collection import (
    ConsultationCollectionResult,
    ConsultationCollectionService,
)
from app.guide.application.dynamic_consultation import (
    DynamicConsultationResult,
    advance_dynamic_consultation,
)
from app.guide.application.consultation_confirmation import (
    ConsultationConfirmationRejected,
    ConsultationConfirmationTransition,
    ConsultationMedicalEscalationTransition,
    ConsultationProvisionalTransition,
    confirm_provisional_conclusion,
    record_medical_escalation,
    record_provisional_conclusion,
    validate_explicit_confirmation,
)
from app.guide.feedback.consultation_state import (
    ConfirmableConsultationAssessment,
    ConsultationSubstate,
    RecordedMedicalEscalation,
)
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStatePort,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.profile_policy import (
    ConfirmedSessionFact,
    CurrentExplicitFact,
    ProfilePersistencePlan,
    ProfilePersistenceRetry,
    ResolvedProfileContext,
    reconcile_confirmed_consultation_profile,
    resolve_profile_context,
)
from app.guide.feedback.profile_state import (
    ProfileStateConflict,
    ProfileStateCorrupt,
    ProfileStatePort,
)
from app.guide.feedback.session_profile import (
    BaseSkinUpdate,
    CurrentConditionUpdate,
    SessionProfile,
    SessionProfileUpdate,
    StableTendencyUpdate,
    reduce_session_profile,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationInput,
    ConsultationEscalationTrigger,
)
from app.guide.understanding.consultation_parsing import (
    ConsultationTurnParse,
    parse_consultation_turn,
)
from app.guide.understanding.consultation_questions import (
    ConsultationQuestion,
)
from app.guide.understanding.contracts import SkinTarget
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


ConsultationApplicationIntent = Literal[
    "consultation_entry",
    "consultation_answer",
    "consultation_clarification",
    "consultation_provisional",
    "consultation_confirmation",
    "consultation_rejection",
    "consultation_medical_escalation",
]
ConsultationApplicationReason = Literal[
    "answer_required",
    "confirmation_required",
    "rejected_by_user",
]


class ConsultationApplicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    intent: ConsultationApplicationIntent
    conversation_version: int = Field(ge=1)
    observations: tuple[ConsultationObservation, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    next_question: ConsultationQuestion | None = None
    conclusion: ProvisionalConsultationConclusion | None = None
    escalation_triggers: tuple[
        ConsultationEscalationTrigger,
        ...,
    ] = Field(
        default_factory=tuple,
        max_length=3,
    )
    stop_skincare_advice: bool = False
    reason: ConsultationApplicationReason | None = None
    session_profile: SessionProfile | None = None
    profile_persistence: (
        ProfilePersistencePlan | ProfilePersistenceRetry | None
    ) = None
    card_display_contract: CardDisplayContract

    @field_validator(
        "observations",
        "escalation_triggers",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_output_shape(self) -> Self:
        cards = self.card_display_contract
        if (
            cards.mode != "none"
            or cards.visible_product_ids
            or cards.max_cards != 0
            or cards.reason is not None
        ):
            raise ValueError("consultation outputs must be zero-card")
        if self.intent in {
            "consultation_provisional",
            "consultation_confirmation",
            "consultation_medical_escalation",
        }:
            if self.conclusion is None:
                raise ValueError(
                    "assessment outputs require a conclusion"
                )
        elif self.conclusion is not None:
            raise ValueError(
                "non-assessment outputs cannot carry a conclusion"
            )
        if self.intent == "consultation_confirmation":
            if (
                not self.conclusion.confirmed_by_user
                or self.session_profile is None
            ):
                raise ValueError(
                    "confirmation output requires a session profile"
                )
        elif (
            self.session_profile is not None
            or self.profile_persistence is not None
        ):
            raise ValueError(
                "only confirmation output carries profile state"
            )
        if self.intent == "consultation_medical_escalation":
            if (
                not self.escalation_triggers
                or not self.stop_skincare_advice
                or self.conclusion.confirmed_by_user
            ):
                raise ValueError(
                    "medical escalation output must be terminal"
                )
        if (self.intent in {
            "consultation_clarification",
            "consultation_rejection",
        }) != (self.reason is not None):
            raise ValueError(
                "clarification and rejection outputs require a reason"
            )
        return self


class ConsultationApplicationCoordinator:
    def __init__(
        self,
        *,
        conversation_state: ConversationStatePort,
        profile_state: ProfileStatePort | None = None,
        long_term_profile_opt_in: bool = False,
    ) -> None:
        if (
            long_term_profile_opt_in
            and profile_state is None
        ):
            raise ValueError(
                "long-term profile opt-in requires a profile state"
            )
        self._conversation_state = conversation_state
        self._profile_state = profile_state
        self._long_term_profile_opt_in = long_term_profile_opt_in
        self._collection = ConsultationCollectionService(
            conversation_state=conversation_state,
        )

    def claims_turn(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        source_turn_id: str,
        profile_owner: ProfileOwnerRef,
    ) -> bool:
        if type(profile_owner) is not ProfileOwnerRef:
            raise TypeError(
                "profile_owner must be an exact ProfileOwnerRef"
            )
        snapshot = self._conversation_state.load(session_id)
        if snapshot is None:
            parsed = parse_consultation_turn(
                message,
                source_turn_id=source_turn_id,
            )
            return parsed is not None and parsed.kind == "entry"
        snapshot = self._load_authority(
            session_id=session_id,
            conversation_version=conversation_version,
            profile_owner=profile_owner,
        )
        consultation = snapshot.consultation
        if consultation is None:
            parsed = parse_consultation_turn(
                message,
                source_turn_id=source_turn_id,
            )
            return parsed is not None and parsed.kind == "entry"
        if consultation.medical_escalation is not None:
            return True
        assessment = consultation.confirmable_assessment
        if assessment is None or not assessment.conclusion.confirmed_by_user:
            return True
        parsed = parse_consultation_turn(
            message,
            awaiting_confirmation=True,
            source_turn_id=source_turn_id,
        )
        assert parsed is not None
        return parsed.kind == "confirm" or bool(
            parsed.escalation_triggers
        )

    def handle_turn(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        source_turn_id: str,
        profile_owner: ProfileOwnerRef,
        confirmed_at: datetime | None = None,
    ) -> ConsultationApplicationResult | None:
        snapshot = self._load_authority(
            session_id=session_id,
            conversation_version=conversation_version,
            profile_owner=profile_owner,
        )
        consultation = (
            snapshot.consultation if snapshot is not None else None
        )
        if consultation is None:
            parsed = parse_consultation_turn(
                message,
                source_turn_id=source_turn_id,
            )
            if parsed is None or parsed.kind != "entry":
                return None
            collected = self._collection.begin(
                session_id=session_id,
                conversation_version=conversation_version,
                skin_target=None,
                profile_owner=profile_owner,
            )
            if collected is None:
                return None
            if parsed.escalation_triggers:
                active = self._require_snapshot(session_id)
                return self._record_medical(
                    active,
                    parsed=parsed,
                    source_turn_id=source_turn_id,
                )
            return self._collection_output(
                collected,
                intent="consultation_entry",
            )

        assessment = consultation.confirmable_assessment
        if consultation.medical_escalation is not None:
            return self._assessment_output(snapshot)
        if assessment is not None:
            parsed = parse_consultation_turn(
                message,
                awaiting_confirmation=True,
                source_turn_id=source_turn_id,
            )
            assert parsed is not None
            if parsed.escalation_triggers:
                if assessment.conclusion.confirmed_by_user:
                    return self._current_turn_medical_output(
                        snapshot,
                        parsed=parsed,
                        source_turn_id=source_turn_id,
                    )
                return self._record_medical(
                    snapshot,
                    parsed=parsed,
                    source_turn_id=source_turn_id,
                )
            if assessment.assessment_kind == "medical_escalation":
                return self._assessment_output(snapshot)
            if assessment.conclusion.confirmed_by_user:
                return self._handle_confirmed_retry(
                    snapshot,
                    message=message,
                    source_turn_id=source_turn_id,
                    confirmed_at=confirmed_at,
                )
            return self._handle_confirmation(
                snapshot,
                message=message,
                source_turn_id=source_turn_id,
                confirmed_at=confirmed_at,
            )

        next_question = self._next_question(consultation)
        if next_question is None:
            return self._record_provisional(
                snapshot,
                source_turn_id=source_turn_id,
            )
        parsed = parse_consultation_turn(
            message,
            active_question=next_question,
            source_turn_id=source_turn_id,
        )
        assert parsed is not None
        if parsed.kind == "clarify" and not parsed.escalation_triggers:
            return self._read_only_output(
                snapshot,
                intent="consultation_clarification",
                reason="answer_required",
                next_question=next_question,
            )
        if parsed.kind == "answer":
            collected = self._collection.answer(
                session_id=session_id,
                conversation_version=conversation_version,
                answer=parsed.answer,
                source_turn_id=source_turn_id,
                profile_owner=profile_owner,
            )
            snapshot = self._require_snapshot(session_id)
            if parsed.escalation_triggers:
                return self._record_medical(
                    snapshot,
                    parsed=parsed,
                    source_turn_id=source_turn_id,
                )
            if collected.next_question is not None:
                return self._collection_output(
                    collected,
                    intent="consultation_answer",
                )
            return self._record_provisional(
                snapshot,
                source_turn_id=source_turn_id,
            )
        return self._record_medical(
            snapshot,
            parsed=parsed,
            source_turn_id=source_turn_id,
        )

    def handle_dynamic_turn(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        meaning: TurnMeaning,
        source_turn_id: str,
        profile_owner: ProfileOwnerRef,
        confirmed_at: datetime | None = None,
    ) -> ConsultationApplicationResult:
        snapshot = self._load_authority(
            session_id=session_id,
            conversation_version=conversation_version,
            profile_owner=profile_owner,
        )
        consultation = (
            snapshot.consultation if snapshot is not None else None
        )
        if consultation is not None:
            if consultation.medical_escalation is not None:
                assert snapshot is not None
                return self._assessment_output(
                    self._advance_read_only_snapshot(snapshot)
                )

        dynamic = advance_dynamic_consultation(
            previous=consultation,
            message=message,
            meaning=meaning,
            source_turn_id=source_turn_id,
            conversation_version=conversation_version + 1,
        )
        if (
            consultation is not None
            and consultation.confirmable_assessment is not None
            and dynamic.observations == consultation.observations
        ):
            result = self.handle_turn(
                session_id=session_id,
                conversation_version=conversation_version,
                message=message,
                source_turn_id=source_turn_id,
                profile_owner=profile_owner,
                confirmed_at=confirmed_at,
            )
            if result is None:
                return self._read_only_output(
                    snapshot,
                    intent="consultation_clarification",
                    reason="confirmation_required",
                )
            return result

        stored, changed = self._save_dynamic_result(
            snapshot,
            session_id=session_id,
            profile_owner=profile_owner,
            dynamic=dynamic,
            source_turn_id=source_turn_id,
        )
        if (
            dynamic.stop_skincare_advice
            or dynamic.ready_for_confirmation
        ):
            return self._assessment_output(stored)
        return ConsultationApplicationResult(
            intent=(
                "consultation_entry"
                if snapshot is None and not dynamic.observations
                else "consultation_answer"
                if changed
                else "consultation_clarification"
            ),
            conversation_version=stored.version,
            observations=dynamic.observations,
            next_question=dynamic.next_question,
            reason=(
                "answer_required"
                if not changed and snapshot is not None
                else None
            ),
            card_display_contract=self._zero_cards(),
        )

    def resolve_turn_profile(
        self,
        *,
        session_id: str,
        profile_owner: ProfileOwnerRef,
        current_explicit_skin: SkinTarget | None = None,
        source_turn_id: str | None = None,
    ) -> ResolvedProfileContext:
        if type(profile_owner) is not ProfileOwnerRef:
            raise TypeError(
                "profile_owner must be an exact ProfileOwnerRef"
            )
        if current_explicit_skin is not None and not isinstance(
            current_explicit_skin,
            SkinTarget,
        ):
            raise TypeError("current_explicit_skin must be a SkinTarget")
        if (current_explicit_skin is None) != (source_turn_id is None):
            raise ValueError(
                "current explicit skin requires source turn provenance"
            )
        snapshot = self._conversation_state.load(session_id)
        if (
            snapshot is not None
            and snapshot.profile_owner != profile_owner
        ):
            raise ConversationStateConflict(session_id)

        current_explicit = (
            [
                CurrentExplicitFact(
                    field="skin_type",
                    value=current_explicit_skin.value,
                    source_turn_id=source_turn_id,
                )
            ]
            if current_explicit_skin is not None
            and source_turn_id is not None
            else []
        )
        confirmed_session = self._confirmed_session_facts(snapshot)
        profile = (
            self._profile_state.load(profile_owner)
            if (
                self._long_term_profile_opt_in
                and self._profile_state is not None
            )
            else None
        )
        return resolve_profile_context(
            current_explicit=current_explicit,
            confirmed_session=confirmed_session,
            profile=profile,
        )

    def _handle_confirmation(
        self,
        snapshot: ConversationSnapshot,
        *,
        message: str,
        source_turn_id: str,
        confirmed_at: datetime | None,
    ) -> ConsultationApplicationResult:
        consultation = snapshot.consultation
        assert consultation is not None
        assessment = consultation.confirmable_assessment
        assert assessment is not None
        parsed = parse_consultation_turn(
            message,
            awaiting_confirmation=True,
            source_turn_id=source_turn_id,
        )
        assert parsed is not None
        if parsed.kind == "reject":
            return self._read_only_output(
                snapshot,
                intent="consultation_rejection",
                reason="rejected_by_user",
            )
        if parsed.kind != "confirm":
            return self._read_only_output(
                snapshot,
                intent="consultation_clarification",
                reason="confirmation_required",
            )
        skin_target = assessment.conclusion.skin_target
        assert skin_target is not None
        try:
            transition = confirm_provisional_conclusion(
                consultation,
                current_conversation_version=snapshot.version,
                message=message,
                source_turn_id=source_turn_id,
                expected_skin_target=skin_target,
                expected_conclusion_source_turn_id=(
                    assessment.conclusion_source_turn_id
                ),
            )
        except ConsultationConfirmationRejected as error:
            if error.code not in {
                "mismatched_confirmation",
                "ambiguous_confirmation",
                "non_affirmative",
            }:
                raise
            return self._read_only_output(
                snapshot,
                intent="consultation_clarification",
                reason="confirmation_required",
            )
        confirmed = self._save_transition(
            snapshot,
            transition,
            session_profile_updates=(
                self._profile_updates_for_conclusion(
                    assessment.conclusion
                )
            ),
            profile_source_turn_id=(
                transition.output.confirmation_source_turn_id
            ),
        )
        persistence = None
        if self._long_term_profile_opt_in:
            self._require_confirmation_time(confirmed_at)
            persistence = self._persist_confirmation_profile(
                confirmed,
                confirmed_at=confirmed_at,
            )
        return self._confirmation_output(
            confirmed,
            persistence=persistence,
        )

    def _handle_confirmed_retry(
        self,
        snapshot: ConversationSnapshot,
        *,
        message: str,
        source_turn_id: str,
        confirmed_at: datetime | None,
    ) -> ConsultationApplicationResult | None:
        consultation = snapshot.consultation
        assert consultation is not None
        assessment = consultation.confirmable_assessment
        assert assessment is not None
        skin_target = assessment.conclusion.skin_target
        assert skin_target is not None
        parsed = parse_consultation_turn(
            message,
            awaiting_confirmation=True,
            source_turn_id=source_turn_id,
        )
        assert parsed is not None
        if parsed.kind != "confirm":
            return None
        try:
            validate_explicit_confirmation(
                message,
                expected_skin_target=skin_target,
            )
        except ConsultationConfirmationRejected as error:
            if error.code not in {
                "mismatched_confirmation",
                "ambiguous_confirmation",
                "non_affirmative",
            }:
                raise
            return self._read_only_output(
                snapshot,
                intent="consultation_clarification",
                reason="confirmation_required",
            )
        snapshot = self._ensure_confirmed_session_profile(
            snapshot,
            conclusion=assessment.conclusion,
        )
        persistence = None
        if self._long_term_profile_opt_in:
            self._require_confirmation_time(confirmed_at)
            persistence = self._persist_confirmation_profile(
                snapshot,
                confirmed_at=confirmed_at,
            )
        return self._confirmation_output(
            snapshot,
            persistence=persistence,
        )

    def _persist_confirmation_profile(
        self,
        snapshot: ConversationSnapshot,
        *,
        confirmed_at: datetime,
    ) -> ProfilePersistencePlan | ProfilePersistenceRetry:
        if self._profile_state is None:
            raise RuntimeError("profile state is unavailable")
        consultation = snapshot.consultation
        assert consultation is not None
        assessment = consultation.confirmable_assessment
        assert assessment is not None
        skin_target = assessment.conclusion.skin_target
        assert skin_target is not None
        try:
            return reconcile_confirmed_consultation_profile(
                self._profile_state,
                self._conversation_state,
                snapshot,
                confirmed_at=confirmed_at,
            )
        except ProfileStateConflict:
            return ProfilePersistenceRetry(
                reason="cas_conflict",
                requested_value=skin_target,
            )
        except (OSError, ProfileStateCorrupt):
            return ProfilePersistenceRetry(
                reason="store_unavailable",
                requested_value=skin_target,
            )

    def _confirmation_output(
        self,
        snapshot: ConversationSnapshot,
        *,
        persistence: (
            ProfilePersistencePlan | ProfilePersistenceRetry | None
        ),
    ) -> ConsultationApplicationResult:
        confirmed_consultation = snapshot.consultation
        assert confirmed_consultation is not None
        confirmed_assessment = (
            confirmed_consultation.confirmable_assessment
        )
        assert confirmed_assessment is not None
        assert snapshot.session_profile is not None
        return ConsultationApplicationResult(
            intent="consultation_confirmation",
            conversation_version=snapshot.version,
            observations=confirmed_consultation.observations,
            conclusion=confirmed_assessment.conclusion,
            escalation_triggers=(),
            stop_skincare_advice=False,
            session_profile=snapshot.session_profile,
            profile_persistence=persistence,
            card_display_contract=self._zero_cards(),
        )

    def _record_provisional(
        self,
        snapshot: ConversationSnapshot,
        *,
        source_turn_id: str,
    ) -> ConsultationApplicationResult:
        consultation = snapshot.consultation
        assert consultation is not None
        assessment = assess_consultation(
            consultation,
            current_conversation_version=snapshot.version,
            conclusion_source_turn_id=source_turn_id,
        )
        transition = record_provisional_conclusion(
            consultation,
            current_conversation_version=snapshot.version,
            assessment=assessment.confirmable_assessment,
        )
        stored = self._save_transition(snapshot, transition)
        return self._assessment_output(stored)

    def _current_turn_medical_output(
        self,
        snapshot: ConversationSnapshot,
        *,
        parsed: ConsultationTurnParse,
        source_turn_id: str,
    ) -> ConsultationApplicationResult:
        consultation = snapshot.consultation
        assert consultation is not None
        assessment = assess_consultation(
            consultation,
            current_conversation_version=snapshot.version,
            conclusion_source_turn_id=source_turn_id,
            escalation=ConsultationEscalationInput(
                triggers=list(parsed.escalation_triggers),
            ),
        ).confirmable_assessment
        return ConsultationApplicationResult(
            intent="consultation_medical_escalation",
            conversation_version=snapshot.version,
            observations=consultation.observations,
            conclusion=assessment.conclusion,
            escalation_triggers=assessment.escalation_triggers,
            stop_skincare_advice=True,
            card_display_contract=self._zero_cards(),
        )

    def _record_medical(
        self,
        snapshot: ConversationSnapshot,
        *,
        parsed: ConsultationTurnParse,
        source_turn_id: str,
    ) -> ConsultationApplicationResult:
        consultation = snapshot.consultation
        assert consultation is not None
        assessment = assess_consultation(
            consultation,
            current_conversation_version=snapshot.version,
            conclusion_source_turn_id=source_turn_id,
            escalation=ConsultationEscalationInput(
                triggers=list(parsed.escalation_triggers),
            ),
        )
        transition = record_medical_escalation(
            consultation,
            current_conversation_version=snapshot.version,
            assessment=assessment.confirmable_assessment,
        )
        stored = self._save_transition(snapshot, transition)
        return self._assessment_output(stored)

    def _save_transition(
        self,
        snapshot: ConversationSnapshot,
        transition: ConsultationProvisionalTransition
        | ConsultationConfirmationTransition
        | ConsultationMedicalEscalationTransition,
        *,
        session_profile_updates: tuple[
            SessionProfileUpdate,
            ...,
        ] = (),
        profile_source_turn_id: str | None = None,
    ) -> ConversationSnapshot:
        update: dict[str, object] = {
            "version": transition.output.conversation_version,
            "consultation": transition.next_consultation,
        }
        if session_profile_updates:
            if profile_source_turn_id is None:
                raise ValueError(
                    "session profile update requires source provenance"
                )
            update["session_profile"] = reduce_session_profile(
                previous=snapshot.session_profile or SessionProfile(),
                updates=session_profile_updates,
                subject_scope="self",
                source_turn_id=profile_source_turn_id,
                conversation_version=(
                    transition.output.conversation_version
                ),
            ).profile
        elif profile_source_turn_id is not None:
            raise ValueError(
                "profile source provenance requires profile updates"
            )
        replacement = snapshot.model_copy(update=update, deep=True)
        return self._conversation_state.save(
            replacement,
            expected_version=transition.expected_conversation_version,
        )

    def _save_dynamic_result(
        self,
        snapshot: ConversationSnapshot | None,
        *,
        session_id: str,
        profile_owner: ProfileOwnerRef,
        dynamic: DynamicConsultationResult,
        source_turn_id: str,
    ) -> tuple[ConversationSnapshot, bool]:
        observations_changed = (
            snapshot is None
            or snapshot.consultation != dynamic.next_consultation
        )
        assessment_required = (
            dynamic.stop_skincare_advice
            or dynamic.ready_for_confirmation
        )
        if not observations_changed and not assessment_required:
            assert snapshot is not None
            return self._advance_read_only_snapshot(snapshot), False
        current_version = snapshot.version if snapshot is not None else 0
        next_version = current_version + 1
        consultation = (
            dynamic.next_consultation
            if observations_changed
            else snapshot.consultation
        )
        assert consultation is not None
        if assessment_required:
            conclusion = dynamic.conclusion
            assert conclusion is not None
            assessment = ConfirmableConsultationAssessment(
                assessment_kind=(
                    "medical_escalation"
                    if dynamic.stop_skincare_advice
                    else "provisional"
                ),
                observation_set_version=(
                    next_version
                    if observations_changed
                    else current_version
                ),
                observations=consultation.observations,
                conclusion=conclusion,
                conclusion_source_turn_id=source_turn_id,
                escalation_triggers=dynamic.escalation_triggers,
                stop_skincare_advice=(
                    dynamic.stop_skincare_advice
                ),
            )
            medical_escalation = (
                RecordedMedicalEscalation(
                    recorded_at_conversation_version=next_version,
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
                medical_escalation=medical_escalation,
            )
        if snapshot is None:
            replacement = ConversationSnapshot(
                session_id=session_id,
                version=next_version,
                profile_owner=profile_owner,
                consultation=consultation,
            )
            expected_version = 0
        else:
            replacement = snapshot.model_copy(
                update={
                    "version": next_version,
                    "consultation": consultation,
                },
                deep=True,
            )
            expected_version = snapshot.version
        return (
            self._conversation_state.save(
                replacement,
                expected_version=expected_version,
            ),
            observations_changed,
        )

    def _advance_read_only_snapshot(
        self,
        snapshot: ConversationSnapshot,
    ) -> ConversationSnapshot:
        replacement = snapshot.model_copy(
            update={"version": snapshot.version + 1},
            deep=True,
        )
        return self._conversation_state.save(
            replacement,
            expected_version=snapshot.version,
        )

    def _ensure_confirmed_session_profile(
        self,
        snapshot: ConversationSnapshot,
        *,
        conclusion: ProvisionalConsultationConclusion,
    ) -> ConversationSnapshot:
        if snapshot.session_profile is not None:
            return snapshot
        consultation = snapshot.consultation
        assert consultation is not None
        source_turn_id = consultation.confirmation_source_turn_id
        assert source_turn_id is not None
        profile = reduce_session_profile(
            previous=SessionProfile(),
            updates=self._profile_updates_for_conclusion(conclusion),
            subject_scope="self",
            source_turn_id=source_turn_id,
            conversation_version=snapshot.version + 1,
        ).profile
        replacement = snapshot.model_copy(
            update={
                "version": snapshot.version + 1,
                "session_profile": profile,
            },
            deep=True,
        )
        return self._conversation_state.save(
            replacement,
            expected_version=snapshot.version,
        )

    @staticmethod
    def _profile_updates_for_skin(
        skin_target: str,
    ) -> tuple[SessionProfileUpdate, ...]:
        if skin_target == "oily_sensitive":
            return (
                BaseSkinUpdate(
                    value="oily",
                    confirmation="confirmed",
                ),
                StableTendencyUpdate(
                    value="sensitivity",
                    confirmation="confirmed",
                ),
            )
        if skin_target == "sensitive":
            return (
                StableTendencyUpdate(
                    value="sensitivity",
                    confirmation="confirmed",
                ),
            )
        if skin_target not in {
            "oily",
            "dry",
            "combination",
            "normal",
        }:
            raise ValueError("unsupported consultation skin target")
        return (
            BaseSkinUpdate(
                value=skin_target,
                confirmation="confirmed",
            ),
        )

    @classmethod
    def _profile_updates_for_conclusion(
        cls,
        conclusion: ProvisionalConsultationConclusion,
    ) -> tuple[SessionProfileUpdate, ...]:
        skin_target = conclusion.skin_target
        if skin_target is None:
            raise ValueError(
                "confirmed consultation requires a base skin direction"
            )
        updates = list(cls._profile_updates_for_skin(skin_target))
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

    def _load_authority(
        self,
        *,
        session_id: str,
        conversation_version: int,
        profile_owner: ProfileOwnerRef,
    ) -> ConversationSnapshot | None:
        if type(profile_owner) is not ProfileOwnerRef:
            raise TypeError(
                "profile_owner must be an exact ProfileOwnerRef"
            )
        snapshot = self._conversation_state.load(session_id)
        authoritative_version = snapshot.version if snapshot else 0
        if (
            conversation_version != authoritative_version
            or (
                snapshot is not None
                and snapshot.profile_owner != profile_owner
            )
        ):
            raise ConversationStateConflict(session_id)
        return snapshot

    def _require_snapshot(
        self,
        session_id: str,
    ) -> ConversationSnapshot:
        snapshot = self._conversation_state.load(session_id)
        if snapshot is None:
            raise RuntimeError("authoritative conversation is missing")
        return snapshot

    @staticmethod
    def _next_question(
        consultation: ConsultationSubstate,
    ) -> ConsultationQuestion | None:
        from app.guide.intent.consultation_planning import (
            plan_consultation_collection,
        )

        return plan_consultation_collection(
            consultation.observations
        ).next_question

    @staticmethod
    def _collection_output(
        collected: ConsultationCollectionResult,
        *,
        intent: Literal[
            "consultation_entry",
            "consultation_answer",
        ],
    ) -> ConsultationApplicationResult:
        return ConsultationApplicationResult(
            intent=intent,
            conversation_version=collected.conversation_version,
            observations=tuple(collected.observations),
            next_question=collected.next_question,
            card_display_contract=(
                ConsultationApplicationCoordinator._zero_cards()
            ),
        )

    @staticmethod
    def _assessment_output(
        snapshot: ConversationSnapshot,
    ) -> ConsultationApplicationResult:
        consultation = snapshot.consultation
        assert consultation is not None
        medical = consultation.medical_escalation
        assessment = (
            medical.assessment
            if medical is not None
            else consultation.confirmable_assessment
        )
        assert assessment is not None
        is_medical = medical is not None or (
            assessment.assessment_kind == "medical_escalation"
        )
        return ConsultationApplicationResult(
            intent=(
                "consultation_medical_escalation"
                if is_medical
                else "consultation_provisional"
            ),
            conversation_version=snapshot.version,
            observations=consultation.observations,
            conclusion=assessment.conclusion,
            escalation_triggers=assessment.escalation_triggers,
            stop_skincare_advice=assessment.stop_skincare_advice,
            card_display_contract=(
                ConsultationApplicationCoordinator._zero_cards()
            ),
        )

    @staticmethod
    def _read_only_output(
        snapshot: ConversationSnapshot,
        *,
        intent: Literal[
            "consultation_clarification",
            "consultation_rejection",
        ],
        reason: ConsultationApplicationReason,
        next_question: ConsultationQuestion | None = None,
    ) -> ConsultationApplicationResult:
        consultation = snapshot.consultation
        assert consultation is not None
        return ConsultationApplicationResult(
            intent=intent,
            conversation_version=snapshot.version,
            observations=consultation.observations,
            next_question=next_question,
            reason=reason,
            card_display_contract=(
                ConsultationApplicationCoordinator._zero_cards()
            ),
        )

    @staticmethod
    def _confirmed_session_facts(
        snapshot: ConversationSnapshot | None,
    ) -> list[ConfirmedSessionFact]:
        if snapshot is None or snapshot.session_profile is None:
            return []
        profile = snapshot.session_profile
        facts: list[ConfirmedSessionFact] = []
        base_skin = profile.base_skin
        sensitivity = next(
            (
                item
                for item in profile.stable_tendencies
                if (
                    item.value == "sensitivity"
                    and item.confirmation == "confirmed"
                )
            ),
            None,
        )
        if (
            base_skin is not None
            and base_skin.confirmation == "confirmed"
            and base_skin.value != "unknown"
        ):
            value = (
                "oily_sensitive"
                if base_skin.value == "oily"
                and sensitivity is not None
                else base_skin.value
            )
            facts.append(ConfirmedSessionFact(
                field="skin_type",
                value=value,
                source_turn_id=base_skin.source_turn_id,
                source_kind="confirmed_consultation",
            ))
        elif sensitivity is not None:
            facts.append(ConfirmedSessionFact(
                field="skin_type",
                value="sensitive",
                source_turn_id=sensitivity.source_turn_id,
                source_kind="confirmed_consultation",
            ))
        facts.extend(
            ConfirmedSessionFact(
                field="ingredient_exclusion",
                value=item.value,
                source_turn_id=item.source_turn_id,
                source_kind="explicit_user",
            )
            for item in profile.explicit_restrictions[:1]
        )
        return facts

    @staticmethod
    def _require_confirmation_time(
        confirmed_at: datetime | None,
    ) -> None:
        if not isinstance(confirmed_at, datetime):
            raise ValueError(
                "confirmed_at is required for profile persistence"
            )
        if (
            confirmed_at.utcoffset() is None
            or confirmed_at.utcoffset() != UTC.utcoffset(confirmed_at)
        ):
            raise ValueError("confirmed_at must be UTC")

    @staticmethod
    def _zero_cards() -> CardDisplayContract:
        return CardDisplayContract(
            mode="none",
            visible_product_ids=[],
            max_cards=0,
            reason=None,
        )
