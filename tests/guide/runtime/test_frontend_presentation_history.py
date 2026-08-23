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


def test_history_restore_preserves_sections_cards_and_references_once() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
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
  data: {{
    products: [{{
      id: 55,
      product_id: 55,
      name: 'product',
      image_url: '/55.png',
    }}],
  }},
}});
state = guide.reduceGuideEvent(state, {{
  event: 'presentation_contract',
  data: {{
    mode: 'single_product',
    copy_source: 'fallback',
    sections: [
      {{ kind: 'summary', copy_text: 'summary' }},
      {{ kind: 'judgement', copy_text: '使用判断' }},
      {{ kind: 'full_cards' }},
    ],
    card_display: {{
      mode: 'single',
      visible_product_ids: [55],
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
state = guide.reduceGuideEvent(state, {{
  event: 'stage',
  data: {{ stage: 'copy', message: 'copying' }},
}});
const serialized = guide.serializePresentation(state);
const restored = guide.restorePresentation(
  JSON.parse(JSON.stringify(serialized))
);
const view = guide.renderSingleProductPresentation(restored);
process.stdout.write(JSON.stringify({{
  sections: view.sections.map(item => item.kind),
  inline: view.inlineCardIds,
  full: view.fullCardIds,
  refs: view.productRefs,
  stages: restored.thinkingStages,
}}));
"""
    )

    assert result == {
        "sections": [
            "summary",
            "judgement",
            "full_cards",
        ],
        "inline": [],
        "full": [55],
        "refs": [],
        "stages": [],
    }


def test_snapshot_history_drops_thinking_but_keeps_presentation_dom() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    start = html.index("function sanitizeSnapshotHtml(snapshot)")
    end = html.index("\n\n        function loadStoredJson", start)
    source = html[start:end]

    assert ".guide-thinking-pipeline" in source
    assert ".guide-presentation-root" not in source
    assert "presentation:" in html
