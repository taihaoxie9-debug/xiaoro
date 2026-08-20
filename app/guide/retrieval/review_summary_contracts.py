from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.guide.retrieval.review_contracts import (
    Content,
    Sha256,
    SourceId,
    SourceLocator,
    Version,
)


class _StrictContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )


FactClaimId = Annotated[
    str,
    StringConstraints(pattern=r"^review-fact-v1:[0-9a-f]{64}$"),
]
SynthesisClaimId = Annotated[
    str,
    StringConstraints(pattern=r"^review-synthesis-v1:[0-9a-f]{64}$"),
]
SynthesisText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]

_CONTENT_ADAPTER = TypeAdapter(Content)
_SYNTHESIS_TEXT_ADAPTER = TypeAdapter(SynthesisText)


class ReviewClaimProvenance(_StrictContract):
    source_id: SourceId
    product_id: int = Field(gt=0)
    source_kind: Literal["platform_consumer_review"]
    source_locator: SourceLocator
    content_kind: Literal["verbatim", "source_verifiable_excerpt"]
    content_sha256: Sha256
    collected_at: datetime
    collection_version: Version

    @field_validator("collected_at")
    @classmethod
    def normalize_collection_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        return value.astimezone(UTC)


class ReviewSourceFact(_StrictContract):
    claim_id: FactClaimId
    kind: Literal["source_quote"] = "source_quote"
    quote: Content
    provenance: ReviewClaimProvenance

    @model_validator(mode="after")
    def validate_source_fact(self) -> Self:
        digest = sha256(self.quote.encode("utf-8")).hexdigest()
        if digest != self.provenance.content_sha256:
            raise ValueError("source fact quote hash mismatch")
        if self.claim_id != review_fact_claim_id(
            quote=self.quote,
            provenance=self.provenance,
        ):
            raise ValueError("source fact claim_id mismatch")
        return self


class ReviewDeterministicSynthesis(_StrictContract):
    claim_id: SynthesisClaimId
    kind: Literal[
        "deterministic_synthesis"
    ] = "deterministic_synthesis"
    method: Literal[
        "structured_source_facts_v1"
    ] = "structured_source_facts_v1"
    text: SynthesisText
    basis_fact_ids: tuple[FactClaimId, ...] = Field(min_length=1)
    provenance: tuple[ReviewClaimProvenance, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_synthesis_claim(self) -> Self:
        if len(self.basis_fact_ids) != len(set(self.basis_fact_ids)):
            raise ValueError("synthesis basis facts must be unique")
        source_ids = [item.source_id for item in self.provenance]
        if source_ids != sorted(source_ids):
            raise ValueError("synthesis provenance must be ordered")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("synthesis provenance must be unique")
        if self.claim_id != review_synthesis_claim_id(
            text=self.text,
            basis_fact_ids=self.basis_fact_ids,
            provenance=self.provenance,
        ):
            raise ValueError("synthesis claim_id mismatch")
        return self


class ReviewSummaryResult(_StrictContract):
    product_id: int = Field(gt=0)
    source_facts: tuple[ReviewSourceFact, ...] = Field(min_length=1)
    synthesis: ReviewDeterministicSynthesis

    @model_validator(mode="after")
    def validate_summary_links(self) -> Self:
        source_ids = [
            item.provenance.source_id for item in self.source_facts
        ]
        if source_ids != sorted(source_ids):
            raise ValueError("source facts must be ordered")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source facts must be unique")
        if any(
            item.provenance.product_id != self.product_id
            for item in self.source_facts
        ):
            raise ValueError("source fact product mismatch")

        fact_ids = tuple(
            item.claim_id for item in self.source_facts
        )
        if self.synthesis.basis_fact_ids != fact_ids:
            raise ValueError("synthesis basis does not match source facts")
        fact_provenance = tuple(
            item.provenance for item in self.source_facts
        )
        if self.synthesis.provenance != fact_provenance:
            raise ValueError(
                "synthesis provenance does not match source facts"
            )
        if self.synthesis.text != deterministic_synthesis_text(
            self.source_facts
        ):
            raise ValueError("synthesis text is not deterministic")
        return self


def review_fact_claim_id(
    *,
    quote: str,
    provenance: ReviewClaimProvenance,
) -> str:
    payload = _canonical_json(
        {
            "source_id": provenance.source_id,
            "product_id": provenance.product_id,
            "source_kind": provenance.source_kind,
            "source_locator": provenance.source_locator,
            "content_kind": provenance.content_kind,
            "quote": quote,
            "content_sha256": provenance.content_sha256,
            "collected_at": provenance.collected_at.isoformat(),
            "collection_version": provenance.collection_version,
        }
    )
    return f"review-fact-v1:{sha256(payload.encode('utf-8')).hexdigest()}"


def create_review_source_fact(
    *,
    quote: str,
    provenance: ReviewClaimProvenance,
) -> ReviewSourceFact:
    normalized_quote = _CONTENT_ADAPTER.validate_python(
        quote,
        strict=True,
    )
    return ReviewSourceFact(
        claim_id=review_fact_claim_id(
            quote=normalized_quote,
            provenance=provenance,
        ),
        quote=normalized_quote,
        provenance=provenance,
    )


def deterministic_synthesis_text(
    source_facts: tuple[ReviewSourceFact, ...],
) -> str:
    return (
        f"综合基于 {len(source_facts)} 条已验证来源事实；"
        "原文和来源信息仅见 source_facts。"
    )


def review_synthesis_claim_id(
    *,
    text: str,
    basis_fact_ids: tuple[str, ...],
    provenance: tuple[ReviewClaimProvenance, ...],
) -> str:
    payload = _canonical_json(
        {
            "method": "structured_source_facts_v1",
            "text": text,
            "basis_fact_ids": basis_fact_ids,
            "provenance": [
                item.model_dump(mode="json")
                for item in provenance
            ],
        }
    )
    return (
        "review-synthesis-v1:"
        f"{sha256(payload.encode('utf-8')).hexdigest()}"
    )


def create_review_synthesis(
    source_facts: tuple[ReviewSourceFact, ...],
) -> ReviewDeterministicSynthesis:
    text = _SYNTHESIS_TEXT_ADAPTER.validate_python(
        deterministic_synthesis_text(source_facts),
        strict=True,
    )
    basis_fact_ids = tuple(
        item.claim_id for item in source_facts
    )
    provenance = tuple(
        item.provenance for item in source_facts
    )
    return ReviewDeterministicSynthesis(
        claim_id=review_synthesis_claim_id(
            text=text,
            basis_fact_ids=basis_fact_ids,
            provenance=provenance,
        ),
        text=text,
        basis_fact_ids=basis_fact_ids,
        provenance=provenance,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
