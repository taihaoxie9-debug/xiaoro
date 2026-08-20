from __future__ import annotations

from datetime import datetime
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_fact_assets import (
    ApprovedCategoryFact,
    CategoryFactAssets,
    CategoryFactManifest,
    PILOT_BINDINGS,
    load_category_fact_assets,
)
from app.guide.retrieval.category_fact_contracts import (
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_fact_reader import CategoryFactReader
from app.guide.retrieval.category_profiles import CategoryProfile

ROOT = Path(__file__).resolve().parents[3]


def _review_packet(
    *,
    review_status: str = "human_review_complete",
) -> dict[str, object]:
    body_ref = "smzdm-browser-body:" + "b" * 64
    facts = [
        {
            "allowed_uses": [
                "product_knowledge",
                "recommendation",
                "comparison",
                "compact_tag",
            ],
            "concept_id": "texture.lightweight",
            "decision": "map",
            "fact_id": "reviewed:product:46:texture:light-v1",
            "field_key": "texture",
            "promotion_status": "approved_non_price_fact",
            "public_text": "轻薄乳霜质地",
            "review_rationale": "正文直接支持轻薄乳霜质地。",
            "sku_status": "exact_product",
            "source_kind": "product_introduction",
            "source_ordinal": None,
            "source_refs": [body_ref],
        },
        {
            "allowed_uses": ["product_knowledge"],
            "concept_id": None,
            "decision": "leave_free",
            "fact_id": "reviewed:product:46:usage:thin-layer-v1",
            "field_key": "usage",
            "promotion_status": "approved_non_price_fact",
            "public_text": "薄涂使用",
            "review_rationale": "正文明确建议薄涂使用。",
            "sku_status": "exact_product",
            "source_kind": "product_introduction",
            "source_ordinal": None,
            "source_refs": [body_ref],
        },
        {
            "allowed_uses": [],
            "concept_id": None,
            "decision": "reject",
            "fact_id": "reviewed:product:46:efficacy:absolute-v1",
            "field_key": "efficacy",
            "promotion_status": "rejected",
            "public_text": "保证修护",
            "review_rationale": "绝对效果没有测试方法。",
            "sku_status": "exact_product",
            "source_kind": "product_introduction",
            "source_ordinal": None,
            "source_refs": [body_ref],
        },
    ]
    return {
        "candidate_facts": (
            [] if review_status == "no_promotion" else facts
        ),
        "category_profile": "skincare",
        "detail_images": [],
        "product_id": 46,
        "review_field_policy": ["efficacy", "texture", "usage"],
        "review_status": review_status,
        "sku_audit": {
            "canonical_sku": "40ml",
            "display_specification": None,
            "identity_status": "exact_product",
            "price_specification_alignment": "unresolved",
            "reference_price_sku": "unresolved",
            "source_sku": "40ml",
        },
        "source_page_text_sha256": "b" * 64,
    }


def test_reviewed_product_fact_promoter_module_exists() -> None:
    try:
        module = importlib.import_module(
            "tools.guide_data.promote_reviewed_product_facts"
        )
    except ModuleNotFoundError:
        module = None

    assert module is not None


def test_promotion_requires_terminal_human_review() -> None:
    module = importlib.import_module(
        "tools.guide_data.promote_reviewed_product_facts"
    )

    with pytest.raises(
        module.ReviewedProductFactPromotionError,
        match="terminal human review",
    ):
        module.promote_reviewed_packets(
            packets=[_review_packet(
                review_status="human_review_required"
            )],
            reviewer="main-agent-smzdm-review",
            reviewed_at=datetime.fromisoformat(
                "2026-08-20T04:00:00+08:00"
            ),
        )


def test_promotion_routes_map_leave_free_and_drops_reject() -> None:
    module = importlib.import_module(
        "tools.guide_data.promote_reviewed_product_facts"
    )

    facts = module.promote_reviewed_packets(
        packets=[_review_packet()],
        reviewer="main-agent-smzdm-review",
        reviewed_at=datetime.fromisoformat(
            "2026-08-20T04:00:00+08:00"
        ),
    )

    assert [(fact.field_key, fact.value) for fact in facts] == [
        ("texture", ["轻薄乳霜质地"]),
        ("usage", ["薄涂使用"]),
    ]
    assert facts[0].capability_limit == frozenset(
        {"evidence", "display", "compare", "soft_rank"}
    )
    assert facts[1].capability_limit == frozenset(
        {"evidence", "display"}
    )
    assert all("保证修护" not in fact.value for fact in facts)


def test_no_promotion_packet_publishes_no_facts() -> None:
    module = importlib.import_module(
        "tools.guide_data.promote_reviewed_product_facts"
    )

    assert module.promote_reviewed_packets(
        packets=[_review_packet(review_status="no_promotion")],
        reviewer="main-agent-smzdm-review",
        reviewed_at=datetime.fromisoformat(
            "2026-08-20T04:00:00+08:00"
        ),
    ) == ()


def test_promotion_requires_main_agent_metadata() -> None:
    module = importlib.import_module(
        "tools.guide_data.promote_reviewed_product_facts"
    )

    with pytest.raises(
        module.ReviewedProductFactPromotionError,
        match="reviewer",
    ):
        module.promote_reviewed_packets(
            packets=[_review_packet()],
            reviewer="",
            reviewed_at=datetime.fromisoformat(
                "2026-08-20T04:00:00+08:00"
            ),
        )


def test_promoted_fields_replace_older_category_facts() -> None:
    module = importlib.import_module(
        "tools.guide_data.promote_reviewed_product_facts"
    )
    promoted = module.promote_reviewed_packets(
        packets=[_review_packet()],
        reviewer="main-agent-smzdm-review",
        reviewed_at=datetime.fromisoformat(
            "2026-08-20T04:00:00+08:00"
        ),
    )
    old_texture = ApprovedCategoryFact(
        fact_id="d" * 64,
        product_id=46,
        category_profile=CategoryProfile.SKINCARE,
        field_key="texture",
        value=["旧质地"],
        source_class=SourceClass.MERCHANT_DESCRIPTION,
        source_refs=(
            "urn:xiaoro:category-fact-source:sha256:"
            + "e" * 64
            + ":"
            + "f" * 64,
        ),
        source_sha256="e" * 64,
        reviewer="legacy-review",
        reviewed_at=datetime.fromisoformat(
            "2026-08-14T04:00:00+08:00"
        ),
    )
    untouched = old_texture.model_copy(
        update={
            "fact_id": "c" * 64,
            "product_id": 47,
            "field_key": "efficacy",
            "value": ["旧功效"],
        },
        deep=True,
    )

    merged = module.merge_promoted_facts(
        existing=(old_texture, untouched),
        promoted=promoted,
    )

    assert old_texture not in merged
    assert untouched in merged
    assert {fact.field_key for fact in merged if fact.product_id == 46} == {
        "texture",
        "usage",
    }


def test_publish_all_reviewed_packets_is_hash_locked(
    tmp_path: Path,
) -> None:
    module = importlib.import_module(
        "tools.guide_data.promote_reviewed_product_facts"
    )
    output = tmp_path / "promoted"

    result = module.publish_reviewed_fact_assets(
        existing_manifest_path=(
            ROOT
            / "data/guide_category_facts/category_facts_v1_manifest.json"
        ),
        review_paths=tuple(sorted(
            (
                ROOT / "docs/audits/smzdm-data/reviewed-products"
            ).glob("product-*-v1.json")
        )),
        output_dir=output,
        reviewer="main-agent-smzdm-review",
        reviewed_at=datetime.fromisoformat(
            "2026-08-20T04:00:00+08:00"
        ),
        canonical_manifest_path=(
            ROOT / "data/canonical/core_products_v1_manifest.json"
        ),
        canonical_products_path=(
            ROOT / "data/canonical/core_products_v1.jsonl"
        ),
    )
    manifest = json.loads(
        result.manifest_path.read_text(encoding="utf-8")
    )
    reader = CanonicalProductReader.from_files(
        manifest_path=(
            ROOT / "data/canonical/core_products_v1_manifest.json"
        ),
        products_path=(
            ROOT / "data/canonical/core_products_v1.jsonl"
        ),
    )
    assets = load_category_fact_assets(
        manifest_path=result.manifest_path,
        facts_path=result.facts_path,
        expected_manifest_sha256=manifest["manifest_sha256"],
        canonical_reader=reader,
        field_registry=category_field_registry(),
    )
    promoted = tuple(
        fact
        for fact in assets.facts
        if fact.reviewer == "main-agent-smzdm-review"
    )

    assert result.promoted_count == 259
    assert result.replaced_count > 0
    assert len(promoted) == 259
    assert sum(
        "soft_rank" in (fact.capability_limit or ())
        for fact in promoted
    ) == 101
    assert sum(
        fact.capability_limit == frozenset({"evidence", "display"})
        for fact in promoted
    ) == 158
    assert result.facts_path.name == (
        "category_facts_v1."
        + manifest["facts_sha256"]
        + ".jsonl"
    )


def test_promoter_cli_publishes_all_terminal_reviews(
    tmp_path: Path,
) -> None:
    output = tmp_path / "promoted"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.promote_reviewed_product_facts",
            "--existing-manifest",
            str(
                ROOT
                / "data/guide_category_facts/"
                "category_facts_v1_manifest.json"
            ),
            "--review-dir",
            str(
                ROOT / "docs/audits/smzdm-data/reviewed-products"
            ),
            "--output-dir",
            str(output),
            "--reviewer",
            "main-agent-smzdm-review",
            "--reviewed-at",
            "2026-08-20T04:00:00+08:00",
            "--canonical-manifest",
            str(
                ROOT / "data/canonical/core_products_v1_manifest.json"
            ),
            "--canonical-products",
            str(ROOT / "data/canonical/core_products_v1.jsonl"),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["promoted_count"] == 259
    assert report["review_packet_count"] == 79
    assert Path(report["manifest_path"]) == (
        output / "category_facts_v1_manifest.json"
    )
    assert Path(report["facts_path"]).is_file()


def test_runtime_generation_loads_all_reviewed_promotions() -> None:
    from app.guide_runtime import composition

    manifest_path = (
        ROOT / composition.GUIDE_CATEGORY_FACT_RELATIVE_PATH
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reader = CanonicalProductReader.from_files(
        manifest_path=(
            ROOT / "data/canonical/core_products_v1_manifest.json"
        ),
        products_path=(
            ROOT / "data/canonical/core_products_v1.jsonl"
        ),
    )
    assets = load_category_fact_assets(
        manifest_path=manifest_path,
        expected_manifest_sha256=(
            composition.GUIDE_CATEGORY_FACT_MANIFEST_SHA256
        ),
        canonical_reader=reader,
        field_registry=category_field_registry(),
    )
    promoted = tuple(
        fact
        for fact in assets.facts
        if fact.reviewer == "main-agent-smzdm-review"
    )

    assert manifest["manifest_sha256"] == (
        composition.GUIDE_CATEGORY_FACT_MANIFEST_SHA256
    )
    assert len(promoted) == 259
    assert sum(
        "soft_rank" in (fact.capability_limit or ())
        for fact in promoted
    ) == 101
    assert sum(
        fact.capability_limit == frozenset({"evidence", "display"})
        for fact in promoted
    ) == 158


def test_category_fact_capability_limit_blocks_leave_free_ranking() -> None:
    fact = ApprovedCategoryFact(
        fact_id="a" * 64,
        product_id=46,
        category_profile=CategoryProfile.SKINCARE,
        field_key="texture",
        value=["柔润乳霜质地"],
        source_class=SourceClass.MERCHANT_DESCRIPTION_OCR,
        source_refs=(
            "urn:xiaoro:category-fact-source:sha256:"
            + "b" * 64
            + ":"
            + "c" * 64,
        ),
        source_sha256="b" * 64,
        reviewer="main-agent-smzdm-review",
        reviewed_at=datetime.fromisoformat(
            "2026-08-20T04:00:00+08:00"
        ),
        capability_limit={"evidence", "display"},
    )
    assets = CategoryFactAssets(
        manifest=CategoryFactManifest(
            asset_id="guide-category-facts-v1",
            asset_version="test",
            fact_count=1,
            facts_file="facts.jsonl",
            facts_sha256="d" * 64,
            manifest_sha256="e" * 64,
            pilot_bindings=PILOT_BINDINGS,
            schema_version="approved-category-facts-v1",
        ),
        facts=(fact,),
    )

    rows = CategoryFactReader(
        assets=assets,
        field_registry=category_field_registry(),
    ).read(
        product_id=46,
        profile=CategoryProfile.SKINCARE,
    )
    texture = next(row for row in rows if row.field_key == "texture")

    assert texture.resolved_state == "known"
    assert texture.capabilities == frozenset({"evidence", "display"})
