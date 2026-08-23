from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright

from app.guide.adapters.image.local_numpy_index import (
    controlled_reencode,
)
from tools.guide_gates.runtime_browser_smoke import (
    _CAPTURE_GUIDE_SSE,
    _wait_for_turn,
)


TRAJECTORIES = (
    {
        "id": "product_focus",
        "turns": (
            "给我推荐三款三百元以内、偏修护的精华。",
            "第一款单独说，核对价格和已确认功效。",
            "先问通用知识，精华和面霜通常哪个先用？",
            "回到第一款，确认它的成分和适用肤质。",
            "把第一款和第二款按价格、功效做比较。",
        ),
        "modes": (
            {"recommendation", "revision"},
            {"product_knowledge", "single_product", "followup"},
            {"general_knowledge"},
            {"product_knowledge", "single_product", "followup"},
            {"comparison"},
        ),
    },
    {
        "id": "consultation",
        "turns": (
            "我想判断自己的肤质，下午鼻子油，洗脸后两颊发紧。",
            "更正一下，额头其实不油，主要是鼻翼出油。",
            "中间看一下B5精华，已知功效和适用肤质适合我现在的需求吗？",
            "先回到肤质判断，继续参考前面的出油和洁面后紧绷。",
            "现在突然肿起来，抓破的位置还持续疼，应该怎么办？",
        ),
        "modes": (
            {"consultation"},
            {"consultation"},
            {"product_knowledge", "single_product"},
            {"consultation"},
            {"consultation"},
        ),
    },
    {
        "id": "consultation_return_comparison",
        "turns": (
            "油敏肌，夏天通勤想找修护精华，预算300内，先推荐两款。",
            (
                "先不继续选产品。我下午鼻子出油，洗脸后两颊发紧，"
                "帮我判断我现在的肤质和状态。"
            ),
            "现在再回到刚才的两款精华，按我这个状态，哪款更适合？",
        ),
        "modes": (
            {"recommendation"},
            {"consultation"},
            {"comparison"},
        ),
    },
    {
        "id": "real_images",
        "images": (
            "docs/audits/continuous-conversation/"
            "real-image-ground-truth-v1/"
            "product-53-lrp-clear-non-index.jpg",
            "docs/audits/continuous-conversation/"
            "real-image-ground-truth-v1/"
            "product-57-biore-background-non-index.jpg",
        ),
        "recovery_images": (
            "app/static/images/products/"
            "taobao_v3_572910260362.png",
            "app/static/images/products/"
            "tmall_v3_718554688787.png",
        ),
        "turns": (
            "请按上传顺序识别这两张防晒商品图。",
            "按提示换成更清晰的两张图，请按上传顺序识别。",
            "明确问第二张，它在百元内吗，防晒标识是什么？",
            "以第二张商品为参照，推荐一百三以内且有明确防晒标识的其他选择。",
            "回到第一张图，只核对原图商品的名称和价格。",
        ),
        "modes": (
            {None},
            {"image_identity"},
            {"product_knowledge", "single_product"},
            {"recommendation", "image_recommendation"},
            {"product_knowledge", "single_product", "followup"},
        ),
    },
)


def _image_uploads_for_turn(
    *,
    trajectory: dict[str, Any],
    turn_index: int,
    root: Path,
) -> list[str | dict[str, Any]]:
    if turn_index == 1:
        paths = tuple(
            root / relative
            for relative in trajectory.get("images", ())
        )
        assert all(path.is_file() for path in paths)
        return [str(path) for path in paths]
    if turn_index != 2:
        return []
    paths = tuple(
        root / relative
        for relative in trajectory.get("recovery_images", ())
    )
    assert all(path.is_file() for path in paths)
    return [
        {
            "name": f"{path.stem}-clearer.png",
            "mimeType": "image/png",
            "buffer": controlled_reencode(path.read_bytes()),
        }
        for path in paths
    ]


def _reset_page(browser: Browser, url: str) -> tuple[Page, dict[str, Any]]:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page.route(
        "https://unpkg.com/**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body="",
        ),
    )
    page.add_init_script(_CAPTURE_GUIDE_SSE)
    evidence: dict[str, Any] = {
        "page_errors": [],
        "console_errors": [],
        "failed_requests": [],
        "failed_images": [],
    }
    page.on(
        "pageerror",
        lambda error: evidence["page_errors"].append(str(error)),
    )
    page.on(
        "console",
        lambda message: evidence["console_errors"].append(message.text)
        if message.type == "error"
        else None,
    )
    page.on(
        "requestfailed",
        lambda request: evidence["failed_requests"].append({
            "url": request.url,
            "error": request.failure,
        })
        if "unpkg.com" not in request.url
        else None,
    )
    page.on(
        "response",
        lambda response: evidence["failed_images"].append({
            "url": response.url,
            "status": response.status,
        })
        if (
            "/static/images/products/" in response.url
            and response.status != 200
        )
        else None,
    )
    page.goto(url, wait_until="networkidle")
    return page, evidence


def _event_evidence(page: Page, turn_index: int) -> dict[str, Any]:
    return page.evaluate(
        """turnIndex => {
            const events = window.__guideSseEvidence[turnIndex] || [];
            const find = name => events.find(item => item.event === name);
            const presentation = find('presentation_contract')?.data || null;
            const products = find('products')?.data?.products || [];
            const end = find('end')?.data || null;
            const messageCount = events.filter(
                item => item.event === 'message'
            ).length;
            const presentationCount = events.filter(
                item => item.event === 'presentation_contract'
            ).length;
            const clarifyCount = events.filter(
                item => item.event === 'clarify'
            ).length;
            return {
                event_names: events.map(item => item.event),
                intent: find('intent')?.data || null,
                presentation,
                product_ids: products.map(item => item.id),
                message_count: messageCount,
                presentation_count: presentationCount,
                clarify_count: clarifyCount,
                clarification: clarifyCount === 1,
                conversation_version:
                    end?.conversation_version ?? null
            };
        }""",
        turn_index,
    )


def _wait_for_loaded_images(page: Page) -> None:
    page.wait_for_function(
        "() => Array.from(document.images).every("
        "image => !image.src || image.complete"
        ")",
        timeout=5000,
    )


def _dom_evidence(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const panels = Array.from(
                document.querySelectorAll('.guide-presentation-root')
            );
            const last = panels.at(-1) || null;
            const shelfCards = last
                ? Array.from(
                    last.querySelectorAll(
                        '[data-guide-card-form="shelf"]'
                    )
                )
                : [];
            const images = Array.from(
                document.querySelectorAll('img')
            );
            const unloaded = images
                .filter(image => image.src && !image.complete)
                .map(image => image.src);
            return {
                presentation_count: panels.length,
                last_mode: last?.dataset.presentationMode || null,
                last_section_kinds: last
                    ? Array.from(
                        last.querySelectorAll(
                            '[data-section-kind]'
                        )
                    ).map(item =>
                        item.getAttribute('data-section-kind')
                    )
                    : [],
                inline_card_count: last
                    ? last.querySelectorAll(
                        '[data-guide-card-form="inline"]'
                    ).length
                    : 0,
                shelf_card_count: shelfCards.length,
                legacy_full_card_count: last
                    ? last.querySelectorAll(
                        '[data-guide-card-form="full"]'
                    ).length
                    : 0,
                shelf_reason_count: shelfCards.filter(card =>
                    card.innerText.includes('推荐理由')
                ).length,
                fit_pending_count: last
                    ? (
                        last.innerText.match(/适配待确认/g) || []
                    ).length
                    : 0,
                comparison_table_count: last
                    ? last.querySelectorAll(
                        '.guide-comparison-table'
                    ).length
                    : 0,
                winner_count: last
                    ? last.querySelectorAll(
                        '.guide-winner-conclusion'
                    ).length
                    : 0,
                horizontal_overflow:
                    document.documentElement.scrollWidth
                    > document.documentElement.clientWidth + 1,
                unloaded_images: unloaded,
                thinking_visible: Boolean(
                    document.querySelector(
                        '.guide-thinking-pipeline:not([hidden])'
                    )
                ),
                body_text: document.body.innerText.slice(-6000)
            };
        }"""
    )


def _assert_turn(
    *,
    trajectory_id: str,
    turn_index: int,
    expected_modes: set[str | None],
    event: dict[str, Any],
    dom: dict[str, Any],
    prior_products: list[int] | None,
) -> list[int] | None:
    assert event["event_names"][-1] == "end", event
    assert event["message_count"] == 0, event
    assert event["event_names"].count("message") == 0, event
    assert not dom["horizontal_overflow"], dom
    assert not dom["unloaded_images"], dom
    mode = (
        event["presentation"].get("mode")
        if event["presentation"] is not None
        else None
    )
    assert mode in expected_modes, (expected_modes, event)
    if event["presentation"] is not None:
        assert event["presentation_count"] == 1, event
        assert event["clarify_count"] == 0, event
        assert not event["clarification"], event
        copy_source = event["presentation"].get("copy_source")
        assert copy_source in {
            "model",
            "authoritative",
            "fallback",
        }, event
        assert dom["presentation_count"] >= 1, dom
        assert dom["last_mode"] == mode, dom
        assert dom["legacy_full_card_count"] == 0, dom
        assert dom["shelf_reason_count"] == 0, dom
        assert dom["fit_pending_count"] == 0, dom
    else:
        assert event["presentation_count"] == 0, event
        assert event["clarify_count"] == 1, event
        assert event["clarification"], event
    products = event["product_ids"]
    if event["presentation"] is not None:
        assert dom["shelf_card_count"] == len(products), dom
        if mode == "recommendation":
            assert dom["inline_card_count"] == len(products), dom
        else:
            assert dom["inline_card_count"] == 0, dom
        if mode == "comparison":
            assert dom["comparison_table_count"] == 1, dom
            assert dom["winner_count"] == 1, dom
    if trajectory_id == "product_focus":
        if turn_index == 1:
            assert 1 <= len(products) <= 3, products
            prior_products = products
        elif turn_index in {2, 4}:
            assert prior_products and products == [prior_products[0]], products
        elif turn_index == 3:
            assert products == [], products
        elif turn_index == 5:
            assert prior_products and products == prior_products[:2], products
    elif trajectory_id == "consultation":
        if turn_index == 3:
            assert products == [38], products
        else:
            assert products == [], products
    elif trajectory_id == "consultation_return_comparison":
        if turn_index == 1:
            assert len(products) == 2, products
            prior_products = products
        elif turn_index == 2:
            assert products == [], products
        elif turn_index == 3:
            assert prior_products and products == prior_products, products
    else:
        if turn_index == 1:
            assert event["clarification"] and products == [], event
        elif turn_index == 2:
            assert products == [53, 57], products
        elif turn_index == 3:
            assert products == [57], products
        elif turn_index == 4:
            assert products and 57 not in products, products
        elif turn_index == 5:
            assert products == [53], products
    return prior_products


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8799/chat",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "docs/audits/continuous-conversation/"
            "browser-real-3x5-v2"
        ),
    )
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    report: dict[str, Any] = {
        "schema_version": "guide-browser-real-transition-v3",
        "url": args.url,
        "trajectories": [],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for trajectory in TRAJECTORIES:
                page, page_evidence = _reset_page(browser, args.url)
                trajectory_result: dict[str, Any] = {
                    "trajectory_id": trajectory["id"],
                    "turns": [],
                    **page_evidence,
                }
                prior_products: list[int] | None = None
                for turn_index, (
                    message,
                    expected_modes,
                ) in enumerate(
                    zip(
                        trajectory["turns"],
                        trajectory["modes"],
                        strict=True,
                    ),
                    start=1,
                ):
                    image_uploads = _image_uploads_for_turn(
                        trajectory=trajectory,
                        turn_index=turn_index,
                        root=root,
                    )
                    if image_uploads:
                        page.set_input_files(
                            "#imageInput",
                            image_uploads,
                        )
                    page.fill("#chatInput", message)
                    page.click("#sendBtn")
                    _wait_for_turn(page, turn_index)
                    event = _event_evidence(page, turn_index - 1)
                    _wait_for_loaded_images(page)
                    dom = _dom_evidence(page)
                    prior_products = _assert_turn(
                        trajectory_id=trajectory["id"],
                        turn_index=turn_index,
                        expected_modes=expected_modes,
                        event=event,
                        dom=dom,
                        prior_products=prior_products,
                    )
                    screenshot = (
                        output
                        / f"{trajectory['id']}-t{turn_index}-desktop.png"
                    )
                    page.screenshot(path=str(screenshot), full_page=True)
                    trajectory_result["turns"].append({
                        "turn_index": turn_index,
                        "event": event,
                        "dom": {
                            key: value
                            for key, value in dom.items()
                            if key != "body_text"
                        },
                        "screenshot": screenshot.name,
                    })
                    (output / "partial.json").write_text(
                        json.dumps(
                            report
                            | {
                                "active_trajectory": trajectory_result,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(500)
                _wait_for_loaded_images(page)
                mobile = output / f"{trajectory['id']}-terminal-mobile.png"
                page.screenshot(path=str(mobile), full_page=True)
                mobile_dom = _dom_evidence(page)
                assert not mobile_dom["horizontal_overflow"], mobile_dom
                trajectory_result["mobile_screenshot"] = mobile.name
                assert not trajectory_result["page_errors"]
                assert not trajectory_result["console_errors"]
                assert not trajectory_result["failed_requests"]
                assert not trajectory_result["failed_images"]
                report["trajectories"].append(trajectory_result)
                page.context.close()
        finally:
            browser.close()

    report["trajectory_count"] = len(report["trajectories"])
    report["turn_count"] = sum(
        len(item["turns"]) for item in report["trajectories"]
    )
    report["passed"] = (
        report["trajectory_count"] == 4
        and report["turn_count"] == 18
    )
    (output / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "partial.json").unlink(missing_ok=True)
    print(json.dumps({
        "passed": report["passed"],
        "trajectory_count": report["trajectory_count"],
        "turn_count": report["turn_count"],
        "output": str(output / "result.json"),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
