from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import stat
from typing import Literal, Self
from urllib.parse import unquote

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
    UnknownProductError,
)
from app.guide.retrieval.category_fact_contracts import (
    Capability,
    CategoryFieldRegistry,
    SourceClass,
)
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)


_SCHEMA_VERSION = "approved-category-facts-v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CATEGORY_FACT_SOURCE_REF_PATTERN = re.compile(
    r"^urn:xiaoro:category-fact-source:sha256:"
    r"[0-9a-f]{64}:[0-9a-f]{64}$"
)
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
_HTTP_URL_PATTERN = re.compile(
    r"https?://[^\s<>'\"]+",
    re.IGNORECASE,
)
_FILE_URI_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+.-])file:",
    re.IGNORECASE,
)
_UNIX_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![\w._~%+-])/(?![/\s])"
)
_HOME_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._~%+-])~[\\/]"
)
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
)
_UNC_PATH_PATTERN = re.compile(r"(?<!\\)\\\\(?![\\\s])")


class CategoryFactAssetIntegrityError(RuntimeError):
    pass


class _HTMLMarkupDetector(HTMLParser):
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

    def unknown_decl(self, data: str) -> None:
        self.found_markup = True


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PilotBinding(_StrictFrozenModel):
    category_profile: CategoryProfile
    product_id: int = Field(gt=0)

    @field_validator("category_profile", mode="before")
    @classmethod
    def parse_category_profile(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return CategoryProfile(value)
            except ValueError:
                return value
        return value


PILOT_BINDINGS = (
    PilotBinding(
        category_profile=CategoryProfile.SKINCARE,
        product_id=38,
    ),
    PilotBinding(
        category_profile=CategoryProfile.SKINCARE,
        product_id=91,
    ),
    PilotBinding(
        category_profile=CategoryProfile.SUNCARE,
        product_id=53,
    ),
    PilotBinding(
        category_profile=CategoryProfile.SUNCARE,
        product_id=57,
    ),
    PilotBinding(
        category_profile=CategoryProfile.BASE_MAKEUP,
        product_id=79,
    ),
    PilotBinding(
        category_profile=CategoryProfile.BASE_MAKEUP,
        product_id=80,
    ),
    PilotBinding(
        category_profile=CategoryProfile.COLOR_MAKEUP,
        product_id=86,
    ),
    PilotBinding(
        category_profile=CategoryProfile.COLOR_MAKEUP,
        product_id=114,
    ),
    PilotBinding(
        category_profile=CategoryProfile.CLEANSER,
        product_id=69,
    ),
    PilotBinding(
        category_profile=CategoryProfile.CLEANSER,
        product_id=103,
    ),
    PilotBinding(
        category_profile=CategoryProfile.FRAGRANCE,
        product_id=120,
    ),
    PilotBinding(
        category_profile=CategoryProfile.FRAGRANCE,
        product_id=121,
    ),
)


class ApprovedCategoryFact(_StrictFrozenModel):
    fact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_id: int = Field(gt=0)
    category_profile: CategoryProfile
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: JsonValue
    source_class: SourceClass
    source_refs: tuple[str, ...] = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_status: Literal["approved_fact"] = "approved_fact"
    reviewer: str = Field(min_length=1)
    reviewed_at: datetime
    capability_limit: frozenset[Capability] | None = None

    @field_validator("category_profile", mode="before")
    @classmethod
    def parse_category_profile(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return CategoryProfile(value)
            except ValueError:
                return value
        return value

    @field_validator("source_class", mode="before")
    @classmethod
    def parse_source_class(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return SourceClass(value)
            except ValueError:
                return value
        return value

    @field_validator("source_refs", mode="before")
    @classmethod
    def freeze_source_refs(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("capability_limit", mode="before")
    @classmethod
    def freeze_capability_limit(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @field_serializer("capability_limit")
    def serialize_capability_limit(
        self,
        value: frozenset[Capability] | None,
    ) -> list[Capability] | None:
        return None if value is None else sorted(value)

    @model_validator(mode="after")
    def validate_review_metadata(self) -> Self:
        if self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        if self.reviewer != self.reviewer.strip():
            raise ValueError("reviewer must be trimmed")
        if any(
            not reference or reference != reference.strip()
            for reference in self.source_refs
        ):
            raise ValueError("source_refs must be non-empty and trimmed")
        if (
            self.capability_limit is not None
            and "evidence" not in self.capability_limit
        ):
            raise ValueError(
                "capability_limit must preserve evidence"
            )
        return self


class CategoryFactManifest(_StrictFrozenModel):
    asset_id: str = Field(
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$"
    )
    asset_version: str = Field(min_length=1)
    fact_count: int = Field(ge=0)
    facts_file: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.jsonl$"
    )
    facts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pilot_bindings: tuple[PilotBinding, ...]
    schema_version: Literal["approved-category-facts-v1"]

    @field_validator("pilot_bindings", mode="before")
    @classmethod
    def freeze_pilot_bindings(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_fixed_pilots(self) -> Self:
        if self.pilot_bindings != PILOT_BINDINGS:
            raise ValueError(
                "pilot_bindings must contain the fixed twelve pilots"
            )
        return self


@dataclass(frozen=True, slots=True)
class CategoryFactAssets:
    manifest: CategoryFactManifest
    facts: tuple[ApprovedCategoryFact, ...]

    @property
    def pilot_ids(self) -> frozenset[int]:
        return frozenset(
            binding.product_id
            for binding in self.manifest.pilot_bindings
        )

    def pilot_ids_for(
        self,
        profile: CategoryProfile,
    ) -> frozenset[int]:
        return frozenset(
            binding.product_id
            for binding in self.manifest.pilot_bindings
            if binding.category_profile is profile
        )


def load_category_fact_assets(
    *,
    manifest_path: str | Path,
    canonical_reader: CanonicalProductReader,
    field_registry: CategoryFieldRegistry,
    expected_manifest_sha256: str | None = None,
    facts_path: str | Path | None = None,
) -> CategoryFactAssets:
    manifest_file_path = Path(manifest_path)
    manifest = _read_manifest(
        manifest_file_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    fact_path = _resolve_facts_path(
        manifest_path=manifest_file_path,
        manifest=manifest,
        facts_path=facts_path,
    )

    fact_bytes = _read_bytes(fact_path, label="category fact asset")
    actual_fact_sha256 = hashlib.sha256(fact_bytes).hexdigest()
    if actual_fact_sha256 != manifest.facts_sha256:
        raise CategoryFactAssetIntegrityError(
            "category fact asset SHA-256 mismatch"
        )
    if manifest.asset_version != (
        f"{_SCHEMA_VERSION}:sha256:{actual_fact_sha256}"
    ):
        raise CategoryFactAssetIntegrityError(
            "category fact asset version is not content-addressed"
        )

    facts = _parse_facts(fact_bytes)
    if len(facts) != manifest.fact_count:
        raise CategoryFactAssetIntegrityError(
            "category fact count mismatch: "
            f"manifest={manifest.fact_count}, loaded={len(facts)}"
        )

    for binding in manifest.pilot_bindings:
        _validate_product_profile(
            product_id=binding.product_id,
            expected_profile=binding.category_profile,
            canonical_reader=canonical_reader,
        )
    for fact in facts:
        _validate_fact_contract(
            fact,
            canonical_reader=canonical_reader,
            field_registry=field_registry,
        )
    return CategoryFactAssets(manifest=manifest, facts=facts)


def _resolve_facts_path(
    *,
    manifest_path: Path,
    manifest: CategoryFactManifest,
    facts_path: str | Path | None,
) -> Path:
    manifest_directory = manifest_path.parent.resolve(strict=True)
    if facts_path is None:
        expected_name = (
            f"category_facts_v1.{manifest.facts_sha256}.jsonl"
        )
        if manifest.facts_file != expected_name:
            raise CategoryFactAssetIntegrityError(
                "category fact manifest facts_file is not content-addressed"
            )
        return manifest_directory / expected_name

    supplied_path = Path(facts_path)
    if manifest.facts_file != supplied_path.name:
        raise CategoryFactAssetIntegrityError(
            "category fact facts_file mismatch"
        )
    try:
        supplied_directory = supplied_path.parent.resolve(strict=True)
    except OSError as exc:
        raise CategoryFactAssetIntegrityError(
            "cannot resolve category fact asset directory"
        ) from exc
    if supplied_directory != manifest_directory:
        raise CategoryFactAssetIntegrityError(
            "category fact facts_file must be a sibling basename"
        )
    return supplied_path


def _read_manifest(
    path: Path,
    *,
    expected_manifest_sha256: str | None,
) -> CategoryFactManifest:
    if (
        expected_manifest_sha256 is not None
        and _SHA256_PATTERN.fullmatch(expected_manifest_sha256) is None
    ):
        raise CategoryFactAssetIntegrityError(
            "expected category fact manifest SHA-256 must be lowercase"
        )
    payload = _read_bytes(path, label="category fact manifest")
    try:
        raw_manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CategoryFactAssetIntegrityError(
            f"invalid category fact manifest: {path}"
        ) from exc
    if not isinstance(raw_manifest, dict):
        raise CategoryFactAssetIntegrityError(
            "invalid category fact manifest: expected object"
        )
    try:
        manifest = CategoryFactManifest.model_validate_json(payload)
    except ValidationError as exc:
        raise CategoryFactAssetIntegrityError(
            f"invalid category fact manifest: {path}"
        ) from exc

    unsigned = {
        key: value
        for key, value in raw_manifest.items()
        if key != "manifest_sha256"
    }
    actual_sha256 = hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()
    if actual_sha256 != manifest.manifest_sha256:
        raise CategoryFactAssetIntegrityError(
            "category fact manifest SHA-256 mismatch"
        )
    if (
        expected_manifest_sha256 is not None
        and manifest.manifest_sha256 != expected_manifest_sha256
    ):
        raise CategoryFactAssetIntegrityError(
            "category fact manifest lock mismatch"
        )
    return manifest


def _parse_facts(
    fact_bytes: bytes,
) -> tuple[ApprovedCategoryFact, ...]:
    if not fact_bytes:
        return ()
    try:
        text = fact_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CategoryFactAssetIntegrityError(
            "category fact JSONL is not valid UTF-8"
        ) from exc

    facts: list[ApprovedCategoryFact] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise CategoryFactAssetIntegrityError(
                f"blank category fact line {line_number}"
            )
        try:
            fact = ApprovedCategoryFact.model_validate_json(line)
        except ValidationError as exc:
            raise CategoryFactAssetIntegrityError(
                f"invalid category fact at line {line_number}"
            ) from exc
        if _fact_content_digest(fact) != fact.fact_id:
            raise CategoryFactAssetIntegrityError(
                f"category fact content address mismatch at line {line_number}"
            )
        facts.append(fact)

    fact_ids = [fact.fact_id for fact in facts]
    if fact_ids != sorted(fact_ids):
        raise CategoryFactAssetIntegrityError(
            "category facts must be sorted by fact_id"
        )

    unique_facts: dict[str, ApprovedCategoryFact] = {}
    for fact in facts:
        existing = unique_facts.get(fact.fact_id)
        if existing is not None and existing != fact:
            raise CategoryFactAssetIntegrityError(
                "conflicting stable fact identity in category facts"
            )
        unique_facts[fact.fact_id] = fact
    facts = sorted(unique_facts.values(), key=lambda fact: fact.fact_id)

    source_identities: set[
        tuple[int, CategoryProfile, str, SourceClass, str]
    ] = set()
    for fact in facts:
        identity = (
            fact.product_id,
            fact.category_profile,
            fact.field_key,
            fact.source_class,
            fact.source_sha256,
        )
        if identity in source_identities:
            raise CategoryFactAssetIntegrityError(
                "conflicting stable source identity in category facts"
            )
        source_identities.add(identity)
    return tuple(facts)


def _validate_fact_contract(
    fact: ApprovedCategoryFact,
    *,
    canonical_reader: CanonicalProductReader,
    field_registry: CategoryFieldRegistry,
) -> None:
    _validate_product_profile(
        product_id=fact.product_id,
        expected_profile=fact.category_profile,
        canonical_reader=canonical_reader,
    )
    definitions = {
        definition.key: definition
        for definition in field_registry.for_profile(
            fact.category_profile
        )
    }
    definition = definitions.get(fact.field_key)
    if definition is None:
        raise CategoryFactAssetIntegrityError(
            "category fact field is not applicable to profile: "
            f"{fact.category_profile.value}.{fact.field_key}"
        )
    if fact.source_class in {
        SourceClass.CANONICAL_CORE,
        SourceClass.UNKNOWN,
    }:
        raise CategoryFactAssetIntegrityError(
            "category fact source is forbidden in approved "
            "category fact sidecar"
        )
    if fact.source_class not in {
        policy.source_class
        for policy in definition.source_policies
    }:
        raise CategoryFactAssetIntegrityError(
            "category fact source is not authorized for field: "
            f"{fact.field_key}.{fact.source_class.value}"
        )
    if fact.capability_limit is not None:
        source_policy = next(
            policy
            for policy in definition.source_policies
            if policy.source_class is fact.source_class
        )
        if not fact.capability_limit <= source_policy.capabilities:
            raise CategoryFactAssetIntegrityError(
                "category fact capability_limit exceeds source policy"
            )
    if fact.source_refs != tuple(sorted(set(fact.source_refs))):
        raise CategoryFactAssetIntegrityError(
            "category fact source_refs must be sorted and unique"
        )
    _validate_value_type(
        value=fact.value,
        value_type=definition.value_type,
        field_key=fact.field_key,
    )
    _validate_content_safety(fact)


def _validate_value_type(
    *,
    value: JsonValue,
    value_type: str,
    field_key: str,
) -> None:
    valid = False
    if value_type == "string":
        valid = (
            isinstance(value, str)
            and bool(value)
            and value == value.strip()
        )
    elif value_type == "string_list":
        valid = (
            isinstance(value, list)
            and bool(value)
            and all(
                isinstance(item, str)
                and bool(item)
                and item == item.strip()
                for item in value
            )
        )
    elif value_type == "number":
        valid = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    elif value_type == "boolean":
        valid = isinstance(value, bool)
    if not valid:
        raise CategoryFactAssetIntegrityError(
            f"category fact value type mismatch for field {field_key}"
        )


def _validate_content_safety(fact: ApprovedCategoryFact) -> None:
    review_content = {
        "reviewer": fact.reviewer,
        "value": fact.value,
    }
    untrusted_values = [
        *_iter_strings(review_content),
        *(
            reference
            for reference in fact.source_refs
            if _CATEGORY_FACT_SOURCE_REF_PATTERN.fullmatch(
                reference
            )
            is None
        ),
    ]
    for value in untrusted_values:
        if _contains_html_markup(value):
            raise CategoryFactAssetIntegrityError(
                "raw HTML in approved category fact"
            )
        if any(
            pattern.search(value)
            for pattern in (
                _EMAIL_PATTERN,
                _MOBILE_PHONE_PATTERN,
                _LANDLINE_PHONE_PATTERN,
                _ID_CARD_PATTERN,
                _WECHAT_PATTERN,
                _QQ_PATTERN,
                _LABELED_ADDRESS_PATTERN,
                _STRUCTURED_ADDRESS_PATTERN,
            )
        ):
            raise CategoryFactAssetIntegrityError(
                "PII in approved category fact"
            )
    for value in _iter_strings(fact.model_dump(mode="json")):
        if _is_absolute_local_path(value):
            raise CategoryFactAssetIntegrityError(
                "absolute path in approved category fact"
            )


def _iter_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_strings(key)
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def _contains_html_markup(value: str) -> bool:
    detector = _HTMLMarkupDetector()
    try:
        detector.feed(value)
        detector.close()
    except Exception:
        return True
    return detector.found_markup


def _is_absolute_local_path(value: str) -> bool:
    candidate = value
    for _ in range(4):
        if _FILE_URI_PATTERN.search(candidate) is not None:
            return True
        without_http_urls = _HTTP_URL_PATTERN.sub("", candidate)
        if any(
            pattern.search(without_http_urls) is not None
            for pattern in (
                _UNIX_ABSOLUTE_PATH_PATTERN,
                _HOME_PATH_PATTERN,
                _WINDOWS_ABSOLUTE_PATH_PATTERN,
                _UNC_PATH_PATTERN,
            )
        ):
            return True
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    return False


def _validate_product_profile(
    *,
    product_id: int,
    expected_profile: CategoryProfile,
    canonical_reader: CanonicalProductReader,
) -> None:
    try:
        product = canonical_reader.get(product_id)
    except UnknownProductError as exc:
        raise CategoryFactAssetIntegrityError(
            f"unknown category fact product_id {product_id}"
        ) from exc
    category = product.fields.get("category")
    if (
        category is None
        or category.resolved_state != "known"
        or not isinstance(category.value, str)
    ):
        raise CategoryFactAssetIntegrityError(
            f"category fact product {product_id} requires known category"
        )
    try:
        actual_profile = category_profile_for(category.value)
    except KeyError as exc:
        raise CategoryFactAssetIntegrityError(
            f"category fact product {product_id} has unmapped category"
        ) from exc
    if actual_profile is not expected_profile:
        raise CategoryFactAssetIntegrityError(
            "category fact product/profile mismatch: "
            f"product={product_id}, expected={expected_profile.value}, "
            f"actual={actual_profile.value}"
        )


def _fact_content_digest(fact: ApprovedCategoryFact) -> str:
    unsigned = fact.model_dump(
        mode="json",
        exclude={"fact_id"},
        exclude_none=True,
    )
    return hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CategoryFactAssetIntegrityError(
            f"cannot inspect {label}: {path}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise CategoryFactAssetIntegrityError(
            f"{label} cannot be a symlink: {path}"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = -1
    try:
        file_descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise CategoryFactAssetIntegrityError(
                f"{label} must be a regular file: {path}"
            )
        with os.fdopen(file_descriptor, "rb") as source:
            file_descriptor = -1
            return source.read()
    except OSError as exc:
        raise CategoryFactAssetIntegrityError(
            f"cannot read {label}: {path}"
        ) from exc
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
