"""Slice 1 文本理解层失败测试（RED）。

验证 understand_text 把自然语言拆成结构化理解：
- 预算数字、品类、否定 → exact_constraints（代码精确抽取）
- 模糊偏好 → semantic_proposals（语义草稿，不参与硬筛）
不发明商品事实、不排序、不判 winner。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.guide.understanding import StructuredUnderstanding
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    EfficacyDraft,
    EfficacyTarget,
    ExclusionDraft,
    SkinDraft,
    TopicCode,
    UnderstandingGoal,
)


def understand():
    from app.guide.understanding.text_understanding import understand_text

    return understand_text


def test_understands_budget_skin_and_category_as_exact_constraints() -> None:
    result = understand()("500 内适合油敏肌的防晒")

    assert isinstance(result, StructuredUnderstanding)
    assert result.goal is UnderstandingGoal.RECOMMENDATION
    assert result.topic is TopicCode.SUNSCREEN
    assert result.signal_trace == []
    kinds = {item.kind for item in result.exact_constraints}
    assert {"budget", "category", "skin"} <= kinds


def test_repair_serum_is_typed_as_category_and_efficacy() -> None:
    result = understand()("500 元内敏感肌修护精华")

    assert result.topic is TopicCode.SERUM
    efficacy = next(
        item
        for item in result.exact_constraints
        if isinstance(item, EfficacyDraft)
    )
    assert efficacy.value is EfficacyTarget.REPAIR


def test_does_not_invent_product_facts_or_scores() -> None:
    result = understand()("500 内适合油敏肌的防晒")

    dumped = result.model_dump()
    assert "candidate_ids" not in dumped
    assert "product_facts" not in dumped
    assert "score" not in dumped
    assert "winner" not in dumped


@pytest.mark.parametrize(
    ("message", "minimum", "maximum"),
    [
        ("500 内防晒", None, Decimal("500")),
        ("500.5 元以内防晒", None, Decimal("500.5")),
        ("300 元以上防晒", Decimal("300"), None),
        ("300 到 500 元防晒", Decimal("300"), Decimal("500")),
    ],
)
def test_budget_directions_are_exact(
    message: str,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> None:
    result = understand()(message)
    budget = next(
        item
        for item in result.exact_constraints
        if isinstance(item, BudgetDraft)
    )
    assert budget.minimum == minimum
    assert budget.maximum == maximum


@pytest.mark.parametrize(
    "message",
    [
        "-100 内防晒",
        "-100 元防晒",
        "0 元以内防晒",
        "0 元防晒",
    ],
)
def test_invalid_budget_becomes_uncertainty(message: str) -> None:
    result = understand()(message)
    assert any(issue.code == "invalid_budget" for issue in result.uncertainties)
    assert not any(
        isinstance(item, BudgetDraft)
        for item in result.exact_constraints
    )


@pytest.mark.parametrize(
    ("message", "minimum", "maximum"),
    (
        ("三百以内的防晒", None, Decimal("300")),
        ("两百五以内的防晒", None, Decimal("250")),
        ("三百到五百的防晒", Decimal("300"), Decimal("500")),
    ),
)
def test_clear_chinese_budget_becomes_exact_constraint(
    message: str,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> None:
    result = understand()(message)
    budget = next(
        item
        for item in result.exact_constraints
        if isinstance(item, BudgetDraft)
    )

    assert budget.minimum == minimum
    assert budget.maximum == maximum
    assert not any(
        issue.code == "unsupported_budget_format"
        for issue in result.uncertainties
    )


@pytest.mark.parametrize(
    ("message", "meaning"),
    (
        ("百来块的防晒", "100 到 199"),
        ("几百上下的防晒", "200 到 900"),
        ("几百块上下的防晒", "200 到 900"),
        ("250 左右的防晒", "225 到 275"),
        ("三张以内的防晒", "300 元以内"),
    ),
)
def test_fuzzy_budget_requests_typed_confirmation_with_meaning(
    message: str,
    meaning: str,
) -> None:
    result = understand()(message)

    assert not any(
        isinstance(item, BudgetDraft)
        for item in result.exact_constraints
    )
    budget_issue = next(
        issue
        for issue in result.uncertainties
        if issue.code == "unsupported_budget_format"
    )
    assert meaning in budget_issue.detail


def test_negation_is_captured_exactly() -> None:
    result = understand()("不要含酒精的防晒")
    assert any(
        isinstance(item, ExclusionDraft) and item.value == "酒精"
        for item in result.exact_constraints
    )


def test_serum_exclusion_suffix_is_removed() -> None:
    result = understand()("不要酒精的修护精华")

    exclusions = [
        item.value
        for item in result.exact_constraints
        if isinstance(item, ExclusionDraft)
    ]
    assert exclusions == ["酒精"]


def test_multiple_exclusions_are_independent() -> None:
    result = understand()("不要酒精也不要香精的防晒")
    exclusions = {
        item.value
        for item in result.exact_constraints
        if isinstance(item, ExclusionDraft)
    }
    assert exclusions == {"酒精", "香精"}


@pytest.mark.parametrize(
    ("message", "excluded_value"),
    (
        ("无矿物油的卸妆", "矿物油"),
        ("绝对不能有尼泊金酯的面霜", "尼泊金酯"),
        ("我对水杨酸过敏，推荐防晒", "水杨酸"),
    ),
)
def test_arbitrary_hard_exclusion_is_extracted_without_ingredient_enum(
    message: str,
    excluded_value: str,
) -> None:
    result = understand()(message)

    assert any(
        isinstance(item, ExclusionDraft)
        and item.value == excluded_value
        for item in result.exact_constraints
    )


@pytest.mark.parametrize(
    "message",
    (
        "孕妇能用的防晒",
        "500 元内油敏肌防晒安全吗",
        "这款精华会不会过敏",
    ),
)
def test_unverifiable_safety_requirement_is_typed_fail_closed(
    message: str,
) -> None:
    result = understand()(message)

    issue = next(
        item
        for item in result.uncertainties
        if item.code == "unverified_safety_requirement"
    )
    assert "无法用强证据核实" in issue.detail


@pytest.mark.parametrize(
    "message",
    (
        "不闷的防晒",
        "不油腻的防晒",
        "不刺激的精华",
        "想要有安全感的香水",
    ),
)
def test_sensory_soft_preference_is_not_misclassified_as_safety_gate(
    message: str,
) -> None:
    result = understand()(message)

    assert not any(
        isinstance(item, ExclusionDraft)
        for item in result.exact_constraints
    )
    assert not any(
        issue.code == "unverified_safety_requirement"
        for issue in result.uncertainties
    )


def test_no_budget_means_no_budget_constraint() -> None:
    result = understand()("适合油敏肌的防晒")
    assert not any(
        isinstance(item, BudgetDraft) for item in result.exact_constraints
    )


def test_category_and_skin_are_typed() -> None:
    result = understand()("适合油敏肌的防晒")
    category = next(
        item
        for item in result.exact_constraints
        if isinstance(item, CategoryDraft)
    )
    skin = next(
        item
        for item in result.exact_constraints
        if isinstance(item, SkinDraft)
    )
    assert category.value is TopicCode.SUNSCREEN
    assert skin.kind == "skin"


@pytest.mark.parametrize("message", ["精华水", "眼部精华"])
def test_adjacent_categories_are_owned_by_skincare(
    message: str,
) -> None:
    result = understand()(message)
    assert result.topic is TopicCode.SKINCARE


def test_understanding_rejects_oversized_direct_input() -> None:
    with pytest.raises(ValueError, match="message length"):
        understand()("x" * 4001)
