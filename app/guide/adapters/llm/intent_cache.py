"""Slice: 校验后语义意图缓存。

只缓存经过 strict validation 的 SemanticIntentProposal（以 LLMCacheEntry
形式）。缓存键指纹包含 provider、base URL、model、prompt version、schema
version、typed context hash 与 generation parameters，因此不同身份不会错误命中。

持久层用 SQLite；进程内用 monotonic 判活（TTL 24h），持久层用 epoch 记录
年龄；上限 512 条，超限按事务内单调 last_access_rank 做确定性 LRU 淘汰。

绝不存原始 API Key，绝不存原始用户消息明文——消息只以 sha256 摘要参与
context 指纹，不落库。
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterator

from pydantic import BaseModel

from app.guide.adapters.llm.contracts import (
    LLMCacheEntry,
    LLMCacheKey,
    LLMGenerationParameters,
    LLMThinkingContract,
)
from app.guide.adapters.state.trusted_sqlite_storage import (
    TrustedSqliteStorage,
)
from app.guide.understanding.semantic_contracts import SemanticContext


_DEFAULT_MAX_ENTRIES = 512
_DEFAULT_TTL_SECONDS = 24 * 60 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS intent_cache (
    fingerprint TEXT PRIMARY KEY,
    entry_json TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL,
    last_access_epoch INTEGER NOT NULL,
    last_access_rank INTEGER NOT NULL
)
"""


def _context_sha256(
    *,
    message: str,
    context: SemanticContext,
    stage_identity: BaseModel | None,
) -> str:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    if not isinstance(context, SemanticContext):
        raise TypeError("context must be a SemanticContext")
    if stage_identity is not None and not isinstance(
        stage_identity,
        BaseModel,
    ):
        raise TypeError("stage_identity must be a Pydantic model")
    payload = json.dumps(
        {
            "message_sha256": hashlib.sha256(
                message.encode("utf-8")
            ).hexdigest(),
            "context": context.model_dump(mode="json"),
            "stage_identity": (
                stage_identity.model_dump(mode="json")
                if stage_identity is not None
                else None
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_intent_cache_key(
    *,
    stage: str,
    result_schema: type[BaseModel],
    provider: str,
    base_url: str,
    model: str,
    prompt_version: str,
    message: str,
    context: SemanticContext,
    temperature: float,
    max_tokens: int,
    enable_thinking: bool | None = False,
    thinking: LLMThinkingContract | None = None,
    stage_identity: BaseModel | None = None,
) -> LLMCacheKey:
    """Build a validated cache key binding the full request identity."""
    if not isinstance(result_schema, type) or not issubclass(
        result_schema,
        BaseModel,
    ):
        raise TypeError("result_schema must be a BaseModel subclass")
    schema_version = getattr(result_schema, "schema_version", None)
    if not isinstance(schema_version, str) or not schema_version:
        raise TypeError("result schema requires schema_version")
    return LLMCacheKey(
        stage=stage,
        provider=provider,
        base_url=base_url,
        model=model,
        prompt_version=prompt_version,
        schema_version=schema_version,
        context_sha256=_context_sha256(
            message=message,
            context=context,
            stage_identity=stage_identity,
        ),
        generation_parameters=LLMGenerationParameters(
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            thinking=thinking,
        ),
    )


class IntentProposalCache:
    """Bounded, TTL/LRU SQLite cache for validated intent proposals."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        trusted_state_root: str | os.PathLike[str],
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            not isinstance(max_entries, int)
            or isinstance(max_entries, bool)
            or max_entries <= 0
        ):
            raise ValueError("max_entries must be a positive integer")
        if (
            not isinstance(ttl_seconds, (int, float))
            or isinstance(ttl_seconds, bool)
            or ttl_seconds <= 0
        ):
            raise ValueError("ttl_seconds must be a positive number")
        self._storage = TrustedSqliteStorage(
            database_path,
            trusted_state_root=trusted_state_root,
        )
        self._database_path = self._storage.database_path
        self._max_entries = max_entries
        self._ttl_seconds = float(ttl_seconds)
        self._monotonic = monotonic
        self._base_monotonic = monotonic()
        self._base_epoch = int(time.time())
        with self._storage.initialize() as (connection, _created):
            journal_mode = connection.execute(
                "PRAGMA journal_mode = WAL"
            ).fetchone()
            if journal_mode != ("wal",):
                raise sqlite3.DatabaseError("WAL mode is unavailable")
            self._initialize_schema(connection)

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def trusted_state_root(self) -> Path:
        return self._storage.state_root

    def get(self, key: LLMCacheKey) -> LLMCacheEntry | None:
        if not isinstance(key, LLMCacheKey):
            raise TypeError("key must be an LLMCacheKey")
        fingerprint = key.fingerprint()
        now_epoch = self._now_epoch()
        with self._connect() as connection:
            with self._write_transaction(connection):
                row = connection.execute(
                    """
                    SELECT entry_json, created_at_epoch
                    FROM intent_cache
                    WHERE fingerprint = ?
                    """,
                    (fingerprint,),
                ).fetchone()
                if row is None:
                    return None
                entry_json, created_at_epoch = row
                if self._is_expired(created_at_epoch, now_epoch):
                    connection.execute(
                        "DELETE FROM intent_cache WHERE fingerprint = ?",
                        (fingerprint,),
                    )
                    return None
                access_rank = self._next_access_rank(connection)
                connection.execute(
                    """
                    UPDATE intent_cache
                    SET last_access_epoch = ?,
                        last_access_rank = ?
                    WHERE fingerprint = ?
                    """,
                    (now_epoch, access_rank, fingerprint),
                )
        try:
            payload = json.loads(entry_json)
        except (TypeError, ValueError):
            return None
        try:
            return LLMCacheEntry.from_cache_payload(payload)
        except (TypeError, ValueError):
            return None

    def put(self, key: LLMCacheKey, entry: LLMCacheEntry) -> None:
        if not isinstance(key, LLMCacheKey):
            raise TypeError("key must be an LLMCacheKey")
        if not isinstance(entry, LLMCacheEntry):
            raise TypeError("entry must be a validated LLMCacheEntry")
        if entry.schema_version != key.schema_version:
            raise ValueError(
                "cache entry schema version must match the cache key"
            )
        fingerprint = key.fingerprint()
        now_epoch = self._now_epoch()
        entry_json = json.dumps(
            entry.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            with self._write_transaction(connection):
                access_rank = self._next_access_rank(connection)
                connection.execute(
                    """
                    INSERT INTO intent_cache (
                        fingerprint,
                        entry_json,
                        created_at_epoch,
                        last_access_epoch,
                        last_access_rank
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        entry_json = excluded.entry_json,
                        created_at_epoch = excluded.created_at_epoch,
                        last_access_epoch = excluded.last_access_epoch,
                        last_access_rank = excluded.last_access_rank
                    """,
                    (
                        fingerprint,
                        entry_json,
                        now_epoch,
                        now_epoch,
                        access_rank,
                    ),
                )
                self._evict_if_needed(connection)

    def size(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM intent_cache"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def _evict_if_needed(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT COUNT(*) FROM intent_cache"
        ).fetchone()
        count = int(row[0]) if row is not None else 0
        overflow = count - self._max_entries
        if overflow <= 0:
            return
        connection.execute(
            """
            DELETE FROM intent_cache
            WHERE fingerprint IN (
                SELECT fingerprint
                FROM intent_cache
                ORDER BY last_access_rank ASC, fingerprint ASC
                LIMIT ?
            )
            """,
            (overflow,),
        )

    def _is_expired(self, created_at_epoch: int, now_epoch: int) -> bool:
        return now_epoch - int(created_at_epoch) >= self._ttl_seconds

    def _now_epoch(self) -> int:
        elapsed = self._monotonic() - self._base_monotonic
        return self._base_epoch + int(elapsed)

    def _initialize_schema(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        with self._write_transaction(connection):
            connection.execute(_SCHEMA)
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(intent_cache)"
                )
            }
            if "last_access_rank" in columns:
                return
            connection.execute(
                """
                ALTER TABLE intent_cache
                ADD COLUMN last_access_rank INTEGER NOT NULL DEFAULT 0
                """
            )
            fingerprints = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT fingerprint
                    FROM intent_cache
                    ORDER BY last_access_epoch ASC, fingerprint ASC
                    """
                )
            ]
            for rank, fingerprint in enumerate(fingerprints, start=1):
                connection.execute(
                    """
                    UPDATE intent_cache
                    SET last_access_rank = ?
                    WHERE fingerprint = ?
                    """,
                    (rank, fingerprint),
                )

    @staticmethod
    def _next_access_rank(
        connection: sqlite3.Connection,
    ) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(last_access_rank), 0) FROM intent_cache"
        ).fetchone()
        return int(row[0]) + 1 if row is not None else 1

    @staticmethod
    @contextmanager
    def _write_transaction(
        connection: sqlite3.Connection,
    ) -> Iterator[None]:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._storage.connect() as connection:
                yield connection
        finally:
            self._storage.secure_database_files()


__all__ = [
    "IntentProposalCache",
    "build_intent_cache_key",
]
