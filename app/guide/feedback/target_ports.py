from __future__ import annotations

from typing import Protocol

from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.target_contracts import (
    TrustedFeedbackTarget,
)


class FeedbackTargetConflict(RuntimeError):
    pass


class FeedbackTargetStoreCorrupt(RuntimeError):
    pass


class FeedbackTargetRegistryPort(Protocol):
    def load(
        self,
        *,
        owner: ProfileOwnerRef,
        reference: ConversationVersionRef,
    ) -> TrustedFeedbackTarget | None: ...

    def record_once(
        self,
        target: TrustedFeedbackTarget,
    ) -> TrustedFeedbackTarget: ...
