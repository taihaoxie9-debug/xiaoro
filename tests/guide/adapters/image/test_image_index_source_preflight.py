from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.guide.adapters.image.index_source_preflight import (
    ImageSourcePreflightError,
    preflight_image_sources,
)


ROOT = Path(__file__).resolve().parents[4]
CANONICAL = ROOT / "data" / "canonical"
MANIFEST = CANONICAL / "seed_product_images_v1_manifest.json"
PRODUCTS = CANONICAL / "seed_product_images_v1.jsonl"


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


def _source_digest(rows: list[dict[str, object]]) -> str:
    value = "\n".join(
        f"{row['product_id']}\t{row['source_image_sha256']}"
        for row in rows
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_snapshot(
    *,
    manifest_path: Path,
    products_path: Path,
    rows: list[dict[str, object]],
) -> None:
    products_text = "\n".join(
        _canonical_json(row) for row in rows
    ) + "\n"
    products_path.write_text(products_text, encoding="utf-8")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["product_count"] = len(rows)
    manifest["products_file"] = products_path.name
    manifest["products_sha256"] = hashlib.sha256(
        products_text.encode("utf-8")
    ).hexdigest()
    manifest["source_images_sha256"] = _source_digest(rows)
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def source_snapshot(
    tmp_path: Path,
) -> tuple[Path, Path, Path, list[dict[str, object]]]:
    source_root = (tmp_path / "source-root").resolve()
    copied_canonical = source_root / "data" / "canonical"
    copied_canonical.mkdir(parents=True)
    manifest_path = (
        copied_canonical / "seed_product_images_v1_manifest.json"
    )
    products_path = copied_canonical / "seed_product_images_v1.jsonl"

    rows = [
        json.loads(line)
        for line in PRODUCTS.read_text(encoding="utf-8").splitlines()[:2]
    ]
    for row in rows:
        source = ROOT / str(row["relative_path"])
        target = source_root / str(row["relative_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    _write_snapshot(
        manifest_path=manifest_path,
        products_path=products_path,
        rows=rows,
    )
    return manifest_path, products_path, source_root, rows


def test_preflights_all_103_real_canonical_images_read_only() -> None:
    before_manifest = MANIFEST.read_bytes()
    before_products = PRODUCTS.read_bytes()

    report = preflight_image_sources(
        manifest_path=MANIFEST,
        products_path=PRODUCTS,
        source_root=ROOT,
    )

    assert len(report.sources) == 103
    assert tuple(item.product_id for item in report.sources) == tuple(
        sorted(item.product_id for item in report.sources)
    )
    assert len({item.product_id for item in report.sources}) == 103
    assert len({item.source_path for item in report.sources}) == 103
    assert report.source_manifest_sha256 == (
        "f41e52c23c9ad3ba8a823b2f62791a427ac4d5392446471c2088c503996ae6bc"
    )
    assert report.source_products_sha256 == (
        "5a5a0c40deb80050b59b52203339497c73c3df1adc37b90799b1a62b1e5d9ab0"
    )
    assert MANIFEST.read_bytes() == before_manifest
    assert PRODUCTS.read_bytes() == before_products


def test_rejects_missing_source_image(source_snapshot) -> None:
    manifest_path, products_path, source_root, rows = source_snapshot
    (source_root / str(rows[0]["relative_path"])).unlink()

    with pytest.raises(
        ImageSourcePreflightError,
        match="missing source image.*24",
    ):
        preflight_image_sources(
            manifest_path=manifest_path,
            products_path=products_path,
            source_root=source_root,
            expected_count=2,
        )

def test_rejects_source_byte_drift(source_snapshot) -> None:
    manifest_path, products_path, source_root, rows = source_snapshot
    image_path = source_root / str(rows[0]["relative_path"])
    image_path.write_bytes(image_path.read_bytes() + b"\0")

    with pytest.raises(
        ImageSourcePreflightError,
        match="source image bytes mismatch.*24",
    ):
        preflight_image_sources(
            manifest_path=manifest_path,
            products_path=products_path,
            source_root=source_root,
            expected_count=2,
        )


def test_rejects_same_size_source_sha_drift(source_snapshot) -> None:
    manifest_path, products_path, source_root, rows = source_snapshot
    image_path = source_root / str(rows[0]["relative_path"])
    content = image_path.read_bytes()
    image_path.write_bytes(bytes([content[0] ^ 0xFF]) + content[1:])

    with pytest.raises(
        ImageSourcePreflightError,
        match="source image SHA-256 mismatch.*24",
    ):
        preflight_image_sources(
            manifest_path=manifest_path,
            products_path=products_path,
            source_root=source_root,
            expected_count=2,
        )


def test_rejects_duplicate_product_id(source_snapshot) -> None:
    manifest_path, products_path, source_root, rows = source_snapshot
    rows[1]["product_id"] = rows[0]["product_id"]
    _write_snapshot(
        manifest_path=manifest_path,
        products_path=products_path,
        rows=rows,
    )

    with pytest.raises(
        ImageSourcePreflightError,
        match="duplicate product_id 24",
    ):
        preflight_image_sources(
            manifest_path=manifest_path,
            products_path=products_path,
            source_root=source_root,
            expected_count=2,
        )


def test_rejects_duplicate_source_path(source_snapshot) -> None:
    manifest_path, products_path, source_root, rows = source_snapshot
    rows[1]["relative_path"] = rows[0]["relative_path"]
    _write_snapshot(
        manifest_path=manifest_path,
        products_path=products_path,
        rows=rows,
    )

    with pytest.raises(
        ImageSourcePreflightError,
        match="duplicate source path",
    ):
        preflight_image_sources(
            manifest_path=manifest_path,
            products_path=products_path,
            source_root=source_root,
            expected_count=2,
        )


def test_rejects_unstable_product_id_order(source_snapshot) -> None:
    manifest_path, products_path, source_root, rows = source_snapshot
    rows.reverse()
    _write_snapshot(
        manifest_path=manifest_path,
        products_path=products_path,
        rows=rows,
    )

    with pytest.raises(
        ImageSourcePreflightError,
        match="stable numeric product_id order",
    ):
        preflight_image_sources(
            manifest_path=manifest_path,
            products_path=products_path,
            source_root=source_root,
            expected_count=2,
        )


def test_wraps_source_root_symlink_loop_without_path_disclosure(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source-loop"
    source_root.symlink_to(source_root, target_is_directory=True)

    with pytest.raises(
        ImageSourcePreflightError,
        match="cannot resolve source root",
    ) as caught:
        preflight_image_sources(
            manifest_path=tmp_path / "manifest.json",
            products_path=tmp_path / "products.jsonl",
            source_root=source_root,
            expected_count=2,
        )

    assert str(source_root) not in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [
        OSError("secret filesystem detail"),
        RuntimeError("secret symlink detail"),
    ],
)
def test_wraps_source_root_resolution_errors(
    source_snapshot,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    manifest_path, products_path, source_root, _ = source_snapshot
    original_resolve = Path.resolve

    def fail_source_root_resolve(path: Path, *args, **kwargs):
        if path == source_root:
            raise failure
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_source_root_resolve)

    with pytest.raises(
        ImageSourcePreflightError,
        match="cannot resolve source root",
    ) as caught:
        preflight_image_sources(
            manifest_path=manifest_path,
            products_path=products_path,
            source_root=source_root,
            expected_count=2,
        )

    assert "secret" not in str(caught.value)
    assert str(source_root) not in str(caught.value)
