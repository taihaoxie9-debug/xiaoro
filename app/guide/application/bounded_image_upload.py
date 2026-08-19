from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import ValidationError

from app.guide.adapters.image.safe_image_input import (
    MAX_BATCH_BYTES,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_COUNT,
    SafeImageInputError,
    UntrustedImageInput,
)


IMAGE_UPLOAD_READ_CHUNK_BYTES = 64 * 1024


class UploadStream(Protocol):
    filename: str | None
    content_type: str | None

    async def read(self, size: int) -> bytes: ...

    async def close(self) -> None: ...


async def read_bounded_uploads(
    uploads: Sequence[UploadStream],
) -> tuple[UntrustedImageInput, ...]:
    files = tuple(uploads)
    business_error: BaseException | None = None
    try:
        if not 1 <= len(files) <= MAX_IMAGE_COUNT:
            raise SafeImageInputError(
                "invalid_image_count",
                f"expected 1..{MAX_IMAGE_COUNT} images",
            )

        batch_total = 0
        materialized: list[UntrustedImageInput] = []
        for ordinal, upload in enumerate(files, start=1):
            file_total = 0
            chunks: list[bytes] = []
            while True:
                request_size = min(
                    IMAGE_UPLOAD_READ_CHUNK_BYTES,
                    MAX_IMAGE_BYTES + 1 - file_total,
                    MAX_BATCH_BYTES + 1 - batch_total,
                )
                chunk = await upload.read(request_size)
                if not chunk:
                    break
                file_total += len(chunk)
                batch_total += len(chunk)
                if batch_total > MAX_BATCH_BYTES:
                    raise SafeImageInputError(
                        "batch_too_large",
                        f"maximum is {MAX_BATCH_BYTES} bytes",
                    )
                if file_total > MAX_IMAGE_BYTES:
                    raise SafeImageInputError(
                        "image_too_large",
                        f"maximum is {MAX_IMAGE_BYTES} bytes",
                        ordinal=ordinal,
                    )
                chunks.append(chunk)

            try:
                materialized.append(
                    UntrustedImageInput(
                        file_name=upload.filename or "",
                        declared_media_type=upload.content_type or "",
                        content=b"".join(chunks),
                    )
                )
            except ValidationError:
                raise SafeImageInputError(
                    "invalid_input_contract",
                    "upload metadata or content is invalid",
                    ordinal=ordinal,
                ) from None
        return tuple(materialized)
    except BaseException as exc:
        business_error = exc
        raise
    finally:
        first_close_error: BaseException | None = None
        for upload in files:
            try:
                await upload.close()
            except BaseException as exc:
                if first_close_error is None:
                    first_close_error = exc
        if business_error is None and first_close_error is not None:
            raise first_close_error
