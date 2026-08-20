from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from pydantic import ValidationError

from app.guide.retrieval.review_contracts import (
    ApprovedReviewEvidence,
    ReviewSourceCatalog,
)


_MANIFEST_KEYS = {
    "approved_source_count",
    "audit_locator",
    "audited_at",
    "catalog_id",
    "catalog_version",
    "manifest_sha256",
    "product_bindings",
    "schema_version",
    "sources_file",
    "sources_sha256",
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TMALL_LOCATOR_PATTERN = re.compile(
    r"^urn:tmall:ssr-html:"
    r"item:(?P<item_id>[0-9]+):"
    r"sku:(?P<sku_id>[0-9]+):"
    r"feed:(?P<feed_id>[0-9]+):"
    r"sha256:(?P<html_sha256>[0-9a-f]{64}):"
    r"ordinal:(?P<page_ordinal>[0-9]{8})$"
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


class ApprovedReviewAssetIntegrityError(RuntimeError):
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


@dataclass(frozen=True, slots=True)
class _TmallProductBinding:
    product_id: int
    item_id: str
    sku_id: str
    html_sha256: str

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.item_id, self.sku_id, self.html_sha256)


@dataclass(frozen=True, slots=True)
class ApprovedReviewAssets:
    catalog: ReviewSourceCatalog
    evidence: tuple[ApprovedReviewEvidence, ...]


def load_approved_review_assets(
    *,
    manifest_path: str | Path,
    sources_path: str | Path,
    expected_manifest_sha256: str,
) -> ApprovedReviewAssets:
    manifest = _read_manifest(
        Path(manifest_path),
        expected_manifest_sha256=expected_manifest_sha256,
    )
    product_bindings = _parse_product_bindings(manifest)
    audit_locator = _validate_audit_locator(
        _require_string(manifest, "audit_locator")
    )
    audited_at = _parse_timestamp(
        _require_string(manifest, "audited_at")
    )
    expected_source_sha = _require_sha256(
        manifest,
        "sources_sha256",
    )
    configured_source_path = Path(sources_path)
    source_path = _resolve_sources_path(
        configured_source_path=configured_source_path,
        sources_file=_require_string(manifest, "sources_file"),
        sources_sha256=expected_source_sha,
    )
    source_bytes = _read_regular_source_asset(
        source_path,
        generation=(source_path != configured_source_path),
    )
    actual_source_sha = hashlib.sha256(source_bytes).hexdigest()
    if actual_source_sha != expected_source_sha:
        raise ApprovedReviewAssetIntegrityError(
            "approved review source asset SHA-256 mismatch"
        )

    catalog_version = _require_string(
        manifest,
        "catalog_version",
    )
    if actual_source_sha not in catalog_version:
        raise ApprovedReviewAssetIntegrityError(
            "approved review catalog version is not content-addressed"
        )

    evidence = _parse_evidence(
        source_bytes,
        product_bindings=product_bindings,
        audited_at=audited_at,
    )
    approved_source_count = _require_integer(
        manifest,
        "approved_source_count",
    )
    if len(evidence) != approved_source_count:
        raise ApprovedReviewAssetIntegrityError(
            "approved source count mismatch: "
            f"manifest={approved_source_count}, loaded={len(evidence)}"
        )

    catalog = ReviewSourceCatalog(
        catalog_id=_require_string(manifest, "catalog_id"),
        catalog_version=catalog_version,
        audit_locator=audit_locator,
        audited_at=audited_at,
        approved_source_count=approved_source_count,
    )
    return ApprovedReviewAssets(
        catalog=catalog,
        evidence=evidence,
    )


def _read_manifest(
    path: Path,
    *,
    expected_manifest_sha256: str,
) -> dict[str, object]:
    if _SHA256_PATTERN.fullmatch(expected_manifest_sha256) is None:
        raise ApprovedReviewAssetIntegrityError(
            "expected approved review manifest SHA-256 "
            "must be lowercase"
        )
    payload = _read_bytes(
        path,
        label="approved review manifest",
    )
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovedReviewAssetIntegrityError(
            f"invalid approved review manifest: {path}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ApprovedReviewAssetIntegrityError(
            "invalid approved review manifest: expected object"
        )
    if set(manifest) != _MANIFEST_KEYS:
        raise ApprovedReviewAssetIntegrityError(
            "invalid approved review manifest fields"
        )
    if (
        _require_string(manifest, "schema_version")
        != "approved-review-sources-v1"
    ):
        raise ApprovedReviewAssetIntegrityError(
            "unsupported approved review schema version"
        )

    expected_sha = _require_sha256(manifest, "manifest_sha256")
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    canonical_json = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    actual_sha = hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()
    if actual_sha != expected_sha:
        raise ApprovedReviewAssetIntegrityError(
            "approved review manifest SHA-256 mismatch"
        )
    if expected_sha != expected_manifest_sha256:
        raise ApprovedReviewAssetIntegrityError(
            "approved review manifest lock mismatch"
        )
    return manifest


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ApprovedReviewAssetIntegrityError(
            f"cannot read {label}: {path}"
        ) from exc


def _resolve_sources_path(
    *,
    configured_source_path: Path,
    sources_file: str,
    sources_sha256: str,
) -> Path:
    if (
        sources_file in {".", ".."}
        or "/" in sources_file
        or "\\" in sources_file
        or ":" in sources_file
        or Path(sources_file).name != sources_file
    ):
        raise ApprovedReviewAssetIntegrityError(
            "approved review sources_file must be a safe basename"
        )
    if sources_file == configured_source_path.name:
        return configured_source_path
    expected_generation_name = (
        f"{configured_source_path.stem}.{sources_sha256}"
        f"{configured_source_path.suffix}"
    )
    if sources_file != expected_generation_name:
        raise ApprovedReviewAssetIntegrityError(
            "approved review source generation filename "
            "does not match sources_sha256"
        )
    return configured_source_path.parent / sources_file


def _read_regular_source_asset(
    path: Path,
    *,
    generation: bool,
) -> bytes:
    label = (
        "approved review source asset generation"
        if generation
        else "approved review source asset"
    )
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ApprovedReviewAssetIntegrityError(
            f"cannot read {label}: {path}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ApprovedReviewAssetIntegrityError(
            f"{label} cannot be a symlink"
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise ApprovedReviewAssetIntegrityError(
            f"{label} must be a regular file"
        )
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ApprovedReviewAssetIntegrityError(
                f"{label} must be a regular file"
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            return source.read()
    except OSError as exc:
        raise ApprovedReviewAssetIntegrityError(
            f"cannot read {label}: {path}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _parse_evidence(
    source_bytes: bytes,
    *,
    product_bindings: dict[tuple[str, str, str], int],
    audited_at: datetime,
) -> tuple[ApprovedReviewEvidence, ...]:
    if not source_bytes:
        raise ApprovedReviewAssetIntegrityError(
            "approved review source asset is empty"
        )
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApprovedReviewAssetIntegrityError(
            "approved review source asset is not valid UTF-8"
        ) from exc

    by_source_id: dict[str, ApprovedReviewEvidence] = {}
    used_bindings: set[tuple[str, str, str]] = set()
    for line_number, line in enumerate(
        source_text.splitlines(),
        start=1,
    ):
        if not line.strip():
            raise ApprovedReviewAssetIntegrityError(
                f"blank approved review source line {line_number}"
            )
        try:
            item = ApprovedReviewEvidence.model_validate_json(line)
        except ValidationError as exc:
            raise ApprovedReviewAssetIntegrityError(
                "invalid approved review source at line "
                f"{line_number}"
            ) from exc
        if item.collected_at > audited_at:
            raise ApprovedReviewAssetIntegrityError(
                "approved review collected_at must not be after "
                f"audited_at at line {line_number}"
            )
        used_bindings.add(
            _validate_tmall_provenance(
                item,
                product_bindings=product_bindings,
                line_number=line_number,
            )
        )
        _validate_content_safety(item, line_number=line_number)

        existing = by_source_id.get(item.source_id)
        if existing is None:
            by_source_id[item.source_id] = item
        elif existing != item:
            raise ApprovedReviewAssetIntegrityError(
                f"conflicting approved review source {item.source_id}"
            )

    if used_bindings != set(product_bindings):
        raise ApprovedReviewAssetIntegrityError(
            "approved review manifest contains unused product bindings"
        )
    return tuple(
        by_source_id[source_id]
        for source_id in sorted(by_source_id)
    )


def _validate_tmall_provenance(
    item: ApprovedReviewEvidence,
    *,
    product_bindings: dict[tuple[str, str, str], int],
    line_number: int,
) -> tuple[str, str, str]:
    match = _TMALL_LOCATOR_PATTERN.fullmatch(item.source_locator)
    if match is None:
        raise ApprovedReviewAssetIntegrityError(
            "invalid Tmall review source locator at line "
            f"{line_number}"
        )
    page_ordinal = match.group("page_ordinal")
    if int(page_ordinal) < 1:
        raise ApprovedReviewAssetIntegrityError(
            f"invalid Tmall review page ordinal at line {line_number}"
        )
    html_sha256 = match.group("html_sha256")
    expected_source_id = (
        f"review_tmall_item_{match.group('item_id')}_"
        f"html_{html_sha256}_ordinal_{page_ordinal}"
    )
    if item.source_id != expected_source_id:
        raise ApprovedReviewAssetIntegrityError(
            "stable Tmall review source ID mismatch at line "
            f"{line_number}"
        )
    if item.collection_version != (
        f"tmall-ssr-html-sha256:{html_sha256}"
    ):
        raise ApprovedReviewAssetIntegrityError(
            "Tmall collection version/hash mismatch at line "
            f"{line_number}"
        )
    identity = (
        match.group("item_id"),
        match.group("sku_id"),
        html_sha256,
    )
    if product_bindings.get(identity) != item.product_id:
        raise ApprovedReviewAssetIntegrityError(
            f"Tmall product binding mismatch at line {line_number}"
        )
    return identity


def _validate_content_safety(
    item: ApprovedReviewEvidence,
    *,
    line_number: int,
) -> None:
    if _contains_html_markup(item.content):
        raise ApprovedReviewAssetIntegrityError(
            f"raw HTML in approved review source at line {line_number}"
        )
    if any(
        pattern.search(item.content)
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
        raise ApprovedReviewAssetIntegrityError(
            f"PII in approved review source at line {line_number}"
        )


def _contains_html_markup(content: str) -> bool:
    detector = _HTMLMarkupDetector()
    try:
        detector.feed(content)
        detector.close()
    except Exception:
        return True
    return detector.found_markup


def _parse_product_bindings(
    manifest: dict[str, object],
) -> dict[tuple[str, str, str], int]:
    raw_bindings = manifest.get("product_bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        raise ApprovedReviewAssetIntegrityError(
            "approved review product_bindings must be a non-empty list"
        )

    bindings: list[_TmallProductBinding] = []
    expected_fields = {
        "product_id",
        "item_id",
        "sku_id",
        "html_sha256",
    }
    for index, raw_binding in enumerate(raw_bindings, start=1):
        if (
            not isinstance(raw_binding, dict)
            or set(raw_binding) != expected_fields
        ):
            raise ApprovedReviewAssetIntegrityError(
                f"invalid approved review product binding {index}"
            )
        product_id = raw_binding.get("product_id")
        if (
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id <= 0
        ):
            raise ApprovedReviewAssetIntegrityError(
                f"invalid approved review product binding {index}"
            )
        item_id = raw_binding.get("item_id")
        sku_id = raw_binding.get("sku_id")
        html_sha256 = raw_binding.get("html_sha256")
        if (
            not isinstance(item_id, str)
            or not item_id.isdigit()
            or not isinstance(sku_id, str)
            or not sku_id.isdigit()
            or not isinstance(html_sha256, str)
            or _SHA256_PATTERN.fullmatch(html_sha256) is None
        ):
            raise ApprovedReviewAssetIntegrityError(
                f"invalid approved review product binding {index}"
            )
        bindings.append(
            _TmallProductBinding(
                product_id=product_id,
                item_id=item_id,
                sku_id=sku_id,
                html_sha256=html_sha256,
            )
        )

    if bindings != sorted(
        bindings,
        key=lambda item: (
            item.product_id,
            item.item_id,
            item.sku_id,
            item.html_sha256,
        ),
    ):
        raise ApprovedReviewAssetIntegrityError(
            "approved review product bindings must be sorted"
        )

    by_identity: dict[tuple[str, str, str], int] = {}
    component_owners: dict[tuple[str, str], int] = {}
    for binding in bindings:
        if binding.identity in by_identity:
            raise ApprovedReviewAssetIntegrityError(
                "duplicate approved review product binding"
            )
        by_identity[binding.identity] = binding.product_id
        for kind, value in (
            ("item_id", binding.item_id),
            ("sku_id", binding.sku_id),
            ("html_sha256", binding.html_sha256),
        ):
            owner_key = (kind, value)
            existing_owner = component_owners.get(owner_key)
            if (
                existing_owner is not None
                and existing_owner != binding.product_id
            ):
                raise ApprovedReviewAssetIntegrityError(
                    "conflicting approved review product binding"
                )
            component_owners[owner_key] = binding.product_id
    return by_identity


def _validate_audit_locator(value: str) -> str:
    segments = value.split("/")
    if (
        "\\" in value
        or value.startswith("/")
        or len(segments) < 2
        or segments[0] != "docs"
        or any(segment in {"", ".", ".."} for segment in segments)
        or any(":" in segment for segment in segments)
    ):
        raise ApprovedReviewAssetIntegrityError(
            "approved review audit_locator must be a "
            "repository-relative docs path"
        )
    return value


def _parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApprovedReviewAssetIntegrityError(
            "invalid approved review audit timestamp"
        ) from exc
    if timestamp.utcoffset() is None:
        raise ApprovedReviewAssetIntegrityError(
            "approved review audit timestamp must be timezone-aware"
        )
    return timestamp


def _require_string(
    payload: dict[str, object],
    key: str,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ApprovedReviewAssetIntegrityError(
            f"approved review manifest field {key} "
            "must be a non-empty string"
        )
    return value


def _require_sha256(
    payload: dict[str, object],
    key: str,
) -> str:
    value = _require_string(payload, key)
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ApprovedReviewAssetIntegrityError(
            f"approved review manifest field {key} "
            "must be a lowercase SHA-256"
        )
    return value


def _require_integer(
    payload: dict[str, object],
    key: str,
) -> int:
    value = payload.get(key)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ApprovedReviewAssetIntegrityError(
            f"approved review manifest field {key} "
            "must be a non-negative integer"
        )
    return value
