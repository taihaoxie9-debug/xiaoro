from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.guide.application.contracts import (
    BundleId,
    ImageAction,
    OwnerToken,
)
from app.guide.session_contract import SessionId


class ChatStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=4000),
    ]
    image_action: ImageAction | None = None
    session_id: SessionId | None = None
    conversation_version: int = Field(default=0, ge=0)
    stream: bool = True
    image_bundle_id: BundleId | None = None
    image_bundle_version: int | None = Field(default=None, ge=1)
    image_bundle_token: OwnerToken | None = None

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
        if self.image_action is not None:
            if self.message:
                raise ValueError("image action forbids message")
            if not all(value is not None for value in reference):
                raise ValueError("image action requires image bundle")
        elif not self.message:
            raise ValueError("empty message requires typed image action")
        return self

    @property
    def has_image_bundle_reference(self) -> bool:
        return self.image_bundle_id is not None
