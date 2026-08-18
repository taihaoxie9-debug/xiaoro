from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.guide.adapters.state.feedback_reference_resolvers import (
    RegisteredFeedbackConversationReferenceResolver,
    SqliteProfileFeedbackReferenceResolver,
)
from app.guide.adapters.state.sqlite_feedback_target_registry import (
    SqliteFeedbackTargetRegistry,
)
from app.guide.adapters.state.sqlite_profile_state import (
    SqliteProfileState,
)
from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.event_contracts import (
    FeedbackActorContext,
    FeedbackProfileVersionRef,
)
from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
    ProfileOwnerRef,
)
from app.guide.feedback.target_contracts import (
    TrustedFeedbackTarget,
)


_OWNER = ProfileOwnerRef(
    scope="authenticated_user",
    subject_id="authenticated-user-0123456789",
)
_FOREIGN_OWNER = ProfileOwnerRef(
    scope="authenticated_user",
    subject_id="authenticated-user-fedcba9876543210",
)
_REFERENCE = ConversationVersionRef(
    session_id="session-feedback-target",
    conversation_version=9,
)


def _actor(
    *,
    owner: ProfileOwnerRef = _OWNER,
    session_id: str = _REFERENCE.session_id,
) -> FeedbackActorContext:
    return FeedbackActorContext(
        owner=owner,
        authorized_session_id=session_id,
    )


def _target_registry(
    tmp_path: Path,
) -> SqliteFeedbackTargetRegistry:
    state_root = tmp_path / "target-state"
    return SqliteFeedbackTargetRegistry(
        state_root / "feedback_targets.sqlite3",
        trusted_state_root=state_root,
    )


def _record_target(
    registry: SqliteFeedbackTargetRegistry,
) -> TrustedFeedbackTarget:
    return registry.record_once(
        TrustedFeedbackTarget(
            owner=_OWNER,
            conversation=_REFERENCE,
            displayed_product_ids=(11, 22, 33, 44),
            profile=FeedbackProfileVersionRef(
                profile_version=3
            ),
        )
    )


def _profile_state(tmp_path: Path) -> SqliteProfileState:
    state_root = tmp_path / "profile-state"
    state = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    for index, (field, value) in enumerate(
        (
            ("skin_type", "sensitive"),
            ("skin_concern", "repair"),
            ("preferred_category", "serum"),
        ),
        start=1,
    ):
        state.save(
            ConfirmedProfileFact(
                owner=_OWNER,
                field=field,
                value=value,
                source_turn_id=f"turn-profile-source-{index:04d}",
                source_kind="explicit_user",
                confirmed_at=datetime(
                    2026,
                    8,
                    9,
                    4,
                    index,
                    tzinfo=UTC,
                ),
                profile_version=index,
            ),
            expected_version=index - 1,
        )
    return state


def test_conversation_resolver_reads_exact_registered_target(
    tmp_path: Path,
) -> None:
    registry = _target_registry(tmp_path)
    target = _record_target(registry)
    resolver = RegisteredFeedbackConversationReferenceResolver(
        registry
    )

    context = resolver.load(
        actor=_actor(),
        reference=_REFERENCE,
    )

    assert context is not None
    assert context.reference == target.conversation
    assert context.owner == target.owner
    assert context.product_ids == [11, 22, 33, 44]
    assert context.profile == target.profile


def test_conversation_resolver_survives_registry_restart(
    tmp_path: Path,
) -> None:
    registry = _target_registry(tmp_path)
    _record_target(registry)
    restarted = SqliteFeedbackTargetRegistry(
        registry.database_path,
        trusted_state_root=registry.database_path.parent,
    )

    context = RegisteredFeedbackConversationReferenceResolver(
        restarted
    ).load(actor=_actor(), reference=_REFERENCE)

    assert context is not None
    assert context.product_ids == [11, 22, 33, 44]


def test_conversation_resolver_fails_closed_for_non_exact_authority(
    tmp_path: Path,
) -> None:
    registry = _target_registry(tmp_path)
    _record_target(registry)
    resolver = RegisteredFeedbackConversationReferenceResolver(
        registry
    )
    attempts = (
        (
            _actor(session_id="session-authorized-elsewhere"),
            _REFERENCE,
        ),
        (
            _actor(owner=_FOREIGN_OWNER),
            _REFERENCE,
        ),
        (
            _actor(),
            _REFERENCE.model_copy(
                update={"session_id": "session-missing"}
            ),
        ),
        (
            _actor(),
            _REFERENCE.model_copy(
                update={"conversation_version": 8}
            ),
        ),
        (
            _actor(),
            _REFERENCE.model_copy(
                update={"conversation_version": 10}
            ),
        ),
    )

    assert [
        resolver.load(actor=actor, reference=reference)
        for actor, reference in attempts
    ] == [None] * len(attempts)


def test_profile_resolver_requires_exact_current_owner_version(
    tmp_path: Path,
) -> None:
    resolver = SqliteProfileFeedbackReferenceResolver(
        _profile_state(tmp_path)
    )

    assert resolver.exists(
        actor=_actor(),
        reference=FeedbackProfileVersionRef(
            profile_version=3
        ),
    )
    assert not resolver.exists(
        actor=_actor(),
        reference=FeedbackProfileVersionRef(
            profile_version=2
        ),
    )
    assert not resolver.exists(
        actor=_actor(),
        reference=FeedbackProfileVersionRef(
            profile_version=4
        ),
    )
    assert not resolver.exists(
        actor=_actor(owner=_FOREIGN_OWNER),
        reference=FeedbackProfileVersionRef(
            profile_version=3
        ),
    )


def test_profile_resolver_fails_closed_for_missing_and_corrupt_state(
    tmp_path: Path,
) -> None:
    profile_state = _profile_state(tmp_path)
    resolver = SqliteProfileFeedbackReferenceResolver(
        profile_state
    )
    reference = FeedbackProfileVersionRef(profile_version=3)

    assert not resolver.exists(
        actor=_actor(owner=_FOREIGN_OWNER),
        reference=reference,
    )

    with profile_state._connect() as connection:
        connection.execute("DROP TABLE profile_facts")

    assert not resolver.exists(
        actor=_actor(),
        reference=reference,
    )


def test_profile_resolver_fails_closed_after_database_redirect(
    tmp_path: Path,
) -> None:
    profile_state = _profile_state(tmp_path)
    resolver = SqliteProfileFeedbackReferenceResolver(
        profile_state
    )
    outside = tmp_path / "outside-profile"
    outside.write_bytes(b"do-not-touch")
    profile_state.database_path.unlink()
    profile_state.database_path.symlink_to(outside)

    assert not resolver.exists(
        actor=_actor(),
        reference=FeedbackProfileVersionRef(
            profile_version=3
        ),
    )
    assert outside.read_bytes() == b"do-not-touch"


def test_sync_resolvers_are_safe_for_threadpool_composition(
    tmp_path: Path,
) -> None:
    registry = _target_registry(tmp_path)
    _record_target(registry)
    conversation_resolver = (
        RegisteredFeedbackConversationReferenceResolver(registry)
    )
    profile_resolver = SqliteProfileFeedbackReferenceResolver(
        _profile_state(tmp_path)
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        conversations = list(
            executor.map(
                lambda _: conversation_resolver.load(
                    actor=_actor(),
                    reference=_REFERENCE,
                ),
                range(8),
            )
        )
        profiles = list(
            executor.map(
                lambda _: profile_resolver.exists(
                    actor=_actor(),
                    reference=FeedbackProfileVersionRef(
                        profile_version=3
                    ),
                ),
                range(8),
            )
        )

    assert all(context is not None for context in conversations)
    assert all(
        context.product_ids == [11, 22, 33, 44]
        for context in conversations
        if context is not None
    )
    assert profiles == [True] * 8
