from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from app.guide.retrieval.image_contracts import (
    ApprovedImageModelLock,
    ImageIndexBuildInput,
    ImageIndexBuildNoGo,
    ImageIndexBuildSuccess,
    ImageIndexEntry,
    ImageIndexManifest,
    ImageIndexRuntimeLock,
    ImageIndexSource,
    ImageRetrievalCandidate,
    ImageRetrievalRequest,
    ImageRetrievalResult,
    UnapprovedImageModel,
)
from app.guide.retrieval.ports import ImageRetrievalPort


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _entry(product_id: int) -> ImageIndexEntry:
    return ImageIndexEntry(
        product_id=product_id,
        source_path=f"app/static/images/products/{product_id}.png",
        source_bytes=100 + product_id,
        source_sha256=SHA_A,
        vector_path=f"vectors/{product_id}.bin",
        vector_sha256=SHA_B,
    )


def _manifest(
    *entries: ImageIndexEntry,
) -> ImageIndexManifest:
    return ImageIndexManifest(
        source_manifest_path=(
            "data/canonical/seed_product_images_v1_manifest.json"
        ),
        source_manifest_sha256=SHA_A,
        source_products_path=(
            "data/canonical/seed_product_images_v1.jsonl"
        ),
        source_products_sha256=SHA_B,
        model_name="approved-model",
        weights_sha256=SHA_C,
        preprocessing_version="preprocess-v1",
        vector_dimension=4,
        entries=entries,
        index_path="index.bin",
        index_sha256=SHA_D,
        manifest_sha256=SHA_E,
    )


def test_image_retrieval_port_has_typed_request_and_result() -> None:
    signature = inspect.signature(ImageRetrievalPort.retrieve)
    hints = get_type_hints(ImageRetrievalPort.retrieve)

    assert tuple(signature.parameters) == ("self", "request")
    assert hints["request"] is ImageRetrievalRequest
    assert hints["return"] is ImageRetrievalResult


def test_retrieval_contracts_are_strict_and_stably_ordered() -> None:
    content = b"decoded-and-validated-image"
    request = ImageRetrievalRequest(
        image_id="image-opaque-id",
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        max_results=3,
    )
    result = ImageRetrievalResult(
        candidates=(
            ImageRetrievalCandidate(
                rank=1,
                product_id=2,
                similarity=0.9,
            ),
            ImageRetrievalCandidate(
                rank=2,
                product_id=10,
                similarity=0.9,
            ),
        ),
        model_name="approved-model",
        weights_sha256=SHA_B,
        preprocessing_version="preprocess-v1",
        vector_dimension=4,
        index_sha256=SHA_C,
    )

    assert request.max_results == 3
    assert [item.product_id for item in result.candidates] == [2, 10]

    with pytest.raises(ValidationError):
        invalid_content = b"image"
        ImageRetrievalRequest(
            image_id="image-opaque-id",
            content_sha256=hashlib.sha256(invalid_content).hexdigest(),
            content=invalid_content,
            max_results="3",
        )

    with pytest.raises(ValidationError, match="candidate order"):
        ImageRetrievalResult(
            candidates=(
                ImageRetrievalCandidate(
                    rank=1,
                    product_id=10,
                    similarity=0.9,
                ),
                ImageRetrievalCandidate(
                    rank=2,
                    product_id=2,
                    similarity=0.9,
                ),
            ),
            model_name="approved-model",
            weights_sha256=SHA_B,
            preprocessing_version="preprocess-v1",
            vector_dimension=4,
            index_sha256=SHA_C,
        )


def test_retrieval_request_rejects_content_sha256_mismatch() -> None:
    content = b"decoded-and-validated-image"
    actual_sha256 = hashlib.sha256(content).hexdigest()
    mismatched_sha256 = "0" * 64
    assert mismatched_sha256 != actual_sha256

    with pytest.raises(
        ValidationError,
        match="content_sha256 must match content",
    ):
        ImageRetrievalRequest(
            image_id="image-opaque-id",
            content_sha256=mismatched_sha256,
            content=content,
            max_results=3,
        )


def test_model_approval_and_build_results_are_discriminated() -> None:
    approved = ApprovedImageModelLock(
        approval_id="decision-2026-08-08",
        model_name="approved-model",
        weights_sha256=SHA_A,
        preprocessing_version="preprocess-v1",
        vector_dimension=4,
    )
    unapproved = UnapprovedImageModel(reason="awaiting user approval")
    build_input = ImageIndexBuildInput(
        source_manifest_path=Path("/repo/data/canonical/images_manifest.json"),
        source_products_path=Path("/repo/data/canonical/images.jsonl"),
        source_root=Path("/repo"),
        output_dir=Path("/repo/data/image-index"),
        model=unapproved,
    )
    no_go = ImageIndexBuildNoGo(
        code="model_not_approved",
        detail="image model is not approved",
        source_count=103,
    )
    success = ImageIndexBuildSuccess(
        output_dir=Path("/repo/data/image-index"),
        manifest_path=Path("/repo/data/image-index/manifest.json"),
        index_path=Path("/repo/data/image-index/index.bin"),
        manifest_sha256=SHA_B,
        index_sha256=SHA_C,
        product_ids=(2, 10),
    )

    assert approved.status == "approved"
    assert build_input.model.status == "unapproved"
    assert no_go.status == "no_go"
    assert success.status == "built"


def test_manifest_schema_records_all_reproducibility_fields() -> None:
    expected = {
        "schema_version",
        "source_manifest_path",
        "source_manifest_sha256",
        "source_products_path",
        "source_products_sha256",
        "model_name",
        "weights_sha256",
        "preprocessing_version",
        "vector_dimension",
        "entries",
        "index_path",
        "index_sha256",
        "manifest_sha256",
    }

    assert set(ImageIndexManifest.model_fields) == expected
    assert set(ImageIndexEntry.model_fields) == {
        "product_id",
        "source_path",
        "source_bytes",
        "source_sha256",
        "vector_path",
        "vector_sha256",
    }
    assert set(ImageIndexSource.model_fields) == {
        "product_id",
        "source_path",
        "source_bytes",
        "source_sha256",
        "media_type",
    }
    assert set(ImageIndexRuntimeLock.model_fields) == {
        "manifest_sha256",
        "model_name",
        "weights_sha256",
        "preprocessing_version",
        "vector_dimension",
        "index_sha256",
    }


def test_manifest_requires_numeric_order_and_unique_paths() -> None:
    manifest = _manifest(_entry(2), _entry(10))

    assert [item.product_id for item in manifest.entries] == [2, 10]

    with pytest.raises(ValidationError, match="numeric product_id order"):
        _manifest(_entry(10), _entry(2))

    with pytest.raises(ValidationError, match="duplicate source_path"):
        _manifest(
            _entry(2),
            _entry(10).model_copy(
                update={"source_path": _entry(2).source_path}
            ),
        )

    with pytest.raises(ValidationError, match="relative"):
        _manifest(
            _entry(2).model_copy(
                update={"vector_path": "/absolute/vector.bin"}
            )
        )
