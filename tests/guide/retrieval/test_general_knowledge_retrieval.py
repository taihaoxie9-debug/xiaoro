from __future__ import annotations

from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeQuery,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    PRIOR_BLOCK_BOOST,
    GeneralKnowledgeRetriever,
)
from app.guide_runtime.composition import (
    build_general_knowledge_assets,
)


def _retriever() -> GeneralKnowledgeRetriever:
    return GeneralKnowledgeRetriever(
        build_general_knowledge_assets().blocks
    )


def _query(
    raw_question: str,
    question_meaning: str,
    *,
    topic: str | None = None,
    safety_sensitive: bool = False,
    prior_knowledge_ids: tuple[str, ...] = (),
    top_k: int = 3,
) -> GeneralKnowledgeQuery:
    return GeneralKnowledgeQuery(
        raw_question=raw_question,
        question_meaning=question_meaning,
        topic=topic,
        safety_sensitive=safety_sensitive,
        prior_knowledge_ids=prior_knowledge_ids,
        top_k=top_k,
    )


def test_spf_and_pa_retrieve_the_audited_sunscreen_explanation() -> None:
    packet = _retriever().retrieve(
        _query(
            "SPF和PA分别是什么意思",
            "询问SPF和PA防晒指标的含义",
            topic="sunscreen",
        )
    )

    assert packet.hits
    assert packet.hits[0].block.knowledge_id == (
        "309019e7948c7d8c426abed62b8d4ddf8644da73ef685aacf508f67b2b41912f"
    )
    assert packet.hits[0].block.section_title == "怎么选"
    assert {"spf", "pa"} <= set(packet.hits[0].matched_terms)


def test_niacinamide_retrieves_ingredient_mechanism() -> None:
    packet = _retriever().retrieve(
        _query(
            "烟酰胺有什么作用",
            "询问烟酰胺的作用和原理",
            topic="serum",
        )
    )

    assert packet.hits[0].block.knowledge_id == (
        "206aa66156025d9b9cf1d346a4d3684d1f500fde8b806ea7869eb5bb5e231775"
    )
    assert packet.hits[0].block.section_title == "关键成分/原理"


def test_chinese_question_with_english_meaning_keeps_raw_anchors() -> None:
    packet = _retriever().retrieve(
        _query(
            "烟酰胺和视黄醇是不是一回事？",
            "Are niacinamide and retinol the same ingredient?",
            topic="serum",
            top_k=5,
        )
    )

    source_paths = {
        hit.block.source_path
        for hit in packet.hits
    }
    assert (
        "data/knowledge_docs/13-烟酰胺适合谁.md"
        in source_paths
    )
    assert (
        "data/knowledge_docs/14-视黄醇A醇适合谁.md"
        in source_paths
    )


def test_sensitive_skin_query_retrieves_identification_section() -> None:
    packet = _retriever().retrieve(
        _query(
            "敏感肌怎么判断",
            "询问如何判断自己是不是敏感肌",
            topic="skincare",
        )
    )

    assert packet.hits[0].block.source_path.endswith(
        "22-怎么判断自己是不是敏感肌.md"
    )
    assert packet.hits[0].block.section_title == "怎么判断是不是敏感肌"


def test_commute_lip_query_retrieves_scenario_guidance() -> None:
    packet = _retriever().retrieve(
        _query(
            "口红通勤怎么选",
            "询问日常通勤场景如何选择唇妆",
            topic="color_makeup",
        )
    )

    assert packet.hits[0].block.knowledge_id == (
        "d6fe839d5131e85dc87b63364257e24f5fc7f0147047de78f95708ee4c0fa2ac"
    )


def test_unrelated_weather_query_returns_an_evidence_gap() -> None:
    packet = _retriever().retrieve(
        _query(
            "明天上海天气怎么样",
            "询问上海明日天气",
        )
    )

    assert packet.hits == ()


def test_same_query_has_byte_identical_hit_order() -> None:
    retriever = _retriever()
    query = _query(
        "烟酰胺有什么作用",
        "询问烟酰胺的作用和原理",
        topic="serum",
    )

    first = retriever.retrieve(query)
    second = retriever.retrieve(query)

    assert first.model_dump_json() == second.model_dump_json()


def test_same_language_question_meaning_keeps_existing_order() -> None:
    retriever = _retriever()
    query = _query(
        "防晒为什么需要补涂",
        "防晒为什么需要补涂？",
        topic="sunscreen",
        top_k=5,
    )
    original = retriever.retrieve(query)
    expanded = retriever.retrieve(
        query.model_copy(
            update={
                "question_meaning": "防晒为什么需要补涂",
            },
            deep=True,
        )
    )

    assert original.hits
    assert tuple(
        hit.block.knowledge_id for hit in expanded.hits
    ) == tuple(
        hit.block.knowledge_id for hit in original.hits
    )


def test_prior_block_boost_is_bounded_and_requires_related_overlap() -> None:
    retriever = _retriever()
    base_query = _query(
        "SPF和PA分别是什么意思",
        "询问SPF和PA防晒指标的含义",
        topic="sunscreen",
    )
    base = retriever.retrieve(base_query)
    prior_id = base.hits[0].block.knowledge_id
    boosted = retriever.retrieve(
        base_query.model_copy(
            update={"prior_knowledge_ids": (prior_id,)},
            deep=True,
        )
    )

    assert boosted.hits[0].block.knowledge_id == prior_id
    assert boosted.hits[0].score > base.hits[0].score
    assert (
        boosted.hits[0].score - base.hits[0].score
        <= PRIOR_BLOCK_BOOST
    )

    unrelated = retriever.retrieve(
        _query(
            "明天上海天气怎么样",
            "询问上海明日天气",
            prior_knowledge_ids=(prior_id,),
        )
    )
    assert unrelated.hits == ()


def test_product_redirect_cannot_outrank_general_education() -> None:
    packet = _retriever().retrieve(
        _query(
            "玻色因有什么作用",
            "询问玻色因的通用作用和原理",
            topic="serum",
        )
    )

    assert packet.hits[0].block.knowledge_id == (
        "f6e1753445e6c87891f5ee437d42d1dccdaddfbf1637c8d4753dea096953e922"
    )
    assert packet.hits[0].block.review_decision == "general_answer"
    assert all(
        hit.block.review_decision != "product_specific_redirect"
        or hit.score < packet.hits[0].score
        for hit in packet.hits
    )


def test_safety_sensitive_query_can_select_escalation_boundary() -> None:
    packet = _retriever().retrieve(
        _query(
            "孕期可以用A醇吗",
            "询问孕期使用A醇的安全边界",
            topic="skincare",
            safety_sensitive=True,
        )
    )

    assert packet.hits
    assert packet.hits[0].block.source_path.endswith(
        "14-视黄醇A醇适合谁.md"
    )
    assert packet.hits[0].block.review_decision == "escalation_only"
    assert "medical_escalation" in packet.hits[0].block.allowed_uses
