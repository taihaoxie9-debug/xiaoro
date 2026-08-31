from __future__ import annotations

import json
import subprocess
from pathlib import Path


MODULE = Path("app/static/guide-presentation.js").resolve()
CHAT_HTML = Path("app/static/chat.html")
DEMO_FIXTURE = Path("app/static/guide-demo-fixture.js").resolve()


def _node(script: str) -> object:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_renderer_accepts_four_product_comparison_contract() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
let state = guide.createTurnState();
state = guide.reduceGuideEvent(state, {{
  event: 'card_display_contract',
  data: {{
    mode: 'comparison',
    visible_product_ids: [51, 52, 53, 54],
    max_cards: 4,
    reason: 'comparison',
  }},
}});
process.stdout.write(JSON.stringify(state.cardDisplay));
"""
    )

    assert result["visible_product_ids"] == [51, 52, 53, 54]
    assert result["max_cards"] == 4


def test_demo_fixture_starts_image_chain_at_identity_after_text_turn() -> None:
    result = _node(
        f"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync({json.dumps(str(DEMO_FIXTURE))}, 'utf8'));

async function readEvents(response) {{
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];
  while (true) {{
    const {{ done, value }} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {{ stream: true }});
    const blocks = buffer.split('\\n\\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {{
      const name = block.match(/^event: (.+)$/m)?.[1];
      const data = block.match(/^data: (.+)$/m)?.[1];
      if (name && data) events.push([name, JSON.parse(data)]);
    }}
  }}
  return events;
}}

(async () => {{
  const sessionId = 'shared-demo-session';
  await readEvents(window.XiaoRoDemoFixture.createResponse({{
    sessionId,
    images: [],
  }}));
  const imageEvents = await readEvents(
    window.XiaoRoDemoFixture.createResponse({{
      sessionId,
      images: [{{ name: 'recording-product38.png' }}],
    }})
  );
  const intent = imageEvents.find(([name]) => name === 'intent')[1].intent;
  const productIds = imageEvents.find(
    ([name]) => name === 'products'
  )[1].products.map(product => product.product_id);
  const presentation = imageEvents.find(
    ([name]) => name === 'presentation_contract'
  )[1];
  const product = presentation.sections.find(
    section => section.kind === 'product'
  );
  process.stdout.write(JSON.stringify({{
    intent,
    productIds,
    observation: presentation.sections.find(
      section => section.kind === 'observation'
    ).copy_text,
    productFacts: product.direct_facts,
  }}));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result == {
        "intent": "image_identity",
        "productIds": [38],
        "observation": (
            "这张图是理肤泉新 B5 多效修护精华，30ml。它的路线"
            "很明确：把修护、补水保湿和舒缓放在一起做，适合拿来"
            "应对皮肤状态不稳定、容易泛红的时候。"
        ),
        "productFacts": [
            {
                "fact_id": "demo:38:direct:1",
                "label": "参考价 / 规格",
                "display_value": "¥294 / 30ml",
            },
            {
                "fact_id": "demo:38:direct:2",
                "label": "品牌主打",
                "display_value": "修护、补水保湿、舒缓",
            },
            {
                "fact_id": "demo:38:direct:3",
                "label": "核心成分",
                "display_value": "维生素原 B5（泛醇）",
            },
            {
                "fact_id": "demo:38:direct:4",
                "label": "质地",
                "display_value": "清润精华，轻薄好吸收",
            },
        ],
    }


def test_demo_fixture_binds_image_recommendation_price_to_a_specification() -> None:
    result = _node(
        f"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync({json.dumps(str(DEMO_FIXTURE))}, 'utf8'));

async function readEvents(response) {{
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];
  while (true) {{
    const {{ done, value }} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {{ stream: true }});
    const blocks = buffer.split('\\n\\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {{
      const name = block.match(/^event: (.+)$/m)?.[1];
      const data = block.match(/^data: (.+)$/m)?.[1];
      if (name && data) events.push([name, JSON.parse(data)]);
    }}
  }}
  return events;
}}

(async () => {{
  const sessionId = 'image-recommendation-price';
  await readEvents(window.XiaoRoDemoFixture.createResponse({{
    sessionId,
    images: [{{ name: 'recording-product38.png' }}],
  }}));
  const events = await readEvents(
    window.XiaoRoDemoFixture.createResponse({{
      sessionId,
      images: [],
    }})
  );
  const product = events.find(
    ([name]) => name === 'products'
  )[1].products;
  const presentation = events.find(
    ([name]) => name === 'presentation_contract'
  )[1];
  process.stdout.write(JSON.stringify({{
    productIds: product.map(item => item.product_id),
    specifications: product.map(item => item.specification),
    winnerStatus: presentation.winner.status,
    winnerProductId: presentation.winner.winner_product_id,
    summary: presentation.sections.find(
      section => section.kind === 'summary'
    ).copy_text,
    productCopy: presentation.sections
      .filter(section => section.kind === 'product')
      .map(section => section.copy_text),
    closing: presentation.sections.find(
      section => section.kind === 'closing'
    ).copy_text,
  }}));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result == {
        "productIds": [42, 91],
        "specifications": ["30ml", "50ml"],
        "winnerStatus": "not_applicable",
        "winnerProductId": None,
        "summary": (
            "图片里的 B5 已经确认，这轮不把它重复算进候选。"
            "我按你说的换季泛红和 T 区出油，挑两款同为精华的"
            "替代方向。"
        ),
        "productCopy": [
            (
                "夸迪稳肌轻龄悬油次抛精华走的是悬油、水油双载和"
                "微囊的次抛路线，重点是轻盈不黏、吸收快和不搓泥。"
            ),
            (
                "玉泽屏障修护精华乳更偏基础保湿、修护和舒缓，"
                "质地更接近乳霜型精华。"
            ),
        ],
        "closing": (
            "两款分别偏轻盈肤感和基础屏障养护，"
            "可以再按你更在意的方向收窄。"
        ),
    }


def test_demo_fixture_image_comparison_returns_to_b5_without_stale_copy() -> None:
    result = _node(
        f"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync({json.dumps(str(DEMO_FIXTURE))}, 'utf8'));

async function readEvents(response) {{
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];
  while (true) {{
    const {{ done, value }} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {{ stream: true }});
    const blocks = buffer.split('\\n\\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {{
      const name = block.match(/^event: (.+)$/m)?.[1];
      const data = block.match(/^data: (.+)$/m)?.[1];
      if (name && data) events.push([name, JSON.parse(data)]);
    }}
  }}
  return events;
}}

(async () => {{
  const sessionId = 'image-comparison';
  await readEvents(window.XiaoRoDemoFixture.createResponse({{
    sessionId,
    images: [{{ name: 'recording-product38.png' }}],
  }}));
  await readEvents(window.XiaoRoDemoFixture.createResponse({{
    sessionId,
    images: [],
    message: '给我找两款相似的，我最近换季泛红，T区出油。',
  }}));
  const events = await readEvents(
    window.XiaoRoDemoFixture.createResponse({{
      sessionId,
      images: [],
      message: '图片里的 B5 和第一款哪个更适合我的肤质？',
    }})
  );
  const presentation = events.find(
    ([name]) => name === 'presentation_contract'
  )[1];
  process.stdout.write(JSON.stringify({{
    productIds: events.find(
      ([name]) => name === 'products'
    )[1].products.map(product => product.product_id),
    observation: presentation.sections.find(
      section => section.kind === 'summary'
    ).copy_text,
    winnerProductId: presentation.winner.winner_product_id,
    winnerReason: presentation.winner.reason,
  }}));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result == {
        "productIds": [38, 42],
        "observation": (
            "结合你说的 T 区出油和换季泛红，当前更像偏油的"
            "敏感倾向，修护舒缓优先。"
        ),
        "winnerProductId": 38,
        "winnerReason": (
            "在当前画像下，B5 的修护和舒缓方向更贴近你描述的"
            "换季泛红；夸迪的优势是轻盈不黏，更适合把 T 区出油"
            "和肤感放在第一优先级的时候。"
        ),
    }


def test_demo_fixture_routes_final_comparison_question_without_turn_count() -> None:
    result = _node(
        f"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync({json.dumps(str(DEMO_FIXTURE))}, 'utf8'));

async function readEvents(response) {{
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];
  while (true) {{
    const {{ done, value }} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {{ stream: true }});
    const blocks = buffer.split('\\n\\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {{
      const name = block.match(/^event: (.+)$/m)?.[1];
      const data = block.match(/^data: (.+)$/m)?.[1];
      if (name && data) events.push([name, JSON.parse(data)]);
    }}
  }}
  return events;
}}

(async () => {{
  const events = await readEvents(
    window.XiaoRoDemoFixture.createResponse({{
      sessionId: 'direct-comparison-question',
      images: [],
      message: '回到刚才的推荐，第一款和第二款哪个更适合我的肤质？',
    }})
  );
  const intent = events.find(([name]) => name === 'intent')[1].intent;
  const contract = events.find(
    ([name]) => name === 'presentation_contract'
  )[1];
  const texture = contract.comparison_rows.find(
    row => row.label === '质地侧重点'
  ).cells[0].value;
  process.stdout.write(JSON.stringify({{
    intent,
    winnerProductId: contract.winner.winner_product_id,
    texture,
  }}));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result == {
        "intent": "comparison",
        "winnerProductId": 33,
        "texture": "清润液体，偏修护护理",
    }


def test_demo_fixture_recommendation_stays_within_the_stated_budget() -> None:
    result = _node(
        f"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync({json.dumps(str(DEMO_FIXTURE))}, 'utf8'));

async function readEvents(response) {{
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];
  while (true) {{
    const {{ done, value }} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {{ stream: true }});
    const blocks = buffer.split('\\n\\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {{
      const name = block.match(/^event: (.+)$/m)?.[1];
      const data = block.match(/^data: (.+)$/m)?.[1];
      if (name && data) events.push([name, JSON.parse(data)]);
    }}
  }}
  return events;
}}

(async () => {{
  const events = await readEvents(
    window.XiaoRoDemoFixture.createResponse({{
      sessionId: 'budgeted-recommendation',
      images: [],
      message: '给我推荐900~1100以内的精华，我是油敏肌',
    }})
  );
  const products = events.find(
    ([name]) => name === 'products'
  )[1].products;
  const contract = events.find(
    ([name]) => name === 'presentation_contract'
  )[1];
  process.stdout.write(JSON.stringify({{
    productIds: products.map(product => product.product_id),
    prices: products.map(product => product.price),
    specifications: products.map(product => product.specification),
    advisorReasons: contract.sections
      .filter(section => section.kind === 'product')
      .map(section => section.advisor_reason),
    summary: contract.sections.find(
      section => section.kind === 'summary'
    ).copy_text,
    productFacts: contract.sections
      .filter(section => section.kind === 'product')
      .map(section => section.direct_facts),
    productCopy: contract.sections
      .filter(section => section.kind === 'product')
      .map(section => section.copy_text),
  }}));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result == {
        "productIds": [33, 39, 35],
        "prices": [968, 1080, 1050],
        "specifications": ["50ml", "30ml", "30ml"],
        "advisorReasons": [
            (
                "它把夜间修护、舒缓和抗老放在同一条线上，"
                "是这一组里很典型的修护向选择。"
            ),
            (
                "它把修护抗老做得更偏轻盈肤感，和小棕瓶是"
                "两种取向。"
            ),
            (
                "它提供的是偏紧致和丰盈的路线，不和前两款"
                "抢同一个位置。"
            ),
        ],
        "summary": (
            "900 到 1100 这个预算，先看三条不同的精华路线："
            "小棕瓶偏夜间修护和舒缓；绿宝瓶是轻盈凝露的修护"
            "抗老路线；紫米精华更侧重保湿、紧致和丰盈感。先按"
            "自己更在意的那一项缩小范围。"
        ),
        "productFacts": [
            [
                {
                    "fact_id": "demo:33:direct:1",
                    "label": "参考价 / 规格",
                    "display_value": "¥968 / 50ml",
                },
                {
                    "fact_id": "demo:33:direct:2",
                    "label": "品牌主打",
                    "display_value": "强韧屏障、舒缓泛红与抗老",
                },
                {
                    "fact_id": "demo:33:direct:3",
                    "label": "核心成分",
                    "display_value": (
                        "二裂酵母发酵产物、透明质酸、三肽-32"
                    ),
                },
                {
                    "fact_id": "demo:33:direct:4",
                    "label": "质地",
                    "display_value": "清润琥珀色液体，轻薄不粘腻",
                },
            ],
            [
                {
                    "fact_id": "demo:39:direct:1",
                    "label": "参考价 / 规格",
                    "display_value": "¥1080 / 30ml",
                },
                {
                    "fact_id": "demo:39:direct:2",
                    "label": "品牌主打",
                    "display_value": "修护抗老、轻盈凝露质地",
                },
                {
                    "fact_id": "demo:39:direct:3",
                    "label": "核心成分",
                    "display_value": "海茴香精粹、植物抗老多肽",
                },
                {
                    "fact_id": "demo:39:direct:4",
                    "label": "质地",
                    "display_value": "轻盈凝露，不搓泥",
                },
            ],
            [
                {
                    "fact_id": "demo:35:direct:1",
                    "label": "参考价 / 规格",
                    "display_value": "¥1050 / 30ml",
                },
                {
                    "fact_id": "demo:35:direct:2",
                    "label": "品牌主打",
                    "display_value": "保湿润泽、紧致淡纹",
                },
                {
                    "fact_id": "demo:35:direct:3",
                    "label": "核心成分",
                    "display_value": (
                        "玻色因、紫米提取物、甘草酸二钾与三重透明质酸"
                    ),
                },
            ],
        ],
        "productCopy": [
            (
                "第 7 代小棕瓶把强韧屏障、舒缓泛红和抗老放在"
                "主打位置。它是清润琥珀色的液体精华，包装建议"
                "早晚用在面霜前。"
            ),
            (
                "第 6 代绿宝瓶走的是更轻盈的修护抗老路线。"
                "海茴香精粹、植物抗老多肽和 EXO SAM 是它的核心"
                "叙事，肤感则是轻盈凝露、偏不搓泥。"
            ),
            (
                "紫米精华更偏保湿打底和紧致丰盈。玻色因、紫米"
                "提取物和三重透明质酸是它的核心成分，产品主打"
                "保湿润泽、紧致淡纹。"
            ),
        ],
    }


def test_demo_fixture_confirmation_defers_comparison_scope() -> None:
    result = _node(
        f"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync({json.dumps(str(DEMO_FIXTURE))}, 'utf8'));

async function readEvents(response) {{
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];
  while (true) {{
    const {{ done, value }} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {{ stream: true }});
    const blocks = buffer.split('\\n\\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {{
      const name = block.match(/^event: (.+)$/m)?.[1];
      const data = block.match(/^data: (.+)$/m)?.[1];
      if (name && data) events.push([name, JSON.parse(data)]);
    }}
  }}
  return events;
}}

(async () => {{
  const events = await readEvents(
    window.XiaoRoDemoFixture.createResponse({{
      sessionId: 'profile-confirmation',
      images: [],
      message: '确认',
    }})
  );
  const presentation = events.find(
    ([name]) => name === 'presentation_contract'
  )[1];
  process.stdout.write(JSON.stringify(
    presentation.sections[0].copy_text
  ));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result == (
        "好，记下了。"
    )


def test_demo_fixture_product_knowledge_uses_public_advisor_language() -> None:
    result = _node(
        f"""
const fs = require('fs');
global.window = global;
eval(fs.readFileSync({json.dumps(str(DEMO_FIXTURE))}, 'utf8'));

async function readEvents(response) {{
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];
  while (true) {{
    const {{ done, value }} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {{ stream: true }});
    const blocks = buffer.split('\\n\\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {{
      const name = block.match(/^event: (.+)$/m)?.[1];
      const data = block.match(/^data: (.+)$/m)?.[1];
      if (name && data) events.push([name, JSON.parse(data)]);
    }}
  }}
  return events;
}}

(async () => {{
  const events = await readEvents(
    window.XiaoRoDemoFixture.createResponse({{
      sessionId: 'product-knowledge',
      images: [],
      message: '第二款的质地适合什么肤质？',
    }})
  );
  const presentation = events.find(
    ([name]) => name === 'presentation_contract'
  )[1];
  process.stdout.write(JSON.stringify(
    presentation.sections.map(section => section.copy_text)
  ));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result == [
        (
            "第二款是赫莲娜绿宝瓶。它的质地是轻盈凝露，主打"
            "轻薄、不搓泥；对于容易觉得精华闷、又想兼顾修护和"
            "抗老的人，会更容易接受。"
        ),
        (
            "海茴香精粹、植物抗老多肽和 EXO SAM 构成了它的"
            "修护抗老主线，品牌也把它描述为多肤质可用、偏油皮"
            "友好。"
        ),
        None,
    ]


def test_saved_product_shelf_retains_bound_specification() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    start = html.index("function saveProductsToShelf(products)")
    end = html.index("\n        function renderProductShelf()", start)
    saver = html[start:end]

    assert "specification: product.specification" in saver
    assert (
        "price_specification_alignment: "
        "product.price_specification_alignment"
        in saver
    )
    assert "variant_scope: product.variant_scope" in saver
    assert "display_name: product.display_name" in saver
    assert "image_source_sha256: product.image_source_sha256" in saver


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
      recommendation_mode: 'fit',
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
          copy_text: null,
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
      winner: {{
        status: 'selected',
        winner_product_id: 52,
        reason: '轻薄肤感更贴近日常通勤。',
        fact_ids: ['f52'],
        dimension_ids: ['texture'],
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
    shelfIds: allNodes
      .filter(node => node.dataset.guideCardForm === 'shelf')
      .map(node => Number(node.dataset.guideProductId)),
    shelfAdvisorReasons: allNodes
      .filter(node => node.dataset.guideCardForm === 'shelf')
      .flatMap(descendants)
      .filter(node => node.matches('.guide-product-advisor-reason'))
      .length,
    shelfDetailLinks: allNodes
      .filter(node => node.matches('.guide-product-detail-link'))
      .map(node => ({{
        href: node.href,
        text: node.textContent,
      }})),
    shelfFavoriteIds: allNodes
      .filter(node => node.dataset.favoriteProductId)
      .map(node => Number(node.dataset.favoriteProductId)),
    winnerTexts: allNodes
      .filter(node => node.matches('.guide-winner-conclusion'))
      .map(node => descendants(node)
        .map(child => child.textContent)
        .filter(Boolean)
        .join('')),
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
        "shelfIds": [52],
        "shelfAdvisorReasons": 0,
        "shelfDetailLinks": [
            {
                "href": "https://example.com/52",
                "text": "去商品页查实时价",
            },
        ],
        "shelfFavoriteIds": [52],
        "winnerTexts": [
            "兰蔻菁纯臻颜防晒隔离乳。轻薄肤感更贴近日常通勤。",
        ],
        "referenceIds": [],
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
    assert "const guideOwnsPresentation = GUIDE_RUNTIME_MODE;" in html
    assert "GUIDE_RESPONSE_CONTRACT_INVALID" in html
    finalize_start = html.index(
        "const finalizeAfterTypewriter = async () =>"
    )
    finalize_end = html.index(
        "const renderStage =",
        finalize_start,
    )
    finalize = html[finalize_start:finalize_end]
    assert (
        "flushDeferredPanels();\n"
        "                autoScrollToBottom(true);"
    ) in finalize


def test_general_knowledge_citations_render_after_terminal_validation() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    validator_start = html.index(
        "function validateGuideTerminalPayload({"
    )
    validator_end = html.index(
        "\n\n        // 发送流式消息",
        validator_start,
    )
    validator = html[validator_start:validator_end]
    stream_start = html.index("async function sendStreamingMessage(")
    stream_end = html.index(
        "\n        function buildDetailedProductReason",
        stream_start,
    )
    stream = html[stream_start:stream_end]
    flush_start = stream.index("const flushDeferredPanels = () =>")
    flush_end = stream.index(
        "\n\n            const resolveTypewriterIfIdle",
        flush_start,
    )
    flush = stream[flush_start:flush_end]
    finalize_start = stream.index(
        "const finalizeAfterTypewriter = async () =>"
    )
    finalize_end = stream.index("const renderStage =", finalize_start)
    finalize = stream[finalize_start:finalize_end]

    assert "validateGeneralKnowledgePayload(generalKnowledge)" in validator
    assert (
        "displayGeneralKnowledgeCitations(\n"
        "                        deferredPanels.generalKnowledge.citations\n"
        "                    );"
    ) in flush
    assert (
        flush.index("displayGeneralKnowledgeCitations(")
        < flush.index("deferredPanels.generalKnowledge = null")
    )
    assert (
        finalize.index("flushDeferredPanels();")
        < finalize.index("autoScrollToBottom(true);")
    )


def test_chat_guide_path_rejects_message_event_as_second_body() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    handler_start = html.index("const handleSseEvent = (eventName, data) =>")
    handler_end = html.index("\n            while (true)", handler_start)
    handler = html[handler_start:handler_end]

    message_start = handler.index("if (eventName === 'message')")
    message_end = handler.index(
        "} else if (eventName === 'stage')",
        message_start,
    )
    contract_message_branch = handler[message_start:message_end]
    assert "GUIDE_RUNTIME_MODE" in contract_message_branch
    assert "GUIDE_RESPONSE_CONTRACT_INVALID" in contract_message_branch


def test_chat_clarification_uses_typed_clarify_event() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    handler_start = html.index("const handleSseEvent = (eventName, data) =>")
    handler_end = html.index("\n            while (true)", handler_start)
    handler = html[handler_start:handler_end]

    clarify_start = handler.index("eventName === 'clarify'")
    clarify_end = handler.index(
        "} else if (eventName === 'stage')",
        clarify_start,
    )
    clarify_branch = handler[clarify_start:clarify_end]
    assert "data.question" in clarify_branch
    assert "enqueueAssistantText" in clarify_branch


def test_chat_guide_clarification_requires_typed_event() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    handler_start = html.index("const handleSseEvent = (eventName, data) =>")
    handler_end = html.index("\n            while (true)", handler_start)
    handler = html[handler_start:handler_end]
    clarify_start = handler.index("eventName === 'clarify'")
    clarify_end = handler.index(
        "} else if (eventName === 'stage')",
        clarify_start,
    )
    flush_start = html.index("const flushDeferredPanels = () =>")
    flush_end = html.index(
        "const resolveTypewriterIfIdle",
        flush_start,
    )

    assert "clarificationReceived: false" in html
    assert (
        "deferredPanels.clarificationReceived = true"
        in handler[clarify_start:clarify_end]
    )
    assert (
        "&& deferredPanels.clarificationReceived"
        in html[flush_start:flush_end]
    )


def test_chat_guide_clarification_does_not_reinterpret_route_intent() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    flush_start = html.index("const flushDeferredPanels = () =>")
    flush_end = html.index(
        "const resolveTypewriterIfIdle",
        flush_start,
    )
    flush = html[flush_start:flush_end]

    clarification_start = flush.index(
        "const isGuideClarification = ("
    )
    clarification_end = flush.index(
        ");",
        clarification_start,
    )
    clarification_expression = flush[
        clarification_start:clarification_end
    ]
    assert "deferredPanels.clarificationReceived" in (
        clarification_expression
    )
    assert "deferredPanels.intent === 'clarify'" not in (
        clarification_expression
    )


def test_chat_guide_terminal_validation_uses_typed_clarification_kind() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    end_start = html.index(
        "} else if (eventName === 'end') {"
    )
    end_end = html.index(
        "if (\n                        !Number.isInteger",
        end_start,
    )
    end_branch = html[end_start:end_end]

    assert (
        "deferredPanels.clarificationReceived"
        in end_branch
    )
    normalized_end_branch = " ".join(end_branch.split())
    assert (
        "deferredPanels.clarificationReceived"
        " ? 'clarify' : deferredPanels.intent"
        in normalized_end_branch
    )


def test_chat_contract_path_does_not_render_a_second_product_shelf() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    start = html.index("const flushDeferredPanels = () =>")
    end = html.index("const resolveTypewriterIfIdle", start)
    flush = html[start:end]

    assert "GUIDE_RESPONSE_CONTRACT_INVALID" in flush
    assert "const guideOwnsPresentation = GUIDE_RUNTIME_MODE;" in flush
    assert "saveProductsToShelf(contractProducts);" in flush
    assert (
        "} else {\n"
        "                            displayProducts("
    ) in flush


def test_product_knowledge_coverage_stream_appends_bound_evidence_section() -> None:
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
  let state = {{
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
          selected: [
            {{
              evidence: {{
                evidence_id: '{"a" * 64}',
                product_id: 52,
                exact_text: 'SPF50 PA++++，30ml',
                management_label: 'product_specification',
                review_status: 'accepted',
              }},
            }},
            {{
              evidence: {{
                evidence_id: '{"b" * 64}',
                product_id: 52,
                exact_text: '同商品但答案未引用的证据',
                management_label: 'product_specification',
                review_status: 'accepted',
              }},
            }},
          ],
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
      mode: 'product_knowledge',
      copy_source: 'model',
      sections: [
        {{ kind: 'summary', copy_text: '先看这一款。' }},
        {{
          kind: 'answer',
          copy_text: '已确认这款的防晒标识。',
          used_fact_ids: ['evidence:{"a" * 64}'],
          direct_facts: [],
        }},
        {{ kind: 'full_cards' }},
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
  state = guide.reduceGuideEvent(state, {{
    event: 'product_evidence',
    data: state.evidence.product_evidence,
  }});
  await guide.streamPresentation(container, state, {{
    characterDelayMs: 0,
    formatPrice: product => `¥${{product.price}}`,
  }});
  const root = container.children[0];
  const evidenceSections = descendants(root)
    .filter(node => node.dataset.sectionKind === 'evidence');
  const evidenceRows = descendants(root)
    .filter(node => node.dataset.evidenceId);
  process.stdout.write(JSON.stringify({{
    evidenceSectionCount: evidenceSections.length,
    sectionOrder: root.children
      .filter(node => node.dataset.sectionKind)
      .map(node => node.dataset.sectionKind),
    evidenceIds: evidenceRows.map(node => node.dataset.evidenceId),
    evidenceProductIds: evidenceRows.map(
      node => Number(node.dataset.guideProductId)
    ),
    text: flattenText(root),
  }}));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    )

    assert result["evidenceSectionCount"] == 1
    assert result["sectionOrder"] == [
        "summary",
        "answer",
        "full_cards",
        "evidence",
    ]
    assert result["evidenceIds"] == ["a" * 64]
    assert result["evidenceProductIds"] == [52]
    assert "展示依据" in result["text"]
    assert "商品证据" in result["text"]
    assert "SPF50" in result["text"]
    assert "用户反馈" not in result["text"]
    assert "不油腻" not in result["text"]
    assert "清爽肤感" not in result["text"]
    assert "同商品但答案未引用的证据" not in result["text"]
    assert "已确认这款的防晒标识" in result["text"].replace(" ", "")


def test_non_product_knowledge_mode_keeps_evidence_layer_hidden() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "view.mode === 'product_knowledge'" in source


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


def test_chat_guide_mode_never_renders_legacy_consultation_or_pitfalls() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream = html[
        html.index("const flushDeferredPanels = () =>"):
        html.index("const resolveTypewriterIfIdle")
    ]

    assert (
        "const shouldRenderLegacyConsultationUpdates = (\n"
        "                    !guideOwnsPresentation"
    ) in stream
    assert (
        "if (\n"
        "                    !guideOwnsPresentation\n"
        "                    && deferredPanels.pitfalls.length"
    ) in stream


def test_chat_skips_legacy_image_panels_when_contract_exists() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream = html[
        html.index("const flushDeferredPanels = () =>"):
        html.index("const resolveTypewriterIfIdle")
    ]

    assert "const guideOwnsPresentation = GUIDE_RUNTIME_MODE;" in stream
    assert "GUIDE_RESPONSE_CONTRACT_INVALID" in stream
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
