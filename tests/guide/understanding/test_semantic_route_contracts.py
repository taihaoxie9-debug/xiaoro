from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import (
    ActiveConstraintKind,
    ClarificationCode,
    ConfirmedProfileField,
    SemanticContext,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticDetailStage,
    SemanticRouteBindingAuthority,
    SemanticRouteProposal,
)


def _valid_route_payload() -> dict[str, object]:
    return {
        "goal": "recommendation",
        "topic": "sunscreen",
        "detail_stage": "recommendation",
        "confidence": 0.95,
        "clarification_hint": None,
    }


def test_route_binding_authority_is_derived_from_typed_context() -> None:
    context = SemanticContext(
        conversation_version=7,
        active_topic=TopicCode.SUNSCREEN,
        visible_candidate_count=3,
        focused_candidate_ordinal=2,
        image_count=2,
        confirmed_image_ordinals=(1, 2),
        focused_image_ordinal=1,
        active_constraint_kinds=(
            ActiveConstraintKind.BUDGET,
            ActiveConstraintKind.INGREDIENT_EXCLUSION,
        ),
        confirmed_profile_fields=(
            ConfirmedProfileField.SKIN_TYPE,
        ),
        pending_clarification=ClarificationCode.BUDGET,
    )

    authority = SemanticRouteBindingAuthority.from_context(context)

    assert authority.model_dump(mode="json") == {
        "active_dialogue": None,
        "awaiting_reply": False,
        "candidate_ordinals": [1, 2, 3],
        "current_item_ordinal": 2,
        "current_batch_available": True,
        "image_ordinals": [1, 2],
        "confirmed_image_ordinals": [1, 2],
        "current_image_ordinal": 1,
        "current_topic": "sunscreen",
        "previous_constraint_kinds": [
            "budget",
            "ingredient_exclusion",
        ],
        "pending_clarification": "budget",
    }
    assert "conversation_version" not in authority.model_fields
    assert "confirmed_profile_fields" not in authority.model_fields


def test_route_binding_authority_does_not_invent_focus() -> None:
    context = SemanticContext(
        conversation_version=1,
        active_topic=None,
        visible_candidate_count=3,
        focused_candidate_ordinal=None,
        image_count=2,
        focused_image_ordinal=None,
        active_constraint_kinds=(),
        confirmed_profile_fields=(),
    )

    authority = SemanticRouteBindingAuthority.from_context(context)

    assert authority.candidate_ordinals == (1, 2, 3)
    assert authority.current_item_ordinal is None
    assert authority.current_batch_available is True
    assert authority.image_ordinals == (1, 2)
    assert authority.confirmed_image_ordinals == ()
    assert "confirmed_image_ordinals" not in authority.model_dump(
        mode="json"
    )
    assert authority.current_image_ordinal is None
    assert authority.current_topic is None


def test_confirmed_image_authority_must_be_a_subset_of_image_ordinals() -> None:
    with pytest.raises(ValidationError, match="confirmed image"):
        SemanticRouteBindingAuthority(
            active_dialogue="recommendation",
            awaiting_reply=False,
            candidate_ordinals=(),
            current_item_ordinal=None,
            current_batch_available=False,
            image_ordinals=(1,),
            confirmed_image_ordinals=(2,),
            current_image_ordinal=None,
            current_topic=TopicCode.SUNSCREEN,
            previous_constraint_kinds=(),
            pending_clarification=None,
        )


def test_route_contract_accepts_only_strict_route_fields() -> None:
    proposal = SemanticRouteProposal.model_validate_json(
        (
            '{"goal":"recommendation","topic":"sunscreen",'
            '"detail_stage":"recommendation","confidence":0.95,'
            '"clarification_hint":null}'
        ),
        strict=True,
    )

    assert proposal.goal is UnderstandingGoal.RECOMMENDATION
    assert proposal.topic is TopicCode.SUNSCREEN
    assert proposal.detail_stage is SemanticDetailStage.RECOMMENDATION

    for forbidden in (
        "product_id",
        "candidate_id",
        "price",
        "winner",
        "score",
        "sql",
        "profile",
    ):
        with pytest.raises(ValidationError):
            SemanticRouteProposal.model_validate(
                {**_valid_route_payload(), forbidden: "bad"},
            )


def test_route_contract_rejects_coercion_and_non_finite_confidence() -> None:
    with pytest.raises(ValidationError):
        SemanticRouteProposal.model_validate(
            {**_valid_route_payload(), "confidence": "0.95"},
            strict=True,
        )
    for confidence in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            SemanticRouteProposal.model_validate(
                {**_valid_route_payload(), "confidence": confidence},
                strict=True,
            )


def test_route_detail_stage_must_match_goal() -> None:
    with pytest.raises(ValidationError, match="detail stage"):
        SemanticRouteProposal.model_validate_json(
            (
                '{"goal":"recommendation","topic":"sunscreen",'
                '"detail_stage":"assessment","confidence":0.95,'
                '"clarification_hint":null}'
            ),
            strict=True,
        )


def test_clarification_route_requires_hint_and_skips_detail() -> None:
    proposal = SemanticRouteProposal(
        goal=UnderstandingGoal.CLARIFICATION,
        topic=None,
        detail_stage=SemanticDetailStage.NONE,
        confidence=0.4,
        clarification_hint=ClarificationCode.GOAL,
    )
    assert proposal.detail_stage is SemanticDetailStage.NONE

    with pytest.raises(ValidationError, match="clarification hint"):
        SemanticRouteProposal(
            goal=UnderstandingGoal.CLARIFICATION,
            topic=None,
            detail_stage=SemanticDetailStage.NONE,
            confidence=0.4,
            clarification_hint=None,
        )
