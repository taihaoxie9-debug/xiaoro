"""Assemble one SMZDM product packet for explicit human review."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal, Mapping, Sequence

from tools.guide_data.smzdm_category_policy import (
    build_review_packet,
    fields_for_profile,
)


SourceMatch = Literal["exact", "family", "variant_review"]
PriceSpecificationAlignment = Literal["aligned", "unresolved", "conflict"]


class SmzdmProductReviewPacketError(ValueError):
    """Raised when raw evidence cannot form an auditable review packet."""


def validate_reviewed_product_packet(
    packet: Mapping[str, object],
) -> dict[str, object]:
    """Validate explicit human decisions without inferring approval."""
    product_id = _positive_int(packet.get("product_id"), "product_id")
    review_status = _text(
        packet.get("review_status"),
        "review_status",
    )
    if review_status not in {
        "human_review_complete",
        "no_promotion",
    }:
        raise SmzdmProductReviewPacketError(
            "review_status must record a terminal human decision"
        )
    sku_audit = _validate_sku_audit(packet.get("sku_audit"))
    review_fields = set(
        _text_sequence(
            packet.get("review_field_policy"),
            "review_field_policy",
        )
    )
    detail_images = _image_rows(packet.get("detail_images"))
    detail_ordinals = {
        _positive_int(row.get("ordinal"), "detail image ordinal")
        for row in detail_images
    }
    detail_refs_by_ordinal = {
        _positive_int(
            row.get("ordinal"),
            "detail image ordinal",
        ): "smzdm-detail-image:"
        + _sha256_text(
            row.get("sha256"),
            "detail image sha256",
        )
        for row in detail_images
    }
    raw_facts = packet.get("candidate_facts")
    if not isinstance(raw_facts, list):
        raise SmzdmProductReviewPacketError(
            "candidate_facts must be a list"
        )
    owned_source_refs: set[str] = set()
    body_source_ref: str | None = None
    if raw_facts:
        page_sha256 = _sha256_text(
            packet.get("source_page_text_sha256"),
            "source_page_text_sha256",
        )
        body_source_ref = f"smzdm-browser-body:{page_sha256}"
        owned_source_refs.add(body_source_ref)
        owned_source_refs.update(
            "smzdm-detail-image:"
            + _sha256_text(
                row.get("sha256"),
                "detail image sha256",
            )
            for row in detail_images
        )
    if review_status == "no_promotion" and raw_facts:
        raise SmzdmProductReviewPacketError(
            "no_promotion review cannot contain candidate facts"
        )
    if review_status == "human_review_complete" and not raw_facts:
        raise SmzdmProductReviewPacketError(
            "completed review requires explicit candidate decisions"
        )

    facts: list[dict[str, object]] = []
    fact_ids: set[str] = set()
    approved_count = 0
    allowed_use_values = {
        "product_knowledge",
        "recommendation",
        "comparison",
        "compact_tag",
    }
    for raw_fact in raw_facts:
        if not isinstance(raw_fact, Mapping):
            raise SmzdmProductReviewPacketError(
                "candidate fact must be an object"
            )
        fact = dict(raw_fact)
        fact_id = _text(fact.get("fact_id"), "fact_id")
        if (
            not fact_id.startswith(f"reviewed:product:{product_id}:")
            or fact_id in fact_ids
        ):
            raise SmzdmProductReviewPacketError(
                "fact_id must be product-owned and unique"
            )
        fact_ids.add(fact_id)
        field_key = _text(fact.get("field_key"), "field_key")
        if field_key not in review_fields:
            raise SmzdmProductReviewPacketError(
                "candidate fact field is outside category review policy"
            )
        _text(fact.get("public_text"), "public_text")
        source_kind = _text(
            fact.get("source_kind"),
            "source_kind",
        )
        source_refs = _text_sequence(
            fact.get("source_refs"),
            "source_refs",
        )
        if not source_refs:
            raise SmzdmProductReviewPacketError(
                "candidate fact requires source_refs"
            )
        if not set(source_refs) <= owned_source_refs:
            raise SmzdmProductReviewPacketError(
                "source_refs are not owned by review packet"
            )
        source_ordinal = fact.get("source_ordinal")
        if source_kind == "detail_image" and source_ordinal is None:
            raise SmzdmProductReviewPacketError(
                "detail image source requires source_ordinal"
            )
        if (
            source_kind in {"parameter_table", "product_introduction"}
            and body_source_ref not in source_refs
        ):
            raise SmzdmProductReviewPacketError(
                "text source requires browser body ref"
            )
        if source_ordinal is not None:
            normalized_ordinal = _positive_int(
                source_ordinal,
                "source_ordinal",
            )
            if normalized_ordinal not in detail_ordinals:
                raise SmzdmProductReviewPacketError(
                    "source_ordinal is not present in detail images"
                )
            if (
                source_kind == "detail_image"
                and detail_refs_by_ordinal[normalized_ordinal]
                not in source_refs
            ):
                raise SmzdmProductReviewPacketError(
                    "source_ordinal does not match source_refs"
                )
        _text(fact.get("sku_status"), "sku_status")
        decision = _text(fact.get("decision"), "decision")
        if decision not in {"map", "leave_free", "reject"}:
            raise SmzdmProductReviewPacketError(
                "candidate fact decision is invalid"
            )
        concept_id = fact.get("concept_id")
        allowed_uses = _text_sequence(
            fact.get("allowed_uses"),
            "allowed_uses",
        )
        if not set(allowed_uses) <= allowed_use_values:
            raise SmzdmProductReviewPacketError(
                "candidate fact contains an unsupported allowed use"
            )
        promotion_status = _text(
            fact.get("promotion_status"),
            "promotion_status",
        )
        if decision == "map":
            if not isinstance(concept_id, str) or not concept_id.strip():
                raise SmzdmProductReviewPacketError(
                    "map decision requires concept_id"
                )
            if not allowed_uses:
                raise SmzdmProductReviewPacketError(
                    "map decision requires allowed uses"
                )
            if promotion_status != "approved_non_price_fact":
                raise SmzdmProductReviewPacketError(
                    "map decision requires approved promotion status"
                )
            approved_count += 1
        elif decision == "leave_free":
            if concept_id is not None:
                raise SmzdmProductReviewPacketError(
                    "leave_free decision forbids concept_id"
                )
            if promotion_status != "approved_non_price_fact":
                raise SmzdmProductReviewPacketError(
                    "leave_free decision requires approved promotion status"
                )
            approved_count += 1
        else:
            if concept_id is not None or allowed_uses:
                raise SmzdmProductReviewPacketError(
                    "reject decision forbids concept and allowed uses"
                )
            if promotion_status != "rejected":
                raise SmzdmProductReviewPacketError(
                    "reject decision requires rejected promotion status"
                )
        _text(fact.get("review_rationale"), "review_rationale")
        facts.append(fact)

    if approved_count > 5:
        raise SmzdmProductReviewPacketError(
            "manual review may approve at most five high-value facts"
        )
    return {
        **dict(packet),
        "sku_audit": sku_audit,
        "candidate_facts": facts,
    }


def build_product_review_packet(
    *,
    target: Mapping[str, object],
    raw_capture: Mapping[str, object],
    detail_image_dir: str | Path,
    source_match: SourceMatch,
    canonical_specification: str | None,
    source_sku: str,
    reference_price_sku: str,
    display_specification: str | None,
    price_specification_alignment: PriceSpecificationAlignment,
) -> dict[str, object]:
    """Join queue context and raw files without approving any facts."""
    product_id = _positive_int(
        target.get("canonical_product_id"),
        "target canonical_product_id",
    )
    raw_product_id = _positive_int(
        raw_capture.get("canonical_product_id"),
        "raw canonical_product_id",
    )
    if raw_product_id != product_id:
        raise SmzdmProductReviewPacketError(
            "target and raw capture product IDs do not match"
        )
    if source_match not in {"exact", "family", "variant_review"}:
        raise SmzdmProductReviewPacketError(
            "source_match must be an explicit review decision"
        )

    parameter_text = _text(
        raw_capture.get("parameter_text"),
        "parameter_text",
        allow_empty=True,
    )
    introduction_text = _text(
        raw_capture.get("product_introduction"),
        "product_introduction",
        allow_empty=True,
    )
    raw_images = _image_rows(raw_capture.get("detail_images"))
    source_summary = build_review_packet(
        parameter_text=parameter_text,
        introduction_text=introduction_text,
        detail_images=raw_images,
    )
    if (
        raw_capture.get("detail_image_count")
        != source_summary.detail_image_count
        or raw_capture.get("detail_image_status")
        != source_summary.detail_image_status
        or raw_capture.get("review_sources")
        != list(source_summary.review_sources)
    ):
        raise SmzdmProductReviewPacketError(
            "raw capture source summary is inconsistent"
        )

    image_dir = Path(detail_image_dir)
    local_images = _bind_local_images(
        raw_images,
        image_dir=image_dir,
    )
    profile = _text(
        target.get("category_profile"),
        "category_profile",
    )
    normalized_specification = (
        None
        if canonical_specification is None
        else _text(
            canonical_specification,
            "canonical_specification",
        )
    )
    normalized_display_specification = (
        None
        if display_specification is None
        else _text(
            display_specification,
            "display_specification",
        )
    )
    identity_status = {
        "exact": "exact_product",
        "family": "family",
        "variant_review": "exact_product_variant",
    }[source_match]
    sku_audit = _validate_sku_audit({
        "identity_status": identity_status,
        "source_sku": source_sku,
        "canonical_sku": normalized_specification or "unresolved",
        "reference_price_sku": reference_price_sku,
        "display_specification": normalized_display_specification,
        "price_specification_alignment": price_specification_alignment,
    })
    return {
        "schema_version": "smzdm-product-human-review-packet-v1",
        "product_id": product_id,
        "category_profile": profile,
        "review_field_policy": list(fields_for_profile(profile)),
        "canonical_identity": _text(
            target.get("canonical_product_identity"),
            "canonical_product_identity",
        ),
        "canonical_specification": normalized_specification,
        "sku_audit": sku_audit,
        "canonical_sku_scope": _text(
            target.get("sku_scope"),
            "sku_scope",
        ),
        "portfolio_role": _text(
            target.get("portfolio_role"),
            "portfolio_role",
        ),
        "missing_fields": list(
            _text_sequence(
                target.get("missing_fields"),
                "missing_fields",
            )
        ),
        "source_url": _https_url(
            raw_capture.get("page_url"),
            "page_url",
        ),
        "source_title": _text(
            raw_capture.get("page_title"),
            "page_title",
        ),
        "source_product_title": _text(
            raw_capture.get("product_title"),
            "product_title",
        ),
        "source_page_text_sha256": _sha256_text(
            raw_capture.get("raw_page_text_sha256"),
            "raw_page_text_sha256",
        ),
        "captured_at": _text(
            raw_capture.get("captured_at"),
            "captured_at",
        ),
        "source_match": source_match,
        "parameter_text": parameter_text,
        "introduction_text": introduction_text,
        "detail_image_count": source_summary.detail_image_count,
        "detail_image_status": source_summary.detail_image_status,
        "review_sources": list(source_summary.review_sources),
        "detail_images": local_images,
        "candidate_facts": [],
        "review_status": "human_review_required",
    }


def _bind_local_images(
    rows: tuple[dict[str, object], ...],
    *,
    image_dir: Path,
) -> list[dict[str, object]]:
    if not rows:
        return []
    if not image_dir.is_dir():
        raise SmzdmProductReviewPacketError(
            "detail image directory is unavailable"
        )
    bound: list[dict[str, object]] = []
    for row in rows:
        ordinal = _positive_int(row.get("ordinal"), "detail image ordinal")
        expected_sha256 = _sha256_text(
            row.get("sha256"),
            "detail image sha256",
        )
        matches = tuple(sorted(image_dir.glob(f"{ordinal:03d}_*")))
        verified = tuple(
            path
            for path in matches
            if path.is_file() and _file_sha256(path) == expected_sha256
        )
        if len(verified) != 1:
            raise SmzdmProductReviewPacketError(
                "detail image file does not match raw capture"
            )
        bound.append({
            "ordinal": ordinal,
            "local_path": str(verified[0]),
            "sha256": expected_sha256,
            "width": _positive_int(
                row.get("width"),
                "detail image width",
            ),
            "height": _positive_int(
                row.get("height"),
                "detail image height",
            ),
        })
    return bound


def _validate_sku_audit(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SmzdmProductReviewPacketError(
            "sku_audit must be an object"
        )
    audit = dict(value)
    identity_status = _text(
        audit.get("identity_status"),
        "sku_audit identity_status",
    )
    if identity_status not in {
        "exact_product",
        "exact_product_variant",
        "family",
        "unresolved",
    }:
        raise SmzdmProductReviewPacketError(
            "sku_audit identity_status is invalid"
        )
    source_sku = _text(
        audit.get("source_sku"),
        "sku_audit source_sku",
    )
    canonical_sku = _text(
        audit.get("canonical_sku"),
        "sku_audit canonical_sku",
    )
    reference_price_sku = _text(
        audit.get("reference_price_sku"),
        "sku_audit reference_price_sku",
    )
    display_value = audit.get("display_specification")
    display_specification = (
        None
        if display_value is None
        else _text(
            display_value,
            "sku_audit display_specification",
        )
    )
    alignment = _text(
        audit.get("price_specification_alignment"),
        "sku_audit price_specification_alignment",
    )
    if alignment not in {"aligned", "unresolved", "conflict"}:
        raise SmzdmProductReviewPacketError(
            "sku_audit price specification alignment is invalid"
        )
    if alignment == "aligned" and (
        display_specification is None
        or len({
            source_sku,
            canonical_sku,
            reference_price_sku,
            display_specification,
        }) != 1
    ):
        raise SmzdmProductReviewPacketError(
            "aligned price and specification require one exact SKU"
        )
    return {
        "identity_status": identity_status,
        "source_sku": source_sku,
        "canonical_sku": canonical_sku,
        "reference_price_sku": reference_price_sku,
        "display_specification": display_specification,
        "price_specification_alignment": alignment,
    }


def _image_rows(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise SmzdmProductReviewPacketError(
            "detail_images must be a list"
        )
    rows: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise SmzdmProductReviewPacketError(
                "detail image row must be an object"
            )
        rows.append(dict(item))
    return tuple(rows)


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise SmzdmProductReviewPacketError(
            f"{label} must be a positive integer"
        )
    return value


def _text(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise SmzdmProductReviewPacketError(f"{label} must be text")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise SmzdmProductReviewPacketError(
            f"{label} must be non-empty text"
        )
    return normalized


def _text_sequence(
    value: object,
    label: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SmzdmProductReviewPacketError(
            f"{label} must be a text list"
        )
    normalized = tuple(
        _text(item, label)
        for item in value
    )
    if len(set(normalized)) != len(normalized):
        raise SmzdmProductReviewPacketError(
            f"{label} must be unique"
        )
    return normalized


def _https_url(value: object, label: str) -> str:
    normalized = _text(value, label)
    if not normalized.startswith("https://"):
        raise SmzdmProductReviewPacketError(
            f"{label} must use https"
        )
    return normalized


def _sha256_text(value: object, label: str) -> str:
    normalized = _text(value, label)
    if (
        len(normalized) != 64
        or any(character not in "0123456789abcdef" for character in normalized)
    ):
        raise SmzdmProductReviewPacketError(
            f"{label} must be a SHA-256"
        )
    return normalized


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmzdmProductReviewPacketError(
            f"invalid JSON file: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise SmzdmProductReviewPacketError(
            f"JSON file must contain an object: {path}"
        )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble one raw SMZDM packet for human review."
    )
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument(
        "--source-match",
        choices=("exact", "family", "variant_review"),
        required=True,
    )
    parser.add_argument("--canonical-specification")
    parser.add_argument("--source-sku", required=True)
    parser.add_argument("--reference-price-sku", required=True)
    parser.add_argument("--display-specification")
    parser.add_argument(
        "--price-specification-alignment",
        choices=("aligned", "unresolved", "conflict"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    packet = build_product_review_packet(
        target=_load_json(args.target),
        raw_capture=_load_json(args.raw),
        detail_image_dir=args.image_dir,
        source_match=args.source_match,
        canonical_specification=args.canonical_specification,
        source_sku=args.source_sku,
        reference_price_sku=args.reference_price_sku,
        display_specification=args.display_specification,
        price_specification_alignment=(
            args.price_specification_alignment
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            packet,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
