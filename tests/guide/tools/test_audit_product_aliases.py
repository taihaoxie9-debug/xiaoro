from __future__ import annotations

import json
from pathlib import Path

from tools.guide_data.audit_product_aliases import (
    ProductAliasReviewRecord,
    audit_product_aliases,
    discover_legacy_aliases,
    publish_controlled_product_aliases,
)


ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "data" / "canonical"
EVIDENCE = ROOT / "data" / "guide_product_evidence"
LEGACY = ROOT.parent / "xiaoro-shopping-master"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return path


def _canonical_row(product_id: int, name: str) -> dict[str, object]:
    return {
        "schema_version": "canonical-decision-product-v1",
        "product_id": product_id,
        "fields": {
            "product_identity": {
                "value": name,
            },
        },
    }


def _evidence_row(
    *,
    evidence_id: str,
    product_id: int,
    exact_text: str,
    subject_scope: str = "exact_product",
    variant_scope: str | None = None,
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "product_id": product_id,
        "review_status": "accepted",
        "exact_text": exact_text,
        "plain_meaning": exact_text,
        "review_rationale": "身份信息已审核。",
        "free_descriptors": [],
        "qualifiers": {"footnotes": []},
        "relations": [],
        "subject_scope": subject_scope,
        "variant_scope": variant_scope,
    }


def _review(
    *,
    alias: str,
    disposition: str,
    candidate_product_ids: list[int],
    product_id: int | None,
    evidence_ids: list[str],
    variant_scope: str | None = None,
    discovery_sources: list[str] | None = None,
) -> dict[str, object]:
    return {
        "alias": alias,
        "candidate_product_ids": candidate_product_ids,
        "discovery_sources": discovery_sources or ["evidence"],
        "disposition": disposition,
        "evidence_ids": evidence_ids,
        "product_id": product_id,
        "review_rationale": "逐项核对昵称与 Canonical 身份。",
        "variant_scope": variant_scope,
    }


def test_unreviewed_accepted_nickname_evidence_fails_closed(
    tmp_path: Path,
) -> None:
    canonical = _write_jsonl(
        tmp_path / "canonical.jsonl",
        [_canonical_row(59, "SK-II护肤精华露")],
    )
    evidence = _write_jsonl(
        tmp_path / "evidence.jsonl",
        [
            _evidence_row(
                evidence_id="a" * 64,
                product_id=59,
                exact_text="神仙水是SK-II护肤精华露的昵称",
            )
        ],
    )
    reviews = _write_jsonl(tmp_path / "reviews.jsonl", [])

    report = audit_product_aliases(
        canonical_path=canonical,
        evidence_path=evidence,
        review_path=reviews,
    ).report

    assert report.evidence_alias_block_count == 1
    assert report.missing_evidence_reviews == 1
    assert not report.clean


def test_exact_variant_requires_matching_reviewed_variant_evidence(
    tmp_path: Path,
) -> None:
    canonical = _write_jsonl(
        tmp_path / "canonical.jsonl",
        [_canonical_row(117, "URBAN DECAY MOONDUST单色眼影")],
    )
    evidence = _write_jsonl(
        tmp_path / "evidence.jsonl",
        [
            _evidence_row(
                evidence_id="b" * 64,
                product_id=117,
                exact_text="茶牛郎是当前商品的昵称",
                subject_scope="exact_product",
            )
        ],
    )
    reviews = _write_jsonl(
        tmp_path / "reviews.jsonl",
        [
            _review(
                alias="茶牛郎",
                disposition="approved_exact_variant",
                candidate_product_ids=[117],
                product_id=117,
                evidence_ids=["b" * 64],
                variant_scope="茶牛郎 / CRUSHIN' HARD / 坠落银河",
            )
        ],
    )

    report = audit_product_aliases(
        canonical_path=canonical,
        evidence_path=evidence,
        review_path=reviews,
    ).report

    assert report.invalid_variant_bindings == 1
    assert not report.clean


def test_marketing_and_ingredient_nicknames_never_publish_runtime_ids() -> None:
    for disposition in ("marketing_phrase", "ingredient_nickname"):
        record = ProductAliasReviewRecord.model_validate(
            _review(
                alias=(
                    "油皮救星"
                    if disposition == "marketing_phrase"
                    else "律波肽"
                ),
                disposition=disposition,
                candidate_product_ids=[126 if disposition == "marketing_phrase" else 33],
                product_id=None,
                evidence_ids=["c" * 64],
            ),
            strict=True,
        )

        assert record.product_id is None
        assert not record.is_runtime_alias


def test_legacy_python_alias_maps_are_discovered_without_importing_them(
    tmp_path: Path,
) -> None:
    module = tmp_path / "legacy.py"
    module.write_text(
        "\n".join(
            (
                'PRODUCT_ALIAS_MAP = {"神仙水": {"brand": "SK-II"}}',
                "def one():",
                '    alias_map = {"蓝胖子": "资生堂"}',
                "def two():",
                '    product_aliases = {"油皮救星": {"brand": "纪梵希"}}',
            )
        )
        + "\n",
        encoding="utf-8",
    )

    candidates = discover_legacy_aliases((module,))

    assert {item.alias for item in candidates} == {
        "神仙水",
        "蓝胖子",
        "油皮救星",
    }


def test_publisher_emits_only_runtime_aliases_with_bound_manifest(
    tmp_path: Path,
) -> None:
    reviews = _write_jsonl(
        tmp_path / "reviews.jsonl",
        [
            _review(
                alias="神仙水",
                disposition="approved_exact_product",
                candidate_product_ids=[59],
                product_id=59,
                evidence_ids=["a" * 64],
            ),
            _review(
                alias="油皮救星",
                disposition="marketing_phrase",
                candidate_product_ids=[126],
                product_id=None,
                evidence_ids=["b" * 64],
            ),
            _review(
                alias="B5",
                disposition="ambiguous_family",
                candidate_product_ids=[38, 46, 77],
                product_id=None,
                evidence_ids=[],
                discovery_sources=["canonical_name"],
            ),
        ],
    )
    aliases_path = tmp_path / "controlled_product_aliases_v1.jsonl"
    manifest_path = (
        tmp_path / "controlled_product_aliases_v1_manifest.json"
    )

    publish_controlled_product_aliases(
        review_path=reviews,
        aliases_path=aliases_path,
        manifest_path=manifest_path,
        canonical_sha256="c" * 64,
    )

    records = [
        json.loads(line)
        for line in aliases_path.read_text(encoding="utf-8").splitlines()
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [record["alias"] for record in records] == ["B5", "神仙水"]
    assert records[0]["identity_scope"] == "ambiguous_family"
    assert records[0]["default_product_id"] is None
    assert records[0]["product_ids"] == [38, 46, 77]
    assert records[1]["identity_scope"] == "exact_product"
    assert records[1]["default_product_id"] == 59
    assert records[1]["source_refs"] == ["a" * 64]
    assert manifest["record_count"] == 2
    assert manifest["canonical_sha256"] == "c" * 64


def test_repository_alias_audit_covers_current_catalog_evidence_and_legacy() -> None:
    manifest = json.loads(
        (EVIDENCE / "product_evidence_v1_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    evidence_path = EVIDENCE / manifest["evidence_file"]

    audit = audit_product_aliases(
        canonical_path=CANONICAL / "core_products_v1.jsonl",
        evidence_path=evidence_path,
        review_path=CANONICAL / "product_alias_reviews_v1.jsonl",
        legacy_paths=(
            LEGACY / "app" / "services" / "intent.py",
            LEGACY / "app" / "services" / "agent.py",
            LEGACY / "app" / "services" / "v2" / "turn_parser.py",
        ),
    )

    assert audit.report.canonical_product_count == 103
    assert audit.report.evidence_alias_block_count >= 20
    assert audit.report.legacy_alias_count >= 70
    assert audit.report.reviewed_alias_count >= audit.report.legacy_alias_count
    assert audit.report.missing_evidence_reviews == 0
    assert audit.report.missing_legacy_reviews == 0
    assert audit.report.unknown_product_bindings == 0
    assert audit.report.invalid_variant_bindings == 0
    assert audit.report.invalid_reviews == 0
    assert audit.report.clean
