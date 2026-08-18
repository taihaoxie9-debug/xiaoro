from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.consultation_state import (
    ConsultationSubstate,
)
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStatePort,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.intent.consultation_planning import (
    ConsultationCollectionPlan,
    plan_consultation_collection,
    plan_unknown_skin_consultation,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)
from app.guide.understanding.consultation_questions import (
    ConsultationQuestion,
    ObservationAnswer,
)
from app.guide.understanding.contracts import SkinTarget


class ConsultationCollectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    mode: Literal["consultation_collection"] = "consultation_collection"
    conversation_version: int = Field(ge=0)
    observations: list[ConsultationObservation] = Field(max_length=5)
    next_question: ConsultationQuestion | None
    visible_product_ids: list[int] = Field(
        default_factory=list,
        max_length=0,
    )


class ConsultationCollectionComplete(RuntimeError):
    pass


class ConsultationNotActive(RuntimeError):
    pass


class ConsultationCollectionService:
    def __init__(
        self,
        *,
        conversation_state: ConversationStatePort,
    ) -> None:
        self._conversation_state = conversation_state

    def begin(
        self,
        *,
        session_id: str,
        conversation_version: int,
        skin_target: SkinTarget | None,
        profile_owner: ProfileOwnerRef | None = None,
    ) -> ConsultationCollectionResult | None:
        snapshot = self._conversation_state.load(session_id)
        _validate_profile_owner(
            snapshot,
            profile_owner=profile_owner,
            session_id=session_id,
        )
        authoritative_version = _snapshot_version(snapshot)
        if conversation_version != authoritative_version:
            raise ConversationStateConflict(session_id)
        observations = _snapshot_observations(snapshot)
        plan = (
            ConsultationCollectionPlan(next_question=None)
            if _has_assessment(snapshot)
            else plan_unknown_skin_consultation(
                skin_target=skin_target,
                observations=observations,
            )
        )
        if plan is None:
            return None
        if snapshot is None or snapshot.consultation is None:
            active = ConsultationSubstate(
                started_at_conversation_version=(
                    authoritative_version + 1
                ),
                observations=[],
            )
            replacement = _replace_consultation(
                snapshot,
                session_id=session_id,
                version=authoritative_version + 1,
                consultation=active,
                profile_owner=profile_owner,
            )
            snapshot = self._conversation_state.save(
                replacement,
                expected_version=authoritative_version,
            )
            authoritative_version = snapshot.version
            observations = _snapshot_observations(snapshot)
            plan = plan_consultation_collection(observations)
        return _collection_result(
            plan,
            conversation_version=authoritative_version,
            observations=observations,
        )

    def answer(
        self,
        *,
        session_id: str,
        conversation_version: int,
        answer: ObservationAnswer,
        source_turn_id: str,
        profile_owner: ProfileOwnerRef | None = None,
    ) -> ConsultationCollectionResult:
        snapshot = self._conversation_state.load(session_id)
        _validate_profile_owner(
            snapshot,
            profile_owner=profile_owner,
            session_id=session_id,
        )
        authoritative_version = _snapshot_version(snapshot)
        if conversation_version != authoritative_version:
            raise ConversationStateConflict(session_id)
        if snapshot is None or snapshot.consultation is None:
            raise ConsultationNotActive(session_id)
        if _has_assessment(snapshot):
            raise ConsultationCollectionComplete(session_id)
        observations = _snapshot_observations(snapshot)
        plan = plan_consultation_collection(observations)
        if plan.next_question is None:
            raise ConsultationCollectionComplete(session_id)
        observation = ConsultationObservation(
            code=plan.next_question.code,
            answer=answer,
            source_turn_id=source_turn_id,
        )
        next_consultation = ConsultationSubstate(
            started_at_conversation_version=(
                snapshot.consultation.started_at_conversation_version
            ),
            observations=(*observations, observation),
        )
        replacement = _replace_consultation(
            snapshot,
            session_id=session_id,
            version=authoritative_version + 1,
            consultation=next_consultation,
            profile_owner=profile_owner,
        )
        saved = self._conversation_state.save(
            replacement,
            expected_version=authoritative_version,
        )
        saved_consultation = saved.consultation
        if saved_consultation is None:
            raise RuntimeError("saved consultation state is missing")
        saved_observations = saved_consultation.observations
        next_plan = plan_consultation_collection(saved_observations)
        return _collection_result(
            next_plan,
            conversation_version=saved.version,
            observations=saved_observations,
        )


def _snapshot_version(snapshot: ConversationSnapshot | None) -> int:
    return snapshot.version if snapshot is not None else 0


def _validate_profile_owner(
    snapshot: ConversationSnapshot | None,
    *,
    profile_owner: ProfileOwnerRef | None,
    session_id: str,
) -> None:
    if profile_owner is not None and not isinstance(
        profile_owner,
        ProfileOwnerRef,
    ):
        raise TypeError("profile_owner must be a ProfileOwnerRef")
    if (
        snapshot is not None
        and snapshot.profile_owner != profile_owner
    ):
        raise ConversationStateConflict(session_id)


def _has_assessment(snapshot: ConversationSnapshot | None) -> bool:
    return (
        snapshot is not None
        and snapshot.consultation is not None
        and snapshot.consultation.confirmable_assessment is not None
    )


def _snapshot_observations(
    snapshot: ConversationSnapshot | None,
) -> tuple[ConsultationObservation, ...]:
    if snapshot is None or snapshot.consultation is None:
        return ()
    return tuple(
        item.model_copy(deep=True)
        for item in snapshot.consultation.observations
    )


def _replace_consultation(
    snapshot: ConversationSnapshot | None,
    *,
    session_id: str,
    version: int,
    consultation: ConsultationSubstate,
    profile_owner: ProfileOwnerRef | None,
) -> ConversationSnapshot:
    if snapshot is None:
        return ConversationSnapshot(
            session_id=session_id,
            version=version,
            profile_owner=profile_owner,
            query_context=None,
            candidates=[],
            consultation=consultation,
        )
    return snapshot.model_copy(
        update={
            "version": version,
            "consultation": consultation,
        },
        deep=True,
    )


def _collection_result(
    plan: ConsultationCollectionPlan,
    *,
    conversation_version: int,
    observations: tuple[ConsultationObservation, ...],
) -> ConsultationCollectionResult:
    return ConsultationCollectionResult(
        conversation_version=conversation_version,
        observations=[
            item.model_copy(deep=True)
            for item in observations
        ],
        next_question=plan.next_question,
    )
