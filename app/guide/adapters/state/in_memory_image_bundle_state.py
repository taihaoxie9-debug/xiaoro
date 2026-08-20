from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock

from app.guide.application.image_bundle_state import (
    ImageBundlePayload,
    ImageBundleCapacityExceeded,
    ImageBundleStateConflict,
    ImageBundleStateCorrupt,
    validated_bundle_payloads,
)
from app.guide.understanding.contracts import ImageBundle


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class _Entry:
    bundle: ImageBundle
    payloads: tuple[ImageBundlePayload, ...]
    deleted: bool = False


class InMemoryImageBundleState:
    def __init__(
        self,
        *,
        max_bundles: int = 512,
        max_payload_bytes: int = 512 * 1024 * 1024,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_bundles <= 0:
            raise ValueError("max_bundles must be positive")
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        self._max_bundles = max_bundles
        self._max_payload_bytes = max_payload_bytes
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = RLock()

    def create(
        self,
        bundle: ImageBundle,
        *,
        payloads: Sequence[ImageBundlePayload],
    ) -> ImageBundle:
        stored_payloads = validated_bundle_payloads(bundle, payloads)
        with self._lock:
            now = self._now()
            self._purge_expired(now)
            if bundle.expires_at <= now:
                raise ValueError("bundle must not already be expired")
            if bundle.bundle_id in self._entries:
                raise ImageBundleStateConflict(bundle.bundle_id)
            if len(self._entries) >= self._max_bundles:
                raise ImageBundleCapacityExceeded("image bundle capacity")
            used_payload_bytes = sum(
                payload.byte_size
                for entry in self._entries.values()
                for payload in entry.payloads
            )
            incoming_payload_bytes = sum(
                payload.byte_size for payload in stored_payloads
            )
            if (
                used_payload_bytes + incoming_payload_bytes
                > self._max_payload_bytes
            ):
                raise ImageBundleCapacityExceeded(
                    "image bundle payload capacity"
                )
            stored = bundle.model_copy(deep=True)
            self._entries[bundle.bundle_id] = _Entry(
                bundle=stored,
                payloads=stored_payloads,
            )
            return stored.model_copy(deep=True)

    def load(self, bundle_id: str) -> ImageBundle | None:
        with self._lock:
            now = self._now()
            self._purge_expired(now)
            entry = self._entries.get(bundle_id)
            if entry is None or entry.deleted:
                return None
            return entry.bundle.model_copy(deep=True)

    def load_payloads(
        self,
        bundle_id: str,
    ) -> tuple[ImageBundlePayload, ...] | None:
        record = self.load_bundle_payloads(bundle_id)
        return record[1] if record is not None else None

    def load_bundle_payloads(
        self,
        bundle_id: str,
    ) -> tuple[ImageBundle, tuple[ImageBundlePayload, ...]] | None:
        with self._lock:
            now = self._now()
            self._purge_expired(now)
            entry = self._entries.get(bundle_id)
            if entry is None or entry.deleted:
                return None
            try:
                payloads = validated_bundle_payloads(
                    entry.bundle,
                    entry.payloads,
                )
            except ValueError:
                raise ImageBundleStateCorrupt(bundle_id) from None
            return entry.bundle.model_copy(deep=True), payloads

    def save(
        self,
        bundle: ImageBundle,
        *,
        expected_version: int,
    ) -> ImageBundle:
        with self._lock:
            now = self._now()
            self._purge_expired(now)
            current = self._entries.get(bundle.bundle_id)
            if (
                current is None
                or current.deleted
                or current.bundle.version != expected_version
            ):
                raise ImageBundleStateConflict(bundle.bundle_id)
            if bundle.version != expected_version + 1:
                raise ValueError("bundle version must increment by one")
            self._validate_immutable_fields(current.bundle, bundle)
            stored = bundle.model_copy(deep=True)
            current.bundle = stored
            return stored.model_copy(deep=True)

    def delete(
        self,
        bundle_id: str,
        *,
        expected_version: int,
    ) -> bool:
        with self._lock:
            now = self._now()
            self._purge_expired(now)
            entry = self._entries.get(bundle_id)
            if (
                entry is None
                or entry.deleted
                or entry.bundle.version != expected_version
            ):
                return False
            entry.deleted = True
            entry.payloads = ()
            return True

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now

    def _purge_expired(self, now: datetime) -> None:
        expired = [
            bundle_id
            for bundle_id, entry in self._entries.items()
            if now >= entry.bundle.expires_at
        ]
        for bundle_id in expired:
            del self._entries[bundle_id]

    @staticmethod
    def _validate_immutable_fields(
        current: ImageBundle,
        replacement: ImageBundle,
    ) -> None:
        immutable = (
            "bundle_id",
            "session_id",
            "owner_token_sha256",
            "created_at",
            "expires_at",
            "images",
        )
        if any(
            getattr(current, field) != getattr(replacement, field)
            for field in immutable
        ):
            raise ValueError("bundle ownership and lifetime are immutable")
