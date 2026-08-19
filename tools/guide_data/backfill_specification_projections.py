from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.guide.retrieval.product_evidence_assets import (
    EvidenceSelectionReview,
)


class SpecificationBackfillError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SpecificationBackfill:
    review_file: str
    line_number: int
    product_id: int
    variant_scope: str | None
    normalized_value: str


_PRODUCTION_BACKFILLS = (
    SpecificationBackfill(
        "base_makeup_batch_001.jsonl", 5, 83, "#584 35ml", "35ml"
    ),
    SpecificationBackfill(
        "base_makeup_batch_001.jsonl", 8, 124, "PO-01 30ml", "30ml"
    ),
    SpecificationBackfill(
        "base_makeup_batch_008.jsonl", 2, 82, None, "14g"
    ),
    SpecificationBackfill(
        "base_makeup_batch_010.jsonl",
        13,
        112,
        "买家照片所示日本本土版40g",
        "40g",
    ),
    SpecificationBackfill(
        "base_makeup_batch_011.jsonl",
        25,
        113,
        "买家照片所示25ml商品",
        "25ml",
    ),
    SpecificationBackfill(
        "cleanser_batch_007.jsonl", 2, 66, None, "150ml"
    ),
    SpecificationBackfill(
        "cleanser_batch_008.jsonl", 14, 67, None, "207ml"
    ),
    SpecificationBackfill(
        "fragrance_batch_002.jsonl",
        17,
        143,
        "买家照片所示N°5 EDP 35ml喷雾",
        "35ml",
    ),
    SpecificationBackfill(
        "skincare_batch_002.jsonl", 21, 33, None, "50ml"
    ),
    SpecificationBackfill(
        "skincare_batch_004.jsonl", 6, 40, None, "30ml"
    ),
    SpecificationBackfill(
        "skincare_batch_009.jsonl", 9, 45, None, "40g"
    ),
    SpecificationBackfill(
        "skincare_batch_009.jsonl",
        18,
        45,
        "40g×2双瓶销售组合",
        "40g×2",
    ),
    SpecificationBackfill(
        "skincare_batch_010.jsonl", 1, 49, "50g单瓶", "50g"
    ),
    SpecificationBackfill(
        "skincare_batch_010.jsonl",
        8,
        49,
        "50g×2囤货组合",
        "50g×2",
    ),
    SpecificationBackfill(
        "skincare_batch_017.jsonl",
        15,
        129,
        "买家照片所示50ml包装",
        "50ml",
    ),
    SpecificationBackfill(
        "skincare_batch_022.jsonl",
        8,
        75,
        "旧注册证黑械注准20162140023对应历史包装",
        "1盒×5片",
    ),
    SpecificationBackfill(
        "skincare_batch_028.jsonl",
        18,
        64,
        "限定版200ml",
        "200ml",
    ),
    SpecificationBackfill(
        "skincare_batch_029.jsonl",
        6,
        50,
        "第二代特护霜50g经典版",
        "50g",
    ),
    SpecificationBackfill(
        "suncare_batch_003.jsonl",
        8,
        54,
        "三代防晒水30ml×2销售组合",
        "30ml×2",
    ),
    SpecificationBackfill(
        "suncare_batch_004.jsonl",
        7,
        56,
        "买家背标所示限期2029.01批次",
        "50ml",
    ),
    SpecificationBackfill(
        "suncare_batch_006.jsonl",
        36,
        55,
        "15g×2双支销售组合",
        "15g×2",
    ),
    SpecificationBackfill(
        "suncare_batch_008.jsonl",
        20,
        58,
        "历史50ml+25ml×2组合",
        "50ml+25ml×2（共100ml）",
    ),
    SpecificationBackfill(
        "suncare_batch_008.jsonl",
        24,
        58,
        "历史100ml+25ml×3+15ml×2组合",
        "100ml+25ml×3+15ml×2（共205ml）",
    ),
    SpecificationBackfill(
        "suncare_batch_008.jsonl",
        28,
        58,
        "买家包装标签所示50ml版本",
        "50ml",
    ),
    SpecificationBackfill(
        "suncare_batch_009.jsonl",
        2,
        102,
        "跨境详情页所示50ml日本版",
        "50ml",
    ),
    SpecificationBackfill(
        "suncare_batch_009.jsonl",
        9,
        102,
        "买家实拍Perfect Sun Protector Lotion版本",
        "50ml",
    ),
)


def backfill_specification_projections(
    *,
    review_root: Path,
    updates: tuple[SpecificationBackfill, ...],
) -> int:
    if not isinstance(review_root, Path):
        raise TypeError("review_root must be pathlib.Path")
    if any(
        not isinstance(update, SpecificationBackfill)
        for update in updates
    ):
        raise TypeError("updates must contain SpecificationBackfill values")

    rows_by_path: dict[Path, list[dict[str, object]]] = {}
    changed = 0
    for update in updates:
        path = review_root / update.review_file
        rows = rows_by_path.get(path)
        if rows is None:
            try:
                rows = [
                    json.loads(line)
                    for line in path.read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line
                ]
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SpecificationBackfillError(
                    f"review file unavailable: {path}"
                ) from exc
            if any(not isinstance(row, dict) for row in rows):
                raise SpecificationBackfillError(
                    f"review file contains a non-object row: {path}"
                )
            rows_by_path[path] = rows
        index = update.line_number - 1
        if index < 0 or index >= len(rows):
            raise SpecificationBackfillError(
                f"review line unavailable: {path}:{update.line_number}"
            )
        row = rows[index]
        if (
            row.get("product_id") != update.product_id
            or row.get("variant_scope") != update.variant_scope
        ):
            raise SpecificationBackfillError(
                f"identity mismatch: {path}:{update.line_number}"
            )
        if row.get("review_status") != "accepted":
            raise SpecificationBackfillError(
                f"backfill requires accepted review: "
                f"{path}:{update.line_number}"
            )
        allowed_uses = row.get("allowed_uses", [])
        if not isinstance(allowed_uses, list) or (
            "compare" not in allowed_uses
        ):
            raise SpecificationBackfillError(
                f"backfill requires compare authorization: "
                f"{path}:{update.line_number}"
            )
        review = row.get("selection_review")
        if not isinstance(review, dict):
            raise SpecificationBackfillError(
                f"selection review unavailable: "
                f"{path}:{update.line_number}"
            )
        projections = review.get("projections")
        if not isinstance(projections, list):
            raise SpecificationBackfillError(
                f"selection projections unavailable: "
                f"{path}:{update.line_number}"
            )
        existing = [
            projection
            for projection in projections
            if isinstance(projection, dict)
            and projection.get("field_key") == "net_content"
        ]
        if existing:
            if len(existing) == 1 and existing[0].get(
                "normalized_value"
            ) == update.normalized_value:
                continue
            raise SpecificationBackfillError(
                f"conflicting net_content projection: "
                f"{path}:{update.line_number}"
            )
        projections.append({
            "field_key": "net_content",
            "normalized_value": update.normalized_value,
            "capabilities": ["compare"],
            "rank_strength": None,
            "safety_role": "ordinary",
        })
        review["decision"] = "projected"
        EvidenceSelectionReview.model_validate(review, strict=True)
        changed += 1

    serialized: dict[Path, str] = {}
    for path, rows in rows_by_path.items():
        serialized[path] = "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in rows
        )
    for path, payload in serialized.items():
        path.write_text(payload, encoding="utf-8")
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    arguments = parser.parse_args(argv)
    review_root = (
        Path(arguments.repo_root)
        / "data"
        / "guide_product_evidence"
        / "reviews"
    )
    changed = backfill_specification_projections(
        review_root=review_root,
        updates=_PRODUCTION_BACKFILLS,
    )
    print(
        json.dumps(
            {
                "changed": changed,
                "reviewed_backfills": len(_PRODUCTION_BACKFILLS),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SpecificationBackfill",
    "SpecificationBackfillError",
    "backfill_specification_projections",
    "main",
]
