from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
from tempfile import gettempdir
from threading import Event, Thread
import zlib

import pytest

from tools.guide_gates import attempt_ledger


@pytest.fixture(autouse=True)
def _unit_readiness_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        attempt_ledger,
        "_verify_current_readiness",
        lambda **_: None,
    )


def _png_bytes(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(
                ">I",
                zlib.crc32(kind + payload) & 0xFFFFFFFF,
            )
        )

    pixels = b"".join(
        b"\x00"
        + bytes(
            (
                row % 256,
                (row * 3) % 256,
                (row * 7) % 256,
            )
        )
        * width
        for row in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _force_valid_ledger_mutation(
    path: Path,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    """Build a hash-valid hostile ledger without a production mutation API."""
    payload = attempt_ledger.read_ledger(path)
    mutate(payload)
    payload["revision"] += 1
    payload["circuit_state"] = attempt_ledger._circuit_state(payload)
    attempt_ledger._append_revision(
        payload,
        operation="compare_and_swap",
    )
    attempt_ledger._atomic_write_ledger(path, payload)


def _readiness(
    tmp_path: Path,
    *,
    ledger: Path | None = None,
) -> tuple[Path, Path]:
    canonical_ledger = (
        ledger.resolve()
        if ledger is not None
        else (tmp_path / "ledger.json").resolve()
    )
    anchor = (
        attempt_ledger.ledger_anchor(
            attempt_ledger.read_ledger(ledger)
        )
        if ledger is not None
        else {"revision": 0, "revision_hash": "a" * 64}
    )
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
            "reviewed_candidate_manifest_sha256": "a" * 64,
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
            "ledger_anchor_revision": anchor["revision"],
            "ledger_anchor_hash": anchor["revision_hash"],
            "ledger_path": str(canonical_ledger),
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


def _checkpoint_manifest(
    tmp_path: Path,
    ledger: Path,
    *,
    repair_epoch: int = 1,
) -> Path:
    payload, source_bytes = attempt_ledger.read_ledger_checkpoint_source(
        ledger
    )
    tip = payload["revision_chain"][-1]
    manifest = (
        tmp_path
        / "docs/audits/final-release/mainline-contract-closure"
        / f"repair-epoch-{repair_epoch}"
        / "task11-candidate-manifest.json"
    )
    _write_json(
        manifest,
        {
            "schema_version": "guide-task11-candidate-manifest-v1",
            "repository_root": str(tmp_path.resolve()),
            "repair_epoch": repair_epoch,
            "mutable_evidence_paths": [
                ledger.relative_to(tmp_path).as_posix()
            ],
            "pre_checkpoint_ledger": {
                "path": str(ledger.resolve()),
                "sha256": sha256(source_bytes).hexdigest(),
                "revision": tip["revision"],
                "revision_hash": tip["revision_hash"],
            },
        },
    )
    return manifest


def _init_git_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=root,
        check=True,
    )


def _write_uncheckpointed_ledger(ledger: Path) -> None:
    state = {
        "schema_version": "guide-smoke-attempt-ledger-v1",
        "revision": 0,
        "circuit_state": "closed",
        "attempts": [],
        "authorizations": [],
    }
    initial = {
        "revision": 0,
        "previous_hash": None,
        "operation": "initialized",
        "attempt_id": None,
        "authorization_id": None,
        "source_sha256": None,
        "state_sha256": sha256(
            attempt_ledger._canonical_bytes(state)
        ).hexdigest(),
    }
    initial["revision_hash"] = sha256(
        attempt_ledger._canonical_bytes(initial)
    ).hexdigest()
    _write_json(
        ledger,
        {
            **state,
            "revision_chain": [initial],
        },
    )


def _allocated_context(
    tmp_path: Path,
    *,
    phase: attempt_ledger.Phase = "bounded",
) -> tuple[Path, Path, Path]:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase=phase,
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    context = attempt_ledger.allocate_attempt(
        phase=phase,
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=tmp_path / "attempts",
    )
    return ledger, readiness, context


def test_attempt_context_binds_reviewed_manifest_sha256(
    tmp_path: Path,
) -> None:
    ledger, _, context = _allocated_context(tmp_path)
    context_payload = json.loads(context.read_text(encoding="utf-8"))
    ledger_payload = attempt_ledger.read_ledger(ledger)

    assert context_payload["expected_manifest_sha256"] == "a" * 64
    assert ledger_payload["authorizations"][0][
        "expected_manifest_sha256"
    ] == "a" * 64
    assert ledger_payload["attempts"][0][
        "expected_manifest_sha256"
    ] == "a" * 64


def _consume_runtime_bound_for_test(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ledger: Path,
    readiness: Path,
    context: Path,
) -> dict[str, str]:
    from tools.guide_gates.runtime_auth import (
        generate_runtime_keypair,
        sign_runtime_proof,
    )

    context_payload = json.loads(context.read_text(encoding="utf-8"))
    attempt_id = context_payload["phase_attempt_ids"]["bounded"]
    private_key, public_key = generate_runtime_keypair()
    registration_id = "runtime_0123456789abcdef"
    identity_path = context.parent / "runtime-identity.json"
    identity = {
        "schema_version": "guide-bound-runtime-identity-v1",
        "phase": "bounded",
        "attempt_id": attempt_id,
        "attempt_context_path": str(context.resolve()),
        "attempt_context_sha256": sha256(
            context.read_bytes()
        ).hexdigest(),
        "readiness_sha256": sha256(
            readiness.read_bytes()
        ).hexdigest(),
        "ledger_path": str(ledger.resolve()),
        "allocated_ledger_revision": context_payload[
            "allocated_ledger_revision"
        ],
        "allocated_ledger_hash": context_payload[
            "allocated_ledger_hash"
        ],
        "runtime_registration_id": registration_id,
        "runtime_public_key": public_key,
        "process_identity": {"pid": 4100, "parent_pid": 4099},
        "host": "127.0.0.1",
        "port": 8821,
    }
    identity_path.write_bytes(attempt_ledger._canonical_bytes(identity))
    runtime_identity_sha256 = sha256(
        identity_path.read_bytes()
    ).hexdigest()
    attempt_ledger.register_runtime_bound_attempt(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
        registration_id=registration_id,
        runtime_identity_sha256=runtime_identity_sha256,
        runtime_public_key=public_key,
        host="127.0.0.1",
        port=8821,
    )
    monkeypatch.setattr(
        attempt_ledger,
        "_verify_live_bound_runtime_identity",
        lambda **_: identity,
    )
    monkeypatch.setattr(
        attempt_ledger,
        "_request_live_runtime_proof",
        lambda *, request, **_: sign_runtime_proof(
            private_key=private_key,
            public_key=public_key,
            request=request,
        ),
    )
    return attempt_ledger.consume_runtime_bound_attempt(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
        base_url="http://127.0.0.1:8821",
    )


def _write_passed_bounded_evidence(
    context_path: Path,
    *,
    runtime_proof: dict[str, str] | None = None,
) -> None:
    from tools.guide_gates import (
        run_mainline_contract_browser_audit as browser_audit,
    )

    context = json.loads(context_path.read_text(encoding="utf-8"))
    attempt_root = Path(context["output_directory"])
    identity_path = attempt_root / browser_audit.RUNTIME_IDENTITY_FILENAME
    if not identity_path.exists():
        identity_path.write_text('{"runtime":"test"}\n', encoding="utf-8")
    browser_root = attempt_root / "browser-desktop"
    browser_root.mkdir()
    fixture_by_mode = {
        ("recommendation", "fit"): "fixture-fit-recommendation",
        ("recommendation", "explore"): (
            "fixture-explore-recommendation"
        ),
        ("product_knowledge", None): "fixture-product-knowledge",
        ("comparison", None): "fixture-comparison",
        ("image_identity", None): "fixture-image-identity",
    }
    trajectory_rows: list[dict[str, object]] = []
    for trajectory in browser_audit.BOUNDED_TRAJECTORIES:
        turn_rows: list[dict[str, object]] = []
        trajectory_dir = browser_root / trajectory.trajectory_id
        trajectory_dir.mkdir()
        for turn in trajectory.turns:
            fixture_mode = (
                "product_knowledge"
                if turn.expected_mode == "consultation"
                else turn.expected_mode
            )
            fixture_id = fixture_by_mode[
                (fixture_mode, turn.expected_recommendation_mode)
            ]
            raw = browser_audit.fixture_sse_bytes(fixture_id)
            if turn.expected_mode == "consultation":
                raw = raw.replace(
                    b'"mode":"product_knowledge"',
                    b'"mode":"consultation"',
                )
            if turn.expected_image_product_id is not None:
                observation = browser_audit._fixture_image_observation(
                    image_ordinal=1,
                    product_id=turn.expected_image_product_id,
                    alternate_product_id=91,
                )
                image_event = (
                    "event: image_observation\n"
                    "data: "
                    + json.dumps(
                        {"observation": observation},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n\n"
                ).encode("utf-8")
                raw = raw.replace(
                    b"event: presentation_contract\n",
                    image_event + b"event: presentation_contract\n",
                    1,
                )
            events = browser_audit._sse_events_from_sse(
                raw.decode("utf-8")
            )
            contract = next(
                payload
                for event, payload in events
                if event == "presentation_contract"
            )
            turn_dir = trajectory_dir / turn.turn_id
            turn_dir.mkdir()
            request_id = (
                f"request-{trajectory.trajectory_id}-{turn.turn_id}"
            )
            _write_json(
                turn_dir / "request.json",
                {
                    "turn_id": (
                        f"{trajectory.trajectory_id}-{turn.turn_id}"
                    ),
                    "request_id": request_id,
                    "viewport": browser_audit.VIEWPORTS["desktop"],
                    "user_message": turn.message,
                },
            )
            (turn_dir / "stream.sse").write_bytes(raw)
            _write_json(
                turn_dir / "presentation-contract.json",
                contract,
            )
            sections = tuple(contract.get("sections", ()))
            _write_json(
                turn_dir / "terminal-dom.json",
                {
                    "request_id": request_id,
                    "presentation_mode": contract["mode"],
                    "legacy_message_count": 0,
                    "legacy_product_card_count": 0,
                    "turn_presentation_root_count": 1,
                    "visible_section_kinds": [
                        section["kind"] for section in sections
                    ],
                    "section_blocks": [
                        {
                            "kind": section["kind"],
                            "text": " ".join(
                                browser_audit._required_section_text(
                                    section
                                )
                            ),
                        }
                        for section in sections
                    ],
                    "inline_product_ids": [
                        section["product_id"]
                        for section in sections
                        if section["kind"] == "product"
                    ],
                    "visible_product_ids": contract[
                        "visible_product_ids"
                    ],
                    "shelf_product_ids": contract[
                        "visible_product_ids"
                    ],
                    "comparison_table_count": int(
                        contract["mode"] == "comparison"
                    ),
                    "presentation_text": " ".join(
                        browser_audit.required_public_text(sections)
                    ),
                },
            )
            (turn_dir / "screenshot.png").write_bytes(
                _png_bytes(1440, 1000)
            )
            _write_json(turn_dir / "console.json", [])
            _write_json(turn_dir / "network.json", [])
            turn_rows.append({
                "turn_id": turn.turn_id,
                "directory": (
                    f"{trajectory.trajectory_id}/{turn.turn_id}"
                ),
            })
        trajectory_report = {
            "trajectory_id": trajectory.trajectory_id,
            "turns": turn_rows,
            "turn_count": len(turn_rows),
            "invalid_clarification_count": 0,
        }
        _write_json(
            trajectory_dir / "summary.json",
            trajectory_report,
        )
        trajectory_rows.append(trajectory_report)
    summary_path = browser_root / "summary.json"
    _write_json(
        summary_path,
        {
            "schema_version": (
                "guide-mainline-contract-browser-audit-v1"
            ),
            "trajectory_set": "bounded",
            "base_url": "http://127.0.0.1:8821",
            "viewport": "desktop",
            "trajectories": trajectory_rows,
            "turn_count": 9,
            "invalid_clarification_count": 0,
            "passed": True,
            "runtime_identity_sha256": sha256(
                identity_path.read_bytes()
            ).hexdigest(),
            "runtime_proof_sha256": (
                runtime_proof["runtime_proof_sha256"]
                if runtime_proof is not None
                else "f" * 64
            ),
            "runtime_attestation_sha256": (
                runtime_proof["runtime_attestation_sha256"]
                if runtime_proof is not None
                else "e" * 64
            ),
            "artifact_sha256_by_path": (
                browser_audit._artifact_sha256_by_path(
                    browser_root,
                    excluded={summary_path},
                )
            ),
        },
    )


def _passed_translation_context(
    tmp_path: Path,
    *,
    result: str = "passed",
) -> tuple[Path, Path, Path, Path]:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="translation",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    context = attempt_ledger.allocate_attempt(
        phase="translation",
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=tmp_path / "attempts",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    if result == "passed":
        _write_passed_translation_evidence(context)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                attempt_ledger,
                "_validate_passed_translation_evidence",
                lambda _: None,
            )
            attempt_ledger.complete_attempt(context, result="passed")
    else:
        attempt_ledger.complete_attempt(
            context,
            result="failed",
            first_failure_turn_id="translation-01",
            first_failure_owner="translation",
            failure_code="translation_failed",
            evidence_directory=str(context.parent),
        )
    return ledger, readiness, audit, context


def _write_passed_translation_evidence(
    parent: Path,
) -> tuple[Path, Path, Path, Path]:
    attempt_root = parent.parent
    focused = attempt_root / "focused.json"
    _write_json(
        focused,
        {
            "schema_version": "guide-final-focused-gate-v1",
            "passed": True,
        },
    )
    translation = attempt_root / "real-translation"
    translation.mkdir(exist_ok=True)
    translation_results = translation / "results.jsonl"
    translation_results.write_text(
        "".join(
            json.dumps(
                {
                    "turn_id": f"translation-turn-{index:02d}",
                    "passed": True,
                },
                sort_keys=True,
            )
            + "\n"
            for index in range(48)
        ),
        encoding="utf-8",
    )
    fixture_path = (
        "tests/fixtures/guide/final_release/"
        "real_translation_12x4_v5.jsonl"
    )
    fixture_sha256 = sha256(Path(fixture_path).read_bytes()).hexdigest()
    translation_summary = translation / "summary.json"
    _write_json(
        translation_summary,
        {
            "schema_version": "guide-final-real-translation-summary-v1",
            "passed": True,
            "expected_turn_count": 48,
            "turn_count": 48,
            "passed_turn_count": 48,
            "schema_valid_count": 48,
            "translation_passed_count": 48,
            "source_grounded_count": 48,
            "binding_passed_count": 48,
            "task_plan_passed_count": 48,
            "recommendation_mode_passed_count": 48,
            "provider_call_count": 48,
            "stopped_early": False,
            "wrong_binding_count": 0,
            "wrong_product_or_image_binding_count": 0,
            "unsafe_downgrade_count": 0,
            "internal_language_count": 0,
            "internal_public_language_count": 0,
            "serious_failure_count": 0,
            "focused_summary_sha256": sha256(
                focused.read_bytes()
            ).hexdigest(),
            "fixture_path": fixture_path,
            "fixture_sha256": fixture_sha256,
            "results_sha256": sha256(
                translation_results.read_bytes()
            ).hexdigest(),
        },
    )
    translation_checksums = translation / "SHA256SUMS"
    translation_checksums.write_text(
        (
            f"{sha256(translation_results.read_bytes()).hexdigest()}  "
            "results.jsonl\n"
            f"{sha256(translation_summary.read_bytes()).hexdigest()}  "
            "summary.json\n"
        ),
        encoding="ascii",
    )
    return (
        focused,
        translation_results,
        translation_summary,
        translation_checksums,
    )


def _write_passed_backend_evidence(parent: Path) -> Path:
    attempt_root = parent.parent
    (
        focused,
        translation_results,
        translation_summary,
        translation_checksums,
    ) = _write_passed_translation_evidence(parent)
    fixture_path = (
        "tests/fixtures/guide/final_release/"
        "real_translation_12x4_v5.jsonl"
    )
    fixture_sha256 = sha256(Path(fixture_path).read_bytes()).hexdigest()
    backend = attempt_root / "real-backend"
    backend.mkdir()
    backend_results = backend / "results.jsonl"
    fixture_rows = [
        json.loads(line)
        for line in Path(fixture_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    image_sha256_by_product = {
        row["product_id"]: row["source_image_sha256"]
        for row in (
            json.loads(line)
            for line in Path(
                "data/canonical/seed_product_images_v1.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    backend_rows = []
    for trajectory in fixture_rows:
        for turn in trajectory["turns"]:
            clarification = (
                turn["case"]["execution"]["expected_task_mode"] == "clarify"
            )
            context_sha256 = sha256(
                json.dumps(
                    turn["case"]["context"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            event_names = (
                ["start", "intent", "clarify", "end"]
                if clarification
                else [
                    "start",
                    "intent",
                    "general_knowledge",
                    "presentation_contract",
                    "end",
                ]
            )
            terminal_payload = (
                {
                    "question": "Please clarify.",
                    "clarification_code": "goal",
                }
                if clarification
                else {
                    "responsibility": "general_knowledge",
                    "mode": "general_knowledge",
                    "recommendation_mode": None,
                    "copy_source": "fallback",
                    "sections": [{
                        "kind": "general_knowledge",
                        "copy_text": "Verified answer.",
                        "used_fact_ids": [],
                        "used_constraint_ids": [],
                        "advisor_reason": None,
                        "advisor_used_fact_ids": [],
                        "advisor_used_constraint_ids": [],
                        "slot_id": None,
                        "product_id": None,
                        "direct_facts": [],
                    }],
                    "requested_comparison_dimensions": [],
                    "comparison_rows": [],
                    "winner": {
                        "status": "not_applicable",
                        "winner_product_id": None,
                        "reason": None,
                        "fact_ids": [],
                        "dimension_ids": [],
                        "tie_reason": None,
                    },
                    "visible_product_ids": [],
                    "compact_tags": [],
                    "card_display": {
                        "mode": "none",
                        "visible_product_ids": [],
                        "max_cards": 0,
                        "reason": None,
                    },
                    "telemetry": {
                        "provider": "test",
                        "model": "deterministic",
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "latency_ms": 0.0,
                        "fallback_reason": "test",
                    },
                }
            )
            payload_by_event = {
                "start": {"session_id": turn["turn_id"]},
                "intent": {
                    "intent": (
                        "clarify" if clarification else "knowledge"
                    ),
                    "entities": {},
                    "scenario_intent": (
                        "clarify" if clarification else "knowledge"
                    ),
                    "guide": True,
                },
                "clarify": terminal_payload,
                "general_knowledge": {
                    "query": "Verified question.",
                    "citations": [],
                    "educational_only": True,
                    "medical_escalation": False,
                },
                "presentation_contract": terminal_payload,
                "end": {"conversation_version": 0},
            }
            event_payloads = tuple(
                {name: payload_by_event[name]}
                for name in event_names
            )
            raw_sse = "".join(
                (
                    f"event: {name}\n"
                    f"data: {json.dumps(payload[name], sort_keys=True)}\n\n"
                )
                for name, payload in zip(
                    event_names,
                    event_payloads,
                    strict=True,
                )
            ).encode("utf-8")
            raw_sse_path = (
                f"turns/{trajectory['trajectory_id']}/"
                f"{turn['turn_id']}/stream.sse"
            )
            stream_path = backend / raw_sse_path
            stream_path.parent.mkdir(parents=True, exist_ok=True)
            stream_path.write_bytes(raw_sse)
            backend_rows.append({
                "trajectory_id": trajectory["trajectory_id"],
                "turn_id": turn["turn_id"],
                "completed": True,
                "clarification": clarification,
                "translation_injection_count": 1,
                "image_product_ids": turn["image_product_ids"],
                "image_asset_sha256s": [
                    image_sha256_by_product[product_id]
                    for product_id in turn["image_product_ids"]
                ],
                "raw_sse_path": raw_sse_path,
                "raw_sse_sha256": sha256(raw_sse).hexdigest(),
                "sealed_context_sha256": context_sha256,
                "observed_context_sha256": context_sha256,
                "context_mismatch_count": 0,
                "provider_call_count": 0,
                "copywriter_call_count": 0,
                "presentation_contract_count": 0 if clarification else 1,
                "message_event_count": 0,
                "wrong_responsibility_count": 0,
                "wrong_binding_count": 0,
                "wrong_product_count": 0,
                "price_specification_mismatch_count": 0,
                "section_order_violation_count": 0,
                "raw_ad_leak_count": 0,
                "internal_language_count": 0,
                "unsafe_downgrade_count": 0,
                "frontend_contract_violation_count": 0,
                "expected_responsibility": (
                    "clarification" if clarification else "general_knowledge"
                ),
                "actual_responsibility": (
                    "clarification" if clarification else "general_knowledge"
                ),
                "visible_product_ids": [],
                "event_names": event_names,
                "passed": True,
            })
    backend_results.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in backend_rows
        ),
        encoding="utf-8",
    )
    clarification_count = sum(
        bool(row["clarification"]) for row in backend_rows
    )
    backend_summary = backend / "summary.json"
    _write_json(
        backend_summary,
        {
            "schema_version": "guide-final-real-backend-summary-v1",
            "context_replay_mode": "sealed_case_context",
            "stateful_transition_count": 0,
            "passed": True,
            "trajectory_count": 12,
            "critical_trajectory_count": 12,
            "critical_trajectory_passed": 12,
            "expected_turn_count": 48,
            "turn_count": 48,
            "completed_turn_count": 48,
            "passed_turn_count": 48,
            "non_clarification_turn_count": 48 - clarification_count,
            "clarification_turn_count": clarification_count,
            "translation_injection_count": 48,
            "context_mismatch_count": 0,
            "provider_call_count": 0,
            "copywriter_call_count": 0,
            "presentation_contract_count": 48 - clarification_count,
            "message_event_count": 0,
            "wrong_responsibility_count": 0,
            "wrong_binding_count": 0,
            "wrong_product_count": 0,
            "wrong_presentation_count": 0,
            "price_specification_mismatch_count": 0,
            "section_order_violation_count": 0,
            "raw_ad_leak_count": 0,
            "internal_language_count": 0,
            "internal_public_language_count": 0,
            "unsafe_downgrade_count": 0,
            "frontend_contract_violation_count": 0,
            "outbound_network_attempt_count": 0,
            "serious_failure_count": 0,
            "fixture_path": fixture_path,
            "fixture_sha256": fixture_sha256,
            "translation_results_sha256": sha256(
                translation_results.read_bytes()
            ).hexdigest(),
            "translation_summary_sha256": sha256(
                translation_summary.read_bytes()
            ).hexdigest(),
            "translation_checksums_sha256": sha256(
                translation_checksums.read_bytes()
            ).hexdigest(),
            "results_sha256": sha256(
                backend_results.read_bytes()
            ).hexdigest(),
        },
    )
    (backend / "SHA256SUMS").write_text(
        (
            f"{sha256(backend_results.read_bytes()).hexdigest()}  "
            "results.jsonl\n"
            f"{sha256(backend_summary.read_bytes()).hexdigest()}  "
            "summary.json\n"
            + "".join(
                f"{row['raw_sse_sha256']}  {row['raw_sse_path']}\n"
                for row in backend_rows
            )
        ),
        encoding="ascii",
    )
    return backend_summary


def _refresh_backend_checksums(backend_summary: Path) -> None:
    backend_results = backend_summary.parent / "results.jsonl"
    rows = [
        json.loads(line)
        for line in backend_results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    (backend_summary.parent / "SHA256SUMS").write_text(
        (
            f"{sha256(backend_results.read_bytes()).hexdigest()}  "
            "results.jsonl\n"
            f"{sha256(backend_summary.read_bytes()).hexdigest()}  "
            "summary.json\n"
            + "".join(
                f"{digest}  {path}\n"
                for path, digest in sorted({
                    str(row["raw_sse_path"]): str(
                        row["raw_sse_sha256"]
                    )
                    for row in rows
                }.items())
            )
        ),
        encoding="ascii",
    )


def test_authorization_is_consumed_once_and_context_is_immutable(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    before = context.read_bytes()
    context_payload = json.loads(before)
    ledger_payload = attempt_ledger.read_ledger(ledger)
    allocation_matches = [
        item
        for item in ledger_payload["revision_chain"]
        if (
            item["revision"]
            == context_payload["allocated_ledger_revision"]
            and item["revision_hash"]
            == context_payload["allocated_ledger_hash"]
        )
    ]

    assert len(allocation_matches) == 1
    assert allocation_matches[0]["operation"] == "attempt_allocated"
    assert allocation_matches[0]["attempt_id"] == (
        context_payload["phase_attempt_ids"]["translation"]
    )

    consumed = attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )

    assert consumed["phase_attempt_ids"]["translation"].startswith(
        "translation-attempt-"
    )
    assert context.read_bytes() == before
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="already consumed",
    ):
        attempt_ledger.consume_attempt_context(
            context,
            phase="translation",
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


def test_consumption_rejects_context_bytes_different_from_parsed_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    def split_context_decode(content: bytes, *, label: str):
        payload = json.loads(content)
        if label == "attempt context":
            payload["output_directory"] = str(tmp_path / "redirected")
        return payload

    monkeypatch.setattr(
        attempt_ledger,
        "_decode_json_object_bytes",
        split_context_decode,
        raising=False,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="context content mismatch",
    ):
        attempt_ledger.consume_attempt_context(
            context,
            phase="translation",
            ledger_path=ledger,
            readiness_path=readiness,
        )

    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "allocated"


def test_completion_rejects_context_tampering_after_consumption(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    payload = json.loads(context.read_text(encoding="utf-8"))
    payload["output_directory"] = str(tmp_path / "redirected")
    _write_json(context, payload)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="context content mismatch",
    ):
        attempt_ledger.complete_attempt(context, result="passed")

    stored = attempt_ledger.read_ledger(ledger)
    assert stored["attempts"][-1]["result"] == "consumed"


def test_completion_rejects_context_bytes_different_from_parsed_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    def split_context_decode(content: bytes, *, label: str):
        payload = json.loads(content)
        if label == "attempt context":
            payload["output_directory"] = str(tmp_path / "redirected")
        return payload

    monkeypatch.setattr(
        attempt_ledger,
        "_decode_json_object_bytes",
        split_context_decode,
        raising=False,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="context content mismatch",
    ):
        attempt_ledger.complete_attempt(context, result="passed")

    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "consumed"


def test_consumption_revalidates_readiness_before_ledger_transition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )

    def reject_readiness(**_: object) -> dict[str, object]:
        raise attempt_ledger.AttemptLedgerError(
            "readiness evidence drift"
        )

    monkeypatch.setattr(
        attempt_ledger,
        "_verify_current_readiness",
        reject_readiness,
        raising=False,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="readiness evidence drift",
    ):
        attempt_ledger.consume_attempt_context(
            context,
            phase="translation",
            ledger_path=ledger,
            readiness_path=readiness,
        )

    stored = attempt_ledger.read_ledger(ledger)
    assert stored["attempts"][-1]["result"] == "allocated"
    assert stored["authorizations"][-1]["state"] == "allocated"


def test_consumption_rejects_context_replaced_after_lock_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    real_require = attempt_ledger._require_current_readiness_binding
    calls = 0

    def replace_context(**kwargs: object) -> None:
        nonlocal calls
        real_require(**kwargs)
        calls += 1
        if calls == 1:
            payload = json.loads(context.read_text(encoding="utf-8"))
            payload["context_id"] = "context_replaced_after_lock"
            context.write_bytes(
                attempt_ledger._canonical_bytes(payload)
            )

    monkeypatch.setattr(
        attempt_ledger,
        "_require_current_readiness_binding",
        replace_context,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="context content mismatch",
    ):
        attempt_ledger.consume_attempt_context(
            context,
            phase="translation",
            ledger_path=ledger,
            readiness_path=readiness,
        )

    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "allocated"


def test_consumption_rejects_evidence_drift_after_lock_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    readiness_payload = json.loads(readiness.read_text(encoding="utf-8"))
    audit = Path(
        readiness_payload["evidence_files"]["independent_audit"]
    )
    real_require = attempt_ledger._require_current_readiness_binding
    calls = 0

    def replace_evidence(**kwargs: object) -> None:
        nonlocal calls
        real_require(**kwargs)
        calls += 1
        if calls == 1:
            audit.write_text('{"changed":true}\n', encoding="utf-8")

    monkeypatch.setattr(
        attempt_ledger,
        "_require_current_readiness_binding",
        replace_evidence,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="readiness evidence drift",
    ):
        attempt_ledger.consume_attempt_context(
            context,
            phase="translation",
            ledger_path=ledger,
            readiness_path=readiness,
        )

    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "allocated"


def test_runtime_request_authority_does_not_reverify_complete_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    _consume_runtime_bound_for_test(
        monkeypatch,
        ledger=ledger,
        readiness=readiness,
        context=context,
    )
    attempt_id = json.loads(
        context.read_text(encoding="utf-8")
    )["phase_attempt_ids"]["bounded"]

    def reject_complete_readiness(**_: object) -> None:
        raise AssertionError(
            "request authority repeated complete readiness verification"
        )

    monkeypatch.setattr(
        attempt_ledger,
        "_verify_current_readiness",
        reject_complete_readiness,
    )

    attempt_ledger.validate_runtime_request_authority(
        context,
        phase="bounded",
        attempt_id=attempt_id,
    )


def test_completion_waits_for_request_lifecycle_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    runtime_proof = _consume_runtime_bound_for_test(
        monkeypatch,
        ledger=ledger,
        readiness=readiness,
        context=context,
    )
    _write_passed_bounded_evidence(
        context,
        runtime_proof=runtime_proof,
    )
    entered = Event()
    release = Event()
    completed = Event()
    attempt_id = json.loads(
        context.read_text(encoding="utf-8")
    )["phase_attempt_ids"]["bounded"]

    def hold_request_lifecycle() -> None:
        with attempt_ledger.runtime_request_lifecycle_lease(context):
            entered.set()
            assert release.wait(timeout=5)

    def complete() -> None:
        attempt_ledger.complete_attempt(context, result="passed")
        completed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        request_future = pool.submit(hold_request_lifecycle)
        assert entered.wait(timeout=5)
        completion_future = pool.submit(complete)
        assert not completed.wait(timeout=0.2)
        release.set()
        request_future.result(timeout=5)
        completion_future.result(timeout=30)

    assert completed.is_set()
    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "passed"


def test_completion_revalidates_readiness_before_terminal_transition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )

    def reject_readiness(**_: object) -> dict[str, object]:
        raise attempt_ledger.AttemptLedgerError(
            "readiness evidence drift"
        )

    monkeypatch.setattr(
        attempt_ledger,
        "_verify_current_readiness",
        reject_readiness,
        raising=False,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="readiness evidence drift",
    ):
        attempt_ledger.complete_attempt(context, result="passed")

    stored = attempt_ledger.read_ledger(ledger)
    assert stored["attempts"][-1]["result"] == "consumed"
    assert stored["authorizations"][-1]["state"] == "consumed"


def test_completion_rejects_context_replaced_after_lock_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    real_require = attempt_ledger._require_current_readiness_binding
    calls = 0

    def replace_context(**kwargs: object) -> None:
        nonlocal calls
        real_require(**kwargs)
        calls += 1
        if calls == 1:
            payload = json.loads(context.read_text(encoding="utf-8"))
            payload["context_id"] = "context_replaced_after_lock"
            context.write_bytes(
                attempt_ledger._canonical_bytes(payload)
            )

    monkeypatch.setattr(
        attempt_ledger,
        "_require_current_readiness_binding",
        replace_context,
    )
    monkeypatch.setattr(
        attempt_ledger,
        "_validate_passed_translation_evidence",
        lambda _: None,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="context content mismatch",
    ):
        attempt_ledger.complete_attempt(context, result="passed")

    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "consumed"


def test_real_terminal_validators_reject_empty_evidence(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="translation terminal evidence is invalid",
    ):
        attempt_ledger._validate_passed_translation_evidence(tmp_path)
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="release browser terminal evidence is invalid",
    ):
        attempt_ledger._validate_passed_release_browser_evidence(tmp_path)


def test_translation_completion_requires_verified_terminal_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )

    def reject_translation(_: object) -> None:
        raise attempt_ledger.AttemptLedgerError(
            "translation terminal evidence is invalid"
        )

    monkeypatch.setattr(
        attempt_ledger,
        "_validate_passed_translation_evidence",
        reject_translation,
        raising=False,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="translation terminal evidence",
    ):
        attempt_ledger.complete_attempt(context, result="passed")

    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "consumed"


@pytest.mark.parametrize("reader", ("ledger", "latest_context"))
def test_terminal_evidence_tampering_is_rejected_on_every_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reader: str,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    terminal_artifact = context.parent / "terminal-result.json"
    _write_json(terminal_artifact, {"passed": True})
    monkeypatch.setattr(
        attempt_ledger,
        "_validate_passed_translation_evidence",
        lambda _: None,
    )
    attempt_ledger.complete_attempt(context, result="passed")
    terminal_artifact.write_text('{"passed":false}\n', encoding="utf-8")

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="terminal evidence changed",
    ):
        if reader == "ledger":
            attempt_ledger.read_ledger(ledger)
        else:
            attempt_ledger.latest_attempt_context(
                phase="translation",
                result="passed",
                readiness_path=readiness,
                ledger_path=ledger,
            )


def test_terminal_evidence_rejects_unrecorded_root_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    (context.parent / "terminal-result.json").write_text(
        '{"passed":true}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        attempt_ledger,
        "_validate_passed_translation_evidence",
        lambda _: None,
    )
    attempt_ledger.complete_attempt(context, result="passed")
    (context.parent / "added-after-completion.json").write_text(
        '{"injected":true}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="terminal evidence changed",
    ):
        attempt_ledger.read_ledger(ledger)


def test_passed_attempt_cannot_remove_terminal_evidence_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    (context.parent / "terminal-result.json").write_text(
        '{"passed":true}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        attempt_ledger,
        "_validate_passed_translation_evidence",
        lambda _: None,
    )
    attempt_ledger.complete_attempt(context, result="passed")

    def remove_manifest(payload: dict[str, object]) -> None:
        payload["attempts"][-1].pop("terminal_evidence")

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="historical ledger",
    ):
        _force_valid_ledger_mutation(ledger, remove_manifest)


def test_failed_completion_requires_existing_hashed_evidence(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="failure evidence",
    ):
        attempt_ledger.complete_attempt(
            context,
            result="failed",
            first_failure_turn_id="translation-t1",
            first_failure_owner="translation",
            failure_code="provider_failure",
            evidence_directory=str(tmp_path / "missing-evidence"),
        )

    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "consumed"


def test_bounded_completion_rejects_pass_without_browser_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    _consume_runtime_bound_for_test(
        monkeypatch,
        ledger=ledger,
        readiness=readiness,
        context=context,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="bounded browser evidence is invalid",
    ):
        attempt_ledger.complete_attempt(context, result="passed")

    stored = attempt_ledger.read_ledger(ledger)
    assert stored["attempts"][-1]["result"] == "consumed"


def test_bounded_consumption_rejects_non_runtime_entrypoint(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="live runtime attestation",
    ):
        attempt_ledger.consume_attempt_context(
            context,
            phase="bounded",
            ledger_path=ledger,
            readiness_path=readiness,
        )


def test_ledger_rejects_fabricated_consumed_state_before_completion(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    def fabricate_consumption(
        payload: dict[str, object],
    ) -> None:
        payload["attempts"][-1]["result"] = "consumed"
        payload["authorizations"][-1]["state"] = "consumed"

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="historical ledger",
    ):
        _force_valid_ledger_mutation(
            ledger,
            fabricate_consumption,
        )
    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "allocated"


def test_runtime_bound_consumption_records_live_attestation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    runtime_proof = _consume_runtime_bound_for_test(
        monkeypatch,
        ledger=ledger,
        readiness=readiness,
        context=context,
    )

    stored = attempt_ledger.read_ledger(ledger)
    attempt = stored["attempts"][-1]
    attestation = attempt["runtime_attestation"]
    identity_path = context.parent / "runtime-identity.json"
    runtime_identity_sha256 = sha256(
        identity_path.read_bytes()
    ).hexdigest()
    assert attempt["result"] == "consumed"
    assert attempt["runtime_proof_sha256"] == sha256(
        attempt_ledger._canonical_bytes(attempt["runtime_proof"])
    ).hexdigest()
    assert attempt["runtime_attestation_sha256"] == sha256(
        attempt_ledger._canonical_bytes(attestation)
    ).hexdigest()
    assert attestation == {
        "schema_version": "guide-bound-runtime-attestation-v2",
        "phase": "bounded",
        "attempt_id": attempt["attempt_id"],
        "attempt_context_sha256": sha256(
            context.read_bytes()
        ).hexdigest(),
        "runtime_registration_id": "runtime_0123456789abcdef",
        "runtime_identity_path": str(identity_path.resolve()),
        "runtime_identity_sha256": runtime_identity_sha256,
        "runtime_public_key": attempt["runtime_proof"][
            "runtime_public_key"
        ],
        "runtime_process_id": 4100,
        "base_url": "http://127.0.0.1:8821",
        "runtime_proof_sha256": attempt["runtime_proof_sha256"],
    }
    assert runtime_proof == {
        "runtime_identity_sha256": runtime_identity_sha256,
        "runtime_proof_sha256": attempt["runtime_proof_sha256"],
        "runtime_attestation_sha256": attempt[
            "runtime_attestation_sha256"
        ],
    }


def test_runtime_bound_consumption_rejects_unregistered_signing_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tools.guide_gates.runtime_auth import (
        PROOF_REQUEST_SCHEMA,
        generate_runtime_keypair,
        sign_runtime_proof,
    )

    ledger, readiness, context = _allocated_context(tmp_path)
    _, registered_public_key = generate_runtime_keypair()
    rogue_private_key, rogue_public_key = generate_runtime_keypair()
    context_payload = json.loads(context.read_text(encoding="utf-8"))
    identity_path = context.parent / "runtime-identity.json"
    identity = {
        "schema_version": "guide-bound-runtime-identity-v1",
        "phase": "bounded",
        "attempt_id": context_payload["phase_attempt_ids"]["bounded"],
        "attempt_context_path": str(context.resolve()),
        "attempt_context_sha256": sha256(
            context.read_bytes()
        ).hexdigest(),
        "readiness_sha256": sha256(
            readiness.read_bytes()
        ).hexdigest(),
        "ledger_path": str(ledger.resolve()),
        "allocated_ledger_revision": context_payload[
            "allocated_ledger_revision"
        ],
        "allocated_ledger_hash": context_payload[
            "allocated_ledger_hash"
        ],
        "runtime_registration_id": "runtime_0123456789abcdef",
        "runtime_public_key": registered_public_key,
        "process_identity": {"pid": 4100, "parent_pid": 4099},
        "host": "127.0.0.1",
        "port": 8821,
    }
    identity_path.write_bytes(attempt_ledger._canonical_bytes(identity))
    identity_sha256 = sha256(identity_path.read_bytes()).hexdigest()
    registration = attempt_ledger.register_runtime_bound_attempt(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
        registration_id="runtime_0123456789abcdef",
        runtime_identity_sha256=identity_sha256,
        runtime_public_key=registered_public_key,
        host="127.0.0.1",
        port=8821,
    )
    monkeypatch.setattr(
        attempt_ledger,
        "_verify_live_bound_runtime_identity",
        lambda **_: identity,
    )

    def forged_proof(
        *,
        host: str,
        port: int,
        request: dict[str, object],
    ) -> dict[str, object]:
        assert (host, port) == ("127.0.0.1", 8821)
        assert request["schema_version"] == PROOF_REQUEST_SCHEMA
        return sign_runtime_proof(
            private_key=rogue_private_key,
            public_key=rogue_public_key,
            request=request,
        )

    monkeypatch.setattr(
        attempt_ledger,
        "_request_live_runtime_proof",
        forged_proof,
        raising=False,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="runtime proof",
    ):
        attempt_ledger.consume_runtime_bound_attempt(
            context,
            phase="bounded",
            ledger_path=ledger,
            readiness_path=readiness,
            base_url="http://127.0.0.1:8821",
        )

    stored = attempt_ledger.read_ledger(ledger)
    assert stored["attempts"][-1]["result"] == "allocated"
    assert stored["attempts"][-1]["runtime_registrations"] == [
        registration
    ]


def test_runtime_bound_consumption_rejects_symlink_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    real_identity = context.parent / "real-runtime-identity.json"
    real_identity.write_text("{}\n", encoding="utf-8")
    (context.parent / "runtime-identity.json").symlink_to(real_identity)
    monkeypatch.setattr(
        attempt_ledger,
        "_verify_live_bound_runtime_identity",
        lambda **_: pytest.fail(
            "symlink identity must fail before runtime verification"
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="runtime identity",
    ):
        attempt_ledger.consume_runtime_bound_attempt(
            context,
            phase="bounded",
            ledger_path=ledger,
            readiness_path=readiness,
            base_url="http://127.0.0.1:8821",
        )


def test_bounded_browser_validator_requires_attestation_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tools.guide_gates import (
        run_mainline_contract_browser_audit as browser_audit,
    )

    ledger, readiness, context = _allocated_context(tmp_path)
    runtime_proof = _consume_runtime_bound_for_test(
        monkeypatch,
        ledger=ledger,
        readiness=readiness,
        context=context,
    )
    _write_passed_bounded_evidence(
        context,
        runtime_proof=runtime_proof,
    )
    summary_path = context.parent / "browser-desktop/summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.pop("runtime_attestation_sha256")
    _write_json(summary_path, summary)

    with pytest.raises(
        browser_audit.AuditBundleError,
        match="bounded browser evidence is invalid",
    ):
        browser_audit.validate_completed_bounded_browser_evidence(
            context.parent
        )


def test_consume_rejects_context_with_wrong_allocation_hash(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    context_payload = json.loads(context.read_text(encoding="utf-8"))
    context_payload["allocated_ledger_hash"] = "f" * 64
    context.write_bytes(attempt_ledger._canonical_bytes(context_payload))
    context_hash = sha256(context.read_bytes()).hexdigest()
    def bind_tampered_context(payload: dict[str, object]) -> None:
        attempts = payload["attempts"]
        assert isinstance(attempts, list)
        attempts[-1]["context_sha256"] = context_hash

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="historical ledger",
    ):
        _force_valid_ledger_mutation(
            ledger,
            bind_tampered_context,
        )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="attempt context content mismatch",
    ):
        attempt_ledger.consume_attempt_context(
            context,
            phase="translation",
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
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
        )


def test_authorization_rejects_readiness_without_ledger_anchor(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    payload = json.loads(readiness.read_text(encoding="utf-8"))
    payload.pop("ledger_anchor_revision")
    payload.pop("ledger_anchor_hash")
    _write_json(readiness, payload)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="readiness is not eligible",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def test_authorization_rejects_readiness_changed_after_verification(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)

    def verify_then_replace(**_: object) -> dict[str, object]:
        verified = json.loads(readiness.read_text(encoding="utf-8"))
        replacement = dict(verified)
        replacement["candidate_head"] = "d" * 40
        _write_json(readiness, replacement)
        return verified

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="readiness changed during authorization",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=verify_then_replace,
        )

    assert attempt_ledger.read_ledger(ledger)["authorizations"] == []


def test_readiness_binding_rejects_nested_protected_tree_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    protected = root / "app/protected.py"
    protected.parent.mkdir(parents=True)
    protected.write_text("trusted = True\n", encoding="utf-8")
    manifest = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "repair-epoch-1"
        / "task11-candidate-manifest.json"
    )
    nested_protected = manifest.parent / "app/protected.py"
    nested_protected.parent.mkdir(parents=True)
    nested_protected.write_bytes(protected.read_bytes())
    _write_json(
        manifest,
        {
            "schema_version": "guide-task11-candidate-manifest-v1",
            "repository_root": str(root.resolve()),
            "repair_epoch": 1,
            "protected_paths": ["app/protected.py"],
            "deleted_paths": [],
        },
    )
    manifest_sha256 = sha256(manifest.read_bytes()).hexdigest()
    readiness = root / "readiness.json"
    _write_json(
        readiness,
        {
            "reviewed_candidate_manifest_sha256": manifest_sha256,
            "evidence_files": {
                "candidate_manifest": str(manifest),
            },
            "evidence_sha256": {
                "candidate_manifest": manifest_sha256,
            },
        },
    )

    binding = attempt_ledger._capture_readiness_binding(readiness)
    protected.write_text("trusted = False\n", encoding="utf-8")

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="readiness evidence drift",
    ):
        attempt_ledger._require_current_readiness_binding(
            readiness_path=readiness,
            binding=binding,
        )


def test_first_revision_attempt_uses_planned_gate_without_repair_metadata(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    readiness_payload = json.loads(readiness.read_text(encoding="utf-8"))
    readiness_payload["plan_revision"] = "2026-08-23-task11-r5"
    _write_json(readiness, readiness_payload)
    audit_payload = json.loads(audit.read_text(encoding="utf-8"))
    audit_payload["plan_revision"] = "2026-08-23-task11-r5"
    audit_payload["repair_epoch"] = 8
    audit_payload.pop("first_failure_owner")
    _write_json(audit, audit_payload)
    readiness_payload["evidence_sha256"]["independent_audit"] = sha256(
        audit.read_bytes()
    ).hexdigest()
    _write_json(readiness, readiness_payload)

    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    authorization = attempt_ledger.read_ledger(ledger)[
        "authorizations"
    ][-1]
    assert authorization["authorization_id"] == authorization_id
    assert authorization["first_failure_owner"] == "planned_gate"
    assert authorization["repair_epoch"] == 0


def test_ledger_rollback_cannot_allocate_a_second_attempt(
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger-root"
    ledger = ledger_root / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    checkpoint_bytes = ledger.read_bytes()

    first_authorization = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    context = attempt_ledger.allocate_attempt(
        phase="bounded",
        authorization_id=first_authorization,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=ledger_root / "attempts",
    )
    shutil.move(
        context.parent,
        tmp_path / "moved-attempt",
    )
    receipts = tuple(
        ledger_root.glob(
            "smoke-attempt-ledger-authorization-*.json"
        )
    )
    assert len(receipts) == 1
    receipts[0].unlink()

    ledger.write_bytes(checkpoint_bytes)
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="authorization rollback detected",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def test_foreign_context_cannot_replace_rollback_witness(
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger-root"
    ledger = ledger_root / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    checkpoint_bytes = ledger.read_bytes()
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
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
        output_root=ledger_root / "attempts",
    )
    shutil.move(context.parent, tmp_path / "moved-attempt")
    next(
        ledger_root.glob(
            "smoke-attempt-ledger-authorization-*.json"
        )
    ).unlink()
    witness = next(
        ledger_root.glob(
            "smoke-attempt-ledger-context-*.json"
        )
    )
    forged = json.loads(witness.read_text(encoding="utf-8"))
    forged["ledger_path"] = str(
        (tmp_path / "other-ledger.json").resolve()
    )
    witness.write_bytes(attempt_ledger._canonical_bytes(forged))
    ledger.write_bytes(checkpoint_bytes)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="persisted attempt context is invalid",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def test_repository_context_survives_dual_sidecar_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", tmp_path)
    ledger_root = (
        tmp_path
        / "docs/audits/final-release/mainline-contract-closure"
    )
    ledger = ledger_root / "smoke-attempt-ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    checkpoint_bytes = ledger.read_bytes()
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
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
        output_root=ledger_root / "attempts",
    )
    moved = tmp_path / "moved-attempt"
    shutil.move(context.parent, moved)
    next(
        ledger_root.glob(
            "smoke-attempt-ledger-authorization-*.json"
        )
    ).unlink()
    next(
        ledger_root.glob(
            "smoke-attempt-ledger-context-*.json"
        )
    ).unlink()
    ledger.write_bytes(checkpoint_bytes)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="authorization rollback detected",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def test_authorization_receipt_survives_attempt_allocation(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    attempt_ledger.allocate_attempt(
        phase="bounded",
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=tmp_path / "attempts",
    )

    with attempt_ledger._ledger_lock(
        ledger.resolve(),
        shared=True,
    ) as binding:
        payload = attempt_ledger._read_ledger_unlocked(
            ledger.resolve(),
            binding=binding,
        )
        verified = attempt_ledger._verify_authorization_receipts(
            binding=binding,
            payload=payload,
        )

    assert verified == {authorization_id}


def test_allocation_requires_authorization_receipt(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    receipt = tmp_path / attempt_ledger._authorization_receipt_name(
        authorization_id
    )
    assert receipt.is_file()
    receipt.unlink()

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="authorization receipt is missing",
    ):
        attempt_ledger.allocate_attempt(
            phase="bounded",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
        )


def test_authorization_receipt_verifier_requires_complete_history(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    (
        tmp_path
        / attempt_ledger._authorization_receipt_name(authorization_id)
    ).unlink()

    with attempt_ledger._ledger_lock(
        ledger.resolve(),
        shared=True,
    ) as binding:
        payload = attempt_ledger._read_ledger_unlocked(
            ledger.resolve(),
            binding=binding,
        )
        with pytest.raises(
            attempt_ledger.AttemptLedgerError,
            match="authorization receipt is missing",
        ):
            attempt_ledger._verify_authorization_receipts(
                binding=binding,
                payload=payload,
            )


def test_authorization_receipt_interruption_recovers_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    write_receipt = attempt_ledger._write_authorization_receipt

    def interrupt_receipt(*_: object, **__: object) -> None:
        raise OSError("simulated receipt interruption")

    monkeypatch.setattr(
        attempt_ledger,
        "_write_authorization_receipt",
        interrupt_receipt,
    )
    with pytest.raises(OSError, match="simulated receipt interruption"):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )
    stored = attempt_ledger.read_ledger(ledger)
    assert len(stored["authorizations"]) == 1
    authorization_id = stored["authorizations"][0]["authorization_id"]
    monkeypatch.setattr(
        attempt_ledger,
        "_write_authorization_receipt",
        write_receipt,
    )

    recovered = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    assert recovered == authorization_id
    assert len(
        attempt_ledger.read_ledger(ledger)["authorizations"]
    ) == 1
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="authorization already issued",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def test_authorization_receipt_recovers_partial_final_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    write_receipt = attempt_ledger._write_authorization_receipt

    def interrupt_receipt(
        *,
        binding: attempt_ledger._BoundLedgerPath,
        payload: dict[str, object],
    ) -> None:
        receipt_path = binding.path.with_name(
            attempt_ledger._authorization_receipt_name(
                str(payload["authorization_id"])
            )
        )
        receipt_path.write_bytes(b"{")
        raise OSError("simulated partial receipt write")

    monkeypatch.setattr(
        attempt_ledger,
        "_write_authorization_receipt",
        interrupt_receipt,
    )
    with pytest.raises(
        OSError,
        match="simulated partial receipt write",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )
    monkeypatch.setattr(
        attempt_ledger,
        "_write_authorization_receipt",
        write_receipt,
    )

    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    receipt = ledger.with_name(
        attempt_ledger._authorization_receipt_name(
            authorization_id
        )
    )

    assert json.loads(receipt.read_text(encoding="utf-8"))[
        "authorization_id"
    ] == authorization_id


def test_allocation_rejects_output_root_outside_ledger_authority(
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger-root"
    ledger = ledger_root / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="outside ledger authority",
    ):
        attempt_ledger.allocate_attempt(
            phase="bounded",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "outside-attempts",
        )


def test_real_call_authorizations_are_exclusive_across_phases(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="active authorization",
    ):
        attempt_ledger.authorize_attempt(
            phase="translation",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


@pytest.mark.parametrize(
    ("summary", "match"),
    [
        (None, "required parent summary is missing"),
        (
            {
                "schema_version": "guide-final-real-backend-summary-v1",
                "passed": False,
            },
            "required parent summary result mismatch",
        ),
    ],
)
def test_browser_child_allocation_requires_passed_backend_summary(
    tmp_path: Path,
    summary: dict[str, object] | None,
    match: str,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    if summary is not None:
        _write_json(parent.parent / "real-backend/summary.json", summary)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match=match,
    ):
        attempt_ledger.allocate_attempt(
            phase="browser",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
            parent_context=parent,
            require_summary_phase="backend",
            require_summary_result="passed",
        )

    assert not tuple(
        (tmp_path / "attempts").glob("release-browser-attempt-*")
    )


def test_browser_child_context_binds_required_backend_summary(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    summary = _write_passed_backend_evidence(parent)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    child = attempt_ledger.allocate_attempt(
        phase="browser",
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=tmp_path / "attempts",
        parent_context=parent,
        require_summary_phase="backend",
        require_summary_result="passed",
    )

    payload = json.loads(child.read_text(encoding="utf-8"))
    assert payload["current_phase"] == "browser"
    assert payload["required_parent_summary"] == {
        "phase": "backend",
        "result": "passed",
        "path": str(summary.resolve()),
        "sha256": sha256(summary.read_bytes()).hexdigest(),
    }
    _write_json(
        summary,
        {
            "schema_version": "guide-final-real-backend-summary-v1",
            "passed": False,
        },
    )
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="required parent summary",
    ):
        attempt_ledger.read_attempt_context(
            child,
            ledger_path=ledger,
            readiness_path=readiness,
        )


def test_browser_child_rejects_tampered_backend_results(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    _write_passed_backend_evidence(parent)
    (parent.parent / "real-backend/results.jsonl").write_text(
        '{"completed":true,"passed":false}\n',
        encoding="utf-8",
    )
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="backend evidence checksum mismatch",
    ):
        attempt_ledger.allocate_attempt(
            phase="browser",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
            parent_context=parent,
            require_summary_phase="backend",
            require_summary_result="passed",
        )


def test_browser_child_rejects_self_consistent_tampered_backend_raw_sse(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    backend_summary = _write_passed_backend_evidence(parent)
    backend_results = backend_summary.parent / "results.jsonl"
    rows = [
        json.loads(line)
        for line in backend_results.read_text(encoding="utf-8").splitlines()
    ]
    raw_sse = backend_summary.parent / rows[0]["raw_sse_path"]
    raw_sse.write_text(
        (
            "event: start\n"
            "data: {}\n\n"
            "event: error\n"
            "data: {\"error\":\"tampered\"}\n\n"
            "event: end\n"
            "data: {}\n\n"
        ),
        encoding="utf-8",
    )
    rows[0]["raw_sse_sha256"] = sha256(
        raw_sse.read_bytes()
    ).hexdigest()
    backend_results.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    backend_payload = json.loads(
        backend_summary.read_text(encoding="utf-8")
    )
    backend_payload["results_sha256"] = sha256(
        backend_results.read_bytes()
    ).hexdigest()
    _write_json(backend_summary, backend_payload)
    _refresh_backend_checksums(backend_summary)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="backend raw SSE evidence",
    ):
        attempt_ledger.allocate_attempt(
            phase="browser",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
            parent_context=parent,
            require_summary_phase="backend",
            require_summary_result="passed",
        )


def test_browser_child_rejects_forged_backend_terminal_payload(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    backend_summary = _write_passed_backend_evidence(parent)
    backend_results = backend_summary.parent / "results.jsonl"
    rows = [
        json.loads(line)
        for line in backend_results.read_text(encoding="utf-8").splitlines()
    ]
    row = next(item for item in rows if not item["clarification"])
    raw_sse = backend_summary.parent / row["raw_sse_path"]
    raw_sse.write_text(
        (
            "event: start\n"
            f"data: {json.dumps({'session_id': row['turn_id']})}\n\n"
            "event: presentation_contract\n"
            "data: {\"forged\":true}\n\n"
            "event: end\n"
            "data: {\"conversation_version\":0}\n\n"
        ),
        encoding="utf-8",
    )
    row["raw_sse_sha256"] = sha256(raw_sse.read_bytes()).hexdigest()
    backend_results.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in rows),
        encoding="utf-8",
    )
    backend_payload = json.loads(
        backend_summary.read_text(encoding="utf-8")
    )
    backend_payload["results_sha256"] = sha256(
        backend_results.read_bytes()
    ).hexdigest()
    _write_json(backend_summary, backend_payload)
    _refresh_backend_checksums(backend_summary)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="backend raw SSE evidence",
    ):
        attempt_ledger.allocate_attempt(
            phase="browser",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
            parent_context=parent,
            require_summary_phase="backend",
            require_summary_result="passed",
        )


@pytest.mark.parametrize(
    "mutation",
    ("invalid_start_payload", "duplicate_start"),
)
def test_browser_child_strictly_validates_every_event_and_lifecycle(
    tmp_path: Path,
    mutation: str,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    backend_summary = _write_passed_backend_evidence(parent)
    backend_results = backend_summary.parent / "results.jsonl"
    rows = [
        json.loads(line)
        for line in backend_results.read_text(encoding="utf-8").splitlines()
    ]
    row = next(item for item in rows if not item["clarification"])
    raw_sse = backend_summary.parent / row["raw_sse_path"]
    first, remainder = raw_sse.read_text(
        encoding="utf-8"
    ).split("\n\n", 1)
    if mutation == "invalid_start_payload":
        first = "event: start\ndata: {\"session_id\":7}"
    else:
        remainder = f"{first}\n\n{remainder}"
        row["event_names"].insert(1, "start")
    raw_sse.write_text(
        f"{first}\n\n{remainder}",
        encoding="utf-8",
    )
    row["raw_sse_sha256"] = sha256(raw_sse.read_bytes()).hexdigest()
    backend_results.write_text(
        "".join(
            json.dumps(item, sort_keys=True) + "\n"
            for item in rows
        ),
        encoding="utf-8",
    )
    backend_payload = json.loads(
        backend_summary.read_text(encoding="utf-8")
    )
    backend_payload["results_sha256"] = sha256(
        backend_results.read_bytes()
    ).hexdigest()
    _write_json(backend_summary, backend_payload)
    _refresh_backend_checksums(backend_summary)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="backend raw SSE evidence",
    ):
        attempt_ledger.allocate_attempt(
            phase="browser",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
            parent_context=parent,
            require_summary_phase="backend",
            require_summary_result="passed",
        )


def test_browser_child_rejects_self_consistent_unsealed_fixture_hash(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    backend_summary = _write_passed_backend_evidence(parent)
    translation = parent.parent / "real-translation"
    translation_summary = translation / "summary.json"
    translation_payload = json.loads(
        translation_summary.read_text(encoding="utf-8")
    )
    translation_payload["fixture_sha256"] = "0" * 64
    _write_json(translation_summary, translation_payload)
    translation_checksums = translation / "SHA256SUMS"
    translation_checksums.write_text(
        (
            f"{sha256((translation / 'results.jsonl').read_bytes()).hexdigest()}"
            "  results.jsonl\n"
            f"{sha256(translation_summary.read_bytes()).hexdigest()}"
            "  summary.json\n"
        ),
        encoding="ascii",
    )
    backend_payload = json.loads(
        backend_summary.read_text(encoding="utf-8")
    )
    backend_payload.update({
        "fixture_sha256": "0" * 64,
        "translation_summary_sha256": sha256(
            translation_summary.read_bytes()
        ).hexdigest(),
        "translation_checksums_sha256": sha256(
            translation_checksums.read_bytes()
        ).hexdigest(),
    })
    _write_json(backend_summary, backend_payload)
    _refresh_backend_checksums(backend_summary)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="canonical fixture",
    ):
        attempt_ledger._validate_passed_backend_evidence(
            attempt_root=parent.parent,
            summary_path=backend_summary,
            summary=backend_payload,
        )


def test_browser_child_rejects_duplicate_fabricated_backend_rows(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    backend_summary = _write_passed_backend_evidence(parent)
    backend_results = backend_summary.parent / "results.jsonl"
    original_rows = [
        json.loads(line)
        for line in backend_results.read_text(encoding="utf-8").splitlines()
    ]
    first = json.dumps(original_rows[0], sort_keys=True)
    backend_results.write_text((first + "\n") * 48, encoding="utf-8")
    for row in original_rows[1:]:
        (backend_summary.parent / row["raw_sse_path"]).unlink()
    backend_payload = json.loads(
        backend_summary.read_text(encoding="utf-8")
    )
    backend_payload["results_sha256"] = sha256(
        backend_results.read_bytes()
    ).hexdigest()
    _write_json(backend_summary, backend_payload)
    _refresh_backend_checksums(backend_summary)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="backend evidence turn identity",
    ):
        attempt_ledger.allocate_attempt(
            phase="browser",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
            parent_context=parent,
            require_summary_phase="backend",
            require_summary_result="passed",
        )


def test_browser_child_derives_context_mismatch_from_backend_hashes(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    backend_summary = _write_passed_backend_evidence(parent)
    backend_results = backend_summary.parent / "results.jsonl"
    rows = [
        json.loads(line)
        for line in backend_results.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["observed_context_sha256"] = "b" * 64
    backend_results.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    backend_payload = json.loads(
        backend_summary.read_text(encoding="utf-8")
    )
    backend_payload["results_sha256"] = sha256(
        backend_results.read_bytes()
    ).hexdigest()
    _write_json(backend_summary, backend_payload)
    _refresh_backend_checksums(backend_summary)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="context hash",
    ):
        attempt_ledger.allocate_attempt(
            phase="browser",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
            parent_context=parent,
            require_summary_phase="backend",
            require_summary_result="passed",
        )


def test_browser_child_rejects_matching_noncanonical_context_hashes(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    backend_summary = _write_passed_backend_evidence(parent)
    backend_results = backend_summary.parent / "results.jsonl"
    rows = [
        json.loads(line)
        for line in backend_results.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["sealed_context_sha256"] = "b" * 64
    rows[0]["observed_context_sha256"] = "b" * 64
    backend_results.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    backend_payload = json.loads(
        backend_summary.read_text(encoding="utf-8")
    )
    backend_payload["results_sha256"] = sha256(
        backend_results.read_bytes()
    ).hexdigest()
    _write_json(backend_summary, backend_payload)
    _refresh_backend_checksums(backend_summary)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="canonical context",
    ):
        attempt_ledger.allocate_attempt(
            phase="browser",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
            parent_context=parent,
            require_summary_phase="backend",
            require_summary_result="passed",
        )


def test_browser_child_rejects_schema_only_backend_summary(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path
    )
    _write_json(
        parent.parent / "real-backend/summary.json",
        {
            "schema_version": "guide-final-real-backend-summary-v1",
            "passed": True,
        },
    )
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="backend evidence is incomplete",
    ):
        attempt_ledger.allocate_attempt(
            phase="browser",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=tmp_path / "attempts",
            parent_context=parent,
            require_summary_phase="backend",
            require_summary_result="passed",
        )


def test_ledger_rejects_rewriting_passed_translation_parent(
    tmp_path: Path,
) -> None:
    ledger, readiness, audit, parent = _passed_translation_context(
        tmp_path,
    )
    _write_passed_backend_evidence(parent)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="browser",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    def fail_parent(payload: dict[str, object]) -> None:
        attempts = payload["attempts"]
        authorizations = payload["authorizations"]
        assert isinstance(attempts, list)
        assert isinstance(authorizations, list)
        attempts[-1]["result"] = "failed"
        authorizations[0]["state"] = "failed"

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="historical ledger",
    ):
        _force_valid_ledger_mutation(
            ledger,
            fail_parent,
        )

    assert attempt_ledger.read_ledger(ledger)["attempts"][-1][
        "result"
    ] == "passed"


def test_allocate_child_cli_requires_backend_summary_contract() -> None:
    parser = attempt_ledger._parser()
    base = [
        "allocate-child",
        "--phase",
        "browser",
        "--authorization-id",
        "auth-browser",
        "--ledger",
        "ledger.json",
        "--readiness",
        "readiness.json",
        "--output-root",
        "attempts",
        "--parent-context",
        "parent-context.json",
    ]

    with pytest.raises(SystemExit):
        parser.parse_args(base)

    parsed = parser.parse_args([
        *base,
        "--require-summary-phase",
        "backend",
        "--require-summary-result",
        "passed",
    ])
    assert parsed.require_summary_phase == "backend"
    assert parsed.require_summary_result == "passed"


def test_authorize_cli_requires_reviewed_manifest_sha256() -> None:
    parser = attempt_ledger._parser()
    arguments = [
        "authorize",
        "--phase",
        "bounded",
        "--readiness",
        "readiness.json",
        "--ledger",
        "ledger.json",
        "--independent-audit",
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


def test_ledger_rejects_inserting_unrecorded_historical_failures(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="translation",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    context = attempt_ledger.allocate_attempt(
        phase="translation",
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=tmp_path / "attempts",
    )
    def open_circuit(payload: dict[str, object]) -> None:
        attempts = payload["attempts"]
        assert isinstance(attempts, list)
        attempts.extend(
            (
                _historical_failure(),
                {
                    **_historical_failure(),
                    "attempt_id": "bounded-smoke-attempt-02",
                },
            )
        )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="historical ledger",
    ):
        _force_valid_ledger_mutation(
            ledger,
            open_circuit,
        )

    assert attempt_ledger.read_ledger(ledger)["circuit_state"] == "closed"


def test_two_concurrent_consumers_only_one_succeeds(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )

    def consume() -> str:
        try:
            attempt_ledger.consume_attempt_context(
                context,
                    phase="translation",
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


def test_generic_compare_and_swap_cannot_reopen_consumed_authorization(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    current = attempt_ledger.read_ledger(ledger)

    def reopen(payload: dict[str, object]) -> dict[str, object]:
        payload["attempts"][-1]["result"] = "allocated"
        payload["authorizations"][-1]["state"] = "allocated"
        return payload

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="generic ledger mutation cannot change attempts",
    ):
        attempt_ledger.compare_and_swap_ledger(
            ledger,
            expected_revision=current["revision"],
            mutate=reopen,
        )


def test_runtime_registration_is_single_active_ledger_transition(
    tmp_path: Path,
) -> None:
    from tools.guide_gates.runtime_auth import generate_runtime_keypair

    ledger, readiness, context = _allocated_context(tmp_path)
    _, public_key = generate_runtime_keypair()
    _, second_public_key = generate_runtime_keypair()
    assert hasattr(
        attempt_ledger,
        "register_runtime_bound_attempt",
    )

    registration = attempt_ledger.register_runtime_bound_attempt(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
        registration_id="runtime_0123456789abcdef",
        runtime_identity_sha256="d" * 64,
        runtime_public_key=public_key,
        host="127.0.0.1",
        port=8821,
    )

    assert registration["state"] == "registered"
    assert registration["attempt_context_sha256"] == sha256(
        context.read_bytes()
    ).hexdigest()
    stored = attempt_ledger.read_ledger(ledger)
    assert stored["attempts"][-1]["runtime_registrations"] == [
        registration
    ]
    assert stored["revision_chain"][-1]["operation"] == (
        "runtime_registered"
    )
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="active runtime registration",
    ):
        attempt_ledger.register_runtime_bound_attempt(
            context,
            phase="bounded",
            ledger_path=ledger,
            readiness_path=readiness,
            registration_id="runtime_fedcba9876543210",
            runtime_identity_sha256="e" * 64,
            runtime_public_key=second_public_key,
            host="127.0.0.1",
            port=8821,
        )


def test_runtime_registration_abort_is_append_only_and_allows_restart(
    tmp_path: Path,
) -> None:
    from tools.guide_gates.runtime_auth import generate_runtime_keypair

    ledger, readiness, context = _allocated_context(tmp_path)
    _, public_key = generate_runtime_keypair()
    first = attempt_ledger.register_runtime_bound_attempt(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
        registration_id="runtime_0123456789abcdef",
        runtime_identity_sha256="d" * 64,
        runtime_public_key=public_key,
        host="127.0.0.1",
        port=8821,
    )

    aborted = attempt_ledger.abort_runtime_bound_registration(
        context,
        phase="bounded",
        ledger_path=ledger,
        registration_id=str(first["registration_id"]),
    )

    assert aborted["state"] == "aborted"
    stored = attempt_ledger.read_ledger(ledger)
    assert stored["revision_chain"][-1]["operation"] == (
        "runtime_registration_aborted"
    )
    _, second_public_key = generate_runtime_keypair()
    second = attempt_ledger.register_runtime_bound_attempt(
        context,
        phase="bounded",
        ledger_path=ledger,
        readiness_path=readiness,
        registration_id="runtime_fedcba9876543210",
        runtime_identity_sha256="e" * 64,
        runtime_public_key=second_public_key,
        host="127.0.0.1",
        port=8821,
    )
    assert second["state"] == "registered"


def test_ledger_lock_file_is_isolated_from_repository(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    identity = sha256(str(ledger.resolve()).encode("utf-8")).hexdigest()
    legacy_lock = (
        Path(gettempdir())
        / "xiaoro-guide-attempt-ledger-locks-v1"
        / f"{identity}.lock"
    )

    attempt_ledger.initialize_ledger(ledger)
    attempt_ledger.read_ledger(ledger)

    assert not (tmp_path / ".ledger.json.lock").exists()
    assert legacy_lock.is_file()
    assert legacy_lock.parent != tmp_path


def test_ledger_lock_path_replacement_cannot_split_critical_section(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    identity = sha256(str(ledger.resolve()).encode("utf-8")).hexdigest()
    lock_path = (
        Path(gettempdir())
        / "xiaoro-guide-attempt-ledger-locks-v1"
        / f"{identity}.lock"
    )
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path.touch()
    displaced_lock = lock_path.with_suffix(".displaced")
    contender_started = Event()
    contender_entered = Event()
    release_contender = Event()

    def contend() -> None:
        contender_started.set()
        with attempt_ledger._ledger_lock(ledger):
            contender_entered.set()
            release_contender.wait(timeout=2)

    thread: Thread | None = None
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="canonical ledger lock changed",
    ):
        with attempt_ledger._ledger_lock(ledger):
            os.replace(lock_path, displaced_lock)
            lock_path.touch()
            thread = Thread(target=contend, daemon=True)
            thread.start()
            assert contender_started.wait(timeout=1)
            try:
                assert not contender_entered.wait(timeout=0.2)
            finally:
                release_contender.set()

    assert thread is not None
    assert contender_entered.wait(timeout=1)
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_ledger_lock_rejects_symlink_substitution(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    identity = sha256(str(ledger.resolve()).encode("utf-8")).hexdigest()
    lock_path = (
        Path(gettempdir())
        / "xiaoro-guide-attempt-ledger-locks-v1"
        / f"{identity}.lock"
    )
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = tmp_path / "attacker-controlled-lock"
    target.write_bytes(b"do-not-open")
    lock_path.symlink_to(target)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="canonical ledger lock is invalid",
    ):
        attempt_ledger.initialize_ledger(ledger)

    assert target.read_bytes() == b"do-not-open"
    assert not ledger.exists()


def test_ledger_lock_root_replacement_cannot_split_critical_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "ledger" / "ledger.json"
    lock_root = tmp_path / "external-lock-root"
    monkeypatch.setattr(
        attempt_ledger,
        "_LOCK_DIRECTORY",
        lock_root / "locks",
    )
    lock_root.mkdir()
    attempt_ledger.initialize_ledger(ledger)
    displaced_root = tmp_path / "displaced-lock-root"
    contender_started = Event()
    contender_entered = Event()
    release_contender = Event()

    def contend() -> None:
        contender_started.set()
        with attempt_ledger._ledger_lock(ledger):
            contender_entered.set()
            release_contender.wait(timeout=2)

    thread: Thread | None = None
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="canonical ledger lock changed",
    ):
        with attempt_ledger._ledger_lock(ledger):
            os.replace(lock_root, displaced_root)
            lock_root.mkdir()
            thread = Thread(target=contend, daemon=True)
            thread.start()
            assert contender_started.wait(timeout=1)
            try:
                assert not contender_entered.wait(timeout=0.2)
            finally:
                release_contender.set()

    assert thread is not None
    assert contender_entered.wait(timeout=1)
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_ledger_revision_chain_rejects_tampered_history(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    payload["revision_chain"][0]["revision_hash"] = "f" * 64
    _write_json(ledger, payload)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="revision chain",
    ):
        attempt_ledger.read_ledger(ledger)


def test_authorization_rejects_forked_ledger_path(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    fork = tmp_path / "forked-ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    shutil.copy2(ledger, fork)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="ledger path",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=fork,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def test_ledger_rejects_recomputed_tip_after_historical_state_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    historical = _historical_failure()
    legacy_state = {
        "schema_version": "guide-smoke-attempt-ledger-v1",
        "revision": 0,
        "circuit_state": "closed",
        "attempts": [historical],
        "authorizations": [],
    }
    initialized = {
        "revision": 0,
        "previous_hash": None,
        "operation": "initialized",
        "attempt_id": None,
        "authorization_id": None,
        "source_sha256": None,
        "state_sha256": sha256(
            attempt_ledger._canonical_bytes(legacy_state)
        ).hexdigest(),
    }
    initialized["revision_hash"] = sha256(
        attempt_ledger._canonical_bytes(initialized)
    ).hexdigest()
    legacy = {
        **legacy_state,
        "revision_chain": [initialized],
    }
    _write_json(ledger, legacy)
    manifest = _checkpoint_manifest(root, ledger)

    checkpointed = attempt_ledger.checkpoint_ledger(
        ledger_path=ledger,
        manifest_path=manifest,
        expected_manifest_sha256=sha256(
            manifest.read_bytes()
        ).hexdigest(),
    )

    assert checkpointed["revision_chain"][:-1] == legacy["revision_chain"]
    assert checkpointed["revision_chain"][-1]["operation"] == (
        "state_checkpoint"
    )
    hostile = json.loads(ledger.read_text(encoding="utf-8"))
    hostile["attempts"] = []
    hostile["revision"] += 1
    hostile["circuit_state"] = "closed"
    attempt_ledger._append_revision(
        hostile,
        operation="compare_and_swap",
    )
    _write_json(ledger, hostile)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="historical ledger state",
    ):
        attempt_ledger.read_ledger(ledger)


def test_checkpoint_rejects_rewritten_history_against_reviewed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    attempt_ledger.initialize_ledger(
        ledger,
        attempts=[_historical_failure()],
    )
    reviewed_bytes = ledger.read_bytes()
    reviewed_payload = attempt_ledger.read_ledger(ledger)
    reviewed_anchor = attempt_ledger.ledger_anchor(reviewed_payload)
    manifest = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "repair-epoch-1"
        / "task11-candidate-manifest.json"
    )
    _write_json(
        manifest,
        {
            "schema_version": "guide-task11-candidate-manifest-v1",
            "repository_root": str(root.resolve()),
            "repair_epoch": 1,
            "mutable_evidence_paths": [
                ledger.relative_to(root).as_posix()
            ],
            "pre_checkpoint_ledger": {
                "path": str(ledger.resolve()),
                "sha256": sha256(reviewed_bytes).hexdigest(),
                "revision": reviewed_anchor["revision"],
                "revision_hash": reviewed_anchor["revision_hash"],
            },
        },
    )

    rewritten = {
        "schema_version": "guide-smoke-attempt-ledger-v1",
        "ledger_path": str(ledger.resolve()),
        "revision": 0,
        "circuit_state": "closed",
        "attempts": [],
        "authorizations": [],
        "revision_chain": [],
    }
    attempt_ledger._append_revision(
        rewritten,
        operation="initialized",
    )
    _write_json(ledger, rewritten)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="reviewed ledger checkpoint source mismatch",
    ):
        attempt_ledger.checkpoint_ledger(
            ledger_path=ledger,
            manifest_path=manifest,
            expected_manifest_sha256=sha256(
                manifest.read_bytes()
            ).hexdigest(),
        )


def test_checkpoint_rejects_nested_repository_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    nested_root = root / "nested"
    ledger = (
        nested_root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    _write_uncheckpointed_ledger(ledger)
    manifest = _checkpoint_manifest(nested_root, ledger)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="manifest authority",
    ):
        attempt_ledger.checkpoint_ledger(
            ledger_path=ledger,
            manifest_path=manifest,
            expected_manifest_sha256=sha256(
                manifest.read_bytes()
            ).hexdigest(),
        )


def test_checkpoint_rejects_ledger_path_outside_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    ledger = tmp_path / "outside-ledger.json"
    _write_uncheckpointed_ledger(ledger)
    payload, source_bytes = attempt_ledger.read_ledger_checkpoint_source(
        ledger
    )
    tip = payload["revision_chain"][-1]
    manifest = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "repair-epoch-1"
        / "task11-candidate-manifest.json"
    )
    _write_json(
        manifest,
        {
            "schema_version": "guide-task11-candidate-manifest-v1",
            "repository_root": str(root.resolve()),
            "repair_epoch": 1,
            "mutable_evidence_paths": ["../outside-ledger.json"],
            "pre_checkpoint_ledger": {
                "path": str(ledger.resolve()),
                "sha256": sha256(source_bytes).hexdigest(),
                "revision": tip["revision"],
                "revision_hash": tip["revision_hash"],
            },
        },
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="manifest authority",
    ):
        attempt_ledger.checkpoint_ledger(
            ledger_path=ledger,
            manifest_path=manifest,
            expected_manifest_sha256=sha256(
                manifest.read_bytes()
            ).hexdigest(),
        )


def test_checkpoint_rejects_precheckpoint_replay_after_readiness_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    _write_uncheckpointed_ledger(ledger)
    pre_checkpoint_bytes = ledger.read_bytes()
    manifest = _checkpoint_manifest(root, ledger)
    manifest_sha256 = sha256(manifest.read_bytes()).hexdigest()

    attempt_ledger.checkpoint_ledger(
        ledger_path=ledger,
        manifest_path=manifest,
        expected_manifest_sha256=manifest_sha256,
    )
    readiness_path = (
        manifest.parent / "task11-candidate-readiness.json"
    )
    readiness_path.write_text("{}\n", encoding="utf-8")
    ledger.write_bytes(pre_checkpoint_bytes)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="readiness already exists",
    ):
        attempt_ledger.checkpoint_ledger(
            ledger_path=ledger,
            manifest_path=manifest,
            expected_manifest_sha256=manifest_sha256,
        )


def test_checkpoint_rejects_precheckpoint_replay_from_new_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    _write_uncheckpointed_ledger(ledger)
    pre_checkpoint_bytes = ledger.read_bytes()
    first_manifest = _checkpoint_manifest(root, ledger, repair_epoch=1)

    checkpointed = attempt_ledger.checkpoint_ledger(
        ledger_path=ledger,
        manifest_path=first_manifest,
        expected_manifest_sha256=sha256(
            first_manifest.read_bytes()
        ).hexdigest(),
    )
    checkpoint_anchor = attempt_ledger.ledger_anchor(checkpointed)
    _write_json(
        first_manifest.parent / "task11-candidate-readiness.json",
        {
            "ledger_path": str(ledger.resolve()),
            "ledger_anchor_revision": checkpoint_anchor["revision"],
            "ledger_anchor_hash": checkpoint_anchor["revision_hash"],
        },
    )
    authority_path = ledger.with_name(
        "smoke-attempt-ledger-checkpoint-authority.json"
    )
    assert authority_path.is_file()
    authority_path.unlink()
    ledger.write_bytes(pre_checkpoint_bytes)
    second_manifest = _checkpoint_manifest(root, ledger, repair_epoch=2)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="checkpoint rollback detected",
    ):
        attempt_ledger.checkpoint_ledger(
            ledger_path=ledger,
            manifest_path=second_manifest,
            expected_manifest_sha256=sha256(
                second_manifest.read_bytes()
            ).hexdigest(),
        )

    assert ledger.read_bytes() == pre_checkpoint_bytes


def test_checkpoint_authority_allows_resume_before_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    _write_uncheckpointed_ledger(ledger)
    pre_checkpoint_bytes = ledger.read_bytes()
    manifest = _checkpoint_manifest(root, ledger)
    manifest_sha256 = sha256(manifest.read_bytes()).hexdigest()
    atomic_write = attempt_ledger._atomic_write_ledger

    def interrupt_checkpoint(*_: object, **__: object) -> None:
        raise OSError("simulated checkpoint interruption")

    monkeypatch.setattr(
        attempt_ledger,
        "_atomic_write_ledger",
        interrupt_checkpoint,
    )
    with pytest.raises(
        OSError,
        match="simulated checkpoint interruption",
    ):
        attempt_ledger.checkpoint_ledger(
            ledger_path=ledger,
            manifest_path=manifest,
            expected_manifest_sha256=manifest_sha256,
        )
    monkeypatch.setattr(
        attempt_ledger,
        "_atomic_write_ledger",
        atomic_write,
    )
    authority_path = ledger.with_name(
        "smoke-attempt-ledger-checkpoint-authority.json"
    )

    assert authority_path.is_file()
    assert ledger.read_bytes() == pre_checkpoint_bytes

    checkpointed = attempt_ledger.checkpoint_ledger(
        ledger_path=ledger,
        manifest_path=manifest,
        expected_manifest_sha256=manifest_sha256,
    )
    verified_authority = (
        attempt_ledger.verify_ledger_checkpoint_authority(
            ledger_path=ledger,
            manifest_path=manifest,
            expected_manifest_sha256=manifest_sha256,
        )
    )

    assert checkpointed["revision_chain"][-1]["operation"] == (
        "state_checkpoint"
    )
    assert verified_authority["source_sha256"] == sha256(
        pre_checkpoint_bytes
    ).hexdigest()


def test_checkpoint_backfills_legacy_authorization_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    _write_uncheckpointed_ledger(ledger)
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    authorization_id = "auth_" + "d" * 32
    payload["authorizations"] = [
        {
            "authorization_id": authorization_id,
            "phase": "bounded",
            "plan_revision": "2026-08-22-task11-r1",
            "repair_epoch": 1,
            "first_failure_owner": "presentation_provenance",
            "readiness_path": str((root / "readiness.json").resolve()),
            "readiness_sha256": "a" * 64,
            "expected_manifest_sha256": "b" * 64,
            "independent_audit_path": str(
                (root / "independent-audit.json").resolve()
            ),
            "independent_audit_sha256": "c" * 64,
            "repair_evidence": {
                "local_reproduction": "historical",
                "focused_test": "historical",
                "shared_owner_repair": "historical",
            },
            "state": "failed",
            "attempt_id": "bounded-smoke-attempt-01",
            "created_at": "2026-08-21T00:00:00Z",
            "consumed_at": "2026-08-21T00:01:00Z",
            "completed_at": "2026-08-21T00:02:00Z",
        }
    ]
    initial = payload["revision_chain"][0]
    initial["state_sha256"] = (
        attempt_ledger._legacy_ledger_state_sha256(payload)
    )
    initial["revision_hash"] = attempt_ledger._revision_hash(initial)
    _write_json(ledger, payload)
    manifest = _checkpoint_manifest(root, ledger)

    checkpointed = attempt_ledger.checkpoint_ledger(
        ledger_path=ledger,
        manifest_path=manifest,
        expected_manifest_sha256=sha256(
            manifest.read_bytes()
        ).hexdigest(),
    )

    receipt = ledger.with_name(
        attempt_ledger._authorization_receipt_name(authorization_id)
    )
    assert receipt.is_file()
    with attempt_ledger._ledger_lock(ledger) as binding:
        assert attempt_ledger._verify_authorization_receipts(
            binding=binding,
            payload=checkpointed,
        ) == {authorization_id}


def test_checkpoint_authority_recovers_partial_final_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    _init_git_repo(root)
    monkeypatch.setattr(attempt_ledger, "_REPO_ROOT", root)
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    _write_uncheckpointed_ledger(ledger)
    manifest = _checkpoint_manifest(root, ledger)
    manifest_sha256 = sha256(manifest.read_bytes()).hexdigest()
    authority = ledger.with_name(
        "smoke-attempt-ledger-checkpoint-authority.json"
    )
    authority.write_bytes(b"{")

    checkpointed = attempt_ledger.checkpoint_ledger(
        ledger_path=ledger,
        manifest_path=manifest,
        expected_manifest_sha256=manifest_sha256,
    )

    assert checkpointed["revision_chain"][-1]["operation"] == (
        "state_checkpoint"
    )
    assert json.loads(authority.read_text(encoding="utf-8"))[
        "schema_version"
    ] == "guide-smoke-ledger-checkpoint-authority-v1"


def test_migrates_legacy_ledger_as_one_hash_bound_checkpoint(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy-ledger.json"
    target = tmp_path / "ledger.json"
    legacy = {
        "schema_version": "guide-smoke-attempt-ledger-v1",
        "revision": 24,
        "circuit_state": "closed",
        "attempts": [_historical_failure()],
        "authorizations": [],
    }
    _write_json(source, legacy)
    source_hash = sha256(source.read_bytes()).hexdigest()

    migrated = attempt_ledger.migrate_legacy_ledger(
        source_path=source,
        target_path=target,
        expected_source_sha256=source_hash,
    )

    assert migrated["revision"] == 24
    assert migrated["attempts"] == legacy["attempts"]
    assert migrated["authorizations"] == []
    assert len(migrated["revision_chain"]) == 1
    checkpoint = migrated["revision_chain"][0]
    assert checkpoint["revision"] == 24
    assert checkpoint["operation"] == "legacy_checkpoint"
    assert checkpoint["source_sha256"] == source_hash
    assert attempt_ledger.read_ledger(target) == migrated


def test_migration_rejects_wrong_source_hash_and_existing_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy-ledger.json"
    target = tmp_path / "ledger.json"
    _write_json(
        source,
        {
            "schema_version": "guide-smoke-attempt-ledger-v1",
            "revision": 0,
            "circuit_state": "closed",
            "attempts": [],
            "authorizations": [],
        },
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="source hash",
    ):
        attempt_ledger.migrate_legacy_ledger(
            source_path=source,
            target_path=target,
            expected_source_sha256="0" * 64,
        )

    source_hash = sha256(source.read_bytes()).hexdigest()
    attempt_ledger.migrate_legacy_ledger(
        source_path=source,
        target_path=target,
        expected_source_sha256=source_hash,
    )
    before = target.read_bytes()
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="already exists",
    ):
        attempt_ledger.migrate_legacy_ledger(
            source_path=source,
            target_path=target,
            expected_source_sha256=source_hash,
        )
    assert target.read_bytes() == before


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


def test_atomic_ledger_write_cannot_follow_predictable_temp_symlink(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    payload = attempt_ledger.read_ledger(ledger)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"must-not-change")
    predictable = attempt_ledger.ledger_temp_path(ledger)
    predictable.symlink_to(victim)

    attempt_ledger._atomic_write_ledger(ledger, payload)

    assert victim.read_bytes() == b"must-not-change"
    assert ledger.is_file()
    assert not ledger.is_symlink()
    assert attempt_ledger.read_ledger(ledger) == payload
    assert not predictable.exists()


def test_allocation_ledger_failure_rolls_back_context_and_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    before = ledger.read_bytes()
    output_root = tmp_path / "attempts"
    atomic_write = attempt_ledger._atomic_write_ledger

    def fail_before_commit(*_: object, **__: object) -> None:
        raise OSError("simulated ledger commit failure")

    monkeypatch.setattr(
        attempt_ledger,
        "_atomic_write_ledger",
        fail_before_commit,
    )
    with pytest.raises(
        OSError,
        match="simulated ledger commit failure",
    ):
        attempt_ledger.allocate_attempt(
            phase="bounded",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=output_root,
        )

    assert ledger.read_bytes() == before
    assert not (output_root / "bounded-smoke-attempt-01").exists()
    stored = attempt_ledger.read_ledger(ledger)
    assert stored["attempts"] == []
    assert stored["authorizations"][-1]["state"] == "allocated"
    assert stored["authorizations"][-1]["attempt_id"] is None

    monkeypatch.setattr(
        attempt_ledger,
        "_atomic_write_ledger",
        atomic_write,
    )
    context = attempt_ledger.allocate_attempt(
        phase="bounded",
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=output_root,
    )

    assert context.is_file()
    assert context.parent.name == "bounded-smoke-attempt-01"


def test_allocation_recovers_process_exit_before_ledger_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    output_root = tmp_path / "attempts"
    atomic_write = attempt_ledger._atomic_write_ledger

    def terminate_before_commit(*_: object, **__: object) -> None:
        raise SystemExit("simulated process exit")

    monkeypatch.setattr(
        attempt_ledger,
        "_atomic_write_ledger",
        terminate_before_commit,
    )
    with pytest.raises(SystemExit, match="simulated process exit"):
        attempt_ledger.allocate_attempt(
            phase="bounded",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=output_root,
        )
    monkeypatch.setattr(
        attempt_ledger,
        "_atomic_write_ledger",
        atomic_write,
    )

    context = attempt_ledger.allocate_attempt(
        phase="bounded",
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=output_root,
    )

    assert context.is_file()
    assert len(attempt_ledger.read_ledger(ledger)["attempts"]) == 1


def test_allocation_recovers_process_exit_after_ledger_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )
    output_root = tmp_path / "attempts"
    write_witness = attempt_ledger._write_attempt_context_witness

    def terminate_before_witness(*_: object, **__: object) -> None:
        raise SystemExit("simulated process exit")

    monkeypatch.setattr(
        attempt_ledger,
        "_write_attempt_context_witness",
        terminate_before_witness,
    )
    with pytest.raises(SystemExit, match="simulated process exit"):
        attempt_ledger.allocate_attempt(
            phase="bounded",
            authorization_id=authorization_id,
            ledger_path=ledger,
            readiness_path=readiness,
            output_root=output_root,
        )
    monkeypatch.setattr(
        attempt_ledger,
        "_write_attempt_context_witness",
        write_witness,
    )

    context = attempt_ledger.allocate_attempt(
        phase="bounded",
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=output_root,
    )

    assert context.is_file()
    assert len(attempt_ledger.read_ledger(ledger)["attempts"]) == 1
    assert len(
        tuple(
            tmp_path.glob(
                "smoke-attempt-ledger-context-*.json"
            )
        )
    ) == 1


def test_interruption_after_temporary_write_preserves_canonical_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    before = ledger.read_bytes()
    temporary_paths: list[Path] = []

    def interrupted_replace(
        source: object,
        target: object,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        del target
        assert src_dir_fd is not None
        assert dst_dir_fd == src_dir_fd
        temporary_paths.append(ledger.parent / Path(str(source)))
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
    assert len(temporary_paths) == 1
    assert temporary_paths[0].is_file()
    monkeypatch.undo()
    assert attempt_ledger.read_ledger(ledger)["revision"] == 0
    assert not temporary_paths[0].exists()


def test_second_same_owner_failure_opens_circuit(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(
        ledger,
        attempts=(
            _historical_failure(),
            {
                **_historical_failure(),
                "attempt_id": "bounded-smoke-attempt-02",
            },
        ),
    )
    readiness, audit = _readiness(tmp_path, ledger=ledger)

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
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=audit,
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def test_unrepaired_failure_cannot_authorize_retry(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
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
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="no verified repair closure",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=tmp_path / "independent-audit.json",
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def test_failed_attempt_can_bind_evidence_subdirectory(
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(
        tmp_path,
        phase="translation",
    )
    attempt_ledger.consume_attempt_context(
        context,
        phase="translation",
        ledger_path=ledger,
        readiness_path=readiness,
    )
    failure_directory = context.parent / "real-translation"
    failure_directory.mkdir()
    _write_json(
        failure_directory / "runner-failure.json",
        {"error_type": "TimeoutError"},
    )

    completed = attempt_ledger.complete_attempt(
        context,
        result="failed",
        first_failure_turn_id="translation-01",
        first_failure_owner="translation",
        failure_code="TimeoutError",
        evidence_directory=str(failure_directory),
    )

    assert completed["result"] == "failed"
    assert completed["evidence_directory"] == str(failure_directory)
    stored = attempt_ledger.read_ledger(ledger)["attempts"][-1]
    assert stored["evidence_directory"] == str(failure_directory)
    assert stored["terminal_evidence"]["sha256_by_path"] == {
        "real-translation/runner-failure.json": sha256(
            (failure_directory / "runner-failure.json").read_bytes()
        ).hexdigest(),
    }
    hashes, bundle_sha256 = (
        attempt_ledger._recorded_failure_evidence_binding(
            stored,
            evidence_directory=failure_directory,
        )
    )
    assert hashes == stored["terminal_evidence"]["sha256_by_path"]
    assert len(bundle_sha256) == 64


def test_attempt_completed_can_rebind_evidence_directory() -> None:
    previous = {
        "attempts": [{
            "attempt_id": "bounded-smoke-attempt-10",
            "evidence_directory": "/evidence/attempt-10",
        }],
        "authorizations": [],
    }
    current = {
        "attempts": [{
            "attempt_id": "bounded-smoke-attempt-10",
            "evidence_directory": (
                "/evidence/attempt-10/browser-desktop"
            ),
        }],
        "authorizations": [],
    }

    attempt_ledger._verify_snapshot_extension(
        previous,
        current,
        entry={
            "operation": "attempt_completed",
            "attempt_id": "bounded-smoke-attempt-10",
            "authorization_id": "auth-attempt-10",
        },
    )


def test_reclassify_accepts_indexed_runner_startup_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    _consume_runtime_bound_for_test(
        monkeypatch,
        ledger=ledger,
        readiness=readiness,
        context=context,
    )
    browser_directory = context.parent / "browser-desktop"
    browser_directory.mkdir()
    _write_json(
        browser_directory / "summary.json",
        {
            "schema_version": "guide-mainline-contract-browser-audit-v1",
            "trajectory_set": "bounded",
            "viewport": "desktop",
            "turn_count": 0,
            "invalid_clarification_count": 0,
            "trajectories": [],
            "passed": False,
        },
    )
    _write_json(
        browser_directory / "runner-failure.json",
        {
            "schema_version": "guide-browser-runner-failure-v1",
            "failure_turn_id": "bounded-runner-startup",
            "error_type": "TimeoutError",
            "error_message": "Page.goto: Timeout 30000ms exceeded: /chat",
        },
    )
    completed = attempt_ledger.complete_attempt(
        context,
        result="failed",
        first_failure_turn_id="bounded-runner-startup",
        first_failure_owner="browser_audit",
        failure_code="TimeoutError",
        evidence_directory=str(context.parent),
    )
    evidence_hashes, evidence_bundle_sha256 = (
        attempt_ledger._recorded_failure_evidence_binding(
            completed,
            evidence_directory=context.parent,
        )
    )
    repair_files = {}
    for name in (
        "pre_fix_reproduction",
        "post_fix_verification",
        "focused_zero_api",
        "repair_patch",
    ):
        path = tmp_path / f"{name}.json"
        _write_json(path, {"name": name})
        repair_files[name] = path
    repair_hashes = {
        name: sha256(path.read_bytes()).hexdigest()
        for name, path in repair_files.items()
    }
    ledger_payload = attempt_ledger.read_ledger(ledger)
    context_payload = json.loads(context.read_text(encoding="utf-8"))
    readiness_payload = json.loads(
        readiness.read_text(encoding="utf-8")
    )
    audit = tmp_path / "failure-reclassification.json"
    _write_json(
        audit,
        {
            "schema_version": (
                "guide-smoke-failure-reclassification-v1"
            ),
            "passed": True,
            "plan_revision": completed["plan_revision"],
            "attempt_id": completed["attempt_id"],
            "evidence_directory": str(context.parent.resolve()),
            "first_failure_turn_id": "bounded-runner-startup",
            "code_revision": completed["code_revision"],
            "attempt_context_sha256": completed["context_sha256"],
            "attempt_record_sha256": context_payload[
                "attempt_record_sha256"
            ],
            "readiness_path": str(readiness.resolve()),
            "readiness_sha256": context_payload["readiness_sha256"],
            "protected_payload_sha256": readiness_payload[
                "protected_payload_sha256"
            ],
            "pre_reclassification_ledger_revision": ledger_payload[
                "revision"
            ],
            "previous_failure_owner": "browser_audit",
            "previous_failure_code": "TimeoutError",
            "first_failure_owner": "runtime_gate",
            "failure_code": (
                "runtime_shell_authority_lease_timeout"
            ),
            "reviewed_evidence_sha256": evidence_hashes,
            "evidence_bundle_sha256": evidence_bundle_sha256,
            "repair_evidence_files": {
                name: str(path.resolve())
                for name, path in repair_files.items()
            },
            "repair_evidence_sha256": repair_hashes,
            "conclusion": "Reclassify the shell startup timeout.",
        },
    )
    lock_depth = 0
    real_ledger_lock = attempt_ledger._ledger_lock

    @contextmanager
    def tracked_ledger_lock(path: Path, *, shared: bool = False):
        nonlocal lock_depth
        with real_ledger_lock(path, shared=shared) as binding:
            lock_depth += 1
            try:
                yield binding
            finally:
                lock_depth -= 1

    repair_validation_events: list[str] = []

    def validate_repair(**_: object) -> None:
        assert lock_depth == 0
        repair_validation_events.append("validated")

    monkeypatch.setattr(
        attempt_ledger,
        "_ledger_lock",
        tracked_ledger_lock,
    )
    monkeypatch.setattr(
        attempt_ledger,
        "_validate_reclassification_repair",
        validate_repair,
    )

    reclassified = attempt_ledger.reclassify_failed_attempt(
        ledger_path=ledger,
        attempt_id=str(completed["attempt_id"]),
        independent_audit_path=audit,
    )

    assert reclassified["first_failure_owner"] == "runtime_gate"
    assert reclassified["failure_code"] == (
        "runtime_shell_authority_lease_timeout"
    )
    assert len(reclassified["failure_reclassifications"]) == 1
    assert repair_validation_events == ["validated"]


def test_authorization_validates_repair_before_exclusive_ledger_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    readiness, audit = _readiness(tmp_path, ledger=ledger)
    lock_depth = 0
    real_ledger_lock = attempt_ledger._ledger_lock

    @contextmanager
    def tracked_ledger_lock(path: Path, *, shared: bool = False):
        nonlocal lock_depth
        with real_ledger_lock(path, shared=shared) as binding:
            lock_depth += 1
            try:
                yield binding
            finally:
                lock_depth -= 1

    repair_validation_events: list[str] = []

    def validate_repair(*_: object, **__: object) -> None:
        assert lock_depth == 0
        repair_validation_events.append("validated")

    monkeypatch.setattr(
        attempt_ledger,
        "_ledger_lock",
        tracked_ledger_lock,
    )
    monkeypatch.setattr(
        attempt_ledger,
        "_verify_retry_repair_artifacts",
        validate_repair,
    )

    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256="a" * 64,
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: json.loads(
            readiness.read_text(encoding="utf-8")
        ),
    )

    assert authorization_id.startswith("auth_")
    assert repair_validation_events == ["validated"]


def test_version_sync_timeout_reclassification_uses_runtime_gate_owner(
) -> None:
    failure_code = "runtime_version_sync_authority_check_timeout"

    assert attempt_ledger._RECLASSIFICATION_OWNER_BY_CODE[
        failure_code
    ] == "runtime_gate"
    assert failure_code in attempt_ledger._ACTIVE_RECLASSIFICATION_CODES


def test_retry_authorization_comes_from_verified_ledger_repair_history(
) -> None:
    repair_files = {
        "pre_fix_reproduction": "/evidence/pre-fix.xml",
        "post_fix_verification": "/evidence/post-fix.xml",
        "focused_zero_api": "/evidence/focused.xml",
        "repair_patch": "/evidence/repair.patch",
    }
    ledger = {
        "attempts": [
            {
                **_historical_failure(),
                "first_failure_owner": "dom_rendering",
                "failure_reclassifications": [
                    {
                        "repair_evidence_files": repair_files,
                        "independent_audit_path": (
                            "/evidence/failure-audit.json"
                        ),
                    }
                ],
            }
        ]
    }

    owner, repair_epoch, repair_evidence = (
        attempt_ledger._retry_authorization_from_verified_ledger(
            ledger,
            plan_revision="task11-r1",
        )
    )

    assert owner == "dom_rendering"
    assert repair_epoch == 1
    assert repair_evidence == {
        "local_reproduction": "/evidence/pre-fix.xml",
        "focused_test": "/evidence/focused.xml",
        "shared_owner_repair": "/evidence/repair.patch",
    }
    source = inspect.getsource(attempt_ledger.authorize_attempt)
    assert "_retry_authorization_from_verified_ledger" in source
    assert 'audit.get("repair_epoch")' not in source


def test_new_plan_revision_inherits_latest_verified_repair_history() -> None:
    repair_files = {
        "pre_fix_reproduction": "/evidence/pre-fix.xml",
        "post_fix_verification": "/evidence/post-fix.xml",
        "focused_zero_api": "/evidence/focused.xml",
        "repair_patch": "/evidence/repair.patch",
    }
    ledger = {
        "attempts": [
            {
                **_historical_failure(),
                "plan_revision": "task11-r5",
                "first_failure_owner": "dom_rendering",
                "failure_reclassifications": [
                    {
                        "repair_evidence_files": repair_files,
                        "independent_audit_path": (
                            "/evidence/failure-audit.json"
                        ),
                    }
                ],
            }
        ]
    }

    owner, repair_epoch, repair_evidence = (
        attempt_ledger._retry_authorization_from_verified_ledger(
            ledger,
            plan_revision="task11-r6",
        )
    )

    assert owner == "dom_rendering"
    assert repair_epoch == 0
    assert repair_evidence == {
        "local_reproduction": "/evidence/pre-fix.xml",
        "focused_test": "/evidence/focused.xml",
        "shared_owner_repair": "/evidence/repair.patch",
    }


def _zero_card_repair_payload(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, Path]]:
    source_root = Path(
        "docs/audits/final-release/mainline-contract-closure/"
        "repair-epoch-26"
    )
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
        shutil.copy2(source_root / path.name, path)
    payload = {
        "attempts": [
            {
                **_historical_failure(),
                "plan_revision": "task11-r5",
                "first_failure_owner": "dom_rendering",
                "failure_code": "zero_card_feedback_target_lookup",
                "failure_reclassifications": [
                    {
                        "repair_evidence_files": {
                            name: str(path.resolve())
                            for name, path in repair_files.items()
                        },
                    }
                ],
            }
        ]
    }
    return payload, repair_files


def _planning_state_repair_payload(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, Path]]:
    source_root = Path(
        "docs/audits/final-release/mainline-contract-closure/"
        "repair-epoch-30"
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
        shutil.copy2(source_root / path.name, path)
    payload = {
        "attempts": [
            {
                **_historical_failure(),
                "attempt_id": "bounded-smoke-attempt-09",
                "plan_revision": "2026-08-25-task11-r6",
                "first_failure_owner": "planning_state",
                "failure_code": (
                    "missing_persisted_image_scenario_inputs"
                ),
                "failure_reclassifications": [
                    {
                        "repair_evidence_files": {
                            name: str(path.resolve())
                            for name, path in repair_files.items()
                        },
                    }
                ],
            }
        ]
    }
    return payload, repair_files


def test_retry_authorization_revalidates_latest_zero_card_repair(
    tmp_path: Path,
) -> None:
    payload, _ = _zero_card_repair_payload(tmp_path)

    attempt_ledger._verify_retry_repair_artifacts(
        payload,
        plan_revision="task11-r6",
    )


def test_retry_authorization_rejects_fabricated_zero_card_repair(
    tmp_path: Path,
) -> None:
    payload, repair_files = _zero_card_repair_payload(tmp_path)
    repair_files["pre_fix_reproduction"].write_text(
        '<testsuite tests="1" failures="1" errors="0"/>',
        encoding="utf-8",
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="retry repair evidence is invalid",
    ):
        attempt_ledger._verify_retry_repair_artifacts(
            payload,
            plan_revision="task11-r6",
        )


def test_retry_authorization_revalidates_latest_planning_state_repair(
    tmp_path: Path,
) -> None:
    payload, _ = _planning_state_repair_payload(tmp_path)

    attempt_ledger._verify_retry_repair_artifacts(
        payload,
        plan_revision="2026-08-26-task11-r9",
    )


def test_retry_authorization_rejects_fabricated_planning_state_repair(
    tmp_path: Path,
) -> None:
    payload, repair_files = _planning_state_repair_payload(tmp_path)
    repair_files["pre_fix_reproduction"].write_text(
        '<testsuite tests="1" failures="1" errors="0"/>',
        encoding="utf-8",
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="retry repair evidence is invalid",
    ):
        attempt_ledger._verify_retry_repair_artifacts(
            payload,
            plan_revision="2026-08-26-task11-r9",
        )


def test_failure_reclassification_cannot_erase_owner_failure_count() -> None:
    first = {
        **_historical_failure(),
        "attempt_id": "bounded-smoke-attempt-01",
        "first_failure_owner": "planning_state",
    }
    second = {
        **_historical_failure(),
        "attempt_id": "bounded-smoke-attempt-02",
        "first_failure_owner": "dom_rendering",
        "failure_reclassifications": [
            {
                "previous_failure_owner": "planning_state",
                "first_failure_owner": "dom_rendering",
            }
        ],
    }
    ledger = {"attempts": [first, second]}

    counts = attempt_ledger._failure_counts(
        ledger,
        plan_revision="task11-r1",
    )

    assert counts["planning_state"] == 2
    assert counts["dom_rendering"] == 1
    assert attempt_ledger._circuit_state(ledger) == "open"


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

    before = ledger.read_bytes()
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="unsupported failure reclassification",
    ):
        attempt_ledger.reclassify_failed_attempt(
            ledger_path=ledger,
            attempt_id="bounded-smoke-attempt-03",
            independent_audit_path=audit,
        )
    assert ledger.read_bytes() == before

    audit_payload = json.loads(audit.read_text(encoding="utf-8"))
    audit_payload["failure_code"] = (
        "missing_persisted_image_scenario_inputs"
    )
    _write_json(audit, audit_payload)
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="reclassification repair evidence is invalid",
    ):
        attempt_ledger.reclassify_failed_attempt(
            ledger_path=ledger,
            attempt_id="bounded-smoke-attempt-03",
            independent_audit_path=audit,
        )
    assert ledger.read_bytes() == before


def test_passed_phase_cannot_be_authorized_again(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, readiness, context = _allocated_context(tmp_path)
    runtime_proof = _consume_runtime_bound_for_test(
        monkeypatch,
        ledger=ledger,
        readiness=readiness,
        context=context,
    )
    _write_passed_bounded_evidence(
        context,
        runtime_proof=runtime_proof,
    )
    attempt_ledger.complete_attempt(context, result="passed")
    completed = attempt_ledger.read_ledger(ledger)["attempts"][-1]
    assert completed["runtime_registrations"][-1]["state"] == (
        "terminated"
    )
    assert completed["runtime_registrations"][-1]["terminated_at"]
    assert attempt_ledger.read_ledger(ledger)["revision_chain"][-1][
        "operation"
    ] == "attempt_completed"

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="phase already passed",
    ):
        attempt_ledger.authorize_attempt(
            phase="bounded",
            expected_manifest_sha256="a" * 64,
            readiness_path=readiness,
            ledger_path=ledger,
            independent_audit_path=tmp_path / "independent-audit.json",
            readiness_verifier=lambda **_: json.loads(
                readiness.read_text(encoding="utf-8")
            ),
        )


def _two_valid_ledgers_for_one_canonical_path(
    tmp_path: Path,
) -> tuple[Path, Path, bytes]:
    visible_directory = tmp_path / "visible"
    ledger = visible_directory / "ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    original_directory = tmp_path / "original"
    visible_directory.rename(original_directory)

    attempt_ledger.initialize_ledger(
        ledger,
        attempts=(_historical_failure(),),
    )
    attacker_bytes = ledger.read_bytes()
    attacker_directory = tmp_path / "attacker"
    visible_directory.rename(attacker_directory)
    original_directory.rename(visible_directory)
    return ledger, attacker_directory, attacker_bytes


def test_ledger_read_rejects_ancestor_replacement_during_leaf_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, attacker_directory, _ = (
        _two_valid_ledgers_for_one_canonical_path(tmp_path)
    )
    displaced_directory = tmp_path / "displaced-read"
    real_open = attempt_ledger.os.open
    swapped = False

    def swap_parent_before_leaf_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(os.fspath(path)).name == ledger.name:
            ledger.parent.rename(displaced_directory)
            attacker_directory.rename(ledger.parent)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(attempt_ledger.os, "open", swap_parent_before_leaf_open)

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="ledger path changed",
    ):
        attempt_ledger.read_ledger(ledger)


def test_ledger_write_rejects_ancestor_replacement_during_atomic_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ledger, attacker_directory, attacker_bytes = (
        _two_valid_ledgers_for_one_canonical_path(tmp_path)
    )
    displaced_directory = tmp_path / "displaced-write"
    real_replace = attempt_ledger.os.replace
    swapped = False

    def swap_parent_before_replace(source, target, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(os.fspath(target)).name == ledger.name:
            ledger.parent.rename(displaced_directory)
            attacker_directory.rename(ledger.parent)
            swapped = True
        return real_replace(source, target, *args, **kwargs)

    monkeypatch.setattr(
        attempt_ledger.os,
        "replace",
        swap_parent_before_replace,
    )

    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="ledger path changed",
    ):
        attempt_ledger.compare_and_swap_ledger(
            ledger,
            expected_revision=0,
            mutate=lambda payload: payload,
        )

    assert ledger.read_bytes() == attacker_bytes
