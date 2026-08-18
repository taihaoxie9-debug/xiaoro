"""Build the locked Slice 2.0 Guide image index."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable, Literal, Sequence
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.guide.adapters.image.index_build import ImageIndexBuildService
from app.guide.adapters.image.index_source_preflight import (
    preflight_image_sources,
)
from app.guide.adapters.image.local_numpy_index import (
    LocalNumpyImageIndex,
    OpenClipNumpyArtifactBuilder,
    verify_image_index_acceptance,
)
from app.guide.adapters.image.openclip_adapter import (
    OpenClipImageEncoder,
    OpenClipModelSpec,
)
from app.guide.retrieval.image_contracts import (
    ImageIndexBuildInput,
    ImageIndexManifest,
    ImageIndexRuntimeLock,
    Sha256,
)


DEFAULT_ARTIFACT_RELATIVE_PATH = (
    "data/guide_image_index/"
    "openclip_vit_b32_laion2b_s34b_b79k_v1"
)
SOURCE_MANIFEST_RELATIVE_PATH = (
    "data/canonical/seed_product_images_v1_manifest.json"
)
SOURCE_PRODUCTS_RELATIVE_PATH = (
    "data/canonical/seed_product_images_v1.jsonl"
)
RELEVANT_SOURCE_PATHS = (
    "app/__init__.py",
    "app/guide/__init__.py",
    "app/guide/adapters/__init__.py",
    "app/guide/adapters/image/__init__.py",
    "app/guide/adapters/image/index_build.py",
    "app/guide/adapters/image/index_runtime.py",
    "app/guide/adapters/image/index_source_preflight.py",
    "app/guide/adapters/image/inference_limiter.py",
    "app/guide/adapters/image/local_numpy_index.py",
    "app/guide/adapters/image/ocr_observation.py",
    "app/guide/adapters/image/openclip_adapter.py",
    "app/guide/adapters/image/safe_image_input.py",
    "app/guide/retrieval/__init__.py",
    "app/guide/retrieval/contracts.py",
    "app/guide/retrieval/image_contracts.py",
    "app/guide/retrieval/ports.py",
    "app/guide/session_contract.py",
    "app/guide/understanding/__init__.py",
    "app/guide/understanding/contracts.py",
    "app/guide/understanding/image_contracts.py",
    "app/guide/understanding/image_identity.py",
    "app/guide/understanding/ports.py",
    SOURCE_MANIFEST_RELATIVE_PATH,
    SOURCE_PRODUCTS_RELATIVE_PATH,
    "docs/audits/slice2.0/model_gate.json",
    "requirements-guide-image.txt",
    "tools/guide_gates/__init__.py",
    "tools/guide_gates/build_guide_image_index.py",
)
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x00000004


class Task11SourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    git_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_status: Literal["clean", "dirty"]
    relevant_source_sha256: Sha256


class Task11BuildReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["slice2-task11-build-v2"] = (
        "slice2-task11-build-v2"
    )
    git_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_status: Literal["clean", "dirty"]
    relevant_source_sha256: Sha256
    device: Literal["mps", "cpu"]
    batch_size: int = Field(gt=0)
    artifact_path: str = Field(min_length=1)
    source_count: int = Field(gt=0)
    vector_count: int = Field(gt=0)
    vector_dimension: int = Field(gt=0)
    model_name: str = Field(min_length=1)
    weights_sha256: Sha256
    preprocessing_version: str = Field(min_length=1)
    manifest_sha256: Sha256
    manifest_file_sha256: Sha256
    index_sha256: Sha256
    vector_sha256_aggregate: Sha256
    build_seconds: float = Field(ge=0.0)
    repeat_build_seconds: float = Field(ge=0.0)
    repeat_manifest_sha256: Sha256
    repeat_index_sha256: Sha256
    reproducible: bool
    original_top1_hits: int = Field(ge=0)
    transformed_top3_hits: int = Field(ge=0)
    original_top1_rate: float = Field(ge=0.0, le=1.0)
    transformed_top3_rate: float = Field(ge=0.0, le=1.0)
    ordering_stable: bool
    acceptance_passed: bool


class Task11CliReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["slice2-task11-cli-v2"] = (
        "slice2-task11-cli-v2"
    )
    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: Literal["in_progress", "accepted", "failed"]
    code: str = Field(min_length=1)
    acceptance_passed: bool
    source_provenance: Task11SourceProvenance | None = None
    build_report: Task11BuildReport | None = None


class Task11BuildError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def build_task11_index(
    *,
    repo_root: str | Path,
    weight_path: str | Path,
    output_dir: str | Path,
    repeat_output_dir: str | Path,
    device: Literal["mps", "cpu"] = "mps",
    batch_size: int = 16,
    _on_completed: Callable[[Task11BuildReport], None] | None = None,
) -> Task11BuildReport:
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise Task11BuildError("repo_root_invalid")
    primary_path = Path(output_dir).resolve()
    repeat_path = Path(repeat_output_dir).resolve()
    if primary_path == repeat_path:
        raise Task11BuildError("repeat_output_must_differ")
    if (
        primary_path in repeat_path.parents
        or repeat_path in primary_path.parents
    ):
        raise Task11BuildError("output_paths_overlap")

    source_manifest_path = root / SOURCE_MANIFEST_RELATIVE_PATH
    source_products_path = root / SOURCE_PRODUCTS_RELATIVE_PATH
    source_provenance = _relevant_source_provenance(root)
    source_report = preflight_image_sources(
        manifest_path=source_manifest_path,
        products_path=source_products_path,
        source_root=root,
    )
    encoder = OpenClipImageEncoder(
        OpenClipModelSpec(
            weight_path=Path(weight_path),
            device=device,
        )
    )
    attempts: list[tuple[Path, Path]] = []
    promoted: tuple[tuple[Path, os.stat_result], ...] = ()
    cleanup_completed = False
    rollback_failed = False
    try:
        primary_attempt = _create_private_attempt(primary_path)
        attempts.append((primary_attempt, primary_path))
        repeat_attempt = _create_private_attempt(repeat_path)
        attempts.append((repeat_attempt, repeat_path))
        primary_artifact = primary_attempt / "artifact"
        repeat_artifact = repeat_attempt / "artifact"

        primary_manifest, build_seconds = _build_once(
            root=root,
            source_manifest_path=source_manifest_path,
            source_products_path=source_products_path,
            output_dir=primary_artifact,
            encoder=encoder,
            batch_size=batch_size,
        )
        repeat_manifest, repeat_build_seconds = _build_once(
            root=root,
            source_manifest_path=source_manifest_path,
            source_products_path=source_products_path,
            output_dir=repeat_artifact,
            encoder=encoder,
            batch_size=batch_size,
        )

        primary_vector_sha = _vector_sha_aggregate(primary_manifest)
        repeat_vector_sha = _vector_sha_aggregate(repeat_manifest)
        reproducible = (
            primary_manifest.manifest_sha256
            == repeat_manifest.manifest_sha256
            and primary_manifest.index_sha256
            == repeat_manifest.index_sha256
            and primary_vector_sha == repeat_vector_sha
        )
        runtime_lock = ImageIndexRuntimeLock(
            manifest_sha256=primary_manifest.manifest_sha256,
            model_name=primary_manifest.model_name,
            weights_sha256=primary_manifest.weights_sha256,
            preprocessing_version=(
                primary_manifest.preprocessing_version
            ),
            vector_dimension=primary_manifest.vector_dimension,
            index_sha256=primary_manifest.index_sha256,
        )
        index = LocalNumpyImageIndex(
            manifest_path=primary_artifact / "manifest.json",
            source_root=root,
            artifact_root=primary_artifact,
            runtime_lock=runtime_lock,
            encoder=encoder,
        )
        acceptance = verify_image_index_acceptance(
            index=index,
            sources=source_report.sources,
            source_root=root,
        )
        acceptance_passed = bool(
            reproducible
            and acceptance.source_count == 103
            and acceptance.original_top1_hits == 103
            and acceptance.transformed_top3_hits == 103
            and acceptance.ordering_stable
        )
        final_provenance = _relevant_source_provenance(root)
        if final_provenance != source_provenance:
            raise Task11BuildError("relevant_source_changed")
        model_lock = encoder.model_lock
        report = Task11BuildReport(
            git_head=source_provenance.git_head,
            source_status=source_provenance.source_status,
            relevant_source_sha256=(
                source_provenance.relevant_source_sha256
            ),
            device=device,
            batch_size=batch_size,
            artifact_path=_display_path(root, primary_path),
            source_count=len(source_report.sources),
            vector_count=len(primary_manifest.entries),
            vector_dimension=primary_manifest.vector_dimension,
            model_name=model_lock.model_name,
            weights_sha256=model_lock.weights_sha256,
            preprocessing_version=model_lock.preprocessing_version,
            manifest_sha256=primary_manifest.manifest_sha256,
            manifest_file_sha256=_file_sha256(
                primary_artifact / "manifest.json"
            ),
            index_sha256=primary_manifest.index_sha256,
            vector_sha256_aggregate=primary_vector_sha,
            build_seconds=build_seconds,
            repeat_build_seconds=repeat_build_seconds,
            repeat_manifest_sha256=repeat_manifest.manifest_sha256,
            repeat_index_sha256=repeat_manifest.index_sha256,
            reproducible=reproducible,
            original_top1_hits=acceptance.original_top1_hits,
            transformed_top3_hits=acceptance.transformed_top3_hits,
            original_top1_rate=acceptance.original_top1_rate,
            transformed_top3_rate=acceptance.transformed_top3_rate,
            ordering_stable=acceptance.ordering_stable,
            acceptance_passed=acceptance_passed,
        )
        if acceptance_passed:
            promoted = _promote_artifacts(
                (
                    (primary_artifact, primary_path),
                    (repeat_artifact, repeat_path),
                )
            )
        _cleanup_private_attempts(attempts)
        cleanup_completed = True
        if _on_completed is not None:
            _on_completed(report)
        return report
    except BaseException as exc:
        if (
            isinstance(exc, Task11BuildError)
            and exc.code == "artifact_rollback_failed"
        ):
            rollback_failed = True
        if promoted:
            try:
                _rollback_promoted_artifacts(promoted)
            except BaseException:
                rollback_failed = True
                raise
        raise
    finally:
        if not cleanup_completed:
            try:
                _cleanup_private_attempts(attempts)
            except BaseException:
                if not rollback_failed:
                    raise


def _build_once(
    *,
    root: Path,
    source_manifest_path: Path,
    source_products_path: Path,
    output_dir: Path,
    encoder: OpenClipImageEncoder,
    batch_size: int,
) -> tuple[ImageIndexManifest, float]:
    started = time.perf_counter()
    result = ImageIndexBuildService(
        artifact_builder=OpenClipNumpyArtifactBuilder(
            source_root=root,
            encoder=encoder,
            batch_size=batch_size,
        )
    ).build(
        ImageIndexBuildInput(
            source_manifest_path=source_manifest_path,
            source_products_path=source_products_path,
            source_root=root,
            output_dir=output_dir,
            model=encoder.model_lock,
        )
    )
    elapsed = time.perf_counter() - started
    if result.status != "built":
        raise Task11BuildError(result.code)
    manifest = ImageIndexManifest.model_validate_json(
        result.manifest_path.read_text(encoding="utf-8")
    )
    return manifest, elapsed


def _vector_sha_aggregate(manifest: ImageIndexManifest) -> str:
    payload = "\n".join(
        f"{entry.product_id}\t{entry.vector_sha256}"
        for entry in manifest.entries
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _create_private_attempt(final_path: Path) -> Path:
    parent = final_path.parent
    if not final_path.name:
        raise Task11BuildError("output_path_invalid")
    if not parent.is_dir():
        raise Task11BuildError("output_parent_missing")
    if final_path.exists():
        raise Task11BuildError("output_already_exists")
    return Path(
        tempfile.mkdtemp(
            prefix=f".{final_path.name}.task11-attempt-",
            dir=parent,
        )
    )


def _cleanup_private_attempts(
    attempts: Sequence[tuple[Path, Path]],
) -> None:
    cleanup_failed = False
    for attempt_path, final_path in reversed(attempts):
        if not attempt_path.exists():
            continue
        expected_prefix = f".{final_path.name}.task11-attempt-"
        try:
            entry = attempt_path.lstat()
            if (
                attempt_path.parent != final_path.parent
                or not attempt_path.name.startswith(expected_prefix)
                or not stat.S_ISDIR(entry.st_mode)
                or entry.st_uid != os.geteuid()
            ):
                raise Task11BuildError("attempt_cleanup_boundary_invalid")
            shutil.rmtree(attempt_path)
        except (OSError, Task11BuildError):
            cleanup_failed = True
    if cleanup_failed:
        raise Task11BuildError("attempt_cleanup_failed")


def _promote_artifacts(
    artifacts: Sequence[tuple[Path, Path]],
) -> tuple[tuple[Path, os.stat_result], ...]:
    promoted: list[tuple[Path, os.stat_result]] = []
    try:
        for private_path, final_path in artifacts:
            if final_path.exists():
                raise Task11BuildError("output_already_exists")
            private_stat = private_path.lstat()
            if (
                private_path.parent.parent != final_path.parent
                or not stat.S_ISDIR(private_stat.st_mode)
                or private_stat.st_uid != os.geteuid()
            ):
                raise Task11BuildError("artifact_promotion_boundary_invalid")
            _rename_no_replace(private_path, final_path)
            promoted.append((final_path, private_stat))
            final_stat = final_path.lstat()
            if not os.path.samestat(private_stat, final_stat):
                raise Task11BuildError("artifact_promotion_identity_changed")
    except Exception:
        _rollback_promoted_artifacts(promoted)
        raise
    return tuple(promoted)


def _rename_no_replace(private_path: Path, final_path: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        try:
            rename = libc.renamex_np
        except AttributeError as exc:
            raise Task11BuildError(
                "artifact_promotion_no_clobber_unsupported"
            ) from exc
        rename.argtypes = (
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            os.fsencode(private_path),
            os.fsencode(final_path),
            _RENAME_EXCL,
        )
    elif sys.platform.startswith("linux"):
        try:
            rename = libc.renameat2
        except AttributeError as exc:
            raise Task11BuildError(
                "artifact_promotion_no_clobber_unsupported"
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
            _AT_FDCWD,
            os.fsencode(private_path),
            _AT_FDCWD,
            os.fsencode(final_path),
            _RENAME_NOREPLACE,
        )
    elif os.name == "nt":
        try:
            os.rename(private_path, final_path)
        except OSError as exc:
            if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise Task11BuildError("output_already_exists") from exc
            raise
        return
    else:
        raise Task11BuildError(
            "artifact_promotion_no_clobber_unsupported"
        )

    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise Task11BuildError("output_already_exists")
    raise OSError(
        error_number,
        os.strerror(error_number),
        str(final_path),
    )


def _rollback_promoted_artifacts(
    promoted: Sequence[tuple[Path, os.stat_result]],
) -> None:
    rollback_failed = False
    for final_path, expected_stat in reversed(promoted):
        try:
            actual_stat = final_path.lstat()
            if not os.path.samestat(expected_stat, actual_stat):
                raise Task11BuildError(
                    "artifact_rollback_identity_changed"
                )
            shutil.rmtree(final_path)
        except (OSError, Task11BuildError):
            rollback_failed = True
    if rollback_failed:
        raise Task11BuildError("artifact_rollback_failed")


def _relevant_source_provenance(
    root: Path,
    *,
    relevant_paths: Sequence[str] = RELEVANT_SOURCE_PATHS,
) -> Task11SourceProvenance:
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise Task11BuildError("repo_root_invalid")
    normalized_paths = tuple(sorted(relevant_paths))
    if not normalized_paths or len(set(normalized_paths)) != len(
        normalized_paths
    ):
        raise Task11BuildError("relevant_source_paths_invalid")

    digest = hashlib.sha256()
    head = _git_head(resolved_root)
    dirty = False
    for relative_path in normalized_paths:
        relative = Path(relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != relative_path
        ):
            raise Task11BuildError("relevant_source_path_invalid")
        try:
            source_path = (resolved_root / relative).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise Task11BuildError("relevant_source_unavailable") from exc
        if (
            not source_path.is_relative_to(resolved_root)
            or not source_path.is_file()
        ):
            raise Task11BuildError("relevant_source_boundary_invalid")
        content = source_path.read_bytes()
        path_bytes = relative_path.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)

        try:
            committed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(resolved_root),
                    "show",
                    f"{head}:{relative_path}",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise Task11BuildError("git_head_unavailable") from exc
        if committed.returncode != 0 or committed.stdout != content:
            dirty = True

    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(resolved_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                *normalized_paths,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Task11BuildError("git_status_unavailable") from exc
    dirty = dirty or bool(status.stdout)
    return Task11SourceProvenance(
        git_head=head,
        source_status="dirty" if dirty else "clean",
        relevant_source_sha256=digest.hexdigest(),
    )


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Task11BuildError("git_head_unavailable") from exc


def _display_path(root: Path, path: Path) -> str:
    if path.is_relative_to(root):
        return path.relative_to(root).as_posix()
    return str(path)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_report(path: Path, report: BaseModel) -> None:
    if not path.is_absolute() or not path.parent.is_dir():
        raise Task11BuildError("report_parent_invalid")
    content = (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _invalidate_stale_report(path: Path) -> None:
    if not path.is_absolute() or not path.parent.is_dir():
        raise Task11BuildError("report_parent_invalid")
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(entry.st_mode):
        raise Task11BuildError("report_path_invalid")
    path.unlink()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build and verify the locked Slice 2.0 OpenCLIP NumPy index."
        )
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--weight-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--repeat-output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument(
        "--device",
        choices=("mps", "cpu"),
        default="mps",
    )
    parser.add_argument("--batch-size", type=int, default=16)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    attempt_id = uuid.uuid4().hex
    report_path = args.report_path.resolve()
    provenance: Task11SourceProvenance | None = None
    terminal_report_written = False

    def write_terminal_report(report: Task11BuildReport) -> None:
        nonlocal terminal_report_written
        terminal_report = Task11CliReport(
            attempt_id=attempt_id,
            status="accepted" if report.acceptance_passed else "failed",
            code=(
                "accepted"
                if report.acceptance_passed
                else "acceptance_failed"
            ),
            acceptance_passed=report.acceptance_passed,
            source_provenance=Task11SourceProvenance(
                git_head=report.git_head,
                source_status=report.source_status,
                relevant_source_sha256=(
                    report.relevant_source_sha256
                ),
            ),
            build_report=report,
        )
        _write_report(report_path, terminal_report)
        terminal_report_written = True

    try:
        _invalidate_stale_report(report_path)
        _write_report(
            report_path,
            Task11CliReport(
                attempt_id=attempt_id,
                status="in_progress",
                code="build_in_progress",
                acceptance_passed=False,
            ),
        )
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        print(
            json.dumps(
                {"status": "error", "code": code},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    try:
        root = Path(args.repo_root).resolve(strict=True)
        provenance = _relevant_source_provenance(root)
        report = build_task11_index(
            repo_root=root,
            weight_path=args.weight_path,
            output_dir=args.output_dir,
            repeat_output_dir=args.repeat_output_dir,
            device=args.device,
            batch_size=args.batch_size,
            _on_completed=write_terminal_report,
        )
        if not terminal_report_written:
            write_terminal_report(report)
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        failure_report = Task11CliReport(
            attempt_id=attempt_id,
            status="failed",
            code=str(code),
            acceptance_passed=False,
            source_provenance=provenance,
        )
        try:
            _write_report(report_path, failure_report)
        except Exception as report_exc:
            code = (
                f"{code}:failure_report_"
                f"{getattr(report_exc, 'code', type(report_exc).__name__)}"
            )
        print(
            json.dumps(
                {"status": "error", "code": code},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report.acceptance_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
