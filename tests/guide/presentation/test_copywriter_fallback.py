from __future__ import annotations

import pytest

from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CopyLengthBudget,
    CopySlot,
    DirectCaution,
    LockedFact,
    PresentationMode,
    PresentationPacket,
    PresentationSectionSpec,
    build_copywriter_section_specs,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
from app.guide.presentation.copywriter_validation import (
    validate_copywriter_draft,
)


PRODUCT_MODES: tuple[PresentationMode, ...] = (
    "recommendation",
    "comparison",
    "single_product",
    "product_knowledge",
    "followup",
    "revision",
    "image_identity",
    "image_recommendation",
    "image_suitability",
    "image_comparison",
)
ZERO_PRODUCT_MODES: tuple[PresentationMode, ...] = (
    "general_knowledge",
    "consultation",
    "clarification",
    "error",
)
INTERNAL_PUBLIC_TERMS = (
    "候选",
    "代码核对",
    "硬条件",
    "证据等级",
    "放行",
    "页面记录版本",
    "本轮筛选",
)


def _section(
    draft,
    kind: str,
    slot_id: str | None = None,
):
    return next(
        section
        for section in draft.sections
        if (section.kind, section.slot_id) == (kind, slot_id)
    )


def _rendered_sections(draft) -> str:
    return " ".join(
        text
        for section in draft.sections
        for text in (
            section.content.text,
            (
                section.advisor_reason.text
                if section.advisor_reason is not None
                else ""
            ),
        )
        if text
    )


def _packet(mode: PresentationMode) -> PresentationPacket:
    has_product = mode in PRODUCT_MODES
    first = CopySlot(
        slot_id="p1",
        product_id=55,
        name="绝不能出现在文案里的商品名",
        category_profile="suncare",
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id="soft-texture",
                product_id=55,
                field_key="texture",
                plain_meaning="质地轻薄清透、不黏腻",
                attribution="verified_fact",
                source_refs=("source:soft",),
            ),
        ),
        locked_facts=(
            LockedFact(
                fact_id="locked-price",
                product_id=55,
                kind="price",
                label="参考价",
                display_value="¥88.11",
                source_refs=("source:price",),
            ),
            LockedFact(
                fact_id="locked-ingredient",
                product_id=55,
                kind="ingredient",
                label="成分",
                display_value="氧化锌",
                source_refs=("source:ingredient",),
            ),
        ),
        required_cautions=(
            DirectCaution(
                caution_id="warning",
                product_id=55,
                severity="high",
                text="特别敏感人群请勿使用。",
                source_refs=("source:warning",),
            ),
        ),
    )
    slots = (first,) if has_product else ()
    if mode in {"comparison", "image_comparison"}:
        second = first.model_copy(
            update={
                "slot_id": "p2",
                "product_id": 57,
                "approved_soft_facts": tuple(
                    fact.model_copy(
                        update={
                            "fact_id": f"{fact.fact_id}-second",
                            "product_id": 57,
                            "source_refs": ("source:soft:second",),
                        }
                    )
                    for fact in first.approved_soft_facts
                ),
                "locked_facts": (),
                "required_cautions": (),
            },
            deep=True,
        )
        slots = (first, second)
        section_order = (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="comparison"),
            PresentationSectionSpec(kind="full_cards"),
        )
    elif mode in {
        "recommendation",
        "followup",
        "revision",
        "image_recommendation",
    }:
        section_order = (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="product", slot_id="p1"),
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
        )
    elif mode == "product_knowledge":
        section_order = (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        )
    elif mode in {"single_product", "image_suitability"}:
        section_order = (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="judgement"),
            PresentationSectionSpec(kind="full_cards"),
        )
    elif mode == "image_identity":
        section_order = (
            PresentationSectionSpec(kind="observation"),
            PresentationSectionSpec(kind="full_cards"),
        )
    elif mode == "clarification":
        section_order = (PresentationSectionSpec(kind="question"),)
    elif mode == "error":
        section_order = (PresentationSectionSpec(kind="error"),)
    elif mode == "consultation":
        section_order = (
            PresentationSectionSpec(kind="observation"),
            PresentationSectionSpec(kind="summary"),
        )
    elif mode == "general_knowledge":
        section_order = (
            PresentationSectionSpec(kind="general_knowledge"),
        )
    else:
        raise AssertionError(f"unsupported test mode {mode}")
    return PresentationPacket(
        mode=mode,
        user_need_summary="需要一段稳定保底文案",
        winner_status="INSUFFICIENT_FOR_WINNER",
        slots=slots,
        section_order=section_order,
        copy_budget=CopyLengthBudget(
            summary_max_chars=180,
            positioning_max_chars=90,
            advisor_reason_max_chars=100,
            closing_max_chars=180,
        ),
    )


@pytest.mark.parametrize(
    "mode",
    (*PRODUCT_MODES, *ZERO_PRODUCT_MODES),
)
def test_fallback_is_mode_specific_valid_and_deterministic(
    mode: PresentationMode,
) -> None:
    packet = _packet(mode)

    first = fallback_copy(packet)
    second = fallback_copy(packet)

    assert first == second
    assert first.mode == mode
    assert [
        (section.kind, section.slot_id)
        for section in first.sections
    ] == [
        (spec.kind, spec.slot_id)
        for spec in build_copywriter_section_specs(packet)
    ]
    assert all(
        len(section.content.text) <= spec.copy_max_chars
        for section, spec in zip(
            first.sections,
            build_copywriter_section_specs(packet),
            strict=True,
        )
    )
    assert validate_copywriter_draft(packet, first) == first


@pytest.mark.parametrize(
    "mode",
    (*PRODUCT_MODES, *ZERO_PRODUCT_MODES),
)
def test_fallback_never_exposes_internal_processing_language(
    mode: PresentationMode,
) -> None:
    draft = fallback_copy(_packet(mode))
    rendered = _rendered_sections(draft)

    assert not any(term in rendered for term in INTERNAL_PUBLIC_TERMS)
    assert "品牌主打：品牌主打" not in rendered


def test_fallback_uses_soft_meaning_without_leaking_code_owned_facts() -> None:
    packet = _packet("recommendation")

    draft = fallback_copy(packet)
    rendered = _rendered_sections(draft)
    product = _section(draft, "product", "p1")

    assert "轻薄清透" in rendered
    assert {
        *product.content.used_fact_ids,
        *product.advisor_reason.used_fact_ids,
    } == {
        "soft-texture",
    }
    assert "绝不能出现在文案里的商品名" not in rendered
    assert "88.11" not in rendered
    assert "氧化锌" not in rendered
    assert "特别敏感人群请勿使用" not in rendered


def test_fallback_keeps_facts_out_of_constraints_only_summary() -> None:
    packet = _packet("single_product")

    draft = fallback_copy(packet)
    summary = _section(draft, "summary")

    assert summary.content.used_fact_ids == ()
    assert validate_copywriter_draft(packet, draft) == draft


def test_fallback_selects_the_requested_child_dimension() -> None:
    base = _packet("product_knowledge")
    facts = (
        ApprovedSoftFact(
            fact_id="soft-anti-age",
            product_id=55,
            field_key="efficacy",
            dimension_ids=("efficacy.anti_age",),
            plain_meaning="紧致淡纹",
            attribution="verified_fact",
            source_refs=("source:anti-age",),
        ),
        ApprovedSoftFact(
            fact_id="soft-repair",
            product_id=55,
            field_key="efficacy",
            dimension_ids=("efficacy.repair",),
            plain_meaning="修护屏障",
            attribution="verified_fact",
            source_refs=("source:repair",),
        ),
    )
    packet = base.model_copy(
        update={
            "slots": (
                base.slots[0].model_copy(
                    update={"approved_soft_facts": facts}
                ),
            ),
            "requested_dimensions": ("efficacy.repair",),
        }
    )

    draft = fallback_copy(packet)
    answer = _section(draft, "answer", "p1")

    assert answer.content.used_fact_ids == ("soft-repair",)
    assert validate_copywriter_draft(packet, draft) == draft
def test_fallback_preserves_merchant_and_consumer_attribution() -> None:
    base = _packet("recommendation")
    slot = base.slots[0].model_copy(
        update={
            "approved_soft_facts": (
                ApprovedSoftFact(
                    fact_id="merchant-texture",
                    product_id=55,
                    field_key="texture",
                    plain_meaning="主打轻薄肤感",
                    attribution="merchant_claim",
                    source_refs=("source:merchant",),
                ),
                ApprovedSoftFact(
                    fact_id="consumer-texture",
                    product_id=55,
                    field_key="finish",
                    plain_meaning="使用后更偏清爽",
                    attribution="consumer_report",
                    source_refs=("source:consumer",),
                ),
            )
        }
    )
    packet = base.model_copy(update={"slots": (slot,)})

    draft = fallback_copy(packet)
    product = _section(draft, "product", "p1")
    product_text = " ".join(
        (
            product.content.text,
            product.advisor_reason.text,
        )
    )

    assert "品牌主打" in product_text
    assert "用户反馈" in product_text
    assert validate_copywriter_draft(packet, draft) == draft


def test_fallback_keeps_approved_merchant_numbers_and_ingredients() -> None:
    base = _packet("recommendation")
    slot = base.slots[0].model_copy(
        update={
            "approved_soft_facts": (
                ApprovedSoftFact(
                    fact_id="merchant-efficacy",
                    product_id=55,
                    field_key="efficacy",
                    plain_meaning="品牌主打：12周充盈凹陷",
                    attribution="merchant_claim",
                    source_refs=("source:merchant:efficacy",),
                ),
                ApprovedSoftFact(
                    fact_id="merchant-ingredient",
                    product_id=55,
                    field_key="ingredients_present",
                    plain_meaning="品牌主打：12%玻色因溶液、透明质酸",
                    attribution="merchant_claim",
                    source_refs=("source:merchant:ingredient",),
                ),
            )
        }
    )
    packet = base.model_copy(
        update={
            "slots": (slot,),
            "copy_budget": CopyLengthBudget(
                summary_max_chars=180,
                positioning_max_chars=200,
                advisor_reason_max_chars=120,
                closing_max_chars=180,
            ),
        }
    )

    draft = fallback_copy(packet)
    product = _section(draft, "product", "p1")
    product_text = " ".join(
        (
            product.content.text,
            product.advisor_reason.text,
        )
    )

    assert "12周充盈凹陷" in product_text
    assert "12%玻色因溶液" in product_text
    assert validate_copywriter_draft(packet, draft) == draft


def test_fallback_uses_substantive_subset_without_forcing_full_coverage() -> None:
    base = _packet("recommendation")
    facts = tuple(
        ApprovedSoftFact(
            fact_id=f"soft-{index}",
            product_id=55,
            field_key=f"feature_{index}",
            plain_meaning=meaning,
            attribution="verified_fact",
            source_refs=(f"source:{index}",),
        )
        for index, meaning in enumerate(
            (
                "肤感轻薄",
                "收尾清爽",
                "成膜利落",
                "适合通勤",
                "后续上妆更省心",
            )
        )
    )
    slot = base.slots[0].model_copy(
        update={"approved_soft_facts": facts}
    )
    packet = base.model_copy(update={"slots": (slot,)})

    draft = fallback_copy(packet)
    product = _section(draft, "product", "p1")

    used = {
        *product.content.used_fact_ids,
        *product.advisor_reason.used_fact_ids,
    }
    assert 1 <= len(used) <= 2
    assert validate_copywriter_draft(packet, draft) == draft


def test_fallback_compacts_long_merged_atoms_without_forcing_coverage() -> None:
    base = _packet("recommendation")
    facts = tuple(
        ApprovedSoftFact(
            fact_id=f"long-{index}",
            product_id=55,
            field_key=f"feature_{index}",
            plain_meaning=(
                f"商家主打：{meaning}；"
                f"商家主打：{meaning}更适合日常使用安排"
            ),
            attribution="merchant_claim",
            source_refs=(f"source:long:{index}",),
        )
        for index, meaning in enumerate(
            (
                "轻薄清透不黏腻",
                "收尾自然贴肤",
                "成膜节奏利落",
                "后续上妆更省心",
                "通勤使用更顺手",
                "肤感路线更偏清爽",
                "日常补涂更好安排",
                "整体使用负担更轻",
            )
        )
    )
    slot = base.slots[0].model_copy(
        update={"approved_soft_facts": facts}
    )
    packet = base.model_copy(update={"slots": (slot,)})

    draft = fallback_copy(packet)
    product = _section(draft, "product", "p1")

    used = {
        *product.content.used_fact_ids,
        *product.advisor_reason.used_fact_ids,
    }
    assert 1 <= len(used) <= 2
    assert validate_copywriter_draft(packet, draft) == draft


def test_fallback_covers_requested_dimensions_instead_of_first_two_facts() -> None:
    base = _packet("product_knowledge")
    facts = (
        ApprovedSoftFact(
            fact_id="soft-efficacy",
            product_id=55,
            field_key="efficacy",
            plain_meaning="修护屏障",
            attribution="verified_fact",
            source_refs=("source:efficacy",),
        ),
        ApprovedSoftFact(
            fact_id="soft-texture",
            product_id=55,
            field_key="texture",
            plain_meaning="轻薄清爽",
            attribution="verified_fact",
            source_refs=("source:texture",),
        ),
        ApprovedSoftFact(
            fact_id="soft-fragrance",
            product_id=55,
            field_key="fragrance_description",
            plain_meaning="清新香调",
            attribution="verified_fact",
            source_refs=("source:fragrance",),
        ),
    )
    packet = base.model_copy(
        update={
            "slots": (
                base.slots[0].model_copy(
                    update={"approved_soft_facts": facts}
                ),
            ),
            "requested_dimensions": (
                "efficacy",
                "texture",
                "fragrance_description",
            ),
        }
    )

    draft = fallback_copy(packet)
    answer = _section(draft, "answer", "p1")

    assert set(answer.content.used_fact_ids) == {
        "soft-efficacy",
        "soft-texture",
        "soft-fragrance",
    }
    assert validate_copywriter_draft(packet, draft) == draft
