from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.understanding.turn_meaning_contracts import (
    TurnMeaning,
)


def _payload() -> dict[str, object]:
    return {
        "operation_hint": "recommendation",
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
    assert meaning.preference_candidates[0].concept_id == (
        "texture.refreshing"
    )
    assert meaning.relative_candidates[0].direction == "higher"


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


def test_turn_meaning_rejects_duplicate_raw_semantic_atoms() -> None:
    payload = _payload()
    payload["preference_candidates"] = [
        payload["preference_candidates"][0],
        payload["preference_candidates"][0],
    ]

    with pytest.raises(ValidationError, match="unique"):
        TurnMeaning.model_validate(payload, strict=True)


def test_consultation_hypothesis_references_current_observation_ids() -> None:
    payload = _payload()
    payload.update(
        {
            "operation_hint": "assessment",
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
