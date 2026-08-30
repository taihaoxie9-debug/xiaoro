from __future__ import annotations

from collections.abc import Sequence

from app.guide.retrieval.general_knowledge_contracts import (
    KnowledgeEntityMention,
    KnowledgeQuerySpec,
)
from app.guide.retrieval.general_knowledge_ontology import (
    explicit_knowledge_relations,
    match_knowledge_concepts,
    match_knowledge_entities,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.knowledge_relation_contracts import (
    KnowledgeRelationIntent,
)


_TOPIC_CONCEPTS = {
    TopicCode.SUNSCREEN: "category.sunscreen",
    TopicCode.SERUM: "category.serum",
    TopicCode.SKINCARE: "skin",
    TopicCode.BASE_MAKEUP: "category.base_makeup",
    TopicCode.COLOR_MAKEUP: "category",
    TopicCode.CLEANSER: "category.cleanser",
    TopicCode.FRAGRANCE: "category.fragrance",
}


def build_knowledge_query_spec(
    *,
    raw_query: str,
    question_meaning: str,
    topic: TopicCode | None,
    relation_hints: Sequence[KnowledgeRelationIntent],
    safety_sensitive: bool,
    prior_knowledge_ids: Sequence[str],
    top_k: int = 3,
) -> KnowledgeQuerySpec:
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise ValueError("knowledge raw query must be nonempty")
    if (
        not isinstance(question_meaning, str)
        or not question_meaning.strip()
    ):
        raise ValueError("knowledge question meaning must be nonempty")
    if topic is not None and not isinstance(topic, TopicCode):
        raise TypeError("knowledge topic must be TopicCode or None")
    if isinstance(relation_hints, (str, bytes)) or not isinstance(
        relation_hints,
        Sequence,
    ):
        raise TypeError("knowledge relation hints must be a sequence")
    if isinstance(prior_knowledge_ids, (str, bytes)) or not isinstance(
        prior_knowledge_ids,
        Sequence,
    ):
        raise TypeError("prior knowledge IDs must be a sequence")

    raw = raw_query.strip()
    concept_matches = match_knowledge_concepts(raw)
    entity_matches = match_knowledge_entities(raw)
    concept_ids = list(
        dict.fromkeys(match.identifier for match in concept_matches)
    )
    for match in entity_matches:
        if match.identifier not in concept_ids:
            concept_ids.append(match.identifier)
    if not concept_ids and topic is not None:
        concept_ids.append(_TOPIC_CONCEPTS[topic])

    relation_intents = list(explicit_knowledge_relations(raw))
    relation_intents.extend(
        relation
        for relation in relation_hints
        if relation not in relation_intents
    )
    if safety_sensitive and "safety" not in relation_intents:
        relation_intents.append("safety")
    if not relation_intents:
        relation_intents.append("overview")

    return KnowledgeQuerySpec(
        raw_query=raw,
        question_meaning=question_meaning.strip(),
        concept_ids=tuple(concept_ids),
        entity_mentions=tuple(
            KnowledgeEntityMention(
                entity_id=match.identifier,
                raw_text=match.raw_text,
            )
            for match in entity_matches
        ),
        relation_intents=tuple(relation_intents),
        safety_sensitive=safety_sensitive,
        prior_knowledge_ids=tuple(sorted(set(prior_knowledge_ids))),
        top_k=top_k,
    )


__all__ = ["build_knowledge_query_spec"]
