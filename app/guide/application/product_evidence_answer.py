from __future__ import annotations

import re
from typing import Literal, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.guide.retrieval.product_evidence_assets import ProductEvidenceBlock
from app.guide.retrieval.product_evidence_retrieval import EvidencePacket


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EvidenceAnswerPlan(_StrictFrozenModel):
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    detail_level: Literal["concise", "detailed"]

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def freeze_evidence_ids(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        if any(
            re.fullmatch(r"[0-9a-f]{64}", evidence_id) is None
            for evidence_id in self.evidence_ids
        ):
            raise ValueError("evidence IDs must be SHA-256 values")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        return self


def render_product_evidence_answer(
    packet: EvidencePacket,
    *,
    product_names: Mapping[int, str],
    plan: EvidenceAnswerPlan | None = None,
) -> str:
    if not isinstance(packet, EvidencePacket):
        raise TypeError("packet must be EvidencePacket")
    if not isinstance(product_names, Mapping):
        raise TypeError("product_names must be a mapping")
    selected_by_id = {
        item.evidence.evidence_id: item.evidence
        for item in packet.selected
    }
    if plan is None:
        evidence = [item.evidence for item in packet.selected]
    else:
        if not isinstance(plan, EvidenceAnswerPlan):
            raise TypeError("plan must be EvidenceAnswerPlan")
        unknown = set(plan.evidence_ids) - set(selected_by_id)
        if unknown:
            raise ValueError(
                "answer plan references evidence outside packet"
            )
        evidence = [
            selected_by_id[evidence_id]
            for evidence_id in plan.evidence_ids
        ]
    if not evidence:
        product_name = _single_product_name(packet, product_names)
        return (
            f"当前已审核的{product_name}商品资料中，"
            "未找到与这个问题直接相关的证据。"
        )

    lines = [
        _render_evidence(
            block,
            product_name=_product_name(block.product_id, product_names),
        )
        for block in evidence
    ]
    lines.extend(packet.ambiguity_reasons)
    lines.extend(packet.safety_caveats)
    return "\n".join(lines)


def _render_evidence(
    block: ProductEvidenceBlock,
    *,
    product_name: str,
) -> str:
    qualifiers = block.qualifiers
    sample = ""
    if qualifiers.sample_size is not None:
        sample = f"{qualifiers.sample_size}名"
        if qualifiers.population is not None:
            sample += qualifiers.population
    method = qualifiers.method or ""
    disclaimer = qualifiers.disclaimer

    if block.management_label == "consumer_self_report":
        context = sample or "消费者"
        if method and method not in context:
            context = f"{context}的{method}"
        rendered = (
            f"{product_name}：品牌给出的使用反馈来自{context}，"
            f"原文为「{block.exact_text}」。"
            "这是消费者自评，不是客观仪器测试；个人感受还会受肤况和"
            "使用方式影响"
        )
        if disclaimer:
            rendered += f"；{disclaimer}"
        return rendered + "。"
    if block.management_label == "merchant_cited_test":
        qualifier_parts = [
            value
            for value in (sample, method)
            if value
        ]
        qualifier_text = (
            f"（{'，'.join(qualifier_parts)}）"
            if qualifier_parts
            else ""
        )
        rendered = (
            f"{product_name}：品牌给出的测试{qualifier_text}提到"
            f"「{block.exact_text}」"
        )
        if disclaimer:
            rendered += f"；{disclaimer}"
        return rendered + "。"
    if block.management_label == "safety_transcript":
        return (
            f"{product_name}：品牌将「{block.exact_text}」作为适用说明。"
            "如果正处于泛红、刺痛或破损期，先暂停尝试；"
            "皮肤稳定后再局部试用。"
        )
    prefix_by_label = {
        "merchant_claim": "品牌主打",
        "packaging_information": "包装说明",
        "faq": "品牌问答",
        "usage": "包装用法",
        "brand_research": "品牌资料",
        "product_specification": "商品信息",
        "unclassified": "商品资料",
    }
    prefix = prefix_by_label[block.management_label]
    rendered = f"{product_name}：{prefix}「{block.exact_text}」"
    return rendered + "。"


def _single_product_name(
    packet: EvidencePacket,
    product_names: Mapping[int, str],
) -> str:
    product_id = packet.query.product_ids[0]
    return _product_name(product_id, product_names)


def _product_name(
    product_id: int,
    product_names: Mapping[int, str],
) -> str:
    value = product_names.get(product_id)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"商品{product_id}"


__all__ = [
    "EvidenceAnswerPlan",
    "render_product_evidence_answer",
]
