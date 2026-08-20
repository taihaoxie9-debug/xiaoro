"""Slice 1 展示层失败测试（RED）。

验证 build_response_plan 把 DecisionResult 转成 ResponsePlan：
- 商品卡严格按 DecisionResult.ordered_product_ids 顺序，不重排、不改分
- 透传肤质缺失标注（risk_findings）到对应卡片
- 商品事实由入参提供，展示层不读取 Canonical、不 import 具体 adapter
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.decision.contracts import (
    CandidateEvaluation,
    DecisionResult,
    RiskFinding,
    WinnerStatus,
)
from app.guide.presentation import ResponsePlan
from app.guide.presentation.contracts import ProductCardFacts
from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile


def build():
    from app.guide.presentation.response_planning import (
        MissingProductFactsError,
        build_response_plan,
    )

    return build_response_plan, MissingProductFactsError


def _decision() -> DecisionResult:
    return DecisionResult(
        ordered_product_ids=[57, 51, 26, 101],
        winner_status=WinnerStatus.INSUFFICIENT_FOR_WINNER,
        winner_product_id=None,
        evaluations=[
            CandidateEvaluation(
                product_id=57,
                disposition="eligible",
                price=Decimal("92.02"),
                skin_match="unknown",
                efficacy_match="not_applicable",
                matched_efficacies=[],
                reasons=["hard_constraints_passed"],
            ),
            CandidateEvaluation(
                product_id=51,
                disposition="eligible",
                price=Decimal("99.9"),
                skin_match="unknown",
                efficacy_match="not_applicable",
                matched_efficacies=[],
                reasons=["hard_constraints_passed"],
            ),
            CandidateEvaluation(
                product_id=26,
                disposition="eligible",
                price=Decimal("329.0"),
                skin_match="unknown",
                efficacy_match="not_applicable",
                matched_efficacies=[],
                reasons=["hard_constraints_passed"],
            ),
            CandidateEvaluation(
                product_id=101,
                disposition="eligible",
                price=Decimal("500.0"),
                skin_match="unknown",
                efficacy_match="not_applicable",
                matched_efficacies=[],
                reasons=["hard_constraints_passed"],
            ),
        ],
        comparison_dimensions=["skin_match", "price"],
        risk_findings=[
            RiskFinding(
                kind="skin_match_unknown",
                product_id=57,
                detail="肤质数据缺失",
            ),
            RiskFinding(
                kind="skin_match_unknown",
                product_id=51,
                detail="肤质数据缺失",
            ),
            RiskFinding(
                kind="skin_match_unknown",
                product_id=26,
                detail="肤质数据缺失",
            ),
            RiskFinding(
                kind="skin_match_unknown",
                product_id=101,
                detail="肤质数据缺失",
            ),
        ],
        evidence_refs=["category=防晒", "budget_max<=500"],
        tie_reason=None,
    )


def _facts() -> dict[int, ProductCardFacts]:
    return {
        57: ProductCardFacts(
            product_id=57,
            category_profile=CategoryProfile.SUNCARE,
            category_fields=(),
            name="A 防晒",
            brand="甲",
            category="防晒",
            price=Decimal("92.02"),
            fact_warnings=[],
        ),
        51: ProductCardFacts(
            product_id=51,
            category_profile=CategoryProfile.SUNCARE,
            category_fields=(),
            name="B 防晒",
            brand="乙",
            category="防晒",
            price=Decimal("99.9"),
            fact_warnings=[],
        ),
        26: ProductCardFacts(
            product_id=26,
            category_profile=CategoryProfile.SUNCARE,
            category_fields=(),
            name="C 防晒",
            brand="丙",
            category="防晒",
            price=Decimal("329.0"),
            fact_warnings=[],
        ),
        101: ProductCardFacts(
            product_id=101,
            category_profile=CategoryProfile.SUNCARE,
            category_fields=(),
            name="D 防晒",
            brand="丁",
            category="防晒",
            price=Decimal("500.0"),
            fact_warnings=[],
        ),
    }


def test_missing_product_fact_record_fails_closed() -> None:
    build_response_plan, error_type = build()

    with pytest.raises(error_type, match="product_id 57"):
        build_response_plan(_decision(), product_facts={})


def test_cards_follow_decision_order_exactly() -> None:
    build_response_plan, _ = build()
    plan = build_response_plan(_decision(), product_facts=_facts())

    assert isinstance(plan, ResponsePlan)
    cards = plan.structured_events
    assert [c.product_id for c in cards] == [57, 51, 26, 101]


def test_presentation_does_not_reorder_or_rescore() -> None:
    build_response_plan, _ = build()
    plan = build_response_plan(_decision(), product_facts=_facts())
    cards = plan.structured_events
    # 展示层不得引入自己的分数字段
    assert all(not hasattr(c, "score") for c in cards)
    # 顺序与决策完全一致（不因价格或名称二次排序）
    assert [c.product_id for c in cards] == _decision().ordered_product_ids


def test_skin_missing_flag_is_surfaced_on_cards() -> None:
    build_response_plan, _ = build()
    plan = build_response_plan(_decision(), product_facts=_facts())
    cards = plan.structured_events
    assert all(c.skin_match == "unknown" for c in cards)


def test_repair_evidence_and_category_are_surfaced_without_inference() -> None:
    decision = DecisionResult(
        ordered_product_ids=[91],
        winner_status=WinnerStatus.INSUFFICIENT_FOR_WINNER,
        winner_product_id=None,
        evaluations=[
            CandidateEvaluation(
                product_id=91,
                disposition="eligible",
                price=Decimal("88"),
                skin_match="unknown",
                efficacy_match="matched",
                matched_efficacies=["修护"],
                reasons=["hard_constraints_passed"],
            )
        ],
        comparison_dimensions=["skin_match", "efficacy_match", "price"],
        risk_findings=[],
        evidence_refs=["category=serum", "efficacy=repair"],
        tie_reason=None,
    )
    facts = {
        91: ProductCardFacts(
            product_id=91,
            category_profile=CategoryProfile.SKINCARE,
            category_fields=(),
            display_name="玉泽皮肤屏障修护精华乳",
            name="玉泽皮肤屏障修护精华乳50ml",
            brand="玉泽",
            category="精华",
            price=Decimal("88"),
            fact_warnings=[],
        )
    }

    card = build()[0](
        decision,
        product_facts=facts,
    ).structured_events[0]
    assert card.category == "精华"
    assert card.matched_efficacies == ["修护"]
    assert card.display_name == "玉泽皮肤屏障修护精华乳"
    assert card.specification is None


def test_canonical_direct_display_fields_reach_product_card() -> None:
    decision = DecisionResult(
        ordered_product_ids=[35],
        winner_status=WinnerStatus.INSUFFICIENT_FOR_WINNER,
        winner_product_id=None,
        evaluations=[
            CandidateEvaluation(
                product_id=35,
                disposition="eligible",
                price=Decimal("1050"),
                skin_match="unknown",
                efficacy_match="matched",
                matched_efficacies=["抗皱"],
                reasons=["hard_constraints_passed"],
            )
        ],
        comparison_dimensions=["skin_match", "efficacy_match", "price"],
        risk_findings=[],
        evidence_refs=["category=serum"],
        tie_reason=None,
    )
    facts = {
        35: ProductCardFacts(
            product_id=35,
            category_profile=CategoryProfile.SKINCARE,
            category_fields=(),
            efficacy=("抗皱", "淡化细纹", "紧致", "保湿"),
            efficacy_state="known",
            suitable_skin=("多种肤质适用",),
            suitable_skin_state="known",
            ingredients_present=("玻色因", "透明质酸"),
            ingredients_present_state="known",
            name="修丽可聚糖多重丰盈精华液",
            brand="修丽可",
            category="精华",
            price=Decimal("1050"),
            fact_warnings=[],
        )
    }

    card = build()[0](
        decision,
        product_facts=facts,
    ).structured_events[0]

    assert [
        (fact.field_key, fact.label, fact.value, fact.state)
        for fact in card.category_facts
    ] == [
        (
            "efficacy",
            "功效",
            ("抗皱", "淡化细纹", "紧致", "保湿"),
            "known",
        ),
        (
            "ingredients_present",
            "确认含有成分",
            ("玻色因", "透明质酸"),
            "known",
        ),
        (
            "suitable_skin",
            "适用肤质",
            ("多种肤质适用",),
            "known",
        ),
    ]


def test_canonical_efficacy_merges_with_existing_display_efficacy() -> None:
    decision = DecisionResult(
        ordered_product_ids=[35],
        winner_status=WinnerStatus.INSUFFICIENT_FOR_WINNER,
        winner_product_id=None,
        evaluations=[
            CandidateEvaluation(
                product_id=35,
                disposition="eligible",
                price=Decimal("1050"),
                skin_match="unknown",
                efficacy_match="matched",
                matched_efficacies=["抗皱"],
                reasons=["hard_constraints_passed"],
            )
        ],
        comparison_dimensions=["skin_match", "efficacy_match", "price"],
        risk_findings=[],
        evidence_refs=["category=serum"],
        tie_reason=None,
    )
    facts = {
        35: ProductCardFacts(
            product_id=35,
            category_profile=CategoryProfile.SKINCARE,
            category_fields=(
                _category_field(
                    field_key="efficacy",
                    value=("充盈", "改善凹陷观感"),
                    state="known",
                    capabilities=frozenset({"evidence", "display"}),
                    source_class=SourceClass.MERCHANT_PARAMETER,
                    category_profile=CategoryProfile.SKINCARE,
                ),
            ),
            efficacy=("抗皱", "淡化细纹", "紧致", "保湿"),
            efficacy_state="known",
            name="修丽可聚糖多重丰盈精华液",
            brand="修丽可",
            category="精华",
            price=Decimal("1050"),
            fact_warnings=[],
        )
    }

    card = build()[0](
        decision,
        product_facts=facts,
    ).structured_events[0]
    efficacy = next(
        fact for fact in card.category_facts
        if fact.field_key == "efficacy"
    )

    assert efficacy.value == (
        "充盈",
        "改善凹陷观感",
        "抗皱",
        "淡化细纹",
        "紧致",
        "保湿",
    )


def test_reviewed_specification_and_variant_scope_reach_product_card() -> None:
    build_response_plan, _ = build()
    facts = _facts()
    facts[57] = ProductCardFacts(
        product_id=57,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        variant_scope="60ml常规装",
        specification="60ml",
        name="A 防晒",
        brand="甲",
        category="防晒",
        price=Decimal("92.02"),
        fact_warnings=[],
    )

    card = build_response_plan(
        _decision(),
        product_facts=facts,
    ).structured_events[0]

    assert card.variant_scope == "60ml常规装"
    assert card.specification == "60ml"


def test_unusable_name_uses_readable_brand_category_fallback() -> None:
    build_response_plan, _ = build()
    facts = _facts()
    facts[57] = ProductCardFacts(
        product_id=57,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        name="无",
        brand="测试品牌",
        category="防晒",
        price=Decimal("92.02"),
        fact_warnings=["product_identity_unusable"],
    )
    card = build_response_plan(
        _decision(),
        product_facts=facts,
    ).structured_events[0]
    assert card.name == "测试品牌 防晒"
    assert card.fact_warnings == ["product_identity_unusable"]


def test_sections_and_context_are_authorized_only() -> None:
    build_response_plan, _ = build()
    plan = build_response_plan(_decision(), product_facts=_facts())

    assert "recommendation" in plan.sections
    ctx = plan.text_generation_context
    assert ctx.get("winner_status") == "INSUFFICIENT_FOR_WINNER"
    assert ctx.get("evidence_refs") == ["category=防晒", "budget_max<=500"]


def _category_field(
    *,
    field_key: str,
    value,
    state: str,
    capabilities: frozenset[str],
    source_class: SourceClass,
    category_profile: CategoryProfile = CategoryProfile.SUNCARE,
) -> AuthorizedCategoryFact:
    return AuthorizedCategoryFact(
        category_profile=category_profile,
        field_key=field_key,
        value=value,
        resolved_state=state,
        source_classes=(source_class,),
        source_refs=(
            ()
            if source_class is SourceClass.UNKNOWN
            else (f"urn:task9:presentation:{field_key}",)
        ),
        capabilities=capabilities,
    )


def test_display_projection_returns_only_known_display_safe_typed_facts() -> None:
    from app.guide.presentation.response_planning import (
        project_display_category_facts,
    )

    display = _category_field(
        field_key="reapplication",
        value="every two hours",
        state="known",
        capabilities=frozenset({"evidence", "display"}),
        source_class=SourceClass.OFFICIAL_DESCRIPTION,
    )
    compare_only = _category_field(
        field_key="spf_pa",
        value="SPF50+",
        state="known",
        capabilities=frozenset({"evidence", "compare"}),
        source_class=SourceClass.OFFICIAL_PACKAGING,
    )
    unknown = _category_field(
        field_key="texture",
        value=None,
        state="unknown",
        capabilities=frozenset({"evidence"}),
        source_class=SourceClass.UNKNOWN,
    )

    assert project_display_category_facts(
        (display, compare_only, unknown)
    ) == (display,)


def test_public_category_fact_dto_forbids_internal_authority_fields() -> None:
    from app.guide.presentation.contracts import DisplayCategoryFact

    with pytest.raises(ValidationError):
        DisplayCategoryFact(
            field_key="finish",
            label="妆效",
            value="natural",
            state="known",
            source_refs=["urn:private:source"],
        )
    with pytest.raises(ValidationError):
        DisplayCategoryFact(
            field_key="finish",
            label="妆效",
            value="natural",
            state="known",
            capabilities=["display"],
        )
    with pytest.raises(ValidationError):
        DisplayCategoryFact(
            field_key="finish",
            label="妆效",
            value="fabricated",
            state="unavailable",
        )


def test_category_fact_projection_changes_only_public_display_fields() -> None:
    build_response_plan, _ = build()
    baseline_facts = _facts()
    baseline = build_response_plan(
        _decision(),
        product_facts=baseline_facts,
    )
    poisoned_fields = (
        _category_field(
            field_key="reapplication",
            value="display only",
            state="known",
            capabilities=frozenset({"evidence", "display"}),
            source_class=SourceClass.OFFICIAL_DESCRIPTION,
        ),
        _category_field(
            field_key="safety",
            value=None,
            state="unknown",
            capabilities=frozenset({"evidence"}),
            source_class=SourceClass.UNKNOWN,
        ),
        _category_field(
            field_key="spf_pa",
            value="compare only",
            state="known",
            capabilities=frozenset({"evidence", "compare"}),
            source_class=SourceClass.OFFICIAL_PACKAGING,
        ),
        _category_field(
            field_key="texture",
            value=None,
            state="conflict",
            capabilities=frozenset({"evidence"}),
            source_class=SourceClass.STRUCTURED_OFFICIAL,
        ),
        _category_field(
            field_key="water_resistance",
            value="unsafe rank poison",
            state="known",
            capabilities=frozenset(
                {"evidence", "hard_filter", "soft_rank"}
            ),
            source_class=SourceClass.STRUCTURED_OFFICIAL,
        ),
    )
    poisoned_facts = dict(baseline_facts)
    poisoned_facts[57] = baseline_facts[57].model_copy(
        update={"category_fields": poisoned_fields},
        deep=True,
    )

    poisoned = build_response_plan(
        _decision(),
        product_facts=poisoned_facts,
    )

    assert [
        card.product_id for card in poisoned.structured_events
    ] == [57, 51, 26, 101]
    assert [
        card.product_id for card in baseline.structured_events
    ] == [57, 51, 26, 101]
    card = poisoned.structured_events[0]
    assert card.category_profile is CategoryProfile.SUNCARE
    assert {
        fact.field_key: fact.model_dump(mode="json")
        for fact in card.category_facts
    } == {
        "reapplication": {
            "field_key": "reapplication",
            "label": "补涂建议",
            "value": "display only",
            "state": "known",
        },
        "safety": {
            "field_key": "safety",
            "label": "安全信息",
            "value": None,
            "state": "unavailable",
        },
        "spf_pa": {
            "field_key": "spf_pa",
            "label": "防晒指数",
            "value": None,
            "state": "unavailable",
        },
        "texture": {
            "field_key": "texture",
            "label": "质地",
            "value": None,
            "state": "conflict",
        },
        "water_resistance": {
            "field_key": "water_resistance",
            "label": "防水性",
            "value": None,
            "state": "unavailable",
        },
    }
    serialized = card.model_dump(mode="json")
    assert "source_refs" not in str(serialized)
    assert "capabilities" not in str(serialized)
