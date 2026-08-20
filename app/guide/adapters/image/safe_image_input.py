from __future__ import annotations

import hashlib
import warnings
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints


MAX_IMAGE_COUNT = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_BATCH_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000

ImageFormat = Literal["JPEG", "PNG", "WEBP"]

_MIME_FORMATS: dict[str, ImageFormat] = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
_EXTENSION_FORMATS: dict[str, ImageFormat] = {
    ".jpeg": "JPEG",
    ".jpg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


class _StrictFrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class UntrustedImageInput(_StrictFrozenContract):
    file_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    ]
    declared_media_type: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]
    content: bytes = Field(min_length=1)


class ValidatedImageInput(_StrictFrozenContract):
    ordinal: int = Field(ge=1, le=MAX_IMAGE_COUNT)
    file_name: str
    media_type: str
    image_format: ImageFormat
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_size: int = Field(gt=0, le=MAX_IMAGE_BYTES)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: bytes = Field(min_length=1, max_length=MAX_IMAGE_BYTES)


class SafeImageInputError(ValueError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        ordinal: int | None = None,
    ) -> None:
        self.code = code
        self.ordinal = ordinal
        location = f" image {ordinal}" if ordinal is not None else ""
        super().__init__(f"{code}:{location} {detail}")


def validate_image_batch(
    images: Sequence[UntrustedImageInput],
) -> tuple[ValidatedImageInput, ...]:
    batch = tuple(images)
    if not 1 <= len(batch) <= MAX_IMAGE_COUNT:
        raise SafeImageInputError(
            "invalid_image_count",
            f"expected 1..{MAX_IMAGE_COUNT} images",
        )

    total_bytes = 0
    for ordinal, image in enumerate(batch, start=1):
        if not isinstance(image, UntrustedImageInput):
            raise SafeImageInputError(
                "invalid_input_contract",
                "image does not match UntrustedImageInput",
                ordinal=ordinal,
            )
        byte_size = len(image.content)
        if byte_size > MAX_IMAGE_BYTES:
            raise SafeImageInputError(
                "image_too_large",
                f"maximum is {MAX_IMAGE_BYTES} bytes",
                ordinal=ordinal,
            )
        total_bytes += byte_size

    if total_bytes > MAX_BATCH_BYTES:
        raise SafeImageInputError(
            "batch_too_large",
            f"maximum is {MAX_BATCH_BYTES} bytes",
        )

    validated: list[ValidatedImageInput] = []
    for ordinal, image in enumerate(batch, start=1):
        image_format = _validate_declared_format(image, ordinal)
        width, height = _decode_and_inspect(
            image.content,
            expected_format=image_format,
            ordinal=ordinal,
        )
        validated.append(
            ValidatedImageInput(
                ordinal=ordinal,
                file_name=image.file_name,
                media_type=image.declared_media_type,
                image_format=image_format,
                width=width,
                height=height,
                byte_size=len(image.content),
                content_sha256=hashlib.sha256(image.content).hexdigest(),
                content=image.content,
            )
        )
    return tuple(validated)


def _validate_declared_format(
    image: UntrustedImageInput,
    ordinal: int,
) -> ImageFormat:
    declared_format = _MIME_FORMATS.get(image.declared_media_type)
    if declared_format is None:
        raise SafeImageInputError(
            "unsupported_media_type",
            "only image/jpeg, image/png, and image/webp are accepted",
            ordinal=ordinal,
        )

    extension_format = _EXTENSION_FORMATS.get(
        Path(image.file_name).suffix.lower()
    )
    if extension_format is None:
        raise SafeImageInputError(
            "unsupported_file_extension",
            "only .jpg, .jpeg, .png, and .webp are accepted",
            ordinal=ordinal,
        )

    magic_format = _format_from_magic(image.content)
    if magic_format is None:
        raise SafeImageInputError(
            "invalid_image_data",
            "content has no supported image signature",
            ordinal=ordinal,
        )

    if declared_format != extension_format:
        if magic_format == extension_format:
            code = "media_type_format_mismatch"
        elif magic_format == declared_format:
            code = "extension_format_mismatch"
        else:
            code = "magic_format_mismatch"
        raise SafeImageInputError(
            code,
            "MIME, extension, and magic bytes disagree",
            ordinal=ordinal,
        )

    if magic_format != declared_format:
        raise SafeImageInputError(
            "magic_format_mismatch",
            "magic bytes disagree with MIME and extension",
            ordinal=ordinal,
        )
    return declared_format


def _format_from_magic(content: bytes) -> ImageFormat | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if (
        len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    ):
        return "WEBP"
    return None


def _decode_and_inspect(
    content: bytes,
    *,
    expected_format: ImageFormat,
    ordinal: int,
) -> tuple[int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                _validate_decoded_header(
                    image,
                    expected_format=expected_format,
                    ordinal=ordinal,
                )
                image.verify()

            with Image.open(BytesIO(content)) as image:
                _validate_decoded_header(
                    image,
                    expected_format=expected_format,
                    ordinal=ordinal,
                )
                image.load()
    except SafeImageInputError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise SafeImageInputError(
            "decompression_bomb",
            "Pillow rejected the image pixel expansion",
            ordinal=ordinal,
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise SafeImageInputError(
            "invalid_image_data",
            "image cannot be fully decoded",
            ordinal=ordinal,
        ) from exc
    return width, height


def _validate_decoded_header(
    image: Image.Image,
    *,
    expected_format: ImageFormat,
    ordinal: int,
) -> None:
    if image.format != expected_format:
        raise SafeImageInputError(
            "decoded_format_mismatch",
            "Pillow format disagrees with declared format",
            ordinal=ordinal,
        )

    width, height = image.size
    if width <= 0 or height <= 0:
        raise SafeImageInputError(
            "invalid_image_data",
            "image dimensions must be positive",
            ordinal=ordinal,
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise SafeImageInputError(
            "pixel_limit_exceeded",
            f"maximum is {MAX_IMAGE_PIXELS} pixels",
            ordinal=ordinal,
        )

    if (
        bool(getattr(image, "is_animated", False))
        or int(getattr(image, "n_frames", 1)) != 1
    ):
        raise SafeImageInputError(
            "animated_image_not_allowed",
            "animated PNG and WebP images are not accepted",
            ordinal=ordinal,
        )
