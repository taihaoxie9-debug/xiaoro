from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import multiprocessing
import os
from pathlib import Path
import sqlite3
import stat
from threading import Barrier

import pytest

from app.guide.adapters.state.sqlite_profile_state import SqliteProfileState
from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
    ProfileOwnerRef,
)
from app.guide.feedback.profile_state import (
    ProfileStateConflict,
    ProfileStateCorrupt,
)


def _owner(
    *,
    subject_id: str = "profile_0123456789abcdef",
) -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope="local_demo",
        subject_id=subject_id,
    )


def _fact(
    *,
    owner: ProfileOwnerRef | None = None,
    field: str = "skin_type",
    value: str = "sensitive",
    source_turn_id: str = "turn_0123456789abcdef",
    source_kind: str = "confirmed_consultation",
    confirmed_at: datetime = datetime(
        2026,
        8,
        9,
        2,
        30,
        tzinfo=UTC,
    ),
    profile_version: int = 1,
) -> ConfirmedProfileFact:
    return ConfirmedProfileFact(
        owner=owner or _owner(),
        field=field,
        value=value,
        source_turn_id=source_turn_id,
        source_kind=source_kind,
        confirmed_at=confirmed_at,
        profile_version=profile_version,
    )


def _state(tmp_path: Path) -> SqliteProfileState:
    state_root = tmp_path / "state"
    return SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )


def _multiprocess_cold_start(
    database_path: str,
    state_root: str,
    barrier: object,
    results: object,
) -> None:
    try:
        barrier.wait()
        state = SqliteProfileState(
            database_path,
            trusted_state_root=state_root,
        )
        version = state.save(_fact(), expected_version=0).version
    except BaseException as error:
        results.put(("error", type(error).__name__, str(error)))
    else:
        results.put(("ok", version))


def test_create_with_expected_zero_persists_confirmed_fact(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    fact = _fact()

    saved = state.save(fact, expected_version=0)

    assert saved.owner == fact.owner
    assert saved.version == 1
    assert saved.facts == (fact,)
    assert state.load(fact.owner) == saved


def test_missing_fields_increment_once_but_existing_fields_cannot_be_replaced(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    first = _fact()
    state.save(first, expected_version=0)
    brand = _fact(
        field="preferred_brand",
        value="CeraVe",
        source_turn_id="turn_brand_0123456789",
        source_kind="explicit_user",
        confirmed_at=datetime(2026, 8, 9, 2, 31, tzinfo=UTC),
        profile_version=2,
    )

    with_brand = state.save(brand, expected_version=1)

    assert with_brand.version == 2
    assert {
        fact.field: (fact.value, fact.profile_version)
        for fact in with_brand.facts
    } == {
        "preferred_brand": ("CeraVe", 2),
        "skin_type": ("sensitive", 1),
    }

    changed_skin = _fact(
        value="dry",
        source_turn_id="turn_skin_change_0001",
        source_kind="explicit_user",
        confirmed_at=datetime(2026, 8, 9, 2, 32, tzinfo=UTC),
        profile_version=3,
    )
    with pytest.raises(ProfileStateConflict):
        state.save(changed_skin, expected_version=2)

    assert state.load(first.owner) == with_brand


def test_exact_replay_is_idempotent_even_after_an_unrelated_change(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    first = _fact()
    created = state.save(first, expected_version=0)

    assert state.save(first, expected_version=0) == created

    second = _fact(
        field="ingredient_exclusion",
        value="fragrance",
        source_turn_id="turn_exclusion_000001",
        source_kind="explicit_user",
        confirmed_at=datetime(2026, 8, 9, 2, 31, tzinfo=UTC),
        profile_version=2,
    )
    updated = state.save(second, expected_version=1)

    assert state.save(first, expected_version=0) == updated
    assert state.load(first.owner) == updated


def test_stale_non_replay_save_conflicts_without_mutation(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    original = state.save(_fact(), expected_version=0)
    stale_change = _fact(
        field="preferred_category",
        value="sunscreen",
        source_turn_id="turn_category_0000001",
    )

    with pytest.raises(ProfileStateConflict):
        state.save(stale_change, expected_version=0)

    assert state.load(original.owner) == original


def test_stale_same_value_with_changed_metadata_is_idempotent(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    first = _fact()
    state.save(first, expected_version=0)
    second = _fact(
        field="preferred_category",
        value="sunscreen",
        source_turn_id="turn_category_0000001",
        profile_version=2,
    )
    current = state.save(second, expected_version=1)
    non_exact_replay = first.model_copy(
        update={
            "source_turn_id": "turn_replay_changed_001",
            "source_kind": "explicit_user",
            "confirmed_at": datetime(
                2026,
                8,
                9,
                2,
                32,
                tzinfo=UTC,
            ),
            "profile_version": 2,
        },
    )

    replayed = state.save(non_exact_replay, expected_version=0)

    assert replayed == current
    assert state.load(first.owner) == current
    stored = next(
        fact for fact in current.facts if fact.field == "skin_type"
    )
    assert stored == first


def test_loaded_snapshot_collections_and_nested_facts_are_immutable(
    tmp_path: Path,
) -> None:
    from pydantic import ValidationError

    state = _state(tmp_path)
    saved = state.save(_fact(), expected_version=0)

    assert isinstance(saved.facts, tuple)
    with pytest.raises(AttributeError):
        saved.facts.append(_fact())
    with pytest.raises(ValidationError):
        saved.facts[0].value = "dry"
    with pytest.raises(ValidationError):
        saved.owner.subject_id = "profile_changed_0123456789"


def test_concurrent_cold_start_exact_create_is_atomic_and_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "profiles.sqlite3"
    worker_count = 8
    barrier = Barrier(worker_count)
    fact = _fact()

    def create() -> int:
        barrier.wait()
        state = SqliteProfileState(
            database_path,
            trusted_state_root=database_path.parent,
        )
        return state.save(fact, expected_version=0).version

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        versions = list(
            executor.map(lambda _: create(), range(worker_count))
        )

    assert versions == [1] * worker_count
    restarted = SqliteProfileState(
        database_path,
        trusted_state_root=database_path.parent,
    )
    assert restarted.load(fact.owner) is not None
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM profiles"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM profile_facts"
        ).fetchone()[0] == 1


def test_atomic_write_disposition_distinguishes_concurrent_create_from_replay(
    tmp_path: Path,
) -> None:
    from app.guide.feedback.profile_state import ProfileWriteDisposition

    state = _state(tmp_path)
    barrier = Barrier(2)
    fact = _fact()

    def write_once() -> ProfileWriteDisposition:
        barrier.wait()
        return state.write_once(
            fact,
            expected_version=0,
        ).disposition

    with ThreadPoolExecutor(max_workers=2) as executor:
        dispositions = list(executor.map(lambda _: write_once(), range(2)))

    assert sorted(item.value for item in dispositions) == [
        "created",
        "idempotent",
    ]


def test_atomic_write_conflict_preserves_existing_value_and_provenance(
    tmp_path: Path,
) -> None:
    from app.guide.feedback.profile_state import ProfileWriteDisposition

    state = _state(tmp_path)
    original = _fact()
    created = state.write_once(original, expected_version=0)
    conflicting = _fact(
        value="dry",
        source_turn_id="turn_conflicting_00001",
        source_kind="explicit_user",
        confirmed_at=datetime(2026, 8, 9, 2, 32, tzinfo=UTC),
        profile_version=2,
    )

    result = state.write_once(conflicting, expected_version=1)

    assert created.disposition is ProfileWriteDisposition.CREATED
    assert result.disposition is ProfileWriteDisposition.CONFLICT
    assert result.stored_fact == original
    assert result.snapshot == created.snapshot
    assert state.load(original.owner) == created.snapshot


def test_multiprocess_cold_start_is_atomic_and_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "profiles.sqlite3"
    worker_count = 4
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(worker_count)
    results = context.Queue()
    processes = [
        context.Process(
            target=_multiprocess_cold_start,
            args=(
                str(database_path),
                str(database_path.parent),
                barrier,
                results,
            ),
        )
        for _ in range(worker_count)
    ]

    for process in processes:
        process.start()
    observed = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert observed == [("ok", 1)] * worker_count
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM profiles"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM profile_facts"
        ).fetchone()[0] == 1


def test_restart_persistence_and_owner_isolation(tmp_path: Path) -> None:
    database_path = tmp_path / "state" / "profiles.sqlite3"
    first_owner = _owner()
    second_owner = ProfileOwnerRef(
        scope="authenticated_user",
        subject_id=first_owner.subject_id,
    )
    state = SqliteProfileState(
        database_path,
        trusted_state_root=database_path.parent,
    )
    first = _fact(owner=first_owner)
    second = _fact(
        owner=second_owner,
        value="oily",
        source_turn_id="turn_other_owner_001",
    )

    first_saved = state.save(first, expected_version=0)
    second_saved = state.save(second, expected_version=0)
    restarted = SqliteProfileState(
        database_path,
        trusted_state_root=database_path.parent,
    )

    assert restarted.load(first_owner) == first_saved
    assert restarted.load(second_owner) == second_saved
    assert restarted.load(first_owner) != restarted.load(second_owner)
    assert restarted.load(
        _owner(subject_id="profile_missing_0123456789")
    ) is None


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "budget",
        "price_sensitivity",
        "transient_symptom",
        "unconfirmed_inference",
    ],
)
def test_sqlite_schema_rejects_non_durable_profile_fields(
    tmp_path: Path,
    forbidden_field: str,
) -> None:
    state = _state(tmp_path)
    fact = _fact()
    state.save(fact, expected_version=0)

    with sqlite3.connect(state.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
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
                    forbidden_field,
                    "must-not-persist",
                    "turn_forbidden_000001",
                    "explicit_user",
                    datetime(2026, 8, 9, 2, 31, tzinfo=UTC).isoformat(),
                    2,
                ),
            )


def test_sqlite_schema_contains_only_profile_provenance_columns(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)

    with sqlite3.connect(state.database_path) as connection:
        profile_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(profiles)"
            ).fetchall()
        }
        fact_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(profile_facts)"
            ).fetchall()
        }

    assert profile_columns == {"scope", "subject_id", "version"}
    assert fact_columns == {
        "scope",
        "subject_id",
        "field",
        "value",
        "source_turn_id",
        "source_kind",
        "confirmed_at",
        "profile_version",
    }


def test_sqlite_profile_state_uses_private_non_symlink_storage(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)

    assert stat.S_IMODE(state.database_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(state.database_path.stat().st_mode) == 0o600

    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        SqliteProfileState(
            linked_directory / "profiles.sqlite3",
            trusted_state_root=tmp_path,
        )

    private_directory = tmp_path / "private"
    private_directory.mkdir()
    target = tmp_path / "target.sqlite3"
    target.touch()
    linked_database = private_directory / "profiles.sqlite3"
    linked_database.symlink_to(target)
    with pytest.raises(ValueError, match="database.*symlink"):
        SqliteProfileState(
            linked_database,
            trusted_state_root=private_directory,
        )


def test_initialized_database_replaced_by_symlink_is_rejected_without_target_write(
    tmp_path: Path,
) -> None:
    source = _state(tmp_path / "source")
    target = _state(tmp_path / "target")
    target_owner = _owner(subject_id="profile_target_0123456789")
    target_saved = target.save(
        _fact(owner=target_owner),
        expected_version=0,
    )
    target_bytes = target.database_path.read_bytes()

    source.database_path.unlink()
    source.database_path.symlink_to(target.database_path)

    with pytest.raises(ValueError, match="database.*symlink"):
        source.save(
            _fact(
                owner=_owner(subject_id="profile_source_0123456789"),
            ),
            expected_version=0,
        )

    assert target.database_path.read_bytes() == target_bytes
    assert target.load(target_owner) == target_saved
    assert target.load(
        _owner(subject_id="profile_source_0123456789")
    ) is None


def test_database_reads_use_a_pinned_open_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.guide.adapters.state.sqlite_profile_state as profile_state

    state = _state(tmp_path)
    observed_database_arguments: list[str] = []
    real_connect = profile_state.sqlite3.connect

    def recording_connect(database: object, *args: object, **kwargs: object):
        observed_database_arguments.append(str(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(profile_state.sqlite3, "connect", recording_connect)

    assert state.load(_owner()) is None

    assert observed_database_arguments
    assert all(
        argument.startswith("file:/dev/fd/")
        for argument in observed_database_arguments
    )


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_sidecar_permission_hardening_does_not_follow_a_raced_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    state = _state(tmp_path)
    sidecar = Path(f"{state.database_path}{suffix}")
    sidecar.write_bytes(b"transient")
    sidecar.chmod(0o644)
    victim = tmp_path / "must-not-be-touched"
    victim.write_text("trusted", encoding="utf-8")
    victim.chmod(0o640)
    original_lstat = Path.lstat

    def replace_after_lstat(path: Path) -> os.stat_result:
        result = original_lstat(path)
        if path == sidecar:
            path.unlink()
            path.symlink_to(victim)
        return result

    monkeypatch.setattr(Path, "lstat", replace_after_lstat)

    try:
        state._secure_database_files()
    except ValueError:
        pass

    assert stat.S_IMODE(victim.stat().st_mode) == 0o640


def test_invalid_sqlite_file_is_corrupt_and_is_not_rewritten(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "profiles.sqlite3"
    database_path.parent.mkdir()
    original = b"not a sqlite database"
    database_path.write_bytes(original)

    with pytest.raises(ProfileStateCorrupt):
        SqliteProfileState(
            database_path,
            trusted_state_root=database_path.parent,
        )

    assert database_path.read_bytes() == original


def test_missing_schema_is_corrupt_and_is_not_auto_created(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "profiles.sqlite3"
    database_path.parent.mkdir()
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")

    with pytest.raises(ProfileStateCorrupt):
        SqliteProfileState(
            database_path,
            trusted_state_root=database_path.parent,
        )

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_schema
                WHERE type = 'table'
                """
            )
        }
    assert tables == {"unrelated"}


def test_incompatible_schema_is_corrupt_and_is_not_rebuilt(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "profiles.sqlite3"
    database_path.parent.mkdir()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE profiles (subject_id TEXT PRIMARY KEY)"
        )

    with pytest.raises(ProfileStateCorrupt):
        SqliteProfileState(
            database_path,
            trusted_state_root=database_path.parent,
        )

    with sqlite3.connect(database_path) as connection:
        columns = [
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(profiles)"
            )
        ]
        fact_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_schema
            WHERE type = 'table' AND name = 'profile_facts'
            """
        ).fetchone()
    assert columns == ["subject_id"]
    assert fact_table is None


def test_malformed_text_row_maps_to_profile_state_corrupt(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    fact = _fact()
    state.save(fact, expected_version=0)
    with sqlite3.connect(state.database_path) as connection:
        connection.execute(
            """
            UPDATE profile_facts
            SET value = CAST(X'80' AS TEXT)
            WHERE scope = ? AND subject_id = ?
            """,
            (fact.owner.scope, fact.owner.subject_id),
        )

    with pytest.raises(ProfileStateCorrupt):
        state.load(fact.owner)


def test_structural_database_error_maps_to_profile_state_corrupt(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    fact = _fact()
    state.save(fact, expected_version=0)
    with sqlite3.connect(state.database_path) as connection:
        connection.execute("DROP TABLE profile_facts")

    with pytest.raises(ProfileStateCorrupt):
        state.load(fact.owner)


def test_database_path_must_remain_inside_trusted_state_root(
    tmp_path: Path,
) -> None:
    trusted_root = tmp_path / "guide-state"
    outside = tmp_path / "outside"
    outside.mkdir()
    trusted_root.mkdir()
    redirected = trusted_root / "nested"
    redirected.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        SqliteProfileState(
            redirected / "profiles.sqlite3",
            trusted_state_root=trusted_root,
        )

    with pytest.raises(ValueError, match="outside trusted state root"):
        SqliteProfileState(
            outside / "profiles.sqlite3",
            trusted_state_root=trusted_root,
        )

    assert not (outside / "profiles.sqlite3").exists()


def test_trusted_root_canonicalization_preserves_containment_and_permissions(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "private" / "guide-state"
    real_root.mkdir(parents=True)
    root_alias = tmp_path / "guide-state-alias"
    root_alias.symlink_to(real_root, target_is_directory=True)
    database_path = real_root / "nested" / "profiles.sqlite3"

    state = SqliteProfileState(
        database_path,
        trusted_state_root=root_alias,
    )

    canonical_root = real_root.resolve()
    assert state.database_path == database_path.resolve()
    assert state.database_path.is_relative_to(canonical_root)
    assert stat.S_IMODE(canonical_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(state.database_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(state.database_path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("database_style", "trusted_root_style"),
    [
        pytest.param("var", "private", id="database-var-root-private-var"),
        pytest.param("private", "var", id="database-private-var-root-var"),
    ],
)
def test_macos_equivalent_paths_are_symmetric_for_containment(
    tmp_path: Path,
    database_style: str,
    trusted_root_style: str,
) -> None:
    private_root = (tmp_path / "guide-state").resolve(strict=False)
    try:
        relative_root = private_root.relative_to("/private/var")
    except ValueError:
        pytest.skip("requires a macOS /private/var temporary directory")
    var_root = Path("/var") / relative_root
    if var_root.resolve(strict=False) != private_root:
        pytest.skip("requires equivalent /var and /private/var paths")
    roots = {"private": private_root, "var": var_root}

    state = SqliteProfileState(
        roots[database_style] / "nested" / "profiles.sqlite3",
        trusted_state_root=roots[trusted_root_style],
    )

    assert state.database_path == (
        private_root / "nested" / "profiles.sqlite3"
    )
