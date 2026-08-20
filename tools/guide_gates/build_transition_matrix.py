"""Generate the deterministic state-transition coverage matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


CORE_STATES = (
    "recommendation_batch",
    "single_product_focus",
    "comparison_batch",
    "consultation",
    "general_knowledge",
    "confirmed_image_product",
)

_FORWARD = (
    "recommendation_batch",
    "single_product_focus",
    "comparison_batch",
    "consultation",
)
_REVERSE = (
    "consultation",
    "comparison_batch",
    "single_product_focus",
    "recommendation_batch",
)


def build_pairwise_edges() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "edge_id": f"{source}->{target}",
            "source": source,
            "target": target,
            "assertion_mode": "ordinary_path_independence",
            "expected_state_change": False,
        }
        for source in CORE_STATES
        for target in CORE_STATES
    )


def build_triple_paths() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "path_id": f"{first}->{second}->{third}",
            "states": [first, second, third],
            "assertion_mode": "ordinary_path_independence",
            "expected_state_change": False,
        }
        for first in CORE_STATES
        for second in CORE_STATES
        for third in CORE_STATES
    )


def build_long_walks() -> tuple[dict[str, object], ...]:
    sequences = (
        _FORWARD,
        _REVERSE,
        (
            "recommendation_batch",
            "single_product_focus",
            "comparison_batch",
            "consultation",
            "consultation",
            "comparison_batch",
            "single_product_focus",
            "recommendation_batch",
        ),
        (
            "recommendation_batch",
            "single_product_focus",
            "comparison_batch",
            "consultation",
            "recommendation_batch",
        ),
        (
            "comparison_batch",
            "single_product_focus",
            "consultation",
            "recommendation_batch",
        ),
        (
            "single_product_focus",
            "consultation",
            "comparison_batch",
            "single_product_focus",
            "recommendation_batch",
        ),
        (
            "confirmed_image_product",
            "single_product_focus",
            "comparison_batch",
            "consultation",
        ),
        (
            "general_knowledge",
            "recommendation_batch",
            "consultation",
            "comparison_batch",
        ),
    )
    return tuple(
        {
            "walk_id": f"walk-{index:02d}",
            "states": list(sequence),
            "assertion_mode": "ordinary_path_independence",
            "expected_state_change": False,
        }
        for index, sequence in enumerate(sequences, start=1)
    )


def build_transition_matrix(output_root: str | Path) -> dict[str, int]:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    states = {
        "schema_version": "guide-transition-states-v1",
        "states": list(CORE_STATES),
    }
    edges = build_pairwise_edges()
    paths = build_triple_paths()
    walks = build_long_walks()
    _write_json(root / "states.json", states)
    _write_jsonl(root / "pairwise_edges.jsonl", edges)
    _write_jsonl(root / "triple_paths.jsonl", paths)
    _write_jsonl(root / "long_walks.jsonl", walks)
    files = {
        filename: _sha256(root / filename)
        for filename in (
            "states.json",
            "pairwise_edges.jsonl",
            "triple_paths.jsonl",
            "long_walks.jsonl",
        )
    }
    _write_json(
        root / "manifest.json",
        {
            "schema_version": "guide-transition-matrix-v1",
            "state_count": len(CORE_STATES),
            "pairwise_count": len(edges),
            "triple_count": len(paths),
            "long_walk_count": len(walks),
            "files": files,
        },
    )
    _write_json(
        root / "truth.json",
        {
            "schema_version": "guide-transition-truth-v1",
            "ordinary_path_independence": True,
            "allowed_state_changes": [
                "safety_escalation",
                "new_image_bundle",
                "explicit_constraint_change",
                "explicit_reset",
            ],
        },
    )
    return {
        "state_count": len(CORE_STATES),
        "pairwise_count": len(edges),
        "triple_count": len(paths),
        "long_walk_count": len(walks),
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: tuple[dict[str, object], ...]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for value in values
        ),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_transition_matrix(args.output_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
