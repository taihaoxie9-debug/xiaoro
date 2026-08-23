"""Slice: 会话/画像上下文解析。

从 ConversationSnapshot（会话确认信息）与已确认长期画像构造一个
最小化、typed、脱敏的 SemanticContext。它只暴露闭合的字段"名"，
绝不放入商品事实、候选 ID、原始文本或任意 value。

优先级（见设计 3.4 / 3.11）：本轮明确 > 会话确认 > 长期画像 > 默认。
本解析器只提供"会话确认 + 长期画像"这一路的只补空信号；本轮明确的
覆盖由合并器负责，绝不在此覆盖本轮。
"""
from __future__ import annotations

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    PendingClarificationSlot,
    PendingReplySlot,
    RecommendationQueryContext,
)
from app.guide.feedback.profile_policy import (
    ResolvedProfileContext,
    has_confirmed_profile_provenance,
)
from app.guide.understanding.contracts import (
    ContextConstraintSignal,
    ExclusionDraft,
    ImageBundle,
    SkinDraft,
    SkinTarget,
    TopicCode,
)
from app.guide.understanding.semantic_contracts import (
    ActiveDialogue,
    ActiveConstraintKind,
    ConfirmedProfileField,
    SemanticContext,
)
from app.guide.intent.responsibility_matrix import (
    decision_for_responsibility,
)


_PROFILE_FIELD_BY_NAME: dict[str, ConfirmedProfileField] = {
    "skin_type": ConfirmedProfileField.SKIN_TYPE,
    "skin_concern": ConfirmedProfileField.SKIN_CONCERN,
    "ingredient_exclusion": ConfirmedProfileField.INGREDIENT_EXCLUSION,
    "preferred_brand": ConfirmedProfileField.PREFERRED_BRAND,
    "preferred_category": ConfirmedProfileField.PREFERRED_CATEGORY,
}
_PROFILE_FIELD_ORDER: tuple[ConfirmedProfileField, ...] = (
    ConfirmedProfileField.SKIN_TYPE,
    ConfirmedProfileField.SKIN_CONCERN,
    ConfirmedProfileField.INGREDIENT_EXCLUSION,
    ConfirmedProfileField.PREFERRED_BRAND,
    ConfirmedProfileField.PREFERRED_CATEGORY,
)
_ACTIVE_CONSTRAINT_ORDER: tuple[ActiveConstraintKind, ...] = (
    ActiveConstraintKind.BUDGET,
    ActiveConstraintKind.CATEGORY,
    ActiveConstraintKind.SKIN,
    ActiveConstraintKind.INGREDIENT_EXCLUSION,
    ActiveConstraintKind.EFFICACY,
)


def resolve_semantic_context(
    *,
    conversation_version: int,
    snapshot: ConversationSnapshot | None,
    profile_context: ResolvedProfileContext | None = None,
    image_bundle: ImageBundle | None = None,
) -> SemanticContext:
    """Build a minimal typed SemanticContext without product facts."""
    if (
        not isinstance(conversation_version, int)
        or isinstance(conversation_version, bool)
        or conversation_version < 0
    ):
        raise ValueError("conversation_version must be a non-negative integer")
    if snapshot is not None and not isinstance(
        snapshot,
        ConversationSnapshot,
    ):
        raise TypeError("snapshot must be a ConversationSnapshot or None")
    if profile_context is not None and not isinstance(
        profile_context,
        ResolvedProfileContext,
    ):
        raise TypeError(
            "profile_context must be a ResolvedProfileContext or None"
        )
    if image_bundle is not None and not isinstance(
        image_bundle,
        ImageBundle,
    ):
        raise TypeError("image_bundle must be an ImageBundle or None")

    recommendation_slot = (
        snapshot.recommendation_slot
        if snapshot is not None
        else None
    )
    query = (
        recommendation_slot.query_context
        if recommendation_slot is not None
        else None
    )
    active_topic = _active_topic(query)
    active_candidates = ()
    if snapshot is not None and snapshot.active_focus is not None:
        if (
            snapshot.active_focus.slot == "recommendation"
            and snapshot.recommendation_slot is not None
        ):
            active_candidates = snapshot.recommendation_slot.candidates
        elif (
            snapshot.active_focus.slot == "product"
            and snapshot.product_slot is not None
        ):
            active_candidates = snapshot.product_slot.products
        elif snapshot.recommendation_slot is not None:
            active_candidates = snapshot.recommendation_slot.candidates
    visible_candidate_count = (
        min(len(active_candidates), 4)
    )
    confirmed_fields = _confirmed_profile_fields(
        query=query,
        profile_context=profile_context,
    )
    confirmed_images = (
        snapshot.image_slot.confirmed_products
        if (
            snapshot is not None
            and snapshot.image_slot is not None
        )
        else ()
    )
    confirmed_focus_ordinals = (
        [
            item.image_ordinal
            for item in confirmed_images
            if (
                snapshot is not None
                and snapshot.image_slot is not None
                and item.image_ordinal
                == snapshot.image_slot.focused_image_ordinal
            )
        ]
        if confirmed_images
        else []
    )
    focused_candidate_ordinal = (
        snapshot.recommendation_slot.focused_candidate_ordinal
        if snapshot is not None
        and snapshot.recommendation_slot is not None
        else None
    )
    current_product_id = (
        snapshot.product_slot.focused_product_id
        if snapshot is not None
        and snapshot.product_slot is not None
        else None
    )
    return SemanticContext(
        conversation_version=conversation_version,
        active_topic=active_topic,
        active_dialogue=_active_dialogue(snapshot),
        active_recommendation_mode=(
            query.recommendation_mode
            if (
                query is not None
                and query.recommendation_mode_basis is not None
            )
            else None
        ),
        active_recommendation_mode_basis=(
            query.recommendation_mode_basis
            if query is not None
            else None
        ),
        active_recommendation_count=(
            query.recommendation_count
            if (
                query is not None
                and query.recommendation_mode_basis is not None
            )
            else None
        ),
        awaiting_reply=_awaiting_reply(snapshot),
        visible_candidate_count=visible_candidate_count,
        focused_candidate_ordinal=focused_candidate_ordinal,
        current_item_available=(
            snapshot is not None
            and current_product_id is not None
        ),
        image_count=(
            len(image_bundle.images)
            if image_bundle is not None
            else len(confirmed_images)
        ),
        confirmed_image_ordinals=(
            ()
            if image_bundle is not None
            else tuple(
                item.image_ordinal
                for item in confirmed_images
            )
        ),
        focused_image_ordinal=(
            image_bundle.focused_image_ordinal
            if image_bundle is not None
            else (
                confirmed_focus_ordinals[0]
                if len(confirmed_focus_ordinals) == 1
                else None
            )
        ),
        active_constraint_kinds=_active_constraint_kinds(query),
        confirmed_profile_fields=confirmed_fields,
        pending_clarification=(
            snapshot.reply_slot.value.gap
            if snapshot is not None
            and isinstance(snapshot.reply_slot, PendingReplySlot)
            else (
                snapshot.reply_slot.value.gap
                if snapshot is not None
                and isinstance(
                    snapshot.reply_slot,
                    PendingClarificationSlot,
                )
                else None
            )
        ),
    )


def resolve_context_constraint_signals(
    *,
    snapshot: ConversationSnapshot | None,
    profile_context: ResolvedProfileContext | None = None,
) -> tuple[ContextConstraintSignal, ...]:
    """Resolve confirmed profile values without exposing them to the model.

    A prior recommendation query is only authoritative for closed followup and
    revision operations. It must not silently constrain a fresh recommendation.
    """
    if snapshot is not None and not isinstance(
        snapshot,
        ConversationSnapshot,
    ):
        raise TypeError("snapshot must be a ConversationSnapshot or None")
    if profile_context is not None and not isinstance(
        profile_context,
        ResolvedProfileContext,
    ):
        raise TypeError(
            "profile_context must be a ResolvedProfileContext or None"
        )

    del snapshot
    signals: list[ContextConstraintSignal] = []
    if profile_context is None:
        return tuple(signals)

    for value in profile_context.values:
        if not has_confirmed_profile_provenance(value):
            continue
        source = (
            "profile"
            if value.source == "long_term_profile"
            else "session"
        )
        if value.field == "skin_type":
            try:
                skin = SkinTarget(value.value)
            except ValueError:
                continue
            signals.append(
                ContextConstraintSignal(
                    source=source,
                    constraint=SkinDraft(value=skin),
                )
            )
        elif value.field == "ingredient_exclusion":
            signals.append(
                ContextConstraintSignal(
                    source=source,
                    constraint=ExclusionDraft(value=value.value),
                )
            )
    return tuple(signals)


def _active_topic(
    query: RecommendationQueryContext | None,
) -> TopicCode | None:
    if query is None:
        return None
    return TopicCode(query.category)


def _active_dialogue(
    snapshot: ConversationSnapshot | None,
) -> ActiveDialogue | None:
    if snapshot is None:
        return None
    if (
        snapshot.reply_slot is not None
    ):
        return "clarification"
    if snapshot.active_owner is None:
        return None
    return decision_for_responsibility(
        snapshot.active_owner
    ).processor


def _awaiting_reply(snapshot: ConversationSnapshot | None) -> bool:
    if snapshot is None:
        return False
    if (
        snapshot.reply_slot is not None
    ):
        return True
    if _active_dialogue(snapshot) != "consultation":
        return False
    consultation_slot = snapshot.consultation_slot
    if consultation_slot is None:
        return False
    consultation = consultation_slot.state
    if consultation.medical_escalation is not None:
        return False
    assessment = consultation.confirmable_assessment
    return (
        assessment is None
        or not assessment.conclusion.confirmed_by_user
    )


def _active_constraint_kinds(
    query: RecommendationQueryContext | None,
) -> tuple[ActiveConstraintKind, ...]:
    if query is None:
        return ()
    present = {ActiveConstraintKind.CATEGORY}
    if (
        query.budget_minimum is not None
        or query.budget_maximum is not None
    ):
        present.add(ActiveConstraintKind.BUDGET)
    if query.skin is not None:
        present.add(ActiveConstraintKind.SKIN)
    if query.exclusions:
        present.add(ActiveConstraintKind.INGREDIENT_EXCLUSION)
    if query.efficacy is not None:
        present.add(ActiveConstraintKind.EFFICACY)
    return tuple(
        kind
        for kind in _ACTIVE_CONSTRAINT_ORDER
        if kind in present
    )


def _confirmed_profile_fields(
    *,
    query: RecommendationQueryContext | None,
    profile_context: ResolvedProfileContext | None,
) -> tuple[ConfirmedProfileField, ...]:
    present: set[ConfirmedProfileField] = set()
    # Session-confirmed condition fields (only field names, never values).
    if query is not None:
        if query.skin is not None:
            present.add(ConfirmedProfileField.SKIN_TYPE)
        if query.exclusions:
            present.add(ConfirmedProfileField.INGREDIENT_EXCLUSION)
    # Long-term profile only fills field names that are still empty.
    if profile_context is not None:
        for value in profile_context.values:
            if not has_confirmed_profile_provenance(value):
                continue
            field = _PROFILE_FIELD_BY_NAME.get(value.field)
            if field is not None:
                present.add(field)
    return tuple(
        field
        for field in _PROFILE_FIELD_ORDER
        if field in present
    )


__all__ = [
    "resolve_context_constraint_signals",
    "resolve_semantic_context",
]
