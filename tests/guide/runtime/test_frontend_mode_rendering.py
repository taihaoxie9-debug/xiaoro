from __future__ import annotations

import json
import subprocess
from pathlib import Path


MODULE = Path("app/static/guide-presentation.js").resolve()


def _node(script: str) -> object:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_module_exposes_separate_mode_renderers() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
const names = [
  'renderRecommendationPresentation',
  'renderComparisonPresentation',
  'renderSingleProductPresentation',
  'renderProductKnowledgePresentation',
  'renderGeneralKnowledgePresentation',
  'renderFollowupPresentation',
  'renderImagePresentation',
  'renderConsultationPresentation',
  'renderClarificationPresentation',
  'renderErrorPresentation',
];
process.stdout.write(JSON.stringify(Object.fromEntries(
  names.map(name => [name, typeof guide[name]])
)));
"""
    )

    assert set(result.values()) == {"function"}


def test_mode_dispatch_preserves_mode_specific_section_shape() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
function stateFor(mode, sections) {{
  return {{
    ...guide.createTurnState(),
    cardDisplay: {{
      mode: 'none',
      visible_product_ids: [],
      max_cards: 0,
      reason: null,
    }},
    presentation: {{
      mode,
      copy_source: 'fallback',
      sections,
      card_display: {{
        mode: 'none',
        visible_product_ids: [],
        max_cards: 0,
        reason: null,
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
}}
const generalState = stateFor('general_knowledge', [
    {{ kind: 'general_knowledge', copy_text: '知识结论' }},
]);
generalState.message = 'SPF表示防晒产品对UVB的防护能力。';
const general = guide.renderGeneralKnowledgePresentation(generalState);
const consultation = guide.renderConsultationPresentation(
  stateFor('consultation', [
    {{ kind: 'observation', copy_text: '当前观察' }},
    {{ kind: 'summary', copy_text: '继续确认' }},
  ])
);
process.stdout.write(JSON.stringify({{
  general: general.sections.map(item => item.kind),
  generalCopy: general.sections[0].copy_text,
  consultation: consultation.sections.map(item => item.kind),
}}));
"""
    )

    assert result == {
        "general": ["general_knowledge"],
        "generalCopy": "知识结论",
        "consultation": ["observation", "summary"],
    }


def test_product_dom_order_places_one_inline_card_after_title() -> None:
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
    brand: 'Lancome',
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
          {{ fact_id: 'price', label: '参考价', display_value: '¥299 / 30ml' }},
          {{ fact_id: 'missing', label: '核心成分', display_value: '' }},
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
guide.renderPresentation(container, state, {{
  getImageUrl: product => product.image_url,
  getDetailUrl: product => product.detail_url,
  formatPrice: product => `¥${{product.price}}`,
}});
const root = container.children[0];
const productSection = root.children.find(
  node => node.dataset.sectionKind === 'product'
);
const order = productSection.children.map(node => (
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
));
const allNodes = descendants(root);
const inlineCard = allNodes.find(
  node => node.dataset.guideCardForm === 'inline'
);
const inlineContent = allNodes.find(
  node => node.matches('.guide-inline-product-content')
);
process.stdout.write(JSON.stringify({{
  order,
  inlineIds: allNodes
    .filter(node => node.dataset.guideCardForm === 'inline')
    .map(node => Number(node.dataset.guideProductId)),
  referenceIds: allNodes
    .filter(node => node.dataset.guideProductRef)
    .map(node => Number(node.dataset.guideProductRef)),
  directFactRows: productSection.children
    .find(node => node.matches('dl')).children.length,
  inlineStructure: inlineContent.children.map(node => (
    node.matches('.guide-inline-product-visual')
      ? 'visual'
      : node.matches('.guide-inline-product-info')
        ? 'info'
        : 'other'
  )),
  inlineBrand: allNodes.find(
    node => node.matches('.guide-inline-product-brand')
  ).textContent,
  inlineName: allNodes.find(
    node => node.matches('.guide-inline-product-name')
  ).textContent,
  inlinePrice: allNodes.find(
    node => node.matches('.guide-inline-product-price')
  ).textContent,
}}));
"""
    )

    assert result == {
        "order": [
            "title",
            "inline_card",
            "copy",
            "facts",
            "advisor_reason",
        ],
        "inlineIds": [52],
        "referenceIds": [52],
        "directFactRows": 1,
        "inlineStructure": ["visual", "info"],
        "inlineBrand": "Lancome",
        "inlineName": "兰蔻菁纯臻颜防晒隔离乳",
        "inlinePrice": "¥299",
    }


def test_comparison_renders_only_contract_rows_in_horizontal_table() -> None:
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
const documentRef = new FakeDocument();
const container = documentRef.createElement('div');
const state = {{
  ...guide.createTurnState(),
  cardDisplay: {{
    mode: 'comparison',
    visible_product_ids: [53, 55],
    max_cards: 2,
    reason: 'comparison',
  }},
  products: [
    {{
      id: 53,
      product_id: 53,
      name: '商品甲',
      display_name: '甲公开名',
      image_url: '/53.png',
      detail_url: 'https://example.com/53',
      price: 100,
    }},
    {{
      id: 55,
      product_id: 55,
      name: '商品乙',
      display_name: '乙公开名',
      image_url: '/55.png',
      detail_url: 'https://example.com/55',
      price: 200,
    }},
  ],
  presentation: {{
    mode: 'comparison',
    copy_source: 'fallback',
    winner: {{
      status: 'selected',
      winner_product_id: 53,
      reason: '第一款在清爽维度有明确事实支持。',
      fact_ids: ['t53'],
      dimension_ids: ['texture.refreshing'],
      tie_reason: null,
    }},
    sections: [
      {{ kind: 'summary', copy_text: '先看两款路线。' }},
      {{ kind: 'comparison', copy_text: '横向看共同信息。' }},
      {{ kind: 'full_cards' }},
    ],
    comparison_rows: [
      {{
        dimension_id: 'brand_positioning',
        label: '品牌主打',
        cells: [
          {{ product_id: 53, value: '轻薄防水', fact_ids: ['f53'], state: 'known' }},
          {{ product_id: 55, value: '修护保湿', fact_ids: ['f55'], state: 'known' }},
        ],
      }},
      {{
        dimension_id: 'texture.refreshing',
        label: '清爽',
        cells: [
          {{ product_id: 53, value: '清爽轻薄', fact_ids: ['t53'], state: 'known' }},
          {{ product_id: 55, value: '不符合：丰润乳霜', fact_ids: ['t55'], state: 'conflict' }},
        ],
      }},
      {{
        dimension_id: 'reference_price',
        label: '参考价',
        cells: [
          {{ product_id: 53, value: '¥100 / 50ml', fact_ids: ['p53'], state: 'known' }},
          {{ product_id: 55, value: '¥200 / 30ml', fact_ids: ['p55'], state: 'known' }},
        ],
      }},
    ],
    card_display: {{
      mode: 'comparison',
      visible_product_ids: [53, 55],
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
guide.renderPresentation(container, state, {{
  getImageUrl: product => product.image_url,
  getDetailUrl: product => product.detail_url,
  formatPrice: product => `¥${{product.price}}`,
}});
const allNodes = descendants(container);
const tables = allNodes.filter(
  node => node.tagName === 'TABLE'
);
const table = tables[0];
const headRow = table?.children[0]?.children[0];
const bodyRows = table?.children[1]?.children || [];
const winner = allNodes.find(
  node => node.dataset.guideWinnerStatus === 'selected'
);
process.stdout.write(JSON.stringify({{
  tableCount: tables.length,
  tableClass: table?.className || null,
  headers: headRow?.children.map(node => node.textContent) || [],
  rows: bodyRows.map(
    row => row.children.map(node => node.textContent)
  ),
  winnerStatus: winner?.dataset.guideWinnerStatus || null,
  winnerParts: winner?.children.map(node => node.textContent) || [],
}}));
"""
    )

    assert result == {
        "tableCount": 1,
        "tableClass": "compare-table guide-comparison-table",
        "headers": ["对比项", "甲公开名", "乙公开名"],
        "rows": [
            [
                "品牌主打",
                "轻薄防水",
                "修护保湿",
            ],
            [
                "清爽",
                "清爽轻薄",
                "不符合：丰润乳霜",
            ],
            ["参考价", "¥100 / 50ml", "¥200 / 30ml"],
        ],
        "winnerStatus": "selected",
        "winnerParts": [
            "综合判断：",
            "甲公开名。第一款在清爽维度有明确事实支持。",
        ],
    }
