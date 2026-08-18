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
