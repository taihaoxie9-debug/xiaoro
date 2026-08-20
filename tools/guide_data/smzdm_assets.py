"""Validate SMZDM raw-page captures before any product-data promotion."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping


_AIGC_MARKERS = (
    "powered by zdm-aigc",
    "zdm-aigc engine",
)
_REQUIRED_EXCLUSIONS = {
    "Powered by ZDM-AIGC Engine v0.3",
    "优势",
    "建议",
}


class SmzdmAssetValidationError(ValueError):
    """Raised when a crawl candidate lacks auditable human review."""


def build_review_candidate(
    raw_page: Mapping[str, object],
    review: Mapping[str, object],
) -> dict[str, object]:
    """Create a hash-bound review record without promoting product facts."""
    normalized_raw = _normalize_raw_page(raw_page)
    normalized_review = _normalize_review(
        review,
        image_url=normalized_raw["main_image_url"],
        image_sha256=normalized_raw["main_image_sha256"],
        page_specification=normalized_raw["page_specification"],
    )
    candidate = {
        "canonical_product_id": normalized_raw["canonical_product_id"],
        "category": normalized_review["category"],
        "source_url": normalized_raw["page_url"],
        "source_title": normalized_raw["page_title"],
        "source_product_title": normalized_raw["product_title"],
        "captured_at": normalized_raw["captured_at"],
        "source_page_text_sha256": normalized_raw[
            "raw_page_text_sha256"
        ],
        "sku_match_evidence": normalized_review["sku_match_evidence"],
        "candidate_fields": normalized_review["candidate_fields"],
        "image_review": normalized_review["image_review"],
        "existing_asset_conflicts": normalized_review[
            "existing_asset_conflicts"
        ],
        "fact_promotion_status": (
            "deferred"
            if normalized_review["existing_asset_conflicts"]
            else "pending"
        ),
        "reviewed_by": normalized_review["reviewed_by"],
        "reviewed_at": normalized_review["reviewed_at"],
        "review_reason": normalized_review["review_reason"],
    }
    candidate_id = hashlib.sha256(
        _canonical_json({
            "canonical_product_id": candidate["canonical_product_id"],
            "source_url": candidate["source_url"],
            "source_page_text_sha256": candidate[
                "source_page_text_sha256"
            ],
            "candidate_fields": candidate["candidate_fields"],
            "image_review": candidate["image_review"],
            "existing_asset_conflicts": candidate[
                "existing_asset_conflicts"
            ],
        }).encode("utf-8")
    ).hexdigest()
    return {"candidate_id": candidate_id, **candidate}


def _normalize_raw_page(
    raw_page: Mapping[str, object],
) -> dict[str, object]:
    product_id = raw_page.get("canonical_product_id")
    if not isinstance(product_id, int) or isinstance(product_id, bool) or product_id < 1:
        raise SmzdmAssetValidationError(
            "canonical_product_id must be a positive integer"
        )
    excluded_sections = _required_texts(raw_page, "excluded_sections")
    if not _REQUIRED_EXCLUSIONS <= set(excluded_sections):
        raise SmzdmAssetValidationError(
            "raw page must explicitly exclude SMZDM AIGC sections"
        )
    product_introduction = _required_text(
        raw_page,
        "raw_product_introduction",
    )
    if _contains_aigc(product_introduction):
        raise SmzdmAssetValidationError(
            "raw_product_introduction must exclude AIGC content"
        )
    return {
        "canonical_product_id": product_id,
        "page_url": _required_https(raw_page, "page_url"),
        "captured_at": _required_text(raw_page, "captured_at"),
        "page_title": _required_text(raw_page, "page_title"),
        "product_title": _required_text(raw_page, "product_title"),
        "page_specification": _required_text(
            raw_page,
            "page_specification",
        ),
        "main_image_url": _required_https(raw_page, "main_image_url"),
        "main_image_sha256": _optional_sha256(
            raw_page.get("main_image_sha256"),
        ),
        "raw_page_text_sha256": _required_sha256(
            raw_page,
            "raw_page_text_sha256",
        ),
    }


def _normalize_review(
    review: Mapping[str, object],
    *,
    image_url: str,
    image_sha256: str | None,
    page_specification: str,
) -> dict[str, object]:
    image_review = review.get("image_review")
    if not isinstance(image_review, Mapping):
        raise SmzdmAssetValidationError("image_review must be an object")
    image_status = image_review.get("status")
    try:
        sku_match_evidence = _required_texts(
            review,
            "sku_match_evidence",
        )
    except SmzdmAssetValidationError as exc:
        raise SmzdmAssetValidationError(
            "approved image requires SKU evidence and image SHA-256"
        ) from exc
    if (
        image_status != "approved"
        or not sku_match_evidence
        or image_sha256 is None
        or not image_url
    ):
        raise SmzdmAssetValidationError(
            "approved image requires SKU evidence and image SHA-256"
        )
    candidate_fields = review.get("candidate_fields")
    if not isinstance(candidate_fields, Mapping):
        raise SmzdmAssetValidationError("candidate_fields must be an object")
    normalized_fields = {
        "net_content": _required_text(candidate_fields, "net_content"),
        "efficacy_positioning": _required_texts(
            candidate_fields,
            "efficacy_positioning",
        ),
        "hero_ingredients": _required_texts(
            candidate_fields,
            "hero_ingredients",
        ),
        "brand_technology": _required_texts(
            candidate_fields,
            "brand_technology",
        ),
    }
    if _contains_aigc(_canonical_json(normalized_fields)):
        raise SmzdmAssetValidationError(
            "AIGC content cannot enter candidate fields"
        )
    if _normalize_specification(
        normalized_fields["net_content"]
    ) != _normalize_specification(page_specification):
        raise SmzdmAssetValidationError(
            "candidate specification conflicts with source page"
        )
    conflicts = _normalize_conflicts(
        review.get("existing_asset_conflicts", ()),
        source_specification=normalized_fields["net_content"],
    )
    return {
        "category": _required_text(review, "category"),
        "sku_match_evidence": sku_match_evidence,
        "candidate_fields": normalized_fields,
        "image_review": {
            "status": "approved",
            "source_url": image_url,
            "source_sha256": image_sha256,
            "background_assessment": _required_text(
                image_review,
                "background_assessment",
            ),
            "sku_match_assessment": _required_text(
                image_review,
                "sku_match_assessment",
            ),
        },
        "existing_asset_conflicts": conflicts,
        "reviewed_by": _required_text(review, "reviewed_by"),
        "reviewed_at": _required_text(review, "reviewed_at"),
        "review_reason": _required_text(review, "review_reason"),
    }


def _normalize_conflicts(
    value: object,
    *,
    source_specification: str,
) -> list[dict[str, str]]:
    if not isinstance(value, (tuple, list)):
        raise SmzdmAssetValidationError(
            "existing_asset_conflicts must be a list"
        )
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise SmzdmAssetValidationError(
                "existing asset conflict must be an object"
            )
        conflict = {
            "field": _required_text(item, "field"),
            "existing_value": _required_text(item, "existing_value"),
            "source_value": _required_text(item, "source_value"),
            "resolution": _required_text(item, "resolution"),
        }
        if (
            conflict["field"] != "net_content"
            or conflict["resolution"] != "defer_fact_promotion"
            or _normalize_specification(conflict["source_value"])
            != _normalize_specification(source_specification)
        ):
            raise SmzdmAssetValidationError(
                "existing asset conflict is not a deferred specification conflict"
            )
        normalized.append(conflict)
    return normalized


def _required_text(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SmzdmAssetValidationError(f"{key} must be non-empty text")
    return value.strip()


def _required_texts(
    payload: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, (tuple, list)):
        raise SmzdmAssetValidationError(f"{key} must be a text list")
    normalized = tuple(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )
    if len(normalized) != len(value) or not normalized:
        raise SmzdmAssetValidationError(
            f"{key} must contain non-empty text"
        )
    return normalized


def _required_https(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = _required_text(payload, key)
    if not value.startswith("https://"):
        raise SmzdmAssetValidationError(f"{key} must use https")
    return value


def _required_sha256(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = _optional_sha256(payload.get(key))
    if value is None:
        raise SmzdmAssetValidationError(f"{key} must be a SHA-256")
    return value


def _optional_sha256(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if (
        len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SmzdmAssetValidationError("image SHA-256 is invalid")
    return value


def _normalize_specification(value: str) -> str:
    return value.casefold().replace(" ", "").replace("毫升", "ml")


def _contains_aigc(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in _AIGC_MARKERS)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
