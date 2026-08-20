from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.build_seed_image_manifest import build_seed_image_manifest


ROOT = Path(__file__).resolve().parents[2]


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_digest(payload: dict) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    text = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_seed_image_manifest_is_complete_and_deterministic(
    tmp_path: Path,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = build_seed_image_manifest(
        root=ROOT,
        seed_dump=ROOT / "data/seed_dump.sql",
        output_dir=first_dir,
    )
    second = build_seed_image_manifest(
        root=ROOT,
        seed_dump=ROOT / "data/seed_dump.sql",
        output_dir=second_dir,
    )

    first_jsonl = first_dir / "seed_product_images_v1.jsonl"
    second_jsonl = second_dir / "seed_product_images_v1.jsonl"
    assert first_jsonl.read_bytes() == second_jsonl.read_bytes()
    assert first == second

    rows = [
        json.loads(line)
        for line in first_jsonl.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert len(rows) == 103
    assert len({row["product_id"] for row in rows}) == 103
    assert len({row["image_url"] for row in rows}) == 103

    for row in rows:
        path = ROOT / row["relative_path"]
        assert path.is_file()
        assert row["source_image_sha256"] == sha256_path(path)
        assert row["bytes"] == path.stat().st_size
        assert row["media_type"] in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }

    assert first["schema_version"] == "seed-product-images-v1"
    assert first["product_count"] == 103
    assert first["manifest_sha256"] == manifest_digest(first)
