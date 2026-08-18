from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Any, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.guide.presentation.copywriter_contracts import (
    PresentationMode,
)
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from tools.guide_gates.unified_router_gate import (
    RouteExpectation,
    SemanticExpectation,
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class ContinuousFailureLayer(str, Enum):
    MODEL_TRANSLATION = "model_translation"
    SEMANTIC_ADMISSION = "semantic_admission"
    IDENTITY_BINDING = "identity_binding"
    ROUTE_SELECTION = "route_selection"
    STATE_TRANSITION = "state_transition"
    DECISION_EXECUTION = "decision_execution"
    DATA_COVERAGE = "data_coverage"
    PUBLIC_PRESENTATION = "public_presentation"


PublicAnswerPolicy = Literal[
    "recommendation",
    "comparison",
    "product_knowledge",
    "general_knowledge",
    "consultation",
    "clarification",
    "safety",
]


class ContinuousTrajectoryExecutionError(RuntimeError):
    pass


class ContinuousTurnExpectation(_StrictFrozen):
    turn_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    message: str = Field(min_length=1, max_length=4000)
    image_fixture_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    acceptable_semantic: SemanticExpectation
    expected_bindings: tuple[ResolvedProductBinding, ...] = ()
    expected_route: RouteExpectation
    expected_snapshot_subset: dict[str, JsonValue]
    expected_task_plan_subset: dict[str, JsonValue]
    expected_card_ids: tuple[int, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    expected_safety: bool
    expected_clarification: bool
    expected_presentation_mode: PresentationMode | None
    public_answer_policy: PublicAnswerPolicy

    @field_validator(
        "image_fixture_ids",
        "expected_bindings",
        "expected_card_ids",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_expected_output(self) -> Self:
        if (
            self.image_fixture_ids
            and (
                len(self.image_fixture_ids)
                != len(set(self.image_fixture_ids))
                or any(
                    not fixture_id
                    or len(fixture_id) > 160
                    or not all(
                        character.isascii()
                        and (
                            character.isalnum()
                            or character in {"_", "-"}
                        )
                        for character in fixture_id
                    )
                    for fixture_id in self.image_fixture_ids
                )
            )
        ):
            raise ValueError(
                "image fixture IDs must be unique ASCII identifiers"
            )
        if (
            self.expected_route.processor == "image_identity"
            and not self.image_fixture_ids
        ):
            raise ValueError(
                "image identity requires image fixtures"
            )
        if self.expected_safety and self.expected_clarification:
            raise ValueError(
                "safety and clarification expectations are exclusive"
            )
        if len(self.expected_card_ids) != len(
            set(self.expected_card_ids)
        ):
            raise ValueError("expected card IDs must be unique")
        return self


class ContinuousTrajectory(_StrictFrozen):
    schema_version: Literal[
        "guide-continuous-trajectory-v1"
    ] = "guide-continuous-trajectory-v1"
    trajectory_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    subject_scope: Literal["self", "other", "mixed"]
    route_families: tuple[str, ...] = Field(min_length=1)
    turns: tuple[
        ContinuousTurnExpectation,
        ContinuousTurnExpectation,
        ContinuousTurnExpectation,
        ContinuousTurnExpectation,
        ContinuousTurnExpectation,
    ]

    @field_validator(
        "route_families",
        "turns",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if len(self.route_families) != len(
            set(self.route_families)
        ):
            raise ValueError("route families must be unique")
        turn_ids = tuple(turn.turn_id for turn in self.turns)
        if len(turn_ids) != len(set(turn_ids)):
            raise ValueError("turn IDs must be unique")
        if any(
            not turn_id.startswith(f"{self.trajectory_id}-t")
            for turn_id in turn_ids
        ):
            raise ValueError("turn IDs must belong to trajectory")
        return self


PublicEvent = tuple[str, dict[str, Any]]


class ContinuousRuntimeTurnResult(_StrictFrozen):
    events: tuple[PublicEvent, ...] = Field(min_length=1)
    delivery_event: Any | None = Field(default=None, exclude=True)
    semantic_admission_passed: bool
    bindings: tuple[ResolvedProductBinding, ...] = ()
    route: RouteExpectation
    task_plan: dict[str, JsonValue]
    safety: bool
    clarification: bool
    presentation_mode: PresentationMode | None
    hard_condition_override: bool
    cross_session_leak: bool

    @field_validator(
        "events",
        "bindings",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ContinuousRuntime(Protocol):
    def execute(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        meaning: TurnMeaning,
        image_fixture_ids: tuple[str, ...],
    ) -> ContinuousRuntimeTurnResult: ...

    def commit(self, terminal_event: PublicEvent) -> None: ...

    def discard(self, terminal_event: object) -> None: ...

    def load_snapshot(
        self,
        session_id: str,
    ) -> ConversationSnapshot: ...


class ContinuousTurnTrace(_StrictFrozen):
    turn_id: str
    starting_version: int = Field(ge=0)
    terminal_version: int = Field(ge=1)
    image_fixture_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    meaning: TurnMeaning
    semantic_admission_passed: bool
    bindings: tuple[ResolvedProductBinding, ...] = ()
    route: RouteExpectation
    task_plan: dict[str, JsonValue]
    card_ids: tuple[int, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    public_messages: tuple[str, ...] = ()
    event_names: tuple[str, ...] = Field(min_length=1)
    safety: bool
    clarification: bool
    presentation_mode: PresentationMode | None
    hard_condition_override: bool
    cross_session_leak: bool
    final_snapshot: ConversationSnapshot


class ContinuousTrajectoryTrace(_StrictFrozen):
    trajectory_id: str
    turns: tuple[
        ContinuousTurnTrace,
        ContinuousTurnTrace,
        ContinuousTurnTrace,
        ContinuousTurnTrace,
        ContinuousTurnTrace,
    ]


def execute_continuous_trajectory(
    trajectory: ContinuousTrajectory,
    *,
    runtime: ContinuousRuntime,
    meanings: Sequence[TurnMeaning],
) -> ContinuousTrajectoryTrace:
    if type(trajectory) is not ContinuousTrajectory:
        raise TypeError(
            "trajectory must be an exact ContinuousTrajectory"
        )
    normalized_meanings = tuple(meanings)
    if (
        len(normalized_meanings) != 5
        or any(
            type(meaning) is not TurnMeaning
            for meaning in normalized_meanings
        )
    ):
        raise ValueError(
            "meanings must contain exactly five TurnMeaning values"
        )
    traces: list[ContinuousTurnTrace] = []
    version = 0
    for turn, meaning in zip(
        trajectory.turns,
        normalized_meanings,
        strict=True,
    ):
        runtime_result = runtime.execute(
            session_id=trajectory.trajectory_id,
            conversation_version=version,
            message=turn.message,
            meaning=meaning,
            image_fixture_ids=turn.image_fixture_ids,
        )
        if type(runtime_result) is not ContinuousRuntimeTurnResult:
            raise TypeError(
                "runtime must return ContinuousRuntimeTurnResult"
            )
        events = runtime_result.events
        delivery_event = (
            runtime_result.delivery_event
            if runtime_result.delivery_event is not None
            else events[-1]
        )
        if not events or events[-1][0] != "end":
            runtime.discard(delivery_event)
            raise ContinuousTrajectoryExecutionError(
                f"{turn.turn_id} did not emit terminal end"
            )
        terminal = events[-1]
        terminal_version = terminal[1].get(
            "conversation_version"
        )
        if (
            type(terminal_version) is not int
            or terminal_version != version + 1
        ):
            runtime.discard(delivery_event)
            raise ContinuousTrajectoryExecutionError(
                f"{turn.turn_id} did not advance exactly once"
            )
        runtime.commit(delivery_event)
        snapshot = runtime.load_snapshot(
            trajectory.trajectory_id
        )
        if snapshot.version != terminal_version:
            raise ContinuousTrajectoryExecutionError(
                f"{turn.turn_id} committed snapshot version drifted"
            )
        card_ids = _public_card_ids(events)
        public_messages = tuple(
            str(data["content"])
            for event, data in events
            if (
                event == "message"
                and isinstance(data.get("content"), str)
            )
        )
        traces.append(ContinuousTurnTrace(
            turn_id=turn.turn_id,
            starting_version=version,
            terminal_version=terminal_version,
            image_fixture_ids=turn.image_fixture_ids,
            meaning=meaning,
            semantic_admission_passed=(
                runtime_result.semantic_admission_passed
            ),
            bindings=runtime_result.bindings,
            route=runtime_result.route,
            task_plan=runtime_result.task_plan,
            card_ids=card_ids,
            public_messages=public_messages,
            event_names=tuple(event for event, _ in events),
            safety=runtime_result.safety,
            clarification=runtime_result.clarification,
            presentation_mode=runtime_result.presentation_mode,
            hard_condition_override=(
                runtime_result.hard_condition_override
            ),
            cross_session_leak=runtime_result.cross_session_leak,
            final_snapshot=snapshot,
        ))
        version = terminal_version
    return ContinuousTrajectoryTrace(
        trajectory_id=trajectory.trajectory_id,
        turns=tuple(traces),
    )


def _public_card_ids(
    events: Sequence[PublicEvent],
) -> tuple[int, ...]:
    ids: list[int] = []
    for event, data in events:
        if event != "products":
            continue
        rows = data.get("products", data.get("cards", ()))
        if not isinstance(rows, (list, tuple)):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            product_id = row.get("id", row.get("product_id"))
            if type(product_id) is int and product_id not in ids:
                ids.append(product_id)
    return tuple(ids)


__all__ = [
    "ContinuousFailureLayer",
    "ContinuousRuntime",
    "ContinuousRuntimeTurnResult",
    "ContinuousTrajectory",
    "ContinuousTrajectoryExecutionError",
    "ContinuousTrajectoryTrace",
    "ContinuousTurnTrace",
    "ContinuousTurnExpectation",
    "PublicAnswerPolicy",
    "execute_continuous_trajectory",
]
