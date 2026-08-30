from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.guide.session_contract import SessionId
from app.guide.understanding.knowledge_relation_contracts import (
    KnowledgeRelationIntent,
)
from app.guide.understanding.turn_meaning_contracts import (
    EXPLORE_RECOMMENDATION_BASES,
    FIT_RECOMMENDATION_BASES,
    RecommendationMode,
    RecommendationModeBasis,
)


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TopicCode(str, Enum):
    SUNSCREEN = "sunscreen"
    SERUM = "serum"
    SKINCARE = "skincare"
    BASE_MAKEUP = "base_makeup"
    COLOR_MAKEUP = "color_makeup"
    CLEANSER = "cleanser"
    FRAGRANCE = "fragrance"


class UnderstandingGoal(str, Enum):
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    SUITABILITY = "suitability"
    IMAGE_IDENTITY = "image_identity"
    IMAGE_SIMILARITY = "image_similarity"
    KNOWLEDGE = "knowledge"
    ASSESSMENT = "assessment"
    FOLLOWUP = "followup"
    CLARIFICATION = "clarification"


class EfficacyTarget(str, Enum):
    HYDRATION = "hydration"
    SOOTHING = "soothing"
    REPAIR = "repair"
    ANTI_AGING = "anti_aging"
    BRIGHTENING = "brightening"
    OIL_CONTROL = "oil_control"
    ACNE_CARE = "acne_care"


class FollowupAction(str, Enum):
    ORDINAL_REFERENCE = "ordinal_reference"
    CHEAPEST = "cheapest"


class ExactRevisionOperation(str, Enum):
    REVISE_CONSTRAINT = "revise_constraint"
    WITHDRAW_CONSTRAINT = "withdraw_constraint"


class ExactRevisionTarget(str, Enum):
    BUDGET = "budget"
    CATEGORY = "category"
    SKIN = "skin"
    INGREDIENT_EXCLUSION = "ingredient_exclusion"
    INGREDIENT_INCLUSION = "ingredient_inclusion"
    FACET = "facet"
    EFFICACY = "efficacy"


class SkinTarget(str, Enum):
    OILY_SENSITIVE = "oily_sensitive"
    OILY = "oily"
    DRY = "dry"
    COMBINATION = "combination"
    SENSITIVE = "sensitive"
    NORMAL = "normal"


class BudgetDraft(_StrictContract):
    kind: Literal["budget"] = "budget"
    minimum: Decimal | None = None
    maximum: Decimal | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.minimum is None and self.maximum is None:
            raise ValueError("budget draft requires a bound")
        values = [
            value
            for value in (self.minimum, self.maximum)
            if value is not None
        ]
        if any(not value.is_finite() or value <= 0 for value in values):
            raise ValueError("budget draft bounds must be positive")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("budget draft minimum exceeds maximum")
        return self


class BudgetRevisionDraft(_StrictContract):
    maximum: Decimal | None = None
    issue: Literal[
        "invalid_budget",
        "unsupported_budget_revision",
    ] | None = None

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        if self.issue is not None:
            if self.maximum is not None:
                raise ValueError(
                    "budget revision issue forbids maximum"
                )
            return self
        if self.maximum is None:
            raise ValueError(
                "budget revision requires maximum or issue"
            )
        if not self.maximum.is_finite() or self.maximum <= 0:
            raise ValueError(
                "budget revision maximum must be positive"
            )
        return self


class SkinRevisionDraft(_StrictContract):
    target: SkinTarget | None = None
    issue: Literal[
        "unsupported_skin_revision",
        "compound_revision",
    ] | None = None

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        if self.target is not None and self.issue is not None:
            raise ValueError("skin revision issue forbids target")
        return self


class CategoryDraft(_StrictContract):
    kind: Literal["category"] = "category"
    value: TopicCode


class SkinDraft(_StrictContract):
    kind: Literal["skin"] = "skin"
    value: SkinTarget


class ExclusionDraft(_StrictContract):
    kind: Literal["exclude"] = "exclude"
    value: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]


class InclusionDraft(_StrictContract):
    kind: Literal["include"] = "include"
    field_key: Literal[
        "ingredients_present"
    ] = "ingredients_present"
    value: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]


class PreferenceDraft(_StrictContract):
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ]
    preference_kind: Literal[
        "legacy_facet",
        "concept",
        "free_descriptor",
    ] = "legacy_facet"
    concept_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$",
    )
    polarity: Literal["prefer", "avoid"] = "prefer"

    @model_validator(mode="after")
    def validate_preference_kind(self) -> Self:
        if self.preference_kind == "concept":
            if self.concept_id is None:
                raise ValueError(
                    "concept preference requires concept_id"
                )
            if not self.concept_id.startswith(f"{self.field_key}."):
                raise ValueError(
                    "concept preference must be field-scoped"
                )
            return self
        if self.concept_id is not None:
            raise ValueError(
                "non-concept preference forbids concept_id"
            )
        if (
            self.preference_kind == "legacy_facet"
            and self.polarity != "prefer"
        ):
            raise ValueError(
                "legacy facet preference supports prefer polarity only"
            )
        return self


class EfficacyDraft(_StrictContract):
    kind: Literal["efficacy"] = "efficacy"
    value: EfficacyTarget


class SourceSpan(_StrictContract):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.end <= self.start:
            raise ValueError("source span end must exceed start")
        return self


class ExactRevisionConfirmation(_StrictContract):
    operation: ExactRevisionOperation
    target: ExactRevisionTarget
    source_span: SourceSpan
    affected_value: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    affected_field_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}$",
    )

    @model_validator(mode="after")
    def validate_affected_field(self) -> Self:
        if (
            self.affected_field_key is not None
            and self.target is not ExactRevisionTarget.FACET
        ):
            raise ValueError(
                "affected_field_key is reserved for facet proofs"
            )
        return self


class ReferenceDraft(_StrictContract):
    kind: Literal[
        "candidate_ordinal",
        "image_ordinal",
        "current_item",
        "current_batch",
        "current_topic",
        "previous_constraint",
    ]
    ordinal: int | None = Field(default=None, ge=1, le=9)
    source_span: SourceSpan | None = None

    @model_validator(mode="after")
    def validate_kind_and_ordinal(self) -> Self:
        if self.kind in {"candidate_ordinal", "image_ordinal"}:
            if self.ordinal is None:
                raise ValueError(f"{self.kind} requires ordinal")
        elif self.ordinal is not None:
            raise ValueError(f"{self.kind} forbids ordinal")
        return self


class RelativeDraft(_StrictContract):
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    concept_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$",
    )
    direction: Literal["higher", "lower"]
    raw_text: str = Field(min_length=1, max_length=160)
    baseline: ReferenceDraft

    @model_validator(mode="after")
    def validate_concept_scope(self) -> Self:
        if (
            self.concept_id is not None
            and not self.concept_id.startswith(f"{self.field_key}.")
        ):
            raise ValueError("relative concept must be field-scoped")
        return self


class ProductMentionDraft(_StrictContract):
    text: str = Field(min_length=1, max_length=160)
    source_span: SourceSpan


class FollowupDraft(_StrictContract):
    action: FollowupAction | None = None
    ordinal: int | None = Field(default=None, ge=1, le=9)
    issue: Literal["unsupported_followup"] | None = None
    source_span: SourceSpan | None = None

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.issue is not None:
            if (
                self.action is not None
                or self.ordinal is not None
                or self.source_span is not None
            ):
                raise ValueError("followup issue forbids action")
            return self
        if self.source_span is None:
            raise ValueError("followup action requires full source span")
        if self.action is FollowupAction.ORDINAL_REFERENCE:
            if self.ordinal is None:
                raise ValueError("ordinal reference requires ordinal")
            return self
        if self.action is FollowupAction.CHEAPEST:
            if self.ordinal is not None:
                raise ValueError("cheapest forbids ordinal")
            return self
        raise ValueError("followup draft requires action or issue")


ExactConstraintDraft = Annotated[
    BudgetDraft
    | CategoryDraft
    | SkinDraft
    | ExclusionDraft
    | InclusionDraft
    | EfficacyDraft
    | ReferenceDraft,
    Field(discriminator="kind"),
]


ContextConstraintDraft = Annotated[
    BudgetDraft
    | SkinDraft
    | ExclusionDraft
    | EfficacyDraft,
    Field(discriminator="kind"),
]


class ContextConstraintSignal(_StrictContract):
    source: Literal["session", "profile"]
    constraint: ContextConstraintDraft


class UnderstandingIssue(_StrictContract):
    code: Literal[
        "invalid_budget",
        "unsupported_budget_format",
        "unsupported_attribute_exclusion",
        "unverified_safety_requirement",
        "ambiguous_category",
        "ambiguous_reference",
        "ambiguous_candidate_reference",
        "ambiguous_image_reference",
        "too_many_candidate_references",
        "too_many_image_references",
        "missing_revision_target",
        "ambiguous_revision_target",
        "confirm_hard_constraint_revision",
        "missing_category",
    ]
    detail: str


class SignalTrace(_StrictContract):
    field: str
    exact_value: str | None
    semantic_value: str | None
    resolution: Literal[
        "agree",
        "exact_wins",
        "semantic_fills",
        "context_fills",
        "clarify",
        "ignored_stale",
        "semantic_unavailable",
        "semantic_skipped_by_contract",
    ]


class ConstraintChangeDraft(_StrictContract):
    parent_concept: Literal[
        "ingredient_exclusion",
        "efficacy",
        "skin",
    ]
    requested_change: Literal["remove", "replace"]
    value: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ] | None = None
    source_span: SourceSpan

    @model_validator(mode="after")
    def validate_parent_change(self) -> Self:
        if (
            self.parent_concept == "ingredient_exclusion"
            and self.requested_change != "remove"
        ):
            raise ValueError(
                "ingredient exclusion supports remove only"
            )
        if (
            self.parent_concept == "skin"
            and self.requested_change == "remove"
        ):
            if self.value is not None:
                raise ValueError(
                    "skin removal requires a bare parent target"
                )
            return self
        if self.value is None:
            raise ValueError(
                "constraint change requires a normalized value"
            )
        return self


class StructuredUnderstanding(_StrictContract):
    goal: UnderstandingGoal = UnderstandingGoal.RECOMMENDATION
    recommendation_mode: RecommendationMode | None = None
    recommendation_mode_basis: RecommendationModeBasis | None = None
    recommendation_count: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )
    topic: TopicCode | None
    observations: list[str]
    exact_constraints: list[ExactConstraintDraft]
    preference_drafts: list[PreferenceDraft] = Field(default_factory=list)
    constraint_changes: list[ConstraintChangeDraft] = Field(
        default_factory=list,
        max_length=4,
    )
    relative_drafts: list[RelativeDraft] = Field(
        default_factory=list,
        max_length=4,
    )
    semantic_proposals: list[str]
    signal_trace: list[SignalTrace] = Field(default_factory=list)
    references: list[ReferenceDraft] = Field(default_factory=list)
    product_mentions: list[ProductMentionDraft] = Field(
        default_factory=list,
        max_length=4,
    )
    image_references: list[str]
    uncertainties: list[UnderstandingIssue]
    confidence: float = Field(ge=0.0, le=1.0)
    semantic_authoritative: bool = False
    question_meaning: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    knowledge_relation_hints: tuple[
        KnowledgeRelationIntent, ...
    ] = Field(
        default_factory=tuple,
        max_length=8,
    )
    safety_sensitive: bool = False

    @field_validator("knowledge_relation_hints", mode="before")
    @classmethod
    def freeze_knowledge_relation_hints(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_exact_references_are_projected(self) -> Self:
        exact_references = [
            item
            for item in self.exact_constraints
            if isinstance(item, ReferenceDraft)
        ]
        if any(
            reference not in self.references
            for reference in exact_references
        ):
            raise ValueError(
                "exact references must remain in typed references"
            )
        recommendation_goal = self.goal in {
            UnderstandingGoal.RECOMMENDATION,
            UnderstandingGoal.IMAGE_SIMILARITY,
        }
        has_recommendation_outcome = any(
            value is not None
            for value in (
                self.recommendation_mode,
                self.recommendation_mode_basis,
                self.recommendation_count,
            )
        )
        if (
            self.goal is not UnderstandingGoal.CLARIFICATION
            and not recommendation_goal
            and has_recommendation_outcome
        ):
            raise ValueError(
                "non-recommendation forbids recommendation outcome"
            )
        if (
            self.recommendation_mode is None
            and (
                self.recommendation_mode_basis is not None
                or self.recommendation_count is not None
            )
        ):
            raise ValueError(
                "recommendation count requires recommendation mode"
            )
        if (
            self.recommendation_mode == "fit"
            and (
                self.recommendation_count != 1
                or self.recommendation_mode_basis
                not in FIT_RECOMMENDATION_BASES
            )
        ):
            if self.recommendation_count != 1:
                raise ValueError(
                    "fit recommendation requires one result"
                )
            raise ValueError(
                "recommendation mode basis must be parent-scoped"
            )
        if (
            self.recommendation_mode == "explore"
            and (
                self.recommendation_count == 1
                or self.recommendation_mode_basis
                not in EXPLORE_RECOMMENDATION_BASES
            )
        ):
            if self.recommendation_count == 1:
                raise ValueError(
                    "explore recommendation requires multiple results"
                )
            raise ValueError(
                "recommendation mode basis must be parent-scoped"
            )
        if len(self.knowledge_relation_hints) != len(
            set(self.knowledge_relation_hints)
        ):
            raise ValueError(
                "knowledge relation hints must be ordered unique"
            )
        if (
            self.knowledge_relation_hints
            and self.goal
            not in {UnderstandingGoal.KNOWLEDGE, UnderstandingGoal.FOLLOWUP}
        ):
            raise ValueError(
                "knowledge relation hints require knowledge or followup"
            )
        return self

    @field_validator("goal", mode="before")
    @classmethod
    def normalize_legacy_goal(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> object:
        if value == "recommend":
            return UnderstandingGoal.RECOMMENDATION
        if info.mode == "json" and value == "recommendation":
            return UnderstandingGoal.RECOMMENDATION
        return value


OpaqueImageId = Annotated[
    str,
    StringConstraints(
        min_length=38,
        max_length=159,
        pattern=r"^image_[A-Za-z0-9_-]{32,152}$",
    ),
]
OpaqueBundleId = Annotated[
    str,
    StringConstraints(
        min_length=39,
        max_length=160,
        pattern=r"^bundle_[A-Za-z0-9_-]{32,152}$",
    ),
]
OwnerTokenSha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
ContentSha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


class ImageObservation(_StrictContract):
    image_id: OpaqueImageId
    ordinal: int = Field(ge=1, le=4)
    content_sha256: ContentSha256
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    image_format: Literal["JPEG", "PNG", "WEBP"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_size: int = Field(gt=0, le=8 * 1024 * 1024)

    @model_validator(mode="after")
    def validate_pixel_limit(self) -> Self:
        if self.width * self.height > 20_000_000:
            raise ValueError("image dimensions exceed pixel limit")
        return self


class ImageBundle(_StrictContract):
    bundle_id: OpaqueBundleId
    session_id: SessionId
    owner_token_sha256: OwnerTokenSha256
    version: int = Field(ge=1)
    created_at: datetime
    expires_at: datetime
    images: list[ImageObservation] = Field(min_length=1, max_length=4)
    focused_image_ordinal: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )

    @model_validator(mode="after")
    def validate_state_and_image_order(self) -> Self:
        if (
            self.created_at.utcoffset() is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError(
                "created_at and expires_at must be timezone-aware"
            )
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")

        image_ids = [image.image_id for image in self.images]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("image_id must be unique within an image bundle")

        ordinals = [image.ordinal for image in self.images]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("ordinal must be unique within an image bundle")

        expected_ordinals = list(range(1, len(self.images) + 1))
        if ordinals != expected_ordinals:
            raise ValueError(
                "ordinal must be contiguous from 1 and match upload order"
            )
        if (
            self.focused_image_ordinal is not None
            and self.focused_image_ordinal > len(self.images)
        ):
            raise ValueError(
                "focused image ordinal must reference a bundled image"
            )

        return self
