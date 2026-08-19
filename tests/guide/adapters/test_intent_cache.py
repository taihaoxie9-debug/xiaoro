from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from app.guide.adapters.llm.contracts import (
    LLMCacheEntry,
    LLMCacheKey,
    LLMGenerationParameters,
    LLMSuccessStatus,
)
from app.guide.adapters.llm.intent_cache import (
    IntentProposalCache,
    build_intent_cache_key,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import (
    ConfirmedProfileField,
    SemanticContext,
    SemanticIntentProposal,
    SemanticGoal,
)
from app.guide.understanding.semantic_detail_contracts import (
    RecommendationDetails,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticRouteProposal,
)


def _context(
    *,
    conversation_version: int = 0,
    active_topic: TopicCode | None = None,
    visible_candidate_count: int = 0,
    confirmed_profile_fields: tuple[ConfirmedProfileField, ...] = (),
) -> SemanticContext:
    return SemanticContext(
        conversation_version=conversation_version,
        active_topic=active_topic,
        visible_candidate_count=visible_candidate_count,
        confirmed_profile_fields=confirmed_profile_fields,
    )


def _proposal(topic: TopicCode = TopicCode.SUNSCREEN) -> SemanticIntentProposal:
    return SemanticIntentProposal(
        goal=SemanticGoal.RECOMMENDATION,
        topic=topic,
        concerns=(),
        observations=(),
        references=(),
        confidence=0.97,
        clarification_hint=None,
    )


def _key(
    *,
    stage: str = "legacy-intent-v3",
    result_schema: type = SemanticIntentProposal,
    provider: str = "siliconflow",
    base_url: str = "https://api.siliconflow.cn/v1",
    model: str = "deepseek-ai/DeepSeek-V3.2",
    prompt_version: str = "guide-semantic-intent-prompt-v1",
    context: SemanticContext | None = None,
    temperature: float = 0.0,
    max_tokens: int = 256,
    enable_thinking: bool = False,
) -> LLMCacheKey:
    return build_intent_cache_key(
        stage=stage,
        result_schema=result_schema,
        provider=provider,
        base_url=base_url,
        model=model,
        prompt_version=prompt_version,
        message="夏天防止晒黑的东西",
        context=context or _context(),
        temperature=temperature,
        max_tokens=max_tokens,
        enable_thinking=enable_thinking,
    )


def _entry(
    key: LLMCacheKey,
    *,
    proposal: SemanticIntentProposal | None = None,
    status: LLMSuccessStatus = LLMSuccessStatus.PRIMARY_SUCCESS,
) -> LLMCacheEntry:
    return LLMCacheEntry.from_validated_result(
        key=key,
        result=proposal or _proposal(),
        result_schema=SemanticIntentProposal,
        actual_provider=key.provider,
        actual_model=key.model,
        status=status,
    )


def test_store_and_load_roundtrips_validated_proposal(tmp_path: Path) -> None:
    cache = IntentProposalCache(
        tmp_path / "intent_cache.sqlite3",
        trusted_state_root=tmp_path,
    )
    key = _key()

    assert cache.get(key) is None
    cache.put(key, _entry(key))

    loaded = cache.get(key)
    assert loaded is not None
    proposal = SemanticIntentProposal.model_validate_json(
        json.dumps(loaded.result),
        strict=True,
    )
    assert proposal.topic is TopicCode.SUNSCREEN
    assert loaded.actual_provider == "siliconflow"


def test_fingerprint_isolates_provider_model_prompt_and_context() -> None:
    baseline = _key()

    assert _key(provider="other").fingerprint() != baseline.fingerprint()
    assert _key(base_url="https://other.invalid").fingerprint() != (
        baseline.fingerprint()
    )
    assert _key(model="deepseek-ai/DeepSeek-V4-Flash").fingerprint() != (
        baseline.fingerprint()
    )
    assert _key(prompt_version="guide-semantic-intent-prompt-v2").fingerprint() != (
        baseline.fingerprint()
    )
    assert _key(max_tokens=512).fingerprint() != baseline.fingerprint()
    assert _key(
        context=_context(active_topic=TopicCode.FRAGRANCE)
    ).fingerprint() != baseline.fingerprint()
    assert _key(
        context=_context(
            confirmed_profile_fields=(ConfirmedProfileField.SKIN_TYPE,)
        )
    ).fingerprint() != baseline.fingerprint()


def test_route_and_detail_cache_keys_never_collide() -> None:
    route = _key(
        stage="route",
        result_schema=SemanticRouteProposal,
        prompt_version="guide-semantic-route-prompt-v1",
    )
    detail = _key(
        stage="detail:recommendation",
        result_schema=RecommendationDetails,
        prompt_version="guide-semantic-detail-prompt-v1",
    )

    assert route.stage == "route"
    assert detail.stage == "detail:recommendation"
    assert route.schema_version == SemanticRouteProposal.schema_version
    assert detail.schema_version == RecommendationDetails.schema_version
    assert route.fingerprint() != detail.fingerprint()


def test_detail_cache_identity_includes_validated_route() -> None:
    first_route = SemanticRouteProposal.model_validate_json(
        (
            '{"goal":"recommendation","topic":"sunscreen",'
            '"detail_stage":"recommendation","confidence":0.9,'
            '"clarification_hint":null}'
        ),
        strict=True,
    )
    second_route = first_route.model_copy(
        update={"topic": TopicCode.SERUM}
    )
    common = {
        "stage": "detail:recommendation",
        "result_schema": RecommendationDetails,
        "provider": "siliconflow",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3.2",
        "prompt_version": "guide-semantic-detail-prompt-v1",
        "message": "推荐一个",
        "context": _context(),
        "temperature": 0.0,
        "max_tokens": 128,
    }

    first = build_intent_cache_key(
        **common,
        stage_identity=first_route,
    )
    second = build_intent_cache_key(
        **common,
        stage_identity=second_route,
    )

    assert first.fingerprint() != second.fingerprint()


def test_fingerprint_isolates_thinking_mode() -> None:
    disabled = _key(enable_thinking=False)
    enabled = _key(enable_thinking=True)

    assert disabled.generation_parameters.enable_thinking is False
    assert enabled.generation_parameters.enable_thinking is True
    assert disabled.fingerprint() != enabled.fingerprint()


def test_schema_version_is_part_of_the_fingerprint_identity() -> None:
    key = _key()
    assert key.schema_version == SemanticIntentProposal.schema_version
    assert key.schema_version in key.model_dump_json()


def test_same_message_and_context_hit_without_second_provider_call(
    tmp_path: Path,
) -> None:
    cache = IntentProposalCache(
        tmp_path / "intent_cache.sqlite3",
        trusted_state_root=tmp_path,
    )
    key = _key()
    cache.put(key, _entry(key))

    identical = _key()
    assert identical.fingerprint() == key.fingerprint()
    assert cache.get(identical) is not None


def test_eviction_is_bounded_and_lru_by_last_access(tmp_path: Path) -> None:
    cache = IntentProposalCache(
        tmp_path / "intent_cache.sqlite3",
        trusted_state_root=tmp_path,
        max_entries=2,
    )
    first = _key(context=_context(conversation_version=1))
    second = _key(context=_context(conversation_version=2))
    third = _key(context=_context(conversation_version=3))

    cache.put(first, _entry(first))
    cache.put(second, _entry(second))
    assert cache.get(first) is not None  # first becomes most-recently used

    cache.put(third, _entry(third))

    assert cache.get(second) is None  # least-recently used evicted
    assert cache.get(first) is not None
    assert cache.get(third) is not None
    assert cache.size() == 2


def test_frozen_clock_hit_updates_monotonic_lru_rank(
    tmp_path: Path,
) -> None:
    cache = IntentProposalCache(
        tmp_path / "intent_cache.sqlite3",
        trusted_state_root=tmp_path,
        max_entries=2,
        monotonic=lambda: 100.0,
    )
    first = _key(context=_context(conversation_version=2))
    second = _key(context=_context(conversation_version=1))
    third = _key(context=_context(conversation_version=3))

    cache.put(first, _entry(first))
    cache.put(second, _entry(second))
    assert cache.get(first) is not None
    cache.put(third, _entry(third))

    assert cache.get(first) is not None
    assert cache.get(second) is None
    assert cache.get(third) is not None

    with sqlite3.connect(cache.database_path) as connection:
        ranks = [
            row[0]
            for row in connection.execute(
                """
                SELECT last_access_rank
                FROM intent_cache
                ORDER BY last_access_rank
                """
            )
        ]
    assert len(ranks) == len(set(ranks))
    assert ranks == sorted(ranks)


def test_expired_entries_are_not_returned(tmp_path: Path) -> None:
    clock = iter([100.0, 100.0, 100.0 + 24 * 3600 + 1])
    cache = IntentProposalCache(
        tmp_path / "intent_cache.sqlite3",
        trusted_state_root=tmp_path,
        ttl_seconds=24 * 3600,
        monotonic=lambda: next(clock),
    )
    key = _key()
    cache.put(key, _entry(key))

    assert cache.get(key) is None


def test_persisted_rows_never_contain_message_or_api_key(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "intent_cache.sqlite3"
    cache = IntentProposalCache(
        database_path,
        trusted_state_root=tmp_path,
    )
    key = build_intent_cache_key(
        stage="legacy-intent-v3",
        result_schema=SemanticIntentProposal,
        provider="siliconflow",
        base_url="https://api.siliconflow.cn/v1",
        model="deepseek-ai/DeepSeek-V3.2",
        prompt_version="guide-semantic-intent-prompt-v1",
        message="这是一条包含敏感明文的消息",
        context=_context(),
        temperature=0.0,
        max_tokens=256,
    )
    cache.put(key, _entry(key))

    with sqlite3.connect(database_path) as connection:
        blob = "\n".join(
            str(value)
            for row in connection.execute("SELECT * FROM intent_cache")
            for value in row
        )
    assert "这是一条包含敏感明文的消息" not in blob


def test_reopen_database_preserves_valid_entries(tmp_path: Path) -> None:
    database_path = tmp_path / "intent_cache.sqlite3"
    key = _key()
    IntentProposalCache(
        database_path,
        trusted_state_root=tmp_path,
    ).put(key, _entry(key))

    reopened = IntentProposalCache(
        database_path,
        trusted_state_root=tmp_path,
    )
    assert reopened.get(key) is not None


def test_existing_epoch_cache_migrates_to_access_rank(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "intent_cache.sqlite3"
    key = _key()
    entry = _entry(key)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE intent_cache (
                fingerprint TEXT PRIMARY KEY,
                entry_json TEXT NOT NULL,
                created_at_epoch INTEGER NOT NULL,
                last_access_epoch INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO intent_cache (
                fingerprint,
                entry_json,
                created_at_epoch,
                last_access_epoch
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                key.fingerprint(),
                json.dumps(entry.model_dump(mode="json")),
                int(time.time()),
                int(time.time()),
            ),
        )

    cache = IntentProposalCache(
        database_path,
        trusted_state_root=tmp_path,
    )

    assert cache.get(key) is not None
    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(intent_cache)"
            )
        }
        rank = connection.execute(
            """
            SELECT last_access_rank
            FROM intent_cache
            WHERE fingerprint = ?
            """,
            (key.fingerprint(),),
        ).fetchone()
    assert "last_access_rank" in columns
    assert rank is not None and rank[0] > 0


def test_cache_rejects_symlink_database_leaf_without_touching_target(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    target = tmp_path / "protected.sqlite3"
    target.write_bytes(b"protected")
    database_path = state_root / "intent_cache.sqlite3"
    database_path.symlink_to(target)

    with pytest.raises(ValueError, match="database.*symlink"):
        IntentProposalCache(
            database_path,
            trusted_state_root=state_root,
        )

    assert target.read_bytes() == b"protected"


def test_cache_rejects_symlink_parent_below_trusted_root(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked_parent = state_root / "nested"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="path components.*symlinks"):
        IntentProposalCache(
            linked_parent / "intent_cache.sqlite3",
            trusted_state_root=state_root,
        )


def test_cache_rejects_database_outside_trusted_root(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    outside = tmp_path / "outside" / "intent_cache.sqlite3"

    with pytest.raises(ValueError, match="outside trusted state root"):
        IntentProposalCache(
            outside,
            trusted_state_root=state_root,
        )


def test_cache_rejects_non_regular_database_leaf(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    database_path = state_root / "intent_cache.sqlite3"
    database_path.mkdir()

    with pytest.raises(ValueError, match="regular file"):
        IntentProposalCache(
            database_path,
            trusted_state_root=state_root,
        )


def test_cache_rejects_parent_drift_after_initialization(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    nested = state_root / "nested"
    cache = IntentProposalCache(
        nested / "intent_cache.sqlite3",
        trusted_state_root=state_root,
    )
    moved = state_root / "moved"
    nested.rename(moved)
    nested.symlink_to(moved, target_is_directory=True)

    with pytest.raises(ValueError, match="path components.*symlinks"):
        cache.size()
