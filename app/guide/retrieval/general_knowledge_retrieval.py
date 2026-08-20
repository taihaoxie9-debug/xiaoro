from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import math

from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeBlock,
    GeneralKnowledgeHit,
    GeneralKnowledgePacket,
    GeneralKnowledgeQuery,
)
from app.guide.retrieval.category_taxonomy import (
    canonical_categories_for,
)
from app.guide.retrieval.general_knowledge_terms import (
    general_knowledge_terms,
)


MINIMUM_KNOWLEDGE_SCORE = 4.0
PRIOR_BLOCK_BOOST = 2.0
_REDIRECT_PENALTY = 5.0
_ESCALATION_BOOST = 5.0
_ESCALATION_ORDINARY_PENALTY = 2.0
_INTRO_BOILERPLATE_PENALTY = 35.0


def _term_shape_weight(term: str) -> float:
    if term.isascii():
        return 1.25 if len(term) >= 2 else 0.1
    if len(term) == 1:
        return 0.12
    if len(term) == 2:
        return 1.0
    return 1.4


class GeneralKnowledgeRetriever:
    def __init__(
        self,
        blocks: Sequence[GeneralKnowledgeBlock],
    ) -> None:
        if (
            isinstance(blocks, (str, bytes))
            or not isinstance(blocks, Sequence)
            or any(
                not isinstance(block, GeneralKnowledgeBlock)
                for block in blocks
            )
        ):
            raise TypeError(
                "knowledge blocks must be a typed sequence"
            )
        normalized = tuple(blocks)
        if any(
            block.review_decision == "rejected"
            for block in normalized
        ):
            raise ValueError(
                "knowledge retriever forbids rejected blocks"
            )
        ids = tuple(block.knowledge_id for block in normalized)
        if len(ids) != len(set(ids)):
            raise ValueError(
                "knowledge retriever block IDs must be unique"
            )
        self._blocks = normalized
        self._document_frequency = Counter(
            term
            for block in normalized
            for term in set(block.retrieval_terms)
        )
        self._retrieval_vocabulary = frozenset(
            self._document_frequency
        )
        self._title_terms = {
            block.knowledge_id: frozenset(
                general_knowledge_terms(block.title)
            )
            for block in normalized
        }
        self._section_terms = {
            block.knowledge_id: frozenset(
                general_knowledge_terms(block.section_title)
            )
            for block in normalized
        }
        self._body_terms = {
            block.knowledge_id: frozenset(
                general_knowledge_terms(block.exact_text)
            )
            for block in normalized
        }

    @property
    def blocks(self) -> tuple[GeneralKnowledgeBlock, ...]:
        return self._blocks

    def _term_weight(self, term: str) -> float:
        count = self._document_frequency.get(term, 0)
        inverse_frequency = math.log(
            (len(self._blocks) + 1) / (count + 1)
        ) + 1.0
        return inverse_frequency * _term_shape_weight(term)

    def _is_informative(self, term: str) -> bool:
        return (
            (len(term) >= 2 or (term.isascii() and len(term) >= 2))
            and self._document_frequency.get(term, 0)
            <= max(1, len(self._blocks) // 3)
        )

    def _literal_anchor_terms(
        self,
        query: GeneralKnowledgeQuery,
    ) -> frozenset[str]:
        raw_question = query.raw_question.casefold()
        maximum_frequency = max(1, len(self._blocks) // 10)
        candidates = {
            term
            for term in self._retrieval_vocabulary
            if (
                (
                    (term.isascii() and len(term) >= 2)
                    or (not term.isascii() and len(term) >= 3)
                )
                and self._document_frequency[term]
                <= maximum_frequency
                and term.casefold() in raw_question
            )
        }
        if query.topic is not None:
            candidates.update(
                category
                for category in canonical_categories_for(
                    query.topic
                )
                if category.casefold() in raw_question
            )
        return frozenset(
            term
            for term in candidates
            if not any(
                term != other
                and term.casefold() in other.casefold()
                for other in candidates
            )
        )

    def _score(
        self,
        *,
        block: GeneralKnowledgeBlock,
        query: GeneralKnowledgeQuery,
        query_terms: frozenset[str],
        anchor_terms: frozenset[str],
    ) -> GeneralKnowledgeHit | None:
        matched = tuple(
            sorted(query_terms.intersection(block.retrieval_terms))
        )
        matched_source_anchors = {
            term
            for term in matched
            if term in anchor_terms and self._is_informative(term)
        }
        matched_title_anchors = {
            term
            for term in anchor_terms
            if (
                self._is_informative(term)
                and term.casefold() in block.title.casefold()
            )
        }
        matched_anchors = tuple(sorted(
            matched_source_anchors.union(matched_title_anchors)
        ))
        if (
            not matched
            or not matched_anchors
        ):
            return None
        body_terms = self._body_terms[block.knowledge_id]
        title_terms = self._title_terms[block.knowledge_id]
        section_terms = self._section_terms[block.knowledge_id]
        body_weight = sum(
            self._term_weight(term)
            for term in matched
            if term in body_terms
        )
        title_weight = sum(
            self._term_weight(term)
            for term in matched
            if term in title_terms
        )
        section_weight = sum(
            self._term_weight(term)
            for term in matched
            if term in section_terms
        )
        is_intro = (
            block.section_order == 0
            and block.section_title == block.title
        )
        if is_intro:
            section_weight = 0.0
        matched_anchor_weight = sum(
            self._term_weight(term)
            for term in matched_anchors
        )
        informative_anchors = tuple(
            term
            for term in anchor_terms
            if self._is_informative(term)
        )
        anchor_weight = sum(
            self._term_weight(term)
            for term in informative_anchors
        )
        coverage = (
            matched_anchor_weight / anchor_weight
            if anchor_weight > 0
            else 0.0
        )
        score = (
            body_weight
            + (0.35 * title_weight)
            + (6.0 * section_weight)
            + (1.5 * matched_anchor_weight)
            + (4.0 * coverage)
        )
        if is_intro:
            score -= _INTRO_BOILERPLATE_PENALTY
        prior_related = (
            block.knowledge_id in query.prior_knowledge_ids
            and bool(matched_anchors)
        )
        if prior_related:
            score += PRIOR_BLOCK_BOOST
        if block.review_decision == "product_specific_redirect":
            score -= _REDIRECT_PENALTY
        elif block.review_decision == "escalation_only":
            score += (
                _ESCALATION_BOOST
                if query.safety_sensitive
                else -_ESCALATION_ORDINARY_PENALTY
            )
        if score < MINIMUM_KNOWLEDGE_SCORE:
            return None
        return GeneralKnowledgeHit(
            block=block,
            score=round(score, 6),
            matched_terms=matched,
        )

    def retrieve(
        self,
        query: GeneralKnowledgeQuery,
    ) -> GeneralKnowledgePacket:
        if not isinstance(query, GeneralKnowledgeQuery):
            raise TypeError("query must be GeneralKnowledgeQuery")
        raw_terms = frozenset(
            general_knowledge_terms(query.raw_question)
        )
        meaning_terms = frozenset(
            general_knowledge_terms(query.question_meaning)
        )
        shared_terms = raw_terms.intersection(meaning_terms)
        shared_anchors = frozenset(
            term
            for term in shared_terms
            if self._is_informative(term)
        )
        anchor_terms = (
            shared_anchors
            if shared_anchors
            else self._literal_anchor_terms(query)
        )
        query_terms = raw_terms.union(
            meaning_terms,
            anchor_terms,
        )
        hits = [
            hit
            for block in self._blocks
            if (
                hit := self._score(
                    block=block,
                    query=query,
                    query_terms=query_terms,
                    anchor_terms=anchor_terms,
                )
            )
            is not None
        ]
        ordered = tuple(
            sorted(
                hits,
                key=lambda hit: (
                    -hit.score,
                    hit.block.document_id,
                    hit.block.section_order,
                    hit.block.knowledge_id,
                ),
            )[:query.top_k]
        )
        return GeneralKnowledgePacket(
            query=query,
            hits=ordered,
        )


__all__ = [
    "MINIMUM_KNOWLEDGE_SCORE",
    "PRIOR_BLOCK_BOOST",
    "GeneralKnowledgeRetriever",
]
