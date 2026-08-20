from __future__ import annotations

import json
import subprocess
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


def test_full_product_cards_render_only_contract_tags() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    body = _source(
        html,
        "function displayProducts(",
        "\n\n        // 显示来源引用",
    )

    assert "categoryFactsHtml" not in body
    assert "buildCategoryFactsHtml(" not in body
    assert "category-facts" not in body
    assert "p.compact_tags" in body
    assert ".slice(0, 3)" in body
    assert "recommendation-contract-tag" in body
    assert "p.matched_efficacies" not in body
    assert "recommendation-reason" not in body
    assert "data-match-percentage" not in body


def test_full_product_cards_do_not_construct_recommendation_reasons() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    body = _source(
        html,
        "function displayProducts(",
        "\n\n        // 显示来源引用",
    )

    for forbidden in (
        "buildDetailedProductReason(",
        "getSkinEvidenceLabel(",
        "rerank_reason",
        "category_facts",
        "matched_efficacies",
        "description",
        "recommendation-reason",
    ):
        assert forbidden not in body


def test_full_product_card_uses_display_name_and_has_no_fit_status() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    display_source = _source(
        html,
        "function displayProducts(",
        "\n\n        // 显示来源引用",
    )

    assert "p.display_name || p.name" in display_source
    assert "getSkinEvidenceLabel(" not in display_source
    assert "recommendation-score" not in display_source
    assert "适配待确认" not in display_source


def test_mobile_product_names_can_wrap_to_two_lines() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    mobile_start = html.index("@media (max-width: 960px)")
    mobile_end = html.index("@media", mobile_start + 1)
    mobile_styles = html[mobile_start:mobile_end]

    name_start = mobile_styles.index(".recommendation-name")
    name_end = mobile_styles.index("}", name_start)
    name_rule = mobile_styles[name_start:name_end]

    assert "-webkit-line-clamp: 2" in name_rule


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
