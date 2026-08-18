from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.guide.adapters.catalog.seed_product_assets import (
    SeedProductAssetIntegrityError,
    load_seed_product_assets,
)


ROOT = Path(__file__).resolve().parents[4]
CANONICAL = ROOT / "data" / "canonical"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _manifest_digest(payload: dict[str, object]) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    return hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()


def _source_images_digest(rows: list[dict[str, object]]) -> str:
    source_digest_text = "\n".join(
        f"{row['product_id']}\t{row['source_image_sha256']}"
        for row in rows
    )
    return hashlib.sha256(source_digest_text.encode("utf-8")).hexdigest()


def _write_assets(
    *,
    manifest_path: Path,
    products_path: Path,
    rows: list[dict[str, object]],
) -> None:
    products_text = "\n".join(_canonical_json(row) for row in rows) + "\n"
    products_path.write_text(products_text, encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["product_count"] = len(rows)
    manifest["products_sha256"] = hashlib.sha256(
        products_text.encode("utf-8")
    ).hexdigest()
    manifest["source_images_sha256"] = _source_images_digest(rows)
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def copied_assets(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    asset_root = (tmp_path / "asset-root").resolve()
    canonical = asset_root / "data" / "canonical"
    canonical.mkdir(parents=True)
    products_path = canonical / "seed_product_images_v1.jsonl"
    manifest_path = canonical / "seed_product_images_v1_manifest.json"

    row = json.loads(
        (
            CANONICAL / "seed_product_images_v1.jsonl"
        ).read_text(encoding="utf-8").splitlines()[0]
    )
    source_image = ROOT / row["relative_path"]
    copied_image = asset_root / row["relative_path"]
    copied_image.parent.mkdir(parents=True)
    shutil.copy2(source_image, copied_image)
    shutil.copy2(
        CANONICAL / "seed_product_images_v1_manifest.json",
        manifest_path,
    )
    _write_assets(
        manifest_path=manifest_path,
        products_path=products_path,
        rows=[row],
    )
    return manifest_path, products_path, asset_root


def test_loads_all_current_seed_product_images() -> None:
    assets = load_seed_product_assets(
        manifest_path=(
            CANONICAL / "seed_product_images_v1_manifest.json"
        ),
        products_path=CANONICAL / "seed_product_images_v1.jsonl",
        asset_root=ROOT,
    )

    assert len(assets) == 103


def test_rejects_invalid_manifest_self_digest(copied_assets) -> None:
    manifest_path, products_path, asset_root = copied_assets
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["source_images_sha256"] = "0" * 64
    manifest_path.write_text(
        _canonical_json(payload) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SeedProductAssetIntegrityError,
        match="manifest SHA-256 mismatch",
    ):
        load_seed_product_assets(
            manifest_path=manifest_path,
            products_path=products_path,
            asset_root=asset_root,
        )


def test_requires_absolute_asset_root(copied_assets) -> None:
    manifest_path, products_path, _ = copied_assets

    with pytest.raises(
        SeedProductAssetIntegrityError,
        match="asset root must be absolute",
    ):
        load_seed_product_assets(
            manifest_path=manifest_path,
            products_path=products_path,
            asset_root=Path("relative-root"),
        )


def test_rejects_image_outside_asset_root(copied_assets) -> None:
    manifest_path, products_path, asset_root = copied_assets
    row = json.loads(products_path.read_text(encoding="utf-8"))
    source_image = asset_root / row["relative_path"]
    outside_image = asset_root.parent / "outside.png"
    shutil.copy2(source_image, outside_image)
    row["relative_path"] = "../outside.png"
    _write_assets(
        manifest_path=manifest_path,
        products_path=products_path,
        rows=[row],
    )

    with pytest.raises(
        SeedProductAssetIntegrityError,
        match="escapes asset root",
    ):
        load_seed_product_assets(
            manifest_path=manifest_path,
            products_path=products_path,
            asset_root=asset_root,
        )


def test_rejects_missing_image_file(copied_assets) -> None:
    manifest_path, products_path, asset_root = copied_assets
    row = json.loads(products_path.read_text(encoding="utf-8"))
    (asset_root / row["relative_path"]).unlink()

    with pytest.raises(
        SeedProductAssetIntegrityError,
        match="missing seed product image",
    ):
        load_seed_product_assets(
            manifest_path=manifest_path,
            products_path=products_path,
            asset_root=asset_root,
        )


def test_rejects_image_size_mismatch(copied_assets) -> None:
    manifest_path, products_path, asset_root = copied_assets
    row = json.loads(products_path.read_text(encoding="utf-8"))
    image_path = asset_root / row["relative_path"]
    image_path.write_bytes(image_path.read_bytes() + b"\0")

    with pytest.raises(
        SeedProductAssetIntegrityError,
        match="image size mismatch",
    ):
        load_seed_product_assets(
            manifest_path=manifest_path,
            products_path=products_path,
            asset_root=asset_root,
        )


def test_rejects_image_sha_mismatch_with_same_size(copied_assets) -> None:
    manifest_path, products_path, asset_root = copied_assets
    row = json.loads(products_path.read_text(encoding="utf-8"))
    image_path = asset_root / row["relative_path"]
    payload = image_path.read_bytes()
    image_path.write_bytes(bytes([payload[0] ^ 0xFF]) + payload[1:])

    with pytest.raises(
        SeedProductAssetIntegrityError,
        match="image SHA-256 mismatch",
    ):
        load_seed_product_assets(
            manifest_path=manifest_path,
            products_path=products_path,
            asset_root=asset_root,
        )
