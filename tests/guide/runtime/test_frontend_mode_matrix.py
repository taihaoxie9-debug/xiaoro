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
}

EXPECTED_PRESENTATION_MODES = {
    "clarify-zero": "clarification",
    "compare-two": "comparison",
    "consultation-confirmation-zero": "consultation",
    "consultation-entry-zero": "consultation",
    "consultation-medical-zero": "consultation",
    "consultation-provisional-zero": "consultation",
    "error-zero": "clarification",
    "followup-product-one": "product_knowledge",
    "followup-relative": "comparison",
    "followup-state-zero": "recommendation",
    "image-compare-two": "comparison",
    "image-identity-one": "image_identity",
    "image-recommend-three": "recommendation",
    "image-suitability-one": "single_product",
    "knowledge-general-zero": "general_knowledge",
    "knowledge-product-one": "product_knowledge",
    "no-match-zero": "recommendation",
    "recommend-three": "recommendation",
    "revision-products": "recommendation",
    "suitability-one": "single_product",
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
        presentation_mode = row["presentation_mode"]

        assert isinstance(visible, list)
        assert isinstance(inline, list)
        assert isinstance(full, list)
        assert len(visible) == len(set(visible))
        assert full == visible
        assert row["pitfall_product_ids"] == []

        case_id = row["case_id"]
        if case_id in ZERO_CARD_CASE_IDS:
            assert visible == []
            assert inline == []
            assert "full_cards" not in row["section_order"]
            continue

        assert visible
        assert (
            inline == visible
            if presentation_mode == "recommendation"
            else inline == []
        )
        if presentation_mode == "recommendation":
            assert row["section_order"] == [
                "summary",
                *(
                    f"product:p{index}"
                    for index in range(1, len(visible) + 1)
                ),
                "closing",
                "full_cards",
            ]
            assert row["advisor_reason"] is True
            continue
        if presentation_mode == "comparison":
            assert row["section_order"] == [
                "summary",
                "comparison",
                "full_cards",
            ]
            assert row["advisor_reason"] is False
            continue
        if presentation_mode == "single_product":
            assert row["section_order"] == [
                "summary",
                "judgement",
                "full_cards",
            ]
            assert row["advisor_reason"] is False
            continue
        if presentation_mode == "product_knowledge":
            assert row["section_order"] == [
                "summary",
                "answer",
                "full_cards",
            ]
            assert row["advisor_reason"] is False
            continue
        assert presentation_mode == "image_identity"
        assert row["section_order"] == [
            "observation",
            "full_cards",
        ]
        assert row["advisor_reason"] is False


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
            "general_knowledge",
        }
        assert isinstance(row["thinking_stages"], list)
        assert 0 <= len(row["thinking_stages"]) <= 4
        assert row["history_behavior"] in {
            "persist",
            "persist_without_thinking",
            "transient",
        }
