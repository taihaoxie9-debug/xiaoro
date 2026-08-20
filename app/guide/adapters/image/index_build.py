from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

from app.guide.adapters.image.index_source_preflight import (
    ImageSourcePreflightError,
    preflight_image_sources,
)
from app.guide.retrieval.image_contracts import (
    ApprovedImageModelLock,
    ImageIndexBuildInput,
    ImageIndexBuildNoGo,
    ImageIndexBuildResult,
    ImageIndexBuildSuccess,
    ImageIndexManifest,
    ImageSourcePreflightReport,
    UnapprovedImageModel,
)


MANIFEST_FILE_NAME = "manifest.json"
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x00000004


class _OutputAlreadyExistsError(RuntimeError):
    pass


class ImageIndexArtifactBuilderPort(Protocol):
    def build(
        self,
        *,
        source_report: ImageSourcePreflightReport,
        model: ApprovedImageModelLock,
        staging_dir: Path,
    ) -> ImageIndexManifest: ...


def compute_image_index_manifest_sha256(
    manifest: ImageIndexManifest,
) -> str:
    payload = manifest.model_dump(mode="json")
    payload.pop("manifest_sha256")
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ImageIndexBuildService:
    def __init__(
        self,
        *,
        artifact_builder: ImageIndexArtifactBuilderPort | None = None,
        expected_source_count: int = 103,
    ) -> None:
        if expected_source_count < 1:
            raise ValueError("expected_source_count must be positive")
        self._artifact_builder = artifact_builder
        self._expected_source_count = expected_source_count

    def build(
        self,
        request: ImageIndexBuildInput,
    ) -> ImageIndexBuildResult:
        try:
            source_report = preflight_image_sources(
                manifest_path=request.source_manifest_path,
                products_path=request.source_products_path,
                source_root=request.source_root,
                expected_count=self._expected_source_count,
            )
        except ImageSourcePreflightError as exc:
            return ImageIndexBuildNoGo(
                code="source_preflight_failed",
                detail=str(exc),
                source_count=0,
            )

        source_count = len(source_report.sources)
        if request.model is None:
            return ImageIndexBuildNoGo(
                code="model_lock_missing",
                detail=(
                    "NO-GO: an approved model and locked weights SHA-256 "
                    "are required"
                ),
                source_count=source_count,
            )
        if isinstance(request.model, UnapprovedImageModel):
            return ImageIndexBuildNoGo(
                code="model_not_approved",
                detail=f"NO-GO: {request.model.reason}",
                source_count=source_count,
            )
        if self._artifact_builder is None:
            return ImageIndexBuildNoGo(
                code="vector_builder_unavailable",
                detail=(
                    "NO-GO: Task 8 provides no model or vector builder"
                ),
                source_count=source_count,
            )

        output_dir = request.output_dir.resolve()
        output_parent = output_dir.parent
        if output_dir.exists():
            return ImageIndexBuildNoGo(
                code="output_already_exists",
                detail="NO-GO: image index output already exists",
                source_count=source_count,
            )
        if not output_parent.is_dir():
            return ImageIndexBuildNoGo(
                code="output_parent_missing",
                detail="NO-GO: image index output parent must exist",
                source_count=source_count,
            )

        staging_dir: Path | None = None
        staging_prefix = f".{output_dir.name}.staging-"
        try:
            staging_dir = Path(
                tempfile.mkdtemp(
                    prefix=staging_prefix,
                    dir=output_parent,
                )
            )
            _validate_staging_directory(
                staging_dir=staging_dir,
                output_parent=output_parent,
                expected_prefix=staging_prefix,
            )
            manifest = self._artifact_builder.build(
                source_report=source_report,
                model=request.model,
                staging_dir=staging_dir,
            )
            self._validate_staged_artifacts(
                staging_dir=staging_dir,
                manifest=manifest,
                source_report=source_report,
                model=request.model,
            )
            manifest_path = staging_dir / MANIFEST_FILE_NAME
            manifest_path.write_text(
                _canonical_manifest_json(manifest) + "\n",
                encoding="utf-8",
            )
            with _cooperative_publish_lock(
                output_dir=output_dir,
            ) as output_parent_descriptor:
                if _directory_entry_exists(
                    directory_descriptor=output_parent_descriptor,
                    name=output_dir.name,
                ):
                    raise _OutputAlreadyExistsError
                _rename_directory_no_replace(
                    staging_dir,
                    output_dir,
                )
            staging_dir = None
        except Exception as exc:
            if staging_dir is not None:
                try:
                    _cleanup_staging_directory(
                        staging_dir=staging_dir,
                        output_parent=output_parent,
                        expected_prefix=staging_prefix,
                    )
                except Exception as cleanup_exc:
                    return ImageIndexBuildNoGo(
                        code="index_cleanup_failed",
                        detail=(
                            "NO-GO: image index build failed and staging "
                            "cleanup failed "
                            f"(build={type(exc).__name__}, "
                            f"cleanup={type(cleanup_exc).__name__}); "
                            f"residual_staging_dir={staging_dir}"
                        ),
                        source_count=source_count,
                    )
            if isinstance(exc, _OutputAlreadyExistsError):
                return ImageIndexBuildNoGo(
                    code="output_already_exists",
                    detail="NO-GO: image index output already exists",
                    source_count=source_count,
                )
            return ImageIndexBuildNoGo(
                code="index_build_failed",
                detail=(
                    "NO-GO: image index build failed atomically "
                    f"({type(exc).__name__})"
                ),
                source_count=source_count,
            )

        return ImageIndexBuildSuccess(
            output_dir=output_dir,
            manifest_path=output_dir / MANIFEST_FILE_NAME,
            index_path=output_dir / manifest.index_path,
            manifest_sha256=manifest.manifest_sha256,
            index_sha256=manifest.index_sha256,
            product_ids=tuple(
                source.product_id for source in source_report.sources
            ),
        )

    @staticmethod
    def _validate_staged_artifacts(
        *,
        staging_dir: Path,
        manifest: ImageIndexManifest,
        source_report: ImageSourcePreflightReport,
        model: ApprovedImageModelLock,
    ) -> None:
        actual_manifest_sha256 = compute_image_index_manifest_sha256(
            manifest
        )
        if actual_manifest_sha256 != manifest.manifest_sha256:
            raise ValueError("image index manifest SHA-256 mismatch")

        expected_model = (
            model.model_name,
            model.weights_sha256,
            model.preprocessing_version,
            model.vector_dimension,
        )
        actual_model = (
            manifest.model_name,
            manifest.weights_sha256,
            manifest.preprocessing_version,
            manifest.vector_dimension,
        )
        if actual_model != expected_model:
            raise ValueError("image index model lock mismatch")

        expected_source_metadata = (
            source_report.source_manifest_path,
            source_report.source_manifest_sha256,
            source_report.source_products_path,
            source_report.source_products_sha256,
        )
        actual_source_metadata = (
            manifest.source_manifest_path,
            manifest.source_manifest_sha256,
            manifest.source_products_path,
            manifest.source_products_sha256,
        )
        if actual_source_metadata != expected_source_metadata:
            raise ValueError("image index source metadata mismatch")

        if len(manifest.entries) != len(source_report.sources):
            raise ValueError("image index source count mismatch")
        declared_files = {manifest.index_path}
        if manifest.index_path == MANIFEST_FILE_NAME:
            raise ValueError("index path collides with manifest path")
        for entry, source in zip(
            manifest.entries,
            source_report.sources,
            strict=True,
        ):
            expected_source = (
                source.product_id,
                source.source_path,
                source.source_bytes,
                source.source_sha256,
            )
            actual_source = (
                entry.product_id,
                entry.source_path,
                entry.source_bytes,
                entry.source_sha256,
            )
            if actual_source != expected_source:
                raise ValueError("image index source entry mismatch")
            if entry.vector_path == manifest.index_path:
                raise ValueError("vector path collides with index path")
            if entry.vector_path == MANIFEST_FILE_NAME:
                raise ValueError("vector path collides with manifest path")
            declared_files.add(entry.vector_path)
            _validate_staged_file(
                staging_dir=staging_dir,
                relative_path=entry.vector_path,
                expected_sha256=entry.vector_sha256,
                label=f"vector for product_id {entry.product_id}",
            )

        _validate_staged_file(
            staging_dir=staging_dir,
            relative_path=manifest.index_path,
            expected_sha256=manifest.index_sha256,
            label="image index",
        )
        actual_files = {
            path.relative_to(staging_dir).as_posix()
            for path in staging_dir.rglob("*")
            if path.is_file()
        }
        if actual_files != declared_files:
            raise ValueError("staging directory has undeclared artifacts")


def _directory_entry_exists(
    *,
    directory_descriptor: int,
    name: str,
) -> bool:
    try:
        os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False
    return True


def _rename_directory_no_replace(
    source_dir: Path,
    output_dir: Path,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        try:
            rename = libc.renamex_np
        except AttributeError as exc:
            raise RuntimeError(
                "atomic no-clobber publication is unavailable"
            ) from exc
        rename.argtypes = (
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            os.fsencode(source_dir),
            os.fsencode(output_dir),
            _RENAME_EXCL,
        )
    elif sys.platform.startswith("linux"):
        try:
            rename = libc.renameat2
        except AttributeError as exc:
            raise RuntimeError(
                "atomic no-clobber publication is unavailable"
            ) from exc
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            -100,
            os.fsencode(source_dir),
            -100,
            os.fsencode(output_dir),
            _RENAME_NOREPLACE,
        )
    else:
        raise RuntimeError(
            "atomic no-clobber publication is unavailable"
        )

    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise _OutputAlreadyExistsError
    raise OSError(
        error_number,
        os.strerror(error_number),
        str(output_dir),
    )


@contextmanager
def _cooperative_publish_lock(
    *,
    output_dir: Path,
) -> Iterator[int]:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if no_follow == 0 or directory == 0:
        raise RuntimeError("secure image index publication is unavailable")

    output_parent_descriptor = os.open(
        output_dir.parent,
        os.O_RDONLY
        | directory
        | no_follow
        | getattr(os, "O_CLOEXEC", 0),
    )
    lock_name = f".{output_dir.name}.publish.lock"
    lock_descriptor: int | None = None
    lock_acquired = False
    try:
        lock_descriptor = os.open(
            lock_name,
            os.O_RDWR
            | os.O_CREAT
            | no_follow
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=output_parent_descriptor,
        )
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        lock_acquired = True
        entry_stat = os.stat(
            lock_name,
            dir_fd=output_parent_descriptor,
            follow_symlinks=False,
        )
        descriptor_stat = os.fstat(lock_descriptor)
        if (
            not stat.S_ISREG(entry_stat.st_mode)
            or not stat.S_ISREG(descriptor_stat.st_mode)
            or not os.path.samestat(entry_stat, descriptor_stat)
            or descriptor_stat.st_uid != os.geteuid()
        ):
            raise ValueError("unsafe image index publish lock")
        yield output_parent_descriptor
    finally:
        try:
            if lock_descriptor is not None:
                try:
                    if lock_acquired:
                        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(lock_descriptor)
        finally:
            os.close(output_parent_descriptor)


def _validate_staged_file(
    *,
    staging_dir: Path,
    relative_path: str,
    expected_sha256: str,
    label: str,
) -> None:
    path = (staging_dir / relative_path).resolve()
    if not path.is_relative_to(staging_dir):
        raise ValueError(f"{label} escapes staging directory")
    if not path.is_file():
        raise ValueError(f"missing {label}")
    content = path.read_bytes()
    if not content:
        raise ValueError(f"{label} must not be empty")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError(f"{label} SHA-256 mismatch")


def _canonical_manifest_json(manifest: ImageIndexManifest) -> str:
    return json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_staging_directory(
    *,
    staging_dir: Path,
    output_parent: Path,
    expected_prefix: str,
) -> None:
    if (
        not staging_dir.is_absolute()
        or staging_dir.parent != output_parent
        or not staging_dir.name.startswith(expected_prefix)
    ):
        raise ValueError("staging directory is outside output boundary")

    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if no_follow == 0 or directory == 0:
        raise RuntimeError("secure staging cleanup is unavailable")

    parent_descriptor = os.open(
        output_parent,
        os.O_RDONLY | directory | no_follow | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        entry_stat = os.stat(
            staging_dir.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        staging_descriptor = os.open(
            staging_dir.name,
            os.O_RDONLY
            | directory
            | no_follow
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        try:
            descriptor_stat = os.fstat(staging_descriptor)
            if (
                not stat.S_ISDIR(entry_stat.st_mode)
                or not stat.S_ISDIR(descriptor_stat.st_mode)
                or not os.path.samestat(entry_stat, descriptor_stat)
                or descriptor_stat.st_uid != os.geteuid()
            ):
                raise ValueError("unsafe staging directory")
        finally:
            os.close(staging_descriptor)
    finally:
        os.close(parent_descriptor)


def _harden_staging_directory_permissions(
    staging_descriptor: int,
) -> None:
    os.fchmod(staging_descriptor, 0o700)
    for _, directory_names, _, directory_descriptor in os.fwalk(
        ".",
        topdown=True,
        follow_symlinks=False,
        dir_fd=staging_descriptor,
    ):
        os.fchmod(directory_descriptor, 0o700)
        for name in directory_names:
            entry_stat = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if stat.S_ISDIR(entry_stat.st_mode):
                os.chmod(
                    name,
                    0o700,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )


def _cleanup_staging_directory(
    *,
    staging_dir: Path,
    output_parent: Path,
    expected_prefix: str,
) -> None:
    _validate_staging_directory(
        staging_dir=staging_dir,
        output_parent=output_parent,
        expected_prefix=expected_prefix,
    )
    parent_descriptor = os.open(
        output_parent,
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        staging_descriptor = os.open(
            staging_dir.name,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        try:
            _harden_staging_directory_permissions(staging_descriptor)
        finally:
            os.close(staging_descriptor)

        shutil.rmtree(
            staging_dir.name,
            dir_fd=parent_descriptor,
        )
        try:
            os.stat(
                staging_dir.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        raise RuntimeError("staging directory remains after cleanup")
    finally:
        os.close(parent_descriptor)
