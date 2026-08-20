"""Build a deterministic inventory for manual parent-concept review."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Sequence
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
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
from tools.guide_data.review_smzdm_product import (
    validate_reviewed_product_packet,
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


class ReviewedConceptMapping(_StrictFrozenModel):
    product_id: int = Field(gt=0)
    profile: CategoryProfile
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    normalized_value: str = Field(min_length=1, max_length=512)
    concept_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$"
    )
    review_fact_id: str = Field(min_length=1, max_length=256)
    rationale: str = Field(min_length=1, max_length=512)

    @field_validator("profile", mode="before")
    @classmethod
    def parse_profile(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return CategoryProfile(value)
            except ValueError:
                return value
        return value

    @model_validator(mode="after")
    def validate_mapping(self) -> Self:
        if not self.concept_id.startswith(f"{self.field_key}."):
            raise ValueError("concept_id must be field-scoped")
        if self.normalized_value != self.normalized_value.strip():
            raise ValueError("normalized_value must be trimmed")
        return self


class ReviewedConceptPolicy(_StrictFrozenModel):
    concept_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$"
    )
    stance: Literal["supports", "opposes"]
    comparability: Literal["binary", "ordered", "numeric"]
    order_value: int | None = Field(default=None, ge=0, le=100)
    rationale: str = Field(min_length=8, max_length=512)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if (
            self.comparability == "ordered"
            and self.order_value is None
        ):
            raise ValueError("ordered policy requires order_value")
        if (
            self.comparability != "ordered"
            and self.order_value is not None
        ):
            raise ValueError(
                "order_value is allowed only for ordered policy"
            )
        return self


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
    *,
    reviewed_mappings: Sequence[ReviewedConceptMapping] = (),
) -> tuple[SelectionConceptCandidate, ...]:
    if not isinstance(inventory, SelectionConceptInventory):
        raise TypeError("inventory must be SelectionConceptInventory")
    if any(
        not isinstance(item, ReviewedConceptMapping)
        for item in reviewed_mappings
    ):
        raise TypeError(
            "reviewed_mappings must contain ReviewedConceptMapping"
        )
    inventory_values = {
        (
            field.profile,
            field.field_key,
            value.normalized_value.casefold(),
        ): value
        for field in inventory.fields
        for value in field.values
    }
    candidate_values: dict[
        tuple[str, str, str],
        SelectionValueInventory,
    ] = {}
    for field in inventory.fields:
        if field.field_key not in _CORE_CONCEPT_FIELDS.get(
            field.profile,
            frozenset(),
        ):
            continue
        for value in field.values:
            if len(value.product_ids) < 2:
                continue
            candidate_values[(
                field.profile,
                field.field_key,
                value.normalized_value.casefold(),
            )] = value

    reviewed_concepts: dict[tuple[str, str, str], str] = {}
    for mapping in reviewed_mappings:
        key = (
            mapping.profile.value,
            mapping.field_key,
            mapping.normalized_value.casefold(),
        )
        if mapping.field_key not in _CORE_CONCEPT_FIELDS.get(
            mapping.profile.value,
            frozenset(),
        ):
            raise ValueError(
                "reviewed map field is outside parent concept policy"
            )
        value = inventory_values.get(key)
        if value is None or mapping.product_id not in value.product_ids:
            raise ValueError(
                "reviewed map value is absent from selection inventory"
            )
        previous_concept = reviewed_concepts.setdefault(
            key,
            mapping.concept_id,
        )
        if previous_concept != mapping.concept_id:
            raise ValueError(
                "reviewed map value has conflicting parent concepts"
            )
        candidate_values[key] = value

    candidates = [
        _candidate_from_value(
            profile=profile,
            field_key=field_key,
            value=value,
        )
        for (profile, field_key, _), value
        in candidate_values.items()
    ]
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


def load_reviewed_concept_mappings(
    review_paths: Sequence[Path],
) -> tuple[ReviewedConceptMapping, ...]:
    mappings: list[ReviewedConceptMapping] = []
    seen_fact_ids: set[str] = set()
    for path in sorted(Path(item) for item in review_paths):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid reviewed product packet: {path}"
            ) from exc
        if not isinstance(raw, dict):
            raise ValueError(
                f"reviewed product packet must be an object: {path}"
            )
        packet = validate_reviewed_product_packet(raw)
        profile = CategoryProfile(str(packet["category_profile"]))
        product_id = int(packet["product_id"])
        for fact in packet["candidate_facts"]:
            if fact["decision"] != "map":
                continue
            fact_id = str(fact["fact_id"])
            if fact_id in seen_fact_ids:
                raise ValueError(
                    "duplicate reviewed map fact identity"
                )
            seen_fact_ids.add(fact_id)
            field_key = _promoted_field_key(str(fact["field_key"]))
            mappings.append(
                ReviewedConceptMapping(
                    product_id=product_id,
                    profile=profile,
                    field_key=field_key,
                    normalized_value=str(fact["public_text"]),
                    concept_id=str(fact["concept_id"]),
                    review_fact_id=fact_id,
                    rationale=str(fact["review_rationale"]),
                )
            )
    return tuple(sorted(
        mappings,
        key=lambda item: (
            item.profile.value,
            item.field_key,
            item.normalized_value.casefold(),
            item.product_id,
            item.review_fact_id,
        ),
    ))


def build_review_v2_decisions(
    *,
    candidates: Sequence[SelectionConceptCandidate],
    prior_reviews: Sequence[SelectionConceptReview],
    reviewed_mappings: Sequence[ReviewedConceptMapping],
    new_concept_policies: Sequence[ReviewedConceptPolicy],
) -> tuple[ParentConceptDecision, ...]:
    if any(
        not isinstance(item, SelectionConceptCandidate)
        for item in candidates
    ):
        raise TypeError(
            "candidates must contain SelectionConceptCandidate"
        )
    if any(
        not isinstance(item, SelectionConceptReview)
        for item in prior_reviews
    ):
        raise TypeError(
            "prior_reviews must contain SelectionConceptReview"
        )
    if any(
        not isinstance(item, ReviewedConceptMapping)
        for item in reviewed_mappings
    ):
        raise TypeError(
            "reviewed_mappings must contain ReviewedConceptMapping"
        )
    if any(
        not isinstance(item, ReviewedConceptPolicy)
        for item in new_concept_policies
    ):
        raise TypeError(
            "new_concept_policies must contain ReviewedConceptPolicy"
        )

    prior_by_key = {
        _concept_value_key(item): item
        for item in prior_reviews
    }
    if len(prior_by_key) != len(prior_reviews):
        raise ValueError("duplicate prior concept review value")

    mapped_concepts: dict[tuple[str, str, str], str] = {}
    for mapping in reviewed_mappings:
        key = _concept_value_key(mapping)
        previous = mapped_concepts.setdefault(
            key,
            mapping.concept_id,
        )
        if previous != mapping.concept_id:
            raise ValueError(
                "reviewed map value has conflicting parent concepts"
            )

    existing_policies: dict[str, ReviewedConceptPolicy] = {}
    for review in prior_reviews:
        if review.decision != "map" or review.concept_id is None:
            continue
        policy = ReviewedConceptPolicy(
            concept_id=review.concept_id,
            stance=review.stance,
            comparability=review.comparability,
            order_value=review.order_value,
            rationale=(
                f"{review.concept_id} 已通过 v1 人工父概念审核。"
            ),
        )
        previous = existing_policies.setdefault(
            review.concept_id,
            policy,
        )
        if (
            previous.stance,
            previous.comparability,
            previous.order_value,
        ) != (
            policy.stance,
            policy.comparability,
            policy.order_value,
        ):
            raise ValueError(
                "prior concept metadata is inconsistent"
            )

    new_policy_by_id = {
        item.concept_id: item
        for item in new_concept_policies
    }
    if len(new_policy_by_id) != len(new_concept_policies):
        raise ValueError("duplicate new concept policy")
    if set(new_policy_by_id) & set(existing_policies):
        raise ValueError(
            "new concept policy cannot replace prior concept metadata"
        )
    required_new_concepts = (
        set(mapped_concepts.values()) - set(existing_policies)
    )
    if set(new_policy_by_id) != required_new_concepts:
        raise ValueError(
            "new concept policies must exactly cover new mapped concepts"
        )
    policies = {**existing_policies, **new_policy_by_id}

    candidate_keys = {
        _concept_value_key(item)
        for item in candidates
    }
    if not set(mapped_concepts) <= candidate_keys:
        raise ValueError(
            "reviewed map value is absent from candidate inventory"
        )

    decisions = []
    for candidate in candidates:
        key = _concept_value_key(candidate)
        prior = prior_by_key.get(key)
        mapped_concept = mapped_concepts.get(key)
        if prior is not None:
            if mapped_concept is not None and (
                prior.decision != "map"
                or prior.concept_id != mapped_concept
            ):
                raise ValueError(
                    "terminal map conflicts with prior concept review"
                )
            decisions.append(
                ParentConceptDecision(
                    candidate_id=candidate.candidate_id,
                    decision=prior.decision,
                    concept_id=prior.concept_id,
                    stance=prior.stance,
                    comparability=prior.comparability,
                    order_value=prior.order_value,
                    rationale=prior.rationale,
                )
            )
            continue
        if mapped_concept is None:
            raise ValueError(
                "candidate lacks prior or terminal map review"
            )
        policy = policies.get(mapped_concept)
        if policy is None:
            raise ValueError(
                "mapped concept lacks reviewed semantic policy"
            )
        decisions.append(
            ParentConceptDecision(
                candidate_id=candidate.candidate_id,
                decision="map",
                concept_id=mapped_concept,
                stance=policy.stance,
                comparability=policy.comparability,
                order_value=policy.order_value,
                rationale=policy.rationale,
            )
        )
    return tuple(
        sorted(decisions, key=lambda item: item.candidate_id)
    )


def _concept_value_key(
    item: (
        SelectionConceptCandidate
        | SelectionConceptReview
        | ReviewedConceptMapping
    ),
) -> tuple[str, str, str]:
    return (
        item.profile.value,
        item.field_key,
        item.normalized_value.casefold(),
    )


def _candidate_from_value(
    *,
    profile: str,
    field_key: str,
    value: SelectionValueInventory,
) -> SelectionConceptCandidate:
    product_ids = tuple(value.product_ids)
    rank_strengths = tuple(value.rank_strengths)
    source_refs = tuple(value.source_refs)
    return SelectionConceptCandidate(
        candidate_id=candidate_id_for(
            profile=profile,
            field_key=field_key,
            normalized_value=value.normalized_value,
            product_ids=product_ids,
            rank_strengths=rank_strengths,
            source_refs=source_refs,
        ),
        profile=profile,
        field_key=field_key,
        normalized_value=value.normalized_value,
        product_ids=product_ids,
        rank_strengths=rank_strengths,
        source_refs=source_refs,
    )


def _promoted_field_key(field_key: str) -> str:
    return (
        "claimed_ingredients"
        if field_key == "ingredients_present"
        else field_key
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


def write_reviewed_concept_mappings(
    mappings: Sequence[ReviewedConceptMapping],
    path: Path,
) -> None:
    if any(
        not isinstance(item, ReviewedConceptMapping)
        for item in mappings
    ):
        raise TypeError(
            "mappings must be ReviewedConceptMapping instances"
        )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        b"".join(
            _canonical_json(item.model_dump(mode="json")) + b"\n"
            for item in mappings
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
    parser.add_argument("--output")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--review-dir")
    parser.add_argument("--output-dir")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    if arguments.inventory_only:
        if arguments.output is None or arguments.output_dir is not None:
            raise SystemExit(
                "--inventory-only requires --output and forbids --output-dir"
            )
        write_selection_inventory(
            build_selection_inventory(Path(arguments.repo_root)),
            Path(arguments.output),
        )
        return 0
    if arguments.output_dir is None or arguments.output is not None:
        raise SystemExit(
            "review packet mode requires --output-dir and forbids --output"
        )

    root = Path(arguments.repo_root).resolve()
    review_dir = (
        Path(arguments.review_dir).resolve()
        if arguments.review_dir is not None
        else (
            root
            / "docs"
            / "audits"
            / "smzdm-data"
            / "reviewed-products"
        )
    )
    review_paths = tuple(sorted(
        review_dir.glob("product-*-v1.json")
    ))
    if not review_paths:
        raise SystemExit("review directory contains no product packets")
    output_dir = Path(arguments.output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    inventory_path = output_dir / "inventory.json"
    candidates_path = output_dir / "candidates.jsonl"
    mappings_path = output_dir / "reviewed_mappings.jsonl"

    inventory = build_selection_inventory(root)
    mappings = load_reviewed_concept_mappings(review_paths)
    candidates = build_parent_concept_candidates(
        inventory,
        reviewed_mappings=mappings,
    )
    write_selection_inventory(inventory, inventory_path)
    write_parent_concept_candidates(candidates, candidates_path)
    write_reviewed_concept_mappings(mappings, mappings_path)

    manifest_payload = {
        "schema_version": "guide-selection-concept-review-packet-v2",
        "inventory_file": inventory_path.name,
        "inventory_sha256": _file_hash(inventory_path),
        "candidates_file": candidates_path.name,
        "candidates_sha256": _file_hash(candidates_path),
        "reviewed_mappings_file": mappings_path.name,
        "reviewed_mappings_sha256": _file_hash(mappings_path),
        "review_packet_count": len(review_paths),
        "review_packet_sha256s": {
            path.name: _file_hash(path)
            for path in review_paths
        },
        "candidate_count": len(candidates),
        "reviewed_mapping_count": len(mappings),
    }
    manifest_payload["manifest_sha256"] = sha256(
        _canonical_json(manifest_payload)
    ).hexdigest()
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_bytes(
        _canonical_json(manifest_payload) + b"\n"
    )
    print(_canonical_json({
        "candidate_count": len(candidates),
        "manifest_path": str(manifest_path),
        "review_packet_count": len(review_paths),
        "reviewed_mapping_count": len(mappings),
    }).decode("utf-8"))
    return 0


def _file_hash(path: Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SelectionConceptInventory",
    "SelectionFieldInventory",
    "SelectionProfileInventory",
    "SelectionValueInventory",
    "ParentConceptDecision",
    "ReviewedConceptMapping",
    "ReviewedConceptPolicy",
    "build_parent_concept_candidates",
    "build_review_v2_decisions",
    "build_selection_inventory",
    "load_parent_concept_decisions",
    "load_reviewed_concept_mappings",
    "main",
    "materialize_parent_concept_reviews",
    "write_parent_concept_candidates",
    "write_parent_concept_reviews",
    "write_reviewed_concept_mappings",
    "write_selection_inventory",
]
