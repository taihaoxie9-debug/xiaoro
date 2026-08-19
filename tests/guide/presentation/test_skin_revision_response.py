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
from app.guide.presentation.skin_revision_response import (
    build_skin_revision_message,
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
            maximum=Decimal("500"),
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
            [] if status is WinnerStatus.NO_CANDIDATE else [91, 38]
        ),
        winner_status=status,
        winner_product_id=None,
        evaluations=[],
        comparison_dimensions=["skin_match", "price"],
        risk_findings=(
            [
                RiskFinding(
                    kind="skin_match_unknown",
                    product_id=product_id,
                    detail="敏感肌适配证据缺失",
                )
                for product_id in (91, 38)
            ]
            if status is WinnerStatus.INSUFFICIENT_FOR_WINNER
            else []
        ),
        evidence_refs=["efficacy=repair", "skin=sensitive"],
        tie_reason=None,
    )


def test_skin_revision_message_confirms_new_skin_and_inherited_context() -> None:
    message = build_skin_revision_message(
        task(),
        decision(WinnerStatus.INSUFFICIENT_FOR_WINNER),
    )

    assert "肤质调整为“敏感肌”" in message
    assert "沿用" in message
    assert "¥500" in message
    assert "修护精华" in message
    assert "敏感肌适配证据仍不足" in message
    assert "预算上限调整" not in message
    assert "最佳" not in message


@pytest.mark.parametrize(("topic", "label"), _TOPIC_LABEL_CASES)
def test_skin_revision_message_uses_exact_topic_label(
    topic: TopicCode,
    label: str,
) -> None:
    message = build_skin_revision_message(
        task(topic),
        decision(WinnerStatus.INSUFFICIENT_FOR_WINNER),
    )
    efficacy = "修护" if topic is TopicCode.SERUM else ""

    assert f"沿用“¥500 内{efficacy}{label}”" in message


def test_no_candidate_skin_revision_says_previous_state_is_retained() -> None:
    message = build_skin_revision_message(
        task(),
        decision(WinnerStatus.NO_CANDIDATE),
    )

    assert "换成这个肤质后，暂时没有找到同时合适的商品" in message
    assert "前面已经挑出的商品先保留" in message
    assert "硬条件" not in message
