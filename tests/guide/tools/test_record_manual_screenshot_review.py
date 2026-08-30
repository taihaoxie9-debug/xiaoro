from hashlib import sha256
import json
from pathlib import Path
import struct
import zlib
from collections.abc import Callable

import pytest

from tools.guide_gates import attempt_ledger
import tools.guide_gates.record_manual_screenshot_review as manual_review


ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = (
    ROOT / "tools/guide_gates/record_manual_screenshot_review.py"
)
EXPECTED_MANIFEST_SHA256 = "f" * 64


def test_manual_screenshot_review_tool_exists() -> None:
    assert TOOL_PATH.is_file()


EXPECTED_MODES = (
    "explore_recommendation",
    "fit_recommendation",
    "product_knowledge",
    "comparison",
    "image_identity",
    "image_fit_recommendation",
    "image_comparison",
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

    split = width // 2
    row = (
        b"\xff\xff\xff" * split
        + b"\x20\x70\xb0" * (width - split)
    )
    pixels = b"".join(b"\x00" + row for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(autouse=True)
def _verified_release_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        manual_review,
        "verify_task11_readiness",
        lambda **_: {},
        raising=False,
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _contract_for_mode(mode: str) -> dict[str, object]:
    contract_mode = {
        "explore_recommendation": "recommendation",
        "fit_recommendation": "recommendation",
        "product_knowledge": "product_knowledge",
        "comparison": "comparison",
        "image_identity": "image_identity",
        "image_fit_recommendation": "recommendation",
        "image_comparison": "comparison",
    }[mode]
    recommendation_mode = {
        "explore_recommendation": "explore",
        "fit_recommendation": "fit",
        "image_fit_recommendation": "fit",
    }.get(mode)
    return {
        "mode": contract_mode,
        "recommendation_mode": recommendation_mode,
        "visible_product_ids": [],
        "sections": [],
    }


def _write_turn_bundle(
    turn_dir: Path,
    *,
    turn_id: str,
    viewport: str,
    mode: str,
) -> None:
    dimensions = {
        "desktop": {"width": 1440, "height": 1000},
        "mobile": {"width": 390, "height": 844},
    }[viewport]
    request_id = f"{viewport}-{mode}"
    contract = _contract_for_mode(mode)
    _write_json(
        turn_dir / "request.json",
        {
            "turn_id": turn_id,
            "request_id": request_id,
            "viewport": dimensions,
            "body": {
                "message": mode,
                "stream": True,
            },
        },
    )
    (turn_dir / "stream.sse").write_text(
        "event: start\n"
        f"data: {{\"session_id\":\"{request_id}\"}}\n\n"
        "event: presentation_contract\n"
        f"data: {json.dumps(contract, sort_keys=True)}\n\n"
        "event: end\n"
        'data: {"conversation_version": 1}\n\n',
        encoding="utf-8",
    )
    _write_json(turn_dir / "presentation-contract.json", contract)
    _write_json(
        turn_dir / "terminal-dom.json",
        {
            "request_id": request_id,
            "presentation_mode": contract["mode"],
            "legacy_message_count": 0,
            "legacy_product_card_count": 0,
            "turn_presentation_root_count": 1,
            "visible_section_kinds": [],
            "section_blocks": [],
            "inline_product_ids": [],
            "visible_product_ids": [],
            "shelf_product_ids": [],
            "comparison_table_count": (
                1 if contract["mode"] == "comparison" else 0
            ),
            "presentation_text": "",
        },
    )
    (turn_dir / "screenshot.png").write_bytes(
        _png_bytes(
            dimensions["width"],
            dimensions["height"],
        )
    )
    _write_json(turn_dir / "console.json", [])
    _write_json(turn_dir / "network.json", [])


def _release_attempt(
    tmp_path: Path,
    *,
    result: str = "passed",
    before_terminal_evidence: Callable[[Path, Path, Path], None] | None = None,
) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    output = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "release-browser-attempt-01"
    )
    output.mkdir(parents=True)
    translation_root = output.parent / "translation-attempt-01"
    focused = translation_root / "focused.json"
    _write_json(
        focused,
        {
            "schema_version": "guide-final-focused-gate-v1",
            "passed": True,
        },
    )
    fixture_path = (
        "tests/fixtures/guide/final_release/"
        "real_translation_12x4_v5.jsonl"
    )
    fixture_sha256 = sha256((ROOT / fixture_path).read_bytes()).hexdigest()
    translation = translation_root / "real-translation"
    translation_results = translation / "results.jsonl"
    translation_results.parent.mkdir(parents=True)
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
    translation_summary = translation / "summary.json"
    _write_json(
        translation_summary,
        {
            "schema_version": "guide-final-real-translation-summary-v1",
            "passed": True,
            "fixture_path": fixture_path,
            "fixture_sha256": fixture_sha256,
            "focused_summary_sha256": sha256(
                focused.read_bytes()
            ).hexdigest(),
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
    backend = translation_root / "real-backend"
    backend_results = backend / "results.jsonl"
    backend_results.parent.mkdir(parents=True)
    fixture_rows = [
        json.loads(line)
        for line in (ROOT / fixture_path).read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    image_sha256_by_product = {
        row["product_id"]: row["source_image_sha256"]
        for row in (
            json.loads(line)
            for line in (
                ROOT / "data/canonical/seed_product_images_v1.jsonl"
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
                    "coverage": {
                        "required_concept_ids": [],
                        "covered_concept_ids": [],
                        "required_entity_ids": [],
                        "covered_entity_ids": [],
                        "required_relation_intents": [],
                        "covered_relation_intents": [],
                        "missing_concept_ids": [],
                        "missing_entity_ids": [],
                        "missing_relation_intents": [],
                        "complete": True,
                    },
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
    readiness = root / "task11-release-readiness.json"
    _write_json(
        readiness,
        {
            "schema_version": "guide-task11-release-readiness-v1",
            "plan_revision": "2026-08-23-task11-r5",
            "reviewed_candidate_manifest_sha256": (
                EXPECTED_MANIFEST_SHA256
            ),
            "candidate_head": "a" * 40,
        },
    )
    ledger = output.parent / "smoke-attempt-ledger.json"
    context_path = output / "attempt-context.json"
    translation_attempt = {
        "attempt_id": "translation-attempt-01",
        "plan_revision": "2026-08-23-task11-r5",
        "repair_epoch": 8,
        "retry_authorization_id": "auth-translation",
        "code_revision": "a" * 40,
        "started_at": "2026-08-23T10:00:00Z",
        "trajectory_set": "translation",
        "context_path": "historical-unavailable",
        "result": "passed",
    }
    browser_attempt = {
        "attempt_id": "release-browser-attempt-01",
        "plan_revision": "2026-08-23-task11-r5",
        "repair_epoch": 8,
        "retry_authorization_id": "auth-browser",
        "code_revision": "a" * 40,
        "expected_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "started_at": "2026-08-23T11:00:00Z",
        "trajectory_set": "browser",
        "context_path": str(context_path.resolve()),
        "evidence_directory": str(output.resolve()),
        "result": result,
        "allocated_ledger_revision": 1,
        "allocated_ledger_hash": None,
        "context_sha256": None,
    }
    ledger_payload = {
        "schema_version": "guide-smoke-attempt-ledger-v1",
        "ledger_path": str(ledger.resolve()),
        "revision": 0,
        "circuit_state": "closed",
        "attempts": [translation_attempt],
        "authorizations": [],
        "revision_chain": [],
    }
    attempt_ledger._append_revision(
        ledger_payload,
        operation="initialized",
    )
    ledger_payload["attempts"].append(browser_attempt)
    ledger_payload["revision"] = 1
    allocation = attempt_ledger._append_revision(
        ledger_payload,
        operation="attempt_allocated",
        attempt_id=browser_attempt["attempt_id"],
        authorization_id=browser_attempt["retry_authorization_id"],
    )
    browser_attempt["allocated_ledger_hash"] = allocation[
        "revision_hash"
    ]
    context = {
        "schema_version": "guide-smoke-attempt-context-v1",
        "expected_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "context_id": "context-release-browser",
        "current_phase": "browser",
        "parent_attempt_id": "translation-attempt-01",
        "phase_attempt_ids": {
            "translation": "translation-attempt-01",
            "browser": "release-browser-attempt-01",
        },
        "phase_authorization_ids": {
            "translation": "auth-translation",
            "browser": "auth-browser",
        },
        "output_directory": str(output.resolve()),
        "readiness_path": str(readiness.resolve()),
        "readiness_sha256": sha256(readiness.read_bytes()).hexdigest(),
        "ledger_path": str(ledger.resolve()),
        "allocated_ledger_revision": 1,
        "allocated_ledger_hash": allocation["revision_hash"],
        "attempt_record_sha256": (
            attempt_ledger._attempt_allocation_sha256(browser_attempt)
        ),
        "required_parent_summary": {
            "phase": "backend",
            "result": "passed",
            "path": str(backend_summary.resolve()),
            "sha256": sha256(backend_summary.read_bytes()).hexdigest(),
        },
    }
    _write_json(context_path, context)
    browser_attempt["context_sha256"] = sha256(
        context_path.read_bytes()
    ).hexdigest()

    turns: list[dict[str, str]] = []
    for viewport in ("desktop", "mobile"):
        for mode in EXPECTED_MODES:
            turn_id = f"{viewport}-{mode}"
            relative = Path(f"browser-{viewport}") / mode
            _write_turn_bundle(
                output / relative,
                turn_id=turn_id,
                viewport=viewport,
                mode=mode,
            )
            turns.append(
                {
                    "turn_id": turn_id,
                    "viewport": viewport,
                    "mode": mode,
                    "directory": relative.as_posix(),
                }
            )

    indexed = {
        path.relative_to(root).as_posix(): sha256(
            path.read_bytes()
        ).hexdigest()
        for directory_name in (
            "browser-desktop",
            "browser-mobile",
            "mainline-browser",
        )
        for path in sorted((output / directory_name).rglob("*"))
        if path.is_file()
    }
    summary = output / "mainline-browser/summary.json"
    _write_json(
        summary,
        {
            "schema_version": (
                "guide-mainline-contract-browser-audit-v1"
            ),
            "trajectory_set": "release",
            "viewport": "all",
            "passed": True,
            "turn_count": 14,
            "serious_failure_count": 0,
            "frontend_contract_violation_count": 0,
            "wrong_binding_count": 0,
            "unaligned_price_specification_count": 0,
            "copywriter_fallback_count": 0,
            "invalid_clarification_count": 0,
            "turns": turns,
            "artifact_sha256": indexed,
        },
    )
    if before_terminal_evidence is not None:
        before_terminal_evidence(root, output, summary)
    browser_attempt["terminal_evidence"] = (
        attempt_ledger._terminal_evidence_manifest(
            output_directory=output,
            evidence_directory=output,
        )
    )
    browser_attempt["completed_at"] = "2026-08-23T12:30:00Z"
    ledger_payload["revision"] = 2
    attempt_ledger._append_revision(
        ledger_payload,
        operation="attempt_completed",
        attempt_id=browser_attempt["attempt_id"],
        authorization_id=browser_attempt["retry_authorization_id"],
    )
    _write_json(ledger, ledger_payload)
    return root, context_path, summary


def _passing_reviews() -> list[dict[str, object]]:
    return [
        {
            "viewport": viewport,
            "mode": mode,
            "reviewer_id": "release-reviewer",
            "reviewed_at": "2026-08-23T12:00:00Z",
            "verdict": "passed",
            "issue_codes": [],
        }
        for viewport in ("desktop", "mobile")
        for mode in EXPECTED_MODES
    ]


def _demo_evidence(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "repo"
    output = root / "demo-real-acceptance"
    desktop = output / "browser-desktop-final"
    mobile = output / "browser-mobile-final"
    trajectories = {
        "explore_recommendation": "demo-explore-recommendation",
        "fit_recommendation": "demo-fit-recommendation",
        "product_knowledge": "demo-product-knowledge",
        "comparison": "demo-comparison",
        "image_identity": "demo-image-identity",
        "image_fit_recommendation": (
            "demo-image-fit-recommendation"
        ),
        "image_comparison": "demo-image-comparison",
    }
    terminal_modes = {
        **{mode: mode for mode in EXPECTED_MODES},
        "image_identity": "product_knowledge",
    }
    desktop_rows = []
    mobile_rows = []
    for mode, trajectory_id in trajectories.items():
        turns = []
        for turn_number in range(1, 4):
            turn_id = f"t{turn_number}"
            relative = Path(trajectory_id) / turn_id
            _write_turn_bundle(
                desktop / relative,
                turn_id=f"{trajectory_id}-{turn_id}",
                viewport="desktop",
                mode=terminal_modes[mode],
            )
            turns.append({
                "turn_id": turn_id,
                "directory": relative.as_posix(),
            })
        desktop_rows.append({
            "trajectory_id": trajectory_id,
            "turn_count": 3,
            "invalid_clarification_count": 0,
            "turns": turns,
        })
        relative = Path(trajectory_id) / "t3"
        _write_turn_bundle(
            mobile / relative,
            turn_id=f"{trajectory_id}-t3",
            viewport="mobile",
            mode=terminal_modes[mode],
        )
        source_stream = desktop / relative / "stream.sse"
        replayed_stream = mobile / relative / "stream.sse"
        replayed_stream.write_bytes(source_stream.read_bytes())
        digest = sha256(source_stream.read_bytes()).hexdigest()
        mobile_rows.append({
            "viewport": "mobile",
            "mode": mode,
            "turn_id": f"{trajectory_id}-t3",
            "directory": relative.as_posix(),
            "source_directory": relative.as_posix(),
            "source_stream_sha256": digest,
            "replayed_stream_sha256": digest,
        })
    desktop_summary = desktop / "summary.json"
    _write_json(
        desktop_summary,
        {
            "schema_version": (
                "guide-mainline-contract-browser-audit-v1"
            ),
            "trajectory_set": "demo",
            "viewport": "desktop",
            "passed": True,
            "turn_count": 21,
            "invalid_clarification_count": 0,
            "trajectories": desktop_rows,
        },
    )
    mobile_summary = mobile / "summary.json"
    _write_json(
        mobile_summary,
        {
            "schema_version": "guide-demo-mobile-replay-v1",
            "trajectory_set": "demo",
            "source_viewport": "desktop",
            "viewport": "mobile",
            "passed": True,
            "turn_count": 7,
            "exact_sse_match_count": 7,
            "source_summary": str(desktop_summary),
            "source_summary_sha256": sha256(
                desktop_summary.read_bytes()
            ).hexdigest(),
            "turns": mobile_rows,
        },
    )
    return (
        root,
        desktop_summary,
        mobile_summary,
        output / "manual-screenshot-review.json",
    )


@pytest.mark.parametrize(
    "issue_code",
    (
        "empty_or_unknown_content",
        "irrelevant_answer",
        "missing_fact_reason",
        "broken_followup_context",
    ),
)
def test_demo_content_issue_codes_are_controlled(
    issue_code: str,
) -> None:
    reviews = _passing_reviews()
    reviews[0]["verdict"] = "failed"
    reviews[0]["issue_codes"] = [issue_code]

    validated = manual_review._validated_reviews(reviews)

    assert validated[
        ("desktop", "explore_recommendation")
    ]["issue_codes"] == [issue_code]


def test_records_demo_review_from_real_desktop_and_exact_mobile_replay(
    tmp_path: Path,
) -> None:
    root, desktop, mobile, output = _demo_evidence(tmp_path)

    result = manual_review.record_demo_screenshot_review(
        desktop_summary_path=desktop,
        mobile_summary_path=mobile,
        output_path=output,
        reviews=_passing_reviews(),
        repo_root=root,
    )

    assert result["schema_version"] == (
        "guide-manual-screenshot-review-v1"
    )
    assert result["evidence_scope"] == "demo"
    assert result["passed"] is True
    assert result["manual_screenshot_review_count"] == 14
    assert result["manual_screenshot_failure_count"] == 0
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert {
        (row["viewport"], row["mode"])
        for row in result["rows"]
    } == {
        (viewport, mode)
        for viewport in ("desktop", "mobile")
        for mode in EXPECTED_MODES
    }


def test_records_exact_hash_bound_fourteen_row_review(
    tmp_path: Path,
) -> None:
    root, context, summary = _release_attempt(tmp_path)

    result = manual_review.record_manual_screenshot_review(
        attempt_context_path=context,
        reviews=_passing_reviews(),
        repo_root=root,
    )

    output = context.parent / "manual-screenshot-review.json"
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert result["schema_version"] == (
        "guide-manual-screenshot-review-v1"
    )
    assert result["passed"] is True
    assert result["manual_screenshot_review_count"] == 14
    assert result["manual_screenshot_failure_count"] == 0
    assert result["attempt_id"] == "release-browser-attempt-01"
    assert result["attempt_context_sha256"] == sha256(
        context.read_bytes()
    ).hexdigest()
    assert result["browser_summary_sha256"] == sha256(
        summary.read_bytes()
    ).hexdigest()
    assert {
        (row["viewport"], row["mode"])
        for row in result["rows"]
    } == {
        (viewport, mode)
        for viewport in ("desktop", "mobile")
        for mode in EXPECTED_MODES
    }
    for row in result["rows"]:
        screenshot = root / row["screenshot_path"]
        contract = root / row["presentation_contract_path"]
        assert row["screenshot_sha256"] == sha256(
            screenshot.read_bytes()
        ).hexdigest()
        assert row["presentation_contract_sha256"] == sha256(
            contract.read_bytes()
        ).hexdigest()


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda rows: rows.pop(),
            "exactly fourteen",
        ),
        (
            lambda rows: rows.__setitem__(1, dict(rows[0])),
            "duplicate",
        ),
        (
            lambda rows: rows[0].__setitem__("mode", "unknown"),
            "unknown review mode",
        ),
        (
            lambda rows: rows[0].__setitem__(
                "issue_codes",
                ["not-controlled"],
            ),
            "unknown issue code",
        ),
    ],
)
def test_rejects_missing_duplicate_or_unknown_review_rows(
    tmp_path: Path,
    mutate,
    match: str,
) -> None:
    root, context, _ = _release_attempt(tmp_path)
    reviews = _passing_reviews()
    mutate(reviews)

    with pytest.raises(
        manual_review.ManualScreenshotReviewError,
        match=match,
    ):
        manual_review.record_manual_screenshot_review(
            attempt_context_path=context,
            reviews=reviews,
            repo_root=root,
        )

    assert not (context.parent / "manual-screenshot-review.json").exists()


def test_failed_row_is_recorded_as_failed_release_evidence(
    tmp_path: Path,
) -> None:
    root, context, _ = _release_attempt(tmp_path)
    reviews = _passing_reviews()
    reviews[0]["verdict"] = "failed"
    reviews[0]["issue_codes"] = ["overlap"]

    result = manual_review.record_manual_screenshot_review(
        attempt_context_path=context,
        reviews=reviews,
        repo_root=root,
    )

    assert result["passed"] is False
    assert result["manual_screenshot_review_count"] == 14
    assert result["manual_screenshot_failure_count"] == 1


@pytest.mark.parametrize(
    ("relative_path", "content", "match"),
    [
        (
            "browser-desktop/explore_recommendation/screenshot.png",
            b"tampered screenshot",
            "artifact hash mismatch",
        ),
        (
            "browser-mobile/comparison/presentation-contract.json",
            b'{"mode": "product_knowledge"}\n',
            "artifact hash mismatch",
        ),
    ],
)
def test_rejects_screenshot_or_contract_hash_mismatch(
    tmp_path: Path,
    relative_path: str,
    content: bytes,
    match: str,
) -> None:
    def tamper(
        _root: Path,
        output: Path,
        _summary: Path,
    ) -> None:
        (output / relative_path).write_bytes(content)

    root, context, _ = _release_attempt(
        tmp_path,
        before_terminal_evidence=tamper,
    )

    with pytest.raises(
        manual_review.ManualScreenshotReviewError,
        match=match,
    ):
        manual_review.record_manual_screenshot_review(
            attempt_context_path=context,
            reviews=_passing_reviews(),
            repo_root=root,
        )


def test_rejects_contract_that_does_not_match_declared_review_mode(
    tmp_path: Path,
) -> None:
    def tamper(root: Path, output: Path, summary: Path) -> None:
        contract = (
            output
            / "browser-desktop/explore_recommendation"
            / "presentation-contract.json"
        )
        payload = json.loads(contract.read_text(encoding="utf-8"))
        payload["recommendation_mode"] = "fit"
        _write_json(contract, payload)
        summary_payload = json.loads(summary.read_text(encoding="utf-8"))
        relative = contract.relative_to(root).as_posix()
        summary_payload["artifact_sha256"][relative] = sha256(
            contract.read_bytes()
        ).hexdigest()
        _write_json(summary, summary_payload)

    root, context, _ = _release_attempt(
        tmp_path,
        before_terminal_evidence=tamper,
    )

    with pytest.raises(
        manual_review.ManualScreenshotReviewError,
        match="contract mode mismatch",
    ):
        manual_review.record_manual_screenshot_review(
            attempt_context_path=context,
            reviews=_passing_reviews(),
            repo_root=root,
        )


def test_rejects_attempt_context_and_summary_hash_drift(
    tmp_path: Path,
) -> None:
    root, context, summary = _release_attempt(tmp_path)
    readiness = Path(
        json.loads(context.read_text(encoding="utf-8"))[
            "readiness_path"
        ]
    )
    readiness.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        manual_review.ManualScreenshotReviewError,
        match="readiness hash mismatch",
    ):
        manual_review.record_manual_screenshot_review(
            attempt_context_path=context,
            reviews=_passing_reviews(),
            repo_root=root,
        )

    def corrupt_summary(
        _root: Path,
        _output: Path,
        summary: Path,
    ) -> None:
        payload = json.loads(summary.read_text(encoding="utf-8"))
        payload["artifact_sha256"][
            next(iter(payload["artifact_sha256"]))
        ] = "0" * 64
        _write_json(summary, payload)

    root, context, _ = _release_attempt(
        tmp_path / "summary-drift",
        before_terminal_evidence=corrupt_summary,
    )
    with pytest.raises(
        manual_review.ManualScreenshotReviewError,
        match="artifact hash mismatch",
    ):
        manual_review.record_manual_screenshot_review(
            attempt_context_path=context,
            reviews=_passing_reviews(),
            repo_root=root,
        )


def test_rejects_nonpassed_browser_attempt(tmp_path: Path) -> None:
    root, context, _ = _release_attempt(tmp_path, result="failed")

    with pytest.raises(
        manual_review.ManualScreenshotReviewError,
        match="browser attempt has not passed",
    ):
        manual_review.record_manual_screenshot_review(
            attempt_context_path=context,
            reviews=_passing_reviews(),
            repo_root=root,
        )


def test_review_verifies_release_readiness_before_browser_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, context, _ = _release_attempt(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        manual_review,
        "verify_task11_readiness",
        lambda **_: calls.append("readiness") or {},
        raising=False,
    )

    def stop_before_browser_artifacts(**_: object) -> tuple[object, str]:
        calls.append("browser")
        raise RuntimeError("stop after readiness verification")

    monkeypatch.setattr(
        manual_review,
        "_validate_browser_summary",
        stop_before_browser_artifacts,
    )

    with pytest.raises(
        RuntimeError,
        match="stop after readiness verification",
    ):
        manual_review.record_manual_screenshot_review(
            attempt_context_path=context,
            reviews=_passing_reviews(),
            repo_root=root,
        )

    assert calls == ["readiness", "browser"]


def test_rejects_overwriting_existing_review(tmp_path: Path) -> None:
    root, context, _ = _release_attempt(tmp_path)
    output = context.parent / "manual-screenshot-review.json"
    output.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        manual_review.ManualScreenshotReviewError,
        match="already exists",
    ):
        manual_review.record_manual_screenshot_review(
            attempt_context_path=context,
            reviews=_passing_reviews(),
            repo_root=root,
        )
