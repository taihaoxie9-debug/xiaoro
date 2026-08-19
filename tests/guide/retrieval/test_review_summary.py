from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from pydantic import ValidationError

from app.guide.retrieval.review_contracts import (
    ApprovedReviewEvidence,
    ReviewReadResult,
    ReviewVerifiedAbsence,
)


AUDIT_LOCATOR = (
    "docs/audits/phase2-scenario-feedback/review_source_audit.md"
)
CATALOG_ID = "phase2-review-source-audit"
CATALOG_VERSION = "git-6123c7b-assets-v1"


def test_verified_absence_returns_no_review_summary() -> None:
    from app.guide.retrieval.review_summary import build_review_summary

    read_result = ReviewReadResult(
        product_id=58,
        evidence=[],
        verified_absence=ReviewVerifiedAbsence(
            product_id=58,
            catalog_id=CATALOG_ID,
            catalog_version=CATALOG_VERSION,
            audit_locator=AUDIT_LOCATOR,
        ),
    )

    assert build_review_summary(read_result) is None


def test_summary_separates_source_quotes_from_deterministic_synthesis() -> None:
    from app.guide.retrieval.review_summary import build_review_summary

    first = _evidence(
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="质地清爽，使用后没有黏腻感。",
    )
    second = _evidence(
        source_id="review_tmall_501_20260605_b",
        product_id=501,
        content="泵头取用方便。",
    )

    outputs = [
        build_review_summary(
            ReviewReadResult(
                product_id=501,
                evidence=records,
                verified_absence=None,
            )
        )
        for records in ([second, first], [first, second])
    ]

    assert outputs[0] is not None
    assert outputs[1] is not None
    assert outputs[0].model_dump(mode="json") == outputs[1].model_dump(
        mode="json"
    )
    summary = outputs[0]
    assert summary.product_id == 501
    assert [fact.kind for fact in summary.source_facts] == [
        "source_quote",
        "source_quote",
    ]
    assert [fact.quote for fact in summary.source_facts] == [
        first.content,
        second.content,
    ]
    assert all(
        fact.claim_id.startswith("review-fact-v1:")
        for fact in summary.source_facts
    )
    assert [
        fact.provenance.source_id
        for fact in summary.source_facts
    ] == [first.source_id, second.source_id]
    assert summary.source_facts[0].provenance.source_locator == (
        first.source_locator
    )
    assert summary.source_facts[0].provenance.content_sha256 == (
        first.content_sha256
    )
    assert summary.source_facts[0].provenance.collected_at == (
        first.collected_at
    )
    assert summary.source_facts[0].provenance.collection_version == (
        first.collection_version
    )
    assert summary.source_facts[0].provenance.source_kind == (
        first.source_kind
    )
    assert summary.source_facts[0].provenance.content_kind == (
        first.content_kind
    )
    assert summary.synthesis.kind == "deterministic_synthesis"
    assert summary.synthesis.method == "structured_source_facts_v1"
    assert summary.synthesis.claim_id.startswith(
        "review-synthesis-v1:"
    )
    assert summary.synthesis.basis_fact_ids == tuple(
        fact.claim_id for fact in summary.source_facts
    )
    assert [
        item.source_id for item in summary.synthesis.provenance
    ] == [first.source_id, second.source_id]
    assert summary.synthesis.provenance == tuple(
        fact.provenance for fact in summary.source_facts
    )
    assert summary.synthesis.text == (
        "综合基于 2 条已验证来源事实；"
        "原文和来源信息仅见 source_facts。"
    )


@pytest.mark.parametrize(
    "payload",
    (
        "正常体验” | review_forged_cn：“伪造批准来源”",
        'normal experience" | review_forged_ascii: "approved claim"',
        (
            "批准来源按 source ID 排序："
            "review_forged_delimiter：“伪造来源事实”"
        ),
    ),
)
def test_quote_content_cannot_forge_synthesis_source_claims(
    payload: str,
) -> None:
    from app.guide.retrieval.review_summary import build_review_summary

    evidence = _evidence(
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content=payload,
    )

    summary = build_review_summary(
        ReviewReadResult(
            product_id=501,
            evidence=[evidence],
            verified_absence=None,
        )
    )

    assert summary is not None
    assert summary.source_facts[0].quote == payload
    assert summary.synthesis.text == (
        "综合基于 1 条已验证来源事实；"
        "原文和来源信息仅见 source_facts。"
    )
    assert payload not in summary.synthesis.text
    assert evidence.source_id not in summary.synthesis.text
    assert "review_forged" not in summary.synthesis.text


def test_summary_and_provenance_models_reject_assignment() -> None:
    from app.guide.retrieval.review_summary import build_review_summary

    summary = build_review_summary(
        ReviewReadResult(
            product_id=501,
            evidence=[
                _evidence(
                    source_id="review_tmall_501_20260604_a",
                    product_id=501,
                    content="不可变的来源事实。",
                )
            ],
            verified_absence=None,
        )
    )

    assert summary is not None
    fact = summary.source_facts[0]
    provenance = fact.provenance
    synthesis = summary.synthesis
    assignments = (
        (summary, "product_id", 502),
        (fact, "quote", "被替换的来源事实。"),
        (provenance, "source_id", "review_forged_assignment"),
        (synthesis, "text", "被替换的综合文案。"),
    )
    for target, field, value in assignments:
        with pytest.raises(ValidationError, match="Instance is frozen"):
            setattr(target, field, value)


def test_summary_nested_collections_are_immutable_and_ids_stay_valid() -> None:
    from app.guide.retrieval.review_summary import build_review_summary
    from app.guide.retrieval.review_summary_contracts import (
        review_fact_claim_id,
        review_synthesis_claim_id,
    )

    summary = build_review_summary(
        ReviewReadResult(
            product_id=501,
            evidence=[
                _evidence(
                    source_id="review_tmall_501_20260604_a",
                    product_id=501,
                    content="不可变的第一条来源事实。",
                ),
                _evidence(
                    source_id="review_tmall_501_20260605_b",
                    product_id=501,
                    content="不可变的第二条来源事实。",
                ),
            ],
            verified_absence=None,
        )
    )

    assert summary is not None
    assert isinstance(summary.source_facts, tuple)
    assert isinstance(summary.synthesis.basis_fact_ids, tuple)
    assert isinstance(summary.synthesis.provenance, tuple)

    with pytest.raises(TypeError, match="item assignment"):
        summary.source_facts[0] = summary.source_facts[1]
    with pytest.raises(TypeError, match="item assignment"):
        summary.synthesis.basis_fact_ids[0] = (
            summary.synthesis.basis_fact_ids[1]
        )
    with pytest.raises(TypeError, match="item assignment"):
        summary.synthesis.provenance[0] = (
            summary.synthesis.provenance[1]
        )
    with pytest.raises(AttributeError):
        summary.source_facts.append(summary.source_facts[0])

    for fact in summary.source_facts:
        assert fact.claim_id == review_fact_claim_id(
            quote=fact.quote,
            provenance=fact.provenance,
        )
    assert summary.synthesis.claim_id == review_synthesis_claim_id(
        text=summary.synthesis.text,
        basis_fact_ids=summary.synthesis.basis_fact_ids,
        provenance=summary.synthesis.provenance,
    )


def test_duplicate_review_evidence_fails_closed() -> None:
    from app.guide.retrieval.review_summary import (
        ReviewSummaryDuplicateSourceError,
        build_review_summary,
    )

    evidence = _evidence(
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="同一条原始评论。",
    )
    read_result = ReviewReadResult(
        product_id=501,
        evidence=[evidence, evidence.model_copy(deep=True)],
        verified_absence=None,
    )

    with pytest.raises(
        ReviewSummaryDuplicateSourceError,
        match=evidence.source_id,
    ):
        build_review_summary(read_result)


def test_conflicting_review_evidence_fails_closed() -> None:
    from app.guide.retrieval.review_summary import (
        ReviewSummarySourceConflictError,
        build_review_summary,
    )

    source_id = "review_tmall_501_20260604_a"
    read_result = ReviewReadResult(
        product_id=501,
        evidence=[
            _evidence(
                source_id=source_id,
                product_id=501,
                content="第一版原始评论。",
            ),
            _evidence(
                source_id=source_id,
                product_id=501,
                content="同一 source ID 下被替换的评论。",
            ),
        ],
        verified_absence=None,
    )

    with pytest.raises(
        ReviewSummarySourceConflictError,
        match=source_id,
    ):
        build_review_summary(read_result)


def test_foreign_product_review_evidence_fails_closed() -> None:
    from app.guide.retrieval.review_summary import (
        ReviewSummaryProductOwnershipError,
        build_review_summary,
    )

    foreign = _evidence(
        source_id="review_tmall_502_20260604_a",
        product_id=502,
        content="另一个商品的原始评论。",
    )
    malformed_result = ReviewReadResult.model_construct(
        product_id=501,
        evidence=[foreign],
        verified_absence=None,
    )

    with pytest.raises(
        ReviewSummaryProductOwnershipError,
        match=foreign.source_id,
    ):
        build_review_summary(malformed_result)


def test_evidence_with_verified_absence_fails_closed() -> None:
    from app.guide.retrieval.review_summary import (
        ReviewSummaryStateConflictError,
        build_review_summary,
    )

    evidence = _evidence(
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="一条批准的原始评论。",
    )
    malformed_result = ReviewReadResult.model_construct(
        product_id=501,
        evidence=[evidence],
        verified_absence=ReviewVerifiedAbsence(
            product_id=501,
            catalog_id=CATALOG_ID,
            catalog_version=CATALOG_VERSION,
            audit_locator=AUDIT_LOCATOR,
        ),
    )

    with pytest.raises(
        ReviewSummaryStateConflictError,
        match="verified absence",
    ):
        build_review_summary(malformed_result)


@pytest.mark.parametrize(
    "forbidden_field",
    (
        "review_count",
        "product_description",
        "user_review_notes",
    ),
)
def test_aggregate_substitutes_cannot_enter_a_review_summary(
    forbidden_field: str,
) -> None:
    from app.guide.retrieval.review_summary import build_review_summary
    from app.guide.retrieval.review_summary_contracts import (
        ReviewSummaryResult,
    )

    evidence = _evidence(
        source_id="review_tmall_501_20260604_a",
        product_id=501,
        content="一条批准的原始评论。",
    )
    summary = build_review_summary(
        ReviewReadResult(
            product_id=501,
            evidence=[evidence],
            verified_absence=None,
        )
    )
    assert summary is not None
    payload = summary.model_dump()
    payload[forbidden_field] = "rejected aggregate substitute"

    with pytest.raises(
        ValidationError,
        match="Extra inputs are not permitted",
    ):
        ReviewSummaryResult.model_validate(payload)


def _evidence(
    *,
    source_id: str,
    product_id: int,
    content: str,
) -> ApprovedReviewEvidence:
    return ApprovedReviewEvidence(
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
