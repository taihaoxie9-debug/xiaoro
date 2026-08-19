from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.understanding.contracts import (
    ContentSha256,
    ImageBundle,
    OpaqueImageId,
)


MAX_STORED_IMAGE_BYTES = 8 * 1024 * 1024
MAX_STORED_BUNDLE_BYTES = 20 * 1024 * 1024


class ImageBundlePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    image_id: OpaqueImageId
    ordinal: int = Field(ge=1, le=4)
    content_sha256: ContentSha256
    byte_size: int = Field(gt=0, le=MAX_STORED_IMAGE_BYTES)
    content: bytes = Field(min_length=1, max_length=MAX_STORED_IMAGE_BYTES)

    @model_validator(mode="after")
    def validate_content(self) -> ImageBundlePayload:
        if len(self.content) != self.byte_size:
            raise ValueError("payload byte_size must match content")
        if hashlib.sha256(self.content).hexdigest() != self.content_sha256:
            raise ValueError("payload SHA-256 must match content")
        return self


class ImageBundleStateConflict(RuntimeError):
    pass


class ImageBundleCapacityExceeded(RuntimeError):
    pass


class ImageBundleStateCorrupt(RuntimeError):
    pass


class ImageBundleStatePort(Protocol):
    def create(
        self,
        bundle: ImageBundle,
        *,
        payloads: Sequence[ImageBundlePayload],
    ) -> ImageBundle: ...

    def load(self, bundle_id: str) -> ImageBundle | None: ...

    def load_payloads(
        self,
        bundle_id: str,
    ) -> tuple[ImageBundlePayload, ...] | None: ...

    def load_bundle_payloads(
        self,
        bundle_id: str,
    ) -> tuple[ImageBundle, tuple[ImageBundlePayload, ...]] | None: ...

    def save(
        self,
        bundle: ImageBundle,
        *,
        expected_version: int,
    ) -> ImageBundle: ...

    def delete(
        self,
        bundle_id: str,
        *,
        expected_version: int,
    ) -> bool: ...


def validated_bundle_payloads(
    bundle: ImageBundle,
    payloads: Sequence[ImageBundlePayload],
) -> tuple[ImageBundlePayload, ...]:
    stored = tuple(
        payload.model_copy(deep=True)
        for payload in payloads
    )
    if len(stored) != len(bundle.images):
        raise ValueError("bundle payload count must match image metadata")
    if sum(payload.byte_size for payload in stored) > MAX_STORED_BUNDLE_BYTES:
        raise ValueError("bundle payload bytes exceed storage limit")
    for observation, payload in zip(
        bundle.images,
        stored,
        strict=True,
    ):
        if (
            payload.image_id,
            payload.ordinal,
            payload.content_sha256,
            payload.byte_size,
        ) != (
            observation.image_id,
            observation.ordinal,
            observation.content_sha256,
            observation.byte_size,
        ):
            raise ValueError("bundle payload does not match image metadata")
    return stored
