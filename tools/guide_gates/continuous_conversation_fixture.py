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
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEALED_V2_SCHEMA = "guide-continuous-blind-fixture-manifest-v2"
_SEALED_V2_CANONICAL = Path(
    "data/canonical/core_products_v1.jsonl"
)
_SEALED_V2_MODE_MATRIX = Path(
    "docs/audits/continuous-conversation/"
    "presentation-mode-matrix-v2.json"
)
_SEALED_V2_IMAGE_GROUND_TRUTH = Path(
    "docs/audits/continuous-conversation/"
    "real-image-ground-truth-v1.json"
)
_SEALED_V2_SEEN_LEDGER = Path(
    "docs/audits/continuous-conversation/"
    "seen-message-ledger-v1.json"
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


def canonical_trajectory_json(
    trajectory: ContinuousTrajectory,
) -> str:
    if type(trajectory) is not ContinuousTrajectory:
        raise TypeError(
            "continuous fixture requires an exact ContinuousTrajectory"
        )
    payload = trajectory.model_dump()
    for turn in payload["turns"]:
        for binding in turn["expected_bindings"]:
            if binding["source_span"] is None:
                del binding["source_span"]
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
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
        if canonical_trajectory_json(trajectory) != line:
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
            canonical_trajectory_json(trajectory).encode("utf-8")
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
        manifest_payload = json.loads(
            manifest_file.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ValueError(
            "continuous fixture manifest is unavailable or invalid"
        ) from exc
    if manifest_payload.get("schema_version") == _SEALED_V2_SCHEMA:
        return _load_sealed_v2_trajectories(
            fixture_path=fixture_path,
            manifest=manifest_payload,
        )
    try:
        manifest = ContinuousFixtureManifest.model_validate_json(
            json.dumps(
                manifest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
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


def _load_sealed_v2_trajectories(
    *,
    fixture_path: Path,
    manifest: dict[str, object],
) -> tuple[ContinuousTrajectory, ...]:
    try:
        selected_bytes = fixture_path.read_bytes()
        selected = _load_jsonl(fixture_path)
        canonical_path = _REPO_ROOT / _SEALED_V2_CANONICAL
        mode_matrix_path = _REPO_ROOT / _SEALED_V2_MODE_MATRIX
        image_ground_truth_path = (
            _REPO_ROOT / _SEALED_V2_IMAGE_GROUND_TRUTH
        )
        seen_ledger_path = _REPO_ROOT / _SEALED_V2_SEEN_LEDGER
        canonical_bytes = canonical_path.read_bytes()
        mode_matrix_bytes = mode_matrix_path.read_bytes()
        image_ground_truth_bytes = image_ground_truth_path.read_bytes()
        seen_ledger_bytes = seen_ledger_path.read_bytes()
        seen_ledger = json.loads(seen_ledger_bytes)
    except (OSError, ValueError) as exc:
        raise ValueError(
            "continuous fixture manifest is unavailable or invalid"
        ) from exc

    selected_ids = tuple(
        trajectory.trajectory_id for trajectory in selected
    )
    messages = tuple(
        turn.message
        for trajectory in selected
        for turn in trajectory.turns
    )
    normalized = tuple(normalize_message(message) for message in messages)
    canonical_ids = {
        json.loads(line)["product_id"]
        for line in canonical_bytes.decode("utf-8").splitlines()
        if line
    }
    referenced_ids = {
        product_id
        for trajectory in selected
        for turn in trajectory.turns
        for product_id in (
            *turn.expected_card_ids,
            *(
                binding.product_id
                for binding in turn.expected_bindings
            ),
        )
    }
    seen_hashes = set(seen_ledger.get("seen_message_hashes", ()))
    normalized_hashes = {
        sha256(message.encode("utf-8")).hexdigest()
        for message in normalized
    }
    label = (
        "A"
        if "_a_" in fixture_path.name
        else "B"
        if "_b_" in fixture_path.name
        else None
    )
    expected_hashes = {
        "selected_sha256": sha256(selected_bytes).hexdigest(),
        "selected_ids_sha256": _line_hash(selected_ids),
        "selected_messages_sha256": _line_hash(messages),
    }
    optional_normalized_hash = manifest.get(
        "normalized_messages_sha256"
    )
    if optional_normalized_hash is not None:
        expected_hashes["normalized_messages_sha256"] = _line_hash(
            normalized
        )
    manifest_hashes = {
        "canonical": (
            manifest.get("canonical_products_sha256")
            or manifest.get("canonical_sha256")
        ),
        "mode_matrix": manifest.get(
            "presentation_mode_matrix_sha256"
        ),
        "image_ground_truth": (
            manifest.get("image_ground_truth_sha256")
            or manifest.get("real_image_ground_truth_sha256")
        ),
        "seen_ledger": (
            manifest.get("seen_ledger_sha256")
            or manifest.get("seen_message_ledger_sha256")
        ),
    }
    actual_asset_hashes = {
        "canonical": sha256(canonical_bytes).hexdigest(),
        "mode_matrix": sha256(mode_matrix_bytes).hexdigest(),
        "image_ground_truth": sha256(
            image_ground_truth_bytes
        ).hexdigest(),
        "seen_ledger": sha256(seen_ledger_bytes).hexdigest(),
    }
    truth_file = manifest.get("mechanical_truth_file")
    truth_sha256 = manifest.get("mechanical_truth_sha256")
    if (truth_file is None) != (truth_sha256 is None):
        raise ValueError(
            "continuous fixture manifest hash mismatch"
        )
    if truth_file is not None:
        if (
            not isinstance(truth_file, str)
            or Path(truth_file).name != truth_file
            or not isinstance(truth_sha256, str)
        ):
            raise ValueError(
                "continuous fixture manifest hash mismatch"
            )
        try:
            truth_bytes = (
                fixture_path.parent / truth_file
            ).read_bytes()
        except OSError as exc:
            raise ValueError(
                "continuous fixture manifest hash mismatch"
            ) from exc
        if sha256(truth_bytes).hexdigest() != truth_sha256:
            raise ValueError(
                "continuous fixture manifest hash mismatch"
            )
    declared_ids = manifest.get("canonical_product_ids_used")
    if any(
        (
            manifest.get(key) != value
            for key, value in expected_hashes.items()
        )
    ) or any(
        manifest_hashes[key] != value
        for key, value in actual_asset_hashes.items()
    ) or any(
        (
            manifest.get("blind_label") != label,
            manifest.get("selected_file") != fixture_path.name,
            manifest.get("selected_count") != 20,
            manifest.get("selected_turn_count") != 100,
            len(selected) != 20,
            len(messages) != 100,
            len(set(normalized)) != 100,
            any(
                trajectory.subject_scope != "self"
                for trajectory in selected
            ),
            bool(normalized_hashes.intersection(seen_hashes)),
            not referenced_ids.issubset(canonical_ids),
            (
                declared_ids is not None
                and set(declared_ids) != referenced_ids
            ),
            not isinstance(manifest.get("coverage_counts"), dict),
            not manifest.get("coverage_counts"),
        )
    ):
        raise ValueError(
            "continuous fixture manifest hash mismatch"
        )
    return selected


def _line_hash(values: Sequence[str]) -> str:
    return sha256(
        (("\n".join(values)) + "\n").encode("utf-8")
    ).hexdigest()


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
    "canonical_trajectory_json",
    "freeze_continuous_fixtures",
    "load_frozen_trajectories",
    "load_trajectory_pool",
    "no_simple_paraphrase_pairs",
    "normalize_message",
    "select_backend_trajectories",
]
