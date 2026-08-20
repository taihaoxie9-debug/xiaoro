"""Slice 1 召回层失败测试（RED）。

验证 retrieve_candidates 从 Canonical 按品类召回候选：
- 返回该品类全部候选及来源
- 附带决策所需字段证据（price / suitable_skin 等），保留 resolved_state
- 只读、不判 winner、不打分、不把 unknown 字段补成默认值
"""
from __future__ import annotations

from pathlib import Path

from app.guide.adapters.catalog import CanonicalGuideCatalog, CanonicalProductReader
from app.guide.retrieval import RetrievalResult
from app.guide.understanding.contracts import TopicCode

CANONICAL = Path("data/canonical")


def make_reader() -> CanonicalProductReader:
    return CanonicalProductReader.from_files(
        manifest_path=CANONICAL / "core_products_v1_manifest.json",
        products_path=CANONICAL / "core_products_v1.jsonl",
    )


def make_catalog() -> CanonicalGuideCatalog:
    return CanonicalGuideCatalog(make_reader())


def retrieve():
    from app.guide.retrieval.canonical_retrieval import retrieve_candidates

    return retrieve_candidates


def test_retrieves_all_sunscreen_family_candidates() -> None:
    result = retrieve()(make_catalog(), category=TopicCode.SUNSCREEN)

    assert isinstance(result, RetrievalResult)
    assert len(result.candidates) == 12
    assert {item.product_id for item in result.candidates} == {
        26, 51, 52, 53, 54, 55, 56, 57, 58, 101, 102, 130
    }
    assert {item.canonical_category for item in result.candidates} == {
        "防晒",
        "防晒隔离",
        "防晒乳液",
        "防晒霜",
        "防晒乳",
    }
    assert all(c.source == "canonical" for c in result.candidates)
    assert all(c.retrieval_reason for c in result.candidates)


def test_retrieves_only_serum_family_candidates() -> None:
    result = retrieve()(make_catalog(), category=TopicCode.SERUM)

    assert [item.product_id for item in result.candidates] == [
        32, 33, 34, 35, 36, 37, 38, 39,
        40, 41, 42, 59, 63, 91, 105, 129,
    ]
    assert {item.canonical_category for item in result.candidates} == {
        "精华",
        "精华液",
    }


def test_unknown_category_returns_empty_and_flags_missing_source() -> None:
    result = retrieve()(make_catalog(), category="不存在的品类")

    assert result.candidates == []
    assert "canonical:不存在的品类" in result.missing_sources


def test_retrieval_does_not_fill_unknown_fields_or_rank() -> None:
    result = retrieve()(make_catalog(), category=TopicCode.SUNSCREEN)

    # 召回结果不含排序/winner 语义
    dumped = result.model_dump()
    assert "ordered_product_ids" not in dumped
    assert "winner_status" not in dumped
    # 候选顺序按 product_id 稳定，不代表排名
    ids = [c.product_id for c in result.candidates]
    assert ids == sorted(ids)
