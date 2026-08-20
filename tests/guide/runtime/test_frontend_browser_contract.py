from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPORT = (
    ROOT
    / "docs/audits/frontend-integration/browser_closure_v1.json"
)
MARKDOWN = (
    ROOT
    / "docs/audits/frontend-integration/browser_closure.md"
)
SCREENSHOTS = (
    ROOT
    / "docs/audits/frontend-integration/screenshots"
)
MODE_FIXTURE = (
    ROOT
    / "tests/fixtures/guide/presentation/"
    "frontend_mode_matrix_v1.jsonl"
)


def _report() -> dict:
    assert REPORT.is_file(), "browser closure report must be published"
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _expected_cases() -> dict[str, dict]:
    return {
        row["case_id"]: row
        for row in (
            json.loads(line)
            for line in MODE_FIXTURE.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        )
    }


def test_browser_closure_covers_every_mode_and_viewport() -> None:
    report = _report()
    expected = _expected_cases()

    assert report["schema_version"] == (
        "guide-frontend-browser-closure-v1"
    )
    assert report["viewports"] == {
        "desktop": {"height": 900, "width": 1440},
        "mobile": {"height": 844, "width": 390},
    }
    rows = report["mode_runs"]
    assert len(rows) == len(expected) * 2
    assert {
        (row["case_id"], row["viewport"])
        for row in rows
    } == {
        (case_id, viewport)
        for case_id in expected
        for viewport in ("desktop", "mobile")
    }


def test_browser_closure_has_no_card_image_or_layout_defect() -> None:
    expected = _expected_cases()

    for row in _report()["mode_runs"]:
        contract = expected[row["case_id"]]
        assert row["inline_card_ids"] == contract["inline_card_ids"]
        assert row["full_card_ids"] == contract["full_card_ids"]
        assert row["third_card_ids"] == []
        assert row["comparison_table_count"] == (
            1
            if "comparison" in contract["section_order"]
            else 0
        )
        assert row["thinking_removed_after_first_character"] is True
        assert row["console_errors"] == []
        assert row["network_failures"] == []
        assert row["image_failures"] == []
        assert row["horizontal_overflow"] is False
        assert row["overlap_count"] == 0
        assert row["clipped_text_count"] == 0
        assert row["nonblank_pixel_ratio"] > 0.01
        screenshot = ROOT / row["screenshot"]
        assert screenshot.is_file()
        assert screenshot.stat().st_size > 10_000
        assert screenshot.is_relative_to(SCREENSHOTS)


def test_browser_closure_records_real_sse_and_visual_shell_lock() -> None:
    report = _report()
    live = report["live_sse"]

    assert live["translator_call_count"] <= 1
    assert live["copywriter_call_count"] == 0
    assert live["copywriter_call_count_source"] == (
        "presentation_contract.telemetry"
    )
    assert live["third_model_call_count"] == 0
    assert live["presentation_before_message"] is True
    assert live["thinking_started_immediately"] is True
    assert live["thinking_removed_after_first_character"] is True
    assert live["console_errors"] == []
    assert live["network_failures"] == []
    assert report["visual_shell_drift_count"] == 0


def test_browser_closure_markdown_uses_the_audited_url() -> None:
    report = _report()

    assert f"Local URL: `{report['url']}`" in MARKDOWN.read_text(
        encoding="utf-8"
    )
