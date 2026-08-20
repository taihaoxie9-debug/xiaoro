"""Build deterministic pending and quarantined review candidates.

This tool never creates approved review evidence. Historical 336/111 counts
remain provenance unless all locked source files and the expected counts are
reproduced.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping, Sequence

from tools.guide_data._safe_source_io import (
    SafeSourceIOError,
    read_relative_regular_bytes,
)


PENDING_FILE = "review_candidates_pending_v1.jsonl"
QUARANTINE_FILE = "review_candidates_quarantine_v1.jsonl"
MANIFEST_FILE = "review_candidates_manifest_v1.json"
HISTORICAL_COUNTS = {
    "total_candidates": 336,
    "strict_candidates": 111,
    "status": "not_rerun",
}

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
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
_MARKETING_PATTERN = re.compile(
    r"(?:官方旗舰店|限时(?:满减|优惠)|立即购买|买一送一|"
    r"直播间|优惠券|到手价|会员专享|赠同款|再送)"
)
_QA_PATTERN = re.compile(
    r"(?:^|\s)(?:问|Q)\s*[:：]|"
    r"(?:^|\s)(?:答|A)\s*[:：]|"
    r"问大家|全部问答|客服(?:回复|回答|建议)",
    re.IGNORECASE,
)

_HISTORICAL_SOURCE_LOCKS = {
    (
        42,
        "998532090974",
        "6153782938028",
        "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4",
    ),
    (
        49,
        "525332729369",
        "5214914101911",
        "55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44",
    ),
    (
        55,
        "746513552108",
        "5318505666088",
        "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783",
    ),
}


class ReviewCandidateBuildError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReviewCandidateBuildResult:
    pending: Path
    quarantine: Path
    manifest: Path
    extracted_count: int
    deduplicated_count: int
    pending_count: int
    quarantine_count: int
    provenance_status: str
    historical_counts: dict[str, int | str]


@dataclass(frozen=True, slots=True)
class _Source:
    path: Path
    display_path: str
    content: bytes
    source_sha256: str
    product_id: int
    item_id: str
    sku_id: str
    collected_at: str


@dataclass(frozen=True, slots=True)
class _Extracted:
    attributes: dict[str, str]
    content: str
    page_ordinal: int


class _ReviewHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[_Extracted] = []
        self._attributes: dict[str, str] | None = None
        self._content: list[str] = []
        self._depth = 0
        self._content_depth: int | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {
            key: "" if value is None else value
            for key, value in attrs
        }
        if (
            self._attributes is None
            and "data-review-candidate" in attributes
        ):
            self._attributes = attributes
            self._content = []
            self._depth = 1
            self._content_depth = None
            return
        if self._attributes is None:
            return
        self._depth += 1
        if "data-review-content" in attributes:
            self._content_depth = self._depth

    def handle_endtag(self, tag: str) -> None:
        if self._attributes is None:
            return
        if self._content_depth == self._depth:
            self._content_depth = None
        self._depth -= 1
        if self._depth != 0:
            return
        self.records.append(
            _Extracted(
                attributes=self._attributes,
                content=_normalize_text(" ".join(self._content)),
                page_ordinal=len(self.records) + 1,
            )
        )
        self._attributes = None
        self._content = []
        self._content_depth = None

    def handle_data(self, data: str) -> None:
        if self._attributes is not None and self._content_depth is not None:
            self._content.append(data)

    def close(self) -> None:
        super().close()
        if self._attributes is not None:
            raise ReviewCandidateBuildError(
                "unterminated review candidate element"
            )


def build_review_candidates(
    *,
    source_manifest_path: str | Path,
    output_root: str | Path,
) -> ReviewCandidateBuildResult:
    sources = _load_sources(Path(source_manifest_path))
    extracted_count = 0
    deduplicated_count = 0
    candidates: list[dict[str, object]] = []
    source_summaries: list[dict[str, object]] = []
    binding_conflict_product_ids = _source_binding_conflict_products(
        sources
    )

    for source in sources:
        html_bytes = source.content
        html_sha256 = source.source_sha256
        records = _parse_html(html_bytes)
        extracted_count += len(records)
        seen_content: set[tuple[int, str, str, str]] = set()
        for record in records:
            raw_content_sha256 = hashlib.sha256(
                record.content.encode("utf-8")
            ).hexdigest()
            actual_item_id = record.attributes.get(
                "data-item-id",
                source.item_id,
            )
            actual_sku_id = record.attributes.get(
                "data-sku-id",
                source.sku_id,
            )
            duplicate_key = (
                source.product_id,
                actual_item_id,
                actual_sku_id,
                raw_content_sha256,
            )
            if duplicate_key in seen_content:
                deduplicated_count += 1
                continue
            seen_content.add(duplicate_key)
            candidate = _candidate(
                source=source,
                record=record,
                html_sha256=html_sha256,
                raw_content_sha256=raw_content_sha256,
                actual_item_id=actual_item_id,
                actual_sku_id=actual_sku_id,
            )
            candidates.append(candidate)
            if "cross_sku" in candidate["quarantine_reasons"]:
                binding_conflict_product_ids.add(source.product_id)
        source_summaries.append(
            {
                "html_sha256": html_sha256,
                "item_id": source.item_id,
                "path": source.display_path,
                "product_id": source.product_id,
                "review_elements": len(records),
                "sku_id": source.sku_id,
            }
        )

    for candidate in candidates:
        if candidate["product_id"] in binding_conflict_product_ids:
            candidate["whole_product_binding_conflict"] = True
            reasons = review_candidate_quarantine_reasons(candidate)
            candidate["quarantine_reasons"] = list(reasons)
            candidate["status"] = "quarantine"
        if candidate["status"] == "quarantine":
            marker = _quarantine_content_marker(
                candidate["quarantine_reasons"]
            )
            candidate["content"] = marker
            candidate["content_kind"] = "quarantine_marker"
            candidate["content_sha256"] = hashlib.sha256(
                marker.encode("utf-8")
            ).hexdigest()
            candidate.pop("body", None)

    pending = sorted(
        (
            item
            for item in candidates
            if item["status"] == "pending"
        ),
        key=lambda item: str(item["candidate_id"]),
    )
    quarantine = sorted(
        (
            item
            for item in candidates
            if item["status"] == "quarantine"
        ),
        key=lambda item: str(item["candidate_id"]),
    )
    provenance_status, historical_counts = _provenance(
        source_summaries=source_summaries,
        extracted_count=extracted_count,
        pending_count=len(pending),
    )

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    pending_path = root / PENDING_FILE
    quarantine_path = root / QUARANTINE_FILE
    manifest_path = root / MANIFEST_FILE
    pending_bytes = _jsonl_bytes(pending)
    quarantine_bytes = _jsonl_bytes(quarantine)
    manifest = {
        "fixture_counts": {
            "deduplicated_candidates": deduplicated_count,
            "extracted_candidates": extracted_count,
            "pending_candidates": len(pending),
            "quarantine_candidates": len(quarantine),
        },
        "historical_counts": historical_counts,
        "pending_file": pending_path.name,
        "pending_sha256": hashlib.sha256(pending_bytes).hexdigest(),
        "provenance_status": provenance_status,
        "quarantine_file": quarantine_path.name,
        "quarantine_sha256": hashlib.sha256(
            quarantine_bytes
        ).hexdigest(),
        "schema_version": "review-candidate-build-v1",
        "sources": sorted(
            source_summaries,
            key=lambda item: (
                int(item["product_id"]),
                str(item["item_id"]),
                str(item["sku_id"]),
                str(item["html_sha256"]),
            ),
        ),
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        _canonical_json(manifest).encode("utf-8")
    ).hexdigest()
    manifest_bytes = (
        _canonical_json(manifest) + "\n"
    ).encode("utf-8")
    _write_atomic(pending_path, pending_bytes)
    _write_atomic(quarantine_path, quarantine_bytes)
    _write_atomic(manifest_path, manifest_bytes)
    return ReviewCandidateBuildResult(
        pending=pending_path,
        quarantine=quarantine_path,
        manifest=manifest_path,
        extracted_count=extracted_count,
        deduplicated_count=deduplicated_count,
        pending_count=len(pending),
        quarantine_count=len(quarantine),
        provenance_status=provenance_status,
        historical_counts=historical_counts,
    )


def _source_binding_conflict_products(
    sources: Sequence[_Source],
) -> set[int]:
    bindings_by_product: dict[int, set[tuple[str, str]]] = {}
    products_by_item: dict[str, set[int]] = {}
    products_by_sku: dict[str, set[int]] = {}
    for source in sources:
        bindings_by_product.setdefault(
            source.product_id,
            set(),
        ).add((source.item_id, source.sku_id))
        products_by_item.setdefault(
            source.item_id,
            set(),
        ).add(source.product_id)
        products_by_sku.setdefault(
            source.sku_id,
            set(),
        ).add(source.product_id)
    conflicts = {
        product_id
        for product_id, bindings in bindings_by_product.items()
        if len(bindings) > 1
    }
    for owners in (
        *products_by_item.values(),
        *products_by_sku.values(),
    ):
        if len(owners) > 1:
            conflicts.update(owners)
    return conflicts


def _quarantine_content_marker(reasons: object) -> str:
    if not isinstance(reasons, list):
        raise ReviewCandidateBuildError(
            "quarantine reasons must be a list"
        )
    markers: list[str] = []
    if "pii" in reasons:
        markers.append("[REDACTED_PII]")
    if "marketing" in reasons:
        markers.append("官方旗舰店")
    if "qa" in reasons:
        markers.append("问大家")
    if markers:
        return " ".join(markers)
    if "empty_content" in reasons:
        return ""
    return "[QUARANTINED]"


def _candidate(
    *,
    source: _Source,
    record: _Extracted,
    html_sha256: str,
    raw_content_sha256: str,
    actual_item_id: str,
    actual_sku_id: str,
) -> dict[str, object]:
    ordinal = f"{record.page_ordinal:08d}"
    candidate_id = (
        f"review_tmall_item_{source.item_id}_"
        f"html_{html_sha256}_ordinal_{ordinal}"
    )
    feed_id = record.attributes.get("data-feed-id", "0")
    content = record.content
    if any(pattern.search(content) for pattern in _PII_PATTERNS):
        for pattern in _PII_PATTERNS:
            content = pattern.sub("[REDACTED_PII]", content)
    content_sha256 = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()
    candidate = {
        "bound_item_id": source.item_id,
        "bound_sku_id": source.sku_id,
        "candidate_id": candidate_id,
        "collected_at": source.collected_at,
        "collection_version": (
            f"tmall-ssr-html-sha256:{html_sha256}"
        ),
        "content": content,
        "content_kind": "verbatim",
        "content_sha256": content_sha256,
        "feed_id": feed_id,
        "html_sha256": html_sha256,
        "item_id": actual_item_id,
        "page_ordinal": ordinal,
        "product_id": source.product_id,
        "raw_content_sha256": raw_content_sha256,
        "sku_id": actual_sku_id,
        "source_locator": (
            f"urn:tmall:ssr-html:item:{actual_item_id}:"
            f"sku:{actual_sku_id}:feed:{feed_id}:"
            f"sha256:{html_sha256}:ordinal:{ordinal}"
        ),
    }
    reasons = review_candidate_quarantine_reasons(candidate)
    candidate["quarantine_reasons"] = list(reasons)
    candidate["status"] = "quarantine" if reasons else "pending"
    return candidate


def review_candidate_quarantine_reasons(
    candidate: Mapping[str, object],
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if (
        candidate.get("item_id") != candidate.get("bound_item_id")
        or candidate.get("sku_id") != candidate.get("bound_sku_id")
    ):
        reasons.add("cross_sku")
    if candidate.get("whole_product_binding_conflict") is True:
        reasons.add("whole_product_binding_conflict")

    feed_id = candidate.get("feed_id")
    if (
        not isinstance(feed_id, str)
        or not feed_id.isdigit()
        or int(feed_id) < 1
    ):
        reasons.add("invalid_metadata")

    content = candidate.get("content")
    if isinstance(content, str):
        if _MARKETING_PATTERN.search(content):
            reasons.add("marketing")
        if _QA_PATTERN.search(content):
            reasons.add("qa")
        if (
            "[REDACTED_PII]" in content
            or any(pattern.search(content) for pattern in _PII_PATTERNS)
        ):
            reasons.add("pii")
        if not content:
            reasons.add("empty_content")
    return tuple(sorted(reasons))


def _load_sources(path: Path) -> tuple[_Source, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewCandidateBuildError(
            f"invalid source manifest: {path}"
        ) from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "sources"}
        or payload["schema_version"] != "review-candidate-sources-v1"
        or not isinstance(payload["sources"], list)
        or not payload["sources"]
    ):
        raise ReviewCandidateBuildError("invalid source manifest fields")

    sources: list[_Source] = []
    expected_fields = {
        "collected_at",
        "item_id",
        "path",
        "product_id",
        "sha256",
        "sku_id",
    }
    for raw in payload["sources"]:
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise ReviewCandidateBuildError("invalid source entry")
        product_id = raw["product_id"]
        item_id = raw["item_id"]
        sku_id = raw["sku_id"]
        relative_path = raw["path"]
        expected_sha256 = raw["sha256"]
        collected_at = raw["collected_at"]
        if (
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id < 1
            or not isinstance(item_id, str)
            or not item_id.isdigit()
            or not isinstance(sku_id, str)
            or not sku_id.isdigit()
            or not isinstance(relative_path, str)
            or not relative_path
            or not isinstance(expected_sha256, str)
            or _SHA256_PATTERN.fullmatch(expected_sha256) is None
            or not isinstance(collected_at, str)
        ):
            raise ReviewCandidateBuildError("invalid source entry")
        _timezone_aware(collected_at)
        source_path = Path(relative_path)
        if source_path.is_absolute() or ".." in source_path.parts:
            raise ReviewCandidateBuildError(
                "source path must be manifest-relative"
            )
        declared_path = path.parent / source_path
        try:
            source_bytes = read_relative_regular_bytes(
                path.parent,
                source_path,
            )
        except SafeSourceIOError as exc:
            raise ReviewCandidateBuildError(
                "source path must be a stable regular file"
            ) from exc
        actual_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ReviewCandidateBuildError(
                "source SHA-256 mismatch"
            )
        sources.append(
            _Source(
                path=declared_path,
                display_path=source_path.as_posix(),
                content=source_bytes,
                source_sha256=actual_sha256,
                product_id=product_id,
                item_id=item_id,
                sku_id=sku_id,
                collected_at=collected_at,
            )
        )
    identities = [
        (item.product_id, item.item_id, item.sku_id, item.path)
        for item in sources
    ]
    if len(identities) != len(set(identities)):
        raise ReviewCandidateBuildError("duplicate source entry")
    return tuple(
        sorted(
            sources,
            key=lambda item: (
                item.product_id,
                item.item_id,
                item.sku_id,
                item.display_path,
            ),
        )
    )


def _parse_html(payload: bytes) -> tuple[_Extracted, ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewCandidateBuildError(
            "review HTML must be UTF-8"
        ) from exc
    parser = _ReviewHTMLParser()
    try:
        parser.feed(text)
        parser.close()
    except ReviewCandidateBuildError:
        raise
    except Exception as exc:
        raise ReviewCandidateBuildError(
            "cannot parse review HTML"
        ) from exc
    return tuple(parser.records)


def _provenance(
    *,
    source_summaries: list[dict[str, object]],
    extracted_count: int,
    pending_count: int,
) -> tuple[str, dict[str, int | str]]:
    supplied = {
        (
            int(item["product_id"]),
            str(item["item_id"]),
            str(item["sku_id"]),
            str(item["html_sha256"]),
        )
        for item in source_summaries
    }
    if (
        supplied == _HISTORICAL_SOURCE_LOCKS
        and extracted_count == 336
        and pending_count == 111
    ):
        return (
            "historical_reproduced",
            {
                "total_candidates": 336,
                "strict_candidates": 111,
                "status": "rerun",
            },
        )
    historical_bindings = {
        (product_id, item_id, sku_id)
        for product_id, item_id, sku_id, _ in _HISTORICAL_SOURCE_LOCKS
    }
    if any(
        (
            int(item["product_id"]),
            str(item["item_id"]),
            str(item["sku_id"]),
        )
        in historical_bindings
        for item in source_summaries
    ):
        return "source_incomplete", dict(HISTORICAL_COUNTS)
    return "fixture_only", dict(HISTORICAL_COUNTS)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _timezone_aware(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewCandidateBuildError(
            "collected_at must be ISO-8601"
        ) from exc
    if parsed.utcoffset() is None:
        raise ReviewCandidateBuildError(
            "collected_at must be timezone-aware"
        )
    return parsed


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _jsonl_bytes(rows: Sequence[dict[str, object]]) -> bytes:
    return "".join(
        f"{_canonical_json(row)}\n"
        for row in rows
    ).encode("utf-8")


def _write_atomic(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic pending/quarantined review candidates; "
            "never approve extracted content."
        )
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = build_review_candidates(
        source_manifest_path=args.source_manifest,
        output_root=args.output_root,
    )
    print(
        _canonical_json(
            {
                "historical_counts": result.historical_counts,
                "manifest": str(result.manifest),
                "pending": str(result.pending),
                "pending_count": result.pending_count,
                "provenance_status": result.provenance_status,
                "quarantine": str(result.quarantine),
                "quarantine_count": result.quarantine_count,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
