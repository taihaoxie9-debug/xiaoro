from __future__ import annotations

from app.guide.application.query_context import (
    query_context_to_constraints,
    task_plan_to_query_context,
)
from app.guide.intent.concept_preferences import (
    ConceptCatalogEntry,
    ConceptPreferenceCatalog,
    compile_concept_preferences,
)
from app.guide.intent.contracts import ConceptConstraint
from app.guide.intent.constraint_transitions import (
    reduce_constraint_state,
)
from app.guide.intent.task_planning import plan_task
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.contracts import (
    CategoryDraft,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnPreferenceCandidate,
)


def _catalog() -> ConceptPreferenceCatalog:
    return ConceptPreferenceCatalog(
        entries=(
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="efficacy",
                concept_id="efficacy.soothing",
            ),
            ConceptCatalogEntry(
                profile=CategoryProfile.SKINCARE,
                field_key="texture",
                concept_id="texture.refreshing",
            ),
        )
    )


def _candidate(
    *,
    field_key: str,
    concept_id: str | None,
    raw_text: str,
    polarity: str = "prefer",
    strength: str = "ordinary",
) -> TurnPreferenceCandidate:
    return TurnPreferenceCandidate.model_validate(
        {
            "field_key": field_key,
            "concept_id": concept_id,
            "raw_text": raw_text,
            "polarity": polarity,
            "strength": strength,
        },
        strict=True,
    )


def _plan(
    message: str,
    candidates: tuple[TurnPreferenceCandidate, ...],
):
    drafts = compile_concept_preferences(
        message=message,
        candidates=candidates,
        profile=CategoryProfile.SKINCARE,
        catalog=_catalog(),
    )
    return plan_task(
        StructuredUnderstanding(
            goal=UnderstandingGoal.RECOMMENDATION,
            topic=TopicCode.SKINCARE,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.SKINCARE),
            ],
            preference_drafts=list(drafts),
            semantic_proposals=[],
            signal_trace=[],
            references=[],
            image_references=[],
            uncertainties=[],
            confidence=1.0,
        )
    )


def test_reviewed_parent_concept_compiles_to_typed_constraint() -> None:
    task = _plan(
        "想镇定泛红",
        (
            _candidate(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                raw_text="镇定泛红",
            ),
        ),
    )

    concept = next(
        item
        for item in task.constraints
        if isinstance(item, ConceptConstraint)
    )
    assert concept.field_key == "efficacy"
    assert concept.concept_id == "efficacy.soothing"
    assert concept.polarity == "prefer"


def test_two_reviewed_concepts_compile_as_independent_slots() -> None:
    task = _plan(
        "清爽又舒缓",
        (
            _candidate(
                field_key="texture",
                concept_id="texture.refreshing",
                raw_text="清爽",
            ),
            _candidate(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                raw_text="舒缓",
            ),
        ),
    )

    assert [
        (item.field_key, item.concept_id)
        for item in task.constraints
        if isinstance(item, ConceptConstraint)
    ] == [
        ("texture", "texture.refreshing"),
        ("efficacy", "efficacy.soothing"),
    ]


def test_unsupported_descriptor_stays_out_of_structured_rank() -> None:
    task = _plan(
        "想要雨后潮湿木头感",
        (
            _candidate(
                field_key="texture",
                concept_id=None,
                raw_text="雨后潮湿木头感",
            ),
        ),
    )

    assert not any(
        isinstance(item, ConceptConstraint)
        for item in task.constraints
    )
    assert [
        (item.field_key, item.value, item.polarity)
        for item in task.free_descriptors
    ] == [
        ("texture", "雨后潮湿木头感", "prefer"),
    ]


def test_repeated_concept_creates_one_query_slot() -> None:
    task = _plan(
        "想镇定泛红，也要舒缓",
        (
            _candidate(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                raw_text="镇定泛红",
            ),
            _candidate(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                raw_text="舒缓",
            ),
        ),
    )

    assert sum(
        isinstance(item, ConceptConstraint)
        for item in task.constraints
    ) == 1


def test_avoid_polarity_is_preserved() -> None:
    task = _plan(
        "不要清爽挂的",
        (
            _candidate(
                field_key="texture",
                concept_id="texture.refreshing",
                raw_text="清爽",
                polarity="avoid",
            ),
        ),
    )

    concept = next(
        item
        for item in task.constraints
        if isinstance(item, ConceptConstraint)
    )
    assert concept.polarity == "avoid"


def test_safety_candidate_cannot_become_ordinary_soft_preference() -> None:
    task = _plan(
        "必须绝对舒缓",
        (
            _candidate(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                raw_text="绝对舒缓",
                strength="safety",
            ),
        ),
    )

    assert not any(
        isinstance(item, ConceptConstraint)
        for item in task.constraints
    )
    assert task.free_descriptors == []


def test_profile_inapplicable_concept_is_not_admitted_to_rank() -> None:
    drafts = compile_concept_preferences(
        message="想要舒缓防晒",
        candidates=(
            _candidate(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                raw_text="舒缓",
            ),
        ),
        profile=CategoryProfile.SUNCARE,
        catalog=_catalog(),
    )

    assert all(draft.preference_kind != "concept" for draft in drafts)
    assert drafts[0].preference_kind == "free_descriptor"


def test_concept_constraint_round_trips_and_survives_unmentioned_followup() -> None:
    task = _plan(
        "想要舒缓的",
        (
            _candidate(
                field_key="efficacy",
                concept_id="efficacy.soothing",
                raw_text="舒缓",
            ),
        ),
    )

    context = task_plan_to_query_context(task)
    restored = query_context_to_constraints(context)
    result = reduce_constraint_state(
        previous=context,
        current_constraints=(),
        revision_confirmations=(),
        goal=UnderstandingGoal.FOLLOWUP,
    )

    assert context.concepts[0].concept_id == "efficacy.soothing"
    assert any(
        isinstance(item, ConceptConstraint)
        and item.concept_id == "efficacy.soothing"
        for item in restored
    )
    assert any(
        isinstance(item, ConceptConstraint)
        and item.concept_id == "efficacy.soothing"
        for item in result.constraints
    )
