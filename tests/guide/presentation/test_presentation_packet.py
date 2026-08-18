from __future__ import annotations

from decimal import Decimal
from hashlib import sha256

import pytest

from app.guide.presentation.card_display import (
    comparison_card_display,
    recommendation_card_display,
    single_product_card_display,
)
from app.guide.presentation.contracts import (
    DisplayCategoryFact,
    ProductCard,
)
from app.guide.presentation.copywriter_contracts import LockedFact
from app.guide.presentation.presentation_packet import (
    build_presentation_packet,
)
from app.guide.presentation.sse_events import (
    ConceptSlotData,
    MerchantClaimEvidenceData,
    SelectionSlotData,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.pitfall_contracts import (
    PitfallClaimKind,
    PitfallSeverity,
    TypedPitfall,
)


def _card(
    product_id: int,
    *,
    name: str,
    price: str,
    specification: str | None = None,
    texture_state: str = "known",
    category_facts: tuple[DisplayCategoryFact, ...] | None = None,
) -> ProductCard:
    return ProductCard(
        product_id=product_id,
        category_profile=CategoryProfile.SUNCARE,
        category_facts=(
            category_facts
            if category_facts is not None
            else (
                DisplayCategoryFact(
                    field_key="spf_pa",
                    label="防晒指数",
                    value="SPF50 PA++++",
                    state="known",
                ),
                DisplayCategoryFact(
                    field_key="texture",
                    label="质地",
                    value=(
                        ("轻薄清透", "不黏腻")
                        if texture_state == "known"
                        else None
                    ),
                    state=texture_state,
                ),
                DisplayCategoryFact(
                    field_key="usage_context",
                    label="使用场景",
                    value=None,
                    state="unavailable",
                ),
            )
        ),
        name=name,
        brand="测试品牌",
        category="防晒",
        price=Decimal(price),
        specification=specification,
        image_url=f"/static/images/products/{product_id}.png",
        detail_url=f"https://example.com/{product_id}",
        platform="天猫",
        skin_match="unknown",
        matched_efficacies=[],
        fact_warnings=[],
    )


def _display_fact(
    field_key: str,
    label: str,
    value: tuple[str, ...],
) -> DisplayCategoryFact:
    return DisplayCategoryFact(
        field_key=field_key,
        label=label,
        value=value,
        state="known",
    )


def _claim(
    product_id: int,
    *,
    field_key: str = "film_speed",
    text: str = "一抹速成膜",
) -> MerchantClaimEvidenceData:
    seed = f"{product_id}:{field_key}:{text}".encode("utf-8")
    return MerchantClaimEvidenceData(
        claim_id=sha256(seed).hexdigest(),
        product_id=product_id,
        field_key=field_key,
        display_claim=text,
        claim_scope="ordinary",
        allowed_use="soft_rank_and_display",
        source_locator=(
            f"urn:merchant:{product_id}:{sha256(seed).hexdigest()}"
        ),
    )


def _selection(product_id: int) -> SelectionSlotData:
    return SelectionSlotData(
        product_id=product_id,
        field_key="texture",
        requested_value="清爽",
        matched_value="轻薄清透",
        match_status="matched",
        rank_strength=2,
        source_refs=[f"source:selection:{product_id}:texture"],
        attribution="verified_fact",
    )


def _concept(product_id: int) -> ConceptSlotData:
    return ConceptSlotData(
        product_id=product_id,
        field_key="texture",
        concept_id="texture.refreshing",
        polarity="prefer",
        match_status="matched",
        stance="supports",
        rank_strength=2,
        source_values=["不黏腻", "轻薄清透"],
        source_refs=[f"source:concept:{product_id}:refreshing"],
        attribution="verified_fact",
    )


def _pitfall(product_id: int) -> TypedPitfall:
    return TypedPitfall(
        finding_id=f"pitfall-v1:safety:product_{product_id}",
        product_id=product_id,
        severity=PitfallSeverity.HIGH,
        claim_kind=PitfallClaimKind.SAFETY,
        title="特别敏感人群注意",
        description="包装明确提示特别敏感人群请勿使用。",
        evidence_refs=[
            f"pitfall_evidence:package:{product_id}:warning"
        ],
    )


def test_packet_uses_exact_visible_card_order_and_excludes_hidden_cards() -> None:
    visible = (
        _card(55, name="清透防晒乳", price="88.11"),
        _card(57, name="水活防晒凝蜜", price="92.02"),
    )
    hidden = _card(54, name="隐藏候选", price="96.71")

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="500元内，油敏肌，防晒",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=recommendation_card_display(visible),
        cards=(*visible, hidden),
        selection_slots=(_selection(55), _selection(57), _selection(54)),
        concept_slots=(_concept(55), _concept(57), _concept(54)),
        merchant_claims=(_claim(55), _claim(57), _claim(54)),
        pitfalls=(_pitfall(57), _pitfall(54)),
    )

    assert [slot.product_id for slot in packet.slots] == [55, 57]
    assert [slot.slot_id for slot in packet.slots] == ["p1", "p2"]
    assert "隐藏候选" not in packet.model_dump_json()
    assert all(
        caution.product_id in {55, 57}
        for slot in packet.slots
        for caution in slot.required_cautions
    )


def test_packet_keeps_relevant_soft_facts_and_code_owned_locked_facts() -> None:
    card = _card(55, name="清透防晒乳", price="88.11")

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="500元内，油敏肌，防晒",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(_selection(55),),
        concept_slots=(_concept(55),),
        merchant_claims=(_claim(55),),
        pitfalls=(_pitfall(55),),
    )

    slot = packet.slots[0]
    meanings = [fact.plain_meaning for fact in slot.approved_soft_facts]
    locked = {
        (fact.kind, fact.label, fact.display_value)
        for fact in slot.locked_facts
    }

    assert len(slot.approved_soft_facts) <= 8
    assert any("清爽" in meaning or "轻薄" in meaning for meaning in meanings)
    assert any("品牌主打" in meaning for meaning in meanings)
    assert ("price", "参考价", "¥88.11") in locked
    assert all(label != "防晒指数" for _, label, _ in locked)
    assert "使用场景" not in packet.model_dump_json()
    assert slot.required_cautions[0].severity == "high"


def test_packet_bytes_are_deterministic() -> None:
    card = _card(55, name="清透防晒乳", price="88.11")
    kwargs = {
        "mode": "recommendation",
        "user_need_summary": "500元内，油敏肌，防晒",
        "winner_status": "INSUFFICIENT_FOR_WINNER",
        "card_display": recommendation_card_display((card,)),
        "cards": (card,),
        "selection_slots": (_selection(55),),
        "concept_slots": (_concept(55),),
        "merchant_claims": (_claim(55),),
        "pitfalls": (_pitfall(55),),
    }

    first = build_presentation_packet(**kwargs)
    second = build_presentation_packet(**kwargs)

    assert first.model_dump_json() == second.model_dump_json()


def test_zero_card_general_knowledge_packet_has_no_product_slots() -> None:
    packet = build_presentation_packet(
        mode="general_knowledge",
        user_need_summary="SPF和PA分别是什么意思",
        winner_status=None,
        card_display=recommendation_card_display(()),
        cards=(),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
    )

    assert packet.slots == ()
    assert all(
        section.kind not in {"product", "full_cards"}
        for section in packet.section_order
    )


def test_mode_specific_section_duties_are_not_shared_recommendation_frame() -> None:
    first = _card(55, name="清透防晒乳", price="88.11")
    second = _card(57, name="水活防晒凝蜜", price="92.02")
    cases = (
        (
            "recommendation",
            recommendation_card_display((first, second)),
            (first, second),
            (
                "summary",
                "product",
                "product",
                "closing",
                "full_cards",
                "pitfalls",
            ),
        ),
        (
            "product_knowledge",
            single_product_card_display(first),
            (first,),
            ("product", "full_cards"),
        ),
        (
            "general_knowledge",
            recommendation_card_display(()),
            (),
            ("general_knowledge",),
        ),
        (
            "comparison",
            comparison_card_display((first, second)),
            (first, second),
            (
                "summary",
                "comparison",
                "product",
                "product",
                "closing",
                "full_cards",
                "pitfalls",
            ),
        ),
    )

    for mode, card_display, cards, expected in cases:
        packet = build_presentation_packet(
            mode=mode,
            user_need_summary="测试当前模式的展示职责",
            winner_status="NOT_APPLICABLE",
            card_display=card_display,
            cards=cards,
            selection_slots=(),
            concept_slots=(),
            merchant_claims=(),
            pitfalls=(),
        )

        assert tuple(
            section.kind for section in packet.section_order
        ) == expected


def test_product_knowledge_requires_exactly_one_visible_product() -> None:
    first = _card(55, name="清透防晒乳", price="88.11")
    second = _card(57, name="水活防晒凝蜜", price="92.02")

    with pytest.raises(
        ValueError,
        match="product knowledge requires one product",
    ):
        build_presentation_packet(
            mode="product_knowledge",
            user_need_summary="这两款分别怎么用",
            winner_status="NOT_APPLICABLE",
            card_display=recommendation_card_display((first, second)),
            cards=(first, second),
            selection_slots=(),
            concept_slots=(),
            merchant_claims=(),
            pitfalls=(),
        )


def test_consumer_soft_fact_keeps_plain_language_attribution() -> None:
    card = _card(55, name="清透防晒乳", price="88.11")
    selection = _selection(55).model_copy(
        update={"attribution": "consumer_report"}
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="想看限定反馈里的肤感",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(selection,),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
    )

    fact = packet.slots[0].approved_soft_facts[0]
    assert fact.attribution == "consumer_report"
    assert fact.plain_meaning.startswith("限定样本的用户反馈：")


def test_packet_projects_four_to_eight_useful_narrative_atoms() -> None:
    card = _card(55, name="清透防晒乳", price="299")

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="300元内清爽通勤防晒",
        winner_status="SELECTED",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(_selection(55),),
        concept_slots=(_concept(55),),
        merchant_claims=tuple(
            _claim(55, field_key=field, text=text)
            for field, text in (
                ("texture", "轻薄清透"),
                ("finish", "透气贴妆"),
                ("film_speed", "快速成膜"),
                ("usage_context", "日常通勤"),
                ("usage", "早晚使用"),
            )
        ),
        pitfalls=(),
    )

    assert len(packet.slots[0].approved_soft_facts) == 5
    assert all(
        fact.fact_id.startswith("atom:")
        for fact in packet.slots[0].approved_soft_facts
    )
    assert all(
        fact.field_key != "usage"
        for fact in packet.slots[0].approved_soft_facts
    )


def test_packet_uses_safe_normalized_claim_instead_of_raw_marketing() -> None:
    card = _card(55, name="测试精华", price="299")
    claim = MerchantClaimEvidenceData(
        claim_id="a" * 64,
        product_id=55,
        field_key="efficacy",
        normalized_value="改善凹陷观感",
        display_claim="12周充盈凹陷，堪比玻尿酸填充",
        claim_scope="ordinary",
        allowed_use="soft_rank_and_display",
        source_locator="urn:merchant:55:claim",
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="想看充盈方向的抗老精华",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(claim,),
        pitfalls=(),
    )

    meanings = [
        fact.plain_meaning
        for fact in packet.slots[0].approved_soft_facts
    ]
    assert meanings == ["品牌主打：改善凹陷观感"]
    assert "玻尿酸" not in packet.model_dump_json()


def test_locked_facts_combine_reference_price_and_exact_spec() -> None:
    card = _card(
        52,
        name="兰蔻菁纯臻颜防晒隔离乳",
        price="299",
        specification="30ml",
        category_facts=(),
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="300元内清爽通勤防晒",
        winner_status="SELECTED",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
    )

    assert [
        (fact.label, fact.display_value)
        for fact in packet.slots[0].locked_facts
    ][0] == ("参考价", "¥299 / 30ml")


def test_missing_ingredients_and_audience_create_no_placeholder_rows() -> None:
    card = _card(
        52,
        name="兰蔻菁纯臻颜防晒隔离乳",
        price="299",
        category_facts=(),
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="300元内清爽通勤防晒",
        winner_status="SELECTED",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
    )

    labels = {
        fact.label for fact in packet.slots[0].locked_facts
    }
    assert "核心成分" not in labels
    assert "适用人群" not in labels


def test_packet_accepts_one_code_owned_numeric_proof_point() -> None:
    card = _card(52, name="兰蔻菁纯臻颜防晒隔离乳", price="299")
    display_value = (
        "商家引用：62名中国消费者连续使用两周后，"
        "通过消费者自评，"
        "100%的受试者认同轻薄不厚重、清爽不油腻"
    )
    proof_point = LockedFact(
        fact_id="evidence:" + "a" * 64,
        product_id=52,
        kind="numeric",
        label="用户测试",
        display_value=display_value,
        source_refs=("urn:xiaoro:test:proof-point",),
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="300元内清爽通勤防晒",
        winner_status="SELECTED",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
        proof_points=(proof_point,),
    )

    numeric = [
        fact
        for fact in packet.slots[0].locked_facts
        if fact.kind == "numeric"
    ]
    assert len(numeric) == 1
    assert numeric[0].display_value == display_value


def test_packet_rejects_two_numeric_proof_points_for_one_product() -> None:
    card = _card(52, name="兰蔻菁纯臻颜防晒隔离乳", price="299")
    points = tuple(
        LockedFact(
            fact_id=f"evidence:{suffix * 64}",
            product_id=52,
            kind="numeric",
            label="用户测试",
            display_value=f"商家引用：证明{suffix}",
            source_refs=(f"urn:xiaoro:test:{suffix}",),
        )
        for suffix in ("a", "b")
    )

    with pytest.raises(ValueError, match="one numeric proof"):
        build_presentation_packet(
            mode="recommendation",
            user_need_summary="300元内清爽通勤防晒",
            winner_status="SELECTED",
            card_display=recommendation_card_display((card,)),
            cards=(card,),
            selection_slots=(),
            concept_slots=(),
            merchant_claims=(),
            pitfalls=(),
            proof_points=points,
        )


def test_product_packet_uses_final_section_order() -> None:
    card = _card(52, name="兰蔻菁纯臻颜防晒隔离乳", price="299")

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="300元内清爽通勤防晒",
        winner_status="SELECTED",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
    )

    assert [section.kind for section in packet.section_order] == [
        "summary",
        "product",
        "closing",
        "full_cards",
        "pitfalls",
    ]
