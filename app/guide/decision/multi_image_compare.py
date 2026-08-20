from typing import Protocol

from app.guide.decision.contracts import (
    DecisionProductFacts,
    DecisionResult,
    FactState,
    WinnerStatus,
)
from app.guide.decision.multi_image_compare_contracts import (
    MultiImageCompareDecisionInput,
    MultiImageCompareDecisionItem,
    MultiImageCompareDecisionReference,
    MultiImageCompareDecisionResult,
    MultiImageCompareEvaluatedPriceFact,
    MultiImageCompareOutcome,
    MultiImageComparisonCardIntent,
)
from app.guide.decision.recommendation import decide_recommendation
from app.guide.intent.contracts import CategoryConstraint
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult


class MultiImageCompareDecisionPort(Protocol):
    def decide(
        self,
        request: MultiImageCompareDecisionInput,
    ) -> MultiImageCompareDecisionResult: ...


class MultiImageCompareDecisionFoundation:
    def decide(
        self,
        request: MultiImageCompareDecisionInput,
    ) -> MultiImageCompareDecisionResult:
        references = tuple(
            _reference(item) for item in request.items
        )
        decision = decide_recommendation(
            _RequestFacts(request.items),
            RetrievalResult(
                candidates=[
                    CandidateRef(
                        product_id=item.product_id,
                        source="canonical",
                        canonical_category=item.canonical_category,
                        retrieval_reason="confirmed_image_identity",
                    )
                    for item in request.items
                ],
                knowledge_evidence=[],
                review_evidence=[],
                memory_evidence=[],
                missing_sources=[],
            ),
            constraints=[CategoryConstraint(value=request.topic)],
        )
        ordered_product_ids = tuple(
            item.product_id for item in request.items
        )
        return MultiImageCompareDecisionResult(
            status="ready_for_outcome",
            bundle_id=request.bundle_id,
            topic=request.topic,
            references=references,
            ordered_product_ids=ordered_product_ids,
            comparison_dimensions=("price",),
            outcome=_outcome(
                request=request,
                references=references,
                decision=decision,
            ),
            card_intent=MultiImageComparisonCardIntent(
                mode="comparison",
                visible_product_ids=ordered_product_ids,
                reason="comparison",
            ),
        )


class _RequestFacts:
    def __init__(
        self,
        items: tuple[MultiImageCompareDecisionItem, ...],
    ) -> None:
        self._facts = {
            item.product_id: item.facts.model_copy(deep=True)
            for item in items
        }

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        return self._facts[product_id].model_copy(deep=True)


def _reference(
    item: MultiImageCompareDecisionItem,
) -> MultiImageCompareDecisionReference:
    return MultiImageCompareDecisionReference(
        ordinal=item.ordinal,
        image_id=item.image_id,
        product_id=item.product_id,
    )


def _outcome(
    *,
    request: MultiImageCompareDecisionInput,
    references: tuple[MultiImageCompareDecisionReference, ...],
    decision: DecisionResult,
) -> MultiImageCompareOutcome:
    evaluated_price_facts = tuple(
        _evaluated_price_fact(item) for item in request.items
    )
    evidence_refs = tuple(
        source_ref
        for fact in evaluated_price_facts
        for source_ref in fact.source_refs
    )
    request_ids = {item.product_id for item in request.items}
    decision_has_all_products = (
        len(decision.ordered_product_ids) == len(request.items)
        and set(decision.ordered_product_ids) == request_ids
    )
    auditable_prices = all(
        fact.state is FactState.KNOWN
        and fact.value is not None
        and bool(fact.source_refs)
        for fact in evaluated_price_facts
    )
    if not auditable_prices or not decision_has_all_products:
        return MultiImageCompareOutcome(
            status="insufficient_evidence",
            evidence_refs=evidence_refs,
            evaluated_price_facts=evaluated_price_facts,
        )

    if (
        decision.winner_status
        is WinnerStatus.TIED_BY_BUSINESS_EVIDENCE
    ):
        return MultiImageCompareOutcome(
            status="tie",
            evidence_refs=evidence_refs,
            evaluated_price_facts=evaluated_price_facts,
            tie_reason="equal_lowest_price",
        )

    if (
        decision.winner_status is WinnerStatus.SELECTED
        and decision.winner_product_id is not None
    ):
        winner = next(
            (
                reference
                for reference in references
                if reference.product_id == decision.winner_product_id
            ),
            None,
        )
        if winner is not None:
            return MultiImageCompareOutcome(
                status="winner",
                winner_reference=winner,
                evidence_refs=evidence_refs,
                evaluated_price_facts=evaluated_price_facts,
            )

    return MultiImageCompareOutcome(
        status="insufficient_evidence",
        evidence_refs=evidence_refs,
        evaluated_price_facts=evaluated_price_facts,
    )


def _evaluated_price_fact(
    item: MultiImageCompareDecisionItem,
) -> MultiImageCompareEvaluatedPriceFact:
    return MultiImageCompareEvaluatedPriceFact(
        reference=_reference(item),
        state=item.facts.price_state,
        value=item.facts.price,
        source_refs=item.facts.price_source_refs,
    )
