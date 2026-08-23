from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.guide.retrieval.selection_parent_concept_assets import (
    load_selection_concept_assets,
    publish_selection_concept_assets,
)
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptReview,
)


def _reviews(path: Path) -> tuple[SelectionConceptReview, ...]:
    return tuple(
        SelectionConceptReview.model_validate_json(line, strict=True)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _publish(tmp_path: Path):
    inventory = tmp_path / "inventory.json"
    review = tmp_path / "review.jsonl"
    shutil.copyfile(
        "docs/audits/selection-concepts/inventory_v1.json",
        inventory,
    )
    shutil.copyfile(
        "docs/audits/selection-concepts/review_v1.jsonl",
        review,
    )
    manifest_path = publish_selection_concept_assets(
        reviews=_reviews(review),
        inventory_path=inventory,
        review_path=review,
        output_dir=tmp_path / "assets",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return inventory, review, manifest_path, manifest


def test_published_asset_is_content_addressed_and_loadable(
    tmp_path: Path,
) -> None:
    inventory, review, manifest_path, manifest = _publish(tmp_path)

    assets = load_selection_concept_assets(
        manifest_path,
        expected_manifest_sha256=manifest["manifest_sha256"],
        inventory_path=inventory,
        review_path=review,
    )

    assert manifest["projection_count"] == 99
    assert manifest["review_count"] == 103
    assert manifest["decision_counts"] == {
        "leave_free": 4,
        "map": 99,
    }
    assert manifest["concept_count"] == 48
    assert manifest["projections_file"] == (
        "selection_concepts_v1."
        + manifest["projections_sha256"]
        + ".jsonl"
    )
    assert len(assets.projections) == 99
    assert assets.manifest == assets.manifest.model_copy(deep=True)


def test_loader_rejects_projection_byte_drift(tmp_path: Path) -> None:
    inventory, review, manifest_path, manifest = _publish(tmp_path)
    projections = manifest_path.parent / manifest["projections_file"]
    projections.write_bytes(projections.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="projection.*SHA"):
        load_selection_concept_assets(
            manifest_path,
            expected_manifest_sha256=manifest["manifest_sha256"],
            inventory_path=inventory,
            review_path=review,
        )


def test_loader_rejects_inventory_or_review_drift(
    tmp_path: Path,
) -> None:
    inventory, review, manifest_path, manifest = _publish(tmp_path)
    inventory.write_bytes(inventory.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="inventory.*SHA"):
        load_selection_concept_assets(
            manifest_path,
            expected_manifest_sha256=manifest["manifest_sha256"],
            inventory_path=inventory,
            review_path=review,
        )


def test_loader_rejects_runtime_manifest_lock_mismatch(
    tmp_path: Path,
) -> None:
    inventory, review, manifest_path, _ = _publish(tmp_path)

    with pytest.raises(ValueError, match="runtime.*lock"):
        load_selection_concept_assets(
            manifest_path,
            expected_manifest_sha256="0" * 64,
            inventory_path=inventory,
            review_path=review,
        )


def test_review_v2_publisher_cli_is_hash_locked(
    tmp_path: Path,
) -> None:
    output = tmp_path / "selection-v2"
    inventory = Path(
        "docs/audits/selection-concepts/review-v2/inventory.json"
    ).resolve()
    reviews = Path(
        "docs/audits/selection-concepts/review-v2/reviews.jsonl"
    ).resolve()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.publish_selection_parent_concepts",
            "--inventory",
            str(inventory),
            "--reviews",
            str(reviews),
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assets = load_selection_concept_assets(
        output / "selection_concepts_v1_manifest.json",
        expected_manifest_sha256=report["manifest_sha256"],
        inventory_path=inventory,
        review_path=reviews,
    )

    assert report["review_count"] == 191
    assert report["projection_count"] == 188
    assert report["concept_count"] == 50
    assert report["decision_counts"] == {
        "leave_free": 3,
        "map": 188,
    }
    assert len(assets.projections) == 188
