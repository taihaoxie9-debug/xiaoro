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

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.public_fact_contracts import (
    ProjectedPublicFact,
)
from app.guide.presentation.public_language import validate_public_text
from app.guide.understanding.turn_meaning_contracts import (
    RecommendationMode,
)


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
WinnerClaim = Literal[
    "none",
    "not_selected",
    "selected",
]
DimensionId = Annotated[
    str,
    Field(
        min_length=2,
        max_length=128,
        pattern=(
            r"^[a-z][a-z0-9_]{1,63}"
            r"(?:\.[a-z][a-z0-9_]{1,63})?$"
        ),
    ),
]


def responsibility_for_presentation_mode(
    mode: PresentationMode,
) -> Responsibility:
    if mode in {
        "recommendation",
        "followup",
        "revision",
        "image_recommendation",
    }:
        return Responsibility.RECOMMENDATION
    if mode in {"comparison", "image_comparison"}:
        return Responsibility.COMPARISON
    if mode in {"single_product", "image_suitability"}:
        return Responsibility.SINGLE_PRODUCT_SUITABILITY
    if mode == "product_knowledge":
        return Responsibility.PRODUCT_KNOWLEDGE
    if mode == "general_knowledge":
        return Responsibility.GENERAL_KNOWLEDGE
    if mode == "consultation":
        return Responsibility.CONSULTATION
    if mode == "image_identity":
        return Responsibility.IMAGE_IDENTITY
    return Responsibility.CLARIFICATION
SectionKind = Literal[
    "summary",
    "product",
    "judgement",
    "answer",
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
WriterSectionKind = Literal[
    "summary",
    "product",
    "judgement",
    "answer",
    "general_knowledge",
    "closing",
]
CopywriterContentSource = Literal[
    "constraints_only",
    "approved_facts",
]
CopySource = Literal["model", "authoritative", "fallback"]
CopywriterPolicy = Literal[
    "eligible",
    "medical_escalation",
    "evidence_gap",
]
_DETERMINISTIC_PRESENTATION_MODES = frozenset(
    {"clarification", "error", "image_identity"}
)
_DETERMINISTIC_COPYWRITER_POLICIES = frozenset(
    {"medical_escalation", "evidence_gap"}
)


def deterministic_copy_source(
    *,
    mode: str,
    copywriter_policy: CopywriterPolicy,
    has_authoritative_public_copy: bool = False,
) -> CopySource | None:
    if has_authoritative_public_copy:
        return "authoritative"
    if (
        mode in _DETERMINISTIC_PRESENTATION_MODES
        or copywriter_policy in _DETERMINISTIC_COPYWRITER_POLICIES
    ):
        return "authoritative"
    return None


def validate_copy_provenance(
    *,
    copy_source: CopySource,
    fallback_reason: str | None,
) -> None:
    if copy_source not in {"model", "authoritative", "fallback"}:
        raise ValueError("unknown copy source")
    if copy_source in {"model", "authoritative"}:
        if fallback_reason is not None:
            raise ValueError(
                "non-fallback copy forbids fallback reason"
            )
        return
    if fallback_reason is None:
        raise ValueError("fallback copy requires fallback reason")


def successful_copy_provenance(
    *,
    copy_source: object,
    fallback_reason: object,
) -> bool:
    try:
        validate_copy_provenance(
            copy_source=copy_source,  # type: ignore[arg-type]
            fallback_reason=fallback_reason,  # type: ignore[arg-type]
        )
    except ValueError:
        return False
    return copy_source in {"model", "authoritative"}


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
    dimension_ids: tuple[DimensionId, ...] = ()
    plain_meaning: str = Field(min_length=1, max_length=512)
    attribution: FactAttribution
    source_refs: tuple[str, ...] = Field(min_length=1)
    generic_copy_allowed: bool = True

    @field_validator("dimension_ids", "source_refs", mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        dimension_ids = (
            self.dimension_ids
            if self.dimension_ids
            else (self.field_key,)
        )
        if any(
            dimension_id != self.field_key
            and not dimension_id.startswith(f"{self.field_key}.")
            for dimension_id in dimension_ids
        ):
            raise ValueError(
                "soft fact dimensions must belong to its field"
            )
        _require_unique(
            dimension_ids,
            label="soft fact dimension IDs",
        )
        _require_unique(self.source_refs, label="soft fact source refs")
        object.__setattr__(self, "dimension_ids", dimension_ids)
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


class ComparisonDimensionEvidence(_StrictFrozen):
    product_id: int = Field(gt=0)
    dimension_id: str = Field(
        pattern=r"^[a-z][a-z0-9_.]{1,95}$"
    )
    match_status: Literal["matched", "mismatch", "unknown"]
    display_value: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    fact_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=3)
    source_refs: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    attribution: FactAttribution | None = None

    @field_validator("fact_ids", "source_refs", mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        _require_unique(self.fact_ids, label="comparison fact IDs")
        _require_unique(self.source_refs, label="comparison source refs")
        if self.match_status == "unknown":
            if (
                self.display_value is not None
                or self.fact_ids
                or self.source_refs
                or self.attribution is not None
            ):
                raise ValueError(
                    "unknown comparison dimension forbids evidence"
                )
        elif (
            self.display_value is None
            or not self.fact_ids
            or not self.source_refs
            or self.attribution is None
        ):
            raise ValueError(
                "known comparison dimension requires evidence"
            )
        return self


class CompactTagEvidence(_StrictFrozen):
    product_id: int = Field(gt=0)
    fact_id: str = Field(min_length=1, max_length=160)
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str = Field(min_length=1, max_length=24)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=8)
    attribution: FactAttribution

    @field_validator("source_refs", mode="before")
    @classmethod
    def freeze_source_refs(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        _require_unique(
            self.source_refs,
            label="compact tag source refs",
        )
        return self


class CopySlot(_StrictFrozen):
    slot_id: str = Field(pattern=r"^p[1-4]$")
    product_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=256)
    category_profile: CategoryProfileValue
    approved_soft_facts: tuple[ApprovedSoftFact, ...] = Field(
        default_factory=tuple,
        max_length=128,
    )
    detail_facts: tuple[ProjectedPublicFact, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    locked_facts: tuple[LockedFact, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    required_cautions: tuple[DirectCaution, ...] = Field(
        default_factory=tuple,
        max_length=6,
    )
    comparison_evidence: tuple[
        ComparisonDimensionEvidence,
        ...,
    ] = Field(default_factory=tuple, max_length=12)
    compact_tag_evidence: tuple[
        CompactTagEvidence,
        ...,
    ] = Field(default_factory=tuple, max_length=24)

    @field_validator(
        "approved_soft_facts",
        "detail_facts",
        "locked_facts",
        "required_cautions",
        "comparison_evidence",
        "compact_tag_evidence",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_fact_ownership(self) -> Self:
        owned = (
            *self.approved_soft_facts,
            *self.detail_facts,
            *self.locked_facts,
            *self.required_cautions,
            *self.comparison_evidence,
            *self.compact_tag_evidence,
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
        detail_fact_ids = tuple(
            item.fact_id for item in self.detail_facts
        )
        _require_unique(
            detail_fact_ids,
            label="copy slot detail fact IDs",
        )
        if set(detail_fact_ids) - {
            item.fact_id for item in self.approved_soft_facts
        }:
            raise ValueError(
                "detail facts must belong to approved soft facts"
            )
        caution_ids = tuple(
            item.caution_id for item in self.required_cautions
        )
        _require_unique(caution_ids, label="copy slot caution IDs")
        dimension_ids = tuple(
            item.dimension_id for item in self.comparison_evidence
        )
        _require_unique(
            dimension_ids,
            label="copy slot comparison dimensions",
        )
        compact_fact_ids = tuple(
            item.fact_id for item in self.compact_tag_evidence
        )
        _require_unique(
            compact_fact_ids,
            label="copy slot compact tag facts",
        )
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


class ApprovedConstraint(_StrictFrozen):
    constraint_id: str = Field(min_length=1, max_length=160)
    kind: Literal[
        "budget",
        "category",
        "facet",
        "concept",
        "context",
        "safety",
    ]
    display_value: str = Field(min_length=1, max_length=512)


class PresentationPacket(_StrictFrozen):
    mode: PresentationMode
    responsibility: Responsibility | None = None
    recommendation_mode: RecommendationMode | None = None
    user_need_summary: str = Field(min_length=1, max_length=512)
    winner_status: str | None = Field(default=None, max_length=96)
    winner_product_id: int | None = Field(default=None, gt=0)
    winner_tie_reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=400,
    )
    slots: tuple[CopySlot, ...] = Field(default_factory=tuple, max_length=4)
    section_order: tuple[PresentationSectionSpec, ...] = Field(min_length=1)
    requested_dimensions: tuple[str, ...] = ()
    approved_constraints: tuple[ApprovedConstraint, ...] = ()
    copy_budget: CopyLengthBudget

    @field_validator(
        "slots",
        "section_order",
        "requested_dimensions",
        "approved_constraints",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_slots_and_sections(self) -> Self:
        responsibility = (
            self.responsibility
            or responsibility_for_presentation_mode(self.mode)
        )
        object.__setattr__(self, "responsibility", responsibility)
        if responsibility is Responsibility.RECOMMENDATION:
            if self.recommendation_mode is None:
                raise ValueError(
                    "recommendation packet requires recommendation mode"
                )
            if self.recommendation_mode == "explore":
                if (
                    self.winner_status
                    in {"SELECTED", "WINNER", "winner"}
                    or self.winner_product_id is not None
                ):
                    raise ValueError(
                        "explore recommendation forbids winner"
                    )
            elif (
                len(self.slots) != 1
                or self.winner_status
                not in {"SELECTED", "WINNER", "winner"}
                or self.winner_product_id != self.slots[0].product_id
            ):
                raise ValueError(
                    "fit recommendation requires one selected product"
                )
        elif self.recommendation_mode is not None:
            raise ValueError(
                "non-recommendation packet forbids recommendation mode"
            )
        if (
            responsibility is Responsibility.COMPARISON
            and self.winner_status in {"SELECTED", "WINNER", "winner"}
            and self.winner_product_id is None
        ):
            raise ValueError(
                "selected comparison winner requires product ID"
            )
        if (
            self.winner_status not in {"SELECTED", "WINNER", "winner"}
            and self.winner_product_id is not None
        ):
            raise ValueError(
                "winner product ID requires selected status"
            )
        if (
            self.requested_dimensions
            != tuple(dict.fromkeys(self.requested_dimensions))
            or any(
                not value or value != value.strip()
                for value in self.requested_dimensions
            )
        ):
            raise ValueError(
                "requested dimensions must be ordered unique values"
            )
        slot_ids = tuple(slot.slot_id for slot in self.slots)
        product_ids = tuple(slot.product_id for slot in self.slots)
        _require_unique(slot_ids, label="presentation slot IDs")
        _require_unique(
            tuple(
                item.constraint_id
                for item in self.approved_constraints
            ),
            label="approved constraint IDs",
        )
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("presentation product IDs must be unique")
        section_slots = tuple(
            section.slot_id
            for section in self.section_order
            if section.kind == "product"
        )
        if responsibility is Responsibility.RECOMMENDATION:
            if section_slots != slot_ids:
                raise ValueError(
                    "recommendation product sections must match slot order"
                )
        elif responsibility is Responsibility.IMAGE_IDENTITY:
            if section_slots != slot_ids:
                raise ValueError(
                    "image identity product section must match slot"
                )
        elif section_slots:
            raise ValueError(
                "non-recommendation packet forbids product sections"
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
        if responsibility is Responsibility.PRODUCT_KNOWLEDGE:
            if len(self.slots) != 1:
                raise ValueError(
                    "product knowledge requires one product"
                )
            if kinds != ("summary", "answer", "full_cards"):
                raise ValueError(
                    "product knowledge has dedicated section duties"
                )
        elif responsibility is Responsibility.GENERAL_KNOWLEDGE:
            if self.slots or kinds != ("general_knowledge",):
                raise ValueError(
                    "general knowledge requires one zero-card body"
                )
        elif responsibility is Responsibility.RECOMMENDATION:
            expected = (
                ("summary", "closing")
                if not self.slots
                else (
                    "summary",
                    *product_sections,
                    "closing",
                    "full_cards",
                )
            )
            if kinds != expected:
                raise ValueError(
                    "recommendation section duties mismatch"
                )
        elif responsibility is Responsibility.COMPARISON:
            if not 2 <= len(self.slots) <= 3:
                raise ValueError(
                    "comparison requires two or three products"
                )
            expected = (
                "summary",
                "comparison",
                "full_cards",
            )
            if kinds != expected:
                raise ValueError(
                    "comparison section duties mismatch"
                )
        elif (
            responsibility
            is Responsibility.SINGLE_PRODUCT_SUITABILITY
        ):
            if len(self.slots) != 1 or kinds != (
                "summary",
                "judgement",
                "full_cards",
            ):
                raise ValueError(
                    "single product suitability duties mismatch"
                )
        elif responsibility is Responsibility.IMAGE_IDENTITY:
            if not 1 <= len(self.slots) <= 4 or kinds != (
                "observation",
                *product_sections,
                "full_cards",
            ):
                raise ValueError("image identity duties mismatch")
        return self


class SourceTaggedCopy(_StrictFrozen):
    text: str = Field(min_length=1, max_length=1200)
    winner_claim: WinnerClaim = "none"
    used_fact_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    used_constraint_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )

    @field_validator(
        "used_fact_ids",
        "used_constraint_ids",
        mode="before",
    )
    @classmethod
    def freeze_ids(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        _require_unique(
            self.used_fact_ids,
            label="used fact IDs",
        )
        _require_unique(
            self.used_constraint_ids,
            label="used constraint IDs",
        )
        return self


def section_copy_blocks_include_winner_claim(raw: object) -> bool:
    if not isinstance(raw, dict):
        return True
    sections = raw.get("sections")
    if sections is None:
        return True
    if not isinstance(sections, list):
        return True
    for section in sections:
        if not isinstance(section, dict):
            continue
        content = section.get("content")
        if isinstance(content, dict) and "winner_claim" not in content:
            return False
        advisor_reason = section.get("advisor_reason")
        if (
            isinstance(advisor_reason, dict)
            and "winner_claim" not in advisor_reason
        ):
            return False
    return True


class ProductCopy(_StrictFrozen):
    slot_id: str = Field(pattern=r"^p[1-4]$")
    positioning: SourceTaggedCopy
    advisor_reason: SourceTaggedCopy


class CopywriterSection(_StrictFrozen):
    kind: WriterSectionKind
    content: SourceTaggedCopy
    slot_id: str | None = Field(default=None, pattern=r"^p[1-4]$")
    advisor_reason: SourceTaggedCopy | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.kind == "product":
            if self.slot_id is None or self.advisor_reason is None:
                raise ValueError(
                    "product copywriter section requires slot and advisor"
                )
        elif self.kind in {"judgement", "answer"}:
            if self.slot_id is None or self.advisor_reason is not None:
                raise ValueError(
                    "bound writer section requires slot without advisor"
                )
        elif self.slot_id is not None or self.advisor_reason is not None:
            raise ValueError(
                "non-product copywriter section forbids slot and advisor"
            )
        return self


class CopywriterSectionSpec(_StrictFrozen):
    kind: WriterSectionKind
    content_source: CopywriterContentSource
    evidence_location: str = Field(min_length=1, max_length=96)
    slot_id: str | None = Field(default=None, pattern=r"^p[1-4]$")
    allowed_fact_ids: tuple[str, ...] = ()
    required_dimension_ids: tuple[str, ...] = ()
    allowed_constraint_ids: tuple[str, ...] = ()
    copy_max_chars: int = Field(ge=1, le=400)
    advisor_reason_required: bool = False

    @field_validator(
        "allowed_fact_ids",
        "required_dimension_ids",
        "allowed_constraint_ids",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        expected_content_source = (
            "approved_facts"
            if self.kind in {"product", "judgement", "answer"}
            else "constraints_only"
        )
        if self.content_source != expected_content_source:
            raise ValueError(
                "writer section kind has incompatible content source"
            )
        if (
            self.content_source == "constraints_only"
            and self.allowed_fact_ids
        ):
            raise ValueError(
                "constraints-only writer section forbids fact IDs"
            )
        if self.kind == "product":
            if self.slot_id is None or not self.advisor_reason_required:
                raise ValueError(
                    "product writer spec requires slot and advisor"
                )
        elif self.kind in {"judgement", "answer"}:
            if self.slot_id is None or self.advisor_reason_required:
                raise ValueError(
                    "bound writer spec requires slot without advisor"
                )
        elif self.slot_id is not None or self.advisor_reason_required:
            raise ValueError(
                "non-product writer spec forbids slot and advisor"
            )
        for values, label in (
            (self.allowed_fact_ids, "writer allowed fact IDs"),
            (
                self.required_dimension_ids,
                "writer required dimension IDs",
            ),
            (
                self.allowed_constraint_ids,
                "writer allowed constraint IDs",
            ),
        ):
            _require_unique(values, label=label)
        return self


class CopywriterDraft(_StrictFrozen):
    mode: PresentationMode
    sections: tuple[CopywriterSection, ...] = ()
    summary_copy: SourceTaggedCopy | None = None
    product_copy: tuple[ProductCopy, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    closing_copy: SourceTaggedCopy | None = None

    @field_validator("sections", "product_copy", mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.summary_copy is None:
            if (
                self.product_copy
                or self.closing_copy is not None
            ):
                raise ValueError(
                    "section draft forbids legacy copy fields"
                )
            keys = tuple(
                (section.kind, section.slot_id)
                for section in self.sections
            )
            _require_unique(keys, label="copywriter section identities")
            return self
        if self.sections:
            raise ValueError("legacy draft forbids section copy fields")
        slot_ids = tuple(item.slot_id for item in self.product_copy)
        _require_unique(slot_ids, label="copywriter product slot IDs")
        return self


def build_copywriter_section_specs(
    packet: PresentationPacket,
) -> tuple[CopywriterSectionSpec, ...]:
    if not isinstance(packet, PresentationPacket):
        raise TypeError("packet must be PresentationPacket")
    responsibility = packet.responsibility
    if responsibility is None:
        raise ValueError("presentation packet requires responsibility")
    if packet.mode in {"clarification", "error", "image_identity"}:
        return ()
    slot_by_id = {slot.slot_id: slot for slot in packet.slots}
    constraints = tuple(
        item.constraint_id for item in packet.approved_constraints
    )
    specs: list[CopywriterSectionSpec] = []
    for section in packet.section_order:
        item = _writer_spec_for_section(
            packet=packet,
            section=section,
            slot_by_id=slot_by_id,
            constraint_ids=constraints,
        )
        if item is not None:
            specs.append(item)
    return tuple(specs)


def _writer_spec_for_section(
    *,
    packet: PresentationPacket,
    section: PresentationSectionSpec,
    slot_by_id: dict[str, CopySlot],
    constraint_ids: tuple[str, ...],
) -> CopywriterSectionSpec | None:
    responsibility = packet.responsibility
    if responsibility is None:
        raise AssertionError("presentation packet requires responsibility")
    budget = packet.copy_budget
    if section.kind == "summary":
        if responsibility is Responsibility.PRODUCT_KNOWLEDGE:
            return None
        location = {
            Responsibility.RECOMMENDATION: "recommendation.summary",
            Responsibility.COMPARISON: "comparison.summary",
            Responsibility.SINGLE_PRODUCT_SUITABILITY: (
                "single_product_suitability.summary"
            ),
            Responsibility.CONSULTATION: "consultation.summary",
            Responsibility.SAFETY_ESCALATION: (
                "safety_escalation.summary"
            ),
        }.get(responsibility)
        if location is None:
            return None
        return CopywriterSectionSpec(
            kind="summary",
            content_source="constraints_only",
            evidence_location=location,
            required_dimension_ids=packet.requested_dimensions,
            allowed_constraint_ids=constraint_ids,
            copy_max_chars=budget.summary_max_chars,
        )
    if section.kind == "product":
        if section.slot_id is None:
            raise ValueError("product section requires slot")
        slot = slot_by_id[section.slot_id]
        return CopywriterSectionSpec(
            kind="product",
            content_source="approved_facts",
            evidence_location="recommendation.product",
            slot_id=slot.slot_id,
            allowed_fact_ids=_generic_slot_fact_ids(slot),
            required_dimension_ids=packet.requested_dimensions,
            allowed_constraint_ids=constraint_ids,
            copy_max_chars=budget.positioning_max_chars,
            advisor_reason_required=True,
        )
    if section.kind == "judgement":
        if not packet.slots:
            raise ValueError("judgement writer section requires slot")
        return CopywriterSectionSpec(
            kind="judgement",
            content_source="approved_facts",
            evidence_location="single_product_suitability.judgement",
            slot_id=packet.slots[0].slot_id,
            allowed_fact_ids=_slot_fact_ids(packet.slots[0]),
            required_dimension_ids=packet.requested_dimensions,
            allowed_constraint_ids=constraint_ids,
            copy_max_chars=budget.advisor_reason_max_chars,
        )
    if section.kind == "answer":
        if not packet.slots:
            raise ValueError("answer writer section requires slot")
        return CopywriterSectionSpec(
            kind="answer",
            content_source="approved_facts",
            evidence_location="product_knowledge.answer",
            slot_id=packet.slots[0].slot_id,
            allowed_fact_ids=_slot_fact_ids(packet.slots[0]),
            required_dimension_ids=packet.requested_dimensions,
            allowed_constraint_ids=constraint_ids,
            copy_max_chars=budget.positioning_max_chars,
        )
    if section.kind == "general_knowledge":
        return CopywriterSectionSpec(
            kind="general_knowledge",
            content_source="constraints_only",
            evidence_location="general_knowledge.body",
            required_dimension_ids=packet.requested_dimensions,
            allowed_constraint_ids=constraint_ids,
            copy_max_chars=budget.summary_max_chars,
        )
    if section.kind == "closing":
        return CopywriterSectionSpec(
            kind="closing",
            content_source="constraints_only",
            evidence_location="recommendation.closing",
            required_dimension_ids=packet.requested_dimensions,
            allowed_constraint_ids=constraint_ids,
            copy_max_chars=budget.closing_max_chars,
        )
    return None


def _slot_fact_ids(slot: CopySlot) -> tuple[str, ...]:
    return tuple(fact.fact_id for fact in slot.approved_soft_facts)


def _generic_slot_fact_ids(slot: CopySlot) -> tuple[str, ...]:
    return tuple(
        fact.fact_id
        for fact in slot.approved_soft_facts
        if fact.generic_copy_allowed
    )


class DirectFactComponent(_StrictFrozen):
    fact_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=64)
    display_value: str = Field(min_length=1, max_length=512)


class PresentationSection(_StrictFrozen):
    kind: SectionKind
    copy_text: str | None = Field(default=None, max_length=1200)
    used_fact_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    used_constraint_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    advisor_reason: str | None = Field(default=None, max_length=400)
    advisor_used_fact_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    advisor_used_constraint_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    slot_id: str | None = Field(default=None, pattern=r"^p[1-4]$")
    product_id: int | None = Field(default=None, gt=0)
    direct_facts: tuple[DirectFactComponent, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )

    @field_validator(
        "direct_facts",
        "used_fact_ids",
        "used_constraint_ids",
        "advisor_used_fact_ids",
        "advisor_used_constraint_ids",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return _tuple(value)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.copy_text is not None:
            validate_public_text(self.copy_text)
        if self.advisor_reason is not None:
            validate_public_text(self.advisor_reason)
        for values, label in (
            (self.used_fact_ids, "section fact IDs"),
            (self.used_constraint_ids, "section constraint IDs"),
            (self.advisor_used_fact_ids, "advisor fact IDs"),
            (
                self.advisor_used_constraint_ids,
                "advisor constraint IDs",
            ),
        ):
            _require_unique(values, label=label)
        if self.copy_text is None and (
            self.used_fact_ids or self.used_constraint_ids
        ):
            raise ValueError(
                "copy evidence IDs require section copy"
            )
        if self.advisor_reason is None and (
            self.advisor_used_fact_ids
            or self.advisor_used_constraint_ids
        ):
            raise ValueError(
                "advisor evidence IDs require advisor copy"
            )
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
            "judgement",
            "answer",
            "general_knowledge",
            "question",
            "observation",
            "error",
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
    copy_source: CopySource
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
        validate_copy_provenance(
            copy_source=self.copy_source,
            fallback_reason=self.telemetry.fallback_reason,
        )
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
    "ApprovedConstraint",
    "ApprovedSoftFact",
    "ClarificationPresentationData",
    "CompactTagEvidence",
    "ComparisonDimensionEvidence",
    "ComparisonPresentationData",
    "ConsultationPresentationData",
    "CopySource",
    "CopywriterPolicy",
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
    "SourceTaggedCopy",
    "deterministic_copy_source",
    "successful_copy_provenance",
    "validate_copy_provenance",
]
