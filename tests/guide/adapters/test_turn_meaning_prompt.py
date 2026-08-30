from __future__ import annotations

import json

from app.guide.adapters.llm.turn_meaning_prompt import (
    TURN_MEANING_PROMPT_VERSION,
    build_turn_meaning_messages,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import (
    ActiveConstraintKind,
    SemanticContext,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticRouteBindingAuthority,
)


def _authority() -> SemanticRouteBindingAuthority:
    return SemanticRouteBindingAuthority.from_context(
        SemanticContext(
            visible_candidate_count=2,
            image_count=1,
            confirmed_image_ordinals=(1,),
            conversation_version=2,
            active_topic=TopicCode.SUNSCREEN,
            active_dialogue="consultation",
            awaiting_reply=True,
            focused_candidate_ordinal=1,
            focused_image_ordinal=None,
            active_constraint_kinds=(
                ActiveConstraintKind.BUDGET,
                ActiveConstraintKind.CATEGORY,
            ),
            confirmed_profile_fields=(),
        )
    )


def test_prompt_uses_one_universal_schema_and_compact_catalog() -> None:
    system, user = build_turn_meaning_messages(
        "换个更清爽的，预算三百以内",
        _authority(),
        concept_catalog=(
            "efficacy.soothing",
            "texture.refreshing",
        ),
    )

    assert TURN_MEANING_PROMPT_VERSION == "guide-turn-meaning-prompt-v37"
    assert "operation_hint" in system["content"]
    assert "recommendation_mode" in system["content"]
    assert "recommendation_count" in system["content"]
    assert "recommendation_mode_basis" in system["content"]
    assert "explore|fit" in system["content"]
    assert "broad_exploration" in system["content"]
    assert "similar_alternatives" in system["content"]
    assert "single_best_request" in system["content"]
    assert "best_among_candidates" in system["content"]
    assert (
        "Generic recommendation verbs, categories, budgets, and needs"
        in system["content"]
    )
    assert (
        "an explicit numeric budget bound uses"
        in system["content"]
    )
    assert (
        "A generic singular product noun does not by itself prove"
        in system["content"]
    )
    assert (
        "A general cause or mechanism question uses knowledge"
        in system["content"]
    )
    assert (
        "A request to assess the user's current symptom or reaction uses "
        "assessment"
        in system["content"]
    )
    assert "continuity_hint" in system["content"]
    assert "subject_scope_hint" in system["content"]
    assert "pending_response_hint" in system["content"]
    assert "constraint_changes" in system["content"]
    assert "relative_candidates" in system["content"]
    assert "consultation_hypothesis" in system["content"]
    assert "next_observation_gap" in system["content"]
    assert "all observations expressed in the current message" in (
        system["content"]
    )
    assert "Never invent a location, trigger, duration, or severity" in (
        system["content"]
    )
    assert (
        "For an explicit correction such as not X, but Y, emit present=false"
    ) in system["content"]
    assert "present=true for Y" in system["content"]
    assert "Emit every listed key" in system["content"]
    assert "recommendation means selecting or finding products" in (
        system["content"]
    )
    assert (
        "image_similarity means using one current or uploaded image product "
        "as the anchor"
    ) in system["content"]
    assert (
        "image_identity means identifying the product shown in a current "
        "or uploaded image"
    ) in system["content"]
    assert (
        "A requested result count is not a set of comparison objects"
    ) in system["content"]
    assert (
        "Budget, texture, skin, or scenario constraints can coexist with "
        "image_similarity"
    ) in system["content"]
    assert (
        "For image_similarity in explore mode, always use "
        "similar_alternatives"
    ) in system["content"]
    assert (
        "comparison requires two or more already supplied or bindable objects"
    ) in system["content"]
    assert "Questions about texture, usage, caution, or facts" in (
        system["content"]
    )
    assert "referenced existing product are followup or knowledge" in (
        system["content"]
    )
    assert "followup requires prior binding authority" in system["content"]
    assert "current skin symptom, reaction, or damage" in (
        system["content"]
    )
    assert "even when the user asks what to do" in system["content"]
    assert "field_key is an unscoped snake_case field name" in (
        system["content"]
    )
    assert "Never copy concept_id into field_key" in system["content"]
    assert "ingredient_exclusion is a closed parent concept" in (
        system["content"]
    )
    assert (
        "ingredient_exclusion is allowed only when the message names an"
    ) in system["content"]
    assert "ingredient or ingredient family" in system["content"]
    assert (
        "fragrance_description for scent profile and notes"
    ) in system["content"]
    assert (
        "rinse_behavior for after-rinse skin feel"
    ) in system["content"]
    assert "must be only the ingredient target" in (
        system["content"]
    )
    assert "parent_concept, requested_change, raw_text" in (
        system["content"]
    )
    assert "ingredient_exclusion|efficacy|skin" in system["content"]
    assert "normalized_value" in system["content"]
    assert "affirm|reject|correct|supplement|replace_task|unknown" in (
        system["content"]
    )
    assert "requested_change: remove|replace" in system["content"]
    assert "remove identifies the old active value being withdrawn" in (
        system["content"]
    )
    assert "replace identifies the new value named by raw_text" in (
        system["content"]
    )
    assert "emit remove for the old value and emit the new targets" in (
        system["content"]
    )
    assert "Never emit add/retain/replace" in system["content"]
    assert "seasonal belongs in trigger, never qualifier" in (
        system["content"]
    )
    assert "persistent belongs only in duration, never qualifier" in (
        system["content"]
    )
    assert "recent is never an allowed duration; use current" in (
        system["content"]
    )
    assert "are always JSON arrays" in system["content"]
    assert "Never emit a scalar string for these three fields" in (
        system["content"]
    )
    assert "Do not use other as a filler value" in system["content"]
    assert (
        "Determine return_to_focus from the relationship between the "
        "current active mode and preserved binding authority"
    ) in system["content"]
    assert (
        "resumes a preserved product, batch, image, or consultation focus"
    ) in system["content"]
    assert "raw_text must occur exactly once" in system["content"]
    assert "choose a longer exact phrase or omit that atom" in (
        system["content"]
    )
    assert "A factual question about a product property belongs in" in (
        system["content"]
    )
    assert "Do not infer prefer or avoid from a factual question" in (
        system["content"]
    )
    assert "Generic category or usage phrases are not product names" in (
        system["content"]
    )
    assert "A complete selection request that supplies its own category" in (
        system["content"]
    )
    assert "releases or dismisses the active candidate batch" in (
        system["content"]
    )
    assert "uses new_task, never return_to_focus" in system["content"]
    assert "Explicitly returning to an earlier preserved focus" in (
        system["content"]
    )
    assert "Pending confirmation or rejection" in system["content"]
    assert "affirm is valid only when no budget candidate is emitted" in (
        system["content"]
    )
    assert "a new source-grounded budget relation requires correct" in (
        system["content"]
    )
    assert "Repeating a rejected proposal's number under negation" in (
        system["content"]
    )
    assert "followup and continue are forbidden" in system["content"]
    assert "A pending rejection without a new numeric amount emits no" in (
        system["content"]
    )
    assert "Oiliness and dryness are observations or base-skin evidence" in (
        system["content"]
    )
    assert "A question about the currently identified image product uses" in (
        system["content"]
    )
    assert "A confirmed image identity is a bound product" in (
        system["content"]
    )
    assert "image_identity is allowed only when product identity" in (
        system["content"]
    )
    assert "confirmed_image_ordinals" in system["content"]
    assert "must never use image_identity" in system["content"]
    assert "asking, confirming, or repeating its product name" in (
        system["content"]
    )
    assert "price, budget fit, SPF/PA, ingredients, safety, usage" in (
        system["content"]
    )
    assert "whether a bound product or image fits" in system["content"]
    assert (
        "updates a suitability conclusion for a\nbound product or image"
        in system["content"]
    )
    assert (
        "standalone definition, distinction, mechanism, or general safety "
        "question"
        in system["content"]
    )
    assert "next_observation_gap must be null outside assessment" in (
        system["content"]
    )
    assert (
        "reference_unclear is an observation code, never a "
        "next_observation_gap"
    ) in system["content"]
    assert "Use the supplied binding_authority" in system["content"]
    assert "batch_size_hint" in system["content"]
    assert "A requested batch smaller than the visible batch is ambiguous" in (
        system["content"]
    )
    assert (
        "When active_dialogue=consultation and awaiting_reply=true"
        in system["content"]
    )
    assert "a direct symptom," in system["content"]
    assert (
        "location, duration, tolerance, or correction answer uses continue."
        in system["content"]
    )
    assert (
        "A subject switch from other to self is new_task"
        in system["content"]
    )
    assert (
        "An ambiguous reference remains clarification"
        in system["content"]
    )
    assert (
        "never inherit active_topic from an earlier shopping task"
        in system["content"]
    )
    assert (
        "temporary named-product suitability detour"
        in system["content"]
    )
    assert "reuses the active" in system["content"]
    assert "consultation state uses continue" in (
        system["content"]
    )
    assert "texture.refreshing" in system["content"]
    assert "efficacy.soothing" in system["content"]
    assert "route stage" not in system["content"].casefold()
    assert "detail stage" not in system["content"].casefold()
    assert '"start"' not in system["content"]
    assert '"end"' not in system["content"]
    for forbidden in (
        "product_id",
        "candidate_id",
        "TaskPlan",
    ):
        assert forbidden in system["content"]
        assert f"Never emit {forbidden}" in system["content"]

    payload = json.loads(user["content"])
    assert payload == {
        "binding_authority": {
            "active_dialogue": "consultation",
            "awaiting_reply": True,
            "candidate_ordinals": [1, 2],
            "current_batch_available": True,
            "confirmed_image_ordinals": [1],
            "current_image_ordinal": None,
            "current_item_available": True,
            "current_item_ordinal": 1,
            "current_topic": "sunscreen",
            "image_ordinals": [1],
            "pending_clarification": None,
            "previous_constraint_kinds": ["budget", "category"],
        },
        "message": "换个更清爽的，预算三百以内",
    }


def test_prompt_rejects_unordered_or_invalid_concept_catalog() -> None:
    for catalog in (
        ("texture.refreshing", "efficacy.soothing"),
        ("texture.refreshing", "texture.refreshing"),
        ("refreshing",),
    ):
        try:
            build_turn_meaning_messages(
                "想清爽一点",
                _authority(),
                concept_catalog=catalog,
            )
        except ValueError:
            continue
        raise AssertionError(f"invalid catalog accepted: {catalog!r}")
