from __future__ import annotations

import json

import pytest

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CopyLengthBudget,
    CopySlot,
    CopywriterDraft,
    CopywriterSection,
    PresentationPacket,
    PresentationSectionSpec,
    SourceTaggedCopy,
    build_copywriter_section_specs,
)
from app.guide.presentation.copywriter_validation import (
    CopywriterValidationError,
    CopywriterValidationErrorCode,
    validate_copywriter_draft,
)
from app.guide.presentation.copywriter_prompt import (
    build_presentation_copy_messages,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompileInputs,
    compile_presentation,
)


def _slot(slot_id: str, product_id: int) -> CopySlot:
    return CopySlot(
        slot_id=slot_id,
        product_id=product_id,
        name=f"商品{product_id}",
        category_profile="skincare",
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id=f"fact:{product_id}:texture",
                product_id=product_id,
                field_key="texture",
                plain_meaning="轻薄清爽",
                attribution="verified_fact",
                source_refs=(f"source:{product_id}",),
            ),
        ),
    )


def _budget() -> CopyLengthBudget:
    return CopyLengthBudget(
        summary_max_chars=180,
        positioning_max_chars=90,
        advisor_reason_max_chars=100,
        closing_max_chars=180,
    )


def _comparison_packet() -> PresentationPacket:
    return PresentationPacket(
        mode="comparison",
        user_need_summary="比较两款的清爽程度",
        winner_status="TIED",
        slots=(_slot("p1", 38), _slot("p2", 91)),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="comparison"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        requested_dimensions=("texture.refreshing",),
        copy_budget=_budget(),
    )


def _recommendation_packet() -> PresentationPacket:
    return PresentationPacket(
        mode="recommendation",
        recommendation_mode="explore",
        user_need_summary="想找一款清爽的日常防晒",
        winner_status="INSUFFICIENT_FOR_WINNER",
        slots=(_slot("p1", 38),),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="product", slot_id="p1"),
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        copy_budget=_budget(),
    )


def test_comparison_writer_scope_contains_only_visible_summary() -> None:
    specs = build_copywriter_section_specs(_comparison_packet())

    assert [
        (spec.kind, spec.slot_id)
        for spec in specs
    ] == [("summary", None)]
    assert specs[0].allowed_fact_ids == ()
    assert specs[0].content_source == "constraints_only"
    assert specs[0].required_dimension_ids == (
        "texture.refreshing",
    )


def test_constraints_only_closing_rejects_product_fact_ids() -> None:
    packet = _recommendation_packet()
    draft = CopywriterDraft(
        mode="recommendation",
        sections=(
            CopywriterSection(
                kind="summary",
                content=SourceTaggedCopy(
                    text="先按你更在意的使用感受来取舍。"
                ),
            ),
            CopywriterSection(
                kind="product",
                slot_id="p1",
                content=SourceTaggedCopy(
                    text="轻薄清爽。",
                    used_fact_ids=("fact:38:texture",),
                ),
                advisor_reason=SourceTaggedCopy(
                    text="适合想要清爽肤感时优先比较。"
                ),
            ),
            CopywriterSection(
                kind="closing",
                content=SourceTaggedCopy(
                    text="结合下方信息再决定即可。",
                    used_fact_ids=("fact:38:texture",),
                ),
            ),
        ),
    )

    with pytest.raises(CopywriterValidationError) as caught:
        validate_copywriter_draft(packet, draft)

    assert caught.value.code is CopywriterValidationErrorCode.FACT_ID_MISMATCH


def test_comparison_draft_rejects_nonrendered_product_and_closing() -> None:
    packet = _comparison_packet()
    draft = CopywriterDraft(
        mode="comparison",
        sections=(
            CopywriterSection(
                kind="summary",
                content=SourceTaggedCopy(
                    text="两款在清爽感上的路线不同。"
                ),
            ),
            CopywriterSection(
                kind="product",
                slot_id="p1",
                content=SourceTaggedCopy(
                    text="轻薄清爽。",
                    used_fact_ids=("fact:38:texture",),
                ),
                advisor_reason=SourceTaggedCopy(
                    text="更适合怕闷的通勤场景。"
                ),
            ),
            CopywriterSection(
                kind="closing",
                content=SourceTaggedCopy(
                    text="按场景选择即可。"
                ),
            ),
        ),
    )

    with pytest.raises(CopywriterValidationError) as caught:
        validate_copywriter_draft(packet, draft)

    assert caught.value.code is CopywriterValidationErrorCode.SLOT_MISMATCH


def test_product_knowledge_writer_scope_contains_answer_only() -> None:
    packet = PresentationPacket(
        mode="product_knowledge",
        user_need_summary="这款的质地怎么样",
        winner_status=None,
        slots=(_slot("p1", 38),),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        requested_dimensions=("texture",),
        copy_budget=_budget(),
    )

    specs = build_copywriter_section_specs(packet)

    assert [
        (spec.kind, spec.slot_id)
        for spec in specs
    ] == [("answer", "p1")]
    assert specs[0].allowed_fact_ids == ("fact:38:texture",)


def test_writer_section_must_cover_requested_dimension() -> None:
    base = _slot("p1", 38)
    slot = base.model_copy(
        update={
            "approved_soft_facts": (
                *base.approved_soft_facts,
                ApprovedSoftFact(
                    fact_id="fact:38:efficacy",
                    product_id=38,
                    field_key="efficacy",
                    plain_meaning="修护屏障",
                    attribution="verified_fact",
                    source_refs=("source:38:efficacy",),
                ),
            )
        }
    )
    packet = PresentationPacket(
        mode="product_knowledge",
        user_need_summary="这款的质地怎么样",
        winner_status=None,
        slots=(slot,),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        requested_dimensions=("texture",),
        copy_budget=_budget(),
    )
    draft = CopywriterDraft(
        mode="product_knowledge",
        sections=(
            CopywriterSection(
                kind="answer",
                slot_id="p1",
                content=SourceTaggedCopy(
                    text="主要说修护方向。",
                    used_fact_ids=("fact:38:efficacy",),
                ),
            ),
        ),
    )

    with pytest.raises(CopywriterValidationError) as caught:
        validate_copywriter_draft(packet, draft)

    assert caught.value.code is CopywriterValidationErrorCode.FACT_COVERAGE


def test_writer_section_requires_the_requested_child_dimension() -> None:
    slot = _slot("p1", 38).model_copy(
        update={
            "approved_soft_facts": (
                ApprovedSoftFact(
                    fact_id="fact:38:repair",
                    product_id=38,
                    field_key="efficacy",
                    dimension_ids=("efficacy.repair",),
                    plain_meaning="修护屏障",
                    attribution="verified_fact",
                    source_refs=("source:38:repair",),
                ),
                ApprovedSoftFact(
                    fact_id="fact:38:anti-age",
                    product_id=38,
                    field_key="efficacy",
                    dimension_ids=("efficacy.anti_age",),
                    plain_meaning="紧致淡纹",
                    attribution="verified_fact",
                    source_refs=("source:38:anti-age",),
                ),
            )
        }
    )
    packet = PresentationPacket(
        mode="product_knowledge",
        user_need_summary="这款的修护方向怎么样",
        winner_status=None,
        slots=(slot,),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        requested_dimensions=("efficacy.repair",),
        copy_budget=_budget(),
    )
    draft = CopywriterDraft(
        mode="product_knowledge",
        sections=(
            CopywriterSection(
                kind="answer",
                slot_id="p1",
                content=SourceTaggedCopy(
                    text="主要看紧致淡纹方向。",
                    used_fact_ids=("fact:38:anti-age",),
                ),
            ),
        ),
    )

    with pytest.raises(CopywriterValidationError) as caught:
        validate_copywriter_draft(packet, draft)

    assert caught.value.code is CopywriterValidationErrorCode.FACT_COVERAGE


def test_writer_validates_required_dimensions_not_all_allowed_facts() -> None:
    base = _slot("p1", 38)
    slot = base.model_copy(
        update={
            "approved_soft_facts": (
                *base.approved_soft_facts,
                ApprovedSoftFact(
                    fact_id="fact:38:ingredients",
                    product_id=38,
                    field_key="ingredients_present",
                    plain_meaning="核心成分：玻色因、透明质酸",
                    attribution="verified_fact",
                    source_refs=("source:38:ingredients",),
                ),
                ApprovedSoftFact(
                    fact_id="fact:38:skin",
                    product_id=38,
                    field_key="suitable_skin",
                    plain_meaning="适合肤质：多种肤质适用",
                    attribution="verified_fact",
                    source_refs=("source:38:skin",),
                ),
            )
        }
    )
    packet = PresentationPacket(
        mode="product_knowledge",
        user_need_summary="这款的质地怎么样",
        winner_status=None,
        slots=(slot,),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        requested_dimensions=("texture",),
        copy_budget=_budget(),
    )
    draft = CopywriterDraft(
        mode="product_knowledge",
        sections=(
            CopywriterSection(
                kind="answer",
                slot_id="p1",
                content=SourceTaggedCopy(
                    text="它是轻薄清爽的质地。",
                    used_fact_ids=("fact:38:texture",),
                ),
            ),
        ),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_writer_rejects_unselected_hard_fact() -> None:
    packet = PresentationPacket(
        mode="product_knowledge",
        user_need_summary="这款的质地怎么样",
        winner_status=None,
        slots=(_slot("p1", 38),),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        requested_dimensions=("texture",),
        copy_budget=_budget(),
    )
    draft = CopywriterDraft(
        mode="product_knowledge",
        sections=(
            CopywriterSection(
                kind="answer",
                slot_id="p1",
                content=SourceTaggedCopy(
                    text="它是轻薄清爽的质地，并含三肽-32。",
                    used_fact_ids=("fact:38:texture",),
                ),
            ),
        ),
    )

    with pytest.raises(CopywriterValidationError) as caught:
        validate_copywriter_draft(packet, draft)

    assert caught.value.code is CopywriterValidationErrorCode.HARD_FACT


def test_copywriter_prompt_serializes_only_writable_sections() -> None:
    system, user = build_presentation_copy_messages(_comparison_packet())
    payload = json.loads(user["content"])

    assert "mode, sections" in system["content"]
    assert payload["writable_sections"] == [
        {
            "kind": "summary",
            "slot_id": None,
            "evidence_location": "comparison.summary",
            "allowed_fact_ids": [],
            "required_dimension_ids": ["texture.refreshing"],
            "allowed_constraint_ids": [],
            "copy_max_chars": 180,
            "advisor_reason_required": False,
            "content_source": "constraints_only",
            "approved_soft_facts": [],
        }
    ]
    assert "slots" not in payload


def test_comparison_compiler_uses_only_returned_summary_section() -> None:
    packet = _comparison_packet()
    draft = CopywriterDraft(
        mode="comparison",
        sections=(
            CopywriterSection(
                kind="summary",
                content=SourceTaggedCopy(
                    text="两款清爽路线不同，直接看下方对比表即可。"
                ),
            ),
        ),
    )

    class Copywriter:
        def write(self, requested_packet: PresentationPacket):
            assert requested_packet is packet
            return CopywriterCallResult(
                draft=draft,
                usage=SemanticTokenUsage(
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    cached_tokens=0,
                ),
                provider="test",
                model="test",
                latency_ms=0.0,
            )

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=CardDisplayContract(
                mode="comparison",
                visible_product_ids=(38, 91),
                max_cards=2,
                reason="comparison",
            ),
        ),
        copywriter=Copywriter(),
    )

    assert [section.kind for section in result.sections] == [
        "summary",
        "comparison",
        "full_cards",
    ]
    assert result.sections[0].copy_text == (
        "两款清爽路线不同，直接看下方对比表即可。"
    )
