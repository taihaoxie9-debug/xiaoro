from __future__ import annotations

import json
from pathlib import Path

from tools.guide_gates.build_responsibility_matrix import (
    write_responsibility_matrix,
)
from tools.guide_gates.run_final_release_gate import (
    aggregate_release_gate,
    run_focused_gate,
)


def _real_summary(
    *,
    passed: bool = True,
    wrong_binding_count: int = 0,
) -> dict[str, object]:
    return {
        "passed": passed,
        "critical_trajectory_count": 12,
        "critical_trajectory_passed": 12 if passed else 11,
        "completed_turn_count": 48 if passed else 47,
        "turn_count": 48,
        "passed_turn_count": 48 if passed else 45,
        "wrong_binding_count": wrong_binding_count,
        "wrong_responsibility_count": 0,
        "wrong_presentation_count": 0,
        "unsafe_downgrade_count": 0,
        "raw_ad_leak_count": 0,
        "internal_language_count": 0,
        "internal_public_language_count": 0,
        "frontend_contract_violation_count": 0,
        "desktop_passed": 8,
        "desktop_total": 8,
        "mobile_passed": 8,
        "mobile_total": 8,
        "serious_failure_count": 0 if passed else 1,
    }


def test_focused_gate_validates_generated_matrix_and_public_renderer(
    tmp_path: Path,
) -> None:
    matrix_dir = tmp_path / "matrix"
    write_responsibility_matrix(matrix_dir)

    result = run_focused_gate(matrix_dir)

    assert result["passed"] is True
    assert result["row_count"] == 6480
    assert result["legal_row_failures"] == 0
    assert result["wrong_binding_count"] == 0
    assert result["wrong_processor_count"] == 0
    assert result["wrong_presentation_count"] == 0
    assert result["forbidden_public_text_count"] == 0


def test_focused_gate_rejects_matrix_drift(tmp_path: Path) -> None:
    matrix_dir = tmp_path / "matrix"
    write_responsibility_matrix(matrix_dir)
    truth_path = matrix_dir / "truth.jsonl"
    rows = [
        json.loads(line)
        for line in truth_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["expected_processor"] = "wrong_processor"
    truth_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )

    result = run_focused_gate(matrix_dir)

    assert result["passed"] is False
    assert result["legal_row_failures"] >= 1
    assert result["wrong_processor_count"] >= 1


def test_aggregate_gate_requires_all_real_layers_to_pass(tmp_path: Path) -> None:
    focused = {
        "passed": True,
        "legal_row_failures": 0,
        "wrong_binding_count": 0,
        "wrong_processor_count": 0,
        "wrong_presentation_count": 0,
        "forbidden_public_text_count": 0,
    }
    translation = _real_summary()
    backend = _real_summary()
    browser = _real_summary()

    result = aggregate_release_gate(
        focused=focused,
        translation=translation,
        backend=backend,
        browser=browser,
    )

    assert result["passed"] is True
    assert result["serious_failure_count"] == 0
    assert result["wrong_binding_count"] == 0
    assert result["unsafe_downgrade_count"] == 0
    assert result["raw_ad_leak_count"] == 0
    assert result["internal_language_count"] == 0
    assert result["frontend_contract_violation_count"] == 0

    blocked = aggregate_release_gate(
        focused=focused,
        translation=_real_summary(wrong_binding_count=1),
        backend=backend,
        browser=browser,
    )
    assert blocked["passed"] is False
    assert blocked["wrong_binding_count"] == 1
    assert blocked["serious_failure_count"] >= 1
