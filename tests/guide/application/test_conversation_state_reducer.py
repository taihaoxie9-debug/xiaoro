from __future__ import annotations

import inspect

import pytest

from app.guide.application.conversation_state_reducer import (
    reduce_conversation_state,
)
from app.guide.application.execution_contracts import (
    ClarificationLaneState,
    ConversationStateDelta,
    ImageLaneState,
    KnowledgeLaneState,
    LaneMutation,
    ProductLaneState,
    ProfileLanePatch,
    RecommendationLaneState,
    TurnIdentity,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    DisplayedCandidateRef,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.ports import ConversationStateConflict
from app.guide.feedback.session_profile import BaseSkinUpdate
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


def _identity(session_id: str = "state-reducer") -> TurnIdentity:
    return TurnIdentity(
        session_id=session_id,
        request_id="request_state_reducer_0001",
        turn_id="turn_state_reducer_0001",
    )


def _candidate(product_id: int, ordinal: int) -> DisplayedCandidateRef:
    return DisplayedCandidateRef(
        product_id=product_id,
        ordinal=ordinal,
        skin_match="unknown",
        matched_efficacies=(),
    )


def _query() -> RecommendationQueryContext:
    return RecommendationQueryContext(
        category="serum",
        recommendation_mode="explore",
        recommendation_mode_basis="broad_exploration",
        recommendation_count=2,
    )


def _recommendation_slot() -> RecommendationSlotState:
    return RecommendationSlotState(
        query_context=_query(),
        candidates=(_candidate(91, 1), _candidate(38, 2)),
        empty_result=False,
        focused_candidate_ordinal=1,
    )


def _snapshot(
    *,
    include_product: bool = False,
) -> ConversationSnapshot:
    product = (
        ProductSlotState(
            products=(_candidate(51, 1), _candidate(57, 2)),
            focused_product_id=None,
            focused_evidence_ids=(),
        )
        if include_product
        else None
    )
    return ConversationSnapshot(
        session_id="state-reducer",
        version=1,
        active_owner=(
            Responsibility.COMPARISON
            if product is not None
            else Responsibility.RECOMMENDATION
        ),
        active_focus=ActiveFocus(
            slot="product" if product is not None else "recommendation",
            ordinal=None if product is not None else 1,
        ),
        recommendation_slot=_recommendation_slot(),
        product_slot=product,
    )


def _decision(
    responsibility: Responsibility,
    *,
    continuity: str = "replace_task",
    focus_source: str = "none",
    product_ids: tuple[int, ...] = (),
) -> UnifiedRouteDecision:
    mapping = {
        Responsibility.RECOMMENDATION: (
            "recommendation",
            "recommendation",
        ),
        Responsibility.COMPARISON: ("comparison", "comparison"),
        Responsibility.PRODUCT_KNOWLEDGE: (
            "product_knowledge",
            "product_knowledge",
        ),
        Responsibility.GENERAL_KNOWLEDGE: (
            "general_knowledge",
            "general_knowledge",
        ),
        Responsibility.CONSULTATION: (
            "consultation",
            "consultation",
        ),
        Responsibility.IMAGE_IDENTITY: (
            "image_identity",
            "image_identity",
        ),
        Responsibility.CLARIFICATION: (
            "clarification",
            "clarification",
        ),
    }
    processor, mode = mapping[responsibility]
    return UnifiedRouteDecision(
        processor=processor,
        responsibility=responsibility,
        presentation_mode=mode,
        continuity=continuity,
        focus_source=focus_source,
        product_bindings=tuple(
            ResolvedProductBinding(
                product_id=product_id,
                source_text=f"product:{product_id}",
            )
            for product_id in product_ids
        ),
        clarification=(
            "请补充信息。"
            if responsibility is Responsibility.CLARIFICATION
            else None
        ),
        clarification_code=(
            ClarificationCode.GOAL
            if responsibility is Responsibility.CLARIFICATION
            else None
        ),
    )


def test_reducer_uses_text_free_turn_identity_input() -> None:
    assert tuple(TurnIdentity.model_fields) == (
        "session_id",
        "request_id",
        "turn_id",
    )
    assert tuple(inspect.signature(reduce_conversation_state).parameters) == (
        "current",
        "turn_identity",
        "decision",
        "delta",
    )


def test_reducer_constructs_snapshot_from_typed_delta() -> None:
    candidates = (_candidate(38, 1), _candidate(91, 2))
    reduced = reduce_conversation_state(
        current=None,
        turn_identity=_identity(),
        decision=_decision(Responsibility.RECOMMENDATION),
        delta=ConversationStateDelta(
            recommendation=LaneMutation[RecommendationLaneState](
                action="replace",
                value=RecommendationLaneState(
                    query_context=_query(),
                    candidates=candidates,
                ),
            )
        ),
    )

    assert reduced.version == 1
    assert reduced.active_owner is Responsibility.RECOMMENDATION
    assert reduced.active_focus.slot == "recommendation"
    assert reduced.recommendation_slot.candidates == candidates


def test_comparison_preserves_dormant_recommendation_slot_byte_for_byte(
) -> None:
    current = _snapshot()
    recommendation_bytes = (
        current.recommendation_slot.model_dump_json().encode("utf-8")
    )
    comparison = (_candidate(51, 1), _candidate(57, 2))

    reduced = reduce_conversation_state(
        current=current,
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.COMPARISON,
            focus_source="explicit_product",
            product_ids=(51, 57),
        ),
        delta=ConversationStateDelta(
            product=LaneMutation[ProductLaneState](
                action="replace",
                value=ProductLaneState(candidates=comparison),
            )
        ),
    )

    assert (
        reduced.recommendation_slot.model_dump_json().encode("utf-8")
        == recommendation_bytes
    )
    assert reduced.product_slot.products == comparison
    assert reduced.active_focus.slot == "product"


def test_return_after_comparison_reactivates_exact_recommendation_slot(
) -> None:
    current = _snapshot(include_product=True)
    recommendation_bytes = (
        current.recommendation_slot.model_dump_json().encode("utf-8")
    )
    product_bytes = current.product_slot.model_dump_json().encode("utf-8")

    reduced = reduce_conversation_state(
        current=current,
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.RECOMMENDATION,
            continuity="return_to_focus",
            focus_source="candidate_batch",
        ),
        delta=ConversationStateDelta(),
    )

    assert (
        reduced.recommendation_slot.model_dump_json().encode("utf-8")
        == recommendation_bytes
    )
    assert (
        reduced.product_slot.model_dump_json().encode("utf-8")
        == product_bytes
    )
    assert reduced.active_focus.slot == "recommendation"
    assert reduced.active_focus.ordinal == 1


def test_general_knowledge_preserves_product_and_recommendation_slots() -> None:
    current = _snapshot(include_product=True)
    reduced = reduce_conversation_state(
        current=current,
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.GENERAL_KNOWLEDGE,
            focus_source="knowledge_topic",
        ),
        delta=ConversationStateDelta(
            knowledge=LaneMutation[KnowledgeLaneState](
                action="replace",
                value=KnowledgeLaneState(
                    focused_ids=("a" * 64,),
                    question="防晒为什么需要补涂",
                    topic="防晒补涂",
                ),
            )
        ),
    )

    assert reduced.recommendation_slot == current.recommendation_slot
    assert reduced.product_slot == current.product_slot
    assert reduced.knowledge_slot.question == "防晒为什么需要补涂"
    assert reduced.active_focus.slot == "knowledge"


def test_clarification_uses_physical_reply_slot() -> None:
    reduced = reduce_conversation_state(
        current=_snapshot(),
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.CLARIFICATION,
            focus_source="none",
        ),
        delta=ConversationStateDelta(
            clarification=LaneMutation[ClarificationLaneState](
                action="replace",
                value=ClarificationLaneState(
                    progress=ClarificationProgress(
                        gap=ClarificationCode.GOAL,
                        attempts=1,
                    )
                ),
            )
        ),
    )

    assert reduced.reply_slot.kind == "clarification"
    assert reduced.reply_slot.value.gap is ClarificationCode.GOAL
    assert reduced.active_focus.slot == "reply"


def test_profile_patch_binds_owner_without_turn_payload() -> None:
    owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="profile-owner-0001",
    )
    consultation = ConsultationSubstate(
        started_at_conversation_version=1,
    )
    reduced = reduce_conversation_state(
        current=None,
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.CONSULTATION,
            focus_source="consultation",
        ),
        delta=ConversationStateDelta(
            consultation=LaneMutation[ConsultationSubstate](
                action="replace",
                value=consultation,
            ),
            profile=LaneMutation[ProfileLanePatch](
                action="replace",
                value=ProfileLanePatch(
                    profile_owner=owner,
                    updates=(
                        BaseSkinUpdate(
                            value="dry",
                            confirmation="confirmed",
                        ),
                    ),
                    subject_scope="self",
                    source_turn_id="turn_profile_owner_0001",
                ),
            ),
        ),
    )

    assert reduced.profile_owner == owner
    assert reduced.session_profile.base_skin.value == "dry"


def test_delta_product_bindings_must_match_route_decision() -> None:
    with pytest.raises(
        ValueError,
        match="product lane must match route decision bindings",
    ):
        reduce_conversation_state(
            current=None,
            turn_identity=_identity(),
            decision=_decision(
                Responsibility.PRODUCT_KNOWLEDGE,
                focus_source="explicit_product",
                product_ids=(38,),
            ),
            delta=ConversationStateDelta(
                product=LaneMutation[ProductLaneState](
                    action="replace",
                    value=ProductLaneState(current_product_id=39),
                )
            ),
        )


def test_image_lane_requires_confirmed_image_authority() -> None:
    with pytest.raises(
        ValueError,
        match="confirmed image authority",
    ):
        reduce_conversation_state(
            current=_snapshot(),
            turn_identity=_identity(),
            decision=_decision(Responsibility.RECOMMENDATION),
            delta=ConversationStateDelta(
                image=LaneMutation[ImageLaneState](
                    action="replace",
                    value=ImageLaneState(
                        confirmed_products=(
                            ConfirmedImageProductRef(
                                image_ordinal=1,
                                product_id=53,
                            ),
                        )
                    ),
                )
            ),
        )


def test_reducer_rejects_wrong_session() -> None:
    with pytest.raises(ConversationStateConflict):
        reduce_conversation_state(
            current=_snapshot(),
            turn_identity=_identity("other-session"),
            decision=_decision(Responsibility.RECOMMENDATION),
            delta=ConversationStateDelta(),
        )
