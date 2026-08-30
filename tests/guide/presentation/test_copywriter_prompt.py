from __future__ import annotations

import json

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.copywriter_contracts import (
    ApprovedConstraint,
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
        responsibility=Responsibility.RECOMMENDATION,
        recommendation_mode="explore",
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
        ),
        approved_constraints=(
            ApprovedConstraint(
                constraint_id="turn:budget:500",
                kind="budget",
                display_value="预算上限500元",
            ),
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
        "guide-presentation-copy-prompt-v18"
    )
    for key in (
        "mode",
        "sections",
        "kind",
        "slot_id",
        "content",
        "winner_claim",
        "advisor_reason",
        "used_fact_ids",
        "used_constraint_ids",
    ):
        assert key in system["content"]
    for boundary in (
        "writable_sections 完全同序、同数量",
        "不得输出价格",
        "allowed_fact_ids 是可用范围",
        "required_dimension_ids",
        "必须在出现它的同一个文本块",
        "品牌主打",
        "不得为凑覆盖率堆料",
        "内部处理过程",
        "user_need_summary 只是用户问题背景，不是可引用事实",
        "由后端按每个 copy block 的 used_fact_ids 统一绑定",
        "不得把 consumer_report 写成品牌主打",
        "JSON",
    ):
        assert boundary in system["content"]
    assert "Markdown" in system["content"]
    assert len(system["content"]) < 4000

    payload = json.loads(user["content"])
    assert payload["mode"] == "recommendation"
    assert payload["allowed_winner_claims"] == ["none", "not_selected"]
    assert [
        (item["kind"], item["slot_id"])
        for item in payload["writable_sections"]
    ] == [
        ("summary", None),
        ("product", "p1"),
        ("closing", None),
    ]
    product = payload["writable_sections"][1]
    assert product["allowed_constraint_ids"] == ["c1"]
    assert product["approved_soft_facts"][0]["fact_ref"] == "f1"
    assert product["approved_soft_facts"][0]["dimension_ids"] == [
        "texture",
    ]
    assert product["advisor_reason_required"] is True
    assert "slots" not in payload
    assert "soft-texture" not in user["content"]
    assert "turn:budget:500" not in user["content"]


def test_copywriter_prompt_distinguishes_constraints_from_product_facts() -> None:
    system, user = build_presentation_copy_messages(_packet())
    payload = json.loads(user["content"])

    assert "content_source=constraints_only" in system["content"]
    assert "used_fact_ids 返回为 []" in system["content"]
    assert (
        "不能描述任何商品属性、品牌主打、用户反馈"
        in system["content"]
    )
    assert "content_source=approved_facts" in system["content"]
    assert [
        (
            item["kind"],
            item["content_source"],
            item["allowed_fact_ids"],
        )
        for item in payload["writable_sections"]
    ] == [
        ("summary", "constraints_only", []),
        ("product", "approved_facts", ["f1"]),
        ("closing", "constraints_only", []),
    ]


def test_copywriter_prompt_uses_section_tagged_content_schema() -> None:
    system, _ = build_presentation_copy_messages(_packet())

    assert "mode, sections" in system["content"]
    assert "kind, slot_id, content, advisor_reason" in system["content"]
    assert "content 是对象" in system["content"]
    assert "不得增加、删除、合并、拆分或重排 section" in system["content"]


def test_copywriter_prompt_forbids_internal_public_language() -> None:
    system, _ = build_presentation_copy_messages(_packet())
    content = system["content"]

    for term in (
        "候选",
        "代码核对",
        "硬条件",
        "证据等级",
        "放行",
        "页面记录版本",
        "本轮筛选",
    ):
        assert term in content


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
