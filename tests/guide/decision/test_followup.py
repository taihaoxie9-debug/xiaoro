from decimal import Decimal

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.decision.followup import decide_followup
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.intent.contracts import FollowupPlan
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.contracts import FollowupAction


class MemoryFacts:
    def __init__(self, products: list[DecisionProductFacts]) -> None:
        self._products = {
            product.product_id: product
            for product in products
        }

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        return self._products[product_id].model_copy(deep=True)


def facts(
    product_id: int,
    price: str | None,
    price_state: FactState = FactState.KNOWN,
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SKINCARE,
        category_fields=(),
        price=Decimal(price) if price is not None else None,
        price_state=price_state,
        efficacy=None,
        efficacy_state=FactState.UNKNOWN,
        suitable_skin=None,
        suitable_skin_state=FactState.UNKNOWN,
        ingredients_present=None,
        ingredients_present_state=FactState.UNKNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
    )


def snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="s-1",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
            budget_minimum=None,
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair",
            exclusions=[],
        ),
        candidates=[
            DisplayedCandidateRef(
                product_id=91,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
            DisplayedCandidateRef(
                product_id=38,
                ordinal=2,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
        ],
    )


def four_candidate_snapshot() -> ConversationSnapshot:
    current = snapshot()
    return ConversationSnapshot(
        session_id=current.session_id,
        version=current.version,
        query_context=current.query_context,
        candidates=[
            *current.candidates,
            DisplayedCandidateRef(
                product_id=55,
                ordinal=3,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
            DisplayedCandidateRef(
                product_id=72,
                ordinal=4,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
        ],
    )


def test_ordinal_selects_exact_snapshot_position() -> None:
    result = decide_followup(
        MemoryFacts([facts(91, "88"), facts(38, "294")]),
        snapshot(),
        FollowupPlan(
            mode="followup",
            action=FollowupAction.ORDINAL_REFERENCE,
            ordinal=2,
        ),
    )
    assert result.status == "selected"
    assert result.ordinal == 2
    assert result.source_candidate_ids == [91, 38]
    assert result.selected_product_ids == [38]
    assert "ordinal=2" in result.evidence_refs


def test_fourth_ordinal_selects_exact_snapshot_position() -> None:
    result = decide_followup(
        MemoryFacts([]),
        four_candidate_snapshot(),
        FollowupPlan(
            mode="followup",
            action=FollowupAction.ORDINAL_REFERENCE,
            ordinal=4,
        ),
    )

    assert result.status == "selected"
    assert result.ordinal == 4
    assert result.source_candidate_ids == [91, 38, 55, 72]
    assert result.selected_product_ids == [72]
    assert result.evidence_refs == ["ordinal=4"]


def test_cheapest_uses_only_snapshot_prices() -> None:
    result = decide_followup(
        MemoryFacts([
            facts(91, "88"),
            facts(38, "294"),
            facts(999, "1"),
        ]),
        snapshot(),
        FollowupPlan(
            mode="followup",
            action=FollowupAction.CHEAPEST,
        ),
    )
    assert result.status == "selected"
    assert result.selected_product_ids == [91]
    assert 999 not in result.source_candidate_ids


def test_cheapest_handles_tie_and_missing_prices() -> None:
    tied = decide_followup(
        MemoryFacts([facts(91, "88"), facts(38, "88")]),
        snapshot(),
        FollowupPlan(
            mode="followup",
            action=FollowupAction.CHEAPEST,
        ),
    )
    assert tied.status == "tied"
    assert tied.selected_product_ids == [91, 38]

    unavailable = decide_followup(
        MemoryFacts([
            facts(91, None, FactState.UNKNOWN),
            facts(38, None, FactState.CONFLICT),
        ]),
        snapshot(),
        FollowupPlan(
            mode="followup",
            action=FollowupAction.CHEAPEST,
        ),
    )
    assert unavailable.status == "insufficient_evidence"
    assert unavailable.selected_product_ids == []
