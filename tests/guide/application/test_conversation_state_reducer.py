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
    ImageSlotState,
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
from app.guide.intent.contracts import TaskPlan
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.presentation.contracts import CardDisplayContract
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
    processor_override: str | None = None,
    image_product_ids: tuple[int, ...] = (),
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
    if (
        responsibility is Responsibility.COMPARISON
        and focus_source == "confirmed_image"
    ):
        processor = "image_comparison"
    processor = processor_override or processor
    task_mode = {
        Responsibility.RECOMMENDATION: "recommend",
        Responsibility.COMPARISON: "comparison",
        Responsibility.PRODUCT_KNOWLEDGE: "knowledge",
        Responsibility.GENERAL_KNOWLEDGE: "knowledge",
        Responsibility.CONSULTATION: "followup",
        Responsibility.IMAGE_IDENTITY: "knowledge",
        Responsibility.CLARIFICATION: "clarify",
    }[responsibility]
    task_values = {
        "mode": task_mode,
        "referenced_image_ids": [],
        "constraints": [],
        "product_ids": list(product_ids),
        "required_evidence": (
            ["canonical_product"] if product_ids else []
        ),
        "question_meaning": "reducer layer contract",
    }
    if responsibility is Responsibility.RECOMMENDATION:
        task_values.update({
            "recommendation_mode": "explore",
            "recommendation_mode_basis": "broad_exploration",
            "recommendation_count": 2,
        })
    if responsibility is Responsibility.CLARIFICATION:
        task_values.update({
            "clarification": "请补充信息。",
            "clarification_code": ClarificationCode.GOAL,
        })
    public_intent_mode = (
        None
        if processor in {"consultation", "safety_escalation"}
        else (
            "image_compare"
            if processor == "image_comparison"
            else (
                "image_identity"
                if responsibility is Responsibility.IMAGE_IDENTITY
                else task_mode
            )
        )
    )
    return UnifiedRouteDecision(
        processor=processor,
        responsibility=responsibility,
        presentation_mode=mode,
        public_intent_mode=public_intent_mode,
        continuity=continuity,
        focus_source=focus_source,
        product_bindings=tuple(
            ResolvedProductBinding(
                product_id=product_id,
                source_text=(
                    f"image_ordinal:{index + 1}"
                    if (
                        processor == "image_comparison"
                        or responsibility is Responsibility.IMAGE_IDENTITY
                        or product_id in image_product_ids
                    )
                    else f"product:{product_id}"
                ),
                source_kind=(
                    "image_ordinal"
                    if (
                        processor == "image_comparison"
                        or responsibility is Responsibility.IMAGE_IDENTITY
                        or product_id in image_product_ids
                    )
                    else "explicit_product"
                ),
                source_ordinal=(
                    index + 1
                    if (
                        processor == "image_comparison"
                        or responsibility is Responsibility.IMAGE_IDENTITY
                        or product_id in image_product_ids
                    )
                    else None
                ),
            )
            for index, product_id in enumerate(product_ids)
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
        task_plan=TaskPlan.model_validate(
            task_values,
            strict=True,
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
        "card_display",
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


def test_reducer_binds_terminal_display_to_active_recommendation_slot(
) -> None:
    terminal_display = CardDisplayContract(
        mode="recommendation",
        visible_product_ids=(38, 91),
        max_cards=2,
        reason="recommendation",
    )

    reduced = reduce_conversation_state(
        current=None,
        turn_identity=_identity(),
        decision=_decision(Responsibility.RECOMMENDATION),
        delta=ConversationStateDelta(
            recommendation=LaneMutation[RecommendationLaneState](
                action="replace",
                value=RecommendationLaneState(
                    query_context=_query(),
                    candidates=(
                        _candidate(38, 1),
                        _candidate(91, 2),
                    ),
                ),
            )
        ),
        card_display=terminal_display,
    )

    assert not hasattr(reduced, "card_display")
    assert reduced.recommendation_slot.card_display == terminal_display


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
                value=ProductLaneState(products=comparison),
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


def test_general_knowledge_cannot_clear_product_slot() -> None:
    with pytest.raises(
        ValueError,
        match="product lane mutation is not owned",
    ):
        reduce_conversation_state(
            current=_snapshot(include_product=True),
            turn_identity=_identity(),
            decision=_decision(
                Responsibility.GENERAL_KNOWLEDGE,
                focus_source="none",
            ),
            delta=ConversationStateDelta(
                product=LaneMutation[ProductLaneState](
                    action="clear",
                    reason="unrelated task",
                ),
                knowledge=LaneMutation[KnowledgeLaneState](
                    action="replace",
                    value=KnowledgeLaneState(
                        focused_ids=("a" * 64,),
                        question="防晒为什么需要补涂",
                        topic="防晒补涂",
                    ),
                ),
            ),
        )


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
                    value=ProductLaneState(
                        products=(_candidate(39, 1),),
                        focused_product_id=39,
                    ),
                )
            ),
        )


def test_single_product_delta_carries_complete_display_state() -> None:
    product = DisplayedCandidateRef(
        product_id=39,
        ordinal=1,
        skin_match="matched",
        matched_efficacies=("repair",),
    )

    reduced = reduce_conversation_state(
        current=None,
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.PRODUCT_KNOWLEDGE,
            focus_source="explicit_product",
            product_ids=(39,),
        ),
        delta=ConversationStateDelta(
            product=LaneMutation[ProductLaneState](
                action="replace",
                value=ProductLaneState(
                    products=(product,),
                    focused_product_id=39,
                ),
            )
        ),
    )

    assert reduced.product_slot is not None
    assert reduced.product_slot.products == (product,)
    assert reduced.product_slot.focused_product_id == 39


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


def test_explicit_product_persists_current_upload_as_dormant_image_lane(
) -> None:
    confirmed_products = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
            source_bundle_id="bundle_" + "a" * 32,
            source_image_id="image_" + "b" * 32,
        ),
    )
    image_mutation = LaneMutation[ImageLaneState](
        action="replace",
        value=ImageLaneState(
            confirmed_products=confirmed_products,
            mutation_source="current_upload",
        ),
    )

    reduced = reduce_conversation_state(
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
                value=ProductLaneState(
                    products=(_candidate(38, 1),),
                    focused_product_id=38,
                ),
            ),
            image=image_mutation,
        ),
    )

    assert image_mutation.value is not None
    assert image_mutation.value.mutation_source == "current_upload"
    assert reduced.active_focus == ActiveFocus(
        slot="product",
        object_id=38,
    )
    assert reduced.image_slot is not None
    assert reduced.image_slot.confirmed_products == confirmed_products


def test_image_comparison_activates_current_image_batch_over_old_product(
) -> None:
    confirmed_products = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
        ),
        ConfirmedImageProductRef(
            image_ordinal=2,
            product_id=55,
        ),
    )
    current = _snapshot(include_product=True).model_copy(
        update={
            "image_slot": ImageSlotState(
                confirmed_products=confirmed_products,
            ),
        },
        deep=True,
    )

    reduced = reduce_conversation_state(
        current=current,
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.COMPARISON,
            focus_source="confirmed_image",
            product_ids=(53, 55),
        ),
        delta=ConversationStateDelta(
            image=LaneMutation[ImageLaneState](
                action="replace",
                value=ImageLaneState(
                    confirmed_products=confirmed_products,
                ),
            ),
        ),
    )

    assert reduced.active_focus == ActiveFocus(slot="image")
    assert reduced.product_slot == current.product_slot


def test_mixed_image_and_explicit_comparison_keeps_exact_terminal_display(
) -> None:
    image_product = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    current = _snapshot().model_copy(
        update={
            "image_slot": ImageSlotState(
                confirmed_products=(image_product,),
                focused_image_ordinal=1,
            ),
        },
        deep=True,
    )
    terminal_display = CardDisplayContract(
        mode="comparison",
        visible_product_ids=(53, 55),
        max_cards=2,
        reason="comparison",
    )

    reduced = reduce_conversation_state(
        current=current,
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.COMPARISON,
            focus_source="confirmed_image",
            product_ids=(53, 55),
            processor_override="comparison",
            image_product_ids=(53,),
        ),
        delta=ConversationStateDelta(
            product=LaneMutation[ProductLaneState](
                action="replace",
                value=ProductLaneState(
                    products=(
                        _candidate(53, 1),
                        _candidate(55, 2),
                    ),
                ),
            ),
        ),
        card_display=terminal_display,
    )

    assert reduced.active_focus == ActiveFocus(
        slot="image",
        object_id=53,
        ordinal=1,
    )
    assert reduced.image_slot.card_display == terminal_display
    assert reduced.product_slot.card_display is None
    assert terminal_display.visible_product_ids[-1] not in {
        item.product_id
        for item in reduced.image_slot.confirmed_products
    }


def test_product_terminal_cannot_reactivate_unrelated_preserved_slot() -> None:
    current = _snapshot(include_product=True)
    terminal_display = CardDisplayContract(
        mode="single",
        visible_product_ids=(38,),
        max_cards=1,
        reason="product",
    )

    with pytest.raises(
        ValueError,
        match="final product lane must match route decision bindings",
    ):
        reduce_conversation_state(
            current=current,
            turn_identity=_identity(),
            decision=_decision(
                Responsibility.PRODUCT_KNOWLEDGE,
                focus_source="explicit_product",
                product_ids=(38,),
            ),
            delta=ConversationStateDelta(),
            card_display=terminal_display,
        )


def test_multi_image_identity_keeps_exact_terminal_display() -> None:
    confirmed_products = tuple(
        ConfirmedImageProductRef(
            image_ordinal=ordinal,
            product_id=product_id,
        )
        for ordinal, product_id in enumerate((53, 55, 57), start=1)
    )
    terminal_display = CardDisplayContract(
        mode="recommendation",
        visible_product_ids=(57, 53),
        max_cards=2,
        reason="recommendation",
    )

    reduced = reduce_conversation_state(
        current=None,
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.IMAGE_IDENTITY,
            focus_source="confirmed_image",
            product_ids=(53, 55, 57),
        ),
        delta=ConversationStateDelta(
            image=LaneMutation[ImageLaneState](
                action="replace",
                value=ImageLaneState(
                    confirmed_products=confirmed_products,
                ),
            ),
        ),
        card_display=terminal_display,
    )

    assert reduced.active_focus == ActiveFocus(slot="image")
    assert reduced.image_slot.card_display == terminal_display
    assert reduced.image_slot.card_display.visible_product_ids == (
        57,
        53,
    )


def test_image_comparison_delta_must_match_router_bindings() -> None:
    with pytest.raises(
        ValueError,
        match="image lane must match route decision bindings",
    ):
        reduce_conversation_state(
            current=None,
            turn_identity=_identity(),
            decision=_decision(
                Responsibility.COMPARISON,
                focus_source="confirmed_image",
                product_ids=(53, 55),
            ),
            delta=ConversationStateDelta(
                image=LaneMutation[ImageLaneState](
                    action="replace",
                    value=ImageLaneState(
                        confirmed_products=(
                            ConfirmedImageProductRef(
                                image_ordinal=1,
                                product_id=53,
                            ),
                            ConfirmedImageProductRef(
                                image_ordinal=2,
                                product_id=57,
                            ),
                        ),
                    ),
                ),
            ),
        )


def test_image_comparison_delta_rejects_swapped_source_ordinals() -> None:
    with pytest.raises(
        ValueError,
        match="image lane must match route decision bindings",
    ):
        reduce_conversation_state(
            current=None,
            turn_identity=_identity(),
            decision=_decision(
                Responsibility.COMPARISON,
                focus_source="confirmed_image",
                product_ids=(53, 55),
            ),
            delta=ConversationStateDelta(
                image=LaneMutation[ImageLaneState](
                    action="replace",
                    value=ImageLaneState(
                        confirmed_products=(
                            ConfirmedImageProductRef(
                                image_ordinal=1,
                                product_id=55,
                            ),
                            ConfirmedImageProductRef(
                                image_ordinal=2,
                                product_id=53,
                            ),
                        ),
                    ),
                ),
            ),
        )


def test_image_comparison_delta_rejects_collapsed_duplicate_sources() -> None:
    base = _decision(
        Responsibility.COMPARISON,
        focus_source="confirmed_image",
        product_ids=(53, 55),
    )
    payload = base.model_dump(mode="python")
    payload["product_bindings"] = [
        {
            "product_id": 53,
            "variant_scope": None,
            "source_text": "image_ordinal:1",
            "source_span": None,
            "source_kind": "image_ordinal",
            "source_ordinal": 1,
        },
        {
            "product_id": 53,
            "variant_scope": None,
            "source_text": "image_ordinal:2",
            "source_span": None,
            "source_kind": "image_ordinal",
            "source_ordinal": 2,
        },
    ]
    payload["task_plan"]["product_ids"] = []
    decision = UnifiedRouteDecision.model_validate(
        payload,
        strict=True,
    )

    with pytest.raises(
        ValueError,
        match="image lane must match route decision bindings",
    ):
        reduce_conversation_state(
            current=None,
            turn_identity=_identity(),
            decision=decision,
            delta=ConversationStateDelta(
                image=LaneMutation[ImageLaneState](
                    action="replace",
                    value=ImageLaneState(
                        confirmed_products=(
                            ConfirmedImageProductRef(
                                image_ordinal=1,
                                product_id=53,
                            ),
                        ),
                    ),
                ),
            ),
        )


def test_image_comparison_delta_rejects_expanded_source_cardinality() -> None:
    with pytest.raises(
        ValueError,
        match="image lane must match route decision bindings",
    ):
        reduce_conversation_state(
            current=None,
            turn_identity=_identity(),
            decision=_decision(
                Responsibility.COMPARISON,
                focus_source="confirmed_image",
                product_ids=(53, 55),
            ),
            delta=ConversationStateDelta(
                image=LaneMutation[ImageLaneState](
                    action="replace",
                    value=ImageLaneState(
                        confirmed_products=(
                            ConfirmedImageProductRef(
                                image_ordinal=1,
                                product_id=53,
                            ),
                            ConfirmedImageProductRef(
                                image_ordinal=2,
                                product_id=55,
                            ),
                            ConfirmedImageProductRef(
                                image_ordinal=3,
                                product_id=57,
                            ),
                        ),
                    ),
                ),
            ),
        )


def test_image_lane_authority_uses_typed_binding_source_not_source_text(
) -> None:
    decision = _decision(
        Responsibility.COMPARISON,
        focus_source="confirmed_image",
        product_ids=(53, 55),
    )
    forged_bindings = tuple(
        binding.model_copy(
            update={
                "source_kind": "explicit_product",
                "source_ordinal": None,
            }
        )
        for binding in decision.product_bindings
    )
    decision = decision.model_copy(
        update={"product_bindings": forged_bindings}
    )

    with pytest.raises(
        ValueError,
        match="image lane must match route decision bindings",
    ):
        reduce_conversation_state(
            current=None,
            turn_identity=_identity(),
            decision=decision,
            delta=ConversationStateDelta(
                image=LaneMutation[ImageLaneState](
                    action="replace",
                    value=ImageLaneState(
                        confirmed_products=(
                            ConfirmedImageProductRef(
                                image_ordinal=1,
                                product_id=53,
                            ),
                            ConfirmedImageProductRef(
                                image_ordinal=2,
                                product_id=55,
                            ),
                        ),
                    ),
                ),
            ),
        )


def test_current_upload_preserves_unselected_confirmed_images() -> None:
    confirmed_products = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
        ),
        ConfirmedImageProductRef(
            image_ordinal=2,
            product_id=57,
        ),
    )

    reduced = reduce_conversation_state(
        current=None,
        turn_identity=_identity(),
        decision=_decision(
            Responsibility.COMPARISON,
            focus_source="confirmed_image",
            product_ids=(53, 55),
            processor_override="comparison",
            image_product_ids=(53,),
        ),
        delta=ConversationStateDelta(
            product=LaneMutation[ProductLaneState](
                action="replace",
                value=ProductLaneState(
                    products=(
                        _candidate(53, 1),
                        _candidate(55, 2),
                    ),
                ),
            ),
            image=LaneMutation[ImageLaneState](
                action="replace",
                value=ImageLaneState(
                    confirmed_products=confirmed_products,
                    mutation_source="current_upload",
                ),
            ),
        ),
    )

    assert reduced.image_slot is not None
    assert reduced.image_slot.confirmed_products == confirmed_products
    assert reduced.active_focus == ActiveFocus(slot="image")


def test_reducer_rejects_wrong_session() -> None:
    with pytest.raises(ConversationStateConflict):
        reduce_conversation_state(
            current=_snapshot(),
            turn_identity=_identity("other-session"),
            decision=_decision(Responsibility.RECOMMENDATION),
            delta=ConversationStateDelta(),
        )
