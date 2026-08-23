from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.guide.application.general_knowledge_answer import (
    render_general_knowledge_answer,
)
from app.guide.presentation.sse_events import (
    GeneralKnowledgeCitationData,
    GeneralKnowledgeData,
    GeneralKnowledgeEvent,
)
from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeHit,
    GeneralKnowledgePacket,
    GeneralKnowledgeQuery,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from app.guide_runtime.composition import (
    build_general_knowledge_assets,
)


def _query(
    raw_question: str,
    question_meaning: str,
    *,
    safety_sensitive: bool = False,
) -> GeneralKnowledgeQuery:
    return GeneralKnowledgeQuery(
        retrieval_query=raw_question,
        question_meaning=question_meaning,
        topic=None,
        safety_sensitive=safety_sensitive,
        prior_knowledge_ids=(),
        top_k=3,
    )


def _retriever() -> GeneralKnowledgeRetriever:
    return GeneralKnowledgeRetriever(
        build_general_knowledge_assets().blocks
    )


def test_renderer_uses_only_reviewed_public_text() -> None:
    packet = _retriever().retrieve(
        _query(
            "SPF和PA分别是什么意思",
            "询问SPF和PA防晒指标的含义",
        )
    )

    rendered = render_general_knowledge_answer(packet)

    assert rendered.data.educational_only is True
    assert rendered.data.medical_escalation is False
    assert rendered.data.citations
    assert rendered.data.citations[0].knowledge_id == (
        packet.hits[0].block.knowledge_id
    )
    assert rendered.data.citations[0].title == "防晒怎么选"
    assert rendered.data.citations[0].public_excerpt == (
        packet.hits[0].block.public_text
    )
    assert packet.hits[0].block.public_text in rendered.message
    assert "通用知识" in rendered.message
    assert str(Path.cwd()) not in rendered.message
    assert packet.hits[0].block.source_sha256 not in rendered.message
    assert packet.hits[0].block.block_sha256 not in rendered.message


def test_renderer_uses_reviewed_public_text_not_raw_exact_text() -> None:
    packet = _retriever().retrieve(
        _query(
            "SPF和PA分别是什么意思",
            "询问SPF和PA防晒指标的含义",
        )
    )
    first = packet.hits[0]
    public_block = first.block.model_copy(
        update={
            "exact_text": "RAW INTERNAL SOURCE",
            "public_text": "SPF表示对UVB防护能力的标注。",
        }
    )
    packet = packet.model_copy(
        update={
            "hits": (
                first.model_copy(update={"block": public_block}),
            )
        }
    )

    rendered = render_general_knowledge_answer(packet)

    assert "SPF表示对UVB防护能力的标注" in rendered.message
    assert "RAW INTERNAL SOURCE" not in rendered.message
    assert rendered.data.citations[0].public_excerpt == (
        "SPF表示对UVB防护能力的标注。"
    )


def test_renderer_marks_medical_escalation_without_diagnosis() -> None:
    packet = _retriever().retrieve(
        _query(
            "孕期可以用A醇吗",
            "询问孕期使用A醇的安全边界",
            safety_sensitive=True,
        )
    )

    rendered = render_general_knowledge_answer(packet)

    assert rendered.data.medical_escalation is True
    assert any(
        citation.review_decision == "escalation_only"
        for citation in rendered.data.citations
    )
    assert "需要专业判断" in rendered.message
    assert "不能据此诊断或保证安全" in rendered.message


def test_product_redirect_never_becomes_general_product_fact() -> None:
    assets = build_general_knowledge_assets()
    redirect = next(
        block
        for block in assets.blocks
        if block.review_decision == "product_specific_redirect"
    )
    query = _query(
        "这款具体配方怎么样",
        "询问具体商品配方",
    )
    packet = GeneralKnowledgePacket(
        query=query,
        hits=(
            GeneralKnowledgeHit(
                block=redirect,
                score=10.0,
                matched_terms=(),
            ),
        ),
    )

    rendered = render_general_knowledge_answer(packet)

    assert redirect.exact_text not in rendered.message
    assert "请明确具体商品" in rendered.message
    assert "ProductEvidence" not in rendered.message
    assert "Canonical" not in rendered.message
    assert rendered.data.citations[0].review_decision == (
        "product_specific_redirect"
    )
    assert rendered.data.educational_only is True


def test_no_hit_returns_explicit_evidence_gap() -> None:
    query = _query(
        "明天上海天气怎么样",
        "询问上海明日天气",
    )
    rendered = render_general_knowledge_answer(
        GeneralKnowledgePacket(query=query, hits=())
    )

    assert rendered.data.citations == []
    assert rendered.data.medical_escalation is False
    assert "暂时没有足够信息" in rendered.message
    assert "不确定的结论" in rendered.message


def test_general_knowledge_sse_contract_rejects_unknown_fields() -> None:
    citation = GeneralKnowledgeCitationData(
        knowledge_id="a" * 64,
        title="防晒怎么选",
        section_title="怎么选",
        public_excerpt="SPF针对UVB。",
        source_path="data/knowledge_docs/06-防晒怎么选.md",
        review_decision="general_answer",
    )
    data = GeneralKnowledgeData(
        query="SPF是什么意思",
        citations=[citation],
        educational_only=True,
        medical_escalation=False,
    )
    event = GeneralKnowledgeEvent(data=data)

    assert event.event == "general_knowledge"
    assert event.data.citations[0].knowledge_id == "a" * 64
    with pytest.raises(ValidationError):
        GeneralKnowledgeData.model_validate(
            {
                **data.model_dump(mode="json"),
                "manifest_sha256": "b" * 64,
            },
            strict=True,
        )
