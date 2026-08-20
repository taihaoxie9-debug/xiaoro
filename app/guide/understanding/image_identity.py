from __future__ import annotations

from math import isclose

from app.guide.retrieval.image_contracts import (
    ImageRetrievalRequest,
    ImageRetrievalResult,
)
from app.guide.understanding.image_contracts import (
    IdentityBindingPolicy,
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ObservationState,
    OcrIdentityObservation,
    OcrObservationState,
    VisualCandidateObservation,
    VisualObservationState,
)
from app.guide.understanding.ports import (
    CanonicalIdentityCatalogPort,
    OcrObservationPort,
    VisualObservationPort,
)


_MARGIN_ABSOLUTE_TOLERANCE = 1e-12


class ImageIdentityObserver:
    def __init__(
        self,
        *,
        visual_observation: VisualObservationPort,
        ocr_observation: OcrObservationPort,
        canonical_identities: CanonicalIdentityCatalogPort,
        policy: IdentityBindingPolicy,
    ) -> None:
        self._visual_observation = visual_observation
        self._ocr_observation = ocr_observation
        self._canonical_identities = canonical_identities
        self._policy = policy

    def observe(
        self,
        request: ImageRetrievalRequest,
    ) -> ImageIdentityObservation:
        visual = self._visual_observation.observe(request)
        if visual.state is VisualObservationState.UNAVAILABLE:
            return _unavailable_observation(request.image_id)

        result = visual.result
        if result is None:
            raise RuntimeError(
                "observed visual state is missing retrieval result"
            )
        candidates = result.candidates
        candidate_ids = tuple(
            candidate.product_id for candidate in candidates
        )
        confidence = candidates[0].similarity if candidates else None
        margin = (
            candidates[0].similarity - candidates[1].similarity
            if len(candidates) >= 2
            else None
        )

        if not candidates:
            return _observed_without_ocr(
                image_id=request.image_id,
                result=result,
                identity_state=IdentityState.NO_CANDIDATE,
                candidate_ids=candidate_ids,
                confidence=confidence,
                margin=margin,
            )

        canonical_product_ids = self._canonical_identities.product_ids
        if any(
            product_id not in canonical_product_ids
            for product_id in candidate_ids
        ):
            return _observed_without_ocr(
                image_id=request.image_id,
                result=result,
                identity_state=IdentityState.NON_CANONICAL_CANDIDATE,
                candidate_ids=candidate_ids,
                confidence=confidence,
                margin=margin,
            )

        if candidates[0].similarity < self._policy.minimum_similarity:
            return _observed_without_ocr(
                image_id=request.image_id,
                result=result,
                identity_state=IdentityState.LOW_CONFIDENCE,
                candidate_ids=candidate_ids,
                confidence=confidence,
                margin=margin,
            )

        if margin is not None and not _meets_minimum_margin(
            margin,
            self._policy.minimum_margin,
        ):
            return _observed_without_ocr(
                image_id=request.image_id,
                result=result,
                identity_state=IdentityState.AMBIGUOUS_CANDIDATES,
                candidate_ids=candidate_ids,
                confidence=confidence,
                margin=margin,
            )

        top_product_id = candidates[0].product_id
        canonical_identity = self._canonical_identities.get_identity(
            top_product_id
        )
        if canonical_identity is None:
            return _observed_without_ocr(
                image_id=request.image_id,
                result=result,
                identity_state=(
                    IdentityState.CANONICAL_IDENTITY_UNAVAILABLE
                ),
                candidate_ids=candidate_ids,
                confidence=confidence,
                margin=margin,
            )

        if margin is None:
            return _observed_without_ocr(
                image_id=request.image_id,
                result=result,
                identity_state=IdentityState.INSUFFICIENT_CANDIDATES,
                candidate_ids=candidate_ids,
                confidence=confidence,
                margin=margin,
            )

        ocr = self._ocr_observation.observe(
            request,
            canonical_identity,
        )
        identity_state = (
            IdentityState.OCR_CONFLICT
            if _has_ocr_conflict(ocr)
            else IdentityState.CONFIRMED
        )
        return _observed_with_ocr(
            image_id=request.image_id,
            result=result,
            ocr=ocr,
            identity_state=identity_state,
            confirmed_product_id=(
                top_product_id
                if identity_state is IdentityState.CONFIRMED
                else None
            ),
            candidate_ids=candidate_ids,
            confidence=confidence,
            margin=margin,
        )


def _meets_minimum_margin(margin: float, minimum_margin: float) -> bool:
    return margin >= minimum_margin or isclose(
        margin,
        minimum_margin,
        rel_tol=0.0,
        abs_tol=_MARGIN_ABSOLUTE_TOLERANCE,
    )


def _has_ocr_conflict(observation: OcrIdentityObservation) -> bool:
    return (
        observation.state is OcrObservationState.OBSERVED
        and IdentityEvidenceConsistency.CONFLICT
        in (
            observation.brand_consistency,
            observation.product_name_consistency,
        )
    )


def _unavailable_observation(image_id: str) -> ImageIdentityObservation:
    return ImageIdentityObservation(
        image_id=image_id,
        observation_state=ObservationState.UNAVAILABLE,
        visual_state=VisualObservationState.UNAVAILABLE,
        ocr_state=OcrObservationState.NOT_RUN,
        identity_state=IdentityState.VISUAL_UNAVAILABLE,
        confirmed_product_id=None,
        candidate_product_ids=(),
        visual_confidence=None,
        similarity_margin=None,
        model_name=None,
        weights_sha256=None,
        preprocessing_version=None,
        vector_dimension=None,
        index_sha256=None,
        ocr_brand_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
        ocr_product_name_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
    )


def _observed_without_ocr(
    *,
    image_id: str,
    result: ImageRetrievalResult,
    identity_state: IdentityState,
    candidate_ids: tuple[int, ...],
    confidence: float | None,
    margin: float | None,
) -> ImageIdentityObservation:
    return _observed_with_ocr(
        image_id=image_id,
        result=result,
        ocr=OcrIdentityObservation(
            state=OcrObservationState.NOT_RUN,
            brand_consistency=(
                IdentityEvidenceConsistency.NOT_CHECKED
            ),
            product_name_consistency=(
                IdentityEvidenceConsistency.NOT_CHECKED
            ),
        ),
        identity_state=identity_state,
        confirmed_product_id=None,
        candidate_ids=candidate_ids,
        confidence=confidence,
        margin=margin,
    )


def _observed_with_ocr(
    *,
    image_id: str,
    result: ImageRetrievalResult,
    ocr: OcrIdentityObservation,
    identity_state: IdentityState,
    confirmed_product_id: int | None,
    candidate_ids: tuple[int, ...],
    confidence: float | None,
    margin: float | None,
) -> ImageIdentityObservation:
    return ImageIdentityObservation(
        image_id=image_id,
        observation_state=(
            ObservationState.COMPLETE
            if ocr.state is OcrObservationState.OBSERVED
            else ObservationState.PARTIAL
        ),
        visual_state=VisualObservationState.OBSERVED,
        ocr_state=ocr.state,
        identity_state=identity_state,
        confirmed_product_id=confirmed_product_id,
        candidate_product_ids=candidate_ids,
        visual_confidence=confidence,
        similarity_margin=margin,
        model_name=result.model_name,
        weights_sha256=result.weights_sha256,
        preprocessing_version=result.preprocessing_version,
        vector_dimension=result.vector_dimension,
        index_sha256=result.index_sha256,
        ocr_brand_consistency=ocr.brand_consistency,
        ocr_product_name_consistency=(
            ocr.product_name_consistency
        ),
    )
