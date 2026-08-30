from __future__ import annotations

from collections.abc import Mapping

from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
    compile_concept_preferences,
)
from app.guide.intent.reference_admission import (
    ReferenceAdmissionError,
    admit_reference,
)
from app.guide.intent.semantic_admission import admit_turn_meaning
from app.guide.understanding.budget_candidate_validation import (
    validate_budget_candidates,
)
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    ConstraintChangeDraft,
    ExclusionDraft,
    EfficacyDraft,
    EfficacyTarget,
    ExactRevisionOperation,
    ExactRevisionTarget,
    PreferenceDraft,
    ProductMentionDraft,
    ReferenceDraft,
    RelativeDraft,
    SignalTrace,
    SkinDraft,
    SkinTarget,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
    UnderstandingIssue,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_revision_confirmations,
)
from app.guide.understanding.semantic_contracts import (
    ActiveConstraintKind,
    ClarificationCode,
    SemanticContext,
    SemanticNumberCandidate,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticRouteBindingAuthority,
)
from app.guide.understanding.source_grounding import (
    SourceGroundingError,
    ground_unique_text,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.category_taxonomy import (
    category_profile_for_topic,
)
from app.guide.retrieval.ingredient_entities import (
    normalize_ingredient_entity,
)


_REFERENCE_REQUIRED_GOALS = {
    UnderstandingGoal.COMPARISON,
    UnderstandingGoal.SUITABILITY,
    UnderstandingGoal.FOLLOWUP,
}


def revalidate_understanding(
    understanding: StructuredUnderstanding,
    *,
    goal: UnderstandingGoal,
    updates: Mapping[str, object] | None = None,
) -> StructuredUnderstanding:
    if not isinstance(understanding, StructuredUnderstanding):
        raise TypeError(
            "understanding must be StructuredUnderstanding"
        )
    if not isinstance(goal, UnderstandingGoal):
        raise TypeError("goal must be UnderstandingGoal")
    payload = understanding.model_dump(mode="python")
    payload["goal"] = goal
    if updates is not None:
        payload.update(updates)
    if goal not in {
        UnderstandingGoal.RECOMMENDATION,
        UnderstandingGoal.IMAGE_SIMILARITY,
    }:
        payload["recommendation_mode"] = None
        payload["recommendation_mode_basis"] = None
        payload["recommendation_count"] = None
    return StructuredUnderstanding.model_validate(payload, strict=True)


def compile_turn_meaning(
    *,
    message: str,
    meaning: TurnMeaning,
    context: SemanticContext,
    concept_catalog: ConceptPreferenceCatalog | None = None,
) -> StructuredUnderstanding:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be nonempty")
    if not isinstance(meaning, TurnMeaning):
        raise TypeError("meaning must be TurnMeaning")
    if not isinstance(context, SemanticContext):
        raise TypeError("context must be SemanticContext")
    text = message.strip()
    exact_constraints, exact_issues = parse_exact_constraints(text)
    revision_proofs = (
        *(
            item
            for item in exact_constraints
            if isinstance(item, BudgetDraft)
        ),
        *meaning.budget_candidates,
        *meaning.constraint_changes,
    )
    issues = list(exact_issues)
    traces: list[SignalTrace] = []

    exact_topics = tuple({
        item.value
        for item in exact_constraints
        if isinstance(item, CategoryDraft)
    })
    semantic_topic = (
        TopicCode(meaning.topic_hint)
        if meaning.topic_hint is not None
        else None
    )
    semantic_goal = UnderstandingGoal(meaning.operation_hint)
    single_image_comparison = (
        semantic_goal is UnderstandingGoal.COMPARISON
        and context.image_count == 1
        and not meaning.reference_mentions
        and not meaning.product_mentions
    )
    if single_image_comparison:
        semantic_goal = UnderstandingGoal.IMAGE_SIMILARITY
    relation_topic_is_not_task_topic = (
        semantic_goal
        in {
            UnderstandingGoal.SUITABILITY,
            UnderstandingGoal.KNOWLEDGE,
            UnderstandingGoal.FOLLOWUP,
        }
        and meaning.question_meaning is not None
        and not meaning.preference_candidates
        and semantic_topic is not None
        and semantic_topic not in exact_topics
        and semantic_topic is context.active_topic
        and any(
            item.object_family_hint in {"product", "image"}
            for item in meaning.reference_mentions
        )
    )
    if relation_topic_is_not_task_topic:
        exact_value = (
            exact_topics[0].value
            if len(exact_topics) == 1
            else None
        )
        exact_constraints = [
            item
            for item in exact_constraints
            if not isinstance(item, CategoryDraft)
        ]
        exact_constraints.append(CategoryDraft(value=semantic_topic))
        topic = semantic_topic
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=exact_value,
                semantic_value=semantic_topic.value,
                resolution="semantic_fills",
            )
        )
    elif len(exact_topics) == 1:
        topic = exact_topics[0]
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=topic.value,
                semantic_value=(
                    semantic_topic.value
                    if semantic_topic is not None
                    else None
                ),
                resolution=(
                    "agree"
                    if semantic_topic is topic
                    else "exact_wins"
                ),
            )
        )
    elif semantic_topic is not None:
        topic = semantic_topic
        exact_constraints.append(CategoryDraft(value=topic))
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=None,
                semantic_value=topic.value,
                resolution="semantic_fills",
            )
        )
    elif (
        context.active_topic is not None
        and meaning.continuity_hint != "new_task"
    ):
        topic = context.active_topic
        exact_constraints.append(CategoryDraft(value=topic))
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=None,
                semantic_value=topic.value,
                resolution="context_fills",
            )
        )
    elif _infers_broad_skincare_topic(
        message=text,
        meaning=meaning,
        goal=semantic_goal,
        concept_catalog=concept_catalog,
    ):
        topic = TopicCode.SKINCARE
        exact_constraints.append(CategoryDraft(value=topic))
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=None,
                semantic_value=topic.value,
                resolution="semantic_fills",
            )
        )
    else:
        topic = None

    admission = admit_turn_meaning(
        message=text,
        meaning=meaning,
        topic=topic,
        active_topic=context.active_topic,
        concept_catalog=concept_catalog,
    )
    if meaning.recommendation_mode_basis is not None:
        basis_outcomes = admission.for_kind(
            "recommendation_mode_basis"
        )
        if (
            len(basis_outcomes) != 1
            or basis_outcomes[0].disposition != "admitted"
            or basis_outcomes[0].normalized_value
            != meaning.recommendation_mode_basis.basis
        ):
            raise ValueError(
                "recommendation mode basis must be source-grounded"
            )
    if meaning.recommendation_count is not None:
        count_outcomes = admission.for_kind("recommendation_count")
        if (
            len(count_outcomes) != 1
            or count_outcomes[0].disposition != "admitted"
            or count_outcomes[0].normalized_value
            != str(meaning.recommendation_count)
        ):
            raise ValueError(
                "recommendation count must be source-grounded"
            )

    if (
        semantic_goal
        in {
            UnderstandingGoal.SUITABILITY,
            UnderstandingGoal.KNOWLEDGE,
            UnderstandingGoal.FOLLOWUP,
        }
        and meaning.question_meaning is not None
        and (
            semantic_goal is UnderstandingGoal.SUITABILITY
            or not meaning.preference_candidates
        )
    ):
        factual_question_issues = {
            "unsupported_attribute_exclusion",
        }
        if meaning.product_mentions:
            factual_question_issues.add("ambiguous_category")
        issues = [
            issue
            for issue in issues
            if issue.code not in factual_question_issues
        ]
    followup_starts_new_selection = (
        semantic_goal is UnderstandingGoal.FOLLOWUP
        and (
            (
                bool(meaning.preference_candidates)
                and not any(
                    item.object_family_hint in {"product", "image"}
                    for item in meaning.reference_mentions
                )
            )
            or (
                topic is not None
                and context.active_topic is not None
                and topic is not context.active_topic
            )
        )
    )
    goal = (
        UnderstandingGoal.RECOMMENDATION
        if (
            semantic_goal is UnderstandingGoal.FOLLOWUP
            and (
                (
                    revision_proofs
                    and context.active_recommendation_mode is not None
                )
                or followup_starts_new_selection
            )
        )
        else semantic_goal
    )
    traces.append(
        SignalTrace(
            field="goal",
            exact_value=None,
            semantic_value=semantic_goal.value,
            resolution=(
                "clarify"
                if goal is UnderstandingGoal.CLARIFICATION
                else (
                    "exact_wins"
                    if goal is not semantic_goal
                    else "semantic_fills"
                )
            ),
        )
    )

    authority = SemanticRouteBindingAuthority.from_context(context)
    explicit_product_spans: set[tuple[int, int]] = set()
    for mention in meaning.product_mentions:
        try:
            grounded = ground_unique_text(text, mention.raw_text)
        except SourceGroundingError:
            continue
        explicit_product_spans.add((grounded.start, grounded.end))
    exact_constraints = [
        item
        for item in exact_constraints
        if (
            not isinstance(item, ReferenceDraft)
            or (
                _exact_reference_is_admitted(item, authority)
                and (
                    item.source_span is None
                    or (
                        item.source_span.start,
                        item.source_span.end,
                    )
                    not in explicit_product_spans
                )
            )
        )
    ]
    references = [
        item
        for item in exact_constraints
        if isinstance(item, ReferenceDraft)
    ]
    has_specific_product_reference = any(
        item.kind
        in {
            "current_item",
            "candidate_ordinal",
            "image_ordinal",
        }
        for item in references
    )
    factual_product_question = (
        semantic_goal
        in {
            UnderstandingGoal.SUITABILITY,
            UnderstandingGoal.KNOWLEDGE,
            UnderstandingGoal.FOLLOWUP,
        }
        and meaning.question_meaning is not None
        and not meaning.preference_candidates
        and (
            has_specific_product_reference
            or bool(meaning.product_mentions)
            or any(
                item.object_family_hint in {"product", "image"}
                for item in meaning.reference_mentions
            )
        )
    )
    for mention in meaning.reference_mentions:
        if mention.object_family_hint == "product":
            try:
                grounded = ground_unique_text(text, mention.raw_text)
            except SourceGroundingError:
                grounded = None
            if (
                grounded is not None
                and (grounded.start, grounded.end)
                in explicit_product_spans
            ):
                traces.append(
                    SignalTrace(
                        field="reference.explicit_product",
                        exact_value=None,
                        semantic_value=mention.raw_text,
                        resolution="semantic_fills",
                    )
                )
                if meaning.continuity_hint != "return_to_focus":
                    continue
                try:
                    admitted = admit_reference(
                        message=text,
                        mention=mention,
                        authority=authority,
                    )
                except ReferenceAdmissionError:
                    continue
                if not any(
                    _same_reference_binding(item, admitted)
                    for item in references
                ):
                    references.append(admitted)
                traces.append(
                    SignalTrace(
                        field=f"reference.{admitted.kind}",
                        exact_value=None,
                        semantic_value=mention.raw_text,
                        resolution="context_fills",
                    )
                )
                continue
        if (
            mention.object_family_hint == "image"
            and mention.plurality_hint == "batch"
            and mention.ordinal_hint is None
        ):
            try:
                grounded = ground_unique_text(text, mention.raw_text)
            except SourceGroundingError:
                if goal in _REFERENCE_REQUIRED_GOALS:
                    _append_issue(
                        issues,
                        code="ambiguous_reference",
                        detail=(
                            "当前图片说法没有唯一对应到本轮原话，"
                            "请重新说明。"
                        ),
                    )
                continue
            if not authority.image_ordinals:
                if goal in _REFERENCE_REQUIRED_GOALS:
                    _append_issue(
                        issues,
                        code="ambiguous_reference",
                        detail="当前没有可绑定的图片，请重新上传。",
                    )
                continue
            if (
                mention.batch_size_hint is not None
                and mention.batch_size_hint
                != len(authority.image_ordinals)
            ):
                if goal in _REFERENCE_REQUIRED_GOALS:
                    _append_issue(
                        issues,
                        code="ambiguous_reference",
                        detail=(
                            "当前请求的图片数量与可见图片不一致，"
                            "请明确图片序号。"
                        ),
                    )
                continue
            span = SourceSpan(
                start=grounded.start,
                end=grounded.end,
            )
            for ordinal in authority.image_ordinals:
                admitted = ReferenceDraft(
                    kind="image_ordinal",
                    ordinal=ordinal,
                    source_span=span,
                )
                if not any(
                    _same_reference_binding(item, admitted)
                    for item in references
                ):
                    references.append(admitted)
                traces.append(
                    SignalTrace(
                        field="reference.image_ordinal",
                        exact_value=None,
                        semantic_value=mention.raw_text,
                        resolution="semantic_fills",
                    )
                )
            continue
        if (
            mention.object_family_hint == "topic"
            and meaning.continuity_hint == "return_to_focus"
            and meaning.product_mentions
            and semantic_topic is not None
            and authority.current_topic is semantic_topic
        ):
            traces.append(
                SignalTrace(
                    field="reference.current_topic",
                    exact_value=authority.current_topic.value,
                    semantic_value=mention.raw_text,
                    resolution="context_fills",
                )
            )
            continue
        if (
            factual_product_question
            and mention.object_family_hint in {"topic", "constraint"}
        ):
            traces.append(
                SignalTrace(
                    field="relation_topic",
                    exact_value=None,
                    semantic_value=mention.raw_text,
                    resolution="semantic_fills",
                )
            )
            continue
        try:
            admitted = admit_reference(
                message=text,
                mention=mention,
                authority=authority,
            )
        except ReferenceAdmissionError:
            admitted = _image_anchored_product_coreference(
                message=text,
                mention=mention,
                references=references,
            )
            if admitted is not None:
                traces.append(
                    SignalTrace(
                        field="reference.image_ordinal",
                        exact_value=None,
                        semantic_value=mention.raw_text,
                        resolution="context_fills",
                    )
                )
                continue
            if goal in _REFERENCE_REQUIRED_GOALS:
                _append_issue(
                    issues,
                    code="ambiguous_reference",
                    detail=(
                        "当前说法还没有唯一对应到商品、图片或之前的条件，"
                        "请明确具体对象。"
                    ),
                )
            traces.append(
                SignalTrace(
                    field="reference",
                    exact_value=None,
                    semantic_value=mention.raw_text,
                    resolution="clarify",
                )
            )
            continue
        if not any(
            _same_reference_binding(item, admitted)
            for item in references
        ):
            references.append(admitted)
        traces.append(
            SignalTrace(
                field=f"reference.{admitted.kind}",
                exact_value=None,
                semantic_value=mention.raw_text,
                resolution="semantic_fills",
            )
        )

    references = _collapse_equivalent_context_references(
        references,
        authority=authority,
    )
    references.sort(
        key=lambda item: (
            item.source_span is None,
            (
                item.source_span.start
                if item.source_span is not None
                else len(text)
            ),
            (
                item.source_span.end
                if item.source_span is not None
                else len(text)
            ),
        )
    )
    exact_constraints = [
        item
        for item in exact_constraints
        if (
            not isinstance(item, ReferenceDraft)
            or any(
                item == reference
                for reference in references
            )
        )
    ]

    if (
        not references
        and not meaning.product_mentions
        and goal
        in {
            UnderstandingGoal.SUITABILITY,
            UnderstandingGoal.FOLLOWUP,
        }
        and meaning.continuity_hint == "continue"
        and meaning.question_meaning is not None
        and authority.current_item_available
        and not (
            authority.active_dialogue == "consultation"
            and authority.awaiting_reply
        )
    ):
        references.append(ReferenceDraft(kind="current_item"))
        traces.append(
            SignalTrace(
                field="reference.current_item",
                exact_value=None,
                semantic_value="active_current_item",
                resolution="context_fills",
            )
        )

    has_product_reference = any(
        item.kind
        in {"current_item", "current_batch", "candidate_ordinal"}
        for item in references
    )
    executable_goal: UnderstandingGoal | None = None
    if goal is UnderstandingGoal.ASSESSMENT and has_product_reference:
        executable_goal = (
            UnderstandingGoal.SUITABILITY
            if meaning.observation_candidates
            else UnderstandingGoal.KNOWLEDGE
        )
    elif (
        goal is UnderstandingGoal.CLARIFICATION
        and (
            has_product_reference
            or (
                context.pending_clarification
                is ClarificationCode.REFERENCE
                and bool(meaning.product_mentions)
            )
        )
        and meaning.question_meaning
    ):
        executable_goal = UnderstandingGoal.KNOWLEDGE
    if executable_goal is not None:
        goal = executable_goal
        traces.append(
            SignalTrace(
                field="goal.execution",
                exact_value=None,
                semantic_value=goal.value,
                resolution="context_fills",
            )
        )

    relative_drafts: list[RelativeDraft] = []
    for candidate in meaning.relative_candidates:
        try:
            grounded = ground_unique_text(text, candidate.raw_text)
            baseline = _relative_baseline(
                candidate.baseline_hint,
                references=references,
                authority=authority,
                source_span=SourceSpan(
                    start=grounded.start,
                    end=grounded.end,
                ),
            )
        except (SourceGroundingError, ReferenceAdmissionError):
            if not _relative_hint_is_non_authoritative(
                candidate,
                meaning=meaning,
                goal=goal,
                references=references,
            ):
                _append_issue(
                    issues,
                    code="ambiguous_reference",
                    detail="相对需求缺少唯一可绑定的基准商品或图片。",
                )
            continue
        concept_id = candidate.concept_id
        if (
            concept_id is not None
            and (
                concept_catalog is None
                or topic is None
                or not concept_catalog.admits(
                    profile=category_profile_for_topic(topic),
                    field_key=candidate.field_key,
                    concept_id=concept_id,
                )
            )
        ):
            concept_id = None
        draft = RelativeDraft(
            field_key=candidate.field_key,
            concept_id=concept_id,
            direction=candidate.direction,
            raw_text=candidate.raw_text,
            baseline=baseline,
        )
        if draft not in relative_drafts:
            relative_drafts.append(draft)
        if not any(
            _same_reference_binding(item, baseline)
            for item in references
        ):
            references.append(baseline)
        traces.append(
            SignalTrace(
                field=f"relative.{candidate.field_key}",
                exact_value=None,
                semantic_value=(
                    concept_id or candidate.raw_text
                ),
                resolution="semantic_fills",
            )
        )
    if (
        goal in _REFERENCE_REQUIRED_GOALS
        and not references
        and not meaning.product_mentions
        and not revision_proofs
        and not (
            meaning.continuity_hint == "return_to_focus"
            and (
                authority.current_item_available
                or authority.current_image_ordinal is not None
            )
        )
    ):
        _append_issue(
            issues,
            code="ambiguous_reference",
            detail="请明确要查看、比较或继续追问的商品或图片。",
        )

    product_mentions: list[ProductMentionDraft] = []
    for mention in meaning.product_mentions:
        try:
            grounded = ground_unique_text(text, mention.raw_text)
        except SourceGroundingError:
            _append_issue(
                issues,
                code="ambiguous_reference",
                detail="商品名称没有唯一绑定当前原话。",
            )
            continue
        product_mentions.append(
            ProductMentionDraft(
                text=mention.raw_text,
                source_span=SourceSpan(
                    start=grounded.start,
                    end=grounded.end,
                ),
            )
        )

    exact_budget_present = any(
        isinstance(item, BudgetDraft)
        for item in exact_constraints
    )
    if not exact_budget_present and meaning.budget_candidates:
        semantic_budget_candidates = []
        for candidate in meaning.budget_candidates:
            try:
                grounded = ground_unique_text(
                    text,
                    candidate.raw_text,
                )
            except SourceGroundingError:
                _append_issue(
                    issues,
                    code="invalid_budget",
                    detail="我没能准确对应你说的预算，请重新说一下。",
                )
                continue
            semantic_budget_candidates.append(
                SemanticNumberCandidate(
                    relation=candidate.relation,
                    raw_text=candidate.raw_text,
                    start=grounded.start,
                    end=grounded.end,
                    minimum=candidate.minimum,
                    maximum=candidate.maximum,
                )
            )
        budget_validation = validate_budget_candidates(
            message=text,
            candidates=semantic_budget_candidates,
            exact_constraints=exact_constraints,
            exact_issues=exact_issues,
        )
        if budget_validation.budget is not None:
            exact_constraints.append(budget_validation.budget)
        if budget_validation.issue is not None:
            issues.append(budget_validation.issue)

    preference_outcomes = admission.for_kind("preference")
    grounded_preference_candidates = []
    for candidate, outcome in zip(
        meaning.preference_candidates,
        preference_outcomes,
        strict=True,
    ):
        if outcome.disposition == "rejected_protocol":
            _append_issue(
                issues,
                code="ambiguous_reference",
                detail="偏好描述没有唯一对应到当前原话。",
            )
            continue
        try:
            ground_unique_text(text, candidate.raw_text)
        except SourceGroundingError:
            _append_issue(
                issues,
                code="ambiguous_reference",
                detail="偏好描述没有唯一绑定当前原话。",
            )
            continue
        grounded_preference_candidates.append(candidate)

    parent_exclusions = _compile_parent_exclusions(
        candidates=grounded_preference_candidates,
    )
    if parent_exclusions:
        parent_values = {
            item.value.casefold()
            for item in parent_exclusions
        }
        exact_constraints = [
            item
            for item in exact_constraints
            if not (
                isinstance(item, ExclusionDraft)
                and normalize_ingredient_entity(item.value).casefold()
                in parent_values
            )
        ]
        exact_constraints.extend(parent_exclusions)

    constraint_changes: list[ConstraintChangeDraft] = []
    change_outcomes = admission.for_kind("constraint_change")
    for candidate, outcome in zip(
        meaning.constraint_changes,
        change_outcomes,
        strict=True,
    ):
        if outcome.disposition == "rejected_protocol":
            _append_issue(
                issues,
                code="ambiguous_reference",
                detail="条件变更没有唯一绑定当前原话。",
            )
            continue
        grounded = ground_unique_text(text, candidate.raw_text)
        value = (
            normalize_ingredient_entity(candidate.raw_text)
            if candidate.parent_concept == "ingredient_exclusion"
            else candidate.normalized_value
        )
        bare_skin_withdrawal = (
            candidate.parent_concept == "skin"
            and candidate.requested_change == "remove"
            and value is None
        )
        if value is None and not bare_skin_withdrawal:
            _append_issue(
                issues,
                code="ambiguous_revision_target",
                detail="条件变更缺少父概念规范值。",
            )
            continue
        constraint_changes.append(
            ConstraintChangeDraft(
                parent_concept=candidate.parent_concept,
                requested_change=candidate.requested_change,
                value=value,
                source_span=SourceSpan(
                    start=grounded.start,
                    end=grounded.end,
                ),
            )
        )
    exact_skin_withdrawal = next(
        (
            proof
            for proof in parse_exact_revision_confirmations(text)
            if (
                proof.operation
                is ExactRevisionOperation.WITHDRAW_CONSTRAINT
                and proof.target is ExactRevisionTarget.SKIN
            )
        ),
        None,
    )
    if (
        exact_skin_withdrawal is not None
        and ActiveConstraintKind.SKIN
        in context.active_constraint_kinds
        and not any(
            item.parent_concept == "skin"
            for item in constraint_changes
        )
    ):
        constraint_changes.append(
            ConstraintChangeDraft(
                parent_concept="skin",
                requested_change="remove",
                value=None,
                source_span=exact_skin_withdrawal.source_span,
            )
        )
    withdrawn_values = {
        item.value.casefold()
        for item in constraint_changes
        if (
            item.requested_change == "remove"
            and item.value is not None
        )
    }
    withdrawn_efficacies = {
        item.value
        for item in constraint_changes
        if (
            item.parent_concept == "efficacy"
            and item.requested_change == "remove"
        )
    }
    if withdrawn_values:
        exact_constraints = [
            item
            for item in exact_constraints
            if not (
                isinstance(item, ExclusionDraft)
                and normalize_ingredient_entity(item.value).casefold()
                in withdrawn_values
            )
            and not (
                isinstance(item, EfficacyDraft)
                and item.value.value in withdrawn_efficacies
            )
        ]
    efficacy_replacements = {
        item.value
        for item in constraint_changes
        if (
            item.parent_concept == "efficacy"
            and item.requested_change == "replace"
        )
    }
    skin_replacements = {
        item.value
        for item in constraint_changes
        if (
            item.parent_concept == "skin"
            and item.requested_change == "replace"
        )
    }
    if efficacy_replacements or skin_replacements:
        exact_constraints = [
            item
            for item in exact_constraints
            if not (
                isinstance(item, EfficacyDraft)
                and efficacy_replacements
                and item.value.value not in efficacy_replacements
            )
            and not (
                isinstance(item, SkinDraft)
                and skin_replacements
                and item.value.value not in skin_replacements
            )
        ]
        if efficacy_replacements:
            replacement = next(iter(efficacy_replacements))
            target = EfficacyTarget(replacement)
            if not any(
                isinstance(item, EfficacyDraft)
                and item.value is target
                for item in exact_constraints
            ):
                exact_constraints.append(EfficacyDraft(value=target))
        if skin_replacements:
            replacement = next(iter(skin_replacements))
            target = SkinTarget(replacement)
            if not any(
                isinstance(item, SkinDraft)
                and item.value is target
                for item in exact_constraints
            ):
                exact_constraints.append(SkinDraft(value=target))

    preference_drafts: list[PreferenceDraft] = []
    if concept_catalog is not None and topic is not None:
        preference_drafts.extend(
            compile_concept_preferences(
                message=text,
                candidates=tuple(
                    candidate
                    for candidate in grounded_preference_candidates
                    if candidate.field_key != "ingredient_exclusion"
                ),
                profile=category_profile_for_topic(topic),
                catalog=concept_catalog,
            )
        )
    elif topic is None:
        preference_drafts.extend(
            PreferenceDraft(
                field_key=candidate.field_key,
                value=candidate.raw_text,
                preference_kind="free_descriptor",
                polarity=candidate.polarity,
            )
            for candidate, outcome in zip(
                meaning.preference_candidates,
                preference_outcomes,
                strict=True,
            )
            if (
                outcome.disposition == "retained_free"
                and candidate.strength == "ordinary"
            )
        )

    semantic_skin = _semantic_task_skin(
        preference_candidates=grounded_preference_candidates,
        observation_candidates=meaning.observation_candidates,
        observation_outcomes=admission.for_kind(
            "consultation_observation"
        ),
    )
    if semantic_skin is not None:
        exact_skin = next(
            (
                item.value
                for item in exact_constraints
                if isinstance(item, SkinDraft)
            ),
            None,
        )
        exact_constraints = [
            item
            for item in exact_constraints
            if not isinstance(item, SkinDraft)
        ]
        exact_constraints.append(SkinDraft(value=semantic_skin))
        traces.append(
            SignalTrace(
                field="skin",
                exact_value=(
                    exact_skin.value
                    if exact_skin is not None
                    else None
                ),
                semantic_value=semantic_skin.value,
                resolution="semantic_fills",
            )
        )

    observation_outcomes = admission.for_kind(
        "consultation_observation"
    )
    observations = [
        ":".join(
            (
                item.code,
                "present" if item.present else "absent",
                item.qualifier or "none",
            )
        )
        for item, outcome in zip(
            meaning.observation_candidates,
            observation_outcomes,
            strict=True,
        )
        if outcome.disposition == "admitted"
    ]
    for item in meaning.observation_candidates:
        try:
            ground_unique_text(text, item.raw_text)
        except SourceGroundingError:
            _append_issue(
                issues,
                code="ambiguous_reference",
                detail="观察描述没有唯一绑定当前原话。",
            )

    issues = _drop_resolved_exact_issues(
        issues,
        goal=goal,
        references=references,
        preferences=preference_drafts,
    )

    if topic is None and goal is UnderstandingGoal.RECOMMENDATION:
        _append_issue(
            issues,
            code="missing_category",
            detail="请明确要找的商品品类。",
        )

    fit_clarification_reply = (
        goal
        in {
            UnderstandingGoal.RECOMMENDATION,
            UnderstandingGoal.IMAGE_SIMILARITY,
        }
        and context.awaiting_reply
        and context.pending_clarification is ClarificationCode.GOAL
        and context.active_recommendation_mode == "fit"
        and topic is context.active_topic
        and (
            bool(preference_drafts)
            or bool(relative_drafts)
            or any(
                isinstance(item, (SkinDraft, EfficacyDraft))
                for item in exact_constraints
            )
        )
    )
    if single_image_comparison:
        recommendation_mode = "explore"
        recommendation_mode_basis = "similar_alternatives"
        recommendation_count = 3
    elif (
        fit_clarification_reply
        and (
            meaning.recommendation_mode is None
            or (
                meaning.recommendation_mode_basis is not None
                and meaning.recommendation_mode_basis.basis
                in {"broad_exploration", "similar_alternatives"}
            )
        )
    ):
        traces.append(
            SignalTrace(
                field="recommendation_mode",
                exact_value=context.active_recommendation_mode,
                semantic_value=meaning.recommendation_mode,
                resolution="context_fills",
            )
        )
        recommendation_mode = context.active_recommendation_mode
        recommendation_mode_basis = (
            context.active_recommendation_mode_basis
        )
        recommendation_count = context.active_recommendation_count
    elif (
        goal
        in {
            UnderstandingGoal.RECOMMENDATION,
            UnderstandingGoal.IMAGE_SIMILARITY,
        }
        and revision_proofs
        and topic is context.active_topic
        and context.active_recommendation_mode is not None
        and (
            meaning.recommendation_mode is None
            or (
                meaning.recommendation_mode_basis is not None
                and meaning.recommendation_mode_basis.basis
                in {"broad_exploration", "similar_alternatives"}
            )
        )
    ):
        traces.append(
            SignalTrace(
                field="recommendation_mode",
                exact_value=context.active_recommendation_mode,
                semantic_value=meaning.recommendation_mode,
                resolution="context_fills",
            )
        )
        recommendation_mode = context.active_recommendation_mode
        recommendation_mode_basis = (
            context.active_recommendation_mode_basis
        )
        recommendation_count = context.active_recommendation_count
    elif (
        goal is UnderstandingGoal.RECOMMENDATION
        and semantic_goal is UnderstandingGoal.FOLLOWUP
    ):
        recommendation_mode = context.active_recommendation_mode
        recommendation_mode_basis = (
            context.active_recommendation_mode_basis
        )
        recommendation_count = context.active_recommendation_count
    else:
        recommendation_mode = meaning.recommendation_mode
        recommendation_mode_basis = (
            meaning.recommendation_mode_basis.basis
            if meaning.recommendation_mode_basis is not None
            else None
        )
        recommendation_count = meaning.recommendation_count

    return StructuredUnderstanding(
        goal=goal,
        recommendation_mode=recommendation_mode,
        recommendation_mode_basis=recommendation_mode_basis,
        recommendation_count=recommendation_count,
        topic=topic,
        observations=observations,
        exact_constraints=exact_constraints,
        preference_drafts=preference_drafts,
        constraint_changes=constraint_changes,
        relative_drafts=relative_drafts,
        semantic_proposals=[
            ":".join(
                (
                    item.atom_kind,
                    item.disposition,
                    item.normalized_value or "",
                    item.raw_text,
                )
            )
            for item in admission.outcomes
        ],
        signal_trace=traces,
        references=references,
        product_mentions=product_mentions,
        image_references=[],
        uncertainties=issues,
        confidence=0.0 if issues else 1.0,
        question_meaning=meaning.question_meaning,
        safety_sensitive=meaning.safety_language == "safety",
        semantic_authoritative=True,
    )


def _compile_parent_exclusions(
    *,
    candidates,
) -> list[ExclusionDraft]:
    values: list[str] = []
    for candidate in candidates:
        if (
            candidate.field_key == "ingredient_exclusion"
            and candidate.polarity == "avoid"
        ):
            values.append(
                normalize_ingredient_entity(candidate.raw_text)
            )
    return [
        ExclusionDraft(value=value)
        for value in dict.fromkeys(values)
    ]


def _append_issue(
    issues: list[UnderstandingIssue],
    *,
    code: str,
    detail: str,
) -> None:
    if any(item.code == code for item in issues):
        return
    issues.append(
        UnderstandingIssue.model_validate(
            {"code": code, "detail": detail},
            strict=True,
        )
    )


def _infers_broad_skincare_topic(
    *,
    message: str,
    meaning: TurnMeaning,
    goal: UnderstandingGoal,
    concept_catalog: ConceptPreferenceCatalog | None,
) -> bool:
    candidates = tuple(meaning.preference_candidates)
    if (
        goal is not UnderstandingGoal.RECOMMENDATION
        or concept_catalog is None
        or not candidates
    ):
        return False
    for candidate in candidates:
        if (
            candidate.field_key != "efficacy"
            or candidate.concept_id is None
            or not candidate.concept_id.startswith("efficacy.")
            or not concept_catalog.admits(
                profile=CategoryProfile.SKINCARE,
                field_key=candidate.field_key,
                concept_id=candidate.concept_id,
            )
        ):
            return False
        try:
            ground_unique_text(message, candidate.raw_text)
        except SourceGroundingError:
            return False
    return True


def _semantic_task_skin(
    *,
    preference_candidates,
    observation_candidates,
    observation_outcomes,
) -> SkinTarget | None:
    skin_concepts = {
        candidate.concept_id
        for candidate in preference_candidates
        if (
            candidate.field_key == "suitable_skin"
            and candidate.polarity == "prefer"
            and candidate.strength == "ordinary"
        )
    }
    admitted_observations = {
        candidate.code
        for candidate, outcome in zip(
            observation_candidates,
            observation_outcomes,
            strict=True,
        )
        if (
            candidate.present
            and outcome.disposition == "admitted"
        )
    }
    if (
        {
            "suitable_skin.oily",
            "suitable_skin.sensitive",
        }
        <= skin_concepts
        and {"oiliness", "product_tolerance"}
        <= admitted_observations
    ):
        return SkinTarget.OILY_SENSITIVE
    return None


def _relative_baseline(
    hint: str,
    *,
    references: list[ReferenceDraft],
    authority: SemanticRouteBindingAuthority,
    source_span: SourceSpan,
) -> ReferenceDraft:
    if hint == "current_item":
        if not authority.current_item_available:
            raise ReferenceAdmissionError("unbound")
        return ReferenceDraft(
            kind="current_item",
            source_span=source_span,
        )
    if hint in {"candidate_ordinal", "image_ordinal"}:
        expected = (
            "candidate_ordinal"
            if hint == "candidate_ordinal"
            else "image_ordinal"
        )
        admitted = tuple(
            item
            for item in references
            if item.kind == expected
        )
        if (
            not admitted
            and expected == "image_ordinal"
            and authority.current_image_ordinal is not None
        ):
            return ReferenceDraft(
                kind="image_ordinal",
                ordinal=authority.current_image_ordinal,
                source_span=source_span,
            )
        if len(admitted) != 1:
            raise ReferenceAdmissionError(
                "unbound" if not admitted else "ambiguous"
            )
        return admitted[0]
    raise ReferenceAdmissionError("unbound")


def _same_reference_binding(
    left: ReferenceDraft,
    right: ReferenceDraft,
) -> bool:
    return (
        left.kind == right.kind
        and left.ordinal == right.ordinal
    )


def _collapse_equivalent_context_references(
    references: list[ReferenceDraft],
    *,
    authority: SemanticRouteBindingAuthority,
) -> list[ReferenceDraft]:
    if (
        authority.current_item_ordinal is None
        or not any(item.kind == "current_item" for item in references)
    ):
        return references
    return [
        item
        for item in references
        if not (
            item.kind == "candidate_ordinal"
            and item.ordinal == authority.current_item_ordinal
        )
    ]


def _image_anchored_product_coreference(
    *,
    message: str,
    mention,
    references: list[ReferenceDraft],
) -> ReferenceDraft | None:
    if (
        mention.object_family_hint != "product"
        or mention.plurality_hint != "single"
    ):
        return None
    try:
        grounded = ground_unique_text(message, mention.raw_text)
    except SourceGroundingError:
        return None
    anchors = [
        item
        for item in references
        if (
            item.kind == "image_ordinal"
            and item.ordinal is not None
            and item.source_span is not None
            and item.source_span.end <= grounded.start
            and message[item.source_span.end:grounded.start]
            in {"", "的"}
        )
    ]
    bindings = {
        (item.kind, item.ordinal)
        for item in anchors
    }
    if len(bindings) != 1:
        return None
    anchor = anchors[-1]
    return ReferenceDraft(
        kind="image_ordinal",
        ordinal=anchor.ordinal,
        source_span=SourceSpan(
            start=grounded.start,
            end=grounded.end,
        ),
    )


def _exact_reference_is_admitted(
    reference: ReferenceDraft,
    authority: SemanticRouteBindingAuthority,
) -> bool:
    if reference.kind == "candidate_ordinal":
        return reference.ordinal in authority.candidate_ordinals
    if reference.kind == "image_ordinal":
        return reference.ordinal in authority.image_ordinals
    if reference.kind == "current_item":
        return authority.current_item_available
    if reference.kind == "current_batch":
        return authority.current_batch_available
    if reference.kind == "current_topic":
        return authority.current_topic is not None
    if reference.kind == "previous_constraint":
        return bool(authority.previous_constraint_kinds)
    return False


def _relative_hint_is_non_authoritative(
    candidate,
    *,
    meaning: TurnMeaning,
    goal: UnderstandingGoal,
    references: list[ReferenceDraft],
) -> bool:
    if (
        goal is UnderstandingGoal.COMPARISON
        and any(item.kind == "current_batch" for item in references)
    ):
        return True
    if goal is not UnderstandingGoal.RECOMMENDATION:
        return False
    return any(
        item.strength == "ordinary"
        and item.field_key == candidate.field_key
        and (
            item.concept_id == candidate.concept_id
            or item.raw_text in candidate.raw_text
            or candidate.raw_text in item.raw_text
        )
        for item in meaning.preference_candidates
    )


def _drop_resolved_exact_issues(
    issues: list[UnderstandingIssue],
    *,
    goal: UnderstandingGoal,
    references: list[ReferenceDraft],
    preferences: list[PreferenceDraft],
) -> list[UnderstandingIssue]:
    resolved_codes: set[str] = set()
    if any(
        item.preference_kind == "free_descriptor"
        and item.polarity == "avoid"
        for item in preferences
    ):
        resolved_codes.add("unsupported_attribute_exclusion")
    if goal is UnderstandingGoal.COMPARISON:
        if len({
            item.ordinal
            for item in references
            if item.kind == "candidate_ordinal"
        }) >= 2:
            resolved_codes.add("ambiguous_candidate_reference")
        if len({
            item.ordinal
            for item in references
            if item.kind == "image_ordinal"
        }) >= 2:
            resolved_codes.add("ambiguous_image_reference")
    return [
        issue
        for issue in issues
        if issue.code not in resolved_codes
    ]


__all__ = ["compile_turn_meaning"]
