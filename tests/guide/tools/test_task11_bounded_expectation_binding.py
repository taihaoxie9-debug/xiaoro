from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.guide_gates import run_task11_independent_audit as independent


ROOT = Path(__file__).resolve().parents[3]
MATRIX = (
    ROOT
    / "tests/fixtures/guide/intent/"
    "task11_production_path_matrix_v1.jsonl"
)


def test_independent_audit_rejects_bounded_expectation_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    browser_path = (
        root
        / "tools/guide_gates/run_mainline_contract_browser_audit.py"
    )
    browser_path.parent.mkdir(parents=True)
    browser_path.write_text(
        (
            ROOT
            / "tools/guide_gates/run_mainline_contract_browser_audit.py"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    rows = [
        json.loads(line)
        for line in MATRIX.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    target = next(
        row
        for row in rows
        if row.get("case_id") == "bounded-text-fit-t1"
    )
    target["expected_processor"] = "comparison"
    cases_path = (
        root
        / "tests/fixtures/guide/intent/"
        "task11_production_path_matrix_v1.jsonl"
    )
    cases_path.parent.mkdir(parents=True)
    cases_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        independent.Task11IndependentAuditError,
        match="bounded trajectory expectations",
    ):
        independent._validate_bounded_trajectory_messages(
            root=root,
            cases_path=cases_path,
        )
