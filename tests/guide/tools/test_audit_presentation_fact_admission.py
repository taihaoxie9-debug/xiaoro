from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_production_fact_admission_audit_is_complete_and_deterministic() -> None:
    from tools.guide_data import audit_presentation_fact_admission

    first = audit_presentation_fact_admission.build_audit_report(ROOT)
    second = audit_presentation_fact_admission.build_audit_report(ROOT)

    assert first == second
    assert first["schema_version"] == (
        "guide-presentation-fact-admission-audit-v1"
    )
    assert first["summary"]["claim_count"] > 1000
    assert first["summary"]["product_count"] > 90
    assert first["summary"]["missing_source_ref_count"] == 0
    assert first["summary"]["field_whitelist_only_drop_count"] == 0
    assert first["summary"]["normalized_fallback_count"] > 0
    assert first["summary"]["validator_only_drop_count"] < 80
    assert first["summary"]["known_category_fact_count"] > 500
    assert first["summary"]["known_category_fact_missing_source_count"] == 0
    assert first["summary"]["approved_review_source_count"] == 6
    assert first["summary"]["review_product_count"] == 3
    assert first["summary"]["direct_fact_unresolved_count"] == 0
    assert first["summary"]["unexplained_drop_count"] == 0
    assert len(first["rows"]) == first["summary"]["claim_count"]
    assert {
        row["disposition"] for row in first["rows"]
    } >= {
        "positioning",
        "direct_fact",
        "question_only",
        "caution",
    }


def test_audit_rows_preserve_authority_and_reason() -> None:
    from tools.guide_data import audit_presentation_fact_admission

    report = audit_presentation_fact_admission.build_audit_report(ROOT)

    for row in report["rows"]:
        assert row["product_id"] > 0
        assert row["field_key"]
        assert row["source_refs"]
        assert row["reason_code"]
        assert row["attribution"] == "merchant_claim"
        assert row["selected_meaning_source"] in {
            "display_claim",
            "normalized_value",
            "not_applicable",
            "rejected",
        }
    assert report["category_fact_inventory"]
    assert report["review_inventory"]
