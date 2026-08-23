from hashlib import sha256
import json
from pathlib import Path

import pytest

from tools.guide_gates import attempt_ledger
import tools.guide_gates.record_manual_screenshot_review as manual_review


ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = (
    ROOT / "tools/guide_gates/record_manual_screenshot_review.py"
)


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
        b"\x89PNG\r\n\x1a\n" + f"{viewport}:{mode}".encode()
    )
    _write_json(turn_dir / "console.json", [])
    _write_json(turn_dir / "network.json", [])


def _release_attempt(
    tmp_path: Path,
    *,
    result: str = "passed",
) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    output = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "release-browser-attempt-01"
    )
    output.mkdir(parents=True)
    readiness = root / "task11-release-readiness.json"
    _write_json(
        readiness,
        {
            "schema_version": "guide-task11-release-readiness-v1",
            "plan_revision": "2026-08-23-task11-r5",
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
        "context_path": str(
            output.parent / "translation-attempt-01/attempt-context.json"
        ),
        "result": "passed",
    }
    browser_attempt = {
        "attempt_id": "release-browser-attempt-01",
        "plan_revision": "2026-08-23-task11-r5",
        "repair_epoch": 8,
        "retry_authorization_id": "auth-browser",
        "code_revision": "a" * 40,
        "started_at": "2026-08-23T11:00:00Z",
        "trajectory_set": "browser",
        "context_path": str(context_path.resolve()),
        "evidence_directory": str(output.resolve()),
        "result": result,
    }
    context = {
        "schema_version": "guide-smoke-attempt-context-v1",
        "context_id": "context-release-browser",
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
        "allocated_ledger_revision": 4,
        "attempt_record_sha256": (
            attempt_ledger._attempt_allocation_sha256(browser_attempt)
        ),
    }
    context_path.write_text(
        json.dumps(context, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    browser_attempt["context_sha256"] = sha256(
        context_path.read_bytes()
    ).hexdigest()
    _write_json(
        ledger,
        {
            "schema_version": "guide-smoke-attempt-ledger-v1",
            "revision": 4,
            "circuit_state": "closed",
            "attempts": [translation_attempt, browser_attempt],
            "authorizations": [],
        },
    )

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
    root, context, _ = _release_attempt(tmp_path)
    (context.parent / relative_path).write_bytes(content)

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
    root, context, summary = _release_attempt(tmp_path)
    contract = (
        context.parent
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

    root, context, summary = _release_attempt(
        tmp_path / "summary-drift"
    )
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["artifact_sha256"][
        next(iter(payload["artifact_sha256"]))
    ] = "0" * 64
    _write_json(summary, payload)
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
