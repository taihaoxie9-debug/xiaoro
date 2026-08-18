from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.public_language import validate_public_text


PresentationMode = Literal[
    "recommendation",
    "comparison",
    "single_product",
    "product_knowledge",
    "general_knowledge",
    "followup",
    "revision",
    "image_identity",
    "image_recommendation",
    "image_suitability",
    "image_comparison",
    "consultation",
    "clarification",
    "error",
]
CategoryProfileValue = Literal[
    "skincare",
    "suncare",
    "base_makeup",
    "cleanser",
    "color_makeup",
    "fragrance",
]
FactAttribution = Literal[
    "verified_fact",
    "merchant_claim",
    "consumer_report",
]
SectionKind = Literal[
    "summary",
    "product",
    "general_knowledge",
    "comparison",
    "question",
    "observation",
    "error",
    "closing",
    "pitfalls",
    "full_cards",
    "evidence",
]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


def _tuple(value: object) -> object:
    return tuple(value) if isinstance(value, list) else value


def _require_unique(values: tuple[str, ...], *, label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class ApprovedSoftFact(_StrictFrozen):
    fact_id: str = Field(min_length=1, max_length=160)
    product_id: int = Field(gt=0)
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    plain_meaning: str = Field(min_length=1, max_length=512)
    attribution: FactAttribution
    source_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("source_refs", mode="before")
    @classmethod
    def freeze_source_refs(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_source_refs(self) -> Self:
        _require_unique(self.source_refs, label="soft fact source refs")
        return self


class LockedFact(_StrictFrozen):
    fact_id: str = Field(min_length=1, max_length=160)
    product_id: int = Field(gt=0)
    kind: Literal[
        "price",
        "specification",
        "numeric",
        "ingredient",
        "package_warning",
        "merchant_quote",
        "consumer_quote",
        "verified_text",
    ]
    label: str = Field(min_length=1, max_length=64)
    display_value: str = Field(min_length=1, max_length=512)
    numeric_value: Decimal | None = None
    source_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("source_refs", mode="before")
    @classmethod
    def freeze_source_refs(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_locked_fact(self) -> Self:
        _require_unique(self.source_refs, label="locked fact source refs")
        if self.numeric_value is not None and not self.numeric_value.is_finite():
            raise ValueError("locked numeric fact must be finite")
        return self


class DirectCaution(_StrictFrozen):
    caution_id: str = Field(min_length=1, max_length=160)
    product_id: int | None = Field(default=None, gt=0)
    severity: Literal["high", "medium", "low"]
    text: str = Field(min_length=1, max_length=512)
    source_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("source_refs", mode="before")
    @classmethod
    def freeze_source_refs(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_source_refs(self) -> Self:
        _require_unique(self.source_refs, label="caution source refs")
        return self


class CopySlot(_StrictFrozen):
    slot_id: str = Field(pattern=r"^p[1-4]$")
    product_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=256)
    category_profile: CategoryProfileValue
    approved_soft_facts: tuple[ApprovedSoftFact, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    locked_facts: tuple[LockedFact, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    required_cautions: tuple[DirectCaution, ...] = Field(
        default_factory=tuple,
        max_length=6,
    )

    @field_validator(
        "approved_soft_facts",
        "locked_facts",
        "required_cautions",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_fact_ownership(self) -> Self:
        owned = (
            *self.approved_soft_facts,
            *self.locked_facts,
            *self.required_cautions,
        )
        if any(
            item.product_id is not None
            and item.product_id != self.product_id
            for item in owned
        ):
            raise ValueError("copy slot facts must belong to slot product")
        fact_ids = tuple(
            item.fact_id
            for item in (*self.approved_soft_facts, *self.locked_facts)
        )
        _require_unique(fact_ids, label="copy slot fact IDs")
        caution_ids = tuple(
            item.caution_id for item in self.required_cautions
        )
        _require_unique(caution_ids, label="copy slot caution IDs")
        return self


class CopyLengthBudget(_StrictFrozen):
    summary_max_chars: int = Field(ge=40, le=400)
    positioning_max_chars: int = Field(ge=30, le=200)
    advisor_reason_max_chars: int = Field(ge=30, le=240)
    closing_max_chars: int = Field(ge=40, le=400)


class PresentationSectionSpec(_StrictFrozen):
    kind: SectionKind
    slot_id: str | None = Field(default=None, pattern=r"^p[1-4]$")

    @model_validator(mode="after")
    def validate_slot_shape(self) -> Self:
        if self.kind == "product" and self.slot_id is None:
            raise ValueError("product section requires slot ID")
        if self.kind != "product" and self.slot_id is not None:
            raise ValueError("non-product section forbids slot ID")
        return self


class PresentationPacket(_StrictFrozen):
    mode: PresentationMode
    user_need_summary: str = Field(min_length=1, max_length=512)
    winner_status: str | None = Field(default=None, max_length=96)
    slots: tuple[CopySlot, ...] = Field(default_factory=tuple, max_length=4)
    section_order: tuple[PresentationSectionSpec, ...] = Field(min_length=1)
    copy_budget: CopyLengthBudget

    @field_validator("slots", "section_order", mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_slots_and_sections(self) -> Self:
        slot_ids = tuple(slot.slot_id for slot in self.slots)
        product_ids = tuple(slot.product_id for slot in self.slots)
        _require_unique(slot_ids, label="presentation slot IDs")
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("presentation product IDs must be unique")
        section_slots = tuple(
            section.slot_id
            for section in self.section_order
            if section.kind == "product"
        )
        if section_slots != slot_ids:
            raise ValueError(
                "product sections must exactly match packet slot order"
            )
        if not self.slots and any(
            section.kind in {"product", "full_cards"}
            for section in self.section_order
        ):
            raise ValueError("zero-slot packet forbids product card sections")
        kinds = tuple(section.kind for section in self.section_order)
        product_sections = tuple(
            "product" for _ in self.slots
        )
        if self.mode == "product_knowledge":
            if len(self.slots) != 1:
                raise ValueError(
                    "product knowledge requires one product"
                )
            if kinds != (*product_sections, "full_cards"):
                raise ValueError(
                    "product knowledge has dedicated section duties"
                )
        elif self.mode == "general_knowledge":
            if self.slots or kinds != ("general_knowledge",):
                raise ValueError(
                    "general knowledge requires one zero-card body"
                )
        elif self.mode == "recommendation":
            expected = (
                ("summary", "closing")
                if not self.slots
                else (
                    "summary",
                    *product_sections,
                    "closing",
                    "full_cards",
                    "pitfalls",
                )
            )
            if kinds != expected:
                raise ValueError(
                    "recommendation section duties mismatch"
                )
        elif self.mode == "comparison":
            if not 2 <= len(self.slots) <= 3:
                raise ValueError(
                    "comparison requires two or three products"
                )
            expected = (
                "summary",
                "comparison",
                *product_sections,
                "closing",
                "full_cards",
                "pitfalls",
            )
            if kinds != expected:
                raise ValueError(
                    "comparison section duties mismatch"
                )
        return self


class ProductCopy(_StrictFrozen):
    slot_id: str = Field(pattern=r"^p[1-4]$")
    positioning: str = Field(min_length=1, max_length=240)
    advisor_reason: str = Field(min_length=1, max_length=280)
    used_soft_fact_ids: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("used_soft_fact_ids", mode="before")
    @classmethod
    def freeze_fact_ids(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_fact_ids(self) -> Self:
        _require_unique(
            self.used_soft_fact_ids,
            label="used soft fact IDs",
        )
        return self


class CopywriterDraft(_StrictFrozen):
    mode: PresentationMode
    summary_copy: str = Field(min_length=1, max_length=800)
    product_copy: tuple[ProductCopy, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    closing_copy: str | None = Field(default=None, max_length=800)

    @field_validator("product_copy", mode="before")
    @classmethod
    def freeze_product_copy(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_slot_ids(self) -> Self:
        slot_ids = tuple(item.slot_id for item in self.product_copy)
        _require_unique(slot_ids, label="copywriter product slot IDs")
        return self


class DirectFactComponent(_StrictFrozen):
    fact_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=64)
    display_value: str = Field(min_length=1, max_length=512)


class PresentationSection(_StrictFrozen):
    kind: SectionKind
    copy_text: str | None = Field(default=None, max_length=1200)
    advisor_reason: str | None = Field(default=None, max_length=400)
    slot_id: str | None = Field(default=None, pattern=r"^p[1-4]$")
    product_id: int | None = Field(default=None, gt=0)
    direct_facts: tuple[DirectFactComponent, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )

    @field_validator("direct_facts", mode="before")
    @classmethod
    def freeze_direct_facts(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.copy_text is not None:
            validate_public_text(self.copy_text)
        if self.advisor_reason is not None:
            validate_public_text(self.advisor_reason)
        if self.kind == "product":
            if self.slot_id is None or self.product_id is None:
                raise ValueError(
                    "product presentation section requires slot and product"
                )
        elif self.slot_id is not None or self.product_id is not None:
            raise ValueError(
                "non-product presentation section forbids product binding"
            )
        elif self.advisor_reason is not None:
            raise ValueError(
                "non-product presentation section forbids advisor reason"
            )
        if self.kind in {
            "summary",
            "product",
            "general_knowledge",
            "question",
            "observation",
            "error",
            "closing",
        } and not self.copy_text:
            raise ValueError(f"{self.kind} section requires copy")
        if self.kind not in {"product"} and self.direct_facts:
            raise ValueError("only product section accepts direct facts")
        return self


class CopywriterTelemetry(_StrictFrozen):
    provider: str = Field(min_length=1, max_length=96)
    model: str = Field(min_length=1, max_length=256)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    fallback_reason: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_token_total(self) -> Self:
        if self.total_tokens != (
            self.prompt_tokens + self.completion_tokens
        ):
            raise ValueError("copywriter token total must match components")
        return self


class _PresentationBase(_StrictFrozen):
    copy_source: Literal["model", "fallback"]
    sections: tuple[PresentationSection, ...] = Field(min_length=1)
    card_display: CardDisplayContract
    telemetry: CopywriterTelemetry

    @field_validator("sections", mode="before")
    @classmethod
    def freeze_sections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_card_sections(self) -> Self:
        visible = self.card_display.visible_product_ids
        product_ids = tuple(
            section.product_id
            for section in self.sections
            if section.kind == "product"
        )
        full_card_positions = tuple(
            index
            for index, section in enumerate(self.sections)
            if section.kind == "full_cards"
        )
        if visible:
            if product_ids != visible:
                raise ValueError(
                    "presentation product sections must match visible cards"
                )
            if len(full_card_positions) != 1:
                raise ValueError(
                    "visible product presentation requires one full shelf"
                )
            product_positions = [
                index
                for index, section in enumerate(self.sections)
                if section.kind == "product"
            ]
            if product_positions and full_card_positions[0] <= max(
                product_positions
            ):
                raise ValueError(
                    "full card shelf must follow product sections"
                )
        elif product_ids or full_card_positions:
            raise ValueError(
                "zero-card presentation forbids product card sections"
            )
        pitfall_positions = [
            index
            for index, section in enumerate(self.sections)
            if section.kind == "pitfalls"
        ]
        if (
            pitfall_positions
            and full_card_positions
            and pitfall_positions[0] <= max(full_card_positions)
        ):
            raise ValueError("pitfalls must follow the full card shelf")
        if self.copy_source == "model" and self.telemetry.fallback_reason:
            raise ValueError("model copy forbids fallback reason")
        if self.copy_source == "fallback" and not (
            self.telemetry.fallback_reason
        ):
            raise ValueError("fallback copy requires fallback reason")
        if self.mode == "product_knowledge":
            if any(
                section.kind == "product"
                and section.advisor_reason is not None
                for section in self.sections
            ):
                raise ValueError(
                    "product knowledge forbids advisor reason"
                )
        elif any(
            section.kind == "product"
            and not section.advisor_reason
            for section in self.sections
        ):
            raise ValueError(
                "advisor modes require product advisor reason"
            )
        return self


class RecommendationPresentationData(_PresentationBase):
    mode: Literal["recommendation"] = "recommendation"


class ComparisonPresentationData(_PresentationBase):
    mode: Literal["comparison"] = "comparison"


class SingleProductPresentationData(_PresentationBase):
    mode: Literal["single_product"] = "single_product"


class ProductKnowledgePresentationData(_PresentationBase):
    mode: Literal["product_knowledge"] = "product_knowledge"


class GeneralKnowledgePresentationData(_PresentationBase):
    mode: Literal["general_knowledge"] = "general_knowledge"


class FollowupPresentationData(_PresentationBase):
    mode: Literal["followup"] = "followup"


class RevisionPresentationData(_PresentationBase):
    mode: Literal["revision"] = "revision"


class ImageIdentityPresentationData(_PresentationBase):
    mode: Literal["image_identity"] = "image_identity"


class ImageRecommendationPresentationData(_PresentationBase):
    mode: Literal["image_recommendation"] = "image_recommendation"


class ImageSuitabilityPresentationData(_PresentationBase):
    mode: Literal["image_suitability"] = "image_suitability"


class ImageComparisonPresentationData(_PresentationBase):
    mode: Literal["image_comparison"] = "image_comparison"


class ConsultationPresentationData(_PresentationBase):
    mode: Literal["consultation"] = "consultation"


class ClarificationPresentationData(_PresentationBase):
    mode: Literal["clarification"] = "clarification"


class ErrorPresentationData(_PresentationBase):
    mode: Literal["error"] = "error"


PresentationContractData = Annotated[
    RecommendationPresentationData
    | ComparisonPresentationData
    | SingleProductPresentationData
    | ProductKnowledgePresentationData
    | GeneralKnowledgePresentationData
    | FollowupPresentationData
    | RevisionPresentationData
    | ImageIdentityPresentationData
    | ImageRecommendationPresentationData
    | ImageSuitabilityPresentationData
    | ImageComparisonPresentationData
    | ConsultationPresentationData
    | ClarificationPresentationData
    | ErrorPresentationData,
    Field(discriminator="mode"),
]


__all__ = [
    "ApprovedSoftFact",
    "ClarificationPresentationData",
    "ComparisonPresentationData",
    "ConsultationPresentationData",
    "CopyLengthBudget",
    "CopySlot",
    "CopywriterDraft",
    "CopywriterTelemetry",
    "DirectCaution",
    "DirectFactComponent",
    "ErrorPresentationData",
    "FollowupPresentationData",
    "GeneralKnowledgePresentationData",
    "ImageComparisonPresentationData",
    "ImageIdentityPresentationData",
    "ImageRecommendationPresentationData",
    "ImageSuitabilityPresentationData",
    "LockedFact",
    "PresentationContractData",
    "PresentationMode",
    "PresentationPacket",
    "PresentationSection",
    "PresentationSectionSpec",
    "ProductCopy",
    "ProductKnowledgePresentationData",
    "RecommendationPresentationData",
    "RevisionPresentationData",
    "SingleProductPresentationData",
]
