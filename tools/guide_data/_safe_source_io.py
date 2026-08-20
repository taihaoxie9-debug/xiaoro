"""Component-safe reads for manifest-relative source files."""

from __future__ import annotations

import os
from pathlib import Path, PurePath
import stat


class SafeSourceIOError(ValueError):
    """Raised when a source path cannot be read without following links."""


def read_relative_regular_bytes(
    root: str | Path,
    relative_path: str | PurePath,
) -> bytes:
    """Read one stable regular file through verified directory descriptors."""

    relative = PurePath(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise SafeSourceIOError(
            "source path must be a stable regular file"
        )

    absolute_root = Path(os.path.abspath(os.fspath(root)))
    descriptors: list[int] = []
    links: list[tuple[int, str, os.stat_result, int]] = []
    file_descriptor = -1
    try:
        current = os.open(
            absolute_root.anchor,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        descriptors.append(current)
        for part in absolute_root.parts[1:]:
            current, link = _open_directory_component(
                current,
                part,
            )
            descriptors.append(current)
            links.append(link)
        for part in relative.parts[:-1]:
            current, link = _open_directory_component(
                current,
                part,
            )
            descriptors.append(current)
            links.append(link)

        leaf = relative.parts[-1]
        expected = _entry_metadata(current, leaf)
        if stat.S_ISLNK(expected.st_mode) or not stat.S_ISREG(
            expected.st_mode
        ):
            raise SafeSourceIOError(
                "source path must be a stable regular file"
            )
        file_descriptor = os.open(
            leaf,
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=current,
        )
        opened = os.fstat(file_descriptor)
        _require_stable_file(expected, opened)
        chunks: list[bytes] = []
        while chunk := os.read(file_descriptor, 1024 * 1024):
            chunks.append(chunk)
        observed_descriptor = os.fstat(file_descriptor)
        observed_entry = _entry_metadata(current, leaf)
        _require_stable_file(opened, observed_descriptor)
        _require_stable_file(opened, observed_entry)
        _verify_directory_links(links)
        return b"".join(chunks)
    except SafeSourceIOError:
        raise
    except OSError as exc:
        raise SafeSourceIOError(
            "source path must be a stable regular file"
        ) from exc
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _open_directory_component(
    parent_descriptor: int,
    name: str,
) -> tuple[int, tuple[int, str, os.stat_result, int]]:
    expected = _entry_metadata(parent_descriptor, name)
    if stat.S_ISLNK(expected.st_mode) or not stat.S_ISDIR(
        expected.st_mode
    ):
        raise SafeSourceIOError(
            "source path must be a stable regular file"
        )
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not _same_inode(expected, opened)
        ):
            raise SafeSourceIOError(
                "source path must be a stable regular file"
            )
        return descriptor, (
            parent_descriptor,
            name,
            opened,
            descriptor,
        )
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _entry_metadata(
    directory_descriptor: int,
    name: str,
) -> os.stat_result:
    return os.stat(
        name,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )


def _verify_directory_links(
    links: list[tuple[int, str, os.stat_result, int]],
) -> None:
    for parent, name, expected, descriptor in links:
        observed_entry = _entry_metadata(parent, name)
        observed_descriptor = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(observed_entry.st_mode)
            or not stat.S_ISDIR(observed_descriptor.st_mode)
            or not _same_inode(expected, observed_entry)
            or not _same_inode(expected, observed_descriptor)
        ):
            raise SafeSourceIOError(
                "source path must be a stable regular file"
            )


def _require_stable_file(
    expected: os.stat_result,
    observed: os.stat_result,
) -> None:
    if (
        not stat.S_ISREG(observed.st_mode)
        or _stable_file_identity(expected)
        != _stable_file_identity(observed)
    ):
        raise SafeSourceIOError(
            "source path must be a stable regular file"
        )


def _same_inode(
    expected: os.stat_result,
    observed: os.stat_result,
) -> bool:
    return (
        expected.st_dev,
        expected.st_ino,
    ) == (
        observed.st_dev,
        observed.st_ino,
    )


def _stable_file_identity(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
