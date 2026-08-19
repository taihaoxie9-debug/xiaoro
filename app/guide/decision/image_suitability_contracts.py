from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.session_contract import SessionId
from app.guide.understanding.contracts import (
    OpaqueBundleId,
    OpaqueImageId,
    SkinTarget,
)


EvidenceRef = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]


_REVIEWED_EVIDENCE_ID = re.compile(r"[0-9a-f]{64}")
_BASE_ROW_EVIDENCE_REF = re.compile(
    r"data/seed_dump\.sql#product=([1-9][0-9]*)"
)


def _validate_canonical_suitability_evidence_ref(value: str) -> str:
    if (
        _REVIEWED_EVIDENCE_ID.fullmatch(value)
        or _BASE_ROW_EVIDENCE_REF.fullmatch(value)
    ):
        return value
    raise ValueError(
        "Canonical suitability evidence reference is not approved"
    )


CanonicalSuitabilityEvidenceRef = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=256,
    ),
    AfterValidator(_validate_canonical_suitability_evidence_ref),
]
ContextValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SuitabilityContextSource(str, Enum):
    CURRENT_EXPLICIT_INPUT = "current_explicit_input"
    CONFIRMED_SESSION = "confirmed_session"
    LONG_TERM_PROFILE = "long_term_profile"


_CONTEXT_PRECEDENCE = {
    SuitabilityContextSource.CURRENT_EXPLICIT_INPUT: 1,
    SuitabilityContextSource.CONFIRMED_SESSION: 2,
    SuitabilityContextSource.LONG_TERM_PROFILE: 3,
}


class SuitabilityContextProvenance(_StrictFrozen):
    """Server-constructed provenance; never hydrate this from client IDs."""

    current_bundle_id: OpaqueBundleId
    current_image_id: OpaqueImageId
    session_id: SessionId
    conversation_version: int = Field(ge=0)
    source_kind: SuitabilityContextSource
    evidence_ref: EvidenceRef
    profile_owner: ProfileOwnerRef | None = None
    profile_version: int | None = Field(default=None, ge=1)
    profile_confirmed: bool | None = None

    @model_validator(mode="after")
    def validate_profile_provenance(self) -> Self:
        profile_fields = (
            self.profile_owner,
            self.profile_version,
            self.profile_confirmed,
        )
        if self.source_kind is SuitabilityContextSource.LONG_TERM_PROFILE:
            if any(value is None for value in profile_fields):
                raise ValueError(
                    "profile source requires complete profile provenance"
                )
            return self
        if any(value is not None for value in profile_fields):
            raise ValueError(
                "non-profile source forbids profile provenance"
            )
        return self


class SuitabilityContextClaim(_StrictFrozen):
    """A server-created context fact bound to exact server provenance."""

    skin_target: ContextValue
    provenance: SuitabilityContextProvenance


class SuitabilityContextClaims(_StrictFrozen):
    claims: tuple[SuitabilityContextClaim, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def require_unique_sources(self) -> Self:
        sources = [
            claim.provenance.source_kind for claim in self.claims
        ]
        if len(sources) != len(set(sources)):
            raise ValueError("suitability context sources must be unique")
        return self


class ResolvedSuitabilityContext(_StrictFrozen):
    precedence: Literal[1, 2, 3]
    skin_target: SkinTarget
    provenance: SuitabilityContextProvenance

    @model_validator(mode="after")
    def require_source_precedence(self) -> Self:
        if (
            self.precedence
            != _CONTEXT_PRECEDENCE[self.provenance.source_kind]
        ):
            raise ValueError(
                "suitability context precedence must match its source"
            )
        return self

    @property
    def source(self) -> SuitabilityContextSource:
        return self.provenance.source_kind

    @property
    def evidence_ref(self) -> str:
        return self.provenance.evidence_ref


class SuitabilityContextResolution(_StrictFrozen):
    kind: Literal["resolved", "absent", "unsupported"]
    context: ResolvedSuitabilityContext | None = None
    source: SuitabilityContextSource | None = None
    unsupported_value: ContextValue | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if self.kind == "resolved":
            if (
                self.context is None
                or self.source is not None
                or self.unsupported_value is not None
            ):
                raise ValueError(
                    "resolved context requires only resolved context data"
                )
            return self
        if self.context is not None:
            raise ValueError(
                "unresolved context forbids resolved context data"
            )
        if self.kind == "absent":
            if self.source is not None or self.unsupported_value is not None:
                raise ValueError("absent context forbids issue metadata")
            return self
        if self.source is None or self.unsupported_value is None:
            raise ValueError(
                "unsupported context requires source and raw value"
            )
        return self


class ImageSuitabilityDecisionReference(_StrictFrozen):
    ordinal: Literal[1]
    image_id: OpaqueImageId
    product_id: int = Field(ge=1)


class ImageSuitabilityDecisionFacts(DecisionProductFacts):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )
    suitable_skin_source_refs: tuple[
        CanonicalSuitabilityEvidenceRef,
        ...,
    ] = ()

    @model_validator(mode="after")
    def require_matching_base_row_evidence(self) -> Self:
        for reference in self.suitable_skin_source_refs:
            match = _BASE_ROW_EVIDENCE_REF.fullmatch(reference)
            if (
                match is not None
                and int(match.group(1)) != self.product_id
            ):
                raise ValueError(
                    "Canonical suitability evidence product mismatch"
                )
        return self


class SuitabilityEvaluatedSkinFact(_StrictFrozen):
    state: FactState
    values: tuple[str, ...] | None
    source_refs: tuple[CanonicalSuitabilityEvidenceRef, ...] = ()

    @model_validator(mode="after")
    def validate_fact(self) -> Self:
        if self.state is FactState.KNOWN:
            if self.values is None:
                raise ValueError("known suitable skin fact requires values")
        elif self.values is not None:
            raise ValueError(
                "unknown suitable skin fact forbids values"
            )
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError(
                "suitable skin evidence references must be unique"
            )
        return self


class SuitabilityCardIntent(_StrictFrozen):
    mode: Literal["single"]
    visible_product_ids: tuple[int, ...]
    reason: Literal["product"]

    @model_validator(mode="after")
    def require_exactly_one_product(self) -> Self:
        if (
            len(self.visible_product_ids) != 1
            or self.visible_product_ids[0] < 1
        ):
            raise ValueError(
                "suitability card intent requires exactly one product"
            )
        return self


class ImageSuitabilityDecisionInput(_StrictFrozen):
    reference: ImageSuitabilityDecisionReference
    context: ResolvedSuitabilityContext
    facts: ImageSuitabilityDecisionFacts

    @field_validator("facts", mode="before")
    @classmethod
    def deeply_freeze_facts(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, DecisionProductFacts):
            return ImageSuitabilityDecisionFacts.model_validate(
                value.model_dump(mode="python")
            )
        return value

    @model_validator(mode="after")
    def require_fact_identity(self) -> Self:
        if self.facts.product_id != self.reference.product_id:
            raise ValueError(
                "suitability facts product_id must match image identity"
            )
        return self


class ImageSuitabilityDecisionResult(_StrictFrozen):
    status: Literal[
        "suitable",
        "not_suitable",
        "insufficient_evidence",
    ]
    reason: Literal[
        "canonical_skin_match",
        "canonical_skin_explicit_exclusion",
        "canonical_skin_unknown",
        "canonical_skin_conflict",
        "canonical_skin_not_applicable",
        "canonical_skin_unaudited",
        "canonical_skin_indeterminate",
    ]
    reference: ImageSuitabilityDecisionReference
    context: ResolvedSuitabilityContext
    evaluated_skin_fact: SuitabilityEvaluatedSkinFact
    evidence_refs: tuple[EvidenceRef, ...]
    card_intent: SuitabilityCardIntent

    @model_validator(mode="after")
    def validate_auditable_result(self) -> Self:
        if self.card_intent.visible_product_ids != (
            self.reference.product_id,
        ):
            raise ValueError(
                "suitability card product must match confirmed identity"
            )
        expected_refs = (
            self.context.evidence_ref,
            *self.evaluated_skin_fact.source_refs,
        )
        if self.evidence_refs != expected_refs:
            raise ValueError(
                "suitability evidence must match context and fact sources"
            )
        if self.status in {"suitable", "not_suitable"} and (
            not self.evaluated_skin_fact.source_refs
        ):
            raise ValueError(
                "definitive suitability requires auditable Canonical facts"
            )
        if self.status == "suitable" and (
            self.evaluated_skin_fact.state is not FactState.KNOWN
            or self.reason != "canonical_skin_match"
        ):
            raise ValueError(
                "definitive suitability status and reason must match"
            )
        if self.status == "not_suitable":
            expected_state = {
                "canonical_skin_explicit_exclusion": FactState.KNOWN,
                "canonical_skin_not_applicable": FactState.NOT_APPLICABLE,
            }.get(self.reason)
            if self.evaluated_skin_fact.state is not expected_state:
                raise ValueError(
                    "negative suitability requires audited exclusion or "
                    "not-applicable evidence"
                )
        if self.status == "insufficient_evidence":
            if not self.evaluated_skin_fact.source_refs:
                expected_insufficient_reason = "canonical_skin_unaudited"
            elif (
                self.evaluated_skin_fact.state
                is FactState.NOT_APPLICABLE
            ):
                raise ValueError(
                    "audited not-applicable evidence requires a negative "
                    "suitability result"
                )
            else:
                expected_insufficient_reason = {
                    FactState.UNKNOWN: "canonical_skin_unknown",
                    FactState.CONFLICT: "canonical_skin_conflict",
                }.get(
                    self.evaluated_skin_fact.state,
                    "canonical_skin_indeterminate",
                )
            if self.reason != expected_insufficient_reason:
                raise ValueError(
                    "insufficient suitability reason must match "
                    "Canonical fact state"
                )
        return self


def context_precedence(source: SuitabilityContextSource) -> int:
    return _CONTEXT_PRECEDENCE[source]
