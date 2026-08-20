from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

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
    CompactTagEvidence,
    CopyLengthBudget,
    CopySlot,
    CopywriterDraft,
    CopywriterSection,
    LockedFact,
    PresentationMode,
    PresentationPacket,
    PresentationSectionSpec,
    SourceTaggedCopy,
    build_copywriter_section_specs,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompileInputs,
    compile_presentation,
)
from app.guide.presentation.public_contracts import (
    PublicPresentationContract,
)
from app.guide.intent.responsibility_matrix import (
    decision_for_responsibility,
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
        compact_tag_evidence=(
            CompactTagEvidence(
                product_id=product_id,
                fact_id=f"soft-{product_id}",
                field_key="texture",
                label="轻盈清爽",
                source_refs=(f"source:soft:{product_id}",),
                attribution="verified_fact",
            ),
        ),
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
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        )
    elif mode in {"single_product", "image_suitability"}:
        sections = (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="judgement"),
            PresentationSectionSpec(kind="full_cards"),
        )
    elif mode == "image_identity":
        sections = (
            PresentationSectionSpec(kind="observation"),
            PresentationSectionSpec(kind="full_cards"),
        )
    elif not slots:
        sections = (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="closing"),
        )
    elif mode in COMPARISON_MODES:
        sections = (
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="comparison"),
            PresentationSectionSpec(kind="full_cards"),
        )
    else:
        sections = (
            PresentationSectionSpec(kind="summary"),
            *(
                PresentationSectionSpec(
                    kind="product",
                    slot_id=slot.slot_id,
                )
                for slot in slots
            ),
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
        )
    return PresentationPacket(
        mode=mode,
        user_need_summary="按当前条件给出展示结果",
        winner_status="INSUFFICIENT_FOR_WINNER",
        slots=slots,
        section_order=sections,
        requested_dimensions=(
            ("texture",)
            if mode in COMPARISON_MODES
            else ()
        ),
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
    slots_by_id = {slot.slot_id: slot for slot in packet.slots}
    sections = []
    for spec in build_copywriter_section_specs(packet):
        if spec.kind == "product":
            slot = slots_by_id[spec.slot_id]
            sections.append(
                CopywriterSection(
                    kind="product",
                    slot_id=slot.slot_id,
                    content=SourceTaggedCopy(
                        text="更偏轻盈清爽的使用路线。",
                        used_fact_ids=(
                            slot.approved_soft_facts[0].fact_id,
                        ),
                    ),
                    advisor_reason=SourceTaggedCopy(
                        text="可以结合自己的肤感偏好继续比较。"
                    ),
                )
            )
        elif spec.kind in {"answer", "judgement"}:
            sections.append(
                CopywriterSection(
                    kind=spec.kind,
                    slot_id=spec.slot_id,
                    content=SourceTaggedCopy(
                        text="这部分信息可以结合当前需求继续判断。"
                    ),
                )
            )
        else:
            sections.append(
                CopywriterSection(
                    kind=spec.kind,
                    content=SourceTaggedCopy(
                        text=(
                            "现有信息可以支持下面的路线说明，"
                            "但不强行分出唯一胜负。"
                        )
                    ),
                )
            )
    return CopywriterDraft(mode=packet.mode, sections=tuple(sections))


def _section(
    draft: CopywriterDraft,
    kind: str,
    slot_id: str | None = None,
) -> CopywriterSection:
    return next(
        section
        for section in draft.sections
        if (section.kind, section.slot_id) == (kind, slot_id)
    )


def _replace_section(
    draft: CopywriterDraft,
    replacement: CopywriterSection,
) -> CopywriterDraft:
    return CopywriterDraft(
        mode=draft.mode,
        sections=tuple(
            replacement
            if (
                section.kind,
                section.slot_id,
            )
            == (
                replacement.kind,
                replacement.slot_id,
            )
            else section
            for section in draft.sections
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

    assert result.mode == decision_for_responsibility(
        packet.responsibility
    ).presentation_mode
    assert result.card_display == _card_display(packet)
    assert tuple(
        section.product_id
        for section in result.sections
        if section.kind == "product"
    ) == (
        result.card_display.visible_product_ids
        if result.responsibility.value == "recommendation"
        else ()
    )
    expected_calls = (
        0 if mode in {"clarification", "error", "image_identity"} else 1
    )
    assert len(copywriter.calls) == expected_calls
    assert result.copy_source == (
        "fallback" if expected_calls == 0 else "model"
    )


def test_compiler_returns_one_public_contract_type() -> None:
    packet = _packet("recommendation")

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
        ),
        copywriter=RecordingCopywriter([_result(packet)]),
    )

    assert isinstance(result, PublicPresentationContract)


def test_comparison_compiles_only_summary_table_and_shelf() -> None:
    packet = _packet("comparison")

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
        ),
        copywriter=RecordingCopywriter([_result(packet)]),
    )

    assert isinstance(result, PublicPresentationContract)
    assert [section.kind for section in result.sections] == [
        "summary",
        "comparison",
        "full_cards",
    ]
    assert [row.label for row in result.comparison_rows] == [
        "品牌主打",
        "质地",
        "参考价",
    ]
    assert all(section.kind != "product" for section in result.sections)
    assert all(
        0 < len([
            tag
            for tag in result.compact_tags
            if tag.product_id == product_id
        ]) <= 3
        for product_id in result.visible_product_ids
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


def test_compiler_has_no_temporary_debug_http_instrumentation() -> None:
    source = Path(
        "app/guide/presentation/presentation_compiler.py"
    ).read_text(encoding="utf-8")

    assert "127.0.0.1:7777" not in source
    assert "urllib.request" not in source
    assert "#region debug" not in source


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
    base = _draft(packet)
    summary = _section(base, "summary")
    invalid = _result(packet).model_copy(
        update={
            "draft": _replace_section(
                base,
                summary.model_copy(
                    update={
                        "content": SourceTaggedCopy(
                                text="这就是最适合你的唯一首选。",
                                winner_claim="selected",
                        )
                    }
                ),
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


def test_demo_relaxed_validation_cannot_bypass_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _packet("recommendation")
    base = _draft(packet)
    summary = _section(base, "summary")
    invalid = _result(packet).model_copy(
        update={
            "draft": _replace_section(
                base,
                summary.model_copy(
                    update={
                        "content": SourceTaggedCopy(
                                text="这就是最适合你的唯一首选。",
                                winner_claim="selected",
                        )
                    }
                ),
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
    assert result.copy_source == "fallback"
    assert result.telemetry.fallback_reason == (
        "validation:winner_language"
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


def test_compiler_rejects_legacy_universal_essay_draft() -> None:
    packet = _packet("general_knowledge")
    legacy = CopywriterCallResult(
        draft=CopywriterDraft(
            mode="general_knowledge",
            summary_copy=SourceTaggedCopy(
                text="这是不应进入新运行路径的旧格式。"
            ),
        ),
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

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
        ),
        copywriter=RecordingCopywriter([legacy]),
    )

    assert result.copy_source == "fallback"
    assert result.telemetry.fallback_reason == "validation:legacy_draft"


def test_reviewed_general_knowledge_copy_bypasses_copywriter() -> None:
    packet = _packet("general_knowledge")
    copywriter = RecordingCopywriter([_result(packet)])
    public_copy = (
        "下面先讲通用知识：\n\n"
        "1. **看防护指标**：SPF 针对 UVB。"
    )

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
            authoritative_public_copy=SourceTaggedCopy(
                text=public_copy,
            ),
        ),
        copywriter=copywriter,
    )

    assert copywriter.calls == []
    assert result.sections[0].copy_text == public_copy
    assert result.copy_source == "fallback"
    assert (
        result.telemetry.fallback_reason
        == "authoritative_public_copy"
    )


def test_authoritative_public_copy_is_knowledge_only() -> None:
    packet = _packet("recommendation")

    with pytest.raises(ValueError, match="knowledge"):
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
            authoritative_public_copy=SourceTaggedCopy(
                text="公开正文",
            ),
        )


def test_product_knowledge_uses_authoritative_copy_with_fact_ids() -> None:
    packet = _packet("product_knowledge")
    copywriter = RecordingCopywriter([_result(packet)])
    answer = SourceTaggedCopy(
        text="品牌主打轻盈清爽，具体肤感仍以实际使用为准。",
        used_fact_ids=("soft-55",),
    )

    result = compile_presentation(
        PresentationCompileInputs(
            packet=packet,
            card_display=_card_display(packet),
            authoritative_public_copy=answer,
        ),
        copywriter=copywriter,
    )

    assert copywriter.calls == []
    assert tuple(section.kind for section in result.sections) == (
        "summary",
        "answer",
        "full_cards",
    )
    assert result.sections[1].copy_text == answer.text
    assert result.sections[1].used_fact_ids == ("soft-55",)


def test_authoritative_product_knowledge_rejects_unknown_fact_id() -> None:
    packet = _packet("product_knowledge")

    with pytest.raises(ValueError, match="authority"):
        compile_presentation(
            PresentationCompileInputs(
                packet=packet,
                card_display=_card_display(packet),
                authoritative_public_copy=SourceTaggedCopy(
                    text="这段正文不能冒用未知依据。",
                    used_fact_ids=("unknown-fact",),
                ),
            ),
            copywriter=None,
        )


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
