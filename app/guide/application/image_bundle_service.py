from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from app.guide.adapters.image.safe_image_input import (
    SafeImageInputError,
    UntrustedImageInput,
    validate_image_batch,
)
from app.guide.application.contracts import (
    ImageBundleUploadReceipt,
    ImageErrorCode,
    PublicImageError,
)
from app.guide.application.image_bundle_state import (
    ImageBundlePayload,
    ImageBundleCapacityExceeded,
    ImageBundleStateConflict,
    ImageBundleStateCorrupt,
    ImageBundleStatePort,
    validated_bundle_payloads,
)
from app.guide.understanding.contracts import (
    ImageBundle,
    ImageObservation,
)


_UNAVAILABLE = PublicImageError(
    code=ImageErrorCode.IMAGE_BUNDLE_UNAVAILABLE,
    message="图片引用不可用，请重新上传。",
    ordinal=None,
)
_CAPACITY = PublicImageError(
    code=ImageErrorCode.IMAGE_BUNDLE_CAPACITY,
    message="图片服务繁忙，请稍后重试。",
    ordinal=None,
)
_SAFE_IMAGE_MESSAGES: dict[ImageErrorCode, str] = {
    ImageErrorCode.INVALID_IMAGE_COUNT: "请选择 1 至 4 张图片。",
    ImageErrorCode.INVALID_INPUT_CONTRACT: "图片上传信息无效。",
    ImageErrorCode.IMAGE_TOO_LARGE: "单张图片不能超过 8 MB。",
    ImageErrorCode.BATCH_TOO_LARGE: "图片总大小不能超过 20 MB。",
    ImageErrorCode.UNSUPPORTED_MEDIA_TYPE: (
        "仅支持 JPEG、PNG 或 WebP 图片。"
    ),
    ImageErrorCode.UNSUPPORTED_FILE_EXTENSION: (
        "仅支持 .jpg、.jpeg、.png 或 .webp 文件。"
    ),
    ImageErrorCode.INVALID_IMAGE_DATA: "图片无法安全解码。",
    ImageErrorCode.MEDIA_TYPE_FORMAT_MISMATCH: "图片类型与文件内容不一致。",
    ImageErrorCode.EXTENSION_FORMAT_MISMATCH: "图片扩展名与文件内容不一致。",
    ImageErrorCode.MAGIC_FORMAT_MISMATCH: "图片签名与声明格式不一致。",
    ImageErrorCode.DECODED_FORMAT_MISMATCH: "图片解码格式与声明不一致。",
    ImageErrorCode.DECOMPRESSION_BOMB: "图片解码资源超出安全限制。",
    ImageErrorCode.PIXEL_LIMIT_EXCEEDED: "单张图片不能超过 2000 万像素。",
    ImageErrorCode.ANIMATED_IMAGE_NOT_ALLOWED: "暂不支持动态图片。",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ImageBundleServiceError(RuntimeError):
    def __init__(self, error: PublicImageError) -> None:
        self.error = error.model_copy(deep=True)
        super().__init__(f"{error.code.value}: {error.message}")


class ImageBundleService:
    def __init__(
        self,
        *,
        state: ImageBundleStatePort,
        ttl_seconds: int = 15 * 60,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._state = state
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock

    def create(
        self,
        *,
        session_id: str,
        images: Sequence[UntrustedImageInput],
    ) -> ImageBundleUploadReceipt:
        try:
            validated = validate_image_batch(images)
        except SafeImageInputError as error:
            raise ImageBundleServiceError(
                self.public_error_for_safe_input(error)
            ) from None

        now = self._now()
        expires_at = now + self._ttl
        owner_token = f"owner_{secrets.token_urlsafe(32)}"
        owner_token_sha256 = self._token_hash(owner_token)
        observations: list[ImageObservation] = []
        payloads: list[ImageBundlePayload] = []
        for image in validated:
            image_id = f"image_{secrets.token_urlsafe(24)}"
            observations.append(
                ImageObservation(
                    image_id=image_id,
                    ordinal=image.ordinal,
                    content_sha256=image.content_sha256,
                    media_type=image.media_type,
                    image_format=image.image_format,
                    width=image.width,
                    height=image.height,
                    byte_size=image.byte_size,
                )
            )
            payloads.append(
                ImageBundlePayload(
                    image_id=image_id,
                    ordinal=image.ordinal,
                    content_sha256=image.content_sha256,
                    byte_size=image.byte_size,
                    content=image.content,
                )
            )

        for _ in range(3):
            bundle = ImageBundle(
                bundle_id=f"bundle_{secrets.token_urlsafe(24)}",
                session_id=session_id,
                owner_token_sha256=owner_token_sha256,
                version=1,
                created_at=now,
                expires_at=expires_at,
                images=[
                    image.model_copy(deep=True)
                    for image in observations
                ],
            )
            try:
                stored = self._state.create(
                    bundle,
                    payloads=payloads,
                )
                break
            except ImageBundleStateConflict:
                continue
            except ImageBundleCapacityExceeded:
                raise ImageBundleServiceError(_CAPACITY) from None
        else:
            raise ImageBundleServiceError(_CAPACITY)

        return ImageBundleUploadReceipt(
            bundle_id=stored.bundle_id,
            version=stored.version,
            owner_token=owner_token,
            expires_at=stored.expires_at,
            image_count=len(stored.images),
            message="图片已安全接收，发送后将进行单图相似检索。",
        )

    def authorize(
        self,
        *,
        bundle_id: str,
        version: int,
        session_id: str,
        owner_token: str,
    ) -> ImageBundle:
        try:
            bundle = self._state.load(bundle_id)
        except ImageBundleStateCorrupt:
            raise ImageBundleServiceError(_UNAVAILABLE) from None
        return self._authorize_bundle(
            bundle,
            version=version,
            session_id=session_id,
            owner_token=owner_token,
        )

    def _authorize_bundle(
        self,
        bundle: ImageBundle | None,
        *,
        version: int,
        session_id: str,
        owner_token: str,
    ) -> ImageBundle:
        supplied_hash = self._token_hash(owner_token)
        expected_hash = (
            bundle.owner_token_sha256
            if bundle is not None
            else "0" * 64
        )
        token_matches = hmac.compare_digest(
            expected_hash,
            supplied_hash,
        )
        if (
            bundle is None
            or not token_matches
            or bundle.session_id != session_id
            or bundle.version != version
        ):
            raise ImageBundleServiceError(_UNAVAILABLE)
        return bundle.model_copy(deep=True)

    def authorize_payloads(
        self,
        *,
        bundle_id: str,
        version: int,
        session_id: str,
        owner_token: str,
    ) -> tuple[ImageBundlePayload, ...]:
        _, payloads = self.authorize_bundle_payloads(
            bundle_id=bundle_id,
            version=version,
            session_id=session_id,
            owner_token=owner_token,
        )
        return payloads

    def authorize_bundle_payloads(
        self,
        *,
        bundle_id: str,
        version: int,
        session_id: str,
        owner_token: str,
    ) -> tuple[ImageBundle, tuple[ImageBundlePayload, ...]]:
        try:
            record = self._state.load_bundle_payloads(bundle_id)
        except ImageBundleStateCorrupt:
            raise ImageBundleServiceError(_UNAVAILABLE) from None
        bundle, payloads = record if record is not None else (None, ())
        authorized_bundle = self._authorize_bundle(
            bundle,
            version=version,
            session_id=session_id,
            owner_token=owner_token,
        )
        try:
            authorized_payloads = validated_bundle_payloads(
                authorized_bundle,
                payloads,
            )
        except ValueError:
            raise ImageBundleServiceError(_UNAVAILABLE) from None
        return authorized_bundle, authorized_payloads

    def delete(
        self,
        *,
        bundle_id: str,
        version: int,
        session_id: str,
        owner_token: str,
    ) -> None:
        self.authorize(
            bundle_id=bundle_id,
            version=version,
            session_id=session_id,
            owner_token=owner_token,
        )
        if not self._state.delete(
            bundle_id,
            expected_version=version,
        ):
            raise ImageBundleServiceError(_UNAVAILABLE)

    @staticmethod
    def public_error_for_safe_input(
        error: SafeImageInputError,
    ) -> PublicImageError:
        code = ImageErrorCode(error.code)
        return PublicImageError(
            code=code,
            message=_SAFE_IMAGE_MESSAGES[code],
            ordinal=error.ordinal,
        )

    @staticmethod
    def _token_hash(owner_token: str) -> str:
        return hashlib.sha256(owner_token.encode("utf-8")).hexdigest()

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now
