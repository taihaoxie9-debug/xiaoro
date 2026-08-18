"""Build local recovery queues without review or production mutation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Callable, Sequence, TypeVar

from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from tools.guide_data.build_category_fact_candidates import (
    build_category_fact_candidates,
)
from tools.guide_data.build_review_candidates import (
    build_review_candidates,
)
from tools.guide_data.inventory_local_sources import (
    _open_output_parent,
    _same_inode,
    _verify_output_parent,
    atomic_write_private,
)


_ROOT = Path(__file__).resolve().parents[2]
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_LOCATOR_PATTERN = re.compile(
    r"^urn:xiaoro:local-source:sha256:[0-9a-f]{64}$"
)
_SOURCE_LOCATOR_DOMAIN = "guide-locked-source-locator-v1"
_INVENTORY_CONTENT_TYPES = frozenset(
    {"html", "jpeg", "json", "jsonl", "png", "webp"}
)
_LOCKED_REVIEW_HASHES = frozenset(
    {
        "55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44",
        "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783",
        "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4",
    }
)
_TARGET_PRODUCT_IDS = {
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
}
_OPERATION_ALLOWLIST = {
    "build_category_fact_candidates": frozenset({"candidate_build"}),
    "build_review_candidates": frozenset({"candidate_build"}),
    "initialize_empty_queues": frozenset({"queue_initialize"}),
}
_FORBIDDEN_CAPABILITIES = frozenset(
    {
        "approval_write",
        "production_write",
        "promotion_call",
        "reviewer_creation",
    }
)
_COVERAGE_STATES = frozenset(
    {"conflict", "known", "not_applicable", "unknown"}
)
_CORE_COVERAGE_KEYS = frozenset(
    {"brand", "category", "identity", "price"}
)
_BINDING_COVERAGE_KEYS = frozenset({"item", "product", "sku"})
_PUBLICATION_DOMAIN = b"guide-recovery-publication-v1\0"
ResultT = TypeVar("ResultT")


class RecoveryError(ValueError):
    """Raised when recovery inputs or operations are not trustworthy."""


@dataclass(frozen=True, slots=True)
class _QueuePaths:
    review_pending: Path
    review_quarantine: Path
    category_pending: Path
    category_quarantine: Path


@dataclass(slots=True)
class _PublicationTarget:
    path: Path
    temporary_name: str
    parent_descriptor: int = -1
    parent_metadata: os.stat_result | None = None
    temporary_metadata: os.stat_result | None = None
    published_metadata: os.stat_result | None = None

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True, slots=True)
class _PublicationParent:
    descriptor: int
    metadata: os.stat_result
    targets: tuple[_PublicationTarget, ...]


class _RecoveryPublication:
    def __init__(
        self,
        *,
        summary_path: str | Path,
        execution_record_path: str | Path,
    ) -> None:
        summary = _normalize_publication_path(
            summary_path,
            label="summary",
        )
        execution = _normalize_publication_path(
            execution_record_path,
            label="execution record",
        )
        if summary == execution:
            raise RecoveryError(
                "summary and execution record outputs must differ"
            )
        self._targets = (
            _PublicationTarget(
                path=summary,
                temporary_name=(
                    f".{summary.name}.guide-recovery.tmp"
                ),
            ),
            _PublicationTarget(
                path=execution,
                temporary_name=(
                    f".{execution.name}.guide-recovery.tmp"
                ),
            ),
        )
        entries = {
            (target.path.parent, name)
            for target in self._targets
            for name in (target.name, target.temporary_name)
        }
        if len(entries) != len(self._targets) * 2:
            raise RecoveryError("recovery output names collide")
        targets_by_parent: dict[Path, list[_PublicationTarget]] = {}
        for target in self._targets:
            targets_by_parent.setdefault(target.path.parent, []).append(
                target
            )
        self._targets_by_parent = {
            parent_path: tuple(targets)
            for parent_path, targets in targets_by_parent.items()
        }
        self._parents: dict[Path, _PublicationParent] = {}
        self._committed = False

    def __enter__(self) -> _RecoveryPublication:
        try:
            for parent_path in sorted(
                self._targets_by_parent,
                key=os.fspath,
            ):
                descriptor, metadata = _open_output_parent(
                    parent_path,
                    create=True,
                )
                registration = _PublicationParent(
                    descriptor=descriptor,
                    metadata=metadata,
                    targets=self._targets_by_parent[parent_path],
                )
                self._parents[parent_path] = registration
                for target in registration.targets:
                    target.parent_descriptor = descriptor
                    target.parent_metadata = metadata
            self._verify_parents()
            self._invalidate_outputs()
            self._verify_parents()
            return self
        except BaseException as exc:
            cleanup_failures: list[BaseException] = []
            try:
                self._invalidate_outputs()
            except BaseException as cleanup_exc:
                cleanup_failures.append(cleanup_exc)
            try:
                self._close_parents()
            except BaseException as close_exc:
                cleanup_failures.append(close_exc)
            if cleanup_failures:
                raise RecoveryError(
                    "recovery outputs could not be invalidated"
                ) from _combined_failure(cleanup_failures)
            if isinstance(exc, RecoveryError):
                raise
            raise RecoveryError(
                "recovery outputs could not be prepared"
            ) from exc

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> bool:
        cleanup_failures: list[BaseException] = []
        try:
            if exc_type is not None or not self._committed:
                self._invalidate_outputs()
        except BaseException as cleanup_exc:
            cleanup_failures.append(cleanup_exc)
        try:
            self._close_parents()
        except BaseException as close_exc:
            cleanup_failures.append(close_exc)
        if cleanup_failures:
            raise RecoveryError(
                "failed recovery publication could not be rolled back"
            ) from _combined_failure(cleanup_failures)
        return False

    def publish(
        self,
        *,
        summary: dict[str, object],
        execution_record: dict[str, object],
    ) -> dict[str, object]:
        bound_summary, bound_execution = _bind_publication_pair(
            summary=summary,
            execution_record=execution_record,
        )
        contents = (
            _canonical_json_bytes(bound_summary) + b"\n",
            _canonical_json_bytes(bound_execution) + b"\n",
        )
        try:
            self._verify_parents()
            self._require_all_outputs_absent()
            for target, content in zip(
                self._targets,
                contents,
                strict=True,
            ):
                target.temporary_metadata = self._write_temporary(
                    target,
                    content,
                )

            self._verify_parents()
            self._require_formal_outputs_absent()
            for target in self._targets:
                os.link(
                    target.temporary_name,
                    target.name,
                    src_dir_fd=target.parent_descriptor,
                    dst_dir_fd=target.parent_descriptor,
                    follow_symlinks=False,
                )
                target.published_metadata = _regular_entry_metadata(
                    target.name,
                    directory_descriptor=target.parent_descriptor,
                )
                if (
                    target.temporary_metadata is None
                    or not _same_inode(
                        target.temporary_metadata,
                        target.published_metadata,
                    )
                ):
                    raise RecoveryError(
                        "recovery output changed during publication"
                    )

            for target in self._targets:
                _unlink_publication_entry(
                    target.temporary_name,
                    directory_descriptor=target.parent_descriptor,
                )
            self._fsync_parents()
            self._verify_parents()
            for target in self._targets:
                observed = _regular_entry_metadata(
                    target.name,
                    directory_descriptor=target.parent_descriptor,
                )
                if (
                    target.published_metadata is None
                    or not _same_inode(
                        target.published_metadata,
                        observed,
                    )
                    or stat.S_IMODE(observed.st_mode) != 0o600
                ):
                    raise RecoveryError(
                        "recovery output changed during publication"
                    )
            self._committed = True
            return bound_summary
        except BaseException as exc:
            try:
                self._invalidate_outputs()
            except BaseException as cleanup_exc:
                raise RecoveryError(
                    "failed recovery publication could not be rolled back"
                ) from cleanup_exc
            if isinstance(exc, RecoveryError):
                raise
            raise RecoveryError(
                "recovery output pair could not be published"
            ) from exc

    def _write_temporary(
        self,
        target: _PublicationTarget,
        content: bytes,
    ) -> os.stat_result:
        descriptor = -1
        try:
            descriptor = os.open(
                target.temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=target.parent_descriptor,
            )
            os.fchmod(descriptor, 0o600)
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise RecoveryError(
                        "recovery temporary output could not be written"
                    )
                view = view[written:]
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size != len(content)
            ):
                raise RecoveryError(
                    "recovery temporary output is invalid"
                )
            observed = _regular_entry_metadata(
                target.temporary_name,
                directory_descriptor=target.parent_descriptor,
            )
            if not _same_inode(metadata, observed):
                raise RecoveryError(
                    "recovery temporary output changed"
                )
            return metadata
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _verify_parents(self) -> None:
        for parent_path, parent in self._parents.items():
            _verify_output_parent(
                parent_path,
                directory_descriptor=parent.descriptor,
                expected_metadata=parent.metadata,
                forbidden_directory_identities=(),
            )

    def _require_all_outputs_absent(self) -> None:
        for target in self._targets:
            for name in (target.name, target.temporary_name):
                if _publication_entry_exists(
                    name,
                    directory_descriptor=target.parent_descriptor,
                ):
                    raise RecoveryError(
                        "recovery output changed before publication"
                    )

    def _require_formal_outputs_absent(self) -> None:
        for target in self._targets:
            if _publication_entry_exists(
                target.name,
                directory_descriptor=target.parent_descriptor,
            ):
                raise RecoveryError(
                    "recovery output changed before publication"
                )

    def _invalidate_outputs(self) -> None:
        failures: list[BaseException] = []
        for parent_path in sorted(self._parents, key=os.fspath):
            parent = self._parents[parent_path]
            for target in parent.targets:
                for name in (target.name, target.temporary_name):
                    try:
                        _unlink_publication_entry(
                            name,
                            directory_descriptor=parent.descriptor,
                        )
                    except BaseException as exc:
                        failures.append(exc)
        for parent_path in sorted(self._parents, key=os.fspath):
            try:
                os.fsync(self._parents[parent_path].descriptor)
            except BaseException as exc:
                failures.append(exc)
        if failures:
            raise RecoveryError(
                "recovery outputs could not be invalidated"
            ) from _combined_failure(failures)

    def _fsync_parents(self) -> None:
        failures: list[BaseException] = []
        for parent_path in sorted(self._parents, key=os.fspath):
            try:
                os.fsync(self._parents[parent_path].descriptor)
            except BaseException as exc:
                failures.append(exc)
        if failures:
            raise RecoveryError(
                "recovery output parents could not be synchronized"
            ) from _combined_failure(failures)

    def _close_parents(self) -> None:
        parents = tuple(self._parents.values())
        self._parents.clear()
        for target in self._targets:
            target.parent_descriptor = -1
            target.parent_metadata = None
        failures: list[BaseException] = []
        for parent in parents:
            try:
                os.close(parent.descriptor)
            except BaseException as exc:
                failures.append(exc)
        if failures:
            raise RecoveryError(
                "recovery output parents could not be closed"
            ) from _combined_failure(failures)


def _combined_failure(
    failures: Sequence[BaseException],
) -> BaseException:
    if len(failures) == 1:
        return failures[0]
    return BaseExceptionGroup(
        "multiple recovery publication cleanup failures",
        list(failures),
    )


def _normalize_publication_path(
    value: str | Path,
    *,
    label: str,
) -> Path:
    raw = os.fspath(Path(value).expanduser())
    if "\x00" in raw:
        raise RecoveryError(f"{label} output path is invalid")
    path = Path(os.path.abspath(raw))
    if not path.name:
        raise RecoveryError(f"{label} output path is invalid")
    return path


def _publication_entry_exists(
    name: str,
    *,
    directory_descriptor: int,
) -> bool:
    try:
        os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RecoveryError(
            "recovery output could not be inspected"
        ) from exc
    return True


def _regular_entry_metadata(
    name: str,
    *,
    directory_descriptor: int,
) -> os.stat_result:
    try:
        metadata = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise RecoveryError(
            "recovery output could not be inspected"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
        metadata.st_mode
    ):
        raise RecoveryError("recovery output must be a regular file")
    return metadata


def _unlink_publication_entry(
    name: str,
    *,
    directory_descriptor: int,
) -> None:
    try:
        os.unlink(name, dir_fd=directory_descriptor)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RecoveryError(
            "recovery output could not be invalidated"
        ) from exc
    if _publication_entry_exists(
        name,
        directory_descriptor=directory_descriptor,
    ):
        raise RecoveryError(
            "recovery output changed during invalidation"
        )


def _bind_publication_pair(
    *,
    summary: dict[str, object],
    execution_record: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    pair_bytes = _canonical_json_bytes(
        {
            "execution_record": execution_record,
            "summary": summary,
        }
    )
    publication = {
        "pair_sha256": hashlib.sha256(pair_bytes).hexdigest(),
        "run_id": hashlib.sha256(
            _PUBLICATION_DOMAIN + pair_bytes
        ).hexdigest(),
        "schema_version": "guide-recovery-publication-v1",
    }
    return (
        {**summary, "publication": publication},
        {**execution_record, "publication": publication},
    )


def recover_candidate_queues(
    *,
    inventory_path: str | Path,
    review_recovery_path: str | Path,
    coverage_path: str | Path,
    canonical_products_path: str | Path,
    output_root: str | Path,
    summary_path: str | Path,
    execution_record_path: str | Path,
    review_source_manifest_path: str | Path | None = None,
    category_source_manifest_path: str | Path | None = None,
) -> dict[str, object]:
    with _RecoveryPublication(
        summary_path=summary_path,
        execution_record_path=execution_record_path,
    ) as publication:
        summary, record = _prepare_candidate_queues(
            inventory_path=inventory_path,
            review_recovery_path=review_recovery_path,
            coverage_path=coverage_path,
            canonical_products_path=canonical_products_path,
            output_root=output_root,
            review_source_manifest_path=review_source_manifest_path,
            category_source_manifest_path=category_source_manifest_path,
        )
        return publication.publish(
            summary=summary,
            execution_record=record,
        )


def _prepare_candidate_queues(
    *,
    inventory_path: str | Path,
    review_recovery_path: str | Path,
    coverage_path: str | Path,
    canonical_products_path: str | Path,
    output_root: str | Path,
    review_source_manifest_path: str | Path | None = None,
    category_source_manifest_path: str | Path | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    inventory_bytes = _read_bytes(Path(inventory_path), label="inventory")
    inventory_rows = _load_inventory(inventory_bytes)
    recovery = _load_recovery(
        Path(review_recovery_path),
        inventory_rows=inventory_rows,
    )
    coverage = _load_coverage(Path(coverage_path))
    if (
        recovery["missing_count"] == 0
        and review_source_manifest_path is None
    ):
        raise RecoveryError(
            "found review sources require source detail for rebuilding"
        )
    operations: list[dict[str, object]] = []
    queue_paths = _execute_allowed(
        "initialize_empty_queues",
        operations,
        lambda: _initialize_empty_queues(Path(output_root)),
    )

    review_result = None
    review_source_hashes: set[str] = set()
    if review_source_manifest_path is not None:
        if recovery["found_count"] == 0:
            raise RecoveryError(
                "review source manifest requires a full SHA match"
            )
        review_source_hashes = _manifest_source_hashes(
            Path(review_source_manifest_path),
            schema_version="review-candidate-sources-v1",
        )
        inventory_hashes = {
            str(row["sha256"]) for row in inventory_rows
        }
        found_review_hashes = {
            str(result["html_sha256"])
            for result in recovery["results"]
            if result.get("status") in {"found", "duplicate"}
        }
        if (
            not review_source_hashes <= inventory_hashes
            or not review_source_hashes <= found_review_hashes
        ):
            raise RecoveryError(
                "review source manifest is not bound to inventory matches"
            )
        review_result = _execute_allowed(
            "build_review_candidates",
            operations,
            lambda: build_review_candidates(
                source_manifest_path=review_source_manifest_path,
                output_root=queue_paths.review_pending.parent,
            ),
        )
        queue_paths = _QueuePaths(
            review_pending=review_result.pending,
            review_quarantine=review_result.quarantine,
            category_pending=queue_paths.category_pending,
            category_quarantine=queue_paths.category_quarantine,
        )

    category_result = None
    if category_source_manifest_path is not None:
        category_source_hashes = _manifest_source_hashes(
            Path(category_source_manifest_path),
            schema_version="guide-category-source-manifest-v1",
        )
        inventory_hashes = {
            str(row["sha256"]) for row in inventory_rows
        }
        if not category_source_hashes <= inventory_hashes:
            raise RecoveryError(
                "category source manifest is not bound to inventory"
            )
        category_result = _execute_allowed(
            "build_category_fact_candidates",
            operations,
            lambda: build_category_fact_candidates(
                source_manifest_path=category_source_manifest_path,
                canonical_products_path=canonical_products_path,
                output_path=queue_paths.category_pending,
                quarantine_path=queue_paths.category_quarantine,
            ),
        )

    execution_counts = _validate_execution_events(operations)
    review_summary, review_candidate_ids = _summarize_queue_family(
        pending_path=queue_paths.review_pending,
        quarantine_path=queue_paths.review_quarantine,
        label="review",
    )
    category_summary, category_candidate_ids = _summarize_queue_family(
        pending_path=queue_paths.category_pending,
        quarantine_path=queue_paths.category_quarantine,
        label="category",
    )
    if review_candidate_ids & category_candidate_ids:
        raise RecoveryError("candidate IDs must be globally unique")
    operation_names = {
        str(operation["name"]) for operation in operations
    }
    if (
        "build_review_candidates" not in operation_names
        and review_candidate_ids
    ):
        raise RecoveryError(
            "review queue records require a review builder event"
        )
    if (
        "build_category_fact_candidates" not in operation_names
        and category_candidate_ids
    ):
        raise RecoveryError(
            "category queue records require a category builder event"
        )
    if review_result is not None and (
        review_result.pending_count != review_summary["pending_count"]
        or review_result.quarantine_count
        != review_summary["quarantine_count"]
        or review_result.extracted_count
        != (
            review_result.deduplicated_count
            + review_summary["pending_count"]
            + review_summary["quarantine_count"]
        )
    ):
        raise RecoveryError(
            "review builder counts contradict queue records"
        )
    if category_result is not None and (
        category_result.pending_count != category_summary["pending_count"]
        or category_result.quarantine_count
        != category_summary["quarantine_count"]
        or category_result.input_count
        != (
            category_result.duplicate_count
            + category_summary["pending_count"]
            + category_summary["quarantine_count"]
        )
    ):
        raise RecoveryError(
            "category builder counts contradict queue records"
        )
    review_provenance = _derive_provenance(
        recovery=recovery,
        review_source_hashes=review_source_hashes,
        review_result=review_result,
        review_summary=review_summary,
    )
    production_fact_count, approved_review_sources = _production_counts()
    summary = {
        "approved_review_sources": approved_review_sources,
        "automatic_approvals": execution_counts["approval_write"],
        "automatic_reviewers": execution_counts["reviewer_creation"],
        "category": category_summary,
        "coverage": {
            "conflict_field_count": coverage["conflict_field_count"],
            "quarantine_count": coverage["quarantine_count"],
            "retained_count": coverage["retained_count"],
            "unknown_field_count": coverage["unknown_field_count"],
        },
        "inventory_file_count": len(inventory_rows),
        "inventory_sha256": _canonical_inventory_sha256(
            inventory_rows
        ),
        "locked_review_sources": {
            "duplicate": recovery["duplicate_count"],
            "found": recovery["found_count"],
            "missing": recovery["missing_count"],
        },
        "product_ids": sorted(
            product["product_id"] for product in coverage["products"]
        ),
        "production_fact_count": production_fact_count,
        "promotion_invocations": execution_counts["promotion_call"],
        "provenance": review_provenance,
        "review": review_summary,
        "schema_version": "guide-recovery-queue-summary-v1",
    }
    record = {
        "allowed_operations": sorted(_OPERATION_ALLOWLIST),
        "operations": operations,
        "schema_version": "guide-recovery-execution-record-v1",
    }
    return summary, record


def _execute_allowed(
    name: str,
    operations: list[dict[str, object]],
    operation: Callable[[], ResultT],
) -> ResultT:
    capabilities = _OPERATION_ALLOWLIST.get(name)
    if capabilities is None or capabilities & _FORBIDDEN_CAPABILITIES:
        raise RecoveryError("recovery operation is not allowed")
    result = operation()
    operations.append(
        {
            "capabilities": sorted(capabilities),
            "name": name,
            "status": "completed",
        }
    )
    return result


def _initialize_empty_queues(output_root: Path) -> _QueuePaths:
    review_root = output_root / "review"
    category_root = output_root / "category"
    review_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    category_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(review_root, 0o700)
    os.chmod(category_root, 0o700)
    paths = _QueuePaths(
        review_pending=review_root / "review_candidates_pending_v1.jsonl",
        review_quarantine=(
            review_root / "review_candidates_quarantine_v1.jsonl"
        ),
        category_pending=category_root / "pending.jsonl",
        category_quarantine=category_root / "quarantine.jsonl",
    )
    for path in (
        paths.review_pending,
        paths.review_quarantine,
        paths.category_pending,
        paths.category_quarantine,
    ):
        atomic_write_private(path, b"")
    return paths


def _summarize_queue_family(
    *,
    pending_path: Path,
    quarantine_path: Path,
    label: str,
) -> tuple[dict[str, int | str], set[str]]:
    pending_bytes, pending_ids = _load_queue_records(
        pending_path,
        expected_status="pending",
        label=f"{label} pending queue",
    )
    quarantine_bytes, quarantine_ids = _load_queue_records(
        quarantine_path,
        expected_status="quarantine",
        label=f"{label} quarantine queue",
    )
    if pending_ids & quarantine_ids:
        raise RecoveryError(f"{label} candidate IDs are duplicated")
    pending_sha256 = hashlib.sha256(pending_bytes).hexdigest()
    quarantine_sha256 = hashlib.sha256(quarantine_bytes).hexdigest()
    aggregate = {
        "pending_sha256": pending_sha256,
        "quarantine_sha256": quarantine_sha256,
    }
    return (
        {
            **aggregate,
            "pending_count": len(pending_ids),
            "quarantine_count": len(quarantine_ids),
            "queue_sha256": hashlib.sha256(
                _canonical_json_bytes(aggregate)
            ).hexdigest(),
        },
        pending_ids | quarantine_ids,
    )


def _load_queue_records(
    path: Path,
    *,
    expected_status: str,
    label: str,
) -> tuple[bytes, set[str]]:
    content = _read_bytes(path, label=label)
    candidate_ids: set[str] = set()
    for line_number, line in enumerate(content.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RecoveryError(
                f"{label} line {line_number} is invalid"
            ) from exc
        candidate_id = (
            row.get("candidate_id") if isinstance(row, dict) else None
        )
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or row.get("status") != expected_status
            or candidate_id in candidate_ids
        ):
            raise RecoveryError(
                f"{label} line {line_number} is invalid"
            )
        candidate_ids.add(candidate_id)
    return content, candidate_ids


def _load_inventory(content: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    identities: set[tuple[str, str]] = set()
    for line_number, line in enumerate(content.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RecoveryError(
                f"invalid inventory line {line_number}"
            ) from exc
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "content_type",
                "relative_name",
                "sha256",
                "size_bytes",
                "source_root_id",
            }
            or row.get("content_type") not in _INVENTORY_CONTENT_TYPES
            or not _safe_relative_name(row.get("relative_name"))
            or not _is_sha256(row.get("sha256"))
            or not _is_sha256(row.get("source_root_id"))
            or type(row.get("size_bytes")) is not int
            or int(row["size_bytes"]) < 0
        ):
            raise RecoveryError("invalid inventory row")
        identity = (
            str(row["source_root_id"]),
            str(row["relative_name"]),
        )
        if identity in identities:
            raise RecoveryError("inventory detail identity is duplicated")
        identities.add(identity)
        rows.append(row)
    if not rows:
        raise RecoveryError("inventory is empty")
    return rows


def _canonical_inventory_sha256(
    rows: list[dict[str, object]],
) -> str:
    ordered = sorted(
        rows,
        key=lambda row: (
            str(row["sha256"]),
            str(row["relative_name"]),
            str(row["source_root_id"]),
            str(row["content_type"]),
            int(row["size_bytes"]),
        ),
    )
    canonical_bytes = b"".join(
        _canonical_json_bytes(row) + b"\n"
        for row in ordered
    )
    return hashlib.sha256(canonical_bytes).hexdigest()


def _load_recovery(
    path: Path,
    *,
    inventory_rows: list[dict[str, object]],
) -> dict[str, object]:
    payload = _load_json_object(path, label="review recovery")
    expected_fields = {
        "duplicate_count",
        "found_count",
        "missing_count",
        "results",
        "schema_version",
    }
    if (
        set(payload) != expected_fields
        or payload["schema_version"]
        != "locked-review-source-lookup-v1"
        or not isinstance(payload["results"], list)
        or len(payload["results"]) != 3
    ):
        raise RecoveryError("invalid review recovery")
    expected_results = _locked_results_from_inventory(inventory_rows)
    declared_results: dict[str, dict[str, object]] = {}
    for raw_result in payload["results"]:
        if (
            not isinstance(raw_result, dict)
            or set(raw_result)
            != {"html_sha256", "matches", "status"}
            or raw_result.get("html_sha256") in declared_results
        ):
            raise RecoveryError("invalid review recovery detail")
        html_sha256 = raw_result.get("html_sha256")
        if (
            not isinstance(html_sha256, str)
            or html_sha256 not in _LOCKED_REVIEW_HASHES
            or raw_result != expected_results[html_sha256]
        ):
            raise RecoveryError("review recovery contradicts inventory")
        declared_results[html_sha256] = raw_result
    if set(declared_results) != _LOCKED_REVIEW_HASHES:
        raise RecoveryError("review recovery locked hashes are incomplete")
    computed_counts = {
        f"{status}_count": sum(
            result["status"] == status
            for result in declared_results.values()
        )
        for status in ("duplicate", "found", "missing")
    }
    if any(
        payload[field] != value
        for field, value in computed_counts.items()
    ):
        raise RecoveryError(
            "review recovery counts contradict detail records"
        )
    return {
        **payload,
        **computed_counts,
        "results": [
            declared_results[html_sha256]
            for html_sha256 in sorted(declared_results)
        ],
    }


def _locked_results_from_inventory(
    rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    matches_by_hash: dict[str, list[dict[str, str]]] = {
        value: [] for value in _LOCKED_REVIEW_HASHES
    }
    for row in rows:
        sha256 = str(row["sha256"])
        if row["content_type"] != "html" or sha256 not in matches_by_hash:
            continue
        matches_by_hash[sha256].append(
            {"source_locator": _anonymous_source_locator(row)}
        )
    results: dict[str, dict[str, object]] = {}
    for html_sha256, matches in matches_by_hash.items():
        ordered = sorted(
            matches,
            key=lambda match: match["source_locator"],
        )
        status = (
            "missing"
            if not ordered
            else "found"
            if len(ordered) == 1
            else "duplicate"
        )
        results[html_sha256] = {
            "html_sha256": html_sha256,
            "matches": ordered,
            "status": status,
        }
    return results


def _anonymous_source_locator(row: dict[str, object]) -> str:
    digest = hashlib.sha256(
        (
            f"{_SOURCE_LOCATOR_DOMAIN}\0"
            f"{row['source_root_id']}\0{row['relative_name']}"
        ).encode("utf-8")
    ).hexdigest()
    locator = f"urn:xiaoro:local-source:sha256:{digest}"
    if _SOURCE_LOCATOR_PATTERN.fullmatch(locator) is None:
        raise RecoveryError("inventory source locator is invalid")
    return locator


def _manifest_source_hashes(
    path: Path,
    *,
    schema_version: str,
) -> set[str]:
    payload = _load_json_object(path, label="source manifest")
    if (
        set(payload) != {"schema_version", "sources"}
        or payload["schema_version"] != schema_version
        or not isinstance(payload["sources"], list)
        or not payload["sources"]
    ):
        raise RecoveryError("source manifest is invalid")
    source_hashes: set[str] = set()
    for source in payload["sources"]:
        if (
            not isinstance(source, dict)
            or not _is_sha256(source.get("sha256"))
        ):
            raise RecoveryError("source manifest SHA-256 is invalid")
        source_hashes.add(str(source["sha256"]))
    return source_hashes


def _load_coverage(path: Path) -> dict[str, object]:
    payload = _load_json_object(path, label="coverage")
    if set(payload) != {
        "conflict_field_count",
        "products",
        "quarantine_count",
        "retained_count",
        "schema_version",
        "target_product_count",
        "unknown_field_count",
    } or payload.get("schema_version") != "pilot-field-coverage-v1":
        raise RecoveryError("invalid pilot coverage")
    raw_products = payload.get("products")
    if not isinstance(raw_products, list) or len(raw_products) != 15:
        raise RecoveryError("invalid pilot coverage")
    products = [
        _validate_coverage_product(product) for product in raw_products
    ]
    product_ids = [int(product["product_id"]) for product in products]
    if (
        len(product_ids) != len(set(product_ids))
        or set(product_ids) != _TARGET_PRODUCT_IDS
    ):
        raise RecoveryError("pilot coverage product IDs are invalid")
    computed = {
        "conflict_field_count": sum(
            field["state"] == "conflict"
            for product in products
            for field in product["fields"].values()
        ),
        "quarantine_count": sum(
            product["product_status"] == "quarantine"
            for product in products
        ),
        "retained_count": sum(
            product["product_status"] == "retained"
            for product in products
        ),
        "target_product_count": len(products),
        "unknown_field_count": sum(
            field["state"] == "unknown"
            for product in products
            for field in product["fields"].values()
        ),
    }
    if any(payload[key] != value for key, value in computed.items()):
        raise RecoveryError(
            "pilot coverage counts contradict detail records"
        )
    return {**payload, **computed, "products": products}


def _validate_coverage_product(
    product: object,
) -> dict[str, object]:
    if not isinstance(product, dict) or set(product) != {
        "bindings",
        "category_profile",
        "core",
        "fields",
        "product_id",
        "product_status",
    }:
        raise RecoveryError("pilot coverage product detail is invalid")
    product_id = product["product_id"]
    if type(product_id) is not int or product_id <= 0:
        raise RecoveryError("pilot coverage product detail is invalid")
    try:
        profile = CategoryProfile(product["category_profile"])
    except (TypeError, ValueError) as exc:
        raise RecoveryError(
            "pilot coverage product profile is invalid"
        ) from exc
    bindings = product["bindings"]
    core = product["core"]
    fields = product["fields"]
    if (
        not isinstance(bindings, dict)
        or set(bindings) != _BINDING_COVERAGE_KEYS
        or any(value not in _COVERAGE_STATES for value in bindings.values())
        or not isinstance(core, dict)
        or set(core) != _CORE_COVERAGE_KEYS
        or any(value not in _COVERAGE_STATES for value in core.values())
        or not isinstance(fields, dict)
    ):
        raise RecoveryError("pilot coverage product detail is invalid")
    expected_field_keys = {
        definition.key
        for definition in category_field_registry().for_profile(profile)
        if definition.key
        not in {"product_identity", "brand", "category", "price"}
    }
    if set(fields) != expected_field_keys:
        raise RecoveryError(
            "pilot coverage field details are incomplete"
        )
    for field in fields.values():
        if (
            not isinstance(field, dict)
            or set(field) != {"action", "state"}
            or field["state"] not in _COVERAGE_STATES
            or field["action"] != _coverage_action(field["state"])
        ):
            raise RecoveryError("pilot coverage field detail is invalid")
    expected_status = (
        "retained"
        if all(value == "known" for value in core.values())
        and bindings["product"] == "known"
        and all(value != "conflict" for value in bindings.values())
        else "quarantine"
    )
    if product["product_status"] != expected_status:
        raise RecoveryError(
            "pilot coverage product status contradicts detail"
        )
    return product


def _coverage_action(state: str) -> str:
    if state == "known":
        return "keep"
    if state == "unknown":
        return "source_recovery"
    return "discard_candidate"


def _validate_execution_events(
    operations: list[dict[str, object]],
) -> dict[str, int]:
    if not operations:
        raise RecoveryError("recovery execution events are missing")
    seen_names: set[str] = set()
    counts = {
        capability: 0
        for capability in _FORBIDDEN_CAPABILITIES
    }
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or set(operation) != {
            "capabilities",
            "name",
            "status",
        }:
            raise RecoveryError("recovery execution event is invalid")
        name = operation["name"]
        capabilities = operation["capabilities"]
        expected = (
            _OPERATION_ALLOWLIST.get(name)
            if isinstance(name, str)
            else None
        )
        if (
            expected is None
            or name in seen_names
            or operation["status"] != "completed"
            or capabilities != sorted(expected)
            or (index == 0 and name != "initialize_empty_queues")
        ):
            raise RecoveryError("recovery execution event is fabricated")
        seen_names.add(name)
        for capability in counts:
            counts[capability] += capability in capabilities
    if any(counts.values()):
        raise RecoveryError(
            "recovery execution attempted a forbidden capability"
        )
    return counts


def _derive_provenance(
    *,
    recovery: dict[str, object],
    review_source_hashes: set[str],
    review_result: object | None,
    review_summary: dict[str, int | str],
) -> str:
    if review_result is None:
        return "source_incomplete"
    historical_hashes = review_source_hashes & _LOCKED_REVIEW_HASHES
    if not historical_hashes:
        computed = "fixture_only"
    elif (
        review_source_hashes == _LOCKED_REVIEW_HASHES
        and recovery["missing_count"] == 0
        and getattr(review_result, "extracted_count", None) == 336
        and review_summary["pending_count"] == 111
    ):
        computed = "historical_reproduced"
    else:
        computed = "source_incomplete"
    if getattr(review_result, "provenance_status", None) != computed:
        raise RecoveryError(
            "review provenance contradicts source and queue details"
        )
    return computed


def _production_counts() -> tuple[int, int]:
    category_root = _ROOT / "data/guide_category_facts"
    category_manifest = _load_json_object(
        category_root / "category_facts_v1_manifest.json",
        label="production category manifest",
    )
    review_root = _ROOT / "data/guide_review_sources"
    review_manifest = _load_json_object(
        review_root / "approved_tmall_feed_reviews_v1_manifest.json",
        label="production review manifest",
    )
    category_name = category_manifest.get("facts_file")
    review_name = review_manifest.get("sources_file")
    if (
        not _safe_relative_name(category_name)
        or not _safe_relative_name(review_name)
    ):
        raise RecoveryError("production counts are invalid")
    category_bytes, fact_count = _jsonl_detail_count(
        category_root / str(category_name),
        label="production category facts",
    )
    review_bytes, source_count = _jsonl_detail_count(
        review_root / str(review_name),
        label="production approved reviews",
    )
    if (
        category_manifest.get("fact_count") != fact_count
        or category_manifest.get("facts_sha256")
        != hashlib.sha256(category_bytes).hexdigest()
        or review_manifest.get("approved_source_count") != source_count
        or review_manifest.get("sources_sha256")
        != hashlib.sha256(review_bytes).hexdigest()
    ):
        raise RecoveryError(
            "production aggregate counts contradict detail records"
        )
    return fact_count, source_count


def _jsonl_detail_count(
    path: Path,
    *,
    label: str,
) -> tuple[bytes, int]:
    content = _read_bytes(path, label=label)
    count = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RecoveryError(
                f"{label} line {line_number} is invalid"
            ) from exc
        if not isinstance(row, dict):
            raise RecoveryError(
                f"{label} line {line_number} is invalid"
            )
        count += 1
    return content, count


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise RecoveryError(f"{label} must be an object")
    return payload


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RecoveryError(f"{label} cannot be read") from exc


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _safe_relative_name(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.parts
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build non-production recovery candidate queues."
    )
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--review-recovery", required=True)
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--canonical-products", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--execution-record", required=True)
    parser.add_argument("--review-source-manifest")
    parser.add_argument("--category-source-manifest")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = recover_candidate_queues(
            inventory_path=args.inventory,
            review_recovery_path=args.review_recovery,
            coverage_path=args.coverage,
            canonical_products_path=args.canonical_products,
            output_root=args.output_root,
            summary_path=args.summary,
            execution_record_path=args.execution_record,
            review_source_manifest_path=args.review_source_manifest,
            category_source_manifest_path=args.category_source_manifest,
        )
    except (OSError, RecoveryError, ValueError) as exc:
        print(
            json.dumps(
                {"error": type(exc).__name__, "status": "failed"},
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=os.sys.stderr,
        )
        return 2
    print(_canonical_json_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
