"""Build non-promoting category candidates from trusted seed product rows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Sequence
import unicodedata

from app.guide.retrieval.category_fact_contracts import (
    CategoryFieldDefinition,
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from tools.guide_data.inventory_local_sources import (
    SourceInventoryError,
    atomic_write_private,
)
from tools.guide_data.read_seed_dump_products import (
    SeedProductRow,
    read_seed_dump_products,
)


DATABASE_FIELD_MAP = {
    "texture": "texture",
    "skin_types": "suitable_skin",
    "suitable_skin_types": "suitable_skin",
    "spf": "spf_pa",
    "usage_note": "usage",
    "free_of": "verified_absences",
    "shade_note": "shade",
    "clinical": "clinical_evidence",
}
SOURCE_TAG_CLASSES = {
    "official_specs": SourceClass.STRUCTURED_OFFICIAL,
    "structured_spec_fallback": SourceClass.STRUCTURED_OFFICIAL,
    "detail_ocr_ingredient_list": SourceClass.OCR_INGREDIENT_LIST,
    "detail_ocr_marketing": SourceClass.OCR_PACKAGING,
    "ocr_html_enrich": SourceClass.OCR_PACKAGING,
    "brand_marketing": SourceClass.OFFICIAL_DESCRIPTION,
}
_DETAIL_OCR_FIELDS = frozenset(
    {"clinical", "free_of", "spf", "texture", "usage_note"}
)
_PROTECTED_CORE_FIELDS = (
    "product_identity",
    "brand",
    "category",
    "price",
)


class SeedCandidateError(ValueError):
    """Raised when seed candidates cannot be classified deterministically."""


@dataclass(frozen=True, slots=True)
class SeedCandidateBuildResult:
    input_count: int
    pending_count: int
    quarantine_count: int
    pending_sha256: str
    quarantine_sha256: str


@dataclass(frozen=True, slots=True)
class _CanonicalProduct:
    profile: CategoryProfile


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    row: SeedProductRow
    profile: CategoryProfile
    field_key: str
    json_path: str
    value: object
    source_tag: str | None
    initial_reasons: tuple[str, ...] = ()


def build_seed_database_candidates(
    *,
    seed_dump_path: str | Path,
    canonical_products_path: str | Path,
    product_ids: Sequence[int],
    output_path: str | Path,
    quarantine_path: str | Path,
) -> SeedCandidateBuildResult:
    """Classify database values without creating review decisions."""

    if Path(output_path).resolve(strict=False) == Path(
        quarantine_path
    ).resolve(strict=False):
        raise SeedCandidateError(
            "pending and quarantine outputs must differ"
        )
    rows = read_seed_dump_products(
        seed_dump_path,
        product_ids=product_ids,
    )
    canonical = _load_canonical_products(
        Path(canonical_products_path),
        product_ids=tuple(row.product_id for row in rows),
    )
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }

    pending: list[dict[str, object]] = []
    quarantine: list[dict[str, object]] = []
    input_count = 0
    for row in rows:
        canonical_product = canonical[row.product_id]
        raw_candidates = _extract_raw_candidates(
            row,
            profile=canonical_product.profile,
        )
        input_count += len(raw_candidates)
        for candidate in raw_candidates:
            is_pending, output_row = _classify_candidate(
                candidate,
                definition=definitions.get(candidate.field_key),
            )
            (pending if is_pending else quarantine).append(output_row)

    pending, conflicted = _quarantine_pending_conflicts(pending)
    quarantine.extend(conflicted)
    pending = _deduplicate_and_sort(pending)
    quarantine = _deduplicate_and_sort(quarantine)
    pending_bytes = _jsonl_bytes(pending)
    quarantine_bytes = _jsonl_bytes(quarantine)
    try:
        atomic_write_private(output_path, pending_bytes)
        atomic_write_private(quarantine_path, quarantine_bytes)
    except SourceInventoryError as exc:
        raise SeedCandidateError(
            "candidate outputs could not be published"
        ) from exc
    return SeedCandidateBuildResult(
        input_count=input_count,
        pending_count=len(pending),
        quarantine_count=len(quarantine),
        pending_sha256=_sha256(pending_bytes),
        quarantine_sha256=_sha256(quarantine_bytes),
    )


def _extract_raw_candidates(
    row: SeedProductRow,
    *,
    profile: CategoryProfile,
) -> tuple[_RawCandidate, ...]:
    source_tags = row.specifications.get("source_tags", {})
    if not isinstance(source_tags, dict):
        raise SeedCandidateError(
            f"product {row.product_id} source_tags must be an object"
        )
    candidates: list[_RawCandidate] = []
    for source_key, field_key in DATABASE_FIELD_MAP.items():
        if source_key not in row.skincare_info:
            continue
        raw_tag = source_tags.get(source_key)
        source_tag = raw_tag if isinstance(raw_tag, str) else None
        if (
            source_tag is None
            and row.skincare_info.get("_detail_ocr_enriched") is True
            and source_key in _DETAIL_OCR_FIELDS
        ):
            source_tag = "detail_ocr_marketing"
        candidates.append(
            _RawCandidate(
                row=row,
                profile=profile,
                field_key=field_key,
                json_path=f"skincare_info.{source_key}",
                value=row.skincare_info[source_key],
                source_tag=source_tag,
            )
        )

    ingredients = row.skincare_info.get("key_ingredients")
    if ingredients is not None:
        if not isinstance(ingredients, list):
            raise SeedCandidateError(
                f"product {row.product_id} key_ingredients must be an array"
            )
        grouped: dict[str | None, list[str]] = {}
        for index, ingredient in enumerate(ingredients):
            if not isinstance(ingredient, dict):
                raise SeedCandidateError(
                    f"product {row.product_id} ingredient is invalid"
                )
            name = ingredient.get("name")
            source_tag = ingredient.get("source")
            if not isinstance(name, str) or not name.strip():
                raise SeedCandidateError(
                    f"product {row.product_id} ingredient name is invalid"
                )
            if source_tag is not None and not isinstance(source_tag, str):
                raise SeedCandidateError(
                    f"product {row.product_id} ingredient source is invalid"
                )
            grouped.setdefault(source_tag, []).append(name)
        for source_tag, names in sorted(
            grouped.items(),
            key=lambda item: item[0] or "",
        ):
            source_tag_locator = (
                source_tag
                if source_tag in SOURCE_TAG_CLASSES
                else "unknown-"
                + _sha256(
                    _canonical_json_bytes(source_tag)
                )[:16]
            )
            candidates.append(
                _RawCandidate(
                    row=row,
                    profile=profile,
                    field_key="ingredients_present",
                    json_path=(
                        "skincare_info.key_ingredients"
                        f"[source={source_tag_locator}]"
                    ),
                    value=names,
                    source_tag=source_tag,
                )
            )

    for source_key, reason in (
        ("qa_facts", "consumer_qa"),
        ("user_review_notes", "consumer_review"),
        ("claim_notes", "marketing_claim"),
    ):
        if source_key not in row.skincare_info:
            continue
        raw_tag = source_tags.get(source_key)
        candidates.append(
            _RawCandidate(
                row=row,
                profile=profile,
                field_key=source_key,
                json_path=f"skincare_info.{source_key}",
                value=row.skincare_info[source_key],
                source_tag=raw_tag if isinstance(raw_tag, str) else None,
                initial_reasons=(reason,),
            )
        )
    return tuple(candidates)


def _classify_candidate(
    candidate: _RawCandidate,
    *,
    definition: CategoryFieldDefinition | None,
) -> tuple[bool, dict[str, object]]:
    reasons = set(candidate.initial_reasons)
    source_class = SOURCE_TAG_CLASSES.get(candidate.source_tag or "")
    if candidate.source_tag == "consumer_qa":
        reasons.add("consumer_qa")
    elif candidate.source_tag is not None and source_class is None:
        reasons.add("unknown_source_tag")
    if source_class is None:
        reasons.add("unbound_database_field")
    if definition is None:
        reasons.add("unknown_field")
    elif candidate.profile not in definition.profiles:
        reasons.add("field_not_applicable")
    if definition is not None and source_class is not None:
        allowed = {
            policy.source_class
            for policy in definition.source_policies
        }
        if source_class not in allowed:
            reasons.add("source_not_authorized")
    if (
        candidate.field_key == "verified_absences"
        and source_class is not SourceClass.STRUCTURED_OFFICIAL
    ):
        reasons.add("verified_absence_requires_official_structure")
    value_sha256 = _sha256(_canonical_json_bytes(candidate.value))
    locator = (
        "urn:xiaoro:seed-dump:"
        f"sha256:{candidate.row.source_sha256}:"
        f"product:{candidate.row.product_id}:field:{candidate.json_path}"
    )
    public_source_class = (
        source_class.value if source_class is not None else "unknown"
    )
    extraction_method = (
        "ocr_json"
        if source_class
        in {SourceClass.OCR_INGREDIENT_LIST, SourceClass.OCR_PACKAGING}
        else "structured_json"
    )
    normalized_value: object | None = None
    if definition is not None:
        try:
            normalized_value = _normalize_value(
                candidate.value,
                definition=definition,
            )
        except ValueError:
            reasons.add("invalid_value")
    id_value = (
        normalized_value
        if normalized_value is not None
        else {"value_sha256": value_sha256}
    )
    candidate_id = _candidate_id(
        product_id=candidate.row.product_id,
        category_profile=candidate.profile.value,
        field_key=candidate.field_key,
        source_sha256=candidate.row.source_sha256,
        source_locator=locator,
        normalized_value=id_value,
    )
    common = {
        "candidate_id": candidate_id,
        "category_profile": candidate.profile.value,
        "extraction_method": extraction_method,
        "field_key": candidate.field_key,
        "product_id": candidate.row.product_id,
        "source_class": public_source_class,
        "source_locator": locator,
        "source_sha256": candidate.row.source_sha256,
        "value_sha256": value_sha256,
    }
    if reasons:
        return False, {
            **common,
            "quarantine_reasons": sorted(reasons),
            "status": "quarantine",
        }
    return True, {
        **common,
        "conflict_candidate_ids": [],
        "conflict_group_id": None,
        "has_conflict": False,
        "normalized_value": normalized_value,
        "status": "pending",
    }


def _quarantine_pending_conflicts(
    pending: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    groups: dict[tuple[int, str], list[dict[str, object]]] = {}
    for row in pending:
        groups.setdefault(
            (int(row["product_id"]), str(row["field_key"])),
            [],
        ).append(row)
    conflicting_ids: set[str] = set()
    for rows in groups.values():
        values = {
            _canonical_json_text(row["normalized_value"])
            for row in rows
        }
        if len(values) > 1:
            conflicting_ids.update(str(row["candidate_id"]) for row in rows)

    retained: list[dict[str, object]] = []
    quarantined: list[dict[str, object]] = []
    for row in pending:
        if row["candidate_id"] not in conflicting_ids:
            retained.append(row)
            continue
        quarantined.append(
            {
                key: value
                for key, value in row.items()
                if key
                not in {
                    "conflict_candidate_ids",
                    "conflict_group_id",
                    "has_conflict",
                    "normalized_value",
                    "status",
                }
            }
            | {
                "quarantine_reasons": ["source_conflict"],
                "status": "quarantine",
            }
        )
    return retained, quarantined


def _load_canonical_products(
    path: Path,
    *,
    product_ids: tuple[int, ...],
) -> dict[int, _CanonicalProduct]:
    expected = set(product_ids)
    products: dict[int, _CanonicalProduct] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SeedCandidateError(
            "canonical products could not be read"
        ) from exc
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            payload = json.loads(line)
            product_id = payload["product_id"]
            fields = payload["fields"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SeedCandidateError(
                f"canonical line {line_number} is invalid"
            ) from exc
        if product_id not in expected:
            continue
        if product_id in products or not isinstance(fields, dict):
            raise SeedCandidateError(
                f"canonical product {product_id} is invalid"
            )
        try:
            raw_category = _known_field_value(fields, "category")
            for field_key in _PROTECTED_CORE_FIELDS:
                _known_field_value(fields, field_key)
            products[product_id] = _CanonicalProduct(
                profile=category_profile_for(str(raw_category)),
            )
        except (KeyError, ValueError) as exc:
            raise SeedCandidateError(
                f"canonical product {product_id} core is invalid"
            ) from exc
    if set(products) != expected:
        missing = sorted(expected - set(products))
        raise SeedCandidateError(
            "canonical products are missing IDs: "
            + ",".join(str(value) for value in missing)
        )
    return products


def _known_field_value(
    fields: dict[str, object],
    field_key: str,
) -> object:
    field = fields[field_key]
    if (
        not isinstance(field, dict)
        or field.get("resolved_state") != "known"
        or field.get("value") is None
    ):
        raise ValueError("canonical core field must be known")
    return field["value"]


def _normalize_value(
    value: object,
    *,
    definition: CategoryFieldDefinition,
) -> object:
    if definition.value_type == "string":
        if not isinstance(value, str):
            raise ValueError("expected string")
        return _normalize_string(value)
    if definition.value_type == "string_list":
        raw_values = [value] if isinstance(value, str) else value
        if not isinstance(raw_values, list):
            raise ValueError("expected string list")
        normalized = {
            _normalize_string(item)
            for item in raw_values
            if isinstance(item, str) and item.strip()
        }
        if not normalized:
            raise ValueError("empty string list")
        return sorted(normalized, key=lambda item: item.casefold())
    if definition.value_type == "boolean":
        if type(value) is not bool:
            raise ValueError("expected boolean")
        return value
    if definition.value_type == "number":
        if type(value) not in {int, float}:
            raise ValueError("expected number")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("number must be finite")
        return value
    raise ValueError("unknown value type")


def _normalize_string(value: str) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value).split()
    ).strip()
    if not normalized:
        raise ValueError("empty string")
    return normalized


def _candidate_id(
    *,
    product_id: int,
    category_profile: str,
    field_key: str,
    source_sha256: str,
    source_locator: str,
    normalized_value: object,
) -> str:
    payload = (
        f"{product_id}\0{category_profile}\0{field_key}\0"
        f"{source_sha256}\0{source_locator}\0"
        f"{_canonical_json_text(normalized_value)}"
    )
    return _sha256(payload.encode("utf-8"))


def _deduplicate_and_sort(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    unique: dict[str, dict[str, object]] = {}
    for row in rows:
        candidate_id = str(row["candidate_id"])
        previous = unique.get(candidate_id)
        if previous is not None and previous != row:
            raise SeedCandidateError("candidate ID collision")
        unique[candidate_id] = row
    return [unique[key] for key in sorted(unique)]


def _jsonl_bytes(rows: list[dict[str, object]]) -> bytes:
    return b"".join(
        _canonical_json_bytes(row) + b"\n"
        for row in rows
    )


def _canonical_json_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_json_bytes(value: object) -> bytes:
    return _canonical_json_text(value).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build non-promoting candidates from seed products."
    )
    parser.add_argument("--seed-dump", required=True)
    parser.add_argument("--canonical", required=True)
    parser.add_argument("--product-id", action="append", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--quarantine", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_seed_database_candidates(
            seed_dump_path=args.seed_dump,
            canonical_products_path=args.canonical,
            product_ids=tuple(args.product_id),
            output_path=args.output,
            quarantine_path=args.quarantine,
        )
    except (SeedCandidateError, ValueError):
        return 2
    print(
        json.dumps(
            {
                "input_count": result.input_count,
                "pending_count": result.pending_count,
                "pending_sha256": result.pending_sha256,
                "quarantine_count": result.quarantine_count,
                "quarantine_sha256": result.quarantine_sha256,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
