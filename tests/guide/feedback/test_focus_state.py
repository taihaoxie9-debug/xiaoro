from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.feedback.focus_state import (
    ConfirmedImageProductRef,
    FocusState,
)
from app.guide.feedback.ports import (
    validate_conversation_state_transition,
)


def _candidate(product_id: int, ordinal: int) -> DisplayedCandidateRef:
    return DisplayedCandidateRef(
        product_id=product_id,
        ordinal=ordinal,
        skin_match="unknown",
        matched_efficacies=(),
    )


def _recommendation_snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="focus-sequence",
        version=1,
        query_context=RecommendationQueryContext(
            category="sunscreen",
            budget_minimum=None,
            budget_maximum=Decimal("500"),
            skin=None,
            efficacy=None,
            exclusions=(),
        ),
        candidates=(
            _candidate(51, 1),
            _candidate(55, 2),
            _candidate(101, 3),
        ),
        focus_state=FocusState(
            active_processor="recommendation",
        ),
    )


def test_focus_survives_general_knowledge_switch_and_return() -> None:
    recommendation = _recommendation_snapshot()
    product = recommendation.model_copy(
        update={
            "version": 2,
            "focused_candidate_ordinal": 2,
            "focus_state": FocusState(
                active_processor="product_knowledge",
                current_product_id=55,
                last_question_meaning="询问第二款质地",
            ),
        },
        deep=True,
    )
    knowledge = product.model_copy(
        update={
            "version": 3,
            "focus_state": product.focus_state.model_copy(
                update={
                    "active_processor": "general_knowledge",
                    "current_knowledge_topic": "视黄醇",
                    "last_question_meaning": "询问视黄醇是什么",
                },
                deep=True,
            ),
        },
        deep=True,
    )
    returned = knowledge.model_copy(
        update={
            "version": 4,
            "focus_state": knowledge.focus_state.model_copy(
                update={
                    "active_processor": "product_knowledge",
                    "last_question_meaning": "回到之前第二款",
                },
                deep=True,
            ),
        },
        deep=True,
    )

    validate_conversation_state_transition(recommendation, product)
    validate_conversation_state_transition(product, knowledge)
    validate_conversation_state_transition(knowledge, returned)

    assert returned.focus_state.current_product_id == 55
    assert [item.product_id for item in returned.candidates] == [
        51,
        55,
        101,
    ]
    assert returned.focus_state.current_knowledge_topic == "视黄醇"


def test_confirmed_image_focus_round_trips_without_raw_candidates() -> None:
    snapshot = ConversationSnapshot(
        session_id="confirmed-image-focus",
        version=1,
        has_image_delivery=True,
        focus_state=FocusState(
            active_processor="image_identity",
            current_product_id=53,
            confirmed_image_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                    variant_scope=None,
                ),
            ),
        ),
    )

    payload = snapshot.model_dump(mode="json")
    restored = ConversationSnapshot.model_validate(payload)

    assert restored == snapshot
    assert payload["focus_state"]["confirmed_image_products"] == [
        {
            "image_ordinal": 1,
            "product_id": 53,
            "variant_scope": None,
        }
    ]
    assert "candidate_product_ids" not in snapshot.model_dump_json()


def test_current_product_must_belong_to_batch_or_confirmed_image() -> None:
    with pytest.raises(ValidationError, match="current product"):
        ConversationSnapshot(
            session_id="invalid-focus-product",
            version=1,
            has_image_delivery=True,
            focus_state=FocusState(
                active_processor="product_knowledge",
                current_product_id=999,
            ),
        )


def test_confirmed_image_ordinals_are_unique_and_bounded() -> None:
    with pytest.raises(ValidationError, match="ordinal"):
        FocusState(
            active_processor="image_identity",
            confirmed_image_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=55,
                ),
            ),
        )
    with pytest.raises(ValidationError):
        ConfirmedImageProductRef(
            image_ordinal=5,
            product_id=53,
        )
