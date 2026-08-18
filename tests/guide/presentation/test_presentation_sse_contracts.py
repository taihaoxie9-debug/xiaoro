from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from app.guide.presentation.sse_events import (
    ConsultationObservationData,
    SseEvent,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)


def _recommendation_event() -> dict[str, object]:
    return {
        "event": "presentation_contract",
        "data": {
            "mode": "recommendation",
            "copy_source": "model",
            "sections": [
                {
                    "kind": "summary",
                    "copy_text": "预算内有两款可以继续比较。",
                    "slot_id": None,
                    "product_id": None,
                    "direct_facts": [],
                },
                {
                    "kind": "product",
                    "copy_text": "第一款更偏轻盈清爽路线。",
                    "advisor_reason": "更看重通勤清爽感时可优先比较。",
                    "slot_id": "p1",
                    "product_id": 55,
                    "direct_facts": [
                        {
                            "fact_id": "price-55",
                            "label": "参考价",
                            "display_value": "¥88.11",
                        }
                    ],
                },
                {
                    "kind": "product",
                    "copy_text": "第二款更偏水润轻薄路线。",
                    "advisor_reason": "更在意水润贴肤时可继续比较。",
                    "slot_id": "p2",
                    "product_id": 57,
                    "direct_facts": [
                        {
                            "fact_id": "price-57",
                            "label": "参考价",
                            "display_value": "¥92.02",
                        }
                    ],
                },
                {
                    "kind": "closing",
                    "copy_text": "先按肤感偏好选择。",
                    "slot_id": None,
                    "product_id": None,
                    "direct_facts": [],
                },
                {
                    "kind": "full_cards",
                    "copy_text": None,
                    "slot_id": None,
                    "product_id": None,
                    "direct_facts": [],
                },
                {
                    "kind": "pitfalls",
                    "copy_text": None,
                    "slot_id": None,
                    "product_id": None,
                    "direct_facts": [],
                },
            ],
            "card_display": {
                "mode": "recommendation",
                "visible_product_ids": [55, 57],
                "max_cards": 2,
                "reason": "recommendation",
            },
            "telemetry": {
                "provider": "deepseek_official",
                "model": "copy-model",
                "prompt_tokens": 120,
                "completion_tokens": 60,
                "total_tokens": 180,
                "latency_ms": 1000.0,
                "fallback_reason": None,
            },
        },
    }


def test_presentation_contract_is_a_strict_typed_sse_event() -> None:
    event = TypeAdapter(SseEvent).validate_json(
        json.dumps(_recommendation_event(), ensure_ascii=False)
    )

    assert event.event == "presentation_contract"
    assert event.data.mode == "recommendation"
    assert event.data.card_display.visible_product_ids == (55, 57)


def test_presentation_sse_rejects_untyped_ranking_or_copy_fields() -> None:
    payload = _recommendation_event()
    payload["data"]["ranking_bonus"] = 10

    with pytest.raises(
        ValidationError,
        match="Extra inputs are not permitted",
    ):
        TypeAdapter(SseEvent).validate_python(payload)


def test_presentation_sse_rejects_reordered_card_contract() -> None:
    payload = _recommendation_event()
    payload["data"]["card_display"]["visible_product_ids"] = [57, 55]

    with pytest.raises(ValidationError):
        TypeAdapter(SseEvent).validate_python(payload)


def test_dynamic_consultation_sse_accepts_more_than_legacy_five() -> None:
    dimensions = (
        "oiliness",
        "dryness",
        "tightness",
        "redness",
        "stinging",
        "product_tolerance",
    )
    observations = [
        ConsultationObservation(
            observation_id=f"obs_{dimension}",
            dimension=dimension,
            state="present",
            source_text=dimension,
            source_turn_id="turn_dynamic_sse_0001",
        )
        for dimension in dimensions
    ]

    data = ConsultationObservationData(
        conversation_version=1,
        observations=observations,
    )

    assert len(data.observations) == 6
