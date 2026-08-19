from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import errno
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
from threading import Lock

from app.guide.feedback.event_contracts import (
    FeedbackEventRequest,
    RecordedFeedbackEvent,
)
from app.guide.feedback.event_ports import (
    FeedbackEventStoreCorrupt,
    FeedbackIdempotencyConflict,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef


_STATE_DIRECTORY_ENV = "XIAORO_GUIDE_STATE_DIR"
_DATABASE_FILE = "feedback_events.sqlite3"
_EXPECTED_COLUMNS = (
    ("owner_scope", "TEXT", True, 1),
    ("owner_subject_id", "TEXT", True, 2),
    ("idempotency_key", "TEXT", True, 3),
    ("event_id", "TEXT", True, 0),
    ("request_json", "TEXT", True, 0),
    ("event_json", "TEXT", True, 0),
)
_CORRUPT_MESSAGE = "feedback event store is invalid or unavailable"
_INITIALIZATION_LOCKS_GUARD = Lock()
_INITIALIZATION_LOCKS: dict[Path, Lock] = {}


def _thread_initialization_lock(database_path: Path) -> Lock:
    with _INITIALIZATION_LOCKS_GUARD:
        return _INITIALIZATION_LOCKS.setdefault(database_path, Lock())


class SqliteFeedbackEventStore:
    """Single-host, cross-process, append-only feedback event store."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
    ) -> None:
        self._database_path = Path(
            database_path
        ).expanduser().absolute()
        self._prepare_storage()
        try:
            with _thread_initialization_lock(self._database_path):
                directory_fd = os.open(
                    self._database_path.parent,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_CLOEXEC
                    | os.O_NOFOLLOW,
                )
                try:
                    fcntl.flock(directory_fd, fcntl.LOCK_EX)
                    self._initialize_schema()
                finally:
                    fcntl.flock(directory_fd, fcntl.LOCK_UN)
                    os.close(directory_fd)
        except sqlite3.Error:
            raise FeedbackEventStoreCorrupt(
                _CORRUPT_MESSAGE
            ) from None

    @classmethod
    def from_environment(cls) -> SqliteFeedbackEventStore:
        raw_directory = os.environ.get(_STATE_DIRECTORY_ENV)
        if not raw_directory:
            raise ValueError(
                f"{_STATE_DIRECTORY_ENV} must be configured"
            )
        directory = Path(raw_directory).expanduser()
        if not directory.is_absolute():
            raise ValueError(
                f"{_STATE_DIRECTORY_ENV} must be an absolute path"
            )
        return cls(directory / _DATABASE_FILE)

    @property
    def database_path(self) -> Path:
        return self._database_path

    def load(
        self,
        *,
        owner: ProfileOwnerRef,
        idempotency_key: str,
    ) -> RecordedFeedbackEvent | None:
        try:
            connection = self._connect()
            try:
                row = connection.execute(
                    """
                    SELECT request_json, event_json
                    FROM feedback_events
                    WHERE owner_scope = ?
                      AND owner_subject_id = ?
                      AND idempotency_key = ?
                    """,
                    (
                        owner.scope,
                        owner.subject_id,
                        idempotency_key,
                    ),
                ).fetchone()
            finally:
                connection.close()
        except sqlite3.Error:
            raise FeedbackEventStoreCorrupt(
                _CORRUPT_MESSAGE
            ) from None
        if row is None:
            return None
        return self._decode(
            row,
            owner=owner,
            idempotency_key=idempotency_key,
        )

    def record_once(
        self,
        event: RecordedFeedbackEvent,
    ) -> RecordedFeedbackEvent:
        try:
            return self._record_once(event)
        except sqlite3.Error:
            raise FeedbackEventStoreCorrupt(
                _CORRUPT_MESSAGE
            ) from None

    def _record_once(
        self,
        event: RecordedFeedbackEvent,
    ) -> RecordedFeedbackEvent:
        candidate = event.model_copy(deep=True)
        request = candidate.to_request()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT request_json, event_json
                FROM feedback_events
                WHERE owner_scope = ?
                  AND owner_subject_id = ?
                  AND idempotency_key = ?
                """,
                (
                    candidate.owner.scope,
                    candidate.owner.subject_id,
                    candidate.idempotency_key,
                ),
            ).fetchone()
            if row is not None:
                existing = self._decode(
                    row,
                    owner=candidate.owner,
                    idempotency_key=candidate.idempotency_key,
                )
                if existing.to_request() != request:
                    raise FeedbackIdempotencyConflict(
                        candidate.idempotency_key
                    )
                return existing.model_copy(deep=True)

            connection.execute(
                """
                INSERT INTO feedback_events (
                    owner_scope,
                    owner_subject_id,
                    idempotency_key,
                    event_id,
                    request_json,
                    event_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.owner.scope,
                    candidate.owner.subject_id,
                    candidate.idempotency_key,
                    candidate.event_id,
                    request.model_dump_json(),
                    candidate.model_dump_json(),
                ),
            )
        return candidate.model_copy(deep=True)

    def _prepare_storage(self) -> None:
        directory = self._database_path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            directory_fd = os.open(directory, directory_flags)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise ValueError(
                    "state directory must be a directory, not a symlink"
                ) from None
            raise
        try:
            directory_stat = os.fstat(directory_fd)
            if not stat.S_ISDIR(directory_stat.st_mode):
                raise ValueError("state directory must be a directory")
            if directory_stat.st_uid != os.getuid():
                raise PermissionError(
                    "state directory must be owned by the current user"
                )
            os.fchmod(directory_fd, 0o700)

            database_flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_CLOEXEC
                | os.O_NOFOLLOW
            )
            try:
                database_fd = os.open(
                    self._database_path,
                    database_flags,
                    0o600,
                )
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.EISDIR}:
                    raise ValueError(
                        "state database must be a regular file, not a symlink"
                    ) from None
                raise
            try:
                database_stat = os.fstat(database_fd)
                if not stat.S_ISREG(database_stat.st_mode):
                    raise ValueError(
                        "state database must be a regular file"
                    )
                if database_stat.st_uid != os.getuid():
                    raise PermissionError(
                        "state database must be owned by the current user"
                    )
                os.fchmod(database_fd, 0o600)
            finally:
                os.close(database_fd)
        finally:
            os.close(directory_fd)

    def _initialize_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_events (
                    owner_scope TEXT NOT NULL,
                    owner_subject_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    PRIMARY KEY (
                        owner_scope,
                        owner_subject_id,
                        idempotency_key
                    )
                )
                """
            )
            columns = connection.execute(
                "PRAGMA table_info(feedback_events)"
            ).fetchall()
            actual_columns = tuple(
                (
                    str(row[1]),
                    str(row[2]).upper(),
                    bool(row[3]),
                    int(row[5]),
                )
                for row in columns
            )
            if actual_columns != _EXPECTED_COLUMNS:
                raise FeedbackEventStoreCorrupt(
                    "feedback event store schema is invalid"
                )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            timeout=5.0,
            isolation_level=None,
        )
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

    @staticmethod
    def _decode(
        row: tuple[object, object],
        *,
        owner: ProfileOwnerRef,
        idempotency_key: str,
    ) -> RecordedFeedbackEvent:
        try:
            request = FeedbackEventRequest.model_validate_json(row[0])
            event = RecordedFeedbackEvent.model_validate_json(row[1])
        except (TypeError, ValueError):
            raise FeedbackEventStoreCorrupt(
                "stored feedback event is invalid"
            ) from None
        if (
            request != event.to_request()
            or event.owner != owner
            or event.idempotency_key != idempotency_key
        ):
            raise FeedbackEventStoreCorrupt(
                "stored feedback event ownership is invalid"
            )
        return event.model_copy(deep=True)
