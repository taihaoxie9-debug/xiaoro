from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from hashlib import sha256
import json
import re

from app.guide.decision.contracts import CandidateEvaluation
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    ConceptConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    FacetConstraint,
    InclusionConstraint,
    SkinConstraint,
    TaskConstraint,
)
from app.guide.intent.responsibility_matrix import (
    Responsibility,
)
from app.guide.presentation.contracts import (
    CardDisplayContract,
    DisplayCategoryFact,
    ProductCard,
)
from app.guide.presentation.copywriter_contracts import (
    ApprovedConstraint,
    ApprovedSoftFact,
    CompactTagEvidence,
    ComparisonDimensionEvidence,
    CopyLengthBudget,
    CopySlot,
    DirectCaution,
    FactAttribution,
    LockedFact,
    PresentationMode,
    PresentationPacket,
    PresentationSectionSpec,
    responsibility_for_presentation_mode,
)
from app.guide.presentation.copywriter_validation import (
    is_safe_soft_fact_text,
)
from app.guide.presentation.fact_admission import (
    presentation_fact_role,
)
from app.guide.presentation.narrative_atoms import build_narrative_atoms
from app.guide.presentation.product_detail_selection import (
    select_product_detail_facts,
)
from app.guide.presentation.public_fact_projection import (
    project_public_facts,
    projected_fact_to_soft_fact,
)
from app.guide.presentation.sse_events import (
    ConceptSlotData,
    MerchantClaimEvidenceData,
    SelectionSlotData,
)
from app.guide.retrieval.pitfall_contracts import TypedPitfall
from app.guide.retrieval.review_summary_contracts import (
    ReviewSummaryResult,
)
from app.guide.understanding.turn_meaning_contracts import (
    RecommendationMode,
)


_SPACE = re.compile(r"\s+")
_CJK = re.compile(r"[\u3400-\u9fff]")


def build_presentation_packet(
    *,
    mode: PresentationMode,
    responsibility: Responsibility,
    recommendation_mode: RecommendationMode | None = None,
    user_need_summary: str,
    winner_status: str | None,
    card_display: CardDisplayContract,
    cards: Sequence[ProductCard],
    selection_slots: Sequence[SelectionSlotData],
    concept_slots: Sequence[ConceptSlotData],
    merchant_claims: Sequence[MerchantClaimEvidenceData],
    pitfalls: Sequence[TypedPitfall],
    review_summaries: Sequence[ReviewSummaryResult] = (),
    proof_points: Sequence[LockedFact] = (),
    task_constraints: Sequence[TaskConstraint] = (),
    additional_soft_facts: Sequence[ApprovedSoftFact] = (),
    requested_dimensions: Sequence[str] = (),
    candidate_evaluations: Sequence[CandidateEvaluation] = (),
    winner_product_id: int | None = None,
    winner_tie_reason: str | None = None,
) -> PresentationPacket:
    if not isinstance(card_display, CardDisplayContract):
        raise TypeError("card_display must be CardDisplayContract")
    normalized_cards = tuple(cards)
    if any(not isinstance(card, ProductCard) for card in normalized_cards):
        raise TypeError("cards must contain ProductCard values")
    card_by_id = {card.product_id: card for card in normalized_cards}
    if len(card_by_id) != len(normalized_cards):
        raise ValueError("presentation cards must have unique product IDs")
    visible_ids = card_display.visible_product_ids
    if any(product_id not in card_by_id for product_id in visible_ids):
        raise ValueError("visible product is missing its ProductCard")
    normalized_evaluations = tuple(candidate_evaluations)
    if any(
        not isinstance(item, CandidateEvaluation)
        for item in normalized_evaluations
    ):
        raise TypeError(
            "candidate_evaluations must contain CandidateEvaluation values"
        )
    evaluation_by_product = {
        item.product_id: item
        for item in normalized_evaluations
    }
    if len(evaluation_by_product) != len(normalized_evaluations):
        raise ValueError("candidate evaluations must have unique products")
    if any(
        product_id not in visible_ids
        for product_id in evaluation_by_product
    ):
        raise ValueError(
            "candidate evaluations must belong to visible products"
        )
    normalized_proof_points = tuple(proof_points)
    if any(
        not isinstance(point, LockedFact)
        for point in normalized_proof_points
    ):
        raise TypeError("proof_points must contain LockedFact values")
    if any(point.kind != "numeric" for point in normalized_proof_points):
        raise ValueError("presentation proof points must be numeric")
    if any(
        point.product_id not in visible_ids
        for point in normalized_proof_points
    ):
        raise ValueError("presentation proof point product must be visible")

    selections_by_product = _group_by_product(selection_slots)
    concepts_by_product = _group_by_product(concept_slots)
    claims_by_product = _group_by_product(merchant_claims)
    reviews_by_product = _group_by_product(review_summaries)
    pitfalls_by_product = _group_by_product(pitfalls)
    proof_points_by_product = _group_by_product(
        normalized_proof_points
    )
    if any(
        len(points) > 1
        for points in proof_points_by_product.values()
    ):
        raise ValueError(
            "each product accepts at most one numeric proof point"
        )
    if mode == "product_knowledge" and len(visible_ids) != 1:
        raise ValueError("product knowledge requires one product")

    claim_values_by_field: dict[
        str,
        dict[int, set[str]],
    ] = {}
    for claim in merchant_claims:
        if (
            claim.product_id not in visible_ids
            or claim.claim_scope != "ordinary"
        ):
            continue
        claim_values_by_field.setdefault(
            claim.field_key,
            {},
        ).setdefault(claim.product_id, set()).add(
            claim.display_claim.casefold()
        )
    distinctive_fields = {
        field_key
        for field_key, values_by_product
        in claim_values_by_field.items()
        if (
            len(values_by_product) > 1
            and len({
                value
                for values in values_by_product.values()
                for value in values
            }) > 1
        )
    }
    preferred_fields = _preferred_fields(
        selection_slots=selection_slots,
        concept_slots=concept_slots,
        task_constraints=task_constraints,
    )

    slots = tuple(
        _build_slot(
            index=index,
            card=card_by_id[product_id],
            selection_slots=selections_by_product.get(product_id, ()),
            concept_slots=concepts_by_product.get(product_id, ()),
            preferred_fields=preferred_fields,
            merchant_claims=claims_by_product.get(product_id, ()),
            review_summaries=reviews_by_product.get(product_id, ()),
            pitfalls=pitfalls_by_product.get(product_id, ()),
            proof_points=proof_points_by_product.get(product_id, ()),
            distinctive_fields=distinctive_fields,
        )
        for index, product_id in enumerate(visible_ids, start=1)
    )
    normalized_additional_facts = tuple(additional_soft_facts)
    if any(
        not isinstance(fact, ApprovedSoftFact)
        for fact in normalized_additional_facts
    ):
        raise TypeError(
            "additional_soft_facts must contain ApprovedSoftFact values"
        )
    if any(
        fact.product_id not in visible_ids
        for fact in normalized_additional_facts
    ):
        raise ValueError(
            "additional soft facts must belong to visible products"
        )
    normalized_additional_facts = tuple(
        fact.model_copy(
            update={
                "generic_copy_allowed": (
                    fact.generic_copy_allowed
                    and card_by_id[fact.product_id]
                    .price_specification_alignment
                    == "aligned"
                )
            }
        )
        for fact in normalized_additional_facts
    )
    additional_by_product = _group_by_product(
        normalized_additional_facts
    )
    slots = tuple(
        CopySlot.model_validate(
            {
                **slot.model_dump(mode="python"),
                "approved_soft_facts": (
                    *slot.approved_soft_facts,
                    *additional_by_product.get(slot.product_id, ()),
                ),
            },
            strict=True,
        )
        for slot in slots
    )
    expected_responsibility = responsibility_for_presentation_mode(mode)
    if (
        responsibility is not expected_responsibility
        and not (
            responsibility is Responsibility.SAFETY_ESCALATION
            and mode == "consultation"
        )
    ):
        raise ValueError(
            "presentation mode must match explicit responsibility"
        )
    explicit_requested_dimensions = _normalize_requested_dimensions(
        requested_dimensions
    )
    normalized_requested_dimensions = (
        explicit_requested_dimensions
        if responsibility.value == "comparison"
        else tuple(dict.fromkeys((
            *explicit_requested_dimensions,
            *_requested_dimensions(
                selection_slots=selection_slots,
                concept_slots=concept_slots,
            ),
        )))
    )
    projected_slots: list[CopySlot] = []
    for slot in slots:
        projection = project_public_facts(
            card=card_by_id[slot.product_id],
            approved_soft_facts=slot.approved_soft_facts,
            requested_dimensions=normalized_requested_dimensions,
        )
        approved_ids = {
            fact.fact_id for fact in slot.approved_soft_facts
        }
        projected_soft_facts = tuple(
            projected_fact_to_soft_fact(fact)
            for fact in projection.facts
            if fact.fact_id not in approved_ids
        )
        projected_slots.append(
            CopySlot.model_validate(
                {
                    **slot.model_dump(mode="python"),
                    "approved_soft_facts": (
                        *slot.approved_soft_facts,
                        *projected_soft_facts,
                    ),
                    "detail_facts": select_product_detail_facts(
                        projection=projection,
                        responsibility=responsibility,
                        requested_dimensions=(
                            normalized_requested_dimensions
                        ),
                    ),
                    "comparison_evidence": (
                        (
                            *slot.comparison_evidence,
                            _profile_match_evidence(
                                slot=slot.model_copy(
                                    update={
                                        "approved_soft_facts": (
                                            *slot.approved_soft_facts,
                                            *projected_soft_facts,
                                        ),
                                    },
                                    deep=True,
                                ),
                                evaluation=evaluation_by_product.get(
                                    slot.product_id
                                ),
                                task_constraints=task_constraints,
                            ),
                        )
                        if responsibility.value == "comparison"
                        else slot.comparison_evidence
                    ),
                },
                strict=True,
            )
        )
    slots = tuple(projected_slots)
    return PresentationPacket(
        mode=mode,
        responsibility=responsibility,
        recommendation_mode=recommendation_mode,
        user_need_summary=normalize_display_text(
            user_need_summary,
            limit=512,
        ),
        winner_status=winner_status,
        winner_product_id=winner_product_id,
        winner_tie_reason=winner_tie_reason,
        slots=slots,
        section_order=_section_order(
            mode,
            slots,
            responsibility=responsibility,
        ),
        requested_dimensions=normalized_requested_dimensions,
        approved_constraints=_approved_constraints(
            task_constraints=task_constraints,
            selection_slots=selection_slots,
            concept_slots=concept_slots,
        ),
        copy_budget=_copy_budget(mode),
    )


def normalize_display_text(value: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise TypeError("display text must be a string")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 2:
        raise ValueError("display text limit must be at least 2")
    normalized = _SPACE.sub(
        " ",
        value.replace("\r", " ").replace("\n", " "),
    ).strip()
    if not normalized:
        raise ValueError("display text must be nonempty")
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _attributed_soft_meaning(
    value: str,
    *,
    attribution: FactAttribution,
    limit: int,
) -> str:
    normalized = normalize_display_text(value, limit=limit)
    if attribution == "consumer_report":
        normalized = f"限定样本的用户反馈：{normalized}"
    elif attribution == "merchant_claim":
        normalized = f"品牌主打：{normalized}"
    return normalize_display_text(normalized, limit=limit)


def _build_slot(
    *,
    index: int,
    card: ProductCard,
    selection_slots: Sequence[SelectionSlotData],
    concept_slots: Sequence[ConceptSlotData],
    preferred_fields: frozenset[str],
    merchant_claims: Sequence[MerchantClaimEvidenceData],
    review_summaries: Sequence[ReviewSummaryResult],
    pitfalls: Sequence[TypedPitfall],
    proof_points: Sequence[LockedFact],
    distinctive_fields: set[str],
) -> CopySlot:
    soft_facts: list[ApprovedSoftFact] = []
    for item in selection_slots:
        if item.match_status != "matched" or item.matched_value is None:
            continue
        soft_facts.append(
            ApprovedSoftFact(
                fact_id=_stable_fact_id(
                    "selection",
                    card.product_id,
                    item.field_key,
                    item.requested_value,
                    item.matched_value,
                ),
                product_id=card.product_id,
                field_key=item.field_key,
                plain_meaning=_attributed_soft_meaning(
                    (
                        f"{item.matched_value}，"
                        f"符合{item.requested_value}偏好"
                    ),
                    attribution=item.attribution,
                    limit=256,
                ),
                attribution=item.attribution,
                source_refs=tuple(item.source_refs),
            )
        )
    for item in concept_slots:
        if item.match_status != "matched" or not item.source_values:
            continue
        soft_facts.append(
            ApprovedSoftFact(
                fact_id=_stable_fact_id(
                    "concept",
                    card.product_id,
                    item.field_key,
                    item.concept_id,
                    *item.source_values,
                ),
                product_id=card.product_id,
                field_key=item.field_key,
                dimension_ids=(item.concept_id,),
                plain_meaning=_attributed_soft_meaning(
                    "、".join(item.source_values),
                    attribution=item.attribution,
                    limit=256,
                ),
                attribution=item.attribution,
                source_refs=tuple(item.source_refs),
            )
        )
    soft_facts.extend(
        _category_soft_facts(
            card,
            excluded_fields=preferred_fields,
        )
    )
    for summary in review_summaries:
        for source_fact in summary.source_facts:
            soft_facts.append(
                ApprovedSoftFact(
                    fact_id=source_fact.claim_id,
                    product_id=card.product_id,
                    field_key="consumer_report",
                    plain_meaning=_attributed_soft_meaning(
                        source_fact.quote,
                        attribution="consumer_report",
                        limit=256,
                    ),
                    attribution="consumer_report",
                    source_refs=(
                        source_fact.provenance.source_locator,
                    ),
                )
            )
    caution_values: list[DirectCaution] = [
        DirectCaution(
            caution_id=item.finding_id,
            product_id=item.product_id,
            severity=item.severity.value,
            text=normalize_display_text(
                f"{item.title}：{item.description}",
                limit=512,
            ),
            source_refs=tuple(item.evidence_refs),
        )
        for item in pitfalls
    ]
    for claim in merchant_claims:
        if claim.claim_scope == "ordinary":
            cleaned = _public_claim_meaning(claim)
            if cleaned is None:
                continue
            soft_facts.append(
                ApprovedSoftFact(
                    fact_id=claim.claim_id,
                    product_id=claim.product_id,
                    field_key=claim.field_key,
                    plain_meaning=f"品牌主打：{cleaned}",
                    attribution="merchant_claim",
                    source_refs=(claim.source_locator,),
                )
            )
        else:
            cleaned = normalize_display_text(
                claim.display_claim,
                limit=160,
            )
            caution_values.append(
                DirectCaution(
                    caution_id=f"merchant-safety:{claim.claim_id}",
                    product_id=claim.product_id,
                    severity="medium",
                    text=(
                        f"品牌将「{cleaned}」作为适用说明。"
                        "皮肤正处于泛红、刺痛或破损时先暂停尝试，"
                        "状态稳定后再局部试用。"
                    ),
                    source_refs=(claim.source_locator,),
                )
            )
    narrative_atoms = build_narrative_atoms(
        tuple(soft_facts),
        preferred_fields=preferred_fields,
        distinctive_fields=distinctive_fields,
    )
    return CopySlot(
        slot_id=f"p{index}",
        product_id=card.product_id,
        name=(
            card.display_name
            or card.name
            or f"商品 {card.product_id}"
        ),
        category_profile=card.category_profile.value,
        approved_soft_facts=narrative_atoms,
        locked_facts=_locked_facts(card, proof_points=proof_points),
        required_cautions=tuple(caution_values[:6]),
        comparison_evidence=_comparison_evidence(
            product_id=card.product_id,
            selection_slots=selection_slots,
            concept_slots=concept_slots,
        ),
        compact_tag_evidence=_compact_tag_evidence(
            card=card,
            selection_slots=selection_slots,
            concept_slots=concept_slots,
            merchant_claims=merchant_claims,
        ),
    )


def _category_soft_facts(
    card: ProductCard,
    *,
    excluded_fields: frozenset[str] = frozenset(),
) -> tuple[ApprovedSoftFact, ...]:
    facts: list[ApprovedSoftFact] = []
    for fact in card.category_facts:
        if (
            fact.state != "known"
            or presentation_fact_role(fact.field_key) != "narrative"
            or fact.field_key in excluded_fields
        ):
            continue
        display = _category_fact_text(fact)
        if not display:
            continue
        label = (
            "核心成分"
            if fact.field_key == "ingredients_present"
            else "适合肤质"
            if fact.field_key == "suitable_skin"
            else fact.label
        )
        facts.append(
            ApprovedSoftFact(
                fact_id=(
                    f"card:{card.product_id}:"
                    f"{fact.field_key}:soft_display"
                ),
                product_id=card.product_id,
                field_key=fact.field_key,
                plain_meaning=f"{label}：{display}",
                attribution="verified_fact",
                source_refs=(
                    f"card:{card.product_id}:{fact.field_key}",
                ),
            )
        )
    return tuple(facts)


def _preferred_fields(
    *,
    selection_slots: Sequence[SelectionSlotData],
    concept_slots: Sequence[ConceptSlotData],
    task_constraints: Sequence[TaskConstraint],
) -> frozenset[str]:
    fields = {
        item.field_key
        for item in (*selection_slots, *concept_slots)
    }
    for constraint in task_constraints:
        if isinstance(constraint, EfficacyConstraint):
            fields.add("efficacy")
        elif isinstance(constraint, SkinConstraint):
            fields.add("suitable_skin")
        elif isinstance(
            constraint,
            (FacetConstraint, ConceptConstraint, InclusionConstraint),
        ):
            fields.add(constraint.field_key)
    return frozenset(fields)


def _locked_facts(
    card: ProductCard,
    *,
    proof_points: Sequence[LockedFact],
) -> tuple[LockedFact, ...]:
    facts: list[LockedFact] = []
    specification = (
        (card.specification or "")
        if card.price_specification_alignment == "aligned"
        else ""
    )
    if card.price is not None:
        price = f"¥{_decimal_text(card.price)}"
        facts.append(
            LockedFact(
                fact_id=f"card:{card.product_id}:reference_price",
                product_id=card.product_id,
                kind="price",
                label="参考价",
                display_value=(
                    f"{price} / {specification}"
                    if specification
                    else price
                ),
                numeric_value=card.price,
                source_refs=(f"card:{card.product_id}:price",),
            )
        )
    category_facts = {
        fact.field_key: fact
        for fact in card.category_facts
        if fact.state == "known"
    }
    direct_field_keys = tuple(sorted(
        field_key
        for field_key in category_facts
        if presentation_fact_role(field_key) == "direct_fact"
    ))
    for field_key in (
        "suitable_skin",
        "ingredients_present",
        *direct_field_keys,
    ):
        if field_key == "net_content" and specification:
            continue
        fact = category_facts.get(field_key)
        if fact is None:
            continue
        display = _category_fact_text(fact)
        if not display:
            continue
        facts.append(
            LockedFact(
                fact_id=f"card:{card.product_id}:{fact.field_key}",
                product_id=card.product_id,
                kind=(
                    "ingredient"
                    if fact.field_key == "ingredients_present"
                    else "verified_text"
                ),
                label=(
                    "核心成分"
                    if fact.field_key == "ingredients_present"
                    else (
                        "适合肤质"
                        if fact.field_key == "suitable_skin"
                        else fact.label
                    )
                ),
                display_value=display,
                source_refs=(
                    f"card:{card.product_id}:{fact.field_key}",
                ),
            )
        )
    facts.extend(proof_points)
    return tuple(facts[:12])


def _category_fact_text(fact: DisplayCategoryFact) -> str:
    value = fact.value
    if value is None:
        return ""
    if isinstance(value, tuple):
        return normalize_display_text(
            "、".join(str(item) for item in value),
            limit=512,
        )
    return normalize_display_text(str(value), limit=512)


def _public_claim_meaning(
    claim: MerchantClaimEvidenceData,
) -> str | None:
    normalized = claim.normalized_value
    if normalized is not None:
        normalized = normalize_display_text(normalized, limit=128)
        if (
            _CJK.search(normalized)
            and is_safe_soft_fact_text(
                normalized,
                attribution="merchant_claim",
                field_key=claim.field_key,
            )
        ):
            return normalized
    display = normalize_display_text(claim.display_claim, limit=160)
    if is_safe_soft_fact_text(
        display,
        attribution="merchant_claim",
        field_key=claim.field_key,
    ):
        return display
    return None


def _group_by_product(values: Sequence[object]) -> dict[int, tuple]:
    grouped: dict[int, list[object]] = {}
    for value in values:
        product_id = getattr(value, "product_id", None)
        if not isinstance(product_id, int) or isinstance(product_id, bool):
            raise TypeError("presentation evidence requires product IDs")
        grouped.setdefault(product_id, []).append(value)
    return {
        product_id: tuple(items)
        for product_id, items in grouped.items()
    }


def _stable_fact_id(prefix: str, *values: object) -> str:
    payload = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:{sha256(payload).hexdigest()}"


def _decimal_text(value: Decimal) -> str:
    normalized = format(value, "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _section_order(
    mode: PresentationMode,
    slots: Sequence[CopySlot],
    *,
    responsibility: Responsibility,
) -> tuple[PresentationSectionSpec, ...]:
    if mode == "clarification":
        return (PresentationSectionSpec(kind="question"),)
    if mode == "error":
        return (PresentationSectionSpec(kind="error"),)
    if mode == "consultation":
        return (
            PresentationSectionSpec(kind="observation"),
            PresentationSectionSpec(kind="summary"),
        )
    if mode == "general_knowledge":
        return (
            PresentationSectionSpec(kind="general_knowledge"),
        )
    if mode == "image_identity":
        return (
            PresentationSectionSpec(kind="observation"),
            *(
                PresentationSectionSpec(
                    kind="product",
                    slot_id=slot.slot_id,
                )
                for slot in slots
            ),
            PresentationSectionSpec(kind="full_cards"),
        )
    if not slots:
        return (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="closing"),
        )
    if responsibility.value == "product_knowledge":
        return (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        )
    if responsibility.value == "single_product_suitability":
        return (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="judgement"),
            PresentationSectionSpec(kind="full_cards"),
        )
    sections = [PresentationSectionSpec(kind="summary")]
    if responsibility.value == "comparison":
        return (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="comparison"),
            PresentationSectionSpec(kind="full_cards"),
        )
    sections.extend(
        PresentationSectionSpec(kind="product", slot_id=slot.slot_id)
        for slot in slots
    )
    sections.extend(
        (
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
        )
    )
    return tuple(sections)


def _requested_dimensions(
    *,
    selection_slots: Sequence[SelectionSlotData],
    concept_slots: Sequence[ConceptSlotData],
) -> tuple[str, ...]:
    values = [
        *(
            item.concept_id
            for item in concept_slots
        ),
        *(
            item.field_key
            for item in selection_slots
        ),
    ]
    return tuple(dict.fromkeys(values))


def _normalize_requested_dimensions(
    values: Sequence[str],
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("requested_dimensions must be a sequence")
    normalized = tuple(values)
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        for value in normalized
    ):
        raise ValueError(
            "requested dimensions must be nonempty strings"
        )
    return normalized


def _comparison_evidence(
    *,
    product_id: int,
    selection_slots: Sequence[SelectionSlotData],
    concept_slots: Sequence[ConceptSlotData],
) -> tuple[ComparisonDimensionEvidence, ...]:
    evidence = []
    for item in selection_slots:
        if item.match_status != "matched":
            evidence.append(
                ComparisonDimensionEvidence(
                    product_id=product_id,
                    dimension_id=item.field_key,
                    match_status="unknown",
                )
            )
            continue
        if item.matched_value is None:
            raise AssertionError(
                "matched selection slot requires matched value"
            )
        fact_id = _stable_fact_id(
            "selection",
            product_id,
            item.field_key,
            item.requested_value,
            item.matched_value,
        )
        evidence.append(
            ComparisonDimensionEvidence(
                product_id=product_id,
                dimension_id=item.field_key,
                match_status="matched",
                display_value=item.matched_value,
                fact_ids=(fact_id,),
                source_refs=tuple(item.source_refs),
                attribution=item.attribution,
            )
        )
    for item in concept_slots:
        if item.match_status == "unknown":
            evidence.append(
                ComparisonDimensionEvidence(
                    product_id=product_id,
                    dimension_id=item.concept_id,
                    match_status="unknown",
                )
            )
            continue
        display_value = normalize_display_text(
            "、".join(item.source_values),
            limit=512,
        )
        fact_id = _stable_fact_id(
            "concept",
            product_id,
            item.field_key,
            item.concept_id,
            *item.source_values,
        )
        evidence.append(
            ComparisonDimensionEvidence(
                product_id=product_id,
                dimension_id=item.concept_id,
                match_status=item.match_status,
                display_value=display_value,
                fact_ids=(fact_id,),
                source_refs=tuple(item.source_refs),
                attribution=item.attribution,
            )
        )
    return tuple(evidence)


def _profile_match_evidence(
    *,
    slot: CopySlot,
    evaluation: CandidateEvaluation | None,
    task_constraints: Sequence[TaskConstraint],
) -> ComparisonDimensionEvidence:
    dimensions = _profile_requirement_dimensions(task_constraints)
    if evaluation is None or not dimensions:
        return _unknown_profile_match(slot.product_id)

    statuses: list[str] = []
    support_facts: list[ApprovedSoftFact] = []
    for dimension_id in dimensions:
        field_key = dimension_id.split(".", 1)[0]
        if field_key == "suitable_skin":
            status = evaluation.skin_match
        elif field_key == "efficacy":
            status = evaluation.efficacy_match
        else:
            evidence = next(
                (
                    item
                    for item in slot.comparison_evidence
                    if item.dimension_id == dimension_id
                ),
                None,
            )
            status = (
                evidence.match_status
                if evidence is not None
                else "unknown"
            )
        statuses.append(
            "unknown" if status == "not_applicable" else status
        )
        fact = next(
            (
                item
                for item in slot.approved_soft_facts
                if (
                    item.field_key == field_key
                    and (
                        "." not in dimension_id
                        or dimension_id in item.dimension_ids
                    )
                )
            ),
            None,
        )
        if (
            fact is None
            or statuses[-1] not in {"matched", "mismatch"}
        ):
            return _unknown_profile_match(slot.product_id)
        support_facts.append(fact)

    selected_fact_ids = tuple(dict.fromkeys(
        fact.fact_id for fact in support_facts
    ))
    attributions = {
        fact.attribution
        for fact in support_facts
    }
    if len(selected_fact_ids) > 3 or len(attributions) != 1:
        return _unknown_profile_match(slot.product_id)
    match_status = (
        "mismatch" if "mismatch" in statuses else "matched"
    )
    selected_facts = tuple(
        next(
            fact
            for fact in support_facts
            if fact.fact_id == fact_id
        )
        for fact_id in selected_fact_ids
    )
    attribution = selected_facts[0].attribution
    return ComparisonDimensionEvidence(
        product_id=slot.product_id,
        dimension_id="profile_match",
        match_status=match_status,
        display_value="；".join(
            _comparison_fact_value(fact)
            for fact in selected_facts
        ),
        fact_ids=tuple(fact.fact_id for fact in selected_facts),
        source_refs=tuple(dict.fromkeys(
            source_ref
            for fact in selected_facts
            for source_ref in fact.source_refs
        ))[:8],
        attribution=attribution,
    )


def _unknown_profile_match(
    product_id: int,
) -> ComparisonDimensionEvidence:
    return ComparisonDimensionEvidence(
        product_id=product_id,
        dimension_id="profile_match",
        match_status="unknown",
    )


def _profile_requirement_dimensions(
    constraints: Sequence[TaskConstraint],
) -> tuple[str, ...]:
    dimensions: list[str] = []
    for constraint in constraints:
        if isinstance(constraint, SkinConstraint):
            dimensions.append("suitable_skin")
        elif isinstance(constraint, EfficacyConstraint):
            dimensions.append("efficacy")
        elif isinstance(constraint, ConceptConstraint):
            dimensions.append(constraint.concept_id)
        elif isinstance(constraint, FacetConstraint):
            dimensions.append(constraint.field_key)
        elif isinstance(constraint, InclusionConstraint):
            dimensions.append("ingredients_present")
    return tuple(dict.fromkeys(dimensions))


def _comparison_fact_value(fact: ApprovedSoftFact) -> str:
    value = fact.plain_meaning
    label = {
        "suitable_skin": "适合肤质",
        "efficacy": "功效方向",
        "ingredients_present": "核心成分",
    }.get(fact.field_key)
    if label is not None:
        value = value.removeprefix(f"{label}：")
    return value


def _approved_constraints(
    *,
    task_constraints: Sequence[TaskConstraint],
    selection_slots: Sequence[SelectionSlotData],
    concept_slots: Sequence[ConceptSlotData],
) -> tuple[ApprovedConstraint, ...]:
    output = list(_task_constraint_authority(task_constraints))
    seen_ids = {item.constraint_id for item in output}
    seen: set[tuple[str, ...]] = set()
    for item in selection_slots:
        identity = (
            "facet",
            item.field_key,
            item.requested_value,
        )
        if identity in seen:
            continue
        seen.add(identity)
        constraint = ApprovedConstraint(
            constraint_id=_constraint_id(*identity),
            kind="facet",
            display_value=(
                f"{item.field_key}：{item.requested_value}"
            ),
        )
        if constraint.constraint_id not in seen_ids:
            seen_ids.add(constraint.constraint_id)
            output.append(constraint)
    for item in concept_slots:
        identity = (
            "concept",
            item.concept_id,
            item.polarity,
        )
        if identity in seen:
            continue
        seen.add(identity)
        constraint = ApprovedConstraint(
            constraint_id=_constraint_id(*identity),
            kind="concept",
            display_value=(
                f"{'偏好' if item.polarity == 'prefer' else '避开'} "
                f"{item.concept_id}"
            ),
        )
        if constraint.constraint_id not in seen_ids:
            seen_ids.add(constraint.constraint_id)
            output.append(constraint)
    return tuple(output)


def _task_constraint_authority(
    constraints: Sequence[TaskConstraint],
) -> tuple[ApprovedConstraint, ...]:
    output = []
    seen: set[str] = set()
    for constraint in constraints:
        if isinstance(constraint, BudgetConstraint):
            values = (
                (
                    "minimum",
                    _decimal_text(constraint.minimum),
                )
                if constraint.minimum is not None
                else None,
                (
                    "maximum",
                    _decimal_text(constraint.maximum),
                )
                if constraint.maximum is not None
                else None,
            )
            parts = tuple(value for value in values if value is not None)
            display = (
                f"预算{parts[0][1]}-{parts[1][1]}元"
                if len(parts) == 2
                else (
                    f"预算下限{parts[0][1]}元"
                    if parts[0][0] == "minimum"
                    else f"预算上限{parts[0][1]}元"
                )
            )
            approved = ApprovedConstraint(
                constraint_id=_constraint_id(
                    "budget",
                    *(f"{key}={value}" for key, value in parts),
                ),
                kind="budget",
                display_value=display,
            )
        elif isinstance(constraint, CategoryConstraint):
            value = constraint.value.value
            approved = ApprovedConstraint(
                constraint_id=_constraint_id("category", value),
                kind="category",
                display_value=f"品类：{value}",
            )
        elif isinstance(constraint, FacetConstraint):
            approved = ApprovedConstraint(
                constraint_id=_constraint_id(
                    "facet",
                    constraint.field_key,
                    constraint.value,
                ),
                kind="facet",
                display_value=(
                    f"{constraint.field_key}：{constraint.value}"
                ),
            )
        elif isinstance(constraint, ConceptConstraint):
            approved = ApprovedConstraint(
                constraint_id=_constraint_id(
                    "concept",
                    constraint.concept_id,
                    constraint.polarity,
                ),
                kind="concept",
                display_value=(
                    f"{'偏好' if constraint.polarity == 'prefer' else '避开'} "
                    f"{constraint.concept_id}"
                ),
            )
        else:
            if isinstance(constraint, SkinConstraint):
                key = "skin"
                value = constraint.value.value
                display = f"肤质：{value}"
            elif isinstance(constraint, EfficacyConstraint):
                key = "efficacy"
                value = constraint.value.value
                display = f"功效需求：{value}"
            elif isinstance(constraint, ExclusionConstraint):
                key = "exclude"
                value = constraint.value
                display = f"避开：{value}"
            elif isinstance(constraint, InclusionConstraint):
                key = "include"
                value = constraint.value
                display = f"需要包含：{value}"
            else:
                raise TypeError("unsupported presentation constraint")
            approved = ApprovedConstraint(
                constraint_id=_constraint_id(key, value),
                kind="context",
                display_value=display,
            )
        if approved.constraint_id in seen:
            continue
        seen.add(approved.constraint_id)
        output.append(approved)
    return tuple(output)


def _constraint_id(kind: str, *values: str) -> str:
    payload = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"turn:{kind}:{sha256(payload).hexdigest()}"


def _compact_tag_evidence(
    *,
    card: ProductCard,
    selection_slots: Sequence[SelectionSlotData],
    concept_slots: Sequence[ConceptSlotData],
    merchant_claims: Sequence[MerchantClaimEvidenceData],
) -> tuple[CompactTagEvidence, ...]:
    evidence: list[CompactTagEvidence] = []
    for item in selection_slots:
        if (
            item.match_status != "matched"
            or item.matched_value is None
            or item.attribution is None
        ):
            continue
        fact_id = _stable_fact_id(
            "selection",
            card.product_id,
            item.field_key,
            item.requested_value,
            item.matched_value,
            item.matched_value,
        )
        evidence.append(
            CompactTagEvidence(
                product_id=card.product_id,
                fact_id=fact_id,
                field_key=item.field_key,
                label=normalize_display_text(
                    item.matched_value,
                    limit=24,
                ),
                source_refs=tuple(item.source_refs),
                attribution=item.attribution,
            )
        )
    for item in concept_slots:
        if (
            item.match_status != "matched"
            or not item.source_values
            or item.attribution is None
        ):
            continue
        fact_id = _stable_fact_id(
            "concept",
            card.product_id,
            item.field_key,
            item.concept_id,
            *item.source_values,
        )
        evidence.append(
            CompactTagEvidence(
                product_id=card.product_id,
                fact_id=fact_id,
                field_key=item.field_key,
                label=normalize_display_text(
                    "、".join(item.source_values),
                    limit=24,
                ),
                source_refs=tuple(item.source_refs),
                attribution=item.attribution,
            )
        )
    for fact in card.category_facts:
        if (
            fact.state != "known"
            or presentation_fact_role(fact.field_key) != "narrative"
        ):
            continue
        label = _category_fact_text(fact)
        if not label:
            continue
        evidence.append(
            CompactTagEvidence(
                product_id=card.product_id,
                fact_id=(
                    f"card:{card.product_id}:"
                    f"{fact.field_key}:soft_display"
                ),
                field_key=fact.field_key,
                label=normalize_display_text(label, limit=24),
                source_refs=(
                    f"card:{card.product_id}:{fact.field_key}",
                ),
                attribution="verified_fact",
            )
        )
    for claim in merchant_claims:
        if claim.claim_scope != "ordinary":
            continue
        label = _public_claim_meaning(claim)
        if label is None:
            continue
        evidence.append(
            CompactTagEvidence(
                product_id=card.product_id,
                fact_id=claim.claim_id,
                field_key=claim.field_key,
                label=normalize_display_text(label, limit=24),
                source_refs=(claim.source_locator,),
                attribution="merchant_claim",
            )
        )
    output = []
    seen: set[str] = set()
    for item in evidence:
        if item.fact_id in seen:
            continue
        seen.add(item.fact_id)
        output.append(item)
    return tuple(output[:24])


def _copy_budget(mode: PresentationMode) -> CopyLengthBudget:
    if mode in {
        "general_knowledge",
        "product_knowledge",
        "consultation",
    }:
        return CopyLengthBudget(
            summary_max_chars=240,
            positioning_max_chars=150,
            advisor_reason_max_chars=120,
            closing_max_chars=220,
        )
    return CopyLengthBudget(
        summary_max_chars=260,
        positioning_max_chars=150,
        advisor_reason_max_chars=110,
        closing_max_chars=200,
    )


__all__ = ["build_presentation_packet", "normalize_display_text"]
