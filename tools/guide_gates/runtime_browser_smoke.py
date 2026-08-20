from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


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


_CAPTURE_GUIDE_SSE = r"""
(() => {
    window.__guideSseEvidence = [];
    window.__guideSseCaptureErrors = [];
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const request = args[0];
        const url = typeof request === 'string'
            ? request
            : (request?.url || '');
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
                        return { event, data: JSON.parse(payload) };
                    })
                    .filter(Boolean);
                window.__guideSseEvidence.push(events);
            }).catch(error => {
                window.__guideSseCaptureErrors.push(String(error));
            });
        }
        return response;
    };
})()
"""

_CONVERSATION_VERSION = """() => {
    const sessionId = localStorage.getItem(
        'lumi_current_session_id'
    );
    const versions = JSON.parse(
        localStorage.getItem(
            'lumi_conversation_versions_v1'
        ) || '{}'
    );
    return versions[sessionId];
}"""


def _wait_for_turn(page, turn_count: int) -> None:
    page.wait_for_function(
        "activeChatRequests.size === 0",
        timeout=120000,
    )
    page.wait_for_function(
        (
            "turnCount => "
            "window.__guideSseEvidence.length >= turnCount"
        ),
        arg=turn_count,
        timeout=120000,
    )
    capture_errors = page.evaluate(
        "() => window.__guideSseCaptureErrors"
    )
    assert not capture_errors, capture_errors


def _turn_evidence(page, turn_index: int) -> dict:
    return page.evaluate(
        """turnIndex => {
            const events = window.__guideSseEvidence[turnIndex];
            const products = events.find(
                item => item.event === 'products'
            );
            const decision = events.find(
                item => item.event === 'decision_process'
            );
            return {
                product_ids: (products?.data?.products || []).map(
                    item => item.id
                ),
                winner_status: decision?.data?.winner_status || null
            };
        }""",
        turn_index,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/chat",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=Path("/tmp/xiaoro-guide-runtime.png"),
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
        page.goto(args.url, wait_until="networkidle")
        assert not page_errors, page_errors
        expect(
            page.locator("#runtimeStatusPill")
        ).to_have_text("文本护肤 · 单图识别/适配 · 2–4 图比较")
        expect(
            page.locator("#runtimeHeaderSubtitle")
        ).to_have_text(
            "肤质咨询 · 单图识别/适配 · 2–4 图比较 · 购买建议"
        )
        page_source = page.content()
        initial_visible_text = page.locator("body").inner_text()
        for prohibited in PROHIBITED_IMAGE_CAPABILITY_COPY:
            assert prohibited not in page_source
            assert prohibited not in initial_visible_text
        runtime_image_copy = page.evaluate(
            """() => onboardingExamples.find(
                item => item.kicker === '图片咨询'
            )?.answer || ''"""
        )
        assert "使用已批准的视觉模型召回候选" in runtime_image_copy
        assert "再按品类和预算执行后端筛选" in runtime_image_copy
        expect(page.locator("#imageUploadBtn")).to_be_visible()
        page.fill("#chatInput", "500 内适合油敏肌的防晒")
        page.click("#sendBtn")
        _wait_for_turn(page, 1)
        expect(
            page.locator(".recommendation-card").first
        ).to_be_visible(timeout=20000)
        expect(
            page.locator("text=真实商品图").first
        ).to_be_visible(timeout=20000)
        expect(
            page.locator(".recommendation-link").first
        ).to_be_visible(timeout=20000)
        assert page.locator(".recommendation-card").count() == 3
        assert page.locator(".message-feedback").count() == 1

        favorite = page.locator("[data-favorite-product-id]").first
        product_id = favorite.get_attribute("data-favorite-product-id")
        assert product_id
        page_count = len(page.context.pages)
        favorite.click()
        expect(favorite).to_have_class("recommendation-save active")
        assert page.evaluate(
            """productId => getStoredProducts().find(
                item => String(item.id) === String(productId)
            )?.favorite""",
            product_id,
        ) is True
        page.reload(wait_until="networkidle")
        restored_favorite = page.locator(
            f'[data-favorite-product-id="{product_id}"]'
        ).first
        expect(restored_favorite).to_be_visible()
        restored_favorite.click()
        assert len(page.context.pages) == page_count
        assert page.evaluate(
            """productId => getStoredProducts().find(
                item => String(item.id) === String(productId)
            )?.favorite""",
            product_id,
        ) is False

        page.evaluate(
            "() => { localStorage.clear(); sessionStorage.clear(); }"
        )
        page.goto(args.url, wait_until="networkidle")
        page.fill("#chatInput", "500 元内修护精华")
        page.click("#sendBtn")
        _wait_for_turn(page, 1)
        expect(
            page.locator(".recommendation-card").first
        ).to_be_visible(timeout=20000)
        expect(
            page.locator("text=真实商品图").first
        ).to_be_visible(timeout=20000)
        expect(
            page.locator(".recommendation-link").first
        ).to_be_visible(timeout=20000)
        repair_panels = page.locator(".recommendation-panel")
        repair_panel = repair_panels.first
        assert repair_panel.locator(".recommendation-card").count() == 2
        first_evidence = _turn_evidence(page, 0)
        assert first_evidence == {
            "product_ids": [91, 38],
            "winner_status": "SELECTED",
        }
        assert page.evaluate(_CONVERSATION_VERSION) == 1

        page.fill("#chatInput", "改成敏感肌呢")
        page.click("#sendBtn")
        _wait_for_turn(page, 2)
        expect(repair_panels.nth(1)).to_be_visible(timeout=20000)
        repair_panel = repair_panels.nth(1)
        assert repair_panel.locator(".recommendation-card").count() == 2
        _assert_category_fact_blocks(
            repair_panel,
            expected_cards=2,
        )
        revision_evidence = _turn_evidence(page, 1)
        assert revision_evidence == {
            "product_ids": [91, 38],
            "winner_status": "INSUFFICIENT_FOR_WINNER",
        }
        assert page.evaluate(_CONVERSATION_VERSION) == 2
        expect(
            repair_panel.locator(".recommendation-efficacies").first
        ).to_contain_text("已审核修护功效")
        expect(
            repair_panel.locator(".recommendation-reason").first
        ).to_contain_text("肤质数据缺失")
        repair_labels = repair_panel.locator(".recommendation-score")
        assert repair_labels.count() == 2
        assert repair_labels.all_inner_texts() == [
            "适配待确认",
            "适配待确认",
        ]
        assert all(
            "%" not in text
            for text in repair_panel.locator(
                ".recommendation-card"
            ).all_inner_texts()
        )
        visible_text = page.locator("body").inner_text()
        assert "知识检索已完成" not in visible_text
        assert "综合打分" not in visible_text
        assert page.locator(".message-feedback").count() == 2
        expect(
            page.locator(".message-markdown").last
        ).to_contain_text("肤质调整为“敏感肌”")

        page.fill("#chatInput", "第二款呢")
        page.click("#sendBtn")
        _wait_for_turn(page, 3)
        expect(repair_panels.nth(2)).to_be_visible(timeout=20000)
        latest_cards = repair_panels.nth(2).locator(
            ".recommendation-card"
        )
        assert latest_cards.count() == 1
        _assert_category_fact_blocks(
            repair_panels.nth(2),
            expected_cards=1,
        )
        expect(latest_cards.first).to_contain_text(
            "理肤泉新B5多效修护精华"
        )
        expect(
            page.locator(".message-markdown").last
        ).to_contain_text("你问的是第二款")
        assert _turn_evidence(page, 2)["product_ids"] == [38]
        assert page.evaluate(_CONVERSATION_VERSION) == 3

        panel_count_before_clarify = repair_panels.count()
        page.fill(
            "#chatInput",
            "预算改成300元，肤质改成敏感肌",
        )
        page.click("#sendBtn")
        _wait_for_turn(page, 4)
        assert repair_panels.count() == panel_count_before_clarify
        clarify_evidence = page.evaluate(
            """() => {
                const events = window.__guideSseEvidence[3];
                const contract = events.find(
                    item => item.event === 'card_display_contract'
                )?.data || null;
                return {
                    hasProducts: events.some(
                        item => item.event === 'products'
                    ),
                    isClarify: events.some(
                        item => item.event === 'message'
                            && item.data?.clarify === true
                    ),
                    contract
                };
            }"""
        )
        assert clarify_evidence["hasProducts"] is False
        assert clarify_evidence["isClarify"] is True
        assert clarify_evidence["contract"] in (
            None,
            {
                "mode": "none",
                "visible_product_ids": [],
                "max_cards": 0,
                "reason": None,
            },
        )
        expect(
            page.locator(".message-markdown").last
        ).to_contain_text("一次只修改一个条件")
        assert page.evaluate(_CONVERSATION_VERSION) == 3

        page.evaluate(
            "() => { localStorage.clear(); sessionStorage.clear(); }"
        )
        page.goto(args.url, wait_until="networkidle")
        page.fill("#chatInput", "500 元内敏感肌修护精华")
        page.click("#sendBtn")
        _wait_for_turn(page, 1)
        budget_panels = page.locator(".recommendation-panel")
        expect(budget_panels.first).to_be_visible(timeout=20000)
        assert (
            budget_panels.first.locator(
                ".recommendation-card"
            ).count()
            == 2
        )

        page.fill("#chatInput", "预算降到 100 元呢")
        page.click("#sendBtn")
        _wait_for_turn(page, 2)
        expect(budget_panels.nth(1)).to_be_visible(timeout=20000)
        budget_cards = budget_panels.nth(1).locator(
            ".recommendation-card"
        )
        assert budget_cards.count() == 1
        _assert_category_fact_blocks(
            budget_panels.nth(1),
            expected_cards=1,
        )
        expect(budget_cards.first).to_contain_text(
            "玉泽皮肤屏障修护精华乳50ml"
        )
        expect(
            page.locator(".message-markdown").last
        ).to_contain_text("预算上限调整为 ¥100")
        expect(
            page.locator(".message-markdown").last
        ).to_contain_text("敏感肌适配证据仍不足")
        assert page.evaluate(_CONVERSATION_VERSION) == 2

        page.evaluate(
            "() => { localStorage.clear(); sessionStorage.clear(); }"
        )
        page.goto(args.url, wait_until="networkidle")
        page.fill("#chatInput", "500元内干性修护精华")
        page.click("#sendBtn")
        _wait_for_turn(page, 1)
        dry_panel = page.locator(".recommendation-panel").first
        expect(dry_panel).to_be_visible(timeout=20000)
        dry_cards = dry_panel.locator(".recommendation-card")
        assert dry_cards.count() == 2
        assert dry_panel.locator(
            ".recommendation-score"
        ).all_inner_texts() == [
            "适配待确认",
            "适配待确认",
        ]
        expect(
            page.locator(".message-markdown").last
        ).to_contain_text("适配证据不足")

        page.evaluate(
            "() => { localStorage.clear(); sessionStorage.clear(); }"
        )
        page.goto(args.url, wait_until="networkidle")
        source_image = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "static"
            / "images"
            / "products"
            / "taobao_v3_572910260362.png"
        )
        assert source_image.is_file()
        page.set_input_files(
            "#imageInput",
            [str(source_image), str(source_image)],
        )
        previews = page.locator("#imagePreview .preview-item")
        expect(previews).to_have_count(2)
        previews.first.locator(".preview-remove").click()
        expect(previews).to_have_count(1)
        page.fill("#chatInput", "150元以内找相似款")
        page.click("#sendBtn")
        _wait_for_turn(page, 1)
        evidence = page.evaluate(
            """() => {
                const events = window.__guideSseEvidence[0];
                const observation = events.find(
                    item => item.event === 'image_observation'
                )?.data?.observation;
                const products = events.find(
                    item => item.event === 'products'
                )?.data?.products || [];
                return {
                    events,
                    observation,
                    product_ids: products.map(item => item.id)
                };
            }"""
        )
        assert evidence["observation"] is not None, evidence
        assert evidence["observation"]["confirmed_product_id"] == 53
        assert evidence["observation"]["model_name"].startswith(
            "OpenCLIP:ViT-B-32"
        )
        assert evidence["observation"]["index_sha256"] == (
            "f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340"
        )
        assert evidence["product_ids"] == [54, 53]
        expect(
            page.locator(".message-markdown").last
        ).to_contain_text("按明确硬条件筛出相似候选")
        assert _turn_evidence(page, 0) == {
            "product_ids": [54, 53],
            "winner_status": "SELECTED",
        }
        image_panel = page.locator(
            "[data-image-model-version][data-image-index-version]"
        ).last
        expect(image_panel).to_be_visible(timeout=20000)
        assert image_panel.get_attribute(
            "data-image-model-version"
        ).startswith("OpenCLIP:ViT-B-32")
        assert image_panel.get_attribute(
            "data-image-index-version"
        ) == evidence["observation"]["index_sha256"]
        image_cards = page.locator(".recommendation-panel").last.locator(
            ".recommendation-card"
        )
        assert image_cards.count() == 2
        assert all(
            value
            for value in image_cards.locator(
                ".recommendation-image"
            ).evaluate_all(
                "(images) => images.map(image => image.currentSrc)"
            )
        )
        assert image_cards.locator(".recommendation-link").count() == 2
        browser_storage = page.evaluate(
            """() => JSON.stringify({
                local: { ...localStorage },
                session: { ...sessionStorage }
            })"""
        )
        assert "owner_" not in browser_storage

        page.evaluate(
            "() => { localStorage.clear(); sessionStorage.clear(); }"
        )
        page.goto(args.url, wait_until="networkidle")
        page.fill("#chatInput", "500 元内长时间户外防晒")
        page.click("#sendBtn")
        _wait_for_turn(page, 1)
        outdoor = page.evaluate(
            """() => {
                const events = window.__guideSseEvidence[0];
                const names = events.map(item => item.event);
                const products = events.find(
                    item => item.event === 'products'
                )?.data?.products || [];
                const scenario = events.find(
                    item => item.event === 'scenario_evidence'
                )?.data?.records || [];
                const reviews = events.find(
                    item => item.event === 'review_evidence'
                )?.data || {};
                return {
                    names,
                    productIds: products.map(item => item.id),
                    scenarioProductIds: scenario.map(
                        item => item.product_id
                    ),
                    approvedSourceCount:
                        reviews.approved_source_count,
                    reviewProductIds: (
                        reviews.results || []
                    ).map(item => item.product_id),
                    evidenceCounts: (
                        reviews.results || []
                    ).map(item => item.evidence.length),
                    absenceProductIds: (
                        reviews.results || []
                    ).filter(item => (
                        item.evidence.length === 0
                        && item.verified_absence?.kind
                            === 'verified_absence'
                    )).map(item => item.product_id),
                    summaryProductIds: (
                        reviews.summaries || []
                    ).map(item => item.product_id),
                    sourceFactCount: (
                        reviews.summaries || []
                    ).reduce(
                        (count, item) => (
                            count + item.source_facts.length
                        ),
                        0
                    ),
                    synthesisCount: (
                        reviews.summaries || []
                    ).filter(item => (
                        item.synthesis?.kind
                            === 'deterministic_synthesis'
                    )).length
                };
            }"""
        )
        assert outdoor["productIds"] == [55, 57, 54]
        assert outdoor["scenarioProductIds"] == [
            55, 55, 55, 57, 57, 57, 54, 54, 54
        ]
        assert outdoor["approvedSourceCount"] == 6
        assert outdoor["reviewProductIds"] == [55, 57, 54]
        assert outdoor["evidenceCounts"] == [2, 0, 0]
        assert outdoor["absenceProductIds"] == [57, 54]
        assert outdoor["summaryProductIds"] == [55]
        assert outdoor["sourceFactCount"] == 2
        assert outdoor["synthesisCount"] == 1
        assert 49 not in outdoor["reviewProductIds"]
        assert 42 not in outdoor["reviewProductIds"]
        assert outdoor["names"].index("scenario_evidence") < (
            outdoor["names"].index("review_evidence")
        )
        assert outdoor["names"].index("review_evidence") < (
            outdoor["names"].index("pitfalls")
        )
        assert outdoor["names"].index("pitfalls") < (
            outdoor["names"].index("decision_process")
        )
        outdoor_panel = page.locator(".recommendation-panel").first
        expect(outdoor_panel).to_be_visible(timeout=20000)
        assert outdoor_panel.locator(".recommendation-card").count() == 3
        expect(page.locator(".evidence-section-title").first).to_have_text(
            "场景证据"
        )
        review_panel = page.locator(".review-evidence-section").first
        expect(review_panel).to_be_visible(timeout=20000)
        assert review_panel.locator(".review-source-fact").count() == 2
        assert review_panel.locator(".review-synthesis").count() == 1
        assert review_panel.locator(".review-product-absence").count() == 2
        assert page.locator(".review-absence-notice").count() == 0
        assert (
            "暂无已批准且可审计的用户评论来源"
            not in page.locator("body").inner_text()
        )

        page.fill("#chatInput", "300到500元长时间户外防晒")
        page.click("#sendBtn")
        _wait_for_turn(page, 2)
        all_absence = page.evaluate(
            """() => {
                const events = window.__guideSseEvidence[1];
                const products = events.find(
                    item => item.event === 'products'
                )?.data?.products || [];
                const reviews = events.find(
                    item => item.event === 'review_evidence'
                )?.data || {};
                const pitfalls = events.find(
                    item => item.event === 'pitfalls'
                )?.data?.pitfalls || [];
                return {
                    productIds: products.map(item => item.id),
                    reviewProductIds: (
                        reviews.results || []
                    ).map(item => item.product_id),
                    absenceProductIds: (
                        reviews.results || []
                    ).filter(item => (
                        item.evidence.length === 0
                        && item.verified_absence?.kind
                            === 'verified_absence'
                    )).map(item => item.product_id),
                    approvedSourceCount:
                        reviews.approved_source_count,
                    summaries: reviews.summaries || [],
                    pitfalls
                };
            }"""
        )
        assert all_absence == {
            "productIds": [26, 101],
            "reviewProductIds": [26, 101],
            "absenceProductIds": [26, 101],
            "approvedSourceCount": 6,
            "summaries": [],
            "pitfalls": [],
        }
        absence_panel = page.locator(".review-evidence-section").nth(1)
        expect(absence_panel).to_be_visible(timeout=20000)
        assert absence_panel.locator(".review-source-fact").count() == 0
        assert absence_panel.locator(".review-synthesis").count() == 0
        assert absence_panel.locator(".review-product-absence").count() == 2

        page.fill("#chatInput", "500 元内敏感期修护精华")
        page.click("#sendBtn")
        _wait_for_turn(page, 3)
        sensitive = page.evaluate(
            """() => {
                const events = window.__guideSseEvidence[2];
                const products = events.find(
                    item => item.event === 'products'
                )?.data?.products || [];
                const pitfalls = events.find(
                    item => item.event === 'pitfalls'
                )?.data?.pitfalls || [];
                return {
                    productIds: products.map(item => item.id),
                    pitfallProductIds: pitfalls.map(
                        item => item.product_id
                    ),
                    severities: pitfalls.map(item => item.severity),
                    hasEvidenceRefs: pitfalls.every(
                        item => item.evidence_refs.length > 0
                    )
                };
            }"""
        )
        assert sensitive == {
            "productIds": [91, 38],
            "pitfallProductIds": [91, 38],
            "severities": ["medium", "medium"],
            "hasEvidenceRefs": True,
        }
        sensitive_panel = page.locator(".recommendation-panel").nth(2)
        expect(sensitive_panel).to_be_visible(timeout=20000)
        assert sensitive_panel.locator(".recommendation-card").count() == 2
        expect(page.locator(".pitfalls-section")).to_be_visible(
            timeout=20000
        )
        assert page.locator(".pitfall-evidence").count() == 2
        assert not page_errors, page_errors
        assert not failed_images, failed_images
        page.screenshot(path=str(args.screenshot), full_page=True)
        page.evaluate(
            """() => displayReviewEvidence({
                approved_source_count: 1,
                results: [{
                    product_id: '<img id="review-product-xss">',
                    evidence: [],
                    verified_absence: { kind: 'verified_absence' }
                }],
                summaries: [{
                    product_id: '<svg id="review-summary-xss">',
                    source_facts: [{
                        quote: '<img id="review-quote-xss">'
                    }],
                    synthesis: {
                        text: '<script id="review-synthesis-xss">'
                    }
                }]
            })"""
        )
        for selector in (
            "#review-product-xss",
            "#review-summary-xss",
            "#review-quote-xss",
            "#review-synthesis-xss",
        ):
            assert page.locator(selector).count() == 0
        escaped_probe = page.locator(
            ".review-evidence-section"
        ).last.inner_text()
        assert '<img id="review-product-xss">' in escaped_probe
        assert '<svg id="review-summary-xss">' in escaped_probe
        assert '<img id="review-quote-xss">' in escaped_probe
        assert '<script id="review-synthesis-xss">' in escaped_probe
        assert not page_errors, page_errors
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
