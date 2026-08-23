from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.intent.contracts import FollowupPlan
from app.guide.understanding.contracts import (
    FollowupAction,
    FollowupDraft,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


def plan_followup(
    draft: FollowupDraft | None,
    *,
    snapshot: ConversationSnapshot | None,
    request_version: int,
) -> FollowupPlan | None:
    if draft is None:
        return None
    if draft.issue is not None:
        return FollowupPlan(
            mode="clarify",
            clarification="当前追问只支持商品序号和最低价比较。",
            clarification_code=ClarificationCode.GOAL,
        )
    if snapshot is None:
        return FollowupPlan(
            mode="clarify",
            clarification="我还没有前面那组商品，请先发起一次推荐。",
            clarification_code=ClarificationCode.REFERENCE,
        )
    if request_version != snapshot.version:
        return FollowupPlan(
            mode="clarify",
            clarification="会话状态已变化，请基于最新结果重试。",
            clarification_code=ClarificationCode.REFERENCE,
        )
    candidates = (
        snapshot.recommendation_slot.candidates
        if snapshot.recommendation_slot is not None
        else ()
    )
    if (
        draft.action is FollowupAction.ORDINAL_REFERENCE
        and draft.ordinal is not None
        and draft.ordinal > len(candidates)
    ):
        return FollowupPlan(
            mode="clarify",
            clarification=(
                f"上一轮只展示了 {len(candidates)} 款，"
                f"没有第 {draft.ordinal} 款。"
            ),
            clarification_code=ClarificationCode.REFERENCE,
        )
    return FollowupPlan(
        mode="followup",
        action=draft.action,
        ordinal=draft.ordinal,
    )
