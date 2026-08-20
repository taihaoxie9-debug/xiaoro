from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.event_contracts import (
    ClickFeedbackPayload,
    FeedbackEventRequest,
    FeedbackProfileVersionRef,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.target_contracts import (
    TrustedFeedbackTarget,
    feedback_target_from_completed_response,
)
from app.guide.presentation.contracts import CardDisplayContract


def _owner() -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope="authenticated_user",
        subject_id="authenticated-user-0123456789",
    )


def _conversation() -> ConversationVersionRef:
    return ConversationVersionRef(
        session_id="session-feedback-target",
        conversation_version=9,
    )


def _display(
    product_ids: list[int],
    *,
    mode: str,
) -> CardDisplayContract:
    return CardDisplayContract(
        mode=mode,
        visible_product_ids=product_ids,
        max_cards=len(product_ids),
        reason=(
            None
            if mode == "none"
            else "product"
            if mode == "single"
            else "recommendation"
            if mode == "recommendation"
            else "comparison"
        ),
    )


@pytest.mark.parametrize(
    ("product_ids", "mode"),
    [
        ([11], "single"),
        ([11, 22], "recommendation"),
        ([11, 22, 33], "recommendation"),
        ([11, 22, 33], "comparison"),
    ],
)
def test_completion_mapper_preserves_exact_display_order(
    product_ids: list[int],
    mode: str,
) -> None:
    profile = FeedbackProfileVersionRef(profile_version=3)

    target = feedback_target_from_completed_response(
        owner=_owner(),
        conversation=_conversation(),
        card_display=_display(product_ids, mode=mode),
        profile=profile,
    )

    assert target == TrustedFeedbackTarget(
        owner=_owner(),
        conversation=_conversation(),
        displayed_product_ids=tuple(product_ids),
        profile=profile,
    )
    assert isinstance(target.displayed_product_ids, tuple)


def test_zero_card_completion_is_not_feedback_capable() -> None:
    target = feedback_target_from_completed_response(
        owner=_owner(),
        conversation=_conversation(),
        card_display=_display([], mode="none"),
    )

    assert target is None


def test_completed_single_display_cannot_authorize_product_99() -> None:
    display = _display([11], mode="single")
    before = display.model_dump(mode="json")

    for field, replacement in (
        ("mode", "comparison"),
        ("visible_product_ids", (99, 11)),
        ("max_cards", 2),
        ("reason", "comparison"),
    ):
        with pytest.raises(ValidationError, match="frozen"):
            setattr(display, field, replacement)

    target = feedback_target_from_completed_response(
        owner=_owner(),
        conversation=_conversation(),
        card_display=display,
    )

    assert display.model_dump(mode="json") == before
    assert target is not None
    assert target.displayed_product_ids == (11,)
    assert 99 not in target.displayed_product_ids


def test_completion_mapper_defensively_revalidates_card_display() -> None:
    invalid_display = CardDisplayContract.model_construct(
        mode="comparison",
        visible_product_ids=(99, 11),
        max_cards=1,
        reason="comparison",
    )

    with pytest.raises(ValidationError):
        feedback_target_from_completed_response(
            owner=_owner(),
            conversation=_conversation(),
            card_display=invalid_display,
        )


@pytest.mark.parametrize(
    "product_ids",
    [
        (),
        (0,),
        (-1,),
        (11, 11),
        (11, 22, 33, 44, 55),
    ],
)
def test_trusted_target_rejects_non_feedback_capable_products(
    product_ids: tuple[int, ...],
) -> None:
    with pytest.raises(ValidationError):
        TrustedFeedbackTarget(
            owner=_owner(),
            conversation=_conversation(),
            displayed_product_ids=product_ids,
        )


def test_trusted_target_is_strict_frozen_and_detached_from_display() -> None:
    visible_ids = [11, 22]
    display = _display(visible_ids, mode="recommendation")
    target = feedback_target_from_completed_response(
        owner=_owner(),
        conversation=_conversation(),
        card_display=display,
    )
    assert target is not None

    visible_ids.reverse()

    assert target.displayed_product_ids == (11, 22)
    assert display.visible_product_ids == (11, 22)
    with pytest.raises(ValidationError):
        target.displayed_product_ids = (22, 11)
    with pytest.raises(ValidationError, match="Extra inputs"):
        TrustedFeedbackTarget.model_validate(
            {
                **target.model_dump(),
                "request_owner": _owner().model_dump(),
            }
        )


@pytest.mark.parametrize(
    ("authority", "field", "replacement"),
    [
        (
            "owner",
            "subject_id",
            "authenticated-user-fedcba9876543210",
        ),
        ("conversation", "session_id", "session-feedback-mutated"),
        ("conversation", "conversation_version", 10),
        ("profile", "profile_version", 4),
    ],
)
def test_trusted_target_authority_is_deeply_immutable(
    authority: str,
    field: str,
    replacement: object,
) -> None:
    target = TrustedFeedbackTarget(
        owner=_owner(),
        conversation=_conversation(),
        displayed_product_ids=(11,),
        profile=FeedbackProfileVersionRef(profile_version=3),
    )
    before = target.model_dump(mode="json")
    nested = getattr(target, authority)
    assert nested is not None

    with pytest.raises(ValidationError, match="frozen"):
        setattr(nested, field, replacement)

    assert target.model_dump(mode="json") == before
    assert isinstance(target.conversation, ConversationVersionRef)
    assert isinstance(target.profile, FeedbackProfileVersionRef)


def test_feedback_request_cannot_supply_target_authority() -> None:
    request = FeedbackEventRequest(
        conversation=_conversation(),
        idempotency_key="feedback-idempotency-key-target-0001",
        payload=ClickFeedbackPayload(product_id=11),
    )

    for authority in (
        {"owner": _owner().model_dump()},
        {"displayed_product_ids": [11]},
        {
            "target": TrustedFeedbackTarget(
                owner=_owner(),
                conversation=_conversation(),
                displayed_product_ids=(11,),
            ).model_dump()
        },
    ):
        with pytest.raises(ValidationError, match="Extra inputs"):
            FeedbackEventRequest.model_validate(
                {
                    **request.model_dump(),
                    **authority,
                }
            )
