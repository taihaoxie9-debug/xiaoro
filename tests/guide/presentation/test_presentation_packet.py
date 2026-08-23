from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

import pytest

from app.guide.decision.contracts import CandidateEvaluation
from app.guide.presentation.card_display import (
    comparison_card_display,
    recommendation_card_display,
    single_product_card_display,
)
from app.guide.presentation.contracts import (
    DisplayCategoryFact,
    ProductCard,
)
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    LockedFact,
    responsibility_for_presentation_mode,
)
from app.guide.presentation.comparison_planning import (
    plan_comparison_rows,
)
from app.guide.presentation.presentation_packet import (
    build_presentation_packet as _build_presentation_packet,
)
from app.guide.presentation.sse_events import (
    ConceptSlotData,
    MerchantClaimEvidenceData,
    SelectionSlotData,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    EfficacyConstraint,
    SkinConstraint,
)
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.pitfall_contracts import (
    PitfallClaimKind,
    PitfallSeverity,
    TypedPitfall,
)
from app.guide.retrieval.review_contracts import (
    ApprovedReviewEvidence,
    ReviewReadResult,
)
from app.guide.retrieval.review_summary import build_review_summary


def build_presentation_packet(**values):
    if (
        responsibility_for_presentation_mode(values["mode"]).value
        == "recommendation"
        and "recommendation_mode" not in values
    ):
        if (
            values.get("winner_status")
            in {"SELECTED", "WINNER", "winner"}
            and len(values["card_display"].visible_product_ids) == 1
        ):
            values["recommendation_mode"] = "fit"
            values.setdefault(
                "winner_product_id",
                values["card_display"].visible_product_ids[0],
            )
        else:
            values["recommendation_mode"] = "explore"
    return _build_presentation_packet(**values)


def _card(
    product_id: int,
    *,
    name: str,
    price: str,
    specification: str | None = None,
    price_specification_alignment: str = "aligned",
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
        price_specification_alignment=price_specification_alignment,
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


def test_conflicted_display_binding_restricts_additional_evidence_copy() -> None:
    card = _card(
        38,
        name="理肤泉新B5多效修护精华",
        price="294",
        price_specification_alignment="conflict",
    )
    fact = ApprovedSoftFact(
        fact_id="evidence:38:sku",
        product_id=38,
        field_key="product_evidence",
        plain_meaning="页面将该商品描述为30ml版本并主打修护。",
        attribution="merchant_claim",
        source_refs=("source:38:sku",),
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="推荐一款修护精华",
        winner_status="NOT_APPLICABLE",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
        additional_soft_facts=(fact,),
    )

    restricted = next(
        fact
        for fact in packet.slots[0].approved_soft_facts
        if "30ml版本" in fact.plain_meaning
    )
    assert restricted.generic_copy_allowed is False


def test_merchant_copy_prefers_reviewed_value_over_long_ocr_claim() -> None:
    card = _card(
        91,
        name="玉泽皮肤屏障修护精华乳",
        price="88",
        price_specification_alignment="conflict",
    )
    claim = _claim(
        91,
        field_key="efficacy",
        text=(
            "医院皮肤科验证\n改善敏感肌修护受损肌\n5大皮肤问题\n"
            "实效缓解灼热泛红紧绷干痒刺痛"
        ),
    ).model_copy(update={"normalized_value": "修护屏障"})

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="推荐一款修护精华",
        winner_status="NOT_APPLICABLE",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(claim,),
        pitfalls=(),
    )

    meanings = " ".join(
        fact.plain_meaning
        for fact in packet.slots[0].approved_soft_facts
    )
    assert "品牌主打：修护屏障" in meanings
    assert "医院皮肤科验证" not in meanings


def test_requested_field_does_not_fall_back_to_full_category_fact_dump() -> None:
    card = _card(
        55,
        name="测试精华",
        price="299",
        category_facts=(
            DisplayCategoryFact(
                field_key="efficacy",
                label="功效",
                value=("修护", "舒缓", "保湿", "提亮"),
                state="known",
            ),
        ),
    )
    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="想看修护方向的精华",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
        task_constraints=(
            EfficacyConstraint(value=EfficacyTarget.REPAIR),
        ),
    )

    meanings = [
        fact.plain_meaning
        for fact in packet.slots[0].approved_soft_facts
    ]
    assert all("功效：" not in meaning for meaning in meanings)


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


def _review_summary(product_id: int, content: str):
    evidence = ApprovedReviewEvidence(
        source_id=f"review_tmall_product_{product_id}_approved_001",
        product_id=product_id,
        source_kind="platform_consumer_review",
        source_locator=(
            f"https://reviews.example/products/{product_id}#approved-001"
        ),
        content_kind="verbatim",
        content=content,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
        collected_at=datetime(2026, 8, 9, 2, 0, tzinfo=UTC),
        collection_version="tmall-approved-v1",
    )
    summary = build_review_summary(
        ReviewReadResult(
            product_id=product_id,
            evidence=[evidence],
            verified_absence=None,
        )
    )
    assert summary is not None
    return summary


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


def test_packet_selects_detail_facts_from_shared_projection() -> None:
    card = _card(
        55,
        name="清透修护精华",
        price="299",
        category_facts=(
            DisplayCategoryFact(
                field_key="ingredients_present",
                label="确认含有成分",
                value=("神经酰胺", "维生素E"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="suitable_skin",
                label="适用肤质",
                value=("多种肤质",),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="texture",
                label="质地",
                value="轻盈凝露",
                state="known",
            ),
        ),
    )
    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="想找质地轻盈的修护精华",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(
            _claim(
                55,
                field_key="efficacy",
                text="轻盈修护抗老",
            ),
        ),
        pitfalls=(),
        requested_dimensions=("texture",),
    )
    slot = packet.slots[0]

    assert [fact.field_key for fact in slot.detail_facts] == [
        "brand_main",
        "texture",
        "ingredients_present",
    ]
    approved_ids = {
        fact.fact_id for fact in slot.approved_soft_facts
    }
    assert {
        fact.fact_id for fact in slot.detail_facts
    } <= approved_ids


def test_packet_preserves_child_dimension_on_narrative_fact() -> None:
    card = _card(55, name="清透防晒乳", price="88.11")
    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="想找一款更清爽的防晒",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(_concept(55),),
        merchant_claims=(),
        pitfalls=(),
    )

    texture_fact = next(
        fact
        for fact in packet.slots[0].approved_soft_facts
        if fact.field_key == "texture"
    )

    assert texture_fact.dimension_ids == ("texture.refreshing",)


def test_packet_merges_child_dimensions_when_facts_are_deduplicated() -> None:
    card = _card(55, name="清透防晒乳", price="88.11")
    matching_concepts = (
        _concept(55),
        ConceptSlotData(
            product_id=55,
            field_key="texture",
            concept_id="texture.breathable",
            polarity="prefer",
            match_status="matched",
            stance="supports",
            rank_strength=2,
            source_values=["不黏腻", "轻薄清透"],
            source_refs=["source:concept:55:breathable"],
            attribution="verified_fact",
        ),
    )
    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="想找轻薄、不闷的防晒",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=matching_concepts,
        merchant_claims=(),
        pitfalls=(),
    )

    texture_fact = next(
        fact
        for fact in packet.slots[0].approved_soft_facts
        if fact.field_key == "texture"
    )

    assert texture_fact.dimension_ids == (
        "texture.refreshing",
        "texture.breathable",
    )


def test_packet_deduplicates_typed_constraint_authority() -> None:
    cards = (
        _card(55, name="清透防晒乳", price="88.11"),
        _card(57, name="水活防晒凝蜜", price="92.02"),
    )
    packet = build_presentation_packet(
        mode="comparison",
        user_need_summary="比较两款清爽程度",
        winner_status="NOT_APPLICABLE",
        card_display=comparison_card_display(cards),
        cards=cards,
        selection_slots=(_selection(55), _selection(57)),
        concept_slots=(_concept(55), _concept(57)),
        merchant_claims=(),
        pitfalls=(),
    )

    assert len(packet.approved_constraints) == 2
    assert {
        (item.kind, item.display_value)
        for item in packet.approved_constraints
    } == {
        ("facet", "texture：清爽"),
        ("concept", "偏好 texture.refreshing"),
    }
    assert {
        item.constraint_id.split(":", 2)[1]
        for item in packet.approved_constraints
    } == {"facet", "concept"}


def test_packet_publishes_budget_from_typed_task_constraint() -> None:
    card = _card(55, name="清透防晒乳", price="88.11")
    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="预算300元内",
        winner_status="SELECTED",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
        task_constraints=(BudgetConstraint(maximum=Decimal("300")),),
    )

    assert len(packet.approved_constraints) == 1
    budget = packet.approved_constraints[0]
    assert budget.kind == "budget"
    assert budget.display_value == "预算上限300元"
    assert budget.constraint_id.startswith("turn:budget:")


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
    assert (
        "verified_text",
        "防晒指数",
        "SPF50 PA++++",
    ) in locked
    assert "使用场景" not in packet.model_dump_json()
    assert slot.required_cautions[0].severity == "high"


def test_packet_uses_reviewed_display_name_instead_of_catalog_identity() -> None:
    card = _card(
        91,
        name="玉泽皮肤屏障修护精华乳50ml",
        price="88",
    ).model_copy(
        update={"display_name": "玉泽皮肤屏障修护精华乳"}
    )

    packet = build_presentation_packet(
        mode="product_knowledge",
        user_need_summary="这款质地怎么样",
        winner_status="NOT_APPLICABLE",
        card_display=single_product_card_display(card),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
    )

    assert packet.slots[0].name == "玉泽皮肤屏障修护精华乳"
    assert "50ml" not in packet.slots[0].name


def test_approved_review_enters_bound_consumer_report_slot() -> None:
    card = _card(55, name="清透防晒乳", price="88.11")
    review = _review_summary(
        55,
        "质地水润贴肤，上脸很好推开。",
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="想看清爽通勤防晒",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=recommendation_card_display((card,)),
        cards=(card,),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        review_summaries=(review,),
        pitfalls=(),
    )

    review_facts = tuple(
        fact
        for fact in packet.slots[0].approved_soft_facts
        if fact.attribution == "consumer_report"
    )
    assert len(review_facts) == 1
    assert "限定样本的用户反馈" in review_facts[0].plain_meaning
    assert "水润贴肤" in review_facts[0].plain_meaning
    assert review_facts[0].source_refs == (
        "https://reviews.example/products/55#approved-001",
    )


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
            ),
        ),
        (
            "product_knowledge",
            single_product_card_display(first),
            (first,),
                ("summary", "answer", "full_cards"),
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
                "full_cards",
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


def test_multi_image_identity_has_one_product_section_per_slot() -> None:
    cards = (
        _card(53, name="第一张图片商品", price="79"),
        _card(55, name="第二张图片商品", price="88.11"),
    )

    packet = build_presentation_packet(
        mode="image_identity",
        user_need_summary="确认两张图片里的商品",
        winner_status="NOT_APPLICABLE",
        card_display=recommendation_card_display(cards),
        cards=cards,
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
    )

    assert tuple(
        (section.kind, section.slot_id)
        for section in packet.section_order
    ) == (
        ("observation", None),
        ("product", "p1"),
        ("product", "p2"),
        ("full_cards", None),
    )


def test_comparison_preserves_requested_concept_status_per_product() -> None:
    rich = _card(
        55,
        name="丰润防晒",
        price="88.11",
        category_facts=(
            DisplayCategoryFact(
                field_key="texture",
                label="质地",
                value="丰润乳霜",
                state="known",
            ),
        ),
    )
    unknown = _card(
        57,
        name="未知质地防晒",
        price="92.02",
        category_facts=(
            DisplayCategoryFact(
                field_key="texture",
                label="质地",
                value=None,
                state="unavailable",
            ),
        ),
    )
    packet = build_presentation_packet(
        mode="comparison",
        user_need_summary="比较两款的清爽程度",
        winner_status="NOT_APPLICABLE",
        card_display=comparison_card_display((rich, unknown)),
        cards=(rich, unknown),
        selection_slots=(),
        concept_slots=(
            ConceptSlotData(
                product_id=55,
                field_key="texture",
                concept_id="texture.refreshing",
                polarity="prefer",
                match_status="mismatch",
                stance="opposes",
                rank_strength=2,
                source_values=["丰润乳霜"],
                source_refs=["source:55:texture:rich"],
                attribution="verified_fact",
            ),
            ConceptSlotData(
                product_id=57,
                field_key="texture",
                concept_id="texture.refreshing",
                polarity="prefer",
                match_status="unknown",
                source_values=[],
                source_refs=[],
            ),
        ),
        merchant_claims=(),
        pitfalls=(),
        requested_dimensions=("texture.refreshing",),
    )

    rows = plan_comparison_rows(
        requested_dimensions=packet.requested_dimensions,
        slots=packet.slots,
    )

    assert [row.label for row in rows] == [
        "品牌主打",
        "清爽",
        "当前画像匹配",
    ]
    assert rows[1].cells[0].value == "不符合：丰润乳霜"
    assert rows[1].cells[0].fact_ids
    assert rows[1].cells[1].state == "unknown"


def test_comparison_packet_does_not_infer_dimensions_from_ranking_slots(
) -> None:
    first = _card(55, name="清透防晒乳", price="88.11")
    second = _card(57, name="水活防晒凝蜜", price="92.02")

    packet = build_presentation_packet(
        mode="comparison",
        user_need_summary="比较这两款",
        winner_status="NOT_APPLICABLE",
        card_display=comparison_card_display((first, second)),
        cards=(first, second),
        selection_slots=(_selection(55), _selection(57)),
        concept_slots=(_concept(55), _concept(57)),
        merchant_claims=(),
        pitfalls=(),
        requested_dimensions=(),
    )

    assert packet.requested_dimensions == ()


def test_comparison_packet_builds_profile_match_from_evaluation_and_fact(
) -> None:
    matched = _card(
        55,
        name="清透防晒乳",
        price="88.11",
        category_facts=(
            DisplayCategoryFact(
                field_key="suitable_skin",
                label="适用肤质",
                value=("油皮", "敏感肌"),
                state="known",
            ),
        ),
    )
    unsupported = _card(
        57,
        name="水活防晒凝蜜",
        price="92.02",
        category_facts=(
            DisplayCategoryFact(
                field_key="suitable_skin",
                label="适用肤质",
                value=None,
                state="unavailable",
            ),
        ),
    )
    evaluations = (
        CandidateEvaluation(
            product_id=55,
            disposition="eligible",
            price=Decimal("88.11"),
            skin_match="matched",
            efficacy_match="not_applicable",
            matched_efficacies=[],
            reasons=["hard_constraints_passed"],
        ),
        CandidateEvaluation(
            product_id=57,
            disposition="eligible",
            price=Decimal("92.02"),
            skin_match="unknown",
            efficacy_match="not_applicable",
            matched_efficacies=[],
            reasons=["hard_constraints_passed"],
        ),
    )

    packet = build_presentation_packet(
        mode="comparison",
        user_need_summary="比较两款对油敏肌的适配",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=comparison_card_display((matched, unsupported)),
        cards=(matched, unsupported),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
        task_constraints=(
            SkinConstraint(value=SkinTarget.OILY_SENSITIVE),
        ),
        candidate_evaluations=evaluations,
    )
    profile_evidence = tuple(
        next(
            item
            for item in slot.comparison_evidence
            if item.dimension_id == "profile_match"
        )
        for slot in packet.slots
    )

    assert profile_evidence[0].match_status == "matched"
    assert profile_evidence[0].fact_ids == (
        "category:55:suitable_skin",
    )
    assert profile_evidence[1].match_status == "unknown"
    assert profile_evidence[1].fact_ids == ()


def test_comparison_profile_match_requires_support_for_every_requirement(
) -> None:
    partially_supported = _card(
        55,
        name="清透防晒乳",
        price="88.11",
        category_facts=(
            DisplayCategoryFact(
                field_key="suitable_skin",
                label="适用肤质",
                value=("油皮", "敏感肌"),
                state="known",
            ),
        ),
    )
    comparison_peer = _card(
        57,
        name="水活防晒凝蜜",
        price="92.02",
    )
    evaluation = CandidateEvaluation(
        product_id=55,
        disposition="eligible",
        price=Decimal("88.11"),
        skin_match="matched",
        efficacy_match="matched",
        matched_efficacies=[EfficacyTarget.REPAIR.value],
        reasons=["hard_constraints_passed"],
    )

    packet = build_presentation_packet(
        mode="comparison",
        user_need_summary="比较两款对油敏肌和修护需求的适配",
        winner_status="INSUFFICIENT_FOR_WINNER",
        card_display=comparison_card_display(
            (partially_supported, comparison_peer)
        ),
        cards=(partially_supported, comparison_peer),
        selection_slots=(),
        concept_slots=(),
        merchant_claims=(),
        pitfalls=(),
        task_constraints=(
            SkinConstraint(value=SkinTarget.OILY_SENSITIVE),
            EfficacyConstraint(value=EfficacyTarget.REPAIR),
        ),
        candidate_evaluations=(evaluation,),
    )
    profile_evidence = next(
        item
        for item in packet.slots[0].comparison_evidence
        if item.dimension_id == "profile_match"
    )

    assert profile_evidence.match_status == "unknown"
    assert profile_evidence.fact_ids == ()


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

    fact = next(
        item
        for item in packet.slots[0].approved_soft_facts
        if item.attribution == "consumer_report"
    )
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

    assert len([
        fact
        for fact in packet.slots[0].approved_soft_facts
        if fact.generic_copy_allowed
    ]) == 5
    assert all(
        fact.fact_id.startswith("atom:")
        for fact in packet.slots[0].approved_soft_facts
        if fact.generic_copy_allowed
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
    assert "品牌主打：改善凹陷观感" in meanings
    assert "12周充盈凹陷，堪比玻尿酸填充" not in packet.model_dump_json()


def test_locked_facts_label_suitable_skin_as_skin_type() -> None:
    card = _card(
        52,
        name="测试精华",
        price="299",
        category_facts=(
            DisplayCategoryFact(
                field_key="ingredients_present",
                label="成分",
                value=("玻色因", "透明质酸"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="suitable_skin",
                label="适用人群",
                value="多种肤质适用",
                state="known",
            ),
        ),
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="想看抗初老精华",
        winner_status="INSUFFICIENT_FOR_WINNER",
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
    ] == [
        ("参考价", "¥299"),
        ("适合肤质", "多种肤质适用"),
        ("核心成分", "玻色因、透明质酸"),
    ]


def test_direct_display_facts_also_feed_positioning_soft_facts() -> None:
    card = _card(
        35,
        name="修丽可聚糖多重丰盈精华液",
        price="1050",
        specification="30ml",
        category_facts=(
            DisplayCategoryFact(
                field_key="efficacy",
                label="功效",
                value=("抗皱", "淡化细纹", "紧致", "保湿"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="ingredients_present",
                label="确认含有成分",
                value=("玻色因", "透明质酸"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="suitable_skin",
                label="适用肤质",
                value=("多种肤质适用",),
                state="known",
            ),
        ),
    )
    claim = MerchantClaimEvidenceData(
        claim_id="b" * 64,
        product_id=35,
        field_key="efficacy",
        normalized_value=None,
        display_claim="12周充盈凹陷，堪比玻尿酸填充",
        claim_scope="ordinary",
        allowed_use="soft_rank_and_display",
        source_locator="urn:merchant:35:claim",
    )

    packet = build_presentation_packet(
        mode="recommendation",
        user_need_summary="想看抗初老精华",
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
    assert any("抗皱、淡化细纹、紧致、保湿" in item for item in meanings)
    assert any("玻色因、透明质酸" in item for item in meanings)
    assert any("12周充盈凹陷" in item for item in meanings)


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


@pytest.mark.parametrize("alignment", ["unresolved", "conflict"])
def test_locked_facts_never_join_unaligned_specification(
    alignment: str,
) -> None:
    card = _card(
        52,
        name="兰蔻菁纯臻颜防晒隔离乳",
        price="299",
        category_facts=(),
    ).model_copy(
        update={
            "price_specification_alignment": alignment,
            "specification": "30ml",
        },
        deep=True,
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
    ][0] == ("参考价", "¥299")


def test_suncare_index_is_a_direct_fact_not_free_copy() -> None:
    card = _card(
        52,
        name="兰蔻菁纯臻颜防晒隔离乳",
        price="299",
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

    assert (
        "防晒指数",
        "SPF50 PA++++",
    ) in {
        (fact.label, fact.display_value)
        for fact in packet.slots[0].locked_facts
    }
    projected_spf = next(
        fact
        for fact in packet.slots[0].approved_soft_facts
        if fact.field_key == "spf_pa"
    )
    assert projected_spf.generic_copy_allowed is False


def test_exact_specification_does_not_repeat_net_content_row() -> None:
    card = _card(
        52,
        name="兰蔻菁纯臻颜防晒隔离乳",
        price="299",
        specification="30ml",
        category_facts=(
            _display_fact(
                "net_content",
                "净含量",
                ("30ml",),
            ),
        ),
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

    assert (
        "参考价",
        "¥299 / 30ml",
    ) in {
        (fact.label, fact.display_value)
        for fact in packet.slots[0].locked_facts
    }
    assert not any(
        fact.label == "净含量"
        for fact in packet.slots[0].locked_facts
    )


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
    ]
