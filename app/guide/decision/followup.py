from decimal import Decimal

from app.guide.decision.contracts import (
    FactState,
    FollowupDecisionResult,
)
from app.guide.decision.ports import DecisionFactPort
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.intent.contracts import FollowupPlan
from app.guide.understanding.contracts import FollowupAction


def decide_followup(
    facts: DecisionFactPort,
    snapshot: ConversationSnapshot,
    plan: FollowupPlan,
) -> FollowupDecisionResult:
    if snapshot.recommendation_slot is None:
        raise ValueError("followup requires recommendation slot")
    candidates = snapshot.recommendation_slot.candidates
    source_ids = [item.product_id for item in candidates]
    if plan.mode != "followup" or plan.action is None:
        raise ValueError("decision requires followup plan")
    if plan.action is FollowupAction.ORDINAL_REFERENCE:
        assert plan.ordinal is not None
        selected = candidates[plan.ordinal - 1].product_id
        return FollowupDecisionResult(
            action=plan.action,
            ordinal=plan.ordinal,
            status="selected",
            source_candidate_ids=source_ids,
            selected_product_ids=[selected],
            evidence_refs=[f"ordinal={plan.ordinal}"],
        )

    priced: list[tuple[int, Decimal]] = []
    for product_id in source_ids:
        product = facts.get_decision_facts(product_id)
        if (
            product.price_state is FactState.KNOWN
            and product.price is not None
        ):
            priced.append((product_id, product.price))
    if not priced:
        return FollowupDecisionResult(
            action=plan.action,
            ordinal=None,
            status="insufficient_evidence",
            source_candidate_ids=source_ids,
            selected_product_ids=[],
            evidence_refs=["price_evidence=unavailable"],
        )
    minimum = min(price for _, price in priced)
    selected_ids = [
        product_id
        for product_id, price in priced
        if price == minimum
    ]
    return FollowupDecisionResult(
        action=plan.action,
        ordinal=None,
        status="tied" if len(selected_ids) > 1 else "selected",
        source_candidate_ids=source_ids,
        selected_product_ids=selected_ids,
        evidence_refs=[f"price_min={minimum}"],
    )
