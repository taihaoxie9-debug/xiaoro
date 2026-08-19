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


def test_structured_stream_emits_first_character_before_inline_card() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
class FakeNode {{
  constructor(tagName, ownerDocument) {{
    this.tagName = String(tagName || '').toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.childNodes = this.children;
    this.dataset = {{}};
    this.className = '';
    this.parentNode = null;
    this.textContent = '';
    this.src = '';
  }}
  append(...nodes) {{
    nodes.forEach(node => this.appendChild(node));
  }}
  appendChild(node) {{
    node.parentNode = this;
    this.children.push(node);
    return node;
  }}
  replaceChildren(...nodes) {{
    this.children.splice(0, this.children.length);
    this.append(...nodes);
  }}
  setAttribute(name, value) {{
    this[name] = String(value);
  }}
  matches(selector) {{
    if (selector.startsWith('.')) {{
      return this.className.split(/\\s+/).includes(selector.slice(1));
    }}
    return this.tagName === selector.toUpperCase();
  }}
}}
class FakeTextNode extends FakeNode {{
  constructor(value, ownerDocument) {{
    super('#text', ownerDocument);
    this.textContent = String(value);
  }}
}}
class FakeDocument {{
  createElement(tagName) {{
    return new FakeNode(tagName, this);
  }}
  createTextNode(value) {{
    return new FakeTextNode(value, this);
  }}
}}
function descendants(node) {{
  return node.children.flatMap(child => [child, ...descendants(child)]);
}}
(async () => {{
  const documentRef = new FakeDocument();
  const container = documentRef.createElement('div');
  const events = [];
  const state = {{
    ...guide.createTurnState(),
    cardDisplay: {{
      mode: 'single',
      visible_product_ids: [52],
      max_cards: 1,
      reason: 'product',
    }},
    products: [{{
      id: 52,
      product_id: 52,
      name: '兰蔻菁纯臻颜防晒隔离乳',
      image_url: '/52.png',
      detail_url: 'https://example.com/52',
      price: 299,
    }}],
    presentation: {{
      mode: 'recommendation',
      copy_source: 'model',
      sections: [
        {{ kind: 'summary', copy_text: '先说我的判断。' }},
        {{
          kind: 'product',
          copy_text: '品牌主打轻薄清透。',
          advisor_reason: '通勤更看重清爽时可以优先比较。',
          slot_id: 'p1',
          product_id: 52,
          direct_facts: [
            {{
              fact_id: 'price',
              label: '参考价',
              display_value: '¥299 / 30ml',
            }},
          ],
        }},
        {{
          kind: 'closing',
          copy_text: '综合来看可回看{{{{product:p1}}}}。',
        }},
        {{ kind: 'full_cards' }},
        {{ kind: 'pitfalls' }},
      ],
      card_display: {{
        mode: 'single',
        visible_product_ids: [52],
        max_cards: 1,
        reason: 'product',
      }},
      telemetry: {{
        provider: 'copy-provider',
        model: 'copy-model',
        prompt_tokens: 1,
        completion_tokens: 1,
        total_tokens: 2,
        latency_ms: 1,
        fallback_reason: null,
      }},
    }},
  }};
  await guide.streamPresentation(container, state, {{
    characterDelayMs: 0,
    onFirstCharacter: () => events.push('first_character'),
    onInlineCard: productId => events.push(`card:${{productId}}`),
    getImageUrl: product => product.image_url,
    getDetailUrl: product => product.detail_url,
    formatPrice: product => `¥${{product.price}}`,
  }});
  const root = container.children[0];
  const allNodes = descendants(root);
  const productSection = root.children.find(
    node => node.dataset.sectionKind === 'product'
  );
  const image = allNodes.find(node => node.matches('img'));
  process.stdout.write(JSON.stringify({{
    events,
    imageSrc: image.src,
    inlineIds: allNodes
      .filter(node => node.dataset.guideCardForm === 'inline')
      .map(node => Number(node.dataset.guideProductId)),
    referenceIds: allNodes
      .filter(node => node.dataset.guideProductRef)
      .map(node => Number(node.dataset.guideProductRef)),
    productOrder: productSection.children.map(node => (
      node.matches('h3')
        ? 'title'
        : node.matches('.inline-product-image')
          ? 'inline_card'
          : node.matches('.guide-product-advisor-reason')
            ? 'advisor_reason'
            : node.matches('p')
              ? 'copy'
              : node.matches('dl')
                ? 'facts'
                : 'other'
    )),
  }}));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result == {
        "events": ["first_character", "card:52"],
        "imageSrc": "/52.png",
        "inlineIds": [52],
        "referenceIds": [52],
        "productOrder": [
            "title",
            "inline_card",
            "copy",
            "facts",
            "advisor_reason",
        ],
    }


def test_chat_uses_structured_stream_without_second_markdown_typewriter() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "structuredPresentationPromise" in html
    assert "await structuredPresentationPromise" in html
    assert "XiaoRoPresentation.streamPresentation(" in html
    assert "characterDelayMs: 6" in html
    assert "onFirstCharacter: () =>" in html
    assert "XiaoRoPresentation.dismissThinkingPipeline(" in html
    assert "structuredPresentationStarted" in html
    assert (
        "GUIDE_RUNTIME_MODE\n"
        "                            && deferredPanels.presentationContract"
        in html
    )


def test_structured_stream_keeps_evidence_out_of_final_display() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
class FakeNode {{
  constructor(tagName, ownerDocument) {{
    this.tagName = String(tagName || '').toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.childNodes = this.children;
    this.dataset = {{}};
    this.className = '';
    this.parentNode = null;
    this.textContent = '';
    this.src = '';
  }}
  append(...nodes) {{
    nodes.forEach(node => this.appendChild(node));
  }}
  appendChild(node) {{
    node.parentNode = this;
    this.children.push(node);
    return node;
  }}
  replaceChildren(...nodes) {{
    this.children.splice(0, this.children.length);
    this.append(...nodes);
  }}
  setAttribute(name, value) {{
    this[name] = String(value);
  }}
  matches(selector) {{
    if (selector.startsWith('.')) {{
      return this.className.split(/\\s+/).includes(selector.slice(1));
    }}
    return this.tagName === selector.toUpperCase();
  }}
}}
class FakeTextNode extends FakeNode {{
  constructor(value, ownerDocument) {{
    super('#text', ownerDocument);
    this.textContent = String(value);
  }}
}}
class FakeDocument {{
  createElement(tagName) {{
    return new FakeNode(tagName, this);
  }}
  createTextNode(value) {{
    return new FakeTextNode(value, this);
  }}
}}
function descendants(node) {{
  return node.children.flatMap(child => [child, ...descendants(child)]);
}}
function flattenText(node) {{
  return [node.textContent, ...node.children.map(flattenText)].join(' ');
}}
(async () => {{
  const documentRef = new FakeDocument();
  const container = documentRef.createElement('div');
  const state = {{
    ...guide.createTurnState(),
    cardDisplay: {{
      mode: 'single',
      visible_product_ids: [52],
      max_cards: 1,
      reason: 'product',
    }},
    products: [{{
      id: 52,
      product_id: 52,
      name: '兰蔻菁纯臻颜防晒隔离乳',
      price: 299,
    }}],
    evidence: {{
      merchant_claims: {{
        claims: [{{
          product_id: 52,
          display_claim: '不油腻，肉粉色乳霜质地',
          claim_scope: 'ordinary',
        }}],
      }},
      product_evidence: {{
        packet: {{
          selected: [{{
            evidence: {{
              product_id: 52,
              exact_text: 'SPF50 PA++++，30ml',
              management_label: 'product_specification',
              review_status: 'accepted',
            }},
          }}],
        }},
      }},
      review_evidence: {{
        results: [{{
          product_id: 52,
          evidence: [{{ quote: '上脸比较清爽' }}],
          synthesis: {{ text: '用户反馈更常提到清爽肤感' }},
        }}],
      }},
    }},
    presentation: {{
      mode: 'single_product',
      copy_source: 'model',
      sections: [
        {{ kind: 'summary', copy_text: '先看这一款。' }},
        {{
          kind: 'product',
          copy_text: '品牌主打轻薄清透。',
          advisor_reason: '适合更看重通勤清爽的人。',
          slot_id: 'p1',
          product_id: 52,
          direct_facts: [
            {{
              fact_id: 'price',
              label: '参考价',
              display_value: '¥299 / 30ml',
            }},
          ],
        }},
        {{ kind: 'closing', copy_text: '可以先按日常通勤场景看。' }},
        {{ kind: 'full_cards' }},
        {{ kind: 'pitfalls' }},
      ],
      card_display: {{
        mode: 'single',
        visible_product_ids: [52],
        max_cards: 1,
        reason: 'product',
      }},
      telemetry: {{
        provider: 'copy-provider',
        model: 'copy-model',
        prompt_tokens: 1,
        completion_tokens: 1,
        total_tokens: 2,
        latency_ms: 1,
        fallback_reason: null,
      }},
    }},
  }};
  await guide.streamPresentation(container, state, {{
    characterDelayMs: 0,
    formatPrice: product => `¥${{product.price}}`,
  }});
  const root = container.children[0];
  const evidenceSections = descendants(root)
    .filter(node => node.dataset.sectionKind === 'evidence');
  process.stdout.write(JSON.stringify({{
    evidenceSectionCount: evidenceSections.length,
    text: flattenText(root),
  }}));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result["evidenceSectionCount"] == 0
    assert "展示依据" not in result["text"]
    assert "商品证据" not in result["text"]
    assert "用户反馈" not in result["text"]
    assert "不油腻" not in result["text"]
    assert "SPF50" not in result["text"]
    assert "清爽肤感" not in result["text"]
    assert "品牌主打轻薄清透" in result["text"].replace(" ", "")


def test_chat_skips_legacy_consultation_panel_when_contract_exists() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream = html[
        html.index("const flushDeferredPanels = () =>"):
        html.index("const resolveTypewriterIfIdle")
    ]

    assert "const shouldRenderLegacyConsultationUpdates" in stream
    assert (
        "&& !deferredPanels.presentationContract"
        in stream
    )
    assert (
        "if (\n"
        "                    shouldRenderLegacyConsultationUpdates"
        in stream
    )


def test_chat_skips_legacy_image_panels_when_contract_exists() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream = html[
        html.index("const flushDeferredPanels = () =>"):
        html.index("const resolveTypewriterIfIdle")
    ]

    assert (
        "const guideOwnsPresentation = (\n"
        "                    GUIDE_RUNTIME_MODE\n"
        "                    && Boolean(deferredPanels.presentationContract)\n"
        "                );"
    ) in stream
    assert (
        "if (\n"
        "                    !guideOwnsPresentation\n"
        "                    && deferredPanels.imageObservations.length"
    ) in stream
    assert (
        "if (\n"
        "                    !guideOwnsPresentation\n"
        "                    && deferredPanels.suitabilityData"
    ) in stream
    assert "deferredPanels.imageObservations = [];" in stream
    assert "deferredPanels.suitabilityData = null;" in stream
