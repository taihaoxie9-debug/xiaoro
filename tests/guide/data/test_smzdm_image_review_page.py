from __future__ import annotations

import json
from pathlib import Path

from tools.guide_data import build_smzdm_image_review_page as image_review_page


def test_current_assets_load_from_manifest_without_cross_product_fallback(
    tmp_path: Path,
) -> None:
    product_image = tmp_path / "images" / "product-33.png"
    product_image.parent.mkdir()
    product_image.write_bytes(b"official-33")
    manifest = tmp_path / "seed_product_images.jsonl"
    manifest.write_text(
        "\n".join(
            (
                json.dumps({
                    "product_id": 33,
                    "relative_path": "images/product-33.png",
                }),
                json.dumps({
                    "product_id": 91,
                    "relative_path": "images/product-91.png",
                }),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    assets = image_review_page.load_current_assets_from_manifest(
        image_manifest_path=manifest,
        repo_root=tmp_path,
        product_ids=(33, 91),
    )

    assert assets[33]["image_path"] == "images/product-33.png"
    assert assets[33]["image_bytes"] == b"official-33"
    assert 91 not in assets


def test_image_review_page_contains_side_by_side_candidate_metadata(
    tmp_path: Path,
) -> None:
    candidate = {
        "candidate_id": "c" * 64,
        "canonical_product_id": 33,
        "source_title": "小棕瓶第七代 100ml",
        "source_url": "https://www.smzdm.com/p/1/",
        "candidate_fields": {"net_content": "100ml"},
        "image_review": {
            "status": "approved",
            "source_url": "https://qny.smzdm.com/1.jpg",
            "source_sha256": "a" * 64,
            "background_assessment": "clean_white",
            "sku_match_assessment": "same_product_100ml",
        },
        "existing_asset_conflicts": [],
        "fact_promotion_status": "pending",
    }
    current = {
        "product_id": 33,
        "name": "小棕瓶",
        "image_path": "app/static/images/products/current.png",
        "image_bytes": b"current",
    }
    candidate_image = tmp_path / "candidate.jpg"
    candidate_image.write_bytes(b"candidate")
    output = tmp_path / "review.html"

    image_review_page.build_image_review_page(
        candidates=(candidate,),
        current_assets={33: current},
        candidate_image_root=tmp_path,
        output_path=output,
    )

    html = output.read_text(encoding="utf-8")
    assert "小棕瓶第七代 100ml" in html
    assert "same_product_100ml" in html
    assert "候选图" in html
    assert "现有正式图" in html
    assert "data:image/jpeg;base64" in html
    assert "data:image/png;base64" in html


def test_image_review_candidates_merge_full_and_image_only_rows() -> None:
    full = {
        "canonical_product_id": 33,
        "source_title": "小棕瓶第七代 100ml",
    }
    image_only = {
        "canonical_product_id": 91,
        "source_title": "玉泽精华乳 50ml",
    }

    assert hasattr(image_review_page, "merge_image_review_candidates")
    merged = image_review_page.merge_image_review_candidates(
        image_candidates=(image_only,),
        reviewed_candidates=(full,),
    )

    assert tuple(
        int(candidate["canonical_product_id"])
        for candidate in merged
    ) == (33, 91)
