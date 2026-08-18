from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from pydantic import ValidationError

from app.guide.retrieval import CanonicalProduct


MANIFEST_SCHEMA_VERSION = "canonical-decision-runtime-v1"
PRODUCT_SCHEMA_VERSION = "canonical-decision-product-v1"


class CanonicalProductIntegrityError(RuntimeError):
    pass


class UnknownProductError(LookupError):
    pass


class CanonicalProductReader:
    __slots__ = ("_product_ids", "_products")

    def __init__(
        self,
        *,
        manifest_path: str | Path,
        products_path: str | Path,
    ) -> None:
        products = self._load(
            manifest_path=Path(manifest_path),
            products_path=Path(products_path),
        )
        self._products: Mapping[int, CanonicalProduct] = MappingProxyType(
            products
        )
        self._product_ids = frozenset(products)

    @classmethod
    def from_files(
        cls,
        *,
        manifest_path: str | Path,
        products_path: str | Path,
    ) -> CanonicalProductReader:
        return cls(
            manifest_path=manifest_path,
            products_path=products_path,
        )

    @property
    def product_ids(self) -> frozenset[int]:
        return self._product_ids

    def __len__(self) -> int:
        return len(self._products)

    def get(self, product_id: int) -> CanonicalProduct:
        try:
            product = self._products[product_id]
        except KeyError as exc:
            raise UnknownProductError(
                f"unknown product_id {product_id}"
            ) from exc
        return product.model_copy(deep=True)

    @staticmethod
    def _load(
        *,
        manifest_path: Path,
        products_path: Path,
    ) -> dict[int, CanonicalProduct]:
        manifest = _read_manifest(manifest_path)
        _validate_manifest(manifest, products_path)

        try:
            products_bytes = products_path.read_bytes()
        except OSError as exc:
            raise CanonicalProductIntegrityError(
                f"cannot read products file: {products_path}"
            ) from exc

        expected_products_sha = _require_string(
            manifest,
            "products_sha256",
        )
        actual_products_sha = hashlib.sha256(products_bytes).hexdigest()
        if actual_products_sha != expected_products_sha:
            raise CanonicalProductIntegrityError(
                "products SHA-256 mismatch"
            )

        products = _parse_products(products_bytes)
        expected_count = _require_integer(manifest, "product_count")
        if len(products) != expected_count:
            raise CanonicalProductIntegrityError(
                "product_count mismatch: "
                f"manifest={expected_count}, loaded={len(products)}"
            )
        return products


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalProductIntegrityError(
            f"invalid manifest: {path}"
        ) from exc

    if not isinstance(payload, dict):
        raise CanonicalProductIntegrityError(
            "invalid manifest: expected a JSON object"
        )

    expected_digest = _require_string(payload, "manifest_sha256")
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    canonical_json = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    actual_digest = hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()
    if actual_digest != expected_digest:
        raise CanonicalProductIntegrityError(
            "manifest SHA-256 mismatch"
        )
    return payload


def _validate_manifest(
    manifest: dict[str, object],
    products_path: Path,
) -> None:
    manifest_schema = _require_string(manifest, "schema_version")
    if manifest_schema != MANIFEST_SCHEMA_VERSION:
        raise CanonicalProductIntegrityError(
            "unsupported manifest schema version: "
            f"{manifest_schema}"
        )

    product_schema = _require_string(
        manifest,
        "product_schema_version",
    )
    if product_schema != PRODUCT_SCHEMA_VERSION:
        raise CanonicalProductIntegrityError(
            "unsupported product schema version: "
            f"{product_schema}"
        )

    products_file = _require_string(manifest, "products_file")
    if products_file != products_path.name:
        raise CanonicalProductIntegrityError(
            "manifest products_file mismatch: "
            f"manifest={products_file}, supplied={products_path.name}"
        )

    product_count = _require_integer(manifest, "product_count")
    if product_count < 0:
        raise CanonicalProductIntegrityError(
            "manifest product_count must not be negative"
        )


def _parse_products(
    products_bytes: bytes,
) -> dict[int, CanonicalProduct]:
    if not products_bytes:
        raise CanonicalProductIntegrityError("products JSONL is empty")

    try:
        text = products_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalProductIntegrityError(
            "products JSONL is not valid UTF-8"
        ) from exc

    products: dict[int, CanonicalProduct] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise CanonicalProductIntegrityError(
                f"blank JSONL line {line_number}"
            )
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CanonicalProductIntegrityError(
                f"invalid JSONL at line {line_number}"
            ) from exc

        try:
            product = CanonicalProduct.model_validate(payload)
        except ValidationError as exc:
            raise CanonicalProductIntegrityError(
                f"invalid canonical product at line {line_number}"
            ) from exc

        if product.schema_version != PRODUCT_SCHEMA_VERSION:
            raise CanonicalProductIntegrityError(
                "product schema version mismatch at line "
                f"{line_number}: {product.schema_version}"
            )
        if product.product_id in products:
            raise CanonicalProductIntegrityError(
                f"duplicate product_id {product.product_id}"
            )
        products[product.product_id] = product

    if not products:
        raise CanonicalProductIntegrityError("products JSONL is empty")
    return products


def _require_string(
    manifest: dict[str, object],
    field: str,
) -> str:
    value = manifest.get(field)
    if not isinstance(value, str) or not value:
        raise CanonicalProductIntegrityError(
            f"manifest field {field} must be a non-empty string"
        )
    return value


def _require_integer(
    manifest: dict[str, object],
    field: str,
) -> int:
    value = manifest.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise CanonicalProductIntegrityError(
            f"manifest field {field} must be an integer"
        )
    return value
