from __future__ import annotations

from pathlib import Path

import pytest

from tools.guide_data.audit_selection_parent_concepts import (
    build_parent_concept_candidates,
    build_selection_inventory,
    load_parent_concept_decisions,
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


def test_production_selection_inventory_has_locked_totals() -> None:
    inventory = build_selection_inventory(Path.cwd())

    assert inventory.schema_version == "guide-selection-concept-inventory-v1"
    assert inventory.product_count == 100
    assert inventory.selection_fact_count == 2344
    assert inventory.soft_rank_fact_count == 1775
    assert inventory.rank_strength_counts == {"1": 1312, "2": 463}
    assert inventory.non_rank_fact_count == 569
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
        "fact_count": 337,
        "product_count": 49,
        "distinct_value_count": 192,
        "strength_1_count": 318,
        "strength_2_count": 19,
        "attribution_counts": {
            "consumer_report": 33,
            "merchant_claim": 297,
            "verified_fact": 21,
        },
        "values": [],
    }
    assert (
        _field(inventory, "suncare", "texture").fact_count,
        _field(inventory, "suncare", "texture").product_count,
        _field(inventory, "suncare", "texture").distinct_value_count,
    ) == (41, 10, 32)
    assert (
        _field(inventory, "base_makeup", "longevity").fact_count,
        _field(inventory, "base_makeup", "longevity").product_count,
        _field(inventory, "base_makeup", "longevity").distinct_value_count,
    ) == (37, 18, 29)
    assert (
        _field(inventory, "cleanser", "cleansing_power").fact_count,
        _field(inventory, "cleanser", "cleansing_power").product_count,
        _field(inventory, "cleanser", "cleansing_power").distinct_value_count,
    ) == (39, 12, 33)
    assert (
        _field(inventory, "color_makeup", "finish").fact_count,
        _field(inventory, "color_makeup", "finish").product_count,
        _field(inventory, "color_makeup", "finish").distinct_value_count,
    ) == (42, 6, 22)


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

    assert len(candidates) == 103
    assert len({item.candidate_id for item in candidates}) == 103
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
    assert len(first.read_text(encoding="utf-8").splitlines()) == 103


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
        build_selection_inventory(Path.cwd())
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
