from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductIntegrityError,
    CanonicalProductReader,
    UnknownProductError,
)
from app.guide.retrieval import CanonicalProduct


ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "data/canonical"
MANIFEST_NAME = "core_products_v1_manifest.json"
PRODUCTS_NAME = "core_products_v1.jsonl"


def canonical_sha256(payload: dict[str, object]) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_manifest(path: Path, payload: dict[str, object]) -> None:
    payload["manifest_sha256"] = canonical_sha256(payload)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def refresh_products_integrity(
    manifest_path: Path,
    products_path: Path,
    *,
    product_count: int | None = None,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["products_sha256"] = hashlib.sha256(
        products_path.read_bytes()
    ).hexdigest()
    if product_count is not None:
        manifest["product_count"] = product_count
    write_manifest(manifest_path, manifest)


@pytest.fixture
def copied_assets(tmp_path: Path) -> tuple[Path, Path]:
    manifest_path = tmp_path / MANIFEST_NAME
    products_path = tmp_path / PRODUCTS_NAME
    shutil.copy2(CANONICAL / MANIFEST_NAME, manifest_path)
    shutil.copy2(CANONICAL / PRODUCTS_NAME, products_path)
    return manifest_path, products_path


def make_reader(
    manifest_path: Path = CANONICAL / MANIFEST_NAME,
    products_path: Path = CANONICAL / PRODUCTS_NAME,
) -> CanonicalProductReader:
    return CanonicalProductReader.from_files(
        manifest_path=manifest_path,
        products_path=products_path,
    )


def test_reader_loads_103_real_products_as_retrieval_contracts() -> None:
    reader = make_reader()

    assert len(reader) == 103
    assert len(reader.product_ids) == 103

    product = reader.get(24)
    assert isinstance(product, CanonicalProduct)
    assert product.product_id == 24
    assert product.schema_version == "canonical-decision-product-v1"


def test_reader_rejects_invalid_manifest_self_digest(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["product_count"] = 102
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="manifest SHA-256",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_products_sha_mismatch(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    products_path.write_bytes(products_path.read_bytes() + b" ")

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="products SHA-256",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_unsupported_manifest_schema(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "canonical-decision-runtime-v2"
    write_manifest(manifest_path, manifest)

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="manifest schema version",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_product_row_schema_mismatch(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    lines = products_path.read_text(encoding="utf-8").splitlines()
    first_product = json.loads(lines[0])
    first_product["schema_version"] = "canonical-decision-product-v2"
    lines[0] = json.dumps(
        first_product,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    products_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    refresh_products_integrity(manifest_path, products_path)

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="product schema version",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_product_count_mismatch(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["product_count"] = 102
    write_manifest(manifest_path, manifest)

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="product_count",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_empty_jsonl(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    products_path.write_bytes(b"")
    refresh_products_integrity(
        manifest_path,
        products_path,
        product_count=0,
    )

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="JSONL is empty",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_blank_jsonl_line(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    lines = products_path.read_text(encoding="utf-8").splitlines()
    products_path.write_text(
        "\n".join([lines[0], "", *lines[1:]]) + "\n",
        encoding="utf-8",
    )
    refresh_products_integrity(manifest_path, products_path)

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="blank JSONL line 2",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_invalid_jsonl(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    lines = products_path.read_text(encoding="utf-8").splitlines()
    lines[0] = "{not-json}"
    products_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    refresh_products_integrity(manifest_path, products_path)

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="invalid JSONL at line 1",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_jsonl_row_outside_retrieval_contract(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    lines = products_path.read_text(encoding="utf-8").splitlines()
    lines[0] = json.dumps(
        {
            "product_id": 24,
            "schema_version": "canonical-decision-product-v1",
        }
    )
    products_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    refresh_products_integrity(manifest_path, products_path)

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="invalid canonical product at line 1",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_duplicate_product_id(
    copied_assets: tuple[Path, Path],
) -> None:
    manifest_path, products_path = copied_assets
    lines = products_path.read_text(encoding="utf-8").splitlines()
    lines.append(lines[0])
    products_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    refresh_products_integrity(
        manifest_path,
        products_path,
        product_count=104,
    )

    with pytest.raises(
        CanonicalProductIntegrityError,
        match="duplicate product_id 24",
    ):
        make_reader(manifest_path, products_path)


def test_reader_rejects_unknown_product_id() -> None:
    reader = make_reader()

    with pytest.raises(UnknownProductError, match="unknown product_id 999999"):
        reader.get(999999)
