from __future__ import annotations

from decimal import Decimal
import importlib

import pytest

from app.guide.understanding.contracts import (
    BudgetDraft,
    UnderstandingIssue,
)
from app.guide.understanding.semantic_contracts import (
    SemanticNumberCandidate,
)


def _module():
    return importlib.import_module(
        "app.guide.understanding.budget_candidate_validation"
    )


def _candidate(
    message: str,
    raw_text: str,
    *,
    relation: str,
    minimum: str | None,
    maximum: str | None,
) -> SemanticNumberCandidate:
    start = message.index(raw_text)
    return SemanticNumberCandidate(
        relation=relation,
        raw_text=raw_text,
        start=start,
        end=start + len(raw_text),
        minimum=minimum,
        maximum=maximum,
    )


def test_code_validates_bound_chinese_candidate_to_decimal_budget() -> None:
    module = _module()
    message = "预算三百以内，推荐防晒"

    result = module.validate_budget_candidates(
        message=message,
        candidates=(
            _candidate(
                message,
                "三百以内",
                relation="maximum",
                minimum=None,
                maximum="300",
            ),
        ),
        exact_constraints=(),
        exact_issues=(),
    )

    assert result.resolution == "semantic_fills"
    assert result.budget == BudgetDraft(
        minimum=None,
        maximum=Decimal("300"),
    )
    assert result.issue is None


@pytest.mark.parametrize(
    ("message", "raw_text", "maximum"),
    (
        (
            "敏感肌想看修护精华，预算别超过500",
            "预算别超过500",
            "500",
        ),
        (
            "五百封顶，给我挑敏感肌修护精华",
            "五百封顶",
            "500",
        ),
        (
            "预算别过500，敏感肌想选修护精华",
            "预算别过500",
            "500",
        ),
        (
            "五百预算看修护精华，我是敏感皮",
            "五百",
            "500",
        ),
        (
            "敏感肌用的修护精华咋选？上限500",
            "上限500",
            "500",
        ),
        (
            "不是我用，给对象看油敏肌防晒，别超500",
            "别超500",
            "500",
        ),
        (
            "帮室友挑防晒，她油皮敏感，预算不超500",
            "预算不超500",
            "500",
        ),
        (
            "改一下，上限只留100",
            "上限只留100",
            "100",
        ),
    ),
)
def test_code_accepts_source_bound_colloquial_maximum_phrases(
    message: str,
    raw_text: str,
    maximum: str,
) -> None:
    module = _module()

    result = module.validate_budget_candidates(
        message=message,
        candidates=(
            _candidate(
                message,
                raw_text,
                relation="maximum",
                minimum=None,
                maximum=maximum,
            ),
        ),
        exact_constraints=(),
        exact_issues=(),
    )

    assert result == module.BudgetCandidateValidation(
        budget=BudgetDraft(
            minimum=None,
            maximum=Decimal(maximum),
        ),
        issue=None,
        resolution="semantic_fills",
    )


@pytest.mark.parametrize(
    ("message", "raw_text", "maximum"),
    (
        (
            "手里五百，皮肤容易敏，想把修护精华定下来",
            "五百",
            "500",
        ),
        (
            "敏皮买修护类精华怎么挑？价格卡在五百",
            "价格卡在五百",
            "500",
        ),
        (
            "其他要求照旧，价钱上限改成100",
            "价钱上限改成100",
            "100",
        ),
    ),
)
def test_source_bound_open_budget_language_uses_closed_model_relation(
    message: str,
    raw_text: str,
    maximum: str,
) -> None:
    module = _module()

    result = module.validate_budget_candidates(
        message=message,
        candidates=(
            _candidate(
                message,
                raw_text,
                relation="maximum",
                minimum=None,
                maximum=maximum,
            ),
        ),
        exact_constraints=(),
        exact_issues=(),
    )

    assert result == module.BudgetCandidateValidation(
        budget=BudgetDraft(
            minimum=None,
            maximum=Decimal(maximum),
        ),
        issue=None,
        resolution="semantic_fills",
    )


def test_open_budget_language_rejects_model_amount_absent_from_source() -> None:
    module = _module()
    message = "手里五百，皮肤容易敏"

    result = module.validate_budget_candidates(
        message=message,
        candidates=(
            _candidate(
                message,
                "手里五百",
                relation="maximum",
                minimum=None,
                maximum="300",
            ),
        ),
        exact_constraints=(),
        exact_issues=(),
    )

    assert result.resolution == "clarify"
    assert result.budget is None
    assert result.issue is not None
    assert result.issue.code == "invalid_budget"


def test_exact_budget_remains_authority_over_semantic_candidate() -> None:
    module = _module()
    message = "500以内，模型误提三百以内"
    exact = BudgetDraft(minimum=None, maximum=Decimal("500"))

    result = module.validate_budget_candidates(
        message=message,
        candidates=(
            _candidate(
                message,
                "三百以内",
                relation="maximum",
                minimum=None,
                maximum="300",
            ),
        ),
        exact_constraints=(exact,),
        exact_issues=(),
    )

    assert result.resolution == "exact_wins"
    assert result.budget is None
    assert result.issue is None


def test_candidate_span_direction_and_decimal_mismatch_fail_closed() -> None:
    module = _module()
    message = "预算三百以内"
    valid = _candidate(
        message,
        "三百以内",
        relation="maximum",
        minimum=None,
        maximum="350",
    )
    invalid_span = valid.model_copy(
        update={"start": valid.start + 1},
    )

    mismatched = module.validate_budget_candidates(
        message=message,
        candidates=(valid,),
        exact_constraints=(),
        exact_issues=(),
    )
    unbound = module.validate_budget_candidates(
        message=message,
        candidates=(invalid_span,),
        exact_constraints=(),
        exact_issues=(),
    )

    assert mismatched.resolution == "clarify"
    assert mismatched.budget is None
    assert mismatched.issue == UnderstandingIssue(
        code="invalid_budget",
        detail="我理解的预算范围和你的原话不一致，请重新说一下预算。",
    )
    assert unbound.resolution == "clarify"
    assert unbound.budget is None
    assert unbound.issue is not None
    assert unbound.issue.code == "invalid_budget"


def test_fuzzy_candidate_preserves_meaningful_budget_clarification() -> None:
    module = _module()
    message = "250 左右的防晒"

    result = module.validate_budget_candidates(
        message=message,
        candidates=(
            _candidate(
                message,
                "250 左右",
                relation="approximate",
                minimum="225",
                maximum="275",
            ),
        ),
        exact_constraints=(),
        exact_issues=(),
    )

    assert result.resolution == "clarify"
    assert result.budget is None
    assert result.issue is not None
    assert result.issue.code == "unsupported_budget_format"
    assert "225 到 275" in result.issue.detail


def test_span_only_candidate_defers_to_exact_fuzzy_budget_issue() -> None:
    module = _module()
    message = "预算几百块上下，要适合油敏肌的防晒"
    candidate = SemanticNumberCandidate.model_construct(
        kind="budget",
        relation="range",
        raw_text="几百块上下",
        start=2,
        end=7,
        minimum=None,
        maximum=None,
    )
    exact_issue = UnderstandingIssue(
        code="unsupported_budget_format",
        detail="“几百块上下”通常可能指 200 到 900 元，请确认具体下限和上限。",
    )

    result = module.validate_budget_candidates(
        message=message,
        candidates=(candidate,),
        exact_constraints=(),
        exact_issues=(exact_issue,),
    )

    assert result.resolution == "exact_wins"
    assert result.budget is None
    assert result.issue is None
