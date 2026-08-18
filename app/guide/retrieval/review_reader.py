from __future__ import annotations

from collections.abc import Iterable

from app.guide.retrieval.review_contracts import (
    ApprovedReviewEvidence,
    ReviewReadResult,
    ReviewSourceCatalog,
    ReviewVerifiedAbsence,
)


class ReviewEvidenceError(ValueError):
    pass


class ReviewCatalogMismatchError(ReviewEvidenceError):
    pass


class ReviewProductOwnershipError(ReviewEvidenceError):
    pass


class ReviewSourceConflictError(ReviewEvidenceError):
    pass


class UnknownReviewSourceError(ReviewEvidenceError):
    pass


class ReviewEvidenceReader:
    def __init__(
        self,
        *,
        catalog: ReviewSourceCatalog,
        evidence: Iterable[ApprovedReviewEvidence],
    ) -> None:
        self._catalog = catalog.model_copy(deep=True)
        self._by_source_id: dict[str, ApprovedReviewEvidence] = {}

        for item in evidence:
            stored = item.model_copy(deep=True)
            existing = self._by_source_id.get(stored.source_id)
            if existing is None:
                self._by_source_id[stored.source_id] = stored
                continue
            if existing.product_id != stored.product_id:
                raise ReviewProductOwnershipError(
                    f"{stored.source_id}: conflicting product ownership"
                )
            if existing != stored:
                raise ReviewSourceConflictError(
                    f"{stored.source_id}: conflicting review source"
                )

        if (
            len(self._by_source_id)
            != self._catalog.approved_source_count
        ):
            raise ReviewCatalogMismatchError(
                "approved source count does not match catalog"
            )

    @property
    def approved_source_count(self) -> int:
        return self._catalog.approved_source_count

    def read(
        self,
        *,
        product_id: int,
        source_ids: Iterable[str] | None = None,
    ) -> ReviewReadResult:
        if source_ids is None:
            selected = [
                item
                for item in self._by_source_id.values()
                if item.product_id == product_id
            ]
        else:
            requested_ids = sorted(set(source_ids))
            if not requested_ids:
                raise ReviewEvidenceError(
                    "source_ids must not be empty"
                )
            selected = [
                self._owned_source(product_id, source_id)
                for source_id in requested_ids
            ]

        evidence = [
            item.model_copy(deep=True)
            for item in sorted(
                selected,
                key=lambda item: item.source_id,
            )
        ]
        if evidence:
            absence = None
        else:
            absence = ReviewVerifiedAbsence(
                product_id=product_id,
                catalog_id=self._catalog.catalog_id,
                catalog_version=self._catalog.catalog_version,
                audit_locator=self._catalog.audit_locator,
            )
        return ReviewReadResult(
            product_id=product_id,
            evidence=evidence,
            verified_absence=absence,
        )

    def _owned_source(
        self,
        product_id: int,
        source_id: str,
    ) -> ApprovedReviewEvidence:
        try:
            item = self._by_source_id[source_id]
        except KeyError as exc:
            raise UnknownReviewSourceError(
                f"{source_id}: unknown review source"
            ) from exc
        if item.product_id != product_id:
            raise ReviewProductOwnershipError(
                f"{source_id}: source does not belong to product "
                f"{product_id}"
            )
        return item
