from __future__ import annotations

import json

from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CopyLengthBudget,
    CopySlot,
    PresentationPacket,
    PresentationSectionSpec,
)
from app.guide.presentation.copywriter_prompt import (
    PRESENTATION_COPY_PROMPT_VERSION,
    build_presentation_copy_messages,
)


def _packet() -> PresentationPacket:
    return PresentationPacket(
        mode="recommendation",
        user_need_summary="500元内，油敏肌，防晒",
        winner_status="INSUFFICIENT_FOR_WINNER",
        slots=(
            CopySlot(
                slot_id="p1",
                product_id=55,
                name="清透防晒乳",
                category_profile="suncare",
                approved_soft_facts=(
                    ApprovedSoftFact(
                        fact_id="soft-texture",
                        product_id=55,
                        field_key="texture",
                        plain_meaning="质地轻薄清透、不黏腻",
                        attribution="merchant_claim",
                        source_refs=("source:merchant:55:texture",),
                    ),
                ),
                locked_facts=(),
                required_cautions=(),
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


def test_copywriter_prompt_uses_strict_json_and_bounded_advisor_role() -> None:
    system, user = build_presentation_copy_messages(_packet())

    assert PRESENTATION_COPY_PROMPT_VERSION == (
        "guide-presentation-copy-prompt-v6"
    )
    for key in (
        "mode",
        "summary_copy",
        "product_copy",
        "slot_id",
        "positioning",
        "advisor_reason",
        "used_soft_fact_ids",
        "closing_copy",
    ):
        assert key in system["content"]
    for boundary in (
        "不得改变商品槽位",
        "不得输出价格",
        "只有 approved_soft_facts 已明示的数字",
        "只有 approved_soft_facts 已明示的成分",
        "证据不足",
        "品牌主打",
        "至少使用一条 approved_soft_facts",
        "不得机械逐条抄写或为凑覆盖率堆料",
        "预算利用算法",
        "约束优先级",
        "摘要需要给出完整判断",
        "综合建议需要明确首选、备选和场景切换",
        "positioning 讲品牌主打，优先自然合并已批准的功效方向、核心成分",
        "不要把核心成分或适合肤质只堆在 advisor_reason 里",
        "不得在",
        "advisor_reason 里写成用户本人画像或匹配理由",
        "user_need_summary 只是用户问题背景，不是可引用事实",
        "归因词必须出现在使用该事实的同一个 product_copy 项",
        "不得把 consumer_report 写成品牌主打",
        "summary_copy 中的归因不能替代",
        "summary_copy、positioning、advisor_reason 必须是非空字符串",
        "JSON",
    ):
        assert boundary in system["content"]
    assert "Markdown" in system["content"]
    assert len(system["content"]) < 7000

    payload = json.loads(user["content"])
    assert payload["mode"] == "recommendation"
    assert payload["required_sections"] == [
        {"kind": "summary", "slot_id": None},
        {"kind": "product", "slot_id": "p1"},
        {"kind": "closing", "slot_id": None},
        {"kind": "full_cards", "slot_id": None},
        {"kind": "pitfalls", "slot_id": None},
    ]
    assert payload["closing_required"] is True
    assert payload["slots"][0]["slot_id"] == "p1"
    assert payload["slots"][0]["approved_soft_facts"][0][
        "fact_id"
    ] == "soft-texture"
    assert "required_caution_summaries" not in payload["slots"][0]
    assert "closing_required" in system["content"]


def test_copywriter_prompt_freezes_mode_specific_public_language() -> None:
    system, _ = build_presentation_copy_messages(_packet())
    content = system["content"]

    assert "product_knowledge" in content
    assert "general_knowledge" in content
    assert "商品知识不得写推荐理由或综合推荐" in content
    assert "advisor_reason 仍必须非空" in content
    assert "通用知识只回答概念本身" in content
    for term in (
        "候选",
        "代码核对",
        "硬条件",
        "证据等级",
        "放行",
        "页面记录版本",
        "本轮筛选",
    ):
        assert f"不得输出“{term}”" in content


def test_copywriter_prompt_contains_no_case_specific_product_answer() -> None:
    system, _ = build_presentation_copy_messages(_packet())
    content = system["content"]

    for forbidden in (
        "薇诺娜",
        "碧柔",
        "怡思丁",
        "水后乳前",
        "500元内，油敏肌，防晒",
        "清透防晒乳",
    ):
        assert forbidden not in content
