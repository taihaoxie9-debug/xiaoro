from __future__ import annotations

from types import SimpleNamespace

from tools.guide_data.audit_selected_catalog_runtime_coverage import (
    build_selected_catalog_runtime_coverage,
)


def _field(
    value: object,
    *,
    state: str = "known",
) -> SimpleNamespace:
    return SimpleNamespace(resolved_state=state, value=value)


def test_runtime_coverage_distinguishes_typed_source_authority() -> None:
    reader = SimpleNamespace(
        get=lambda product_id: SimpleNamespace(
            product_id=product_id,
            fields={
                "category": _field("精华"),
                "product_identity": _field("示例精华"),
                "ingredients_present": _field(["神经酰胺"]),
                "net_content": _field(None, state="unknown"),
                "texture": _field(None, state="unknown"),
                "efficacy": _field(None, state="unknown"),
            },
        )
    )
    catalog = SimpleNamespace(
        get_presentation_facts=lambda product_id: SimpleNamespace(
            specification="30ml",
            category_fields=(
                SimpleNamespace(
                    field_key="texture",
                    resolved_state="known",
                    value=("清爽",),
                    source_classes=("merchant_description_ocr",),
                ),
            ),
        )
    )

    report = build_selected_catalog_runtime_coverage(
        reader=reader,
        catalog=catalog,
        scope={
            "selected_products": [
                {
                    "product_id": 11,
                    "category_profile": "skincare",
                }
            ]
        },
    )

    product = report["products"][0]
    assert product["field_sources"] == {
        "efficacy": "missing",
        "ingredients_present": "canonical",
        "net_content": "reviewed_specification",
        "texture": "merchant_claim",
    }
    assert product["missing_fields"] == ["efficacy"]
