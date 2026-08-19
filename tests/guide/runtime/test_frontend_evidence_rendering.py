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


def test_full_product_card_reason_avoids_price_or_budget_fillers() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    format_source = _source(
        html,
        "function formatCategoryFactValue(fact)",
        "\n\n        function buildCategoryFactsHtml",
    )
    body = _source(
        html,
        "function buildDetailedProductReason(p, index)",
        "\n\n        function getSkinEvidenceLabel",
    )
    completed = subprocess.run(
        [
            "node",
            "-e",
            f"""
{format_source}
{body}
const product = {{
  price: 1080,
  rerank_reason: '价格约¥1080，符合预算，京东详情可查实时价',
  matched_efficacies: ['修护', '抗老'],
  category_facts: [
    {{
      field_key: 'ingredients_present',
      label: '核心成分',
      value: ['玻色因', '透明质酸'],
      state: 'known',
    }},
    {{
      field_key: 'suitable_skin',
      label: '适合肤质',
      value: ['多种肤质适用'],
      state: 'known',
    }},
  ],
}};
process.stdout.write(JSON.stringify({{
  reason: buildDetailedProductReason(product, 0),
}}));
""",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    reason = json.loads(completed.stdout)["reason"]

    for prohibited_output in (
        "参考价约",
        "实时价",
        "预算建议",
        "符合预算",
        "价格和肤感取舍",
    ):
        assert prohibited_output not in reason
    assert "修护" in reason
    assert "抗老" in reason
    assert "玻色因" in reason


def test_full_product_card_hides_default_unbounded_skin_label() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    score_source = _source(
        html,
        "function getSkinEvidenceLabel(product)",
        "\n\n        function displayImageObservation",
    )
    display_source = _source(
        html,
        "function displayProducts(products)",
        "\n\n        // 显示来源引用",
    )

    assert "return '未限定肤质'" not in score_source
    assert "evidenceLabel ? " in display_source
    assert "recommendation-score" in display_source


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
