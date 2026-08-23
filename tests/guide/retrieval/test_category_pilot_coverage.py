from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_fact_assets import (
    load_category_fact_assets,
)
from app.guide.retrieval.category_fact_contracts import (
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from tools.guide_data.promote_approved_category_facts import (
    promote_approved_category_facts,
)


ROOT = Path(__file__).resolve().parents[3]
CANONICAL_ROOT = ROOT / "data" / "canonical"
CANONICAL_MANIFEST = CANONICAL_ROOT / "core_products_v1_manifest.json"
CANONICAL_PRODUCTS = CANONICAL_ROOT / "core_products_v1.jsonl"
ASSET_ROOT = ROOT / "data" / "guide_category_facts"
MANIFEST_PATH = ASSET_ROOT / "category_facts_v1_manifest.json"
REPORT_PATH = (
    ROOT
    / "docs"
    / "audits"
    / "category-data-foundation"
    / "pilot_coverage.md"
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
PILOT_IDS = {
    CategoryProfile.SKINCARE: frozenset({38, 91}),
    CategoryProfile.SUNCARE: frozenset({53, 57}),
    CategoryProfile.BASE_MAKEUP: frozenset({79, 80}),
    CategoryProfile.COLOR_MAKEUP: frozenset({86, 114}),
    CategoryProfile.CLEANSER: frozenset({69, 103}),
    CategoryProfile.FRAGRANCE: frozenset({120, 121}),
}
EXPECTED_UNKNOWN_BY_PROFILE = {
    CategoryProfile.SKINCARE: 38,
    CategoryProfile.SUNCARE: 45,
    CategoryProfile.BASE_MAKEUP: 39,
    CategoryProfile.COLOR_MAKEUP: 46,
    CategoryProfile.CLEANSER: 43,
    CategoryProfile.FRAGRANCE: 25,
}
EXPECTED_APPROVED_BY_PROFILE = {
    CategoryProfile.SKINCARE: 6,
    CategoryProfile.SUNCARE: 11,
    CategoryProfile.BASE_MAKEUP: 13,
    CategoryProfile.COLOR_MAKEUP: 8,
    CategoryProfile.CLEANSER: 5,
    CategoryProfile.FRAGRANCE: 11,
}


def _coverage_api():
    try:
        from tools.guide_data.build_category_pilot_coverage import (
            build_category_pilot_coverage,
        )
    except ModuleNotFoundError:
        pytest.fail("category pilot coverage builder is missing")
    return build_category_pilot_coverage


def _canonical_reader() -> CanonicalProductReader:
    return CanonicalProductReader.from_files(
        manifest_path=CANONICAL_MANIFEST,
        products_path=CANONICAL_PRODUCTS,
    )


def _load_assets(
    *,
    manifest_path: Path = MANIFEST_PATH,
    facts_path: Path | None = None,
):
    return load_category_fact_assets(
        manifest_path=manifest_path,
        facts_path=facts_path,
        canonical_reader=_canonical_reader(),
        field_registry=category_field_registry(),
    )


def _sidecar_fields(profile: CategoryProfile) -> tuple[str, ...]:
    return tuple(
        sorted(
            definition.key
            for definition in category_field_registry().for_profile(profile)
            if any(
                policy.source_class is not SourceClass.CANONICAL_CORE
                for policy in definition.source_policies
            )
        )
    )


def _write_empty_queues(root: Path) -> tuple[Path, Path, Path]:
    paths = (
        root / "pending.jsonl",
        root / "quarantine.jsonl",
        root / "decisions.jsonl",
    )
    root.mkdir(parents=True)
    for path in paths:
        path.write_bytes(b"")
    return paths


def _promote_empty_generation(output_dir: Path) -> None:
    queues = _write_empty_queues(output_dir.parent / "review")
    report = promote_approved_category_facts(
        candidates_path=queues[0],
        quarantine_path=queues[1],
        decisions_path=queues[2],
        output_dir=output_dir,
        expected_candidates_sha256=EMPTY_SHA256,
        expected_quarantine_sha256=EMPTY_SHA256,
        expected_decisions_sha256=EMPTY_SHA256,
        canonical_manifest_path=CANONICAL_MANIFEST,
        canonical_products_path=CANONICAL_PRODUCTS,
    )
    assert report.fact_count == 0


def test_production_asset_contains_verified_full_catalog_facts() -> None:
    assert MANIFEST_PATH.is_file(), "production category manifest is missing"
    assets = _load_assets()
    expected_ids = frozenset().union(*PILOT_IDS.values())

    assert assets.pilot_ids == expected_ids
    assert len(expected_ids) == 12
    assert assets.manifest.fact_count == 508
    assert len(assets.facts) == 508
    assert assets.manifest.facts_sha256 != EMPTY_SHA256
    assert assets.manifest.facts_file == (
        f"category_facts_v1.{assets.manifest.facts_sha256}.jsonl"
    )
    facts_bytes = (
        ASSET_ROOT / assets.manifest.facts_file
    ).read_bytes()
    assert hashlib.sha256(facts_bytes).hexdigest() == (
        assets.manifest.facts_sha256
    )
    assert not (ASSET_ROOT / "category_facts_v1.jsonl").exists()
    assert expected_ids.intersection(
        fact.product_id for fact in assets.facts
    ) == expected_ids

    canonical_reader = _canonical_reader()
    for profile, product_ids in PILOT_IDS.items():
        assert len(product_ids) == 2
        assert assets.pilot_ids_for(profile) == product_ids
        for product_id in product_ids:
            category = canonical_reader.get(product_id).fields["category"]
            assert category.resolved_state == "known"
            assert isinstance(category.value, str)
            assert category_profile_for(category.value) is profile

    assert all(
        fact.evidence_status == "approved_fact" and fact.source_refs
        for fact in assets.facts
    )


def test_pilot_coverage_tracks_promoted_and_unknown_fields(
    tmp_path: Path,
) -> None:
    build_coverage = _coverage_api()
    generated_report = tmp_path / "pilot_coverage.md"

    coverage = build_coverage(
        manifest_path=MANIFEST_PATH,
        canonical_manifest_path=CANONICAL_MANIFEST,
        canonical_products_path=CANONICAL_PRODUCTS,
        report_path=generated_report,
    )

    assert len(coverage.rows) == 12
    for row in coverage.rows:
        assert row.product_id in PILOT_IDS[row.category_profile]
        assert row.applicable_fields == _sidecar_fields(
            row.category_profile
        )
        assert set(row.approved_known_fields).isdisjoint(
            row.unknown_fields
        )
        assert (
            set(row.approved_known_fields)
            | set(row.unknown_fields)
        ) == set(row.applicable_fields)
        assert row.conflict_fields == ()
        assert bool(row.source_refs) is bool(
            row.approved_known_fields
        )

    for profile, expected_unknown in EXPECTED_UNKNOWN_BY_PROFILE.items():
        stats = coverage.stats_for(profile)
        assert stats.pilot_count == 2
        assert stats.approved == EXPECTED_APPROVED_BY_PROFILE[profile]
        assert stats.unknown == expected_unknown
        assert stats.conflict == 0

    report_text = generated_report.read_text(encoding="utf-8")
    assert "`approved=54`" in report_text
    assert "`conflict=0`" in report_text
    assert "`336/111`" in report_text
    assert "unrelated to this pilot coverage report" in report_text
    assert "not a pseudo-value" in report_text
    assert "passed both independent verifiers" in report_text
    assert "missing fields remain `unknown`" in report_text
    assert generated_report.read_bytes() == REPORT_PATH.read_bytes()


def test_known_fixture_fields_retain_source_refs(tmp_path: Path) -> None:
    build_coverage = _coverage_api()
    fixture_root = ROOT / "tests" / "fixtures" / "guide" / "category_facts"
    fixture_assets = _load_assets(
        manifest_path=fixture_root / "manifest.json",
        facts_path=fixture_root / "approved.jsonl",
    )

    coverage = build_coverage(
        manifest_path=fixture_root / "manifest.json",
        facts_path=fixture_root / "approved.jsonl",
        canonical_manifest_path=CANONICAL_MANIFEST,
        canonical_products_path=CANONICAL_PRODUCTS,
        report_path=tmp_path / "fixture_coverage.md",
    )

    assert all(fact.source_refs for fact in fixture_assets.facts)
    known_rows = [
        row for row in coverage.rows if row.approved_known_fields
    ]
    assert {
        (row.product_id, row.approved_known_fields)
        for row in known_rows
    } == {
        (38, ("efficacy",)),
        (53, ("spf_pa",)),
    }
    assert all(row.source_refs for row in known_rows)


def test_empty_generation_and_report_rebuilds_are_byte_stable(
    tmp_path: Path,
) -> None:
    build_coverage = _coverage_api()
    snapshots: list[tuple[bytes, bytes, bytes]] = []

    for run in ("first", "second"):
        output_dir = tmp_path / run / "published"
        _promote_empty_generation(output_dir)
        report_path = tmp_path / run / "pilot_coverage.md"
        build_coverage(
            manifest_path=output_dir / MANIFEST_PATH.name,
            canonical_manifest_path=CANONICAL_MANIFEST,
            canonical_products_path=CANONICAL_PRODUCTS,
            report_path=report_path,
        )
        manifest_bytes = (output_dir / MANIFEST_PATH.name).read_bytes()
        facts_name = _load_assets(
            manifest_path=output_dir / MANIFEST_PATH.name
        ).manifest.facts_file
        snapshots.append(
            (
                manifest_bytes,
                (output_dir / facts_name).read_bytes(),
                report_path.read_bytes(),
            )
        )

    assert snapshots[0] == snapshots[1]
    assert snapshots[0][1] == b""
    assert b"`approved=0`" in snapshots[0][2]
    assert snapshots[0][0] != MANIFEST_PATH.read_bytes()
