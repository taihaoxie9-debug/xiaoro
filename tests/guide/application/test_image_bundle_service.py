from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image

from app.guide.adapters.image.safe_image_input import UntrustedImageInput
from app.guide.adapters.state.in_memory_image_bundle_state import (
    InMemoryImageBundleState,
)
from app.guide.application.contracts import (
    ImageErrorCode,
    PublicImageError,
)
from app.guide.application.image_bundle_service import (
    ImageBundleService,
    ImageBundleServiceError,
)
from app.guide.application.image_bundle_state import ImageBundleStateCorrupt


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _jpeg(*, color: tuple[int, int, int] = (23, 67, 101)) -> bytes:
    image = Image.new("RGB", (4, 3), color=color)
    output = BytesIO()
    image.save(output, format="JPEG")
    image.close()
    return output.getvalue()


def _image(
    *,
    name: str = "product.jpg",
    content: bytes | None = None,
) -> UntrustedImageInput:
    return UntrustedImageInput(
        file_name=name,
        declared_media_type="image/jpeg",
        content=content or _jpeg(),
    )


def _service(
    *,
    clock: Clock | None = None,
    max_bundles: int = 8,
) -> tuple[ImageBundleService, InMemoryImageBundleState, Clock]:
    active_clock = clock or Clock()
    state = InMemoryImageBundleState(
        max_bundles=max_bundles,
        clock=active_clock,
    )
    service = ImageBundleService(
        state=state,
        ttl_seconds=300,
        clock=active_clock,
    )
    return service, state, active_clock


def _assert_unavailable(
    service: ImageBundleService,
    **overrides: object,
) -> None:
    arguments = {
        "bundle_id": "bundle_unknown-token-value-with-entropy",
        "version": 1,
        "session_id": "session-attacker",
        "owner_token": "owner_attacker-token-value-with-entropy",
    }
    arguments.update(overrides)

    with pytest.raises(ImageBundleServiceError) as caught:
        service.authorize(**arguments)

    assert caught.value.error == PublicImageError(
        code=ImageErrorCode.IMAGE_BUNDLE_UNAVAILABLE,
        message="图片引用不可用，请重新上传。",
        ordinal=None,
    )
    assert arguments["owner_token"] not in str(caught.value)
    assert arguments["owner_token"] not in repr(caught.value)


def test_create_uses_opaque_ids_and_stores_only_owner_token_sha256() -> None:
    service, state, clock = _service()
    first = _jpeg()
    second = _jpeg(color=(151, 113, 71))

    receipt = service.create(
        session_id="session-owner",
        images=[
            _image(name="first.jpg", content=first),
            _image(name="second.jpeg", content=second),
        ],
    )
    stored = state.load(receipt.bundle_id)

    assert stored is not None
    assert receipt.bundle_id.startswith("bundle_")
    assert len(receipt.bundle_id) >= 39
    assert receipt.version == 1
    assert receipt.image_count == 2
    assert receipt.expires_at == clock.now + timedelta(seconds=300)
    assert receipt.message == "图片已安全接收，发送后将进行单图相似检索。"
    assert receipt.owner_token.startswith("owner_")
    assert len(receipt.owner_token) >= 49
    assert stored.bundle_id == receipt.bundle_id
    assert stored.session_id == "session-owner"
    assert stored.owner_token_sha256 == hashlib.sha256(
        receipt.owner_token.encode("utf-8")
    ).hexdigest()
    assert stored.version == 1
    assert stored.created_at == clock.now
    assert stored.expires_at == receipt.expires_at
    assert [item.ordinal for item in stored.images] == [1, 2]
    assert all(item.image_id.startswith("image_") for item in stored.images)
    assert len({item.image_id for item in stored.images}) == 2
    assert stored.images[0].width == 4
    assert stored.images[0].height == 3
    assert stored.images[0].byte_size == len(first)
    assert stored.images[0].content_sha256 == hashlib.sha256(first).hexdigest()
    assert stored.images[0].media_type == "image/jpeg"
    assert stored.images[0].image_format == "JPEG"
    assert receipt.owner_token not in repr(stored)
    assert receipt.owner_token not in repr(state.__dict__)


def test_ids_and_tokens_are_unique_across_many_creations() -> None:
    service, _, _ = _service(max_bundles=256)

    receipts = [
        service.create(
            session_id=f"session-{index}",
            images=[_image()],
        )
        for index in range(128)
    ]

    assert len({item.bundle_id for item in receipts}) == len(receipts)
    assert len({item.owner_token for item in receipts}) == len(receipts)


def test_authorize_uses_constant_time_hash_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, _ = _service()
    receipt = service.create(
        session_id="session-owner",
        images=[_image()],
    )
    calls: list[tuple[str, str]] = []

    from app.guide.application import image_bundle_service as subject

    real_compare = subject.hmac.compare_digest

    def recording_compare(left: str, right: str) -> bool:
        calls.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(subject.hmac, "compare_digest", recording_compare)

    bundle = service.authorize(
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )

    assert bundle.bundle_id == receipt.bundle_id
    assert calls == [
        (
            bundle.owner_token_sha256,
            hashlib.sha256(
                receipt.owner_token.encode("utf-8")
            ).hexdigest(),
        )
    ]


def test_unknown_foreign_wrong_token_and_stale_version_are_indistinguishable(
) -> None:
    service, _, _ = _service()
    receipt = service.create(
        session_id="session-owner",
        images=[_image()],
    )

    _assert_unavailable(service)
    _assert_unavailable(
        service,
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="session-foreign",
        owner_token=receipt.owner_token,
    )
    _assert_unavailable(
        service,
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="session-owner",
        owner_token="owner_wrong-token-value-with-entropy",
    )
    _assert_unavailable(
        service,
        bundle_id=receipt.bundle_id,
        version=receipt.version + 1,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )


def test_authorize_maps_corrupt_state_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, state, _ = _service()

    def raise_corrupt(bundle_id: str):
        raise ImageBundleStateCorrupt(bundle_id)

    monkeypatch.setattr(state, "load", raise_corrupt)

    with pytest.raises(ImageBundleServiceError) as caught:
        service.authorize(
            bundle_id="bundle_corrupt-state-value-with-entropy",
            version=1,
            session_id="session-owner",
            owner_token="owner_owner-token-value-with-entropy",
        )

    assert caught.value.error == PublicImageError(
        code=ImageErrorCode.IMAGE_BUNDLE_UNAVAILABLE,
        message="图片引用不可用，请重新上传。",
        ordinal=None,
    )


def test_delete_maps_corrupt_state_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, state, _ = _service()

    def raise_corrupt(bundle_id: str):
        raise ImageBundleStateCorrupt(bundle_id)

    monkeypatch.setattr(state, "load", raise_corrupt)

    with pytest.raises(ImageBundleServiceError) as caught:
        service.delete(
            bundle_id="bundle_corrupt-state-value-with-entropy",
            version=1,
            session_id="session-owner",
            owner_token="owner_owner-token-value-with-entropy",
        )

    assert caught.value.error == PublicImageError(
        code=ImageErrorCode.IMAGE_BUNDLE_UNAVAILABLE,
        message="图片引用不可用，请重新上传。",
        ordinal=None,
    )


def test_absolute_ttl_is_not_extended_and_expires_at_exact_boundary() -> None:
    service, _, clock = _service()
    receipt = service.create(
        session_id="session-owner",
        images=[_image()],
    )

    clock.advance(299)
    service.authorize(
        bundle_id=receipt.bundle_id,
        version=1,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )
    clock.advance(1)

    _assert_unavailable(
        service,
        bundle_id=receipt.bundle_id,
        version=1,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )


def test_delete_makes_replay_fail_closed_without_leaking_token() -> None:
    service, state, _ = _service()
    receipt = service.create(
        session_id="session-owner",
        images=[_image()],
    )

    service.delete(
        bundle_id=receipt.bundle_id,
        version=1,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )

    assert state.load(receipt.bundle_id) is None
    _assert_unavailable(
        service,
        bundle_id=receipt.bundle_id,
        version=1,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )
    with pytest.raises(ImageBundleServiceError) as caught:
        service.delete(
            bundle_id=receipt.bundle_id,
            version=1,
            session_id="session-owner",
            owner_token=receipt.owner_token,
        )
    assert caught.value.error.code is ImageErrorCode.IMAGE_BUNDLE_UNAVAILABLE
    assert receipt.owner_token not in repr(caught.value)


def test_capacity_is_a_typed_public_error() -> None:
    service, _, _ = _service(max_bundles=1)
    first = service.create(
        session_id="session-one",
        images=[_image()],
    )
    service.delete(
        bundle_id=first.bundle_id,
        version=1,
        session_id="session-one",
        owner_token=first.owner_token,
    )

    with pytest.raises(ImageBundleServiceError) as caught:
        service.create(
            session_id="session-two",
            images=[_image()],
        )

    assert caught.value.error == PublicImageError(
        code=ImageErrorCode.IMAGE_BUNDLE_CAPACITY,
        message="图片服务繁忙，请稍后重试。",
        ordinal=None,
    )


def test_authorized_payloads_preserve_validated_bytes_and_order() -> None:
    service, _, _ = _service()
    first = _jpeg()
    second = _jpeg(color=(151, 113, 71))
    receipt = service.create(
        session_id="session-owner",
        images=[
            _image(name="first.jpg", content=first),
            _image(name="second.jpg", content=second),
        ],
    )

    payloads = service.authorize_payloads(
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )

    assert [payload.ordinal for payload in payloads] == [1, 2]
    assert [payload.content for payload in payloads] == [first, second]
    assert [payload.content_sha256 for payload in payloads] == [
        hashlib.sha256(first).hexdigest(),
        hashlib.sha256(second).hexdigest(),
    ]

    with pytest.raises(ImageBundleServiceError) as caught:
        service.authorize_payloads(
            bundle_id=receipt.bundle_id,
            version=receipt.version,
            session_id="session-owner",
            owner_token="owner_wrong-token-value-with-entropy",
        )
    assert caught.value.error.code is ImageErrorCode.IMAGE_BUNDLE_UNAVAILABLE


def test_authorized_bundle_and_payloads_share_one_authoritative_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, state, _ = _service()
    first = _jpeg()
    second = _jpeg(color=(151, 113, 71))
    receipt = service.create(
        session_id="session-owner",
        images=[
            _image(name="first.jpg", content=first),
            _image(name="second.jpg", content=second),
        ],
    )

    def reject_split_read(bundle_id: str):
        del bundle_id
        raise RuntimeError("split state read is not atomic")

    monkeypatch.setattr(state, "load", reject_split_read)
    monkeypatch.setattr(state, "load_payloads", reject_split_read)

    bundle, payloads = service.authorize_bundle_payloads(
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )

    assert bundle.bundle_id == receipt.bundle_id
    assert bundle.session_id == "session-owner"
    assert bundle.version == receipt.version
    assert [image.ordinal for image in bundle.images] == [1, 2]
    assert [payload.ordinal for payload in payloads] == [1, 2]
    assert [payload.content for payload in payloads] == [first, second]
    assert [
        (image.image_id, image.content_sha256)
        for image in bundle.images
    ] == [
        (payload.image_id, payload.content_sha256)
        for payload in payloads
    ]


def test_authorized_payloads_use_one_atomic_state_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, state, _ = _service()
    content = _jpeg()
    receipt = service.create(
        session_id="session-owner",
        images=[_image(content=content)],
    )

    def reject_split_metadata_read(bundle_id: str):
        del bundle_id
        raise RuntimeError("split metadata read is not atomic")

    monkeypatch.setattr(state, "load", reject_split_metadata_read)

    payloads = service.authorize_payloads(
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )

    assert len(payloads) == 1
    assert payloads[0].content == content
