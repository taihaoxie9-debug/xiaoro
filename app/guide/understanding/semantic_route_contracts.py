from __future__ import annotations

from enum import Enum
from typing import ClassVar, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_serializer,
    model_validator,
)

from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import (
    ActiveDialogue,
    ActiveConstraintKind,
    ClarificationCode,
    SemanticContext,
)


class SemanticDetailStage(str, Enum):
    RECOMMENDATION = "recommendation"
    ASSESSMENT = "assessment"
    COMPARISON = "comparison"
    FOLLOWUP = "followup"
    KNOWLEDGE = "knowledge"
    IMAGE = "image"
    NONE = "none"


_DETAIL_STAGE_BY_GOAL = {
    UnderstandingGoal.RECOMMENDATION: SemanticDetailStage.RECOMMENDATION,
    UnderstandingGoal.SUITABILITY: SemanticDetailStage.ASSESSMENT,
    UnderstandingGoal.ASSESSMENT: SemanticDetailStage.ASSESSMENT,
    UnderstandingGoal.COMPARISON: SemanticDetailStage.COMPARISON,
    UnderstandingGoal.FOLLOWUP: SemanticDetailStage.FOLLOWUP,
    UnderstandingGoal.KNOWLEDGE: SemanticDetailStage.KNOWLEDGE,
    UnderstandingGoal.IMAGE_SIMILARITY: SemanticDetailStage.IMAGE,
    UnderstandingGoal.CLARIFICATION: SemanticDetailStage.NONE,
}


class SemanticRouteBindingAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    active_dialogue: ActiveDialogue | None
    awaiting_reply: bool
    candidate_ordinals: tuple[int, ...] = Field(max_length=4)
    current_item_ordinal: int | None = Field(default=None, ge=1, le=4)
    current_batch_available: bool
    image_ordinals: tuple[int, ...] = Field(max_length=4)
    confirmed_image_ordinals: tuple[int, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    current_image_ordinal: int | None = Field(default=None, ge=1, le=4)
    current_topic: TopicCode | None
    previous_constraint_kinds: tuple[
        ActiveConstraintKind,
        ...,
    ] = Field(max_length=5)
    pending_clarification: ClarificationCode | None

    @model_serializer(mode="wrap")
    def omit_empty_confirmed_image_ordinals(self, handler):
        payload = handler(self)
        if not self.confirmed_image_ordinals:
            payload.pop("confirmed_image_ordinals", None)
        return payload

    @classmethod
    def from_context(
        cls,
        context: SemanticContext,
    ) -> SemanticRouteBindingAuthority:
        if not isinstance(context, SemanticContext):
            raise TypeError("context must be a SemanticContext")
        return cls(
            active_dialogue=context.active_dialogue,
            awaiting_reply=context.awaiting_reply,
            candidate_ordinals=tuple(
                range(1, context.visible_candidate_count + 1)
            ),
            current_item_ordinal=context.focused_candidate_ordinal,
            current_batch_available=(
                context.visible_candidate_count > 0
            ),
            image_ordinals=tuple(range(1, context.image_count + 1)),
            confirmed_image_ordinals=(
                context.confirmed_image_ordinals
            ),
            current_image_ordinal=context.focused_image_ordinal,
            current_topic=context.active_topic,
            previous_constraint_kinds=context.active_constraint_kinds,
            pending_clarification=context.pending_clarification,
        )

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.candidate_ordinals != tuple(
            range(1, len(self.candidate_ordinals) + 1)
        ):
            raise ValueError(
                "candidate ordinals must be contiguous from one"
            )
        if self.current_batch_available != bool(
            self.candidate_ordinals
        ):
            raise ValueError(
                "current batch availability must match candidates"
            )
        if (
            self.current_item_ordinal is not None
            and self.current_item_ordinal
            not in self.candidate_ordinals
        ):
            raise ValueError(
                "current item must reference an admitted candidate"
            )
        if self.image_ordinals != tuple(
            range(1, len(self.image_ordinals) + 1)
        ):
            raise ValueError("image ordinals must be contiguous from one")
        if (
            self.current_image_ordinal is not None
            and self.current_image_ordinal not in self.image_ordinals
        ):
            raise ValueError(
                "current image must reference an admitted image"
            )
        if (
            self.confirmed_image_ordinals
            != tuple(sorted(set(self.confirmed_image_ordinals)))
            or not set(self.confirmed_image_ordinals).issubset(
                self.image_ordinals
            )
        ):
            raise ValueError(
                "confirmed image ordinals must be sorted, unique, and "
                "admitted"
            )
        if len(self.previous_constraint_kinds) != len(
            set(self.previous_constraint_kinds)
        ):
            raise ValueError(
                "previous constraint kinds must be unique"
            )
        return self


class SemanticRouteProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: ClassVar[str] = "guide-semantic-route-v1"

    goal: UnderstandingGoal
    topic: TopicCode | None
    detail_stage: SemanticDetailStage
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    clarification_hint: ClarificationCode | None = None

    @model_validator(mode="after")
    def validate_stage(self) -> Self:
        if self.detail_stage is not _DETAIL_STAGE_BY_GOAL[self.goal]:
            raise ValueError("detail stage must match route goal")
        if (
            self.goal is UnderstandingGoal.CLARIFICATION
            and self.clarification_hint is None
        ):
            raise ValueError("clarification route requires clarification hint")
        if (
            self.goal is not UnderstandingGoal.CLARIFICATION
            and self.clarification_hint is not None
        ):
            raise ValueError(
                "non-clarification route forbids clarification hint"
            )
        return self


__all__ = [
    "SemanticDetailStage",
    "SemanticRouteBindingAuthority",
    "SemanticRouteProposal",
]
