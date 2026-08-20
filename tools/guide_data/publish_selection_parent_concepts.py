"""Publish manually reviewed parent-concept projections."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path

from app.guide.retrieval.selection_parent_concept_assets import (
    load_selection_concept_assets,
    publish_selection_concept_assets,
)
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptReview,
)


def publish_from_paths(
    *,
    inventory: Path,
    reviews: Path,
    output_dir: Path,
) -> Path:
    rows = tuple(
        SelectionConceptReview.model_validate_json(line, strict=True)
        for line in Path(reviews).read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    )
    manifest_path = publish_selection_concept_assets(
        reviews=rows,
        inventory_path=Path(inventory),
        review_path=Path(reviews),
        output_dir=Path(output_dir),
    )
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    load_selection_concept_assets(
        manifest_path,
        expected_manifest_sha256=manifest["manifest_sha256"],
        inventory_path=Path(inventory),
        review_path=Path(reviews),
    )
    return manifest_path


def _parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--reviews", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    manifest_path = publish_from_paths(
        inventory=Path(arguments.inventory),
        reviews=Path(arguments.reviews),
        output_dir=Path(arguments.output_dir),
    )
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    print(json.dumps(
        {
            "concept_count": manifest["concept_count"],
            "decision_counts": manifest["decision_counts"],
            "manifest_path": str(manifest_path),
            "manifest_sha256": manifest["manifest_sha256"],
            "projection_count": manifest["projection_count"],
            "review_count": manifest["review_count"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "publish_from_paths"]
