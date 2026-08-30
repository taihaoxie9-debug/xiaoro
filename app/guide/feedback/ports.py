from contextlib import AbstractContextManager
from enum import Enum
from typing import Protocol

from app.guide.application.contracts import UserTurn
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    PendingClarificationSlot,
    PendingReplySlot,
    PendingTurn,
)
from app.guide.feedback.consultation_state import (
    ConfirmableConsultationAssessment,
    ConsultationSubstate,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef


class FeedbackWriteStatus(str, Enum):
    SKIPPED_SLICE_SCOPE = "SKIPPED_SLICE_SCOPE"


class FeedbackPort(Protocol):
    def record_turn(self, turn: UserTurn) -> FeedbackWriteStatus: ...


class Slice1DisabledFeedback:
    def record_turn(self, turn: UserTurn) -> FeedbackWriteStatus:
        return FeedbackWriteStatus.SKIPPED_SLICE_SCOPE


class ConversationStateConflict(RuntimeError):
    pass


class ConversationStateCorrupt(RuntimeError):
    pass


def validate_conversation_state_transition(
    current: ConversationSnapshot | None,
    replacement: ConversationSnapshot,
) -> None:
    _validate_clarification_transition(
        _clarification(current),
        _clarification(replacement),
    )
    _validate_pending_turn_transition(
        _pending_turn(current),
        _pending_turn(replacement),
    )
    previous = (
        current.consultation_slot.state
        if current is not None
        and current.consultation_slot is not None
        else None
    )
    _validate_consultation_transition(
        previous,
        (
            replacement.consultation_slot.state
            if replacement.consultation_slot is not None
            else None
        ),
        replacement_version=replacement.version,
    )


def _clarification(
    snapshot: ConversationSnapshot | None,
) -> ClarificationProgress | None:
    if (
        snapshot is None
        or not isinstance(
            snapshot.reply_slot,
            PendingClarificationSlot,
        )
    ):
        return None
    return snapshot.reply_slot.value


def _pending_turn(
    snapshot: ConversationSnapshot | None,
) -> PendingTurn | None:
    if (
        snapshot is None
        or not isinstance(snapshot.reply_slot, PendingReplySlot)
    ):
        return None
    return snapshot.reply_slot.value


def _validate_clarification_transition(
    previous: ClarificationProgress | None,
    replacement: ClarificationProgress | None,
) -> None:
    if replacement is None:
        return
    if previous is None:
        if replacement.attempts != 1:
            raise ValueError("clarification must start at attempt one")
        return
    if replacement.gap is previous.gap:
        if replacement.attempts not in {
            previous.attempts,
            min(previous.attempts + 1, 2),
        }:
            raise ValueError(
                "clarification attempts must advance monotonically"
            )
        return
    if replacement.attempts != 1:
        raise ValueError(
            "a new clarification gap must start at attempt one"
        )


def _validate_pending_turn_transition(
    previous: PendingTurn | None,
    replacement: PendingTurn | None,
) -> None:
    if replacement is None:
        return
    if previous is None:
        if replacement.attempts != 1:
            raise ValueError("pending turn must start at attempt one")
        return
    mutable_fields = {
        "attempts",
        "expected_response",
        "proposed_budget",
    }
    previous_source = previous.model_dump(exclude=mutable_fields)
    replacement_source = replacement.model_dump(exclude=mutable_fields)
    if replacement_source != previous_source:
        if replacement.attempts != 1:
            raise ValueError(
                "pending turn source data is immutable"
            )
        if (
            replacement.source_conversation_version
            <= previous.source_conversation_version
        ):
            raise ValueError(
                "replacement pending source data must come from a newer turn"
            )
        return
    if replacement.attempts not in {
        previous.attempts,
        min(previous.attempts + 1, 2),
    }:
        raise ValueError(
            "pending turn attempts must advance monotonically"
        )


def _validate_consultation_transition(
    previous: ConsultationSubstate | None,
    replacement: ConsultationSubstate | None,
    *,
    replacement_version: int,
) -> None:
    if previous is None:
        if replacement is None:
            return
        if (
            replacement.started_at_conversation_version
            != replacement_version
        ):
            raise ValueError(
                "consultation start marker must match activation version"
            )
        if (
            replacement.confirmable_assessment is not None
            or replacement.medical_escalation is not None
        ):
            _validate_atomic_dynamic_assessment(
                replacement,
                replacement_version=replacement_version,
            )
        elif replacement.confirmation_source_turn_id is not None:
            raise ValueError(
                "consultation entry cannot include a confirmation"
            )
        return

    if replacement is None:
        raise ValueError(
            "existing consultation observations must remain an "
            "immutable prefix"
        )
    if (
        replacement.started_at_conversation_version
        != previous.started_at_conversation_version
    ):
        raise ValueError("consultation start marker is immutable")
    _validate_dynamic_consultation_transition(
        previous,
        replacement,
        replacement_version=replacement_version,
    )


def _validate_dynamic_consultation_transition(
    previous: ConsultationSubstate,
    replacement: ConsultationSubstate,
    *,
    replacement_version: int,
) -> None:
    previous_by_dimension = {
        item.dimension: item
        for item in previous.observations
    }
    replacement_by_dimension = {
        item.dimension: item
        for item in replacement.observations
    }
    changed = False
    for dimension, prior in previous_by_dimension.items():
        current = replacement_by_dimension.get(dimension)
        if current is None:
            raise ValueError(
                "dynamic consultation observation was removed "
                "without replacement"
            )
        if current == prior:
            continue
        if current.source_turn_id == prior.source_turn_id:
            raise ValueError(
                "dynamic correction requires new source provenance"
            )
        changed = True
    if set(replacement_by_dimension) - set(previous_by_dimension):
        changed = True

    if not changed:
        _validate_medical_escalation_transition(
            previous,
            replacement,
            replacement_version=replacement_version,
        )
        _validate_assessment_transition(previous, replacement)
        return

    if previous.medical_escalation is not None:
        raise ValueError("medical escalation is immutable")
    previous_assessment = previous.confirmable_assessment
    if (
        previous_assessment is not None
        and previous_assessment.conclusion.confirmed_by_user
    ):
        raise ValueError(
            "consultation confirmation is immutable once recorded"
        )
    if (
        replacement.confirmable_assessment is not None
        or replacement.medical_escalation is not None
    ):
        _validate_atomic_dynamic_assessment(
            replacement,
            replacement_version=replacement_version,
        )
    elif replacement.confirmation_source_turn_id is not None:
        raise ValueError(
            "dynamic observations cannot be confirmed in the same "
            "transition"
        )


def _validate_atomic_dynamic_assessment(
    replacement: ConsultationSubstate,
    *,
    replacement_version: int,
) -> None:
    assessment = replacement.confirmable_assessment
    if (
        assessment is None
        or assessment.observation_set_version != replacement_version
        or assessment.observations != replacement.observations
        or replacement.confirmation_source_turn_id is not None
    ):
        raise ValueError(
            "atomic dynamic assessment must bind the transition "
            "observations and version"
        )
    medical = replacement.medical_escalation
    if assessment.assessment_kind == "medical_escalation":
        if (
            medical is None
            or medical.assessment != assessment
            or medical.recorded_at_conversation_version
            != replacement_version
        ):
            raise ValueError(
                "atomic dynamic medical assessment requires a matching "
                "transition marker"
            )
    elif medical is not None:
        raise ValueError(
            "provisional dynamic assessment cannot record a medical "
            "escalation"
        )


def _validate_medical_escalation_transition(
    previous: ConsultationSubstate,
    replacement: ConsultationSubstate,
    *,
    replacement_version: int,
) -> None:
    previous_escalation = previous.medical_escalation
    replacement_escalation = replacement.medical_escalation
    if (
        replacement_escalation is not None
        and replacement.confirmation_source_turn_id is not None
    ):
        raise ValueError(
            "consultation confirmation and medical escalation "
            "are mutually exclusive"
        )
    if previous_escalation is not None:
        if replacement_escalation != previous_escalation:
            raise ValueError("medical escalation is immutable")
        return
    if replacement_escalation is None:
        return
    if (
        replacement_escalation.recorded_at_conversation_version
        != replacement_version
    ):
        raise ValueError(
            "medical escalation marker must match transition version"
        )


def _validate_assessment_transition(
    previous: ConsultationSubstate,
    replacement: ConsultationSubstate,
) -> None:
    previous_assessment = previous.confirmable_assessment
    replacement_assessment = replacement.confirmable_assessment
    if previous_assessment is None:
        if replacement_assessment is None:
            if replacement.confirmation_source_turn_id is not None:
                raise ValueError(
                    "consultation confirmation requires a provisional "
                    "assessment"
                )
            return
        if (
            replacement_assessment.conclusion.confirmed_by_user
            or replacement.confirmation_source_turn_id is not None
        ):
            raise ValueError(
                "consultation confirmation requires a provisional "
                "assessment"
            )
        return

    if previous_assessment.conclusion.confirmed_by_user:
        if (
            replacement_assessment != previous_assessment
            or replacement.confirmation_source_turn_id
            != previous.confirmation_source_turn_id
        ):
            raise ValueError(
                "consultation confirmation is immutable once recorded"
            )
        return

    if (
        replacement_assessment == previous_assessment
        and replacement.confirmation_source_turn_id
        == previous.confirmation_source_turn_id
    ):
        return
    if replacement_assessment is None:
        raise ValueError(
            "consultation assessment is immutable once recorded"
        )
    if not _is_confirmation_transition(
        previous_assessment,
        replacement_assessment,
        replacement.confirmation_source_turn_id,
    ):
        raise ValueError(
            "consultation assessment is immutable once recorded"
        )


def _is_confirmation_transition(
    previous: ConfirmableConsultationAssessment,
    replacement: ConfirmableConsultationAssessment,
    confirmation_source_turn_id: str | None,
) -> bool:
    if confirmation_source_turn_id is None:
        return False
    expected_conclusion = previous.conclusion.model_copy(
        update={"confirmed_by_user": True}
    )
    expected_assessment = previous.model_copy(
        update={"conclusion": expected_conclusion},
        deep=True,
    )
    return replacement == expected_assessment


class ConversationStatePort(Protocol):
    def load(self, session_id: str) -> ConversationSnapshot | None: ...

    def save(
        self,
        snapshot: ConversationSnapshot,
        *,
        expected_version: int,
    ) -> ConversationSnapshot: ...

    def delete(
        self,
        session_id: str,
        *,
        expected_owner: ProfileOwnerRef | None,
    ) -> bool: ...


class SessionLockPort(Protocol):
    def hold(
        self,
        session_id: str,
    ) -> AbstractContextManager[None]: ...
