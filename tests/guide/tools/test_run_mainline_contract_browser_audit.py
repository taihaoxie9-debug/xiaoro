from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.guide_gates.run_mainline_contract_browser_audit as mainline_audit
from tools.guide_gates.run_mainline_contract_browser_audit import (
    AuditBundleError,
    FIXTURE_TURN_IDS,
    REQUIRED_TURN_FILES,
    fixture_sse_bytes,
    required_public_text,
    validate_audit_bundle,
)


ROOT = Path(__file__).resolve().parents[3]


def test_chat_marks_assistant_wrapper_with_request_id() -> None:
    html = (ROOT / "app/static/chat.html").read_text(
        encoding="utf-8"
    )

    assert (
        "typingDiv.dataset.guideRequestId = requestContext.requestId"
        in html
    )


def test_zero_api_fixture_streams_are_typed_terminal_contracts() -> None:
    assert FIXTURE_TURN_IDS == (
        "fixture-explore-recommendation",
        "fixture-fit-recommendation",
        "fixture-product-knowledge",
        "fixture-comparison",
        "fixture-image-identity",
        "fixture-image-fit-recommendation",
        "fixture-multi-image-comparison",
    )
    for turn_id in FIXTURE_TURN_IDS:
        raw = fixture_sse_bytes(turn_id)
        assert b"event: presentation_contract\n" in raw
        assert raw.endswith(b"event: end\ndata: {\"conversation_version\":1}\n\n")
    multi_image = fixture_sse_bytes(
        "fixture-multi-image-comparison"
    )
    assert multi_image.count(b"event: image_observation\n") == 2


def test_fixture_audit_all_viewports_runs_desktop_then_mobile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, str]] = []

    def fake_run_fixture_browser_audit(
        *,
        base_url: str,
        output: Path,
        viewport: str,
    ) -> dict[str, object]:
        calls.append((output, viewport))
        output.mkdir(parents=True, exist_ok=False)
        return {
            "base_url": base_url,
            "viewport": viewport,
            "turn_count": 7,
            "passed": True,
        }

    monkeypatch.setattr(
        mainline_audit,
        "run_fixture_browser_audit",
        fake_run_fixture_browser_audit,
    )

    report = mainline_audit.run_fixture_browser_audits(
        base_url="http://127.0.0.1:8795",
        output=tmp_path / "all",
        viewport="all",
    )

    assert calls == [
        (tmp_path / "all" / "desktop", "desktop"),
        (tmp_path / "all" / "mobile", "mobile"),
    ]
    assert report["passed"] is True
    assert report["turn_count"] == 14
    assert report["invalid_clarification_count"] == 0
    assert (tmp_path / "all" / "summary.json").is_file()


def test_bounded_real_trajectories_are_fixed_and_image_grounded() -> None:
    trajectories = mainline_audit.BOUNDED_TRAJECTORIES

    assert [trajectory.trajectory_id for trajectory in trajectories] == [
        "bounded-text-fit",
        "bounded-text-context",
        "bounded-image-context",
    ]
    assert [turn.message for turn in trajectories[0].turns] == [
        "给我推荐一款 900 到 1100 元的精华，我是油敏肌，换季容易泛红",
    ]
    assert [turn.message for turn in trajectories[1].turns] == [
        "给我推荐 900 到 1100 元的精华",
        "第二款的质地适合什么肤质？",
        "我现在有点换季泛红，T 区出油，我可能是什么肤质？",
        "确认",
        "回到刚才的推荐，第一款和第二款哪个更适合我的肤质？",
    ]
    assert trajectories[2].turns[0].image_path == (
        ROOT / "tests/fixtures/guide/images/product-38-index-control.png"
    )
    assert trajectories[2].turns[0].expected_image_product_id == 38
    assert trajectories[0].turns[0].allow_clarification is True
    assert all(
        turn.allow_clarification is False
        for trajectory in trajectories[1:]
        for turn in trajectory.turns
    )
    assert [turn.message for turn in trajectories[2].turns] == [
        "",
        "给我找两款相似的，我最近换季泛红，T 区出油。",
        "图片里的 B5 和第一款哪个更适合我的肤质？",
    ]


def test_bounded_contract_rejects_copywriter_fallback() -> None:
    with pytest.raises(
        AuditBundleError,
        match="bounded smoke forbids fallback copy",
    ):
        mainline_audit.validate_bounded_contract(
            {
                "mode": "recommendation",
                "recommendation_mode": "fit",
                "copy_source": "fallback",
                "telemetry": {
                    "fallback_reason": "provider_unavailable",
                },
            },
            expected_mode="recommendation",
            expected_recommendation_mode="fit",
            expected_image_product_id=None,
            observations=(),
        )


def test_bounded_contract_accepts_authoritative_knowledge_copy() -> None:
    mainline_audit.validate_bounded_contract(
        {
            "mode": "product_knowledge",
            "copy_source": "authoritative",
            "telemetry": {
                "fallback_reason": None,
            },
        },
        expected_mode="product_knowledge",
        expected_recommendation_mode=None,
        expected_image_product_id=None,
        observations=(),
    )


def test_bounded_terminal_accepts_typed_clarification() -> None:
    mainline_audit.validate_bounded_contract(
        {
            "terminal_kind": "clarification",
            "clarification": {
                "question": "请补充一个更明确的使用场景。",
                "clarification_code": "goal",
                "intended_responsibility": "recommendation",
                "intended_recommendation_mode": "fit",
                "clarification_basis": "fit_selection_evidence_gap",
                "fit_gap_stage": "decision_selection",
                "fit_decision_status": "INSUFFICIENT_FOR_WINNER",
                "fit_candidate_count": 2,
                "fit_evidence_ref_count": 1,
                "fit_public_fact_count": 0,
            },
        },
        expected_mode="recommendation",
        expected_recommendation_mode="fit",
        expected_image_product_id=None,
        observations=(),
        allow_clarification=True,
    )


def test_bounded_terminal_rejects_unproved_fit_clarification() -> None:
    with pytest.raises(
        AuditBundleError,
        match="invalid fit clarification",
    ):
        mainline_audit.validate_bounded_contract(
            {
                "terminal_kind": "clarification",
                "clarification": {
                    "question": "请补充一个更明确的使用场景。",
                    "clarification_code": "goal",
                },
            },
            expected_mode="recommendation",
            expected_recommendation_mode="fit",
            expected_image_product_id=None,
            observations=(),
            allow_clarification=True,
        )


def test_bounded_terminal_rejects_unexpected_clarification() -> None:
    with pytest.raises(
        AuditBundleError,
        match="unexpected clarification terminal",
    ):
        mainline_audit.validate_bounded_contract(
            {
                "terminal_kind": "clarification",
                "clarification": {
                    "question": "请补充一个更明确的使用场景。",
                    "clarification_code": "goal",
                },
            },
            expected_mode="recommendation",
            expected_recommendation_mode="explore",
            expected_image_product_id=None,
            observations=(),
            allow_clarification=False,
        )


def test_bounded_runner_stops_after_first_trajectory_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fail_first_trajectory(
        *,
        trajectory: object,
        **_: object,
    ) -> dict[str, object]:
        calls.append(trajectory.trajectory_id)
        raise AuditBundleError("bounded smoke forbids fallback copy")

    monkeypatch.setattr(
        mainline_audit,
        "_run_bounded_browser_trajectory",
        fail_first_trajectory,
        raising=False,
    )

    with pytest.raises(
        AuditBundleError,
        match="bounded smoke forbids fallback copy",
    ):
        mainline_audit.run_bounded_browser_audit(
            base_url="http://127.0.0.1:8821",
            output=tmp_path / "bounded",
            viewport="desktop",
        )

    assert calls == ["bounded-text-fit"]


def test_authorized_bounded_verifies_and_consumes_before_browser(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "attempt-context.json"
    output = tmp_path / "bounded-smoke-attempt-02"
    output.mkdir()
    readiness_path = tmp_path / "readiness.json"
    ledger_path = tmp_path / "ledger.json"
    calls: list[str] = []
    context = {
        "output_directory": str(output),
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
    }
    context_path.write_text(
        json.dumps(context) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mainline_audit,
        "read_attempt_context",
        lambda *args, **kwargs: calls.append("read") or context,
    )
    monkeypatch.setattr(
        mainline_audit,
        "verify_task11_readiness",
        lambda **kwargs: calls.append("verify") or {},
    )
    monkeypatch.setattr(
        mainline_audit,
        "consume_attempt_context",
        lambda *args, **kwargs: calls.append("consume") or context,
    )
    monkeypatch.setattr(
        mainline_audit,
        "run_bounded_browser_audit",
        lambda **kwargs: calls.append("browser")
        or {"passed": True, "invalid_clarification_count": 0},
    )
    monkeypatch.setattr(
        mainline_audit,
        "complete_attempt",
        lambda *args, **kwargs: calls.append("complete") or {},
    )

    report = mainline_audit.run_authorized_bounded_browser_audit(
        base_url="http://127.0.0.1:8821",
        attempt_context=context_path,
        viewport="desktop",
    )

    assert report["passed"] is True
    assert calls == [
        "read",
        "verify",
        "consume",
        "browser",
        "complete",
    ]


def test_authorized_bounded_records_structured_first_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "attempt-context.json"
    output = tmp_path / "bounded-smoke-attempt-02"
    output.mkdir()
    readiness_path = tmp_path / "readiness.json"
    ledger_path = tmp_path / "ledger.json"
    context = {
        "output_directory": str(output),
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
    }
    context_path.write_text(json.dumps(context), encoding="utf-8")
    completions: list[dict[str, object]] = []

    monkeypatch.setattr(
        mainline_audit,
        "read_attempt_context",
        lambda *args, **kwargs: context,
    )
    monkeypatch.setattr(
        mainline_audit,
        "verify_task11_readiness",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        mainline_audit,
        "consume_attempt_context",
        lambda *args, **kwargs: context,
    )

    def fail_browser(**_: object) -> dict[str, object]:
        raise mainline_audit.BoundedAuditFailure(
            turn_id="bounded-image-context-t1",
            owner="presentation_provenance",
            failure_code="fallback_copy",
            evidence_directory=output / "browser-desktop" / "image",
        )

    monkeypatch.setattr(
        mainline_audit,
        "run_bounded_browser_audit",
        fail_browser,
    )
    monkeypatch.setattr(
        mainline_audit,
        "complete_attempt",
        lambda *args, **kwargs: completions.append(kwargs) or {},
    )

    with pytest.raises(mainline_audit.BoundedAuditFailure):
        mainline_audit.run_authorized_bounded_browser_audit(
            base_url="http://127.0.0.1:8821",
            attempt_context=context_path,
            viewport="desktop",
        )

    assert completions == [{
        "result": "failed",
        "first_failure_turn_id": "bounded-image-context-t1",
        "first_failure_owner": "presentation_provenance",
        "failure_code": "fallback_copy",
        "evidence_directory": str(
            output / "browser-desktop" / "image"
        ),
    }]


def test_cli_output_contract_separates_fixture_and_real_runs() -> None:
    output = Path("/tmp/fixture-output")
    context = Path("/tmp/attempt-context.json")

    assert mainline_audit.resolve_cli_output(
        trajectory_set="fixture",
        output=output,
        attempt_context=None,
    ) == output
    with pytest.raises(
        AuditBundleError,
        match="requires --attempt-context",
    ):
        mainline_audit.resolve_cli_output(
            trajectory_set="bounded",
            output=output,
            attempt_context=None,
        )
    with pytest.raises(
        AuditBundleError,
        match="forbids --output",
    ):
        mainline_audit.resolve_cli_output(
            trajectory_set="bounded",
            output=output,
            attempt_context=context,
        )


def test_live_terminal_wait_passes_capture_count_by_keyword() -> None:
    calls: list[tuple[str, int | None, int]] = []

    class PageProbe:
        def wait_for_function(
            self,
            expression: str,
            *,
            arg: int | None = None,
            timeout: int,
        ) -> None:
            calls.append((expression, arg, timeout))

        def evaluate(self, expression: str) -> list[object]:
            assert expression == (
                "() => window.__mainlineAuditCaptureErrors"
            )
            return []

    mainline_audit._wait_for_live_terminal(
        PageProbe(),
        expected_capture_count=3,
    )

    assert calls == [
        (
            (
                """expected => (
            window.__mainlineAuditCaptures.length >= expected
            && window.__mainlineAuditCaptureErrors.length === 0
            && typeof activeChatRequests !== 'undefined'
            && activeChatRequests.size === 0
        )"""
            ),
            3,
            120_000,
        )
    ]


def test_live_bundle_preserves_typed_error_terminal_and_owner(
    tmp_path: Path,
) -> None:
    raw_stream = (
        b"event: error\n"
        b"data: {\"error\":\"PROVIDER_UNAVAILABLE\"}\n\n"
    )

    class PageProbe:
        def evaluate(self, expression: str, *_: object) -> object:
            if expression.startswith("index =>"):
                return {
                    "method": "POST",
                    "url": "http://127.0.0.1:8821/api/v1/chat/stream",
                    "body": json.dumps({"message": "请求失败"}),
                    "bytes": list(raw_stream),
                    "events": [
                        {
                            "event": "error",
                            "data": {
                                "error": "PROVIDER_UNAVAILABLE",
                            },
                        }
                    ],
                }
            if ".message-wrapper.ai[data-guide-request-id]" in expression:
                return "request-live-001"
            raise AssertionError(expression)

        def screenshot(self, *, path: str, full_page: bool) -> None:
            assert full_page is True
            Path(path).write_bytes(b"png")

    turn = mainline_audit.BOUNDED_TRAJECTORIES[0].turns[0]
    with pytest.raises(
        mainline_audit.BoundedContractError,
        match="PROVIDER_UNAVAILABLE",
    ) as caught:
        mainline_audit._write_live_turn_bundle(
            page=PageProbe(),
            turn_dir=tmp_path,
            trajectory_id="bounded-text-fit",
            turn=turn,
            viewport="desktop",
            capture_index=0,
            evidence={"console": [], "network": []},
        )

    assert caught.value.owner == "sse_contract"
    assert caught.value.failure_code == "PROVIDER_UNAVAILABLE"
    assert (tmp_path / "stream.sse").read_bytes() == raw_stream
    assert set(REQUIRED_TURN_FILES) <= {
        path.name for path in tmp_path.iterdir()
    }
    assert json.loads(
        (tmp_path / "presentation-contract.json").read_text(
            encoding="utf-8"
        )
    ) == {
        "terminal_kind": "error",
        "error": {
            "error": "PROVIDER_UNAVAILABLE",
        },
    }


def test_live_bundle_persists_raw_sse_after_failed_wrapper_is_removed(
    tmp_path: Path,
) -> None:
    raw_stream = (
        b"event: error\n"
        b"data: {\"error\":\"PROVIDER_UNAVAILABLE\"}\n\n"
    )

    class PageProbe:
        def evaluate(self, expression: str, *_: object) -> object:
            if expression.startswith("index =>"):
                return {
                    "method": "POST",
                    "url": "http://127.0.0.1:8821/api/v1/chat/stream",
                    "body": json.dumps({"message": "请求失败"}),
                    "bytes": list(raw_stream),
                    "events": [
                        {
                            "event": "error",
                            "data": {
                                "error": "PROVIDER_UNAVAILABLE",
                            },
                        }
                    ],
                }
            if ".message-wrapper.ai[data-guide-request-id]" in expression:
                return None
            raise AssertionError(expression)

        def screenshot(self, *, path: str, full_page: bool) -> None:
            assert full_page is True
            Path(path).write_bytes(b"png")

    turn = mainline_audit.BOUNDED_TRAJECTORIES[0].turns[0]
    with pytest.raises(
        mainline_audit.BoundedContractError,
        match="PROVIDER_UNAVAILABLE",
    ) as caught:
        mainline_audit._write_live_turn_bundle(
            page=PageProbe(),
            turn_dir=tmp_path,
            trajectory_id="bounded-text-fit",
            turn=turn,
            viewport="desktop",
            capture_index=0,
            evidence={"console": [], "network": []},
        )

    assert caught.value.owner == "sse_contract"
    assert caught.value.failure_code == "PROVIDER_UNAVAILABLE"
    assert (tmp_path / "stream.sse").read_bytes() == raw_stream
    request = json.loads(
        (tmp_path / "request.json").read_text(encoding="utf-8")
    )
    assert request["request_id"] is None
    assert json.loads(
        (tmp_path / "presentation-contract.json").read_text(
            encoding="utf-8"
        )
    )["terminal_kind"] == "error"


def test_saved_error_terminal_is_owned_by_sse_contract(
    tmp_path: Path,
) -> None:
    (tmp_path / "presentation-contract.json").write_text(
        json.dumps(
            {
                "terminal_kind": "error",
                "error": {
                    "error": "GUIDE_INTERNAL_ERROR",
                    "message": "推荐暂时不可用，请稍后重试。",
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "terminal-dom.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    assert (
        mainline_audit._failure_owner_from_bundle(tmp_path)
        == "sse_contract"
    )


def test_live_bundle_writes_typed_clarification_terminal(
    tmp_path: Path,
) -> None:
    clarification = {
        "question": "请补充一个更明确的使用场景。",
        "clarification_code": "goal",
    }
    raw_stream = (
        b"event: start\n"
        b"data: {\"session_id\":\"clarification\"}\n\n"
        b"event: intent\n"
        b"data: {\"intent\":\"clarify\"}\n\n"
        b"event: clarify\n"
        b"data: {\"question\":\""
        b"\xe8\xaf\xb7\xe8\xa1\xa5\xe5\x85\x85\xe4\xb8\x80\xe4\xb8\xaa"
        b"\xe6\x9b\xb4\xe6\x98\x8e\xe7\xa1\xae\xe7\x9a\x84\xe4\xbd\xbf"
        b"\xe7\x94\xa8\xe5\x9c\xba\xe6\x99\xaf\xe3\x80\x82\","
        b"\"clarification_code\":\"goal\"}\n\n"
        b"event: end\n"
        b"data: {\"conversation_version\":1}\n\n"
    )

    class PageProbe:
        def evaluate(self, expression: str, *_: object) -> object:
            if expression.startswith("index =>"):
                return {
                    "method": "POST",
                    "url": "http://127.0.0.1:8821/api/v1/chat/stream",
                    "body": json.dumps({"message": "请求澄清"}),
                    "bytes": list(raw_stream),
                    "events": [
                        {
                            "event": "start",
                            "data": {"session_id": "clarification"},
                        },
                        {
                            "event": "intent",
                            "data": {"intent": "clarify"},
                        },
                        {"event": "clarify", "data": clarification},
                        {
                            "event": "end",
                            "data": {"conversation_version": 1},
                        },
                    ],
                }
            if expression.startswith("input =>"):
                return {
                    "request_id": "request-clarification-001",
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
                }
            if ".message-wrapper.ai[data-guide-request-id]" in expression:
                return "request-clarification-001"
            raise AssertionError(expression)

        def screenshot(self, *, path: str, full_page: bool) -> None:
            assert full_page is True
            Path(path).write_bytes(b"png")

    turn = mainline_audit.BOUNDED_TRAJECTORIES[0].turns[0]
    terminal, observations = mainline_audit._write_live_turn_bundle(
        page=PageProbe(),
        turn_dir=tmp_path,
        trajectory_id="bounded-text-fit",
        turn=turn,
        viewport="desktop",
        capture_index=0,
        evidence={"console": [], "network": []},
    )

    assert terminal == {
        "terminal_kind": "clarification",
        "clarification": clarification,
    }
    assert observations == ()
    validate_audit_bundle(
        tmp_path,
        expected_turn_id="bounded-text-fit-t1",
    )


def test_audit_bundle_requires_same_turn_contract_dom_and_screenshot(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        AuditBundleError,
        match="presentation-contract.json",
    ):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="text-fit-001",
        )


def test_audit_bundle_accepts_bound_contract_dom_and_screenshot(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "text-fit-001",
        "request_id": "request-001",
        "viewport": {"width": 1440, "height": 1000},
    }
    contract = {
        "mode": "recommendation",
        "visible_product_ids": [38],
        "sections": [
            {"kind": "summary", "copy_text": "先看修护路线。"},
            {
                "kind": "product",
                "product_id": 38,
                "copy_text": "品牌主打修护舒缓。",
                "advisor_reason": "更贴合换季泛红。",
                "direct_facts": [
                    {
                        "fact_id": "fact:38:ingredient",
                        "label": "核心成分",
                        "display_value": "维生素原 B5\n（泛醇）",
                    }
                ],
            },
            {"kind": "closing", "copy_text": None},
            {"kind": "full_cards", "copy_text": None},
        ],
    }
    dom = {
        "request_id": "request-001",
        "presentation_mode": "recommendation",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": [
            "summary",
            "product",
            "closing",
            "full_cards",
        ],
        "section_blocks": [
            {"kind": "summary", "text": "先看修护路线。"},
            {
                "kind": "product",
                "text": (
                    "品牌主打修护舒缓。 维生素原 B5 （泛醇） "
                    "更贴合换季泛红。"
                ),
            },
            {"kind": "closing", "text": ""},
            {"kind": "full_cards", "text": "本轮提到的商品"},
        ],
        "inline_product_ids": [38],
        "visible_product_ids": [38],
        "shelf_product_ids": [38],
        "presentation_text": (
            "先看修护路线。 品牌主打修护舒缓。 "
            "更贴合换季泛红。 维生素原 B5 （泛醇）"
        ),
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": (
            "event: presentation_contract\n"
            f"data: {json.dumps(contract)}\n\n"
        ),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": "not-empty",
        "console.json": "[]",
        "network.json": "[]",
    }
    for name, content in payloads.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    validate_audit_bundle(
        tmp_path,
        expected_turn_id="text-fit-001",
    )

    assert set(REQUIRED_TURN_FILES) == set(payloads)
    assert required_public_text(tuple(contract["sections"])) == (
        "先看修护路线。",
        "品牌主打修护舒缓。",
        "更贴合换季泛红。",
        "维生素原 B5\n（泛醇）",
    )


def test_comparison_bundle_requires_visible_comparison_table(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "image-comparison-001",
        "request_id": "request-image-comparison-001",
    }
    contract = {
        "mode": "comparison",
        "visible_product_ids": [38, 91],
        "sections": [{"kind": "comparison"}],
        "comparison_rows": [
            {
                "dimension_id": "brand_main",
                "label": "品牌主打",
                "cells": [],
            }
        ],
    }
    dom = {
        "request_id": "request-image-comparison-001",
        "presentation_mode": "comparison",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": ["comparison"],
        "section_blocks": [
            {"kind": "comparison", "text": ""},
        ],
        "inline_product_ids": [],
        "visible_product_ids": [38, 91],
        "shelf_product_ids": [38, 91],
        "comparison_table_count": 0,
        "presentation_text": "",
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": (
            "event: presentation_contract\n"
            f"data: {json.dumps(contract)}\n\n"
        ),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": "not-empty",
        "console.json": "[]",
        "network.json": "[]",
    }
    for name, content in payloads.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    with pytest.raises(
        AuditBundleError,
        match="comparison table count mismatch",
    ):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="image-comparison-001",
        )


def test_audit_bundle_accepts_shelf_only_product_knowledge(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "knowledge-001",
        "request_id": "request-knowledge-001",
    }
    contract = {
        "mode": "product_knowledge",
        "visible_product_ids": [38],
        "sections": [
            {"kind": "summary", "copy_text": "先确认这款精华。"},
            {
                "kind": "answer",
                "copy_text": "品牌主打修护舒缓。",
            },
            {"kind": "full_cards", "copy_text": None},
        ],
    }
    dom = {
        "request_id": "request-knowledge-001",
        "presentation_mode": "product_knowledge",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": ["summary", "answer", "full_cards"],
        "section_blocks": [
            {"kind": "summary", "text": "先确认这款精华。"},
            {"kind": "answer", "text": "品牌主打修护舒缓。"},
            {"kind": "full_cards", "text": "本轮提到的商品"},
        ],
        "inline_product_ids": [],
        "visible_product_ids": [38],
        "shelf_product_ids": [38],
        "presentation_text": "先确认这款精华。 品牌主打修护舒缓。",
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": (
            "event: presentation_contract\n"
            f"data: {json.dumps(contract)}\n\n"
        ),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": "not-empty",
        "console.json": "[]",
        "network.json": "[]",
    }
    for name, content in payloads.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    validate_audit_bundle(
        tmp_path,
        expected_turn_id="knowledge-001",
    )


def test_audit_bundle_accepts_typed_terminal_clarification(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "fit-clarification-001",
        "request_id": "request-clarification-001",
    }
    terminal = {
        "terminal_kind": "clarification",
        "clarification": {
            "question": "请补充一个更明确的使用场景。",
            "clarification_code": "goal",
        },
    }
    dom = {
        "request_id": "request-clarification-001",
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
        "presentation_text": "请补充一个更明确的使用场景。",
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": (
            "event: start\n"
            "data: {\"session_id\":\"clarification\"}\n\n"
            "event: intent\n"
            "data: {\"intent\":\"clarify\"}\n\n"
            "event: clarify\n"
            "data: {\"question\":\"请补充一个更明确的使用场景。\","
            "\"clarification_code\":\"goal\"}\n\n"
            "event: end\n"
            "data: {\"conversation_version\":1}\n\n"
        ),
        "presentation-contract.json": json.dumps(terminal),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": "not-empty",
        "console.json": "[]",
        "network.json": "[]",
    }
    for name, content in payloads.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    validate_audit_bundle(
        tmp_path,
        expected_turn_id="fit-clarification-001",
    )


def test_audit_bundle_rejects_inline_card_outside_product_section(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "knowledge-002",
        "request_id": "request-knowledge-002",
    }
    contract = {
        "mode": "product_knowledge",
        "visible_product_ids": [38],
        "sections": [
            {"kind": "answer", "copy_text": "品牌主打修护舒缓。"},
            {"kind": "full_cards", "copy_text": None},
        ],
    }
    dom = {
        "request_id": "request-knowledge-002",
        "presentation_mode": "product_knowledge",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": ["answer", "full_cards"],
        "section_blocks": [
            {"kind": "answer", "text": "品牌主打修护舒缓。"},
            {"kind": "full_cards", "text": "本轮提到的商品"},
        ],
        "inline_product_ids": [38],
        "visible_product_ids": [38],
        "shelf_product_ids": [38],
        "presentation_text": "品牌主打修护舒缓。",
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": (
            "event: presentation_contract\n"
            f"data: {json.dumps(contract)}\n\n"
        ),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": "not-empty",
        "console.json": "[]",
        "network.json": "[]",
    }
    for name, content in payloads.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    with pytest.raises(
        AuditBundleError,
        match="DOM inline product IDs mismatch",
    ):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="knowledge-002",
        )


def test_audit_bundle_rejects_copy_rendered_in_wrong_section(
    tmp_path: Path,
) -> None:
    request = {
        "turn_id": "block-owner-001",
        "request_id": "request-block-owner-001",
    }
    contract = {
        "mode": "recommendation",
        "visible_product_ids": [38],
        "sections": [
            {"kind": "summary", "copy_text": "先看修护路线。"},
            {
                "kind": "product",
                "product_id": 38,
                "copy_text": "品牌主打修护舒缓。",
                "advisor_reason": "更贴合当前肤况。",
                "direct_facts": [],
            },
            {"kind": "full_cards", "copy_text": None},
        ],
    }
    dom = {
        "request_id": "request-block-owner-001",
        "presentation_mode": "recommendation",
        "legacy_message_count": 0,
        "legacy_product_card_count": 0,
        "turn_presentation_root_count": 1,
        "visible_section_kinds": [
            "summary",
            "product",
            "full_cards",
        ],
        "section_blocks": [
            {
                "kind": "summary",
                "text": "先看修护路线。 品牌主打修护舒缓。",
            },
            {
                "kind": "product",
                "text": "理肤泉新B5多效修护精华 更贴合当前肤况。",
            },
            {"kind": "full_cards", "text": "本轮提到的商品"},
        ],
        "inline_product_ids": [38],
        "visible_product_ids": [38],
        "shelf_product_ids": [38],
        "presentation_text": (
            "先看修护路线。 品牌主打修护舒缓。 "
            "理肤泉新B5多效修护精华 更贴合当前肤况。"
        ),
    }
    payloads = {
        "request.json": json.dumps(request),
        "stream.sse": (
            "event: presentation_contract\n"
            f"data: {json.dumps(contract)}\n\n"
        ),
        "presentation-contract.json": json.dumps(contract),
        "terminal-dom.json": json.dumps(dom),
        "screenshot.png": "not-empty",
        "console.json": "[]",
        "network.json": "[]",
    }
    for name, content in payloads.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    with pytest.raises(
        AuditBundleError,
        match="DOM section text mismatch",
    ):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="block-owner-001",
        )


def test_audit_bundle_rejects_dom_contract_drift(
    tmp_path: Path,
) -> None:
    for name in REQUIRED_TURN_FILES:
        (tmp_path / name).write_bytes(
            b"png"
            if name == "screenshot.png"
            else b"[]"
        )
    (tmp_path / "request.json").write_text(
        json.dumps(
            {
                "turn_id": "comparison-001",
                "request_id": "request-001",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "presentation-contract.json").write_text(
        json.dumps(
            {
                "mode": "comparison",
                "visible_product_ids": [38, 91],
                "sections": [{"kind": "comparison"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "terminal-dom.json").write_text(
        json.dumps(
            {
                "request_id": "request-002",
                "presentation_mode": "recommendation",
                "legacy_message_count": 0,
                "legacy_product_card_count": 0,
                "turn_presentation_root_count": 1,
                "visible_section_kinds": ["summary"],
                "visible_product_ids": [38],
                "shelf_product_ids": [38],
                "presentation_text": "",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AuditBundleError, match="DOM request ID mismatch"):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="comparison-001",
        )
