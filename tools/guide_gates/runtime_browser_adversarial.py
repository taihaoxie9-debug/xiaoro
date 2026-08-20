from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import Browser, Page, expect, sync_playwright


PROHIBITED_IMAGE_CAPABILITY_COPY = (
    "图片识别",
    "识别图片里的品牌",
    "识别品牌、品类",
    "图片没有识别到清晰的品牌",
    "我没有识别到清晰的品牌",
    "识别到商品：",
    "已识别图片内容",
    "识别图片内容",
    "识别分数约",
    "重新识别",
    "OCR识别结果",
)
MOCK_BUNDLE_ID = f"bundle_{'a' * 32}"
MOCK_BUNDLE_VERSION = 1
MOCK_OWNER_TOKEN = f"owner_{'b' * 43}"
IMAGE_BUNDLE_UNAVAILABLE_DETAIL = {
    "detail": {
        "code": "image_bundle_unavailable",
        "message": "图片引用不可用，请重新上传。",
        "ordinal": None,
    }
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/chat",
    )
    parser.add_argument("--evidence-dir", type=Path)
    return parser.parse_args(argv)


def _write_evidence(
    page: Page,
    evidence_dir: Path | None,
    basename: str,
    payload: dict[str, object],
) -> None:
    if evidence_dir is None:
        return
    evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    screenshot_path = evidence_dir / f"{basename}.png"
    sidecar_path = evidence_dir / f"{basename}.json"
    page.screenshot(path=str(screenshot_path), full_page=True)
    sidecar_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _stream_script(mode: str) -> str:
    return (
        r"""
(() => {
    const nativeFetch = window.fetch.bind(window);
    const encoder = new TextEncoder();
    const state = {
        mode: __MODE__,
        requests: [],
        uploads: [],
        deletes: [],
        bundle: null,
        emit(index, event, data) {
            const request = this.requests[index];
            if (!request || request.closed) return false;
            request.controller.enqueue(
                encoder.encode(
                    `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
                )
            );
            return true;
        },
        emitBytes(index, bytes) {
            const request = this.requests[index];
            if (!request || request.closed) return false;
            request.controller.enqueue(new Uint8Array(bytes));
            return true;
        },
        close(index) {
            const request = this.requests[index];
            if (!request || request.closed) return false;
            request.closed = true;
            request.controller.close();
            return true;
        },
        resolveUpload(index) {
            const request = this.uploads[index];
            if (!request || request.resolved) return false;
            request.resolved = true;
            const receipt = {
                bundle_id: __BUNDLE_ID__,
                version: __BUNDLE_VERSION__,
                owner_token: __OWNER_TOKEN__,
                expires_at: '2026-08-08T12:00:00Z',
                image_count: request.imageCount,
                message: '图片已安全接收，发送后将进行单图相似检索。'
            };
            this.bundle = {
                bundle_id: receipt.bundle_id,
                version: receipt.version,
                owner_token: receipt.owner_token,
                session_id: request.sessionId
            };
            request.resolve(new Response(JSON.stringify(receipt), {
                status: 201,
                headers: { 'Content-Type': 'application/json' }
            }));
            return true;
        }
    };
    window.__guideAdversarial = state;

    window.fetch = async (input, options = {}) => {
        const url = typeof input === 'string'
            ? input
            : String(input?.url || input);
        if (
            url.includes('/api/v1/chat/image-bundles')
            && options.method === 'POST'
        ) {
            return new Promise(resolve => {
                const upload = {
                    sessionId: String(
                        options.body?.get?.('session_id') || ''
                    ),
                    imageCount: options.body?.getAll?.('images')?.length || 0,
                    signalAttached: Boolean(options.signal),
                    aborted: false,
                    resolved: false,
                    resolve
                };
                state.uploads.push(upload);
                options.signal?.addEventListener(
                    'abort',
                    () => {
                        upload.aborted = true;
                    },
                    { once: true }
                );
            });
        }
        if (
            url.includes('/api/v1/chat/image-bundles/')
            && options.method === 'DELETE'
        ) {
            let body = null;
            try {
                body = JSON.parse(options.body || '{}');
            } catch (error) {
                body = null;
            }
            const requestPath = new URL(
                url,
                window.location.href
            ).pathname;
            const expectedPath = state.bundle
                ? (
                    '/api/v1/chat/image-bundles/'
                    + encodeURIComponent(state.bundle.bundle_id)
                )
                : null;
            const hasValidCredentials = Boolean(
                state.bundle
                && requestPath === expectedPath
                && body
                && body.session_id === state.bundle.session_id
                && body.version === state.bundle.version
                && body.owner_token === state.bundle.owner_token
            );
            state.deletes.push({
                url,
                body,
                status: hasValidCredentials ? 204 : 404
            });
            if (!hasValidCredentials) {
                return new Response(JSON.stringify({
                    detail: {
                        code: 'image_bundle_unavailable',
                        message: '图片引用不可用，请重新上传。',
                        ordinal: null
                    }
                }), {
                    status: 404,
                    headers: { 'Content-Type': 'application/json' }
                });
            }
            return new Response(null, { status: 204 });
        }
        if (!url.includes('/api/v1/chat/stream')) {
            return nativeFetch(input, options);
        }

        const request = {
            mode: state.mode,
            body: JSON.parse(options.body || '{}'),
            signalAttached: Boolean(options.signal),
            aborted: false,
            closed: false,
            controller: null
        };
        const index = state.requests.push(request) - 1;
        const stream = new ReadableStream({
            start(controller) {
                request.controller = controller;
                options.signal?.addEventListener(
                    'abort',
                    () => {
                        request.aborted = true;
                    },
                    { once: true }
                );
                state.emit(index, 'start', {
                    session_id: request.body.session_id
                });

                if (request.mode === 'error') {
                    state.emit(index, 'error', {
                        error: 'GUIDE_INTERNAL_ERROR',
                        message: '推荐暂时不可用，请稍后重试。'
                    });
                    state.close(index);
                } else if (
                    request.mode === 'missing_end'
                    || request.mode === 'malformed_contract'
                ) {
                    state.emit(index, 'intent', {
                        intent: 'recommend',
                        entities: {},
                        guide: true
                    });
                    state.emit(index, 'answer_contract', {
                        answer_contract: {
                            product_count: 1,
                            winner_status: 'SELECTED',
                            has_unknown_skin: true
                        }
                    });
                    state.emit(index, 'card_display_contract', {
                        mode: 'single',
                        visible_product_ids:
                            request.mode === 'malformed_contract'
                                ? [999]
                                : [55],
                        max_cards: 1,
                        reason: 'recommendation'
                    });
                    state.emit(index, 'products', {
                        products: [{
                            id: 55,
                            name: 'SHOULD_NOT_RENDER',
                            image_url: '/static/images/products/'
                                + 'tmall_v3_746513552108.png'
                        }]
                    });
                    state.emit(index, 'message', {
                        content: 'SHOULD_NOT_PERSIST',
                        done: false
                    });
                    if (request.mode === 'malformed_contract') {
                        state.emit(index, 'end', {
                            conversation_version: 1
                        });
                    }
                    state.close(index);
                } else if (
                    request.mode === 'contradictory_status'
                    || request.mode === 'foreign_winner'
                ) {
                    const comparison = {
                        status: 'winner',
                        references: [
                            {
                                ordinal: 1,
                                image_id: 'image-a',
                                product_id: 53
                            },
                            {
                                ordinal: 2,
                                image_id: 'image-b',
                                product_id: 55
                            }
                        ],
                        winner_reference: {
                            ordinal: 2,
                            image_id: 'image-b',
                            product_id: (
                                request.mode === 'foreign_winner'
                                    ? 999
                                    : 55
                            )
                        },
                        tie_reason: null,
                        comparison_dimensions: ['price'],
                        evidence_refs: ['price:53', 'price:55'],
                        evaluated_price_facts: [
                            {
                                reference: {
                                    ordinal: 1,
                                    image_id: 'image-a',
                                    product_id: 53
                                },
                                state: 'known',
                                value: '125',
                                source_refs: ['price:53']
                            },
                            {
                                reference: {
                                    ordinal: 2,
                                    image_id: 'image-b',
                                    product_id: 55
                                },
                                state: 'known',
                                value: '88.11',
                                source_refs: ['price:55']
                            }
                        ]
                    };
                    state.emit(index, 'image_observation', {
                        observation: {
                            image_id: 'image-a',
                            confirmed_product_id: 53
                        }
                    });
                    state.emit(index, 'image_observation', {
                        observation: {
                            image_id: 'image-b',
                            confirmed_product_id: 55
                        }
                    });
                    state.emit(index, 'intent', {
                        intent: 'image_compare',
                        entities: {},
                        guide: true
                    });
                    state.emit(index, 'decision_process', {
                        ordered_product_ids: [53, 55],
                        winner_status: 'winner',
                        comparison_data: comparison,
                        decision_process: {
                            steps: [{
                                data: {
                                    winner_status: 'winner',
                                    products: 2,
                                    outcome: comparison
                                }
                            }],
                            final_recommendation: null
                        }
                    });
                    const answerStatus = (
                        request.mode === 'contradictory_status'
                            ? 'tie'
                            : 'winner'
                    );
                    state.emit(index, 'answer_contract', {
                        answer_contract: {
                            product_count: 2,
                            winner_status: answerStatus,
                            has_unknown_skin: true
                        },
                        product_count: 2,
                        winner_status: answerStatus,
                        has_unknown_skin: true
                    });
                    state.emit(index, 'card_display_contract', {
                        mode: 'comparison',
                        visible_product_ids: [53, 55],
                        max_cards: 2,
                        reason: 'comparison'
                    });
                    state.emit(index, 'products', {
                        products: [
                            {
                                id: 53,
                                product_id: 53,
                                name: 'SHOULD_NOT_RENDER',
                                image_url: '/static/images/products/'
                                    + 'tmall_v3_746513552108.png'
                            },
                            {
                                id: 55,
                                product_id: 55,
                                name: 'SHOULD_NOT_RENDER',
                                image_url: '/static/images/products/'
                                    + 'tmall_v3_746513552108.png'
                            }
                        ]
                    });
                    state.emit(index, 'message', {
                        content: 'SHOULD_NOT_PERSIST',
                        done: false
                    });
                    state.emit(index, 'end', {
                        conversation_version: 1
                    });
                    state.close(index);
                } else if (
                    request.mode === 'malformed_utf8_after_end'
                    || request.mode === 'trailing_bytes_after_end'
                ) {
                    state.emit(index, 'intent', {
                        intent: 'clarify',
                        entities: {},
                        guide: true
                    });
                    state.emit(index, 'message', {
                        content: 'SHOULD_NOT_PERSIST',
                        done: false
                    });
                    state.emit(index, 'end', {
                        conversation_version: 1
                    });
                    if (request.mode === 'malformed_utf8_after_end') {
                        state.emitBytes(index, [0xc3]);
                    } else {
                        state.emitBytes(
                            index,
                            Array.from(encoder.encode('trailing'))
                        );
                    }
                    state.close(index);
                } else if (request.mode === 'stage') {
                    state.emit(index, 'stage', {
                        stage: 'state',
                        message: '正在读取真实会话状态'
                    });
                }
            },
            cancel() {
                request.cancelled = true;
            }
        });
        return new Response(stream, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' }
        });
    };
})();
"""
        .replace("__MODE__", json.dumps(mode))
        .replace("__BUNDLE_ID__", json.dumps(MOCK_BUNDLE_ID))
        .replace("__BUNDLE_VERSION__", str(MOCK_BUNDLE_VERSION))
        .replace("__OWNER_TOKEN__", json.dumps(MOCK_OWNER_TOKEN))
    )


def _new_page(browser: Browser, url: str, mode: str):
    context = browser.new_context()
    context.route("https://unpkg.com/**", lambda route: route.abort())
    page = context.new_page()
    page_errors: list[str] = []
    parse_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: parse_errors.append(message.text)
        if "SSE JSON parse failed" in message.text
        else None,
    )
    page.add_init_script(script=_stream_script(mode))
    page.goto(url, wait_until="networkidle")
    expect(
        page.locator("#runtimeHeaderSubtitle")
    ).to_have_text(
        "肤质咨询 · 单图识别/适配 · 2–4 图比较 · 购买建议"
    )
    page_source = page.content()
    visible_text = page.locator("body").inner_text()
    for prohibited in PROHIBITED_IMAGE_CAPABILITY_COPY:
        assert prohibited not in page_source
        assert prohibited not in visible_text
    return context, page, page_errors, parse_errors


def _assert_no_script_errors(
    page_errors: list[str],
    parse_errors: list[str],
) -> None:
    assert not page_errors, page_errors
    assert not parse_errors, parse_errors


def _send(page: Page, text: str) -> None:
    page.fill("#chatInput", text)
    page.click("#sendBtn")


def _run_error_scenario(browser: Browser, url: str) -> None:
    context, page, page_errors, parse_errors = _new_page(
        browser,
        url,
        "error",
    )
    try:
        _send(page, "触发错误")
        expect(page.locator("body")).to_contain_text(
            "推荐暂时不可用，请稍后重试。",
            timeout=5000,
        )
        page.wait_for_function("activeChatRequests.size === 0")
        request = page.evaluate(
            """() => {
                const request = window.__guideAdversarial.requests[0];
                return {
                    signalAttached: request?.signalAttached,
                    aborted: request?.aborted
                };
            }"""
        )
        assert request == {
            "signalAttached": True,
            "aborted": False,
        }
        _assert_no_script_errors(page_errors, parse_errors)
    finally:
        context.close()


def _run_terminal_failure_scenario(
    browser: Browser,
    url: str,
    mode: str,
) -> None:
    context, page, page_errors, parse_errors = _new_page(
        browser,
        url,
        mode,
    )
    try:
        _send(page, f"terminal failure {mode}")
        page.wait_for_function(
            "activeChatRequests.size === 0",
            timeout=5000,
        )
        expected = {
            "missing_end": "GUIDE_STREAM_INCOMPLETE",
            "malformed_contract": "GUIDE_RESPONSE_CONTRACT_INVALID",
            "contradictory_status": "GUIDE_RESPONSE_CONTRACT_INVALID",
            "foreign_winner": "GUIDE_RESPONSE_CONTRACT_INVALID",
            "malformed_utf8_after_end": "GUIDE_STREAM_INVALID_UTF8",
            "trailing_bytes_after_end": "GUIDE_STREAM_INCOMPLETE",
        }[mode]
        expect(page.locator("body")).to_contain_text(
            expected,
            timeout=5000,
        )
        assert page.locator(".recommendation-panel").count() == 0
        assert page.locator(".message-feedback").count() == 0
        body_text = page.locator("body").inner_text()
        assert "SHOULD_NOT_RENDER" not in body_text
        assert "SHOULD_NOT_PERSIST" not in body_text
        stored_products = page.evaluate(
            """() => JSON.parse(
                localStorage.getItem('lumi_recent_products_v2') || '[]'
            )"""
        )
        assert stored_products == []
        versions = page.evaluate(
            """() => JSON.parse(
                localStorage.getItem(
                    'lumi_conversation_versions_v1'
                ) || '{}'
            )"""
        )
        assert versions == {}
        _assert_no_script_errors(page_errors, parse_errors)
    finally:
        context.close()


def _run_abort_and_late_chunk_scenario(
    browser: Browser,
    url: str,
    evidence_dir: Path | None = None,
) -> None:
    context, page, page_errors, parse_errors = _new_page(
        browser,
        url,
        "delayed",
    )
    try:
        first_session = page.evaluate("getSessionId()")
        _send(page, "延迟回答")
        page.wait_for_function(
            """sessionId => (
                window.__guideAdversarial.requests.length === 1
                && activeChatRequests.has(sessionId)
            )""",
            arg=first_session,
        )

        second_session = page.evaluate(
            """() => {
                createFreshSession();
                return getSessionId();
            }"""
        )
        assert second_session != first_session
        page.wait_for_function(
            "window.__guideAdversarial.requests[0].aborted === true"
        )
        switch_state = page.evaluate(
            """() => ({
                signalAttached:
                    window.__guideAdversarial.requests[0].signalAttached,
                requestAborted:
                    window.__guideAdversarial.requests[0].aborted,
                activeRequestCount: activeChatRequests.size,
                versions: JSON.parse(
                    localStorage.getItem(
                        'lumi_conversation_versions_v1'
                    ) || '{}'
                )
            })"""
        )
        _write_evidence(
            page,
            evidence_dir,
            "session-switch",
            {
                "scenario": "session_switch",
                "session_ids": {
                    "original": first_session,
                    "current": second_session,
                },
                "abort": {
                    "signal_attached": switch_state["signalAttached"],
                    "request_aborted": switch_state["requestAborted"],
                    "active_request_count": switch_state[
                        "activeRequestCount"
                    ],
                },
                "versions": switch_state["versions"],
            },
        )

        released = page.evaluate(
            """() => {
                const state = window.__guideAdversarial;
                const scenarioSent = state.emit(
                    0,
                    'scenario_evidence',
                    {
                        records: [{
                            product_id: 55,
                            field: 'spf_pa',
                            state: 'known',
                            value: 'LATE_SCENARIO_EVIDENCE'
                        }]
                    }
                );
                const reviewSent = state.emit(
                    0,
                    'review_evidence',
                    {
                        approved_source_count: 0,
                        results: [{
                            product_id: 55,
                            evidence: [],
                            verified_absence: {
                                kind: 'verified_absence'
                            }
                        }],
                        summaries: []
                    }
                );
                const pitfallsSent = state.emit(0, 'pitfalls', {
                    pitfalls: [{
                        product_id: 55,
                        severity: 'medium',
                        title: 'LATE_PITFALL',
                        description: 'LATE_PITFALL_DESCRIPTION',
                        evidence_refs: [
                            'pitfall_evidence:canonical:55:late'
                        ]
                    }]
                });
                const messageSent = state.emit(0, 'message', {
                    content: 'FROM_ORIGINAL_SESSION',
                    done: false
                });
                const endSent = state.emit(0, 'end', {
                    conversation_version: 99
                });
                const closed = state.close(0);
                return {
                    scenarioSent,
                    reviewSent,
                    pitfallsSent,
                    messageSent,
                    endSent,
                    closed
                };
            }"""
        )
        assert released == {
            "scenarioSent": True,
            "reviewSent": True,
            "pitfallsSent": True,
            "messageSent": True,
            "endSent": True,
            "closed": True,
        }
        page.wait_for_function("activeChatRequests.size === 0")

        body_text = page.locator("body").inner_text()
        assert "FROM_ORIGINAL_SESSION" not in body_text
        assert "LATE_SCENARIO_EVIDENCE" not in body_text
        assert "LATE_PITFALL" not in body_text
        assert "场景证据" not in body_text
        assert "评论证据" not in body_text
        dom_absence = {
            "late_message": "FROM_ORIGINAL_SESSION" not in body_text,
            "late_scenario_evidence": (
                "LATE_SCENARIO_EVIDENCE" not in body_text
            ),
            "late_pitfall": "LATE_PITFALL" not in body_text,
            "scenario_panel": "场景证据" not in body_text,
            "review_panel": "评论证据" not in body_text,
        }
        versions = page.evaluate(
            """() => JSON.parse(
                localStorage.getItem(
                    'lumi_conversation_versions_v1'
                ) || '{}'
            )"""
        )
        assert first_session not in versions
        assert second_session not in versions
        _write_evidence(
            page,
            evidence_dir,
            "late-event",
            {
                "scenario": "late_event_isolation",
                "session_ids": {
                    "original": first_session,
                    "current": second_session,
                },
                "abort": {
                    "request_aborted": page.evaluate(
                        """() => (
                            window.__guideAdversarial.requests[0].aborted
                        )"""
                    ),
                    "active_request_count": page.evaluate(
                        "() => activeChatRequests.size"
                    ),
                },
                "late_emit": released,
                "dom_absence": dom_absence,
                "versions": versions,
            },
        )
        _assert_no_script_errors(page_errors, parse_errors)
    finally:
        context.close()


def _run_current_session_reactivation_scenario(
    browser: Browser,
    url: str,
    evidence_dir: Path | None = None,
) -> None:
    context, page, page_errors, parse_errors = _new_page(
        browser,
        url,
        "delayed",
    )
    try:
        session_id = page.evaluate("getSessionId()")
        _send(page, "当前会话点击测试")
        page.wait_for_function(
            """sessionId => (
                window.__guideAdversarial.requests.length === 1
                && activeChatRequests.has(sessionId)
                && activeChatRequests.get(sessionId).typingDiv.isConnected
            )""",
            arg=session_id,
        )
        before = page.evaluate(
            """sessionId => {
                const request = activeChatRequests.get(sessionId);
                return {
                    html: chatMessages.innerHTML,
                    typingConnected: request?.typingDiv?.isConnected,
                    aborted: request?.controller?.signal?.aborted,
                    activeHistoryItems: document.querySelectorAll(
                        '.list-item.active'
                    ).length
                };
            }""",
            arg=session_id,
        )
        assert before["typingConnected"] is True
        assert before["aborted"] is False
        assert before["activeHistoryItems"] == 1

        page.locator(".list-item.active").click()
        after = page.evaluate(
            """sessionId => {
                const request = activeChatRequests.get(sessionId);
                return {
                    html: chatMessages.innerHTML,
                    typingConnected: request?.typingDiv?.isConnected,
                    aborted: request?.controller?.signal?.aborted
                };
            }""",
            arg=session_id,
        )
        assert after == {
            "html": before["html"],
            "typingConnected": True,
            "aborted": False,
        }

        released = page.evaluate(
            """() => {
                const state = window.__guideAdversarial;
                const intentSent = state.emit(0, 'intent', {
                    intent: 'clarify',
                    entities: {},
                    guide: true
                });
                const messageSent = state.emit(0, 'message', {
                    content: 'CURRENT_SESSION_RESPONSE',
                    done: false
                });
                const endSent = state.emit(0, 'end', {
                    conversation_version: 1
                });
                const closed = state.close(0);
                return { intentSent, messageSent, endSent, closed };
            }"""
        )
        assert released == {
            "intentSent": True,
            "messageSent": True,
            "endSent": True,
            "closed": True,
        }
        expect(page.locator("body")).to_contain_text(
            "CURRENT_SESSION_RESPONSE",
            timeout=5000,
        )
        page.wait_for_function("activeChatRequests.size === 0")
        versions = page.evaluate(
            """() => JSON.parse(
                localStorage.getItem(
                    'lumi_conversation_versions_v1'
                ) || '{}'
            )"""
        )
        assert versions[session_id] == 1
        final_body_text = page.locator("body").inner_text()
        _write_evidence(
            page,
            evidence_dir,
            "current-session-reactivation",
            {
                "scenario": "current_session_reactivation",
                "session_ids": {
                    "original": session_id,
                    "current": page.evaluate("getSessionId()"),
                },
                "abort": {
                    "before_click": before["aborted"],
                    "after_click": after["aborted"],
                },
                "late_emit": released,
                "dom_absence": {
                    "typing_indicator": page.locator(
                        ".message-wrapper.ai.typing"
                    ).count()
                    == 0,
                    "foreign_session_message": (
                        "FROM_ORIGINAL_SESSION" not in final_body_text
                    ),
                },
                "reactivation": {
                    "dom_preserved": after["html"] == before["html"],
                    "response_present": (
                        "CURRENT_SESSION_RESPONSE" in final_body_text
                    ),
                },
                "versions": versions,
            },
        )
        _assert_no_script_errors(page_errors, parse_errors)
    finally:
        context.close()


def _run_real_stage_scenario(browser: Browser, url: str) -> None:
    context, page, page_errors, parse_errors = _new_page(
        browser,
        url,
        "stage",
    )
    try:
        session_id = page.evaluate("getSessionId()")
        _send(page, "真实阶段测试")
        page.wait_for_function(
            """sessionId => (
                window.__guideAdversarial.requests.length === 1
                && activeChatRequests.has(sessionId)
            )""",
            arg=session_id,
        )
        expect(page.locator("body")).to_contain_text(
            "正在读取真实会话状态",
            timeout=5000,
        )
        visible_text = page.locator("body").inner_text()
        for fake_copy in (
            "正在调用 AI 工具链路",
            "补充知识库与避坑信息",
            "知识检索",
            "综合打分",
            "Agent 决策排序",
        ):
            assert fake_copy not in visible_text

        released = page.evaluate(
            """() => {
                const state = window.__guideAdversarial;
                const intentSent = state.emit(0, 'intent', {
                    intent: 'clarify',
                    entities: {},
                    guide: true
                });
                const messageSent = state.emit(0, 'message', {
                    content: '真实阶段完成',
                    done: false
                });
                const endSent = state.emit(0, 'end', {
                    conversation_version: 1
                });
                const closed = state.close(0);
                return { intentSent, messageSent, endSent, closed };
            }"""
        )
        assert released == {
            "intentSent": True,
            "messageSent": True,
            "endSent": True,
            "closed": True,
        }
        expect(page.locator("body")).to_contain_text(
            "真实阶段完成",
            timeout=5000,
        )
        page.wait_for_function("activeChatRequests.size === 0")
        version = page.evaluate(
            """sessionId => {
                const versions = JSON.parse(
                    localStorage.getItem(
                        'lumi_conversation_versions_v1'
                    ) || '{}'
                );
                return versions[sessionId];
            }""",
            arg=session_id,
        )
        assert version == 1
        _assert_no_script_errors(page_errors, parse_errors)
    finally:
        context.close()


def _run_multi_image_upload_ownership_scenario(
    browser: Browser,
    url: str,
    source_image: str,
    image_count: int,
) -> None:
    context, page, page_errors, parse_errors = _new_page(
        browser,
        url,
        "delayed",
    )
    try:
        page.set_input_files(
            "#imageInput",
            [source_image] * image_count,
        )
        expect(
            page.locator("#imagePreview .preview-item")
        ).to_have_count(image_count)
        session_id = page.evaluate("getSessionId()")
        page.fill("#chatInput", f"比较这 {image_count} 张图片")
        page.click("#sendBtn")
        page.wait_for_function(
            """sessionId => (
                window.__guideAdversarial.uploads.length === 1
                && activeChatRequests.has(sessionId)
            )""",
            arg=session_id,
        )
        expect(
            page.locator("#imagePreview .preview-item")
        ).to_have_count(0)

        evidence = page.evaluate(
            """() => ({
                uploadCount: window.__guideAdversarial.uploads.length,
                uploadImageCount:
                    window.__guideAdversarial.uploads[0]?.imageCount,
                signalAttached:
                    window.__guideAdversarial.uploads[0]?.signalAttached,
                aborted: window.__guideAdversarial.uploads[0]?.aborted,
                streamCount: window.__guideAdversarial.requests.length,
                deleteCount: window.__guideAdversarial.deletes.length,
                activeRequestCount: activeChatRequests.size,
                draftCount: uploadedImages.length,
                inputText: chatInput.value
            })"""
        )
        assert evidence == {
            "uploadCount": 1,
            "uploadImageCount": image_count,
            "signalAttached": True,
            "aborted": False,
            "streamCount": 0,
            "deleteCount": 0,
            "activeRequestCount": 1,
            "draftCount": 0,
            "inputText": "",
        }
        _assert_no_script_errors(page_errors, parse_errors)
    finally:
        context.close()


def _run_image_draft_switch_scenario(
    browser: Browser,
    url: str,
    source_image: str,
) -> None:
    context, page, page_errors, parse_errors = _new_page(
        browser,
        url,
        "delayed",
    )
    try:
        first_session = page.evaluate("getSessionId()")
        page.set_input_files("#imageInput", source_image)
        expect(
            page.locator("#imagePreview .preview-item")
        ).to_have_count(1)
        assert page.evaluate("imageDraftSessionId") == first_session

        second_session = page.evaluate(
            """() => {
                createFreshSession();
                return getSessionId();
            }"""
        )

        assert second_session != first_session
        expect(
            page.locator("#imagePreview .preview-item")
        ).to_have_count(0)
        draft = page.evaluate(
            """() => ({
                count: uploadedImages.length,
                owner: imageDraftSessionId
            })"""
        )
        assert draft == {"count": 0, "owner": None}
        _assert_no_script_errors(page_errors, parse_errors)
    finally:
        context.close()


def _start_delayed_image_upload(
    page: Page,
    source_image: str,
    text: str,
) -> str:
    session_id = page.evaluate("getSessionId()")
    page.set_input_files("#imageInput", source_image)
    expect(
        page.locator("#imagePreview .preview-item")
    ).to_have_count(1)
    page.fill("#chatInput", text)
    page.click("#sendBtn")
    page.wait_for_function(
        """sessionId => (
            window.__guideAdversarial.uploads.length === 1
            && activeChatRequests.has(sessionId)
        )""",
        arg=session_id,
    )
    upload = page.evaluate(
        """() => {
            const upload = window.__guideAdversarial.uploads[0];
            return {
                signalAttached: upload.signalAttached,
                aborted: upload.aborted
            };
        }"""
    )
    assert upload == {
        "signalAttached": True,
        "aborted": False,
    }
    return session_id


def _assert_late_upload_is_discarded(
    page: Page,
    original_session: str,
) -> None:
    assert page.evaluate(
        "() => window.__guideAdversarial.resolveUpload(0)"
    ) is True
    page.wait_for_function("activeChatRequests.size === 0")
    evidence = page.evaluate(
        """() => ({
            streamCount: window.__guideAdversarial.requests.length,
            deletes: window.__guideAdversarial.deletes,
            currentSession: getSessionId()
        })"""
    )
    assert evidence["streamCount"] == 0
    assert len(evidence["deletes"]) == 1
    assert evidence["deletes"][0] == {
        "url": f"/api/v1/chat/image-bundles/{MOCK_BUNDLE_ID}",
        "body": {
            "session_id": original_session,
            "version": MOCK_BUNDLE_VERSION,
            "owner_token": MOCK_OWNER_TOKEN,
        },
        "status": 204,
    }
    invalid_results = page.evaluate(
        """async credentials => {
            const invalidCases = [
                {
                    field: 'bundle_id',
                    bundleId: `bundle_${'c'.repeat(32)}`,
                    body: {
                        session_id: credentials.sessionId,
                        version: credentials.version,
                        owner_token: credentials.ownerToken
                    }
                },
                {
                    field: 'session_id',
                    bundleId: credentials.bundleId,
                    body: {
                        session_id: 'wrong-session',
                        version: credentials.version,
                        owner_token: credentials.ownerToken
                    }
                },
                {
                    field: 'version',
                    bundleId: credentials.bundleId,
                    body: {
                        session_id: credentials.sessionId,
                        version: credentials.version + 1,
                        owner_token: credentials.ownerToken
                    }
                },
                {
                    field: 'owner_token',
                    bundleId: credentials.bundleId,
                    body: {
                        session_id: credentials.sessionId,
                        version: credentials.version,
                        owner_token: `owner_${'c'.repeat(43)}`
                    }
                }
            ];
            const results = [];
            for (const invalidCase of invalidCases) {
                const response = await fetch(
                    `/api/v1/chat/image-bundles/${invalidCase.bundleId}`,
                    {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(invalidCase.body)
                    }
                );
                let payload = null;
                try {
                    payload = await response.json();
                } catch (error) {
                    payload = null;
                }
                results.push({
                    field: invalidCase.field,
                    status: response.status,
                    payload
                });
            }
            return results;
        }""",
        arg={
            "bundleId": MOCK_BUNDLE_ID,
            "sessionId": original_session,
            "version": MOCK_BUNDLE_VERSION,
            "ownerToken": MOCK_OWNER_TOKEN,
        },
    )
    assert invalid_results == [
        {
            "field": field,
            "status": 404,
            "payload": IMAGE_BUNDLE_UNAVAILABLE_DETAIL,
        }
        for field in (
            "bundle_id",
            "session_id",
            "version",
            "owner_token",
        )
    ], invalid_results
    assert "图片已安全接收" not in page.locator("body").inner_text()


def _run_cancel_inflight_upload_scenario(
    browser: Browser,
    url: str,
    source_image: str,
) -> None:
    context, page, page_errors, parse_errors = _new_page(
        browser,
        url,
        "delayed",
    )
    try:
        session_id = _start_delayed_image_upload(
            page,
            source_image,
            "取消上传测试",
        )
        expect(page.locator("#closeSearchMode")).to_be_visible()
        page.click("#closeSearchMode")
        page.wait_for_function(
            "window.__guideAdversarial.uploads[0].aborted === true"
        )
        _assert_late_upload_is_discarded(page, session_id)
        assert page.evaluate("getSessionId()") == session_id
        _assert_no_script_errors(page_errors, parse_errors)
    finally:
        context.close()


def _run_switch_during_upload_scenario(
    browser: Browser,
    url: str,
    source_image: str,
) -> None:
    context, page, page_errors, parse_errors = _new_page(
        browser,
        url,
        "delayed",
    )
    try:
        first_session = _start_delayed_image_upload(
            page,
            source_image,
            "切换会话测试",
        )
        second_session = page.evaluate(
            """() => {
                createFreshSession();
                return getSessionId();
            }"""
        )
        assert second_session != first_session
        page.wait_for_function(
            "window.__guideAdversarial.uploads[0].aborted === true"
        )
        _assert_late_upload_is_discarded(page, first_session)
        assert page.evaluate("getSessionId()") == second_session
        _assert_no_script_errors(page_errors, parse_errors)
    finally:
        context.close()


def main() -> int:
    args = _parse_args()
    source_image = str(
        (
            Path(__file__).resolve().parents[2]
            / "app"
            / "static"
            / "images"
            / "products"
            / "tmall_v3_746513552108.png"
        )
    )

    with sync_playwright() as playwright:
        executable_path = os.environ.get(
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
        )
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path or None,
        )
        try:
            _run_error_scenario(browser, args.url)
            _run_terminal_failure_scenario(
                browser,
                args.url,
                "missing_end",
            )
            _run_terminal_failure_scenario(
                browser,
                args.url,
                "malformed_contract",
            )
            _run_terminal_failure_scenario(
                browser,
                args.url,
                "contradictory_status",
            )
            _run_terminal_failure_scenario(
                browser,
                args.url,
                "foreign_winner",
            )
            _run_terminal_failure_scenario(
                browser,
                args.url,
                "malformed_utf8_after_end",
            )
            _run_terminal_failure_scenario(
                browser,
                args.url,
                "trailing_bytes_after_end",
            )
            _run_abort_and_late_chunk_scenario(
                browser,
                args.url,
                args.evidence_dir,
            )
            _run_current_session_reactivation_scenario(
                browser,
                args.url,
                args.evidence_dir,
            )
            _run_real_stage_scenario(browser, args.url)
            for image_count in (3, 4):
                _run_multi_image_upload_ownership_scenario(
                    browser,
                    args.url,
                    source_image,
                    image_count,
                )
            _run_image_draft_switch_scenario(
                browser,
                args.url,
                source_image,
            )
            _run_cancel_inflight_upload_scenario(
                browser,
                args.url,
                source_image,
            )
            _run_switch_during_upload_scenario(
                browser,
                args.url,
                source_image,
            )
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
