"""Reconcile canonical, seed, and saved-page evidence for pilot products."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
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
from tools.guide_data._safe_source_io import (
    SafeSourceIOError,
    read_relative_regular_bytes,
)
from tools.guide_data.extract_saved_page_evidence import (
    SavedPageError,
    extract_saved_page_evidence_bytes,
)
from tools.guide_data.inventory_local_sources import (
    SourceInventoryError,
    atomic_write_private,
)


TARGET_PRODUCT_IDS = (
    38,
    42,
    49,
    53,
    55,
    57,
    69,
    79,
    80,
    86,
    91,
    103,
    114,
    120,
    121,
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DIGITS = re.compile(r"^[0-9]+$")
_FORBIDDEN_WRITER_KEYS = frozenset(
    {"approval", "decision", "reviewer", "signature"}
)
_PARAMETER_FIELD_MAP = {
    "SPF": "spf_pa",
    "SPF值": "spf_pa",
    "产品质地": "texture",
    "使用方法": "usage",
    "使用方式": "usage",
    "妆效": "finish",
    "持久度": "longevity",
    "水润度": "texture",
    "色号": "shade",
    "规格参数": None,
    "适合肤质": "suitable_skin",
    "适用肤质": "suitable_skin",
    "防晒指数": "spf_pa",
    "颜色": "shade",
    "颜色分类": "shade",
    "质地": "texture",
}
class PilotCandidateError(ValueError):
    """Raised when pilot candidate evidence cannot be bound safely."""


@dataclass(frozen=True, slots=True)
class PilotCandidateResult:
    product_count: int
    status_count: int
    known_count: int
    pending_count: int
    quarantine_count: int
    unknown_count: int
    status_sha256: str
    pending_sha256: str
    quarantine_sha256: str
    parsed_page_count: int
    parsed_review_count: int


@dataclass(frozen=True, slots=True)
class _CanonicalProduct:
    profile: CategoryProfile
    fields: dict[str, dict[str, object]]


def build_pilot_candidates(
    *,
    canonical_products_path: str | Path,
    database_pending_path: str | Path,
    database_quarantine_path: str | Path,
    saved_page_manifest_path: str | Path,
    saved_page_root: str | Path,
    product_ids: Sequence[int],
    status_output_path: str | Path,
    pending_output_path: str | Path,
    quarantine_output_path: str | Path,
) -> PilotCandidateResult:
    """Write local candidate queues and a complete four-state matrix."""

    normalized_ids = _validate_product_ids(product_ids)
    _require_distinct_outputs(
        status_output_path,
        pending_output_path,
        quarantine_output_path,
    )
    canonical = _load_canonical_products(
        Path(canonical_products_path),
        product_ids=normalized_ids,
    )
    database_pending = _load_jsonl(
        Path(database_pending_path),
        label="database pending",
    )
    database_quarantine = _load_jsonl(
        Path(database_quarantine_path),
        label="database quarantine",
    )
    _validate_queue_products(
        database_pending + database_quarantine,
        product_ids=set(normalized_ids),
    )
    html_pending, parsed_pages, parsed_reviews = _saved_page_candidates(
        manifest_path=Path(saved_page_manifest_path),
        source_root=Path(saved_page_root),
        canonical=canonical,
        product_ids=set(normalized_ids),
    )

    pending = [
        {**row, "_evidence_source": "database"}
        for row in database_pending
    ] + html_pending
    quarantine = [
        {**row, "_evidence_source": "database"}
        for row in database_quarantine
    ]
    pending, new_quarantine = _quarantine_source_conflicts(pending)
    quarantine.extend(new_quarantine)
    pending, whole_product_quarantine = _quarantine_core_conflicts(
        pending,
        quarantine,
    )
    quarantine.extend(whole_product_quarantine)

    status_rows = _build_status_rows(
        canonical=canonical,
        product_ids=normalized_ids,
        pending=pending,
        quarantine=quarantine,
    )
    public_pending = _public_rows(pending)
    public_quarantine = _public_rows(quarantine)
    status_rows.sort(
        key=lambda row: (
            int(row["product_id"]),
            str(row["field_key"]),
        )
    )
    public_pending = _deduplicate_by_candidate_id(public_pending)
    public_quarantine = _deduplicate_by_candidate_id(public_quarantine)
    _reject_writer_metadata(
        status_rows + public_pending + public_quarantine
    )

    status_bytes = _jsonl_bytes(status_rows)
    pending_bytes = _jsonl_bytes(public_pending)
    quarantine_bytes = _jsonl_bytes(public_quarantine)
    try:
        atomic_write_private(status_output_path, status_bytes)
        atomic_write_private(pending_output_path, pending_bytes)
        atomic_write_private(quarantine_output_path, quarantine_bytes)
    except SourceInventoryError as exc:
        raise PilotCandidateError(
            "pilot candidate outputs could not be published"
        ) from exc

    counts = {
        state: sum(row["status"] == state for row in status_rows)
        for state in ("known", "pending", "quarantine", "unknown")
    }
    return PilotCandidateResult(
        product_count=len(normalized_ids),
        status_count=len(status_rows),
        known_count=counts["known"],
        pending_count=counts["pending"],
        quarantine_count=counts["quarantine"],
        unknown_count=counts["unknown"],
        status_sha256=_sha256(status_bytes),
        pending_sha256=_sha256(pending_bytes),
        quarantine_sha256=_sha256(quarantine_bytes),
        parsed_page_count=parsed_pages,
        parsed_review_count=parsed_reviews,
    )


def render_pilot_review_matrix(
    status_path: str | Path,
    output_path: str | Path,
) -> str:
    """Render a hash-only local matrix for independent verifiers."""

    rows = _load_jsonl(Path(status_path), label="pilot status")
    lines = [
        "# Pilot Candidate Verification Matrix",
        "",
        (
            "| product_id | profile | field | status | candidate hashes | "
            "value hash | source hashes | next step |"
        ),
        "| ---: | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in sorted(
        rows,
        key=lambda item: (
            int(item["product_id"]),
            str(item["field_key"]),
        ),
    ):
        candidate_hashes = _hash_prefixes(row.get("candidate_ids"))
        source_hashes = _hash_prefixes(row.get("source_sha256"))
        value_hash = row.get("value_sha256")
        rendered_value_hash = (
            str(value_hash)[:12]
            if isinstance(value_hash, str)
            else "-"
        )
        next_step = {
            "known": "none",
            "pending": "independent_verification_required",
            "quarantine": "resolve_or_defer",
            "unknown": "keep_unknown",
        }.get(str(row.get("status")), "keep_unknown")
        lines.append(
            f"| {row['product_id']} | `{row['category_profile']}` | "
            f"`{row['field_key']}` | `{row['status']}` | "
            f"{candidate_hashes} | {rendered_value_hash} | "
            f"{source_hashes} | `{next_step}` |"
        )
    content = ("\n".join(lines) + "\n").encode("utf-8")
    try:
        atomic_write_private(output_path, content)
    except SourceInventoryError as exc:
        raise PilotCandidateError(
            "pilot matrix could not be published"
        ) from exc
    return _sha256(content)


def _saved_page_candidates(
    *,
    manifest_path: Path,
    source_root: Path,
    canonical: dict[int, _CanonicalProduct],
    product_ids: set[int],
) -> tuple[list[dict[str, object]], int, int]:
    manifest = _load_json_object(manifest_path, label="saved page manifest")
    if set(manifest) != {"schema_version", "sources"} or manifest.get(
        "schema_version"
    ) != "pilot-saved-page-sources-v1":
        raise PilotCandidateError("saved page manifest is invalid")
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise PilotCandidateError("saved page manifest sources are invalid")
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    candidates: list[dict[str, object]] = []
    seen_bindings: set[tuple[int, str]] = set()
    review_count = 0
    for index, source in enumerate(sources, start=1):
        expected_fields = {
            "item_id",
            "path",
            "product_id",
            "sha256",
            "sku_id",
        }
        if not isinstance(source, dict) or set(source) != expected_fields:
            raise PilotCandidateError(
                f"saved page source {index} fields are invalid"
            )
        product_id = source["product_id"]
        item_id = source["item_id"]
        sku_id = source["sku_id"]
        expected_sha = source["sha256"]
        relative_path = source["path"]
        if (
            type(product_id) is not int
            or product_id not in product_ids
            or not _valid_numeric_id(item_id)
            or not _valid_numeric_id(sku_id)
            or not isinstance(expected_sha, str)
            or _SHA256_PATTERN.fullmatch(expected_sha) is None
            or not _safe_relative_path(relative_path)
        ):
            raise PilotCandidateError(
                f"saved page source {index} binding is invalid"
            )
        binding = (product_id, expected_sha)
        if binding in seen_bindings:
            raise PilotCandidateError("saved page source is duplicated")
        seen_bindings.add(binding)
        try:
            content = read_relative_regular_bytes(
                source_root,
                Path(relative_path),
            )
        except SafeSourceIOError as exc:
            raise PilotCandidateError(
                "saved page source must be a stable regular file"
            ) from exc
        if _sha256(content) != expected_sha:
            raise PilotCandidateError("saved page source SHA-256 mismatch")
        try:
            evidence = extract_saved_page_evidence_bytes(content)
        except SavedPageError as exc:
            raise PilotCandidateError(
                "saved page source could not be parsed"
            ) from exc
        if (
            evidence.source_sha256 != expected_sha
            or evidence.item_id != item_id
            or sku_id not in evidence.sku_ids
        ):
            raise PilotCandidateError(
                "saved page product/item/SKU binding mismatch"
            )
        review_count += evidence.review_count
        product = canonical[product_id]
        for parameter_name, values in evidence.parameters.items():
            field_key = _PARAMETER_FIELD_MAP.get(parameter_name)
            if field_key is None:
                continue
            definition = definitions[field_key]
            if product.profile not in definition.profiles:
                continue
            canonical_field = product.fields.get(field_key)
            if (
                isinstance(canonical_field, dict)
                and canonical_field.get("resolved_state") == "known"
            ):
                continue
            try:
                normalized_value = _normalize_parameter_value(
                    values,
                    definition=definition,
                )
            except ValueError:
                continue
            locator = (
                "urn:xiaoro:saved-page:"
                f"sha256:{expected_sha}:item:{item_id}:parameter:"
                f"{_sha256(parameter_name.encode('utf-8'))}"
            )
            value_sha256 = _sha256(
                _canonical_json_bytes(normalized_value)
            )
            candidate_id = _candidate_id(
                product_id=product_id,
                category_profile=product.profile.value,
                field_key=field_key,
                source_sha256=expected_sha,
                source_locator=locator,
                normalized_value=normalized_value,
            )
            candidates.append(
                {
                    "_evidence_source": "html",
                    "candidate_id": candidate_id,
                    "category_profile": product.profile.value,
                    "conflict_candidate_ids": [],
                    "conflict_group_id": None,
                    "extraction_method": "html",
                    "field_key": field_key,
                    "has_conflict": False,
                    "normalized_value": normalized_value,
                    "product_id": product_id,
                    "source_class": SourceClass.STRUCTURED_OFFICIAL.value,
                    "source_locator": locator,
                    "source_sha256": expected_sha,
                    "status": "pending",
                    "value_sha256": value_sha256,
                }
            )
    return candidates, len(sources), review_count


def _quarantine_source_conflicts(
    pending: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    groups: dict[tuple[int, str], list[dict[str, object]]] = {}
    for row in pending:
        groups.setdefault(
            (int(row["product_id"]), str(row["field_key"])),
            [],
        ).append(row)
    conflict_ids: set[str] = set()
    for group in groups.values():
        values = {
            _canonical_json_text(row["normalized_value"])
            for row in group
        }
        if len(values) > 1:
            conflict_ids.update(str(row["candidate_id"]) for row in group)
    retained: list[dict[str, object]] = []
    quarantine: list[dict[str, object]] = []
    for row in pending:
        if row["candidate_id"] not in conflict_ids:
            retained.append(row)
            continue
        quarantine.append(
            _to_quarantine(row, reasons=("source_conflict",))
        )
    return retained, quarantine


def _quarantine_core_conflicts(
    pending: list[dict[str, object]],
    quarantine: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    product_ids = {
        int(row["product_id"])
        for row in quarantine
        if "whole_product_core_conflict"
        in row.get("quarantine_reasons", [])
        and type(row.get("product_id")) is int
    }
    if not product_ids:
        return pending, []
    retained: list[dict[str, object]] = []
    converted: list[dict[str, object]] = []
    for row in pending:
        if row["product_id"] not in product_ids:
            retained.append(row)
            continue
        converted.append(
            _to_quarantine(
                row,
                reasons=("whole_product_core_conflict",),
            )
        )
    return retained, converted


def _to_quarantine(
    row: dict[str, object],
    *,
    reasons: tuple[str, ...],
) -> dict[str, object]:
    return {
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
    } | {
        "quarantine_reasons": sorted(set(reasons)),
        "status": "quarantine",
    }


def _build_status_rows(
    *,
    canonical: dict[int, _CanonicalProduct],
    product_ids: tuple[int, ...],
    pending: list[dict[str, object]],
    quarantine: list[dict[str, object]],
) -> list[dict[str, object]]:
    pending_by_field = _rows_by_field(pending)
    quarantine_by_field = _rows_by_field(quarantine)
    whole_quarantine_ids = {
        int(row["product_id"])
        for row in quarantine
        if "whole_product_core_conflict"
        in row.get("quarantine_reasons", [])
        and type(row.get("product_id")) is int
    }
    status_rows: list[dict[str, object]] = []
    for product_id in product_ids:
        product = canonical[product_id]
        for definition in category_field_registry().for_profile(
            product.profile
        ):
            canonical_field = product.fields.get(definition.key)
            if (
                isinstance(canonical_field, dict)
                and canonical_field.get("resolved_state") == "known"
            ):
                value = canonical_field.get("value")
                status_rows.append(
                    _status_row(
                        product_id=product_id,
                        profile=product.profile,
                        field_key=definition.key,
                        status="known",
                        normalized_value=value,
                        candidate_rows=[],
                        quarantine_reasons=[],
                        evidence_sources=["canonical"],
                    )
                )
                continue
            key = (product_id, definition.key)
            field_pending = pending_by_field.get(key, [])
            field_quarantine = quarantine_by_field.get(key, [])
            if field_pending:
                values = {
                    _canonical_json_text(row["normalized_value"])
                    for row in field_pending
                }
                if len(values) != 1:
                    raise PilotCandidateError(
                        "pending field values are inconsistent"
                    )
                status_rows.append(
                    _status_row(
                        product_id=product_id,
                        profile=product.profile,
                        field_key=definition.key,
                        status="pending",
                        normalized_value=field_pending[0][
                            "normalized_value"
                        ],
                        candidate_rows=field_pending,
                        quarantine_reasons=[],
                        evidence_sources=sorted(
                            {
                                str(row["_evidence_source"])
                                for row in field_pending
                            }
                        ),
                    )
                )
            elif field_quarantine or product_id in whole_quarantine_ids:
                reasons = {
                    str(reason)
                    for row in field_quarantine
                    for reason in row.get("quarantine_reasons", [])
                }
                if product_id in whole_quarantine_ids:
                    reasons.add("whole_product_core_conflict")
                status_rows.append(
                    _status_row(
                        product_id=product_id,
                        profile=product.profile,
                        field_key=definition.key,
                        status="quarantine",
                        normalized_value=None,
                        candidate_rows=field_quarantine,
                        quarantine_reasons=sorted(reasons),
                        evidence_sources=sorted(
                            {
                                str(row["_evidence_source"])
                                for row in field_quarantine
                            }
                        ),
                    )
                )
            else:
                status_rows.append(
                    _status_row(
                        product_id=product_id,
                        profile=product.profile,
                        field_key=definition.key,
                        status="unknown",
                        normalized_value=None,
                        candidate_rows=[],
                        quarantine_reasons=[],
                        evidence_sources=[],
                    )
                )
    return status_rows


def _status_row(
    *,
    product_id: int,
    profile: CategoryProfile,
    field_key: str,
    status: str,
    normalized_value: object,
    candidate_rows: list[dict[str, object]],
    quarantine_reasons: list[str],
    evidence_sources: list[str],
) -> dict[str, object]:
    value_sha256 = (
        _sha256(_canonical_json_bytes(normalized_value))
        if normalized_value is not None
        else None
    )
    return {
        "candidate_ids": sorted(
            str(row["candidate_id"]) for row in candidate_rows
        ),
        "category_profile": profile.value,
        "evidence_sources": evidence_sources,
        "field_key": field_key,
        "normalized_value": normalized_value,
        "product_id": product_id,
        "quarantine_reasons": quarantine_reasons,
        "source_classes": sorted(
            {str(row["source_class"]) for row in candidate_rows}
        ),
        "source_sha256": sorted(
            {str(row["source_sha256"]) for row in candidate_rows}
        ),
        "status": status,
        "value_sha256": value_sha256,
    }


def _rows_by_field(
    rows: list[dict[str, object]],
) -> dict[tuple[int, str], list[dict[str, object]]]:
    grouped: dict[tuple[int, str], list[dict[str, object]]] = {}
    for row in rows:
        product_id = row.get("product_id")
        field_key = row.get("field_key")
        if type(product_id) is int and isinstance(field_key, str):
            grouped.setdefault((product_id, field_key), []).append(row)
    return grouped


def _load_canonical_products(
    path: Path,
    *,
    product_ids: tuple[int, ...],
) -> dict[int, _CanonicalProduct]:
    expected = set(product_ids)
    products: dict[int, _CanonicalProduct] = {}
    for line_number, row in enumerate(
        _load_jsonl(path, label="canonical products"),
        start=1,
    ):
        product_id = row.get("product_id")
        fields = row.get("fields")
        if product_id not in expected:
            continue
        if (
            type(product_id) is not int
            or not isinstance(fields, dict)
            or product_id in products
        ):
            raise PilotCandidateError(
                f"canonical product line {line_number} is invalid"
            )
        category = fields.get("category")
        if (
            not isinstance(category, dict)
            or category.get("resolved_state") != "known"
            or not isinstance(category.get("value"), str)
        ):
            raise PilotCandidateError(
                f"canonical product {product_id} category is invalid"
            )
        try:
            profile = category_profile_for(category["value"])
        except KeyError as exc:
            raise PilotCandidateError(
                f"canonical product {product_id} category is unmapped"
            ) from exc
        products[product_id] = _CanonicalProduct(
            profile=profile,
            fields=fields,
        )
    if set(products) != expected:
        raise PilotCandidateError("canonical target products are incomplete")
    return products


def _load_jsonl(path: Path, *, label: str) -> list[dict[str, object]]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PilotCandidateError(f"{label} could not be read") from exc
    if not content:
        return []
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PilotCandidateError(f"{label} must be UTF-8") from exc
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise PilotCandidateError(
                f"{label} line {line_number} is blank"
            )
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PilotCandidateError(
                f"{label} line {line_number} is invalid"
            ) from exc
        if not isinstance(row, dict):
            raise PilotCandidateError(
                f"{label} line {line_number} is invalid"
            )
        rows.append(row)
    return rows


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotCandidateError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise PilotCandidateError(f"{label} is invalid")
    return payload


def _validate_queue_products(
    rows: list[dict[str, object]],
    *,
    product_ids: set[int],
) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        product_id = row.get("product_id")
        candidate_id = row.get("candidate_id")
        status = row.get("status")
        if (
            type(product_id) is not int
            or product_id not in product_ids
            or not isinstance(candidate_id, str)
            or _SHA256_PATTERN.fullmatch(candidate_id) is None
            or status not in {"pending", "quarantine"}
        ):
            raise PilotCandidateError("database candidate queue is invalid")
        identity = (str(status), candidate_id)
        if identity in seen:
            raise PilotCandidateError(
                "database candidate queue contains duplicates"
            )
        seen.add(identity)


def _normalize_parameter_value(
    values: tuple[str, ...],
    *,
    definition: CategoryFieldDefinition,
) -> object:
    normalized = sorted(
        {
            _normalize_string(value)
            for value in values
            if isinstance(value, str) and value.strip()
        },
        key=lambda item: item.casefold(),
    )
    if not normalized:
        raise ValueError("empty parameter")
    if definition.value_type == "string_list":
        return normalized
    if definition.value_type == "string" and len(normalized) == 1:
        return normalized[0]
    raise ValueError("parameter value type is ambiguous")


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


def _public_rows(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            key: value
            for key, value in row.items()
            if not key.startswith("_")
        }
        for row in rows
    ]


def _deduplicate_by_candidate_id(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    unique: dict[str, dict[str, object]] = {}
    for row in rows:
        candidate_id = str(row["candidate_id"])
        previous = unique.get(candidate_id)
        if previous is not None and previous != row:
            raise PilotCandidateError("candidate ID collision")
        unique[candidate_id] = row
    return [unique[key] for key in sorted(unique)]


def _reject_writer_metadata(rows: list[dict[str, object]]) -> None:
    for row in rows:
        if _FORBIDDEN_WRITER_KEYS & set(row):
            raise PilotCandidateError(
                "candidate writer emitted review metadata"
            )


def _validate_product_ids(
    product_ids: Sequence[int],
) -> tuple[int, ...]:
    values = tuple(product_ids)
    if (
        not values
        or any(type(value) is not int or value <= 0 for value in values)
        or len(values) != len(set(values))
    ):
        raise PilotCandidateError(
            "product_ids must be unique positive integers"
        )
    return tuple(sorted(values))


def _require_distinct_outputs(*paths: str | Path) -> None:
    normalized = [Path(path).resolve(strict=False) for path in paths]
    if len(normalized) != len(set(normalized)):
        raise PilotCandidateError("candidate outputs must be distinct")


def _safe_relative_path(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
    ):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _valid_numeric_id(value: object) -> bool:
    return isinstance(value, str) and _DIGITS.fullmatch(value) is not None


def _hash_prefixes(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "-"
    prefixes = [
        str(item)[:12]
        for item in value
        if isinstance(item, str)
    ]
    return "<br>".join(f"`{prefix}`" for prefix in prefixes) or "-"


def _normalize_string(value: str) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value).split()
    ).strip()
    if not normalized:
        raise ValueError("empty string")
    return normalized


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
        description="Reconcile fifteen pilot candidate states."
    )
    parser.add_argument("--canonical", required=True)
    parser.add_argument("--database-pending", required=True)
    parser.add_argument("--database-quarantine", required=True)
    parser.add_argument("--saved-page-manifest", required=True)
    parser.add_argument("--saved-page-root", required=True)
    parser.add_argument("--product-id", action="append", type=int, required=True)
    parser.add_argument("--status-output", required=True)
    parser.add_argument("--pending-output", required=True)
    parser.add_argument("--quarantine-output", required=True)
    parser.add_argument("--matrix-output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_pilot_candidates(
            canonical_products_path=args.canonical,
            database_pending_path=args.database_pending,
            database_quarantine_path=args.database_quarantine,
            saved_page_manifest_path=args.saved_page_manifest,
            saved_page_root=args.saved_page_root,
            product_ids=tuple(args.product_id),
            status_output_path=args.status_output,
            pending_output_path=args.pending_output,
            quarantine_output_path=args.quarantine_output,
        )
        matrix_sha256 = (
            render_pilot_review_matrix(
                args.status_output,
                args.matrix_output,
            )
            if args.matrix_output
            else None
        )
    except PilotCandidateError:
        return 2
    payload = {
        "known_count": result.known_count,
        "matrix_sha256": matrix_sha256,
        "parsed_page_count": result.parsed_page_count,
        "parsed_review_count": result.parsed_review_count,
        "pending_count": result.pending_count,
        "pending_sha256": result.pending_sha256,
        "product_count": result.product_count,
        "quarantine_count": result.quarantine_count,
        "quarantine_sha256": result.quarantine_sha256,
        "status_count": result.status_count,
        "status_sha256": result.status_sha256,
        "unknown_count": result.unknown_count,
    }
    print(
        json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
