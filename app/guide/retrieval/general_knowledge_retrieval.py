from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import math
import re

from app.guide.retrieval.general_knowledge_contracts import (
    GeneralKnowledgeBlock,
    GeneralKnowledgeCoverage,
    GeneralKnowledgeHit,
    GeneralKnowledgePacket,
    GeneralKnowledgeQuery,
    KnowledgeQuerySpec,
)
from app.guide.retrieval.general_knowledge_query import (
    build_knowledge_query_spec,
)
from app.guide.retrieval.general_knowledge_ontology import (
    explicit_knowledge_relations,
    match_knowledge_entities,
)
from app.guide.retrieval.general_knowledge_terms import (
    general_knowledge_terms,
)


MINIMUM_KNOWLEDGE_SCORE = 4.0
PRIOR_BLOCK_BOOST = 2.0
_REDIRECT_PENALTY = 5.0
_ESCALATION_BOOST = 5.0
_ESCALATION_ORDINARY_PENALTY = 20.0
_ESCALATION_EXACT_ANCHOR_PENALTY = 2.0
_INTRO_BOILERPLATE_PENALTY = 35.0
_SECTION_LEAD_IN_PENALTY = 12.0
PRIMARY_ENTITY_BOOST = 20.0
MENTIONED_ENTITY_BOOST = 10.0
PRIMARY_CONCEPT_BOOST = 8.0
MENTIONED_CONCEPT_BOOST = 3.0
RELATION_MATCH_BOOST = 6.0
RELATION_MISMATCH_PENALTY = 8.0
EXPLICIT_RELATION_EVIDENCE_BOOST = 12.0
DIRECT_MULTI_ENTITY_BOOST = 12.0
_RELATION_SEGMENT = re.compile(r"[\n。；;！？!?]+")


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
        query: KnowledgeQuerySpec,
    ) -> frozenset[str]:
        retrieval_query = query.raw_query.casefold()
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
                and term.casefold() in retrieval_query
            )
        }
        return frozenset(
            term
            for term in candidates
            if not any(
                term != other
                and term.casefold() in other.casefold()
                for other in candidates
            )
        )

    @staticmethod
    def _query_entity_ids(
        query: KnowledgeQuerySpec,
    ) -> tuple[str, ...]:
        return tuple(
            mention.entity_id for mention in query.entity_mentions
        )

    @staticmethod
    def _block_concept_ids(
        block: GeneralKnowledgeBlock,
    ) -> frozenset[str]:
        return frozenset(
            (*block.primary_concept_ids, *block.mentioned_concept_ids)
        )

    @staticmethod
    def _block_entity_ids(
        block: GeneralKnowledgeBlock,
    ) -> frozenset[str]:
        return frozenset(
            (*block.primary_entity_ids, *block.mentioned_entity_ids)
        )

    def _eligible(
        self,
        *,
        block: GeneralKnowledgeBlock,
        query: KnowledgeQuerySpec,
        literal_anchors: frozenset[str],
    ) -> bool:
        entity_ids = frozenset(self._query_entity_ids(query))
        if entity_ids:
            return bool(
                entity_ids.intersection(self._block_entity_ids(block))
            )
        if query.concept_ids:
            return bool(
                set(query.concept_ids).intersection(
                    self._block_concept_ids(block)
                )
            )
        return bool(
            literal_anchors.intersection(block.retrieval_terms)
        )

    def _supported_relations(
        self,
        *,
        block: GeneralKnowledgeBlock,
        query: KnowledgeQuerySpec,
        matched_entity_ids: tuple[str, ...],
    ) -> tuple[tuple[str, ...], bool]:
        required_entities = frozenset(
            self._query_entity_ids(query)
        )
        direct_multi_entity = (
            len(required_entities) >= 2
            and any(
                required_entities.issubset({
                    match.identifier
                    for match in match_knowledge_entities(segment)
                })
                and "compatibility" in explicit_knowledge_relations(
                    segment
                )
                for segment in _RELATION_SEGMENT.split(block.exact_text)
                if segment.strip()
            )
        )
        supported: set[str] = set()
        block_relations = frozenset(block.relation_intents)
        for relation in query.relation_intents:
            if relation == "difference":
                if (
                    matched_entity_ids
                    and block_relations.intersection(
                        {"difference", "mechanism", "overview"}
                    )
                ):
                    supported.add(relation)
                elif (
                    not required_entities
                    and "difference" in block_relations
                ):
                    supported.add(relation)
            elif relation == "compatibility":
                if (
                    (
                        len(required_entities) < 2
                        or direct_multi_entity
                    )
                    and block_relations.intersection(
                        {"compatibility", "safety", "usage"}
                    )
                ):
                    supported.add(relation)
            elif relation == "safety":
                if (
                    relation in block_relations
                    or block.review_decision == "escalation_only"
                ):
                    supported.add(relation)
            elif relation in block_relations:
                supported.add(relation)
        return tuple(sorted(supported)), direct_multi_entity

    def _score(
        self,
        *,
        block: GeneralKnowledgeBlock,
        query: KnowledgeQuerySpec,
        query_terms: frozenset[str],
        anchor_terms: frozenset[str],
        literal_anchor_terms: frozenset[str],
    ) -> GeneralKnowledgeHit | None:
        body_terms = self._body_terms[block.knowledge_id]
        matched = tuple(
            sorted(query_terms.intersection(block.retrieval_terms))
        )
        matched_source_anchors = {
            term
            for term in matched
            if (
                term in anchor_terms
                and term in body_terms
                and self._is_informative(term)
            )
        }
        matched_literal_body_anchors = {
            term
            for term in literal_anchor_terms
            if term.casefold() in block.exact_text.casefold()
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
        matched_concept_ids = tuple(sorted(
            set(query.concept_ids).intersection(
                self._block_concept_ids(block)
            )
        ))
        matched_entity_ids = tuple(sorted(
            set(self._query_entity_ids(query)).intersection(
                self._block_entity_ids(block)
            )
        ))
        if (
            not matched
            and not matched_concept_ids
            and not matched_entity_ids
        ):
            return None
        if (
            not matched_anchors
            and not matched_concept_ids
            and not matched_entity_ids
        ):
            return None
        supported_relations, direct_multi_entity = (
            self._supported_relations(
                block=block,
                query=query,
                matched_entity_ids=matched_entity_ids,
            )
        )
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
        primary_entity_matches = set(matched_entity_ids).intersection(
            block.primary_entity_ids
        )
        mentioned_entity_matches = set(matched_entity_ids).difference(
            primary_entity_matches
        )
        primary_concept_matches = set(matched_concept_ids).intersection(
            block.primary_concept_ids
        )
        mentioned_concept_matches = set(matched_concept_ids).difference(
            primary_concept_matches
        )
        score += (
            PRIMARY_ENTITY_BOOST * len(primary_entity_matches)
            + MENTIONED_ENTITY_BOOST * len(mentioned_entity_matches)
            + PRIMARY_CONCEPT_BOOST * len(primary_concept_matches)
            + MENTIONED_CONCEPT_BOOST * len(mentioned_concept_matches)
            + RELATION_MATCH_BOOST * len(supported_relations)
        )
        explicit_relation_matches = set(
            explicit_knowledge_relations(
                f"{block.section_title}\n{block.exact_text}"
            )
        ).intersection(query.relation_intents)
        score += EXPLICIT_RELATION_EVIDENCE_BOOST * len(
            explicit_relation_matches
        )
        if query.relation_intents and not supported_relations:
            score -= RELATION_MISMATCH_PENALTY
        if (
            direct_multi_entity
            and "compatibility" in supported_relations
        ):
            score += DIRECT_MULTI_ENTITY_BOOST
        if is_intro and not explicit_relation_matches:
            score -= _INTRO_BOILERPLATE_PENALTY
        if (
            len(block.exact_text) < 160
            and block.exact_text.rstrip().endswith((":", "："))
        ):
            score -= _SECTION_LEAD_IN_PENALTY
        prior_related = (
            block.knowledge_id in query.prior_knowledge_ids
            and bool(
                matched_anchors
                or matched_concept_ids
                or matched_entity_ids
            )
        )
        if prior_related:
            score += PRIOR_BLOCK_BOOST
        if block.review_decision == "product_specific_redirect":
            score -= _REDIRECT_PENALTY
        elif block.review_decision == "escalation_only":
            score += (
                _ESCALATION_BOOST
                if query.safety_sensitive
                else -(
                    _ESCALATION_EXACT_ANCHOR_PENALTY
                    if matched_literal_body_anchors
                    else _ESCALATION_ORDINARY_PENALTY
                )
            )
        if score < MINIMUM_KNOWLEDGE_SCORE:
            return None
        return GeneralKnowledgeHit(
            block=block,
            score=round(score, 6),
            matched_terms=matched,
            matched_concept_ids=matched_concept_ids,
            matched_entity_ids=matched_entity_ids,
            supported_relation_intents=supported_relations,
            direct_multi_entity_evidence=direct_multi_entity,
        )

    @staticmethod
    def _ordered_hits(
        hits: Sequence[GeneralKnowledgeHit],
    ) -> tuple[GeneralKnowledgeHit, ...]:
        return tuple(
            sorted(
                hits,
                key=lambda hit: (
                    -hit.score,
                    hit.block.document_id,
                    hit.block.section_order,
                    hit.block.knowledge_id,
                ),
            )
        )

    def _assemble(
        self,
        *,
        query: KnowledgeQuerySpec,
        ordered: tuple[GeneralKnowledgeHit, ...],
    ) -> tuple[GeneralKnowledgeHit, ...]:
        selected: list[GeneralKnowledgeHit] = []

        def add(hit: GeneralKnowledgeHit | None) -> None:
            if (
                hit is not None
                and hit not in selected
                and len(selected) < query.top_k
            ):
                selected.append(hit)

        def choose(
            predicate,
        ) -> GeneralKnowledgeHit | None:
            matches = [hit for hit in ordered if predicate(hit)]
            section_relation_matches = [
                hit
                for hit in matches
                if (
                    "selection" in query.relation_intents
                    and "selection" in explicit_knowledge_relations(
                        hit.block.section_title
                    )
                )
            ]
            if section_relation_matches:
                return section_relation_matches[0]
            return matches[0] if matches else None

        entity_ids = self._query_entity_ids(query)
        if "difference" in query.relation_intents:
            for entity_id in entity_ids:
                primary = choose(
                    lambda hit: (
                        entity_id in hit.block.primary_entity_ids
                        and bool(set(
                            hit.block.relation_intents
                        ).intersection({"difference", "mechanism"}))
                        and "difference"
                        in hit.supported_relation_intents
                    )
                )
                add(
                    primary
                    or choose(
                        lambda hit: (
                            entity_id in hit.block.primary_entity_ids
                            and "difference"
                            in hit.supported_relation_intents
                        )
                    )
                    or choose(
                        lambda hit: (
                            entity_id in hit.matched_entity_ids
                            and "difference"
                            in hit.supported_relation_intents
                        )
                    )
                )
        if "compatibility" in query.relation_intents:
            add(choose(
                lambda hit: (
                    hit.direct_multi_entity_evidence
                    and "compatibility"
                    in hit.supported_relation_intents
                )
            ))

        needs_individual_entity_evidence = (
            len(entity_ids) == 1
            or any(
                relation != "compatibility"
                for relation in query.relation_intents
            )
        )
        if (
            "difference" not in query.relation_intents
            and needs_individual_entity_evidence
        ):
            for entity_id in entity_ids:
                add(choose(
                    lambda hit: (
                        entity_id in hit.block.primary_entity_ids
                        and (
                            not query.relation_intents
                            or hit.supported_relation_intents
                        )
                    )
                ))

        if len(query.concept_ids) >= 2 and not entity_ids:
            coverage_counts = {
                hit.block.knowledge_id: len(
                    set(query.concept_ids).intersection(
                        hit.matched_concept_ids
                    )
                )
                for hit in ordered
            }
            maximum_coverage = max(
                coverage_counts.values(),
                default=0,
            )
            if maximum_coverage >= 2:
                candidates = [
                    hit
                    for hit in ordered
                    if coverage_counts[hit.block.knowledge_id]
                    == maximum_coverage
                    and hit.supported_relation_intents
                ]
                if "selection" in query.relation_intents:
                    category_primary = [
                        hit
                        for hit in candidates
                        if any(
                            concept_id.startswith("category.")
                            and concept_id
                            in hit.block.primary_concept_ids
                            for concept_id in query.concept_ids
                        )
                    ]
                    if category_primary:
                        candidates = category_primary
                add(choose(lambda hit: hit in candidates))

        for concept_id in query.concept_ids:
            if any(
                concept_id in hit.matched_concept_ids
                for hit in selected
            ):
                continue
            add(
                choose(
                    lambda hit: (
                        concept_id in hit.block.primary_concept_ids
                        and (
                            not query.relation_intents
                            or hit.supported_relation_intents
                        )
                )
                )
                or choose(
                    lambda hit: (
                        concept_id in hit.matched_concept_ids
                        and (
                            not query.relation_intents
                            or hit.supported_relation_intents
                        )
                    )
                )
            )

        covered_concepts = {
            value
            for hit in selected
            for value in hit.matched_concept_ids
        }
        covered_entities = {
            value
            for hit in selected
            for value in hit.matched_entity_ids
        }
        covered_relations = {
            value
            for hit in selected
            for value in hit.supported_relation_intents
        }
        for hit in ordered:
            if len(selected) >= query.top_k:
                break
            contributions = (
                set(hit.matched_concept_ids).difference(
                    covered_concepts
                )
                or set(hit.matched_entity_ids).difference(
                    covered_entities
                )
                or set(hit.supported_relation_intents).difference(
                    covered_relations
                )
            )
            if not selected or contributions:
                add(hit)
                covered_concepts.update(hit.matched_concept_ids)
                covered_entities.update(hit.matched_entity_ids)
                covered_relations.update(
                    hit.supported_relation_intents
                )
        return self._ordered_hits(selected)

    def _coverage(
        self,
        *,
        query: KnowledgeQuerySpec,
        hits: tuple[GeneralKnowledgeHit, ...],
    ) -> GeneralKnowledgeCoverage:
        required_concepts = query.concept_ids
        required_entities = self._query_entity_ids(query)
        covered_concepts = tuple(
            concept_id
            for concept_id in required_concepts
            if any(
                concept_id in hit.matched_concept_ids
                for hit in hits
            )
        )
        covered_entities = tuple(
            entity_id
            for entity_id in required_entities
            if any(
                entity_id in hit.matched_entity_ids
                for hit in hits
            )
        )
        covered_relations_list: list[str] = []
        for relation in query.relation_intents:
            if relation == "difference" and len(required_entities) >= 2:
                covered = all(
                    any(
                        entity_id in hit.matched_entity_ids
                        and relation in hit.supported_relation_intents
                        for hit in hits
                    )
                    for entity_id in required_entities
                )
            elif (
                relation == "compatibility"
                and len(required_entities) >= 2
            ):
                covered = any(
                    hit.direct_multi_entity_evidence
                    and relation in hit.supported_relation_intents
                    for hit in hits
                )
            else:
                covered = any(
                    relation in hit.supported_relation_intents
                    for hit in hits
                )
            if covered:
                covered_relations_list.append(relation)
        covered_relations = tuple(covered_relations_list)
        missing_concepts = tuple(
            value
            for value in required_concepts
            if value not in covered_concepts
        )
        missing_entities = tuple(
            value
            for value in required_entities
            if value not in covered_entities
        )
        missing_relations = tuple(
            value
            for value in query.relation_intents
            if value not in covered_relations
        )
        return GeneralKnowledgeCoverage(
            required_concept_ids=required_concepts,
            covered_concept_ids=covered_concepts,
            required_entity_ids=required_entities,
            covered_entity_ids=covered_entities,
            required_relation_intents=query.relation_intents,
            covered_relation_intents=covered_relations,
            missing_concept_ids=missing_concepts,
            missing_entity_ids=missing_entities,
            missing_relation_intents=missing_relations,
            complete=not (
                missing_concepts
                or missing_entities
                or missing_relations
            ),
        )

    def retrieve(
        self,
        query: GeneralKnowledgeQuery | KnowledgeQuerySpec,
    ) -> GeneralKnowledgePacket:
        if isinstance(query, GeneralKnowledgeQuery):
            query = build_knowledge_query_spec(
                raw_query=query.retrieval_query,
                question_meaning=query.question_meaning,
                topic=query.topic,
                relation_hints=(),
                safety_sensitive=query.safety_sensitive,
                prior_knowledge_ids=query.prior_knowledge_ids,
                top_k=query.top_k,
            )
        elif not isinstance(query, KnowledgeQuerySpec):
            raise TypeError(
                "query must be KnowledgeQuerySpec or GeneralKnowledgeQuery"
            )
        raw_terms = frozenset(
            general_knowledge_terms(query.raw_query)
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
        literal_anchors = self._literal_anchor_terms(query)
        anchor_terms = (
            literal_anchors.union(shared_anchors)
        )
        query_terms = raw_terms.union(
            meaning_terms,
            anchor_terms,
        )
        hits = [
            hit
            for block in self._blocks
            if self._eligible(
                block=block,
                query=query,
                literal_anchors=literal_anchors,
            )
            if (
                hit := self._score(
                    block=block,
                    query=query,
                    query_terms=query_terms,
                    anchor_terms=anchor_terms,
                    literal_anchor_terms=literal_anchors,
                )
            ) is not None
        ]
        ordered = self._ordered_hits(hits)
        selected = self._assemble(
            query=query,
            ordered=ordered,
        )
        coverage = self._coverage(query=query, hits=selected)
        return GeneralKnowledgePacket(
            query=query,
            hits=selected,
            coverage=coverage,
        )


__all__ = [
    "EXPLICIT_RELATION_EVIDENCE_BOOST",
    "MINIMUM_KNOWLEDGE_SCORE",
    "MENTIONED_CONCEPT_BOOST",
    "MENTIONED_ENTITY_BOOST",
    "PRIMARY_CONCEPT_BOOST",
    "PRIMARY_ENTITY_BOOST",
    "PRIOR_BLOCK_BOOST",
    "RELATION_MATCH_BOOST",
    "RELATION_MISMATCH_PENALTY",
    "GeneralKnowledgeRetriever",
]
