from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.application.contracts import UserTurn
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
)
from app.guide.understanding.contracts import EfficacyTarget, TopicCode


def test_user_turn_rejects_empty_and_oversized_messages() -> None:
    base = {
        "session_id": "s-1",
        "image_bundle_id": None,
        "conversation_version": 0,
    }
    with pytest.raises(ValidationError):
        UserTurn(message="   ", **base)
    with pytest.raises(ValidationError):
        UserTurn(message="x" * 4001, **base)


def test_budget_contract_rejects_non_positive_and_reversed_range() -> None:
    with pytest.raises(ValidationError):
        BudgetConstraint(minimum=None, maximum=Decimal("0"))
    with pytest.raises(ValidationError):
        BudgetConstraint(
            minimum=Decimal("500"),
            maximum=Decimal("300"),
        )


def test_category_constraint_uses_normalized_topic_code() -> None:
    constraint = CategoryConstraint(value=TopicCode.SUNSCREEN)
    assert constraint.kind == "category"
    assert constraint.value is TopicCode.SUNSCREEN


def test_efficacy_constraint_uses_controlled_target() -> None:
    constraint = EfficacyConstraint(value=EfficacyTarget.REPAIR)
    assert constraint.kind == "efficacy"
    assert constraint.value is EfficacyTarget.REPAIR
