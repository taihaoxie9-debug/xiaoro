from __future__ import annotations

from typing import Literal
import re

from pydantic import BaseModel, ConfigDict

from app.guide.feedback.contracts import (
    PendingBudgetRange,
    PendingRecommendationContext,
    PendingTurn,
    StoredConcept,
    StoredFacet,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    ConceptConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    FacetConstraint,
    InclusionConstraint,
    SkinConstraint,
    TaskPlan,
)
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    EfficacyTarget,
    ExclusionDraft,
    SkinTarget,
    StructuredUnderstanding,
    TopicCode,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide.understanding.colloquial_budget import (
    parse_colloquial_budget,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
)


PendingReplyKind = Literal[
    "affirm",
    "reject",
    "correct",
    "supplement",
    "replace_task",
    "ambiguous",
]

_AFFIRMATIONS = frozenset({
    "是",
    "是的",
    "对",
    "对的",
    "没错",
    "可以",
})
_REJECTIONS = frozenset({
    "不是",
    "不是的",
    "不对",
    "不行",
})
_TRAILING_PUNCTUATION = re.compile(r"[\s，,。.!！?？；;：:]+$")
_AFFIRMATIVE_PREFIX = re.compile(
    r"^\s*(?:是的|对的|没错|是|对)"
    r"(?:\s*[，,。.!！?？；;：:]|\s*(?:而且|并且|还要|再加))"
)
_PENDING_REJECTION_PREFIX = re.compile(
    r"^\s*(?:先\s*)?(?:"
    r"不是|不对|不要|不行|否|别确认|不确认|"
    r"停\s*[，,。.!！?？；;：:]\s*"
    r"(?:数|数字|预算|范围|价格)\s*(?:不对|错了?|理解错了?)|"
    r"(?:刚才的?|之前的?|这个|那个|该)?"
    r"(?:数|数字|预算|范围|价格)\s*"
    r"(?:不对|错了?|不是|理解错了?))"
)
_PENDING_AFFIRMATION_PREFIX = re.compile(
    r"^\s*(?:嗯|啊|好)?\s*[，,。.!！?？；;：:]*\s*(?:我\s*)?"
    r"(?:是的?|对的?|没错|可以|没问题|"
    r"确认(?:无误|(?:这个|该)?(?:预算|范围|数值))?|"
    r"同意(?:这个|该)?(?:预算|范围|数值)?|"
    r"是(?:这个|那个|该)(?:数|预算|范围)|"
    r"(?:这个|那个|该)(?:数|预算|范围|数值)"
    r"(?:没错|正确|可以))"
    r"(?=$|[\s，,。.!！?？；;：:]|就|我|继续)"
)


class PendingReply(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    kind: PendingReplyKind
    accepted_proposal: bool = False
    budget: PendingBudgetRange | None = None
    exclusions: tuple[str, ...] = ()
    replacement_category: str | None = None


def classify_pending_reply(
    *,
    message: str,
    pending: PendingTurn,
) -> PendingReply:
    if not isinstance(message, str):
        raise TypeError("pending reply message must be a string")
    if not isinstance(pending, PendingTurn):
        raise TypeError("pending must be a PendingTurn")
    if _PENDING_REJECTION_PREFIX.search(message):
        return PendingReply(kind="reject")
    constraints, issues = parse_exact_constraints(message)
    if not issues:
        categories = [
            item
            for item in constraints
            if isinstance(item, CategoryDraft)
        ]
        if categories and any(
            item.value.value != pending.resume_context.category
            for item in categories
        ):
            return PendingReply(
                kind="replace_task",
                replacement_category=categories[-1].value.value,
            )

        budgets = [
            item
            for item in constraints
            if isinstance(item, BudgetDraft)
        ]
        if budgets:
            corrected = budgets[-1]
            if (
                corrected.minimum is not None
                or corrected.maximum is not None
            ):
                return PendingReply(
                    kind="correct",
                    accepted_proposal=True,
                    budget=PendingBudgetRange(
                        minimum=corrected.minimum,
                        maximum=corrected.maximum,
                    ),
                )

        exclusions = tuple(dict.fromkeys(
            item.value
            for item in constraints
            if isinstance(item, ExclusionDraft)
        ))
        if exclusions and _AFFIRMATIVE_PREFIX.search(message):
            return PendingReply(
                kind="supplement",
                accepted_proposal=True,
                budget=pending.proposed_budget,
                exclusions=exclusions,
            )

    short_reply = _TRAILING_PUNCTUATION.sub("", message.strip())
    if (
        (
            short_reply in _AFFIRMATIONS
            or _PENDING_AFFIRMATION_PREFIX.search(message)
        )
        and pending.proposed_budget is not None
    ):
        return PendingReply(
            kind="affirm",
            accepted_proposal=True,
            budget=pending.proposed_budget,
        )
    if short_reply in _REJECTIONS:
        return PendingReply(kind="reject")
    return PendingReply(kind="ambiguous")


def resolve_semantic_pending_reply(
    *,
    meaning: TurnMeaning,
    understanding: StructuredUnderstanding,
    pending: PendingTurn,
) -> PendingReply:
    if type(meaning) is not TurnMeaning:
        raise TypeError("meaning must be an exact TurnMeaning")
    if type(understanding) is not StructuredUnderstanding:
        raise TypeError(
            "understanding must be an exact StructuredUnderstanding"
        )
    if type(pending) is not PendingTurn:
        raise TypeError("pending must be an exact PendingTurn")
    if not understanding.semantic_authoritative:
        raise ValueError(
            "semantic pending reply requires authoritative understanding"
        )

    hint = meaning.pending_response_hint
    budgets = [
        item
        for item in understanding.exact_constraints
        if isinstance(item, BudgetDraft)
    ]
    exclusions = tuple(dict.fromkeys(
        item.value
        for item in understanding.exact_constraints
        if isinstance(item, ExclusionDraft)
    ))
    categories = [
        item
        for item in understanding.exact_constraints
        if isinstance(item, CategoryDraft)
    ]
    if hint == "replace_task":
        replacement = next(
            (
                item.value.value
                for item in reversed(categories)
                if item.value.value
                != pending.resume_context.category
            ),
            None,
        )
        return (
            PendingReply(
                kind="replace_task",
                replacement_category=replacement,
            )
            if replacement is not None
            else PendingReply(kind="ambiguous")
        )
    if hint == "reject":
        return PendingReply(kind="reject")
    if hint == "correct":
        if not budgets:
            return PendingReply(kind="ambiguous")
        budget = budgets[-1]
        return PendingReply(
            kind="correct",
            accepted_proposal=True,
            budget=PendingBudgetRange(
                minimum=budget.minimum,
                maximum=budget.maximum,
            ),
        )
    if hint == "supplement":
        if pending.proposed_budget is None:
            return PendingReply(kind="ambiguous")
        return PendingReply(
            kind="supplement",
            accepted_proposal=True,
            budget=pending.proposed_budget,
            exclusions=exclusions,
        )
    if hint == "affirm" and pending.proposed_budget is not None:
        return PendingReply(
            kind="affirm",
            accepted_proposal=True,
            budget=pending.proposed_budget,
        )
    return PendingReply(kind="ambiguous")


def build_pending_turn(
    *,
    message: str,
    source_conversation_version: int,
    task: TaskPlan,
) -> PendingTurn | None:
    if (
        task.mode != "clarify"
        or task.clarification_code is None
        or task.clarification_code.value != "budget"
    ):
        return None
    proposed = parse_colloquial_budget(message)
    if (
        proposed is None
        or proposed.clarification is None
        or proposed.minimum is None
        or proposed.maximum is None
    ):
        return None
    category = next(
        (
            item
            for item in task.constraints
            if isinstance(item, CategoryConstraint)
        ),
        None,
    )
    if category is None:
        return None
    if any(
        value is None
        for value in (
            task.recommendation_mode,
            task.recommendation_mode_basis,
            task.recommendation_count,
        )
    ):
        raise ValueError(
            "pending recommendation requires complete outcome"
        )
    skin = next(
        (
            item
            for item in task.constraints
            if isinstance(item, SkinConstraint)
        ),
        None,
    )
    efficacy = next(
        (
            item
            for item in task.constraints
            if isinstance(item, EfficacyConstraint)
        ),
        None,
    )
    return PendingTurn(
        gap=task.clarification_code,
        attempts=1,
        source_conversation_version=source_conversation_version,
        source_message=message,
        expected_response="confirm_or_correct",
        resume_mode="recommendation",
        resume_context=PendingRecommendationContext(
            category=category.value.value,
            recommendation_mode=task.recommendation_mode,
            recommendation_mode_basis=task.recommendation_mode_basis,
            recommendation_count=task.recommendation_count,
            skin=skin.value.value if skin is not None else None,
            efficacy=(
                efficacy.value.value
                if efficacy is not None
                else None
            ),
            exclusions=tuple(
                item.value
                for item in task.constraints
                if isinstance(item, ExclusionConstraint)
            ),
            inclusions=tuple(
                item.value
                for item in task.constraints
                if isinstance(item, InclusionConstraint)
            ),
            facets=tuple(
                StoredFacet(
                    field_key=item.field_key,
                    value=item.value,
                )
                for item in task.constraints
                if isinstance(item, FacetConstraint)
            ),
            concepts=tuple(
                StoredConcept(
                    field_key=item.field_key,
                    concept_id=item.concept_id,
                    polarity=item.polarity,
                )
                for item in task.constraints
                if isinstance(item, ConceptConstraint)
            ),
            safety_sensitive=task.safety_sensitive,
        ),
        proposed_budget=PendingBudgetRange(
            minimum=proposed.minimum,
            maximum=proposed.maximum,
        ),
    )


def resume_pending_recommendation(
    *,
    pending: PendingTurn,
    reply: PendingReply,
) -> TaskPlan:
    if not reply.accepted_proposal or reply.budget is None:
        raise ValueError(
            "pending recommendation resume requires accepted budget"
        )
    context = pending.resume_context
    constraints = [
        CategoryConstraint(value=TopicCode(context.category)),
        BudgetConstraint(
            minimum=reply.budget.minimum,
            maximum=reply.budget.maximum,
        ),
    ]
    if context.skin is not None:
        constraints.append(
            SkinConstraint(value=SkinTarget(context.skin))
        )
    if context.efficacy is not None:
        constraints.append(
            EfficacyConstraint(value=EfficacyTarget(context.efficacy))
        )
    constraints.extend(
        ExclusionConstraint(value=value)
        for value in dict.fromkeys(
            (*context.exclusions, *reply.exclusions)
        )
    )
    constraints.extend(
        InclusionConstraint(value=value)
        for value in context.inclusions
    )
    constraints.extend(
        FacetConstraint(
            field_key=item.field_key,
            value=item.value,
        )
        for item in context.facets
    )
    constraints.extend(
        ConceptConstraint(
            field_key=item.field_key,
            concept_id=item.concept_id,
            polarity=item.polarity,
        )
        for item in context.concepts
    )
    return TaskPlan(
        mode="recommend",
        recommendation_mode=context.recommendation_mode,
        recommendation_mode_basis=context.recommendation_mode_basis,
        recommendation_count=context.recommendation_count,
        referenced_image_ids=[],
        constraints=constraints,
        references=[],
        product_mentions=[],
        product_ids=[],
        required_evidence=["canonical_product"],
        question_meaning=pending.source_message,
        safety_sensitive=context.safety_sensitive,
    )


__all__ = [
    "PendingReply",
    "PendingReplyKind",
    "build_pending_turn",
    "classify_pending_reply",
    "resolve_semantic_pending_reply",
    "resume_pending_recommendation",
]
