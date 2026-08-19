import json
from pathlib import Path

import tools.guide_gates.runtime_browser_adversarial as adversarial_gate


TWO_IMAGE_GATE = Path("tools/guide_gates/two_image_browser_gate.py")
TEXT_GATE = Path("tools/guide_gates/runtime_browser_smoke.py")
COMBINED_IMAGE_GATE = Path(
    "tools/guide_gates/combined_image_browser_gate.py"
)
ADVERSARIAL_GATE = Path(
    "tools/guide_gates/runtime_browser_adversarial.py"
)


def test_two_image_gate_enforces_owned_feedback_contract() -> None:
    source = TWO_IMAGE_GATE.read_text(encoding="utf-8")

    assert 'locator(".message-feedback").count() == 0' not in source
    for contract_fragment in (
        "feedback_target",
        "conversation_version",
        "displayed_product_ids",
        "profile_version",
        '".message-wrapper.ai"',
        '":scope > .message-feedback"',
        '"thumbs_up"',
        '"thumbs_down"',
        '"有帮助"',
        '"无帮助"',
        '"data-compare-product-ids"',
        '"event_type": "compare"',
        '"product_ids": [53, 55]',
        '"owner"',
        '"session_id"',
        '"#feedbackModal"',
        '".welcome-shell"',
        '".image-analysis-hint"',
        '".evidence-section"',
        '".recommendation-panel"',
        '".citations-section"',
    ):
        assert contract_fragment in source


def test_two_image_gate_submits_negative_feedback_through_real_ui() -> None:
    source = TWO_IMAGE_GATE.read_text(encoding="utf-8")

    assert 'page.locator("#feedbackCancel").click()' not in source
    for contract_fragment in (
        "as compare_request_info, page.expect_response(",
        "compare_request = compare_request_info.value",
        'compare_request.method == "POST"',
        "compare_request.post_data_json",
        '_feedback_request_matches(request, "compare")',
        '_feedback_request_matches(response.request, "compare")',
        "compare_response.status == 200",
        'compare_receipt["event_type"] == "compare"',
        'page.locator("#feedbackText").fill("没有帮助")',
        "as negative_request_info, page.expect_response(",
        'page.locator("#feedbackSubmit").click()',
        'negative_request.method == "POST"',
        "negative_request.post_data_json",
        '_feedback_request_matches(request, "negative_feedback")',
        '_feedback_request_matches(response.request, "negative_feedback")',
        "negative_response.status == 200",
        'negative_receipt["event_type"] == "negative_feedback"',
        "negative_target == feedback_target",
        'negative_target["displayed_product_ids"] == [53, 55]',
        'negative_body["conversation_version"] == (',
        'evidence["end"]["conversation_version"]',
        'negative_body["profile_version"] == (',
        'feedback_target.get("profile_version")',
        'negative_body["payload"] == {',
        '"event_type": "negative_feedback"',
        '"reason": "not_helpful"',
        "set(negative_body) == {",
        '"conversation_version"',
        '"profile_version"',
        '"idempotency_key"',
        '"payload"',
        'len(final_feedback["requests"]) == 2',
        'len(final_feedback["responses"]) == 2',
        'final_feedback["requests"][0]["body"] == comparison_body',
        'final_feedback["requests"][1]["body"] == negative_body',
        'final_feedback["responses"][0] == comparison_response',
        'expect(page.locator("#feedbackModal")).to_be_hidden()',
        'expect(thumbs_down).to_have_class(',
        'expect(thumbs_up).not_to_have_class(',
        "thumbs_down.is_disabled() is False",
        "thumbs_up.is_disabled() is False",
        "assert not page_errors, page_errors",
        "assert not console_errors, console_errors",
    ):
        assert contract_fragment in source


def test_two_image_gate_serves_offline_icons_without_console_failure() -> None:
    source = TWO_IMAGE_GATE.read_text(encoding="utf-8")

    assert "lambda route: route.abort()" not in source
    for contract_fragment in (
        "def _serve_offline_icons(route) -> None:",
        "route.fulfill(",
        "status=200,",
        'content_type="application/javascript",',
        'body="",',
        'page.route("https://unpkg.com/**", _serve_offline_icons)',
    ):
        assert contract_fragment in source


def test_runtime_adversarial_evidence_dir_is_optional() -> None:
    default_args = adversarial_gate._parse_args([])
    evidence_args = adversarial_gate._parse_args(
        ["--evidence-dir", "/private/tmp/runtime-evidence"]
    )

    assert default_args.evidence_dir is None
    assert evidence_args.evidence_dir == Path(
        "/private/tmp/runtime-evidence"
    )


def test_real_followup_revision_and_image_gates_require_category_facts(
) -> None:
    text_source = TEXT_GATE.read_text(encoding="utf-8")
    image_source = COMBINED_IMAGE_GATE.read_text(encoding="utf-8")

    for contract_fragment in (
        "def _assert_category_fact_blocks(",
        "_assert_category_fact_blocks(\n"
        "            repair_panel,\n"
        "            expected_cards=2,",
        "_assert_category_fact_blocks(\n"
        "            repair_panels.nth(2),\n"
        "            expected_cards=1,",
        "_assert_category_fact_blocks(\n"
        "            budget_panels.nth(1),\n"
        "            expected_cards=1,",
        '".category-facts"',
        '".category-fact-row"',
    ):
        assert contract_fragment in text_source

    for contract_fragment in (
        "def _assert_category_fact_blocks(",
        "_assert_category_fact_blocks(\n"
        "        panel,\n"
        "        expected_cards=len(expected_ids),",
        '".category-facts"',
        '".category-fact-row"',
    ):
        assert contract_fragment in image_source


class _ScreenshotPage:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def screenshot(self, **kwargs: object) -> None:
        self.calls.append(kwargs)
        Path(str(kwargs["path"])).write_bytes(b"png")


def test_runtime_adversarial_writes_png_and_json_sidecar(
    tmp_path: Path,
) -> None:
    page = _ScreenshotPage()
    payload = {
        "scenario": "late_event",
        "session_ids": ["session-a", "session-b"],
        "request_aborted": True,
        "late_emit": {"message": True, "end": True},
        "dom_absence": {"late_message": True},
        "versions": {},
    }

    adversarial_gate._write_evidence(
        page,
        tmp_path,
        "late-event",
        payload,
    )

    assert page.calls == [
        {
            "path": str(tmp_path / "late-event.png"),
            "full_page": True,
        }
    ]
    assert (tmp_path / "late-event.png").read_bytes() == b"png"
    assert json.loads(
        (tmp_path / "late-event.json").read_text(encoding="utf-8")
    ) == payload


def test_runtime_adversarial_default_does_not_write_evidence(
    tmp_path: Path,
) -> None:
    page = _ScreenshotPage()

    adversarial_gate._write_evidence(
        page,
        None,
        "unused",
        {"scenario": "unused"},
    )

    assert page.calls == []
    assert list(tmp_path.iterdir()) == []


def test_runtime_adversarial_wires_three_scenario_sidecars() -> None:
    source = ADVERSARIAL_GATE.read_text(encoding="utf-8")

    for basename in (
        '"session-switch"',
        '"late-event"',
        '"current-session-reactivation"',
    ):
        assert basename in source
