from __future__ import annotations

import re
from collections.abc import Collection
from typing import Literal, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.contracts import ProductCard
from app.guide.presentation.product_detail_selection import (
    select_product_detail_facts,
)
from app.guide.presentation.public_fact_contracts import (
    ProductPublicFactProjection,
    ProjectedPublicFact,
)
from app.guide.presentation.public_language_policy import (
    validate_final_public_text,
)
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


class ProductKnowledgeAnswerPlan(_StrictFrozenModel):
    answer_text: str = Field(min_length=1, max_length=1600)
    direct_facts: tuple[ProjectedPublicFact, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    used_fact_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )

    @field_validator("direct_facts", "used_fact_ids", mode="before")
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_fact_ids(self) -> Self:
        expected = tuple(
            fact.fact_id for fact in self.direct_facts
        )
        if self.used_fact_ids != expected:
            raise ValueError(
                "knowledge answer IDs must match direct facts"
            )
        return self


_PUBLIC_LABEL_BY_KEY = {
    "brand_main": "品牌主打",
    "efficacy": "功效方向",
    "ingredients_present": "核心成分",
    "suitable_skin": "适合肤质",
    "texture": "质地",
    "usage": "使用方法",
    "net_content": "规格",
    "specification": "规格",
    "warranty": "保修",
}
_PUBLIC_RELATION_CONNECTOR = {
    "merchant_shade_correspondence": "对应",
}


def build_product_knowledge_answer_plan(
    *,
    projection: ProductPublicFactProjection,
    question: str,
    requested_dimensions: Collection[str],
) -> ProductKnowledgeAnswerPlan:
    if not isinstance(projection, ProductPublicFactProjection):
        raise TypeError(
            "projection must be ProductPublicFactProjection"
        )
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be nonempty")
    dimensions = tuple(requested_dimensions)
    requested_fields = tuple(dict.fromkeys(
        item.split(".", 1)[0] for item in dimensions
    ))
    selected = select_product_detail_facts(
        projection=projection,
        responsibility=Responsibility.PRODUCT_KNOWLEDGE,
        requested_dimensions=dimensions,
    )
    available_fields = {
        fact.field_key for fact in projection.facts
    }
    missing_fields = tuple(
        field_key
        for field_key in requested_fields
        if field_key not in available_fields
    )
    if selected:
        lines = [
            f"{fact.label}：{fact.display_value}"
            for fact in selected
        ]
        lines.extend(
            "这款目前没有明确标注的"
            f"{_PUBLIC_LABEL_BY_KEY.get(field_key, '相关')}信息。"
            for field_key in missing_fields
        )
        answer_text = "\n".join(lines)
    else:
        missing = missing_fields or ("相关",)
        answer_text = "\n".join(
            "这款目前没有明确标注的"
            f"{_PUBLIC_LABEL_BY_KEY.get(field_key, '相关')}信息。"
            for field_key in missing
        )
    return ProductKnowledgeAnswerPlan(
        answer_text=validate_final_public_text(answer_text),
        direct_facts=selected,
        used_fact_ids=tuple(fact.fact_id for fact in selected),
    )


def resolve_product_knowledge_dimensions(
    question: str,
) -> tuple[str, ...]:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be nonempty")
    keyword_by_field = {
        "brand_main": (
            "品牌主打",
            "主打",
            "定位",
        ),
        "efficacy": (
            "功效",
            "修护",
            "提亮",
            "抗老",
            "作用",
        ),
        "ingredients_present": (
            "成分",
            "配方",
            "含不含",
            "核心成分",
        ),
        "suitable_skin": (
            "适合",
            "肤质",
            "敏感",
            "泛红",
            "油皮",
            "干皮",
        ),
        "texture": (
            "质地",
            "肤感",
            "清爽",
            "黏",
            "厚重",
            "成膜",
        ),
        "usage": (
            "用法",
            "使用",
            "顺序",
            "早上",
            "晚上",
            "怎么涂",
        ),
        "net_content": (
            "规格",
            "容量",
            "多少毫升",
            "多大",
        ),
        "warranty": (
            "保修",
            "质保",
        ),
    }
    return tuple(
        field_key
        for field_key, keywords in keyword_by_field.items()
        if any(keyword in question for keyword in keywords)
    )


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
        return validate_final_public_text(
            f"{product_name}暂时没有与这个问题直接相关的明确信息。"
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
    return validate_final_public_text("\n".join(lines))


def render_catalog_product_facts_answer(
    card: ProductCard,
    *,
    question: str,
) -> str:
    if not isinstance(card, ProductCard):
        raise TypeError("card must be ProductCard")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be nonempty")

    requested = _requested_fact_keys(question)
    ordered_keys = (
        "efficacy",
        "ingredients_present",
        "suitable_skin",
        "texture",
        "usage",
    )
    facts = {
        fact.field_key: fact
        for fact in card.category_facts
        if fact.state == "known" and fact.value is not None
    }
    selected = [
        facts[field_key]
        for field_key in ordered_keys
        if field_key in facts
        and (not requested or field_key in requested)
    ]
    if not selected:
        product_name = (
            card.display_name
            or card.name
            or f"商品{card.product_id}"
        )
        return validate_final_public_text(
            f"{product_name}暂时没有与这个问题直接相关的明确信息。"
        )

    product_name = (
        card.display_name
        or card.name
        or f"商品{card.product_id}"
    )
    public_label_by_key = {
        "efficacy": "功效方向",
        "ingredients_present": "核心成分",
        "suitable_skin": "适合肤质",
        "texture": "质地",
        "usage": "使用方法",
    }
    lines = [f"{product_name}："]
    for fact in selected:
        lines.append(
            f"{public_label_by_key.get(fact.field_key, fact.label)}："
            f"{_category_fact_value_text(fact.value)}"
        )
    return validate_final_public_text("\n".join(lines))


def _render_evidence(
    block: ProductEvidenceBlock,
    *,
    product_name: str,
) -> str:
    qualifiers = block.qualifiers
    population = (
        _sanitize_public_source_language(qualifiers.population)
        if qualifiers.population is not None
        else None
    )
    sample = ""
    if qualifiers.sample_size is not None:
        sample = f"{qualifiers.sample_size}名"
        if population is not None:
            sample += population
    method = (
        _sanitize_public_source_language(qualifiers.method)
        if qualifiers.method is not None
        else ""
    )
    disclaimer = (
        _sanitize_public_source_language(qualifiers.disclaimer)
        if qualifiers.disclaimer is not None
        else None
    )
    public_text = _public_evidence_meaning(block)

    if block.management_label == "consumer_self_report":
        context = sample or "消费者"
        if method and method not in context:
            context = f"{context}的{method}"
        rendered = (
            f"{product_name}：品牌收集的使用反馈来自{context}，"
            f"内容为「{public_text}」。"
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
            f"{product_name}：品牌提供的测试{qualifier_text}提到"
            f"「{public_text}」"
        )
        if disclaimer:
            rendered += f"；{disclaimer}"
        return rendered + "。"
    if block.management_label == "safety_transcript":
        return (
            f"{product_name}：品牌将「{public_text}」作为适用说明。"
            "这类说明不能当作个人安全保证；"
            "如果正处于泛红、刺痛或破损期，先暂停尝试；"
            "皮肤稳定后再局部试用。"
        )
    prefix_by_label = {
        "merchant_claim": "品牌主打",
        "packaging_information": "包装说明",
        "faq": "使用问答",
        "usage": "使用方法",
        "brand_research": "研究信息",
        "product_specification": "商品信息",
        "unclassified": "商品信息",
    }
    prefix = prefix_by_label[block.management_label]
    rendered = (
        f"{product_name}："
        f"{_public_fact_text(prefix, public_text)}"
    )
    return rendered + "。"


def render_product_evidence_fact(
    block: ProductEvidenceBlock,
    *,
    product_name: str,
) -> str:
    if not isinstance(block, ProductEvidenceBlock):
        raise TypeError("block must be ProductEvidenceBlock")
    if not isinstance(product_name, str) or not product_name.strip():
        raise ValueError("product_name must be nonempty")
    return validate_final_public_text(
        _render_evidence(
            block,
            product_name=product_name.strip(),
        )
    )


def _requested_fact_keys(question: str) -> frozenset[str]:
    return frozenset(resolve_product_knowledge_dimensions(question))


def _category_fact_value_text(value: object) -> str:
    if isinstance(value, tuple):
        return "、".join(str(item) for item in value)
    return str(value)


def _sanitize_public_source_language(text: str) -> str:
    sanitized = text.strip()
    replacements = (
        ("跨境详情页给出", "商品信息包括"),
        ("跨境页面概述", "商品信息概述"),
        ("详情页给出", "商品信息包括"),
        ("详情页概述", "商品信息概述"),
        ("跨境页面版本", "该规格版本"),
        ("跨境页面", "商品信息"),
        ("详情页", "商品信息"),
        ("页面", "商品信息"),
        ("商家肤感宣传", "产品肤感描述"),
        ("商家宣传", "产品描述"),
        ("完整INCI", "完整成分表"),
        ("临床治疗证据", "临床治疗结论"),
        ("临床舒缓证据", "临床舒缓结论"),
        ("当前证据", "当前信息"),
        ("证据", "信息"),
    )
    for source, target in replacements:
        sanitized = sanitized.replace(source, target)
    sanitized = re.sub(r"\bPID[0-9]+\b", "", sanitized)
    sanitized = re.sub(r"\s{2,}", " ", sanitized)
    sanitized = sanitized.replace(
        "不能与56国行中文背标的名称、注册号或成分无条件混用",
        "具体信息请以对应规格实物为准",
    )
    sanitized = sanitized.replace(
        "不能与国行中文背标的名称、注册号或成分无条件混用",
        "具体信息请以对应规格实物为准",
    )
    return sanitized.strip(" ；;")


def _public_evidence_meaning(block: ProductEvidenceBlock) -> str:
    public_text = _sanitize_public_source_language(
        block.plain_meaning
    ).rstrip("。")
    normalized = public_text.casefold()
    relation_values: list[str] = []
    seen: set[str] = set()
    for relation in block.relations:
        subject = _sanitize_public_source_language(
            relation.subject
        ).rstrip("。")
        relation_object = _sanitize_public_source_language(
            relation.object
        ).rstrip("。")
        connector = _PUBLIC_RELATION_CONNECTOR.get(
            relation.predicate,
            "：",
        )
        value = (
            f"{subject}{connector}{relation_object}"
            if (
                subject
                and subject.casefold()
                not in relation_object.casefold()
            )
            else relation_object
        )
        identity = value.casefold()
        if (
            not value
            or identity in normalized
            or identity in seen
        ):
            continue
        relation_values.append(value)
        seen.add(identity)
    covered = " ".join((public_text, *relation_values)).casefold()
    for descriptor in block.free_descriptors:
        value = _sanitize_public_source_language(
            descriptor
        ).rstrip("。")
        identity = value.casefold()
        if (
            not value
            or identity in covered
            or identity in seen
        ):
            continue
        relation_values.append(value)
        seen.add(identity)
        covered += f" {identity}"
    if relation_values:
        public_text += "；具体信息：" + "；".join(relation_values)
    return public_text


def _public_fact_text(prefix: str, text: str) -> str:
    normalized = text.strip().rstrip("。")
    if normalized.startswith(prefix):
        return normalized
    return f"{prefix}{normalized}"


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
    "ProductKnowledgeAnswerPlan",
    "build_product_knowledge_answer_plan",
    "render_catalog_product_facts_answer",
    "render_product_evidence_fact",
    "render_product_evidence_answer",
    "resolve_product_knowledge_dimensions",
]
