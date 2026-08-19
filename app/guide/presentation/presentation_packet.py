from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from hashlib import sha256
import json
import re

from app.guide.presentation.contracts import (
    CardDisplayContract,
    DisplayCategoryFact,
    ProductCard,
)
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CopyLengthBudget,
    CopySlot,
    DirectCaution,
    FactAttribution,
    LockedFact,
    PresentationMode,
    PresentationPacket,
    PresentationSectionSpec,
)
from app.guide.presentation.copywriter_validation import (
    is_safe_soft_fact_text,
)
from app.guide.presentation.fact_admission import (
    presentation_fact_role,
)
from app.guide.presentation.narrative_atoms import build_narrative_atoms
from app.guide.presentation.sse_events import (
    ConceptSlotData,
    MerchantClaimEvidenceData,
    SelectionSlotData,
)
from app.guide.retrieval.pitfall_contracts import TypedPitfall
from app.guide.retrieval.review_summary_contracts import (
    ReviewSummaryResult,
)


_SPACE = re.compile(r"\s+")
_CJK = re.compile(r"[\u3400-\u9fff]")


def build_presentation_packet(
    *,
    mode: PresentationMode,
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

    slots = tuple(
        _build_slot(
            index=index,
            card=card_by_id[product_id],
            selection_slots=selections_by_product.get(product_id, ()),
            concept_slots=concepts_by_product.get(product_id, ()),
            merchant_claims=claims_by_product.get(product_id, ()),
            review_summaries=reviews_by_product.get(product_id, ()),
            pitfalls=pitfalls_by_product.get(product_id, ()),
            proof_points=proof_points_by_product.get(product_id, ()),
            distinctive_fields=distinctive_fields,
        )
        for index, product_id in enumerate(visible_ids, start=1)
    )
    return PresentationPacket(
        mode=mode,
        user_need_summary=normalize_display_text(
            user_need_summary,
            limit=512,
        ),
        winner_status=winner_status,
        slots=slots,
        section_order=_section_order(mode, slots),
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
                plain_meaning=_attributed_soft_meaning(
                    "、".join(item.source_values),
                    attribution=item.attribution,
                    limit=256,
                ),
                attribution=item.attribution,
                source_refs=tuple(item.source_refs),
            )
        )
    soft_facts.extend(_category_soft_facts(card))
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
    preferred_fields = {
        item.field_key for item in selection_slots
    }.union(item.field_key for item in concept_slots)
    narrative_atoms = build_narrative_atoms(
        _deduplicate_soft_facts(soft_facts),
        preferred_fields=preferred_fields,
        distinctive_fields=distinctive_fields,
    )
    return CopySlot(
        slot_id=f"p{index}",
        product_id=card.product_id,
        name=card.name or f"商品 {card.product_id}",
        category_profile=card.category_profile.value,
        approved_soft_facts=narrative_atoms,
        locked_facts=_locked_facts(card, proof_points=proof_points),
        required_cautions=tuple(caution_values[:6]),
    )


def _category_soft_facts(card: ProductCard) -> tuple[ApprovedSoftFact, ...]:
    facts: list[ApprovedSoftFact] = []
    for fact in card.category_facts:
        if (
            fact.state != "known"
            or presentation_fact_role(fact.field_key) != "narrative"
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


def _locked_facts(
    card: ProductCard,
    *,
    proof_points: Sequence[LockedFact],
) -> tuple[LockedFact, ...]:
    facts: list[LockedFact] = []
    specification = card.specification or ""
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
    display = normalize_display_text(claim.display_claim, limit=160)
    if is_safe_soft_fact_text(
        display,
        attribution="merchant_claim",
        field_key=claim.field_key,
    ):
        return display
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
    return None


def _deduplicate_soft_facts(
    facts: Sequence[ApprovedSoftFact],
) -> tuple[ApprovedSoftFact, ...]:
    output: list[ApprovedSoftFact] = []
    seen: set[tuple[str, str, str]] = set()
    for fact in facts:
        key = (
            fact.field_key,
            fact.attribution,
            fact.plain_meaning.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(fact)
    return tuple(output)


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
    if not slots:
        return (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="closing"),
        )
    if mode in {"product_knowledge"}:
        return (
            *(
                PresentationSectionSpec(
                    kind="product",
                    slot_id=slot.slot_id,
                )
                for slot in slots
            ),
            PresentationSectionSpec(kind="full_cards"),
        )
    sections = [PresentationSectionSpec(kind="summary")]
    if mode in {"comparison", "image_comparison"}:
        sections.append(PresentationSectionSpec(kind="comparison"))
    sections.extend(
        PresentationSectionSpec(kind="product", slot_id=slot.slot_id)
        for slot in slots
    )
    sections.extend(
        (
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
            PresentationSectionSpec(kind="pitfalls"),
        )
    )
    return tuple(sections)


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
