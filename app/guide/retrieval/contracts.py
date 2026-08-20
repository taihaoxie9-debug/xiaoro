from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CandidateRef(_StrictContract):
    product_id: int
    source: str
    canonical_category: str
    canonical_category_state: Literal[
        "known",
        "unknown",
        "conflict",
        "not_applicable",
    ] = "known"
    retrieval_reason: str


class CanonicalField(_StrictContract):
    key: str
    value: JsonValue
    field_origin: str
    resolved_state: str
    source_classes: list[str]
    source_refs: list[str]
    evidence_status: str | None


class CanonicalProduct(_StrictContract):
    product_id: int
    schema_version: str
    fields: dict[str, CanonicalField]


class RetrievalResult(_StrictContract):
    candidates: list[CandidateRef]
    knowledge_evidence: list[JsonValue]
    review_evidence: list[JsonValue]
    memory_evidence: list[JsonValue]
    missing_sources: list[str]
