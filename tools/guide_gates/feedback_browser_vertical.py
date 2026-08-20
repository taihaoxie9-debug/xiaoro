from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


_CAPTURE_FEEDBACK = r"""
(() => {
    const nativeFetch = window.fetch.bind(window);
    window.__feedbackEvidence = {
        requests: [],
        responses: [],
        errors: []
    };
    window.fetch = async (input, options = {}) => {
        const url = typeof input === 'string'
            ? input
            : String(input?.url || input);
        if (!url.includes('/feedback')) {
            return nativeFetch(input, options);
        }
        let body = null;
        try {
            body = JSON.parse(options.body || '{}');
        } catch (error) {
            window.__feedbackEvidence.errors.push(String(error));
        }
        window.__feedbackEvidence.requests.push({ url, body });
        const response = await nativeFetch(input, options);
        response.clone().json().then(payload => {
            window.__feedbackEvidence.responses.push({
                status: response.status,
                payload
            });
        }).catch(error => {
            window.__feedbackEvidence.errors.push(String(error));
        });
        return response;
    };
})()
"""


def _wait_for_turn(page) -> None:
    page.wait_for_function(
        "activeChatRequests.size === 0",
        timeout=120_000,
    )
    expect(page.locator(".recommendation-card").first).to_be_visible(
        timeout=20_000
    )
    page.wait_for_function(
        """() => {
            const controls = document.querySelectorAll(
                '.message-feedback .feedback-btn'
            );
            return Boolean(feedbackTargetForElement(
                controls[controls.length - 1]
            ));
        }""",
        timeout=20_000,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8767/chat",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=Path("/tmp/xiaoro-feedback-browser.png"),
    )
    args = parser.parse_args()

    page_errors: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        owner_context = browser.new_context()
        owner_page = owner_context.new_page()
        owner_page.add_init_script(_CAPTURE_FEEDBACK)
        owner_page.on(
            "pageerror",
            lambda error: page_errors.append(str(error)),
        )
        owner_page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        owner_page.goto(args.url, wait_until="networkidle")
        owner_page.fill(
            "#chatInput",
            "500 元内敏感肌修护精华",
        )
        owner_page.click("#sendBtn")
        _wait_for_turn(owner_page)

        owner_session_id = owner_page.evaluate("getSessionId()")
        target = owner_page.evaluate(
            """() => {
                const controls = document.querySelectorAll(
                    '.message-feedback .feedback-btn'
                );
                const item = feedbackTargetForElement(
                    controls[controls.length - 1]
                );
                return {
                    conversation_version: item.conversation_version,
                    displayed_product_ids: [
                        ...item.displayed_product_ids
                    ],
                    profile_version: item.profile_version
                };
            }"""
        )
        assert target["displayed_product_ids"] == [91, 38]
        favorite = owner_page.locator(
            "[data-favorite-product-id]"
        ).first
        product_id = int(
            favorite.get_attribute("data-favorite-product-id")
        )

        favorite.click()
        owner_page.wait_for_function(
            "window.__feedbackEvidence.responses.length >= 1"
        )
        favorite.click()
        favorite.click()
        owner_page.wait_for_function(
            "window.__feedbackEvidence.responses.length >= 2"
        )
        replay_evidence = owner_page.evaluate(
            "() => window.__feedbackEvidence"
        )
        assert replay_evidence["errors"] == []
        requests = replay_evidence["requests"][:2]
        responses = replay_evidence["responses"][:2]
        assert requests[0]["body"]["payload"] == {
            "event_type": "favorite",
            "product_id": product_id,
        }
        assert requests[0]["body"]["idempotency_key"] == (
            requests[1]["body"]["idempotency_key"]
        )
        assert "owner" not in requests[0]["body"]
        assert "session_id" not in requests[0]["body"]
        assert responses[0]["status"] == 200
        assert responses[1]["status"] == 200
        assert responses[0]["payload"]["event_id"] == (
            responses[1]["payload"]["event_id"]
        )

        foreign_context = browser.new_context()
        foreign_page = foreign_context.new_page()
        foreign_page.goto(args.url, wait_until="networkidle")
        foreign = foreign_page.evaluate(
            """async ({ sessionId, target, productId }) => {
                const response = await fetch(
                    `/api/v1/chat/sessions/${
                        encodeURIComponent(sessionId)
                    }/feedback`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            conversation_version:
                                target.conversation_version,
                            profile_version: target.profile_version,
                            idempotency_key:
                                'foreign-browser-feedback-0001',
                            payload: {
                                event_type: 'click',
                                product_id: productId
                            }
                        })
                    }
                );
                return {
                    status: response.status,
                    payload: await response.json()
                };
            }""",
            {
                "sessionId": owner_session_id,
                "target": target,
                "productId": product_id,
            },
        )
        assert foreign["status"] == 404
        assert foreign["payload"]["detail"]["code"] == (
            "FEEDBACK_TARGET_UNAVAILABLE"
        )

        owner_page.evaluate(
            """({ productId }) => {
                const previousFetch = window.fetch;
                window.__lateFeedback = {
                    accepted: 0,
                    result: null
                };
                window.fetch = async (input, options = {}) => {
                    const url = typeof input === 'string'
                        ? input
                        : String(input?.url || input);
                    if (!url.includes('/feedback')) {
                        return previousFetch(input, options);
                    }
                    return new Promise(resolve => {
                        window.__resolveLateFeedback = () => resolve(
                            new Response(JSON.stringify({
                                event_id:
                                    'feedback_event_late0123456789abcdef',
                                event_type: 'click',
                                occurred_at:
                                    '2026-08-09T05:30:00Z'
                            }), {
                                status: 200,
                                headers: {
                                    'Content-Type': 'application/json'
                                }
                            })
                        );
                    });
                };
                const sessionId = getSessionId();
                const controls = document.querySelectorAll(
                    '.message-feedback .feedback-btn'
                );
                const target = feedbackTargetForElement(
                    controls[controls.length - 1]
                );
                submitTypedFeedback({
                    sessionId,
                    target,
                    eventType: 'click',
                    payload: { product_id: productId },
                    operationId: `late:${target.conversation_version}:${
                        productId
                    }`,
                    onAccepted() {
                        window.__lateFeedback.accepted += 1;
                    }
                }).then(result => {
                    window.__lateFeedback.result = result;
                });
            }""",
            {"productId": product_id},
        )
        owner_page.evaluate("createFreshSession()")
        owner_page.evaluate("window.__resolveLateFeedback()")
        owner_page.wait_for_function(
            "window.__lateFeedback.result !== null"
        )
        late = owner_page.evaluate(
            "() => window.__lateFeedback"
        )
        assert late["accepted"] == 0
        assert late["result"]["ignored"] is True
        assert owner_page.evaluate("getSessionId()") != owner_session_id

        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        owner_page.screenshot(path=args.screenshot, full_page=True)
        assert page_errors == []
        assert console_errors == []

        evidence = {
            "idempotency_key": requests[0]["body"][
                "idempotency_key"
            ],
            "replayed_event_id": responses[0]["payload"]["event_id"],
            "foreign_status": foreign["status"],
            "late_response_ignored": late["result"]["ignored"],
            "page_errors": page_errors,
            "console_errors": console_errors,
            "screenshot": str(args.screenshot),
        }
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
        foreign_context.close()
        owner_context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
