from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
import os
from pathlib import Path
import sqlite3
import stat

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


class SqliteImageBundleState:
    """Single-host, cross-process image bundle state."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        max_bundles: int = 512,
        max_payload_bytes: int = 512 * 1024 * 1024,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_bundles <= 0:
            raise ValueError("max_bundles must be positive")
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        self._database_path = Path(database_path).expanduser().absolute()
        self._max_bundles = max_bundles
        self._max_payload_bytes = max_payload_bytes
        self._clock = clock
        self._prepare_storage()
        self._initialize_schema()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def create(
        self,
        bundle: ImageBundle,
        *,
        payloads: Sequence[ImageBundlePayload],
    ) -> ImageBundle:
        now = self._now()
        if bundle.expires_at <= now:
            raise ValueError("bundle must not already be expired")
        stored = bundle.model_copy(deep=True)
        stored_payloads = validated_bundle_payloads(
            stored,
            payloads,
        )
        with self._transaction() as connection:
            self._purge_expired(connection, now)
            duplicate = connection.execute(
                """
                SELECT 1
                FROM image_bundles
                WHERE bundle_id = ?
                """,
                (stored.bundle_id,),
            ).fetchone()
            if duplicate is not None:
                raise ImageBundleStateConflict(stored.bundle_id)
            count = connection.execute(
                "SELECT COUNT(*) FROM image_bundles"
            ).fetchone()[0]
            if count >= self._max_bundles:
                raise ImageBundleCapacityExceeded(
                    "image bundle capacity"
                )
            used_payload_bytes = connection.execute(
                """
                SELECT COALESCE(SUM(byte_size), 0)
                FROM image_bundle_payloads
                """
            ).fetchone()[0]
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
            try:
                connection.execute(
                    """
                    INSERT INTO image_bundles (
                        bundle_id,
                        owner_token_sha256,
                        version,
                        expires_at,
                        deleted,
                        bundle_json
                    )
                    VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (
                        stored.bundle_id,
                        stored.owner_token_sha256,
                        stored.version,
                        stored.expires_at.timestamp(),
                        stored.model_dump_json(),
                    ),
                )
            except sqlite3.IntegrityError:
                raise ImageBundleStateConflict(
                    stored.bundle_id
                ) from None
            connection.executemany(
                """
                INSERT INTO image_bundle_payloads (
                    bundle_id,
                    image_id,
                    ordinal,
                    content_sha256,
                    byte_size,
                    content
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        stored.bundle_id,
                        payload.image_id,
                        payload.ordinal,
                        payload.content_sha256,
                        payload.byte_size,
                        payload.content,
                    )
                    for payload in stored_payloads
                ),
            )
        return stored.model_copy(deep=True)

    def load(self, bundle_id: str) -> ImageBundle | None:
        now = self._now()
        with self._transaction() as connection:
            self._purge_expired(connection, now)
            row = connection.execute(
                """
                SELECT bundle_json
                FROM image_bundles
                WHERE bundle_id = ? AND deleted = 0
                """,
                (bundle_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return ImageBundle.model_validate_json(row[0]).model_copy(
                deep=True
            )
        except (TypeError, ValueError):
            raise ImageBundleStateCorrupt(bundle_id) from None

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
        now = self._now()
        with self._transaction() as connection:
            self._purge_expired(connection, now)
            bundle_row = connection.execute(
                """
                SELECT bundle_json
                FROM image_bundles
                WHERE bundle_id = ? AND deleted = 0
                """,
                (bundle_id,),
            ).fetchone()
            if bundle_row is None:
                return None
            payload_rows = connection.execute(
                """
                SELECT
                    image_id,
                    ordinal,
                    content_sha256,
                    byte_size,
                    content
                FROM image_bundle_payloads
                WHERE bundle_id = ?
                ORDER BY ordinal ASC
                """,
                (bundle_id,),
            ).fetchall()
        try:
            bundle = ImageBundle.model_validate_json(bundle_row[0])
            payloads = tuple(
                ImageBundlePayload(
                    image_id=row[0],
                    ordinal=row[1],
                    content_sha256=row[2],
                    byte_size=row[3],
                    content=bytes(row[4]),
                )
                for row in payload_rows
            )
            return (
                bundle.model_copy(deep=True),
                validated_bundle_payloads(bundle, payloads),
            )
        except (TypeError, ValueError):
            raise ImageBundleStateCorrupt(bundle_id) from None

    def save(
        self,
        bundle: ImageBundle,
        *,
        expected_version: int,
    ) -> ImageBundle:
        now = self._now()
        with self._transaction() as connection:
            self._purge_expired(connection, now)
            row = connection.execute(
                """
                SELECT version, bundle_json
                FROM image_bundles
                WHERE bundle_id = ? AND deleted = 0
                """,
                (bundle.bundle_id,),
            ).fetchone()
            if row is None or row[0] != expected_version:
                raise ImageBundleStateConflict(bundle.bundle_id)
            if bundle.version != expected_version + 1:
                raise ValueError("bundle version must increment by one")
            current = ImageBundle.model_validate_json(row[1])
            self._validate_immutable_fields(current, bundle)
            stored = bundle.model_copy(deep=True)
            cursor = connection.execute(
                """
                UPDATE image_bundles
                SET version = ?, bundle_json = ?
                WHERE bundle_id = ?
                  AND version = ?
                  AND deleted = 0
                """,
                (
                    stored.version,
                    stored.model_dump_json(),
                    stored.bundle_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ImageBundleStateConflict(stored.bundle_id)
        return stored.model_copy(deep=True)

    def delete(
        self,
        bundle_id: str,
        *,
        expected_version: int,
    ) -> bool:
        now = self._now()
        with self._transaction() as connection:
            self._purge_expired(connection, now)
            cursor = connection.execute(
                """
                UPDATE image_bundles
                SET deleted = 1
                WHERE bundle_id = ?
                  AND version = ?
                  AND deleted = 0
                """,
                (bundle_id, expected_version),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    DELETE FROM image_bundle_payloads
                    WHERE bundle_id = ?
                    """,
                    (bundle_id,),
                )
            return cursor.rowcount == 1

    def _prepare_storage(self) -> None:
        directory = self._database_path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = directory.lstat()
        if stat.S_ISLNK(directory_stat.st_mode):
            raise ValueError("state directory must not be a symlink")
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ValueError("state directory must be a directory")
        if directory_stat.st_uid != os.getuid():
            raise PermissionError(
                "state directory must be owned by the current user"
            )
        os.chmod(directory, 0o700)

        if self._database_path.exists():
            database_stat = self._database_path.lstat()
            if stat.S_ISLNK(database_stat.st_mode):
                raise ValueError("state database must not be a symlink")
            if not stat.S_ISREG(database_stat.st_mode):
                raise ValueError("state database must be a regular file")
            if database_stat.st_uid != os.getuid():
                raise PermissionError(
                    "state database must be owned by the current user"
                )

    def _initialize_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS image_bundles (
                    bundle_id TEXT PRIMARY KEY,
                    owner_token_sha256 TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version >= 1),
                    expires_at REAL NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                        CHECK (deleted IN (0, 1)),
                    bundle_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    image_bundles_expires_at_idx
                ON image_bundles (expires_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS image_bundle_payloads (
                    bundle_id TEXT NOT NULL,
                    image_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK (
                        ordinal BETWEEN 1 AND 4
                    ),
                    content_sha256 TEXT NOT NULL CHECK (
                        length(content_sha256) = 64
                    ),
                    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
                    content BLOB NOT NULL,
                    PRIMARY KEY (bundle_id, image_id),
                    UNIQUE (bundle_id, ordinal),
                    FOREIGN KEY (bundle_id)
                        REFERENCES image_bundles (bundle_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.commit()
        finally:
            connection.close()
        self._secure_database_files()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._secure_database_files()

    def _secure_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{self._database_path}{suffix}")
            if path.exists():
                path_stat = path.lstat()
                if stat.S_ISLNK(path_stat.st_mode):
                    raise ValueError(
                        "state database files must not be symlinks"
                    )
                if path_stat.st_uid != os.getuid():
                    raise PermissionError(
                        "state database files must be owned by current user"
                    )
                os.chmod(path, 0o600)

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now

    @staticmethod
    def _purge_expired(
        connection: sqlite3.Connection,
        now: datetime,
    ) -> None:
        connection.execute(
            "DELETE FROM image_bundles WHERE expires_at <= ?",
            (now.timestamp(),),
        )

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
