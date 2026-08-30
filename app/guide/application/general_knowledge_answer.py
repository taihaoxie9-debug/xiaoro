from __future__ import annotations

from dataclasses import dataclass

from app.guide.presentation.sse_events import (
    GeneralKnowledgeCitationData,
    GeneralKnowledgeCoverageData,
    GeneralKnowledgeData,
)
from app.guide.presentation.public_language_policy import (
    validate_final_public_text,
)
from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeCoverage,
    GeneralKnowledgePacket,
)


@dataclass(frozen=True, slots=True)
class RenderedGeneralKnowledgeAnswer:
    message: str
    data: GeneralKnowledgeData


_RELATION_LABELS = {
    "overview": "基础说明",
    "mechanism": "作用原理",
    "difference": "区别",
    "compatibility": "能否一起使用",
    "usage": "使用方法",
    "selection": "选择方法",
    "identification": "判断方法",
    "safety": "安全边界",
}


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


def _public_coverage(
    packet: GeneralKnowledgePacket,
) -> GeneralKnowledgeCoverageData:
    coverage = packet.coverage
    if coverage is None:
        required_relations = ("overview",)
        covered_relations = required_relations if packet.hits else ()
        coverage = GeneralKnowledgeCoverage(
            required_concept_ids=(),
            covered_concept_ids=(),
            required_entity_ids=(),
            covered_entity_ids=(),
            required_relation_intents=required_relations,
            covered_relation_intents=covered_relations,
            missing_concept_ids=(),
            missing_entity_ids=(),
            missing_relation_intents=(
                ()
                if covered_relations
                else required_relations
            ),
            complete=bool(covered_relations),
        )
    return GeneralKnowledgeCoverageData.model_validate(
        coverage.model_dump(mode="json"),
        strict=True,
    )


def render_general_knowledge_answer(
    packet: GeneralKnowledgePacket,
) -> RenderedGeneralKnowledgeAnswer:
    if not isinstance(packet, GeneralKnowledgePacket):
        raise TypeError("packet must be GeneralKnowledgePacket")
    coverage = _public_coverage(packet)
    citations = [_citation(hit) for hit in packet.hits]
    comparison_blocked = (
        "difference" in coverage.required_relation_intents
        and bool(coverage.missing_entity_ids)
    )
    answer_blocks = [
        hit.block
        for hit in packet.hits
        if hit.block.review_decision == "general_answer"
        and "answer" in hit.block.allowed_uses
        and not comparison_blocked
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
    if packet.hits and coverage.missing_relation_intents:
        if coverage.missing_relation_intents == ["compatibility"]:
            parts.append(
                "现有可靠资料没有直接说明这组对象能否一起使用，"
                "这里不根据各自介绍推导兼容性结论。"
            )
        else:
            missing = "、".join(
                _RELATION_LABELS[relation]
                for relation in coverage.missing_relation_intents
            )
            parts.append(
                f"现有审核资料暂时不足以覆盖：{missing}。"
                "这里不补充未经审核的结论。"
            )
    if comparison_blocked:
        parts.append(
            "当前缺少部分对象的审核资料，不能据此给出区别结论。"
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
            coverage=coverage,
            educational_only=True,
            medical_escalation=medical_escalation,
        ),
    )


__all__ = [
    "RenderedGeneralKnowledgeAnswer",
    "render_general_knowledge_answer",
]
