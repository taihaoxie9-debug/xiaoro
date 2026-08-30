from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeBlock,
    GeneralKnowledgeCoverage,
    GeneralKnowledgeDocument,
    GeneralKnowledgeHit,
    GeneralKnowledgePacket,
    GeneralKnowledgeQuery,
    GeneralKnowledgeRetrievalProfile,
    KnowledgeEntityMention,
    KnowledgeQuerySpec,
    general_knowledge_id,
)


_FORBIDDEN_USES = {
    "product_fact",
    "hard_filter",
    "soft_rank",
    "safety_guarantee",
    "profile_write",
}


def _document_payload() -> dict[str, object]:
    return {
        "title": "防晒怎么选",
        "source_path": "data/knowledge_docs/06-防晒怎么选.md",
        "source_sha256": "a" * 64,
        "document_kind": "educational_seed",
    }


def _document() -> GeneralKnowledgeDocument:
    payload = _document_payload()
    return GeneralKnowledgeDocument.model_validate(
        {
            "document_id": general_knowledge_id(payload),
            **payload,
        },
        strict=True,
    )


def _block_payload(
    *,
    review_decision: str = "general_answer",
    allowed_uses: set[str] | None = None,
    forbidden_uses: set[str] | None = None,
    exact_text: str = "SPF针对UVB，PA针对UVA。",
) -> dict[str, object]:
    return {
        "document_id": _document().document_id,
        "title": "防晒怎么选",
        "section_title": "关键成分与原理",
        "exact_text": exact_text,
        "public_text": (
            exact_text
            if review_decision == "general_answer"
            else None
        ),
        "source_path": "data/knowledge_docs/06-防晒怎么选.md",
        "source_sha256": "a" * 64,
        "block_sha256": hashlib.sha256(
            exact_text.encode("utf-8")
        ).hexdigest(),
        "section_order": 2,
        "review_decision": review_decision,
        "allowed_uses": (
            {"answer", "citation", "followup"}
            if allowed_uses is None
            else allowed_uses
        ),
        "forbidden_uses": (
            _FORBIDDEN_USES
            if forbidden_uses is None
            else forbidden_uses
        ),
        "review_rationale": "通用防晒指标解释，不指向具体商品。",
        "retrieval_terms": ("pa", "spf", "uva", "uvb", "防晒"),
    }


def _block_identity(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: payload[key]
        for key in (
            "document_id",
            "title",
            "section_title",
            "exact_text",
            "source_path",
            "source_sha256",
            "block_sha256",
            "section_order",
        )
    }


def _block(**overrides: object) -> GeneralKnowledgeBlock:
    payload = _block_payload()
    payload.update(overrides)
    if "public_text" not in overrides:
        payload["public_text"] = (
            payload["exact_text"]
            if payload["review_decision"] == "general_answer"
            else None
        )
    return GeneralKnowledgeBlock.model_validate(
        {
            "knowledge_id": general_knowledge_id(
                _block_identity(payload)
            ),
            **payload,
        },
        strict=True,
    )


def test_document_and_block_ids_are_content_addressed() -> None:
    document = _document()
    block = _block()

    assert document.document_id == general_knowledge_id(
        _document_payload()
    )
    assert block.knowledge_id == general_knowledge_id(
        _block_identity(_block_payload())
    )
    assert block.block_sha256 == hashlib.sha256(
        block.exact_text.encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValidationError, match="knowledge ID mismatch"):
        _block(knowledge_id="f" * 64)


def test_general_answer_requires_answer_and_citation_permissions() -> None:
    for allowed_uses in (
        {"answer"},
        {"citation"},
        {"followup"},
    ):
        with pytest.raises(
            ValidationError,
            match="general answer requires answer and citation",
        ):
            _block(allowed_uses=allowed_uses)


def test_every_block_forbids_all_product_and_state_uses() -> None:
    assert _block().forbidden_uses == frozenset(_FORBIDDEN_USES)

    with pytest.raises(
        ValidationError,
        match="mandatory forbidden uses",
    ):
        _block(
            forbidden_uses=_FORBIDDEN_USES - {"soft_rank"},
        )


@pytest.mark.parametrize(
    ("decision", "allowed_uses", "error"),
    (
        (
            "escalation_only",
            {"answer", "citation", "medical_escalation"},
            "escalation-only block forbids answer",
        ),
        (
            "product_specific_redirect",
            {"answer", "citation"},
            "product redirect forbids answer",
        ),
        (
            "rejected",
            {"citation"},
            "rejected block forbids allowed uses",
        ),
    ),
)
def test_nonanswer_decisions_cannot_gain_answer_permission(
    decision: str,
    allowed_uses: set[str],
    error: str,
) -> None:
    with pytest.raises(ValidationError, match=error):
        _block(
            review_decision=decision,
            allowed_uses=allowed_uses,
        )


def test_escalation_and_redirect_permissions_are_bounded() -> None:
    escalation = _block(
        review_decision="escalation_only",
        allowed_uses={"citation", "followup", "medical_escalation"},
    )
    redirect = _block(
        review_decision="product_specific_redirect",
        allowed_uses={"citation", "followup"},
    )
    rejected = _block(
        review_decision="rejected",
        allowed_uses=set(),
    )

    assert "answer" not in escalation.allowed_uses
    assert "medical_escalation" in escalation.allowed_uses
    assert "answer" not in redirect.allowed_uses
    assert not rejected.allowed_uses


@pytest.mark.parametrize(
    "source_path",
    (
        "/tmp/knowledge.md",
        "../knowledge.md",
        "data/knowledge_docs/../secret.md",
        "data\\knowledge_docs\\06.md",
    ),
)
def test_source_paths_are_repository_relative(
    source_path: str,
) -> None:
    payload = _document_payload()
    payload["source_path"] = source_path

    with pytest.raises(ValidationError, match="repository-relative"):
        GeneralKnowledgeDocument.model_validate(
            {
                "document_id": general_knowledge_id(payload),
                **payload,
            },
            strict=True,
        )


def test_terms_and_query_source_refs_are_sorted_unique() -> None:
    with pytest.raises(
        ValidationError,
        match="retrieval terms must be sorted and unique",
    ):
        _block(retrieval_terms=("spf", "pa", "spf"))

    with pytest.raises(
        ValidationError,
        match="prior knowledge IDs must be sorted and unique",
    ):
        GeneralKnowledgeQuery(
            retrieval_query="那敏感肌呢",
            question_meaning="询问敏感肌如何使用",
            topic=None,
            safety_sensitive=False,
            prior_knowledge_ids=("b" * 64, "a" * 64, "b" * 64),
            top_k=3,
        )


def test_rejected_blocks_cannot_enter_retrieval_packets() -> None:
    rejected = _block(
        review_decision="rejected",
        allowed_uses=set(),
    )

    with pytest.raises(
        ValidationError,
        match="rejected block cannot be retrieved",
    ):
        GeneralKnowledgeHit(
            block=rejected,
            score=1.0,
            matched_terms=(),
        )


def test_query_and_packet_order_are_deterministic() -> None:
    query = GeneralKnowledgeQuery(
        retrieval_query="SPF和PA分别是什么意思",
        question_meaning="询问SPF和PA含义",
        topic="sunscreen",
        safety_sensitive=False,
        prior_knowledge_ids=(),
        top_k=3,
    )
    first = GeneralKnowledgeHit(
        block=_block(),
        score=3.0,
        matched_terms=("pa", "spf"),
    )
    second = GeneralKnowledgeHit(
        block=_block(
            exact_text="PA描述UVA防护等级。",
            section_order=3,
            block_sha256=hashlib.sha256(
                "PA描述UVA防护等级。".encode("utf-8")
            ).hexdigest(),
        ),
        score=2.0,
        matched_terms=("pa",),
    )

    packet = GeneralKnowledgePacket(
        query=query,
        hits=(first, second),
    )

    assert packet.hits == (first, second)
    with pytest.raises(
        ValidationError,
        match="knowledge hits must use deterministic order",
    ):
        GeneralKnowledgePacket(
            query=query,
            hits=(second, first),
        )


def test_typed_query_and_coverage_contracts_are_strict() -> None:
    query = KnowledgeQuerySpec(
        raw_query="烟酰胺和A醇有什么区别",
        question_meaning="比较烟酰胺和视黄醇",
        concept_ids=(
            "ingredient.niacinamide",
            "ingredient.retinol",
        ),
        entity_mentions=(
            KnowledgeEntityMention(
                entity_id="ingredient.niacinamide",
                raw_text="烟酰胺",
            ),
            KnowledgeEntityMention(
                entity_id="ingredient.retinol",
                raw_text="A醇",
            ),
        ),
        relation_intents=("difference",),
        safety_sensitive=False,
        prior_knowledge_ids=(),
        top_k=3,
    )
    coverage = GeneralKnowledgeCoverage(
        required_concept_ids=query.concept_ids,
        covered_concept_ids=query.concept_ids,
        required_entity_ids=tuple(
            item.entity_id for item in query.entity_mentions
        ),
        covered_entity_ids=tuple(
            item.entity_id for item in query.entity_mentions
        ),
        required_relation_intents=query.relation_intents,
        covered_relation_intents=query.relation_intents,
        missing_concept_ids=(),
        missing_entity_ids=(),
        missing_relation_intents=(),
        complete=True,
    )

    assert coverage.complete
    with pytest.raises(ValidationError, match="ordered unique"):
        KnowledgeQuerySpec.model_validate(
            {
                **query.model_dump(mode="python"),
                "relation_intents": (
                    "difference",
                    "difference",
                ),
            },
            strict=True,
        )


def test_coverage_complete_must_match_missing_requirements() -> None:
    with pytest.raises(ValidationError, match="complete"):
        GeneralKnowledgeCoverage(
            required_concept_ids=("ingredient.retinol",),
            covered_concept_ids=(),
            required_entity_ids=("ingredient.retinol",),
            covered_entity_ids=(),
            required_relation_intents=("usage",),
            covered_relation_intents=(),
            missing_concept_ids=("ingredient.retinol",),
            missing_entity_ids=("ingredient.retinol",),
            missing_relation_intents=("usage",),
            complete=True,
        )


def test_retrieval_profile_requires_complete_typed_section_metadata() -> None:
    profile = GeneralKnowledgeRetrievalProfile(
        source_path="data/knowledge_docs/06-防晒怎么选.md",
        primary_concept_ids=("category", "category.sunscreen"),
        primary_entity_ids=(),
        section_relations={
            "防晒怎么选": ("overview",),
            "怎么选": ("selection", "usage"),
            "关键成分/原理": ("mechanism",),
            "避雷与注意": ("compatibility", "safety", "usage"),
            "可以考虑的商品类型": ("selection",),
        },
    )

    assert profile.primary_concept_ids == (
        "category",
        "category.sunscreen",
    )
    assert profile.section_relations["避雷与注意"] == (
        "compatibility",
        "safety",
        "usage",
    )

    with pytest.raises(ValidationError, match="ordered unique"):
        GeneralKnowledgeRetrievalProfile(
            source_path="data/knowledge_docs/06-防晒怎么选.md",
            primary_concept_ids=("category", "category"),
            primary_entity_ids=(),
            section_relations={"防晒怎么选": ("overview",)},
        )

    with pytest.raises(ValidationError, match="section relation"):
        GeneralKnowledgeRetrievalProfile(
            source_path="data/knowledge_docs/06-防晒怎么选.md",
            primary_concept_ids=("category", "category.sunscreen"),
            primary_entity_ids=(),
            section_relations={"防晒怎么选": ()},
        )
