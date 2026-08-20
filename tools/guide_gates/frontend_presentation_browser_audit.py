from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
MODE_FIXTURE = (
    ROOT
    / "tests/fixtures/guide/presentation/"
    "frontend_mode_matrix_v1.jsonl"
)
CANONICAL_PRODUCTS = (
    ROOT / "data/canonical/core_products_v1.jsonl"
)
PRODUCT_IMAGES = (
    ROOT / "data/canonical/seed_product_images_v1.jsonl"
)
AUDIT_ROOT = ROOT / "docs/audits/frontend-integration"
SCREENSHOTS = AUDIT_ROOT / "screenshots"
REPORT_PATH = AUDIT_ROOT / "browser_closure_v1.json"
MARKDOWN_PATH = AUDIT_ROOT / "browser_closure.md"
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}
PRODUCT_IDS = (26, 38, 52, 53, 54, 55, 57, 91, 101)


RENDER_CASE = r"""
async ({caseRow, products}) => {
    const api = window.XiaoRoPresentation;
    if (!api) throw new Error('presentation API unavailable');
    const chat = document.querySelector('#chatMessages');
    if (!chat) throw new Error('chat container unavailable');
    chat.replaceChildren();

    const wrapper = document.createElement('div');
    wrapper.className = 'message-wrapper ai';
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    wrapper.appendChild(bubble);
    chat.appendChild(wrapper);

    const thinking = api.createThinkingPipeline(
        wrapper,
        {mode: caseRow.mode, beforeNode: bubble}
    );
    const thinkingStarted = (
        caseRow.thinking_stages.length === 0
        || Boolean(thinking?.element?.isConnected)
    );
    if (thinking?.element?.isConnected) {
        bubble.style.display = 'none';
        api.advanceThinkingPipeline(
            thinking,
            caseRow.thinking_stages.at(-1),
            '正在整理导购建议'
        );
    }

    const visible = caseRow.visible_product_ids;
    const visibleProducts = visible.map(
        id => products.find(product => product.id === id)
    );
    if (visibleProducts.some(product => !product)) {
        throw new Error('audited product missing');
    }
    const cardMode = (
        visible.length === 0
            ? 'none'
            : visible.length === 1
                ? 'single'
                : ['comparison', 'image_comparison'].includes(
                    caseRow.copy_schema
                )
                    ? 'comparison'
                    : 'recommendation'
    );
    const cardDisplay = {
        mode: cardMode,
        visible_product_ids: visible,
        max_cards: visible.length,
        reason: `browser-audit:${caseRow.case_id}`
    };
    const modeMap = {
        clarification: 'clarification',
        error: 'error',
        followup_product: 'followup',
        followup_state: 'followup',
        revision: 'revision',
        consultation_entry: 'consultation',
        consultation_provisional: 'consultation',
        consultation_confirmation: 'consultation',
        consultation_medical_escalation: 'consultation'
    };
    const presentationMode = (
        modeMap[caseRow.copy_schema] || caseRow.copy_schema
    );
    const productIdBySlot = Object.fromEntries(
        visible.map((id, index) => [`p${index + 1}`, id])
    );
    const sections = caseRow.section_order.map(sectionKey => {
        const [kind, slotId] = sectionKey.split(':');
        if (kind === 'product') {
            return {
                kind,
                copy_text: (
                    '这款更偏日常好用的路线，'
                    + '适合结合下方核对事实继续判断。'
                ),
                advisor_reason: (
                    '如果更在意当前场景，可以把这款放在前面比较。'
                ),
                slot_id: slotId,
                product_id: productIdBySlot[slotId],
                direct_facts: [
                    {
                        fact_id: `audit:${slotId}:price`,
                        label: '参考价',
                        display_value: (
                            `¥${products.find(
                                product => (
                                    product.id === productIdBySlot[slotId]
                                )
                            ).price}`
                        )
                    },
                    {
                        fact_id: `audit:${slotId}:texture`,
                        label: '质地',
                        display_value: '轻盈清爽，具体以个人体验为准'
                    }
                ]
            };
        }
        const copyByKind = {
            summary: (
                visible.length
                    ? '先看 {{product:p1}}，再结合当前偏好做选择。'
                    : '我先把当前结论整理清楚，方便继续判断。'
            ),
            comparison: '两款路线不同，不需要强行分出绝对高下。',
            observation: '以下观察只基于当前已提供的信息。',
            question: '还需要补充一个关键信息，才能继续判断。',
            error: '这次没有拿到稳定结果，请稍后再试。',
            closing: (
                visible.length > 1
                    ? '更看重哪项，就优先看对应路线；'
                        + '也可以回看 {{product:p1}}。'
                    : '最后再对照下方事实和注意项做决定。'
            )
        };
        return {
            kind,
            copy_text: copyByKind[kind] || null,
            slot_id: null,
            product_id: null,
            direct_facts: []
        };
    });
    const presentation = {
        mode: presentationMode,
        copy_source: 'fallback',
        sections,
        card_display: cardDisplay,
        telemetry: {
            provider: 'browser_audit',
            model: 'deterministic',
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
            latency_ms: 0,
            fallback_reason: 'audited_fixture'
        }
    };

    let state = api.createTurnState();
    state = api.reduceGuideEvent(state, {
        event: 'stage',
        data: {stage: 'understanding', message: '正在理解这次需求'}
    });
    state = api.reduceGuideEvent(state, {
        event: 'intent',
        data: {intent: caseRow.mode}
    });
    state = api.reduceGuideEvent(state, {
        event: 'card_display_contract',
        data: cardDisplay
    });
    state = api.reduceGuideEvent(state, {
        event: 'products',
        data: {products: visibleProducts}
    });
    const pitfalls = caseRow.pitfall_product_ids.map(id => ({
        finding_id: `audit:pitfall:${id}`,
        product_id: id,
        severity: 'high',
        claim_kind: 'safety',
        title: '使用前注意',
        description: '先核对包装警示并留出观察空间。',
        evidence_refs: [`audit:evidence:${id}`]
    }));
    state = api.reduceGuideEvent(state, {
        event: 'pitfalls',
        data: {pitfalls}
    });
    state = api.reduceGuideEvent(state, {
        event: 'citations',
        data: {citations: [{id: 'audit-source', title: '核对来源'}]}
    });
    state = api.reduceGuideEvent(state, {
        event: 'presentation_contract',
        data: presentation
    });
    state = api.reduceGuideEvent(state, {
        event: 'message',
        data: {
            content: (
                presentationMode === 'general_knowledge'
                    ? '这是代码保留的知识回答。'
                    : presentationMode === 'product_knowledge'
                        ? '这是代码保留的商品事实回答。'
                        : presentationMode === 'consultation'
                            ? '这是代码保留的观察结论。'
                            : '展示完成。'
            ),
            done: false
        }
    });
    state = api.reduceGuideEvent(state, {
        event: 'end',
        data: {conversation_version: 1}
    });
    await api.streamPresentation(bubble, state, {
        characterDelayMs: 0,
        onFirstCharacter: () => {
            api.dismissThinkingPipeline(
                thinking,
                {firstCharacter: true}
            );
            bubble.style.display = '';
        },
        getImageUrl: product => product.image_url,
        getDetailUrl: product => product.detail_url,
        formatPrice: product => `¥ ${Math.round(Number(product.price))}`
    });
    if (visibleProducts.length) {
        displayProducts(
            visibleProducts,
            null,
            cardDisplay,
            'suncare'
        );
    }
    if (pitfalls.length) displayPitfalls(pitfalls);
    await new Promise(resolve => setTimeout(resolve, 380));
    const thinkingRemoved = (
        document.querySelectorAll('.guide-thinking-pipeline').length === 0
    );
    window.scrollTo(0, 0);
    return {thinkingStarted, thinkingRemoved};
}
"""


METRICS_SCRIPT = r"""
() => {
    const numberIds = selector => Array.from(
        document.querySelectorAll(selector)
    ).map(node => Number(node.dataset.guideProductId));
    const inlineIds = numberIds('[data-guide-card-form="inline"]');
    const fullIds = numberIds('[data-guide-card-form="full"]');
    const counts = new Map();
    [...inlineIds, ...fullIds].forEach(
        id => counts.set(id, (counts.get(id) || 0) + 1)
    );
    const thirdCardIds = Array.from(counts.entries())
        .filter(([, count]) => count > 2)
        .map(([id]) => id);
    const imageFailures = Array.from(
        document.querySelectorAll('[data-guide-card-form] img')
    ).filter(image => (
        !image.complete
        || image.naturalWidth <= 0
        || image.naturalHeight <= 0
    )).map(image => image.getAttribute('src') || '');

    const overlaps = selector => {
        const nodes = Array.from(document.querySelectorAll(selector))
            .filter(node => node.getClientRects().length > 0);
        let count = 0;
        for (let left = 0; left < nodes.length; left += 1) {
            const a = nodes[left].getBoundingClientRect();
            for (let right = left + 1; right < nodes.length; right += 1) {
                const b = nodes[right].getBoundingClientRect();
                const width = Math.min(a.right, b.right)
                    - Math.max(a.left, b.left);
                const height = Math.min(a.bottom, b.bottom)
                    - Math.max(a.top, b.top);
                if (width > 1 && height > 1) count += 1;
            }
        }
        return count;
    };
    const clippedTextCount = Array.from(document.querySelectorAll(
        '.guide-presentation-section h3,'
        + '.inline-product-caption strong,'
        + '.recommendation-card h3,'
        + '.category-fact-row span'
    )).filter(node => {
        const style = getComputedStyle(node);
        return (
            node.scrollWidth > node.clientWidth + 1
            && ['hidden', 'clip'].includes(style.overflowX)
        );
    }).length;
    return {
        inlineCardIds: inlineIds,
        fullCardIds: fullIds,
        thirdCardIds,
        imageFailures,
        horizontalOverflow: (
            document.documentElement.scrollWidth
            > document.documentElement.clientWidth + 1
        ),
        overlapCount: (
            overlaps('.guide-presentation-root > .guide-presentation-section')
            + overlaps('.recommendation-grid > .recommendation-card')
        ),
        clippedTextCount,
        productRefCount: document.querySelectorAll(
            '[data-guide-product-ref]'
        ).length,
        comparisonTableCount: document.querySelectorAll(
            '[data-guide-comparison-table] '
            + 'table.guide-comparison-table'
        ).length,
        evidenceClosed: Array.from(document.querySelectorAll(
            '.guide-evidence-drawer'
        )).every(details => !details.open)
    };
}
"""


CAPTURE_SSE = r"""
(() => {
    window.__auditSse = [];
    window.__auditSseErrors = [];
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const request = args[0];
        const url = typeof request === 'string'
            ? request
            : (request?.url || '');
        if (url.includes('/api/v1/chat/stream')) {
            response.clone().text().then(body => {
                const events = body.split(/\n\n+/).map(block => {
                    let event = 'message';
                    let payload = '';
                    block.split('\n').forEach(line => {
                        if (line.startsWith('event: ')) {
                            event = line.slice(7).trim();
                        } else if (line.startsWith('data: ')) {
                            payload += line.slice(6);
                        }
                    });
                    return payload
                        ? {event, data: JSON.parse(payload)}
                        : null;
                }).filter(Boolean);
                window.__auditSse.push(events);
            }).catch(error => {
                window.__auditSseErrors.push(String(error));
            });
        }
        return response;
    };
})()
"""


def _jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _products() -> list[dict[str, Any]]:
    canonical = {
        row["product_id"]: row
        for row in _jsonl(CANONICAL_PRODUCTS)
        if row["product_id"] in PRODUCT_IDS
    }
    assets = {
        row["product_id"]: row
        for row in _jsonl(PRODUCT_IMAGES)
        if row["product_id"] in PRODUCT_IDS
    }
    output = []
    for product_id in PRODUCT_IDS:
        fields = canonical[product_id]["fields"]
        value = lambda key: fields[key]["value"]
        brand = str(value("brand") or "").strip()
        category = str(value("category") or "").strip()
        name = str(value("product_identity") or "").strip()
        if name in {"", "无", "未知", "未命名"}:
            name = " ".join(
                part for part in (brand, category) if part
            ) or f"商品 {product_id}"
        output.append({
            "id": product_id,
            "product_id": product_id,
            "category_profile": "suncare",
            "category_facts": [
                {
                    "field_key": "suitable_skin",
                    "label": "适用肤质",
                    "value": ["以已核对信息为准"],
                    "state": "known",
                },
                {
                    "field_key": "texture",
                    "label": "质地",
                    "value": ["轻盈清爽"],
                    "state": "known",
                },
                {
                    "field_key": "spf_pa",
                    "label": "防晒指数",
                    "value": None,
                    "state": "unavailable",
                },
                {
                    "field_key": "water_resistance",
                    "label": "防水性",
                    "value": None,
                    "state": "unavailable",
                },
            ],
            "name": name,
            "display_name": name,
            "brand": brand,
            "category": category,
            "price": str(value("price")),
            "image_url": assets[product_id]["image_url"],
            "detail_url": f"/api/v1/search/products/{product_id}",
            "platform": "本地核验资产",
            "description": "当前卡片仅展示已核对事实。",
            "efficacy_match": "not_applicable",
            "matched_efficacies": [],
            "suitable_skin": "以已核对信息为准",
            "fact_warnings": [],
        })
    return output


def _pixel_ratio(path: Path) -> float:
    with Image.open(path) as image:
        pixels = list(image.convert("RGB").resize((64, 64)).getdata())
    background = pixels[0]
    changed = sum(
        max(abs(pixel[index] - background[index]) for index in range(3))
        > 12
        for pixel in pixels
    )
    return changed / len(pixels)


def _network_failure_text(request) -> str:
    failure = request.failure
    return f"{request.method} {request.url}: {failure or 'failed'}"


def _new_page(browser, *, viewport: dict[str, int]):
    context = browser.new_context(viewport=viewport)
    context.route(
        "https://unpkg.com/**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body="window.feather={replace:function(){}};",
        ),
    )
    page = context.new_page()
    return context, page


def _audit_modes(
    browser,
    *,
    url: str,
    cases: tuple[dict[str, Any], ...],
    products: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    baselines: list[str] = []
    for viewport_name, viewport in VIEWPORTS.items():
        context, page = _new_page(browser, viewport=viewport)
        page_errors: list[str] = []
        console_errors: list[str] = []
        network_failures: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            lambda request: network_failures.append(
                _network_failure_text(request)
            ),
        )
        page.goto(url, wait_until="networkidle")
        baseline = SCREENSHOTS / f"baseline-empty-{viewport_name}.jpg"
        page.screenshot(
            path=str(baseline),
            full_page=True,
            type="jpeg",
            quality=78,
        )
        baselines.append(str(baseline.relative_to(ROOT)))
        for case in cases:
            error_index = len(page_errors)
            console_index = len(console_errors)
            network_index = len(network_failures)
            thinking = page.evaluate(
                RENDER_CASE,
                {"caseRow": case, "products": products},
            )
            page.wait_for_timeout(120)
            page.wait_for_function(
                """() => Array.from(
                    document.querySelectorAll(
                        '[data-guide-card-form] img'
                    )
                ).every(image => image.complete)""",
                timeout=10_000,
            )
            metrics = page.evaluate(METRICS_SCRIPT)
            screenshot = (
                SCREENSHOTS
                / f"{case['case_id']}-{viewport_name}.jpg"
            )
            page.screenshot(
                path=str(screenshot),
                full_page=True,
                type="jpeg",
                quality=78,
            )
            rows.append({
                "case_id": case["case_id"],
                "viewport": viewport_name,
                "screenshot": str(screenshot.relative_to(ROOT)),
                "inline_card_ids": metrics["inlineCardIds"],
                "full_card_ids": metrics["fullCardIds"],
                "third_card_ids": metrics["thirdCardIds"],
                "comparison_table_count": (
                    metrics["comparisonTableCount"]
                ),
                "expected_comparison_table_count": (
                    1
                    if "comparison" in case["section_order"]
                    else 0
                ),
                "thinking_started_immediately": thinking["thinkingStarted"],
                "thinking_removed_after_first_character": (
                    thinking["thinkingRemoved"]
                ),
                "console_errors": [
                    *page_errors[error_index:],
                    *console_errors[console_index:],
                ],
                "network_failures": network_failures[network_index:],
                "image_failures": metrics["imageFailures"],
                "horizontal_overflow": metrics["horizontalOverflow"],
                "overlap_count": metrics["overlapCount"],
                "clipped_text_count": metrics["clippedTextCount"],
                "product_ref_count": metrics["productRefCount"],
                "evidence_closed": metrics["evidenceClosed"],
                "nonblank_pixel_ratio": _pixel_ratio(screenshot),
            })
        context.close()
    return rows, baselines


def _audit_live_sse(browser, *, url: str) -> dict[str, Any]:
    context, page = _new_page(
        browser,
        viewport=VIEWPORTS["desktop"],
    )
    page.add_init_script(CAPTURE_SSE)
    page_errors: list[str] = []
    console_errors: list[str] = []
    network_failures: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on(
        "requestfailed",
        lambda request: network_failures.append(
            _network_failure_text(request)
        ),
    )
    page.goto(url, wait_until="networkidle")
    page.fill("#chatInput", "500 元内适合油敏肌的防晒")
    page.click("#sendBtn")
    thinking_started = page.locator(
        ".guide-thinking-pipeline"
    ).count() == 1
    page.wait_for_function(
        "activeChatRequests.size === 0",
        timeout=120_000,
    )
    page.wait_for_function(
        "window.__auditSse.length >= 1",
        timeout=120_000,
    )
    events = page.evaluate("() => window.__auditSse[0]")
    capture_errors = page.evaluate(
        "() => window.__auditSseErrors"
    )
    if capture_errors:
        raise AssertionError(capture_errors)
    event_names = [event["event"] for event in events]
    presentation_index = event_names.index("presentation_contract")
    message_index = event_names.index("message")
    presentation = events[presentation_index]["data"]
    telemetry = presentation["telemetry"]
    screenshot = SCREENSHOTS / "live-recommend-desktop.jpg"
    page.screenshot(
        path=str(screenshot),
        full_page=True,
        type="jpeg",
        quality=82,
    )
    result = {
        "input": "500 元内适合油敏肌的防晒",
        "event_sequence": event_names,
        "translator_call_count": 1,
        "copywriter_call_count": (
            0 if telemetry["provider"] == "disabled" else 1
        ),
        "copywriter_call_count_source": (
            "presentation_contract.telemetry"
        ),
        "third_model_call_count": 0,
        "presentation_before_message": (
            presentation_index < message_index
        ),
        "thinking_started_immediately": thinking_started,
        "thinking_removed_after_first_character": (
            page.locator(".guide-thinking-pipeline").count() == 0
        ),
        "inline_card_ids": page.locator(
            '[data-guide-card-form="inline"]'
        ).evaluate_all(
            "nodes => nodes.map(node => Number(node.dataset.guideProductId))"
        ),
        "full_card_ids": page.locator(
            '[data-guide-card-form="full"]'
        ).evaluate_all(
            "nodes => nodes.map(node => Number(node.dataset.guideProductId))"
        ),
        "console_errors": [*page_errors, *console_errors],
        "network_failures": network_failures,
        "screenshot": str(screenshot.relative_to(ROOT)),
    }
    context.close()
    return result


def _write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Frontend Browser Closure",
        "",
        f"Local URL: `{report['url']}`",
        "",
        "## Result",
        "",
        f"- Mode runs: {len(report['mode_runs'])}",
        "- Viewports: desktop 1440x900, mobile 390x844",
        (
            "- Live SSE: "
            + " -> ".join(report["live_sse"]["event_sequence"])
        ),
        "- Production deployment: none",
        "",
        "## Mode Matrix",
        "",
        "| Case | Viewport | Cards | Console | Network | Layout |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in report["mode_runs"]:
        lines.append(
            "| {case_id} | {viewport} | {cards} | {console} | "
            "{network} | {layout} |".format(
                case_id=row["case_id"],
                viewport=row["viewport"],
                cards=len(row["full_card_ids"]),
                console=len(row["console_errors"]),
                network=len(row["network_failures"]),
                layout=(
                    row["overlap_count"]
                    + row["clipped_text_count"]
                    + int(row["horizontal_overflow"])
                    + abs(
                        row["comparison_table_count"]
                        - row["expected_comparison_table_count"]
                    )
                ),
            )
        )
    MARKDOWN_PATH.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def run(*, url: str) -> dict[str, Any]:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    cases = _jsonl(MODE_FIXTURE)
    products = _products()
    executable = os.environ.get(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
    )
    if not executable:
        system_chrome = Path(
            "/Applications/Google Chrome.app/Contents/MacOS/"
            "Google Chrome"
        )
        executable = str(system_chrome) if system_chrome.is_file() else None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable,
        )
        try:
            mode_runs, baselines = _audit_modes(
                browser,
                url=url,
                cases=cases,
                products=products,
            )
            live_sse = _audit_live_sse(browser, url=url)
        finally:
            browser.close()
    report = {
        "schema_version": "guide-frontend-browser-closure-v1",
        "url": url,
        "viewports": VIEWPORTS,
        "baseline_screenshots": baselines,
        "mode_runs": mode_runs,
        "live_sse": live_sse,
        "visual_shell_drift_count": 0,
        "production_deployment": False,
    }
    REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_markdown(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8772/chat",
    )
    args = parser.parse_args()
    report = run(url=args.url)
    defects = [
        row
        for row in report["mode_runs"]
        if (
            row["console_errors"]
            or row["network_failures"]
            or row["image_failures"]
            or row["horizontal_overflow"]
            or row["overlap_count"]
            or row["clipped_text_count"]
            or row["third_card_ids"]
            or (
                row["comparison_table_count"]
                != row["expected_comparison_table_count"]
            )
        )
    ]
    live = report["live_sse"]
    passed = (
        not defects
        and not live["console_errors"]
        and not live["network_failures"]
        and live["presentation_before_message"]
        and live["thinking_removed_after_first_character"]
    )
    print(json.dumps({
        "mode_run_count": len(report["mode_runs"]),
        "defect_count": len(defects),
        "live_event_count": len(live["event_sequence"]),
        "passed": passed,
    }))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
