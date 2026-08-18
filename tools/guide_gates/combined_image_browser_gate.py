from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

from tools.guide_gates.runtime_browser_smoke import (
    _CAPTURE_GUIDE_SSE,
    _wait_for_turn,
)


EXPECTED_INDEX_SHA256 = (
    "f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340"
)


def _reset(page: Page, url: str) -> None:
    page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    page.goto(url, wait_until="networkidle")
    expect(page.locator("#runtimeHeaderSubtitle")).to_have_text(
        "肤质咨询 · 单图识别/适配 · 2–4 图比较 · 购买建议"
    )


def _assert_category_fact_blocks(
    panel,
    *,
    expected_cards: int,
) -> None:
    cards = panel.locator(".recommendation-card")
    assert cards.count() == expected_cards
    for index in range(expected_cards):
        facts = cards.nth(index).locator(".category-facts")
        assert facts.count() == 1
        assert facts.locator(".category-fact-row").count() > 0


def _run_case(
    page: Page,
    *,
    image_paths: list[Path],
    message: str,
    expected_ids: list[int],
    expected_intent: str,
) -> dict:
    page.set_input_files(
        "#imageInput",
        [str(path) for path in image_paths],
    )
    expect(page.locator("#imagePreview .preview-item")).to_have_count(
        len(image_paths)
    )
    page.fill("#chatInput", message)
    page.click("#sendBtn")
    _wait_for_turn(page, 1)
    evidence = page.evaluate(
        """() => {
            const events = window.__guideSseEvidence[0];
            const observations = events.filter(
                item => item.event === 'image_observation'
            ).map(item => item.data.observation);
            const decision = events.find(
                item => item.event === 'decision_process'
            )?.data;
            const contract = events.find(
                item => item.event === 'card_display_contract'
            )?.data;
            const products = events.find(
                item => item.event === 'products'
            )?.data?.products || [];
            const citations = events.find(
                item => item.event === 'citations'
            )?.data?.citations || [];
            return {
                names: events.map(item => item.event),
                observations,
                intent: events.find(
                    item => item.event === 'intent'
                )?.data?.intent,
                decision,
                contract,
                products,
                citations
            };
        }"""
    )
    assert evidence["intent"] == expected_intent
    assert [
        item["confirmed_product_id"]
        for item in evidence["observations"]
    ] == expected_ids
    assert all(
        item["index_sha256"] == EXPECTED_INDEX_SHA256
        for item in evidence["observations"]
    )
    assert evidence["decision"]["ordered_product_ids"] == expected_ids
    assert [item["id"] for item in evidence["products"]] == expected_ids
    assert evidence["contract"]["visible_product_ids"] == expected_ids
    assert evidence["contract"]["max_cards"] == len(expected_ids)
    assert evidence["names"][-1] == "end"
    assert {
        item["source_kind"] for item in evidence["citations"]
    } == {
        "visual_model",
        "ocr_observation",
        "canonical",
    }
    panel = page.locator(".recommendation-panel").last
    cards = panel.locator(".recommendation-card")
    assert cards.count() == len(expected_ids)
    _assert_category_fact_blocks(
        panel,
        expected_cards=len(expected_ids),
    )
    assert page.locator("[data-image-ocr-state]").count() == len(expected_ids)
    expect(page.locator(".citations-section").last).to_be_visible()
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8784/chat",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=Path("/tmp/xiaoro-combined-image-browser.png"),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    product_paths = {
        53: root
        / "app/static/images/products/taobao_v3_572910260362.png",
        55: root
        / "app/static/images/products/tmall_v3_746513552108.png",
        57: root
        / "app/static/images/products/tmall_v3_718554688787.png",
        58: root
        / "app/static/images/products/tmall_v3_768314295559.png",
    }
    assert all(path.is_file() for path in product_paths.values())

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=os.environ.get(
                "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
            )
            or None,
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200}
        )
        page = context.new_page()
        page.route("https://unpkg.com/**", lambda route: route.abort())
        page.add_init_script(_CAPTURE_GUIDE_SSE)
        page_errors: list[str] = []
        failed_images: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "response",
            lambda response: failed_images.append(response.url)
            if "/static/images/products/" in response.url
            and response.status != 200
            else None,
        )
        try:
            page.goto(args.url, wait_until="networkidle")
            single = _run_case(
                page,
                image_paths=[product_paths[53]],
                message="这款适合敏感肌吗",
                expected_ids=[53],
                expected_intent="image_suitability",
            )
            assert single["decision"]["suitability_data"]["status"] in {
                "suitable",
                "not_suitable",
                "insufficient_evidence",
            }

            _reset(page, args.url)
            two = _run_case(
                page,
                image_paths=[product_paths[53], product_paths[55]],
                message="比较这两张图片",
                expected_ids=[53, 55],
                expected_intent="image_compare",
            )
            assert two["decision"]["comparison_data"][
                "winner_reference"
            ]["ordinal"] == 2

            _reset(page, args.url)
            four_ids = [53, 55, 57, 58]
            four = _run_case(
                page,
                image_paths=[product_paths[item] for item in four_ids],
                message="比较这四张图片",
                expected_ids=four_ids,
                expected_intent="image_compare",
            )
            assert [
                item["ordinal"]
                for item in four["decision"]["comparison_data"]["references"]
            ] == [1, 2, 3, 4]
            assert four["decision"]["comparison_data"][
                "winner_reference"
            ]["ordinal"] == 2
            assert not page_errors, page_errors
            assert not failed_images, failed_images
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.screenshot), full_page=True)
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
