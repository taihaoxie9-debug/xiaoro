from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.guide.feedback.event_contracts import (
    ClickFeedbackPayload,
    CompareFeedbackPayload,
    FavoriteFeedbackPayload,
    FeedbackActorContext,
    FeedbackEventRequest,
    FeedbackProfileVersionRef,
    NegativeFeedbackPayload,
    RecordedFeedbackEvent,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.contracts import ConversationVersionRef


def _owner(subject_id: str = "profile_0123456789abcdef") -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope="local_demo",
        subject_id=subject_id,
    )


def _request(
    payload: object,
    *,
    profile: FeedbackProfileVersionRef | None = None,
) -> FeedbackEventRequest:
    return FeedbackEventRequest(
        conversation=ConversationVersionRef(
            session_id="session-feedback-owner",
            conversation_version=7,
        ),
        profile=profile,
        idempotency_key="feedback-idempotency-key-0001",
        payload=payload,
    )


def _actor() -> FeedbackActorContext:
    return FeedbackActorContext(
        owner=_owner(),
        authorized_session_id="session-feedback-owner",
    )


@pytest.mark.parametrize(
    ("payload", "event_type"),
    [
        (ClickFeedbackPayload(product_id=11), "click"),
        (FavoriteFeedbackPayload(product_id=11), "favorite"),
        (CompareFeedbackPayload(product_ids=[11, 22]), "compare"),
        (
            NegativeFeedbackPayload(
                product_id=11,
                reason="not_relevant",
            ),
            "negative_feedback",
        ),
    ],
)
def test_feedback_requests_are_typed_and_round_trip_deterministically(
    payload: object,
    event_type: str,
) -> None:
    request = _request(payload)

    restored = FeedbackEventRequest.model_validate_json(
        request.model_dump_json()
    )

    assert restored == request
    assert restored.payload.event_type == event_type


@pytest.mark.parametrize(
    "product_ids",
    [
        [],
        [11],
        [11, 11],
        [11, 22, 33, 44, 55],
    ],
)
def test_compare_requires_two_to_four_unique_products(
    product_ids: list[int],
) -> None:
    with pytest.raises(ValidationError):
        CompareFeedbackPayload(product_ids=product_ids)


@pytest.mark.parametrize(
    "payload",
    [
        {"event_type": "click", "product_id": 0},
        {"event_type": "favorite", "product_id": -1},
        {
            "event_type": "negative_feedback",
            "product_id": 0,
            "reason": "not_relevant",
        },
        {
            "event_type": "negative_feedback",
            "product_id": 11,
            "reason": "invented_reason",
        },
    ],
)
def test_feedback_payloads_reject_invalid_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        FeedbackEventRequest.model_validate(
            {
                **_request(ClickFeedbackPayload(product_id=11)).model_dump(),
                "payload": payload,
            }
        )


def test_actor_context_rejects_malformed_ownership() -> None:
    with pytest.raises(ValidationError):
        ProfileOwnerRef(scope="local_demo", subject_id="short")

    with pytest.raises(ValidationError):
        FeedbackActorContext(
            owner=_owner(),
            authorized_session_id="",
        )


def test_request_rejects_all_client_supplied_owner_fields() -> None:
    request = _request(
        ClickFeedbackPayload(product_id=11),
        profile=FeedbackProfileVersionRef(profile_version=3),
    )

    with pytest.raises(ValidationError, match="Extra inputs"):
        FeedbackEventRequest.model_validate(
            {
                **request.model_dump(),
                "owner": _owner().model_dump(),
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        FeedbackEventRequest.model_validate(
            {
                **request.model_dump(),
                "profile": {
                    "profile_version": 3,
                    "owner": _owner().model_dump(),
                },
            }
        )


def test_profile_reference_may_be_omitted() -> None:
    payload = _request(ClickFeedbackPayload(product_id=11)).model_dump()
    del payload["profile"]

    request = FeedbackEventRequest.model_validate(payload)

    assert request.profile is None


@pytest.mark.parametrize(
    "idempotency_key",
    ["", "short", "contains whitespace", "x" * 161],
)
def test_idempotency_key_is_required_and_opaque(
    idempotency_key: str,
) -> None:
    payload = _request(ClickFeedbackPayload(product_id=11)).model_dump()
    payload["idempotency_key"] = idempotency_key

    with pytest.raises(ValidationError):
        FeedbackEventRequest.model_validate(payload)


def test_recorded_event_requires_a_utc_timestamp() -> None:
    request = _request(ClickFeedbackPayload(product_id=11))
    event = RecordedFeedbackEvent(
        **request.model_dump(),
        owner=_actor().owner,
        event_id="feedback_event_0123456789abcdef",
        occurred_at=datetime(2026, 8, 9, 4, 0, tzinfo=UTC),
    )

    assert event.owner == _actor().owner
    assert event.occurred_at.tzinfo is UTC
    assert event.to_request() == request
    assert "owner" not in event.to_request().model_dump()

    for invalid_time in (
        datetime(2026, 8, 9, 4, 0),
        datetime(
            2026,
            8,
            9,
            12,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    ):
        with pytest.raises(ValidationError, match="UTC"):
            RecordedFeedbackEvent(
                **request.model_dump(),
                owner=_actor().owner,
                event_id="feedback_event_0123456789abcdef",
                occurred_at=invalid_time,
            )


def test_feedback_contracts_are_strict_and_forbid_unknown_fields() -> None:
    request = _request(ClickFeedbackPayload(product_id=11))

    with pytest.raises(ValidationError):
        FeedbackEventRequest.model_validate(
            {
                **request.model_dump(),
                "conversation": {
                    "session_id": "session-feedback-owner",
                    "conversation_version": "7",
                },
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        FeedbackEventRequest.model_validate(
            {
                **request.model_dump(),
                "recommendation_score": 0.9,
            }
        )
