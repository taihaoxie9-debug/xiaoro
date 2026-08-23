from __future__ import annotations

from hashlib import sha256
import json
import subprocess
from pathlib import Path


CHAT_HTML = Path("app/static/chat.html")
MODULE = Path("app/static/guide-presentation.js").resolve()


def _node(script: str) -> object:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_thinking_stage_contract_is_mode_specific_and_bounded() -> None:
    result = _node(
        f"""
const guide = require({json.dumps(str(MODULE))});
const modes = [
  'recommend',
  'comparison',
  'knowledge',
  'image_identity',
  'image_compare',
  'consultation_entry',
  'clarify',
  'error',
];
process.stdout.write(JSON.stringify(Object.fromEntries(
  modes.map(mode => [mode, guide.thinkingStagesForMode(mode)])
)));
"""
    )

    assert result["recommend"] == [
        "understanding",
        "retrieval",
        "decision",
        "copy",
    ]
    assert result["comparison"][-1] == "copy"
    assert result["knowledge"] == [
        "understanding",
        "retrieval",
        "copy",
    ]
    assert result["image_identity"][0] == "image_observation"
    assert result["image_compare"][-1] == "copy"
    assert result["consultation_entry"] == [
        "state",
        "observation",
        "copy",
    ]
    assert result["clarify"] == []
    assert result["error"] == []
    assert all(len(stages) <= 4 for stages in result.values())


def test_thinking_pipeline_auto_advances_to_final_stage() -> None:
    result = _node(
        f"""
let timers = [];
globalThis.setTimeout = (callback, ms) => {{
  timers.push({{ callback, ms }});
  return timers.length;
}};
globalThis.clearTimeout = id => {{
  const index = Number(id) - 1;
  if (timers[index]) timers[index].cancelled = true;
}};
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
    this.isConnected = true;
  }}
  appendChild(node) {{
    node.parentNode = this;
    this.children.push(node);
    return node;
  }}
  insertBefore(node, beforeNode) {{
    node.parentNode = this;
    const index = this.children.indexOf(beforeNode);
    if (index >= 0) this.children.splice(index, 0, node);
    else this.children.push(node);
    return node;
  }}
  replaceChildren(...nodes) {{
    this.children = [];
    this.childNodes = this.children;
    nodes.forEach(node => this.appendChild(node));
  }}
  setAttribute(name, value) {{
    this[name] = String(value);
  }}
}}
class FakeDocument {{
  createElement(tagName) {{
    return new FakeNode(tagName, this);
  }}
}}
function flushOne() {{
  const next = timers.find(item => !item.cancelled && !item.done);
  if (!next) return false;
  next.done = true;
  next.callback();
  return true;
}}
const documentRef = new FakeDocument();
const container = documentRef.createElement('div');
const controller = guide.createThinkingPipeline(container, {{
  mode: 'recommend',
  autoAdvanceMs: 1000,
}});
const initial = controller.current;
flushOne();
const afterOne = controller.current;
flushOne();
const afterTwo = controller.current;
flushOne();
const afterThree = controller.current;
flushOne();
const afterFour = controller.current;
process.stdout.write(JSON.stringify({{
  initial,
  afterOne,
  afterTwo,
  afterThree,
  afterFour,
  timerDelays: timers.map(item => item.ms),
}}));
"""
    )

    assert result["initial"] == 0
    assert result["afterOne"] == 1
    assert result["afterTwo"] == 2
    assert result["afterThree"] == 3
    assert result["afterFour"] == 3
    assert result["timerDelays"][:3] == [1000, 1000, 1000]


def test_chat_wires_immediate_stage_driven_first_character_dismissal() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    module_version = sha256(MODULE.read_bytes()).hexdigest()[:12]

    assert (
        f'<script src="/static/guide-presentation.js?v={module_version}">'
        "</script>"
    ) in html
    assert "XiaoRoPresentation.createThinkingPipeline(" in html
    assert "XiaoRoPresentation.advanceThinkingPipeline(" in html
    assert "XiaoRoPresentation.setThinkingMode(" in html
    assert "XiaoRoPresentation.dismissThinkingPipeline(" in html
    assert "if (!hasFirstToken)" in html
    assert "firstCharacter: true" in html
    assert "eventName === 'stage'" in html
    assert "eventName === 'intent'" in html


def test_thinking_panel_uses_only_approved_visual_extension_selectors() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    for selector in (
        ".guide-thinking-pipeline",
        ".guide-thinking-stage",
        ".guide-thinking-markers",
    ):
        assert selector in html
    assert "min-height:" in html[
        html.index(".guide-thinking-pipeline") :
        html.index(".guide-presentation-section")
    ]
    assert "@media (prefers-reduced-motion: reduce)" in html


def test_history_sanitizer_removes_transient_thinking_panel() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    start = html.index("function sanitizeSnapshotHtml(snapshot)")
    end = html.index("\n\n        function loadStoredJson", start)
    source = html[start:end]

    assert ".guide-thinking-pipeline" in source
    assert "el.remove()" in source
