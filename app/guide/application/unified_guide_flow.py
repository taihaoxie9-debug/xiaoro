from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from app.guide.application.contracts import UserTurn
from app.guide.application.pending_turn import (
    resolve_semantic_pending_reply,
)
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStatePort,
)
from app.guide.intent.transition_planning import (
    plan_route_transition_operations,
)
from app.guide.intent.unified_turn_router import (
    reconcile_product_resolution_issue,
    route_unified_turn,
)
from app.guide.presentation.sse_events import SseEvent
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
)
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.contracts import (
    StructuredUnderstanding,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.safety_admission import (
    admit_safety_signal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


class UnifiedUnderstandingPort(Protocol):
    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> tuple[TurnMeaning, StructuredUnderstanding]: ...


class UnifiedUnderstandingAdapter:
    def __init__(self, understanding) -> None:
        if not callable(getattr(understanding, "understand", None)):
            raise TypeError("understanding must expose understand")
        self._understanding = understanding

    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> tuple[TurnMeaning, StructuredUnderstanding]:
        translate = getattr(self._understanding, "translate", None)
        if callable(translate):
            return translate(message, context=context)
        compiled = self._understanding.understand(
            message,
            context=context,
        )
        if (
            compiled.goal.value == "clarification"
            and compiled.topic is not None
            and compiled.uncertainties
            and all(
                item.code == "missing_category"
                for item in compiled.uncertainties
            )
        ):
            compiled = compiled.model_copy(
                update={
                    "goal": UnderstandingGoal.RECOMMENDATION,
                    "uncertainties": [],
                    "confidence": 1.0,
                },
                deep=True,
            )
        return _meaning_from_compilation(
            compiled,
            message=message,
            context=context,
        ), compiled


class UnifiedGuideFlow:
    def __init__(
        self,
        *,
        understanding: UnifiedUnderstandingPort,
        text_processor,
        consultation_processor,
        conversation_state: ConversationStatePort,
    ) -> None:
        if not callable(getattr(understanding, "translate", None)):
            raise TypeError("understanding must expose translate")
        if not callable(
            getattr(text_processor, "stream_understanding", None)
        ):
            raise TypeError(
                "text processor must expose stream_understanding"
            )
        if not callable(
            getattr(consultation_processor, "stream", None)
        ):
            raise TypeError("consultation processor must expose stream")
        if not callable(
            getattr(consultation_processor, "stream_meaning", None)
        ):
            raise TypeError(
                "consultation processor must expose stream_meaning"
            )
        self._understanding = understanding
        self._text_processor = text_processor
        self._consultation_processor = consultation_processor
        self._conversation_state = conversation_state

    def stream(self, turn: UserTurn) -> Iterator[SseEvent]:
        if type(turn) is not UserTurn:
            raise TypeError("turn must be an exact UserTurn")
        snapshot = self._conversation_state.load(turn.session_id)
        self._validate_owner(snapshot, turn)
        meaning, understanding = self._understanding.translate(
            turn.message,
            context=resolve_semantic_context(
                conversation_version=turn.conversation_version,
                snapshot=snapshot,
            ),
        )
        if type(meaning) is not TurnMeaning:
            raise TypeError("translator must return TurnMeaning")
        if type(understanding) is not StructuredUnderstanding:
            raise TypeError(
                "translator must return StructuredUnderstanding"
            )

        resolve_product_resolution = getattr(
            self._text_processor,
            "resolve_product_resolution",
            None,
        )
        if callable(resolve_product_resolution):
            product_resolution = resolve_product_resolution(
                message=turn.message,
                understanding=understanding,
                snapshot=snapshot,
            )
        else:
            product_resolution = ProductMentionResolution(
                bindings=tuple(
                    self._text_processor.resolve_product_bindings(
                        message=turn.message,
                        understanding=understanding,
                        snapshot=snapshot,
                    )
                )
            )
        product_resolution_issue = reconcile_product_resolution_issue(
            understanding=understanding,
            issue=product_resolution.issue,
            continuity_hint=meaning.continuity_hint,
        )
        product_bindings = product_resolution.bindings
        router_product_bindings = (
            product_bindings
            if understanding.product_mentions
            else ()
        )
        pending_reply = None
        if snapshot is not None and snapshot.pending_turn is not None:
            pending_reply = resolve_semantic_pending_reply(
                meaning=meaning,
                understanding=understanding,
                pending=snapshot.pending_turn,
            )
        pending_reply_kind = (
            pending_reply.kind
            if pending_reply is not None
            else None
        )
        route = route_unified_turn(
            meaning=meaning,
            understanding=understanding,
            snapshot=snapshot,
            product_bindings=router_product_bindings,
            product_resolution_issue=product_resolution_issue,
            pending_reply_kind=pending_reply_kind,
            transition_operations=plan_route_transition_operations(
                message=turn.message,
                understanding=understanding,
                previous=(
                    snapshot.query_context
                    if snapshot is not None
                    else None
                ),
                continuity_hint=meaning.continuity_hint,
                resolved_product_ids=tuple(
                    item.product_id
                    for item in product_bindings
                ),
                product_resolution_issue=product_resolution_issue,
            ),
            safety_signal=admit_safety_signal(
                message=turn.message,
                candidates=meaning.observation_candidates,
            ),
        )
        if route.processor == "clarification":
            claims = getattr(
                self._consultation_processor,
                "claims",
                None,
            )
            if callable(claims) and claims(turn):
                yield from self._stream_consultation(
                    turn,
                    meaning=meaning,
                )
                return

        if (
            snapshot is not None
            and snapshot.pending_turn is not None
            and pending_reply is not None
            and meaning.continuity_hint != "new_task"
        ):
            stream_pending_reply = getattr(
                self._text_processor,
                "stream_pending_reply",
                None,
            )
            if not callable(stream_pending_reply):
                raise TypeError(
                    "text processor must expose stream_pending_reply"
                )
            yield from stream_pending_reply(
                turn,
                reply=pending_reply,
            )
            return
        if route.processor in {
            "consultation",
            "safety_escalation",
        }:
            yield from self._stream_consultation(
                turn,
                meaning=meaning,
            )
            return
        stream_kwargs = {
            "understanding": understanding,
            "route_decision": route,
            "product_bindings": route.product_bindings,
        }
        if product_resolution_issue is not None:
            stream_kwargs["product_resolution_issue"] = (
                product_resolution_issue
            )
        yield from self._text_processor.stream_understanding(
            turn,
            **stream_kwargs,
        )

    def stream_image(
        self,
        turn: UserTurn,
        *,
        image_processor,
    ) -> Iterator[SseEvent]:
        if type(turn) is not UserTurn:
            raise TypeError("turn must be an exact UserTurn")
        if not callable(
            getattr(image_processor, "stream_understanding", None)
        ):
            raise TypeError(
                "image processor must expose stream_understanding"
            )
        semantic_image_count = getattr(
            image_processor,
            "semantic_image_count",
            None,
        )
        if not callable(semantic_image_count):
            raise TypeError(
                "image processor must expose semantic_image_count"
            )
        snapshot = self._conversation_state.load(turn.session_id)
        self._validate_owner(snapshot, turn)
        image_count = semantic_image_count(turn)
        if type(image_count) is not int or not 0 <= image_count <= 4:
            raise ValueError(
                "semantic image count must be between zero and four"
            )
        context = resolve_semantic_context(
            conversation_version=turn.conversation_version,
            snapshot=snapshot,
        ).model_copy(
            update={
                "image_count": image_count,
                "focused_image_ordinal": (
                    1 if image_count == 1 else None
                ),
            },
            deep=True,
        )
        meaning, understanding = self._understanding.translate(
            turn.message,
            context=context,
        )
        if type(meaning) is not TurnMeaning:
            raise TypeError("translator must return TurnMeaning")
        if type(understanding) is not StructuredUnderstanding:
            raise TypeError(
                "translator must return StructuredUnderstanding"
            )
        yield from image_processor.stream_understanding(
            turn,
            meaning=meaning,
            understanding=understanding,
            snapshot=snapshot,
        )

    def _stream_consultation(
        self,
        turn: UserTurn,
        *,
        meaning: TurnMeaning,
    ) -> Iterator[SseEvent]:
        has_dynamic_session = getattr(
            self._consultation_processor,
            "has_dynamic_session",
            None,
        )
        if (
            (
                callable(has_dynamic_session)
                and has_dynamic_session(turn)
            )
            or meaning.observation_candidates
            or meaning.consultation_hypothesis is not None
            or meaning.next_observation_gap is not None
        ):
            yield from self._consultation_processor.stream_meaning(
                turn,
                meaning=meaning,
            )
            return
        yield from self._consultation_processor.stream(turn)

    @staticmethod
    def _validate_owner(
        snapshot: ConversationSnapshot | None,
        turn: UserTurn,
    ) -> None:
        if (
            snapshot is not None
            and snapshot.profile_owner != turn.profile_owner
        ):
            raise ConversationStateConflict(turn.session_id)


def _meaning_from_compilation(
    understanding: StructuredUnderstanding,
    *,
    message: str,
    context: SemanticContext,
) -> TurnMeaning:
    operation_hint = understanding.goal.value
    if (
        operation_hint == "clarification"
        and understanding.topic is not None
    ):
        operation_hint = "recommendation"
    return TurnMeaning(
        operation_hint=operation_hint,
        topic_hint=(
            understanding.topic.value
            if understanding.topic is not None
            else None
        ),
        continuity_hint=(
            "new_task"
            if (
                context.conversation_version == 0
                or (
                    operation_hint == "recommendation"
                    and understanding.topic is not None
                    and understanding.topic is not context.active_topic
                )
            )
            else "unknown"
        ),
        subject_scope_hint="unknown",
        reference_mentions=(),
        product_mentions=(),
        budget_candidates=(),
        observation_candidates=(),
        preference_candidates=(),
        relative_candidates=(),
        consultation_hypothesis=None,
        next_observation_gap=None,
        question_meaning=(
            understanding.question_meaning or message.strip()
        ),
        safety_language=(
            "safety"
            if understanding.safety_sensitive
            else "unknown"
        ),
    )


__all__ = [
    "UnifiedGuideFlow",
    "UnifiedUnderstandingAdapter",
    "UnifiedUnderstandingPort",
]
