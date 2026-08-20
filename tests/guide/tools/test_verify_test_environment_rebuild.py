from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import stat


SUITES = ("focused", "full", "runtime", "all")


def _verifier_module():
    return importlib.import_module(
        "tools.guide_gates.verify_test_environment_rebuild"
    )


def _json_sha256(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _environment_manifest(
    *,
    installed_distributions_sha256: str = "a" * 64,
    sys_executable: str = (
        "/private/tmp/xiaoro-test-gate-repro/.venv/bin/python"
    ),
) -> dict[str, object]:
    return {
        "artifact_hashes_locked": False,
        "installed_distribution_count": 42,
        "installed_distributions_sha256": (
            installed_distributions_sha256
        ),
        "pytest_guide_ini_sha256": "b" * 64,
        "python_version": "3.11.1 (main, reproducible build)",
        "requirements_input_sha256": "c" * 64,
        "residual_risks": [
            "installed_versions_do_not_lock_artifact_bytes"
        ],
        "schema_version": "guide-test-environment-v1",
        "sys_executable": sys_executable,
    }


def _environment_identity_sha256(
    manifest: dict[str, object],
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


def _write_rebuild_evidence(
    root: Path,
    *,
    environment_manifest: dict[str, object] | None = None,
    changed_suite: str | None = None,
) -> None:
    manifest = environment_manifest or _environment_manifest()
    environment_sha256 = _json_sha256(manifest)
    for index, suite in enumerate(SUITES):
        suite_root = root / suite
        suite_root.mkdir(parents=True)
        (suite_root / "environment-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        nodeids = [
            f"tests/guide/{suite}/test_contract.py::test_{index}",
            f"tests/guide/{suite}/test_identity.py::test_{index}",
        ]
        if suite == changed_suite:
            nodeids.append(
                f"tests/guide/{suite}/test_drift.py::test_{index}"
            )
        normalized = "".join(f"{nodeid}\n" for nodeid in sorted(nodeids))
        collection_manifest = {
            "environment_manifest_sha256": environment_sha256,
            "nodeid_count": len(nodeids),
            "nodeids_sha256": hashlib.sha256(
                normalized.encode("utf-8")
            ).hexdigest(),
            "schema_version": "guide-test-collection-v1",
            "suite": suite,
        }
        (suite_root / f"{suite}.collection-manifest.json").write_text(
            json.dumps(collection_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _write_unreadable_rebuild_evidence(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "environment-manifest.json").write_text(
        "{not-json",
        encoding="utf-8",
    )


def _assert_evidence_roots_not_distinct(
    verifier,
    first: Path,
    second: Path,
    tmp_path: Path,
) -> None:
    result = verifier.verify_test_environment_rebuild(
        first,
        second,
        state_path=tmp_path / "stop-loss.json",
        output_path=tmp_path / "verification.json",
    )

    assert result.status == "failed"
    assert result.failure_layer == (
        "test_environment.dependency_resolution"
    )
    assert result.failure_code == "evidence_roots_not_distinct"
    assert result.consecutive_failures == 1


def test_verifier_rejects_same_evidence_path_before_reading(
    tmp_path: Path,
) -> None:
    verifier = _verifier_module()
    evidence = tmp_path / "fresh"
    _write_unreadable_rebuild_evidence(evidence)

    _assert_evidence_roots_not_distinct(
        verifier,
        evidence,
        evidence,
        tmp_path,
    )


def test_verifier_rejects_resolved_same_evidence_path_before_reading(
    tmp_path: Path,
) -> None:
    verifier = _verifier_module()
    evidence = tmp_path / "fresh"
    _write_unreadable_rebuild_evidence(evidence)
    nested = evidence / "nested"
    nested.mkdir()
    resolved_alias = nested / ".."
    assert evidence != resolved_alias
    assert evidence.resolve() == resolved_alias.resolve()

    _assert_evidence_roots_not_distinct(
        verifier,
        evidence,
        resolved_alias,
        tmp_path,
    )


def test_verifier_rejects_same_directory_inode_before_reading(
    tmp_path: Path,
) -> None:
    verifier = _verifier_module()
    evidence = tmp_path / "fresh"
    _write_unreadable_rebuild_evidence(evidence)
    inode_alias = tmp_path / "fresh-inode-alias"
    inode_alias.symlink_to(evidence, target_is_directory=True)
    assert evidence != inode_alias
    assert evidence.stat().st_ino == inode_alias.stat().st_ino

    _assert_evidence_roots_not_distinct(
        verifier,
        evidence,
        inode_alias,
        tmp_path,
    )


def test_verifier_accepts_two_complete_matching_fresh_rebuilds(
    tmp_path: Path,
) -> None:
    verifier = _verifier_module()
    first = tmp_path / "fresh-1"
    second = tmp_path / "fresh-2"
    _write_rebuild_evidence(first)
    _write_rebuild_evidence(second)
    state_path = tmp_path / "stop-loss.json"
    output_path = tmp_path / "verification.json"

    result = verifier.verify_test_environment_rebuild(
        first,
        second,
        state_path=state_path,
        output_path=output_path,
    )

    assert result.status == "passed"
    assert result.failure_layer is None
    assert result.failure_code is None
    assert result.consecutive_failures == 0
    assert result.environment_identity_sha256 == (
        _environment_identity_sha256(_environment_manifest())
    )
    assert set(result.collection_nodeids_sha256) == set(SUITES)
    assert result.residual_risks == (
        "installed_versions_do_not_lock_artifact_bytes",
    )
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["status"] == "passed"
    assert output["artifact_hashes_locked"] is False
    assert output["collection_nodeids_sha256"] == (
        result.collection_nodeids_sha256
    )
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600


def test_verifier_identity_is_location_independent_but_audits_executable(
    tmp_path: Path,
) -> None:
    verifier = _verifier_module()
    first = tmp_path / "fresh-1"
    second = tmp_path / "fresh-2"
    first_executable = "/private/tmp/fresh-1/.venv/bin/python"
    second_executable = "/private/tmp/fresh-2/.venv/bin/python"
    first_manifest = _environment_manifest(
        sys_executable=first_executable
    )
    second_manifest = _environment_manifest(
        sys_executable=second_executable
    )
    _write_rebuild_evidence(
        first,
        environment_manifest=first_manifest,
    )
    _write_rebuild_evidence(
        second,
        environment_manifest=second_manifest,
    )
    output_path = tmp_path / "verification.json"

    result = verifier.verify_test_environment_rebuild(
        first,
        second,
        state_path=tmp_path / "stop-loss.json",
        output_path=output_path,
    )

    assert result.status == "passed"
    assert result.environment_identity_sha256 == (
        _environment_identity_sha256(first_manifest)
    )
    assert json.loads(
        (first / "focused" / "environment-manifest.json").read_text(
            encoding="utf-8"
        )
    )["sys_executable"] == first_executable
    assert json.loads(
        (second / "focused" / "environment-manifest.json").read_text(
            encoding="utf-8"
        )
    )["sys_executable"] == second_executable
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["environment_identity_sha256"] == (
        result.environment_identity_sha256
    )


def test_verifier_reports_typed_collection_drift(
    tmp_path: Path,
) -> None:
    verifier = _verifier_module()
    first = tmp_path / "fresh-1"
    second = tmp_path / "fresh-2"
    _write_rebuild_evidence(first)
    _write_rebuild_evidence(second, changed_suite="runtime")

    result = verifier.verify_test_environment_rebuild(
        first,
        second,
        state_path=tmp_path / "stop-loss.json",
        output_path=tmp_path / "verification.json",
    )

    assert result.status == "failed"
    assert result.failure_layer == "test_environment.collection"
    assert result.failure_code == "collection_nodeids_drift"
    assert result.consecutive_failures == 1
    assert result.collection_nodeids_sha256 == {}


def test_verifier_rejects_mixed_executables_within_one_rebuild(
    tmp_path: Path,
) -> None:
    verifier = _verifier_module()
    first = tmp_path / "fresh-1"
    second = tmp_path / "fresh-2"
    _write_rebuild_evidence(first)
    _write_rebuild_evidence(second)
    runtime_root = second / "runtime"
    runtime_manifest_path = runtime_root / "environment-manifest.json"
    runtime_manifest = json.loads(
        runtime_manifest_path.read_text(encoding="utf-8")
    )
    runtime_manifest["sys_executable"] = (
        "/private/tmp/foreign/.venv/bin/python"
    )
    runtime_manifest_path.write_text(
        json.dumps(runtime_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    collection_path = runtime_root / "runtime.collection-manifest.json"
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    collection["environment_manifest_sha256"] = _json_sha256(
        runtime_manifest
    )
    collection_path.write_text(
        json.dumps(collection, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = verifier.verify_test_environment_rebuild(
        first,
        second,
        state_path=tmp_path / "stop-loss.json",
        output_path=tmp_path / "verification.json",
    )

    assert result.status == "failed"
    assert result.failure_layer == (
        "test_environment.dependency_resolution"
    )
    assert result.failure_code == "environment_manifest_internal_drift"


def test_dependency_resolution_second_failure_blocks_third_before_evidence(
    tmp_path: Path,
) -> None:
    verifier = _verifier_module()
    first = tmp_path / "fresh-1"
    second = tmp_path / "fresh-2"
    _write_rebuild_evidence(first)
    _write_rebuild_evidence(
        second,
        environment_manifest=_environment_manifest(
            installed_distributions_sha256="d" * 64,
        ),
    )
    state_path = tmp_path / "stop-loss.json"

    first_failure = verifier.verify_test_environment_rebuild(
        first,
        second,
        state_path=state_path,
        output_path=tmp_path / "failure-1.json",
    )
    second_failure = verifier.verify_test_environment_rebuild(
        first,
        second,
        state_path=state_path,
        output_path=tmp_path / "failure-2.json",
    )
    third = verifier.verify_test_environment_rebuild(
        tmp_path / "must-not-be-read-1",
        tmp_path / "must-not-be-read-2",
        state_path=state_path,
        output_path=tmp_path / "blocked-3.json",
    )

    assert first_failure.status == "failed"
    assert first_failure.failure_layer == (
        "test_environment.dependency_resolution"
    )
    assert first_failure.failure_code == "environment_identity_drift"
    assert first_failure.consecutive_failures == 1
    assert second_failure.status == "failed"
    assert second_failure.consecutive_failures == 2
    assert third.status == "blocked"
    assert third.failure_layer == "test_environment.dependency_resolution"
    assert third.failure_code == "third_execution_rejected"
    assert third.consecutive_failures == 2
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state == {
        "blocked": True,
        "consecutive_failures": 2,
        "failure_layer": "test_environment.dependency_resolution",
        "schema_version": "guide-test-stop-loss-v1",
    }
    assert stat.S_IMODE(
        (tmp_path / "blocked-3.json").stat().st_mode
    ) == 0o600
