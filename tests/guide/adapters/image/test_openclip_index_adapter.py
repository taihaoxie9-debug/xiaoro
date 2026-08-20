from __future__ import annotations

import importlib.util
from dataclasses import fields, replace
from pathlib import Path
from typing import cast

import app.guide.adapters.image.openclip_index as openclip_index
import app.guide.adapters.image.openclip_adapter as openclip_adapter
import pytest


def test_openclip_index_adapter_module_exists() -> None:
    assert (
        importlib.util.find_spec(
            "app.guide.adapters.image.openclip_index"
        )
        is not None
    )


def test_openclip_index_adapter_exports_task11_api() -> None:
    assert {
        "ImageIndexAcceptanceReport",
        "LocalNumpyImageIndex",
        "OpenClipImageEncoder",
        "OpenClipModelError",
        "OpenClipModelSpec",
        "OpenClipNumpyArtifactBuilder",
        "controlled_reencode",
        "verify_image_index_acceptance",
    }.issubset(vars(openclip_index))


def test_openclip_model_contract_is_fully_locked_and_testable() -> None:
    assert openclip_adapter.LOCKED_MODEL_NAME == "ViT-B-32"
    assert (
        openclip_adapter.LOCKED_PRETRAINED_TAG
        == "laion2b_s34b_b79k"
    )
    assert openclip_adapter.LOCKED_REVISION == (
        "1a25a446712ba5ee05982a381eed697ef9b435cf"
    )
    assert openclip_adapter.LOCKED_WEIGHT_BYTES == 605143316
    assert openclip_adapter.LOCKED_WEIGHT_SHA256 == (
        "ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6"
    )
    assert openclip_adapter.LOCKED_VECTOR_DIMENSION == 512
    assert openclip_adapter.LOCKED_PREPROCESS_VERSION.startswith(
        "openclip-3.3.0|ViT-B-32|"
    )
    assert {field.name for field in fields(openclip_adapter.OpenClipModelSpec)} == {
        "weight_path",
        "device",
        "model_name",
        "pretrained_tag",
        "revision",
        "preprocessing_version",
        "vector_dimension",
    }
    assert hasattr(
        openclip_adapter.OpenClipModelSpec,
        "validate_static_contract",
    )
    assert hasattr(
        openclip_adapter.OpenClipImageEncoder,
        "model_lock",
    )
    assert hasattr(
        openclip_adapter.OpenClipImageEncoder,
        "encode_paths",
    )
    assert hasattr(
        openclip_adapter.OpenClipImageEncoder,
        "encode_bytes",
    )


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"model_name": "ViT-B-16"}, "model_name_drift"),
        ({"pretrained_tag": "other"}, "pretrained_tag_drift"),
        ({"revision": "0" * 40}, "model_revision_drift"),
        (
            {"preprocessing_version": "preprocess-v2"},
            "preprocessing_version_drift",
        ),
        ({"vector_dimension": 768}, "vector_dimension_drift"),
        ({"device": "auto"}, "device_not_allowed"),
    ],
)
def test_model_spec_rejects_every_locked_identity_drift(
    tmp_path: Path,
    updates: dict[str, object],
    code: str,
) -> None:
    spec = replace(
        openclip_adapter.OpenClipModelSpec(
            weight_path=tmp_path / "open_clip_model.safetensors",
            device="cpu",
        ),
        **updates,
    )

    with pytest.raises(openclip_adapter.OpenClipModelError) as caught:
        spec.validate_static_contract()

    assert caught.value.code == code


def test_cpu_is_an_explicit_valid_device_without_auto_fallback(
    tmp_path: Path,
) -> None:
    spec = openclip_adapter.OpenClipModelSpec(
        weight_path=tmp_path / "open_clip_model.safetensors",
        device=cast("object", "cpu"),
    )

    spec.validate_static_contract()

    assert spec.device == "cpu"


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("open_clip_model.safetensors", "weight_size_drift"),
        ("open_clip_pytorch_model.bin", "weight_format_prohibited"),
    ],
)
def test_encoder_rejects_incomplete_or_prohibited_weight_before_load(
    tmp_path: Path,
    name: str,
    code: str,
) -> None:
    weight_path = tmp_path / name
    weight_path.write_bytes(b"incomplete-checkpoint")
    spec = openclip_adapter.OpenClipModelSpec(
        weight_path=weight_path,
        device="cpu",
    )

    with pytest.raises(openclip_adapter.OpenClipModelError) as caught:
        openclip_adapter.OpenClipImageEncoder(spec)

    assert caught.value.code == code
