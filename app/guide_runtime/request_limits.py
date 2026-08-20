from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
import os
from pathlib import Path
from threading import Lock
import tempfile

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.formparsers import MultiPartException, MultiPartParser

from app.guide.adapters.image.inference_limiter import (
    ImageInferenceLockSecurityError,
    image_inference_slot,
)
from app.guide.adapters.image.safe_image_input import (
    MAX_BATCH_BYTES,
    MAX_IMAGE_COUNT,
)
from app.guide_runtime.upload_rate_limit import (
    ImageUploadRateStateError,
    SqliteImageUploadRateLimiter,
)


MAX_CHAT_REQUEST_BYTES = 256 * 1024
MAX_IMAGE_UPLOAD_REQUEST_BYTES = MAX_BATCH_BYTES + 64 * 1024
MAX_MULTIPART_FIELDS = 1
MAX_MULTIPART_FIELD_BYTES = 256
MAX_MULTIPART_FIELD_NAME_BYTES = 64
MAX_MULTIPART_FILENAME_BYTES = 255
MAX_MULTIPART_HEADERS_PER_PART = 8
MAX_MULTIPART_HEADER_NAME_BYTES = 64
MAX_MULTIPART_HEADER_VALUE_BYTES = 1024
MAX_MULTIPART_HEADERS_BYTES = 4096
MAX_MULTIPART_CONTENT_TYPE_BYTES = 512
IMAGE_UPLOAD_RATE_LIMIT = 12
IMAGE_UPLOAD_RATE_WINDOW_SECONDS = 60.0
IMAGE_UPLOAD_RATE_ENTRY_TTL_SECONDS = 120.0
IMAGE_UPLOAD_RATE_MAX_CLIENTS = 512
IMAGE_UPLOAD_LOCK_DIR_ENV = "XIAORO_IMAGE_UPLOAD_LOCK_DIR"
IMAGE_UPLOAD_RATE_STATE_PATH_ENV = (
    "XIAORO_IMAGE_UPLOAD_RATE_STATE_PATH"
)

_UPLOAD_LIMIT_DETAIL = {
    "code": "image_upload_request_too_large",
    "message": "图片上传请求超过安全限制。",
    "ordinal": None,
}
_UPLOAD_BUSY_DETAIL = {
    "code": "image_upload_busy",
    "message": "图片上传繁忙，请稍后重试。",
    "ordinal": None,
}
_UPLOAD_RATE_DETAIL = {
    "code": "image_upload_rate_limited",
    "message": "图片上传过于频繁，请稍后重试。",
    "ordinal": None,
}
_UPLOAD_UNAVAILABLE_DETAIL = {
    "code": "image_upload_unavailable",
    "message": "图片上传服务暂时不可用，请稍后重试。",
    "ordinal": None,
}
_INVALID_UPLOAD_DETAIL = {
    "code": "invalid_image_upload",
    "message": "图片上传格式无效。",
    "ordinal": None,
}


class _ImageUploadRequestTooLarge(MultiPartException):
    def __init__(self) -> None:
        super().__init__("image upload request body limit")


class _MultipartStructureLimit(MultiPartException):
    pass


class _ImageUploadBusy(RuntimeError):
    pass


class _ImageUploadRateLimited(RuntimeError):
    pass


class _ImageUploadUnavailable(RuntimeError):
    pass


def image_upload_rate_database_path() -> Path:
    if IMAGE_UPLOAD_RATE_STATE_PATH_ENV in os.environ:
        configured = os.environ[IMAGE_UPLOAD_RATE_STATE_PATH_ENV]
        if not configured:
            raise ValueError("rate state path must not be empty")
        database_path = Path(configured).expanduser()
        if not database_path.is_absolute():
            raise ValueError("rate state path must be absolute")
        return database_path

    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    return (
        temp_root
        / f"xiaoro-image-upload-rate-{os.getuid()}"
        / "image_upload_rate.sqlite3"
    )


class _ImageUploadAdmission:
    def __init__(self) -> None:
        self._lock = Lock()
        self._rate_limiter: SqliteImageUploadRateLimiter | None = None
        self._rate_database_path: Path | None = None

    def _get_rate_limiter(self) -> SqliteImageUploadRateLimiter:
        database_path = image_upload_rate_database_path()
        with self._lock:
            if (
                self._rate_limiter is None
                or self._rate_database_path != database_path
            ):
                self._rate_limiter = SqliteImageUploadRateLimiter(
                    database_path,
                    limit=IMAGE_UPLOAD_RATE_LIMIT,
                    window_seconds=IMAGE_UPLOAD_RATE_WINDOW_SECONDS,
                    entry_ttl_seconds=(
                        IMAGE_UPLOAD_RATE_ENTRY_TTL_SECONDS
                    ),
                    max_entries=IMAGE_UPLOAD_RATE_MAX_CLIENTS,
                )
                self._rate_database_path = database_path
            return self._rate_limiter

    @contextmanager
    def admit(self, client_key: str) -> Iterator[None]:
        try:
            allowed = self._get_rate_limiter().consume(client_key)
        except (
            ImageUploadRateStateError,
            OSError,
            RuntimeError,
            ValueError,
        ):
            raise _ImageUploadUnavailable from None
        if not allowed:
            raise _ImageUploadRateLimited

        try:
            configured = os.environ.get(IMAGE_UPLOAD_LOCK_DIR_ENV)
            lock_dir = (
                configured
                if configured
                else Path(tempfile.gettempdir())
                / f"xiaoro-image-upload-{os.getuid()}"
            )
        except (OSError, RuntimeError):
            raise _ImageUploadUnavailable from None

        try:
            with image_inference_slot(
                lock_dir=lock_dir,
                timeout=0,
            ):
                yield
        except TimeoutError:
            raise _ImageUploadBusy from None
        except ImageInferenceLockSecurityError:
            raise _ImageUploadUnavailable from None


class _BoundedMultiPartParser(MultiPartParser):
    def on_part_begin(self) -> None:
        super().on_part_begin()
        self._part_header_count = 0
        self._part_header_bytes = 0

    def on_header_field(
        self,
        data: bytes,
        start: int,
        end: int,
    ) -> None:
        fragment = data[start:end]
        if (
            len(self._current_partial_header_name) + len(fragment)
            > MAX_MULTIPART_HEADER_NAME_BYTES
        ):
            raise _MultipartStructureLimit("multipart header limit")
        super().on_header_field(data, start, end)

    def on_header_value(
        self,
        data: bytes,
        start: int,
        end: int,
    ) -> None:
        fragment = data[start:end]
        if (
            len(self._current_partial_header_value) + len(fragment)
            > MAX_MULTIPART_HEADER_VALUE_BYTES
        ):
            raise _MultipartStructureLimit("multipart header limit")
        super().on_header_value(data, start, end)

    def on_header_end(self) -> None:
        self._part_header_count += 1
        self._part_header_bytes += (
            len(self._current_partial_header_name)
            + len(self._current_partial_header_value)
        )
        if (
            self._part_header_count > MAX_MULTIPART_HEADERS_PER_PART
            or self._part_header_bytes > MAX_MULTIPART_HEADERS_BYTES
        ):
            raise _MultipartStructureLimit("multipart header limit")
        super().on_header_end()

    def on_headers_finished(self) -> None:
        super().on_headers_finished()
        if (
            len(self._current_part.field_name.encode("utf-8"))
            > MAX_MULTIPART_FIELD_NAME_BYTES
        ):
            raise _MultipartStructureLimit("multipart field name limit")
        if self._current_part.file is not None:
            filename = self._current_part.file.filename or ""
            if (
                len(filename.encode("utf-8"))
                > MAX_MULTIPART_FILENAME_BYTES
            ):
                raise _MultipartStructureLimit("multipart filename limit")

    def on_part_data(
        self,
        data: bytes,
        start: int,
        end: int,
    ) -> None:
        if (
            self._current_part.file is None
            and len(self._current_part.data) + end - start
            > MAX_MULTIPART_FIELD_BYTES
        ):
            raise _MultipartStructureLimit("multipart field limit")
        super().on_part_data(data, start, end)


def _json_error(status_code: int, detail: dict[str, object]) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
    )


def _declared_content_length(request: Request) -> int | None:
    value = request.headers.get("content-length")
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return -1
    return parsed if parsed >= 0 else -1


def _is_image_bundle_upload(
    request: Request,
    content_type: str,
) -> bool:
    return (
        request.method == "POST"
        and request.url.path.endswith("/chat/image-bundles")
        and content_type.lower().startswith("multipart/form-data")
    )


async def _parse_bounded_multipart(request: Request) -> None:
    content_type = request.headers.get("content-type", "")
    if (
        len(content_type.encode("latin-1", errors="replace"))
        > MAX_MULTIPART_CONTENT_TYPE_BYTES
    ):
        raise _MultipartStructureLimit("multipart content type limit")
    parser = _BoundedMultiPartParser(
        request.headers,
        request.stream(),
        max_files=MAX_IMAGE_COUNT,
        max_fields=MAX_MULTIPART_FIELDS,
    )
    request._form = await parser.parse()


class ChatBodyLimitRoute(APIRoute):
    """Apply body limits before FastAPI parses JSON or multipart forms."""

    def __init__(self, *args, **kwargs) -> None:
        self._image_upload_admission = _ImageUploadAdmission()
        super().__init__(*args, **kwargs)

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def limited_handler(request: Request):
            content_type = request.headers.get("content-type", "")
            image_upload = _is_image_bundle_upload(
                request,
                content_type,
            )
            body_limit = (
                MAX_IMAGE_UPLOAD_REQUEST_BYTES
                if image_upload
                else MAX_CHAT_REQUEST_BYTES
            )
            content_length = _declared_content_length(request)
            if content_length == -1:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "无效的 Content-Length"},
                )
            if (
                content_length is not None
                and content_length > body_limit
            ):
                if image_upload:
                    return _json_error(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        _UPLOAD_LIMIT_DETAIL,
                    )
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "请求体过大"},
                )

            received_bytes = 0
            original_receive = request.receive

            async def limited_receive():
                nonlocal received_bytes
                message = await original_receive()
                if message["type"] == "http.request":
                    received_bytes += len(message.get("body", b""))
                    if received_bytes > body_limit:
                        if image_upload:
                            raise _ImageUploadRequestTooLarge
                        raise HTTPException(
                            status_code=(
                                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                            ),
                            detail="请求体过大",
                        )
                return message

            limited_request = Request(
                request.scope,
                receive=limited_receive,
            )
            try:
                admission = (
                    self._image_upload_admission.admit(
                        request.client.host
                        if request.client is not None
                        else "unknown"
                    )
                    if image_upload
                    else nullcontext()
                )
                with admission:
                    if image_upload:
                        await _parse_bounded_multipart(limited_request)
                    return await original_handler(limited_request)
            except _ImageUploadRateLimited:
                return _json_error(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    _UPLOAD_RATE_DETAIL,
                )
            except _ImageUploadBusy:
                return _json_error(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    _UPLOAD_BUSY_DETAIL,
                )
            except _ImageUploadUnavailable:
                return _json_error(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    _UPLOAD_UNAVAILABLE_DETAIL,
                )
            except (
                _ImageUploadRequestTooLarge,
                _MultipartStructureLimit,
            ):
                return _json_error(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    _UPLOAD_LIMIT_DETAIL,
                )
            except MultiPartException as error:
                if error.message.startswith(
                    ("Too many files.", "Too many fields.")
                ):
                    return _json_error(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        _UPLOAD_LIMIT_DETAIL,
                    )
                return _json_error(
                    status.HTTP_400_BAD_REQUEST,
                    _INVALID_UPLOAD_DETAIL,
                )

        return limited_handler
