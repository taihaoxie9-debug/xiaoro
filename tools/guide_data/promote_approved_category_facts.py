"""Promote explicitly reviewed category fact candidates into approved assets."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Iterator, Literal, Sequence, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_fact_assets import (
    PILOT_BINDINGS,
    ApprovedCategoryFact,
    load_category_fact_assets,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)


_SCHEMA_VERSION = "approved-category-facts-v1"
_FACTS_PREFIX = "category_facts_v1"
_MANIFEST_NAME = "category_facts_v1_manifest.json"
_LOCK_NAME = ".category-fact-promotion.lock"
_DECISION_MANIFEST_SCHEMA_VERSION = "category-fact-decision-manifest-v1"
_DECISION_SIGNATURE_SCHEMA_VERSION = "category-fact-decision-signature-v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GENERATION_STAGING_PATTERN = re.compile(
    r"^\.category-fact-generation\.[A-Za-z0-9_-]+\.staging$"
)
_MANIFEST_STAGING_PATTERN = re.compile(
    r"^\.category-fact-manifest\.[A-Za-z0-9_-]+\.new$"
)
_PENDING_FIELDS = frozenset(
    {
        "candidate_id",
        "category_profile",
        "conflict_candidate_ids",
        "conflict_group_id",
        "extraction_method",
        "field_key",
        "has_conflict",
        "normalized_value",
        "product_id",
        "source_class",
        "source_locator",
        "source_sha256",
        "status",
        "value_sha256",
    }
)
_QUARANTINE_FIELDS = frozenset(
    {
        "candidate_id",
        "category_profile",
        "extraction_method",
        "field_key",
        "product_id",
        "quarantine_reasons",
        "source_class",
        "source_locator",
        "source_sha256",
        "status",
        "value_sha256",
    }
)


class CategoryFactPromotionError(RuntimeError):
    """Raised when a promotion transaction cannot be trusted or recovered."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _PendingCandidate(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    category_profile: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    conflict_candidate_ids: tuple[str, ...]
    conflict_group_id: str | None
    extraction_method: Literal["html", "ocr_json", "structured_json"]
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    has_conflict: bool
    normalized_value: JsonValue
    product_id: int = Field(gt=0)
    source_class: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_locator: str = Field(min_length=1, max_length=512)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pending"]
    value_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("conflict_candidate_ids", mode="before")
    @classmethod
    def freeze_conflict_candidate_ids(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_candidate_contract(self) -> "_PendingCandidate":
        if self.source_locator != self.source_locator.strip():
            raise ValueError("source_locator must be trimmed")
        if self.conflict_candidate_ids != tuple(
            sorted(set(self.conflict_candidate_ids))
        ):
            raise ValueError(
                "conflict_candidate_ids must be sorted and unique"
            )
        if self.candidate_id in self.conflict_candidate_ids:
            raise ValueError("candidate cannot conflict with itself")
        if self.has_conflict or (
            self.conflict_group_id is not None
            or self.conflict_candidate_ids
        ):
            raise ValueError(
                "pending candidate cannot contain conflicts"
            )
        if _candidate_content_digest(self) != self.candidate_id:
            raise ValueError("candidate content address mismatch")
        return self


class _QuarantineCandidate(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    category_profile: str = Field(min_length=1, max_length=128)
    extraction_method: Literal["html", "ocr_json", "structured_json"]
    field_key: str = Field(min_length=1, max_length=128)
    product_id: int | None
    quarantine_reasons: tuple[str, ...] = Field(min_length=1)
    source_class: str = Field(min_length=1, max_length=128)
    source_locator: str = Field(min_length=1, max_length=512)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["quarantine"]
    value_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("quarantine_reasons", mode="before")
    @classmethod
    def freeze_quarantine_reasons(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_quarantine_contract(self) -> "_QuarantineCandidate":
        if self.source_locator != self.source_locator.strip():
            raise ValueError("source_locator must be trimmed")
        if self.quarantine_reasons != tuple(
            sorted(set(self.quarantine_reasons))
        ):
            raise ValueError(
                "quarantine_reasons must be sorted and unique"
            )
        if any(
            not reason or reason != reason.strip()
            for reason in self.quarantine_reasons
        ):
            raise ValueError("quarantine reasons must be non-empty")
        if (
            self.product_id is not None
            and (
                isinstance(self.product_id, bool)
                or self.product_id <= 0
            )
        ):
            raise ValueError("quarantine product_id is invalid")
        return self


class _ReviewDecision(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approved_fact", "rejected"]
    reason: str = Field(min_length=1)
    reviewed_at: datetime
    reviewer: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_human_metadata(self) -> "_ReviewDecision":
        if self.reviewer != self.reviewer.strip():
            raise ValueError("reviewer must be trimmed")
        if self.reason != self.reason.strip():
            raise ValueError("reason must be trimmed")
        if not self.reviewer:
            raise ValueError("reviewer must be non-empty")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return self


@dataclass(frozen=True, slots=True)
class PromotionReport:
    fact_count: int
    facts_sha256: str
    manifest_sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "fact_count": self.fact_count,
            "facts_sha256": self.facts_sha256,
            "manifest_sha256": self.manifest_sha256,
        }


ModelT = TypeVar("ModelT", bound=BaseModel)


def promote_approved_category_facts(
    *,
    candidates_path: str | Path,
    quarantine_path: str | Path,
    decisions_path: str | Path,
    output_dir: str | Path,
    expected_candidates_sha256: str,
    expected_quarantine_sha256: str,
    expected_decisions_sha256: str,
    canonical_manifest_path: str | Path,
    canonical_products_path: str | Path,
    decision_signature: str | None = None,
    decision_hmac_key: bytes | None = None,
    asset_id: str = "guide-category-facts-v1",
) -> PromotionReport:
    """Build and transactionally publish facts from explicit human decisions."""

    output_root = _prepare_output_directory(Path(output_dir))
    manifest_path = output_root / _MANIFEST_NAME
    lock_path = output_root / _LOCK_NAME

    with _exclusive_publish_lock(lock_path):
        _remove_unreferenced_staging_files(output_root)
        candidates = _load_locked_jsonl(
            Path(candidates_path),
            expected_sha256=expected_candidates_sha256,
            model=_PendingCandidate,
            expected_fields=_PENDING_FIELDS,
            label="candidate",
        )
        quarantine = _load_locked_jsonl(
            Path(quarantine_path),
            expected_sha256=expected_quarantine_sha256,
            model=_QuarantineCandidate,
            expected_fields=_QUARANTINE_FIELDS,
            label="quarantine candidate",
        )
        decisions = _load_decisions(
            Path(decisions_path),
            expected_sha256=expected_decisions_sha256,
        )
        _validate_queue_identity(candidates, quarantine)
        approved = _select_approved_candidates(
            candidates=candidates,
            quarantine=quarantine,
            decisions=decisions,
        )
        _verify_approved_decision_batch(
            approved=approved,
            decisions=decisions,
            candidate_manifest_raw_sha256=expected_candidates_sha256,
            decision_signature=decision_signature,
            decision_hmac_key=decision_hmac_key,
        )
        facts_bytes = _build_facts_bytes(approved)
        facts_sha256 = _sha256(facts_bytes)
        facts_file = f"{_FACTS_PREFIX}.{facts_sha256}.jsonl"
        manifest_bytes, manifest_sha256 = _build_manifest_bytes(
            asset_id=asset_id,
            facts_file=facts_file,
            facts_sha256=facts_sha256,
            fact_count=len(approved),
        )
        _publish_validated_generation(
            output_root=output_root,
            facts_path=output_root / facts_file,
            manifest_path=manifest_path,
            facts_bytes=facts_bytes,
            manifest_bytes=manifest_bytes,
            manifest_sha256=manifest_sha256,
            canonical_manifest_path=Path(canonical_manifest_path),
            canonical_products_path=Path(canonical_products_path),
        )
    return PromotionReport(
        fact_count=len(approved),
        facts_sha256=facts_sha256,
        manifest_sha256=manifest_sha256,
    )


def _load_locked_jsonl(
    path: Path,
    *,
    expected_sha256: str,
    model: type[ModelT],
    expected_fields: frozenset[str],
    label: str,
) -> tuple[ModelT, ...]:
    _validate_expected_sha256(expected_sha256, label=label)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} queue cannot be read") from exc
    if _sha256(content) != expected_sha256:
        raise ValueError(f"{label} queue SHA-256 mismatch")
    rows = _parse_jsonl(
        content,
        model=model,
        expected_fields=expected_fields,
        label=label,
    )
    candidate_ids = [
        str(getattr(row, "candidate_id"))
        for row in rows
    ]
    if candidate_ids != sorted(candidate_ids):
        raise ValueError(f"{label} queue must be sorted by candidate_id")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError(f"{label} queue has duplicate candidate_id")
    return rows


def _load_decisions(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[_ReviewDecision, ...]:
    _validate_expected_sha256(expected_sha256, label="decision queue")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ValueError("decision queue cannot be read") from exc
    if _sha256(content) != expected_sha256:
        raise ValueError("decision queue SHA-256 mismatch")
    decisions = _parse_jsonl(
        content,
        model=_ReviewDecision,
        expected_fields=frozenset(
            {
                "candidate_id",
                "decision",
                "reason",
                "reviewed_at",
                "reviewer",
            }
        ),
        label="decision",
    )
    seen: set[str] = set()
    for decision in decisions:
        if decision.candidate_id in seen:
            raise ValueError(
                f"duplicate decision for candidate {decision.candidate_id}"
            )
        seen.add(decision.candidate_id)
    return decisions


def _parse_jsonl(
    content: bytes,
    *,
    model: type[ModelT],
    expected_fields: frozenset[str],
    label: str,
) -> tuple[ModelT, ...]:
    if not content:
        return ()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} queue is not valid UTF-8") from exc
    rows: list[ModelT] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"blank {label} line {line_number}")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid {label} JSON at line {line_number}"
            ) from exc
        if not isinstance(raw, dict):
            raise ValueError(
                f"invalid {label} object at line {line_number}"
            )
        if frozenset(raw) != expected_fields:
            missing = sorted(expected_fields - frozenset(raw))
            extra = sorted(frozenset(raw) - expected_fields)
            detail = (
                f"missing {','.join(missing)}"
                if missing
                else f"unexpected {','.join(extra)}"
            )
            raise ValueError(
                f"invalid {label} fields at line {line_number}: {detail}"
            )
        try:
            rows.append(model.model_validate_json(line))
        except ValidationError as exc:
            raise ValueError(
                _validation_error_message(
                    exc,
                    label=label,
                    line_number=line_number,
                )
            ) from exc
    return tuple(rows)


def _validation_error_message(
    error: ValidationError,
    *,
    label: str,
    line_number: int,
) -> str:
    first = error.errors()[0]
    location = ".".join(str(item) for item in first["loc"])
    message = str(first["msg"])
    detail = f"{location}: {message}" if location else message
    return f"invalid {label} at line {line_number}: {detail}"


def _validate_queue_identity(
    candidates: tuple[_PendingCandidate, ...],
    quarantine: tuple[_QuarantineCandidate, ...],
) -> None:
    pending_ids = {candidate.candidate_id for candidate in candidates}
    quarantine_ids = {candidate.candidate_id for candidate in quarantine}
    if pending_ids & quarantine_ids:
        raise ValueError(
            "candidate_id appears in pending and quarantine queues"
        )


def _select_approved_candidates(
    *,
    candidates: tuple[_PendingCandidate, ...],
    quarantine: tuple[_QuarantineCandidate, ...],
    decisions: tuple[_ReviewDecision, ...],
) -> tuple[tuple[_PendingCandidate, _ReviewDecision], ...]:
    pending_by_id = {
        candidate.candidate_id: candidate
        for candidate in candidates
    }
    quarantine_ids = {
        candidate.candidate_id for candidate in quarantine
    }
    approved: list[tuple[_PendingCandidate, _ReviewDecision]] = []
    for decision in decisions:
        if decision.candidate_id in quarantine_ids:
            if decision.decision == "approved_fact":
                raise ValueError(
                    "quarantine candidate cannot be approved"
                )
            continue
        candidate = pending_by_id.get(decision.candidate_id)
        if candidate is None:
            raise ValueError(
                f"unknown candidate {decision.candidate_id}"
            )
        if decision.decision == "approved_fact":
            approved.append((candidate, decision))
    return tuple(approved)


def _verify_approved_decision_batch(
    *,
    approved: tuple[tuple[_PendingCandidate, _ReviewDecision], ...],
    decisions: tuple[_ReviewDecision, ...],
    candidate_manifest_raw_sha256: str,
    decision_signature: str | None,
    decision_hmac_key: bytes | None,
) -> None:
    if not approved:
        return
    if decision_hmac_key is None:
        raise ValueError(
            "decision HMAC key is required for non-empty approval"
        )
    if not isinstance(decision_hmac_key, bytes):
        raise TypeError("decision HMAC key must be bytes")
    if len(decision_hmac_key) < 32:
        raise ValueError("decision HMAC key must contain at least 32 bytes")
    if decision_signature is None:
        raise ValueError(
            "detached decision batch signature is required "
            "for non-empty approval"
        )
    if _SHA256_PATTERN.fullmatch(decision_signature) is None:
        raise ValueError(
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
        raise ValueError("decision batch signature mismatch")


def _decision_batch_signature(
    *,
    decisions: tuple[_ReviewDecision, ...],
    candidate_manifest_raw_sha256: str,
    decision_hmac_key: bytes,
) -> str:
    decision_manifest = {
        "decision_count": len(decisions),
        "decisions": [
            decision.model_dump(mode="json")
            for decision in decisions
        ],
        "schema_version": _DECISION_MANIFEST_SCHEMA_VERSION,
    }
    signature_payload = {
        "candidate_manifest_raw_sha256": (
            candidate_manifest_raw_sha256
        ),
        "decision_manifest_sha256": _sha256(
            _canonical_json_bytes(decision_manifest)
        ),
        "schema_version": _DECISION_SIGNATURE_SCHEMA_VERSION,
    }
    return hmac.new(
        decision_hmac_key,
        _canonical_json_bytes(signature_payload),
        hashlib.sha256,
    ).hexdigest()


def _build_facts_bytes(
    approved: tuple[tuple[_PendingCandidate, _ReviewDecision], ...],
) -> bytes:
    facts: dict[str, ApprovedCategoryFact] = {}
    for candidate, decision in approved:
        locator_sha256 = _sha256(
            candidate.source_locator.encode("utf-8")
        )
        source_ref = (
            "urn:xiaoro:category-fact-source:sha256:"
            f"{candidate.source_sha256}:{locator_sha256}"
        )
        unsigned: dict[str, object] = {
            "category_profile": candidate.category_profile,
            "evidence_status": "approved_fact",
            "field_key": candidate.field_key,
            "product_id": candidate.product_id,
            "reviewed_at": decision.reviewed_at,
            "reviewer": decision.reviewer,
            "source_class": candidate.source_class,
            "source_refs": [source_ref],
            "source_sha256": candidate.source_sha256,
            "value": candidate.normalized_value,
        }
        provisional = ApprovedCategoryFact.model_validate(
            {"fact_id": "0" * 64, **unsigned}
        )
        fact_id = _sha256(
            _canonical_json_bytes(
                provisional.model_dump(
                    mode="json",
                    exclude={"fact_id"},
                    exclude_none=True,
                )
            )
        )
        fact = provisional.model_copy(update={"fact_id": fact_id})
        existing = facts.get(fact_id)
        if existing is not None and existing != fact:
            raise CategoryFactPromotionError(
                "approved fact content address collision"
            )
        facts[fact_id] = fact
    return b"".join(
        _canonical_json_bytes(fact.model_dump(mode="json")) + b"\n"
        for fact in sorted(facts.values(), key=lambda item: item.fact_id)
    )


def _build_manifest_bytes(
    *,
    asset_id: str,
    facts_file: str,
    facts_sha256: str,
    fact_count: int,
) -> tuple[bytes, str]:
    unsigned = {
        "asset_id": asset_id,
        "asset_version": (
            f"{_SCHEMA_VERSION}:sha256:{facts_sha256}"
        ),
        "fact_count": fact_count,
        "facts_file": facts_file,
        "facts_sha256": facts_sha256,
        "pilot_bindings": [
            binding.model_dump(mode="json")
            for binding in PILOT_BINDINGS
        ],
        "schema_version": _SCHEMA_VERSION,
    }
    manifest_sha256 = _sha256(_canonical_json_bytes(unsigned))
    manifest = {
        **unsigned,
        "manifest_sha256": manifest_sha256,
    }
    return _canonical_json_bytes(manifest) + b"\n", manifest_sha256


def _candidate_content_digest(candidate: _PendingCandidate) -> str:
    payload = (
        f"{candidate.product_id}\0{candidate.category_profile}\0"
        f"{candidate.field_key}\0{candidate.source_sha256}\0"
        f"{candidate.source_locator}\0"
        f"{_canonical_json_text(candidate.normalized_value)}"
    )
    return _sha256(payload.encode("utf-8"))


def _publish_validated_generation(
    *,
    output_root: Path,
    facts_path: Path,
    manifest_path: Path,
    facts_bytes: bytes,
    manifest_bytes: bytes,
    manifest_sha256: str,
    canonical_manifest_path: Path,
    canonical_products_path: Path,
) -> None:
    _read_existing_target(manifest_path)
    _install_immutable_generation(
        output_root=output_root,
        facts_path=facts_path,
        facts_bytes=facts_bytes,
    )
    manifest_new = _write_manifest_temporary_file(
        output_root,
        manifest_bytes,
    )
    try:
        load_category_fact_assets(
            manifest_path=manifest_new,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
            canonical_reader=CanonicalProductReader.from_files(
                manifest_path=canonical_manifest_path,
                products_path=canonical_products_path,
            ),
            field_registry=category_field_registry(),
        )
        previous_manifest_bytes = _read_existing_target(manifest_path)
        os.replace(manifest_new, manifest_path)
        manifest_new = None
        try:
            _fsync_directory(output_root)
        except OSError:
            restored = _restore_manifest_after_failed_fsync(
                output_root=output_root,
                manifest_path=manifest_path,
                previous_manifest_bytes=previous_manifest_bytes,
                published_manifest_bytes=manifest_bytes,
            )
            if restored:
                raise
    finally:
        if manifest_new is not None:
            manifest_new.unlink(missing_ok=True)
            _fsync_directory(output_root)


def _restore_manifest_after_failed_fsync(
    *,
    output_root: Path,
    manifest_path: Path,
    previous_manifest_bytes: bytes | None,
    published_manifest_bytes: bytes,
) -> bool:
    rollback_path: Path | None = None
    try:
        if previous_manifest_bytes is None:
            manifest_path.unlink()
        else:
            rollback_path = _write_manifest_temporary_file(
                output_root,
                previous_manifest_bytes,
            )
            os.replace(rollback_path, manifest_path)
            rollback_path = None
        _fsync_directory(output_root)
    except OSError as rollback_error:
        if rollback_path is not None:
            try:
                rollback_path.unlink(missing_ok=True)
                _fsync_directory(output_root)
            except OSError:
                pass
        current_manifest_bytes = _read_existing_target(manifest_path)
        if current_manifest_bytes == previous_manifest_bytes:
            return True
        if current_manifest_bytes == published_manifest_bytes:
            return False
        raise CategoryFactPromotionError(
            "manifest pointer state is unknown after failed directory fsync"
        ) from rollback_error

    if _read_existing_target(manifest_path) != previous_manifest_bytes:
        raise CategoryFactPromotionError(
            "previous manifest pointer was not restored"
        )
    return True


def _install_immutable_generation(
    *,
    output_root: Path,
    facts_path: Path,
    facts_bytes: bytes,
) -> None:
    staging_path = _write_generation_staging_file(
        output_root,
        facts_bytes,
    )
    try:
        try:
            os.link(
                staging_path,
                facts_path,
                follow_symlinks=False,
            )
        except FileExistsError:
            existing = _read_existing_target(facts_path)
            if existing != facts_bytes:
                raise CategoryFactPromotionError(
                    "content-addressed facts generation "
                    "has different content"
                )
        else:
            _fsync_directory(output_root)
    finally:
        staging_path.unlink(missing_ok=True)
        _fsync_directory(output_root)

    installed = _read_existing_target(facts_path)
    expected_name = f"{_FACTS_PREFIX}.{_sha256(facts_bytes)}.jsonl"
    if installed != facts_bytes or facts_path.name != expected_name:
        raise CategoryFactPromotionError(
            "content-addressed facts generation verification failed"
        )


def _write_generation_staging_file(
    output_root: Path,
    content: bytes,
) -> Path:
    file_descriptor, raw_path = tempfile.mkstemp(
        prefix=".category-fact-generation.",
        suffix=".staging",
        dir=output_root,
    )
    path = Path(raw_path)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "wb") as output:
            file_descriptor = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(output_root)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        _fsync_directory(output_root)
        raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def _write_manifest_temporary_file(
    output_root: Path,
    content: bytes,
) -> Path:
    file_descriptor, raw_path = tempfile.mkstemp(
        prefix=".category-fact-manifest.",
        suffix=".new",
        dir=output_root,
    )
    path = Path(raw_path)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "wb") as output:
            file_descriptor = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(output_root)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        _fsync_directory(output_root)
        raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def _remove_unreferenced_staging_files(output_root: Path) -> None:
    removed = False
    for candidate in output_root.iterdir():
        if not (
            _GENERATION_STAGING_PATTERN.fullmatch(candidate.name)
            or _MANIFEST_STAGING_PATTERN.fullmatch(candidate.name)
        ):
            continue
        metadata = candidate.lstat()
        if not (
            stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
        ):
            raise CategoryFactPromotionError(
                "promotion staging artifact must be a file"
            )
        candidate.unlink()
        removed = True
    if removed:
        _fsync_directory(output_root)


def _prepare_output_directory(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        _reject_symlink(path, label="promotion output directory")
        if not path.is_dir():
            raise CategoryFactPromotionError(
                "promotion output must be a directory"
            )
    else:
        path.mkdir(parents=True)
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise CategoryFactPromotionError(
            "promotion output cannot be resolved"
        ) from exc


@contextmanager
def _exclusive_publish_lock(path: Path) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(file_descriptor, 0o600)
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise CategoryFactPromotionError(
                "promotion lock must be a regular file"
            )
        fcntl.flock(file_descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(file_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(file_descriptor)


def _read_existing_target(path: Path) -> bytes | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CategoryFactPromotionError(
            "production asset cannot be inspected"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise CategoryFactPromotionError(
            "production asset cannot be a symlink"
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise CategoryFactPromotionError(
            "production asset must be a regular file"
        )
    file_descriptor = -1
    try:
        file_descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise CategoryFactPromotionError(
                "production asset must be a regular file"
            )
        with os.fdopen(file_descriptor, "rb") as source:
            file_descriptor = -1
            return source.read()
    except OSError as exc:
        raise CategoryFactPromotionError(
            "production asset cannot be read"
        ) from exc
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def _reject_symlink(path: Path, *, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        raise CategoryFactPromotionError(
            f"{label} cannot be inspected"
        ) from exc
    if stat.S_ISLNK(mode):
        raise CategoryFactPromotionError(
            f"{label} cannot be a symlink"
        )


def _fsync_directory(path: Path) -> None:
    file_descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


def _validate_expected_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"expected {label} SHA-256 must be lowercase hexadecimal"
        )


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
        raise ValueError("value is not valid JSON") from exc


def _canonical_json_bytes(value: object) -> bytes:
    return _canonical_json_text(value).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _decision_key_from_environment(
    environment_name: str | None,
) -> bytes | None:
    if environment_name is None:
        return None
    if _ENVIRONMENT_NAME_PATTERN.fullmatch(environment_name) is None:
        raise ValueError("decision key environment variable name is invalid")
    value = os.environ.get(environment_name)
    if not value:
        raise ValueError(
            "decision HMAC key environment variable is missing or empty"
        )
    return value.encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Promote explicit human decisions into approved category facts."
        )
    )
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--quarantine", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--expected-candidates-sha256", required=True)
    parser.add_argument("--expected-quarantine-sha256", required=True)
    parser.add_argument("--expected-decisions-sha256", required=True)
    parser.add_argument("--decision-signature")
    parser.add_argument(
        "--decision-key-env",
        help="name of the environment variable containing the HMAC key",
    )
    parser.add_argument("--canonical-manifest", required=True)
    parser.add_argument("--canonical-products", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--asset-id",
        default="guide-category-facts-v1",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = promote_approved_category_facts(
            candidates_path=args.candidates,
            quarantine_path=args.quarantine,
            decisions_path=args.decisions,
            output_dir=args.output_dir,
            expected_candidates_sha256=(
                args.expected_candidates_sha256
            ),
            expected_quarantine_sha256=(
                args.expected_quarantine_sha256
            ),
            expected_decisions_sha256=args.expected_decisions_sha256,
            canonical_manifest_path=args.canonical_manifest,
            canonical_products_path=args.canonical_products,
            decision_signature=args.decision_signature,
            decision_hmac_key=_decision_key_from_environment(
                args.decision_key_env
            ),
            asset_id=args.asset_id,
        )
    except Exception as exc:
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
