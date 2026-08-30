from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator

from app.guide.adapters.state.trusted_sqlite_storage import (
    TrustedSqliteStorage,
)
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    migrate_legacy_conversation_snapshot_payload,
)
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStateCorrupt,
    validate_conversation_state_transition,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef


_APPLICATION_ID = 0x58524356
_SLOT_SCHEMA_VERSION = 2
_SCHEMA_VERSION = 3

_CONVERSATIONS_SCHEMA = """
CREATE TABLE conversations (
    session_id TEXT NOT NULL PRIMARY KEY,
    snapshot_version INTEGER NOT NULL CHECK (snapshot_version >= 1),
    owner_scope TEXT CHECK (
        owner_scope IS NULL OR owner_scope IN (
            'authenticated_user',
            'local_demo',
            'anonymous_browser'
        )
    ),
    owner_subject_id TEXT,
    snapshot_json TEXT NOT NULL,
    CHECK (
        (owner_scope IS NULL AND owner_subject_id IS NULL)
        OR
        (owner_scope IS NOT NULL AND owner_subject_id IS NOT NULL)
    )
)
"""

_CONVERSATION_TOMBSTONES_SCHEMA = """
CREATE TABLE conversation_tombstones (
    session_id TEXT NOT NULL PRIMARY KEY,
    deleted_version INTEGER NOT NULL CHECK (deleted_version >= 0),
    owner_scope TEXT CHECK (
        owner_scope IS NULL OR owner_scope IN (
            'authenticated_user',
            'local_demo',
            'anonymous_browser'
        )
    ),
    owner_subject_id TEXT,
    CHECK (
        (owner_scope IS NULL AND owner_subject_id IS NULL)
        OR
        (owner_scope IS NOT NULL AND owner_subject_id IS NOT NULL)
    )
)
"""


class _PostCommitTransactionError(RuntimeError):
    pass


class SqliteConversationState:
    """Durable optimistic-CAS storage for authoritative conversations."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        trusted_state_root: str | os.PathLike[str],
    ) -> None:
        self._storage = TrustedSqliteStorage(
            database_path,
            trusted_state_root=trusted_state_root,
        )
        self._state_root = self._storage.state_root
        self._database_path = self._storage.database_path
        self._database_relative_path = (
            self._storage.database_relative_path
        )
        try:
            with self._storage.initialize() as (connection, created):
                self._initialize_schema(
                    connection=connection,
                    created=created,
                )
        except sqlite3.DatabaseError:
            raise ConversationStateCorrupt(
                str(self._database_path)
            ) from None

    @property
    def database_path(self) -> Path:
        return self._database_path

    def load(self, session_id: str) -> ConversationSnapshot | None:
        if not isinstance(session_id, str):
            raise TypeError("session_id must be a string")
        with self._read_transaction(session_id) as connection:
            return self._load(connection, session_id)

    def save(
        self,
        snapshot: ConversationSnapshot,
        *,
        expected_version: int,
    ) -> ConversationSnapshot:
        if type(snapshot) is not ConversationSnapshot:
            raise TypeError("snapshot must be an exact ConversationSnapshot")
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 0
        ):
            raise ValueError(
                "expected_version must be a non-negative integer"
            )
        try:
            snapshot = ConversationSnapshot.model_validate(
                snapshot.model_dump(mode="python"),
                strict=True,
            )
        except (TypeError, ValueError):
            raise ConversationStateCorrupt(
                snapshot.session_id
            ) from None
        try:
            with self._transaction(snapshot.session_id) as connection:
                return self._save_in_transaction(
                    connection,
                    snapshot=snapshot,
                    expected_version=expected_version,
                )
        except _PostCommitTransactionError as error:
            return self._reconcile_post_commit_save(
                snapshot,
                error=error,
            )

    def _save_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        snapshot: ConversationSnapshot,
        expected_version: int,
    ) -> ConversationSnapshot:
        current = self._load(connection, snapshot.session_id)
        current_version = current.version if current is not None else 0
        if (
            current is None
            and self._is_tombstoned(connection, snapshot.session_id)
        ):
            raise ConversationStateConflict(snapshot.session_id)
        if current_version != expected_version:
            raise ConversationStateConflict(snapshot.session_id)
        if (
            current is not None
            and current.profile_owner != snapshot.profile_owner
        ):
            raise ConversationStateConflict(snapshot.session_id)
        if snapshot.version != expected_version + 1:
            raise ValueError("snapshot version must increment by one")
        validate_conversation_state_transition(current, snapshot)
        owner_scope, owner_subject_id = self._owner_columns(snapshot)
        payload = snapshot.model_dump_json()
        if current is None:
            connection.execute(
                """
                INSERT INTO conversations (
                    session_id,
                    snapshot_version,
                    owner_scope,
                    owner_subject_id,
                    snapshot_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.session_id,
                    snapshot.version,
                    owner_scope,
                    owner_subject_id,
                    payload,
                ),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE conversations
                SET
                    snapshot_version = ?,
                    owner_scope = ?,
                    owner_subject_id = ?,
                    snapshot_json = ?
                WHERE session_id = ? AND snapshot_version = ?
                """,
                (
                    snapshot.version,
                    owner_scope,
                    owner_subject_id,
                    payload,
                    snapshot.session_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConversationStateConflict(snapshot.session_id)
        stored = self._load(connection, snapshot.session_id)
        if stored != snapshot:
            raise ConversationStateCorrupt(snapshot.session_id)
        return stored.model_copy(deep=True)

    def _reconcile_post_commit_save(
        self,
        snapshot: ConversationSnapshot,
        *,
        error: _PostCommitTransactionError,
    ) -> ConversationSnapshot:
        try:
            stored = self.load(snapshot.session_id)
        except BaseException as read_error:
            raise ConversationStateCorrupt(
                snapshot.session_id
            ) from read_error
        if stored == snapshot:
            return stored.model_copy(deep=True)
        if (
            stored is None
            or stored.profile_owner != snapshot.profile_owner
            or stored.version <= snapshot.version
        ):
            raise ConversationStateCorrupt(
                snapshot.session_id
            ) from error
        return snapshot.model_copy(deep=True)

    def delete(
        self,
        session_id: str,
        *,
        expected_owner: ProfileOwnerRef | None,
    ) -> bool:
        if not isinstance(session_id, str):
            raise TypeError("session_id must be a string")
        if (
            expected_owner is not None
            and type(expected_owner) is not ProfileOwnerRef
        ):
            raise TypeError(
                "expected_owner must be ProfileOwnerRef or None"
            )
        owner_scope = (
            expected_owner.scope
            if expected_owner is not None
            else None
        )
        owner_subject_id = (
            expected_owner.subject_id
            if expected_owner is not None
            else None
        )
        deleted = False
        try:
            with self._transaction(session_id) as connection:
                current = self._load(connection, session_id)
                if current is None:
                    return False
                if current.profile_owner != expected_owner:
                    return False
                cursor = connection.execute(
                    """
                    DELETE FROM conversations
                    WHERE
                        session_id = ?
                        AND (
                            (
                                ? IS NULL
                                AND owner_scope IS NULL
                                AND owner_subject_id IS NULL
                            )
                            OR (
                                owner_scope = ?
                                AND owner_subject_id = ?
                            )
                        )
                    """,
                    (
                        session_id,
                        owner_scope,
                        owner_scope,
                        owner_subject_id,
                    ),
                )
                deleted = cursor.rowcount == 1
                if deleted:
                    connection.execute(
                        """
                        INSERT INTO conversation_tombstones (
                            session_id,
                            deleted_version,
                            owner_scope,
                            owner_subject_id
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            current.version,
                            owner_scope,
                            owner_subject_id,
                        ),
                    )
        except _PostCommitTransactionError as error:
            return self._reconcile_post_commit_delete(
                session_id,
                expected_owner=expected_owner,
                deleted=deleted,
                error=error,
            )
        return deleted

    def _reconcile_post_commit_delete(
        self,
        session_id: str,
        *,
        expected_owner: ProfileOwnerRef | None,
        deleted: bool,
        error: _PostCommitTransactionError,
    ) -> bool:
        try:
            stored = self.load(session_id)
        except BaseException as read_error:
            raise ConversationStateCorrupt(session_id) from read_error
        if deleted:
            if stored is not None:
                raise ConversationStateCorrupt(session_id) from error
            return True
        return False

    @staticmethod
    def _owner_columns(
        snapshot: ConversationSnapshot,
    ) -> tuple[str | None, str | None]:
        owner = snapshot.profile_owner
        if owner is None:
            return None, None
        return owner.scope, owner.subject_id

    def _initialize_schema(
        self,
        *,
        connection: sqlite3.Connection,
        created: bool,
    ) -> None:
        if not created:
            self._validate_schema(
                connection,
                allowed_versions={
                    1,
                    _SLOT_SCHEMA_VERSION,
                    _SCHEMA_VERSION,
                },
            )
            if connection.execute(
                "PRAGMA user_version"
            ).fetchone() == (1,):
                self._migrate_v1_to_v3(connection)
            if connection.execute(
                "PRAGMA user_version"
            ).fetchone() == (_SLOT_SCHEMA_VERSION,):
                self._migrate_v2_to_v3(connection)
        journal_mode = connection.execute(
            "PRAGMA journal_mode = WAL"
        ).fetchone()
        if journal_mode != ("wal",):
            raise sqlite3.DatabaseError("WAL mode is unavailable")
        if created:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(_CONVERSATIONS_SCHEMA)
                connection.execute(_CONVERSATION_TOMBSTONES_SCHEMA)
                connection.execute(
                    f"PRAGMA application_id = {_APPLICATION_ID}"
                )
                connection.execute(
                    f"PRAGMA user_version = {_SCHEMA_VERSION}"
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        self._validate_schema(
            connection,
            allowed_versions={_SCHEMA_VERSION},
        )

    @staticmethod
    def _validate_schema(
        connection: sqlite3.Connection,
        *,
        allowed_versions: set[int],
    ) -> None:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise sqlite3.DatabaseError(
                "conversation state integrity check failed"
            )
        if (
            connection.execute("PRAGMA application_id").fetchone()
            != (_APPLICATION_ID,)
            or connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            not in allowed_versions
        ):
            raise sqlite3.DatabaseError(
                "conversation state schema version is incompatible"
            )
        schema_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        schema_rows = connection.execute(
            """
            SELECT name, sql
            FROM sqlite_schema
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name ASC
            """
        ).fetchall()
        actual_schema = {
            name: " ".join(sql.split())
            for name, sql in schema_rows
            if isinstance(name, str) and isinstance(sql, str)
        }
        expected_schema = {
            "conversations": " ".join(_CONVERSATIONS_SCHEMA.split()),
        }
        if schema_version == _SCHEMA_VERSION:
            expected_schema["conversation_tombstones"] = " ".join(
                _CONVERSATION_TOMBSTONES_SCHEMA.split()
            )
        if actual_schema != expected_schema:
            raise sqlite3.DatabaseError(
                "conversation state schema is incompatible"
            )

    @staticmethod
    def _migrate_v1_to_v3(
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(_CONVERSATION_TOMBSTONES_SCHEMA)
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    snapshot_version,
                    owner_scope,
                    owner_subject_id,
                    snapshot_json
                FROM conversations
                ORDER BY session_id
                """
            ).fetchall()
            for (
                session_id,
                snapshot_version,
                owner_scope,
                owner_subject_id,
                snapshot_json,
            ) in rows:
                raw_payload = json.loads(snapshot_json)
                if not isinstance(raw_payload, dict):
                    raise ValueError(
                        "snapshot payload must be an object"
                    )
                migrated = (
                    migrate_legacy_conversation_snapshot_payload(
                        raw_payload
                    )
                )
                if (
                    migrated.get("active_focus") is None
                    and migrated.get("session_profile") is None
                    and all(
                        migrated.get(slot_name) is None
                        for slot_name in (
                            "recommendation_slot",
                            "product_slot",
                            "image_slot",
                            "consultation_slot",
                            "knowledge_slot",
                            "reply_slot",
                        )
                    )
                ):
                    connection.execute(
                        """
                        INSERT INTO conversation_tombstones (
                            session_id,
                            deleted_version,
                            owner_scope,
                            owner_subject_id
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            snapshot_version,
                            owner_scope,
                            owner_subject_id,
                        ),
                    )
                    connection.execute(
                        "DELETE FROM conversations WHERE session_id = ?",
                        (session_id,),
                    )
                    continue
                snapshot = ConversationSnapshot.model_validate_json(
                    json.dumps(
                        migrated,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    strict=True,
                )
                owner_scope, owner_subject_id = (
                    SqliteConversationState._owner_columns(snapshot)
                )
                connection.execute(
                    """
                    UPDATE conversations
                    SET
                        owner_scope = ?,
                        owner_subject_id = ?,
                        snapshot_json = ?
                    WHERE session_id = ?
                    """,
                    (
                        owner_scope,
                        owner_subject_id,
                        snapshot.model_dump_json(),
                        session_id,
                    ),
                )
            connection.execute(
                f"PRAGMA user_version = {_SCHEMA_VERSION}"
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @staticmethod
    def _migrate_v2_to_v3(
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(_CONVERSATION_TOMBSTONES_SCHEMA)
            connection.execute(
                f"PRAGMA user_version = {_SCHEMA_VERSION}"
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._storage.connect() as connection:
            yield connection

    @contextmanager
    def _transaction(
        self,
        session_id: str,
    ) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        committed = False
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                try:
                    connection.commit()
                except BaseException:
                    committed = bool(
                        getattr(
                            connection,
                            "_last_commit_completed",
                            False,
                        )
                    )
                    raise
                else:
                    committed = True
        except BaseException as error:
            if committed:
                raise _PostCommitTransactionError(session_id) from error
            if connection is not None:
                self._rollback_quietly(connection)
            if isinstance(error, ConversationStateCorrupt):
                raise
            if isinstance(error, sqlite3.DatabaseError):
                raise ConversationStateCorrupt(session_id) from None
            raise
        finally:
            try:
                self._secure_database_files()
            except BaseException as error:
                if committed:
                    raise _PostCommitTransactionError(
                        session_id
                    ) from error
                raise

    @contextmanager
    def _read_transaction(
        self,
        session_id: str,
    ) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            with self._connect() as connection:
                connection.execute("BEGIN")
                yield connection
                connection.commit()
        except ConversationStateCorrupt:
            if connection is not None:
                self._rollback_quietly(connection)
            raise
        except sqlite3.DatabaseError:
            if connection is not None:
                self._rollback_quietly(connection)
            raise ConversationStateCorrupt(session_id) from None
        except BaseException:
            if connection is not None:
                self._rollback_quietly(connection)
            raise
        finally:
            self._secure_database_files()

    @staticmethod
    def _rollback_quietly(connection: sqlite3.Connection) -> None:
        try:
            connection.rollback()
        except sqlite3.DatabaseError:
            pass

    def _secure_database_files(self) -> None:
        self._storage.secure_database_files()

    @staticmethod
    def _load(
        connection: sqlite3.Connection,
        session_id: str,
    ) -> ConversationSnapshot | None:
        row = connection.execute(
            """
            SELECT
                snapshot_version,
                owner_scope,
                owner_subject_id,
                snapshot_json
            FROM conversations
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            raw_payload = json.loads(row[3])
            if not isinstance(raw_payload, dict):
                raise ValueError("snapshot payload must be an object")
            snapshot = ConversationSnapshot.model_validate_json(
                json.dumps(
                    raw_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                strict=True,
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            raise ConversationStateCorrupt(session_id) from None
        owner_scope, owner_subject_id = (
            SqliteConversationState._owner_columns(snapshot)
        )
        if (
            snapshot.session_id != session_id
            or snapshot.version != row[0]
            or owner_scope != row[1]
            or owner_subject_id != row[2]
        ):
            raise ConversationStateCorrupt(session_id)
        return snapshot.model_copy(deep=True)

    @staticmethod
    def _is_tombstoned(
        connection: sqlite3.Connection,
        session_id: str,
    ) -> bool:
        return (
            connection.execute(
                """
                SELECT 1
                FROM conversation_tombstones
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            is not None
        )
