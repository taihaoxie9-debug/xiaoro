from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.guide.feedback.contracts import (
    ConsultationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.profile_policy import (
    ResolvedProfileContext,
    ResolvedProfileValue,
    ResolvedValueProvenance,
)
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.understanding.context_resolver import (
    resolve_context_constraint_signals,
    resolve_semantic_context,
)
from app.guide.understanding.contracts import (
    ExclusionDraft,
    ImageBundle,
    ImageObservation,
    SkinDraft,
    SkinTarget,
    TopicCode,
)
from app.guide.understanding.semantic_contracts import (
    ActiveConstraintKind,
    ConfirmedProfileField,
    SemanticContext,
)


def _snapshot(
    *,
    version: int = 2,
    query_context: RecommendationQueryContext,
    candidates: tuple[DisplayedCandidateRef, ...] = (),
    focused_candidate_ordinal: int | None = None,
) -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="s-context",
        version=version,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(
            slot="recommendation",
            ordinal=focused_candidate_ordinal,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=query_context,
            candidates=candidates,
            empty_result=not candidates,
            focused_candidate_ordinal=focused_candidate_ordinal,
        ),
    )


def _candidate(product_id: int, ordinal: int) -> DisplayedCandidateRef:
    return DisplayedCandidateRef(
        product_id=product_id,
        ordinal=ordinal,
        skin_match="unknown",
        matched_efficacies=(),
    )


def _image_bundle(
    count: int,
    *,
    focused_image_ordinal: int | None = None,
) -> ImageBundle:
    created_at = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    return ImageBundle(
        bundle_id="bundle_" + "a" * 32,
        session_id="s-context",
        owner_token_sha256="f" * 64,
        version=1,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=15),
        images=[
            ImageObservation(
                image_id=f"image_{ordinal:032d}",
                ordinal=ordinal,
                content_sha256=f"{ordinal:x}".rjust(64, "0"),
                media_type="image/jpeg",
                image_format="JPEG",
                width=4,
                height=3,
                byte_size=631,
            )
            for ordinal in range(1, count + 1)
        ],
        focused_image_ordinal=focused_image_ordinal,
    )


def _session_fact(field: str, value: str) -> ResolvedProfileValue:
    return ResolvedProfileValue(
        field=field,
        value=value,
        source="confirmed_session_fact",
        provenance=ResolvedValueProvenance(
            source_turn_id="turn_000000000000001",
            source_kind="confirmed_consultation",
        ),
    )


def _default_fact(field: str, value: str) -> ResolvedProfileValue:
    return ResolvedProfileValue(
        field=field,
        value=value,
        source="default",
        provenance=ResolvedValueProvenance(),
    )


def test_empty_context_when_no_snapshot_or_profile() -> None:
    context = resolve_semantic_context(
        conversation_version=0,
        snapshot=None,
    )

    assert context == SemanticContext(
        conversation_version=0,
        active_topic=None,
        visible_candidate_count=0,
        confirmed_profile_fields=(),
    )


def test_active_topic_and_candidate_count_come_from_snapshot() -> None:
    context = resolve_semantic_context(
        conversation_version=3,
        snapshot=_snapshot(
            version=3,
            query_context=RecommendationQueryContext(
                category="sunscreen",
                recommendation_mode="fit",
                recommendation_mode_basis="personal_suitability",
                recommendation_count=1,
                budget_maximum=Decimal("500"),
                skin="oily_sensitive",
            ),
            candidates=(
                _candidate(55, 1),
                _candidate(57, 2),
            ),
            focused_candidate_ordinal=2,
        ),
    )

    assert context.conversation_version == 3
    assert context.active_topic is TopicCode.SUNSCREEN
    assert context.visible_candidate_count == 2
    assert context.focused_candidate_ordinal == 2
    assert context.active_recommendation_mode == "fit"
    assert (
        context.active_recommendation_mode_basis
        == "personal_suitability"
    )
    assert context.active_recommendation_count == 1
    assert context.active_constraint_kinds == (
        ActiveConstraintKind.BUDGET,
        ActiveConstraintKind.CATEGORY,
        ActiveConstraintKind.SKIN,
    )
    assert ConfirmedProfileField.SKIN_TYPE in (
        context.confirmed_profile_fields
    )


def test_image_count_and_focus_come_only_from_trusted_bundle() -> None:
    focused = resolve_semantic_context(
        conversation_version=1,
        snapshot=None,
        image_bundle=_image_bundle(3, focused_image_ordinal=2),
    )
    unfocused = resolve_semantic_context(
        conversation_version=1,
        snapshot=None,
        image_bundle=_image_bundle(1),
    )

    assert focused.image_count == 3
    assert focused.focused_image_ordinal == 2
    assert unfocused.image_count == 1
    assert unfocused.focused_image_ordinal == 1


def test_confirmed_image_focus_projects_into_later_semantic_context() -> None:
    snapshot = ConversationSnapshot(
        session_id="s-context",
        version=1,
        active_owner=Responsibility.IMAGE_IDENTITY,
        active_focus=ActiveFocus(
            slot="image",
            object_id=55,
            ordinal=2,
        ),
        image_slot=ImageSlotState(
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
            focused_image_ordinal=2,
        ),
    )

    context = resolve_semantic_context(
        conversation_version=1,
        snapshot=snapshot,
    )

    assert context.image_count == 2
    assert context.confirmed_image_ordinals == (1, 2)
    assert context.focused_image_ordinal == 2


def test_current_upload_does_not_claim_preserved_images_are_confirmed() -> None:
    snapshot = ConversationSnapshot(
        session_id="s-context",
        version=1,
        active_owner=Responsibility.IMAGE_IDENTITY,
        active_focus=ActiveFocus(slot="image"),
        image_slot=ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
            ),
        ),
    )

    context = resolve_semantic_context(
        conversation_version=1,
        snapshot=snapshot,
        image_bundle=_image_bundle(2),
    )

    assert context.image_count == 2
    assert context.confirmed_image_ordinals == ()


def test_single_candidate_never_implies_candidate_focus() -> None:
    context = resolve_semantic_context(
        conversation_version=1,
        snapshot=_snapshot(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=(_candidate(91, 1),),
        ),
    )

    assert context.visible_candidate_count == 1
    assert context.focused_candidate_ordinal is None


def test_recommendation_slot_focus_projects_candidate_ordinal() -> None:
    candidates = (
        _candidate(38, 1),
        _candidate(91, 2),
    )
    snapshot = ConversationSnapshot(
        session_id="s-context",
        version=2,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(
            slot="product",
            object_id=91,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=candidates,
            focused_candidate_ordinal=2,
        ),
        product_slot=ProductSlotState(
            products=candidates,
            focused_product_id=91,
        ),
    )

    context = resolve_semantic_context(
        conversation_version=2,
        snapshot=snapshot,
    )

    assert context.focused_candidate_ordinal == 2


def test_product_focus_uses_product_slot_ordinal_not_dormant_recommendation(
) -> None:
    recommendation_candidates = (
        _candidate(38, 1),
        _candidate(55, 2),
        _candidate(91, 3),
    )
    product_candidates = (_candidate(91, 1),)
    snapshot = ConversationSnapshot(
        session_id="s-context",
        version=2,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(slot="product", object_id=91),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=recommendation_candidates,
            focused_candidate_ordinal=3,
        ),
        product_slot=ProductSlotState(
            products=product_candidates,
            focused_product_id=91,
        ),
    )

    context = resolve_semantic_context(
        conversation_version=2,
        snapshot=snapshot,
    )

    assert context.visible_candidate_count == 1
    assert context.focused_candidate_ordinal == 1


def test_context_exposes_dialogue_shape_without_raw_history_or_ids() -> None:
    snapshot = ConversationSnapshot(
        session_id="s-context",
        version=2,
        active_owner=Responsibility.CONSULTATION,
        active_focus=ActiveFocus(slot="consultation"),
        consultation_slot=ConsultationSlotState(
            state=ConsultationSubstate(
                started_at_conversation_version=1,
            ),
        ),
        image_slot=ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=55,
                ),
            ),
            focused_image_ordinal=1,
        ),
    )

    context = resolve_semantic_context(
        conversation_version=2,
        snapshot=snapshot,
    )

    assert context.active_dialogue == "consultation"
    assert context.awaiting_reply is True
    payload = context.model_dump_json()
    assert "product_id" not in payload


def test_product_interruption_does_not_expose_background_consultation_wait(
) -> None:
    candidates = (_candidate(91, 1),)
    snapshot = ConversationSnapshot(
        session_id="s-context",
        version=3,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(
            slot="product",
            object_id=91,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=candidates,
        ),
        product_slot=ProductSlotState(
            products=candidates,
            focused_product_id=91,
        ),
        consultation_slot=ConsultationSlotState(
            state=ConsultationSubstate(
                started_at_conversation_version=1,
            ),
        ),
    )

    context = resolve_semantic_context(
        conversation_version=3,
        snapshot=snapshot,
    )

    assert context.active_dialogue == "product_knowledge"
    assert context.awaiting_reply is False
    assert context.current_item_available is True


def test_session_exclusions_map_to_ingredient_exclusion_field() -> None:
    context = resolve_semantic_context(
        conversation_version=1,
        snapshot=_snapshot(
            query_context=RecommendationQueryContext(
                category="fragrance",
                recommendation_mode_basis="broad_exploration",
                exclusions=("酒精",),
            ),
            candidates=(_candidate(42, 1),),
        ),
    )

    assert ConfirmedProfileField.INGREDIENT_EXCLUSION in (
        context.confirmed_profile_fields
    )
    assert "酒精" not in context.model_dump_json()


def test_long_term_profile_only_fills_empty_field_names() -> None:
    context = resolve_semantic_context(
        conversation_version=4,
        snapshot=_snapshot(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
                skin="dry",
            ),
            candidates=(_candidate(91, 1),),
        ),
        profile_context=ResolvedProfileContext(
            values=(
                _session_fact("skin_type", "干性"),
                _session_fact("preferred_brand", "some_brand"),
            )
        ),
    )

    fields = context.confirmed_profile_fields
    assert fields.count(ConfirmedProfileField.SKIN_TYPE) == 1
    assert ConfirmedProfileField.PREFERRED_BRAND in fields
    assert len(fields) == len(set(fields))


def test_default_profile_value_is_not_confirmed() -> None:
    context = resolve_semantic_context(
        conversation_version=0,
        snapshot=None,
        profile_context=ResolvedProfileContext(
            values=(_default_fact("skin_type", "normal"),)
        ),
    )

    assert context.confirmed_profile_fields == ()


def test_resolved_context_carries_no_values_or_product_facts() -> None:
    context = resolve_semantic_context(
        conversation_version=2,
        snapshot=_snapshot(
            query_context=RecommendationQueryContext(
                category="sunscreen",
                recommendation_mode_basis="broad_exploration",
                skin="oily_sensitive",
                exclusions=("酒精",),
            ),
            candidates=(_candidate(55, 1),),
        ),
        profile_context=ResolvedProfileContext(
            values=(_session_fact("preferred_brand", "some_brand"),)
        ),
    )

    dumped = context.model_dump_json().casefold()
    assert "product" not in dumped
    assert "some_brand" not in dumped
    assert "55" not in dumped
    # No candidate product identity leaks; only a bounded count is present.
    assert '"visible_candidate_count":1' in context.model_dump_json()


def test_resolver_result_passes_strict_validation() -> None:
    context = resolve_semantic_context(
        conversation_version=2,
        snapshot=_snapshot(
            query_context=RecommendationQueryContext(
                category="cleanser",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=(_candidate(49, 1),),
        ),
    )

    assert SemanticContext.model_validate(
        context.model_dump(),
        strict=True,
    ) == context


@pytest.mark.parametrize("candidate_count", (0, 3))
def test_visible_candidate_count_is_bounded_and_matches_snapshot(
    candidate_count: int,
) -> None:
    if candidate_count == 0:
        snapshot = None
    else:
        snapshot = _snapshot(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=tuple(
                _candidate(90 + index, index)
                for index in range(1, candidate_count + 1)
            ),
        )
    context = resolve_semantic_context(
        conversation_version=1,
        snapshot=snapshot,
    )
    assert context.visible_candidate_count == candidate_count
    assert 0 <= context.visible_candidate_count <= 4


def test_confirmed_context_signals_keep_values_out_of_semantic_context() -> None:
    snapshot = _snapshot(
        query_context=RecommendationQueryContext(
            category="sunscreen",
            recommendation_mode_basis="broad_exploration",
            budget_maximum=Decimal("500"),
            skin="oily_sensitive",
            exclusions=("酒精",),
        ),
        candidates=(_candidate(55, 1),),
    )
    profile_context = ResolvedProfileContext(
        values=(
            _session_fact("skin_type", "oily_sensitive"),
            ResolvedProfileValue(
                field="ingredient_exclusion",
                value="酒精",
                source="long_term_profile",
                provenance=ResolvedValueProvenance(
                    source_turn_id="turn_profile_000000001",
                    source_kind="confirmed_consultation",
                    profile_version=1,
                ),
            ),
        )
    )

    signals = resolve_context_constraint_signals(
        snapshot=snapshot,
        profile_context=profile_context,
    )
    semantic = resolve_semantic_context(
        conversation_version=2,
        snapshot=snapshot,
        profile_context=profile_context,
    )

    assert [
        (signal.source, type(signal.constraint))
        for signal in signals
    ] == [
        ("session", SkinDraft),
        ("profile", ExclusionDraft),
    ]
    assert isinstance(signals[0].constraint, SkinDraft)
    assert signals[0].constraint.value is SkinTarget.OILY_SENSITIVE
    assert "500" not in semantic.model_dump_json()
    assert "oily_sensitive" not in semantic.model_dump_json()
    assert "酒精" not in semantic.model_dump_json()


def test_default_profile_values_never_become_context_constraints() -> None:
    signals = resolve_context_constraint_signals(
        snapshot=None,
        profile_context=ResolvedProfileContext(
            values=(_default_fact("skin_type", "normal"),)
        ),
    )

    assert signals == ()
