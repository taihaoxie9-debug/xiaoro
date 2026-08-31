from __future__ import annotations

from app.guide.application.product_resolution import (
    PreRoutingProductResolutionCollector,
)
from app.guide.feedback.contracts import (
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
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import route_unified_turn
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.retrieval.controlled_product_aliases import (
    ControlledProductAliasRecord,
    ControlledProductAliasRegistry,
)
from app.guide.retrieval.product_name_resolver import ProductNameResolver
from app.guide.understanding.contracts import (
    ProductMentionDraft,
    ReferenceDraft,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.image_contracts import CanonicalIdentity
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


class _IdentityCatalog:
    def __init__(self, product_ids: tuple[int, ...]) -> None:
        self.product_ids = frozenset(product_ids)

    def get_identity(
        self,
        product_id: int,
    ) -> CanonicalIdentity | None:
        if product_id not in self.product_ids:
            return None
        return CanonicalIdentity(
            product_id=product_id,
            brand=f"品牌{product_id}",
            product_name=f"商品{product_id}",
        )


def _comparison_understanding(
    message: str,
    *,
    product_mentions: tuple[str, ...],
) -> StructuredUnderstanding:
    return StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=TopicCode.SERUM,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        relative_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[
            ProductMentionDraft(
                text=text,
                source_span=SourceSpan(
                    start=message.index(text),
                    end=message.index(text) + len(text),
                ),
            )
            for text in product_mentions
        ],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning="比较两款精华",
    )


def test_partial_provider_mentions_are_completed_from_catalog() -> None:
    message = "帮我对比兰蔻小黑瓶和小棕瓶"
    collector = PreRoutingProductResolutionCollector(
        ProductNameResolver(
            _IdentityCatalog((129, 33)),
            aliases={"兰蔻小黑瓶": 129, "小棕瓶": 33},
        )
    )

    result = collector.collect(
        message=message,
        understanding=_comparison_understanding(
            message,
            product_mentions=("兰蔻小黑瓶",),
        ),
        snapshot=None,
    )

    assert result.resolution.product_ids == (129, 33)
    assert tuple(
        binding.source_text for binding in result.explicit_bindings
    ) == ("兰蔻小黑瓶", "小棕瓶")


def test_wide_model_mention_uses_overlapping_unique_controlled_alias() -> None:
    class _Catalog:
        product_ids = frozenset({39})

        @staticmethod
        def get_identity(product_id: int) -> CanonicalIdentity | None:
            if product_id != 39:
                return None
            return CanonicalIdentity(
                product_id=39,
                brand="赫莲娜（HR）",
                product_name="赫莲娜绿宝瓶精华",
            )

    message = "赫莲娜绿宝瓶第六代跟旧版主要改了什么？"
    controlled_aliases = ControlledProductAliasRegistry((
        ControlledProductAliasRecord(
            alias="绿宝瓶",
            identity_scope="exact_product",
            product_ids=(39,),
            default_product_id=39,
            source_refs=("a" * 64,),
            review_status="approved",
            review_rationale="审核别名唯一绑定赫莲娜绿宝瓶。",
        ),
    ))
    collector = PreRoutingProductResolutionCollector(
        ProductNameResolver(
            _Catalog(),
            controlled_aliases=controlled_aliases,
        )
    )

    result = collector.collect(
        message=message,
        understanding=_comparison_understanding(
            message,
            product_mentions=("赫莲娜绿宝瓶第六代",),
        ),
        snapshot=None,
    )

    assert result.resolution.product_ids == (39,)
    assert result.resolution.issue is None


def test_recovered_explicit_binding_preserves_source_order() -> None:
    message = "商品129和第一款比"
    understanding = _comparison_understanding(
        message,
        product_mentions=(),
    ).model_copy(
        update={
            "references": [
                ReferenceDraft(
                    kind="candidate_ordinal",
                    ordinal=1,
                    source_span=SourceSpan(
                        start=message.index("第一款"),
                        end=message.index("第一款") + len("第一款"),
                    ),
                )
            ]
        },
        deep=True,
    )
    candidate = DisplayedCandidateRef(
        product_id=33,
        ordinal=1,
        skin_match="unknown",
        matched_efficacies=(),
    )
    snapshot = ConversationSnapshot(
        session_id="source-order-session",
        version=1,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(slot="recommendation"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=(candidate,),
        ),
    )
    collected = PreRoutingProductResolutionCollector(
        ProductNameResolver(_IdentityCatalog((129, 33)))
    ).collect(
        message=message,
        understanding=understanding,
        snapshot=snapshot,
    )

    assert collected.explicit_bindings[0].source_span == SourceSpan(
        start=0,
        end=len("商品129"),
    )

    decision = route_unified_turn(
        meaning=TurnMeaning(
            operation_hint="comparison",
            topic_hint="serum",
            continuity_hint="continue",
            subject_scope_hint="self",
            question_meaning="比较明确商品和第一款",
            safety_language="ordinary",
        ),
        understanding=understanding,
        snapshot=snapshot,
        product_bindings=collected.explicit_bindings,
        task_plan=plan_task(
            understanding,
            resolved_product_ids=(129, 33),
        ),
    )

    assert decision.processor == "comparison"
    assert tuple(
        binding.product_id for binding in decision.product_bindings
    ) == (129, 33)


def test_current_item_resolution_uses_active_image_before_dormant_product(
) -> None:
    dormant = DisplayedCandidateRef(
        product_id=91,
        ordinal=1,
        skin_match="unknown",
        matched_efficacies=(),
    )
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
        variant_scope="50ml",
    )
    snapshot = ConversationSnapshot(
        session_id="product-resolution-session",
        version=2,
        active_owner=Responsibility.IMAGE_IDENTITY,
        active_focus=ActiveFocus(
            slot="image",
            object_id=53,
            ordinal=1,
        ),
        product_slot=ProductSlotState(
            products=(dormant,),
            focused_product_id=91,
        ),
        image_slot=ImageSlotState(
            confirmed_products=(image,),
            focused_image_ordinal=1,
        ),
    )

    resolution = (
        PreRoutingProductResolutionCollector.resolve_reference_products(
            (
                ReferenceDraft(
                    kind="current_item",
                    source_span=SourceSpan(start=0, end=2),
                ),
            ),
            snapshot=snapshot,
        )
    )

    assert resolution.product_ids == (53,)


def test_comparison_ordinal_uses_current_product_batch_before_dormant_recommendation(
) -> None:
    old_candidate = DisplayedCandidateRef(
        product_id=91,
        ordinal=1,
        skin_match="unknown",
        matched_efficacies=(),
    )
    current_products = (
        DisplayedCandidateRef(
            product_id=53,
            ordinal=1,
            skin_match="unknown",
            matched_efficacies=(),
        ),
        DisplayedCandidateRef(
            product_id=55,
            ordinal=2,
            skin_match="unknown",
            matched_efficacies=(),
        ),
    )
    snapshot = ConversationSnapshot(
        session_id="product-resolution-session",
        version=3,
        active_owner=Responsibility.COMPARISON,
        active_focus=ActiveFocus(slot="image", object_id=53, ordinal=1),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=(old_candidate,),
        ),
        product_slot=ProductSlotState(products=current_products),
        image_slot=ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
            ),
            focused_image_ordinal=1,
            card_display=CardDisplayContract(
                mode="comparison",
                visible_product_ids=(53, 55),
                max_cards=2,
                reason="comparison",
            ),
        ),
    )

    resolution = (
        PreRoutingProductResolutionCollector.resolve_reference_products(
            (
                ReferenceDraft(
                    kind="candidate_ordinal",
                    ordinal=1,
                    source_span=SourceSpan(start=0, end=3),
                ),
            ),
            snapshot=snapshot,
        )
    )

    assert resolution.product_ids == (53,)
