from __future__ import annotations

from pathlib import Path


CHAT_HTML = Path("app/static/chat.html")


def _source(
    html: str,
    start_marker: str,
    end_marker: str,
) -> str:
    start = html.index(start_marker)
    end = html.index(end_marker, start)
    return html[start:end]


def test_terminal_panel_order_is_full_cards_then_pitfalls_without_evidence() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    stream = _source(
        html,
        "const flushDeferredPanels = () =>",
        "const resolveTypewriterIfIdle",
    )

    cards = stream.index("displayProducts(")
    pitfall = stream.index("displayPitfalls(")
    assert cards < pitfall
    for hidden_renderer in (
        "displayScenarioEvidence(",
        "displayMerchantClaims(",
        "displayProductEvidence(",
        "displayReviewEvidence(",
        "displayCitations(",
    ):
        assert hidden_renderer not in stream


def test_exact_evidence_stays_available_for_audit_but_not_terminal_flush() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "function addEvidenceDrawer(" in html
    for function_name in (
        "displayScenarioEvidence",
        "displayProductEvidence",
        "displayMerchantClaims",
        "displayReviewEvidence",
        "displayCitations",
    ):
        body = _source(
            html,
            f"function {function_name}(",
            "\n        function ",
        )
        assert "addEvidenceDrawer(" in body, function_name
    assert '<details class="guide-evidence-drawer">' in html
    assert "details.open = false" in html


def test_full_product_cards_omit_category_table_and_bound_efficacy_tags() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    body = _source(
        html,
        "function displayProducts(products)",
        "\n\n        // 显示来源引用",
    )

    assert "categoryFactsHtml" not in body
    assert "buildCategoryFactsHtml(" not in body
    assert "category-facts" not in body
    assert "p.matched_efficacies" in body
    assert ".filter(Boolean).slice(0, 2)" in body
    assert "data-match-percentage" not in body


def test_typed_pitfalls_keep_high_separate_and_merge_other_severities() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    body = _source(
        html,
        "function displayPitfalls(pitfalls)",
        "\n\n        // 单个步骤卡片 HTML",
    )

    assert "severity === 'high'" in body
    assert "const otherPitfalls" in body
    assert "其他注意" in body
    assert "typedOthers.map" not in body
    assert "escapeHtml(" in body
