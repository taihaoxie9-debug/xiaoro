from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
from pathlib import Path
import re
import shutil
import threading

import pytest

from app.guide.retrieval.approved_review_assets import (
    load_approved_review_assets,
)
from tools.guide_data.build_review_candidates import (
    build_review_candidates,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "guide" / "reviews"
PRODUCTION_ROOT = ROOT / "data" / "guide_review_sources"
PRODUCTION_MANIFEST = (
    PRODUCTION_ROOT / "approved_tmall_feed_reviews_v1_manifest.json"
)
PRODUCTION_SOURCES = (
    PRODUCTION_ROOT / "approved_tmall_feed_reviews_v1.jsonl"
)
PRODUCTION_AUDIT = (
    ROOT
    / "docs"
    / "audits"
    / "phase2-scenario-feedback"
    / "review_source_audit.md"
)
EXPECTED_MANIFEST_SHA256 = (
    "823c249166e93b4ab709b3423fa8a97a23e3ab3e7677e5d39d74abc21c165113"
)
EXPECTED_AUDIT_LOCATOR = (
    "docs/audits/phase2-scenario-feedback/review_source_audit.md"
)
AUDIT_BLOCK_START = "<!-- current-approved-catalog:start -->"
AUDIT_BLOCK_END = "<!-- current-approved-catalog:end -->"
DECISION_KEY = b"review-decision-key-material-32-bytes-minimum"
OTHER_DECISION_KEY = b"other-review-decision-key-material-32-bytes"


def _api():
    try:
        import tools.guide_data.promote_approved_reviews as promotion
    except ModuleNotFoundError:
        pytest.fail("approved review promotion tool is missing")
    return promotion


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _manifest_digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                key: item
                for key, item in value.items()
                if key != "manifest_sha256"
            }
        ).encode("utf-8")
    ).hexdigest()


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _candidate_assets(tmp_path: Path):
    input_root = tmp_path / "candidate-inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    html_path = input_root / "tmall_reviews_beta.html"
    html = html_path.read_text(encoding="utf-8")
    synthetic_candidate = """
    <article
      data-review-candidate
      data-feed-id="800000000003"
      data-item-id="333333333333"
      data-sku-id="444444444444"
    >
      <p data-review-content>synthetic fixture candidate</p>
    </article>
"""
    html_path.write_text(
        html.replace("</body>", synthetic_candidate + "  </body>"),
        encoding="utf-8",
    )
    _refresh_manifest_source_sha(input_root, html_path.name)
    return build_review_candidates(
        source_manifest_path=input_root / "source_manifest.json",
        output_root=tmp_path / "candidate-output",
    )


def _refresh_manifest_source_sha(
    input_root: Path,
    source_name: str,
) -> None:
    manifest_path = input_root / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = next(
        row for row in manifest["sources"] if row["path"] == source_name
    )
    source["sha256"] = _raw_sha256(input_root / source_name)
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )


def _candidate_assets_with_invalid_metadata(tmp_path: Path):
    input_root = tmp_path / "candidate-inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    html_path = input_root / "tmall_reviews_alpha.html"
    html = html_path.read_text(encoding="utf-8")
    html_path.write_text(
        html.replace(
            "  </body>",
            """
    <article
      data-review-candidate
      data-feed-id="0"
      data-item-id="111111111111"
      data-sku-id="222222222222"
    >
      <p data-review-content>无香精，肤感温和。</p>
    </article>
  </body>""",
        ),
        encoding="utf-8",
    )
    _refresh_manifest_source_sha(input_root, html_path.name)
    return build_review_candidates(
        source_manifest_path=input_root / "source_manifest.json",
        output_root=tmp_path / "candidate-output",
    )


def _production_copies(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path]:
    asset_root = tmp_path / "published"
    asset_root.mkdir(parents=True)
    manifest_path = asset_root / PRODUCTION_MANIFEST.name
    sources_path = asset_root / PRODUCTION_SOURCES.name
    audit_path = asset_root / "review_source_audit.md"
    shutil.copy2(PRODUCTION_MANIFEST, manifest_path)
    shutil.copy2(PRODUCTION_SOURCES, sources_path)
    shutil.copy2(PRODUCTION_AUDIT, audit_path)
    return (
        manifest_path,
        sources_path,
        audit_path,
        asset_root / ".review-promotion.lock",
    )


def _decision(candidate_id: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "decision": "approved",
        "reason": (
            "脱敏 fixture 中的消费者原文已核对商品归属和隔离规则。"
        ),
        "reviewed_at": "2026-08-10T08:00:00Z",
        "reviewer": "human-reviewer-fixture-01",
    }


def _write_decisions(
    path: Path,
    decisions: list[dict[str, object]],
) -> Path:
    path.write_text(
        "".join(
            f"{_canonical_json(decision)}\n"
            for decision in decisions
        ),
        encoding="utf-8",
    )
    return path


def _write_rows(
    path: Path,
    rows: list[dict[str, object]],
) -> Path:
    path.write_text(
        "".join(f"{_canonical_json(row)}\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _decision_signature(
    *,
    decisions_path: Path,
    candidate_manifest_sha256: str,
    key: bytes = DECISION_KEY,
) -> str:
    decisions = _jsonl(decisions_path)
    decision_manifest = {
        "decision_count": len(decisions),
        "decisions": decisions,
        "schema_version": "approved-review-decision-manifest-v1",
    }
    payload = {
        "candidate_manifest_raw_sha256": candidate_manifest_sha256,
        "decision_manifest_sha256": hashlib.sha256(
            _canonical_json(decision_manifest).encode("utf-8")
        ).hexdigest(),
        "schema_version": "approved-review-decision-signature-v1",
    }
    return hmac.new(
        key,
        _canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _promote_reviews(**arguments):
    decisions_path = Path(arguments["decisions_path"])
    arguments.setdefault(
        "expected_decisions_sha256",
        _raw_sha256(decisions_path),
    )
    if any(
        row.get("decision") == "approved"
        for row in _jsonl(decisions_path)
    ):
        arguments.setdefault("decision_hmac_key", DECISION_KEY)
        arguments.setdefault(
            "decision_signature",
            _decision_signature(
                decisions_path=decisions_path,
                candidate_manifest_sha256=str(
                    arguments["expected_candidate_manifest_sha256"]
                ),
            ),
        )
    return _api().promote_approved_reviews(**arguments)


def _active_generation_paths(
    *,
    manifest_path: Path,
    configured_sources_path: Path,
    configured_audit_path: Path,
) -> tuple[Path, Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return (
        configured_sources_path.parent / str(manifest["sources_file"]),
        configured_audit_path.parent
        / Path(str(manifest["audit_locator"])).name,
    )


def _move_quarantine_row_and_rehash(
    candidates,
    *,
    quarantine_reason: str,
) -> dict[str, object]:
    pending_rows = _jsonl(candidates.pending)
    quarantine_rows = _jsonl(candidates.quarantine)
    moved = next(
        row
        for row in quarantine_rows
        if quarantine_reason in row["quarantine_reasons"]
    )
    quarantine_rows.remove(moved)
    moved["status"] = "pending"
    moved["quarantine_reasons"] = []
    pending_rows.append(moved)
    _write_rows(
        candidates.pending,
        sorted(pending_rows, key=lambda row: str(row["candidate_id"])),
    )
    _write_rows(
        candidates.quarantine,
        sorted(
            quarantine_rows,
            key=lambda row: str(row["candidate_id"]),
        ),
    )
    manifest = json.loads(
        candidates.manifest.read_text(encoding="utf-8")
    )
    manifest["fixture_counts"]["pending_candidates"] = len(pending_rows)
    manifest["fixture_counts"]["quarantine_candidates"] = len(
        quarantine_rows
    )
    manifest["pending_sha256"] = hashlib.sha256(
        candidates.pending.read_bytes()
    ).hexdigest()
    manifest["quarantine_sha256"] = hashlib.sha256(
        candidates.quarantine.read_bytes()
    ).hexdigest()
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    candidates.manifest.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return moved


def _promote(
    tmp_path: Path,
    *,
    decisions: list[dict[str, object]],
):
    candidates = _candidate_assets(tmp_path)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )
    decisions_path = _write_decisions(
        tmp_path / "decisions.jsonl",
        decisions,
    )
    result = _promote_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=decisions_path,
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        lock_path=lock_path,
    )
    return (
        result,
        candidates,
        manifest_path,
        sources_path,
        audit_path,
        lock_path,
    )


def test_promotion_api_requires_external_candidate_manifest_digest(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    with pytest.raises(
        TypeError,
        match="expected_candidate_manifest_sha256",
    ):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            decisions_path=_write_decisions(
                tmp_path / "decisions.jsonl",
                [],
            ),
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_promotion_cli_requires_external_candidate_manifest_digest() -> None:
    with pytest.raises(SystemExit) as exc_info:
        _api()._build_parser().parse_args(
            [
                "--pending",
                "pending.jsonl",
                "--quarantine",
                "quarantine.jsonl",
                "--candidate-manifest",
                "candidate-manifest.json",
                "--decisions",
                "decisions.jsonl",
                "--manifest",
                "approved-manifest.json",
                "--sources",
                "approved-sources.jsonl",
                "--audit",
                "audit.md",
                "--expected-manifest-sha256",
                EXPECTED_MANIFEST_SHA256,
                "--lock",
                ".promotion.lock",
            ]
        )

    assert exc_info.value.code == 2


def test_promotion_api_requires_external_decisions_digest(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    with pytest.raises(TypeError, match="expected_decisions_sha256"):
        _api().promote_approved_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=_write_decisions(
                tmp_path / "decisions.jsonl",
                [],
            ),
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_promotion_cli_requires_external_decisions_digest() -> None:
    with pytest.raises(SystemExit) as exc_info:
        _api()._build_parser().parse_args(
            [
                "--pending",
                "pending.jsonl",
                "--quarantine",
                "quarantine.jsonl",
                "--candidate-manifest",
                "candidate-manifest.json",
                "--expected-candidate-manifest-sha256",
                "0" * 64,
                "--decisions",
                "decisions.jsonl",
                "--manifest",
                "approved-manifest.json",
                "--sources",
                "approved-sources.jsonl",
                "--audit",
                "audit.md",
                "--expected-manifest-sha256",
                EXPECTED_MANIFEST_SHA256,
                "--lock",
                ".promotion.lock",
            ]
        )

    assert exc_info.value.code == 2


def test_promotion_rejects_stale_external_decisions_digest(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )
    decisions_path = _write_decisions(
        tmp_path / "decisions.jsonl",
        [],
    )

    with pytest.raises(ValueError, match="decision queue SHA-256 mismatch"):
        _api().promote_approved_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=decisions_path,
            expected_decisions_sha256="0" * 64,
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_promotion_rejects_stale_external_candidate_manifest_digest(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    locked_digest = _raw_sha256(candidates.manifest)
    candidates.manifest.write_bytes(
        candidates.manifest.read_bytes() + b"\n"
    )
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    with pytest.raises(
        ValueError,
        match="candidate manifest raw SHA-256 mismatch",
    ):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=locked_digest,
            decisions_path=_write_decisions(
                tmp_path / "decisions.jsonl",
                [],
            ),
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_promotion_accepts_valid_external_candidate_manifest_digest(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    result = _promote_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=_write_decisions(
            tmp_path / "decisions.jsonl",
            [],
        ),
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        lock_path=lock_path,
    )

    assert result.changed is False
    assert result.approved_source_count == 6


@pytest.mark.parametrize(
    ("key", "signature_mode", "message"),
    [
        (None, "valid", "decision HMAC key"),
        (DECISION_KEY, "missing", "decision batch signature"),
        (OTHER_DECISION_KEY, "valid", "signature mismatch"),
    ],
)
def test_nonempty_approval_rejects_missing_signature_and_wrong_key(
    tmp_path: Path,
    key: bytes | None,
    signature_mode: str,
    message: str,
) -> None:
    candidates = _candidate_assets(tmp_path)
    candidate_id = str(_jsonl(candidates.pending)[0]["candidate_id"])
    decisions_path = _write_decisions(
        tmp_path / "decisions.jsonl",
        [_decision(candidate_id)],
    )
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )
    candidate_manifest_sha256 = _raw_sha256(candidates.manifest)
    signature = (
        _decision_signature(
            decisions_path=decisions_path,
            candidate_manifest_sha256=candidate_manifest_sha256,
        )
        if signature_mode == "valid"
        else None
    )

    with pytest.raises(ValueError, match=message):
        _api().promote_approved_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=(
                candidate_manifest_sha256
            ),
            decisions_path=decisions_path,
            expected_decisions_sha256=_raw_sha256(decisions_path),
            decision_signature=signature,
            decision_hmac_key=key,
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_signature_rejects_coordinated_candidate_and_decision_tampering(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    pending_rows = _jsonl(candidates.pending)
    candidate_id = str(pending_rows[0]["candidate_id"])
    decisions_path = _write_decisions(
        tmp_path / "decisions.jsonl",
        [_decision(candidate_id)],
    )
    original_signature = _decision_signature(
        decisions_path=decisions_path,
        candidate_manifest_sha256=_raw_sha256(candidates.manifest),
    )

    tampered_content = str(pending_rows[0]["content"]) + " 补充核验内容。"
    pending_rows[0]["content"] = tampered_content
    pending_rows[0]["content_sha256"] = hashlib.sha256(
        tampered_content.encode("utf-8")
    ).hexdigest()
    _write_rows(candidates.pending, pending_rows)
    candidate_manifest = json.loads(
        candidates.manifest.read_text(encoding="utf-8")
    )
    candidate_manifest["pending_sha256"] = _raw_sha256(
        candidates.pending
    )
    candidate_manifest["manifest_sha256"] = _manifest_digest(
        candidate_manifest
    )
    candidates.manifest.write_text(
        _canonical_json(candidate_manifest) + "\n",
        encoding="utf-8",
    )
    forged_decision = _decision(candidate_id)
    forged_decision.update(
        {
            "reason": "自动化改写后的伪造批准理由。",
            "reviewed_at": "2026-08-10T10:00:00Z",
            "reviewer": "forged-reviewer",
        }
    )
    _write_decisions(decisions_path, [forged_decision])
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    with pytest.raises(ValueError, match="signature mismatch"):
        _api().promote_approved_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=decisions_path,
            expected_decisions_sha256=_raw_sha256(decisions_path),
            decision_signature=original_signature,
            decision_hmac_key=DECISION_KEY,
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_cli_exposes_only_environment_hmac_key_input() -> None:
    option_strings = {
        option
        for action in _api()._build_parser()._actions
        for option in action.option_strings
    }

    assert "--decision-signature" in option_strings
    assert "--decision-key-env" in option_strings
    assert "--decision-key" not in option_strings
    assert "--decision-hmac-key" not in option_strings


@pytest.mark.parametrize(
    "missing_field",
    ("decision", "reviewer", "reviewed_at", "reason"),
)
def test_promotion_requires_complete_human_decision(
    tmp_path: Path,
    missing_field: str,
) -> None:
    candidates = _candidate_assets(tmp_path)
    candidate_id = str(_jsonl(candidates.pending)[0]["candidate_id"])
    decision = _decision(candidate_id)
    decision.pop(missing_field)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    with pytest.raises(ValueError, match=missing_field):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=_write_decisions(
                tmp_path / "decisions.jsonl",
                [decision],
            ),
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_promotion_requires_timezone_aware_review_time(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    candidate_id = str(_jsonl(candidates.pending)[0]["candidate_id"])
    decision = _decision(candidate_id)
    decision["reviewed_at"] = "2026-08-10T08:00:00"
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=_write_decisions(
                tmp_path / "decisions.jsonl",
                [decision],
            ),
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_promotion_rejects_unknown_and_quarantined_candidates(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    quarantined_id = str(
        _jsonl(candidates.quarantine)[0]["candidate_id"]
    )
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    for candidate_id, message in (
        ("review_missing_candidate", "unknown candidate"),
        (quarantined_id, "quarantined candidate"),
    ):
        with pytest.raises(ValueError, match=message):
            _promote_reviews(
                pending_path=candidates.pending,
                quarantine_path=candidates.quarantine,
                candidate_manifest_path=candidates.manifest,
                expected_candidate_manifest_sha256=_raw_sha256(
                    candidates.manifest
                ),
                decisions_path=_write_decisions(
                    tmp_path / f"{message}.jsonl",
                    [_decision(candidate_id)],
                ),
                manifest_path=manifest_path,
                sources_path=sources_path,
                audit_path=audit_path,
                expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
                lock_path=lock_path,
            )


@pytest.mark.parametrize(
    "quarantine_reason",
    ("marketing", "pii", "qa", "cross_sku"),
)
def test_promotion_rejects_reclassified_candidate_queue_tampering(
    tmp_path: Path,
    quarantine_reason: str,
) -> None:
    candidates = _candidate_assets(tmp_path)
    pending_rows = _jsonl(candidates.pending)
    quarantine_rows = _jsonl(candidates.quarantine)
    moved = next(
        row
        for row in quarantine_rows
        if quarantine_reason in row["quarantine_reasons"]
    )
    quarantine_rows.remove(moved)
    moved["status"] = "pending"
    moved["quarantine_reasons"] = []
    pending_rows.append(moved)
    _write_rows(
        candidates.pending,
        sorted(pending_rows, key=lambda row: str(row["candidate_id"])),
    )
    _write_rows(
        candidates.quarantine,
        sorted(
            quarantine_rows,
            key=lambda row: str(row["candidate_id"]),
        ),
    )
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    with pytest.raises(
        ValueError,
        match="candidate pending SHA-256 mismatch",
    ):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=_write_decisions(
                tmp_path / "decisions.jsonl",
                [_decision(str(moved["candidate_id"]))],
            ),
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


@pytest.mark.parametrize(
    "quarantine_reason",
    ("qa", "marketing", "invalid_metadata"),
)
def test_promotion_rejects_coordinated_quarantine_rehash(
    tmp_path: Path,
    quarantine_reason: str,
) -> None:
    if quarantine_reason == "invalid_metadata":
        candidates = _candidate_assets_with_invalid_metadata(tmp_path)
    else:
        candidates = _candidate_assets(tmp_path)
    moved = _move_quarantine_row_and_rehash(
        candidates,
        quarantine_reason=quarantine_reason,
    )
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    with pytest.raises(ValueError, match="quarantine classification"):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=_write_decisions(
                tmp_path / "decisions.jsonl",
                [_decision(str(moved["candidate_id"]))],
            ),
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_promotion_rejects_fixture_relabelled_as_historical_reproduced(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    candidate_manifest = json.loads(
        candidates.manifest.read_text(encoding="utf-8")
    )
    candidate_manifest["provenance_status"] = "historical_reproduced"
    candidate_manifest["historical_counts"]["status"] = "rerun"
    candidate_manifest["manifest_sha256"] = _manifest_digest(
        candidate_manifest
    )
    candidates.manifest.write_text(
        _canonical_json(candidate_manifest) + "\n",
        encoding="utf-8",
    )
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    with pytest.raises(
        ValueError,
        match="historical candidate provenance mismatch",
    ):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=_write_decisions(
                tmp_path / "decisions.jsonl",
                [],
            ),
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )


def test_promotion_accepts_source_incomplete_candidate_manifest(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    candidate_manifest = json.loads(
        candidates.manifest.read_text(encoding="utf-8")
    )
    candidate_manifest["provenance_status"] = "source_incomplete"
    candidate_manifest["historical_counts"]["status"] = "not_rerun"
    candidate_manifest["manifest_sha256"] = _manifest_digest(
        candidate_manifest
    )
    candidates.manifest.write_text(
        _canonical_json(candidate_manifest) + "\n",
        encoding="utf-8",
    )
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    result = _promote_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=_write_decisions(
            tmp_path / "decisions.jsonl",
            [],
        ),
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        lock_path=lock_path,
    )

    assert result.changed is False
    assert result.approved_source_count == 6


def test_review_promotion_source_has_no_retired_provenance_semantics() -> None:
    module = _api()
    source = Path(module.__file__).read_text(encoding="utf-8")
    retired_term = "locked_" + "originals"

    assert retired_term not in source


def test_promotion_accepts_manifest_locked_empty_content_quarantine(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "candidate-inputs"
    shutil.copytree(FIXTURE_ROOT, input_root)
    html_path = input_root / "tmall_reviews_alpha.html"
    html = html_path.read_text(encoding="utf-8")
    html_path.write_text(
        html.replace(
            "  </body>",
            """
    <article
      data-review-candidate
      data-feed-id="700000000006"
      data-item-id="111111111111"
      data-sku-id="222222222222"
    >
      <p data-review-content>   </p>
    </article>
  </body>""",
        ),
        encoding="utf-8",
    )
    _refresh_manifest_source_sha(input_root, html_path.name)
    candidates = build_review_candidates(
        source_manifest_path=input_root / "source_manifest.json",
        output_root=tmp_path / "candidate-output",
    )
    assert any(
        "empty_content" in row["quarantine_reasons"]
        for row in _jsonl(candidates.quarantine)
    )
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    result = _promote_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=_write_decisions(
            tmp_path / "decisions.jsonl",
            [],
        ),
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        lock_path=lock_path,
    )

    assert result.changed is False
    assert result.approved_source_count == 6


def test_no_new_decisions_is_byte_for_byte_noop_for_existing_six(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )
    before = {
        path: path.read_bytes()
        for path in (manifest_path, sources_path, audit_path)
    }

    result = _promote_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=_write_decisions(
            tmp_path / "decisions.jsonl",
            [],
        ),
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        lock_path=lock_path,
    )

    assert result.changed is False
    assert result.approved_source_count == 6
    assert result.manifest_sha256 == EXPECTED_MANIFEST_SHA256
    assert {
        path: path.read_bytes()
        for path in (manifest_path, sources_path, audit_path)
    } == before
    loaded = load_approved_review_assets(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
    )
    assert len(loaded.evidence) == 6


def test_new_fixture_approval_preserves_grandfathered_rows(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    pending = _jsonl(candidates.pending)
    candidate_id = str(pending[0]["candidate_id"])
    existing_rows = _jsonl(PRODUCTION_SOURCES)

    (
        result,
        _,
        manifest_path,
        sources_path,
        audit_path,
        _,
    ) = _promote(
        tmp_path / "promotion",
        decisions=[_decision(candidate_id)],
    )

    assert result.changed is True
    assert result.approved_source_count == 7
    active_sources, active_audit = _active_generation_paths(
        manifest_path=manifest_path,
        configured_sources_path=sources_path,
        configured_audit_path=audit_path,
    )
    loaded = load_approved_review_assets(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=result.manifest_sha256,
    )
    assert len(loaded.evidence) == 7
    assert candidate_id in {item.source_id for item in loaded.evidence}
    output_rows = _jsonl(active_sources)
    by_id = {str(row["source_id"]): row for row in output_rows}
    for row in existing_rows:
        assert by_id[str(row["source_id"])] == row
        assert "reviewer" not in by_id[str(row["source_id"])]
        assert "reviewed_at" not in by_id[str(row["source_id"])]
        assert "reason" not in by_id[str(row["source_id"])]

    audit_text = active_audit.read_text(encoding="utf-8")
    block = audit_text.split(AUDIT_BLOCK_START, 1)[1].split(
        AUDIT_BLOCK_END,
        1,
    )[0]
    current = json.loads(
        block.removeprefix("\n```json\n").removesuffix("```\n")
    )
    assert current["approved_source_count"] == 7
    assert current["approved_product_count"] == 4
    assert current["manifest_sha256"] == result.manifest_sha256
    assert current["sources_sha256"] == hashlib.sha256(
        active_sources.read_bytes()
    ).hexdigest()
    assert current["grandfathered_source_count"] == 6
    assert current["promotion_decisions"] == [
        {
            "decision": "approved",
            "reason": (
                "脱敏 fixture 中的消费者原文已核对商品归属和隔离规则。"
            ),
            "reviewed_at": "2026-08-10T08:00:00Z",
            "reviewer": "human-reviewer-fixture-01",
            "source_id": candidate_id,
        }
    ]
    assert not {
        str(row["source_id"]) for row in existing_rows
    } & {
        str(decision["source_id"])
        for decision in current["promotion_decisions"]
    }


def test_manifest_points_to_immutable_sources_and_audit_generations(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    candidate_id = str(_jsonl(candidates.pending)[0]["candidate_id"])

    (
        result,
        _,
        manifest_path,
        sources_path,
        audit_path,
        _,
    ) = _promote(
        tmp_path / "promotion",
        decisions=[_decision(candidate_id)],
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    active_sources, active_audit = _active_generation_paths(
        manifest_path=manifest_path,
        configured_sources_path=sources_path,
        configured_audit_path=audit_path,
    )
    sources_sha256 = hashlib.sha256(
        active_sources.read_bytes()
    ).hexdigest()

    assert manifest["sources_file"] == (
        f"{sources_path.stem}.{sources_sha256}{sources_path.suffix}"
    )
    assert Path(str(manifest["audit_locator"])).parent == Path(
        EXPECTED_AUDIT_LOCATOR
    ).parent
    assert re.fullmatch(
        rf"{re.escape(audit_path.stem)}\.[0-9a-f]{{64}}"
        rf"{re.escape(audit_path.suffix)}",
        active_audit.name,
    )
    assert active_sources.is_file()
    assert active_audit.is_file()
    assert not active_sources.is_symlink()
    assert not active_audit.is_symlink()
    assert sources_path.read_bytes() == PRODUCTION_SOURCES.read_bytes()
    assert audit_path.read_bytes() == PRODUCTION_AUDIT.read_bytes()
    assert result.generation_atomic is True


def test_repeated_promotion_reuses_identical_generations(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    candidate_id = str(_jsonl(candidates.pending)[0]["candidate_id"])
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )
    decisions_path = _write_decisions(
        tmp_path / "decisions.jsonl",
        [_decision(candidate_id)],
    )
    common = {
        "pending_path": candidates.pending,
        "quarantine_path": candidates.quarantine,
        "candidate_manifest_path": candidates.manifest,
        "expected_candidate_manifest_sha256": _raw_sha256(
            candidates.manifest
        ),
        "decisions_path": decisions_path,
        "expected_decisions_sha256": _raw_sha256(decisions_path),
        "manifest_path": manifest_path,
        "sources_path": sources_path,
        "audit_path": audit_path,
        "lock_path": lock_path,
    }
    first = _promote_reviews(
        **common,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
    )
    first_manifest = manifest_path.read_bytes()
    active_sources, active_audit = _active_generation_paths(
        manifest_path=manifest_path,
        configured_sources_path=sources_path,
        configured_audit_path=audit_path,
    )
    first_sources = active_sources.read_bytes()
    first_audit = active_audit.read_bytes()

    second = _api().promote_approved_reviews(
        **common,
        expected_manifest_sha256=first.manifest_sha256,
    )

    assert second.changed is False
    assert second.manifest_sha256 == first.manifest_sha256
    assert manifest_path.read_bytes() == first_manifest
    assert active_sources.read_bytes() == first_sources
    assert active_audit.read_bytes() == first_audit
    assert list(sources_path.parent.glob(f"{sources_path.stem}.*.jsonl")) == [
        active_sources
    ]
    assert list(audit_path.parent.glob(f"{audit_path.stem}.*.md")) == [
        active_audit
    ]


@pytest.mark.parametrize(
    ("generation_kind", "preexisting_kind", "message"),
    [
        ("sources", "conflict", "different content"),
        ("audit", "symlink", "symlink"),
    ],
)
def test_preexisting_conflicting_or_symlink_generation_fails_closed(
    tmp_path: Path,
    generation_kind: str,
    preexisting_kind: str,
    message: str,
) -> None:
    target = tmp_path / "target"
    candidates = _candidate_assets(target)
    candidate_id = str(_jsonl(candidates.pending)[0]["candidate_id"])
    probe = tmp_path / "probe"
    (
        _,
        _,
        probe_manifest,
        probe_sources,
        probe_audit,
        _,
    ) = _promote(
        probe,
        decisions=[_decision(candidate_id)],
    )
    probe_active = _active_generation_paths(
        manifest_path=probe_manifest,
        configured_sources_path=probe_sources,
        configured_audit_path=probe_audit,
    )

    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(target)
    )
    before_manifest = manifest_path.read_bytes()
    configured = (
        sources_path if generation_kind == "sources" else audit_path
    )
    probe_generation = (
        probe_active[0] if generation_kind == "sources" else probe_active[1]
    )
    preexisting = configured.parent / probe_generation.name
    if preexisting_kind == "conflict":
        preexisting.write_bytes(b"preexisting conflicting generation\n")
    else:
        preexisting.symlink_to(probe_generation)
    decisions_path = _write_decisions(
        target / "decisions.jsonl",
        [_decision(candidate_id)],
    )

    with pytest.raises(ValueError, match=message):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=decisions_path,
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
            lock_path=lock_path,
        )

    assert manifest_path.read_bytes() == before_manifest
    if preexisting_kind == "conflict":
        assert preexisting.read_bytes() == (
            b"preexisting conflicting generation\n"
        )
    else:
        assert preexisting.is_symlink()


def test_unlocked_reader_never_observes_mixed_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = _candidate_assets(tmp_path)
    pending = _jsonl(candidates.pending)
    assert len(pending) >= 2
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )

    first_decisions = _write_decisions(
        tmp_path / "first-decisions.jsonl",
        [_decision(str(pending[0]["candidate_id"]))],
    )
    first = _promote_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=first_decisions,
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        lock_path=lock_path,
    )
    old_manifest = manifest_path.read_bytes()
    old_sources_path, old_audit_path = _active_generation_paths(
        manifest_path=manifest_path,
        configured_sources_path=sources_path,
        configured_audit_path=audit_path,
    )
    old_sources = old_sources_path.read_bytes()
    old_audit = old_audit_path.read_bytes()

    second_decisions = _write_decisions(
        tmp_path / "second-decisions.jsonl",
        [_decision(str(pending[1]["candidate_id"]))],
    )
    module = _api()
    real_replace = module.os.replace
    publication_window = threading.Event()
    release_writer = threading.Event()
    writer_results: list[object] = []
    writer_errors: list[BaseException] = []

    def pause_before_manifest_commit(source: object, target: object) -> None:
        if Path(target) == manifest_path:
            publication_window.set()
            if not release_writer.wait(timeout=10):
                raise TimeoutError("reader did not inspect publication window")
        real_replace(source, target)

    def publish() -> None:
        try:
            writer_results.append(
                _promote_reviews(
                    pending_path=candidates.pending,
                    quarantine_path=candidates.quarantine,
                    candidate_manifest_path=candidates.manifest,
                    expected_candidate_manifest_sha256=_raw_sha256(
                        candidates.manifest
                    ),
                    decisions_path=second_decisions,
                    manifest_path=manifest_path,
                    sources_path=sources_path,
                    audit_path=audit_path,
                    expected_manifest_sha256=first.manifest_sha256,
                    lock_path=lock_path,
                )
            )
        except BaseException as exc:
            writer_errors.append(exc)

    monkeypatch.setattr(module.os, "replace", pause_before_manifest_commit)
    writer = threading.Thread(target=publish, daemon=True)
    writer.start()
    assert publication_window.wait(timeout=10)
    try:
        during = load_approved_review_assets(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=first.manifest_sha256,
        )
        assert manifest_path.read_bytes() == old_manifest
        assert old_sources_path.read_bytes() == old_sources
        assert old_audit_path.read_bytes() == old_audit
    finally:
        release_writer.set()
        writer.join(timeout=10)

    assert not writer.is_alive()
    assert not writer_errors
    assert len(writer_results) == 1
    assert len(during.evidence) == 7
    published = writer_results[0]
    after = load_approved_review_assets(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=published.manifest_sha256,
    )
    assert len(after.evidence) == 8


def test_system_exit_before_manifest_commit_keeps_old_generation_loadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = _candidate_assets(tmp_path)
    pending = _jsonl(candidates.pending)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )
    first_decisions = _write_decisions(
        tmp_path / "first-decisions.jsonl",
        [_decision(str(pending[0]["candidate_id"]))],
    )
    first = _promote_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=first_decisions,
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        lock_path=lock_path,
    )
    old_manifest = manifest_path.read_bytes()
    old_generations = _active_generation_paths(
        manifest_path=manifest_path,
        configured_sources_path=sources_path,
        configured_audit_path=audit_path,
    )
    old_generation_bytes = tuple(
        path.read_bytes() for path in old_generations
    )
    second_decisions = _write_decisions(
        tmp_path / "second-decisions.jsonl",
        [_decision(str(pending[1]["candidate_id"]))],
    )
    module = _api()
    real_replace = module.os.replace

    def exit_before_manifest_commit(source: object, target: object) -> None:
        if Path(target) == manifest_path:
            raise SystemExit("simulated process termination")
        real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", exit_before_manifest_commit)
    with pytest.raises(SystemExit, match="simulated process termination"):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=second_decisions,
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=first.manifest_sha256,
            lock_path=lock_path,
        )

    assert manifest_path.read_bytes() == old_manifest
    assert tuple(
        path.read_bytes() for path in old_generations
    ) == old_generation_bytes
    loaded = load_approved_review_assets(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=first.manifest_sha256,
    )
    assert len(loaded.evidence) == 7
    assert not lock_path.with_name(
        f"{lock_path.name}.journal.json"
    ).exists()


def test_next_run_reuses_orphan_generations_without_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = _candidate_assets(tmp_path)
    pending = _jsonl(candidates.pending)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )
    first_decisions = _write_decisions(
        tmp_path / "first-decisions.jsonl",
        [_decision(str(pending[0]["candidate_id"]))],
    )
    first = _promote_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=first_decisions,
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        lock_path=lock_path,
    )
    second_decisions = _write_decisions(
        tmp_path / "second-decisions.jsonl",
        [_decision(str(pending[1]["candidate_id"]))],
    )
    module = _api()
    real_replace = module.os.replace

    def exit_before_manifest_commit(source: object, target: object) -> None:
        if Path(target) == manifest_path:
            raise SystemExit("simulated process termination")
        real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", exit_before_manifest_commit)
    with pytest.raises(SystemExit):
        _promote_reviews(
            pending_path=candidates.pending,
            quarantine_path=candidates.quarantine,
            candidate_manifest_path=candidates.manifest,
            expected_candidate_manifest_sha256=_raw_sha256(
                candidates.manifest
            ),
            decisions_path=second_decisions,
            manifest_path=manifest_path,
            sources_path=sources_path,
            audit_path=audit_path,
            expected_manifest_sha256=first.manifest_sha256,
            lock_path=lock_path,
        )
    orphan_sources = set(
        sources_path.parent.glob(f"{sources_path.stem}.*.jsonl")
    )
    orphan_audits = set(
        audit_path.parent.glob(f"{audit_path.stem}.*.md")
    )
    orphan_inodes = {
        path: path.stat().st_ino
        for path in orphan_sources | orphan_audits
    }
    monkeypatch.setattr(module.os, "replace", real_replace)

    second = _promote_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=second_decisions,
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=first.manifest_sha256,
        lock_path=lock_path,
    )

    assert {
        path: path.stat().st_ino
        for path in orphan_inodes
    } == orphan_inodes
    assert not lock_path.with_name(
        f"{lock_path.name}.journal.json"
    ).exists()
    loaded = load_approved_review_assets(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=second.manifest_sha256,
    )
    assert len(loaded.evidence) == 8


def test_rejected_only_decisions_do_not_require_hmac(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    candidate_id = str(_jsonl(candidates.pending)[0]["candidate_id"])
    decision = _decision(candidate_id)
    decision["decision"] = "rejected"
    decisions_path = _write_decisions(
        tmp_path / "decisions.jsonl",
        [decision],
    )
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )
    before = tuple(
        path.read_bytes()
        for path in (manifest_path, sources_path, audit_path)
    )

    result = _api().promote_approved_reviews(
        pending_path=candidates.pending,
        quarantine_path=candidates.quarantine,
        candidate_manifest_path=candidates.manifest,
        expected_candidate_manifest_sha256=_raw_sha256(
            candidates.manifest
        ),
        decisions_path=decisions_path,
        expected_decisions_sha256=_raw_sha256(decisions_path),
        manifest_path=manifest_path,
        sources_path=sources_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        lock_path=lock_path,
    )

    assert result.changed is False
    assert tuple(
        path.read_bytes()
        for path in (manifest_path, sources_path, audit_path)
    ) == before


def test_publication_lock_rejects_a_concurrent_promoter(
    tmp_path: Path,
) -> None:
    candidates = _candidate_assets(tmp_path)
    manifest_path, sources_path, audit_path, lock_path = (
        _production_copies(tmp_path)
    )
    lock_path.touch(mode=0o600)

    with lock_path.open("r+b") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="publication lock"):
            _promote_reviews(
                pending_path=candidates.pending,
                quarantine_path=candidates.quarantine,
                candidate_manifest_path=candidates.manifest,
                expected_candidate_manifest_sha256=_raw_sha256(
                    candidates.manifest
                ),
                decisions_path=_write_decisions(
                    tmp_path / "decisions.jsonl",
                    [],
                ),
                manifest_path=manifest_path,
                sources_path=sources_path,
                audit_path=audit_path,
                expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
                lock_path=lock_path,
            )


def test_result_reports_true_generation_atomicity(tmp_path: Path) -> None:
    result, *_ = _promote(
        tmp_path,
        decisions=[],
    )

    notice = result.atomicity_notice.lower()
    assert result.generation_atomic is True
    assert "manifest" in notice
    assert "complete generation" in notice
    assert "mixed generation" not in notice
    assert not hasattr(_api(), "PROCESS_CRASH_ATOMICITY_LIMITATION")
