from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.guide.retrieval.product_evidence_assets import ProductEvidenceBlock
from tools.guide_data.audit_product_knowledge_coverage import (
    build_product_knowledge_coverage,
    write_product_knowledge_coverage,
)


def _field(value: object, *, state: str = "known") -> SimpleNamespace:
    return SimpleNamespace(resolved_state=state, value=value)


class _CanonicalReader:
    product_ids = frozenset({26, 38, 90, 100})

    _products = {
        26: SimpleNamespace(
            fields={
                "product_identity": _field("无"),
                "brand": _field("兰蔻（LANCOME）"),
                "category": _field("防晒"),
            }
        ),
        38: SimpleNamespace(
            fields={
                "product_identity": _field("理肤泉新B5多效修护精华"),
                "brand": _field("理肤泉（LA ROCHE-POSAY）"),
                "category": _field("精华"),
            }
        ),
        90: SimpleNamespace(
            fields={
                "product_identity": _field("理肤泉"),
                "brand": _field("理肤泉（LA ROCHE-POSAY）"),
                "category": _field("乳霜"),
            }
        ),
        100: SimpleNamespace(
            fields={
                "product_identity": _field("000"),
                "brand": _field("科颜氏（Kiehl's）"),
                "category": _field("面霜"),
            }
        ),
    }

    def get(self, product_id: int):
        return self._products[product_id]


class _CategoryFactReader:
    def read(self, *, product_id: int, profile):
        del profile
        if product_id != 38:
            return ()
        return (
            SimpleNamespace(
                field_key="ingredients_present",
                resolved_state="known",
                value=("泛醇",),
            ),
            SimpleNamespace(
                field_key="texture",
                resolved_state="known",
                value="清爽",
            ),
            SimpleNamespace(
                field_key="usage",
                resolved_state="unknown",
                value=None,
            ),
        )


def _evidence(
    *,
    evidence_id: str,
    label: str,
    meaning: str,
    relation: tuple[str, str, str],
) -> ProductEvidenceBlock:
    return ProductEvidenceBlock.model_construct(
        evidence_id=evidence_id,
        product_id=38,
        subject_scope="exact_product",
        variant_scope=None,
        management_label=label,
        exact_text=meaning,
        plain_meaning=meaning,
        relations=(
            SimpleNamespace(
                subject=relation[0],
                predicate=relation[1],
                object=relation[2],
            ),
        ),
        qualifiers=SimpleNamespace(),
        free_descriptors=(),
        review_status="accepted",
        allowed_uses=frozenset({"answer", "display"}),
        forbidden_uses=frozenset(),
        review_rationale="test",
        selection_review=None,
        source=SimpleNamespace(source_locator="urn:test"),
        supporting_sources=(),
    )


class _EvidenceReader:
    manifest = SimpleNamespace(
        allowed_use_counts={"answer": 2},
        product_count=1,
    )

    def read_answerable(self, *, product_id: int):
        if product_id != 38:
            return ()
        return (
            _evidence(
                evidence_id="1" * 64,
                label="faq",
                meaning="商家FAQ说明晚间使用方式。",
                relation=(
                    "晚间护理",
                    "merchant_faq_answer",
                    "洁面后使用",
                ),
            ),
            _evidence(
                evidence_id="2" * 64,
                label="product_specification",
                meaning="净含量30ml。",
                relation=("产品", "label_net_content", "30ml"),
            ),
        )

    def read(self, *, product_id: int):
        return self.read_answerable(product_id=product_id)


def test_product_knowledge_coverage_separates_sources_and_identity_gaps() -> None:
    report = build_product_knowledge_coverage(
        canonical_reader=_CanonicalReader(),
        category_fact_reader=_CategoryFactReader(),
        evidence_reader=_EvidenceReader(),
    )

    assert report["canonical_product_count"] == 4
    assert report["product_evidence_product_count"] == 1
    assert report["category_fact_product_count"] == 1
    assert report["union_covered_product_count"] == 1
    assert [row["product_id"] for row in report["products"]] == [
        26,
        38,
        90,
        100,
    ]
    rows = {
        row["product_id"]: row
        for row in report["products"]
    }
    assert rows[26]["identity_status"] == "placeholder"
    assert rows[26]["remediation"] == "catalog_cleanup"
    assert rows[90]["identity_status"] == "underspecified"
    assert rows[90]["remediation"] == "catalog_cleanup"
    assert rows[100]["identity_status"] == "placeholder"
    assert rows[100]["remediation"] == "catalog_cleanup"
    assert rows[38]["answerable_evidence_count"] == 2
    assert rows[38]["faq_count"] == 1
    assert rows[38]["category_fact_count"] == 2
    assert rows[38]["covered_fields"] == [
        "ingredients_present",
        "net_content",
        "texture",
        "usage",
    ]
    assert rows[38]["missing_priority_fields"] == ["efficacy"]
    assert rows[38]["remediation"] == "already_available"


def test_product_knowledge_coverage_outputs_are_deterministic(
    tmp_path: Path,
) -> None:
    report = build_product_knowledge_coverage(
        canonical_reader=_CanonicalReader(),
        category_fact_reader=_CategoryFactReader(),
        evidence_reader=_EvidenceReader(),
    )
    first_json = tmp_path / "first.json"
    first_markdown = tmp_path / "first.md"
    second_json = tmp_path / "second.json"
    second_markdown = tmp_path / "second.md"

    write_product_knowledge_coverage(
        report=report,
        json_output=first_json,
        markdown_output=first_markdown,
    )
    write_product_knowledge_coverage(
        report=report,
        json_output=second_json,
        markdown_output=second_markdown,
    )

    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_markdown.read_bytes() == second_markdown.read_bytes()
    parsed = json.loads(first_json.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == "product-knowledge-coverage-v1"
    assert "PID 90" in first_markdown.read_text(encoding="utf-8")
