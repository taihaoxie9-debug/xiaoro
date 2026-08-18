from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.application.product_evidence_answer import (
    EvidenceAnswerPlan,
    render_product_evidence_answer,
)
from app.guide.retrieval.product_evidence_assets import (
    ProductEvidenceBlock,
    product_evidence_id,
)
from app.guide.retrieval.product_evidence_retrieval import (
    EvidencePacket,
    EvidenceQuery,
    EvidenceSelection,
)


def _block(
    *,
    label: str,
    exact_text: str,
    sample_size: int | None = None,
    method: str | None = None,
    disclaimer: str | None = None,
) -> ProductEvidenceBlock:
    forbidden = ["hard_filter", "safety_guarantee"]
    if label == "consumer_self_report":
        forbidden.append("clinical_effectiveness")
    payload: dict[str, object] = {
        "product_id": 78,
        "subject_scope": "exact_product",
        "variant_scope": None,
        "management_label": label,
        "transcription_basis": "visual_transcription",
        "exact_text": exact_text,
        "plain_meaning": exact_text,
        "relations": [],
        "qualifiers": {
            "sample_size": sample_size,
            "population": "中国敏感肌消费者" if sample_size else None,
            "method": method,
            "baseline": None,
            "duration": None,
            "disclaimer": disclaimer,
            "footnotes": [],
        },
        "free_descriptors": [],
        "review_status": "accepted",
        "allowed_uses": ["answer", "display"],
        "forbidden_uses": forbidden,
        "review_rationale": "回答测试。",
        "selection_review": {
            "decision": "answer_only",
            "visual_confirmed": True,
            "rationale": "回答夹具不授权选择用途。",
            "projections": [],
        },
        "source": {
            "source_file": "detail_78_ocr.json",
            "source_sha256": "1" * 64,
            "image_file": "004.jpg",
            "image_index": 4,
            "image_sha256": "2" * 64,
            "source_locator": (
                "urn:xiaoro:product-detail-image:pid:78:"
                f"source-sha256:{'1' * 64}:image-sha256:{'2' * 64}"
            ),
            "source_url": "https://example.com/004.jpg",
            "recovery_status": "source_record",
            "resolved_image_file": "004.jpg",
            "image_region": [0, 0, 790, 1364],
        },
        "supporting_sources": [],
    }
    return ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )


def _packet(*blocks: ProductEvidenceBlock) -> EvidencePacket:
    return EvidencePacket(
        query=EvidenceQuery(
            product_ids=(78,),
            raw_question="这个测试靠谱吗？",
            question_meaning="询问商品测试证据",
            safety_sensitive=False,
        ),
        selected=tuple(
            EvidenceSelection(
                evidence=block,
                score=1.0,
                reasons=("test",),
            )
            for block in blocks
        ),
        safety_caveats=(),
        missing_aspects=(),
    )


def test_consumer_self_report_keeps_sample_and_method_language() -> None:
    block = _block(
        label="consumer_self_report",
        exact_text="91%消费者认同水润舒缓",
        sample_size=35,
        method="消费者自评",
        disclaimer="结果仅供参考，实际结果因人而异",
    )
    packet = _packet(block)

    answer = render_product_evidence_answer(
        packet,
        product_names={78: "薇诺娜舒敏保湿丝滑面膜"},
    )

    assert "35名中国敏感肌消费者" in answer
    assert "消费者自评" in answer
    assert "91%消费者认同水润舒缓" in answer
    assert "不是客观仪器测试" in answer
    assert "实际结果因人而异" in answer


def test_merchant_cited_test_is_attributed_without_endorsement() -> None:
    block = _block(
        label="merchant_cited_test",
        exact_text="热风刺激后皮肤红区面积降低49.5%",
        sample_size=34,
        method="仪器测试",
        disclaimer="实际结果因人而异",
    )

    answer = render_product_evidence_answer(
        _packet(block),
        product_names={78: "薇诺娜舒敏保湿丝滑面膜"},
    )

    assert "品牌给出的测试" in answer
    assert "34名中国敏感肌消费者" in answer
    assert "降低49.5%" in answer
    assert "未经独立核实" not in answer


def test_product_evidence_answer_uses_public_advisor_language() -> None:
    safety = _block(
        label="safety_transcript",
        exact_text="敏感肌适用",
    )
    specification = _block(
        label="product_specification",
        exact_text="净含量50ml",
    )

    answer = render_product_evidence_answer(
        _packet(safety, specification),
        product_names={78: "测试精华"},
    )

    assert "品牌将「敏感肌适用」作为适用说明" in answer
    assert "商品信息「净含量50ml」" in answer
    assert not any(
        term in answer
        for term in (
            "强证据",
            "硬筛",
            "放行",
            "未经独立核实",
            "页面记录版本",
        )
    )


def test_answer_plan_cannot_reference_evidence_outside_packet() -> None:
    block = _block(
        label="merchant_claim",
        exact_text="膜布轻薄服帖",
    )
    packet = _packet(block)
    plan = EvidenceAnswerPlan(
        evidence_ids=("f" * 64,),
        detail_level="concise",
    )

    with pytest.raises(
        ValueError,
        match="answer plan references evidence outside packet",
    ):
        render_product_evidence_answer(
            packet,
            product_names={78: "薇诺娜舒敏保湿丝滑面膜"},
            plan=plan,
        )


def test_answer_plan_rejects_duplicate_or_invalid_ids() -> None:
    with pytest.raises(ValidationError):
        EvidenceAnswerPlan(
            evidence_ids=("bad",),
            detail_level="concise",
        )

    with pytest.raises(
        ValidationError,
        match="evidence IDs must be unique",
    ):
        EvidenceAnswerPlan(
            evidence_ids=("a" * 64, "a" * 64),
            detail_level="detailed",
        )


def test_missing_packet_returns_explicit_no_evidence_message() -> None:
    packet = EvidencePacket(
        query=EvidenceQuery(
            product_ids=(78,),
            raw_question="开封后能放多久？",
            question_meaning="询问开封后的保存期限",
            safety_sensitive=False,
        ),
        selected=(),
        safety_caveats=(),
        missing_aspects=("未找到相关证据。",),
    )

    answer = render_product_evidence_answer(
        packet,
        product_names={78: "薇诺娜舒敏保湿丝滑面膜"},
    )

    assert answer == (
        "当前已审核的薇诺娜舒敏保湿丝滑面膜商品资料中，"
        "未找到与这个问题直接相关的证据。"
    )


def test_answer_renders_code_controlled_variant_ambiguity() -> None:
    block = _block(
        label="product_specification",
        exact_text="净含量100ml",
    )
    packet = EvidencePacket(
        query=EvidenceQuery(
            product_ids=(78,),
            raw_question="这瓶多大？",
            question_meaning="询问容量规格",
            safety_sensitive=False,
        ),
        selected=(
            EvidenceSelection(
                evidence=block,
                score=1.0,
                reasons=("test",),
            ),
        ),
        safety_caveats=(),
        missing_aspects=(),
        ambiguity_reasons=(
            "已审核证据包含100ml与35ml变体，请核对具体规格。",
        ),
    )

    answer = render_product_evidence_answer(
        packet,
        product_names={78: "测试香水"},
    )

    assert "净含量100ml" in answer
    assert "100ml与35ml变体" in answer
    assert "核对具体规格" in answer
