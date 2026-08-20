from __future__ import annotations

from app.guide.retrieval.review_contracts import (
    ApprovedReviewEvidence,
    ReviewReadResult,
)
from app.guide.retrieval.review_summary_contracts import (
    ReviewClaimProvenance,
    ReviewSourceFact,
    ReviewSummaryResult,
    create_review_source_fact,
    create_review_synthesis,
)


class ReviewSummaryEvidenceError(ValueError):
    pass


class ReviewSummaryDuplicateSourceError(ReviewSummaryEvidenceError):
    pass


class ReviewSummarySourceConflictError(ReviewSummaryEvidenceError):
    pass


class ReviewSummaryProductOwnershipError(ReviewSummaryEvidenceError):
    pass


class ReviewSummaryStateConflictError(ReviewSummaryEvidenceError):
    pass


def build_review_summary(
    read_result: ReviewReadResult,
) -> ReviewSummaryResult | None:
    if not read_result.evidence:
        return None
    if read_result.verified_absence is not None:
        raise ReviewSummaryStateConflictError(
            "review evidence conflicts with verified absence"
        )

    ordered_evidence = sorted(
        read_result.evidence,
        key=lambda item: item.source_id,
    )
    _validate_evidence(
        product_id=read_result.product_id,
        evidence=ordered_evidence,
    )
    source_facts = tuple(
        _source_fact(item)
        for item in ordered_evidence
    )
    synthesis = create_review_synthesis(source_facts)
    return ReviewSummaryResult(
        product_id=read_result.product_id,
        source_facts=source_facts,
        synthesis=synthesis,
    )


def _validate_evidence(
    *,
    product_id: int,
    evidence: list[ApprovedReviewEvidence],
) -> None:
    previous: ApprovedReviewEvidence | None = None
    for item in evidence:
        if item.product_id != product_id:
            raise ReviewSummaryProductOwnershipError(
                f"{item.source_id}: source does not belong to product "
                f"{product_id}"
            )
        if previous is not None and item.source_id == previous.source_id:
            if item == previous:
                raise ReviewSummaryDuplicateSourceError(
                    f"{item.source_id}: duplicate review source"
                )
            raise ReviewSummarySourceConflictError(
                f"{item.source_id}: conflicting review source"
            )
        previous = item


def _source_fact(item: ApprovedReviewEvidence) -> ReviewSourceFact:
    provenance = ReviewClaimProvenance(
        source_id=item.source_id,
        product_id=item.product_id,
        source_kind=item.source_kind,
        source_locator=item.source_locator,
        content_kind=item.content_kind,
        content_sha256=item.content_sha256,
        collected_at=item.collected_at,
        collection_version=item.collection_version,
    )
    return create_review_source_fact(
        quote=item.content,
        provenance=provenance,
    )
