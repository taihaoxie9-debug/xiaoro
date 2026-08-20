from __future__ import annotations

import hashlib
import inspect
from importlib import import_module
from io import BytesIO
from typing import Any

import pytest
from PIL import Image
from pydantic import ValidationError


MIB = 1024 * 1024


def _subject() -> Any:
    return import_module("app.guide.adapters.image.safe_image_input")


def _encode_image(
    image_format: str,
    *,
    size: tuple[int, int] = (4, 3),
    animated: bool = False,
) -> bytes:
    first = Image.new("RGB", size, color=(23, 67, 101))
    output = BytesIO()
    if not animated:
        first.save(output, format=image_format)
        first.close()
        return output.getvalue()

    second = Image.new("RGB", size, color=(151, 113, 71))
    first.save(
        output,
        format=image_format,
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    first.close()
    second.close()
    return output.getvalue()


def _input(
    *,
    file_name: str = "photo.jpg",
    media_type: str = "image/jpeg",
    content: bytes | None = None,
) -> Any:
    module = _subject()
    return module.UntrustedImageInput(
        file_name=file_name,
        declared_media_type=media_type,
        content=content or _encode_image("JPEG"),
    )


def _assert_rejected(
    images: list[Any],
    *,
    code: str,
    ordinal: int | None,
) -> None:
    module = _subject()
    with pytest.raises(module.SafeImageInputError) as caught:
        module.validate_image_batch(images)

    assert caught.value.code == code
    assert caught.value.ordinal == ordinal


@pytest.mark.parametrize(
    ("image_format", "file_name", "media_type"),
    [
        ("JPEG", "first.jpeg", "image/jpeg"),
        ("PNG", "second.PNG", "image/png"),
        ("WEBP", "third.webp", "image/webp"),
    ],
)
def test_accepts_supported_still_image_formats(
    image_format: str,
    file_name: str,
    media_type: str,
) -> None:
    module = _subject()
    content = _encode_image(image_format)

    result = module.validate_image_batch(
        [
            _input(
                file_name=file_name,
                media_type=media_type,
                content=content,
            )
        ]
    )

    assert result == (
        module.ValidatedImageInput(
            ordinal=1,
            file_name=file_name,
            media_type=media_type,
            image_format=image_format,
            width=4,
            height=3,
            byte_size=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
            content=content,
        ),
    )


def test_preserves_upload_order_and_stable_metadata() -> None:
    module = _subject()
    cases = [
        ("one.webp", "image/webp", _encode_image("WEBP")),
        ("two.png", "image/png", _encode_image("PNG")),
        ("three.jpg", "image/jpeg", _encode_image("JPEG")),
    ]

    result = module.validate_image_batch(
        [
            _input(file_name=name, media_type=media_type, content=content)
            for name, media_type, content in cases
        ]
    )

    assert tuple(image.ordinal for image in result) == (1, 2, 3)
    assert tuple(image.file_name for image in result) == tuple(
        case[0] for case in cases
    )
    assert tuple(image.content_sha256 for image in result) == tuple(
        hashlib.sha256(case[2]).hexdigest() for case in cases
    )


def test_accepts_four_images_and_rejects_zero_or_five() -> None:
    image = _input()

    assert len(_subject().validate_image_batch([image] * 4)) == 4
    _assert_rejected([], code="invalid_image_count", ordinal=None)
    _assert_rejected(
        [image] * 5,
        code="invalid_image_count",
        ordinal=None,
    )


def test_single_image_limit_is_inclusive_at_eight_mib() -> None:
    content = _encode_image("JPEG")
    exactly_eight_mib = content + b"\0" * (8 * MIB - len(content))

    result = _subject().validate_image_batch(
        [_input(content=exactly_eight_mib)]
    )

    assert result[0].byte_size == 8 * MIB
    _assert_rejected(
        [_input(content=exactly_eight_mib + b"\0")],
        code="image_too_large",
        ordinal=1,
    )


def test_batch_limit_is_inclusive_at_twenty_mib_and_checked_atomically() -> None:
    content = _encode_image("JPEG")
    five_mib = content + b"\0" * (5 * MIB - len(content))
    images = [_input(content=five_mib) for _ in range(4)]

    result = _subject().validate_image_batch(images)

    assert sum(image.byte_size for image in result) == 20 * MIB
    oversized_last = _input(content=five_mib + b"\0")
    _assert_rejected(
        [*images[:3], oversized_last],
        code="batch_too_large",
        ordinal=None,
    )


@pytest.mark.parametrize(
    ("file_name", "media_type", "content", "expected_code"),
    [
        (
            "photo.jpg",
            "image/png",
            _encode_image("JPEG"),
            "media_type_format_mismatch",
        ),
        (
            "photo.png",
            "image/jpeg",
            _encode_image("JPEG"),
            "extension_format_mismatch",
        ),
        (
            "photo.jpg",
            "image/jpeg",
            _encode_image("PNG"),
            "magic_format_mismatch",
        ),
        (
            "photo.gif",
            "image/gif",
            _encode_image("JPEG"),
            "unsupported_media_type",
        ),
    ],
)
def test_rejects_declared_format_mismatches(
    file_name: str,
    media_type: str,
    content: bytes,
    expected_code: str,
) -> None:
    _assert_rejected(
        [
            _input(
                file_name=file_name,
                media_type=media_type,
                content=content,
            )
        ],
        code=expected_code,
        ordinal=1,
    )


def test_rejects_pillow_format_disagreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _subject()

    class WrongFormatImage:
        format = "PNG"
        size = (4, 3)
        n_frames = 1
        is_animated = False

        def __enter__(self) -> WrongFormatImage:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def verify(self) -> None:
            return None

        def load(self) -> None:
            return None

    monkeypatch.setattr(module.Image, "open", lambda stream: WrongFormatImage())

    _assert_rejected(
        [_input(content=_encode_image("JPEG"))],
        code="decoded_format_mismatch",
        ordinal=1,
    )


def test_rejects_image_over_twenty_million_pixels() -> None:
    image = Image.new("1", (5000, 4001), color=0)
    output = BytesIO()
    image.save(output, format="PNG")
    image.close()

    _assert_rejected(
        [
            _input(
                file_name="large.png",
                media_type="image/png",
                content=output.getvalue(),
            )
        ],
        code="pixel_limit_exceeded",
        ordinal=1,
    )


@pytest.mark.parametrize(
    ("image_format", "file_name", "media_type"),
    [
        ("PNG", "animated.png", "image/png"),
        ("WEBP", "animated.webp", "image/webp"),
    ],
)
def test_rejects_apng_and_animated_webp(
    image_format: str,
    file_name: str,
    media_type: str,
) -> None:
    _assert_rejected(
        [
            _input(
                file_name=file_name,
                media_type=media_type,
                content=_encode_image(image_format, animated=True),
            )
        ],
        code="animated_image_not_allowed",
        ordinal=1,
    )


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\xd8\xff\xe0" + b"\0" * 128,
        _encode_image("JPEG")[:256],
    ],
)
def test_rejects_corrupt_or_truncated_images(content: bytes) -> None:
    _assert_rejected(
        [_input(content=content)],
        code="invalid_image_data",
        ordinal=1,
    )


@pytest.mark.parametrize(
    ("max_pixels", "size"),
    [
        (2, (3, 1)),
        (2, (5, 1)),
    ],
)
def test_rejects_pillow_decompression_bomb_warning_and_error(
    monkeypatch: pytest.MonkeyPatch,
    max_pixels: int,
    size: tuple[int, int],
) -> None:
    content = _encode_image("PNG", size=size)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", max_pixels)

    _assert_rejected(
        [
            _input(
                file_name="bomb.png",
                media_type="image/png",
                content=content,
            )
        ],
        code="decompression_bomb",
        ordinal=1,
    )


def test_failure_is_atomic_before_any_downstream_side_effect() -> None:
    module = _subject()
    effects: dict[str, list[object]] = {
        "bundle": [],
        "observation": [],
        "index": [],
        "success": [],
    }

    def downstream_pipeline(images: list[Any]) -> None:
        validated = module.validate_image_batch(images)
        effects["bundle"].append(validated)
        effects["observation"].append(validated)
        effects["index"].append(validated)
        effects["success"].append(validated)

    valid = _input()
    invalid = _input(
        file_name="second.png",
        media_type="image/png",
        content=b"not an image",
    )
    with pytest.raises(module.SafeImageInputError):
        downstream_pipeline([valid, invalid])

    assert effects == {
        "bundle": [],
        "observation": [],
        "index": [],
        "success": [],
    }
    assert tuple(inspect.signature(module.validate_image_batch).parameters) == (
        "images",
    )


def test_decodes_sequentially_and_closes_every_pillow_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _subject()
    real_open = module.Image.open
    active = 0
    maximum_active = 0
    close_count = 0

    class TrackedImage:
        def __init__(self, image: Image.Image) -> None:
            self.image = image

        def __enter__(self) -> Image.Image:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            return self.image

        def __exit__(self, *args: object) -> None:
            nonlocal active, close_count
            self.image.close()
            close_count += 1
            active -= 1

    def tracked_open(stream: BytesIO) -> TrackedImage:
        return TrackedImage(real_open(stream))

    monkeypatch.setattr(module.Image, "open", tracked_open)
    images = [
        _input(content=_encode_image("JPEG")),
        _input(content=_encode_image("JPEG")),
    ]

    module.validate_image_batch(images)

    assert maximum_active == 1
    assert active == 0
    assert close_count == 4


def test_closes_pillow_resource_when_decode_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _subject()
    closed = 0

    class FailingImage:
        format = "JPEG"
        size = (4, 3)
        n_frames = 1
        is_animated = False

        def __enter__(self) -> FailingImage:
            return self

        def __exit__(self, *args: object) -> None:
            nonlocal closed
            closed += 1

        def verify(self) -> None:
            raise OSError("corrupt stream")

    monkeypatch.setattr(module.Image, "open", lambda stream: FailingImage())

    _assert_rejected(
        [_input(content=_encode_image("JPEG"))],
        code="invalid_image_data",
        ordinal=1,
    )
    assert closed == 1


def test_input_and_output_models_are_strict_frozen_contracts() -> None:
    module = _subject()
    payload = {
        "file_name": "photo.jpg",
        "declared_media_type": "image/jpeg",
        "content": _encode_image("JPEG"),
    }

    with pytest.raises(ValidationError):
        module.UntrustedImageInput(**payload, unexpected=True)

    pending = module.UntrustedImageInput(**payload)
    validated = module.validate_image_batch([pending])[0]
    with pytest.raises(ValidationError):
        validated.ordinal = 2

    for contract in (
        module.UntrustedImageInput,
        module.ValidatedImageInput,
    ):
        assert contract.model_config["strict"] is True
        assert contract.model_config["extra"] == "forbid"
        assert contract.model_config["frozen"] is True
