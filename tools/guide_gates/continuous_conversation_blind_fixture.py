from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
import random
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.guide_gates.continuous_conversation_fixture import (
    load_trajectory_pool,
    normalize_message,
)
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousTrajectory,
)


BLIND_SHUFFLE_SEED = 2026081801
_FIXTURE_DIRECTORY = Path("tests/fixtures/guide/conversation")
DEFAULT_BLIND_POOL_PATH = (
    _FIXTURE_DIRECTORY / "continuous_blind_pool_v1.jsonl"
)
DEFAULT_BLIND_A_PATH = (
    _FIXTURE_DIRECTORY / "continuous_blind_a_20x5_v1.jsonl"
)
DEFAULT_BLIND_A_MANIFEST_PATH = (
    _FIXTURE_DIRECTORY / "continuous_blind_a_20x5_v1_manifest.json"
)
DEFAULT_BLIND_B_PATH = (
    _FIXTURE_DIRECTORY / "continuous_blind_b_20x5_v1.jsonl"
)
DEFAULT_BLIND_B_MANIFEST_PATH = (
    _FIXTURE_DIRECTORY / "continuous_blind_b_20x5_v1_manifest.json"
)


class ContinuousBlindFixtureManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )

    schema_version: Literal[
        "guide-continuous-blind-fixture-manifest-v1"
    ] = "guide-continuous-blind-fixture-manifest-v1"
    pool_file: Literal[
        "continuous_blind_pool_v1.jsonl"
    ] = "continuous_blind_pool_v1.jsonl"
    selected_file: str = Field(
        min_length=1,
        pattern=r"^continuous_blind_[ab]_20x5_v1\.jsonl$",
    )
    selection_seed: Literal[2026081801] = BLIND_SHUFFLE_SEED
    blind_label: Literal["A", "B"]
    pool_count: Literal[40] = 40
    selected_count: Literal[20] = 20
    selected_turn_count: Literal[100] = 100
    pool_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_messages_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )


def normalized_messages(
    trajectories: Sequence[ContinuousTrajectory],
) -> set[str]:
    return {
        normalize_message(turn.message)
        for trajectory in trajectories
        for turn in trajectory.turns
    }


def _load_pool(path: Path) -> tuple[ContinuousTrajectory, ...]:
    pool = load_trajectory_pool(Path(path))
    if len(pool) != 40:
        raise ValueError(
            "continuous blind pool must contain exactly 40 trajectories"
        )
    return pool


def select_blind_exams(
    pool: Sequence[ContinuousTrajectory],
) -> tuple[
    tuple[ContinuousTrajectory, ...],
    tuple[ContinuousTrajectory, ...],
]:
    normalized = list(pool)
    if len(normalized) != 40:
        raise ValueError(
            "continuous blind pool must contain exactly 40 trajectories"
        )
    randomizer = random.Random(BLIND_SHUFFLE_SEED)
    blind_a: list[ContinuousTrajectory] = []
    blind_b: list[ContinuousTrajectory] = []
    for group_name in ("rpf", "kcr", "cps", "img"):
        group = [
            trajectory
            for trajectory in normalized
            if (
                len(trajectory.trajectory_id.split("-")) > 2
                and trajectory.trajectory_id.split("-")[1]
                == group_name
            )
        ]
        if len(group) != 10:
            raise ValueError(
                "continuous blind pool must contain ten "
                f"{group_name} trajectories"
            )
        randomizer.shuffle(group)
        blind_a.extend(group[:5])
        blind_b.extend(group[5:])
    return (
        tuple(sorted(
            blind_a,
            key=lambda trajectory: trajectory.trajectory_id,
        )),
        tuple(sorted(
            blind_b,
            key=lambda trajectory: trajectory.trajectory_id,
        )),
    )


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


def _lines_sha256(lines: Sequence[str]) -> str:
    payload = "\n".join(lines) + "\n"
    return sha256(payload.encode("utf-8")).hexdigest()


def _build_manifest(
    *,
    label: Literal["A", "B"],
    pool_bytes: bytes,
    selected_path: Path,
    selected_bytes: bytes,
    selected: Sequence[ContinuousTrajectory],
) -> ContinuousBlindFixtureManifest:
    normalized_selected = tuple(selected)
    if len(normalized_selected) != 20:
        raise ValueError(
            "continuous blind manifest requires 20 trajectories"
        )
    if selected_bytes != _trajectory_bytes(normalized_selected):
        raise ValueError(
            "selected bytes do not match selected trajectories"
        )
    return ContinuousBlindFixtureManifest(
        selected_file=selected_path.name,
        blind_label=label,
        pool_sha256=sha256(pool_bytes).hexdigest(),
        selected_sha256=sha256(selected_bytes).hexdigest(),
        selected_ids_sha256=_lines_sha256(
            tuple(
                trajectory.trajectory_id
                for trajectory in normalized_selected
            )
        ),
        selected_messages_sha256=_lines_sha256(
            tuple(
                turn.message
                for trajectory in normalized_selected
                for turn in trajectory.turns
            )
        ),
    )


def _write_exam(
    *,
    label: Literal["A", "B"],
    pool_bytes: bytes,
    selected: Sequence[ContinuousTrajectory],
    selected_path: Path,
    manifest_path: Path,
) -> ContinuousBlindFixtureManifest:
    selected_bytes = _trajectory_bytes(selected)
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    selected_path.write_bytes(selected_bytes)
    manifest = _build_manifest(
        label=label,
        pool_bytes=pool_bytes,
        selected_path=selected_path,
        selected_bytes=selected_bytes,
        selected=selected,
    )
    manifest_path.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def freeze_blind_exams(
    *,
    pool_path: Path = DEFAULT_BLIND_POOL_PATH,
    blind_a_path: Path = DEFAULT_BLIND_A_PATH,
    blind_a_manifest_path: Path = DEFAULT_BLIND_A_MANIFEST_PATH,
    blind_b_path: Path = DEFAULT_BLIND_B_PATH,
    blind_b_manifest_path: Path = DEFAULT_BLIND_B_MANIFEST_PATH,
) -> tuple[
    ContinuousBlindFixtureManifest,
    ContinuousBlindFixtureManifest,
]:
    pool_file = Path(pool_path)
    pool = _load_pool(pool_file)
    blind_a, blind_b = select_blind_exams(pool)
    pool_bytes = pool_file.read_bytes()
    manifest_a = _write_exam(
        label="A",
        pool_bytes=pool_bytes,
        selected=blind_a,
        selected_path=Path(blind_a_path),
        manifest_path=Path(blind_a_manifest_path),
    )
    manifest_b = _write_exam(
        label="B",
        pool_bytes=pool_bytes,
        selected=blind_b,
        selected_path=Path(blind_b_path),
        manifest_path=Path(blind_b_manifest_path),
    )
    return manifest_a, manifest_b


def _load_exam(
    *,
    label: Literal["A", "B"],
    selected_path: Path,
    manifest_path: Path,
) -> tuple[
    tuple[ContinuousTrajectory, ...],
    ContinuousBlindFixtureManifest,
]:
    try:
        manifest = ContinuousBlindFixtureManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8"),
            strict=True,
        )
        selected_bytes = selected_path.read_bytes()
        selected = load_trajectory_pool(selected_path)
        adjacent_pool_path = manifest_path.parent / manifest.pool_file
        pool_path = (
            adjacent_pool_path
            if adjacent_pool_path.is_file()
            else DEFAULT_BLIND_POOL_PATH
        )
        _load_pool(pool_path)
        pool_bytes = pool_path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError(
            "continuous blind fixture manifest is unavailable or invalid"
        ) from exc
    if (
        manifest.blind_label != label
        or manifest.selected_file != selected_path.name
        or len(selected) != 20
        or sum(len(item.turns) for item in selected) != 100
        or manifest.pool_sha256 != sha256(pool_bytes).hexdigest()
        or manifest.selected_sha256
        != sha256(selected_bytes).hexdigest()
        or manifest.selected_ids_sha256
        != _lines_sha256(
            tuple(item.trajectory_id for item in selected)
        )
        or manifest.selected_messages_sha256
        != _lines_sha256(
            tuple(
                turn.message
                for item in selected
                for turn in item.turns
            )
        )
    ):
        raise ValueError(
            "continuous blind fixture manifest hash mismatch"
        )
    return selected, manifest


def load_blind_exams(
    *,
    blind_a_path: Path = DEFAULT_BLIND_A_PATH,
    blind_a_manifest_path: Path = DEFAULT_BLIND_A_MANIFEST_PATH,
    blind_b_path: Path = DEFAULT_BLIND_B_PATH,
    blind_b_manifest_path: Path = DEFAULT_BLIND_B_MANIFEST_PATH,
) -> tuple[
    tuple[ContinuousTrajectory, ...],
    tuple[ContinuousTrajectory, ...],
]:
    blind_a, manifest_a = _load_exam(
        label="A",
        selected_path=Path(blind_a_path),
        manifest_path=Path(blind_a_manifest_path),
    )
    blind_b, manifest_b = _load_exam(
        label="B",
        selected_path=Path(blind_b_path),
        manifest_path=Path(blind_b_manifest_path),
    )
    if (
        manifest_a.pool_sha256 != manifest_b.pool_sha256
        or {
            item.trajectory_id for item in blind_a
        }.intersection(
            item.trajectory_id for item in blind_b
        )
        or normalized_messages(blind_a).intersection(
            normalized_messages(blind_b)
        )
    ):
        raise ValueError(
            "continuous blind fixtures must be disjoint"
        )
    return blind_a, blind_b


__all__ = [
    "BLIND_SHUFFLE_SEED",
    "ContinuousBlindFixtureManifest",
    "freeze_blind_exams",
    "load_blind_exams",
    "normalized_messages",
    "select_blind_exams",
]
