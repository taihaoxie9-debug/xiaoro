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
