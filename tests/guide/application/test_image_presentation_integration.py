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
from app.guide_runtime.composition import build_review_evidence_reader
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
    review_evidence=None,
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
        review_evidence=review_evidence,
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


def test_confirmed_identity_preserves_canonical_direct_display_facts() -> None:
    flow, receipt, copywriter = _flow(
        observer=FakeIdentityObserver(candidate_ids=(38, 91)),
    )

    events = list(flow.stream(_turn(receipt, "这是什么商品")))
    presentation = _event(events, "presentation_contract").data
    product = _event(events, "products").data.cards[0]
    product_section = next(
        section
        for section in presentation.sections
        if section.kind == "product"
    )
    slot = copywriter.calls[0].slots[0]

    assert {
        fact.field_key
        for fact in product.category_facts
        if fact.state == "known"
    } >= {
        "efficacy",
        "ingredients_present",
        "suitable_skin",
    }
    assert {
        fact.field_key for fact in slot.approved_soft_facts
    } >= {
        "efficacy",
        "ingredients_present",
        "suitable_skin",
    }
    assert {
        fact.label for fact in product_section.direct_facts
    } >= {"核心成分", "适合肤质"}


def test_confirmed_identity_passes_approved_reviews_to_copywriter() -> None:
    flow, receipt, copywriter = _flow(
        observer=FakeIdentityObserver(candidate_ids=(49, 46)),
        review_evidence=build_review_evidence_reader(),
    )

    list(flow.stream(_turn(receipt, "这是什么商品")))
    slot = copywriter.calls[0].slots[0]

    assert slot.product_id == 49
    assert any(
        fact.attribution == "consumer_report"
        for fact in slot.approved_soft_facts
    )


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


def test_image_suitability_preserves_facts_without_inventing_match() -> None:
    flow, receipt, _ = _flow(
        observer=FakeIdentityObserver(candidate_ids=(38, 91)),
    )

    events = list(flow.stream(_turn(receipt, "这款适合敏感肌吗")))
    product = _event(events, "products").data.cards[0]

    assert product.product_id == 38
    assert product.skin_match == "unknown"
    assert {
        fact.field_key
        for fact in product.category_facts
        if fact.state == "known"
    } >= {
        "efficacy",
        "ingredients_present",
        "suitable_skin",
    }


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


def test_two_image_comparison_preserves_order_and_known_fact_states() -> None:
    flow, receipt, _ = _flow(
        image_count=2,
        observer=SequencedIdentityObserver((38, 91)),
    )

    events = list(flow.stream(_turn(receipt, "比较这两张图")))
    products = _event(events, "products").data.cards

    assert [product.product_id for product in products] == [38, 91]
    assert [product.skin_match for product in products] == [
        "unknown",
        "unknown",
    ]
    assert {
        fact.field_key
        for fact in products[0].category_facts
        if fact.state == "known"
    } >= {
        "efficacy",
        "ingredients_present",
        "suitable_skin",
    }
    assert {
        fact.field_key
        for fact in products[1].category_facts
        if fact.state == "known"
    } >= {"efficacy", "suitable_skin"}
    assert not any(
        fact.field_key == "ingredients_present"
        and fact.state == "known"
        for fact in products[1].category_facts
    )
