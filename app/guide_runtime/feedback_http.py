from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import secrets

from fastapi import Request, Response

from app.guide.feedback.event_contracts import FeedbackActorContext
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.session_contract import SessionId


FEEDBACK_SESSION_COOKIE = "xiaoro_feedback_session"
_FEEDBACK_SESSION_PATTERN = re.compile(
    r"^feedback_session_[A-Za-z0-9_-]{43,96}$"
)
_DIRECT_SESSION_TOKEN = (
    "feedback_session_direct_test_boundary_"
    "0123456789abcdefghijklmnop"
)


@dataclass(frozen=True)
class FeedbackActorSession:
    actor: FeedbackActorContext
    cookie_to_set: str | None


def resolve_feedback_actor_session(
    request: Request | None,
    *,
    authorized_session_id: SessionId,
    current_user_id: int | None = None,
) -> FeedbackActorSession:
    if (
        isinstance(current_user_id, int)
        and not isinstance(current_user_id, bool)
        and current_user_id > 0
    ):
        return FeedbackActorSession(
            actor=FeedbackActorContext(
                owner=ProfileOwnerRef(
                    scope="authenticated_user",
                    subject_id=(
                        f"authenticated-user-{current_user_id:016d}"
                    ),
                ),
                authorized_session_id=authorized_session_id,
            ),
            cookie_to_set=None,
        )

    supplied = (
        request.cookies.get(FEEDBACK_SESSION_COOKIE)
        if request is not None
        else _DIRECT_SESSION_TOKEN
    )
    cookie_to_set = None
    if (
        not isinstance(supplied, str)
        or _FEEDBACK_SESSION_PATTERN.fullmatch(supplied) is None
    ):
        supplied = f"feedback_session_{secrets.token_urlsafe(32)}"
        cookie_to_set = supplied
    subject_id = (
        "feedback-browser-"
        + hashlib.sha256(supplied.encode("utf-8")).hexdigest()
    )
    return FeedbackActorSession(
        actor=FeedbackActorContext(
            owner=ProfileOwnerRef(
                scope="local_demo",
                subject_id=subject_id,
            ),
            authorized_session_id=authorized_session_id,
        ),
        cookie_to_set=cookie_to_set,
    )


def set_feedback_session_cookie(
    response: Response,
    actor_session: FeedbackActorSession,
    *,
    secure: bool,
) -> None:
    if actor_session.cookie_to_set is None:
        return
    response.set_cookie(
        key=FEEDBACK_SESSION_COOKIE,
        value=actor_session.cookie_to_set,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
