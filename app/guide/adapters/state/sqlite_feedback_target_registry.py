from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
from threading import Lock
from typing import Iterator

from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.target_contracts import (
    TrustedFeedbackTarget,
)
from app.guide.feedback.target_ports import (
    FeedbackTargetConflict,
    FeedbackTargetStoreCorrupt,
)


_APPLICATION_ID = 0x58524654
_SCHEMA_VERSION = 1
_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_INITIALIZATION_LOCKS_GUARD = Lock()
_INITIALIZATION_LOCKS: dict[Path, Lock] = {}
_CORRUPT_MESSAGE = (
    "feedback target registry is invalid or unavailable"
)

_TARGETS_SCHEMA = """
CREATE TABLE feedback_targets (
    owner_scope TEXT NOT NULL CHECK (
        owner_scope IN ('authenticated_user', 'local_demo')
    ),
    owner_subject_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    conversation_version INTEGER NOT NULL CHECK (
        conversation_version >= 0
    ),
    target_json TEXT NOT NULL,
    PRIMARY KEY (
        owner_scope,
        owner_subject_id,
        session_id,
        conversation_version
    )
)
"""


class _PinnedDatabaseTarget(os.PathLike[str]):
    """Retain descriptor provenance while allowing SQLite WAL files."""

    def __init__(
        self,
        *,
        descriptor: int,
        anchor_path: Path,
    ) -> None:
        self._descriptor_uri = f"file:/dev/fd/{descriptor}?mode=rw"
        self._anchor_uri = f"{anchor_path.as_uri()}?mode=rw"

    def __str__(self) -> str:
        return self._descriptor_uri

    def __fspath__(self) -> str:
        return self._anchor_uri


def _thread_initialization_lock(database_path: Path) -> Lock:
    with _INITIALIZATION_LOCKS_GUARD:
        return _INITIALIZATION_LOCKS.setdefault(database_path, Lock())


class SqliteFeedbackTargetRegistry:
    """Durable trusted feedback targets for one local host."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        trusted_state_root: str | os.PathLike[str],
    ) -> None:
        raw_database_path = self._absolute_path(database_path)
        raw_state_root = self._absolute_path(trusted_state_root)
        (
            self._state_root,
            self._database_path,
            self._database_relative_path,
            parent_descriptor,
        ) = self._prepare_storage(
            raw_database_path=raw_database_path,
            raw_state_root=raw_state_root,
        )
        database_descriptor: int | None = None
        anchor_descriptor: int | None = None
        try:
            with _thread_initialization_lock(self._database_path):
                fcntl.flock(parent_descriptor, fcntl.LOCK_EX)
                database_descriptor, created = self._open_database_file(
                    parent_descriptor,
                    create=True,
                )
                anchor_descriptor = self._open_database_anchor(
                    parent_descriptor,
                    database_descriptor,
                )
                try:
                    self._initialize_schema(
                        created=created,
                        parent_descriptor=parent_descriptor,
                        database_descriptor=database_descriptor,
                        anchor_descriptor=anchor_descriptor,
                    )
                except sqlite3.DatabaseError:
                    raise FeedbackTargetStoreCorrupt(
                        _CORRUPT_MESSAGE
                    ) from None
                self._assert_database_containment()
        finally:
            if anchor_descriptor is not None:
                os.close(anchor_descriptor)
            if database_descriptor is not None:
                os.close(database_descriptor)
            fcntl.flock(parent_descriptor, fcntl.LOCK_UN)
            os.close(parent_descriptor)

    @property
    def database_path(self) -> Path:
        return self._database_path

    def load(
        self,
        *,
        owner: ProfileOwnerRef,
        reference: ConversationVersionRef,
    ) -> TrustedFeedbackTarget | None:
        if not isinstance(owner, ProfileOwnerRef):
            raise TypeError("owner must be a ProfileOwnerRef")
        if not isinstance(reference, ConversationVersionRef):
            raise TypeError(
                "reference must be a ConversationVersionRef"
            )
        try:
            with self._read_transaction() as connection:
                row = connection.execute(
                    """
                    SELECT target_json
                    FROM feedback_targets
                    WHERE owner_scope = ?
                      AND owner_subject_id = ?
                      AND session_id = ?
                      AND conversation_version = ?
                    """,
                    (
                        owner.scope,
                        owner.subject_id,
                        reference.session_id,
                        reference.conversation_version,
                    ),
                ).fetchone()
        except FeedbackTargetStoreCorrupt:
            raise
        except sqlite3.DatabaseError:
            raise FeedbackTargetStoreCorrupt(
                _CORRUPT_MESSAGE
            ) from None
        if row is None:
            return None
        return self._decode(
            row,
            owner=owner,
            reference=reference,
        )

    def record_once(
        self,
        target: TrustedFeedbackTarget,
    ) -> TrustedFeedbackTarget:
        if not isinstance(target, TrustedFeedbackTarget):
            raise TypeError(
                "target must be a TrustedFeedbackTarget"
            )
        candidate = target.model_copy(deep=True)
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    """
                    SELECT target_json
                    FROM feedback_targets
                    WHERE owner_scope = ?
                      AND owner_subject_id = ?
                      AND session_id = ?
                      AND conversation_version = ?
                    """,
                    self._key(candidate),
                ).fetchone()
                if row is not None:
                    existing = self._decode(
                        row,
                        owner=candidate.owner,
                        reference=candidate.conversation,
                    )
                    if existing != candidate:
                        raise FeedbackTargetConflict(
                            candidate.conversation.session_id
                        )
                    return existing.model_copy(deep=True)
                connection.execute(
                    """
                    INSERT INTO feedback_targets (
                        owner_scope,
                        owner_subject_id,
                        session_id,
                        conversation_version,
                        target_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        *self._key(candidate),
                        candidate.model_dump_json(),
                    ),
                )
        except (FeedbackTargetConflict, FeedbackTargetStoreCorrupt):
            raise
        except sqlite3.DatabaseError:
            raise FeedbackTargetStoreCorrupt(
                _CORRUPT_MESSAGE
            ) from None
        return candidate.model_copy(deep=True)

    @staticmethod
    def _key(
        target: TrustedFeedbackTarget,
    ) -> tuple[str, str, str, int]:
        return (
            target.owner.scope,
            target.owner.subject_id,
            target.conversation.session_id,
            target.conversation.conversation_version,
        )

    @staticmethod
    def _absolute_path(
        path: str | os.PathLike[str],
    ) -> Path:
        expanded = Path(path).expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return Path(os.path.normpath(expanded))

    @classmethod
    def _prepare_storage(
        cls,
        *,
        raw_database_path: Path,
        raw_state_root: Path,
    ) -> tuple[Path, Path, Path, int]:
        raw_state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        state_root = raw_state_root.resolve(strict=True)
        relative_path = cls._relative_database_path(
            raw_database_path=raw_database_path,
            raw_state_root=raw_state_root,
            canonical_state_root=state_root,
        )
        if relative_path.name in ("", ".", ".."):
            raise ValueError(
                "state database path must name a file"
            )

        root_descriptor = cls._open_directory(state_root)
        try:
            cls._validate_private_directory(root_descriptor)
            parent_descriptor = cls._traverse_parent_directories(
                root_descriptor,
                relative_path.parent.parts,
                create=True,
            )
        finally:
            os.close(root_descriptor)
        return (
            state_root,
            state_root / relative_path,
            relative_path,
            parent_descriptor,
        )

    @staticmethod
    def _relative_database_path(
        *,
        raw_database_path: Path,
        raw_state_root: Path,
        canonical_state_root: Path,
    ) -> Path:
        for candidate_root in (
            raw_state_root,
            canonical_state_root,
        ):
            try:
                relative_path = raw_database_path.relative_to(
                    candidate_root
                )
            except ValueError:
                continue
            if (
                relative_path.is_absolute()
                or not relative_path.parts
                or any(
                    part in ("", ".", "..")
                    for part in relative_path.parts
                )
            ):
                break
            return relative_path

        for candidate_root in reversed(raw_database_path.parents):
            try:
                equivalent_root = candidate_root.samefile(
                    canonical_state_root
                )
            except OSError:
                continue
            if not equivalent_root:
                continue
            relative_path = raw_database_path.relative_to(
                candidate_root
            )
            if (
                relative_path.is_absolute()
                or not relative_path.parts
                or any(
                    part in ("", ".", "..")
                    for part in relative_path.parts
                )
            ):
                break
            return relative_path
        raise ValueError(
            "state database is outside trusted state root"
        )

    @staticmethod
    def _open_directory(path: Path) -> int:
        if _DIRECTORY == 0 or _NO_FOLLOW == 0:
            raise RuntimeError(
                "secure state directory access is unavailable"
            )
        try:
            return os.open(
                path,
                os.O_RDONLY
                | _DIRECTORY
                | _NO_FOLLOW
                | _CLOSE_ON_EXEC,
            )
        except OSError as error:
            raise ValueError(
                "state directory must not be a symlink"
            ) from error

    @staticmethod
    def _validate_private_directory(descriptor: int) -> None:
        directory_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ValueError("state directory must be a directory")
        if directory_stat.st_uid != os.geteuid():
            raise PermissionError(
                "state directory must be owned by the current user"
            )
        os.fchmod(descriptor, 0o700)

    @classmethod
    def _traverse_parent_directories(
        cls,
        root_descriptor: int,
        parts: tuple[str, ...],
        *,
        create: bool,
    ) -> int:
        current_descriptor = os.dup(root_descriptor)
        try:
            for part in parts:
                if create:
                    try:
                        os.mkdir(
                            part,
                            mode=0o700,
                            dir_fd=current_descriptor,
                        )
                    except FileExistsError:
                        pass
                try:
                    next_descriptor = os.open(
                        part,
                        os.O_RDONLY
                        | _DIRECTORY
                        | _NO_FOLLOW
                        | _CLOSE_ON_EXEC,
                        dir_fd=current_descriptor,
                    )
                except OSError as error:
                    raise ValueError(
                        "state path components must not be symlinks"
                    ) from error
                os.close(current_descriptor)
                current_descriptor = next_descriptor
                cls._validate_private_directory(
                    current_descriptor
                )
            return current_descriptor
        except BaseException:
            os.close(current_descriptor)
            raise

    def _open_database_parent(self) -> int:
        root_descriptor = self._open_directory(self._state_root)
        try:
            self._validate_private_directory(root_descriptor)
            return self._traverse_parent_directories(
                root_descriptor,
                self._database_relative_path.parent.parts,
                create=False,
            )
        finally:
            os.close(root_descriptor)

    def _open_database_file(
        self,
        parent_descriptor: int,
        *,
        create: bool,
    ) -> tuple[int, bool]:
        if create:
            try:
                descriptor = os.open(
                    self._database_relative_path.name,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | _NO_FOLLOW
                    | _CLOSE_ON_EXEC,
                    0o600,
                    dir_fd=parent_descriptor,
                )
            except FileExistsError:
                created = False
            else:
                created = True
        else:
            created = False

        if not created:
            try:
                descriptor = os.open(
                    self._database_relative_path.name,
                    os.O_RDWR
                    | _NO_FOLLOW
                    | _CLOSE_ON_EXEC,
                    dir_fd=parent_descriptor,
                )
            except OSError as error:
                raise ValueError(
                    "state database must not be a symlink or missing"
                ) from error
        try:
            self._validate_database_descriptor(descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor, created

    @staticmethod
    def _database_anchor_name(database_name: str) -> str:
        return f".{database_name}.inode"

    @property
    def _database_anchor_path(self) -> Path:
        return (
            self._database_path.parent
            / self._database_anchor_name(
                self._database_relative_path.name
            )
        )

    @staticmethod
    def _validate_database_descriptor(descriptor: int) -> None:
        database_stat = os.fstat(descriptor)
        if not stat.S_ISREG(database_stat.st_mode):
            raise ValueError(
                "state database must be a regular file"
            )
        if database_stat.st_uid != os.geteuid():
            raise PermissionError(
                "state database must be owned by the current user"
            )
        os.fchmod(descriptor, 0o600)

    def _open_database_anchor(
        self,
        parent_descriptor: int,
        database_descriptor: int,
    ) -> int:
        database_name = self._database_relative_path.name
        anchor_name = self._database_anchor_name(database_name)
        try:
            os.link(
                database_name,
                anchor_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
        except OSError as error:
            raise ValueError(
                "state database inode anchor is unavailable"
            ) from error
        try:
            anchor_descriptor = os.open(
                anchor_name,
                os.O_RDWR | _NO_FOLLOW | _CLOSE_ON_EXEC,
                dir_fd=parent_descriptor,
            )
        except OSError as error:
            raise ValueError(
                "state database inode anchor must not be a symlink"
            ) from error
        try:
            self._validate_database_descriptor(anchor_descriptor)
            self._verify_database_anchor(
                parent_descriptor=parent_descriptor,
                database_descriptor=database_descriptor,
                anchor_descriptor=anchor_descriptor,
            )
        except BaseException:
            os.close(anchor_descriptor)
            raise
        return anchor_descriptor

    def _verify_database_anchor(
        self,
        *,
        parent_descriptor: int,
        database_descriptor: int,
        anchor_descriptor: int,
    ) -> None:
        database_name = self._database_relative_path.name
        anchor_name = self._database_anchor_name(database_name)
        try:
            database_entry = os.stat(
                database_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            anchor_entry = os.stat(
                anchor_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as error:
            raise ValueError(
                "state database inode anchor is unavailable"
            ) from error
        database_stat = os.fstat(database_descriptor)
        anchor_stat = os.fstat(anchor_descriptor)
        identities = {
            (item.st_dev, item.st_ino)
            for item in (
                database_entry,
                anchor_entry,
                database_stat,
                anchor_stat,
            )
        }
        if (
            len(identities) != 1
            or not stat.S_ISREG(database_entry.st_mode)
            or not stat.S_ISREG(anchor_entry.st_mode)
            or database_stat.st_nlink != 2
            or anchor_stat.st_nlink != 2
        ):
            raise ValueError(
                "state database inode anchor changed"
            )

    def _assert_database_containment(self) -> None:
        resolved_database = self._database_path.resolve(strict=True)
        if (
            resolved_database != self._database_path
            or not resolved_database.is_relative_to(
                self._state_root
            )
        ):
            raise ValueError(
                "state database is outside trusted state root"
            )
        database_stat = resolved_database.stat()
        if (
            not stat.S_ISREG(database_stat.st_mode)
            or stat.S_IMODE(database_stat.st_mode) != 0o600
        ):
            raise PermissionError(
                "state database must be private"
            )
        resolved_anchor = self._database_anchor_path.resolve(
            strict=True
        )
        if not resolved_anchor.is_relative_to(self._state_root):
            raise ValueError(
                "state database anchor is outside trusted root"
            )
        anchor_stat = resolved_anchor.stat()
        if (
            not stat.S_ISREG(anchor_stat.st_mode)
            or stat.S_IMODE(anchor_stat.st_mode) != 0o600
            or (anchor_stat.st_dev, anchor_stat.st_ino)
            != (database_stat.st_dev, database_stat.st_ino)
        ):
            raise PermissionError(
                "state database anchor must be private"
            )

    def _initialize_schema(
        self,
        *,
        created: bool,
        parent_descriptor: int,
        database_descriptor: int,
        anchor_descriptor: int,
    ) -> None:
        with self._connect(
            parent_descriptor=parent_descriptor,
            database_descriptor=database_descriptor,
            anchor_descriptor=anchor_descriptor,
        ) as connection:
            if not created:
                self._validate_schema(connection)
            journal_mode = connection.execute(
                "PRAGMA journal_mode = WAL"
            ).fetchone()
            if journal_mode != ("wal",):
                raise sqlite3.DatabaseError(
                    "WAL mode is unavailable"
                )
            if created:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(_TARGETS_SCHEMA)
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
            self._validate_schema(connection)
            self._validate_integrity(connection)
        self._secure_database_files()

    @staticmethod
    def _validate_integrity(
        connection: sqlite3.Connection,
    ) -> None:
        if connection.execute("PRAGMA quick_check").fetchall() != [
            ("ok",)
        ]:
            raise sqlite3.DatabaseError(
                "feedback target integrity check failed"
            )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "PRAGMA application_id"
        ).fetchone() != (_APPLICATION_ID,):
            raise sqlite3.DatabaseError(
                "feedback target application ID is incompatible"
            )
        if connection.execute(
            "PRAGMA user_version"
        ).fetchone() != (_SCHEMA_VERSION,):
            raise sqlite3.DatabaseError(
                "feedback target schema version is incompatible"
            )
        schema_rows = connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_schema
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type ASC, name ASC
            """
        ).fetchall()
        actual_schema = [
            (
                object_type,
                name,
                table_name,
                " ".join(sql.split()),
            )
            for object_type, name, table_name, sql in schema_rows
            if all(
                isinstance(value, str)
                for value in (
                    object_type,
                    name,
                    table_name,
                    sql,
                )
            )
        ]
        expected_schema = [
            (
                "table",
                "feedback_targets",
                "feedback_targets",
                " ".join(_TARGETS_SCHEMA.split()),
            )
        ]
        if actual_schema != expected_schema:
            raise sqlite3.DatabaseError(
                "feedback target schema is incompatible"
            )

    @contextmanager
    def _connect(
        self,
        *,
        parent_descriptor: int | None = None,
        database_descriptor: int | None = None,
        anchor_descriptor: int | None = None,
    ) -> Iterator[sqlite3.Connection]:
        borrowed_descriptors = parent_descriptor is not None
        if borrowed_descriptors != (
            database_descriptor is not None
            and anchor_descriptor is not None
        ):
            raise ValueError(
                "database descriptors must be supplied together"
            )
        if not borrowed_descriptors:
            parent_descriptor = self._open_database_parent()
            fcntl.flock(parent_descriptor, fcntl.LOCK_SH)
            try:
                database_descriptor, _ = self._open_database_file(
                    parent_descriptor,
                    create=False,
                )
                anchor_descriptor = self._open_database_anchor(
                    parent_descriptor,
                    database_descriptor,
                )
            except BaseException:
                fcntl.flock(parent_descriptor, fcntl.LOCK_UN)
                os.close(parent_descriptor)
                raise

        assert parent_descriptor is not None
        assert database_descriptor is not None
        assert anchor_descriptor is not None
        connection: sqlite3.Connection | None = None
        try:
            self._verify_database_anchor(
                parent_descriptor=parent_descriptor,
                database_descriptor=database_descriptor,
                anchor_descriptor=anchor_descriptor,
            )
            self._validate_database_files(parent_descriptor)
            connection = sqlite3.connect(
                _PinnedDatabaseTarget(
                    descriptor=database_descriptor,
                    anchor_path=self._database_anchor_path,
                ),
                timeout=5.0,
                isolation_level=None,
                uri=True,
            )
            self._verify_database_anchor(
                parent_descriptor=parent_descriptor,
                database_descriptor=database_descriptor,
                anchor_descriptor=anchor_descriptor,
            )
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA trusted_schema = OFF")
            yield connection
        finally:
            if connection is not None:
                connection.close()
            if not borrowed_descriptors:
                os.close(anchor_descriptor)
                os.close(database_descriptor)
                fcntl.flock(parent_descriptor, fcntl.LOCK_UN)
                os.close(parent_descriptor)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._validate_schema(connection)
                yield connection
                connection.commit()
        except BaseException:
            if connection is not None:
                self._rollback_quietly(connection)
            raise
        finally:
            self._secure_database_files()

    @contextmanager
    def _read_transaction(
        self,
    ) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            with self._connect() as connection:
                connection.execute("BEGIN")
                self._validate_schema(connection)
                yield connection
                connection.commit()
        except BaseException:
            if connection is not None:
                self._rollback_quietly(connection)
            raise
        finally:
            self._secure_database_files()

    def _validate_database_files(
        self,
        parent_descriptor: int,
    ) -> None:
        database_name = self._database_relative_path.name
        anchor_name = self._database_anchor_name(database_name)
        for name in (
            database_name,
            f"{database_name}-wal",
            f"{database_name}-shm",
            anchor_name,
            f"{anchor_name}-wal",
            f"{anchor_name}-shm",
        ):
            try:
                descriptor = os.open(
                    name,
                    os.O_RDONLY | _NO_FOLLOW | _CLOSE_ON_EXEC,
                    dir_fd=parent_descriptor,
                )
            except FileNotFoundError:
                continue
            except OSError as error:
                raise ValueError(
                    "state database files must not be symlinks"
                ) from error
            try:
                file_stat = os.fstat(descriptor)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise ValueError(
                        "state database files must be regular files"
                    )
                if file_stat.st_uid != os.geteuid():
                    raise PermissionError(
                        "state database files must be owned by current user"
                    )
            finally:
                os.close(descriptor)

    def _secure_database_files(self) -> None:
        parent_descriptor = self._open_database_parent()
        try:
            self._validate_database_files(parent_descriptor)
            database_name = self._database_relative_path.name
            anchor_name = self._database_anchor_name(database_name)
            for name in (
                database_name,
                f"{database_name}-wal",
                f"{database_name}-shm",
                anchor_name,
                f"{anchor_name}-wal",
                f"{anchor_name}-shm",
            ):
                try:
                    descriptor = os.open(
                        name,
                        os.O_RDONLY
                        | _NO_FOLLOW
                        | _CLOSE_ON_EXEC,
                        dir_fd=parent_descriptor,
                    )
                except FileNotFoundError:
                    continue
                except OSError as error:
                    raise ValueError(
                        "state database files must not be symlinks"
                    ) from error
                try:
                    os.fchmod(descriptor, 0o600)
                finally:
                    os.close(descriptor)
        finally:
            os.close(parent_descriptor)

    @staticmethod
    def _rollback_quietly(
        connection: sqlite3.Connection,
    ) -> None:
        try:
            connection.rollback()
        except sqlite3.DatabaseError:
            pass

    @staticmethod
    def _decode(
        row: tuple[object],
        *,
        owner: ProfileOwnerRef,
        reference: ConversationVersionRef,
    ) -> TrustedFeedbackTarget:
        try:
            target = TrustedFeedbackTarget.model_validate_json(
                row[0]
            )
        except (TypeError, ValueError):
            raise FeedbackTargetStoreCorrupt(
                "stored feedback target is invalid"
            ) from None
        if (
            target.owner != owner
            or target.conversation != reference
        ):
            raise FeedbackTargetStoreCorrupt(
                "stored feedback target authority is invalid"
            )
        return target.model_copy(deep=True)
