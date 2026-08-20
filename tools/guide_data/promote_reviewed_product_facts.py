"""Promote terminal SMZDM product reviews into runtime fact assets."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_fact_assets import (
    ApprovedCategoryFact,
    CategoryFactManifest,
    PILOT_BINDINGS,
    load_category_fact_assets,
)
from app.guide.retrieval.category_fact_contracts import (
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from tools.guide_data.review_smzdm_product import (
    SmzdmProductReviewPacketError,
    validate_reviewed_product_packet,
)


class ReviewedProductFactPromotionError(ValueError):
    """Raised when reviewed facts cannot be safely promoted."""


_SOURCE_CLASS_BY_KIND = {
    "parameter_table": SourceClass.MERCHANT_PARAMETER,
    "product_introduction": SourceClass.MERCHANT_DESCRIPTION,
    "detail_image": SourceClass.MERCHANT_DESCRIPTION_OCR,
}
_SOURCE_KIND_PRIORITY = {
    SourceClass.MERCHANT_DESCRIPTION: 1,
    SourceClass.MERCHANT_PARAMETER: 2,
    SourceClass.MERCHANT_DESCRIPTION_OCR: 3,
}
_MAP_CAPABILITIES = frozenset({
    "evidence",
    "display",
    "compare",
    "soft_rank",
})
_LEAVE_FREE_CAPABILITIES = frozenset({
    "evidence",
    "display",
})


@dataclass(frozen=True, slots=True)
class ReviewedProductFactPromotionResult:
    manifest_path: Path
    facts_path: Path
    promoted_count: int
    replaced_count: int
    total_count: int


def promote_reviewed_packets(
    *,
    packets: Sequence[Mapping[str, object]],
    reviewer: str,
    reviewed_at: datetime,
) -> tuple[ApprovedCategoryFact, ...]:
    """Convert only terminal approved decisions into category facts."""
    normalized_reviewer = _reviewer(reviewer)
    normalized_reviewed_at = _reviewed_at(reviewed_at)
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    groups: dict[
        tuple[int, CategoryProfile, str],
        list[tuple[dict[str, object], str]],
    ] = defaultdict(list)

    for raw_packet in packets:
        if raw_packet.get("review_status") not in {
            "human_review_complete",
            "no_promotion",
        }:
            raise ReviewedProductFactPromotionError(
                "promotion requires terminal human review"
            )
        try:
            packet = validate_reviewed_product_packet(raw_packet)
        except SmzdmProductReviewPacketError as exc:
            raise ReviewedProductFactPromotionError(str(exc)) from exc
        if packet["review_status"] == "no_promotion":
            continue
        profile = _profile(packet.get("category_profile"))
        product_id = _product_id(packet.get("product_id"))
        packet_sha256 = sha256(
            _canonical_json(packet)
        ).hexdigest()
        for raw_fact in packet["candidate_facts"]:
            fact = dict(raw_fact)
            decision = fact.get("decision")
            if decision == "reject":
                continue
            if decision not in {"map", "leave_free"}:
                raise ReviewedProductFactPromotionError(
                    "approved fact has invalid decision"
                )
            if fact.get("promotion_status") != "approved_non_price_fact":
                raise ReviewedProductFactPromotionError(
                    "approved fact lacks promotion status"
                )
            field_key = _promoted_field_key(fact.get("field_key"))
            if field_key not in definitions:
                raise ReviewedProductFactPromotionError(
                    "approved fact has unknown field"
                )
            groups[(product_id, profile, field_key)].append(
                (fact, packet_sha256)
            )

    promoted = [
        _promote_group(
            product_id=product_id,
            profile=profile,
            field_key=field_key,
            rows=rows,
            reviewer=normalized_reviewer,
            reviewed_at=normalized_reviewed_at,
            definition=definitions[field_key],
        )
        for (product_id, profile, field_key), rows in sorted(
            groups.items(),
            key=lambda item: (
                item[0][0],
                item[0][1].value,
                item[0][2],
            ),
        )
    ]
    return tuple(promoted)


def publish_reviewed_fact_assets(
    *,
    existing_manifest_path: Path,
    review_paths: Sequence[Path],
    output_dir: Path,
    reviewer: str,
    reviewed_at: datetime,
    canonical_manifest_path: Path,
    canonical_products_path: Path,
) -> ReviewedProductFactPromotionResult:
    """Publish a verified content-addressed category fact generation."""
    if not review_paths:
        raise ReviewedProductFactPromotionError(
            "review_paths must not be empty"
        )
    packets = tuple(
        _load_packet(Path(path))
        for path in review_paths
    )
    promoted = promote_reviewed_packets(
        packets=packets,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
    )
    canonical_reader = CanonicalProductReader.from_files(
        manifest_path=canonical_manifest_path,
        products_path=canonical_products_path,
    )
    existing_manifest = _load_json(existing_manifest_path)
    existing_assets = load_category_fact_assets(
        manifest_path=existing_manifest_path,
        expected_manifest_sha256=_nonempty_text(
            existing_manifest.get("manifest_sha256"),
            "existing manifest_sha256",
        ),
        canonical_reader=canonical_reader,
        field_registry=category_field_registry(),
    )
    promoted_keys = {
        (fact.product_id, fact.category_profile, fact.field_key)
        for fact in promoted
    }
    replaced_count = sum(
        (
            fact.product_id,
            fact.category_profile,
            fact.field_key,
        )
        in promoted_keys
        for fact in existing_assets.facts
    )
    merged = merge_promoted_facts(
        existing=existing_assets.facts,
        promoted=promoted,
    )
    destination = Path(output_dir)
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ReviewedProductFactPromotionError(
            "output_dir must not already exist"
        ) from exc

    facts_bytes = b"".join(
        _canonical_json(
            fact.model_dump(
                mode="json",
                exclude_none=True,
            )
        )
        + b"\n"
        for fact in merged
    )
    facts_sha256 = sha256(facts_bytes).hexdigest()
    facts_path = (
        destination
        / f"category_facts_v1.{facts_sha256}.jsonl"
    )
    facts_path.write_bytes(facts_bytes)
    unsigned_manifest = {
        "asset_id": "guide-category-facts-v1",
        "asset_version": (
            "approved-category-facts-v1:sha256:"
            f"{facts_sha256}"
        ),
        "fact_count": len(merged),
        "facts_file": facts_path.name,
        "facts_sha256": facts_sha256,
        "pilot_bindings": [
            binding.model_dump(mode="json")
            for binding in PILOT_BINDINGS
        ],
        "schema_version": "approved-category-facts-v1",
    }
    manifest_sha256 = sha256(
        _canonical_json(unsigned_manifest)
    ).hexdigest()
    manifest = CategoryFactManifest.model_validate({
        **unsigned_manifest,
        "manifest_sha256": manifest_sha256,
    })
    manifest_path = destination / "category_facts_v1_manifest.json"
    manifest_path.write_bytes(
        _canonical_json(manifest.model_dump(mode="json")) + b"\n"
    )
    load_category_fact_assets(
        manifest_path=manifest_path,
        facts_path=facts_path,
        expected_manifest_sha256=manifest_sha256,
        canonical_reader=canonical_reader,
        field_registry=category_field_registry(),
    )
    return ReviewedProductFactPromotionResult(
        manifest_path=manifest_path,
        facts_path=facts_path,
        promoted_count=len(promoted),
        replaced_count=replaced_count,
        total_count=len(merged),
    )


def merge_promoted_facts(
    *,
    existing: Sequence[ApprovedCategoryFact],
    promoted: Sequence[ApprovedCategoryFact],
) -> tuple[ApprovedCategoryFact, ...]:
    """Replace only fields covered by terminal reviewed promotions."""
    if any(
        not isinstance(item, ApprovedCategoryFact)
        for item in (*existing, *promoted)
    ):
        raise TypeError(
            "fact collections must contain ApprovedCategoryFact"
        )
    promoted_keys = {
        (item.product_id, item.category_profile, item.field_key)
        for item in promoted
    }
    if len(promoted_keys) != len(promoted):
        raise ReviewedProductFactPromotionError(
            "promoted facts must be unique by product field"
        )
    merged_by_id: dict[str, ApprovedCategoryFact] = {}
    for item in (
        *(
            fact
            for fact in existing
            if (
                fact.product_id,
                fact.category_profile,
                fact.field_key,
            )
            not in promoted_keys
        ),
        *promoted,
    ):
        previous = merged_by_id.get(item.fact_id)
        if previous is not None and previous != item:
            raise ReviewedProductFactPromotionError(
                "conflicting promoted fact ID"
            )
        merged_by_id[item.fact_id] = item
    return tuple(
        sorted(
            merged_by_id.values(),
            key=lambda item: item.fact_id,
        )
    )


def _promote_group(
    *,
    product_id: int,
    profile: CategoryProfile,
    field_key: str,
    rows: Sequence[tuple[dict[str, object], str]],
    reviewer: str,
    reviewed_at: datetime,
    definition,
) -> ApprovedCategoryFact:
    decisions = {str(row[0]["decision"]) for row in rows}
    if len(decisions) != 1:
        raise ReviewedProductFactPromotionError(
            "one product field cannot mix promotion decisions"
        )
    decision = next(iter(decisions))
    source_class = max(
        (
            _source_class_for_kind(str(row[0]["source_kind"]))
            for row in rows
        ),
        key=lambda value: _SOURCE_KIND_PRIORITY[value],
    )
    policy = next(
        (
            item
            for item in definition.source_policies
            if item.source_class is source_class
        ),
        None,
    )
    if policy is None or profile not in definition.profiles:
        raise ReviewedProductFactPromotionError(
            "approved fact source is not authorized for field"
        )
    requested = (
        _MAP_CAPABILITIES
        if decision == "map"
        else _LEAVE_FREE_CAPABILITIES
    )
    capability_limit = requested & policy.capabilities
    if decision == "map" and not {
        "compare",
        "soft_rank",
    } <= capability_limit:
        raise ReviewedProductFactPromotionError(
            "mapped fact cannot receive selection capabilities"
        )
    if "evidence" not in capability_limit:
        raise ReviewedProductFactPromotionError(
            "promoted fact must remain evidence"
        )

    values = sorted({
        _nonempty_text(row[0].get("public_text"), "public_text")
        for row in rows
    })
    value = _field_value(
        values=values,
        value_type=definition.value_type,
        field_key=field_key,
    )
    packet_hashes = sorted({row[1] for row in rows})
    source_fact_ids = sorted({
        _nonempty_text(row[0].get("fact_id"), "fact_id")
        for row in rows
    })
    source_sha256 = sha256(_canonical_json({
        "packet_sha256s": packet_hashes,
        "source_fact_ids": source_fact_ids,
    })).hexdigest()
    record_sha256 = sha256(_canonical_json([
        row[0] for row in rows
    ])).hexdigest()
    for row in rows:
        _source_refs(row[0].get("source_refs"))
    source_refs = (
        "urn:xiaoro:category-fact-source:sha256:"
        f"{source_sha256}:{record_sha256}",
    )
    unsigned = {
        "product_id": product_id,
        "category_profile": profile,
        "field_key": field_key,
        "value": value,
        "source_class": source_class,
        "source_refs": source_refs,
        "source_sha256": source_sha256,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "capability_limit": capability_limit,
    }
    provisional = ApprovedCategoryFact(
        fact_id="0" * 64,
        **unsigned,
    )
    fact_id = sha256(_canonical_json(
        provisional.model_dump(
            mode="json",
            exclude={"fact_id"},
            exclude_none=True,
        )
    )).hexdigest()
    return provisional.model_copy(
        update={"fact_id": fact_id},
        deep=True,
    )


def _field_value(
    *,
    values: list[str],
    value_type: str,
    field_key: str,
) -> object:
    if value_type == "string_list":
        return values
    if value_type == "string" and len(values) == 1:
        return values[0]
    raise ReviewedProductFactPromotionError(
        f"reviewed values cannot populate {field_key}.{value_type}"
    )


def _promoted_field_key(value: object) -> str:
    field_key = _nonempty_text(value, "field_key")
    return (
        "claimed_ingredients"
        if field_key == "ingredients_present"
        else field_key
    )


def _source_class_for_kind(value: str) -> SourceClass:
    if "detail_image" in value:
        return SourceClass.MERCHANT_DESCRIPTION_OCR
    if "parameter" in value:
        return SourceClass.MERCHANT_PARAMETER
    if "introduction" in value:
        return SourceClass.MERCHANT_DESCRIPTION
    try:
        return _SOURCE_CLASS_BY_KIND[value]
    except KeyError as exc:
        raise ReviewedProductFactPromotionError(
            "approved fact source kind is unsupported"
        ) from exc


def _source_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ReviewedProductFactPromotionError(
            "approved fact requires source refs"
        )
    return tuple(
        _nonempty_text(item, "source_ref")
        for item in value
    )


def _reviewer(value: object) -> str:
    return _nonempty_text(value, "reviewer")


def _reviewed_at(value: object) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ReviewedProductFactPromotionError(
            "reviewed_at must be timezone-aware"
        )
    return value


def _profile(value: object) -> CategoryProfile:
    try:
        return CategoryProfile(value)
    except (TypeError, ValueError) as exc:
        raise ReviewedProductFactPromotionError(
            "category_profile is invalid"
        ) from exc


def _product_id(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ReviewedProductFactPromotionError(
            "product_id must be positive"
        )
    return value


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewedProductFactPromotionError(
            f"{label} must be non-empty text"
        )
    return value.strip()


def _load_packet(path: Path) -> dict[str, object]:
    value = _load_json(path)
    return value


def _parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing-manifest", required=True)
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--canonical-manifest", required=True)
    parser.add_argument("--canonical-products", required=True)
    return parser.parse_args(argv)


def _review_paths(directory: Path) -> tuple[Path, ...]:
    try:
        paths = tuple(sorted(
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.name.startswith("product-")
            and path.name.endswith("-v1.json")
        ))
    except OSError as exc:
        raise ReviewedProductFactPromotionError(
            f"cannot read review directory: {directory}"
        ) from exc
    if not paths:
        raise ReviewedProductFactPromotionError(
            "review directory contains no product review packets"
        )
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    review_paths = _review_paths(Path(arguments.review_dir))
    try:
        reviewed_at = datetime.fromisoformat(arguments.reviewed_at)
    except ValueError as exc:
        raise ReviewedProductFactPromotionError(
            "reviewed_at must be an ISO-8601 datetime"
        ) from exc
    result = publish_reviewed_fact_assets(
        existing_manifest_path=Path(arguments.existing_manifest),
        review_paths=review_paths,
        output_dir=Path(arguments.output_dir),
        reviewer=arguments.reviewer,
        reviewed_at=reviewed_at,
        canonical_manifest_path=Path(arguments.canonical_manifest),
        canonical_products_path=Path(arguments.canonical_products),
    )
    print(_canonical_json({
        "facts_path": str(result.facts_path),
        "manifest_path": str(result.manifest_path),
        "promoted_count": result.promoted_count,
        "replaced_count": result.replaced_count,
        "review_packet_count": len(review_paths),
        "total_count": result.total_count,
    }).decode("utf-8"))
    return 0


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewedProductFactPromotionError(
            f"invalid JSON file: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise ReviewedProductFactPromotionError(
            f"JSON file must contain an object: {path}"
        )
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, CategoryProfile):
        return value.value
    if isinstance(value, SourceClass):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


__all__ = [
    "ReviewedProductFactPromotionResult",
    "ReviewedProductFactPromotionError",
    "merge_promoted_facts",
    "main",
    "publish_reviewed_fact_assets",
    "promote_reviewed_packets",
]


if __name__ == "__main__":
    raise SystemExit(main())
