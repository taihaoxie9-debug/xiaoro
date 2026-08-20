from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from app.guide.adapters.image.local_numpy_index import (
    ImageIndexAcceptanceReport,
)
from app.guide.adapters.image.openclip_adapter import (
    LOCKED_ARTIFACT_MODEL_NAME,
    LOCKED_PREPROCESS_VERSION,
    LOCKED_WEIGHT_SHA256,
)
from app.guide.retrieval.image_contracts import ApprovedImageModelLock
import tools.guide_gates.build_guide_image_index as build_cli


def test_task11_build_cli_module_exists() -> None:
    spec = importlib.util.find_spec(
        "tools.guide_gates.build_guide_image_index"
    )

    assert spec is not None


def test_task11_build_cli_exports_reproducible_build_api() -> None:
    assert build_cli.DEFAULT_ARTIFACT_RELATIVE_PATH == (
        "data/guide_image_index/"
        "openclip_vit_b32_laion2b_s34b_b79k_v1"
    )
    assert {
        "Task11BuildReport",
        "build_task11_index",
        "main",
    }.issubset(vars(build_cli))


class _FakeLockedEncoder:
    model_lock = ApprovedImageModelLock(
        approval_id="slice2.0-model-gate-2026-08-08",
        model_name=LOCKED_ARTIFACT_MODEL_NAME,
        weights_sha256=LOCKED_WEIGHT_SHA256,
        preprocessing_version=LOCKED_PREPROCESS_VERSION,
        vector_dimension=512,
    )

    def __init__(self, spec) -> None:
        self.spec = spec

    def encode_paths(self, paths, *, batch_size: int) -> np.ndarray:
        matrix = np.zeros((len(paths), 512), dtype=np.float32)
        for index in range(len(paths)):
            matrix[index, index % 512] = 1.0
        return matrix

    def encode_contents(self, contents, *, batch_size: int) -> np.ndarray:
        matrix = np.zeros((len(contents), 512), dtype=np.float32)
        for index in range(len(contents)):
            matrix[index, index % 512] = 1.0
        return matrix

    def encode_bytes(self, content: bytes) -> np.ndarray:
        vector = np.zeros(512, dtype=np.float32)
        vector[0] = 1.0
        return vector


def _full_acceptance(index, sources, source_root):
    return ImageIndexAcceptanceReport(
        source_count=len(sources),
        original_top1_hits=len(sources),
        transformed_top3_hits=len(sources),
        original_top1_rate=1.0,
        transformed_top3_rate=1.0,
        ordering_stable=True,
        index_sha256=index.runtime_lock.index_sha256,
    )


def _failed_acceptance(index, sources, source_root):
    return ImageIndexAcceptanceReport(
        source_count=len(sources),
        original_top1_hits=len(sources) - 1,
        transformed_top3_hits=len(sources),
        original_top1_rate=(len(sources) - 1) / len(sources),
        transformed_top3_rate=1.0,
        ordering_stable=True,
        index_sha256=index.runtime_lock.index_sha256,
    )


def _private_attempts(parent: Path) -> list[Path]:
    return sorted(parent.glob(".*.task11-attempt-*"))


def test_build_task11_index_publishes_only_after_all_gates_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[3]
    output_dir = tmp_path / "primary"
    repeat_output_dir = tmp_path / "repeat"
    monkeypatch.setattr(
        build_cli,
        "OpenClipImageEncoder",
        _FakeLockedEncoder,
    )

    def accept_while_outputs_are_private(index, sources, source_root):
        assert not output_dir.exists()
        assert not repeat_output_dir.exists()
        return _full_acceptance(index, sources, source_root)

    monkeypatch.setattr(
        build_cli,
        "verify_image_index_acceptance",
        accept_while_outputs_are_private,
    )

    report = build_cli.build_task11_index(
        repo_root=root,
        weight_path=tmp_path / "open_clip_model.safetensors",
        output_dir=output_dir,
        repeat_output_dir=repeat_output_dir,
        device="cpu",
        batch_size=16,
    )

    assert report.source_count == 103
    assert report.vector_count == 103
    assert report.vector_dimension == 512
    assert report.original_top1_hits == 103
    assert report.transformed_top3_hits == 103
    assert report.ordering_stable
    assert report.reproducible
    assert report.acceptance_passed
    assert report.manifest_sha256 == report.repeat_manifest_sha256
    assert report.index_sha256 == report.repeat_index_sha256
    assert output_dir.is_dir()
    assert repeat_output_dir.is_dir()
    assert len(list((output_dir / "vectors").glob("*.npy"))) == 103
    assert _private_attempts(tmp_path) == []


def test_cleanup_failure_after_promotion_rolls_back_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[3]
    output_dir = tmp_path / "primary"
    repeat_output_dir = tmp_path / "repeat"
    monkeypatch.setattr(
        build_cli,
        "OpenClipImageEncoder",
        _FakeLockedEncoder,
    )
    monkeypatch.setattr(
        build_cli,
        "verify_image_index_acceptance",
        _full_acceptance,
    )
    original_cleanup = build_cli._cleanup_private_attempts
    cleanup_calls = 0

    def fail_first_cleanup_after_removal(attempts):
        nonlocal cleanup_calls
        original_cleanup(attempts)
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise build_cli.Task11BuildError("attempt_cleanup_failed")

    monkeypatch.setattr(
        build_cli,
        "_cleanup_private_attempts",
        fail_first_cleanup_after_removal,
    )

    with pytest.raises(
        build_cli.Task11BuildError,
        match="attempt_cleanup_failed",
    ):
        build_cli.build_task11_index(
            repo_root=root,
            weight_path=tmp_path / "open_clip_model.safetensors",
            output_dir=output_dir,
            repeat_output_dir=repeat_output_dir,
            device="cpu",
            batch_size=16,
        )

    assert not output_dir.exists()
    assert not repeat_output_dir.exists()
    retry_report = build_cli.build_task11_index(
        repo_root=root,
        weight_path=tmp_path / "open_clip_model.safetensors",
        output_dir=output_dir,
        repeat_output_dir=repeat_output_dir,
        device="cpu",
        batch_size=16,
    )
    assert retry_report.acceptance_passed
    assert output_dir.is_dir()
    assert repeat_output_dir.is_dir()
    assert _private_attempts(tmp_path) == []


def test_persistent_cleanup_failure_does_not_mask_rollback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[3]
    cleanup_calls = 0
    rollback_calls = 0
    monkeypatch.setattr(
        build_cli,
        "OpenClipImageEncoder",
        _FakeLockedEncoder,
    )
    monkeypatch.setattr(
        build_cli,
        "verify_image_index_acceptance",
        _full_acceptance,
    )

    def fail_cleanup(attempts) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise build_cli.Task11BuildError("attempt_cleanup_failed")

    def fail_rollback(promoted) -> None:
        nonlocal rollback_calls
        rollback_calls += 1
        raise build_cli.Task11BuildError("artifact_rollback_failed")

    monkeypatch.setattr(
        build_cli,
        "_cleanup_private_attempts",
        fail_cleanup,
    )
    monkeypatch.setattr(
        build_cli,
        "_rollback_promoted_artifacts",
        fail_rollback,
    )

    with pytest.raises(build_cli.Task11BuildError) as raised:
        build_cli.build_task11_index(
            repo_root=root,
            weight_path=tmp_path / "open_clip_model.safetensors",
            output_dir=tmp_path / "primary",
            repeat_output_dir=tmp_path / "repeat",
            device="cpu",
            batch_size=16,
        )

    assert raised.value.code == "artifact_rollback_failed"
    assert isinstance(
        raised.value.__context__,
        build_cli.Task11BuildError,
    )
    assert raised.value.__context__.code == "attempt_cleanup_failed"
    assert cleanup_calls == 2
    assert rollback_calls == 1


def test_partial_promotion_rollback_failure_survives_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[3]
    monkeypatch.setattr(
        build_cli,
        "OpenClipImageEncoder",
        _FakeLockedEncoder,
    )
    monkeypatch.setattr(
        build_cli,
        "verify_image_index_acceptance",
        _full_acceptance,
    )

    def fail_partial_promotion(artifacts):
        raise build_cli.Task11BuildError("artifact_rollback_failed")

    def fail_cleanup(attempts) -> None:
        raise build_cli.Task11BuildError("attempt_cleanup_failed")

    monkeypatch.setattr(
        build_cli,
        "_promote_artifacts",
        fail_partial_promotion,
    )
    monkeypatch.setattr(
        build_cli,
        "_cleanup_private_attempts",
        fail_cleanup,
    )

    with pytest.raises(build_cli.Task11BuildError) as raised:
        build_cli.build_task11_index(
            repo_root=root,
            weight_path=tmp_path / "open_clip_model.safetensors",
            output_dir=tmp_path / "primary",
            repeat_output_dir=tmp_path / "repeat",
            device="cpu",
            batch_size=16,
        )

    assert raised.value.code == "artifact_rollback_failed"


@pytest.mark.parametrize(
    "failure_mode",
    ("acceptance", "reproducibility"),
)
def test_failed_gate_cleans_attempts_without_publishing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    root = Path(__file__).resolve().parents[3]
    output_dir = tmp_path / "primary"
    repeat_output_dir = tmp_path / "repeat"
    monkeypatch.setattr(
        build_cli,
        "OpenClipImageEncoder",
        _FakeLockedEncoder,
    )
    monkeypatch.setattr(
        build_cli,
        "verify_image_index_acceptance",
        (
            _failed_acceptance
            if failure_mode == "acceptance"
            else _full_acceptance
        ),
    )
    if failure_mode == "reproducibility":
        vector_digests = iter(("1" * 64, "2" * 64))
        monkeypatch.setattr(
            build_cli,
            "_vector_sha_aggregate",
            lambda manifest: next(vector_digests),
        )

    report = build_cli.build_task11_index(
        repo_root=root,
        weight_path=tmp_path / "open_clip_model.safetensors",
        output_dir=output_dir,
        repeat_output_dir=repeat_output_dir,
        device="cpu",
        batch_size=16,
    )

    assert not report.acceptance_passed
    assert not output_dir.exists()
    assert not repeat_output_dir.exists()
    assert _private_attempts(tmp_path) == []


def test_acceptance_exception_cleans_private_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[3]
    output_dir = tmp_path / "primary"
    repeat_output_dir = tmp_path / "repeat"
    monkeypatch.setattr(
        build_cli,
        "OpenClipImageEncoder",
        _FakeLockedEncoder,
    )

    def fail_acceptance(index, sources, source_root):
        raise RuntimeError("acceptance exploded")

    monkeypatch.setattr(
        build_cli,
        "verify_image_index_acceptance",
        fail_acceptance,
    )

    with pytest.raises(RuntimeError, match="acceptance exploded"):
        build_cli.build_task11_index(
            repo_root=root,
            weight_path=tmp_path / "open_clip_model.safetensors",
            output_dir=output_dir,
            repeat_output_dir=repeat_output_dir,
            device="cpu",
            batch_size=16,
        )

    assert not output_dir.exists()
    assert not repeat_output_dir.exists()
    assert _private_attempts(tmp_path) == []


def test_promotion_identity_failure_rolls_back_published_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / ".primary.task11-attempt-test"
    private_artifact = attempt / "artifact"
    final_artifact = tmp_path / "primary"
    private_artifact.mkdir(parents=True)
    (private_artifact / "manifest.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    identity_check_count = 0

    def reject_first_identity_check(left, right):
        nonlocal identity_check_count
        identity_check_count += 1
        return identity_check_count != 1

    monkeypatch.setattr(
        build_cli.os.path,
        "samestat",
        reject_first_identity_check,
    )

    with pytest.raises(
        build_cli.Task11BuildError,
        match="artifact_promotion_identity_changed",
    ):
        build_cli._promote_artifacts(
            ((private_artifact, final_artifact),)
        )

    assert not final_artifact.exists()


def test_promotion_does_not_clobber_output_created_after_precheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / ".primary.task11-attempt-test"
    private_artifact = attempt / "artifact"
    final_artifact = tmp_path / "primary"
    private_artifact.mkdir(parents=True)
    (private_artifact / "manifest.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    original_exists = Path.exists
    raced_stat = None

    def create_output_during_precheck(path: Path) -> bool:
        nonlocal raced_stat
        if path == final_artifact and raced_stat is None:
            final_artifact.mkdir()
            raced_stat = final_artifact.lstat()
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", create_output_during_precheck)

    with pytest.raises(
        build_cli.Task11BuildError,
        match="output_already_exists",
    ):
        build_cli._promote_artifacts(
            ((private_artifact, final_artifact),)
        )

    assert raced_stat is not None
    assert final_artifact.is_dir()
    assert final_artifact.stat().st_ino == raced_stat.st_ino
    assert list(final_artifact.iterdir()) == []


def _report(*, acceptance_passed: bool) -> build_cli.Task11BuildReport:
    return build_cli.Task11BuildReport(
        git_head="a" * 40,
        source_status="clean",
        relevant_source_sha256="f" * 64,
        device="mps",
        batch_size=16,
        artifact_path=build_cli.DEFAULT_ARTIFACT_RELATIVE_PATH,
        source_count=103,
        vector_count=103,
        vector_dimension=512,
        model_name=LOCKED_ARTIFACT_MODEL_NAME,
        weights_sha256=LOCKED_WEIGHT_SHA256,
        preprocessing_version=LOCKED_PREPROCESS_VERSION,
        manifest_sha256="b" * 64,
        manifest_file_sha256="c" * 64,
        index_sha256="d" * 64,
        vector_sha256_aggregate="e" * 64,
        build_seconds=1.25,
        repeat_build_seconds=1.20,
        repeat_manifest_sha256="b" * 64,
        repeat_index_sha256="d" * 64,
        reproducible=True,
        original_top1_hits=103 if acceptance_passed else 102,
        transformed_top3_hits=103,
        original_top1_rate=1.0 if acceptance_passed else 102 / 103,
        transformed_top3_rate=1.0,
        ordering_stable=True,
        acceptance_passed=acceptance_passed,
    )


@pytest.mark.parametrize(
    ("acceptance_passed", "expected_exit"),
    [(True, 0), (False, 1)],
)
def test_cli_writes_structured_report_and_returns_acceptance_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acceptance_passed: bool,
    expected_exit: int,
) -> None:
    report = _report(acceptance_passed=acceptance_passed)
    report_path = tmp_path / "task11-report.json"
    root = Path(__file__).resolve().parents[3]
    monkeypatch.setattr(
        build_cli,
        "build_task11_index",
        lambda **kwargs: report,
    )

    exit_code = build_cli.main(
        [
            "--repo-root",
            str(root),
            "--weight-path",
            str(tmp_path / "weight.safetensors"),
            "--output-dir",
            str(tmp_path / "output"),
            "--repeat-output-dir",
            str(tmp_path / "repeat"),
            "--report-path",
            str(report_path),
            "--device",
            "mps",
            "--batch-size",
            "16",
        ]
    )

    assert exit_code == expected_exit
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "slice2-task11-cli-v2"
    assert payload["status"] == (
        "accepted" if acceptance_passed else "failed"
    )
    assert payload["code"] == (
        "accepted" if acceptance_passed else "acceptance_failed"
    )
    assert payload["acceptance_passed"] is acceptance_passed
    assert len(payload["attempt_id"]) == 32
    assert payload["build_report"] == report.model_dump(mode="json")
    assert hashlib.sha256(report_path.read_bytes()).hexdigest()


def test_cli_exception_replaces_stale_success_with_failure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "task11-report.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "accepted",
                "attempt_id": "stale-attempt",
                "acceptance_passed": True,
            }
        ),
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[3]

    def fail_build(**kwargs):
        raise build_cli.Task11BuildError("build_exploded")

    monkeypatch.setattr(build_cli, "build_task11_index", fail_build)

    exit_code = build_cli.main(
        [
            "--repo-root",
            str(root),
            "--weight-path",
            str(tmp_path / "weight.safetensors"),
            "--output-dir",
            str(tmp_path / "output"),
            "--repeat-output-dir",
            str(tmp_path / "repeat"),
            "--report-path",
            str(report_path),
            "--device",
            "cpu",
        ]
    )

    assert exit_code == 2
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "slice2-task11-cli-v2"
    assert payload["status"] == "failed"
    assert payload["code"] == "build_exploded"
    assert payload["acceptance_passed"] is False
    assert payload["attempt_id"] != "stale-attempt"
    assert payload["build_report"] is None


def test_accepted_report_write_failure_rolls_back_for_cli_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[3]
    output_dir = tmp_path / "output"
    repeat_output_dir = tmp_path / "repeat"
    report_path = tmp_path / "task11-report.json"
    argv = [
        "--repo-root",
        str(root),
        "--weight-path",
        str(tmp_path / "weight.safetensors"),
        "--output-dir",
        str(output_dir),
        "--repeat-output-dir",
        str(repeat_output_dir),
        "--report-path",
        str(report_path),
        "--device",
        "cpu",
    ]
    monkeypatch.setattr(
        build_cli,
        "OpenClipImageEncoder",
        _FakeLockedEncoder,
    )
    monkeypatch.setattr(
        build_cli,
        "verify_image_index_acceptance",
        _full_acceptance,
    )
    original_write_report = build_cli._write_report
    accepted_write_failed = False

    def fail_first_accepted_report(path, report):
        nonlocal accepted_write_failed
        if report.status == "accepted" and not accepted_write_failed:
            accepted_write_failed = True
            raise OSError("accepted report exploded")
        original_write_report(path, report)

    monkeypatch.setattr(
        build_cli,
        "_write_report",
        fail_first_accepted_report,
    )

    assert build_cli.main(argv) == 2
    assert accepted_write_failed
    assert not output_dir.exists()
    assert not repeat_output_dir.exists()

    monkeypatch.setattr(
        build_cli,
        "_write_report",
        original_write_report,
    )
    assert build_cli.main(argv) == 0
    assert output_dir.is_dir()
    assert repeat_output_dir.is_dir()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "accepted"
    assert payload["acceptance_passed"] is True


def _run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_relevant_source_provenance_is_deterministic_and_truthful(
    tmp_path: Path,
) -> None:
    tracked = tmp_path / "tracked.py"
    untracked = tmp_path / "new.py"
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    _run_git(tmp_path, "init", "-q")
    _run_git(tmp_path, "add", "tracked.py")
    _run_git(
        tmp_path,
        "-c",
        "user.name=Task 11 Test",
        "-c",
        "user.email=task11@example.invalid",
        "commit",
        "-qm",
        "test: seed relevant source",
    )

    clean = build_cli._relevant_source_provenance(
        tmp_path,
        relevant_paths=("tracked.py",),
    )
    clean_repeat = build_cli._relevant_source_provenance(
        tmp_path,
        relevant_paths=("tracked.py",),
    )

    assert clean.source_status == "clean"
    assert clean.relevant_source_sha256 == (
        clean_repeat.relevant_source_sha256
    )
    assert clean.git_head == _run_git(tmp_path, "rev-parse", "HEAD")

    tracked.write_text("VALUE = 2\n", encoding="utf-8")
    dirty = build_cli._relevant_source_provenance(
        tmp_path,
        relevant_paths=("tracked.py",),
    )
    assert dirty.source_status == "dirty"
    assert dirty.git_head == clean.git_head
    assert dirty.relevant_source_sha256 != clean.relevant_source_sha256

    untracked.write_text("VALUE = 3\n", encoding="utf-8")
    absent_from_head = build_cli._relevant_source_provenance(
        tmp_path,
        relevant_paths=("new.py", "tracked.py"),
    )
    assert absent_from_head.source_status == "dirty"
    assert absent_from_head.relevant_source_sha256 not in {
        clean.relevant_source_sha256,
        dirty.relevant_source_sha256,
    }


_EXECUTED_LOCAL_SOURCE_PATHS = (
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
    "tools/guide_gates/__init__.py",
    "tools/guide_gates/build_guide_image_index.py",
)


@pytest.mark.parametrize(
    "relative_path",
    _EXECUTED_LOCAL_SOURCE_PATHS,
)
def test_default_provenance_tracks_each_executed_local_source(
    tmp_path: Path,
    relative_path: str,
) -> None:
    assert relative_path in build_cli.RELEVANT_SOURCE_PATHS

    original_contents: dict[str, str] = {}
    for relevant_path in build_cli.RELEVANT_SOURCE_PATHS:
        content = f"{relevant_path}\n"
        original_contents[relevant_path] = content
        path = tmp_path / relevant_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _run_git(tmp_path, "init", "-q")
    _run_git(tmp_path, "add", ".")
    _run_git(
        tmp_path,
        "-c",
        "user.name=Task 14A Test",
        "-c",
        "user.email=task14a@example.invalid",
        "commit",
        "-qm",
        "test: seed relevant runtime sources",
    )
    clean = build_cli._relevant_source_provenance(tmp_path)

    assert clean.source_status == "clean"
    path = tmp_path / relative_path
    path.write_text(
        original_contents[relative_path] + "DIRTY = True\n",
        encoding="utf-8",
    )
    dirty = build_cli._relevant_source_provenance(tmp_path)

    assert dirty.source_status == "dirty"
    assert dirty.relevant_source_sha256 != clean.relevant_source_sha256
