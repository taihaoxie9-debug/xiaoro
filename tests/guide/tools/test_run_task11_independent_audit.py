from __future__ import annotations

import ast
import base64
from functools import lru_cache
from hashlib import sha256
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from typing import Callable
import zlib

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from tools.guide_gates import attempt_ledger
from tools.guide_gates import run_zero_api_runtime as zero_runtime
from tools.guide_gates.run_mainline_contract_browser_audit import (
    fixture_sse_bytes,
)


MODULE = "tools.guide_gates.run_task11_independent_audit"
HEAD = "a" * 64
FIXTURE_TURNS = (
    "fixture-explore-recommendation",
    "fixture-fit-recommendation",
    "fixture-fit-clarification",
    "fixture-product-knowledge",
    "fixture-comparison",
    "fixture-image-identity",
    "fixture-image-fit-recommendation",
    "fixture-multi-image-comparison",
)
TASK12_TOOL_PATHS = (
    "tools/guide_gates/attempt_ledger.py",
    "tools/guide_gates/build_responsibility_matrix.py",
    "tools/guide_gates/build_task11_readiness.py",
    "tools/guide_gates/record_manual_screenshot_review.py",
    "tools/guide_gates/replay_final_real_backend.py",
    "tools/guide_gates/run_bound_runtime.py",
    "tools/guide_gates/runtime_auth.py",
    "tools/guide_gates/run_final_real_translation.py",
    "tools/guide_gates/run_final_release_gate.py",
    "tools/guide_gates/run_mainline_contract_browser_audit.py",
    "tools/guide_gates/run_zero_api_runtime.py",
)
TASK12_TEST_PATHS = (
    "tests/guide/tools/test_build_responsibility_matrix.py",
    "tests/guide/tools/test_final_real_translation.py",
    "tests/guide/tools/test_replay_final_real_backend.py",
    "tests/guide/tools/test_final_release_gate.py",
    "tests/guide/tools/test_record_manual_screenshot_review.py",
)
TASK12_FIXTURE_PATHS = (
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v5.jsonl",
)
TASK12_RUNTIME_DATA_PATHS = (
    "data/canonical/core_products_v1_manifest.json",
    "data/canonical/core_products_v1.jsonl",
    "data/canonical/seed_product_images_v1_manifest.json",
    "data/canonical/seed_product_images_v1.jsonl",
)
BROWSER_CANONICAL_DATA_PATHS = (
    "data/canonical/core_products_v1_manifest.json",
    "data/canonical/core_products_v1.jsonl",
    "data/canonical/seed_product_images_v1_manifest.json",
    "data/canonical/seed_product_images_v1.jsonl",
    "data/canonical/controlled_product_aliases_v1_manifest.json",
    "data/canonical/controlled_product_aliases_v1.jsonl",
    "data/guide_category_facts/category_facts_v1_manifest.json",
    (
        "data/guide_category_facts/"
        "category_facts_v1."
        "9e037e77a4f7dbf3c5eb67f18850ff70fa33748131c19f3c7f3ceaa023f859bb."
        "jsonl"
    ),
    (
        "data/guide_product_display_bindings/v1/"
        "product_display_bindings_v1_manifest.json"
    ),
    (
        "data/guide_product_display_bindings/v1/"
        "product_display_bindings_v1."
        "1c4c8b655862cace29f62d9e7e14abf111668434572dbd8ddb902c8bf5b45d31."
        "jsonl"
    ),
    (
        "data/guide_selection_concepts/v2/"
        "selection_concepts_v1_manifest.json"
    ),
    (
        "data/guide_selection_concepts/v2/"
        "selection_concepts_v1."
        "0642ea8067325c7f3aed8ffbb884d5415ff42c9163b634def913f5de2a24e4d5."
        "jsonl"
    ),
    "data/guide_merchant_claims/merchant_claims_v1_manifest.json",
    (
        "data/guide_merchant_claims/"
        "merchant_claims_v1."
        "8b90f33d45368c269076d96a8b0ca76fd1c5fcac988fd96cc93937da7d4207fd."
        "jsonl"
    ),
)
PRODUCTION_MATRIX_FIXTURE_PATH = (
    "tests/fixtures/guide/intent/"
    "task11_production_path_matrix_v1.jsonl"
)
SEMANTIC_MATRIX_FIXTURE_PATH = (
    "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
)
BOUNDED_TRAJECTORY_MESSAGES = (
    (
        "bounded-text-fit",
        "bounded-text-fit-t1",
        "给我推荐一款最适合油敏肌、换季泛红的 900 到 1100 元精华",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t1",
        "给我推荐 900 到 1100 元的精华",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t2",
        "第二款的质地适合什么肤质？",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t3",
        "我现在有点换季泛红，T 区出油，我可能是什么肤质？",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t4",
        "确认",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t5",
        "回到刚才的推荐，第一款和第二款哪个更适合我的肤质？",
    ),
    (
        "bounded-image-context",
        "bounded-image-context-t1",
        "",
    ),
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
REAL_RECLASSIFICATION_REPAIR_ROOT = Path(
    "docs/audits/final-release/mainline-contract-closure/"
    "repair-epoch-26"
)
REAL_PLANNING_REPAIR_ROOT = Path(
    "docs/audits/final-release/mainline-contract-closure/"
    "repair-epoch-30"
)
REAL_ATTEMPT_09_FAILURE_ROOT = Path(
    "docs/audits/final-release/mainline-contract-closure/"
    "bounded-smoke-attempt-09/browser-desktop/"
    "bounded-image-context/t2"
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
RETRY_RUNTIME_PUBLIC_KEY = (
    "Kay64UG8yvCyLhqU000LxzYeUm0L_hLIl5S8kyKWbdc"
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


def _audit_module():
    return importlib.import_module(MODULE)


def test_independent_audit_requires_clarification_browser_fixture() -> None:
    assert _audit_module().FIXTURE_TURNS == FIXTURE_TURNS


@pytest.mark.parametrize(
    "path",
    (
        ".env.example",
        "Dockerfile",
        "docker-compose.prod.yml",
        "docker-compose.yml",
        "init.sql",
        "nginx.conf",
        "pytest-guide.ini",
        "requirements-guide-browser-matrix.txt",
        "requirements-guide-image.txt",
        "requirements-guide-runtime-test.txt",
        "requirements-guide-runtime.txt",
        "requirements.txt",
        "start.sh",
    ),
)
def test_independent_audit_includes_root_runtime_inputs(path: str) -> None:
    assert _audit_module()._is_relevant_change_path(path)


def test_independent_audit_binds_matrix_to_browser_bounded_messages() -> None:
    observed = _audit_module()._validate_bounded_trajectory_messages(
        root=Path.cwd(),
        cases_path=Path(PRODUCTION_MATRIX_FIXTURE_PATH),
    )

    assert observed == BOUNDED_TRAJECTORY_MESSAGES


def test_independent_audit_rejects_bounded_browser_message_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    browser_path = (
        root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    browser_path.parent.mkdir(parents=True)
    source_path = Path(
        "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    source = source_path.read_text(encoding="utf-8")
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
        _audit_module().Task11IndependentAuditError,
        match="bounded trajectory messages",
    ):
        _audit_module()._validate_bounded_trajectory_messages(
            root=root,
            cases_path=cases_path,
        )


def test_independent_audit_rejects_non_string_bounded_message(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    browser_path = (
        root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    browser_path.parent.mkdir(parents=True)
    browser_source = Path(
        "tools/guide_gates/run_mainline_contract_browser_audit.py"
    ).read_text(encoding="utf-8")
    assert browser_source.count('message=""') >= 1
    browser_path.write_text(
        browser_source.replace('message=""', 'message="None"', 1),
        encoding="utf-8",
    )
    source_cases = Path(PRODUCTION_MATRIX_FIXTURE_PATH)
    rows = [
        json.loads(line)
        for line in source_cases.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    target = next(
        row
        for row in rows
        if row.get("case_id") == "bounded-image-context-t1"
    )
    target["message"] = None
    cases_path = root / PRODUCTION_MATRIX_FIXTURE_PATH
    cases_path.parent.mkdir(parents=True)
    cases_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="bounded trajectory messages",
    ):
        _audit_module()._validate_bounded_trajectory_messages(
            root=root,
            cases_path=cases_path,
        )


def _failure_reclassification_case(
    tmp_path: Path,
) -> dict[str, object]:
    evidence = (
        tmp_path
        / "bounded-smoke-attempt-08"
        / "browser-desktop"
        / "bounded-text-fit"
        / "t1"
    )
    evidence.mkdir(parents=True)
    clarification = {
        "question": "请补充一个更明确的使用场景。",
        "clarification_code": "goal",
        "intended_responsibility": "recommendation",
        "intended_recommendation_mode": "fit",
        "clarification_basis": "fit_selection_evidence_gap",
        "fit_gap_stage": "decision_selection",
        "fit_decision_status": "INSUFFICIENT_FOR_WINNER",
        "fit_candidate_count": 3,
        "fit_evidence_ref_count": 9,
        "fit_public_fact_count": 0,
    }
    request_id = "request-attempt-08"
    _write_json(
        evidence / "request.json",
        {
            "turn_id": "bounded-text-fit-t1",
            "request_id": request_id,
            "viewport": {"width": 1440, "height": 1000},
        },
    )
    _write_json(
        evidence / "presentation-contract.json",
        {
            "terminal_kind": "clarification",
            "clarification": clarification,
        },
    )
    _write_json(
        evidence / "terminal-dom.json",
        {
            "request_id": request_id,
            "terminal_kind": "clarification",
            "presentation_mode": None,
            "legacy_message_count": 0,
            "clarification_message_count": 1,
            "legacy_product_card_count": 0,
            "turn_presentation_root_count": 0,
            "visible_section_kinds": [],
            "inline_product_ids": [],
            "visible_product_ids": [],
            "shelf_product_ids": [],
            "presentation_text": clarification["question"],
        },
    )
    (evidence / "stream.sse").write_text(
        "event: start\n"
        'data: {"session_id":"attempt-08"}\n\n'
        "event: intent\n"
        'data: {"intent":"recommend"}\n\n'
        "event: clarify\n"
        f"data: {json.dumps(clarification, ensure_ascii=False)}\n\n"
        "event: end\n"
        'data: {"conversation_version":1}\n\n',
        encoding="utf-8",
    )
    (evidence / "screenshot.png").write_bytes(_png_bytes(1440, 1000))
    _write_json(
        evidence / "console.json",
        [{
            "type": "error",
            "text": (
                "Failed to load resource: the server responded with "
                "a status of 404 (Not Found)"
            ),
        }],
    )
    _write_json(evidence / "network.json", [])

    repair_root = tmp_path / "repair-epoch-26"
    repair_root.mkdir()
    repair_files = {
        "pre_fix_reproduction": (
            repair_root / "attempt-08-pre-fix-reproduction.xml"
        ),
        "post_fix_verification": (
            repair_root / "attempt-08-post-fix-verification.xml"
        ),
        "focused_zero_api": (
            repair_root / "attempt-08-focused-zero-api.xml"
        ),
        "repair_patch": (
            repair_root / "attempt-08-frontend-delivery-repair.patch"
        ),
    }
    for path in repair_files.values():
        shutil.copy2(REAL_RECLASSIFICATION_REPAIR_ROOT / path.name, path)
    readiness = tmp_path / "readiness.json"
    _write_json(
        readiness,
        {"protected_payload_sha256": "d" * 64},
    )
    context = evidence.parents[2] / "attempt-context.json"
    historical = {
        "attempt_id": "bounded-smoke-attempt-08",
        "plan_revision": "2026-08-23-task11-r5",
        "repair_epoch": 1,
        "retry_authorization_id": "auth-attempt-08",
        "code_revision": "a" * 40,
        "started_at": "2026-08-25T05:41:10Z",
        "trajectory_set": "bounded",
        "context_path": str(context.resolve()),
        "context_sha256": None,
        "first_failure_turn_id": "bounded-text-fit-t1",
        "first_failure_owner": "planning_state",
        "failure_code": "AuditBundleError",
        "evidence_directory": str(evidence.resolve()),
        "result": "failed",
    }
    _write_json(
        context,
        {
            "attempt_record_sha256": (
                attempt_ledger._attempt_allocation_sha256(historical)
            ),
            "readiness_path": str(readiness.resolve()),
            "readiness_sha256": sha256(readiness.read_bytes()).hexdigest(),
        },
    )
    historical["context_sha256"] = sha256(
        context.read_bytes()
    ).hexdigest()
    ledger = tmp_path / "ledger.json"
    _write_json(
        ledger,
        {
            "schema_version": "guide-smoke-attempt-ledger-v1",
            "revision": 33,
            "attempts": [historical],
        },
    )
    output = (
        repair_root
        / "attempt-08-failure-reclassification-audit.json"
    )
    return {
        "attempt_id": "bounded-smoke-attempt-08",
        "ledger": ledger,
        "repair_root": repair_root,
        "repair_files": repair_files,
        "output": output,
    }


def _planning_state_reclassification_case(
    tmp_path: Path,
) -> dict[str, object]:
    evidence = (
        tmp_path
        / "bounded-smoke-attempt-09"
        / "browser-desktop"
        / "bounded-image-context"
        / "t2"
    )
    evidence.mkdir(parents=True)
    for name in (
        "console.json",
        "network.json",
        "presentation-contract.json",
        "request.json",
        "screenshot.png",
        "stream.sse",
        "terminal-dom.json",
    ):
        shutil.copy2(REAL_ATTEMPT_09_FAILURE_ROOT / name, evidence / name)
    previous_turn = evidence.parent / "t1"
    previous_turn.mkdir()
    shutil.copy2(
        REAL_ATTEMPT_09_FAILURE_ROOT.parent / "t1" / "stream.sse",
        previous_turn / "stream.sse",
    )

    repair_root = tmp_path / "repair-epoch-30"
    repair_root.mkdir()
    repair_files = {
        "pre_fix_reproduction": (
            repair_root / "attempt-09-pre-fix-reproduction.xml"
        ),
        "post_fix_verification": (
            repair_root / "attempt-09-post-fix-verification.xml"
        ),
        "focused_zero_api": (
            repair_root / "attempt-09-focused-zero-api.xml"
        ),
        "repair_patch": (
            repair_root / "attempt-09-planning-state-repair.patch"
        ),
    }
    for path in repair_files.values():
        shutil.copy2(REAL_PLANNING_REPAIR_ROOT / path.name, path)

    readiness = tmp_path / "readiness.json"
    _write_json(
        readiness,
        {"protected_payload_sha256": "e" * 64},
    )
    context = evidence.parents[2] / "attempt-context.json"
    historical = {
        "attempt_id": "bounded-smoke-attempt-09",
        "plan_revision": "2026-08-25-task11-r6",
        "repair_epoch": 0,
        "retry_authorization_id": "auth-attempt-09",
        "code_revision": "b" * 40,
        "started_at": "2026-08-25T14:31:05Z",
        "trajectory_set": "bounded",
        "context_path": str(context.resolve()),
        "context_sha256": None,
        "first_failure_turn_id": "bounded-image-context-t2",
        "first_failure_owner": "sse_contract",
        "failure_code": "GUIDE_INTERNAL_ERROR",
        "evidence_directory": str(evidence.resolve()),
        "result": "failed",
    }
    _write_json(
        context,
        {
            "attempt_record_sha256": (
                attempt_ledger._attempt_allocation_sha256(historical)
            ),
            "readiness_path": str(readiness.resolve()),
            "readiness_sha256": sha256(readiness.read_bytes()).hexdigest(),
        },
    )
    historical["context_sha256"] = sha256(
        context.read_bytes()
    ).hexdigest()
    ledger = tmp_path / "ledger.json"
    _write_json(
        ledger,
        {
            "schema_version": "guide-smoke-attempt-ledger-v1",
            "revision": 38,
            "attempts": [historical],
        },
    )
    return {
        "attempt_id": "bounded-smoke-attempt-09",
        "ledger": ledger,
        "repair_root": repair_root,
        "repair_files": repair_files,
        "output": (
            repair_root
            / "attempt-09-failure-reclassification-audit.json"
        ),
    }


def _runtime_shell_reclassification_case(
    tmp_path: Path,
    *,
    version_sync: bool = False,
) -> dict[str, object]:
    attempt_number = 11 if version_sync else 10
    attempt_id = f"bounded-smoke-attempt-{attempt_number}"
    attempt_root = tmp_path / attempt_id
    browser = attempt_root / "browser-desktop"
    browser.mkdir(parents=True)
    readiness = tmp_path / "readiness.json"
    _write_json(
        readiness,
        {"protected_payload_sha256": "f" * 64},
    )
    context = attempt_root / "attempt-context.json"
    historical = {
        "attempt_id": attempt_id,
        "plan_revision": (
            "2026-08-29-task11-r46"
            if version_sync
            else "2026-08-29-task11-r44"
        ),
        "repair_epoch": 0,
        "retry_authorization_id": f"auth-attempt-{attempt_number}",
        "code_revision": "c" * 40,
        "started_at": "2026-08-29T02:20:02Z",
        "trajectory_set": "bounded",
        "context_path": str(context.resolve()),
        "context_sha256": None,
        "first_failure_turn_id": "bounded-runner-startup",
        "first_failure_owner": "browser_audit",
        "failure_code": "TimeoutError",
        "evidence_directory": str(
            (browser if version_sync else attempt_root).resolve()
        ),
        "result": "failed",
    }
    _write_json(
        context,
        {
            "attempt_record_sha256": (
                attempt_ledger._attempt_allocation_sha256(historical)
            ),
            "readiness_path": str(readiness.resolve()),
            "readiness_sha256": sha256(readiness.read_bytes()).hexdigest(),
        },
    )
    context_sha256 = sha256(context.read_bytes()).hexdigest()
    historical["context_sha256"] = context_sha256
    _write_json(
        attempt_root / "runtime-identity.json",
        {
            "schema_version": "guide-bound-runtime-identity-v1",
            "phase": "bounded",
            "attempt_id": attempt_id,
            "attempt_context_path": str(context.resolve()),
            "attempt_context_sha256": context_sha256,
        },
    )
    _write_json(
        browser / "summary.json",
        {
            "schema_version": "guide-mainline-contract-browser-audit-v1",
            "trajectory_set": "bounded",
            "base_url": "http://127.0.0.1:8821",
            "viewport": "desktop",
            "trajectories": [],
            "turn_count": 0,
            "invalid_clarification_count": 0,
            "passed": False,
        },
    )
    _write_json(
        browser / "runner-failure.json",
        {
            "schema_version": "guide-browser-runner-failure-v1",
            "failure_turn_id": "bounded-runner-startup",
            "error_type": "TimeoutError",
            "error_message": (
                "Page.wait_for_function: Timeout 120000ms exceeded."
                if version_sync
                else (
                    "Page.goto: Timeout 30000ms exceeded.\n"
                    'navigating to "http://127.0.0.1:8821/chat"'
                )
            ),
        },
    )
    if version_sync:
        trajectory = browser / "bounded-text-fit"
        trajectory.mkdir()
        _write_json(
            trajectory / "summary.json",
            {
                "trajectory_id": "bounded-text-fit",
                "turns": [],
                "turn_count": 0,
                "invalid_clarification_count": 0,
            },
        )
    terminal_root = browser if version_sync else attempt_root
    evidence_hashes = {
        path.relative_to(attempt_root).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(terminal_root.rglob("*"))
        if path.is_file()
    }
    historical["terminal_evidence"] = {
        "schema_version": "guide-attempt-terminal-evidence-v1",
        "root": str(terminal_root.resolve()),
        "sha256_by_path": evidence_hashes,
    }
    historical["runtime_attestation"] = {
        "schema_version": "guide-bound-runtime-attestation-v2",
        "phase": "bounded",
        "attempt_id": attempt_id,
        "attempt_context_sha256": context_sha256,
        "runtime_identity_path": str(
            (attempt_root / "runtime-identity.json").resolve()
        ),
        "runtime_identity_sha256": evidence_hashes[
            "runtime-identity.json"
        ] if not version_sync else sha256(
            (attempt_root / "runtime-identity.json").read_bytes()
        ).hexdigest(),
    }
    ledger = tmp_path / "ledger.json"
    _write_json(
        ledger,
        {
            "schema_version": "guide-smoke-attempt-ledger-v1",
            "revision": 51 if version_sync else 45,
            "attempts": [historical],
        },
    )
    repair_root = tmp_path / "repair-epoch-62"
    repair_root.mkdir()
    repair_files: dict[str, Path] = {}
    for suffix in (
        "pre-fix-reproduction.xml",
        "post-fix-verification.xml",
        "focused-zero-api.xml",
        "runtime-gate-repair.patch",
    ):
        path = repair_root / f"attempt-{attempt_number}-{suffix}"
        path.write_text("evidence\n", encoding="utf-8")
        repair_files[suffix] = path
    return {
        "attempt_id": attempt_id,
        "ledger": ledger,
        "repair_root": repair_root,
        "repair_files": repair_files,
        "output": (
            repair_root
            / (
                f"attempt-{attempt_number}-"
                "failure-reclassification-audit.json"
            )
        ),
    }


def _run_failure_reclassification_case(
    case: dict[str, object],
) -> dict[str, object]:
    return _audit_module().run_failure_reclassification_audit(
        ledger_path=case["ledger"],
        attempt_id=str(case["attempt_id"]),
        repair_root=case["repair_root"],
        output_path=case["output"],
    )


def test_failure_reclassification_is_derived_from_bound_artifacts(
    tmp_path: Path,
) -> None:
    case = _failure_reclassification_case(tmp_path)

    report = _run_failure_reclassification_case(case)

    assert report["passed"] is True
    assert report["previous_failure_owner"] == "planning_state"
    assert report["first_failure_owner"] == "dom_rendering"
    assert report["failure_code"] == "zero_card_feedback_target_lookup"
    assert report["repair_evidence_files"] == {
        name: str(path.resolve())
        for name, path in case["repair_files"].items()
    }
    assert json.loads(
        case["output"].read_text(encoding="utf-8")
    ) == report


def test_attempt_09_reclassification_derives_planning_state_owner(
    tmp_path: Path,
) -> None:
    case = _planning_state_reclassification_case(tmp_path)

    report = _run_failure_reclassification_case(case)

    assert report["passed"] is True
    assert report["attempt_id"] == "bounded-smoke-attempt-09"
    assert report["previous_failure_owner"] == "sse_contract"
    assert report["previous_failure_code"] == "GUIDE_INTERNAL_ERROR"
    assert report["first_failure_owner"] == "planning_state"
    assert report["failure_code"] == (
        "missing_persisted_image_scenario_inputs"
    )
    assert report["repair_proof"]["pre_fix_test_count"] == 1
    assert report["repair_proof"]["post_fix_test_count"] == 1
    assert report["repair_proof"]["focused_test_count"] == 8
    assert (
        report["repair_proof"]["live_preimage_outcome"]
        == "descendant_red"
    )
    assert (
        report["repair_proof"]["historical_red_evidence_preserved"]
        is True
    )
    assert report["repair_proof"]["live_red_exit_code"] == 1
    assert report["repair_proof"]["live_green_exit_code"] == 0
    assert set(
        report["repair_proof"]["patch_preimage_blob_sha1_by_path"]
    ) == {
        "app/guide/application/unified_guide_flow.py",
        "tests/guide/tools/test_task11_production_path_matrix.py",
    }


def test_attempt_10_reclassification_derives_runtime_gate_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _audit_module()
    case = _runtime_shell_reclassification_case(tmp_path)
    monkeypatch.setattr(
        module,
        "validate_runtime_shell_lease_repair_evidence",
        lambda **_: {
            "regression_node_count": 2,
            "pre_fix_test_count": 2,
            "post_fix_test_count": 2,
            "focused_test_count": 3,
        },
        raising=False,
    )

    report = _run_failure_reclassification_case(case)

    assert report["passed"] is True
    assert report["previous_failure_owner"] == "browser_audit"
    assert report["previous_failure_code"] == "TimeoutError"
    assert report["first_failure_owner"] == "runtime_gate"
    assert report["failure_code"] == (
        "runtime_shell_authority_lease_timeout"
    )
    assert report["repair_proof"]["regression_node_count"] == 2
    assert json.loads(
        case["output"].read_text(encoding="utf-8")
    ) == report


def test_attempt_11_reclassification_derives_version_sync_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _audit_module()
    case = _runtime_shell_reclassification_case(
        tmp_path,
        version_sync=True,
    )
    monkeypatch.setattr(
        module,
        "validate_runtime_request_authority_repair_evidence",
        lambda **_: {
            "regression_node_count": 4,
            "pre_fix_test_count": 4,
            "post_fix_test_count": 4,
            "focused_test_count": 5,
        },
        raising=False,
    )

    report = _run_failure_reclassification_case(case)

    assert report["passed"] is True
    assert report["previous_failure_owner"] == "browser_audit"
    assert report["previous_failure_code"] == "TimeoutError"
    assert report["first_failure_owner"] == "runtime_gate"
    assert report["failure_code"] == (
        "runtime_version_sync_authority_check_timeout"
    )
    assert report["repair_proof"]["regression_node_count"] == 4
    assert json.loads(
        case["output"].read_text(encoding="utf-8")
    ) == report


def test_runtime_request_authority_repair_rejects_unbound_files(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="runtime request authority repair evidence file inventory",
    ):
        _audit_module().validate_runtime_request_authority_repair_evidence(
            repair_files={},
            repo_root=tmp_path,
        )


def test_attempt_09_reclassification_rejects_unbound_repair_patch(
    tmp_path: Path,
) -> None:
    case = _planning_state_reclassification_case(tmp_path)
    patch_path = case["repair_files"]["repair_patch"]
    patch_path.write_text(
        patch_path.read_text(encoding="utf-8").replace(
            "planning_product_ids = _confirmed_image_product_ids(snapshot)",
            "planning_product_ids = forged_snapshot_product_ids",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="planning-state repair patch",
    ):
        _run_failure_reclassification_case(case)


def test_attempt_09_reclassification_requires_current_focused_nodes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = _planning_state_reclassification_case(tmp_path)
    module = _audit_module()
    missing = next(
        node
        for node in module.PLANNING_RECLASSIFICATION_FOCUSED_NODES
        if node != module.PLANNING_RECLASSIFICATION_REGRESSION_NODE
    )
    monkeypatch.setattr(
        module,
        "_collect_pytest_nodes",
        lambda *_args, **_kwargs: tuple(
            sorted(
                module.PLANNING_RECLASSIFICATION_FOCUSED_NODES
                - {missing}
            )
        ),
    )

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="planning-state focused JUnit node inventory is invalid",
    ):
        module.validate_persisted_image_planning_repair_evidence(
            repair_files=case["repair_files"],
            repo_root=Path(__file__).resolve().parents[3],
        )


def test_attempt_09_reclassification_binds_previous_turn_stream(
    tmp_path: Path,
) -> None:
    case = _planning_state_reclassification_case(tmp_path)
    previous_stream = (
        Path(case["repair_root"]).parent
        / "bounded-smoke-attempt-09"
        / "browser-desktop"
        / "bounded-image-context"
        / "t1"
        / "stream.sse"
    )
    previous_stream.write_bytes(previous_stream.read_bytes() + b"\n")

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="previous image turn stream",
    ):
        _run_failure_reclassification_case(case)


def test_failure_reclassification_rejects_testcase_free_junit(
    tmp_path: Path,
) -> None:
    case = _failure_reclassification_case(tmp_path)
    case["repair_files"]["pre_fix_reproduction"].write_text(
        '<testsuite tests="1" failures="1" errors="0"/>',
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="repair JUnit evidence has no test cases",
    ):
        _run_failure_reclassification_case(case)


def test_failure_reclassification_rejects_wrong_regression_node(
    tmp_path: Path,
) -> None:
    case = _failure_reclassification_case(tmp_path)
    case["repair_files"]["pre_fix_reproduction"].write_text(
        (
            '<testsuite tests="1" failures="1" errors="0">'
            '<testcase classname="tests.guide.runtime.'
            'test_feedback_frontend" name="test_unrelated">'
            "<failure>failed</failure></testcase></testsuite>"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="repair RED JUnit regression node is invalid",
    ):
        _run_failure_reclassification_case(case)


def test_failure_reclassification_rejects_unreviewed_focused_nodes(
    tmp_path: Path,
) -> None:
    case = _failure_reclassification_case(tmp_path)
    case["repair_files"]["focused_zero_api"].write_text(
        (
            '<testsuite tests="1" failures="0" errors="0">'
            '<testcase classname="tests.guide.runtime.'
            'test_feedback_frontend" '
            'name="test_feedback_target_lookup_requires_terminal_visible_products" />'
            "</testsuite>"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="focused JUnit node inventory is invalid",
    ):
        _run_failure_reclassification_case(case)


def test_failure_reclassification_rejects_forged_focused_node_identity(
    tmp_path: Path,
) -> None:
    case = _failure_reclassification_case(tmp_path)
    focused_path = case["repair_files"]["focused_zero_api"]
    focused_path.write_text(
        focused_path.read_text(encoding="utf-8").replace(
            "test_renderer_accepts_four_product_comparison_contract",
            "test_forged_renderer_case",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="focused JUnit node inventory is invalid",
    ):
        _run_failure_reclassification_case(case)


def test_failure_reclassification_rejects_non_applicable_patch(
    tmp_path: Path,
) -> None:
    case = _failure_reclassification_case(tmp_path)
    patch_path = case["repair_files"]["repair_patch"]
    patch_path.write_text(
        patch_path.read_text(encoding="utf-8").replace(
            "// owner check: before version write",
            "// forged context that does not exist",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="repair patch does not reverse-apply to the candidate",
    ):
        _run_failure_reclassification_case(case)


def test_reclassification_inventory_registers_chromium_probe_regression(
) -> None:
    nodes = {
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_rejects_sibling_manifest_path"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_rejects_sibling_symlink"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_rejects_symlinked_epoch_directory"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_canonical_payload_rejects_symlinked_ancestor"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_revalidates_protected_payload_before_publish"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_hashes_the_same_bytes_it_parses"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_manifest_requires_reviewed_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_candidate_readiness_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_zero_api_summary_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_zero_api_summary_reuses_the_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_change_manifest_clis_require_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_task11_readiness_requires_external_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_release_readiness_branch_forwards_external_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_runtime_verifier_receives_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_sibling_candidate_manifest"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_symlinked_epoch_directory"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_payload_hash_rejects_symlinked_ancestor"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_hashes_the_same_bytes_it_parses"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_cli_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_top_level_rejects_wrong_reviewed_sha256"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[runtime-key-consumption-order]"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_allocation_requires_authorization_receipt"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorization_receipt_verifier_requires_complete_history"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_checkpoint_backfills_legacy_authorization_receipts"
        ),
        (
            "tests/guide/tools/test_single_path_architecture.py::"
            "test_processor_cannot_delegate_through_local_callable_alias"
        ),
        (
            "tests/guide/tools/test_single_path_architecture.py::"
            "test_processor_alias_resolution_uses_definition_at_call_site"
        ),
        (
            "tests/guide/tools/test_single_path_architecture.py::"
            "test_processor_cannot_delegate_through_module_callable_alias"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_publish_recovers_partial_pending_write"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_revalidates_payload_after_final_key_check"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_rechecks_runtime_keys_after_publication_link"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_canonical_payload_rejects_replaced_intermediate_ancestor"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_rejects_dead_calls"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_rejects_"
            "empty_loop_calls"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_rejects_"
            "local_callable_alias"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_uses_"
            "reaching_alias_definition"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_resolves_"
            "module_callable_alias"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_rejects_shadowed_calls"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_payload_hash_rejects_"
            "replaced_intermediate_ancestor"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_executable_call_nodes_ignore_empty_comprehensions"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[allocation-requires-authorization-receipt]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[authorization-receipt-history-complete]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[readiness-final-payload-revalidation]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_rejects_task12_tool_mutations"
            "[readiness-no-replace-commit]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_requires_allocation_"
            "authority_revalidation[persisted-contexts]"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_requires_allocation_"
            "authority_revalidation[authorization-receipts]"
        ),
        (
            "tests/guide/tools/test_run_zero_api_runtime.py::"
            "test_runtime_private_key_unlink_interruption_"
            "preserves_retryable_key"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_attempt_context_binds_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_attempt_ledger.py::"
            "test_authorize_cli_requires_reviewed_manifest_sha256"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_sandbox_audit_records_kernel_denied_chromium_ipv6_probe"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_sandbox_audit_rejects_chromium_probe_denial_after_end"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_drain_canary_is_parent_marked_before_release"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_drain_canary_kills_nonquiescent_descendants"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_drain_child_requires_start_gate"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_sandbox_audit_rejects_child_marker_before_kernel_identity"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_fixture_capture_waits_for_every_required_marker_family"
        ),
        (
            "tests/guide/tools/test_run_mainline_contract_browser_audit.py::"
            "test_short_lived_fixture_canaries_do_not_emit_logger_markers"
        ),
        (
            "tests/guide/tools/test_build_task11_readiness.py::"
            "test_readiness_accepts_parent_observed_runtime_canary_order"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_audit_accepts_parent_observed_runtime_canary_order"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_audit_rejects_marker_before_kernel_identity"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_audit_accepts_fixed_chromium_probe"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_audit_rejects_probe_without_kernel_denial"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_marker_ownership_is_ast_verified"
        ),
        (
            "tests/guide/tools/test_run_task11_independent_audit.py::"
            "test_independent_browser_audit_rejects_probe_denial_after_end"
        ),
    }

    assert nodes <= _audit_module().RECLASSIFICATION_POST_EVIDENCE_NODES


def test_failure_reclassification_cli_uses_derived_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _audit_module()
    observed: dict[str, object] = {}

    def fake_run(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"passed": True}

    monkeypatch.setattr(
        module,
        "run_failure_reclassification_audit",
        fake_run,
    )
    ledger = tmp_path / "ledger.json"
    repair_root = tmp_path / "repair-epoch-26"
    output = repair_root / "attempt-08-failure-reclassification-audit.json"

    assert module.main([
        "audit-failure-reclassification",
        "--ledger",
        str(ledger),
        "--attempt-id",
        "bounded-smoke-attempt-08",
        "--repair-root",
        str(repair_root),
        "--output",
        str(output),
    ]) == 0
    assert observed == {
        "ledger_path": ledger,
        "attempt_id": "bounded-smoke-attempt-08",
        "repair_root": repair_root,
        "output_path": output,
    }


def _task12_manifest() -> dict[str, list[str]]:
    return {
        "source_paths": list(TASK12_RUNTIME_DATA_PATHS),
        "tool_paths": list(TASK12_TOOL_PATHS),
        "test_paths": list(TASK12_TEST_PATHS),
        "fixture_paths": list(TASK12_FIXTURE_PATHS),
    }


def _copy_task12_files(root: Path) -> None:
    for index, relative in enumerate((
        *TASK12_TOOL_PATHS,
        *TASK12_TEST_PATHS,
        *TASK12_FIXTURE_PATHS,
        *TASK12_RUNTIME_DATA_PATHS,
    )):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative in TASK12_TEST_PATHS:
            target.write_text(
                f"def test_task12_surface_{index}():\n"
                "    assert True\n",
                encoding="utf-8",
            )
        else:
            shutil.copy2(Path(relative), target)


def _copy_browser_canonical_files(root: Path) -> None:
    for relative in BROWSER_CANONICAL_DATA_PATHS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(relative), target)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _paeth_predictor(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


@lru_cache(maxsize=16)
def _png_bytes(
    width: int,
    height: int,
    *,
    idat_override: bytes | None = None,
    solid_color: tuple[int, int, int] | None = None,
    nearly_blank: bool = False,
) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", checksum)
        )

    def row_pixels(row_index: int) -> bytes:
        row = bytearray()
        for column in range(width):
            if solid_color is not None:
                color = solid_color
            elif nearly_blank:
                color = (
                    (32, 96, 192)
                    if row_index == 0 and column == 0
                    else (255, 255, 255)
                )
            else:
                x_band = min(7, column * 8 // width)
                y_band = min(7, row_index * 8 // height)
                color = (
                    (37 * x_band + 19 * y_band) % 256,
                    (43 * x_band + 31 * y_band + 20) % 256,
                    (17 * x_band + 59 * y_band + 70) % 256,
                )
            row.extend(color)
        return bytes(row)

    encoded = bytearray()
    previous = bytes(width * 3)
    for row_index in range(height):
        current = row_pixels(row_index)
        filter_type = row_index % 5
        filtered = bytearray(len(current))
        for index, value in enumerate(current):
            left = current[index - 3] if index >= 3 else 0
            above = previous[index]
            upper_left = previous[index - 3] if index >= 3 else 0
            predictor = (
                0
                if filter_type == 0
                else left
                if filter_type == 1
                else above
                if filter_type == 2
                else (left + above) // 2
                if filter_type == 3
                else _paeth_predictor(left, above, upper_left)
            )
            filtered[index] = (value - predictor) & 0xFF
        encoded.append(filter_type)
        encoded.extend(filtered)
        previous = current
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        )
        + chunk(
            b"IDAT",
            (
                zlib.compress(bytes(encoded))
                if idat_override is None
                else idat_override
            ),
        )
        + chunk(b"IEND", b"")
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


def test_independent_audit_accepts_parent_observed_runtime_canary_order(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    payload = json.loads(json.dumps(_runtime_network_payload(manifest_path)))

    _audit_module()._validate_runtime_seatbelt_report(
        payload,
        label="runtime network report",
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


def _fixture_events(
    turn_id: str,
) -> tuple[bytes, tuple[tuple[str, dict[str, object]], ...]]:
    raw = fixture_sse_bytes(turn_id)
    events = []
    for block in raw.decode("utf-8").split("\n\n"):
        if not block:
            continue
        lines = block.splitlines()
        event = lines[0].removeprefix("event:").strip()
        data = json.loads(
            "\n".join(
                line.removeprefix("data:").lstrip()
                for line in lines[1:]
            )
        )
        assert isinstance(data, dict)
        events.append((event, data))
    return raw, tuple(events)


def _browser_summary(
    *,
    root: Path,
    viewport: str,
    runtime_identity_bytes: bytes | None = None,
    challenge: str | None = None,
    challenge_digest: str | None = None,
) -> Path:
    directory = root / f"fixture-browser-{viewport}"
    directory.mkdir(parents=True)
    identity_bytes = (
        runtime_identity_bytes
        if runtime_identity_bytes is not None
        else _canonical_bytes({})
    )
    runtime_identity_sha256 = sha256(
        identity_bytes
    ).hexdigest()
    challenge_payload = _challenge_payload(
        runtime_identity_sha256=runtime_identity_sha256,
        challenge=challenge or challenge_digest or "2" * 64,
    )
    (directory / "runtime-identity.json").write_bytes(
        identity_bytes
    )
    (directory / "consumed-runtime-health-challenge.json").write_bytes(
        _canonical_bytes(challenge_payload)
    )
    nonce = ("d" if viewport == "desktop" else "e") * 64
    sandbox_profile = (
        "(version 1)"
        "(allow default)"
        "(deny network-outbound "
        "(with telemetry) "
        f"(with message \"{nonce}\"))"
        "(allow network-outbound (remote ip \"localhost:*\"))"
        "(allow network-inbound)"
    )
    sandbox_profile_path = directory / "sandbox-profile.sb"
    sandbox_profile_path.write_text(sandbox_profile, encoding="utf-8")
    netlog_path = directory / "chromium-netlog.json"
    netlog_path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "type": "URL_REQUEST_START_JOB",
                        "params": {
                            "url": (
                                "http://127.0.0.1:8820/"
                                "api/v1/chat/stream"
                            ),
                        },
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        directory / "browser-requests.json",
        [
            {
                "url": "http://127.0.0.1:8820/api/v1/chat/stream",
                "method": "POST",
                "resource_type": "fetch",
            }
            for _ in FIXTURE_TURNS
        ],
    )
    root_pid = 4100 if viewport == "desktop" else 4200
    root_child_pid = root_pid + 1
    descendant_pid = root_pid + 2
    drain_pid = root_pid + 100
    raw_events = (
        {
            "eventType": "logEvent",
            "eventMessage": f"XIAORO_SEATBELT_READY:{nonce}",
            "processImagePath": "/usr/bin/logger",
        },
        {
            "eventType": "logEvent",
            "eventMessage": (
                f"XIAORO_SEATBELT_BEGIN:{nonce}:{root_pid}"
            ),
            "processImagePath": "/usr/bin/logger",
        },
        {
            "eventType": "logEvent",
            "eventMessage": (
                f"Sandbox: nc({root_child_pid}) deny(1) "
                f"network-outbound remote:*:9\n{nonce}"
            ),
            "processImagePath": "/kernel",
            "senderImagePath": (
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            ),
        },
        {
            "eventType": "logEvent",
            "eventMessage": (
                f"Sandbox: nc({descendant_pid}) deny(1) "
                f"network-outbound remote:*:443\n{nonce}"
            ),
            "processImagePath": "/kernel",
            "senderImagePath": (
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            ),
        },
        {
            "eventType": "logEvent",
            "eventMessage": (
                f"XIAORO_SEATBELT_CANARY:{nonce}:"
                f"root_child:{root_child_pid}:9"
            ),
            "processImagePath": "/usr/bin/logger",
        },
        {
            "eventType": "logEvent",
            "eventMessage": (
                f"XIAORO_SEATBELT_CANARY:{nonce}:"
                f"descendant:{descendant_pid}:443"
            ),
            "processImagePath": "/usr/bin/logger",
        },
        {
            "eventType": "logEvent",
            "eventMessage": (
                f"XIAORO_SEATBELT_CANARY:{nonce}:"
                f"drain:{drain_pid}:53"
            ),
            "processImagePath": "/usr/bin/logger",
        },
        {
            "eventType": "logEvent",
            "eventMessage": (
                f"Sandbox: nc({drain_pid}) deny(1) "
                f"network-outbound remote:*:53\n{nonce}"
            ),
            "processImagePath": "/kernel",
            "senderImagePath": (
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            ),
        },
        {
            "eventType": "logEvent",
            "eventMessage": f"XIAORO_SEATBELT_END:{nonce}:{root_pid}",
            "processImagePath": "/usr/bin/logger",
        },
        {
            "eventType": "logEvent",
            "eventMessage": f"XIAORO_SEATBELT_DRAIN:{nonce}",
            "processImagePath": "/usr/bin/logger",
        },
    )
    raw = b"".join(
        (
            json.dumps(event, ensure_ascii=True, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        for event in raw_events
    )
    raw_path = directory / "seatbelt.raw.ndjson"
    raw_path.write_bytes(raw)
    profile_sha256 = sha256(sandbox_profile.encode("utf-8")).hexdigest()
    sandbox_path = directory / "sandbox-audit.json"
    sandbox_payload = {
        "schema_version": "guide-fixture-browser-sandbox-audit-v2",
        "passed": True,
        "sandbox_identity": (
            "macos-sandbox-exec-loopback-only:" + profile_sha256
        ),
        "sandbox_profile_sha256": profile_sha256,
        "netlog_sha256": sha256(netlog_path.read_bytes()).hexdigest(),
        "enforcement": "macos-sandbox-exec-loopback-only",
        "measurement": "macos-unified-log-seatbelt-kernel",
        "measurement_nonce": nonce,
        "seatbelt_raw_ndjson_sha256": sha256(raw).hexdigest(),
        "seatbelt_raw_byte_count": len(raw),
        "seatbelt_event_count": len(raw_events),
        "seatbelt_canary_denial_count": 3,
        "logger_ready": True,
        "logger_readiness_marker_count": 1,
        "logger_loss_event_count": 0,
        "logger_returncode": 0,
        "root_pid": root_pid,
        "sandbox_process_group_id": root_pid,
        "process_group_quiescent": True,
        "root_child_canary_pid": root_child_pid,
        "descendant_canary_pid": descendant_pid,
        "drain_canary_pid": drain_pid,
        "canary_denials": [
            {
                "process": "nc",
                "pid": root_child_pid,
                "port": 9,
                "line_number": 3,
            },
            {
                "process": "nc",
                "pid": descendant_pid,
                "port": 443,
                "line_number": 4,
            },
            {
                "process": "nc",
                "pid": drain_pid,
                "port": 53,
                "line_number": 8,
            },
        ],
        "blocked_environmental_probe_count": 0,
        "blocked_environmental_probe_duplicate_count": 0,
        "blocked_environmental_probe_targets": [],
        "process_tree_non_loopback_attempt_count": 0,
        "browser_request_count": len(FIXTURE_TURNS),
        "browser_observed_non_loopback_attempt_count": 0,
        "attempts": [],
    }
    _write_json(
        sandbox_path,
        sandbox_payload,
    )
    for turn_id in FIXTURE_TURNS:
        turn_dir = directory / turn_id
        turn_dir.mkdir()
        image_turn = turn_id in {
            "fixture-image-identity",
            "fixture-image-fit-recommendation",
            "fixture-multi-image-comparison",
        }
        _write_json(
            turn_dir / "request.json",
            {
                "turn_id": turn_id,
                "request_id": f"{viewport}-{turn_id}",
                "body": (
                    {
                        "message": "",
                        "session_id": f"{viewport}-{turn_id}",
                        "conversation_version": 0,
                        "stream": True,
                        "image_bundle_id": "bundle_" + "a" * 32,
                        "image_bundle_version": 1,
                        "image_bundle_token": "token_" + "b" * 32,
                    }
                    if image_turn
                    else {
                        "message": "fixture request",
                        "session_id": f"{viewport}-{turn_id}",
                        "conversation_version": 0,
                        "stream": True,
                    }
                ),
            },
        )
        raw_stream, events = _fixture_events(turn_id)
        is_clarification = turn_id == "fixture-fit-clarification"
        terminal_event = (
            "clarify" if is_clarification else "presentation_contract"
        )
        terminal_payloads = [
            payload
            for event, payload in events
            if event == terminal_event
        ]
        assert len(terminal_payloads) == 1
        terminal_payload = terminal_payloads[0]
        clarification = terminal_payload if is_clarification else None
        contract = (
            {
                "terminal_kind": "clarification",
                "clarification": terminal_payload,
            }
            if is_clarification
            else terminal_payload
        )
        _write_json(turn_dir / "presentation-contract.json", contract)
        (turn_dir / "stream.sse").write_bytes(raw_stream)
        sections = (
            contract.get("sections", [])
            if not is_clarification
            else []
        )
        visible_ids = (
            contract.get("visible_product_ids", [])
            if not is_clarification
            else []
        )
        section_blocks = [
            {
                "kind": section["kind"],
                "text": " ".join(
                    str(value)
                    for value in (
                        section.get("copy_text"),
                        section.get("advisor_reason"),
                        *(
                            fact.get("display_value")
                            for fact in section.get(
                                "direct_facts",
                                [],
                            )
                            if isinstance(fact, dict)
                        ),
                    )
                    if isinstance(value, str) and value
                ),
            }
            for section in sections
            if isinstance(section, dict)
        ]
        inline_ids = [
            section["product_id"]
            for section in sections
            if (
                isinstance(section, dict)
                and section.get("kind") == "product"
                and isinstance(section.get("product_id"), int)
            )
        ]
        _write_json(
            turn_dir / "terminal-dom.json",
            (
                {
                    "request_id": f"{viewport}-{turn_id}",
                    "terminal_kind": "clarification",
                    "presentation_mode": None,
                    "visible_section_kinds": [],
                    "section_blocks": [],
                    "inline_product_ids": [],
                    "visible_product_ids": [],
                    "shelf_product_ids": [],
                    "legacy_message_count": 0,
                    "clarification_message_count": 1,
                    "legacy_product_card_count": 0,
                    "turn_presentation_root_count": 0,
                    "comparison_table_count": 0,
                    "presentation_text": terminal_payload["question"],
                }
                if is_clarification
                else {
                    "request_id": f"{viewport}-{turn_id}",
                    "terminal_kind": "presentation",
                    "presentation_mode": contract["mode"],
                    "visible_section_kinds": [
                        block["kind"] for block in section_blocks
                    ],
                    "section_blocks": section_blocks,
                    "inline_product_ids": inline_ids,
                    "visible_product_ids": visible_ids,
                    "shelf_product_ids": visible_ids,
                    "legacy_message_count": 0,
                    "legacy_product_card_count": 0,
                    "turn_presentation_root_count": 1,
                    "comparison_table_count": (
                        1 if contract["mode"] == "comparison" else 0
                    ),
                    "presentation_text": " ".join(
                        block["text"] for block in section_blocks
                    ),
                }
            ),
        )
        width, height = (
            (1440, 1000)
            if viewport == "desktop"
            else (390, 844)
        )
        (turn_dir / "screenshot.png").write_bytes(
            _png_bytes(width, height)
        )
        _write_json(turn_dir / "console.json", [])
        _write_json(turn_dir / "network.json", [])
        _write_json(
            turn_dir / "sandbox-audit.json",
            sandbox_payload,
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
            "evidence_scope": "frontend_fixture_only",
            "backend_path_claim": False,
            "base_url": "http://127.0.0.1:8820",
            "viewport": viewport,
            "passed": True,
            "turn_count": len(FIXTURE_TURNS),
            "invalid_clarification_count": 0,
            "runtime_identity_sha256": runtime_identity_sha256,
            "consumed_health_challenge_sha256": (
                challenge_payload["challenge_sha256"]
            ),
            "sandbox_identity": (
                "macos-sandbox-exec-loopback-only:" + profile_sha256
            ),
            "sandbox_audit_sha256": sha256(
                sandbox_path.read_bytes()
            ).hexdigest(),
            "seatbelt_raw_ndjson_sha256": sha256(raw).hexdigest(),
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


def _production_summary(
    *,
    manifest_path: Path,
    protected_payload_sha256: str,
    cases_path: Path,
) -> dict[str, object]:
    coverage_dimensions = (
        "active_owner",
        "reply_state",
        "preserved_authority",
        "semantic_act",
        "reference_source",
    )
    cases = [
        json.loads(line)
        for line in cases_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    traces: list[dict[str, object]] = []
    required_edges = sorted({
        edge
        for case in cases
        for edge in case.get("required_state_edges", ())
    })
    versions: dict[str, int] = {}
    for index, case in enumerate(cases):
        trajectory = case["trajectory_id"]
        loaded_version = versions.get(trajectory, 0)
        is_pre_decision_rejection = (
            case["partition"] == "pre_decision_rejection"
        )
        committed_version = (
            loaded_version
            if is_pre_decision_rejection
            else loaded_version + 1
        )
        versions[trajectory] = committed_version
        selected = case.get("expected_processor") or "recommendation"
        digest = sha256(f"decision-{index}".encode()).hexdigest()
        envelope_digest = sha256(f"envelope-{index}".encode()).hexdigest()
        if is_pre_decision_rejection:
            traces.append(
                {
                    "turn_id": case["case_id"],
                    "trajectory_id": trajectory,
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
                    "validated_sse_sha256": envelope_digest,
                    "emitted_sse_sha256": envelope_digest,
                    "selected_processor": "none",
                    "processor_invocation_counts": {
                        "recommendation": 0,
                    },
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
                    "loaded_version": loaded_version,
                    "committed_version": committed_version,
                    "expected_state_edge": case["expected_state_edge"],
                    "observed_state_edge": case["expected_state_edge"],
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
                }
            )
            continue
        traces.append(
            {
                "turn_id": case["case_id"],
                "trajectory_id": trajectory,
                "partition": case["partition"],
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
                "selected_processor": selected,
                "processor_invocation_counts": {selected: 1},
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
                "loaded_version": loaded_version,
                "committed_version": committed_version,
                "expected_state_edge": case["expected_state_edge"],
                "observed_state_edge": case["expected_state_edge"],
                "terminal_event": "end",
                "bounded": case["bounded"],
                "semantic_equivalence_passed": True,
                "accepted": True,
                "coverage_edges": [
                    (
                        f"{left}={case['expected_coverage'][left]}|"
                        f"{right}={case['expected_coverage'][right]}"
                    )
                    for left_index, left in enumerate(coverage_dimensions)
                    for right in coverage_dimensions[left_index + 1 :]
                ]
                if case.get("expected_coverage") is not None
                else [],
                "actual_processor": selected,
                "actual_intent": (
                    case.get("expected_intent") or "recommend"
                ),
                "card_ids": case.get("expected_card_ids") or [],
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
        "candidate_manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "protected_payload_sha256": protected_payload_sha256,
        "cases_sha256": sha256(cases_path.read_bytes()).hexdigest(),
        "passed": True,
        "expected_contract_case_count": 128,
        "actual_equivalence_case_count": 128,
        "trajectory_count": 12,
        "stateful_turn_count": 48,
        "turn_count": 177,
        "state_edge_count": 40,
        "required_state_edge_count": 40,
        "required_state_edges": required_edges,
        "bounded_turn_count": 9,
        "pre_decision_rejection_count": 1,
        "pre_decision_rejection_failure_count": 0,
        "translation_injection_count": 176,
        "observed_layers": [
            "translation",
            "compiler",
            "router",
            "processor",
            "reducer",
            "sqlite",
            "sse",
        ],
        "turn_traces": traces,
        **zero_fields,
    }


def _bundle(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "repo"
    source = "app/guide/service.py"
    test = "tests/guide/test_service.py"
    tool = "tools/guide_gates/run_task11_production_path_matrix.py"
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
    _copy_task12_files(root)
    _copy_browser_canonical_files(root)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    candidate_head = _git(root, "rev-parse", "HEAD")
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    attempt_ledger.initialize_ledger(ledger)
    ledger_bytes = ledger.read_bytes()
    ledger_anchor = attempt_ledger.ledger_anchor(
        attempt_ledger.read_ledger(ledger)
    )
    deleted_bytes = subprocess.run(
        ["git", "show", f"{candidate_head}:{deleted}"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout

    updates = {
        source: "def execute():\n    return 'single-path'\n",
        test: (
            "from tools.guide_gates.run_task11_production_path_matrix "
            "import DEFAULT_CASES_PATH, run_production_path_matrix\n\n"
            "FIXTURE = 'tests/fixtures/guide/task11.json'\n\n"
            "def test_single_path():\n"
            "    result = run_production_path_matrix(\n"
            "        repo_root=REPO_ROOT,\n"
            "        cases_path=DEFAULT_CASES_PATH,\n"
            "        state_root=STATE_ROOT,\n"
            "        candidate_manifest_sha256='a' * 64,\n"
            "        protected_payload_sha256='b' * 64,\n"
            "        cases_sha256='c' * 64,\n"
            "    )\n"
            "    assert result.passed is True\n"
        ),
        tool: (
            "from pathlib import Path\n\n"
            "DEFAULT_CASES_PATH = (\n"
            "    Path(__file__).resolve().parents[2]\n"
            "    / 'tests'\n"
            "    / 'fixtures'\n"
            "    / 'guide'\n"
            "    / 'intent'\n"
            "    / 'task11_production_path_matrix_v1.jsonl'\n"
            ")\n\n"
            "class _ProductionPathObserver:\n"
            "    def compiled(self, **values):\n"
            "        self.compiled_understanding = "
            "values['understanding']\n\n"
            "class Task11ProductionPathRuntime:\n"
            "    def execute(self, case):\n"
            "        actual_coverage = _derive_state_coverage(\n"
            "            current=before,\n"
            "            understanding="
            "self._observer.compiled_understanding,\n"
            "            decision=self._observer.route_decision,\n"
            "            committed=after,\n"
            "            current_image_action=case.image_action,\n"
            "        )\n"
            "        observed_layers = _derive_observed_layers(\n"
            "            observer=self._observer,\n"
            "            emitted_sse=response.content,\n"
            "        )\n"
            "        return ProductionPathTurnTrace(\n"
            "            coverage_edges=actual_coverage.edge_ids(),\n"
            "            observed_layers=observed_layers,\n"
            "        )\n\n"
            "def run_production_path_matrix():\n"
            "    return True\n"
        ),
        plan: (
            "Plan revision: 2026-08-26-task11-r9\n"
            "Task 11 evidence epoch: repair-epoch-08\n"
        ),
        fixture: '{"version": 1}\n',
    }
    for relative, content in updates.items():
        (root / relative).write_text(content, encoding="utf-8")
    (root / deleted).unlink()

    epoch = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "repair-epoch-8"
    )
    epoch.mkdir(parents=True)
    protected = sorted({
        source,
        test,
        tool,
        plan,
        fixture,
        PRODUCTION_MATRIX_FIXTURE_PATH,
        SEMANTIC_MATRIX_FIXTURE_PATH,
        *TASK12_TOOL_PATHS,
        *TASK12_TEST_PATHS,
        *TASK12_FIXTURE_PATHS,
        *BROWSER_CANONICAL_DATA_PATHS,
    })
    payload_hash = _payload_hash(root, protected)
    manifest_path = epoch / "task11-candidate-manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": "guide-task11-candidate-manifest-v1",
            "repository_root": str(root.resolve()),
            "plan_revision": "2026-08-26-task11-r9",
            "repair_epoch": 8,
            "candidate_head": candidate_head,
            "source_paths": sorted({
                source,
                *BROWSER_CANONICAL_DATA_PATHS,
            }),
            "test_paths": sorted({test, *TASK12_TEST_PATHS}),
            "tool_paths": sorted({tool, *TASK12_TOOL_PATHS}),
            "plan_paths": [plan],
            "fixture_paths": sorted({
                fixture,
                PRODUCTION_MATRIX_FIXTURE_PATH,
                SEMANTIC_MATRIX_FIXTURE_PATH,
                *TASK12_FIXTURE_PATHS,
            }),
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
            "change_paths": sorted([
                source,
                test,
                tool,
                plan,
                fixture,
                deleted,
            ]),
            "candidate_payload_sha256": payload_hash,
            "protected_payload_sha256": payload_hash,
            "fixture_runtime_public_keys": [
                TEST_RUNTIME_PUBLIC_KEY,
                RETRY_RUNTIME_PUBLIC_KEY,
            ],
            "fixture_runtime_private_key_paths": [
                str((tmp_path / "runtime-key.json").resolve()),
                str(
                    (
                        tmp_path / "runtime-key.retry-2.json"
                    ).resolve()
                ),
            ],
            "pre_checkpoint_ledger": {
                "path": str(ledger.resolve()),
                "sha256": sha256(ledger_bytes).hexdigest(),
                "revision": ledger_anchor["revision"],
                "revision_hash": ledger_anchor["revision_hash"],
            },
        },
    )

    semantic = epoch / "task11-semantic-matrix-summary.json"
    _write_json(
        semantic,
        {
            "schema_version": "guide-task11-semantic-summary-v1",
            "matrix_kind": "expected_contract",
            "cases_sha256": sha256(
                semantic_fixture.read_bytes()
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
    network = epoch / "task11-zero-api-network.json"
    _write_json(
        network,
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
    zero_api = epoch / "task11-zero-api-summary.json"
    _write_json(
        zero_api,
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
            "candidate_manifest_sha256": sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "protected_payload_sha256": payload_hash,
            "network_report_sha256": sha256(
                network.read_bytes()
            ).hexdigest(),
            "commands": [
                {
                    "argv": ["git", "diff", "--check"],
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                },
                {
                    "argv": [
                        sys.executable,
                        "-m",
                        "compileall",
                        "-q",
                        "app",
                        "tools",
                        "tests",
                    ],
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                },
                {
                    "argv": [
                        "/usr/bin/sandbox-exec",
                        "-p",
                        _audit_module().ZERO_API_SANDBOX_PROFILE,
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "-p",
                        "tools.guide_gates.zero_api_network_guard",
                        *sorted({test, *TASK12_TEST_PATHS}),
                    ],
                    "returncode": 0,
                    "stdout": (
                        f"{1 + len(TASK12_TEST_PATHS)} "
                        "passed in 0.01s\n"
                    ),
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
            "scope_counts": {
                "frontend_fixture": 0,
                "layer_contract": 0,
                "production_path_from_turn_meaning": 1,
                "unit": len(TASK12_TEST_PATHS),
            },
            "fixture_dependencies": sorted({
                fixture,
                PRODUCTION_MATRIX_FIXTURE_PATH,
                SEMANTIC_MATRIX_FIXTURE_PATH,
                *TASK12_FIXTURE_PATHS,
            }),
            "gates": [
                {
                    "gate": (
                        "tests/guide/test_service.py::test_single_path"
                    ),
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
                    "semantic_injection_type": (
                        "frozen_turn_meaning_provider"
                    ),
                    "runtime_evidence_source": (
                        "task11-production-path-summary"
                    ),
                    "test_files": [test],
                    "fixture_files": [PRODUCTION_MATRIX_FIXTURE_PATH],
                    "case_count": 177,
                    "trajectory_count": 12,
                    "turn_count": 177,
                    "state_edge_count": 40,
                    "pre_decision_rejection_count": 1,
                },
                *[
                    {
                        "gate": (
                            f"{relative}::test_task12_surface_{index}"
                        ),
                        "claimed_scope": "unit",
                        "real_entrypoint": "direct_component_api",
                        "layers_executed": ["isolated_component"],
                        "layers_bypassed": [
                            "http_production_path",
                            "cross_layer_integration",
                        ],
                        "semantic_injection_type": (
                            "direct_value_or_component"
                        ),
                        "test_files": [relative],
                        "fixture_files": [],
                        "case_count": 0,
                        "trajectory_count": 0,
                        "turn_count": 0,
                        "state_edge_count": 0,
                    }
                    for index, relative in enumerate(
                        TASK12_TEST_PATHS,
                        start=len(TASK12_TOOL_PATHS),
                    )
                ],
            ],
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
    runtime_bundle = epoch / "runtime-browser-evidence"
    runtime_network = (
        runtime_bundle / "task11-zero-api-runtime-network.json"
    )
    _write_json(
        runtime_network,
        _runtime_network_payload(
            manifest_path,
            runtime_identity_sha256=runtime_identity_sha256,
            consumed_challenge_sha256s=(
                desktop_challenge["challenge_sha256"],
                mobile_challenge["challenge_sha256"],
            ),
        ),
    )
    production = epoch / "task11-production-path-summary.json"
    _write_json(
        production,
        _production_summary(
            manifest_path=manifest_path,
            protected_payload_sha256=payload_hash,
            cases_path=root / PRODUCTION_MATRIX_FIXTURE_PATH,
        ),
    )
    desktop = _browser_summary(
        root=runtime_bundle,
        viewport="desktop",
        runtime_identity_bytes=runtime_identity_bytes,
        challenge="2" * 64,
    )
    mobile = _browser_summary(
        root=runtime_bundle,
        viewport="mobile",
        runtime_identity_bytes=runtime_identity_bytes,
        challenge="3" * 64,
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


def _run(
    bundle: dict[str, Path],
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, object]:
    module = _audit_module()
    return module.run_independent_audit(
        repo_root=bundle["repo_root"],
        manifest_path=bundle["manifest"],
        expected_manifest_sha256=(
            sha256(bundle["manifest"].read_bytes()).hexdigest()
            if expected_manifest_sha256 is None
            else expected_manifest_sha256
        ),
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


def test_independent_audit_validates_task12_execution_tool_surface() -> None:
    hashes = _audit_module()._validate_task12_execution_tools(
        root=Path.cwd(),
        manifest=_task12_manifest(),
    )

    assert set(hashes) == {
        *TASK12_TOOL_PATHS,
        *TASK12_TEST_PATHS,
        *TASK12_FIXTURE_PATHS,
        *TASK12_RUNTIME_DATA_PATHS,
    }
    assert all(
        len(digest) == 64 for digest in hashes.values()
    )


def test_independent_browser_truth_does_not_reuse_production_card_builders(
) -> None:
    source = Path(
        "tools/guide_gates/run_task11_independent_audit.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "CanonicalProductReader",
        "CanonicalGuideCatalog",
        "load_seed_product_assets",
        "resolve_skin_match",
        "build_product_card",
        "build_category_fact_reader",
        "build_controlled_product_alias_registry",
        "build_product_display_binding_reader",
    ):
        assert forbidden not in source
    assert "project_frontend_product" in source


def test_independent_audit_rejects_catch_all_layer_scope(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    payload = json.loads(
        bundle["test_path_audit"].read_text(encoding="utf-8")
    )
    for gate in payload["gates"]:
        if gate["claimed_scope"] == "production_path_from_turn_meaning":
            continue
        gate.update({
            "claimed_scope": "layer_contract",
            "real_entrypoint": "direct_layer_boundary",
            "layers_executed": ["declared_test_layer"],
            "layers_bypassed": ["full_http_production_path"],
            "semantic_injection_type": "direct_contract_or_component",
        })
    _write_json(bundle["test_path_audit"], payload)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="catch-all",
    ):
        _run(bundle)


def test_independent_audit_rejects_incomplete_production_layer_inventory(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    payload = json.loads(
        bundle["test_path_audit"].read_text(encoding="utf-8")
    )
    production_gate = next(
        gate
        for gate in payload["gates"]
        if gate["claimed_scope"]
        == "production_path_from_turn_meaning"
    )
    production_gate["layers_executed"] = []

    _write_json(bundle["test_path_audit"], payload)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="runtime evidence source",
    ):
        _run(bundle)


def test_independent_audit_accepts_measured_production_layers(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    payload = json.loads(
        bundle["test_path_audit"].read_text(encoding="utf-8")
    )
    production_gate = next(
        gate
        for gate in payload["gates"]
        if gate["claimed_scope"]
        == "production_path_from_turn_meaning"
    )
    production_gate["layers_executed"] = [
        "translation",
        "compiler",
        "router",
        "processor",
        "reducer",
        "sqlite",
        "sse",
    ]
    _write_json(bundle["test_path_audit"], payload)

    report = _run(bundle)

    assert report["passed"] is True


def test_independent_audit_rejects_non_frozen_production_provider(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    payload = json.loads(
        bundle["test_path_audit"].read_text(encoding="utf-8")
    )
    production_gate = next(
        gate
        for gate in payload["gates"]
        if gate["claimed_scope"]
        == "production_path_from_turn_meaning"
    )
    production_gate["semantic_injection_type"] = (
        "turn_meaning_provider"
    )
    _write_json(bundle["test_path_audit"], payload)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="frozen provider",
    ):
        _run(bundle)


def test_independent_audit_requires_production_matrix_fixture_binding(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    payload = json.loads(
        bundle["test_path_audit"].read_text(encoding="utf-8")
    )
    production_gate = next(
        gate
        for gate in payload["gates"]
        if gate["claimed_scope"]
        == "production_path_from_turn_meaning"
    )
    production_gate["fixture_files"] = []
    _write_json(bundle["test_path_audit"], payload)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="production matrix fixture",
    ):
        _run(bundle)


def test_independent_architecture_rejects_processor_product_resolution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source = (
        root / "app/guide/application/text_recommendation_flow.py"
    )
    source.parent.mkdir(parents=True)
    source.write_text(
        "class TextRecommendationOrchestrator:\n"
        "    def __init__(self, product_name_resolver):\n"
        "        self._product_name_resolver = product_name_resolver\n"
        "\n"
        "    def resolve_product_resolution(self, request):\n"
        "        return request\n"
        "\n"
        "    def execute(self, execution_input):\n"
        "        return execution_input\n",
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="pre-routing product resolution",
    ):
        _audit_module()._scan_production_architecture(root)


def test_independent_architecture_rejects_parallel_image_stream(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source = root / "app/guide/application/unified_guide_flow.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "class UnifiedGuideFlow:\n"
        "    def stream(self, turn):\n"
        "        return turn\n"
        "\n"
        "    def stream_image(self, turn):\n"
        "        return turn\n",
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="parallel unified flow entrypoint",
    ):
        _audit_module()._scan_production_architecture(root)


def test_independent_architecture_rejects_presentation_mode_rederivation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source = root / "app/guide/presentation/presentation_compiler.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from app.guide.intent.responsibility_matrix import (\n"
        "    decision_for_responsibility,\n"
        ")\n"
        "\n"
        "def compile_presentation(inputs):\n"
        "    return decision_for_responsibility(\n"
        "        inputs.packet.responsibility\n"
        "    ).presentation_mode\n",
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="presentation mode rederived",
    ):
        _audit_module()._scan_production_architecture(root)


def test_independent_audit_rejects_missing_observed_runtime_layer(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = json.loads(
        bundle["production_path_summary"].read_text(encoding="utf-8")
    )
    summary["turn_traces"][0]["observed_layers"].remove("sqlite")
    _write_json(bundle["production_path_summary"], summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="observed runtime layers",
    ):
        _run(bundle)


def test_independent_audit_rejects_non_registry_processor_entry(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = json.loads(
        bundle["production_path_summary"].read_text(encoding="utf-8")
    )
    trace = summary["turn_traces"][0]
    trace["selected_processor_instance_entry_count"] = 0
    trace["unregistered_processor_invocation_count"] = 1
    _write_json(bundle["production_path_summary"], summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="processor instance",
    ):
        _run(bundle)


def test_independent_audit_requires_pre_decision_rejection_coverage(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = json.loads(
        bundle["production_path_summary"].read_text(encoding="utf-8")
    )
    summary["pre_decision_rejection_count"] = 0
    _write_json(bundle["production_path_summary"], summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="pre-decision rejection",
    ):
        _run(bundle)


def test_independent_audit_rejects_forged_scope_counts(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    payload = json.loads(
        bundle["test_path_audit"].read_text(encoding="utf-8")
    )
    payload["scope_counts"]["unit"] += 1
    _write_json(bundle["test_path_audit"], payload)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="scope counts",
    ):
        _run(bundle)


def test_independent_audit_rejects_missing_backend_runtime_data() -> None:
    manifest = _task12_manifest()
    manifest["source_paths"].remove(TASK12_RUNTIME_DATA_PATHS[0])

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="runtime data",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=Path.cwd(),
            manifest=manifest,
        )


@pytest.mark.parametrize("omitted_path", BROWSER_CANONICAL_DATA_PATHS)
def test_independent_audit_requires_each_browser_canonical_input_in_payload(
    omitted_path: str,
) -> None:
    protected_paths = set(BROWSER_CANONICAL_DATA_PATHS)
    protected_paths.remove(omitted_path)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="browser canonical data",
    ):
        _audit_module()._validate_governance_source_contracts(
            root=Path(__file__).resolve().parents[3],
            manifest={
                "tool_paths": [
                    "tools/guide_gates/"
                    "run_task11_production_path_matrix.py"
                ],
                "protected_paths": sorted(protected_paths),
            },
        )


@pytest.mark.parametrize(
    "excluded_path",
    (
        "app/static/demo.html",
        "app/static/recording-v1/",
        "a*/*",
        "[a]pp/**",
        "*",
    ),
)
def test_independent_audit_rejects_production_path_exclusion(
    tmp_path: Path,
    excluded_path: str,
) -> None:
    bundle = _bundle(tmp_path)
    manifest = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    manifest["excluded_paths"] = sorted({
        *manifest["excluded_paths"],
        excluded_path,
    })
    _write_json(bundle["manifest"], manifest)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="production path exclusion",
    ):
        _audit_module()._validate_manifest(
            root=bundle["repo_root"],
            path=bundle["manifest"],
            payload=manifest,
            raw_bytes=bundle["manifest"].read_bytes(),
            expected_manifest_sha256=sha256(
                bundle["manifest"].read_bytes()
            ).hexdigest(),
        )


def test_independent_audit_accepts_plan_bound_revision_upgrade(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    root = bundle["repo_root"]
    manifest = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    revision = "2026-08-26-task11-r13"
    plan_path = root / manifest["plan_paths"][0]
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "2026-08-26-task11-r9",
            revision,
        ),
        encoding="utf-8",
    )
    manifest["plan_revision"] = revision
    payload_hash = _payload_hash(root, manifest["protected_paths"])
    manifest["candidate_payload_sha256"] = payload_hash
    manifest["protected_payload_sha256"] = payload_hash
    _write_json(bundle["manifest"], manifest)

    actual_payload_hash, _ = _audit_module()._validate_manifest(
        root=root,
        path=bundle["manifest"],
        payload=manifest,
        raw_bytes=bundle["manifest"].read_bytes(),
        expected_manifest_sha256=sha256(
            bundle["manifest"].read_bytes()
        ).hexdigest(),
    )

    assert actual_payload_hash == payload_hash


def test_independent_audit_accepts_matching_revision_qualified_manifest(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    root = bundle["repo_root"]
    manifest = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    revision = "2026-08-26-task11-r13"
    plan_path = root / manifest["plan_paths"][0]
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "2026-08-26-task11-r9",
            revision,
        ),
        encoding="utf-8",
    )
    manifest["plan_revision"] = revision
    payload_hash = _payload_hash(root, manifest["protected_paths"])
    manifest["candidate_payload_sha256"] = payload_hash
    manifest["protected_payload_sha256"] = payload_hash
    versioned = bundle["manifest"].with_name(
        "task11-candidate-manifest-r13.json"
    )
    _write_json(versioned, manifest)

    actual_payload_hash, _ = _audit_module()._validate_manifest(
        root=root,
        path=versioned,
        payload=manifest,
        raw_bytes=versioned.read_bytes(),
        expected_manifest_sha256=sha256(
            versioned.read_bytes()
        ).hexdigest(),
    )

    assert actual_payload_hash == payload_hash


def test_independent_audit_rejects_sibling_candidate_manifest(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    manifest = json.loads(
        bundle["manifest"].read_text(encoding="utf-8")
    )
    sibling = bundle["manifest"].with_name("attacker-manifest.json")
    sibling.write_bytes(bundle["manifest"].read_bytes())

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="canonical path",
    ):
        _audit_module()._validate_manifest(
            root=bundle["repo_root"],
            path=sibling,
            payload=manifest,
            raw_bytes=sibling.read_bytes(),
            expected_manifest_sha256=sha256(
                sibling.read_bytes()
            ).hexdigest(),
        )


def test_independent_audit_rejects_symlinked_epoch_directory(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    manifest_path = bundle["manifest"]
    epoch = manifest_path.parent
    real_epoch = epoch.with_name("repair-epoch-8-real")
    epoch.rename(real_epoch)
    epoch.symlink_to(real_epoch, target_is_directory=True)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="symlink",
    ):
        _run(bundle)


def test_independent_payload_hash_rejects_symlinked_ancestor(
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
        _audit_module().Task11IndependentAuditError,
        match="protected path is invalid",
    ):
        _audit_module()._canonical_payload_hash(
            root,
            ("app/example.py",),
        )


def test_independent_payload_hash_rejects_replaced_intermediate_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _audit_module()
    root = tmp_path / "repo"
    detached = tmp_path / "detached-app"
    (root / "app").mkdir(parents=True)
    (root / "app/example.py").write_text(
        "VALUE = 'reviewed'\n",
        encoding="utf-8",
    )
    original_open = module.os.open
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

    monkeypatch.setattr(module.os, "open", replace_after_ancestor_open)

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="ancestor changed",
    ):
        module._canonical_payload_hash(
            root,
            ("app/example.py",),
        )


def test_independent_payload_hash_rejects_repository_root_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _audit_module()
    root = tmp_path / "repo"
    replaced_root = tmp_path / "replaced-repo"
    (root / "app").mkdir(parents=True)
    for name in ("first.py", "second.py"):
        (root / "app" / name).write_text(
            f"VALUE = {name!r}\n",
            encoding="utf-8",
        )
    real_read = module.os.read
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

    monkeypatch.setattr(module.os, "read", replace_after_first_read)

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="repository root changed",
    ):
        module._canonical_payload_hash(
            root,
            ("app/first.py", "app/second.py"),
        )


def test_independent_audit_hashes_the_same_bytes_it_parses(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    reviewed_bytes = bundle["manifest"].read_bytes()
    attacker = json.loads(reviewed_bytes)
    attacker["attacker_controlled"] = True

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="manifest bytes",
    ):
        _audit_module()._validate_manifest(
            root=bundle["repo_root"],
            path=bundle["manifest"],
            payload=attacker,
            raw_bytes=reviewed_bytes,
            expected_manifest_sha256=sha256(
                reviewed_bytes
            ).hexdigest(),
        )


def test_independent_audit_requires_reviewed_manifest_sha256(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    manifest = json.loads(
        bundle["manifest"].read_text(encoding="utf-8")
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="reviewed SHA-256",
    ):
        _audit_module()._validate_manifest(
            root=bundle["repo_root"],
            path=bundle["manifest"],
            payload=manifest,
            raw_bytes=bundle["manifest"].read_bytes(),
            expected_manifest_sha256="0" * 64,
        )


def test_independent_audit_cli_requires_reviewed_manifest_sha256() -> None:
    parser = _audit_module()._parser()
    arguments = [
        "--repo-root",
        ".",
        "--manifest",
        "manifest.json",
        "--semantic-summary",
        "semantic.json",
        "--zero-api-summary",
        "zero-api.json",
        "--single-path-architecture",
        "architecture.json",
        "--test-path-audit",
        "test-path.json",
        "--network-report",
        "network.json",
        "--runtime-network-report",
        "runtime-network.json",
        "--production-path-summary",
        "production.json",
        "--desktop-summary",
        "desktop.json",
        "--mobile-summary",
        "mobile.json",
        "--output",
        "audit.json",
    ]

    with pytest.raises(SystemExit):
        parser.parse_args(arguments)

    parsed = parser.parse_args([
        *arguments,
        "--expected-manifest-sha256",
        "a" * 64,
    ])

    assert parsed.expected_manifest_sha256 == "a" * 64


def test_independent_audit_top_level_rejects_wrong_reviewed_sha256(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="reviewed SHA-256",
    ):
        _run(bundle, expected_manifest_sha256="0" * 64)

    assert not bundle["output"].exists()


def test_independent_audit_rejects_unprotected_local_static_dependency(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    static_root = root / "app/static"
    static_root.mkdir(parents=True)
    (static_root / "chat.html").write_text(
        '<script src="/static/guide-demo-fixture.js"></script>\n',
        encoding="utf-8",
    )
    (static_root / "guide-demo-fixture.js").write_text(
        "window.fixture = true;\n",
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="local static dependency",
    ):
        _audit_module()._require_local_static_dependencies(
            root=root,
            protected_paths=("app/static/chat.html",),
        )


def test_independent_audit_requires_ledger_owned_retry_derivation(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    needle = (
        "        owner, repair_epoch, repair_evidence = (\n"
        "            _retry_authorization_from_verified_ledger(\n"
        "                payload,\n"
        "                plan_revision=plan_revision,\n"
        "            )\n"
        "        )\n"
    )
    assert source.count(needle) == 1
    target.write_text(
        source.replace(
            needle,
            (
                '        owner = "planned_gate"\n'
                "        repair_epoch = 0\n"
                "        repair_evidence = {}\n"
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="attempt ledger retry closure",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_requires_retry_repair_revalidation(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    needle = (
        "    _verify_retry_repair_artifacts(\n"
        "        preflight_ledger,\n"
        "        plan_revision=readiness[\"plan_revision\"],\n"
        "    )\n"
    )
    assert source.count(needle) == 1
    target.write_text(
        source.replace(
            needle,
            (
                "    accept_unverified_retry_repair(\n"
                "        preflight_ledger,\n"
                "        plan_revision=readiness[\"plan_revision\"],\n"
                "    )\n"
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="attempt ledger retry repair validation",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_requires_commit_seal_readiness_rederivation(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/build_task11_readiness.py"
    source = target.read_text(encoding="utf-8")
    needle = (
        "    candidate_readiness = verify_task11_readiness(\n"
        "        readiness_path=candidate_readiness_file,\n"
        "        ledger_path=ledger_file,\n"
        "        expected_manifest_sha256=expected_manifest_sha256,\n"
        "        expected_candidate_head=parent,\n"
        "    )\n"
    )
    assert source.count(needle) == 1
    target.write_text(
        source.replace(
            needle,
            (
                "    candidate_readiness = "
                "_read_object(candidate_readiness_file, "
                "label=\"candidate readiness\")\n"
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="commit seal readiness",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_requires_finalize_bounded_attempt_revalidation(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/build_task11_readiness.py"
    source = target.read_text(encoding="utf-8")
    needle = "    ) = _validated_bounded_attempt_artifacts(\n"
    assert source.count(needle) == 3
    target.write_text(
        source.replace(
            needle,
            "    ) = accept_bounded_attempt_artifacts(\n",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="change manifest finalization",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_requires_release_candidate_rederivation(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/build_task11_readiness.py"
    source = target.read_text(encoding="utf-8")
    needle = "    verified_candidate = verify_task11_readiness(\n"
    assert source.count(needle) == 1
    target.write_text(
        source.replace(
            needle,
            "    verified_candidate = accept_candidate_readiness(\n",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="release readiness fixture artifacts",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


@pytest.mark.parametrize(
    ("relative", "old", "new", "match"),
    [
        (
            "tools/guide_gates/run_final_real_translation.py",
            "real_translation_12x4_v5.jsonl",
            "real_translation_12x4_v4.jsonl",
            "v5",
        ),
        (
            "tools/guide_gates/replay_final_real_backend.py",
            "verify_task11_readiness(",
            "removed_readiness_verifier(",
            "readiness",
        ),
        (
            "tools/guide_gates/run_final_release_gate.py",
            'subparsers.add_parser("create-seal")',
            'subparsers.add_parser("create-seal-disabled")',
            "create-seal",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "args.require_summary_phase",
            "None",
            "parent summary",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "_validate_passed_backend_evidence(",
            "removed_backend_evidence_validation(",
            "backend evidence",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "raw_sse_events = _backend_sse_events(raw_sse_file)",
            "raw_sse_events = tuple()",
            "backend raw SSE",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "            or not _backend_sse_payloads_match(",
            "            or not accept_backend_sse_payloads(",
            "backend raw SSE",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "        validate_completed_bounded_browser_evidence(",
            "        accept_bounded_browser_evidence(",
            "bounded browser evidence",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "            proof = _request_live_runtime_proof(",
            "            proof = accept_unsigned_runtime_proof(",
            "signed runtime proof",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "            validate_runtime_bound_attempt_attestation(",
            "            accept_runtime_attestation(",
            "terminal evidence",
        ),
        (
            "tools/guide_gates/run_mainline_contract_browser_audit.py",
            "    runtime_proof = consume_runtime_bound_attempt(",
            "    runtime_proof = consume_attempt_context(",
            "bounded browser",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            "    _validate_completed_bounded_evidence(attempt_dir)",
            "    accept_completed_bounded_evidence(attempt_dir)",
            "bounded attempt artifact validation",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            "        validate_runtime_bound_attempt_attestation(",
            "        accept_runtime_attestation(",
            "bounded attempt artifact validation",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            "        and not _production_path_test_executes_runner(",
            "        and not accept_named_production_test(",
            "test path production claim",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            '"step_0_passed": step_0_passed,',
            '"step_0_passed": True,',
            "readiness completion fields",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "return _LOCK_DIRECTORY / f\"{identity}.lock\"",
            "return path.with_name(f\".{path.name}.lock\")",
            "lock",
        ),
        (
            "tools/guide_gates/run_final_real_translation.py",
            (
                "fixture_path, fixture_sha256 = "
                "validate_final_translation_fixture("
            ),
            (
                "fixture_path, fixture_sha256 = "
                "removed_fixture_validation("
            ),
            "final translation",
        ),
        (
            "tools/guide_gates/run_final_real_translation.py",
            "usage_limiter = build_provider_usage_limiter(",
            "usage_limiter = DailyUsageLimiter(",
            "provider quota",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "with _bound_ledger_path("
                "path, create_parent=True) as binding:"
            ),
            "with nullcontext() as binding:",
            "ledger path binding",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "with _bound_external_ledger_lock(path, shared=shared):",
            "with nullcontext():",
            "lock inode binding",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "os.O_RDWR | os.O_CREAT | _NO_FOLLOW | "
                "_CLOSE_ON_EXEC"
            ),
            "os.O_RDWR | os.O_CREAT | _CLOSE_ON_EXEC",
            "lock inode binding",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "root = _lock_anchor_path()",
            "root = _LOCK_DIRECTORY.parent",
            "lock inode binding",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "        _write_checkpoint_authority(\n"
                "            binding,"
            ),
            (
                "        accept_checkpoint_authority(\n"
                "            binding,"
            ),
            "checkpoint authority",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            "        verify_ledger_checkpoint_authority(\n",
            "        accept_ledger_checkpoint_authority(\n",
            "checkpoint authority",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "        verified_receipts = "
                "_verify_authorization_receipts(\n"
            ),
            (
                "        verified_receipts = "
                "accept_authorization_receipts(\n"
            ),
            "authorization receipt",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "        _write_authorization_receipt(\n"
                "            binding=binding,"
            ),
            (
                "        accept_authorization_receipt(\n"
                "            binding=binding,"
            ),
            "authorization receipt",
        ),
        pytest.param(
            "tools/guide_gates/attempt_ledger.py",
            "        if authorization_id not in verified_receipts:",
            "        if False:",
            "authorization receipt",
            id="allocation-requires-authorization-receipt",
        ),
        pytest.param(
            "tools/guide_gates/attempt_ledger.py",
            (
                "    if (\n"
                "        authorization_ids - present_authorization_ids\n"
                "        - allowed_missing_authorization_ids\n"
                "    ):"
            ),
            "    if False:",
            "authorization receipt",
            id="authorization-receipt-history-complete",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "_canonical_bytes(immutable_authorization)",
            "_canonical_bytes(authorization)",
            "authorization receipt",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            '    "created_at",\n})',
            '    "created_at",\n    "state",\n})',
            "authorization receipt",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "    _write_bound_immutable_json(\n"
                "        binding=receipt_binding,"
            ),
            (
                "    accept_bound_immutable_json(\n"
                "        binding=receipt_binding,"
            ),
            "authorization receipt",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "    _write_bound_immutable_json(\n"
                "        binding=authority_binding,"
            ),
            (
                "    accept_bound_immutable_json(\n"
                "        binding=authority_binding,"
            ),
            "checkpoint authority",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "            _write_attempt_context_witness(\n"
                "                binding=binding,"
            ),
            (
                "            accept_attempt_context_witness(\n"
                "                binding=binding,"
            ),
            "authorization receipt",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "        _write_attempt_context_witness(\n"
                "            binding=binding,"
            ),
            (
                "        accept_attempt_context_witness(\n"
                "            binding=binding,"
            ),
            "authorization receipt",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "            if witness_attempt_id is not None:\n"
                "                raise AttemptLedgerError("
            ),
            (
                "            if False:\n"
                "                raise AttemptLedgerError("
            ),
            "authorization receipt",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "    repository_root = _REPO_ROOT.resolve()",
            "    repository_root = binding.path.parent",
            "authorization receipt",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "        os.link(\n"
                "            temporary_binding.name,\n"
                "            binding.name,"
            ),
            (
                "        os.replace(\n"
                "            temporary_binding.name,\n"
                "            binding.name,"
            ),
            "immutable sidecar commit",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            (
                "        if len(current) >= len(data) "
                "or not data.startswith(current):"
            ),
            "        if False:",
            "immutable sidecar commit",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            (
                "        if not content:\n"
                "            raise Task11ReadinessError("
            ),
            (
                "        if False:\n"
                "            raise Task11ReadinessError("
            ),
            "runtime key cleanup resume",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            (
                "        if not content:\n"
                "            raise Task11ReadinessError("
            ),
            (
                "        if not content:\n"
                "            return\n"
                "        if not content:\n"
                "            raise Task11ReadinessError("
            ),
            "runtime key cleanup resume",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            (
                "            _runtime_private_key_destruction_receipt(\n"
                "                path=path,"
            ),
            (
                "            accept_private_key_destruction(\n"
                "                path=path,"
            ),
            "runtime key cleanup resume",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            (
                "        _verify_runtime_signature(\n"
                "            public_key=expected_public_key,\n"
                "            signature=signature,\n"
                "            domain="
                "_RUNTIME_PRIVATE_KEY_DESTRUCTION_SIGNATURE_DOMAIN,"
            ),
            (
                "        accept_runtime_signature(\n"
                "            public_key=expected_public_key,\n"
                "            signature=signature,\n"
                "            domain="
                "_RUNTIME_PRIVATE_KEY_DESTRUCTION_SIGNATURE_DOMAIN,"
            ),
            "runtime key cleanup resume",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            "        os.ftruncate(file_descriptor, 0)",
            "        accept_unlinked_key(file_descriptor)",
            "runtime key cleanup resume",
        ),
        pytest.param(
            "tools/guide_gates/build_task11_readiness.py",
            (
                "        canonical_payload_sha256(\n"
                "            repo_root,\n"
                "            tuple(protected_paths),\n"
                "        )"
            ),
            (
                "        accept_protected_payload(\n"
                "            repo_root,\n"
                "            tuple(protected_paths),\n"
                "        )"
            ),
            "candidate readiness publication",
            id="readiness-final-payload-revalidation",
        ),
        pytest.param(
            "tools/guide_gates/build_task11_readiness.py",
            (
                "        os.link(\n"
                "            pending_name,\n"
                "            path.name,"
            ),
            (
                "        os.replace(\n"
                "            pending_name,\n"
                "            path.name,"
            ),
            "candidate readiness publication",
            id="readiness-no-replace-commit",
        ),
        pytest.param(
            "tools/guide_gates/run_zero_api_runtime.py",
            (
                "        os.unlink(\n"
                "            canonical_path.name,\n"
                "            dir_fd=parent_descriptor,\n"
                "        )\n"
                "        os.fsync(parent_descriptor)\n"
                "        consumed = os.fstat(descriptor)\n"
                "        if (\n"
                "            consumed.st_dev != metadata.st_dev\n"
                "            or consumed.st_ino != metadata.st_ino\n"
                "            or consumed.st_nlink != 0\n"
                "        ):\n"
                "            raise ZeroApiRuntimeError(\n"
                "                \"fixture runtime private key inode changed\"\n"
                "            )\n"
                "        os.ftruncate(descriptor, 0)\n"
                "        os.fsync(descriptor)"
            ),
            (
                "        os.ftruncate(descriptor, 0)\n"
                "        os.fsync(descriptor)\n"
                "        os.unlink(\n"
                "            canonical_path.name,\n"
                "            dir_fd=parent_descriptor,\n"
                "        )\n"
                "        os.fsync(parent_descriptor)\n"
                "        consumed = os.fstat(descriptor)\n"
                "        if (\n"
                "            consumed.st_dev != metadata.st_dev\n"
                "            or consumed.st_ino != metadata.st_ino\n"
                "            or consumed.st_nlink != 0\n"
                "        ):\n"
                "            raise ZeroApiRuntimeError(\n"
                "                \"fixture runtime private key inode changed\"\n"
                "            )"
            ),
            "runtime key consumption",
            id="runtime-key-consumption-order",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            '"key_inode": key_metadata.st_ino,',
            '"key_inode": 0,',
            "runtime key cleanup resume",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            (
                "        _require_runtime_private_keys_destroyed(\n"
                "            fixture_runtime_private_key_path,"
            ),
            (
                "        accept_destroyed_runtime_private_keys(\n"
                "            fixture_runtime_private_key_path,"
            ),
            "runtime key cleanup receipt",
        ),
        (
            "tools/guide_gates/build_task11_readiness.py",
            (
                "            _verify_runtime_private_key_"
                "destruction_receipt_file(\n"
            ),
            (
                "            accept_runtime_private_key_"
                "destruction_receipt_file(\n"
            ),
            "runtime key cleanup receipt",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "        _verify_published_readiness_anchors(\n",
            "        accept_published_readiness_anchors(\n",
            "checkpoint authority",
        ),
        (
            "tools/guide_gates/attempt_ledger.py",
            "        _verify_persisted_attempt_contexts(\n",
            "        accept_persisted_attempt_contexts(\n",
            "authorization receipt",
        ),
        (
            "tools/guide_gates/run_final_release_gate.py",
            "_indexed_browser_artifacts(",
            "removed_browser_artifact_validation(",
            "aggregate evidence",
        ),
        (
            "tools/guide_gates/run_final_release_gate.py",
            "manifest = _validated_committed_evidence_manifest(",
            "manifest = removed_committed_manifest_validation(",
            "seal evidence",
        ),
        (
            "tools/guide_gates/replay_final_real_backend.py",
            "snapshot = _materialize_replay_snapshot(",
            "snapshot = removed_context_materialization(",
            "sealed context",
        ),
        (
            "tools/guide_gates/replay_final_real_backend.py",
            "expected_context=turn.case.context",
            "expected_context=SemanticContext.model_construct()",
            "sealed context",
        ),
        (
            "tools/guide_gates/replay_final_real_backend.py",
            "    raw_sse_path: str = Field(",
            "    ignored_raw_sse_path: str = Field(",
            "raw SSE",
        ),
        (
            "tools/guide_gates/replay_final_real_backend.py",
            "    image_product_ids: tuple[int, ...] = ()",
            "    ignored_image_product_ids: tuple[int, ...] = ()",
            "image",
        ),
        (
            "tools/guide_gates/run_mainline_contract_browser_audit.py",
            "        _validate_success_stream_lifecycle(events)",
            "        removed_stream_lifecycle_validation(events)",
            "stream lifecycle",
        ),
        (
            "tools/guide_gates/run_mainline_contract_browser_audit.py",
            "        _validate_stream_terminal_ownership(",
            "        removed_terminal_ownership_validation(",
            "stream lifecycle",
        ),
        (
            "tools/guide_gates/run_mainline_contract_browser_audit.py",
            "    if _capture_count(page) != expected_capture_count:",
            "    if expected_capture_count != expected_capture_count:",
            "capture count",
        ),
        (
            "tools/guide_gates/run_mainline_contract_browser_audit.py",
            "        or not _product_payloads_match_canonical(",
            "        or not accept_product_payloads(",
            "stream lifecycle",
        ),
        (
            "tools/guide_gates/run_mainline_contract_browser_audit.py",
            (
                "            project_frontend_product(card)\n"
                "            for card in typed_cards"
            ),
            (
                "            dict(card)\n"
                "            for card in typed_cards"
            ),
            "frontend product projection",
        ),
        (
            "tools/guide_gates/run_mainline_contract_browser_audit.py",
            (
                "from app.guide.application.public_event_envelope "
                "import (\n"
            ),
            "from attacker.projection import (\n",
            "frontend product projection",
        ),
        (
            "tools/guide_gates/run_final_release_gate.py",
            "_validate_sealed_release_evidence(",
            "removed_sealed_evidence_validation(",
            "seal evidence",
        ),
    ],
)
def test_independent_audit_rejects_task12_tool_mutations(
    tmp_path: Path,
    relative: str,
    old: str,
    new: str,
    match: str,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / relative
    source = target.read_text(encoding="utf-8")
    assert old in source
    target.write_text(source.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match=match,
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


@pytest.mark.parametrize(
    "call",
    (
        "_verify_persisted_attempt_contexts",
        "_verify_authorization_receipts",
    ),
    ids=("persisted-contexts", "authorization-receipts"),
)
def test_independent_audit_requires_allocation_authority_revalidation(
    tmp_path: Path,
    call: str,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    prefix, allocation = source.split("def allocate_attempt(", 1)
    needle = f"        {call}("
    if call == "_verify_authorization_receipts":
        needle = f"        verified_receipts = {call}("
    assert needle in allocation
    allocation = allocation.replace(
        needle,
        needle.replace(call, f"accept_{call.removeprefix('_')}"),
        1,
    )
    target.write_text(
        prefix + "def allocate_attempt(" + allocation,
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="authorization receipt",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


@pytest.mark.parametrize(
    ("replacement", "match"),
    [
        (
            (
                "    if False:\n"
                "        verify_task11_readiness(\n"
            ),
            "readiness",
        ),
        (
            (
                "    verify_task11_readiness = lambda **_: {}\n"
                "    verify_task11_readiness(\n"
            ),
            "readiness",
        ),
    ],
)
def test_independent_audit_rejects_dead_or_shadowed_readiness_call(
    tmp_path: Path,
    replacement: str,
    match: str,
) -> None:
    _copy_task12_files(tmp_path)
    target = (
        tmp_path / "tools/guide_gates/run_final_real_translation.py"
    )
    source = target.read_text(encoding="utf-8")
    needle = "    verify_task11_readiness(\n"
    assert source.count(needle) == 1
    target.write_text(
        source.replace(needle, replacement, 1),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match=match,
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_rejects_module_level_shadowed_call(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = (
        tmp_path / "tools/guide_gates/run_final_real_translation.py"
    )
    source = target.read_text(encoding="utf-8")
    needle = "def run_authorized_final_translation(\n"
    assert source.count(needle) == 1
    target.write_text(
        source.replace(
            needle,
            (
                "verify_task11_readiness = lambda **_: {}\n\n\n"
                + needle
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="readiness",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_rejects_conditionally_shadowed_call(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = (
        tmp_path / "tools/guide_gates/run_final_real_translation.py"
    )
    source = target.read_text(encoding="utf-8")
    needle = "def run_authorized_final_translation(\n"
    assert source.count(needle) == 1
    target.write_text(
        source.replace(
            needle,
            (
                "if True:\n"
                "    verify_task11_readiness = lambda **_: {}\n\n\n"
                + needle
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="readiness",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_rejects_nonlauncher_runtime_registration(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/run_final_release_gate.py"
    with target.open("a", encoding="utf-8") as stream:
        stream.write(
            "\nfrom tools.guide_gates.attempt_ledger import (\n"
            "    register_runtime_bound_attempt as register_runtime,\n"
            ")\n\n"
            "def start_unbound_runtime():\n"
            "    return register_runtime()\n"
        )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="runtime registration owner",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


@pytest.mark.parametrize("condition", ("False", "1 == 0"))
def test_independent_audit_rejects_dead_bounded_evidence_validation(
    tmp_path: Path,
    condition: str,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    needle = (
        "        validate_completed_bounded_browser_evidence(\n"
    )
    assert source.count(needle) == 1
    target.write_text(
        source.replace(
            needle,
            (
                f"        if {condition}:\n"
                "            "
                "validate_completed_bounded_browser_evidence(\n"
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="bounded browser evidence",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_rejects_type_checking_only_validation(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    typing_import = "from typing import Any, Literal\n"
    call = "        validate_completed_bounded_browser_evidence(\n"
    assert source.count(typing_import) == 1
    assert source.count(call) == 1
    target.write_text(
        source.replace(
            typing_import,
            "from typing import Any, Literal, TYPE_CHECKING\n",
            1,
        ).replace(
            call,
            (
                "        if TYPE_CHECKING:\n"
                "            "
                "validate_completed_bounded_browser_evidence(\n"
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="bounded browser evidence",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_rejects_call_after_true_return(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    call = "        validate_completed_bounded_browser_evidence(\n"
    assert source.count(call) == 1
    target.write_text(
        source.replace(
            call,
            (
                "        if True:\n"
                "            return\n"
                + call
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="bounded browser evidence",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


@pytest.mark.parametrize(
    ("module_import", "condition"),
    (
        ("import typing\n", "typing.TYPE_CHECKING"),
        ("import typing as typing_alias\n", "typing_alias.TYPE_CHECKING"),
    ),
)
def test_independent_audit_rejects_qualified_type_checking_validation(
    tmp_path: Path,
    module_import: str,
    condition: str,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    typing_import = "from typing import Any, Literal\n"
    call = "        validate_completed_bounded_browser_evidence(\n"
    assert source.count(typing_import) == 1
    assert source.count(call) == 1
    target.write_text(
        source.replace(
            typing_import,
            module_import + typing_import,
            1,
        ).replace(
            call,
            (
                f"        if {condition}:\n"
                "            "
                "validate_completed_bounded_browser_evidence(\n"
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="bounded browser evidence",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


@pytest.mark.parametrize(
    "shadow",
    (
        (
            "        try:\n"
            "            pass\n"
            "        except Exception as "
            "validate_completed_bounded_browser_evidence:\n"
            "            pass\n"
        ),
        (
            "        match None:\n"
            "            case "
            "validate_completed_bounded_browser_evidence:\n"
            "                pass\n"
        ),
    ),
)
def test_independent_audit_rejects_non_name_store_shadowing(
    tmp_path: Path,
    shadow: str,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    call = "        validate_completed_bounded_browser_evidence(\n"
    assert source.count(call) == 1
    target.write_text(
        source.replace(call, shadow + call, 1),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="bounded browser evidence",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_rejects_conditionally_executed_bounded_validation(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    call = "        validate_completed_bounded_browser_evidence(\n"
    assert source.count(call) == 1
    target.write_text(
        source.replace(
            call,
            (
                "        if output_directory:\n"
                "            "
                "validate_completed_bounded_browser_evidence(\n"
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="bounded browser evidence",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_rejects_wrong_bounded_validation_path(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    call = (
        "        validate_completed_bounded_browser_evidence(\n"
        "            Path(str(output_directory))\n"
        "        )\n"
    )
    assert source.count(call) == 1
    target.write_text(
        source.replace(
            call,
            (
                "        validate_completed_bounded_browser_evidence(\n"
                '            Path("/tmp/forged-evidence")\n'
                "        )\n"
            ),
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="bounded browser evidence",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
        )


def test_independent_audit_rejects_dead_parent_summary_forwarding(
    tmp_path: Path,
) -> None:
    _copy_task12_files(tmp_path)
    target = tmp_path / "tools/guide_gates/attempt_ledger.py"
    source = target.read_text(encoding="utf-8")
    live = (
        "                require_summary_phase=(\n"
        "                    args.require_summary_phase\n"
        "                    if args.command == \"allocate-child\"\n"
        "                    else None\n"
        "                ),\n"
        "                require_summary_result=(\n"
        "                    args.require_summary_result\n"
        "                    if args.command == \"allocate-child\"\n"
        "                    else None\n"
        "                ),\n"
    )
    dead = live.replace(
        'args.command == "allocate-child"',
        "False",
    )
    assert source.count(live) == 1
    target.write_text(
        source.replace(live, dead, 1),
        encoding="utf-8",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="parent summary",
    ):
        _audit_module()._validate_task12_execution_tools(
            root=tmp_path,
            manifest=_task12_manifest(),
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
    assert report["plan_revision"] == "2026-08-26-task11-r9"
    assert report["repair_epoch"] == 8
    assert report["finding_count"] == 0
    assert report["p0_finding_count"] == 0
    assert report["p1_finding_count"] == 0
    assert report["checks"]["task12_execution_tools"] is True
    assert report["checks"]["bounded_trajectory_messages"] is True
    assert set(report["task12_execution_tool_sha256"]) == {
        *TASK12_TOOL_PATHS,
        *TASK12_TEST_PATHS,
        *TASK12_FIXTURE_PATHS,
        *TASK12_RUNTIME_DATA_PATHS,
    }
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


def test_independent_audit_rejects_input_replacement_after_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    module = _audit_module()
    original = module._validate_semantic_summary

    def validate_then_replace(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)
        payload = json.loads(
            bundle["semantic_summary"].read_text(encoding="utf-8")
        )
        payload["replacement_after_validation"] = True
        _write_json(bundle["semantic_summary"], payload)

    monkeypatch.setattr(
        module,
        "_validate_semantic_summary",
        validate_then_replace,
    )

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="changed during independent audit",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_rejects_production_summary_from_other_candidate(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    production = json.loads(
        bundle["production_path_summary"].read_text(encoding="utf-8")
    )
    production.update({
        "candidate_manifest_sha256": "f" * 64,
        "protected_payload_sha256": "e" * 64,
        "cases_sha256": "d" * 64,
    })
    _write_json(bundle["production_path_summary"], production)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="candidate binding",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_rejects_forged_test_node_inventory(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    audit = json.loads(
        bundle["test_path_audit"].read_text(encoding="utf-8")
    )
    audit["gates"][0]["gate"] = (
        "tests/guide/test_service.py::test_forged"
    )
    _write_json(bundle["test_path_audit"], audit)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="pytest node inventory",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_accepts_protected_plan_level_fixture(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    audit = json.loads(
        bundle["test_path_audit"].read_text(encoding="utf-8")
    )
    manifest = json.loads(
        bundle["manifest"].read_text(encoding="utf-8")
    )
    audit["fixture_dependencies"] = manifest["fixture_paths"]
    _write_json(bundle["test_path_audit"], audit)

    collected_count = _audit_module()._validate_test_path(
        audit,
        root=bundle["repo_root"],
        manifest=manifest,
    )

    assert collected_count == 1 + len(TASK12_TEST_PATHS)


def test_independent_fixture_discovery_resolves_module_path_constants(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    test_path = root / "tests/guide/test_fixture_reader.py"
    fixture = root / "tests/fixtures/guide/data/case.json"
    test_path.parent.mkdir(parents=True)
    fixture.parent.mkdir(parents=True)
    test_path.write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "FIXTURE_ROOT = (",
                "    Path(__file__).resolve().parents[2]",
                "    / 'fixtures'",
                "    / 'guide'",
                "    / 'data'",
                ")",
                "CASE_PATH = FIXTURE_ROOT / 'case.json'",
                "",
            )
        ),
        encoding="utf-8",
    )
    fixture.write_text("{}\n", encoding="utf-8")

    assert _audit_module()._discover_test_fixture_dependencies(
        test_path,
        repo_root=root,
    ) == ("tests/fixtures/guide/data/case.json",)


def test_independent_runner_call_must_be_unconditional(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "tests/guide/test_matrix.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "import os\n"
        "from tools.guide_gates.run_task11_production_path_matrix "
        "import run_production_path_matrix\n\n"
        "def test_matrix():\n"
        "    if os.getenv('RUN_MATRIX'):\n"
        "        run_production_path_matrix()\n",
        encoding="utf-8",
    )

    assert not _audit_module()._production_gate_calls_runner(
        tmp_path,
        "tests/guide/test_matrix.py::test_matrix",
    )


def test_independent_runner_call_must_precede_unconditional_return(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "tests/guide/test_matrix.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from tools.guide_gates.run_task11_production_path_matrix "
        "import run_production_path_matrix\n\n"
        "def test_matrix():\n"
        "    return\n"
        "    run_production_path_matrix()\n",
        encoding="utf-8",
    )

    assert not _audit_module()._production_gate_calls_runner(
        tmp_path,
        "tests/guide/test_matrix.py::test_matrix",
    )


def test_independent_runner_call_rejects_preceding_failing_assert(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "tests/guide/test_matrix.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from tools.guide_gates.run_task11_production_path_matrix "
        "import run_production_path_matrix\n\n"
        "def test_matrix():\n"
        "    assert False\n"
        "    summary = run_production_path_matrix()\n"
        "    assert summary.passed is True\n",
        encoding="utf-8",
    )

    assert not _audit_module()._production_gate_calls_runner(
        tmp_path,
        "tests/guide/test_matrix.py::test_matrix",
    )


def test_independent_runner_call_requires_reachable_pass_assertion(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "tests/guide/test_matrix.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from tools.guide_gates.run_task11_production_path_matrix "
        "import run_production_path_matrix\n\n"
        "def test_matrix():\n"
        "    summary = run_production_path_matrix()\n"
        "    return\n"
        "    assert summary.passed is True\n",
        encoding="utf-8",
    )

    assert not _audit_module()._production_gate_calls_runner(
        tmp_path,
        "tests/guide/test_matrix.py::test_matrix",
    )


def test_independent_runner_call_rejects_nested_result_rebinding(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "tests/guide/test_matrix.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from tools.guide_gates.run_task11_production_path_matrix "
        "import run_production_path_matrix\n\n"
        "def test_matrix():\n"
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
        "    assert summary.passed is True\n",
        encoding="utf-8",
    )

    assert not _audit_module()._production_gate_calls_runner(
        tmp_path,
        "tests/guide/test_matrix.py::test_matrix",
    )


def test_independent_runner_call_rejects_nested_second_call(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "tests/guide/test_matrix.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from tools.guide_gates.run_task11_production_path_matrix "
        "import run_production_path_matrix\n\n"
        "def test_matrix():\n"
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
        "    assert summary.passed is True\n",
        encoding="utf-8",
    )

    assert not _audit_module()._production_gate_calls_runner(
        tmp_path,
        "tests/guide/test_matrix.py::test_matrix",
    )


def test_independent_runner_call_rejects_call_after_terminating_try(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "tests/guide/test_matrix.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from tools.guide_gates.run_task11_production_path_matrix "
        "import run_production_path_matrix\n\n"
        "def test_matrix():\n"
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
        "    assert summary.passed is True\n",
        encoding="utf-8",
    )

    assert not _audit_module()._production_gate_calls_runner(
        tmp_path,
        "tests/guide/test_matrix.py::test_matrix",
    )


def test_independent_runner_call_rejects_call_after_infinite_loop(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "tests/guide/test_matrix.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from tools.guide_gates.run_task11_production_path_matrix "
        "import run_production_path_matrix\n\n"
        "def test_matrix():\n"
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
        "    assert summary.passed is True\n",
        encoding="utf-8",
    )

    assert not _audit_module()._production_gate_calls_runner(
        tmp_path,
        "tests/guide/test_matrix.py::test_matrix",
    )


def test_independent_runner_call_rejects_impure_extra_assertion(
    tmp_path: Path,
) -> None:
    test_path = tmp_path / "tests/guide/test_matrix.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "from tools.guide_gates.run_task11_production_path_matrix "
        "import run_production_path_matrix\n\n"
        "def test_matrix():\n"
        "    summary = run_production_path_matrix(\n"
        "        repo_root=REPO_ROOT,\n"
        "        cases_path=CASES,\n"
        "        state_root=STATE_ROOT,\n"
        "        candidate_manifest_sha256='a' * 64,\n"
        "        protected_payload_sha256='b' * 64,\n"
        "        cases_sha256='c' * 64,\n"
        "    )\n"
        "    assert mutate(summary)\n"
        "    assert summary.passed is True\n",
        encoding="utf-8",
    )

    assert not _audit_module()._production_gate_calls_runner(
        tmp_path,
        "tests/guide/test_matrix.py::test_matrix",
    )


def test_independent_audit_rejects_trace_that_disagrees_with_matrix(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = json.loads(
        bundle["production_path_summary"].read_text(encoding="utf-8")
    )
    trace = summary["turn_traces"][0]
    trace["selected_processor"] = "forged"
    trace["actual_processor"] = "forged"
    trace["processor_invocation_counts"] = {"forged": 1}
    _write_json(bundle["production_path_summary"], summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="matrix expectation",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_rejects_reassigned_per_case_coverage(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = json.loads(
        bundle["production_path_summary"].read_text(encoding="utf-8")
    )
    first = summary["turn_traces"][120]
    second = summary["turn_traces"][121]
    first["coverage_edges"], second["coverage_edges"] = (
        second["coverage_edges"],
        first["coverage_edges"],
    )
    _write_json(bundle["production_path_summary"], summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="matrix expectation",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_requires_matrix_edge_inventory(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = json.loads(
        bundle["production_path_summary"].read_text(encoding="utf-8")
    )
    summary.pop("required_state_edges")
    _write_json(bundle["production_path_summary"], summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="required state edge inventory",
    ):
        _run(bundle)


@pytest.mark.parametrize(
    "mutation",
    (
        {"cases_sha256": "f" * 64},
        {"fit_count": 3, "explore_count": 29},
    ),
)
def test_independent_audit_rejects_self_authored_semantic_summary(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    bundle = _bundle(tmp_path)
    semantic = json.loads(
        bundle["semantic_summary"].read_text(encoding="utf-8")
    )
    semantic.update(mutation)
    _write_json(bundle["semantic_summary"], semantic)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="semantic summary",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def _reindex_browser_summary(summary_path: Path) -> None:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    sandbox_path = summary_path.parent / "sandbox-audit.json"
    summary["sandbox_audit_sha256"] = sha256(
        sandbox_path.read_bytes()
    ).hexdigest()
    summary["artifact_sha256"] = {
        path.relative_to(summary_path.parent).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(summary_path.parent.rglob("*"))
        if path.is_file() and path != summary_path
    }
    _write_json(summary_path, summary)


def _reindex_browser_seatbelt(
    summary_path: Path,
    *,
    events: list[dict[str, object]],
) -> dict[str, object]:
    root = summary_path.parent
    raw = b"".join(
        (
            json.dumps(event, ensure_ascii=True, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        for event in events
    )
    raw_path = root / "seatbelt.raw.ndjson"
    raw_path.write_bytes(raw)
    sandbox_path = root / "sandbox-audit.json"
    sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
    sandbox["seatbelt_raw_ndjson_sha256"] = sha256(raw).hexdigest()
    sandbox["seatbelt_raw_byte_count"] = len(raw)
    sandbox["seatbelt_event_count"] = len(events)
    for denial in sandbox["canary_denials"]:
        denial["line_number"] = next(
            index
            for index, event in enumerate(events, start=1)
            if (
                event.get("processImagePath") == "/kernel"
                and f"({denial['pid']})" in str(event.get("eventMessage"))
                and f"remote:*:{denial['port']}" in str(
                    event.get("eventMessage")
                )
            )
        )
    _write_json(sandbox_path, sandbox)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["seatbelt_raw_ndjson_sha256"] = sha256(raw).hexdigest()
    _write_json(summary_path, summary)
    _reindex_browser_summary(summary_path)
    return json.loads(summary_path.read_text(encoding="utf-8"))


def test_independent_browser_audit_rejects_marker_before_kernel_identity(
    tmp_path: Path,
) -> None:
    summary_path = _browser_summary(
        root=tmp_path,
        viewport="desktop",
        challenge_digest="2" * 64,
    )
    raw_path = summary_path.parent / "seatbelt.raw.ndjson"
    events = [
        json.loads(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    root_denial_index = next(
        index
        for index, event in enumerate(events)
        if "network-outbound remote:*:9" in str(event.get("eventMessage"))
    )
    root_marker_index = next(
        index
        for index, event in enumerate(events)
        if ":root_child:" in str(event.get("eventMessage"))
    )
    events[root_denial_index], events[root_marker_index] = (
        events[root_marker_index],
        events[root_denial_index],
    )
    summary = _reindex_browser_seatbelt(
        summary_path,
        events=events,
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="canary delivery order",
    ):
        _audit_module()._validate_seatbelt_audit(
            root=summary_path.parent,
            summary=summary,
            label="desktop browser summary",
        )


def test_independent_browser_audit_accepts_fixed_chromium_probe(
    tmp_path: Path,
) -> None:
    summary_path = _browser_summary(
        root=tmp_path,
        viewport="desktop",
        challenge_digest="2" * 64,
    )
    root = summary_path.parent
    netlog_path = root / "chromium-netlog.json"
    netlog = json.loads(netlog_path.read_text(encoding="utf-8"))
    netlog["events"].append({
        "type": 94,
        "params": {"address": "[2001:4860:4860::8888]:443"},
    })
    _write_json(netlog_path, netlog)
    raw_path = root / "seatbelt.raw.ndjson"
    events = [
        json.loads(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    end_index = next(
        index
        for index, event in enumerate(events)
        if str(event.get("eventMessage", "")).startswith(
            "XIAORO_SEATBELT_END:"
        )
    )
    events.insert(
        end_index,
        {
            "eventType": "logEvent",
            "eventMessage": (
                "Sandbox: chrome-headless-shell(4999) deny(1) "
                "network-outbound remote:*:443\n"
                + "d" * 64
            ),
            "processImagePath": "/kernel",
            "senderImagePath": (
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            ),
        },
    )
    summary = _reindex_browser_seatbelt(
        summary_path,
        events=events,
    )
    sandbox_path = root / "sandbox-audit.json"
    sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
    sandbox["netlog_sha256"] = sha256(netlog_path.read_bytes()).hexdigest()
    sandbox["blocked_environmental_probe_count"] = 1
    sandbox["blocked_environmental_probe_duplicate_count"] = 0
    sandbox["blocked_environmental_probe_targets"] = [
        "[2001:4860:4860::8888]:443"
    ]
    _write_json(sandbox_path, sandbox)
    _reindex_browser_summary(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    _audit_module()._validate_seatbelt_audit(
        root=root,
        summary=summary,
        label="desktop browser summary",
    )
    _audit_module()._validate_chromium_netlog(
        netlog_path,
        label="desktop browser summary",
        allowed_non_loopback_targets=frozenset({
            "[2001:4860:4860::8888]:443"
        }),
    )


def test_independent_browser_audit_rejects_probe_without_kernel_denial(
    tmp_path: Path,
) -> None:
    summary_path = _browser_summary(
        root=tmp_path,
        viewport="desktop",
        challenge_digest="2" * 64,
    )
    root = summary_path.parent
    netlog_path = root / "chromium-netlog.json"
    netlog = json.loads(netlog_path.read_text(encoding="utf-8"))
    netlog["events"].append({
        "type": 94,
        "params": {"address": "[2001:4860:4860::8888]:443"},
    })
    _write_json(netlog_path, netlog)
    sandbox_path = root / "sandbox-audit.json"
    sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
    sandbox["netlog_sha256"] = sha256(netlog_path.read_bytes()).hexdigest()
    _write_json(sandbox_path, sandbox)
    _reindex_browser_summary(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="canary evidence",
    ):
        _audit_module()._validate_seatbelt_audit(
            root=root,
            summary=summary,
            label="desktop browser summary",
        )


def test_independent_browser_audit_rejects_probe_denial_after_end(
    tmp_path: Path,
) -> None:
    summary_path = _browser_summary(
        root=tmp_path,
        viewport="desktop",
        challenge_digest="2" * 64,
    )
    root = summary_path.parent
    netlog_path = root / "chromium-netlog.json"
    netlog = json.loads(netlog_path.read_text(encoding="utf-8"))
    netlog["events"].append({
        "type": 94,
        "params": {"address": "[2001:4860:4860::8888]:443"},
    })
    _write_json(netlog_path, netlog)
    raw_path = root / "seatbelt.raw.ndjson"
    events = [
        json.loads(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    end_index = next(
        index
        for index, event in enumerate(events)
        if str(event.get("eventMessage", "")).startswith(
            "XIAORO_SEATBELT_END:"
        )
    )
    events.insert(
        end_index + 1,
        {
            "eventType": "logEvent",
            "eventMessage": (
                "Sandbox: chrome-headless-shell(4999) deny(1) "
                "network-outbound remote:*:443\n"
                + "d" * 64
            ),
            "processImagePath": "/kernel",
            "senderImagePath": (
                "/System/Library/Extensions/Sandbox.kext/"
                "Contents/MacOS/Sandbox"
            ),
        },
    )
    summary = _reindex_browser_seatbelt(
        summary_path,
        events=events,
    )
    sandbox_path = root / "sandbox-audit.json"
    sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
    sandbox["netlog_sha256"] = sha256(netlog_path.read_bytes()).hexdigest()
    sandbox["blocked_environmental_probe_count"] = 1
    sandbox["blocked_environmental_probe_duplicate_count"] = 0
    sandbox["blocked_environmental_probe_targets"] = [
        "[2001:4860:4860::8888]:443"
    ]
    _write_json(sandbox_path, sandbox)
    _reindex_browser_summary(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="probe denial order",
    ):
        _audit_module()._validate_seatbelt_audit(
            root=root,
            summary=summary,
            label="desktop browser summary",
        )


def test_independent_browser_marker_ownership_is_ast_verified(
    tmp_path: Path,
) -> None:
    module = _audit_module()
    module._validate_fixture_marker_ownership(Path.cwd())
    source = (
        Path("tools/guide_gates/run_mainline_contract_browser_audit.py")
        .read_text(encoding="utf-8")
    )
    mutated = source.replace(
        "def _run_seatbelt_canary_child(\n",
        "def _forged_marker_bridge() -> None:\n"
        '    _emit_seatbelt_marker("forged")\n\n\n'
        "def _run_seatbelt_canary_child(\n",
        1,
    ).replace(
        "    os.execv(\n        \"/usr/bin/nc\",",
        "    _forged_marker_bridge()\n"
        "    os.execv(\n        \"/usr/bin/nc\",",
        1,
    )
    assert mutated != source
    mutated_root = tmp_path / "repository"
    mutated_path = (
        mutated_root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    mutated_path.parent.mkdir(parents=True)
    mutated_path.write_text(mutated, encoding="utf-8")

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="short-lived canary emits a marker",
    ):
        module._validate_fixture_marker_ownership(mutated_root)


def test_independent_browser_marker_ownership_rejects_local_callable_alias(
    tmp_path: Path,
) -> None:
    module = _audit_module()
    source = (
        Path("tools/guide_gates/run_mainline_contract_browser_audit.py")
        .read_text(encoding="utf-8")
    )
    needle = '    os.execv(\n        "/usr/bin/nc",'
    assert source.count(needle) == 1
    mutated = source.replace(
        needle,
        "    marker = _emit_seatbelt_marker\n"
        '    marker("forged")\n'
        + needle,
        1,
    )
    mutated_root = tmp_path / "repository"
    mutated_path = (
        mutated_root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    mutated_path.parent.mkdir(parents=True)
    mutated_path.write_text(mutated, encoding="utf-8")

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="short-lived canary emits a marker",
    ):
        module._validate_fixture_marker_ownership(mutated_root)


def test_independent_browser_marker_ownership_uses_reaching_alias_definition(
    tmp_path: Path,
) -> None:
    module = _audit_module()
    source = (
        Path("tools/guide_gates/run_mainline_contract_browser_audit.py")
        .read_text(encoding="utf-8")
    )
    ready = "            _emit_seatbelt_marker(ready_marker)\n"
    begin = (
        "        _emit_seatbelt_marker(\n"
        '            f"{_SEATBELT_BEGIN_PREFIX}:'
        '{measurement_nonce}:{child_pid}"\n'
        "        )\n"
    )
    assert source.count(ready) == 1
    assert source.count(begin) == 1
    mutated = source.replace(
        ready,
        "            marker = _emit_seatbelt_marker\n"
        "            marker = lambda *_: None\n"
        "            marker(ready_marker)\n",
        1,
    ).replace(
        begin,
        "        marker(\n"
        '            f"{_SEATBELT_BEGIN_PREFIX}:'
        '{measurement_nonce}:{child_pid}"\n'
        "        )\n",
        1,
    )
    mutated_root = tmp_path / "repository"
    mutated_path = (
        mutated_root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    mutated_path.parent.mkdir(parents=True)
    mutated_path.write_text(mutated, encoding="utf-8")

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="parent-owned marker capture",
    ):
        module._validate_fixture_marker_ownership(mutated_root)


def test_independent_browser_marker_ownership_resolves_module_callable_alias(
    tmp_path: Path,
) -> None:
    module = _audit_module()
    source = (
        Path("tools/guide_gates/run_mainline_contract_browser_audit.py")
        .read_text(encoding="utf-8")
    )
    definition = "def _run_seatbelt_canary_child(\n"
    call = '    os.execv(\n        "/usr/bin/nc",'
    assert source.count(definition) == 1
    assert source.count(call) == 1
    mutated = source.replace(
        definition,
        "marker_alias = _emit_seatbelt_marker\n\n\n" + definition,
        1,
    ).replace(
        call,
        '    marker_alias("forged")\n' + call,
        1,
    )
    mutated_root = tmp_path / "repository"
    mutated_path = (
        mutated_root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    mutated_path.parent.mkdir(parents=True)
    mutated_path.write_text(mutated, encoding="utf-8")

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="short-lived canary emits a marker",
    ):
        module._validate_fixture_marker_ownership(mutated_root)


def test_independent_browser_marker_ownership_rejects_dead_calls(
    tmp_path: Path,
) -> None:
    module = _audit_module()
    source = (
        Path("tools/guide_gates/run_mainline_contract_browser_audit.py")
        .read_text(encoding="utf-8")
    )
    needle = "        on_started(canary.pid)\n"
    assert source.count(needle) == 1
    mutated = source.replace(
        needle,
        "        return canary.pid\n" + needle,
        1,
    )
    mutated_root = tmp_path / "repository"
    mutated_path = (
        mutated_root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    mutated_path.parent.mkdir(parents=True)
    mutated_path.write_text(mutated, encoding="utf-8")

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="drain marker",
    ):
        module._validate_fixture_marker_ownership(mutated_root)


def test_independent_browser_marker_ownership_rejects_empty_loop_calls(
    tmp_path: Path,
) -> None:
    module = _audit_module()
    source = (
        Path("tools/guide_gates/run_mainline_contract_browser_audit.py")
        .read_text(encoding="utf-8")
    )
    needle = "        on_started(canary.pid)\n"
    assert source.count(needle) == 1
    mutated = source.replace(
        needle,
        "        for _ in ():\n            on_started(canary.pid)\n",
        1,
    )
    mutated_root = tmp_path / "repository"
    mutated_path = (
        mutated_root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    mutated_path.parent.mkdir(parents=True)
    mutated_path.write_text(mutated, encoding="utf-8")

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="drain marker",
    ):
        module._validate_fixture_marker_ownership(mutated_root)


def test_independent_browser_marker_ownership_rejects_shadowed_calls(
    tmp_path: Path,
) -> None:
    module = _audit_module()
    source = (
        Path("tools/guide_gates/run_mainline_contract_browser_audit.py")
        .read_text(encoding="utf-8")
    )
    needle = "    log_process = subprocess.Popen(\n"
    assert source.count(needle) == 1
    mutated = source.replace(
        needle,
        "    _emit_seatbelt_marker = lambda *_: None\n" + needle,
        1,
    )
    mutated_root = tmp_path / "repository"
    mutated_path = (
        mutated_root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    mutated_path.parent.mkdir(parents=True)
    mutated_path.write_text(mutated, encoding="utf-8")

    with pytest.raises(
        module.Task11IndependentAuditError,
        match="parent-owned marker capture",
    ):
        module._validate_fixture_marker_ownership(mutated_root)


def test_executable_call_nodes_ignore_empty_comprehensions() -> None:
    module = _audit_module()
    tree = ast.parse(
        "def probe():\n"
        "    return [required_call() for _ in ()]\n"
    )
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    )

    names = {
        module._call_name(call)
        for call in module._executable_call_nodes(
            function,
            include_local_names=True,
        )
    }

    assert "required_call" not in names


def test_independent_audit_rejects_reindexed_dom_drift(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = bundle["desktop_summary"]
    dom_path = summary.parent / FIXTURE_TURNS[0] / "terminal-dom.json"
    dom = json.loads(dom_path.read_text(encoding="utf-8"))
    dom["visible_product_ids"] = [999]
    _write_json(dom_path, dom)
    _reindex_browser_summary(summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="DOM visible product IDs",
    ):
        _run(bundle)


def test_independent_audit_rejects_image_fit_without_fit_contract(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = bundle["desktop_summary"]
    turn_dir = summary.parent / "fixture-image-fit-recommendation"
    contract = {
        "terminal_kind": "presentation",
        "responsibility": "recommendation",
        "mode": "recommendation",
        "recommendation_mode": None,
        "sections": [],
        "visible_product_ids": [],
    }
    _write_json(turn_dir / "presentation-contract.json", contract)
    blocks = []
    for block in (
        turn_dir / "stream.sse"
    ).read_text(encoding="utf-8").split("\n\n"):
        if block.startswith("event: presentation_contract\n"):
            blocks.append(
                "event: presentation_contract\n"
                f"data: {json.dumps(contract, sort_keys=True)}"
            )
        elif block:
            blocks.append(block)
    (turn_dir / "stream.sse").write_text(
        "\n\n".join(blocks) + "\n\n",
        encoding="utf-8",
    )
    dom = json.loads(
        (turn_dir / "terminal-dom.json").read_text(encoding="utf-8")
    )
    dom.update({
        "presentation_mode": "recommendation",
        "visible_section_kinds": [],
        "section_blocks": [],
        "inline_product_ids": [],
        "visible_product_ids": [],
        "shelf_product_ids": [],
        "comparison_table_count": 0,
    })
    _write_json(turn_dir / "terminal-dom.json", dom)
    _reindex_browser_summary(summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="image-fit",
    ):
        _run(bundle)


def test_independent_audit_rejects_invalid_png_structure(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = bundle["desktop_summary"]
    screenshot = summary.parent / FIXTURE_TURNS[0] / "screenshot.png"
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")
    _reindex_browser_summary(summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="PNG",
    ):
        _run(bundle)


def test_independent_audit_rejects_crc_valid_undecodable_png(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = bundle["desktop_summary"]
    screenshot = summary.parent / FIXTURE_TURNS[0] / "screenshot.png"
    screenshot.write_bytes(
        _png_bytes(1440, 1000, idat_override=b"forged")
    )
    _reindex_browser_summary(summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="PNG",
    ):
        _run(bundle)


def test_independent_png_validator_decodes_filters_zero_through_four(
    tmp_path: Path,
) -> None:
    screenshot = tmp_path / "screenshot.png"
    screenshot.write_bytes(_png_bytes(1440, 1000))

    _audit_module()._validate_png(
        screenshot,
        viewport="desktop",
        label="test screenshot",
    )


@pytest.mark.parametrize(
    ("solid_color", "nearly_blank"),
    (
        ((255, 255, 255), False),
        ((24, 96, 160), False),
        (None, True),
    ),
)
def test_independent_png_validator_rejects_empty_visual_content(
    tmp_path: Path,
    solid_color: tuple[int, int, int] | None,
    nearly_blank: bool,
) -> None:
    screenshot = tmp_path / "screenshot.png"
    screenshot.write_bytes(
        _png_bytes(
            1440,
            1000,
            solid_color=solid_color,
            nearly_blank=nearly_blank,
        )
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="visual content",
    ):
        _audit_module()._validate_png(
            screenshot,
            viewport="desktop",
            label="test screenshot",
        )


def test_independent_browser_requests_reject_unknown_resource_type(
    tmp_path: Path,
) -> None:
    path = tmp_path / "browser-requests.json"
    _write_json(
        path,
        [
            {
                "url": "http://127.0.0.1:8820/api/v1/chat/stream",
                "method": "POST",
                "resource_type": "caller_authored_pass",
            }
            for _ in FIXTURE_TURNS
        ],
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="resource type",
    ):
        _audit_module()._validate_browser_requests(
            path,
            declared_count=len(FIXTURE_TURNS),
            label="test browser",
        )


def test_independent_stream_post_cannot_evade_netlog_binding_as_document(
    tmp_path: Path,
) -> None:
    requests_path = tmp_path / "browser-requests.json"
    netlog_path = tmp_path / "chromium-netlog.json"
    _write_json(
        requests_path,
        [
            {
                "url": "http://127.0.0.1:8820/api/v1/chat/stream",
                "method": "POST",
                "resource_type": "document",
            }
            for _ in FIXTURE_TURNS
        ],
    )
    _write_json(netlog_path, {"events": []})
    required_urls = _audit_module()._validate_browser_requests(
        requests_path,
        declared_count=len(FIXTURE_TURNS),
        label="test browser",
    )

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="Chromium netlog is empty",
    ):
        _audit_module()._validate_chromium_netlog(
            netlog_path,
            label="test browser",
            required_urls=required_urls,
        )


def test_independent_chromium_netlog_is_never_empty(
    tmp_path: Path,
) -> None:
    netlog_path = tmp_path / "chromium-netlog.json"
    _write_json(netlog_path, {"events": []})

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="Chromium netlog is empty",
    ):
        _audit_module()._validate_chromium_netlog(
            netlog_path,
            label="test browser",
        )


def test_independent_audit_rejects_nonloopback_chromium_netlog(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    summary = bundle["desktop_summary"]
    netlog = summary.parent / "chromium-netlog.json"
    _write_json(
        netlog,
        {"events": [{"params": {"url": "https://example.invalid/x"}}]},
    )
    sandbox_path = summary.parent / "sandbox-audit.json"
    sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
    sandbox["netlog_sha256"] = sha256(netlog.read_bytes()).hexdigest()
    _write_json(sandbox_path, sandbox)
    for turn_id in FIXTURE_TURNS:
        _write_json(
            summary.parent / turn_id / "sandbox-audit.json",
            sandbox,
        )
    _reindex_browser_summary(summary)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="Chromium netlog.*non-loopback",
    ):
        _run(bundle)


@pytest.mark.parametrize("mutation", ("canonical", "projection"))
def test_independent_browser_rejects_product_payload_forgery(
    mutation: str,
) -> None:
    module = _audit_module()
    sources = module._canonical_product_sources(Path.cwd())
    products = sources["products"]
    assets = sources["assets"]
    displays = sources["displays"]
    assert isinstance(products, dict)
    assert isinstance(assets, dict)
    assert isinstance(displays, dict)
    product = products[38]
    asset = assets[38]
    display = displays.get(38)
    assert isinstance(product, dict)
    assert isinstance(asset, dict)
    assert display is None or isinstance(display, dict)
    category = module._known_core_field(product, "category")
    name = module._known_core_field(product, "product_identity")
    brand = module._known_core_field(product, "brand")
    price = module._known_core_field(product, "price")
    assert isinstance(category, str)
    platform, detail_url = module._asset_link(asset.get("image_url"))
    from app.guide.presentation.contracts import ProductCard

    card = ProductCard.model_validate_json(
        json.dumps(
            {
            "product_id": 38,
            "category_profile": module._CATEGORY_PROFILE_BY_RAW[category],
            "category_facts": [],
            "price_specification_alignment": (
                display["price_specification_alignment"]
                if display is not None
                else "unresolved"
            ),
            "specification": (
                display["display_specification"]
                if (
                    display is not None
                    and display["price_specification_alignment"] == "aligned"
                )
                else None
            ),
            "display_name": (
                display["display_name"] if display is not None else name
            ),
            "name": name,
            "brand": brand,
            "category": category,
            "price": price,
            "image_url": asset["image_url"],
            "detail_url": detail_url,
            "platform": platform,
            "image_source_sha256": asset["source_image_sha256"],
            "skin_match": "unknown",
            "matched_efficacies": [],
            "fact_warnings": [],
            },
            ensure_ascii=False,
        )
    )
    raw_card = card.model_dump(mode="json")
    frontend = module.project_frontend_product(card)
    if mutation == "canonical":
        raw_card["price"] = "9999"
        forged = type(card).model_validate_json(json.dumps(raw_card))
        frontend = module.project_frontend_product(forged)
    else:
        frontend["description"] = "forged"

    with pytest.raises(
        module.Task11IndependentAuditError,
        match=(
            "canonical product binding"
            if mutation == "canonical"
            else "frontend product projection"
        ),
    ):
        module._validate_browser_products(
            events=(
                (
                    "products",
                    {"cards": [raw_card], "products": [frontend]},
                ),
            ),
            visible_ids=(38,),
            sources=sources,
            label="test browser",
        )


def test_independent_audit_rejects_non_kernel_browser_measurement(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    root = bundle["desktop_summary"].parent
    sandbox = json.loads(
        (root / "sandbox-audit.json").read_text(encoding="utf-8")
    )
    sandbox["measurement"] = (
        "chromium-netlog-and-playwright-request-events"
    )
    _write_json(root / "sandbox-audit.json", sandbox)
    for turn_id in FIXTURE_TURNS:
        _write_json(root / turn_id / "sandbox-audit.json", sandbox)
    _reindex_browser_summary(bundle["desktop_summary"])

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="Seatbelt",
    ):
        _run(bundle)


def test_independent_audit_rejects_tampered_raw_seatbelt_log(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    root = bundle["desktop_summary"].parent
    raw_path = root / "seatbelt.raw.ndjson"
    raw_path.write_bytes(raw_path.read_bytes() + b"{}\n")
    _reindex_browser_summary(bundle["desktop_summary"])

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="Seatbelt raw log hash",
    ):
        _run(bundle)


def test_independent_audit_rejects_missing_seatbelt_canary(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    root = bundle["desktop_summary"].parent
    sandbox = json.loads(
        (root / "sandbox-audit.json").read_text(encoding="utf-8")
    )
    sandbox["seatbelt_canary_denial_count"] = 0
    sandbox["canary_denials"] = []
    _write_json(root / "sandbox-audit.json", sandbox)
    for turn_id in FIXTURE_TURNS:
        _write_json(root / turn_id / "sandbox-audit.json", sandbox)
    _reindex_browser_summary(bundle["desktop_summary"])

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="Seatbelt canary",
    ):
        _run(bundle)


def test_independent_audit_rejects_non_quiescent_fixture_process_group(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    root = bundle["desktop_summary"].parent
    sandbox = json.loads(
        (root / "sandbox-audit.json").read_text(encoding="utf-8")
    )
    sandbox["process_group_quiescent"] = False
    _write_json(root / "sandbox-audit.json", sandbox)
    for turn_id in FIXTURE_TURNS:
        _write_json(root / turn_id / "sandbox-audit.json", sandbox)
    _reindex_browser_summary(bundle["desktop_summary"])

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="process group",
    ):
        _run(bundle)


def test_independent_audit_derives_runtime_escape_from_raw_kernel_log(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    runtime_network = json.loads(
        bundle["runtime_network_report"].read_text(encoding="utf-8")
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
    _write_json(bundle["runtime_network_report"], runtime_network)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="runtime network report",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_rejects_non_quiescent_runtime_process_group(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    runtime_network = json.loads(
        bundle["runtime_network_report"].read_text(encoding="utf-8")
    )
    runtime_network["process_group_quiescent"] = False
    _write_json(bundle["runtime_network_report"], runtime_network)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="runtime network report",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_rejects_unconsumed_runtime_challenge(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    runtime_network = _runtime_network_payload(manifest)
    runtime_network["challenge_consumed"] = False
    runtime_network["passed"] = True

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="runtime network report lifecycle",
    ):
        _audit_module()._validate_network_report(
            runtime_network,
            runtime=True,
            candidate_manifest_hash=sha256(
                manifest.read_bytes()
            ).hexdigest(),
        )


def test_independent_audit_rejects_jointly_forged_identity_and_challenge_digests(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    original_identity = json.loads(
        (
            bundle["desktop_summary"].parent
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
        summary_path = bundle[role]
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
        summary["artifact_sha256"][
            "runtime-identity.json"
        ] = sha256(forged_identity_bytes).hexdigest()
        summary["artifact_sha256"][
            "consumed-runtime-health-challenge.json"
        ] = sha256(challenge_path.read_bytes()).hexdigest()
        _write_json(summary_path, summary)

    runtime_network = json.loads(
        bundle["runtime_network_report"].read_text(encoding="utf-8")
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
    _write_json(bundle["runtime_network_report"], runtime_network)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="runtime provenance",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


def test_independent_audit_requires_zero_api_process_guard() -> None:
    network_report = {
        "schema_version": "guide-zero-api-network-report-v1",
        "guard_active": True,
        "passed": True,
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
        "attempts": [],
    }

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="process guard",
    ):
        _audit_module()._validate_network_report(
            network_report,
            runtime=False,
        )


def test_independent_audit_rejects_missing_runtime_drain_marker(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    runtime_network = json.loads(
        bundle["runtime_network_report"].read_text(encoding="utf-8")
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
    _write_json(bundle["runtime_network_report"], runtime_network)

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match="runtime network report",
    ):
        _run(bundle)

    assert not bundle["output"].exists()


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
        "attempt_ledger",
        "record_manual_screenshot_review",
        "replay_final_real_backend",
        "run_bound_runtime",
        "run_final_real_translation",
        "run_final_release_gate",
        "run_mainline_contract_browser_audit",
    )
    assert all(
        f"import {module_name}" not in source
        and f"from tools.guide_gates.{module_name}" not in source
        for module_name in forbidden
    )


@pytest.mark.parametrize(
    ("old", "new", "match"),
    (
        (
            "understanding=self._observer.compiled_understanding,",
            "understanding=case.meaning,",
            "observed compiler output",
        ),
        (
            "observed_layers = _derive_observed_layers(",
            "observed_layers = tuple(_RUNTIME_LAYER_ORDER) or "
            "_derive_observed_layers(",
            "runtime layers",
        ),
    ),
)
def test_independent_audit_rejects_production_runner_self_assertion(
    tmp_path: Path,
    old: str,
    new: str,
    match: str,
) -> None:
    relative = (
        "tools/guide_gates/run_task11_production_path_matrix.py"
    )
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    source = (
        Path(__file__).resolve().parents[3] / relative
    ).read_text(encoding="utf-8")
    assert old in source
    target.write_text(source.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match=match,
    ):
        _audit_module()._validate_governance_source_contracts(
            root=tmp_path,
            manifest={
                "tool_paths": [relative],
                "protected_paths": list(BROWSER_CANONICAL_DATA_PATHS),
            },
        )


@pytest.mark.parametrize(
    ("relative", "old", "new", "match"),
    (
        (
            "app/guide/application/text_recommendation_flow.py",
            "        notify_processor_entry(\n",
            "        removed_processor_entry_observer(\n",
            "concrete processor entry",
        ),
        (
            "app/guide/application/unified_guide_flow.py",
            "        return processor.execute(execution_input)\n",
            (
                "        notify_processor_entry(\n"
                "            self._observer,\n"
                "            execution_input=execution_input,\n"
                "            implementation=type(processor).__qualname__,\n"
                "            processor_instance=processor,\n"
                "        )\n"
                "        return processor.execute(execution_input)\n"
            ),
            "dispatcher processor entry",
        ),
    ),
)
def test_independent_audit_rejects_processor_entry_source_mutation(
    tmp_path: Path,
    relative: str,
    old: str,
    new: str,
    match: str,
) -> None:
    root = Path(__file__).resolve().parents[3]
    source_paths = [
        "app/guide/application/text_recommendation_flow.py",
        "app/guide/application/image_recommendation_flow.py",
        "app/guide/application/consultation_chat_flow.py",
        "app/guide/application/unified_guide_flow.py",
    ]
    tool_path = (
        "tools/guide_gates/run_task11_production_path_matrix.py"
    )
    for path in (*source_paths, tool_path):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / path).read_bytes())
    target = tmp_path / relative
    source = target.read_text(encoding="utf-8")
    assert old in source
    target.write_text(source.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(
        _audit_module().Task11IndependentAuditError,
        match=match,
    ):
        _audit_module()._validate_governance_source_contracts(
            root=tmp_path,
            manifest={
                "tool_paths": [tool_path],
                "source_paths": source_paths,
                "protected_paths": list(BROWSER_CANONICAL_DATA_PATHS),
            },
        )
