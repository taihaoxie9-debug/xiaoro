"""Build a deterministic inventory for manual parent-concept review."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Sequence
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_profiles import category_profile_for
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptCandidate,
    SelectionConceptReview,
    candidate_id_for,
)
from app.guide.retrieval.selection_fact_contracts import SelectionFact
from app.guide_runtime.composition import (
    build_category_fact_reader,
    build_product_evidence_reader,
    build_selection_fact_reader,
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class SelectionValueInventory(_StrictFrozenModel):
    normalized_value: str = Field(min_length=1)
    fact_count: int = Field(gt=0)
    product_ids: list[int] = Field(min_length=1)
    rank_strengths: list[Literal[1, 2]] = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    attribution_counts: dict[str, int]


class SelectionFieldInventory(_StrictFrozenModel):
    profile: str
    field_key: str
    fact_count: int = Field(gt=0)
    product_count: int = Field(gt=0)
    distinct_value_count: int = Field(gt=0)
    strength_1_count: int = Field(ge=0)
    strength_2_count: int = Field(ge=0)
    attribution_counts: dict[str, int]
    values: list[SelectionValueInventory] = Field(min_length=1)


class SelectionProfileInventory(_StrictFrozenModel):
    profile: str
    product_count: int = Field(gt=0)
    fact_count: int = Field(gt=0)
    soft_rank_fact_count: int = Field(gt=0)


class SelectionConceptInventory(_StrictFrozenModel):
    schema_version: Literal["guide-selection-concept-inventory-v1"] = (
        "guide-selection-concept-inventory-v1"
    )
    source_file_sha256s: dict[str, str]
    product_count: int = Field(gt=0)
    selection_fact_count: int = Field(gt=0)
    soft_rank_fact_count: int = Field(gt=0)
    non_rank_fact_count: int = Field(ge=0)
    rank_strength_counts: dict[str, int]
    attribution_counts: dict[str, int]
    profiles: list[SelectionProfileInventory] = Field(min_length=1)
    fields: list[SelectionFieldInventory] = Field(min_length=1)


class ParentConceptDecision(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^sc_[0-9a-f]{64}$")
    decision: Literal["map", "leave_free"]
    concept_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$",
    )
    stance: Literal["supports", "opposes", "not_comparable"]
    comparability: Literal["binary", "ordered", "numeric", "none"]
    order_value: int | None = Field(default=None, ge=0, le=100)
    rationale: str = Field(min_length=8, max_length=512)


_CORE_CONCEPT_FIELDS = {
    "base_makeup": frozenset({
        "coverage",
        "finish",
        "longevity",
        "texture",
    }),
    "cleanser": frozenset({
        "cleansing_power",
        "efficacy",
        "rinse_behavior",
        "texture",
    }),
    "color_makeup": frozenset({
        "color_payoff",
        "finish",
        "longevity",
    }),
    "skincare": frozenset({
        "efficacy",
        "skin_concern",
        "suitable_skin",
        "texture",
    }),
    "suncare": frozenset({
        "film_speed",
        "finish",
        "texture",
        "usage_context",
        "water_resistance",
    }),
}


def build_selection_inventory(
    repo_root: Path,
) -> SelectionConceptInventory:
    root = Path(repo_root).resolve()
    reader = CanonicalProductReader.from_files(
        manifest_path=(
            root / "data" / "canonical" / "core_products_v1_manifest.json"
        ),
        products_path=(
            root / "data" / "canonical" / "core_products_v1.jsonl"
        ),
    )
    category_facts = build_category_fact_reader(reader, repo_root=root)
    product_evidence = build_product_evidence_reader(root)
    selection = build_selection_fact_reader(
        category_facts=category_facts,
        product_evidence=product_evidence,
    )

    rows: list[SelectionFact] = []
    for product_id in sorted(reader.product_ids):
        category = reader.get(product_id).fields.get("category")
        if (
            category is None
            or category.resolved_state != "known"
            or not isinstance(category.value, str)
        ):
            continue
        try:
            profile = category_profile_for(category.value)
        except KeyError:
            continue
        rows.extend(
            selection.read(product_id=product_id, profile=profile)
        )
    soft_rows = tuple(
        row for row in rows if "soft_rank" in row.capabilities
    )

    profiles: list[SelectionProfileInventory] = []
    profile_names = sorted(
        {row.category_profile.value for row in rows}
    )
    for profile in profile_names:
        profile_rows = tuple(
            row for row in rows
            if row.category_profile.value == profile
        )
        profile_soft = tuple(
            row for row in soft_rows
            if row.category_profile.value == profile
        )
        profiles.append(
            SelectionProfileInventory(
                profile=profile,
                product_count=len({
                    row.product_id for row in profile_rows
                }),
                fact_count=len(profile_rows),
                soft_rank_fact_count=len(profile_soft),
            )
        )

    grouped: dict[tuple[str, str], list[SelectionFact]] = defaultdict(list)
    for row in soft_rows:
        grouped[(row.category_profile.value, row.field_key)].append(row)
    fields = [
        _field_inventory(profile, field_key, values)
        for (profile, field_key), values in sorted(grouped.items())
    ]

    return SelectionConceptInventory(
        source_file_sha256s=_source_hashes(root),
        product_count=len({row.product_id for row in rows}),
        selection_fact_count=len(rows),
        soft_rank_fact_count=len(soft_rows),
        non_rank_fact_count=len(rows) - len(soft_rows),
        rank_strength_counts={
            str(strength): count
            for strength, count in sorted(
                Counter(
                    row.rank_strength
                    for row in soft_rows
                ).items()
            )
            if strength is not None
        },
        attribution_counts=_attribution_counts(rows),
        profiles=profiles,
        fields=fields,
    )


def build_parent_concept_candidates(
    inventory: SelectionConceptInventory,
) -> tuple[SelectionConceptCandidate, ...]:
    if not isinstance(inventory, SelectionConceptInventory):
        raise TypeError("inventory must be SelectionConceptInventory")
    candidates: list[SelectionConceptCandidate] = []
    for field in inventory.fields:
        if field.field_key not in _CORE_CONCEPT_FIELDS.get(
            field.profile,
            frozenset(),
        ):
            continue
        for value in field.values:
            if len(value.product_ids) < 2:
                continue
            candidate_id = candidate_id_for(
                profile=field.profile,
                field_key=field.field_key,
                normalized_value=value.normalized_value,
                product_ids=tuple(value.product_ids),
                rank_strengths=tuple(value.rank_strengths),
                source_refs=tuple(value.source_refs),
            )
            candidates.append(
                SelectionConceptCandidate(
                    candidate_id=candidate_id,
                    profile=field.profile,
                    field_key=field.field_key,
                    normalized_value=value.normalized_value,
                    product_ids=tuple(value.product_ids),
                    rank_strengths=tuple(value.rank_strengths),
                    source_refs=tuple(value.source_refs),
                )
            )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.profile.value,
                item.field_key,
                item.normalized_value.casefold(),
            ),
        )
    )


def load_parent_concept_decisions(
    path: Path,
) -> tuple[ParentConceptDecision, ...]:
    decisions = tuple(
        ParentConceptDecision.model_validate_json(line, strict=True)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    ids = tuple(item.candidate_id for item in decisions)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate parent concept decision")
    return tuple(sorted(decisions, key=lambda item: item.candidate_id))


def materialize_parent_concept_reviews(
    candidates: Sequence[SelectionConceptCandidate],
    decisions: Sequence[ParentConceptDecision],
) -> tuple[SelectionConceptReview, ...]:
    candidates_by_id = {
        candidate.candidate_id: candidate
        for candidate in candidates
    }
    decisions_by_id = {
        decision.candidate_id: decision
        for decision in decisions
    }
    unknown = sorted(set(decisions_by_id) - set(candidates_by_id))
    if unknown:
        raise ValueError(
            "unknown parent concept decisions: " + ",".join(unknown)
        )
    missing = sorted(set(candidates_by_id) - set(decisions_by_id))
    if missing:
        raise ValueError(
            "missing parent concept decisions: " + ",".join(missing)
        )
    reviews = []
    for candidate in candidates:
        decision = decisions_by_id[candidate.candidate_id]
        reviews.append(
            SelectionConceptReview.model_validate(
                {
                    **candidate.model_dump(mode="python"),
                    **decision.model_dump(
                        mode="python",
                        exclude={"candidate_id"},
                    ),
                },
                strict=True,
            )
        )
    return tuple(
        sorted(
            reviews,
            key=lambda item: (
                item.profile.value,
                item.field_key,
                item.normalized_value.casefold(),
            ),
        )
    )


def write_selection_inventory(
    inventory: SelectionConceptInventory,
    path: Path,
) -> None:
    if not isinstance(inventory, SelectionConceptInventory):
        raise TypeError("inventory must be SelectionConceptInventory")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        _canonical_json(inventory.model_dump(mode="json")) + b"\n"
    )


def write_parent_concept_candidates(
    candidates: Sequence[SelectionConceptCandidate],
    path: Path,
) -> None:
    if any(
        not isinstance(item, SelectionConceptCandidate)
        for item in candidates
    ):
        raise TypeError(
            "candidates must be SelectionConceptCandidate instances"
        )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        b"".join(
            _canonical_json(item.model_dump(mode="json")) + b"\n"
            for item in candidates
        )
    )


def write_parent_concept_reviews(
    reviews: Sequence[SelectionConceptReview],
    path: Path,
) -> None:
    if any(
        not isinstance(item, SelectionConceptReview)
        for item in reviews
    ):
        raise TypeError(
            "reviews must be SelectionConceptReview instances"
        )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        b"".join(
            _canonical_json(item.model_dump(mode="json")) + b"\n"
            for item in reviews
        )
    )


def _field_inventory(
    profile: str,
    field_key: str,
    rows: list[SelectionFact],
) -> SelectionFieldInventory:
    by_value: dict[str, list[SelectionFact]] = defaultdict(list)
    for row in rows:
        by_value[row.normalized_value].append(row)
    values = [
        SelectionValueInventory(
            normalized_value=value,
            fact_count=len(value_rows),
            product_ids=sorted({
                row.product_id for row in value_rows
            }),
            rank_strengths=sorted({
                row.rank_strength
                for row in value_rows
                if row.rank_strength is not None
            }),
            source_refs=sorted({
                reference
                for row in value_rows
                for reference in row.source_refs
            }),
            attribution_counts=_attribution_counts(value_rows),
        )
        for value, value_rows in sorted(
            by_value.items(),
            key=lambda item: item[0].casefold(),
        )
    ]
    strengths = Counter(row.rank_strength for row in rows)
    return SelectionFieldInventory(
        profile=profile,
        field_key=field_key,
        fact_count=len(rows),
        product_count=len({row.product_id for row in rows}),
        distinct_value_count=len(values),
        strength_1_count=strengths[1],
        strength_2_count=strengths[2],
        attribution_counts=_attribution_counts(rows),
        values=values,
    )


def _attribution_counts(
    rows: Sequence[SelectionFact],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row.attributions)
    return dict(sorted(counts.items()))


def _source_hashes(root: Path) -> dict[str, str]:
    relative_paths = (
        "data/canonical/core_products_v1_manifest.json",
        "data/guide_category_facts/category_facts_v1_manifest.json",
        "data/guide_merchant_claims/merchant_claims_v1_manifest.json",
        "data/guide_product_evidence/product_evidence_v1_manifest.json",
        "docs/audits/evidence-use/selection_concept_audit_v1.jsonl",
    )
    return {
        path: sha256((root / path).read_bytes()).hexdigest()
        for path in relative_paths
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="materialize the deterministic inventory",
    )
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    if not arguments.inventory_only:
        raise SystemExit("--inventory-only is required in Task 1")
    write_selection_inventory(
        build_selection_inventory(Path.cwd()),
        Path(arguments.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SelectionConceptInventory",
    "SelectionFieldInventory",
    "SelectionProfileInventory",
    "SelectionValueInventory",
    "ParentConceptDecision",
    "build_parent_concept_candidates",
    "build_selection_inventory",
    "load_parent_concept_decisions",
    "main",
    "materialize_parent_concept_reviews",
    "write_parent_concept_candidates",
    "write_parent_concept_reviews",
    "write_selection_inventory",
]
