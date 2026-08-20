from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.retrieval.category_profiles import category_profile_for


CATEGORY_CASES = (
    ("skincare", "推荐日常保湿面霜"),
    ("suncare", "推荐通勤防晒"),
    ("base_makeup", "推荐持妆粉底液"),
    ("color_makeup", "推荐显白口红"),
    ("cleanser", "推荐温和卸妆油"),
    ("fragrance", "推荐木质调香水"),
)
_CAPTURE_SSE = r"""
(() => {
    window.__categorySse = [];
    window.__categorySseErrors = [];
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await nativeFetch(...args);
        const input = args[0];
        const url = typeof input === 'string' ? input : (input?.url || '');
        if (url.includes('/api/v1/chat/stream')) {
            response.clone().text().then(body => {
                const events = body.split(/\n\n+/).filter(Boolean).map(block => {
                    let event = 'message';
                    let payload = '';
                    for (const line of block.split('\n')) {
                        if (line.startsWith('event: ')) {
                            event = line.slice(7).trim();
                        } else if (line.startsWith('data: ')) {
                            payload += line.slice(6);
                        }
                    }
                    return { event, data: JSON.parse(payload) };
                });
                window.__categorySse.push(events);
            }).catch(error => {
                window.__categorySseErrors.push(String(error));
            });
        }
        return response;
    };
})()
"""
_ADVERSARIAL_SSE = r"""
(() => {
    const nativeFetch = window.fetch.bind(window);
    const encoder = new TextEncoder();
    const state = {
        requests: [],
        errors: [],
        emit(index, event, data) {
            const request = this.requests[index];
            if (!request || request.closed) return false;
            try {
                request.controller.enqueue(encoder.encode(
                    `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
                ));
                return true;
            } catch (error) {
                if (!request.aborted) this.errors.push(String(error));
                return false;
            }
        },
        close(index) {
            const request = this.requests[index];
            if (!request || request.closed) return false;
            request.closed = true;
            try {
                request.controller.close();
                return true;
            } catch (error) {
                if (!request.aborted) this.errors.push(String(error));
                return false;
            }
        }
    };
    window.__categoryAdversarial = state;
    window.fetch = async (input, options = {}) => {
        const url = typeof input === 'string'
            ? input
            : String(input?.url || input);
        if (!url.includes('/api/v1/chat/stream')) {
            return nativeFetch(input, options);
        }
        const request = {
            body: JSON.parse(options.body || '{}'),
            controller: null,
            aborted: false,
            closed: false
        };
        options.signal?.addEventListener('abort', () => {
            request.aborted = true;
        }, { once: true });
        state.requests.push(request);
        const stream = new ReadableStream({
            start(controller) {
                request.controller = controller;
            },
            cancel() {
                request.aborted = true;
            }
        });
        return new Response(stream, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' }
        });
    };
})()
"""


def _profile_by_product_id() -> dict[int, str]:
    canonical = REPO_ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    result: dict[int, str] = {}
    for product_id in reader.product_ids:
        category = reader.get(product_id).fields["category"]
        assert category.resolved_state == "known"
        assert isinstance(category.value, str)
        result[product_id] = category_profile_for(category.value).value
    return result


def _product_id_for_profile(
    profiles: dict[int, str],
    expected_profile: str,
) -> int:
    product_ids = sorted(
        product_id
        for product_id, profile in profiles.items()
        if profile == expected_profile
    )
    assert product_ids, expected_profile
    return product_ids[0]


def _new_errors() -> dict[str, list[str]]:
    return {
        "page_errors": [],
        "console_errors": [],
        "sse_errors": [],
        "unexpected_5xx": [],
        "failed_images": [],
        "cross_session_leakage": [],
        "late_event_pollution": [],
    }


def _attach_observers(page: Page, errors: dict[str, list[str]]) -> None:
    page.on("pageerror", lambda error: errors["page_errors"].append(str(error)))
    page.on(
        "console",
        lambda message: errors["console_errors"].append(message.text)
        if message.type == "error"
        else None,
    )
    page.on(
        "response",
        lambda response: errors["unexpected_5xx"].append(response.url)
        if response.status >= 500
        else (
            errors["failed_images"].append(response.url)
            if response.request.resource_type == "image"
            and response.status >= 400
            else None
        ),
    )
    page.on(
        "requestfailed",
        lambda request: errors["failed_images"].append(request.url)
        if request.resource_type == "image"
        else None,
    )


def _serve_offline_icons(route) -> None:
    route.fulfill(
        status=200,
        content_type="application/javascript",
        body="",
    )


def _wait_for_normal_turn(page: Page, count: int) -> None:
    page.wait_for_function("activeChatRequests.size === 0", timeout=120_000)
    page.wait_for_function(
        "count => window.__categorySse.length >= count",
        arg=count,
        timeout=120_000,
    )


def _normal_gate(
    *,
    browser,
    url: str,
    screenshot: Path,
) -> dict[str, Any]:
    errors = _new_errors()
    profiles = _profile_by_product_id()
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_init_script(_CAPTURE_SSE)
    evidence: list[dict[str, Any]] = []
    try:
        for index, (expected_profile, message) in enumerate(CATEGORY_CASES):
            page = context.new_page()
            _attach_observers(page, errors)
            page.route("https://unpkg.com/**", _serve_offline_icons)
            page.goto(url, wait_until="networkidle")
            page.fill("#chatInput", message)
            page.click("#sendBtn")
            _wait_for_normal_turn(page, 1)
            events = page.evaluate("() => window.__categorySse[0]")
            errors["sse_errors"].extend(
                page.evaluate("() => window.__categorySseErrors")
            )
            names = [item["event"] for item in events]
            assert names.count("start") == 1
            assert names.count("end") == 1
            assert names.count("error") == 0
            assert names[-1] == "end"
            intent = next(
                item["data"]
                for item in events
                if item["event"] == "intent"
            )
            assert intent["guide"] is True
            assert intent["category_profile"] == expected_profile
            products_data = next(
                item["data"]
                for item in events
                if item["event"] == "products"
            )
            products = products_data["products"]
            product_ids = [item["id"] for item in products]
            assert 1 <= len(product_ids) <= 3
            assert all(
                profiles[product_id] == expected_profile
                for product_id in product_ids
            )
            assert all(
                item["category_profile"] == expected_profile
                for item in products
            )
            assert all(
                item["category_facts"]
                and all(
                    fact["state"] == "unavailable"
                    and fact["value"] is None
                    for fact in item["category_facts"]
                )
                for item in products
            )
            contract = next(
                item["data"]
                for item in events
                if item["event"] == "card_display_contract"
            )
            assert contract["visible_product_ids"] == product_ids
            page.wait_for_selector(".recommendation-panel")
            panel = page.locator(".recommendation-panel").last
            dom_ids = panel.locator(".recommendation-card").evaluate_all(
                """cards => cards.map(card => Number(
                    card.getAttribute('data-feedback-product-id')
                ))"""
            )
            assert dom_ids == product_ids, {
                "profile": expected_profile,
                "backend": product_ids,
                "dom": dom_ids,
            }
            assert panel.locator(
                ".category-fact-state-unavailable"
            ).count() > 0
            evidence.append(
                {
                    "profile": expected_profile,
                    "product_ids": product_ids,
                    "dom_product_ids": dom_ids,
                }
            )
            if index == len(CATEGORY_CASES) - 1:
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot), full_page=True)
            page.close()
    finally:
        context.close()
    assert all(not values for values in errors.values()), errors
    return {"mode": "normal", "profiles": evidence, "errors": errors}


def _emit_adversarial_turn(
    page: Page,
    *,
    request_index: int,
    product_id: int,
    marker: str,
    expected_profile: str,
    product_profile: str,
    category_facts: list[dict[str, Any]],
    conversation_version: int = 1,
    feedback_target: dict[str, Any] | None = None,
) -> None:
    product = {
        "id": product_id,
        "product_id": product_id,
        "name": marker,
        "display_name": marker,
        "brand": "安全测试",
        "category": "香水" if product_profile == "fragrance" else "面霜",
        "category_profile": product_profile,
        "category_facts": category_facts,
        "price": 1,
        "image_url": "",
        "detail_url": "",
        "platform": "",
        "description": "安全测试",
        "efficacy_match": "not_applicable",
        "matched_efficacies": [],
        "suitable_skin": "待确认",
        "fact_warnings": [],
    }
    events = [
        ("start", {"session_id": "synthetic"}),
        (
            "intent",
            {
                "intent": "recommend",
                "entities": {},
                "scenario_intent": "recommend",
                "guide": True,
                "category_profile": expected_profile,
            },
        ),
        (
            "decision_process",
            {
                "ordered_product_ids": [product_id],
                "winner_status": "INSUFFICIENT_FOR_WINNER",
                "evidence_refs": [],
                "decision_process": {
                    "steps": [
                        {
                            "type": "decision",
                            "title": "安全测试",
                            "description": "安全测试",
                            "data": {
                                "winner_status": "INSUFFICIENT_FOR_WINNER",
                                "products": 1,
                            },
                        }
                    ],
                    "final_recommendation": None,
                },
            },
        ),
        (
            "answer_contract",
            {
                "answer_contract": {
                    "product_count": 1,
                    "winner_status": "INSUFFICIENT_FOR_WINNER",
                    "has_unknown_skin": False,
                },
                "product_count": 1,
                "winner_status": "INSUFFICIENT_FOR_WINNER",
                "has_unknown_skin": False,
            },
        ),
        (
            "card_display_contract",
            {
                "mode": "single",
                "visible_product_ids": [product_id],
                "max_cards": 1,
                "reason": "recommendation",
            },
        ),
        (
            "products",
            {"cards": [product], "products": [product]},
        ),
        ("message", {"content": marker, "done": False}),
        ("end", {"conversation_version": conversation_version}),
    ]
    if feedback_target is not None:
        events.insert(-1, ("feedback_target", feedback_target))
    page.evaluate(
        """payload => {
            for (const [event, data] of payload.events) {
                window.__categoryAdversarial.emit(
                    payload.requestIndex,
                    event,
                    data
                );
            }
            window.__categoryAdversarial.close(payload.requestIndex);
        }""",
        {"requestIndex": request_index, "events": events},
    )


def _adversarial_gate(
    *,
    browser,
    url: str,
    screenshot: Path,
) -> dict[str, Any]:
    errors = _new_errors()
    profiles = _profile_by_product_id()
    product_id = _product_id_for_profile(profiles, "fragrance")
    wrong_profile_product_id = _product_id_for_profile(
        profiles,
        "skincare",
    )
    assert profiles[product_id] == "fragrance"
    assert profiles[wrong_profile_product_id] == "skincare"
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_init_script(_ADVERSARIAL_SSE)
    page = context.new_page()
    _attach_observers(page, errors)
    try:
        page.route("https://unpkg.com/**", _serve_offline_icons)
        page.goto(url, wait_until="networkidle")
        page.fill(
            "#chatInput",
            '推荐香水 <img src=x onerror="globalThis.__categoryXss=5">',
        )
        page.click("#sendBtn")
        page.wait_for_function(
            "window.__categoryAdversarial.requests.length === 1"
        )
        _emit_adversarial_turn(
            page,
            request_index=0,
            product_id=product_id,
            marker="ADVERSARIAL_CATEGORY_EVENT",
            expected_profile="fragrance",
            product_profile="fragrance",
            category_facts=[
                {
                    "field_key": "sillage",
                    "label": (
                        '<img src=x '
                        'onerror="globalThis.__categoryXss=3">'
                    ),
                    "value": (
                        "<script>"
                        "globalThis.__categoryXss=4"
                        "</script>"
                    ),
                    "state": "known",
                },
                {
                    "field_key": "top_notes",
                    "label": "前调",
                    "value": None,
                    "state": "unavailable",
                },
            ],
        )
        page.wait_for_function("activeChatRequests.size === 0")
        assert page.evaluate(
            "() => globalThis.__categoryXss ?? null"
        ) is None
        assert page.locator(
            ".category-facts img, .category-facts script, .category-facts svg"
        ).count() == 0
        assert "<script>globalThis.__categoryXss=4</script>" in (
            page.locator(".category-facts").inner_text()
        )
        assert page.locator(
            ".category-fact-state-unavailable"
        ).count() == 1
        positive_panel = page.locator(".recommendation-panel").last
        assert positive_panel.locator(
            ".recommendation-card"
        ).get_attribute("data-feedback-product-id") == str(product_id)

        panel_count = page.locator(".recommendation-panel").count()
        state_before_invalid = page.evaluate(
            """() => {
                const sessionId = localStorage.getItem(
                    'lumi_current_session_id'
                );
                return {
                    version: getConversationVersion(sessionId),
                    feedbackTargets: localStorage.getItem(
                        "lumi_feedback_targets_v1"
                    )
                };
            }"""
        )
        assert state_before_invalid["version"] == 1
        page.fill("#chatInput", "推荐香水错画像负例")
        page.click("#sendBtn")
        page.wait_for_function(
            "window.__categoryAdversarial.requests.length === 2"
        )
        _emit_adversarial_turn(
            page,
            request_index=1,
            product_id=wrong_profile_product_id,
            marker="WRONG_PROFILE_CATEGORY_EVENT",
            expected_profile="fragrance",
            product_profile="skincare",
            category_facts=[
                {
                    "field_key": "efficacy",
                    "label": "功效",
                    "value": None,
                    "state": "unavailable",
                }
            ],
            conversation_version=state_before_invalid["version"] + 1,
            feedback_target={
                "conversation_version": (
                    state_before_invalid["version"] + 1
                ),
                "displayed_product_ids": [wrong_profile_product_id],
                "profile_version": None,
            },
        )
        page.wait_for_function("activeChatRequests.size === 0")
        assert page.locator(".recommendation-panel").count() == panel_count
        assert page.locator(
            (
                ".recommendation-card"
                f'[data-feedback-product-id="{wrong_profile_product_id}"]'
            )
        ).count() == 0
        state_after_invalid = page.evaluate(
            """() => {
                const sessionId = localStorage.getItem(
                    'lumi_current_session_id'
                );
                return {
                    version: getConversationVersion(sessionId),
                    feedbackTargets: localStorage.getItem(
                        "lumi_feedback_targets_v1"
                    )
                };
            }"""
        )
        assert state_after_invalid == state_before_invalid

        page.fill("#chatInput", "推荐香水合法恢复")
        page.click("#sendBtn")
        page.wait_for_function(
            "window.__categoryAdversarial.requests.length === 3"
        )
        recovery_request_version = page.evaluate(
            "() => window.__categoryAdversarial.requests[2]"
            ".body.conversation_version"
        )
        assert recovery_request_version == state_before_invalid["version"]
        _emit_adversarial_turn(
            page,
            request_index=2,
            product_id=product_id,
            marker="RECOVERED_CATEGORY_EVENT",
            expected_profile="fragrance",
            product_profile="fragrance",
            category_facts=[
                {
                    "field_key": "sillage",
                    "label": "扩香度",
                    "value": None,
                    "state": "unavailable",
                }
            ],
            conversation_version=state_before_invalid["version"] + 1,
            feedback_target={
                "conversation_version": (
                    state_before_invalid["version"] + 1
                ),
                "displayed_product_ids": [product_id],
                "profile_version": None,
            },
        )
        page.wait_for_function("activeChatRequests.size === 0")
        state_after_recovery = page.evaluate(
            """() => {
                const sessionId = localStorage.getItem(
                    'lumi_current_session_id'
                );
                return {
                    version: getConversationVersion(sessionId),
                    feedbackTargets: localStorage.getItem(
                        "lumi_feedback_targets_v1"
                    )
                };
            }"""
        )
        assert state_after_recovery["version"] == (
            state_before_invalid["version"] + 1
        )
        assert (
            state_after_recovery["feedbackTargets"]
            != state_before_invalid["feedbackTargets"]
        )
        panel_count = page.locator(".recommendation-panel").count()

        page.fill("#chatInput", "推荐香水非法画像负例")
        page.click("#sendBtn")
        page.wait_for_function(
            "window.__categoryAdversarial.requests.length === 4"
        )
        _emit_adversarial_turn(
            page,
            request_index=3,
            product_id=product_id,
            marker="INVALID_PROFILE_CATEGORY_EVENT",
            expected_profile="fragrance",
            product_profile="invalid_profile",
            category_facts=[
                {
                    "field_key": "sillage",
                    "label": "扩香度",
                    "value": None,
                    "state": "unavailable",
                }
            ],
        )
        page.wait_for_function("activeChatRequests.size === 0")
        assert page.locator(".recommendation-panel").count() == panel_count

        page.fill("#chatInput", "推荐香水非法字段负例")
        page.click("#sendBtn")
        page.wait_for_function(
            "window.__categoryAdversarial.requests.length === 5"
        )
        _emit_adversarial_turn(
            page,
            request_index=4,
            product_id=product_id,
            marker="INVALID_FIELD_CATEGORY_EVENT",
            expected_profile="fragrance",
            product_profile="fragrance",
            category_facts=[
                {
                    "field_key": "invalid_field",
                    "label": "非法字段",
                    "value": None,
                    "state": "unavailable",
                }
            ],
        )
        page.wait_for_function("activeChatRequests.size === 0")
        assert page.locator(".recommendation-panel").count() == panel_count

        page.fill("#chatInput", "推荐香水")
        page.click("#sendBtn")
        page.wait_for_function(
            "window.__categoryAdversarial.requests.length === 6"
        )
        old_session = page.evaluate(
            "() => window.__categoryAdversarial.requests[5].body.session_id"
        )
        page.evaluate("() => createFreshSession()")
        page.wait_for_function(
            "window.__categoryAdversarial.requests[5].aborted === true"
        )
        _emit_adversarial_turn(
            page,
            request_index=5,
            product_id=product_id,
            marker="LATE_CATEGORY_EVENT",
            expected_profile="fragrance",
            product_profile="fragrance",
            category_facts=[
                {
                    "field_key": "sillage",
                    "label": "扩香度",
                    "value": None,
                    "state": "unavailable",
                }
            ],
        )
        page.fill("#chatInput", "推荐香水")
        page.click("#sendBtn")
        page.wait_for_function(
            "window.__categoryAdversarial.requests.length === 7"
        )
        _emit_adversarial_turn(
            page,
            request_index=6,
            product_id=product_id,
            marker="CURRENT_CATEGORY_EVENT",
            expected_profile="fragrance",
            product_profile="fragrance",
            category_facts=[
                {
                    "field_key": "sillage",
                    "label": "扩香度",
                    "value": None,
                    "state": "unavailable",
                }
            ],
        )
        page.wait_for_function("activeChatRequests.size === 0")
        current_session = page.evaluate(
            "() => localStorage.getItem('lumi_current_session_id')"
        )
        body_text = page.locator("body").inner_text()
        if old_session == current_session:
            errors["cross_session_leakage"].append(old_session)
        if "LATE_CATEGORY_EVENT" in body_text:
            errors["late_event_pollution"].append("LATE_CATEGORY_EVENT")
        assert "CURRENT_CATEGORY_EVENT" in body_text
        errors["sse_errors"].extend(
            page.evaluate("() => window.__categoryAdversarial.errors")
        )
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot), full_page=True)
    finally:
        context.close()
    assert all(not values for values in errors.values()), errors
    return {
        "mode": "adversarial",
        "canonical_ids": {
            "fragrance": product_id,
            "wrong_profile_skincare": wrong_profile_product_id,
        },
        "typed_payloads": {
            "valid_xss": "rendered_escaped",
            "wrong_profile": "rejected",
            "invalid_state": "rejected_without_commit",
            "recovery": "accepted_same_version",
            "invalid_profile": "rejected",
            "invalid_field": "rejected",
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/chat",
    )
    parser.add_argument(
        "--mode",
        choices=("normal", "adversarial"),
        required=True,
    )
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=(
                os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
                or None
            ),
        )
        try:
            result = (
                _normal_gate(
                    browser=browser,
                    url=args.url,
                    screenshot=args.screenshot,
                )
                if args.mode == "normal"
                else _adversarial_gate(
                    browser=browser,
                    url=args.url,
                    screenshot=args.screenshot,
                )
            )
        finally:
            browser.close()

    if args.evidence is not None:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
