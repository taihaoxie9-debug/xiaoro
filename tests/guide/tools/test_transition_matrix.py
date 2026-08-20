from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.guide_gates.build_transition_matrix import (
    CORE_STATES,
    build_long_walks,
    build_pairwise_edges,
    build_transition_matrix,
    build_triple_paths,
)
from tools.guide_gates.run_transition_matrix import (
    TransitionOutcome,
    compare_outcomes,
    run_typed_router_matrix,
)


def test_transition_matrix_covers_all_ordered_edges_and_triples() -> None:
    edges = build_pairwise_edges()
    paths = build_triple_paths()

    assert len(CORE_STATES) == 6
    assert len(edges) == 36
    assert len(paths) == 216
    assert len({item["edge_id"] for item in edges}) == 36
    assert len({item["path_id"] for item in paths}) == 216
    assert edges[0] == {
        "edge_id": "recommendation_batch->recommendation_batch",
        "source": "recommendation_batch",
        "target": "recommendation_batch",
        "assertion_mode": "ordinary_path_independence",
        "expected_state_change": False,
    }


def test_long_walks_include_forward_reverse_and_reentry_paths() -> None:
    walks = build_long_walks()
    sequences = {tuple(item["states"]) for item in walks}

    assert len(walks) >= 8
    assert (
        "recommendation_batch",
        "single_product_focus",
        "comparison_batch",
        "consultation",
    ) in sequences
    assert (
        "consultation",
        "comparison_batch",
        "single_product_focus",
        "recommendation_batch",
    ) in sequences
    assert (
        "recommendation_batch",
        "single_product_focus",
        "comparison_batch",
        "consultation",
        "consultation",
        "comparison_batch",
        "single_product_focus",
        "recommendation_batch",
    ) in sequences


def test_matrix_writer_hash_locks_every_generated_file(
    tmp_path: Path,
) -> None:
    result = build_transition_matrix(tmp_path)
    manifest = json.loads(
        (tmp_path / "manifest.json").read_text(encoding="utf-8")
    )

    assert result["pairwise_count"] == 36
    assert result["triple_count"] == 216
    assert result["long_walk_count"] >= 8
    assert manifest["schema_version"] == "guide-transition-matrix-v1"
    for filename, digest in manifest["files"].items():
        assert digest == hashlib.sha256(
            (tmp_path / filename).read_bytes()
        ).hexdigest()


def _outcome(
    *,
    product_ids: tuple[int, ...] = (38, 91),
    expected_state_change: bool = False,
) -> TransitionOutcome:
    return TransitionOutcome(
        processor_family="comparison",
        product_ids=product_ids,
        image_ordinals=(),
        card_type="comparison",
        card_product_ids=product_ids,
        active_state="comparison_batch",
        safety_state=None,
        expected_state_change=expected_state_change,
    )


def test_equal_ordinary_outcomes_are_path_independent() -> None:
    result = compare_outcomes(_outcome(), _outcome())

    assert result == {
        "path_independent": True,
        "expected_state_change": False,
        "differences": [],
    }


def test_changed_product_binding_is_path_pollution() -> None:
    result = compare_outcomes(
        _outcome(),
        _outcome(product_ids=(38, 90)),
    )

    assert result["path_independent"] is False
    assert result["expected_state_change"] is False
    assert "product_ids" in result["differences"]


def test_expected_state_change_is_reported_separately() -> None:
    result = compare_outcomes(
        _outcome(expected_state_change=True),
        _outcome(product_ids=(38,), expected_state_change=True),
    )

    assert result["path_independent"] is False
    assert result["expected_state_change"] is True
    assert "product_ids" in result["differences"]


def test_typed_router_matrix_executes_all_edges_and_triples() -> None:
    report = run_typed_router_matrix()

    assert report["pairwise_edges"] == 36
    assert report["triple_paths"] == 216
    assert report["ordinary_path_pollution"] == 0
    assert report["serious_failures"] == 0
    assert report["passed"] is True


def test_typed_router_matrix_keeps_batch_suitability_in_comparison() -> None:
    report = run_typed_router_matrix()
    key = "consultation->comparison_batch"

    outcome = report["edge_outcomes"][key]
    assert outcome["processor_family"] == "comparison"
    assert outcome["product_ids"] == [38, 91]
    assert outcome["card_type"] == "comparison"


def test_cli_refuses_outcome_scoring_without_observed_outcomes(
    tmp_path: Path,
) -> None:
    from tools.guide_gates.run_transition_matrix import main

    fixture_root = tmp_path / "fixture"
    output_root = tmp_path / "output"
    build_transition_matrix(fixture_root)

    assert main([
        "--fixture-root",
        str(fixture_root),
        "--output-dir",
        str(output_root),
        "--outcome-scoring",
    ]) == 3
    score = json.loads(
        (output_root / "score.json").read_text(encoding="utf-8")
    )
    assert score["scoring_status"] == "missing_outcomes"


def test_cli_runs_typed_router_matrix(
    tmp_path: Path,
) -> None:
    from tools.guide_gates.run_transition_matrix import main

    fixture_root = tmp_path / "fixture"
    output_root = tmp_path / "output"
    build_transition_matrix(fixture_root)

    assert main([
        "--fixture-root",
        str(fixture_root),
        "--output-dir",
        str(output_root),
        "--execute-typed-router",
    ]) == 0
    score = json.loads(
        (output_root / "score.json").read_text(encoding="utf-8")
    )
    assert score["typed_router"]["pairwise_edges"] == 36
    assert score["typed_router"]["triple_paths"] == 216
    assert score["typed_router"]["passed"] is True


def test_script_entrypoint_runs_typed_router_matrix(
    tmp_path: Path,
) -> None:
    fixture_root = tmp_path / "fixture"
    output_root = tmp_path / "output"
    build_transition_matrix(fixture_root)
    script = (
        Path(__file__).resolve().parents[3]
        / "tools/guide_gates/run_transition_matrix.py"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--fixture-root",
            str(fixture_root),
            "--output-dir",
            str(output_root),
            "--execute-typed-router",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(
        (output_root / "score.json").read_text(encoding="utf-8")
    )["typed_router"]["passed"] is True
