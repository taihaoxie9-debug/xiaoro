from __future__ import annotations

import pytest

from app.guide.intent.concept_preferences import (
    ConceptCatalogEntry,
    ConceptPreferenceCatalog,
)
from app.guide.intent.semantic_admission import admit_turn_meaning
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


def _catalog() -> ConceptPreferenceCatalog:
    return ConceptPreferenceCatalog(
        entries=(
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="texture",
                concept_id="texture.refreshing",
            ),
            ConceptCatalogEntry(
                profile=CategoryProfile.SUNCARE,
                field_key="texture",
                concept_id="texture.refreshing",
            ),
        )
    )


def _meaning(**updates) -> TurnMeaning:
    payload = {
        "operation_hint": "recommendation",
        "recommendation_mode": "explore",
        "recommendation_count": 3,
        "recommendation_mode_basis": {
            "basis": "broad_exploration",
            "source_text": "推荐",
        },
        "topic_hint": None,
        "continuity_hint": "new_task",
        "subject_scope_hint": "self",
        "reference_mentions": [],
        "product_mentions": [],
        "budget_candidates": [],
        "observation_candidates": [],
        "preference_candidates": [],
        "relative_candidates": [],
        "consultation_hypothesis": None,
        "next_observation_gap": None,
        "question_meaning": None,
        "safety_language": "ordinary",
    }
    payload.update(updates)
    if (
        payload["operation_hint"]
        not in {"recommendation", "image_similarity"}
    ):
        payload["recommendation_mode"] = updates.get(
            "recommendation_mode"
        )
        payload["recommendation_count"] = updates.get(
            "recommendation_count"
        )
        payload["recommendation_mode_basis"] = updates.get(
            "recommendation_mode_basis"
        )
    return TurnMeaning.model_validate(payload, strict=True)


def test_recommendation_outcome_is_admitted_as_closed_protocol() -> None:
    result = admit_turn_meaning(
        message="给我推荐两款防晒",
        meaning=_meaning(
            topic_hint="sunscreen",
            recommendation_mode="explore",
            recommendation_count=2,
            recommendation_mode_basis={
                "basis": "count_requested",
                "source_text": "两款",
            },
        ),
        topic=TopicCode.SUNSCREEN,
        concept_catalog=_catalog(),
    )

    assert result.for_kind("recommendation_mode")[0].normalized_value == (
        "explore"
    )
    assert result.for_kind("recommendation_mode_basis")[
        0
    ].normalized_value == "count_requested"
    assert result.for_kind("recommendation_count")[0].normalized_value == (
        "2"
    )


def test_recommendation_basis_is_bound_to_current_turn_evidence() -> None:
    result = admit_turn_meaning(
        message="给我推荐 500 内的防晒",
        meaning=_meaning(
            topic_hint="sunscreen",
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": "single_best_request",
                "source_text": "唯一最适合",
            },
        ),
        topic=TopicCode.SUNSCREEN,
        concept_catalog=_catalog(),
    )

    outcome = result.for_kind("recommendation_mode_basis")[0]
    assert outcome.disposition == "rejected_protocol"
    assert outcome.normalized_value is None


@pytest.mark.parametrize(
    "basis",
    (
        "personal_suitability",
        "profile_match_choice",
        "best_among_candidates",
    ),
)
def test_fit_count_requires_source_bound_single_selection_evidence(
    basis: str,
) -> None:
    result = admit_turn_meaning(
        message="推荐清爽防晒，适合我用",
        meaning=_meaning(
            topic_hint="sunscreen",
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": basis,
                "source_text": "适合我用",
            },
        ),
        topic=TopicCode.SUNSCREEN,
        concept_catalog=_catalog(),
    )

    count = result.for_kind("recommendation_count")[0]
    assert count.disposition == "rejected_protocol"
    assert count.normalized_value is None


def test_reviewed_preference_is_admitted_for_known_topic() -> None:
    result = admit_turn_meaning(
        message="想要清爽一点的防晒",
        meaning=_meaning(
            topic_hint="sunscreen",
            preference_candidates=(
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "raw_text": "清爽一点",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ),
        ),
        topic=TopicCode.SUNSCREEN,
        concept_catalog=_catalog(),
    )
    preference = result.for_kind("preference")[0]

    assert preference.disposition == "admitted"
    assert preference.normalized_value == "texture.refreshing"


def test_reviewed_preference_defers_until_topic_without_disappearing() -> None:
    result = admit_turn_meaning(
        message="想要清爽一点的",
        meaning=_meaning(
            preference_candidates=(
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "raw_text": "清爽一点",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ),
        ),
        topic=None,
        concept_catalog=_catalog(),
    )

    assert result.for_kind("preference")[0].model_dump() == {
        "atom_kind": "preference",
        "raw_text": "清爽一点",
        "disposition": "deferred_until_topic",
        "normalized_value": "texture.refreshing",
        "reason": "reviewed concept awaits a product topic",
    }


def test_unsupported_open_descriptor_is_retained_losslessly() -> None:
    result = admit_turn_meaning(
        message="想要雨后潮湿木头感",
        meaning=_meaning(
            preference_candidates=(
                {
                    "field_key": "scent_profile",
                    "concept_id": None,
                    "raw_text": "雨后潮湿木头感",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ),
        ),
        topic=TopicCode.FRAGRANCE,
        concept_catalog=_catalog(),
    )

    preference = result.for_kind("preference")[0]
    assert preference.disposition == "retained_free"
    assert preference.normalized_value == "雨后潮湿木头感"


def test_generic_ingredient_avoid_is_rejected_without_closed_parent() -> None:
    result = admit_turn_meaning(
        message="给我找防晒，避开乙醇",
        meaning=_meaning(
            topic_hint="sunscreen",
            preference_candidates=(
                {
                    "field_key": "ingredient",
                    "concept_id": None,
                    "raw_text": "乙醇",
                    "polarity": "avoid",
                    "strength": "ordinary",
                },
            ),
        ),
        topic=TopicCode.SUNSCREEN,
        concept_catalog=_catalog(),
    )

    preference = result.for_kind("preference")[0]
    assert preference.disposition == "rejected_protocol"
    assert preference.reason == (
        "ingredient exclusions require ingredient_exclusion"
    )


def test_unbound_source_is_rejected_as_protocol_not_semantic_mismatch() -> None:
    result = admit_turn_meaning(
        message="想要清爽防晒",
        meaning=_meaning(
            topic_hint="sunscreen",
            preference_candidates=(
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "raw_text": "轻薄",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ),
        ),
        topic=TopicCode.SUNSCREEN,
        concept_catalog=_catalog(),
    )

    preference = result.for_kind("preference")[0]
    assert preference.disposition == "rejected_protocol"
    assert preference.reason == "raw_text is not uniquely source-bound"


def test_matching_active_topic_return_reference_is_admitted() -> None:
    result = admit_turn_meaning(
        message="回到精华，比较B5精华和CE精华",
        meaning=_meaning(
            operation_hint="comparison",
            topic_hint="serum",
            continuity_hint="return_to_focus",
            reference_mentions=(
                {
                    "raw_text": "精华",
                    "object_family_hint": "topic",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
            ),
            product_mentions=(
                {"raw_text": "B5精华"},
                {"raw_text": "CE精华"},
            ),
        ),
        topic=TopicCode.SERUM,
        active_topic=TopicCode.SERUM,
        concept_catalog=_catalog(),
    )

    reference = result.for_kind("reference")[0]
    assert reference.disposition == "admitted"
    assert reference.reason == "typed current topic matches active context"


def test_mismatched_active_topic_return_reference_is_rejected() -> None:
    result = admit_turn_meaning(
        message="回到精华，比较B5精华和CE精华",
        meaning=_meaning(
            operation_hint="comparison",
            topic_hint="serum",
            continuity_hint="return_to_focus",
            reference_mentions=(
                {
                    "raw_text": "精华",
                    "object_family_hint": "topic",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
            ),
            product_mentions=(
                {"raw_text": "B5精华"},
                {"raw_text": "CE精华"},
            ),
        ),
        topic=TopicCode.SERUM,
        active_topic=TopicCode.SUNSCREEN,
        concept_catalog=_catalog(),
    )

    assert result.for_kind("reference")[0].disposition == (
        "rejected_protocol"
    )


def test_all_consultation_observations_receive_auditable_outcomes() -> None:
    result = admit_turn_meaning(
        message="下午鼻子额头油，两颊洗完紧，换季会红刺",
        meaning=_meaning(
            operation_hint="assessment",
            topic_hint="skincare",
            continuity_hint="continue",
            observation_candidates=(
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
                {
                    "observation_id": "obs_invented",
                    "code": "stinging",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "刷酸刺痛",
                    "location": None,
                    "trigger": "acid",
                    "duration": None,
                    "severity": None,
                },
            ),
        ),
        topic=TopicCode.SKINCARE,
        concept_catalog=_catalog(),
    )
    observations = result.for_kind("consultation_observation")

    assert [item.disposition for item in observations] == [
        "admitted",
        "admitted",
        "rejected_protocol",
    ]
    assert [item.raw_text for item in observations] == [
        "鼻子额头油",
        "两颊洗完紧",
        "刷酸刺痛",
    ]
