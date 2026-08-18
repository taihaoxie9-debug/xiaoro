from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticTokenUsage,
)
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CopyLengthBudget,
    CopySlot,
    CopywriterDraft,
    LockedFact,
    PresentationMode,
    PresentationPacket,
    PresentationSectionSpec,
    ProductCopy,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompileInputs,
    compile_presentation,
)


PRODUCT_MODES: tuple[PresentationMode, ...] = (
    "recommendation",
    "single_product",
    "product_knowledge",
    "followup",
    "revision",
    "image_identity",
    "image_recommendation",
    "image_suitability",
)
COMPARISON_MODES: tuple[PresentationMode, ...] = (
    "comparison",
    "image_comparison",
)
ZERO_CARD_MODES: tuple[PresentationMode, ...] = (
    "general_knowledge",
    "consultation",
    "clarification",
    "error",
)
ALL_MODES: tuple[PresentationMode, ...] = (
    *PRODUCT_MODES,
    *COMPARISON_MODES,
    *ZERO_CARD_MODES,
)


class RecordingCopywriter:
    def __init__(
        self,
        responses: Sequence[
            CopywriterCallResult | SemanticProviderFailure
        ],
    ) -> None:
        self._responses = iter(responses)
        self.calls: list[PresentationPacket] = []

    def write(
        self,
        packet: PresentationPacket,
    ) -> CopywriterCallResult:
        self.calls.append(packet)
        response = next(self._responses)
        if isinstance(response, SemanticProviderFailure):
            raise response
        return response


def _slot(index: int, product_id: int) -> CopySlot:
    return CopySlot(
        slot_id=f"p{index}",
        product_id=product_id,
        name=f"受代码管理的商品{index}",
        category_profile="suncare",
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id=f"soft-{product_id}",
                product_id=product_id,
                field_key="texture",
                plain_meaning="质地更偏轻盈清爽",
                attribution="verified_fact",
                source_refs=(f"source:soft:{product_id}",),
            ),
        ),
        locked_facts=(
            LockedFact(
                fact_id=f"price-{product_id}",
                product_id=product_id,
                kind="price",
                label="参考价",
                display_value=f"¥{product_id}.00",
                source_refs=(f"source:price:{product_id}",),
            ),
        ),
        required_cautions=(),
    )


def _packet(mode: PresentationMode) -> PresentationPacket:
    if mode in COMPARISON_MODES:
        slots = (_slot(1, 55), _slot(2, 57))
    elif mode in PRODUCT_MODES:
        slots = (_slot(1, 55),)
    else:
        slots = ()
    if mode == "clarification":
        sections = (PresentationSectionSpec(kind="question"),)
    elif mode == "error":
        sections = (PresentationSectionSpec(kind="error"),)
    elif mode == "consultation":
        sections = (
            PresentationSectionSpec(kind="observation"),
            PresentationSectionSpec(kind="summary"),
        )
    elif mode == "general_knowledge":
        sections = (
            PresentationSectionSpec(kind="general_knowledge"),
        )
    elif mode == "product_knowledge":
        sections = (
            PresentationSectionSpec(kind="product", slot_id="p1"),
            PresentationSectionSpec(kind="full_cards"),
        )
    elif not slots:
        sections = (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="evidence"),
        )
    else:
        prefix = [PresentationSectionSpec(kind="summary")]
        if mode in COMPARISON_MODES:
            prefix.append(PresentationSectionSpec(kind="comparison"))
        sections = (
            *prefix,
            *(
                PresentationSectionSpec(
                    kind="product",
                    slot_id=slot.slot_id,
                )
                for slot in slots
            ),
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
            PresentationSectionSpec(kind="pitfalls"),
        )
    return PresentationPacket(
        mode=mode,
        user_need_summary="按当前条件给出展示结果",
        winner_status="INSUFFICIENT_FOR_WINNER",
        slots=slots,
        section_order=sections,
        copy_budget=CopyLengthBudget(
            summary_max_chars=180,
            positioning_max_chars=90,
            advisor_reason_max_chars=100,
            closing_max_chars=180,
        ),
    )


def _card_display(packet: PresentationPacket) -> CardDisplayContract:
    product_ids = tuple(slot.product_id for slot in packet.slots)
    if not product_ids:
        return CardDisplayContract(
            mode="none",
            visible_product_ids=(),
            max_cards=0,
            reason=None,
        )
    if len(product_ids) == 1:
        return CardDisplayContract(
            mode="single",
            visible_product_ids=product_ids,
            max_cards=1,
            reason="product",
        )
    return CardDisplayContract(
        mode="comparison",
        visible_product_ids=product_ids,
        max_cards=len(product_ids),
        reason="comparison",
    )


def _draft(packet: PresentationPacket) -> CopywriterDraft:
    has_closing = any(
        section.kind == "closing"
        for section in packet.section_order
    )
    return CopywriterDraft(
        mode=packet.mode,
        summary_copy="现有信息可以支持下面的路线说明，但不强行分出唯一胜负。",
        product_copy=tuple(
            ProductCopy(
                slot_id=slot.slot_id,
                positioning="更偏轻盈清爽的使用路线。",
                advisor_reason="可以结合自己的肤感偏好继续比较。",
                used_soft_fact_ids=(slot.approved_soft_facts[0].fact_id,),
            )
            for slot in packet.slots
        ),
        closing_copy=(
            "最后结合下方商品资料和注意项选择。"
            if has_closing
            else None
        ),
    )


def _result(packet: PresentationPacket) -> CopywriterCallResult:
    return CopywriterCallResult(
        draft=_draft(packet),
        usage=SemanticTokenUsage(
            prompt_tokens=80,
            completion_tokens=30,
            total_tokens=110,
            cached_tokens=0,
        ),
        provider="copy-provider",
        model="copy-model",
        latency_ms=25.0,
    )


@pytest.mark.parametrize("mode", ALL_MODES)
def test_compiler_builds_each_mode_with_exact_card_authority(
    mode: PresentationMode,
) -> None:
    packet = _packet(mode)
    copywriter = RecordingCopywriter([_result(packet)])

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
        ),
        copywriter=copywriter,
    )

    assert result.mode == mode
    assert result.card_display == _card_display(packet)
    assert tuple(
        section.product_id
        for section in result.sections
        if section.kind == "product"
    ) == result.card_display.visible_product_ids
    expected_calls = 0 if mode in {"clarification", "error"} else 1
    assert len(copywriter.calls) == expected_calls
    assert result.copy_source == (
        "fallback" if expected_calls == 0 else "model"
    )


def test_compiler_attaches_locked_facts_after_valid_model_copy() -> None:
    packet = _packet("recommendation")
    copywriter = RecordingCopywriter([_result(packet)])

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
        ),
        copywriter=copywriter,
    )

    product = next(
        section
        for section in result.sections
        if section.kind == "product"
    )
    assert product.copy_text == "更偏轻盈清爽的使用路线。"
    assert product.advisor_reason == (
        "可以结合自己的肤感偏好继续比较。"
    )
    assert product.product_id == 55
    assert product.direct_facts[0].fact_id == "price-55"
    assert product.direct_facts[0].display_value == "¥55.00"
    assert "55.00" not in product.copy_text


@pytest.mark.parametrize(
    "policy",
    ["medical_escalation", "evidence_gap"],
)
def test_compiler_skips_copywriter_for_deterministic_policies(
    policy: str,
) -> None:
    packet = _packet("consultation")
    copywriter = RecordingCopywriter([_result(packet)])

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
            copywriter_policy=policy,
        ),
        copywriter=copywriter,
    )

    assert copywriter.calls == []
    assert result.copy_source == "fallback"
    assert result.telemetry.fallback_reason == policy


def test_invalid_model_copy_falls_back_without_second_request() -> None:
    packet = _packet("recommendation")
    invalid = _result(packet).model_copy(
        update={
            "draft": _draft(packet).model_copy(
                update={
                    "summary_copy": "这就是最适合你的唯一首选。"
                }
            )
        }
    )
    copywriter = RecordingCopywriter([invalid])

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
        ),
        copywriter=copywriter,
    )

    assert len(copywriter.calls) == 1
    assert result.copy_source == "fallback"
    assert result.telemetry.provider == "copy-provider"
    assert result.telemetry.prompt_tokens == 80
    assert result.telemetry.fallback_reason == (
        "validation:winner_language"
    )


def test_demo_relaxed_validation_uses_model_copy_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _packet("recommendation")
    invalid = _result(packet).model_copy(
        update={
            "draft": _draft(packet).model_copy(
                update={
                    "summary_copy": "这就是最适合你的唯一首选。"
                }
            )
        }
    )
    copywriter = RecordingCopywriter([invalid])
    monkeypatch.setenv(
        "GUIDE_DEMO_RELAX_COPYWRITER_VALIDATION",
        "true",
    )

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
        ),
        copywriter=copywriter,
    )

    assert len(copywriter.calls) == 1
    assert result.copy_source == "model"
    assert result.telemetry.fallback_reason is None
    assert result.sections[0].copy_text == (
        "这就是最适合你的唯一首选。"
    )


def test_provider_failure_falls_back_without_retry() -> None:
    packet = _packet("recommendation")
    copywriter = RecordingCopywriter(
        [
            SemanticProviderFailure(
                SemanticProviderFailureCode.TIMEOUT
            )
        ]
    )

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
        ),
        copywriter=copywriter,
    )

    assert len(copywriter.calls) == 1
    assert result.copy_source == "fallback"
    assert result.telemetry.fallback_reason == "provider:timeout"


def test_missing_copywriter_uses_deterministic_fallback() -> None:
    packet = _packet("general_knowledge")

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
        ),
        copywriter=None,
    )

    assert result.copy_source == "fallback"
    assert result.telemetry.fallback_reason == "copywriter_disabled"


def test_compile_inputs_reject_card_slot_mismatch_before_model_call() -> None:
    packet = _packet("recommendation")

    with pytest.raises(ValueError, match="visible product"):
        PresentationCompileInputs(
            packet=packet,
            card_display=CardDisplayContract(
                mode="single",
                visible_product_ids=(57,),
                max_cards=1,
                reason="product",
            ),
        )
