from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    SkinConstraint,
    SkinRevisionPlan,
)
from app.guide.intent.skin_revision_planning import plan_skin_revision
from app.guide.understanding.contracts import (
    EfficacyTarget,
    ExactRevisionConfirmation,
    ExactRevisionOperation,
    ExactRevisionTarget,
    SkinRevisionDraft,
    SkinTarget,
    SourceSpan,
    TopicCode,
)


def query_context() -> RecommendationQueryContext:
    return RecommendationQueryContext(
        category="serum",
        budget_minimum=Decimal("300"),
        budget_maximum=Decimal("500"),
        skin="oily",
        efficacy="repair",
        exclusions=["酒精", "香精"],
    )


def _skin_proof() -> ExactRevisionConfirmation:
    return ExactRevisionConfirmation(
        operation=ExactRevisionOperation.REVISE_CONSTRAINT,
        target=ExactRevisionTarget.SKIN,
        source_span=SourceSpan(start=0, end=7),
        affected_value=SkinTarget.SENSITIVE.value,
    )


def test_skin_revision_without_exact_proof_clarifies() -> None:
    plan = plan_skin_revision(
        SkinRevisionDraft(target=SkinTarget.SENSITIVE),
        query_context=query_context(),
        request_version=1,
        snapshot_version=1,
        revision_confirmation=None,
    )

    assert plan is not None
    assert plan.mode == "clarify"
    assert "缺少精确修改证明" in plan.clarification


def test_replaces_only_skin_and_preserves_query_context() -> None:
    context = query_context()
    plan = plan_skin_revision(
        SkinRevisionDraft(target=SkinTarget.SENSITIVE),
        query_context=context,
        request_version=1,
        snapshot_version=1,
        revision_confirmation=_skin_proof(),
    )

    assert plan is not None
    assert plan.mode == "revise"
    assert plan.clarification is None
    categories = [
        item
        for item in plan.constraints
        if isinstance(item, CategoryConstraint)
    ]
    budgets = [
        item
        for item in plan.constraints
        if isinstance(item, BudgetConstraint)
    ]
    skins = [
        item
        for item in plan.constraints
        if isinstance(item, SkinConstraint)
    ]
    efficacies = [
        item
        for item in plan.constraints
        if isinstance(item, EfficacyConstraint)
    ]
    exclusions = [
        item
        for item in plan.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    assert [item.value for item in categories] == [TopicCode.SERUM]
    assert len(budgets) == 1
    assert budgets[0].minimum == Decimal("300")
    assert budgets[0].maximum == Decimal("500")
    assert [item.value for item in skins] == [SkinTarget.SENSITIVE]
    assert [item.value for item in efficacies] == [EfficacyTarget.REPAIR]
    assert [item.value for item in exclusions] == ["酒精", "香精"]
    assert context.skin == "oily"


def test_adds_one_skin_when_context_has_no_skin() -> None:
    context = RecommendationQueryContext(
        category="sunscreen",
        budget_minimum=None,
        budget_maximum=None,
        skin=None,
        efficacy=None,
        exclusions=[],
    )
    plan = plan_skin_revision(
        SkinRevisionDraft(target=SkinTarget.OILY_SENSITIVE),
        query_context=context,
        request_version=2,
        snapshot_version=2,
        revision_confirmation=_skin_proof(),
    )

    assert plan is not None
    assert plan.mode == "revise"
    assert len(plan.constraints) == 2
    assert isinstance(plan.constraints[0], CategoryConstraint)
    assert isinstance(plan.constraints[1], SkinConstraint)
    assert plan.constraints[1].value is SkinTarget.OILY_SENSITIVE


@pytest.mark.parametrize(
    ("context", "snapshot_version"),
    [
        (None, None),
        (query_context(), None),
    ],
)
def test_missing_snapshot_clarifies(
    context: RecommendationQueryContext | None,
    snapshot_version: int | None,
) -> None:
    plan = plan_skin_revision(
        SkinRevisionDraft(target=SkinTarget.DRY),
        query_context=context,
        request_version=1,
        snapshot_version=snapshot_version,
    )

    assert plan is not None
    assert plan.mode == "clarify"
    assert plan.constraints == []
    assert "完整推荐" in plan.clarification


def test_stale_version_clarifies() -> None:
    plan = plan_skin_revision(
        SkinRevisionDraft(target=SkinTarget.DRY),
        query_context=query_context(),
        request_version=0,
        snapshot_version=1,
    )

    assert plan is not None
    assert plan.mode == "clarify"
    assert plan.constraints == []
    assert "状态已变化" in plan.clarification


@pytest.mark.parametrize(
    ("draft_values", "clarification"),
    [
        ({}, "明确"),
        ({"issue": "unsupported_skin_revision"}, "明确"),
        ({"issue": "compound_revision"}, "一次只修改"),
    ],
)
def test_missing_target_or_issue_clarifies(
    draft_values: dict[str, str],
    clarification: str,
) -> None:
    plan = plan_skin_revision(
        SkinRevisionDraft(**draft_values),
        query_context=query_context(),
        request_version=1,
        snapshot_version=1,
    )

    assert plan is not None
    assert plan.mode == "clarify"
    assert plan.constraints == []
    assert clarification in plan.clarification


def test_none_draft_is_not_a_skin_revision_plan() -> None:
    assert plan_skin_revision(
        None,
        query_context=query_context(),
        request_version=1,
        snapshot_version=1,
    ) is None


def test_skin_revision_plan_enforces_mode_contract() -> None:
    with pytest.raises(ValidationError, match="constraints"):
        SkinRevisionPlan(
            mode="revise",
            constraints=[],
            clarification=None,
        )
