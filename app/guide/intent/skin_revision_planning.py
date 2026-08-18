from __future__ import annotations

from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.constraint_transitions import (
    BoundConstraint,
    reduce_constraint_state,
)
from app.guide.intent.contracts import (
    SkinConstraint,
    SkinRevisionPlan,
)
from app.guide.understanding.contracts import (
    ExactRevisionConfirmation,
    SkinRevisionDraft,
    SourceSpan,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


def plan_skin_revision(
    draft: SkinRevisionDraft | None,
    *,
    query_context: RecommendationQueryContext | None,
    request_version: int,
    snapshot_version: int | None,
    revision_confirmation: ExactRevisionConfirmation | None = None,
) -> SkinRevisionPlan | None:
    if draft is None:
        return None
    if draft.issue == "compound_revision":
        return SkinRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "一次只修改一个条件，请分别修改预算和肤质。"
            ),
            clarification_code=ClarificationCode.GOAL,
        )
    if draft.issue is not None or draft.target is None:
        return SkinRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "请明确改成敏感肌、油皮、干皮、混合肌、"
                "中性肌或油敏肌。"
            ),
            clarification_code=ClarificationCode.CONCERN,
        )
    if query_context is None or snapshot_version is None:
        return SkinRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "我找不到可继承的最近筛选条件，"
                "请先发起一次完整推荐。"
            ),
            clarification_code=ClarificationCode.REFERENCE,
        )
    if request_version != snapshot_version:
        return SkinRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "会话状态已变化，请基于最新结果重试。"
            ),
            clarification_code=ClarificationCode.REFERENCE,
        )

    source_span = (
        revision_confirmation.source_span
        if revision_confirmation is not None
        else SourceSpan(start=0, end=1)
    )
    result = reduce_constraint_state(
        previous=query_context,
        current_constraints=(
            BoundConstraint(
                constraint=SkinConstraint(value=draft.target),
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
        return SkinRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=result.issues[0].detail,
            clarification_code=ClarificationCode.CONCERN,
        )
    return SkinRevisionPlan(
        mode="revise",
        constraints=[
            item.model_copy(deep=True)
            for item in result.constraints
        ],
        clarification=None,
    )
