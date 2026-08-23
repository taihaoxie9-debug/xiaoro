from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from app.guide.application.chat_api_adapter import (
    iter_guide_public_events,
)
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.adapters.image.safe_image_input import (
    UntrustedImageInput,
)
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    KnowledgeSlotState,
)
from app.guide.feedback.focus_state import ActiveFocus
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.presentation_compiler import (
    PresentationCompiler,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
)
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousFailureLayer,
    ContinuousRuntimeTurnResult,
    ContinuousTrajectory,
)
from tools.guide_gates.continuous_conversation_mechanical_truth import (
    RuntimeImageFixture,
)
from tools.guide_gates.unified_router_gate import (
    RouteExpectation,
    detect_cross_session_leak,
    detect_hard_condition_override,
)


_IMAGE_FIXTURES = {
    "product-53-front": RuntimeImageFixture(
        product_id=53,
        relative_path=(
            "app/static/images/products/"
            "taobao_v3_572910260362.png"
        ),
        media_type="image/png",
    ),
    "product-55-front": RuntimeImageFixture(
        product_id=55,
        relative_path=(
            "app/static/images/products/"
            "tmall_v3_746513552108.png"
        ),
        media_type="image/png",
    ),
}


def runtime_image_fixtures() -> dict[str, RuntimeImageFixture]:
    return dict(_IMAGE_FIXTURES)


class _FrozenTurnMeaningProvider:
    def __init__(self) -> None:
        self._message: str | None = None
        self._meaning: TurnMeaning | None = None

    def bind(self, *, message: str, meaning: TurnMeaning) -> None:
        self._message = message
        self._meaning = meaning

    def propose(self, message, context) -> TurnMeaning:
        del context
        if message != self._message or self._meaning is None:
            raise ValueError("runtime TurnMeaning binding mismatch")
        return self._meaning


class _ContinuousExecutionObserver:
    def __init__(self) -> None:
        self.turn_identities: list[TurnIdentity] = []
        self.reset()

    def reset(self) -> None:
        self.compiled_understanding = None
        self.decision = None
        self.result = None
        self.reduced_snapshot = None
        self.envelope = None
        self.saved_snapshot = None

    def compiled(self, **values) -> None:
        self.compiled_understanding = values["understanding"]
        self.turn_identities.append(values["turn"].identity)

    def routed(self, **values) -> None:
        self.decision = values["decision"]

    def result_received(self, **values) -> None:
        self.result = values["result"]

    def state_reduced(self, **values) -> None:
        self.reduced_snapshot = values["snapshot"]

    def envelope_materialized(self, **values) -> None:
        self.envelope = values["envelope"]

    def state_saved(self, **values) -> None:
        self.saved_snapshot = values["snapshot"]


class ContinuousLocalRuntime:
    def __init__(
        self,
        trajectory: ContinuousTrajectory,
        state_root: Path,
        *,
        repo_root: Path,
    ) -> None:
        if type(trajectory) is not ContinuousTrajectory:
            raise TypeError(
                "trajectory must be an exact ContinuousTrajectory"
            )
        root = Path(repo_root).resolve()
        state_directory = Path(state_root).resolve()
        if not root.is_dir():
            raise ValueError("repo_root must be a directory")
        state_directory.mkdir(parents=True, exist_ok=False)
        self._trajectory = trajectory
        self._repo_root = root
        self._failure_layer = (
            ContinuousFailureLayer.SEMANTIC_ADMISSION
        )
        self._meaning_provider = _FrozenTurnMeaningProvider()
        self._observer = _ContinuousExecutionObserver()
        self._vertical = build_consultation_vertical_runtime(
            repo_root=root,
            state_dir=state_directory,
            semantic_intent=self._meaning_provider,
            execution_observer=self._observer,
        )
        disabled_compiler = PresentationCompiler(copywriter=None)
        self._vertical.recommendation._presentation_compiler = (
            disabled_compiler
        )
        self._vertical.consultation._presentation_compiler = (
            disabled_compiler
        )
        self._vertical.image_processor._presentation_compiler = (
            disabled_compiler
        )
        self._owner = self._vertical.profile_owner(
            trajectory.trajectory_id
        )
        sentinel_id = (
            "continuous-isolation-"
            + sha256(
                trajectory.trajectory_id.encode("utf-8")
            ).hexdigest()[:24]
        )
        self._isolation_sentinel = ConversationSnapshot(
            session_id=sentinel_id,
            version=1,
            active_owner=Responsibility.GENERAL_KNOWLEDGE,
            active_focus=ActiveFocus(slot="knowledge"),
            knowledge_slot=KnowledgeSlotState(
                question="isolation-sentinel",
            ),
        )
        self._vertical.conversation_state.save(
            self._isolation_sentinel,
            expected_version=0,
        )

    def execute(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        meaning: TurnMeaning,
        image_fixture_ids: tuple[str, ...],
    ) -> ContinuousRuntimeTurnResult:
        if session_id != self._trajectory.trajectory_id:
            raise ValueError("runtime session ID changed")
        snapshot = self._vertical.conversation_state.load(session_id)
        actual_version = snapshot.version if snapshot is not None else 0
        if conversation_version != actual_version:
            raise ValueError("conversation version drifted")
        if image_fixture_ids:
            return self._execute_image(
                session_id=session_id,
                conversation_version=conversation_version,
                message=message,
                meaning=meaning,
                image_fixture_ids=image_fixture_ids,
            )
        self._failure_layer = (
            ContinuousFailureLayer.SEMANTIC_ADMISSION
        )
        self._meaning_provider.bind(message=message, meaning=meaning)
        self._observer.reset()
        turn = UserTurn(
            identity=self._new_turn_identity(session_id),
            session_id=session_id,
            message=message,
            profile_owner=self._owner,
            conversation_version=conversation_version,
        )
        self._failure_layer = (
            ContinuousFailureLayer.DECISION_EXECUTION
        )
        frames = tuple(
            iter_guide_public_events(
                self._vertical.unified.stream(turn),
                session_id=turn.session_id,
            )
        )
        if not frames:
            raise RuntimeError(
                "continuous runtime emitted no public events"
            )
        events = _decode_public_sse_frames(frames)
        return self._observed_runtime_result(events=events)

    def _execute_image(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        meaning: TurnMeaning,
        image_fixture_ids: tuple[str, ...],
    ) -> ContinuousRuntimeTurnResult:
        self._failure_layer = (
            ContinuousFailureLayer.IDENTITY_BINDING
        )
        images: list[UntrustedImageInput] = []
        for fixture_id in image_fixture_ids:
            try:
                fixture = _IMAGE_FIXTURES[fixture_id]
            except KeyError as exc:
                raise ValueError(
                    f"unknown image fixture: {fixture_id}"
                ) from exc
            path = self._repo_root / fixture.relative_path
            images.append(UntrustedImageInput(
                file_name=path.name,
                declared_media_type=fixture.media_type,
                content=path.read_bytes(),
            ))
        receipt = self._vertical.image_bundle_service.create(
            session_id=session_id,
            images=tuple(images),
        )
        self._failure_layer = (
            ContinuousFailureLayer.SEMANTIC_ADMISSION
        )
        self._meaning_provider.bind(message=message, meaning=meaning)
        self._observer.reset()
        turn = UserTurn(
            identity=self._new_turn_identity(session_id),
            session_id=session_id,
            message=message,
            profile_owner=self._owner,
            image_bundle_id=receipt.bundle_id,
            image_bundle_version=receipt.version,
            image_bundle_token=receipt.owner_token,
            conversation_version=conversation_version,
        )

        self._failure_layer = (
            ContinuousFailureLayer.IDENTITY_BINDING
        )
        frames = tuple(
            iter_guide_public_events(
                self._vertical.unified.stream_image(turn),
                session_id=turn.session_id,
            ),
        )
        if not frames:
            raise RuntimeError(
                "continuous image runtime emitted no public events"
            )
        events = _decode_public_sse_frames(frames)
        return self._observed_runtime_result(events=events)

    @staticmethod
    def _new_turn_identity(session_id: str) -> TurnIdentity:
        return TurnIdentity(
            session_id=session_id,
            request_id=f"request_{uuid4().hex}",
            turn_id=f"turn_{uuid4().hex}",
        )

    def _observed_runtime_result(
        self,
        *,
        events: tuple[tuple[str, dict], ...],
    ) -> ContinuousRuntimeTurnResult:
        self._failure_layer = (
            ContinuousFailureLayer.PUBLIC_PRESENTATION
        )
        intent = next(
            (
                str(data.get("intent"))
                for event, data in events
                if event == "intent"
            ),
            "",
        )
        presentation_mode = next(
            (
                data.get("mode")
                for event, data in events
                if event == "presentation_contract"
            ),
            None,
        )
        card_ids = tuple(
            int(item["id"])
            for event, data in events
            if event == "products"
            for item in data.get("products", [])
            if isinstance(item, dict)
            and type(item.get("id")) is int
        )
        route = self._observer.decision
        if route is None:
            raise RuntimeError(
                "production flow emitted no observed route decision"
            )
        mode_by_intent = {
            "recommend": "recommend",
            "comparison": "comparison",
            "suitability": "suitability",
            "knowledge": "knowledge",
            "followup": "followup",
            "image_identity": "image_identity",
            "image_recommend": "recommend",
            "image_compare": "compare",
            "image_suitability": "suitability",
            "consultation_entry": "consultation",
            "consultation_answer": "consultation",
            "consultation_clarification": "consultation",
            "consultation_provisional": "consultation",
            "consultation_confirmation": "consultation",
            "consultation_rejection": "consultation",
            "consultation_medical_escalation": "consultation",
            "clarify": "clarify",
        }
        task_plan: dict[str, object] = {
            "mode": mode_by_intent.get(intent, intent),
        }
        if route.product_bindings:
            task_plan["product_ids"] = [
                binding.product_id
                for binding in route.product_bindings
            ]
        cross_session_snapshot = (
            self._vertical.conversation_state.load(
                self._isolation_sentinel.session_id
            )
        )
        return self._runtime_result(
            events=events,
            semantic_admission_passed=(
                self._observer.compiled_understanding is not None
            ),
            bindings=route.product_bindings,
            route=RouteExpectation(
                processor=route.processor,
                continuity=route.continuity,
                focus_source=route.focus_source,
            ),
            task_plan=task_plan,
            safety=any(
                event == "medical_escalation"
                for event, _ in events
            ),
            clarification=intent == "clarify",
            presentation_mode=presentation_mode,
            hard_condition_override=(
                detect_hard_condition_override(
                    events=events,
                    card_ids=card_ids,
                )
            ),
            cross_session_leak=detect_cross_session_leak(
                expected=self._isolation_sentinel,
                actual=cross_session_snapshot,
            ),
        )

    @staticmethod
    def _runtime_result(
        *,
        events,
        **values,
    ) -> ContinuousRuntimeTurnResult:
        return ContinuousRuntimeTurnResult(
            events=events,
            **values,
        )

    def failure_layer_for_last_error(
        self,
    ) -> ContinuousFailureLayer:
        return self._failure_layer

    def load_snapshot(
        self,
        session_id: str,
    ) -> ConversationSnapshot:
        snapshot = self._vertical.conversation_state.load(session_id)
        if snapshot is None:
            raise RuntimeError("committed snapshot is unavailable")
        return snapshot


def build_local_continuous_runtime(
    trajectory: ContinuousTrajectory,
    state_root: Path,
    *,
    repo_root: Path,
) -> ContinuousLocalRuntime:
    return ContinuousLocalRuntime(
        trajectory,
        state_root,
        repo_root=repo_root,
    )


def _decode_public_sse_frames(
    frames: tuple[bytes, ...],
) -> tuple[tuple[str, dict], ...]:
    events: list[tuple[str, dict]] = []
    for frame in frames:
        if type(frame) is not bytes:
            raise TypeError("continuous runtime SSE frame must be bytes")
        event_line, data_line, separator = frame.split(
            b"\n",
            maxsplit=2,
        )
        if (
            not event_line.startswith(b"event: ")
            or not data_line.startswith(b"data: ")
            or separator != b"\n"
        ):
            raise ValueError("continuous runtime emitted malformed SSE")
        event = event_line.removeprefix(b"event: ").decode("ascii")
        data = json.loads(
            data_line.removeprefix(b"data: ").decode("utf-8")
        )
        if not isinstance(data, dict):
            raise ValueError(
                "continuous runtime SSE data must be an object"
            )
        events.append((event, data))
    return tuple(events)


__all__ = [
    "ContinuousLocalRuntime",
    "build_local_continuous_runtime",
]
