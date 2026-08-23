from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    PendingClarificationSlot,
    PendingReplySlot,
)
from app.guide.feedback.focus_state import (
    ConfirmedImageProductRef,
)
from app.guide.intent.responsibility_matrix import (
    DialogueState,
    ObjectCardinality,
    ObjectType,
    ProcessorKind,
    Responsibility,
    ResponsibilityPresentationMode,
    decision_for_responsibility,
    resolve_responsibility,
)
from app.guide.retrieval.product_name_resolver import (
    ProductResolutionIssue,
    ResolvedProductBinding,
    merge_batch_and_specific_bindings,
)
from app.guide.understanding.contracts import (
    ReferenceDraft,
    StructuredUnderstanding,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.safety_admission import (
    AdmittedSafetySignal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


ContinuityKind = Literal[
    "continue",
    "supplement",
    "correct",
    "withdraw",
    "replace_task",
    "return_to_focus",
]
FocusSource = Literal[
    "explicit_product",
    "candidate_batch",
    "current_product",
    "confirmed_image",
    "knowledge_topic",
    "consultation",
    "none",
]
PendingReplyKind = Literal[
    "affirm",
    "reject",
    "correct",
    "supplement",
    "replace_task",
    "ambiguous",
]
TransitionOperation = Literal["add", "retain", "replace", "remove"]
_GENERIC_TOPIC_MENTIONS = {
    "sunscreen": frozenset({"防晒", "防晒产品", "防晒品"}),
    "serum": frozenset({"精华", "精华产品"}),
    "skincare": frozenset({"护肤", "护肤品", "护肤产品"}),
    "base_makeup": frozenset({"底妆", "底妆产品"}),
    "color_makeup": frozenset({"彩妆", "彩妆产品"}),
    "cleanser": frozenset({"洁面", "卸妆", "清洁产品"}),
    "fragrance": frozenset({"香水", "香氛"}),
}


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class UnifiedRouteDecision(_StrictFrozen):
    processor: ProcessorKind
    responsibility: Responsibility
    presentation_mode: ResponsibilityPresentationMode
    continuity: ContinuityKind
    focus_source: FocusSource
    product_bindings: tuple[ResolvedProductBinding, ...] = ()
    clarification: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    clarification_code: ClarificationCode | None = None

    @field_validator("product_bindings", mode="before")
    @classmethod
    def freeze_bindings(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_route_shape(self) -> Self:
        responsibility_decision = decision_for_responsibility(
            self.responsibility
        )
        processor_matches = (
            self.processor == responsibility_decision.processor
            or (
                self.responsibility is Responsibility.COMPARISON
                and self.processor == "image_comparison"
            )
        )
        if (
            not processor_matches
            or self.presentation_mode
            != responsibility_decision.presentation_mode
        ):
            raise ValueError(
                "route processor and presentation must match responsibility"
            )
        binding_count = len(self.product_bindings)
        if self.processor in {
            "comparison",
            "image_comparison",
        } and not 2 <= binding_count <= 3:
            raise ValueError(
                "comparison route requires two or three products"
            )
        if (
            self.processor == "product_knowledge"
            and binding_count != 1
        ):
            raise ValueError(
                "product knowledge route requires one product"
            )
        if self.processor == "image_identity" and not 1 <= binding_count <= 3:
            raise ValueError(
                "image identity route requires confirmed products"
            )
        if self.processor in {
            "general_knowledge",
            "consultation",
            "clarification",
            "safety_escalation",
        } and binding_count:
            raise ValueError(
                f"{self.processor} route forbids product bindings"
            )
        is_clarification = self.processor == "clarification"
        if is_clarification != (
            self.clarification is not None
            and self.clarification_code is not None
        ):
            raise ValueError(
                "clarification route requires message and code"
            )
        return self


def reconcile_product_resolution_issue(
    *,
    understanding: StructuredUnderstanding,
    issue: ProductResolutionIssue | None,
    continuity_hint: str = "unknown",
) -> ProductResolutionIssue | None:
    if type(understanding) is not StructuredUnderstanding:
        raise TypeError(
            "understanding must be an exact StructuredUnderstanding"
        )
    if (
        issue in {"missing_reference", "ambiguous_reference"}
        and any(
            reference.kind == "current_item"
            for reference in understanding.references
        )
    ):
        return None
    if issue != "missing_reference":
        return issue
    mention_spans = {
        (
            mention.source_span.start,
            mention.source_span.end,
        )
        for mention in understanding.product_mentions
    }
    if (
        continuity_hint == "return_to_focus"
        and mention_spans
        and any(
            reference.kind == "current_item"
            for reference in understanding.references
        )
    ):
        return None
    bound_reference_spans = {
        (
            reference.source_span.start,
            reference.source_span.end,
        )
        for reference in understanding.references
        if (
            reference.kind
            in {
                "candidate_ordinal",
                "image_ordinal",
                "current_item",
                "current_batch",
            }
            and reference.source_span is not None
        )
    }
    generic_surfaces = (
        _GENERIC_TOPIC_MENTIONS.get(understanding.topic.value, frozenset())
        if understanding.topic is not None
        else frozenset()
    )
    all_mentions_are_bound = mention_spans and all(
        (
            mention.source_span.start,
            mention.source_span.end,
        )
        in bound_reference_spans
        or (
            bool(bound_reference_spans)
            and mention.text.strip() in generic_surfaces
        )
        for mention in understanding.product_mentions
    )
    if all_mentions_are_bound:
        return None
    return issue


def route_unified_turn(
    *,
    meaning: TurnMeaning,
    understanding: StructuredUnderstanding,
    snapshot: ConversationSnapshot | None,
    product_bindings: Sequence[ResolvedProductBinding] = (),
    current_image_products: Sequence[ConfirmedImageProductRef] = (),
    product_resolution_issue: ProductResolutionIssue | None = None,
    pending_reply_kind: PendingReplyKind | None = None,
    transition_operations: Sequence[TransitionOperation] = (),
    safety_signal: AdmittedSafetySignal | None = None,
) -> UnifiedRouteDecision:
    if type(meaning) is not TurnMeaning:
        raise TypeError("meaning must be an exact TurnMeaning")
    if type(understanding) is not StructuredUnderstanding:
        raise TypeError(
            "understanding must be an exact StructuredUnderstanding"
        )
    if snapshot is not None and type(snapshot) is not ConversationSnapshot:
        raise TypeError(
            "snapshot must be an exact ConversationSnapshot or None"
        )
    if (
        safety_signal is not None
        and type(safety_signal) is not AdmittedSafetySignal
    ):
        raise TypeError(
            "safety_signal must be an exact AdmittedSafetySignal or None"
        )
    bindings = _require_bindings(product_bindings)
    images = _require_images(current_image_products)
    operations = tuple(transition_operations)
    if any(
        item not in {"add", "retain", "replace", "remove"}
        for item in operations
    ):
        raise ValueError("unsupported transition operation")
    product_resolution_issue = reconcile_product_resolution_issue(
        understanding=understanding,
        issue=product_resolution_issue,
        continuity_hint=meaning.continuity_hint,
    )

    if (
        safety_signal is not None
        and safety_signal.requires_escalation
    ):
        responsibility = resolve_responsibility(
            operation=meaning.operation_hint,
            cardinality="zero",
            object_type="none",
            dialogue_state=_dialogue_state(snapshot),
            safety=True,
        )
        return UnifiedRouteDecision(
            processor=responsibility.processor,
            responsibility=responsibility.responsibility,
            presentation_mode=responsibility.presentation_mode,
            continuity=(
                "continue"
                if _continues_active_safety_escalation(
                    meaning=meaning,
                    snapshot=snapshot,
                )
                else _continuity(
                    meaning,
                    snapshot=snapshot,
                    operations=operations,
                )
            ),
            focus_source="consultation",
        )

    explicit_new_task = meaning.continuity_hint == "new_task"
    pending_turn = _pending_turn(snapshot)
    if (
        pending_turn is not None
        and pending_reply_kind is not None
        and pending_reply_kind != "replace_task"
        and not explicit_new_task
    ):
        return _pending_route(
            pending_reply_kind,
            gap=pending_turn.gap,
        )
    if (
        _active_processor(snapshot) == "consultation"
        and meaning.operation_hint
        in {"followup", "clarification"}
        and not meaning.reference_mentions
        and not understanding.product_mentions
    ):
        responsibility = decision_for_responsibility(
            Responsibility.CONSULTATION
        )
        return UnifiedRouteDecision(
            processor=responsibility.processor,
            responsibility=responsibility.responsibility,
            presentation_mode=responsibility.presentation_mode,
            continuity=_continuity(
                meaning,
                snapshot=snapshot,
                operations=operations,
            ),
            focus_source="consultation",
        )
    if product_resolution_issue is not None:
        return _clarification(
            {
                "ambiguous_reference": (
                    "这个名称可能对应多款商品，请补充具体品类或完整名称。"
                ),
                "missing_reference": (
                    "请明确这次指的是哪一款商品。"
                ),
                "invalid_source_span": (
                    "商品名称没有和当前消息可靠对应，请重新说明。"
                ),
            }[product_resolution_issue],
            code=ClarificationCode.REFERENCE,
            continuity=_continuity(
                meaning,
                snapshot=snapshot,
                operations=operations,
            ),
        )

    resolved_bindings, focus_source = _resolve_bindings(
        understanding=understanding,
        snapshot=snapshot,
        explicit_bindings=bindings,
        current_image_products=images,
        continuity_hint=meaning.continuity_hint,
        operation_hint=meaning.operation_hint,
    )
    continuity = _continuity(
        meaning,
        snapshot=snapshot,
        operations=operations,
    )
    if _uncertainties_require_clarification(
        understanding=understanding,
        bindings=resolved_bindings,
    ):
        return _clarification(
            understanding.uncertainties[0].detail,
            code=_clarification_code(
                understanding=understanding,
                meaning=meaning,
            ),
            continuity=continuity,
        )
    object_type = _matrix_object_type(
        meaning=meaning,
        understanding=understanding,
        focus_source=focus_source,
        bindings=resolved_bindings,
    )
    cardinality = _matrix_cardinality(
        meaning=meaning,
        focus_source=focus_source,
        bindings=resolved_bindings,
    )
    operation = _operation_for_current_batch(
        meaning=meaning,
        understanding=understanding,
        cardinality=cardinality,
    )
    responsibility = resolve_responsibility(
        operation=operation,
        cardinality=cardinality,
        object_type=object_type,
        dialogue_state=_dialogue_state(snapshot),
        safety=False,
    )
    processor = responsibility.processor
    if (
        processor == "general_knowledge"
        and _active_processor(snapshot) != "general_knowledge"
    ):
        continuity = "replace_task"
    if (
        processor == "comparison"
        and focus_source == "explicit_product"
        and len(resolved_bindings) >= 2
        and _active_processor(snapshot) != "comparison"
    ):
        continuity = "replace_task"
    if (
        processor == "product_knowledge"
        and focus_source == "explicit_product"
        and snapshot is not None
        and _pending_clarification(snapshot) is not None
        and _pending_clarification(snapshot).gap
        is ClarificationCode.REFERENCE
        and meaning.continuity_hint != "new_task"
    ):
        continuity = "supplement"
    if (
        processor == "product_knowledge"
        and _active_processor(snapshot) == "general_knowledge"
        and focus_source
        in {"current_product", "candidate_batch", "confirmed_image"}
        and meaning.continuity_hint != "new_task"
    ):
        continuity = "return_to_focus"
    if (
        processor == "recommendation"
        and _active_processor(snapshot)
        in {"consultation", "safety_escalation"}
    ):
        continuity = "replace_task"

    if processor == "comparison":
        if len(resolved_bindings) > 3:
            return _clarification(
                "一次最多比较三款，请保留最想看的三款。",
                code=ClarificationCode.REFERENCE,
                continuity=continuity,
            )
        if len(resolved_bindings) < 2:
            return _clarification(
                "商品对比需要明确两到三款商品。",
                code=ClarificationCode.REFERENCE,
                continuity=continuity,
            )
    if processor == "product_knowledge" and len(resolved_bindings) != 1:
        return _clarification(
            "请明确这次想继续了解哪一款商品。",
            code=ClarificationCode.REFERENCE,
            continuity=continuity,
        )
    if processor == "clarification":
        return _clarification(
            _matrix_clarification(
                responsibility.clarification_code
            ),
            code=_clarification_code(
                understanding=understanding,
                meaning=meaning,
            ),
            continuity=continuity,
        )
    if (
        processor == "comparison"
        and focus_source == "confirmed_image"
        and current_image_products
    ):
        processor = "image_comparison"

    return UnifiedRouteDecision(
        processor=processor,
        responsibility=responsibility.responsibility,
        presentation_mode=responsibility.presentation_mode,
        continuity=continuity,
        focus_source=(
            focus_source
            if focus_source != "none"
            else _processor_focus_source(processor, snapshot)
        ),
        product_bindings=resolved_bindings,
    )


def _pending_route(
    reply_kind: PendingReplyKind,
    *,
    gap: ClarificationCode,
) -> UnifiedRouteDecision:
    if reply_kind in {"affirm", "correct", "supplement"}:
        responsibility = decision_for_responsibility(
            Responsibility.RECOMMENDATION
        )
        return UnifiedRouteDecision(
            processor=responsibility.processor,
            responsibility=responsibility.responsibility,
            presentation_mode=responsibility.presentation_mode,
            continuity={
                "affirm": "continue",
                "correct": "correct",
                "supplement": "supplement",
            }[reply_kind],
            focus_source="none",
        )
    return _clarification(
        (
            "请给出一个明确值，我会继续前面的任务。"
            if reply_kind == "reject"
            else "请确认、纠正，或补充一个明确值。"
        ),
        code=gap,
        continuity="continue",
    )


def _matrix_object_type(
    *,
    meaning: TurnMeaning,
    understanding: StructuredUnderstanding,
    focus_source: FocusSource,
    bindings: tuple[ResolvedProductBinding, ...],
) -> ObjectType:
    reference_kinds = {
        item.kind for item in understanding.references
    }
    if bindings:
        if "image_ordinal" in reference_kinds:
            return "image_ordinals"
        if "candidate_ordinal" in reference_kinds:
            return "candidate_ordinals"
        if "current_batch" in reference_kinds:
            return "current_batch"
        if "current_item" in reference_kinds:
            return "current_product"
    if focus_source == "explicit_product":
        return "explicit_products"
    if focus_source == "confirmed_image":
        return "confirmed_images"
    if bindings:
        return "explicit_products"
    object_mentions = tuple(
        item
        for item in meaning.reference_mentions
        if item.object_family_hint in {"product", "image"}
    )
    if object_mentions:
        return (
            "image_ordinals"
            if any(
                item.object_family_hint == "image"
                for item in object_mentions
            )
            else "explicit_products"
        )
    if meaning.operation_hint == "knowledge":
        return "topic"
    return "none"


def _matrix_cardinality(
    *,
    meaning: TurnMeaning,
    focus_source: FocusSource,
    bindings: tuple[ResolvedProductBinding, ...],
) -> ObjectCardinality:
    count = len(bindings)
    if (
        meaning.operation_hint == "comparison"
        and count == 1
        and focus_source == "confirmed_image"
        and any(
            item.plurality_hint == "single"
            and item.ordinal_hint is None
            for item in meaning.reference_mentions
        )
    ):
        return "unresolved"
    if count == 0 and any(
        item.object_family_hint in {"product", "image"}
        for item in meaning.reference_mentions
    ):
        return "unresolved"
    if count == 0:
        return "zero"
    if count == 1:
        return "one"
    if count <= 3:
        return "two_or_three"
    return "over_limit"


def _operation_for_current_batch(
    *,
    meaning: TurnMeaning,
    understanding: StructuredUnderstanding,
    cardinality: ObjectCardinality,
) -> str:
    """Keep an existing candidate batch in comparison ownership."""
    operation = understanding.goal.value
    if (
        operation == "recommendation"
        and meaning.continuity_hint != "new_task"
        and cardinality == "two_or_three"
        and any(
            reference.kind == "current_batch"
            for reference in understanding.references
        )
    ):
        return "comparison"
    return operation


def _matrix_clarification(code: str | None) -> str:
    return {
        "reference_over_limit": (
            "一次最多比较三款，请保留最想看的三款。"
        ),
        "comparison_requires_multiple": (
            "商品对比需要明确两到三款商品。"
        ),
        "reference_unresolved": "请明确这次指的是哪一款商品。",
        None: "请再明确一下这次想完成的事情。",
    }[code]


def _uncertainties_require_clarification(
    *,
    understanding: StructuredUnderstanding,
    bindings: tuple[ResolvedProductBinding, ...],
) -> bool:
    if not understanding.uncertainties:
        return False
    return not (
        understanding.safety_sensitive
        and bool(bindings)
        and understanding.goal
        in {
            UnderstandingGoal.COMPARISON,
            UnderstandingGoal.SUITABILITY,
            UnderstandingGoal.KNOWLEDGE,
            UnderstandingGoal.FOLLOWUP,
        }
        and all(
            issue.code == "unverified_safety_requirement"
            for issue in understanding.uncertainties
        )
    )


def _resolve_bindings(
    *,
    understanding: StructuredUnderstanding,
    snapshot: ConversationSnapshot | None,
    explicit_bindings: tuple[ResolvedProductBinding, ...],
    current_image_products: tuple[ConfirmedImageProductRef, ...],
    continuity_hint: str,
    operation_hint: str,
) -> tuple[tuple[ResolvedProductBinding, ...], FocusSource]:
    reference_bindings: list[ResolvedProductBinding] = []
    batch_reference_bindings: list[ResolvedProductBinding] = []
    specific_reference_bindings: list[ResolvedProductBinding] = []
    image_reference_bindings: list[ResolvedProductBinding] = []
    reference_source: FocusSource = "none"
    for reference in understanding.references:
        resolved, source = _bindings_for_reference(
            reference,
            snapshot=snapshot,
            current_image_products=current_image_products,
        )
        if resolved:
            reference_bindings.extend(resolved)
            if reference.kind == "current_batch":
                batch_reference_bindings.extend(resolved)
            elif reference.kind in {
                "current_item",
                "candidate_ordinal",
            }:
                specific_reference_bindings.extend(resolved)
            elif reference.kind == "image_ordinal":
                image_reference_bindings.extend(resolved)
            reference_source = source

    if (
        operation_hint == "image_similarity"
        and image_reference_bindings
    ):
        return (
            _deduplicate_bindings(image_reference_bindings),
            "confirmed_image",
        )
    if (
        operation_hint == "recommendation"
        and continuity_hint == "new_task"
        and any(
            item.kind == "current_batch"
            for item in understanding.references
        )
    ):
        if explicit_bindings:
            return (
                _deduplicate_bindings(explicit_bindings),
                "explicit_product",
            )
        return (), "none"
    if batch_reference_bindings:
        combined = merge_batch_and_specific_bindings(
            batch_reference_bindings,
            (*specific_reference_bindings, *explicit_bindings),
        )
        return (
            combined,
            (
                "explicit_product"
                if len(combined) == 1 and explicit_bindings
                else "candidate_batch"
            ),
        )
    if (
        operation_hint == "comparison"
        and len(explicit_bindings) == 1
        and snapshot is not None
    ):
        current = _current_product_binding(snapshot)
        if current is not None:
            combined = _deduplicate_bindings(
                (current, *explicit_bindings)
            )
            if len(combined) >= 2:
                return combined, "explicit_product"
    if explicit_bindings:
        return _deduplicate_bindings(explicit_bindings), "explicit_product"
    if reference_bindings:
        return _deduplicate_bindings(reference_bindings), reference_source
    if (
        operation_hint == "image_similarity"
        and snapshot is not None
        and snapshot.image_slot is not None
    ):
        committed_images = snapshot.image_slot.confirmed_products
        current_product_id = (
            snapshot.active_focus.object_id
            if snapshot.active_focus is not None
            and snapshot.active_focus.slot == "image"
            and isinstance(snapshot.active_focus.object_id, int)
            else None
        )
        focused_image = next(
            (
                item
                for item in committed_images
                if item.product_id == current_product_id
            ),
            None,
        )
        if focused_image is not None:
            return (_image_binding(focused_image),), "confirmed_image"
        if len(committed_images) == 1:
            return (
                (_image_binding(committed_images[0]),),
                "confirmed_image",
            )
    if current_image_products:
        return (
            _deduplicate_bindings(
                _image_binding(item)
                for item in current_image_products
            ),
            "confirmed_image",
        )
    if (
        continuity_hint == "return_to_focus"
        and snapshot is not None
        and operation_hint
        not in {"assessment", "consultation", "clarification"}
    ):
        current = _current_product_binding(snapshot)
        if current is not None:
            return (current,), "current_product"
    return (), "none"


def _bindings_for_reference(
    reference: ReferenceDraft,
    *,
    snapshot: ConversationSnapshot | None,
    current_image_products: tuple[ConfirmedImageProductRef, ...],
) -> tuple[tuple[ResolvedProductBinding, ...], FocusSource]:
    if reference.kind == "candidate_ordinal" and snapshot is not None:
        candidate = next(
            (
                item
                for item in _candidate_batch(snapshot)
                if item.ordinal == reference.ordinal
            ),
            None,
        )
        return (
            ((_candidate_binding(candidate),) if candidate is not None else ()),
            "candidate_batch",
        )
    if reference.kind == "current_batch" and snapshot is not None:
        return (
            tuple(
                _candidate_binding(item)
                for item in _candidate_batch(snapshot)
            ),
            "candidate_batch",
        )
    if reference.kind == "current_item" and snapshot is not None:
        current = _current_product_binding(snapshot)
        matching_images = (
            tuple(
                item
                for item in (
                    snapshot.image_slot.confirmed_products
                    if snapshot.image_slot is not None
                    else ()
                )
                if (
                    current is not None
                    and item.product_id == current.product_id
                    and item.variant_scope == current.variant_scope
                )
            )
        )
        if len(matching_images) == 1:
            return (
                (_image_binding(matching_images[0]),),
                "confirmed_image",
            )
        return (
            ((current,) if current is not None else ()),
            "current_product",
        )
    if reference.kind == "image_ordinal":
        images = (
            current_image_products
            or (
                snapshot.image_slot.confirmed_products
                if snapshot is not None
                and snapshot.image_slot is not None
                else ()
            )
        )
        image = next(
            (
                item
                for item in images
                if item.image_ordinal == reference.ordinal
            ),
            None,
        )
        return (
            ((_image_binding(image),) if image is not None else ()),
            "confirmed_image",
        )
    return (), "none"


def _current_product_binding(
    snapshot: ConversationSnapshot,
) -> ResolvedProductBinding | None:
    product_id = (
        snapshot.product_slot.focused_product_id
        if snapshot.product_slot is not None
        else None
    )
    if product_id is None and (
        snapshot.active_focus is not None
        and snapshot.active_focus.slot == "image"
        and isinstance(snapshot.active_focus.object_id, int)
    ):
        product_id = snapshot.active_focus.object_id
    if product_id is not None:
        image = next(
            (
                item
                for item in (
                    snapshot.image_slot.confirmed_products
                    if snapshot.image_slot is not None
                    else ()
                )
                if item.product_id == product_id
            ),
            None,
        )
        return ResolvedProductBinding(
            product_id=product_id,
            variant_scope=(
                image.variant_scope if image is not None else None
            ),
            source_text="current_product",
        )
    focused_candidate_ordinal = (
        snapshot.recommendation_slot.focused_candidate_ordinal
        if snapshot.recommendation_slot is not None
        else None
    )
    if focused_candidate_ordinal is not None:
        candidate = next(
            (
                item
                for item in snapshot.recommendation_slot.candidates
                if item.ordinal == focused_candidate_ordinal
            ),
            None,
        )
        if candidate is not None:
            return _candidate_binding(candidate)
    return None


def _candidate_binding(candidate) -> ResolvedProductBinding:
    return ResolvedProductBinding(
        product_id=candidate.product_id,
        variant_scope=None,
        source_text=f"candidate_ordinal:{candidate.ordinal}",
    )


def _image_binding(
    image: ConfirmedImageProductRef,
) -> ResolvedProductBinding:
    return ResolvedProductBinding(
        product_id=image.product_id,
        variant_scope=image.variant_scope,
        source_text=f"image_ordinal:{image.image_ordinal}",
    )


def _deduplicate_bindings(
    bindings,
) -> tuple[ResolvedProductBinding, ...]:
    unique: dict[
        tuple[int, str | None],
        ResolvedProductBinding,
    ] = {}
    for binding in bindings:
        unique.setdefault(
            (binding.product_id, binding.variant_scope),
            binding,
        )
    return tuple(unique.values())


def _continuity(
    meaning: TurnMeaning,
    *,
    snapshot: ConversationSnapshot | None,
    operations: tuple[TransitionOperation, ...],
) -> ContinuityKind:
    if meaning.continuity_hint == "new_task":
        return "replace_task"
    operation_set = set(operations)
    if (
        "replace" in operation_set
        or {"remove", "add"} <= operation_set
    ):
        return "correct"
    if "remove" in operations:
        return "withdraw"
    if "add" in operations:
        return "supplement"
    if meaning.continuity_hint == "return_to_focus":
        return "return_to_focus"
    if meaning.continuity_hint == "continue":
        return "continue"
    return "continue" if snapshot is not None else "replace_task"


def _continues_active_safety_escalation(
    *,
    meaning: TurnMeaning,
    snapshot: ConversationSnapshot | None,
) -> bool:
    if snapshot is None or meaning.operation_hint != "assessment":
        return False
    return (
        _active_processor(snapshot) == "safety_escalation"
        or (
            snapshot.consultation_slot is not None
            and snapshot.consultation_slot.state.medical_escalation
            is not None
        )
    )


def _candidate_batch(snapshot: ConversationSnapshot):
    if (
        snapshot.active_focus is not None
        and snapshot.active_focus.slot == "product"
        and snapshot.product_slot is not None
    ):
        return snapshot.product_slot.products
    if snapshot.recommendation_slot is not None:
        return snapshot.recommendation_slot.candidates
    if snapshot.product_slot is not None:
        return snapshot.product_slot.products
    return ()


def _pending_turn(snapshot: ConversationSnapshot | None):
    if (
        snapshot is not None
        and isinstance(snapshot.reply_slot, PendingReplySlot)
    ):
        return snapshot.reply_slot.value
    return None


def _pending_clarification(
    snapshot: ConversationSnapshot | None,
):
    if (
        snapshot is not None
        and isinstance(
            snapshot.reply_slot,
            PendingClarificationSlot,
        )
    ):
        return snapshot.reply_slot.value
    return None


def _active_processor(
    snapshot: ConversationSnapshot | None,
) -> ProcessorKind | None:
    if snapshot is None or snapshot.active_owner is None:
        return None
    return decision_for_responsibility(
        snapshot.active_owner
    ).processor


def _dialogue_state(
    snapshot: ConversationSnapshot | None,
) -> DialogueState:
    if snapshot is None:
        return "empty"
    if snapshot.reply_slot is not None:
        return "pending_clarification"
    active = _active_processor(snapshot)
    return {
        "recommendation": "recommendation_batch",
        "comparison": "comparison_batch",
        "product_knowledge": "single_product_focus",
        "general_knowledge": "general_knowledge",
        "consultation": "consultation",
        "image_identity": "confirmed_image_product",
        "clarification": "pending_clarification",
        "safety_escalation": "safety_escalation",
        None: "empty",
    }[active]


def _processor_focus_source(
    processor: ProcessorKind,
    snapshot: ConversationSnapshot | None,
) -> FocusSource:
    if processor == "general_knowledge":
        return "knowledge_topic"
    if processor in {"consultation", "safety_escalation"}:
        return "consultation"
    if processor == "product_knowledge" and snapshot is not None:
        return "current_product"
    return "none"


def _clarification_code(
    *,
    understanding: StructuredUnderstanding,
    meaning: TurnMeaning,
) -> ClarificationCode:
    issue_codes = {
        issue.code for issue in understanding.uncertainties
    }
    if issue_codes.intersection({
        "invalid_budget",
        "unsupported_budget_format",
    }):
        return ClarificationCode.BUDGET
    if issue_codes.intersection({
        "ambiguous_category",
        "missing_category",
    }):
        return ClarificationCode.TOPIC
    if (
        understanding.references
        or meaning.reference_mentions
        or issue_codes.intersection({
            "ambiguous_reference",
            "ambiguous_candidate_reference",
            "ambiguous_image_reference",
            "too_many_candidate_references",
            "too_many_image_references",
        })
    ):
        return ClarificationCode.REFERENCE
    if issue_codes.intersection({
        "unsupported_attribute_exclusion",
        "unverified_safety_requirement",
        "missing_revision_target",
        "ambiguous_revision_target",
        "confirm_hard_constraint_revision",
    }):
        return ClarificationCode.CONCERN
    return ClarificationCode.GOAL


def _clarification(
    message: str,
    *,
    code: ClarificationCode,
    continuity: ContinuityKind,
) -> UnifiedRouteDecision:
    responsibility = decision_for_responsibility(
        Responsibility.CLARIFICATION
    )
    return UnifiedRouteDecision(
        processor=responsibility.processor,
        responsibility=responsibility.responsibility,
        presentation_mode=responsibility.presentation_mode,
        continuity=continuity,
        focus_source="none",
        clarification=message,
        clarification_code=code,
    )


def _require_bindings(
    bindings: Sequence[ResolvedProductBinding],
) -> tuple[ResolvedProductBinding, ...]:
    if isinstance(bindings, (str, bytes)) or any(
        not isinstance(item, ResolvedProductBinding)
        for item in bindings
    ):
        raise TypeError(
            "product_bindings must contain ResolvedProductBinding values"
        )
    return tuple(bindings)


def _require_images(
    images: Sequence[ConfirmedImageProductRef],
) -> tuple[ConfirmedImageProductRef, ...]:
    if isinstance(images, (str, bytes)) or any(
        not isinstance(item, ConfirmedImageProductRef)
        for item in images
    ):
        raise TypeError(
            "current_image_products must contain confirmed image refs"
        )
    return tuple(images)


__all__ = [
    "ContinuityKind",
    "FocusSource",
    "UnifiedRouteDecision",
    "reconcile_product_resolution_issue",
    "route_unified_turn",
]
