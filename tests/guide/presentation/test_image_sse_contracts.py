from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

from app.guide.understanding.image_contracts import (
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ObservationState,
    OcrObservationState,
    VisualObservationState,
)


def _observation() -> ImageIdentityObservation:
    return ImageIdentityObservation(
        image_id="image_" + "a" * 32,
        observation_state=ObservationState.PARTIAL,
        visual_state=VisualObservationState.OBSERVED,
        ocr_state=OcrObservationState.NOT_CONFIGURED,
        identity_state=IdentityState.CONFIRMED,
        confirmed_product_id=53,
        candidate_product_ids=(53, 55, 57),
        visual_confidence=0.99,
        similarity_margin=0.2,
        model_name="approved-openclip",
        weights_sha256="a" * 64,
        preprocessing_version="openclip-preprocess-v1",
        vector_dimension=512,
        index_sha256="b" * 64,
        ocr_brand_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
        ocr_product_name_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
    )


def test_image_observation_event_contains_only_typed_safe_evidence() -> None:
    events = importlib.import_module("app.guide.presentation.sse_events")
    event_type = getattr(events, "ImageObservationEvent")
    data_type = getattr(events, "ImageObservationData")

    event = event_type(
        data=data_type(observation=_observation())
    )

    payload = event.model_dump(mode="json")
    assert payload["event"] == "image_observation"
    assert payload["data"]["observation"]["confirmed_product_id"] == 53
    assert payload["data"]["observation"]["model_name"] == (
        "approved-openclip"
    )
    assert payload["data"]["observation"]["index_sha256"] == "b" * 64
    assert "raw_ocr" not in str(payload)

    with pytest.raises(ValidationError):
        data_type(
            observation=_observation(),
            raw_ocr="untrusted",
        )


@pytest.mark.parametrize(
    ("code", "message"),
    (
        (
            "IMAGE_BUNDLE_UNAVAILABLE",
            "图片引用不可用，请重新上传。",
        ),
        (
            "IMAGE_SINGLE_REQUIRED",
            "当前单图识别一次只支持 1 张图片。",
        ),
        (
            "IMAGE_RETRIEVAL_UNAVAILABLE",
            "图片检索暂时不可用，请稍后重试。",
        ),
        (
            "IMAGE_IDENTITY_UNCONFIRMED",
            "图片信息还不足以确认具体商品，请换一张更清晰的正面图。",
        ),
        (
            "IMAGE_CATEGORY_UNSUPPORTED",
            "当前图片商品不在已开放的防晒或修护精华范围内。",
        ),
    ),
)
def test_image_errors_are_fixed_public_contracts(
    code: str,
    message: str,
) -> None:
    events = importlib.import_module("app.guide.presentation.sse_events")
    error = events.ErrorData(code=code, message=message)

    assert error.model_dump() == {
        "code": code,
        "message": message,
    }
