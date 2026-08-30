from __future__ import annotations

from app.guide.retrieval.general_knowledge_query import (
    build_knowledge_query_spec,
)
from app.guide.understanding.contracts import TopicCode


def test_query_spec_keeps_raw_entities_authoritative() -> None:
    spec = build_knowledge_query_spec(
        raw_query="烟酰胺能做什么",
        question_meaning="Compare retinol and vitamin C",
        topic=TopicCode.SERUM,
        relation_hints=("mechanism",),
        safety_sensitive=False,
        prior_knowledge_ids=(),
    )

    assert tuple(
        item.entity_id for item in spec.entity_mentions
    ) == ("ingredient.niacinamide",)
    assert tuple(
        item.raw_text for item in spec.entity_mentions
    ) == ("烟酰胺",)
    assert "ingredient.retinol" not in spec.concept_ids
    assert "ingredient.vitamin_c" not in spec.concept_ids


def test_query_spec_merges_explicit_relations_before_model_hints() -> None:
    spec = build_knowledge_query_spec(
        raw_query="烟酰胺和A醇有什么区别，能一起用吗？",
        question_meaning="比较两种活性成分",
        topic=TopicCode.SERUM,
        relation_hints=("difference",),
        safety_sensitive=False,
        prior_knowledge_ids=(),
    )

    assert tuple(
        item.entity_id for item in spec.entity_mentions
    ) == (
        "ingredient.niacinamide",
        "ingredient.retinol",
    )
    assert spec.relation_intents == (
        "difference",
        "compatibility",
    )


def test_query_spec_uses_topic_only_as_parent_fallback() -> None:
    spec = build_knowledge_query_spec(
        raw_query="这个指标是什么意思",
        question_meaning="询问防晒指标含义",
        topic=TopicCode.SUNSCREEN,
        relation_hints=("mechanism",),
        safety_sensitive=False,
        prior_knowledge_ids=(),
    )

    assert spec.concept_ids == ("category.sunscreen",)
    assert spec.entity_mentions == ()


def test_safety_authority_adds_safety_relation() -> None:
    spec = build_knowledge_query_spec(
        raw_query="孕期可以用A醇吗",
        question_meaning="询问孕期使用视黄醇的安全边界",
        topic=TopicCode.SKINCARE,
        relation_hints=("usage",),
        safety_sensitive=True,
        prior_knowledge_ids=(),
    )

    assert spec.relation_intents == ("safety", "usage")
    assert spec.safety_sensitive is True


def test_query_spec_sorts_prior_ids_without_changing_query_order() -> None:
    spec = build_knowledge_query_spec(
        raw_query="维C和烟酰胺有什么区别",
        question_meaning="比较维C和烟酰胺",
        topic=TopicCode.SERUM,
        relation_hints=("difference",),
        safety_sensitive=False,
        prior_knowledge_ids=("b" * 64, "a" * 64),
    )

    assert tuple(
        item.entity_id for item in spec.entity_mentions
    ) == (
        "ingredient.vitamin_c",
        "ingredient.niacinamide",
    )
    assert spec.prior_knowledge_ids == ("a" * 64, "b" * 64)
