from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.session_contract import SessionId
UserMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
ImageCapableMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=4000),
]
ImageAction = Literal["identify", "compare"]
BundleId = Annotated[
    str,
    StringConstraints(
        min_length=39,
        max_length=160,
        pattern=r"^bundle_[A-Za-z0-9_-]{32,152}$",
    ),
]
OwnerToken = Annotated[
    str,
    StringConstraints(
        min_length=49,
        max_length=192,
        pattern=r"^owner_[A-Za-z0-9_-]{43,186}$",
    ),
]


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TurnIdentity(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    session_id: SessionId
    request_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)


class ImageErrorCode(str, Enum):
    INVALID_IMAGE_COUNT = "invalid_image_count"
    INVALID_INPUT_CONTRACT = "invalid_input_contract"
    IMAGE_TOO_LARGE = "image_too_large"
    BATCH_TOO_LARGE = "batch_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    UNSUPPORTED_FILE_EXTENSION = "unsupported_file_extension"
    INVALID_IMAGE_DATA = "invalid_image_data"
    MEDIA_TYPE_FORMAT_MISMATCH = "media_type_format_mismatch"
    EXTENSION_FORMAT_MISMATCH = "extension_format_mismatch"
    MAGIC_FORMAT_MISMATCH = "magic_format_mismatch"
    DECODED_FORMAT_MISMATCH = "decoded_format_mismatch"
    DECOMPRESSION_BOMB = "decompression_bomb"
    PIXEL_LIMIT_EXCEEDED = "pixel_limit_exceeded"
    ANIMATED_IMAGE_NOT_ALLOWED = "animated_image_not_allowed"
    IMAGE_UPLOAD_REQUEST_TOO_LARGE = "image_upload_request_too_large"
    INVALID_IMAGE_UPLOAD = "invalid_image_upload"
    IMAGE_UPLOAD_BUSY = "image_upload_busy"
    IMAGE_UPLOAD_RATE_LIMITED = "image_upload_rate_limited"
    IMAGE_UPLOAD_UNAVAILABLE = "image_upload_unavailable"
    IMAGE_BUNDLE_UNAVAILABLE = "image_bundle_unavailable"
    IMAGE_BUNDLE_CAPACITY = "image_bundle_capacity"


class PublicImageError(_StrictContract):
    code: ImageErrorCode
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
    ]
    ordinal: int | None = Field(default=None, ge=1, le=4)


class ImageBundleUploadReceipt(_StrictContract):
    bundle_id: BundleId
    version: int = Field(ge=1)
    owner_token: OwnerToken
    expires_at: datetime
    image_count: int = Field(ge=1, le=4)
    message: Literal["图片已安全接收，发送后将进行单图相似检索。"]


class ImageBundleDeleteRequest(_StrictContract):
    session_id: SessionId
    version: int = Field(ge=1)
    owner_token: OwnerToken


class UserTurn(_StrictContract):
    identity: TurnIdentity
    session_id: SessionId
    message: ImageCapableMessage
    image_action: ImageAction | None = None
    profile_owner: ProfileOwnerRef | None = None
    image_bundle_id: BundleId | None = None
    image_bundle_version: int | None = Field(default=None, ge=1)
    image_bundle_token: OwnerToken | None = None
    conversation_version: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_image_bundle_reference(self) -> Self:
        if self.identity.session_id != self.session_id:
            raise ValueError(
                "turn identity session must match user turn session"
            )
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
    def question_summary(self) -> str:
        if self.message:
            return self.message
        return {
            "identify": "识别上传图片中的商品",
            "compare": "比较上传图片中的商品",
        }[self.image_action]
