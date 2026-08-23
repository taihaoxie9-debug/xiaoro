from decimal import Decimal
from copy import deepcopy
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.guide.understanding.turn_meaning_contracts import (
    EXPLORE_RECOMMENDATION_BASES,
    FIT_RECOMMENDATION_BASES,
    RecommendationMode,
    RecommendationModeBasis,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.session_profile import SessionProfile
from app.guide.intent.responsibility_matrix import Responsibility
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
    recommendation_mode: RecommendationMode = "explore"
    recommendation_mode_basis: RecommendationModeBasis
    recommendation_count: int = Field(default=3, ge=1, le=4)
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
    def validate_recommendation_outcome(self) -> Self:
        if (
            self.recommendation_mode_basis is not None
            and (
                (
                    self.recommendation_mode == "fit"
                    and self.recommendation_mode_basis
                    not in FIT_RECOMMENDATION_BASES
                )
                or (
                    self.recommendation_mode == "explore"
                    and self.recommendation_mode_basis
                    not in EXPLORE_RECOMMENDATION_BASES
                )
            )
        ):
            raise ValueError(
                "recommendation context basis must be parent-scoped"
            )
        if (
            self.recommendation_mode == "fit"
            and self.recommendation_count != 1
        ):
            raise ValueError(
                "fit recommendation context requires one result"
            )
        if (
            self.recommendation_mode == "explore"
            and self.recommendation_count not in {2, 3, 4}
        ):
            raise ValueError(
                "explore recommendation context requires multiple results"
            )
        return self

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

    minimum: Decimal | None = None
    maximum: Decimal | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        bounds = [
            value
            for value in (self.minimum, self.maximum)
            if value is not None
        ]
        if not bounds:
            raise ValueError(
                "pending budget requires at least one bound"
            )
        if any(
            not value.is_finite() or value <= 0
            for value in bounds
        ):
            raise ValueError(
                "pending budget bounds must be positive and finite"
            )
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
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
    recommendation_mode: RecommendationMode = "explore"
    recommendation_mode_basis: RecommendationModeBasis
    recommendation_count: int = Field(default=3, ge=1, le=4)
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
        if (
            self.recommendation_mode_basis is not None
            and (
                (
                    self.recommendation_mode == "fit"
                    and self.recommendation_mode_basis
                    not in FIT_RECOMMENDATION_BASES
                )
                or (
                    self.recommendation_mode == "explore"
                    and self.recommendation_mode_basis
                    not in EXPLORE_RECOMMENDATION_BASES
                )
            )
        ):
            raise ValueError(
                "pending recommendation basis must be parent-scoped"
            )
        if (
            self.recommendation_mode == "fit"
            and self.recommendation_count != 1
        ):
            raise ValueError(
                "fit pending context requires one result"
            )
        if (
            self.recommendation_mode == "explore"
            and self.recommendation_count not in {2, 3, 4}
        ):
            raise ValueError(
                "explore pending context requires multiple results"
            )
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


class _StrictFrozenState(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )


class RecommendationSlotState(_StrictFrozenState):
    kind: Literal["recommendation"] = "recommendation"
    query_context: RecommendationQueryContext
    candidates: tuple[DisplayedCandidateRef, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    empty_result: bool = False
    focused_candidate_ordinal: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )

    @field_validator("candidates", mode="before")
    @classmethod
    def freeze_candidates(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_recommendation_slot(self) -> Self:
        if self.empty_result == bool(self.candidates):
            raise ValueError(
                "recommendation slot requires candidates xor empty result"
            )
        ordinals = tuple(item.ordinal for item in self.candidates)
        if ordinals != tuple(range(1, len(self.candidates) + 1)):
            raise ValueError("candidate ordinal must be contiguous")
        product_ids = tuple(
            item.product_id for item in self.candidates
        )
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("candidate product_id must be unique")
        if (
            self.focused_candidate_ordinal is not None
            and self.focused_candidate_ordinal > len(self.candidates)
        ):
            raise ValueError(
                "focused candidate ordinal must reference a candidate"
            )
        return self


class ProductSlotState(_StrictFrozenState):
    kind: Literal["product"] = "product"
    products: tuple[DisplayedCandidateRef, ...] = Field(
        min_length=1,
        max_length=3,
    )
    focused_product_id: int | None = Field(default=None, gt=0)
    focused_evidence_ids: tuple[EvidenceId, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )

    @field_validator(
        "products",
        "focused_evidence_ids",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_product_slot(self) -> Self:
        ordinals = tuple(item.ordinal for item in self.products)
        if ordinals != tuple(range(1, len(self.products) + 1)):
            raise ValueError("product ordinal must be contiguous")
        product_ids = tuple(item.product_id for item in self.products)
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("product slot IDs must be unique")
        if (
            self.focused_product_id is not None
            and self.focused_product_id not in product_ids
        ):
            raise ValueError(
                "focused product must belong to product slot"
            )
        if len(self.focused_evidence_ids) != len(
            set(self.focused_evidence_ids)
        ):
            raise ValueError("focused evidence IDs must be unique")
        return self


class ImageSlotState(_StrictFrozenState):
    kind: Literal["image"] = "image"
    confirmed_products: tuple[ConfirmedImageProductRef, ...] = Field(
        min_length=1,
        max_length=3,
    )
    focused_image_ordinal: int | None = Field(
        default=None,
        ge=1,
        le=3,
    )

    @field_validator("confirmed_products", mode="before")
    @classmethod
    def freeze_products(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_image_slot(self) -> Self:
        ordinals = tuple(
            item.image_ordinal for item in self.confirmed_products
        )
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("confirmed image ordinals must be unique")
        if (
            self.focused_image_ordinal is not None
            and self.focused_image_ordinal not in ordinals
        ):
            raise ValueError(
                "focused image ordinal must be confirmed"
            )
        return self


class ConsultationSlotState(_StrictFrozenState):
    kind: Literal["consultation"] = "consultation"
    state: ConsultationSubstate


class KnowledgeSlotState(_StrictFrozenState):
    kind: Literal["knowledge"] = "knowledge"
    question: str = Field(min_length=1, max_length=4000)
    evidence_ids: tuple[EvidenceId, ...] = Field(
        default_factory=tuple,
        max_length=5,
    )

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def freeze_evidence(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise ValueError(
                "knowledge evidence IDs must be sorted and unique"
            )
        return self


class PendingClarificationSlot(_StrictFrozenState):
    kind: Literal["clarification"] = "clarification"
    value: ClarificationProgress


class PendingReplySlot(_StrictFrozenState):
    kind: Literal["pending_reply"] = "pending_reply"
    value: PendingTurn


ReplySlotState = Annotated[
    PendingClarificationSlot | PendingReplySlot,
    Field(discriminator="kind"),
]


class ConversationSnapshot(_StrictFrozenState):
    session_id: SessionId
    version: int = Field(ge=1)
    profile_owner: ProfileOwnerRef | None = None
    session_profile: SessionProfile | None = None
    active_owner: Responsibility | None = None
    active_focus: ActiveFocus | None = None
    recommendation_slot: RecommendationSlotState | None = None
    product_slot: ProductSlotState | None = None
    image_slot: ImageSlotState | None = None
    consultation_slot: ConsultationSlotState | None = None
    knowledge_slot: KnowledgeSlotState | None = None
    reply_slot: ReplySlotState | None = None

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if (
            self.active_owner is None
            and self.active_focus is not None
        ) or (
            self.active_owner is not None
            and self.active_focus is None
        ):
            raise ValueError(
                "active owner and focus must be present together"
            )
        if (
            self.active_focus is None
            and self.session_profile is None
        ):
            raise ValueError(
                "snapshot requires active focus or session profile"
            )
        if self.active_focus is not None:
            slot = getattr(
                self,
                f"{self.active_focus.slot}_slot",
            )
            if slot is None:
                raise ValueError(
                    "active focus must reference a present slot"
                )
            self._validate_focus(slot)
        if isinstance(self.reply_slot, PendingReplySlot):
            if (
                self.reply_slot.value.source_conversation_version
                >= self.version
            ):
                raise ValueError(
                    "pending turn source version must precede snapshot version"
                )
        return self

    def _validate_focus(self, slot: object) -> None:
        focus = self.active_focus
        if focus is None:
            return
        if isinstance(slot, RecommendationSlotState):
            if focus.ordinal != slot.focused_candidate_ordinal:
                raise ValueError(
                    "active recommendation focus must match slot"
                )
        elif isinstance(slot, ProductSlotState):
            if (
                focus.object_id is not None
                and focus.object_id != slot.focused_product_id
            ):
                raise ValueError(
                    "active product focus must match slot"
                )
        elif isinstance(slot, ImageSlotState):
            if focus.ordinal != slot.focused_image_ordinal:
                raise ValueError(
                    "active image focus must match slot"
                )


def migrate_legacy_conversation_snapshot_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    legacy = deepcopy(payload)
    query_context = legacy.get("query_context")
    candidates = legacy.get("candidates")
    candidate_rows = candidates if isinstance(candidates, list) else []
    recommendation_slot = None
    if (
        isinstance(query_context, dict)
        and query_context.get("recommendation_mode_basis") is not None
        and (candidate_rows or legacy.get("empty_result") is True)
    ):
        recommendation_slot = {
            "kind": "recommendation",
            "query_context": query_context,
            "candidates": candidate_rows,
            "empty_result": legacy.get("empty_result") is True,
            "focused_candidate_ordinal": legacy.get(
                "focused_candidate_ordinal"
            ),
        }

    focus_state = legacy.get("focus_state")
    focus_payload = focus_state if isinstance(focus_state, dict) else {}
    active_processor = focus_payload.get("active_processor")
    current_product_id = focus_payload.get("current_product_id")
    product_slot = None
    if (
        active_processor in {"comparison", "product_knowledge"}
        and candidate_rows
    ):
        product_slot = {
            "kind": "product",
            "products": candidate_rows[:3],
            "focused_product_id": (
                current_product_id
                if current_product_id
                in {
                    item.get("product_id")
                    for item in candidate_rows
                    if isinstance(item, dict)
                }
                else None
            ),
            "focused_evidence_ids": legacy.get(
                "focused_evidence_ids",
                [],
            ),
        }

    confirmed_images = focus_payload.get("confirmed_image_products")
    image_rows = (
        confirmed_images
        if isinstance(confirmed_images, list)
        else []
    )
    image_slot = (
        {
            "kind": "image",
            "confirmed_products": image_rows[:3],
            "focused_image_ordinal": (
                image_rows[0].get("image_ordinal")
                if len(image_rows) == 1
                and isinstance(image_rows[0], dict)
                else None
            ),
        }
        if image_rows
        else None
    )
    consultation = legacy.get("consultation")
    consultation_slot = (
        {"kind": "consultation", "state": consultation}
        if isinstance(consultation, dict)
        else None
    )
    question = legacy.get("last_general_knowledge_question")
    knowledge_slot = (
        {
            "kind": "knowledge",
            "question": question,
            "evidence_ids": legacy.get(
                "focused_general_knowledge_ids",
                [],
            ),
        }
        if isinstance(question, str) and question
        else None
    )
    pending_turn = legacy.get("pending_turn")
    pending_is_valid = (
        isinstance(pending_turn, dict)
        and isinstance(pending_turn.get("resume_context"), dict)
        and pending_turn["resume_context"].get(
            "recommendation_mode_basis"
        )
        is not None
    )
    clarification = legacy.get("clarification")
    reply_slot = (
        {
            "kind": "pending_reply",
            "value": pending_turn,
        }
        if pending_is_valid
        else (
            {
                "kind": "clarification",
                "value": clarification,
            }
            if isinstance(clarification, dict)
            else None
        )
    )

    owner_by_processor = {
        "recommendation": Responsibility.RECOMMENDATION.value,
        "comparison": Responsibility.COMPARISON.value,
        "product_knowledge": Responsibility.PRODUCT_KNOWLEDGE.value,
        "general_knowledge": Responsibility.GENERAL_KNOWLEDGE.value,
        "consultation": Responsibility.CONSULTATION.value,
        "image_identity": Responsibility.IMAGE_IDENTITY.value,
        "clarification": Responsibility.CLARIFICATION.value,
        "safety_escalation": Responsibility.SAFETY_ESCALATION.value,
    }
    focus = None
    if active_processor == "recommendation" and recommendation_slot:
        focus = {
            "slot": "recommendation",
            "object_id": None,
            "ordinal": recommendation_slot[
                "focused_candidate_ordinal"
            ],
        }
    elif active_processor in {"comparison", "product_knowledge"}:
        if product_slot is not None:
            focus = {
                "slot": "product",
                "object_id": product_slot["focused_product_id"],
                "ordinal": None,
            }
        elif image_slot is not None:
            focus = {
                "slot": "image",
                "object_id": current_product_id,
                "ordinal": image_slot["focused_image_ordinal"],
            }
    elif active_processor == "image_identity" and image_slot is not None:
        focus = {
            "slot": "image",
            "object_id": current_product_id,
            "ordinal": image_slot["focused_image_ordinal"],
        }
    elif active_processor in {"consultation", "safety_escalation"}:
        if consultation_slot is not None:
            focus = {
                "slot": "consultation",
                "object_id": None,
                "ordinal": None,
            }
    elif active_processor == "general_knowledge":
        if knowledge_slot is not None:
            focus = {
                "slot": "knowledge",
                "object_id": None,
                "ordinal": None,
            }
    elif active_processor == "clarification" and reply_slot is not None:
        focus = {
            "slot": "reply",
            "object_id": None,
            "ordinal": None,
        }

    active_owner = (
        owner_by_processor.get(active_processor)
        if focus is not None
        else None
    )
    return {
        "session_id": legacy.get("session_id"),
        "version": legacy.get("version"),
        "profile_owner": legacy.get("profile_owner"),
        "session_profile": legacy.get("session_profile"),
        "active_owner": active_owner,
        "active_focus": focus,
        "recommendation_slot": recommendation_slot,
        "product_slot": product_slot,
        "image_slot": image_slot,
        "consultation_slot": consultation_slot,
        "knowledge_slot": knowledge_slot,
        "reply_slot": reply_slot,
    }
