from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import math
from multiprocessing import get_context
import os
from pathlib import Path
import stat
from threading import Event, Lock
import time
from typing import Any

import pytest


def _subject() -> Any:
    return import_module("app.guide.adapters.image.inference_limiter")


def _run_process_limited_task(
    lock_dir: str,
    start: Any,
    release: Any,
    ready: Any,
    active: Any,
    maximum_active: Any,
) -> None:
    os.environ["XIAORO_IMAGE_INFERENCE_LOCK_DIR"] = lock_dir
    module = _subject()
    ready.put(os.getpid())
    if not start.wait(timeout=5):
        raise RuntimeError("multiprocessing start barrier timed out")

    with module.image_inference_slot():
        with active.get_lock():
            active.value += 1
            maximum_active.value = max(maximum_active.value, active.value)
        try:
            if not release.wait(timeout=5):
                raise RuntimeError("multiprocessing release barrier timed out")
        finally:
            with active.get_lock():
                active.value -= 1


def _run_process_thread_limited_tasks(
    lock_dir: str,
    start: Any,
    release: Any,
    ready: Any,
    active: Any,
    maximum_active: Any,
) -> None:
    module = _subject()
    ready.put(os.getpid())
    if not start.wait(timeout=5):
        raise RuntimeError("mixed concurrency start barrier timed out")

    def run() -> None:
        with module.image_inference_slot(lock_dir=lock_dir):
            with active.get_lock():
                active.value += 1
                maximum_active.value = max(
                    maximum_active.value,
                    active.value,
                )
            try:
                if not release.wait(timeout=5):
                    raise RuntimeError(
                        "mixed concurrency release barrier timed out"
                    )
            finally:
                with active.get_lock():
                    active.value -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        for future in futures:
            future.result(timeout=6)


def _hold_process_slot(
    lock_dir: str,
    entered: Any,
    release: Any,
) -> None:
    module = _subject()
    with module.image_inference_slot(lock_dir=lock_dir):
        entered.put(os.getpid())
        if not release.wait(timeout=5):
            raise RuntimeError("process holder release barrier timed out")


def test_limiter_enforces_two_slot_peak_across_processes(
    tmp_path: Path,
) -> None:
    context = get_context("spawn")
    start = context.Event()
    release = context.Event()
    ready = context.Queue()
    active = context.Value("i", 0)
    maximum_active = context.Value("i", 0)
    processes = [
        context.Process(
            target=_run_process_limited_task,
            args=(
                str(tmp_path),
                start,
                release,
                ready,
                active,
                maximum_active,
            ),
        )
        for _ in range(4)
    ]

    try:
        for process in processes:
            process.start()
        for _ in processes:
            ready.get(timeout=5)
        start.set()

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and maximum_active.value < 3:
            time.sleep(0.01)
    finally:
        start.set()
        release.set()
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        ready.close()
        ready.join_thread()

    assert [process.exitcode for process in processes] == [0, 0, 0, 0]
    assert maximum_active.value <= 2
    assert active.value == 0


def test_limiter_enforces_two_slot_peak_across_processes_and_threads(
    tmp_path: Path,
) -> None:
    context = get_context("spawn")
    start = context.Event()
    release = context.Event()
    ready = context.Queue()
    active = context.Value("i", 0)
    maximum_active = context.Value("i", 0)
    processes = [
        context.Process(
            target=_run_process_thread_limited_tasks,
            args=(
                str(tmp_path),
                start,
                release,
                ready,
                active,
                maximum_active,
            ),
        )
        for _ in range(3)
    ]

    try:
        for process in processes:
            process.start()
        for _ in processes:
            ready.get(timeout=5)
        start.set()

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and maximum_active.value < 3:
            time.sleep(0.01)
    finally:
        start.set()
        release.set()
        for process in processes:
            process.join(timeout=7)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        ready.close()
        ready.join_thread()

    assert [process.exitcode for process in processes] == [0, 0, 0]
    assert maximum_active.value == 2
    assert active.value == 0


def test_new_lock_directory_and_lock_file_are_private(
    tmp_path: Path,
) -> None:
    module = _subject()
    lock_dir = tmp_path / "locks"
    first_slot = lock_dir / "slot-0.lock"

    with module.image_inference_slot(lock_dir=lock_dir):
        directory_stat = lock_dir.stat()
        lock_stat = first_slot.stat()

    assert stat.S_IMODE(directory_stat.st_mode) == 0o700
    assert directory_stat.st_uid == os.geteuid()
    assert stat.S_ISREG(lock_stat.st_mode)
    assert stat.S_IMODE(lock_stat.st_mode) == 0o600
    assert lock_stat.st_uid == os.geteuid()


def test_rejects_custom_lock_directory_symlink(tmp_path: Path) -> None:
    module = _subject()
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    lock_dir = tmp_path / "locks"
    lock_dir.symlink_to(target, target_is_directory=True)

    with pytest.raises(RuntimeError, match="unsafe image inference lock"):
        with module.image_inference_slot(lock_dir=lock_dir):
            raise AssertionError("symlinked lock directory was accepted")


def test_rejects_default_lock_directory_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _subject()
    monkeypatch.delenv(module.IMAGE_INFERENCE_LOCK_DIR_ENV, raising=False)
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(tmp_path))
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    default_lock_dir = (
        tmp_path / f"xiaoro-image-inference-{os.getuid()}"
    )
    default_lock_dir.symlink_to(target, target_is_directory=True)

    with pytest.raises(RuntimeError, match="unsafe image inference lock"):
        with module.image_inference_slot():
            raise AssertionError(
                "symlinked default lock directory was accepted"
            )


def test_default_lock_directory_canonicalizes_trusted_temp_root_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _subject()
    monkeypatch.delenv(module.IMAGE_INFERENCE_LOCK_DIR_ENV, raising=False)
    real_temp_root = tmp_path / "real-temp"
    real_temp_root.mkdir(mode=0o700)
    temp_root_alias = tmp_path / "temp-alias"
    temp_root_alias.symlink_to(real_temp_root, target_is_directory=True)
    monkeypatch.setattr(
        module.tempfile,
        "gettempdir",
        lambda: str(temp_root_alias),
    )
    expected_lock_dir = (
        real_temp_root / f"xiaoro-image-inference-{os.getuid()}"
    )

    with module.image_inference_slot():
        assert expected_lock_dir.is_dir()

    assert stat.S_IMODE(expected_lock_dir.stat().st_mode) == 0o700


def test_configured_lock_directory_canonicalizes_trusted_parent_alias(
    tmp_path: Path,
) -> None:
    module = _subject()
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    parent_alias = tmp_path / "parent-alias"
    parent_alias.symlink_to(real_parent, target_is_directory=True)
    expected_lock_dir = real_parent / "locks"

    with module.image_inference_slot(lock_dir=parent_alias / "locks"):
        assert expected_lock_dir.is_dir()

    assert stat.S_IMODE(expected_lock_dir.stat().st_mode) == 0o700


def test_rejects_lock_directory_with_insecure_permissions(
    tmp_path: Path,
) -> None:
    module = _subject()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(mode=0o700)
    lock_dir.chmod(0o755)

    with pytest.raises(RuntimeError, match="unsafe image inference lock"):
        with module.image_inference_slot(lock_dir=lock_dir):
            raise AssertionError("insecure lock directory was accepted")


def test_rejects_lock_directory_owned_by_another_uid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _subject()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(mode=0o700)
    actual_uid = os.geteuid()
    monkeypatch.setattr(module.os, "geteuid", lambda: actual_uid + 1)

    with pytest.raises(RuntimeError, match="unsafe image inference lock"):
        with module.image_inference_slot(lock_dir=lock_dir):
            raise AssertionError("foreign-owned lock directory was accepted")


def test_rejects_lock_file_symlink_without_chmodding_target(
    tmp_path: Path,
) -> None:
    module = _subject()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_bytes(b"do-not-touch")
    target.chmod(0o640)
    (lock_dir / "slot-0.lock").symlink_to(target)

    with pytest.raises(RuntimeError, match="unsafe image inference lock"):
        with module.image_inference_slot(lock_dir=lock_dir):
            raise AssertionError("symlinked lock file was accepted")

    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_rejects_lock_file_with_insecure_permissions(
    tmp_path: Path,
) -> None:
    module = _subject()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(mode=0o700)
    lock_file = lock_dir / "slot-0.lock"
    lock_file.touch(mode=0o600)
    lock_file.chmod(0o644)

    with pytest.raises(RuntimeError, match="unsafe image inference lock"):
        with module.image_inference_slot(lock_dir=lock_dir):
            raise AssertionError("insecure lock file was accepted")


def test_rejects_nonregular_lock_file(tmp_path: Path) -> None:
    module = _subject()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(mode=0o700)
    os.mkfifo(lock_dir / "slot-0.lock", mode=0o600)

    with pytest.raises(RuntimeError, match="unsafe image inference lock"):
        with module.image_inference_slot(lock_dir=lock_dir):
            raise AssertionError("nonregular lock file was accepted")


def test_rejects_lock_file_inode_replacement_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _subject()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir(mode=0o700)
    real_open = os.open
    real_unlink = os.unlink
    replaced = False

    def replace_after_open(
        path,
        flags,
        mode=0o777,
        *,
        dir_fd=None,
    ):
        nonlocal replaced
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if (
            not replaced
            and Path(path).name == "slot-0.lock"
            and flags & os.O_CREAT
        ):
            replaced = True
            real_unlink(path, dir_fd=dir_fd)
            replacement = real_open(
                path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            os.close(replacement)
        return descriptor

    monkeypatch.setattr(module.os, "open", replace_after_open)

    with pytest.raises(RuntimeError, match="unsafe image inference lock"):
        with module.image_inference_slot(lock_dir=lock_dir):
            raise AssertionError("replaced lock inode was accepted")


def test_zero_timeout_fails_when_both_slots_are_held(
    tmp_path: Path,
) -> None:
    module = _subject()
    release = Event()
    entered = [Event(), Event()]

    def hold_slot(index: int) -> None:
        with module.image_inference_slot(lock_dir=tmp_path):
            entered[index].set()
            release.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(hold_slot, index) for index in range(2)]
        assert entered[0].wait(timeout=1)
        assert entered[1].wait(timeout=1)
        try:
            with pytest.raises(TimeoutError, match="timed out"):
                with module.image_inference_slot(
                    lock_dir=tmp_path,
                    timeout=0,
                ):
                    raise AssertionError("unavailable slot was entered")
        finally:
            release.set()
            for future in futures:
                future.result(timeout=2)


def test_distinct_lock_directory_domains_have_independent_process_slots(
    tmp_path: Path,
) -> None:
    module = _subject()
    inference_lock_dir = tmp_path / "inference-slots"
    upload_lock_dir = tmp_path / "upload-slots"
    release = Event()
    entered = [Event(), Event()]

    def hold_inference_slot(index: int) -> None:
        with module.image_inference_slot(lock_dir=inference_lock_dir):
            entered[index].set()
            release.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(hold_inference_slot, index)
            for index in range(2)
        ]
        assert entered[0].wait(timeout=1)
        assert entered[1].wait(timeout=1)
        try:
            with module.image_inference_slot(
                lock_dir=upload_lock_dir,
                timeout=0,
            ):
                pass
        finally:
            release.set()
            for future in futures:
                future.result(timeout=2)


def test_equivalent_lock_directory_paths_share_process_limit(
    tmp_path: Path,
) -> None:
    module = _subject()
    lock_dir = tmp_path / "shared-slots"
    equivalent_lock_dir = lock_dir / ".." / lock_dir.name
    release = Event()
    entered = [Event(), Event()]

    def hold_slot(index: int) -> None:
        with module.image_inference_slot(lock_dir=lock_dir):
            entered[index].set()
            release.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(hold_slot, index) for index in range(2)]
        assert entered[0].wait(timeout=1)
        assert entered[1].wait(timeout=1)
        try:
            with pytest.raises(TimeoutError, match="timed out"):
                with module.image_inference_slot(
                    lock_dir=equivalent_lock_dir,
                    timeout=0,
                ):
                    raise AssertionError(
                        "equivalent domain bypassed the process limit"
                    )
        finally:
            release.set()
            for future in futures:
                future.result(timeout=2)


def test_same_domain_rejects_conflicting_process_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _subject()
    lock_dir = tmp_path / "capacity-slots"

    with module.image_inference_slot(lock_dir=lock_dir):
        monkeypatch.setattr(module, "PROCESS_IMAGE_INFERENCE_LIMIT", 3)
        with pytest.raises(ValueError, match="capacity"):
            with module.image_inference_slot(lock_dir=lock_dir, timeout=0):
                raise AssertionError(
                    "active conflicting domain capacity was accepted"
                )

    with module.image_inference_slot(lock_dir=lock_dir, timeout=0):
        pass


def test_process_admission_registry_releases_inactive_domains(
    tmp_path: Path,
) -> None:
    module = _subject()

    for index in range(32):
        with module.image_inference_slot(
            lock_dir=tmp_path / f"domain-{index}",
        ):
            pass

    assert module._PROCESS_SEMAPHORE_REGISTRY == {}
    assert module._PROCESS_CAPACITY_BY_DOMAIN == {}
    assert module._PROCESS_SEMAPHORE_USERS == {}


def test_finite_timeout_applies_to_cross_process_file_slots(
    tmp_path: Path,
) -> None:
    module = _subject()
    context = get_context("spawn")
    entered = context.Queue()
    release = context.Event()
    processes = [
        context.Process(
            target=_hold_process_slot,
            args=(str(tmp_path), entered, release),
        )
        for _ in range(2)
    ]
    elapsed = 0.0

    try:
        for process in processes:
            process.start()
        for _ in processes:
            entered.get(timeout=5)

        started = time.monotonic()
        with pytest.raises(TimeoutError, match="timed out"):
            with module.image_inference_slot(
                lock_dir=tmp_path,
                timeout=0.05,
            ):
                raise AssertionError("cross-process slot was entered")
        elapsed = time.monotonic() - started
    finally:
        release.set()
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        entered.close()
        entered.join_thread()

    assert [process.exitcode for process in processes] == [0, 0]
    assert 0.04 <= elapsed < 1


def test_replacing_locked_slot_inodes_cannot_admit_third_process(
    tmp_path: Path,
) -> None:
    module = _subject()
    context = get_context("spawn")
    entered = context.Queue()
    release = context.Event()
    processes = [
        context.Process(
            target=_hold_process_slot,
            args=(str(tmp_path), entered, release),
        )
        for _ in range(2)
    ]

    try:
        for process in processes:
            process.start()
        for _ in processes:
            entered.get(timeout=5)

        for index in range(2):
            lock_file = tmp_path / f"slot-{index}.lock"
            lock_file.unlink()
            lock_file.touch(mode=0o600)

        with pytest.raises(RuntimeError, match="unsafe image inference lock"):
            with module.image_inference_slot(lock_dir=tmp_path, timeout=0):
                raise AssertionError(
                    "replacement lock inodes admitted a third process"
                )
    finally:
        release.set()
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        entered.close()
        entered.join_thread()

    assert [process.exitcode for process in processes] == [0, 0]


@pytest.mark.parametrize("timeout", [-0.01, math.nan, math.inf])
def test_invalid_timeout_is_rejected(
    tmp_path: Path,
    timeout: float,
) -> None:
    module = _subject()

    with pytest.raises(ValueError, match="finite non-negative"):
        with module.image_inference_slot(lock_dir=tmp_path, timeout=timeout):
            raise AssertionError("invalid timeout was accepted")


def test_limiter_allows_at_most_two_inference_tasks_across_threads(
    tmp_path: Path,
) -> None:
    module = _subject()
    release = Event()
    entered = [Event(), Event(), Event()]
    state_lock = Lock()
    active = 0
    maximum_active = 0

    def run(index: int) -> None:
        nonlocal active, maximum_active
        with module.image_inference_slot(lock_dir=tmp_path):
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            entered[index].set()
            release.wait(timeout=2)
            with state_lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run, index) for index in range(3)]
        deadline = time.monotonic() + 1
        while (
            time.monotonic() < deadline
            and sum(event.is_set() for event in entered) < 2
        ):
            time.sleep(0.01)
        entered_while_slots_held = sum(event.is_set() for event in entered)
        release.set()
        for future in futures:
            future.result(timeout=2)

    assert entered_while_slots_held == 2
    assert all(event.is_set() for event in entered)
    assert maximum_active == 2
    assert active == 0


def test_limiter_releases_file_and_thread_slots_after_exception(
    tmp_path: Path,
) -> None:
    module = _subject()

    with pytest.raises(RuntimeError, match="inference failed"):
        with module.image_inference_slot(lock_dir=tmp_path):
            raise RuntimeError("inference failed")

    release = Event()
    entered = [Event(), Event()]

    def run(index: int) -> None:
        with module.image_inference_slot(lock_dir=tmp_path):
            entered[index].set()
            release.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, index) for index in range(2)]
        both_slots_reusable = (
            entered[0].wait(timeout=1)
            and entered[1].wait(timeout=1)
        )
        release.set()
        for future in futures:
            future.result(timeout=2)

    assert both_slots_reusable is True


def test_limiter_releases_thread_slot_when_lock_directory_setup_fails(
    tmp_path: Path,
) -> None:
    module = _subject()
    invalid_lock_dir = tmp_path / "not-a-directory"
    invalid_lock_dir.write_text("occupied", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unsafe image inference lock"):
        with module.image_inference_slot(lock_dir=invalid_lock_dir):
            raise AssertionError("invalid lock directory was accepted")

    invalid_lock_dir.unlink()
    release = Event()
    entered = [Event(), Event()]

    def run(index: int) -> None:
        with module.image_inference_slot(lock_dir=invalid_lock_dir):
            entered[index].set()
            release.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, index) for index in range(2)]
        both_slots_reusable = (
            entered[0].wait(timeout=1)
            and entered[1].wait(timeout=1)
        )
        release.set()
        for future in futures:
            future.result(timeout=2)

    assert both_slots_reusable is True


def test_limiter_documents_single_host_scope_and_multi_host_boundary() -> None:
    module = _subject()

    assert module.PROCESS_IMAGE_INFERENCE_LIMIT == 2
    assert module.IMAGE_INFERENCE_LIMIT_SCOPE == "single_host"
    assert module.__doc__ is not None
    documentation = module.__doc__.lower()
    assert "single host" in documentation
    assert "shared lock directory" in documentation
    assert "linux" in documentation
    assert "macos" in documentation
    assert "same os account" in documentation
    assert "multi-host" in documentation
    assert "isolated filesystems" in documentation
