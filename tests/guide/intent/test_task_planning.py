"""Slice 1 意图层失败测试（RED）。

验证 plan_task 把结构化理解编译成 TaskPlan：
- 判定推荐模式
- 把 exact_constraints 编译成结构化 constraints
- 信息足够时不追问；关键信息缺失时提出澄清
不读取商品详情、不召回、不打分、不判 winner。
"""
from __future__ import annotations

from decimal import Decimal
import inspect

import pytest
from pydantic import ValidationError

import app.guide.intent.contracts as intent_contracts
import app.guide.understanding.contracts as understanding_contracts
from app.guide.intent import TaskPlan
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    SkinConstraint,
)
from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    EfficacyDraft,
    EfficacyTarget,
    ExclusionDraft,
    PreferenceDraft,
    ProductMentionDraft,
    ReferenceDraft,
    SignalTrace,
    SkinTarget,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
    UnderstandingIssue,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    SemanticLaneDisposition,
)
from tests.guide.legacy_text_understanding import understand_text


_TASK29_CATEGORY_QUANTIFIERS = (
    "任意",
    "任一",
    "任何",
    "一切",
    "所有",
    "全部",
    "每个",
    "每一款",
    "每一种",
    "每一类",
    "各个",
    "各款",
    "各类",
    "这类",
    "这种",
    "这一类",
    "那种",
    "那一类",
)
_TASK30_NESTED_NEGATIVE_ATTRIBUTES = (
    "不含酒精的",
    "无酒精的",
    "无香精的",
)
_TASK32_OUTER_EXCLUSION_CUES = (
    "避开",
    "不要",
    "不想要",
    "排除",
    "拒绝",
    "不要有",
)
_TASK32_INNER_ABSENCE_CUES = ("不含", "无")
_TASK32_INGREDIENTS = ("酒精", "香精")
_TASK32_CATEGORIES = (("香水", TopicCode.FRAGRANCE),)


def plan():
    from app.guide.intent.task_planning import plan_task

    return plan_task


def test_full_query_becomes_recommend_plan_without_clarification() -> None:
    understanding = understand_text("500 内适合油敏肌的防晒")
    assert understanding.recommendation_mode == "explore"
    assert (
        understanding.recommendation_mode_basis
        == "broad_exploration"
    )
    assert understanding.recommendation_count == 3

    task = plan()(understanding)

    assert isinstance(task, TaskPlan)
    assert task.mode == "recommend"
    assert task.clarification is None
    assert "canonical_product" in task.required_evidence


def test_route_responsibility_controls_mode_without_mutating_understanding(
) -> None:
    planner = plan()
    assert "responsibility" in inspect.signature(planner).parameters
    understanding = understand_text(
        "500 内适合油敏肌的防晒"
    )
    original = understanding.model_dump(mode="python")

    task = planner(
        understanding,
        responsibility=Responsibility.COMPARISON,
        resolved_product_ids=(38, 91),
    )

    assert task.mode == "comparison"
    assert task.product_ids == [38, 91]
    assert understanding.model_dump(mode="python") == original


def test_explore_recommendation_preserves_typed_result_count() -> None:
    understanding = understand_text(
        "500 内适合油敏肌的防晒"
    ).model_copy(
        update={
            "recommendation_mode": "explore",
            "recommendation_count": 2,
            "recommendation_mode_basis": "count_requested",
        }
    )

    task = plan()(understanding)

    assert task.mode == "recommend"
    assert task.recommendation_mode == "explore"
    assert task.recommendation_count == 2
    assert task.recommendation_mode_basis == "count_requested"


def test_fit_recommendation_requires_one_result_and_usable_need() -> None:
    understanding = understand_text(
        "500 内适合油敏肌的防晒"
    ).model_copy(
        update={
            "recommendation_mode": "fit",
            "recommendation_count": 1,
            "recommendation_mode_basis": "personal_suitability",
        }
    )

    task = plan()(understanding)

    assert task.mode == "recommend"
    assert task.recommendation_mode == "fit"
    assert task.recommendation_count == 1
    assert task.recommendation_mode_basis == "personal_suitability"


def test_fit_without_usable_need_returns_typed_clarification() -> None:
    understanding = understand_text(
        "给我推荐 500 内的防晒"
    ).model_copy(
        update={
            "recommendation_mode": "fit",
            "recommendation_count": 1,
            "recommendation_mode_basis": "single_best_request",
        }
    )

    task = plan()(understanding)

    assert task.mode == "clarify"
    assert task.clarification_code is ClarificationCode.GOAL
    assert task.recommendation_mode == "fit"
    assert task.recommendation_mode_basis == "single_best_request"
    assert task.recommendation_count == 1


def test_plan_task_rejects_missing_recommendation_basis() -> None:
    understanding = understand_text(
        "500 内适合油敏肌的防晒"
    ).model_copy(
        update={
            "recommendation_mode": "fit",
            "recommendation_mode_basis": None,
            "recommendation_count": 1,
        }
    )

    with pytest.raises(
        ValueError,
        match="recommendation understanding requires complete outcome",
    ):
        plan()(understanding)


@pytest.mark.parametrize(
    ("recommendation_mode", "recommendation_mode_basis"),
    (
        ("explore", "single_best_request"),
        ("fit", "broad_exploration"),
    ),
)
def test_task_plan_rejects_cross_parent_recommendation_basis(
    recommendation_mode: str,
    recommendation_mode_basis: str,
) -> None:
    task = plan()(understand_text("500 内适合油敏肌的防晒"))

    with pytest.raises(
        ValidationError,
        match="recommendation mode basis must be parent-scoped",
    ):
        TaskPlan.model_validate(
            {
                **task.model_dump(mode="python"),
                "recommendation_mode": recommendation_mode,
                "recommendation_mode_basis": (
                    recommendation_mode_basis
                ),
                "recommendation_count": (
                    1 if recommendation_mode == "fit" else 2
                ),
            },
            strict=True,
        )


def test_structured_understanding_rejects_cross_parent_basis() -> None:
    understanding = understand_text("500 内适合油敏肌的防晒")

    with pytest.raises(
        ValidationError,
        match="recommendation mode basis must be parent-scoped",
    ):
        StructuredUnderstanding.model_validate(
            {
                **understanding.model_dump(mode="python"),
                "recommendation_mode": "fit",
                "recommendation_mode_basis": "broad_exploration",
                "recommendation_count": 1,
            },
            strict=True,
        )


def test_comparison_dimensions_come_from_current_turn_atoms() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=TopicCode.SERUM,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SERUM),
            BudgetDraft(maximum=Decimal("500")),
        ],
        preference_drafts=[
            PreferenceDraft(
                field_key="texture",
                value="清爽",
                preference_kind="concept",
                concept_id="texture.refreshing",
            )
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
    )

    task = plan()(understanding, resolved_product_ids=(38, 91))

    assert task.requested_comparison_dimensions == (
        "reference_price",
        "texture.refreshing",
    )


def test_current_skin_comparison_adds_suitable_skin_dimension() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=TopicCode.SERUM,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SERUM),
            understanding_contracts.SkinDraft(
                value=SkinTarget.OILY_SENSITIVE
            ),
        ],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
    )

    task = plan()(understanding, resolved_product_ids=(129, 33))

    assert task.requested_comparison_dimensions == ("suitable_skin",)


def test_inherited_budget_does_not_add_comparison_price_dimension() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=TopicCode.SERUM,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SERUM),
            BudgetDraft(maximum=Decimal("500")),
        ],
        preference_drafts=[
            PreferenceDraft(
                field_key="texture",
                value="清爽",
                preference_kind="concept",
                concept_id="texture.refreshing",
            )
        ],
        semantic_proposals=[],
        signal_trace=[
            SignalTrace(
                field="context.budget.session",
                exact_value=None,
                semantic_value="maximum=500",
                resolution="context_fills",
            )
        ],
        references=[],
        product_mentions=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
    )

    task = plan()(understanding, resolved_product_ids=(38, 91))

    assert task.requested_comparison_dimensions == (
        "texture.refreshing",
    )


def test_product_question_plan_carries_unrestricted_meaning() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.KNOWLEDGE,
        topic=TopicCode.SKINCARE,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[
            ProductMentionDraft(
                text="薇诺娜面膜",
                source_span=SourceSpan(start=0, end=5),
            )
        ],
        image_references=[],
        uncertainties=[],
        confidence=0.95,
        question_meaning="询问面膜是否服帖、是否容易滑落",
        safety_sensitive=False,
    )

    task = plan()(understanding, resolved_product_ids=(78,))

    assert task.mode == "knowledge"
    assert task.product_ids == [78]
    assert task.question_meaning == "询问面膜是否服帖、是否容易滑落"
    assert not task.safety_sensitive


def test_general_knowledge_plan_carries_relation_hints() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.KNOWLEDGE,
        topic=TopicCode.SERUM,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        knowledge_relation_hints=(
            "difference",
            "compatibility",
        ),
        question_meaning="比较两种活性成分并询问能否叠加",
        safety_sensitive=False,
    )

    task = plan()(
        understanding,
        responsibility=Responsibility.GENERAL_KNOWLEDGE,
        message="烟酰胺和A醇有什么区别，能一起用吗？",
    )

    assert task.mode == "knowledge"
    assert task.knowledge_relation_hints == (
        "difference",
        "compatibility",
    )


def test_resolved_safety_question_executes_fail_closed_evidence_path() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.KNOWLEDGE,
        topic=TopicCode.SKINCARE,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SKINCARE),
        ],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[
            ProductMentionDraft(
                text="薇诺娜面膜",
                source_span=SourceSpan(start=0, end=5),
            )
        ],
        image_references=[],
        uncertainties=[
            UnderstandingIssue(
                code="unverified_safety_requirement",
                detail="安全问题必须按证据 fail-closed。",
            )
        ],
        confidence=0.99,
        question_meaning="询问特殊美容项目后使用是否安全",
        safety_sensitive=True,
    )

    task = plan()(understanding, resolved_product_ids=(78,))

    assert task.mode == "knowledge"
    assert task.safety_sensitive
    assert task.clarification is None


def test_unresolved_safety_question_still_clarifies_reference() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.KNOWLEDGE,
        topic=TopicCode.SKINCARE,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SKINCARE),
        ],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[],
        image_references=[],
        uncertainties=[
            UnderstandingIssue(
                code="unverified_safety_requirement",
                detail="安全问题必须按证据 fail-closed。",
            )
        ],
        confidence=0.99,
        question_meaning="询问特殊美容项目后使用是否安全",
        safety_sensitive=True,
    )

    task = plan()(understanding)

    assert task.mode == "clarify"


def test_confirmed_product_name_efficacy_is_not_a_user_constraint() -> None:
    first_name = "可复美面膜"
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    message = f"对比{first_name}和{name}"
    first_start = message.index(first_name)
    start = message.index(name)
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=TopicCode.SKINCARE,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SKINCARE),
            EfficacyDraft(value=EfficacyTarget.HYDRATION),
        ],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[
            ProductMentionDraft(
                text=first_name,
                source_span=SourceSpan(
                    start=first_start,
                    end=first_start + len(first_name),
                ),
            ),
            ProductMentionDraft(
                text=name,
                source_span=SourceSpan(
                    start=start,
                    end=start + len(name),
                ),
            )
        ],
        image_references=[],
        uncertainties=[],
        confidence=0.99,
    )

    task = plan()(
        understanding,
        resolved_product_ids=(74, 78),
        message=message,
    )

    assert not any(
        isinstance(item, EfficacyConstraint)
        for item in task.constraints
    )


def test_explicit_efficacy_outside_product_name_remains_a_constraint() -> None:
    first_name = "可复美面膜"
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    message = f"对比{first_name}和{name}，我明确想要补水"
    first_start = message.index(first_name)
    start = message.index(name)
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=TopicCode.SKINCARE,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SKINCARE),
            EfficacyDraft(value=EfficacyTarget.HYDRATION),
        ],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[
            ProductMentionDraft(
                text=first_name,
                source_span=SourceSpan(
                    start=first_start,
                    end=first_start + len(first_name),
                ),
            ),
            ProductMentionDraft(
                text=name,
                source_span=SourceSpan(
                    start=start,
                    end=start + len(name),
                ),
            )
        ],
        image_references=[],
        uncertainties=[],
        confidence=0.99,
    )

    task = plan()(
        understanding,
        resolved_product_ids=(74, 78),
        message=message,
    )

    assert any(
        isinstance(item, EfficacyConstraint)
        and item.value is EfficacyTarget.HYDRATION
        for item in task.constraints
    )


def test_confirmed_product_name_can_clear_false_category_exclusion() -> None:
    name = "茵芙莎光透无瑕修饰遮瑕膏e"
    message = f"{name}青色黑眼圈该用哪一格？"
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.KNOWLEDGE,
        topic=None,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[
            SignalTrace(
                field="topic",
                exact_value="excluded:base_makeup",
                semantic_value="base_makeup",
                resolution="exact_wins",
            )
        ],
        references=[],
        product_mentions=[
            ProductMentionDraft(
                text=name,
                source_span=SourceSpan(
                    start=0,
                    end=len(name),
                ),
            )
        ],
        image_references=[],
        uncertainties=[
            UnderstandingIssue(
                code="ambiguous_category",
                detail=(
                    "语义品类与本轮明确排除的品类冲突，"
                    "请确认目标品类。"
                ),
            )
        ],
        confidence=0.0,
        question_meaning="询问青色黑眼圈的遮瑕用法",
        safety_sensitive=False,
    )

    task = plan()(
        understanding,
        resolved_product_ids=(111,),
        message=message,
    )

    assert task.mode == "knowledge"
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.BASE_MAKEUP


def test_category_exclusion_outside_product_name_still_clarifies() -> None:
    name = "已确认商品"
    message = f"{name}，不要遮瑕膏"
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.KNOWLEDGE,
        topic=None,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[
            SignalTrace(
                field="topic",
                exact_value="excluded:base_makeup",
                semantic_value="base_makeup",
                resolution="exact_wins",
            )
        ],
        references=[],
        product_mentions=[
            ProductMentionDraft(
                text=name,
                source_span=SourceSpan(
                    start=0,
                    end=len(name),
                ),
            )
        ],
        image_references=[],
        uncertainties=[
            UnderstandingIssue(
                code="ambiguous_category",
                detail=(
                    "语义品类与本轮明确排除的品类冲突，"
                    "请确认目标品类。"
                ),
            )
        ],
        confidence=0.0,
        question_meaning="询问商品",
        safety_sensitive=False,
    )

    task = plan()(
        understanding,
        resolved_product_ids=(111,),
        message=message,
    )

    assert task.mode == "clarify"


def test_confirmed_product_name_can_clear_embedded_category_conflict() -> None:
    name = "SK-II护肤洁面霜"
    message = f"{name}为什么有酵母味？"
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.KNOWLEDGE,
        topic=None,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        semantic_proposals=[],
        signal_trace=[
            SignalTrace(
                field="topic",
                exact_value=None,
                semantic_value="cleanser",
                resolution="clarify",
            )
        ],
        references=[],
        product_mentions=[
            ProductMentionDraft(
                text=name,
                source_span=SourceSpan(
                    start=0,
                    end=len(name),
                ),
            )
        ],
        image_references=[],
        uncertainties=[
            UnderstandingIssue(
                code="ambiguous_category",
                detail="检测到多个不同品类。",
            )
        ],
        confidence=0.0,
        question_meaning="询问洁面产品特殊气味原因",
        safety_sensitive=False,
    )

    task = plan()(
        understanding,
        resolved_product_ids=(97,),
        message=message,
    )

    assert task.mode == "knowledge"
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.CLEANSER


def test_constraints_are_compiled_to_structured_form() -> None:
    understanding = understand_text("500 内适合油敏肌的防晒")
    task = plan()(understanding)

    assert any(isinstance(c, BudgetConstraint) for c in task.constraints)
    assert any(isinstance(c, CategoryConstraint) for c in task.constraints)
    assert any(isinstance(c, SkinConstraint) for c in task.constraints)

    budget = next(
        c for c in task.constraints if isinstance(c, BudgetConstraint)
    )
    assert budget.maximum == 500
    assert budget.minimum is None


def test_repair_serum_compiles_typed_efficacy_constraint() -> None:
    task = plan()(understand_text("500 元内敏感肌修护精华"))

    assert task.mode == "recommend"
    efficacy = next(
        item
        for item in task.constraints
        if isinstance(item, EfficacyConstraint)
    )
    assert efficacy.value is EfficacyTarget.REPAIR


def test_hydrating_serum_does_not_require_repair_confirmation() -> None:
    task = plan()(understand_text("想找保湿精华"))

    assert task.mode == "recommend"
    assert task.clarification is None
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.SERUM


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        ("保湿精华", "hydration"),
        ("舒缓精华", "soothing"),
        ("修护精华", "repair"),
        ("抗老精华", "anti_aging"),
        ("提亮精华", "brightening"),
        ("控油精华", "oil_control"),
        ("祛痘精华", "acne_care"),
    ),
)
def test_common_serum_efficacy_compiles_to_closed_constraint(
    message: str,
    expected: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "recommend"
    efficacy = next(
        item
        for item in task.constraints
        if isinstance(item, EfficacyConstraint)
    )
    assert efficacy.value.value == expected


@pytest.mark.parametrize("message", ["精华", "美白精华", "抗老精华"])
def test_serum_does_not_require_repair_efficacy(
    message: str,
) -> None:
    task = plan()(understand_text(message))
    assert task.mode == "recommend"
    assert task.clarification is None
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.SERUM


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("推荐防晒", TopicCode.SUNSCREEN),
        ("推荐精华水", TopicCode.SKINCARE),
        ("推荐粉底液", TopicCode.BASE_MAKEUP),
        ("推荐口红", TopicCode.COLOR_MAKEUP),
        ("推荐卸妆油", TopicCode.CLEANSER),
        ("推荐香水", TopicCode.FRAGRANCE),
    ],
)
def test_non_serum_topics_can_recommend_without_repair_efficacy(
    message: str,
    topic: TopicCode,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "recommend"
    assert task.clarification is None
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is topic
    assert not any(
        isinstance(item, EfficacyConstraint)
        for item in task.constraints
    )


def test_semantic_followup_keeps_typed_followup_mode() -> None:
    reference = ReferenceDraft(
        kind="candidate_ordinal",
        ordinal=2,
        source_span=None,
    )
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.FOLLOWUP,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
            reference,
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[reference],
        image_references=[],
        uncertainties=[],
        confidence=0.99,
    )

    task = plan()(understanding)

    assert task.mode == "followup"
    assert task.references == [reference]
    assert task.required_evidence == ["canonical_product"]


def _semantic_task_input(
    goal: UnderstandingGoal,
    *,
    product_mentions: list[ProductMentionDraft] | None = None,
    references: list[ReferenceDraft] | None = None,
) -> StructuredUnderstanding:
    return StructuredUnderstanding(
        goal=goal,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=references or [],
        product_mentions=product_mentions or [],
        image_references=[],
        uncertainties=[],
        confidence=0.95,
    )


@pytest.mark.parametrize(
    ("goal", "product_ids", "expected_mode"),
    (
        (UnderstandingGoal.COMPARISON, (51, 53), "comparison"),
        (UnderstandingGoal.SUITABILITY, (53,), "suitability"),
    ),
)
def test_direct_product_goals_compile_to_typed_task_mode(
    goal: UnderstandingGoal,
    product_ids: tuple[int, ...],
    expected_mode: str,
) -> None:
    mentions = [
        ProductMentionDraft(
            text=f"product-{product_id}",
            source_span=SourceSpan(
                start=index * 10,
                end=index * 10 + 9,
            ),
        )
        for index, product_id in enumerate(product_ids)
    ]

    task = plan()(
        _semantic_task_input(
            goal,
            product_mentions=mentions,
        ),
        resolved_product_ids=product_ids,
    )

    assert task.mode == expected_mode
    assert task.product_ids == list(product_ids)
    assert task.product_mentions == mentions
    assert task.required_evidence == ["canonical_product"]
    assert task.clarification is None


def test_comparison_with_four_products_clarifies_maximum_three() -> None:
    product_ids = (51, 53, 55, 57)
    mentions = [
        ProductMentionDraft(
            text=f"product-{product_id}",
            source_span=SourceSpan(
                start=index * 10,
                end=index * 10 + 9,
            ),
        )
        for index, product_id in enumerate(product_ids)
    ]

    task = plan()(
        _semantic_task_input(
            UnderstandingGoal.COMPARISON,
            product_mentions=mentions,
        ),
        resolved_product_ids=product_ids,
    )

    assert task.mode == "clarify"
    assert task.product_ids == []
    assert task.clarification == (
        "一次最多对比 3 款商品，请保留最想看的 2 到 3 款。"
    )


def test_resolved_product_mentions_clear_false_reference_uncertainty() -> None:
    message = "帮我对比兰蔻小黑瓶和小棕瓶"
    names = ("兰蔻小黑瓶", "小棕瓶")
    mentions = [
        ProductMentionDraft(
            text=name,
            source_span=SourceSpan(
                start=message.index(name),
                end=message.index(name) + len(name),
            ),
        )
        for name in names
    ]
    understanding = _semantic_task_input(
        UnderstandingGoal.COMPARISON,
        product_mentions=mentions,
    ).model_copy(
        update={
            "topic": TopicCode.SERUM,
            "exact_constraints": [
                CategoryDraft(value=TopicCode.SERUM),
            ],
            "uncertainties": [
                UnderstandingIssue(
                    code="ambiguous_reference",
                    detail="当前指代没有唯一绑定，请明确具体对象。",
                )
            ],
        },
        deep=True,
    )

    task = plan()(
        understanding,
        resolved_product_ids=(129, 33),
        product_resolution_issue=None,
        message=message,
    )

    assert task.mode == "comparison"
    assert task.product_ids == [129, 33]
    assert task.clarification is None


def test_resolved_name_does_not_clear_unresolved_reference_uncertainty() -> None:
    message = "帮我对比这款和小棕瓶"
    name = "小棕瓶"
    understanding = _semantic_task_input(
        UnderstandingGoal.COMPARISON,
        product_mentions=[
            ProductMentionDraft(
                text=name,
                source_span=SourceSpan(
                    start=message.index(name),
                    end=message.index(name) + len(name),
                ),
            )
        ],
        references=[
            ReferenceDraft(
                kind="current_item",
                source_span=SourceSpan(start=5, end=7),
            )
        ],
    ).model_copy(
        update={
            "topic": TopicCode.SERUM,
            "exact_constraints": [
                CategoryDraft(value=TopicCode.SERUM),
            ],
            "uncertainties": [
                UnderstandingIssue(
                    code="ambiguous_reference",
                    detail="当前指代没有唯一绑定，请明确具体对象。",
                )
            ],
        },
        deep=True,
    )

    task = plan()(
        understanding,
        resolved_product_ids=(33,),
        product_resolution_issue=None,
        message=message,
    )

    assert task.mode == "clarify"
    assert task.clarification_code is ClarificationCode.REFERENCE


@pytest.mark.parametrize(
    ("goal", "expected_mode"),
    (
        (UnderstandingGoal.KNOWLEDGE, "followup"),
        (UnderstandingGoal.FOLLOWUP, "followup"),
    ),
)
def test_current_item_question_compiles_to_followup_mode(
    goal: UnderstandingGoal,
    expected_mode: str,
) -> None:
    reference = ReferenceDraft(
        kind="current_item",
        source_span=None,
    )
    task = plan()(
        _semantic_task_input(
            goal,
            references=[reference],
        )
    )

    assert task.mode == expected_mode
    assert task.references == [reference]
    assert task.clarification is None


@pytest.mark.parametrize(
    "goal",
    (
        UnderstandingGoal.COMPARISON,
        UnderstandingGoal.FOLLOWUP,
    ),
)
def test_missing_product_for_reference_goal_clarifies_reference(
    goal: UnderstandingGoal,
) -> None:
    task = plan()(_semantic_task_input(goal))

    assert task.mode == "clarify"
    assert task.clarification_code is ClarificationCode.REFERENCE
    assert "商品" in task.clarification
    assert task.required_evidence == []


def test_category_suitability_does_not_require_product_reference() -> None:
    task = plan()(
        _semantic_task_input(UnderstandingGoal.SUITABILITY)
    )

    assert task.mode == "suitability"
    assert task.product_ids == []
    assert task.clarification is None


def test_same_clarification_copy_preserves_typed_semantic_hint() -> None:
    question = "同一显示文案不能决定澄清类型。"

    def planning_input(code: ClarificationCode) -> StructuredUnderstanding:
        return StructuredUnderstanding(
            goal=UnderstandingGoal.RECOMMENDATION,
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=3,
            topic=None,
            observations=[],
            exact_constraints=[],
            semantic_proposals=[],
            signal_trace=[
                SignalTrace(
                    field="clarification_hint",
                    exact_value=None,
                    semantic_value=code.value,
                    resolution="clarify",
                )
            ],
            references=[],
            image_references=[],
            uncertainties=[
                UnderstandingIssue(
                    code="missing_category",
                    detail=question,
                )
            ],
            confidence=0.5,
        )

    goal = plan()(planning_input(ClarificationCode.GOAL))
    budget = plan()(planning_input(ClarificationCode.BUDGET))

    assert goal.clarification == budget.clarification == question
    assert goal.clarification_code is ClarificationCode.GOAL
    assert budget.clarification_code is ClarificationCode.BUDGET


def test_negation_becomes_exclude_constraint() -> None:
    understanding = understand_text("不要含酒精的防晒")
    task = plan()(understanding)

    excludes = [
        c for c in task.constraints if isinstance(c, ExclusionConstraint)
    ]
    assert any(c.value == "酒精" for c in excludes)


def test_missing_category_asks_for_clarification() -> None:
    understanding = understand_text("500 以内")
    task = plan()(understanding)

    assert task.mode == "clarify"
    assert task.clarification == (
        "当前支持护肤、防晒、精华、底妆、彩妆、"
        "洁面/卸妆和香水；请明确品类。"
    )
    assert not task.constraints or all(
        not isinstance(c, CategoryConstraint) for c in task.constraints
    )


def test_multiple_positive_category_topics_clarify_without_a_winner() -> None:
    task = plan()(understand_text("粉底液还是口红"))

    assert task.mode == "clarify"
    assert task.clarification == (
        "检测到多个不同品类，请只保留一个明确的推荐品类。"
    )
    assert not any(
        isinstance(item, CategoryConstraint)
        for item in task.constraints
    )


@pytest.mark.parametrize(
    "modifier",
    ["平价", "高端", "适合学生的"],
)
@pytest.mark.parametrize(
    "connector",
    ["以及", "并且", "并", "且"],
)
def test_modified_coordinated_category_negation_clarifies(
    connector: str,
    modifier: str,
) -> None:
    task = plan()(
        understand_text(f"不考虑防晒{connector}{modifier}香水")
    )

    assert task.mode == "clarify"
    assert not any(
        isinstance(item, CategoryConstraint)
        for item in task.constraints
    )


@pytest.mark.parametrize(
    "message",
    [
        "不考虑防晒并想买平价香水",
        "不考虑防晒并推荐平价香水",
        "不考虑防晒且想买平价香水",
        "不考虑防晒并且推荐平价香水",
    ],
)
def test_explicit_coordinated_positive_predicate_recommends(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "recommend"
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.FRAGRANCE


@pytest.mark.parametrize(
    "connector",
    ["并且", "并", "且", "以及"],
)
@pytest.mark.parametrize(
    "predicate",
    ["想买", "想要", "要买", "推荐", "改买"],
)
def test_task26_direct_positive_predicate_recommends(
    connector: str,
    predicate: str,
) -> None:
    task = plan()(
        understand_text(
            f"不考虑防晒{connector}{predicate}平价香水"
        )
    )

    assert task.mode == "recommend"
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.FRAGRANCE


@pytest.mark.parametrize(
    "message",
    [
        "不考虑防晒并不想买香水",
        "不考虑防晒并非要买香水",
        "不考虑防晒并想要避开的香水",
        "不考虑防晒并推荐避雷香水",
        "不考虑防晒并想买但不买香水",
        "不考虑防晒并改买香水但不要香水",
    ],
)
def test_task26_final_negative_category_state_clarifies(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "clarify"
    assert not any(
        isinstance(item, CategoryConstraint)
        for item in task.constraints
    )


@pytest.mark.parametrize(
    "message",
    [
        "不甜的香水",
        "不贵的香水",
        "不含酒精的香水",
    ],
)
def test_task26_attribute_negation_recommends_category(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "recommend"
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.FRAGRANCE


@pytest.mark.parametrize(
    "message",
    [
        "避开甜腻的香水",
        "不要太甜的香水",
        "不想要太甜的香水",
    ],
)
def test_task27_attribute_exclusion_clarifies_with_category(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "clarify"
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.FRAGRANCE
    assert not any(
        isinstance(item, ExclusionConstraint)
        for item in task.constraints
    )


@pytest.mark.parametrize(
    "cue",
    ["不要", "避开", "排除", "拒绝"],
)
@pytest.mark.parametrize(
    "category_target",
    [
        "所有的",
        "所有",
        "全部的",
        "全部",
        "这类的",
        "这类",
        "这种的",
        "这种",
    ],
)
def test_task28_quantified_category_target_clarifies(
    cue: str,
    category_target: str,
) -> None:
    task = plan()(
        understand_text(f"{cue}{category_target}香水")
    )

    assert task.mode == "clarify"
    assert not any(
        isinstance(item, CategoryConstraint)
        for item in task.constraints
    )


@pytest.mark.parametrize(
    "message",
    [
        "避开甜腻的香水",
        "不要太甜的香水",
        "不想要太甜的香水",
    ],
)
def test_task28_pure_attribute_target_clarifies_with_category(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "clarify"
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.FRAGRANCE
    assert not any(
        isinstance(item, ExclusionConstraint)
        for item in task.constraints
    )


@pytest.mark.parametrize("cue", ["不要", "避开", "排除", "拒绝"])
@pytest.mark.parametrize("quantifier", _TASK29_CATEGORY_QUANTIFIERS)
@pytest.mark.parametrize("particle", ["", "的"])
def test_task29_closed_quantifier_set_clarifies_without_category(
    cue: str,
    quantifier: str,
    particle: str,
) -> None:
    task = plan()(
        understand_text(f"{cue}{quantifier}{particle}香水")
    )

    assert task.mode == "clarify"
    assert not any(
        isinstance(item, CategoryConstraint)
        for item in task.constraints
    )


@pytest.mark.parametrize(
    "message",
    [
        "避开甜腻的香水",
        "不要太甜的香水",
        "不想要太甜的香水",
    ],
)
def test_task29_unsupported_sensory_exclusion_clarifies_with_category(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    categories = [
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    ]
    exclusions = [
        item
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    assert task.mode == "clarify"
    assert [item.value for item in categories] == [TopicCode.FRAGRANCE]
    assert exclusions == []
    assert task.required_evidence == []
    assert task.clarification is not None
    assert "属性描述" in task.clarification


@pytest.mark.parametrize("cue", ["不要", "避开", "排除", "不想要"])
@pytest.mark.parametrize(
    "attribute",
    _TASK30_NESTED_NEGATIVE_ATTRIBUTES,
)
def test_task30_consumed_unsupported_attribute_does_not_compile_exclusion(
    cue: str,
    attribute: str,
) -> None:
    task = plan()(understand_text(f"{cue}{attribute}香水"))

    categories = [
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    ]
    exclusions = [
        item
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    assert task.mode == "clarify"
    assert [item.value for item in categories] == [TopicCode.FRAGRANCE]
    assert exclusions == []
    assert task.required_evidence == []
    assert task.clarification is not None
    assert "属性描述" in task.clarification


@pytest.mark.parametrize("cue", ["不要", "避开", "排除", "拒绝"])
@pytest.mark.parametrize("quantifier", _TASK29_CATEGORY_QUANTIFIERS)
@pytest.mark.parametrize("particle", ["", "的"])
def test_task30_consumed_category_target_does_not_compile_exclusion(
    cue: str,
    quantifier: str,
    particle: str,
) -> None:
    task = plan()(
        understand_text(f"{cue}{quantifier}{particle}香水")
    )

    assert task.mode == "clarify"
    assert not any(
        isinstance(item, CategoryConstraint)
        for item in task.constraints
    )
    assert not any(
        isinstance(item, ExclusionConstraint)
        for item in task.constraints
    )


@pytest.mark.parametrize(
    "message",
    [
        "不要含酒精的香水",
        "不含酒精的香水",
    ],
)
def test_task30_ordinary_ingredient_exclusion_still_recommends(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    categories = [
        item.value
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    ]
    exclusions = [
        item.value
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    assert task.mode == "recommend"
    assert categories == [TopicCode.FRAGRANCE]
    assert exclusions == ["酒精"]
    assert task.required_evidence == ["canonical_product"]
    assert task.clarification is None


@pytest.mark.parametrize(
    "cue",
    ["不要有", "不要含", "不含", "不能有", "无"],
)
@pytest.mark.parametrize("ingredient", ["酒精", "香精"])
def test_task31_ingredient_exclusion_compiles_bare_value(
    cue: str,
    ingredient: str,
) -> None:
    task = plan()(
        understand_text(f"{cue}{ingredient}的香水")
    )

    categories = [
        item.value
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    ]
    exclusions = [
        item.value
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    assert task.mode == "recommend"
    assert categories == [TopicCode.FRAGRANCE]
    assert exclusions == [ingredient]
    assert all(not value.startswith("有") for value in exclusions)
    assert task.required_evidence == ["canonical_product"]
    assert task.clarification is None


@pytest.mark.parametrize("outer_cue", _TASK32_OUTER_EXCLUSION_CUES)
@pytest.mark.parametrize("inner_cue", _TASK32_INNER_ABSENCE_CUES)
@pytest.mark.parametrize("ingredient", _TASK32_INGREDIENTS)
@pytest.mark.parametrize(("category", "topic"), _TASK32_CATEGORIES)
def test_task32_nested_absence_clarifies_without_exclusion_constraint(
    outer_cue: str,
    inner_cue: str,
    ingredient: str,
    category: str,
    topic: TopicCode,
) -> None:
    task = plan()(
        understand_text(f"{outer_cue}{inner_cue}{ingredient}的{category}")
    )

    categories = [
        item.value
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    ]
    exclusions = [
        item.value
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    assert task.mode == "clarify"
    assert categories == [topic]
    assert exclusions == []
    assert task.required_evidence == []
    assert task.clarification is not None
    assert "属性描述" in task.clarification


@pytest.mark.parametrize(
    "message",
    [
        "想要避开的香水",
        "推荐避雷香水",
        "想买但不买香水",
        "推荐防晒但不推荐防晒",
        "不考虑防晒并改买香水但最后不推荐香水",
    ],
)
def test_task27_effective_category_negation_clarifies(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "clarify"
    assert not any(
        isinstance(item, CategoryConstraint)
        for item in task.constraints
    )


@pytest.mark.parametrize(
    "message",
    [
        "不考虑防晒但后来还是想买高端香水",
        "不考虑防晒以及后来还是想买高端香水",
        "不考虑防晒以及后来还是要买高端香水",
        "不考虑防晒以及后来还是想要高端香水",
        "不考虑防晒以及我后来还是想买高端香水",
        "不考虑防晒以及后来改买高端香水",
    ],
)
def test_modified_positive_category_transition_recommends(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "recommend"
    category = next(
        item
        for item in task.constraints
        if isinstance(item, CategoryConstraint)
    )
    assert category.value is TopicCode.FRAGRANCE


def test_task_plan_rejects_unknown_constraint_kind() -> None:
    with pytest.raises(ValidationError):
        TaskPlan.model_validate({
            "mode": "recommend",
            "referenced_image_ids": [],
            "constraints": [
                {"kind": "typo", "operator": "anything", "value": []}
            ],
            "required_evidence": ["canonical_product"],
            "clarification": None,
        })


def test_invalid_budget_forces_clarification() -> None:
    task = plan()(understand_text("0 元以内的防晒"))
    assert task.mode == "clarify"
    assert "预算" in task.clarification


@pytest.mark.parametrize(
    "message",
    (
        "孕妇能用的防晒",
        "500 元内油敏肌防晒安全吗",
        "这款精华会不会过敏",
        "皮肤破损还能用这款面霜吗",
    ),
)
def test_unverifiable_safety_requirement_forces_concern_clarification(
    message: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "clarify"
    assert task.clarification_code is ClarificationCode.CONCERN
    assert "无法用强证据核实" in task.clarification
    assert task.required_evidence == []


@pytest.mark.parametrize(
    ("message", "meaning"),
    (
        ("百来块的防晒", "100 到 199"),
        ("几百上下的防晒", "200 到 900"),
        ("几百块上下的防晒", "200 到 900"),
        ("250 左右的防晒", "225 到 275"),
        ("三张以内的防晒", "300 元以内"),
    ),
)
def test_fuzzy_budget_clarification_is_typed_and_meaningful(
    message: str,
    meaning: str,
) -> None:
    task = plan()(understand_text(message))

    assert task.mode == "clarify"
    assert task.clarification_code is ClarificationCode.BUDGET
    assert meaning in task.clarification


def test_applicable_preference_draft_compiles_to_facet_constraint() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        recommendation_mode="explore",
        recommendation_mode_basis="broad_exploration",
        recommendation_count=3,
        topic=TopicCode.BASE_MAKEUP,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.BASE_MAKEUP),
        ],
        preference_drafts=[
            PreferenceDraft(field_key="finish", value="哑光"),
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        image_references=[],
        uncertainties=[],
        confidence=0.95,
    )

    task = plan()(understanding)

    facets = [
        item
        for item in task.constraints
        if item.kind == "facet"
    ]
    assert [
        (item.field_key, item.value)
        for item in facets
    ] == [("finish", "哑光")]


def test_multiple_values_for_one_field_compile_as_independent_slots() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        recommendation_mode="explore",
        recommendation_mode_basis="broad_exploration",
        recommendation_count=3,
        topic=TopicCode.SKINCARE,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SKINCARE),
        ],
        preference_drafts=[
            PreferenceDraft(field_key="efficacy", value="保湿"),
            PreferenceDraft(field_key="efficacy", value="舒缓"),
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        image_references=[],
        uncertainties=[],
        confidence=0.95,
    )

    task = plan()(understanding)

    assert [
        (item.field_key, item.value)
        for item in task.constraints
        if item.kind == "facet"
    ] == [
        ("efficacy", "保湿"),
        ("efficacy", "舒缓"),
    ]


def test_absolute_ingredient_presence_compiles_to_hard_inclusion() -> None:
    assert hasattr(understanding_contracts, "InclusionDraft")
    assert hasattr(intent_contracts, "InclusionConstraint")

    task = plan()(understand_text("必须含烟酰胺的精华"))

    inclusion = next(
        item
        for item in task.constraints
        if isinstance(item, intent_contracts.InclusionConstraint)
    )
    assert inclusion.field_key == "ingredients_present"
    assert inclusion.value == "烟酰胺"


def test_non_applicable_or_unknown_preference_draft_is_dropped() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        recommendation_mode="explore",
        recommendation_mode_basis="broad_exploration",
        recommendation_count=3,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        preference_drafts=[
            PreferenceDraft(field_key="shade", value="冷白"),
            PreferenceDraft(
                field_key="cold_unknown_field",
                value="冷门偏好",
            ),
        ],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        image_references=[],
        uncertainties=[],
        confidence=0.95,
    )

    task = plan()(understanding)

    assert task.mode == "recommend"
    assert not any(item.kind == "facet" for item in task.constraints)
    assert task.clarification is None


def test_hard_constraint_revision_confirmation_blocks_retrieval() -> None:
    task = plan()(
        StructuredUnderstanding(
            goal=UnderstandingGoal.RECOMMENDATION,
            recommendation_mode="explore",
            recommendation_mode_basis="broad_exploration",
            recommendation_count=3,
            topic=TopicCode.FRAGRANCE,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.FRAGRANCE),
                ExclusionDraft(value="酒精"),
            ],
            semantic_proposals=[],
            signal_trace=[],
            references=[],
            image_references=[],
            uncertainties=[
                UnderstandingIssue(
                    code="confirm_hard_constraint_revision",
                    detail="请确认是否修改已有硬约束。",
                )
            ],
            confidence=0.0,
        )
    )

    assert task.mode == "clarify"
    assert task.required_evidence == []
    assert "硬约束" in task.clarification


def test_unproved_semantic_skip_blocks_all_downstream_work() -> None:
    understanding = merge_intent_signals(
        message="对比防晒",
        exact_constraints=[CategoryDraft(value=TopicCode.SUNSCREEN)],
        exact_issues=[],
        exact_revision_confirmations=[],
        semantic=None,
        semantic_disposition=(
            SemanticLaneDisposition.SKIPPED_BY_CONTRACT
        ),
    )

    task = plan()(understanding)

    assert task.mode == "clarify"
    assert task.required_evidence == []
    assert task.referenced_image_ids == []
    assert task.clarification is not None


def test_all_compiled_constraints_are_typed() -> None:
    task = plan()(understand_text("300 到 500 元、不要酒精的防晒"))
    assert {item.kind for item in task.constraints} == {
        "budget",
        "category",
        "exclude",
    }


def test_task_plan_does_not_fabricate_missing_recommendation_basis() -> None:
    with pytest.raises(
        ValidationError,
        match="recommend plan requires recommendation mode basis",
    ):
        TaskPlan(
            mode="recommend",
            recommendation_mode="fit",
            recommendation_count=1,
            referenced_image_ids=[],
            constraints=[
                CategoryConstraint(value=TopicCode.SERUM),
                SkinConstraint(value=SkinTarget.SENSITIVE),
            ],
            required_evidence=["canonical_product"],
        )


def test_revalidated_task_copy_rejects_missing_recommendation_basis() -> None:
    assert hasattr(intent_contracts, "revalidate_task_plan")
    source = TaskPlan(
        mode="followup",
        referenced_image_ids=[],
        constraints=[CategoryConstraint(value=TopicCode.SERUM)],
        required_evidence=["canonical_product"],
    )

    with pytest.raises(
        ValidationError,
        match="recommend plan requires recommendation mode basis",
    ):
        intent_contracts.revalidate_task_plan(
            source,
            update={
                "mode": "recommend",
                "recommendation_mode": "fit",
                "recommendation_count": 1,
            },
        )
