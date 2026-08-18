from __future__ import annotations

from collections.abc import Sequence
import unicodedata

from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    ContextConstraintSignal,
    EfficacyDraft,
    ExactConstraintDraft,
    ExactRevisionConfirmation,
    ExactRevisionOperation,
    ExactRevisionTarget,
    ExclusionDraft,
    InclusionDraft,
    PreferenceDraft,
    ProductMentionDraft,
    ReferenceDraft,
    SignalTrace,
    SkinDraft,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
    UnderstandingIssue,
)
from app.guide.understanding.budget_candidate_validation import (
    validate_budget_candidates,
)
from app.guide.understanding.exact_parsing import (
    exact_revision_confirmation_matches_message,
    parse_exact_constraints,
    parse_hard_category_exclusions,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    ObservationCode,
    SemanticContext,
    SemanticIntentProposal,
    SemanticLaneDisposition,
    SemanticObservation,
    SemanticPreferenceCandidate,
    SemanticPreferenceField,
    SemanticPreferenceStrength,
    SemanticProductMention,
    SemanticReference,
)
from app.guide.intent.facet_preferences import (
    preference_draft_for_candidate,
)


_MINIMUM_SEMANTIC_CONFIDENCE = 0.70
_EXACT_CONSTRAINT_TYPES = (
    BudgetDraft,
    CategoryDraft,
    SkinDraft,
    ExclusionDraft,
    InclusionDraft,
    EfficacyDraft,
    ReferenceDraft,
)
_CLARIFICATION_BY_UNCLEAR_OBSERVATION = {
    ObservationCode.GOAL_UNCLEAR: ClarificationCode.GOAL,
    ObservationCode.TOPIC_UNCLEAR: ClarificationCode.TOPIC,
    ObservationCode.REFERENCE_UNCLEAR: ClarificationCode.REFERENCE,
    ObservationCode.CURRENT_BUDGET_UNKNOWN: ClarificationCode.BUDGET,
}
_REFERENCE_REQUIRED_GOALS = frozenset(
    {
        UnderstandingGoal.COMPARISON,
        UnderstandingGoal.SUITABILITY,
        UnderstandingGoal.FOLLOWUP,
    }
)
_EXACT_REFERENCE_ISSUE_BY_KIND = {
    "candidate_ordinal": "ambiguous_candidate_reference",
    "image_ordinal": "ambiguous_image_reference",
}
_EXACT_REFERENCE_KIND_BY_ISSUE = {
    issue: kind
    for kind, issue in _EXACT_REFERENCE_ISSUE_BY_KIND.items()
}
_REVISION_TARGET_VALUE_BY_ISSUE = {
    "missing_revision_target": "missing",
    "ambiguous_revision_target": "ambiguous",
}


def merge_intent_signals(
    *,
    message: str,
    exact_constraints: Sequence[ExactConstraintDraft],
    exact_issues: Sequence[UnderstandingIssue],
    semantic: SemanticIntentProposal | None,
    exact_revision_confirmations: Sequence[
        ExactRevisionConfirmation
    ] = (),
    semantic_disposition: SemanticLaneDisposition | None = None,
    context: SemanticContext | None = None,
) -> StructuredUnderstanding:
    """Merge validated independent signals without mutating any input.

    ``context`` carries the typed session/profile lane (本轮>会话确认>长期画像).
    It only fills open semantic slots that neither the exact path nor the
    current-turn semantic proposal supplied; it never overrides an exact hard
    constraint or a current-turn semantic value. When ``context`` is ``None``
    the behavior is identical to the exact+semantic two-lane merge.
    """
    resolved_semantic_disposition = _resolve_semantic_disposition(
        semantic=semantic,
        semantic_disposition=semantic_disposition,
    )
    _validate_inputs(
        message=message,
        exact_constraints=exact_constraints,
        exact_issues=exact_issues,
        exact_revision_confirmations=exact_revision_confirmations,
        semantic=semantic,
        semantic_disposition=resolved_semantic_disposition,
        context=context,
    )
    current_revision_confirmations = tuple(
        confirmation
        for confirmation in exact_revision_confirmations
        if exact_revision_confirmation_matches_message(
            text=message,
            confirmation=confirmation,
        )
    )
    constraints, exact_reference_ambiguities = (
        _normalize_exact_references(exact_constraints)
    )
    issues = list(exact_issues)
    for issue in issues:
        kind = _EXACT_REFERENCE_KIND_BY_ISSUE.get(issue.code)
        if kind is not None:
            exact_reference_ambiguities.setdefault(kind, [])
    for kind in exact_reference_ambiguities:
        code = _EXACT_REFERENCE_ISSUE_BY_KIND[kind]
        if any(issue.code == code for issue in issues):
            continue
        issues.append(
            UnderstandingIssue(
                code=code,
                detail=(
                    f"精确理解对 {kind} 给出多个不同指代，"
                    "请只确认一个序号。"
                ),
            )
        )
    exact_topics = _distinct_exact_topics(constraints)
    exact_topic = exact_topics[0] if len(exact_topics) == 1 else None

    if semantic is None:
        hard_exclusions = parse_hard_category_exclusions(message)
        if (
            resolved_semantic_disposition
            is SemanticLaneDisposition.SKIPPED_BY_CONTRACT
            and _has_matching_closed_operation_proof(
                message=message,
                constraints=constraints,
                confirmations=current_revision_confirmations,
            )
            and exact_topic is not None
            and not issues
            and exact_topic not in hard_exclusions
        ):
            return _understanding(
                goal=UnderstandingGoal.RECOMMENDATION,
                topic=exact_topic,
                constraints=constraints,
                issues=issues,
                signal_trace=[
                    *_exact_topic_early_exit_trace(
                        exact_topic=exact_topic,
                        semantic_topic=None,
                    ),
                    SignalTrace(
                        field="semantic",
                        exact_value=None,
                        semantic_value=None,
                        resolution="semantic_skipped_by_contract",
                    ),
                ],
                confidence=1.0,
            )
        _append_issue(
            issues,
            code="missing_category",
            detail=(
                (
                    "协议闭合的精确操作缺少可执行目标，"
                    if (
                        resolved_semantic_disposition
                        is SemanticLaneDisposition.SKIPPED_BY_CONTRACT
                    )
                    else "语义理解当前不可用，"
                )
                + "请明确要找的商品品类和目标。"
            ),
        )
        return _understanding(
            goal=UnderstandingGoal.CLARIFICATION,
            topic=exact_topic,
            constraints=constraints,
            issues=issues,
            signal_trace=[
                *_exact_topic_early_exit_trace(
                    exact_topic=exact_topic,
                    semantic_topic=None,
                ),
                *_exact_reference_ambiguity_traces(
                    exact_reference_ambiguities,
                    semantic_references=(),
                ),
                *_revision_target_traces(
                    issues,
                    semantic_topic=None,
                ),
                SignalTrace(
                    field="semantic",
                    exact_value=None,
                    semantic_value=None,
                    resolution=(
                        "semantic_skipped_by_contract"
                        if (
                            resolved_semantic_disposition
                            is SemanticLaneDisposition.SKIPPED_BY_CONTRACT
                        )
                        else "semantic_unavailable"
                    ),
                )
            ],
            confidence=0.0,
        )

    if semantic.confidence < _MINIMUM_SEMANTIC_CONFIDENCE:
        _append_issue(
            issues,
            code="missing_category",
            detail=(
                "语义理解置信度不足，"
                "请明确要找的商品品类和目标。"
            ),
        )
        return _understanding(
            goal=UnderstandingGoal.CLARIFICATION,
            topic=exact_topic,
            constraints=constraints,
            issues=issues,
            signal_trace=[
                *_exact_topic_early_exit_trace(
                    exact_topic=exact_topic,
                    semantic_topic=semantic.topic,
                ),
                *_exact_reference_ambiguity_traces(
                    exact_reference_ambiguities,
                    semantic_references=semantic.references,
                ),
                *_revision_target_traces(
                    issues,
                    semantic_topic=semantic.topic,
                ),
                SignalTrace(
                    field="semantic_confidence",
                    exact_value=None,
                    semantic_value=_stable_confidence(
                        semantic.confidence
                    ),
                    resolution="clarify",
                )
            ],
            confidence=0.0,
        )

    traces: list[SignalTrace] = []
    budget_validation = validate_budget_candidates(
        message=message,
        candidates=semantic.number_candidates,
        exact_constraints=constraints,
        exact_issues=exact_issues,
    )
    if budget_validation.budget is not None:
        constraints.append(budget_validation.budget)
    if budget_validation.issue is not None:
        issues.append(budget_validation.issue)
    if budget_validation.resolution != "no_candidate":
        traces.append(
            SignalTrace(
                field="number_candidate.budget",
                exact_value=(
                    _budget_trace_value(constraints)
                    if budget_validation.resolution == "exact_wins"
                    else None
                ),
                semantic_value="|".join(
                    candidate.raw_text
                    for candidate in semantic.number_candidates
                )
                or None,
                resolution=budget_validation.resolution,
            )
        )
    goal = _resolve_semantic_goal(
        semantic=semantic,
        constraints=constraints,
        context=context,
    )
    topic = _merge_topic(
        message=message,
        exact_topics=exact_topics,
        semantic_topic=semantic.topic,
        constraints=constraints,
        issues=issues,
        traces=traces,
        context=context,
        allow_missing=(
            goal
            in {
                UnderstandingGoal.COMPARISON,
                UnderstandingGoal.FOLLOWUP,
                UnderstandingGoal.IMAGE_SIMILARITY,
            }
            and _has_image_reference(
                constraints=constraints,
                semantic_references=semantic.references,
            )
        ),
    )
    goal_resolution = "semantic_fills"
    goal_exact_value: str | None = None
    if goal is not semantic.goal:
        goal_resolution = "exact_wins"
        goal_exact_value = goal.value
    elif goal is UnderstandingGoal.CLARIFICATION:
        goal_resolution = "clarify"
    traces.append(
        SignalTrace(
            field="goal",
            exact_value=goal_exact_value,
            semantic_value=semantic.goal.value,
            resolution=goal_resolution,
        )
    )
    references = _merge_references(
        message=message,
        constraints=constraints,
        semantic_references=semantic.references,
        revision_confirmations=current_revision_confirmations,
        issues=issues,
        traces=traces,
        exact_ambiguities=exact_reference_ambiguities,
        context=context,
    )
    constraints = [
        item
        for item in constraints
        if (
            not isinstance(item, ReferenceDraft)
            or item in references
        )
    ]
    product_mentions = _merge_product_mentions(
        message=message,
        semantic_mentions=semantic.product_mentions,
        issues=issues,
        traces=traces,
    )
    preference_drafts = _merge_preference_candidates(
        message=message,
        candidates=semantic.preference_candidates,
        constraints=constraints,
        confirmations=current_revision_confirmations,
        issues=issues,
        traces=traces,
    )

    if goal is UnderstandingGoal.CLARIFICATION:
        _append_issue(
            issues,
            code="missing_category",
            detail=(
                "语义目标仍不明确，需要你确认要完成的"
                "导购任务或商品品类。"
            ),
        )
    if semantic.clarification_hint is not None:
        if _clarification_is_required(
            semantic.clarification_hint,
            goal=goal,
            topic=topic,
            references=references,
            product_mentions=product_mentions,
            budget_resolved=any(
                isinstance(item, BudgetDraft)
                for item in constraints
            ),
            issues=issues,
            observations=semantic.observations,
        ):
            existing_issue = _existing_clarification_issue(
                semantic.clarification_hint,
                issues,
            )
            if existing_issue is not None:
                traces.append(
                    SignalTrace(
                        field="clarification_hint",
                        exact_value=existing_issue,
                        semantic_value=semantic.clarification_hint.value,
                        resolution="agree",
                    )
                )
            else:
                _append_clarification_hint(
                    issues,
                    traces,
                    semantic.clarification_hint,
                )
        else:
            _append_ignored_stale_signal(
                traces,
                field="clarification_hint",
                value=semantic.clarification_hint.value,
            )
    for observation in semantic.observations:
        if not observation.present:
            continue
        clarification = _CLARIFICATION_BY_UNCLEAR_OBSERVATION.get(
            observation.code
        )
        if clarification is None:
            continue
        if _clarification_is_required(
            clarification,
            goal=goal,
            topic=topic,
            references=references,
            product_mentions=product_mentions,
            budget_resolved=any(
                isinstance(item, BudgetDraft)
                for item in constraints
            ),
            issues=issues,
            observations=semantic.observations,
        ):
            existing_issue = _existing_clarification_issue(
                clarification,
                issues,
            )
            if existing_issue is not None:
                traces.append(
                    SignalTrace(
                        field=f"observation.{observation.code.value}",
                        exact_value=existing_issue,
                        semantic_value="present",
                        resolution="agree",
                    )
                )
            else:
                _append_issue(
                    issues,
                    code="missing_category",
                    detail=(
                        "语义信号仍有未确认项，"
                        "请补充目标、品类或指代。"
                    ),
                )
                traces.append(
                    SignalTrace(
                        field=f"observation.{observation.code.value}",
                        exact_value=None,
                        semantic_value="present",
                        resolution="clarify",
                    )
                )
        else:
            _append_ignored_stale_signal(
                traces,
                field=f"observation.{observation.code.value}",
                value="present",
            )

    return _understanding(
        goal=goal,
        topic=topic,
        constraints=constraints,
        issues=issues,
        observations=[
            _project_observation(item)
            for item in semantic.observations
        ],
        semantic_proposals=[
            *(
                f"concern={concern.value}"
                for concern in semantic.concerns
            ),
        ],
        references=references,
        product_mentions=product_mentions,
        preference_drafts=preference_drafts,
        question_meaning=semantic.question_meaning,
        safety_sensitive=semantic.safety_sensitive,
        signal_trace=traces,
        confidence=semantic.confidence if not issues else 0.0,
    )


def merge_context_signals(
    understanding: StructuredUnderstanding,
    *,
    signals: Sequence[ContextConstraintSignal],
) -> StructuredUnderstanding:
    """Fill empty hard-constraint slots from typed session/profile signals."""
    if not isinstance(understanding, StructuredUnderstanding):
        raise TypeError(
            "understanding must be a validated StructuredUnderstanding"
        )
    if (
        isinstance(signals, (str, bytes))
        or not isinstance(signals, Sequence)
        or any(
            not isinstance(signal, ContextConstraintSignal)
            for signal in signals
        )
    ):
        raise TypeError(
            "signals must contain typed ContextConstraintSignal values"
        )

    constraints = list(understanding.exact_constraints)
    traces = list(understanding.signal_trace)
    initial_by_kind = {
        constraint.kind: constraint
        for constraint in constraints
        if not isinstance(constraint, ReferenceDraft)
    }
    selected_source_by_kind: dict[str, str] = {}
    selected_by_kind: dict[str, ExactConstraintDraft] = {}
    ordered_signals = sorted(
        enumerate(signals),
        key=lambda item: (
            0 if item[1].source == "session" else 1,
            item[0],
        ),
    )

    for _, signal in ordered_signals:
        candidate = signal.constraint
        kind = candidate.kind
        field = f"context.{kind}.{signal.source}"
        initial = initial_by_kind.get(kind)
        if initial is not None:
            traces.append(
                SignalTrace(
                    field=field,
                    exact_value=_constraint_trace_value(initial),
                    semantic_value=_constraint_trace_value(candidate),
                    resolution="exact_wins",
                )
            )
            continue

        selected_source = selected_source_by_kind.get(kind)
        selected = selected_by_kind.get(kind)
        if selected_source is None:
            selected_source_by_kind[kind] = signal.source
            selected_by_kind[kind] = candidate
            constraints.append(candidate.model_copy(deep=True))
            traces.append(
                SignalTrace(
                    field=field,
                    exact_value=None,
                    semantic_value=_constraint_trace_value(candidate),
                    resolution="context_fills",
                )
            )
            continue
        if selected_source != signal.source:
            traces.append(
                SignalTrace(
                    field=field,
                    exact_value=(
                        _constraint_trace_value(selected)
                        if selected is not None
                        else None
                    ),
                    semantic_value=_constraint_trace_value(candidate),
                    resolution="exact_wins",
                )
            )
            continue
        if isinstance(candidate, ExclusionDraft):
            if any(
                isinstance(item, ExclusionDraft)
                and item.value == candidate.value
                for item in constraints
            ):
                continue
            constraints.append(candidate.model_copy(deep=True))
            traces.append(
                SignalTrace(
                    field=field,
                    exact_value=None,
                    semantic_value=_constraint_trace_value(candidate),
                    resolution="context_fills",
                )
            )
            continue
        if (
            selected is not None
            and selected.model_dump(mode="python")
            != candidate.model_dump(mode="python")
        ):
            raise ValueError(
                f"conflicting {signal.source} context signals for {kind}"
            )

    return understanding.model_copy(
        update={
            "exact_constraints": constraints,
            "signal_trace": traces,
        },
        deep=True,
    )


def _validate_inputs(
    *,
    message: str,
    exact_constraints: Sequence[ExactConstraintDraft],
    exact_issues: Sequence[UnderstandingIssue],
    exact_revision_confirmations: Sequence[
        ExactRevisionConfirmation
    ],
    semantic: SemanticIntentProposal | None,
    semantic_disposition: SemanticLaneDisposition,
    context: SemanticContext | None = None,
) -> None:
    if not isinstance(message, str):
        raise TypeError("message must be str")
    if not 1 <= len(message) <= 4000:
        raise ValueError("message length must be between 1 and 4000")
    if (
        isinstance(exact_constraints, (str, bytes))
        or not isinstance(exact_constraints, Sequence)
        or any(
            not isinstance(item, _EXACT_CONSTRAINT_TYPES)
            for item in exact_constraints
        )
    ):
        raise TypeError(
            "exact_constraints must contain typed exact drafts"
        )
    if (
        isinstance(exact_issues, (str, bytes))
        or not isinstance(exact_issues, Sequence)
        or any(
            not isinstance(item, UnderstandingIssue)
            for item in exact_issues
        )
    ):
        raise TypeError(
            "exact_issues must contain UnderstandingIssue values"
        )
    if (
        isinstance(exact_revision_confirmations, (str, bytes))
        or not isinstance(exact_revision_confirmations, Sequence)
        or any(
            not isinstance(item, ExactRevisionConfirmation)
            for item in exact_revision_confirmations
        )
    ):
        raise TypeError(
            "exact_revision_confirmations must contain "
            "ExactRevisionConfirmation values"
        )
    if semantic is not None and not isinstance(
        semantic,
        SemanticIntentProposal,
    ):
        raise TypeError(
            "semantic must be a validated SemanticIntentProposal or None"
        )
    if not isinstance(
        semantic_disposition,
        SemanticLaneDisposition,
    ):
        raise TypeError(
            "semantic_disposition must be a SemanticLaneDisposition"
        )
    if context is not None and not isinstance(context, SemanticContext):
        raise TypeError(
            "context must be a validated SemanticContext or None"
        )


def _resolve_semantic_disposition(
    *,
    semantic: SemanticIntentProposal | None,
    semantic_disposition: SemanticLaneDisposition | None,
) -> SemanticLaneDisposition:
    if semantic_disposition is None:
        return (
            SemanticLaneDisposition.AVAILABLE
            if semantic is not None
            else SemanticLaneDisposition.UNAVAILABLE
        )
    if not isinstance(
        semantic_disposition,
        SemanticLaneDisposition,
    ):
        raise TypeError(
            "semantic_disposition must be a SemanticLaneDisposition or None"
        )
    if (
        semantic is None
        and semantic_disposition is SemanticLaneDisposition.AVAILABLE
    ):
        raise ValueError(
            "available semantic disposition requires a proposal"
        )
    if (
        semantic is not None
        and semantic_disposition
        is not SemanticLaneDisposition.AVAILABLE
    ):
        raise ValueError(
            "semantic proposal requires available disposition"
        )
    return semantic_disposition


def _distinct_exact_topics(
    constraints: Sequence[ExactConstraintDraft],
) -> list[TopicCode]:
    topics: list[TopicCode] = []
    for item in constraints:
        if (
            isinstance(item, CategoryDraft)
            and item.value not in topics
        ):
            topics.append(item.value)
    return topics


def _budget_trace_value(
    constraints: Sequence[ExactConstraintDraft],
) -> str | None:
    budget = next(
        (
            item
            for item in constraints
            if isinstance(item, BudgetDraft)
        ),
        None,
    )
    if budget is None:
        return None
    minimum = (
        str(budget.minimum)
        if budget.minimum is not None
        else ""
    )
    maximum = (
        str(budget.maximum)
        if budget.maximum is not None
        else ""
    )
    return f"{minimum}:{maximum}"


def _exact_topic_early_exit_trace(
    *,
    exact_topic: TopicCode | None,
    semantic_topic: TopicCode | None,
) -> list[SignalTrace]:
    if exact_topic is None:
        return []
    return [
        SignalTrace(
            field="topic",
            exact_value=exact_topic.value,
            semantic_value=_topic_value(semantic_topic),
            resolution="exact_wins",
        )
    ]


def _resolve_semantic_goal(
    *,
    semantic: SemanticIntentProposal,
    constraints: Sequence[ExactConstraintDraft],
    context: SemanticContext | None,
) -> UnderstandingGoal:
    if semantic.goal is not UnderstandingGoal.CLARIFICATION:
        return semantic.goal
    reference_clarification = (
        semantic.clarification_hint is ClarificationCode.REFERENCE
        or any(
            observation.present
            and observation.code is ObservationCode.REFERENCE_UNCLEAR
            for observation in semantic.observations
        )
    )
    if not reference_clarification:
        return semantic.goal
    exact_references = [
        item
        for item in constraints
        if isinstance(item, ReferenceDraft)
    ]
    if len(exact_references) != 1:
        return semantic.goal
    if _reference_context_issue(
        exact_references[0],
        context=context,
    ) is not None:
        return semantic.goal
    return UnderstandingGoal.FOLLOWUP


def _has_image_reference(
    *,
    constraints: Sequence[ExactConstraintDraft],
    semantic_references: Sequence[SemanticReference],
) -> bool:
    return any(
        isinstance(item, ReferenceDraft)
        and item.kind == "image_ordinal"
        for item in constraints
    ) or any(
        item.kind == "image_ordinal"
        for item in semantic_references
    )


def _merge_topic(
    *,
    message: str,
    exact_topics: list[TopicCode],
    semantic_topic: TopicCode | None,
    constraints: list[ExactConstraintDraft],
    issues: list[UnderstandingIssue],
    traces: list[SignalTrace],
    context: SemanticContext | None = None,
    allow_missing: bool = False,
) -> TopicCode | None:
    exact_topic = exact_topics[0] if len(exact_topics) == 1 else None
    revision_traces = _revision_target_traces(
        issues,
        semantic_topic=semantic_topic,
    )
    if revision_traces:
        traces.extend(revision_traces)
        return None
    if len(exact_topics) > 1 or any(
        issue.code == "ambiguous_category"
        for issue in issues
    ):
        _append_issue(
            issues,
            code="ambiguous_category",
            detail=(
                "本轮存在同级品类冲突，请只确认一个目标品类。"
            ),
        )
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=_join_topics(exact_topics),
                semantic_value=_topic_value(semantic_topic),
                resolution="clarify",
            )
        )
        return None

    hard_exclusions = parse_hard_category_exclusions(message)
    if (
        semantic_topic is not None
        and semantic_topic in hard_exclusions
    ):
        _append_issue(
            issues,
            code="ambiguous_category",
            detail=(
                "语义品类与本轮明确排除的品类冲突，"
                "请确认目标品类。"
            ),
        )
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=f"excluded:{semantic_topic.value}",
                semantic_value=semantic_topic.value,
                resolution="exact_wins",
            )
        )
        return exact_topic

    if exact_topic is not None and semantic_topic is exact_topic:
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=exact_topic.value,
                semantic_value=semantic_topic.value,
                resolution="agree",
            )
        )
        return exact_topic

    if exact_topic is not None and semantic_topic is not None:
        _append_issue(
            issues,
            code="ambiguous_category",
            detail=(
                "精确品类与语义品类不一致，请确认一个目标品类。"
            ),
        )
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=exact_topic.value,
                semantic_value=semantic_topic.value,
                resolution="clarify",
            )
        )
        return exact_topic

    if exact_topic is not None:
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=exact_topic.value,
                semantic_value=None,
                resolution="exact_wins",
            )
        )
        return exact_topic

    if semantic_topic is not None:
        constraints.append(CategoryDraft(value=semantic_topic))
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=None,
                semantic_value=semantic_topic.value,
                resolution="semantic_fills",
            )
        )
        return semantic_topic

    context_topic = context.active_topic if context is not None else None
    if (
        context_topic is not None
        and context_topic not in hard_exclusions
    ):
        constraints.append(CategoryDraft(value=context_topic))
        traces.append(
            SignalTrace(
                field="topic",
                exact_value=None,
                semantic_value=context_topic.value,
                resolution="context_fills",
            )
        )
        return context_topic

    if allow_missing:
        return None

    _append_issue(
        issues,
        code="missing_category",
        detail="当前缺少明确品类，请确认要找哪类商品。",
    )
    traces.append(
        SignalTrace(
            field="topic",
            exact_value=None,
            semantic_value=None,
            resolution="clarify",
        )
    )
    return None


def _append_clarification_hint(
    issues: list[UnderstandingIssue],
    traces: list[SignalTrace],
    hint: ClarificationCode,
) -> None:
    _append_issue(
        issues,
        code="missing_category",
        detail=(
            f"语义信号要求补充 {hint.value}，"
            "请确认后再继续。"
        ),
    )
    traces.append(
        SignalTrace(
            field="clarification_hint",
            exact_value=None,
            semantic_value=hint.value,
            resolution="clarify",
        )
    )


def _clarification_is_required(
    clarification: ClarificationCode,
    *,
    goal: UnderstandingGoal,
    topic: TopicCode | None,
    references: Sequence[ReferenceDraft],
    product_mentions: Sequence[ProductMentionDraft],
    budget_resolved: bool,
    issues: Sequence[UnderstandingIssue],
    observations: Sequence[SemanticObservation],
) -> bool:
    if clarification is ClarificationCode.GOAL:
        return (
            goal is UnderstandingGoal.CLARIFICATION
            and topic is not None
        )
    if clarification is ClarificationCode.TOPIC:
        return topic is None
    if clarification is ClarificationCode.REFERENCE:
        return (
            goal in _REFERENCE_REQUIRED_GOALS
            and not references
            and not product_mentions
        )
    if clarification is ClarificationCode.BUDGET:
        return (
            any(
                issue.code
                in {"invalid_budget", "unsupported_budget_format"}
                for issue in issues
            )
            or (
                not budget_resolved
                and any(
                    observation.present
                    and observation.code
                    is ObservationCode.CURRENT_BUDGET_UNKNOWN
                    for observation in observations
                )
            )
        )
    return any(
        issue.code
        in {
            "unsupported_attribute_exclusion",
            "unverified_safety_requirement",
        }
        for issue in issues
    )


def _existing_clarification_issue(
    clarification: ClarificationCode,
    issues: Sequence[UnderstandingIssue],
) -> str | None:
    issue_codes = {
        ClarificationCode.TOPIC: {
            "ambiguous_category",
            "missing_category",
        },
        ClarificationCode.REFERENCE: {
            "ambiguous_reference",
            "ambiguous_candidate_reference",
            "ambiguous_image_reference",
        },
        ClarificationCode.BUDGET: {
            "invalid_budget",
            "unsupported_budget_format",
        },
        ClarificationCode.CONCERN: {
            "unsupported_attribute_exclusion",
            "unverified_safety_requirement",
        },
    }.get(clarification, set())
    return next(
        (
            issue.code
            for issue in issues
            if issue.code in issue_codes
        ),
        None,
    )


def _append_ignored_stale_signal(
    traces: list[SignalTrace],
    *,
    field: str,
    value: str,
) -> None:
    traces.append(
        SignalTrace(
            field=field,
            exact_value=None,
            semantic_value=value,
            resolution="ignored_stale",
        )
    )


def _merge_product_mentions(
    *,
    message: str,
    semantic_mentions: Sequence[SemanticProductMention],
    issues: list[UnderstandingIssue],
    traces: list[SignalTrace],
) -> list[ProductMentionDraft]:
    mentions: list[ProductMentionDraft] = []
    seen: set[tuple[int, int, str]] = set()
    for mention in semantic_mentions:
        key = (mention.start, mention.end, mention.text)
        if key in seen:
            continue
        seen.add(key)
        start = mention.start
        end = mention.end
        rebound = False
        if (
            mention.end > len(message)
            or message[mention.start:mention.end] != mention.text
        ):
            occurrences = _exact_substring_starts(
                message,
                mention.text,
            )
            if len(occurrences) != 1:
                _append_issue(
                    issues,
                    code="ambiguous_reference",
                    detail=(
                        "商品名称没有唯一绑定当前消息，"
                        "请重新确认商品全名。"
                    ),
                )
                traces.append(
                    SignalTrace(
                        field="product_mention",
                        exact_value=None,
                        semantic_value=mention.text,
                        resolution="clarify",
                    )
                )
                continue
            start = occurrences[0]
            end = start + len(mention.text)
            rebound = True
        mentions.append(
            ProductMentionDraft(
                text=mention.text,
                source_span=SourceSpan(
                    start=start,
                    end=end,
                ),
            )
        )
        traces.append(
            SignalTrace(
                field="product_mention",
                exact_value=mention.text,
                semantic_value=mention.text,
                resolution=(
                    "semantic_fills" if rebound else "agree"
                ),
            )
        )
    return mentions


def _exact_substring_starts(message: str, value: str) -> list[int]:
    starts: list[int] = []
    start = 0
    while True:
        index = message.find(value, start)
        if index < 0:
            return starts
        starts.append(index)
        start = index + 1


def _merge_preference_candidates(
    *,
    message: str,
    candidates: Sequence[SemanticPreferenceCandidate],
    constraints: list[ExactConstraintDraft],
    confirmations: Sequence[ExactRevisionConfirmation],
    issues: list[UnderstandingIssue],
    traces: list[SignalTrace],
) -> list[PreferenceDraft]:
    drafts: list[PreferenceDraft] = []
    for candidate in candidates:
        field = candidate.field.value
        source_bound = not (
            candidate.end > len(message)
            or message[candidate.start:candidate.end]
            != candidate.raw_text
        )
        rebound = False
        if not source_bound:
            occurrences = _exact_substring_starts(
                message,
                candidate.raw_text,
            )
            rebound = len(occurrences) == 1
        if not source_bound and not rebound:
            if candidate.strength is SemanticPreferenceStrength.PREFERENCE:
                _append_ignored_stale_signal(
                    traces,
                    field=f"preference_candidate.{field}",
                    value=candidate.raw_text,
                )
                continue
            _append_issue(
                issues,
                code="unverified_safety_requirement",
                detail=(
                    "安全硬门槛没有逐字绑定当前消息，"
                    "当前无法用强证据核实。"
                ),
            )
            traces.append(
                SignalTrace(
                    field=f"preference_candidate.{field}",
                    exact_value=None,
                    semantic_value=candidate.raw_text,
                    resolution="clarify",
                )
            )
            continue

        draft = preference_draft_for_candidate(candidate)
        if draft is None:
            _append_ignored_stale_signal(
                traces,
                field=f"preference_candidate.{field}",
                value=candidate.raw_text,
            )
            continue

        exact_duplicate = _equivalent_exact_preference(
            candidate=candidate,
            constraints=constraints,
            confirmations=confirmations,
        )
        if exact_duplicate is not None:
            traces.append(
                SignalTrace(
                    field=f"preference_candidate.{field}",
                    exact_value=exact_duplicate,
                    semantic_value=draft.value,
                    resolution="exact_wins",
                )
            )
            continue

        if candidate.field is SemanticPreferenceField.INGREDIENT_EXCLUSION:
            existing = next(
                (
                    item
                    for item in constraints
                    if isinstance(item, ExclusionDraft)
                    and item.value.casefold() == draft.value.casefold()
                ),
                None,
            )
            if candidate.strength is SemanticPreferenceStrength.PREFERENCE:
                if existing is None:
                    drafts.append(draft)
                traces.append(
                    SignalTrace(
                        field=f"preference_candidate.{field}",
                        exact_value=(
                            existing.value
                            if existing is not None
                            else (
                                candidate.raw_text
                                if rebound
                                else None
                            )
                        ),
                        semantic_value=draft.value,
                        resolution=(
                            "exact_wins"
                            if existing is not None
                            else "semantic_fills"
                        ),
                    )
                )
                continue
            if existing is None:
                constraints.append(ExclusionDraft(value=draft.value))
            traces.append(
                SignalTrace(
                    field=f"preference_candidate.{field}",
                    exact_value=existing.value if existing is not None else None,
                    semantic_value=draft.value,
                    resolution=(
                        "agree"
                        if existing is not None
                        else "semantic_fills"
                    ),
                )
            )
            continue

        if candidate.field is SemanticPreferenceField.INGREDIENT_PRESENCE:
            existing = next(
                (
                    item
                    for item in constraints
                    if isinstance(item, InclusionDraft)
                    and item.value.casefold() == draft.value.casefold()
                ),
                None,
            )
            if candidate.strength is SemanticPreferenceStrength.PREFERENCE:
                if existing is None:
                    drafts.append(draft)
                traces.append(
                    SignalTrace(
                        field=f"preference_candidate.{field}",
                        exact_value=(
                            existing.value
                            if existing is not None
                            else (
                                candidate.raw_text
                                if rebound
                                else None
                            )
                        ),
                        semantic_value=draft.value,
                        resolution=(
                            "exact_wins"
                            if existing is not None
                            else "semantic_fills"
                        ),
                    )
                )
                continue
            if existing is None:
                _append_issue(
                    issues,
                    code="unverified_safety_requirement",
                    detail=(
                        "绝对含有要求没有当前消息中的确定性措辞证明，"
                        "请明确是否为必须条件。"
                    ),
                )
                traces.append(
                    SignalTrace(
                        field=f"preference_candidate.{field}",
                        exact_value=None,
                        semantic_value=draft.value,
                        resolution="clarify",
                    )
                )
                continue
            traces.append(
                SignalTrace(
                    field=f"preference_candidate.{field}",
                    exact_value=existing.value,
                    semantic_value=draft.value,
                    resolution="agree",
                )
            )
            continue

        if candidate.strength is not SemanticPreferenceStrength.PREFERENCE:
            _append_issue(
                issues,
                code="unverified_safety_requirement",
                detail=(
                    "严重或强度不明的适用要求缺少可执行的强事实字段，"
                    "当前按 fail-closed 处理。"
                ),
            )
            traces.append(
                SignalTrace(
                    field=f"preference_candidate.{field}",
                    exact_value=None,
                    semantic_value=candidate.raw_text,
                    resolution="clarify",
                )
            )
            continue
        drafts.append(draft)
        traces.append(
            SignalTrace(
                field=f"preference_candidate.{field}",
                exact_value=candidate.raw_text if rebound else None,
                semantic_value=draft.value,
                resolution="semantic_fills",
            )
        )

    unique: list[PreferenceDraft] = []
    seen: set[tuple[str, str]] = set()
    for draft in drafts:
        key = (draft.field_key, draft.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(draft)
    return unique


def _equivalent_exact_preference(
    *,
    candidate: SemanticPreferenceCandidate,
    constraints: Sequence[ExactConstraintDraft],
    confirmations: Sequence[ExactRevisionConfirmation],
) -> str | None:
    exact_type: type[SkinDraft] | type[EfficacyDraft]
    target: ExactRevisionTarget
    if candidate.field is SemanticPreferenceField.SUITABLE_SKIN:
        exact_type = SkinDraft
        target = ExactRevisionTarget.SKIN
    elif candidate.field is SemanticPreferenceField.EFFICACY:
        exact_type = EfficacyDraft
        target = ExactRevisionTarget.EFFICACY
    else:
        return None
    if not any(
        proof.operation is ExactRevisionOperation.REVISE_CONSTRAINT
        and proof.target is target
        for proof in confirmations
    ):
        return None
    parsed, _ = parse_exact_constraints(candidate.raw_text)
    candidate_values = {
        item.value
        for item in parsed
        if isinstance(item, exact_type)
    }
    if len(candidate_values) != 1:
        return None
    candidate_value = next(iter(candidate_values))
    existing = next(
        (
            item
            for item in constraints
            if isinstance(item, exact_type)
            and item.value is candidate_value
        ),
        None,
    )
    return existing.value.value if existing is not None else None


def _has_matching_closed_operation_proof(
    *,
    message: str,
    constraints: Sequence[ExactConstraintDraft],
    confirmations: Sequence[ExactRevisionConfirmation],
) -> bool:
    if len(confirmations) != 1:
        return False
    proof = confirmations[0]
    span = proof.source_span
    if (
        span.end > len(message)
        or not message[span.start:span.end].strip()
        or not _proof_covers_complete_semantic_input(
            message=message,
            proof=proof,
        )
    ):
        return False

    exact_type_by_target = {
        ExactRevisionTarget.BUDGET: BudgetDraft,
        ExactRevisionTarget.CATEGORY: CategoryDraft,
        ExactRevisionTarget.SKIN: SkinDraft,
        ExactRevisionTarget.INGREDIENT_EXCLUSION: ExclusionDraft,
        ExactRevisionTarget.EFFICACY: EfficacyDraft,
    }
    exact_type = exact_type_by_target[proof.target]
    target_is_present = any(
        isinstance(item, exact_type)
        for item in constraints
    )
    if proof.operation is ExactRevisionOperation.REVISE_CONSTRAINT:
        return target_is_present
    return not target_is_present


def _proof_covers_complete_semantic_input(
    *,
    message: str,
    proof: ExactRevisionConfirmation,
) -> bool:
    span = proof.source_span
    outside = f"{message[:span.start]}{message[span.end:]}"
    return all(
        character.isspace()
        or unicodedata.category(character).startswith("P")
        for character in outside
    )


def _append_issue(
    issues: list[UnderstandingIssue],
    *,
    code: str,
    detail: str,
) -> None:
    if any(
        item.code == code and item.detail == detail
        for item in issues
    ):
        return
    issues.append(
        UnderstandingIssue(code=code, detail=detail)
    )


def _understanding(
    *,
    goal: UnderstandingGoal,
    topic: TopicCode | None,
    constraints: list[ExactConstraintDraft],
    issues: list[UnderstandingIssue],
    signal_trace: list[SignalTrace],
    confidence: float,
    observations: list[str] | None = None,
    semantic_proposals: list[str] | None = None,
    references: list[ReferenceDraft] | None = None,
    product_mentions: list[ProductMentionDraft] | None = None,
    preference_drafts: list[PreferenceDraft] | None = None,
    question_meaning: str | None = None,
    safety_sensitive: bool = False,
) -> StructuredUnderstanding:
    exact_references = [
        item
        for item in constraints
        if isinstance(item, ReferenceDraft)
    ]
    return StructuredUnderstanding(
        goal=goal,
        topic=topic,
        observations=[] if observations is None else observations,
        exact_constraints=constraints,
        preference_drafts=(
            []
            if preference_drafts is None
            else preference_drafts
        ),
        semantic_proposals=(
            []
            if semantic_proposals is None
            else semantic_proposals
        ),
        signal_trace=signal_trace,
        references=(
            exact_references
            if references is None
            else references
        ),
        product_mentions=(
            []
            if product_mentions is None
            else product_mentions
        ),
        image_references=[],
        uncertainties=issues,
        confidence=confidence,
        question_meaning=question_meaning,
        safety_sensitive=safety_sensitive,
    )


def _project_observation(
    observation: SemanticObservation,
) -> str:
    qualifier = (
        observation.qualifier.value
        if observation.qualifier is not None
        else "none"
    )
    present = "true" if observation.present else "false"
    return (
        f"observation={observation.code.value};"
        f"present={present};qualifier={qualifier}"
    )


def _merge_references(
    *,
    message: str,
    constraints: Sequence[ExactConstraintDraft],
    semantic_references: Sequence[SemanticReference],
    revision_confirmations: Sequence[ExactRevisionConfirmation],
    issues: list[UnderstandingIssue],
    traces: list[SignalTrace],
    exact_ambiguities: dict[str, list[int | None]],
    context: SemanticContext | None,
) -> list[ReferenceDraft]:
    exact_references = [
        item
        for item in constraints
        if isinstance(item, ReferenceDraft)
    ]
    if (
        revision_confirmations
        and not any(
            item.kind == "previous_constraint"
            for item in exact_references
        )
        and not any(
            item.kind == "previous_constraint"
            for item in semantic_references
        )
    ):
        proof = min(
            revision_confirmations,
            key=lambda item: (
                item.source_span.start,
                item.source_span.end,
                item.target.value,
            ),
        )
        exact_references.append(
            ReferenceDraft(
                kind="previous_constraint",
                source_span=proof.source_span,
            )
        )
    exact_by_kind = {
        reference.kind: reference
        for reference in exact_references
    }
    semantic_by_kind: dict[str, list[ReferenceDraft]] = {}
    for semantic in semantic_references:
        if semantic.kind in exact_by_kind:
            semantic_by_kind.setdefault(semantic.kind, []).append(
                ReferenceDraft(
                    kind=semantic.kind,
                    ordinal=semantic.ordinal,
                    source_span=None,
                )
            )
            continue
        grounded = _ground_semantic_reference(
            message=message,
            reference=semantic,
            context=context,
            issues=issues,
            traces=traces,
        )
        if grounded is not None:
            semantic_by_kind.setdefault(semantic.kind, []).append(
                grounded
            )

    ordered_kinds = list(exact_by_kind)
    ordered_kinds.extend(
        kind
        for kind in exact_ambiguities
        if kind not in exact_by_kind
    )
    ordered_kinds.extend(
        kind
        for kind in semantic_by_kind
        if kind not in exact_by_kind
        and kind not in exact_ambiguities
    )
    references: list[ReferenceDraft] = []
    for kind in ordered_kinds:
        exact = exact_by_kind.get(kind)
        semantic_values = list(
            dict.fromkeys(
                reference.ordinal
                for reference in semantic_by_kind.get(kind, ())
            )
        )
        if kind in exact_ambiguities:
            traces.append(
                SignalTrace(
                    field=f"reference.{kind}",
                    exact_value=_join_reference_values(
                        exact_ambiguities[kind]
                    ),
                    semantic_value=_join_reference_values(
                        semantic_values
                    ),
                    resolution="clarify",
                )
            )
            continue
        if exact is not None:
            context_issue = _reference_context_issue(
                exact,
                context=context,
            )
            if context_issue is not None:
                issue_code, detail = context_issue
                _append_issue(
                    issues,
                    code=issue_code,
                    detail=detail,
                )
                traces.append(
                    SignalTrace(
                        field=f"reference.{kind}",
                        exact_value=_reference_value(exact.ordinal),
                        semantic_value=_join_reference_values(
                            semantic_values
                        ),
                        resolution="clarify",
                    )
                )
                continue
            references.append(exact)
            if not semantic_values:
                continue
            resolution = (
                "agree"
                if semantic_values == [exact.ordinal]
                else "exact_wins"
            )
            traces.append(
                SignalTrace(
                    field=f"reference.{kind}",
                    exact_value=_reference_value(exact.ordinal),
                    semantic_value=_join_reference_values(
                        semantic_values
                    ),
                    resolution=resolution,
                )
            )
            continue
        if len(semantic_values) != 1:
            _append_issue(
                issues,
                code="ambiguous_reference",
                detail=(
                    f"语义信号对 {kind} 给出多个不同指代，"
                    "请只确认一个序号。"
                ),
            )
            traces.append(
                SignalTrace(
                    field=f"reference.{kind}",
                    exact_value=None,
                    semantic_value=_join_reference_values(
                        semantic_values
                    ),
                    resolution="clarify",
                )
            )
            continue
        ordinal = semantic_values[0]
        semantic_reference = next(
            reference
            for reference in semantic_by_kind[kind]
            if reference.ordinal == ordinal
        )
        references.append(semantic_reference)
        traces.append(
            SignalTrace(
                field=f"reference.{kind}",
                exact_value=None,
                semantic_value=_reference_value(ordinal),
                resolution="semantic_fills",
            )
        )
    return references


def _ground_semantic_reference(
    *,
    message: str,
    reference: SemanticReference,
    context: SemanticContext | None,
    issues: list[UnderstandingIssue],
    traces: list[SignalTrace],
) -> ReferenceDraft | None:
    start = reference.start
    end = reference.end
    rebound = False
    if (
        end > len(message)
        or message[start:end] != reference.raw_text
    ):
        occurrences = _exact_substring_starts(
            message,
            reference.raw_text,
        )
        if len(occurrences) != 1:
            _append_issue(
                issues,
                code="ambiguous_reference",
                detail=(
                    "语义指代没有唯一绑定当前消息，"
                    "请重新确认所指对象。"
                ),
            )
            traces.append(
                SignalTrace(
                    field=f"reference.{reference.kind}",
                    exact_value=None,
                    semantic_value=_reference_value(reference.ordinal),
                    resolution="clarify",
                )
            )
            return None
        start = occurrences[0]
        end = start + len(reference.raw_text)
        rebound = True

    draft = ReferenceDraft(
        kind=reference.kind,
        ordinal=reference.ordinal,
        source_span=SourceSpan(start=start, end=end),
    )
    context_issue = _reference_context_issue(
        draft,
        context=context,
    )
    if context_issue is not None:
        issue_code, detail = context_issue
        _append_issue(
            issues,
            code=issue_code,
            detail=detail,
        )
        traces.append(
            SignalTrace(
                field=f"reference.{reference.kind}",
                exact_value=None,
                semantic_value=_reference_value(reference.ordinal),
                resolution="clarify",
            )
        )
        return None

    if rebound:
        traces.append(
            SignalTrace(
                field=f"reference_span.{reference.kind}",
                exact_value=reference.raw_text,
                semantic_value=reference.raw_text,
                resolution="semantic_fills",
            )
        )
    return draft


def _reference_context_issue(
    reference: ReferenceDraft,
    *,
    context: SemanticContext | None,
) -> tuple[str, str] | None:
    if context is None:
        return None
    if reference.kind == "candidate_ordinal":
        if (
            reference.ordinal is None
            or reference.ordinal > context.visible_candidate_count
        ):
            return (
                "ambiguous_candidate_reference",
                "你说的商品序号不在当前展示范围里，请重新确认。",
            )
        return None
    if reference.kind == "image_ordinal":
        if (
            reference.ordinal is None
            or reference.ordinal > context.image_count
        ):
            return (
                "ambiguous_image_reference",
                "所指图片序号不在当前图片中，请重新确认。",
            )
        return None
    if reference.kind == "current_item":
        if context.focused_candidate_ordinal is None:
            return (
                "ambiguous_reference",
                "目前没有唯一对应的商品，请直接说商品名或序号。",
            )
        return None
    if reference.kind == "current_batch":
        if context.visible_candidate_count == 0:
            return (
                "ambiguous_reference",
                "目前没有前面那组商品可以继续查看，请先发起一次推荐。",
            )
        return None
    if reference.kind == "current_topic":
        if context.active_topic is None:
            return (
                "ambiguous_reference",
                "当前没有可引用的商品品类，请明确目标品类。",
            )
        return None
    if (
        reference.kind == "previous_constraint"
        and not context.active_constraint_kinds
    ):
        return (
            "ambiguous_reference",
            "当前没有可引用的既有条件，请明确要调整的条件。",
        )
    return None


def _normalize_exact_references(
    constraints: Sequence[ExactConstraintDraft],
) -> tuple[
    list[ExactConstraintDraft],
    dict[str, list[int | None]],
]:
    references_by_kind: dict[str, list[ReferenceDraft]] = {}
    for item in constraints:
        if isinstance(item, ReferenceDraft):
            references_by_kind.setdefault(item.kind, []).append(item)

    ordinals_by_kind = {
        kind: list(
            dict.fromkeys(reference.ordinal for reference in references)
        )
        for kind, references in references_by_kind.items()
    }
    ambiguities = {
        kind: ordinals
        for kind, ordinals in ordinals_by_kind.items()
        if len(ordinals) > 1
    }
    normalized: list[ExactConstraintDraft] = []
    emitted_reference_kinds: set[str] = set()
    for item in constraints:
        if not isinstance(item, ReferenceDraft):
            normalized.append(item)
            continue
        if item.kind in emitted_reference_kinds:
            continue
        emitted_reference_kinds.add(item.kind)
        if item.kind not in ambiguities:
            normalized.append(item)
    return normalized, ambiguities


def _exact_reference_ambiguity_traces(
    ambiguities: dict[str, list[int | None]],
    *,
    semantic_references: Sequence[SemanticReference],
) -> list[SignalTrace]:
    semantic_by_kind: dict[str, list[int | None]] = {}
    for reference in semantic_references:
        values = semantic_by_kind.setdefault(reference.kind, [])
        if reference.ordinal not in values:
            values.append(reference.ordinal)
    return [
        SignalTrace(
            field=f"reference.{kind}",
            exact_value=_join_reference_values(ordinals),
            semantic_value=_join_reference_values(
                semantic_by_kind.get(kind, ())
            ),
            resolution="clarify",
        )
        for kind, ordinals in ambiguities.items()
    ]


def _revision_target_traces(
    issues: Sequence[UnderstandingIssue],
    *,
    semantic_topic: TopicCode | None,
) -> list[SignalTrace]:
    return [
        SignalTrace(
            field="revision_target",
            exact_value=_REVISION_TARGET_VALUE_BY_ISSUE[issue.code],
            semantic_value=_topic_value(semantic_topic),
            resolution="clarify",
        )
        for issue in issues
        if issue.code in _REVISION_TARGET_VALUE_BY_ISSUE
    ]


def _reference_value(ordinal: int | None) -> str:
    return "current" if ordinal is None else str(ordinal)


def _join_reference_values(
    ordinals: Sequence[int | None],
) -> str | None:
    return ",".join(_reference_value(value) for value in ordinals) or None


def _topic_value(topic: TopicCode | None) -> str | None:
    return topic.value if topic is not None else None


def _join_topics(topics: Sequence[TopicCode]) -> str | None:
    return ",".join(topic.value for topic in topics) or None


def _stable_confidence(value: float) -> str:
    return format(value, ".6g")


def _constraint_trace_value(
    constraint: ExactConstraintDraft | None,
) -> str | None:
    if constraint is None:
        return None
    if isinstance(constraint, BudgetDraft):
        minimum = (
            str(constraint.minimum)
            if constraint.minimum is not None
            else ""
        )
        maximum = (
            str(constraint.maximum)
            if constraint.maximum is not None
            else ""
        )
        return f"{minimum}:{maximum}"
    if isinstance(
        constraint,
        (CategoryDraft, SkinDraft, EfficacyDraft),
    ):
        return constraint.value.value
    if isinstance(constraint, ExclusionDraft):
        return constraint.value
    if isinstance(constraint, InclusionDraft):
        return constraint.value
    if isinstance(constraint, ReferenceDraft):
        return (
            f"{constraint.kind}:{constraint.ordinal}"
            if constraint.ordinal is not None
            else constraint.kind
        )
    raise TypeError("unsupported constraint trace value")


__all__ = ["merge_context_signals", "merge_intent_signals"]
