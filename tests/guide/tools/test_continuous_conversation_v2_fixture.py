from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.guide.adapters.catalog import CanonicalProductReader
from tools.guide_gates.continuous_conversation_fixture import (
    load_frozen_trajectories,
    normalize_message,
)
from tools.guide_gates.continuous_conversation_mechanical_truth import (
    MechanicalTruthError,
    MechanicalTruthSpec,
    TruthCorrectionOverlay,
    apply_truth_correction_overlay,
    audit_mechanical_truth,
)
from tools.guide_gates.continuous_conversation_runtime import (
    runtime_image_fixtures,
)


FIXTURE_DIRECTORY = Path("tests/fixtures/guide/conversation")
REPLACEMENT_FIXTURE = (
    FIXTURE_DIRECTORY
    / "continuous_blind_b_replacement_20x5_v2.jsonl"
)
REPLACEMENT_MANIFEST = (
    FIXTURE_DIRECTORY
    / "continuous_blind_b_replacement_20x5_v2_manifest.json"
)
REPLACEMENT_TRUTH = (
    FIXTURE_DIRECTORY
    / "continuous_blind_b_replacement_20x5_v2_truth.json"
)
REPLACEMENT_TRUTH_CORRECTION = Path(
    "docs/audits/continuous-conversation/"
    "blind-b-replacement-v2-truth-correction-v1.json"
)


def _load_v2_paper(label: str):
    return load_frozen_trajectories(
        FIXTURE_DIRECTORY
        / f"continuous_blind_{label}_20x5_v2.jsonl",
        manifest_path=(
            FIXTURE_DIRECTORY
            / f"continuous_blind_{label}_20x5_v2_manifest.json"
        ),
    )


@pytest.mark.parametrize("label", ("a", "b"))
def test_v2_blind_paper_loads_as_sealed_frozen_fixture(
    label: str,
) -> None:
    trajectories = _load_v2_paper(label)
    normalized = {
        normalize_message(turn.message)
        for trajectory in trajectories
        for turn in trajectory.turns
    }

    assert len(trajectories) == 20
    assert sum(len(item.turns) for item in trajectories) == 100
    assert len(normalized) == 100
    assert all(item.subject_scope == "self" for item in trajectories)


def test_v2_blind_papers_are_disjoint_from_each_other() -> None:
    blind_a = _load_v2_paper("a")
    blind_b = _load_v2_paper("b")

    a_ids = {item.trajectory_id for item in blind_a}
    b_ids = {item.trajectory_id for item in blind_b}
    a_messages = {
        normalize_message(turn.message)
        for item in blind_a
        for turn in item.turns
    }
    b_messages = {
        normalize_message(turn.message)
        for item in blind_b
        for turn in item.turns
    }

    assert a_ids.isdisjoint(b_ids)
    assert a_messages.isdisjoint(b_messages)


def test_v2_blind_papers_only_use_runtime_image_fixtures() -> None:
    fixture_ids = {
        fixture_id
        for label in ("a", "b")
        for item in _load_v2_paper(label)
        for turn in item.turns
        for fixture_id in turn.image_fixture_ids
    }

    assert fixture_ids == {
        "product-53-front",
        "product-55-front",
    }


def test_v2_blind_paper_rejects_manifest_hash_drift(
    tmp_path: Path,
) -> None:
    fixture = (
        FIXTURE_DIRECTORY / "continuous_blind_a_20x5_v2.jsonl"
    )
    manifest = json.loads(
        (
            FIXTURE_DIRECTORY
            / "continuous_blind_a_20x5_v2_manifest.json"
        ).read_text(encoding="utf-8")
    )
    manifest["selected_sha256"] = "0" * 64
    copied_fixture = tmp_path / fixture.name
    copied_manifest = tmp_path / "manifest.json"
    copied_fixture.write_bytes(fixture.read_bytes())
    copied_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="manifest hash mismatch",
    ):
        load_frozen_trajectories(
            copied_fixture,
            manifest_path=copied_manifest,
        )


def test_replacement_b_is_sealed_disjoint_and_mechanically_grounded(
) -> None:
    replacement = load_frozen_trajectories(
        REPLACEMENT_FIXTURE,
        manifest_path=REPLACEMENT_MANIFEST,
    )
    truth = MechanicalTruthSpec.model_validate_json(
        REPLACEMENT_TRUTH.read_text(encoding="utf-8"),
        strict=True,
    )
    canonical_root = Path("data/canonical")
    canonical_reader = CanonicalProductReader.from_files(
        manifest_path=(
            canonical_root / "core_products_v1_manifest.json"
        ),
        products_path=(
            canonical_root / "core_products_v1.jsonl"
        ),
    )
    with pytest.raises(
        MechanicalTruthError,
        match="explicit_comparison_requires_replace_task",
    ):
        audit_mechanical_truth(
            trajectories=replacement,
            canonical_reader=canonical_reader,
            spec=truth,
            runtime_image_fixtures=runtime_image_fixtures(),
            repo_root=Path.cwd(),
        )
    overlay = TruthCorrectionOverlay.model_validate_json(
        REPLACEMENT_TRUTH_CORRECTION.read_text(encoding="utf-8"),
        strict=True,
    )
    corrected = apply_truth_correction_overlay(
        trajectories=replacement,
        overlay=overlay,
        fixture_path=REPLACEMENT_FIXTURE,
        manifest_path=REPLACEMENT_MANIFEST,
        mechanical_truth_path=REPLACEMENT_TRUTH,
    )
    report = audit_mechanical_truth(
        trajectories=corrected,
        canonical_reader=canonical_reader,
        spec=truth,
        runtime_image_fixtures=runtime_image_fixtures(),
        repo_root=Path.cwd(),
    )
    replacement_ids = {
        item.trajectory_id for item in replacement
    }
    replacement_messages = {
        normalize_message(turn.message)
        for item in replacement
        for turn in item.turns
    }
    prior_ids = {
        item.trajectory_id
        for label in ("a", "b")
        for item in _load_v2_paper(label)
    }
    prior_messages = {
        normalize_message(turn.message)
        for label in ("a", "b")
        for item in _load_v2_paper(label)
        for turn in item.turns
    }

    assert len(replacement) == 20
    assert report.turn_count == 100
    assert len(replacement_messages) == 100
    assert replacement_ids.isdisjoint(prior_ids)
    assert replacement_messages.isdisjoint(prior_messages)
    assert report.canonical_product_count == 103
    assert report.variable_recommendation_turn_count > 0


def test_replacement_b_rejects_mechanical_truth_hash_drift(
    tmp_path: Path,
) -> None:
    copied_fixture = tmp_path / REPLACEMENT_FIXTURE.name
    copied_manifest = tmp_path / REPLACEMENT_MANIFEST.name
    copied_truth = tmp_path / REPLACEMENT_TRUTH.name
    copied_fixture.write_bytes(REPLACEMENT_FIXTURE.read_bytes())
    copied_manifest.write_bytes(REPLACEMENT_MANIFEST.read_bytes())
    copied_truth.write_bytes(REPLACEMENT_TRUTH.read_bytes() + b" ")

    with pytest.raises(
        ValueError,
        match="manifest hash mismatch",
    ):
        load_frozen_trajectories(
            copied_fixture,
            manifest_path=copied_manifest,
        )
