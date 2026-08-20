from __future__ import annotations

from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.constraint_transitions import (
    BoundConstraint,
    reduce_constraint_state,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    BudgetRevisionPlan,
)
from app.guide.understanding.contracts import (
    BudgetRevisionDraft,
    ExactRevisionConfirmation,
    SourceSpan,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


def plan_budget_revision(
    draft: BudgetRevisionDraft | None,
    *,
    query_context: RecommendationQueryContext | None,
    request_version: int,
    snapshot_version: int | None,
    revision_confirmation: ExactRevisionConfirmation | None = None,
) -> BudgetRevisionPlan | None:
    if draft is None:
        return None
    if draft.issue == "invalid_budget":
        return BudgetRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "预算必须是大于 0 的阿拉伯数字。"
            ),
            clarification_code=ClarificationCode.BUDGET,
        )
    if draft.issue == "unsupported_budget_revision":
        return BudgetRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "当前预算追问先支持明确上限，"
                "例如“预算改成100元以内”。"
            ),
            clarification_code=ClarificationCode.BUDGET,
        )
    if query_context is None or snapshot_version is None:
        return BudgetRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "我找不到可继承的最近筛选条件，"
                "请先发起一次完整推荐。"
            ),
            clarification_code=ClarificationCode.REFERENCE,
        )
    if request_version != snapshot_version:
        return BudgetRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "会话状态已变化，请基于最新结果重试。"
            ),
            clarification_code=ClarificationCode.REFERENCE,
        )
    assert draft.maximum is not None
    source_span = (
        revision_confirmation.source_span
        if revision_confirmation is not None
        else SourceSpan(start=0, end=1)
    )
    result = reduce_constraint_state(
        previous=query_context,
        current_constraints=(
            BoundConstraint(
                constraint=BudgetConstraint(
                    minimum=None,
                    maximum=draft.maximum,
                ),
                source_span=source_span,
                authority="exact",
            ),
        ),
        revision_confirmations=(
            ()
            if revision_confirmation is None
            else (revision_confirmation,)
        ),
        goal=UnderstandingGoal.FOLLOWUP,
    )
    if result.issues:
        return BudgetRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=result.issues[0].detail,
            clarification_code=ClarificationCode.BUDGET,
        )
    return BudgetRevisionPlan(
        mode="revise",
        constraints=[
            item.model_copy(deep=True)
            for item in result.constraints
        ],
        clarification=None,
    )
