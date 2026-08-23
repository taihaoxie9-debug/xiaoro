from __future__ import annotations

from hashlib import sha256
import importlib
import json

import pytest
from pydantic import ValidationError

from app.guide.feedback.contracts import (
    ClarificationProgress,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.application.contracts import UserTurn
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.copywriter_contracts import (
    CopywriterTelemetry,
    PresentationSection,
)
from app.guide.presentation.public_contracts import (
    PublicPresentationContract,
)
from app.guide.presentation.sse_events import (
    ClarifyData,
    ErrorData,
    IntentData,
    IntentEvent,
)
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


def _contracts():
    try:
        return importlib.import_module(
            "app.guide.application.execution_contracts"
        )
    except ModuleNotFoundError:
        pytest.fail("execution contracts module is missing")


def _clarification_decision() -> UnifiedRouteDecision:
    return UnifiedRouteDecision(
        processor="clarification",
        responsibility=Responsibility.CLARIFICATION,
        presentation_mode="clarification",
        continuity="continue",
        focus_source="none",
        clarification="请补充预算。",
        clarification_code=ClarificationCode.BUDGET,
    )


def _product_decision(product_id: int = 38) -> UnifiedRouteDecision:
    return UnifiedRouteDecision(
        processor="product_knowledge",
        responsibility=Responsibility.PRODUCT_KNOWLEDGE,
        presentation_mode="product_knowledge",
        continuity="replace_task",
        focus_source="explicit_product",
        product_bindings=(
            ResolvedProductBinding(
                product_id=product_id,
                source_text="这款精华",
            ),
        ),
    )


def _product_presentation(
    product_id: int = 38,
) -> PublicPresentationContract:
    return PublicPresentationContract(
        responsibility=Responsibility.PRODUCT_KNOWLEDGE,
        mode="product_knowledge",
        copy_source="fallback",
        sections=(
            PresentationSection(
                kind="summary",
                copy_text="先看这款商品。",
            ),
            PresentationSection(
                kind="answer",
                copy_text="这款商品的公开信息如下。",
            ),
            PresentationSection(kind="full_cards"),
        ),
        visible_product_ids=(product_id,),
        card_display=CardDisplayContract(
            mode="single",
            visible_product_ids=(product_id,),
            max_cards=1,
            reason="product",
        ),
        telemetry=CopywriterTelemetry(
            provider="test",
            model="deterministic",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            fallback_reason="test",
        ),
    )


def test_state_delta_defaults_every_lane_to_preserve() -> None:
    contracts = _contracts()

    delta = contracts.ConversationStateDelta()

    assert {
        delta.recommendation.action,
        delta.product.action,
        delta.image.action,
        delta.consultation.action,
        delta.knowledge.action,
        delta.clarification.action,
        delta.profile.action,
    } == {"preserve"}


def test_user_turn_requires_ingress_owned_turn_identity() -> None:
    contracts = _contracts()

    with pytest.raises(ValidationError):
        UserTurn(
            session_id="identity-required",
            message="推荐防晒",
            conversation_version=0,
        )

    identity = contracts.TurnIdentity(
        session_id="identity-required",
        request_id="request_0123456789abcdef",
        turn_id="turn_0123456789abcdef",
    )
    turn = UserTurn(
        identity=identity,
        session_id="identity-required",
        message="推荐防晒",
        conversation_version=0,
    )

    assert turn.identity is identity


def test_processor_execution_input_is_raw_request_free() -> None:
    contracts = _contracts()

    assert tuple(contracts.ProcessorExecutionInput.model_fields) == (
        "turn_identity",
        "understanding",
        "decision",
        "current_snapshot",
        "routing_evidence",
    )
    assert tuple(contracts.PreRoutingEvidence.model_fields) == (
        "query",
        "conversation_version",
        "profile_owner",
        "profile_context",
        "product_resolution",
        "pending_reply",
        "task_plan",
        "scenario_inputs",
        "product_knowledge_dimensions",
        "consultation",
        "image",
        "candidate_product_ids",
        "scenario_observations",
        "transition_operations",
    )
    forbidden = {
        "message",
        "question_summary",
        "request",
        "turn",
        "user_turn",
    }
    assert forbidden.isdisjoint(
        contracts.ProcessorExecutionInput.model_fields
    )
    assert forbidden.isdisjoint(
        contracts.PreRoutingEvidence.model_fields
    )


def test_recommendation_lane_replace_is_typed() -> None:
    contracts = _contracts()

    delta = contracts.ConversationStateDelta.model_validate(
        {
            "recommendation": {
                "action": "replace",
                "value": {
                    "query_context": RecommendationQueryContext(
                        category="serum",
                        recommendation_mode="explore",
                        recommendation_mode_basis="broad_exploration",
                        recommendation_count=3,
                    ),
                    "candidates": (
                        DisplayedCandidateRef(
                            product_id=38,
                            ordinal=1,
                            skin_match="unknown",
                            matched_efficacies=(),
                        ),
                    ),
                    "empty_result": False,
                },
            }
        },
        strict=True,
    )

    assert delta.recommendation.action == "replace"
    assert delta.recommendation.value.candidates[0].product_id == 38


def test_lane_replace_requires_value_and_preserve_forbids_value() -> None:
    contracts = _contracts()

    with pytest.raises(ValidationError):
        contracts.ConversationStateDelta.model_validate(
            {"recommendation": {"action": "replace"}},
            strict=True,
        )
    with pytest.raises(ValidationError):
        contracts.ConversationStateDelta.model_validate(
            {
                "recommendation": {
                    "action": "preserve",
                    "value": {
                        "query_context": RecommendationQueryContext(
                            category="serum",
                            recommendation_mode="explore",
                            recommendation_mode_basis=(
                                "broad_exploration"
                            ),
                            recommendation_count=3,
                        ),
                        "candidates": (),
                        "empty_result": True,
                    },
                }
            },
            strict=True,
        )


def test_execution_result_keeps_decision_and_one_typed_terminal() -> None:
    contracts = _contracts()
    decision = _clarification_decision()
    terminal = contracts.ClarificationTerminal(
        data=ClarifyData(
            question="请补充预算。",
            clarification_code=ClarificationCode.BUDGET,
        )
    )

    result = contracts.ExecutionResult(
        decision=decision,
        state_delta=contracts.ConversationStateDelta(
            clarification=contracts.LaneMutation[
                contracts.ClarificationLaneState
            ](
                action="replace",
                value=contracts.ClarificationLaneState(
                    progress=ClarificationProgress(
                        gap=ClarificationCode.BUDGET,
                        attempts=1,
                    ),
                ),
            )
        ),
        terminal=terminal,
    )

    assert result.decision is decision
    assert result.terminal is terminal
    assert result.audit_events == ()


def test_execution_result_forbids_snapshot_side_channel() -> None:
    contracts = _contracts()

    with pytest.raises(ValidationError):
        contracts.ExecutionResult.model_validate(
            {
                "decision": _clarification_decision(),
                "state_delta": contracts.ConversationStateDelta(),
                "terminal": contracts.ClarificationTerminal(
                    data=ClarifyData(
                        question="请补充预算。",
                        clarification_code=ClarificationCode.BUDGET,
                    )
                ),
                "snapshot": {"session_id": "forbidden"},
            },
            strict=True,
        )


def test_clarification_terminal_requires_matching_state_delta() -> None:
    contracts = _contracts()
    decision = _clarification_decision()
    terminal = contracts.ClarificationTerminal(
        data=ClarifyData(
            question="请补充预算。",
            clarification_code=ClarificationCode.BUDGET,
        )
    )

    with pytest.raises(
        ValidationError,
        match="clarification terminal requires matching state delta",
    ):
        contracts.ExecutionResult(
            decision=decision,
            state_delta=contracts.ConversationStateDelta(),
            terminal=terminal,
        )

    result = contracts.ExecutionResult(
        decision=decision,
        state_delta=contracts.ConversationStateDelta(
            clarification=contracts.LaneMutation[
                contracts.ClarificationLaneState
            ](
                action="replace",
                value=contracts.ClarificationLaneState(
                    progress=ClarificationProgress(
                        gap=ClarificationCode.BUDGET,
                        attempts=1,
                    ),
                ),
            )
        ),
        terminal=terminal,
    )

    assert result.decision is decision


def test_error_terminal_forbids_state_mutation() -> None:
    contracts = _contracts()

    with pytest.raises(
        ValidationError,
        match="error terminal forbids state mutation",
    ):
        contracts.ExecutionResult(
            decision=_clarification_decision(),
            state_delta=contracts.ConversationStateDelta(
                clarification=contracts.LaneMutation[
                    contracts.ClarificationLaneState
                ](
                    action="clear",
                    reason="error",
                )
            ),
            terminal=contracts.ErrorTerminal(
                data=ErrorData(
                    code="GUIDE_INTERNAL_ERROR",
                        message="推荐暂时不可用，请稍后重试。",
                )
            ),
        )


def test_presentation_and_state_delta_share_product_bindings() -> None:
    contracts = _contracts()

    with pytest.raises(
        ValidationError,
        match="product bindings must match decision and presentation",
    ):
        contracts.ExecutionResult(
            decision=_product_decision(product_id=38),
            state_delta=contracts.ConversationStateDelta(
                product=contracts.LaneMutation[
                    contracts.ProductLaneState
                ](
                    action="replace",
                    value=contracts.ProductLaneState(
                        current_product_id=39,
                    ),
                )
            ),
            terminal=contracts.PresentationTerminal(
                data=_product_presentation(product_id=38),
            ),
        )


def test_execution_result_materializes_one_way_validated_envelope() -> None:
    contracts = _contracts()
    decision = _clarification_decision()
    result = contracts.ExecutionResult(
        decision=decision,
        state_delta=contracts.ConversationStateDelta(
            clarification=contracts.LaneMutation[
                contracts.ClarificationLaneState
            ](
                action="replace",
                value=contracts.ClarificationLaneState(
                    progress=ClarificationProgress(
                        gap=ClarificationCode.BUDGET,
                        attempts=1,
                    ),
                ),
            )
        ),
        terminal=contracts.ClarificationTerminal(
            data=ClarifyData(
                question="请补充预算。",
                clarification_code=ClarificationCode.BUDGET,
            )
        ),
        audit_events=(
            IntentEvent(data=IntentData(mode="clarify")),
        ),
    )

    envelope = contracts.materialize_execution_envelope(
        result,
        session_id="execution-envelope",
        conversation_version=1,
    )

    assert envelope.decision is decision
    assert [
        frame.split(b"\n", maxsplit=1)[0]
        for frame in envelope.frames
    ] == [
        b"event: start",
        b"event: intent",
        b"event: clarify",
        b"event: end",
    ]
    assert json.loads(
        envelope.frames[-1].split(b"data: ", maxsplit=1)[1]
    )["conversation_version"] == 1


def test_execution_envelope_contains_frozen_encoded_sse_frames() -> None:
    contracts = _contracts()
    result = contracts.ExecutionResult(
        decision=_clarification_decision(),
        state_delta=contracts.ConversationStateDelta(
            clarification=contracts.LaneMutation[
                contracts.ClarificationLaneState
            ](
                action="replace",
                value=contracts.ClarificationLaneState(
                    progress=ClarificationProgress(
                        gap=ClarificationCode.BUDGET,
                        attempts=1,
                    ),
                ),
            )
        ),
        terminal=contracts.ClarificationTerminal(
            data=ClarifyData(
                question="请补充预算。",
                clarification_code=ClarificationCode.BUDGET,
            )
        ),
        audit_events=(
            IntentEvent(data=IntentData(mode="clarify")),
        ),
    )

    envelope = contracts.materialize_execution_envelope(
        result,
        session_id="encoded-envelope",
        conversation_version=1,
    )

    assert type(envelope.frames) is tuple
    assert all(type(frame) is bytes for frame in envelope.frames)
    assert [
        frame.split(b"\n", maxsplit=1)[0]
        for frame in envelope.frames
    ] == [
        b"event: start",
        b"event: intent",
        b"event: clarify",
        b"event: end",
    ]
    with pytest.raises(ValidationError, match="frozen"):
        envelope.frames = envelope.frames[:-1]


def test_sse_decision_digest_equals_execution_result_decision() -> None:
    contracts = _contracts()
    decision = _clarification_decision()
    result = contracts.ExecutionResult(
        decision=decision,
        state_delta=contracts.ConversationStateDelta(
            clarification=contracts.LaneMutation[
                contracts.ClarificationLaneState
            ](
                action="replace",
                value=contracts.ClarificationLaneState(
                    progress=ClarificationProgress(
                        gap=ClarificationCode.BUDGET,
                        attempts=1,
                    ),
                ),
            )
        ),
        terminal=contracts.ClarificationTerminal(
            data=ClarifyData(
                question="请补充预算。",
                clarification_code=ClarificationCode.BUDGET,
            )
        ),
        audit_events=(
            IntentEvent(data=IntentData(mode="clarify")),
        ),
    )
    canonical = json.dumps(
        result.decision.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    envelope = contracts.materialize_execution_envelope(
        result,
        session_id="decision-digest",
        conversation_version=1,
    )

    assert envelope.decision is result.decision
    assert envelope.decision_digest == sha256(canonical).hexdigest()


def test_error_envelope_has_no_success_end_event() -> None:
    contracts = _contracts()
    result = contracts.ExecutionResult(
        decision=_clarification_decision(),
        state_delta=contracts.ConversationStateDelta(),
        terminal=contracts.ErrorTerminal(
            data=ErrorData(
                code="GUIDE_INTERNAL_ERROR",
                message="推荐暂时不可用，请稍后重试。",
            )
        ),
    )

    envelope = contracts.materialize_execution_envelope(
        result,
        session_id="execution-envelope",
        conversation_version=0,
    )

    assert [
        frame.split(b"\n", maxsplit=1)[0]
        for frame in envelope.frames
    ] == [
        b"event: start",
        b"event: error",
    ]
