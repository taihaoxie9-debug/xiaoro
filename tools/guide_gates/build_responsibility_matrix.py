"""Generate the complete responsibility matrix truth fixture."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from hashlib import sha256
import json
from pathlib import Path

from app.guide.intent.responsibility_matrix import (
    DIALOGUE_STATES,
    OBJECT_CARDINALITIES,
    OBJECT_TYPES,
    OPERATIONS,
    is_legal_matrix_input,
    resolve_responsibility,
)


def build_responsibility_matrix_rows() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for operation in OPERATIONS:
        for cardinality in OBJECT_CARDINALITIES:
            for object_type in OBJECT_TYPES:
                for dialogue_state in DIALOGUE_STATES:
                    for safety in (False, True):
                        base = {
                            "operation": operation,
                            "cardinality": cardinality,
                            "object_type": object_type,
                            "dialogue_state": dialogue_state,
                            "safety": safety,
                        }
                        if not is_legal_matrix_input(**base):
                            rows.append({
                                **base,
                                "status": "invalid_input",
                                "expected_responsibility": (
                                    "invalid_input"
                                ),
                                "expected_processor": None,
                                "expected_presentation_mode": None,
                                "preserve_product_order": False,
                                "clarification_code": None,
                            })
                            continue
                        decision = resolve_responsibility(**base)
                        rows.append({
                            **base,
                            "status": "legal",
                            "expected_responsibility": (
                                decision.responsibility.value
                            ),
                            "expected_processor": decision.processor,
                            "expected_presentation_mode": (
                                decision.presentation_mode
                            ),
                            "preserve_product_order": (
                                decision.preserve_product_order
                            ),
                            "clarification_code": (
                                decision.clarification_code
                            ),
                        })
    return tuple(rows)


def write_responsibility_matrix(output_dir: Path) -> dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    rows = build_responsibility_matrix_rows()
    truth_bytes = b"".join(
        _canonical_json(row) + b"\n"
        for row in rows
    )
    truth_path = output / "truth.jsonl"
    truth_path.write_bytes(truth_bytes)
    legal_count = sum(row["status"] == "legal" for row in rows)
    summary = {
        "schema_version": "guide-responsibility-matrix-v1",
        "row_count": len(rows),
        "legal_row_count": legal_count,
        "invalid_input_count": len(rows) - legal_count,
        "truth_file": truth_path.name,
        "truth_sha256": sha256(truth_bytes).hexdigest(),
    }
    (output / "summary.json").write_bytes(
        _canonical_json(summary) + b"\n"
    )
    return summary


def _parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    print(_canonical_json(
        write_responsibility_matrix(
            Path(arguments.output_dir)
        )
    ).decode("utf-8"))
    return 0


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "build_responsibility_matrix_rows",
    "main",
    "write_responsibility_matrix",
]
