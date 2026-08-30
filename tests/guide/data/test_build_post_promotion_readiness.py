from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

import pytest

from app.guide.retrieval.category_fact_assets import (
    ApprovedCategoryFact,
    PILOT_BINDINGS,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from tools.guide_data.build_post_promotion_readiness import (
    PostPromotionReadinessError,
    build_post_promotion_readiness,
    derive_product_readiness,
)

ROOT = Path(__file__).resolve().parents[3]
CANONICAL_ROOT = ROOT / "data" / "canonical"
CANONICAL_MANIFEST = CANONICAL_ROOT / "core_products_v1_manifest.json"
CANONICAL_PRODUCTS = CANONICAL_ROOT / "core_products_v1.jsonl"


def _field_states(
    profile: CategoryProfile,
) -> dict[str, str]:
    states = {
        definition.key: (
            "unknown"
            if profile in definition.profiles
            else "not_applicable"
        )
        for definition in category_field_registry().definitions
    }
    states.update(
        {
            "product_identity": "known",
            "brand": "known",
            "category": "known",
            "price": "known",
        }
    )
    return states


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> str:
    payload = b"".join(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for row in rows
    )
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_fact_asset(
    root: Path,
    *,
    product_id: int,
    profile: CategoryProfile,
    field_key: str,
    value: object,
    forged_fact_id: bool = False,
) -> tuple[Path, Path, str]:
    source_sha256 = "b" * 64
    unsigned = {
        "category_profile": profile.value,
        "evidence_status": "approved_fact",
        "field_key": field_key,
        "product_id": product_id,
        "reviewed_at": datetime.fromisoformat(
            "2026-08-14T04:00:00+08:00"
        ),
        "reviewer": "verifier-consensus",
        "source_class": "merchant_parameter",
        "source_refs": [
            "urn:xiaoro:category-fact-source:sha256:"
            f"{source_sha256}:{'c' * 64}"
        ],
        "source_sha256": source_sha256,
        "value": value,
    }
    provisional = ApprovedCategoryFact.model_validate(
        {"fact_id": "0" * 64, **unsigned}
    )
    normalized = provisional.model_dump(
        mode="json",
        exclude={"fact_id"},
        exclude_none=True,
    )
    fact_id = hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    fact = {"fact_id": ("a" * 64 if forged_fact_id else fact_id), **normalized}
    facts_bytes = (
        json.dumps(
            fact,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    facts_sha256 = hashlib.sha256(facts_bytes).hexdigest()
    facts_name = f"category_facts_v1.{facts_sha256}.jsonl"
    facts_path = root / facts_name
    facts_path.write_bytes(facts_bytes)
    manifest_unsigned = {
        "asset_id": "guide-category-facts-v1",
        "asset_version": (
            "approved-category-facts-v1:sha256:"
            f"{facts_sha256}"
        ),
        "fact_count": 1,
        "facts_file": facts_name,
        "facts_sha256": facts_sha256,
        "pilot_bindings": [
            binding.model_dump(mode="json")
            for binding in PILOT_BINDINGS
        ],
        "schema_version": "approved-category-facts-v1",
    }
    manifest_sha256 = hashlib.sha256(
        json.dumps(
            manifest_unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    manifest_path = root / "category_facts_v1_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                **manifest_unsigned,
                "manifest_sha256": manifest_sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path, facts_path, manifest_sha256


def test_readiness_uses_six_explicit_capability_states() -> None:
    profile = CategoryProfile.SKINCARE
    base = _field_states(profile)

    blocked = dict(base)
    blocked["brand"] = "unknown"
    assert derive_product_readiness(
        binding_status="exact_item",
        category_profile=profile,
        field_states=blocked,
    ) == "BLOCKED"

    assert derive_product_readiness(
        binding_status="alternate_equivalent",
        category_profile=profile,
        field_states=base,
    ) == "IDENTITY_READY"
    assert derive_product_readiness(
        binding_status="exact_item",
        category_profile=profile,
        field_states=base,
    ) == "RECOMMEND_READY"

    comparable = dict(base)
    comparable["texture"] = "known"
    assert derive_product_readiness(
        binding_status="exact_item",
        category_profile=profile,
        field_states=comparable,
    ) == "COMPARE_READY"

    suitable = dict(base)
    suitable.update(
        {
            "suitable_skin": "known",
            "safety": "known",
            "ingredients_present": "known",
        }
    )
    assert derive_product_readiness(
        binding_status="exact_item",
        category_profile=profile,
        field_states=suitable,
    ) == "SUITABILITY_READY"

    complete = {
        key: ("known" if value != "not_applicable" else value)
        for key, value in base.items()
    }
    assert derive_product_readiness(
        binding_status="exact_item",
        category_profile=profile,
        field_states=complete,
    ) == "FULL_READY"


def test_build_applies_promoted_facts_and_reports_real_improvement(
    tmp_path: Path,
) -> None:
    profile = CategoryProfile.SKINCARE
    states = _field_states(profile)
    states["texture"] = "pending"
    matrix_path = tmp_path / "matrix.jsonl"
    matrix_sha = _write_jsonl(
        matrix_path,
        [
            {
                "binding_status": "exact_item",
                "category_profile": profile.value,
                "field_states": states,
                "product_id": 41,
                "readiness": "ready",
                "state_counts": {
                    "known": 4,
                    "pending": 1,
                    "quarantine": 0,
                    "unknown": sum(
                        value == "unknown"
                        for value in states.values()
                    ),
                    "not_applicable": sum(
                        value == "not_applicable"
                        for value in states.values()
                    ),
                },
            }
        ],
    )
    manifest_path, facts_path, manifest_sha = _write_fact_asset(
        tmp_path,
        product_id=41,
        profile=profile,
        field_key="texture",
        value=["轻薄"],
    )
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"

    first_report = build_post_promotion_readiness(
        matrix_path=matrix_path,
        manifest_path=manifest_path,
        facts_path=facts_path,
        output_path=first,
        expected_matrix_sha256=matrix_sha,
        expected_manifest_sha256=manifest_sha,
        canonical_manifest_path=CANONICAL_MANIFEST,
        canonical_products_path=CANONICAL_PRODUCTS,
    )
    second_report = build_post_promotion_readiness(
        matrix_path=matrix_path,
        manifest_path=manifest_path,
        facts_path=facts_path,
        output_path=second,
        expected_matrix_sha256=matrix_sha,
        expected_manifest_sha256=manifest_sha,
        canonical_manifest_path=CANONICAL_MANIFEST,
        canonical_products_path=CANONICAL_PRODUCTS,
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_report == second_report
    assert first_report.product_count == 1
    assert first_report.promoted_fact_count == 1
    assert first_report.known_delta == 1
    assert first_report.pending_delta == -1
    assert first_report.readiness_transition_count == 1
    row = json.loads(first.read_text(encoding="utf-8"))
    assert row["baseline_readiness"] == "RECOMMEND_READY"
    assert row["readiness"] == "COMPARE_READY"
    assert row["field_states"]["texture"] == "known"


def test_build_rejects_promoted_fact_profile_mismatch(
    tmp_path: Path,
) -> None:
    matrix_path = tmp_path / "matrix.jsonl"
    matrix_sha = _write_jsonl(
        matrix_path,
        [
            {
                "binding_status": "exact_item",
                "category_profile": "skincare",
                "field_states": _field_states(CategoryProfile.SKINCARE),
                "product_id": 41,
                "readiness": "ready",
                "state_counts": {},
            }
        ],
    )
    manifest_path, facts_path, manifest_sha = _write_fact_asset(
        tmp_path,
        product_id=41,
        profile=CategoryProfile.SUNCARE,
        field_key="texture",
        value=["轻薄"],
    )

    with pytest.raises(
        PostPromotionReadinessError,
        match="profile mismatch",
    ):
        build_post_promotion_readiness(
            matrix_path=matrix_path,
            manifest_path=manifest_path,
            facts_path=facts_path,
            output_path=tmp_path / "output.jsonl",
            expected_matrix_sha256=matrix_sha,
            expected_manifest_sha256=manifest_sha,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_products_path=CANONICAL_PRODUCTS,
        )


def test_build_rejects_self_consistent_asset_with_forged_fact_id(
    tmp_path: Path,
) -> None:
    states = _field_states(CategoryProfile.SKINCARE)
    states["texture"] = "pending"
    matrix_path = tmp_path / "matrix.jsonl"
    matrix_sha = _write_jsonl(
        matrix_path,
        [
            {
                "binding_status": "exact_item",
                "category_profile": "skincare",
                "field_states": states,
                "product_id": 41,
                "readiness": "ready",
                "state_counts": {},
            }
        ],
    )
    manifest_path, facts_path, manifest_sha = _write_fact_asset(
        tmp_path,
        product_id=41,
        profile=CategoryProfile.SKINCARE,
        field_key="texture",
        value=["轻薄"],
        forged_fact_id=True,
    )

    with pytest.raises(
        PostPromotionReadinessError,
        match="content address",
    ):
        build_post_promotion_readiness(
            matrix_path=matrix_path,
            manifest_path=manifest_path,
            facts_path=facts_path,
            output_path=tmp_path / "output.jsonl",
            expected_matrix_sha256=matrix_sha,
            expected_manifest_sha256=manifest_sha,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_products_path=CANONICAL_PRODUCTS,
        )
