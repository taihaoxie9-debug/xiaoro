"""Slice 1 意图层：把结构化理解编译成 TaskPlan。

原则：只做意图判定与约束编译，不读取商品详情、不召回、不打分、不判 winner。
关键信息（品类）缺失时转澄清模式，不猜。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, assert_never

from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    ConceptConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    FacetConstraint,
    FreeDescriptor,
    InclusionConstraint,
    RelativeRequirement,
    SkinConstraint,
    TaskConstraint,
    TaskPlan,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    EfficacyDraft,
    ExclusionDraft,
    InclusionDraft,
    PreferenceDraft,
    ProductMentionDraft,
    ReferenceDraft,
    SkinDraft,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.knowledge_relation_contracts import (
    KnowledgeRelationIntent,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_hard_category_exclusions,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_taxonomy import (
    category_profile_for_topic,
)


def plan_task(
    understanding: StructuredUnderstanding,
    *,
    responsibility: Responsibility | None = None,
    resolved_product_ids: Sequence[int] = (),
    product_resolution_issue: Literal[
        "missing_reference",
        "ambiguous_reference",
        "invalid_source_span",
    ] | None = None,
    message: str | None = None,
) -> TaskPlan:
    if not isinstance(understanding, StructuredUnderstanding):
        raise TypeError(
            "understanding must be a validated StructuredUnderstanding"
        )
    if (
        responsibility is not None
        and not isinstance(responsibility, Responsibility)
    ):
        raise TypeError(
            "responsibility must be Responsibility or None"
        )
    if (
        isinstance(resolved_product_ids, (str, bytes))
        or not isinstance(resolved_product_ids, Sequence)
        or any(
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id <= 0
            for product_id in resolved_product_ids
        )
    ):
        raise TypeError(
            "resolved_product_ids must contain positive integers"
        )
    if message is not None and not isinstance(message, str):
        raise TypeError("message must be str or None")
    if (
        message is not None
        and product_resolution_issue is None
        and understanding.product_mentions
        and len(resolved_product_ids)
        == len(understanding.product_mentions)
    ):
        understanding = _without_confirmed_name_constraints(
            understanding,
            message=message,
        )
    execution_goal = (
        UnderstandingGoal.COMPARISON
        if responsibility is Responsibility.COMPARISON
        else understanding.goal
    )
    constraints = compile_task_constraints(understanding)
    if (
        execution_goal
        in {
            UnderstandingGoal.RECOMMENDATION,
            UnderstandingGoal.IMAGE_SIMILARITY,
        }
        and (
            understanding.recommendation_mode is None
            or understanding.recommendation_mode_basis is None
            or (
                understanding.recommendation_mode == "fit"
                and understanding.recommendation_count is None
            )
        )
    ):
        raise ValueError(
            "recommendation understanding requires complete outcome"
        )
    recommendation_mode = (
        understanding.recommendation_mode
        if execution_goal
        in {
            UnderstandingGoal.RECOMMENDATION,
            UnderstandingGoal.IMAGE_SIMILARITY,
        }
        else None
    )
    recommendation_mode_basis = (
        understanding.recommendation_mode_basis
        if recommendation_mode is not None
        else None
    )
    recommendation_count = (
        understanding.recommendation_count
        if recommendation_mode is not None
        else None
    )
    if (
        recommendation_mode == "explore"
        and recommendation_count is None
    ):
        recommendation_count = 3
    clarification_recommendation_outcome = (
        {
            "recommendation_mode": recommendation_mode,
            "recommendation_mode_basis": recommendation_mode_basis,
            "recommendation_count": recommendation_count,
        }
        if execution_goal
        in {
            UnderstandingGoal.RECOMMENDATION,
            UnderstandingGoal.IMAGE_SIMILARITY,
        }
        else {}
    )
    references = list(understanding.references)
    product_mentions = list(understanding.product_mentions)
    product_ids = list(resolved_product_ids)
    if product_resolution_issue is not None:
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            references=references,
            product_mentions=product_mentions,
            required_evidence=[],
            clarification=(
                "这个名称可能对应多款商品，"
                "请补充品牌和完整商品名称。"
            ),
            clarification_code=ClarificationCode.REFERENCE,
            **clarification_recommendation_outcome,
        )
    if (
        understanding.uncertainties
        and not _can_execute_fail_closed_safety_question(
            understanding,
            product_ids=product_ids,
        )
    ):
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            references=references,
            product_mentions=product_mentions,
            required_evidence=[],
            clarification=understanding.uncertainties[0].detail,
            clarification_code=_understanding_clarification_code(
                understanding
            ),
            **clarification_recommendation_outcome,
        )
    if execution_goal is UnderstandingGoal.IMAGE_SIMILARITY:
        if len(product_ids) != 1:
            return TaskPlan(
                mode="clarify",
                referenced_image_ids=[],
                constraints=constraints,
                references=references,
                product_mentions=product_mentions,
                required_evidence=[],
                clarification=(
                    "请明确要以哪一张已确认图片作为相似款参考。"
                ),
                clarification_code=ClarificationCode.REFERENCE,
                **clarification_recommendation_outcome,
            )
        return TaskPlan(
            mode="recommend",
            recommendation_mode=recommendation_mode,
            recommendation_mode_basis=recommendation_mode_basis,
            recommendation_count=recommendation_count,
            referenced_image_ids=[],
            constraints=constraints,
            references=references,
            product_mentions=product_mentions,
            product_ids=[],
            similarity_anchor_product_id=product_ids[0],
            required_evidence=["canonical_product"],
            free_descriptors=_compile_free_descriptors(understanding),
            relative_requirements=_compile_relative_requirements(
                understanding
            ),
            question_meaning=understanding.question_meaning,
            knowledge_relation_hints=(
                understanding.knowledge_relation_hints
            ),
            safety_sensitive=understanding.safety_sensitive,
        )
    if execution_goal in {
        UnderstandingGoal.COMPARISON,
        UnderstandingGoal.SUITABILITY,
        UnderstandingGoal.KNOWLEDGE,
        UnderstandingGoal.FOLLOWUP,
    }:
        return _plan_semantic_task(
            execution_goal,
            constraints=constraints,
            references=references,
            product_mentions=product_mentions,
            product_ids=product_ids,
            relative_requirements=_compile_relative_requirements(
                understanding
            ),
            question_meaning=understanding.question_meaning,
            knowledge_relation_hints=(
                understanding.knowledge_relation_hints
            ),
            safety_sensitive=understanding.safety_sensitive,
            requested_comparison_dimensions=(
                _current_comparison_dimensions(
                    understanding,
                    message=message,
                )
                if execution_goal
                in {
                    UnderstandingGoal.COMPARISON,
                    UnderstandingGoal.SUITABILITY,
                    UnderstandingGoal.FOLLOWUP,
                }
                else ()
            ),
        )
    if execution_goal is not UnderstandingGoal.RECOMMENDATION:
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            references=references,
            product_mentions=product_mentions,
            required_evidence=[],
            clarification=(
                "当前文字流程还不能安全执行这个目标，"
                "请确认具体导购任务。"
            ),
            clarification_code=ClarificationCode.GOAL,
        )
    category = next(
        (
            item
            for item in constraints
            if isinstance(item, CategoryConstraint)
        ),
        None,
    )
    if category is None:
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            references=references,
            product_mentions=product_mentions,
            required_evidence=[],
            clarification=(
                "当前支持护肤、防晒、精华、底妆、彩妆、"
                "洁面/卸妆和香水；请明确品类。"
            ),
            clarification_code=ClarificationCode.TOPIC,
            **clarification_recommendation_outcome,
        )

    free_descriptors = _compile_free_descriptors(understanding)
    relative_requirements = _compile_relative_requirements(
        understanding
    )
    if (
        recommendation_mode == "fit"
        and not _has_usable_fit_need(
            constraints=constraints,
            free_descriptors=free_descriptors,
            relative_requirements=relative_requirements,
        )
        and not _inherits_fit_need(understanding)
    ):
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            references=references,
            product_mentions=product_mentions,
            required_evidence=[],
            clarification=(
                "请再补充一个最在意的肤质、功效、肤感或使用场景，"
                "我再帮你选最适合的一款。"
            ),
            clarification_code=ClarificationCode.GOAL,
            **clarification_recommendation_outcome,
        )

    return TaskPlan(
        mode="recommend",
        recommendation_mode=recommendation_mode,
        recommendation_mode_basis=recommendation_mode_basis,
        recommendation_count=recommendation_count,
        referenced_image_ids=[],
        constraints=constraints,
        references=references,
        product_mentions=product_mentions,
        product_ids=product_ids,
        required_evidence=["canonical_product"],
        free_descriptors=free_descriptors,
        relative_requirements=relative_requirements,
        question_meaning=understanding.question_meaning,
        safety_sensitive=understanding.safety_sensitive,
        clarification=None,
    )


def _current_comparison_dimensions(
    understanding: StructuredUnderstanding,
    *,
    message: str | None = None,
) -> tuple[str, ...]:
    context_filled_kinds = {
        parts[1]
        for trace in understanding.signal_trace
        if (
            trace.resolution == "context_fills"
            and len(parts := trace.field.split(".")) >= 3
            and parts[0] == "context"
        )
    }
    dimensions = list(
        _explicit_comparison_dimensions(
            _mask_product_mentions(
                message,
                product_mentions=understanding.product_mentions,
            )
        )
        if message is not None
        else ()
    )
    for draft in understanding.exact_constraints:
        if (
            isinstance(draft, BudgetDraft)
            and "budget" not in context_filled_kinds
        ):
            dimensions.append("reference_price")
        elif (
            isinstance(draft, EfficacyDraft)
            and "efficacy" not in context_filled_kinds
        ):
            dimensions.append("efficacy")
        elif (
            isinstance(draft, SkinDraft)
            and "skin" not in context_filled_kinds
        ):
            dimensions.append("suitable_skin")
        elif isinstance(draft, InclusionDraft):
            dimensions.append("ingredients_present")
    for constraint in _compile_preference_drafts(understanding):
        if isinstance(constraint, ConceptConstraint):
            _append_comparison_dimension(
                dimensions,
                constraint.concept_id,
            )
        elif isinstance(constraint, FacetConstraint):
            _append_comparison_dimension(
                dimensions,
                constraint.field_key,
            )
    for draft in understanding.relative_drafts:
        _append_comparison_dimension(
            dimensions,
            "reference_price"
            if draft.field_key == "price"
            else draft.concept_id or draft.field_key,
        )
    return tuple(dict.fromkeys(dimensions))


def _mask_product_mentions(
    message: str,
    *,
    product_mentions: Sequence[ProductMentionDraft],
) -> str:
    characters = list(message)
    for mention in product_mentions:
        span = mention.source_span
        if message[span.start:span.end] != mention.text:
            return message
        characters[span.start:span.end] = " " * (
            span.end - span.start
        )
    return "".join(characters)


def _append_comparison_dimension(
    dimensions: list[str],
    dimension_id: str,
) -> None:
    parent = dimension_id.split(".", 1)[0]
    if dimension_id != parent and parent in dimensions:
        dimensions[dimensions.index(parent)] = dimension_id
        return
    if dimension_id == parent and any(
        item.startswith(f"{parent}.") for item in dimensions
    ):
        return
    if dimension_id not in dimensions:
        dimensions.append(dimension_id)


def _explicit_comparison_dimensions(
    message: str,
) -> tuple[str, ...]:
    aliases = {
        "efficacy": ("功效", "作用"),
        "texture": ("质地", "肤感"),
        "reference_price": ("参考价", "价格", "价钱"),
        "suitable_skin": ("适合肤质", "肤质"),
        "ingredients_present": ("核心成分", "成分"),
        "spf_pa": ("防晒指数", "SPF", "PA"),
        "water_resistance": ("防水",),
        "finish": ("妆效",),
        "coverage": ("遮瑕",),
        "longevity": ("持妆",),
    }
    found: list[tuple[int, int, str]] = []
    for dimension_id, terms in aliases.items():
        positions = [
            (message.find(term), len(term))
            for term in terms
            if message.find(term) >= 0
        ]
        if not positions:
            continue
        start, length = min(positions)
        prefix = message[max(0, start - 6):start]
        suffix = message[start + length:start + length + 5]
        if (
            any(
                prefix.endswith(marker)
                for marker in (
                    "不考虑",
                    "不用考虑",
                    "忽略",
                    "不看",
                    "不比较",
                )
            )
            or suffix.startswith(("不限", "不作要求"))
        ):
            continue
        found.append((start, -length, dimension_id))
    return tuple(
        dimension_id
        for _, _, dimension_id in sorted(found)
    )


def _has_usable_fit_need(
    *,
    constraints: Sequence[TaskConstraint],
    free_descriptors: Sequence[FreeDescriptor],
    relative_requirements: Sequence[RelativeRequirement],
) -> bool:
    return (
        any(
            not isinstance(
                constraint,
                (BudgetConstraint, CategoryConstraint),
            )
            for constraint in constraints
        )
        or bool(free_descriptors)
        or bool(relative_requirements)
    )


def _inherits_fit_need(
    understanding: StructuredUnderstanding,
) -> bool:
    return any(
        trace.field == "recommendation_mode"
        and trace.resolution == "context_fills"
        and trace.exact_value == "fit"
        for trace in understanding.signal_trace
    )


def _can_execute_fail_closed_safety_question(
    understanding: StructuredUnderstanding,
    *,
    product_ids: list[int],
) -> bool:
    return (
        understanding.safety_sensitive
        and bool(product_ids)
        and understanding.goal
        in {
            UnderstandingGoal.COMPARISON,
            UnderstandingGoal.SUITABILITY,
            UnderstandingGoal.KNOWLEDGE,
            UnderstandingGoal.FOLLOWUP,
        }
        and all(
            issue.code == "unverified_safety_requirement"
            for issue in understanding.uncertainties
        )
    )


_NAME_SENSITIVE_DRAFTS = (
    SkinDraft,
    EfficacyDraft,
    ExclusionDraft,
    InclusionDraft,
)


def _without_confirmed_name_constraints(
    understanding: StructuredUnderstanding,
    *,
    message: str,
) -> StructuredUnderstanding:
    characters = list(message)
    for mention in understanding.product_mentions:
        span = mention.source_span
        if message[span.start:span.end] != mention.text:
            return understanding
        characters[span.start:span.end] = " " * (
            span.end - span.start
        )
    masked_message = "".join(characters)
    masked_constraints, _ = parse_exact_constraints(masked_message)
    retained = [
        draft
        for draft in understanding.exact_constraints
        if (
            not isinstance(draft, _NAME_SENSITIVE_DRAFTS)
            or _is_context_filled(understanding, draft)
        )
    ]
    retained.extend(
        draft
        for draft in masked_constraints
        if isinstance(draft, _NAME_SENSITIVE_DRAFTS)
    )
    deduplicated: list[object] = []
    seen: set[tuple[type, str]] = set()
    for draft in retained:
        key = (
            type(draft),
            draft.model_dump_json(
                exclude_none=False,
                exclude_unset=False,
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(draft)
    recovered_topic = _recover_name_masked_topic(
        understanding,
        masked_message=masked_message,
    )
    uncertainties = list(understanding.uncertainties)
    if not understanding.references:
        uncertainties = [
            issue
            for issue in uncertainties
            if issue.code != "ambiguous_reference"
        ]
    if recovered_topic is not None:
        if not any(
            isinstance(draft, CategoryDraft)
            and draft.value is recovered_topic
            for draft in deduplicated
        ):
            deduplicated.append(
                CategoryDraft(value=recovered_topic)
            )
        uncertainties = [
            issue
            for issue in uncertainties
            if issue.code != "ambiguous_category"
        ]
    return understanding.model_copy(
        update={
            "exact_constraints": deduplicated,
            "topic": recovered_topic or understanding.topic,
            "uncertainties": uncertainties,
        },
        deep=True,
    )


def _is_context_filled(
    understanding: StructuredUnderstanding,
    draft: object,
) -> bool:
    kind = getattr(draft, "kind", None)
    value = getattr(draft, "value", None)
    trace_value = getattr(value, "value", value)
    return any(
        trace.field.startswith(f"context.{kind}.")
        and trace.resolution == "context_fills"
        and trace.semantic_value == str(trace_value)
        for trace in understanding.signal_trace
    )


def _recover_name_masked_topic(
    understanding: StructuredUnderstanding,
    *,
    masked_message: str,
) -> TopicCode | None:
    if understanding.topic is not None:
        return None
    trace = next(
        (
            item
            for item in reversed(understanding.signal_trace)
            if (
                item.field == "topic"
                and item.semantic_value is not None
                and (
                    item.resolution == "clarify"
                    or (
                        item.resolution == "exact_wins"
                        and item.exact_value is not None
                        and item.exact_value.startswith("excluded:")
                    )
                )
            )
        ),
        None,
    )
    if trace is None:
        return None
    try:
        semantic_topic = TopicCode(trace.semantic_value)
    except ValueError:
        return None
    masked_constraints, masked_issues = parse_exact_constraints(
        masked_message
    )
    if any(
        issue.code == "ambiguous_category"
        for issue in masked_issues
    ):
        return None
    masked_topics = {
        draft.value
        for draft in masked_constraints
        if isinstance(draft, CategoryDraft)
    }
    if masked_topics and masked_topics != {semantic_topic}:
        return None
    if semantic_topic in parse_hard_category_exclusions(
        masked_message
    ):
        return None
    return semantic_topic


def _plan_semantic_task(
    goal: UnderstandingGoal,
    *,
    constraints: list[TaskConstraint],
    references: list[ReferenceDraft],
    product_mentions: list[ProductMentionDraft],
    product_ids: list[int],
    relative_requirements: list[RelativeRequirement],
    requested_comparison_dimensions: tuple[str, ...],
    question_meaning: str | None,
    knowledge_relation_hints: tuple[KnowledgeRelationIntent, ...],
    safety_sensitive: bool,
) -> TaskPlan:
    if (
        goal is UnderstandingGoal.KNOWLEDGE
        and len(references) == 1
        and references[0].kind == "current_item"
        and not product_mentions
    ):
        goal = UnderstandingGoal.FOLLOWUP
    if goal is UnderstandingGoal.COMPARISON:
        if product_ids and not 2 <= len(product_ids) <= 3:
            return _reference_clarification(
                constraints=constraints,
                references=references,
                product_mentions=product_mentions,
                question=(
                    "一次最多对比 3 款商品，请保留最想看的 2 到 3 款。"
                    if len(product_ids) > 3
                    else "商品对比需要 2 到 3 款，请再补充一款完整商品名。"
                ),
            )
        if not product_ids and not references:
            return _reference_clarification(
                constraints=constraints,
                references=references,
                product_mentions=product_mentions,
                question="请提供 2 到 3 个需要对比的完整商品名称。",
            )
        mode = "comparison"
    elif goal is UnderstandingGoal.SUITABILITY:
        if product_ids and len(product_ids) != 1:
            return _reference_clarification(
                constraints=constraints,
                references=references,
                product_mentions=product_mentions,
                question="适配判断需要 1 个唯一商品，请确认完整商品名。",
            )
        if (
            not product_ids
            and not references
            and product_mentions
        ):
            return _reference_clarification(
                constraints=constraints,
                references=references,
                product_mentions=product_mentions,
                question="请提供需要判断是否适合的完整商品名称。",
            )
        mode = "suitability"
    elif goal is UnderstandingGoal.FOLLOWUP:
        if not product_ids and not references:
            return _reference_clarification(
                constraints=constraints,
                references=references,
                product_mentions=product_mentions,
                question="请明确想继续看哪个商品，或者直接说商品名。",
            )
        mode = "followup"
    elif goal is UnderstandingGoal.KNOWLEDGE:
        mode = "knowledge"
    else:
        assert_never(goal)

    return TaskPlan(
        mode=mode,
        referenced_image_ids=[],
        constraints=constraints,
        references=references,
        product_mentions=product_mentions,
        product_ids=product_ids,
        required_evidence=["canonical_product"],
        relative_requirements=relative_requirements,
        requested_comparison_dimensions=(
            requested_comparison_dimensions
        ),
        question_meaning=question_meaning,
        knowledge_relation_hints=knowledge_relation_hints,
        safety_sensitive=safety_sensitive,
    )


def _reference_clarification(
    *,
    constraints: list[TaskConstraint],
    references: list[ReferenceDraft],
    product_mentions: list[ProductMentionDraft],
    question: str,
) -> TaskPlan:
    return TaskPlan(
        mode="clarify",
        referenced_image_ids=[],
        constraints=constraints,
        references=references,
        product_mentions=product_mentions,
        required_evidence=[],
        clarification=question,
        clarification_code=ClarificationCode.REFERENCE,
    )


def _understanding_clarification_code(
    understanding: StructuredUnderstanding,
) -> ClarificationCode:
    typed_hint = next(
        (
            trace.semantic_value
            for trace in understanding.signal_trace
            if (
                trace.field == "clarification_hint"
                and trace.resolution == "clarify"
                and trace.semantic_value is not None
            )
        ),
        None,
    )
    if typed_hint is not None:
        return ClarificationCode(typed_hint)
    if (
        understanding.topic is None
        and understanding.exact_constraints
        and any(
            issue.code in {"ambiguous_category", "missing_category"}
            for issue in understanding.uncertainties
        )
    ):
        return ClarificationCode.TOPIC
    if any(
        trace.field == "goal"
        and trace.resolution == "clarify"
        for trace in understanding.signal_trace
    ):
        return ClarificationCode.GOAL
    issue = understanding.uncertainties[0].code
    if issue in {"invalid_budget", "unsupported_budget_format"}:
        return ClarificationCode.BUDGET
    if issue in {
        "ambiguous_reference",
        "ambiguous_candidate_reference",
        "ambiguous_image_reference",
        "too_many_candidate_references",
        "too_many_image_references",
    }:
        return ClarificationCode.REFERENCE
    if issue in {"ambiguous_category", "missing_category"}:
        return ClarificationCode.TOPIC
    if issue in {
        "unsupported_attribute_exclusion",
        "unverified_safety_requirement",
    }:
        return ClarificationCode.CONCERN
    return ClarificationCode.GOAL


def compile_task_constraints(
    understanding: StructuredUnderstanding,
) -> list[TaskConstraint]:
    compiled: list[TaskConstraint] = []
    for draft in understanding.exact_constraints:
        if isinstance(draft, BudgetDraft):
            compiled.append(
                BudgetConstraint(
                    minimum=draft.minimum,
                    maximum=draft.maximum,
                )
            )
        elif isinstance(draft, CategoryDraft):
            compiled.append(CategoryConstraint(value=draft.value))
        elif isinstance(draft, SkinDraft):
            compiled.append(SkinConstraint(value=draft.value))
        elif isinstance(draft, ExclusionDraft):
            compiled.append(ExclusionConstraint(value=draft.value))
        elif isinstance(draft, InclusionDraft):
            compiled.append(InclusionConstraint(value=draft.value))
        elif isinstance(draft, EfficacyDraft):
            compiled.append(EfficacyConstraint(value=draft.value))
        elif isinstance(draft, ReferenceDraft):
            continue
        else:
            assert_never(draft)
    compiled.extend(_compile_preference_drafts(understanding))
    return compiled


def _compile_preference_drafts(
    understanding: StructuredUnderstanding,
) -> list[TaskConstraint]:
    if understanding.topic is None:
        return []
    profile = category_profile_for_topic(understanding.topic)
    applicable = {
        definition.key
        for definition in category_field_registry().for_profile(profile)
    }
    unique_facets: dict[tuple[str, str], PreferenceDraft] = {}
    unique_concepts: dict[
        tuple[str, str, str],
        PreferenceDraft,
    ] = {}
    for draft in understanding.preference_drafts:
        if draft.field_key not in applicable:
            continue
        if draft.preference_kind == "legacy_facet":
            unique_facets.setdefault(
                (draft.field_key, draft.value),
                draft,
            )
        elif (
            draft.preference_kind == "concept"
            and draft.concept_id is not None
        ):
            unique_concepts.setdefault(
                (
                    draft.field_key,
                    draft.concept_id,
                    draft.polarity,
                ),
                draft,
            )
    facets: list[TaskConstraint] = [
        FacetConstraint(field_key=field_key, value=draft.value)
        for (field_key, _), draft in unique_facets.items()
    ]
    facets.extend(
        ConceptConstraint(
            field_key=field_key,
            concept_id=concept_id,
            polarity=polarity,
        )
        for (
            field_key,
            concept_id,
            polarity,
        ), draft in unique_concepts.items()
    )
    return facets


def _compile_free_descriptors(
    understanding: StructuredUnderstanding,
) -> list[FreeDescriptor]:
    unique: dict[tuple[str, str, str], FreeDescriptor] = {}
    for draft in understanding.preference_drafts:
        if draft.preference_kind != "free_descriptor":
            continue
        key = (
            draft.field_key,
            draft.value.casefold(),
            draft.polarity,
        )
        unique.setdefault(
            key,
            FreeDescriptor(
                field_key=draft.field_key,
                value=draft.value,
                polarity=draft.polarity,
            ),
        )
    return list(unique.values())


def _compile_relative_requirements(
    understanding: StructuredUnderstanding,
) -> list[RelativeRequirement]:
    unique: dict[
        tuple[str, str | None, str, str, int | None],
        RelativeRequirement,
    ] = {}
    for draft in understanding.relative_drafts:
        key = (
            draft.field_key,
            draft.concept_id,
            draft.direction,
            draft.baseline.kind,
            draft.baseline.ordinal,
        )
        unique.setdefault(
            key,
            RelativeRequirement(
                field_key=draft.field_key,
                concept_id=draft.concept_id,
                direction=draft.direction,
                baseline=draft.baseline,
            ),
        )
    return list(unique.values())
