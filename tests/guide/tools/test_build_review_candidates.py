from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil

import pytest

import tools.guide_data.build_review_candidates as review_builder
from tools.guide_data.build_review_candidates import (
    ReviewCandidateBuildError,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "guide" / "reviews"


def _api():
    try:
        from tools.guide_data.build_review_candidates import (
            build_review_candidates,
        )
    except ModuleNotFoundError:
        pytest.fail("review candidate builder is missing")
    return build_review_candidates


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _manifest_digest(payload: dict[str, object]) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    return hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _build(
    tmp_path: Path,
    *,
    reverse_inputs: bool = False,
):
    input_root = tmp_path / "inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    manifest_path = input_root / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if reverse_inputs:
        manifest["sources"] = list(reversed(manifest["sources"]))
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return _api()(
        source_manifest_path=manifest_path,
        output_root=tmp_path / "output",
    )


def test_review_candidate_fixture_is_byte_deterministic(
    tmp_path: Path,
) -> None:
    first = _build(tmp_path / "first")
    second = _build(tmp_path / "second", reverse_inputs=True)

    assert first.pending.read_bytes() == second.pending.read_bytes()
    assert first.quarantine.read_bytes() == second.quarantine.read_bytes()
    assert first.manifest.read_bytes() == second.manifest.read_bytes()


def test_stable_id_binds_item_full_html_hash_and_eight_digit_ordinal(
    tmp_path: Path,
) -> None:
    result = _build(tmp_path)
    pending = _rows(result.pending)
    rows = pending + _rows(result.quarantine)
    first = next(row for row in rows if row["product_id"] == 501)
    html_sha256 = hashlib.sha256(
        (FIXTURE_ROOT / "tmall_reviews_alpha.html").read_bytes()
    ).hexdigest()

    assert first["candidate_id"] == (
        "review_tmall_item_111111111111_"
        f"html_{html_sha256}_ordinal_00000001"
    )
    assert first["html_sha256"] == html_sha256
    assert first["page_ordinal"] == "00000001"
    assert first["source_locator"] == (
        "urn:tmall:ssr-html:item:111111111111:"
        "sku:222222222222:feed:700000000001:"
        f"sha256:{html_sha256}:ordinal:00000001"
    )
    assert all(
        re.fullmatch(
            r"review_tmall_item_[0-9]+_html_[0-9a-f]{64}_"
            r"ordinal_[0-9]{8}",
            str(row["candidate_id"]),
        )
        for row in [*pending, *_rows(result.quarantine)]
    )


def test_builder_quarantines_pii_marketing_qa_and_cross_sku(
    tmp_path: Path,
) -> None:
    result = _build(tmp_path)
    quarantine = _rows(result.quarantine)

    assert {
        reason
        for row in quarantine
        for reason in row["quarantine_reasons"]
    } == {
        "cross_sku",
        "marketing",
        "pii",
        "qa",
        "whole_product_binding_conflict",
    }
    pii = next(
        row for row in quarantine if "pii" in row["quarantine_reasons"]
    )
    assert pii["content"] == "[REDACTED_PII]"
    assert pii["content_kind"] == "quarantine_marker"
    assert "body" not in pii
    assert all(
        row["content_kind"] == "quarantine_marker"
        for row in quarantine
    )
    serialized = result.quarantine.read_text(encoding="utf-8")
    assert "质地清爽" not in serialized
    assert "fixture_user_123" not in serialized
    assert "另一规格的香味" not in serialized
    assert str(FIXTURE_ROOT) not in result.quarantine.read_text(
        encoding="utf-8"
    )


def test_cross_sku_quarantines_all_candidates_for_bound_product(
    tmp_path: Path,
) -> None:
    result = _build(tmp_path)
    pending = _rows(result.pending)
    quarantine = _rows(result.quarantine)
    bound_product_rows = [
        row
        for row in pending + quarantine
        if row["product_id"] == 501
    ]

    assert bound_product_rows
    assert not [
        row for row in pending if row["product_id"] == 501
    ]
    assert all(
        "whole_product_binding_conflict"
        in row["quarantine_reasons"]
        for row in bound_product_rows
    )


def test_cross_sku_quarantines_all_sources_for_the_product(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    manifest_path = input_root / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"][1]["product_id"] = 501
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = _api()(
        source_manifest_path=manifest_path,
        output_root=tmp_path / "output",
    )
    pending = _rows(result.pending)
    quarantine = _rows(result.quarantine)

    assert not [row for row in pending if row["product_id"] == 501]
    assert len(quarantine) == 6
    assert {row["product_id"] for row in quarantine} == {501}
    assert all(
        "whole_product_binding_conflict"
        in row["quarantine_reasons"]
        for row in quarantine
    )
    assert all(
        row["content_kind"] == "quarantine_marker"
        for row in quarantine
    )
    assert all("body" not in row for row in quarantine)
    serialized = result.quarantine.read_text(encoding="utf-8")
    assert "质地清爽" not in serialized
    assert "洗后没有紧绷感" not in serialized


def test_builder_outputs_pending_or_quarantine_only(
    tmp_path: Path,
) -> None:
    result = _build(tmp_path)
    pending = _rows(result.pending)
    quarantine = _rows(result.quarantine)
    rows = [*pending, *quarantine]

    assert rows
    assert {row["status"] for row in rows} == {
        "pending",
        "quarantine",
    }
    assert {row["status"] for row in pending} == {"pending"}
    assert {row["status"] for row in quarantine} == {"quarantine"}
    assert all("reviewer" not in row for row in rows)
    assert all("decision" not in row for row in rows)
    assert b'"approved"' not in result.pending.read_bytes()
    assert b'"approved"' not in result.quarantine.read_bytes()


def test_fixture_counts_and_historical_provenance_are_honest(
    tmp_path: Path,
) -> None:
    result = _build(tmp_path)
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))

    assert result.extracted_count == 7
    assert result.deduplicated_count == 1
    assert result.pending_count == 1
    assert result.quarantine_count == 5
    assert result.provenance_status == "fixture_only"
    assert result.historical_counts == {
        "total_candidates": 336,
        "strict_candidates": 111,
        "status": "not_rerun",
    }
    assert manifest["provenance_status"] == "fixture_only"
    assert manifest["historical_counts"] == result.historical_counts
    assert manifest["fixture_counts"] == {
        "deduplicated_candidates": 1,
        "extracted_candidates": 7,
        "pending_candidates": 1,
        "quarantine_candidates": 5,
    }


def test_candidate_manifest_locks_queues_counts_sources_and_provenance(
    tmp_path: Path,
) -> None:
    result = _build(tmp_path)
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    pending_rows = _rows(result.pending)
    quarantine_rows = _rows(result.quarantine)

    assert manifest["manifest_sha256"] == _manifest_digest(manifest)
    assert manifest["pending_file"] == result.pending.name
    assert manifest["pending_sha256"] == hashlib.sha256(
        result.pending.read_bytes()
    ).hexdigest()
    assert manifest["quarantine_file"] == result.quarantine.name
    assert manifest["quarantine_sha256"] == hashlib.sha256(
        result.quarantine.read_bytes()
    ).hexdigest()
    assert manifest["fixture_counts"] == {
        "deduplicated_candidates": 1,
        "extracted_candidates": 7,
        "pending_candidates": len(pending_rows),
        "quarantine_candidates": len(quarantine_rows),
    }
    assert manifest["provenance_status"] == "fixture_only"
    assert manifest["historical_counts"]["status"] == "not_rerun"
    assert {
        str(source["html_sha256"])
        for source in manifest["sources"]
    } == {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in FIXTURE_ROOT.glob("*.html")
    }


def test_source_manifest_requires_a_complete_sha256(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    manifest_path = input_root / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["sources"][0]["sha256"]
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ReviewCandidateBuildError,
        match="invalid source entry",
    ):
        _api()(
            source_manifest_path=manifest_path,
            output_root=tmp_path / "output",
        )


def test_source_manifest_sha_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    manifest_path = input_root / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"][0]["sha256"] = "0" * 64
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ReviewCandidateBuildError,
        match="SHA-256 mismatch",
    ):
        _api()(
            source_manifest_path=manifest_path,
            output_root=tmp_path / "output",
        )
    assert not (tmp_path / "output").exists()


def test_source_replaced_after_hash_validation_uses_validated_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_root = tmp_path / "inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    manifest_path = input_root / "source_manifest.json"
    declared = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared_hashes = {
        source["sha256"] for source in declared["sources"]
    }
    drifted_bytes = b"""<!doctype html>
<article data-review-candidate data-feed-id="999999999999">
  <p data-review-content>drifted source bytes</p>
</article>
"""
    real_load_sources = review_builder._load_sources

    def replace_after_validation(path: Path):
        sources = real_load_sources(path)
        sources[0].path.write_bytes(drifted_bytes)
        return sources

    monkeypatch.setattr(
        review_builder,
        "_load_sources",
        replace_after_validation,
    )

    result = _api()(
        source_manifest_path=manifest_path,
        output_root=tmp_path / "output",
    )
    serialized = result.pending.read_bytes() + result.quarantine.read_bytes()
    built_manifest = json.loads(
        result.manifest.read_text(encoding="utf-8")
    )

    assert {
        source["html_sha256"]
        for source in built_manifest["sources"]
    } == declared_hashes
    assert b"drifted source bytes" not in serialized


def test_source_symlink_is_rejected_even_when_target_hash_matches(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    source_path = input_root / "tmall_reviews_alpha.html"
    source_path.unlink()
    source_path.symlink_to(FIXTURE_ROOT / source_path.name)

    with pytest.raises(
        ReviewCandidateBuildError,
        match="source path must be a stable regular file",
    ):
        _api()(
            source_manifest_path=input_root / "source_manifest.json",
            output_root=tmp_path / "output",
        )


def test_source_intermediate_symlink_is_rejected_even_inside_root(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    manifest_path = input_root / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = manifest["sources"][0]
    original_path = input_root / source["path"]
    real_root = input_root / "real-sources"
    real_root.mkdir()
    moved_path = real_root / original_path.name
    original_path.replace(moved_path)
    linked_root = input_root / "linked-sources"
    linked_root.symlink_to(real_root.name, target_is_directory=True)
    source["path"] = f"{linked_root.name}/{moved_path.name}"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ReviewCandidateBuildError,
        match="source path must be a stable regular file",
    ):
        _api()(
            source_manifest_path=manifest_path,
            output_root=tmp_path / "output",
        )


def test_source_replacement_between_stat_and_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_root = tmp_path / "inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    manifest_path = input_root / "source_manifest.json"
    source_path = input_root / "tmall_reviews_alpha.html"
    original_bytes = source_path.read_bytes()
    real_open = review_builder.os.open
    raced = False

    def replace_before_leaf_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal raced
        if (
            not raced
            and os.path.basename(os.fspath(path)) == source_path.name
            and not flags & getattr(os, "O_DIRECTORY", 0)
        ):
            raced = True
            source_path.unlink()
            source_path.write_bytes(original_bytes)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(
        review_builder.os,
        "open",
        replace_before_leaf_open,
    )

    with pytest.raises(
        ReviewCandidateBuildError,
        match="source path must be a stable regular file",
    ):
        _api()(
            source_manifest_path=manifest_path,
            output_root=tmp_path / "output",
        )
    assert raced is True


def test_partial_historical_reproduction_is_source_incomplete() -> None:
    locked = next(iter(review_builder._HISTORICAL_SOURCE_LOCKS))
    status, historical = review_builder._provenance(
        source_summaries=[
            {
                "html_sha256": locked[3],
                "item_id": locked[1],
                "path": "opaque.html",
                "product_id": locked[0],
                "review_elements": 1,
                "sku_id": locked[2],
            }
        ],
        extracted_count=1,
        pending_count=1,
    )

    assert status == "source_incomplete"
    assert historical == {
        "total_candidates": 336,
        "strict_candidates": 111,
        "status": "not_rerun",
    }


def test_complete_historical_reproduction_uses_new_provenance_term() -> None:
    summaries = [
        {
            "html_sha256": html_sha256,
            "item_id": item_id,
            "path": f"opaque-{index}.html",
            "product_id": product_id,
            "review_elements": 112,
            "sku_id": sku_id,
        }
        for index, (
            product_id,
            item_id,
            sku_id,
            html_sha256,
        ) in enumerate(
            sorted(review_builder._HISTORICAL_SOURCE_LOCKS),
            start=1,
        )
    ]

    status, historical = review_builder._provenance(
        source_summaries=summaries,
        extracted_count=336,
        pending_count=111,
    )

    assert status == "historical_reproduced"
    assert historical["status"] == "rerun"


def test_review_builder_source_has_no_retired_provenance_semantics() -> None:
    source = Path(review_builder.__file__).read_text(encoding="utf-8")
    retired_term = "locked_" + "originals"

    assert retired_term not in source
