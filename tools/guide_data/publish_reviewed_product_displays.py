"""Publish reviewed SKU/display bindings without inferring alignment."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.retrieval.product_display_assets import (
    ProductDisplayBinding,
    ProductDisplayManifest,
    load_product_display_assets,
)
from tools.guide_data.review_smzdm_product import (
    validate_reviewed_product_packet,
)


@dataclass(frozen=True, slots=True)
class ProductDisplayPublishResult:
    manifest_path: Path
    records_path: Path
    record_count: int


class ReviewedProductDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[
        "reviewed-product-display-v1"
    ] = "reviewed-product-display-v1"
    product_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=512)
    display_specification: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    source_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_by: Literal["main-agent-product-display-review"]
    reviewed_at: datetime
    review_rationale: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        values = (
            self.display_name,
            self.review_rationale,
        )
        if any(value != value.strip() for value in values):
            raise ValueError("display review strings must be trimmed")
        if (
            self.display_specification is not None
            and self.display_specification
            != self.display_specification.strip()
        ):
            raise ValueError(
                "display review specification must be trimmed"
            )
        return self


def publish_reviewed_product_display_assets(
    *,
    review_paths: Sequence[Path],
    display_review_path: Path,
    output_dir: Path,
) -> ProductDisplayPublishResult:
    if not review_paths:
        raise ValueError("review_paths must not be empty")
    display_review_file = Path(display_review_path)
    display_review_bytes = display_review_file.read_bytes()
    display_reviews = _load_display_reviews(display_review_bytes)
    source_paths = tuple(Path(path) for path in review_paths)
    source_ids = tuple(
        int(json.loads(path.read_text(encoding="utf-8"))["product_id"])
        for path in source_paths
    )
    display_ids = tuple(review.product_id for review in display_reviews)
    if tuple(sorted(source_ids)) != display_ids:
        raise ValueError(
            "display review product IDs must exactly cover source reviews"
        )
    display_by_id = {
        review.product_id: review for review in display_reviews
    }
    records = tuple(
        sorted(
            (
                _binding_from_review(
                    path,
                    display_review=display_by_id[
                        int(json.loads(
                            path.read_text(encoding="utf-8")
                        )["product_id"])
                    ],
                )
                for path in source_paths
            ),
            key=lambda item: item.product_id,
        )
    )
    if len({record.product_id for record in records}) != len(records):
        raise ValueError("duplicate product display binding")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    records_bytes = b"".join(
        _canonical_json(record.model_dump(mode="json")) + b"\n"
        for record in records
    )
    records_sha256 = sha256(records_bytes).hexdigest()
    records_path = output / (
        "product_display_bindings_v1."
        f"{records_sha256}.jsonl"
    )
    records_path.write_bytes(records_bytes)
    manifest_payload = {
        "schema_version": "guide-product-display-bindings-v1",
        "asset_id": "guide-product-display-bindings",
        "records_file": records_path.name,
        "records_sha256": records_sha256,
        "display_review_sha256": sha256(
            display_review_bytes
        ).hexdigest(),
        "record_count": len(records),
    }
    manifest_payload["manifest_sha256"] = sha256(
        _canonical_json(manifest_payload)
    ).hexdigest()
    manifest = ProductDisplayManifest.model_validate(
        manifest_payload,
        strict=True,
    )
    manifest_path = output / "product_display_bindings_v1_manifest.json"
    manifest_path.write_bytes(
        _canonical_json(manifest.model_dump(mode="json")) + b"\n"
    )
    load_product_display_assets(
        manifest_path=manifest_path,
        expected_manifest_sha256=manifest.manifest_sha256,
    )
    return ProductDisplayPublishResult(
        manifest_path=manifest_path,
        records_path=records_path,
        record_count=len(records),
    )


def _binding_from_review(
    path: Path,
    *,
    display_review: ReviewedProductDisplay,
) -> ProductDisplayBinding:
    raw_bytes = path.read_bytes()
    raw = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("review packet must be an object")
    packet = validate_reviewed_product_packet(raw)
    source_review_sha256 = sha256(raw_bytes).hexdigest()
    if display_review.source_review_sha256 != source_review_sha256:
        raise ValueError(
            "display review source packet SHA mismatch"
        )
    if display_review.product_id != int(packet["product_id"]):
        raise ValueError("display review product ID mismatch")
    audit = packet["sku_audit"]
    if not isinstance(audit, dict):
        raise ValueError("review packet SKU audit is invalid")
    alignment = str(audit["price_specification_alignment"])
    if (
        alignment == "aligned"
        and display_review.display_specification is None
    ):
        raise ValueError(
            "aligned SKU requires reviewed display specification"
        )
    return ProductDisplayBinding(
        product_id=int(packet["product_id"]),
        display_name=display_review.display_name,
        identity_status=str(audit["identity_status"]),
        source_sku=str(audit["source_sku"]),
        canonical_sku=str(audit["canonical_sku"]),
        reference_price_sku=str(audit["reference_price_sku"]),
        display_specification=display_review.display_specification,
        price_specification_alignment=alignment,
        source_review_sha256=source_review_sha256,
        display_review_sha256=sha256(
            _canonical_json(
                display_review.model_dump(mode="json")
            )
        ).hexdigest(),
    )


def _load_display_reviews(
    payload: bytes,
) -> tuple[ReviewedProductDisplay, ...]:
    reviews = tuple(
        ReviewedProductDisplay.model_validate_json(line, strict=True)
        for line in payload.decode("utf-8").splitlines()
        if line.strip()
    )
    if not reviews:
        raise ValueError("display review file must not be empty")
    product_ids = tuple(review.product_id for review in reviews)
    if product_ids != tuple(sorted(set(product_ids))):
        raise ValueError(
            "display reviews must be sorted and unique"
        )
    return reviews


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = [
    "ProductDisplayPublishResult",
    "ReviewedProductDisplay",
    "publish_reviewed_product_display_assets",
]
