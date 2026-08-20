from __future__ import annotations

import hashlib
import importlib

import pytest

from app.guide.adapters.image.index_runtime import (
    ImageRetrievalUnavailableError,
)
from app.guide.adapters.image.openclip_adapter import OpenClipModelError
from app.guide.retrieval.image_contracts import (
    ImageRetrievalCandidate,
    ImageRetrievalRequest,
    ImageRetrievalResult,
)
from app.guide.understanding.image_contracts import VisualObservationState


def _request() -> ImageRetrievalRequest:
    content = b"validated-image"
    return ImageRetrievalRequest(
        image_id="image_" + "a" * 32,
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        max_results=3,
    )


def _result() -> ImageRetrievalResult:
    return ImageRetrievalResult(
        candidates=(
            ImageRetrievalCandidate(
                rank=1,
                product_id=53,
                similarity=0.99,
            ),
            ImageRetrievalCandidate(
                rank=2,
                product_id=55,
                similarity=0.7,
            ),
        ),
        model_name="approved-openclip",
        weights_sha256="a" * 64,
        preprocessing_version="openclip-preprocess-v1",
        vector_dimension=512,
        index_sha256="b" * 64,
    )


class FakeRetrieval:
    def __init__(self, value) -> None:
        self.value = value

    def retrieve(self, request):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _adapter_type():
    module = importlib.import_module(
        "app.guide.adapters.image.visual_observation"
    )
    return getattr(module, "ImageRetrievalVisualObservationAdapter")


def test_visual_observation_wraps_real_retrieval_result() -> None:
    result = _result()
    adapter = _adapter_type()(retrieval=FakeRetrieval(result))

    observation = adapter.observe(_request())

    assert observation.state is VisualObservationState.OBSERVED
    assert observation.result == result


@pytest.mark.parametrize(
    "error",
    (
        ImageRetrievalUnavailableError(("index_integrity_drift",)),
        OpenClipModelError("model_inference_failed"),
    ),
)
def test_visual_observation_fails_closed_on_model_or_index_error(
    error: Exception,
) -> None:
    adapter = _adapter_type()(retrieval=FakeRetrieval(error))

    observation = adapter.observe(_request())

    assert observation.state is VisualObservationState.UNAVAILABLE
    assert observation.result is None
