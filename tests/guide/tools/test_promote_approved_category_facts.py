from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
from typing import Any

import pytest

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_fact_assets import (
    load_category_fact_assets,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)


ROOT = Path(__file__).resolve().parents[3]
CANONICAL_ROOT = ROOT / "data" / "canonical"
CANONICAL_MANIFEST = CANONICAL_ROOT / "core_products_v1_manifest.json"
CANONICAL_PRODUCTS = CANONICAL_ROOT / "core_products_v1.jsonl"
FACTS_NAME = "category_facts_v1.jsonl"
MANIFEST_NAME = "category_facts_v1_manifest.json"
LOCK_NAME = ".category-fact-promotion.lock"
JOURNAL_NAME = ".category-fact-promotion.transaction.json"
DECISION_KEY = b"task-7-independent-review-key-01"
OTHER_DECISION_KEY = b"task-7-wrong-independent-key-001"


def _promotion_module():
    try:
        return importlib.import_module(
            "tools.guide_data.promote_approved_category_facts"
        )
    except ModuleNotFoundError:
        pytest.fail("category fact promotion tool is missing")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _candidate_id(row: dict[str, Any]) -> str:
    payload = (
        f"{row['product_id']}\0{row['category_profile']}\0"
        f"{row['field_key']}\0{row['source_sha256']}\0"
        f"{row['source_locator']}\0"
        f"{_canonical_json(row['normalized_value'])}"
    )
    return _sha256(payload.encode("utf-8"))


def _pending_candidate(
    *,
    value: object = None,
) -> dict[str, Any]:
    normalized_value = ["2C0"] if value is None else value
    row: dict[str, Any] = {
        "candidate_id": "",
        "category_profile": "base_makeup",
        "conflict_candidate_ids": [],
        "conflict_group_id": None,
        "extraction_method": "structured_json",
        "field_key": "shade",
        "has_conflict": False,
        "normalized_value": normalized_value,
        "product_id": 79,
        "source_class": "structured_official",
        "source_locator": "official-product-79:shade",
        "source_sha256": "a" * 64,
        "status": "pending",
        "value_sha256": _sha256(
            _canonical_json(normalized_value).encode("utf-8")
        ),
    }
    row["candidate_id"] = _candidate_id(row)
    return row


def _quarantine_candidate() -> dict[str, Any]:
    return {
        "candidate_id": _sha256(b"quarantine-candidate"),
        "category_profile": "base_makeup",
        "extraction_method": "structured_json",
        "field_key": "brand",
        "product_id": 79,
        "quarantine_reasons": ["protected_canonical_field"],
        "source_class": "structured_official",
        "source_locator": "official-product-79:brand",
        "source_sha256": "b" * 64,
        "status": "quarantine",
        "value_sha256": "c" * 64,
    }


def _approved_decision(candidate_id: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "decision": "approved_fact",
        "reason": "原始页面明确标注，且产品与字段归属已人工核对",
        "reviewed_at": "2026-08-10T08:30:00+08:00",
        "reviewer": "human-reviewer-01",
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = b"".join(
        _canonical_json(row).encode("utf-8") + b"\n"
        for row in rows
    )
    path.write_bytes(content)
    return content


def _promotion_inputs(
    tmp_path: Path,
    *,
    candidates: list[dict[str, object]] | None = None,
    quarantine: list[dict[str, object]] | None = None,
    decisions: list[dict[str, object]] | None = None,
    trusted_approval: bool = True,
) -> dict[str, object]:
    pending_rows = candidates or [_pending_candidate()]
    quarantine_rows = (
        [_quarantine_candidate()] if quarantine is None else quarantine
    )
    decision_rows = (
        [_approved_decision(str(pending_rows[0]["candidate_id"]))]
        if decisions is None
        else decisions
    )
    candidates_path = tmp_path / "review/pending.jsonl"
    quarantine_path = tmp_path / "review/quarantine.jsonl"
    decisions_path = tmp_path / "review/decisions.jsonl"
    pending_bytes = _write_jsonl(candidates_path, pending_rows)
    quarantine_bytes = _write_jsonl(quarantine_path, quarantine_rows)
    decision_bytes = _write_jsonl(decisions_path, decision_rows)
    arguments: dict[str, object] = {
        "candidates_path": candidates_path,
        "quarantine_path": quarantine_path,
        "decisions_path": decisions_path,
        "output_dir": tmp_path / "published",
        "expected_candidates_sha256": _sha256(pending_bytes),
        "expected_quarantine_sha256": _sha256(quarantine_bytes),
        "expected_decisions_sha256": _sha256(decision_bytes),
        "canonical_manifest_path": CANONICAL_MANIFEST,
        "canonical_products_path": CANONICAL_PRODUCTS,
    }
    if trusted_approval and any(
        row.get("decision") == "approved_fact"
        for row in decision_rows
    ):
        arguments["decision_hmac_key"] = DECISION_KEY
        arguments["decision_signature"] = _decision_signature(arguments)
    return arguments


def _promote(arguments: dict[str, object]):
    module = _promotion_module()
    return module.promote_approved_category_facts(**arguments)


def _signed_cli_command(arguments: dict[str, object]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tools.guide_data.promote_approved_category_facts",
        "--candidates",
        str(arguments["candidates_path"]),
        "--quarantine",
        str(arguments["quarantine_path"]),
        "--decisions",
        str(arguments["decisions_path"]),
        "--expected-candidates-sha256",
        str(arguments["expected_candidates_sha256"]),
        "--expected-quarantine-sha256",
        str(arguments["expected_quarantine_sha256"]),
        "--expected-decisions-sha256",
        str(arguments["expected_decisions_sha256"]),
        "--decision-signature",
        str(arguments["decision_signature"]),
        "--decision-key-env",
        "TASK7_DECISION_HMAC_KEY",
        "--canonical-manifest",
        str(CANONICAL_MANIFEST),
        "--canonical-products",
        str(CANONICAL_PRODUCTS),
        "--output-dir",
        str(arguments["output_dir"]),
    ]


def _with_decisions_digest(
    arguments: dict[str, object],
    *,
    digest: str | None = None,
) -> dict[str, object]:
    locked = dict(arguments)
    decisions_path = Path(locked["decisions_path"])
    locked["expected_decisions_sha256"] = (
        digest if digest is not None else _sha256(decisions_path.read_bytes())
    )
    return locked


def _decision_signature(
    arguments: dict[str, object],
    *,
    key: bytes = DECISION_KEY,
) -> str:
    decision_rows = _read_jsonl(Path(arguments["decisions_path"]))
    decision_manifest = {
        "decision_count": len(decision_rows),
        "decisions": decision_rows,
        "schema_version": "category-fact-decision-manifest-v1",
    }
    signature_payload = {
        "candidate_manifest_raw_sha256": arguments[
            "expected_candidates_sha256"
        ],
        "decision_manifest_sha256": _sha256(
            _canonical_json(decision_manifest).encode("utf-8")
        ),
        "schema_version": "category-fact-decision-signature-v1",
    }
    return hmac.new(
        key,
        _canonical_json(signature_payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.read_bytes():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _published_facts_path(output_dir: Path) -> Path:
    manifest = json.loads(
        (output_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    )
    return output_dir / str(manifest["facts_file"])


def _load_published(output_dir: Path, manifest_sha256: str):
    return load_category_fact_assets(
        manifest_path=output_dir / MANIFEST_NAME,
        expected_manifest_sha256=manifest_sha256,
        canonical_reader=CanonicalProductReader.from_files(
            manifest_path=CANONICAL_MANIFEST,
            products_path=CANONICAL_PRODUCTS,
        ),
        field_registry=category_field_registry(),
    )


def _load_published_snapshot(output_dir: Path):
    return load_category_fact_assets(
        manifest_path=output_dir / MANIFEST_NAME,
        canonical_reader=CanonicalProductReader.from_files(
            manifest_path=CANONICAL_MANIFEST,
            products_path=CANONICAL_PRODUCTS,
        ),
        field_registry=category_field_registry(),
    )


def test_api_requires_external_decisions_sha256(tmp_path: Path) -> None:
    arguments = _promotion_inputs(tmp_path)
    del arguments["expected_decisions_sha256"]

    with pytest.raises(TypeError, match="expected_decisions_sha256"):
        _promote(arguments)


def test_decision_queue_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    arguments = _with_decisions_digest(
        _promotion_inputs(tmp_path),
        digest="0" * 64,
    )

    with pytest.raises(ValueError, match="decision queue SHA-256 mismatch"):
        _promote(arguments)

    output_dir = Path(arguments["output_dir"])
    assert not (output_dir / FACTS_NAME).exists()
    assert not (output_dir / MANIFEST_NAME).exists()


def test_coordinated_decision_rewrite_cannot_replace_external_digest(
    tmp_path: Path,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    decisions_path = Path(arguments["decisions_path"])
    external_digest = _sha256(decisions_path.read_bytes())
    candidate_id = _pending_candidate()["candidate_id"]
    rewritten = _approved_decision(candidate_id)
    rewritten.update(
        {
            "reason": "另一组完整且格式合法的人工批准理由",
            "reviewed_at": "2026-08-10T10:00:00+08:00",
            "reviewer": "different-human-reviewer",
        }
    )
    _write_jsonl(decisions_path, [rewritten])
    arguments["expected_decisions_sha256"] = external_digest

    with pytest.raises(ValueError, match="decision queue SHA-256 mismatch"):
        _promote(arguments)

    output_dir = Path(arguments["output_dir"])
    assert not (output_dir / FACTS_NAME).exists()
    assert not (output_dir / MANIFEST_NAME).exists()


def test_cli_requires_external_decisions_sha256(tmp_path: Path) -> None:
    arguments = _promotion_inputs(tmp_path)
    command = [
        sys.executable,
        "-m",
        "tools.guide_data.promote_approved_category_facts",
        "--candidates",
        str(arguments["candidates_path"]),
        "--quarantine",
        str(arguments["quarantine_path"]),
        "--decisions",
        str(arguments["decisions_path"]),
        "--expected-candidates-sha256",
        str(arguments["expected_candidates_sha256"]),
        "--expected-quarantine-sha256",
        str(arguments["expected_quarantine_sha256"]),
        "--canonical-manifest",
        str(CANONICAL_MANIFEST),
        "--canonical-products",
        str(CANONICAL_PRODUCTS),
        "--output-dir",
        str(arguments["output_dir"]),
    ]

    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--expected-decisions-sha256" in completed.stderr


def test_nonempty_approval_without_repository_external_key_fails_closed(
    tmp_path: Path,
) -> None:
    arguments = _with_decisions_digest(
        _promotion_inputs(tmp_path, trusted_approval=False)
    )

    with pytest.raises(ValueError, match="decision HMAC key"):
        _promote(arguments)

    output_dir = Path(arguments["output_dir"])
    assert not (output_dir / MANIFEST_NAME).exists()


@pytest.mark.parametrize(
    ("key", "signature", "message"),
    [
        (DECISION_KEY, None, "decision batch signature"),
        (OTHER_DECISION_KEY, "valid", "signature mismatch"),
    ],
)
def test_nonempty_approval_rejects_missing_signature_and_wrong_key(
    tmp_path: Path,
    key: bytes,
    signature: str | None,
    message: str,
) -> None:
    arguments = _with_decisions_digest(_promotion_inputs(tmp_path))
    arguments["decision_hmac_key"] = key
    arguments["decision_signature"] = (
        _decision_signature(arguments)
        if signature == "valid"
        else signature
    )

    with pytest.raises(ValueError, match=message):
        _promote(arguments)

    assert not (
        Path(arguments["output_dir"]) / MANIFEST_NAME
    ).exists()


def test_signature_rejects_coordinated_candidate_and_decision_tampering(
    tmp_path: Path,
) -> None:
    arguments = _with_decisions_digest(_promotion_inputs(tmp_path))
    signature = _decision_signature(arguments)
    tampered_candidate = _pending_candidate(value=["3N0"])
    tampered_decision = _approved_decision(
        tampered_candidate["candidate_id"]
    )
    tampered_decision.update(
        {
            "reason": "自动化伪造原因",
            "reviewed_at": "2026-08-10T10:00:00+08:00",
            "reviewer": "forged-reviewer",
        }
    )
    pending_bytes = _write_jsonl(
        Path(arguments["candidates_path"]),
        [tampered_candidate],
    )
    decision_bytes = _write_jsonl(
        Path(arguments["decisions_path"]),
        [tampered_decision],
    )
    arguments.update(
        {
            "decision_hmac_key": DECISION_KEY,
            "decision_signature": signature,
            "expected_candidates_sha256": _sha256(pending_bytes),
            "expected_decisions_sha256": _sha256(decision_bytes),
        }
    )

    with pytest.raises(ValueError, match="signature mismatch"):
        _promote(arguments)

    assert not (
        Path(arguments["output_dir"]) / MANIFEST_NAME
    ).exists()


@pytest.mark.parametrize(
    "missing_field",
    ["reviewer", "reviewed_at", "decision", "reason"],
)
def test_promotion_requires_complete_human_decision_without_defaults(
    tmp_path: Path,
    missing_field: str,
) -> None:
    candidate = _pending_candidate()
    decision = _approved_decision(candidate["candidate_id"])
    decision.pop(missing_field)
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[decision],
    )
    output_dir = Path(arguments["output_dir"])
    output_dir.mkdir()
    facts_path = output_dir / FACTS_NAME
    manifest_path = output_dir / MANIFEST_NAME
    old_facts = b'{"generation":"old-facts"}\n'
    old_manifest = b'{"generation":"old-manifest"}\n'
    facts_path.write_bytes(old_facts)
    manifest_path.write_bytes(old_manifest)

    with pytest.raises(ValueError, match=missing_field):
        _promote(arguments)

    assert facts_path.read_bytes() == old_facts
    assert manifest_path.read_bytes() == old_manifest


def test_promotion_requires_timezone_aware_reviewed_at(
    tmp_path: Path,
) -> None:
    candidate = _pending_candidate()
    decision = _approved_decision(candidate["candidate_id"])
    decision["reviewed_at"] = "2026-08-10T08:30:00"
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[decision],
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        _promote(arguments)

    output_dir = Path(arguments["output_dir"])
    assert not (output_dir / FACTS_NAME).exists()
    assert not (output_dir / MANIFEST_NAME).exists()


def test_approved_fact_preserves_supplied_reviewer_and_reviewed_at(
    tmp_path: Path,
) -> None:
    candidate = _pending_candidate()
    decision = _approved_decision(candidate["candidate_id"])
    decision["reviewer"] = "named-human-reviewer"
    decision["reviewed_at"] = "2026-08-10T09:45:00+08:00"
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[decision],
    )

    report = _promote(arguments)
    loaded = _load_published(
        Path(arguments["output_dir"]),
        report.manifest_sha256,
    )

    assert report.fact_count == 1
    assert loaded.facts[0].reviewer == "named-human-reviewer"
    assert loaded.facts[0].reviewed_at.isoformat() == (
        "2026-08-10T09:45:00+08:00"
    )


@pytest.mark.parametrize("use_rejected_decision", [False, True])
def test_zero_approvals_publish_valid_empty_asset(
    tmp_path: Path,
    use_rejected_decision: bool,
) -> None:
    candidate = _pending_candidate()
    decisions: list[dict[str, object]] = []
    if use_rejected_decision:
        rejected = _approved_decision(candidate["candidate_id"])
        rejected["decision"] = "rejected"
        decisions.append(rejected)
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=decisions,
    )

    report = _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    loaded = _load_published(output_dir, report.manifest_sha256)
    manifest = json.loads(
        (output_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    )

    assert report.fact_count == 0
    if not decisions:
        assert "decision_hmac_key" not in arguments
        assert "decision_signature" not in arguments
    assert _published_facts_path(output_dir).read_bytes() == b""
    assert manifest["facts_file"] == (
        "category_facts_v1."
        "e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855.jsonl"
    )
    assert manifest["fact_count"] == 0
    assert loaded.facts == ()


def test_non_approved_decision_never_enters_production_asset(
    tmp_path: Path,
) -> None:
    approved = _pending_candidate(value=["2C0"])
    rejected = _pending_candidate(value=["3N0"])
    rejected_decision = _approved_decision(rejected["candidate_id"])
    rejected_decision["decision"] = "rejected"
    arguments = _promotion_inputs(
        tmp_path,
        candidates=sorted(
            [approved, rejected],
            key=lambda row: str(row["candidate_id"]),
        ),
        decisions=[
            _approved_decision(approved["candidate_id"]),
            rejected_decision,
        ],
    )

    report = _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    facts_path = _published_facts_path(output_dir)
    rows = _read_jsonl(facts_path)

    assert report.fact_count == 1
    assert rows[0]["value"] == ["2C0"]
    assert all(row["evidence_status"] == "approved_fact" for row in rows)
    assert b"rejected" not in facts_path.read_bytes()


def test_unknown_candidate_decision_is_rejected(
    tmp_path: Path,
) -> None:
    arguments = _promotion_inputs(
        tmp_path,
        decisions=[_approved_decision("f" * 64)],
    )

    with pytest.raises(ValueError, match="unknown candidate"):
        _promote(arguments)


def test_duplicate_candidate_decisions_are_rejected(
    tmp_path: Path,
) -> None:
    candidate = _pending_candidate()
    decision = _approved_decision(candidate["candidate_id"])
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[decision, dict(decision)],
    )

    with pytest.raises(ValueError, match="duplicate decision"):
        _promote(arguments)


def test_quarantine_candidate_cannot_be_approved(
    tmp_path: Path,
) -> None:
    quarantined = _quarantine_candidate()
    arguments = _promotion_inputs(
        tmp_path,
        decisions=[_approved_decision(quarantined["candidate_id"])],
    )

    with pytest.raises(ValueError, match="quarantine candidate"):
        _promote(arguments)


def test_conflicting_pending_candidate_is_rejected(
    tmp_path: Path,
) -> None:
    candidate = _pending_candidate()
    candidate["has_conflict"] = True
    candidate["conflict_group_id"] = "d" * 64
    candidate["conflict_candidate_ids"] = ["e" * 64]
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )

    with pytest.raises(
        ValueError,
        match="pending candidate cannot contain conflicts",
    ):
        _promote(arguments)


@pytest.mark.parametrize(
    ("queue_name", "expected_key"),
    [
        ("candidates_path", "expected_candidates_sha256"),
        ("quarantine_path", "expected_quarantine_sha256"),
    ],
)
def test_review_queue_hash_drift_is_rejected(
    tmp_path: Path,
    queue_name: str,
    expected_key: str,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    queue_path = Path(arguments[queue_name])
    expected_sha256 = arguments[expected_key]
    queue_path.write_bytes(queue_path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        _promote(arguments)

    assert arguments[expected_key] == expected_sha256
    output_dir = Path(arguments["output_dir"])
    assert not (output_dir / FACTS_NAME).exists()
    assert not (output_dir / MANIFEST_NAME).exists()


@pytest.mark.parametrize(
    "drift_field",
    ["normalized_value", "source_sha256"],
)
def test_candidate_content_address_drift_is_rejected(
    tmp_path: Path,
    drift_field: str,
) -> None:
    candidate = _pending_candidate()
    if drift_field == "normalized_value":
        candidate[drift_field] = ["tampered"]
    else:
        candidate[drift_field] = "d" * 64
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )

    with pytest.raises(ValueError, match="content address mismatch"):
        _promote(arguments)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"category_profile": "fragrance"},
            "product/profile mismatch",
        ),
        (
            {"product_id": 120},
            "product/profile mismatch",
        ),
        (
            {"field_key": "fragrance_family"},
            "field is not applicable",
        ),
    ],
)
def test_product_profile_and_field_misbinding_is_rejected_by_loader(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    candidate = _pending_candidate()
    candidate.update(updates)
    candidate["candidate_id"] = _candidate_id(candidate)
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )

    with pytest.raises(RuntimeError, match=message):
        _promote(arguments)

    output_dir = Path(arguments["output_dir"])
    assert not (output_dir / FACTS_NAME).exists()
    assert not (output_dir / MANIFEST_NAME).exists()


@pytest.mark.parametrize(
    "unsafe_value",
    [
        ["<article>raw source</article>"],
        ["/private/tmp/raw-source.html"],
        ["reviewer@example.com"],
    ],
)
def test_unsafe_candidate_values_never_enter_output(
    tmp_path: Path,
    unsafe_value: list[str],
) -> None:
    candidate = _pending_candidate(value=unsafe_value)
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )

    with pytest.raises(RuntimeError):
        _promote(arguments)

    output_dir = Path(arguments["output_dir"])
    assert not (output_dir / FACTS_NAME).exists()
    assert not (output_dir / MANIFEST_NAME).exists()


def test_decision_reason_and_local_input_paths_are_not_serialized(
    tmp_path: Path,
) -> None:
    candidate = _pending_candidate()
    decision = _approved_decision(candidate["candidate_id"])
    decision["reason"] = (
        "<article>review</article> /private/tmp/review.html "
        "reviewer@example.com"
    )
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[decision],
    )

    _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    output = (
        _published_facts_path(output_dir).read_bytes()
        + (output_dir / MANIFEST_NAME).read_bytes()
    )

    assert str(tmp_path).encode() not in output
    assert b"/private/tmp" not in output
    assert b"<article>" not in output
    assert b"reviewer@example.com" not in output
    assert "人工核对".encode() not in output


def test_manifest_points_to_sha_bound_immutable_facts_generation(
    tmp_path: Path,
) -> None:
    arguments = _promotion_inputs(tmp_path)

    report = _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    manifest = json.loads(
        (output_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    )
    expected_name = f"category_facts_v1.{report.facts_sha256}.jsonl"
    generation_path = output_dir / expected_name

    assert manifest["facts_file"] == expected_name
    assert _sha256(generation_path.read_bytes()) == report.facts_sha256
    assert not (output_dir / FACTS_NAME).exists()


def test_preexisting_different_generation_content_fails_closed(
    tmp_path: Path,
) -> None:
    probe_arguments = _promotion_inputs(tmp_path / "probe")
    probe_report = _promote(probe_arguments)
    arguments = _promotion_inputs(tmp_path / "target")
    output_dir = Path(arguments["output_dir"])
    output_dir.mkdir(parents=True)
    generation_path = output_dir / (
        f"category_facts_v1.{probe_report.facts_sha256}.jsonl"
    )
    generation_path.write_bytes(b"different existing content\n")

    module = _promotion_module()
    with pytest.raises(
        module.CategoryFactPromotionError,
        match="different content",
    ):
        _promote(arguments)

    assert not (output_dir / MANIFEST_NAME).exists()
    assert generation_path.read_bytes() == b"different existing content\n"


def test_preexisting_symlink_generation_fails_closed(
    tmp_path: Path,
) -> None:
    probe_arguments = _promotion_inputs(tmp_path / "probe")
    probe_report = _promote(probe_arguments)
    arguments = _promotion_inputs(tmp_path / "target")
    output_dir = Path(arguments["output_dir"])
    output_dir.mkdir(parents=True)
    generation_path = output_dir / (
        f"category_facts_v1.{probe_report.facts_sha256}.jsonl"
    )
    generation_path.symlink_to(
        _published_facts_path(Path(probe_arguments["output_dir"]))
    )

    module = _promotion_module()
    with pytest.raises(
        module.CategoryFactPromotionError,
        match="symlink",
    ):
        _promote(arguments)

    assert not (output_dir / MANIFEST_NAME).exists()
    assert generation_path.is_symlink()


def test_repeated_promotion_is_byte_identical_and_reuses_generation(
    tmp_path: Path,
) -> None:
    arguments = _promotion_inputs(tmp_path)

    first_report = _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    first_manifest = (output_dir / MANIFEST_NAME).read_bytes()
    first_facts = _published_facts_path(output_dir).read_bytes()
    second_report = _promote(arguments)
    generation_paths = sorted(
        output_dir.glob("category_facts_v1.*.jsonl")
    )

    assert second_report == first_report
    assert (output_dir / MANIFEST_NAME).read_bytes() == first_manifest
    assert _published_facts_path(output_dir).read_bytes() == first_facts
    assert len(generation_paths) == 1


def test_cleanup_removes_only_staging_and_preserves_generations(
    tmp_path: Path,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    published_generation = _published_facts_path(output_dir)
    published_bytes = published_generation.read_bytes()
    generation_staging = (
        output_dir / ".category-fact-generation.orphan.staging"
    )
    manifest_staging = (
        output_dir / ".category-fact-manifest.orphan.new"
    )
    generation_staging.write_bytes(b"unreferenced partial facts")
    manifest_staging.write_bytes(b"unreferenced partial manifest")

    _promote(arguments)

    assert not generation_staging.exists()
    assert not manifest_staging.exists()
    assert published_generation.read_bytes() == published_bytes


def test_unlocked_reader_never_observes_mixed_publication_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_arguments = _promotion_inputs(tmp_path)
    _promote(first_arguments)
    output_dir = Path(first_arguments["output_dir"])
    old_value = _load_published_snapshot(output_dir).facts[0].value

    candidate = _pending_candidate(value=["3N0"])
    second_arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )
    module = _promotion_module()
    real_replace = module.os.replace
    publication_window = threading.Event()
    release_writer = threading.Event()
    writer_errors: list[BaseException] = []

    def pause_before_manifest_commit(
        source: object,
        target: object,
    ) -> None:
        if Path(target) == output_dir / MANIFEST_NAME:
            publication_window.set()
            if not release_writer.wait(timeout=10):
                raise TimeoutError("reader did not inspect publication window")
        real_replace(source, target)

    def publish() -> None:
        try:
            _promote(second_arguments)
        except BaseException as exc:
            writer_errors.append(exc)

    monkeypatch.setattr(
        module.os,
        "replace",
        pause_before_manifest_commit,
    )
    writer = threading.Thread(target=publish, daemon=True)
    writer.start()
    assert publication_window.wait(timeout=10)
    try:
        during_publish = _load_published_snapshot(output_dir)
    finally:
        release_writer.set()
        writer.join(timeout=10)

    assert not writer.is_alive()
    assert not writer_errors
    assert during_publish.facts[0].value == old_value
    assert _load_published_snapshot(output_dir).facts[0].value == ["3N0"]


def test_sigkill_before_manifest_commit_keeps_old_generation_loadable(
    tmp_path: Path,
) -> None:
    first_arguments = _promotion_inputs(tmp_path)
    _promote(first_arguments)
    output_dir = Path(first_arguments["output_dir"])
    old_manifest = json.loads(
        (output_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    )
    old_facts_path = output_dir / str(old_manifest["facts_file"])
    old_facts = old_facts_path.read_bytes()

    candidate = _pending_candidate(value=["3N0"])
    interrupted = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )
    candidates_sha256 = str(interrupted["expected_candidates_sha256"])
    quarantine_sha256 = str(
        interrupted["expected_quarantine_sha256"]
    )
    decisions_sha256 = str(interrupted["expected_decisions_sha256"])
    decision_signature = str(interrupted["decision_signature"])
    decision_hmac_key = bytes(interrupted["decision_hmac_key"])
    script = f"""
import os
from pathlib import Path
import signal
import tools.guide_data.promote_approved_category_facts as promotion

real_replace = promotion.os.replace
manifest_path = Path({str(output_dir / MANIFEST_NAME)!r})

def kill_before_manifest_commit(source, target):
    if Path(target) == manifest_path:
        os.kill(os.getpid(), signal.SIGKILL)
    real_replace(source, target)

promotion.os.replace = kill_before_manifest_commit
promotion.promote_approved_category_facts(
    candidates_path={str(interrupted["candidates_path"])!r},
    quarantine_path={str(interrupted["quarantine_path"])!r},
    decisions_path={str(interrupted["decisions_path"])!r},
    output_dir={str(interrupted["output_dir"])!r},
    expected_candidates_sha256={candidates_sha256!r},
    expected_quarantine_sha256={quarantine_sha256!r},
    expected_decisions_sha256={decisions_sha256!r},
    decision_signature={decision_signature!r},
    decision_hmac_key={decision_hmac_key!r},
    canonical_manifest_path={str(CANONICAL_MANIFEST)!r},
    canonical_products_path={str(CANONICAL_PRODUCTS)!r},
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == -signal.SIGKILL
    loaded_after_kill = _load_published_snapshot(output_dir)
    assert loaded_after_kill.facts[0].value == ["2C0"]
    assert old_facts_path.read_bytes() == old_facts

    _promote(interrupted)
    assert _load_published_snapshot(output_dir).facts[0].value == ["3N0"]
    assert old_facts_path.read_bytes() == old_facts
    assert not list(output_dir.glob(".category-fact-generation.*.staging"))
    assert not list(output_dir.glob(".category-fact-manifest.*.new"))


def test_failed_manifest_commit_keeps_old_asset_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    facts_path = _published_facts_path(output_dir)
    manifest_path = output_dir / MANIFEST_NAME
    old_facts = facts_path.read_bytes()
    old_manifest = manifest_path.read_bytes()
    old_generations = set(output_dir.glob("category_facts_v1.*.jsonl"))

    candidate = _pending_candidate(value=["3N0"])
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )
    module = _promotion_module()
    real_replace = module.os.replace
    failed_once = False
    manifest_temp_modes: list[int] = []
    lock_modes: list[int] = []

    def fail_manifest_publish(source: object, target: object) -> None:
        nonlocal failed_once
        source_path = Path(source)
        target_path = Path(target)
        if target_path == manifest_path:
            manifest_temp_modes.append(
                stat.S_IMODE(source_path.stat().st_mode)
            )
            lock_modes.append(
                stat.S_IMODE((output_dir / LOCK_NAME).stat().st_mode)
            )
        if target_path == manifest_path and not failed_once:
            failed_once = True
            raise OSError("injected manifest publication failure")
        real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", fail_manifest_publish)

    with pytest.raises(
        OSError,
        match="injected manifest publication failure",
    ):
        _promote(arguments)

    assert facts_path.read_bytes() == old_facts
    assert manifest_path.read_bytes() == old_manifest
    assert _load_published_snapshot(output_dir).facts[0].value == ["2C0"]
    assert manifest_temp_modes and set(manifest_temp_modes) == {0o600}
    assert lock_modes and set(lock_modes) == {0o600}
    assert not (output_dir / JOURNAL_NAME).exists()
    assert not list(output_dir.glob(".category-fact-manifest.*.new"))
    assert len(
        set(output_dir.glob("category_facts_v1.*.jsonl"))
        - old_generations
    ) == 1


def test_directory_fsync_failure_after_manifest_swap_restores_old_asset_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    first_report = _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    manifest_path = output_dir / MANIFEST_NAME
    old_manifest = manifest_path.read_bytes()
    old_facts_path = _published_facts_path(output_dir)
    old_facts = old_facts_path.read_bytes()

    candidate = _pending_candidate(value=["3N0"])
    second_arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )
    module = _promotion_module()
    real_replace = module.os.replace
    real_fsync_directory = module._fsync_directory
    manifest_swapped = False
    injected = False

    def track_manifest_swap(source: object, target: object) -> None:
        nonlocal manifest_swapped
        real_replace(source, target)
        if Path(target) == manifest_path:
            manifest_swapped = True

    def fail_after_manifest_swap(path: Path) -> None:
        nonlocal injected
        if manifest_swapped and not injected:
            injected = True
            raise OSError("injected post-swap directory fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(module.os, "replace", track_manifest_swap)
    monkeypatch.setattr(module, "_fsync_directory", fail_after_manifest_swap)

    with pytest.raises(
        OSError,
        match="injected post-swap directory fsync failure",
    ):
        _promote(second_arguments)

    assert injected
    assert manifest_path.read_bytes() == old_manifest
    assert old_facts_path.read_bytes() == old_facts
    assert _published_facts_path(output_dir).read_bytes() == old_facts
    loaded = _load_published(
        output_dir,
        first_report.manifest_sha256,
    )
    assert loaded.facts[0].value == ["2C0"]


def test_post_swap_fsync_failure_reports_success_if_new_pointer_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    manifest_path = output_dir / MANIFEST_NAME

    candidate = _pending_candidate(value=["3N0"])
    second_arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )
    module = _promotion_module()
    real_replace = module.os.replace
    real_fsync_directory = module._fsync_directory
    manifest_replace_count = 0
    manifest_swapped = False
    fsync_injected = False

    def keep_new_manifest_on_rollback(
        source: object,
        target: object,
    ) -> None:
        nonlocal manifest_replace_count, manifest_swapped
        if Path(target) == manifest_path:
            manifest_replace_count += 1
            if manifest_replace_count > 1:
                raise OSError("injected manifest rollback failure")
        real_replace(source, target)
        if Path(target) == manifest_path:
            manifest_swapped = True

    def fail_after_manifest_swap(path: Path) -> None:
        nonlocal fsync_injected
        if manifest_swapped and not fsync_injected:
            fsync_injected = True
            raise OSError("injected post-swap directory fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(
        module.os,
        "replace",
        keep_new_manifest_on_rollback,
    )
    monkeypatch.setattr(module, "_fsync_directory", fail_after_manifest_swap)

    report = _promote(second_arguments)

    assert fsync_injected
    assert manifest_replace_count == 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["facts_sha256"] == report.facts_sha256
    assert manifest["manifest_sha256"] == report.manifest_sha256
    loaded = _load_published(output_dir, report.manifest_sha256)
    assert loaded.facts[0].value == ["3N0"]


def test_keyboard_interrupt_restores_old_asset_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    facts_path = _published_facts_path(output_dir)
    manifest_path = output_dir / MANIFEST_NAME
    old_facts = facts_path.read_bytes()
    old_manifest = manifest_path.read_bytes()

    candidate = _pending_candidate(value=["3N0"])
    arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )
    module = _promotion_module()
    real_replace = module.os.replace
    interrupted = False

    def interrupt_manifest_publish(source: object, target: object) -> None:
        nonlocal interrupted
        if (
            Path(target) == manifest_path
            and not interrupted
        ):
            interrupted = True
            raise KeyboardInterrupt
        real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", interrupt_manifest_publish)

    with pytest.raises(KeyboardInterrupt):
        _promote(arguments)

    assert facts_path.read_bytes() == old_facts
    assert manifest_path.read_bytes() == old_manifest
    assert _load_published_snapshot(output_dir).facts[0].value == ["2C0"]
    assert not (output_dir / JOURNAL_NAME).exists()


def test_next_run_reuses_generation_after_interrupted_manifest_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    _promote(arguments)
    output_dir = Path(arguments["output_dir"])
    facts_path = _published_facts_path(output_dir)
    manifest_path = output_dir / MANIFEST_NAME
    old_facts = facts_path.read_bytes()
    old_manifest = manifest_path.read_bytes()
    old_manifest_sha256 = str(
        json.loads(old_manifest)["manifest_sha256"]
    )

    candidate = _pending_candidate(value=["3N0"])
    interrupted_arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )
    module = _promotion_module()
    real_replace = module.os.replace

    def interrupt_before_manifest_swap(
        source: object,
        target: object,
    ) -> None:
        target_path = Path(target)
        if target_path == manifest_path:
            raise KeyboardInterrupt
        real_replace(source, target)

    monkeypatch.setattr(
        module.os,
        "replace",
        interrupt_before_manifest_swap,
    )
    with pytest.raises(KeyboardInterrupt):
        _promote(interrupted_arguments)
    assert not (output_dir / JOURNAL_NAME).exists()
    assert facts_path.read_bytes() == old_facts
    assert manifest_path.read_bytes() == old_manifest
    assert _load_published(
        output_dir,
        old_manifest_sha256,
    ).facts[0].value == ["2C0"]
    assert len(list(output_dir.glob("category_facts_v1.*.jsonl"))) == 2
    monkeypatch.setattr(module.os, "replace", real_replace)

    unknown_decision = _approved_decision("f" * 64)
    invalid_arguments = _promotion_inputs(
        tmp_path,
        decisions=[unknown_decision],
    )
    with pytest.raises(ValueError, match="unknown candidate"):
        _promote(invalid_arguments)

    assert facts_path.read_bytes() == old_facts
    assert manifest_path.read_bytes() == old_manifest
    assert not (output_dir / JOURNAL_NAME).exists()

    interrupted_arguments = _promotion_inputs(
        tmp_path,
        candidates=[candidate],
        decisions=[_approved_decision(candidate["candidate_id"])],
    )
    _promote(interrupted_arguments)
    assert _load_published_snapshot(output_dir).facts[0].value == ["3N0"]
    assert facts_path.read_bytes() == old_facts


def test_cli_publishes_loader_valid_assets_without_path_leaks(
    tmp_path: Path,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    command = _signed_cli_command(arguments)
    environment = dict(os.environ)
    environment["TASK7_DECISION_HMAC_KEY"] = DECISION_KEY.decode()

    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["fact_count"] == 1
    assert set(summary) == {
        "fact_count",
        "facts_sha256",
        "manifest_sha256",
    }
    assert str(tmp_path) not in completed.stdout
    assert str(tmp_path) not in completed.stderr
    assert DECISION_KEY.decode() not in completed.stdout
    assert DECISION_KEY.decode() not in completed.stderr
    published_output = (
        _published_facts_path(Path(arguments["output_dir"])).read_bytes()
        + (
            Path(arguments["output_dir"]) / MANIFEST_NAME
        ).read_bytes()
    )
    assert DECISION_KEY not in published_output
    loaded = _load_published(
        Path(arguments["output_dir"]),
        summary["manifest_sha256"],
    )
    assert len(loaded.facts) == 1


def test_cli_fails_closed_when_named_key_environment_is_missing(
    tmp_path: Path,
) -> None:
    arguments = _promotion_inputs(tmp_path)
    environment = dict(os.environ)
    environment.pop("TASK7_DECISION_HMAC_KEY", None)

    completed = subprocess.run(
        _signed_cli_command(arguments),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stderr) == {
        "error": "ValueError",
        "status": "failed",
    }
    assert not (Path(arguments["output_dir"]) / MANIFEST_NAME).exists()


def test_cli_has_no_raw_hmac_key_argument() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.promote_approved_category_facts",
            "--help",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--decision-key-env" in completed.stdout
    assert "--decision-hmac-key" not in completed.stdout
