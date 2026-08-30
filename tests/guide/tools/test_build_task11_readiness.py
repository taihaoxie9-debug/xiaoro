from __future__ import annotations

import base64
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from tools.guide_gates import attempt_ledger
from tools.guide_gates import build_task11_readiness as readiness
from tools.guide_gates import run_task11_independent_audit as independent_audit
from tools.guide_gates import run_zero_api_runtime as zero_runtime


TASK12_RUNTIME_DATA_PATHS = (
    "data/canonical/core_products_v1_manifest.json",
    "data/canonical/core_products_v1.jsonl",
    "data/canonical/seed_product_images_v1_manifest.json",
    "data/canonical/seed_product_images_v1.jsonl",
)
SEMANTIC_MATRIX_FIXTURE_PATH = (
    "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
)
PRODUCTION_MATRIX_FIXTURE_PATH = (
    "tests/fixtures/guide/intent/"
    "task11_production_path_matrix_v1.jsonl"
)
BOUNDED_BROWSER_TOOL_PATH = (
    "tools/guide_gates/run_mainline_contract_browser_audit.py"
)
FIXTURE_ROOT_ARTIFACTS = (
    "browser-requests.json",
    "chromium-netlog.json",
    "consumed-runtime-health-challenge.json",
    "runtime-identity.json",
    "sandbox-audit.json",
    "sandbox-profile.sb",
    "seatbelt.raw.ndjson",
)
FIXTURE_TURN_ARTIFACTS = (
    "console.json",
    "network.json",
    "presentation-contract.json",
    "request.json",
    "sandbox-audit.json",
    "screenshot.png",
    "stream.sse",
    "terminal-dom.json",
)
TEST_RUNTIME_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    bytes(range(32))
)
TEST_RUNTIME_PUBLIC_KEY = (
    base64.urlsafe_b64encode(
        TEST_RUNTIME_PRIVATE_KEY.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    .decode("ascii")
    .rstrip("=")
)
IDENTITY_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-identity-v1\x00"
)
CHALLENGE_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-challenge-v1\x00"
)
CHILD_REPORT_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-child-report-v1\x00"
)
PARENT_REPORT_SIGNATURE_DOMAIN = (
    b"xiaoro-guide-zero-api-runtime-parent-report-v1\x00"
)


def test_readiness_requires_clarification_browser_fixture() -> None:
    assert readiness._FIXTURE_TURN_IDS == (
        "fixture-explore-recommendation",
        "fixture-fit-recommendation",
        "fixture-fit-clarification",
        "fixture-product-knowledge",
        "fixture-comparison",
        "fixture-image-identity",
        "fixture-image-fit-recommendation",
        "fixture-multi-image-comparison",
    )


def test_readiness_task12_execution_surface_includes_runtime_auth() -> None:
    assert (
        "tools/guide_gates/runtime_auth.py"
        in readiness._TASK12_EXECUTION_PATHS
    )


def test_readiness_task12_execution_surface_includes_zero_api_runtime() -> None:
    assert (
        "tools/guide_gates/run_zero_api_runtime.py"
        in readiness._TASK12_EXECUTION_PATHS
    )


def test_readiness_task12_execution_surface_matches_independent_audit() -> None:
    assert set(readiness._TASK12_EXECUTION_PATHS) == {
        *independent_audit.TASK12_TOOL_PATHS,
        *independent_audit.TASK12_TEST_PATHS,
        *independent_audit.TASK12_FIXTURE_PATHS,
        *independent_audit.TASK12_RUNTIME_DATA_PATHS,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sign_test_payload(
    domain: bytes,
    payload: dict[str, object],
    *,
    private_key: Ed25519PrivateKey = TEST_RUNTIME_PRIVATE_KEY,
) -> str:
    return (
        base64.urlsafe_b64encode(
            private_key.sign(
                domain + _canonical_bytes(payload)
            )
        )
        .decode("ascii")
        .rstrip("=")
    )


def _runtime_identity_bytes(
    manifest_path: Path,
    *,
    pid: int = 4100,
) -> bytes:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity: dict[str, object] = {
        "schema_version": "guide-zero-api-runtime-identity-v1",
        "candidate_manifest_path": str(manifest_path.resolve()),
        "candidate_manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "plan_revision": manifest["plan_revision"],
        "code_revision": manifest["candidate_head"],
        "protected_payload_sha256": (
            manifest["protected_payload_sha256"]
        ),
        "process_identity": {"pid": pid},
        "host": "127.0.0.1",
        "port": 8820,
        "state_dir": str(manifest_path.parent / "runtime-state"),
        "runtime_nonce": "8" * 64,
        "runtime_public_key": TEST_RUNTIME_PUBLIC_KEY,
    }
    identity["identity_sha256"] = sha256(
        _canonical_bytes(identity)
    ).hexdigest()
    identity["identity_signature"] = _sign_test_payload(
        IDENTITY_SIGNATURE_DOMAIN,
        identity,
    )
    return _canonical_bytes(identity)


def _challenge_payload(
    *,
    runtime_identity_sha256: str,
    challenge: str,
) -> dict[str, str]:
    unsigned = {
        "schema_version": "guide-zero-api-runtime-challenge-v1",
        "runtime_identity_sha256": runtime_identity_sha256,
        "challenge": challenge,
    }
    signed = {
        **unsigned,
        "challenge_sha256": sha256(
            _canonical_bytes(unsigned)
        ).hexdigest(),
    }
    return {
        **signed,
        "challenge_signature": _sign_test_payload(
            CHALLENGE_SIGNATURE_DOMAIN,
            signed,
        ),
    }


def _write_indexed_fixture_summary(
    path: Path,
    *,
    viewport: str,
    runtime_identity_bytes: bytes | None = None,
    challenge: str | None = None,
) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    identity_bytes = (
        runtime_identity_bytes
        if runtime_identity_bytes is not None
        else _canonical_bytes({})
    )
    runtime_identity_sha256 = sha256(identity_bytes).hexdigest()
    challenge_payload = _challenge_payload(
        runtime_identity_sha256=runtime_identity_sha256,
        challenge=challenge or ("2" if viewport == "desktop" else "3") * 64,
    )
    for relative in FIXTURE_ROOT_ARTIFACTS:
        artifact = directory / relative
        if relative == "runtime-identity.json":
            artifact.write_bytes(identity_bytes)
        elif relative == "consumed-runtime-health-challenge.json":
            artifact.write_bytes(_canonical_bytes(challenge_payload))
        else:
            artifact.write_bytes(relative.encode("ascii"))
    for turn_id in readiness._FIXTURE_TURN_IDS:
        turn_dir = directory / turn_id
        turn_dir.mkdir()
        for name in FIXTURE_TURN_ARTIFACTS:
            (turn_dir / name).write_bytes(
                f"{turn_id}/{name}".encode("ascii")
            )
    artifact_index = {
        artifact.relative_to(directory).as_posix(): sha256(
            artifact.read_bytes()
        ).hexdigest()
        for artifact in sorted(directory.rglob("*"))
        if artifact.is_file() and artifact != path
    }
    _write_json(
        path,
        {
            "schema_version": (
                "guide-mainline-contract-browser-audit-v1"
            ),
            "trajectory_set": "fixture",
            "evidence_scope": "frontend_fixture_only",
            "backend_path_claim": False,
            "base_url": "http://127.0.0.1:8820",
            "viewport": viewport,
            "turn_count": len(readiness._FIXTURE_TURN_IDS),
            "invalid_clarification_count": 0,
            "turns": [
                {
                    "turn_id": turn_id,
                    "directory": turn_id,
                }
                for turn_id in readiness._FIXTURE_TURN_IDS
            ],
            "browser_request_count": 49,
            "browser_observed_non_loopback_attempt_count": 0,
            "process_tree_non_loopback_attempt_count": 0,
            "runtime_identity_sha256": runtime_identity_sha256,
            "consumed_health_challenge_sha256": (
                challenge_payload["challenge_sha256"]
            ),
            "artifact_sha256_by_path": artifact_index,
            "passed": True,
        },
    )


def _runtime_network_payload(
    manifest_path: Path,
    *,
    runtime_identity_sha256: str = "1" * 64,
    consumed_challenge_sha256s: tuple[str, ...] = ("2" * 64,),
) -> dict[str, object]:
    nonce = "9" * 64
    profile = zero_runtime._runtime_sandbox_profile(nonce)
    kernel = "/System/Library/Extensions/Sandbox.kext/Contents/MacOS/Sandbox"

    def event(
        message: str,
        *,
        process_path: str,
        sender_path: str = "",
    ) -> bytes:
        return (
            json.dumps(
                {
                    "eventType": "logEvent",
                    "processImagePath": process_path,
                    "senderImagePath": sender_path,
                    "eventMessage": message,
                },
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    raw = b"".join(
        (
            event(
                f"XIAORO_RUNTIME_SEATBELT_READY:{nonce}",
                process_path="/usr/bin/logger",
            ),
            event(
                f"XIAORO_RUNTIME_SEATBELT_CANARY_BEGIN:{nonce}:4000",
                process_path="/usr/bin/logger",
            ),
            event(
                (
                    "Sandbox: nc(4001) deny(1) "
                    f"network-outbound remote:*:9\n{nonce}"
                ),
                process_path="/kernel",
                sender_path=kernel,
            ),
            event(
                (
                    "Sandbox: nc(4002) deny(1) "
                    f"network-outbound remote:*:443\n{nonce}"
                ),
                process_path="/kernel",
                sender_path=kernel,
            ),
            event(
                (
                    f"XIAORO_RUNTIME_SEATBELT_CANARY:{nonce}:"
                    "root_child:4001:9"
                ),
                process_path="/usr/bin/logger",
            ),
            event(
                (
                    f"XIAORO_RUNTIME_SEATBELT_CANARY:{nonce}:"
                    "descendant:4002:443"
                ),
                process_path="/usr/bin/logger",
            ),
            event(
                f"XIAORO_RUNTIME_SEATBELT_CANARY_END:{nonce}:4000",
                process_path="/usr/bin/logger",
            ),
            event(
                f"XIAORO_RUNTIME_SEATBELT_BEGIN:{nonce}:4100",
                process_path="/usr/bin/logger",
            ),
            event(
                f"XIAORO_RUNTIME_SEATBELT_END:{nonce}:4100",
                process_path="/usr/bin/logger",
            ),
            event(
                f"XIAORO_RUNTIME_SEATBELT_CANARY:{nonce}:drain:4200:53",
                process_path="/usr/bin/logger",
            ),
            event(
                (
                    "Sandbox: nc(4200) deny(1) "
                    f"network-outbound remote:*:53\n{nonce}"
                ),
                process_path="/kernel",
                sender_path=kernel,
            ),
            event(
                f"XIAORO_RUNTIME_SEATBELT_DRAIN:{nonce}",
                process_path="/usr/bin/logger",
            ),
        )
    )
    child_report: dict[str, object] = {
            "schema_version": (
                "guide-zero-api-runtime-child-network-report-v1"
            ),
            "measurement": "python-runtime-guard",
            "fixture_runtime_public_key": TEST_RUNTIME_PUBLIC_KEY,
            "guard_active": True,
            "process_guard_active": True,
            "kernel_network_sandbox_active": True,
            "child_process_policy": "deny_process_creation",
            "passed": True,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "attempts": [],
            "runtime_started": True,
            "ready_identity_written": True,
            "challenge_consumed": True,
            "shutdown_consumed": True,
            "shutdown_finalized": True,
            "runtime_succeeded": True,
            "process_creation_attempt_count": 0,
            "process_creation_attempts": [],
            "candidate_manifest_sha256": sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "runtime_identity_sha256": runtime_identity_sha256,
            "consumed_health_challenge_sha256s": list(
                consumed_challenge_sha256s
            ),
    }
    child_report["runtime_report_signature"] = _sign_test_payload(
        CHILD_REPORT_SIGNATURE_DOMAIN,
        child_report,
    )
    report = zero_runtime._build_runtime_sandbox_report(
        child_report=child_report,
        fixture_runtime_public_key=TEST_RUNTIME_PUBLIC_KEY,
        sandbox_profile=profile,
        runtime_sandbox_profile=(
            zero_runtime._runtime_execution_sandbox_profile(nonce)
        ),
        measurement_nonce=nonce,
        seatbelt_raw=raw,
        logger_stderr=b"",
        logger_returncode=0,
        canary_root_pid=4000,
        runtime_root_pid=4100,
        runtime_process_group_id=4100,
        drain_canary_pid=4200,
        canary_process_groups_quiescent=True,
        process_group_quiescent=True,
    )
    report["runtime_report_signature"] = _sign_test_payload(
        PARENT_REPORT_SIGNATURE_DOMAIN,
        report,
    )
    return report


def _production_matrix_fixture_rows() -> str:
    rows = [
        json.dumps({
            "partition": (
                "semantic"
                if index < 128
                else ("bounded" if index < 137 else "state")
            ),
            "trajectory_id": (
                f"semantic-{index}"
                if index < 128
                else f"state-{(index - 128) // 4}"
            ),
            "required_state_edges": (
                [f"edge-{(index - 128) % 40}"]
                if index >= 128
                else []
            ),
        })
        for index in range(176)
    ]
    rows.append(
        json.dumps({
            "partition": "pre_decision_rejection",
            "trajectory_id": "state-11",
            "conversation_version_delta": -1,
            "expected_terminal_event": "error",
            "expected_rejection_stage": "pre_decision",
            "required_state_edges": [],
        })
    )
    return "\n".join(rows) + "\n"


def _plan(path: Path) -> None:
    task12_rows = "\n".join(
        (
            f"- Create: `{relative}`"
            if relative.startswith("tools/")
            or relative.startswith("tests/fixtures/")
            else f"- Test: `{relative}`"
        )
        for relative in readiness._TASK12_EXECUTION_PATHS
    )
    path.write_text(
        f"""
# Plan

Plan revision: task11-r1
Task 11 evidence epoch: repair-epoch-22

### Task 11: Close

**Files:**
- Modify: `app/guide/example.py`
- Test: `tests/guide/test_example.py`
- Create: `tests/fixtures/guide/example.json`
- Test: `{PRODUCTION_MATRIX_FIXTURE_PATH}`
- Test: `{SEMANTIC_MATRIX_FIXTURE_PATH}`
- Create: `tools/guide_gates/example.py`
- Delete: `tools/guide_gates/legacy.py`
- Modify: `docs/superpowers/plans/plan.md`
- Generate: `docs/audits/generated.json`
{task12_rows}

- [ ] **Step 0: Run**
""".lstrip(),
        encoding="utf-8",
    )


def _candidate(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / "app/guide").mkdir(parents=True)
    (root / "tests/guide").mkdir(parents=True)
    (root / "tests/fixtures/guide").mkdir(parents=True)
    (root / "tools/guide_gates").mkdir(parents=True)
    (root / "docs/superpowers/plans").mkdir(parents=True)
    plan = root / "docs/superpowers/plans/plan.md"
    plan.write_text("# Baseline plan\n", encoding="utf-8")
    (root / "app/guide/example.py").write_text("VALUE = 0\n")
    (root / "tests/guide/test_example.py").write_text(
        "def test_old_value(): pass\n"
    )
    (root / "tests/fixtures/guide/example.json").write_text(
        '{"version": 0}\n',
        encoding="utf-8",
    )
    semantic_fixture = root / SEMANTIC_MATRIX_FIXTURE_PATH
    semantic_fixture.parent.mkdir(parents=True, exist_ok=True)
    semantic_fixture.write_bytes(
        (
            Path(__file__).resolve().parents[3]
            / SEMANTIC_MATRIX_FIXTURE_PATH
        ).read_bytes()
    )
    production_fixture = root / PRODUCTION_MATRIX_FIXTURE_PATH
    production_fixture.parent.mkdir(parents=True, exist_ok=True)
    production_fixture.write_bytes(
        (
            Path(__file__).resolve().parents[3]
            / PRODUCTION_MATRIX_FIXTURE_PATH
        ).read_bytes()
    )
    (root / "tools/guide_gates/example.py").write_text("VALUE = 0\n")
    (root / "tools/guide_gates/legacy.py").write_text(
        "VALUE = 'legacy'\n"
    )
    for relative in readiness._RELEASE_PLAN_PATHS:
        release_plan = root / relative
        release_plan.parent.mkdir(parents=True, exist_ok=True)
        release_plan.write_text(
            "# Release plan\n",
            encoding="utf-8",
        )
    for relative in readiness._TASK12_EXECUTION_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == BOUNDED_BROWSER_TOOL_PATH:
            path.write_bytes(Path(relative).read_bytes())
        else:
            path.write_text(
                "{}\n"
                if relative.endswith(".jsonl")
                else "VALUE = 'task12-release-tool'\n",
                encoding="utf-8",
            )
    candidate_head = _initialize_git_repo(root)

    _plan(plan)
    (root / "app/guide/example.py").write_text("VALUE = 1\n")
    (root / "tests/guide/test_example.py").write_text(
        "def test_value(): pass\n"
    )
    (root / "tests/fixtures/guide/example.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (root / "tools/guide_gates/example.py").write_text("VALUE = 1\n")
    (root / "tools/guide_gates/legacy.py").unlink()
    ledger = root / readiness._MUTABLE_EVIDENCE_PATHS[0]
    attempt_ledger.initialize_ledger(ledger)
    manifest = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "repair-epoch-22"
        / "task11-candidate-manifest.json"
    )
    readiness.build_candidate_manifest(
        repo_root=root,
        plan_path=plan,
        output_path=manifest,
        candidate_head=candidate_head,
        changed_paths=(
            "app/guide/example.py",
            "tests/guide/test_example.py",
            "tests/fixtures/guide/example.json",
            "tools/guide_gates/example.py",
            "tools/guide_gates/legacy.py",
            "docs/superpowers/plans/plan.md",
        ),
        fixture_runtime_private_key_path=(
            tmp_path / "fixture-runtime-private-key.json"
        ),
        _fixture_runtime_private_key=TEST_RUNTIME_PRIVATE_KEY,
    )
    return root, manifest


def _relative_ledger_path(root: Path, ledger: Path) -> str:
    return ledger.relative_to(root).as_posix()


def _initialize_git_repo(root: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=root,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_readiness_accepts_parent_observed_runtime_canary_order(
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)

    assert readiness._runtime_network_report_passed(
        json.loads(json.dumps(_runtime_network_payload(manifest_path))),
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
    )


def _evidence(
    root: Path,
    manifest_path: Path,
) -> tuple[dict[str, Path], Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    epoch_root = manifest_path.parent
    runtime_bundle = epoch_root / "runtime-browser-evidence"
    paths = {
        "semantic_summary": (
            epoch_root / "task11-semantic-matrix-summary.json"
        ),
        "zero_api_summary": epoch_root / "task11-zero-api-summary.json",
        "network_report": epoch_root / "task11-zero-api-network.json",
        "runtime_network_report": (
            runtime_bundle / "task11-zero-api-runtime-network.json"
        ),
        "single_path_architecture": (
            epoch_root / "task11-single-path-architecture.json"
        ),
        "test_path_audit": epoch_root / "task11-test-path-audit.json",
        "production_path_summary": (
            epoch_root / "task11-production-path-summary.json"
        ),
        "independent_audit": (
            epoch_root / "task11-independent-audit.json"
        ),
        "desktop_summary": (
            runtime_bundle
            / "fixture-browser-desktop"
            / "summary.json"
        ),
        "mobile_summary": (
            runtime_bundle
            / "fixture-browser-mobile"
            / "summary.json"
        ),
    }
    _write_json(
        paths["semantic_summary"],
        {
            "schema_version": "guide-task11-semantic-summary-v1",
            "matrix_kind": "expected_contract",
            "cases_sha256": sha256(
                (root / SEMANTIC_MATRIX_FIXTURE_PATH).read_bytes()
            ).hexdigest(),
            "passed": True,
            "case_count": 128,
            "fit_count": 0,
            "explore_count": 34,
            "image_fit_count": 0,
            "recommendation_outcome_contract_gap_count": 0,
            "cross_parent_basis_count": 0,
        },
    )
    commands = readiness._zero_api_commands(
        manifest,
        python_executable=sys.executable,
    )
    _write_json(
        paths["network_report"],
        {
            "schema_version": "guide-zero-api-network-report-v1",
            "guard_active": True,
            "process_guard_active": True,
            "kernel_network_sandbox_active": True,
            "child_process_policy": "kernel_inherited_network_deny",
            "passed": True,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "attempts": [],
            "process_creation_attempt_count": 0,
            "process_creation_attempts": [],
        },
    )
    runtime_identity_bytes = _runtime_identity_bytes(manifest_path)
    runtime_identity_sha256 = sha256(
        runtime_identity_bytes
    ).hexdigest()
    desktop_challenge = _challenge_payload(
        runtime_identity_sha256=runtime_identity_sha256,
        challenge="2" * 64,
    )
    mobile_challenge = _challenge_payload(
        runtime_identity_sha256=runtime_identity_sha256,
        challenge="3" * 64,
    )
    _write_json(
        paths["runtime_network_report"],
        _runtime_network_payload(
            manifest_path,
            runtime_identity_sha256=runtime_identity_sha256,
            consumed_challenge_sha256s=(
                desktop_challenge["challenge_sha256"],
                mobile_challenge["challenge_sha256"],
            ),
        ),
    )
    _write_json(
        paths["single_path_architecture"],
        {
            "schema_version": (
                "guide-task11-single-path-architecture-v1"
            ),
            "passed": True,
            "inspected_module_count": 1,
            "inspected_modules": ["app.guide.example"],
            "violation_count": 0,
            "violations": [],
            "forbidden_symbol_count": 0,
        },
    )
    _write_json(
        paths["zero_api_summary"],
        {
            "schema_version": "guide-task11-zero-api-summary-v1",
            "passed": True,
            "guard_active": True,
            "process_guard_active": True,
            "kernel_network_sandbox_active": True,
            "child_process_policy": "kernel_inherited_network_deny",
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "process_creation_attempt_count": 0,
            "process_creation_attempts": [],
            "network_report_sha256": sha256(
                paths["network_report"].read_bytes()
            ).hexdigest(),
            "candidate_manifest_sha256": sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "protected_payload_sha256": (
                manifest["protected_payload_sha256"]
            ),
            "commands": [
                {
                    "argv": list(command),
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                }
                for command in commands
            ],
        },
    )
    _write_json(
        paths["test_path_audit"],
        {
            "schema_version": "guide-task11-test-path-audit-v1",
            "passed": True,
            "production_path_gate_count": 1,
            "invalid_production_path_claim_count": 0,
            "unprotected_fixture_dependency_count": 0,
            "gates": [
                {
                    "gate": "task11-production-path-matrix",
                    "claimed_scope": (
                        "production_path_from_turn_meaning"
                    ),
                    "real_entrypoint": "/api/v1/chat/stream",
                    "layers_executed": list(
                        readiness._RUNTIME_LAYER_ORDER
                    ),
                    "layers_bypassed": [],
                    "semantic_injection_type": (
                        "frozen_turn_meaning_provider"
                    ),
                    "runtime_evidence_source": (
                        "task11-production-path-summary"
                    ),
                    "test_files": [
                        "tests/guide/tools/"
                        "test_task11_production_path_matrix.py"
                    ],
                    "fixture_files": [
                        PRODUCTION_MATRIX_FIXTURE_PATH
                    ],
                    "case_count": 177,
                    "trajectory_count": 12,
                    "turn_count": 177,
                    "state_edge_count": 40,
                    "pre_decision_rejection_count": 1,
                }
            ],
        },
    )
    required_edges = [f"edge-{index:02d}" for index in range(40)]
    production_traces = [
        {
            "turn_id": f"turn-{index:03d}",
            "trajectory_id": (
                f"semantic-{index:03d}"
                if index < 128
                else f"state-{(index - 128) // 4:02d}"
            ),
            "partition": (
                "semantic"
                if index < 128
                else ("bounded" if index < 137 else "state")
            ),
            "translation_injection_count": 1,
            "structured_understanding_injection_count": 0,
            "compiler_call_count": 1,
            "direct_router_bypass_count": 0,
            "legacy_entrypoint_count": 0,
            "router_call_count": 1,
            "route_decision_digest": "a" * 64,
            "selected_processor_decision_digest": "a" * 64,
            "result_decision_digest": "a" * 64,
            "sse_decision_digest": "a" * 64,
            "validated_sse_sha256": "b" * 64,
            "emitted_sse_sha256": "b" * 64,
            "selected_processor": "recommendation",
            "processor_invocation_counts": {
                "recommendation": 1,
            },
            "processor_implementation_counts": {
                "TextRecommendationOrchestrator": 1,
            },
            "selected_processor_instance_entry_count": 1,
            "unregistered_processor_invocation_count": 0,
            "decision_identity_violation_count": 0,
            "execution_result_count": 1,
            "reducer_call_count": 1,
            "state_save_count": 1,
            "state_save_completed_count": 1,
            "state_backend": "SqliteConversationState",
            "processor_state_write_count": 0,
            "event_state_projection_count": 0,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "loaded_version": (
                0 if index < 128 else (index - 128) % 4
            ),
            "committed_version": (
                1 if index < 128 else (index - 128) % 4 + 1
            ),
            "expected_state_edge": "none->recommendation",
            "observed_state_edge": "none->recommendation",
            "terminal_event": "end",
            "bounded": 128 <= index < 137,
            "semantic_equivalence_passed": True,
            "accepted": True,
            "coverage_edges": (
                []
                if index < 128
                else [required_edges[(index - 128) % 40]]
            ),
            "actual_processor": "recommendation",
            "actual_intent": "recommend",
            "card_ids": [],
            "event_names": ["start", "end"],
            "observed_layers": [
                "translation",
                "compiler",
                "router",
                "processor",
                "reducer",
                "sqlite",
                "sse",
            ],
        }
        for index in range(176)
    ]
    production_traces.append({
        "turn_id": "predecision-stale-version-rejection-001",
        "trajectory_id": "state-11",
        "partition": "pre_decision_rejection",
        "rejection_stage": "pre_decision",
        "translation_injection_count": 0,
        "structured_understanding_injection_count": 0,
        "compiler_call_count": 0,
        "direct_router_bypass_count": 0,
        "legacy_entrypoint_count": 0,
        "router_call_count": 0,
        "route_decision_digest": "0" * 64,
        "selected_processor_decision_digest": "0" * 64,
        "result_decision_digest": "0" * 64,
        "sse_decision_digest": "0" * 64,
        "validated_sse_sha256": "d" * 64,
        "emitted_sse_sha256": "d" * 64,
        "selected_processor": "none",
        "processor_invocation_counts": {"recommendation": 0},
        "processor_implementation_counts": {},
        "selected_processor_instance_entry_count": 0,
        "unregistered_processor_invocation_count": 0,
        "decision_identity_violation_count": 0,
        "execution_result_count": 0,
        "reducer_call_count": 0,
        "state_save_count": 0,
        "state_save_completed_count": 0,
        "state_backend": "SqliteConversationState",
        "processor_state_write_count": 0,
        "event_state_projection_count": 0,
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
        "loaded_version": 4,
        "committed_version": 4,
        "expected_state_edge": "recommendation->recommendation",
        "observed_state_edge": "recommendation->recommendation",
        "terminal_event": "error",
        "bounded": False,
        "semantic_equivalence_passed": True,
        "accepted": False,
        "coverage_edges": [],
        "actual_processor": "none",
        "actual_intent": "",
        "card_ids": [],
        "event_names": ["start", "error"],
        "observed_layers": ["http", "sse"],
    })
    _write_json(
        paths["production_path_summary"],
        {
            "schema_version": (
                "guide-task11-production-path-summary-v1"
            ),
            "candidate_manifest_sha256": sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "protected_payload_sha256": (
                manifest["protected_payload_sha256"]
            ),
            "cases_sha256": sha256(
                (root / PRODUCTION_MATRIX_FIXTURE_PATH).read_bytes()
            ).hexdigest(),
            "passed": True,
            "expected_contract_case_count": 128,
            "actual_equivalence_case_count": 128,
            "actual_equivalence_failure_count": 0,
            "trajectory_count": 12,
            "stateful_turn_count": 48,
            "turn_count": 177,
            "state_edge_count": 40,
            "required_state_edge_count": 40,
            "required_state_edges": required_edges,
            "bounded_turn_count": 9,
            "bounded_failure_count": 0,
            "pre_decision_rejection_count": 1,
            "pre_decision_rejection_failure_count": 0,
            "translation_injection_count": 176,
            "compiler_bypass_count": 0,
            "compiler_call_count_violation_count": 0,
            "structured_understanding_injection_count": 0,
            "direct_router_bypass_count": 0,
            "legacy_entrypoint_count": 0,
            "router_call_count_violation_count": 0,
            "decision_identity_violation_count": 0,
            "selected_processor_invocation_count_violation_count": 0,
            "nonselected_processor_invocation_count": 0,
            "execution_result_count_violation_count": 0,
            "reducer_call_count_violation_count": 0,
            "processor_state_write_count": 0,
            "event_state_projection_count": 0,
            "state_save_count_violation_count": 0,
            "terminal_contract_failure_count": 0,
            "state_transition_failure_count": 0,
            "outbound_network_attempt_count": 0,
            "provider_call_count": 0,
            "observed_layers": [
                "translation",
                "compiler",
                "router",
                "processor",
                "reducer",
                "sqlite",
                "sse",
            ],
            "turn_traces": production_traces,
        },
    )
    for viewport, challenge in (
        ("desktop", "2" * 64),
        ("mobile", "3" * 64),
    ):
        _write_indexed_fixture_summary(
            paths[f"{viewport}_summary"],
            viewport=viewport,
            runtime_identity_bytes=runtime_identity_bytes,
            challenge=challenge,
        )
    reviewed = {
        "candidate_manifest": manifest_path,
        "semantic_summary": paths["semantic_summary"],
        "zero_api_summary": paths["zero_api_summary"],
        "network_report": paths["network_report"],
        "runtime_network_report": paths["runtime_network_report"],
        "single_path_architecture": paths[
            "single_path_architecture"
        ],
        "test_path_audit": paths["test_path_audit"],
        "production_path_summary": paths[
            "production_path_summary"
        ],
        "desktop_summary": paths["desktop_summary"],
        "mobile_summary": paths["mobile_summary"],
    }
    _write_json(
        paths["independent_audit"],
        {
            "schema_version": "guide-task11-independent-audit-v1",
            "passed": True,
            "plan_revision": manifest["plan_revision"],
            "repair_epoch": manifest["repair_epoch"],
            "candidate_manifest_sha256": sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "protected_payload_sha256": (
                manifest["protected_payload_sha256"]
            ),
            "production_diff_sha256": readiness._candidate_diff_sha256(
                root,
                revision=manifest["candidate_head"],
                change_paths=manifest["change_paths"],
            ),
            "checks": {
                check: True
                for check in readiness._INDEPENDENT_AUDIT_CHECKS
            },
            "task12_execution_tool_sha256": {
                relative: sha256(
                    (root / relative).read_bytes()
                ).hexdigest()
                for relative in readiness._TASK12_EXECUTION_PATHS
            },
            "reviewed_evidence_sha256": {
                role: sha256(path.read_bytes()).hexdigest()
                for role, path in reviewed.items()
            },
            "finding_count": 0,
            "p0_finding_count": 0,
            "p1_finding_count": 0,
            "findings": [],
        },
    )
    ledger = root / manifest["mutable_evidence_paths"][0]
    if not ledger.exists():
        attempt_ledger.initialize_ledger(ledger)
    return paths, ledger


def _derive_or_seal_candidate_readiness(
    **arguments: object,
) -> dict[str, object]:
    if arguments.get("output_path") is None:
        return readiness.derive_candidate_readiness(**arguments)
    manifest_path = Path(str(arguments["manifest_path"]))
    repo_root = manifest_path.parents[5]
    primary_key = _destroy_runtime_keys_for_seal(
        manifest_path=manifest_path,
        runtime_network_report_path=Path(
            str(arguments["runtime_network_report_path"])
        ),
    )
    return readiness.seal_candidate_readiness(
        **arguments,
        fixture_runtime_private_key_path=primary_key,
    )


def _destroy_runtime_keys_for_seal(
    *,
    manifest_path: Path,
    runtime_network_report_path: Path,
) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parents[5]
    runtime_public_keys = tuple(
        manifest["fixture_runtime_public_keys"]
    )
    runtime_report = json.loads(
        runtime_network_report_path.read_text(encoding="utf-8")
    )
    selected_slot = runtime_public_keys.index(
        runtime_report["fixture_runtime_public_key"]
    ) + 1
    primary_key = Path(
        manifest["fixture_runtime_private_key_paths"][0]
    )
    private_key_paths = (
        primary_key,
        readiness.retry_runtime_private_key_path(primary_key),
    )
    for path in private_key_paths[:selected_slot]:
        path.unlink(missing_ok=True)
    readiness._destroy_unused_runtime_private_keys(
        primary_key,
        repo_root=root,
        manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        runtime_public_keys=runtime_public_keys,
        selected_slot=selected_slot,
    )
    return primary_key


def _derived_candidate_readiness(
    root: Path,
    manifest_path: Path,
) -> tuple[Path, dict[str, Path], Path, list[str]]:
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent
        / "task11-candidate-readiness.json"
    )
    _derive_or_seal_candidate_readiness(
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
        runtime_network_report_path=evidence["runtime_network_report"],
        single_path_architecture_path=evidence[
            "single_path_architecture"
        ],
        test_path_audit_path=evidence["test_path_audit"],
        production_path_summary_path=evidence[
            "production_path_summary"
        ],
        independent_audit_path=evidence["independent_audit"],
        desktop_summary_path=evidence["desktop_summary"],
        mobile_summary_path=evidence["mobile_summary"],
        ledger_path=ledger,
        output_path=output,
    )
    fixture_artifact_paths = sorted({
        path.relative_to(root).as_posix()
        for summary in (
            evidence["desktop_summary"],
            evidence["mobile_summary"],
        )
        for path in summary.parent.rglob("*")
        if path.is_file() and path != summary
    })
    return output, evidence, ledger, fixture_artifact_paths


def _stub_bounded_attempt_validation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    root: Path,
) -> str:
    context_relative = "bounded-attempt/attempt-context.json"
    context = root / context_relative
    context.parent.mkdir(parents=True, exist_ok=True)
    context.write_text("{}\n", encoding="utf-8")

    def validate(**kwargs: object):
        ledger_path = Path(str(kwargs["ledger_file"]))
        return (
            "bounded-smoke-attempt-02",
            (context_relative,),
            attempt_ledger.ledger_anchor(
                attempt_ledger.read_ledger(ledger_path)
            ),
        )

    monkeypatch.setattr(
        readiness,
        "_validated_bounded_attempt_artifacts",
        validate,
    )
    return context_relative


def test_candidate_manifest_parses_task_files_and_hashes_raw_bytes(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["source_paths"] == sorted({
        "app/guide/example.py",
        *(
            path
            for path in readiness._TASK12_EXECUTION_PATHS
            if path.startswith("data/")
        ),
    })


def test_candidate_manifest_seals_external_runtime_private_key(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    private_key_path = tmp_path / "fixture-runtime-private-key.json"
    retry_private_key_path = (
        tmp_path / "fixture-runtime-private-key.retry-2.json"
    )
    private_key = json.loads(
        private_key_path.read_text(encoding="utf-8")
    )
    retry_private_key = json.loads(
        retry_private_key_path.read_text(encoding="utf-8")
    )

    public_keys = manifest["fixture_runtime_public_keys"]
    assert len(public_keys) == 2
    assert len(set(public_keys)) == 2
    assert public_keys[0] == TEST_RUNTIME_PUBLIC_KEY
    for index, (path, payload) in enumerate(
        (
            (private_key_path, private_key),
            (retry_private_key_path, retry_private_key),
        ),
        start=1,
    ):
        assert payload["runtime_key_slot"] == index
        assert payload["fixture_runtime_public_key"] == public_keys[index - 1]
        assert payload["candidate_manifest_sha256"] == sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.resolve().is_relative_to(
            manifest_path.parents[1]
        ) is False
    assert manifest["test_paths"] == sorted({
        "tests/guide/test_example.py",
        *(
            path
            for path in readiness._TASK12_EXECUTION_PATHS
            if path.startswith("tests/guide/")
        ),
    })
    assert manifest["fixture_paths"] == sorted({
        "tests/fixtures/guide/example.json",
        PRODUCTION_MATRIX_FIXTURE_PATH,
        SEMANTIC_MATRIX_FIXTURE_PATH,
        *(
            path
            for path in readiness._TASK12_EXECUTION_PATHS
            if path.startswith("tests/fixtures/")
        ),
    })
    assert manifest["tool_paths"] == sorted({
        "tools/guide_gates/example.py",
        *(
            path
            for path in readiness._TASK12_EXECUTION_PATHS
            if path.startswith("tools/")
        ),
    })
    assert manifest["deleted_paths"] == [
        "tools/guide_gates/legacy.py"
    ]
    assert manifest["plan_paths"] == [
        "docs/superpowers/plans/plan.md"
    ]
    assert manifest["repair_epoch"] == 22
    assert manifest["protected_paths"] == sorted({
        "app/guide/example.py",
        "tests/guide/test_example.py",
        "tests/fixtures/guide/example.json",
        PRODUCTION_MATRIX_FIXTURE_PATH,
        SEMANTIC_MATRIX_FIXTURE_PATH,
        "tools/guide_gates/example.py",
        "docs/superpowers/plans/plan.md",
        *readiness._TASK12_EXECUTION_PATHS,
    })
    expected = sha256()
    for relative in manifest["protected_paths"]:
        encoded_path = relative.encode("utf-8")
        content = (root / relative).read_bytes()
        expected.update(str(len(encoded_path)).encode("ascii"))
        expected.update(b":")
        expected.update(encoded_path)
        expected.update(str(len(content)).encode("ascii"))
        expected.update(b":")
        expected.update(content)
    assert manifest["candidate_payload_sha256"] == expected.hexdigest()
    assert (
        manifest["protected_payload_sha256"]
        == manifest["candidate_payload_sha256"]
    )
    assert "docs/audits/generated.json" not in manifest["protected_paths"]
    assert "tools/guide_gates/legacy.py" not in (
        manifest["protected_paths"]
    )
    assert manifest["change_paths"] == sorted([
        "app/guide/example.py",
        "docs/superpowers/plans/plan.md",
        "tests/fixtures/guide/example.json",
        "tests/guide/test_example.py",
        "tools/guide_gates/example.py",
        "tools/guide_gates/legacy.py",
    ])
    assert manifest["mutable_evidence_paths"] == [
        "docs/audits/final-release/mainline-contract-closure/"
        "smoke-attempt-ledger.json"
    ]
    deleted_bytes = subprocess.run(
        [
            "git",
            "show",
            f"{manifest['candidate_head']}:"
            "tools/guide_gates/legacy.py",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    assert manifest["deleted_base_blob_sha256_by_path"] == {
        "tools/guide_gates/legacy.py": sha256(
            deleted_bytes
        ).hexdigest()
    }


def test_candidate_manifest_preserves_preexisting_retry_key(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    primary_key_path = tmp_path / "fixture-runtime-private-key.json"
    retry_key_path = readiness.retry_runtime_private_key_path(
        primary_key_path
    )
    sentinel = retry_key_path.read_bytes()
    primary_key_path.unlink()
    manifest_path.unlink()

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="already exists",
    ):
        readiness.build_candidate_manifest(
            repo_root=root,
            plan_path=root / "docs/superpowers/plans/plan.md",
            output_path=manifest_path,
            candidate_head=str(manifest["candidate_head"]),
            changed_paths=tuple(manifest["change_paths"]),
            fixture_runtime_private_key_path=primary_key_path,
            _fixture_runtime_private_key=TEST_RUNTIME_PRIVATE_KEY,
        )

    assert retry_key_path.read_bytes() == sentinel
    assert not primary_key_path.exists()
    assert not manifest_path.exists()


def _stage_runtime_browser_evidence(
    *,
    manifest_path: Path,
    evidence: dict[str, Path],
    attempt_root: Path,
) -> dict[str, bytes]:
    attempt_root.mkdir(parents=True)
    runtime_target = (
        attempt_root / "task11-zero-api-runtime-network.json"
    )
    desktop_target = attempt_root / "fixture-browser-desktop"
    mobile_target = attempt_root / "fixture-browser-mobile"
    evidence["runtime_network_report"].rename(runtime_target)
    evidence["desktop_summary"].parent.rename(desktop_target)
    evidence["mobile_summary"].parent.rename(mobile_target)
    canonical_bundle = manifest_path.parent / "runtime-browser-evidence"
    if canonical_bundle.exists():
        canonical_bundle.rmdir()
    return {
        path.relative_to(attempt_root).as_posix(): path.read_bytes()
        for path in sorted(attempt_root.rglob("*"))
        if path.is_file()
    }


def test_runtime_browser_promotion_is_atomic_and_byte_identical(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, _ = _evidence(root, manifest_path)
    attempt_root = tmp_path / "runtime-attempts" / "attempt-01"
    expected_bytes = _stage_runtime_browser_evidence(
        manifest_path=manifest_path,
        evidence=evidence,
        attempt_root=attempt_root,
    )
    private_key_path = tmp_path / "fixture-runtime-private-key.json"
    private_key_path.unlink()

    report = readiness.promote_runtime_browser_evidence(
        repo_root=root,
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        attempt_root=attempt_root,
        fixture_runtime_private_key_path=private_key_path,
    )

    canonical = manifest_path.parent / "runtime-browser-evidence"
    actual_bytes = {
        path.relative_to(canonical).as_posix(): path.read_bytes()
        for path in sorted(canonical.rglob("*"))
        if path.is_file()
    }
    assert actual_bytes == expected_bytes
    assert report["attempt_id"] == "attempt-01"
    assert report["canonical_bundle"] == str(canonical.resolve())
    assert not readiness.retry_runtime_private_key_path(
        private_key_path
    ).exists()


def test_runtime_browser_promotion_rejects_invalid_staging_without_publish(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, _ = _evidence(root, manifest_path)
    attempt_root = tmp_path / "runtime-attempts" / "attempt-01"
    _stage_runtime_browser_evidence(
        manifest_path=manifest_path,
        evidence=evidence,
        attempt_root=attempt_root,
    )
    runtime_report = (
        attempt_root / "task11-zero-api-runtime-network.json"
    )
    payload = json.loads(runtime_report.read_text(encoding="utf-8"))
    payload["passed"] = False
    _write_json(runtime_report, payload)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="runtime browser staging is invalid",
    ):
        readiness.promote_runtime_browser_evidence(
            repo_root=root,
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            attempt_root=attempt_root,
            fixture_runtime_private_key_path=(
                tmp_path / "fixture-runtime-private-key.json"
            ),
        )

    assert not (
        manifest_path.parent / "runtime-browser-evidence"
    ).exists()
    assert readiness.retry_runtime_private_key_path(
        tmp_path / "fixture-runtime-private-key.json"
    ).exists()


def test_runtime_browser_promotion_interruption_does_not_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, _ = _evidence(root, manifest_path)
    attempt_root = tmp_path / "runtime-attempts" / "attempt-01"
    _stage_runtime_browser_evidence(
        manifest_path=manifest_path,
        evidence=evidence,
        attempt_root=attempt_root,
    )
    private_key_path = tmp_path / "fixture-runtime-private-key.json"
    private_key_path.unlink()

    def interrupt(_source: Path, _destination: Path) -> None:
        raise OSError("injected promotion interruption")

    monkeypatch.setattr(
        readiness,
        "_rename_runtime_browser_bundle_no_replace",
        interrupt,
    )
    with pytest.raises(
        OSError,
        match="injected promotion interruption",
    ):
        readiness.promote_runtime_browser_evidence(
            repo_root=root,
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            attempt_root=attempt_root,
            fixture_runtime_private_key_path=private_key_path,
        )

    assert not (
        manifest_path.parent / "runtime-browser-evidence"
    ).exists()
    assert readiness.retry_runtime_private_key_path(
        private_key_path
    ).exists()


def test_runtime_browser_promotion_resumes_post_commit_key_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, _ = _evidence(root, manifest_path)
    attempt_root = tmp_path / "runtime-attempts" / "attempt-01"
    expected_bytes = _stage_runtime_browser_evidence(
        manifest_path=manifest_path,
        evidence=evidence,
        attempt_root=attempt_root,
    )
    private_key_path = tmp_path / "fixture-runtime-private-key.json"
    private_key_path.unlink()
    retry_key_path = readiness.retry_runtime_private_key_path(
        private_key_path
    )
    destroy = readiness._destroy_unused_runtime_private_keys

    def interrupt_cleanup(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected post-commit cleanup interruption")

    monkeypatch.setattr(
        readiness,
        "_destroy_unused_runtime_private_keys",
        interrupt_cleanup,
    )
    with pytest.raises(
        OSError,
        match="injected post-commit cleanup interruption",
    ):
        readiness.promote_runtime_browser_evidence(
            repo_root=root,
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            attempt_root=attempt_root,
            fixture_runtime_private_key_path=private_key_path,
        )

    canonical = manifest_path.parent / "runtime-browser-evidence"
    assert canonical.is_dir()
    assert retry_key_path.is_file()

    monkeypatch.setattr(
        readiness,
        "_destroy_unused_runtime_private_keys",
        destroy,
    )
    report = readiness.promote_runtime_browser_evidence(
        repo_root=root,
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        attempt_root=attempt_root,
        fixture_runtime_private_key_path=private_key_path,
    )

    actual_bytes = {
        path.relative_to(canonical).as_posix(): path.read_bytes()
        for path in sorted(canonical.rglob("*"))
        if path.is_file()
    }
    assert report["passed"] is True
    assert actual_bytes == expected_bytes
    assert not retry_key_path.exists()


def test_runtime_private_key_cleanup_rejects_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retry_key_path = readiness.retry_runtime_private_key_path(
        tmp_path / "fixture-runtime-private-key.json"
    )
    escaped_key_path = tmp_path / "escaped-private-key.json"
    original_unlink = os.unlink
    swapped = False

    def swap_before_unlink(
        path: str | bytes,
        *args: object,
        dir_fd: int | None = None,
        **kwargs: object,
    ) -> None:
        nonlocal swapped
        if path == retry_key_path.name and not swapped:
            swapped = True
            assert dir_fd is not None
            os.rename(
                path,
                escaped_key_path.name,
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
            )
            replacement = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            try:
                os.write(replacement, b"{}\n")
            finally:
                os.close(replacement)
        original_unlink(
            path,
            *args,
            dir_fd=dir_fd,
            **kwargs,
        )

    monkeypatch.setattr(os, "unlink", swap_before_unlink)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="cleanup target changed",
    ):
        readiness._unlink_validated_runtime_private_key(
            retry_key_path,
            manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            expected_slot=2,
            expected_public_key=manifest[
                "fixture_runtime_public_keys"
            ][1],
        )

    assert escaped_key_path.exists()
    assert escaped_key_path.read_bytes()


def test_runtime_private_key_cleanup_resumes_after_unlink_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retry_key_path = readiness.retry_runtime_private_key_path(
        tmp_path / "fixture-runtime-private-key.json"
    )
    original_unlink = os.unlink

    def interrupt_before_tombstone_unlink(
        path: str | bytes,
        *args: object,
        dir_fd: int | None = None,
        **kwargs: object,
    ) -> None:
        if str(path).startswith(
            f".{retry_key_path.name}.destroying-"
        ):
            raise OSError("simulated unlink interruption")
        original_unlink(
            path,
            *args,
            dir_fd=dir_fd,
            **kwargs,
        )

    monkeypatch.setattr(
        os,
        "unlink",
        interrupt_before_tombstone_unlink,
    )
    with pytest.raises(
        readiness.Task11ReadinessError,
        match="cleanup target is invalid",
    ):
        readiness._unlink_validated_runtime_private_key(
            retry_key_path,
            manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            expected_slot=2,
            expected_public_key=manifest[
                "fixture_runtime_public_keys"
            ][1],
        )

    assert not retry_key_path.exists()
    tombstones = readiness._runtime_private_key_cleanup_residue_paths(
        retry_key_path
    )
    assert len(tombstones) == 1
    assert tombstones[0].read_bytes()
    receipt = retry_key_path.with_name(
        f".{retry_key_path.name}.destroyed.json"
    )
    assert receipt.is_file()
    monkeypatch.setattr(os, "unlink", original_unlink)

    readiness._unlink_validated_runtime_private_key(
        retry_key_path,
        manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        expected_slot=2,
        expected_public_key=manifest[
            "fixture_runtime_public_keys"
        ][1],
    )

    assert not retry_key_path.exists()
    assert not tombstones[0].exists()
    assert receipt.is_file()


def test_runtime_private_key_cleanup_rejects_unbound_zero_file(
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retry_key_path = readiness.retry_runtime_private_key_path(
        tmp_path / "fixture-runtime-private-key.json"
    )
    escaped_key_path = tmp_path / "escaped-live-private-key.json"
    retry_key_path.rename(escaped_key_path)
    retry_key_path.write_bytes(b"")
    retry_key_path.chmod(0o600)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="cleanup target is invalid",
    ):
        readiness._unlink_validated_runtime_private_key(
            retry_key_path,
            manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            expected_slot=2,
            expected_public_key=manifest[
                "fixture_runtime_public_keys"
            ][1],
        )

    assert escaped_key_path.read_bytes()
    assert retry_key_path.read_bytes() == b""


def test_runtime_private_key_cleanup_rejects_forged_empty_tombstone(
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retry_key_path = readiness.retry_runtime_private_key_path(
        tmp_path / "fixture-runtime-private-key.json"
    )
    escaped_key_path = tmp_path / "escaped-live-private-key.json"
    retry_key_path.rename(escaped_key_path)
    provisional = retry_key_path.with_name(
        f".{retry_key_path.name}.destroying-provisional"
    )
    provisional.write_bytes(b"")
    provisional.chmod(0o600)
    metadata = provisional.stat()
    tombstone = retry_key_path.with_name(
        f".{retry_key_path.name}.destroying-"
        f"{metadata.st_dev:x}-{metadata.st_ino:x}"
    )
    provisional.rename(tombstone)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="cleanup target is invalid",
    ):
        readiness._unlink_validated_runtime_private_key(
            retry_key_path,
            manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            expected_slot=2,
            expected_public_key=manifest[
                "fixture_runtime_public_keys"
            ][1],
        )

    assert escaped_key_path.read_bytes()
    assert tombstone.read_bytes() == b""


def test_readiness_requires_signed_unused_key_destruction_receipt(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    primary_key_path = tmp_path / "fixture-runtime-private-key.json"
    retry_key_path = readiness.retry_runtime_private_key_path(
        primary_key_path
    )
    primary_key_path.unlink()
    retry_key_path.unlink()

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="cleanup receipt is missing",
    ):
        readiness._require_runtime_private_keys_destroyed(
            primary_key_path,
            repo_root=root,
            manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            runtime_public_keys=tuple(
                manifest["fixture_runtime_public_keys"]
            ),
            selected_slot=1,
        )


def test_runtime_private_key_cleanup_rejects_parent_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    key_parent = tmp_path / "runtime-keys"
    key_parent.mkdir()
    retry_key_path = (
        key_parent / "fixture-runtime-private-key.retry-2.json"
    )
    readiness.retry_runtime_private_key_path(
        tmp_path / "fixture-runtime-private-key.json"
    ).rename(retry_key_path)
    escaped_parent = tmp_path / "escaped-runtime-keys"
    original_unlink = os.unlink
    swapped = False

    def swap_parent_before_unlink(
        path: str | bytes,
        *args: object,
        dir_fd: int | None = None,
        **kwargs: object,
    ) -> None:
        nonlocal swapped
        if path == retry_key_path.name and not swapped:
            swapped = True
            key_parent.rename(escaped_parent)
            key_parent.mkdir()
            replacement = key_parent / retry_key_path.name
            replacement.write_bytes(
                (escaped_parent / retry_key_path.name).read_bytes()
            )
            replacement.chmod(0o600)
        original_unlink(
            path,
            *args,
            dir_fd=dir_fd,
            **kwargs,
        )

    monkeypatch.setattr(os, "unlink", swap_parent_before_unlink)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="cleanup parent changed",
    ):
        readiness._unlink_validated_runtime_private_key(
            retry_key_path,
            manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            expected_slot=2,
            expected_public_key=manifest[
                "fixture_runtime_public_keys"
            ][1],
        )

    assert retry_key_path.exists()
    assert retry_key_path.read_bytes()


def test_runtime_browser_promotion_rejects_unbound_private_key_path(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, _ = _evidence(root, manifest_path)
    attempt_root = tmp_path / "runtime-attempts" / "attempt-01"
    _stage_runtime_browser_evidence(
        manifest_path=manifest_path,
        evidence=evidence,
        attempt_root=attempt_root,
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="runtime private key path",
    ):
        readiness.promote_runtime_browser_evidence(
            repo_root=root,
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            attempt_root=attempt_root,
            fixture_runtime_private_key_path=(
                tmp_path / "unbound-private-key.json"
            ),
        )

    assert not (
        manifest_path.parent / "runtime-browser-evidence"
    ).exists()
    assert readiness.retry_runtime_private_key_path(
        tmp_path / "fixture-runtime-private-key.json"
    ).exists()


def test_readiness_seal_rejects_surviving_runtime_private_key(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent / "task11-candidate-readiness.json"
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="runtime private keys were not destroyed",
    ):
        readiness.seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=output,
            fixture_runtime_private_key_path=(
                tmp_path / "fixture-runtime-private-key.json"
            ),
        )

    assert not output.exists()


def test_readiness_seal_rejects_unbound_private_key_path(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent / "task11-candidate-readiness.json"
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="runtime private key path",
    ):
        readiness.seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=output,
            fixture_runtime_private_key_path=(
                tmp_path / "unbound-private-key.json"
            ),
        )

    assert not output.exists()


def test_readiness_rechecks_runtime_keys_immediately_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent / "task11-candidate-readiness.json"
    )
    primary = tmp_path / "fixture-runtime-private-key.json"
    retry = readiness.retry_runtime_private_key_path(primary)
    _destroy_runtime_keys_for_seal(
        manifest_path=manifest_path,
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
    )
    derive = readiness.derive_candidate_readiness

    def recreate_key(**arguments: object) -> dict[str, object]:
        result = derive(**arguments)
        retry.write_text("surviving-key\n", encoding="utf-8")
        return result

    monkeypatch.setattr(
        readiness,
        "derive_candidate_readiness",
        recreate_key,
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="runtime private keys were not destroyed",
    ):
        readiness.seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=output,
            fixture_runtime_private_key_path=primary,
        )

    assert not output.exists()


def test_readiness_publish_recovers_partial_pending_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent / "task11-candidate-readiness.json"
    )
    primary = _destroy_runtime_keys_for_seal(
        manifest_path=manifest_path,
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
    )
    arguments = {
        "manifest_path": manifest_path,
        "expected_manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "semantic_summary_path": evidence["semantic_summary"],
        "zero_api_summary_path": evidence["zero_api_summary"],
        "network_report_path": evidence["network_report"],
        "runtime_network_report_path": evidence[
            "runtime_network_report"
        ],
        "single_path_architecture_path": evidence[
            "single_path_architecture"
        ],
        "test_path_audit_path": evidence["test_path_audit"],
        "production_path_summary_path": evidence[
            "production_path_summary"
        ],
        "independent_audit_path": evidence["independent_audit"],
        "desktop_summary_path": evidence["desktop_summary"],
        "mobile_summary_path": evidence["mobile_summary"],
        "ledger_path": ledger,
        "output_path": output,
        "fixture_runtime_private_key_path": primary,
    }
    original_write = os.write
    interrupted = False

    def interrupt_partial_write(
        descriptor: int,
        content: bytes | bytearray | memoryview,
    ) -> int:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            prefix_length = max(1, len(content) // 2)
            original_write(descriptor, content[:prefix_length])
            raise OSError("simulated readiness write interruption")
        return original_write(descriptor, content)

    monkeypatch.setattr(os, "write", interrupt_partial_write)
    with pytest.raises(
        readiness.Task11ReadinessError,
        match="candidate readiness could not be published",
    ):
        readiness.seal_candidate_readiness(**arguments)

    pending = output.with_name(f".{output.name}.pending")
    assert not output.exists()
    assert pending.is_file()

    monkeypatch.setattr(os, "write", original_write)
    result = readiness.seal_candidate_readiness(**arguments)

    assert output.read_bytes() == _canonical_bytes(result)
    assert not pending.exists()


def test_readiness_revalidates_payload_after_final_key_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent / "task11-candidate-readiness.json"
    )
    primary = _destroy_runtime_keys_for_seal(
        manifest_path=manifest_path,
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
    )
    protected = root / "app/guide/example.py"
    original_check = readiness._require_runtime_private_keys_destroyed
    checks = 0

    def mutate_after_final_key_check(
        primary_path: str | Path,
        **arguments: object,
    ) -> None:
        nonlocal checks
        original_check(primary_path, **arguments)
        checks += 1
        if checks == 2:
            protected.write_text("VALUE = 2\n", encoding="utf-8")

    monkeypatch.setattr(
        readiness,
        "_require_runtime_private_keys_destroyed",
        mutate_after_final_key_check,
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="protected payload drift",
    ):
        readiness.seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=output,
            fixture_runtime_private_key_path=primary,
        )

    assert checks == 2
    assert not output.exists()


def test_readiness_rechecks_runtime_keys_after_publication_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent / "task11-candidate-readiness.json"
    )
    primary = _destroy_runtime_keys_for_seal(
        manifest_path=manifest_path,
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
    )
    retry = readiness.retry_runtime_private_key_path(primary)
    original_link = readiness.os.link

    def recreate_key_before_link(*args: object, **kwargs: object) -> None:
        retry.write_text("recreated-key\n", encoding="utf-8")
        original_link(*args, **kwargs)

    monkeypatch.setattr(readiness.os, "link", recreate_key_before_link)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="runtime private keys were not destroyed",
    ):
        readiness.seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=output,
            fixture_runtime_private_key_path=primary,
        )

    assert not output.exists()


def test_readiness_recovery_rolls_back_canonical_on_authority_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent / "task11-candidate-readiness.json"
    )
    primary = _destroy_runtime_keys_for_seal(
        manifest_path=manifest_path,
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
    )
    arguments = {
        "manifest_path": manifest_path,
        "expected_manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "semantic_summary_path": evidence["semantic_summary"],
        "zero_api_summary_path": evidence["zero_api_summary"],
        "network_report_path": evidence["network_report"],
        "runtime_network_report_path": evidence[
            "runtime_network_report"
        ],
        "single_path_architecture_path": evidence[
            "single_path_architecture"
        ],
        "test_path_audit_path": evidence["test_path_audit"],
        "production_path_summary_path": evidence[
            "production_path_summary"
        ],
        "independent_audit_path": evidence["independent_audit"],
        "desktop_summary_path": evidence["desktop_summary"],
        "mobile_summary_path": evidence["mobile_summary"],
        "ledger_path": ledger,
        "output_path": output,
        "fixture_runtime_private_key_path": primary,
    }
    pending = output.with_name(f".{output.name}.pending")
    original_unlink = readiness.os.unlink
    interrupted = False

    def interrupt_pending_cleanup(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal interrupted
        if path == pending.name and not interrupted:
            interrupted = True
            raise OSError("simulated post-link cleanup interruption")
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(
        readiness.os,
        "unlink",
        interrupt_pending_cleanup,
    )
    with pytest.raises(
        readiness.Task11ReadinessError,
        match="candidate readiness could not be published",
    ):
        readiness.seal_candidate_readiness(**arguments)

    assert output.is_file()
    assert pending.is_file()

    monkeypatch.setattr(readiness.os, "unlink", original_unlink)
    retry = readiness.retry_runtime_private_key_path(primary)
    retry.write_text("recreated-key\n", encoding="utf-8")

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="runtime private keys were not destroyed",
    ):
        readiness.seal_candidate_readiness(**arguments)

    assert not output.exists()
    assert pending.is_file()


def test_readiness_publish_rejects_parent_directory_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent / "task11-candidate-readiness.json"
    )
    primary = tmp_path / "fixture-runtime-private-key.json"
    _destroy_runtime_keys_for_seal(
        manifest_path=manifest_path,
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
    )
    escaped_parent = manifest_path.parent.with_name(
        "repair-epoch-22-escaped"
    )
    original_open = os.open
    swapped = False

    def swap_parent_before_publish(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        *args: object,
        dir_fd: int | None = None,
        **kwargs: object,
    ) -> int:
        nonlocal swapped
        if (
            path == f".{output.name}.pending"
            and dir_fd is not None
            and flags & os.O_EXCL
            and not swapped
        ):
            swapped = True
            manifest_path.parent.rename(escaped_parent)
            manifest_path.parent.mkdir()
        return original_open(
            path,
            flags,
            *args,
            dir_fd=dir_fd,
            **kwargs,
        )

    monkeypatch.setattr(os, "open", swap_parent_before_publish)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="candidate readiness parent changed",
    ):
        readiness.seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=output,
            fixture_runtime_private_key_path=primary,
        )

    assert not output.exists()
    assert (
        escaped_parent / f".{output.name}.pending"
    ).is_file()


def test_derive_candidate_readiness_cannot_publish(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent / "task11-candidate-readiness.json"
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="seal_candidate_readiness is the only readiness writer",
    ):
        readiness.derive_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=output,
        )

    assert not output.exists()


def test_runtime_private_key_paths_resolve_only_parent_alias(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    key_root = tmp_path / "keys"
    key_root.mkdir()
    alias = tmp_path / "key-alias"
    alias.symlink_to(key_root, target_is_directory=True)

    paths = readiness._runtime_private_key_paths(
        alias / "fixture-runtime-private-key.json",
        repo_root=root,
    )

    assert paths == (
        key_root / "fixture-runtime-private-key.json",
        key_root / "fixture-runtime-private-key.retry-2.json",
    )


def test_candidate_manifest_binds_repository_keys_and_ledger_source(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    primary = (
        tmp_path / "fixture-runtime-private-key.json"
    ).resolve()
    ledger = root / readiness._MUTABLE_EVIDENCE_PATHS[0]
    ledger_anchor = attempt_ledger.ledger_anchor(
        attempt_ledger.read_ledger(ledger)
    )

    assert manifest["repository_root"] == str(root.resolve())
    assert manifest["fixture_runtime_private_key_paths"] == [
        str(primary),
        str(readiness.retry_runtime_private_key_path(primary)),
    ]
    assert manifest["pre_checkpoint_ledger"] == {
        "path": str(ledger.resolve()),
        "sha256": sha256(ledger.read_bytes()).hexdigest(),
        "revision": ledger_anchor["revision"],
        "revision_hash": ledger_anchor["revision_hash"],
    }


def test_manifest_validation_rejects_nested_repository_copy(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    nested_root = root / "nested-copy"
    for relative in manifest["protected_paths"]:
        source = root / relative
        target = nested_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    nested_manifest = nested_root / manifest_path.relative_to(root)
    nested_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, nested_manifest)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="canonical path",
    ):
        readiness._validated_manifest(
            nested_manifest,
            expected_manifest_sha256=sha256(
                nested_manifest.read_bytes()
            ).hexdigest(),
        )


def test_candidate_manifest_rejects_repair_epoch_path_mismatch(
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["repair_epoch"] = 23
    _write_json(manifest_path, manifest)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="repair epoch",
    ):
        readiness._validated_manifest(
            manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
        )


def test_candidate_manifest_rejects_sibling_manifest_path(
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    sibling = manifest_path.with_name("attacker-manifest.json")
    sibling.write_bytes(manifest_path.read_bytes())

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="canonical path",
    ):
        readiness._validated_manifest(
            sibling,
            expected_manifest_sha256=sha256(
                sibling.read_bytes()
            ).hexdigest(),
        )


def test_candidate_manifest_accepts_matching_revision_qualified_path(
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    versioned = manifest_path.with_name(
        "task11-candidate-manifest-r1.json"
    )
    versioned.write_bytes(manifest_path.read_bytes())

    manifest, _ = readiness._validated_manifest(
        versioned,
        expected_manifest_sha256=sha256(
            versioned.read_bytes()
        ).hexdigest(),
    )
    readiness._require_candidate_readiness_path(
        manifest_file=versioned,
        manifest=manifest,
        readiness_path=versioned.with_name(
            "task11-candidate-readiness-r1.json"
        ),
    )
    evidence_paths = readiness._canonical_epoch_evidence_paths(
        versioned
    )

    assert manifest["plan_revision"] == "task11-r1"
    assert evidence_paths["semantic_summary"].name == (
        "task11-semantic-matrix-summary-r1.json"
    )
    assert "runtime-browser-evidence-r1" in (
        evidence_paths["desktop_summary"].parts
    )


def test_candidate_manifest_rejects_sibling_symlink(
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    sibling = manifest_path.with_name("attacker-manifest.json")
    sibling.symlink_to(manifest_path)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="symlink",
    ):
        readiness._validated_manifest(
            sibling,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
        )


def test_candidate_manifest_rejects_symlinked_epoch_directory(
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    epoch = manifest_path.parent
    real_epoch = epoch.with_name("repair-epoch-22-real")
    epoch.rename(real_epoch)
    epoch.symlink_to(real_epoch, target_is_directory=True)
    aliased_manifest = epoch / manifest_path.name

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="symlink",
    ):
        readiness._validated_manifest(
            aliased_manifest,
            expected_manifest_sha256=sha256(
                aliased_manifest.read_bytes()
            ).hexdigest(),
        )


def test_canonical_payload_rejects_symlinked_ancestor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "example.py").write_text(
        "VALUE = 'outside'\n",
        encoding="utf-8",
    )
    (root / "app").symlink_to(outside, target_is_directory=True)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="invalid",
    ):
        readiness.canonical_payload_sha256(
            root,
            ("app/example.py",),
        )


def test_canonical_payload_rejects_replaced_intermediate_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    detached = tmp_path / "detached-app"
    (root / "app").mkdir(parents=True)
    (root / "app/example.py").write_text(
        "VALUE = 'reviewed'\n",
        encoding="utf-8",
    )
    original_open = readiness.os.open
    replaced = False

    def replace_after_ancestor_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal replaced
        descriptor = original_open(
            path,
            flags,
            mode,
            dir_fd=dir_fd,
        )
        if path == "app" and dir_fd is not None and not replaced:
            replaced = True
            (root / "app").rename(detached)
            (root / "app").mkdir()
            (root / "app/example.py").write_text(
                "VALUE = 'attacker'\n",
                encoding="utf-8",
            )
        return descriptor

    monkeypatch.setattr(readiness.os, "open", replace_after_ancestor_open)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="ancestor changed",
    ):
        readiness.canonical_payload_sha256(
            root,
            ("app/example.py",),
        )


def test_payload_hash_rejects_repository_root_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    replaced_root = tmp_path / "replaced-repo"
    (root / "app").mkdir(parents=True)
    for name in ("first.py", "second.py"):
        (root / "app" / name).write_text(
            f"VALUE = {name!r}\n",
            encoding="utf-8",
        )
    real_read = readiness.os.read
    replaced = False

    def replace_after_first_read(
        descriptor: int,
        byte_count: int,
    ) -> bytes:
        nonlocal replaced
        content = real_read(descriptor, byte_count)
        if not content and not replaced:
            replaced = True
            root.rename(replaced_root)
            (root / "app").mkdir(parents=True)
            for name in ("first.py", "second.py"):
                (root / "app" / name).write_text(
                    f"ATTACKER = {name!r}\n",
                    encoding="utf-8",
                )
        return content

    monkeypatch.setattr(readiness.os, "read", replace_after_first_read)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="repository root changed",
    ):
        readiness.canonical_payload_sha256(
            root,
            ("app/first.py", "app/second.py"),
        )


def test_candidate_manifest_hashes_the_same_bytes_it_parses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)
    reviewed_bytes = manifest_path.read_bytes()
    attacker = json.loads(reviewed_bytes)
    attacker["attacker_controlled"] = True
    _write_json(manifest_path, attacker)
    original_read_bytes = Path.read_bytes

    def stale_hash_bytes(path: Path) -> bytes:
        if path == manifest_path:
            return reviewed_bytes
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", stale_hash_bytes)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="reviewed SHA-256",
    ):
        readiness._validated_manifest(
            manifest_path,
            expected_manifest_sha256=sha256(
                reviewed_bytes
            ).hexdigest(),
        )


def test_readiness_rejects_noncanonical_epoch_evidence(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    alternate = manifest_path.parent / "alternate-semantic-summary.json"
    alternate.write_bytes(evidence["semantic_summary"].read_bytes())

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="canonical epoch evidence",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=alternate,
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_hashes_the_same_evidence_bytes_it_parses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    target = evidence["network_report"]
    reviewed_bytes = target.read_bytes()
    attacker = json.loads(reviewed_bytes)
    attacker["attacker_controlled"] = True
    _write_json(target, attacker)
    original_read_bytes = Path.read_bytes

    def stale_hash_bytes(path: Path) -> bytes:
        if path == target:
            return reviewed_bytes
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", stale_hash_bytes)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="zero API evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=target,
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


@pytest.mark.parametrize(
    "runtime_public_keys",
    (
        [TEST_RUNTIME_PUBLIC_KEY],
        [TEST_RUNTIME_PUBLIC_KEY, TEST_RUNTIME_PUBLIC_KEY],
        [TEST_RUNTIME_PUBLIC_KEY, {}],
    ),
)
def test_candidate_manifest_requires_two_distinct_runtime_public_keys(
    tmp_path: Path,
    runtime_public_keys: list[object],
) -> None:
    _, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fixture_runtime_public_keys"] = runtime_public_keys
    manifest_path.write_bytes(readiness._canonical_bytes(manifest))

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="runtime provenance",
    ):
        readiness._validated_manifest(
            manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
        )


def test_candidate_manifest_requires_reviewed_sha256(
    tmp_path: Path,
) -> None:
    _, manifest_path = _candidate(tmp_path)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="reviewed SHA-256",
    ):
        readiness._validated_manifest(
            manifest_path,
            expected_manifest_sha256="0" * 64,
        )


def test_candidate_manifest_rejects_relevant_changed_path_omission(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest_path.unlink()
    omitted = root / "app/guide/omitted.py"
    omitted.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="missing from Task 11 Files",
    ):
        readiness.build_candidate_manifest(
            repo_root=root,
            plan_path=root / "docs/superpowers/plans/plan.md",
                output_path=manifest_path,
            candidate_head="a" * 40,
            changed_paths=(
                "app/guide/example.py",
                "app/guide/omitted.py",
            ),
        )


def test_candidate_manifest_rejects_modified_public_demo_when_plan_omits_it(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.unlink()
    demo = root / "app/static/demo.html"
    demo.parent.mkdir(parents=True, exist_ok=True)
    demo.write_text("<main>modified public demo</main>\n", encoding="utf-8")

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="relevant changed paths missing",
    ):
        readiness.build_candidate_manifest(
            repo_root=root,
            plan_path=root / "docs/superpowers/plans/plan.md",
                output_path=manifest_path,
            candidate_head=manifest["candidate_head"],
            changed_paths=(
                *manifest["change_paths"],
                "app/static/demo.html",
            ),
        )


def test_candidate_manifest_rejects_static_runtime_path_omission(
    tmp_path: Path,
) -> None:
    assert readiness._is_relevant("app/static/guide-presentation.js")
    root, manifest_path = _candidate(tmp_path)
    manifest_path.unlink()

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="missing from Task 11 Files",
    ):
        readiness.build_candidate_manifest(
            repo_root=root,
            plan_path=root / "docs/superpowers/plans/plan.md",
                output_path=manifest_path,
            candidate_head="a" * 40,
            changed_paths=(
                "app/guide/example.py",
                "app/static/guide-presentation.js",
            ),
        )


@pytest.mark.parametrize(
    "path",
    (
        "app/main.py",
        "app/config.py",
        "tools/rogue_paid_call.py",
        "tests/test_runtime_entry.py",
        "start.sh",
        "Dockerfile",
        "docker-compose.prod.yml",
        "nginx.conf",
        "requirements-guide-runtime.txt",
        "requirements-guide-browser-matrix.txt",
        "pytest-guide.ini",
        "init.sql",
    ),
)
def test_candidate_scope_includes_all_executable_change_roots(
    path: str,
) -> None:
    assert readiness._is_relevant(path)


def test_candidate_readiness_rejects_non_epoch_output_path(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="candidate readiness path is invalid",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=root / "readiness.json",
        )


def test_candidate_manifest_rejects_unprotected_local_script_dependency(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    static_root = root / "app/static"
    static_root.mkdir(parents=True, exist_ok=True)
    (static_root / "chat.html").write_text(
        '<script src="/static/guide-demo-fixture.js"></script>\n',
        encoding="utf-8",
    )
    (static_root / "guide-demo-fixture.js").write_text(
        "window.fixture = true;\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "app/static"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "add static baseline"],
        cwd=root,
        check=True,
    )
    plan = root / "docs/superpowers/plans/plan.md"
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "- Modify: `app/guide/example.py`",
            "- Modify: `app/guide/example.py`\n"
            "- Modify: `app/static/chat.html`",
        ),
        encoding="utf-8",
    )
    manifest_path.unlink()

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="local static dependencies missing",
    ):
        readiness.build_candidate_manifest(
            repo_root=root,
            plan_path=plan,
                output_path=manifest_path,
            candidate_head=subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            changed_paths=(
                "app/guide/example.py",
                "tests/guide/test_example.py",
                "tests/fixtures/guide/example.json",
                "tools/guide_gates/example.py",
                "tools/guide_gates/legacy.py",
                "docs/superpowers/plans/plan.md",
            ),
        )


def test_candidate_manifest_excludes_historical_recording_plan(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    candidate_head = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )["candidate_head"]
    manifest_path.unlink()
    private_key_path = tmp_path / "fixture-runtime-private-key.json"
    private_key_path.unlink()
    readiness.retry_runtime_private_key_path(
        private_key_path
    ).unlink()

    manifest = readiness.build_candidate_manifest(
        repo_root=root,
        plan_path=root / "docs/superpowers/plans/plan.md",
        output_path=manifest_path,
        candidate_head=candidate_head,
        changed_paths=(
            "app/guide/example.py",
            "tests/guide/test_example.py",
            "tools/guide_gates/example.py",
            "tools/guide_gates/legacy.py",
            "docs/superpowers/plans/plan.md",
            (
                "docs/superpowers/plans/"
                "2026-08-20-recording-ready-guide-path.md"
            ),
        ),
        fixture_runtime_private_key_path=private_key_path,
        _fixture_runtime_private_key=TEST_RUNTIME_PRIVATE_KEY,
    )

    assert (
        "docs/superpowers/plans/"
        "2026-08-20-recording-ready-guide-path.md"
        not in manifest["protected_paths"]
    )
    assert (
        "tests/fixtures/guide/example.json"
        not in manifest["change_paths"]
    )


def test_test_path_audit_classifies_claims_and_discovers_fixtures(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    production_test = (
        root
        / "tests/guide/tools/test_task11_production_path_matrix.py"
    )
    frontend_test = (
        root
        / "tests/guide/tools/"
        "test_run_mainline_contract_browser_audit.py"
    )
    layer_test = root / "tests/guide/intent/test_router.py"
    fixture = (
        root
        / "tests/fixtures/guide/intent/"
        "task11_production_path_matrix_v1.jsonl"
    )
    tool = (
        root
        / "tools/guide_gates/"
        "run_task11_production_path_matrix.py"
    )
    plan = root / "docs/superpowers/plans/plan.md"
    for path in (
        production_test,
        frontend_test,
        layer_test,
        fixture,
        tool,
        plan,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    production_test.write_text(
        (
                "from tools.guide_gates.run_task11_production_path_matrix "
                "import DEFAULT_CASES_PATH, run_production_path_matrix\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    summary = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
                "        cases_path=DEFAULT_CASES_PATH,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    assert summary.passed is True\n\n"
            "def test_matrix_rejects_bad_trace():\n"
            "    return None\n"
        ),
        encoding="utf-8",
    )
    frontend_test.write_text(
        (
            "def fixture_sse_bytes(fixture_id):\n"
            "    return b'event: start\\n\\n'\n\n"
            "def test_fixture_renderer_contract():\n"
            "    assert fixture_sse_bytes('fixture-card')\n"
        ),
        encoding="utf-8",
    )
    layer_test.write_text(
        (
            "def route_unified_turn(value):\n"
            "    return value\n\n"
            "def test_router_contract():\n"
            "    assert route_unified_turn('recommendation')\n"
        ),
        encoding="utf-8",
    )
    fixture.write_text(
        _production_matrix_fixture_rows(),
        encoding="utf-8",
    )
    tool.write_text(
        (
                "from pathlib import Path\n\n"
                "DEFAULT_CASES_PATH = (\n"
                "    Path(__file__).resolve().parents[2]\n"
                "    / 'tests'\n"
                "    / 'fixtures'\n"
                "    / 'guide'\n"
                "    / 'intent'\n"
                "    / 'task11_production_path_matrix_v1.jsonl'\n"
                ")\n\n"
            "def run_production_path_matrix(**kwargs):\n"
            "    return None\n"
        ),
        encoding="utf-8",
    )
    plan.write_text(
        """
# Plan

Plan revision: task11-r1
Task 11 evidence epoch: repair-epoch-22

### Task 11: Close

**Files:**
- Test: `tests/guide/tools/test_task11_production_path_matrix.py`
- Test: `tests/guide/tools/test_run_mainline_contract_browser_audit.py`
- Test: `tests/guide/intent/test_router.py`
- Create: `tools/guide_gates/run_task11_production_path_matrix.py`
- Modify: `docs/superpowers/plans/plan.md`

- [ ] **Step 0: Run**
""".lstrip(),
        encoding="utf-8",
    )
    audit_path = root / "test-path-audit.json"

    audit = readiness.build_test_path_audit(
        repo_root=root,
        plan_path=plan,
        output_path=audit_path,
    )
    candidate_head = _initialize_git_repo(root)
    ledger = root / readiness._MUTABLE_EVIDENCE_PATHS[0]
    attempt_ledger.initialize_ledger(ledger)
    manifest = readiness.build_candidate_manifest(
        repo_root=root,
        plan_path=plan,
        output_path=(
            root
            / "docs/audits/final-release/mainline-contract-closure"
            / "repair-epoch-22"
            / "task11-candidate-manifest.json"
        ),
        candidate_head=candidate_head,
        changed_paths=(),
        test_path_audit_path=audit_path,
        fixture_runtime_private_key_path=(
            tmp_path / "fixture-runtime-private-key.json"
        ),
        _fixture_runtime_private_key=TEST_RUNTIME_PRIVATE_KEY,
    )

    assert audit["passed"] is True
    assert audit["production_path_gate_count"] == 1
    assert audit["scope_counts"] == {
        "frontend_fixture": 1,
        "layer_contract": 1,
        "production_path_from_turn_meaning": 1,
        "unit": 1,
    }
    assert {
        gate["gate"]: gate["claimed_scope"]
        for gate in audit["gates"]
    } == {
        (
            "tests/guide/tools/"
            "test_task11_production_path_matrix.py::"
            "test_frozen_matrix_runs_full_http_production_path"
        ): (
            "production_path_from_turn_meaning"
        ),
        (
            "tests/guide/tools/"
            "test_task11_production_path_matrix.py::"
            "test_matrix_rejects_bad_trace"
        ): "unit",
        (
            "tests/guide/tools/"
            "test_run_mainline_contract_browser_audit.py::"
            "test_fixture_renderer_contract"
        ): "frontend_fixture",
        (
            "tests/guide/intent/test_router.py::test_router_contract"
        ): "layer_contract",
    }
    production_gate = next(
        gate
        for gate in audit["gates"]
        if gate["claimed_scope"]
        == "production_path_from_turn_meaning"
    )
    assert production_gate["case_count"] == 177
    assert production_gate["trajectory_count"] == 12
    assert production_gate["turn_count"] == 177
    assert production_gate["state_edge_count"] == 40
    assert production_gate["pre_decision_rejection_count"] == 1
    assert production_gate["layers_executed"] == (
        readiness._RUNTIME_LAYER_ORDER
    )
    assert production_gate["runtime_evidence_source"] == (
        "task11-production-path-summary"
    )
    assert production_gate["semantic_injection_type"] == (
        "frozen_turn_meaning_provider"
    )
    assert production_gate["fixture_files"] == [
        "tests/fixtures/guide/intent/"
        "task11_production_path_matrix_v1.jsonl"
    ]
    assert audit["fixture_dependencies"] == [
        "tests/fixtures/guide/intent/"
        "task11_production_path_matrix_v1.jsonl"
    ]
    assert manifest["fixture_paths"] == audit["fixture_dependencies"]
    assert set(manifest["protected_paths"]) == {
        *manifest["test_paths"],
        *manifest["tool_paths"],
        *manifest["plan_paths"],
        *manifest["fixture_paths"],
    }


def test_test_path_audit_rejects_empty_named_production_test(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    production_test = (
        root
        / "tests/guide/tools/test_task11_production_path_matrix.py"
    )
    fixture = (
        root
        / "tests/fixtures/guide/intent/"
        "task11_production_path_matrix_v1.jsonl"
    )
    tool = (
        root
        / "tools/guide_gates/"
        "run_task11_production_path_matrix.py"
    )
    plan = root / "docs/superpowers/plans/plan.md"
    for path in (production_test, fixture, tool, plan):
        path.parent.mkdir(parents=True, exist_ok=True)
    production_test.write_text(
        (
            "CASES = 'tests/fixtures/guide/intent/"
            "task11_production_path_matrix_v1.jsonl'\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    pass\n"
        ),
        encoding="utf-8",
    )
    fixture.write_text(
        _production_matrix_fixture_rows(),
        encoding="utf-8",
    )
    plan.write_text(
        """
# Plan

Plan revision: task11-r1

### Task 11: Close

**Files:**
- Test: `tests/guide/tools/test_task11_production_path_matrix.py`

- [ ] **Step 0: Run**
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="production-path test body is invalid",
    ):
        readiness.build_test_path_audit(
            repo_root=root,
            plan_path=plan,
            output_path=root / "test-path-audit.json",
        )


def test_production_path_test_rejects_runner_after_terminating_branch(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_task11_production_path_matrix.py"
    test_path.write_text(
        (
            "from tools.guide_gates.run_task11_production_path_matrix "
            "import run_production_path_matrix\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    if True:\n"
            "        return\n"
            "    summary = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
            "        cases_path=CASES,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    assert summary.passed is True\n"
        ),
        encoding="utf-8",
    )

    assert not readiness._production_path_test_executes_runner(test_path)


def test_production_path_test_rejects_assertion_after_return(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_task11_production_path_matrix.py"
    test_path.write_text(
        (
            "from tools.guide_gates.run_task11_production_path_matrix "
            "import run_production_path_matrix\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    summary = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
            "        cases_path=CASES,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    return\n"
            "    assert summary.passed is True\n"
        ),
        encoding="utf-8",
    )

    assert not readiness._production_path_test_executes_runner(test_path)


def test_production_path_test_rejects_runner_after_failing_assert(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_task11_production_path_matrix.py"
    test_path.write_text(
        (
            "from tools.guide_gates.run_task11_production_path_matrix "
            "import run_production_path_matrix\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    assert False\n"
            "    summary = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
            "        cases_path=CASES,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    assert summary.passed is True\n"
        ),
        encoding="utf-8",
    )

    assert not readiness._production_path_test_executes_runner(test_path)


def test_production_path_test_rejects_nested_result_rebinding(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_task11_production_path_matrix.py"
    test_path.write_text(
        (
            "from tools.guide_gates.run_task11_production_path_matrix "
            "import run_production_path_matrix\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    summary = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
            "        cases_path=CASES,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    if True:\n"
            "        summary = forged\n"
            "    assert summary.passed is True\n"
        ),
        encoding="utf-8",
    )

    assert not readiness._production_path_test_executes_runner(test_path)


def test_production_path_test_rejects_nested_second_runner_call(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_task11_production_path_matrix.py"
    test_path.write_text(
        (
            "from tools.guide_gates.run_task11_production_path_matrix "
            "import run_production_path_matrix\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    summary = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
            "        cases_path=CASES,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    if True:\n"
            "        run_production_path_matrix(\n"
            "            repo_root=REPO_ROOT,\n"
            "            cases_path=CASES,\n"
            "            state_root=STATE_ROOT,\n"
            "            candidate_manifest_sha256='a' * 64,\n"
            "            protected_payload_sha256='b' * 64,\n"
            "            cases_sha256='c' * 64,\n"
            "        )\n"
            "    assert summary.passed is True\n"
        ),
        encoding="utf-8",
    )

    assert not readiness._production_path_test_executes_runner(test_path)


def test_production_path_test_rejects_runner_after_terminating_try(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_task11_production_path_matrix.py"
    test_path.write_text(
        (
            "from tools.guide_gates.run_task11_production_path_matrix "
            "import run_production_path_matrix\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    try:\n"
            "        return\n"
            "    finally:\n"
            "        cleanup()\n"
            "    summary = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
            "        cases_path=CASES,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    assert summary.passed is True\n"
        ),
        encoding="utf-8",
    )

    assert not readiness._production_path_test_executes_runner(test_path)


def test_production_path_test_rejects_runner_after_infinite_loop(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_task11_production_path_matrix.py"
    test_path.write_text(
        (
            "from tools.guide_gates.run_task11_production_path_matrix "
            "import run_production_path_matrix\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    while True:\n"
            "        pass\n"
            "    summary = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
            "        cases_path=CASES,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    assert summary.passed is True\n"
        ),
        encoding="utf-8",
    )

    assert not readiness._production_path_test_executes_runner(test_path)


def test_production_path_test_rejects_impure_extra_assertion(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "test_task11_production_path_matrix.py"
    test_path.write_text(
        (
            "from tools.guide_gates.run_task11_production_path_matrix "
            "import run_production_path_matrix\n\n"
            "def test_frozen_matrix_runs_full_http_production_path():\n"
            "    summary = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
            "        cases_path=CASES,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    assert mutate(summary)\n"
            "    assert summary.passed is True\n"
        ),
        encoding="utf-8",
    )

    assert not readiness._production_path_test_executes_runner(test_path)


def test_test_path_audit_ignores_non_repository_fixture_examples(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    production_test = (
        root
        / "tests/guide/tools/test_task11_production_path_matrix.py"
    )
    fixture = (
        root
        / "tests/fixtures/guide/intent/"
        "task11_production_path_matrix_v1.jsonl"
    )
    tool = (
        root
        / "tools/guide_gates/"
        "run_task11_production_path_matrix.py"
    )
    plan = root / "docs/superpowers/plans/plan.md"
    for path in (production_test, fixture, tool, plan):
        path.parent.mkdir(parents=True, exist_ok=True)
    production_test.write_text(
        "\n".join(
            (
                (
                    "from tools.guide_gates."
                    "run_task11_production_path_matrix import "
                    "run_production_path_matrix"
                ),
                "CASES = (",
                "    'tests/fixtures/guide/intent/'",
                "    'task11_production_path_matrix_v1.jsonl'",
                ")",
                "SYNTHETIC_PLAN = '''",
                "- Create: `tests/fixtures/guide/example.json`",
                "'''",
                "TMP_REPOSITORY_FIXTURE = (",
                "    'tests/fixtures/guide/task11.json'",
                ")",
                "",
                "def test_frozen_matrix_runs_full_http_production_path():",
                "    summary = run_production_path_matrix(",
                "        repo_root=REPO_ROOT,",
                "        cases_path=CASES,",
                "        state_root=STATE_ROOT,",
                "        candidate_manifest_sha256='a' * 64,",
                "        protected_payload_sha256='b' * 64,",
                "        cases_sha256='c' * 64,",
                "    )",
                "    assert summary.passed is True",
                "",
            )
        ),
        encoding="utf-8",
    )
    fixture.write_text(
        _production_matrix_fixture_rows(),
        encoding="utf-8",
    )
    tool.write_text(
        (
            "def run_production_path_matrix(**kwargs):\n"
            "    return None\n"
        ),
        encoding="utf-8",
    )
    plan.write_text(
        """
# Plan

Plan revision: task11-r1

### Task 11: Close

**Files:**
- Test: `tests/guide/tools/test_task11_production_path_matrix.py`
- Create: `tools/guide_gates/run_task11_production_path_matrix.py`

- [ ] **Step 0: Run**
""".lstrip(),
        encoding="utf-8",
    )

    audit = readiness.build_test_path_audit(
        repo_root=root,
        plan_path=plan,
        output_path=root / "test-path-audit.json",
    )

    assert audit["passed"] is True
    assert audit["fixture_dependencies"] == [
        "tests/fixtures/guide/intent/"
        "task11_production_path_matrix_v1.jsonl"
    ]
    assert audit["missing_fixture_dependencies"] == []


def test_test_path_audit_discovers_pathlib_fixture_composition(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    test_path = root / "tests/guide/intent/test_transitions.py"
    fixture = (
        root
        / "tests/fixtures/guide/intent/"
        "transition_metamorphic_v1.jsonl"
    )
    for path in (test_path, fixture):
        path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "FIXTURE = (",
                "    Path(__file__).resolve().parents[2]",
                "    / 'fixtures'",
                "    / 'guide'",
                "    / 'intent'",
                "    / 'transition_metamorphic_v1.jsonl'",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    fixture.write_text("{}\n", encoding="utf-8")
    expected = (
        "tests/fixtures/guide/intent/"
        "transition_metamorphic_v1.jsonl"
    )
    assert readiness._fixture_dependencies_in_python(
        test_path,
        repo_root=root,
    ) == (expected,)


def test_test_path_audit_resolves_module_fixture_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    test_path = root / "tests/guide/intent/test_transitions.py"
    fixture = (
        root
        / "tests/fixtures/guide/intent/"
        "transition_metamorphic_v1.jsonl"
    )
    for path in (test_path, fixture):
        path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "FIXTURE_ROOT = (",
                "    Path(__file__).resolve().parents[2]",
                "    / 'fixtures'",
                "    / 'guide'",
                "    / 'intent'",
                ")",
                "CASE_PATH = FIXTURE_ROOT / "
                "'transition_metamorphic_v1.jsonl'",
                "",
            )
        ),
        encoding="utf-8",
    )
    fixture.write_text("{}\n", encoding="utf-8")

    assert readiness._fixture_dependencies_in_python(
        test_path,
        repo_root=root,
    ) == (
        "tests/fixtures/guide/intent/"
        "transition_metamorphic_v1.jsonl",
    )


def test_readiness_is_derived_from_evidence_and_rejects_drift(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent
        / "task11-candidate-readiness.json"
    )

    result = _derive_or_seal_candidate_readiness(
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
        single_path_architecture_path=evidence[
            "single_path_architecture"
        ],
        test_path_audit_path=evidence["test_path_audit"],
        production_path_summary_path=(
            evidence["production_path_summary"]
        ),
        independent_audit_path=evidence["independent_audit"],
        desktop_summary_path=evidence["desktop_summary"],
        mobile_summary_path=evidence["mobile_summary"],
        ledger_path=ledger,
        output_path=output,
    )

    assert result["step_0_passed"] is True
    assert result["step_0_5_passed"] is True
    assert result["step_4_5_passed"] is True
    assert result["step_4_6_passed"] is True
    assert result["affected_zero_api_passed"] is True
    assert result["single_path_architecture_passed"] is True
    assert result["production_path_matrix_passed"] is True
    assert result["provider_call_count"] == 0
    assert result["outbound_network_attempt_count"] == 0
    assert result["runtime_process_tree_non_loopback_attempt_count"] == 0
    assert result["fixture_browser_non_loopback_attempt_count"] == 0
    assert result["fixture_process_tree_non_loopback_attempt_count"] == 0
    assert result["desktop_fixture_passed"] is True
    assert result["mobile_fixture_passed"] is True
    assert result["invalid_clarification_count"] == 0
    assert result["circuit_state"] == "closed"
    ledger_payload = attempt_ledger.read_ledger(ledger)
    assert result["ledger_anchor_revision"] == ledger_payload["revision"]
    assert result["ledger_anchor_hash"] == (
        ledger_payload["revision_chain"][-1]["revision_hash"]
    )
    readiness.verify_saved_readiness(
        readiness_path=output,
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
        single_path_architecture_path=evidence[
            "single_path_architecture"
        ],
        test_path_audit_path=evidence["test_path_audit"],
        production_path_summary_path=(
            evidence["production_path_summary"]
        ),
        independent_audit_path=evidence["independent_audit"],
        desktop_summary_path=evidence["desktop_summary"],
        mobile_summary_path=evidence["mobile_summary"],
        ledger_path=ledger,
    )

    (root / "app/guide/example.py").write_text(
        "VALUE = 3\n",
        encoding="utf-8",
    )
    with pytest.raises(
        readiness.Task11ReadinessError,
        match="protected payload drift",
    ):
        readiness.verify_saved_readiness(
            readiness_path=output,
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
                runtime_network_report_path=evidence[
                    "runtime_network_report"
                ],
                single_path_architecture_path=evidence[
                    "single_path_architecture"
                ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_revalidates_protected_payload_before_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent
        / "task11-candidate-readiness.json"
    )
    expected = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )["protected_payload_sha256"]
    calls = 0
    original = readiness.canonical_payload_sha256

    def changed_after_validation(
        repo_root: str | Path,
        paths: tuple[str, ...] | list[str],
    ) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(repo_root, paths)
        return "0" * 64

    monkeypatch.setattr(
        readiness,
        "canonical_payload_sha256",
        changed_after_validation,
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="protected payload drift",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=output,
        )

    assert calls >= 2
    assert not output.exists()
    assert expected != "0" * 64


def test_candidate_readiness_requires_reviewed_manifest_sha256(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="reviewed SHA-256",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256="0" * 64,
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_completion_fields_are_derived_from_evidence() -> None:
    source = inspect.getsource(readiness.derive_candidate_readiness)

    for field in (
        "step_0_passed",
        "step_0_5_passed",
        "step_4_5_passed",
        "step_4_6_passed",
        "affected_zero_api_passed",
        "single_path_architecture_passed",
        "production_path_matrix_passed",
        "desktop_fixture_passed",
        "mobile_fixture_passed",
    ):
        assert f'"{field}": True' not in source


def test_task11_readiness_requires_external_manifest_sha256() -> None:
    parameter = inspect.signature(
        readiness.verify_task11_readiness
    ).parameters["expected_manifest_sha256"]

    assert parameter.default is inspect.Parameter.empty


def test_release_readiness_branch_forwards_external_manifest_sha256(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    saved = tmp_path / "task11-release-readiness.json"
    _write_json(
        saved,
        {
            "schema_version": "guide-task11-release-readiness-v1",
            "task11_commit": "a" * 40,
        },
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        readiness,
        "verify_release_readiness",
        lambda **kwargs: observed.update(kwargs) or {"passed": True},
    )

    readiness.verify_task11_readiness(
        readiness_path=saved,
        ledger_path=tmp_path / "ledger.json",
        expected_manifest_sha256="b" * 64,
    )

    assert observed["expected_manifest_sha256"] == "b" * 64


def test_readiness_rejects_independent_audit_without_task12_tool_check(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    audit = json.loads(
        evidence["independent_audit"].read_text(encoding="utf-8")
    )
    audit["checks"].pop("task12_execution_tools")
    _write_json(evidence["independent_audit"], audit)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="independent audit evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        {
            "finding_count": 1,
            "p0_finding_count": 1,
            "p1_finding_count": 0,
            "findings": [{"severity": "P0", "detail": "forged"}],
        },
        {"candidate_manifest_sha256": "f" * 64},
        {"production_diff_sha256": "f" * 64},
        {"checks": {"task12_execution_tools": True, "manifest": False}},
    ),
)
def test_readiness_rejects_incomplete_or_failing_independent_audit(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    audit = json.loads(
        evidence["independent_audit"].read_text(encoding="utf-8")
    )
    audit.update(mutation)
    _write_json(evidence["independent_audit"], audit)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="independent audit evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_seal_rejects_existing_output(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent
        / "task11-candidate-readiness.json"
    )
    arguments = {
        "manifest_path": manifest_path,
        "expected_manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "semantic_summary_path": evidence["semantic_summary"],
        "zero_api_summary_path": evidence["zero_api_summary"],
        "network_report_path": evidence["network_report"],
        "runtime_network_report_path": evidence[
            "runtime_network_report"
        ],
        "single_path_architecture_path": evidence[
            "single_path_architecture"
        ],
        "test_path_audit_path": evidence["test_path_audit"],
        "production_path_summary_path": (
            evidence["production_path_summary"]
        ),
        "independent_audit_path": evidence["independent_audit"],
        "desktop_summary_path": evidence["desktop_summary"],
        "mobile_summary_path": evidence["mobile_summary"],
        "ledger_path": ledger,
        "output_path": output,
    }
    _derive_or_seal_candidate_readiness(**arguments)
    before = output.read_bytes()

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="readiness already exists",
    ):
        _derive_or_seal_candidate_readiness(**arguments)

    assert output.read_bytes() == before


def test_saved_readiness_accepts_valid_ledger_extension(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent
        / "task11-candidate-readiness.json"
    )
    _derive_or_seal_candidate_readiness(
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
        single_path_architecture_path=evidence[
            "single_path_architecture"
        ],
        test_path_audit_path=evidence["test_path_audit"],
        production_path_summary_path=(
            evidence["production_path_summary"]
        ),
        independent_audit_path=evidence["independent_audit"],
        desktop_summary_path=evidence["desktop_summary"],
        mobile_summary_path=evidence["mobile_summary"],
        ledger_path=ledger,
        output_path=output,
    )
    current = attempt_ledger.read_ledger(ledger)
    attempt_ledger.compare_and_swap_ledger(
        ledger,
        expected_revision=current["revision"],
        mutate=lambda payload: payload,
    )

    verified = readiness.verify_saved_readiness(
        readiness_path=output,
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
        single_path_architecture_path=evidence[
            "single_path_architecture"
        ],
        test_path_audit_path=evidence["test_path_audit"],
        production_path_summary_path=(
            evidence["production_path_summary"]
        ),
        independent_audit_path=evidence["independent_audit"],
        desktop_summary_path=evidence["desktop_summary"],
        mobile_summary_path=evidence["mobile_summary"],
        ledger_path=ledger,
    )

    assert verified["ledger_anchor_revision"] == 0
    assert attempt_ledger.read_ledger(ledger)["revision"] == 1


def test_saved_readiness_uses_one_ledger_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent
        / "task11-candidate-readiness.json"
    )
    derive_arguments = {
        "manifest_path": manifest_path,
        "expected_manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "semantic_summary_path": evidence["semantic_summary"],
        "zero_api_summary_path": evidence["zero_api_summary"],
        "network_report_path": evidence["network_report"],
        "runtime_network_report_path": evidence[
            "runtime_network_report"
        ],
        "single_path_architecture_path": evidence[
            "single_path_architecture"
        ],
        "test_path_audit_path": evidence["test_path_audit"],
        "production_path_summary_path": evidence[
            "production_path_summary"
        ],
        "independent_audit_path": evidence["independent_audit"],
        "desktop_summary_path": evidence["desktop_summary"],
        "mobile_summary_path": evidence["mobile_summary"],
        "ledger_path": ledger,
    }
    _derive_or_seal_candidate_readiness(
        **derive_arguments,
        output_path=output,
    )
    snapshot = attempt_ledger.read_ledger(ledger)
    calls = 0

    def read_once(path: str | Path) -> dict[str, object]:
        nonlocal calls
        assert Path(path) == ledger
        calls += 1
        if calls > 1:
            pytest.fail("readiness verification split its ledger snapshot")
        return snapshot

    monkeypatch.setattr(readiness, "read_ledger", read_once)

    readiness.verify_saved_readiness(
        readiness_path=output,
        **derive_arguments,
    )

    assert calls == 1


def test_readiness_recomputes_pass_fields_instead_of_trusting_json(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    semantic = json.loads(
        evidence["semantic_summary"].read_text(encoding="utf-8")
    )
    semantic["fit_count"] = 1
    _write_json(evidence["semantic_summary"], semantic)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="semantic matrix evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        {"cases_sha256": "f" * 64},
        {"fit_count": 3, "explore_count": 29},
    ),
)
def test_readiness_rejects_self_authored_semantic_summary(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    semantic = json.loads(
        evidence["semantic_summary"].read_text(encoding="utf-8")
    )
    semantic.update(mutation)
    _write_json(evidence["semantic_summary"], semantic)
    audit = json.loads(
        evidence["independent_audit"].read_text(encoding="utf-8")
    )
    audit["reviewed_evidence_sha256"]["semantic_summary"] = sha256(
        evidence["semantic_summary"].read_bytes()
    ).hexdigest()
    _write_json(evidence["independent_audit"], audit)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="semantic matrix evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_rejects_audit_without_reviewed_evidence_hashes(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    audit = json.loads(
        evidence["independent_audit"].read_text(encoding="utf-8")
    )
    audit.pop("reviewed_evidence_sha256")
    _write_json(evidence["independent_audit"], audit)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="independent audit evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_semantic_summary_is_derived_from_reviewed_matrix(
    tmp_path: Path,
) -> None:
    output = tmp_path / "semantic-summary.json"

    result = readiness.build_semantic_summary(
        cases_path=Path(
            "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
        ),
        output_path=output,
    )

    assert result["passed"] is True
    assert result["case_count"] == 128
    assert result["fit_count"] == 0
    assert result["explore_count"] == 34
    assert result["image_fit_count"] == 0
    assert result["matrix_kind"] == "expected_contract"
    assert result["recommendation_outcome_contract_gap_count"] == 0
    assert "missing_actual_outcome_count" not in result
    assert output.is_file()


def test_readiness_rejects_missing_production_path_summary(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    evidence["production_path_summary"].unlink()

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="production path summary is invalid",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_rejects_production_summary_from_other_candidate(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    production = json.loads(
        evidence["production_path_summary"].read_text(encoding="utf-8")
    )
    production.update({
        "candidate_manifest_sha256": "f" * 64,
        "protected_payload_sha256": "e" * 64,
        "cases_sha256": "d" * 64,
    })
    _write_json(evidence["production_path_summary"], production)
    audit = json.loads(
        evidence["independent_audit"].read_text(encoding="utf-8")
    )
    audit["reviewed_evidence_sha256"]["production_path_summary"] = sha256(
        evidence["production_path_summary"].read_bytes()
    ).hexdigest()
    _write_json(evidence["independent_audit"], audit)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="production path summary failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_binds_matrix_to_browser_bounded_messages() -> None:
    observed = readiness._validate_bounded_trajectory_messages(
        repo_root=Path.cwd(),
        cases_path=Path(PRODUCTION_MATRIX_FIXTURE_PATH),
    )

    assert len(observed) == 9
    assert observed[-2:] == (
        (
            "bounded-image-context",
            "bounded-image-context-t2",
            "给我找两款相似的，我最近换季泛红，T 区出油。",
        ),
        (
            "bounded-image-context",
            "bounded-image-context-t3",
            "图片里的 B5 和第一款哪个更适合我的肤质？",
        ),
    )


def test_readiness_rejects_bounded_browser_message_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    browser_path = root / BOUNDED_BROWSER_TOOL_PATH
    browser_path.parent.mkdir(parents=True)
    source = Path(BOUNDED_BROWSER_TOOL_PATH).read_text(encoding="utf-8")
    original = '"给我找两款相似的，我最近换季泛红，"'
    assert source.count(original) == 1
    browser_path.write_text(
        source.replace(original, '"给我找三款相似的，"', 1),
        encoding="utf-8",
    )
    cases_path = root / PRODUCTION_MATRIX_FIXTURE_PATH
    cases_path.parent.mkdir(parents=True)
    cases_path.write_bytes(
        Path(PRODUCTION_MATRIX_FIXTURE_PATH).read_bytes()
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="bounded trajectory messages",
    ):
        readiness._validate_bounded_trajectory_messages(
            repo_root=root,
            cases_path=cases_path,
        )


def test_readiness_rejects_unmeasured_provider_count(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    zero_api = json.loads(
        evidence["zero_api_summary"].read_text(encoding="utf-8")
    )
    zero_api.pop("network_report_sha256")
    _write_json(evidence["zero_api_summary"], zero_api)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="zero API evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_rejects_invalid_test_path_claim(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    audit = json.loads(
        evidence["test_path_audit"].read_text(encoding="utf-8")
    )
    audit["invalid_production_path_claim_count"] = 1
    _write_json(evidence["test_path_audit"], audit)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="test path audit failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_rejects_unmeasured_processor_invocations(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    production = json.loads(
        evidence["production_path_summary"].read_text(
            encoding="utf-8"
        )
    )
    production["turn_traces"][0].pop("processor_invocation_counts")
    _write_json(evidence["production_path_summary"], production)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="production path summary failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_requires_pre_decision_rejection_coverage(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    production = json.loads(
        evidence["production_path_summary"].read_text(encoding="utf-8")
    )
    production["pre_decision_rejection_count"] = 0
    _write_json(evidence["production_path_summary"], production)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="production path summary failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_rejects_measured_network_attempt(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    network = json.loads(
        evidence["network_report"].read_text(encoding="utf-8")
    )
    network.update({
        "passed": False,
        "outbound_network_attempt_count": 1,
        "attempts": [{"kind": "DNS", "target": "example.com"}],
    })
    _write_json(evidence["network_report"], network)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="zero API network evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_rejects_single_path_architecture_violation(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    architecture = json.loads(
        evidence["single_path_architecture"].read_text(
            encoding="utf-8"
        )
    )
    architecture.update({
        "passed": False,
        "violation_count": 1,
        "violations": [{"rule": "POST_CAS_SERIALIZATION_CAPABILITY"}],
    })
    _write_json(evidence["single_path_architecture"], architecture)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="single-path architecture failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_rejects_runtime_process_tree_escape(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    runtime_network = json.loads(
        evidence["runtime_network_report"].read_text(
            encoding="utf-8"
        )
    )
    runtime_network[
        "runtime_process_tree_non_loopback_attempt_count"
    ] = 1
    _write_json(evidence["runtime_network_report"], runtime_network)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="zero API runtime network evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_rejects_non_quiescent_runtime_process_group(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    runtime_network = json.loads(
        evidence["runtime_network_report"].read_text(
            encoding="utf-8"
        )
    )
    runtime_network["process_group_quiescent"] = False
    _write_json(evidence["runtime_network_report"], runtime_network)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="zero API runtime network evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_rejects_jointly_forged_identity_and_challenge_digests(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    original_identity = json.loads(
        (
            evidence["desktop_summary"].parent
            / "runtime-identity.json"
        ).read_text(encoding="utf-8")
    )
    forged_private_key = Ed25519PrivateKey.from_private_bytes(
        bytes(reversed(range(32)))
    )
    forged_public_key = (
        base64.urlsafe_b64encode(
            forged_private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
        .decode("ascii")
        .rstrip("=")
    )
    forged_unsigned_identity = {
        key: value
        for key, value in original_identity.items()
        if key not in {"identity_sha256", "identity_signature"}
    }
    forged_unsigned_identity["runtime_nonce"] = "a" * 64
    forged_unsigned_identity["runtime_public_key"] = forged_public_key
    forged_signed_identity = {
        **forged_unsigned_identity,
        "identity_sha256": sha256(
            _canonical_bytes(forged_unsigned_identity)
        ).hexdigest(),
    }
    forged_identity = {
        **forged_signed_identity,
        "identity_signature": _sign_test_payload(
            IDENTITY_SIGNATURE_DOMAIN,
            forged_signed_identity,
            private_key=forged_private_key,
        ),
    }
    forged_identity_bytes = _canonical_bytes(forged_identity)
    forged_identity_sha256 = sha256(
        forged_identity_bytes
    ).hexdigest()
    forged_challenge_sha256s: list[str] = []
    for role, challenge in (
        ("desktop_summary", "b" * 64),
        ("mobile_summary", "c" * 64),
    ):
        summary_path = evidence[role]
        fixture_root = summary_path.parent
        identity_path = fixture_root / "runtime-identity.json"
        challenge_path = (
            fixture_root
            / "consumed-runtime-health-challenge.json"
        )
        identity_path.write_bytes(forged_identity_bytes)
        unsigned_challenge = {
            "schema_version": (
                "guide-zero-api-runtime-challenge-v1"
            ),
            "runtime_identity_sha256": forged_identity_sha256,
            "challenge": challenge,
        }
        signed_challenge = {
            **unsigned_challenge,
            "challenge_sha256": sha256(
                _canonical_bytes(unsigned_challenge)
            ).hexdigest(),
        }
        challenge_payload = {
            **signed_challenge,
            "challenge_signature": _sign_test_payload(
                CHALLENGE_SIGNATURE_DOMAIN,
                signed_challenge,
                private_key=forged_private_key,
            ),
        }
        challenge_path.write_bytes(
            _canonical_bytes(challenge_payload)
        )
        challenge_sha256 = challenge_payload["challenge_sha256"]
        forged_challenge_sha256s.append(challenge_sha256)
        summary = json.loads(
            summary_path.read_text(encoding="utf-8")
        )
        summary["runtime_identity_sha256"] = (
            forged_identity_sha256
        )
        summary["consumed_health_challenge_sha256"] = (
            challenge_sha256
        )
        summary["artifact_sha256_by_path"][
            "runtime-identity.json"
        ] = sha256(forged_identity_bytes).hexdigest()
        summary["artifact_sha256_by_path"][
            "consumed-runtime-health-challenge.json"
        ] = sha256(challenge_path.read_bytes()).hexdigest()
        _write_json(summary_path, summary)

    runtime_network = json.loads(
        evidence["runtime_network_report"].read_text(encoding="utf-8")
    )
    runtime_network.pop("runtime_report_signature")
    runtime_network["runtime_identity_sha256"] = (
        forged_identity_sha256
    )
    runtime_network["fixture_runtime_public_key"] = forged_public_key
    runtime_network["consumed_health_challenge_sha256s"] = (
        forged_challenge_sha256s
    )
    runtime_network["runtime_report_signature"] = _sign_test_payload(
        PARENT_REPORT_SIGNATURE_DOMAIN,
        runtime_network,
        private_key=forged_private_key,
    )
    _write_json(evidence["runtime_network_report"], runtime_network)
    audit = json.loads(
        evidence["independent_audit"].read_text(encoding="utf-8")
    )
    for role in (
        "runtime_network_report",
        "desktop_summary",
        "mobile_summary",
    ):
        audit["reviewed_evidence_sha256"][role] = sha256(
            evidence[role].read_bytes()
        ).hexdigest()
    _write_json(evidence["independent_audit"], audit)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="runtime provenance",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_zero_api_network_report_requires_process_guard_evidence() -> None:
    report = {
        "schema_version": "guide-zero-api-network-report-v1",
        "guard_active": True,
        "passed": True,
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
        "attempts": [],
    }

    assert readiness._network_report_passed(report) is False

    report.update({
        "process_guard_active": True,
        "kernel_network_sandbox_active": True,
        "child_process_policy": "kernel_inherited_network_deny",
        "process_creation_attempt_count": 0,
        "process_creation_attempts": [],
    })

    assert readiness._network_report_passed(report) is True


def test_zero_api_summary_reuses_the_reviewed_manifest_sha256(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    expected_manifest_sha256 = sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    network_report = root / "network.json"
    network_payload = {
        "schema_version": "guide-zero-api-network-report-v1",
        "guard_active": True,
        "process_guard_active": True,
        "kernel_network_sandbox_active": True,
        "child_process_policy": "kernel_inherited_network_deny",
        "passed": True,
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
        "attempts": [],
        "process_creation_attempt_count": 0,
        "process_creation_attempts": [],
    }
    monkeypatch.setattr(
        readiness,
        "_zero_api_commands",
        lambda *_, **__: (("fake-zero-api-command",),),
    )
    original_read_bytes = Path.read_bytes

    def replaced_manifest_read(path: Path) -> bytes:
        if path == manifest_path:
            return b"candidate manifest replaced after validation"
        return original_read_bytes(path)

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        _write_json(network_report, network_payload)
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout="ok\n",
            stderr="",
        )

    monkeypatch.setattr(Path, "read_bytes", replaced_manifest_read)

    result = readiness.run_zero_api_suite(
        repo_root=root,
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        output_path=root / "zero-api.json",
        network_report_path=network_report,
        command_runner=run,
    )

    assert (
        result["candidate_manifest_sha256"]
        == expected_manifest_sha256
    )


def test_readiness_rejects_missing_runtime_drain_marker(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    runtime_network = json.loads(
        evidence["runtime_network_report"].read_text(
            encoding="utf-8"
        )
    )
    nonce = runtime_network["measurement_nonce"]
    assert isinstance(nonce, str)
    events = [
        json.loads(line)
        for line in runtime_network["seatbelt_raw_ndjson"].splitlines()
        if f"XIAORO_RUNTIME_SEATBELT_DRAIN:{nonce}" not in line
    ]
    raw = "".join(
        json.dumps(event, sort_keys=True) + "\n"
        for event in events
    )
    runtime_network.update({
        "seatbelt_raw_ndjson": raw,
        "seatbelt_raw_ndjson_sha256": sha256(
            raw.encode("utf-8")
        ).hexdigest(),
        "seatbelt_raw_byte_count": len(raw.encode("utf-8")),
        "seatbelt_event_count": len(events),
        "logger_drain_marker_count": 0,
    })
    _write_json(evidence["runtime_network_report"], runtime_network)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="zero API runtime network evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_derives_runtime_escape_from_raw_kernel_log(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    runtime_network = json.loads(
        evidence["runtime_network_report"].read_text(
            encoding="utf-8"
        )
    )
    nonce = runtime_network["measurement_nonce"]
    assert isinstance(nonce, str)
    events = [
        json.loads(line)
        for line in runtime_network["seatbelt_raw_ndjson"].splitlines()
    ]
    events.insert(
        -1,
        {
            "eventType": "logEvent",
            "processImagePath": "/kernel",
            "senderImagePath": (
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            ),
            "eventMessage": (
                "Sandbox: Python(4100) deny(1) "
                f"network-outbound remote:*:8443\n{nonce}"
            ),
        },
    )
    raw = "".join(
        json.dumps(event, sort_keys=True) + "\n"
        for event in events
    )
    runtime_network.update({
        "seatbelt_raw_ndjson": raw,
        "seatbelt_raw_ndjson_sha256": sha256(
            raw.encode("utf-8")
        ).hexdigest(),
        "seatbelt_raw_byte_count": len(raw.encode("utf-8")),
        "seatbelt_event_count": len(events),
        "process_tree_attempts": [],
        "runtime_process_tree_non_loopback_attempt_count": 0,
        "passed": True,
    })
    _write_json(evidence["runtime_network_report"], runtime_network)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="zero API runtime network evidence failed",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


@pytest.mark.parametrize(
    "relative_path",
    (
        "fixture-explore-recommendation/screenshot.png",
        "fixture-explore-recommendation/stream.sse",
        "browser-requests.json",
        "chromium-netlog.json",
        "seatbelt.raw.ndjson",
        "sandbox-audit.json",
    ),
)
def test_seal_readiness_rejects_browser_artifact_drift(
    tmp_path: Path,
    relative_path: str,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    artifact = evidence["desktop_summary"].parent / relative_path
    artifact.write_bytes(artifact.read_bytes() + b"drift")
    output = (
        manifest_path.parent
        / "task11-candidate-readiness.json"
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="fixture artifact index",
    ):
        _derive_or_seal_candidate_readiness(
            manifest_path=manifest_path,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=output,
        )

    assert not output.exists()


def test_zero_api_summary_runs_only_manifest_test_paths(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    output = root / "zero-api.json"
    network_report = root / "zero-api-network.json"
    calls: list[tuple[str, ...]] = []

    def run(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "pytest" in command:
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            _write_json(
                Path(environment["XIAORO_ZERO_API_NETWORK_REPORT"]),
                {
                    "schema_version": (
                        "guide-zero-api-network-report-v1"
                    ),
                    "guard_active": True,
                    "process_guard_active": True,
                    "kernel_network_sandbox_active": True,
                    "child_process_policy": (
                        "kernel_inherited_network_deny"
                    ),
                    "passed": True,
                    "provider_call_count": 0,
                    "outbound_network_attempt_count": 0,
                    "attempts": [],
                    "process_creation_attempt_count": 0,
                    "process_creation_attempts": [],
                },
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ok\n",
            stderr="",
        )

    result = readiness.run_zero_api_suite(
        repo_root=root,
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        output_path=output,
        network_report_path=network_report,
        command_runner=run,
        python_executable="python",
    )

    assert result["passed"] is True
    assert result["provider_call_count"] == 0
    assert result["outbound_network_attempt_count"] == 0
    assert result["process_creation_attempt_count"] == 0
    assert calls[0] == ("git", "diff", "--check")
    assert calls[1][:4] == (
        "python",
        "-m",
        "compileall",
        "-q",
    )
    assert calls[2][:3] == (
        "/usr/bin/sandbox-exec",
        "-p",
        readiness.ZERO_API_SANDBOX_PROFILE,
    )
    assert calls[2][7:9] == (
        "-p",
        "tools.guide_gates.zero_api_network_guard",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert calls[2][9:] == tuple(manifest["test_paths"])
    assert "docs/superpowers/plans/plan.md" not in calls[2]


def test_zero_api_summary_requires_reviewed_manifest_sha256(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="reviewed SHA-256",
    ):
        readiness.run_zero_api_suite(
            repo_root=root,
            manifest_path=manifest_path,
            expected_manifest_sha256="0" * 64,
            output_path=root / "zero-api.json",
            network_report_path=root / "zero-api-network.json",
            command_runner=lambda *_, **__: pytest.fail(
                "commands must not run for an unreviewed manifest"
            ),
        )


def test_zero_api_summary_rejects_an_unreviewed_command(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    network_report = tmp_path / "network.json"
    _write_json(
        network_report,
        {
            "schema_version": "guide-zero-api-network-report-v1",
            "guard_active": True,
            "process_guard_active": True,
            "kernel_network_sandbox_active": True,
            "child_process_policy": "kernel_inherited_network_deny",
            "passed": True,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "attempts": [],
            "process_creation_attempt_count": 0,
            "process_creation_attempts": [],
        },
    )
    payload = {
        "schema_version": "guide-task11-zero-api-summary-v1",
        "passed": True,
        "guard_active": True,
        "process_guard_active": True,
        "kernel_network_sandbox_active": True,
        "child_process_policy": "kernel_inherited_network_deny",
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
        "process_creation_attempt_count": 0,
        "process_creation_attempts": [],
        "network_report_sha256": sha256(
            network_report.read_bytes()
        ).hexdigest(),
        "candidate_manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "protected_payload_sha256": (
            manifest["protected_payload_sha256"]
        ),
        "commands": [{
            "argv": ["true"],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }],
    }

    assert not readiness._zero_api_passed(
        payload,
        manifest=manifest,
        root=root,
        network_report=json.loads(
            network_report.read_text(encoding="utf-8")
        ),
        network_report_sha256=sha256(
            network_report.read_bytes()
        ).hexdigest(),
    )


def test_prepare_evidence_does_not_create_audit_or_readiness(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    pre_audit, _ = _evidence(root, manifest_path)
    output = root / "evidence"
    network_report = output / "network.json"
    architecture = root / "architecture.json"
    _write_json(
        architecture,
        {
            "schema_version": (
                "guide-task11-single-path-architecture-v1"
            ),
            "passed": True,
            "inspected_module_count": 1,
            "inspected_modules": ["app.guide.example"],
            "violation_count": 0,
            "violations": [],
            "forbidden_symbol_count": 0,
        },
    )
    calls: list[tuple[str, ...]] = []

    def run(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "pytest" in command:
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            _write_json(
                Path(environment["XIAORO_ZERO_API_NETWORK_REPORT"]),
                {
                    "schema_version": (
                        "guide-zero-api-network-report-v1"
                    ),
                    "guard_active": True,
                    "process_guard_active": True,
                    "kernel_network_sandbox_active": True,
                    "child_process_policy": (
                        "kernel_inherited_network_deny"
                    ),
                    "passed": True,
                    "provider_call_count": 0,
                    "outbound_network_attempt_count": 0,
                    "attempts": [],
                    "process_creation_attempt_count": 0,
                    "process_creation_attempts": [],
                },
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ok\n",
            stderr="",
        )

    result = readiness.prepare_task11_evidence(
        repo_root=root,
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        semantic_summary_path=output / "semantic.json",
        zero_api_summary_path=output / "zero-api.json",
        network_report_path=network_report,
        single_path_architecture_path=architecture,
        test_path_audit_path=pre_audit["test_path_audit"],
        production_path_summary_path=(
            pre_audit["production_path_summary"]
        ),
        cases_path=Path(
            "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
        ),
        command_runner=run,
        python_executable="python",
    )

    assert set(result) == {
        "single_path_architecture",
        "test_path_audit",
        "production_path_summary",
        "semantic_summary",
        "zero_api_summary",
        "network_report",
    }
    assert not (output / "independent-audit.json").exists()
    assert not (output / "readiness.json").exists()
    assert len(calls) == 3


def test_r5_cli_contract_matches_the_authoritative_plan() -> None:
    prepare_arguments = [
        "prepare-evidence",
        "--manifest",
        "manifest.json",
        "--semantic-summary-output",
        "semantic.json",
        "--zero-api-summary-output",
        "zero-api.json",
        "--network-report-output",
        "network.json",
        "--single-path-architecture",
        "architecture.json",
        "--test-path-audit",
        "test-path.json",
        "--production-path-summary",
        "production-path.json",
    ]
    with pytest.raises(SystemExit):
        readiness._parser().parse_args(prepare_arguments)
    prepare = readiness._parser().parse_args([
        *prepare_arguments,
        "--expected-manifest-sha256",
        "a" * 64,
    ])
    assert prepare.semantic_summary_output == Path("semantic.json")
    assert prepare.zero_api_summary_output == Path("zero-api.json")
    assert prepare.network_report_output == Path("network.json")
    assert prepare.single_path_architecture == Path(
        "architecture.json"
    )
    assert prepare.expected_manifest_sha256 == "a" * 64

    seal_arguments = [
        "seal-readiness",
        "--manifest",
        "manifest.json",
        "--readiness",
        "readiness.json",
        "--semantic-summary",
        "semantic.json",
        "--zero-api-summary",
        "zero-api.json",
        "--network-report",
        "network.json",
        "--runtime-network-report",
        "runtime-network.json",
        "--single-path-architecture",
        "architecture.json",
        "--test-path-audit",
        "test-path.json",
        "--production-path-summary",
        "production-path.json",
        "--independent-audit",
        "audit.json",
        "--desktop-summary",
        "desktop.json",
        "--mobile-summary",
        "mobile.json",
        "--ledger",
        "ledger.json",
    ]
    with pytest.raises(SystemExit):
        readiness._parser().parse_args([
            "derive",
            *seal_arguments[1:],
            "--expected-manifest-sha256",
            "a" * 64,
        ])
    with pytest.raises(SystemExit):
        readiness._parser().parse_args(seal_arguments)
    with pytest.raises(SystemExit):
        readiness._parser().parse_args([
            *seal_arguments,
            "--expected-manifest-sha256",
            "a" * 64,
        ])
    seal = readiness._parser().parse_args([
        *seal_arguments,
        "--expected-manifest-sha256",
        "a" * 64,
        "--fixture-runtime-private-key",
        "/tmp/fixture-runtime-private-key.json",
    ])
    assert seal.runtime_network_report == Path(
        "runtime-network.json"
    )
    assert seal.single_path_architecture == Path(
        "architecture.json"
    )
    assert seal.expected_manifest_sha256 == "a" * 64
    assert seal.fixture_runtime_private_key == Path(
        "/tmp/fixture-runtime-private-key.json"
    )

    finalize = readiness._parser().parse_args([
        "finalize-change-manifest",
        "--draft",
        "draft.json",
        "--candidate-manifest",
        "candidate.json",
        "--candidate-readiness",
        "readiness.json",
        "--ledger",
        "ledger.json",
        "--output",
        "final.json",
        "--expected-manifest-sha256",
        "b" * 64,
    ])
    assert finalize.draft == Path("draft.json")
    assert finalize.candidate_manifest == Path("candidate.json")
    assert finalize.candidate_readiness == Path("readiness.json")
    assert finalize.ledger == Path("ledger.json")
    assert finalize.output == Path("final.json")
    assert finalize.expected_manifest_sha256 == "b" * 64

    commit_seal_arguments = [
        "seal-commit",
        "--manifest",
        "change-manifest.json",
        "--candidate-readiness",
        "candidate-readiness.json",
        "--release-readiness",
        "release-readiness.json",
        "--task11-commit",
        "a" * 40,
    ]
    with pytest.raises(SystemExit):
        readiness._parser().parse_args(commit_seal_arguments)
    commit_seal = readiness._parser().parse_args([
        *commit_seal_arguments,
        "--expected-manifest-sha256",
        "b" * 64,
    ])
    assert commit_seal.manifest == Path("change-manifest.json")
    assert commit_seal.candidate_readiness == Path(
        "candidate-readiness.json"
    )
    assert commit_seal.release_readiness == Path(
        "release-readiness.json"
    )
    assert commit_seal.task11_commit == "a" * 40
    assert commit_seal.expected_manifest_sha256 == "b" * 64

    verify_release_arguments = [
        "verify-release-readiness",
        "--readiness",
        "release-readiness.json",
        "--require-head",
        "a" * 40,
    ]
    with pytest.raises(SystemExit):
        readiness._parser().parse_args(verify_release_arguments)
    verify_release = readiness._parser().parse_args([
        *verify_release_arguments,
        "--expected-manifest-sha256",
        "b" * 64,
    ])
    assert verify_release.readiness == Path("release-readiness.json")
    assert verify_release.require_head == "a" * 40
    assert verify_release.expected_manifest_sha256 == "b" * 64


def test_change_manifest_clis_require_reviewed_manifest_sha256() -> None:
    commands = (
        [
            "finalize-change-manifest",
            "--draft",
            "draft.json",
            "--candidate-manifest",
            "candidate.json",
            "--candidate-readiness",
            "readiness.json",
            "--ledger",
            "ledger.json",
            "--output",
            "final.json",
        ],
        [
            "build-change-manifest",
            "--candidate-manifest",
            "candidate.json",
            "--candidate-readiness",
            "readiness.json",
            "--attempt-context",
            "attempt-context.json",
            "--ledger",
            "ledger.json",
            "--output",
            "draft.json",
        ],
    )

    for arguments in commands:
        with pytest.raises(SystemExit):
            readiness._parser().parse_args(arguments)
        parsed = readiness._parser().parse_args([
            *arguments,
            "--expected-manifest-sha256",
            "c" * 64,
        ])
        assert parsed.expected_manifest_sha256 == "c" * 64


def test_saved_readiness_rejects_late_relevant_worktree_change(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent
        / "task11-candidate-readiness.json"
    )
    _derive_or_seal_candidate_readiness(
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
        single_path_architecture_path=evidence[
            "single_path_architecture"
        ],
        test_path_audit_path=evidence["test_path_audit"],
        production_path_summary_path=(
            evidence["production_path_summary"]
        ),
        independent_audit_path=evidence["independent_audit"],
        desktop_summary_path=evidence["desktop_summary"],
        mobile_summary_path=evidence["mobile_summary"],
        ledger_path=ledger,
        output_path=output,
    )
    late = root / "app/guide/late.py"
    late.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="relevant changed paths missing",
    ):
        readiness.verify_task11_readiness(
            readiness_path=output,
            ledger_path=ledger,
            expected_manifest_sha256=sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            fixture_bundle_verifier=lambda _: None,
        )


def test_saved_readiness_revalidates_all_fixture_bundles(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = (
        manifest_path.parent
        / "task11-candidate-readiness.json"
    )
    _derive_or_seal_candidate_readiness(
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
        runtime_network_report_path=evidence[
            "runtime_network_report"
        ],
        single_path_architecture_path=evidence[
            "single_path_architecture"
        ],
        test_path_audit_path=evidence["test_path_audit"],
        production_path_summary_path=(
            evidence["production_path_summary"]
        ),
        independent_audit_path=evidence["independent_audit"],
        desktop_summary_path=evidence["desktop_summary"],
        mobile_summary_path=evidence["mobile_summary"],
        ledger_path=ledger,
        output_path=output,
    )
    reviewed: list[Path] = []

    readiness.verify_task11_readiness(
        readiness_path=output,
        ledger_path=ledger,
        expected_manifest_sha256=sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        fixture_bundle_verifier=lambda path: reviewed.append(path),
    )

    assert reviewed == [
        evidence["desktop_summary"],
        evidence["mobile_summary"],
    ]


def test_finalize_change_manifest_rejects_missing_bounded_attempt_context(
    tmp_path: Path,
) -> None:
    root, candidate_manifest = _candidate(tmp_path)
    draft = tmp_path / "task11-change-manifest-draft.json"
    _write_json(
        draft,
        {
            "schema_version": "guide-task11-change-manifest-v1",
            "approved_paths": ["candidate.json"],
        },
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="bounded attempt context",
    ):
        readiness.finalize_change_manifest(
            repo_root=root,
            draft_path=draft,
            candidate_manifest_path=candidate_manifest,
            candidate_readiness_path=root / "missing-readiness.json",
            expected_manifest_sha256=sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            ledger_path=root / "missing-ledger.json",
            output_path=root / "task11-change-manifest.json",
        )


def test_finalize_change_manifest_hashes_exact_staged_diff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, candidate_manifest = _candidate(tmp_path)
    candidate = json.loads(
        candidate_manifest.read_text(encoding="utf-8")
    )
    (
        candidate_readiness,
        evidence,
        ledger,
        fixture_artifact_paths,
    ) = _derived_candidate_readiness(root, candidate_manifest)
    monkeypatch.setattr(
        readiness,
        "_verify_fixture_summary_bundles",
        readiness._verify_fixture_artifact_index,
    )
    context_relative = _stub_bounded_attempt_validation(
        monkeypatch,
        root=root,
    )
    ledger_payload = attempt_ledger.read_ledger(ledger)
    ledger_tip = attempt_ledger.ledger_anchor(ledger_payload)
    approved = sorted({
        *candidate["change_paths"],
        candidate_readiness.relative_to(root).as_posix(),
        candidate_manifest.relative_to(root).as_posix(),
        _relative_ledger_path(root, ledger),
        context_relative,
        *(path.relative_to(root).as_posix() for path in evidence.values()),
        *fixture_artifact_paths,
    })
    subprocess.run(
        ["git", "add", "-A", "--", *approved],
        cwd=root,
        check=True,
    )
    draft = tmp_path / "task11-change-manifest-draft.json"
    _write_json(
        draft,
        {
            "schema_version": "guide-task11-change-manifest-v1",
            "plan_revision": candidate["plan_revision"],
            "candidate_manifest_sha256": sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            "candidate_readiness_sha256": sha256(
                candidate_readiness.read_bytes()
            ).hexdigest(),
            "ledger_path": _relative_ledger_path(root, ledger),
            "final_ledger_revision": ledger_tip["revision"],
            "final_ledger_hash": ledger_tip["revision_hash"],
            "bounded_attempt_id": "bounded-smoke-attempt-02",
            "attempt_context_path": context_relative,
            "bounded_artifact_paths": [context_relative],
            "fixture_artifact_paths": fixture_artifact_paths,
            "approved_paths": approved,
            "staged_diff_sha256": None,
            "finalized": False,
        },
    )
    draft_bytes = draft.read_bytes()
    output = root / "task11-change-manifest.json"

    result = readiness.finalize_change_manifest(
        repo_root=root,
        draft_path=draft,
        candidate_manifest_path=candidate_manifest,
        candidate_readiness_path=candidate_readiness,
        expected_manifest_sha256=sha256(
            candidate_manifest.read_bytes()
        ).hexdigest(),
        ledger_path=ledger,
        output_path=output,
    )

    expected_diff = subprocess.run(
        ["git", "diff", "--cached", "--binary", "--", *approved],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    assert result["staged_diff_sha256"] == sha256(
        expected_diff
    ).hexdigest()
    assert result["finalized"] is True
    assert result["final_ledger_revision"] == ledger_tip["revision"]
    assert result["final_ledger_hash"] == ledger_tip["revision_hash"]
    assert output.is_file()
    assert draft.read_bytes() == draft_bytes


def test_finalize_change_manifest_rejects_unapproved_staged_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, candidate_manifest = _candidate(tmp_path)
    candidate = json.loads(
        candidate_manifest.read_text(encoding="utf-8")
    )
    (root / "other.txt").write_text("unapproved\n", encoding="utf-8")
    (
        candidate_readiness,
        evidence,
        ledger,
        fixture_artifact_paths,
    ) = _derived_candidate_readiness(root, candidate_manifest)
    monkeypatch.setattr(
        readiness,
        "_verify_fixture_summary_bundles",
        readiness._verify_fixture_artifact_index,
    )
    context_relative = _stub_bounded_attempt_validation(
        monkeypatch,
        root=root,
    )
    ledger_payload = attempt_ledger.read_ledger(ledger)
    ledger_tip = attempt_ledger.ledger_anchor(ledger_payload)
    approved = sorted({
        *candidate["change_paths"],
        candidate_readiness.relative_to(root).as_posix(),
        candidate_manifest.relative_to(root).as_posix(),
        _relative_ledger_path(root, ledger),
        context_relative,
        *(path.relative_to(root).as_posix() for path in evidence.values()),
        *fixture_artifact_paths,
    })
    subprocess.run(
        ["git", "add", "-A", "--", *approved, "other.txt"],
        cwd=root,
        check=True,
    )
    draft = tmp_path / "task11-change-manifest-draft.json"
    _write_json(
        draft,
        {
            "schema_version": "guide-task11-change-manifest-v1",
            "plan_revision": candidate["plan_revision"],
            "candidate_manifest_sha256": sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            "candidate_readiness_sha256": sha256(
                candidate_readiness.read_bytes()
            ).hexdigest(),
            "ledger_path": _relative_ledger_path(root, ledger),
            "final_ledger_revision": ledger_tip["revision"],
            "final_ledger_hash": ledger_tip["revision_hash"],
            "bounded_attempt_id": "bounded-smoke-attempt-02",
            "attempt_context_path": context_relative,
            "bounded_artifact_paths": [context_relative],
            "fixture_artifact_paths": fixture_artifact_paths,
            "approved_paths": approved,
            "staged_diff_sha256": None,
            "finalized": False,
        },
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="staged path set mismatch",
    ):
        readiness.finalize_change_manifest(
            repo_root=root,
            draft_path=draft,
            candidate_manifest_path=candidate_manifest,
            candidate_readiness_path=candidate_readiness,
            expected_manifest_sha256=sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            ledger_path=ledger,
            output_path=root / "task11-change-manifest.json",
        )


def test_finalize_change_manifest_rejects_forged_fixture_artifact_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, candidate_manifest = _candidate(tmp_path)
    candidate = json.loads(
        candidate_manifest.read_text(encoding="utf-8")
    )
    (
        candidate_readiness,
        evidence,
        ledger,
        fixture_artifact_paths,
    ) = _derived_candidate_readiness(root, candidate_manifest)
    monkeypatch.setattr(
        readiness,
        "_verify_fixture_summary_bundles",
        readiness._verify_fixture_artifact_index,
    )
    context_relative = _stub_bounded_attempt_validation(
        monkeypatch,
        root=root,
    )
    ledger_tip = attempt_ledger.ledger_anchor(
        attempt_ledger.read_ledger(ledger)
    )
    omitted = next(
        path
        for path in fixture_artifact_paths
        if path.endswith(
            "fixture-browser-desktop/"
            "fixture-fit-recommendation/screenshot.png"
        )
    )
    forged_fixture_paths = [
        path for path in fixture_artifact_paths if path != omitted
    ]
    approved = sorted({
        *candidate["change_paths"],
        candidate_readiness.relative_to(root).as_posix(),
        candidate_manifest.relative_to(root).as_posix(),
        _relative_ledger_path(root, ledger),
        context_relative,
        *(path.relative_to(root).as_posix() for path in evidence.values()),
        *forged_fixture_paths,
    })
    subprocess.run(
        ["git", "add", "-A", "--", *approved],
        cwd=root,
        check=True,
    )
    draft = tmp_path / "task11-change-manifest-draft.json"
    _write_json(
        draft,
        {
            "schema_version": "guide-task11-change-manifest-v1",
            "plan_revision": candidate["plan_revision"],
            "candidate_manifest_sha256": sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            "candidate_readiness_sha256": sha256(
                candidate_readiness.read_bytes()
            ).hexdigest(),
            "ledger_path": _relative_ledger_path(root, ledger),
            "final_ledger_revision": ledger_tip["revision"],
            "final_ledger_hash": ledger_tip["revision_hash"],
            "bounded_attempt_id": "bounded-smoke-attempt-02",
            "attempt_context_path": context_relative,
            "bounded_artifact_paths": [context_relative],
            "fixture_artifact_paths": forged_fixture_paths,
            "approved_paths": approved,
            "staged_diff_sha256": None,
            "finalized": False,
        },
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="approved path set",
    ):
        readiness.finalize_change_manifest(
            repo_root=root,
            draft_path=draft,
            candidate_manifest_path=candidate_manifest,
            candidate_readiness_path=candidate_readiness,
            expected_manifest_sha256=sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            ledger_path=ledger,
            output_path=root / "task11-change-manifest.json",
        )


def test_finalize_change_manifest_rejects_ledger_advance_after_draft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, candidate_manifest = _candidate(tmp_path)
    candidate = json.loads(
        candidate_manifest.read_text(encoding="utf-8")
    )
    (
        candidate_readiness,
        evidence,
        ledger,
        fixture_artifact_paths,
    ) = _derived_candidate_readiness(root, candidate_manifest)
    monkeypatch.setattr(
        readiness,
        "_verify_fixture_summary_bundles",
        readiness._verify_fixture_artifact_index,
    )
    context_relative = _stub_bounded_attempt_validation(
        monkeypatch,
        root=root,
    )
    initial = attempt_ledger.read_ledger(ledger)
    initial_tip = attempt_ledger.ledger_anchor(initial)
    approved = sorted({
        *candidate["change_paths"],
        candidate_readiness.relative_to(root).as_posix(),
        candidate_manifest.relative_to(root).as_posix(),
        _relative_ledger_path(root, ledger),
        context_relative,
        *(path.relative_to(root).as_posix() for path in evidence.values()),
        *fixture_artifact_paths,
    })
    draft = tmp_path / "task11-change-manifest-draft.json"
    _write_json(
        draft,
        {
            "schema_version": "guide-task11-change-manifest-v1",
            "plan_revision": candidate["plan_revision"],
            "candidate_manifest_sha256": sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            "candidate_readiness_sha256": sha256(
                candidate_readiness.read_bytes()
            ).hexdigest(),
            "ledger_path": _relative_ledger_path(root, ledger),
            "final_ledger_revision": initial_tip["revision"],
            "final_ledger_hash": initial_tip["revision_hash"],
            "bounded_attempt_id": "bounded-smoke-attempt-02",
            "attempt_context_path": context_relative,
            "bounded_artifact_paths": [context_relative],
            "fixture_artifact_paths": fixture_artifact_paths,
            "approved_paths": approved,
            "staged_diff_sha256": None,
            "finalized": False,
        },
    )
    attempt_ledger.compare_and_swap_ledger(
        ledger,
        expected_revision=0,
        mutate=lambda payload: payload,
    )
    subprocess.run(
        ["git", "add", "-A", "--", *approved],
        cwd=root,
        check=True,
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="ledger advanced",
    ):
        readiness.finalize_change_manifest(
            repo_root=root,
            draft_path=draft,
            candidate_manifest_path=candidate_manifest,
            candidate_readiness_path=candidate_readiness,
            expected_manifest_sha256=sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            ledger_path=ledger,
            output_path=root / "task11-change-manifest.json",
        )


def test_build_change_manifest_binds_passed_attempt_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, candidate_manifest = _candidate(tmp_path)
    candidate = json.loads(
        candidate_manifest.read_text(encoding="utf-8")
    )
    evidence = root / "evidence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    desktop_summary = root / "desktop" / "summary.json"
    mobile_summary = root / "mobile" / "summary.json"
    _write_indexed_fixture_summary(
        desktop_summary,
        viewport="desktop",
    )
    _write_indexed_fixture_summary(
        mobile_summary,
        viewport="mobile",
    )
    candidate_readiness = (
        candidate_manifest.parent
        / "task11-candidate-readiness.json"
    )
    _write_json(
        candidate_readiness,
        {
            "plan_revision": "task11-r1",
            "reviewed_candidate_manifest_sha256": sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            "protected_payload_sha256": (
                candidate["protected_payload_sha256"]
            ),
            "evidence_files": {
                "zero_api_summary": str(evidence),
                "desktop_summary": str(desktop_summary),
                "mobile_summary": str(mobile_summary),
            },
        },
    )
    ledger = root / "ledger.json"
    ledger.write_text("{}\n", encoding="utf-8")
    attempt_dir = root / "attempt"
    attempt_dir.mkdir()
    context = attempt_dir / "attempt-context.json"
    context.write_text("{}\n", encoding="utf-8")
    browser_dir = attempt_dir / "browser-desktop"
    browser_dir.mkdir()
    _write_json(
        browser_dir / "summary.json",
        {
            "schema_version": (
                "guide-mainline-contract-browser-audit-v1"
            ),
            "trajectory_set": "bounded",
            "viewport": "desktop",
            "passed": True,
            "turn_count": 9,
            "invalid_clarification_count": 0,
        },
    )
    output = root / "task11-change-manifest.json"

    monkeypatch.setattr(
        readiness,
        "verify_task11_readiness",
        lambda **_: json.loads(
            candidate_readiness.read_text(encoding="utf-8")
        ),
    )
    monkeypatch.setattr(
        readiness,
        "read_attempt_context",
        lambda *args, **kwargs: {
            "phase_attempt_ids": {
                "bounded": "bounded-smoke-attempt-02"
            },
            "output_directory": str(attempt_dir),
        },
        raising=False,
    )
    monkeypatch.setattr(
        readiness,
        "read_ledger",
        lambda _: {
            "revision": 17,
            "revision_chain": [{
                "revision": 17,
                "revision_hash": "a" * 64,
            }],
            "attempts": [{
                "attempt_id": "bounded-smoke-attempt-02",
                "result": "passed",
            }]
        },
    )
    monkeypatch.setattr(
        readiness,
        "ledger_anchor",
        lambda _: {
            "revision": 17,
            "revision_hash": "a" * 64,
        },
    )
    monkeypatch.setattr(
        readiness,
        "_validate_completed_bounded_evidence",
        lambda _: None,
    )
    attestation_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        readiness,
        "validate_runtime_bound_attempt_attestation",
        lambda **kwargs: attestation_calls.append(kwargs) or {},
        raising=False,
    )
    unmodified_path = "app/guide/unmodified.py"
    unmodified = {
        **candidate,
        "source_paths": sorted([
            *candidate["source_paths"],
            unmodified_path,
        ]),
        "protected_paths": sorted([
            *candidate["protected_paths"],
            unmodified_path,
        ]),
    }
    monkeypatch.setattr(
        readiness,
        "_validated_manifest",
        lambda _, **__: (unmodified, root),
    )

    result = readiness.build_change_manifest(
        candidate_manifest_path=candidate_manifest,
        candidate_readiness_path=candidate_readiness,
        attempt_context_path=context,
        expected_manifest_sha256=sha256(
            candidate_manifest.read_bytes()
        ).hexdigest(),
        ledger_path=ledger,
        output_path=output,
    )

    assert result["bounded_attempt_id"] == (
        "bounded-smoke-attempt-02"
    )
    assert result["ledger_path"] == "ledger.json"
    assert result["final_ledger_revision"] == 17
    assert result["final_ledger_hash"] == "a" * 64
    assert len(attestation_calls) == 1
    assert attestation_calls[0]["context_path"] == context
    assert attestation_calls[0]["require_browser_summary"] is True
    assert (
        "attempt/browser-desktop/summary.json"
        in result["bounded_artifact_paths"]
    )
    assert "app/guide/example.py" in result["approved_paths"]
    assert "evidence.json" in result["approved_paths"]
    assert (
        "desktop/fixture-fit-recommendation/screenshot.png"
        in result["approved_paths"]
    )
    assert (
        "mobile/fixture-image-identity/stream.sse"
        in result["approved_paths"]
    )
    assert result["fixture_artifact_paths"] == sorted({
        *(
            path.relative_to(root).as_posix()
            for path in desktop_summary.parent.rglob("*")
            if path.is_file() and path != desktop_summary
        ),
        *(
            path.relative_to(root).as_posix()
            for path in mobile_summary.parent.rglob("*")
            if path.is_file() and path != mobile_summary
        ),
    })
    assert unmodified_path not in result["approved_paths"]
    assert result["staged_diff_sha256"] is None
    assert result["finalized"] is False


def test_build_change_manifest_rejects_false_bounded_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, candidate_manifest = _candidate(tmp_path)
    candidate = json.loads(
        candidate_manifest.read_text(encoding="utf-8")
    )
    evidence = root / "evidence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    candidate_readiness = (
        candidate_manifest.parent
        / "task11-candidate-readiness.json"
    )
    _write_json(
        candidate_readiness,
        {
            "plan_revision": "task11-r1",
            "reviewed_candidate_manifest_sha256": sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            "protected_payload_sha256": (
                candidate["protected_payload_sha256"]
            ),
            "evidence_files": {"zero_api_summary": str(evidence)},
        },
    )
    ledger = root / "ledger.json"
    ledger.write_text("{}\n", encoding="utf-8")
    attempt_dir = root / "attempt"
    browser_dir = attempt_dir / "browser-desktop"
    browser_dir.mkdir(parents=True)
    context = attempt_dir / "attempt-context.json"
    context.write_text("{}\n", encoding="utf-8")
    _write_json(
        browser_dir / "summary.json",
        {
            "schema_version": (
                "guide-mainline-contract-browser-audit-v1"
            ),
            "trajectory_set": "bounded",
            "viewport": "desktop",
            "passed": False,
            "turn_count": 0,
            "invalid_clarification_count": 0,
        },
    )
    monkeypatch.setattr(
        readiness,
        "verify_task11_readiness",
        lambda **_: json.loads(
            candidate_readiness.read_text(encoding="utf-8")
        ),
    )
    monkeypatch.setattr(
        readiness,
        "read_attempt_context",
        lambda *args, **kwargs: {
            "phase_attempt_ids": {
                "bounded": "bounded-smoke-attempt-02"
            },
            "output_directory": str(attempt_dir),
        },
    )
    monkeypatch.setattr(
        readiness,
        "read_ledger",
        lambda _: {
            "revision": 17,
            "revision_chain": [{
                "revision": 17,
                "revision_hash": "a" * 64,
            }],
            "attempts": [{
                "attempt_id": "bounded-smoke-attempt-02",
                "result": "passed",
            }]
        },
    )
    monkeypatch.setattr(
        readiness,
        "ledger_anchor",
        lambda _: {
            "revision": 17,
            "revision_hash": "a" * 64,
        },
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="bounded browser evidence is invalid",
    ):
        readiness.build_change_manifest(
            candidate_manifest_path=candidate_manifest,
            candidate_readiness_path=candidate_readiness,
            attempt_context_path=context,
            expected_manifest_sha256=sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            ledger_path=ledger,
            output_path=root / "change.json",
        )


def _committed_task11_release(
    tmp_path: Path,
    *,
    self_authored_readiness: bool = False,
    omitted_fixture_artifact: str | None = None,
) -> tuple[Path, Path, Path, str]:
    root, candidate_manifest = _candidate(tmp_path)
    candidate = json.loads(
        candidate_manifest.read_text(encoding="utf-8")
    )
    evidence, ledger = _evidence(root, candidate_manifest)
    ledger_payload = attempt_ledger.read_ledger(ledger)
    ledger_tip = attempt_ledger.ledger_anchor(ledger_payload)
    candidate_readiness = (
        candidate_manifest.parent
        / "task11-candidate-readiness.json"
    )
    if self_authored_readiness:
        independent_audit = evidence["independent_audit"]
        _write_json(candidate_readiness, {
            "schema_version": "guide-task11-readiness-v1",
            "plan_revision": candidate["plan_revision"],
                "reviewed_candidate_manifest_sha256": sha256(
                    candidate_manifest.read_bytes()
                ).hexdigest(),
            "candidate_head": candidate["candidate_head"],
            "candidate_payload_sha256": (
                candidate["candidate_payload_sha256"]
            ),
            "protected_payload_sha256": (
                candidate["protected_payload_sha256"]
            ),
            "step_0_passed": True,
            "step_0_5_passed": True,
            "step_4_5_passed": True,
            "step_4_6_passed": True,
            "affected_zero_api_passed": True,
            "single_path_architecture_passed": True,
            "production_path_matrix_passed": True,
            "desktop_fixture_passed": True,
            "mobile_fixture_passed": True,
            "invalid_clarification_count": 0,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "runtime_outbound_network_attempt_count": 0,
            "runtime_process_tree_non_loopback_attempt_count": 0,
            "fixture_browser_non_loopback_attempt_count": 0,
            "fixture_process_tree_non_loopback_attempt_count": 0,
            "ledger_anchor_revision": ledger_tip["revision"],
            "ledger_anchor_hash": ledger_tip["revision_hash"],
            "circuit_state": "closed",
            "evidence_files": {
                "candidate_manifest": str(candidate_manifest.resolve()),
                "independent_audit": str(independent_audit.resolve()),
            },
            "evidence_sha256": {
                "candidate_manifest": sha256(
                    candidate_manifest.read_bytes()
                ).hexdigest(),
                "independent_audit": sha256(
                    independent_audit.read_bytes()
                ).hexdigest(),
            },
        })
    else:
        _derive_or_seal_candidate_readiness(
            manifest_path=candidate_manifest,
                expected_manifest_sha256=sha256(
                    candidate_manifest.read_bytes()
                ).hexdigest(),
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            runtime_network_report_path=evidence[
                "runtime_network_report"
            ],
            single_path_architecture_path=evidence[
                "single_path_architecture"
            ],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=evidence[
                "production_path_summary"
            ],
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
            output_path=candidate_readiness,
        )
    release_plans = tuple(
        root / path
        for path in readiness._RELEASE_PLAN_PATHS
    )
    for release_plan in release_plans:
        release_plan.write_text(
            "# Release plan\n",
            encoding="utf-8",
        )
    context_relative = "bounded-attempt/attempt-context.json"
    context = root / context_relative
    context.parent.mkdir(parents=True, exist_ok=True)
    context.write_text("{}\n", encoding="utf-8")
    change_manifest = root / "task11-change-manifest.json"
    fixture_artifact_paths = sorted({
        path.relative_to(root).as_posix()
        for summary in (
            evidence["desktop_summary"],
            evidence["mobile_summary"],
        )
        for path in summary.parent.rglob("*")
        if (
            path.is_file()
            and path != summary
            and (
                omitted_fixture_artifact is None
                or (
                    path.relative_to(root).as_posix()
                    != omitted_fixture_artifact
                    and not path.relative_to(root).as_posix().endswith(
                        omitted_fixture_artifact
                    )
                )
            )
        )
    })
    approved = sorted({
        *candidate["change_paths"],
        candidate_manifest.relative_to(root).as_posix(),
        candidate_readiness.relative_to(root).as_posix(),
        _relative_ledger_path(root, ledger),
        context_relative,
        *(
            path.relative_to(root).as_posix()
            for path in evidence.values()
        ),
        *(
            fixture_artifact_paths
        ),
    })
    subprocess.run(
        ["git", "add", "-A", "--", *approved],
        cwd=root,
        check=True,
    )
    staged_diff = subprocess.run(
        ["git", "diff", "--cached", "--binary", "--", *approved],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    _write_json(
        change_manifest,
        {
            "schema_version": "guide-task11-change-manifest-v1",
            "plan_revision": candidate["plan_revision"],
            "candidate_manifest_sha256": sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
            "candidate_readiness_sha256": sha256(
                candidate_readiness.read_bytes()
            ).hexdigest(),
            "ledger_path": _relative_ledger_path(root, ledger),
            "final_ledger_revision": ledger_tip["revision"],
            "final_ledger_hash": ledger_tip["revision_hash"],
            "bounded_attempt_id": "bounded-smoke-attempt-02",
            "attempt_context_path": context_relative,
            "bounded_artifact_paths": [context_relative],
            "approved_paths": approved,
            "fixture_artifact_paths": fixture_artifact_paths,
            "staged_diff_sha256": sha256(staged_diff).hexdigest(),
            "finalized": True,
        },
    )
    subprocess.run(
        ["git", "add", "--", "task11-change-manifest.json"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "task11"],
        cwd=root,
        check=True,
    )
    task11_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return root, change_manifest, candidate_readiness, task11_commit


def _reviewed_manifest_sha256_from_readiness(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload["reviewed_candidate_manifest_sha256"])


def test_seal_commit_rejects_self_authored_candidate_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (
        root,
        change_manifest,
        candidate_readiness,
        task11_commit,
    ) = _committed_task11_release(
        tmp_path,
        self_authored_readiness=True,
    )
    _stub_bounded_attempt_validation(monkeypatch, root=root)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="readiness evidence binding",
    ):
        readiness.seal_task11_commit(
            repo_root=root,
            change_manifest_path=change_manifest,
            candidate_readiness_path=candidate_readiness,
            release_readiness_path=root / "release-readiness.json",
            task11_commit=task11_commit,
            expected_manifest_sha256=(
                _reviewed_manifest_sha256_from_readiness(
                    candidate_readiness
                )
            ),
        )


def test_seal_commit_rejects_uncommitted_fixture_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        readiness,
        "_verify_fixture_summary_bundles",
        readiness._verify_fixture_artifact_index,
    )
    omitted = (
        "runtime-browser-evidence/fixture-browser-desktop/"
        "fixture-fit-recommendation/screenshot.png"
    )
    (
        root,
        change_manifest,
        candidate_readiness,
        task11_commit,
    ) = _committed_task11_release(
        tmp_path,
        omitted_fixture_artifact=omitted,
    )
    _stub_bounded_attempt_validation(monkeypatch, root=root)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="fixture artifact",
    ):
        readiness.seal_task11_commit(
            repo_root=root,
            change_manifest_path=change_manifest,
            candidate_readiness_path=candidate_readiness,
            release_readiness_path=root / "release-readiness.json",
            task11_commit=task11_commit,
            expected_manifest_sha256=(
                _reviewed_manifest_sha256_from_readiness(
                    candidate_readiness
                )
            ),
        )


def test_seal_commit_writes_and_verifies_release_execution_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        readiness,
        "_verify_fixture_summary_bundles",
        readiness._verify_fixture_artifact_index,
    )
    (
        root,
        change_manifest,
        candidate_readiness,
        task11_commit,
    ) = _committed_task11_release(tmp_path)
    _stub_bounded_attempt_validation(monkeypatch, root=root)
    output = root / "release-readiness.json"

    sealed = readiness.seal_task11_commit(
        repo_root=root,
        change_manifest_path=change_manifest,
        candidate_readiness_path=candidate_readiness,
        release_readiness_path=output,
        task11_commit=task11_commit,
        expected_manifest_sha256=(
            _reviewed_manifest_sha256_from_readiness(
                candidate_readiness
            )
        ),
    )

    assert sealed["schema_version"] == (
        "guide-task11-release-readiness-v1"
    )
    assert sealed["task11_commit"] == task11_commit
    assert sealed["candidate_head"] == task11_commit
    assert sealed["task11_parent_commit"]
    assert sealed["release_execution_paths"]
    assert sealed["release_execution_tree_sha256"]
    assert readiness.verify_release_readiness(
        readiness_path=output,
        require_head=task11_commit,
        expected_manifest_sha256=(
            _reviewed_manifest_sha256_from_readiness(
                candidate_readiness
            )
        ),
    ) == sealed

    late = root / "tools/late_release_tool.py"
    late.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(
        readiness.Task11ReadinessError,
        match="execution tree",
    ):
        readiness.verify_release_readiness(
            readiness_path=output,
            require_head=task11_commit,
            expected_manifest_sha256=(
                _reviewed_manifest_sha256_from_readiness(
                    candidate_readiness
                )
            ),
        )


def test_release_readiness_rejects_post_seal_fixture_artifact_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        readiness,
        "_verify_fixture_summary_bundles",
        readiness._verify_fixture_artifact_index,
    )
    (
        root,
        change_manifest,
        candidate_readiness,
        task11_commit,
    ) = _committed_task11_release(tmp_path)
    _stub_bounded_attempt_validation(monkeypatch, root=root)
    output = root / "release-readiness.json"
    readiness.seal_task11_commit(
        repo_root=root,
        change_manifest_path=change_manifest,
        candidate_readiness_path=candidate_readiness,
        release_readiness_path=output,
        task11_commit=task11_commit,
        expected_manifest_sha256=(
            _reviewed_manifest_sha256_from_readiness(
                candidate_readiness
            )
        ),
    )
    fixture_artifact_paths = (
        readiness._readiness_fixture_artifact_paths(
            root=root,
            readiness=json.loads(
                candidate_readiness.read_text(encoding="utf-8")
            ),
        )
    )
    screenshot = root / next(
        path
        for path in fixture_artifact_paths
        if path.endswith(
            "fixture-browser-desktop/"
            "fixture-fit-recommendation/screenshot.png"
        )
    )
    screenshot.write_bytes(screenshot.read_bytes() + b"drift")

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="fixture artifact index drift",
    ):
        readiness.verify_release_readiness(
            readiness_path=output,
            require_head=task11_commit,
            expected_manifest_sha256=(
                _reviewed_manifest_sha256_from_readiness(
                    candidate_readiness
                )
            ),
        )


def test_release_readiness_rederives_candidate_completion_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        readiness,
        "_verify_fixture_summary_bundles",
        readiness._verify_fixture_artifact_index,
    )
    (
        root,
        change_manifest,
        candidate_readiness,
        task11_commit,
    ) = _committed_task11_release(tmp_path)
    _stub_bounded_attempt_validation(monkeypatch, root=root)
    output = root / "release-readiness.json"
    readiness.seal_task11_commit(
        repo_root=root,
        change_manifest_path=change_manifest,
        candidate_readiness_path=candidate_readiness,
        release_readiness_path=output,
        task11_commit=task11_commit,
        expected_manifest_sha256=(
            _reviewed_manifest_sha256_from_readiness(
                candidate_readiness
            )
        ),
    )
    forged = json.loads(output.read_text(encoding="utf-8"))
    forged["provider_call_count"] = 99
    _write_json(output, forged)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="candidate readiness derivation",
    ):
        readiness.verify_release_readiness(
            readiness_path=output,
            require_head=task11_commit,
            expected_manifest_sha256=(
                _reviewed_manifest_sha256_from_readiness(
                    candidate_readiness
                )
            ),
        )


def test_release_execution_inventory_includes_backend_runtime_data(
    tmp_path: Path,
) -> None:
    assert set(TASK12_RUNTIME_DATA_PATHS) <= set(
        readiness._TASK12_EXECUTION_PATHS
    )
    root = tmp_path / "repo"
    for relative in (
        *readiness._RELEASE_PLAN_PATHS,
        *TASK12_RUNTIME_DATA_PATHS,
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n", encoding="utf-8")
    revision = _initialize_git_repo(root)

    paths, hashes = readiness._release_execution_inventory(
        root,
        revision=revision,
    )

    assert set(TASK12_RUNTIME_DATA_PATHS) <= set(paths)
    assert set(TASK12_RUNTIME_DATA_PATHS) <= set(hashes)
