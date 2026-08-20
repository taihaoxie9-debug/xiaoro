from __future__ import annotations

import hashlib
import importlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _requirement_lines(requirements: str) -> set[str]:
    return {
        line
        for raw_line in requirements.splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    }


def _runner_module():
    return importlib.import_module("tools.guide_gates.run_test_gate")


def _bounded_result(
    runner,
    *,
    returncode: int = 0,
    timed_out: bool = False,
):
    return runner.BoundedCommandResult(
        returncode=returncode,
        timed_out=timed_out,
        term_sent=False,
        kill_sent=False,
        elapsed_seconds=0.1,
        output_lines=1,
    )


def _fake_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    python = repo_root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    (repo_root / "requirements-guide-runtime.txt").write_text(
        "fastapi==0.115.0\n",
        encoding="utf-8",
    )
    (repo_root / "requirements-guide-runtime-test.txt").write_text(
        (
            "-r requirements-guide-runtime.txt\n"
            "numpy==2.3.4\n"
            "pytest==8.0.0\n"
            "PyYAML==6.0.3\n"
            "torch==2.12.0\n"
        ),
        encoding="utf-8",
    )
    (repo_root / "requirements-guide-browser-matrix.txt").write_text(
        (
            "-r requirements-guide-runtime-test.txt\n"
            "open_clip_torch==3.3.0\n"
            "playwright==1.60.0\n"
            "rapidocr-onnxruntime==1.3.0\n"
            "torchvision==0.27.0\n"
        ),
        encoding="utf-8",
    )
    (repo_root / "pytest-guide.ini").write_text(
        "[pytest]\ntestpaths = tests/guide\n",
        encoding="utf-8",
    )
    return repo_root, python


def _identity_payload(
    repo_root: Path,
    python: Path,
    *,
    installed_distributions_sha256: str = "b" * 64,
) -> dict[str, Any]:
    return {
        "manifest": {
            "artifact_hashes_locked": False,
            "installed_distribution_count": 37,
            "installed_distributions_sha256": (
                installed_distributions_sha256
            ),
            "pytest_guide_ini_sha256": "c" * 64,
            "python_version": "3.11.1 (main, reproducible build)",
            "requirements_input_sha256": "d" * 64,
            "residual_risks": [
                "installed_versions_do_not_lock_artifact_bytes"
            ],
            "schema_version": "guide-test-environment-v1",
            "sys_executable": str(python.absolute()),
        },
        "status": "passed",
    }


def _write_json_output(
    options: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    os.write(
        options["output_fd"],
        (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
    )


def _normalized_installed_distributions_sha256() -> str:
    normalized = sorted(
        {
            (
                re.sub(
                    r"[-_.]+",
                    "-",
                    distribution.metadata["Name"],
                ).lower()
                + "=="
                + distribution.version
            )
            for distribution in metadata.distributions()
            if distribution.metadata.get("Name")
        }
    )
    payload = "".join(f"{item}\n" for item in normalized)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_sha256(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _environment_identity_sha256(
    manifest: dict[str, Any],
) -> str:
    return _json_sha256(
        {
            "artifact_hashes_locked": manifest[
                "artifact_hashes_locked"
            ],
            "installed_distribution_count": manifest[
                "installed_distribution_count"
            ],
            "installed_distributions_sha256": manifest[
                "installed_distributions_sha256"
            ],
            "pytest_guide_ini_sha256": manifest[
                "pytest_guide_ini_sha256"
            ],
            "python_version": manifest["python_version"],
            "requirements_input_sha256": manifest[
                "requirements_input_sha256"
            ],
            "schema_version": "guide-test-environment-identity-v1",
        }
    )


def _verification_payload(
    environment_manifest: dict[str, Any],
    *,
    suite: str,
    nodeids: tuple[str, ...],
) -> dict[str, Any]:
    normalized_nodeids = "".join(
        f"{nodeid}\n" for nodeid in sorted(nodeids)
    )
    collection_hashes = {
        name: "e" * 64
        for name in ("focused", "full", "runtime", "all")
    }
    collection_hashes[suite] = hashlib.sha256(
        normalized_nodeids.encode("utf-8")
    ).hexdigest()
    return {
        "artifact_hashes_locked": False,
        "collection_nodeids_sha256": collection_hashes,
        "consecutive_failures": 0,
        "environment_identity_sha256": _environment_identity_sha256(
            environment_manifest
        ),
        "failure_code": None,
        "failure_layer": None,
        "residual_risks": [
            "installed_versions_do_not_lock_artifact_bytes"
        ],
        "schema_version": (
            "guide-test-environment-rebuild-verification-v2"
        ),
        "status": "passed",
    }


def _assert_private_output_fd(
    options: dict[str, Any],
    output_path: Path,
) -> int:
    assert "output_path" not in options
    assert "summary_path" not in options
    output_fd = options.get("output_fd")
    assert isinstance(output_fd, int), (
        "run_test_gate must pass a pre-created output_fd"
    )
    descriptor_status = os.fstat(output_fd)
    path_status = output_path.stat()
    assert descriptor_status.st_dev == path_status.st_dev
    assert descriptor_status.st_ino == path_status.st_ino
    assert stat.S_IMODE(descriptor_status.st_mode) == 0o600
    return output_fd


def test_runtime_test_requirements_lock_full_suite_dependencies() -> None:
    requirements = (
        REPO_ROOT / "requirements-guide-runtime-test.txt"
    ).read_text(encoding="utf-8")
    requirement_lines = _requirement_lines(requirements)

    assert "-r requirements-guide-runtime.txt" in requirement_lines
    assert all(
        "requirements-guide-image.txt" not in line
        for line in requirement_lines
    )
    assert "numpy==2.3.4" in requirement_lines
    assert "PyYAML==6.0.3" in requirement_lines
    assert "torch==2.12.0" in requirement_lines
    assert "pytest==8.0.0" in requirement_lines


def test_runtime_test_requirements_reject_commented_or_suffixed_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirements_path = REPO_ROOT / "requirements-guide-runtime-test.txt"
    invalid_requirements = "\n".join(
        (
            "-r requirements-guide-runtime.txt.disabled",
            "# numpy==2.3.4",
            "PyYAML==6.0.30",
            "torch==2.12.0+cpu",
            "pytest==8.0.0rc1",
        )
    )
    original_read_text = Path.read_text

    def read_invalid_requirements(path: Path, *args, **kwargs) -> str:
        if path == requirements_path:
            return invalid_requirements
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_invalid_requirements)

    with pytest.raises(AssertionError):
        test_runtime_test_requirements_lock_full_suite_dependencies()


def test_preflight_program_emits_complete_reproducible_identity(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    pytest_version = metadata.version("pytest")
    (repo_root / "requirements-base.txt").write_text(
        f"pytest=={pytest_version}\n",
        encoding="utf-8",
    )
    (repo_root / "requirements-test.txt").write_text(
        "-r requirements-base.txt\n",
        encoding="utf-8",
    )
    pytest_config = repo_root / "pytest-guide.ini"
    pytest_config.write_text("[pytest]\naddopts = -ra\n", encoding="utf-8")

    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            runner.PREFLIGHT_PROGRAM,
            str(Path(sys.executable).absolute()),
            str(Path(sys.prefix).absolute()),
            str(repo_root),
            "requirements-test.txt",
            "pytest-guide.ini",
            "{}",
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    manifest = payload["manifest"]
    assert manifest == {
        "artifact_hashes_locked": False,
        "installed_distribution_count": len(
            {
                re.sub(
                    r"[-_.]+",
                    "-",
                    distribution.metadata["Name"],
                ).lower()
                for distribution in metadata.distributions()
                if distribution.metadata.get("Name")
            }
        ),
        "installed_distributions_sha256": (
            _normalized_installed_distributions_sha256()
        ),
        "pytest_guide_ini_sha256": hashlib.sha256(
            pytest_config.read_bytes()
        ).hexdigest(),
        "python_version": sys.version,
        "requirements_input_sha256": manifest[
            "requirements_input_sha256"
        ],
        "residual_risks": [
            "installed_versions_do_not_lock_artifact_bytes"
        ],
        "schema_version": "guide-test-environment-v1",
        "sys_executable": str(Path(sys.executable).absolute()),
    }
    assert re.fullmatch(
        r"[0-9a-f]{64}",
        manifest["requirements_input_sha256"],
    )

    original_sha = manifest["requirements_input_sha256"]
    (repo_root / "requirements-base.txt").write_text(
        f"pytest=={pytest_version}\n# changed input\n",
        encoding="utf-8",
    )
    changed = subprocess.run(
        completed.args,
        check=False,
        capture_output=True,
        text=True,
    )
    assert changed.returncode == 0
    assert (
        json.loads(changed.stdout)["manifest"][
            "requirements_input_sha256"
        ]
        != original_sha
    )


def test_environment_identity_uses_recursive_browser_matrix_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _runner_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runtime_lock = repo_root / "requirements-guide-runtime-test.txt"
    runtime_lock.write_text(
        f"pytest=={metadata.version('pytest')}\n",
        encoding="utf-8",
    )
    browser_lock = repo_root / "requirements-guide-browser-matrix.txt"
    browser_lock.write_text(
        (
            "-r requirements-guide-runtime-test.txt\n"
            "playwright==1.60.0\n"
        ),
        encoding="utf-8",
    )
    pytest_config = repo_root / "pytest-guide.ini"
    pytest_config.write_text("[pytest]\n", encoding="utf-8")
    runtime_only_distributions = tuple(
        distribution
        for distribution in metadata.distributions()
        if re.sub(
            r"[-_.]+",
            "-",
            distribution.metadata.get("Name", ""),
        ).lower()
        != "playwright"
    )
    monkeypatch.setattr(
        metadata,
        "distributions",
        lambda: iter(runtime_only_distributions),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            sys.executable,
            str(Path(sys.executable).absolute()),
            str(Path(sys.prefix).absolute()),
            str(repo_root),
            runner.REQUIREMENTS_INPUT,
            "pytest-guide.ini",
            "{}",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        exec(runner.PREFLIGHT_PROGRAM, {})

    assert runner.REQUIREMENTS_INPUT == (
        "requirements-guide-browser-matrix.txt"
    )
    assert exit_info.value.code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["failures"] == [
        "playwright_distribution_expected_1.60.0_actual_MISSING"
    ]
    assert all("ImportError" not in failure for failure in payload["failures"])
    requirements_identity = json.dumps(
        [
            {
                "path": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted((browser_lock, runtime_lock))
        ],
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert payload["manifest"]["requirements_input_sha256"] == (
        hashlib.sha256(requirements_identity).hexdigest()
    )


def test_preflight_program_rejects_requirement_include_outside_repo(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (tmp_path / "outside.txt").write_text(
        f"pytest=={metadata.version('pytest')}\n",
        encoding="utf-8",
    )
    (repo_root / "requirements-test.txt").write_text(
        "-r ../outside.txt\n",
        encoding="utf-8",
    )
    (repo_root / "pytest-guide.ini").write_text(
        "[pytest]\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            runner.PREFLIGHT_PROGRAM,
            str(Path(sys.executable).absolute()),
            str(Path(sys.prefix).absolute()),
            str(repo_root),
            "requirements-test.txt",
            "pytest-guide.ini",
            "{}",
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 3
    payload = json.loads(completed.stdout)
    assert payload["status"] == "failed"
    assert any(
        failure.startswith("requirements_invalid_ValueError_")
        for failure in payload["failures"]
    )


def test_gate_builds_minimal_fixed_child_environment_with_trusted_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    docker_compose = Path("/opt/homebrew/bin/docker-compose")
    assert docker_compose.is_file()
    assert os.access(docker_compose, os.X_OK)
    repo_root, _ = _fake_repo(tmp_path)
    evidence_dir = tmp_path / "evidence"
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    (hostile_bin / "docker-compose").touch(mode=0o755)
    calls: list[dict[str, Any]] = []

    def fake_run_bounded(command, **kwargs):
        _assert_private_output_fd(
            kwargs,
            evidence_dir / "preflight.log",
        )
        _write_json_output(
            kwargs,
            _identity_payload(repo_root, repo_root / ".venv/bin/python"),
        )
        calls.append(kwargs)
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", fake_run_bounded)

    runner.run_test_gate(
        "preflight",
        repo_root=repo_root,
        evidence_dir=evidence_dir,
        environment={
            "HOME": "/tmp/home",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": str(hostile_bin),
            "PYTHONHOME": "/tmp/foreign-python",
            "PYTHONPATH": "/tmp/foreign-packages",
            "PYTEST_ADDOPTS": "--collect-only",
            "PYTEST_PLUGINS": "hostile_plugin",
            "TMPDIR": "/tmp/runner",
            "TZ": "UTC",
            "UNRELATED_SETTING": "must-not-pass",
            "VIRTUAL_ENV": "/tmp/foreign-venv",
        },
    )

    assert len(calls) == 1
    assert calls[0]["env"] == {
        "HOME": "/tmp/home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.pathsep.join(
            (
                str(repo_root / ".venv" / "bin"),
                str(docker_compose.parent),
                "/usr/bin",
                "/bin",
            )
        ),
        "TMPDIR": "/tmp/runner",
        "TZ": "UTC",
    }


def test_gate_child_cannot_log_parent_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, python = _fake_repo(tmp_path)
    python.unlink()
    python.symlink_to(sys.executable)
    evidence_dir = tmp_path / "evidence"
    credentials = {
        "AUTHORIZATION": "Bearer credential-auth",
        "CLIENT_SECRET": "credential-client-secret",
        "DATABASE_PASSWORD": "credential-password",
        "GUIDE_LLM_API_KEY": "credential-guide-key",
        "SERVICE_TOKEN": "credential-service-token",
    }
    credential_names = tuple(credentials)
    identity = _identity_payload(repo_root, python)
    probe_path = python.parent / "credential_probe.py"
    probe_path.write_text(
        (
            "import json\n"
            "import os\n"
            f"payload = {identity!r}\n"
            f"names = {credential_names!r}\n"
            "payload['observed_credentials'] = [\n"
            "    os.environ.get(name, 'MISSING') for name in names\n"
            "]\n"
            "print(json.dumps(payload, sort_keys=True))"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "PREFLIGHT_PROGRAM",
        (
            "from pathlib import Path\n"
            "import sys\n"
            "probe = Path(sys.argv[1]).parent / 'credential_probe.py'\n"
            "exec(probe.read_text(encoding='utf-8'))"
        ),
    )

    result = runner.run_test_gate(
        "preflight",
        repo_root=repo_root,
        evidence_dir=evidence_dir,
        environment={
            "HOME": "/tmp/home",
            **credentials,
        },
    )

    assert result.preflight.returncode == 0
    evidence = json.loads(
        (evidence_dir / "preflight.log").read_text(encoding="utf-8")
    )
    assert evidence["observed_credentials"] == (
        ["MISSING"] * len(credentials)
    )
    serialized_evidence = json.dumps(evidence, sort_keys=True)
    assert all(
        value not in serialized_evidence for value in credentials.values()
    )


def test_gate_rejects_replaced_log_without_reopening_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, _ = _fake_repo(tmp_path)
    evidence_dir = tmp_path / "evidence"
    output_path = evidence_dir / "preflight.log"
    detached_output = evidence_dir / "detached.log"
    replacement = b"replacement must remain unchanged\n"
    descriptor_output = b"descriptor-bound output\n"

    def replace_log_path(command, **kwargs):
        output_fd = _assert_private_output_fd(kwargs, output_path)
        output_path.rename(detached_output)
        output_path.write_bytes(replacement)
        os.write(output_fd, descriptor_output)
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", replace_log_path)

    with pytest.raises(RuntimeError, match="binding changed"):
        runner.run_test_gate(
            "preflight",
            repo_root=repo_root,
            evidence_dir=evidence_dir,
        )

    assert output_path.read_bytes() == replacement
    assert detached_output.read_bytes() == descriptor_output
    assert stat.S_IMODE(detached_output.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("suite", "pytest_arguments", "timeout_seconds"),
    [
        (
            "focused",
            (
                "-c",
                "pytest-guide.ini",
                "-q",
                "tests/guide/understanding",
                "tests/guide/intent",
                "tests/guide/adapters",
                "tests/guide/application/test_text_recommendation_flow.py",
                "tests/guide/application/test_cross_worker_text_state.py",
                "tests/guide/runtime/test_composition_understanding.py",
                "tests/guide/runtime/test_import_boundary.py",
                "tests/guide/tools",
            ),
            1200,
        ),
        (
            "full",
            ("-c", "pytest-guide.ini", "-q"),
            1800,
        ),
        (
            "runtime",
            (
                "-c",
                "pytest-guide.ini",
                "-q",
                "tests/guide/runtime",
            ),
            1800,
        ),
        (
            "all",
            ("-c", "pytest-guide.ini", "-q", "tests"),
            1800,
        ),
    ],
)
def test_gate_uses_clean_repo_venv_and_fixed_pytest_suites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
    pytest_arguments: tuple[str, ...],
    timeout_seconds: int,
) -> None:
    runner = _runner_module()
    repo_root, python = _fake_repo(tmp_path)
    evidence_dir = tmp_path / "evidence"
    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    nodeids = (
        "tests/guide/z_test.py::test_second",
        "tests/guide/a_test.py::test_first",
    )
    identity = _identity_payload(repo_root, python)
    rebuild_manifest = dict(identity["manifest"])
    rebuild_manifest["sys_executable"] = (
        "/private/tmp/independent-fresh/.venv/bin/python"
    )
    verification_path = tmp_path / "rebuild-verification.json"
    verification_path.write_text(
        json.dumps(
            _verification_payload(
                rebuild_manifest,
                suite=suite,
                nodeids=nodeids,
            ),
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    def fake_run_bounded(command, **kwargs):
        output_name = (
            "preflight.log"
            if not calls
            else (
                f"{suite}.collection.log"
                if len(calls) == 1
                else f"{suite}.log"
            )
        )
        _assert_private_output_fd(
            kwargs,
            evidence_dir / output_name,
        )
        if not calls:
            _write_json_output(
                kwargs,
                identity,
            )
        elif len(calls) == 1:
            os.write(
                kwargs["output_fd"],
                ("\n".join(nodeids) + "\n").encode("utf-8"),
            )
        calls.append((tuple(command), kwargs))
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", fake_run_bounded)

    result = runner.run_test_gate(
        suite,
        repo_root=repo_root,
        evidence_dir=evidence_dir,
        environment={
            "HOME": "/tmp/home",
            "PYTHONPATH": "/tmp/foreign-packages",
            "PYTHONHOME": "/tmp/foreign-python",
        },
        rebuild_verification=verification_path,
    )

    assert result.preflight.returncode == 0
    assert result.collection is not None
    assert result.collection.returncode == 0
    assert result.pytest is not None
    assert result.pytest.returncode == 0
    assert result.failure is None
    assert len(calls) == 3

    preflight_command, preflight_options = calls[0]
    assert preflight_command[0] == str(python)
    preflight_contract = "\n".join(preflight_command)
    for required_value in (
        "3.11",
        str(python),
        str(repo_root / ".venv"),
        "fastapi",
        "yaml",
        "numpy",
        "torch",
        "requirements-guide-browser-matrix.txt",
        "pytest-guide.ini",
    ):
        assert required_value in preflight_contract
    assert preflight_options["timeout_seconds"] == 60
    assert preflight_options["cwd"] == repo_root
    assert preflight_options["env"] == {
        "HOME": "/tmp/home",
        "PATH": os.pathsep.join(
            (
                str(repo_root / ".venv" / "bin"),
                "/opt/homebrew/bin",
                "/usr/bin",
                "/bin",
            )
        ),
    }
    assert json.loads(
        (evidence_dir / "preflight.json").read_text(encoding="utf-8")
    )["returncode"] == 0
    environment_manifest_path = (
        evidence_dir / "environment-manifest.json"
    )
    environment_manifest = json.loads(
        environment_manifest_path.read_text(encoding="utf-8")
    )
    assert environment_manifest == _identity_payload(
        repo_root,
        python,
    )["manifest"]
    assert stat.S_IMODE(environment_manifest_path.stat().st_mode) == 0o600

    collection_command, collection_options = calls[1]
    assert collection_command == (
        str(python),
        "-m",
        "pytest",
        "--collect-only",
        *pytest_arguments,
    )
    assert collection_options["cwd"] == repo_root
    assert collection_options["env"] == preflight_options["env"]
    collection_manifest_path = (
        evidence_dir / f"{suite}.collection-manifest.json"
    )
    collection_manifest = json.loads(
        collection_manifest_path.read_text(encoding="utf-8")
    )
    sorted_nodeids = "".join(
        f"{nodeid}\n" for nodeid in sorted(nodeids)
    )
    assert collection_manifest["nodeid_count"] == 2
    assert collection_manifest["nodeids_sha256"] == hashlib.sha256(
        sorted_nodeids.encode("utf-8")
    ).hexdigest()
    assert collection_manifest["suite"] == suite
    assert stat.S_IMODE(collection_manifest_path.stat().st_mode) == 0o600

    pytest_command, pytest_options = calls[2]
    assert pytest_command == (
        str(python),
        "-m",
        "pytest",
        *pytest_arguments,
    )
    assert pytest_options["timeout_seconds"] == timeout_seconds
    assert pytest_options["heartbeat_seconds"] == 30
    assert pytest_options["cwd"] == repo_root
    assert pytest_options["env"] == {
        "HOME": "/tmp/home",
        "PATH": os.pathsep.join(
            (
                str(repo_root / ".venv" / "bin"),
                "/opt/homebrew/bin",
                "/usr/bin",
                "/bin",
            )
        ),
    }
    assert json.loads(
        (evidence_dir / f"{suite}.json").read_text(encoding="utf-8")
    )["returncode"] == 0


def test_identity_only_collects_without_starting_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, python = _fake_repo(tmp_path)
    calls: list[tuple[str, ...]] = []

    def collect_identity(command, **kwargs):
        calls.append(tuple(command))
        if len(calls) == 1:
            _write_json_output(
                kwargs,
                _identity_payload(repo_root, python),
            )
        else:
            os.write(
                kwargs["output_fd"],
                b"tests/guide/test_identity.py::test_contract\n",
            )
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", collect_identity)

    result = runner.run_test_gate(
        "focused",
        repo_root=repo_root,
        evidence_dir=tmp_path / "evidence",
        identity_only=True,
    )

    assert len(calls) == 2
    assert result.collection is not None
    assert result.pytest is None
    assert result.failure is None


def test_suite_without_rebuild_verification_is_typed_fail_before_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, python = _fake_repo(tmp_path)
    calls: list[tuple[str, ...]] = []

    def collect_identity(command, **kwargs):
        calls.append(tuple(command))
        if len(calls) == 1:
            _write_json_output(
                kwargs,
                _identity_payload(repo_root, python),
            )
        else:
            os.write(
                kwargs["output_fd"],
                b"tests/guide/test_identity.py::test_contract\n",
            )
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", collect_identity)

    result = runner.run_test_gate(
        "focused",
        repo_root=repo_root,
        evidence_dir=tmp_path / "evidence",
    )

    assert len(calls) == 2
    assert result.pytest is None
    assert result.failure is not None
    assert result.failure.layer == "test_environment.dependency_resolution"
    assert result.failure.code == "rebuild_verification_missing"


def test_collection_drift_from_rebuild_verification_blocks_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, python = _fake_repo(tmp_path)
    identity = _identity_payload(repo_root, python)
    verification_path = tmp_path / "rebuild-verification.json"
    verification_path.write_text(
        json.dumps(
            _verification_payload(
                identity["manifest"],
                suite="runtime",
                nodeids=("tests/guide/test_expected.py::test_contract",),
            ),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, ...]] = []

    def collect_drifted_identity(command, **kwargs):
        calls.append(tuple(command))
        if len(calls) == 1:
            _write_json_output(kwargs, identity)
        else:
            os.write(
                kwargs["output_fd"],
                b"tests/guide/test_actual.py::test_contract\n",
            )
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", collect_drifted_identity)

    result = runner.run_test_gate(
        "runtime",
        repo_root=repo_root,
        evidence_dir=tmp_path / "evidence",
        rebuild_verification=verification_path,
    )

    assert len(calls) == 2
    assert result.pytest is None
    assert result.failure is not None
    assert result.failure.layer == "test_environment.collection"
    assert result.failure.code == "rebuild_verification_collection_drift"


def test_environment_manifest_drift_is_typed_before_collection_or_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, python = _fake_repo(tmp_path)
    evidence_dir = tmp_path / "evidence"
    expected_manifest = _identity_payload(repo_root, python)["manifest"]
    expected_manifest["installed_distributions_sha256"] = "a" * 64
    expected_manifest_path = tmp_path / "expected-environment.json"
    expected_manifest_path.write_text(
        json.dumps(expected_manifest, sort_keys=True),
        encoding="utf-8",
    )
    calls: list[tuple[str, ...]] = []

    def emit_drifted_identity(command, **kwargs):
        calls.append(tuple(command))
        _write_json_output(
            kwargs,
            _identity_payload(repo_root, python),
        )
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", emit_drifted_identity)

    result = runner.run_test_gate(
        "focused",
        repo_root=repo_root,
        evidence_dir=evidence_dir,
        expected_environment_manifest=expected_manifest_path,
    )

    assert len(calls) == 1
    assert result.collection is None
    assert result.pytest is None
    assert result.failure is not None
    assert result.failure.layer == "test_environment.dependency_resolution"
    assert result.failure.code == "environment_manifest_drift"
    failure_path = evidence_dir / "test-environment-failure.json"
    assert json.loads(failure_path.read_text(encoding="utf-8")) == {
        "code": "environment_manifest_drift",
        "layer": "test_environment.dependency_resolution",
        "status": "failed",
    }
    assert stat.S_IMODE(failure_path.stat().st_mode) == 0o600


def test_collection_failure_never_starts_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, python = _fake_repo(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fail_collection(command, **kwargs):
        calls.append(tuple(command))
        if len(calls) == 1:
            _write_json_output(
                kwargs,
                _identity_payload(repo_root, python),
            )
            return _bounded_result(runner)
        return _bounded_result(runner, returncode=4)

    monkeypatch.setattr(runner, "run_bounded", fail_collection)

    result = runner.run_test_gate(
        "runtime",
        repo_root=repo_root,
        evidence_dir=tmp_path / "evidence",
    )

    assert len(calls) == 2
    assert result.collection is not None
    assert result.collection.returncode == 4
    assert result.pytest is None
    assert result.failure is not None
    assert result.failure.layer == "test_environment.collection"
    assert result.failure.code == "collect_only_failed"


def test_preflight_failure_never_starts_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, _ = _fake_repo(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fail_preflight(command, **kwargs):
        calls.append(tuple(command))
        return _bounded_result(runner, returncode=3)

    monkeypatch.setattr(runner, "run_bounded", fail_preflight)

    result = runner.run_test_gate(
        "focused",
        repo_root=repo_root,
        evidence_dir=tmp_path / "evidence",
    )

    assert result.preflight.returncode == 3
    assert result.collection is None
    assert result.pytest is None
    assert len(calls) == 1
    assert result.failure is not None
    assert result.failure.layer == "test_environment.dependency_resolution"
    assert result.failure.code == "preflight_failed"
    failure = json.loads(
        (
            tmp_path
            / "evidence"
            / "test-environment-failure.json"
        ).read_text(encoding="utf-8")
    )
    assert failure == {
        "code": "preflight_failed",
        "layer": "test_environment.dependency_resolution",
        "status": "failed",
    }


def test_runtime_only_environment_is_typed_failure_before_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _runner_module()
    repo_root = tmp_path / "repo"
    python = repo_root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    (repo_root / "requirements-guide-runtime-test.txt").write_text(
        f"pytest=={metadata.version('pytest')}\n",
        encoding="utf-8",
    )
    (repo_root / "requirements-guide-browser-matrix.txt").write_text(
        (
            "-r requirements-guide-runtime-test.txt\n"
            "playwright==1.60.0\n"
        ),
        encoding="utf-8",
    )
    (repo_root / "pytest-guide.ini").write_text(
        "[pytest]\n",
        encoding="utf-8",
    )
    runtime_only_distributions = tuple(
        distribution
        for distribution in metadata.distributions()
        if re.sub(
            r"[-_.]+",
            "-",
            distribution.metadata.get("Name", ""),
        ).lower()
        != "playwright"
    )
    monkeypatch.setattr(
        metadata,
        "distributions",
        lambda: iter(runtime_only_distributions),
    )
    monkeypatch.setattr(runner, "EXPECTED_DEPENDENCIES", {})
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "prefix", str(repo_root / ".venv"))
    calls: list[tuple[str, ...]] = []

    def run_real_preflight(command, **kwargs):
        calls.append(tuple(command))
        monkeypatch.setattr(sys, "argv", ["-c", *command[3:]])
        try:
            exec(command[2], {})
        except SystemExit as exc:
            returncode = int(exc.code)
        output = capsys.readouterr().out
        os.write(kwargs["output_fd"], output.encode("utf-8"))
        return _bounded_result(runner, returncode=returncode)

    monkeypatch.setattr(runner, "run_bounded", run_real_preflight)
    evidence_dir = tmp_path / "evidence"

    result = runner.run_test_gate(
        "focused",
        repo_root=repo_root,
        evidence_dir=evidence_dir,
    )

    assert len(calls) == 1
    assert runner.REQUIREMENTS_INPUT in calls[0]
    assert result.preflight.returncode == 3
    assert result.collection is None
    assert result.pytest is None
    assert result.failure is not None
    assert result.failure.layer == "test_environment.dependency_resolution"
    assert result.failure.code == "preflight_failed"
    preflight = json.loads(
        (evidence_dir / "preflight.log").read_text(encoding="utf-8")
    )
    assert preflight["failures"] == [
        "playwright_distribution_expected_1.60.0_actual_MISSING"
    ]
    assert "ImportError" not in json.dumps(preflight, sort_keys=True)


def test_preflight_timeout_never_starts_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, _ = _fake_repo(tmp_path)
    calls: list[tuple[str, ...]] = []

    def time_out_preflight(command, **kwargs):
        calls.append(tuple(command))
        return _bounded_result(
            runner,
            returncode=-15,
            timed_out=True,
        )

    monkeypatch.setattr(runner, "run_bounded", time_out_preflight)

    result = runner.run_test_gate(
        "all",
        repo_root=repo_root,
        evidence_dir=tmp_path / "evidence",
    )

    assert result.preflight.timed_out is True
    assert result.collection is None
    assert result.pytest is None
    assert len(calls) == 1


def test_preflight_suite_does_not_start_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, _ = _fake_repo(tmp_path)
    calls: list[tuple[str, ...]] = []

    def pass_preflight(command, **kwargs):
        calls.append(tuple(command))
        _write_json_output(
            kwargs,
            _identity_payload(repo_root, repo_root / ".venv/bin/python"),
        )
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", pass_preflight)

    result = runner.run_test_gate(
        "preflight",
        repo_root=repo_root,
        evidence_dir=tmp_path / "evidence",
    )

    assert result.preflight.returncode == 0
    assert result.collection is None
    assert result.pytest is None
    assert len(calls) == 1


def test_gate_rejects_missing_repository_venv_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    launched = False

    def unexpected_launch(command, **kwargs):
        nonlocal launched
        launched = True
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", unexpected_launch)

    with pytest.raises(
        runner.TestEnvironmentError,
        match=r"\.venv/bin/python",
    ):
        runner.run_test_gate(
            "focused",
            repo_root=tmp_path,
            evidence_dir=tmp_path / "evidence",
        )

    assert launched is False


def test_gate_rejects_missing_trusted_docker_compose_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner_module()
    repo_root, _ = _fake_repo(tmp_path)
    homebrew_bin = tmp_path / "opt" / "homebrew" / "bin"
    local_bin = tmp_path / "usr" / "local" / "bin"
    homebrew_bin.mkdir(parents=True)
    local_bin.mkdir(parents=True)
    (homebrew_bin / "docker-compose").touch(mode=0o644)
    monkeypatch.setattr(
        runner,
        "TRUSTED_EXTERNAL_TOOL_DIRECTORIES",
        (homebrew_bin, local_bin),
    )
    launched = False

    def unexpected_launch(command, **kwargs):
        nonlocal launched
        launched = True
        return _bounded_result(runner)

    monkeypatch.setattr(runner, "run_bounded", unexpected_launch)

    with pytest.raises(
        runner.MissingExternalToolError,
        match="docker-compose",
    ):
        runner.run_test_gate(
            "focused",
            repo_root=repo_root,
            evidence_dir=tmp_path / "evidence",
            environment={"PATH": str(tmp_path / "hostile-bin")},
        )

    assert launched is False


def test_gate_rejects_unknown_suite() -> None:
    runner = _runner_module()

    with pytest.raises(ValueError, match="unknown test suite"):
        runner.run_test_gate(
            "arbitrary",
            repo_root=REPO_ROOT,
            evidence_dir=REPO_ROOT / ".test-evidence",
        )
