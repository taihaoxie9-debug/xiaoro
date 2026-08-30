from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from app.guide.adapters.image.safe_image_input import UntrustedImageInput
from app.guide.application.image_bundle_service import (
    ImageBundleService,
    ImageBundleServiceError,
)
from app.guide.application.image_bundle_state import ImageBundlePayload
from app.guide.retrieval.image_contracts import ImageRetrievalRequest
from app.guide.understanding.contracts import ImageObservation
from app.guide.understanding.image_contracts import (
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ImageIdentityTrace,
    VisualObservationState,
)


class ImageIdentityTraceRuntime(Protocol):
    def trace_identity_request(
        self,
        request: ImageRetrievalRequest,
    ) -> tuple[ImageIdentityObservation, ImageIdentityTrace]: ...


_MEDIA_TYPE_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def trace_image_identity_pipeline(
    *,
    image_path: Path,
    output_path: Path,
    image_bundles: ImageBundleService,
    runtime: ImageIdentityTraceRuntime,
) -> dict[str, object]:
    submitted = image_path.read_bytes()
    input_metadata = _input_metadata(
        image_path=image_path,
        content=submitted,
    )
    media_type = _MEDIA_TYPE_BY_SUFFIX.get(image_path.suffix.lower())
    if media_type is None:
        raise ValueError("unsupported image trace suffix")

    try:
        receipt = image_bundles.create(
            session_id="image-trace",
            images=(
                UntrustedImageInput(
                    file_name=image_path.name,
                    declared_media_type=media_type,
                    content=submitted,
                ),
            ),
        )
    except ImageBundleServiceError as error:
        output = _input_failure_payload(
            input_metadata=input_metadata,
            error_code=error.error.code.value,
        )
        _write_trace(output_path, output)
        return output

    bundle, payloads = image_bundles.authorize_bundle_payloads(
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="image-trace",
        owner_token=receipt.owner_token,
    )
    if len(bundle.images) != 1 or len(payloads) != 1:
        raise RuntimeError("image trace requires exactly one payload")
    image = bundle.images[0]
    payload = payloads[0]
    request = ImageRetrievalRequest(
        image_id=payload.image_id,
        content_sha256=payload.content_sha256,
        content=payload.content,
        max_results=10,
    )
    observation, trace = runtime.trace_identity_request(request)
    if (
        observation.image_id != request.image_id
        or trace.observation != observation
    ):
        raise ValueError("identity trace is not bound to the request")

    output = _trace_payload(
        input_metadata=input_metadata,
        submitted=submitted,
        image=image,
        payload=payload,
        trace=trace,
        observation=observation,
    )
    _write_trace(output_path, output)
    return output


def _input_metadata(
    *,
    image_path: Path,
    content: bytes,
) -> dict[str, object]:
    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        width, height = 0, 0
    return {
        "path": image_path.as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "width": width,
        "height": height,
        "byte_size": len(content),
    }


def _trace_payload(
    *,
    input_metadata: dict[str, object],
    submitted: bytes,
    image: ImageObservation,
    payload: ImageBundlePayload,
    trace: ImageIdentityTrace,
    observation: ImageIdentityObservation,
) -> dict[str, object]:
    result = trace.visual.result
    candidates = result.candidates if result is not None else ()
    return {
        "input": input_metadata,
        "validated_input": {
            "sha256": payload.content_sha256,
            "width": image.width,
            "height": image.height,
            "byte_size": payload.byte_size,
            "bytes_unchanged": (
                payload.content == submitted
                and payload.content_sha256
                == input_metadata["sha256"]
            ),
        },
        "visual": {
            "state": trace.visual.state.value,
            "model_name": (
                result.model_name if result is not None else None
            ),
            "weights_sha256": (
                result.weights_sha256 if result is not None else None
            ),
            "preprocessing_version": (
                result.preprocessing_version
                if result is not None
                else None
            ),
            "vector_dimension": (
                result.vector_dimension if result is not None else None
            ),
            "index_sha256": (
                result.index_sha256 if result is not None else None
            ),
        },
        "ocr_observation": trace.ocr_observation.model_dump(mode="json"),
        "ocr_diagnostic": trace.ocr_diagnostic.model_dump(mode="json"),
        "visual_candidates": [
            {
                "rank": candidate.rank,
                "product_id": candidate.product_id,
                "similarity": candidate.similarity,
            }
            for candidate in candidates
        ],
        "fusion": {
            "minimum_similarity": trace.minimum_similarity,
            "minimum_margin": trace.minimum_margin,
            "observed_margin": observation.similarity_margin,
            "ocr_support": _has_ocr_support(trace),
        },
        "identity": {
            "state": observation.identity_state.value,
            "confirmed_product_id": observation.confirmed_product_id,
            "candidate_product_ids": list(
                observation.candidate_product_ids
            ),
        },
        "earliest_failure_layer": _earliest_failure_layer(
            observation
        ),
    }


def _has_ocr_support(trace: ImageIdentityTrace) -> bool:
    return IdentityEvidenceConsistency.CONSISTENT in {
        trace.ocr_observation.brand_consistency,
        trace.ocr_observation.product_name_consistency,
    }


def _earliest_failure_layer(
    observation: ImageIdentityObservation,
) -> str | None:
    if observation.identity_state is IdentityState.CONFIRMED:
        return None
    if observation.identity_state in {
        IdentityState.VISUAL_UNAVAILABLE,
        IdentityState.NO_CANDIDATE,
        IdentityState.LOW_CONFIDENCE,
    }:
        return "visual_retrieval"
    if observation.identity_state is IdentityState.OCR_CONFLICT:
        return "ocr"
    if observation.identity_state is IdentityState.AMBIGUOUS_CANDIDATES:
        return "fusion"
    return "identity_contract"


def _input_failure_payload(
    *,
    input_metadata: dict[str, object],
    error_code: str,
) -> dict[str, object]:
    return {
        "input": input_metadata,
        "validated_input": None,
        "visual": {
            "state": VisualObservationState.UNAVAILABLE.value,
            "model_name": None,
            "weights_sha256": None,
            "preprocessing_version": None,
            "vector_dimension": None,
            "index_sha256": None,
        },
        "ocr_observation": None,
        "ocr_diagnostic": None,
        "visual_candidates": [],
        "fusion": None,
        "identity": {
            "state": None,
            "confirmed_product_id": None,
            "candidate_product_ids": [],
        },
        "input_error_code": error_code,
        "earliest_failure_layer": "input_validation",
    }


def _write_trace(
    output_path: Path,
    output: dict[str, object],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


__all__ = ["trace_image_identity_pipeline"]
