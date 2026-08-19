from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
from typing import Any

import pytest

from app.guide.retrieval.category_fact_contracts import (
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile
import tools.guide_data.build_category_fact_candidates as candidate_builder
from tools.guide_data.build_category_fact_candidates import (
    CandidateBuildError,
    CandidateBuildReport,
    build_category_fact_candidates,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests/fixtures/guide/category_data"
CANONICAL_PRODUCTS = ROOT / "data/canonical/core_products_v1.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.read_bytes():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _fixture_copy(tmp_path: Path, *, reverse_sources: bool) -> Path:
    copied = tmp_path / "category-data"
    shutil.copytree(FIXTURE_ROOT, copied)
    manifest_path = copied / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if reverse_sources:
        manifest["sources"].reverse()
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _build(
    tmp_path: Path,
    *,
    reverse_sources: bool = False,
) -> tuple[CandidateBuildReport, Path, Path]:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=reverse_sources,
    )
    pending_path = tmp_path / "out/pending.jsonl"
    quarantine_path = tmp_path / "out/quarantine.jsonl"
    report = build_category_fact_candidates(
        source_manifest_path=manifest_path,
        canonical_products_path=CANONICAL_PRODUCTS,
        output_path=pending_path,
        quarantine_path=quarantine_path,
    )
    return report, pending_path, quarantine_path


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _replace_source(
    manifest_path: Path,
    *,
    source_id: str,
    content: bytes,
    keep_only_source: bool = False,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = next(
        item
        for item in manifest["sources"]
        if item["source_id"] == source_id
    )
    source_path = manifest_path.parent / source["path"]
    source_path.write_bytes(content)
    source["sha256"] = hashlib.sha256(content).hexdigest()
    if keep_only_source:
        manifest["sources"] = [source]
    _write_manifest(manifest_path, manifest)


def _build_from_manifest(
    tmp_path: Path,
    manifest_path: Path,
) -> tuple[CandidateBuildReport, Path, Path]:
    pending_path = tmp_path / "out/pending.jsonl"
    quarantine_path = tmp_path / "out/quarantine.jsonl"
    report = build_category_fact_candidates(
        source_manifest_path=manifest_path,
        canonical_products_path=CANONICAL_PRODUCTS,
        output_path=pending_path,
        quarantine_path=quarantine_path,
    )
    return report, pending_path, quarantine_path


def _normalized_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _candidate_id(row: dict[str, Any]) -> str:
    payload = (
        f"{row['product_id']}\0{row['category_profile']}\0"
        f"{row['field_key']}\0{row['source_sha256']}\0"
        f"{row['source_locator']}\0"
        f"{_normalized_json(row['normalized_value'])}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_builder_reads_html_ocr_and_official_structured_sources(
    tmp_path: Path,
) -> None:
    report, pending_path, quarantine_path = _build(tmp_path)
    pending = _read_jsonl(pending_path)
    quarantine = _read_jsonl(quarantine_path)

    assert {row["extraction_method"] for row in pending + quarantine} == {
        "html",
        "ocr_json",
        "structured_json",
    }
    assert report.input_count == 20
    assert report.pending_count == len(pending) == 0
    assert report.quarantine_count == len(quarantine) == 19
    assert report.duplicate_count == 1
    assert (
        report.input_count
        == report.pending_count
        + report.quarantine_count
        + report.duplicate_count
    )


def test_candidate_outputs_are_byte_stable_when_source_order_changes(
    tmp_path: Path,
) -> None:
    first, first_pending, first_quarantine = _build(tmp_path / "first")
    second, second_pending, second_quarantine = _build(
        tmp_path / "second",
        reverse_sources=True,
    )

    assert first_pending.read_bytes() == second_pending.read_bytes()
    assert first_quarantine.read_bytes() == second_quarantine.read_bytes()
    assert first.pending_sha256 == second.pending_sha256
    assert first.quarantine_sha256 == second.quarantine_sha256


def test_candidate_ids_follow_the_spec_formula_and_outputs_are_unique_sorted(
    tmp_path: Path,
) -> None:
    _, pending_path, quarantine_path = _build(tmp_path)

    for path in (pending_path, quarantine_path):
        rows = _read_jsonl(path)
        ids = [row["candidate_id"] for row in rows]
        assert ids == sorted(ids)
        assert len(ids) == len(set(ids))

    for row in _read_jsonl(pending_path):
        assert row["candidate_id"] == _candidate_id(row)

    inapplicable = next(
        row
        for row in _read_jsonl(quarantine_path)
        if row["field_key"] == "fragrance_family"
    )
    assert inapplicable["candidate_id"] == _candidate_id(
        {
            **inapplicable,
            "normalized_value": ["木质调"],
        }
    )


def test_optional_field_conflicts_are_quarantined_without_values(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    payload = {
        "schema_version": "guide-category-official-v1",
        "facts": [
            {
                "field_key": "shade",
                "source_locator": "official:shade",
                "value": ["2W0", "2C0"],
            },
            {
                "field_key": "longevity",
                "source_locator": "official:longevity",
                "value": "12 小时持妆",
            },
            {
                "field_key": "finish",
                "source_locator": "official:finish-a",
                "value": ["柔焦哑光"],
            },
            {
                "field_key": "finish",
                "source_locator": "official:finish-b",
                "value": ["自然哑光"],
            },
        ],
    }
    _replace_source(
        manifest_path,
        source_id="official-structured-product-79",
        content=(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8"),
        keep_only_source=True,
    )

    report, pending_path, quarantine_path = _build_from_manifest(
        tmp_path,
        manifest_path,
    )
    pending = _read_jsonl(pending_path)
    quarantine = _read_jsonl(quarantine_path)

    shade_rows = [row for row in pending if row["field_key"] == "shade"]
    assert len(shade_rows) == 1
    assert shade_rows[0]["normalized_value"] == ["2C0", "2W0"]

    longevity_rows = [
        row for row in pending if row["field_key"] == "longevity"
    ]
    assert len(longevity_rows) == 1
    assert longevity_rows[0]["normalized_value"] == "12 小时持妆"

    finish_rows = [
        row for row in quarantine if row["field_key"] == "finish"
    ]
    assert len(finish_rows) == 2
    assert report.conflict_group_count == 1
    assert all(
        "field_value_conflict" in row["quarantine_reasons"]
        for row in finish_rows
    )
    assert all("normalized_value" not in row for row in finish_rows)
    assert report.pending_count == 2
    assert report.quarantine_count == 2


def test_core_field_conflict_quarantines_every_candidate_for_product(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    payload = {
        "schema_version": "guide-category-official-v1",
        "facts": [
            {
                "field_key": "brand",
                "source_locator": "official:brand",
                "value": "不是雅诗兰黛",
            },
            {
                "field_key": "coverage",
                "source_locator": "official:coverage",
                "value": "中高遮瑕",
            },
        ],
    }
    _replace_source(
        manifest_path,
        source_id="official-structured-product-79",
        content=(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8"),
        keep_only_source=True,
    )

    report, pending_path, quarantine_path = _build_from_manifest(
        tmp_path,
        manifest_path,
    )
    quarantine = _read_jsonl(quarantine_path)

    assert report.input_count == 2
    assert report.pending_count == 0
    assert _read_jsonl(pending_path) == []
    assert report.quarantine_count == len(quarantine) == 2
    assert {row["product_id"] for row in quarantine} == {79}
    assert all(
        "whole_product_core_conflict" in row["quarantine_reasons"]
        for row in quarantine
    )
    assert all("normalized_value" not in row for row in quarantine)


def test_product_binding_conflict_quarantines_bound_product(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    payload = {
        "schema_version": "guide-category-official-v1",
        "facts": [
            {
                "field_key": "coverage",
                "source_locator": "official:bound-product",
                "value": "中高遮瑕",
            },
            {
                "field_key": "coverage",
                "product_id": 80,
                "source_locator": "official:wrong-product",
                "value": "高遮瑕",
            },
        ],
    }
    _replace_source(
        manifest_path,
        source_id="official-structured-product-79",
        content=(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8"),
        keep_only_source=True,
    )

    report, pending_path, quarantine_path = _build_from_manifest(
        tmp_path,
        manifest_path,
    )
    quarantine = _read_jsonl(quarantine_path)

    assert report.input_count == 2
    assert report.pending_count == 0
    assert _read_jsonl(pending_path) == []
    assert report.quarantine_count == len(quarantine) == 2
    assert all(
        "whole_product_binding_conflict" in row["quarantine_reasons"]
        for row in quarantine
    )
    assert all("normalized_value" not in row for row in quarantine)


def test_registry_rejects_unauthorized_misbound_unknown_and_inapplicable_rows(
    tmp_path: Path,
) -> None:
    _, pending_path, quarantine_path = _build(tmp_path)
    pending = _read_jsonl(pending_path)
    quarantine = _read_jsonl(quarantine_path)
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }

    for row in pending:
        profile = CategoryProfile(row["category_profile"])
        definition = definitions[row["field_key"]]
        assert profile in definition.profiles
        assert SourceClass(row["source_class"]) is not SourceClass.UNKNOWN
        assert SourceClass(row["source_class"]) in {
            policy.source_class
            for policy in definition.source_policies
        }

    reasons = {
        reason
        for row in quarantine
        for reason in row["quarantine_reasons"]
    }
    assert {
        "field_not_applicable",
        "product_not_found",
        "product_profile_mismatch",
        "protected_canonical_field",
        "sensitive_value",
        "source_not_authorized",
        "source_binding_mismatch",
        "unknown_field",
        "unknown_profile",
        "unknown_source",
    } <= reasons


def test_pending_and_quarantine_never_approve_or_leak_sensitive_content(
    tmp_path: Path,
) -> None:
    _, pending_path, quarantine_path = _build(tmp_path)
    pending = _read_jsonl(pending_path)
    quarantine = _read_jsonl(quarantine_path)
    output = pending_path.read_bytes() + quarantine_path.read_bytes()

    assert all(row["status"] == "pending" for row in pending)
    assert {row["status"] for row in quarantine} == {"quarantine"}
    assert all(
        key not in row
        for row in pending + quarantine
        for key in (
            "approved_fact",
            "built_at",
            "created_at",
            "decision",
            "generated_at",
            "input_path",
            "raw_content",
            "raw_html",
            "raw_value",
            "reviewed_at",
            "reviewer",
        )
    )
    for forbidden in (
        b"approved_fact",
        b"alice.sensitive@example.com",
        b"/Users/alice",
        b"<b>",
        "消费者声称绝对安全".encode(),
        "不应输出的原始标签".encode(),
    ):
        assert forbidden not in output
    assert str(tmp_path).encode() not in output
    assert all(
        not Path(row["source_locator"]).is_absolute()
        for row in pending + quarantine
    )
    assert all("normalized_value" not in row for row in quarantine)
    assert all(
        set(row) >= {"value_sha256", "quarantine_reasons"}
        for row in quarantine
    )


def test_build_time_is_absent_from_ids_and_serialized_outputs(
    tmp_path: Path,
) -> None:
    _, pending_path, quarantine_path = _build(tmp_path)
    rows = _read_jsonl(pending_path) + _read_jsonl(quarantine_path)

    assert all(
        forbidden not in row
        for row in rows
        for forbidden in (
            "build_time",
            "built_at",
            "created_at",
            "generated_at",
            "timestamp",
        )
    )


@pytest.mark.parametrize(
    ("source_id", "source_class"),
    [
        ("packaging-ocr-product-79", "structured_official"),
        ("official-html-product-79", "structured_official"),
        ("official-structured-product-79", "ocr_packaging"),
    ],
)
def test_source_types_cannot_claim_authority_outside_their_allowlist(
    tmp_path: Path,
    source_id: str,
    source_class: str,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = next(
        item
        for item in manifest["sources"]
        if item["source_id"] == source_id
    )
    source["source_class"] = source_class
    _write_manifest(manifest_path, manifest)

    with pytest.raises(
        CandidateBuildError,
        match="source_type/source_class combination is not allowed",
    ):
        _build_from_manifest(tmp_path, manifest_path)


def test_embedded_absolute_paths_are_quarantined_or_redacted_everywhere(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    payload = {
        "schema_version": "guide-category-official-v1",
        "facts": [
            {
                "field_key": "coverage",
                "source_locator": "official:value-posix",
                "value": "high /Users/alice/private/fact.json lasting",
            },
            {
                "field_key": "coverage",
                "source_locator": "official:value-private",
                "value": "high /tmp/private-fact.json lasting",
            },
            {
                "field_key": "coverage",
                "source_locator": "official:value-windows",
                "value": r"high C:\Users\alice\private\fact.json lasting",
            },
            {
                "field_key": "coverage",
                "source_locator": (
                    "official:line 7 /private/tmp/category-source.json"
                ),
                "value": "high lasting",
            },
        ],
    }
    _replace_source(
        manifest_path,
        source_id="official-structured-product-79",
        content=(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8"),
        keep_only_source=True,
    )

    report, pending_path, quarantine_path = _build_from_manifest(
        tmp_path,
        manifest_path,
    )
    pending = _read_jsonl(pending_path)
    quarantine = _read_jsonl(quarantine_path)
    output = pending_path.read_bytes() + quarantine_path.read_bytes()

    assert report.input_count == 4
    assert report.pending_count == len(pending) == 0
    assert report.quarantine_count == len(quarantine) == 4
    assert report.duplicate_count == 0
    assert report.input_count == (
        report.pending_count
        + report.quarantine_count
        + report.duplicate_count
    )
    assert {
        reason
        for row in quarantine
        for reason in row["quarantine_reasons"]
    } >= {"field_value_conflict", "sensitive_value"}
    assert any(
        row["source_locator"].startswith(
            "official-structured-product-79:redacted:"
        )
        for row in quarantine
    )
    assert all("normalized_value" not in row for row in quarantine)
    assert all("raw_value" not in row for row in pending + quarantine)
    for forbidden in (
        b"/Users/alice",
        b"/private/tmp",
        b"/tmp/private-fact",
        b"C:\\\\Users\\\\alice",
    ):
        assert forbidden not in output


@pytest.mark.parametrize(
    "unsafe_uri",
    [
        "file:///Users/alice/private/fact.json",
        "file%3A%2F%2F%2FUsers%2Falice%2Fprivate%2Ffact.json",
    ],
)
def test_file_uris_never_enter_serialized_review_queues(
    tmp_path: Path,
    unsafe_uri: str,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    payload = {
        "schema_version": "guide-category-official-v1",
        "facts": [
            {
                "field_key": "coverage",
                "source_locator": unsafe_uri,
                "value": f"high {unsafe_uri} lasting",
            },
        ],
    }
    _replace_source(
        manifest_path,
        source_id="official-structured-product-79",
        content=(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8"),
        keep_only_source=True,
    )

    report, pending_path, quarantine_path = _build_from_manifest(
        tmp_path,
        manifest_path,
    )
    quarantine = _read_jsonl(quarantine_path)
    output = pending_path.read_bytes() + quarantine_path.read_bytes()

    assert report.pending_count == 0
    assert report.quarantine_count == len(quarantine) == 1
    assert "sensitive_value" in quarantine[0]["quarantine_reasons"]
    assert quarantine[0]["source_locator"].startswith(
        "official-structured-product-79:redacted:"
    )
    assert "normalized_value" not in quarantine[0]
    assert unsafe_uri.encode() not in output
    assert b"/Users/alice" not in output


def test_html_void_elements_do_not_break_capture_depth(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    html = b"""<!doctype html>
<html><head><meta charset="utf-8"></head><body>
<section data-guide-field="longevity" data-source-locator="html:void">
high<br>lasting<img src="product.png"><input value="ignored">
</section>
</body></html>
"""
    _replace_source(
        manifest_path,
        source_id="official-html-product-79",
        content=html,
        keep_only_source=True,
    )

    report, pending_path, quarantine_path = _build_from_manifest(
        tmp_path,
        manifest_path,
    )

    assert report.input_count == 1
    assert report.pending_count == 1
    assert report.quarantine_count == 0
    assert _read_jsonl(quarantine_path) == []
    assert _read_jsonl(pending_path)[0]["normalized_value"] == "high lasting"


def test_pair_publication_uses_private_staging_lock_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    output_root = tmp_path / "published"
    output_root.mkdir()
    pending_path = output_root / "pending.jsonl"
    quarantine_path = output_root / "quarantine.jsonl"
    old_pending = b'{"old":"pending"}\n'
    old_quarantine = b'{"old":"quarantine"}\n'
    pending_path.write_bytes(old_pending)
    quarantine_path.write_bytes(old_quarantine)

    real_replace = candidate_builder.os.replace
    failed_once = False
    staging_modes: list[int] = []
    lock_modes: list[int] = []

    def fail_second_publish(source: object, target: object) -> None:
        nonlocal failed_once
        source_path = Path(source)
        target_path = Path(target)
        staging_modes.append(
            stat.S_IMODE(source_path.parent.stat().st_mode)
        )
        lock_modes.extend(
            stat.S_IMODE(lock_path.stat().st_mode)
            for lock_path in output_root.glob(
                ".category-fact-candidates.*.lock"
            )
        )
        if target_path == quarantine_path and not failed_once:
            failed_once = True
            raise OSError("injected quarantine publication failure")
        real_replace(source, target)

    monkeypatch.setattr(
        candidate_builder.os,
        "replace",
        fail_second_publish,
    )

    with pytest.raises(
        OSError,
        match="injected quarantine publication failure",
    ):
        build_category_fact_candidates(
            source_manifest_path=manifest_path,
            canonical_products_path=CANONICAL_PRODUCTS,
            output_path=pending_path,
            quarantine_path=quarantine_path,
        )

    assert pending_path.read_bytes() == old_pending
    assert quarantine_path.read_bytes() == old_quarantine
    assert staging_modes and set(staging_modes) == {0o700}
    assert lock_modes and set(lock_modes) == {0o600}
    assert not list(
        output_root.glob(".category-fact-candidates.*.staging")
    )


def test_overlapping_output_pairs_share_stable_locks_without_deadlock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "published"
    output_root.mkdir()
    first_path = output_root / "a.jsonl"
    shared_path = output_root / "b.jsonl"
    second_path = output_root / "c.jsonl"
    for path in (first_path, shared_path, second_path):
        path.write_bytes(b'{"generation":"old"}\n')

    real_lock = candidate_builder._exclusive_publish_lock
    real_replace = candidate_builder.os.replace
    lock_attempts: dict[str, list[Path]] = {}
    first_replace_entered = threading.Event()
    release_first_publish = threading.Event()
    second_replace_entered = threading.Event()
    errors: list[BaseException] = []

    @contextmanager
    def record_lock_attempt(path: Path):
        lock_attempts.setdefault(
            threading.current_thread().name,
            [],
        ).append(path)
        with real_lock(path):
            yield

    def coordinate_replace(source: object, target: object) -> None:
        target_path = Path(target)
        real_replace(source, target)
        thread_name = threading.current_thread().name
        if thread_name == "publish-ab" and target_path == first_path:
            first_replace_entered.set()
            if not release_first_publish.wait(timeout=5):
                raise TimeoutError("first publisher was not released")
        elif thread_name == "publish-bc" and target_path == shared_path:
            second_replace_entered.set()

    def publish(
        pending_path: Path,
        pending_content: bytes,
        quarantine_path: Path,
        quarantine_content: bytes,
    ) -> None:
        try:
            candidate_builder._publish_output_pair(
                pending_path=pending_path,
                pending_content=pending_content,
                quarantine_path=quarantine_path,
                quarantine_content=quarantine_content,
            )
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(
        candidate_builder,
        "_exclusive_publish_lock",
        record_lock_attempt,
    )
    monkeypatch.setattr(
        candidate_builder.os,
        "replace",
        coordinate_replace,
    )
    first = threading.Thread(
        target=publish,
        args=(first_path, b"A1\n", shared_path, b"B1\n"),
        name="publish-ab",
    )
    second = threading.Thread(
        target=publish,
        args=(shared_path, b"B2\n", second_path, b"C2\n"),
        name="publish-bc",
    )

    first.start()
    assert first_replace_entered.wait(timeout=5)
    second.start()
    try:
        assert not second_replace_entered.wait(timeout=0.25)
    finally:
        release_first_publish.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert lock_attempts["publish-ab"] == sorted(
        lock_attempts["publish-ab"],
        key=str,
    )
    assert lock_attempts["publish-bc"] == sorted(
        lock_attempts["publish-bc"],
        key=str,
    )
    assert (
        set(lock_attempts["publish-ab"])
        & set(lock_attempts["publish-bc"])
    )
    assert first_path.read_bytes() == b"A1\n"
    assert shared_path.read_bytes() == b"B2\n"
    assert second_path.read_bytes() == b"C2\n"


@pytest.mark.parametrize("symlink_output", ["pending", "quarantine"])
def test_output_symlink_is_rejected_without_changing_target_bytes(
    tmp_path: Path,
    symlink_output: str,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    output_root = tmp_path / "published"
    output_root.mkdir()
    symlink_target = tmp_path / f"{symlink_output}-target.jsonl"
    symlink_target.write_bytes(b'{"protected":"target"}\n')
    symlink_path = output_root / f"{symlink_output}.jsonl"
    symlink_path.symlink_to(symlink_target)
    other_path = output_root / (
        "quarantine.jsonl"
        if symlink_output == "pending"
        else "pending.jsonl"
    )
    other_path.write_bytes(b'{"protected":"other"}\n')
    pending_path = (
        symlink_path if symlink_output == "pending" else other_path
    )
    quarantine_path = (
        symlink_path if symlink_output == "quarantine" else other_path
    )

    with pytest.raises(
        CandidateBuildError,
        match="candidate output cannot be a symlink",
    ):
        build_category_fact_candidates(
            source_manifest_path=manifest_path,
            canonical_products_path=CANONICAL_PRODUCTS,
            output_path=pending_path,
            quarantine_path=quarantine_path,
        )

    assert symlink_path.is_symlink()
    assert symlink_target.read_bytes() == b'{"protected":"target"}\n'
    assert other_path.read_bytes() == b'{"protected":"other"}\n'


def test_candidate_ids_are_globally_unique_across_review_queues(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    payload = {
        "schema_version": "guide-category-official-v1",
        "facts": [
            {
                "field_key": "coverage",
                "source_locator": "official:duplicate-authority",
                "value": "high coverage",
            },
            {
                "field_key": "coverage",
                "source_class": "official_description",
                "source_locator": "official:duplicate-authority",
                "value": "high coverage",
            },
        ],
    }
    _replace_source(
        manifest_path,
        source_id="official-structured-product-79",
        content=(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8"),
        keep_only_source=True,
    )

    report, pending_path, quarantine_path = _build_from_manifest(
        tmp_path,
        manifest_path,
    )
    pending = _read_jsonl(pending_path)
    quarantine = _read_jsonl(quarantine_path)
    rows = pending + quarantine
    candidate_ids = [row["candidate_id"] for row in rows]

    assert report.input_count == 2
    assert report.pending_count == len(pending) == 0
    assert report.quarantine_count == len(quarantine) == 1
    assert report.duplicate_count == 1
    assert report.conflict_group_count == 0
    assert report.input_count == (
        report.pending_count
        + report.quarantine_count
        + report.duplicate_count
    )
    assert len(candidate_ids) == len(set(candidate_ids))
    assert quarantine[0]["status"] == "quarantine"
    assert "candidate_id_conflict" in quarantine[0]["quarantine_reasons"]
    assert "normalized_value" not in quarantine[0]


def test_source_manifest_sha_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    html_path = manifest_path.parent / "official_product.html"
    html_path.write_text(
        html_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CandidateBuildError, match="SHA-256 mismatch"):
        build_category_fact_candidates(
            source_manifest_path=manifest_path,
            canonical_products_path=CANONICAL_PRODUCTS,
            output_path=tmp_path / "pending.jsonl",
            quarantine_path=tmp_path / "quarantine.jsonl",
        )


def test_source_leaf_symlink_is_rejected_even_when_hash_matches(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    source_path = manifest_path.parent / "official_product.html"
    target_path = manifest_path.parent / "official_product_real.html"
    target_path.write_bytes(source_path.read_bytes())
    source_path.unlink()
    source_path.symlink_to(target_path.name)

    with pytest.raises(
        CandidateBuildError,
        match="source path must be a stable regular file",
    ):
        build_category_fact_candidates(
            source_manifest_path=manifest_path,
            canonical_products_path=CANONICAL_PRODUCTS,
            output_path=tmp_path / "pending.jsonl",
            quarantine_path=tmp_path / "quarantine.jsonl",
        )


def test_source_intermediate_symlink_is_rejected_even_inside_root(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = next(
        item
        for item in manifest["sources"]
        if item["source_id"] == "official-structured-product-79"
    )
    real_root = manifest_path.parent / "real-sources"
    real_root.mkdir()
    original_path = manifest_path.parent / source["path"]
    moved_path = real_root / original_path.name
    original_path.replace(moved_path)
    linked_root = manifest_path.parent / "linked-sources"
    linked_root.symlink_to(real_root.name, target_is_directory=True)
    source["path"] = f"{linked_root.name}/{moved_path.name}"
    _write_manifest(manifest_path, manifest)

    with pytest.raises(
        CandidateBuildError,
        match="source path must be a stable regular file",
    ):
        build_category_fact_candidates(
            source_manifest_path=manifest_path,
            canonical_products_path=CANONICAL_PRODUCTS,
            output_path=tmp_path / "pending.jsonl",
            quarantine_path=tmp_path / "quarantine.jsonl",
        )


def test_source_replacement_between_stat_and_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    source_path = manifest_path.parent / "official_structured.json"
    original_bytes = source_path.read_bytes()
    real_open = candidate_builder.os.open
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
            and dir_fd is not None
            and os.fspath(path) == source_path.name
            and not flags & getattr(os, "O_DIRECTORY", 0)
        ):
            raced = True
            source_path.unlink()
            source_path.write_bytes(original_bytes)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(
        candidate_builder.os,
        "open",
        replace_before_leaf_open,
    )

    with pytest.raises(
        CandidateBuildError,
        match="source path must be a stable regular file",
    ):
        build_category_fact_candidates(
            source_manifest_path=manifest_path,
            canonical_products_path=CANONICAL_PRODUCTS,
            output_path=tmp_path / "pending.jsonl",
            quarantine_path=tmp_path / "quarantine.jsonl",
        )
    assert raced is True


def test_source_replaced_after_hash_validation_uses_validated_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    validated_payload = {
        "schema_version": "guide-category-official-v1",
        "facts": [
            {
                "field_key": "coverage",
                "source_locator": "official:coverage",
                "value": "validated bytes",
            },
        ],
    }
    drifted_payload = {
        "schema_version": "guide-category-official-v1",
        "facts": [
            {
                "field_key": "coverage",
                "source_locator": "official:coverage",
                "value": "drifted path bytes",
            },
        ],
    }
    validated_bytes = (
        json.dumps(validated_payload, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    drifted_bytes = (
        json.dumps(drifted_payload, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    _replace_source(
        manifest_path,
        source_id="official-structured-product-79",
        content=validated_bytes,
        keep_only_source=True,
    )

    real_load_source_manifest = candidate_builder._load_source_manifest

    def replace_after_validation(path: Path):
        sources = real_load_source_manifest(path)
        sources[0].path.write_bytes(drifted_bytes)
        return sources

    monkeypatch.setattr(
        candidate_builder,
        "_load_source_manifest",
        replace_after_validation,
    )

    report, pending_path, quarantine_path = _build_from_manifest(
        tmp_path,
        manifest_path,
    )

    assert report.pending_count == 1
    assert report.quarantine_count == 0
    assert _read_jsonl(quarantine_path) == []
    pending = _read_jsonl(pending_path)
    assert pending[0]["normalized_value"] == "validated bytes"
    assert pending[0]["source_sha256"] == hashlib.sha256(
        validated_bytes
    ).hexdigest()


def test_cli_writes_both_outputs_without_exposing_local_paths(
    tmp_path: Path,
) -> None:
    manifest_path = _fixture_copy(
        tmp_path,
        reverse_sources=False,
    )
    pending_path = tmp_path / "cli/pending.jsonl"
    quarantine_path = tmp_path / "cli/quarantine.jsonl"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.build_category_fact_candidates",
            "--source-manifest",
            str(manifest_path),
            "--canonical-products",
            str(CANONICAL_PRODUCTS),
            "--output",
            str(pending_path),
            "--quarantine",
            str(quarantine_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary == {
        "conflict_group_count": 3,
        "duplicate_count": 1,
        "input_count": 20,
        "pending_count": 0,
        "pending_sha256": hashlib.sha256(
            pending_path.read_bytes()
        ).hexdigest(),
        "quarantine_count": 19,
        "quarantine_sha256": hashlib.sha256(
            quarantine_path.read_bytes()
        ).hexdigest(),
    }
    assert str(tmp_path) not in completed.stdout
