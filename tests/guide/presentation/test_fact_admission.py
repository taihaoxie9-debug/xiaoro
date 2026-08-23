import pytest

from app.guide.presentation.fact_admission import (
    presentation_fact_role,
)


@pytest.mark.parametrize(
    ("field_key", "expected"),
    (
        ("longevity", "narrative"),
        ("claimed_ingredients", "narrative"),
        ("future_purchase_attribute", "narrative"),
        ("spf_pa", "direct_fact"),
        ("net_content", "direct_fact"),
        ("usage", "question_only"),
        ("mechanism", "question_only"),
        ("origin", "question_only"),
        ("shade", "question_only"),
        ("shelf_life", "question_only"),
        ("safety_claim", "caution"),
    ),
)
def test_approved_fact_role_is_explicit_without_narrative_whitelist(
    field_key: str,
    expected: str,
) -> None:
    assert presentation_fact_role(field_key) == expected


def test_empty_fact_field_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="field key must be nonempty",
    ):
        presentation_fact_role("")
