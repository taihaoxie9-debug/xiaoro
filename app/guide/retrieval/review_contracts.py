from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


SourceId = Annotated[
    str,
    StringConstraints(
        min_length=8,
        max_length=160,
        pattern=r"^review_[A-Za-z0-9._:-]+$",
    ),
]
SourceLocator = Annotated[
    str,
    StringConstraints(
        min_length=8,
        max_length=1000,
        pattern=r"^(https://|urn:|s3://|file://).+$",
    ),
]
Content = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
Version = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
CatalogId = Annotated[
    str,
    StringConstraints(
        min_length=8,
        max_length=160,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]
AuditLocator = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=8, max_length=500),
]


class ApprovedReviewEvidence(_StrictContract):
    source_id: SourceId
    product_id: int = Field(gt=0)
    source_kind: Literal["platform_consumer_review"]
    source_locator: SourceLocator
    content_kind: Literal["verbatim", "source_verifiable_excerpt"]
    content: Content
    content_sha256: Sha256
    collected_at: datetime
    collection_version: Version

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.collected_at.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        self.collected_at = self.collected_at.astimezone(UTC)
        digest = sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_sha256 != digest:
            raise ValueError("content sha256 mismatch")
        return self


class ReviewSourceCatalog(_StrictContract):
    catalog_id: CatalogId
    catalog_version: Version
    audit_locator: AuditLocator
    audited_at: datetime
    approved_source_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_audit_time(self) -> Self:
        if self.audited_at.utcoffset() is None:
            raise ValueError("audited_at must be timezone-aware")
        return self


class ReviewVerifiedAbsence(_StrictContract):
    kind: Literal["verified_absence"] = "verified_absence"
    product_id: int = Field(gt=0)
    reason: Literal[
        "no_approved_review_sources_for_product"
    ] = "no_approved_review_sources_for_product"
    catalog_id: CatalogId
    catalog_version: Version
    audit_locator: AuditLocator


class ReviewReadResult(_StrictContract):
    product_id: int = Field(gt=0)
    evidence: list[ApprovedReviewEvidence]
    verified_absence: ReviewVerifiedAbsence | None

    @model_validator(mode="after")
    def validate_evidence_or_absence(self) -> Self:
        if self.evidence:
            if self.verified_absence is not None:
                raise ValueError(
                    "review evidence forbids verified absence"
                )
            if any(
                item.product_id != self.product_id
                for item in self.evidence
            ):
                raise ValueError("review evidence product mismatch")
        else:
            if self.verified_absence is None:
                raise ValueError(
                    "empty review evidence requires verified absence"
                )
            if self.verified_absence.product_id != self.product_id:
                raise ValueError(
                    "review absence product mismatch"
                )
        return self
