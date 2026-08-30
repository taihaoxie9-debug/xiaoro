from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ProductDisplayBinding(_StrictFrozen):
    product_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=512)
    identity_status: Literal[
        "exact_product",
        "exact_product_variant",
        "family",
    ]
    source_sku: str = Field(min_length=1, max_length=512)
    canonical_sku: str = Field(min_length=1, max_length=512)
    reference_price_sku: str = Field(min_length=1, max_length=512)
    display_specification: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    price_specification_alignment: Literal[
        "aligned",
        "unresolved",
        "conflict",
    ]
    source_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    display_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        for value in (
            self.display_name,
            self.source_sku,
            self.canonical_sku,
            self.reference_price_sku,
        ):
            if value != value.strip():
                raise ValueError(
                    "product display binding strings must be trimmed"
                )
        if (
            self.display_specification is not None
            and self.display_specification
            != self.display_specification.strip()
        ):
            raise ValueError(
                "display specification must be trimmed"
            )
        if (
            self.price_specification_alignment == "aligned"
            and self.display_specification is None
        ):
            raise ValueError(
                "aligned binding requires display specification"
            )
        if (
            self.price_specification_alignment == "aligned"
            and len({
                self.source_sku,
                self.canonical_sku,
                self.reference_price_sku,
            }) != 1
        ):
            raise ValueError(
                "aligned binding requires exact SKU equality"
            )
        return self


class ProductDisplayManifest(_StrictFrozen):
    schema_version: Literal[
        "guide-product-display-bindings-v1"
    ] = "guide-product-display-bindings-v1"
    asset_id: Literal[
        "guide-product-display-bindings"
    ] = "guide-product-display-bindings"
    records_file: str = Field(
        pattern=(
            r"^product_display_bindings_v1\."
            r"[0-9a-f]{64}\.jsonl$"
        )
    )
    records_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    display_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(gt=0)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.records_file != (
            "product_display_bindings_v1."
            f"{self.records_sha256}.jsonl"
        ):
            raise ValueError("product display file hash mismatch")
        expected = _hash_json(
            self.model_dump(
                mode="json",
                exclude={"manifest_sha256"},
            )
        )
        if self.manifest_sha256 != expected:
            raise ValueError("product display manifest self-hash mismatch")
        return self


class ProductDisplayAssets(_StrictFrozen):
    manifest: ProductDisplayManifest
    records: tuple[ProductDisplayBinding, ...]

    @field_validator("records", mode="before")
    @classmethod
    def freeze_records(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


def load_product_display_assets(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
) -> ProductDisplayAssets:
    manifest_file = Path(manifest_path)
    manifest = ProductDisplayManifest.model_validate_json(
        manifest_file.read_text(encoding="utf-8"),
        strict=True,
    )
    if manifest.manifest_sha256 != expected_manifest_sha256:
        raise ValueError("product display runtime manifest lock mismatch")
    records_path = manifest_file.parent / manifest.records_file
    records_bytes = records_path.read_bytes()
    if sha256(records_bytes).hexdigest() != manifest.records_sha256:
        raise ValueError("product display records SHA mismatch")
    records = tuple(
        ProductDisplayBinding.model_validate_json(line, strict=True)
        for line in records_bytes.decode("utf-8").splitlines()
        if line.strip()
    )
    if len(records) != manifest.record_count:
        raise ValueError("product display record count mismatch")
    product_ids = tuple(record.product_id for record in records)
    if product_ids != tuple(sorted(set(product_ids))):
        raise ValueError(
            "product display records must be sorted and unique"
        )
    return ProductDisplayAssets(
        manifest=manifest,
        records=records,
    )


class ProductDisplayBindingReader:
    __slots__ = ("assets", "_by_product_id")

    def __init__(self, assets: ProductDisplayAssets) -> None:
        if not isinstance(assets, ProductDisplayAssets):
            raise TypeError("assets must be ProductDisplayAssets")
        self.assets = assets
        self._by_product_id = {
            record.product_id: record
            for record in assets.records
        }

    def get(self, product_id: int) -> ProductDisplayBinding:
        try:
            return self._by_product_id[product_id]
        except KeyError as exc:
            raise KeyError(
                f"unknown product display binding {product_id}"
            ) from exc

    def get_optional(
        self,
        product_id: int,
    ) -> ProductDisplayBinding | None:
        return self._by_product_id.get(product_id)

    def price_bound_specification(
        self,
        product_id: int,
    ) -> str | None:
        binding = self.get_optional(product_id)
        if (
            binding is None
            or binding.price_specification_alignment != "aligned"
        ):
            return None
        return binding.display_specification


def _hash_json(value: object) -> str:
    return sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = [
    "ProductDisplayAssets",
    "ProductDisplayBinding",
    "ProductDisplayBindingReader",
    "ProductDisplayManifest",
    "load_product_display_assets",
]
