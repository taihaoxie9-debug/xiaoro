from __future__ import annotations

import ast
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from app.guide.understanding.turn_meaning_contracts import (
    TurnBudgetCandidate,
    TurnMeaning,
    TurnRecommendationModeBasis,
)
from tools.guide_gates.replay_final_real_backend import (
    BackendReplayError,
    replay_final_real_backend,
)


SOURCE_PATH = Path("tools/guide_gates/replay_final_real_backend.py")
BASE_FIXTURE = Path(
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v5.jsonl"
)
_HEAD = "a" * 40


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256_json(payload: object) -> str:
    return sha256(_canonical_bytes(payload).rstrip(b"\n")).hexdigest()


def _attempt_allocation_sha256(attempt: dict[str, object]) -> str:
    fields = {
        key: attempt.get(key)
        for key in (
            "attempt_id",
            "plan_revision",
            "repair_epoch",
            "retry_authorization_id",
            "code_revision",
            "started_at",
            "trajectory_set",
            "context_path",
        )
    }
    payload = (
        json.dumps(
            fields,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _meaning(kind: str) -> TurnMeaning:
    if kind == "recommendation":
        return TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_mode_basis=TurnRecommendationModeBasis(
                basis="bounded_exploration",
                source_text="预算三百以内",
            ),
            topic_hint="sunscreen",
            continuity_hint="new_task",
            subject_scope_hint="self",
            pending_response_hint="unknown",
            budget_candidates=(
                TurnBudgetCandidate(
                    raw_text="三百以内",
                    relation="maximum",
                    maximum="300",
                ),
            ),
            safety_language="ordinary",
        )
    if kind == "clarification":
        return TurnMeaning(
            operation_hint="clarification",
            topic_hint=None,
            continuity_hint="unknown",
            subject_scope_hint="unknown",
            pending_response_hint="unknown",
            safety_language="ordinary",
        )
    return TurnMeaning(
        operation_hint="knowledge",
        topic_hint="skincare",
        continuity_hint="new_task",
        subject_scope_hint="self",
        pending_response_hint="unknown",
        question_meaning="防晒为什么需要补涂",
        safety_language="ordinary",
    )


def _fixture_and_capture(
    tmp_path: Path,
    *,
    capture_count: int = 48,
) -> tuple[Path, list[dict[str, object]]]:
    source_rows = [
        json.loads(line)
        for line in BASE_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    recommendation_template = source_rows[0]["turns"][0]
    knowledge_template = source_rows[4]["turns"][0]
    clarification_template = source_rows[9]["turns"][0]
    fixture_rows: list[dict[str, object]] = []
    capture_rows: list[dict[str, object]] = []

    for trajectory_index in range(12):
        trajectory_id = f"backend-{trajectory_index + 1:02d}"
        turns: list[dict[str, object]] = []
        for turn_index in range(4):
            is_recommendation = turn_index == 0
            is_clarification = (
                trajectory_index == 11 and turn_index == 3
            )
            if is_clarification:
                turn = deepcopy(clarification_template)
                kind = "clarification"
                responsibility = "clarification"
            elif is_recommendation:
                turn = deepcopy(recommendation_template)
                kind = "recommendation"
                responsibility = "recommendation"
            else:
                turn = deepcopy(knowledge_template)
                kind = "knowledge"
                responsibility = "general_knowledge"
            turn_id = (
                f"backend-{trajectory_index + 1:02d}-"
                f"{turn_index + 1:02d}"
            )
            turn["trajectory_id"] = trajectory_id
            turn["turn_id"] = turn_id
            turn["case"]["case_id"] = turn_id
            turn["case"]["message"] = (
                "预算三百以内，推荐适合海边的防晒"
                if kind == "recommendation"
                else (
                    "第二个"
                    if kind == "clarification"
                    else "防晒为什么需要补涂"
                )
            )
            turn["case"]["execution"]["expected_task_mode"] = {
                "recommendation": "recommend",
                "knowledge": "knowledge",
                "clarification": "clarify",
            }[kind]
            turn["case"]["binding"]["expected_objects"] = []
            turns.append(turn)

            meaning_payload = _meaning(kind).model_dump(mode="json")
            capture_rows.append(
                {
                    "trajectory_id": trajectory_id,
                    "turn_id": turn_id,
                    "case_id": turn_id,
                    "status": "ok",
                    "schema_valid": True,
                    "translation_passed": True,
                    "source_grounded": True,
                    "binding_passed": True,
                    "task_plan_passed": True,
                    "recommendation_mode_passed": True,
                    "passed": True,
                    "provider_output": meaning_payload,
                    "provider_output_sha256": _sha256_json(
                        meaning_payload
                    ),
                    "responsibility": responsibility,
                }
            )
        fixture_rows.append(
            {
                "trajectory_id": trajectory_id,
                "family": "offline backend replay",
                "turns": turns,
                "critical": True,
            }
        )

    fixture = tmp_path / "real_translation_12x4_v5.jsonl"
    fixture.write_bytes(
        b"".join(_canonical_bytes(row) for row in fixture_rows)
    )
    return fixture, capture_rows[:capture_count]


def _attempt_context(
    tmp_path: Path,
    capture_rows: list[dict[str, object]],
) -> Path:
    attempt_root = tmp_path / "translation-attempt-01"
    translation = attempt_root / "real-translation"
    translation.mkdir(parents=True)
    results_bytes = b"".join(
        _canonical_bytes(row) for row in capture_rows
    )
    results_sha256 = sha256(results_bytes).hexdigest()
    (translation / "results.jsonl").write_bytes(results_bytes)
    summary = {
        "schema_version": "guide-final-real-translation-summary-v1",
        "passed": True,
        "trajectory_count": 12,
        "critical_trajectory_count": 12,
        "critical_trajectory_passed": 12,
        "expected_turn_count": 48,
        "turn_count": len(capture_rows),
        "provider_call_count": len(capture_rows),
        "stopped_early": False,
        "passed_turn_count": len(capture_rows),
        "schema_valid_count": len(capture_rows),
        "translation_passed_count": len(capture_rows),
        "source_grounded_count": len(capture_rows),
        "binding_passed_count": len(capture_rows),
        "task_plan_passed_count": len(capture_rows),
        "recommendation_mode_passed_count": len(capture_rows),
        "wrong_binding_count": 0,
        "wrong_product_or_image_binding_count": 0,
        "unsafe_downgrade_count": 0,
        "internal_language_count": 0,
        "internal_public_language_count": 0,
        "serious_failure_count": 0,
        "results_sha256": results_sha256,
    }
    summary_bytes = _canonical_bytes(summary)
    (translation / "summary.json").write_bytes(summary_bytes)
    (translation / "SHA256SUMS").write_text(
        (
            f"{results_sha256}  results.jsonl\n"
            f"{sha256(summary_bytes).hexdigest()}  summary.json\n"
        ),
        encoding="ascii",
    )

    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps(
            {
                "schema_version": "guide-task11-readiness-v1",
                "plan_revision": "2026-08-23-task11-r5",
                "candidate_head": _HEAD,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.json"
    context = attempt_root / "attempt-context.json"
    attempt: dict[str, object] = {
        "attempt_id": "translation-attempt-01",
        "plan_revision": "2026-08-23-task11-r5",
        "repair_epoch": 8,
        "retry_authorization_id": "auth-translation",
        "code_revision": _HEAD,
        "started_at": "2026-08-23T00:00:00Z",
        "trajectory_set": "translation",
        "first_failure_turn_id": None,
        "first_failure_owner": None,
        "failure_code": None,
        "evidence_directory": str(attempt_root.resolve()),
        "local_reproduction": None,
        "focused_test": None,
        "shared_owner_repair": None,
        "independent_audit": None,
        "result": "passed",
        "context_path": str(context.resolve()),
    }
    context_payload = {
        "schema_version": "guide-smoke-attempt-context-v1",
        "context_id": "context_backend_replay",
        "parent_attempt_id": None,
        "phase_attempt_ids": {
            "translation": "translation-attempt-01",
        },
        "phase_authorization_ids": {
            "translation": "auth-translation",
        },
        "output_directory": str(attempt_root.resolve()),
        "readiness_path": str(readiness.resolve()),
        "readiness_sha256": sha256(readiness.read_bytes()).hexdigest(),
        "ledger_path": str(ledger.resolve()),
        "allocated_ledger_revision": 1,
        "attempt_record_sha256": _attempt_allocation_sha256(
            attempt
        ),
    }
    context.write_bytes(_canonical_bytes(context_payload))
    attempt["context_sha256"] = sha256(context.read_bytes()).hexdigest()
    ledger.write_text(
        json.dumps(
            {
                "schema_version": "guide-smoke-attempt-ledger-v1",
                "revision": 1,
                "attempts": [attempt],
                "authorizations": [],
                "circuit_state": "closed",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return context


def test_replay_runs_all_captured_meanings_through_real_http_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    context = _attempt_context(tmp_path, capture_rows)
    context_before = context.read_bytes()
    monkeypatch.setenv("GUIDE_LLM_API_KEY", "must-not-call")
    monkeypatch.setenv("GUIDE_COPY_LLM_API_KEY", "must-not-call")

    report = replay_final_real_backend(
        cases_path=fixture,
        attempt_context_path=context,
        phase="backend",
        repo_root=Path.cwd(),
    )

    assert report.passed is True
    assert report.turn_count == 48
    assert report.completed_turn_count == 48
    assert report.translation_injection_count == 48
    assert report.provider_call_count == 0
    assert report.copywriter_call_count == 0
    assert report.non_clarification_turn_count == 47
    assert report.presentation_contract_count == 47
    assert report.clarification_turn_count == 1
    assert report.message_event_count == 0
    assert report.wrong_responsibility_count == 0
    assert report.wrong_binding_count == 0
    assert report.wrong_product_count == 0
    assert report.price_specification_mismatch_count == 0
    assert report.section_order_violation_count == 0
    assert report.raw_ad_leak_count == 0
    assert report.internal_language_count == 0
    assert report.serious_failure_count == 0
    assert context.read_bytes() == context_before
    assert (context.parent / "real-backend" / "results.jsonl").is_file()
    assert (context.parent / "real-backend" / "summary.json").is_file()
    assert (context.parent / "real-backend" / "SHA256SUMS").is_file()
    assert os.environ["GUIDE_LLM_API_KEY"] == "must-not-call"
    assert os.environ["GUIDE_COPY_LLM_API_KEY"] == "must-not-call"


def test_replay_rejects_anything_other_than_all_48_captured_meanings(
    tmp_path: Path,
) -> None:
    fixture, capture_rows = _fixture_and_capture(
        tmp_path,
        capture_count=47,
    )
    context = _attempt_context(tmp_path, capture_rows)

    with pytest.raises(
        BackendReplayError,
        match="exactly 48 captured meanings",
    ):
        replay_final_real_backend(
            cases_path=fixture,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )

    assert not (context.parent / "real-backend").exists()


def test_replay_rejects_missing_recommendation_mode_proof(
    tmp_path: Path,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    capture_rows[0].pop("recommendation_mode_passed")
    context = _attempt_context(tmp_path, capture_rows)

    with pytest.raises(
        BackendReplayError,
        match="failed row",
    ):
        replay_final_real_backend(
            cases_path=fixture,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )


def test_replay_rejects_tampered_attempt_context(
    tmp_path: Path,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    context = _attempt_context(tmp_path, capture_rows)
    payload = json.loads(context.read_text(encoding="utf-8"))
    payload["output_directory"] = str(tmp_path / "redirected")
    context.write_bytes(_canonical_bytes(payload))

    with pytest.raises(
        BackendReplayError,
        match="attempt context",
    ):
        replay_final_real_backend(
            cases_path=fixture,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )


def test_replay_source_uses_only_real_unified_http_entrypoint() -> None:
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
    }
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert "app.guide_runtime.app" in imported_modules
    assert "app.guide_runtime.composition" in imported_modules
    assert "/api/v1/chat/stream" in source
    assert "tools.guide_gates.run_task11_production_path_matrix" not in (
        imported_modules
    )
    assert "app.guide.intent.executable_intent_compiler" not in (
        imported_modules
    )
    assert "app.guide.intent.unified_turn_router" not in imported_modules
    assert "slice1_backend" not in source
