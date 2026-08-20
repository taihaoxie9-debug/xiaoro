from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3

import pytest
from PIL import Image

from app.guide.adapters.image.safe_image_input import UntrustedImageInput
from app.guide.adapters.state.sqlite_image_bundle_state import (
    SqliteImageBundleState,
)
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide.application.image_bundle_state import (
    ImageBundlePayload,
    ImageBundleCapacityExceeded,
    ImageBundleStateConflict,
    ImageBundleStateCorrupt,
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
    state: SqliteImageBundleState,
    bundle: ImageBundle,
) -> ImageBundle:
    return state.create(bundle, payloads=_payloads(bundle))


def _payload_row_count(
    state: SqliteImageBundleState,
    bundle_id: str,
) -> int:
    with sqlite3.connect(state.database_path) as connection:
        return connection.execute(
            """
            SELECT COUNT(*)
            FROM image_bundle_payloads
            WHERE bundle_id = ?
            """,
            (bundle_id,),
        ).fetchone()[0]


def _jpeg() -> bytes:
    image = Image.new("RGB", (4, 3), color=(23, 67, 101))
    output = BytesIO()
    image.save(output, format="JPEG")
    image.close()
    return output.getvalue()


def _state(
    tmp_path: Path,
    clock: Clock,
    *,
    max_bundles: int = 2,
    max_payload_bytes: int = 512 * 1024 * 1024,
) -> SqliteImageBundleState:
    return SqliteImageBundleState(
        tmp_path / "state" / "image_bundles.sqlite3",
        max_bundles=max_bundles,
        max_payload_bytes=max_payload_bytes,
        clock=clock,
    )


def test_sqlite_create_and_load_return_deep_copies(
    tmp_path: Path,
) -> None:
    clock = Clock()
    state = _state(tmp_path, clock)
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


def test_sqlite_load_malformed_bundle_json_fails_closed(
    tmp_path: Path,
) -> None:
    clock = Clock()
    state = _state(tmp_path, clock)
    bundle = _bundle(clock)
    _create(state, bundle)
    with sqlite3.connect(state.database_path) as connection:
        connection.execute(
            """
            UPDATE image_bundles
            SET bundle_json = ?
            WHERE bundle_id = ?
            """,
            ("{malformed-json", bundle.bundle_id),
        )
        connection.commit()

    with pytest.raises(ImageBundleStateCorrupt):
        state.load(bundle.bundle_id)


def test_sqlite_save_is_cas_and_preserves_immutable_fields(
    tmp_path: Path,
) -> None:
    clock = Clock()
    state = _state(tmp_path, clock)
    original = _bundle(clock)
    _create(state, original)
    updated = original.model_copy(update={"version": 2}, deep=True)

    assert state.save(updated, expected_version=1).version == 2
    with pytest.raises(ImageBundleStateConflict):
        state.save(
            updated.model_copy(update={"version": 3}, deep=True),
            expected_version=1,
        )
    with pytest.raises(ValueError, match="immutable"):
        state.save(
            updated.model_copy(
                update={
                    "version": 3,
                    "session_id": "session-foreign",
                },
                deep=True,
            ),
            expected_version=2,
        )


def test_sqlite_round_trips_focus_and_loads_legacy_unfocused_row(
    tmp_path: Path,
) -> None:
    clock = Clock()
    state = _state(tmp_path, clock)
    original = _bundle(clock)
    _create(state, original)

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

    with sqlite3.connect(state.database_path) as connection:
        payload = json.loads(
            connection.execute(
                """
                SELECT bundle_json
                FROM image_bundles
                WHERE bundle_id = ?
                """,
                (original.bundle_id,),
            ).fetchone()[0]
        )
        del payload["focused_image_ordinal"]
        connection.execute(
            """
            UPDATE image_bundles
            SET bundle_json = ?
            WHERE bundle_id = ?
            """,
            (
                json.dumps(payload, ensure_ascii=False),
                original.bundle_id,
            ),
        )

    loaded = _state(tmp_path, clock).load(original.bundle_id)

    assert loaded is not None
    assert loaded.version == 2
    assert loaded.focused_image_ordinal is None


def test_sqlite_delete_tombstone_counts_until_absolute_ttl(
    tmp_path: Path,
) -> None:
    clock = Clock()
    state = _state(tmp_path, clock, max_bundles=1)
    first = _bundle(clock)
    _create(state, first)

    assert state.delete(first.bundle_id, expected_version=2) is False
    assert state.delete(first.bundle_id, expected_version=1) is True
    assert state.load(first.bundle_id) is None
    assert _payload_row_count(state, first.bundle_id) == 0
    assert state.delete(first.bundle_id, expected_version=1) is False
    with pytest.raises(ImageBundleCapacityExceeded):
        candidate = _bundle(clock, suffix="d" * 32)
        _create(state, candidate)

    clock.advance(60)
    replacement = _bundle(clock, suffix="d" * 32)
    assert _create(state, replacement).bundle_id == replacement.bundle_id


def test_sqlite_rejects_symlink_directory_and_database(
    tmp_path: Path,
) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(ValueError, match="directory.*symlink"):
        SqliteImageBundleState(
            linked_directory / "image_bundles.sqlite3"
        )

    private_directory = tmp_path / "private"
    private_directory.mkdir()
    target = tmp_path / "target.sqlite3"
    target.touch()
    linked_database = private_directory / "image_bundles.sqlite3"
    linked_database.symlink_to(target)
    with pytest.raises(ValueError, match="database.*symlink"):
        SqliteImageBundleState(linked_database)


def test_sqlite_payloads_are_atomic_and_visible_to_another_instance(
    tmp_path: Path,
) -> None:
    from app.guide.application import image_bundle_state as state_contract

    clock = Clock()
    state = _state(tmp_path, clock)
    content = b"validated-image-payload"
    digest = hashlib.sha256(content).hexdigest()
    bundle = _bundle(clock).model_copy(deep=True)
    bundle.images[0].content_sha256 = digest
    bundle.images[0].byte_size = len(content)
    payload_type = getattr(state_contract, "ImageBundlePayload")
    payload = payload_type(
        image_id=bundle.images[0].image_id,
        ordinal=1,
        content_sha256=digest,
        byte_size=len(content),
        content=content,
    )

    state.create(bundle, payloads=(payload,))

    other = _state(tmp_path, clock)
    loaded = other.load_payloads(bundle.bundle_id)
    assert loaded is not None
    assert loaded[0].image_id == bundle.images[0].image_id
    assert loaded[0].content == content
    assert loaded[0].content_sha256 == digest


def test_sqlite_payload_capacity_is_atomic_and_delete_reclaims_bytes(
    tmp_path: Path,
) -> None:
    clock = Clock()
    content = b"0123456789"
    state = _state(
        tmp_path,
        clock,
        max_bundles=3,
        max_payload_bytes=len(content),
    )
    first = _bundle(clock, content=content)
    state.create(first, payloads=_payloads(first, content=content))
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


def test_sqlite_payload_tampering_fails_closed(tmp_path: Path) -> None:
    clock = Clock()
    state = _state(tmp_path, clock)
    bundle = _bundle(clock)
    _create(state, bundle)
    with sqlite3.connect(state.database_path) as connection:
        connection.execute(
            """
            UPDATE image_bundle_payloads
            SET content = ?
            WHERE bundle_id = ?
            """,
            (b"tampered-image-data", bundle.bundle_id),
        )
        connection.commit()

    with pytest.raises(ImageBundleStateCorrupt):
        state.load_payloads(bundle.bundle_id)


def test_sqlite_mismatched_payload_rolls_back_bundle_create(
    tmp_path: Path,
) -> None:
    clock = Clock()
    state = _state(tmp_path, clock)
    bundle = _bundle(clock)
    foreign = _bundle(clock, suffix="d" * 32)

    with pytest.raises(ValueError, match="does not match"):
        state.create(bundle, payloads=_payloads(foreign))

    assert state.load(bundle.bundle_id) is None
    assert _payload_row_count(state, bundle.bundle_id) == 0


def test_sqlite_expiration_cascades_payload_rows(tmp_path: Path) -> None:
    clock = Clock()
    state = _state(tmp_path, clock)
    bundle = _bundle(clock)
    _create(state, bundle)
    assert _payload_row_count(state, bundle.bundle_id) == 1

    clock.advance(60)

    assert state.load_payloads(bundle.bundle_id) is None
    assert state.load(bundle.bundle_id) is None
    assert _payload_row_count(state, bundle.bundle_id) == 0


def test_sqlite_service_authorizes_payloads_across_instances(
    tmp_path: Path,
) -> None:
    clock = Clock()
    first = ImageBundleService(
        state=_state(tmp_path, clock),
        ttl_seconds=60,
        clock=clock,
    )
    content = _jpeg()
    receipt = first.create(
        session_id="session-owner",
        images=[
            UntrustedImageInput(
                file_name="product.jpg",
                declared_media_type="image/jpeg",
                content=content,
            )
        ],
    )
    second = ImageBundleService(
        state=_state(tmp_path, clock),
        ttl_seconds=60,
        clock=clock,
    )

    payloads = second.authorize_payloads(
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="session-owner",
        owner_token=receipt.owner_token,
    )

    assert len(payloads) == 1
    assert payloads[0].content == content
