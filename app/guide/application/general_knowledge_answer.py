from __future__ import annotations

from dataclasses import dataclass

from app.guide.presentation.sse_events import (
    GeneralKnowledgeCitationData,
    GeneralKnowledgeData,
)
from app.guide.presentation.public_language_policy import (
    validate_final_public_text,
)
from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgePacket,
)


@dataclass(frozen=True, slots=True)
class RenderedGeneralKnowledgeAnswer:
    message: str
    data: GeneralKnowledgeData


def _citation(hit) -> GeneralKnowledgeCitationData:
    block = hit.block
    return GeneralKnowledgeCitationData(
        knowledge_id=block.knowledge_id,
        title=block.title,
        section_title=block.section_title,
        public_excerpt=block.public_text,
        source_path=block.source_path,
        review_decision=block.review_decision,
    )


def render_general_knowledge_answer(
    packet: GeneralKnowledgePacket,
) -> RenderedGeneralKnowledgeAnswer:
    if not isinstance(packet, GeneralKnowledgePacket):
        raise TypeError("packet must be GeneralKnowledgePacket")
    citations = [_citation(hit) for hit in packet.hits]
    answer_blocks = [
        hit.block
        for hit in packet.hits
        if hit.block.review_decision == "general_answer"
        and "answer" in hit.block.allowed_uses
    ]
    medical_escalation = any(
        hit.block.review_decision == "escalation_only"
        and "medical_escalation" in hit.block.allowed_uses
        for hit in packet.hits
    )
    has_product_redirect = any(
        hit.block.review_decision == "product_specific_redirect"
        for hit in packet.hits
    )

    parts: list[str] = []
    if answer_blocks:
        parts.append(
            "下面先讲通用知识，不把它当作具体商品结论："
        )
        parts.extend(
            (
                f"【{block.title} / {block.section_title}】\n"
                f"{block.public_text}"
            )
            for block in answer_blocks
        )
    if medical_escalation:
        parts.append(
            "这个问题包含需要专业判断的边界；这里不能据此诊断"
            "或保证安全。请结合产品官方"
            "说明，并向正规医疗专业人士确认。"
        )
    if not answer_blocks and has_product_redirect:
        parts.append(
            "相关内容涉及具体商品配方、版本、价格或横向结论，"
            "不能直接当作通用知识回答；"
            "请明确具体商品后再结合对应资料判断。"
        )
    if not parts:
        parts.append(
            "这类通用知识暂时没有足够信息，先不补充不确定的结论。"
        )
    return RenderedGeneralKnowledgeAnswer(
        message=validate_final_public_text("\n\n".join(parts)),
        data=GeneralKnowledgeData(
            query=packet.query.question_meaning,
            citations=citations,
            educational_only=True,
            medical_escalation=medical_escalation,
        ),
    )


__all__ = [
    "RenderedGeneralKnowledgeAnswer",
    "render_general_knowledge_answer",
]
