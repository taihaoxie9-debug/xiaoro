from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    KnowledgeSlotState,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.feedback.ports import (
    validate_conversation_state_transition,
)
from app.guide.intent.responsibility_matrix import Responsibility


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
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(slot="recommendation"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="sunscreen",
                recommendation_mode_basis="broad_exploration",
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
        ),
    )


def test_focus_survives_general_knowledge_switch_and_return() -> None:
    recommendation = _recommendation_snapshot()
    product = recommendation.model_copy(
        update={
            "version": 2,
            "active_owner": Responsibility.PRODUCT_KNOWLEDGE,
            "active_focus": ActiveFocus(
                slot="product",
                object_id=55,
            ),
            "recommendation_slot": (
                recommendation.recommendation_slot.model_copy(
                    update={"focused_candidate_ordinal": 2},
                    deep=True,
                )
            ),
            "product_slot": ProductSlotState(
                products=recommendation.recommendation_slot.candidates,
                focused_product_id=55,
            ),
        },
        deep=True,
    )
    knowledge = product.model_copy(
        update={
            "version": 3,
            "active_owner": Responsibility.GENERAL_KNOWLEDGE,
            "active_focus": ActiveFocus(slot="knowledge"),
            "knowledge_slot": KnowledgeSlotState(
                question="询问视黄醇是什么",
            ),
        },
        deep=True,
    )
    returned = knowledge.model_copy(
        update={
            "version": 4,
            "active_owner": Responsibility.PRODUCT_KNOWLEDGE,
            "active_focus": ActiveFocus(
                slot="product",
                object_id=55,
            ),
        },
        deep=True,
    )

    validate_conversation_state_transition(recommendation, product)
    validate_conversation_state_transition(product, knowledge)
    validate_conversation_state_transition(knowledge, returned)

    assert returned.active_focus is not None
    assert returned.active_focus.object_id == 55
    assert returned.product_slot is not None
    assert returned.product_slot.focused_product_id == 55
    assert returned.recommendation_slot is not None
    assert [
        item.product_id
        for item in returned.recommendation_slot.candidates
    ] == [
        51,
        55,
        101,
    ]
    assert returned.knowledge_slot is not None
    assert returned.knowledge_slot.question == "询问视黄醇是什么"


def test_confirmed_image_focus_round_trips_without_raw_candidates() -> None:
    snapshot = ConversationSnapshot(
        session_id="confirmed-image-focus",
        version=1,
        active_owner=Responsibility.IMAGE_IDENTITY,
        active_focus=ActiveFocus(
            slot="image",
            object_id=53,
            ordinal=1,
        ),
        image_slot=ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                    variant_scope=None,
                ),
            ),
            focused_image_ordinal=1,
        ),
    )

    payload = snapshot.model_dump(mode="json")
    restored = ConversationSnapshot.model_validate_json(
        snapshot.model_dump_json()
    )

    assert restored == snapshot
    assert payload["image_slot"]["confirmed_products"] == [
        {
            "image_ordinal": 1,
            "product_id": 53,
            "variant_scope": None,
        }
    ]
    assert "candidate_product_ids" not in snapshot.model_dump_json()


def test_current_product_can_be_an_independent_latest_product_slot() -> None:
    snapshot = ConversationSnapshot(
        session_id="independent-product-slot",
        version=1,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(
            slot="product",
            object_id=999,
        ),
        product_slot=ProductSlotState(
            products=(_candidate(999, 1),),
            focused_product_id=999,
        ),
    )

    assert snapshot.active_focus is not None
    assert snapshot.active_focus.object_id == 999
    assert snapshot.product_slot is not None
    assert snapshot.product_slot.focused_product_id == 999


def test_confirmed_image_ordinals_are_unique_and_bounded() -> None:
    with pytest.raises(ValidationError, match="ordinal"):
        ImageSlotState(
            confirmed_products=(
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
