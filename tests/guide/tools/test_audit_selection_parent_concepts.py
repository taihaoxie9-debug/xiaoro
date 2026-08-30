from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptReview,
)
from tools.guide_data.audit_selection_parent_concepts import (
    ReviewedConceptPolicy,
    SelectionConceptInventory,
    build_parent_concept_candidates,
    build_review_v2_decisions,
    build_selection_inventory,
    load_parent_concept_decisions,
    load_reviewed_concept_mappings,
    materialize_parent_concept_reviews,
    write_parent_concept_candidates,
    write_parent_concept_reviews,
    write_selection_inventory,
)


def _field(inventory, profile: str, field_key: str):
    return next(
        item
        for item in inventory.fields
        if item.profile == profile and item.field_key == field_key
    )


def _v1_inventory() -> SelectionConceptInventory:
    return SelectionConceptInventory.model_validate_json(
        Path(
            "docs/audits/selection-concepts/inventory_v1.json"
        ).read_text(encoding="utf-8"),
        strict=True,
    )


def _v1_reviews() -> tuple[SelectionConceptReview, ...]:
    return tuple(
        SelectionConceptReview.model_validate_json(line, strict=True)
        for line in Path(
            "docs/audits/selection-concepts/review_v1.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def test_production_selection_inventory_has_locked_totals() -> None:
    inventory = build_selection_inventory(Path.cwd())

    assert inventory.schema_version == "guide-selection-concept-inventory-v1"
    assert inventory.product_count == 101
    assert inventory.selection_fact_count == 2435
    assert inventory.soft_rank_fact_count == 1869
    assert inventory.rank_strength_counts == {"1": 1312, "2": 557}
    assert inventory.non_rank_fact_count == 566
    assert [item.profile for item in inventory.profiles] == [
        "base_makeup",
        "cleanser",
        "color_makeup",
        "fragrance",
        "skincare",
        "suncare",
    ]


def test_inventory_locks_representative_high_coverage_fields() -> None:
    inventory = build_selection_inventory(Path.cwd())

    assert _field(inventory, "skincare", "efficacy").model_dump(
        mode="json"
    ) | {"values": []} == {
        "profile": "skincare",
        "field_key": "efficacy",
        "fact_count": 364,
        "product_count": 49,
        "distinct_value_count": 208,
        "strength_1_count": 319,
        "strength_2_count": 45,
        "attribution_counts": {
            "consumer_report": 33,
            "merchant_claim": 297,
            "verified_fact": 47,
        },
        "values": [],
    }
    assert (
        _field(inventory, "suncare", "texture").fact_count,
        _field(inventory, "suncare", "texture").product_count,
        _field(inventory, "suncare", "texture").distinct_value_count,
    ) == (48, 11, 39)
    assert (
        _field(inventory, "base_makeup", "longevity").fact_count,
        _field(inventory, "base_makeup", "longevity").product_count,
        _field(inventory, "base_makeup", "longevity").distinct_value_count,
    ) == (44, 18, 35)
    assert (
        _field(inventory, "cleanser", "cleansing_power").fact_count,
        _field(inventory, "cleanser", "cleansing_power").product_count,
        _field(inventory, "cleanser", "cleansing_power").distinct_value_count,
    ) == (44, 12, 38)
    assert (
        _field(inventory, "color_makeup", "finish").fact_count,
        _field(inventory, "color_makeup", "finish").product_count,
        _field(inventory, "color_makeup", "finish").distinct_value_count,
    ) == (40, 4, 20)


def test_inventory_preserves_value_coverage_and_evidence_strength() -> None:
    inventory = build_selection_inventory(Path.cwd())
    efficacy = _field(inventory, "skincare", "efficacy")
    soothing_redness = next(
        item for item in efficacy.values
        if item.normalized_value == "舒缓泛红"
    )

    assert soothing_redness.product_ids == [
        32,
        33,
        38,
        39,
        46,
        50,
        62,
        77,
        78,
        91,
        106,
        129,
        131,
    ]
    assert soothing_redness.rank_strengths == [1, 2]
    assert soothing_redness.fact_count >= len(soothing_redness.product_ids)
    assert soothing_redness.source_refs == sorted(
        set(soothing_redness.source_refs)
    )


def test_inventory_materialization_is_byte_stable(
    tmp_path: Path,
) -> None:
    inventory = build_selection_inventory(Path.cwd())
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    write_selection_inventory(inventory, first)
    write_selection_inventory(inventory, second)

    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"\n")


def test_parent_concept_candidates_cover_repeated_core_values() -> None:
    inventory = build_selection_inventory(Path.cwd())

    candidates = build_parent_concept_candidates(inventory)

    assert len(candidates) == 113
    assert len({item.candidate_id for item in candidates}) == 113
    assert [
        (
            item.profile.value,
            item.field_key,
            item.normalized_value,
        )
        for item in candidates
    ] == sorted(
        (
            item.profile.value,
            item.field_key,
            item.normalized_value,
        )
        for item in candidates
    )
    assert any(
        item.profile.value == "skincare"
        and item.field_key == "efficacy"
        and item.normalized_value == "舒缓泛红"
        for item in candidates
    )
    assert not any(
        item.field_key == "mechanism"
        or len(item.product_ids) < 2
        for item in candidates
    )


def test_terminal_map_reviews_all_enter_parent_concept_candidates() -> None:
    inventory = build_selection_inventory(Path.cwd())
    review_paths = tuple(sorted(
        Path(
            "docs/audits/smzdm-data/reviewed-products"
        ).glob("product-*-v1.json")
    ))

    mappings = load_reviewed_concept_mappings(review_paths)
    candidates = build_parent_concept_candidates(
        inventory,
        reviewed_mappings=mappings,
    )
    by_value = {
        (
            item.profile.value,
            item.field_key,
            item.normalized_value.casefold(),
        ): item
        for item in candidates
    }

    assert len(review_paths) == 79
    assert len(mappings) == 106
    assert all(
        mapping.product_id
        in by_value[(
            mapping.profile.value,
            mapping.field_key,
            mapping.normalized_value.casefold(),
        )].product_ids
        for mapping in mappings
    )
    assert any(
        len(item.product_ids) == 1
        for item in candidates
    )


def test_v2_decisions_are_only_prior_reviews_or_terminal_maps() -> None:
    inventory = build_selection_inventory(Path.cwd())
    mappings = load_reviewed_concept_mappings(tuple(sorted(
        Path(
            "docs/audits/smzdm-data/reviewed-products"
        ).glob("product-*-v1.json")
    )))
    candidates = build_parent_concept_candidates(
        inventory,
        reviewed_mappings=mappings,
    )
    policies = (
        ReviewedConceptPolicy(
            concept_id="texture.rich_cream",
            stance="supports",
            comparability="binary",
            order_value=None,
            rationale="丰润乳霜是普通质地比较方向。",
        ),
        ReviewedConceptPolicy(
            concept_id="texture.silky",
            stance="supports",
            comparability="binary",
            order_value=None,
            rationale="丝滑肤感是普通质地比较方向。",
        ),
    )

    decisions = build_review_v2_decisions(
        candidates=candidates,
        prior_reviews=_v1_reviews(),
        reviewed_mappings=mappings,
        new_concept_policies=policies,
    )

    assert len(decisions) == 191
    assert sum(item.decision == "map" for item in decisions) == 188
    assert sum(
        item.decision == "leave_free"
        for item in decisions
    ) == 3
    assert {
        item.concept_id
        for item in decisions
        if item.concept_id in {
            "texture.rich_cream",
            "texture.silky",
        }
    } == {"texture.rich_cream", "texture.silky"}


def test_review_v2_cli_builds_hash_locked_non_promoting_packet(
    tmp_path: Path,
) -> None:
    output = tmp_path / "review-v2"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.audit_selection_parent_concepts",
            "--repo-root",
            str(Path.cwd()),
            "--review-dir",
            str(
                Path.cwd()
                / "docs/audits/smzdm-data/reviewed-products"
            ),
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    manifest = json.loads(
        (output / "manifest.json").read_text(encoding="utf-8")
    )

    assert report["candidate_count"] == 191
    assert report["reviewed_mapping_count"] == 106
    assert manifest["candidate_count"] == 191
    assert manifest["reviewed_mapping_count"] == 106
    assert (output / "inventory.json").is_file()
    assert (output / "candidates.jsonl").is_file()
    assert (output / "reviewed_mappings.jsonl").is_file()
    assert not (output / "reviews.jsonl").exists()
    assert not (output / "review_decisions.jsonl").exists()


def test_review_v2_assets_are_complete_and_hash_locked() -> None:
    root = Path("docs/audits/selection-concepts/review-v2")
    manifest = json.loads(
        (root / "manifest.json").read_text(encoding="utf-8")
    )
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    actual_manifest_sha256 = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    for file_key in (
        "inventory",
        "candidates",
        "reviewed_mappings",
        "new_concept_policies",
        "review_decisions",
        "reviews",
    ):
        path = root / manifest[f"{file_key}_file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == (
            manifest[f"{file_key}_sha256"]
        )

    candidates = tuple(
        SelectionConceptReview.model_validate_json(
            line,
            strict=True,
        )
        for line in (root / "reviews.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    )
    decisions = load_parent_concept_decisions(
        root / "review_decisions.jsonl"
    )
    reviewed_mappings = load_reviewed_concept_mappings(
        tuple(sorted(
            Path(
                "docs/audits/smzdm-data/reviewed-products"
            ).glob("product-*-v1.json")
        ))
    )
    candidate_rows = build_parent_concept_candidates(
        build_selection_inventory(Path.cwd()),
        reviewed_mappings=reviewed_mappings,
    )
    candidate_by_key = {
        (
            item.profile.value,
            item.field_key,
            item.normalized_value.casefold(),
        ): item
        for item in candidate_rows
    }
    decision_by_id = {
        item.candidate_id: item
        for item in decisions
    }

    assert manifest["manifest_sha256"] == actual_manifest_sha256
    assert manifest["review_status"] == "human_review_complete"
    assert manifest["reviewer"] == "main-agent-smzdm-review"
    assert manifest["decision_counts"] == {
        "leave_free": 3,
        "map": 188,
    }
    assert manifest["concept_count"] == 50
    assert candidates == materialize_parent_concept_reviews(
        candidate_rows,
        decisions,
    )
    assert all(
        decision_by_id[
            candidate_by_key[(
                mapping.profile.value,
                mapping.field_key,
                mapping.normalized_value.casefold(),
            )].candidate_id
        ].concept_id
        == mapping.concept_id
        for mapping in reviewed_mappings
    )


def test_candidate_jsonl_materialization_is_byte_stable(
    tmp_path: Path,
) -> None:
    candidates = build_parent_concept_candidates(
        build_selection_inventory(Path.cwd())
    )
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"

    write_parent_concept_candidates(candidates, first)
    write_parent_concept_candidates(candidates, second)

    assert first.read_bytes() == second.read_bytes()
    assert len(first.read_text(encoding="utf-8").splitlines()) == 113


def test_review_materializer_requires_one_known_decision_per_candidate(
    tmp_path: Path,
) -> None:
    candidates = build_parent_concept_candidates(
        build_selection_inventory(Path.cwd())
    )[:2]
    decision_path = tmp_path / "decisions.jsonl"
    decision_path.write_text(
        (
            '{"candidate_id":"'
            + candidates[0].candidate_id
            + '","comparability":"binary","concept_id":"'
            + candidates[0].field_key
            + '.covered","decision":"map","order_value":null,'
            '"rationale":"跨商品稳定决策方向。","stance":"supports"}\n'
        ),
        encoding="utf-8",
    )

    decisions = load_parent_concept_decisions(decision_path)

    with pytest.raises(ValueError, match="missing"):
        materialize_parent_concept_reviews(candidates, decisions)

    decision_path.write_text(
        decision_path.read_text(encoding="utf-8")
        + (
            '{"candidate_id":"sc_'
            + ("0" * 64)
            + '","comparability":"none","concept_id":null,'
            '"decision":"leave_free","order_value":null,'
            '"rationale":"未知候选不能进入审核。",'
            '"stance":"not_comparable"}\n'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown"):
        materialize_parent_concept_reviews(
            candidates,
            load_parent_concept_decisions(decision_path),
        )


def test_real_review_catalog_is_complete_and_byte_stable(
    tmp_path: Path,
) -> None:
    candidates = build_parent_concept_candidates(
        _v1_inventory()
    )
    reviews = materialize_parent_concept_reviews(
        candidates,
        load_parent_concept_decisions(
            Path(
                "docs/audits/selection-concepts/"
                "review_decisions_v1.jsonl"
            )
        ),
    )
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"

    write_parent_concept_reviews(reviews, first)
    write_parent_concept_reviews(reviews, second)

    assert len(reviews) == 103
    assert sum(item.decision == "map" for item in reviews) == 99
    assert sum(item.decision == "leave_free" for item in reviews) == 4
    assert first.read_bytes() == second.read_bytes()
