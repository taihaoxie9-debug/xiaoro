from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.guide_data.backfill_specification_projections import (
    SpecificationBackfill,
    SpecificationBackfillError,
    backfill_specification_projections,
)


def _write_review(path: Path) -> None:
    rows = [
        {
            "product_id": 33,
            "review_status": "accepted",
            "subject_scope": "exact_product",
            "variant_scope": None,
            "allowed_uses": ["answer", "compare", "display"],
            "selection_review": {
                "decision": "comparison_only",
                "visual_confirmed": True,
                "rationale": "规格原文可比较。",
                "projections": [],
            },
        },
        {
            "product_id": 45,
            "review_status": "accepted",
            "subject_scope": "exact_variant",
            "variant_scope": "40g双瓶",
            "allowed_uses": ["answer", "compare", "display"],
            "selection_review": {
                "decision": "projected",
                "visual_confirmed": True,
                "rationale": "保留现有功效投影。",
                "projections": [
                    {
                        "field_key": "efficacy",
                        "normalized_value": "保湿",
                        "capabilities": ["compare", "soft_rank"],
                        "rank_strength": 1,
                        "safety_role": "ordinary",
                    }
                ],
            },
        },
    ]
    path.write_text(
        "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def test_backfill_adds_only_reviewed_net_content_projection(
    tmp_path: Path,
) -> None:
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    review = reviews / "skincare.jsonl"
    _write_review(review)

    count = backfill_specification_projections(
        review_root=reviews,
        updates=(
            SpecificationBackfill(
                review_file="skincare.jsonl",
                line_number=1,
                product_id=33,
                variant_scope=None,
                normalized_value="50ml",
            ),
            SpecificationBackfill(
                review_file="skincare.jsonl",
                line_number=2,
                product_id=45,
                variant_scope="40g双瓶",
                normalized_value="40g×2",
            ),
        ),
    )

    rows = [
        json.loads(line)
        for line in review.read_text(encoding="utf-8").splitlines()
    ]
    assert count == 2
    assert rows[0]["selection_review"]["decision"] == "projected"
    assert rows[0]["selection_review"]["projections"] == [
        {
            "capabilities": ["compare"],
            "field_key": "net_content",
            "normalized_value": "50ml",
            "rank_strength": None,
            "safety_role": "ordinary",
        }
    ]
    assert [
        projection["field_key"]
        for projection in rows[1]["selection_review"]["projections"]
    ] == ["efficacy", "net_content"]


def test_backfill_fails_before_writing_on_identity_mismatch(
    tmp_path: Path,
) -> None:
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    review = reviews / "skincare.jsonl"
    _write_review(review)
    before = review.read_bytes()

    with pytest.raises(
        SpecificationBackfillError,
        match="identity mismatch",
    ):
        backfill_specification_projections(
            review_root=reviews,
            updates=(
                SpecificationBackfill(
                    review_file="skincare.jsonl",
                    line_number=1,
                    product_id=129,
                    variant_scope=None,
                    normalized_value="50ml",
                ),
            ),
        )

    assert review.read_bytes() == before
