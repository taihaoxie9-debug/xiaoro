from __future__ import annotations

from collections.abc import Iterable
import json
from typing import Any

from pydantic import BaseModel, TypeAdapter

from app.guide.decision.contracts import WinnerStatus
from app.guide.intent.responsibility_matrix import (
    Responsibility,
)
from app.guide.presentation.contracts import ProductCard
from app.guide.presentation.public_contracts import (
    PublicPresentationContract,
)
from app.guide.presentation.terminal_contract_guard import (
    GuideTerminalContractError,
    GuideTerminalContractGuard,
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
    ErrorData,
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
    StartData,
    StartEvent,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.semantic_contracts import ClarificationCode


class GuidePublicEventError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


def encode_sse_frame(
    event: str,
    data: dict[str, object],
) -> bytes:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        b"event: "
        + event.encode("ascii")
        + b"\ndata: "
        + payload
        + b"\n\n"
    )


def materialize_public_event_envelope(
    events: Iterable[Any],
    *,
    session_id: str,
) -> tuple[bytes, ...]:
    return tuple(
        encode_sse_frame(event, data)
        for event, data in materialize_guide_public_events(
            events,
            session_id=session_id,
        )
    )


def materialize_error_frames(
    *,
    session_id: str,
    code: str,
    message: str,
) -> tuple[bytes, bytes]:
    frames = materialize_public_event_envelope(
        (
            StartEvent(data=StartData(session_id=session_id)),
            ErrorEvent(data=ErrorData(code=code, message=message)),
        ),
        session_id=session_id,
    )
    if len(frames) != 2:
        raise GuidePublicEventError(
            code="GUIDE_EVENT_CONTRACT_INVALID",
            message="推荐响应不完整，请稍后重试。",
        )
    return frames


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
_PRESENTATION_ADAPTER = TypeAdapter(PublicPresentationContract)


def materialize_guide_public_events(
    events: Iterable[Any],
    *,
    session_id: str,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    public_events = tuple(
        _adapt_public_terminal_events(
            _public_terminal_events(tuple(events))
        )
    )
    _validate_guide_event_sequence(
        public_events,
        session_id=session_id,
    )
    return public_events


def _project_public_event(event) -> tuple[str, dict[str, Any]]:
    if isinstance(event, ClarifyEvent):
        return (
            "clarify",
            event.data.model_dump(
                mode="json",
                exclude_none=True,
            ),
        )
    return event.event, _project_public_event_data(event)


def _adapt_public_terminal_events(
    events: tuple[Any, ...],
) -> list[tuple[str, dict[str, Any]]]:
    return [_project_public_event(event) for event in events]


def _public_terminal_events(events) -> tuple[Any, ...]:
    typed_events = tuple(events)
    guard = GuideTerminalContractGuard()
    try:
        for event in typed_events:
            guard.observe(event)
        guard.finish()
    except GuideTerminalContractError as error:
        raise GuidePublicEventError(
            code="GUIDE_EVENT_CONTRACT_INVALID",
            message="推荐响应不完整，请稍后重试。",
        ) from error
    return typed_events


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
    if intent_position is None or "message" in names:
        _invalid_guide_events()
    intent = events[intent_position][1].get("intent")
    if not isinstance(intent, str) or not intent:
        _invalid_guide_events()

    if "clarify" in names:
        clarification_position = _single_event_position(
            names,
            "clarify",
        )
        if any(
            names.count(name)
            for name in (
                "answer_contract",
                "card_display_contract",
                "products",
                "decision_process",
                "presentation_contract",
            )
        ) or (
            clarification_position is None
            or not (
                intent_position
                < clarification_position
                < len(events) - 1
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
            < len(events) - 1
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
                < len(events) - 1
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
            < len(events) - 1
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
            and not 1 <= len(product_ids) <= 4
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
    if (
        presentation.responsibility is Responsibility.RECOMMENDATION
        and presentation.recommendation_mode == "explore"
        and answer.get("winner_status") != "NOT_APPLICABLE"
    ):
        _invalid_guide_events()
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
            explore_recommendation=(
                presentation.responsibility
                is Responsibility.RECOMMENDATION
                and presentation.recommendation_mode == "explore"
            ),
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
            "recommendation",
            "comparison",
            "single_product",
            "product_knowledge",
            "general_knowledge",
        },
        "revise": {"recommendation"},
        "image_identity": {"image_identity"},
        "image_recommend": {"recommendation"},
        "image_suitability": {"single_product"},
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
    return presentation


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
    if list(presentation.visible_product_ids) != visible_ids:
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
            project_frontend_product(card)
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
    mixed_identity_profiles = (
        intent_payload.get("intent") == "image_identity"
    )
    if typed_cards and (
        (
            not mixed_identity_profiles
            and len(set(product_profiles)) != 1
        )
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
            < len(events) - 1
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
    explore_recommendation: bool,
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
        and not (
            explore_recommendation
            and decision_status == "NOT_APPLICABLE"
        )
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
    context_source = comparison.get("context_source")
    if (
        context_source == "current_upload"
        and len(observation_payloads) != image_count
    ):
        _invalid_guide_events()
    if (
        context_source == "confirmed_session"
        and observation_payloads
    ):
        _invalid_guide_events()
    if context_source == "confirmed_session":
        return
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


def _project_public_event_data(event) -> dict[str, Any]:
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
        typed_cards = list(event.data.cards)
        cards = [
            card.model_dump(mode="json")
            for card in typed_cards
        ]
        return {
            "cards": cards,
            "products": [
                project_frontend_product(card)
                for card in typed_cards
            ],
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


def project_frontend_product(card: ProductCard) -> dict[str, Any]:
    if not isinstance(card, ProductCard):
        raise TypeError("frontend product projection requires ProductCard")
    payload = card.model_dump(mode="json")
    warnings = list(card.fact_warnings)
    matched_efficacies = list(card.matched_efficacies)
    return {
        "id": payload["product_id"],
        "product_id": payload["product_id"],
        "category_profile": payload["category_profile"],
        "category_facts": payload["category_facts"],
        "variant_scope": payload["variant_scope"],
        "price_specification_alignment": payload[
            "price_specification_alignment"
        ],
        "specification": payload["specification"],
        "name": payload["name"],
        "display_name": payload["display_name"] or payload["name"],
        "brand": payload["brand"],
        "category": payload["category"],
        "price": payload["price"],
        "image_url": payload["image_url"] or "",
        "detail_url": payload["detail_url"] or "",
        "platform": payload["platform"] or "",
        "image_source_sha256": payload["image_source_sha256"],
        "description": _product_description(
            skin_match=card.skin_match,
            warnings=warnings,
            matched_efficacies=matched_efficacies,
        ),
        "efficacy_match": (
            "matched"
            if matched_efficacies
            else "not_applicable"
        ),
        "matched_efficacies": matched_efficacies,
        "suitable_skin": _skin_label(card.skin_match),
        "fact_warnings": warnings,
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
