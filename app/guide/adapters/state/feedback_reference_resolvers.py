"""Synchronous feedback authority adapters for threadpool composition."""

from __future__ import annotations

from app.guide.adapters.state.sqlite_profile_state import (
    SqliteProfileState,
)
from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.event_contracts import (
    FeedbackActorContext,
    FeedbackConversationContext,
    FeedbackProfileVersionRef,
)
from app.guide.feedback.profile_state import ProfileStateCorrupt
from app.guide.feedback.target_ports import (
    FeedbackTargetRegistryPort,
)


class RegisteredFeedbackConversationReferenceResolver:
    """Resolve only durable targets owned by the trusted actor."""

    def __init__(
        self,
        targets: FeedbackTargetRegistryPort,
    ) -> None:
        self._targets = targets

    def load(
        self,
        *,
        actor: FeedbackActorContext,
        reference: ConversationVersionRef,
    ) -> FeedbackConversationContext | None:
        if actor.authorized_session_id != reference.session_id:
            return None
        target = self._targets.load(
            owner=actor.owner,
            reference=reference,
        )
        if (
            target is None
            or target.owner != actor.owner
            or target.conversation != reference
        ):
            return None
        return FeedbackConversationContext(
            reference=target.conversation.model_copy(deep=True),
            owner=target.owner.model_copy(deep=True),
            product_ids=list(target.displayed_product_ids),
            profile=(
                target.profile.model_copy(deep=True)
                if target.profile is not None
                else None
            ),
        )


class SqliteProfileFeedbackReferenceResolver:
    """Resolve an actor's exact current durable profile version."""

    def __init__(self, profile_state: SqliteProfileState) -> None:
        if not isinstance(profile_state, SqliteProfileState):
            raise TypeError(
                "profile_state must be a SqliteProfileState"
            )
        self._profile_state = profile_state

    def exists(
        self,
        *,
        actor: FeedbackActorContext,
        reference: FeedbackProfileVersionRef,
    ) -> bool:
        try:
            snapshot = self._profile_state.load(actor.owner)
        except (ProfileStateCorrupt, OSError, ValueError):
            return False
        return (
            snapshot is not None
            and snapshot.owner == actor.owner
            and snapshot.version == reference.profile_version
        )


class UnavailableFeedbackProfileReferenceResolver:
    """Explicit fail-closed adapter for compositions without profile state."""

    def exists(
        self,
        *,
        actor: FeedbackActorContext,
        reference: FeedbackProfileVersionRef,
    ) -> bool:
        del actor, reference
        return False
