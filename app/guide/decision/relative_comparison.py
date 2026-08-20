from __future__ import annotations

from typing import Literal

from app.guide.decision.contracts import (
    DecisionProductFacts,
    FactState,
    RelativeComparisonResult,
)
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptFact,
)
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)


def compare_relative_candidate(
    *,
    candidate: DecisionProductFacts,
    baseline: DecisionProductFacts,
    field_key: str,
    concept_id: str | None,
    direction: Literal["higher", "lower"],
    reader: SelectionParentConceptReader | None,
) -> RelativeComparisonResult:
    if not isinstance(candidate, DecisionProductFacts):
        raise TypeError("candidate must be DecisionProductFacts")
    if not isinstance(baseline, DecisionProductFacts):
        raise TypeError("baseline must be DecisionProductFacts")
    if candidate.category_profile is not baseline.category_profile:
        return _result(
            candidate,
            baseline,
            status="evidence_gap",
            kind="unsupported",
        )
    if field_key == "price" and concept_id is None:
        return _compare_price(
            candidate,
            baseline,
            direction=direction,
        )
    if concept_id is None or reader is None:
        return _result(
            candidate,
            baseline,
            status="evidence_gap",
            kind="unsupported",
        )
    if not concept_id.startswith(f"{field_key}."):
        raise ValueError("relative concept must be field-scoped")

    candidate_fact = _concept_fact(
        reader,
        candidate,
        concept_id=concept_id,
    )
    baseline_fact = _concept_fact(
        reader,
        baseline,
        concept_id=concept_id,
    )
    if candidate_fact is None:
        return _result(
            candidate,
            baseline,
            status="evidence_gap",
            kind="unsupported",
            source_refs=(
                baseline_fact.source_refs
                if baseline_fact is not None
                else ()
            ),
        )
    source_refs = tuple(sorted({
        *candidate_fact.source_refs,
        *(
            baseline_fact.source_refs
            if baseline_fact is not None
            else ()
        ),
    }))
    if (
        baseline_fact is not None
        and candidate_fact.comparability == "ordered"
        and baseline_fact.comparability == "ordered"
        and candidate_fact.order_value is not None
        and baseline_fact.order_value is not None
    ):
        better = _is_better(
            candidate_fact.order_value,
            baseline_fact.order_value,
            direction=direction,
        )
        return _result(
            candidate,
            baseline,
            status="better" if better else "not_better",
            kind="ordered",
            source_refs=source_refs,
            effect_claim_supported=True,
        )

    desired_stance = "supports" if direction == "higher" else "opposes"
    baseline_matches = (
        baseline_fact is not None
        and baseline_fact.stance == desired_stance
    )
    candidate_matches = candidate_fact.stance == desired_stance
    if candidate_matches and not baseline_matches:
        return _result(
            candidate,
            baseline,
            status="better",
            kind="better_preference_match",
            source_refs=source_refs,
        )
    if (
        candidate_matches
        and baseline_matches
        and baseline_fact is not None
        and candidate_fact.rank_strength
        > baseline_fact.rank_strength
    ):
        return _result(
            candidate,
            baseline,
            status="better",
            kind="better_evidence_support",
            source_refs=source_refs,
        )
    return _result(
        candidate,
        baseline,
        status="not_better",
        kind="better_preference_match",
        source_refs=source_refs,
    )


def _compare_price(
    candidate: DecisionProductFacts,
    baseline: DecisionProductFacts,
    *,
    direction: Literal["higher", "lower"],
) -> RelativeComparisonResult:
    if (
        candidate.price_state is not FactState.KNOWN
        or baseline.price_state is not FactState.KNOWN
        or candidate.price is None
        or baseline.price is None
    ):
        return _result(
            candidate,
            baseline,
            status="evidence_gap",
            kind="numeric",
            source_refs=tuple(sorted({
                *candidate.price_source_refs,
                *baseline.price_source_refs,
            })),
        )
    return _result(
        candidate,
        baseline,
        status=(
            "better"
            if _is_better(
                candidate.price,
                baseline.price,
                direction=direction,
            )
            else "not_better"
        ),
        kind="numeric",
        source_refs=tuple(sorted({
            *candidate.price_source_refs,
            *baseline.price_source_refs,
        })),
        effect_claim_supported=True,
    )


def _concept_fact(
    reader: SelectionParentConceptReader,
    product: DecisionProductFacts,
    *,
    concept_id: str,
) -> SelectionConceptFact | None:
    return next(
        (
            item
            for item in reader.project(product.selection_facts)
            if item.concept_id == concept_id
        ),
        None,
    )


def _is_better(
    candidate,
    baseline,
    *,
    direction: Literal["higher", "lower"],
) -> bool:
    return (
        candidate > baseline
        if direction == "higher"
        else candidate < baseline
    )


def _result(
    candidate: DecisionProductFacts,
    baseline: DecisionProductFacts,
    *,
    status: Literal["better", "not_better", "evidence_gap"],
    kind: Literal[
        "numeric",
        "ordered",
        "better_preference_match",
        "better_evidence_support",
        "unsupported",
    ],
    source_refs: tuple[str, ...] = (),
    effect_claim_supported: bool = False,
) -> RelativeComparisonResult:
    return RelativeComparisonResult(
        candidate_product_id=candidate.product_id,
        baseline_product_id=baseline.product_id,
        status=status,
        relation_kind=kind,
        source_refs=source_refs,
        effect_claim_supported=effect_claim_supported,
    )


__all__ = [
    "RelativeComparisonResult",
    "compare_relative_candidate",
]
