"""Independently verify full-catalog source and policy evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Literal

from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import category_profile_for
from tools.guide_data.build_full_catalog_closure import (
    classify_parameter_group,
    promotion_candidate_row,
)
from tools.guide_data.extract_saved_page_evidence import (
    extract_saved_page_evidence,
)
from tools.guide_data.inventory_local_sources import (
    atomic_write_private,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFETY_FIELDS = frozenset(
    {"ingredients_present", "safety", "verified_absences"}
)


@dataclass(frozen=True, slots=True)
class VerifierReport:
    verifier_id: Literal["verifier_a_source", "verifier_b_policy"]
    status: Literal["PASS", "FAIL"]
    source_commit: str
    candidate_sha256: str
    passed_candidate_ids: tuple[str, ...]
    failures: tuple[dict[str, str], ...]
    evidence_sha256: dict[str, str]


def verify_source_candidates(
    *,
    candidates_path: str | Path,
    classifications_path: str | Path,
    page_manifest_path: str | Path,
    inventory_path: str | Path,
    downloads_root: str | Path,
    expected_candidates_sha256: str,
    expected_classifications_sha256: str,
    expected_page_manifest_sha256: str,
    expected_inventory_sha256: str,
    source_commit: str,
) -> VerifierReport:
    _validate_source_commit(source_commit)
    candidates = _load_locked_jsonl(
        Path(candidates_path),
        expected_candidates_sha256,
        label="candidate",
    )
    classifications = _load_locked_jsonl(
        Path(classifications_path),
        expected_classifications_sha256,
        label="classification",
    )
    page_manifest = _load_locked_jsonl(
        Path(page_manifest_path),
        expected_page_manifest_sha256,
        label="page manifest",
    )
    inventory = _load_locked_jsonl(
        Path(inventory_path),
        expected_inventory_sha256,
        label="inventory",
    )
    classification_by_locator = {
        row.get("source_locator"): row
        for row in classifications
        if row.get("disposition") == "pending"
    }
    parsed_sources = {
        row.get("source_sha256")
        for row in page_manifest
        if row.get("parse_status") == "parsed"
    }
    inventory_by_sha = {
        row.get("sha256"): row
        for row in inventory
        if (
            row.get("content_type") == "html"
            and isinstance(row.get("relative_name"), str)
            and "/" not in str(row["relative_name"])
            and "\\" not in str(row["relative_name"])
        )
    }
    passed: list[str] = []
    failures: list[dict[str, str]] = []
    page_cache = {}
    for candidate in candidates:
        candidate_id = _candidate_id(candidate)
        reason = _verify_source_candidate(
            candidate,
            classification_by_locator=classification_by_locator,
            parsed_sources=parsed_sources,
            inventory_by_sha=inventory_by_sha,
            downloads_root=Path(downloads_root),
            page_cache=page_cache,
        )
        if reason is None:
            passed.append(candidate_id)
        else:
            failures.append(
                {"candidate_id": candidate_id, "reason": reason}
            )
    return _report(
        verifier_id="verifier_a_source",
        source_commit=source_commit,
        candidate_sha256=expected_candidates_sha256,
        candidates=candidates,
        passed=passed,
        failures=failures,
        evidence_sha256={
            "classifications": expected_classifications_sha256,
            "inventory": expected_inventory_sha256,
            "page_manifest": expected_page_manifest_sha256,
        },
    )


def _verify_source_candidate(
    candidate: dict[str, object],
    *,
    classification_by_locator: dict[object, dict[str, object]],
    parsed_sources: set[object],
    inventory_by_sha: dict[object, dict[str, object]],
    downloads_root: Path,
    page_cache: dict[str, object],
) -> str | None:
    locator = candidate.get("source_locator")
    classification = classification_by_locator.get(locator)
    if classification is None:
        return "classification_missing"
    source_sha256 = candidate.get("source_sha256")
    if source_sha256 not in parsed_sources:
        return "source_not_in_parsed_manifest"
    inventory_row = inventory_by_sha.get(source_sha256)
    if inventory_row is None:
        return "source_not_in_inventory"
    relative_name = inventory_row["relative_name"]
    assert isinstance(relative_name, str)
    page = page_cache.get(str(source_sha256))
    if page is None:
        page = extract_saved_page_evidence(
            downloads_root / relative_name
        )
        page_cache[str(source_sha256)] = page
    if page.source_sha256 != source_sha256:
        return "source_sha256_mismatch"
    if page.item_id != classification.get("item_id"):
        return "item_id_mismatch"
    if list(page.sku_ids) != classification.get("sku_ids"):
        return "sku_ids_mismatch"
    parameter_name = classification.get("parameter_name")
    if (
        not isinstance(parameter_name, str)
        or parameter_name not in page.parameters
    ):
        return "parameter_missing"
    ordinal_by_name = {
        name: index
        for index, name in enumerate(
            sorted(page.parameters),
            start=1,
        )
    }
    profile_value = classification.get("category_profile")
    try:
        from app.guide.retrieval.category_profiles import CategoryProfile

        profile = CategoryProfile(profile_value)
    except (TypeError, ValueError):
        return "category_profile_invalid"
    replayed = classify_parameter_group(
        product_id=classification.get("product_id"),
        category_profile=profile,
        binding_status=classification.get("binding_status"),
        source_sha256=page.source_sha256,
        item_id=page.item_id,
        sku_ids=page.sku_ids,
        parameter_name=parameter_name,
        raw_values=page.parameters[parameter_name],
        ordinal=ordinal_by_name[parameter_name],
    )
    if (
        replayed.raw_value_sha256
        != classification.get("raw_value_sha256")
    ):
        return "raw_value_sha256_mismatch"
    if (
        replayed.normalized_value_sha256
        != classification.get("normalized_value_sha256")
    ):
        return "normalized_value_sha256_mismatch"
    if replayed.source_locator != classification.get("source_locator"):
        return "source_locator_mismatch"
    if promotion_candidate_row(replayed) != candidate:
        return "candidate_replay_mismatch"
    return None


def verify_policy_candidates(
    *,
    candidates_path: str | Path,
    matrix_path: str | Path,
    canonical_products_path: str | Path,
    expected_candidates_sha256: str,
    expected_matrix_sha256: str,
    source_commit: str,
) -> VerifierReport:
    _validate_source_commit(source_commit)
    candidates = _load_locked_jsonl(
        Path(candidates_path),
        expected_candidates_sha256,
        label="candidate",
    )
    matrix = _load_locked_jsonl(
        Path(matrix_path),
        expected_matrix_sha256,
        label="matrix",
    )
    canonical_content = Path(canonical_products_path).read_bytes()
    canonical_sha256 = _sha256(canonical_content)
    canonical_rows = _parse_jsonl(canonical_content, label="canonical")
    canonical = {
        row.get("product_id"): row
        for row in canonical_rows
    }
    matrix_by_product = {
        row.get("product_id"): row
        for row in matrix
    }
    seen_product_fields: set[tuple[int, str]] = set()
    passed: list[str] = []
    failures: list[dict[str, str]] = []
    for candidate in candidates:
        candidate_id = _candidate_id(candidate)
        reason = _verify_policy_candidate(
            candidate,
            canonical=canonical,
            matrix_by_product=matrix_by_product,
            seen_product_fields=seen_product_fields,
        )
        if reason is None:
            passed.append(candidate_id)
        else:
            failures.append(
                {"candidate_id": candidate_id, "reason": reason}
            )
    return _report(
        verifier_id="verifier_b_policy",
        source_commit=source_commit,
        candidate_sha256=expected_candidates_sha256,
        candidates=candidates,
        passed=passed,
        failures=failures,
        evidence_sha256={
            "canonical_products": canonical_sha256,
            "product_matrix": expected_matrix_sha256,
        },
    )


def _verify_policy_candidate(
    candidate: dict[str, object],
    *,
    canonical: dict[object, dict[str, object]],
    matrix_by_product: dict[object, dict[str, object]],
    seen_product_fields: set[tuple[int, str]],
) -> str | None:
    if _candidate_content_digest(candidate) != candidate.get(
        "candidate_id"
    ):
        return "candidate_content_address_mismatch"
    product_id = candidate.get("product_id")
    field_key = candidate.get("field_key")
    if (
        isinstance(product_id, bool)
        or not isinstance(product_id, int)
        or not isinstance(field_key, str)
    ):
        return "candidate_identity_invalid"
    product_field = (product_id, field_key)
    if product_field in seen_product_fields:
        return "duplicate_product_field"
    seen_product_fields.add(product_field)
    if field_key in _SAFETY_FIELDS:
        return "safety_field_forbidden"
    product = canonical.get(product_id)
    if product is None:
        return "canonical_product_missing"
    fields = product.get("fields")
    if not isinstance(fields, dict):
        return "canonical_fields_invalid"
    category = fields.get("category")
    category_value = (
        category.get("value")
        if isinstance(category, dict)
        else None
    )
    if not isinstance(category_value, str):
        return "canonical_category_invalid"
    try:
        profile = category_profile_for(category_value)
    except KeyError:
        return "canonical_category_unmapped"
    if candidate.get("category_profile") != profile.value:
        return "category_profile_mismatch"
    definition = next(
        (
            item
            for item in category_field_registry().for_profile(profile)
            if item.key == field_key
        ),
        None,
    )
    if definition is None:
        return "field_not_applicable"
    canonical_field = fields.get(field_key)
    canonical_state = (
        canonical_field.get("resolved_state")
        if isinstance(canonical_field, dict)
        else None
    )
    if canonical_state in {"known", "conflict"}:
        return "canonical_field_not_open"
    if candidate.get("source_class") != SourceClass.MERCHANT_PARAMETER.value:
        return "source_class_mismatch"
    policy = next(
        (
            item
            for item in definition.source_policies
            if item.source_class is SourceClass.MERCHANT_PARAMETER
        ),
        None,
    )
    if policy is None or "hard_filter" in policy.capabilities:
        return "merchant_policy_invalid"
    value = candidate.get("normalized_value")
    if definition.value_type == "string_list" and isinstance(value, list):
        value = tuple(value)
    try:
        AuthorizedCategoryFact(
            category_profile=profile,
            field_key=field_key,
            value=value,
            resolved_state="known",
            source_classes=(SourceClass.MERCHANT_PARAMETER,),
            source_refs=(str(candidate.get("source_locator")),),
            capabilities=policy.capabilities,
        )
    except Exception:
        return "authorized_fact_validation_failed"
    matrix = matrix_by_product.get(product_id)
    if matrix is None or matrix.get("binding_status") != "exact_item":
        return "matrix_binding_not_exact"
    field_states = matrix.get("field_states")
    if (
        not isinstance(field_states, dict)
        or field_states.get(field_key) != "pending"
    ):
        return "matrix_field_not_pending"
    return None


def build_joint_decisions(
    *,
    verifier_a: VerifierReport,
    verifier_b: VerifierReport,
    candidates_path: str | Path,
    expected_candidates_sha256: str,
    reviewed_at: str,
) -> bytes:
    if (
        verifier_a.verifier_id != "verifier_a_source"
        or verifier_b.verifier_id != "verifier_b_policy"
        or verifier_a.status != "PASS"
        or verifier_b.status != "PASS"
        or verifier_a.source_commit != verifier_b.source_commit
        or verifier_a.candidate_sha256 != expected_candidates_sha256
        or verifier_b.candidate_sha256 != expected_candidates_sha256
    ):
        raise ValueError("verifier consensus is not valid")
    try:
        timestamp = datetime.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise ValueError("reviewed_at is invalid") from exc
    if timestamp.utcoffset() is None:
        raise ValueError("reviewed_at must be timezone-aware")
    candidates = _load_locked_jsonl(
        Path(candidates_path),
        expected_candidates_sha256,
        label="candidate",
    )
    candidate_ids = {
        _candidate_id(candidate)
        for candidate in candidates
    }
    common_pass = (
        set(verifier_a.passed_candidate_ids)
        & set(verifier_b.passed_candidate_ids)
        & candidate_ids
    )
    if not common_pass:
        raise ValueError("verifier consensus has no common PASS")
    decisions = [
        {
            "candidate_id": candidate_id,
            "decision": "approved_fact",
            "reason": (
                "source binding and category policy independently verified"
            ),
            "reviewed_at": reviewed_at,
            "reviewer": "task19-verifier-consensus",
        }
        for candidate_id in sorted(common_pass)
    ]
    return _render_jsonl(decisions)


def write_verifier_report(
    report: VerifierReport,
    output_path: str | Path,
) -> str:
    payload = {
        "candidate_sha256": report.candidate_sha256,
        "evidence_sha256": report.evidence_sha256,
        "failures": list(report.failures),
        "passed_candidate_ids": list(report.passed_candidate_ids),
        "source_commit": report.source_commit,
        "status": report.status,
        "verifier_id": report.verifier_id,
    }
    content = _canonical_json_bytes(payload) + b"\n"
    atomic_write_private(Path(output_path), content)
    return _sha256(content)


def _report(
    *,
    verifier_id: Literal["verifier_a_source", "verifier_b_policy"],
    source_commit: str,
    candidate_sha256: str,
    candidates: list[dict[str, object]],
    passed: list[str],
    failures: list[dict[str, str]],
    evidence_sha256: dict[str, str],
) -> VerifierReport:
    candidate_ids = {_candidate_id(item) for item in candidates}
    status: Literal["PASS", "FAIL"] = (
        "PASS"
        if (
            candidate_ids
            and not failures
            and set(passed) == candidate_ids
        )
        else "FAIL"
    )
    return VerifierReport(
        verifier_id=verifier_id,
        status=status,
        source_commit=source_commit,
        candidate_sha256=candidate_sha256,
        passed_candidate_ids=tuple(sorted(passed)),
        failures=tuple(failures),
        evidence_sha256=dict(sorted(evidence_sha256.items())),
    )


def _load_locked_jsonl(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
) -> list[dict[str, object]]:
    if _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError(f"{label} expected SHA-256 is invalid")
    content = path.read_bytes()
    if _sha256(content) != expected_sha256:
        raise ValueError(f"{label} SHA-256 mismatch")
    return _parse_jsonl(content, label=label)


def _parse_jsonl(
    content: bytes,
    *,
    label: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{label} line {line_number} is invalid"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(f"{label} row must be an object")
        rows.append(row)
    return rows


def _candidate_id(candidate: dict[str, object]) -> str:
    candidate_id = candidate.get("candidate_id")
    return str(candidate_id)


def _candidate_content_digest(candidate: dict[str, object]) -> str:
    return _sha256(
        (
            f"{candidate.get('product_id')}\0"
            f"{candidate.get('category_profile')}\0"
            f"{candidate.get('field_key')}\0"
            f"{candidate.get('source_sha256')}\0"
            f"{candidate.get('source_locator')}\0"
            f"{_canonical_json_text(candidate.get('normalized_value'))}"
        ).encode("utf-8")
    )


def _render_jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join(
        _canonical_json_bytes(row) + b"\n"
        for row in rows
    )


def _canonical_json_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_json_bytes(value: object) -> bytes:
    return _canonical_json_text(value).encode("utf-8")


def _validate_source_commit(value: str) -> None:
    if _COMMIT.fullmatch(value) is None:
        raise ValueError("source_commit must be a full Git SHA")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


__all__ = [
    "VerifierReport",
    "build_joint_decisions",
    "verify_policy_candidates",
    "verify_source_candidates",
    "write_verifier_report",
]
