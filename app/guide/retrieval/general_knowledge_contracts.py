from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
import hashlib
import json
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.understanding.contracts import TopicCode


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

_SCHEMA_VERSION = "guide-general-knowledge-v1"
_ASSET_ID = "guide-general-knowledge-v1"
_MANDATORY_FORBIDDEN_USES = frozenset({
    "product_fact",
    "hard_filter",
    "soft_rank",
    "safety_guarantee",
    "profile_write",
})


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
        "guide-general-knowledge-v1"
    ] = _SCHEMA_VERSION
    asset_id: Literal[
        "guide-general-knowledge-v1"
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
            f"general_knowledge_v1.{self.blocks_sha256}.jsonl"
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
    raw_question: str = Field(min_length=1, max_length=4000)
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
        if self.raw_question != self.raw_question.strip():
            raise ValueError("knowledge question must be trimmed")
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


class GeneralKnowledgeHit(_StrictFrozenModel):
    block: GeneralKnowledgeBlock
    score: float = Field(ge=0.0, allow_inf_nan=False)
    matched_terms: tuple[str, ...] = Field(max_length=2048)

    @field_validator("matched_terms", mode="before")
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
        return self


class GeneralKnowledgePacket(_StrictFrozenModel):
    query: GeneralKnowledgeQuery
    hits: tuple[GeneralKnowledgeHit, ...] = Field(max_length=5)

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
        return self


__all__ = [
    "GeneralKnowledgeBlock",
    "GeneralKnowledgeDocument",
    "GeneralKnowledgeHit",
    "GeneralKnowledgeManifest",
    "GeneralKnowledgePacket",
    "GeneralKnowledgeQuery",
    "KnowledgeForbiddenUse",
    "KnowledgeReviewDecision",
    "KnowledgeUse",
    "general_knowledge_id",
]
