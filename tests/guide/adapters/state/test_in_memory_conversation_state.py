from __future__ import annotations

from pathlib import Path

import pytest

from app.guide.adapters.state import InMemoryConversationState
from app.guide.adapters.state.sqlite_conversation_state import (
    SqliteConversationState,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConsultationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    KnowledgeSlotState,
    PendingClarificationSlot,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.feedback.ports import ConversationStateConflict
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.understanding.semantic_contracts import ClarificationCode


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _candidate(product_id: int, ordinal: int) -> DisplayedCandidateRef:
    return DisplayedCandidateRef(
        product_id=product_id,
        ordinal=ordinal,
        skin_match="unknown",
        matched_efficacies=(),
    )


def _snapshot(
    session_id: str,
    version: int,
    *,
    owner: ProfileOwnerRef | None = None,
) -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id=session_id,
        version=version,
        profile_owner=owner,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(
            slot="recommendation",
            ordinal=1,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=2,
            ),
            candidates=(_candidate(91, 1), _candidate(38, 2)),
            focused_candidate_ordinal=1,
        ),
    )


def _fully_populated_snapshot(
    session_id: str,
    version: int = 1,
) -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id=session_id,
        version=version,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(
            slot="recommendation",
            ordinal=1,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=2,
            ),
            candidates=(_candidate(91, 1), _candidate(38, 2)),
            focused_candidate_ordinal=1,
        ),
        product_slot=ProductSlotState(
            products=(_candidate(51, 1), _candidate(57, 2)),
            focused_evidence_ids=("a" * 64,),
        ),
        image_slot=ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
            ),
            focused_image_ordinal=1,
        ),
        consultation_slot=ConsultationSlotState(
            state=ConsultationSubstate(
                started_at_conversation_version=1,
            )
        ),
        knowledge_slot=KnowledgeSlotState(
            question="防晒为什么需要补涂",
            evidence_ids=("b" * 64,),
        ),
        reply_slot=PendingClarificationSlot(
            value=ClarificationProgress(
                gap=ClarificationCode.BUDGET,
                attempts=1,
            )
        ),
    )


def test_bool_expected_version_is_rejected() -> None:
    store = InMemoryConversationState()

    with pytest.raises(
        ValueError,
        match="expected_version must be a non-negative integer",
    ):
        store.save(
            _snapshot("bool-version", 1),
            expected_version=False,
        )


def test_store_compare_and_set_and_copy_isolation() -> None:
    store = InMemoryConversationState()
    first = store.save(_snapshot("cas", 1), expected_version=0)

    loaded = store.load("cas")
    assert loaded == first
    assert loaded is not first
    second = first.model_copy(update={"version": 2}, deep=True)
    assert store.save(second, expected_version=1) == second
    with pytest.raises(ConversationStateConflict):
        store.save(
            second.model_copy(update={"version": 3}, deep=True),
            expected_version=1,
        )


def test_delete_requires_matching_owner() -> None:
    owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="owner-delete-0001",
    )
    other = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="owner-delete-0002",
    )
    store = InMemoryConversationState()
    store.save(
        _snapshot("delete", 1, owner=owner),
        expected_version=0,
    )

    assert store.delete("delete", expected_owner=other) is False
    assert store.load("delete") is not None
    assert store.delete("delete", expected_owner=owner) is True
    assert store.load("delete") is None


def test_bound_profile_owner_cannot_change() -> None:
    first_owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="owner-stable-0001",
    )
    second_owner = ProfileOwnerRef(
        scope="anonymous_browser",
        subject_id="owner-stable-0002",
    )
    store = InMemoryConversationState()
    first = store.save(
        _snapshot("owner-stable", 1, owner=first_owner),
        expected_version=0,
    )

    with pytest.raises(ConversationStateConflict):
        store.save(
            _snapshot("owner-stable", 2, owner=second_owner),
            expected_version=1,
        )
    assert store.load("owner-stable") == first


def test_store_expires_by_injected_clock() -> None:
    clock = FakeClock()
    store = InMemoryConversationState(
        ttl_seconds=10,
        clock=clock,
    )
    store.save(_snapshot("expires", 1), expected_version=0)
    clock.value = 10

    assert store.load("expires") is None


def test_store_evicts_least_recently_updated_session() -> None:
    clock = FakeClock()
    store = InMemoryConversationState(
        max_sessions=2,
        clock=clock,
    )
    store.save(_snapshot("oldest", 1), expected_version=0)
    clock.value = 1
    store.save(_snapshot("newer", 1), expected_version=0)
    clock.value = 2
    store.save(_snapshot("newest", 1), expected_version=0)

    assert store.load("oldest") is None
    assert store.load("newer") is not None
    assert store.load("newest") is not None


def test_store_instances_do_not_share_state() -> None:
    first = InMemoryConversationState()
    second = InMemoryConversationState()
    first.save(_snapshot("isolated", 1), expected_version=0)

    assert second.load("isolated") is None


def test_snapshot_slots_round_trip_independently_in_both_stores(
    tmp_path: Path,
) -> None:
    stores = (
        InMemoryConversationState(),
        SqliteConversationState(
            tmp_path / "state" / "conversations.sqlite3",
            trusted_state_root=tmp_path / "state",
        ),
    )

    for index, store in enumerate(stores):
        original = _fully_populated_snapshot(
            f"six-slot-store-{index}",
        )
        first = store.save(original, expected_version=0)
        updated = first.model_copy(
            update={
                "version": 2,
                "knowledge_slot": KnowledgeSlotState(
                    question="UVA 和 UVB 有什么区别",
                    evidence_ids=("c" * 64,),
                ),
            },
            deep=True,
        )
        second = store.save(updated, expected_version=1)
        for slot_name in (
            "recommendation_slot",
            "product_slot",
            "image_slot",
            "consultation_slot",
            "reply_slot",
        ):
            assert getattr(second, slot_name).model_dump_json() == (
                getattr(first, slot_name).model_dump_json()
            )
