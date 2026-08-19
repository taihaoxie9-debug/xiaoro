from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from app.guide.adapters.state.sqlite_profile_state import (
    SqliteProfileState,
)
from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
    ProfileOwnerRef,
)
from app.guide.feedback.profile_state import ProfileStateCorrupt


_APPLICATION_ID = 0x58525046
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
_LEGACY_PROFILE_FACTS_SCHEMA = """
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


def _owner(scope: str, subject_id: str) -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope=scope,
        subject_id=subject_id,
    )


def _fact(
    owner: ProfileOwnerRef,
    *,
    value: str,
    source_turn_id: str,
) -> ConfirmedProfileFact:
    return ConfirmedProfileFact(
        owner=owner,
        field="skin_type",
        value=value,
        source_turn_id=source_turn_id,
        source_kind="confirmed_consultation",
        confirmed_at=datetime(2026, 8, 9, tzinfo=UTC),
        profile_version=1,
    )


def _create_legacy_database(
    path: Path,
    *,
    user_version: int = 1,
) -> None:
    path.parent.mkdir(mode=0o700, parents=True)
    path.parent.chmod(0o700)
    with sqlite3.connect(path) as connection:
        connection.execute(_LEGACY_PROFILES_SCHEMA)
        connection.execute(_LEGACY_PROFILE_FACTS_SCHEMA)
        connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {user_version}")
        for scope, value, turn in (
            (
                "authenticated_user",
                "dry",
                "turn_legacy_auth_0001",
            ),
            (
                "local_demo",
                "sensitive",
                "turn_legacy_demo_0001",
            ),
        ):
            subject_id = "shared_subject_0123456789"
            connection.execute(
                """
                INSERT INTO profiles (scope, subject_id, version)
                VALUES (?, ?, 1)
                """,
                (scope, subject_id),
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
                VALUES (?, ?, 'skin_type', ?, ?, ?, ?, 1)
                """,
                (
                    scope,
                    subject_id,
                    value,
                    turn,
                    "confirmed_consultation",
                    "2026-08-09T00:00:00+00:00",
                ),
            )
    path.chmod(0o600)


def test_anonymous_browser_is_an_explicit_owner_scope() -> None:
    owner = _owner(
        "anonymous_browser",
        "browser_subject_0123456789",
    )

    assert owner.scope == "anonymous_browser"
    assert owner.subject_id == "browser_subject_0123456789"


def test_schema_v1_migrates_and_keeps_existing_scopes_readable(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    database_path = state_root / "profiles.sqlite3"
    _create_legacy_database(database_path)

    state = SqliteProfileState(
        database_path,
        trusted_state_root=state_root,
    )

    authenticated = state.load(
        _owner(
            "authenticated_user",
            "shared_subject_0123456789",
        )
    )
    local_demo = state.load(
        _owner("local_demo", "shared_subject_0123456789")
    )
    assert authenticated is not None
    assert authenticated.facts[0].value == "dry"
    assert local_demo is not None
    assert local_demo.facts[0].value == "sensitive"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)


def test_migrated_store_isolates_same_subject_across_all_scopes(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    database_path = state_root / "profiles.sqlite3"
    _create_legacy_database(database_path)
    state = SqliteProfileState(
        database_path,
        trusted_state_root=state_root,
    )
    anonymous = _owner(
        "anonymous_browser",
        "shared_subject_0123456789",
    )

    anonymous_snapshot = state.save(
        _fact(
            anonymous,
            value="oily",
            source_turn_id="turn_anonymous_000001",
        ),
        expected_version=0,
    )

    assert anonymous_snapshot.owner == anonymous
    assert anonymous_snapshot.facts[0].value == "oily"
    assert state.load(
        _owner(
            "authenticated_user",
            "shared_subject_0123456789",
        )
    ).facts[0].value == "dry"
    assert state.load(
        _owner("local_demo", "shared_subject_0123456789")
    ).facts[0].value == "sensitive"


def test_anonymous_scope_does_not_enable_ownerless_access(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )

    with pytest.raises(TypeError, match="ProfileOwnerRef"):
        state.load(None)  # type: ignore[arg-type]


def test_unknown_schema_version_fails_closed_without_rebuild(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    database_path = state_root / "profiles.sqlite3"
    _create_legacy_database(database_path, user_version=99)
    before = database_path.read_bytes()

    with pytest.raises(ProfileStateCorrupt):
        SqliteProfileState(
            database_path,
            trusted_state_root=state_root,
        )

    assert database_path.read_bytes() == before
