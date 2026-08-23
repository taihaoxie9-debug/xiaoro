from __future__ import annotations

from typing import Literal

from app.guide.decision.contracts import DecisionResult, WinnerStatus
from app.guide.presentation.sse_events import ClarifyData
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.turn_meaning_contracts import RecommendationMode


FIT_SELECTION_CLARIFICATION = (
    "现有公开事实还不能支持唯一选择。"
    "请补充一个更明确的功效、肤感或使用场景，"
    "或者改为查看多款方向。"
)


class FitSelectionEvidenceGap(RuntimeError):
    pass


def fit_selection_clarification_data(
    *,
    decision: DecisionResult,
    gap_stage: Literal[
        "decision_selection",
        "public_fact_projection",
    ],
    public_fact_count: int = 0,
) -> ClarifyData:
    return ClarifyData(
        question=FIT_SELECTION_CLARIFICATION,
        clarification_code=ClarificationCode.GOAL,
        intended_responsibility="recommendation",
        intended_recommendation_mode="fit",
        clarification_basis="fit_selection_evidence_gap",
        fit_gap_stage=gap_stage,
        fit_decision_status=decision.winner_status.value,
        fit_candidate_count=len(decision.ordered_product_ids),
        fit_evidence_ref_count=len(decision.evidence_refs),
        fit_public_fact_count=public_fact_count,
    )


def fit_selection_is_unresolved(
    *,
    recommendation_mode: RecommendationMode | None,
    decision: DecisionResult,
) -> bool:
    return (
        recommendation_mode == "fit"
        and decision.winner_status is not WinnerStatus.SELECTED
    )


def require_fit_presentation_facts(
    *,
    recommendation_mode: RecommendationMode | None,
    detail_fact_counts: tuple[int, ...],
) -> None:
    if recommendation_mode != "fit":
        return
    if len(detail_fact_counts) != 1:
        raise FitSelectionEvidenceGap(
            "fit recommendation requires one presentation slot"
        )
    if detail_fact_counts[0] == 0:
        raise FitSelectionEvidenceGap(
            "fit recommendation requires public winner facts"
        )
