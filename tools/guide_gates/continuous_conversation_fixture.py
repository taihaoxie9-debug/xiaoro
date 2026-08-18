from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher
from hashlib import sha256
import json
from pathlib import Path
import random
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.guide_gates.continuous_conversation_gate import (
    ContinuousTrajectory,
)


BACKEND_SELECTION_SEED = 2026081701
DEFAULT_POOL_PATH = Path(
    "tests/fixtures/guide/conversation/"
    "continuous_trajectory_pool_v1.jsonl"
)
DEFAULT_FROZEN_PATH = Path(
    "tests/fixtures/guide/conversation/"
    "continuous_20x5_v1.jsonl"
)
DEFAULT_MANIFEST_PATH = Path(
    "tests/fixtures/guide/conversation/"
    "continuous_20x5_v1_manifest.json"
)


class ContinuousFixtureManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )

    schema_version: Literal[
        "guide-continuous-fixture-manifest-v1"
    ] = "guide-continuous-fixture-manifest-v1"
    pool_file: Literal[
        "continuous_trajectory_pool_v1.jsonl"
    ] = "continuous_trajectory_pool_v1.jsonl"
    selected_file: Literal[
        "continuous_20x5_v1.jsonl"
    ] = "continuous_20x5_v1.jsonl"
    selection_seed: Literal[
        2026081701
    ] = BACKEND_SELECTION_SEED
    pool_count: int = Field(ge=30)
    selected_count: Literal[20] = 20
    selected_turn_count: Literal[100] = 100
    pool_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_messages_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )


def normalize_message(message: str) -> str:
    if not isinstance(message, str):
        raise TypeError("message must be a string")
    normalized = unicodedata.normalize("NFKC", message).casefold()
    return "".join(
        character
        for character in normalized
        if not (
            character.isspace()
            or unicodedata.category(character).startswith("P")
        )
    )


def no_simple_paraphrase_pairs(
    trajectories: Sequence[ContinuousTrajectory],
) -> bool:
    normalized = tuple(
        (
            trajectory.trajectory_id,
            tuple(
                normalize_message(turn.message)
                for turn in trajectory.turns
            ),
        )
        for trajectory in trajectories
    )
    for left_index, (_, left_turns) in enumerate(normalized):
        for _, right_turns in normalized[left_index + 1:]:
            joined_ratio = SequenceMatcher(
                None,
                "\n".join(left_turns),
                "\n".join(right_turns),
            ).ratio()
            aligned_ratio = sum(
                SequenceMatcher(None, left, right).ratio()
                for left, right in zip(
                    left_turns,
                    right_turns,
                    strict=True,
                )
            ) / 5
            if joined_ratio >= 0.86 or aligned_ratio >= 0.80:
                return False
    return True


def _load_jsonl(path: Path) -> tuple[ContinuousTrajectory, ...]:
    fixture_path = Path(path)
    try:
        lines = fixture_path.read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError as exc:
        raise ValueError(
            f"continuous fixture is unavailable: {fixture_path}"
        ) from exc
    if not lines or any(not line for line in lines):
        raise ValueError(
            "continuous fixture must be nonempty canonical JSONL"
        )
    trajectories: list[ContinuousTrajectory] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            trajectory = ContinuousTrajectory.model_validate_json(
                line,
                strict=True,
            )
        except ValueError as exc:
            raise ValueError(
                "invalid continuous trajectory at "
                f"line {line_number}"
            ) from exc
        if trajectory.model_dump_json() != line:
            raise ValueError(
                "continuous fixture JSONL must use canonical model order"
            )
        trajectories.append(trajectory)
    ids = tuple(item.trajectory_id for item in trajectories)
    if len(ids) != len(set(ids)):
        raise ValueError("continuous trajectory IDs must be unique")
    return tuple(trajectories)


def load_trajectory_pool(
    path: Path = DEFAULT_POOL_PATH,
) -> tuple[ContinuousTrajectory, ...]:
    return _load_jsonl(path)


def select_backend_trajectories(
    pool: Sequence[ContinuousTrajectory],
) -> tuple[ContinuousTrajectory, ...]:
    normalized = tuple(pool)
    if (
        len(normalized) < 30
        or any(
            type(item) is not ContinuousTrajectory
            for item in normalized
        )
    ):
        raise ValueError(
            "backend selection requires at least 30 trajectories"
        )
    self_only = tuple(
        item
        for item in normalized
        if item.subject_scope == "self"
    )
    if len(self_only) < 20:
        raise ValueError(
            "backend selection requires at least 20 self-only trajectories"
        )
    selected = random.Random(
        BACKEND_SELECTION_SEED
    ).sample(self_only, 20)
    return tuple(sorted(
        selected,
        key=lambda item: item.trajectory_id,
    ))


def _trajectory_bytes(
    trajectories: Sequence[ContinuousTrajectory],
) -> bytes:
    return (
        b"\n".join(
            trajectory.model_dump_json().encode("utf-8")
            for trajectory in trajectories
        )
        + b"\n"
    )


def build_continuous_fixture_manifest(
    *,
    pool_bytes: bytes,
    selected_bytes: bytes,
    pool: Sequence[ContinuousTrajectory],
    selected: Sequence[ContinuousTrajectory],
) -> ContinuousFixtureManifest:
    normalized_pool = tuple(pool)
    normalized_selected = tuple(selected)
    if len(normalized_selected) != 20:
        raise ValueError(
            "continuous manifest requires 20 selected trajectories"
        )
    if selected_bytes != _trajectory_bytes(normalized_selected):
        raise ValueError(
            "selected bytes do not match selected trajectories"
        )
    selected_ids = "\n".join(
        item.trajectory_id for item in normalized_selected
    ) + "\n"
    selected_messages = "\n".join(
        turn.message
        for item in normalized_selected
        for turn in item.turns
    ) + "\n"
    return ContinuousFixtureManifest(
        pool_count=len(normalized_pool),
        pool_sha256=sha256(pool_bytes).hexdigest(),
        selected_sha256=sha256(selected_bytes).hexdigest(),
        selected_ids_sha256=sha256(
            selected_ids.encode("utf-8")
        ).hexdigest(),
        selected_messages_sha256=sha256(
            selected_messages.encode("utf-8")
        ).hexdigest(),
    )


def load_frozen_trajectories(
    path: Path = DEFAULT_FROZEN_PATH,
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> tuple[ContinuousTrajectory, ...]:
    fixture_path = Path(path)
    manifest_file = Path(manifest_path)
    try:
        manifest = ContinuousFixtureManifest.model_validate_json(
            manifest_file.read_text(encoding="utf-8"),
            strict=True,
        )
        selected_bytes = fixture_path.read_bytes()
        pool_path = manifest_file.parent / manifest.pool_file
        pool_bytes = pool_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError(
            "continuous fixture manifest is unavailable or invalid"
        ) from exc
    selected = _load_jsonl(fixture_path)
    pool = _load_jsonl(pool_path)
    expected = build_continuous_fixture_manifest(
        pool_bytes=pool_bytes,
        selected_bytes=selected_bytes,
        pool=pool,
        selected=selected,
    )
    if expected != manifest:
        raise ValueError(
            "continuous fixture manifest hash mismatch"
        )
    return selected


def freeze_continuous_fixtures(
    *,
    pool_path: Path = DEFAULT_POOL_PATH,
    selected_path: Path = DEFAULT_FROZEN_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> ContinuousFixtureManifest:
    pool_file = Path(pool_path)
    selected_file = Path(selected_path)
    manifest_file = Path(manifest_path)
    pool = load_trajectory_pool(pool_file)
    selected = select_backend_trajectories(pool)
    selected_bytes = _trajectory_bytes(selected)
    selected_file.parent.mkdir(parents=True, exist_ok=True)
    selected_file.write_bytes(selected_bytes)
    manifest = build_continuous_fixture_manifest(
        pool_bytes=pool_file.read_bytes(),
        selected_bytes=selected_bytes,
        pool=pool,
        selected=selected,
    )
    manifest_file.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


__all__ = [
    "BACKEND_SELECTION_SEED",
    "ContinuousFixtureManifest",
    "build_continuous_fixture_manifest",
    "freeze_continuous_fixtures",
    "load_frozen_trajectories",
    "load_trajectory_pool",
    "no_simple_paraphrase_pairs",
    "normalize_message",
    "select_backend_trajectories",
]
