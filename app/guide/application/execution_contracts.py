from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.application.contracts import OwnerToken, TurnIdentity
from app.guide.application.dynamic_consultation import (
    PreparedConsultationEvidence,
)
from app.guide.application.image_bundle_state import ImageBundlePayload
from app.guide.application.pending_turn import PendingReply
from app.guide.application.public_event_envelope import (
    encode_sse_frame,
    materialize_guide_public_events,
)
from app.guide.application.scenario_contracts import ScenarioInputBundle
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    DisplayedCandidateRef,
    EvidenceId,
    PendingTurn,
    RecommendationQueryContext,
)
from app.guide.feedback.focus_state import ConfirmedImageProductRef
from app.guide.feedback.profile_policy import ResolvedProfileContext
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.session_profile import (
    SessionProfileUpdate,
    SourceTurnId,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.contracts import TaskPlan
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.presentation.public_contracts import (
    PublicPresentationContract,
)
from app.guide.presentation.sse_events import (
    ClarifyData,
    ClarifyEvent,
    EndData,
    EndEvent,
    ErrorData,
    ErrorEvent,
    PresentationContractEvent,
    SseEvent,
    StartData,
    StartEvent,
)
from app.guide.presentation.terminal_contract_guard import (
    GuideTerminalContractGuard,
)
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
)
from app.guide.understanding.contracts import (
    ImageBundle,
    StructuredUnderstanding,
    TopicCode,
)
from app.guide.understanding.image_contracts import (
    IdentityState,
    ImageIdentityObservation,
)
from app.guide.understanding.scenario_parsing import ScenarioObservation


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


@dataclass(frozen=True, slots=True)
class ImageRoutingEvidence:
    bundle: ImageBundle
    owner_token: OwnerToken
    payloads: tuple[ImageBundlePayload, ...]
    observations: tuple[ImageIdentityObservation, ...]
    anchor_topic: TopicCode | None

    def __post_init__(self) -> None:
        if not 1 <= len(self.payloads) <= 4:
            raise ValueError(
                "image routing evidence requires one to four payloads"
            )
        if len(self.payloads) != len(self.observations):
            raise ValueError(
                "image routing evidence count mismatch"
            )

    @property
    def image_count(self) -> int:
        return len(self.payloads)

    @property
    def confirmed_products(
        self,
    ) -> tuple[ConfirmedImageProductRef, ...]:
        return tuple(
            ConfirmedImageProductRef(
                image_ordinal=ordinal,
                product_id=observation.confirmed_product_id,
            )
            for ordinal, observation in enumerate(
                self.observations,
                start=1,
            )
            if (
                observation.identity_state is IdentityState.CONFIRMED
                and observation.confirmed_product_id is not None
            )
        )


class OpaqueRetrievalQuery(_StrictFrozen):
    value: str = Field(min_length=1, max_length=4000)


class PreRoutingEvidence(_StrictFrozen):
    query: OpaqueRetrievalQuery
    conversation_version: int = Field(ge=0)
    profile_owner: ProfileOwnerRef | None = None
    profile_context: ResolvedProfileContext
    product_resolution: ProductMentionResolution
    pending_reply: PendingReply | None = None
    task_plan: TaskPlan
    scenario_inputs: ScenarioInputBundle | None = None
    product_knowledge_dimensions: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    consultation: PreparedConsultationEvidence
    image: ImageRoutingEvidence | None = None
    candidate_product_ids: tuple[int, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    scenario_observations: tuple[ScenarioObservation, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    transition_operations: tuple[
        Literal["add", "retain", "replace", "remove"],
        ...,
    ] = Field(default_factory=tuple, max_length=32)

    @model_validator(mode="after")
    def validate_evidence(self):
        if (
            len(self.candidate_product_ids)
            != len(set(self.candidate_product_ids))
            or any(
                isinstance(product_id, bool) or product_id <= 0
                for product_id in self.candidate_product_ids
            )
        ):
            raise ValueError(
                "candidate product IDs must be unique positive integers"
            )
        scenario_codes = tuple(
            observation.scenario
            for observation in self.scenario_observations
        )
        if len(scenario_codes) != len(set(scenario_codes)):
            raise ValueError("scenario observations must be unique")
        return self


class ProcessorExecutionInput(_StrictFrozen):
    turn_identity: TurnIdentity
    understanding: StructuredUnderstanding
    decision: UnifiedRouteDecision
    current_snapshot: ConversationSnapshot | None
    routing_evidence: PreRoutingEvidence

    @model_validator(mode="after")
    def validate_input(self):
        if (
            self.turn_identity.session_id
            != (
                self.current_snapshot.session_id
                if self.current_snapshot is not None
                else self.turn_identity.session_id
            )
        ):
            raise ValueError(
                "processor input snapshot session must match turn identity"
            )
        if (
            self.current_snapshot is not None
            and self.current_snapshot.version
            != self.routing_evidence.conversation_version
        ):
            raise ValueError(
                "processor input version must match current snapshot"
            )
        return self


class RecommendationLaneState(_StrictFrozen):
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
    focused_evidence_ids: tuple[EvidenceId, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )


class ProductLaneState(_StrictFrozen):
    current_product_id: int | None = Field(default=None, gt=0)
    candidates: tuple[DisplayedCandidateRef, ...] = Field(
        default_factory=tuple,
        min_length=0,
        max_length=3,
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

    @model_validator(mode="after")
    def validate_product_lane(self):
        has_current = self.current_product_id is not None
        has_candidates = bool(self.candidates)
        if has_current == has_candidates:
            raise ValueError(
                "product lane requires one current item or one batch"
            )
        if has_candidates:
            ordinals = tuple(item.ordinal for item in self.candidates)
            product_ids = tuple(
                item.product_id for item in self.candidates
            )
            if (
                len(self.candidates) < 2
                or ordinals
                != tuple(range(1, len(self.candidates) + 1))
                or len(product_ids) != len(set(product_ids))
                or self.focused_candidate_ordinal is not None
            ):
                raise ValueError(
                    "product batch must be ordered, unique, and unfocused"
                )
        return self


class ImageLaneState(_StrictFrozen):
    confirmed_products: tuple[ConfirmedImageProductRef, ...] = Field(
        min_length=1,
        max_length=3,
    )
    has_image_delivery: Literal[True] = True


class KnowledgeLaneState(_StrictFrozen):
    focused_ids: tuple[EvidenceId, ...] = Field(
        default_factory=tuple,
        max_length=5,
    )
    question: str = Field(min_length=1, max_length=4000)
    topic: str = Field(min_length=1, max_length=256)


class ClarificationLaneState(_StrictFrozen):
    progress: ClarificationProgress
    pending_turn: PendingTurn | None = None


class ProfileLanePatch(_StrictFrozen):
    profile_owner: ProfileOwnerRef
    updates: tuple[SessionProfileUpdate, ...] = Field(
        min_length=1,
        max_length=16,
    )
    subject_scope: Literal["self"]
    source_turn_id: SourceTurnId


LaneValue = TypeVar("LaneValue")


class LaneMutation(_StrictFrozen, Generic[LaneValue]):
    action: Literal["preserve", "replace", "clear"] = "preserve"
    value: LaneValue | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "replace":
            if self.value is None or self.reason is not None:
                raise ValueError(
                    "replace lane mutation requires only value"
                )
            return self
        if self.value is not None:
            raise ValueError(
                f"{self.action} lane mutation forbids value"
            )
        if self.action == "clear":
            if self.reason is None:
                raise ValueError(
                    "clear lane mutation requires reason"
                )
            return self
        if self.reason is not None:
            raise ValueError(
                "preserve lane mutation forbids reason"
            )
        return self


def _preserve(lane_type):
    return lambda: LaneMutation[lane_type](action="preserve")


class ConversationStateDelta(_StrictFrozen):
    profile_owner: ProfileOwnerRef | None = None
    recommendation: LaneMutation[RecommendationLaneState] = Field(
        default_factory=_preserve(RecommendationLaneState)
    )
    product: LaneMutation[ProductLaneState] = Field(
        default_factory=_preserve(ProductLaneState)
    )
    image: LaneMutation[ImageLaneState] = Field(
        default_factory=_preserve(ImageLaneState)
    )
    consultation: LaneMutation[ConsultationSubstate] = Field(
        default_factory=_preserve(ConsultationSubstate)
    )
    knowledge: LaneMutation[KnowledgeLaneState] = Field(
        default_factory=_preserve(KnowledgeLaneState)
    )
    clarification: LaneMutation[ClarificationLaneState] = Field(
        default_factory=_preserve(ClarificationLaneState)
    )
    profile: LaneMutation[ProfileLanePatch] = Field(
        default_factory=_preserve(ProfileLanePatch)
    )


class PresentationTerminal(_StrictFrozen):
    kind: Literal["presentation"] = "presentation"
    data: PublicPresentationContract


class ClarificationTerminal(_StrictFrozen):
    kind: Literal["clarification"] = "clarification"
    data: ClarifyData


class ErrorTerminal(_StrictFrozen):
    kind: Literal["error"] = "error"
    data: ErrorData


ExecutionTerminal = Annotated[
    PresentationTerminal | ClarificationTerminal | ErrorTerminal,
    Field(discriminator="kind"),
]


class ExecutionResult(_StrictFrozen):
    decision: UnifiedRouteDecision
    state_delta: ConversationStateDelta
    terminal: ExecutionTerminal
    audit_events: tuple[SseEvent, ...] = ()

    @model_validator(mode="after")
    def validate_result(self):
        if isinstance(self.terminal, PresentationTerminal):
            if (
                self.terminal.data.responsibility
                is not self.decision.responsibility
                or self.terminal.data.mode
                != self.decision.presentation_mode
            ):
                raise ValueError(
                    "presentation terminal must match route decision"
                )
            self._validate_presentation_bindings()
        elif isinstance(self.terminal, ClarificationTerminal):
            mutation = self.state_delta.clarification
            progress = (
                mutation.value.progress
                if (
                    mutation.action == "replace"
                    and mutation.value is not None
                )
                else None
            )
            if (
                progress is None
                or progress.gap
                is not self.terminal.data.clarification_code
            ):
                raise ValueError(
                    "clarification terminal requires matching state delta"
                )
        elif any(
            mutation.action != "preserve"
            for mutation in self._lane_mutations()
        ):
            raise ValueError("error terminal forbids state mutation")
        if any(
            event.event
            in {
                "start",
                "presentation_contract",
                "clarify",
                "error",
                "end",
            }
            for event in self.audit_events
        ):
            raise ValueError(
                "audit events cannot contain framing or terminal events"
            )
        return self

    def _lane_mutations(self) -> tuple[LaneMutation, ...]:
        delta = self.state_delta
        return (
            delta.recommendation,
            delta.product,
            delta.image,
            delta.consultation,
            delta.knowledge,
            delta.clarification,
            delta.profile,
        )

    def _validate_presentation_bindings(self) -> None:
        if not isinstance(self.terminal, PresentationTerminal):
            raise AssertionError("presentation terminal is required")
        visible_product_ids = self.terminal.data.visible_product_ids
        route_product_ids = tuple(
            binding.product_id
            for binding in self.decision.product_bindings
        )
        if self.decision.responsibility in {
            Responsibility.COMPARISON,
            Responsibility.SINGLE_PRODUCT_SUITABILITY,
            Responsibility.PRODUCT_KNOWLEDGE,
            Responsibility.IMAGE_IDENTITY,
        } and route_product_ids != visible_product_ids:
            raise ValueError(
                "product bindings must match decision and presentation"
            )
        product_mutation = self.state_delta.product
        if product_mutation.action == "replace":
            product = product_mutation.value
            if product is None:
                raise ValueError(
                    "product bindings must match decision and presentation"
                )
            product_ids = (
                tuple(
                    candidate.product_id
                    for candidate in product.candidates
                )
                if product.candidates
                else (product.current_product_id,)
            )
            if visible_product_ids != product_ids:
                raise ValueError(
                    "product bindings must match decision and presentation"
                )
        recommendation_mutation = self.state_delta.recommendation
        if (
            self.decision.responsibility
            is Responsibility.RECOMMENDATION
            and recommendation_mutation.action == "replace"
        ):
            recommendation = recommendation_mutation.value
            if (
                recommendation is None
                or tuple(
                    candidate.product_id
                    for candidate in recommendation.candidates
                )
                != visible_product_ids
            ):
                raise ValueError(
                    "recommendation bindings must match presentation"
                )
        image_mutation = self.state_delta.image
        if (
            self.decision.responsibility
            is Responsibility.IMAGE_IDENTITY
            and image_mutation.action == "replace"
        ):
            image = image_mutation.value
            if (
                image is None
                or tuple(
                    item.product_id
                    for item in image.confirmed_products
                )
                != visible_product_ids
            ):
                raise ValueError(
                    "image bindings must match presentation"
                )


class EncodedSseEnvelope(_StrictFrozen):
    decision: UnifiedRouteDecision
    decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    frames: tuple[bytes, ...] = Field(min_length=2)


def materialize_execution_envelope(
    result: ExecutionResult,
    *,
    session_id: str,
    conversation_version: int,
) -> EncodedSseEnvelope:
    if type(result) is not ExecutionResult:
        raise TypeError("result must be an exact ExecutionResult")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be nonempty")
    if (
        not isinstance(conversation_version, int)
        or isinstance(conversation_version, bool)
        or conversation_version < 0
    ):
        raise ValueError(
            "conversation_version must be a non-negative integer"
        )

    terminal = result.terminal
    if isinstance(terminal, PresentationTerminal):
        terminal_events: tuple[SseEvent, ...] = (
            PresentationContractEvent(data=terminal.data),
            EndEvent(
                data=EndData(
                    conversation_version=conversation_version,
                )
            ),
        )
    elif isinstance(terminal, ClarificationTerminal):
        terminal_events = (
            ClarifyEvent(data=terminal.data),
            EndEvent(
                data=EndData(
                    conversation_version=conversation_version,
                )
            ),
        )
    else:
        terminal_events = (ErrorEvent(data=terminal.data),)

    events = (
        StartEvent(data=StartData(session_id=session_id)),
        *result.audit_events,
        *terminal_events,
    )
    guard = GuideTerminalContractGuard()
    for event in events:
        guard.observe(event)
    guard.finish()

    public_events = materialize_guide_public_events(
        events,
        session_id=session_id,
    )
    decision_bytes = json.dumps(
        result.decision.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return EncodedSseEnvelope(
        decision=result.decision,
        decision_digest=sha256(decision_bytes).hexdigest(),
        frames=tuple(
            encode_sse_frame(event, data)
            for event, data in public_events
        ),
    )
__all__ = [
    "ClarificationLaneState",
    "ClarificationTerminal",
    "ConversationStateDelta",
    "ErrorTerminal",
    "EncodedSseEnvelope",
    "ExecutionResult",
    "ExecutionTerminal",
    "ImageRoutingEvidence",
    "ImageLaneState",
    "KnowledgeLaneState",
    "LaneMutation",
    "OpaqueRetrievalQuery",
    "PreRoutingEvidence",
    "PresentationTerminal",
    "ProcessorExecutionInput",
    "ProductLaneState",
    "ProfileLanePatch",
    "RecommendationLaneState",
    "TurnIdentity",
    "materialize_execution_envelope",
]
