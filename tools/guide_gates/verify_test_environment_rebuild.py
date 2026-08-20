"""Verify two fresh test-environment rebuild evidence trees."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

if __package__:
    from tools.guide_gates.private_output_io import (
        open_private_path,
        verify_path_binding,
        write_json_fd,
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
    from test_environment_identity import (
        stable_environment_identity_sha256,
    )


SUITES = ("focused", "full", "runtime", "all")
DEPENDENCY_FAILURE_LAYER = "test_environment.dependency_resolution"
COLLECTION_FAILURE_LAYER = "test_environment.collection"
STOP_LOSS_SCHEMA = "guide-test-stop-loss-v1"
VERIFICATION_SCHEMA = "guide-test-environment-rebuild-verification-v2"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RebuildVerificationResult:
    status: str
    failure_layer: str | None
    failure_code: str | None
    consecutive_failures: int
    environment_identity_sha256: str | None
    collection_nodeids_sha256: dict[str, str]
    artifact_hashes_locked: bool
    residual_risks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _EvidenceSnapshot:
    environment_manifest: dict[str, Any]
    environment_manifest_sha256: str
    environment_identity_sha256: str
    collection_nodeids_sha256: dict[str, str]
    collection_nodeid_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class _StopLossState:
    failure_layer: str | None = None
    consecutive_failures: int = 0
    blocked: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "consecutive_failures": self.consecutive_failures,
            "failure_layer": self.failure_layer,
            "schema_version": STOP_LOSS_SCHEMA,
        }


class RebuildEvidenceError(RuntimeError):
    """Raised when rebuild evidence violates its typed contract."""

    def __init__(self, layer: str, code: str) -> None:
        super().__init__(f"{layer}: {code}")
        self.layer = layer
        self.code = code


class StopLossStateError(RuntimeError):
    """Raised when persistent stop-loss state is invalid."""


def _json_sha256(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _read_json_path(path: Path) -> dict[str, Any]:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise OSError("evidence must be a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 64 * 1024):
            chunks.append(chunk)
        verify_path_binding(path, descriptor)
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OSError("evidence must contain one JSON object") from exc
    if not isinstance(payload, dict):
        raise OSError("evidence must contain one JSON object")
    return payload


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            f"invalid_{field}",
        )
    return value


def _validate_environment_manifest(
    payload: dict[str, Any],
) -> dict[str, Any]:
    expected_fields = {
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
    if set(payload) != expected_fields:
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "environment_manifest_fields_invalid",
        )
    if payload["schema_version"] != "guide-test-environment-v1":
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "environment_manifest_schema_invalid",
        )
    executable = payload["sys_executable"]
    if not isinstance(executable, str) or not Path(executable).is_absolute():
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "sys_executable_not_absolute",
        )
    python_version = payload["python_version"]
    if not isinstance(python_version, str) or not python_version:
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "python_version_invalid",
        )
    count = payload["installed_distribution_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "installed_distribution_count_invalid",
        )
    for field in (
        "installed_distributions_sha256",
        "pytest_guide_ini_sha256",
        "requirements_input_sha256",
    ):
        _require_sha256(payload[field], field)
    artifact_hashes_locked = payload["artifact_hashes_locked"]
    if not isinstance(artifact_hashes_locked, bool):
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "artifact_hash_identity_invalid",
        )
    residual_risks = payload["residual_risks"]
    if (
        not isinstance(residual_risks, list)
        or any(not isinstance(item, str) for item in residual_risks)
        or (not artifact_hashes_locked and not residual_risks)
    ):
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "artifact_hash_residual_invalid",
        )
    return payload


def _validate_collection_manifest(
    payload: dict[str, Any],
    *,
    environment_manifest_sha256: str,
) -> tuple[str, str, int]:
    expected_fields = {
        "environment_manifest_sha256",
        "nodeid_count",
        "nodeids_sha256",
        "schema_version",
        "suite",
    }
    if set(payload) != expected_fields:
        raise RebuildEvidenceError(
            COLLECTION_FAILURE_LAYER,
            "collection_manifest_fields_invalid",
        )
    if payload["schema_version"] != "guide-test-collection-v1":
        raise RebuildEvidenceError(
            COLLECTION_FAILURE_LAYER,
            "collection_manifest_schema_invalid",
        )
    suite = payload["suite"]
    if suite not in SUITES:
        raise RebuildEvidenceError(
            COLLECTION_FAILURE_LAYER,
            "collection_suite_invalid",
        )
    if payload["environment_manifest_sha256"] != (
        environment_manifest_sha256
    ):
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "collection_environment_identity_drift",
        )
    nodeids_sha256 = _require_sha256(
        payload["nodeids_sha256"],
        "nodeids_sha256",
    )
    nodeid_count = payload["nodeid_count"]
    if (
        isinstance(nodeid_count, bool)
        or not isinstance(nodeid_count, int)
        or nodeid_count <= 0
    ):
        raise RebuildEvidenceError(
            COLLECTION_FAILURE_LAYER,
            "collection_nodeid_count_invalid",
        )
    return suite, nodeids_sha256, nodeid_count


def _evidence_files(root: Path, filename: str) -> list[Path]:
    try:
        status = root.lstat()
    except OSError as exc:
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "evidence_root_unavailable",
        ) from exc
    if not stat.S_ISDIR(status.st_mode) or root.is_symlink():
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "evidence_root_invalid",
        )
    return sorted(root.rglob(filename))


def _load_evidence_snapshot(root: Path) -> _EvidenceSnapshot:
    environment_paths = _evidence_files(root, "environment-manifest.json")
    if not environment_paths:
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "environment_manifest_missing",
        )
    try:
        environment_manifests = [
            _validate_environment_manifest(_read_json_path(path))
            for path in environment_paths
        ]
    except OSError as exc:
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "environment_manifest_unreadable",
        ) from exc
    environment_hashes = {
        _json_sha256(manifest) for manifest in environment_manifests
    }
    if len(environment_hashes) != 1:
        raise RebuildEvidenceError(
            DEPENDENCY_FAILURE_LAYER,
            "environment_manifest_internal_drift",
        )
    environment_manifest = environment_manifests[0]
    environment_sha256 = environment_hashes.pop()

    collection_paths = _evidence_files(root, "*.collection-manifest.json")
    nodeids_by_suite: dict[str, str] = {}
    counts_by_suite: dict[str, int] = {}
    try:
        for path in collection_paths:
            suite, nodeids_sha256, nodeid_count = (
                _validate_collection_manifest(
                    _read_json_path(path),
                    environment_manifest_sha256=environment_sha256,
                )
            )
            if suite in nodeids_by_suite:
                raise RebuildEvidenceError(
                    COLLECTION_FAILURE_LAYER,
                    "collection_suite_duplicated",
                )
            nodeids_by_suite[suite] = nodeids_sha256
            counts_by_suite[suite] = nodeid_count
    except OSError as exc:
        raise RebuildEvidenceError(
            COLLECTION_FAILURE_LAYER,
            "collection_manifest_unreadable",
        ) from exc
    if set(nodeids_by_suite) != set(SUITES):
        raise RebuildEvidenceError(
            COLLECTION_FAILURE_LAYER,
            "collection_suites_incomplete",
        )
    return _EvidenceSnapshot(
        environment_manifest=environment_manifest,
        environment_manifest_sha256=environment_sha256,
        environment_identity_sha256=(
            stable_environment_identity_sha256(environment_manifest)
        ),
        collection_nodeids_sha256=nodeids_by_suite,
        collection_nodeid_counts=counts_by_suite,
    )


def _open_locked_state(path: Path) -> int:
    descriptor = os.open(
        path,
        os.O_RDWR
        | os.O_CREAT
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
        0o600,
    )
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise StopLossStateError("stop-loss state must be regular")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        verify_path_binding(path, descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_state(descriptor: int) -> _StopLossState:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 64 * 1024):
        chunks.append(chunk)
    if not chunks:
        return _StopLossState()
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StopLossStateError("stop-loss state is invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != STOP_LOSS_SCHEMA
        or set(payload)
        != {
            "blocked",
            "consecutive_failures",
            "failure_layer",
            "schema_version",
        }
    ):
        raise StopLossStateError("stop-loss state is invalid")
    state = _StopLossState(
        failure_layer=payload["failure_layer"],
        consecutive_failures=payload["consecutive_failures"],
        blocked=payload["blocked"],
    )
    if (
        state.failure_layer is not None
        and not isinstance(state.failure_layer, str)
    ) or (
        isinstance(state.consecutive_failures, bool)
        or state.consecutive_failures not in (0, 1, 2)
    ) or not isinstance(state.blocked, bool):
        raise StopLossStateError("stop-loss state is invalid")
    if state.blocked != (state.consecutive_failures == 2):
        raise StopLossStateError("stop-loss state is inconsistent")
    return state


def _failed_state(
    current: _StopLossState,
    failure_layer: str,
) -> _StopLossState:
    failures = (
        current.consecutive_failures + 1
        if current.failure_layer == failure_layer
        else 1
    )
    failures = min(failures, 2)
    return _StopLossState(
        failure_layer=failure_layer,
        consecutive_failures=failures,
        blocked=failures == 2,
    )


def _result_payload(
    result: RebuildVerificationResult,
) -> dict[str, Any]:
    payload = asdict(result)
    payload["schema_version"] = VERIFICATION_SCHEMA
    return payload


def _same_evidence_root(first: Path, second: Path) -> bool:
    if first == second:
        return True
    try:
        if first.resolve() == second.resolve():
            return True
    except (OSError, RuntimeError):
        pass
    try:
        return first.samefile(second)
    except OSError:
        return False


def verify_test_environment_rebuild(
    first_evidence: str | Path,
    second_evidence: str | Path,
    *,
    state_path: str | Path,
    output_path: str | Path,
) -> RebuildVerificationResult:
    """Compare two rebuilds and persist same-layer stop-loss state."""
    state_file = Path(state_path).absolute()
    output_file = Path(output_path).absolute()
    output_descriptor = open_private_path(output_file)
    try:
        state_descriptor = _open_locked_state(state_file)
    except BaseException:
        os.close(output_descriptor)
        raise
    try:
        state = _read_state(state_descriptor)
        if state.blocked:
            result = RebuildVerificationResult(
                status="blocked",
                failure_layer=state.failure_layer,
                failure_code="third_execution_rejected",
                consecutive_failures=state.consecutive_failures,
                environment_identity_sha256=None,
                collection_nodeids_sha256={},
                artifact_hashes_locked=False,
                residual_risks=(),
            )
            next_state = state
        else:
            try:
                first_root = Path(first_evidence).absolute()
                second_root = Path(second_evidence).absolute()
                if _same_evidence_root(first_root, second_root):
                    raise RebuildEvidenceError(
                        DEPENDENCY_FAILURE_LAYER,
                        "evidence_roots_not_distinct",
                    )
                first = _load_evidence_snapshot(first_root)
                second = _load_evidence_snapshot(second_root)
                if first.environment_identity_sha256 != (
                    second.environment_identity_sha256
                ):
                    raise RebuildEvidenceError(
                        DEPENDENCY_FAILURE_LAYER,
                        "environment_identity_drift",
                    )
                if (
                    first.collection_nodeids_sha256
                    != second.collection_nodeids_sha256
                    or first.collection_nodeid_counts
                    != second.collection_nodeid_counts
                ):
                    raise RebuildEvidenceError(
                        COLLECTION_FAILURE_LAYER,
                        "collection_nodeids_drift",
                    )
            except RebuildEvidenceError as exc:
                next_state = _failed_state(state, exc.layer)
                result = RebuildVerificationResult(
                    status="failed",
                    failure_layer=exc.layer,
                    failure_code=exc.code,
                    consecutive_failures=(
                        next_state.consecutive_failures
                    ),
                    environment_identity_sha256=None,
                    collection_nodeids_sha256={},
                    artifact_hashes_locked=False,
                    residual_risks=(),
                )
            else:
                next_state = _StopLossState()
                result = RebuildVerificationResult(
                    status="passed",
                    failure_layer=None,
                    failure_code=None,
                    consecutive_failures=0,
                    environment_identity_sha256=(
                        first.environment_identity_sha256
                    ),
                    collection_nodeids_sha256=dict(
                        first.collection_nodeids_sha256
                    ),
                    artifact_hashes_locked=bool(
                        first.environment_manifest[
                            "artifact_hashes_locked"
                        ]
                    ),
                    residual_risks=tuple(
                        first.environment_manifest["residual_risks"]
                    ),
                )

        verify_path_binding(state_file, state_descriptor)
        write_json_fd(state_descriptor, next_state.payload())
        verify_path_binding(state_file, state_descriptor)
        verify_path_binding(output_file, output_descriptor)
        write_json_fd(output_descriptor, _result_payload(result))
        verify_path_binding(output_file, output_descriptor)
        return result
    finally:
        fcntl.flock(state_descriptor, fcntl.LOCK_UN)
        os.close(state_descriptor)
        os.close(output_descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two complete fresh test-environment evidence trees."
        )
    )
    parser.add_argument("first_evidence")
    parser.add_argument("second_evidence")
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = verify_test_environment_rebuild(
            arguments.first_evidence,
            arguments.second_evidence,
            state_path=arguments.state_file,
            output_path=arguments.output,
        )
    except (OSError, StopLossStateError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if result.status == "passed":
        return 0
    if result.status == "blocked":
        return 4
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
