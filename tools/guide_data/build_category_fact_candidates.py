"""Build deterministic pending and quarantine category fact candidates."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Any, Iterator, Literal, Sequence
import unicodedata
from urllib.parse import unquote

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


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_MOBILE_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?86[\s-]?)?1[3-9](?:[\s-]?\d){9}(?!\d)"
)
_LANDLINE_PHONE_PATTERN = re.compile(
    r"(?<!\d)\(?0\d{2,3}\)?[\s-]?\d{7,8}(?!\d)"
)
_ID_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_WECHAT_PATTERN = re.compile(
    r"(?:微信|微\s*信|V信|vx|wechat)\s*"
    r"(?:号|id)?\s*[:：]?\s*[A-Za-z][A-Za-z0-9_-]{5,19}",
    re.IGNORECASE,
)
_QQ_PATTERN = re.compile(
    r"(?:QQ|扣扣)\s*(?:号)?\s*[:：]?\s*[1-9]\d{4,11}",
    re.IGNORECASE,
)
_LABELED_ADDRESS_PATTERN = re.compile(
    r"(?:收货地址|联系地址|家庭住址|住址|地址)\s*[:：]\s*\S{4,}"
)
_STRUCTURED_ADDRESS_PATTERN = re.compile(
    r"(?:省|市).{0,20}(?:区|县).{0,20}"
    r"(?:路|街|道|巷).{0,12}\d+号"
)
_POSIX_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![\w/])/(?!/)[^\s/\\\"'<>|]+"
    r"(?:[/\\][^\s/\\\"'<>|]+)*"
)
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![\w])[A-Za-z]:[\\/]"
)
_UNC_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![\\])\\\\[^\\/\s]+[\\/][^\\/\s]+"
)
_FILE_URI_PATTERN = re.compile(
    r"(?<![\w+.-])file:",
    re.IGNORECASE,
)
_LIST_SEPARATOR_PATTERN = re.compile(r"[,，、;；\n]+")
_PROTECTED_CANONICAL_FIELDS = frozenset(
    {"product_identity", "brand", "category", "price"}
)
_PII_PATTERNS = (
    _EMAIL_PATTERN,
    _MOBILE_PHONE_PATTERN,
    _LANDLINE_PHONE_PATTERN,
    _ID_CARD_PATTERN,
    _WECHAT_PATTERN,
    _QQ_PATTERN,
    _LABELED_ADDRESS_PATTERN,
    _STRUCTURED_ADDRESS_PATTERN,
)
_SOURCE_TYPES = frozenset({"html", "ocr_json", "structured_json"})
_HTML_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

JsonValue = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None
SourceType = Literal["html", "ocr_json", "structured_json"]
_SOURCE_CLASS_ALLOWLIST: dict[SourceType, frozenset[SourceClass]] = {
    "html": frozenset({SourceClass.OFFICIAL_DESCRIPTION}),
    "ocr_json": frozenset(
        {
            SourceClass.OCR_PACKAGING,
            SourceClass.OCR_INGREDIENT_LIST,
        }
    ),
    "structured_json": frozenset(
        {
            SourceClass.STRUCTURED_OFFICIAL,
            SourceClass.OFFICIAL_PACKAGING,
            SourceClass.OFFICIAL_DESCRIPTION,
        }
    ),
}


class CandidateBuildError(RuntimeError):
    """Raised when declared source inputs cannot be trusted or parsed."""


@dataclass(frozen=True, slots=True)
class CandidateBuildReport:
    input_count: int
    pending_count: int
    quarantine_count: int
    duplicate_count: int
    conflict_group_count: int
    pending_sha256: str
    quarantine_sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "conflict_group_count": self.conflict_group_count,
            "duplicate_count": self.duplicate_count,
            "input_count": self.input_count,
            "pending_count": self.pending_count,
            "pending_sha256": self.pending_sha256,
            "quarantine_count": self.quarantine_count,
            "quarantine_sha256": self.quarantine_sha256,
        }


@dataclass(frozen=True, slots=True)
class _SourceSpec:
    source_id: str
    source_type: SourceType
    path: Path
    content: bytes
    source_sha256: str
    product_id: int
    category_profile: str
    source_class: str


@dataclass(frozen=True, slots=True)
class _CanonicalProduct:
    profile: CategoryProfile
    core_values: dict[str, object]


@dataclass(frozen=True, slots=True)
class _ExtractedFact:
    source: _SourceSpec
    ordinal: int
    product_id: object
    category_profile: object
    field_key: object
    source_class: object
    source_locator: object
    value: object


@dataclass(slots=True)
class _HtmlCapture:
    depth: int
    field_key: str
    source_locator: str
    parts: list[str]


class _CategoryFactHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.captures: list[_HtmlCapture] = []
        self.records: list[tuple[str, str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in _HTML_VOID_ELEMENTS:
            if normalized_tag == "br":
                for capture in self.captures:
                    capture.parts.append(" ")
            self._capture_standalone(attrs)
            return
        self.depth += 1
        attributes = dict(attrs)
        field_key = attributes.get("data-guide-field")
        if field_key is None:
            return
        locator = attributes.get("data-source-locator")
        if not locator:
            locator = f"html:fact-{len(self.records) + len(self.captures) + 1:08d}"
        self.captures.append(
            _HtmlCapture(
                depth=self.depth,
                field_key=field_key,
                source_locator=locator,
                parts=[],
            )
        )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() == "br":
            for capture in self.captures:
                capture.parts.append(" ")
        self._capture_standalone(attrs)

    def _capture_standalone(
        self,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        field_key = attributes.get("data-guide-field")
        if field_key is None:
            return
        locator = attributes.get("data-source-locator")
        if not locator:
            locator = f"html:fact-{len(self.records) + 1:08d}"
        value = attributes.get("data-guide-value") or ""
        self.records.append((field_key, locator, value))

    def handle_data(self, data: str) -> None:
        for capture in self.captures:
            capture.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in _HTML_VOID_ELEMENTS:
            return
        completed = [
            capture
            for capture in self.captures
            if capture.depth == self.depth
        ]
        for capture in completed:
            self.records.append(
                (
                    capture.field_key,
                    capture.source_locator,
                    "".join(capture.parts),
                )
            )
            self.captures.remove(capture)
        self.depth = max(0, self.depth - 1)


class _MarkupDetector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.found_markup = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.found_markup = True

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.found_markup = True

    def handle_endtag(self, tag: str) -> None:
        self.found_markup = True

    def handle_comment(self, data: str) -> None:
        self.found_markup = True

    def handle_decl(self, decl: str) -> None:
        self.found_markup = True

    def handle_pi(self, data: str) -> None:
        self.found_markup = True


def build_category_fact_candidates(
    *,
    source_manifest_path: str | Path,
    canonical_products_path: str | Path,
    output_path: str | Path,
    quarantine_path: str | Path,
) -> CandidateBuildReport:
    """Build deterministic review inputs without approving any fact."""

    declared_pending_path = Path(output_path)
    declared_rejected_path = Path(quarantine_path)
    _reject_output_symlink(declared_pending_path)
    _reject_output_symlink(declared_rejected_path)
    manifest_path = Path(source_manifest_path).resolve(strict=True)
    canonical_path = Path(canonical_products_path).resolve(strict=True)
    pending_path = _normalize_output_path(declared_pending_path)
    rejected_path = _normalize_output_path(declared_rejected_path)
    if pending_path == rejected_path:
        raise CandidateBuildError(
            "pending and quarantine outputs must be different"
        )

    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    canonical_products = _load_canonical_products(canonical_path)
    sources = _load_source_manifest(manifest_path)
    extracted = tuple(
        fact
        for source in sources
        for fact in _extract_source(source)
    )

    pending_rows: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []
    for fact in extracted:
        pending, row = _classify_fact(
            fact,
            definitions=definitions,
            canonical_products=canonical_products,
        )
        (pending_rows if pending else quarantine_rows).append(row)

    pending_rows, pending_duplicates = _deduplicate_rows(pending_rows)
    quarantine_rows, quarantine_duplicates = _deduplicate_rows(
        quarantine_rows
    )
    (
        pending_rows,
        quarantine_rows,
        cross_status_duplicates,
    ) = _quarantine_cross_status_duplicates(
        pending_rows,
        quarantine_rows,
    )
    duplicate_count = (
        pending_duplicates
        + quarantine_duplicates
        + cross_status_duplicates
    )
    (
        pending_rows,
        quarantine_rows,
        conflict_group_count,
        core_conflict_product_ids,
    ) = _quarantine_field_conflicts(
        pending_rows,
        quarantine_rows,
    )
    binding_conflict_product_ids: set[int] = set()
    for row in pending_rows + quarantine_rows:
        if row.get("_binding_conflict") is not True:
            continue
        for product_id in (
            row.get("_bound_product_id"),
            row.get("product_id"),
        ):
            if isinstance(product_id, int) and not isinstance(
                product_id,
                bool,
            ):
                binding_conflict_product_ids.add(product_id)
    pending_rows, quarantine_rows = _quarantine_whole_products(
        pending_rows,
        quarantine_rows,
        product_ids=binding_conflict_product_ids,
        reason="whole_product_binding_conflict",
    )
    core_conflict_product_ids.update(
        row["product_id"]
        for row in quarantine_rows
        if "core_value_conflict" in row["quarantine_reasons"]
        and isinstance(row["product_id"], int)
    )
    pending_rows, quarantine_rows = _quarantine_whole_products(
        pending_rows,
        quarantine_rows,
        product_ids=core_conflict_product_ids,
        reason="whole_product_core_conflict",
    )
    for row in pending_rows + quarantine_rows:
        for internal_key in (
            "_binding_conflict",
            "_bound_product_id",
            "_conflict_value",
        ):
            row.pop(internal_key, None)
    pending_rows.sort(key=lambda row: row["candidate_id"])
    quarantine_rows.sort(key=lambda row: row["candidate_id"])
    _validate_candidate_accounting(
        input_count=len(extracted),
        pending_rows=pending_rows,
        quarantine_rows=quarantine_rows,
        duplicate_count=duplicate_count,
        conflict_group_count=conflict_group_count,
    )

    pending_bytes = _jsonl_bytes(pending_rows)
    quarantine_bytes = _jsonl_bytes(quarantine_rows)
    _publish_output_pair(
        pending_path=pending_path,
        pending_content=pending_bytes,
        quarantine_path=rejected_path,
        quarantine_content=quarantine_bytes,
    )
    return CandidateBuildReport(
        input_count=len(extracted),
        pending_count=len(pending_rows),
        quarantine_count=len(quarantine_rows),
        duplicate_count=duplicate_count,
        conflict_group_count=conflict_group_count,
        pending_sha256=_sha256(pending_bytes),
        quarantine_sha256=_sha256(quarantine_bytes),
    )


def _load_source_manifest(path: Path) -> tuple[_SourceSpec, ...]:
    manifest = _load_json_object(path, label="source manifest")
    if set(manifest) != {"schema_version", "sources"}:
        raise CandidateBuildError("source manifest fields are invalid")
    if manifest["schema_version"] != "guide-category-source-manifest-v1":
        raise CandidateBuildError("source manifest schema version is invalid")
    raw_sources = manifest["sources"]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise CandidateBuildError("source manifest sources must be non-empty")

    source_root = path.parent
    sources: list[_SourceSpec] = []
    source_ids: set[str] = set()
    expected_fields = {
        "category_profile",
        "path",
        "product_id",
        "sha256",
        "source_class",
        "source_id",
        "source_type",
    }
    for index, raw_source in enumerate(raw_sources, start=1):
        if not isinstance(raw_source, dict) or set(raw_source) != expected_fields:
            raise CandidateBuildError(
                f"source manifest entry {index} fields are invalid"
            )
        source_id = raw_source["source_id"]
        if (
            not isinstance(source_id, str)
            or _SOURCE_ID_PATTERN.fullmatch(source_id) is None
        ):
            raise CandidateBuildError(
                f"source manifest entry {index} source_id is invalid"
            )
        if source_id in source_ids:
            raise CandidateBuildError("source manifest source_id is duplicated")
        source_ids.add(source_id)

        source_type = raw_source["source_type"]
        if not isinstance(source_type, str) or source_type not in _SOURCE_TYPES:
            raise CandidateBuildError(
                f"source manifest entry {index} source_type is invalid"
            )
        relative_path = raw_source["path"]
        if not isinstance(relative_path, str) or not relative_path:
            raise CandidateBuildError(
                f"source manifest entry {index} path is invalid"
            )
        declared_path = Path(relative_path)
        try:
            source_bytes = read_relative_regular_bytes(
                source_root,
                declared_path,
            )
        except SafeSourceIOError as exc:
            raise CandidateBuildError(
                "source path must be a stable regular file"
            ) from exc
        source_path = source_root / declared_path

        expected_sha256 = raw_source["sha256"]
        if (
            not isinstance(expected_sha256, str)
            or _SHA256_PATTERN.fullmatch(expected_sha256) is None
        ):
            raise CandidateBuildError(
                f"source manifest entry {index} SHA-256 is invalid"
            )
        actual_sha256 = _sha256(source_bytes)
        if actual_sha256 != expected_sha256:
            raise CandidateBuildError(
                f"source manifest entry {index} SHA-256 mismatch"
            )
        product_id = raw_source["product_id"]
        if (
            isinstance(product_id, bool)
            or not isinstance(product_id, int)
            or product_id <= 0
        ):
            raise CandidateBuildError(
                f"source manifest entry {index} product_id is invalid"
            )
        category_profile = raw_source["category_profile"]
        source_class = raw_source["source_class"]
        if not isinstance(category_profile, str) or not category_profile:
            raise CandidateBuildError(
                f"source manifest entry {index} profile is invalid"
            )
        if not isinstance(source_class, str) or not source_class:
            raise CandidateBuildError(
                f"source manifest entry {index} source class is invalid"
            )
        try:
            declared_source_class = SourceClass(source_class)
        except ValueError as exc:
            raise CandidateBuildError(
                f"source manifest entry {index} source class is invalid"
            ) from exc
        if declared_source_class not in _SOURCE_CLASS_ALLOWLIST[source_type]:
            raise CandidateBuildError(
                "source_type/source_class combination is not allowed"
            )
        sources.append(
            _SourceSpec(
                source_id=source_id,
                source_type=source_type,  # type: ignore[arg-type]
                path=source_path,
                content=source_bytes,
                source_sha256=actual_sha256,
                product_id=product_id,
                category_profile=category_profile,
                source_class=source_class,
            )
        )
    return tuple(sources)


def _load_canonical_products(
    path: Path,
) -> dict[int, _CanonicalProduct]:
    products: dict[int, _CanonicalProduct] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            product_id = row["product_id"]
            fields = row["fields"]
            category = fields["category"]
            raw_category = category["value"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CandidateBuildError(
                f"canonical product line {line_number} is invalid"
            ) from exc
        if (
            isinstance(product_id, bool)
            or not isinstance(product_id, int)
            or product_id <= 0
            or not isinstance(raw_category, str)
            or category.get("resolved_state") != "known"
        ):
            raise CandidateBuildError(
                f"canonical product line {line_number} binding is invalid"
            )
        if product_id in products:
            raise CandidateBuildError("canonical product_id is duplicated")
        try:
            core_values = {
                field_key: _normalize_core_value(
                    field_key,
                    fields[field_key]["value"],
                )
                for field_key in _PROTECTED_CANONICAL_FIELDS
            }
            if any(
                fields[field_key].get("resolved_state") != "known"
                for field_key in _PROTECTED_CANONICAL_FIELDS
            ):
                raise CandidateBuildError(
                    f"canonical product line {line_number} core is unknown"
                )
            products[product_id] = _CanonicalProduct(
                profile=category_profile_for(raw_category),
                core_values=core_values,
            )
        except KeyError as exc:
            raise CandidateBuildError(
                f"canonical product line {line_number} category is unmapped"
            ) from exc
    if not products:
        raise CandidateBuildError("canonical product file is empty")
    return products


def _extract_source(source: _SourceSpec) -> tuple[_ExtractedFact, ...]:
    if source.source_type == "html":
        parser = _CategoryFactHtmlParser()
        try:
            parser.feed(source.content.decode("utf-8"))
            parser.close()
        except UnicodeError as exc:
            raise CandidateBuildError("HTML source cannot be parsed") from exc
        raw_records: list[dict[str, object]] = [
            {
                "field_key": field_key,
                "source_locator": source_locator,
                "value": value,
            }
            for field_key, source_locator, value in parser.records
        ]
    else:
        payload = _load_json_object_bytes(
            source.content,
            label=source.source_type,
        )
        if source.source_type == "ocr_json":
            version = "guide-category-ocr-v1"
            collection_key = "observations"
        else:
            version = "guide-category-official-v1"
            collection_key = "facts"
        if set(payload) != {"schema_version", collection_key}:
            raise CandidateBuildError(
                f"{source.source_type} fields are invalid"
            )
        if payload["schema_version"] != version:
            raise CandidateBuildError(
                f"{source.source_type} schema version is invalid"
            )
        records = payload[collection_key]
        if not isinstance(records, list):
            raise CandidateBuildError(
                f"{source.source_type} records must be an array"
            )
        raw_records = records

    extracted: list[_ExtractedFact] = []
    allowed_record_fields = {
        "category_profile",
        "field_key",
        "product_id",
        "source_class",
        "source_locator",
        "value",
    }
    required_record_fields = {"field_key", "source_locator", "value"}
    for ordinal, record in enumerate(raw_records, start=1):
        if (
            not isinstance(record, dict)
            or not required_record_fields <= set(record)
            or not set(record) <= allowed_record_fields
        ):
            raise CandidateBuildError(
                f"{source.source_type} record {ordinal} is invalid"
            )
        extracted.append(
            _ExtractedFact(
                source=source,
                ordinal=ordinal,
                product_id=record.get("product_id", source.product_id),
                category_profile=record.get(
                    "category_profile",
                    source.category_profile,
                ),
                field_key=record["field_key"],
                source_class=record.get(
                    "source_class",
                    source.source_class,
                ),
                source_locator=record["source_locator"],
                value=record["value"],
            )
        )
    return tuple(extracted)


def _classify_fact(
    fact: _ExtractedFact,
    *,
    definitions: dict[str, CategoryFieldDefinition],
    canonical_products: dict[int, _CanonicalProduct],
) -> tuple[bool, dict[str, Any]]:
    reasons: set[str] = set()
    binding_conflict = (
        fact.product_id != fact.source.product_id
        or fact.category_profile != fact.source.category_profile
    )
    if (
        binding_conflict
        or fact.source_class != fact.source.source_class
    ):
        reasons.add("source_binding_mismatch")
    product_id = fact.product_id
    valid_product_id = (
        not isinstance(product_id, bool)
        and isinstance(product_id, int)
        and product_id > 0
    )
    canonical_product = (
        canonical_products.get(product_id) if valid_product_id else None
    )
    if canonical_product is None:
        reasons.add("product_not_found")

    profile: CategoryProfile | None = None
    if isinstance(fact.category_profile, str):
        try:
            profile = CategoryProfile(fact.category_profile)
        except ValueError:
            reasons.add("unknown_profile")
    else:
        reasons.add("unknown_profile")
    if (
        canonical_product is not None
        and profile is not None
        and canonical_product.profile is not profile
    ):
        reasons.add("product_profile_mismatch")

    field_key = (
        fact.field_key if isinstance(fact.field_key, str) else ""
    )
    definition = definitions.get(field_key)
    if definition is None:
        reasons.add("unknown_field")
    elif profile is not None and profile not in definition.profiles:
        reasons.add("field_not_applicable")
    supplied_core_value: object | None = None
    if field_key in _PROTECTED_CANONICAL_FIELDS:
        reasons.add("protected_canonical_field")
        if canonical_product is not None:
            try:
                supplied_core_value = _normalize_core_value(
                    field_key,
                    fact.value,
                )
            except ValueError:
                reasons.add("invalid_value")
            else:
                if (
                    supplied_core_value
                    != canonical_product.core_values[field_key]
                ):
                    reasons.add("core_value_conflict")

    source_class: SourceClass | None = None
    if isinstance(fact.source_class, str):
        try:
            source_class = SourceClass(fact.source_class)
        except ValueError:
            reasons.add("unknown_source")
    else:
        reasons.add("unknown_source")
    if source_class is SourceClass.UNKNOWN:
        reasons.add("unknown_source")
    elif definition is not None and source_class is not None:
        authorized_sources = {
            policy.source_class
            for policy in definition.source_policies
        }
        if source_class not in authorized_sources:
            reasons.add("source_not_authorized")
    if (
        source_class is not None
        and source_class
        not in _SOURCE_CLASS_ALLOWLIST[fact.source.source_type]
    ):
        reasons.add("source_type_not_authorized")

    value_sha256 = _sha256(_canonical_json_bytes(fact.value))
    sensitive_value = _contains_sensitive_value(fact.value)
    if sensitive_value:
        reasons.add("sensitive_value")

    normalized_value: object | None = None
    if definition is not None:
        try:
            normalized_value = _normalize_value(
                fact.value,
                definition=definition,
            )
        except ValueError:
            reasons.add("invalid_value")
    locator = _safe_source_locator(
        source_id=fact.source.source_id,
        value=fact.source_locator,
        ordinal=fact.ordinal,
    )
    public_product_id = product_id if valid_product_id else None
    public_profile = _safe_identifier(
        fact.category_profile,
        fallback_label="invalid-profile",
    )
    public_field_key = _safe_identifier(
        fact.field_key,
        fallback_label="invalid-field",
    )
    public_source_class = _safe_identifier(
        fact.source_class,
        fallback_label="invalid-source",
    )
    id_value = (
        normalized_value
        if normalized_value is not None and not sensitive_value
        else {"value_sha256": value_sha256}
    )
    candidate_id = _build_candidate_id(
        product_id=public_product_id,
        category_profile=public_profile,
        field_key=public_field_key,
        source_sha256=fact.source.source_sha256,
        source_locator=locator,
        normalized_value=id_value,
    )
    common = {
        "_binding_conflict": binding_conflict,
        "_bound_product_id": fact.source.product_id,
        "_conflict_value": (
            supplied_core_value
            if supplied_core_value is not None
            else normalized_value
        ),
        "candidate_id": candidate_id,
        "category_profile": public_profile,
        "extraction_method": fact.source.source_type,
        "field_key": public_field_key,
        "product_id": public_product_id,
        "source_class": public_source_class,
        "source_locator": locator,
        "source_sha256": fact.source.source_sha256,
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


def _normalize_value(
    value: object,
    *,
    definition: CategoryFieldDefinition,
) -> object:
    if _contains_sensitive_value(value):
        raise ValueError("sensitive value")
    if definition.value_type == "string":
        if not isinstance(value, str):
            raise ValueError("expected string")
        return _normalize_string(value)
    if definition.value_type == "string_list":
        return _normalize_string_list(value)
    if definition.value_type == "boolean":
        return _normalize_boolean(value)
    if definition.value_type == "number":
        return _normalize_number(value)
    raise ValueError("unknown value type")


def _normalize_core_value(field_key: str, value: object) -> object:
    if field_key == "price":
        return _normalize_number(value)
    if field_key in {"brand", "category", "product_identity"}:
        if not isinstance(value, str):
            raise ValueError("expected core string")
        return _normalize_string(value)
    raise ValueError("unknown core field")


def _normalize_string(value: str) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value).split()
    ).strip()
    if not normalized:
        raise ValueError("empty string")
    return normalized


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw_items = _LIST_SEPARATOR_PATTERN.split(value)
    elif isinstance(value, list) and not isinstance(value, str):
        raw_items = value
    else:
        raise ValueError("expected string list")
    normalized: dict[str, str] = {}
    for item in raw_items:
        if not isinstance(item, str):
            raise ValueError("string list contains non-string")
        if not unicodedata.normalize("NFKC", item).strip():
            continue
        item_value = _normalize_string(item)
        normalized.setdefault(item_value.casefold(), item_value)
    if not normalized:
        raise ValueError("empty string list")
    return [
        normalized[key]
        for key in sorted(normalized, key=lambda item: (item, normalized[item]))
    ]


def _normalize_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = _normalize_string(value).casefold()
        if normalized in {"true", "yes", "1", "是", "需要"}:
            return True
        if normalized in {"false", "no", "0", "否", "不需要"}:
            return False
    raise ValueError("expected boolean")


def _normalize_number(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("expected number")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid number") from exc
    if not number.is_finite():
        raise ValueError("number must be finite")
    if number == number.to_integral():
        return int(number)
    result = float(number.normalize())
    if not math.isfinite(result):
        raise ValueError("number must be finite")
    return result


def _contains_sensitive_value(value: object) -> bool:
    for text in _iter_strings(value):
        if (
            any(pattern.search(text) for pattern in _PII_PATTERNS)
            or _looks_like_absolute_path(text)
            or _contains_html_markup(text)
        ):
            return True
    return False


def _iter_strings(value: object) -> Sequence[str]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(
            text
            for item in value
            for text in _iter_strings(item)
        )
    if isinstance(value, dict):
        return tuple(
            text
            for key, item in value.items()
            for text in (
                *_iter_strings(key),
                *_iter_strings(item),
            )
        )
    return ()


def _contains_html_markup(value: str) -> bool:
    detector = _MarkupDetector()
    try:
        detector.feed(value)
        detector.close()
    except Exception:
        return True
    return detector.found_markup


def _looks_like_absolute_path(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    for _ in range(3):
        if (
            _FILE_URI_PATTERN.search(normalized) is not None
            or _POSIX_ABSOLUTE_PATH_PATTERN.search(normalized) is not None
            or _WINDOWS_ABSOLUTE_PATH_PATTERN.search(normalized) is not None
            or _UNC_ABSOLUTE_PATH_PATTERN.search(normalized) is not None
        ):
            return True
        decoded = unicodedata.normalize("NFKC", unquote(normalized))
        if decoded == normalized:
            break
        normalized = decoded
    return False


def _safe_source_locator(
    *,
    source_id: str,
    value: object,
    ordinal: int,
) -> str:
    if not isinstance(value, str) or not value.strip():
        return f"{source_id}:record:{ordinal:08d}"
    normalized = _normalize_string(value)
    unsafe = (
        len(normalized) > 256
        or "\n" in value
        or "\r" in value
        or _looks_like_absolute_path(normalized)
        or any(pattern.search(normalized) for pattern in _PII_PATTERNS)
        or _contains_html_markup(normalized)
    )
    if unsafe:
        locator_hash = _sha256(normalized.encode("utf-8"))[:16]
        return f"{source_id}:redacted:{locator_hash}"
    return f"{source_id}:{normalized}"


def _safe_identifier(value: object, *, fallback_label: str) -> str:
    if isinstance(value, str) and _FIELD_KEY_PATTERN.fullmatch(value):
        return value
    value_hash = _sha256(_canonical_json_bytes(value))[:16]
    return f"{fallback_label}-{value_hash}"


def _build_candidate_id(
    *,
    product_id: int | None,
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


def _deduplicate_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    unique: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for row in rows:
        candidate_id = row["candidate_id"]
        previous = unique.get(candidate_id)
        if previous is None:
            unique[candidate_id] = row
            continue
        if previous != row:
            raise CandidateBuildError("candidate ID collision")
        duplicate_count += 1
    return list(unique.values()), duplicate_count


def _quarantine_cross_status_duplicates(
    pending_rows: list[dict[str, Any]],
    quarantine_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    pending_by_id = {
        row["candidate_id"]: row
        for row in pending_rows
    }
    quarantine_by_id = {
        row["candidate_id"]: row
        for row in quarantine_rows
    }
    duplicate_ids = set(pending_by_id) & set(quarantine_by_id)
    for candidate_id in sorted(duplicate_ids):
        quarantined = quarantine_by_id[candidate_id]
        reasons = set(quarantined["quarantine_reasons"])
        reasons.add("candidate_id_conflict")
        quarantined["quarantine_reasons"] = sorted(reasons)
    return (
        [
            row
            for row in pending_rows
            if row["candidate_id"] not in duplicate_ids
        ],
        quarantine_rows,
        len(duplicate_ids),
    )


def _quarantine_field_conflicts(
    pending_rows: list[dict[str, Any]],
    quarantine_rows: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
    set[int],
]:
    groups: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for row in pending_rows + quarantine_rows:
        if not isinstance(row["product_id"], int):
            continue
        group_key = (
            row["product_id"],
            row["category_profile"],
            row["field_key"],
        )
        groups.setdefault(group_key, []).append(row)

    conflict_groups = 0
    conflicting_ids: set[str] = set()
    core_conflict_product_ids: set[int] = set()
    for group_key, group_rows in groups.items():
        values = {
            (
                "normalized",
                _canonical_json_text(row["_conflict_value"]),
            )
            if row.get("_conflict_value") is not None
            else ("raw", row["value_sha256"])
            for row in group_rows
        }
        if len(values) <= 1:
            continue
        conflict_groups += 1
        for row in group_rows:
            conflicting_ids.add(row["candidate_id"])
        if group_key[2] in _PROTECTED_CANONICAL_FIELDS:
            core_conflict_product_ids.add(group_key[0])

    retained_pending: list[dict[str, Any]] = []
    moved_quarantine: list[dict[str, Any]] = []
    for row in pending_rows:
        if row["candidate_id"] in conflicting_ids:
            moved_quarantine.append(
                _as_quarantine(row, reason="field_value_conflict")
            )
        else:
            retained_pending.append(row)
    updated_quarantine = [
        (
            _as_quarantine(row, reason="field_value_conflict")
            if row["candidate_id"] in conflicting_ids
            else row
        )
        for row in quarantine_rows
    ]
    updated_quarantine.extend(moved_quarantine)
    return (
        retained_pending,
        updated_quarantine,
        conflict_groups,
        core_conflict_product_ids,
    )


def _quarantine_whole_products(
    pending_rows: list[dict[str, Any]],
    quarantine_rows: list[dict[str, Any]],
    *,
    product_ids: set[int],
    reason: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    retained_pending: list[dict[str, Any]] = []
    moved_quarantine: list[dict[str, Any]] = []
    for row in pending_rows:
        if row["product_id"] in product_ids:
            moved_quarantine.append(_as_quarantine(row, reason=reason))
        else:
            retained_pending.append(row)
    updated_quarantine = [
        (
            _as_quarantine(row, reason=reason)
            if row["product_id"] in product_ids
            else row
        )
        for row in quarantine_rows
    ]
    updated_quarantine.extend(moved_quarantine)
    return retained_pending, updated_quarantine


def _as_quarantine(
    row: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    reasons = set(row.get("quarantine_reasons", []))
    reasons.add(reason)
    return {
        "candidate_id": row["candidate_id"],
        "category_profile": row["category_profile"],
        "extraction_method": row["extraction_method"],
        "field_key": row["field_key"],
        "product_id": row["product_id"],
        "quarantine_reasons": sorted(reasons),
        "source_class": row["source_class"],
        "source_locator": row["source_locator"],
        "source_sha256": row["source_sha256"],
        "status": "quarantine",
        "value_sha256": row["value_sha256"],
    }


def _validate_candidate_accounting(
    *,
    input_count: int,
    pending_rows: list[dict[str, Any]],
    quarantine_rows: list[dict[str, Any]],
    duplicate_count: int,
    conflict_group_count: int,
) -> None:
    all_rows = pending_rows + quarantine_rows
    candidate_ids = [row["candidate_id"] for row in all_rows]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise CandidateBuildError("candidate IDs must be globally unique")
    if input_count != len(all_rows) + duplicate_count:
        raise CandidateBuildError("candidate counts are not conserved")
    if any(
        (
            row["has_conflict"]
            or row["conflict_group_id"] is not None
            or row["conflict_candidate_ids"]
        )
        for row in pending_rows
    ):
        raise CandidateBuildError(
            "conflicting candidate cannot remain pending"
        )
    if conflict_group_count < 0:
        raise CandidateBuildError("conflict group count is invalid")


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise CandidateBuildError(f"{label} is not valid JSON") from exc
    return _load_json_object_bytes(content, label=label)


def _load_json_object_bytes(
    content: bytes,
    *,
    label: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateBuildError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise CandidateBuildError(f"{label} must be a JSON object")
    return payload


def _canonical_json_text(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CandidateBuildError("source value is not valid JSON") from exc


def _canonical_json_bytes(value: object) -> bytes:
    return _canonical_json_text(value).encode("utf-8")


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        _canonical_json_bytes(row) + b"\n"
        for row in rows
    )


def _reject_output_symlink(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        raise CandidateBuildError(
            "candidate output cannot be inspected"
        ) from exc
    if stat.S_ISLNK(mode):
        raise CandidateBuildError("candidate output cannot be a symlink")


def _normalize_output_path(path: Path) -> Path:
    try:
        parent = path.parent.resolve()
    except OSError as exc:
        raise CandidateBuildError(
            "candidate output parent cannot be resolved"
        ) from exc
    return parent / path.name


def _publish_output_pair(
    *,
    pending_path: Path,
    pending_content: bytes,
    quarantine_path: Path,
    quarantine_content: bytes,
) -> None:
    targets = (
        (pending_path, pending_content),
        (quarantine_path, quarantine_content),
    )
    parents = sorted(
        {path.parent for path, _ in targets},
        key=lambda path: str(path),
    )
    for parent in parents:
        parent.mkdir(parents=True, exist_ok=True)

    pair_key = _sha256(
        "\0".join(
            sorted(str(path) for path, _ in targets)
        ).encode("utf-8")
    )[:16]
    lock_paths = tuple(
        sorted(
            (
                target.parent
                / (
                    ".category-fact-candidates."
                    f"{_sha256(os.fsencode(str(target)))}.lock"
                )
                for target, _ in targets
            ),
            key=str,
        )
    )
    with _exclusive_publish_locks(lock_paths):
        staging_roots = {
            parent: _private_staging_directory(parent, pair_key)
            for parent in parents
        }
        try:
            staged_targets: list[tuple[Path, Path]] = []
            previous_content: dict[Path, bytes | None] = {}
            for index, (target, content) in enumerate(targets):
                _reject_output_symlink(target)
                previous_content[target] = (
                    target.read_bytes() if target.exists() else None
                )
                staged = (
                    staging_roots[target.parent]
                    / f"{index:02d}-{target.name}.new"
                )
                _write_private_file(staged, content)
                staged_targets.append((staged, target))

            published: list[Path] = []
            try:
                for staged, target in staged_targets:
                    _reject_output_symlink(target)
                    os.replace(staged, target)
                    published.append(target)
                for parent in parents:
                    _fsync_directory(parent)
            except BaseException as publish_error:
                rollback_errors: list[BaseException] = []
                for target in reversed(published):
                    try:
                        _restore_output(
                            target,
                            previous_content[target],
                            staging_root=staging_roots[target.parent],
                        )
                    except BaseException as rollback_error:
                        rollback_errors.append(rollback_error)
                for parent in parents:
                    try:
                        _fsync_directory(parent)
                    except BaseException as rollback_error:
                        rollback_errors.append(rollback_error)
                if rollback_errors:
                    raise CandidateBuildError(
                        "candidate output rollback failed"
                    ) from publish_error
                raise
        finally:
            for staging_root in staging_roots.values():
                shutil.rmtree(staging_root)


def _private_staging_directory(parent: Path, pair_key: str) -> Path:
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".category-fact-candidates.{pair_key}.",
            suffix=".staging",
            dir=parent,
        )
    )
    os.chmod(staging_root, 0o700)
    return staging_root


@contextmanager
def _exclusive_publish_locks(paths: Sequence[Path]) -> Iterator[None]:
    with ExitStack() as stack:
        for path in paths:
            stack.enter_context(_exclusive_publish_lock(path))
        yield


@contextmanager
def _exclusive_publish_lock(path: Path) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(file_descriptor, 0o600)
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise CandidateBuildError("publish lock must be a regular file")
        fcntl.flock(file_descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(file_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(file_descriptor)


def _write_private_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    file_descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "wb") as output:
            file_descriptor = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def _restore_output(
    path: Path,
    content: bytes | None,
    *,
    staging_root: Path,
) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    rollback_path = staging_root / f"{path.name}.rollback"
    _write_private_file(rollback_path, content)
    os.replace(rollback_path, path)


def _fsync_directory(path: Path) -> None:
    file_descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic pending and quarantine category facts."
        )
    )
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--canonical-products", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--quarantine", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_category_fact_candidates(
            source_manifest_path=args.source_manifest,
            canonical_products_path=args.canonical_products,
            output_path=args.output,
            quarantine_path=args.quarantine,
        )
    except (CandidateBuildError, OSError) as exc:
        print(
            json.dumps(
                {"error": type(exc).__name__, "status": "failed"},
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=os.sys.stderr,
        )
        return 2
    print(
        json.dumps(
            report.as_dict(),
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
