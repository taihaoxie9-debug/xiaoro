from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import subprocess

import pytest

from tools.guide_gates.build_responsibility_matrix import (
    write_responsibility_matrix,
)
from tools.guide_gates import attempt_ledger
from tools.guide_gates import run_final_release_gate as release_gate
from tools.guide_gates.run_final_release_gate import (
    aggregate_release_gate,
    run_focused_gate,
)


def _release_plan_before_seal(title: str) -> str:
    return "\n".join([
        f"# {title}",
        "Core release invariant remains unchanged.",
        "Task 11 status: completed",
        "Task 12 status: awaiting_step_9",
        "Release status: READY_TO_SEAL",
        "## Task 11",
        "## Task 12",
        "- [ ] **Step 9: Finalize release seal**",
        "",
    ])


def _release_plan_after_seal(
    title: str,
    *,
    seal: dict[str, object],
    seal_path: str,
) -> str:
    return "\n".join([
        f"# {title}",
        "Core release invariant remains unchanged.",
        "Task 11 status: completed",
        "Task 12 status: completed",
        "Release status: READY",
        "## ~~Task 11~~",
        "## ~~Task 12~~",
        "- [x] **Step 9: Finalize release seal**",
        "",
        "## Final Release Closure Record",
        "- [x] Task 12 Step 9 complete",
        f"Task 11 commit: {seal['task11_commit']}",
        f"Attempt context: {seal['attempt_context_path']}",
        f"Evidence commit: {seal['evidence_commit']}",
        f"Release summary path: {seal['release_summary_path']}",
        f"Release summary SHA-256: {seal['release_summary_sha256']}",
        (
            "Manual review path: "
            f"{seal['manual_screenshot_review_path']}"
        ),
        (
            "Manual review SHA-256: "
            f"{seal['manual_screenshot_review_sha256']}"
        ),
        f"Release seal path: {seal_path}",
        f"Release seal SHA-256: {seal['release_seal_sha256']}",
        "",
    ])


def _real_summary(
    *,
    passed: bool = True,
    wrong_binding_count: int = 0,
) -> dict[str, object]:
    return {
        "passed": passed,
        "critical_trajectory_count": 12,
        "critical_trajectory_passed": 12 if passed else 11,
        "completed_turn_count": 48 if passed else 47,
        "turn_count": 48,
        "passed_turn_count": 48 if passed else 45,
        "wrong_binding_count": wrong_binding_count,
        "wrong_processor_count": 0,
        "wrong_responsibility_count": 0,
        "wrong_presentation_count": 0,
        "unaligned_price_specification_count": 0,
        "copywriter_fallback_count": 0,
        "invalid_clarification_count": 0,
        "unsafe_downgrade_count": 0,
        "raw_ad_leak_count": 0,
        "internal_language_count": 0,
        "internal_public_language_count": 0,
        "frontend_contract_violation_count": 0,
        "context_mismatch_count": 0,
        "desktop_passed": 8,
        "desktop_total": 8,
        "mobile_passed": 8,
        "mobile_total": 8,
        "serious_failure_count": 0 if passed else 1,
    }


def test_focused_gate_validates_generated_matrix_and_public_renderer(
    tmp_path: Path,
) -> None:
    matrix_dir = tmp_path / "matrix"
    write_responsibility_matrix(matrix_dir)

    result = run_focused_gate(matrix_dir)

    assert result["passed"] is True
    assert result["row_count"] == 7776
    assert result["legal_row_failures"] == 0
    assert result["wrong_binding_count"] == 0
    assert result["wrong_processor_count"] == 0
    assert result["wrong_presentation_count"] == 0
    assert result["forbidden_public_text_count"] == 0


def test_focused_gate_rejects_matrix_drift(tmp_path: Path) -> None:
    matrix_dir = tmp_path / "matrix"
    write_responsibility_matrix(matrix_dir)
    truth_path = matrix_dir / "truth.jsonl"
    rows = [
        json.loads(line)
        for line in truth_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["expected_processor"] = "wrong_processor"
    truth_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )

    result = run_focused_gate(matrix_dir)

    assert result["passed"] is False
    assert result["legal_row_failures"] >= 1
    assert result["wrong_processor_count"] >= 1


def test_aggregate_gate_requires_all_real_layers_to_pass(tmp_path: Path) -> None:
    focused = {
        "passed": True,
        "legal_row_failures": 0,
        "wrong_binding_count": 0,
        "wrong_processor_count": 0,
        "wrong_presentation_count": 0,
        "forbidden_public_text_count": 0,
    }
    translation = _real_summary()
    backend = _real_summary()
    browser = _real_summary()
    translation["schema_version"] = (
        "guide-final-real-translation-summary-v1"
    )
    backend["schema_version"] = "guide-final-real-backend-summary-v1"
    browser.update({
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "release",
        "viewport": "all",
    })
    manual = {
        "schema_version": "guide-manual-screenshot-review-v1",
        "passed": True,
        "manual_screenshot_review_count": 14,
        "manual_screenshot_failure_count": 0,
    }

    result = aggregate_release_gate(
        focused=focused,
        translation=translation,
        backend=backend,
        browser=browser,
        manual_review=manual,
    )

    assert result["passed"] is True
    assert result["serious_failure_count"] == 0
    assert result["wrong_binding_count"] == 0
    assert result["unsafe_downgrade_count"] == 0
    assert result["raw_ad_leak_count"] == 0
    assert result["internal_language_count"] == 0
    assert result["frontend_contract_violation_count"] == 0

    blocked = aggregate_release_gate(
        focused=focused,
        translation=_real_summary(wrong_binding_count=1),
        backend=backend,
        browser=browser,
        manual_review=manual,
    )
    assert blocked["passed"] is False
    assert blocked["wrong_binding_count"] == 1
    assert blocked["serious_failure_count"] >= 1


def test_aggregate_gate_rejects_missing_required_counter() -> None:
    focused = {
        "schema_version": "guide-final-focused-gate-v1",
        "passed": True,
        "legal_row_failures": 0,
        "wrong_binding_count": 0,
        "wrong_processor_count": 0,
        "wrong_presentation_count": 0,
        "forbidden_public_text_count": 0,
    }
    translation = _real_summary()
    backend = _real_summary()
    browser = _real_summary()
    del browser["invalid_clarification_count"]

    with pytest.raises(ValueError, match="invalid_clarification_count"):
        aggregate_release_gate(
            focused=focused,
            translation=translation,
            backend=backend,
            browser=browser,
            manual_review={
                "schema_version": "guide-manual-screenshot-review-v1",
                "passed": True,
                "manual_screenshot_review_count": 14,
                "manual_screenshot_failure_count": 0,
            },
        )


def test_aggregate_gate_rejects_backend_context_mismatch() -> None:
    focused = {
        "schema_version": "guide-final-focused-gate-v1",
        "passed": True,
        "wrong_binding_count": 0,
        "wrong_processor_count": 0,
        "wrong_presentation_count": 0,
    }
    translation = _real_summary()
    translation["schema_version"] = (
        "guide-final-real-translation-summary-v1"
    )
    backend = _real_summary()
    backend.update({
        "schema_version": "guide-final-real-backend-summary-v1",
        "context_mismatch_count": 1,
    })
    browser = _real_summary()
    browser.update({
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "release",
        "viewport": "all",
    })

    result = aggregate_release_gate(
        focused=focused,
        translation=translation,
        backend=backend,
        browser=browser,
        manual_review={
            "schema_version": "guide-manual-screenshot-review-v1",
            "passed": True,
            "manual_screenshot_review_count": 14,
            "manual_screenshot_failure_count": 0,
        },
    )

    assert result["passed"] is False
    assert result["context_mismatch_count"] == 1


def test_aggregate_gate_accepts_actual_phase_summary_schemas() -> None:
    result = aggregate_release_gate(
        focused={
            "schema_version": "guide-final-focused-gate-v1",
            "passed": True,
            "wrong_binding_count": 0,
            "wrong_processor_count": 0,
            "wrong_presentation_count": 0,
        },
        translation={
            "schema_version": "guide-final-real-translation-summary-v1",
            "passed": True,
            "critical_trajectory_count": 12,
            "critical_trajectory_passed": 12,
            "turn_count": 48,
            "passed_turn_count": 48,
            "wrong_binding_count": 0,
            "unsafe_downgrade_count": 0,
            "internal_language_count": 0,
            "internal_public_language_count": 0,
            "serious_failure_count": 0,
        },
        backend={
            "schema_version": "guide-final-real-backend-summary-v1",
            "passed": True,
            "critical_trajectory_count": 12,
            "critical_trajectory_passed": 12,
            "turn_count": 48,
            "completed_turn_count": 48,
            "wrong_binding_count": 0,
            "wrong_presentation_count": 0,
            "unsafe_downgrade_count": 0,
            "raw_ad_leak_count": 0,
            "internal_language_count": 0,
            "internal_public_language_count": 0,
            "frontend_contract_violation_count": 0,
            "context_mismatch_count": 0,
            "serious_failure_count": 0,
        },
        browser={
            "schema_version": (
                "guide-mainline-contract-browser-audit-v1"
            ),
            "passed": True,
            "turn_count": 14,
            "wrong_binding_count": 0,
            "frontend_contract_violation_count": 0,
            "unaligned_price_specification_count": 0,
            "copywriter_fallback_count": 0,
            "invalid_clarification_count": 0,
            "serious_failure_count": 0,
        },
        manual_review={
            "schema_version": "guide-manual-screenshot-review-v1",
            "passed": True,
            "manual_screenshot_review_count": 14,
            "manual_screenshot_failure_count": 0,
        },
    )

    assert result["passed"] is True
    assert result["serious_failure_count"] == 0


def test_r5_release_cli_surface_matches_plan() -> None:
    focused = release_gate._parse_args([
        "--responsibility-matrix",
        "matrix",
        "--attempt-context",
        "context.json",
        "--phase",
        "focused",
    ])
    assert focused.phase == "focused"
    assert focused.attempt_context == Path("context.json")

    aggregate = release_gate._parse_args([
        "--attempt-context",
        "context.json",
        "--phase",
        "aggregate",
    ])
    assert aggregate.phase == "aggregate"

    manifest = release_gate._parse_args([
        "build-evidence-manifest",
        "--attempt-context",
        "context.json",
        "--readiness",
        "readiness.json",
        "--ledger",
        "ledger.json",
        "--plan",
        "plan-a.md",
        "--plan",
        "plan-b.md",
        "--output",
        "manifest.json",
    ])
    assert manifest.command == "build-evidence-manifest"
    assert manifest.plans == [Path("plan-a.md"), Path("plan-b.md")]

    for command in (
        "stage-evidence",
        "verify-evidence-staging",
    ):
        parsed = release_gate._parse_args([
            command,
            "--manifest",
            "manifest.json",
        ])
        assert parsed.command == command

    create = release_gate._parse_args([
        "create-seal",
        "--attempt-context",
        "context.json",
        "--evidence-commit",
        "a" * 40,
        "--manual-screenshot-review-from-context",
        "--output",
        "release-seal.json",
    ])
    assert create.command == "create-seal"

    verify = release_gate._parse_args([
        "verify-seal",
        "--seal",
        "release-seal.json",
        "--head",
        "b" * 40,
        "--expected-evidence-commit",
        "a" * 40,
    ])
    assert verify.command == "verify-seal"


def test_r5_release_public_api_exposes_all_prebuilt_operations() -> None:
    assert {
        "aggregate_release_gate",
        "build_evidence_manifest",
        "create_release_seal",
        "main",
        "run_aggregate_phase",
        "run_focused_gate",
        "run_focused_phase",
        "stage_evidence",
        "verify_evidence_staging",
        "verify_release_seal",
    } <= set(release_gate.__all__)


def test_focused_phase_uses_verified_context_owned_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "translation-attempt-01"
    output.mkdir()
    context_path = output / "attempt-context.json"
    readiness_path = tmp_path / "release-readiness.json"
    ledger_path = tmp_path / "ledger.json"
    context = {
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
        "output_directory": str(output),
        "current_phase": "translation",
        "phase_attempt_ids": {
            "translation": "translation-attempt-01",
        },
    }
    context_path.write_text(json.dumps(context), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        release_gate,
        "read_attempt_context",
        lambda *args, **kwargs: calls.append("context") or context,
        raising=False,
    )
    monkeypatch.setattr(
        release_gate,
        "verify_task11_readiness",
        lambda **kwargs: calls.append("readiness") or {"passed": True},
        raising=False,
    )
    monkeypatch.setattr(
        release_gate,
        "read_ledger",
        lambda path: {
            "attempts": [{
                "attempt_id": "translation-attempt-01",
                "trajectory_set": "translation",
                "result": "allocated",
                "context_path": str(context_path.resolve()),
            }]
        },
        raising=False,
    )
    expected = {
        "schema_version": "guide-final-focused-gate-v1",
        "passed": True,
    }
    monkeypatch.setattr(
        release_gate,
        "run_focused_gate",
        lambda path: calls.append("focused") or expected,
    )

    result = release_gate.run_focused_phase(
        responsibility_matrix=tmp_path / "matrix",
        attempt_context_path=context_path,
        repo_root=tmp_path,
    )

    assert result == expected
    assert json.loads(
        (output / "focused.json").read_text(encoding="utf-8")
    ) == expected
    assert calls == ["context", "readiness", "focused"]


def test_aggregate_phase_resolves_inputs_from_context_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    translation_output = tmp_path / "translation-attempt-01"
    browser_output = tmp_path / "release-browser-attempt-01"
    translation_context = translation_output / "attempt-context.json"
    browser_context = browser_output / "attempt-context.json"
    for path in (
        translation_output / "real-translation",
        translation_output / "real-backend",
        browser_output / "mainline-browser",
    ):
        path.mkdir(parents=True)
    translation_context.write_text("{}\n", encoding="utf-8")
    browser_context.write_text("{}\n", encoding="utf-8")
    focused = {
        "schema_version": "guide-final-focused-gate-v1",
        "passed": True,
        "legal_row_failures": 0,
        "wrong_binding_count": 0,
        "wrong_processor_count": 0,
        "wrong_presentation_count": 0,
        "forbidden_public_text_count": 0,
    }
    translation = _real_summary()
    backend = _real_summary()
    browser = _real_summary()
    manual = {
        "schema_version": "guide-manual-screenshot-review-v1",
        "passed": True,
        "manual_screenshot_review_count": 14,
        "manual_screenshot_failure_count": 0,
    }
    for path, payload in (
        (translation_output / "focused.json", focused),
        (
            translation_output / "real-translation/summary.json",
            translation,
        ),
        (translation_output / "real-backend/summary.json", backend),
        (
            browser_output / "mainline-browser/summary.json",
            browser,
        ),
        (browser_output / "manual-screenshot-review.json", manual),
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")
    context = {
        "output_directory": str(browser_output),
        "current_phase": "browser",
        "phase_attempt_ids": {
            "translation": "translation-attempt-01",
            "browser": "release-browser-attempt-01",
        },
    }
    ledger = {
        "attempts": [
            {
                "attempt_id": "translation-attempt-01",
                "trajectory_set": "translation",
                "result": "passed",
                "context_path": str(translation_context.resolve()),
            },
            {
                "attempt_id": "release-browser-attempt-01",
                "trajectory_set": "browser",
                "result": "passed",
                "context_path": str(browser_context.resolve()),
            },
        ]
    }
    monkeypatch.setattr(
        release_gate,
        "_verified_context",
        lambda **kwargs: (
            context,
            browser_output,
            tmp_path / "ledger.json",
            ledger,
        ),
    )
    monkeypatch.setattr(
        release_gate,
        "_validate_aggregate_bindings",
        lambda **kwargs: None,
    )

    result = release_gate.run_aggregate_phase(
        attempt_context_path=browser_context,
        repo_root=tmp_path,
    )

    assert result["passed"] is True
    assert json.loads(
        (browser_output / "release-summary.json").read_text(
            encoding="utf-8"
        )
    )["manual_screenshot_review_count"] == 14


def test_aggregate_phase_rejects_stale_manual_browser_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    translation_output = tmp_path / "translation-attempt-01"
    browser_output = tmp_path / "release-browser-attempt-01"
    translation_context = translation_output / "attempt-context.json"
    browser_context = browser_output / "attempt-context.json"
    readiness = tmp_path / "task11-release-readiness.json"
    for path in (
        translation_output / "real-translation",
        translation_output / "real-backend",
        browser_output / "mainline-browser",
    ):
        path.mkdir(parents=True)
    translation_context.write_text("{}\n", encoding="utf-8")
    readiness.write_text("{}\n", encoding="utf-8")
    context = {
        "readiness_path": str(readiness.resolve()),
        "readiness_sha256": sha256(readiness.read_bytes()).hexdigest(),
        "output_directory": str(browser_output.resolve()),
        "current_phase": "browser",
        "phase_attempt_ids": {
            "translation": "translation-attempt-01",
            "browser": "release-browser-attempt-01",
        },
    }
    browser_context.write_text(
        json.dumps(context, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    browser_summary = browser_output / "mainline-browser/summary.json"
    browser_summary.write_text(
        json.dumps(
            {
                "schema_version": (
                    "guide-mainline-contract-browser-audit-v1"
                ),
                "passed": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    for path in (
        translation_output / "focused.json",
        translation_output / "real-translation/summary.json",
        translation_output / "real-backend/summary.json",
    ):
        path.write_text('{"passed":true}\n', encoding="utf-8")
    manual = browser_output / "manual-screenshot-review.json"
    manual.write_text(
        json.dumps(
            {
                "schema_version": "guide-manual-screenshot-review-v1",
                "passed": True,
                "attempt_id": "release-browser-attempt-01",
                "code_revision": "a" * 40,
                "attempt_context_path": (
                    browser_context.relative_to(tmp_path).as_posix()
                ),
                "attempt_context_sha256": sha256(
                    browser_context.read_bytes()
                ).hexdigest(),
                "readiness_path": readiness.relative_to(
                    tmp_path
                ).as_posix(),
                "readiness_sha256": sha256(
                    readiness.read_bytes()
                ).hexdigest(),
                "browser_summary_path": browser_summary.relative_to(
                    tmp_path
                ).as_posix(),
                "browser_summary_sha256": "0" * 64,
                "manual_screenshot_review_count": 14,
                "manual_screenshot_failure_count": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = {
        "attempts": [
            {
                "attempt_id": "translation-attempt-01",
                "trajectory_set": "translation",
                "result": "passed",
                "context_path": str(translation_context.resolve()),
            },
            {
                "attempt_id": "release-browser-attempt-01",
                "trajectory_set": "browser",
                "result": "passed",
                "context_path": str(browser_context.resolve()),
                "code_revision": "a" * 40,
            },
        ]
    }
    monkeypatch.setattr(
        release_gate,
        "_verified_context",
        lambda **kwargs: (
            context,
            browser_output,
            tmp_path / "ledger.json",
            ledger,
        ),
    )

    with pytest.raises(
        release_gate.FinalReleaseGateError,
        match="manual review browser summary hash mismatch",
    ):
        release_gate.run_aggregate_phase(
            attempt_context_path=browser_context,
            repo_root=tmp_path,
        )

    assert not (browser_output / "release-summary.json").exists()


def test_aggregate_bindings_reject_mixed_translation_and_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path
    output = root / "release-browser-attempt-01"
    translation_output = root / "translation-attempt-01"
    translation_dir = translation_output / "real-translation"
    backend_dir = translation_output / "real-backend"
    browser_dir = output / "mainline-browser"
    for path in (translation_dir, backend_dir, browser_dir):
        path.mkdir(parents=True)
    context_path = output / "attempt-context.json"
    readiness_path = root / "task11-release-readiness.json"
    focused_path = translation_output / "focused.json"
    browser_summary_path = browser_dir / "summary.json"
    fixture_path = (
        root
        / "tests/fixtures/guide/final_release/"
        "real_translation_12x4_v5.jsonl"
    )
    fixture_path.parent.mkdir(parents=True)
    fixture_path.write_text('{"fixture":"v5"}\n', encoding="utf-8")
    fixture_sha256 = sha256(fixture_path.read_bytes()).hexdigest()
    context_path.write_text("{}\n", encoding="utf-8")
    readiness_path.write_text("{}\n", encoding="utf-8")
    focused_path.write_text('{"passed":true}\n', encoding="utf-8")
    browser_artifact = output / "browser-desktop/turn-01/screenshot.png"
    browser_artifact.parent.mkdir(parents=True)
    browser_artifact.write_bytes(b"browser-artifact")
    browser_summary_path.write_text(
        json.dumps(
            {
                "schema_version": (
                    "guide-mainline-contract-browser-audit-v1"
                ),
                "trajectory_set": "release",
                "viewport": "all",
                "artifact_sha256": {
                    browser_artifact.relative_to(root).as_posix(): sha256(
                        browser_artifact.read_bytes()
                    ).hexdigest(),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    translation_results = translation_dir / "results.jsonl"
    translation_summary = translation_dir / "summary.json"
    translation_results.write_text("{}\n", encoding="utf-8")
    translation_summary.write_text(
        json.dumps(
            {
                "focused_summary_sha256": sha256(
                    focused_path.read_bytes()
                ).hexdigest(),
                "results_sha256": sha256(
                    translation_results.read_bytes()
                ).hexdigest(),
                "fixture_path": fixture_path.relative_to(root).as_posix(),
                "fixture_sha256": fixture_sha256,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    translation_checksums = translation_dir / "SHA256SUMS"
    translation_checksums.write_text(
        (
            f"{sha256(translation_results.read_bytes()).hexdigest()}  "
            "results.jsonl\n"
            f"{sha256(translation_summary.read_bytes()).hexdigest()}  "
            "summary.json\n"
        ),
        encoding="ascii",
    )
    backend_results = backend_dir / "results.jsonl"
    backend_summary = backend_dir / "summary.json"
    backend_results.write_text("{}\n", encoding="utf-8")
    backend_summary.write_text(
        json.dumps(
            {
                "results_sha256": sha256(
                    backend_results.read_bytes()
                ).hexdigest(),
                "translation_results_sha256": sha256(
                    translation_results.read_bytes()
                ).hexdigest(),
                "translation_summary_sha256": sha256(
                    translation_summary.read_bytes()
                ).hexdigest(),
                "translation_checksums_sha256": sha256(
                    translation_checksums.read_bytes()
                ).hexdigest(),
                "fixture_path": fixture_path.relative_to(root).as_posix(),
                "fixture_sha256": fixture_sha256,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (backend_dir / "SHA256SUMS").write_text(
        (
            f"{sha256(backend_results.read_bytes()).hexdigest()}  "
            "results.jsonl\n"
            f"{sha256(backend_summary.read_bytes()).hexdigest()}  "
            "summary.json\n"
        ),
        encoding="ascii",
    )
    context = {
        "readiness_sha256": sha256(
            readiness_path.read_bytes()
        ).hexdigest(),
    }
    manual = {
        "attempt_id": "release-browser-attempt-01",
        "code_revision": "a" * 40,
        "attempt_context_path": context_path.relative_to(root).as_posix(),
        "attempt_context_sha256": sha256(
            context_path.read_bytes()
        ).hexdigest(),
        "readiness_path": readiness_path.relative_to(root).as_posix(),
        "readiness_sha256": context["readiness_sha256"],
        "browser_summary_path": (
            browser_summary_path.relative_to(root).as_posix()
        ),
        "browser_summary_sha256": sha256(
            browser_summary_path.read_bytes()
        ).hexdigest(),
    }
    binding_arguments = {
        "repo_root": root,
        "context_path": context_path,
        "context": context,
        "readiness_path": readiness_path,
        "focused_path": focused_path,
        "translation_directory": translation_dir,
        "translation_summary": json.loads(
            translation_summary.read_text(encoding="utf-8")
        ),
        "backend_directory": backend_dir,
        "browser_summary_path": browser_summary_path,
        "browser_summary": json.loads(
            browser_summary_path.read_text(encoding="utf-8")
        ),
        "manual_review": manual,
        "browser_attempt": {
            "attempt_id": "release-browser-attempt-01",
            "code_revision": "a" * 40,
        },
    }
    browser_validation_calls: list[Path] = []
    monkeypatch.setattr(
        release_gate,
        "_validate_browser_release_evidence",
        lambda **kwargs: browser_validation_calls.append(
            kwargs["output"]
        ),
    )

    release_gate._validate_aggregate_bindings(
        **binding_arguments,
        backend_summary=json.loads(
            backend_summary.read_text(encoding="utf-8")
        ),
    )
    assert browser_validation_calls == [output]

    original_backend = backend_summary.read_bytes()
    backend_payload = json.loads(original_backend)
    backend_payload["fixture_sha256"] = "0" * 64
    backend_summary.write_text(
        json.dumps(backend_payload) + "\n",
        encoding="utf-8",
    )
    (backend_dir / "SHA256SUMS").write_text(
        (
            f"{sha256(backend_results.read_bytes()).hexdigest()}  "
            "results.jsonl\n"
            f"{sha256(backend_summary.read_bytes()).hexdigest()}  "
            "summary.json\n"
        ),
        encoding="ascii",
    )
    with pytest.raises(
        release_gate.FinalReleaseGateError,
        match="fixture binding",
    ):
        release_gate._validate_aggregate_bindings(
            **binding_arguments,
            backend_summary=backend_payload,
        )

    backend_summary.write_bytes(original_backend)
    (backend_dir / "SHA256SUMS").write_text(
        (
            f"{sha256(backend_results.read_bytes()).hexdigest()}  "
            "results.jsonl\n"
            f"{sha256(backend_summary.read_bytes()).hexdigest()}  "
            "summary.json\n"
        ),
        encoding="ascii",
    )
    backend_payload = json.loads(
        backend_summary.read_text(encoding="utf-8")
    )
    backend_payload["translation_results_sha256"] = "0" * 64
    backend_summary.write_text(
        json.dumps(backend_payload) + "\n",
        encoding="utf-8",
    )
    (backend_dir / "SHA256SUMS").write_text(
        (
            f"{sha256(backend_results.read_bytes()).hexdigest()}  "
            "results.jsonl\n"
            f"{sha256(backend_summary.read_bytes()).hexdigest()}  "
            "summary.json\n"
        ),
        encoding="ascii",
    )

    with pytest.raises(
        release_gate.FinalReleaseGateError,
        match="translation capture hash mismatch",
    ):
        release_gate._validate_aggregate_bindings(
            **binding_arguments,
            backend_summary=json.loads(
                backend_summary.read_text(encoding="utf-8")
            ),
        )


def test_seal_manual_rows_accept_producer_directory_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path
    output = root / "release-browser-attempt-01"
    turns = []
    rows = []
    artifact_sha256: dict[str, str] = {}
    modes = (
        "explore_recommendation",
        "fit_recommendation",
        "product_knowledge",
        "comparison",
        "image_identity",
        "image_fit_recommendation",
        "image_comparison",
    )
    for viewport in ("desktop", "mobile"):
        for mode in modes:
            trajectory_id = f"release-{mode}"
            turn_id = f"{trajectory_id}-turn-1"
            directory = (
                output
                / f"browser-{viewport}"
                / trajectory_id
                / "turn-1"
            )
            directory.mkdir(parents=True)
            screenshot = directory / "screenshot.png"
            contract = directory / "presentation-contract.json"
            screenshot.write_bytes(f"{viewport}:{mode}".encode("utf-8"))
            expected_contract_mode = {
                "explore_recommendation": "recommendation",
                "fit_recommendation": "recommendation",
                "product_knowledge": "product_knowledge",
                "comparison": "comparison",
                "image_identity": "image_identity",
                "image_fit_recommendation": "recommendation",
                "image_comparison": "comparison",
            }[mode]
            contract.write_text(
                json.dumps({
                    "mode": expected_contract_mode,
                    "recommendation_mode": (
                        "explore"
                        if mode == "explore_recommendation"
                        else (
                            "fit"
                            if mode
                            in {
                                "fit_recommendation",
                                "image_fit_recommendation",
                            }
                            else None
                        )
                    ),
                })
                + "\n",
                encoding="utf-8",
            )
            screenshot_relative = screenshot.relative_to(root).as_posix()
            contract_relative = contract.relative_to(root).as_posix()
            artifact_sha256.update({
                screenshot_relative: sha256(
                    screenshot.read_bytes()
                ).hexdigest(),
                contract_relative: sha256(
                    contract.read_bytes()
                ).hexdigest(),
            })
            turns.append({
                "viewport": viewport,
                "mode": mode,
                "turn_id": turn_id,
                "directory": directory.relative_to(output).as_posix(),
            })
            rows.append({
                "viewport": viewport,
                "mode": mode,
                "turn_id": turn_id,
                "artifact_directory": (
                    directory.relative_to(root).as_posix()
                ),
                "screenshot_path": screenshot_relative,
                "screenshot_sha256": artifact_sha256[
                    screenshot_relative
                ],
                "presentation_contract_path": contract_relative,
                "presentation_contract_sha256": artifact_sha256[
                    contract_relative
                ],
                "reviewer_id": "release-reviewer",
                "reviewed_at": "2026-08-23T12:00:00Z",
                "verdict": "passed",
                "issue_codes": [],
            })

    zero_counters = {
        "serious_failure_count": 0,
        "frontend_contract_violation_count": 0,
        "wrong_binding_count": 0,
        "unaligned_price_specification_count": 0,
        "copywriter_fallback_count": 0,
        "invalid_clarification_count": 0,
    }
    browser_summary = {
        "schema_version": "guide-mainline-contract-browser-audit-v1",
        "trajectory_set": "release",
        "viewport": "all",
        "turns": turns,
        "turn_count": 14,
        **zero_counters,
        "passed": True,
        "artifact_sha256": artifact_sha256,
    }
    browser_summary_path = output / "mainline-browser/summary.json"
    browser_summary_path.parent.mkdir(parents=True)
    browser_summary_path.write_text(
        json.dumps(browser_summary) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        release_gate,
        "validate_audit_bundle",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        release_gate,
        "derive_release_turn_counters",
        lambda path: dict(zero_counters),
    )
    release_gate._validate_browser_release_evidence(
        repo_root=root,
        output=output,
        browser_summary=browser_summary,
    )
    release_gate._validate_manual_review_rows(
        repo_root=root,
        output=output,
        browser_summary=browser_summary,
        manual_review={"rows": rows},
    )

    forged = {**browser_summary, "wrong_binding_count": 1}
    with pytest.raises(
        release_gate.FinalReleaseGateError,
        match="counters are not derived",
    ):
        release_gate._validate_browser_release_evidence(
            repo_root=root,
            output=output,
            browser_summary=forged,
        )


def test_release_evidence_manifest_stages_only_indexed_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
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
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "base.txt"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "base"],
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
    translation_output = root / "translation-attempt-01"
    browser_output = root / "release-browser-attempt-01"
    translation_context = translation_output / "attempt-context.json"
    browser_context = browser_output / "attempt-context.json"
    readiness_path = root / "task11-release-readiness.json"
    ledger_path = root / "smoke-attempt-ledger.json"
    for path in (
        translation_output / "real-translation",
        translation_output / "real-backend",
        browser_output / "mainline-browser",
        browser_output / "browser-desktop",
        browser_output / "browser-mobile",
        root / "docs/superpowers/plans",
    ):
        path.mkdir(parents=True, exist_ok=True)
    translation_context.write_text("{}\n", encoding="utf-8")
    browser_context.write_text("{}\n", encoding="utf-8")
    readiness_path.write_text(
        json.dumps({"task11_commit": task11_commit}) + "\n",
        encoding="utf-8",
    )
    ledger_path.write_text("{}\n", encoding="utf-8")
    for directory in (
        translation_output / "real-translation",
        translation_output / "real-backend",
    ):
        results = directory / "results.jsonl"
        summary = directory / "summary.json"
        results.write_text("{}\n", encoding="utf-8")
        summary.write_text('{"passed":true}\n', encoding="utf-8")
        (directory / "SHA256SUMS").write_text(
            (
                f"{sha256(results.read_bytes()).hexdigest()}  "
                "results.jsonl\n"
                f"{sha256(summary.read_bytes()).hexdigest()}  "
                "summary.json\n"
            ),
            encoding="ascii",
        )
    browser_artifact = (
        browser_output / "browser-desktop" / "screenshot.png"
    )
    browser_artifact.write_bytes(b"png")
    browser_summary = (
        browser_output / "mainline-browser" / "summary.json"
    )
    browser_summary.write_text(
        json.dumps({
            "artifact_sha256": {
                browser_artifact.relative_to(root).as_posix(): sha256(
                    browser_artifact.read_bytes()
                ).hexdigest(),
            }
        })
        + "\n",
        encoding="utf-8",
    )
    (browser_output / "runtime-identity.json").write_text(
        '{"verified":true}\n',
        encoding="utf-8",
    )
    for path in (
        translation_output / "focused.json",
        browser_output / "manual-screenshot-review.json",
        browser_output / "release-summary.json",
    ):
        path.write_text('{"passed":true}\n', encoding="utf-8")
    plans = [
        root
        / "docs/superpowers/plans/"
        "2026-08-20-final-guide-release-closure.md",
        root
        / "docs/superpowers/plans/"
        "2026-08-21-guide-mainline-contract-closure.md",
    ]
    for plan in plans:
        plan.write_text("# ready to seal\n", encoding="utf-8")
    context = {
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
        "output_directory": str(browser_output),
        "current_phase": "browser",
        "phase_attempt_ids": {
            "translation": "translation-attempt-01",
            "browser": "release-browser-attempt-01",
        },
    }
    browser_context.write_text(json.dumps(context), encoding="utf-8")
    ledger = {
        "revision": 8,
        "revision_chain": [{
            "revision": 8,
            "revision_hash": "a" * 64,
        }],
        "attempts": [
            {
                "attempt_id": "translation-attempt-01",
                "trajectory_set": "translation",
                "result": "passed",
                "context_path": str(translation_context.resolve()),
            },
            {
                "attempt_id": "release-browser-attempt-01",
                "trajectory_set": "browser",
                "result": "passed",
                "context_path": str(browser_context.resolve()),
            },
        ],
    }
    monkeypatch.setattr(
        release_gate,
        "_verified_post_real_context",
        lambda **kwargs: (
            context,
            browser_output,
            ledger_path,
            ledger,
            {"task11_commit": task11_commit},
        ),
    )
    monkeypatch.setattr(
        release_gate,
        "ledger_anchor",
        lambda payload: {
            "revision": 8,
            "revision_hash": "a" * 64,
        },
    )
    monkeypatch.setattr(
        release_gate,
        "read_ledger",
        lambda path: ledger,
    )
    manifest_path = (
        root
        / "docs/audits/final-release/mainline-contract-closure/"
        "release-evidence-manifest.json"
    )

    manifest = release_gate.build_evidence_manifest(
        attempt_context_path=browser_context,
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        plan_paths=plans,
        output_path=manifest_path,
        repo_root=root,
    )

    assert manifest["task11_commit"] == task11_commit
    assert (
        browser_artifact.relative_to(root).as_posix()
        in manifest["artifact_sha256_by_path"]
    )
    release_gate.stage_evidence(
        manifest_path=manifest_path,
        repo_root=root,
    )
    assert release_gate.verify_evidence_staging(
        manifest_path=manifest_path,
        repo_root=root,
    )["passed"] is True


def test_release_seal_binds_exact_two_commit_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
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
    plans = [
        root
        / "docs/superpowers/plans/"
        "2026-08-20-final-guide-release-closure.md",
        root
        / "docs/superpowers/plans/"
        "2026-08-21-guide-mainline-contract-closure.md",
    ]
    for plan in plans:
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("# Task 11\n", encoding="utf-8")
    (root / "app").mkdir()
    (root / "app/main.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
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
    translation_output = root / "translation-attempt-01"
    browser_output = root / "release-browser-attempt-01"
    translation_output.mkdir()
    browser_output.mkdir()
    translation_context = translation_output / "attempt-context.json"
    browser_context = browser_output / "attempt-context.json"
    translation_context.write_text("{}\n", encoding="utf-8")
    readiness_path = root / "task11-release-readiness.json"
    readiness_path.write_text(
        json.dumps({
            "schema_version": "guide-task11-release-readiness-v1",
            "task11_commit": task11_commit,
            "plan_revision": "task11-r1",
            "release_execution_paths": ["app/main.py"],
            "release_execution_blob_sha256_by_path": {
                "app/main.py": sha256(
                    (root / "app/main.py").read_bytes()
                ).hexdigest(),
            },
        })
        + "\n",
        encoding="utf-8",
    )
    ledger_path = root / "smoke-attempt-ledger.json"
    attempt_ledger.initialize_ledger(ledger_path)
    ledger_anchor = attempt_ledger.ledger_anchor(
        attempt_ledger.read_ledger(ledger_path)
    )
    context = {
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
        "output_directory": str(browser_output),
        "current_phase": "browser",
        "phase_attempt_ids": {
            "translation": "translation-attempt-01",
            "browser": "release-browser-attempt-01",
        },
    }
    browser_context.write_text(json.dumps(context), encoding="utf-8")
    summary = browser_output / "release-summary.json"
    manual = browser_output / "manual-screenshot-review.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": "guide-final-release-summary-v1",
                "passed": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manual.write_text(
        json.dumps(
            {
                "schema_version": "guide-manual-screenshot-review-v1",
                "passed": True,
                "manual_screenshot_review_count": 14,
                "manual_screenshot_failure_count": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    for index, plan in enumerate(plans, start=1):
        plan.write_text(
            _release_plan_before_seal(f"Release Plan {index}"),
            encoding="utf-8",
        )
    manifest_path = (
        root
        / "docs/audits/final-release/mainline-contract-closure/"
        "release-evidence-manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_paths = [
        translation_context,
        browser_context,
        readiness_path,
        ledger_path,
        summary,
        manual,
        *plans,
    ]
    manifest_payload = {
        "schema_version": "guide-release-evidence-manifest-v1",
        "plan_revision": "task11-r1",
        "task11_commit": task11_commit,
        "attempt_context_path": browser_context.relative_to(root).as_posix(),
        "attempt_context_sha256": sha256(
            browser_context.read_bytes()
        ).hexdigest(),
        "readiness_path": readiness_path.relative_to(root).as_posix(),
        "readiness_sha256": sha256(
            readiness_path.read_bytes()
        ).hexdigest(),
        "ledger_path": ledger_path.relative_to(root).as_posix(),
        "ledger_revision": ledger_anchor["revision"],
        "ledger_hash": ledger_anchor["revision_hash"],
        "artifact_sha256_by_path": {
            path.relative_to(root).as_posix(): sha256(
                path.read_bytes()
            ).hexdigest()
            for path in evidence_paths
        },
        "approved_paths": sorted([
            *(path.relative_to(root).as_posix() for path in evidence_paths),
            manifest_path.relative_to(root).as_posix(),
        ]),
    }
    manifest_payload["expected_name_status"] = {
        relative: (
            "M"
            if relative
            in {plan.relative_to(root).as_posix() for plan in plans}
            else "A"
        )
        for relative in manifest_payload["approved_paths"]
    }
    manifest_payload["payload_sha256"] = (
        release_gate._canonical_payload_sha256(
            root,
            tuple(manifest_payload["artifact_sha256_by_path"]),
        )
    )
    manifest_path.write_text(
        json.dumps(manifest_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-A", "--", *manifest_payload["approved_paths"]],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "release evidence"],
        cwd=root,
        check=True,
    )
    evidence_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    ledger = {
        "attempts": [
            {
                "attempt_id": "translation-attempt-01",
                "result": "passed",
                "context_path": str(translation_context.resolve()),
            },
            {
                "attempt_id": "release-browser-attempt-01",
                "result": "passed",
                "context_path": str(browser_context.resolve()),
            },
        ]
    }
    monkeypatch.setattr(
        release_gate,
        "_verified_post_real_context",
        lambda **kwargs: (
            context,
            browser_output,
            ledger_path,
            ledger,
            json.loads(readiness_path.read_text(encoding="utf-8")),
        ),
    )
    sealed_evidence_calls: list[str] = []
    monkeypatch.setattr(
        release_gate,
        "_validate_sealed_release_evidence",
        lambda **kwargs: sealed_evidence_calls.append(
            str(kwargs["summary_path"])
        ),
        raising=False,
    )
    seal_path = (
        root
        / "docs/audits/final-release/mainline-contract-closure/"
        "release-seal.json"
    )

    seal = release_gate.create_release_seal(
        attempt_context_path=browser_context,
        evidence_commit=evidence_commit,
        output_path=seal_path,
        repo_root=root,
    )
    assert sealed_evidence_calls == [str(summary)]

    seal_hash = sha256(seal_path.read_bytes()).hexdigest()
    summary_hash = sha256(summary.read_bytes()).hexdigest()
    manual_hash = sha256(manual.read_bytes()).hexdigest()
    for plan in plans:
        plan.write_text(
            "\n".join([
                "Release status: READY",
                f"Evidence commit: {evidence_commit}",
                f"Release summary SHA-256: {summary_hash}",
                f"Manual review SHA-256: {manual_hash}",
                f"Release seal SHA-256: {seal_hash}",
                "",
            ]),
            encoding="utf-8",
        )
    subprocess.run(
        [
            "git",
            "add",
            "--",
            *(plan.relative_to(root).as_posix() for plan in plans),
            seal_path.relative_to(root).as_posix(),
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "release seal"],
        cwd=root,
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert seal["evidence_commit"] == evidence_commit
    with pytest.raises(
        release_gate.FinalReleaseGateError,
        match="release plan",
    ):
        release_gate.verify_release_seal(
            seal_path=seal_path,
            head=head,
            expected_evidence_commit=evidence_commit,
            repo_root=root,
        )

    complete_seal = {
        **seal,
        "release_seal_sha256": seal_hash,
    }
    seal_relative = seal_path.relative_to(root).as_posix()
    for index, plan in enumerate(plans, start=1):
        plan.write_text(
            _release_plan_after_seal(
                f"Release Plan {index}",
                seal=complete_seal,
                seal_path=seal_relative,
            ),
            encoding="utf-8",
        )
    subprocess.run(
        [
            "git",
            "add",
            "--",
            *(plan.relative_to(root).as_posix() for plan in plans),
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit", "-q"],
        cwd=root,
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert release_gate.verify_release_seal(
        seal_path=seal_path,
        head=head,
        expected_evidence_commit=evidence_commit,
        repo_root=root,
    )["passed"] is True
    assert sealed_evidence_calls == [str(summary), str(summary)]

    plans[0].write_text(
        plans[0].read_text(encoding="utf-8").replace(
            "Core release invariant remains unchanged.",
            "Core release invariant was rewritten.",
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "--", plans[0].relative_to(root).as_posix()],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit", "-q"],
        cwd=root,
        check=True,
    )
    drifted_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(
        release_gate.FinalReleaseGateError,
        match="closure diff",
    ):
        release_gate.verify_release_seal(
            seal_path=seal_path,
            head=drifted_head,
            expected_evidence_commit=evidence_commit,
            repo_root=root,
        )
    plans[0].write_text(
        _release_plan_after_seal(
            "Release Plan 1",
            seal=complete_seal,
            seal_path=seal_relative,
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "--", plans[0].relative_to(root).as_posix()],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit", "-q"],
        cwd=root,
        check=True,
    )

    for path_key, hash_key, match in (
        (
            "release_evidence_manifest_path",
            "release_evidence_manifest_sha256",
            "release evidence manifest",
        ),
        (
            "release_summary_path",
            "release_summary_sha256",
            "release summary",
        ),
        (
            "manual_screenshot_review_path",
            "manual_screenshot_review_sha256",
            "manual screenshot review",
        ),
    ):
        fabricated = {
            **seal,
            path_key: f"missing/{path_key}.json",
            hash_key: "0" * 64,
        }
        seal_path.write_text(
            json.dumps(fabricated, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        fabricated_seal_hash = sha256(seal_path.read_bytes()).hexdigest()
        fabricated_complete = {
            **fabricated,
            "release_seal_sha256": fabricated_seal_hash,
        }
        for index, plan in enumerate(plans, start=1):
            plan.write_text(
                _release_plan_after_seal(
                    f"Release Plan {index}",
                    seal=fabricated_complete,
                    seal_path=seal_relative,
                ),
                encoding="utf-8",
            )
        subprocess.run(
            [
                "git",
                "add",
                "--",
                *(plan.relative_to(root).as_posix() for plan in plans),
                seal_path.relative_to(root).as_posix(),
            ],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--amend", "--no-edit", "-q"],
            cwd=root,
            check=True,
        )
        fabricated_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        with pytest.raises(
            release_gate.FinalReleaseGateError,
            match=match,
        ):
            release_gate.verify_release_seal(
                seal_path=seal_path,
                head=fabricated_head,
                expected_evidence_commit=evidence_commit,
                repo_root=root,
            )


def test_post_real_readiness_accepts_evidence_commit_and_rejects_code_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
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
    plan_paths = [
        (
            "docs/superpowers/plans/"
            "2026-08-20-final-guide-release-closure.md"
        ),
        (
            "docs/superpowers/plans/"
            "2026-08-21-guide-mainline-contract-closure.md"
        ),
    ]
    execution_paths = sorted([
        "app/main.py",
        "tests/test_main.py",
        "tools/release.py",
        *plan_paths,
    ])
    for relative in execution_paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
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
    ledger_path = root / "smoke-attempt-ledger.json"
    attempt_ledger.initialize_ledger(ledger_path)
    anchor = attempt_ledger.ledger_anchor(
        attempt_ledger.read_ledger(ledger_path)
    )
    readiness_path = root / "task11-release-readiness.json"
    readiness_path.write_text(
        json.dumps(
            {
                "schema_version": (
                    "guide-task11-release-readiness-v1"
                ),
                "task11_commit": task11_commit,
                "candidate_head": task11_commit,
                "release_plan_paths": plan_paths,
                "release_execution_paths": execution_paths,
                "release_execution_blob_sha256_by_path": {
                    relative: sha256(
                        (root / relative).read_bytes()
                    ).hexdigest()
                    for relative in execution_paths
                },
                "release_execution_tree_sha256": (
                    release_gate._canonical_payload_sha256(
                        root,
                        execution_paths,
                    )
                ),
                "evidence_files": {},
                "evidence_sha256": {},
                "ledger_path": str(ledger_path.resolve()),
                "ledger_anchor_revision": anchor["revision"],
                "ledger_anchor_hash": anchor["revision_hash"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for relative in plan_paths:
        (root / relative).write_text(
            "Release status: READY_TO_SEAL\n",
            encoding="utf-8",
        )
    evidence = root / "release-summary.json"
    evidence.write_text('{"passed":true}\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "--", *plan_paths, "release-summary.json"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "release evidence"],
        cwd=root,
        check=True,
    )
    evidence_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    verified = release_gate._verify_post_real_readiness(
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        require_head=evidence_commit,
        repo_root=root,
    )

    assert verified["task11_commit"] == task11_commit
    (root / "app/main.py").write_text("drift\n", encoding="utf-8")
    with pytest.raises(
        release_gate.FinalReleaseGateError,
        match="execution tree drift",
    ):
        release_gate._verify_post_real_readiness(
            readiness_path=readiness_path,
            ledger_path=ledger_path,
            require_head=evidence_commit,
            repo_root=root,
        )
    (root / "app/main.py").write_text("app/main.py\n", encoding="utf-8")
    external = tmp_path / "external"
    external.mkdir()
    external_evidence = external / "independent.json"
    external_evidence.write_text('{"passed":true}\n', encoding="utf-8")
    (root / "evidence-link").symlink_to(external, target_is_directory=True)
    readiness_payload = json.loads(
        readiness_path.read_text(encoding="utf-8")
    )
    readiness_payload["evidence_files"] = {
        "independent_audit": str(
            root / "evidence-link/independent.json"
        ),
    }
    readiness_payload["evidence_sha256"] = {
        "independent_audit": sha256(
            external_evidence.read_bytes()
        ).hexdigest(),
    }
    readiness_path.write_text(
        json.dumps(readiness_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        release_gate.FinalReleaseGateError,
        match="evidence path",
    ):
        release_gate._verify_post_real_readiness(
            readiness_path=readiness_path,
            ledger_path=ledger_path,
            require_head=evidence_commit,
            repo_root=root,
        )
