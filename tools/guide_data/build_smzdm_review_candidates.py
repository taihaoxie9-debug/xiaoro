"""Compile reviewed SMZDM raw captures into non-promoted candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from tools.guide_data.smzdm_assets import (
    SmzdmAssetValidationError,
    build_review_candidate,
)
from tools.guide_data.smzdm_category_policy import (
    SmzdmCategoryPolicyError,
    fields_for_profile,
)


class SmzdmReviewCandidateBuildError(RuntimeError):
    """Raised when raw capture and human review cannot be joined safely."""


@dataclass(frozen=True, slots=True)
class SmzdmReviewCandidateBuildResult:
    output_dir: Path
    raw_page_count: int
    review_count: int
    candidate_count: int


def build_smzdm_review_candidates(
    *,
    raw_pages_path: str | Path,
    reviews_path: str | Path,
    output_dir: str | Path,
) -> SmzdmReviewCandidateBuildResult:
    raw_pages = _read_jsonl(Path(raw_pages_path), "raw pages")
    reviews = _read_jsonl(Path(reviews_path), "human reviews")
    raw_by_id = _index_unique(raw_pages, "canonical_product_id")
    review_by_id = _index_unique(reviews, "canonical_product_id")
    if set(raw_by_id) != set(review_by_id):
        raise SmzdmReviewCandidateBuildError(
            "raw capture requires exactly one human review per page"
        )

    candidates: list[dict[str, object]] = []
    try:
        for product_id in sorted(raw_by_id):
            candidate = build_review_candidate(
                raw_by_id[product_id],
                review_by_id[product_id],
            )
            candidate["review_policy_fields"] = list(
                fields_for_profile(candidate["category"])
            )
            candidates.append(candidate)
    except (
        SmzdmAssetValidationError,
        SmzdmCategoryPolicyError,
        ValueError,
    ) as exc:
        raise SmzdmReviewCandidateBuildError(
            f"review candidate validation failed: {exc}"
        ) from exc

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    candidate_bytes = _jsonl_bytes(candidates)
    (destination / "review_candidates.jsonl").write_bytes(candidate_bytes)
    raw_bytes = Path(raw_pages_path).read_bytes()
    review_bytes = Path(reviews_path).read_bytes()
    manifest = {
        "schema_version": "smzdm-capture-review-v1",
        "raw_page_count": len(raw_pages),
        "review_count": len(reviews),
        "candidate_count": len(candidates),
        "files": {
            "raw_pages.jsonl": hashlib.sha256(raw_bytes).hexdigest(),
            "human_reviews.jsonl": hashlib.sha256(review_bytes).hexdigest(),
            "review_candidates.jsonl": hashlib.sha256(
                candidate_bytes
            ).hexdigest(),
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        _canonical_json(manifest).encode("utf-8")
    ).hexdigest()
    (destination / "manifest.json").write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return SmzdmReviewCandidateBuildResult(
        output_dir=destination,
        raw_page_count=len(raw_pages),
        review_count=len(reviews),
        candidate_count=len(candidates),
    )


def _read_jsonl(
    path: Path,
    label: str,
) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SmzdmReviewCandidateBuildError(
            f"{label} file is unavailable"
        ) from exc
    rows: list[dict[str, object]] = []
    try:
        for line in lines:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError
            rows.append(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SmzdmReviewCandidateBuildError(
            f"{label} file contains invalid JSONL"
        ) from exc
    return rows


def _index_unique(
    rows: Sequence[Mapping[str, object]],
    key: str,
) -> dict[int, dict[str, object]]:
    indexed: dict[int, dict[str, object]] = {}
    for row in rows:
        product_id = row.get(key)
        if type(product_id) is not int or product_id < 1:
            raise SmzdmReviewCandidateBuildError(
                f"{key} must be a positive integer"
            )
        if product_id in indexed:
            raise SmzdmReviewCandidateBuildError(
                f"{key} must be unique"
            )
        indexed[product_id] = dict(row)
    return indexed


def _jsonl_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(
        _canonical_json(row).encode("utf-8") + b"\n"
        for row in rows
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build reviewed SMZDM candidate assets."
    )
    parser.add_argument("--raw-pages", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_smzdm_review_candidates(
        raw_pages_path=args.raw_pages,
        reviews_path=args.reviews,
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "candidate_count": result.candidate_count,
        "raw_page_count": result.raw_page_count,
        "review_count": result.review_count,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
