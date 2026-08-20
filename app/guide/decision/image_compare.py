from typing import Protocol

from app.guide.decision.contracts import (
    DecisionProductFacts,
    DecisionResult,
    FactState,
    WinnerStatus,
)
from app.guide.decision.image_compare_contracts import (
    ImageCompareDecisionInput,
    ImageCompareDecisionItem,
    ImageCompareOutcome,
    ImageCompareDecisionReference,
    ImageCompareDecisionResult,
    ImageCompareEvaluatedPriceFact,
)
from app.guide.decision.recommendation import decide_recommendation
from app.guide.intent.contracts import CategoryConstraint
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult


class ImageCompareDecisionPort(Protocol):
    def decide(
        self,
        request: ImageCompareDecisionInput,
    ) -> ImageCompareDecisionResult: ...


class ImageCompareDecisionFoundation:
    def decide(
        self,
        request: ImageCompareDecisionInput,
    ) -> ImageCompareDecisionResult:
        references = _references(request)
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
        return ImageCompareDecisionResult(
            status="ready_for_outcome",
            bundle_id=request.bundle_id,
            topic=request.topic,
            references=references,
            ordered_product_ids=tuple(
                item.product_id for item in request.items
            ),
            comparison_dimensions=("price",),
            outcome=_outcome(
                request=request,
                references=references,
                decision=decision,
            ),
        )


class _RequestFacts:
    def __init__(
        self,
        items: tuple[
            ImageCompareDecisionItem,
            ImageCompareDecisionItem,
        ],
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


def _references(
    request: ImageCompareDecisionInput,
) -> tuple[
    ImageCompareDecisionReference,
    ImageCompareDecisionReference,
]:
    first, second = request.items
    return (
        _reference(first),
        _reference(second),
    )


def _reference(
    item: ImageCompareDecisionItem,
) -> ImageCompareDecisionReference:
    return ImageCompareDecisionReference(
        ordinal=item.ordinal,
        image_id=item.image_id,
        product_id=item.product_id,
    )


def _outcome(
    *,
    request: ImageCompareDecisionInput,
    references: tuple[
        ImageCompareDecisionReference,
        ImageCompareDecisionReference,
    ],
    decision: DecisionResult,
) -> ImageCompareOutcome:
    evaluated_price_facts = tuple(
        _evaluated_price_fact(item)
        for item in request.items
    )
    evidence_refs = tuple(
        source_ref
        for fact in evaluated_price_facts
        for source_ref in fact.source_refs
    )
    request_ids = {item.product_id for item in request.items}
    decision_has_both_products = (
        len(decision.ordered_product_ids) == 2
        and set(decision.ordered_product_ids) == request_ids
    )
    auditable_price_evidence = all(
        fact.state is FactState.KNOWN
        and fact.value is not None
        and bool(fact.source_refs)
        for fact in evaluated_price_facts
    )
    if not auditable_price_evidence or not decision_has_both_products:
        return ImageCompareOutcome(
            status="insufficient_evidence",
            evidence_refs=evidence_refs,
            evaluated_price_facts=evaluated_price_facts,
        )

    if (
        decision.winner_status
        is WinnerStatus.TIED_BY_BUSINESS_EVIDENCE
    ):
        return ImageCompareOutcome(
            status="tie",
            evidence_refs=evidence_refs,
            evaluated_price_facts=evaluated_price_facts,
            tie_reason="equal_price",
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
            return ImageCompareOutcome(
                status="winner",
                winner_reference=winner,
                evidence_refs=evidence_refs,
                evaluated_price_facts=evaluated_price_facts,
            )

    return ImageCompareOutcome(
        status="insufficient_evidence",
        evidence_refs=evidence_refs,
        evaluated_price_facts=evaluated_price_facts,
    )


def _evaluated_price_fact(
    item: ImageCompareDecisionItem,
) -> ImageCompareEvaluatedPriceFact:
    return ImageCompareEvaluatedPriceFact(
        reference=_reference(item),
        state=item.facts.price_state,
        value=item.facts.price,
        source_refs=item.facts.price_source_refs,
    )
