from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_previous_closure_is_superseded_for_product_readiness() -> None:
    text = (
        ROOT / "docs/audits/unified-router/final-closure.md"
    ).read_text(encoding="utf-8")

    assert "Status: Superseded for product-readiness" in text
    assert "continuous-conversation-acceptance-design.md" in text
