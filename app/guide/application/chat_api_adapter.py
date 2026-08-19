from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from enum import Enum
import json
from threading import Lock, local
from typing import Any

from pydantic import BaseModel, TypeAdapter

from app.guide.application.contracts import UserTurn
from app.guide.decision.contracts import WinnerStatus
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    PendingTurn,
)
from app.guide.feedback.focus_state import (
    ConfirmedImageProductRef,
    FocusState,
)
from app.guide.feedback.ports import ConversationStatePort
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.presentation.contracts import ProductCard
from app.guide.presentation.copywriter_contracts import (
    PresentationContractData,
)
from app.guide.presentation.sse_events import (
    AnswerContractEvent,
    CardDisplayContractEvent,
    CitationsEvent,
    ClarifyEvent,
    ConsultationObservationEvent,
    ConsultationProvisionalEvent,
    DecisionProcessEvent,
    EndEvent,
    ErrorEvent,
    GeneralKnowledgeData,
    GeneralKnowledgeEvent,
    ImageComparisonData,
    ImageObservationEvent,
    ImageSuitabilityData,
    IntentEvent,
    MedicalEscalationEvent,
    MessageEvent,
    MerchantClaimsEvent,
    PitfallsEvent,
    PresentationContractEvent,
    ProductEvidenceEvent,
    ProfileConfirmationEvent,
    ProductsEvent,
    ReviewEvidenceEvent,
    ScenarioEvidenceEvent,
    StageEvent,
    StartEvent,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.semantic_contracts import ClarificationCode


class ChatOwner(str, Enum):
    GUIDE_TEXT = "guide_text"
    GUIDE_CONSULTATION = "guide_consultation"
    GUIDE_IMAGE = "guide_image"


class GuidePublicEventError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


class _PublicEventStateTransaction:
    def __init__(
        self,
        state: PublicEventCommitConversationState,
    ) -> None:
        self._state = state
        self.pending: tuple[ConversationSnapshot, int] | None = None
        self.staged_saves: list[
            tuple[ConversationSnapshot, int]
        ] = []
        self._committed = False
        self._commit_lock = Lock()

    def commit(self) -> None:
        with self._commit_lock:
            if self.pending is None or self._committed:
                return
            for index, (snapshot, expected_version) in enumerate(
                self.staged_saves
            ):
                if index == len(self.staged_saves) - 1:
                    snapshot, expected_version = self.pending
                self._state._delegate.save(
                    snapshot,
                    expected_version=expected_version,
                )
            self._committed = True


class _PublicEventDelivery:
    def __init__(
        self,
        transaction: _PublicEventStateTransaction,
        release,
    ) -> None:
        self._transaction = transaction
        self._release = release
        self._lock = Lock()
        self._finished = False
        self.exposed = False

    def commit(self) -> None:
        with self._lock:
            if self._finished:
                return
            try:
                self._transaction.commit()
            finally:
                self._finished = True
                self._release()

    def discard(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
            self._release()


class _PublicHttpEvent(tuple):
    def __new__(
        cls,
        event: str,
        data: dict[str, Any],
        *,
        delivery: _PublicEventDelivery | None = None,
        clarification_code: ClarificationCode | None = None,
        pending_turn: PendingTurn | None = None,
    ):
        instance = super().__new__(cls, (event, data))
        instance._delivery = delivery
        instance._clarification_code = clarification_code
        instance._pending_turn = pending_turn
        return instance


def commit_http_event_delivery(event: object) -> None:
    delivery = getattr(event, "_delivery", None)
    if isinstance(delivery, _PublicEventDelivery):
        delivery.commit()


def discard_http_event_delivery(event: object) -> None:
    delivery = getattr(event, "_delivery", None)
    if isinstance(delivery, _PublicEventDelivery):
        delivery.discard()


class PublicEventCommitConversationState:
    """Defer a turn's durable snapshot until its public events validate."""

    def __init__(self, delegate: ConversationStatePort) -> None:
        self._delegate = delegate
        self._local = local()
        self._delivery_locks = tuple(Lock() for _ in range(64))

    def load(self, session_id: str) -> ConversationSnapshot | None:
        transaction = self._active_transaction()
        if (
            transaction is not None
            and transaction.pending is not None
            and transaction.pending[0].session_id == session_id
        ):
            return transaction.pending[0].model_copy(deep=True)
        return self._delegate.load(session_id)

    def save(
        self,
        snapshot: ConversationSnapshot,
        *,
        expected_version: int,
    ) -> ConversationSnapshot:
        transaction = self._active_transaction()
        if transaction is None:
            return self._delegate.save(
                snapshot,
                expected_version=expected_version,
            )
        if transaction.pending is not None:
            previous, _ = transaction.pending
            if (
                previous.session_id != snapshot.session_id
                or previous.version != expected_version
            ):
                raise RuntimeError(
                    "public event transaction save chain is invalid"
                )
        staged = snapshot.model_copy(deep=True)
        transaction.pending = (staged, expected_version)
        transaction.staged_saves.append(
            (staged, expected_version)
        )
        return staged.model_copy(deep=True)

    def delete(
        self,
        session_id: str,
        *,
        expected_owner: ProfileOwnerRef | None,
    ) -> bool:
        if self._active_transaction() is not None:
            raise RuntimeError(
                "cannot delete conversation during event transaction"
            )
        return self._delegate.delete(
            session_id,
            expected_owner=expected_owner,
        )

    @contextmanager
    def public_event_transaction(
        self,
    ) -> Iterator[_PublicEventStateTransaction]:
        if self._active_transaction() is not None:
            raise RuntimeError("nested public event transaction")
        transaction = _PublicEventStateTransaction(self)
        self._local.transaction = transaction
        try:
            yield transaction
        finally:
            self._local.transaction = None

    @contextmanager
    def public_event_delivery(self, session_id: str) -> Iterator[None]:
        release = self.acquire_public_event_delivery(session_id)
        try:
            yield
        finally:
            release()

    def acquire_public_event_delivery(self, session_id: str):
        if not session_id:
            raise ValueError("session_id must not be empty")
        lock = self._delivery_locks[
            hash(session_id) % len(self._delivery_locks)
        ]
        lock.acquire()
        released = False
        release_lock = Lock()

        def release() -> None:
            nonlocal released
            with release_lock:
                if released:
                    return
                released = True
            lock.release()

        return release

    def _active_transaction(
        self,
    ) -> _PublicEventStateTransaction | None:
        return getattr(self._local, "transaction", None)


_DECISION_WINNER_STATUSES = frozenset(
    status.value for status in WinnerStatus
)
_CONSULTATION_EVENT_BY_INTENT = {
    "consultation_entry": "consultation_observation",
    "consultation_answer": "consultation_observation",
    "consultation_clarification": "consultation_observation",
    "consultation_provisional": "consultation_provisional",
    "consultation_confirmation": "profile_confirmation",
    "consultation_rejection": "consultation_observation",
    "consultation_medical_escalation": "medical_escalation",
}
_SCOPE_NOTICE = (
    "当前支持护肤、防晒、底妆、彩妆、洁面/卸妆和香水导购。"
    "请明确品类、预算、肤质，或指出要比较的商品。"
)
_PRESENTATION_ADAPTER = TypeAdapter(PresentationContractData)


def classify_chat_owner(
    *,
    message: str,
    conversation_version: int,
    has_image_bundle_reference: bool,
    has_legacy_image_payload: bool,
    consultation_claimed: bool = False,
    guide_conversation_claimed: bool = False,
) -> ChatOwner:
    if has_image_bundle_reference:
        return ChatOwner.GUIDE_IMAGE
    if has_legacy_image_payload:
        return ChatOwner.GUIDE_TEXT
    if consultation_claimed:
        return ChatOwner.GUIDE_CONSULTATION
    del message, conversation_version, guide_conversation_claimed
    return ChatOwner.GUIDE_TEXT


def iter_guide_public_events(
    orchestrator,
    turn: UserTurn,
) -> Iterator[tuple[str, dict[str, Any]]]:
    conversation_state = getattr(
        orchestrator,
        "_conversation_state",
        None,
    )
    if isinstance(
        conversation_state,
        PublicEventCommitConversationState,
    ):
        guide_events = iter(orchestrator.stream(turn))
        delivery: _PublicEventDelivery | None = None
        release_delivery = None
        try:
            try:
                first_event = _adapt_guide_event(next(guide_events))
                _validate_guide_start_event(
                    first_event,
                    session_id=turn.session_id,
                )
            except GuidePublicEventError as error:
                yield "start", {"session_id": turn.session_id}
                yield "error", {
                    "error": error.code,
                    "message": error.message,
                }
                return
            except Exception:
                yield "start", {"session_id": turn.session_id}
                yield "error", {
                    "error": "GUIDE_INTERNAL_ERROR",
                    "message": "推荐暂时不可用，请稍后重试。",
                }
                return

            yield first_event
            release_delivery = (
                conversation_state.acquire_public_event_delivery(
                    turn.session_id
                )
            )
            try:
                with (
                    conversation_state.public_event_transaction()
                ) as transaction:
                    current = conversation_state.load(turn.session_id)
                    public_events = [
                        first_event,
                        *[
                            _adapt_guide_event(event)
                            for event in guide_events
                        ],
                    ]
                    _validate_guide_event_sequence(
                        public_events,
                        session_id=turn.session_id,
                    )
                    _stage_public_conversation_state(
                        conversation_state,
                        transaction,
                        turn=turn,
                        current=current,
                        public_events=public_events,
                    )
            except GuidePublicEventError as error:
                yield "error", {
                    "error": error.code,
                    "message": error.message,
                }
                return
            except Exception:
                yield "error", {
                    "error": "GUIDE_INTERNAL_ERROR",
                    "message": "推荐暂时不可用，请稍后重试。",
                }
                return
            delivery = _PublicEventDelivery(
                transaction,
                release_delivery,
            )
            release_delivery = None
            for public_event in public_events[1:]:
                if public_event[0] == "end":
                    delivery.exposed = True
                    yield _PublicHttpEvent(
                        public_event[0],
                        public_event[1],
                        delivery=delivery,
                    )
                    continue
                yield public_event
            return
        finally:
            if release_delivery is not None:
                release_delivery()
            if delivery is not None and not delivery.exposed:
                delivery.discard()
            close = getattr(guide_events, "close", None)
            if close is not None:
                close()

    for event in orchestrator.stream(turn):
        yield _adapt_guide_event(event)


def _stage_public_conversation_state(
    conversation_state: PublicEventCommitConversationState,
    transaction: _PublicEventStateTransaction,
    *,
    turn: UserTurn,
    current: ConversationSnapshot | None,
    public_events: list[tuple[str, dict[str, Any]]],
) -> None:
    intent = next(
        (
            data.get("intent")
            for event, data in public_events
            if event == "intent"
        ),
        None,
    )
    if intent == "clarify":
        _stage_clarification(
            conversation_state,
            turn=turn,
            current=current,
            public_events=public_events,
        )
        return
    if transaction.pending is None:
        return
    snapshot, expected_version = transaction.pending
    if (
        snapshot.clarification is not None
        or snapshot.pending_turn is not None
    ):
        snapshot = snapshot.model_copy(
            update={
                "clarification": None,
                "pending_turn": None,
            },
            deep=True,
        )
    snapshot = snapshot.model_copy(
        update={
            "focus_state": _focus_state_from_public_events(
                turn=turn,
                current=current,
                replacement=snapshot,
                public_events=public_events,
                intent=str(intent),
            )
        },
        deep=True,
    )
    transaction.pending = (snapshot, expected_version)


def _focus_state_from_public_events(
    *,
    turn: UserTurn,
    current: ConversationSnapshot | None,
    replacement: ConversationSnapshot,
    public_events: list[tuple[str, dict[str, Any]]],
    intent: str,
) -> FocusState:
    previous = (
        current.focus_state
        if current is not None and current.focus_state is not None
        else FocusState()
    )
    product_ids = tuple(
        int(item["id"])
        for event, data in public_events
        if event == "products"
        for item in data.get("products", ())
        if isinstance(item, dict)
        and isinstance(item.get("id"), int)
        and not isinstance(item.get("id"), bool)
    )
    image_refs = tuple(
        ConfirmedImageProductRef(
            image_ordinal=index,
            product_id=int(observation["confirmed_product_id"]),
        )
        for index, observation in enumerate(
            (
                data.get("observation")
                for event, data in public_events
                if event == "image_observation"
            ),
            start=1,
        )
        if isinstance(observation, dict)
        and isinstance(observation.get("confirmed_product_id"), int)
        and not isinstance(
            observation.get("confirmed_product_id"),
            bool,
        )
    )
    confirmed_images = image_refs or previous.confirmed_image_products
    has_general_knowledge = any(
        event == "general_knowledge"
        for event, _ in public_events
    )
    processor = {
        "recommend": "recommendation",
        "revise": "recommendation",
        "comparison": "comparison",
        "suitability": "product_knowledge",
        "knowledge": (
            "general_knowledge"
            if has_general_knowledge
            else "product_knowledge"
        ),
        "followup": (
            "general_knowledge"
            if has_general_knowledge
            else "product_knowledge"
        ),
        "image_identity": "image_identity",
        "image_recommend": "recommendation",
        "image_suitability": "product_knowledge",
        "image_compare": "comparison",
        "consultation_entry": "consultation",
        "consultation_answer": "consultation",
        "consultation_clarification": "consultation",
        "consultation_provisional": "consultation",
        "consultation_confirmation": "consultation",
        "consultation_rejection": "consultation",
        "consultation_medical_escalation": "safety_escalation",
    }.get(intent, previous.active_processor)
    current_product_id = previous.current_product_id
    if processor == "image_identity":
        current_product_id = (
            product_ids[0] if len(product_ids) == 1 else None
        )
    elif processor == "product_knowledge":
        current_product_id = (
            product_ids[0] if len(product_ids) == 1 else current_product_id
        )
    elif processor in {"recommendation", "comparison"}:
        current_product_id = None

    allowed_product_ids = {
        item.product_id for item in replacement.candidates
    } | {
        item.product_id for item in confirmed_images
    }
    if current_product_id not in allowed_product_ids:
        current_product_id = None
    knowledge_topic = previous.current_knowledge_topic
    if has_general_knowledge:
        knowledge_topic = next(
            (
                str(data.get("query"))
                for event, data in public_events
                if event == "general_knowledge"
                and data.get("query")
            ),
            turn.message.strip(),
        )
    return FocusState(
        active_processor=processor,
        current_product_id=current_product_id,
        confirmed_image_products=confirmed_images,
        current_knowledge_topic=knowledge_topic,
        last_question_meaning=turn.message.strip(),
    )


def _stage_clarification(
    conversation_state: PublicEventCommitConversationState,
    *,
    turn: UserTurn,
    current: ConversationSnapshot | None,
    public_events: list[tuple[str, dict[str, Any]]],
) -> None:
    current_version = current.version if current is not None else 0
    gap = _typed_clarification_code_from_public_events(public_events)
    if turn.conversation_version != current_version:
        return
    previous = (
        current.clarification
        if current is not None
        else None
    )
    same_gap = previous is not None and previous.gap is gap
    attempts = (
        min(previous.attempts + 1, 2)
        if same_gap
        else 1
    )
    progress = ClarificationProgress(gap=gap, attempts=attempts)
    pending_turn = _typed_pending_turn_from_public_events(
        public_events
    )
    if pending_turn is not None:
        if pending_turn.gap is not gap:
            _invalid_guide_events()
        pending_turn = pending_turn.model_copy(
            update={"attempts": attempts},
            deep=True,
        )
    if current is None:
        replacement = ConversationSnapshot(
            session_id=turn.session_id,
            version=1,
            profile_owner=turn.profile_owner,
            clarification=progress,
            pending_turn=pending_turn,
        )
    else:
        replacement = current.model_copy(
            update={
                "version": current.version + 1,
                "clarification": progress,
                "pending_turn": pending_turn,
            },
            deep=True,
        )
    saved = conversation_state.save(
        replacement,
        expected_version=current_version,
    )
    end_data = next(
        data for event, data in public_events if event == "end"
    )
    end_data["conversation_version"] = saved.version
    if same_gap and previous.attempts == 2:
        message_data = next(
            data for event, data in public_events if event == "message"
        )
        message_data["content"] = _SCOPE_NOTICE


def _typed_clarification_code_from_public_events(
    public_events: list[tuple[str, dict[str, Any]]],
) -> ClarificationCode:
    codes = [
        getattr(public_event, "_clarification_code", None)
        for public_event in public_events
        if (
            public_event[0] == "message"
            and public_event[1].get("clarify") is True
        )
    ]
    if len(codes) != 1 or not isinstance(codes[0], ClarificationCode):
        _invalid_guide_events()
    return codes[0]


def _typed_pending_turn_from_public_events(
    public_events: list[tuple[str, dict[str, Any]]],
) -> PendingTurn | None:
    values = [
        getattr(public_event, "_pending_turn", None)
        for public_event in public_events
        if (
            public_event[0] == "message"
            and public_event[1].get("clarify") is True
        )
    ]
    if len(values) != 1:
        _invalid_guide_events()
    value = values[0]
    if value is not None and not isinstance(value, PendingTurn):
        _invalid_guide_events()
    return value


def _adapt_guide_event(event) -> tuple[str, dict[str, Any]]:
    if isinstance(event, ClarifyEvent):
        return _PublicHttpEvent(
            "message",
            {
                "content": event.data.question,
                "done": False,
                "clarify": True,
            },
            clarification_code=event.data.clarification_code,
            pending_turn=event.data.pending_turn,
        )
    return event.event, _to_legacy_data(event)


def _validate_guide_start_event(
    event: tuple[str, dict[str, Any]],
    *,
    session_id: str,
) -> None:
    if (
        event[0] != "start"
        or event[1].get("session_id") != session_id
    ):
        _invalid_guide_events()


def collect_guide_chat_response(
    events: Iterable[tuple[str, dict[str, Any]]],
    *,
    session_id: str,
    conversation_version: int,
) -> dict[str, Any]:
    event_list = [
        (event_name, dict(event_data))
        for event_name, event_data in events
    ]
    _validate_guide_event_sequence(event_list, session_id=session_id)

    text_parts: list[str] = []
    products: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    image_observations: list[dict[str, Any]] = []
    intent_data: dict[str, Any] | None = None
    decision_process: dict[str, Any] | None = None
    comparison_data: dict[str, Any] | None = None
    suitability_data: dict[str, Any] | None = None
    answer_contract: dict[str, Any] | None = None
    card_display_contract: dict[str, Any] | None = None
    scenario_evidence: dict[str, Any] | None = None
    review_evidence: dict[str, Any] | None = None
    general_knowledge: dict[str, Any] | None = None
    presentation_contract: dict[str, Any] | None = None
    pitfalls: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    consultation_payloads: dict[str, dict[str, Any]] = {}
    current_version = conversation_version

    for event_name, event_data in event_list:
        if event_name == "message":
            content = event_data.get("content") or ""
            if content:
                text_parts.append(content)
        elif event_name == "products":
            products = list(event_data.get("products") or [])
        elif event_name == "intent":
            intent_data = event_data
        elif event_name == "decision_process":
            decision_process = event_data.get("decision_process")
            comparison_data = event_data.get("comparison_data")
            suitability_data = event_data.get("suitability_data")
        elif event_name == "answer_contract":
            answer_contract = event_data.get("answer_contract")
        elif event_name == "card_display_contract":
            card_display_contract = event_data
        elif event_name == "scenario_evidence":
            scenario_evidence = event_data
        elif event_name == "review_evidence":
            review_evidence = event_data
        elif event_name == "general_knowledge":
            general_knowledge = event_data
        elif event_name == "presentation_contract":
            presentation_contract = event_data
        elif event_name == "pitfalls":
            pitfalls = list(event_data.get("pitfalls") or [])
        elif event_name == "citations":
            citations = list(event_data.get("citations") or [])
        elif event_name == "image_observation":
            observation = event_data.get("observation")
            if isinstance(observation, dict):
                image_observations.append(observation)
        elif event_name in _CONSULTATION_EVENT_BY_INTENT.values():
            consultation_payloads[event_name] = event_data
        elif event_name == "end":
            current_version = event_data.get(
                "conversation_version",
                current_version,
            )
        elif event_name == "error":
            raise GuidePublicEventError(
                code=str(event_data.get("error") or ""),
                message=str(event_data.get("message") or ""),
            )

    if image_observations:
        metadata["image_observation"] = image_observations[-1]
        metadata["image_observations"] = image_observations
    metadata["answer_contract"] = answer_contract
    metadata["presentation_contract"] = presentation_contract
    metadata["conversation_version"] = current_version
    return {
        "response": "".join(text_parts),
        "intent": intent_data or {},
        "products": products,
        "comparison_data": comparison_data,
        "suitability_data": suitability_data,
        "decision_process": decision_process,
        "answer_contract": answer_contract,
        "card_display_contract": card_display_contract,
        "scenario_evidence": scenario_evidence,
        "review_evidence": review_evidence,
        "general_knowledge": general_knowledge,
        "presentation_contract": presentation_contract,
        "citations": citations,
        "pitfalls": pitfalls,
        "conversation_version": current_version,
        "metadata": metadata,
        "session_id": session_id,
        **consultation_payloads,
    }


def _validate_guide_event_sequence(
    events: list[tuple[str, dict[str, Any]]],
    *,
    session_id: str,
) -> None:
    names = [name for name, _ in events]
    if (
        not events
        or names[0] != "start"
        or names.count("start") != 1
        or events[0][1].get("session_id") != session_id
    ):
        _invalid_guide_events()

    terminal_positions = [
        index
        for index, name in enumerate(names)
        if name in {"end", "error"}
    ]
    if terminal_positions != [len(events) - 1]:
        _invalid_guide_events()
    if names[-1] == "error":
        if (
            names.count("error") != 1
            or "end" in names
            or "presentation_contract" in names
        ):
            _invalid_guide_events()
        return
    if names.count("end") != 1 or "error" in names:
        _invalid_guide_events()

    intent_position = _single_event_position(names, "intent")
    message_positions = [
        index for index, name in enumerate(names) if name == "message"
    ]
    if (
        intent_position is None
        or not message_positions
        or intent_position >= message_positions[0]
        or message_positions[-1] >= len(events) - 1
    ):
        _invalid_guide_events()
    intent = events[intent_position][1].get("intent")
    if not isinstance(intent, str) or not intent:
        _invalid_guide_events()

    if intent == "clarify":
        if any(
            names.count(name)
            for name in (
                "answer_contract",
                "card_display_contract",
                "products",
                "decision_process",
                "presentation_contract",
            )
        ):
            _invalid_guide_events()
        return

    presentation_position = _single_event_position(
        names,
        "presentation_contract",
    )
    if (
        presentation_position is None
        or not (
            intent_position
            < presentation_position
            < message_positions[0]
        )
    ):
        _invalid_guide_events()
    presentation = _typed_presentation(
        events[presentation_position][1],
        intent=str(intent),
        names=names,
    )

    if intent in {"knowledge", "followup"} and (
        "general_knowledge" in names
    ):
        knowledge_position = _single_event_position(
            names,
            "general_knowledge",
        )
        if (
            knowledge_position is None
            or not (
                intent_position
                < knowledge_position
                < presentation_position
                < message_positions[0]
            )
            or any(
                names.count(name)
                for name in {
                    "answer_contract",
                    "card_display_contract",
                    "products",
                    "decision_process",
                    "product_evidence",
                }
            )
        ):
            _invalid_guide_events()
        try:
            GeneralKnowledgeData.model_validate(
                events[knowledge_position][1],
                strict=True,
            )
        except ValueError:
            _invalid_guide_events()
        _validate_presentation_authority(
            presentation,
            visible_ids=[],
            card_display=None,
        )
        return
    if intent in _CONSULTATION_EVENT_BY_INTENT:
        _validate_consultation_zero_card_sequence(
            events=events,
            names=names,
            intent=str(intent),
            intent_position=intent_position,
            presentation=presentation,
            presentation_position=presentation_position,
            message_position=message_positions[0],
        )
        return

    answer_position = _single_event_position(names, "answer_contract")
    card_position = _single_event_position(names, "card_display_contract")
    products_position = _single_event_position(names, "products")
    if (
        answer_position is None
        or card_position is None
        or products_position is None
        or not (
            intent_position
            < answer_position
            < card_position
            < products_position
            < presentation_position
            < message_positions[0]
        )
    ):
        _invalid_guide_events()

    answer = events[answer_position][1].get("answer_contract")
    answer_event = events[answer_position][1]
    card_display = events[card_position][1]
    products_payload = events[products_position][1]
    products = products_payload.get("products")
    if (
        not isinstance(answer, dict)
        or not isinstance(card_display, dict)
        or not isinstance(products, list)
    ):
        _invalid_guide_events()

    product_ids = _ordered_ids(products, key="id")
    if any(
        product.get("product_id") != product_id
        for product, product_id in zip(products, product_ids, strict=True)
    ):
        _invalid_guide_events()
    visible_ids = _ordered_positive_ids(
        card_display.get("visible_product_ids")
    )
    product_count = answer.get("product_count")
    max_cards = card_display.get("max_cards")
    if (
        not _is_non_negative_int(product_count)
        or not _is_non_negative_int(max_cards)
        or product_count != len(product_ids)
        or max_cards != len(visible_ids)
        or visible_ids != product_ids
    ):
        _invalid_guide_events()
    if any(
        answer_event.get(field_name) != answer.get(field_name)
        for field_name in (
            "product_count",
            "winner_status",
            "has_unknown_skin",
        )
    ):
        _invalid_guide_events()
    if (
        not isinstance(answer.get("winner_status"), str)
        or not isinstance(answer.get("has_unknown_skin"), bool)
    ):
        _invalid_guide_events()

    cards = products_payload.get("cards")
    if (
        not isinstance(cards, list)
        or _ordered_ids(cards, key="product_id") != product_ids
    ):
        _invalid_guide_events()
    _validate_category_payload(
        intent_payload=events[intent_position][1],
        products=products,
        cards=cards,
    )

    mode = card_display.get("mode")
    if (
        (mode == "none" and product_ids)
        or (mode == "single" and len(product_ids) != 1)
        or (
            mode == "recommendation"
            and not 1 <= len(product_ids) <= 3
        )
        or (
            mode == "comparison"
            and not 2 <= len(product_ids) <= 4
        )
        or mode not in {
            "none",
            "single",
            "recommendation",
            "comparison",
        }
    ):
        _invalid_guide_events()

    _validate_presentation_authority(
        presentation,
        visible_ids=visible_ids,
        card_display=card_display,
    )
    for evidence_name in (
        "scenario_evidence",
        "review_evidence",
        "merchant_claims",
        "product_evidence",
        "pitfalls",
        "citations",
    ):
        if any(
            index > presentation_position
            for index, name in enumerate(names)
            if name == evidence_name
        ):
            _invalid_guide_events()
    for name, payload in events:
        if name != "pitfalls":
            continue
        pitfalls = payload.get("pitfalls")
        if not isinstance(pitfalls, list):
            _invalid_guide_events()
        if any(
            isinstance(item, dict)
            and item.get("product_id") is not None
            and item.get("product_id") not in visible_ids
            for item in pitfalls
        ):
            _invalid_guide_events()

    decision_positions = [
        index
        for index, name in enumerate(names)
        if name == "decision_process"
    ]
    if len(decision_positions) > 1:
        _invalid_guide_events()
    decision = (
        events[decision_positions[0]][1]
        if decision_positions
        else None
    )
    if decision is not None:
        if not intent_position < decision_positions[0] < answer_position:
            _invalid_guide_events()
        if _ordered_positive_ids(
            decision.get("ordered_product_ids")
        ) != product_ids:
            _invalid_guide_events()
        _validate_decision_process(
            decision=decision,
            answer=answer,
            product_count=len(product_ids),
            comparison_expected=intent == "image_compare",
            suitability_expected=intent == "image_suitability",
        )
    elif intent in {
        "recommend",
        "revise",
        "image_recommend",
        "image_compare",
        "image_suitability",
    }:
        _invalid_guide_events()

    if intent == "image_compare":
        _validate_image_comparison(
            events=events,
            names=names,
            decision=decision,
            answer=answer,
            product_ids=product_ids,
            card_mode=mode,
        )
    elif intent == "image_suitability":
        _validate_image_suitability(
            events=events,
            names=names,
            decision=decision,
            answer=answer,
            product_ids=product_ids,
            card_mode=mode,
        )
    elif decision is not None and (
        decision.get("comparison_data") is not None
        or decision.get("suitability_data") is not None
    ):
        _invalid_guide_events()


def _typed_presentation(
    payload: dict[str, Any],
    *,
    intent: str,
    names: list[str],
):
    try:
        presentation = _PRESENTATION_ADAPTER.validate_python(
            payload,
            strict=True,
        )
    except (TypeError, ValueError):
        _invalid_guide_events()
        raise AssertionError("unreachable")
    allowed_modes = {
        "recommend": {"recommendation"},
        "comparison": {"comparison"},
        "suitability": {"single_product"},
        "knowledge": {"product_knowledge", "general_knowledge"},
        "followup": {
            "followup",
            "product_knowledge",
            "general_knowledge",
        },
        "revise": {"revision"},
        "image_identity": {"image_identity"},
        "image_recommend": {
            "recommendation",
            "image_recommendation",
        },
        "image_suitability": {"product_knowledge"},
        "image_compare": {"comparison"},
    }
    if intent in _CONSULTATION_EVENT_BY_INTENT:
        expected_modes = {"consultation"}
    else:
        expected_modes = allowed_modes.get(intent, set())
    if presentation.mode not in expected_modes:
        _invalid_guide_events()
    if (
        presentation.mode == "general_knowledge"
        and "general_knowledge" not in names
    ):
        _invalid_guide_events()
    _validate_presentation_section_order(presentation)
    return presentation


def _validate_presentation_section_order(presentation) -> None:
    kinds = [section.kind for section in presentation.sections]
    product_sections = [
        section
        for section in presentation.sections
        if section.kind == "product"
    ]
    if presentation.mode == "consultation":
        expected = ["observation", "summary"]
    elif presentation.mode == "general_knowledge":
        expected = ["general_knowledge"]
    elif presentation.mode == "product_knowledge":
        expected = [
            *("product" for _ in product_sections),
            "full_cards",
        ]
    elif not product_sections:
        expected = ["summary", "closing"]
    else:
        expected = ["summary"]
        if presentation.mode in {
            "comparison",
            "image_comparison",
        }:
            expected.append("comparison")
        expected.extend("product" for _ in product_sections)
        expected.extend(
            ["closing", "full_cards", "pitfalls"]
        )
    if kinds != expected:
        _invalid_guide_events()


def _validate_presentation_authority(
    presentation,
    *,
    visible_ids: list[int],
    card_display: dict[str, Any] | None,
) -> None:
    presentation_display = presentation.card_display.model_dump(
        mode="json"
    )
    if card_display is None:
        if presentation_display != {
            "mode": "none",
            "visible_product_ids": [],
            "max_cards": 0,
            "reason": None,
        }:
            _invalid_guide_events()
    elif presentation_display != card_display:
        _invalid_guide_events()
    product_ids = [
        section.product_id
        for section in presentation.sections
        if section.kind == "product"
    ]
    if product_ids != visible_ids:
        _invalid_guide_events()


def _validate_category_payload(
    *,
    intent_payload: dict[str, Any],
    products: list[Any],
    cards: list[Any],
) -> None:
    try:
        typed_cards = [
            ProductCard.model_validate_json(
                json.dumps(card, ensure_ascii=False)
            )
            for card in cards
        ]
        expected_products = [
            _card_to_frontend_product(
                card.model_dump(mode="json")
            )
            for card in typed_cards
        ]
    except (AttributeError, TypeError, ValueError):
        _invalid_guide_events()
        return

    if products != expected_products:
        _invalid_guide_events()

    product_profiles = [
        card.category_profile for card in typed_cards
    ]
    if typed_cards and (
        len(set(product_profiles)) != 1
        or any(not card.category_facts for card in typed_cards)
    ):
        _invalid_guide_events()

    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    for card in typed_cards:
        if any(
            fact.field_key not in definitions
            or card.category_profile
            not in definitions[fact.field_key].profiles
            for fact in card.category_facts
        ):
            _invalid_guide_events()

    intent_profile = intent_payload.get("category_profile")
    if intent_profile is None:
        return
    try:
        typed_intent_profile = CategoryProfile(intent_profile)
    except (TypeError, ValueError):
        _invalid_guide_events()
        return
    if any(
        profile is not typed_intent_profile
        for profile in product_profiles
    ):
        _invalid_guide_events()


def _validate_consultation_zero_card_sequence(
    *,
    events: list[tuple[str, dict[str, Any]]],
    names: list[str],
    intent: str,
    intent_position: int,
    presentation,
    presentation_position: int,
    message_position: int,
) -> None:
    typed_event = _CONSULTATION_EVENT_BY_INTENT[intent]
    typed_position = _single_event_position(names, typed_event)
    answer_position = _single_event_position(names, "answer_contract")
    card_position = _single_event_position(
        names,
        "card_display_contract",
    )
    if (
        typed_position is None
        or answer_position is None
        or card_position is None
        or not (
            intent_position
            < typed_position
            < answer_position
            < card_position
            < presentation_position
            < message_position
        )
    ):
        _invalid_guide_events()
    if any(
        names.count(name)
        for name in {
            "products",
            "decision_process",
            "scenario_evidence",
            "review_evidence",
            "pitfalls",
            "citations",
            "image_observation",
        }
    ):
        _invalid_guide_events()
    consultation_events = set(_CONSULTATION_EVENT_BY_INTENT.values())
    if any(
        name != typed_event and name in consultation_events
        for name in names
    ):
        _invalid_guide_events()

    answer_event = events[answer_position][1]
    answer = answer_event.get("answer_contract")
    card_display = events[card_position][1]
    if (
        not isinstance(answer, dict)
        or answer.get("product_count") != 0
        or answer.get("winner_status") != "NOT_APPLICABLE"
        or answer.get("has_unknown_skin") is not False
        or card_display.get("mode") != "none"
        or card_display.get("visible_product_ids") != []
        or card_display.get("max_cards") != 0
        or any(
            answer_event.get(field_name) != answer.get(field_name)
            for field_name in (
                "product_count",
                "winner_status",
                "has_unknown_skin",
            )
        )
    ):
        _invalid_guide_events()
    _validate_presentation_authority(
        presentation,
        visible_ids=[],
        card_display=card_display,
    )


def _validate_decision_process(
    *,
    decision: dict[str, Any],
    answer: dict[str, Any],
    product_count: int,
    comparison_expected: bool,
    suitability_expected: bool,
) -> None:
    decision_status = decision.get("winner_status")
    if not isinstance(decision_status, str):
        _invalid_guide_events()
    if answer.get("winner_status") != decision_status:
        _invalid_guide_events()
    if (
        not comparison_expected
        and not suitability_expected
        and decision_status not in _DECISION_WINNER_STATUSES
    ):
        _invalid_guide_events()

    process = decision.get("decision_process")
    steps = process.get("steps") if isinstance(process, dict) else None
    if (
        not isinstance(steps, list)
        or len(steps) != 1
        or not isinstance(steps[0], dict)
        or not isinstance(steps[0].get("data"), dict)
    ):
        _invalid_guide_events()
    step_data = steps[0]["data"]
    if (
        step_data.get("winner_status") != decision_status
        or step_data.get("products") != product_count
    ):
        _invalid_guide_events()
    nested_outcome = step_data.get("outcome")
    if comparison_expected or suitability_expected:
        expected_outcome = (
            decision.get("comparison_data")
            if comparison_expected
            else decision.get("suitability_data")
        )
        if nested_outcome != expected_outcome:
            _invalid_guide_events()
    elif nested_outcome is not None:
        _invalid_guide_events()


def _validate_image_comparison(
    *,
    events: list[tuple[str, dict[str, Any]]],
    names: list[str],
    decision: dict[str, Any] | None,
    answer: dict[str, Any],
    product_ids: list[int],
    card_mode: Any,
) -> None:
    image_count = len(product_ids)
    if (
        decision is None
        or card_mode != "comparison"
        or not 2 <= image_count <= 4
    ):
        _invalid_guide_events()
    comparison = decision.get("comparison_data")
    if not isinstance(comparison, dict):
        _invalid_guide_events()
    try:
        ImageComparisonData.model_validate_json(
            json.dumps(comparison)
        )
    except ValueError:
        _invalid_guide_events()
    comparison_status = comparison.get("status")
    if (
        decision.get("winner_status") != comparison_status
        or answer.get("winner_status") != comparison_status
    ):
        _invalid_guide_events()
    references = comparison.get("references")
    price_facts = comparison.get("evaluated_price_facts")
    if (
        not isinstance(references, list)
        or len(references) != image_count
        or not isinstance(price_facts, list)
        or len(price_facts) != image_count
    ):
        _invalid_guide_events()
    if _ordered_ids(references, key="product_id") != product_ids:
        _invalid_guide_events()
    if [reference.get("ordinal") for reference in references] != list(
        range(1, image_count + 1)
    ):
        _invalid_guide_events()
    if any(not isinstance(fact, dict) for fact in price_facts):
        _invalid_guide_events()
    price_references = [fact.get("reference") for fact in price_facts]
    if price_references != references:
        _invalid_guide_events()
    if _ordered_ids(price_references, key="product_id") != product_ids:
        _invalid_guide_events()

    winner_reference = comparison.get("winner_reference")
    if comparison_status == "winner":
        if (
            not isinstance(winner_reference, dict)
            or sum(
                winner_reference == reference
                for reference in references
            )
            != 1
        ):
            _invalid_guide_events()
    elif winner_reference is not None:
        _invalid_guide_events()
    if (
        comparison_status == "tie"
        and comparison.get("tie_reason")
        != (
            "equal_price"
            if image_count == 2
            else "equal_lowest_price"
        )
    ):
        _invalid_guide_events()
    if (
        comparison_status != "tie"
        and comparison.get("tie_reason") is not None
    ):
        _invalid_guide_events()

    observation_payloads = [
        payload
        for name, payload in events
        if name == "image_observation"
    ]
    if len(observation_payloads) != image_count:
        _invalid_guide_events()
    observed_image_ids = [
        payload.get("observation", {}).get("image_id")
        if isinstance(payload.get("observation"), dict)
        else None
        for payload in observation_payloads
    ]
    observed_product_ids = [
        payload.get("observation", {}).get("confirmed_product_id")
        if isinstance(payload.get("observation"), dict)
        else None
        for payload in observation_payloads
    ]
    if observed_image_ids != [
        reference.get("image_id") for reference in references
    ]:
        _invalid_guide_events()
    if observed_product_ids != product_ids:
        _invalid_guide_events()
    observation_positions = [
        index
        for index, name in enumerate(names)
        if name == "image_observation"
    ]
    intent_position = names.index("intent")
    if any(position >= intent_position for position in observation_positions):
        _invalid_guide_events()


def _validate_image_suitability(
    *,
    events: list[tuple[str, dict[str, Any]]],
    names: list[str],
    decision: dict[str, Any] | None,
    answer: dict[str, Any],
    product_ids: list[int],
    card_mode: Any,
) -> None:
    if decision is None or card_mode != "single" or len(product_ids) != 1:
        _invalid_guide_events()
    suitability = decision.get("suitability_data")
    if not isinstance(suitability, dict):
        _invalid_guide_events()
    try:
        ImageSuitabilityData.model_validate_json(
            json.dumps(suitability)
        )
    except ValueError:
        _invalid_guide_events()
    if (
        suitability.get("status") != decision.get("winner_status")
        or suitability.get("status") != answer.get("winner_status")
    ):
        _invalid_guide_events()
    reference = suitability.get("reference")
    if (
        not isinstance(reference, dict)
        or reference.get("ordinal") != 1
        or reference.get("product_id") != product_ids[0]
    ):
        _invalid_guide_events()
    observations = [
        payload.get("observation")
        for name, payload in events
        if name == "image_observation"
    ]
    if (
        len(observations) != 1
        or not isinstance(observations[0], dict)
        or observations[0].get("image_id") != reference.get("image_id")
        or observations[0].get("confirmed_product_id") != product_ids[0]
    ):
        _invalid_guide_events()
    observation_position = names.index("image_observation")
    if observation_position >= names.index("intent"):
        _invalid_guide_events()


def _single_event_position(
    names: list[str],
    event_name: str,
) -> int | None:
    positions = [
        index for index, name in enumerate(names) if name == event_name
    ]
    if len(positions) != 1:
        return None
    return positions[0]


def _ordered_ids(items: list[Any], *, key: str) -> list[int]:
    if any(not isinstance(item, dict) for item in items):
        _invalid_guide_events()
    return _ordered_positive_ids([item.get(key) for item in items])


def _ordered_positive_ids(value: Any) -> list[int]:
    if (
        not isinstance(value, list)
        or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or item < 1
            for item in value
        )
        or len(value) != len(set(value))
    ):
        _invalid_guide_events()
    return list(value)


def _is_non_negative_int(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def _invalid_guide_events() -> None:
    raise GuidePublicEventError(
        code="GUIDE_EVENT_CONTRACT_INVALID",
        message="推荐响应不完整，请稍后重试。",
    )


def _to_legacy_data(event) -> dict[str, Any]:
    if isinstance(event, StartEvent):
        return {"session_id": event.data.session_id}
    if isinstance(event, StageEvent):
        return {
            "message": event.data.summary,
            "status": "active",
            "stage": event.data.stage,
        }
    if isinstance(event, IntentEvent):
        payload = {
            "intent": event.data.mode,
            "entities": {},
            "scenario_intent": event.data.mode,
            "guide": True,
        }
        if event.data.category_profile is not None:
            payload["category_profile"] = (
                event.data.category_profile.value
            )
        return payload
    if isinstance(event, ClarifyEvent):
        return {"question": event.data.question}
    if isinstance(event, DecisionProcessEvent):
        payload = {
            "ordered_product_ids": list(event.data.ordered_product_ids),
            "winner_status": event.data.winner_status,
            "evidence_refs": list(event.data.evidence_refs),
            "decision_process": {
                "steps": [
                    {
                        "type": "decision",
                        "title": "执行后端筛选规则",
                        "description": (
                            "预算、品类、功效和肤质证据"
                            "已按后端合同处理。"
                        ),
                        "data": {
                            "winner_status": event.data.winner_status,
                            "products": len(event.data.ordered_product_ids),
                        },
                    }
                ],
                "final_recommendation": None,
            },
        }
        if event.data.comparison_data is not None:
            comparison_data = event.data.comparison_data.model_dump(
                mode="json"
            )
            payload["comparison_data"] = comparison_data
            payload["decision_process"]["steps"][0]["data"][
                "outcome"
            ] = comparison_data
        if event.data.suitability_data is not None:
            suitability_data = event.data.suitability_data.model_dump(
                mode="json"
            )
            payload["suitability_data"] = suitability_data
            payload["decision_process"]["steps"][0]["data"][
                "outcome"
            ] = suitability_data
        return payload
    if isinstance(event, ScenarioEvidenceEvent):
        return event.data.model_dump(mode="json")
    if isinstance(event, ReviewEvidenceEvent):
        return event.data.model_dump(mode="json")
    if isinstance(event, MerchantClaimsEvent):
        return event.data.model_dump(mode="json")
    if isinstance(event, ProductEvidenceEvent):
        return event.data.model_dump(mode="json")
    if isinstance(event, GeneralKnowledgeEvent):
        return event.data.model_dump(mode="json")
    if isinstance(event, PitfallsEvent):
        return event.data.model_dump(mode="json")
    if isinstance(event, CitationsEvent):
        return event.data.model_dump(mode="json")
    if isinstance(event, AnswerContractEvent):
        return {
            "answer_contract": event.data.model_dump(mode="json"),
            "winner_status": event.data.winner_status,
            "product_count": event.data.product_count,
            "has_unknown_skin": event.data.has_unknown_skin,
        }
    if isinstance(event, CardDisplayContractEvent):
        return event.data.model_dump(mode="json")
    if isinstance(event, ProductsEvent):
        cards = [
            card.model_dump(mode="json")
            for card in event.data.cards
        ]
        return {
            "cards": cards,
            "products": [_card_to_frontend_product(card) for card in cards],
        }
    if isinstance(event, PresentationContractEvent):
        return event.data.model_dump(mode="json")
    if isinstance(event, MessageEvent):
        return {"content": event.data.content, "done": False}
    if isinstance(event, ErrorEvent):
        return {
            "error": event.data.code,
            "message": event.data.message,
        }
    if isinstance(event, ImageObservationEvent):
        return event.data.model_dump(mode="json")
    if isinstance(
        event,
        (
            ConsultationObservationEvent,
            ConsultationProvisionalEvent,
            MedicalEscalationEvent,
            ProfileConfirmationEvent,
        ),
    ):
        return event.data.model_dump(mode="json")
    if isinstance(event, EndEvent):
        return {
            "conversation_version": event.data.conversation_version,
        }
    return _model_dump(event)


def _card_to_frontend_product(card: dict[str, Any]) -> dict[str, Any]:
    warnings = card.get("fact_warnings") or []
    return {
        "id": card["product_id"],
        "product_id": card["product_id"],
        "category_profile": card["category_profile"],
        "category_facts": list(card["category_facts"]),
        "variant_scope": card.get("variant_scope"),
        "specification": card.get("specification"),
        "name": card.get("name"),
        "display_name": card.get("name"),
        "brand": card.get("brand"),
        "category": card.get("category"),
        "price": card.get("price"),
        "image_url": card.get("image_url") or "",
        "detail_url": card.get("detail_url") or "",
        "platform": card.get("platform") or "",
        "image_source_sha256": card.get("image_source_sha256"),
        "description": _product_description(
            skin_match=card.get("skin_match"),
            warnings=warnings,
            matched_efficacies=list(
                card.get("matched_efficacies") or []
            ),
        ),
        "efficacy_match": (
            "matched"
            if card.get("matched_efficacies")
            else "not_applicable"
        ),
        "matched_efficacies": list(
            card.get("matched_efficacies") or []
        ),
        "suitable_skin": _skin_label(card.get("skin_match")),
        "fact_warnings": list(warnings),
    }


def _product_description(
    *,
    skin_match: str | None,
    warnings: list[str],
    matched_efficacies: list[str],
) -> str:
    parts: list[str] = []
    if matched_efficacies:
        parts.append(
            f"已审核功效：{'、'.join(matched_efficacies)}。"
        )
    if skin_match == "unknown":
        parts.append("肤质数据缺失，保留但不作为明确适配结论。")
    elif skin_match == "matched":
        parts.append("肤质证据明确匹配。")
    if "product_identity_unusable" in warnings:
        parts.append("商品名称字段不可用，按原始事实标注。")
    return " ".join(parts)


def _skin_label(skin_match: str | None) -> str:
    if skin_match == "matched":
        return "已确认适配"
    if skin_match == "unknown":
        return "肤质数据缺失"
    return "未限定肤质"


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return {"value": value}
