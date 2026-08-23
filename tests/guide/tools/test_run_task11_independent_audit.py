from __future__ import annotations

from hashlib import sha256
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
from typing import Callable

import pytest


MODULE = "tools.guide_gates.run_task11_independent_audit"
HEAD = "a" * 64
FIXTURE_TURNS = (
    "fixture-explore-recommendation",
    "fixture-fit-recommendation",
    "fixture-product-knowledge",
    "fixture-comparison",
    "fixture-image-identity",
    "fixture-image-fit-recommendation",
    "fixture-multi-image-comparison",
)


def _audit_module():
    return importlib.import_module(MODULE)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _payload_hash(root: Path, paths: list[str]) -> str:
    digest = sha256()
    for relative in sorted(paths):
        encoded_path = relative.encode("utf-8")
        content = (root / relative).read_bytes()
        digest.update(str(len(encoded_path)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded_path)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return digest.hexdigest()


def _browser_summary(
    *,
    root: Path,
    viewport: str,
    challenge_digest: str,
) -> Path:
    directory = root / f"fixture-browser-{viewport}"
    directory.mkdir(parents=True)
    sandbox_path = directory / "sandbox-audit.json"
    _write_json(
        sandbox_path,
        {
            "passed": True,
            "process_tree_non_loopback_attempt_count": 0,
            "attempts": [],
        },
    )
    for turn_id in FIXTURE_TURNS:
        turn_dir = directory / turn_id
        turn_dir.mkdir()
        _write_json(
            turn_dir / "request.json",
            {"turn_id": turn_id, "request_id": f"{viewport}-{turn_id}"},
        )
        contract = {
            "terminal_kind": "presentation",
            "mode": "recommendation",
        }
        _write_json(turn_dir / "presentation-contract.json", contract)
        (turn_dir / "stream.sse").write_text(
            "event: presentation_contract\n"
            f"data: {json.dumps(contract, sort_keys=True)}\n\n"
            "event: end\n"
            'data: {"ok": true}\n\n',
            encoding="utf-8",
        )
        _write_json(
            turn_dir / "terminal-dom.json",
            {
                "request_id": f"{viewport}-{turn_id}",
                "presentation_mode": "recommendation",
            },
        )
        (turn_dir / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        _write_json(turn_dir / "console.json", [])
        _write_json(turn_dir / "network.json", [])
        _write_json(
            turn_dir / "sandbox-audit.json",
            {
                "passed": True,
                "process_tree_non_loopback_attempt_count": 0,
                "attempts": [],
            },
        )
    indexed = {
        path.relative_to(directory).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    summary = directory / "summary.json"
    _write_json(
        summary,
        {
            "schema_version": "guide-mainline-contract-browser-audit-v1",
            "trajectory_set": "fixture",
            "viewport": viewport,
            "passed": True,
            "turn_count": len(FIXTURE_TURNS),
            "invalid_clarification_count": 0,
            "runtime_identity_sha256": "1" * 64,
            "consumed_health_challenge_sha256": challenge_digest,
            "sandbox_identity": "macos-sandbox-exec-loopback-only",
            "sandbox_audit_sha256": sha256(
                sandbox_path.read_bytes()
            ).hexdigest(),
            "browser_request_count": len(FIXTURE_TURNS),
            "process_tree_non_loopback_attempt_count": 0,
            "browser_observed_non_loopback_attempt_count": 0,
            "turns": [
                {"turn_id": turn_id, "directory": turn_id}
                for turn_id in FIXTURE_TURNS
            ],
            "artifact_sha256": indexed,
        },
    )
    return summary


def _production_summary() -> dict[str, object]:
    traces: list[dict[str, object]] = []
    required_edges = [f"edge-{index:02d}" for index in range(40)]
    for index in range(176):
        semantic = index < 128
        state_index = index - 128
        partition = (
            "semantic"
            if semantic
            else ("bounded" if state_index < 9 else "state")
        )
        digest = sha256(f"decision-{index}".encode()).hexdigest()
        envelope_digest = sha256(f"envelope-{index}".encode()).hexdigest()
        trajectory = (
            f"semantic-{index:03d}"
            if semantic
            else f"state-{state_index // 4:02d}"
        )
        traces.append(
            {
                "turn_id": f"turn-{index:03d}",
                "trajectory_id": trajectory,
                "partition": partition,
                "translation_injection_count": 1,
                "structured_understanding_injection_count": 0,
                "compiler_call_count": 1,
                "direct_router_bypass_count": 0,
                "legacy_entrypoint_count": 0,
                "router_call_count": 1,
                "route_decision_digest": digest,
                "selected_processor_decision_digest": digest,
                "result_decision_digest": digest,
                "sse_decision_digest": digest,
                "validated_sse_sha256": envelope_digest,
                "emitted_sse_sha256": envelope_digest,
                "selected_processor": "recommendation",
                "processor_invocation_counts": {
                    "recommendation": 1,
                    "comparison": 0,
                },
                "decision_identity_violation_count": 0,
                "execution_result_count": 1,
                "reducer_call_count": 1,
                "state_save_count": 1,
                "processor_state_write_count": 0,
                "event_state_projection_count": 0,
                "provider_call_count": 0,
                "outbound_network_attempt_count": 0,
                "loaded_version": state_index % 4 if not semantic else 0,
                "committed_version": (
                    state_index % 4 + 1 if not semantic else 1
                ),
                "expected_state_edge": "none->recommendation",
                "observed_state_edge": "none->recommendation",
                "terminal_event": "end",
                "bounded": partition == "bounded",
                "semantic_equivalence_passed": True,
                "accepted": True,
                "coverage_edges": (
                    []
                    if semantic
                    else [required_edges[state_index % 40]]
                ),
            }
        )
    zero_fields = {
        "actual_equivalence_failure_count": 0,
        "bounded_failure_count": 0,
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
    }
    return {
        "schema_version": "guide-task11-production-path-summary-v1",
        "passed": True,
        "expected_contract_case_count": 128,
        "actual_equivalence_case_count": 128,
        "trajectory_count": 12,
        "stateful_turn_count": 48,
        "turn_count": 176,
        "state_edge_count": 40,
        "required_state_edge_count": 40,
        "required_state_edges": required_edges,
        "bounded_turn_count": 9,
        "translation_injection_count": 176,
        "turn_traces": traces,
        **zero_fields,
    }


def _bundle(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "repo"
    source = "app/guide/service.py"
    test = "tests/guide/test_service.py"
    tool = "tools/guide_gates/local_gate.py"
    plan = "docs/superpowers/plans/task11.md"
    fixture = "tests/fixtures/guide/task11.json"
    deleted = "app/guide/legacy_bridge.py"
    initial = {
        source: "def execute():\n    return 'base'\n",
        test: "def test_base():\n    assert True\n",
        tool: "VALUE = 'base'\n",
        plan: "Plan revision: old\n",
        fixture: '{"version": 0}\n',
        deleted: "def legacy_dispatch():\n    return 'legacy'\n",
    }
    for relative, content in initial.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    candidate_head = _git(root, "rev-parse", "HEAD")
    deleted_bytes = subprocess.run(
        ["git", "show", f"{candidate_head}:{deleted}"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout

    updates = {
        source: "def execute():\n    return 'single-path'\n",
        test: "def test_single_path():\n    assert True\n",
        tool: "VALUE = 'r5'\n",
        plan: "Plan revision: 2026-08-23-task11-r5\n",
        fixture: '{"version": 1}\n',
    }
    for relative, content in updates.items():
        (root / relative).write_text(content, encoding="utf-8")
    (root / deleted).unlink()

    epoch = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "repair-epoch-08"
    )
    epoch.mkdir(parents=True)
    protected = sorted([source, test, tool, plan, fixture])
    payload_hash = _payload_hash(root, protected)
    manifest_path = epoch / "task11-candidate-manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": "guide-task11-candidate-manifest-v1",
            "plan_revision": "2026-08-23-task11-r5",
            "candidate_head": candidate_head,
            "source_paths": [source],
            "test_paths": [test],
            "tool_paths": [tool],
            "plan_paths": [plan],
            "fixture_paths": [fixture],
            "deleted_paths": [deleted],
            "deleted_base_blob_sha256_by_path": {
                deleted: sha256(deleted_bytes).hexdigest(),
            },
            "mutable_evidence_paths": [
                "docs/audits/final-release/mainline-contract-closure/"
                "smoke-attempt-ledger.json"
            ],
            "excluded_paths": [
                ".tmp-*",
                "docs/audits/final-release/mainline-contract-closure/",
            ],
            "protected_paths": protected,
            "change_paths": sorted([*protected, deleted]),
            "candidate_payload_sha256": payload_hash,
            "protected_payload_sha256": payload_hash,
        },
    )

    semantic = epoch / "task11-semantic-matrix-summary.json"
    _write_json(
        semantic,
        {
            "schema_version": "guide-task11-semantic-summary-v1",
            "matrix_kind": "expected_contract",
            "passed": True,
            "case_count": 128,
            "fit_count": 2,
            "explore_count": 30,
            "image_fit_count": 1,
            "recommendation_outcome_contract_gap_count": 0,
            "cross_parent_basis_count": 0,
        },
    )
    network = epoch / "task11-zero-api-network.json"
    _write_json(
        network,
        {
            "schema_version": "guide-zero-api-network-report-v1",
            "guard_active": True,
            "passed": True,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "attempts": [],
        },
    )
    zero_api = epoch / "task11-zero-api-summary.json"
    _write_json(
        zero_api,
        {
            "schema_version": "guide-task11-zero-api-summary-v1",
            "passed": True,
            "guard_active": True,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "candidate_manifest_sha256": sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "protected_payload_sha256": payload_hash,
            "network_report_sha256": sha256(
                network.read_bytes()
            ).hexdigest(),
            "commands": [
                {
                    "argv": ["python", "-m", "pytest", test],
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                }
            ],
        },
    )
    architecture = epoch / "task11-single-path-architecture.json"
    _write_json(
        architecture,
        {
            "schema_version": "guide-task11-single-path-architecture-v1",
            "passed": True,
            "inspected_module_count": 1,
            "inspected_modules": ["app.guide.service"],
            "violation_count": 0,
            "violations": [],
            "forbidden_symbol_count": 0,
        },
    )
    test_path = epoch / "task11-test-path-audit.json"
    _write_json(
        test_path,
        {
            "schema_version": "guide-task11-test-path-audit-v1",
            "passed": True,
            "production_path_gate_count": 1,
            "invalid_production_path_claim_count": 0,
            "unprotected_fixture_dependency_count": 0,
            "fixture_dependencies": [fixture],
            "gates": [
                {
                    "gate": "task11-production-path-matrix",
                    "claimed_scope": "production_path_from_turn_meaning",
                    "real_entrypoint": "/api/v1/chat/stream",
                    "layers_executed": [
                        "translation",
                        "compiler",
                        "router",
                        "processor",
                        "reducer",
                        "sqlite",
                        "sse",
                    ],
                    "layers_bypassed": [],
                    "semantic_injection_type": "turn_meaning_provider",
                    "test_files": [test],
                    "fixture_files": [fixture],
                    "case_count": 176,
                    "trajectory_count": 12,
                    "turn_count": 176,
                    "state_edge_count": 40,
                }
            ],
        },
    )
    runtime_network = epoch / "task11-zero-api-runtime-network.json"
    _write_json(
        runtime_network,
        {
            "schema_version": "guide-zero-api-runtime-network-report-v1",
            "guard_active": True,
            "passed": True,
            "runtime_started": True,
            "ready_identity_written": True,
            "shutdown_finalized": True,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "process_creation_attempt_count": 0,
            "runtime_process_tree_non_loopback_attempt_count": 0,
            "attempts": [],
            "process_creation_attempts": [],
            "candidate_manifest_sha256": sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "runtime_identity_sha256": "1" * 64,
        },
    )
    production = epoch / "task11-production-path-summary.json"
    _write_json(production, _production_summary())
    desktop = _browser_summary(
        root=epoch,
        viewport="desktop",
        challenge_digest="2" * 64,
    )
    mobile = _browser_summary(
        root=epoch,
        viewport="mobile",
        challenge_digest="3" * 64,
    )
    return {
        "repo_root": root,
        "manifest": manifest_path,
        "semantic_summary": semantic,
        "zero_api_summary": zero_api,
        "single_path_architecture": architecture,
        "test_path_audit": test_path,
        "network_report": network,
        "runtime_network_report": runtime_network,
        "production_path_summary": production,
        "desktop_summary": desktop,
        "mobile_summary": mobile,
        "output": epoch / "task11-independent-audit.json",
    }


def _run(bundle: dict[str, Path]) -> dict[str, object]:
    module = _audit_module()
    return module.run_independent_audit(
        repo_root=bundle["repo_root"],
        manifest_path=bundle["manifest"],
        semantic_summary_path=bundle["semantic_summary"],
        zero_api_summary_path=bundle["zero_api_summary"],
        single_path_architecture_path=(
            bundle["single_path_architecture"]
        ),
        test_path_audit_path=bundle["test_path_audit"],
        network_report_path=bundle["network_report"],
        runtime_network_report_path=bundle["runtime_network_report"],
        production_path_summary_path=bundle["production_path_summary"],
        desktop_summary_path=bundle["desktop_summary"],
        mobile_summary_path=bundle["mobile_summary"],
        output_path=bundle["output"],
    )


def test_independent_audit_derives_hashes_and_writes_output_exclusively(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)

    report = _run(bundle)

    assert report["schema_version"] == (
        "guide-task11-independent-audit-v1"
    )
    assert report["passed"] is True
    assert report["plan_revision"] == "2026-08-23-task11-r5"
    assert report["repair_epoch"] == 8
    assert report["finding_count"] == 0
    assert report["p0_finding_count"] == 0
    assert report["p1_finding_count"] == 0
    assert report["candidate_manifest_sha256"] == sha256(
        bundle["manifest"].read_bytes()
    ).hexdigest()
    assert len(report["production_diff_sha256"]) == 64
    assert report["reviewed_evidence_sha256"] == {
        "candidate_manifest": sha256(
            bundle["manifest"].read_bytes()
        ).hexdigest(),
        **{
            role: sha256(bundle[role].read_bytes()).hexdigest()
            for role in (
                "semantic_summary",
                "zero_api_summary",
                "single_path_architecture",
                "test_path_audit",
                "network_report",
                "runtime_network_report",
                "production_path_summary",
                "desktop_summary",
                "mobile_summary",
            )
        },
    }
    assert json.loads(
        bundle["output"].read_text(encoding="utf-8")
    ) == report
    original = bundle["output"].read_bytes()
    with pytest.raises(FileExistsError, match="already exists"):
        _run(bundle)
    assert bundle["output"].read_bytes() == original
    assert not tuple(bundle["output"].parent.glob(".*.tmp-*"))


@pytest.mark.parametrize(
    "missing_role",
    (
        "semantic_summary",
        "zero_api_summary",
        "single_path_architecture",
        "test_path_audit",
        "network_report",
        "runtime_network_report",
        "production_path_summary",
        "desktop_summary",
        "mobile_summary",
    ),
)
def test_independent_audit_rejects_each_missing_primary_input(
    tmp_path: Path,
    missing_role: str,
) -> None:
    bundle = _bundle(tmp_path)
    bundle[missing_role].unlink()

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="missing",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_rejects_stale_nested_evidence_hash(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    network = json.loads(
        bundle["network_report"].read_text(encoding="utf-8")
    )
    network["measurement_nonce"] = "tampered-after-zero-api-summary"
    _write_json(bundle["network_report"], network)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="network report hash",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_rejects_manifest_bound_production_bridge(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    source = bundle["repo_root"] / "app/guide/service.py"
    source.write_text(
        "from tests.guide.semantic_test_port import compile_understanding\n"
        "\n"
        "def execute():\n"
        "    return compile_understanding()\n",
        encoding="utf-8",
    )
    manifest = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    digest = _payload_hash(
        bundle["repo_root"],
        manifest["protected_paths"],
    )
    manifest["candidate_payload_sha256"] = digest
    manifest["protected_payload_sha256"] = digest
    _write_json(bundle["manifest"], manifest)
    zero_api = json.loads(
        bundle["zero_api_summary"].read_text(encoding="utf-8")
    )
    zero_api["candidate_manifest_sha256"] = sha256(
        bundle["manifest"].read_bytes()
    ).hexdigest()
    zero_api["protected_payload_sha256"] = digest
    _write_json(bundle["zero_api_summary"], zero_api)
    runtime_network = json.loads(
        bundle["runtime_network_report"].read_text(encoding="utf-8")
    )
    runtime_network["candidate_manifest_sha256"] = sha256(
        bundle["manifest"].read_bytes()
    ).hexdigest()
    _write_json(bundle["runtime_network_report"], runtime_network)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="production bridge",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_source_has_no_gate_implementation_imports() -> None:
    spec = importlib.util.find_spec(MODULE)
    assert spec is not None and spec.origin is not None
    source = Path(spec.origin).read_text(encoding="utf-8")

    forbidden = (
        "build_task11_readiness",
        "check_single_path_architecture",
        "run_task11_production_path_matrix",
    )
    assert all(
        f"import {module_name}" not in source
        and f"from tools.guide_gates.{module_name}" not in source
        for module_name in forbidden
    )
