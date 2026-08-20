from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256

import pytest
from pydantic import ValidationError


AUDIT_LOCATOR = (
    "docs/audits/phase2-scenario-feedback/review_source_audit.md"
)


def review_api():
    from app.guide.retrieval.review_contracts import (
        ApprovedReviewEvidence,
        ReviewSourceCatalog,
    )
    from app.guide.retrieval.review_reader import (
        ReviewCatalogMismatchError,
        ReviewEvidenceReader,
        ReviewProductOwnershipError,
        ReviewSourceConflictError,
        UnknownReviewSourceError,
    )

    return (
        ApprovedReviewEvidence,
        ReviewSourceCatalog,
        ReviewEvidenceReader,
        ReviewCatalogMismatchError,
        ReviewProductOwnershipError,
        ReviewSourceConflictError,
        UnknownReviewSourceError,
    )


def test_approved_review_evidence_requires_auditable_provenance() -> None:
    ApprovedReviewEvidence, *_ = review_api()
    evidence = _evidence(
        ApprovedReviewEvidence,
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="质地清爽，使用后没有黏腻感。",
    )

    assert evidence.source_id == "review_tmall_501_20260604_a"
    assert evidence.product_id == 501
    assert evidence.source_kind == "platform_consumer_review"
    assert evidence.source_locator.endswith(
        "#review=review_tmall_501_20260604_a"
    )
    assert evidence.content_kind == "verbatim"
    assert evidence.content == "质地清爽，使用后没有黏腻感。"
    assert evidence.content_sha256 == sha256(
        evidence.content.encode("utf-8")
    ).hexdigest()
    assert evidence.collected_at == datetime(
        2026,
        8,
        9,
        2,
        0,
        tzinfo=UTC,
    )
    assert evidence.collection_version == "tmall-export-2026-08-09-v1"


@pytest.mark.parametrize(
    "forbidden_field",
    (
        "rating",
        "review_count",
        "product_description",
        "user_review_notes",
        "llm_summary",
    ),
)
def test_review_evidence_rejects_non_review_substitutes(
    forbidden_field: str,
) -> None:
    ApprovedReviewEvidence, *_ = review_api()
    payload = _evidence(
        ApprovedReviewEvidence,
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="原始消费者评论。",
    ).model_dump()
    payload[forbidden_field] = "not review evidence"

    with pytest.raises(
        ValidationError,
        match="Extra inputs are not permitted",
    ):
        ApprovedReviewEvidence.model_validate(payload)


def test_review_evidence_rejects_unverifiable_content_hash() -> None:
    ApprovedReviewEvidence, *_ = review_api()
    payload = _evidence(
        ApprovedReviewEvidence,
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="原始消费者评论。",
    ).model_dump()
    payload["content_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="content sha256 mismatch"):
        ApprovedReviewEvidence.model_validate(payload)


def test_review_evidence_requires_timezone_aware_collection_time() -> None:
    ApprovedReviewEvidence, *_ = review_api()
    payload = _evidence(
        ApprovedReviewEvidence,
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="原始消费者评论。",
    ).model_dump()
    payload["collected_at"] = datetime(2026, 8, 9, 2, 0)

    with pytest.raises(ValidationError, match="timezone-aware"):
        ApprovedReviewEvidence.model_validate(payload)


def test_duplicate_sources_are_idempotent_and_order_is_stable() -> None:
    (
        ApprovedReviewEvidence,
        ReviewSourceCatalog,
        ReviewEvidenceReader,
        *_,
    ) = review_api()
    first = _evidence(
        ApprovedReviewEvidence,
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="第一条原始评论。",
    )
    second = _evidence(
        ApprovedReviewEvidence,
        source_id="review_tmall_501_20260605_b",
        product_id=501,
        content="第二条原始评论。",
    )
    catalog = _catalog(ReviewSourceCatalog, approved_source_count=2)

    outputs = [
        ReviewEvidenceReader(
            catalog=catalog,
            evidence=records,
        ).read(product_id=501)
        for records in (
            [second, first, first],
            [first, second, first],
            [first, first, second],
        )
    ]

    assert [
        [item.source_id for item in result.evidence]
        for result in outputs
    ] == [
        [
            "review_tmall_501_20260604_a",
            "review_tmall_501_20260605_b",
        ]
    ] * 3
    assert all(
        result.verified_absence is None
        for result in outputs
    )


def test_equivalent_provenance_timestamps_serialize_stably() -> None:
    (
        ApprovedReviewEvidence,
        ReviewSourceCatalog,
        ReviewEvidenceReader,
        *_,
    ) = review_api()
    utc_record = _evidence(
        ApprovedReviewEvidence,
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="同一条原始评论。",
    )
    offset_payload = utc_record.model_dump()
    offset_payload["collected_at"] = datetime(
        2026,
        8,
        9,
        10,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )
    offset_record = ApprovedReviewEvidence.model_validate(
        offset_payload
    )
    catalog = _catalog(ReviewSourceCatalog, approved_source_count=1)

    outputs = [
        ReviewEvidenceReader(
            catalog=catalog,
            evidence=records,
        ).read(product_id=501)
        for records in (
            [utc_record, offset_record],
            [offset_record, utc_record],
        )
    ]

    assert outputs[0].model_dump(mode="json") == outputs[1].model_dump(
        mode="json"
    )


def test_conflicting_duplicate_source_is_rejected() -> None:
    (
        ApprovedReviewEvidence,
        ReviewSourceCatalog,
        ReviewEvidenceReader,
        _,
        _,
        ReviewSourceConflictError,
        _,
    ) = review_api()
    first = _evidence(
        ApprovedReviewEvidence,
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="第一版原始评论。",
    )
    changed = _evidence(
        ApprovedReviewEvidence,
        source_id=first.source_id,
        product_id=501,
        content="同一 source ID 下被替换的评论。",
    )

    with pytest.raises(
        ReviewSourceConflictError,
        match=first.source_id,
    ):
        ReviewEvidenceReader(
            catalog=_catalog(
                ReviewSourceCatalog,
                approved_source_count=1,
            ),
            evidence=[first, changed],
        )


def test_duplicate_source_with_different_product_is_rejected() -> None:
    (
        ApprovedReviewEvidence,
        ReviewSourceCatalog,
        ReviewEvidenceReader,
        _,
        ReviewProductOwnershipError,
        *_,
    ) = review_api()
    source_id = "review_tmall_501_20260604_a"

    with pytest.raises(
        ReviewProductOwnershipError,
        match=source_id,
    ):
        ReviewEvidenceReader(
            catalog=_catalog(
                ReviewSourceCatalog,
                approved_source_count=1,
            ),
            evidence=[
                _evidence(
                    ApprovedReviewEvidence,
                    source_id=source_id,
                    product_id=501,
                    content="商品 501 的评论。",
                ),
                _evidence(
                    ApprovedReviewEvidence,
                    source_id=source_id,
                    product_id=502,
                    content="错误归属到商品 502 的评论。",
                ),
            ],
        )


def test_requested_source_must_belong_to_requested_product() -> None:
    (
        ApprovedReviewEvidence,
        ReviewSourceCatalog,
        ReviewEvidenceReader,
        _,
        ReviewProductOwnershipError,
        *_,
    ) = review_api()
    evidence = _evidence(
        ApprovedReviewEvidence,
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="商品 501 的评论。",
    )
    reader = ReviewEvidenceReader(
        catalog=_catalog(
            ReviewSourceCatalog,
            approved_source_count=1,
        ),
        evidence=[evidence],
    )

    with pytest.raises(
        ReviewProductOwnershipError,
        match=evidence.source_id,
    ):
        reader.read(
            product_id=502,
            source_ids=[evidence.source_id],
        )


def test_unknown_requested_source_is_rejected() -> None:
    (
        _,
        ReviewSourceCatalog,
        ReviewEvidenceReader,
        _,
        _,
        _,
        UnknownReviewSourceError,
    ) = review_api()
    reader = ReviewEvidenceReader(
        catalog=_catalog(
            ReviewSourceCatalog,
            approved_source_count=0,
        ),
        evidence=[],
    )

    with pytest.raises(
        UnknownReviewSourceError,
        match="review_missing",
    ):
        reader.read(
            product_id=501,
            source_ids=["review_missing"],
        )


def test_empty_requested_source_selection_fails_closed() -> None:
    from app.guide.retrieval.review_contracts import ReviewSourceCatalog
    from app.guide.retrieval.review_reader import (
        ReviewEvidenceError,
        ReviewEvidenceReader,
    )

    reader = ReviewEvidenceReader(
        catalog=_catalog(
            ReviewSourceCatalog,
            approved_source_count=0,
        ),
        evidence=[],
    )

    with pytest.raises(
        ReviewEvidenceError,
        match="source_ids must not be empty",
    ):
        reader.read(product_id=501, source_ids=[])


def test_catalog_count_mismatch_fails_closed() -> None:
    (
        ApprovedReviewEvidence,
        ReviewSourceCatalog,
        ReviewEvidenceReader,
        ReviewCatalogMismatchError,
        *_,
    ) = review_api()

    with pytest.raises(
        ReviewCatalogMismatchError,
        match="approved source count",
    ):
        ReviewEvidenceReader(
            catalog=_catalog(
                ReviewSourceCatalog,
                approved_source_count=2,
            ),
            evidence=[
                _evidence(
                    ApprovedReviewEvidence,
                    source_id="review_tmall_501_20260604_a",
                    product_id=501,
                    content="唯一批准评论。",
                )
            ],
        )


def test_no_approved_source_returns_verified_absence_without_summary() -> None:
    (
        _,
        ReviewSourceCatalog,
        ReviewEvidenceReader,
        *_,
    ) = review_api()
    catalog = _catalog(
        ReviewSourceCatalog,
        approved_source_count=0,
    )

    result = ReviewEvidenceReader(
        catalog=catalog,
        evidence=[],
    ).read(product_id=58)

    assert result.product_id == 58
    assert result.evidence == []
    assert result.verified_absence is not None
    assert result.verified_absence.reason == (
        "no_approved_review_sources_for_product"
    )
    assert result.verified_absence.catalog_id == catalog.catalog_id
    assert result.verified_absence.catalog_version == (
        catalog.catalog_version
    )
    assert result.verified_absence.audit_locator == AUDIT_LOCATOR
    assert "summary" not in result.model_dump()


def _evidence(
    model,
    *,
    source_id: str,
    product_id: int,
    content: str,
):
    return model(
        source_id=source_id,
        product_id=product_id,
        source_kind="platform_consumer_review",
        source_locator=(
            f"https://reviews.example/items/{product_id}"
            f"#review={source_id}"
        ),
        content_kind="verbatim",
        content=content,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
        collected_at=datetime(2026, 8, 9, 2, 0, tzinfo=UTC),
        collection_version="tmall-export-2026-08-09-v1",
    )


def _catalog(model, *, approved_source_count: int):
    return model(
        catalog_id="phase2-review-source-audit",
        catalog_version="git-6123c7b-assets-v1",
        audit_locator=AUDIT_LOCATOR,
        audited_at=datetime(2026, 8, 9, 3, 0, tzinfo=UTC),
        approved_source_count=approved_source_count,
    )
