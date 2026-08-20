from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
from threading import Lock
from typing import Iterator


_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_INITIALIZATION_LOCKS_GUARD = Lock()
_INITIALIZATION_LOCKS: dict[Path, Lock] = {}


class _PinnedDatabaseTarget(os.PathLike[str]):
    def __init__(self, *, descriptor: int, anchor_path: Path) -> None:
        self._descriptor_uri = f"file:/dev/fd/{descriptor}?mode=rw"
        self._anchor_uri = f"{anchor_path.as_uri()}?mode=rw"

    def __str__(self) -> str:
        return self._descriptor_uri

    def __fspath__(self) -> str:
        return self._anchor_uri


class _OpenedDatabaseFile:
    def __init__(
        self,
        *,
        name: str,
        descriptor: int,
        owns_descriptor: bool,
    ) -> None:
        self.name = name
        self.descriptor = descriptor
        self.owns_descriptor = owns_descriptor

    def verify(
        self,
        parent_descriptor: int,
        *,
        allow_missing: bool = False,
    ) -> bool:
        try:
            entry_stat = os.stat(
                self.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError as error:
            if allow_missing:
                return False
            raise ValueError(
                "state database file anchor changed"
            ) from error
        except OSError as error:
            raise ValueError(
                "state database file anchor changed"
            ) from error
        descriptor_stat = os.fstat(self.descriptor)
        if (
            (entry_stat.st_dev, entry_stat.st_ino)
            != (descriptor_stat.st_dev, descriptor_stat.st_ino)
            or stat.S_IFMT(entry_stat.st_mode)
            != stat.S_IFMT(descriptor_stat.st_mode)
            or not stat.S_ISREG(entry_stat.st_mode)
        ):
            raise ValueError("state database file anchor changed")
        return True

    def close(self) -> None:
        if self.owns_descriptor:
            os.close(self.descriptor)
            self.owns_descriptor = False


class _DatabaseFileAnchors:
    def __init__(
        self,
        *,
        storage: TrustedSqliteStorage,
        parent_descriptor: int,
        database_descriptor: int,
        anchor_descriptor: int,
    ) -> None:
        self._storage = storage
        self._parent_descriptor = parent_descriptor
        database_name = storage.database_relative_path.name
        anchor_name = storage._database_anchor_name(database_name)
        self._required_names = frozenset((database_name, anchor_name))
        self._files = {
            database_name: storage._bind_database_file_descriptor(
                parent_descriptor=parent_descriptor,
                name=database_name,
                descriptor=database_descriptor,
                owns_descriptor=False,
                secure_permissions=False,
            ),
            anchor_name: storage._bind_database_file_descriptor(
                parent_descriptor=parent_descriptor,
                name=anchor_name,
                descriptor=anchor_descriptor,
                owns_descriptor=False,
                secure_permissions=False,
            ),
        }
        try:
            self.verify()
        except BaseException:
            self.close()
            raise

    def verify(self) -> None:
        self._storage._verify_database_parent_anchor(
            self._parent_descriptor
        )
        for opened_file in tuple(self._files.values()):
            opened_file.verify(self._parent_descriptor)
        for name in self._storage._database_file_names():
            if name in self._files:
                continue
            opened_file = self._storage._open_database_file_anchor(
                parent_descriptor=self._parent_descriptor,
                name=name,
                required=False,
                secure_permissions=True,
            )
            if opened_file is not None:
                self._files[name] = opened_file
        self._storage._verify_database_parent_anchor(
            self._parent_descriptor
        )
        for opened_file in tuple(self._files.values()):
            opened_file.verify(self._parent_descriptor)

    def verify_after_connection_close(self) -> None:
        self._storage._verify_database_parent_anchor(
            self._parent_descriptor
        )
        for name, opened_file in tuple(self._files.items()):
            if name in self._required_names:
                opened_file.verify(self._parent_descriptor)
                continue
            if not opened_file.verify(
                self._parent_descriptor,
                allow_missing=True,
            ):
                opened_file.close()
                del self._files[name]
        for name in self._storage._database_file_names():
            if name in self._files:
                continue
            opened_file = self._storage._open_database_file_anchor(
                parent_descriptor=self._parent_descriptor,
                name=name,
                required=False,
                secure_permissions=True,
            )
            if opened_file is not None:
                self._files[name] = opened_file
        self._storage._verify_database_parent_anchor(
            self._parent_descriptor
        )

    def close(self) -> None:
        for opened_file in self._files.values():
            opened_file.close()
        self._files.clear()


class _AnchoredSqliteConnection(sqlite3.Connection):
    _database_file_anchors: _DatabaseFileAnchors | None = None

    def _bind_database_file_anchors(
        self,
        anchors: _DatabaseFileAnchors,
    ) -> None:
        if self._database_file_anchors is not None:
            raise RuntimeError("database file anchors are already bound")
        anchors.verify()
        self._database_file_anchors = anchors

    def _run_with_database_file_anchors(self, operation):
        anchors = self._database_file_anchors
        if anchors is None:
            return operation()
        anchors.verify()
        try:
            result = operation()
        except BaseException:
            anchors.verify()
            raise
        anchors.verify()
        return result

    def execute(self, sql, parameters=(), /):
        return self._run_with_database_file_anchors(
            lambda: super(_AnchoredSqliteConnection, self).execute(
                sql,
                parameters,
            )
        )

    def executemany(self, sql, parameters, /):
        return self._run_with_database_file_anchors(
            lambda: super(_AnchoredSqliteConnection, self).executemany(
                sql,
                parameters,
            )
        )

    def executescript(self, sql_script, /):
        return self._run_with_database_file_anchors(
            lambda: super(_AnchoredSqliteConnection, self).executescript(
                sql_script
            )
        )

    def commit(self) -> None:
        self._run_with_database_file_anchors(
            lambda: super(_AnchoredSqliteConnection, self).commit()
        )

    def rollback(self) -> None:
        self._run_with_database_file_anchors(
            lambda: super(_AnchoredSqliteConnection, self).rollback()
        )

    def close(self) -> None:
        anchors = self._database_file_anchors
        if anchors is None:
            super().close()
            return
        self._database_file_anchors = None
        failure: BaseException | None = None
        try:
            anchors.verify()
        except BaseException as error:
            failure = error
        try:
            super().close()
        except BaseException as error:
            if failure is None:
                failure = error
        try:
            anchors.verify_after_connection_close()
        except BaseException as error:
            if failure is None:
                failure = error
        finally:
            anchors.close()
        if failure is not None:
            raise failure


def _thread_initialization_lock(database_path: Path) -> Lock:
    with _INITIALIZATION_LOCKS_GUARD:
        return _INITIALIZATION_LOCKS.setdefault(database_path, Lock())


class TrustedSqliteStorage:
    """Pin one private SQLite file below a no-follow trusted root."""

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
        ) = self._prepare_storage(
            raw_database_path=raw_database_path,
            raw_state_root=raw_state_root,
        )

    @property
    def state_root(self) -> Path:
        return self._state_root

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def database_relative_path(self) -> Path:
        return self._database_relative_path

    @contextmanager
    def initialize(
        self,
    ) -> Iterator[tuple[sqlite3.Connection, bool]]:
        parent_descriptor: int | None = None
        database_descriptor: int | None = None
        anchor_descriptor: int | None = None
        with _thread_initialization_lock(self._database_path):
            try:
                parent_descriptor = self._open_database_parent()
                fcntl.flock(parent_descriptor, fcntl.LOCK_EX)
                database_descriptor, created = self._open_database_file(
                    parent_descriptor,
                    create=True,
                )
                anchor_descriptor = self._open_database_anchor(
                    parent_descriptor,
                    database_descriptor,
                )
                with self.connect(
                    parent_descriptor=parent_descriptor,
                    database_descriptor=database_descriptor,
                    anchor_descriptor=anchor_descriptor,
                ) as connection:
                    yield connection, created
                self.assert_database_containment()
            finally:
                if anchor_descriptor is not None:
                    os.close(anchor_descriptor)
                if database_descriptor is not None:
                    os.close(database_descriptor)
                if parent_descriptor is not None:
                    fcntl.flock(parent_descriptor, fcntl.LOCK_UN)
                    os.close(parent_descriptor)
                self.secure_database_files()

    @contextmanager
    def connect(
        self,
        *,
        parent_descriptor: int | None = None,
        database_descriptor: int | None = None,
        anchor_descriptor: int | None = None,
    ) -> Iterator[sqlite3.Connection]:
        borrowed = parent_descriptor is not None
        if borrowed != (
            database_descriptor is not None
            and anchor_descriptor is not None
        ):
            raise ValueError("database descriptors must be supplied together")
        if not borrowed:
            parent_descriptor = self._open_database_parent()
            fcntl.flock(parent_descriptor, fcntl.LOCK_EX)
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
        file_anchors: _DatabaseFileAnchors | None = None
        try:
            self._verify_database_anchor(
                parent_descriptor=parent_descriptor,
                database_descriptor=database_descriptor,
                anchor_descriptor=anchor_descriptor,
            )
            file_anchors = _DatabaseFileAnchors(
                storage=self,
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
                factory=_AnchoredSqliteConnection,
            )
            file_anchors.verify()
            if not isinstance(connection, _AnchoredSqliteConnection):
                raise TypeError(
                    "trusted SQLite connection factory was bypassed"
                )
            connection._bind_database_file_anchors(file_anchors)
            file_anchors = None
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
            if file_anchors is not None:
                file_anchors.close()
            if not borrowed:
                os.close(anchor_descriptor)
                os.close(database_descriptor)
                fcntl.flock(parent_descriptor, fcntl.LOCK_UN)
                os.close(parent_descriptor)

    def assert_database_containment(self) -> None:
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
        anchor_stat = resolved_anchor.stat()
        if (
            not resolved_anchor.is_relative_to(self._state_root)
            or not stat.S_ISREG(anchor_stat.st_mode)
            or stat.S_IMODE(anchor_stat.st_mode) != 0o600
            or (anchor_stat.st_dev, anchor_stat.st_ino)
            != (database_stat.st_dev, database_stat.st_ino)
        ):
            raise PermissionError("state database anchor must be private")

    def secure_database_files(self) -> None:
        parent_descriptor = self._open_database_parent()
        try:
            self._verify_database_parent_anchor(parent_descriptor)
            for name in self._database_file_names():
                opened_file = self._open_database_file_anchor(
                    parent_descriptor=parent_descriptor,
                    name=name,
                    required=False,
                    secure_permissions=True,
                )
                if opened_file is None:
                    self._verify_database_parent_anchor(
                        parent_descriptor
                    )
                    continue
                try:
                    opened_file.verify(parent_descriptor)
                    self._verify_database_parent_anchor(
                        parent_descriptor
                    )
                finally:
                    opened_file.close()
            self._verify_database_parent_anchor(parent_descriptor)
        finally:
            os.close(parent_descriptor)

    @staticmethod
    def _absolute_path(path: str | os.PathLike[str]) -> Path:
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
    ) -> tuple[Path, Path, Path]:
        if raw_state_root.is_symlink():
            raise ValueError("state directory must not be a symlink")
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
            os.close(parent_descriptor)
        finally:
            os.close(root_descriptor)
        return state_root, state_root / relative_path, relative_path

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
                or any(
                    part in ("", ".", "..")
                    for part in relative_path.parts
                )
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
    def _validate_private_directory(
        descriptor: int,
        *,
        secure_permissions: bool = True,
    ) -> None:
        directory_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ValueError("state directory must be a directory")
        if directory_stat.st_uid != os.geteuid():
            raise PermissionError(
                "state directory must be owned by the current user"
            )
        if secure_permissions:
            os.fchmod(descriptor, 0o700)

    @classmethod
    def _traverse_parent_directories(
        cls,
        root_descriptor: int,
        parts: tuple[str, ...],
        *,
        create: bool,
        secure_permissions: bool = True,
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
                    current_descriptor,
                    secure_permissions=secure_permissions,
                )
            return current_descriptor
        except BaseException:
            os.close(current_descriptor)
            raise

    def _open_database_parent(
        self,
        *,
        secure_permissions: bool = True,
    ) -> int:
        root_descriptor = self._open_directory(self._state_root)
        try:
            self._validate_private_directory(
                root_descriptor,
                secure_permissions=secure_permissions,
            )
            return self._traverse_parent_directories(
                root_descriptor,
                self._database_relative_path.parent.parts,
                create=False,
                secure_permissions=secure_permissions,
            )
        finally:
            os.close(root_descriptor)

    def _verify_database_parent_anchor(
        self,
        parent_descriptor: int,
    ) -> None:
        expected_stat = os.fstat(parent_descriptor)
        current_descriptor: int | None = None
        try:
            current_descriptor = self._open_database_parent(
                secure_permissions=False,
            )
            current_stat = os.fstat(current_descriptor)
        except OSError as error:
            raise ValueError(
                "state database parent anchor changed"
            ) from error
        except (PermissionError, ValueError) as error:
            raise ValueError(
                "state database parent anchor changed"
            ) from error
        finally:
            if current_descriptor is not None:
                os.close(current_descriptor)
        if (
            not stat.S_ISDIR(expected_stat.st_mode)
            or not stat.S_ISDIR(current_stat.st_mode)
            or (expected_stat.st_dev, expected_stat.st_ino)
            != (current_stat.st_dev, current_stat.st_ino)
        ):
            raise ValueError("state database parent anchor changed")

    def _database_file_names(self) -> tuple[str, ...]:
        database_name = self._database_relative_path.name
        anchor_name = self._database_anchor_name(database_name)
        return (
            database_name,
            f"{database_name}-wal",
            f"{database_name}-shm",
            anchor_name,
            f"{anchor_name}-wal",
            f"{anchor_name}-shm",
        )

    def _open_database_file_anchor(
        self,
        *,
        parent_descriptor: int,
        name: str,
        required: bool,
        secure_permissions: bool,
    ) -> _OpenedDatabaseFile | None:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | _NO_FOLLOW | _CLOSE_ON_EXEC,
                dir_fd=parent_descriptor,
            )
        except FileNotFoundError:
            if required:
                raise ValueError(
                    "state database file anchor changed"
                ) from None
            return None
        except OSError as error:
            raise ValueError(
                "state database files must not be symlinks"
            ) from error
        try:
            return self._bind_database_file_descriptor(
                parent_descriptor=parent_descriptor,
                name=name,
                descriptor=descriptor,
                owns_descriptor=True,
                secure_permissions=secure_permissions,
            )
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _bind_database_file_descriptor(
        *,
        parent_descriptor: int,
        name: str,
        descriptor: int,
        owns_descriptor: bool,
        secure_permissions: bool,
    ) -> _OpenedDatabaseFile:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(
                "state database files must be regular files"
            )
        if file_stat.st_uid != os.geteuid():
            raise PermissionError(
                "state database files must be owned by current user"
            )
        opened_file = _OpenedDatabaseFile(
            name=name,
            descriptor=descriptor,
            owns_descriptor=owns_descriptor,
        )
        opened_file.verify(parent_descriptor)
        if secure_permissions:
            os.fchmod(descriptor, 0o600)
            opened_file.verify(parent_descriptor)
        return opened_file

    def _open_database_file(
        self,
        parent_descriptor: int,
        *,
        create: bool,
    ) -> tuple[int, bool]:
        created = False
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
                pass
            else:
                created = True
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
    def _validate_database_descriptor(descriptor: int) -> None:
        database_stat = os.fstat(descriptor)
        if not stat.S_ISREG(database_stat.st_mode):
            raise ValueError("state database must be a regular file")
        if database_stat.st_uid != os.geteuid():
            raise PermissionError(
                "state database must be owned by the current user"
            )
        os.fchmod(descriptor, 0o600)

    @staticmethod
    def _database_anchor_name(database_name: str) -> str:
        return f".{database_name}.inode"

    @property
    def _database_anchor_path(self) -> Path:
        return (
            self._database_path.parent
            / self._database_anchor_name(self._database_relative_path.name)
        )

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
