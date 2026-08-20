from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from app.guide.retrieval.category_profiles import CategoryProfile
from tools.guide_data.build_full_catalog_closure import (
    build_product_state_row,
    classify_parameter_group,
    promotion_candidate_row,
    render_classifications,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _module():
    try:
        return importlib.import_module(
            "tools.guide_data.verify_full_catalog_closure"
        )
    except ModuleNotFoundError:
        pytest.fail("full catalog closure verifier is missing")


def _jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join(
        (
            json.dumps(
                row,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        for row in rows
    )


def _write_fixture_batch(tmp_path: Path) -> dict[str, object]:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    source = (FIXTURES / "tmall_saved_page.html").read_bytes()
    source_sha256 = hashlib.sha256(source).hexdigest()
    relative_name = "saved.html"
    (downloads / relative_name).write_bytes(source)
    root_id = hashlib.sha256(
        b"guide-source-root-v1\0approved-root-0001"
    ).hexdigest()
    inventory_bytes = _jsonl(
        [
            {
                "content_type": "html",
                "relative_name": relative_name,
                "sha256": source_sha256,
                "size_bytes": len(source),
                "source_root_id": root_id,
            }
        ]
    )
    inventory = tmp_path / "inventory.jsonl"
    inventory.write_bytes(inventory_bytes)
    classification = classify_parameter_group(
        product_id=42,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        source_sha256=source_sha256,
        item_id="998532090974",
        sku_ids=("6153782938028",),
        parameter_name="适用肤质",
        raw_values=("干性",),
        ordinal=4,
    )
    classifications = tmp_path / "parameter_classifications.jsonl"
    classification_bytes = render_classifications((classification,))
    classifications.write_bytes(classification_bytes)
    candidate = promotion_candidate_row(classification)
    candidates = tmp_path / "pending_candidates.jsonl"
    candidate_bytes = _jsonl([candidate])
    candidates.write_bytes(candidate_bytes)
    page_manifest = tmp_path / "page_manifest.jsonl"
    page_bytes = _jsonl(
        [
            {
                "item_id": "998532090974",
                "parameter_group_count": 4,
                "parse_status": "parsed",
                "platform": "tmall",
                "relative_name_sha256": hashlib.sha256(
                    relative_name.encode()
                ).hexdigest(),
                "review_count": 1,
                "sku_ids": ["6153782938028"],
                "source_sha256": source_sha256,
                "title_sha256": hashlib.sha256(
                    "示例精华".encode()
                ).hexdigest(),
            }
        ]
    )
    page_manifest.write_bytes(page_bytes)
    canonical = {
        "product_id": 42,
        "fields": {
            "product_identity": {
                "resolved_state": "known",
                "value": "示例精华",
            },
            "brand": {"resolved_state": "known", "value": "示例品牌"},
            "category": {"resolved_state": "known", "value": "精华"},
            "price": {"resolved_state": "known", "value": 100},
            "suitable_skin": {
                "resolved_state": "unknown",
                "value": None,
            },
        },
    }
    canonical_path = tmp_path / "canonical.jsonl"
    canonical_path.write_bytes(_jsonl([canonical]))
    matrix = build_product_state_row(
        canonical_product=canonical,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        classifications=(classification,),
    )
    matrix_path = tmp_path / "product_matrix.jsonl"
    matrix_bytes = _jsonl([matrix])
    matrix_path.write_bytes(matrix_bytes)
    return {
        "candidate_bytes": candidate_bytes,
        "candidates": candidates,
        "canonical": canonical_path,
        "classification_bytes": classification_bytes,
        "classifications": classifications,
        "downloads": downloads,
        "inventory": inventory,
        "inventory_bytes": inventory_bytes,
        "matrix": matrix_path,
        "matrix_bytes": matrix_bytes,
        "page_bytes": page_bytes,
        "page_manifest": page_manifest,
    }


def test_serial_source_and_policy_verifiers_share_frozen_candidate_sha(
    tmp_path: Path,
) -> None:
    module = _module()
    batch = _write_fixture_batch(tmp_path)
    candidate_sha256 = hashlib.sha256(
        batch["candidate_bytes"]
    ).hexdigest()
    source_commit = "a" * 40

    verifier_a = module.verify_source_candidates(
        candidates_path=batch["candidates"],
        classifications_path=batch["classifications"],
        page_manifest_path=batch["page_manifest"],
        inventory_path=batch["inventory"],
        downloads_root=batch["downloads"],
        expected_candidates_sha256=candidate_sha256,
        expected_classifications_sha256=hashlib.sha256(
            batch["classification_bytes"]
        ).hexdigest(),
        expected_page_manifest_sha256=hashlib.sha256(
            batch["page_bytes"]
        ).hexdigest(),
        expected_inventory_sha256=hashlib.sha256(
            batch["inventory_bytes"]
        ).hexdigest(),
        source_commit=source_commit,
    )
    verifier_b = module.verify_policy_candidates(
        candidates_path=batch["candidates"],
        matrix_path=batch["matrix"],
        canonical_products_path=batch["canonical"],
        expected_candidates_sha256=candidate_sha256,
        expected_matrix_sha256=hashlib.sha256(
            batch["matrix_bytes"]
        ).hexdigest(),
        source_commit=source_commit,
    )

    assert verifier_a.status == "PASS"
    assert verifier_b.status == "PASS"
    assert verifier_a.candidate_sha256 == candidate_sha256
    assert verifier_b.candidate_sha256 == candidate_sha256
    assert verifier_a.passed_candidate_ids == (
        verifier_b.passed_candidate_ids
    )

    decisions = module.build_joint_decisions(
        verifier_a=verifier_a,
        verifier_b=verifier_b,
        candidates_path=batch["candidates"],
        expected_candidates_sha256=candidate_sha256,
        reviewed_at="2026-08-14T04:00:00+08:00",
    )
    rows = [
        json.loads(line)
        for line in decisions.decode().splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["decision"] == "approved_fact"


def test_source_verifier_rejects_raw_value_hash_drift(
    tmp_path: Path,
) -> None:
    module = _module()
    batch = _write_fixture_batch(tmp_path)
    rows = [
        json.loads(line)
        for line in batch["classification_bytes"].decode().splitlines()
    ]
    rows[0]["raw_value_sha256"] = "0" * 64
    tampered = _jsonl(rows)
    batch["classifications"].write_bytes(tampered)

    report = module.verify_source_candidates(
        candidates_path=batch["candidates"],
        classifications_path=batch["classifications"],
        page_manifest_path=batch["page_manifest"],
        inventory_path=batch["inventory"],
        downloads_root=batch["downloads"],
        expected_candidates_sha256=hashlib.sha256(
            batch["candidate_bytes"]
        ).hexdigest(),
        expected_classifications_sha256=hashlib.sha256(
            tampered
        ).hexdigest(),
        expected_page_manifest_sha256=hashlib.sha256(
            batch["page_bytes"]
        ).hexdigest(),
        expected_inventory_sha256=hashlib.sha256(
            batch["inventory_bytes"]
        ).hexdigest(),
        source_commit="b" * 40,
    )

    assert report.status == "FAIL"
    assert report.passed_candidate_ids == ()
    assert report.failures[0]["reason"] == "raw_value_sha256_mismatch"
