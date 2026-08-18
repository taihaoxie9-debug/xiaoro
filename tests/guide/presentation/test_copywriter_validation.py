from __future__ import annotations

from collections.abc import Callable

import pytest

from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CopyLengthBudget,
    CopySlot,
    CopywriterDraft,
    DirectCaution,
    LockedFact,
    PresentationPacket,
    PresentationSectionSpec,
    ProductCopy,
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
    return PresentationPacket(
        mode="recommendation",
        user_need_summary="油敏肌通勤防晒",
        winner_status=winner_status,
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
            PresentationSectionSpec(kind="pitfalls"),
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
    positioning: str = "更偏轻盈不黏的通勤路线。",
    reason: str = "早上赶时间时会更利落。",
    product_copy: tuple[ProductCopy, ...] | None = None,
    used_fact_ids: tuple[str, ...] = (
        "soft-texture",
        "soft-film",
    ),
    closing: str = "建议结合下方商品资料再做选择。",
) -> CopywriterDraft:
    return CopywriterDraft(
        mode="recommendation",
        summary_copy=summary,
        product_copy=product_copy or (
            ProductCopy(
                slot_id="p1",
                positioning=positioning,
                advisor_reason=reason,
                used_soft_fact_ids=used_fact_ids,
            ),
        ),
        closing_copy=closing,
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

    assert validated.product_copy[0].positioning == (
        "更偏轻盈不黏的通勤路线。"
    )
    assert validated.product_copy[0].advisor_reason == (
        "早上赶时间时会更利落。"
    )


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


def test_validator_authorizes_hard_fact_even_when_fact_id_is_not_listed() -> None:
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

    assert validate_copywriter_draft(packet, draft) == draft


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


def test_validator_still_rejects_unauthorized_numbers_and_ingredients() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-texture",
                attribution="merchant_claim",
                plain_meaning="品牌主打：轻盈滋润、快速吸收、不粘腻",
            ),
        )
    )
    draft = _draft(
        positioning="这款主打12周见效，还额外加入12%玻色因溶液。",
        reason="适合想看清爽肤感的人先比较。",
        used_fact_ids=("soft-texture",),
    )

    _invalid(packet, draft, CopywriterValidationErrorCode.HARD_FACT)


def test_validator_rejects_bare_number_reuse_from_approved_claim() -> None:
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-ingredient",
                attribution="merchant_claim",
                field_key="ingredients_present",
                plain_meaning="品牌主打：12%玻色因溶液",
            ),
        )
    )
    draft = _draft(
        positioning="这款主打12种活性思路，配方方向包含玻色因。",
        reason="适合想看充盈路线的人先比较。",
        used_fact_ids=("soft-ingredient",),
    )

    _invalid(packet, draft, CopywriterValidationErrorCode.HARD_FACT)


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
                    fact.model_copy(update={"product_id": product_id})
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
                clone_slot("p1", 55),
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
    base_item = _draft().product_copy[0]
    draft = _draft(
        summary="这3款先按肤感、主打方向和预算取舍分开看。",
        product_copy=(
            base_item.model_copy(update={"slot_id": "p1"}),
            base_item.model_copy(update={"slot_id": "p2"}),
            base_item.model_copy(update={"slot_id": "p3"}),
        ),
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
            "winner_status": None,
            "slots": (),
            "section_order": (
                PresentationSectionSpec(kind="summary"),
                PresentationSectionSpec(kind="closing"),
            ),
        },
        deep=True,
    )
    draft = CopywriterDraft(
        mode="general_knowledge",
        summary_copy="补涂频率要结合活动场景和皮肤状态判断。",
        product_copy=(),
        closing_copy="可以选择适合自己的防晒产品，并按场景补涂。",
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_validator_allows_explicitly_negated_winner_language() -> None:
    draft = _draft(
        summary="当前证据不足以直接定首选，也无法断言哪款最佳。",
    )

    assert validate_copywriter_draft(_packet(), draft) == draft


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
                    "product_copy": (
                        draft.product_copy[0].model_copy(
                            update={"slot_id": "p2"}
                        ),
                    )
                }
            ),
            CopywriterValidationErrorCode.SLOT_MISMATCH,
        ),
        (
            lambda draft: draft.model_copy(
                update={
                    "product_copy": (
                        draft.product_copy[0].model_copy(
                            update={
                                "used_soft_fact_ids": (
                                    "soft-texture",
                                    "unknown-fact",
                                )
                            }
                        ),
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
            "参考价只要88.11元，直接买就行。",
            CopywriterValidationErrorCode.HARD_FACT,
        ),
        (
            "有93%的用户使用两周后都觉得不错。",
            CopywriterValidationErrorCode.HARD_FACT,
        ),
        (
            "它还额外含有烟酰胺。",
            CopywriterValidationErrorCode.INGREDIENT,
        ),
        (
            "也可以换成碧柔水感防晒。",
            CopywriterValidationErrorCode.PRODUCT_NAME,
        ),
        (
            "预算内有多款修护精华，可以继续比较。",
            CopywriterValidationErrorCode.CATEGORY_MISMATCH,
        ),
        (
            "这就是最适合你的唯一首选。",
            CopywriterValidationErrorCode.WINNER_LANGUAGE,
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
def test_validator_rejects_fact_and_rendering_overreach(
    text: str,
    code: CopywriterValidationErrorCode,
) -> None:
    _invalid(_packet(), _draft(reason=text), code)


def test_validator_allows_other_category_terms_in_usage_context() -> None:
    draft = _draft(
        reason="日常洗面奶可卸，无需额外卸妆。",
    )

    assert validate_copywriter_draft(_packet(), draft).product_copy


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
        summary="按当前已核对的证据，它可以作为这轮的首选。",
    )

    assert validate_copywriter_draft(selected, draft).summary_copy


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
        used_fact_ids=("soft-attributed",),
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
        used_fact_ids=("soft-attributed",),
    )

    assert validate_copywriter_draft(packet, draft).product_copy


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
        CopywriterValidationErrorCode.REQUIRED_COPY,
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
