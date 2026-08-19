from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from app.guide.application.chat_api_adapter import (
    commit_http_event_delivery,
    discard_http_event_delivery,
    iter_guide_public_events,
)
from app.guide.application.contracts import UserTurn
from app.guide.adapters.image.safe_image_input import (
    UntrustedImageInput,
)
from app.guide.application.pending_turn import (
    resolve_semantic_pending_reply,
    resume_pending_recommendation,
)
from app.guide.application.query_context import (
    apply_session_profile_to_task,
)
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.focus_state import (
    ConfirmedImageProductRef,
    FocusState,
)
from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.intent.semantic_admission import admit_turn_meaning
from app.guide.intent.task_planning import plan_task
from app.guide.intent.transition_planning import (
    plan_code_owned_transitions,
    plan_route_transition_operations,
)
from app.guide.intent.unified_turn_router import (
    reconcile_product_resolution_issue,
    route_unified_turn,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompiler,
)
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
    ResolvedProductBinding,
)
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.safety_admission import (
    admit_safety_signal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
    build_image_bundle_service,
    build_image_recommendation_orchestrator,
    build_selection_concept_assets,
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
        self._vertical = build_consultation_vertical_runtime(
            repo_root=root,
            state_dir=state_directory,
        )
        disabled_compiler = PresentationCompiler(copywriter=None)
        self._vertical.recommendation._presentation_compiler = (
            disabled_compiler
        )
        self._vertical.consultation._presentation_compiler = (
            disabled_compiler
        )
        self._image_bundle_service = None
        self._image_processor = None
        if any(
            turn.image_fixture_ids
            for turn in trajectory.turns
        ):
            self._image_bundle_service = build_image_bundle_service(
                database_path=(
                    state_directory / "image_bundles.sqlite3"
                )
            )
            self._image_processor = (
                build_image_recommendation_orchestrator(
                    repo_root=root,
                    image_bundle_service=self._image_bundle_service,
                    consultation_runtime=self._vertical,
                )
            )
            self._image_processor._presentation_compiler = (
                disabled_compiler
            )
        self._concept_catalog = (
            ConceptPreferenceCatalog.from_projections(
                build_selection_concept_assets(root).projections
            )
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
            focus_state=FocusState(
                active_processor="general_knowledge",
                current_knowledge_topic="isolation-sentinel",
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
                snapshot=snapshot,
            )
        context = resolve_semantic_context(
            conversation_version=conversation_version,
            snapshot=snapshot,
        )
        self._failure_layer = (
            ContinuousFailureLayer.SEMANTIC_ADMISSION
        )
        compiled = compile_turn_meaning(
            message=message,
            meaning=meaning,
            context=context,
            concept_catalog=self._concept_catalog,
        )
        admission = admit_turn_meaning(
            message=message,
            meaning=meaning,
            topic=compiled.topic,
            active_topic=context.active_topic,
            concept_catalog=self._concept_catalog,
        )
        self._failure_layer = (
            ContinuousFailureLayer.IDENTITY_BINDING
        )
        resolve_product_resolution = getattr(
            self._vertical.recommendation,
            "resolve_product_resolution",
            None,
        )
        if callable(resolve_product_resolution):
            product_resolution = resolve_product_resolution(
                message=message,
                understanding=compiled,
                snapshot=snapshot,
            )
        else:
            product_resolution = ProductMentionResolution(
                bindings=tuple(
                    self._vertical.recommendation
                    .resolve_product_bindings(
                        message=message,
                        understanding=compiled,
                        snapshot=snapshot,
                    )
                )
            )
        bindings = product_resolution.bindings
        product_resolution_issue = reconcile_product_resolution_issue(
            understanding=compiled,
            issue=product_resolution.issue,
            continuity_hint=meaning.continuity_hint,
        )
        pending_reply = None
        pending_reply_kind = None
        if snapshot is not None and snapshot.pending_turn is not None:
            pending_reply = resolve_semantic_pending_reply(
                meaning=meaning,
                understanding=compiled,
                pending=snapshot.pending_turn,
            )
            pending_reply_kind = pending_reply.kind
        transition_operations = plan_route_transition_operations(
            message=message,
            understanding=compiled,
            previous=(
                snapshot.query_context
                if snapshot is not None
                else None
            ),
            continuity_hint=meaning.continuity_hint,
            resolved_product_ids=tuple(
                item.product_id for item in bindings
            ),
            product_resolution_issue=product_resolution_issue,
        )
        self._failure_layer = (
            ContinuousFailureLayer.ROUTE_SELECTION
        )
        route = route_unified_turn(
            meaning=meaning,
            understanding=compiled,
            snapshot=snapshot,
            product_bindings=(
                bindings if compiled.product_mentions else ()
            ),
            product_resolution_issue=product_resolution_issue,
            pending_reply_kind=pending_reply_kind,
            transition_operations=transition_operations,
            safety_signal=admit_safety_signal(
                message=message,
                candidates=meaning.observation_candidates,
            ),
        )
        self._failure_layer = (
            ContinuousFailureLayer.DECISION_EXECUTION
        )
        task = plan_task(
            compiled,
            resolved_product_ids=tuple(
                item.product_id for item in route.product_bindings
            ),
            product_resolution_issue=product_resolution_issue,
            message=message,
        )
        task = plan_code_owned_transitions(
            message=message,
            understanding=compiled,
            task=task,
            previous=(
                snapshot.query_context
                if snapshot is not None
                else None
            ),
        ).task_plan
        if (
            snapshot is not None
            and snapshot.pending_turn is not None
            and pending_reply is not None
            and pending_reply.kind
            in {"affirm", "correct", "supplement"}
        ):
            task = resume_pending_recommendation(
                pending=snapshot.pending_turn,
                reply=pending_reply,
            )
        if snapshot is not None and snapshot.session_profile is not None:
            task = apply_session_profile_to_task(
                task,
                snapshot.session_profile,
            )

        class FrozenUnderstanding:
            def translate(self, candidate_message, *, context):
                if candidate_message != message:
                    raise ValueError("runtime message changed")
                del context
                return meaning, compiled

        frozen = FrozenUnderstanding()
        self._vertical.unified._understanding = frozen
        self._vertical.recommendation._understanding = frozen
        turn = UserTurn(
            session_id=session_id,
            message=message,
            profile_owner=self._owner,
            conversation_version=conversation_version,
        )
        self._failure_layer = (
            ContinuousFailureLayer.DECISION_EXECUTION
        )
        events = tuple(
            iter_guide_public_events(self._vertical.unified, turn)
        )
        if not events:
            raise RuntimeError(
                "continuous runtime emitted no public events"
            )
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
        cross_session_snapshot = (
            self._vertical.conversation_state.load(
                self._isolation_sentinel.session_id
            )
        )
        return self._runtime_result(
            events=events,
            semantic_admission_passed=not any(
                item.disposition == "rejected_protocol"
                for item in admission.outcomes
            ),
            bindings=route.product_bindings,
            route=RouteExpectation(
                processor=route.processor,
                continuity=route.continuity,
                focus_source=route.focus_source,
            ),
            task_plan=task.model_dump(mode="json"),
            safety=(
                intent == "consultation_medical_escalation"
                or any(
                    event == "medical_escalation"
                    for event, _ in events
                )
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

    def _execute_image(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        meaning: TurnMeaning,
        image_fixture_ids: tuple[str, ...],
        snapshot: ConversationSnapshot | None,
    ) -> ContinuousRuntimeTurnResult:
        if (
            self._image_bundle_service is None
            or self._image_processor is None
        ):
            raise ValueError(
                "local continuous image runtime is not configured"
            )
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
        receipt = self._image_bundle_service.create(
            session_id=session_id,
            images=tuple(images),
        )
        context = resolve_semantic_context(
            conversation_version=conversation_version,
            snapshot=snapshot,
        ).model_copy(
            update={
                "image_count": len(image_fixture_ids),
                "focused_image_ordinal": (
                    1 if len(image_fixture_ids) == 1 else None
                ),
            },
            deep=True,
        )
        self._failure_layer = (
            ContinuousFailureLayer.SEMANTIC_ADMISSION
        )
        compiled = compile_turn_meaning(
            message=message,
            meaning=meaning,
            context=context,
            concept_catalog=self._concept_catalog,
        )
        admission = admit_turn_meaning(
            message=message,
            meaning=meaning,
            topic=compiled.topic,
            active_topic=context.active_topic,
            concept_catalog=self._concept_catalog,
        )

        class FrozenUnderstanding:
            def translate(self, candidate_message, *, context):
                if candidate_message != message:
                    raise ValueError("runtime message changed")
                del context
                return meaning, compiled

        self._vertical.unified._understanding = FrozenUnderstanding()
        turn = UserTurn(
            session_id=session_id,
            message=message,
            profile_owner=self._owner,
            image_bundle_id=receipt.bundle_id,
            image_bundle_version=receipt.version,
            image_bundle_token=receipt.owner_token,
            conversation_version=conversation_version,
        )

        class ImageFlow:
            def __init__(self, unified, image_processor) -> None:
                self._unified = unified
                self._image_processor = image_processor
                self._conversation_state = getattr(
                    image_processor,
                    "_conversation_state",
                    None,
                )

            def stream(self, image_turn):
                yield from self._unified.stream_image(
                    image_turn,
                    image_processor=self._image_processor,
                )

        self._failure_layer = (
            ContinuousFailureLayer.IDENTITY_BINDING
        )
        events = tuple(iter_guide_public_events(
            ImageFlow(
                self._vertical.unified,
                self._image_processor,
            ),
            turn,
        ))
        if not events:
            raise RuntimeError(
                "continuous image runtime emitted no public events"
            )
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
        confirmed_images = tuple(
            ConfirmedImageProductRef(
                image_ordinal=ordinal,
                product_id=int(observation["confirmed_product_id"]),
            )
            for ordinal, observation in enumerate(
                (
                    data.get("observation")
                    for event, data in events
                    if event == "image_observation"
                ),
                start=1,
            )
            if (
                isinstance(observation, dict)
                and observation.get("identity_state") == "confirmed"
                and type(observation.get("confirmed_product_id"))
                is int
            )
        )
        if confirmed_images:
            actual_route = route_unified_turn(
                meaning=meaning,
                understanding=compiled,
                snapshot=snapshot,
                current_image_products=confirmed_images,
                safety_signal=admit_safety_signal(
                    message=message,
                    candidates=meaning.observation_candidates,
                ),
            )
            processor = actual_route.processor
            route_bindings = actual_route.product_bindings
            route_expectation = RouteExpectation(
                processor=actual_route.processor,
                continuity=actual_route.continuity,
                focus_source=actual_route.focus_source,
            )
        else:
            processor = "clarification"
            route_bindings = ()
            route_expectation = RouteExpectation(
                processor="clarification",
                continuity=(
                    "replace_task"
                    if conversation_version == 0
                    or meaning.continuity_hint == "new_task"
                    else "continue"
                ),
                focus_source="none",
            )
        task_plan: dict[str, object] = {}
        if processor == "product_knowledge" and card_ids:
            task_plan = {
                "mode": "suitability",
                "product_ids": list(card_ids),
            }
        elif processor == "recommendation":
            task_plan = {"mode": "recommend"}
        elif processor == "comparison":
            task_plan = {
                "mode": "comparison",
                "product_ids": list(card_ids),
            }
        elif processor == "clarification":
            task_plan = {"mode": "clarify"}
        cross_session_snapshot = (
            self._vertical.conversation_state.load(
                self._isolation_sentinel.session_id
            )
        )
        return self._runtime_result(
            events=events,
            semantic_admission_passed=not any(
                item.disposition == "rejected_protocol"
                for item in admission.outcomes
            ),
            bindings=route_bindings,
            route=route_expectation,
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
        try:
            return ContinuousRuntimeTurnResult(
                events=events,
                delivery_event=events[-1],
                **values,
            )
        except BaseException:
            if events:
                discard_http_event_delivery(events[-1])
            raise

    @staticmethod
    def commit(terminal_event) -> None:
        commit_http_event_delivery(terminal_event)

    @staticmethod
    def discard(terminal_event) -> None:
        discard_http_event_delivery(terminal_event)

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


__all__ = [
    "ContinuousLocalRuntime",
    "build_local_continuous_runtime",
]
