from __future__ import annotations

from enum import Enum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.guide.retrieval.image_contracts import ImageRetrievalResult
from app.guide.understanding.contracts import ContentSha256, OpaqueImageId


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class _StrictFrozenContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class ObservationState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class VisualObservationState(str, Enum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"


class OcrObservationState(str, Enum):
    NOT_RUN = "not_run"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    OBSERVED = "observed"


class IdentityEvidenceConsistency(str, Enum):
    NOT_CHECKED = "not_checked"
    CONSISTENT = "consistent"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


class IdentityState(str, Enum):
    CONFIRMED = "confirmed"
    VISUAL_UNAVAILABLE = "visual_unavailable"
    NO_CANDIDATE = "no_candidate"
    INSUFFICIENT_CANDIDATES = "insufficient_candidates"
    LOW_CONFIDENCE = "low_confidence"
    AMBIGUOUS_CANDIDATES = "ambiguous_candidates"
    NON_CANONICAL_CANDIDATE = "non_canonical_candidate"
    CANONICAL_IDENTITY_UNAVAILABLE = "canonical_identity_unavailable"
    OCR_CONFLICT = "ocr_conflict"


class IdentityBindingPolicy(_StrictFrozenContract):
    minimum_similarity: float = Field(ge=-1.0, le=1.0)
    minimum_margin: float = Field(gt=0.0, le=2.0)


class CanonicalIdentity(_StrictFrozenContract):
    product_id: int = Field(ge=1)
    brand: NonEmptyString | None = None
    product_name: NonEmptyString | None = None

    @model_validator(mode="after")
    def require_authoritative_identity_field(self) -> Self:
        if self.brand is None and self.product_name is None:
            raise ValueError(
                "canonical identity requires brand or product_name"
            )
        return self


class VisualCandidateObservation(_StrictFrozenContract):
    state: VisualObservationState
    result: ImageRetrievalResult | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.state is VisualObservationState.OBSERVED:
            if self.result is None:
                raise ValueError(
                    "observed visual state requires retrieval result"
                )
            return self
        if self.result is not None:
            raise ValueError(
                "unavailable visual state forbids retrieval result"
            )
        return self


class OcrIdentityObservation(_StrictFrozenContract):
    state: OcrObservationState
    brand_consistency: IdentityEvidenceConsistency
    product_name_consistency: IdentityEvidenceConsistency

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        consistencies = (
            self.brand_consistency,
            self.product_name_consistency,
        )
        if self.state is OcrObservationState.OBSERVED:
            if all(
                item is IdentityEvidenceConsistency.NOT_CHECKED
                for item in consistencies
            ):
                raise ValueError(
                    "observed OCR requires checked identity evidence"
                )
            return self
        if any(
            item is not IdentityEvidenceConsistency.NOT_CHECKED
            for item in consistencies
        ):
            raise ValueError(
                "OCR without an observation forbids consistency claims"
            )
        return self


class ImageIdentityObservation(_StrictFrozenContract):
    image_id: OpaqueImageId
    observation_state: ObservationState
    visual_state: VisualObservationState
    ocr_state: OcrObservationState
    identity_state: IdentityState
    confirmed_product_id: int | None = Field(default=None, ge=1)
    candidate_product_ids: tuple[int, ...]
    visual_confidence: float | None = Field(default=None, ge=-1.0, le=1.0)
    similarity_margin: float | None = Field(default=None, ge=0.0, le=2.0)
    model_name: NonEmptyString | None = None
    weights_sha256: ContentSha256 | None = None
    preprocessing_version: NonEmptyString | None = None
    vector_dimension: int | None = Field(default=None, gt=0)
    index_sha256: ContentSha256 | None = None
    ocr_brand_consistency: IdentityEvidenceConsistency
    ocr_product_name_consistency: IdentityEvidenceConsistency

    @model_validator(mode="after")
    def validate_safe_identity_state(self) -> Self:
        if (
            any(product_id < 1 for product_id in self.candidate_product_ids)
            or len(self.candidate_product_ids)
            != len(set(self.candidate_product_ids))
        ):
            raise ValueError(
                "candidate_product_ids must be unique positive values"
            )

        candidate_count = len(self.candidate_product_ids)
        if (
            self.identity_state is IdentityState.NO_CANDIDATE
            and candidate_count != 0
        ):
            raise ValueError(
                "NO_CANDIDATE evidence shape requires no candidates"
            )
        if (
            self.identity_state is IdentityState.INSUFFICIENT_CANDIDATES
            and candidate_count != 1
        ):
            raise ValueError(
                "INSUFFICIENT_CANDIDATES evidence shape requires exactly "
                "one candidate"
            )
        if (
            self.identity_state is IdentityState.AMBIGUOUS_CANDIDATES
            and candidate_count < 2
        ):
            raise ValueError(
                "AMBIGUOUS_CANDIDATES evidence shape requires multiple "
                "candidates"
            )
        if (
            self.identity_state is IdentityState.OCR_CONFLICT
            and candidate_count < 2
        ):
            raise ValueError(
                "identity_state OCR_CONFLICT evidence shape requires "
                "multiple candidates"
            )
        if self.identity_state in {
            IdentityState.LOW_CONFIDENCE,
            IdentityState.NON_CANONICAL_CANDIDATE,
            IdentityState.CANONICAL_IDENTITY_UNAVAILABLE,
        } and candidate_count == 0:
            raise ValueError(
                f"{self.identity_state.name} evidence shape requires a "
                "candidate"
            )
        pre_ocr_states = {
            IdentityState.NO_CANDIDATE,
            IdentityState.INSUFFICIENT_CANDIDATES,
            IdentityState.LOW_CONFIDENCE,
            IdentityState.AMBIGUOUS_CANDIDATES,
            IdentityState.NON_CANONICAL_CANDIDATE,
            IdentityState.CANONICAL_IDENTITY_UNAVAILABLE,
        }
        if (
            self.identity_state in pre_ocr_states
            and self.ocr_state is not OcrObservationState.NOT_RUN
        ):
            raise ValueError(
                "pre-OCR identity states require OCR NOT_RUN"
            )

        is_confirmed = self.identity_state is IdentityState.CONFIRMED
        if is_confirmed:
            if (
                candidate_count < 2
                or self.confirmed_product_id is None
                or self.confirmed_product_id
                != self.candidate_product_ids[0]
            ):
                raise ValueError(
                    "confirmed identity requires multiple candidates and "
                    "the top candidate ID"
                )
        elif self.confirmed_product_id is not None:
            raise ValueError(
                "unconfirmed identity forbids confirmed_product_id"
            )

        if self.candidate_product_ids:
            if self.visual_confidence is None:
                raise ValueError(
                    "visual candidates require visual_confidence"
                )
        elif self.visual_confidence is not None:
            raise ValueError(
                "visual_confidence requires visual candidates"
            )

        if candidate_count >= 2:
            if self.similarity_margin is None:
                raise ValueError(
                    "multiple candidates require similarity_margin"
                )
        elif self.similarity_margin is not None:
            raise ValueError(
                "similarity_margin requires multiple candidates"
            )

        visual_metadata = (
            self.model_name,
            self.weights_sha256,
            self.preprocessing_version,
            self.vector_dimension,
            self.index_sha256,
        )
        if self.visual_state is VisualObservationState.OBSERVED:
            if any(value is None for value in visual_metadata):
                raise ValueError(
                    "observed visual state requires model and index metadata"
                )
        else:
            if (
                self.observation_state is not ObservationState.UNAVAILABLE
                or self.candidate_product_ids
                or any(value is not None for value in visual_metadata)
            ):
                raise ValueError(
                    "unavailable visual state forbids visual evidence"
                )
        if (
            self.identity_state is IdentityState.VISUAL_UNAVAILABLE
        ) != (
            self.visual_state is VisualObservationState.UNAVAILABLE
        ):
            raise ValueError(
                "identity_state must match visual availability"
            )

        ocr_observation = OcrIdentityObservation(
            state=self.ocr_state,
            brand_consistency=self.ocr_brand_consistency,
            product_name_consistency=(
                self.ocr_product_name_consistency
            ),
        )
        expected_observation_state = (
            ObservationState.UNAVAILABLE
            if self.visual_state is VisualObservationState.UNAVAILABLE
            else (
                ObservationState.COMPLETE
                if self.ocr_state is OcrObservationState.OBSERVED
                else ObservationState.PARTIAL
            )
        )
        if self.observation_state is not expected_observation_state:
            raise ValueError(
                "observation_state must match visual and OCR states"
            )

        has_ocr_conflict = (
            ocr_observation.state is OcrObservationState.OBSERVED
            and IdentityEvidenceConsistency.CONFLICT
            in (
                ocr_observation.brand_consistency,
                ocr_observation.product_name_consistency,
            )
        )
        if (
            self.identity_state is IdentityState.OCR_CONFLICT
        ) != has_ocr_conflict:
            raise ValueError(
                "identity_state must be OCR_CONFLICT exactly when an "
                "OCR conflict exists"
            )
        return self
