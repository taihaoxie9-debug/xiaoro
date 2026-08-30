from copy import deepcopy
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
    validate_confirmed_image_batch,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.session_profile import SessionProfile
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.contracts import CardDisplayContract
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


class _PresentationSlotState(_StrictFrozenState):
    card_display: CardDisplayContract | None = None


class RecommendationSlotState(_PresentationSlotState):
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


class ProductSlotState(_PresentationSlotState):
    kind: Literal["product"] = "product"
    products: tuple[DisplayedCandidateRef, ...] = Field(
        min_length=1,
        max_length=4,
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


class ImageSlotState(_PresentationSlotState):
    kind: Literal["image"] = "image"
    confirmed_products: tuple[ConfirmedImageProductRef, ...] = Field(
        min_length=1,
        max_length=4,
    )
    focused_image_ordinal: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )

    @field_validator("confirmed_products", mode="before")
    @classmethod
    def freeze_products(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_image_slot(self) -> Self:
        validate_confirmed_image_batch(self.confirmed_products)
        ordinals = tuple(
            item.image_ordinal for item in self.confirmed_products
        )
        if (
            self.focused_image_ordinal is not None
            and self.focused_image_ordinal not in ordinals
        ):
            raise ValueError(
                "focused image ordinal must be confirmed"
            )
        return self


class ConsultationSlotState(_PresentationSlotState):
    kind: Literal["consultation"] = "consultation"
    state: ConsultationSubstate


class KnowledgeSlotState(_PresentationSlotState):
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
        has_slot_state = any(
            slot is not None
            for slot in (
                self.recommendation_slot,
                self.product_slot,
                self.image_slot,
                self.consultation_slot,
                self.knowledge_slot,
                self.reply_slot,
            )
        )
        if (
            self.active_focus is None
            and self.session_profile is None
            and not has_slot_state
        ):
            raise ValueError(
                "snapshot requires active focus, session profile, "
                "or dormant slot state"
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
            if focus.ordinal is None:
                if focus.object_id is not None:
                    raise ValueError(
                        "active image focus requires paired object "
                        "and ordinal"
                    )
                return
            focused_product = next(
                item
                for item in slot.confirmed_products
                if item.image_ordinal == focus.ordinal
            )
            if focus.object_id != focused_product.product_id:
                raise ValueError(
                    "active image focus must bind one confirmed product"
                )


def _normalize_legacy_image_rows(
    value: object,
) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        return []
    try:
        legacy_products = tuple(
            ConfirmedImageProductRef.model_validate(
                item,
                strict=True,
            )
            for item in value
        )
        legacy_ordinals = tuple(
            item.image_ordinal for item in legacy_products
        )
        if len(legacy_ordinals) != len(set(legacy_ordinals)):
            return []
        legacy_product_ids = tuple(
            item.product_id for item in legacy_products
        )
        if len(legacy_product_ids) != len(set(legacy_product_ids)):
            return []
        normalized_products = tuple(
            item.model_copy(
                update={"image_ordinal": ordinal},
            )
            for ordinal, item in enumerate(
                sorted(
                    legacy_products,
                    key=lambda item: item.image_ordinal,
                ),
                start=1,
            )
        )
        validate_confirmed_image_batch(normalized_products)
    except (TypeError, ValueError):
        return []
    return [
        item.model_dump(mode="json")
        for item in normalized_products
    ]


_LEGACY_CONSULTATION_OBSERVATIONS = {
    "post_cleanse_tightness": {
        "dimension": "tightness",
        "location": "whole_face",
        "trigger": "post_cleanse",
        "duration": "current",
        "source_text": "洗脸后紧绷",
    },
    "t_zone_oiliness": {
        "dimension": "oiliness",
        "location": "t_zone",
        "trigger": "unknown",
        "duration": "current",
        "source_text": "T区出油",
    },
    "recurrent_redness": {
        "dimension": "redness",
        "location": "whole_face",
        "trigger": "unknown",
        "duration": "recurrent",
        "source_text": "反复泛红",
    },
    "stinging": {
        "dimension": "stinging",
        "location": "whole_face",
        "trigger": "unknown",
        "duration": "current",
        "source_text": "刺痛",
    },
    "flaking": {
        "dimension": "flaking",
        "location": "whole_face",
        "trigger": "unknown",
        "duration": "current",
        "source_text": "起皮",
    },
}
_LEGACY_CONSULTATION_STATES = {
    "yes": "present",
    "no": "absent",
    "sometimes": "sometimes",
    "unknown": "unknown",
}


def _migrate_legacy_consultation_state(
    value: object,
) -> object:
    if not isinstance(value, dict):
        return value
    observations = value.get("observations")
    if not isinstance(observations, list):
        return value
    migrated = deepcopy(value)
    migrated_observations: list[object] = []
    for observation in observations:
        if not isinstance(observation, dict):
            migrated_observations.append(observation)
            continue
        code = observation.get("code")
        answer = observation.get("answer")
        template = (
            _LEGACY_CONSULTATION_OBSERVATIONS.get(code)
            if isinstance(code, str)
            else None
        )
        state = (
            _LEGACY_CONSULTATION_STATES.get(answer)
            if isinstance(answer, str)
            else None
        )
        if (
            template is None
            or state is None
            or not isinstance(
                observation.get("source_turn_id"),
                str,
            )
        ):
            migrated_observations.append(observation)
            continue
        migrated_observations.append({
            "observation_id": f"obs_legacy_{code}",
            **template,
            "state": state,
            "severity": "unknown",
            "source_turn_id": observation["source_turn_id"],
        })
    migrated["observations"] = migrated_observations
    return migrated


def migrate_legacy_conversation_snapshot_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    legacy = deepcopy(payload)
    slot_names = (
        "recommendation_slot",
        "product_slot",
        "image_slot",
        "consultation_slot",
        "knowledge_slot",
        "reply_slot",
    )
    if any(name in legacy for name in slot_names):
        migrated = {
            "session_id": legacy.get("session_id"),
            "version": legacy.get("version"),
            "profile_owner": legacy.get("profile_owner"),
            "session_profile": legacy.get("session_profile"),
            "active_owner": legacy.get("active_owner"),
            "active_focus": legacy.get("active_focus"),
            **{
                name: legacy.get(name)
                for name in slot_names
            },
        }
        _move_card_display_to_active_slot(
            source=legacy,
            migrated=migrated,
        )
        consultation_slot = migrated.get("consultation_slot")
        if isinstance(consultation_slot, dict):
            consultation_slot["state"] = (
                _migrate_legacy_consultation_state(
                    consultation_slot.get("state")
                )
            )
        return migrated

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
    retained_product_rows = candidate_rows[:4]
    current_product_matches = tuple(
        item
        for item in retained_product_rows
        if (
            isinstance(item, dict)
            and item.get("product_id") == current_product_id
        )
    )
    product_slot = None
    if (
        retained_product_rows
        and (
            active_processor in {"comparison", "product_knowledge"}
            or len(current_product_matches) == 1
        )
    ):
        product_slot = {
            "kind": "product",
            "products": retained_product_rows,
            "focused_product_id": (
                current_product_id
                if len(current_product_matches) == 1
                else None
            ),
            "focused_evidence_ids": legacy.get(
                "focused_evidence_ids",
                [],
            ),
        }

    confirmed_images = focus_payload.get("confirmed_image_products")
    retained_image_rows = _normalize_legacy_image_rows(
        confirmed_images
    )
    focused_image_row = next(
        (
            item
            for item in retained_image_rows
            if (
                isinstance(item, dict)
                and item.get("product_id") == current_product_id
            )
        ),
        None,
    )
    if (
        focused_image_row is None
        and len(retained_image_rows) == 1
        and isinstance(retained_image_rows[0], dict)
    ):
        focused_image_row = retained_image_rows[0]
    focused_image_ordinal = (
        focused_image_row.get("image_ordinal")
        if focused_image_row is not None
        else None
    )
    focused_image_product_id = (
        focused_image_row.get("product_id")
        if focused_image_row is not None
        else None
    )
    image_slot = (
        {
            "kind": "image",
            "confirmed_products": retained_image_rows,
            "focused_image_ordinal": focused_image_ordinal,
        }
        if retained_image_rows
        else None
    )
    consultation = _migrate_legacy_consultation_state(
        legacy.get("consultation")
    )
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
        image_slot_owns_focus = (
            image_slot is not None
            and current_product_id is not None
            and focused_image_product_id == current_product_id
        )
        product_slot_owns_focus = (
            product_slot is not None
            and (
                current_product_id is None
                or product_slot["focused_product_id"]
                == current_product_id
            )
        )
        if product_slot_owns_focus:
            focus = {
                "slot": "product",
                "object_id": product_slot["focused_product_id"],
                "ordinal": None,
            }
        elif image_slot_owns_focus:
            focus = {
                "slot": "image",
                "object_id": focused_image_product_id,
                "ordinal": image_slot["focused_image_ordinal"],
            }
    elif active_processor == "image_identity" and image_slot is not None:
        focus = {
            "slot": "image",
            "object_id": focused_image_product_id,
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
    migrated = {
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
    _move_card_display_to_active_slot(
        source=legacy,
        migrated=migrated,
    )
    return migrated


def _move_card_display_to_active_slot(
    *,
    source: dict[str, object],
    migrated: dict[str, object],
) -> None:
    card_display = source.get("card_display")
    active_focus = migrated.get("active_focus")
    if card_display is None or not isinstance(active_focus, dict):
        return
    focus_slot = active_focus.get("slot")
    if focus_slot not in {
        "recommendation",
        "product",
        "image",
        "consultation",
        "knowledge",
    }:
        return
    slot_name = f"{focus_slot}_slot"
    slot = migrated.get(slot_name)
    if isinstance(slot, dict):
        slot["card_display"] = deepcopy(card_display)
