"""Single-host image inference concurrency control for Linux and macOS.

All participating workers must use the same local shared lock directory and
the same OS account. They share two file-lock slots on a single host, while a
process-local semaphore also coordinates threads. This is not a multi-host
limit; separate hosts or isolated filesystems require an external
admission-control mechanism.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import math
import os
from pathlib import Path
import stat
from threading import BoundedSemaphore, Lock
import tempfile
import time


PROCESS_IMAGE_INFERENCE_LIMIT = 2
IMAGE_INFERENCE_LIMIT_SCOPE = "single_host"
IMAGE_INFERENCE_LOCK_DIR_ENV = "XIAORO_IMAGE_INFERENCE_LOCK_DIR"

_PROCESS_SEMAPHORE_REGISTRY: dict[
    tuple[Path, int],
    BoundedSemaphore,
] = {}
_PROCESS_CAPACITY_BY_DOMAIN: dict[Path, int] = {}
_PROCESS_SEMAPHORE_USERS: dict[tuple[Path, int], int] = {}
_PROCESS_SEMAPHORE_REGISTRY_LOCK = Lock()


class ImageInferenceLockSecurityError(RuntimeError):
    pass


def _lock_directory(configured: str | os.PathLike[str] | None) -> Path:
    if configured is None:
        configured = os.environ.get(IMAGE_INFERENCE_LOCK_DIR_ENV)
    if configured:
        try:
            path = Path(configured).expanduser()
            absolute_path = Path(os.path.abspath(path))
            canonical_parent = absolute_path.parent.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise _security_error("directory") from exc
        return canonical_parent / absolute_path.name
    else:
        try:
            temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise _security_error("directory") from exc
        path = temp_root / f"xiaoro-image-inference-{os.getuid()}"
    return Path(os.path.abspath(path))


def _process_semaphore(
    lock_dir: Path,
    capacity: int,
) -> BoundedSemaphore:
    if capacity <= 0:
        raise ValueError("image inference capacity must be positive")
    key = (lock_dir, capacity)
    with _PROCESS_SEMAPHORE_REGISTRY_LOCK:
        registered_capacity = _PROCESS_CAPACITY_BY_DOMAIN.get(lock_dir)
        if (
            registered_capacity is not None
            and registered_capacity != capacity
        ):
            raise ValueError(
                "image inference domain capacity conflicts with "
                f"registered capacity {registered_capacity}"
            )
        semaphore = _PROCESS_SEMAPHORE_REGISTRY.get(key)
        if semaphore is None:
            semaphore = BoundedSemaphore(capacity)
            _PROCESS_SEMAPHORE_REGISTRY[key] = semaphore
            _PROCESS_CAPACITY_BY_DOMAIN[lock_dir] = capacity
        _PROCESS_SEMAPHORE_USERS[key] = (
            _PROCESS_SEMAPHORE_USERS.get(key, 0) + 1
        )
        return semaphore


def _release_process_semaphore(
    lock_dir: Path,
    capacity: int,
    semaphore: BoundedSemaphore,
) -> None:
    key = (lock_dir, capacity)
    with _PROCESS_SEMAPHORE_REGISTRY_LOCK:
        users = _PROCESS_SEMAPHORE_USERS.get(key)
        if (
            users is None
            or _PROCESS_SEMAPHORE_REGISTRY.get(key) is not semaphore
        ):
            raise RuntimeError("image inference semaphore registry corrupted")
        if users > 1:
            _PROCESS_SEMAPHORE_USERS[key] = users - 1
            return
        del _PROCESS_SEMAPHORE_USERS[key]
        del _PROCESS_SEMAPHORE_REGISTRY[key]
        del _PROCESS_CAPACITY_BY_DOMAIN[lock_dir]


_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _security_error(detail: str) -> ImageInferenceLockSecurityError:
    return ImageInferenceLockSecurityError(
        f"unsafe image inference lock {detail}"
    )


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _open_directory_component(
    parent_descriptor: int,
    component: str,
) -> int:
    flags = os.O_RDONLY | _DIRECTORY | _NO_FOLLOW | _CLOSE_ON_EXEC
    try:
        return os.open(component, flags, dir_fd=parent_descriptor)
    except FileNotFoundError:
        try:
            os.mkdir(component, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
        try:
            return os.open(component, flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise _security_error("directory") from exc
    except OSError as exc:
        raise _security_error("directory") from exc


def _verify_lock_directory(
    descriptor: int,
    lock_dir: Path,
) -> None:
    try:
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.stat(lock_dir, follow_symlinks=False)
    except OSError as exc:
        raise _security_error("directory") from exc
    if (
        not stat.S_ISDIR(descriptor_stat.st_mode)
        or not stat.S_ISDIR(path_stat.st_mode)
        or not _same_inode(descriptor_stat, path_stat)
        or descriptor_stat.st_uid != os.geteuid()
        or stat.S_IMODE(descriptor_stat.st_mode) != 0o700
    ):
        raise _security_error("directory")


def _open_lock_directory(lock_dir: Path) -> int:
    if not lock_dir.is_absolute() or _NO_FOLLOW == 0 or _DIRECTORY == 0:
        raise _security_error("directory")

    descriptor = os.open(
        lock_dir.anchor,
        os.O_RDONLY | _DIRECTORY | _CLOSE_ON_EXEC,
    )
    try:
        for component in lock_dir.parts[1:]:
            child_descriptor = _open_directory_component(
                descriptor,
                component,
            )
            os.close(descriptor)
            descriptor = child_descriptor
        _verify_lock_directory(descriptor, lock_dir)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _verify_lock_file(
    *,
    directory_descriptor: int,
    name: str,
    descriptor: int,
    anchor_name: str | None,
) -> None:
    try:
        descriptor_stat = os.fstat(descriptor)
        entry_stat = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise _security_error("file") from exc
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or not stat.S_ISREG(entry_stat.st_mode)
        or not _same_inode(descriptor_stat, entry_stat)
        or descriptor_stat.st_uid != os.geteuid()
        or stat.S_IMODE(descriptor_stat.st_mode) != 0o600
    ):
        raise _security_error("file")
    if anchor_name is None:
        if descriptor_stat.st_nlink not in (1, 2):
            raise _security_error("file")
        return

    try:
        anchor_stat = os.stat(
            anchor_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise _security_error("file") from exc
    if (
        not stat.S_ISREG(anchor_stat.st_mode)
        or not _same_inode(descriptor_stat, anchor_stat)
        or descriptor_stat.st_nlink != 2
    ):
        raise _security_error("file")


def _lock_anchor_name(name: str) -> str:
    # Keep a second name for the inode so replacing a held slot is detectable.
    return f".{name}.inode"


def _ensure_lock_file_anchor(
    *,
    directory_descriptor: int,
    name: str,
) -> str:
    anchor_name = _lock_anchor_name(name)
    try:
        os.stat(
            anchor_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        try:
            os.link(
                name,
                anchor_name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
        except OSError as exc:
            raise _security_error("file") from exc
    except OSError as exc:
        raise _security_error("file") from exc
    return anchor_name


def _open_lock_file(
    *,
    directory_descriptor: int,
    name: str,
) -> int:
    flags = os.O_RDWR | os.O_CREAT | _NO_FOLLOW | _CLOSE_ON_EXEC
    for attempt in range(2):
        try:
            descriptor = os.open(
                name,
                flags,
                0o600,
                dir_fd=directory_descriptor,
            )
            break
        except FileNotFoundError:
            if attempt == 0:
                continue
            raise _security_error("file")
        except OSError as exc:
            raise _security_error("file") from exc
    try:
        _verify_lock_file(
            directory_descriptor=directory_descriptor,
            name=name,
            descriptor=descriptor,
            anchor_name=None,
        )
        anchor_name = _ensure_lock_file_anchor(
            directory_descriptor=directory_descriptor,
            name=name,
        )
        _verify_lock_file(
            directory_descriptor=directory_descriptor,
            name=name,
            descriptor=descriptor,
            anchor_name=anchor_name,
        )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _acquire_file_slot(
    lock_dir: Path,
    deadline: float | None,
    capacity: int,
) -> tuple[int, int]:
    directory_descriptor = _open_lock_directory(lock_dir)
    try:
        while True:
            _verify_lock_directory(directory_descriptor, lock_dir)
            for index in range(capacity):
                name = f"slot-{index}.lock"
                descriptor = _open_lock_file(
                    directory_descriptor=directory_descriptor,
                    name=name,
                )
                try:
                    fcntl.flock(
                        descriptor,
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                    _verify_lock_file(
                        directory_descriptor=directory_descriptor,
                        name=name,
                        descriptor=descriptor,
                        anchor_name=_lock_anchor_name(name),
                    )
                    _verify_lock_directory(
                        directory_descriptor,
                        lock_dir,
                    )
                except BlockingIOError:
                    os.close(descriptor)
                    continue
                except BaseException:
                    os.close(descriptor)
                    raise
                return descriptor, directory_descriptor
            if deadline is None:
                time.sleep(0.01)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "image inference slot acquisition timed out"
                )
            time.sleep(min(0.01, remaining))
    except BaseException:
        os.close(directory_descriptor)
        raise


@contextmanager
def image_inference_slot(
    *,
    lock_dir: str | os.PathLike[str] | None = None,
    timeout: float | None = None,
) -> Iterator[None]:
    """Acquire one inference slot.

    ``timeout=None`` blocks until a slot is available. A finite non-negative
    timeout is the total wait budget in seconds; ``0`` performs one immediate
    attempt. Exhausting the budget raises ``TimeoutError``.
    """

    if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
        raise ValueError("timeout must be a finite non-negative number or None")
    lock_directory = _lock_directory(lock_dir)
    capacity = PROCESS_IMAGE_INFERENCE_LIMIT
    semaphore = _process_semaphore(lock_directory, capacity)
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        semaphore_acquired = (
            semaphore.acquire()
            if timeout is None
            else semaphore.acquire(timeout=timeout)
        )
        if not semaphore_acquired:
            raise TimeoutError("image inference slot acquisition timed out")

        descriptor: int | None = None
        directory_descriptor: int | None = None
        try:
            descriptor, directory_descriptor = _acquire_file_slot(
                lock_directory,
                deadline,
                capacity,
            )
            yield
        finally:
            try:
                if descriptor is not None:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    finally:
                        os.close(descriptor)
            finally:
                try:
                    if directory_descriptor is not None:
                        os.close(directory_descriptor)
                finally:
                    semaphore.release()
    finally:
        _release_process_semaphore(
            lock_directory,
            capacity,
            semaphore,
        )
