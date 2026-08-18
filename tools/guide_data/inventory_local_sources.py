"""Build a read-only, anonymous inventory of approved local source roots."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Sequence
import unicodedata


_CONTENT_TYPES = {
    ".htm": "html",
    ".html": "html",
    ".jpeg": "jpeg",
    ".jpg": "jpeg",
    ".json": "json",
    ".jsonl": "jsonl",
    ".png": "png",
    ".webp": "webp",
}
_ROOT_ID_DOMAIN = "guide-source-root-v1"


class SourceInventoryError(ValueError):
    """Raised when an inventory boundary cannot be enforced."""


@dataclass(frozen=True, slots=True)
class ApprovedSourceRoot:
    """An explicitly approved path with a non-sensitive stable label."""

    label: str
    path: Path


@dataclass(frozen=True, slots=True)
class InventoryResult:
    root_count: int
    missing_root_count: int
    rejected_entry_count: int
    file_count: int
    skipped_file_count: int
    overall_status: str
    output_sha256: str


@dataclass(frozen=True, slots=True)
class _NormalizedRoot:
    path: Path
    resolved_path: Path
    source_root_id: str


def inventory_sources(
    roots: Sequence[str | Path | ApprovedSourceRoot],
    output_path: str | Path,
    *,
    continue_on_rejected_entries: bool = False,
) -> InventoryResult:
    """Hash supported regular files without parsing or copying their content."""

    normalized_roots = _normalize_roots(roots)
    output = _validate_output_location(
        output=Path(output_path),
        roots=normalized_roots,
    )

    source_root_identities: list[tuple[int, int]] = []
    rows: list[dict[str, object]] = []
    missing_root_count = 0
    rejected_entry_count = 0
    skipped_file_count = 0
    for root in normalized_roots:
        opened_root = _open_approved_root(
            root.path,
            resolved_path=root.resolved_path,
        )
        if opened_root is None:
            missing_root_count += 1
            continue
        root_descriptor, root_metadata = opened_root
        source_root_identities.append(_inode_identity(root_metadata))
        try:
            root_rows, skipped, rejected = _inventory_root(
                root,
                directory_descriptor=root_descriptor,
                continue_on_rejected_entries=continue_on_rejected_entries,
            )
            _verify_approved_root(
                root.path,
                resolved_path=root.resolved_path,
                expected_metadata=root_metadata,
            )
        finally:
            os.close(root_descriptor)
        rows.extend(root_rows)
        skipped_file_count += skipped
        rejected_entry_count += rejected

    rows.sort(
        key=lambda row: (
            str(row["sha256"]),
            str(row["relative_name"]),
            str(row["source_root_id"]),
        )
    )
    content = b"".join(
        (
            json.dumps(
                row,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        for row in rows
    )
    atomic_write_private(
        output=output,
        content=content,
        forbidden_directory_identities=tuple(source_root_identities),
    )
    return InventoryResult(
        root_count=len(normalized_roots),
        missing_root_count=missing_root_count,
        rejected_entry_count=rejected_entry_count,
        file_count=len(rows),
        skipped_file_count=skipped_file_count,
        overall_status=(
            "complete"
            if missing_root_count == 0 and rejected_entry_count == 0
            else "incomplete"
        ),
        output_sha256=hashlib.sha256(content).hexdigest(),
    )


def atomic_write_private(
    output: str | Path,
    content: bytes,
    *,
    forbidden_directory_identities: Sequence[tuple[int, int]] = (),
) -> None:
    """Atomically replace a regular output with a mode-0600 file."""

    output_path = Path(
        os.path.abspath(os.fspath(Path(output).expanduser()))
    )
    if not output_path.name:
        raise SourceInventoryError("private output path is invalid")

    parent_descriptor = -1
    parent_metadata: os.stat_result | None = None
    rollback_name: str | None = None
    descriptor = -1
    try:
        parent_descriptor, parent_metadata = _open_output_parent(
            output_path.parent,
            create=True,
        )
        _verify_output_parent(
            output_path.parent,
            directory_descriptor=parent_descriptor,
            expected_metadata=parent_metadata,
            forbidden_directory_identities=(
                forbidden_directory_identities
            ),
        )
        expected_output = _inspect_output_entry(
            output_path.name,
            directory_descriptor=parent_descriptor,
        )
        descriptor, rollback_name = _create_private_temporary_file(
            directory_descriptor=parent_descriptor,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as temporary:
            descriptor = -1
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_metadata = os.fstat(temporary.fileno())
        if not stat.S_ISREG(temporary_metadata.st_mode):
            raise SourceInventoryError(
                "private temporary output must be a regular file"
            )

        _verify_output_parent(
            output_path.parent,
            directory_descriptor=parent_descriptor,
            expected_metadata=parent_metadata,
            forbidden_directory_identities=(
                forbidden_directory_identities
            ),
        )
        observed_output = _inspect_output_entry(
            output_path.name,
            directory_descriptor=parent_descriptor,
        )
        _require_unchanged_output_entry(
            expected=expected_output,
            observed=observed_output,
        )
        os.rename(
            rollback_name,
            output_path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        rollback_name = output_path.name
        published_metadata = _inspect_output_entry(
            output_path.name,
            directory_descriptor=parent_descriptor,
        )
        if (
            published_metadata is None
            or not _same_inode(temporary_metadata, published_metadata)
        ):
            raise SourceInventoryError(
                "private output changed during publication"
            )
        _verify_output_parent(
            output_path.parent,
            directory_descriptor=parent_descriptor,
            expected_metadata=parent_metadata,
            forbidden_directory_identities=(
                forbidden_directory_identities
            ),
        )
        os.fsync(parent_descriptor)
        rollback_name = None
    except SourceInventoryError:
        raise
    except OSError as exc:
        raise SourceInventoryError(
            "private output could not be published"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if rollback_name is not None and parent_descriptor >= 0:
            try:
                os.unlink(
                    rollback_name,
                    dir_fd=parent_descriptor,
                )
            except FileNotFoundError:
                pass
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _normalize_roots(
    roots: Sequence[str | Path | ApprovedSourceRoot],
) -> tuple[_NormalizedRoot, ...]:
    if not roots:
        raise SourceInventoryError(
            "at least one approved source root is required"
        )

    normalized: list[_NormalizedRoot] = []
    labels: set[str] = set()
    paths: set[Path] = set()
    for index, raw_root in enumerate(roots, start=1):
        if isinstance(raw_root, ApprovedSourceRoot):
            label = raw_root.label
            path = Path(raw_root.path)
        else:
            label = f"approved-root-{index:04d}"
            path = Path(raw_root)
        normalized_label = unicodedata.normalize(
            "NFKC",
            label,
        ).strip().casefold()
        if not normalized_label or "\x00" in normalized_label:
            raise SourceInventoryError(
                "approved source root label is invalid"
            )
        if normalized_label in labels:
            raise SourceInventoryError(
                "approved source root labels must be unique"
            )
        labels.add(normalized_label)

        resolved_path = path.expanduser().resolve(strict=False)
        if resolved_path in paths:
            raise SourceInventoryError(
                "approved source roots must be unique"
            )
        paths.add(resolved_path)
        root_identity = hashlib.sha256(
            (
                f"{_ROOT_ID_DOMAIN}\0{normalized_label}"
            ).encode("utf-8")
        ).hexdigest()
        normalized.append(
            _NormalizedRoot(
                path=path,
                resolved_path=resolved_path,
                source_root_id=root_identity,
            )
        )
    return tuple(normalized)


def _validate_output_location(
    *,
    output: Path,
    roots: tuple[_NormalizedRoot, ...],
) -> Path:
    output_resolved = output.expanduser().resolve(strict=False)
    for root in roots:
        try:
            output_resolved.relative_to(root.resolved_path)
        except ValueError:
            continue
        raise SourceInventoryError(
            "output must be outside source roots"
        )
    _reject_unsafe_output(output)
    return output_resolved


def _open_output_parent(
    path: Path,
    *,
    create: bool,
) -> tuple[int, os.stat_result]:
    absolute = Path(os.path.abspath(os.fspath(path)))
    descriptor = -1
    keep_open = False
    try:
        descriptor = os.open(
            absolute.anchor,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        for name in absolute.parts[1:]:
            expected = _output_directory_metadata(
                name,
                directory_descriptor=descriptor,
                create=create,
            )
            opened = -1
            try:
                opened = os.open(
                    name,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=descriptor,
                )
                opened_metadata = os.fstat(opened)
                if (
                    not stat.S_ISDIR(opened_metadata.st_mode)
                    or not _same_inode(expected, opened_metadata)
                ):
                    raise SourceInventoryError(
                        "output parent changed during traversal"
                    )
            except BaseException:
                if opened >= 0:
                    os.close(opened)
                raise
            os.close(descriptor)
            descriptor = opened
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise SourceInventoryError(
                "output parent must be a real directory"
            )
        keep_open = True
        return descriptor, metadata
    except SourceInventoryError:
        raise
    except OSError as exc:
        raise SourceInventoryError(
            "output parent could not be opened safely"
        ) from exc
    finally:
        if descriptor >= 0 and not keep_open:
            os.close(descriptor)


def _output_directory_metadata(
    name: str,
    *,
    directory_descriptor: int,
    create: bool,
) -> os.stat_result:
    try:
        metadata = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        if not create:
            raise SourceInventoryError(
                "output parent changed during publication"
            )
        try:
            os.mkdir(
                name,
                mode=0o700,
                dir_fd=directory_descriptor,
            )
        except FileExistsError:
            pass
        try:
            metadata = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise SourceInventoryError(
                "output parent could not be created safely"
            ) from exc
    except OSError as exc:
        raise SourceInventoryError(
            "output parent could not be inspected safely"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
        metadata.st_mode
    ):
        raise SourceInventoryError(
            "output parent must be a real directory"
        )
    return metadata


def _verify_output_parent(
    path: Path,
    *,
    directory_descriptor: int,
    expected_metadata: os.stat_result,
    forbidden_directory_identities: Sequence[tuple[int, int]],
) -> None:
    descriptor_metadata = os.fstat(directory_descriptor)
    if (
        not stat.S_ISDIR(descriptor_metadata.st_mode)
        or not _same_inode(expected_metadata, descriptor_metadata)
    ):
        raise SourceInventoryError(
            "output parent changed during publication"
        )

    reopened_descriptor, reopened_metadata = _open_output_parent(
        path,
        create=False,
    )
    try:
        if (
            not _same_inode(expected_metadata, reopened_metadata)
            or not _same_inode(
                descriptor_metadata,
                reopened_metadata,
            )
        ):
            raise SourceInventoryError(
                "output parent changed during publication"
            )
    finally:
        os.close(reopened_descriptor)

    _reject_output_parent_in_source_tree(
        directory_descriptor,
        forbidden_directory_identities=(
            forbidden_directory_identities
        ),
    )


def _reject_output_parent_in_source_tree(
    directory_descriptor: int,
    *,
    forbidden_directory_identities: Sequence[tuple[int, int]],
) -> None:
    forbidden = set(forbidden_directory_identities)
    if not forbidden:
        return

    current = os.dup(directory_descriptor)
    try:
        while True:
            current_metadata = os.fstat(current)
            if _inode_identity(current_metadata) in forbidden:
                raise SourceInventoryError(
                    "output must be outside source roots"
                )
            parent = os.open(
                "..",
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=current,
            )
            parent_metadata = os.fstat(parent)
            if _same_inode(current_metadata, parent_metadata):
                os.close(parent)
                break
            os.close(current)
            current = parent
    finally:
        os.close(current)


def _inspect_output_entry(
    name: str,
    *,
    directory_descriptor: int,
) -> os.stat_result | None:
    try:
        metadata = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SourceInventoryError(
            "output could not be inspected"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
        metadata.st_mode
    ):
        raise SourceInventoryError(
            "output must be a regular file"
        )
    return metadata


def _require_unchanged_output_entry(
    *,
    expected: os.stat_result | None,
    observed: os.stat_result | None,
) -> None:
    if expected is None and observed is None:
        return
    if (
        expected is None
        or observed is None
        or not _same_inode(expected, observed)
    ):
        raise SourceInventoryError(
            "output changed during publication"
        )


def _create_private_temporary_file(
    *,
    directory_descriptor: int,
) -> tuple[int, str]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    for _ in range(128):
        name = f".guide-inventory-{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(
                name,
                flags,
                0o600,
                dir_fd=directory_descriptor,
            )
        except FileExistsError:
            continue
        return descriptor, name
    raise SourceInventoryError(
        "private temporary output could not be created"
    )


def _open_approved_root(
    path: Path,
    *,
    resolved_path: Path,
) -> tuple[int, os.stat_result] | None:
    declared_path = path.expanduser()
    try:
        declared_metadata = declared_path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SourceInventoryError(
            "approved source root could not be inspected"
        ) from exc
    if stat.S_ISLNK(declared_metadata.st_mode) or not stat.S_ISDIR(
        declared_metadata.st_mode
    ):
        raise SourceInventoryError(
            "approved source roots must be real directories"
        )

    absolute = Path(os.path.abspath(os.fspath(resolved_path)))
    descriptor = -1
    keep_open = False
    try:
        descriptor = os.open(
            "/",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        for name in absolute.parts[1:]:
            try:
                expected = os.stat(
                    name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return None
            if stat.S_ISLNK(expected.st_mode) or not stat.S_ISDIR(
                expected.st_mode
            ):
                raise SourceInventoryError(
                    "approved source roots must be real directories"
                )
            opened = -1
            try:
                opened = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                opened_metadata = os.fstat(opened)
                if (
                    not stat.S_ISDIR(opened_metadata.st_mode)
                    or not _same_inode(expected, opened_metadata)
                ):
                    raise SourceInventoryError(
                        "approved source root changed during inventory"
                    )
            except BaseException:
                if opened >= 0:
                    os.close(opened)
                raise
            os.close(descriptor)
            descriptor = opened
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise SourceInventoryError(
                "approved source roots must be real directories"
            )
        if not _same_inode(declared_metadata, metadata):
            raise SourceInventoryError(
                "approved source root changed during inventory"
            )
        keep_open = True
        return descriptor, metadata
    except SourceInventoryError:
        raise
    except OSError as exc:
        raise SourceInventoryError(
            "approved source root could not be opened safely"
        ) from exc
    finally:
        if descriptor >= 0 and not keep_open:
            os.close(descriptor)


def _verify_approved_root(
    path: Path,
    *,
    resolved_path: Path,
    expected_metadata: os.stat_result,
) -> None:
    opened_root = _open_approved_root(
        path,
        resolved_path=resolved_path,
    )
    if opened_root is None:
        raise SourceInventoryError(
            "approved source root changed during inventory"
        )
    descriptor, observed_metadata = opened_root
    try:
        if not _same_inode(expected_metadata, observed_metadata):
            raise SourceInventoryError(
                "approved source root changed during inventory"
            )
    finally:
        os.close(descriptor)


def _inventory_root(
    root: _NormalizedRoot,
    *,
    directory_descriptor: int,
    continue_on_rejected_entries: bool,
) -> tuple[list[dict[str, object]], int, int]:
    rows: list[dict[str, object]] = []
    skipped_file_count, rejected_entry_count = _inventory_directory(
        directory_descriptor=directory_descriptor,
        relative_parts=(),
        source_root_id=root.source_root_id,
        rows=rows,
        continue_on_rejected_entries=continue_on_rejected_entries,
    )
    return rows, skipped_file_count, rejected_entry_count


def _inventory_directory(
    *,
    directory_descriptor: int,
    relative_parts: tuple[str, ...],
    source_root_id: str,
    rows: list[dict[str, object]],
    continue_on_rejected_entries: bool,
) -> tuple[int, int]:
    skipped_file_count = 0
    rejected_entry_count = 0
    try:
        names = sorted(os.listdir(directory_descriptor))
        for name in names:
            try:
                metadata = _entry_metadata(
                    name,
                    directory_descriptor=directory_descriptor,
                )
                if stat.S_ISDIR(metadata.st_mode):
                    child_descriptor = _open_directory_entry(
                        name,
                        directory_descriptor=directory_descriptor,
                        expected_metadata=metadata,
                    )
                    child_rows: list[dict[str, object]] = []
                    try:
                        child_skipped, child_rejected = (
                            _inventory_directory(
                                directory_descriptor=child_descriptor,
                                relative_parts=relative_parts + (name,),
                                source_root_id=source_root_id,
                                rows=child_rows,
                                continue_on_rejected_entries=(
                                    continue_on_rejected_entries
                                ),
                            )
                        )
                    finally:
                        os.close(child_descriptor)
                    observed = _require_directory(
                        name,
                        directory_descriptor=directory_descriptor,
                    )
                    _require_same_inode(metadata, observed)
                    rows.extend(child_rows)
                    skipped_file_count += child_skipped
                    rejected_entry_count += child_rejected
                    continue

                metadata = _require_regular_file(
                    name,
                    directory_descriptor=directory_descriptor,
                )
                content_type = _CONTENT_TYPES.get(
                    Path(name).suffix.casefold()
                )
                if content_type is None:
                    observed = _require_regular_file(
                        name,
                        directory_descriptor=directory_descriptor,
                    )
                    _require_same_inode(metadata, observed)
                    skipped_file_count += 1
                    continue
                digest, size_bytes = _hash_regular_file(
                    name,
                    directory_descriptor=directory_descriptor,
                    expected_metadata=metadata,
                )
                observed = _require_regular_file(
                    name,
                    directory_descriptor=directory_descriptor,
                )
                _require_same_inode(metadata, observed)
            except SourceInventoryError:
                if not continue_on_rejected_entries:
                    raise
                rejected_entry_count += 1
                continue
            rows.append(
                {
                    "content_type": content_type,
                    "relative_name": "/".join(
                        relative_parts + (name,)
                    ),
                    "sha256": digest,
                    "size_bytes": size_bytes,
                    "source_root_id": source_root_id,
                }
            )
    except SourceInventoryError:
        raise
    except OSError as exc:
        raise SourceInventoryError(
            "approved source root could not be scanned"
        ) from exc
    return skipped_file_count, rejected_entry_count


def _entry_metadata(
    name: str,
    *,
    directory_descriptor: int,
) -> os.stat_result:
    try:
        return os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise SourceInventoryError(
            "source entries could not be inspected"
        ) from exc


def _open_directory_entry(
    name: str,
    *,
    directory_descriptor: int,
    expected_metadata: os.stat_result,
) -> int:
    descriptor = -1
    keep_open = False
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=directory_descriptor,
        )
        opened_metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(opened_metadata.st_mode):
            raise SourceInventoryError(
                "source entries must be regular files or directories"
            )
        _require_same_inode(expected_metadata, opened_metadata)
        keep_open = True
        return descriptor
    except SourceInventoryError:
        raise
    except OSError as exc:
        raise SourceInventoryError(
            "source entry could not be opened safely"
        ) from exc
    finally:
        if descriptor >= 0 and not keep_open:
            os.close(descriptor)


def _require_directory(
    name: str,
    *,
    directory_descriptor: int,
) -> os.stat_result:
    metadata = _entry_metadata(
        name,
        directory_descriptor=directory_descriptor,
    )
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
        metadata.st_mode
    ):
        raise SourceInventoryError(
            "source entries must be regular files or directories"
        )
    return metadata


def _require_regular_file(
    name: str,
    *,
    directory_descriptor: int,
) -> os.stat_result:
    metadata = _entry_metadata(
        name,
        directory_descriptor=directory_descriptor,
    )
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
        metadata.st_mode
    ):
        raise SourceInventoryError(
            "source entries must be regular files or directories"
        )
    return metadata


def _same_inode(
    expected: os.stat_result,
    observed: os.stat_result,
) -> bool:
    return _inode_identity(expected) == _inode_identity(observed)


def _inode_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _require_same_inode(
    expected: os.stat_result,
    observed: os.stat_result,
) -> None:
    if not _same_inode(expected, observed):
        raise SourceInventoryError(
            "source entry changed during inventory"
        )


def _hash_regular_file(
    name: str,
    *,
    directory_descriptor: int,
    expected_metadata: os.stat_result,
) -> tuple[str, int]:
    descriptor = -1
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=directory_descriptor,
        )
        opened_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(opened_metadata.st_mode):
            raise SourceInventoryError(
                "source entries must be regular files or directories"
            )
        _require_same_inode(expected_metadata, opened_metadata)
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size_bytes += len(chunk)
    except SourceInventoryError:
        raise
    except OSError as exc:
        raise SourceInventoryError(
            "source entry could not be read safely"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return digest.hexdigest(), size_bytes


def _reject_unsafe_output(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        raise SourceInventoryError(
            "output could not be inspected"
        ) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise SourceInventoryError(
            "output must be a regular file"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory explicitly approved local source roots without "
            "copying source content."
        )
    )
    parser.add_argument(
        "--root",
        action="append",
        required=True,
        help="approved local source root; may be repeated",
    )
    parser.add_argument(
        "--continue-on-rejected-entry",
        action="store_true",
        help=(
            "skip rejected entries and mark the aggregate inventory "
            "incomplete"
        ),
    )
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = inventory_sources(
            roots=[Path(value) for value in args.root],
            output_path=Path(args.output),
            continue_on_rejected_entries=(
                args.continue_on_rejected_entry
            ),
        )
    except SourceInventoryError:
        print(
            json.dumps(
                {"status": "error", "type": "source_inventory_error"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            asdict(result),
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
