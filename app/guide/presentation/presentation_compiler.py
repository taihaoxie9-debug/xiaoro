from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.guide.adapters.llm.contracts import SemanticProviderFailure
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
    PresentationCopywriterPort,
)
from app.guide.intent.responsibility_matrix import (
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
    CopywriterDraft,
    CopywriterSection,
    CopywriterTelemetry,
    DirectFactComponent,
    PresentationPacket,
    PresentationSection,
    SourceTaggedCopy,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
from app.guide.presentation.copywriter_validation import (
    CopywriterValidationError,
    validate_copywriter_draft,
)
from app.guide.presentation.public_contracts import (
    PublicPresentationContract,
)


CopywriterPolicy = Literal[
    "eligible",
    "medical_escalation",
    "evidence_gap",
]


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

    deterministic_reason = _deterministic_reason(inputs)
    if deterministic_reason is not None:
        return _compile_fallback(
            inputs,
            reason=deterministic_reason,
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


def _deterministic_reason(
    inputs: PresentationCompileInputs,
) -> str | None:
    if inputs.packet.mode in {
        "clarification",
        "error",
        "image_identity",
    }:
        return "copywriter_not_called"
    if inputs.copywriter_policy != "eligible":
        return inputs.copywriter_policy
    return None


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
        copy_source="fallback",
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
            fallback_reason="authoritative_public_copy",
        ),
    )


def _compile_contract(
    inputs: PresentationCompileInputs,
    *,
    draft: CopywriterDraft,
    copy_source: Literal["model", "fallback"],
    telemetry: CopywriterTelemetry,
) -> PublicPresentationContract:
    sections = _compile_sections(inputs.packet, draft)
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
        copy_source=copy_source,
        sections=sections,
        comparison_rows=comparison_rows,
        visible_product_ids=(
            inputs.card_display.visible_product_ids
        ),
        compact_tags=compact_tags,
        card_display=inputs.card_display,
        telemetry=telemetry,
    )


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
                        for fact in slot.locked_facts
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
            writer = writer_section("product", spec.slot_id)
            slot = slot_by_id[spec.slot_id]
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
                    direct_facts=tuple(
                        DirectFactComponent(
                            fact_id=fact.fact_id,
                            label=fact.label,
                            display_value=fact.display_value,
                        )
                        for fact in slot.locked_facts
                    ),
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
                    copy_text=(
                        "以下观察只基于当前已提供的信息，"
                        "不替代诊断或治疗建议。"
                    ),
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
