from __future__ import annotations

import json
from pathlib import Path

from tools.guide_data.build_seed_database_candidates import (
    build_seed_database_candidates,
)
from tools.guide_data.promote_approved_category_facts import (
    _PendingCandidate,
)


FIXTURES = Path(__file__).parent / "fixtures"
SEED = FIXTURES / "products_copy.sql"
CANONICAL = FIXTURES / "canonical_products.jsonl"
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


def test_structured_database_fields_become_typed_candidates(
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / "pending.jsonl"
    quarantine_path = tmp_path / "quarantine.jsonl"

    result = build_seed_database_candidates(
        seed_dump_path=SEED,
        canonical_products_path=CANONICAL,
        product_ids=(42,),
        output_path=pending_path,
        quarantine_path=quarantine_path,
    )

    pending = _rows(pending_path)
    assert result.pending_count == 2
    assert {row["field_key"] for row in pending} == {
        "suitable_skin",
        "texture",
    }
    assert all(
        row["source_class"] == "structured_official"
        and row["status"] == "pending"
        and str(row["source_locator"]).startswith(
            "urn:xiaoro:seed-dump:sha256:"
        )
        for row in pending
    )
    for row in pending:
        _PendingCandidate.model_validate(row)


def test_marketing_qa_and_wrong_profile_are_quarantined(
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / "pending.jsonl"
    quarantine_path = tmp_path / "quarantine.jsonl"

    build_seed_database_candidates(
        seed_dump_path=SEED,
        canonical_products_path=CANONICAL,
        product_ids=(42,),
        output_path=pending_path,
        quarantine_path=quarantine_path,
    )

    reasons = {
        reason
        for row in _rows(quarantine_path)
        for reason in row["quarantine_reasons"]
    }
    assert reasons >= {
        "consumer_qa",
        "field_not_applicable",
        "marketing_claim",
    }


def test_candidate_writer_emits_no_review_or_promotion_metadata(
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / "pending.jsonl"
    quarantine_path = tmp_path / "quarantine.jsonl"

    build_seed_database_candidates(
        seed_dump_path=SEED,
        canonical_products_path=CANONICAL,
        product_ids=(42, 49),
        output_path=pending_path,
        quarantine_path=quarantine_path,
    )

    for row in _rows(pending_path) + _rows(quarantine_path):
        assert FORBIDDEN_WRITER_KEYS.isdisjoint(row)
    serialized = pending_path.read_text(
        encoding="utf-8"
    ) + quarantine_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert "opaque source tag" not in serialized


def test_canonical_core_override_is_not_emitted_as_a_candidate(
    tmp_path: Path,
) -> None:
    canonical_path = tmp_path / "canonical.jsonl"
    canonical = json.loads(
        CANONICAL.read_text(encoding="utf-8").splitlines()[0]
    )
    canonical["fields"]["brand"]["value"] = "冲突品牌"
    canonical_path.write_text(
        json.dumps(canonical, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pending_path = tmp_path / "pending.jsonl"
    quarantine_path = tmp_path / "quarantine.jsonl"

    build_seed_database_candidates(
        seed_dump_path=SEED,
        canonical_products_path=canonical_path,
        product_ids=(42,),
        output_path=pending_path,
        quarantine_path=quarantine_path,
    )

    rows = _rows(pending_path) + _rows(quarantine_path)
    assert rows
    assert {
        row["field_key"]
        for row in rows
    }.isdisjoint({"product_identity", "brand", "category", "price"})
    assert all(
        "whole_product_core_conflict" not in row.get(
            "quarantine_reasons",
            [],
        )
        for row in rows
    )
