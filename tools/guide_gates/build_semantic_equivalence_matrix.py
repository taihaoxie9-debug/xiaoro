from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.guide.understanding.semantic_equivalence import (
    derive_semantic_outcome,
)
from tools.guide_gates.turn_meaning_gate import (
    TurnMeaningGateCase,
    load_gate_cases,
)


_REJECTED_BY_RESPONSIBILITY = {
    "recommendation": (
        "comparison",
        "product_knowledge",
        "clarification",
    ),
    "comparison": (
        "recommendation",
        "product_knowledge",
        "clarification",
    ),
    "single_product_suitability": (
        "recommendation",
        "comparison",
        "product_knowledge",
    ),
    "product_knowledge": (
        "recommendation",
        "comparison",
        "general_knowledge",
    ),
    "general_knowledge": (
        "recommendation",
        "product_knowledge",
        "comparison",
    ),
    "consultation": (
        "recommendation",
        "comparison",
        "product_knowledge",
    ),
    "image_identity": (
        "recommendation",
        "image_recommendation",
        "general_knowledge",
    ),
    "image_recommendation": (
        "recommendation",
        "image_identity",
        "product_knowledge",
    ),
    "clarification": (
        "recommendation",
        "comparison",
        "product_knowledge",
    ),
    "safety_escalation": (
        "recommendation",
        "comparison",
        "single_product_suitability",
    ),
    "followup": (
        "recommendation",
        "comparison",
        "general_knowledge",
    ),
}


def build_matrix(
    cases: tuple[TurnMeaningGateCase, ...],
) -> tuple[dict[str, Any], ...]:
    if len(cases) != 128:
        raise ValueError("semantic equivalence matrix requires 128 cases")
    rows: list[dict[str, Any]] = []
    for case in cases:
        outcome = derive_semantic_outcome(expected_case=case)
        rows.append(
            {
                "case_id": case.case_id,
                "family": case.family,
                "expected_outcome": outcome.model_dump(mode="json"),
                "rejected_competing_responsibilities": list(
                    _REJECTED_BY_RESPONSIBILITY[outcome.responsibility]
                ),
            }
        )
    return tuple(rows)


def write_matrix(
    *,
    cases_path: str | Path,
    output_path: str | Path,
) -> None:
    cases = load_gate_cases(cases_path)
    payload = {
        "schema_version": "guide-semantic-equivalence-matrix-v1",
        "matrix_kind": "expected_contract",
        "case_count": len(cases),
        "rows": list(build_matrix(cases)),
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    write_matrix(
        cases_path=args.cases,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_matrix", "write_matrix"]
