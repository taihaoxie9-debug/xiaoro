from __future__ import annotations

from decimal import Decimal

from app.guide.decision.contracts import DecisionResult, WinnerStatus
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    SkinConstraint,
    TaskPlan,
)
from app.guide.presentation.topic_labels import topic_label
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
)


_SKIN_LABELS = {
    SkinTarget.OILY_SENSITIVE: "油敏肌",
    SkinTarget.OILY: "油皮",
    SkinTarget.DRY: "干皮",
    SkinTarget.COMBINATION: "混合肌",
    SkinTarget.SENSITIVE: "敏感肌",
    SkinTarget.NORMAL: "中性肌",
}


def build_skin_revision_message(
    task: TaskPlan,
    decision: DecisionResult,
) -> str:
    skin = _required(task, SkinConstraint)
    inherited = _inherited_context_label(task)
    prefix = (
        f"已把肤质调整为“{_SKIN_LABELS[skin.value]}”，"
        f"沿用“{inherited}”。"
    )
    if decision.winner_status is WinnerStatus.NO_CANDIDATE:
        return (
            f"{prefix}换成这个肤质后，暂时没有找到同时合适的商品，"
            "前面已经挑出的商品先保留，方便你继续比较。"
        )
    if (
        decision.winner_status
        is WinnerStatus.INSUFFICIENT_FOR_WINNER
    ):
        has_unknown_skin = any(
            item.kind == "skin_match_unknown"
            for item in decision.risk_findings
        )
        if has_unknown_skin:
            evidence_note = (
                f"{_SKIN_LABELS[skin.value]}适配证据仍不足，"
                "暂不把它表述为唯一最适合。"
            )
        else:
            evidence_note = (
                "现有业务证据仍不足，暂不强行指定唯一推荐。"
            )
        return (
            f"{prefix}现有审核事实下保留 "
            f"{len(decision.ordered_product_ids)} 款，"
            f"但{evidence_note}"
        )
    return (
        f"{prefix}已按新肤质重新执行审核事实筛选和稳定排序。"
    )


def _inherited_context_label(task: TaskPlan) -> str:
    category = _required(task, CategoryConstraint)
    budget = _optional(task, BudgetConstraint)
    efficacy = _optional(task, EfficacyConstraint)
    parts = []
    if budget is not None:
        parts.append(_budget_label(budget))
    if (
        efficacy is not None
        and efficacy.value is EfficacyTarget.REPAIR
    ):
        parts.append("修护")
    parts.append(topic_label(category.value))
    return "".join(parts)


def _budget_label(budget: BudgetConstraint) -> str:
    if (
        budget.minimum is not None
        and budget.maximum is not None
    ):
        return (
            f"¥{_format_amount(budget.minimum)}-"
            f"¥{_format_amount(budget.maximum)}"
        )
    if budget.maximum is not None:
        return f"¥{_format_amount(budget.maximum)} 内"
    assert budget.minimum is not None
    return f"¥{_format_amount(budget.minimum)} 起"


def _required(task: TaskPlan, constraint_type: type):
    value = _optional(task, constraint_type)
    if value is None:
        raise ValueError(f"missing {constraint_type.__name__}")
    return value


def _optional(task: TaskPlan, constraint_type: type):
    values = [
        item for item in task.constraints
        if isinstance(item, constraint_type)
    ]
    if len(values) > 1:
        raise ValueError(f"duplicate {constraint_type.__name__}")
    return values[0] if values else None


def _format_amount(value: Decimal) -> str:
    return format(value.normalize(), "f")
