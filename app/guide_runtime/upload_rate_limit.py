"""Single-host, cross-process image upload rate-limit state."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import stat
import time


class ImageUploadRateStateError(RuntimeError):
    """The private rate-limit state cannot be used safely."""


class SqliteImageUploadRateLimiter:
    """Atomic fixed-window limiter backed by a bounded SQLite registry."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        limit: int,
        window_seconds: float,
        entry_ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("window_seconds must be finite and positive")
        if (
            not math.isfinite(entry_ttl_seconds)
            or entry_ttl_seconds < window_seconds
        ):
            raise ValueError(
                "entry_ttl_seconds must cover at least one window"
            )
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")

        raw_path = Path(database_path).expanduser()
        if not raw_path.is_absolute():
            raise ValueError("rate state database path must be absolute")
        self._database_path = raw_path
        self._limit = limit
        self._window_seconds = window_seconds
        self._entry_ttl_seconds = entry_ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        try:
            self._prepare_storage()
            self._initialize_schema()
        except (OSError, sqlite3.Error, ValueError) as error:
            raise ImageUploadRateStateError(
                "image upload rate state unavailable"
            ) from error

    @property
    def database_path(self) -> Path:
        return self._database_path

    def consume(self, client_key: str) -> bool:
        now = float(self._clock())
        if not math.isfinite(now) or now < 0:
            raise ValueError("clock must return a finite non-negative value")
        client_key_sha256 = hashlib.sha256(
            client_key.encode("utf-8")
        ).hexdigest()
        window_id = math.floor(now / self._window_seconds)

        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    DELETE FROM image_upload_rate_windows
                    WHERE last_seen_at <= ? OR window_id < ?
                    """,
                    (
                        now - self._entry_ttl_seconds,
                        window_id,
                    ),
                )
                row = connection.execute(
                    """
                    SELECT window_id, request_count
                    FROM image_upload_rate_windows
                    WHERE client_key_sha256 = ?
                    """,
                    (client_key_sha256,),
                ).fetchone()

                if row is not None:
                    if row[0] > window_id:
                        return False
                    if row[0] == window_id and row[1] >= self._limit:
                        return False
                    request_count = (
                        row[1] + 1 if row[0] == window_id else 1
                    )
                    connection.execute(
                        """
                        UPDATE image_upload_rate_windows
                        SET window_id = ?,
                            request_count = ?,
                            last_seen_at = ?
                        WHERE client_key_sha256 = ?
                        """,
                        (
                            window_id,
                            request_count,
                            now,
                            client_key_sha256,
                        ),
                    )
                    return True

                count = connection.execute(
                    "SELECT COUNT(*) FROM image_upload_rate_windows"
                ).fetchone()[0]
                if count >= self._max_entries:
                    return False
                connection.execute(
                    """
                    INSERT INTO image_upload_rate_windows (
                        client_key_sha256,
                        window_id,
                        request_count,
                        last_seen_at
                    )
                    VALUES (?, ?, 1, ?)
                    """,
                    (client_key_sha256, window_id, now),
                )
                return True
        except (OSError, sqlite3.Error) as error:
            raise ImageUploadRateStateError(
                "image upload rate state unavailable"
            ) from error

    def _prepare_storage(self) -> None:
        directory = self._database_path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = directory.lstat()
        if stat.S_ISLNK(directory_stat.st_mode):
            raise ValueError("rate state directory must not be a symlink")
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ValueError("rate state directory must be a directory")
        if directory_stat.st_uid != os.getuid():
            raise PermissionError(
                "rate state directory must be owned by current user"
            )
        if stat.S_IMODE(directory_stat.st_mode) != 0o700:
            raise PermissionError("rate state directory must be private")

        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self._database_path, flags, 0o600)
        except FileExistsError:
            self._validate_database_file()
        else:
            try:
                os.fchmod(descriptor, 0o600)
            finally:
                os.close(descriptor)

    def _validate_database_file(self) -> None:
        database_stat = self._database_path.lstat()
        if stat.S_ISLNK(database_stat.st_mode):
            raise ValueError("rate state database must not be a symlink")
        if not stat.S_ISREG(database_stat.st_mode):
            raise ValueError(
                "rate state database must be a regular file"
            )
        if database_stat.st_uid != os.getuid():
            raise PermissionError(
                "rate state database must be owned by current user"
            )
        if stat.S_IMODE(database_stat.st_mode) & 0o077:
            raise PermissionError("rate state database must be private")

    def _initialize_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS image_upload_rate_windows (
                    client_key_sha256 TEXT PRIMARY KEY
                        CHECK (length(client_key_sha256) = 64),
                    window_id INTEGER NOT NULL,
                    request_count INTEGER NOT NULL
                        CHECK (request_count >= 1),
                    last_seen_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    image_upload_rate_last_seen_idx
                ON image_upload_rate_windows (last_seen_at)
                """
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._secure_database_files()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA trusted_schema = OFF")
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
            if not path.exists():
                continue
            path_stat = path.lstat()
            if stat.S_ISLNK(path_stat.st_mode):
                raise ImageUploadRateStateError(
                    "rate state database files must not be symlinks"
                )
            if not stat.S_ISREG(path_stat.st_mode):
                raise ImageUploadRateStateError(
                    "rate state database files must be regular files"
                )
            if path_stat.st_uid != os.getuid():
                raise ImageUploadRateStateError(
                    "rate state database files have an invalid owner"
                )
            os.chmod(path, 0o600)
