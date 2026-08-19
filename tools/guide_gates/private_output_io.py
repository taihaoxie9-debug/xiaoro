"""Descriptor-based helpers for private runtime evidence files."""

from __future__ import annotations

from collections.abc import Mapping
import fcntl
import json
import os
from pathlib import Path
import stat
from typing import Any


class InvalidOutputDescriptorError(ValueError):
    """Raised when an output descriptor is not a writable regular file."""


class OutputBindingError(RuntimeError):
    """Raised when an output name no longer refers to its opened inode."""


class PrivateRunDirectory:
    """A private run directory bound to held parent and child descriptors."""

    def __init__(
        self,
        path: Path,
        parent_descriptor: int,
        directory_descriptor: int,
    ) -> None:
        self.path = path
        self.parent_descriptor = parent_descriptor
        self.directory_descriptor = directory_descriptor

    @classmethod
    def create(cls, path: Path) -> PrivateRunDirectory:
        if not path.name or ".." in path.parts:
            raise ValueError("output_dir must name a new child directory")
        parent_flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | os.O_CLOEXEC
        )
        parent_descriptor = os.open(path.parent, parent_flags)
        try:
            parent_status = os.fstat(parent_descriptor)
            if not stat.S_ISDIR(parent_status.st_mode):
                raise NotADirectoryError(path.parent)
            if (
                parent_status.st_mode & 0o022
                and not parent_status.st_mode & stat.S_ISVTX
            ):
                raise PermissionError(
                    "output_dir parent must not be group/world writable"
                )
            os.mkdir(path.name, mode=0o700, dir_fd=parent_descriptor)
            directory_descriptor = os.open(
                path.name,
                parent_flags,
                dir_fd=parent_descriptor,
            )
        except BaseException:
            os.close(parent_descriptor)
            raise

        try:
            if not stat.S_ISDIR(os.fstat(directory_descriptor).st_mode):
                raise NotADirectoryError(path)
            os.fchmod(directory_descriptor, 0o700)
            run_directory = cls(
                path,
                parent_descriptor,
                directory_descriptor,
            )
            run_directory.verify_binding()
            return run_directory
        except BaseException:
            os.close(directory_descriptor)
            os.close(parent_descriptor)
            raise

    def verify_binding(self) -> None:
        """Require the visible output path to name the held directory."""
        try:
            opened = os.fstat(self.directory_descriptor)
            parent_bound = os.stat(
                self.path.name,
                dir_fd=self.parent_descriptor,
                follow_symlinks=False,
            )
            visible = os.stat(self.path, follow_symlinks=False)
        except OSError as exc:
            raise OutputBindingError(
                f"private output directory binding changed: {self.path}"
            ) from exc
        for bound in (parent_bound, visible):
            if (
                not stat.S_ISDIR(bound.st_mode)
                or opened.st_dev != bound.st_dev
                or opened.st_ino != bound.st_ino
            ):
                raise OutputBindingError(
                    "private output directory binding changed: "
                    f"{self.path}"
                )

    def close(self) -> None:
        os.close(self.directory_descriptor)
        os.close(self.parent_descriptor)


def duplicate_writable_regular_fd(descriptor: int) -> int:
    """Validate and duplicate a caller-owned output descriptor."""
    duplicate: int | None = None
    try:
        duplicate = os.dup(descriptor)
        status = os.fstat(duplicate)
        access_mode = fcntl.fcntl(duplicate, fcntl.F_GETFL) & os.O_ACCMODE
        if not stat.S_ISREG(status.st_mode) or access_mode == os.O_RDONLY:
            raise InvalidOutputDescriptorError(
                "output_fd must reference a regular writable file"
            )
        return duplicate
    except InvalidOutputDescriptorError:
        if duplicate is not None:
            os.close(duplicate)
        raise
    except (OSError, TypeError, ValueError) as exc:
        if duplicate is not None:
            os.close(duplicate)
        raise InvalidOutputDescriptorError(
            "output_fd must reference a regular writable file"
        ) from exc


def open_private_path(path: str | Path) -> int:
    """Create one private output path without following a final symlink."""
    descriptor = os.open(
        Path(path),
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
        0o600,
    )
    try:
        _validate_created_output(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def open_private_at(directory_fd: int, filename: str) -> int:
    """Create a private regular file relative to a held directory fd."""
    if not filename or Path(filename).name != filename:
        raise ValueError("private output filename must be a basename")
    descriptor = os.open(
        filename,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        _validate_created_output(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def verify_output_binding(
    directory_fd: int,
    filename: str,
    descriptor: int,
) -> None:
    """Require a directory entry to remain bound to its opened inode."""
    try:
        opened = os.fstat(descriptor)
        bound = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise OutputBindingError(
            f"private output binding changed: {filename}"
        ) from exc
    if (
        not stat.S_ISREG(bound.st_mode)
        or opened.st_dev != bound.st_dev
        or opened.st_ino != bound.st_ino
    ):
        raise OutputBindingError(
            f"private output binding changed: {filename}"
        )


def verify_path_binding(path: str | Path, descriptor: int) -> None:
    """Require a visible path to remain bound to its opened file inode."""
    output_path = Path(path)
    try:
        opened = os.fstat(descriptor)
        visible = os.stat(output_path, follow_symlinks=False)
    except OSError as exc:
        raise OutputBindingError(
            f"private output path binding changed: {output_path}"
        ) from exc
    if (
        not stat.S_ISREG(visible.st_mode)
        or opened.st_dev != visible.st_dev
        or opened.st_ino != visible.st_ino
    ):
        raise OutputBindingError(
            f"private output path binding changed: {output_path}"
        )


def write_json_fd(
    descriptor: int,
    payload: Mapping[str, Any],
) -> None:
    """Replace JSON content through a duplicated caller-owned fd."""
    duplicate = duplicate_writable_regular_fd(descriptor)
    try:
        os.lseek(duplicate, 0, os.SEEK_SET)
        os.ftruncate(duplicate, 0)
        destination = os.fdopen(
            duplicate,
            "w",
            encoding="utf-8",
            closefd=True,
        )
    except BaseException:
        os.close(duplicate)
        raise
    try:
        json.dump(
            payload,
            destination,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        destination.write("\n")
    finally:
        destination.close()


def _validate_created_output(descriptor: int) -> None:
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        raise OSError("private output must be a regular file")
    os.fchmod(descriptor, 0o600)
