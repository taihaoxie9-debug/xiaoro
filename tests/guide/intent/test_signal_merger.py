from __future__ import annotations

from decimal import Decimal

import pytest

from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.intent.task_planning import plan_task as _plan_task
from app.guide.understanding import exact_parsing
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    EfficacyDraft,
    EfficacyTarget,
    ExactRevisionConfirmation,
    ExactRevisionOperation,
    ExactRevisionTarget,
    ExclusionDraft,
    ReferenceDraft,
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
    parse_hard_category_exclusions,
)
from app.guide.understanding.semantic_contracts import (
    ActiveConstraintKind,
    ClarificationCode,
    ConfirmedProfileField,
    ConcernCode,
    ObservationCode,
    ObservationQualifier,
    SemanticContext,
    SemanticIntentProposal,
    SemanticLaneDisposition,
    SemanticNumberCandidate,
    SemanticObservation,
    SemanticPreferenceCandidate,
    SemanticPreferenceField,
    SemanticPreferenceStrength,
    SemanticProductMention,
    SemanticReference,
)


def _proposal(
    *,
    goal: UnderstandingGoal = UnderstandingGoal.RECOMMENDATION,
    topic: TopicCode | None = TopicCode.FRAGRANCE,
    confidence: float = 0.95,
    concerns: tuple[ConcernCode, ...] = (),
    observations: tuple[SemanticObservation, ...] = (),
    references: tuple[SemanticReference, ...] = (),
    product_mentions: tuple[SemanticProductMention, ...] = (),
    number_candidates: tuple[SemanticNumberCandidate, ...] = (),
    preference_candidates: tuple[SemanticPreferenceCandidate, ...] = (),
    clarification_hint: ClarificationCode | None = None,
    question_meaning: str | None = None,
    safety_sensitive: bool = False,
) -> SemanticIntentProposal:
    return SemanticIntentProposal(
        goal=goal,
        topic=topic,
        concerns=concerns,
        observations=observations,
        references=references,
        product_mentions=product_mentions,
        number_candidates=number_candidates,
        preference_candidates=preference_candidates,
        confidence=confidence,
        clarification_hint=clarification_hint,
        question_meaning=question_meaning,
        safety_sensitive=safety_sensitive,
    )


def _merge_message(
    message: str,
    *,
    semantic: SemanticIntentProposal | None,
):
    constraints, issues = parse_exact_constraints(message)
    return merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        semantic=semantic,
    )


_POLARITY_CATEGORY_CASES = (
    ("香水", TopicCode.FRAGRANCE),
    ("防晒", TopicCode.SUNSCREEN),
)
_LEXICAL_POSITIVE_PREFIXES = (
    "无比",
    "毫无疑问",
    "无论如何都",
    "忍不住",
    "不由得",
    "不禁",
)
_POSITIVE_SELECTION_PREDICATES = ("想买", "想要")
_DIRECT_NEGATIVE_PREDICATES = ("不想买", "不要", "不考虑")
_NOMINAL_NEGATIVE_PREDICATES = ("购买", "入手")
_HEDGED_NEGATION_OPERATORS = ("不太", "没有特别", "并非真的")
_SELECTION_ATTRIBUTES = ("高端", "木质调")
_DOUBLE_NEGATION_OUTERS = ("不是", "并非")
_DOUBLE_NEGATION_PREDICATES = ("不要", "不需要", "不考虑")
_REPORTING_WRAPPERS = ("没说", "不能说")


def test_merger_preserves_unrestricted_product_question_meaning() -> None:
    message = "这面膜贴着会不会老往下掉？"
    understanding = _merge_message(
        message,
        semantic=_proposal(
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.SKINCARE,
            question_meaning="询问面膜是否服帖、是否容易滑落",
            safety_sensitive=False,
        ),
    )

    assert understanding.question_meaning == (
        "询问面膜是否服帖、是否容易滑落"
    )
    assert not understanding.safety_sensitive
_EVENT_SEPARATORS = ("，", "。", "；")
_FINAL_NEGATIVE_PREDICATES = ("不想买了", "不考虑了")
_FINAL_POSITIVE_PREDICATES = ("明确想买了", "明确想要了")
_REVISION_MARKERS = (
    "后来",
    "最后",
    "最终",
    "转而",
    "转头",
    "相反",
    "而是",
)
_REVISION_ACTIONS = ("改买", "改选", "改要", "转选", "换成")
_SELECTION_ACTION_CASES = (
    ("买", "buy"),
    ("购买", "buy"),
    ("入手", "buy"),
    ("选择", "select"),
    ("挑选", "select"),
    ("考虑", "consider"),
    ("要", "need"),
    ("需要", "need"),
    ("推荐", "recommend"),
)
_ORDINARY_POSITIVE_ACTIONS = tuple(
    action
    for action, _ in _SELECTION_ACTION_CASES
)
_REVISION_SEPARATORS = (
    "，",
    ",",
    "。",
    ".",
    "！",
    "!",
    "？",
    "?",
    "；",
    ";",
    "…",
    "……",
    "、",
    " ",
    "？！……、",
)
_WITHDRAWAL_SEPARATORS = (
    *_EVENT_SEPARATORS,
    "…",
    "……",
    "、",
    " ",
    "……、？！",
)


def _plan_with_explicit_test_outcome(
    understanding: StructuredUnderstanding,
):
    if (
        understanding.goal
        in {
            UnderstandingGoal.RECOMMENDATION,
            UnderstandingGoal.IMAGE_SIMILARITY,
        }
        and understanding.recommendation_mode is None
    ):
        payload = understanding.model_dump(mode="python")
        payload.update(
            recommendation_mode="explore",
            recommendation_mode_basis=(
                "similar_alternatives"
                if understanding.goal
                is UnderstandingGoal.IMAGE_SIMILARITY
                else "broad_exploration"
            ),
            recommendation_count=3,
        )
        understanding = StructuredUnderstanding.model_validate(
            payload,
            strict=True,
        )
    return _plan_task(understanding)


def _selection_pipeline_record(
    message: str,
    topic: TopicCode,
    *,
    semantic_references: tuple[SemanticReference, ...] = (),
) -> dict[str, object]:
    constraints, issues = parse_exact_constraints(message)
    semantic = _proposal(
        topic=topic,
        references=semantic_references,
    )
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        semantic=semantic,
    )
    task = _plan_with_explicit_test_outcome(merged)

    return {
        "exact": {
            "categories": [
                item.value.value
                for item in constraints
                if isinstance(item, CategoryDraft)
            ],
            "exclusions": [
                item.value
                for item in constraints
                if isinstance(item, ExclusionDraft)
            ],
            "issues": [item.code for item in issues],
            "references": [
                item.model_dump(mode="json")
                for item in constraints
                if item.kind == "candidate_ordinal"
            ],
        },
        "semantic": {
            "goal": semantic.goal.value,
            "topic": semantic.topic.value if semantic.topic else None,
            "confidence": semantic.confidence,
        },
        "merger": {
            "topic": (
                merged.topic.value
                if merged.topic is not None
                else None
            ),
            "issues": [item.code for item in merged.uncertainties],
            "trace": [
                item.model_dump(mode="json")
                for item in merged.signal_trace
            ],
            "references": [
                item.model_dump(mode="json")
                for item in getattr(merged, "references", ())
            ],
        },
        "TaskPlan": {
            "mode": task.mode,
            "categories": [
                item.value.value
                for item in task.constraints
                if item.kind == "category"
            ],
            "exclusions": [
                item.value
                for item in task.constraints
                if item.kind == "exclude"
            ],
            "references": [
                item.model_dump(mode="json")
                for item in getattr(task, "references", ())
            ],
        },
        "downstream": (
            "canonical_retrieval"
            if task.required_evidence
            else "blocked_by_clarification"
        ),
        "RetrievalResult": {
            "disposition": (
                "eligible"
                if task.required_evidence
                else "not_invoked"
            ),
        },
        "DecisionResult": {
            "disposition": (
                "pending_retrieval"
                if task.required_evidence
                else "not_invoked"
            ),
        },
        "ResponsePlan/SSE": {
            "disposition": (
                "pending_evidence"
                if task.required_evidence
                else "typed_clarification"
            ),
        },
        "state": (
            "eligible_after_visible_cards"
            if task.required_evidence
            else "unchanged"
        ),
    }


def _assert_selection_outcome(
    record: dict[str, object],
    *,
    topic: TopicCode,
    outcome: str,
) -> None:
    exact = record["exact"]
    merger = record["merger"]
    task = record["TaskPlan"]
    assert isinstance(exact, dict)
    assert isinstance(merger, dict)
    assert isinstance(task, dict)

    if outcome == "positive":
        assert exact == {
            "categories": [topic.value],
            "exclusions": [],
            "issues": [],
            "references": [],
        }
        assert merger["topic"] == topic.value
        assert merger["issues"] == []
        assert task == {
            "mode": "recommend",
            "categories": [topic.value],
            "exclusions": [],
            "references": [],
        }
        assert record["downstream"] == "canonical_retrieval"
        assert record["state"] == "eligible_after_visible_cards"
        return

    assert exact["categories"] == []
    assert exact["exclusions"] == []
    assert merger["topic"] is None
    assert task["mode"] == "clarify"
    assert task["categories"] == []
    assert task["exclusions"] == []
    assert record["downstream"] == "blocked_by_clarification"
    assert record["state"] == "unchanged"
    if outcome == "negative":
        assert exact["issues"] == []
        assert merger["trace"][0]["resolution"] == "exact_wins"
        return
    if outcome == "unknown":
        assert exact["issues"] == ["ambiguous_category"]
        assert "ambiguous_category" in merger["issues"]
        assert merger["trace"][0]["resolution"] == "clarify"
        return
    raise AssertionError(f"unsupported test outcome: {outcome}")


def _assert_full_chain_disposition(
    record: dict[str, object],
    *,
    recommend: bool,
) -> None:
    if recommend:
        assert record["RetrievalResult"] == {
            "disposition": "eligible",
        }
        assert record["DecisionResult"] == {
            "disposition": "pending_retrieval",
        }
        assert record["ResponsePlan/SSE"] == {
            "disposition": "pending_evidence",
        }
        assert record["state"] == "eligible_after_visible_cards"
        return
    assert record["RetrievalResult"] == {
        "disposition": "not_invoked",
    }
    assert record["DecisionResult"] == {
        "disposition": "not_invoked",
    }
    assert record["ResponsePlan/SSE"] == {
        "disposition": "typed_clarification",
    }
    assert record["state"] == "unchanged"


@pytest.mark.parametrize(
    (
        "kind",
        "exact_ordinal",
        "semantic_ordinals",
        "expected_ordinals",
        "resolution",
        "expected_mode",
    ),
    (
        (
            "candidate_ordinal",
            2,
            (3,),
            [2],
            "exact_wins",
            "recommend",
        ),
        (
            "image_ordinal",
            2,
            (3,),
            [2],
            "exact_wins",
            "recommend",
        ),
        (
            "candidate_ordinal",
            2,
            (2,),
            [2],
            "agree",
            "recommend",
        ),
        (
            "image_ordinal",
            2,
            (2,),
            [2],
            "agree",
            "recommend",
        ),
        (
            "candidate_ordinal",
            None,
            (3,),
            [3],
            "semantic_fills",
            "recommend",
        ),
        (
            "image_ordinal",
            None,
            (3,),
            [3],
            "semantic_fills",
            "recommend",
        ),
        (
            "candidate_ordinal",
            None,
            (2, 3),
            [],
            "clarify",
            "clarify",
        ),
        (
            "image_ordinal",
            None,
            (2, 3),
            [],
            "clarify",
            "clarify",
        ),
    ),
)
def test_reference_kind_has_one_authority_across_full_pipeline(
    kind: str,
    exact_ordinal: int | None,
    semantic_ordinals: tuple[int, ...],
    expected_ordinals: list[int],
    resolution: str,
    expected_mode: str,
) -> None:
    message = "第二款香水" if kind == "candidate_ordinal" else "第二张香水"
    exact = [CategoryDraft(value=TopicCode.FRAGRANCE)]
    if exact_ordinal is not None:
        exact.append(
            ReferenceDraft(
                kind=kind,
                ordinal=exact_ordinal,
                source_span=SourceSpan(start=0, end=3),
            )
        )
    semantic = _proposal(
        topic=TopicCode.FRAGRANCE,
        references=tuple(
            SemanticReference(
                kind=kind,
                ordinal=ordinal,
                raw_text=message[:3],
                start=0,
                end=3,
            )
            for ordinal in semantic_ordinals
        ),
    )

    merged = merge_intent_signals(
        message=message,
        exact_constraints=exact,
        exact_issues=[],
        semantic=semantic,
    )
    task = _plan_with_explicit_test_outcome(merged)
    merger_ordinals = [
        reference.ordinal
        for reference in merged.references
        if reference.kind == kind
    ]
    task_ordinals = [
        reference.ordinal
        for reference in task.references
        if reference.kind == kind
    ]
    reference_traces = [
        trace
        for trace in merged.signal_trace
        if trace.field == f"reference.{kind}"
    ]

    assert merger_ordinals == expected_ordinals
    assert task_ordinals == expected_ordinals
    assert len(set(merger_ordinals)) == len(merger_ordinals)
    assert [trace.resolution for trace in reference_traces] == [
        resolution
    ]
    assert task.mode == expected_mode
    assert (task.required_evidence != []) is (
        expected_mode == "recommend"
    )
    assert not (
        2 in task_ordinals
        and 3 in task_ordinals
    )


@pytest.mark.parametrize(
    ("kind", "message", "issue_code"),
    (
        (
            "candidate_ordinal",
            "第二款和第三款香水",
            "ambiguous_candidate_reference",
        ),
        (
            "image_ordinal",
            "第二张和第三张香水",
            "ambiguous_image_reference",
        ),
    ),
)
def test_distinct_exact_ordinals_of_one_kind_remain_explicit(
    kind: str,
    message: str,
    issue_code: str,
) -> None:
    constraints, issues = parse_exact_constraints(message)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        semantic=_proposal(
            topic=TopicCode.FRAGRANCE,
            references=(
                SemanticReference(
                    kind=kind,
                    ordinal=2,
                    raw_text=message[:3],
                    start=0,
                    end=3,
                ),
            ),
        ),
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert [
        item.ordinal
        for item in constraints
        if isinstance(item, ReferenceDraft) and item.kind == kind
    ] == [2, 3]
    assert issue_code not in {item.code for item in issues}
    assert [
        item.ordinal
        for item in merged.references
        if item.kind == kind
    ] == [2, 3]
    assert issue_code not in {
        item.code
        for item in merged.uncertainties
    }
    assert [
        trace.model_dump(mode="json")
        for trace in merged.signal_trace
        if trace.field == f"reference.{kind}"
    ] == [
        {
            "field": f"reference.{kind}",
            "exact_value": "2,3",
            "semantic_value": "2",
            "resolution": "exact_wins",
        }
    ]
    assert [
        item.ordinal
        for item in task.references
        if item.kind == kind
    ] == [2, 3]
    assert task.mode == "recommend"
    assert task.required_evidence == ["canonical_product"]


@pytest.mark.parametrize(
    ("kind", "message"),
    (
        ("candidate_ordinal", "第二款和第二款香水"),
        ("image_ordinal", "第二张和第二张香水"),
    ),
)
def test_repeated_identical_exact_ordinal_is_one_reference(
    kind: str,
    message: str,
) -> None:
    constraints, issues = parse_exact_constraints(message)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        semantic=_proposal(
            topic=TopicCode.FRAGRANCE,
            references=(
                SemanticReference(
                    kind=kind,
                    ordinal=2,
                    raw_text=message[:3],
                    start=0,
                    end=3,
                ),
                SemanticReference(
                    kind=kind,
                    ordinal=2,
                    raw_text=message[4:7],
                    start=4,
                    end=7,
                ),
            ),
        ),
    )
    task = _plan_with_explicit_test_outcome(merged)
    exact_references = [
        item
        for item in constraints
        if isinstance(item, ReferenceDraft) and item.kind == kind
    ]

    assert len(exact_references) == 1
    assert exact_references[0].ordinal == 2
    assert issues == []
    assert [
        (item.kind, item.ordinal)
        for item in merged.references
    ] == [(kind, 2)]
    assert [
        (item.kind, item.ordinal)
        for item in task.references
    ] == [(kind, 2)]
    assert task.mode == "recommend"
    assert task.required_evidence == ["canonical_product"]


def test_exact_candidate_and_image_ordinals_coexist_by_kind() -> None:
    message = "第二款和第三张香水"
    constraints, issues = parse_exact_constraints(message)
    semantic_references = (
        SemanticReference(
            kind="candidate_ordinal",
            ordinal=2,
            raw_text="第二款",
            start=0,
            end=3,
        ),
        SemanticReference(
            kind="image_ordinal",
            ordinal=3,
            raw_text="第三张",
            start=4,
            end=7,
        ),
    )
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        semantic=_proposal(
            topic=TopicCode.FRAGRANCE,
            references=semantic_references,
        ),
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert issues == []
    assert [
        (item.kind, item.ordinal)
        for item in constraints
        if isinstance(item, ReferenceDraft)
    ] == [
        ("candidate_ordinal", 2),
        ("image_ordinal", 3),
    ]
    assert [
        (item.kind, item.ordinal)
        for item in merged.references
    ] == [
        ("candidate_ordinal", 2),
        ("image_ordinal", 3),
    ]
    assert [
        (item.kind, item.ordinal)
        for item in task.references
    ] == [
        ("candidate_ordinal", 2),
        ("image_ordinal", 3),
    ]
    assert task.mode == "recommend"


@pytest.mark.parametrize(
    ("kind", "issue_code"),
    (
        (
            "candidate_ordinal",
            "ambiguous_candidate_reference",
        ),
        (
            "image_ordinal",
            "ambiguous_image_reference",
        ),
    ),
)
def test_merger_preserves_distinct_typed_exact_references(
    kind: str,
    issue_code: str,
) -> None:
    message = (
        "第二款和第三款香水"
        if kind == "candidate_ordinal"
        else "第二张和第三张香水"
    )
    exact = [
        CategoryDraft(value=TopicCode.FRAGRANCE),
        ReferenceDraft(
            kind=kind,
            ordinal=2,
            source_span=SourceSpan(start=0, end=3),
        ),
        ReferenceDraft(
            kind=kind,
            ordinal=3,
            source_span=SourceSpan(start=4, end=7),
        ),
    ]

    merged = merge_intent_signals(
        message=message,
        exact_constraints=exact,
        exact_issues=[],
        semantic=_proposal(
            topic=TopicCode.FRAGRANCE,
            references=(
                SemanticReference(
                    kind=kind,
                    ordinal=2,
                    raw_text="第二款" if kind == "candidate_ordinal" else "第二张",
                    start=0,
                    end=3,
                ),
            ),
        ),
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert [
        item.ordinal
        for item in merged.exact_constraints
        if isinstance(item, ReferenceDraft) and item.kind == kind
    ] == [2, 3]
    assert [
        item.ordinal
        for item in merged.references
        if item.kind == kind
    ] == [2, 3]
    assert issue_code not in {
        item.code
        for item in merged.uncertainties
    }
    assert [
        item.ordinal
        for item in task.references
        if item.kind == kind
    ] == [2, 3]
    assert task.mode == "recommend"
    assert task.required_evidence == ["canonical_product"]


@pytest.mark.parametrize("ingredient", ("酒精", "香精"))
def test_nested_ingredient_does_not_drop_negative_selection_event(
    ingredient: str,
) -> None:
    message = f"不选择{ingredient}香水"
    record = _selection_pipeline_record(
        message,
        TopicCode.FRAGRANCE,
    )
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    merger = record["merger"]
    task = record["TaskPlan"]

    assert isinstance(exact, dict)
    assert isinstance(merger, dict)
    assert isinstance(task, dict)
    assert len(events) == 1
    assert events[0].action.value == "select"
    assert events[0].operator.value == "negated"
    assert events[0].target_topic is TopicCode.FRAGRANCE
    assert exact == {
        "categories": [],
        "exclusions": [ingredient],
        "issues": [],
        "references": [],
    }
    assert parse_hard_category_exclusions(message) == (
        TopicCode.FRAGRANCE,
    )
    assert merger["topic"] is None
    assert merger["trace"][0]["resolution"] == "exact_wins"
    assert task["mode"] == "clarify"
    assert task["exclusions"] == [ingredient]
    _assert_full_chain_disposition(record, recommend=False)


@pytest.mark.parametrize(
    (
        "message",
        "expected_topic",
        "revision_markers",
        "revision_actions",
        "expected_mode",
    ),
    (
        (
            "先选择香水，最后改选洁面",
            TopicCode.CLEANSER,
            ["最后"],
            ["改选"],
            "recommend",
        ),
        (
            "先选择洁面。后来转选香水",
            TopicCode.FRAGRANCE,
            ["后来"],
            ["转选"],
            "recommend",
        ),
        (
            "先选择香水；最终选择洁面",
            TopicCode.CLEANSER,
            ["最终"],
            [],
            "recommend",
        ),
        (
            "先选择洁面,改选香水",
            TopicCode.FRAGRANCE,
            [],
            ["改选"],
            "recommend",
        ),
        (
            "香水和洁面",
            None,
            [],
            [],
            "clarify",
        ),
    ),
)
def test_typed_revision_replaces_only_prior_positive_topic(
    message: str,
    expected_topic: TopicCode | None,
    revision_markers: list[str],
    revision_actions: list[str],
    expected_mode: str,
) -> None:
    semantic_topic = expected_topic or TopicCode.FRAGRANCE
    record = _selection_pipeline_record(message, semantic_topic)
    tokens = exact_parsing._lex_exact_tokens(message)
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    task = record["TaskPlan"]

    assert isinstance(exact, dict)
    assert isinstance(task, dict)
    assert [
        message[token.source_span.start:token.source_span.end]
        for token in tokens
        if token.kind.value == "revision"
    ] == revision_markers
    assert [
        message[token.source_span.start:token.source_span.end]
        for token in tokens
        if (
            token.kind.value == "selection_action"
            and token.is_revision
        )
    ] == revision_actions
    assert [
        event.target_topic
        for event in events
        if event.is_revision
    ] == (
        []
        if expected_topic is None
        else [expected_topic]
    )
    assert exact["categories"] == (
        []
        if expected_topic is None
        else [expected_topic.value]
    )
    assert task["mode"] == expected_mode
    _assert_full_chain_disposition(
        record,
        recommend=expected_mode == "recommend",
    )


@pytest.mark.parametrize("separator", ("，", "。", "；", ","))
@pytest.mark.parametrize("marker", _REVISION_MARKERS)
@pytest.mark.parametrize("action", _REVISION_ACTIONS)
def test_positive_revision_without_explicit_target_fails_closed(
    separator: str,
    marker: str,
    action: str,
) -> None:
    message = f"先选择香水{separator}{marker}{action}"
    record = _selection_pipeline_record(
        message,
        TopicCode.FRAGRANCE,
    )
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    merger = record["merger"]
    task = record["TaskPlan"]

    assert isinstance(exact, dict)
    assert isinstance(merger, dict)
    assert isinstance(task, dict)
    assert [
        event
        for event in events
        if event.is_revision
    ] == []
    assert exact["categories"] == []
    assert exact["issues"] == ["missing_revision_target"]
    assert merger["topic"] is None
    assert "missing_revision_target" in merger["issues"]
    assert [
        trace
        for trace in merger["trace"]
        if trace["field"] == "revision_target"
    ] == [
        {
            "field": "revision_target",
            "exact_value": "missing",
            "semantic_value": TopicCode.FRAGRANCE.value,
            "resolution": "clarify",
        }
    ]
    assert task["mode"] == "clarify"
    assert task["categories"] == []
    assert task["references"] == []
    _assert_full_chain_disposition(record, recommend=False)


@pytest.mark.parametrize("separator", _REVISION_SEPARATORS)
@pytest.mark.parametrize("marker", _REVISION_MARKERS)
@pytest.mark.parametrize("action", _ORDINARY_POSITIVE_ACTIONS)
def test_marker_only_positive_revision_without_target_fails_closed(
    separator: str,
    marker: str,
    action: str,
) -> None:
    message = f"先选择香水{separator}{marker}{action}"
    record = _selection_pipeline_record(
        message,
        TopicCode.FRAGRANCE,
    )
    tokens = exact_parsing._lex_exact_tokens(message)
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    merger = record["merger"]
    task = record["TaskPlan"]
    final_action = [
        token
        for token in tokens
        if token.kind.value == "selection_action"
    ][-1]

    assert isinstance(exact, dict)
    assert isinstance(merger, dict)
    assert isinstance(task, dict)
    assert message[
        final_action.source_span.start:final_action.source_span.end
    ] == action
    assert final_action.is_revision is False
    assert task["mode"] == "clarify"
    assert [
        event
        for event in events
        if event.is_revision
    ] == []
    assert exact["categories"] == []
    assert exact["issues"] == ["missing_revision_target"]
    assert merger["topic"] is None
    assert "missing_revision_target" in merger["issues"]
    assert task["categories"] == []
    assert task["references"] == []
    _assert_full_chain_disposition(record, recommend=False)


@pytest.mark.parametrize("separator", _REVISION_SEPARATORS)
@pytest.mark.parametrize("marker", _REVISION_MARKERS)
@pytest.mark.parametrize("action", _ORDINARY_POSITIVE_ACTIONS)
def test_marker_positive_revision_with_target_replaces_old_target(
    separator: str,
    marker: str,
    action: str,
) -> None:
    message = f"先选择香水{separator}{marker}{action}洁面"
    record = _selection_pipeline_record(
        message,
        TopicCode.CLEANSER,
    )
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    task = record["TaskPlan"]

    assert isinstance(exact, dict)
    assert isinstance(task, dict)
    assert [
        event.target_topic
        for event in events
        if event.is_revision
    ] == [TopicCode.CLEANSER]
    assert exact["categories"] == [TopicCode.CLEANSER.value]
    assert exact["issues"] == []
    assert task["mode"] == "recommend"
    assert task["categories"] == [TopicCode.CLEANSER.value]
    _assert_full_chain_disposition(record, recommend=True)


@pytest.mark.parametrize("separator", _REVISION_SEPARATORS)
@pytest.mark.parametrize("action", _ORDINARY_POSITIVE_ACTIONS)
def test_ordinary_positive_action_without_marker_does_not_inherit_target(
    separator: str,
    action: str,
) -> None:
    message = f"先选择香水{separator}{action}"
    record = _selection_pipeline_record(
        message,
        TopicCode.FRAGRANCE,
    )
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    task = record["TaskPlan"]
    final_action = [
        token
        for token in exact_parsing._lex_exact_tokens(message)
        if token.kind.value == "selection_action"
    ][-1]

    assert isinstance(exact, dict)
    assert isinstance(task, dict)
    assert not any(
        event.action_span == final_action.source_span
        for event in events
    )
    assert exact["categories"] == [TopicCode.FRAGRANCE.value]
    assert exact["issues"] == []
    assert task["mode"] == "recommend"
    assert task["categories"] == [TopicCode.FRAGRANCE.value]
    _assert_full_chain_disposition(record, recommend=True)


@pytest.mark.parametrize("withdrawal", _FINAL_NEGATIVE_PREDICATES)
def test_unmarked_negative_withdrawal_inherits_same_clause_target(
    withdrawal: str,
) -> None:
    message = f"先选择香水 {withdrawal}"
    record = _selection_pipeline_record(
        message,
        TopicCode.FRAGRANCE,
    )
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    task = record["TaskPlan"]

    assert isinstance(exact, dict)
    assert isinstance(task, dict)
    assert len(events) == 2
    final_event = events[-1]
    assert final_event.is_revision is False
    assert final_event.inherited_target is True
    assert final_event.polarity.value == "negative"
    assert final_event.target_topic is TopicCode.FRAGRANCE
    assert exact["categories"] == []
    assert exact["issues"] == []
    assert task["mode"] == "clarify"
    _assert_full_chain_disposition(record, recommend=False)


@pytest.mark.parametrize("action", _REVISION_ACTIONS)
def test_positive_revision_with_multiple_targets_is_typed_ambiguity(
    action: str,
) -> None:
    message = f"先选择香水，后来{action}洁面和防晒"
    record = _selection_pipeline_record(
        message,
        TopicCode.CLEANSER,
    )
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    merger = record["merger"]
    task = record["TaskPlan"]

    assert isinstance(exact, dict)
    assert isinstance(merger, dict)
    assert isinstance(task, dict)
    assert [
        event
        for event in events
        if event.is_revision
    ] == []
    assert exact["categories"] == []
    assert exact["issues"] == ["ambiguous_revision_target"]
    assert merger["topic"] is None
    assert "ambiguous_revision_target" in merger["issues"]
    assert [
        trace
        for trace in merger["trace"]
        if trace["field"] == "revision_target"
    ] == [
        {
            "field": "revision_target",
            "exact_value": "ambiguous",
            "semantic_value": TopicCode.CLEANSER.value,
            "resolution": "clarify",
        }
    ]
    assert task["mode"] == "clarify"
    assert task["categories"] == []
    _assert_full_chain_disposition(record, recommend=False)


@pytest.mark.parametrize("action", _REVISION_ACTIONS)
def test_positive_revision_with_one_new_target_still_replaces_old_target(
    action: str,
) -> None:
    message = f"先选择香水，后来{action}洁面"
    record = _selection_pipeline_record(
        message,
        TopicCode.CLEANSER,
    )
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    task = record["TaskPlan"]

    assert isinstance(exact, dict)
    assert isinstance(task, dict)
    assert [
        event.target_topic
        for event in events
        if event.is_revision
    ] == [TopicCode.CLEANSER]
    assert exact["categories"] == [TopicCode.CLEANSER.value]
    assert exact["issues"] == []
    assert task["mode"] == "recommend"
    assert task["categories"] == [TopicCode.CLEANSER.value]
    _assert_full_chain_disposition(record, recommend=True)


@pytest.mark.parametrize("separator", _WITHDRAWAL_SEPARATORS)
@pytest.mark.parametrize("marker", _REVISION_MARKERS)
@pytest.mark.parametrize("withdrawal", _FINAL_NEGATIVE_PREDICATES)
def test_final_negative_withdrawal_may_inherit_existing_target(
    separator: str,
    marker: str,
    withdrawal: str,
) -> None:
    message = f"先选择香水{separator}{marker}{withdrawal}"
    record = _selection_pipeline_record(
        message,
        TopicCode.FRAGRANCE,
    )
    events = exact_parsing._selection_events(message)
    exact = record["exact"]
    task = record["TaskPlan"]
    final_event = events[-1]

    assert isinstance(exact, dict)
    assert isinstance(task, dict)
    assert final_event.is_revision is True
    assert final_event.inherited_target is True
    assert final_event.polarity.value == "negative"
    assert final_event.target_topic is TopicCode.FRAGRANCE
    assert exact["categories"] == []
    assert exact["issues"] == []
    assert task["mode"] == "clarify"
    _assert_full_chain_disposition(record, recommend=False)


@pytest.mark.parametrize(
    ("message", "topic", "modal", "outcome", "event_count"),
    (
        (
            "可能不选择香水",
            TopicCode.FRAGRANCE,
            "可能",
            "unknown",
            1,
        ),
        (
            "也许不选择香水",
            TopicCode.FRAGRANCE,
            "也许",
            "unknown",
            1,
        ),
        (
            "没有负担的防晒",
            TopicCode.SUNSCREEN,
            None,
            "positive",
            0,
        ),
    ),
)
def test_modal_and_action_boundary_fail_closed_across_full_pipeline(
    message: str,
    topic: TopicCode,
    modal: str | None,
    outcome: str,
    event_count: int,
) -> None:
    record = _selection_pipeline_record(message, topic)
    tokens = exact_parsing._lex_exact_tokens(message)
    events = exact_parsing._selection_events(message)

    _assert_selection_outcome(
        record,
        topic=topic,
        outcome=outcome,
    )
    assert [
        message[token.source_span.start:token.source_span.end]
        for token in tokens
        if token.kind.value == "modal"
    ] == ([] if modal is None else [modal])
    assert len(events) == event_count
    if event_count == 0:
        assert not any(
            token.kind.value == "selection_action"
            for token in tokens
        )
    _assert_full_chain_disposition(
        record,
        recommend=outcome == "positive",
    )


@pytest.mark.parametrize(
    ("message", "topic", "outcome"),
    (
        ("无意选择香水", TopicCode.FRAGRANCE, "negative"),
        (
            "不太想选择木质调的香水",
            TopicCode.FRAGRANCE,
            "unknown",
        ),
    ),
)
def test_selection_action_findings_fail_closed_across_full_pipeline(
    message: str,
    topic: TopicCode,
    outcome: str,
) -> None:
    _assert_selection_outcome(
        _selection_pipeline_record(message, topic),
        topic=topic,
        outcome=outcome,
    )


@pytest.mark.parametrize(
    ("action", "expected_action"),
    _SELECTION_ACTION_CASES,
)
def test_selection_actions_are_lexed_by_grammatical_action_class(
    action: str,
    expected_action: str,
) -> None:
    lexer = getattr(
        __import__(
            "app.guide.understanding.exact_parsing",
            fromlist=["_lex_exact_tokens"],
        ),
        "_lex_exact_tokens",
        None,
    )
    assert lexer is not None

    tokens = lexer(f"我不太想{action}香水")
    action_values = [
        token.value.value
        for token in tokens
        if token.kind.value == "selection_action"
    ]

    assert action_values == [expected_action]


@pytest.mark.parametrize(
    "message",
    (
        "并非不是不想买香水",
        "没说不是不想买香水",
    ),
)
def test_nested_or_reported_selection_is_unknown_across_full_pipeline(
    message: str,
) -> None:
    _assert_selection_outcome(
        _selection_pipeline_record(message, TopicCode.FRAGRANCE),
        topic=TopicCode.FRAGRANCE,
        outcome="unknown",
    )


@pytest.mark.parametrize(
    ("message", "topic"),
    (
        ("无预算限制，我选择香水", TopicCode.FRAGRANCE),
        ("香水也不要；最后改选洁面", TopicCode.CLEANSER),
    ),
)
def test_clause_span_ownership_prevents_synthetic_exclusions(
    message: str,
    topic: TopicCode,
) -> None:
    record = _selection_pipeline_record(message, topic)
    exact = record["exact"]
    task = record["TaskPlan"]

    assert isinstance(exact, dict)
    assert isinstance(task, dict)
    assert exact["exclusions"] == []
    assert task["exclusions"] == []


def test_ordinal_reference_remains_typed_through_full_pipeline() -> None:
    message = "预算500元以内，想买第二款不含酒精的修护精华"
    constraints, issues = parse_exact_constraints(message)
    semantic = _proposal(
        topic=TopicCode.SERUM,
        references=(
            SemanticReference(
                kind="candidate_ordinal",
                ordinal=2,
                raw_text="第二款",
                start=message.index("第二款"),
                end=message.index("第二款") + len("第二款"),
            ),
        ),
    )
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        semantic=semantic,
    )
    task = _plan_with_explicit_test_outcome(merged)
    expected_span = {
        "start": message.index("第二款"),
        "end": message.index("第二款") + len("第二款"),
    }

    exact_references = [
        item.model_dump(mode="json")
        for item in constraints
        if item.kind == "candidate_ordinal"
    ]
    merged_references = [
        item.model_dump(mode="json")
        for item in getattr(merged, "references", ())
    ]
    task_references = [
        item.model_dump(mode="json")
        for item in getattr(task, "references", ())
    ]

    assert exact_references == [
        {
            "kind": "candidate_ordinal",
            "ordinal": 2,
            "source_span": expected_span,
        }
    ]
    assert merged_references == exact_references
    assert task_references == exact_references
    assert all(
        not proposal.startswith("reference=")
        for proposal in merged.semantic_proposals
    )
    assert task.mode == "recommend"


@pytest.mark.parametrize(
    ("alias", "topic"),
    _POLARITY_CATEGORY_CASES,
)
@pytest.mark.parametrize(
    "predicate",
    _POSITIVE_SELECTION_PREDICATES,
)
@pytest.mark.parametrize("prefix", _LEXICAL_POSITIVE_PREFIXES)
def test_intervening_lexical_content_cannot_negate_selection_predicate(
    alias: str,
    topic: TopicCode,
    predicate: str,
    prefix: str,
) -> None:
    _assert_selection_outcome(
        _selection_pipeline_record(
            f"我{prefix}{predicate}{alias}",
            topic,
        ),
        topic=topic,
        outcome="positive",
    )


@pytest.mark.parametrize(
    ("alias", "topic"),
    _POLARITY_CATEGORY_CASES,
)
@pytest.mark.parametrize("predicate", _NOMINAL_NEGATIVE_PREDICATES)
def test_nominal_negative_stance_vetoes_selection_without_fake_exclusion(
    alias: str,
    topic: TopicCode,
    predicate: str,
) -> None:
    _assert_selection_outcome(
        _selection_pipeline_record(
            f"我无意{predicate}{alias}",
            topic,
        ),
        topic=topic,
        outcome="negative",
    )


@pytest.mark.parametrize(
    ("alias", "topic"),
    _POLARITY_CATEGORY_CASES,
)
@pytest.mark.parametrize("predicate", _DIRECT_NEGATIVE_PREDICATES)
def test_direct_negative_selection_is_conservatively_excluded(
    alias: str,
    topic: TopicCode,
    predicate: str,
) -> None:
    _assert_selection_outcome(
        _selection_pipeline_record(
            f"我直接{predicate}{alias}",
            topic,
        ),
        topic=topic,
        outcome="negative",
    )


@pytest.mark.parametrize(
    ("alias", "topic"),
    _POLARITY_CATEGORY_CASES,
)
@pytest.mark.parametrize("attribute", _SELECTION_ATTRIBUTES)
@pytest.mark.parametrize(
    "predicate",
    _POSITIVE_SELECTION_PREDICATES,
)
@pytest.mark.parametrize("operator", _HEDGED_NEGATION_OPERATORS)
def test_hedged_negative_selection_is_unknown_not_attribute_exclusion(
    alias: str,
    topic: TopicCode,
    attribute: str,
    predicate: str,
    operator: str,
) -> None:
    _assert_selection_outcome(
        _selection_pipeline_record(
            f"我{operator}{predicate}{attribute}的{alias}",
            topic,
        ),
        topic=topic,
        outcome="unknown",
    )


@pytest.mark.parametrize(
    ("alias", "topic"),
    _POLARITY_CATEGORY_CASES,
)
@pytest.mark.parametrize("predicate", _DOUBLE_NEGATION_PREDICATES)
@pytest.mark.parametrize("outer", _DOUBLE_NEGATION_OUTERS)
def test_outer_negation_cancels_negative_selection_proposition(
    alias: str,
    topic: TopicCode,
    predicate: str,
    outer: str,
) -> None:
    _assert_selection_outcome(
        _selection_pipeline_record(
            f"{outer}{predicate}{alias}",
            topic,
        ),
        topic=topic,
        outcome="positive",
    )


@pytest.mark.parametrize(
    ("alias", "topic"),
    _POLARITY_CATEGORY_CASES,
)
@pytest.mark.parametrize("wrapper", _REPORTING_WRAPPERS)
def test_reporting_or_modal_wrapper_is_unknown_not_recommendation(
    alias: str,
    topic: TopicCode,
    wrapper: str,
) -> None:
    _assert_selection_outcome(
        _selection_pipeline_record(
            f"我{wrapper}不想买{alias}",
            topic,
        ),
        topic=topic,
        outcome="unknown",
    )


@pytest.mark.parametrize(
    ("alias", "topic"),
    _POLARITY_CATEGORY_CASES,
)
@pytest.mark.parametrize("separator", _EVENT_SEPARATORS)
@pytest.mark.parametrize(
    "initial_predicate",
    _POSITIVE_SELECTION_PREDICATES,
)
@pytest.mark.parametrize(
    "final_predicate",
    _FINAL_NEGATIVE_PREDICATES,
)
def test_final_negative_event_inherits_target_across_punctuation(
    alias: str,
    topic: TopicCode,
    separator: str,
    initial_predicate: str,
    final_predicate: str,
) -> None:
    _assert_selection_outcome(
        _selection_pipeline_record(
            (
                f"本来{initial_predicate}{alias}"
                f"{separator}后来{final_predicate}"
            ),
            topic,
        ),
        topic=topic,
        outcome="negative",
    )


@pytest.mark.parametrize(
    ("alias", "topic"),
    _POLARITY_CATEGORY_CASES,
)
@pytest.mark.parametrize("separator", _EVENT_SEPARATORS)
@pytest.mark.parametrize(
    "initial_predicate",
    ("不想买", "不考虑"),
)
@pytest.mark.parametrize(
    "final_predicate",
    _FINAL_POSITIVE_PREDICATES,
)
def test_positive_event_without_revision_marker_does_not_inherit_target(
    alias: str,
    topic: TopicCode,
    separator: str,
    initial_predicate: str,
    final_predicate: str,
) -> None:
    message = (
        f"本来{initial_predicate}{alias}"
        f"{separator}{final_predicate}"
    )
    record = _selection_pipeline_record(message, topic)
    final_action = [
        token
        for token in exact_parsing._lex_exact_tokens(message)
        if token.kind.value == "selection_action"
    ][-1]

    assert not any(
        event.action_span == final_action.source_span
        for event in exact_parsing._selection_events(message)
    )
    _assert_selection_outcome(
        record,
        topic=topic,
        outcome="negative",
    )


@pytest.mark.parametrize(
    ("message", "topic", "exclusions", "issue_codes"),
    (
        (
            "不含酒精的香水",
            TopicCode.FRAGRANCE,
            ["酒精"],
            [],
        ),
        (
            "不要所有的香水",
            None,
            [],
            [],
        ),
        (
            "不要太甜的香水",
            TopicCode.FRAGRANCE,
            [],
            ["unsupported_attribute_exclusion"],
        ),
    ),
)
def test_predicate_polarity_keeps_existing_ingredient_and_category_scope(
    message: str,
    topic: TopicCode | None,
    exclusions: list[str],
    issue_codes: list[str],
) -> None:
    constraints, issues = parse_exact_constraints(message)

    assert [
        item.value
        for item in constraints
        if isinstance(item, CategoryDraft)
    ] == ([] if topic is None else [topic])
    assert [
        item.value
        for item in constraints
        if isinstance(item, ExclusionDraft)
    ] == exclusions
    assert [item.code for item in issues] == issue_codes


def test_high_confidence_semantic_topic_fills_exact_gap_once() -> None:
    merged = merge_intent_signals(
        message="夏天涂的防止晒黑的东西",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(topic=TopicCode.SUNSCREEN),
    )

    assert merged.goal is UnderstandingGoal.RECOMMENDATION
    assert merged.topic is TopicCode.SUNSCREEN
    assert [
        item.value
        for item in merged.exact_constraints
        if isinstance(item, CategoryDraft)
    ] == [TopicCode.SUNSCREEN]
    assert merged.signal_trace[0].model_dump() == {
        "field": "topic",
        "exact_value": None,
        "semantic_value": "sunscreen",
        "resolution": "semantic_fills",
    }
    assert any(
        item.field == "goal" and item.resolution == "semantic_fills"
        for item in merged.signal_trace
    )


def test_matching_exact_and_semantic_topic_agree_without_duplication() -> None:
    exact = [CategoryDraft(value=TopicCode.FRAGRANCE)]

    merged = merge_intent_signals(
        message="推荐香水",
        exact_constraints=exact,
        exact_issues=[],
        semantic=_proposal(topic=TopicCode.FRAGRANCE),
    )

    assert merged.topic is TopicCode.FRAGRANCE
    assert [
        item.value
        for item in merged.exact_constraints
        if isinstance(item, CategoryDraft)
    ] == [TopicCode.FRAGRANCE]
    assert merged.signal_trace[0].resolution == "agree"
    assert merged.uncertainties == []


@pytest.mark.parametrize(
    ("exact_topic", "semantic_topic", "expected_resolution"),
    (
        (
            TopicCode.SERUM,
            TopicCode.SKINCARE,
            "exact_wins",
        ),
        (
            TopicCode.SKINCARE,
            TopicCode.SERUM,
            "semantic_fills",
        ),
    ),
)
def test_parent_and_child_topics_choose_the_more_specific_topic(
    exact_topic: TopicCode,
    semantic_topic: TopicCode,
    expected_resolution: str,
) -> None:
    merged = merge_intent_signals(
        message="想找一款护肤精华",
        exact_constraints=[CategoryDraft(value=exact_topic)],
        exact_issues=[],
        semantic=_proposal(topic=semantic_topic),
    )

    assert merged.topic is TopicCode.SERUM
    assert [
        item.value
        for item in merged.exact_constraints
        if isinstance(item, CategoryDraft)
    ] == [TopicCode.SERUM]
    assert not any(
        item.code == "ambiguous_category"
        for item in merged.uncertainties
    )
    assert merged.signal_trace[0].resolution == expected_resolution


def test_non_hard_topic_conflict_preserves_exact_and_clarifies() -> None:
    merged = merge_intent_signals(
        message="推荐防晒",
        exact_constraints=[CategoryDraft(value=TopicCode.SUNSCREEN)],
        exact_issues=[],
        semantic=_proposal(topic=TopicCode.FRAGRANCE),
    )

    assert merged.topic is TopicCode.SUNSCREEN
    assert [
        item.value
        for item in merged.exact_constraints
        if isinstance(item, CategoryDraft)
    ] == [TopicCode.SUNSCREEN]
    assert [item.code for item in merged.uncertainties] == [
        "ambiguous_category"
    ]
    assert merged.signal_trace[0].model_dump() == {
        "field": "topic",
        "exact_value": "sunscreen",
        "semantic_value": "fragrance",
        "resolution": "clarify",
    }


def test_exact_hard_constraints_remain_value_and_order_identical() -> None:
    exact = [
        BudgetDraft(
            minimum=Decimal("300.00"),
            maximum=Decimal("500.50"),
        ),
        SkinDraft(value=SkinTarget.OILY_SENSITIVE),
        ExclusionDraft(value="酒精"),
        EfficacyDraft(value=EfficacyTarget.REPAIR),
    ]
    before = [item.model_dump_json() for item in exact]

    merged = merge_intent_signals(
        message="300到500.50元，油敏肌，不要酒精，修护",
        exact_constraints=exact,
        exact_issues=[],
        semantic=_proposal(
            topic=TopicCode.SERUM,
            concerns=(ConcernCode.BUDGET, ConcernCode.EFFICACY),
        ),
    )

    assert [item.model_dump_json() for item in exact] == before
    assert [
        item.model_dump_json()
        for item in merged.exact_constraints[: len(exact)]
    ] == before
    assert isinstance(merged.exact_constraints[-1], CategoryDraft)
    assert merged.exact_constraints[-1].value is TopicCode.SERUM


def test_low_confidence_semantic_proposal_only_clarifies() -> None:
    merged = merge_intent_signals(
        message="给我来点那个",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(topic=None, confidence=0.69),
    )

    assert merged.goal is UnderstandingGoal.CLARIFICATION
    assert merged.topic is None
    assert merged.exact_constraints == []
    assert merged.semantic_proposals == []
    assert [item.code for item in merged.uncertainties] == [
        "missing_category"
    ]
    assert merged.signal_trace[0].resolution == "clarify"


def test_missing_semantic_proposal_is_typed_unavailable_clarification() -> None:
    merged = merge_intent_signals(
        message="给我来点那个",
        exact_constraints=[],
        exact_issues=[],
        semantic=None,
    )

    assert merged.goal is UnderstandingGoal.CLARIFICATION
    assert merged.topic is None
    assert [item.code for item in merged.uncertainties] == [
        "missing_category"
    ]
    assert [item.resolution for item in merged.signal_trace] == [
        "semantic_unavailable"
    ]


def test_semantic_unavailable_blocks_exact_recommendation_guessing(
) -> None:
    merged = _merge_message(
        "500 内适合油敏肌的防晒",
        semantic=None,
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert merged.goal is UnderstandingGoal.CLARIFICATION
    assert merged.topic is TopicCode.SUNSCREEN
    assert merged.uncertainties
    assert any(
        trace.resolution == "semantic_unavailable"
        for trace in merged.signal_trace
    )
    assert task.mode == "clarify"
    assert task.required_evidence == []


@pytest.mark.parametrize(
    "message",
    (
        "500 元内油敏肌防晒安全吗",
        "500 元内油敏肌防晒好不好",
        "500 元内油敏肌防晒是否适合",
        "500 元内适合油敏肌的防晒有哪些成分",
        "对比 500 元内适合油敏肌的防晒",
        "500 元内适合油敏肌的防晒适合我吗",
        "500 元内适合油敏肌的防晒怎么用",
    ),
)
def test_semantic_unavailable_does_not_guess_open_goal(
    message: str,
) -> None:
    merged = _merge_message(message, semantic=None)
    task = _plan_with_explicit_test_outcome(merged)

    assert merged.goal is UnderstandingGoal.CLARIFICATION
    assert merged.uncertainties
    assert any(
        trace.resolution == "semantic_unavailable"
        for trace in merged.signal_trace
    )
    assert task.mode == "clarify"
    assert task.required_evidence == []


@pytest.mark.parametrize(
    "message",
    (
        "推荐防晒",
        "对比防晒",
        "防晒适合我吗",
        "防晒有哪些成分",
    ),
)
def test_skip_disposition_without_closed_exact_proof_clarifies(
    message: str,
) -> None:
    merged = merge_intent_signals(
        message=message,
        exact_constraints=[CategoryDraft(value=TopicCode.SUNSCREEN)],
        exact_issues=[],
        exact_revision_confirmations=[],
        semantic=None,
        semantic_disposition=(
            SemanticLaneDisposition.SKIPPED_BY_CONTRACT
        ),
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert merged.goal is UnderstandingGoal.CLARIFICATION
    assert merged.topic is TopicCode.SUNSCREEN
    assert merged.uncertainties
    assert task.mode == "clarify"
    assert task.required_evidence == []


def test_skip_disposition_accepts_matching_typed_revision_proof() -> None:
    message = "后来改选洁面！！！"
    constraints, issues = parse_exact_constraints(message)
    confirmations = parse_exact_revision_confirmations(message)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        exact_revision_confirmations=confirmations,
        semantic=None,
        semantic_disposition=(
            SemanticLaneDisposition.SKIPPED_BY_CONTRACT
        ),
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert merged.goal is UnderstandingGoal.RECOMMENDATION
    assert merged.topic is TopicCode.CLEANSER
    assert merged.uncertainties == []
    assert task.mode == "recommend"
    assert task.required_evidence == ["canonical_product"]


@pytest.mark.parametrize(
    "message",
    (
        "后来改选洁面，对比一下",
        "后来改选洁面，适合我吗",
        "后来改选洁面，有哪些成分",
        "后来改选洁面对比一下",
        "后来改选洁面compare",
        "后来改选洁面123",
    ),
)
def test_skip_proof_cannot_authorize_open_goal_suffix(
    message: str,
) -> None:
    constraints, issues = parse_exact_constraints(message)
    confirmations = parse_exact_revision_confirmations(message)

    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        exact_revision_confirmations=confirmations,
        semantic=None,
        semantic_disposition=(
            SemanticLaneDisposition.SKIPPED_BY_CONTRACT
        ),
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert merged.goal is UnderstandingGoal.CLARIFICATION
    assert merged.topic is TopicCode.CLEANSER
    assert merged.uncertainties
    assert task.mode == "clarify"
    assert task.required_evidence == []


def test_skip_disposition_rejects_proof_span_outside_message() -> None:
    merged = merge_intent_signals(
        message="改选洁面",
        exact_constraints=[CategoryDraft(value=TopicCode.CLEANSER)],
        exact_issues=[],
        exact_revision_confirmations=[
            ExactRevisionConfirmation(
                operation=ExactRevisionOperation.REVISE_CONSTRAINT,
                target=ExactRevisionTarget.CATEGORY,
                source_span=SourceSpan(start=20, end=24),
            )
        ],
        semantic=None,
        semantic_disposition=(
            SemanticLaneDisposition.SKIPPED_BY_CONTRACT
        ),
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert merged.goal is UnderstandingGoal.CLARIFICATION
    assert merged.uncertainties
    assert task.mode == "clarify"
    assert task.required_evidence == []


def test_skip_disposition_rejects_proof_for_other_exact_target() -> None:
    message = "后来改选洁面"
    merged = merge_intent_signals(
        message=message,
        exact_constraints=[CategoryDraft(value=TopicCode.CLEANSER)],
        exact_issues=[],
        exact_revision_confirmations=[
            ExactRevisionConfirmation(
                operation=ExactRevisionOperation.REVISE_CONSTRAINT,
                target=ExactRevisionTarget.BUDGET,
                source_span=SourceSpan(start=0, end=len(message)),
            )
        ],
        semantic=None,
        semantic_disposition=(
            SemanticLaneDisposition.SKIPPED_BY_CONTRACT
        ),
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert merged.goal is UnderstandingGoal.CLARIFICATION
    assert merged.uncertainties
    assert task.mode == "clarify"
    assert task.required_evidence == []


def test_semantic_unavailable_does_not_relax_hard_topic_conflict() -> None:
    merged = _merge_message(
        "推荐防晒但不推荐防晒",
        semantic=None,
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert merged.goal is UnderstandingGoal.CLARIFICATION
    assert merged.topic is None
    assert merged.uncertainties
    assert task.mode == "clarify"
    assert task.required_evidence == []


def test_exact_lane_emits_typed_category_revision_confirmation() -> None:
    confirmations = parse_exact_revision_confirmations(
        "先选择香水，后来改选洁面"
    )

    assert [
        (
            confirmation.operation.value,
            confirmation.target.value,
        )
        for confirmation in confirmations
    ] == [("revise_constraint", "category")]


def test_exact_lane_emits_chinese_budget_revision_confirmation() -> None:
    message = "预算改成三百以内，防晒继续看"

    confirmations = parse_exact_revision_confirmations(message)

    budget = next(
        confirmation
        for confirmation in confirmations
        if confirmation.target is ExactRevisionTarget.BUDGET
    )
    assert budget.operation is ExactRevisionOperation.REVISE_CONSTRAINT
    assert (
        message[budget.source_span.start:budget.source_span.end]
        == "预算改成三百以内"
    )


def test_chinese_budget_revision_proof_remains_code_owned() -> None:
    message = "预算改成三百以内，防晒继续看"
    constraints, issues = parse_exact_constraints(message)
    confirmations = parse_exact_revision_confirmations(message)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        exact_revision_confirmations=confirmations,
        semantic=_proposal(
            goal=UnderstandingGoal.FOLLOWUP,
            topic=TopicCode.SUNSCREEN,
            references=(
                SemanticReference(
                    kind="previous_constraint",
                    raw_text="预算",
                    start=0,
                    end=2,
                ),
            ),
        ),
    )

    assert confirmations[0].target is ExactRevisionTarget.BUDGET
    assert not any(
        trace.field.startswith("act.")
        for trace in merged.signal_trace
    )


def test_exact_revision_proof_fills_missing_previous_constraint_reference(
) -> None:
    message = "预算改成三百以内，而且还是不要含酒精的呢"
    constraints, issues = parse_exact_constraints(message)
    confirmations = parse_exact_revision_confirmations(message)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        exact_revision_confirmations=confirmations,
        semantic=_proposal(
            goal=UnderstandingGoal.FOLLOWUP,
            topic=TopicCode.SUNSCREEN,
            references=(),
        ),
        context=SemanticContext(
            conversation_version=3,
            active_topic=TopicCode.SUNSCREEN,
            visible_candidate_count=3,
            focused_candidate_ordinal=None,
            image_count=0,
            focused_image_ordinal=None,
            active_constraint_kinds=(
                ActiveConstraintKind.BUDGET,
                ActiveConstraintKind.CATEGORY,
                ActiveConstraintKind.INGREDIENT_EXCLUSION,
            ),
            confirmed_profile_fields=(
                ConfirmedProfileField.INGREDIENT_EXCLUSION,
            ),
        ),
    )

    proof = confirmations[0]
    assert [
        (
            reference.kind,
            reference.source_span,
        )
        for reference in merged.references
    ] == [
        (
            "previous_constraint",
            proof.source_span,
        )
    ]
    assert merged.uncertainties == []
    assert _plan_with_explicit_test_outcome(merged).mode == "followup"


@pytest.mark.parametrize(
    ("semantic", "semantic_value", "fallback_field", "fallback_resolution"),
    (
        (None, None, "semantic", "semantic_unavailable"),
        (
            _proposal(topic=TopicCode.SUNSCREEN, confidence=0.69),
            "sunscreen",
            "semantic_confidence",
            "clarify",
        ),
    ),
)
def test_exact_topic_is_traced_before_semantic_early_exit(
    semantic: SemanticIntentProposal | None,
    semantic_value: str | None,
    fallback_field: str,
    fallback_resolution: str,
) -> None:
    exact_issues = [
        UnderstandingIssue(
            code="invalid_budget",
            detail="first exact issue",
        ),
        UnderstandingIssue(
            code="unsupported_budget_format",
            detail="second exact issue",
        ),
    ]

    merged = merge_intent_signals(
        message="推荐香水",
        exact_constraints=[CategoryDraft(value=TopicCode.FRAGRANCE)],
        exact_issues=exact_issues,
        semantic=semantic,
    )

    assert merged.topic is TopicCode.FRAGRANCE
    assert merged.signal_trace[0].model_dump() == {
        "field": "topic",
        "exact_value": "fragrance",
        "semantic_value": semantic_value,
        "resolution": "exact_wins",
    }
    assert merged.signal_trace[1].field == fallback_field
    assert merged.signal_trace[1].resolution == fallback_resolution
    assert [
        item.model_dump_json()
        for item in merged.uncertainties[: len(exact_issues)]
    ] == [item.model_dump_json() for item in exact_issues]


def test_fuzzy_budget_observation_agrees_without_fake_missing_category(
) -> None:
    message = "预算几百块上下，要适合油敏肌的防晒"
    merged = _merge_message(
        message,
        semantic=_proposal(
            topic=TopicCode.SUNSCREEN,
            concerns=(
                ConcernCode.SUN_PROTECTION,
                ConcernCode.SENSITIVITY,
            ),
            observations=(
                SemanticObservation(
                    code=ObservationCode.CURRENT_BUDGET_UNKNOWN,
                    present=True,
                    qualifier=ObservationQualifier.RANGE,
                ),
            ),
            number_candidates=(
                SemanticNumberCandidate(
                    relation="range",
                    raw_text="几百块上下",
                    start=2,
                    end=7,
                    minimum=None,
                    maximum=None,
                ),
            ),
        ),
    )

    assert merged.topic is TopicCode.SUNSCREEN
    assert [issue.code for issue in merged.uncertainties] == [
        "unsupported_budget_format",
    ]
    assert any(
        trace.field == "observation.current_budget_unknown"
        and trace.resolution == "agree"
        for trace in merged.signal_trace
    )
    task = _plan_with_explicit_test_outcome(merged)
    assert task.mode == "clarify"
    assert task.clarification_code is ClarificationCode.BUDGET
    assert "200 到 900" in task.clarification


def test_original_exact_issue_order_is_preserved_before_merger_issue() -> None:
    exact_issues = [
        UnderstandingIssue(
            code="invalid_budget",
            detail="first exact issue",
        ),
        UnderstandingIssue(
            code="unsupported_budget_format",
            detail="second exact issue",
        ),
    ]
    before = [item.model_dump_json() for item in exact_issues]

    merged = merge_intent_signals(
        message="预算不明确",
        exact_constraints=[],
        exact_issues=exact_issues,
        semantic=None,
    )

    assert [item.model_dump_json() for item in exact_issues] == before
    assert [
        item.model_dump_json()
        for item in merged.uncertainties[: len(exact_issues)]
    ] == before
    assert merged.uncertainties[-1].code == "missing_category"


def test_all_clarification_outcomes_pass_strict_validation() -> None:
    unavailable = merge_intent_signals(
        message="给我来点那个",
        exact_constraints=[],
        exact_issues=[],
        semantic=None,
    )
    low_confidence = merge_intent_signals(
        message="给我来点那个",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(topic=None, confidence=0.3),
    )
    conflict = merge_intent_signals(
        message="推荐防晒",
        exact_constraints=[CategoryDraft(value=TopicCode.SUNSCREEN)],
        exact_issues=[],
        semantic=_proposal(topic=TopicCode.FRAGRANCE),
    )

    for outcome in (unavailable, low_confidence, conflict):
        validated = StructuredUnderstanding.model_validate(
            outcome.model_dump(),
            strict=True,
        )
        assert validated == outcome


@pytest.mark.parametrize("raw_semantic", [{}, "recommendation"])
def test_raw_semantic_payload_cannot_bypass_pydantic(
    raw_semantic: object,
) -> None:
    with pytest.raises(TypeError, match="SemanticIntentProposal"):
        merge_intent_signals(
            message="推荐香水",
            exact_constraints=[],
            exact_issues=[],
            semantic=raw_semantic,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field", "raw_value"),
    (
        ("exact_constraints", [{"kind": "category", "value": "fragrance"}]),
        (
            "exact_issues",
            [{"code": "missing_category", "detail": "raw"}],
        ),
    ),
)
def test_raw_exact_payload_cannot_bypass_typed_contracts(
    field: str,
    raw_value: object,
) -> None:
    arguments = {
        "message": "推荐香水",
        "exact_constraints": [],
        "exact_issues": [],
        "semantic": _proposal(),
    }
    arguments[field] = raw_value

    with pytest.raises(TypeError, match=field):
        merge_intent_signals(**arguments)  # type: ignore[arg-type]


def test_semantic_meaning_is_redacted_into_public_audit_fields() -> None:
    merged = merge_intent_signals(
        message="第二款会不会让T区出油",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(
            topic=TopicCode.SKINCARE,
            concerns=(ConcernCode.TEXTURE,),
            observations=(
                SemanticObservation(
                    code=ObservationCode.OILINESS,
                    present=True,
                    qualifier=ObservationQualifier.T_ZONE,
                ),
            ),
            references=(
                SemanticReference(
                    kind="candidate_ordinal",
                    ordinal=2,
                    raw_text="第二款",
                    start=0,
                    end=3,
                ),
            ),
        ),
    )

    assert merged.observations == [
        "observation=oiliness;present=true;qualifier=t_zone"
    ]
    assert merged.semantic_proposals == ["concern=texture"]
    assert [
        item.model_dump(mode="json")
        for item in merged.references
    ] == [
        {
            "kind": "candidate_ordinal",
            "ordinal": 2,
                "source_span": {"start": 0, "end": 3},
        }
    ]
    assert merged.image_references == []


@pytest.mark.parametrize(
    ("message", "semantic_topic"),
    (
        ("不要所有的香水", TopicCode.FRAGRANCE),
        ("不考虑防晒并且平价香水", TopicCode.FRAGRANCE),
        ("推荐防晒但不推荐防晒", TopicCode.SUNSCREEN),
    ),
)
def test_hard_category_negation_vetoes_semantic_topic(
    message: str,
    semantic_topic: TopicCode,
) -> None:
    merged = _merge_message(
        message,
        semantic=_proposal(topic=semantic_topic),
    )

    assert merged.topic is None
    assert not any(
        isinstance(item, CategoryDraft)
        and item.value is semantic_topic
        for item in merged.exact_constraints
    )
    assert merged.uncertainties
    assert merged.signal_trace[0].model_dump() == {
        "field": "topic",
        "exact_value": f"excluded:{semantic_topic.value}",
        "semantic_value": semantic_topic.value,
        "resolution": "exact_wins",
    }


@pytest.mark.parametrize(
    "message",
    (
        "没有特别想买但后来还是想买香水",
        "不见得推荐防晒但是后来改买香水",
        "没多么想买防晒后来推荐香水",
    ),
)
def test_later_explicit_positive_turn_cancels_earlier_negated_predicate(
    message: str,
) -> None:
    merged = _merge_message(
        message,
        semantic=_proposal(topic=TopicCode.FRAGRANCE),
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert merged.topic is TopicCode.FRAGRANCE
    assert [
        item.value
        for item in merged.exact_constraints
        if isinstance(item, CategoryDraft)
    ] == [TopicCode.FRAGRANCE]
    assert merged.uncertainties == []
    assert merged.signal_trace[0].resolution == "agree"
    assert task.mode == "recommend"


@pytest.mark.parametrize(
    "message",
    (
        "不考虑防晒并非常想买香水",
        "不考虑防晒并帮我推荐香水",
    ),
)
def test_round9_open_positive_topic_can_be_filled_by_semantic(
    message: str,
) -> None:
    merged = _merge_message(
        message,
        semantic=_proposal(topic=TopicCode.FRAGRANCE),
    )

    assert merged.goal is UnderstandingGoal.RECOMMENDATION
    assert merged.topic is TopicCode.FRAGRANCE
    assert merged.uncertainties == []
    assert merged.signal_trace[0].resolution in {
        "agree",
        "semantic_fills",
    }


def test_source_bound_finish_preference_projects_typed_preference_draft(
) -> None:
    message = "想要哑光一点的粉底"
    merged = _merge_message(
        message,
        semantic=_proposal(
            topic=TopicCode.BASE_MAKEUP,
            concerns=(ConcernCode.FINISH,),
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=SemanticPreferenceField.FINISH,
                    raw_text="哑光",
                    start=5,
                    end=7,
                    strength=SemanticPreferenceStrength.PREFERENCE,
                ),
            ),
        ),
    )

    assert [
        (draft.field_key, draft.value)
        for draft in merged.preference_drafts
    ] == [("finish", "哑光")]
    task = _plan_with_explicit_test_outcome(merged)
    assert any(
        item.kind == "facet"
        and item.field_key == "finish"
        and item.value == "哑光"
        for item in task.constraints
    )


def test_exact_skin_deduplicates_equivalent_soft_skin_preference(
) -> None:
    message = "肤质改成油敏肌后呢"
    start = message.index("油敏肌")
    constraints, issues = parse_exact_constraints(message)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        exact_revision_confirmations=(
            parse_exact_revision_confirmations(message)
        ),
        semantic=_proposal(
            goal=UnderstandingGoal.FOLLOWUP,
            topic=TopicCode.BASE_MAKEUP,
            references=(
                SemanticReference(
                    kind="previous_constraint",
                    ordinal=None,
                    raw_text="肤质",
                    start=0,
                    end=2,
                ),
            ),
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=SemanticPreferenceField.SUITABLE_SKIN,
                    raw_text="油敏肌",
                    start=start,
                    end=start + 3,
                    strength=SemanticPreferenceStrength.PREFERENCE,
                ),
            ),
        ),
    )

    assert any(
        isinstance(item, SkinDraft)
        and item.value is SkinTarget.OILY_SENSITIVE
        for item in merged.exact_constraints
    )
    assert merged.preference_drafts == []
    assert any(
        trace.field == "preference_candidate.suitable_skin"
        and trace.resolution == "exact_wins"
        for trace in merged.signal_trace
    )


def test_ingredient_tone_routes_preference_soft_and_unknown_hard() -> None:
    soft_message = "偏向不含酒精的防晒"
    soft = _merge_message(
        soft_message,
        semantic=_proposal(
            topic=TopicCode.SUNSCREEN,
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=SemanticPreferenceField.INGREDIENT_EXCLUSION,
                    raw_text="不含酒精",
                    start=2,
                    end=6,
                    strength=SemanticPreferenceStrength.PREFERENCE,
                ),
            ),
        ),
    )
    hard_message = "不含酒精的防晒"
    hard = _merge_message(
        hard_message,
        semantic=_proposal(
            topic=TopicCode.SUNSCREEN,
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=SemanticPreferenceField.INGREDIENT_EXCLUSION,
                    raw_text="酒精",
                    start=2,
                    end=4,
                    strength=SemanticPreferenceStrength.UNKNOWN,
                ),
            ),
        ),
    )

    assert not any(
        isinstance(item, ExclusionDraft)
        for item in soft.exact_constraints
    )
    assert [
        (draft.field_key, draft.value)
        for draft in soft.preference_drafts
    ] == [("verified_absences", "酒精")]
    assert any(
        isinstance(item, ExclusionDraft) and item.value == "酒精"
        for item in hard.exact_constraints
    )
    assert hard.preference_drafts == []


def test_allergy_strength_keeps_ingredient_exclusion_hard() -> None:
    message = "我酒精过敏，推荐防晒"
    merged = _merge_message(
        message,
        semantic=_proposal(
            topic=TopicCode.SUNSCREEN,
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=SemanticPreferenceField.INGREDIENT_EXCLUSION,
                    raw_text="酒精",
                    start=1,
                    end=3,
                    strength=SemanticPreferenceStrength.SAFETY,
                ),
            ),
        ),
    )

    assert any(
        isinstance(item, ExclusionDraft) and item.value == "酒精"
        for item in merged.exact_constraints
    )
    assert merged.preference_drafts == []


@pytest.mark.parametrize(
    ("message", "field_name", "raw_text", "expected_field"),
    (
        (
            "我是敏感肌，想找温和一点的防晒",
            "SUITABLE_SKIN",
            "敏感肌",
            "suitable_skin",
        ),
        (
            "刚做完医美，想找温和一点的防晒",
            "USAGE_CONTEXT",
            "医美",
            "usage_context",
        ),
    ),
)
def test_ordinary_sensitivity_context_remains_soft_preference(
    message: str,
    field_name: str,
    raw_text: str,
    expected_field: str,
) -> None:
    start = message.index(raw_text)
    merged = _merge_message(
        message,
        semantic=_proposal(
            topic=TopicCode.SUNSCREEN,
            safety_sensitive=False,
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=getattr(
                        SemanticPreferenceField,
                        field_name,
                    ),
                    raw_text=raw_text,
                    start=start,
                    end=start + len(raw_text),
                    strength=SemanticPreferenceStrength.PREFERENCE,
                ),
            ),
        ),
    )

    assert not merged.safety_sensitive
    assert [
        (draft.field_key, draft.value)
        for draft in merged.preference_drafts
    ] == [(expected_field, raw_text)]


def test_ingredient_presence_soft_and_absolute_routes_stay_separate() -> None:
    soft_message = "最好含烟酰胺的精华"
    hard_message = "必须含烟酰胺的精华"
    field = getattr(
        SemanticPreferenceField,
        "INGREDIENT_PRESENCE",
    )
    soft_start = soft_message.index("烟酰胺")
    hard_start = hard_message.index("烟酰胺")

    soft = _merge_message(
        soft_message,
        semantic=_proposal(
            topic=TopicCode.SERUM,
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=field,
                    raw_text="烟酰胺",
                    start=soft_start,
                    end=soft_start + 3,
                    strength=SemanticPreferenceStrength.PREFERENCE,
                ),
            ),
        ),
    )
    hard = _merge_message(
        hard_message,
        semantic=_proposal(
            topic=TopicCode.SERUM,
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=field,
                    raw_text="烟酰胺",
                    start=hard_start,
                    end=hard_start + 3,
                    strength=SemanticPreferenceStrength.SAFETY,
                ),
            ),
        ),
    )

    assert [
        (draft.field_key, draft.value)
        for draft in soft.preference_drafts
    ] == [("ingredients_present", "烟酰胺")]
    assert not any(
        item.kind == "include"
        for item in soft.exact_constraints
    )
    assert any(
        item.kind == "include" and item.value == "烟酰胺"
        for item in hard.exact_constraints
    )
    assert hard.preference_drafts == []


def test_model_cannot_promote_ingredient_presence_without_absolute_text(
) -> None:
    message = "含烟酰胺的精华"
    start = message.index("烟酰胺")
    merged = _merge_message(
        message,
        semantic=_proposal(
            topic=TopicCode.SERUM,
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=getattr(
                        SemanticPreferenceField,
                        "INGREDIENT_PRESENCE",
                    ),
                    raw_text="烟酰胺",
                    start=start,
                    end=start + 3,
                    strength=SemanticPreferenceStrength.SAFETY,
                ),
            ),
        ),
    )

    assert not any(
        item.kind == "include"
        for item in merged.exact_constraints
    )
    assert [item.code for item in merged.uncertainties] == [
        "unverified_safety_requirement"
    ]


@pytest.mark.parametrize(
    ("message", "field_name", "raw_text", "hard_kind"),
    (
        (
            "我酒精过敏，推荐防晒",
            "INGREDIENT_EXCLUSION",
            "酒精",
            "exclude",
        ),
        (
            "必须含烟酰胺的精华",
            "INGREDIENT_PRESENCE",
            "烟酰胺",
            "include",
        ),
    ),
)
def test_exact_hard_ingredient_signal_cannot_be_downgraded_to_preference(
    message: str,
    field_name: str,
    raw_text: str,
    hard_kind: str,
) -> None:
    start = message.index(raw_text)
    merged = _merge_message(
        message,
        semantic=_proposal(
            topic=(
                TopicCode.SUNSCREEN
                if hard_kind == "exclude"
                else TopicCode.SERUM
            ),
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=getattr(
                        SemanticPreferenceField,
                        field_name,
                    ),
                    raw_text=raw_text,
                    start=start,
                    end=start + len(raw_text),
                    strength=SemanticPreferenceStrength.PREFERENCE,
                ),
            ),
        ),
    )

    assert any(
        item.kind == hard_kind and item.value == raw_text
        for item in merged.exact_constraints
    )
    assert merged.preference_drafts == []
    assert any(
        trace.field.endswith(field_name.casefold())
        and trace.resolution == "exact_wins"
        for trace in merged.signal_trace
    )


@pytest.mark.parametrize(
    "strength",
    (
        SemanticPreferenceStrength.SAFETY,
        SemanticPreferenceStrength.UNKNOWN,
    ),
)
def test_noningredient_serious_or_unknown_severity_fails_closed(
    strength: SemanticPreferenceStrength,
) -> None:
    message = "我的皮肤很敏感，一定不能刺激，推荐防晒"
    start = message.index("敏感")
    merged = _merge_message(
        message,
        semantic=_proposal(
            topic=TopicCode.SUNSCREEN,
            safety_sensitive=True,
            preference_candidates=(
                SemanticPreferenceCandidate(
                    field=SemanticPreferenceField.SUITABLE_SKIN,
                    raw_text="敏感",
                    start=start,
                    end=start + 2,
                    strength=strength,
                ),
            ),
        ),
    )

    assert merged.safety_sensitive
    assert merged.preference_drafts == []
    assert "unverified_safety_requirement" in {
        item.code for item in merged.uncertainties
    }


@pytest.mark.parametrize(
    "message",
    (
        "不要这种太甜的香水",
        "避开所有甜腻的香水",
        "香水不推荐太甜的",
    ),
)
def test_round9_attribute_scope_is_preserved_as_typed_clarification(
    message: str,
) -> None:
    merged = _merge_message(
        message,
        semantic=_proposal(topic=TopicCode.FRAGRANCE),
    )

    assert merged.topic is TopicCode.FRAGRANCE
    assert not any(
        isinstance(item, ExclusionDraft)
        for item in merged.exact_constraints
    )
    assert [item.code for item in merged.uncertainties] == [
        "unsupported_attribute_exclusion"
    ]


@pytest.mark.parametrize(
    ("goal", "expected_code"),
    (
        (
            UnderstandingGoal.COMPARISON,
            ClarificationCode.REFERENCE,
        ),
        (
            UnderstandingGoal.IMAGE_SIMILARITY,
            ClarificationCode.REFERENCE,
        ),
        (
            UnderstandingGoal.ASSESSMENT,
            ClarificationCode.GOAL,
        ),
        (
            UnderstandingGoal.CLARIFICATION,
            ClarificationCode.GOAL,
        ),
    ),
)
def test_non_executable_semantic_goal_fails_closed_with_typed_gap(
    goal: UnderstandingGoal,
    expected_code: ClarificationCode,
) -> None:
    merged = merge_intent_signals(
        message="看看这个",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(goal=goal, topic=TopicCode.FRAGRANCE),
    )

    task = _plan_with_explicit_test_outcome(merged)

    assert merged.goal is goal
    assert task.mode == "clarify"
    assert task.constraints
    assert task.required_evidence == []
    assert task.clarification
    assert task.clarification_code is expected_code


def test_knowledge_goal_keeps_typed_mode_without_product_reference() -> None:
    merged = merge_intent_signals(
        message="香水留香是什么原理",
        exact_constraints=[
            CategoryDraft(value=TopicCode.FRAGRANCE),
        ],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.FRAGRANCE,
        ),
    )

    task = _plan_with_explicit_test_outcome(merged)

    assert task.mode == "knowledge"
    assert task.required_evidence == ["canonical_product"]
    assert task.clarification is None


def test_category_suitability_keeps_typed_mode_without_product_reference(
) -> None:
    merged = merge_intent_signals(
        message="敏感肌能用防晒吗",
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.SUITABILITY,
            topic=TopicCode.SUNSCREEN,
        ),
    )

    task = _plan_with_explicit_test_outcome(merged)

    assert task.mode == "suitability"
    assert task.product_ids == []
    assert task.clarification is None


@pytest.mark.parametrize("raw_understanding", [{}, "recommendation"])
def test_task_planning_rejects_raw_understanding(
    raw_understanding: object,
) -> None:
    with pytest.raises(TypeError, match="StructuredUnderstanding"):
        _plan_task(raw_understanding)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "message",
    (
        "预算 - 100到200元推荐香水",
        "预算 - 100.5到200.75元推荐香水",
    ),
)
def test_signed_budget_range_fails_closed_across_full_pipeline(
    message: str,
) -> None:
    constraints, issues = parse_exact_constraints(message)
    semantic = _proposal(topic=TopicCode.FRAGRANCE)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        semantic=semantic,
    )
    task = _plan_with_explicit_test_outcome(merged)

    assert not any(
        isinstance(item, BudgetDraft)
        for item in constraints
    )
    assert [item.code for item in issues] == ["invalid_budget"]
    assert semantic.topic is TopicCode.FRAGRANCE
    assert merged.topic is TopicCode.FRAGRANCE
    assert [item.code for item in merged.uncertainties] == [
        "invalid_budget"
    ]
    assert task.mode == "clarify"
    assert task.required_evidence == []
    assert "预算" in task.clarification

    record = {
        "RetrievalResult": {"disposition": "not_invoked"},
        "DecisionResult": {"disposition": "not_invoked"},
        "ResponsePlan/SSE": {"disposition": "typed_clarification"},
        "state": "unchanged",
    }
    _assert_full_chain_disposition(record, recommend=False)


def test_terminal_clause_topic_does_not_inherit_exclusion_across_full_pipeline(
) -> None:
    message = "不要香水。防晒"
    record = _selection_pipeline_record(
        message,
        TopicCode.SUNSCREEN,
    )
    events = exact_parsing._selection_events(message)

    assert [
        (event.target_topic, event.polarity.value)
        for event in events
    ] == [(TopicCode.FRAGRANCE, "negative")]
    assert exact_parsing.parse_hard_category_exclusions(message) == (
        TopicCode.FRAGRANCE,
    )
    assert record["exact"] == {
        "categories": [TopicCode.SUNSCREEN.value],
        "exclusions": [],
        "issues": [],
        "references": [],
    }
    assert record["semantic"] == {
        "goal": UnderstandingGoal.RECOMMENDATION.value,
        "topic": TopicCode.SUNSCREEN.value,
        "confidence": 0.95,
    }
    merger = record["merger"]
    task = record["TaskPlan"]
    assert isinstance(merger, dict)
    assert isinstance(task, dict)
    assert merger["topic"] == TopicCode.SUNSCREEN.value
    assert merger["issues"] == []
    assert merger["trace"][0]["resolution"] == "agree"
    assert task["mode"] == "recommend"
    assert task["categories"] == [TopicCode.SUNSCREEN.value]
    _assert_full_chain_disposition(record, recommend=True)


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        ("预算1,000元推荐防晒", Decimal("1000")),
        ("预算１，０００．５０元推荐防晒", Decimal("1000.50")),
    ),
)
def test_grouped_budget_is_complete_across_full_pipeline(
    message: str,
    expected: Decimal,
) -> None:
    constraints, issues = parse_exact_constraints(message)
    semantic = _proposal(topic=TopicCode.SUNSCREEN)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        semantic=semantic,
    )
    task = _plan_with_explicit_test_outcome(merged)
    exact_budgets = [
        item
        for item in constraints
        if isinstance(item, BudgetDraft)
    ]
    task_budgets = [
        item
        for item in task.constraints
        if item.kind == "budget"
    ]

    assert len(exact_budgets) == 1
    assert exact_budgets[0].minimum is None
    assert exact_budgets[0].maximum == expected
    assert issues == []
    assert semantic.topic is TopicCode.SUNSCREEN
    assert merged.topic is TopicCode.SUNSCREEN
    assert merged.uncertainties == []
    assert merged.signal_trace[0].resolution == "agree"
    assert task.mode == "recommend"
    assert len(task_budgets) == 1
    assert task_budgets[0].minimum is None
    assert task_budgets[0].maximum == expected
    assert task.required_evidence == ["canonical_product"]

    record = {
        "RetrievalResult": {"disposition": "eligible"},
        "DecisionResult": {"disposition": "pending_retrieval"},
        "ResponsePlan/SSE": {"disposition": "pending_evidence"},
        "state": "eligible_after_visible_cards",
    }
    _assert_full_chain_disposition(record, recommend=True)


@pytest.mark.parametrize(
    ("hint", "observation"),
    (
        (
            ClarificationCode.GOAL,
            ObservationCode.GOAL_UNCLEAR,
        ),
        (
            ClarificationCode.TOPIC,
            ObservationCode.TOPIC_UNCLEAR,
        ),
    ),
)
def test_resolved_goal_and_topic_ignore_stale_clarification_signals(
    hint: ClarificationCode,
    observation: ObservationCode,
) -> None:
    merged = merge_intent_signals(
        message="推荐香水",
        exact_constraints=[
            CategoryDraft(value=TopicCode.FRAGRANCE),
        ],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.RECOMMENDATION,
            topic=TopicCode.FRAGRANCE,
            observations=(
                SemanticObservation(
                    code=observation,
                    present=True,
                ),
            ),
            clarification_hint=hint,
        ),
    )

    assert merged.goal is UnderstandingGoal.RECOMMENDATION
    assert merged.topic is TopicCode.FRAGRANCE
    assert merged.uncertainties == []
    assert not any(
        trace.resolution == "clarify"
        for trace in merged.signal_trace
        if (
            trace.field == "clarification_hint"
            or trace.field == f"observation.{observation.value}"
        )
    )


def test_resolved_reference_ignores_stale_reference_signals() -> None:
    reference = ReferenceDraft(
        kind="current_item",
        source_span=SourceSpan(start=0, end=2),
    )
    merged = merge_intent_signals(
        message="这个香水适合我吗",
        exact_constraints=[
            CategoryDraft(value=TopicCode.FRAGRANCE),
            reference,
        ],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.SUITABILITY,
            topic=TopicCode.FRAGRANCE,
            observations=(
                SemanticObservation(
                    code=ObservationCode.REFERENCE_UNCLEAR,
                    present=True,
                ),
            ),
            references=(
                SemanticReference(
                    kind="current_item",
                    raw_text="这个",
                    start=0,
                    end=2,
                ),
            ),
            clarification_hint=ClarificationCode.REFERENCE,
        ),
    )

    assert merged.references == [reference]
    assert merged.uncertainties == []
    assert not any(
        trace.resolution == "clarify"
        for trace in merged.signal_trace
        if (
            trace.field == "clarification_hint"
            or trace.field
            == "observation.reference_unclear"
        )
    )


def test_semantic_reference_wrong_unique_offset_is_rebound() -> None:
    message = "第二款香水"
    merged = merge_intent_signals(
        message=message,
        exact_constraints=[
            CategoryDraft(value=TopicCode.FRAGRANCE),
        ],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.FOLLOWUP,
            topic=TopicCode.FRAGRANCE,
            references=(
                SemanticReference(
                    kind="candidate_ordinal",
                    ordinal=2,
                    raw_text="第二款",
                    start=3,
                    end=6,
                ),
            ),
        ),
        context=SemanticContext(
            conversation_version=2,
            active_topic=TopicCode.FRAGRANCE,
            visible_candidate_count=3,
            confirmed_profile_fields=(),
        ),
    )

    assert merged.references == [
        ReferenceDraft(
            kind="candidate_ordinal",
            ordinal=2,
            source_span=SourceSpan(start=0, end=3),
        )
    ]
    assert not merged.uncertainties


def test_semantic_reference_wrong_repeated_span_fails_closed() -> None:
    message = "第二款和第二款香水"
    merged = merge_intent_signals(
        message=message,
        exact_constraints=[
            CategoryDraft(value=TopicCode.FRAGRANCE),
        ],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.FOLLOWUP,
            topic=TopicCode.FRAGRANCE,
            references=(
                SemanticReference(
                    kind="candidate_ordinal",
                    ordinal=2,
                    raw_text="第二款",
                    start=1,
                    end=4,
                ),
            ),
        ),
        context=SemanticContext(
            conversation_version=2,
            active_topic=TopicCode.FRAGRANCE,
            visible_candidate_count=3,
            confirmed_profile_fields=(),
        ),
    )

    assert merged.references == []
    assert any(
        issue.code == "ambiguous_reference"
        for issue in merged.uncertainties
    )


def test_semantic_candidate_ordinal_requires_visible_candidate() -> None:
    merged = merge_intent_signals(
        message="第三款怎么样",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.FOLLOWUP,
            topic=TopicCode.FRAGRANCE,
            references=(
                SemanticReference(
                    kind="candidate_ordinal",
                    ordinal=3,
                    raw_text="第三款",
                    start=0,
                    end=3,
                ),
            ),
        ),
        context=SemanticContext(
            conversation_version=2,
            active_topic=TopicCode.FRAGRANCE,
            visible_candidate_count=2,
            confirmed_profile_fields=(),
        ),
    )

    assert merged.references == []
    assert any(
        issue.code == "ambiguous_candidate_reference"
        for issue in merged.uncertainties
    )
    task = _plan_with_explicit_test_outcome(merged)
    assert task.clarification == (
        "你说的商品序号不在当前展示范围里，请重新确认。"
    )


def test_semantic_current_item_requires_focused_candidate() -> None:
    merged = merge_intent_signals(
        message="这个怎么样",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.FOLLOWUP,
            topic=TopicCode.FRAGRANCE,
            references=(
                SemanticReference(
                    kind="current_item",
                    raw_text="这个",
                    start=0,
                    end=2,
                ),
            ),
        ),
        context=SemanticContext(
            conversation_version=2,
            active_topic=TopicCode.FRAGRANCE,
            visible_candidate_count=1,
            focused_candidate_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )

    assert merged.references == []
    assert any(
        issue.code == "ambiguous_reference"
        for issue in merged.uncertainties
    )
    task = _plan_with_explicit_test_outcome(merged)
    assert task.clarification == (
        "目前没有唯一对应的商品，请直接说商品名或序号。"
    )


def test_semantic_current_batch_requires_visible_products() -> None:
    merged = merge_intent_signals(
        message="这些怎么样",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.FOLLOWUP,
            topic=TopicCode.FRAGRANCE,
            references=(
                SemanticReference(
                    kind="current_batch",
                    raw_text="这些",
                    start=0,
                    end=2,
                ),
            ),
        ),
        context=SemanticContext(
            conversation_version=2,
            active_topic=TopicCode.FRAGRANCE,
            visible_candidate_count=0,
            focused_candidate_ordinal=None,
            confirmed_profile_fields=(),
        ),
    )

    assert merged.references == []
    task = _plan_with_explicit_test_outcome(merged)
    assert task.clarification == (
        "目前没有前面那组商品可以继续查看，请先发起一次推荐。"
    )


def test_semantic_image_ordinal_requires_existing_image() -> None:
    merged = merge_intent_signals(
        message="第一张呢",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.FOLLOWUP,
            topic=None,
            references=(
                SemanticReference(
                    kind="image_ordinal",
                    ordinal=1,
                    raw_text="第一张",
                    start=0,
                    end=3,
                ),
            ),
        ),
        context=SemanticContext(
            conversation_version=2,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            confirmed_profile_fields=(),
        ),
    )

    assert merged.references == []
    assert any(
        issue.code == "ambiguous_image_reference"
        for issue in merged.uncertainties
    )


def test_exact_image_ordinal_vetoes_stale_semantic_clarification() -> None:
    message = "第一张呢"
    constraints, issues = parse_exact_constraints(message)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=constraints,
        exact_issues=issues,
        semantic=_proposal(
            goal=UnderstandingGoal.CLARIFICATION,
            topic=None,
            observations=(
                SemanticObservation(
                    code=ObservationCode.REFERENCE_UNCLEAR,
                    present=True,
                ),
            ),
            clarification_hint=ClarificationCode.REFERENCE,
        ),
        context=SemanticContext(
            conversation_version=2,
            active_topic=None,
            visible_candidate_count=0,
            image_count=1,
            confirmed_profile_fields=(),
        ),
    )

    assert merged.goal is UnderstandingGoal.FOLLOWUP
    assert [
        (reference.kind, reference.ordinal)
        for reference in merged.references
    ] == [("image_ordinal", 1)]
    assert merged.uncertainties == []


def test_missing_required_reference_keeps_typed_reference_clarification(
) -> None:
    merged = merge_intent_signals(
        message="这个适合我吗",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.SUITABILITY,
            topic=TopicCode.FRAGRANCE,
            clarification_hint=ClarificationCode.REFERENCE,
        ),
    )

    assert merged.references == []
    assert merged.uncertainties
    assert any(
        trace.field == "clarification_hint"
        and trace.semantic_value == ClarificationCode.REFERENCE.value
        and trace.resolution == "clarify"
        for trace in merged.signal_trace
    )


def test_product_mention_is_bound_to_exact_current_message_span() -> None:
    message = "对比安热沙智感倍护防晒乳液GB和理肤泉防晒"
    text = "安热沙智感倍护防晒乳液GB"
    start = message.index(text)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.COMPARISON,
            topic=TopicCode.SUNSCREEN,
            product_mentions=(
                SemanticProductMention(
                    text=text,
                    start=start,
                    end=start + len(text),
                ),
            ),
        ),
    )

    assert [
        item.model_dump()
        for item in merged.product_mentions
    ] == [
        {
            "text": text,
            "source_span": {
                "start": start,
                "end": start + len(text),
            },
        }
    ]


def test_product_mention_with_wrong_offset_rebinds_unique_exact_text() -> None:
    merged = merge_intent_signals(
        message="理肤泉防晒适合我吗",
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.SUITABILITY,
            topic=TopicCode.SUNSCREEN,
            product_mentions=(
                SemanticProductMention(
                    text="理肤泉防晒",
                    start=1,
                    end=6,
                ),
            ),
        ),
    )

    assert len(merged.product_mentions) == 1
    mention = merged.product_mentions[0]
    assert mention.text == "理肤泉防晒"
    assert mention.source_span == SourceSpan(
        start=0,
        end=len(mention.text),
    )
    assert merged.uncertainties == []


def test_product_mention_wrong_offset_with_repeated_text_fails_closed(
) -> None:
    merged = merge_intent_signals(
        message="理肤泉防晒和理肤泉防晒",
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        exact_issues=[],
        semantic=_proposal(
            goal=UnderstandingGoal.COMPARISON,
            topic=TopicCode.SUNSCREEN,
            product_mentions=(
                SemanticProductMention(
                    text="理肤泉防晒",
                    start=1,
                    end=6,
                ),
            ),
        ),
    )

    assert merged.product_mentions == []
    assert any(
        issue.code == "ambiguous_reference"
        for issue in merged.uncertainties
    )


def test_validated_number_candidate_fills_only_open_budget_slot() -> None:
    message = "预算三百以内的防晒"
    raw_text = "三百以内"
    start = message.index(raw_text)
    candidate = SemanticNumberCandidate(
        relation="maximum",
        raw_text=raw_text,
        start=start,
        end=start + len(raw_text),
        minimum=None,
        maximum="300",
    )
    merged = merge_intent_signals(
        message=message,
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        exact_issues=[],
        semantic=_proposal(
            topic=TopicCode.SUNSCREEN,
            number_candidates=(candidate,),
        ),
    )

    budgets = [
        item
        for item in merged.exact_constraints
        if isinstance(item, BudgetDraft)
    ]
    assert budgets == [
        BudgetDraft(
            minimum=None,
            maximum=Decimal("300"),
        )
    ]
    assert any(
        trace.field == "number_candidate.budget"
        and trace.resolution == "semantic_fills"
        and trace.exact_value is None
        for trace in merged.signal_trace
    )


def test_exact_budget_wins_over_conflicting_number_candidate() -> None:
    message = "500以内，不是三百以内"
    raw_text = "三百以内"
    start = message.index(raw_text)
    merged = merge_intent_signals(
        message=message,
        exact_constraints=[
            BudgetDraft(
                minimum=None,
                maximum=Decimal("500"),
            ),
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        exact_issues=[],
        semantic=_proposal(
            topic=TopicCode.SUNSCREEN,
            number_candidates=(
                SemanticNumberCandidate(
                    relation="maximum",
                    raw_text=raw_text,
                    start=start,
                    end=start + len(raw_text),
                    minimum=None,
                    maximum="300",
                ),
            ),
        ),
    )

    budgets = [
        item
        for item in merged.exact_constraints
        if isinstance(item, BudgetDraft)
    ]
    assert budgets == [
        BudgetDraft(
            minimum=None,
            maximum=Decimal("500"),
        )
    ]
    assert any(
        trace.field == "number_candidate.budget"
        and trace.resolution == "exact_wins"
        and trace.exact_value == ":500"
        for trace in merged.signal_trace
    )


def test_exact_budget_ignores_stale_unknown_budget_signals() -> None:
    merged = merge_intent_signals(
        message="500以内适合油敏肌的防晒",
        exact_constraints=[
            BudgetDraft(
                minimum=None,
                maximum=Decimal("500"),
            ),
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        exact_issues=[],
        semantic=_proposal(
            topic=TopicCode.SUNSCREEN,
            observations=(
                SemanticObservation(
                    code=ObservationCode.CURRENT_BUDGET_UNKNOWN,
                    present=True,
                    qualifier=None,
                ),
            ),
            clarification_hint=ClarificationCode.BUDGET,
        ),
    )

    assert merged.uncertainties == []
    assert _plan_with_explicit_test_outcome(merged).mode == "recommend"
    assert {
        trace.field
        for trace in merged.signal_trace
        if trace.resolution == "ignored_stale"
    } >= {
        "clarification_hint",
        "observation.current_budget_unknown",
    }
