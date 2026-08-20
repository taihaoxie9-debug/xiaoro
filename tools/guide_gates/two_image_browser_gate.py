from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from tools.guide_gates.runtime_browser_smoke import (
    _CAPTURE_GUIDE_SSE,
    _wait_for_turn,
)


EXPECTED_INDEX_SHA256 = (
    "f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340"
)
_CAPTURE_FEEDBACK = r"""
(() => {
    const nativeFetch = window.fetch.bind(window);
    const state = {
        requests: [],
        responses: [],
        errors: []
    };
    window.__twoImageFeedback = state;
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
            state.errors.push(String(error));
        }
        state.requests.push({ url, body });
        const response = await nativeFetch(input, options);
        try {
            state.responses.push({
                status: response.status,
                payload: await response.clone().json()
            });
        } catch (error) {
            state.errors.push(String(error));
        }
        return response;
    };
})()
"""


def _feedback_request_matches(request, event_type: str) -> bool:
    if "/feedback" not in request.url or request.method != "POST":
        return False
    body = request.post_data_json
    return (
        isinstance(body, dict)
        and isinstance(body.get("payload"), dict)
        and body["payload"].get("event_type") == event_type
    )


def _serve_offline_icons(route) -> None:
    route.fulfill(
        status=200,
        content_type="application/javascript",
        body="",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8784/chat",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=Path("/tmp/xiaoro-two-image-browser.png"),
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    first_image = (
        root
        / "app"
        / "static"
        / "images"
        / "products"
        / "taobao_v3_572910260362.png"
    )
    second_image = (
        root
        / "app"
        / "static"
        / "images"
        / "products"
        / "tmall_v3_746513552108.png"
    )
    assert first_image.is_file()
    assert second_image.is_file()

    with sync_playwright() as playwright:
        executable_path = os.environ.get(
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
        )
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path or None,
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}
        )
        page = context.new_page()
        page.route("https://unpkg.com/**", _serve_offline_icons)
        page.add_init_script(_CAPTURE_GUIDE_SSE)
        page.add_init_script(_CAPTURE_FEEDBACK)
        page_errors: list[str] = []
        console_errors: list[str] = []
        failed_images: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "response",
            lambda response: failed_images.append(response.url)
            if "/static/images/products/" in response.url
            and response.status != 200
            else None,
        )
        try:
            page.goto(args.url, wait_until="networkidle")
            expect(page.locator("#runtimeHeaderSubtitle")).to_have_text(
                "肤质咨询 · 单图识别/适配 · 2–4 图比较 · 购买建议"
            )
            page.set_input_files(
                "#imageInput",
                [str(first_image), str(second_image)],
            )
            expect(
                page.locator("#imagePreview .preview-item")
            ).to_have_count(2)
            page.fill("#chatInput", "比较这两张图")
            page.click("#sendBtn")
            _wait_for_turn(page, 1)

            evidence = page.evaluate(
                """() => {
                    const events = window.__guideSseEvidence[0];
                    const observations = events.filter(
                        item => item.event === 'image_observation'
                    ).map(item => item.data.observation);
                    const intent = events.find(
                        item => item.event === 'intent'
                    )?.data?.intent;
                    const decision = events.find(
                        item => item.event === 'decision_process'
                    )?.data;
                    const answer = events.find(
                        item => item.event === 'answer_contract'
                    )?.data?.answer_contract;
                    const contract = events.find(
                        item => item.event === 'card_display_contract'
                    )?.data;
                    const feedbackTarget = events.find(
                        item => item.event === 'feedback_target'
                    )?.data;
                    const end = events.find(
                        item => item.event === 'end'
                    )?.data;
                    const products = events.find(
                        item => item.event === 'products'
                    )?.data?.products || [];
                    return {
                        names: events.map(item => item.event),
                        observations,
                        intent,
                        decision,
                        answer,
                        contract,
                        feedbackTarget,
                        end,
                        products
                    };
                }"""
            )
            observations = evidence["observations"]
            assert len(observations) == 2
            assert [
                item["confirmed_product_id"] for item in observations
            ] == [53, 55]
            assert all(
                item["model_name"].startswith("OpenCLIP:ViT-B-32")
                for item in observations
            )
            assert [
                item["index_sha256"] for item in observations
            ] == [EXPECTED_INDEX_SHA256, EXPECTED_INDEX_SHA256]
            assert evidence["intent"] == "image_compare"
            assert evidence["decision"]["ordered_product_ids"] == [53, 55]
            comparison = evidence["decision"]["comparison_data"]
            assert comparison["status"] == "winner"
            assert comparison["winner_reference"]["ordinal"] == 2
            assert evidence["answer"] == {
                "product_count": 2,
                "winner_status": "winner",
                "has_unknown_skin": True,
            }
            assert evidence["contract"] == {
                "mode": "comparison",
                "visible_product_ids": [53, 55],
                "max_cards": 2,
                "reason": "comparison",
            }
            products = evidence["products"]
            assert [item["id"] for item in products] == [53, 55]
            assert [item["matched_efficacies"] for item in products] == [
                [],
                [],
            ]
            assert [item["suitable_skin"] for item in products] == [
                "肤质数据缺失",
                "肤质数据缺失",
            ]
            assert evidence["names"].count("image_observation") == 2
            assert evidence["names"].count("feedback_target") == 1
            assert evidence["names"][-1] == "end"
            feedback_target = evidence["feedbackTarget"]
            assert feedback_target == {
                "conversation_version": evidence["end"][
                    "conversation_version"
                ],
                "displayed_product_ids": [53, 55],
                "profile_version": None,
            }

            answer_wrapper = page.locator(
                ".message-wrapper.ai"
            ).filter(has=page.locator(".message-markdown")).last
            expect(answer_wrapper.locator(".message-markdown")).to_contain_text(
                "第二张对应商品价格更低"
            )
            assert answer_wrapper.locator(
                ":scope > .message-bubble .message-markdown"
            ).count() == 1
            feedback = answer_wrapper.locator(
                ":scope > .message-feedback"
            )
            assert feedback.count() == 1
            assert page.locator(".message-feedback").count() == 1
            buttons = feedback.locator(":scope > .feedback-btn")
            assert buttons.count() == 2
            button_contracts = buttons.evaluate_all(
                """nodes => nodes.map(node => ({
                    type: node.dataset.type,
                    text: node.textContent.trim()
                }))"""
            )
            assert button_contracts == [
                {"type": "thumbs_up", "text": "有帮助"},
                {"type": "thumbs_down", "text": "无帮助"},
            ]

            cards = page.locator(
                ".recommendation-panel"
            ).last.locator(".recommendation-card")
            assert cards.count() == 2
            expect(cards.nth(0)).to_contain_text("理肤泉特护清盈防晒乳")
            expect(cards.nth(1)).to_contain_text("清透防晒乳")
            assert page.locator(
                "[data-image-model-version][data-image-index-version]"
            ).count() == 2
            comparison_control = page.locator(
                "[data-compare-product-ids]"
            ).last
            expect(comparison_control).to_have_text("记录这组对比")
            assert comparison_control.get_attribute(
                "data-compare-product-ids"
            ) == "53,55"
            assert comparison_control.get_attribute(
                "data-feedback-version"
            ) == str(feedback_target["conversation_version"])
            comparison_target = comparison_control.evaluate(
                """button => {
                    const target = feedbackTargetForElement(button);
                    return {
                        conversation_version: target?.conversation_version,
                        displayed_product_ids:
                            target?.displayed_product_ids || [],
                        profile_version: target?.profile_version ?? null
                    };
                }"""
            )
            assert comparison_target == {
                "conversation_version": feedback_target[
                    "conversation_version"
                ],
                "displayed_product_ids": [53, 55],
                "profile_version": feedback_target.get(
                    "profile_version"
                ),
            }
            with page.expect_request(
                lambda request: _feedback_request_matches(request, "compare")
            ) as compare_request_info, page.expect_response(
                lambda response: _feedback_request_matches(response.request, "compare")
            ) as compare_response_info:
                comparison_control.click()
            compare_request = compare_request_info.value
            compare_response = compare_response_info.value
            assert compare_request.method == "POST"
            assert compare_response.status == 200
            page.wait_for_function(
                "window.__twoImageFeedback.responses.length === 1"
            )
            comparison_feedback = page.evaluate(
                "() => window.__twoImageFeedback"
            )
            assert comparison_feedback["errors"] == []
            assert len(comparison_feedback["requests"]) == 1
            assert len(comparison_feedback["responses"]) == 1
            comparison_body = compare_request.post_data_json
            assert (
                comparison_feedback["requests"][0]["body"]
                == comparison_body
            )
            assert set(comparison_body) == {
                "conversation_version",
                "profile_version",
                "idempotency_key",
                "payload",
            }
            assert comparison_body["conversation_version"] == (
                feedback_target["conversation_version"]
            )
            assert comparison_body["profile_version"] == (
                feedback_target.get("profile_version")
            )
            assert comparison_body["payload"] == {
                "event_type": "compare",
                "product_ids": [53, 55],
            }
            assert "owner" not in comparison_body
            assert "session_id" not in comparison_body
            comparison_response = comparison_feedback["responses"][0]
            assert comparison_response["status"] == 200
            assert comparison_response["payload"]["event_type"] == "compare"
            compare_receipt = compare_response.json()
            assert compare_receipt["event_type"] == "compare"
            assert comparison_response["payload"] == compare_receipt

            thumbs_down = feedback.locator(
                '[data-type="thumbs_down"]'
            )
            thumbs_up = feedback.locator('[data-type="thumbs_up"]')
            thumbs_down.click()
            assert "active" in (
                thumbs_down.get_attribute("class") or ""
            ).split()
            expect(page.locator("#feedbackModal")).to_be_visible()
            expect(
                page.locator("#feedbackModal .feedback-modal-title")
            ).to_contain_text("谢谢你的反馈")
            negative_target = thumbs_down.evaluate(
                """button => {
                    const target = feedbackTargetForElement(button);
                    return {
                        conversation_version: target?.conversation_version,
                        displayed_product_ids:
                            target?.displayed_product_ids || [],
                        profile_version: target?.profile_version ?? null
                    };
                }"""
            )
            assert negative_target == comparison_target
            assert negative_target == feedback_target
            assert negative_target["displayed_product_ids"] == [53, 55]
            page.locator("#feedbackText").fill("没有帮助")
            with page.expect_request(
                lambda request: _feedback_request_matches(request, "negative_feedback")
            ) as negative_request_info, page.expect_response(
                lambda response: _feedback_request_matches(response.request, "negative_feedback")
            ) as negative_response_info:
                page.locator("#feedbackSubmit").click()
            negative_request = negative_request_info.value
            negative_response = negative_response_info.value
            assert negative_request.method == "POST"
            assert negative_response.status == 200
            page.wait_for_function(
                "window.__twoImageFeedback.responses.length === 2"
            )
            final_feedback = page.evaluate(
                "() => window.__twoImageFeedback"
            )
            assert final_feedback["errors"] == []
            assert len(final_feedback["requests"]) == 2
            assert len(final_feedback["responses"]) == 2
            negative_body = negative_request.post_data_json
            assert final_feedback["requests"][0]["body"] == comparison_body
            assert final_feedback["requests"][1]["body"] == negative_body
            assert final_feedback["responses"][0] == comparison_response
            assert set(negative_body) == {
                "conversation_version",
                "profile_version",
                "idempotency_key",
                "payload",
            }
            assert negative_body["conversation_version"] == (
                evidence["end"]["conversation_version"]
            )
            assert negative_body["conversation_version"] == (
                feedback_target["conversation_version"]
            )
            assert negative_body["profile_version"] == (
                feedback_target.get("profile_version")
            )
            assert negative_body["profile_version"] is None
            assert negative_body["payload"] == {
                "event_type": "negative_feedback",
                "reason": "not_helpful",
            }
            assert not {
                "owner",
                "session_id",
                "displayed_product_ids",
            } & set(negative_body)
            assert final_feedback["responses"][1]["status"] == 200
            negative_receipt = negative_response.json()
            assert set(negative_receipt) == {
                "event_id",
                "event_type",
                "occurred_at",
            }
            assert negative_receipt["event_type"] == "negative_feedback"
            assert negative_receipt["event_id"].startswith(
                "feedback_event_"
            )
            assert negative_receipt["occurred_at"]
            assert final_feedback["responses"][1]["payload"] == (
                negative_receipt
            )
            expect(page.locator("#feedbackModal")).to_be_hidden()
            expect(thumbs_down).to_have_class(
                "feedback-btn thumbs-down active"
            )
            expect(thumbs_up).not_to_have_class(
                "feedback-btn thumbs-up active"
            )
            assert thumbs_down.is_disabled() is False
            assert thumbs_up.is_disabled() is False

            panel_feedback_counts = page.evaluate(
                """selectors => Object.fromEntries(
                    selectors.map(selector => [
                        selector,
                        Array.from(document.querySelectorAll(selector))
                            .reduce((count, panel) => {
                                const wrapper = panel.closest(
                                    '.message-wrapper.ai'
                                );
                                return count + (
                                    wrapper?.querySelectorAll(
                                        ':scope > .message-feedback'
                                    ).length || 0
                                );
                            }, 0)
                    ])
                )""",
                [
                    ".welcome-shell",
                    ".image-analysis-hint",
                    ".evidence-section",
                    ".recommendation-panel",
                    ".citations-section",
                ],
            )
            assert panel_feedback_counts == {
                ".welcome-shell": 0,
                ".image-analysis-hint": 0,
                ".evidence-section": 0,
                ".recommendation-panel": 0,
                ".citations-section": 0,
            }
            assert not page_errors, page_errors
            assert not console_errors, console_errors
            assert not failed_images, failed_images
            browser_storage = page.evaluate(
                """() => JSON.stringify({
                    local: { ...localStorage },
                    session: { ...sessionStorage }
                })"""
            )
            assert "owner_" not in browser_storage
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.screenshot), full_page=True)
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
