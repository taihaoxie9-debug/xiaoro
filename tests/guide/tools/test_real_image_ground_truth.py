from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GROUND_TRUTH = (
    ROOT
    / "docs"
    / "audits"
    / "continuous-conversation"
    / "real-image-ground-truth-v1.json"
)
INDEX_MANIFEST = (
    ROOT
    / "data"
    / "guide_image_index"
    / "openclip_vit_b32_laion2b_s34b_b79k_v1"
    / "manifest.json"
)
CANONICAL = ROOT / "data" / "canonical" / "core_products_v1.jsonl"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_real_image_ground_truth_is_canonical_and_non_index() -> None:
    ground_truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    images = ground_truth["images"]
    canonical = {
        row["product_id"]: row
        for row in (
            json.loads(line)
            for line in CANONICAL.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    indexed_hashes = {
        row["source_sha256"]
        for row in json.loads(
            INDEX_MANIFEST.read_text(encoding="utf-8")
        )["entries"]
    }
    static_hashes = {
        _sha(path)
        for path in (ROOT / "app" / "static" / "images" / "products").glob(
            "*"
        )
        if path.is_file()
    }

    assert len(images) == 2
    assert {row["duty"] for row in images} == {
        "clear_non_index",
        "background_angle_or_crop",
    }
    for row in images:
        image_path = ROOT / row["local_path"]
        assert image_path.is_file()
        assert _sha(image_path) == row["sha256"]
        assert row["sha256"] not in indexed_hashes
        assert row["sha256"] not in static_hashes
        assert row["source_url"].startswith("https://")
        assert row["expected_product_name"] == canonical[
            row["expected_product_id"]
        ]["fields"]["product_identity"]["value"]
        assert row["ground_truth_status"] == "independently_confirmed"

    assert ground_truth["two_image_upload"]["ordered_product_ids"] == [
        row["expected_product_id"] for row in images
    ]
    assert ground_truth["acceptance"]["high_confidence_wrong_identity"] == 0
