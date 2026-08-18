from __future__ import annotations

import pytest

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    PresentationPacket,
    ProductCopy,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompiler,
)
from app.guide.understanding.image_contracts import IdentityState
from tests.guide.application.test_image_recommendation_flow import (
    FakeIdentityObserver,
    SequencedIdentityObserver,
    _bundle,
    _catalog,
    _flow_type,
    _turn,
)


class RecordingCopywriter:
    def __init__(self) -> None:
        self.calls: list[PresentationPacket] = []

    def write(
        self,
        packet: PresentationPacket,
    ) -> CopywriterCallResult:
        self.calls.append(packet)
        return CopywriterCallResult(
            draft=CopywriterDraft(
                mode=packet.mode,
                summary_copy="我先按已确认的图片商品和核对事实说明。",
                product_copy=tuple(
                    ProductCopy(
                        slot_id=slot.slot_id,
                        positioning="这款可以放在当前图片结果中继续看。",
                        advisor_reason="具体差异以下方核对事实为准。",
                        used_soft_fact_ids=(),
                    )
                    for slot in packet.slots
                ),
                closing_copy=(
                    "最后结合自己的使用偏好选择。"
                    if any(
                        item.kind == "closing"
                        for item in packet.section_order
                    )
                    else None
                ),
            ),
            usage=SemanticTokenUsage(
                prompt_tokens=60,
                completion_tokens=20,
                total_tokens=80,
                cached_tokens=0,
            ),
            provider="recording",
            model="image-copy",
            latency_ms=10.0,
        )


def _flow(
    *,
    image_count: int = 1,
    observer=None,
):
    service, receipt, _ = _bundle(image_count=image_count)
    catalog = _catalog()
    copywriter = RecordingCopywriter()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=observer or FakeIdentityObserver(),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        presentation_compiler=PresentationCompiler(
            copywriter=copywriter
        ),
        max_results=10,
    )
    return flow, receipt, copywriter


def _event(events, name: str):
    return next(item for item in events if item.event == name)


def test_image_recommendation_emits_presentation_before_message() -> None:
    flow, receipt, copywriter = _flow()

    events = list(
        flow.stream(_turn(receipt, "100元以内找相似款"))
    )
    names = [item.event for item in events]
    presentation = _event(events, "presentation_contract").data

    assert names.index("citations") < names.index(
        "presentation_contract"
    )
    assert names.index("presentation_contract") < names.index(
        "message"
    )
    assert presentation.mode == "recommendation"
    assert presentation.card_display.visible_product_ids == (57, 55)
    assert len(copywriter.calls) == 1


def test_confirmed_identity_shows_only_confirmed_product() -> None:
    flow, receipt, copywriter = _flow()

    events = list(flow.stream(_turn(receipt, "这是什么商品")))
    presentation = _event(events, "presentation_contract").data
    products = _event(events, "products").data.cards

    assert presentation.mode == "image_identity"
    assert presentation.card_display.mode == "single"
    assert [card.product_id for card in products] == [53]
    assert presentation.card_display.visible_product_ids == (53,)
    assert len(copywriter.calls) == 1


@pytest.mark.parametrize(
    ("state", "error_code"),
    (
        (
            IdentityState.LOW_CONFIDENCE,
            "IMAGE_IDENTITY_UNCONFIRMED",
        ),
        (
            IdentityState.AMBIGUOUS_CANDIDATES,
            "IMAGE_IDENTITY_UNCONFIRMED",
        ),
        (
            IdentityState.OCR_CONFLICT,
            "IMAGE_IDENTITY_UNCONFIRMED",
        ),
        (
            IdentityState.VISUAL_UNAVAILABLE,
            "IMAGE_RETRIEVAL_UNAVAILABLE",
        ),
    ),
)
def test_unconfirmed_identity_has_no_cards_or_copywriter_call(
    state: IdentityState,
    error_code: str,
) -> None:
    flow, receipt, copywriter = _flow(
        observer=FakeIdentityObserver(
            identity_state=state,
            candidate_ids=(53, 55),
        )
    )

    events = list(flow.stream(_turn(receipt, "这是什么商品")))

    assert not any(item.event == "products" for item in events)
    assert not any(
        item.event == "presentation_contract" for item in events
    )
    error = _event(events, "error")
    assert error.data.code == error_code
    assert copywriter.calls == []


def test_image_suitability_binds_one_product() -> None:
    flow, receipt, copywriter = _flow()

    events = list(flow.stream(_turn(receipt, "这款适合敏感肌吗")))
    presentation = _event(events, "presentation_contract").data

    assert presentation.mode == "product_knowledge"
    assert presentation.card_display.visible_product_ids == (53,)
    assert len(copywriter.calls) == 1


def test_two_image_comparison_preserves_ordinal_order() -> None:
    flow, receipt, copywriter = _flow(
        image_count=2,
        observer=SequencedIdentityObserver((53, 55)),
    )

    events = list(flow.stream(_turn(receipt, "比较这两张图")))
    presentation = _event(events, "presentation_contract").data
    products = _event(events, "products").data.cards

    assert presentation.mode == "comparison"
    assert [card.product_id for card in products] == [53, 55]
    assert presentation.card_display.visible_product_ids == (53, 55)
    assert len(copywriter.calls) == 1
