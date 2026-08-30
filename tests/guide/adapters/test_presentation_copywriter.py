from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
import json

import httpx
import pytest

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.adapters.llm.deepseek_presentation_copywriter import (
    DeepSeekPresentationCopywriterAdapter,
)
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.adapters.llm.siliconflow_presentation_copywriter import (
    SiliconFlowPresentationCopywriterAdapter,
)
from app.guide.presentation.copywriter_contracts import (
    ApprovedConstraint,
    ApprovedSoftFact,
    CopyLengthBudget,
    CopySlot,
    PresentationPacket,
    PresentationSectionSpec,
)
from app.guide_runtime.copywriter_config import CopywriterLlmConfig


class SequenceTransport(httpx.BaseTransport):
    def __init__(
        self,
        responses: Sequence[httpx.Response | BaseException],
    ) -> None:
        self.responses = iter(responses)
        self.request_count = 0
        self.bodies: list[dict[str, object]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        self.bodies.append(json.loads(request.read()))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


def _packet() -> PresentationPacket:
    return PresentationPacket(
        mode="general_knowledge",
        responsibility=Responsibility.GENERAL_KNOWLEDGE,
        user_need_summary="SPF和PA分别是什么意思",
        winner_status=None,
        slots=(),
        section_order=(
            PresentationSectionSpec(kind="general_knowledge"),
        ),
        copy_budget=CopyLengthBudget(
            summary_max_chars=240,
            positioning_max_chars=90,
            advisor_reason_max_chars=120,
            closing_max_chars=220,
        ),
    )


def _reference_packet() -> PresentationPacket:
    return PresentationPacket(
        mode="recommendation",
        responsibility=Responsibility.RECOMMENDATION,
        recommendation_mode="explore",
        user_need_summary="想找一款清爽的日常防晒",
        winner_status="INSUFFICIENT_FOR_WINNER",
        slots=(
            CopySlot(
                slot_id="p1",
                product_id=55,
                name="清透防晒乳",
                category_profile="suncare",
                approved_soft_facts=(
                    ApprovedSoftFact(
                        fact_id=(
                            "fact:sha256:"
                            "3c4ad1240db59935e28c981ef7d8a91e"
                        ),
                        product_id=55,
                        field_key="texture",
                        plain_meaning="质地轻薄清透、不黏腻",
                        attribution="merchant_claim",
                        source_refs=("source:merchant:55:texture",),
                    ),
                ),
            ),
        ),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="product", slot_id="p1"),
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        approved_constraints=(
            ApprovedConstraint(
                constraint_id=(
                    "constraint:sha256:"
                    "5e1c7bcaf0488d3c4978d63ec0249af2"
                ),
                kind="facet",
                display_value="清爽肤感",
            ),
        ),
        copy_budget=CopyLengthBudget(
            summary_max_chars=180,
            positioning_max_chars=90,
            advisor_reason_max_chars=120,
            closing_max_chars=180,
        ),
    )


def _draft() -> dict[str, object]:
    return {
        "mode": "general_knowledge",
        "sections": [
            {
                "kind": "general_knowledge",
                "slot_id": None,
                "content": {
                    "text": "SPF主要描述对UVB的防护能力。",
                    "winner_claim": "none",
                    "used_fact_ids": [],
                    "used_constraint_ids": [],
                },
                "advisor_reason": None,
            }
        ],
    }


def _reference_draft() -> dict[str, object]:
    return {
        "mode": "recommendation",
        "sections": [
            {
                "kind": "summary",
                "slot_id": None,
                "content": {
                    "text": "先按清爽肤感这个重点来取舍。",
                    "winner_claim": "none",
                    "used_fact_ids": [],
                    "used_constraint_ids": ["c1"],
                },
                "advisor_reason": None,
            },
            {
                "kind": "product",
                "slot_id": "p1",
                "content": {
                    "text": "轻薄清透、不黏腻的使用感。",
                    "winner_claim": "none",
                    "used_fact_ids": ["f1"],
                    "used_constraint_ids": [],
                },
                "advisor_reason": {
                    "text": "更贴合你对清爽肤感的关注。",
                    "winner_claim": "none",
                    "used_fact_ids": ["f1"],
                    "used_constraint_ids": ["c1"],
                },
            },
            {
                "kind": "closing",
                "slot_id": None,
                "content": {
                    "text": "可结合清爽肤感再做最后选择。",
                    "winner_claim": "none",
                    "used_fact_ids": [],
                    "used_constraint_ids": ["c1"],
                },
                "advisor_reason": None,
            },
        ],
    }


def test_copywriter_rejects_section_without_structured_winner_claim() -> None:
    draft = _draft()
    content = draft["sections"][0]["content"]
    assert isinstance(content, dict)
    del content["winner_claim"]
    transport = SequenceTransport(
        [_response(json.dumps(draft, ensure_ascii=False))]
    )
    adapter = _deepseek(transport)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.write(_packet())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT
    assert transport.request_count == 1


def test_copywriter_expands_short_evidence_references_before_validation() -> None:
    transport = SequenceTransport(
        [_response(json.dumps(_reference_draft(), ensure_ascii=False))]
    )
    adapter = _deepseek(transport)

    result = adapter.write(_reference_packet())

    product = result.draft.sections[1]
    assert product.content.used_fact_ids == (
        "fact:sha256:3c4ad1240db59935e28c981ef7d8a91e",
    )
    assert product.advisor_reason is not None
    assert product.advisor_reason.used_constraint_ids == (
        "constraint:sha256:5e1c7bcaf0488d3c4978d63ec0249af2",
    )


def test_copywriter_binds_merchant_attribution_from_used_fact_ids() -> None:
    draft = _reference_draft()
    product = draft["sections"][1]
    assert isinstance(product, dict)
    content = product["content"]
    assert isinstance(content, dict)
    content["text"] = "品牌故事之外，重点是轻薄清透、不黏腻的使用感。"
    advisor_reason = product["advisor_reason"]
    assert isinstance(advisor_reason, dict)
    advisor_reason["text"] = "更贴合你对清爽肤感的关注。"
    transport = SequenceTransport(
        [_response(json.dumps(draft, ensure_ascii=False))]
    )
    adapter = _deepseek(transport)

    result = adapter.write(_reference_packet())

    product_section = result.draft.sections[1]
    assert product_section.content.text.startswith(
        "品牌主打：品牌故事之外"
    )
    assert product_section.advisor_reason is not None
    assert product_section.advisor_reason.text.startswith(
        "品牌主打："
    )


def test_copywriter_rejects_unknown_short_evidence_reference() -> None:
    draft = _reference_draft()
    product = draft["sections"][1]
    assert isinstance(product, dict)
    content = product["content"]
    assert isinstance(content, dict)
    content["used_fact_ids"] = ["f99"]
    transport = SequenceTransport(
        [_response(json.dumps(draft, ensure_ascii=False))]
    )
    adapter = _deepseek(transport)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.write(_reference_packet())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT


@pytest.mark.parametrize("invalid_references", (None, 7, {"f1": True}))
def test_copywriter_rejects_non_list_evidence_references(
    invalid_references: object,
) -> None:
    draft = _reference_draft()
    product = draft["sections"][1]
    assert isinstance(product, dict)
    content = product["content"]
    assert isinstance(content, dict)
    content["used_fact_ids"] = invalid_references
    transport = SequenceTransport(
        [_response(json.dumps(draft, ensure_ascii=False))]
    )
    adapter = _deepseek(transport)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.write(_reference_packet())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT


@pytest.mark.parametrize(
    "mutate",
    [
        lambda draft: draft.pop("sections"),
        lambda draft: draft["sections"][0].pop("slot_id"),
        lambda draft: draft["sections"][0]["content"].pop(
            "used_fact_ids"
        ),
    ],
)
def test_copywriter_rejects_missing_exact_section_keys(mutate) -> None:
    draft = _draft()
    mutate(draft)
    content = json.dumps(draft, ensure_ascii=False)
    transport = SequenceTransport([_response(content)])
    adapter = _deepseek(transport)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.write(_packet())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT
    assert transport.request_count == 1


def _legacy_draft() -> dict[str, object]:
    return {
        "mode": "general_knowledge",
        "summary_copy": {
            "text": "SPF主要描述对UVB的防护能力。",
            "used_fact_ids": [],
            "used_constraint_ids": [],
        },
        "product_copy": [],
        "closing_copy": None,
    }


def _response(content: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"x-request-id": "copy-trace-1"},
        json={
            "choices": [
                {
                    "message": {
                        "content": content or json.dumps(_draft())
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 80,
                "completion_tokens": 30,
                "total_tokens": 110,
            },
        },
    )


def _deepseek(transport: httpx.BaseTransport):
    return DeepSeekPresentationCopywriterAdapter(
        api_key="not-a-real-key",
        model="deepseek-v4-pro",
        timeout_seconds=2.0,
        max_tokens=512,
        temperature=0.3,
        daily_budget_cny=Decimal("2"),
        daily_call_cap=100,
        transport=transport,
        clock=lambda: datetime(2026, 8, 16, tzinfo=UTC),
    )


def _config() -> CopywriterLlmConfig:
    return CopywriterLlmConfig(
        api_key="not-a-real-key",
        base_url="https://example.invalid/v1",
        model="provider/copy-model",
        timeout_seconds=2.0,
        max_tokens=512,
        temperature=0.3,
        daily_budget_cny=Decimal("2"),
        daily_call_cap=100,
    )


def test_deepseek_copywriter_uses_one_non_thinking_request() -> None:
    transport = SequenceTransport([_response()])
    adapter = _deepseek(transport)

    result = adapter.write(_packet())

    assert isinstance(result, CopywriterCallResult)
    assert result.draft.mode == "general_knowledge"
    assert result.usage.total_tokens == 110
    assert transport.request_count == 1
    body = transport.bodies[0]
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False
    assert body["temperature"] == 0.3
    assert len(body["messages"]) == 2


def test_siliconflow_copywriter_uses_one_non_thinking_request() -> None:
    transport = SequenceTransport([_response()])
    adapter = SiliconFlowPresentationCopywriterAdapter.from_config(
        _config(),
        transport=transport,
        clock=lambda: datetime(2026, 8, 16, tzinfo=UTC),
    )

    result = adapter.write(_packet())

    assert result.draft.sections
    assert transport.request_count == 1
    assert transport.bodies[0]["enable_thinking"] is False
    assert "thinking" not in transport.bodies[0]


def test_copywriter_rejects_legacy_universal_essay_shape() -> None:
    transport = SequenceTransport(
        [_response(json.dumps(_legacy_draft()))]
    )
    adapter = _deepseek(transport)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.write(_packet())

    assert caught.value.code is SemanticProviderFailureCode.INVALID_OUTPUT
    assert transport.request_count == 1


@pytest.mark.parametrize(
    "content",
    [
        "{not-json",
        json.dumps({**_draft(), "product_ids": [55]}),
    ],
)
def test_invalid_copywriter_output_fails_without_retry(
    content: str,
) -> None:
    transport = SequenceTransport([_response(content)])
    adapter = _deepseek(transport)

    with pytest.raises(SemanticProviderFailure) as caught:
        adapter.write(_packet())

    assert caught.value.code in {
        SemanticProviderFailureCode.INVALID_OUTPUT,
        SemanticProviderFailureCode.FORBIDDEN_OUTPUT,
    }
    assert caught.value.raw_content == content
    assert caught.value.trace_id is not None
    assert caught.value.trace_id.startswith("sha256:")
    assert caught.value.usage is not None
    assert caught.value.usage.total_tokens == 110
    assert transport.request_count == 1
