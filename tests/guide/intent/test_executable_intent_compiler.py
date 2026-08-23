from __future__ import annotations

from decimal import Decimal

import pytest

from app.guide.feedback.contracts import (
    RecommendationQueryContext,
    StoredConcept,
)
from app.guide.intent.concept_preferences import (
    ConceptCatalogEntry,
    ConceptPreferenceCatalog,
)
from app.guide.intent.contracts import (
    CategoryConstraint,
    ConceptConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    SkinConstraint,
)
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.intent.task_planning import plan_task
from app.guide.intent.transition_planning import (
    plan_code_owned_transitions,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.contracts import (
    CategoryDraft,
    SkinTarget,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import (
    ActiveConstraintKind,
    ClarificationCode,
    ConfirmedProfileField,
    SemanticContext,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


def _meaning(**updates) -> TurnMeaning:
    payload = {
        "operation_hint": "recommendation",
        "recommendation_mode": "explore",
        "recommendation_count": None,
        "recommendation_mode_basis": {
            "basis": "broad_exploration",
            "source_text": "推荐",
        },
        "topic_hint": "sunscreen",
        "reference_mentions": [],
        "product_mentions": [],
        "budget_candidates": [],
        "observation_candidates": [],
        "preference_candidates": [],
        "relative_candidates": [],
        "question_meaning": None,
        "safety_language": "ordinary",
    }
    payload.update(updates)
    if (
        payload["operation_hint"]
        in {"recommendation", "image_similarity"}
        and "recommendation_mode_basis" not in updates
    ):
        source_text = next(
            (
                str(item["raw_text"])
                for field in (
                    "preference_candidates",
                    "budget_candidates",
                    "constraint_changes",
                    "relative_candidates",
                    "reference_mentions",
                    "product_mentions",
                    "observation_candidates",
                )
                for item in payload.get(field, ())
                if item.get("raw_text")
            ),
            "推荐",
        )
        payload["recommendation_mode_basis"] = {
            **payload["recommendation_mode_basis"],
            "basis": (
                "similar_alternatives"
                if payload["operation_hint"] == "image_similarity"
                else payload["recommendation_mode_basis"]["basis"]
            ),
            "source_text": source_text,
        }
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


def _context(
    *,
    topic: TopicCode | None = None,
    active_dialogue: str | None = None,
    awaiting_reply: bool = False,
    candidates: int = 0,
    focused: int | None = None,
    images: int = 0,
    focused_image: int | None = None,
    constraints: tuple[ActiveConstraintKind, ...] = (),
    pending: ClarificationCode | None = None,
    recommendation_mode: str | None = None,
    recommendation_mode_basis: str | None = None,
    recommendation_count: int | None = None,
) -> SemanticContext:
    return SemanticContext(
        conversation_version=2 if candidates or topic or images else 0,
        active_topic=topic,
        active_dialogue=active_dialogue,
        awaiting_reply=awaiting_reply,
        active_recommendation_mode=recommendation_mode,
        active_recommendation_mode_basis=(
            recommendation_mode_basis
        ),
        active_recommendation_count=recommendation_count,
        visible_candidate_count=candidates,
        focused_candidate_ordinal=focused,
        image_count=images,
        focused_image_ordinal=focused_image,
        active_constraint_kinds=constraints,
        pending_clarification=pending,
        confirmed_profile_fields=(
            (ConfirmedProfileField.PREFERRED_CATEGORY,)
            if topic is not None
            else ()
        ),
    )


def _concept_catalog() -> ConceptPreferenceCatalog:
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


def test_relative_current_item_compiles_bound_requirement() -> None:
    understanding = compile_turn_meaning(
        message="换个更清爽的",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="skincare",
            relative_candidates=[
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "direction": "higher",
                    "raw_text": "更清爽",
                    "baseline_hint": "current_item",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SKINCARE,
            candidates=2,
            focused=2,
        ),
        concept_catalog=_concept_catalog(),
    )
    task = plan_task(understanding)

    assert understanding.relative_drafts[0].baseline.kind == "current_item"
    assert task.relative_requirements[0].concept_id == "texture.refreshing"
    assert task.relative_requirements[0].direction == "higher"
    assert task.mode == "followup"


def test_named_product_reference_atom_does_not_become_context_reference(
) -> None:
    understanding = compile_turn_meaning(
        message="再和新商品比较",
        meaning=_meaning(
            operation_hint="comparison",
            topic_hint="skincare",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "新商品",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
            ],
            product_mentions=[{"raw_text": "新商品"}],
            question_meaning="比较当前商品和新商品",
        ),
        context=_context(
            topic=TopicCode.SKINCARE,
            candidates=1,
            focused=1,
        ),
        concept_catalog=_concept_catalog(),
    )

    assert understanding.goal is UnderstandingGoal.COMPARISON
    assert understanding.references == []
    assert [item.text for item in understanding.product_mentions] == [
        "新商品"
    ]
    assert understanding.uncertainties == []


def test_relative_candidate_ordinal_compiles_price_baseline() -> None:
    understanding = compile_turn_meaning(
        message="比第二款便宜",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="skincare",
            reference_mentions=[
                {
                    "raw_text": "第二款",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                }
            ],
            relative_candidates=[
                {
                    "field_key": "price",
                    "concept_id": None,
                    "direction": "lower",
                    "raw_text": "便宜",
                    "baseline_hint": "candidate_ordinal",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SKINCARE,
            candidates=3,
        ),
        concept_catalog=_concept_catalog(),
    )
    task = plan_task(understanding)

    requirement = task.relative_requirements[0]
    assert requirement.baseline.kind == "candidate_ordinal"
    assert requirement.baseline.ordinal == 2
    assert requirement.field_key == "price"
    assert requirement.direction == "lower"


def test_relative_request_without_unique_baseline_clarifies() -> None:
    understanding = compile_turn_meaning(
        message="换个更清爽的",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="skincare",
            relative_candidates=[
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "direction": "higher",
                    "raw_text": "更清爽",
                    "baseline_hint": "current_item",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SKINCARE,
            candidates=2,
            focused=None,
        ),
        concept_catalog=_concept_catalog(),
    )
    task = plan_task(understanding)

    assert understanding.relative_drafts == []
    assert task.mode == "clarify"
    assert task.clarification_code.value == "reference"


def test_reviewed_concept_identity_survives_executable_compilation() -> None:
    understanding = compile_turn_meaning(
        message="推荐清爽防晒",
        meaning=_meaning(
            preference_candidates=[
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "raw_text": "清爽",
                    "polarity": "prefer",
                    "strength": "ordinary",
                }
            ],
        ),
        context=_context(),
        concept_catalog=_concept_catalog(),
    )
    task = plan_task(understanding)

    assert understanding.preference_drafts[0].preference_kind == "concept"
    concept = next(
        item
        for item in task.constraints
        if isinstance(item, ConceptConstraint)
    )
    assert concept.concept_id == "texture.refreshing"


def test_recommendation_hint_compiles_to_executable_task() -> None:
    understanding = compile_turn_meaning(
        message="推荐清爽防晒",
        meaning=_meaning(
            preference_candidates=[
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "raw_text": "清爽",
                    "polarity": "prefer",
                    "strength": "ordinary",
                }
            ],
        ),
        context=_context(),
        concept_catalog=_concept_catalog(),
    )
    task = plan_task(understanding)

    assert understanding.goal is UnderstandingGoal.RECOMMENDATION
    assert understanding.topic is TopicCode.SUNSCREEN
    assert understanding.preference_drafts[0].value == "清爽"
    assert understanding.recommendation_mode == "explore"
    assert understanding.recommendation_count is None
    assert understanding.recommendation_mode_basis == (
        "broad_exploration"
    )
    assert task.mode == "recommend"
    assert task.recommendation_mode == "explore"
    assert task.recommendation_count == 3
    assert task.recommendation_mode_basis == "broad_exploration"


def test_compiler_rejects_ungrounded_recommendation_basis() -> None:
    with pytest.raises(
        ValueError,
        match="recommendation mode basis must be source-grounded",
    ):
        compile_turn_meaning(
            message="给我找清爽防晒",
            meaning=_meaning(
                topic_hint="sunscreen",
                recommendation_mode_basis={
                    "basis": "broad_exploration",
                    "source_text": "推荐三款",
                },
                preference_candidates=[
                    {
                        "field_key": "texture",
                        "concept_id": "texture.refreshing",
                        "raw_text": "清爽",
                        "polarity": "prefer",
                        "strength": "ordinary",
                    }
                ],
            ),
            context=_context(),
            concept_catalog=_concept_catalog(),
        )


def test_new_task_does_not_inherit_previous_topic() -> None:
    understanding = compile_turn_meaning(
        message="给我推荐一些",
        meaning=_meaning(
            topic_hint=None,
            continuity_hint="new_task",
            recommendation_count=None,
        ),
        context=_context(topic=TopicCode.SUNSCREEN),
    )

    assert understanding.topic is None
    assert not any(
        isinstance(item, CategoryDraft)
        for item in understanding.exact_constraints
    )
    assert [item.code for item in understanding.uncertainties] == [
        "missing_category"
    ]


def test_provider_count_without_source_evidence_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="recommendation count must be source-grounded",
    ):
        compile_turn_meaning(
            message="给我推荐防晒",
            meaning=_meaning(
                recommendation_count=3,
                recommendation_mode_basis={
                    "basis": "broad_exploration",
                    "source_text": "推荐",
                },
            ),
            context=_context(),
        )


def test_source_bound_oily_and_sensitive_meaning_projects_task_skin(
) -> None:
    message = "替同事找防晒，她皮肤又出油又易敏，价格上限500"
    catalog = ConceptPreferenceCatalog(
        entries=(
            ConceptCatalogEntry(
                profile=CategoryProfile.SUNCARE,
                field_key="suitable_skin",
                concept_id="suitable_skin.oily",
            ),
            ConceptCatalogEntry(
                profile=CategoryProfile.SUNCARE,
                field_key="suitable_skin",
                concept_id="suitable_skin.sensitive",
            ),
        )
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="recommendation",
            topic_hint="sunscreen",
            continuity_hint="new_task",
            subject_scope_hint="other",
            budget_candidates=[
                {
                    "raw_text": "价格上限500",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "500",
                }
            ],
            observation_candidates=[
                {
                    "observation_id": "obs_oiliness",
                    "code": "oiliness",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "出油",
                    "location": "unknown",
                    "trigger": "unknown",
                    "duration": "unknown",
                    "severity": "unknown",
                },
                {
                    "observation_id": "obs_sensitivity",
                    "code": "product_tolerance",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "易敏",
                    "location": "unknown",
                    "trigger": "unknown",
                    "duration": "unknown",
                    "severity": "unknown",
                },
            ],
            preference_candidates=[
                {
                    "field_key": "suitable_skin",
                    "concept_id": "suitable_skin.oily",
                    "polarity": "prefer",
                    "raw_text": "出油",
                    "strength": "ordinary",
                },
                {
                    "field_key": "suitable_skin",
                    "concept_id": "suitable_skin.sensitive",
                    "polarity": "prefer",
                    "raw_text": "易敏",
                    "strength": "ordinary",
                },
            ],
        ),
        context=_context(),
        concept_catalog=catalog,
    )
    task = plan_task(understanding)

    skin = next(
        item
        for item in task.constraints
        if isinstance(item, SkinConstraint)
    )
    assert skin.value is SkinTarget.OILY_SENSITIVE
    assert understanding.uncertainties == []


def test_preference_without_topic_is_deferred_and_auditable() -> None:
    understanding = compile_turn_meaning(
        message="想要清爽一点的",
        meaning=_meaning(
            topic_hint=None,
            preference_candidates=[
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "raw_text": "清爽一点",
                    "polarity": "prefer",
                    "strength": "ordinary",
                }
            ],
        ),
        context=_context(),
        concept_catalog=_concept_catalog(),
    )

    assert understanding.preference_drafts == []
    assert (
        "preference:deferred_until_topic:"
        "texture.refreshing:清爽一点"
        in understanding.semantic_proposals
    )
    assert plan_task(understanding).mode == "clarify"


def test_efficacy_only_recommendation_infers_broad_skincare_topic() -> None:
    message = "先按修护和保湿优先，预算二百"
    catalog = ConceptPreferenceCatalog(
        entries=(
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                concept_id="efficacy.hydration",
                source_values=("保湿",),
            ),
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                concept_id="efficacy.moisturizing",
                source_values=("滋养", "滋润"),
            ),
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                concept_id="efficacy.repair",
                source_values=("修护",),
            ),
        )
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            topic_hint=None,
            continuity_hint="continue",
            budget_candidates=[
                {
                    "raw_text": "预算二百",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "200",
                }
            ],
            preference_candidates=[
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.repair",
                    "raw_text": "修护",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.moisturizing",
                    "raw_text": "保湿",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ],
        ),
        context=_context(),
        concept_catalog=catalog,
    )
    task = plan_task(understanding)

    assert understanding.topic is TopicCode.SKINCARE
    assert not any(
        issue.code == "missing_category"
        for issue in understanding.uncertainties
    )
    assert task.mode == "recommend"
    assert {
        item.concept_id
        for item in task.constraints
        if isinstance(item, ConceptConstraint)
    } == {
        "efficacy.hydration",
        "efficacy.repair",
    }


def test_suitability_hint_uses_admitted_current_item() -> None:
    understanding = compile_turn_meaning(
        message="这个适合我吗",
        meaning=_meaning(
            operation_hint="suitability",
            topic_hint="sunscreen",
            reference_mentions=[
                {
                    "raw_text": "这个",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            question_meaning="询问当前防晒是否适合",
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            candidates=1,
            focused=1,
        ),
    )
    task = plan_task(understanding)

    assert understanding.references[0].kind == "current_item"
    assert task.mode == "suitability"


def test_continuing_suitability_uses_unique_current_item_without_pronoun(
) -> None:
    understanding = compile_turn_meaning(
        message="我最近刚好泛红刺痛，结论需要怎么调整",
        meaning=_meaning(
            operation_hint="suitability",
            topic_hint="sunscreen",
            continuity_hint="continue",
            observation_candidates=[
                {
                    "observation_id": "obs_redness",
                    "code": "redness",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "泛红",
                    "location": "unknown",
                    "trigger": "unknown",
                    "duration": "current",
                    "severity": "unknown",
                },
                {
                    "observation_id": "obs_stinging",
                    "code": "stinging",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "刺痛",
                    "location": "unknown",
                    "trigger": "unknown",
                    "duration": "current",
                    "severity": "unknown",
                },
            ],
            question_meaning="当前商品的适配结论需要怎么调整",
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            candidates=1,
            focused=1,
            images=1,
            focused_image=1,
        ),
    )

    assert [
        (reference.kind, reference.ordinal)
        for reference in understanding.references
    ] == [("current_item", None)]
    assert understanding.uncertainties == []
    assert plan_task(understanding).mode == "suitability"


def test_collecting_consultation_does_not_inherit_stale_current_item(
) -> None:
    understanding = compile_turn_meaning(
        message="确认",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="serum",
            continuity_hint="continue",
            question_meaning=(
                "User confirms the pending consultation reply."
            ),
        ),
        context=_context(
            topic=TopicCode.SERUM,
            active_dialogue="consultation",
            awaiting_reply=True,
            candidates=3,
            focused=2,
        ),
    )

    assert understanding.goal is UnderstandingGoal.FOLLOWUP
    assert understanding.references == []


def test_image_suitability_question_does_not_become_attribute_filter_issue(
) -> None:
    understanding = compile_turn_meaning(
        message="识别出的防晒对容易敏感的皮肤友好吗",
        meaning=_meaning(
            operation_hint="suitability",
            topic_hint="sunscreen",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "识别出的防晒",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            question_meaning="识别出的防晒是否适合敏感皮肤",
        ),
        context=SemanticContext(
            conversation_version=1,
            active_topic=TopicCode.SUNSCREEN,
            visible_candidate_count=0,
            image_count=1,
            focused_image_ordinal=1,
            active_constraint_kinds=(),
            confirmed_profile_fields=(),
        ),
    )
    task = plan_task(
        understanding,
        resolved_product_ids=(53,),
    )

    assert understanding.uncertainties == []
    assert task.mode == "suitability"
    assert task.product_ids == [53]


def test_image_suitability_ignores_redundant_ordinary_preference_issue(
) -> None:
    message = "图片识别到的防晒，敏感肤质考虑可以吗"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="suitability",
            topic_hint="sunscreen",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "图片识别到的防晒",
                    "object_family_hint": "image",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                }
            ],
            observation_candidates=[
                {
                    "observation_id": "obs_sensitivity",
                    "code": "product_tolerance",
                    "present": True,
                    "qualifier": "candidate",
                    "raw_text": "敏感肤质",
                    "location": None,
                    "trigger": None,
                    "duration": None,
                    "severity": None,
                }
            ],
            preference_candidates=[
                {
                    "field_key": "suitable_skin",
                    "concept_id": "suitable_skin.sensitive",
                    "polarity": "prefer",
                    "raw_text": "敏感肤质",
                    "strength": "ordinary",
                }
            ],
            question_meaning="询问图片商品是否适合敏感肤质",
        ),
        context=SemanticContext(
            conversation_version=1,
            active_topic=TopicCode.SUNSCREEN,
            visible_candidate_count=0,
            image_count=1,
            focused_image_ordinal=1,
            active_constraint_kinds=(),
            confirmed_profile_fields=(),
        ),
    )
    task = plan_task(
        understanding,
        resolved_product_ids=(53,),
    )

    assert understanding.uncertainties == []
    assert task.mode == "suitability"
    assert task.product_ids == [53]


def test_bound_product_usage_question_ignores_routine_product_category(
) -> None:
    understanding = compile_turn_meaning(
        message="B5精华涂完会粘吗，放在面霜前还是后",
        meaning=_meaning(
            operation_hint="knowledge",
            topic_hint="serum",
            continuity_hint="new_task",
            product_mentions=[{"raw_text": "B5精华"}],
            question_meaning="询问B5精华质地和相对面霜的使用顺序",
        ),
        context=_context(),
    )
    task = plan_task(
        understanding,
        resolved_product_ids=(38,),
        message="B5精华涂完会粘吗，放在面霜前还是后",
    )

    assert understanding.uncertainties == []
    assert task.mode == "knowledge"
    assert task.product_ids == [38]


def test_bound_followup_uses_product_topic_over_relation_topic() -> None:
    message = "第二个候选和面霜怎么叠"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="serum",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "第二个候选",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                },
                {
                    "raw_text": "面霜",
                    "object_family_hint": "topic",
                    "ordinal_hint": None,
                    "plurality_hint": "unknown",
                },
            ],
            question_meaning="询问第二个候选与面霜的叠加顺序",
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=2,
        ),
    )
    task = plan_task(
        understanding,
        resolved_product_ids=(91,),
        message=message,
    )

    assert understanding.uncertainties == []
    assert understanding.goal is UnderstandingGoal.FOLLOWUP
    assert understanding.topic is TopicCode.SERUM
    assert task.mode == "followup"
    assert task.product_ids == [91]


def test_bound_followup_keeps_active_topic_when_relation_is_not_tagged(
) -> None:
    message = "只说二号商品，吸收后会不会影响后续面霜"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="serum",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "二号商品",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                }
            ],
            question_meaning="询问二号商品与后续面霜的叠加关系",
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=2,
        ),
    )
    task = plan_task(
        understanding,
        resolved_product_ids=(91,),
        message=message,
    )

    assert understanding.uncertainties == []
    assert understanding.goal is UnderstandingGoal.FOLLOWUP
    assert understanding.topic is TopicCode.SERUM
    assert task.mode == "followup"
    assert task.product_ids == [91]


def test_factual_topic_reference_does_not_compete_with_product_ordinal(
) -> None:
    message = "我想知道第二瓶和水类产品的先后顺序"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="serum",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "第二瓶",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                },
                {
                    "raw_text": "水类产品",
                    "object_family_hint": "topic",
                    "ordinal_hint": None,
                    "plurality_hint": "batch",
                },
            ],
            question_meaning="询问第二瓶和水类产品的使用先后顺序",
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=2,
        ),
    )
    task = plan_task(
        understanding,
        resolved_product_ids=(91,),
        message=message,
    )

    assert understanding.uncertainties == []
    assert [item.kind for item in understanding.references] == [
        "candidate_ordinal"
    ]
    assert task.mode == "followup"
    assert task.product_ids == [91]


@pytest.mark.parametrize(
    ("message", "first_product", "second_product"),
    (
        (
            "回到精华，B5精华和玉泽屏障修护精华做比较",
            "B5精华",
            "玉泽屏障修护精华",
        ),
        (
            "继续精华这条线，对比B5精华与CE精华",
            "B5精华",
            "CE精华",
        ),
    ),
)
def test_matching_topic_return_does_not_compete_with_explicit_products(
    message: str,
    first_product: str,
    second_product: str,
) -> None:
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="comparison",
            topic_hint="serum",
            continuity_hint="return_to_focus",
            reference_mentions=[
                {
                    "raw_text": "精华",
                    "object_family_hint": "topic",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            product_mentions=[
                {"raw_text": first_product},
                {"raw_text": second_product},
            ],
        ),
        context=_context(topic=TopicCode.SERUM, candidates=2),
    )

    assert understanding.uncertainties == []
    assert [item.text for item in understanding.product_mentions] == [
        first_product,
        second_product,
    ]


def test_mismatched_topic_return_still_requires_clarification() -> None:
    message = "回到精华，B5精华和玉泽屏障修护精华做比较"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="comparison",
            topic_hint="serum",
            continuity_hint="return_to_focus",
            reference_mentions=[
                {
                    "raw_text": "精华",
                    "object_family_hint": "topic",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            product_mentions=[
                {"raw_text": "B5精华"},
                {"raw_text": "玉泽屏障修护精华"},
            ],
        ),
        context=_context(topic=TopicCode.SUNSCREEN, candidates=2),
    )

    assert [item.code for item in understanding.uncertainties] == [
        "ambiguous_reference"
    ]


def test_return_to_focus_uses_preserved_current_item_without_reference_atom(
) -> None:
    understanding = compile_turn_meaning(
        message="结束这个知识话题，回前面聚焦商品说用法",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="serum",
            continuity_hint="return_to_focus",
            question_meaning="回到之前商品查看用法",
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=2,
            focused=2,
        ),
    )
    task = plan_task(
        understanding,
        resolved_product_ids=(91,),
    )

    assert understanding.uncertainties == []
    assert task.mode == "followup"
    assert task.product_ids == [91]


def test_current_item_and_matching_candidate_ordinal_share_one_authority(
) -> None:
    understanding = compile_turn_meaning(
        message="回到第二支，它在户外场景的资料够不够",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="sunscreen",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "第二支",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                }
            ],
            question_meaning="询问第二支防晒的户外资料",
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            candidates=2,
            focused=2,
        ),
    )

    assert [
        (reference.kind, reference.ordinal)
        for reference in understanding.references
    ] == [("current_item", None)]
    assert understanding.uncertainties == []


def test_current_item_and_different_candidate_ordinal_remain_distinct(
) -> None:
    understanding = compile_turn_meaning(
        message="第二支和它分别有什么资料",
        meaning=_meaning(
            operation_hint="comparison",
            topic_hint="sunscreen",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "第二支",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                }
            ],
            question_meaning="比较第二支和当前商品",
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            candidates=2,
            focused=1,
        ),
    )

    assert {
        (reference.kind, reference.ordinal)
        for reference in understanding.references
    } == {
        ("current_item", None),
        ("candidate_ordinal", 2),
    }


def test_pending_reference_clarification_with_product_name_becomes_knowledge(
) -> None:
    message = "我指理肤泉新B5多效修护精华"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="clarification",
            topic_hint="serum",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "理肤泉新B5多效修护精华",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            product_mentions=[
                {"raw_text": "理肤泉新B5多效修护精华"}
            ],
            question_meaning="澄清当前商品身份",
        ),
        context=_context(
            topic=None,
            candidates=0,
            pending=ClarificationCode.REFERENCE,
        ),
    )

    assert understanding.goal is UnderstandingGoal.KNOWLEDGE
    assert [
        mention.text for mention in understanding.product_mentions
    ] == ["理肤泉新B5多效修护精华"]
    assert understanding.uncertainties == []


def test_overlapping_product_surface_preserves_typed_current_reference(
) -> None:
    message = "回到玉泽那支，早上叠防晒该留意什么"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="serum",
            continuity_hint="return_to_focus",
            reference_mentions=[
                {
                    "raw_text": "玉泽那支",
                    "object_family_hint": "product",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                }
            ],
            product_mentions=[{"raw_text": "玉泽那支"}],
            question_meaning="查询当前商品叠加防晒的注意事项",
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=1,
            focused=1,
        ),
    )

    assert [item.text for item in understanding.product_mentions] == [
        "玉泽那支"
    ]
    assert [
        (item.kind, item.ordinal)
        for item in understanding.references
    ] == [("current_item", None)]
    assert understanding.uncertainties == []


def test_unbound_followup_fails_closed_with_reference_clarification() -> None:
    understanding = compile_turn_meaning(
        message="改成另一个吧",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="sunscreen",
            reference_mentions=[
                {
                    "raw_text": "另一个",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            candidates=3,
            focused=None,
        ),
    )
    task = plan_task(understanding)

    assert task.mode == "clarify"
    assert task.clarification_code.value == "reference"
    assert task.clarification == (
        "当前说法还没有唯一对应到商品、图片或之前的条件，"
        "请明确具体对象。"
    )


def test_exact_narrow_topic_wins_without_rejecting_open_observation() -> None:
    understanding = compile_turn_meaning(
        message="洁面后紧绷起皮，帮我看看",
        meaning=_meaning(
            operation_hint="assessment",
            topic_hint="skincare",
            observation_candidates=[
                {
                    "code": "tightness",
                    "present": True,
                    "qualifier": "post_cleanse",
                    "raw_text": "洁面后紧绷",
                },
                {
                    "code": "flaking",
                    "present": True,
                    "qualifier": "post_cleanse",
                    "raw_text": "起皮",
                },
            ],
            question_meaning="分析洁面后的紧绷起皮",
        ),
        context=_context(),
    )

    assert understanding.topic is TopicCode.CLEANSER
    assert "tightness:present:post_cleanse" in understanding.observations
    assert understanding.uncertainties == []


def test_ingredient_exclusion_parent_projects_canonical_target() -> None:
    understanding = compile_turn_meaning(
        message="给我找防晒，先避开乙醇",
        meaning=_meaning(
            operation_hint="recommendation",
            topic_hint="sunscreen",
            preference_candidates=[
                {
                    "field_key": "ingredient_exclusion",
                    "concept_id": None,
                    "raw_text": "乙醇",
                    "polarity": "avoid",
                    "strength": "ordinary",
                }
            ],
        ),
        context=_context(),
        concept_catalog=_concept_catalog(),
    )
    task = plan_task(understanding)

    assert [
        item.value
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ] == ["酒精"]
    assert task.free_descriptors == []


def test_ingredient_exclusion_withdrawal_uses_semantic_parent_change() -> None:
    message = "酒精这一条放开，继续看防晒"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="recommendation",
            topic_hint="sunscreen",
            continuity_hint="continue",
            constraint_changes=[
                {
                    "parent_concept": "ingredient_exclusion",
                    "requested_change": "remove",
                    "raw_text": "酒精",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            constraints=(
                ActiveConstraintKind.CATEGORY,
                ActiveConstraintKind.INGREDIENT_EXCLUSION,
            ),
        ),
        concept_catalog=_concept_catalog(),
    )
    planned = plan_code_owned_transitions(
        message=message,
        understanding=understanding,
        task=plan_task(understanding),
        previous=RecommendationQueryContext(
            category="sunscreen",
            recommendation_mode_basis="broad_exploration",
            exclusions=("酒精",),
        ),
        continuation_requested=True,
    )

    assert planned.task_plan.mode == "recommend"
    assert not any(
        isinstance(item, ExclusionConstraint)
        for item in planned.task_plan.constraints
    )
    assert planned.transition_result is not None
    assert {
        (
            item.target,
            item.operation,
            item.authority,
        )
        for item in planned.transition_result.transitions
    } >= {
        ("exclusion:酒精", "remove", "validated_semantic"),
    }


def test_semantic_topic_survives_supplement_transition() -> None:
    message = "预算放到一百五，仍然要清爽通勤"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="recommendation",
            topic_hint="sunscreen",
            continuity_hint="continue",
            budget_candidates=[
                {
                    "raw_text": "一百五",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "150",
                }
            ],
            preference_candidates=[
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "raw_text": "清爽",
                    "polarity": "prefer",
                    "strength": "ordinary",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            constraints=(ActiveConstraintKind.CATEGORY,),
        ),
        concept_catalog=_concept_catalog(),
    )
    planned = plan_code_owned_transitions(
        message=message,
        understanding=understanding,
        task=plan_task(understanding),
        previous=RecommendationQueryContext(
            category="sunscreen",
            recommendation_mode_basis="broad_exploration",
            budget_maximum=Decimal("100"),
        ),
        continuation_requested=True,
    )

    assert planned.task_plan.mode == "recommend"
    assert any(
        isinstance(item, CategoryConstraint)
        and item.value is TopicCode.SUNSCREEN
        for item in planned.task_plan.constraints
    )
    assert any(
        item.target == "budget" and item.operation == "replace"
        for item in planned.transition_result.transitions
    )
    assert not any(
        item.target == "category"
        for item in planned.transition_result.transitions
    )


def test_budget_revision_uses_existing_code_owned_reducer() -> None:
    message = "预算改成三百以内，而且还是不要含酒精的呢"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="sunscreen",
            reference_mentions=[
                {
                    "raw_text": "预算",
                    "object_family_hint": "constraint",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            budget_candidates=[
                {
                    "raw_text": "三百以内",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "300",
                }
            ],
            preference_candidates=[
                {
                    "field_key": "ingredient_exclusion",
                    "concept_id": None,
                    "raw_text": "不要含酒精",
                    "polarity": "avoid",
                    "strength": "safety",
                }
            ],
            safety_language="safety",
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            candidates=3,
            recommendation_mode="fit",
            recommendation_mode_basis="personal_suitability",
            recommendation_count=1,
            constraints=(
                ActiveConstraintKind.BUDGET,
                ActiveConstraintKind.CATEGORY,
                ActiveConstraintKind.INGREDIENT_EXCLUSION,
            ),
        ),
    )
    assert understanding.recommendation_mode == "fit"
    assert (
        understanding.recommendation_mode_basis
        == "personal_suitability"
    )
    assert understanding.recommendation_count == 1
    task = plan_task(understanding)
    planned = plan_code_owned_transitions(
        message=message,
        understanding=understanding,
        task=task,
        previous=RecommendationQueryContext(
            category="sunscreen",
            recommendation_mode="fit",
            recommendation_mode_basis="personal_suitability",
            recommendation_count=1,
            budget_maximum=Decimal("500"),
            exclusions=("酒精",),
            similarity_anchor_product_id=53,
            safety_sensitive=True,
        ),
    )

    assert planned.task_plan.mode == "recommend"
    assert planned.task_plan.similarity_anchor_product_id == 53
    assert planned.transition_result is not None
    operations = {
        transition.target: transition.operation
        for transition in planned.transition_result.transitions
    }
    assert operations["budget"] == "replace"
    assert operations["exclusion:酒精"] == "retain"


def test_untyped_efficacy_action_does_not_use_wording_parser() -> None:
    message = "抗老先撤掉，改成保湿修护优先"
    catalog = ConceptPreferenceCatalog(
        entries=tuple(
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                concept_id=concept_id,
            )
            for concept_id in (
                "efficacy.anti_aging",
                "efficacy.hydration",
                "efficacy.repair",
            )
        )
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="recommendation",
            topic_hint="serum",
            continuity_hint="continue",
            preference_candidates=[
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.anti_aging",
                    "raw_text": "抗老",
                    "polarity": "avoid",
                    "strength": "ordinary",
                },
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.hydration",
                    "raw_text": "保湿",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.repair",
                    "raw_text": "修护",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ],
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=1,
            constraints=(
                ActiveConstraintKind.BUDGET,
                ActiveConstraintKind.CATEGORY,
                ActiveConstraintKind.EFFICACY,
            ),
        ),
        concept_catalog=catalog,
    )
    planned = plan_code_owned_transitions(
        message=message,
        understanding=understanding,
        task=plan_task(understanding),
        previous=RecommendationQueryContext(
            category="serum",
            recommendation_mode_basis="broad_exploration",
            budget_maximum=Decimal("400"),
            efficacy="anti_aging",
            concepts=(
                StoredConcept(
                    field_key="efficacy",
                    concept_id="efficacy.anti_aging",
                    polarity="prefer",
                ),
            ),
        ),
        continuation_requested=True,
    )

    assert planned.task_plan.mode == "clarify"
    assert planned.transition_result is not None
    assert [
        issue.code
        for issue in planned.transition_result.issues
    ] == ["confirm_hard_constraint_revision"]


def test_typed_efficacy_withdrawal_replaces_old_quiz_without_parser(
    monkeypatch,
) -> None:
    message = "抗老先撤掉，改成保湿修护优先"
    catalog = ConceptPreferenceCatalog(
        entries=tuple(
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                concept_id=concept_id,
            )
            for concept_id in (
                "efficacy.hydration",
                "efficacy.repair",
            )
        )
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="recommendation",
            topic_hint="serum",
            continuity_hint="continue",
            preference_candidates=[
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.hydration",
                    "raw_text": "保湿",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.repair",
                    "raw_text": "修护",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ],
            constraint_changes=[
                {
                    "parent_concept": "efficacy",
                    "requested_change": "remove",
                    "raw_text": "抗老",
                    "normalized_value": "anti_aging",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=1,
            constraints=(
                ActiveConstraintKind.BUDGET,
                ActiveConstraintKind.CATEGORY,
                ActiveConstraintKind.EFFICACY,
            ),
        ),
        concept_catalog=catalog,
    )
    monkeypatch.setattr(
        "app.guide.intent.transition_planning."
        "parse_exact_revision_confirmations",
        lambda message: (_ for _ in ()).throw(
            AssertionError("semantic path called exact action parser")
        ),
    )
    monkeypatch.setattr(
        "app.guide.intent.transition_planning."
        "parse_exact_efficacy_withdrawals",
        lambda message: (_ for _ in ()).throw(
            AssertionError("semantic path called efficacy wording parser")
        ),
    )

    planned = plan_code_owned_transitions(
        message=message,
        understanding=understanding,
        task=plan_task(understanding),
        previous=RecommendationQueryContext(
            category="serum",
            recommendation_mode_basis="broad_exploration",
            budget_maximum=Decimal("400"),
            efficacy="anti_aging",
            concepts=(
                StoredConcept(
                    field_key="efficacy",
                    concept_id="efficacy.anti_aging",
                    polarity="prefer",
                ),
            ),
        ),
        continuation_requested=True,
    )

    assert planned.task_plan.mode == "recommend"
    assert planned.transition_result is not None
    assert any(
        item.target == "efficacy"
        and item.operation == "replace"
        and item.authority == "validated_semantic"
        for item in planned.transition_result.transitions
    )
    assert not any(
        item.target == "category"
        for item in planned.transition_result.transitions
    )


def test_context_topic_is_projected_into_continuation_task_constraints(
) -> None:
    message = "抗老退出，接下来保湿优先，预算仍然四百以内"
    catalog = ConceptPreferenceCatalog(
        entries=(
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                concept_id="efficacy.hydration",
            ),
        )
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="recommendation",
            topic_hint=None,
            continuity_hint="continue",
            budget_candidates=[
                {
                    "raw_text": "四百以内",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "400",
                }
            ],
            preference_candidates=[
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.hydration",
                    "raw_text": "保湿",
                    "polarity": "prefer",
                    "strength": "ordinary",
                }
            ],
            constraint_changes=[
                {
                    "parent_concept": "efficacy",
                    "requested_change": "remove",
                    "raw_text": "抗老",
                    "normalized_value": "anti_aging",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=2,
            constraints=(
                ActiveConstraintKind.BUDGET,
                ActiveConstraintKind.CATEGORY,
                ActiveConstraintKind.EFFICACY,
            ),
        ),
        concept_catalog=catalog,
    )
    task = plan_task(understanding)

    assert understanding.topic is TopicCode.SERUM
    assert task.mode == "recommend"
    assert any(
        isinstance(item, CategoryConstraint)
        and item.value is TopicCode.SERUM
        for item in task.constraints
    )
    assert not any(
        isinstance(item, EfficacyConstraint)
        for item in task.constraints
    )
    assert any(
        isinstance(item, ConceptConstraint)
        and item.concept_id == "efficacy.hydration"
        for item in task.constraints
    )


def test_efficacy_replacement_uses_typed_parent_change(
    monkeypatch,
) -> None:
    message = "抗老这项退出，接下来重点看修护"
    catalog = ConceptPreferenceCatalog(
        entries=(
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                concept_id="efficacy.repair",
            ),
        )
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="recommendation",
            topic_hint="serum",
            continuity_hint="continue",
            constraint_changes=[
                {
                    "parent_concept": "efficacy",
                    "requested_change": "replace",
                    "raw_text": "修护",
                    "normalized_value": "repair",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SERUM,
            constraints=(
                ActiveConstraintKind.CATEGORY,
                ActiveConstraintKind.EFFICACY,
            ),
        ),
        concept_catalog=catalog,
    )
    monkeypatch.setattr(
        "app.guide.intent.transition_planning."
        "parse_exact_revision_confirmations",
        lambda message: (_ for _ in ()).throw(
            AssertionError("semantic path called exact action parser")
        ),
    )
    monkeypatch.setattr(
        "app.guide.intent.transition_planning."
        "parse_exact_efficacy_withdrawals",
        lambda message: (_ for _ in ()).throw(
            AssertionError("semantic path called efficacy wording parser")
        ),
    )
    planned = plan_code_owned_transitions(
        message=message,
        understanding=understanding,
        task=plan_task(understanding),
        previous=RecommendationQueryContext(
            category="serum",
            recommendation_mode_basis="broad_exploration",
            efficacy="anti_aging",
            concepts=(
                StoredConcept(
                    field_key="efficacy",
                    concept_id="efficacy.anti_aging",
                    polarity="prefer",
                ),
            ),
        ),
        continuation_requested=True,
    )

    assert any(
        item.target == "efficacy"
        and item.operation == "replace"
        and item.authority == "validated_semantic"
        for item in planned.transition_result.transitions
    )
    dumped = [
        item.model_dump(mode="json")
        for item in planned.task_plan.constraints
    ]
    assert {"kind": "efficacy", "value": "repair"} in dumped
    assert {
        item["concept_id"]
        for item in dumped
        if item["kind"] == "concept"
    } == set()


def test_ordinary_avoid_descriptor_is_not_vetoed_by_exact_parser() -> None:
    understanding = compile_turn_meaning(
        message="避开所有甜腻的香水",
        meaning=_meaning(
            topic_hint="fragrance",
            preference_candidates=[
                {
                    "field_key": "scent_profile",
                    "concept_id": None,
                    "raw_text": "甜腻",
                    "polarity": "avoid",
                    "strength": "ordinary",
                }
            ],
        ),
        context=_context(),
        concept_catalog=_concept_catalog(),
    )
    task = plan_task(understanding)

    assert not any(
        issue.code == "unsupported_attribute_exclusion"
        for issue in understanding.uncertainties
    )
    assert task.mode == "recommend"
    assert task.free_descriptors[0].polarity == "avoid"


def test_comparison_accepts_two_distinct_candidate_ordinals() -> None:
    message = "第一款和第二款具体差在哪"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="comparison",
            topic_hint="serum",
            reference_mentions=[
                {
                    "raw_text": "第一款",
                    "object_family_hint": "product",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                },
                {
                    "raw_text": "第二款",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                },
            ],
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=3,
        ),
    )
    task = plan_task(understanding)

    assert understanding.uncertainties == []
    assert [
        (item.kind, item.ordinal)
        for item in understanding.references
    ] == [
        ("candidate_ordinal", 1),
        ("candidate_ordinal", 2),
    ]
    assert task.mode == "comparison"


def test_suitability_preserves_two_candidate_ordinals_for_matrix() -> None:
    message = "第一款和第二款哪个更适合我"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="suitability",
            topic_hint="serum",
            reference_mentions=[
                {
                    "raw_text": "第一款",
                    "object_family_hint": "product",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                },
                {
                    "raw_text": "第二款",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                },
            ],
            question_meaning="判断两款里哪款更适合当前用户",
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=3,
        ),
    )

    assert understanding.uncertainties == []
    assert [
        (item.kind, item.ordinal)
        for item in understanding.references
    ] == [
        ("candidate_ordinal", 1),
        ("candidate_ordinal", 2),
    ]


def test_optional_unbound_knowledge_reference_does_not_force_clarify() -> None:
    understanding = compile_turn_meaning(
        message="挡紫外线的两个等级标识怎么看",
        meaning=_meaning(
            operation_hint="knowledge",
            topic_hint="sunscreen",
            reference_mentions=[
                {
                    "raw_text": "两个等级标识",
                    "object_family_hint": "topic",
                    "ordinal_hint": None,
                    "plurality_hint": "batch",
                }
            ],
            question_meaning="询问防晒等级标识",
        ),
        context=_context(),
    )
    task = plan_task(understanding)

    assert understanding.uncertainties == []
    assert task.mode == "knowledge"


def test_semantic_budget_continuation_does_not_require_wording_proof() -> None:
    message = "预算改成三百以内，而且还是不要含酒精的呢"
    understanding = compile_turn_meaning(
        message=message,
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="sunscreen",
                continuity_hint="continue",
            budget_candidates=[
                {
                    "raw_text": "三百以内",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "300",
                }
            ],
            preference_candidates=[
                {
                    "field_key": "ingredient_exclusion",
                    "concept_id": None,
                        "raw_text": "酒精",
                    "polarity": "avoid",
                    "strength": "ordinary",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            candidates=3,
            recommendation_mode="fit",
            recommendation_mode_basis="personal_suitability",
            recommendation_count=1,
            constraints=(
                ActiveConstraintKind.BUDGET,
                ActiveConstraintKind.CATEGORY,
                ActiveConstraintKind.INGREDIENT_EXCLUSION,
            ),
        ),
        concept_catalog=_concept_catalog(),
    )
    task = plan_task(understanding)
    planned = plan_code_owned_transitions(
        message=message,
        understanding=understanding,
        task=task,
        previous=RecommendationQueryContext(
            category="sunscreen",
            recommendation_mode="fit",
            recommendation_mode_basis="personal_suitability",
            recommendation_count=1,
            budget_maximum=Decimal("500"),
            exclusions=("酒精",),
            safety_sensitive=True,
        ),
        continuation_requested=True,
    )

    assert understanding.uncertainties == []
    assert planned.task_plan.mode == "recommend"
    assert planned.task_plan.recommendation_mode == "fit"
    assert (
        planned.task_plan.recommendation_mode_basis
        == "personal_suitability"
    )
    assert planned.task_plan.recommendation_count == 1
    assert {
        (item.target, item.operation)
        for item in planned.transition_result.transitions
    } >= {
        ("budget", "replace"),
        ("exclusion:酒精", "retain"),
    }


def test_recommendation_preference_shadows_unbound_relative_hint() -> None:
    understanding = compile_turn_meaning(
        message="就按这类继续给我挑清爽一点的",
        meaning=_meaning(
            topic_hint="fragrance",
            reference_mentions=[
                {
                    "raw_text": "这类",
                    "object_family_hint": "topic",
                    "ordinal_hint": None,
                    "plurality_hint": "unknown",
                }
            ],
            preference_candidates=[
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "raw_text": "清爽",
                    "polarity": "prefer",
                    "strength": "ordinary",
                }
            ],
            relative_candidates=[
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "direction": "higher",
                    "raw_text": "清爽一点",
                    "baseline_hint": "current_batch",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.FRAGRANCE,
            candidates=3,
        ),
        concept_catalog=_concept_catalog(),
    )

    assert understanding.uncertainties == []
    assert understanding.relative_drafts == []
    assert plan_task(understanding).mode == "recommend"


def test_semantic_budget_with_explicit_maximum_prefix_is_verified() -> None:
    understanding = compile_turn_meaning(
        message="它适合我吗，预算最多四百",
        meaning=_meaning(
            operation_hint="suitability",
            topic_hint="serum",
            reference_mentions=[
                {
                    "raw_text": "它",
                    "object_family_hint": "product",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                }
            ],
            budget_candidates=[
                {
                    "raw_text": "预算最多四百",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "400",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.SERUM,
            candidates=2,
            focused=1,
        ),
    )

    assert understanding.uncertainties == []
    assert any(
        item.kind == "budget" and item.maximum == Decimal("400")
        for item in understanding.exact_constraints
    )


def test_followup_hint_with_new_preference_compiles_recommendation() -> None:
    understanding = compile_turn_meaning(
        message="不要这种太甜的香水",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="fragrance",
            preference_candidates=[
                {
                    "field_key": "scent_sweetness",
                    "concept_id": None,
                    "raw_text": "太甜",
                    "polarity": "avoid",
                    "strength": "ordinary",
                }
            ],
        ),
        context=_context(
            topic=TopicCode.FRAGRANCE,
            candidates=3,
            recommendation_mode="explore",
            recommendation_mode_basis="broad_exploration",
            recommendation_count=3,
        ),
        concept_catalog=_concept_catalog(),
    )

    assert understanding.goal is UnderstandingGoal.RECOMMENDATION
    assert understanding.recommendation_mode == "explore"
    assert (
        understanding.recommendation_mode_basis
        == "broad_exploration"
    )
    assert understanding.recommendation_count == 3
    assert plan_task(understanding).mode == "recommend"


def test_bound_assessment_without_observation_compiles_product_knowledge() -> None:
    understanding = compile_turn_meaning(
        message="这款留香怎么样",
        meaning=_meaning(
            operation_hint="assessment",
            topic_hint="fragrance",
            reference_mentions=[
                {
                    "raw_text": "这款",
                    "object_family_hint": "product",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                }
            ],
            question_meaning="询问当前香水留香表现",
        ),
        context=_context(
            topic=TopicCode.FRAGRANCE,
            candidates=2,
            focused=1,
        ),
    )

    assert understanding.goal is UnderstandingGoal.KNOWLEDGE
    assert plan_task(understanding).mode == "followup"


def test_bound_assessment_with_observation_compiles_suitability() -> None:
    understanding = compile_turn_meaning(
        message="洗完脸总紧绷，这个洁面还能用吗",
        meaning=_meaning(
            operation_hint="assessment",
            topic_hint="cleanser",
            reference_mentions=[
                {
                    "raw_text": "这个洁面",
                    "object_family_hint": "product",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                }
            ],
            observation_candidates=[
                {
                    "code": "tightness",
                    "present": True,
                    "qualifier": "post_cleanse",
                    "raw_text": "洗完脸总紧绷",
                }
            ],
            question_meaning="询问当前洁面使用后紧绷是否还能继续使用",
        ),
        context=_context(
            topic=TopicCode.CLEANSER,
            candidates=1,
            focused=1,
        ),
    )

    assert understanding.goal is UnderstandingGoal.SUITABILITY
    assert plan_task(understanding).mode == "suitability"


def test_bound_clarification_question_compiles_product_knowledge() -> None:
    understanding = compile_turn_meaning(
        message="第二款提到的水感质地是什么意思",
        meaning=_meaning(
            operation_hint="clarification",
            topic_hint="sunscreen",
            reference_mentions=[
                {
                    "raw_text": "第二款",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                }
            ],
            question_meaning="询问第二款所说的水感质地含义",
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            candidates=3,
        ),
    )

    assert understanding.goal is UnderstandingGoal.KNOWLEDGE
    assert plan_task(understanding).mode == "knowledge"


def test_bound_image_similarity_keeps_code_owned_similarity_goal() -> None:
    understanding = compile_turn_meaning(
        message="第二张再看一下",
        meaning=_meaning(
            operation_hint="image_similarity",
            topic_hint=None,
            reference_mentions=[
                {
                    "raw_text": "第二张",
                    "object_family_hint": "image",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                }
            ],
        ),
        context=SemanticContext(
            conversation_version=2,
            active_topic=None,
            visible_candidate_count=0,
            image_count=2,
            confirmed_profile_fields=(),
        ),
    )

    assert understanding.goal is UnderstandingGoal.IMAGE_SIMILARITY
    task = plan_task(
        understanding,
        resolved_product_ids=(55,),
    )
    assert task.mode == "recommend"
    assert task.similarity_anchor_product_id == 55
    assert task.product_ids == []


def test_image_identity_compiles_as_a_closed_goal() -> None:
    understanding = compile_turn_meaning(
        message="帮我确认图片里的防晒是什么",
        meaning=_meaning(
            operation_hint="image_identity",
            topic_hint="sunscreen",
            question_meaning="确认图片中的商品身份",
        ),
        context=_context(images=1, focused_image=1),
    )

    assert understanding.goal is UnderstandingGoal.IMAGE_IDENTITY


def test_image_batch_reference_expands_to_current_image_ordinals() -> None:
    understanding = compile_turn_meaning(
        message="比较这三张图，按使用场景说怎么选",
        meaning=_meaning(
            operation_hint="comparison",
            topic_hint=None,
            reference_mentions=[
                {
                    "raw_text": "这三张图",
                    "object_family_hint": "image",
                    "ordinal_hint": None,
                    "plurality_hint": "batch",
                }
            ],
            question_meaning="比较三张图片中的商品",
        ),
        context=_context(images=3),
    )

    assert [
        (reference.kind, reference.ordinal)
        for reference in understanding.references
    ] == [
        ("image_ordinal", 1),
        ("image_ordinal", 2),
        ("image_ordinal", 3),
    ]
    assert understanding.uncertainties == []


def test_image_batch_size_mismatch_clarifies_instead_of_expanding() -> None:
    understanding = compile_turn_meaning(
        message="比较这两张图",
        meaning=_meaning(
            operation_hint="comparison",
            topic_hint=None,
            reference_mentions=[
                {
                    "raw_text": "这两张图",
                    "object_family_hint": "image",
                    "ordinal_hint": None,
                    "plurality_hint": "batch",
                    "batch_size_hint": 2,
                }
            ],
            question_meaning="比较两张图片中的商品",
        ),
        context=_context(images=3),
    )

    assert understanding.references == []
    assert [item.code for item in understanding.uncertainties] == [
        "ambiguous_reference"
    ]


def test_generic_product_coreference_reuses_unique_explicit_image_anchor(
) -> None:
    understanding = compile_turn_meaning(
        message="只讲第二张原商品的用法",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint="sunscreen",
            continuity_hint="continue",
            reference_mentions=[
                {
                    "raw_text": "第二张",
                    "object_family_hint": "image",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                },
                {
                    "raw_text": "原商品",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
            ],
            question_meaning="只讲第二张原商品的用法",
        ),
        context=_context(
            topic=TopicCode.SUNSCREEN,
            candidates=3,
            images=2,
        ),
        concept_catalog=_concept_catalog(),
    )

    assert [
        (reference.kind, reference.ordinal)
        for reference in understanding.references
    ] == [("image_ordinal", 2)]
    assert understanding.uncertainties == []
    assert plan_task(understanding).mode == "followup"


def test_single_image_relative_baseline_uses_current_image() -> None:
    understanding = compile_turn_meaning(
        message="找两款相似的，预算150以内，更清爽一点",
        meaning=_meaning(
            operation_hint="image_similarity",
            topic_hint=None,
            relative_candidates=[
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "direction": "higher",
                    "raw_text": "更清爽一点",
                    "baseline_hint": "image_ordinal",
                }
            ],
        ),
        context=_context(images=1, focused_image=1),
        concept_catalog=_concept_catalog(),
    )

    assert len(understanding.relative_drafts) == 1
    baseline = understanding.relative_drafts[0].baseline
    assert (baseline.kind, baseline.ordinal) == ("image_ordinal", 1)
    assert understanding.uncertainties == []


def test_exact_ordinal_is_revalidated_against_empty_authority() -> None:
    understanding = compile_turn_meaning(
        message="第二个",
        meaning=_meaning(
            operation_hint="followup",
            topic_hint=None,
            reference_mentions=[
                {
                    "raw_text": "第二个",
                    "object_family_hint": "unknown",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                }
            ],
        ),
        context=_context(),
    )

    assert understanding.references == []
    assert plan_task(understanding).mode == "clarify"
