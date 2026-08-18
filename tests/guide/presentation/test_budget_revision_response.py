from decimal import Decimal

import pytest

from app.guide.decision.contracts import (
    DecisionResult,
    RiskFinding,
    WinnerStatus,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    SkinConstraint,
    TaskPlan,
)
from app.guide.presentation.budget_revision_response import (
    build_budget_revision_message,
)
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
    TopicCode,
)


_TOPIC_LABEL_CASES = (
    (TopicCode.SUNSCREEN, "防晒"),
    (TopicCode.SERUM, "精华"),
    (TopicCode.SKINCARE, "护肤"),
    (TopicCode.BASE_MAKEUP, "底妆"),
    (TopicCode.COLOR_MAKEUP, "彩妆"),
    (TopicCode.CLEANSER, "洁面/卸妆"),
    (TopicCode.FRAGRANCE, "香水"),
)


def task(topic: TopicCode = TopicCode.SERUM) -> TaskPlan:
    constraints = [
        CategoryConstraint(value=topic),
        BudgetConstraint(
            minimum=None,
            maximum=Decimal("100"),
        ),
        SkinConstraint(value=SkinTarget.SENSITIVE),
    ]
    if topic is TopicCode.SERUM:
        constraints.append(
            EfficacyConstraint(value=EfficacyTarget.REPAIR)
        )
    return TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=constraints,
        required_evidence=["canonical_product"],
        clarification=None,
    )


def decision(status: WinnerStatus) -> DecisionResult:
    return DecisionResult(
        ordered_product_ids=(
            [] if status is WinnerStatus.NO_CANDIDATE else [91]
        ),
        winner_status=status,
        winner_product_id=None,
        evaluations=[],
        comparison_dimensions=["price"],
        risk_findings=(
            [
                RiskFinding(
                    kind="skin_match_unknown",
                    product_id=91,
                    detail="敏感肌适配证据缺失",
                )
            ]
            if status is WinnerStatus.INSUFFICIENT_FOR_WINNER
            else []
        ),
        evidence_refs=["efficacy=repair"],
        tie_reason=None,
    )


def test_budget_revision_message_confirms_inheritance_and_stays_honest() -> None:
    message = build_budget_revision_message(
        task(),
        decision(WinnerStatus.INSUFFICIENT_FOR_WINNER),
    )

    assert "敏感肌修护精华" in message
    assert "¥100" in message
    assert "敏感肌适配证据仍不足" in message
    assert "唯一最适合" in message
    assert "最佳" not in message


@pytest.mark.parametrize(("topic", "label"), _TOPIC_LABEL_CASES)
def test_budget_revision_message_uses_exact_topic_label(
    topic: TopicCode,
    label: str,
) -> None:
    message = build_budget_revision_message(
        task(topic),
        decision(WinnerStatus.INSUFFICIENT_FOR_WINNER),
    )
    efficacy = "修护" if topic is TopicCode.SERUM else ""

    assert f"已沿用“敏感肌{efficacy}{label}”" in message


def test_no_candidate_message_says_previous_state_is_retained() -> None:
    message = build_budget_revision_message(
        task(),
        decision(WinnerStatus.NO_CANDIDATE),
    )

    assert "这个预算内暂时没有找到同时合适的商品" in message
    assert "前面已经挑出的商品先保留" in message
    assert "硬条件" not in message
