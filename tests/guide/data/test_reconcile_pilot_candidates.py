from __future__ import annotations

import json
from pathlib import Path

from tools.guide_data.build_seed_database_candidates import (
    build_seed_database_candidates,
)
from tools.guide_data.reconcile_pilot_candidates import (
    build_pilot_candidates,
    render_pilot_review_matrix,
)


FIXTURES = Path(__file__).parent / "fixtures"
SEED = FIXTURES / "products_copy.sql"
CANONICAL = FIXTURES / "canonical_products.jsonl"
TMALL = FIXTURES / "tmall_saved_page.html"
SOURCE_SHA = __import__("hashlib").sha256(TMALL.read_bytes()).hexdigest()
FORBIDDEN_WRITER_KEYS = {
    "approval",
    "decision",
    "reviewer",
    "signature",
}


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _database_candidates(tmp_path: Path) -> tuple[Path, Path]:
    pending = tmp_path / "db-pending.jsonl"
    quarantine = tmp_path / "db-quarantine.jsonl"
    build_seed_database_candidates(
        seed_dump_path=SEED,
        canonical_products_path=CANONICAL,
        product_ids=(42,),
        output_path=pending,
        quarantine_path=quarantine,
    )
    return pending, quarantine


def _source_manifest(tmp_path: Path, source_name: str) -> Path:
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "pilot-saved-page-sources-v1",
                "sources": [
                    {
                        "item_id": "998532090974",
                        "path": source_name,
                        "product_id": 42,
                        "sha256": SOURCE_SHA,
                        "sku_id": "6153782938028",
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest


def test_matching_database_and_html_values_stay_pending(
    tmp_path: Path,
) -> None:
    database_pending, database_quarantine = _database_candidates(
        tmp_path
    )
    status = tmp_path / "status.jsonl"
    pending = tmp_path / "pending.jsonl"
    quarantine = tmp_path / "quarantine.jsonl"

    result = build_pilot_candidates(
        canonical_products_path=CANONICAL,
        database_pending_path=database_pending,
        database_quarantine_path=database_quarantine,
        saved_page_manifest_path=_source_manifest(
            tmp_path,
            TMALL.name,
        ),
        saved_page_root=FIXTURES,
        product_ids=(42,),
        status_output_path=status,
        pending_output_path=pending,
        quarantine_output_path=quarantine,
    )

    statuses = {
        row["field_key"]: row
        for row in _rows(status)
    }
    assert result.product_count == 1
    assert statuses["product_identity"]["status"] == "known"
    assert statuses["suitable_skin"]["status"] == "pending"
    assert statuses["texture"]["status"] == "pending"
    assert statuses["texture"]["evidence_sources"] == [
        "database",
        "html",
    ]
    assert statuses["ingredients_present"]["status"] == "quarantine"
    assert {
        row["source_class"]
        for row in _rows(pending)
        if row["field_key"] == "texture"
    } == {"structured_official"}


def test_database_html_conflict_is_quarantined(
    tmp_path: Path,
) -> None:
    database_pending, database_quarantine = _database_candidates(
        tmp_path
    )
    conflicting_source = tmp_path / TMALL.name
    conflicting_source.write_text(
        TMALL.read_text(encoding="utf-8").replace(
            '"valueName":"水液"',
            '"valueName":"乳霜"',
        ),
        encoding="utf-8",
    )
    global SOURCE_SHA
    original_sha = SOURCE_SHA
    SOURCE_SHA = __import__("hashlib").sha256(
        conflicting_source.read_bytes()
    ).hexdigest()
    try:
        manifest = _source_manifest(tmp_path, conflicting_source.name)
    finally:
        SOURCE_SHA = original_sha
    status = tmp_path / "status.jsonl"
    pending = tmp_path / "pending.jsonl"
    quarantine = tmp_path / "quarantine.jsonl"

    build_pilot_candidates(
        canonical_products_path=CANONICAL,
        database_pending_path=database_pending,
        database_quarantine_path=database_quarantine,
        saved_page_manifest_path=manifest,
        saved_page_root=tmp_path,
        product_ids=(42,),
        status_output_path=status,
        pending_output_path=pending,
        quarantine_output_path=quarantine,
    )

    texture = next(
        row for row in _rows(status) if row["field_key"] == "texture"
    )
    assert texture["status"] == "quarantine"
    assert texture["quarantine_reasons"] == ["source_conflict"]
    assert not any(
        row["field_key"] == "texture" for row in _rows(pending)
    )


def test_writer_and_matrix_contain_no_approval_or_source_paths(
    tmp_path: Path,
) -> None:
    database_pending, database_quarantine = _database_candidates(
        tmp_path
    )
    status = tmp_path / "status.jsonl"
    pending = tmp_path / "pending.jsonl"
    quarantine = tmp_path / "quarantine.jsonl"
    matrix = tmp_path / "matrix.md"
    build_pilot_candidates(
        canonical_products_path=CANONICAL,
        database_pending_path=database_pending,
        database_quarantine_path=database_quarantine,
        saved_page_manifest_path=_source_manifest(
            tmp_path,
            TMALL.name,
        ),
        saved_page_root=FIXTURES,
        product_ids=(42,),
        status_output_path=status,
        pending_output_path=pending,
        quarantine_output_path=quarantine,
    )
    render_pilot_review_matrix(status, matrix)

    for row in _rows(status) + _rows(pending) + _rows(quarantine):
        assert FORBIDDEN_WRITER_KEYS.isdisjoint(row)
    rendered = matrix.read_text(encoding="utf-8")
    assert FORBIDDEN_WRITER_KEYS.isdisjoint(rendered.casefold().split())
    assert str(tmp_path) not in rendered
    assert str(FIXTURES) not in rendered
    assert "水液" not in rendered
    assert "清爽" not in rendered
