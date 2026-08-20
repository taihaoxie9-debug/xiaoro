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


def test_slot_substitution_never_interprets_html_or_unknown_slots() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
const input = [
  '<img src=x onerror=alert(1)>',
  '<script>alert(2)</script>',
  '[click](javascript:alert(3))',
  '{{{{product:p1}}}}',
  '{{{{product:p4}}}}',
].join(' ');
const tokens = guide.substituteProductSlots(input, [
  {{ slot_id: 'p1', product_id: 55 }},
]);
process.stdout.write(JSON.stringify(tokens));
"""
    )

    assert result == [
        {
            "type": "text",
            "value": (
                "<img src=x onerror=alert(1)> "
                "<script>alert(2)</script> "
                "[click](javascript:alert(3)) "
            ),
        },
        {
            "type": "product_ref",
            "slot_id": "p1",
            "product_id": 55,
        },
        {"type": "text", "value": " {{product:p4}}"},
    ]


def test_presentation_renderer_has_no_model_html_sink() -> None:
    source = MODULE.read_text(encoding="utf-8")
    start = source.index("function appendCopyTokens(")
    end = source.index("\n        function thinkingStagesForMode", start)
    renderer = source[start:end]

    assert "createTextNode(" in renderer
    assert ".textContent =" in renderer
    assert ".innerHTML" not in renderer
    assert "javascript:" not in renderer
    assert "insertAdjacentHTML" not in renderer
