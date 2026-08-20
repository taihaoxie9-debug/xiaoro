from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tools.guide_gates.build_responsibility_matrix import (
    build_responsibility_matrix_rows,
    write_responsibility_matrix,
)


def test_generated_matrix_covers_legal_and_invalid_input_rows() -> None:
    rows = build_responsibility_matrix_rows()
    legal = tuple(row for row in rows if row["status"] == "legal")
    invalid = tuple(
        row for row in rows if row["status"] == "invalid_input"
    )

    assert len(rows) == 6480
    assert len(legal) == 3888
    assert len(invalid) == 2592
    assert all(row["expected_responsibility"] for row in legal)
    assert all(
        row["expected_responsibility"] == "invalid_input"
        for row in invalid
    )
    assert any(
        row["operation"] == "suitability"
        and row["object_type"] == "candidate_ordinals"
        and row["cardinality"] == "two_or_three"
        and row["expected_responsibility"] == "comparison"
        for row in legal
    )
    assert any(
        row["operation"] == "suitability"
        and row["object_type"] == "image_ordinals"
        and row["cardinality"] == "two_or_three"
        and row["expected_responsibility"] == "comparison"
        for row in legal
    )


def test_matrix_cli_writes_stable_truth_and_summary(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    command = [
        sys.executable,
        "-m",
        "tools.guide_gates.build_responsibility_matrix",
    ]

    subprocess.run(
        [*command, "--output-dir", str(first)],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [*command, "--output-dir", str(second)],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(
        (first / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["row_count"] == 6480
    assert summary["legal_row_count"] == 3888
    assert summary["invalid_input_count"] == 2592
    assert (first / "truth.jsonl").read_bytes() == (
        second / "truth.jsonl"
    ).read_bytes()


def test_checked_in_matrix_matches_current_resolver(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generated"
    write_responsibility_matrix(generated)
    fixture = Path(
        "tests/fixtures/guide/responsibility_matrix"
    )

    assert (fixture / "truth.jsonl").read_bytes() == (
        generated / "truth.jsonl"
    ).read_bytes()
    assert (fixture / "summary.json").read_bytes() == (
        generated / "summary.json"
    ).read_bytes()
