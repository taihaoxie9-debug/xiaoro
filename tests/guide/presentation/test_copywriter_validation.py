from __future__ import annotations

from collections.abc import Callable

import pytest

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CopyLengthBudget,
    CopySlot,
    CopywriterDraft,
    CopywriterSection,
    DirectCaution,
    LockedFact,
    PresentationPacket,
    PresentationSectionSpec,
    SourceTaggedCopy,
)
from app.guide.presentation.copywriter_references import (
    CopywriterReferenceError,
    bind_copywriter_fact_attribution,
)
from app.guide.presentation.copywriter_validation import (
    CopywriterValidationError,
    CopywriterValidationErrorCode,
    validate_copywriter_draft,
)


def _soft_fact(
    fact_id: str,
    *,
    attribution: str = "verified_fact",
    field_key: str = "texture",
    plain_meaning: str = "质地轻薄清透、不黏腻",
) -> ApprovedSoftFact:
    return ApprovedSoftFact(
        fact_id=fact_id,
        product_id=55,
        field_key=field_key,
        plain_meaning=plain_meaning,
        attribution=attribution,
        source_refs=(f"source:{fact_id}",),
    )


def _packet(
    *,
    winner_status: str | None = "INSUFFICIENT_FOR_WINNER",
    soft_facts: tuple[ApprovedSoftFact, ...] | None = None,
) -> PresentationPacket:
    facts = soft_facts or (
        _soft_fact("soft-texture"),
        _soft_fact(
            "soft-film",
            plain_meaning="成膜速度较快，适合通勤节奏",
        ),
    )
    selected = winner_status in {"SELECTED", "WINNER", "winner"}
    return PresentationPacket(
        mode="recommendation",
        responsibility=Responsibility.RECOMMENDATION,
        recommendation_mode="fit" if selected else "explore",
        user_need_summary="油敏肌通勤防晒",
        winner_status=winner_status,
        winner_product_id=55 if selected else None,
        slots=(
            CopySlot(
                slot_id="p1",
                product_id=55,
                name="清透防晒乳",
                category_profile="suncare",
                approved_soft_facts=facts,
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
                        caution_id="warning-sensitive",
                        product_id=55,
                        severity="high",
                        text="特别敏感人群请勿使用。",
                        source_refs=("source:warning",),
                    ),
                ),
            ),
        ),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="product", slot_id="p1"),
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        copy_budget=CopyLengthBudget(
            summary_max_chars=180,
            positioning_max_chars=90,
            advisor_reason_max_chars=100,
            closing_max_chars=180,
        ),
    )


def _draft(
    *,
    summary: str = "现有信息更适合先看使用路线，不急着直接拍板。",
    summary_winner_claim: str = "none",
    positioning: str = "更偏轻盈不黏的通勤路线。",
    reason: str = "早上赶时间时会更利落。",
    product_sections: tuple[CopywriterSection, ...] | None = None,
    used_fact_ids: tuple[str, ...] = (
        "soft-texture",
        "soft-film",
    ),
    reason_fact_ids: tuple[str, ...] = (),
    reason_winner_claim: str = "none",
    summary_fact_ids: tuple[str, ...] = (),
    summary_constraint_ids: tuple[str, ...] = (),
    closing: str | None = "建议结合下方商品资料再做选择。",
) -> CopywriterDraft:
    product = (
        product_sections
        if product_sections is not None
        else (
            CopywriterSection(
                kind="product",
                slot_id="p1",
                content=SourceTaggedCopy(
                    text=positioning,
                    used_fact_ids=used_fact_ids,
                ),
                advisor_reason=SourceTaggedCopy(
                    text=reason,
                    winner_claim=reason_winner_claim,
                    used_fact_ids=reason_fact_ids,
                ),
            ),
        )
    )
    return CopywriterDraft(
        mode="recommendation",
        sections=(
            CopywriterSection(
                kind="summary",
                content=SourceTaggedCopy(
                    text=summary,
                    winner_claim=summary_winner_claim,
                    used_fact_ids=summary_fact_ids,
                    used_constraint_ids=summary_constraint_ids,
                ),
            ),
            *product,
            *(
                (
                    CopywriterSection(
                        kind="closing",
                        content=SourceTaggedCopy(text=closing),
                    ),
                )
                if closing is not None
                else ()
            ),
        ),
    )


def _invalid(
    packet: PresentationPacket,
    draft: CopywriterDraft,
    code: CopywriterValidationErrorCode,
) -> None:
    with pytest.raises(CopywriterValidationError) as caught:
        validate_copywriter_draft(packet, draft)
    assert caught.value.code is code


def test_validator_accepts_natural_soft_fact_paraphrases() -> None:
    validated = validate_copywriter_draft(_packet(), _draft())

    assert validated.sections[1].content.text == (
        "更偏轻盈不黏的通勤路线。"
    )
    assert validated.sections[1].advisor_reason.text == (
        "早上赶时间时会更利落。"
    )


def test_validator_requires_attribution_in_each_product_copy_block() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-positioning",
                attribution="merchant_claim",
            ),
            _soft_fact(
                "soft-reason",
                attribution="merchant_claim",
            ),
        )
    )
    draft = _draft(
        positioning="品牌主打轻盈不黏的肤感。",
        reason="这条路线更适合通勤使用。",
        used_fact_ids=("soft-positioning",),
        reason_fact_ids=("soft-reason",),
    )

    _invalid(
        packet,
        draft,
        CopywriterValidationErrorCode.ATTRIBUTION,
    )


@pytest.mark.parametrize("text", [None, "", "   ", 17])
def test_fact_attribution_rejects_non_string_or_blank_block_text(
    text: object,
) -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-texture",
                attribution="merchant_claim",
            ),
        )
    )
    raw_output = {
        "sections": [
            {
                "content": {
                    "text": text,
                    "used_fact_ids": ["soft-texture"],
                }
            }
        ]
    }

    with pytest.raises(
        CopywriterReferenceError,
        match="block text must be a non-empty string",
    ):
        bind_copywriter_fact_attribution(packet, raw_output)


def test_fact_attribution_rejects_mixed_sources_in_one_copy_block() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-merchant",
                attribution="merchant_claim",
            ),
            _soft_fact(
                "soft-verified",
                attribution="verified_fact",
            ),
        )
    )
    raw_output = {
        "sections": [
            {
                "content": {
                    "text": "质地轻薄，同时有明确的成分记录。",
                    "used_fact_ids": [
                        "soft-merchant",
                        "soft-verified",
                    ],
                }
            }
        ]
    }

    with pytest.raises(
        CopywriterReferenceError,
        match="mixed fact attribution",
    ):
        bind_copywriter_fact_attribution(packet, raw_output)


def test_validator_allows_approved_merchant_positioning_numbers_and_ingredients() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-efficacy",
                attribution="merchant_claim",
                field_key="efficacy",
                plain_meaning="品牌主打：12周充盈凹陷",
            ),
            _soft_fact(
                "soft-ingredient",
                attribution="merchant_claim",
                field_key="ingredients_present",
                plain_meaning="品牌主打：12%玻色因溶液、透明质酸",
            ),
        )
    )
    packet = packet.model_copy(
        update={
            "copy_budget": CopyLengthBudget(
                summary_max_chars=180,
                positioning_max_chars=200,
                advisor_reason_max_chars=120,
                closing_max_chars=180,
            )
        }
    )
    draft = _draft(
        positioning=(
            "这款主打12周充盈凹陷，配方方向包含12%玻色因溶液"
            "和透明质酸。"
        ),
        reason="适合想看充盈、淡纹和饱满感路线的人先重点比较。",
        used_fact_ids=("soft-efficacy", "soft-ingredient"),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_rejects_hard_fact_when_fact_id_is_not_listed() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-efficacy",
                attribution="merchant_claim",
                field_key="efficacy",
                plain_meaning="品牌主打：12周充盈凹陷",
            ),
            _soft_fact(
                "soft-skin",
                attribution="verified_fact",
                field_key="suitable_skin",
                plain_meaning="适合肤质：多种肤质适用",
            ),
        )
    )
    draft = _draft(
        positioning="品牌主打12周充盈凹陷。",
        reason="多种肤质适用，可以作为充盈路线的补充选择。",
        used_fact_ids=("soft-skin",),
    )

    _invalid(
        packet,
        draft,
        CopywriterValidationErrorCode.HARD_FACT,
    )


def test_validator_allows_approved_verified_ingredients() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-ingredient",
                attribution="verified_fact",
                field_key="ingredients_present",
                plain_meaning="核心成分：玻色因、透明质酸",
            ),
        )
    )
    draft = _draft(
        positioning="配方方向包含玻色因和透明质酸。",
        reason="适合想看充盈和保湿路线的人先比较。",
        used_fact_ids=("soft-ingredient",),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_approved_alphanumeric_ingredient_name() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-ingredient",
                attribution="verified_fact",
                field_key="ingredients_present",
                plain_meaning="核心成分：维生素原B5（泛醇）",
            ),
        )
    )
    draft = _draft(
        positioning="配方方向包含维生素原B5（泛醇）。",
        reason="适合想看保湿修护路线的人比较。",
        used_fact_ids=("soft-ingredient",),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_recommendation_summary_forbids_product_ingredient_fact() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-ingredient",
                attribution="verified_fact",
                field_key="ingredients_present",
                plain_meaning="核心成分：维生素原B5（泛醇）",
            ),
        )
    )
    draft = _draft(
        summary="这款精华的核心成分是维生素原B5（泛醇），先看修护路线。",
        summary_fact_ids=("soft-ingredient",),
        positioning="配方方向包含维生素原B5（泛醇）。",
        reason="适合想看保湿修护路线的人比较。",
        used_fact_ids=("soft-ingredient",),
    )

    _invalid(
        packet,
        draft,
        CopywriterValidationErrorCode.FACT_ID_MISMATCH,
    )


def test_multi_product_summary_cannot_borrow_one_product_ingredient_fact() -> None:
    base = _packet(
        soft_facts=(
            _soft_fact(
                "soft-ingredient",
                attribution="verified_fact",
                field_key="ingredients_present",
                plain_meaning="核心成分：维生素原B5（泛醇）",
            ),
        )
    )
    second_slot = base.slots[0].model_copy(
        update={
            "slot_id": "p2",
            "product_id": 56,
            "approved_soft_facts": tuple(
                fact.model_copy(
                    update={
                        "fact_id": f"{fact.fact_id}-p2",
                        "product_id": 56,
                    }
                )
                for fact in base.slots[0].approved_soft_facts
            ),
            "locked_facts": (),
            "required_cautions": (),
        },
        deep=True,
    )
    packet = base.model_copy(
        update={
            "slots": (base.slots[0], second_slot),
            "section_order": (
                PresentationSectionSpec(kind="summary"),
                PresentationSectionSpec(kind="product", slot_id="p1"),
                PresentationSectionSpec(kind="product", slot_id="p2"),
                PresentationSectionSpec(kind="closing"),
                PresentationSectionSpec(kind="full_cards"),
                PresentationSectionSpec(kind="pitfalls"),
            ),
        },
        deep=True,
    )
    first = _draft().sections[1]
    first = first.model_copy(
        update={
            "content": first.content.model_copy(
                update={"used_fact_ids": ("soft-ingredient",)}
            )
        }
    )
    draft = _draft(
        summary="两款里有一款的核心成分是维生素原B5（泛醇），先看路线差异。",
        summary_fact_ids=("soft-ingredient",),
        product_sections=(
            first.model_copy(update={"slot_id": "p1"}),
            first.model_copy(
                update={
                    "slot_id": "p2",
                    "content": first.content.model_copy(
                        update={
                            "used_fact_ids": (
                                "soft-ingredient-p2",
                            )
                        }
                    ),
                }
            ),
        ),
    )

    _invalid(
        packet,
        draft,
        CopywriterValidationErrorCode.FACT_ID_MISMATCH,
    )


def test_validator_allows_exact_number_from_approved_finish_fact() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-finish",
                attribution="merchant_claim",
                field_key="finish",
                plain_meaning="品牌主打：24小时不暗沉柔雾妆效",
            ),
        )
    )
    draft = _draft(
        positioning="品牌主打24小时不暗沉的柔雾妆效。",
        reason="适合更看重通勤持妆观感的人比较。",
        used_fact_ids=("soft-finish",),
    )

    assert validate_copywriter_draft(packet, draft) == draft


@pytest.mark.parametrize(
    "positioning",
    (
        "品牌主打16小时持久贴肤。",
        "按商家资料，持久贴肤时长为16 h。",
    ),
)
def test_validator_allows_equivalent_hour_unit_from_approved_fact(
    positioning: str,
) -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-film",
                attribution="merchant_claim",
                field_key="film_speed",
                plain_meaning="品牌主打：16H持久贴肤",
            ),
        )
    )
    draft = _draft(
        positioning=positioning,
        reason="适合想了解成膜持久度的人比较。",
        used_fact_ids=("soft-film",),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_approved_decimal_percentage() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-efficacy",
                attribution="merchant_claim",
                field_key="efficacy",
                plain_meaning="品牌主打：皮肤紧致提升35.97%",
            ),
        )
    )
    draft = _draft(
        positioning="品牌主打皮肤紧致提升35.97%。",
        reason="适合想了解紧致路线的人比较。",
        used_fact_ids=("soft-efficacy",),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_approved_chinese_quantity_unit() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-efficacy",
                attribution="merchant_claim",
                field_key="efficacy",
                plain_meaning="品牌主打：1瓶覆盖抗老与抗氧方向",
            ),
        )
    )
    draft = _draft(
        positioning="品牌主打1瓶覆盖抗老与抗氧方向。",
        reason="适合想简化护肤步骤的人比较。",
        used_fact_ids=("soft-efficacy",),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_summary_to_restate_user_budget_range() -> None:
    packet = _packet().model_copy(
        update={
            "user_need_summary": (
                "干敏肌想要抗初老精华，预算 900 到 1100 元"
            )
        }
    )
    draft = _draft(
        summary="在900-1100元预算内，先看抗初老精华的路线差异。",
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_summary_to_reference_visible_product_count() -> None:
    base = _packet()

    def clone_slot(slot_id: str, product_id: int) -> CopySlot:
        slot = base.slots[0]
        return slot.model_copy(
            update={
                "slot_id": slot_id,
                "product_id": product_id,
                "approved_soft_facts": tuple(
                    fact.model_copy(
                        update={
                            "fact_id": f"{fact.fact_id}-{slot_id}",
                            "product_id": product_id,
                        }
                    )
                    for fact in slot.approved_soft_facts
                ),
                "locked_facts": (),
                "required_cautions": (),
            },
            deep=True,
        )

    packet = base.model_copy(
        update={
            "slots": (
                base.slots[0],
                clone_slot("p2", 56),
                clone_slot("p3", 57),
            ),
            "section_order": (
                PresentationSectionSpec(kind="summary"),
                PresentationSectionSpec(kind="product", slot_id="p1"),
                PresentationSectionSpec(kind="product", slot_id="p2"),
                PresentationSectionSpec(kind="product", slot_id="p3"),
                PresentationSectionSpec(kind="closing"),
                PresentationSectionSpec(kind="full_cards"),
                PresentationSectionSpec(kind="pitfalls"),
            ),
        },
        deep=True,
    )
    base_item = _draft().sections[1]

    def clone_item(slot_id: str) -> CopywriterSection:
        return base_item.model_copy(
            update={
                "slot_id": slot_id,
                "content": base_item.content.model_copy(
                    update={
                        "used_fact_ids": tuple(
                            f"{fact_id}-{slot_id}"
                            for fact_id in (
                                base_item.content.used_fact_ids
                            )
                        )
                    }
                ),
            }
        )

    draft = _draft(
        summary="这3款先按肤感、主打方向和预算取舍分开看。",
        product_sections=(
            base_item.model_copy(update={"slot_id": "p1"}),
            clone_item("p2"),
            clone_item("p3"),
        ),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_generic_one_product_selection_wording() -> None:
    base = _packet()
    second_slot = base.slots[0].model_copy(
        update={
            "slot_id": "p2",
            "product_id": 56,
            "approved_soft_facts": tuple(
                fact.model_copy(
                    update={
                        "fact_id": f"{fact.fact_id}-p2",
                        "product_id": 56,
                    }
                )
                for fact in base.slots[0].approved_soft_facts
            ),
            "locked_facts": (),
            "required_cautions": (),
        },
        deep=True,
    )
    packet = base.model_copy(
        update={
            "slots": (base.slots[0], second_slot),
            "section_order": (
                PresentationSectionSpec(kind="summary"),
                PresentationSectionSpec(kind="product", slot_id="p1"),
                PresentationSectionSpec(kind="product", slot_id="p2"),
                PresentationSectionSpec(kind="closing"),
                PresentationSectionSpec(kind="full_cards"),
                PresentationSectionSpec(kind="pitfalls"),
            ),
        },
        deep=True,
    )
    base_item = _draft().sections[1]
    second_item = base_item.model_copy(
        update={
            "slot_id": "p2",
            "content": base_item.content.model_copy(
                update={
                    "used_fact_ids": tuple(
                        f"{fact_id}-p2"
                        for fact_id in (
                            base_item.content.used_fact_ids
                        )
                    )
                }
            ),
        }
    )
    draft = _draft(
        product_sections=(
            base_item.model_copy(update={"slot_id": "p1"}),
            second_item,
        ),
        closing="按自己的场景从中选一款即可。",
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_chinese_hundred_budget_in_summary() -> None:
    packet = _packet().model_copy(
        update={"user_need_summary": "油敏肌通勤防晒，预算100元内"}
    )
    draft = _draft(
        summary="百元内优先看通勤时的轻薄和成膜表现。",
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_colloquial_hundred_price_in_summary() -> None:
    packet = _packet().model_copy(
        update={"user_need_summary": "油敏肌通勤防晒，预算130元内"}
    )
    draft = _draft(
        summary="一百三元内先按肤感和通勤场景取舍。",
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_placeholder_product_name_does_not_ban_normal_copy_character() -> None:
    packet = _packet()
    slot = packet.slots[0].model_copy(update={"name": "无"})
    packet = packet.model_copy(update={"slots": (slot,)})
    draft = _draft(positioning="肤感偏无感延展，收尾也更轻盈。")

    assert validate_copywriter_draft(packet, draft) == draft


def test_general_knowledge_allows_generic_product_category_language() -> None:
    packet = _packet().model_copy(
        update={
            "mode": "general_knowledge",
            "responsibility": Responsibility.GENERAL_KNOWLEDGE,
            "winner_status": None,
            "slots": (),
            "section_order": (
                PresentationSectionSpec(kind="general_knowledge"),
            ),
        },
        deep=True,
    )
    draft = CopywriterDraft(
        mode="general_knowledge",
        sections=(
            CopywriterSection(
                kind="general_knowledge",
                content=SourceTaggedCopy(
                    text="补涂频率要结合活动场景和皮肤状态判断。"
                ),
            ),
        ),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_explicitly_negated_winner_language() -> None:
    draft = _draft(
        summary="现有信息不足以直接定首选，也无法断言哪款最佳。",
    )

    assert validate_copywriter_draft(_packet(), draft) == draft


def test_validator_accepts_typed_non_selection_without_lexical_guessing() -> None:
    draft = _draft(
        summary=(
            "这次先围绕你关心的肤感来整理，暂不直接给唯一推荐。"
        ),
        summary_winner_claim="not_selected",
    )

    assert validate_copywriter_draft(_packet(), draft) == draft


def test_validator_rejects_typed_selection_without_authorized_winner() -> None:
    draft = _draft(
        summary="结合当前信息整理这款的使用方向。",
        summary_winner_claim="selected",
    )

    with pytest.raises(CopywriterValidationError) as caught:
        validate_copywriter_draft(_packet(), draft)

    assert caught.value.code is CopywriterValidationErrorCode.WINNER_LANGUAGE


def test_validator_allows_future_conditional_winner_question() -> None:
    draft = _draft(
        closing=(
            "后续有更多同维度信息，再确认是否升级为首选。"
        ),
    )

    assert validate_copywriter_draft(_packet(), draft) == draft


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda draft: draft.model_copy(
                update={"mode": "comparison"}
            ),
            CopywriterValidationErrorCode.MODE_MISMATCH,
        ),
        (
            lambda draft: draft.model_copy(
                update={
                    "sections": (
                        draft.sections[0],
                        draft.sections[1].model_copy(
                            update={"slot_id": "p2"}
                        ),
                        draft.sections[2],
                    )
                }
            ),
            CopywriterValidationErrorCode.SLOT_MISMATCH,
        ),
        (
            lambda draft: draft.model_copy(
                update={
                    "sections": (
                        draft.sections[0],
                        draft.sections[1].model_copy(
                            update={
                                "content": (
                                    draft.sections[1]
                                    .content.model_copy(
                                        update={
                                            "used_fact_ids": (
                                                "soft-texture",
                                                "unknown-fact",
                                            )
                                        }
                                    )
                                )
                            }
                        ),
                        draft.sections[2],
                    )
                }
            ),
            CopywriterValidationErrorCode.FACT_ID_MISMATCH,
        ),
    ],
)
def test_validator_rejects_structural_authority_changes(
    mutate: Callable[[CopywriterDraft], CopywriterDraft],
    code: CopywriterValidationErrorCode,
) -> None:
    _invalid(_packet(), mutate(_draft()), code)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (
            "也可以换成碧柔水感防晒。",
            CopywriterValidationErrorCode.PRODUCT_NAME,
        ),
        (
            "预算内有多款修护精华，可以继续比较。",
            CopywriterValidationErrorCode.CATEGORY_MISMATCH,
        ),
        (
            "保证不过敏、不闷痘，还能治疗皮炎。",
            CopywriterValidationErrorCode.SAFETY_GUARANTEE,
        ),
        (
            "<strong>更适合通勤</strong>",
            CopywriterValidationErrorCode.MARKUP,
        ),
        (
            "**更适合通勤**",
            CopywriterValidationErrorCode.MARKUP,
        ),
    ],
)
def test_validator_rejects_rendering_and_safety_overreach(
    text: str,
    code: CopywriterValidationErrorCode,
) -> None:
    _invalid(_packet(), _draft(reason=text), code)


def test_validator_allows_other_category_terms_in_usage_context() -> None:
    draft = _draft(
        reason="日常洗面奶可卸，无需额外卸妆。",
    )

    assert validate_copywriter_draft(_packet(), draft).sections


@pytest.mark.parametrize(
    "text",
    (
        "这是代码核对后的候选。",
        "这款满足硬条件，可以放行。",
        "页面记录版本显示它证据等级更高。",
        "本轮筛选先看这一款。",
        "品牌主打：品牌主打轻薄肤感。",
    ),
)
def test_validator_rejects_internal_or_duplicated_public_language(
    text: str,
) -> None:
    with pytest.raises(CopywriterValidationError) as caught:
        validate_copywriter_draft(
            _packet(),
            _draft(reason=text),
        )

    assert caught.value.code.value == "internal_language"


def test_validator_allows_winner_language_only_for_authorized_winner() -> None:
    selected = _packet(winner_status="SELECTED")
    draft = _draft(
        summary="综合这轮的选择条件，它可以作为首选。",
        summary_winner_claim="selected",
    )

    assert validate_copywriter_draft(selected, draft).sections


@pytest.mark.parametrize(
    ("attribution", "reason"),
    [
        (
            "merchant_claim",
            "它的肤感就是轻盈不黏。",
        ),
        (
            "consumer_report",
            "它的肤感就是轻盈不黏。",
        ),
    ],
)
def test_validator_requires_claim_attribution(
    attribution: str,
    reason: str,
) -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-attributed",
                attribution=attribution,
            ),
        )
    )
    draft = _draft(
        reason=reason,
        used_fact_ids=(),
        reason_fact_ids=("soft-attributed",),
    )

    _invalid(
        packet,
        draft,
        CopywriterValidationErrorCode.ATTRIBUTION,
    )


@pytest.mark.parametrize(
    ("attribution", "reason"),
    [
        (
            "merchant_claim",
            "按商家资料，它更偏轻盈不黏的肤感。",
        ),
        (
            "merchant_claim",
            "这款主打轻盈不黏的肤感。",
        ),
        (
            "consumer_report",
            "从限定样本的用户反馈看，肤感更偏轻盈不黏。",
        ),
    ],
)
def test_validator_accepts_explicit_claim_attribution(
    attribution: str,
    reason: str,
) -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-attributed",
                attribution=attribution,
            ),
        )
    )
    draft = _draft(
        reason=reason,
        used_fact_ids=(),
        reason_fact_ids=("soft-attributed",),
    )

    assert validate_copywriter_draft(packet, draft).sections


def test_validator_enforces_packet_copy_budget() -> None:
    _invalid(
        _packet(),
        _draft(positioning="清" * 91),
        CopywriterValidationErrorCode.LENGTH,
    )


def test_validator_allows_partial_substantive_soft_fact_coverage() -> None:
    facts = tuple(
        _soft_fact(f"fact-{index}")
        for index in range(5)
    )
    packet = _packet(soft_facts=facts)
    draft = _draft(
        used_fact_ids=("fact-0", "fact-1"),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_requires_at_least_one_soft_fact_when_available() -> None:
    facts = tuple(
        _soft_fact(f"fact-{index}")
        for index in range(4)
    )
    packet = _packet(soft_facts=facts)
    draft = _draft(used_fact_ids=())

    with pytest.raises(CopywriterValidationError) as caught:
        validate_copywriter_draft(packet, draft)

    assert caught.value.code.value == "fact_coverage"


def test_validator_requires_copy_for_required_closing_section() -> None:
    _invalid(
        _packet(),
        _draft(closing=None),
        CopywriterValidationErrorCode.SLOT_MISMATCH,
    )


def test_validator_rejects_verbatim_locked_fact_or_caution() -> None:
    _invalid(
        _packet(),
        _draft(closing="特别敏感人群请勿使用。"),
        CopywriterValidationErrorCode.HARD_FACT,
    )


def test_validator_allows_locked_text_also_approved_as_soft_fact() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-overlap",
                plain_meaning="肤感更偏轻薄清透",
            ),
        )
    )
    slot = packet.slots[0].model_copy(
        update={
            "locked_facts": (
                LockedFact(
                    fact_id="locked-overlap",
                    product_id=55,
                    kind="verified_text",
                    label="质地",
                    display_value="轻薄清透",
                    source_refs=("source:overlap",),
                ),
            )
        }
    )
    packet = packet.model_copy(update={"slots": (slot,)})
    draft = _draft(
        positioning="肤感更偏轻薄清透。",
        used_fact_ids=("soft-overlap",),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_does_not_treat_verified_category_as_global_ban() -> None:
    packet = _packet()
    slot = packet.slots[0].model_copy(
        update={
            "locked_facts": (
                LockedFact(
                    fact_id="locked-category",
                    product_id=55,
                    kind="verified_text",
                    label="功效",
                    display_value="防晒",
                    source_refs=("source:category",),
                ),
            )
        }
    )
    packet = packet.model_copy(update={"slots": (slot,)})
    draft = _draft(
        summary="先把它作为防晒产品继续看，不急着直接拍板。",
    )

    assert validate_copywriter_draft(packet, draft) == draft
