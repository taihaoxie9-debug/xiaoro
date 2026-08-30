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


def test_reducer_binds_presentation_to_authoritative_cards() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
let state = guide.createTurnState();
state = guide.reduceGuideEvent(state, {{
  event: 'intent',
  data: {{ intent: 'recommend' }},
}});
state = guide.reduceGuideEvent(state, {{
  event: 'card_display_contract',
  data: {{
    mode: 'recommendation',
    visible_product_ids: [55, 57],
    max_cards: 2,
    reason: 'recommendation',
  }},
}});
state = guide.reduceGuideEvent(state, {{
  event: 'products',
  data: {{
    products: [
      {{ id: 57, product_id: 57, name: 'second' }},
      {{ id: 55, product_id: 55, name: 'first' }},
    ],
  }},
}});
state = guide.reduceGuideEvent(state, {{
  event: 'presentation_contract',
  data: {{
    mode: 'recommendation',
    recommendation_mode: 'explore',
    copy_source: 'fallback',
    sections: [
      {{ kind: 'summary', copy_text: 'summary' }},
      {{
        kind: 'product',
        copy_text: 'first copy',
        slot_id: 'p1',
        product_id: 55,
        direct_facts: [],
      }},
      {{
        kind: 'product',
        copy_text: 'second copy',
        slot_id: 'p2',
        product_id: 57,
        direct_facts: [],
      }},
      {{ kind: 'closing', copy_text: 'closing' }},
      {{ kind: 'pitfalls' }},
      {{ kind: 'full_cards' }},
      {{ kind: 'evidence' }},
    ],
    card_display: {{
      mode: 'recommendation',
      visible_product_ids: [55, 57],
      max_cards: 2,
      reason: 'recommendation',
    }},
    telemetry: {{
      provider: 'disabled',
      model: 'deterministic',
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      latency_ms: 0,
      fallback_reason: 'copywriter_disabled',
    }},
    winner: {{
      status: 'not_applicable',
      winner_product_id: null,
      reason: null,
      fact_ids: [],
      dimension_ids: [],
      tie_reason: null,
    }},
  }},
}});
process.stdout.write(JSON.stringify({{
  ids: guide.resolveVisibleProducts(state).map(item => item.id),
  mode: state.presentation.mode,
  slots: state.presentation.sections
    .filter(item => item.kind === 'product')
    .map(item => item.slot_id),
}}));
"""
    )

    assert result == {
        "ids": [55, 57],
        "mode": "recommendation",
        "slots": ["p1", "p2"],
    }


def test_reducer_requires_typed_recommendation_outcome() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
function errorFor(recommendationMode, ids, winner, closingCopy) {{
  let state = guide.createTurnState();
  state = guide.reduceGuideEvent(state, {{
    event: 'card_display_contract',
    data: {{
      mode: 'recommendation',
      visible_product_ids: ids,
      max_cards: ids.length,
      reason: 'recommendation',
    }},
  }});
  state = guide.reduceGuideEvent(state, {{
    event: 'products',
    data: {{
      products: ids.map(id => ({{
        id,
        product_id: id,
        name: `商品${{id}}`,
      }})),
    }},
  }});
  const presentation = {{
    mode: 'recommendation',
    copy_source: 'fallback',
    sections: [
      {{ kind: 'summary', copy_text: '先看推荐。' }},
      ...ids.map((id, index) => ({{
        kind: 'product',
        slot_id: `p${{index + 1}}`,
        product_id: id,
        copy_text: '商品说明。',
        direct_facts: [],
      }})),
      {{ kind: 'closing', copy_text: closingCopy }},
      {{ kind: 'full_cards' }},
    ],
    comparison_rows: [],
    winner,
    card_display: {{
      mode: 'recommendation',
      visible_product_ids: ids,
      max_cards: ids.length,
      reason: 'recommendation',
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
  }};
  if (recommendationMode !== undefined) {{
    presentation.recommendation_mode = recommendationMode;
  }}
  try {{
    guide.reduceGuideEvent(state, {{
      event: 'presentation_contract',
      data: presentation,
    }});
    return null;
  }} catch (error) {{
    return error.message;
  }}
}}
const notApplicable = {{
  status: 'not_applicable',
  winner_product_id: null,
  reason: null,
  fact_ids: [],
  dimension_ids: [],
  tie_reason: null,
}};
const selected = {{
  status: 'selected',
  winner_product_id: 55,
  reason: '清爽肤感有公开事实支持。',
  fact_ids: ['category:55:texture'],
  dimension_ids: ['texture'],
  tie_reason: null,
}};
process.stdout.write(JSON.stringify({{
  missingMode: errorFor(
    undefined,
    [55, 57],
    notApplicable,
    '再按需求收窄。'
  ),
  exploreWinner: errorFor(
    'explore',
    [55, 57],
    selected,
    '再按需求收窄。'
  ),
  exploreMissingWinner: errorFor(
    'explore',
    [55, 57],
    null,
    '再按需求收窄。'
  ),
  exploreLatentWinner: errorFor(
    'explore',
    [55, 57],
    {{
      ...notApplicable,
      winner_product_id: 55,
    }},
    '再按需求收窄。'
  ),
  fitWithoutWinner: errorFor(
    'fit',
    [55],
    notApplicable,
    null
  ),
  fitMultiple: errorFor(
    'fit',
    [55, 57],
    selected,
    null
  ),
  fitClosingCopy: errorFor(
    'fit',
    [55],
    selected,
    '不应出现第二段结论。'
  ),
}}));
"""
    )

    assert result == {
        "missingMode": "PRESENTATION_RECOMMENDATION_MODE_INVALID",
        "exploreWinner": "PRESENTATION_WINNER_INVALID",
        "exploreMissingWinner": "PRESENTATION_WINNER_INVALID",
        "exploreLatentWinner": "PRESENTATION_WINNER_INVALID",
        "fitWithoutWinner": "PRESENTATION_WINNER_INVALID",
        "fitMultiple": "PRESENTATION_CARD_CONTRACT_MISMATCH",
        "fitClosingCopy": "PRESENTATION_CONTRACT_INVALID",
    }


def test_reducer_fails_closed_on_card_or_section_mismatch() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
function errorFor(presentationIds) {{
  let state = guide.createTurnState();
  state = guide.reduceGuideEvent(state, {{
    event: 'card_display_contract',
    data: {{
      mode: 'single',
      visible_product_ids: [55],
      max_cards: 1,
      reason: 'product',
    }},
  }});
  state = guide.reduceGuideEvent(state, {{
    event: 'products',
    data: {{ products: [{{ id: 55, product_id: 55 }}] }},
  }});
  try {{
    guide.reduceGuideEvent(state, {{
      event: 'presentation_contract',
      data: {{
        mode: 'single_product',
        copy_source: 'fallback',
        sections: [
          {{ kind: 'summary', copy_text: 'summary' }},
          {{
            kind: 'product',
            copy_text: 'copy',
            slot_id: 'p1',
            product_id: presentationIds[0],
            direct_facts: [],
          }},
          {{ kind: 'closing', copy_text: 'closing' }},
          {{ kind: 'pitfalls' }},
          {{ kind: 'full_cards' }},
          {{ kind: 'evidence' }},
        ],
        card_display: {{
          mode: 'single',
          visible_product_ids: presentationIds,
          max_cards: 1,
          reason: 'product',
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
    }});
    return null;
  }} catch (error) {{
    return error.message;
  }}
}}
process.stdout.write(JSON.stringify({{
  mismatch: errorFor([57]),
}}));
"""
    )

    assert result == {
        "mismatch": "PRESENTATION_CARD_CONTRACT_MISMATCH",
    }


def test_zero_card_contract_clears_stale_products() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
let state = guide.createTurnState();
state = guide.reduceGuideEvent(state, {{
  event: 'products',
  data: {{ products: [{{ id: 55, product_id: 55 }}] }},
}});
state = guide.reduceGuideEvent(state, {{
  event: 'card_display_contract',
  data: {{
    mode: 'none',
    visible_product_ids: [],
    max_cards: 0,
    reason: null,
  }},
}});
process.stdout.write(JSON.stringify({{
  products: state.products,
  visible: guide.resolveVisibleProducts(state),
}}));
"""
    )

    assert result == {"products": [], "visible": []}


def test_image_identity_contract_uses_inline_product_and_shelf_binding() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
let state = guide.createTurnState();
state = guide.reduceGuideEvent(state, {{
  event: 'card_display_contract',
  data: {{
    mode: 'single',
    visible_product_ids: [38],
    max_cards: 1,
    reason: 'product',
  }},
}});
state = guide.reduceGuideEvent(state, {{
  event: 'products',
  data: {{
    products: [{{
      id: 38,
      product_id: 38,
      name: '理肤泉新B5多效修护精华',
    }}],
  }},
}});
state = guide.reduceGuideEvent(state, {{
  event: 'presentation_contract',
  data: {{
    mode: 'image_identity',
    copy_source: 'fallback',
    sections: [
      {{ kind: 'observation', copy_text: '已确认图片里的商品。' }},
      {{
        kind: 'product',
        slot_id: 'p1',
        product_id: 38,
        direct_facts: [{{
          fact_id: 'category:38:ingredients_present',
          label: '核心成分',
          display_value: '维生素原B5（泛醇）',
        }}],
      }},
      {{ kind: 'full_cards' }},
    ],
    comparison_rows: [],
    winner: {{
      status: 'not_applicable',
      winner_product_id: null,
      reason: null,
      fact_ids: [],
      dimension_ids: [],
      tie_reason: null,
    }},
    compact_tags: [],
    card_display: {{
      mode: 'single',
      visible_product_ids: [38],
      max_cards: 1,
      reason: 'product',
    }},
    telemetry: {{
      provider: 'disabled',
      model: 'deterministic',
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      latency_ms: 0,
      fallback_reason: 'copywriter_not_called',
    }},
  }},
}});
const view = guide.renderImagePresentation(state);
process.stdout.write(JSON.stringify({{
  inline: view.inlineCardIds,
  shelf: view.fullCardIds,
  facts: view.sections[1].direct_facts,
}}));
"""
    )

    assert result == {
        "inline": [38],
        "shelf": [38],
        "facts": [
            {
                "fact_id": "category:38:ingredients_present",
                "label": "核心成分",
                "display_value": "维生素原B5（泛醇）",
            }
        ],
    }


def test_history_round_trip_excludes_transient_thinking_state() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
let state = guide.createTurnState();
state = guide.reduceGuideEvent(state, {{
  event: 'stage',
  data: {{ stage: 'retrieval', message: 'retrieving' }},
}});
state = guide.reduceGuideEvent(state, {{
  event: 'message',
  data: {{ content: 'answer', done: false }},
}});
const serialized = guide.serializePresentation(state);
const restored = guide.restorePresentation(serialized);
process.stdout.write(JSON.stringify({{
  serialized,
  restoredStages: restored.thinkingStages,
  restoredAnswer: restored.message,
}}));
"""
    )

    assert "thinkingStages" not in result["serialized"]
    assert result["restoredStages"] == []
    assert result["restoredAnswer"] == "answer"
