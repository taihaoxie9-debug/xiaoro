from __future__ import annotations

import json
from pathlib import Path

from tools.guide_gates.build_semantic_equivalence_matrix import (
    build_matrix,
    write_matrix,
)
from tools.guide_gates.turn_meaning_gate import load_gate_cases


_FIXTURE = Path(
    "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
)


def test_written_matrix_is_labeled_expected_contract(
    tmp_path: Path,
) -> None:
    output = tmp_path / "matrix.json"

    write_matrix(cases_path=_FIXTURE, output_path=output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["matrix_kind"] == "expected_contract"


def test_matrix_covers_all_gate_cases_with_rejected_responsibilities() -> None:
    cases = load_gate_cases(_FIXTURE)
    rows = build_matrix(cases)

    assert len(rows) == 128
    assert len({row["case_id"] for row in rows}) == 128
    candidate = next(
        row
        for row in rows
        if row["case_id"] == "know-012-candidate-reference"
    )
    assert candidate["expected_outcome"]["responsibility"] == (
        "product_knowledge"
    )
    assert "recommendation" in candidate[
        "rejected_competing_responsibilities"
    ]
    recommendation = next(
        row
        for row in rows
        if row["case_id"] == "rec-002-round9-fragrance-request"
    )
    assert recommendation["expected_outcome"][
        "recommendation_mode"
    ] == "explore"
    assert recommendation["expected_outcome"][
        "recommendation_mode_basis"
    ] == "broad_exploration"
    image = next(
        row
        for row in rows
        if row["case_id"] == "img-001-find-similar-first"
    )
    assert image["expected_outcome"]["recommendation_mode"] == (
        "explore"
    )
    assert image["expected_outcome"][
        "recommendation_mode_basis"
    ] == "similar_alternatives"
    assert candidate["expected_outcome"]["recommendation_mode"] is None
    recommendation_rows = tuple(
        row
        for row in rows
        if row["expected_outcome"]["responsibility"]
        in {"recommendation", "image_recommendation"}
    )
    assert {
        row["expected_outcome"]["recommendation_mode"]
        for row in recommendation_rows
    } == {"explore", "fit"}
    assert any(
        row["expected_outcome"]["responsibility"]
        == "image_recommendation"
        and row["expected_outcome"]["recommendation_mode"] == "fit"
        for row in recommendation_rows
    )
    by_id = {row["case_id"]: row for row in rows}
    assert by_id["img-003-find-similar-third"][
        "expected_outcome"
    ]["responsibility"] == "image_identity"
    assert by_id["img-004-find-similar-fourth"][
        "expected_outcome"
    ]["responsibility"] == "product_knowledge"
    assert by_id["img-005-sunscreen-package"][
        "expected_outcome"
    ]["recommendation_mode"] == "fit"
    assert by_id["cmp-011-image-ordinals"]["expected_outcome"][
        "responsibility"
    ] == "comparison"
