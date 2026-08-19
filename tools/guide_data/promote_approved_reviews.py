"""Promote explicitly reviewed candidates into approved review assets.

Existing approved rows are grandfathered as immutable source records. This
tool does not invent reviewer metadata for them. Reviewer, review time,
decision, and reason are mandatory only for newly submitted decisions.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import errno
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import BinaryIO, Sequence

from app.guide.retrieval.approved_review_assets import (
    load_approved_review_assets,
)
from tools.guide_data.build_review_candidates import (
    review_candidate_quarantine_reasons,
)


GENERATION_ATOMICITY_NOTICE = (
    "Immutable sources and audit files are fully validated before the "
    "stable manifest pointer atomically commits the complete generation."
)
AUDIT_BLOCK_START = "<!-- current-approved-catalog:start -->"
AUDIT_BLOCK_END = "<!-- current-approved-catalog:end -->"
_DECISION_MANIFEST_SCHEMA_VERSION = (
    "approved-review-decision-manifest-v1"
)
_DECISION_SIGNATURE_SCHEMA_VERSION = (
    "approved-review-decision-signature-v1"
)
_ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DECISION_FIELDS = {
    "candidate_id",
    "decision",
    "reason",
    "reviewed_at",
    "reviewer",
}
_CANDIDATE_MANIFEST_FIELDS = {
    "fixture_counts",
    "historical_counts",
    "manifest_sha256",
    "pending_file",
    "pending_sha256",
    "provenance_status",
    "quarantine_file",
    "quarantine_sha256",
    "schema_version",
    "sources",
}
_CANDIDATE_SOURCE_FIELDS = {
    "html_sha256",
    "item_id",
    "path",
    "product_id",
    "review_elements",
    "sku_id",
}
_FIXTURE_COUNT_FIELDS = {
    "deduplicated_candidates",
    "extracted_candidates",
    "pending_candidates",
    "quarantine_candidates",
}
_QUARANTINE_REASONS = {
    "cross_sku",
    "empty_content",
    "invalid_metadata",
    "marketing",
    "pii",
    "qa",
    "whole_product_binding_conflict",
}
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


class ReviewPromotionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReviewPromotionResult:
    changed: bool
    approved_source_count: int
    manifest_sha256: str
    generation_atomic: bool = True
    atomicity_notice: str = GENERATION_ATOMICITY_NOTICE


@dataclass(frozen=True, slots=True)
class _Decision:
    candidate_id: str
    decision: str
    reviewer: str
    reviewed_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class _PublicationPaths:
    manifest: Path
    sources: Path
    audit: Path
    lock: Path


def promote_approved_reviews(
    *,
    pending_path: str | Path,
    quarantine_path: str | Path,
    candidate_manifest_path: str | Path,
    expected_candidate_manifest_sha256: str,
    decisions_path: str | Path,
    expected_decisions_sha256: str,
    manifest_path: str | Path,
    sources_path: str | Path,
    audit_path: str | Path,
    expected_manifest_sha256: str,
    lock_path: str | Path,
    decision_signature: str | None = None,
    decision_hmac_key: bytes | None = None,
) -> ReviewPromotionResult:
    decisions = _load_decisions(
        Path(decisions_path),
        expected_sha256=expected_decisions_sha256,
    )
    paths = _publication_paths(
        manifest_path=Path(manifest_path),
        sources_path=Path(sources_path),
        audit_path=Path(audit_path),
        lock_path=Path(lock_path),
    )

    with _publication_lock(paths.lock):
        _remove_unreferenced_staging_files(paths)
        pending, quarantined = _load_candidates(
            Path(pending_path),
            Path(quarantine_path),
            Path(candidate_manifest_path),
            expected_candidate_manifest_sha256=(
                expected_candidate_manifest_sha256
            ),
        )
        existing = load_approved_review_assets(
            manifest_path=paths.manifest,
            sources_path=paths.sources,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        existing_manifest = _read_json_object(paths.manifest)
        existing_manifest_bytes = _read_existing_target(
            paths.manifest,
            label="stable manifest",
        )
        active_sources_path = _active_sources_path(
            configured_path=paths.sources,
            manifest=existing_manifest,
        )
        active_audit_path = _active_audit_path(
            configured_path=paths.audit,
            manifest=existing_manifest,
        )
        existing_source_bytes = _read_existing_target(
            active_sources_path,
            label="active sources generation",
        )
        existing_rows = _read_jsonl_bytes(
            existing_source_bytes,
            name=active_sources_path.name,
        )
        existing_audit_bytes = _read_existing_target(
            active_audit_path,
            label="active audit generation",
        )
        try:
            existing_audit = existing_audit_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReviewPromotionError(
                "active audit generation is not valid UTF-8"
            ) from exc
        existing_audit_block = _extract_audit_block(existing_audit)
        _validate_existing_audit(
            block=existing_audit_block,
            manifest=existing_manifest,
            manifest_bytes=existing_manifest_bytes,
            source_rows=existing_rows,
            source_bytes=existing_source_bytes,
        )

        approved_candidates = _approved_candidates(
            decisions=decisions,
            pending=pending,
            quarantined=quarantined,
            existing_rows=existing_rows,
        )
        _verify_approved_decision_batch(
            approved=approved_candidates,
            decisions=decisions,
            candidate_manifest_raw_sha256=(
                expected_candidate_manifest_sha256
            ),
            decision_signature=decision_signature,
            decision_hmac_key=decision_hmac_key,
        )
        if not approved_candidates:
            return ReviewPromotionResult(
                changed=False,
                approved_source_count=(
                    existing.catalog.approved_source_count
                ),
                manifest_sha256=expected_manifest_sha256,
            )

        source_rows = _merged_source_rows(
            existing_rows=existing_rows,
            approved_candidates=approved_candidates,
        )
        sources_bytes = _jsonl_bytes(source_rows)
        sources_sha256 = hashlib.sha256(sources_bytes).hexdigest()
        sources_file = _generation_filename(
            configured_path=paths.sources,
            generation_sha256=sources_sha256,
        )
        audit_file = _generation_filename(
            configured_path=paths.audit,
            generation_sha256=_audit_generation_digest(
                previous=existing_audit_block,
                sources_sha256=sources_sha256,
                approved_candidates=approved_candidates,
            ),
        )
        audit_locator = _versioned_audit_locator(
            existing_locator=_non_empty_string(
                existing_manifest,
                "audit_locator",
            ),
            audit_file=audit_file,
        )
        manifest = _build_manifest(
            existing_manifest=existing_manifest,
            source_rows=source_rows,
            sources_bytes=sources_bytes,
            sources_file=sources_file,
            audit_locator=audit_locator,
            approved_candidates=approved_candidates,
        )
        manifest_bytes = (
            _canonical_json(manifest) + "\n"
        ).encode("utf-8")
        audit_block = _audit_payload(
            previous=existing_audit_block,
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            source_rows=source_rows,
            sources_bytes=sources_bytes,
            approved_candidates=approved_candidates,
        )
        audit_bytes = _replace_audit_block(
            existing_audit,
            audit_block,
        ).encode("utf-8")

        _publish_generation(
            paths=paths,
            sources_path=paths.sources.parent / sources_file,
            sources_bytes=sources_bytes,
            audit_path=paths.audit.parent / audit_file,
            audit_bytes=audit_bytes,
            manifest_bytes=manifest_bytes,
            expected_manifest_sha256=str(
                manifest["manifest_sha256"]
            ),
            expected_audit_block=audit_block,
            previous_manifest_bytes=existing_manifest_bytes,
        )
        return ReviewPromotionResult(
            changed=True,
            approved_source_count=len(source_rows),
            manifest_sha256=str(manifest["manifest_sha256"]),
        )


def _approved_candidates(
    *,
    decisions: tuple[_Decision, ...],
    pending: dict[str, dict[str, object]],
    quarantined: set[str],
    existing_rows: list[dict[str, object]],
) -> tuple[tuple[_Decision, dict[str, object]], ...]:
    existing_by_id = {
        str(row["source_id"]): row
        for row in existing_rows
    }
    approved: list[tuple[_Decision, dict[str, object]]] = []
    for decision in decisions:
        if decision.candidate_id in quarantined:
            raise ReviewPromotionError(
                f"quarantined candidate: {decision.candidate_id}"
            )
        candidate = pending.get(decision.candidate_id)
        if candidate is None:
            raise ReviewPromotionError(
                f"unknown candidate: {decision.candidate_id}"
            )
        if decision.decision == "rejected":
            continue
        _validate_pending_candidate(candidate)
        existing = existing_by_id.get(decision.candidate_id)
        if existing is not None:
            if existing != _candidate_source_row(candidate):
                raise ReviewPromotionError(
                    "existing approved candidate content conflict: "
                    f"{decision.candidate_id}"
                )
            continue
        approved.append((decision, candidate))
    return tuple(
        sorted(approved, key=lambda item: item[0].candidate_id)
    )


def _candidate_source_row(
    candidate: dict[str, object],
) -> dict[str, object]:
    return {
        "collection_version": candidate["collection_version"],
        "collected_at": candidate["collected_at"],
        "content": candidate["content"],
        "content_kind": candidate["content_kind"],
        "content_sha256": candidate["content_sha256"],
        "product_id": candidate["product_id"],
        "source_id": candidate["candidate_id"],
        "source_kind": "platform_consumer_review",
        "source_locator": candidate["source_locator"],
    }


def _merged_source_rows(
    *,
    existing_rows: list[dict[str, object]],
    approved_candidates: tuple[
        tuple[_Decision, dict[str, object]],
        ...,
    ],
) -> list[dict[str, object]]:
    by_source_id = {
        str(row["source_id"]): dict(row)
        for row in existing_rows
    }
    if len(by_source_id) != len(existing_rows):
        raise ReviewPromotionError(
            "existing approved sources contain duplicate IDs"
        )
    for _, candidate in approved_candidates:
        source_id = str(candidate["candidate_id"])
        row = _candidate_source_row(candidate)
        existing = by_source_id.get(source_id)
        if existing is not None and existing != row:
            raise ReviewPromotionError(
                f"conflicting approved source: {source_id}"
            )
        by_source_id[source_id] = row
    return [
        by_source_id[source_id]
        for source_id in sorted(by_source_id)
    ]


def _build_manifest(
    *,
    existing_manifest: dict[str, object],
    source_rows: list[dict[str, object]],
    sources_bytes: bytes,
    sources_file: str,
    audit_locator: str,
    approved_candidates: tuple[
        tuple[_Decision, dict[str, object]],
        ...,
    ],
) -> dict[str, object]:
    bindings = [
        dict(item)
        for item in existing_manifest["product_bindings"]
        if isinstance(item, dict)
    ]
    for _, candidate in approved_candidates:
        bindings.append(
            {
                "html_sha256": candidate["html_sha256"],
                "item_id": candidate["item_id"],
                "product_id": candidate["product_id"],
                "sku_id": candidate["sku_id"],
            }
        )
    unique_bindings = {
        (
            int(item["product_id"]),
            str(item["item_id"]),
            str(item["sku_id"]),
            str(item["html_sha256"]),
        ): item
        for item in bindings
    }
    if len(unique_bindings) != len(bindings):
        bindings = list(unique_bindings.values())
    bindings = sorted(
        bindings,
        key=lambda item: (
            int(item["product_id"]),
            str(item["item_id"]),
            str(item["sku_id"]),
            str(item["html_sha256"]),
        ),
    )

    reviewed_times = [
        decision.reviewed_at
        for decision, _ in approved_candidates
    ]
    existing_audited_at = _parse_time(
        str(existing_manifest["audited_at"]),
        field="audited_at",
    )
    audited_at = max([existing_audited_at, *reviewed_times])
    sources_sha256 = hashlib.sha256(sources_bytes).hexdigest()
    manifest = dict(existing_manifest)
    manifest.update(
        {
            "approved_source_count": len(source_rows),
            "audit_locator": audit_locator,
            "audited_at": _format_time(audited_at),
            "catalog_version": (
                "approved-tmall-feed-reviews-v1:"
                f"sha256:{sources_sha256}"
            ),
            "product_bindings": bindings,
            "sources_file": sources_file,
            "sources_sha256": sources_sha256,
        }
    )
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    return manifest


def _audit_payload(
    *,
    previous: dict[str, object],
    manifest: dict[str, object],
    manifest_bytes: bytes,
    source_rows: list[dict[str, object]],
    sources_bytes: bytes,
    approved_candidates: tuple[
        tuple[_Decision, dict[str, object]],
        ...,
    ] = (),
) -> dict[str, object]:
    counts = Counter(int(row["product_id"]) for row in source_rows)
    payload = {
        "approved_product_count": len(counts),
        "approved_product_counts": {
            str(product_id): count
            for product_id, count in sorted(counts.items())
        },
        "approved_source_count": len(source_rows),
        "audit_locator": manifest["audit_locator"],
        "catalog_id": manifest["catalog_id"],
        "catalog_version": manifest["catalog_version"],
        "manifest_file": previous["manifest_file"],
        "manifest_file_sha256": hashlib.sha256(
            manifest_bytes
        ).hexdigest(),
        "manifest_file_sha256_semantics": (
            "raw-file-bytes:includes-manifest_sha256:"
            "includes-trailing-newline"
        ),
        "manifest_sha256": manifest["manifest_sha256"],
        "manifest_sha256_semantics": (
            "canonical-json:exclude-manifest_sha256:utf-8:"
            "sorted-keys:compact:no-trailing-newline"
        ),
        "sources_file": _versioned_asset_locator(
            existing_locator=_non_empty_string(previous, "sources_file"),
            asset_file=_non_empty_string(manifest, "sources_file"),
        ),
        "sources_sha256": hashlib.sha256(sources_bytes).hexdigest(),
    }
    previous_decisions = previous.get("promotion_decisions", [])
    if not isinstance(previous_decisions, list) or not all(
        isinstance(item, dict) for item in previous_decisions
    ):
        raise ReviewPromotionError(
            "invalid promotion decision history in audit block"
        )
    promotion_decisions = [
        dict(item) for item in previous_decisions
    ]
    promotion_decisions.extend(
        {
            "decision": decision.decision,
            "reason": decision.reason,
            "reviewed_at": _format_time(decision.reviewed_at),
            "reviewer": decision.reviewer,
            "source_id": decision.candidate_id,
        }
        for decision, _ in approved_candidates
    )
    if promotion_decisions:
        by_source_id = {
            str(item.get("source_id")): item
            for item in promotion_decisions
        }
        if (
            len(by_source_id) != len(promotion_decisions)
            or "None" in by_source_id
        ):
            raise ReviewPromotionError(
                "duplicate or invalid promotion decision history"
            )
        payload["grandfathered_source_count"] = previous.get(
            "grandfathered_source_count",
            len(source_rows) - len(approved_candidates),
        )
        payload["promotion_decisions"] = [
            by_source_id[source_id]
            for source_id in sorted(by_source_id)
        ]
    return payload


def _validate_existing_audit(
    *,
    block: dict[str, object],
    manifest: dict[str, object],
    manifest_bytes: bytes,
    source_rows: list[dict[str, object]],
    source_bytes: bytes,
) -> None:
    expected = _audit_payload(
        previous=block,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        source_rows=source_rows,
        sources_bytes=source_bytes,
    )
    if block != expected:
        raise ReviewPromotionError(
            "existing audit machine block does not match assets"
        )


def _publish_generation(
    *,
    paths: _PublicationPaths,
    sources_path: Path,
    sources_bytes: bytes,
    audit_path: Path,
    audit_bytes: bytes,
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
    expected_audit_block: dict[str, object],
    previous_manifest_bytes: bytes,
) -> None:
    _install_immutable_generation(
        target=sources_path,
        content=sources_bytes,
        label="sources generation",
    )
    _install_immutable_generation(
        target=audit_path,
        content=audit_bytes,
        label="audit generation",
    )
    manifest_new = _write_temporary_file(
        parent=paths.manifest.parent,
        prefix=".review-manifest.",
        suffix=".new",
        content=manifest_bytes,
    )
    try:
        load_approved_review_assets(
            manifest_path=manifest_new,
            sources_path=paths.sources,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        if _extract_audit_block(
            audit_bytes.decode("utf-8")
        ) != expected_audit_block:
            raise ReviewPromotionError(
                "immutable audit generation validation failed"
            )
        if _read_existing_target(
            paths.manifest,
            label="stable manifest",
        ) != previous_manifest_bytes:
            raise ReviewPromotionError(
                "stable manifest changed during publication"
            )
        os.replace(manifest_new, paths.manifest)
        manifest_new = None
        _fsync_directory(paths.manifest.parent)
    finally:
        if manifest_new is not None:
            manifest_new.unlink(missing_ok=True)
            _fsync_directory(paths.manifest.parent)


def _install_immutable_generation(
    *,
    target: Path,
    content: bytes,
    label: str,
) -> None:
    staging = _write_temporary_file(
        parent=target.parent,
        prefix=".review-generation.",
        suffix=".staging",
        content=content,
    )
    try:
        try:
            os.link(staging, target, follow_symlinks=False)
        except FileExistsError:
            existing = _read_existing_target(target, label=label)
            if existing != content:
                raise ReviewPromotionError(
                    f"content-addressed {label} has different content"
                )
        else:
            _fsync_directory(target.parent)
    finally:
        staging.unlink(missing_ok=True)
        _fsync_directory(target.parent)

    if _read_existing_target(target, label=label) != content:
        raise ReviewPromotionError(
            f"content-addressed {label} verification failed"
        )


def _write_temporary_file(
    *,
    parent: Path,
    prefix: str,
    suffix: str,
    content: bytes,
) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=prefix,
        suffix=suffix,
        dir=parent,
    )
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(parent)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        _fsync_directory(parent)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _publication_lock(path: Path):
    class _Lock:
        def __init__(self, lock_path: Path) -> None:
            self.path = lock_path
            self.stream: BinaryIO | None = None

        def __enter__(self):
            descriptor = os.open(
                self.path,
                os.O_RDWR | os.O_CREAT,
                0o600,
            )
            os.fchmod(descriptor, 0o600)
            self.stream = os.fdopen(descriptor, "r+b")
            try:
                fcntl.flock(
                    self.stream.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except OSError as exc:
                self.stream.close()
                self.stream = None
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise ReviewPromotionError(
                        "publication lock is already held"
                    ) from exc
                raise
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            if self.stream is None:
                return
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None

    return _Lock(path)


def _publication_paths(
    *,
    manifest_path: Path,
    sources_path: Path,
    audit_path: Path,
    lock_path: Path,
) -> _PublicationPaths:
    targets = tuple(
        _configured_target(path)
        for path in (manifest_path, sources_path, audit_path)
    )
    if len(set(targets)) != 3:
        raise ReviewPromotionError(
            "publication targets must be distinct"
        )
    resolved_lock = lock_path.resolve()
    if not resolved_lock.parent.is_dir():
        raise ReviewPromotionError(
            "publication lock parent is missing"
        )
    return _PublicationPaths(
        manifest=targets[0],
        sources=targets[1],
        audit=targets[2],
        lock=resolved_lock,
    )


def _configured_target(path: Path) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReviewPromotionError(
            f"publication target cannot be inspected: {path.name}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ReviewPromotionError(
            f"publication target cannot be a symlink: {path.name}"
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise ReviewPromotionError(
            f"publication target must be a regular file: {path.name}"
        )
    return path.resolve(strict=True)


def _active_sources_path(
    *,
    configured_path: Path,
    manifest: dict[str, object],
) -> Path:
    sources_file = _non_empty_string(manifest, "sources_file")
    sources_sha256 = _non_empty_string(manifest, "sources_sha256")
    if (
        sources_file in {".", ".."}
        or "/" in sources_file
        or "\\" in sources_file
        or ":" in sources_file
    ):
        raise ReviewPromotionError("invalid active sources filename")
    if sources_file == configured_path.name:
        return configured_path
    if sources_file != _generation_filename(
        configured_path=configured_path,
        generation_sha256=sources_sha256,
    ):
        raise ReviewPromotionError(
            "active sources generation filename mismatch"
        )
    return configured_path.parent / sources_file


def _active_audit_path(
    *,
    configured_path: Path,
    manifest: dict[str, object],
) -> Path:
    audit_locator = _non_empty_string(manifest, "audit_locator")
    audit_file = Path(audit_locator).name
    if audit_file == configured_path.name:
        return configured_path
    expected_pattern = re.compile(
        rf"^{re.escape(configured_path.stem)}\.[0-9a-f]{{64}}"
        rf"{re.escape(configured_path.suffix)}$"
    )
    if expected_pattern.fullmatch(audit_file) is None:
        raise ReviewPromotionError(
            "active audit generation filename mismatch"
        )
    return configured_path.parent / audit_file


def _generation_filename(
    *,
    configured_path: Path,
    generation_sha256: str,
) -> str:
    if not _is_sha256(generation_sha256):
        raise ReviewPromotionError("invalid generation SHA-256")
    return (
        f"{configured_path.stem}.{generation_sha256}"
        f"{configured_path.suffix}"
    )


def _versioned_audit_locator(
    *,
    existing_locator: str,
    audit_file: str,
) -> str:
    return _versioned_asset_locator(
        existing_locator=existing_locator,
        asset_file=audit_file,
    )


def _versioned_asset_locator(
    *,
    existing_locator: str,
    asset_file: str,
) -> str:
    segments = existing_locator.split("/")
    if (
        len(segments) < 2
        or any(segment in {"", ".", ".."} for segment in segments)
        or "\\" in existing_locator
        or ":" in existing_locator
    ):
        raise ReviewPromotionError("invalid existing audit locator")
    return "/".join([*segments[:-1], asset_file])


def _audit_generation_digest(
    *,
    previous: dict[str, object],
    sources_sha256: str,
    approved_candidates: tuple[
        tuple[_Decision, dict[str, object]],
        ...,
    ],
) -> str:
    previous_decisions = previous.get("promotion_decisions", [])
    if not isinstance(previous_decisions, list) or not all(
        isinstance(item, dict) for item in previous_decisions
    ):
        raise ReviewPromotionError(
            "invalid promotion decision history in audit block"
        )
    decisions = [dict(item) for item in previous_decisions]
    decisions.extend(
        {
            "decision": decision.decision,
            "reason": decision.reason,
            "reviewed_at": _format_time(decision.reviewed_at),
            "reviewer": decision.reviewer,
            "source_id": decision.candidate_id,
        }
        for decision, _ in approved_candidates
    )
    decisions.sort(key=lambda item: str(item.get("source_id")))
    payload = {
        "promotion_decisions": decisions,
        "schema_version": "approved-review-audit-generation-v1",
        "sources_sha256": sources_sha256,
    }
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _read_existing_target(path: Path, *, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReviewPromotionError(f"{label} cannot be inspected") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ReviewPromotionError(f"{label} cannot be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise ReviewPromotionError(f"{label} must be a regular file")
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReviewPromotionError(
                f"{label} must be a regular file"
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            return source.read()
    except OSError as exc:
        raise ReviewPromotionError(f"{label} cannot be read") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _remove_unreferenced_staging_files(
    paths: _PublicationPaths,
) -> None:
    patterns = (
        re.compile(r"^\.review-generation\.[A-Za-z0-9_-]+\.staging$"),
        re.compile(r"^\.review-manifest\.[A-Za-z0-9_-]+\.new$"),
    )
    for parent in {
        paths.manifest.parent,
        paths.sources.parent,
        paths.audit.parent,
    }:
        removed = False
        for candidate in parent.iterdir():
            if not any(
                pattern.fullmatch(candidate.name)
                for pattern in patterns
            ):
                continue
            metadata = candidate.lstat()
            if not (
                stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
            ):
                raise ReviewPromotionError(
                    "promotion staging artifact must be a file"
                )
            candidate.unlink()
            removed = True
        if removed:
            _fsync_directory(parent)


def _load_candidates(
    pending_path: Path,
    quarantine_path: Path,
    candidate_manifest_path: Path,
    *,
    expected_candidate_manifest_sha256: str,
) -> tuple[dict[str, dict[str, object]], set[str]]:
    if (
        not isinstance(expected_candidate_manifest_sha256, str)
        or not _is_sha256(expected_candidate_manifest_sha256)
    ):
        raise ReviewPromotionError(
            "expected candidate manifest raw SHA-256 must be "
            "64 lowercase hex characters"
        )
    manifest_bytes = _read_bytes(
        candidate_manifest_path,
        label="candidate manifest",
    )
    if hashlib.sha256(manifest_bytes).hexdigest() != (
        expected_candidate_manifest_sha256
    ):
        raise ReviewPromotionError(
            "candidate manifest raw SHA-256 mismatch"
        )
    manifest = _read_json_object_bytes(
        manifest_bytes,
        name=candidate_manifest_path.name,
    )
    if (
        set(manifest) != _CANDIDATE_MANIFEST_FIELDS
        or manifest.get("schema_version")
        != "review-candidate-build-v1"
    ):
        raise ReviewPromotionError("invalid candidate manifest fields")
    manifest_sha256 = _non_empty_string(
        manifest,
        "manifest_sha256",
    )
    if (
        not _is_sha256(manifest_sha256)
        or _manifest_digest(manifest) != manifest_sha256
    ):
        raise ReviewPromotionError(
            "candidate manifest SHA-256 mismatch"
        )
    if (
        manifest.get("pending_file") != pending_path.name
        or manifest.get("quarantine_file") != quarantine_path.name
        or pending_path.resolve() == quarantine_path.resolve()
    ):
        raise ReviewPromotionError(
            "candidate manifest queue filename mismatch"
        )

    pending_bytes = _read_bytes(
        pending_path,
        label="candidate pending",
    )
    quarantine_bytes = _read_bytes(
        quarantine_path,
        label="candidate quarantine",
    )
    if hashlib.sha256(pending_bytes).hexdigest() != (
        manifest.get("pending_sha256")
    ):
        raise ReviewPromotionError(
            "candidate pending SHA-256 mismatch"
        )
    if hashlib.sha256(quarantine_bytes).hexdigest() != (
        manifest.get("quarantine_sha256")
    ):
        raise ReviewPromotionError(
            "candidate quarantine SHA-256 mismatch"
        )

    pending_rows = _read_jsonl_bytes(
        pending_bytes,
        name=pending_path.name,
    )
    quarantine_rows = _read_jsonl_bytes(
        quarantine_bytes,
        name=quarantine_path.name,
    )
    counts = _candidate_manifest_counts(manifest)
    if (
        counts["pending_candidates"] != len(pending_rows)
        or counts["quarantine_candidates"] != len(quarantine_rows)
        or (
            counts["extracted_candidates"]
            - counts["deduplicated_candidates"]
        )
        != len(pending_rows) + len(quarantine_rows)
    ):
        raise ReviewPromotionError(
            "candidate manifest count mismatch"
        )
    source_locks = _candidate_source_locks(
        manifest,
        expected_extracted_count=counts["extracted_candidates"],
    )
    if (
        manifest["provenance_status"] == "historical_reproduced"
        and (
            counts["extracted_candidates"] != 336
            or counts["pending_candidates"] != 111
            or source_locks != _HISTORICAL_SOURCE_LOCKS
        )
    ):
        raise ReviewPromotionError(
            "historical candidate provenance mismatch"
        )

    pending: dict[str, dict[str, object]] = {}
    quarantined: set[str] = set()
    pending_ids = [
        _non_empty_string(row, "candidate_id")
        for row in pending_rows
    ]
    quarantine_ids = [
        _non_empty_string(row, "candidate_id")
        for row in quarantine_rows
    ]
    if pending_ids != sorted(pending_ids):
        raise ReviewPromotionError(
            "pending candidates are not deterministically ordered"
        )
    if quarantine_ids != sorted(quarantine_ids):
        raise ReviewPromotionError(
            "quarantined candidates are not deterministically ordered"
        )
    for row in pending_rows:
        if row.get("status") != "pending":
            raise ReviewPromotionError(
                "pending asset contains a non-pending candidate"
            )
        candidate_id = _non_empty_string(row, "candidate_id")
        if candidate_id in pending:
            raise ReviewPromotionError("duplicate pending candidate")
        _validate_pending_candidate(row)
        _validate_candidate_source_lock(row, source_locks)
        pending[candidate_id] = row
    for row in quarantine_rows:
        if row.get("status") != "quarantine":
            raise ReviewPromotionError(
                "quarantine asset contains a non-quarantined candidate"
            )
        candidate_id = _non_empty_string(row, "candidate_id")
        if candidate_id in pending or candidate_id in quarantined:
            raise ReviewPromotionError(
                "candidate appears in multiple queues"
            )
        _validate_quarantined_candidate(row)
        _validate_candidate_source_lock(row, source_locks)
        quarantined.add(candidate_id)
    return pending, quarantined


def _candidate_manifest_counts(
    manifest: dict[str, object],
) -> dict[str, int]:
    counts = manifest.get("fixture_counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != _FIXTURE_COUNT_FIELDS
        or not all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for value in counts.values()
        )
    ):
        raise ReviewPromotionError(
            "invalid candidate manifest counts"
        )
    provenance_status = manifest.get("provenance_status")
    historical_counts = manifest.get("historical_counts")
    expected_historical = {
        "total_candidates": 336,
        "strict_candidates": 111,
        "status": (
            "rerun"
            if provenance_status == "historical_reproduced"
            else "not_rerun"
        ),
    }
    if (
        provenance_status
        not in {
            "fixture_only",
            "historical_reproduced",
            "source_incomplete",
        }
        or historical_counts != expected_historical
    ):
        raise ReviewPromotionError(
            "invalid candidate manifest provenance"
        )
    return {
        key: int(value)
        for key, value in counts.items()
    }


def _candidate_source_locks(
    manifest: dict[str, object],
    *,
    expected_extracted_count: int,
) -> set[tuple[int, str, str, str]]:
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ReviewPromotionError(
            "invalid candidate manifest sources"
        )
    locks: set[tuple[int, str, str, str]] = set()
    review_element_count = 0
    previous_sort_key: tuple[int, str, str, str] | None = None
    for source in sources:
        if (
            not isinstance(source, dict)
            or set(source) != _CANDIDATE_SOURCE_FIELDS
        ):
            raise ReviewPromotionError(
                "invalid candidate manifest source"
            )
        product_id = source.get("product_id")
        item_id = source.get("item_id")
        sku_id = source.get("sku_id")
        html_sha256 = source.get("html_sha256")
        path = source.get("path")
        review_elements = source.get("review_elements")
        if (
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id < 1
            or not isinstance(item_id, str)
            or not item_id.isdigit()
            or not isinstance(sku_id, str)
            or not sku_id.isdigit()
            or not isinstance(html_sha256, str)
            or not _is_sha256(html_sha256)
            or not isinstance(path, str)
            or not path
            or not isinstance(review_elements, int)
            or isinstance(review_elements, bool)
            or review_elements < 0
        ):
            raise ReviewPromotionError(
                "invalid candidate manifest source"
            )
        lock = (product_id, item_id, sku_id, html_sha256)
        if lock in locks:
            raise ReviewPromotionError(
                "duplicate candidate manifest source"
            )
        if previous_sort_key is not None and lock < previous_sort_key:
            raise ReviewPromotionError(
                "candidate manifest sources are not ordered"
            )
        previous_sort_key = lock
        locks.add(lock)
        review_element_count += review_elements
    if review_element_count != expected_extracted_count:
        raise ReviewPromotionError(
            "candidate source count mismatch"
        )
    return locks


def _validate_candidate_source_lock(
    candidate: dict[str, object],
    source_locks: set[tuple[int, str, str, str]],
) -> None:
    product_id = candidate.get("product_id")
    if (
        not isinstance(product_id, int)
        or isinstance(product_id, bool)
        or product_id < 1
    ):
        raise ReviewPromotionError(
            "candidate product_id must be a positive integer"
        )
    lock = (
        product_id,
        _non_empty_string(candidate, "bound_item_id"),
        _non_empty_string(candidate, "bound_sku_id"),
        _non_empty_string(candidate, "html_sha256"),
    )
    if lock not in source_locks:
        raise ReviewPromotionError(
            "candidate source is not locked by manifest"
        )


def _validate_quarantined_candidate(
    candidate: dict[str, object],
) -> None:
    reasons = candidate.get("quarantine_reasons")
    if (
        not isinstance(reasons, list)
        or not reasons
        or reasons != sorted(set(reasons))
        or not all(reason in _QUARANTINE_REASONS for reason in reasons)
    ):
        raise ReviewPromotionError(
            "invalid quarantined candidate classification"
        )
    _validate_candidate_integrity(candidate)
    expected_reasons = list(
        review_candidate_quarantine_reasons(candidate)
    )
    if reasons != expected_reasons:
        raise ReviewPromotionError(
            "invalid quarantined candidate classification"
        )


def _load_decisions(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[_Decision, ...]:
    if not isinstance(expected_sha256, str) or not _is_sha256(
        expected_sha256
    ):
        raise ReviewPromotionError(
            "expected decision queue SHA-256 must be "
            "64 lowercase hex characters"
        )
    decision_bytes = _read_bytes(path, label="decision queue")
    if hashlib.sha256(decision_bytes).hexdigest() != expected_sha256:
        raise ReviewPromotionError("decision queue SHA-256 mismatch")
    rows = _read_jsonl_bytes(
        decision_bytes,
        name=path.name,
        allow_empty=True,
    )
    decisions: list[_Decision] = []
    seen: set[str] = set()
    for row in rows:
        for field in _DECISION_FIELDS:
            if field not in row:
                raise ReviewPromotionError(
                    f"decision missing {field}"
                )
        if set(row) != _DECISION_FIELDS:
            raise ReviewPromotionError("invalid decision fields")
        candidate_id = _non_empty_string(row, "candidate_id")
        decision = _non_empty_string(row, "decision")
        reviewer = _non_empty_string(row, "reviewer")
        reason = _non_empty_string(row, "reason")
        reviewed_at_raw = _non_empty_string(row, "reviewed_at")
        if decision not in {"approved", "rejected"}:
            raise ReviewPromotionError(
                "decision must be approved or rejected"
            )
        if candidate_id in seen:
            raise ReviewPromotionError(
                f"duplicate decision: {candidate_id}"
            )
        seen.add(candidate_id)
        decisions.append(
            _Decision(
                candidate_id=candidate_id,
                decision=decision,
                reviewer=reviewer,
                reviewed_at=_parse_time(
                    reviewed_at_raw,
                    field="reviewed_at",
                ),
                reason=reason,
            )
        )
    return tuple(
        sorted(decisions, key=lambda item: item.candidate_id)
    )


def _verify_approved_decision_batch(
    *,
    approved: tuple[
        tuple[_Decision, dict[str, object]],
        ...,
    ],
    decisions: tuple[_Decision, ...],
    candidate_manifest_raw_sha256: str,
    decision_signature: str | None,
    decision_hmac_key: bytes | None,
) -> None:
    if not approved:
        return
    if decision_hmac_key is None:
        raise ReviewPromotionError(
            "decision HMAC key is required for non-empty approval"
        )
    if not isinstance(decision_hmac_key, bytes):
        raise TypeError("decision HMAC key must be bytes")
    if len(decision_hmac_key) < 32:
        raise ReviewPromotionError(
            "decision HMAC key must contain at least 32 bytes"
        )
    if decision_signature is None:
        raise ReviewPromotionError(
            "detached decision batch signature is required "
            "for non-empty approval"
        )
    if not _is_sha256(decision_signature):
        raise ReviewPromotionError(
            "decision batch signature must be lowercase hexadecimal"
        )
    expected_signature = _decision_batch_signature(
        decisions=decisions,
        candidate_manifest_raw_sha256=(
            candidate_manifest_raw_sha256
        ),
        decision_hmac_key=decision_hmac_key,
    )
    if not hmac.compare_digest(expected_signature, decision_signature):
        raise ReviewPromotionError("decision batch signature mismatch")


def _decision_batch_signature(
    *,
    decisions: tuple[_Decision, ...],
    candidate_manifest_raw_sha256: str,
    decision_hmac_key: bytes,
) -> str:
    decision_manifest = {
        "decision_count": len(decisions),
        "decisions": [
            {
                "candidate_id": decision.candidate_id,
                "decision": decision.decision,
                "reason": decision.reason,
                "reviewed_at": _format_time(decision.reviewed_at),
                "reviewer": decision.reviewer,
            }
            for decision in decisions
        ],
        "schema_version": _DECISION_MANIFEST_SCHEMA_VERSION,
    }
    signature_payload = {
        "candidate_manifest_raw_sha256": (
            candidate_manifest_raw_sha256
        ),
        "decision_manifest_sha256": hashlib.sha256(
            _canonical_json(decision_manifest).encode("utf-8")
        ).hexdigest(),
        "schema_version": _DECISION_SIGNATURE_SCHEMA_VERSION,
    }
    return hmac.new(
        decision_hmac_key,
        _canonical_json(signature_payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _validate_pending_candidate(candidate: dict[str, object]) -> None:
    if candidate.get("status") != "pending":
        raise ReviewPromotionError("candidate is not pending")
    if candidate.get("quarantine_reasons") != []:
        raise ReviewPromotionError(
            "pending candidate has quarantine reasons"
        )
    _non_empty_string(candidate, "content")
    _validate_candidate_integrity(candidate)
    reasons = review_candidate_quarantine_reasons(candidate)
    if reasons:
        raise ReviewPromotionError(
            "pending candidate fails quarantine classification: "
            + ",".join(reasons)
        )
    if "[REDACTED_PII]" in str(candidate.get("content", "")):
        raise ReviewPromotionError(
            "pending candidate contains redacted PII"
        )
    candidate_id = _non_empty_string(candidate, "candidate_id")
    item_id = _non_empty_string(candidate, "item_id")
    sku_id = _non_empty_string(candidate, "sku_id")
    bound_item_id = _non_empty_string(candidate, "bound_item_id")
    bound_sku_id = _non_empty_string(candidate, "bound_sku_id")
    html_sha256 = _non_empty_string(candidate, "html_sha256")
    ordinal = _non_empty_string(candidate, "page_ordinal")
    if item_id != bound_item_id or sku_id != bound_sku_id:
        raise ReviewPromotionError(
            "pending candidate product binding mismatch"
        )
    expected_id = (
        f"review_tmall_item_{item_id}_"
        f"html_{html_sha256}_ordinal_{ordinal}"
    )
    if candidate_id != expected_id:
        raise ReviewPromotionError(
            "pending candidate stable ID mismatch"
        )


def _validate_candidate_integrity(
    candidate: dict[str, object],
) -> None:
    candidate_id = _non_empty_string(candidate, "candidate_id")
    bound_item_id = _non_empty_string(candidate, "bound_item_id")
    _non_empty_string(candidate, "bound_sku_id")
    html_sha256 = _non_empty_string(candidate, "html_sha256")
    ordinal = _non_empty_string(candidate, "page_ordinal")
    content = candidate.get("content")
    if not isinstance(content, str):
        raise ReviewPromotionError(
            "content must be a string"
        )
    content_sha256 = _non_empty_string(candidate, "content_sha256")
    raw_content_sha256 = _non_empty_string(
        candidate,
        "raw_content_sha256",
    )
    if (
        not bound_item_id.isdigit()
        or not ordinal.isdigit()
        or len(ordinal) != 8
        or not _is_sha256(html_sha256)
        or not _is_sha256(content_sha256)
        or not _is_sha256(raw_content_sha256)
    ):
        raise ReviewPromotionError(
            "invalid candidate identity or SHA-256"
        )
    expected_id = (
        f"review_tmall_item_{bound_item_id}_"
        f"html_{html_sha256}_ordinal_{ordinal}"
    )
    if candidate_id != expected_id:
        raise ReviewPromotionError(
            "candidate stable ID mismatch"
        )
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != (
        content_sha256
    ):
        raise ReviewPromotionError(
            "candidate content hash mismatch"
        )
    _parse_time(
        _non_empty_string(candidate, "collected_at"),
        field="collected_at",
    )


def _extract_audit_block(text: str) -> dict[str, object]:
    if text.count(AUDIT_BLOCK_START) != 1 or text.count(
        AUDIT_BLOCK_END
    ) != 1:
        raise ReviewPromotionError(
            "audit document must contain one current catalog block"
        )
    block = text.split(AUDIT_BLOCK_START, 1)[1].split(
        AUDIT_BLOCK_END,
        1,
    )[0]
    if not block.startswith("\n```json\n") or not block.endswith(
        "```\n"
    ):
        raise ReviewPromotionError(
            "invalid audit machine block framing"
        )
    try:
        payload = json.loads(
            block.removeprefix("\n```json\n").removesuffix("```\n")
        )
    except json.JSONDecodeError as exc:
        raise ReviewPromotionError(
            "invalid audit machine block JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ReviewPromotionError(
            "audit machine block must be an object"
        )
    return payload


def _replace_audit_block(
    text: str,
    payload: dict[str, object],
) -> str:
    before, remainder = text.split(AUDIT_BLOCK_START, 1)
    _, after = remainder.split(AUDIT_BLOCK_END, 1)
    replacement = (
        f"{AUDIT_BLOCK_START}\n```json\n"
        f"{_canonical_json(payload)}\n```\n"
        f"{AUDIT_BLOCK_END}"
    )
    return f"{before}{replacement}{after}"


def _manifest_digest(manifest: dict[str, object]) -> str:
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    return hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ReviewPromotionError(
            f"invalid JSON object: {path.name}"
        ) from exc
    return _read_json_object_bytes(payload, name=path.name)


def _read_json_object_bytes(
    payload: bytes,
    *,
    name: str,
) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewPromotionError(
            f"invalid JSON object: {name}"
        ) from exc
    if not isinstance(value, dict):
        raise ReviewPromotionError(
            f"invalid JSON object: {name}"
        )
    return value


def _read_jsonl_bytes(
    payload: bytes,
    *,
    name: str,
    allow_empty: bool = False,
) -> list[dict[str, object]]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewPromotionError(
            f"cannot read JSONL: {name}"
        ) from exc
    if not text and allow_empty:
        return []
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise ReviewPromotionError(
                f"blank JSONL line {line_number}: {name}"
            )
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewPromotionError(
                f"invalid JSONL line {line_number}: {name}"
            ) from exc
        if not isinstance(row, dict):
            raise ReviewPromotionError(
                f"JSONL line {line_number} must be an object"
            )
        rows.append(row)
    if not rows and not allow_empty:
        raise ReviewPromotionError(f"empty JSONL: {name}")
    return rows


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ReviewPromotionError(
            f"cannot read {label}: {path.name}"
        ) from exc


def _non_empty_string(
    payload: dict[str, object],
    field: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ReviewPromotionError(
            f"{field} must be a non-empty string"
        )
    return value


def _parse_time(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewPromotionError(
            f"{field} must be ISO-8601"
        ) from exc
    if parsed.utcoffset() is None:
        raise ReviewPromotionError(
            f"{field} must be timezone-aware"
        )
    return parsed.astimezone(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


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


def _is_sha256(value: str) -> bool:
    return (
        len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _decision_key_from_environment(
    environment_name: str | None,
) -> bytes | None:
    if environment_name is None:
        return None
    if _ENVIRONMENT_NAME_PATTERN.fullmatch(environment_name) is None:
        raise ReviewPromotionError(
            "decision key environment variable name is invalid"
        )
    value = os.environ.get(environment_name)
    if not value:
        raise ReviewPromotionError(
            "decision HMAC key environment variable is missing or empty"
        )
    return value.encode("utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Promote explicitly approved review candidates. "
            + GENERATION_ATOMICITY_NOTICE
        )
    )
    parser.add_argument("--pending", type=Path, required=True)
    parser.add_argument("--quarantine", type=Path, required=True)
    parser.add_argument(
        "--candidate-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--expected-candidate-manifest-sha256",
        required=True,
    )
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--expected-decisions-sha256", required=True)
    parser.add_argument("--decision-signature")
    parser.add_argument(
        "--decision-key-env",
        help="name of the environment variable containing the HMAC key",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    parser.add_argument("--lock", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = promote_approved_reviews(
        pending_path=args.pending,
        quarantine_path=args.quarantine,
        candidate_manifest_path=args.candidate_manifest,
        expected_candidate_manifest_sha256=(
            args.expected_candidate_manifest_sha256
        ),
        decisions_path=args.decisions,
        expected_decisions_sha256=args.expected_decisions_sha256,
        manifest_path=args.manifest,
        sources_path=args.sources,
        audit_path=args.audit,
        expected_manifest_sha256=args.expected_manifest_sha256,
        lock_path=args.lock,
        decision_signature=args.decision_signature,
        decision_hmac_key=_decision_key_from_environment(
            args.decision_key_env
        ),
    )
    print(
        _canonical_json(
            {
                "approved_source_count": result.approved_source_count,
                "atomicity_notice": result.atomicity_notice,
                "changed": result.changed,
                "generation_atomic": result.generation_atomic,
                "manifest_sha256": result.manifest_sha256,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
