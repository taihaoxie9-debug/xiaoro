from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
import json

import httpx
import pytest

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
    CopyLengthBudget,
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


def _draft() -> dict[str, object]:
    return {
        "mode": "general_knowledge",
        "summary_copy": "SPF主要描述对UVB的防护能力。",
        "product_copy": [],
        "closing_copy": "PA用于表示UVA防护等级。",
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

    assert result.draft.summary_copy
    assert transport.request_count == 1
    assert transport.bodies[0]["enable_thinking"] is False
    assert "thinking" not in transport.bodies[0]


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
