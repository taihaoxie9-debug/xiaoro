from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.understanding.turn_meaning_contracts import (
    TurnMeaning,
)


def _payload() -> dict[str, object]:
    return {
        "operation_hint": "recommendation",
        "recommendation_mode": "explore",
        "recommendation_count": 3,
        "recommendation_mode_basis": {
            "basis": "count_requested",
            "source_text": "三款",
        },
        "topic_hint": "sunscreen",
        "continuity_hint": "new_task",
        "subject_scope_hint": "self",
        "reference_mentions": [
            {
                "raw_text": "这个",
                "object_family_hint": "product",
                "ordinal_hint": None,
                "plurality_hint": "single",
            }
        ],
        "product_mentions": [],
        "budget_candidates": [
            {
                "raw_text": "三百以内",
                "relation": "maximum",
                "minimum": None,
                "maximum": "300",
            }
        ],
        "observation_candidates": [],
        "preference_candidates": [
            {
                "field_key": "texture",
                "concept_id": "texture.refreshing",
                "raw_text": "清爽一点",
                "polarity": "prefer",
                "strength": "ordinary",
            }
        ],
        "relative_candidates": [
            {
                "field_key": "texture",
                "concept_id": "texture.refreshing",
                "direction": "higher",
                "raw_text": "更清爽",
                "baseline_hint": "current_item",
            }
        ],
        "consultation_hypothesis": None,
        "next_observation_gap": None,
        "question_meaning": "想找预算三百以内且更清爽的防晒",
        "safety_language": "ordinary",
    }


def test_turn_meaning_accepts_one_universal_translation() -> None:
    meaning = TurnMeaning.model_validate(_payload(), strict=True)

    assert meaning.operation_hint == "recommendation"
    assert meaning.recommendation_mode == "explore"
    assert meaning.recommendation_count == 3
    assert meaning.recommendation_mode_basis.basis == (
        "count_requested"
    )
    assert meaning.preference_candidates[0].concept_id == (
        "texture.refreshing"
    )
    assert meaning.relative_candidates[0].direction == "higher"


def test_turn_meaning_accepts_one_product_fit() -> None:
    payload = _payload()
    payload["recommendation_mode"] = "fit"
    payload["recommendation_count"] = 1
    payload["recommendation_mode_basis"] = {
        "basis": "single_best_request",
        "source_text": "这个",
    }

    meaning = TurnMeaning.model_validate(payload, strict=True)

    assert meaning.recommendation_mode == "fit"
    assert meaning.recommendation_count == 1
    assert meaning.recommendation_mode_basis.basis == (
        "single_best_request"
    )
    assert meaning.recommendation_mode_basis.source_text == "这个"


def test_turn_meaning_rejects_recommendation_without_basis() -> None:
    payload = _payload()
    payload["recommendation_mode_basis"] = None

    with pytest.raises(ValidationError, match="recommendation basis"):
        TurnMeaning.model_validate(payload, strict=True)


def test_turn_meaning_rejects_fit_with_explore_basis() -> None:
    payload = _payload()
    payload["recommendation_mode"] = "fit"
    payload["recommendation_count"] = 1
    payload["recommendation_mode_basis"] = {
        "basis": "count_requested",
        "source_text": "这个",
    }

    with pytest.raises(ValidationError, match="parent-scoped"):
        TurnMeaning.model_validate(payload, strict=True)


def test_turn_meaning_rejects_fit_with_multiple_results() -> None:
    payload = _payload()
    payload["recommendation_mode"] = "fit"
    payload["recommendation_count"] = 2
    payload["recommendation_mode_basis"] = {
        "basis": "single_best_request",
        "source_text": "这个",
    }

    with pytest.raises(ValidationError, match="fit"):
        TurnMeaning.model_validate(payload, strict=True)


def test_non_recommendation_forbids_recommendation_outcome() -> None:
    payload = _payload()
    payload["operation_hint"] = "knowledge"

    with pytest.raises(ValidationError, match="non-recommendation"):
        TurnMeaning.model_validate(payload, strict=True)

    payload["recommendation_mode"] = None
    payload["recommendation_count"] = None
    payload["recommendation_mode_basis"] = None
    meaning = TurnMeaning.model_validate(payload, strict=True)

    assert meaning.recommendation_mode is None
    assert meaning.recommendation_count is None


def test_non_recommendation_forbids_recommendation_mode_basis() -> None:
    payload = _payload()
    payload["operation_hint"] = "knowledge"
    payload["recommendation_mode"] = None
    payload["recommendation_count"] = None

    with pytest.raises(ValidationError, match="recommendation basis"):
        TurnMeaning.model_validate(payload, strict=True)


def test_turn_meaning_forbids_offsets_ids_and_state_operations() -> None:
    for field, value in (
        ("start", 0),
        ("end", 2),
        ("product_id", 55),
        ("candidate_id", 1),
        ("operation", "replace"),
        ("task_plan", {"mode": "recommend"}),
    ):
        payload = _payload()
        payload[field] = value
        with pytest.raises(ValidationError, match=field):
            TurnMeaning.model_validate(payload, strict=True)

    payload = _payload()
    payload["reference_mentions"][0]["start"] = 0
    with pytest.raises(ValidationError, match="start"):
        TurnMeaning.model_validate(payload, strict=True)


def test_batch_size_hint_requires_a_batch_reference() -> None:
    payload = _payload()
    payload["reference_mentions"][0]["batch_size_hint"] = 2

    with pytest.raises(ValidationError, match="batch_size_hint"):
        TurnMeaning.model_validate(payload, strict=True)


def test_concept_id_must_be_scoped_to_preference_field() -> None:
    payload = _payload()
    payload["preference_candidates"][0]["concept_id"] = (
        "efficacy.soothing"
    )

    with pytest.raises(ValidationError, match="field-scoped"):
        TurnMeaning.model_validate(payload, strict=True)


def test_free_descriptor_is_valid_without_parent_concept() -> None:
    payload = _payload()
    payload["preference_candidates"] = [
        {
            "field_key": "fragrance_description",
            "concept_id": None,
            "raw_text": "雨后潮湿木头感",
            "polarity": "prefer",
            "strength": "ordinary",
        }
    ]
    payload["relative_candidates"] = []

    meaning = TurnMeaning.model_validate(payload, strict=True)

    assert meaning.preference_candidates[0].concept_id is None


def test_ingredient_exclusion_parent_requires_a_bare_avoid_target() -> None:
    payload = _payload()
    payload["preference_candidates"] = [
        {
            "field_key": "ingredient_exclusion",
            "concept_id": "ingredient_exclusion.alcohol",
            "raw_text": "酒精",
            "polarity": "avoid",
            "strength": "ordinary",
        }
    ]
    payload["relative_candidates"] = []

    with pytest.raises(ValidationError, match="ingredient exclusion"):
        TurnMeaning.model_validate(payload, strict=True)


def test_turn_meaning_rejects_duplicate_raw_semantic_atoms() -> None:
    payload = _payload()
    payload["preference_candidates"] = [
        payload["preference_candidates"][0],
        payload["preference_candidates"][0],
    ]

    with pytest.raises(ValidationError, match="unique"):
        TurnMeaning.model_validate(payload, strict=True)


def test_turn_meaning_accepts_closed_state_action_atoms() -> None:
    payload = _payload()
    payload["pending_response_hint"] = "unknown"
    payload["constraint_changes"] = [
        {
            "parent_concept": "efficacy",
            "requested_change": "replace",
            "raw_text": "修护",
            "normalized_value": "repair",
        },
        {
            "parent_concept": "skin",
            "requested_change": "replace",
            "raw_text": "油皮",
            "normalized_value": "oily",
        },
    ]

    meaning = TurnMeaning.model_validate(payload, strict=True)

    assert [
        (
            item.parent_concept,
            item.requested_change,
            item.normalized_value,
        )
        for item in meaning.constraint_changes
    ] == [
        ("efficacy", "replace", "repair"),
        ("skin", "replace", "oily"),
    ]


def test_consultation_hypothesis_references_current_observation_ids() -> None:
    payload = _payload()
    payload.update(
        {
            "operation_hint": "assessment",
            "recommendation_mode": None,
            "recommendation_count": None,
            "recommendation_mode_basis": None,
            "topic_hint": "skincare",
            "continuity_hint": "continue",
            "observation_candidates": [
                {
                    "observation_id": "obs_oil",
                    "code": "oiliness",
                    "present": True,
                    "qualifier": "t_zone",
                    "raw_text": "鼻子额头油",
                    "location": "t_zone",
                    "trigger": None,
                    "duration": "current",
                    "severity": None,
                },
                {
                    "observation_id": "obs_tight",
                    "code": "tightness",
                    "present": True,
                    "qualifier": "post_cleanse",
                    "raw_text": "两颊洗完紧",
                    "location": "cheeks",
                    "trigger": "post_cleanse",
                    "duration": "recurrent",
                    "severity": None,
                },
            ],
            "consultation_hypothesis": {
                "base_skin_direction": "combination",
                "stable_tendencies": [],
                "current_conditions": ["tightness"],
                "supporting_observation_ids": [
                    "obs_oil",
                    "obs_tight",
                ],
            },
            "next_observation_gap": "persistence_or_trigger",
        }
    )

    meaning = TurnMeaning.model_validate(payload, strict=True)

    assert meaning.continuity_hint == "continue"
    assert meaning.subject_scope_hint == "self"
    assert meaning.consultation_hypothesis is not None
    assert meaning.consultation_hypothesis.base_skin_direction == (
        "combination"
    )
    assert meaning.next_observation_gap == "persistence_or_trigger"

    payload["consultation_hypothesis"][
        "supporting_observation_ids"
    ] = ["obs_invented"]
    with pytest.raises(ValidationError, match="current observation"):
        TurnMeaning.model_validate(payload, strict=True)


def test_empty_unknown_consultation_hypothesis_normalizes_to_none() -> None:
    payload = _payload()
    payload["consultation_hypothesis"] = {
        "base_skin_direction": "unknown",
        "stable_tendencies": [],
        "current_conditions": [],
        "supporting_observation_ids": [],
    }

    meaning = TurnMeaning.model_validate(payload, strict=True)

    assert meaning.consultation_hypothesis is None


@pytest.mark.parametrize(
    ("qualifier", "trigger"),
    (
        ("seasonal", "seasonal"),
        ("ordinary_skincare", "ordinary_skincare"),
        ("acid", "acid"),
        ("new_product", "new_product"),
        ("unknown", "unknown"),
    ),
)
def test_observation_accepts_source_bound_trigger_qualifier_aliases(
    qualifier: str,
    trigger: str,
) -> None:
    payload = _payload()
    payload.update(
        {
            "operation_hint": "assessment",
            "recommendation_mode": None,
            "recommendation_count": None,
                "recommendation_mode_basis": None,
            "topic_hint": "skincare",
            "reference_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [
                {
                    "observation_id": "obs_condition",
                    "code": "redness",
                    "present": True,
                    "qualifier": qualifier,
                    "raw_text": "换季会红",
                    "location": "unknown",
                    "trigger": trigger,
                    "duration": "recurrent",
                    "severity": "unknown",
                }
            ],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": "persistence_or_trigger",
            "question_meaning": None,
        }
    )

    meaning = TurnMeaning.model_validate(payload, strict=True)

    assert meaning.observation_candidates[0].qualifier == qualifier
