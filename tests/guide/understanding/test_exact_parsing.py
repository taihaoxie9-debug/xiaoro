from __future__ import annotations

import pytest

from app.guide.understanding.contracts import (
    CategoryDraft,
    ExactRevisionOperation,
    ExactRevisionTarget,
    SkinDraft,
    SkinTarget,
    TopicCode,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_revision_confirmations,
)


def _proofs(message: str):
    return parse_exact_revision_confirmations(message)


def test_skin_revision_emits_code_owned_single_slot_proof() -> None:
    proofs = _proofs("肤质改成油敏肌")

    assert len(proofs) == 1
    assert proofs[0].operation is (
        ExactRevisionOperation.REVISE_CONSTRAINT
    )
    assert proofs[0].target is ExactRevisionTarget.SKIN
    assert proofs[0].affected_value == "oily_sensitive"
    span = proofs[0].source_span
    assert "肤质改成油敏肌"[span.start:span.end] == "肤质改成油敏肌"


@pytest.mark.parametrize(
    ("message", "target", "value"),
    (
        (
            "取消酒精排除",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "不再排除香精",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "香精",
        ),
        (
            "酒精这条排除取消掉",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "不用再避开酒精了",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "把不要酒精这个限制删了",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "可以含酒精，前面那条撤掉",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "酒精不排除了，继续选",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "把酒精禁用条件拿掉",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "撤销之前对酒精的排除",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "酒精可以接受了，删掉那项限制",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "别再把含酒精的筛出去",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "前面说避开酒精作废，继续推荐",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "解除无酒精要求",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "之前的酒精排除不算了",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "允许含酒精，把禁用项删除",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "酒精这一项从避开清单移除",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "撤回酒精限制，其余条件照旧",
            ExactRevisionTarget.INGREDIENT_EXCLUSION,
            "酒精",
        ),
        (
            "取消必须含烟酰胺",
            ExactRevisionTarget.INGREDIENT_INCLUSION,
            "烟酰胺",
        ),
    ),
)
def test_named_multi_value_withdrawal_binds_affected_value(
    message: str,
    target: ExactRevisionTarget,
    value: str,
) -> None:
    proofs = _proofs(message)

    assert len(proofs) == 1
    assert proofs[0].operation is (
        ExactRevisionOperation.WITHDRAW_CONSTRAINT
    )
    assert proofs[0].target is target
    assert proofs[0].affected_value == value
    span = proofs[0].source_span
    assert message[span.start:span.end] == message


@pytest.mark.parametrize(
    "message",
    (
        "如果取消酒精排除会怎样",
        "不要取消酒精排除",
        "也许不再排除酒精",
        "是否应该取消必须含烟酰胺",
    ),
)
def test_conditional_or_negated_withdrawal_has_no_proof(
    message: str,
) -> None:
    assert _proofs(message) == []


@pytest.mark.parametrize(
    ("message", "expected_topics"),
    (
        (
            "B5精华怎么搭护肤步骤，肤感如何",
            [TopicCode.SERUM],
        ),
        (
            "B5精华放在护肤哪一步，吸收后黏不黏",
            [TopicCode.SERUM],
        ),
        (
            "B5精华怎么叠加其他护肤，会不会黏腻",
            [TopicCode.SERUM],
        ),
        (
            "排在二号的产品要放护肤哪一步",
            [],
        ),
    ),
)
def test_skincare_routine_phrase_does_not_add_second_product_topic(
    message: str,
    expected_topics: list[TopicCode],
) -> None:
    constraints, issues = parse_exact_constraints(message)

    assert issues == []
    assert [
        item.value
        for item in constraints
        if isinstance(item, CategoryDraft)
    ] == expected_topics


@pytest.mark.parametrize(
    "message",
    (
        "再把B5精华和CE精华放一起看差异",
        "两款一起比较",
        "这些成分可以一起用吗",
    ),
)
def test_together_phrase_does_not_create_minimum_budget(
    message: str,
) -> None:
    constraints, issues = parse_exact_constraints(message)

    assert issues == []
    assert not any(
        getattr(item, "kind", None) == "budget"
        for item in constraints
    )


@pytest.mark.parametrize(
    ("message", "minimum", "maximum"),
    (
        ("这些成分一起用，预算三百以内", None, "300"),
        ("三百起的精华", "300", None),
        ("五元起的小样", "5", None),
    ),
)
def test_valid_budget_after_or_around_together_language_is_preserved(
    message: str,
    minimum: str | None,
    maximum: str | None,
) -> None:
    constraints, issues = parse_exact_constraints(message)
    budgets = [
        item
        for item in constraints
        if getattr(item, "kind", None) == "budget"
    ]

    assert issues == []
    assert len(budgets) == 1
    assert (
        None if budgets[0].minimum is None else str(budgets[0].minimum)
    ) == minimum
    assert (
        None if budgets[0].maximum is None else str(budgets[0].maximum)
    ) == maximum


def test_separate_oily_and_sensitive_phrases_compose_oily_sensitive() -> None:
    constraints, issues = parse_exact_constraints(
        "帮室友挑防晒，她油皮敏感，预算不超500"
    )

    assert issues == []
    assert [
        item.value
        for item in constraints
        if isinstance(item, SkinDraft)
    ] == [SkinTarget.OILY_SENSITIVE]
