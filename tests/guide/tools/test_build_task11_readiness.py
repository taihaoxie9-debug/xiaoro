from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.guide_gates import attempt_ledger
from tools.guide_gates import build_task11_readiness as readiness


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _plan(path: Path) -> None:
    path.write_text(
        """
# Plan

Plan revision: task11-r1

### Task 11: Close

**Files:**
- Modify: `app/guide/example.py`
- Test: `tests/guide/test_example.py`
- Create: `tests/fixtures/guide/example.json`
- Create: `tools/guide_gates/example.py`
- Delete: `tools/guide_gates/legacy.py`
- Modify: `docs/superpowers/plans/plan.md`
- Generate: `docs/audits/generated.json`

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
    manifest = root / "candidate.json"
    readiness.build_candidate_manifest(
        repo_root=root,
        plan_path=plan,
        output_path=manifest,
        candidate_head="a" * 40,
        changed_paths=(
            "app/guide/example.py",
            "tests/guide/test_example.py",
            "tools/guide_gates/example.py",
            "tools/guide_gates/legacy.py",
            "docs/superpowers/plans/plan.md",
        ),
    )
    return root, manifest


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


def _evidence(
    root: Path,
    manifest_path: Path,
) -> tuple[dict[str, Path], Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = {
        "semantic_summary": root / "semantic.json",
        "zero_api_summary": root / "zero-api.json",
        "network_report": root / "zero-api-network.json",
        "test_path_audit": root / "test-path-audit.json",
        "production_path_summary": root / "production-path.json",
        "independent_audit": root / "independent.json",
        "desktop_summary": root / "desktop.json",
        "mobile_summary": root / "mobile.json",
    }
    _write_json(
        paths["semantic_summary"],
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
    commands = readiness._zero_api_commands(
        manifest,
        python_executable=sys.executable,
    )
    _write_json(
        paths["network_report"],
        {
            "schema_version": "guide-zero-api-network-report-v1",
            "guard_active": True,
            "passed": True,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "attempts": [],
        },
    )
    _write_json(
        paths["zero_api_summary"],
        {
            "schema_version": "guide-task11-zero-api-summary-v1",
            "passed": True,
            "guard_active": True,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
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
                    "claimed_scope": "production_path",
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
                    "test_files": [
                        "tests/guide/tools/"
                        "test_task11_production_path_matrix.py"
                    ],
                    "fixture_files": [
                        "tests/fixtures/guide/example.json"
                    ],
                    "case_count": 176,
                    "trajectory_count": 12,
                    "turn_count": 176,
                    "state_edge_count": 40,
                }
            ],
        },
    )
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
            "result_decision_digest": "a" * 64,
            "decision_identity_violation_count": 0,
            "execution_result_count": 1,
            "reducer_call_count": 1,
            "state_save_count": 1,
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
            "coverage_edges": [],
            "actual_processor": "recommendation",
            "actual_intent": "recommend",
            "card_ids": [],
            "event_names": ["start", "end"],
        }
        for index in range(176)
    ]
    _write_json(
        paths["production_path_summary"],
        {
            "schema_version": (
                "guide-task11-production-path-summary-v1"
            ),
            "passed": True,
            "expected_contract_case_count": 128,
            "actual_equivalence_case_count": 128,
            "actual_equivalence_failure_count": 0,
            "trajectory_count": 12,
            "stateful_turn_count": 48,
            "turn_count": 176,
            "state_edge_count": 40,
            "required_state_edge_count": 40,
            "bounded_turn_count": 9,
            "bounded_failure_count": 0,
            "translation_injection_count": 176,
            "compiler_bypass_count": 0,
            "compiler_call_count_violation_count": 0,
            "structured_understanding_injection_count": 0,
            "direct_router_bypass_count": 0,
            "legacy_entrypoint_count": 0,
            "router_call_count_violation_count": 0,
            "decision_identity_violation_count": 0,
            "execution_result_count_violation_count": 0,
            "reducer_call_count_violation_count": 0,
            "processor_state_write_count": 0,
            "event_state_projection_count": 0,
            "state_save_count_violation_count": 0,
            "terminal_contract_failure_count": 0,
            "state_transition_failure_count": 0,
            "outbound_network_attempt_count": 0,
            "provider_call_count": 0,
            "turn_traces": production_traces,
        },
    )
    for viewport in ("desktop", "mobile"):
        _write_json(
            paths[f"{viewport}_summary"],
            {
                "schema_version": (
                    "guide-mainline-contract-browser-audit-v1"
                ),
                "trajectory_set": "fixture",
                "viewport": viewport,
                "turn_count": 7,
                "invalid_clarification_count": 0,
                "turns": [
                    {"turn_id": turn_id}
                    for turn_id in readiness._FIXTURE_TURN_IDS
                ],
                "passed": True,
            },
        )
    reviewed = {
        "candidate_manifest": manifest_path,
        "semantic_summary": paths["semantic_summary"],
        "zero_api_summary": paths["zero_api_summary"],
        "network_report": paths["network_report"],
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
            "first_failure_owner": "planned_gate",
            "repair_epoch": 0,
            "protected_payload_sha256": (
                manifest["protected_payload_sha256"]
            ),
            "reviewed_evidence_sha256": {
                role: sha256(path.read_bytes()).hexdigest()
                for role, path in reviewed.items()
            },
        },
    )
    ledger = root / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    return paths, ledger


def test_candidate_manifest_parses_task_files_and_hashes_raw_bytes(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["source_paths"] == ["app/guide/example.py"]
    assert manifest["test_paths"] == ["tests/guide/test_example.py"]
    assert manifest["fixture_paths"] == [
        "tests/fixtures/guide/example.json"
    ]
    assert manifest["tool_paths"] == ["tools/guide_gates/example.py"]
    assert manifest["deleted_paths"] == [
        "tools/guide_gates/legacy.py"
    ]
    assert manifest["plan_paths"] == [
        "docs/superpowers/plans/plan.md"
    ]
    assert manifest["protected_paths"] == sorted(
        [
            "app/guide/example.py",
            "tests/guide/test_example.py",
            "tests/fixtures/guide/example.json",
            "tools/guide_gates/example.py",
            "docs/superpowers/plans/plan.md",
        ]
    )
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


def test_candidate_manifest_rejects_relevant_changed_path_omission(
    tmp_path: Path,
) -> None:
    root, _ = _candidate(tmp_path)
    omitted = root / "app/guide/omitted.py"
    omitted.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="missing from Task 11 Files",
    ):
        readiness.build_candidate_manifest(
            repo_root=root,
            plan_path=root / "docs/superpowers/plans/plan.md",
            output_path=root / "rejected.json",
            candidate_head="a" * 40,
            changed_paths=(
                "app/guide/example.py",
                "app/guide/omitted.py",
            ),
        )


def test_candidate_manifest_rejects_static_runtime_path_omission(
    tmp_path: Path,
) -> None:
    assert readiness._is_relevant("app/static/guide-presentation.js")
    root, _ = _candidate(tmp_path)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="missing from Task 11 Files",
    ):
        readiness.build_candidate_manifest(
            repo_root=root,
            plan_path=root / "docs/superpowers/plans/plan.md",
            output_path=root / "rejected.json",
            candidate_head="a" * 40,
            changed_paths=(
                "app/guide/example.py",
                "app/static/guide-presentation.js",
            ),
        )


def test_candidate_manifest_excludes_historical_recording_plan(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)

    manifest = readiness.build_candidate_manifest(
        repo_root=root,
        plan_path=root / "docs/superpowers/plans/plan.md",
        output_path=manifest_path,
        candidate_head="a" * 40,
        changed_paths=(
            "app/guide/example.py",
            "tests/guide/test_example.py",
            "tools/guide_gates/example.py",
            "docs/superpowers/plans/plan.md",
            (
                "docs/superpowers/plans/"
                "2026-08-20-recording-ready-guide-path.md"
            ),
        ),
    )

    assert (
        "docs/superpowers/plans/"
        "2026-08-20-recording-ready-guide-path.md"
        not in manifest["protected_paths"]
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
            "CASES = 'tests/fixtures/guide/intent/"
            "task11_production_path_matrix_v1.jsonl'\n"
        ),
        encoding="utf-8",
    )
    frontend_test.write_text("VALUE = 1\n", encoding="utf-8")
    layer_test.write_text("VALUE = 1\n", encoding="utf-8")
    fixture.write_text("{}\n", encoding="utf-8")
    tool.write_text("VALUE = 1\n", encoding="utf-8")
    plan.write_text(
        """
# Plan

Plan revision: task11-r1

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
    manifest = readiness.build_candidate_manifest(
        repo_root=root,
        plan_path=plan,
        output_path=root / "candidate.json",
        candidate_head="a" * 40,
        changed_paths=(),
        test_path_audit_path=audit_path,
    )

    assert audit["passed"] is True
    assert audit["production_path_gate_count"] == 1
    assert {
        gate["gate"]: gate["claimed_scope"]
        for gate in audit["gates"]
    } == {
        "task11-production-path-matrix": "production_path",
        "test_run_mainline_contract_browser_audit": (
            "frontend_fixture"
        ),
        "test_router": "layer_contract",
    }
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


def test_readiness_is_derived_from_evidence_and_rejects_drift(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    output = root / "readiness.json"

    result = readiness.derive_candidate_readiness(
        manifest_path=manifest_path,
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
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
    assert result["production_path_matrix_passed"] is True
    assert result["provider_call_count"] == 0
    assert result["outbound_network_attempt_count"] == 0
    assert result["desktop_fixture_passed"] is True
    assert result["mobile_fixture_passed"] is True
    assert result["invalid_clarification_count"] == 0
    assert result["circuit_state"] == "closed"
    readiness.verify_saved_readiness(
        readiness_path=output,
        manifest_path=manifest_path,
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
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
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


def test_readiness_recomputes_pass_fields_instead_of_trusting_json(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    evidence, ledger = _evidence(root, manifest_path)
    semantic = json.loads(
        evidence["semantic_summary"].read_text(encoding="utf-8")
    )
    semantic["fit_count"] = 0
    _write_json(evidence["semantic_summary"], semantic)

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="semantic matrix evidence failed",
    ):
        readiness.derive_candidate_readiness(
            manifest_path=manifest_path,
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
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
        readiness.derive_candidate_readiness(
            manifest_path=manifest_path,
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
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
    assert result["fit_count"] > 0
    assert result["explore_count"] > 0
    assert result["image_fit_count"] > 0
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
        readiness.derive_candidate_readiness(
            manifest_path=manifest_path,
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
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
        readiness.derive_candidate_readiness(
            manifest_path=manifest_path,
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
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
        readiness.derive_candidate_readiness(
            manifest_path=manifest_path,
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
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
        readiness.derive_candidate_readiness(
            manifest_path=manifest_path,
            semantic_summary_path=evidence["semantic_summary"],
            zero_api_summary_path=evidence["zero_api_summary"],
            network_report_path=evidence["network_report"],
            test_path_audit_path=evidence["test_path_audit"],
            production_path_summary_path=(
                evidence["production_path_summary"]
            ),
            independent_audit_path=evidence["independent_audit"],
            desktop_summary_path=evidence["desktop_summary"],
            mobile_summary_path=evidence["mobile_summary"],
            ledger_path=ledger,
        )


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
                    "passed": True,
                    "provider_call_count": 0,
                    "outbound_network_attempt_count": 0,
                    "attempts": [],
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
        output_path=output,
        network_report_path=network_report,
        command_runner=run,
        python_executable="python",
    )

    assert result["passed"] is True
    assert result["provider_call_count"] == 0
    assert result["outbound_network_attempt_count"] == 0
    assert calls[0] == ("git", "diff", "--check")
    assert calls[1][:4] == (
        "python",
        "-m",
        "compileall",
        "-q",
    )
    assert calls[2][-1] == "tests/guide/test_example.py"
    assert calls[2][4:6] == (
        "-p",
        "tools.guide_gates.zero_api_network_guard",
    )
    assert "docs/superpowers/plans/plan.md" not in calls[2]


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
            "passed": True,
            "provider_call_count": 0,
            "outbound_network_attempt_count": 0,
            "attempts": [],
        },
    )
    payload = {
        "schema_version": "guide-task11-zero-api-summary-v1",
        "passed": True,
        "guard_active": True,
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
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
        network_report_path=network_report,
    )


def test_prepare_evidence_does_not_create_audit_or_readiness(
    tmp_path: Path,
) -> None:
    root, _ = _candidate(tmp_path)
    output = root / "evidence"
    network_report = output / "network.json"
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
                    "passed": True,
                    "provider_call_count": 0,
                    "outbound_network_attempt_count": 0,
                    "attempts": [],
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
        plan_path=root / "docs/superpowers/plans/plan.md",
        manifest_path=output / "manifest.json",
        semantic_summary_path=output / "semantic.json",
        zero_api_summary_path=output / "zero-api.json",
        network_report_path=network_report,
        cases_path=Path(
            "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
        ),
        candidate_head="a" * 40,
        changed_paths=(
            "app/guide/example.py",
            "tests/guide/test_example.py",
            "tools/guide_gates/example.py",
            "docs/superpowers/plans/plan.md",
        ),
        command_runner=run,
        python_executable="python",
    )

    assert set(result) == {
        "candidate_manifest",
        "semantic_summary",
        "zero_api_summary",
        "network_report",
    }
    assert not (output / "independent-audit.json").exists()
    assert not (output / "readiness.json").exists()
    assert len(calls) == 3


def test_saved_readiness_rejects_late_relevant_worktree_change(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    head = _initialize_git_repo(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["candidate_head"] = head
    _write_json(manifest_path, manifest)
    evidence, ledger = _evidence(root, manifest_path)
    output = root / "readiness.json"
    readiness.derive_candidate_readiness(
        manifest_path=manifest_path,
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
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
            fixture_bundle_verifier=lambda _: None,
        )


def test_saved_readiness_revalidates_all_fixture_bundles(
    tmp_path: Path,
) -> None:
    root, manifest_path = _candidate(tmp_path)
    head = _initialize_git_repo(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["candidate_head"] = head
    _write_json(manifest_path, manifest)
    evidence, ledger = _evidence(root, manifest_path)
    output = root / "readiness.json"
    readiness.derive_candidate_readiness(
        manifest_path=manifest_path,
        semantic_summary_path=evidence["semantic_summary"],
        zero_api_summary_path=evidence["zero_api_summary"],
        network_report_path=evidence["network_report"],
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
        fixture_bundle_verifier=lambda path: reviewed.append(path),
    )

    assert reviewed == [
        evidence["desktop_summary"],
        evidence["mobile_summary"],
    ]


def test_finalize_change_manifest_hashes_exact_staged_diff(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    approved = root / "approved.txt"
    approved.write_text("before\n", encoding="utf-8")
    _initialize_git_repo(root)
    approved.write_text("after\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "approved.txt"],
        cwd=root,
        check=True,
    )
    manifest_path = root / "task11-change-manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": "guide-task11-change-manifest-v1",
            "approved_paths": ["approved.txt"],
            "staged_diff_sha256": None,
            "finalized": False,
        },
    )

    result = readiness.finalize_change_manifest(
        repo_root=root,
        manifest_path=manifest_path,
    )

    expected_diff = subprocess.run(
        ["git", "diff", "--cached", "--binary", "--", "approved.txt"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    assert result["staged_diff_sha256"] == sha256(
        expected_diff
    ).hexdigest()
    assert result["finalized"] is True


def test_finalize_change_manifest_rejects_unapproved_staged_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "approved.txt").write_text("before\n", encoding="utf-8")
    (root / "other.txt").write_text("before\n", encoding="utf-8")
    _initialize_git_repo(root)
    (root / "approved.txt").write_text("after\n", encoding="utf-8")
    (root / "other.txt").write_text("after\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "approved.txt", "other.txt"],
        cwd=root,
        check=True,
    )
    manifest_path = root / "task11-change-manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": "guide-task11-change-manifest-v1",
            "approved_paths": ["approved.txt"],
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
            manifest_path=manifest_path,
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
    candidate_readiness = root / "candidate-readiness.json"
    _write_json(
        candidate_readiness,
        {
            "plan_revision": "task11-r1",
            "protected_payload_sha256": (
                candidate["protected_payload_sha256"]
            ),
            "evidence_files": {"zero_api_summary": str(evidence)},
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
            "attempts": [{
                "attempt_id": "bounded-smoke-attempt-02",
                "result": "passed",
            }]
        },
    )

    result = readiness.build_change_manifest(
        candidate_manifest_path=candidate_manifest,
        candidate_readiness_path=candidate_readiness,
        attempt_context_path=context,
        ledger_path=ledger,
        output_path=output,
    )

    assert result["bounded_attempt_id"] == (
        "bounded-smoke-attempt-02"
    )
    assert (
        "attempt/browser-desktop/summary.json"
        in result["bounded_artifact_paths"]
    )
    assert "app/guide/example.py" in result["approved_paths"]
    assert "evidence.json" in result["approved_paths"]
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
    candidate_readiness = root / "candidate-readiness.json"
    _write_json(
        candidate_readiness,
        {
            "plan_revision": "task11-r1",
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
            "attempts": [{
                "attempt_id": "bounded-smoke-attempt-02",
                "result": "passed",
            }]
        },
    )

    with pytest.raises(
        readiness.Task11ReadinessError,
        match="bounded summary is invalid",
    ):
        readiness.build_change_manifest(
            candidate_manifest_path=candidate_manifest,
            candidate_readiness_path=candidate_readiness,
            attempt_context_path=context,
            ledger_path=ledger,
            output_path=root / "change.json",
        )
