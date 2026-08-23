from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path

import pytest

from tools.guide_gates import attempt_ledger


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _readiness(tmp_path: Path) -> tuple[Path, Path]:
    audit = tmp_path / "independent-audit.json"
    _write_json(
        audit,
        {
            "schema_version": "guide-task11-independent-audit-v1",
            "passed": True,
            "plan_revision": "task11-r1",
            "first_failure_owner": "presentation_provenance",
            "repair_epoch": 1,
            "protected_payload_sha256": "b" * 64,
            "local_reproduction": (
                "tests/guide/presentation/test_presentation_compiler.py"
            ),
            "focused_test": "test_image_identity_is_authoritative",
            "shared_owner_repair": (
                "app/guide/presentation/presentation_compiler.py"
            ),
        },
    )
    readiness = tmp_path / "readiness.json"
    _write_json(
        readiness,
        {
            "schema_version": "guide-task11-readiness-v1",
            "plan_revision": "task11-r1",
            "candidate_head": "a" * 40,
            "candidate_payload_sha256": "c" * 64,
            "protected_payload_sha256": "b" * 64,
            "step_0_passed": True,
            "step_0_5_passed": True,
            "step_4_5_passed": True,
            "affected_zero_api_passed": True,
            "desktop_fixture_passed": True,
            "mobile_fixture_passed": True,
            "invalid_clarification_count": 0,
            "circuit_state": "closed",
            "evidence_files": {
                "independent_audit": str(audit),
            },
            "evidence_sha256": {
                "independent_audit": sha256(
                    audit.read_bytes()
                ).hexdigest(),
            },
        },
    )
    return readiness, audit


def _historical_failure() -> dict[str, object]:
    return {
        "attempt_id": "bounded-smoke-attempt-01",
        "plan_revision": "task11-r1",
        "repair_epoch": 0,
        "retry_authorization_id": "historical-unavailable",
        "code_revision": "historical-unavailable",
        "started_at": "2026-08-21T00:00:00Z",
        "trajectory_set": "bounded",
        "first_failure_turn_id": "bounded-image-context-t1",
        "first_failure_owner": "presentation_provenance",
        "failure_code": "image_identity_marked_fallback",
        "evidence_directory": "historical-unavailable",
        "local_reproduction": None,
        "focused_test": None,
        "shared_owner_repair": None,
        "independent_audit": None,
        "result": "failed",
        "context_path": None,
    }


def _allocated_context(tmp_path: Path) -> tuple[Path, Path, Path]:
    ledger = tmp_path / "ledger.json"
    readiness, audit = _readiness(tmp_path)
    attempt_ledger.initialize_ledger(
        ledger,
        attempts=(_historical_failure(),),
    )
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    context = attempt_ledger.allocate_attempt(
        phase="bounded",
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=tmp_path / "attempts",
    )
    return ledger, readiness, context


def test_authorization_is_consumed_once_and_context_is_immutable(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    before = context.read_bytes()

    consumed = attempt_ledger.consume_attempt_context(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
    )

    assert consumed["phase_attempt_ids"]["bounded"].startswith(
        "bounded-smoke-attempt-"
    )
    assert context.read_bytes() == before
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="already consumed",
    ):
        attempt_ledger.consume_attempt_context(
            context,
            phase="bounded",
            ledger_path=ledger,
            readiness_path=readiness,
        )


def test_attempt_context_rejects_content_tampering(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    payload = json.loads(context.read_text(encoding="utf-8"))
    payload["output_directory"] = str(tmp_path / "redirected")
    _write_json(context, payload)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="context content mismatch",
    ):
        attempt_ledger.read_attempt_context(
            context,
            ledger_path=ledger,
            readiness_path=readiness,
        )


def test_authorization_rejects_readiness_without_full_verification(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    readiness, audit = _readiness(tmp_path)
    attempt_ledger.initialize_ledger(
        ledger,
        attempts=(_historical_failure(),),
    )

    with pytest.raises(ValueError, match="readiness evidence binding"):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
        )


def test_two_concurrent_consumers_only_one_succeeds(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)

    def consume() -> str:
        try:
            attempt_ledger.consume_attempt_context(
                context,
                phase="bounded",
                ledger_path=ledger,
                readiness_path=readiness,
            )
        except attempt_ledger.AttemptLedgerError:
            return "rejected"
        return "consumed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: consume(), range(2)))

    assert sorted(outcomes) == ["consumed", "rejected"]


def test_compare_and_swap_rejects_stale_revision(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="stale ledger revision",
    ):
        attempt_ledger.compare_and_swap_ledger(
            ledger,
            expected_revision=7,
            mutate=lambda payload: payload,
        )


def test_init_cli_requires_explicit_historical_attempts() -> None:
    with pytest.raises(SystemExit):
        attempt_ledger._parser().parse_args(
            ["init", "--ledger", "/tmp/ledger.json"]
        )


def test_orphan_temporary_file_is_recovered_only_from_valid_ledger(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    orphan = attempt_ledger.ledger_temp_path(ledger)
    orphan.write_text('{"incomplete":', encoding="utf-8")

    payload = attempt_ledger.read_ledger(ledger)

    assert payload["revision"] == 0
    assert not orphan.exists()
    ledger.write_text('{"broken":', encoding="utf-8")
    orphan.write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="canonical ledger is invalid",
    ):
        attempt_ledger.read_ledger(ledger)
    assert orphan.exists()


def test_interruption_after_temporary_write_preserves_canonical_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    before = ledger.read_bytes()

    def interrupted_replace(source: object, target: object) -> None:
        del source, target
        raise OSError("simulated interruption")

    monkeypatch.setattr(
        attempt_ledger.os,
        "replace",
        interrupted_replace,
    )
    with pytest.raises(OSError, match="simulated interruption"):
        attempt_ledger.compare_and_swap_ledger(
            ledger,
            expected_revision=0,
            mutate=lambda payload: payload,
        )

    assert ledger.read_bytes() == before
    assert attempt_ledger.ledger_temp_path(ledger).is_file()
    monkeypatch.undo()
    assert attempt_ledger.read_ledger(ledger)["revision"] == 0
    assert not attempt_ledger.ledger_temp_path(ledger).exists()


def test_second_same_owner_failure_opens_circuit(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    attempt_ledger.consume_attempt_context(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    attempt_ledger.complete_attempt(
        context,
        result="failed",
        first_failure_turn_id="bounded-image-context-t1",
        first_failure_owner="presentation_provenance",
        failure_code="image_identity_marked_fallback",
        evidence_directory="bounded-smoke-attempt-02",
        local_reproduction="tests/guide/presentation/test_presentation_compiler.py",
        focused_test="test_image_identity_is_authoritative",
        shared_owner_repair="app/guide/presentation/presentation_compiler.py",
        independent_audit="task11-independent-audit.json",
    )

    assert (
        attempt_ledger.read_ledger(ledger)["circuit_state"]
        == "open"
    )
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="circuit is open",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=tmp_path / "independent-audit.json",
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def test_new_failure_owner_starts_at_repair_epoch_one(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    attempt_ledger.consume_attempt_context(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    attempt_ledger.complete_attempt(
        context,
        result="failed",
        first_failure_turn_id="bounded-text-fit-t1",
        first_failure_owner="planning_state",
        failure_code="invalid_fit_clarification",
        evidence_directory=str(context.parent),
    )
    audit_path = tmp_path / "independent-audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["first_failure_owner"] = "planning_state"
    audit["repair_epoch"] = 1
    _write_json(audit_path, audit)
    readiness_payload = json.loads(
        readiness.read_text(encoding="utf-8")
    )
    readiness_payload["evidence_sha256"]["independent_audit"] = (
        sha256(audit_path.read_bytes()).hexdigest()
    )
    _write_json(readiness, readiness_payload)

    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit_path,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    assert authorization_id.startswith("auth_")
    authorization = attempt_ledger.read_ledger(ledger)[
        "authorizations"
    ][-1]
    assert authorization["first_failure_owner"] == "planning_state"
    assert authorization["repair_epoch"] == 1


def test_latest_does_not_search_backward_past_newer_failure(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    readiness, _ = _readiness(tmp_path)
    attempt_ledger.initialize_ledger(
        ledger,
        attempts=(
            {
                **_historical_failure(),
                "attempt_id": "bounded-smoke-attempt-01",
                "result": "passed",
            },
            {
                **_historical_failure(),
                "attempt_id": "bounded-smoke-attempt-02",
                "first_failure_owner": "planning_state",
                "result": "failed",
            },
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="latest attempt result mismatch",
    ):
        attempt_ledger.latest_attempt_context(
            phase="bounded",
            result="passed",
            readiness_path=readiness,
            ledger_path=ledger,
        )


def test_failure_reclassification_requires_bound_independent_evidence(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "bounded-smoke-attempt-03" / "turn"
    evidence.mkdir(parents=True)
    evidence_files = (
        "request.json",
        "stream.sse",
        "presentation-contract.json",
        "terminal-dom.json",
        "screenshot.png",
        "console.json",
        "network.json",
    )
    for name in evidence_files:
        (evidence / name).write_bytes(f"{name}\n".encode())
    repair_evidence = tmp_path / "repair-epoch-03"
    repair_evidence.mkdir()
    repair_evidence_files = {
        "pre_fix_reproduction": (
            repair_evidence / "pre-fix.xml"
        ),
        "post_fix_verification": (
            repair_evidence / "post-fix.xml"
        ),
        "focused_zero_api": (
            repair_evidence / "focused.xml"
        ),
        "repair_patch": (
            repair_evidence / "repair.patch"
        ),
    }
    for name, path in repair_evidence_files.items():
        path.write_bytes(f"{name}\n".encode())
    readiness = repair_evidence / "readiness.json"
    _write_json(
        readiness,
        {
            "protected_payload_sha256": "d" * 64,
        },
    )
    historical = {
        **_historical_failure(),
        "attempt_id": "bounded-smoke-attempt-03",
        "first_failure_turn_id": "bounded-text-context-t1",
        "first_failure_owner": "dom_rendering",
        "failure_code": "AuditBundleError",
        "evidence_directory": str(evidence),
        "context_path": str(
            evidence.parent / "attempt-context.json"
        ),
    }
    attempt_context = {
        "schema_version": "guide-smoke-attempt-context-v1",
        "attempt_record_sha256": (
            attempt_ledger._attempt_allocation_sha256(historical)
        ),
        "readiness_path": str(readiness.resolve()),
        "readiness_sha256": sha256(
            readiness.read_bytes()
        ).hexdigest(),
    }
    _write_json(Path(historical["context_path"]), attempt_context)
    historical["context_sha256"] = sha256(
        Path(historical["context_path"]).read_bytes()
    ).hexdigest()
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(
        ledger,
        attempts=(
            {
                **_historical_failure(),
                "attempt_id": "bounded-smoke-attempt-02",
                "first_failure_owner": "planning_state",
            },
            historical,
        ),
    )
    audit = tmp_path / "failure-reclassification.json"
    _write_json(
        audit,
        {
            "schema_version": (
                "guide-smoke-failure-reclassification-v1"
            ),
            "passed": True,
            "plan_revision": "task11-r1",
            "attempt_id": "bounded-smoke-attempt-03",
            "evidence_directory": str(evidence.resolve()),
            "first_failure_turn_id": "bounded-text-context-t1",
            "code_revision": "historical-unavailable",
            "attempt_context_sha256": historical["context_sha256"],
            "attempt_record_sha256": (
                attempt_context["attempt_record_sha256"]
            ),
            "readiness_path": str(readiness.resolve()),
            "readiness_sha256": attempt_context["readiness_sha256"],
            "protected_payload_sha256": "d" * 64,
            "pre_reclassification_ledger_revision": 0,
            "previous_failure_owner": "dom_rendering",
            "previous_failure_code": "AuditBundleError",
            "first_failure_owner": "planning_state",
            "failure_code": "missing_explore_result_count_default",
            "reviewed_evidence_sha256": {
                name: sha256((evidence / name).read_bytes()).hexdigest()
                for name in evidence_files
            },
            "evidence_bundle_sha256": (
                attempt_ledger._failure_evidence_sha256(evidence)
            ),
            "repair_evidence_files": {
                name: str(path.resolve())
                for name, path in repair_evidence_files.items()
            },
            "repair_evidence_sha256": {
                name: sha256(path.read_bytes()).hexdigest()
                for name, path in repair_evidence_files.items()
            },
            "conclusion": (
                "The raw error terminal is reproduced at the planning "
                "boundary with a legal omitted explore count."
            ),
        },
    )

    updated = attempt_ledger.reclassify_failed_attempt(
        ledger_path=ledger,
        attempt_id="bounded-smoke-attempt-03",
        independent_audit_path=audit,
    )

    assert updated["first_failure_owner"] == "planning_state"
    assert updated["failure_code"] == (
        "missing_explore_result_count_default"
    )
    assert updated["failure_reclassifications"] == [{
        "previous_failure_owner": "dom_rendering",
        "previous_failure_code": "AuditBundleError",
        "first_failure_owner": "planning_state",
        "failure_code": "missing_explore_result_count_default",
        "first_failure_turn_id": "bounded-text-context-t1",
        "code_revision": "historical-unavailable",
        "evidence_bundle_sha256": (
            attempt_ledger._failure_evidence_sha256(evidence)
        ),
        "reviewed_evidence_sha256": {
            name: sha256((evidence / name).read_bytes()).hexdigest()
            for name in evidence_files
        },
        "attempt_context_sha256": historical["context_sha256"],
        "attempt_record_sha256": attempt_context[
            "attempt_record_sha256"
        ],
        "readiness_path": str(readiness.resolve()),
        "readiness_sha256": attempt_context["readiness_sha256"],
        "protected_payload_sha256": "d" * 64,
        "repair_evidence_files": {
            name: str(path.resolve())
            for name, path in repair_evidence_files.items()
        },
        "repair_evidence_sha256": {
            name: sha256(path.read_bytes()).hexdigest()
            for name, path in repair_evidence_files.items()
        },
        "pre_reclassification_ledger_revision": 0,
        "independent_audit_path": str(audit.resolve()),
        "independent_audit_sha256": sha256(
            audit.read_bytes()
        ).hexdigest(),
    }]
    assert attempt_ledger.read_ledger(ledger)["circuit_state"] == "open"
    (evidence / "screenshot.png").write_bytes(b"tampered\n")
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="reclassification evidence mismatch",
    ):
        attempt_ledger.read_ledger(ledger)


def test_passed_phase_cannot_be_authorized_again(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    attempt_ledger.consume_attempt_context(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    attempt_ledger.complete_attempt(context, result="passed")

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="phase already passed",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=tmp_path / "independent-audit.json",
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )
