from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

import pytest

from app.guide.adapters.state.in_memory_image_bundle_state import (
    InMemoryImageBundleState,
)
from app.guide.application.image_bundle_state import (
    ImageBundlePayload,
    ImageBundleCapacityExceeded,
    ImageBundleStateConflict,
)
from app.guide.understanding.contracts import (
    ImageBundle,
    ImageObservation,
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


_PAYLOAD_CONTENT = b"stored-image-payload"


def _bundle(
    clock: Clock,
    *,
    suffix: str = "a" * 32,
    version: int = 1,
    content: bytes = _PAYLOAD_CONTENT,
) -> ImageBundle:
    return ImageBundle(
        bundle_id=f"bundle_{suffix}",
        session_id=f"session-{suffix[:8]}",
        owner_token_sha256="b" * 64,
        version=version,
        created_at=clock.now,
        expires_at=clock.now + timedelta(seconds=60),
        images=[
            ImageObservation(
                image_id=f"image_{suffix}",
                ordinal=1,
                content_sha256=hashlib.sha256(content).hexdigest(),
                media_type="image/jpeg",
                image_format="JPEG",
                width=4,
                height=3,
                byte_size=len(content),
            )
        ],
    )


def _payloads(
    bundle: ImageBundle,
    *,
    content: bytes = _PAYLOAD_CONTENT,
) -> tuple[ImageBundlePayload, ...]:
    image = bundle.images[0]
    return (
        ImageBundlePayload(
            image_id=image.image_id,
            ordinal=image.ordinal,
            content_sha256=image.content_sha256,
            byte_size=image.byte_size,
            content=content,
        ),
    )


def _create(
    state: InMemoryImageBundleState,
    bundle: ImageBundle,
) -> ImageBundle:
    return state.create(bundle, payloads=_payloads(bundle))


def test_create_and_load_return_deep_copies() -> None:
    clock = Clock()
    state = InMemoryImageBundleState(max_bundles=2, clock=clock)
    original = _bundle(clock)

    created = _create(state, original)
    original.images[0].width = 99
    created.images[0].height = 99
    loaded = state.load(original.bundle_id)

    assert loaded is not None
    assert loaded.images[0].width == 4
    assert loaded.images[0].height == 3
    loaded.images[0].width = 77
    assert state.load(original.bundle_id).images[0].width == 4


def test_create_rejects_duplicate_id_and_capacity_without_eviction() -> None:
    clock = Clock()
    state = InMemoryImageBundleState(max_bundles=1, clock=clock)
    first = _bundle(clock)
    _create(state, first)

    with pytest.raises(ImageBundleStateConflict):
        _create(state, first)
    with pytest.raises(ImageBundleCapacityExceeded):
        candidate = _bundle(clock, suffix="d" * 32)
        _create(state, candidate)

    assert state.load(first.bundle_id) is not None


def test_save_requires_cas_and_single_version_increment() -> None:
    clock = Clock()
    state = InMemoryImageBundleState(max_bundles=2, clock=clock)
    original = _bundle(clock)
    _create(state, original)
    updated = original.model_copy(
        update={"version": 2},
        deep=True,
    )

    saved = state.save(updated, expected_version=1)

    assert saved.version == 2
    assert state.load(original.bundle_id).version == 2
    with pytest.raises(ImageBundleStateConflict):
        state.save(
            updated.model_copy(update={"version": 3}, deep=True),
            expected_version=1,
        )
    with pytest.raises(ValueError, match="increment"):
        state.save(
            updated.model_copy(update={"version": 4}, deep=True),
            expected_version=2,
        )


def test_save_round_trips_explicit_image_focus_without_inference() -> None:
    clock = Clock()
    state = InMemoryImageBundleState(max_bundles=2, clock=clock)
    original = _bundle(clock)
    created = _create(state, original)

    assert created.focused_image_ordinal is None

    focused = state.save(
        original.model_copy(
            update={
                "version": 2,
                "focused_image_ordinal": 1,
            },
            deep=True,
        ),
        expected_version=1,
    )

    assert focused.focused_image_ordinal == 1
    assert state.load(original.bundle_id).focused_image_ordinal == 1


def test_save_cannot_change_ownership_or_absolute_expiration() -> None:
    clock = Clock()
    state = InMemoryImageBundleState(max_bundles=2, clock=clock)
    original = _bundle(clock)
    _create(state, original)

    for update in (
        {"version": 2, "session_id": "session-foreign"},
        {"version": 2, "owner_token_sha256": "d" * 64},
        {
            "version": 2,
            "expires_at": original.expires_at + timedelta(seconds=60),
        },
        {
            "version": 2,
            "created_at": original.created_at + timedelta(seconds=1),
        },
    ):
        with pytest.raises(ValueError, match="immutable"):
            state.save(
                original.model_copy(update=update, deep=True),
                expected_version=1,
            )


def test_expiration_is_absolute_and_reads_do_not_refresh_it() -> None:
    clock = Clock()
    state = InMemoryImageBundleState(max_bundles=1, clock=clock)
    bundle = _bundle(clock)
    _create(state, bundle)

    clock.advance(59)
    assert state.load(bundle.bundle_id) is not None
    clock.advance(1)

    assert state.load(bundle.bundle_id) is None
    replacement = _bundle(clock, suffix="e" * 32)
    assert _create(state, replacement).bundle_id == replacement.bundle_id


def test_delete_uses_cas_and_keeps_tombstone_until_expiration() -> None:
    clock = Clock()
    state = InMemoryImageBundleState(max_bundles=1, clock=clock)
    bundle = _bundle(clock)
    _create(state, bundle)

    assert state.delete(bundle.bundle_id, expected_version=2) is False
    assert state.load(bundle.bundle_id) is not None
    assert state.delete(bundle.bundle_id, expected_version=1) is True
    assert state.load(bundle.bundle_id) is None
    assert state.delete(bundle.bundle_id, expected_version=1) is False
    with pytest.raises(ImageBundleCapacityExceeded):
        candidate = _bundle(clock, suffix="f" * 32)
        _create(state, candidate)

    clock.advance(60)
    replacement = _bundle(clock, suffix="f" * 32)
    assert _create(state, replacement).bundle_id == replacement.bundle_id


def test_invalid_constructor_limits_are_rejected() -> None:
    with pytest.raises(ValueError, match="max_bundles"):
        InMemoryImageBundleState(max_bundles=0)


def test_payload_capacity_is_atomic_and_delete_reclaims_bytes() -> None:
    clock = Clock()
    content = b"0123456789"
    state = InMemoryImageBundleState(
        max_bundles=3,
        max_payload_bytes=len(content),
        clock=clock,
    )
    first = _bundle(clock, content=content)
    state.create(
        first,
        payloads=_payloads(first, content=content),
    )
    second = _bundle(
        clock,
        suffix="d" * 32,
        content=content,
    )

    with pytest.raises(ImageBundleCapacityExceeded):
        state.create(
            second,
            payloads=_payloads(second, content=content),
        )
    assert state.load(second.bundle_id) is None

    assert state.delete(first.bundle_id, expected_version=1) is True
    assert state.create(
        second,
        payloads=_payloads(second, content=content),
    ).bundle_id == second.bundle_id
