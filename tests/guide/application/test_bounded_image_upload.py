from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from PIL import Image

from app.guide.adapters.image.safe_image_input import (
    MAX_BATCH_BYTES,
    MAX_IMAGE_BYTES,
    SafeImageInputError,
)
from app.guide.application.bounded_image_upload import (
    IMAGE_UPLOAD_READ_CHUNK_BYTES,
    read_bounded_uploads,
)


class ObservableUpload:
    def __init__(
        self,
        *,
        logical_size: int,
        file_name: str = "product.jpg",
        content_type: str = "image/jpeg",
        content: bytes | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.filename = file_name
        self.content_type = content_type
        self.logical_size = logical_size
        self._content = content
        self._close_error = close_error
        self.total_returned = 0
        self.requested_sizes: list[int] = []
        self.closed = False

    async def read(self, size: int) -> bytes:
        assert isinstance(size, int)
        assert 0 < size <= IMAGE_UPLOAD_READ_CHUNK_BYTES
        self.requested_sizes.append(size)
        remaining = self.logical_size - self.total_returned
        if remaining <= 0:
            return b""
        count = min(size, remaining)
        start = self.total_returned
        self.total_returned += count
        if self._content is None:
            return b"x" * count
        return self._content[start:self.total_returned]

    async def close(self) -> None:
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


def _jpeg() -> bytes:
    image = Image.new("RGB", (4, 3), color=(23, 67, 101))
    output = BytesIO()
    image.save(output, format="JPEG")
    image.close()
    return output.getvalue()


def test_reads_valid_uploads_in_bounded_chunks_and_closes_them() -> None:
    content = _jpeg()
    upload = ObservableUpload(
        logical_size=len(content),
        content=content,
    )

    result = asyncio.run(read_bounded_uploads([upload]))

    assert len(result) == 1
    assert result[0].file_name == "product.jpg"
    assert result[0].declared_media_type == "image/jpeg"
    assert result[0].content == content
    assert upload.requested_sizes
    assert all(
        size <= IMAGE_UPLOAD_READ_CHUNK_BYTES
        for size in upload.requested_sizes
    )
    assert upload.closed is True


def test_single_oversized_stream_stops_at_eight_mib_plus_one() -> None:
    upload = ObservableUpload(logical_size=64 * 1024 * 1024)

    with pytest.raises(SafeImageInputError) as caught:
        asyncio.run(read_bounded_uploads([upload]))

    assert caught.value.code == "image_too_large"
    assert caught.value.ordinal == 1
    assert upload.total_returned == MAX_IMAGE_BYTES + 1
    assert upload.total_returned < upload.logical_size
    assert upload.closed is True
    assert all(
        size <= IMAGE_UPLOAD_READ_CHUNK_BYTES
        for size in upload.requested_sizes
    )


def test_batch_streams_stop_at_twenty_mib_plus_one() -> None:
    uploads = [
        ObservableUpload(logical_size=MAX_IMAGE_BYTES),
        ObservableUpload(logical_size=MAX_IMAGE_BYTES),
        ObservableUpload(logical_size=MAX_IMAGE_BYTES),
    ]

    with pytest.raises(SafeImageInputError) as caught:
        asyncio.run(read_bounded_uploads(uploads))

    assert caught.value.code == "batch_too_large"
    assert caught.value.ordinal is None
    assert sum(item.total_returned for item in uploads) == (
        MAX_BATCH_BYTES + 1
    )
    assert uploads[-1].total_returned == 4 * 1024 * 1024 + 1
    assert uploads[-1].total_returned < uploads[-1].logical_size
    assert all(item.closed for item in uploads)


@pytest.mark.parametrize("count", [0, 5])
def test_invalid_count_is_rejected_before_any_stream_read(
    count: int,
) -> None:
    uploads = [
        ObservableUpload(logical_size=64 * 1024 * 1024)
        for _ in range(count)
    ]

    with pytest.raises(SafeImageInputError) as caught:
        asyncio.run(read_bounded_uploads(uploads))

    assert caught.value.code == "invalid_image_count"
    assert all(item.total_returned == 0 for item in uploads)
    assert all(item.requested_sizes == [] for item in uploads)
    assert all(item.closed for item in uploads)


def test_failure_closes_unread_later_files() -> None:
    uploads = [
        ObservableUpload(logical_size=MAX_IMAGE_BYTES + 1),
        ObservableUpload(logical_size=1),
    ]

    with pytest.raises(SafeImageInputError):
        asyncio.run(read_bounded_uploads(uploads))

    assert uploads[0].total_returned == MAX_IMAGE_BYTES + 1
    assert uploads[1].total_returned == 0
    assert all(item.closed for item in uploads)


def test_close_failure_does_not_prevent_later_uploads_from_closing() -> None:
    content = _jpeg()
    close_error = RuntimeError("first close failed")
    uploads = [
        ObservableUpload(
            logical_size=len(content),
            content=content,
            close_error=close_error,
        ),
        ObservableUpload(logical_size=len(content), content=content),
    ]

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(read_bounded_uploads(uploads))

    assert caught.value is close_error
    assert all(item.closed for item in uploads)


def test_business_error_takes_priority_over_close_failure() -> None:
    uploads = [
        ObservableUpload(
            logical_size=MAX_IMAGE_BYTES + 1,
            close_error=RuntimeError("first close failed"),
        ),
        ObservableUpload(logical_size=1),
    ]

    with pytest.raises(SafeImageInputError) as caught:
        asyncio.run(read_bounded_uploads(uploads))

    assert caught.value.code == "image_too_large"
    assert all(item.closed for item in uploads)
