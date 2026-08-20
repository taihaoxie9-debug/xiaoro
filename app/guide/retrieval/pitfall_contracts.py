from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
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


EvidenceRef = Annotated[
    str,
    StringConstraints(
        min_length=20,
        max_length=200,
        pattern=r"^pitfall_evidence:[A-Za-z0-9._:-]+$",
    ),
]
FindingId = Annotated[
    str,
    StringConstraints(
        min_length=20,
        max_length=200,
        pattern=(
            r"^pitfall-v1:"
            r"(usage|compatibility|suitability|safety):"
            r"[A-Za-z0-9._:-]+$"
        ),
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
Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
Description = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
Version = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]


class PitfallSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PitfallClaimKind(str, Enum):
    USAGE = "usage"
    COMPATIBILITY = "compatibility"
    SUITABILITY = "suitability"
    SAFETY = "safety"


class PitfallEvidenceState(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    ABSENT = "absent"
    CONFLICT = "conflict"


class ApprovedPitfallEvidenceRef(_StrictContract):
    evidence_ref: EvidenceRef
    product_id: int = Field(gt=0)
    source_kind: Literal[
        "canonical_reviewed_fact",
        "approved_review_evidence",
    ]
    source_locator: SourceLocator
    content: Content
    content_sha256: Sha256
    approved_at: datetime
    approval_version: Version

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.approved_at.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")
        self.approved_at = self.approved_at.astimezone(UTC)
        digest = sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_sha256 != digest:
            raise ValueError("content sha256 mismatch")
        return self


class PitfallFinding(_StrictContract):
    finding_id: FindingId
    product_id: int = Field(gt=0)
    severity: PitfallSeverity
    claim_kind: PitfallClaimKind
    evidence_state: PitfallEvidenceState
    title: Title | None = None
    description: Description | None = None
    evidence_refs: list[EvidenceRef]

    @model_validator(mode="after")
    def validate_conclusion_state(self) -> Self:
        self.evidence_refs = sorted(set(self.evidence_refs))
        if self.evidence_state is PitfallEvidenceState.KNOWN:
            if self.title is None or self.description is None:
                raise ValueError(
                    "known pitfall finding requires conclusion text"
                )
            if not self.evidence_refs:
                raise ValueError(
                    "known pitfall finding requires evidence refs"
                )
            return self

        if self.title is not None or self.description is not None:
            raise ValueError(
                "unresolved pitfall finding forbids conclusion text"
            )
        if (
            self.evidence_state
            in {
                PitfallEvidenceState.UNKNOWN,
                PitfallEvidenceState.ABSENT,
            }
            and self.evidence_refs
        ):
            raise ValueError(
                "unknown or absent pitfall finding forbids evidence refs"
            )
        return self


class TypedPitfall(_StrictContract):
    finding_id: FindingId
    product_id: int = Field(gt=0)
    severity: PitfallSeverity
    claim_kind: PitfallClaimKind
    title: Title
    description: Description
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
