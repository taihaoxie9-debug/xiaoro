"""Run fixed test suites from one repository-local Python environment."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

if __package__:
    from tools.guide_gates.private_output_io import (
        open_private_path,
        verify_path_binding,
        write_json_fd,
    )
    from tools.guide_gates.run_bounded_command import (
        BoundedCommandResult,
        _summary_payload,
        run_bounded,
    )
    from tools.guide_gates.test_environment_identity import (
        stable_environment_identity_sha256,
    )
else:
    from private_output_io import (
        open_private_path,
        verify_path_binding,
        write_json_fd,
    )
    from run_bounded_command import (
        BoundedCommandResult,
        _summary_payload,
        run_bounded,
    )
    from test_environment_identity import (
        stable_environment_identity_sha256,
    )


REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_TIMEOUT_SECONDS = 60
COLLECTION_TIMEOUT_SECONDS = 600
HEARTBEAT_SECONDS = 30
REQUIREMENTS_INPUT = "requirements-guide-browser-matrix.txt"
PYTEST_CONFIG = "pytest-guide.ini"
DEPENDENCY_FAILURE_LAYER = "test_environment.dependency_resolution"
COLLECTION_FAILURE_LAYER = "test_environment.collection"
PASSTHROUGH_ENVIRONMENT_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TZ",
)
MINIMAL_SYSTEM_PATH = ("/usr/bin", "/bin")
TRUSTED_EXTERNAL_TOOL_DIRECTORIES = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)
REQUIRED_EXTERNAL_TOOLS = ("docker-compose",)
EXPECTED_DEPENDENCIES = {
    "fastapi": "0.115.0",
    "numpy": "2.3.4",
    "torch": "2.12.0",
    "yaml": "6.0.3",
}
PREFLIGHT_PROGRAM = r"""
import hashlib
import importlib
from importlib import metadata
import json
from pathlib import Path
import re
import stat
import sys

expected_python = Path(sys.argv[1]).absolute()
expected_prefix = Path(sys.argv[2]).absolute()
repo_root = Path(sys.argv[3]).absolute()
requirements_name = sys.argv[4]
pytest_config_name = sys.argv[5]
expected_dependencies = json.loads(sys.argv[6])
failures = []

if sys.version_info[:2] != (3, 11):
    failures.append(
        "python_version_expected_3.11_actual_"
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )
if Path(sys.executable).absolute() != expected_python:
    failures.append("python_executable_mismatch")
if Path(sys.prefix).absolute() != expected_prefix:
    failures.append("python_prefix_mismatch")

name_pattern = re.compile(r"[-_.]+")
pin_pattern = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)$"
)
include_pattern = re.compile(r"^-r\s+(\S+)$")

def canonical_name(name):
    return name_pattern.sub("-", name).lower()

def checked_path(relative_name):
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("requirements_path_outside_repo")
    candidate = repo_root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("requirements_symlink_not_allowed")
    status = candidate.stat()
    if not stat.S_ISREG(status.st_mode):
        raise ValueError("requirements_input_not_regular")
    return candidate, relative.as_posix()

requirements_records = {}
expected_pins = {}

def load_requirements(relative_name):
    path, relative = checked_path(relative_name)
    if relative in requirements_records:
        return
    content = path.read_bytes()
    requirements_records[relative] = hashlib.sha256(content).hexdigest()
    for raw_line in content.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        include = include_pattern.fullmatch(line)
        if include is not None:
            nested = (path.parent / include.group(1)).relative_to(repo_root)
            load_requirements(nested.as_posix())
            continue
        pin = pin_pattern.fullmatch(line)
        if pin is None:
            raise ValueError("requirements_must_use_exact_pins")
        name = canonical_name(pin.group(1))
        version = pin.group(2)
        existing = expected_pins.get(name)
        if existing is not None and existing != version:
            raise ValueError("requirements_contain_conflicting_pins")
        expected_pins[name] = version

requirements_input_sha256 = ""
try:
    load_requirements(requirements_name)
    requirements_identity = json.dumps(
        [
            {"path": path, "sha256": digest}
            for path, digest in sorted(requirements_records.items())
        ],
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    requirements_input_sha256 = hashlib.sha256(
        requirements_identity
    ).hexdigest()
except Exception as exc:
    failures.append(f"requirements_invalid_{type(exc).__name__}_{exc}")

installed = {}
for distribution in metadata.distributions():
    raw_name = distribution.metadata.get("Name")
    if not raw_name:
        continue
    name = canonical_name(raw_name)
    version = distribution.version
    existing = installed.get(name)
    if existing is not None and existing != version:
        failures.append(f"installed_distribution_conflict_{name}")
    installed[name] = version

for name, expected_version in sorted(expected_pins.items()):
    actual_version = installed.get(name)
    if actual_version != expected_version:
        failures.append(
            f"{name}_distribution_expected_{expected_version}"
            f"_actual_{actual_version or 'MISSING'}"
        )

normalized_distributions = "".join(
    f"{entry}\n"
    for entry in sorted(
        f"{name}=={version}"
        for name, version in installed.items()
    )
)
installed_distributions_sha256 = hashlib.sha256(
    normalized_distributions.encode("utf-8")
).hexdigest()

pytest_config_sha256 = ""
try:
    pytest_config, _ = checked_path(pytest_config_name)
    pytest_config_sha256 = hashlib.sha256(
        pytest_config.read_bytes()
    ).hexdigest()
except Exception as exc:
    failures.append(f"pytest_config_invalid_{type(exc).__name__}_{exc}")

observed = {}
for module_name, expected_version in sorted(expected_dependencies.items()):
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        failures.append(
            f"{module_name}_import_failed_{type(exc).__name__}"
        )
        continue
    actual_version = str(getattr(module, "__version__", "UNKNOWN"))
    observed[module_name] = actual_version
    if actual_version != expected_version:
        failures.append(
            f"{module_name}_version_expected_{expected_version}"
            f"_actual_{actual_version}"
        )

payload = {
    "dependencies": observed,
    "manifest": {
        "artifact_hashes_locked": False,
        "installed_distribution_count": len(installed),
        "installed_distributions_sha256": (
            installed_distributions_sha256
        ),
        "pytest_guide_ini_sha256": pytest_config_sha256,
        "python_version": sys.version,
        "requirements_input_sha256": requirements_input_sha256,
        "residual_risks": [
            "installed_versions_do_not_lock_artifact_bytes"
        ],
        "schema_version": "guide-test-environment-v1",
        "sys_executable": str(Path(sys.executable).absolute()),
    },
    "status": "failed" if failures else "passed",
}
if failures:
    payload["failures"] = failures
print(json.dumps(payload, sort_keys=True))
raise SystemExit(3 if failures else 0)
""".strip()


@dataclass(frozen=True, slots=True)
class SuiteSpec:
    pytest_arguments: tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class TestGateResult:
    preflight: BoundedCommandResult
    collection: BoundedCommandResult | None
    pytest: BoundedCommandResult | None
    failure: TestGateFailure | None


@dataclass(frozen=True, slots=True)
class TestGateFailure:
    layer: str
    code: str


@dataclass(frozen=True, slots=True)
class CapturedCommandResult:
    command: BoundedCommandResult
    output: str | None


class TestEnvironmentError(RuntimeError):
    """Raised when the repository-local test interpreter is unavailable."""


class MissingExternalToolError(TestEnvironmentError):
    """Raised when a required tool is absent from trusted directories."""


def _resolve_external_tool_directories() -> tuple[Path, ...]:
    resolved_directories: list[Path] = []
    for tool_name in REQUIRED_EXTERNAL_TOOLS:
        for directory in TRUSTED_EXTERNAL_TOOL_DIRECTORIES:
            candidate = directory / tool_name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                if directory not in resolved_directories:
                    resolved_directories.append(directory)
                break
        else:
            raise MissingExternalToolError(
                f"required external tool is missing: {tool_name}"
            )
    return tuple(resolved_directories)


SUITES = {
    "focused": SuiteSpec(
        pytest_arguments=(
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
        timeout_seconds=1200,
    ),
    "full": SuiteSpec(
        pytest_arguments=("-c", "pytest-guide.ini", "-q"),
        timeout_seconds=1800,
    ),
    "runtime": SuiteSpec(
        pytest_arguments=(
            "-c",
            "pytest-guide.ini",
            "-q",
            "tests/guide/runtime",
        ),
        timeout_seconds=1800,
    ),
    "all": SuiteSpec(
        pytest_arguments=("-c", PYTEST_CONFIG, "-q", "tests"),
        timeout_seconds=1800,
    ),
}
SUITE_NAMES = ("preflight", *SUITES)


def _run_bounded_with_evidence(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    heartbeat_seconds: float,
    output_path: Path,
    summary_path: Path,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    capture_output: bool = False,
) -> CapturedCommandResult:
    output_fd = (
        _open_private_capture_path(output_path)
        if capture_output
        else open_private_path(output_path)
    )
    try:
        summary_fd = open_private_path(summary_path)
    except BaseException:
        os.close(output_fd)
        raise

    def verify_bindings() -> None:
        verify_path_binding(output_path, output_fd)
        verify_path_binding(summary_path, summary_fd)

    try:
        try:
            verify_bindings()
            result = run_bounded(
                command,
                timeout_seconds=timeout_seconds,
                heartbeat_seconds=heartbeat_seconds,
                output_fd=output_fd,
                cwd=cwd,
                env=env,
            )
            verify_bindings()
            write_json_fd(summary_fd, _summary_payload(result))
            verify_bindings()
            output = (
                _read_text_fd(output_fd) if capture_output else None
            )
            verify_bindings()
            return CapturedCommandResult(
                command=result,
                output=output,
            )
        except BaseException as failure:
            try:
                write_json_fd(
                    summary_fd,
                    _summary_payload(None, failure=failure),
                )
                verify_bindings()
            except BaseException:
                pass
            raise
    finally:
        os.close(summary_fd)
        os.close(output_fd)


def _open_private_capture_path(path: Path) -> int:
    descriptor = os.open(
        path,
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
        0o600,
    )
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise OSError("private output must be a regular file")
        os.fchmod(descriptor, 0o600)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_text_fd(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 64 * 1024):
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = open_private_path(path)
    try:
        verify_path_binding(path, descriptor)
        write_json_fd(descriptor, payload)
        verify_path_binding(path, descriptor)
    finally:
        os.close(descriptor)


def _read_json_object(path: Path) -> dict[str, Any]:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise TestEnvironmentError(
                f"manifest is not a regular file: {path}"
            )
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TestEnvironmentError(f"invalid JSON manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise TestEnvironmentError(f"invalid JSON manifest: {path}")
    return payload


def _parse_preflight_manifest(output: str | None) -> dict[str, Any]:
    if output is None:
        raise TestEnvironmentError("preflight identity output is unavailable")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise TestEnvironmentError(
            "preflight identity output is invalid"
        ) from exc
    manifest = payload.get("manifest")
    if payload.get("status") != "passed" or not isinstance(manifest, dict):
        raise TestEnvironmentError("preflight identity did not pass")
    required_fields = {
        "artifact_hashes_locked",
        "installed_distribution_count",
        "installed_distributions_sha256",
        "pytest_guide_ini_sha256",
        "python_version",
        "requirements_input_sha256",
        "residual_risks",
        "schema_version",
        "sys_executable",
    }
    if set(manifest) != required_fields:
        raise TestEnvironmentError(
            "preflight identity manifest fields are invalid"
        )
    return manifest


def _json_sha256(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _failure(
    evidence: Path,
    *,
    layer: str,
    code: str,
) -> TestGateFailure:
    failure = TestGateFailure(layer=layer, code=code)
    _write_private_json(
        evidence / "test-environment-failure.json",
        {
            "code": failure.code,
            "layer": failure.layer,
            "status": "failed",
        },
    )
    return failure


def _collection_manifest(
    *,
    suite: str,
    output: str | None,
    environment_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if output is None:
        raise TestEnvironmentError("collection output is unavailable")
    nodeids = sorted(
        {
            line.strip()
            for line in output.splitlines()
            if line.startswith("tests/") and "::" in line
        }
    )
    if not nodeids:
        raise TestEnvironmentError("collect-only returned no nodeids")
    normalized_nodeids = "".join(f"{nodeid}\n" for nodeid in nodeids)
    return {
        "environment_manifest_sha256": _json_sha256(
            environment_manifest
        ),
        "nodeid_count": len(nodeids),
        "nodeids_sha256": hashlib.sha256(
            normalized_nodeids.encode("utf-8")
        ).hexdigest(),
        "schema_version": "guide-test-collection-v1",
        "suite": suite,
    }


def _rebuild_admission_failure(
    verification: Mapping[str, Any],
    *,
    suite: str,
    environment_manifest: Mapping[str, Any],
    collection_manifest: Mapping[str, Any],
) -> TestGateFailure | None:
    if (
        verification.get("schema_version")
        != "guide-test-environment-rebuild-verification-v2"
        or verification.get("status") != "passed"
    ):
        return TestGateFailure(
            layer=DEPENDENCY_FAILURE_LAYER,
            code="rebuild_verification_not_passed",
        )
    if verification.get("environment_identity_sha256") != (
        stable_environment_identity_sha256(environment_manifest)
    ):
        return TestGateFailure(
            layer=DEPENDENCY_FAILURE_LAYER,
            code="rebuild_verification_environment_drift",
        )
    collection_hashes = verification.get("collection_nodeids_sha256")
    if (
        not isinstance(collection_hashes, dict)
        or set(collection_hashes) != set(SUITES)
        or collection_hashes.get(suite)
        != collection_manifest["nodeids_sha256"]
    ):
        return TestGateFailure(
            layer=COLLECTION_FAILURE_LAYER,
            code="rebuild_verification_collection_drift",
        )
    return None


def run_test_gate(
    suite: str,
    *,
    evidence_dir: str | Path,
    repo_root: str | Path = REPO_ROOT,
    environment: Mapping[str, str] | None = None,
    expected_environment_manifest: str | Path | None = None,
    rebuild_verification: str | Path | None = None,
    identity_only: bool = False,
) -> TestGateResult:
    if suite not in SUITE_NAMES:
        raise ValueError(f"unknown test suite: {suite}")

    root = Path(repo_root).absolute()
    python = root / ".venv" / "bin" / "python"
    if not python.is_file():
        raise TestEnvironmentError(
            f"repository interpreter is missing: {python}"
        )
    external_tool_directories = _resolve_external_tool_directories()

    evidence = Path(evidence_dir)
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    source_environment = (
        os.environ if environment is None else environment
    )
    clean_environment = {
        key: source_environment[key]
        for key in PASSTHROUGH_ENVIRONMENT_KEYS
        if key in source_environment
    }
    clean_environment["PATH"] = os.pathsep.join(
        (
            str(root / ".venv" / "bin"),
            *(str(path) for path in external_tool_directories),
            *MINIMAL_SYSTEM_PATH,
        )
    )

    preflight_capture = _run_bounded_with_evidence(
        (
            str(python),
            "-c",
            PREFLIGHT_PROGRAM,
            str(python),
            str(root / ".venv"),
            str(root),
            REQUIREMENTS_INPUT,
            PYTEST_CONFIG,
            json.dumps(EXPECTED_DEPENDENCIES, sort_keys=True),
        ),
        timeout_seconds=PREFLIGHT_TIMEOUT_SECONDS,
        heartbeat_seconds=HEARTBEAT_SECONDS,
        output_path=evidence / "preflight.log",
        summary_path=evidence / "preflight.json",
        cwd=root,
        env=clean_environment,
        capture_output=True,
    )
    preflight = preflight_capture.command
    if preflight.returncode != 0 or preflight.timed_out:
        return TestGateResult(
            preflight=preflight,
            collection=None,
            pytest=None,
            failure=_failure(
                evidence,
                layer=DEPENDENCY_FAILURE_LAYER,
                code=(
                    "preflight_timed_out"
                    if preflight.timed_out
                    else "preflight_failed"
                ),
            ),
        )
    manifest = _parse_preflight_manifest(preflight_capture.output)
    _write_private_json(evidence / "environment-manifest.json", manifest)
    if expected_environment_manifest is not None:
        expected = _read_json_object(
            Path(expected_environment_manifest).absolute()
        )
        if manifest != expected:
            return TestGateResult(
                preflight=preflight,
                collection=None,
                pytest=None,
                failure=_failure(
                    evidence,
                    layer=DEPENDENCY_FAILURE_LAYER,
                    code="environment_manifest_drift",
                ),
            )
    if suite == "preflight":
        return TestGateResult(
            preflight=preflight,
            collection=None,
            pytest=None,
            failure=None,
        )

    specification = SUITES[suite]
    collection_capture = _run_bounded_with_evidence(
        (
            str(python),
            "-m",
            "pytest",
            "--collect-only",
            *specification.pytest_arguments,
        ),
        timeout_seconds=COLLECTION_TIMEOUT_SECONDS,
        heartbeat_seconds=HEARTBEAT_SECONDS,
        output_path=evidence / f"{suite}.collection.log",
        summary_path=evidence / f"{suite}.collection.json",
        cwd=root,
        env=clean_environment,
        capture_output=True,
    )
    collection = collection_capture.command
    if collection.returncode != 0 or collection.timed_out:
        return TestGateResult(
            preflight=preflight,
            collection=collection,
            pytest=None,
            failure=_failure(
                evidence,
                layer=COLLECTION_FAILURE_LAYER,
                code=(
                    "collect_only_timed_out"
                    if collection.timed_out
                    else "collect_only_failed"
                ),
            ),
        )
    try:
        collection_manifest = _collection_manifest(
            suite=suite,
            output=collection_capture.output,
            environment_manifest=manifest,
        )
    except TestEnvironmentError:
        return TestGateResult(
            preflight=preflight,
            collection=collection,
            pytest=None,
            failure=_failure(
                evidence,
                layer=COLLECTION_FAILURE_LAYER,
                code="collect_only_nodeids_invalid",
            ),
        )
    _write_private_json(
        evidence / f"{suite}.collection-manifest.json",
        collection_manifest,
    )
    if identity_only:
        return TestGateResult(
            preflight=preflight,
            collection=collection,
            pytest=None,
            failure=None,
        )
    if rebuild_verification is None:
        return TestGateResult(
            preflight=preflight,
            collection=collection,
            pytest=None,
            failure=_failure(
                evidence,
                layer=DEPENDENCY_FAILURE_LAYER,
                code="rebuild_verification_missing",
            ),
        )
    verification = _read_json_object(
        Path(rebuild_verification).absolute()
    )
    admission_failure = _rebuild_admission_failure(
        verification,
        suite=suite,
        environment_manifest=manifest,
        collection_manifest=collection_manifest,
    )
    if admission_failure is not None:
        return TestGateResult(
            preflight=preflight,
            collection=collection,
            pytest=None,
            failure=_failure(
                evidence,
                layer=admission_failure.layer,
                code=admission_failure.code,
            ),
        )

    pytest_capture = _run_bounded_with_evidence(
        (
            str(python),
            "-m",
            "pytest",
            *specification.pytest_arguments,
        ),
        timeout_seconds=specification.timeout_seconds,
        heartbeat_seconds=HEARTBEAT_SECONDS,
        output_path=evidence / f"{suite}.log",
        summary_path=evidence / f"{suite}.json",
        cwd=root,
        env=clean_environment,
    )
    pytest_result = pytest_capture.command
    return TestGateResult(
        preflight=preflight,
        collection=collection,
        pytest=pytest_result,
        failure=None,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a fixed test suite with repository .venv preflight."
        )
    )
    parser.add_argument("suite", choices=SUITE_NAMES)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--expected-environment-manifest")
    parser.add_argument("--rebuild-verification")
    parser.add_argument("--identity-only", action="store_true")
    return parser


def _result_returncode(result: BoundedCommandResult) -> int:
    if result.timed_out:
        return 124
    return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = run_test_gate(
            arguments.suite,
            evidence_dir=arguments.evidence_dir,
            expected_environment_manifest=(
                arguments.expected_environment_manifest
            ),
            rebuild_verification=arguments.rebuild_verification,
            identity_only=arguments.identity_only,
        )
    except (TestEnvironmentError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if result.failure is not None:
        return 3
    if result.pytest is None:
        return _result_returncode(result.preflight)
    return _result_returncode(result.pytest)


if __name__ == "__main__":
    raise SystemExit(main())
