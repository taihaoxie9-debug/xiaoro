from __future__ import annotations

import json
import re
from pathlib import Path


CHAT_HTML = Path("app/static/chat.html")
VISUAL_LOCK = Path(
    "docs/audits/frontend-integration/old_visual_shell_v1.json"
)


def _lock() -> dict[str, object]:
    assert VISUAL_LOCK.is_file(), "frontend visual-shell lock must exist"
    return json.loads(VISUAL_LOCK.read_text(encoding="utf-8"))


def _css_variables(html: str) -> dict[str, str]:
    root = re.search(r":root\s*\{(?P<body>.*?)\}", html, re.DOTALL)
    assert root is not None
    return {
        name: value.strip()
        for name, value in re.findall(
            r"(--[a-z0-9-]+)\s*:\s*([^;]+);",
            root.group("body"),
        )
    }


def test_frontend_shell_keeps_locked_palette_and_motion_tokens() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    locked = _lock()

    assert _css_variables(html) == locked["css_variables"]


def test_frontend_shell_keeps_critical_layout_and_component_fragments() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    locked = _lock()

    for fragment in locked["critical_fragments"]:
        assert fragment in html


def test_frontend_shell_declares_only_approved_visual_extension_selectors() -> None:
    locked = _lock()

    assert set(locked["allowed_extension_selectors"]) == {
        ".guide-thinking-pipeline",
        ".guide-thinking-stage",
        ".guide-thinking-markers",
        ".guide-presentation-section",
        ".guide-product-ref",
        ".guide-direct-fact",
        ".guide-evidence-drawer",
    }
