from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]

IMAGE_INDEX_SCHEMA_VERSION = "image-index-manifest-v1"


class _StrictFrozenContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


def _require_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise ValueError("artifact path must be a normalized relative path")
    return value


class ImageRetrievalRequest(_StrictFrozenContract):
    image_id: NonEmptyString
    content_sha256: Sha256
    content: bytes = Field(min_length=1)
    max_results: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def validate_content_sha256(self) -> ImageRetrievalRequest:
        if hashlib.sha256(self.content).hexdigest() != self.content_sha256:
            raise ValueError("content_sha256 must match content")
        return self


class ImageRetrievalCandidate(_StrictFrozenContract):
    rank: int = Field(ge=1)
    product_id: int = Field(ge=1)
    similarity: float = Field(ge=-1.0, le=1.0)


class ImageRetrievalResult(_StrictFrozenContract):
    candidates: tuple[ImageRetrievalCandidate, ...]
    model_name: NonEmptyString
    weights_sha256: Sha256
    preprocessing_version: NonEmptyString
    vector_dimension: int = Field(gt=0)
    index_sha256: Sha256

    @model_validator(mode="after")
    def validate_candidate_order(self) -> ImageRetrievalResult:
        expected_ranks = tuple(range(1, len(self.candidates) + 1))
        actual_ranks = tuple(item.rank for item in self.candidates)
        expected_candidates = tuple(
            sorted(
                self.candidates,
                key=lambda item: (-item.similarity, item.product_id),
            )
        )
        product_ids = tuple(item.product_id for item in self.candidates)
        if (
            actual_ranks != expected_ranks
            or self.candidates != expected_candidates
            or len(product_ids) != len(set(product_ids))
        ):
            raise ValueError(
                "candidate order must be rank-contiguous, similarity "
                "descending, and numeric product_id ascending on ties"
            )
        return self


class UnapprovedImageModel(_StrictFrozenContract):
    status: Literal["unapproved"] = "unapproved"
    reason: NonEmptyString


class ApprovedImageModelLock(_StrictFrozenContract):
    status: Literal["approved"] = "approved"
    approval_id: NonEmptyString
    model_name: NonEmptyString
    weights_sha256: Sha256
    preprocessing_version: NonEmptyString
    vector_dimension: int = Field(gt=0)


ImageModelApproval = Annotated[
    ApprovedImageModelLock | UnapprovedImageModel,
    Field(discriminator="status"),
]


class ImageIndexSource(_StrictFrozenContract):
    product_id: int = Field(ge=1)
    source_path: NonEmptyString
    source_bytes: int = Field(gt=0)
    source_sha256: Sha256
    media_type: Literal["image/jpeg", "image/png", "image/webp"]

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return _require_relative_path(value)


class ImageSourcePreflightReport(_StrictFrozenContract):
    source_manifest_path: NonEmptyString
    source_manifest_sha256: Sha256
    source_products_path: NonEmptyString
    source_products_sha256: Sha256
    sources: tuple[ImageIndexSource, ...] = Field(min_length=1)

    @field_validator("source_manifest_path", "source_products_path")
    @classmethod
    def validate_source_metadata_path(cls, value: str) -> str:
        return _require_relative_path(value)

    @model_validator(mode="after")
    def validate_sources(self) -> ImageSourcePreflightReport:
        product_ids = tuple(item.product_id for item in self.sources)
        if product_ids != tuple(sorted(product_ids)):
            raise ValueError(
                "sources must use stable numeric product_id order"
            )
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("duplicate product_id in image sources")
        source_paths = tuple(item.source_path for item in self.sources)
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("duplicate source path in image sources")
        return self


class ImageIndexEntry(_StrictFrozenContract):
    product_id: int = Field(ge=1)
    source_path: NonEmptyString
    source_bytes: int = Field(gt=0)
    source_sha256: Sha256
    vector_path: NonEmptyString
    vector_sha256: Sha256

    @field_validator("source_path", "vector_path")
    @classmethod
    def validate_artifact_path(cls, value: str) -> str:
        return _require_relative_path(value)


class ImageIndexManifest(_StrictFrozenContract):
    schema_version: Literal[IMAGE_INDEX_SCHEMA_VERSION] = (
        IMAGE_INDEX_SCHEMA_VERSION
    )
    source_manifest_path: NonEmptyString
    source_manifest_sha256: Sha256
    source_products_path: NonEmptyString
    source_products_sha256: Sha256
    model_name: NonEmptyString
    weights_sha256: Sha256
    preprocessing_version: NonEmptyString
    vector_dimension: int = Field(gt=0)
    entries: tuple[ImageIndexEntry, ...] = Field(min_length=1)
    index_path: NonEmptyString
    index_sha256: Sha256
    manifest_sha256: Sha256

    @field_validator(
        "source_manifest_path",
        "source_products_path",
        "index_path",
    )
    @classmethod
    def validate_manifest_path(cls, value: str) -> str:
        return _require_relative_path(value)

    @model_validator(mode="after")
    def validate_entries(self) -> ImageIndexManifest:
        product_ids = tuple(item.product_id for item in self.entries)
        if product_ids != tuple(sorted(product_ids)):
            raise ValueError(
                "entries must use stable numeric product_id order"
            )
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("duplicate product_id in image index manifest")

        source_paths = tuple(item.source_path for item in self.entries)
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("duplicate source_path in image index manifest")

        vector_paths = tuple(item.vector_path for item in self.entries)
        if len(vector_paths) != len(set(vector_paths)):
            raise ValueError("duplicate vector_path in image index manifest")

        for entry in self.entries:
            _require_relative_path(entry.source_path)
            _require_relative_path(entry.vector_path)
        return self


class ImageIndexBuildInput(_StrictFrozenContract):
    source_manifest_path: Path
    source_products_path: Path
    source_root: Path
    output_dir: Path
    model: ImageModelApproval | None = None

    @field_validator(
        "source_manifest_path",
        "source_products_path",
        "source_root",
        "output_dir",
    )
    @classmethod
    def require_absolute_paths(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("image index build paths must be absolute")
        return value


class ImageIndexBuildNoGo(_StrictFrozenContract):
    status: Literal["no_go"] = "no_go"
    code: NonEmptyString
    detail: NonEmptyString
    source_count: int = Field(ge=0)


class ImageIndexBuildSuccess(_StrictFrozenContract):
    status: Literal["built"] = "built"
    output_dir: Path
    manifest_path: Path
    index_path: Path
    manifest_sha256: Sha256
    index_sha256: Sha256
    product_ids: tuple[int, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_product_ids(self) -> ImageIndexBuildSuccess:
        if self.product_ids != tuple(sorted(set(self.product_ids))):
            raise ValueError(
                "product_ids must be unique numeric ascending values"
            )
        if any(product_id < 1 for product_id in self.product_ids):
            raise ValueError("product_ids must be positive")
        return self


ImageIndexBuildResult = ImageIndexBuildNoGo | ImageIndexBuildSuccess


class ImageIndexRuntimeLock(_StrictFrozenContract):
    manifest_sha256: Sha256
    model_name: NonEmptyString
    weights_sha256: Sha256
    preprocessing_version: NonEmptyString
    vector_dimension: int = Field(gt=0)
    index_sha256: Sha256
