from __future__ import annotations

import json
from pathlib import Path


MATRIX = Path(
    "tests/fixtures/guide/presentation/frontend_mode_matrix_v2.jsonl"
)

EXPECTED_CASE_IDS = {
    "recommend-three",
    "compare-two",
    "suitability-one",
    "followup-product-one",
    "followup-relative",
    "revision-products",
    "followup-state-zero",
    "knowledge-product-one",
    "knowledge-general-zero",
    "image-identity-one",
    "image-recommend-three",
    "image-suitability-one",
    "image-compare-two",
    "consultation-entry-zero",
    "consultation-provisional-zero",
    "consultation-confirmation-zero",
    "consultation-medical-zero",
    "clarify-zero",
    "no-match-zero",
    "error-zero",
}

ZERO_CARD_CASE_IDS = {
    "knowledge-general-zero",
    "followup-state-zero",
    "consultation-entry-zero",
    "consultation-provisional-zero",
    "consultation-confirmation-zero",
    "consultation-medical-zero",
    "clarify-zero",
    "no-match-zero",
    "error-zero",
}

COMPARISON_CASE_IDS = {
    "compare-two",
    "followup-relative",
    "image-compare-two",
}

PRODUCT_KNOWLEDGE_CASE_IDS = {
    "knowledge-product-one",
    "image-suitability-one",
}

EXPECTED_PRESENTATION_MODES = {
    "clarify-zero": "clarification",
    "compare-two": "comparison",
    "consultation-confirmation-zero": "consultation",
    "consultation-entry-zero": "consultation",
    "consultation-medical-zero": "consultation",
    "consultation-provisional-zero": "consultation",
    "error-zero": "error",
    "followup-product-one": "followup",
    "followup-relative": "followup",
    "followup-state-zero": "followup",
    "image-compare-two": "comparison",
    "image-identity-one": "image_identity",
    "image-recommend-three": "recommendation",
    "image-suitability-one": "product_knowledge",
    "knowledge-general-zero": "general_knowledge",
    "knowledge-product-one": "product_knowledge",
    "no-match-zero": "recommendation",
    "recommend-three": "recommendation",
    "revision-products": "revision",
    "suitability-one": "single_product",
}

EXPECTED_CARD_RANGES = {
    "recommend-three": (1, 3),
    "compare-two": (2, 4),
    "suitability-one": (1, 1),
    "followup-product-one": (1, 1),
    "followup-relative": (1, 3),
    "revision-products": (1, 3),
    "knowledge-product-one": (1, 1),
    "image-identity-one": (1, 1),
    "image-recommend-three": (1, 3),
    "image-suitability-one": (1, 1),
    "image-compare-two": (2, 4),
}

PUBLIC_MODES = {
    "recommend",
    "comparison",
    "suitability",
    "knowledge",
    "followup",
    "clarify",
    "revise",
    "image_recommend",
    "image_identity",
    "image_compare",
    "image_suitability",
    "consultation_entry",
    "consultation_provisional",
    "consultation_confirmation",
    "consultation_medical_escalation",
    "error",
}


def _rows() -> list[dict[str, object]]:
    assert MATRIX.is_file(), "frontend mode matrix must be published"
    return [
        json.loads(line)
        for line in MATRIX.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_frontend_mode_matrix_covers_every_public_display_family() -> None:
    rows = _rows()

    assert len(rows) == 20
    assert {row["case_id"] for row in rows} == EXPECTED_CASE_IDS
    assert {row["mode"] for row in rows} <= PUBLIC_MODES
    assert {
        row["case_id"]: row["presentation_mode"]
        for row in rows
    } == EXPECTED_PRESENTATION_MODES
    assert [row["case_id"] for row in rows] == sorted(
        row["case_id"] for row in rows
    )


def test_mode_matrix_binds_both_card_forms_to_visible_products() -> None:
    for row in _rows():
        visible = row["visible_product_ids"]
        inline = row["inline_card_ids"]
        full = row["full_card_ids"]

        assert isinstance(visible, list)
        assert isinstance(inline, list)
        assert isinstance(full, list)
        assert len(visible) == len(set(visible))
        assert inline == visible
        assert full == visible
        assert set(row["pitfall_product_ids"]).issubset(visible)

        case_id = row["case_id"]
        if case_id in ZERO_CARD_CASE_IDS:
            assert visible == []
            assert not any(
                str(section).startswith("product:")
                for section in row["section_order"]
            )
            assert "full_cards" not in row["section_order"]
            assert "pitfalls" not in row["section_order"]
            continue

        minimum, maximum = EXPECTED_CARD_RANGES[case_id]
        assert minimum <= len(visible) <= maximum
        if case_id in PRODUCT_KNOWLEDGE_CASE_IDS:
            assert row["section_order"] == [
                "product:p1",
                "full_cards",
            ]
            assert row["advisor_reason"] is False
            assert "pitfalls" not in row["section_order"]
            continue
        expected_sections = ["summary"]
        if case_id in COMPARISON_CASE_IDS:
            expected_sections.append("comparison")
        expected_sections.extend(
            f"product:p{index}"
            for index in range(1, len(visible) + 1)
        )
        expected_sections.extend(
            ["closing", "full_cards", "pitfalls"]
        )
        assert row["section_order"] == expected_sections
        assert row["advisor_reason"] is True
        assert "evidence" not in row["section_order"]


def test_mode_matrix_has_explicit_copy_sections_and_thinking_states() -> None:
    for row in _rows():
        assert isinstance(row["copy_schema"], str)
        assert row["copy_schema"]
        assert row["copy_schema"] == row["presentation_mode"]
        assert isinstance(row["section_order"], list)
        assert row["section_order"]
        assert row["section_order"][0] in {
            "summary",
            "question",
            "observation",
            "error",
            "product:p1",
            "general_knowledge",
        }
        assert isinstance(row["thinking_stages"], list)
        assert 0 <= len(row["thinking_stages"]) <= 4
        assert row["history_behavior"] in {
            "persist",
            "persist_without_thinking",
            "transient",
        }
