from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.focus_state import FocusState
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.session_profile import SessionProfile
from app.guide.session_contract import SessionId
from app.guide.understanding.semantic_contracts import ClarificationCode


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConversationVersionRef(_StrictContract):
    session_id: SessionId
    conversation_version: int = Field(ge=0)


class FeedbackEventRef(_StrictContract):
    event_id: str
    conversation_version: ConversationVersionRef


StoredExclusion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
    ),
]

EvidenceId = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


class StoredFacet(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: str = Field(min_length=1, max_length=512)


class StoredConcept(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    concept_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$"
    )
    polarity: Literal["prefer", "avoid"]

    @model_validator(mode="after")
    def validate_field_scope(self) -> Self:
        if not self.concept_id.startswith(f"{self.field_key}."):
            raise ValueError("stored concept must be field-scoped")
        return self


class RecommendationQueryContext(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    category: Literal[
        "sunscreen",
        "serum",
        "skincare",
        "base_makeup",
        "color_makeup",
        "cleanser",
        "fragrance",
    ]
    budget_minimum: Decimal | None = None
    budget_maximum: Decimal | None = None
    skin: Literal[
        "oily_sensitive",
        "oily",
        "dry",
        "combination",
        "sensitive",
        "normal",
    ] | None = None
    efficacy: Literal[
        "hydration",
        "soothing",
        "repair",
        "anti_aging",
        "brightening",
        "oil_control",
        "acne_care",
    ] | None = None
    exclusions: tuple[StoredExclusion, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    facets: tuple[StoredFacet, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    concepts: tuple[StoredConcept, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    similarity_anchor_product_id: int | None = Field(
        default=None,
        gt=0,
    )
    inclusions: tuple[StoredExclusion, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    safety_sensitive: bool = False

    @field_validator(
        "exclusions",
        "facets",
        "concepts",
        "inclusions",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        bounds = [
            value
            for value in (
                self.budget_minimum,
                self.budget_maximum,
            )
            if value is not None
        ]
        if any(not value.is_finite() or value <= 0 for value in bounds):
            raise ValueError(
                "budget bounds must be positive and finite"
            )
        if (
            self.budget_minimum is not None
            and self.budget_maximum is not None
            and self.budget_minimum > self.budget_maximum
        ):
            raise ValueError("budget minimum exceeds maximum")
        if len(self.exclusions) != len(set(self.exclusions)):
            raise ValueError("exclusions must be unique")
        if len(self.inclusions) != len(set(self.inclusions)):
            raise ValueError("inclusions must be unique")
        facet_keys = tuple(
            (item.field_key, item.value.casefold())
            for item in self.facets
        )
        if len(facet_keys) != len(set(facet_keys)):
            raise ValueError("facets must be unique")
        concept_keys = tuple(
            (
                item.field_key,
                item.concept_id,
                item.polarity,
            )
            for item in self.concepts
        )
        if len(concept_keys) != len(set(concept_keys)):
            raise ValueError("concepts must be unique")
        return self


class DisplayedCandidateRef(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    product_id: int
    ordinal: int = Field(ge=1, le=4)
    skin_match: Literal["matched", "unknown", "not_applicable"]
    matched_efficacies: tuple[str, ...]

    @field_validator("matched_efficacies", mode="before")
    @classmethod
    def freeze_matched_efficacies(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class ClarificationProgress(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    gap: ClarificationCode
    attempts: int = Field(ge=1, le=2)


class PendingBudgetRange(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    minimum: Decimal
    maximum: Decimal

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if (
            not self.minimum.is_finite()
            or not self.maximum.is_finite()
            or self.minimum <= 0
            or self.maximum <= 0
        ):
            raise ValueError(
                "pending budget bounds must be positive and finite"
            )
        if self.minimum > self.maximum:
            raise ValueError(
                "pending budget minimum exceeds maximum"
            )
        return self


class PendingRecommendationContext(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    category: Literal[
        "sunscreen",
        "serum",
        "skincare",
        "base_makeup",
        "color_makeup",
        "cleanser",
        "fragrance",
    ]
    skin: Literal[
        "oily_sensitive",
        "oily",
        "dry",
        "combination",
        "sensitive",
        "normal",
    ] | None = None
    efficacy: Literal[
        "hydration",
        "soothing",
        "repair",
        "anti_aging",
        "brightening",
        "oil_control",
        "acne_care",
    ] | None = None
    exclusions: tuple[StoredExclusion, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    inclusions: tuple[StoredExclusion, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    facets: tuple[StoredFacet, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    concepts: tuple[StoredConcept, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    safety_sensitive: bool = False

    @field_validator(
        "exclusions",
        "inclusions",
        "facets",
        "concepts",
        mode="before",
    )
    @classmethod
    def freeze_pending_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if len(self.exclusions) != len(set(self.exclusions)):
            raise ValueError("pending exclusions must be unique")
        if len(self.inclusions) != len(set(self.inclusions)):
            raise ValueError("pending inclusions must be unique")
        facet_keys = tuple(
            (item.field_key, item.value.casefold())
            for item in self.facets
        )
        if len(facet_keys) != len(set(facet_keys)):
            raise ValueError("pending facets must be unique")
        concept_keys = tuple(
            (
                item.field_key,
                item.concept_id,
                item.polarity,
            )
            for item in self.concepts
        )
        if len(concept_keys) != len(set(concept_keys)):
            raise ValueError("pending concepts must be unique")
        return self


class PendingTurn(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    kind: Literal["clarification"] = "clarification"
    gap: ClarificationCode
    attempts: int = Field(ge=1, le=2)
    source_conversation_version: int = Field(ge=0)
    source_message: str = Field(min_length=1, max_length=4000)
    expected_response: Literal[
        "confirm_or_correct",
        "supply_value",
    ]
    resume_mode: Literal["recommendation"]
    resume_context: PendingRecommendationContext
    proposed_budget: PendingBudgetRange | None = None

    @model_validator(mode="after")
    def validate_payload_for_gap(self) -> Self:
        if self.gap is ClarificationCode.BUDGET:
            if (
                self.expected_response == "confirm_or_correct"
                and self.proposed_budget is None
            ):
                raise ValueError(
                    "budget gap requires a proposed budget"
                )
            if (
                self.expected_response == "supply_value"
                and self.proposed_budget is not None
            ):
                raise ValueError(
                    "budget supply-value state forbids a proposal"
                )
        elif self.proposed_budget is not None:
            raise ValueError(
                "non-budget gap forbids a proposed budget"
            )
        return self


class ConversationSnapshot(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    session_id: SessionId
    version: int = Field(ge=1)
    profile_owner: ProfileOwnerRef | None = None
    session_profile: SessionProfile | None = None
    focus_state: FocusState | None = None
    has_image_delivery: bool = False
    query_context: RecommendationQueryContext | None = None
    empty_result: bool = False
    candidates: tuple[DisplayedCandidateRef, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    focused_candidate_ordinal: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )
    focused_evidence_ids: tuple[EvidenceId, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    focused_general_knowledge_ids: tuple[EvidenceId, ...] = Field(
        default_factory=tuple,
        max_length=5,
    )
    last_general_knowledge_question: str | None = Field(
        default=None,
        min_length=1,
        max_length=4000,
    )
    consultation: ConsultationSubstate | None = None
    clarification: ClarificationProgress | None = None
    pending_turn: PendingTurn | None = None

    @field_validator("candidates", mode="before")
    @classmethod
    def freeze_candidates(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator(
        "focused_evidence_ids",
        "focused_general_knowledge_ids",
        mode="before",
    )
    @classmethod
    def freeze_focused_evidence_ids(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_candidates(self) -> Self:
        has_query_context = self.query_context is not None
        has_candidates = bool(self.candidates)
        if has_candidates and not has_query_context:
            raise ValueError(
                "recommendation query_context and candidates "
                "must be stored together"
            )
        if self.empty_result:
            if not has_query_context or has_candidates:
                raise ValueError(
                    "empty result requires query context and no candidates"
                )
        elif has_query_context and not has_candidates:
            raise ValueError(
                "query context without candidates requires empty_result"
            )
        if (
            not has_candidates
            and not self.empty_result
            and self.consultation is None
            and not self.has_image_delivery
            and self.clarification is None
            and self.pending_turn is None
            and self.last_general_knowledge_question is None
            and self.session_profile is None
            and self.focus_state is None
        ):
            raise ValueError(
                "snapshot requires recommendation, consultation, "
                "image delivery, clarification, knowledge, or profile state"
            )
        if (
            self.pending_turn is not None
            and self.pending_turn.source_conversation_version
            >= self.version
        ):
            raise ValueError(
                "pending turn source version must precede snapshot version"
            )
        if (
            self.pending_turn is not None
            and self.clarification is not None
            and (
                self.pending_turn.gap is not self.clarification.gap
                or self.pending_turn.attempts
                != self.clarification.attempts
            )
        ):
            raise ValueError(
                "pending turn and clarification progress must agree"
            )
        ordinals = [item.ordinal for item in self.candidates]
        if ordinals != list(range(1, len(self.candidates) + 1)):
            raise ValueError("candidate ordinal must be contiguous")
        product_ids = [item.product_id for item in self.candidates]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("candidate product_id must be unique")
        if len(self.focused_evidence_ids) != len(
            set(self.focused_evidence_ids)
        ):
            raise ValueError("focused evidence IDs must be unique")
        if self.focused_general_knowledge_ids != tuple(
            sorted(set(self.focused_general_knowledge_ids))
        ):
            raise ValueError(
                "general knowledge IDs must be sorted and unique"
            )
        if (
            self.focused_general_knowledge_ids
            and self.last_general_knowledge_question is None
        ):
            raise ValueError(
                "general knowledge focus requires prior question"
            )
        if (
            self.focused_candidate_ordinal is not None
            and self.focused_candidate_ordinal > len(self.candidates)
        ):
            raise ValueError(
                "focused candidate ordinal must reference a visible candidate"
            )
        if (
            self.focus_state is not None
            and self.focus_state.current_product_id is not None
        ):
            focused_product_ids = {
                item.product_id for item in self.candidates
            } | {
                item.product_id
                for item in self.focus_state.confirmed_image_products
            }
            if (
                self.focus_state.current_product_id
                not in focused_product_ids
            ):
                raise ValueError(
                    "focus current product must reference a visible "
                    "candidate or confirmed image"
                )
        return self
