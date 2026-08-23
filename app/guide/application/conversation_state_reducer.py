from __future__ import annotations

from app.guide.application.execution_contracts import (
    ClarificationLaneState,
    ConversationStateDelta,
    ImageLaneState,
    KnowledgeLaneState,
    ProductLaneState,
    ProfileLanePatch,
    RecommendationLaneState,
    TurnIdentity,
)
from app.guide.feedback.contracts import (
    ConsultationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    KnowledgeSlotState,
    PendingClarificationSlot,
    PendingReplySlot,
    ProductSlotState,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import ActiveFocus
from app.guide.feedback.ports import (
    ConversationStateConflict,
    validate_conversation_state_transition,
)
from app.guide.feedback.session_profile import (
    SessionProfile,
    reduce_session_profile,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.unified_turn_router import UnifiedRouteDecision


def reduce_conversation_state(
    *,
    current: ConversationSnapshot | None,
    turn_identity: TurnIdentity,
    decision: UnifiedRouteDecision,
    delta: ConversationStateDelta,
) -> ConversationSnapshot:
    if current is not None and type(current) is not ConversationSnapshot:
        raise TypeError(
            "current must be ConversationSnapshot or None"
        )
    if type(turn_identity) is not TurnIdentity:
        raise TypeError("turn_identity must be an exact TurnIdentity")
    if type(decision) is not UnifiedRouteDecision:
        raise TypeError(
            "decision must be an exact UnifiedRouteDecision"
        )
    if type(delta) is not ConversationStateDelta:
        raise TypeError(
            "delta must be an exact ConversationStateDelta"
        )
    validated_current = (
        ConversationSnapshot.model_validate(
            current.model_dump(mode="python"),
            strict=True,
        )
        if current is not None
        else None
    )
    if (
        validated_current is not None
        and validated_current.session_id != turn_identity.session_id
    ):
        raise ConversationStateConflict(turn_identity.session_id)

    _validate_lane_authority(decision=decision, delta=delta)
    recommendation_slot = _apply_recommendation(
        _current_slot(validated_current, "recommendation_slot"),
        delta,
    )
    product_slot = _apply_product(
        _current_slot(validated_current, "product_slot"),
        recommendation_slot,
        delta,
    )
    image_slot = _apply_image(
        _current_slot(validated_current, "image_slot"),
        delta,
    )
    consultation_slot = _apply_consultation(
        _current_slot(validated_current, "consultation_slot"),
        delta,
    )
    knowledge_slot = _apply_knowledge(
        _current_slot(validated_current, "knowledge_slot"),
        delta,
    )
    reply_slot = _apply_reply(
        _current_slot(validated_current, "reply_slot"),
        delta,
    )
    _validate_delta_bindings(decision=decision, delta=delta)
    profile_owner, session_profile = _apply_profile(
        current=validated_current,
        declared_owner=delta.profile_owner,
        patch=delta.profile,
        version=(
            validated_current.version + 1
            if validated_current is not None
            else 1
        ),
    )
    slots = {
        "recommendation": recommendation_slot,
        "product": product_slot,
        "image": image_slot,
        "consultation": consultation_slot,
        "knowledge": knowledge_slot,
        "reply": reply_slot,
    }
    active_focus = _active_focus(
        current=validated_current,
        decision=decision,
        delta=delta,
        slots=slots,
    )
    replacement = ConversationSnapshot(
        session_id=turn_identity.session_id,
        version=(
            validated_current.version + 1
            if validated_current is not None
            else 1
        ),
        profile_owner=profile_owner,
        session_profile=session_profile,
        active_owner=decision.responsibility,
        active_focus=active_focus,
        recommendation_slot=recommendation_slot,
        product_slot=product_slot,
        image_slot=image_slot,
        consultation_slot=consultation_slot,
        knowledge_slot=knowledge_slot,
        reply_slot=reply_slot,
    )
    validate_conversation_state_transition(
        validated_current,
        replacement,
    )
    _validate_return_authority(
        current=validated_current,
        decision=decision,
    )
    return replacement


def _current_slot(current, name: str):
    return getattr(current, name) if current is not None else None


def _apply_recommendation(current, delta):
    mutation = delta.recommendation
    if mutation.action == "preserve":
        return current
    if mutation.action == "clear":
        return None
    value = mutation.value
    if type(value) is not RecommendationLaneState:
        raise TypeError(
            "recommendation replacement must be RecommendationLaneState"
        )
    return RecommendationSlotState(
        query_context=value.query_context,
        candidates=value.candidates,
        empty_result=value.empty_result,
        focused_candidate_ordinal=value.focused_candidate_ordinal,
    )


def _apply_product(current, recommendation_slot, delta):
    mutation = delta.product
    if mutation.action == "preserve":
        return current
    if mutation.action == "clear":
        return None
    value = mutation.value
    if type(value) is not ProductLaneState:
        raise TypeError(
            "product replacement must be ProductLaneState"
        )
    products = value.candidates
    focused_product_id = value.current_product_id
    if not products:
        candidate = _candidate_for_product(
            focused_product_id,
            current=current,
            recommendation_slot=recommendation_slot,
        )
        products = (candidate,)
    return ProductSlotState(
        products=products,
        focused_product_id=focused_product_id,
        focused_evidence_ids=value.focused_evidence_ids,
    )


def _candidate_for_product(
    product_id: int | None,
    *,
    current: ProductSlotState | None,
    recommendation_slot: RecommendationSlotState | None,
) -> DisplayedCandidateRef:
    if product_id is None:
        raise ValueError("product replacement requires a product")
    candidates = (
        *(current.products if current is not None else ()),
        *(
            recommendation_slot.candidates
            if recommendation_slot is not None
            else ()
        ),
    )
    for candidate in candidates:
        if candidate.product_id == product_id:
            return candidate.model_copy(update={"ordinal": 1})
    return DisplayedCandidateRef(
        product_id=product_id,
        ordinal=1,
        skin_match="not_applicable",
        matched_efficacies=(),
    )


def _apply_image(current, delta):
    mutation = delta.image
    if mutation.action == "preserve":
        return current
    if mutation.action == "clear":
        return None
    value = mutation.value
    if type(value) is not ImageLaneState:
        raise TypeError("image replacement must be ImageLaneState")
    focused_ordinal = (
        value.confirmed_products[0].image_ordinal
        if len(value.confirmed_products) == 1
        else None
    )
    return ImageSlotState(
        confirmed_products=value.confirmed_products,
        focused_image_ordinal=focused_ordinal,
    )


def _apply_consultation(current, delta):
    mutation = delta.consultation
    if mutation.action == "preserve":
        return current
    if mutation.action == "clear":
        return None
    if mutation.value is None:
        raise TypeError("consultation replacement requires state")
    return ConsultationSlotState(state=mutation.value)


def _apply_knowledge(current, delta):
    mutation = delta.knowledge
    if mutation.action == "preserve":
        return current
    if mutation.action == "clear":
        return None
    value = mutation.value
    if type(value) is not KnowledgeLaneState:
        raise TypeError(
            "knowledge replacement must be KnowledgeLaneState"
        )
    return KnowledgeSlotState(
        question=value.question,
        evidence_ids=value.focused_ids,
    )


def _apply_reply(current, delta):
    mutation = delta.clarification
    if mutation.action == "preserve":
        return current
    if mutation.action == "clear":
        return None
    value = mutation.value
    if type(value) is not ClarificationLaneState:
        raise TypeError(
            "clarification replacement must be ClarificationLaneState"
        )
    if value.pending_turn is not None:
        return PendingReplySlot(value=value.pending_turn)
    return PendingClarificationSlot(value=value.progress)


def _apply_profile(
    *,
    current: ConversationSnapshot | None,
    declared_owner,
    patch,
    version: int,
):
    owner = current.profile_owner if current is not None else None
    profile = current.session_profile if current is not None else None
    if (
        owner is not None
        and declared_owner is not None
        and owner != declared_owner
    ):
        raise ValueError("profile owner cannot change")
    owner = owner or declared_owner
    if patch.action == "preserve":
        return owner, profile
    if patch.action == "clear":
        return owner, None
    value = patch.value
    if type(value) is not ProfileLanePatch:
        raise TypeError(
            "profile replacement must be ProfileLanePatch"
        )
    if owner is not None and owner != value.profile_owner:
        raise ValueError("profile owner cannot change")
    return (
        value.profile_owner,
        reduce_session_profile(
            previous=profile or SessionProfile(),
            updates=value.updates,
            subject_scope=value.subject_scope,
            source_turn_id=value.source_turn_id,
            conversation_version=version,
        ).profile,
    )


def _active_focus(
    *,
    current: ConversationSnapshot | None,
    decision: UnifiedRouteDecision,
    delta: ConversationStateDelta,
    slots: dict[str, object],
) -> ActiveFocus:
    if delta.clarification.action == "replace":
        return ActiveFocus(slot="reply")
    preferred = {
        Responsibility.RECOMMENDATION: "recommendation",
        Responsibility.COMPARISON: "product",
        Responsibility.SINGLE_PRODUCT_SUITABILITY: "product",
        Responsibility.PRODUCT_KNOWLEDGE: "product",
        Responsibility.GENERAL_KNOWLEDGE: "knowledge",
        Responsibility.CONSULTATION: "consultation",
        Responsibility.IMAGE_IDENTITY: "image",
        Responsibility.CLARIFICATION: "reply",
        Responsibility.SAFETY_ESCALATION: "consultation",
    }[decision.responsibility]
    slot_name = preferred if slots.get(preferred) is not None else None
    if (
        decision.continuity == "return_to_focus"
        and decision.responsibility is Responsibility.RECOMMENDATION
        and slots.get("recommendation") is not None
    ):
        slot_name = "recommendation"
    if slot_name is None:
        source_slot = {
            "candidate_batch": "recommendation",
            "current_product": "product",
            "explicit_product": "product",
            "confirmed_image": "image",
            "knowledge_topic": "knowledge",
            "consultation": "consultation",
            "none": None,
        }[decision.focus_source]
        if source_slot is not None and slots.get(source_slot) is not None:
            slot_name = source_slot
    if slot_name is None:
        raise ValueError(
            "route decision has no corresponding physical state slot"
        )
    slot = slots[slot_name]
    if isinstance(slot, RecommendationSlotState):
        return ActiveFocus(
            slot="recommendation",
            ordinal=slot.focused_candidate_ordinal,
        )
    if isinstance(slot, ProductSlotState):
        return ActiveFocus(
            slot="product",
            object_id=slot.focused_product_id,
        )
    if isinstance(slot, ImageSlotState):
        return ActiveFocus(
            slot="image",
            object_id=(
                slot.confirmed_products[0].product_id
                if len(slot.confirmed_products) == 1
                else None
            ),
            ordinal=slot.focused_image_ordinal,
        )
    return ActiveFocus(slot=slot_name)


def _validate_lane_authority(
    *,
    decision: UnifiedRouteDecision,
    delta: ConversationStateDelta,
) -> None:
    if (
        delta.recommendation.action != "preserve"
        and decision.processor != "recommendation"
    ):
        raise ValueError(
            "recommendation lane mutation is not owned by "
            f"{decision.processor}"
        )
    if (
        delta.knowledge.action != "preserve"
        and decision.processor != "general_knowledge"
    ):
        raise ValueError(
            "knowledge lane mutation is not owned by "
            f"{decision.processor}"
        )
    if (
        delta.consultation.action != "preserve"
        and decision.processor
        not in {"consultation", "safety_escalation"}
    ):
        raise ValueError(
            "consultation lane mutation is not owned by "
            f"{decision.processor}"
        )
    if (
        delta.image.action != "preserve"
        and decision.focus_source != "confirmed_image"
    ):
        raise ValueError(
            "image lane mutation requires confirmed image authority"
        )
    if (
        delta.profile.action != "preserve"
        and decision.processor
        not in {"consultation", "safety_escalation"}
    ):
        raise ValueError(
            "profile lane mutation requires consultation authority"
        )


def _validate_delta_bindings(
    *,
    decision: UnifiedRouteDecision,
    delta: ConversationStateDelta,
) -> None:
    route_product_ids = tuple(
        binding.product_id
        for binding in decision.product_bindings
    )
    if delta.product.action == "replace":
        value = delta.product.value
        if type(value) is not ProductLaneState:
            raise TypeError(
                "product replacement must be ProductLaneState"
            )
        product_ids = (
            tuple(item.product_id for item in value.candidates)
            if value.candidates
            else (value.current_product_id,)
        )
        if route_product_ids != product_ids:
            raise ValueError(
                "product lane must match route decision bindings"
            )
    if (
        delta.image.action == "replace"
        and decision.processor in {"image_identity", "comparison"}
    ):
        value = delta.image.value
        if type(value) is not ImageLaneState:
            raise TypeError(
                "image replacement must be ImageLaneState"
            )
        if {
            item.product_id for item in value.confirmed_products
        } != set(route_product_ids):
            raise ValueError(
                "image lane must match route decision bindings"
            )


def _validate_return_authority(
    *,
    current: ConversationSnapshot | None,
    decision: UnifiedRouteDecision,
) -> None:
    if decision.continuity != "return_to_focus":
        return
    if current is None:
        raise ValueError(
            "return-to-focus lacks preserved authority"
        )
    bound_ids = {
        binding.product_id for binding in decision.product_bindings
    }
    recommendation_ids = {
        item.product_id
        for item in (
            current.recommendation_slot.candidates
            if current.recommendation_slot is not None
            else ()
        )
    }
    product_ids = {
        item.product_id
        for item in (
            current.product_slot.products
            if current.product_slot is not None
            else ()
        )
    }
    image_ids = {
        item.product_id
        for item in (
            current.image_slot.confirmed_products
            if current.image_slot is not None
            else ()
        )
    }
    has_authority = {
        "explicit_product": bool(bound_ids),
        "candidate_batch": bool(recommendation_ids)
        and (not bound_ids or bound_ids <= recommendation_ids),
        "current_product": bool(bound_ids)
        and bound_ids <= product_ids,
        "confirmed_image": bool(bound_ids)
        and bound_ids <= image_ids,
        "knowledge_topic": current.knowledge_slot is not None,
        "consultation": current.consultation_slot is not None,
        "none": False,
    }[decision.focus_source]
    if not has_authority:
        raise ValueError(
            "return-to-focus lacks preserved authority"
        )


__all__ = ["reduce_conversation_state"]
