from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.application.product_evidence_answer import (
    EvidenceAnswerPlan,
    build_product_knowledge_answer_plan,
    render_catalog_product_facts_answer,
    render_product_evidence_fact,
    render_product_evidence_answer,
)
from app.guide.presentation.contracts import (
    DisplayCategoryFact,
    ProductCard,
)
from app.guide.presentation.public_fact_contracts import (
    ProductPublicFactProjection,
    ProjectedPublicFact,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.product_evidence_assets import (
    ProductEvidenceBlock,
    product_evidence_id,
)
from app.guide.retrieval.product_evidence_retrieval import (
    EvidencePacket,
    EvidenceQuery,
    EvidenceSelection,
    prepare_evidence_search,
)


def _query(
    *,
    source_text: str,
    question_meaning: str,
) -> EvidenceQuery:
    return EvidenceQuery(
        product_ids=(78,),
        search=prepare_evidence_search(
            source_text=source_text,
            question_meaning=question_meaning,
        ),
        safety_sensitive=False,
    )


def _block(
    *,
    label: str,
    exact_text: str,
    plain_meaning: str | None = None,
    sample_size: int | None = None,
    method: str | None = None,
    disclaimer: str | None = None,
    relations: tuple[dict[str, str], ...] = (),
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
        "plain_meaning": plain_meaning or exact_text,
        "relations": relations,
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
        query=_query(
            source_text="这个测试靠谱吗？",
            question_meaning="询问商品测试证据",
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

    assert "品牌提供的测试" in answer
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
    assert "商品信息净含量50ml" in answer
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


def test_product_evidence_answer_sanitizes_source_mechanical_language() -> None:
    specification = _block(
        label="product_specification",
        exact_text=(
            "资生堂水动力蓝胖子防晒乳50ml，SPF50+，PA++++，日本原装进口"
        ),
        plain_meaning=(
            "跨境详情页给出商品名、50ml、SPF50+、PA++++、日本产地"
            "和通用保质期。"
        ),
        disclaimer=(
            "这是跨境页面版本，不能与PID56国行中文背标的名称、注册号"
            "或成分无条件混用；具体有效期看实物批次"
        ),
    )
    merchant = _block(
        label="merchant_claim",
        exact_text="水润质地、轻薄肤感、温和舒适、清爽易推开",
        plain_meaning=(
            "跨境页面概述水润质地、轻薄肤感和清爽易推开的肤感。"
        ),
        disclaimer=(
            "“温和”是商家肤感宣传，成分仅为概述并非完整INCI，"
            "不能用于绝对成分排除或安全保证"
        ),
    )

    answer = render_product_evidence_answer(
        _packet(specification, merchant),
        product_names={78: "资生堂蓝胖子防晒"},
    )

    assert "资生堂蓝胖子防晒" in answer
    assert "50ml" in answer
    assert "SPF50+" in answer
    assert "轻薄肤感" in answer
    for forbidden in ("详情页", "页面", "PID56", "商家宣传", "完整INCI"):
        assert forbidden not in answer


def test_catalog_facts_answer_uses_known_public_fields_when_evidence_is_empty() -> None:
    card = ProductCard(
        product_id=91,
        category_profile=CategoryProfile.SKINCARE,
        category_facts=(
            DisplayCategoryFact(
                field_key="efficacy",
                label="功效",
                value=("修护屏障", "舒缓泛红"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="ingredients_present",
                label="确认含有成分",
                value=("神经酰胺", "泛醇"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="suitable_skin",
                label="适用肤质",
                value=("多种肤质", "敏感肌"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="texture",
                label="质地",
                value=("轻盈", "不粘腻", "易吸收"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="usage",
                label="使用方法",
                value="洁面后取适量轻柔按摩",
                state="known",
            ),
        ),
        name="玉泽皮肤屏障修护精华乳",
        brand="玉泽",
        category="精华",
        price=None,
        skin_match="unknown",
        matched_efficacies=[],
        fact_warnings=[],
    )

    answer = render_catalog_product_facts_answer(
        card,
        question="这款的质地、核心成分、适合肤质和使用顺序是什么？",
    )

    assert "质地：轻盈、不粘腻、易吸收" in answer
    assert "核心成分：神经酰胺、泛醇" in answer
    assert "适合肤质：多种肤质、敏感肌" in answer
    assert "使用方法：洁面后取适量轻柔按摩" in answer
    assert "没有与这个问题直接相关" not in answer
def test_product_evidence_answer_never_renders_raw_exact_text() -> None:
    block = _block(
        label="merchant_claim",
        exact_text="一抹根源灭火，闪褪泛红",
        plain_meaning="品牌主打舒缓泛红与屏障修护",
    )

    answer = render_product_evidence_answer(
        _packet(block),
        product_names={78: "测试精华"},
    )

    assert "品牌主打舒缓泛红与屏障修护" in answer
    assert "一抹根源灭火" not in answer


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
        query=_query(
            source_text="开封后能放多久？",
            question_meaning="询问开封后的保存期限",
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
        "薇诺娜舒敏保湿丝滑面膜暂时没有与这个问题直接相关的明确信息。"
    )


def test_answer_renders_code_controlled_variant_ambiguity() -> None:
    block = _block(
        label="product_specification",
        exact_text="净含量100ml",
    )
    packet = EvidencePacket(
        query=_query(
            source_text="这瓶多大？",
            question_meaning="询问容量规格",
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
            "这款有100ml与35ml变体，购买前请核对具体规格。",
        ),
    )

    answer = render_product_evidence_answer(
        packet,
        product_names={78: "测试香水"},
    )

    assert "净含量100ml" in answer
    assert "100ml与35ml变体" in answer
    assert "核对具体规格" in answer


def _projected_fact(
    fact_id: str,
    field_key: str,
    label: str,
    value: str,
    *,
    source_kind: str = "category",
) -> ProjectedPublicFact:
    return ProjectedPublicFact(
        fact_id=fact_id,
        product_id=39,
        field_key=field_key,
        label=label,
        display_value=value,
        source_refs=(f"urn:{fact_id}",),
        source_kind=source_kind,
        attribution=(
            "merchant_claim"
            if source_kind == "merchant"
            else "verified_fact"
        ),
    )


def test_product_knowledge_answer_plan_uses_category_and_evidence_ids() -> None:
    projection = ProductPublicFactProjection(
        product_id=39,
        facts=(
            _projected_fact(
                "category:39:texture",
                "texture",
                "质地",
                "轻盈凝露",
            ),
            _projected_fact(
                "evidence:39:brand-main",
                "brand_main",
                "品牌主打",
                "轻盈修护抗老",
                source_kind="merchant",
            ),
            _projected_fact(
                "category:39:ingredients_present",
                "ingredients_present",
                "核心成分",
                "海茴香精粹、植物抗老多肽",
            ),
        ),
    )

    plan = build_product_knowledge_answer_plan(
        projection=projection,
        question="第二款的质地适合什么肤质？",
        requested_dimensions=("texture",),
    )

    assert "轻盈凝露" in plan.answer_text
    assert "海茴香精粹" in plan.answer_text
    assert "category:39:texture" in plan.used_fact_ids
    assert "evidence:39:brand-main" in plan.used_fact_ids
    assert plan.direct_facts


def test_product_knowledge_answer_plan_names_honest_missing_field() -> None:
    plan = build_product_knowledge_answer_plan(
        projection=ProductPublicFactProjection(
            product_id=39,
            facts=(),
        ),
        question="这款的质地怎么样？",
        requested_dimensions=("texture",),
    )

    assert plan.answer_text == "这款目前没有明确标注的质地信息。"
    for forbidden in (
        "资料不足",
        "证据不足",
        "当前卡片记录",
        "页面",
        "系统",
        "不知道",
    ):
        assert forbidden not in plan.answer_text


def test_product_knowledge_answer_names_missing_requested_dimension(
) -> None:
    plan = build_product_knowledge_answer_plan(
        projection=ProductPublicFactProjection(
            product_id=39,
            facts=(
                _projected_fact(
                    "category:39:efficacy",
                    "efficacy",
                    "功效方向",
                    "舒缓泛红",
                ),
            ),
        ),
        question="它的质地和功效是什么？",
        requested_dimensions=("efficacy", "texture"),
    )

    assert "功效方向：舒缓泛红" in plan.answer_text
    assert "没有明确标注的质地信息" in plan.answer_text
    assert plan.used_fact_ids == ("category:39:efficacy",)


def test_product_knowledge_answer_plan_prioritizes_selected_evidence() -> None:
    projection = ProductPublicFactProjection(
        product_id=39,
        facts=(
            _projected_fact(
                "merchant:39:brand-main",
                "brand_main",
                "品牌主打",
                "保湿舒缓",
                source_kind="merchant",
            ),
            _projected_fact(
                "category:39:texture",
                "texture",
                "质地",
                "服帖",
            ),
            _projected_fact(
                "evidence:39:consumer-report",
                "consumer_report",
                "使用反馈",
                "35名消费者自评认为不易滑落。",
                source_kind="review",
            ),
        ),
    )

    plan = build_product_knowledge_answer_plan(
        projection=projection,
        question="这个面膜布会不会老往下掉？",
        requested_dimensions=(),
    )

    assert plan.direct_facts[0].fact_id == (
        "evidence:39:consumer-report"
    )
    assert "消费者自评" in plan.answer_text
    assert "不易滑落" in plan.answer_text


def test_product_knowledge_answer_plan_does_not_fill_missing_dimension() -> None:
    projection = ProductPublicFactProjection(
        product_id=39,
        facts=(
            _projected_fact(
                "merchant:39:brand-main",
                "brand_main",
                "品牌主打",
                "保湿舒缓",
                source_kind="merchant",
            ),
            _projected_fact(
                "category:39:texture",
                "texture",
                "质地",
                "服帖",
            ),
        ),
    )

    plan = build_product_knowledge_answer_plan(
        projection=projection,
        question="这款保修几年？",
        requested_dimensions=("warranty",),
    )

    assert plan.answer_text == "这款目前没有明确标注的保修信息。"
    assert plan.direct_facts == ()
    assert plan.used_fact_ids == ()


def test_product_knowledge_projection_accepts_dense_approved_universe() -> None:
    projection = ProductPublicFactProjection(
        product_id=39,
        facts=tuple(
            _projected_fact(
                f"merchant:39:fact-{index}",
                "product_information",
                "商品信息",
                f"公开事实 {index}",
                source_kind="merchant",
            )
            for index in range(40)
        ),
    )

    assert len(projection.facts) == 40


def test_public_evidence_fact_sanitizes_qualifier_source_language() -> None:
    block = _block(
        label="consumer_self_report",
        exact_text="87%消费者认可提亮肌肤",
        method="消费者认可，页面未披露样本量和周期",
        disclaimer="结果仅供参考，实际结果因人而异",
    )

    answer = render_product_evidence_fact(
        block,
        product_name="测试洁面乳",
    )

    assert "消费者自评" in answer
    assert "商品信息未披露样本量和周期" in answer
    assert "页面" not in answer


def test_public_evidence_fact_keeps_reviewed_relation_values() -> None:
    block = _block(
        label="packaging_information",
        exact_text="RAW OCR TRANSCRIPT MUST NOT RENDER",
        plain_meaning="包装正面确认防晒等级和防水技术标识。",
        relations=(
            {
                "subject": "包装正面",
                "predicate": "observed_package_marking",
                "object": (
                    "SPF50+、PA++++、"
                    "Very Water-Resistant、50mL"
                ),
            },
        ),
    )

    answer = render_product_evidence_fact(
        block,
        product_name="测试防晒乳",
    )

    assert "Very Water-Resistant" in answer
    assert "RAW OCR TRANSCRIPT" not in answer


def test_public_evidence_fact_sanitizes_evidence_audit_terms() -> None:
    block = _block(
        label="merchant_cited_test",
        exact_text="测试结果",
        disclaimer=(
            "当前证据不能当作临床治疗证据或临床舒缓证据"
        ),
    )

    answer = render_product_evidence_fact(
        block,
        product_name="测试精华",
    )

    assert "当前信息" in answer
    assert "临床治疗结论" in answer
    assert "临床舒缓结论" in answer
    assert "证据" not in answer
