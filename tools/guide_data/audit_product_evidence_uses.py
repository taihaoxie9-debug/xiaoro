from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from app.guide.retrieval.product_evidence_assets import (
    EvidenceSelectionReview,
)


class EvidenceUseAuditError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SpecificationProjectionGap:
    product_id: int
    subject_scope: str
    variant_scope: str | None
    capacity_values: tuple[str, ...]
    review_path: str
    line_number: int
    uniquely_bound: bool


@dataclass(frozen=True, slots=True)
class EvidenceUseAuditResult:
    accepted_total: int
    accepted_reviewed: int
    accepted_missing: int
    nonaccepted_with_review: int
    projected: int
    answer_only: int
    comparison_only: int
    safety_gate: int
    answer_only_without_rationale: int
    duplicate_projection_keys: int
    authorization_mismatches: int
    invalid_reviews: int
    specification_projection_gap_count: int
    unique_specification_projection_gap_count: int
    specification_projection_gaps: tuple[
        SpecificationProjectionGap,
        ...,
    ]
    projections_by_field: dict[str, int]
    projections_by_capability: dict[str, int]
    projections_by_strength: dict[str, int]

    def assert_clean(self) -> None:
        if any(
            (
                self.accepted_missing,
                self.nonaccepted_with_review,
                self.answer_only_without_rationale,
                self.duplicate_projection_keys,
                self.authorization_mismatches,
                self.invalid_reviews,
                self.unique_specification_projection_gap_count,
            )
        ):
            raise EvidenceUseAuditError(
                "evidence use audit is incomplete"
            )


def audit_product_evidence_uses(
    review_paths: tuple[Path, ...],
) -> EvidenceUseAuditResult:
    accepted_total = 0
    accepted_reviewed = 0
    nonaccepted_with_review = 0
    projected = 0
    answer_only = 0
    comparison_only = 0
    safety_gate = 0
    answer_only_without_rationale = 0
    duplicate_projection_keys = 0
    authorization_mismatches = 0
    invalid_reviews = 0
    fields: Counter[str] = Counter()
    capabilities: Counter[str] = Counter()
    strengths: Counter[str] = Counter()
    specification_projection_gaps: list[
        SpecificationProjectionGap
    ] = []

    for row, path, line_number in _load_rows(review_paths):
        status = row.get("review_status")
        review_payload = row.get("selection_review")
        if status != "accepted":
            if review_payload is not None:
                nonaccepted_with_review += 1
            continue
        accepted_total += 1
        if not isinstance(review_payload, dict):
            continue
        accepted_reviewed += 1
        decision = review_payload.get("decision")
        if decision == "projected":
            projected += 1
        elif decision == "answer_only":
            answer_only += 1
        elif decision == "comparison_only":
            comparison_only += 1
        elif decision == "safety_gate":
            safety_gate += 1
        rationale = review_payload.get("rationale")
        if decision == "answer_only" and (
            not isinstance(rationale, str)
            or not rationale.strip()
        ):
            answer_only_without_rationale += 1
        raw_projections = review_payload.get("projections", [])
        allowed_uses = set(row.get("allowed_uses", []))
        if not isinstance(raw_projections, list):
            invalid_reviews += 1
            continue
        specification_gap = _specification_projection_gap(
            row,
            raw_projections=raw_projections,
            path=path,
            line_number=line_number,
        )
        if specification_gap is not None:
            specification_projection_gaps.append(
                specification_gap
            )
        keys: list[tuple[str, str]] = []
        for projection in raw_projections:
            if not isinstance(projection, dict):
                invalid_reviews += 1
                continue
            field_key = projection.get("field_key")
            normalized_value = projection.get("normalized_value")
            if isinstance(field_key, str) and isinstance(
                normalized_value,
                str,
            ):
                keys.append(
                    (field_key, normalized_value.casefold())
                )
                fields[field_key] += 1
            raw_capabilities = projection.get("capabilities", [])
            if isinstance(raw_capabilities, list):
                if (
                    "soft_rank" in raw_capabilities
                    and not {
                        "soft_rank",
                        "weak_soft_rank",
                    }.intersection(allowed_uses)
                ):
                    authorization_mismatches += 1
                if (
                    "hard_filter" in raw_capabilities
                    and "hard_filter" not in allowed_uses
                ):
                    authorization_mismatches += 1
                if (
                    "compare" in raw_capabilities
                    and "compare" not in allowed_uses
                ):
                    authorization_mismatches += 1
                if (
                    "safety_gate" in raw_capabilities
                    and "safety_gate" not in allowed_uses
                ):
                    authorization_mismatches += 1
                capabilities.update(
                    value
                    for value in raw_capabilities
                    if isinstance(value, str)
                )
            strength = projection.get("rank_strength")
            if strength is not None:
                strengths[str(strength)] += 1
        duplicate_projection_keys += len(keys) - len(set(keys))
        try:
            EvidenceSelectionReview.model_validate(
                review_payload,
                strict=True,
            )
        except ValidationError:
            invalid_reviews += 1

    return EvidenceUseAuditResult(
        accepted_total=accepted_total,
        accepted_reviewed=accepted_reviewed,
        accepted_missing=accepted_total - accepted_reviewed,
        nonaccepted_with_review=nonaccepted_with_review,
        projected=projected,
        answer_only=answer_only,
        comparison_only=comparison_only,
        safety_gate=safety_gate,
        answer_only_without_rationale=answer_only_without_rationale,
        duplicate_projection_keys=duplicate_projection_keys,
        authorization_mismatches=authorization_mismatches,
        invalid_reviews=invalid_reviews,
        specification_projection_gap_count=len(
            specification_projection_gaps
        ),
        unique_specification_projection_gap_count=sum(
            gap.uniquely_bound
            for gap in specification_projection_gaps
        ),
        specification_projection_gaps=tuple(
            specification_projection_gaps
        ),
        projections_by_field=dict(sorted(fields.items())),
        projections_by_capability=dict(sorted(capabilities.items())),
        projections_by_strength=dict(sorted(strengths.items())),
    )


def _load_rows(
    paths: tuple[Path, ...],
) -> list[tuple[dict[str, object], Path, int]]:
    rows: list[tuple[dict[str, object], Path, int]] = []
    for path in sorted(paths, key=lambda item: str(item)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise EvidenceUseAuditError(
                f"evidence review is unavailable: {path}"
            ) from exc
        for line_number, line in enumerate(lines, start=1):
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvidenceUseAuditError(
                    f"invalid evidence review line: {path}:{line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise EvidenceUseAuditError(
                    f"evidence review row is not an object: "
                    f"{path}:{line_number}"
                )
            rows.append((row, path, line_number))
    return rows


_CAPACITY_PREDICATE_MARKERS = (
    "net_content",
    "specification",
    "quantity",
    "size_option",
    "bundle",
)
_CAPACITY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9.])"
    r"(\d+(?:\.\d+)?\s*(?:ml|g|片|瓶|盒|支)"
    r"(?:\s*[xX×]\s*\d+(?:\s*(?:片|瓶|盒|支))?)?)",
    flags=re.IGNORECASE,
)


def _specification_projection_gap(
    row: dict[str, object],
    *,
    raw_projections: list[object],
    path: Path,
    line_number: int,
) -> SpecificationProjectionGap | None:
    if any(
        isinstance(projection, dict)
        and projection.get("field_key") == "net_content"
        for projection in raw_projections
    ):
        return None
    subject_scope = row.get("subject_scope")
    if subject_scope not in {"exact_product", "exact_variant"}:
        return None
    raw_relations = row.get("relations", [])
    if not isinstance(raw_relations, list):
        return None
    capacity_values: list[str] = []
    for relation in raw_relations:
        if not isinstance(relation, dict):
            continue
        predicate = relation.get("predicate")
        relation_object = relation.get("object")
        if not isinstance(predicate, str) or not isinstance(
            relation_object,
            str,
        ):
            continue
        normalized_predicate = predicate.casefold()
        if not any(
            marker in normalized_predicate
            for marker in _CAPACITY_PREDICATE_MARKERS
        ):
            continue
        for matched in _CAPACITY_PATTERN.findall(relation_object):
            normalized_value = re.sub(r"\s+", "", matched).lower()
            normalized_value = re.sub(
                r"[xX]",
                "×",
                normalized_value,
            )
            if normalized_value not in capacity_values:
                capacity_values.append(normalized_value)
    if not capacity_values:
        return None
    product_id = row.get("product_id")
    if (
        not isinstance(product_id, int)
        or isinstance(product_id, bool)
        or product_id <= 0
    ):
        return None
    variant_scope = row.get("variant_scope")
    if not isinstance(variant_scope, str):
        variant_scope = None
    return SpecificationProjectionGap(
        product_id=product_id,
        subject_scope=subject_scope,
        variant_scope=variant_scope,
        capacity_values=tuple(capacity_values),
        review_path=str(path),
        line_number=line_number,
        uniquely_bound=(
            subject_scope == "exact_variant"
            or len(capacity_values) == 1
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--review",
        action="append",
    )
    parser.add_argument("--repo-root")
    parser.add_argument(
        "--require-clean",
        action="store_true",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    review_paths = tuple(
        Path(value) for value in (arguments.review or ())
    )
    if arguments.repo_root is not None:
        repo_root = Path(arguments.repo_root)
        review_paths = (
            *review_paths,
            *sorted(
                (
                    repo_root
                    / "data"
                    / "guide_product_evidence"
                    / "reviews"
                ).glob("*.jsonl")
            ),
        )
    if not review_paths:
        parser.error("one of --review or --repo-root is required")
    result = audit_product_evidence_uses(
        tuple(review_paths)
    )
    print(
        json.dumps(
            asdict(result),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    if arguments.require_clean:
        try:
            result.assert_clean()
        except EvidenceUseAuditError:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EvidenceUseAuditError",
    "EvidenceUseAuditResult",
    "SpecificationProjectionGap",
    "audit_product_evidence_uses",
    "main",
]
