from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


_CAPTURE_SSE = r"""
(() => {
    window.__consultationSse = [];
    window.__consultationCaptureErrors = [];
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await nativeFetch(...args);
        const input = args[0];
        const url = typeof input === 'string'
            ? input
            : (input?.url || '');
        if (url.includes('/api/v1/chat/stream')) {
            response.clone().text().then(body => {
                const events = body
                    .split(/\n\n+/)
                    .map(block => {
                        let event = 'message';
                        let payload = '';
                        for (const line of block.split('\n')) {
                            if (line.startsWith('event: ')) {
                                event = line.slice(7).trim();
                            } else if (line.startsWith('data: ')) {
                                payload += line.slice(6);
                            }
                        }
                        if (!payload) return null;
                        return {
                            event,
                            data: JSON.parse(payload)
                        };
                    })
                    .filter(Boolean);
                window.__consultationSse.push(events);
            }).catch(error => {
                window.__consultationCaptureErrors.push(String(error));
            });
        }
        return response;
    };
})()
"""


def _send(page, message: str, turn_count: int) -> list[dict]:
    page.fill("#chatInput", message)
    page.click("#sendBtn")
    page.wait_for_function(
        "activeChatRequests.size === 0",
        timeout=120_000,
    )
    page.wait_for_function(
        "count => window.__consultationSse.length >= count",
        arg=turn_count,
        timeout=120_000,
    )
    return page.evaluate(
        "index => window.__consultationSse[index]",
        turn_count - 1,
    )


def _event(events: list[dict], name: str) -> dict:
    return next(item["data"] for item in events if item["event"] == name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/chat",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=Path("/tmp/xiaoro-consultation-browser.png"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("/tmp/xiaoro-consultation-browser.json"),
    )
    args = parser.parse_args()

    with sync_playwright() as playwright:
        executable_path = os.environ.get(
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
        )
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path or None,
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("https://unpkg.com/**", lambda route: route.abort())
        page.add_init_script(_CAPTURE_SSE)
        page_errors: list[str] = []
        parse_errors: list[str] = []
        failed_images: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: parse_errors.append(message.text)
            if "SSE JSON parse failed" in message.text
            else None,
        )
        page.on(
            "response",
            lambda response: failed_images.append(response.url)
            if "/static/images/products/" in response.url
            and response.status != 200
            else None,
        )
        page.goto(args.url, wait_until="networkidle")
        page.evaluate(
            "() => { localStorage.clear(); sessionStorage.clear(); }"
        )
        page.reload(wait_until="networkidle")

        turns: list[dict] = []
        sequence = (
            (
                "我不知道自己是什么肤质",
                "consultation_observation",
            ),
            ("会", "consultation_observation"),
            ("不会", "consultation_observation"),
            ("不会", "consultation_observation"),
            ("不会", "consultation_observation"),
            ("不会", "consultation_provisional"),
            ("我确认是干皮", "profile_confirmation"),
        )
        for index, (message, typed_event) in enumerate(
            sequence,
            start=1,
        ):
            before_cards = page.locator(
                ".recommendation-card"
            ).count()
            events = _send(page, message, index)
            names = [item["event"] for item in events]
            assert typed_event in names
            assert "products" not in names
            card_contract = _event(
                events,
                "card_display_contract",
            )
            assert card_contract == {
                "mode": "none",
                "visible_product_ids": [],
                "max_cards": 0,
                "reason": None,
            }
            assert (
                page.locator(".recommendation-card").count()
                == before_cards
            )
            expect(
                page.locator(
                    "[data-consultation-event="
                    f"'{typed_event}']"
                ).last
            ).to_be_visible(timeout=20_000)
            turns.append(
                {
                    "message": message,
                    "event_names": names,
                    "card_display_contract": card_contract,
                    "conversation_version": _event(
                        events,
                        "end",
                    )["conversation_version"],
                }
            )

        confirmation = _event(
            page.evaluate(
                "() => window.__consultationSse[6]"
            ),
            "profile_confirmation",
        )
        assert confirmation["conclusion"]["confirmed_by_user"] is True
        assert confirmation["profile_persistence"]["outcome"] in {
            "created",
            "idempotent",
        }
        expect(
            page.locator(
                "[data-consultation-event='profile_confirmation']"
            ).last
        ).to_contain_text("长期画像")

        recommendation_events = _send(
            page,
            "500元内防晒",
            len(sequence) + 1,
        )
        products = _event(
            recommendation_events,
            "products",
        )["products"]
        card_contract = _event(
            recommendation_events,
            "card_display_contract",
        )
        assert 1 <= len(products) <= 3
        assert card_contract["mode"] == "recommendation"
        assert card_contract["visible_product_ids"] == [
            item["id"] for item in products
        ]
        expect(
            page.locator(".recommendation-panel").last
        ).to_be_visible(timeout=20_000)
        assert (
            page.locator(".recommendation-panel").last.locator(
                ".recommendation-card"
            ).count()
            == len(products)
        )

        capture_errors = page.evaluate(
            "() => window.__consultationCaptureErrors"
        )
        assert not page_errors, page_errors
        assert not parse_errors, parse_errors
        assert not capture_errors, capture_errors
        assert not failed_images, failed_images

        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.screenshot), full_page=True)
        evidence = {
            "session_id": page.evaluate("getSessionId()"),
            "turns": turns,
            "profile_confirmation": confirmation,
            "later_recommendation": {
                "event_names": [
                    item["event"]
                    for item in recommendation_events
                ],
                "product_ids": [item["id"] for item in products],
                "card_display_contract": card_contract,
            },
            "page_errors": page_errors,
            "sse_parse_errors": parse_errors,
            "sse_capture_errors": capture_errors,
            "failed_product_images": failed_images,
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
