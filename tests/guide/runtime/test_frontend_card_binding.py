from __future__ import annotations

import json
import subprocess
from pathlib import Path


MODULE = Path("app/static/guide-presentation.js").resolve()
CHAT_HTML = Path("app/static/chat.html")


def _node(script: str) -> object:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_view_model_binds_inline_and_full_cards_to_same_ids() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
const state = {{
  ...guide.createTurnState(),
  cardDisplay: {{
    mode: 'comparison',
    visible_product_ids: [55, 57],
    max_cards: 2,
    reason: 'comparison',
  }},
  products: [
    {{ id: 57, product_id: 57, image_url: '/57.png' }},
    {{ id: 99, product_id: 99, image_url: '/hidden.png' }},
    {{ id: 55, product_id: 55, image_url: '/55.png' }},
  ],
  presentation: {{
    mode: 'comparison',
    copy_source: 'fallback',
    sections: [
      {{ kind: 'summary', copy_text: '先看差异' }},
      {{ kind: 'comparison', copy_text: '同口径比较' }},
      {{
        kind: 'product',
        copy_text: '第一款',
        slot_id: 'p1',
        product_id: 55,
        direct_facts: [],
      }},
      {{
        kind: 'product',
        copy_text: '第二款',
        slot_id: 'p2',
        product_id: 57,
        direct_facts: [],
      }},
      {{
        kind: 'closing',
        copy_text: '更看重清爽就回看{{{{product:p1}}}}。',
      }},
      {{ kind: 'pitfalls' }},
      {{ kind: 'full_cards' }},
      {{ kind: 'evidence' }},
    ],
    card_display: {{
      mode: 'comparison',
      visible_product_ids: [55, 57],
      max_cards: 2,
      reason: 'comparison',
    }},
    telemetry: {{
      provider: 'disabled',
      model: 'deterministic',
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      latency_ms: 0,
      fallback_reason: 'disabled',
    }},
  }},
}};
const view = guide.renderComparisonPresentation(state);
process.stdout.write(JSON.stringify({{
  inline: view.inlineCardIds,
  full: view.fullCardIds,
  images: view.products.map(item => item.image_url),
  refs: view.productRefs,
}}));
"""
    )

    assert result == {
        "inline": [55, 57],
        "full": [55, 57],
        "images": ["/55.png", "/57.png"],
        "refs": [{"slot_id": "p1", "product_id": 55}],
    }


def test_chat_uses_typed_renderer_and_delegated_product_reference() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "eventName === 'presentation_contract'" in html
    assert "deferredPanels.presentationContract = data" in html
    assert "XiaoRoPresentation.streamPresentation(" in html
    assert "handleGuideProductReference" in html
    assert "'[data-guide-product-ref]'" in html
    assert "scrollIntoView(" in html


def test_renderer_uses_dom_text_not_model_html() -> None:
    source = MODULE.read_text(encoding="utf-8")
    start = source.index("function appendCopyTokens(")
    end = source.index("\n        function thinkingStagesForMode", start)
    renderer = source[start:end]

    assert ".textContent =" in renderer
    assert ".innerHTML" not in renderer
    assert "createTextNode(" in renderer


def test_full_and_inline_cards_prefer_backend_specification() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    start = html.index("function formatProductPrice(product")
    end = html.index(
        "\n        function formatProductPriceMeta",
        start,
    )
    formatter = html[start:end]

    assert "product?.specification" in formatter
    assert "formatCurrency(product?.price)" in formatter
    assert " / ${specification}" in formatter
    assert formatter.index("product?.specification") < formatter.index(
        "displayMeta.price_label"
    )


def test_product_shelf_titles_follow_presentation_mode() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    for title in (
        "为你挑到这些",
        "本轮提到的商品",
        "本轮识别到的商品",
        "本次对比商品",
    ):
        assert title in html
    assert "按需求筛过" not in html
