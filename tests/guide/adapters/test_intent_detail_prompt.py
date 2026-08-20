from __future__ import annotations

import pytest

from app.guide.adapters.llm.intent_detail_prompt import (
    DETAIL_PROMPT_VERSION,
    build_detail_messages,
)
from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.semantic_route_contracts import (
    SemanticDetailStage,
    SemanticRouteProposal,
)


_GOAL_BY_STAGE = {
    SemanticDetailStage.RECOMMENDATION: UnderstandingGoal.RECOMMENDATION,
    SemanticDetailStage.ASSESSMENT: UnderstandingGoal.ASSESSMENT,
    SemanticDetailStage.COMPARISON: UnderstandingGoal.COMPARISON,
    SemanticDetailStage.FOLLOWUP: UnderstandingGoal.FOLLOWUP,
    SemanticDetailStage.KNOWLEDGE: UnderstandingGoal.KNOWLEDGE,
    SemanticDetailStage.IMAGE: UnderstandingGoal.IMAGE_SIMILARITY,
}


def _context() -> SemanticContext:
    return SemanticContext(
        conversation_version=2,
        active_topic=TopicCode.SUNSCREEN,
        visible_candidate_count=2,
        focused_candidate_ordinal=1,
        image_count=1,
        focused_image_ordinal=1,
        confirmed_profile_fields=(),
    )


def _route(stage: SemanticDetailStage) -> SemanticRouteProposal:
    return SemanticRouteProposal(
        goal=_GOAL_BY_STAGE[stage],
        topic=TopicCode.SUNSCREEN,
        detail_stage=stage,
        confidence=0.92,
        clarification_hint=None,
    )


@pytest.mark.parametrize(
    ("stage", "required", "forbidden"),
    [
        (
            SemanticDetailStage.RECOMMENDATION,
            (
                "concerns",
                "observations",
                "product_mentions",
                "number_candidates",
                "preference_candidates",
            ),
            ("references",),
        ),
        (
            SemanticDetailStage.ASSESSMENT,
            ("concerns", "observations", "product_mentions"),
            ("references", "number_candidates"),
        ),
        (
            SemanticDetailStage.COMPARISON,
            ("references", "product_mentions"),
            ("observations", "concerns"),
        ),
        (
            SemanticDetailStage.FOLLOWUP,
            (
                "references",
                "product_mentions",
                "number_candidates",
                "preference_candidates",
            ),
            ("observations", "concerns"),
        ),
        (
            SemanticDetailStage.KNOWLEDGE,
            ("concerns", "product_mentions"),
            ("references", "observations"),
        ),
        (
            SemanticDetailStage.IMAGE,
            ("references", "observations"),
            ("concerns",),
        ),
    ],
)
def test_detail_prompt_exposes_only_stage_fields(
    stage: SemanticDetailStage,
    required: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> None:
    system = build_detail_messages(
        "测试",
        _context(),
        _route(stage),
    )[0]["content"]

    assert len(system.encode("utf-8")) < 6500
    for field in (*required, "question_meaning", "safety_sensitive"):
        assert field in system
    for field in forbidden:
        assert field not in system
    assert '"acts"' not in system
    for forbidden_output in (
        "product_id",
        "candidate_id",
        "price",
        "score",
        "winner",
        "SQL",
        "profile",
    ):
        assert forbidden_output in system


def test_detail_prompt_has_frozen_version_and_rejects_none_stage() -> None:
    assert DETAIL_PROMPT_VERSION == "guide-semantic-detail-prompt-v10"
    route = SemanticRouteProposal.model_validate_json(
        (
            '{"goal":"clarification","topic":null,"detail_stage":"none",'
            '"confidence":0.3,"clarification_hint":"goal"}'
        ),
        strict=True,
    )

    with pytest.raises(ValueError, match="does not have details"):
        build_detail_messages("看看", _context(), route)


@pytest.mark.parametrize(
    "stage",
    (
        SemanticDetailStage.COMPARISON,
        SemanticDetailStage.FOLLOWUP,
    ),
)
def test_reference_stage_does_not_force_model_to_decide_executability(
    stage: SemanticDetailStage,
) -> None:
    system = build_detail_messages(
        "继续看看",
        _context(),
        _route(stage),
    )[0]["content"]

    assert "Execution sufficiency is decided by code" in system
    assert "Do not invent a reference to satisfy the schema" in system
    assert "At least one reference or product mention is required" not in (
        system
    )


def test_detail_prompt_keeps_safety_boolean_out_of_concerns() -> None:
    system = build_detail_messages(
        "医美后一定安全吗",
        _context(),
        _route(SemanticDetailStage.ASSESSMENT),
    )[0]["content"]

    assert "safety_sensitive is a separate boolean" in system
    assert "MUST NOT appear in concerns" in system
    assert "use sensitivity or leave concerns empty" in system


def test_detail_prompt_allows_ambiguous_budget_candidate_to_stay_empty(
) -> None:
    system = build_detail_messages(
        "预算几百块上下，要适合油敏肌的防晒",
        _context(),
        _route(SemanticDetailStage.RECOMMENDATION),
    )[0]["content"]

    assert "Ambiguous colloquial budget wording" in system
    assert "leave number_candidates empty" in system
    assert "typed BUDGET confirmation" in system
    assert "code owns transitions" in system


def test_detail_prompt_requires_typed_source_bound_preference_candidates(
) -> None:
    system = build_detail_messages(
        "想要哑光一点的粉底",
        _context(),
        _route(SemanticDetailStage.RECOMMENDATION),
    )[0]["content"]

    assert "preference_candidates items use exactly" in system
    assert (
        "texture|fragrance_description|finish|brand|efficacy|"
        "suitable_skin|skin_concern|usage_context|ingredient_presence|"
        "ingredient_exclusion"
        in system
    )
    assert "strength is preference|safety|unknown" in system
    assert "raw_text and offsets must bind current-message text" in system


def test_detail_prompt_requires_source_bound_references() -> None:
    system = build_detail_messages(
        "第一张呢",
        _context(),
        _route(SemanticDetailStage.FOLLOWUP),
    )[0]["content"]

    assert (
        "references items use exactly kind,ordinal,raw_text,start,end"
        in system
    )
    assert (
        "raw_text and offsets must bind the exact current-message "
        "referring expression"
        in system
    )


def test_detail_prompt_splits_ordinary_preference_from_serious_safety(
) -> None:
    system = build_detail_messages(
        "我是敏感肌，想找温和一点的",
        _context(),
        _route(SemanticDetailStage.RECOMMENDATION),
    )[0]["content"]

    assert "bare sensitive-skin identity is an ordinary preference" in system
    assert "ordinary post-procedure preference is not safety-sensitive" in (
        system
    )
    assert "allergy, intolerance, pregnancy, active adverse reaction" in (
        system
    )
    assert "unknown severity is safety-sensitive" in system
    assert "code must confirm absolute ingredient inclusion" in system
