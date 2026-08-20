from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.application.contracts import BundleId, OwnerToken
from app.guide.session_contract import SessionId


class ChatStreamRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    message: str = Field(min_length=1, max_length=4000)
    session_id: SessionId | None = None
    conversation_version: int = Field(default=0, ge=0)
    stream: bool = True
    image_bundle_id: BundleId | None = None
    image_bundle_version: int | None = Field(default=None, ge=1)
    image_bundle_token: OwnerToken | None = None
    image_results: list[dict[str, Any]] | None = None
    image_context: dict[str, Any] | None = None
    images: list[str] | None = None

    @model_validator(mode="after")
    def validate_image_bundle_reference(self) -> Self:
        reference = (
            self.image_bundle_id,
            self.image_bundle_version,
            self.image_bundle_token,
        )
        if any(value is not None for value in reference) and not all(
            value is not None for value in reference
        ):
            raise ValueError(
                "image bundle id, version, and token must be supplied together"
            )
        return self

    @property
    def has_image_bundle_reference(self) -> bool:
        return self.image_bundle_id is not None

    @property
    def has_legacy_image_payload(self) -> bool:
        return bool(
            self.image_results
            or self.image_context
            or self.images
        )
