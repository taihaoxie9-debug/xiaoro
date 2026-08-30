from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, model_validator

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
    ProductNameResolver,
    ResolvedProductBinding,
    merge_batch_and_specific_bindings,
)
from app.guide.understanding.contracts import (
    ProductMentionDraft,
    ReferenceDraft,
    SourceSpan,
    StructuredUnderstanding,
)
from app.guide.understanding.semantic_contracts import (
    SemanticProductMention,
)


class PreRoutingProductResolution(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    resolution: ProductMentionResolution
    explicit_bindings: tuple[ResolvedProductBinding, ...] = ()

    @model_validator(mode="after")
    def validate_explicit_bindings(self):
        if any(
            binding not in self.resolution.bindings
            for binding in self.explicit_bindings
        ):
            raise ValueError(
                "explicit bindings must belong to product resolution"
            )
        spans = tuple(
            binding.source_span for binding in self.explicit_bindings
        )
        if any(span is None for span in spans):
            raise ValueError(
                "explicit bindings require typed source spans"
            )
        ordered = tuple(
            sorted(
                self.explicit_bindings,
                key=lambda binding: (
                    binding.source_span.start,
                    binding.source_span.end,
                ),
            )
        )
        if self.explicit_bindings != ordered:
            raise ValueError(
                "explicit bindings must follow source-span order"
            )
        return self


class PreRoutingProductResolutionCollector:
    def __init__(self, resolver: ProductNameResolver) -> None:
        if type(resolver) is not ProductNameResolver:
            raise TypeError("resolver must be ProductNameResolver")
        self._resolver = resolver

    def collect(
        self,
        *,
        message: str,
        understanding: StructuredUnderstanding,
        snapshot: ConversationSnapshot | None,
    ) -> PreRoutingProductResolution:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be nonempty")
        if type(understanding) is not StructuredUnderstanding:
            raise TypeError(
                "understanding must be an exact StructuredUnderstanding"
            )
        if (
            snapshot is not None
            and type(snapshot) is not ConversationSnapshot
        ):
            raise TypeError(
                "snapshot must be an exact ConversationSnapshot or None"
            )
        recovered = self._recover_explicit_product_mentions(
            message,
            understanding,
        )
        resolution, explicit_bindings = (
            self._resolve_product_mentions_or_references(
                message,
                recovered,
                snapshot=snapshot,
            )
        )
        return PreRoutingProductResolution(
            resolution=resolution,
            explicit_bindings=explicit_bindings,
        )

    def _resolve_product_mentions_or_references(
        self,
        message: str,
        understanding: StructuredUnderstanding,
        *,
        snapshot: ConversationSnapshot | None,
    ) -> tuple[
        ProductMentionResolution,
        tuple[ResolvedProductBinding, ...],
    ]:
        mention_resolution = self._resolve_product_mentions(
            message,
            understanding.product_mentions,
        )
        reference_resolution = self.resolve_reference_products(
            understanding.references,
            snapshot=snapshot,
        )
        if not understanding.product_mentions:
            return reference_resolution, ()
        if (
            mention_resolution.issue is not None
            and reference_resolution.bindings
        ):
            return reference_resolution, ()
        return mention_resolution, mention_resolution.bindings

    def _resolve_product_mentions(
        self,
        message: str,
        mentions: Sequence[ProductMentionDraft],
    ) -> ProductMentionResolution:
        if not mentions:
            return ProductMentionResolution(bindings=(), issue=None)
        semantic_mentions = tuple(
            SemanticProductMention(
                text=mention.text,
                start=mention.source_span.start,
                end=mention.source_span.end,
            )
            for mention in mentions
        )
        return self._resolver.resolve(
            message=message,
            mentions=semantic_mentions,
        )

    def _recover_explicit_product_mentions(
        self,
        message: str,
        understanding: StructuredUnderstanding,
    ) -> StructuredUnderstanding:
        recovered = self._resolver.find_explicit_mentions(message)
        if not recovered:
            return understanding
        product_mentions = list(understanding.product_mentions)
        for mention in recovered:
            if any(
                mention.start < existing.source_span.end
                and existing.source_span.start < mention.end
                for existing in product_mentions
            ):
                continue
            product_mentions.append(
                ProductMentionDraft(
                    text=mention.text,
                    source_span=SourceSpan(
                        start=mention.start,
                        end=mention.end,
                    ),
                )
            )
        product_mentions.sort(
            key=lambda item: (
                item.source_span.start,
                item.source_span.end,
            )
        )
        if product_mentions == understanding.product_mentions:
            return understanding
        return StructuredUnderstanding.model_validate(
            {
                **understanding.model_dump(mode="python"),
                "product_mentions": product_mentions,
            },
            strict=True,
        )

    @staticmethod
    def resolve_reference_products(
        references: Sequence[ReferenceDraft],
        *,
        snapshot: ConversationSnapshot | None,
    ) -> ProductMentionResolution:
        product_references = tuple(
            reference
            for reference in references
            if reference.kind
            in {
                "current_item",
                "current_batch",
                "candidate_ordinal",
            }
        )
        if not product_references:
            return ProductMentionResolution(bindings=(), issue=None)
        if snapshot is None:
            return ProductMentionResolution(
                bindings=(),
                issue="missing_reference",
            )
        candidates = _candidate_batch(snapshot)
        candidate_by_ordinal = {
            candidate.ordinal: candidate.product_id
            for candidate in candidates
        }
        current_product = _current_product_binding(snapshot)
        current_product_id = (
            current_product.product_id
            if current_product is not None
            else None
        )
        focused_ordinal = _focused_candidate_ordinal(snapshot)
        if focused_ordinal is None and current_product_id is not None:
            focused_ordinals = [
                candidate.ordinal
                for candidate in candidates
                if candidate.product_id == current_product_id
            ]
            if len(focused_ordinals) == 1:
                focused_ordinal = focused_ordinals[0]
        batch_bindings: list[ResolvedProductBinding] = []
        specific_bindings: list[ResolvedProductBinding] = []
        for reference in product_references:
            if reference.kind == "current_batch":
                batch_bindings.extend(
                    ResolvedProductBinding(
                        product_id=candidate.product_id,
                        source_text="current_batch",
                        source_kind="current_batch",
                    )
                    for candidate in candidates
                )
                continue
            if (
                reference.kind == "current_item"
                and snapshot.active_focus is not None
                and snapshot.active_focus.slot == "image"
                and current_product is not None
            ):
                specific_bindings.append(
                    ResolvedProductBinding(
                        product_id=current_product.product_id,
                        variant_scope=current_product.variant_scope,
                        source_text="current_item",
                        source_kind="current_item",
                    )
                )
                continue
            ordinal = (
                (
                    focused_ordinal
                    or (
                        candidates[0].ordinal
                        if len(candidates) == 1
                        else None
                    )
                )
                if reference.kind == "current_item"
                else reference.ordinal
            )
            if (
                reference.kind == "current_item"
                and ordinal is None
                and current_product_id is not None
            ):
                specific_bindings.append(
                    ResolvedProductBinding(
                        product_id=current_product_id,
                        variant_scope=current_product.variant_scope,
                        source_text="current_item",
                        source_kind="current_item",
                    )
                )
                continue
            if ordinal is None or ordinal not in candidate_by_ordinal:
                return ProductMentionResolution(
                    bindings=(),
                    issue="missing_reference",
                )
            specific_bindings.append(
                ResolvedProductBinding(
                    product_id=candidate_by_ordinal[ordinal],
                    source_text=f"{reference.kind}:{ordinal}",
                    source_kind=reference.kind,
                    source_ordinal=(
                        ordinal
                        if reference.kind == "candidate_ordinal"
                        else None
                    ),
                )
            )
        return ProductMentionResolution(
            bindings=merge_batch_and_specific_bindings(
                batch_bindings,
                specific_bindings,
            )
        )


def _candidate_batch(
    snapshot: ConversationSnapshot,
) -> tuple[DisplayedCandidateRef, ...]:
    if (
        snapshot.active_focus is not None
        and snapshot.active_focus.slot == "product"
        and snapshot.product_slot is not None
    ):
        return snapshot.product_slot.products
    if (
        snapshot.active_owner is Responsibility.COMPARISON
        and snapshot.active_focus is not None
        and snapshot.active_focus.slot == "image"
    ):
        if (
            snapshot.image_slot is None
            or snapshot.image_slot.card_display is None
            or snapshot.product_slot is None
            or tuple(
                item.product_id
                for item in snapshot.product_slot.products
            )
            != snapshot.image_slot.card_display.visible_product_ids
        ):
            return ()
        return snapshot.product_slot.products
    if snapshot.recommendation_slot is not None:
        return snapshot.recommendation_slot.candidates
    if snapshot.product_slot is not None:
        return snapshot.product_slot.products
    return ()


def _focused_candidate_ordinal(
    snapshot: ConversationSnapshot,
) -> int | None:
    if snapshot.recommendation_slot is None:
        return None
    if (
        snapshot.active_focus is not None
        and snapshot.active_focus.slot in {"image", "product"}
    ):
        return None
    return snapshot.recommendation_slot.focused_candidate_ordinal


def _current_product_id(
    snapshot: ConversationSnapshot,
) -> int | None:
    binding = _current_product_binding(snapshot)
    return binding.product_id if binding is not None else None


def _current_product_binding(
    snapshot: ConversationSnapshot,
) -> ResolvedProductBinding | None:
    focus = snapshot.active_focus
    if focus is not None and focus.slot == "image":
        image = next(
            (
                item
                for item in (
                    snapshot.image_slot.confirmed_products
                    if snapshot.image_slot is not None
                    else ()
                )
                if (
                    item.image_ordinal == focus.ordinal
                    and item.product_id == focus.object_id
                )
            ),
            None,
        )
        if image is None:
            return None
        return ResolvedProductBinding(
            product_id=image.product_id,
            variant_scope=image.variant_scope,
            source_text="current_product",
            source_kind="current_product",
        )
    if focus is not None and focus.slot == "product":
        product_id = (
            snapshot.product_slot.focused_product_id
            if snapshot.product_slot is not None
            else None
        )
        return (
            ResolvedProductBinding(
                product_id=product_id,
                source_text="current_product",
                source_kind="current_product",
            )
            if product_id is not None
            else None
        )
    if focus is not None and focus.slot == "recommendation":
        ordinal = (
            snapshot.recommendation_slot.focused_candidate_ordinal
            if snapshot.recommendation_slot is not None
            else None
        )
        candidate = next(
            (
                item
                for item in (
                    snapshot.recommendation_slot.candidates
                    if snapshot.recommendation_slot is not None
                    else ()
                )
                if item.ordinal == ordinal
            ),
            None,
        )
        return (
            ResolvedProductBinding(
                product_id=candidate.product_id,
                source_text="current_product",
                source_kind="current_product",
            )
            if candidate is not None
            else None
        )
    if (
        snapshot.product_slot is not None
        and snapshot.product_slot.focused_product_id is not None
    ):
        return ResolvedProductBinding(
            product_id=snapshot.product_slot.focused_product_id,
            source_text="current_product",
            source_kind="current_product",
        )
    ordinal = _focused_candidate_ordinal(snapshot)
    candidate = next(
        (
            item
            for item in (
                snapshot.recommendation_slot.candidates
                if snapshot.recommendation_slot is not None
                else ()
            )
            if item.ordinal == ordinal
        ),
        None,
    )
    if candidate is not None:
        return ResolvedProductBinding(
            product_id=candidate.product_id,
            source_text="current_product",
            source_kind="current_product",
        )
    return None


__all__ = [
    "PreRoutingProductResolution",
    "PreRoutingProductResolutionCollector",
]
