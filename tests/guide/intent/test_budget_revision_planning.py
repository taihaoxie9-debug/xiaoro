from decimal import Decimal

from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.budget_revision_planning import (
    plan_budget_revision,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    SkinConstraint,
)
from app.guide.understanding.budget_revision_parsing import (
    parse_budget_revision,
)
from app.guide.understanding.contracts import (
    BudgetRevisionDraft,
    EfficacyTarget,
    ExactRevisionConfirmation,
    ExactRevisionOperation,
    ExactRevisionTarget,
    SkinTarget,
    SourceSpan,
    TopicCode,
)


def query_context():
    return RecommendationQueryContext(
        category="serum",
        budget_minimum=None,
        budget_maximum=Decimal("500"),
        skin="sensitive",
        efficacy="repair",
        exclusions=["酒精"],
    )


def _budget_proof() -> ExactRevisionConfirmation:
    return ExactRevisionConfirmation(
        operation=ExactRevisionOperation.REVISE_CONSTRAINT,
        target=ExactRevisionTarget.BUDGET,
        source_span=SourceSpan(start=0, end=8),
    )


def test_budget_revision_without_exact_proof_clarifies() -> None:
    plan = plan_budget_revision(
        parse_budget_revision("预算降到100元呢"),
        query_context=query_context(),
        request_version=1,
        snapshot_version=1,
        revision_confirmation=None,
    )

    assert plan is not None
    assert plan.mode == "clarify"
    assert "缺少精确修改证明" in plan.clarification


def test_replaces_budget_and_preserves_other_constraints() -> None:
    original = query_context()
    plan = plan_budget_revision(
        parse_budget_revision("预算降到100元呢"),
        query_context=original,
        request_version=1,
        snapshot_version=1,
        revision_confirmation=_budget_proof(),
    )

    assert plan is not None
    assert plan.mode == "revise"
    budgets = [
        item for item in plan.constraints
        if isinstance(item, BudgetConstraint)
    ]
    assert len(budgets) == 1
    assert budgets[0].minimum is None
    assert budgets[0].maximum == Decimal("100")
    assert any(
        isinstance(item, CategoryConstraint)
        and item.value is TopicCode.SERUM
        for item in plan.constraints
    )
    assert any(
        isinstance(item, SkinConstraint)
        and item.value is SkinTarget.SENSITIVE
        for item in plan.constraints
    )
    assert any(
        isinstance(item, EfficacyConstraint)
        and item.value is EfficacyTarget.REPAIR
        for item in plan.constraints
    )
    assert any(
        isinstance(item, ExclusionConstraint)
        and item.value == "酒精"
        for item in plan.constraints
    )
    assert original.budget_maximum == Decimal("500")


def test_revision_clears_old_budget_minimum() -> None:
    context = query_context().model_copy(
        update={"budget_minimum": Decimal("300")},
        deep=True,
    )

    plan = plan_budget_revision(
        parse_budget_revision("预算改成100元"),
        query_context=context,
        request_version=1,
        snapshot_version=1,
        revision_confirmation=_budget_proof(),
    )

    assert plan is not None
    budget = next(
        item for item in plan.constraints
        if isinstance(item, BudgetConstraint)
    )
    assert budget.minimum is None
    assert budget.maximum == Decimal("100")


def test_missing_snapshot_and_stale_version_clarify() -> None:
    missing = plan_budget_revision(
        parse_budget_revision("预算降到100元呢"),
        query_context=None,
        request_version=0,
        snapshot_version=None,
    )
    assert missing is not None
    assert missing.mode == "clarify"
    assert "完整推荐" in missing.clarification

    stale = plan_budget_revision(
        parse_budget_revision("预算降到100元呢"),
        query_context=query_context(),
        request_version=0,
        snapshot_version=1,
        revision_confirmation=_budget_proof(),
    )
    assert stale is not None
    assert stale.mode == "clarify"
    assert "状态已变化" in stale.clarification


def test_invalid_and_unsupported_revision_clarify() -> None:
    invalid = plan_budget_revision(
        parse_budget_revision("预算改成0元"),
        query_context=query_context(),
        request_version=1,
        snapshot_version=1,
    )
    assert invalid is not None
    assert invalid.mode == "clarify"
    assert "大于 0" in invalid.clarification

    unsupported = plan_budget_revision(
        BudgetRevisionDraft(issue="unsupported_budget_revision"),
        query_context=query_context(),
        request_version=1,
        snapshot_version=1,
    )
    assert unsupported is not None
    assert unsupported.mode == "clarify"
    assert "明确上限" in unsupported.clarification


def test_none_draft_is_not_a_revision_plan() -> None:
    assert plan_budget_revision(
        None,
        query_context=query_context(),
        request_version=1,
        snapshot_version=1,
    ) is None
