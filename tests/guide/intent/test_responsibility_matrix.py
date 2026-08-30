from __future__ import annotations

import subprocess
import sys

import pytest

from app.guide.intent.responsibility_matrix import (
    Responsibility,
    resolve_responsibility,
)


def test_responsibility_matrix_imports_in_a_cold_process() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.guide.intent.responsibility_matrix",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_two_candidate_ordinals_plus_suitability_resolves_comparison(
) -> None:
    result = resolve_responsibility(
        operation="suitability",
        cardinality="two_or_three",
        object_type="candidate_ordinals",
        dialogue_state="recommendation_batch",
        safety=False,
    )

    assert result.responsibility is Responsibility.COMPARISON
    assert result.processor == "comparison"
    assert result.presentation_mode == "comparison"


def test_two_image_ordinals_plus_suitability_resolves_comparison() -> None:
    result = resolve_responsibility(
        operation="suitability",
        cardinality="two_or_three",
        object_type="image_ordinals",
        dialogue_state="confirmed_image_product",
        safety=False,
    )

    assert result.responsibility is Responsibility.COMPARISON


def test_one_candidate_plus_suitability_remains_single_product() -> None:
    result = resolve_responsibility(
        operation="suitability",
        cardinality="one",
        object_type="candidate_ordinals",
        dialogue_state="recommendation_batch",
        safety=False,
    )

    assert (
        result.responsibility
        is Responsibility.SINGLE_PRODUCT_SUITABILITY
    )
    assert result.processor == "product_knowledge"
    assert result.presentation_mode == "single_product"


def test_assessment_with_bound_image_remains_consultation() -> None:
    result = resolve_responsibility(
        operation="assessment",
        cardinality="one",
        object_type="image_ordinals",
        dialogue_state="confirmed_image_product",
        safety=False,
    )

    assert result.responsibility is Responsibility.CONSULTATION
    assert result.processor == "consultation"
    assert result.presentation_mode == "consultation"


@pytest.mark.parametrize(
    ("cardinality", "expected"),
    (
        ("zero", Responsibility.GENERAL_KNOWLEDGE),
        ("one", Responsibility.PRODUCT_KNOWLEDGE),
        ("two_or_three", Responsibility.COMPARISON),
    ),
)
def test_knowledge_responsibility_depends_on_object_count(
    cardinality: str,
    expected: Responsibility,
) -> None:
    result = resolve_responsibility(
        operation="knowledge",
        cardinality=cardinality,
        object_type={
            "zero": "topic",
            "one": "current_product",
            "two_or_three": "explicit_products",
        }[cardinality],
        dialogue_state="single_product_focus",
        safety=False,
    )

    assert result.responsibility is expected


@pytest.mark.parametrize(
    ("dialogue_state", "expected"),
    (
        ("recommendation_batch", Responsibility.RECOMMENDATION),
        ("general_knowledge", Responsibility.GENERAL_KNOWLEDGE),
        ("consultation", Responsibility.CONSULTATION),
        ("comparison_batch", Responsibility.CLARIFICATION),
    ),
)
def test_unbound_followup_uses_current_dialogue_state(
    dialogue_state: str,
    expected: Responsibility,
) -> None:
    result = resolve_responsibility(
        operation="followup",
        cardinality="zero",
        object_type="none",
        dialogue_state=dialogue_state,
        safety=False,
    )

    assert result.responsibility is expected


def test_safety_escalation_precedes_ordinary_matrix_rules() -> None:
    result = resolve_responsibility(
        operation="recommendation",
        cardinality="two_or_three",
        object_type="current_batch",
        dialogue_state="recommendation_batch",
        safety=True,
    )

    assert result.responsibility is Responsibility.SAFETY_ESCALATION
    assert result.processor == "safety_escalation"


def test_over_limit_objects_fail_closed_to_clarification() -> None:
    result = resolve_responsibility(
        operation="comparison",
        cardinality="over_limit",
        object_type="explicit_products",
        dialogue_state="comparison_batch",
        safety=False,
    )

    assert result.responsibility is Responsibility.CLARIFICATION
    assert result.clarification_code == "reference_over_limit"


def test_invalid_object_shape_is_rejected() -> None:
    with pytest.raises(ValueError, match="object shape"):
        resolve_responsibility(
            operation="comparison",
            cardinality="zero",
            object_type="candidate_ordinals",
            dialogue_state="empty",
            safety=False,
        )


def test_four_confirmed_images_select_image_comparison() -> None:
    result = resolve_responsibility(
        operation="comparison",
        cardinality="four",
        object_type="confirmed_images",
        dialogue_state="empty",
        safety=False,
    )

    assert result.responsibility is Responsibility.COMPARISON
    assert result.processor == "image_comparison"
    assert result.presentation_mode == "comparison"


def test_four_explicit_products_remain_over_comparison_limit() -> None:
    result = resolve_responsibility(
        operation="comparison",
        cardinality="four",
        object_type="explicit_products",
        dialogue_state="comparison_batch",
        safety=False,
    )

    assert result.responsibility is Responsibility.CLARIFICATION
    assert result.clarification_code == "reference_over_limit"
