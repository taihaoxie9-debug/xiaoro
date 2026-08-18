from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.guide.adapters.llm.contracts import SemanticProviderFailure
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
    PresentationCopywriterPort,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.copywriter_contracts import (
    ClarificationPresentationData,
    ComparisonPresentationData,
    ConsultationPresentationData,
    CopywriterDraft,
    CopywriterTelemetry,
    DirectFactComponent,
    ErrorPresentationData,
    FollowupPresentationData,
    GeneralKnowledgePresentationData,
    ImageComparisonPresentationData,
    ImageIdentityPresentationData,
    ImageRecommendationPresentationData,
    ImageSuitabilityPresentationData,
    PresentationContractData,
    PresentationPacket,
    PresentationSection,
    ProductKnowledgePresentationData,
    RecommendationPresentationData,
    RevisionPresentationData,
    SingleProductPresentationData,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
from app.guide.presentation.copywriter_validation import (
    CopywriterValidationError,
    validate_copywriter_draft,
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

    @model_validator(mode="after")
    def validate_card_authority(self) -> Self:
        packet_ids = tuple(slot.product_id for slot in self.packet.slots)
        if packet_ids != self.card_display.visible_product_ids:
            raise ValueError(
                "visible product IDs must exactly match packet slots"
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
    ) -> PresentationContractData:
        return compile_presentation(
            inputs,
            copywriter=self._copywriter,
        )


def compile_presentation(
    inputs: PresentationCompileInputs,
    *,
    copywriter: PresentationCopywriterPort | None,
) -> PresentationContractData:
    if not isinstance(inputs, PresentationCompileInputs):
        raise TypeError("inputs must be PresentationCompileInputs")

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
    if inputs.packet.mode in {"clarification", "error"}:
        return "copywriter_not_called"
    if inputs.copywriter_policy != "eligible":
        return inputs.copywriter_policy
    return None


def _compile_fallback(
    inputs: PresentationCompileInputs,
    *,
    reason: str,
    call: CopywriterCallResult | None = None,
) -> PresentationContractData:
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


def _compile_contract(
    inputs: PresentationCompileInputs,
    *,
    draft: CopywriterDraft,
    copy_source: Literal["model", "fallback"],
    telemetry: CopywriterTelemetry,
) -> PresentationContractData:
    sections = _compile_sections(inputs.packet, draft)
    values = {
        "copy_source": copy_source,
        "sections": sections,
        "card_display": inputs.card_display,
        "telemetry": telemetry,
    }
    mode = inputs.packet.mode
    if mode == "recommendation":
        return RecommendationPresentationData(**values)
    if mode == "comparison":
        return ComparisonPresentationData(**values)
    if mode == "single_product":
        return SingleProductPresentationData(**values)
    if mode == "product_knowledge":
        return ProductKnowledgePresentationData(**values)
    if mode == "general_knowledge":
        return GeneralKnowledgePresentationData(**values)
    if mode == "followup":
        return FollowupPresentationData(**values)
    if mode == "revision":
        return RevisionPresentationData(**values)
    if mode == "image_identity":
        return ImageIdentityPresentationData(**values)
    if mode == "image_recommendation":
        return ImageRecommendationPresentationData(**values)
    if mode == "image_suitability":
        return ImageSuitabilityPresentationData(**values)
    if mode == "image_comparison":
        return ImageComparisonPresentationData(**values)
    if mode == "consultation":
        return ConsultationPresentationData(**values)
    if mode == "clarification":
        return ClarificationPresentationData(**values)
    if mode == "error":
        return ErrorPresentationData(**values)
    raise AssertionError(f"unsupported presentation mode: {mode}")


def _compile_sections(
    packet: PresentationPacket,
    draft: CopywriterDraft,
) -> tuple[PresentationSection, ...]:
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
                    copy_text=draft.summary_copy,
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
                    copy_text=item.positioning,
                    advisor_reason=(
                        None
                        if packet.mode == "product_knowledge"
                        else item.advisor_reason
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
        elif spec.kind == "closing":
            if draft.closing_copy is None:
                raise _DraftCompilationError(
                    "closing section missing copy"
                )
            sections.append(
                PresentationSection(
                    kind="closing",
                    copy_text=draft.closing_copy,
                )
            )
        elif spec.kind == "question":
            sections.append(
                PresentationSection(
                    kind="question",
                    copy_text=draft.summary_copy,
                )
            )
        elif spec.kind == "error":
            sections.append(
                PresentationSection(
                    kind="error",
                    copy_text=draft.summary_copy,
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
            sections.append(
                PresentationSection(
                    kind="comparison",
                    copy_text="下面按同一组已核对信息看差异。",
                )
            )
        elif spec.kind == "general_knowledge":
            sections.append(
                PresentationSection(
                    kind="general_knowledge",
                    copy_text=draft.summary_copy,
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
