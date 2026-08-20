from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_fact_assets import (
    CategoryFactAssetIntegrityError,
    load_category_fact_assets,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile


_SHA256_LENGTH = 64
_CORE_FIELDS = frozenset(
    {"product_identity", "brand", "category", "price"}
)
_SUITABILITY_FIELDS = frozenset(
    {"suitable_skin", "safety", "ingredients_present"}
)
_FIELD_STATES = (
    "known",
    "pending",
    "quarantine",
    "unknown",
    "not_applicable",
)
_READINESS_STATES = (
    "IDENTITY_READY",
    "RECOMMEND_READY",
    "COMPARE_READY",
    "SUITABILITY_READY",
    "FULL_READY",
    "BLOCKED",
)
_READINESS_RANK = {
    "BLOCKED": 0,
    "IDENTITY_READY": 1,
    "RECOMMEND_READY": 2,
    "COMPARE_READY": 3,
    "SUITABILITY_READY": 4,
    "FULL_READY": 5,
}


class PostPromotionReadinessError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PostPromotionReadinessReport:
    schema_version: str
    matrix_sha256: str
    facts_sha256: str
    output_sha256: str
    product_count: int
    promoted_fact_count: int
    known_delta: int
    pending_delta: int
    quarantine_delta: int
    unknown_delta: int
    not_applicable_delta: int
    readiness_transition_count: int
    baseline_readiness_counts: dict[str, int]
    promoted_readiness_counts: dict[str, int]


def derive_product_readiness(
    *,
    binding_status: str,
    category_profile: CategoryProfile,
    field_states: Mapping[str, str],
) -> str:
    if not isinstance(category_profile, CategoryProfile):
        raise TypeError("category_profile must be a CategoryProfile")
    normalized_states = _validate_field_states(
        category_profile=category_profile,
        field_states=field_states,
    )
    if any(
        normalized_states.get(field) != "known"
        for field in _CORE_FIELDS
    ):
        return "BLOCKED"
    if binding_status != "exact_item":
        return "IDENTITY_READY"

    applicable = {
        field
        for field, state in normalized_states.items()
        if state != "not_applicable"
    }
    if all(normalized_states[field] == "known" for field in applicable):
        return "FULL_READY"

    required_suitability = _SUITABILITY_FIELDS & applicable
    if required_suitability and all(
        normalized_states[field] == "known"
        for field in required_suitability
    ):
        return "SUITABILITY_READY"

    compare_fields = _compare_fields(category_profile) & applicable
    if any(
        normalized_states[field] == "known"
        for field in compare_fields
    ):
        return "COMPARE_READY"
    return "RECOMMEND_READY"


def build_post_promotion_readiness(
    *,
    matrix_path: str | Path,
    manifest_path: str | Path,
    facts_path: str | Path,
    output_path: str | Path,
    expected_matrix_sha256: str,
    expected_manifest_sha256: str,
    canonical_manifest_path: str | Path,
    canonical_products_path: str | Path,
) -> PostPromotionReadinessReport:
    matrix_file = Path(matrix_path)
    output_file = Path(output_path)
    matrix_sha256 = _verified_sha256(
        matrix_file,
        expected_matrix_sha256,
        label="matrix",
    )
    canonical_reader = CanonicalProductReader.from_files(
        manifest_path=canonical_manifest_path,
        products_path=canonical_products_path,
    )
    try:
        assets = load_category_fact_assets(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=expected_manifest_sha256,
            canonical_reader=canonical_reader,
            field_registry=category_field_registry(),
        )
    except CategoryFactAssetIntegrityError as exc:
        raise PostPromotionReadinessError(str(exc)) from exc
    facts_sha256 = assets.manifest.facts_sha256
    matrix_rows = _read_jsonl(matrix_file, label="matrix")
    facts = [
        fact.model_dump(mode="json")
        for fact in assets.facts
    ]
    if not matrix_rows:
        raise PostPromotionReadinessError("matrix must not be empty")

    rows_by_product: dict[int, dict[str, object]] = {}
    for row in matrix_rows:
        product_id = _positive_int(row.get("product_id"), "product_id")
        if product_id in rows_by_product:
            raise PostPromotionReadinessError(
                f"duplicate matrix product_id: {product_id}"
            )
        rows_by_product[product_id] = deepcopy(row)

    promoted_by_product: dict[int, list[str]] = {}
    seen_facts: set[tuple[int, str]] = set()
    for fact in facts:
        product_id = _positive_int(
            fact.get("product_id"),
            "fact product_id",
        )
        row = rows_by_product.get(product_id)
        if row is None:
            raise PostPromotionReadinessError(
                f"fact product is absent from matrix: {product_id}"
            )
        profile = _profile(row.get("category_profile"))
        fact_profile = _profile(fact.get("category_profile"))
        if fact_profile is not profile:
            raise PostPromotionReadinessError(
                f"fact profile mismatch for product_id {product_id}"
            )
        if fact.get("evidence_status") != "approved_fact":
            raise PostPromotionReadinessError(
                "post-promotion facts require approved_fact status"
            )
        field_key = fact.get("field_key")
        if not isinstance(field_key, str) or not field_key:
            raise PostPromotionReadinessError(
                "fact field_key must be a non-empty string"
            )
        identity = (product_id, field_key)
        if identity in seen_facts:
            raise PostPromotionReadinessError(
                f"duplicate promoted fact: {product_id}.{field_key}"
            )
        seen_facts.add(identity)
        states = row.get("field_states")
        if not isinstance(states, dict) or field_key not in states:
            raise PostPromotionReadinessError(
                f"fact field is absent from matrix: {product_id}.{field_key}"
            )
        if states[field_key] == "not_applicable":
            raise PostPromotionReadinessError(
                "promoted fact cannot target a not_applicable field"
            )
        if fact.get("value") is None:
            raise PostPromotionReadinessError(
                "approved fact requires a non-null value"
            )
        states[field_key] = "known"
        fact_id = fact.get("fact_id")
        if (
            not isinstance(fact_id, str)
            or len(fact_id) != _SHA256_LENGTH
        ):
            raise PostPromotionReadinessError(
                "approved fact requires a SHA-256 fact_id"
            )
        promoted_by_product.setdefault(product_id, []).append(fact_id)

    baseline_counts = Counter()
    promoted_counts = Counter()
    baseline_readiness = Counter()
    promoted_readiness = Counter()
    transition_count = 0
    output_rows: list[dict[str, object]] = []
    baseline_by_product = {
        _positive_int(row.get("product_id"), "product_id"): row
        for row in matrix_rows
    }
    for product_id in sorted(rows_by_product):
        baseline_row = baseline_by_product[product_id]
        promoted_row = rows_by_product[product_id]
        profile = _profile(promoted_row.get("category_profile"))
        baseline_states = _validate_field_states(
            category_profile=profile,
            field_states=_states(baseline_row),
        )
        promoted_states = _validate_field_states(
            category_profile=profile,
            field_states=_states(promoted_row),
        )
        for state in _FIELD_STATES:
            baseline_counts[state] += sum(
                value == state for value in baseline_states.values()
            )
            promoted_counts[state] += sum(
                value == state for value in promoted_states.values()
            )
        binding_status = promoted_row.get("binding_status")
        if not isinstance(binding_status, str) or not binding_status:
            raise PostPromotionReadinessError(
                "binding_status must be a non-empty string"
            )
        before = derive_product_readiness(
            binding_status=binding_status,
            category_profile=profile,
            field_states=baseline_states,
        )
        after = derive_product_readiness(
            binding_status=binding_status,
            category_profile=profile,
            field_states=promoted_states,
        )
        if _READINESS_RANK[after] < _READINESS_RANK[before]:
            raise PostPromotionReadinessError(
                f"readiness regressed for product_id {product_id}"
            )
        transition_count += after != before
        baseline_readiness[before] += 1
        promoted_readiness[after] += 1
        output_rows.append(
            {
                **promoted_row,
                "baseline_readiness": before,
                "field_states": promoted_states,
                "promoted_fact_ids": sorted(
                    promoted_by_product.get(product_id, ())
                ),
                "readiness": after,
                "state_counts": {
                    state: sum(
                        value == state
                        for value in promoted_states.values()
                    )
                    for state in _FIELD_STATES
                },
            }
        )

    output_bytes = _render_jsonl(output_rows)
    _atomic_write(output_file, output_bytes)
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    return PostPromotionReadinessReport(
        schema_version="full-catalog-post-promotion-readiness-v1",
        matrix_sha256=matrix_sha256,
        facts_sha256=facts_sha256,
        output_sha256=output_sha256,
        product_count=len(output_rows),
        promoted_fact_count=len(facts),
        known_delta=promoted_counts["known"] - baseline_counts["known"],
        pending_delta=(
            promoted_counts["pending"] - baseline_counts["pending"]
        ),
        quarantine_delta=(
            promoted_counts["quarantine"]
            - baseline_counts["quarantine"]
        ),
        unknown_delta=(
            promoted_counts["unknown"] - baseline_counts["unknown"]
        ),
        not_applicable_delta=(
            promoted_counts["not_applicable"]
            - baseline_counts["not_applicable"]
        ),
        readiness_transition_count=transition_count,
        baseline_readiness_counts=_complete_readiness_counts(
            baseline_readiness
        ),
        promoted_readiness_counts=_complete_readiness_counts(
            promoted_readiness
        ),
    )


def _compare_fields(profile: CategoryProfile) -> frozenset[str]:
    return frozenset(
        definition.key
        for definition in category_field_registry().for_profile(profile)
        if definition.key not in _CORE_FIELDS
        and any(
            "compare" in policy.capabilities
            for policy in definition.source_policies
        )
    )


def _validate_field_states(
    *,
    category_profile: CategoryProfile,
    field_states: Mapping[str, str],
) -> dict[str, str]:
    if not isinstance(field_states, Mapping):
        raise TypeError("field_states must be a mapping")
    expected = {
        definition.key
        for definition in category_field_registry().definitions
    }
    if set(field_states) != expected:
        raise PostPromotionReadinessError(
            "field_states must cover the complete registry"
        )
    normalized = dict(field_states)
    if any(state not in _FIELD_STATES for state in normalized.values()):
        raise PostPromotionReadinessError(
            "field_states contains an invalid state"
        )
    applicable = {
        definition.key
        for definition in category_field_registry().for_profile(
            category_profile
        )
    }
    if any(
        (
            field in applicable
            and state == "not_applicable"
        )
        or (
            field not in applicable
            and state != "not_applicable"
        )
        for field, state in normalized.items()
    ):
        raise PostPromotionReadinessError(
            "field applicability does not match category profile"
        )
    return normalized


def _states(row: Mapping[str, object]) -> Mapping[str, str]:
    states = row.get("field_states")
    if not isinstance(states, Mapping):
        raise PostPromotionReadinessError(
            "matrix row requires field_states"
        )
    return states


def _profile(value: object) -> CategoryProfile:
    try:
        return CategoryProfile(value)
    except (TypeError, ValueError):
        raise PostPromotionReadinessError(
            "invalid category_profile"
        ) from None


def _positive_int(value: object, label: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise PostPromotionReadinessError(
            f"{label} must be a positive integer"
        )
    return value


def _verified_sha256(
    path: Path,
    expected: str,
    *,
    label: str,
) -> str:
    if (
        not isinstance(expected, str)
        or len(expected) != _SHA256_LENGTH
    ):
        raise PostPromotionReadinessError(
            f"expected {label} SHA-256 is invalid"
        )
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise PostPromotionReadinessError(
            f"{label} SHA-256 mismatch"
        )
    return actual


def _read_jsonl(
    path: Path,
    *,
    label: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            raise PostPromotionReadinessError(
                f"{label} JSONL is invalid at line {line_number}"
            ) from None
        if not isinstance(payload, dict):
            raise PostPromotionReadinessError(
                f"{label} row must be an object"
            )
        rows.append(payload)
    return rows


def _render_jsonl(rows: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for row in rows
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _complete_readiness_counts(
    counts: Mapping[str, int],
) -> dict[str, int]:
    return {
        state: int(counts.get(state, 0))
        for state in _READINESS_STATES
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument(
        "--canonical-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--canonical-products",
        type=Path,
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-matrix-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    report = build_post_promotion_readiness(
        matrix_path=arguments.matrix,
        manifest_path=arguments.manifest,
        facts_path=arguments.facts,
        output_path=arguments.output,
        expected_matrix_sha256=arguments.expected_matrix_sha256,
        expected_manifest_sha256=(
            arguments.expected_manifest_sha256
        ),
        canonical_manifest_path=arguments.canonical_manifest,
        canonical_products_path=arguments.canonical_products,
    )
    summary_bytes = (
        json.dumps(
            asdict(report),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    _atomic_write(arguments.summary, summary_bytes)
    print(summary_bytes.decode("utf-8").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
