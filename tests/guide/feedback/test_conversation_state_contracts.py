from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConsultationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    KnowledgeSlotState,
    PendingClarificationSlot,
    PendingRecommendationContext,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
    migrate_legacy_conversation_snapshot_payload,
)
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.understanding.semantic_contracts import ClarificationCode


def _candidate(product_id: int, ordinal: int) -> DisplayedCandidateRef:
    return DisplayedCandidateRef(
        product_id=product_id,
        ordinal=ordinal,
        skin_match="unknown",
        matched_efficacies=(),
    )


def _query() -> RecommendationQueryContext:
    return RecommendationQueryContext(
        category="serum",
        recommendation_mode="explore",
        recommendation_mode_basis="broad_exploration",
        recommendation_count=2,
        budget_minimum=Decimal("100"),
        budget_maximum=Decimal("500"),
    )


def _snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="six-slot-contract",
        version=1,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(
            slot="recommendation",
            ordinal=1,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=_query(),
            candidates=(_candidate(91, 1), _candidate(38, 2)),
            focused_candidate_ordinal=1,
        ),
        product_slot=ProductSlotState(
            products=(_candidate(51, 1), _candidate(57, 2)),
            focused_product_id=None,
            focused_evidence_ids=("a" * 64,),
        ),
        image_slot=ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
            ),
            focused_image_ordinal=1,
        ),
        consultation_slot=ConsultationSlotState(
            state=ConsultationSubstate(
                started_at_conversation_version=1,
            ),
        ),
        knowledge_slot=KnowledgeSlotState(
            question="防晒为什么需要补涂",
            evidence_ids=("b" * 64,),
        ),
        reply_slot=PendingClarificationSlot(
            value=ClarificationProgress(
                gap=ClarificationCode.BUDGET,
                attempts=1,
            )
        ),
    )


def test_recommendation_context_requires_parent_scoped_basis() -> None:
    with pytest.raises(ValidationError, match="parent-scoped"):
        RecommendationQueryContext(
            category="serum",
            recommendation_mode="fit",
            recommendation_mode_basis="broad_exploration",
            recommendation_count=1,
        )


def test_pending_recommendation_context_requires_parent_scoped_basis() -> None:
    with pytest.raises(ValidationError, match="parent-scoped"):
        PendingRecommendationContext(
            category="serum",
            recommendation_mode="explore",
            recommendation_mode_basis="personal_suitability",
            recommendation_count=3,
        )


def test_recommendation_slot_requires_contiguous_unique_candidates() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        RecommendationSlotState(
            query_context=_query(),
            candidates=(_candidate(91, 1), _candidate(38, 3)),
        )
    with pytest.raises(ValidationError, match="unique"):
        RecommendationSlotState(
            query_context=_query(),
            candidates=(_candidate(91, 1), _candidate(91, 2)),
        )


def test_recommendation_slot_requires_candidates_xor_empty_result() -> None:
    with pytest.raises(ValidationError, match="xor"):
        RecommendationSlotState(
            query_context=_query(),
            candidates=(),
            empty_result=False,
        )
    empty = RecommendationSlotState(
        query_context=_query(),
        candidates=(),
        empty_result=True,
    )
    assert empty.candidates == ()


def test_product_and_image_focus_must_reference_owned_values() -> None:
    with pytest.raises(ValidationError, match="focused product"):
        ProductSlotState(
            products=(_candidate(51, 1),),
            focused_product_id=57,
        )
    with pytest.raises(ValidationError, match="focused image"):
        ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
            ),
            focused_image_ordinal=2,
        )


def test_image_slot_accepts_four_products_and_fourth_focus() -> None:
    confirmed_products = tuple(
        ConfirmedImageProductRef(
            image_ordinal=ordinal,
            product_id=50 + ordinal,
        )
        for ordinal in range(1, 5)
    )

    slot = ImageSlotState(
        confirmed_products=confirmed_products,
        focused_image_ordinal=4,
    )
    snapshot = ConversationSnapshot(
        session_id="four-image-focus",
        version=1,
        active_owner=Responsibility.IMAGE_IDENTITY,
        active_focus=ActiveFocus(
            slot="image",
            object_id=54,
            ordinal=4,
        ),
        image_slot=slot,
    )

    assert snapshot.image_slot == slot


@pytest.mark.parametrize(
    ("confirmed_products", "message"),
    (
        (
            (
                ConfirmedImageProductRef(
                    image_ordinal=2,
                    product_id=53,
                ),
            ),
            "contiguous and ordered",
        ),
        (
            (
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
                ConfirmedImageProductRef(
                    image_ordinal=2,
                    product_id=53,
                ),
            ),
            "without source identities must be unique",
        ),
        (
            (
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                    source_bundle_id="bundle_" + "a" * 32,
                    source_image_id="image_" + "b" * 32,
                ),
                ConfirmedImageProductRef(
                    image_ordinal=2,
                    product_id=55,
                    source_bundle_id="bundle_" + "c" * 32,
                    source_image_id="image_" + "d" * 32,
                ),
            ),
            "one unique batch",
        ),
    ),
)
def test_image_slot_rejects_noncanonical_persisted_batch(
    confirmed_products: tuple[ConfirmedImageProductRef, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ImageSlotState(confirmed_products=confirmed_products)


def test_active_image_focus_binds_object_and_ordinal_to_same_item() -> None:
    image_slot = ImageSlotState(
        confirmed_products=(
            ConfirmedImageProductRef(
                image_ordinal=1,
                product_id=53,
            ),
            ConfirmedImageProductRef(
                image_ordinal=2,
                product_id=55,
            ),
        ),
        focused_image_ordinal=1,
    )

    with pytest.raises(ValidationError, match="active image focus"):
        ConversationSnapshot(
            session_id="mismatched-image-focus",
            version=1,
            active_owner=Responsibility.IMAGE_IDENTITY,
            active_focus=ActiveFocus(
                slot="image",
                object_id=55,
                ordinal=1,
            ),
            image_slot=image_slot,
        )


def test_dormant_image_batch_forbids_object_focus_and_needs_no_owner() -> None:
    image_slot = ImageSlotState(
        confirmed_products=(
            ConfirmedImageProductRef(
                image_ordinal=1,
                product_id=53,
            ),
            ConfirmedImageProductRef(
                image_ordinal=2,
                product_id=55,
            ),
        ),
    )

    dormant = ConversationSnapshot(
        session_id="dormant-image-batch",
        version=1,
        image_slot=image_slot,
    )
    assert dormant.active_owner is None
    assert dormant.active_focus is None

    with pytest.raises(ValidationError, match="active image focus"):
        ConversationSnapshot(
            session_id="unfocused-image-object",
            version=1,
            active_owner=Responsibility.IMAGE_IDENTITY,
            active_focus=ActiveFocus(
                slot="image",
                object_id=53,
            ),
            image_slot=image_slot,
        )


def test_snapshot_serialization_has_exact_physical_slot_keys() -> None:
    payload = _snapshot().model_dump(mode="json")

    assert set(payload) == {
        "session_id",
        "version",
        "profile_owner",
        "session_profile",
        "active_owner",
        "active_focus",
        "recommendation_slot",
        "product_slot",
        "image_slot",
        "consultation_slot",
        "knowledge_slot",
        "reply_slot",
    }
    assert set(payload["active_focus"]) == {
        "slot",
        "object_id",
        "ordinal",
    }
    assert {
        name: set(payload[name])
        for name in (
            "recommendation_slot",
            "product_slot",
            "image_slot",
            "consultation_slot",
            "knowledge_slot",
            "reply_slot",
        )
    } == {
        "recommendation_slot": {
            "kind",
            "query_context",
            "candidates",
            "empty_result",
            "focused_candidate_ordinal",
            "card_display",
        },
        "product_slot": {
            "kind",
            "products",
            "focused_product_id",
            "focused_evidence_ids",
            "card_display",
        },
        "image_slot": {
            "kind",
            "confirmed_products",
            "focused_image_ordinal",
            "card_display",
        },
        "consultation_slot": {"kind", "state", "card_display"},
        "knowledge_slot": {
            "kind",
            "question",
            "evidence_ids",
            "card_display",
        },
        "reply_slot": {"kind", "value"},
    }


def test_card_bearing_slots_preserve_exact_terminal_display_contract() -> None:
    display = CardDisplayContract(
        mode="comparison",
        visible_product_ids=(55, 53),
        max_cards=2,
        reason="comparison",
    )

    slots = (
        RecommendationSlotState(
            query_context=_query(),
            candidates=(_candidate(53, 1), _candidate(55, 2)),
            card_display=display,
        ),
        ProductSlotState(
            products=(_candidate(53, 1), _candidate(55, 2)),
            card_display=display,
        ),
        ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
                ConfirmedImageProductRef(
                    image_ordinal=2,
                    product_id=55,
                ),
            ),
            card_display=display,
        ),
    )

    assert all(slot.card_display == display for slot in slots)


@pytest.mark.parametrize(
    "forbidden_key",
    (
        "card_display",
        "focus_state",
        "has_image_delivery",
        "query_context",
        "empty_result",
        "candidates",
        "focused_candidate_ordinal",
        "focused_evidence_ids",
        "focused_general_knowledge_ids",
        "last_general_knowledge_question",
        "consultation",
        "clarification",
        "pending_turn",
        "unknown_state",
    ),
)
def test_snapshot_rejects_legacy_or_extra_top_level_state_keys(
    forbidden_key: str,
) -> None:
    payload = _snapshot().model_dump(mode="python")
    payload[forbidden_key] = "forbidden"

    with pytest.raises(ValidationError, match="Extra inputs"):
        ConversationSnapshot.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    "slot_name",
    (
        "recommendation_slot",
        "product_slot",
        "image_slot",
        "consultation_slot",
        "knowledge_slot",
        "reply_slot",
        "active_focus",
    ),
)
def test_snapshot_rejects_extra_nested_slot_state(
    slot_name: str,
) -> None:
    payload = _snapshot().model_dump(mode="python")
    payload[slot_name] = deepcopy(payload[slot_name])
    payload[slot_name]["legacy_alias"] = "forbidden"

    with pytest.raises(ValidationError, match="Extra inputs"):
        ConversationSnapshot.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    ("target_slot", "foreign_slot"),
    [
        (target, foreign)
        for target in (
            "recommendation_slot",
            "product_slot",
            "image_slot",
            "consultation_slot",
            "knowledge_slot",
            "reply_slot",
        )
        for foreign in (
            "recommendation_slot",
            "product_slot",
            "image_slot",
            "consultation_slot",
            "knowledge_slot",
            "reply_slot",
        )
        if target != foreign
    ],
)
def test_snapshot_rejects_cross_lane_slot_payloads(
    target_slot: str,
    foreign_slot: str,
) -> None:
    payload = _snapshot().model_dump(mode="python")
    payload[target_slot] = deepcopy(payload[foreign_slot])

    with pytest.raises(ValidationError):
        ConversationSnapshot.model_validate(payload, strict=True)


def test_migration_moves_top_level_display_to_exact_active_slot() -> None:
    payload = _snapshot().model_dump(mode="json")
    for slot_name in (
        "recommendation_slot",
        "product_slot",
        "image_slot",
        "consultation_slot",
        "knowledge_slot",
    ):
        payload[slot_name].pop("card_display")
    terminal_display = CardDisplayContract(
        mode="comparison",
        visible_product_ids=(57, 53),
        max_cards=2,
        reason="comparison",
    ).model_dump(mode="json")
    payload["active_owner"] = Responsibility.COMPARISON.value
    payload["active_focus"] = {
        "slot": "image",
        "object_id": 53,
        "ordinal": 1,
    }
    payload["card_display"] = terminal_display

    migrated = migrate_legacy_conversation_snapshot_payload(payload)

    assert set(migrated) == {
        "session_id",
        "version",
        "profile_owner",
        "session_profile",
        "active_owner",
        "active_focus",
        "recommendation_slot",
        "product_slot",
        "image_slot",
        "consultation_slot",
        "knowledge_slot",
        "reply_slot",
    }
    assert migrated["image_slot"]["card_display"] == terminal_display
    assert "card_display" not in migrated["product_slot"]
    assert "card_display" not in migrated["recommendation_slot"]
    restored = ConversationSnapshot.model_validate_json(
        json.dumps(migrated),
        strict=True,
    )
    assert restored.image_slot.card_display == CardDisplayContract(
        **terminal_display
    )


def test_migration_converts_legacy_consultation_observation_once() -> None:
    payload = _snapshot().model_dump(mode="json")
    payload["consultation_slot"]["state"]["observations"] = [
        {
            "code": "post_cleanse_tightness",
            "answer": "yes",
            "source_turn_id": "turn_000000000001",
        }
    ]

    migrated = migrate_legacy_conversation_snapshot_payload(payload)

    observation = migrated["consultation_slot"]["state"]["observations"][0]
    assert observation == {
        "observation_id": "obs_legacy_post_cleanse_tightness",
        "dimension": "tightness",
        "state": "present",
        "location": "whole_face",
        "trigger": "post_cleanse",
        "duration": "current",
        "severity": "unknown",
        "source_text": "洗脸后紧绷",
        "source_turn_id": "turn_000000000001",
    }
    ConversationSnapshot.model_validate_json(
        json.dumps(migrated),
        strict=True,
    )


def test_query_context_rejects_invalid_bounds_and_duplicates() -> None:
    with pytest.raises(ValidationError, match="budget"):
        RecommendationQueryContext(
            category="serum",
            recommendation_mode_basis="broad_exploration",
            budget_minimum=Decimal("500"),
            budget_maximum=Decimal("100"),
        )
    with pytest.raises(ValidationError, match="exclusions"):
        RecommendationQueryContext(
            category="serum",
            recommendation_mode_basis="broad_exploration",
            exclusions=("酒精", "酒精"),
        )


def test_snapshot_and_slots_are_deeply_immutable() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.active_focus = None
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.recommendation_slot.empty_result = True
