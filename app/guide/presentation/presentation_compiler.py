from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.guide.adapters.llm.contracts import SemanticProviderFailure
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
    PresentationCopywriterPort,
)
from app.guide.intent.responsibility_matrix import (
    Responsibility,
    decision_for_responsibility,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.compact_tag_planning import plan_compact_tags
from app.guide.presentation.comparison_planning import (
    plan_comparison_rows,
)
from app.guide.presentation.copy_evidence_validation import (
    validate_copy_evidence,
)
from app.guide.presentation.copywriter_contracts import (
    CopySource,
    CopywriterPolicy,
    CopywriterDraft,
    CopywriterSection,
    CopywriterTelemetry,
    DirectFactComponent,
    PresentationPacket,
    PresentationSection,
    SourceTaggedCopy,
    deterministic_copy_source,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
from app.guide.presentation.copywriter_validation import (
    CopywriterValidationError,
    validate_copywriter_draft,
)
from app.guide.presentation.public_contracts import (
    PublicPresentationContract,
    WinnerPresentation,
)


class PresentationCompileInputs(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    packet: PresentationPacket
    card_display: CardDisplayContract
    copywriter_policy: CopywriterPolicy = "eligible"
    authoritative_public_copy: SourceTaggedCopy | None = None

    @model_validator(mode="after")
    def validate_card_authority(self) -> Self:
        packet_ids = tuple(slot.product_id for slot in self.packet.slots)
        if packet_ids != self.card_display.visible_product_ids:
            raise ValueError(
                "visible product IDs must exactly match packet slots"
            )
        if (
            self.authoritative_public_copy is not None
            and self.packet.responsibility.value
            not in {"general_knowledge", "product_knowledge"}
        ):
            raise ValueError(
                "authoritative public copy is knowledge only"
            )
        return self


class _DraftCompilationError(ValueError):
    pass


class PresentationCompiler:
    def __init__(
        self,
        *,
        copywriter: PresentationCopywriterPort | None,
    ) -> None:
        self._copywriter = copywriter

    def compile(
        self,
        inputs: PresentationCompileInputs,
    ) -> PublicPresentationContract:
        return compile_presentation(
            inputs,
            copywriter=self._copywriter,
        )


def compile_presentation(
    inputs: PresentationCompileInputs,
    *,
    copywriter: PresentationCopywriterPort | None,
) -> PublicPresentationContract:
    if not isinstance(inputs, PresentationCompileInputs):
        raise TypeError("inputs must be PresentationCompileInputs")

    if inputs.authoritative_public_copy is not None:
        return _compile_authoritative_public_copy(inputs)

    if (
        deterministic_copy_source(
            mode=inputs.packet.mode,
            copywriter_policy=inputs.copywriter_policy,
        )
        == "authoritative"
    ):
        return _compile_deterministic(
            inputs,
        )
    if copywriter is None:
        return _compile_fallback(
            inputs,
            reason="copywriter_disabled",
        )

    try:
        call = copywriter.write(inputs.packet)
    except SemanticProviderFailure as failure:
        return _compile_fallback(
            inputs,
            reason=f"provider:{failure.code.value}",
        )
    if call.draft.summary_copy is not None:
        return _compile_fallback(
            inputs,
            reason="validation:legacy_draft",
            call=call,
        )

    try:
        validated = validate_copywriter_draft(
            inputs.packet,
            call.draft,
        )
        return _compile_contract(
            inputs,
            draft=validated,
            copy_source="model",
            telemetry=_telemetry_from_call(call),
        )
    except CopywriterValidationError as failure:
        return _compile_fallback(
            inputs,
            reason=f"validation:{failure.code.value}",
            call=call,
        )
    except _DraftCompilationError:
        return _compile_fallback(
            inputs,
            reason="validation:draft_shape",
            call=call,
        )


def _compile_deterministic(
    inputs: PresentationCompileInputs,
) -> PublicPresentationContract:
    draft = fallback_copy(inputs.packet)
    validated = validate_copywriter_draft(inputs.packet, draft)
    return _compile_contract(
        inputs,
        draft=validated,
        copy_source="authoritative",
        telemetry=CopywriterTelemetry(
            provider="code",
            model="deterministic",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            fallback_reason=None,
        ),
    )


def _compile_fallback(
    inputs: PresentationCompileInputs,
    *,
    reason: str,
    call: CopywriterCallResult | None = None,
) -> PublicPresentationContract:
    draft = fallback_copy(inputs.packet)
    validated = validate_copywriter_draft(inputs.packet, draft)
    telemetry = (
        _telemetry_from_call(call, fallback_reason=reason)
        if call is not None
        else CopywriterTelemetry(
            provider="disabled",
            model="deterministic",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            fallback_reason=reason,
        )
    )
    return _compile_contract(
        inputs,
        draft=validated,
        copy_source="fallback",
        telemetry=telemetry,
    )


def _compile_authoritative_public_copy(
    inputs: PresentationCompileInputs,
) -> PublicPresentationContract:
    responsibility = inputs.packet.responsibility
    if responsibility is None:
        raise AssertionError("presentation packet requires responsibility")
    copy_text = inputs.authoritative_public_copy
    if copy_text is None:
        raise AssertionError("authoritative public copy is required")
    if responsibility.value == "general_knowledge":
        location = "general_knowledge.body"
        sections = (
            PresentationSection(
                kind="general_knowledge",
                copy_text=copy_text.text,
                used_fact_ids=copy_text.used_fact_ids,
                used_constraint_ids=copy_text.used_constraint_ids,
            ),
        )
    elif responsibility.value == "product_knowledge":
        location = "product_knowledge.answer"
        sections = (
            PresentationSection(
                kind="summary",
                copy_text="我按你问的内容，整理这款商品的相关信息。",
            ),
            PresentationSection(
                kind="answer",
                copy_text=copy_text.text,
                used_fact_ids=copy_text.used_fact_ids,
                used_constraint_ids=copy_text.used_constraint_ids,
            ),
            PresentationSection(kind="full_cards"),
        )
    else:
        raise AssertionError(
            "authoritative public copy requires knowledge responsibility"
        )
    validate_copy_evidence(
        packet=inputs.packet,
        location=location,
        used_fact_ids=copy_text.used_fact_ids,
        used_constraint_ids=copy_text.used_constraint_ids,
    )
    compact_tags = tuple(
        tag
        for slot in inputs.packet.slots
        for tag in plan_compact_tags(
            responsibility=responsibility,
            slot=slot,
            requested_concepts=inputs.packet.requested_dimensions,
        )
    )
    return PublicPresentationContract(
        responsibility=responsibility,
        mode=decision_for_responsibility(
            responsibility
        ).presentation_mode,
        copy_source="authoritative",
        sections=sections,
        comparison_rows=(),
        visible_product_ids=(
            inputs.card_display.visible_product_ids
        ),
        compact_tags=compact_tags,
        card_display=inputs.card_display,
        telemetry=CopywriterTelemetry(
            provider="reviewed_assets",
            model="deterministic",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            fallback_reason=None,
        ),
    )


def _compile_contract(
    inputs: PresentationCompileInputs,
    *,
    draft: CopywriterDraft,
    copy_source: CopySource,
    telemetry: CopywriterTelemetry,
) -> PublicPresentationContract:
    sections = _compile_sections(inputs.packet, draft)
    if (
        inputs.packet.responsibility is Responsibility.RECOMMENDATION
        and inputs.packet.recommendation_mode == "fit"
    ):
        sections = tuple(
            PresentationSection(kind="closing")
            if section.kind == "closing"
            else section
            for section in sections
        )
    responsibility = inputs.packet.responsibility
    if responsibility is None:
        raise AssertionError("presentation packet requires responsibility")
    comparison_rows = (
        plan_comparison_rows(
            requested_dimensions=inputs.packet.requested_dimensions,
            slots=inputs.packet.slots,
        )
        if responsibility.value == "comparison"
        else ()
    )
    winner = _build_winner_presentation(
        packet=inputs.packet,
        comparison_rows=comparison_rows,
    )
    compact_tags = tuple(
        tag
        for slot in inputs.packet.slots
        for tag in plan_compact_tags(
            responsibility=responsibility,
            slot=slot,
            requested_concepts=(
                inputs.packet.requested_dimensions
            ),
        )
    )
    public_mode = decision_for_responsibility(
        responsibility
    ).presentation_mode
    return PublicPresentationContract(
        responsibility=responsibility,
        mode=public_mode,
        recommendation_mode=inputs.packet.recommendation_mode,
        copy_source=copy_source,
        sections=sections,
        requested_comparison_dimensions=(
            inputs.packet.requested_dimensions
            if responsibility is Responsibility.COMPARISON
            else ()
        ),
        comparison_rows=comparison_rows,
        winner=winner,
        visible_product_ids=(
            inputs.card_display.visible_product_ids
        ),
        compact_tags=compact_tags,
        card_display=inputs.card_display,
        telemetry=telemetry,
    )


def _build_winner_presentation(
    *,
    packet: PresentationPacket,
    comparison_rows,
) -> WinnerPresentation:
    if packet.responsibility is Responsibility.RECOMMENDATION:
        if packet.recommendation_mode == "explore":
            return WinnerPresentation(status="not_applicable")
        if (
            packet.recommendation_mode != "fit"
            or packet.winner_status
            not in {"SELECTED", "WINNER", "winner"}
            or packet.winner_product_id is None
        ):
            return WinnerPresentation(status="insufficient")
        slot = next(
            (
                item
                for item in packet.slots
                if item.product_id == packet.winner_product_id
            ),
            None,
        )
        if slot is None:
            return WinnerPresentation(status="insufficient")
        selected_facts = slot.detail_facts
        if not selected_facts:
            return WinnerPresentation(status="insufficient")
        first = selected_facts[0]
        return WinnerPresentation(
            status="selected",
            winner_product_id=slot.product_id,
            reason=(
                f"综合当前需求，{slot.name}的{first.label}是"
                f"{first.display_value}，更贴合当前条件。"
            ),
            fact_ids=tuple(
                item.fact_id for item in selected_facts
            ),
            dimension_ids=tuple(dict.fromkeys(
                item.field_key for item in selected_facts
            )),
        )
    if packet.responsibility is None or (
        packet.responsibility.value != "comparison"
    ):
        return WinnerPresentation(status="not_applicable")
    status = packet.winner_status
    if status in {"SELECTED", "WINNER", "winner"}:
        if packet.winner_product_id is None:
            raise _DraftCompilationError(
                "selected comparison winner has no product ID"
            )
        fact_ids: list[str] = []
        dimension_ids: list[str] = []
        for row in comparison_rows:
            cell = next(
                (
                    item
                    for item in row.cells
                    if item.product_id == packet.winner_product_id
                ),
                None,
            )
            if (
                cell is not None
                and cell.state == "known"
                and cell.fact_ids
            ):
                fact_ids.extend(cell.fact_ids)
                dimension_ids.append(row.dimension_id)
        if not fact_ids:
            return WinnerPresentation(status="insufficient")
        return WinnerPresentation(
            status="selected",
            winner_product_id=packet.winner_product_id,
            reason="综合当前对比维度，优先选择有明确事实支持的一款。",
            fact_ids=tuple(dict.fromkeys(fact_ids)),
            dimension_ids=tuple(dict.fromkeys(dimension_ids)),
        )
    if status in {
        "TIED",
        "TIED_BY_BUSINESS_EVIDENCE",
        "tie",
    }:
        return WinnerPresentation(
            status="tied",
            tie_reason=(
                packet.winner_tie_reason
                or "当前对比维度下暂无唯一胜出。"
            ),
        )
    return WinnerPresentation(status="insufficient")


def _compile_sections(
    packet: PresentationPacket,
    draft: CopywriterDraft,
) -> tuple[PresentationSection, ...]:
    if draft.summary_copy is None:
        return _compile_section_draft_sections(packet, draft)
    copy_by_slot = {
        item.slot_id: item for item in draft.product_copy
    }
    slot_by_id = {slot.slot_id: slot for slot in packet.slots}
    sections: list[PresentationSection] = []
    for spec in packet.section_order:
        if spec.kind == "summary":
            sections.append(
                PresentationSection(
                    kind="summary",
                    copy_text=draft.summary_copy.text,
                    used_fact_ids=draft.summary_copy.used_fact_ids,
                    used_constraint_ids=(
                        draft.summary_copy.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "product":
            if spec.slot_id is None:
                raise _DraftCompilationError(
                    "product section missing slot"
                )
            item = copy_by_slot[spec.slot_id]
            slot = slot_by_id[spec.slot_id]
            sections.append(
                PresentationSection(
                    kind="product",
                    copy_text=item.positioning.text,
                    used_fact_ids=item.positioning.used_fact_ids,
                    used_constraint_ids=(
                        item.positioning.used_constraint_ids
                    ),
                    advisor_reason=item.advisor_reason.text,
                    advisor_used_fact_ids=(
                        item.advisor_reason.used_fact_ids
                    ),
                    advisor_used_constraint_ids=(
                        item.advisor_reason.used_constraint_ids
                    ),
                    slot_id=slot.slot_id,
                    product_id=slot.product_id,
                    direct_facts=tuple(
                        DirectFactComponent(
                            fact_id=fact.fact_id,
                            label=fact.label,
                            display_value=fact.display_value,
                        )
                        for fact in slot.detail_facts
                    ),
                )
            )
        elif spec.kind == "judgement":
            if not packet.slots:
                raise _DraftCompilationError(
                    "judgement section requires one slot"
                )
            item = copy_by_slot[packet.slots[0].slot_id]
            sections.append(
                PresentationSection(
                    kind="judgement",
                    copy_text=item.advisor_reason.text,
                    used_fact_ids=item.advisor_reason.used_fact_ids,
                    used_constraint_ids=(
                        item.advisor_reason.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "answer":
            if not packet.slots:
                raise _DraftCompilationError(
                    "answer section requires one slot"
                )
            item = copy_by_slot[packet.slots[0].slot_id]
            sections.append(
                PresentationSection(
                    kind="answer",
                    copy_text=item.positioning.text,
                    used_fact_ids=item.positioning.used_fact_ids,
                    used_constraint_ids=(
                        item.positioning.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "closing":
            if draft.closing_copy is None:
                raise _DraftCompilationError(
                    "closing section missing copy"
                )
            sections.append(
                PresentationSection(
                    kind="closing",
                    copy_text=draft.closing_copy.text,
                    used_fact_ids=draft.closing_copy.used_fact_ids,
                    used_constraint_ids=(
                        draft.closing_copy.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "question":
            sections.append(
                PresentationSection(
                    kind="question",
                    copy_text=draft.summary_copy.text,
                    used_fact_ids=draft.summary_copy.used_fact_ids,
                    used_constraint_ids=(
                        draft.summary_copy.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "error":
            sections.append(
                PresentationSection(
                    kind="error",
                    copy_text=draft.summary_copy.text,
                    used_fact_ids=draft.summary_copy.used_fact_ids,
                    used_constraint_ids=(
                        draft.summary_copy.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "observation":
            uses_summary = (
                packet.responsibility is not None
                and packet.responsibility.value == "image_identity"
            )
            sections.append(
                PresentationSection(
                    kind="observation",
                    copy_text=(
                        draft.summary_copy.text
                        if uses_summary
                        else (
                            "以下观察只基于当前已提供的信息，"
                            "不替代诊断或治疗建议。"
                        )
                    ),
                    used_fact_ids=(
                        draft.summary_copy.used_fact_ids
                        if uses_summary
                        else ()
                    ),
                    used_constraint_ids=(
                        draft.summary_copy.used_constraint_ids
                        if uses_summary
                        else ()
                    ),
                )
            )
        elif spec.kind == "comparison":
            sections.append(
                PresentationSection(kind="comparison")
            )
        elif spec.kind == "general_knowledge":
            sections.append(
                PresentationSection(
                    kind="general_knowledge",
                    copy_text=draft.summary_copy.text,
                    used_fact_ids=draft.summary_copy.used_fact_ids,
                    used_constraint_ids=(
                        draft.summary_copy.used_constraint_ids
                    ),
                )
            )
        else:
            sections.append(PresentationSection(kind=spec.kind))
    return tuple(sections)


def _compile_section_draft_sections(
    packet: PresentationPacket,
    draft: CopywriterDraft,
) -> tuple[PresentationSection, ...]:
    copy_by_identity = {
        (section.kind, section.slot_id): section
        for section in draft.sections
    }
    slot_by_id = {slot.slot_id: slot for slot in packet.slots}

    def writer_section(
        kind: str,
        slot_id: str | None = None,
    ) -> CopywriterSection:
        try:
            return copy_by_identity[(kind, slot_id)]
        except KeyError as error:
            raise _DraftCompilationError(
                f"missing writer section: {kind}:{slot_id}"
            ) from error

    sections: list[PresentationSection] = []
    for spec in packet.section_order:
        if spec.kind == "summary":
            if packet.responsibility is not None and (
                packet.responsibility.value == "product_knowledge"
            ):
                sections.append(
                    PresentationSection(
                        kind="summary",
                        copy_text=(
                            "我按你问的内容，整理这款商品的相关信息。"
                        ),
                    )
                )
                continue
            writer = writer_section("summary")
            sections.append(
                PresentationSection(
                    kind="summary",
                    copy_text=writer.content.text,
                    used_fact_ids=writer.content.used_fact_ids,
                    used_constraint_ids=(
                        writer.content.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "product":
            if spec.slot_id is None:
                raise _DraftCompilationError(
                    "product section missing slot"
                )
            slot = slot_by_id[spec.slot_id]
            direct_facts = tuple(
                DirectFactComponent(
                    fact_id=fact.fact_id,
                    label=fact.label,
                    display_value=fact.display_value,
                )
                for fact in slot.detail_facts
            )
            if (
                packet.responsibility is not None
                and packet.responsibility.value == "image_identity"
            ):
                sections.append(
                    PresentationSection(
                        kind="product",
                        slot_id=slot.slot_id,
                        product_id=slot.product_id,
                        direct_facts=direct_facts,
                    )
                )
                continue
            writer = writer_section("product", spec.slot_id)
            if writer.advisor_reason is None:
                raise _DraftCompilationError(
                    "product writer section missing advisor"
                )
            sections.append(
                PresentationSection(
                    kind="product",
                    copy_text=writer.content.text,
                    used_fact_ids=writer.content.used_fact_ids,
                    used_constraint_ids=(
                        writer.content.used_constraint_ids
                    ),
                    advisor_reason=writer.advisor_reason.text,
                    advisor_used_fact_ids=(
                        writer.advisor_reason.used_fact_ids
                    ),
                    advisor_used_constraint_ids=(
                        writer.advisor_reason.used_constraint_ids
                    ),
                    slot_id=slot.slot_id,
                    product_id=slot.product_id,
                    direct_facts=direct_facts,
                )
            )
        elif spec.kind == "judgement":
            if not packet.slots:
                raise _DraftCompilationError(
                    "judgement section requires one slot"
                )
            writer = writer_section(
                "judgement",
                packet.slots[0].slot_id,
            )
            sections.append(
                PresentationSection(
                    kind="judgement",
                    copy_text=writer.content.text,
                    used_fact_ids=writer.content.used_fact_ids,
                    used_constraint_ids=(
                        writer.content.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "answer":
            if not packet.slots:
                raise _DraftCompilationError(
                    "answer section requires one slot"
                )
            writer = writer_section(
                "answer",
                packet.slots[0].slot_id,
            )
            sections.append(
                PresentationSection(
                    kind="answer",
                    copy_text=writer.content.text,
                    used_fact_ids=writer.content.used_fact_ids,
                    used_constraint_ids=(
                        writer.content.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "closing":
            writer = writer_section("closing")
            sections.append(
                PresentationSection(
                    kind="closing",
                    copy_text=writer.content.text,
                    used_fact_ids=writer.content.used_fact_ids,
                    used_constraint_ids=(
                        writer.content.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "general_knowledge":
            writer = writer_section("general_knowledge")
            sections.append(
                PresentationSection(
                    kind="general_knowledge",
                    copy_text=writer.content.text,
                    used_fact_ids=writer.content.used_fact_ids,
                    used_constraint_ids=(
                        writer.content.used_constraint_ids
                    ),
                )
            )
        elif spec.kind == "observation":
            sections.append(
                PresentationSection(
                    kind="observation",
                    copy_text=_observation_text(packet),
                )
            )
        elif spec.kind == "comparison":
            sections.append(PresentationSection(kind="comparison"))
        elif spec.kind == "question":
            sections.append(
                PresentationSection(
                    kind="question",
                    copy_text=(
                        "还需要补充一个关键信息，"
                        "才能继续给出可靠结果。"
                    ),
                )
            )
        elif spec.kind == "error":
            sections.append(
                PresentationSection(
                    kind="error",
                    copy_text=(
                        "这次暂时没有得到可用结果，"
                        "请稍后重试或换一种说法。"
                    ),
                )
            )
        else:
            sections.append(PresentationSection(kind=spec.kind))
    return tuple(sections)


def _observation_text(packet: PresentationPacket) -> str:
    if (
        packet.responsibility is not None
        and packet.responsibility.value == "image_identity"
    ):
        names = "、".join(slot.name for slot in packet.slots)
        return (
            f"已确认图片里的商品是{names}。"
            if len(packet.slots) == 1
            else f"已确认图片里的商品依次是{names}。"
        )
    return (
        "以下观察只基于当前已提供的信息，"
        "不替代诊断或治疗建议。"
    )


def _telemetry_from_call(
    call: CopywriterCallResult,
    *,
    fallback_reason: str | None = None,
) -> CopywriterTelemetry:
    prompt_tokens = call.usage.prompt_tokens or 0
    completion_tokens = call.usage.completion_tokens or 0
    return CopywriterTelemetry(
        provider=call.provider,
        model=call.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=call.latency_ms,
        fallback_reason=fallback_reason,
    )


__all__ = [
    "CopywriterPolicy",
    "PresentationCompileInputs",
    "PresentationCompiler",
    "compile_presentation",
]
