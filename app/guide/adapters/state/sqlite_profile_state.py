from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
from threading import Lock
from typing import Iterator

from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
    ProfileOwnerRef,
)
from app.guide.feedback.profile_state import (
    ProfileSnapshot,
    ProfileStateConflict,
    ProfileStateCorrupt,
    ProfileWriteDisposition,
    ProfileWriteResult,
)

_APPLICATION_ID = 0x58525046
_LEGACY_SCHEMA_VERSION = 1
_SCHEMA_VERSION = 2
_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_INITIALIZATION_LOCKS_GUARD = Lock()
_INITIALIZATION_LOCKS: dict[Path, Lock] = {}


class _PinnedDatabaseTarget(os.PathLike[str]):
    """Expose descriptor provenance while retaining a WAL-capable path."""

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


_LEGACY_PROFILES_SCHEMA = """
CREATE TABLE profiles (
    scope TEXT NOT NULL CHECK (
        scope IN ('authenticated_user', 'local_demo')
    ),
    subject_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    PRIMARY KEY (scope, subject_id)
)
"""

_PROFILES_SCHEMA = """
CREATE TABLE profiles (
    scope TEXT NOT NULL CHECK (
        scope IN (
            'authenticated_user',
            'local_demo',
            'anonymous_browser'
        )
    ),
    subject_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    PRIMARY KEY (scope, subject_id)
)
"""

_PROFILE_FACTS_SCHEMA = """
CREATE TABLE profile_facts (
    scope TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    field TEXT NOT NULL CHECK (
        field IN (
            'skin_type',
            'skin_concern',
            'ingredient_exclusion',
            'preferred_brand',
            'preferred_category'
        )
    ),
    value TEXT NOT NULL,
    source_turn_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (
        source_kind IN (
            'explicit_user',
            'confirmed_consultation'
        )
    ),
    confirmed_at TEXT NOT NULL CHECK (
        substr(confirmed_at, -6) = '+00:00'
    ),
    profile_version INTEGER NOT NULL CHECK (
        profile_version >= 1
    ),
    PRIMARY KEY (scope, subject_id, field),
    FOREIGN KEY (scope, subject_id)
        REFERENCES profiles (scope, subject_id)
        ON DELETE CASCADE
)
"""


def _thread_initialization_lock(database_path: Path) -> Lock:
    with _INITIALIZATION_LOCKS_GUARD:
        return _INITIALIZATION_LOCKS.setdefault(database_path, Lock())


class SqliteProfileState:
    """Durable, owner-scoped confirmed profile facts."""

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
                    raise ProfileStateCorrupt(
                        str(self._database_path)
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

    def load(self, owner: ProfileOwnerRef) -> ProfileSnapshot | None:
        if not isinstance(owner, ProfileOwnerRef):
            raise TypeError("owner must be a ProfileOwnerRef")
        with self._read_transaction(owner.subject_id) as connection:
            return self._load(connection, owner)

    def save(
        self,
        fact: ConfirmedProfileFact,
        *,
        expected_version: int,
    ) -> ProfileSnapshot:
        result = self.write_once(
            fact,
            expected_version=expected_version,
        )
        if result.disposition is ProfileWriteDisposition.CONFLICT:
            raise ProfileStateConflict(fact.owner.subject_id)
        return result.snapshot

    def write_once(
        self,
        fact: ConfirmedProfileFact,
        *,
        expected_version: int,
    ) -> ProfileWriteResult:
        if not isinstance(fact, ConfirmedProfileFact):
            raise TypeError("fact must be a ConfirmedProfileFact")
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 0
        ):
            raise ValueError("expected_version must be a non-negative integer")
        with self._transaction(fact.owner.subject_id) as connection:
            current = self._load(connection, fact.owner)
            current_version = current.version if current is not None else 0
            current_fact = (
                next(
                    (
                        stored
                        for stored in current.facts
                        if stored.field == fact.field
                    ),
                    None,
                )
                if current is not None
                else None
            )
            if current_fact is not None:
                if current_fact.value == fact.value:
                    return ProfileWriteResult(
                        disposition=ProfileWriteDisposition.IDEMPOTENT,
                        snapshot=current,
                        stored_fact=current_fact,
                    )
                return ProfileWriteResult(
                    disposition=ProfileWriteDisposition.CONFLICT,
                    snapshot=current,
                    stored_fact=current_fact,
                )
            if current_version != expected_version:
                raise ProfileStateConflict(fact.owner.subject_id)
            if fact.profile_version != expected_version + 1:
                raise ValueError("profile version must increment by one")
            if current is None:
                connection.execute(
                    """
                    INSERT INTO profiles (scope, subject_id, version)
                    VALUES (?, ?, ?)
                    """,
                    (
                        fact.owner.scope,
                        fact.owner.subject_id,
                        fact.profile_version,
                    ),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE profiles
                    SET version = ?
                    WHERE scope = ?
                      AND subject_id = ?
                      AND version = ?
                    """,
                    (
                        fact.profile_version,
                        fact.owner.scope,
                        fact.owner.subject_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ProfileStateConflict(fact.owner.subject_id)
            self._insert_fact(connection, fact)
            stored = self._load(connection, fact.owner)
            assert stored is not None
            stored_fact = next(
                item for item in stored.facts if item.field == fact.field
            )
            return ProfileWriteResult(
                disposition=ProfileWriteDisposition.CREATED,
                snapshot=stored,
                stored_fact=stored_fact,
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
            raise ValueError("state database path must name a file")

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

        database_path = state_root / relative_path
        return (
            state_root,
            database_path,
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
        for candidate_root in (raw_state_root, canonical_state_root):
            try:
                relative_path = raw_database_path.relative_to(candidate_root)
            except ValueError:
                continue
            if (
                relative_path.is_absolute()
                or not relative_path.parts
                or any(part in ("", ".", "..") for part in relative_path.parts)
            ):
                break
            return relative_path

        # Keep descendants lexical so descriptor traversal still rejects
        # symlinks below an equivalent spelling of the trusted root.
        for candidate_root in reversed(raw_database_path.parents):
            try:
                equivalent_root = candidate_root.samefile(
                    canonical_state_root
                )
            except OSError:
                continue
            if not equivalent_root:
                continue
            relative_path = raw_database_path.relative_to(candidate_root)
            if (
                relative_path.is_absolute()
                or not relative_path.parts
                or any(part in ("", ".", "..") for part in relative_path.parts)
            ):
                break
            return relative_path
        raise ValueError("state database is outside trusted state root")

    @staticmethod
    def _open_directory(path: Path) -> int:
        if _DIRECTORY == 0 or _NO_FOLLOW == 0:
            raise RuntimeError("secure state directory access is unavailable")
        try:
            return os.open(
                path,
                os.O_RDONLY | _DIRECTORY | _NO_FOLLOW | _CLOSE_ON_EXEC,
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
                cls._validate_private_directory(current_descriptor)
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
            create_flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | _NO_FOLLOW
                | _CLOSE_ON_EXEC
            )
            try:
                descriptor = os.open(
                    self._database_relative_path.name,
                    create_flags,
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
                    os.O_RDWR | _NO_FOLLOW | _CLOSE_ON_EXEC,
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
            / self._database_anchor_name(self._database_relative_path.name)
        )

    @staticmethod
    def _validate_database_descriptor(descriptor: int) -> None:
        database_stat = os.fstat(descriptor)
        if not stat.S_ISREG(database_stat.st_mode):
            raise ValueError("state database must be a regular file")
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
            raise ValueError("state database inode anchor changed")

    def _assert_database_containment(self) -> None:
        resolved_database = self._database_path.resolve(strict=True)
        if (
            resolved_database != self._database_path
            or not resolved_database.is_relative_to(self._state_root)
        ):
            raise ValueError("state database is outside trusted state root")
        database_stat = resolved_database.stat()
        if (
            not stat.S_ISREG(database_stat.st_mode)
            or stat.S_IMODE(database_stat.st_mode) != 0o600
        ):
            raise PermissionError("state database must be private")

        resolved_anchor = self._database_anchor_path.resolve(strict=True)
        if not resolved_anchor.is_relative_to(self._state_root):
            raise ValueError("state database anchor is outside trusted root")
        anchor_stat = resolved_anchor.stat()
        if (
            not stat.S_ISREG(anchor_stat.st_mode)
            or stat.S_IMODE(anchor_stat.st_mode) != 0o600
            or (anchor_stat.st_dev, anchor_stat.st_ino)
            != (database_stat.st_dev, database_stat.st_ino)
        ):
            raise PermissionError("state database anchor must be private")

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
                self._validate_or_migrate_schema(connection)
            journal_mode = connection.execute(
                "PRAGMA journal_mode = WAL"
            ).fetchone()
            if journal_mode != ("wal",):
                raise sqlite3.DatabaseError("WAL mode is unavailable")
            if created:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(_PROFILES_SCHEMA)
                    connection.execute(_PROFILE_FACTS_SCHEMA)
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
        self._secure_database_files()

    @classmethod
    def _validate_or_migrate_schema(
        cls,
        connection: sqlite3.Connection,
    ) -> None:
        cls._validate_integrity(connection)
        application_id = connection.execute(
            "PRAGMA application_id"
        ).fetchone()
        schema_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()
        if application_id != (_APPLICATION_ID,):
            raise sqlite3.DatabaseError(
                "profile state application id is incompatible"
            )
        if schema_version == (_SCHEMA_VERSION,):
            cls._validate_schema(connection)
            return
        if schema_version != (_LEGACY_SCHEMA_VERSION,):
            raise sqlite3.DatabaseError(
                "profile state schema version is incompatible"
            )
        cls._validate_schema_definition(
            connection,
            profiles_schema=_LEGACY_PROFILES_SCHEMA,
        )
        cls._migrate_legacy_schema(connection)
        cls._validate_schema(connection)

    @staticmethod
    def _migrate_legacy_schema(
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                CREATE TEMP TABLE legacy_profiles AS
                SELECT scope, subject_id, version
                FROM profiles
                """
            )
            connection.execute(
                """
                CREATE TEMP TABLE legacy_profile_facts AS
                SELECT
                    scope,
                    subject_id,
                    field,
                    value,
                    source_turn_id,
                    source_kind,
                    confirmed_at,
                    profile_version
                FROM profile_facts
                """
            )
            connection.execute("DROP TABLE profile_facts")
            connection.execute("DROP TABLE profiles")
            connection.execute(_PROFILES_SCHEMA)
            connection.execute(_PROFILE_FACTS_SCHEMA)
            connection.execute(
                """
                INSERT INTO profiles (scope, subject_id, version)
                SELECT scope, subject_id, version
                FROM legacy_profiles
                """
            )
            connection.execute(
                """
                INSERT INTO profile_facts (
                    scope,
                    subject_id,
                    field,
                    value,
                    source_turn_id,
                    source_kind,
                    confirmed_at,
                    profile_version
                )
                SELECT
                    scope,
                    subject_id,
                    field,
                    value,
                    source_turn_id,
                    source_kind,
                    confirmed_at,
                    profile_version
                FROM legacy_profile_facts
                """
            )
            connection.execute("DROP TABLE legacy_profile_facts")
            connection.execute("DROP TABLE legacy_profiles")
            connection.execute(
                f"PRAGMA user_version = {_SCHEMA_VERSION}"
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        cls._validate_integrity(connection)
        application_id = connection.execute(
            "PRAGMA application_id"
        ).fetchone()
        schema_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()
        if (
            application_id != (_APPLICATION_ID,)
            or schema_version != (_SCHEMA_VERSION,)
        ):
            raise sqlite3.DatabaseError(
                "profile state schema version is incompatible"
            )
        cls._validate_schema_definition(
            connection,
            profiles_schema=_PROFILES_SCHEMA,
        )

    @staticmethod
    def _validate_integrity(connection: sqlite3.Connection) -> None:
        quick_check = connection.execute("PRAGMA quick_check").fetchall()
        if quick_check != [("ok",)]:
            raise sqlite3.DatabaseError("profile state integrity check failed")

    @staticmethod
    def _validate_schema_definition(
        connection: sqlite3.Connection,
        *,
        profiles_schema: str,
    ) -> None:
        schema_rows = connection.execute(
            """
            SELECT name, sql
            FROM sqlite_schema
            WHERE type = 'table'
            ORDER BY name ASC
            """
        ).fetchall()
        expected_schema = {
            "profile_facts": " ".join(_PROFILE_FACTS_SCHEMA.split()),
            "profiles": " ".join(profiles_schema.split()),
        }
        actual_schema = {
            name: " ".join(sql.split())
            for name, sql in schema_rows
            if isinstance(name, str) and isinstance(sql, str)
        }
        if actual_schema != expected_schema:
            raise sqlite3.DatabaseError(
                "profile state schema is incompatible"
            )
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise sqlite3.DatabaseError(
                "profile state foreign keys are corrupt"
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
            raise ValueError("database descriptors must be supplied together")
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
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA trusted_schema = OFF")
            yield connection
        except BaseException:
            raise
        finally:
            if connection is not None:
                connection.close()
            if not borrowed_descriptors:
                os.close(anchor_descriptor)
                os.close(database_descriptor)
                fcntl.flock(parent_descriptor, fcntl.LOCK_UN)
                os.close(parent_descriptor)

    @contextmanager
    def _transaction(
        self,
        subject_id: str,
    ) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
        except ProfileStateCorrupt:
            if connection is not None:
                self._rollback_quietly(connection)
            raise
        except sqlite3.DatabaseError:
            if connection is not None:
                self._rollback_quietly(connection)
            raise ProfileStateCorrupt(subject_id) from None
        except BaseException:
            if connection is not None:
                self._rollback_quietly(connection)
            raise
        finally:
            self._secure_database_files()

    @contextmanager
    def _read_transaction(
        self,
        subject_id: str,
    ) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            with self._connect() as connection:
                connection.execute("BEGIN")
                yield connection
                connection.commit()
        except ProfileStateCorrupt:
            if connection is not None:
                self._rollback_quietly(connection)
            raise
        except sqlite3.DatabaseError:
            if connection is not None:
                self._rollback_quietly(connection)
            raise ProfileStateCorrupt(subject_id) from None
        except BaseException:
            if connection is not None:
                self._rollback_quietly(connection)
            raise
        finally:
            self._secure_database_files()

    def _secure_database_files(self) -> None:
        parent_descriptor = self._open_database_parent()
        try:
            database_name = self._database_relative_path.name
            anchor_name = self._database_anchor_name(database_name)
            names = (
                database_name,
                f"{database_name}-wal",
                f"{database_name}-shm",
                anchor_name,
                f"{anchor_name}-wal",
                f"{anchor_name}-shm",
            )
            for name in names:
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
                    os.fchmod(descriptor, 0o600)
                finally:
                    os.close(descriptor)
        finally:
            os.close(parent_descriptor)

    @staticmethod
    def _rollback_quietly(connection: sqlite3.Connection) -> None:
        try:
            connection.rollback()
        except sqlite3.DatabaseError:
            pass

    @staticmethod
    def _insert_fact(
        connection: sqlite3.Connection,
        fact: ConfirmedProfileFact,
    ) -> None:
        connection.execute(
            """
            INSERT INTO profile_facts (
                scope,
                subject_id,
                field,
                value,
                source_turn_id,
                source_kind,
                confirmed_at,
                profile_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact.owner.scope,
                fact.owner.subject_id,
                fact.field,
                fact.value,
                fact.source_turn_id,
                fact.source_kind,
                fact.confirmed_at.isoformat(),
                fact.profile_version,
            ),
        )

    @staticmethod
    def _load(
        connection: sqlite3.Connection,
        owner: ProfileOwnerRef,
    ) -> ProfileSnapshot | None:
        profile_row = connection.execute(
            """
            SELECT version
            FROM profiles
            WHERE scope = ? AND subject_id = ?
            """,
            (owner.scope, owner.subject_id),
        ).fetchone()
        if profile_row is None:
            return None
        fact_rows = connection.execute(
            """
            SELECT
                field,
                value,
                source_turn_id,
                source_kind,
                confirmed_at,
                profile_version
            FROM profile_facts
            WHERE scope = ? AND subject_id = ?
            ORDER BY field ASC
            """,
            (owner.scope, owner.subject_id),
        ).fetchall()
        try:
            facts = [
                ConfirmedProfileFact(
                    owner=owner,
                    field=row[0],
                    value=row[1],
                    source_turn_id=row[2],
                    source_kind=row[3],
                    confirmed_at=datetime.fromisoformat(row[4]),
                    profile_version=row[5],
                )
                for row in fact_rows
            ]
            return ProfileSnapshot(
                owner=owner,
                version=profile_row[0],
                facts=facts,
            )
        except (TypeError, ValueError):
            raise ProfileStateCorrupt(owner.subject_id) from None
