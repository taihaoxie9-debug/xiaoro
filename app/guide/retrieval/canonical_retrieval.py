"""Slice 1 召回层：从 Canonical 按品类召回候选。

原则：只读 Canonical 商品事实，按 product_id 稳定输出候选及来源；
不判 winner、不打分、不把 unknown 字段补成默认值。
决策所需的字段证据保留在 Canonical 商品本身，由 decision 层读取。
"""
from __future__ import annotations

from app.guide.retrieval.category_taxonomy import (
    CATEGORY_TAXONOMY_VERSION,
    canonical_categories_for,
)
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.retrieval.ports import CategoryCatalogPort
from app.guide.understanding.contracts import TopicCode


def retrieve_candidates(
    catalog: CategoryCatalogPort,
    *,
    category: TopicCode,
) -> RetrievalResult:
    if not isinstance(category, TopicCode):
        return RetrievalResult(
            candidates=[],
            knowledge_evidence=[],
            review_evidence=[],
            memory_evidence=[],
            missing_sources=[f"canonical:{category}"],
        )

    allowed = canonical_categories_for(category)
    candidates = [
        CandidateRef(
            product_id=record.product_id,
            source="canonical",
            canonical_category=record.value,
            retrieval_reason=(
                f"category_family={category.value};"
                f"taxonomy={CATEGORY_TAXONOMY_VERSION};"
                f"matched={record.value}"
            ),
        )
        for record in catalog.iter_category_records()
        if record.state == "known"
        and record.value is not None
        and record.value in allowed
    ]
    return RetrievalResult(
        candidates=candidates,
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[] if candidates else [f"canonical:{category.value}"],
    )
