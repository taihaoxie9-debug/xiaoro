from __future__ import annotations

from collections.abc import Sequence

from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.guide.adapters.image.safe_image_input import SafeImageInputError
from app.guide.application.bounded_image_upload import UploadStream
from app.guide.application.bounded_image_upload import (
    read_bounded_uploads,
)
from app.guide.application.contracts import (
    ImageBundleUploadReceipt,
    ImageErrorCode,
)
from app.guide.application.image_bundle_service import (
    ImageBundleService,
    ImageBundleServiceError,
)


async def create_image_bundle_from_uploads(
    service: ImageBundleService,
    *,
    session_id: str,
    uploads: Sequence[UploadStream],
) -> ImageBundleUploadReceipt:
    try:
        images = await read_bounded_uploads(uploads)
        return await run_in_threadpool(
            service.create,
            session_id=session_id,
            images=images,
        )
    except SafeImageInputError as error:
        public_error = service.public_error_for_safe_input(error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=public_error.model_dump(mode="json"),
        ) from None
    except ImageBundleServiceError as error:
        if error.error.code is ImageErrorCode.IMAGE_BUNDLE_CAPACITY:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif (
            error.error.code
            is ImageErrorCode.IMAGE_BUNDLE_UNAVAILABLE
        ):
            status_code = status.HTTP_404_NOT_FOUND
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=status_code,
            detail=error.error.model_dump(mode="json"),
        ) from None


def delete_image_bundle(
    service: ImageBundleService,
    *,
    bundle_id: str,
    version: int,
    session_id: str,
    owner_token: str,
) -> None:
    try:
        service.delete(
            bundle_id=bundle_id,
            version=version,
            session_id=session_id,
            owner_token=owner_token,
        )
    except ImageBundleServiceError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error.error.model_dump(mode="json"),
        ) from None
