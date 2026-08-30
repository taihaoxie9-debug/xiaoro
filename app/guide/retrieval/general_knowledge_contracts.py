from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.knowledge_relation_contracts import (
    KnowledgeRelationIntent,
)


KnowledgeReviewDecision = Literal[
    "general_answer",
    "escalation_only",
    "product_specific_redirect",
    "rejected",
]
KnowledgeUse = Literal[
    "answer",
    "citation",
    "followup",
    "medical_escalation",
]
KnowledgeForbiddenUse = Literal[
    "product_fact",
    "hard_filter",
    "soft_rank",
    "safety_guarantee",
    "profile_write",
]

_SCHEMA_VERSION = "guide-general-knowledge-v2"
_ASSET_ID = "guide-general-knowledge-v2"
_MANDATORY_FORBIDDEN_USES = frozenset({
    "product_fact",
    "hard_filter",
    "soft_rank",
    "safety_guarantee",
    "profile_write",
})
_KNOWLEDGE_CONCEPT_ID = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"
)
_KNOWLEDGE_ENTITY_ID = re.compile(
    r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


def _canonical_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(
                value.items(),
                key=lambda pair: str(pair[0]),
            )
        }
    if isinstance(value, (set, frozenset)):
        normalized = [_canonical_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def general_knowledge_id(payload: Mapping[str, object]) -> str:
    if not isinstance(payload, Mapping):
        raise TypeError("knowledge ID payload must be a mapping")
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _validate_source_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or "." in path.parts
        or ".." in path.parts
        or path.parts[:2] != ("data", "knowledge_docs")
        or path.suffix != ".md"
    ):
        raise ValueError(
            "knowledge source path must be repository-relative"
        )
    return value


class GeneralKnowledgeDocument(_StrictFrozenModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=256)
    source_path: str = Field(min_length=1, max_length=512)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_kind: Literal["educational_seed"] = "educational_seed"

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return _validate_source_path(value)

    @model_validator(mode="after")
    def validate_document_id(self) -> Self:
        expected = general_knowledge_id(
            self.model_dump(mode="json", exclude={"document_id"})
        )
        if self.document_id != expected:
            raise ValueError("general knowledge document ID mismatch")
        return self


class GeneralKnowledgeRetrievalProfile(_StrictFrozenModel):
    source_path: str = Field(min_length=1, max_length=512)
    primary_concept_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=16,
    )
    primary_entity_ids: tuple[str, ...] = Field(max_length=8)
    section_relations: dict[
        str,
        tuple[KnowledgeRelationIntent, ...],
    ]

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return _validate_source_path(value)

    @field_validator(
        "primary_concept_ids",
        "primary_entity_ids",
        mode="before",
    )
    @classmethod
    def freeze_profile_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("section_relations", mode="before")
    @classmethod
    def freeze_section_relations(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        return {
            key: tuple(relations)
            if isinstance(relations, list)
            else relations
            for key, relations in value.items()
        }

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        for label, values, pattern in (
            (
                "primary concept IDs",
                self.primary_concept_ids,
                _KNOWLEDGE_CONCEPT_ID,
            ),
            (
                "primary entity IDs",
                self.primary_entity_ids,
                _KNOWLEDGE_ENTITY_ID,
            ),
        ):
            if (
                values != tuple(sorted(set(values)))
                or any(pattern.fullmatch(value) is None for value in values)
            ):
                raise ValueError(f"{label} must be ordered unique")
        if (
            not self.section_relations
            or any(
                not section
                or section != section.strip()
                or not relations
                or relations != tuple(sorted(set(relations)))
                for section, relations in self.section_relations.items()
            )
        ):
            raise ValueError(
                "section relation metadata must be nonempty and ordered unique"
            )
        return self


def _block_identity(block: GeneralKnowledgeBlock) -> dict[str, object]:
    return {
        "document_id": block.document_id,
        "title": block.title,
        "section_title": block.section_title,
        "exact_text": block.exact_text,
        "source_path": block.source_path,
        "source_sha256": block.source_sha256,
        "block_sha256": block.block_sha256,
        "section_order": block.section_order,
    }


class GeneralKnowledgeBlock(_StrictFrozenModel):
    knowledge_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=256)
    section_title: str = Field(min_length=1, max_length=256)
    exact_text: str = Field(min_length=1, max_length=4000)
    public_text: str | None = Field(
        default=None,
        min_length=1,
        max_length=4000,
    )
    source_path: str = Field(min_length=1, max_length=512)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    block_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    section_order: int = Field(ge=0)
    review_decision: KnowledgeReviewDecision
    allowed_uses: frozenset[KnowledgeUse]
    forbidden_uses: frozenset[KnowledgeForbiddenUse]
    review_rationale: str = Field(min_length=1, max_length=1000)
    retrieval_terms: tuple[str, ...] = Field(
        min_length=1,
        max_length=2048,
    )
    primary_concept_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    mentioned_concept_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    primary_entity_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    mentioned_entity_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    relation_intents: tuple[KnowledgeRelationIntent, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return _validate_source_path(value)

    @field_validator(
        "allowed_uses",
        "forbidden_uses",
        mode="before",
    )
    @classmethod
    def freeze_uses(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @field_validator("retrieval_terms", mode="before")
    @classmethod
    def freeze_terms(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator(
        "primary_concept_ids",
        "mentioned_concept_ids",
        "primary_entity_ids",
        "mentioned_entity_ids",
        "relation_intents",
        mode="before",
    )
    @classmethod
    def freeze_retrieval_metadata(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_block(self) -> Self:
        if self.exact_text != self.exact_text.strip():
            raise ValueError("knowledge exact text must be trimmed")
        if (
            self.public_text is not None
            and self.public_text != self.public_text.strip()
        ):
            raise ValueError("knowledge public text must be trimmed")
        if self.review_rationale != self.review_rationale.strip():
            raise ValueError("knowledge review rationale must be trimmed")
        if self.block_sha256 != hashlib.sha256(
            self.exact_text.encode("utf-8")
        ).hexdigest():
            raise ValueError("knowledge block SHA mismatch")
        if self.knowledge_id != general_knowledge_id(
            _block_identity(self)
        ):
            raise ValueError("knowledge ID mismatch")
        if self.forbidden_uses != _MANDATORY_FORBIDDEN_USES:
            raise ValueError(
                "knowledge block requires all mandatory forbidden uses"
            )
        if (
            self.retrieval_terms
            != tuple(sorted(set(self.retrieval_terms)))
            or any(
                not term
                or term != term.strip()
                or len(term) > 128
                for term in self.retrieval_terms
            )
        ):
            raise ValueError(
                "retrieval terms must be sorted and unique"
            )
        for label, values, pattern in (
            (
                "primary concept IDs",
                self.primary_concept_ids,
                _KNOWLEDGE_CONCEPT_ID,
            ),
            (
                "mentioned concept IDs",
                self.mentioned_concept_ids,
                _KNOWLEDGE_CONCEPT_ID,
            ),
            (
                "primary entity IDs",
                self.primary_entity_ids,
                _KNOWLEDGE_ENTITY_ID,
            ),
            (
                "mentioned entity IDs",
                self.mentioned_entity_ids,
                _KNOWLEDGE_ENTITY_ID,
            ),
        ):
            if (
                values != tuple(sorted(set(values)))
                or any(pattern.fullmatch(value) is None for value in values)
            ):
                raise ValueError(f"{label} must be sorted and unique")
        if self.relation_intents != tuple(
            sorted(set(self.relation_intents))
        ):
            raise ValueError(
                "knowledge relation intents must be sorted and unique"
            )
        if self.review_decision == "general_answer":
            if not {"answer", "citation"} <= self.allowed_uses:
                raise ValueError(
                    "general answer requires answer and citation"
                )
            if "medical_escalation" in self.allowed_uses:
                raise ValueError(
                    "general answer forbids medical escalation use"
                )
            if self.public_text is None:
                raise ValueError(
                    "general answer requires reviewed public text"
                )
        elif self.review_decision == "escalation_only":
            if "answer" in self.allowed_uses:
                raise ValueError(
                    "escalation-only block forbids answer"
                )
            if not {
                "citation",
                "medical_escalation",
            } <= self.allowed_uses:
                raise ValueError(
                    "escalation-only block requires escalation citation"
                )
            if self.public_text is not None:
                raise ValueError(
                    "non-answer knowledge forbids public text"
                )
        elif self.review_decision == "product_specific_redirect":
            if "answer" in self.allowed_uses:
                raise ValueError("product redirect forbids answer")
            if "medical_escalation" in self.allowed_uses:
                raise ValueError(
                    "product redirect forbids medical escalation"
                )
            if self.public_text is not None:
                raise ValueError(
                    "non-answer knowledge forbids public text"
                )
        elif self.allowed_uses:
            raise ValueError("rejected block forbids allowed uses")
        elif self.public_text is not None:
            raise ValueError("rejected block forbids public text")
        return self


class GeneralKnowledgeManifest(_StrictFrozenModel):
    schema_version: Literal[
        "guide-general-knowledge-v1",
        "guide-general-knowledge-v2",
    ] = _SCHEMA_VERSION
    asset_id: Literal[
        "guide-general-knowledge-v1",
        "guide-general-knowledge-v2",
    ] = _ASSET_ID
    asset_version: str = Field(min_length=1, max_length=64)
    blocks_file: str = Field(min_length=1, max_length=255)
    blocks_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    block_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    document_count: int = Field(ge=0)
    source_document_ids: tuple[str, ...]
    source_sha256s: tuple[str, ...]
    review_file_sha256s: tuple[str, ...]
    retrieval_profile_path: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    retrieval_profile_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    decision_counts: dict[KnowledgeReviewDecision, int]
    allowed_use_counts: dict[KnowledgeUse, int]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "source_document_ids",
        "source_sha256s",
        "review_file_sha256s",
        mode="before",
    )
    @classmethod
    def freeze_hashes(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        expected_version = self.schema_version.rsplit("-", 1)[-1]
        if self.asset_id != self.schema_version:
            raise ValueError(
                "general knowledge asset and schema versions must match"
            )
        if self.schema_version == "guide-general-knowledge-v2":
            if (
                self.retrieval_profile_path
                != (
                    "docs/audits/general-knowledge/"
                    "retrieval_profiles_v1.jsonl"
                )
                or self.retrieval_profile_sha256 is None
            ):
                raise ValueError(
                    "v2 knowledge manifest requires retrieval profile"
                )
        elif (
            self.retrieval_profile_path is not None
            or self.retrieval_profile_sha256 is not None
        ):
            raise ValueError(
                "v1 knowledge manifest forbids retrieval profile"
            )
        inventories = (
            self.source_document_ids,
            self.source_sha256s,
            self.review_file_sha256s,
        )
        if any(
            values != tuple(sorted(set(values)))
            or any(
                len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
                for value in values
            )
            for values in inventories
        ):
            raise ValueError(
                "knowledge manifest hash inventories are invalid"
            )
        if (
            len(self.source_document_ids) != self.document_count
            or len(self.source_sha256s) != self.document_count
        ):
            raise ValueError(
                "knowledge manifest document count mismatch"
            )
        if sum(self.decision_counts.values()) != self.candidate_count:
            raise ValueError(
                "knowledge manifest candidate count mismatch"
            )
        published = (
            self.decision_counts.get("general_answer", 0)
            + self.decision_counts.get("escalation_only", 0)
            + self.decision_counts.get("product_specific_redirect", 0)
        )
        if published != self.block_count:
            raise ValueError("knowledge manifest block count mismatch")
        expected_file = (
            f"general_knowledge_{expected_version}."
            f"{self.blocks_sha256}.jsonl"
        )
        if self.blocks_file != expected_file:
            raise ValueError(
                "knowledge manifest blocks file is not content addressed"
            )
        expected_sha = general_knowledge_id(
            self.model_dump(
                mode="json",
                exclude={"manifest_sha256"},
            )
        )
        if self.manifest_sha256 != expected_sha:
            raise ValueError("knowledge manifest SHA mismatch")
        return self


class GeneralKnowledgeQuery(_StrictFrozenModel):
    retrieval_query: str = Field(min_length=1, max_length=4000)
    question_meaning: str = Field(min_length=1, max_length=512)
    topic: TopicCode | None
    safety_sensitive: bool
    prior_knowledge_ids: tuple[str, ...] = Field(max_length=16)
    top_k: int = Field(default=3, ge=1, le=5)

    @field_validator("topic", mode="before")
    @classmethod
    def parse_topic(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return TopicCode(value)
            except ValueError:
                return value
        return value

    @field_validator("prior_knowledge_ids", mode="before")
    @classmethod
    def freeze_prior_ids(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        if self.retrieval_query != self.retrieval_query.strip():
            raise ValueError("knowledge retrieval query must be trimmed")
        if self.question_meaning != self.question_meaning.strip():
            raise ValueError("knowledge meaning must be trimmed")
        if (
            self.prior_knowledge_ids
            != tuple(sorted(set(self.prior_knowledge_ids)))
            or any(
                len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
                for value in self.prior_knowledge_ids
            )
        ):
            raise ValueError(
                "prior knowledge IDs must be sorted and unique"
            )
        return self


class KnowledgeEntityMention(_StrictFrozenModel):
    entity_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
    )
    raw_text: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_raw_text(self) -> Self:
        if self.raw_text != self.raw_text.strip():
            raise ValueError("knowledge entity raw text must be trimmed")
        return self


class KnowledgeQuerySpec(_StrictFrozenModel):
    raw_query: str = Field(min_length=1, max_length=4000)
    question_meaning: str = Field(min_length=1, max_length=512)
    concept_ids: tuple[str, ...] = Field(max_length=16)
    entity_mentions: tuple[KnowledgeEntityMention, ...] = Field(max_length=8)
    relation_intents: tuple[KnowledgeRelationIntent, ...] = Field(max_length=8)
    safety_sensitive: bool
    prior_knowledge_ids: tuple[str, ...] = Field(max_length=16)
    top_k: int = Field(default=3, ge=1, le=5)

    @field_validator(
        "concept_ids",
        "entity_mentions",
        "relation_intents",
        "prior_knowledge_ids",
        mode="before",
    )
    @classmethod
    def freeze_query_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_query_spec(self) -> Self:
        if self.raw_query != self.raw_query.strip():
            raise ValueError("knowledge raw query must be trimmed")
        if self.question_meaning != self.question_meaning.strip():
            raise ValueError("knowledge meaning must be trimmed")
        if any(
            not value
            or value != value.strip()
            or not all(
                part
                and part[0].isalpha()
                and all(
                    character.islower()
                    or character.isdigit()
                    or character == "_"
                    for character in part
                )
                for part in value.split(".")
            )
            for value in self.concept_ids
        ):
            raise ValueError("knowledge concept IDs are invalid")
        for name, values in (
            ("concept IDs", self.concept_ids),
            ("relation intents", self.relation_intents),
        ):
            if len(values) != len(set(values)):
                raise ValueError(
                    f"knowledge {name} must be ordered unique"
                )
        entity_ids = tuple(
            mention.entity_id for mention in self.entity_mentions
        )
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError(
                "knowledge entity mentions must be ordered unique"
            )
        if (
            self.prior_knowledge_ids
            != tuple(sorted(set(self.prior_knowledge_ids)))
            or any(
                len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
                for value in self.prior_knowledge_ids
            )
        ):
            raise ValueError(
                "prior knowledge IDs must be sorted and unique"
            )
        return self


class GeneralKnowledgeCoverage(_StrictFrozenModel):
    required_concept_ids: tuple[str, ...] = Field(max_length=16)
    covered_concept_ids: tuple[str, ...] = Field(max_length=16)
    required_entity_ids: tuple[str, ...] = Field(max_length=8)
    covered_entity_ids: tuple[str, ...] = Field(max_length=8)
    required_relation_intents: tuple[
        KnowledgeRelationIntent, ...
    ] = Field(max_length=8)
    covered_relation_intents: tuple[
        KnowledgeRelationIntent, ...
    ] = Field(max_length=8)
    missing_concept_ids: tuple[str, ...] = Field(max_length=16)
    missing_entity_ids: tuple[str, ...] = Field(max_length=8)
    missing_relation_intents: tuple[
        KnowledgeRelationIntent, ...
    ] = Field(max_length=8)
    complete: bool

    @field_validator(
        "required_concept_ids",
        "covered_concept_ids",
        "required_entity_ids",
        "covered_entity_ids",
        "required_relation_intents",
        "covered_relation_intents",
        "missing_concept_ids",
        "missing_entity_ids",
        "missing_relation_intents",
        mode="before",
    )
    @classmethod
    def freeze_coverage_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        for name in (
            "required_concept_ids",
            "covered_concept_ids",
            "required_entity_ids",
            "covered_entity_ids",
            "required_relation_intents",
            "covered_relation_intents",
            "missing_concept_ids",
            "missing_entity_ids",
            "missing_relation_intents",
        ):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(
                    "knowledge coverage values must be ordered unique"
                )
        expected_missing_concepts = tuple(
            value
            for value in self.required_concept_ids
            if value not in self.covered_concept_ids
        )
        expected_missing_entities = tuple(
            value
            for value in self.required_entity_ids
            if value not in self.covered_entity_ids
        )
        expected_missing_relations = tuple(
            value
            for value in self.required_relation_intents
            if value not in self.covered_relation_intents
        )
        if (
            self.missing_concept_ids != expected_missing_concepts
            or self.missing_entity_ids != expected_missing_entities
            or self.missing_relation_intents != expected_missing_relations
        ):
            raise ValueError(
                "knowledge coverage missing requirements are inconsistent"
            )
        expected_complete = not (
            expected_missing_concepts
            or expected_missing_entities
            or expected_missing_relations
        )
        if self.complete is not expected_complete:
            raise ValueError(
                "knowledge coverage complete flag is inconsistent"
            )
        return self


class GeneralKnowledgeHit(_StrictFrozenModel):
    block: GeneralKnowledgeBlock
    score: float = Field(ge=0.0, allow_inf_nan=False)
    matched_terms: tuple[str, ...] = Field(max_length=2048)
    matched_concept_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    matched_entity_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    supported_relation_intents: tuple[
        KnowledgeRelationIntent, ...
    ] = Field(
        default_factory=tuple,
        max_length=8,
    )
    direct_multi_entity_evidence: bool = False

    @field_validator(
        "matched_terms",
        "matched_concept_ids",
        "matched_entity_ids",
        "supported_relation_intents",
        mode="before",
    )
    @classmethod
    def freeze_matched_terms(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_hit(self) -> Self:
        if self.block.review_decision == "rejected":
            raise ValueError("rejected block cannot be retrieved")
        if (
            self.matched_terms
            != tuple(sorted(set(self.matched_terms)))
            or not set(self.matched_terms).issubset(
                self.block.retrieval_terms
            )
        ):
            raise ValueError(
                "matched terms must be sorted source terms"
            )
        for label, values in (
            ("matched concept IDs", self.matched_concept_ids),
            ("matched entity IDs", self.matched_entity_ids),
            (
                "supported relation intents",
                self.supported_relation_intents,
            ),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{label} must be sorted and unique")
        if not set(self.matched_concept_ids) <= set(
            self.block.primary_concept_ids
        ).union(self.block.mentioned_concept_ids):
            raise ValueError(
                "matched concept IDs must belong to the block"
            )
        if not set(self.matched_entity_ids) <= set(
            self.block.primary_entity_ids
        ).union(self.block.mentioned_entity_ids):
            raise ValueError(
                "matched entity IDs must belong to the block"
            )
        if (
            self.direct_multi_entity_evidence
            and len(self.matched_entity_ids) < 2
        ):
            raise ValueError(
                "direct multi-entity evidence requires two matched entities"
            )
        return self


class GeneralKnowledgePacket(_StrictFrozenModel):
    query: GeneralKnowledgeQuery | KnowledgeQuerySpec
    hits: tuple[GeneralKnowledgeHit, ...] = Field(max_length=5)
    coverage: GeneralKnowledgeCoverage | None = None

    @field_validator("hits", mode="before")
    @classmethod
    def freeze_hits(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_packet(self) -> Self:
        if len(self.hits) > self.query.top_k:
            raise ValueError("knowledge packet exceeds query top_k")
        expected = tuple(
            sorted(
                self.hits,
                key=lambda hit: (
                    -hit.score,
                    hit.block.document_id,
                    hit.block.section_order,
                    hit.block.knowledge_id,
                ),
            )
        )
        if self.hits != expected:
            raise ValueError(
                "knowledge hits must use deterministic order"
            )
        ids = tuple(hit.block.knowledge_id for hit in self.hits)
        if len(ids) != len(set(ids)):
            raise ValueError("knowledge packet contains duplicate blocks")
        if isinstance(self.query, KnowledgeQuerySpec):
            if self.coverage is None:
                raise ValueError(
                    "typed knowledge packet requires coverage"
                )
            required_entity_ids = tuple(
                item.entity_id for item in self.query.entity_mentions
            )
            if (
                self.coverage.required_concept_ids
                != self.query.concept_ids
                or self.coverage.required_entity_ids
                != required_entity_ids
                or self.coverage.required_relation_intents
                != self.query.relation_intents
            ):
                raise ValueError(
                    "knowledge packet coverage differs from query"
                )
        return self


__all__ = [
    "GeneralKnowledgeBlock",
    "GeneralKnowledgeCoverage",
    "GeneralKnowledgeDocument",
    "GeneralKnowledgeHit",
    "GeneralKnowledgeManifest",
    "GeneralKnowledgePacket",
    "GeneralKnowledgeQuery",
    "GeneralKnowledgeRetrievalProfile",
    "KnowledgeEntityMention",
    "KnowledgeQuerySpec",
    "KnowledgeForbiddenUse",
    "KnowledgeReviewDecision",
    "KnowledgeUse",
    "general_knowledge_id",
]
