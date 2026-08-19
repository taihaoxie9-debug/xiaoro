from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    ClarificationPresentationData,
    CopyLengthBudget,
    CopySlot,
    CopywriterDraft,
    CopywriterTelemetry,
    DirectCaution,
    DirectFactComponent,
    LockedFact,
    PresentationContractData,
    PresentationPacket,
    PresentationSection,
    PresentationSectionSpec,
    ProductCopy,
    RecommendationPresentationData,
)


def _soft_fact(
    fact_id: str = "soft-texture",
    *,
    product_id: int = 55,
) -> ApprovedSoftFact:
    return ApprovedSoftFact(
        fact_id=fact_id,
        product_id=product_id,
        field_key="texture",
        plain_meaning="质地轻薄清透、不黏腻",
        attribution="merchant_claim",
        source_refs=("source:merchant:55:texture",),
    )


def _locked_fact(
    fact_id: str = "locked-price",
    *,
    product_id: int = 55,
) -> LockedFact:
    return LockedFact(
        fact_id=fact_id,
        product_id=product_id,
        kind="price",
        label="参考价",
        display_value="¥88.11",
        source_refs=("source:canonical:55:price",),
    )


def _caution(
    caution_id: str = "warning-sensitive",
    *,
    product_id: int = 55,
) -> DirectCaution:
    return DirectCaution(
        caution_id=caution_id,
        product_id=product_id,
        severity="high",
        text="特别敏感人群请勿使用。",
        source_refs=("source:package:55:warning",),
    )


def _slot(
    slot_id: str = "p1",
    *,
    product_id: int = 55,
) -> CopySlot:
    return CopySlot(
        slot_id=slot_id,
        product_id=product_id,
        name="清透防晒乳",
        category_profile="suncare",
        approved_soft_facts=(_soft_fact(product_id=product_id),),
        locked_facts=(_locked_fact(product_id=product_id),),
        required_cautions=(_caution(product_id=product_id),),
    )


def _budget() -> CopyLengthBudget:
    return CopyLengthBudget(
        summary_max_chars=180,
        positioning_max_chars=90,
        advisor_reason_max_chars=100,
        closing_max_chars=180,
    )


def _packet() -> PresentationPacket:
    return PresentationPacket(
        mode="recommendation",
        user_need_summary="500元内，油敏肌，防晒",
        winner_status="INSUFFICIENT_FOR_WINNER",
        slots=(_slot(),),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="product", slot_id="p1"),
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
            PresentationSectionSpec(kind="pitfalls"),
        ),
        copy_budget=_budget(),
    )


def _draft() -> CopywriterDraft:
    return CopywriterDraft(
        mode="recommendation",
        summary_copy="预算内有一款可以继续看，但现有证据不足以替你拍板。",
        product_copy=(
            ProductCopy(
                slot_id="p1",
                positioning="更偏轻盈清爽的日常防晒路线。",
                advisor_reason="如果不喜欢明显膜感，可以先把它放进对比名单。",
                used_soft_fact_ids=("soft-texture",),
            ),
        ),
        closing_copy="第一次使用仍建议先做局部测试。",
    )


def _telemetry() -> CopywriterTelemetry:
    return CopywriterTelemetry(
        provider="offline",
        model="copy-test",
        prompt_tokens=120,
        completion_tokens=60,
        total_tokens=180,
        latency_ms=25.0,
        fallback_reason=None,
    )


def test_packet_and_draft_freeze_nested_collections() -> None:
    packet = _packet()
    draft = _draft()

    assert isinstance(packet.slots, tuple)
    assert isinstance(packet.section_order, tuple)
    assert isinstance(packet.slots[0].approved_soft_facts, tuple)
    assert isinstance(draft.product_copy, tuple)
    assert draft.product_copy[0].used_soft_fact_ids == ("soft-texture",)


def test_packet_rejects_duplicate_product_or_slot_identity() -> None:
    with pytest.raises(ValidationError):
        PresentationPacket(
            mode="recommendation",
            user_need_summary="防晒",
            winner_status="WINNER",
            slots=(
                _slot("p1", product_id=55),
                _slot("p1", product_id=57),
            ),
            section_order=(
                PresentationSectionSpec(kind="summary"),
                PresentationSectionSpec(kind="product", slot_id="p1"),
            ),
            copy_budget=_budget(),
        )

    with pytest.raises(ValidationError):
        PresentationPacket(
            mode="recommendation",
            user_need_summary="防晒",
            winner_status="WINNER",
            slots=(
                _slot("p1", product_id=55),
                _slot("p2", product_id=55),
            ),
            section_order=(
                PresentationSectionSpec(kind="summary"),
                PresentationSectionSpec(kind="product", slot_id="p1"),
                PresentationSectionSpec(kind="product", slot_id="p2"),
            ),
            copy_budget=_budget(),
        )


def test_copywriter_draft_rejects_duplicate_or_reordered_slots() -> None:
    with pytest.raises(ValidationError):
        CopywriterDraft(
            mode="recommendation",
            summary_copy="摘要",
            product_copy=(
                _draft().product_copy[0],
                _draft().product_copy[0],
            ),
            closing_copy="建议",
        )


def test_recommendation_contract_binds_both_card_forms_to_product_sections() -> None:
    contract = RecommendationPresentationData(
        copy_source="model",
        sections=(
            PresentationSection(
                kind="summary",
                copy_text="预算内有一款可看。",
            ),
            PresentationSection(
                kind="product",
                slot_id="p1",
                product_id=55,
                copy_text="更偏轻盈清爽的日常防晒路线。",
                advisor_reason="适合更看重清爽肤感的通勤场景。",
                direct_facts=(
                    DirectFactComponent(
                        fact_id="locked-price",
                        label="参考价",
                        display_value="¥88.11",
                    ),
                ),
            ),
            PresentationSection(
                kind="closing",
                copy_text="先局部测试。",
            ),
            PresentationSection(kind="full_cards"),
            PresentationSection(kind="pitfalls"),
        ),
        card_display=CardDisplayContract(
            mode="single",
            visible_product_ids=(55,),
            max_cards=1,
            reason="recommendation",
        ),
        telemetry=_telemetry(),
    )

    parsed = TypeAdapter(PresentationContractData).validate_python(
        contract.model_dump(mode="python")
    )

    assert parsed.mode == "recommendation"
    assert parsed.card_display.visible_product_ids == (55,)


def test_presentation_contract_rejects_card_product_mismatch() -> None:
    with pytest.raises(ValidationError):
        RecommendationPresentationData(
            copy_source="model",
            sections=(
                PresentationSection(kind="summary", copy_text="摘要"),
                PresentationSection(
                    kind="product",
                    slot_id="p1",
                    product_id=55,
                    copy_text="商品说明",
                    advisor_reason="推荐理由",
                ),
                PresentationSection(kind="full_cards"),
            ),
            card_display=CardDisplayContract(
                mode="single",
                visible_product_ids=(57,),
                max_cards=1,
                reason="recommendation",
            ),
            telemetry=_telemetry(),
        )


def test_zero_card_contract_rejects_product_sections() -> None:
    empty = ClarificationPresentationData(
        copy_source="fallback",
        sections=(
            PresentationSection(
                kind="question",
                copy_text="请告诉我想看的商品品类。",
            ),
        ),
        card_display=CardDisplayContract(
            mode="none",
            visible_product_ids=(),
            max_cards=0,
            reason=None,
        ),
        telemetry=CopywriterTelemetry(
            provider="disabled",
            model="deterministic",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            fallback_reason="copywriter_not_called",
        ),
    )
    assert empty.mode == "clarification"

    with pytest.raises(ValidationError):
        ClarificationPresentationData(
            copy_source="fallback",
            sections=(
                PresentationSection(
                    kind="product",
                    slot_id="p1",
                    product_id=55,
                    copy_text="不应出现",
                    advisor_reason="不应出现",
                ),
            ),
            card_display=CardDisplayContract(
                mode="none",
                visible_product_ids=(),
                max_cards=0,
                reason=None,
            ),
            telemetry=empty.telemetry,
        )


def test_locked_numeric_fact_keeps_decimal_display_as_code_owned_text() -> None:
    fact = LockedFact(
        fact_id="locked-spf",
        product_id=55,
        kind="numeric",
        label="防晒指数",
        display_value="SPF48 PA+++",
        numeric_value=Decimal("48"),
        source_refs=("source:canonical:55:spf",),
    )

    assert fact.numeric_value == Decimal("48")
    assert fact.display_value == "SPF48 PA+++"


def test_copy_slot_accepts_eight_bounded_soft_facts() -> None:
    payload = _slot().model_dump(mode="python")
    payload["approved_soft_facts"] = tuple(
        _soft_fact(f"fact-{index}")
        for index in range(8)
    )

    slot = CopySlot.model_validate(payload, strict=True)

    assert len(slot.approved_soft_facts) == 8
