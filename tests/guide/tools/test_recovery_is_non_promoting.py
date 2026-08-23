from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

import tools.guide_data.recover_candidate_queues as recovery_runner
from tools.guide_data.recover_candidate_queues import RecoveryError
from tools.guide_data.report_pilot_field_coverage import (
    build_pilot_field_coverage,
)


ROOT = Path(__file__).resolve().parents[3]
TARGET_PRODUCT_IDS = [
    38,
    42,
    49,
    53,
    55,
    57,
    69,
    79,
    80,
    86,
    91,
    103,
    114,
    120,
    121,
]
LOCKED_HASHES = [
    "55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44",
    "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783",
    "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4",
]
PROTECTED_PATHS = [
    ROOT / "data/canonical/core_products_v1_manifest.json",
    ROOT / "data/canonical/core_products_v1.jsonl",
    ROOT / "app/guide/decision/deterministic_ranking.py",
    ROOT / "data/guide_category_facts/category_facts_v1_manifest.json",
    ROOT
    / "data/guide_category_facts"
    / (
        "category_facts_v1."
        "e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855.jsonl"
    ),
    ROOT
    / "data/guide_review_sources"
    / "approved_tmall_feed_reviews_v1_manifest.json",
    ROOT
    / "data/guide_review_sources"
    / "approved_tmall_feed_reviews_v1.jsonl",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _recovery_temp_paths(
    summary_path: Path,
    execution_record_path: Path,
) -> tuple[Path, Path]:
    return (
        summary_path.parent
        / f".{summary_path.name}.guide-recovery.tmp",
        execution_record_path.parent
        / f".{execution_record_path.name}.guide-recovery.tmp",
    )


def _run_recovery(
    *,
    inventory: Path,
    review_recovery: Path,
    coverage: Path,
    output_root: Path,
    summary_path: Path,
    execution_record_path: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.recover_candidate_queues",
            "--inventory",
            str(inventory),
            "--review-recovery",
            str(review_recovery),
            "--coverage",
            str(coverage),
            "--canonical-products",
            str(ROOT / "data/canonical/core_products_v1.jsonl"),
            "--output-root",
            str(output_root),
            "--summary",
            str(summary_path),
            "--execution-record",
            str(execution_record_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _assert_no_recovery_publication(
    summary_path: Path,
    execution_record_path: Path,
) -> None:
    assert not summary_path.exists()
    assert not execution_record_path.exists()
    assert all(
        not path.exists()
        for path in _recovery_temp_paths(
            summary_path,
            execution_record_path,
        )
    )


def _recovery_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    inventory = tmp_path / "inventory.jsonl"
    inventory.write_text(
        "".join(
            json.dumps(
                row,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for row in [
                {
                    "content_type": "json",
                    "relative_name": "opaque-source-a.json",
                    "sha256": "a" * 64,
                    "size_bytes": 17,
                    "source_root_id": "b" * 64,
                },
                {
                    "content_type": "html",
                    "relative_name": "opaque-source-b.html",
                    "sha256": "c" * 64,
                    "size_bytes": 23,
                    "source_root_id": "d" * 64,
                },
            ]
        ),
        encoding="utf-8",
    )
    review_recovery = tmp_path / "review-recovery.json"
    _write_json(
        review_recovery,
        {
            "duplicate_count": 0,
            "found_count": 0,
            "missing_count": 3,
            "results": [
                {
                    "html_sha256": locked_hash,
                    "matches": [],
                    "status": "missing",
                }
                for locked_hash in LOCKED_HASHES
            ],
            "schema_version": "locked-review-source-lookup-v1",
        },
    )
    coverage = tmp_path / "coverage.json"
    build_pilot_field_coverage(
        canonical_manifest_path=(
            ROOT / "data/canonical/core_products_v1_manifest.json"
        ),
        canonical_products_path=(
            ROOT / "data/canonical/core_products_v1.jsonl"
        ),
        category_manifest_path=(
            ROOT
            / "data/guide_category_facts/category_facts_v1_manifest.json"
        ),
        review_manifest_path=(
            ROOT
            / "data/guide_review_sources"
            / "approved_tmall_feed_reviews_v1_manifest.json"
        ),
        output_path=coverage,
    )
    return inventory, review_recovery, coverage


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}"
    return ""


def test_recovery_command_is_mechanically_non_promoting(
    tmp_path: Path,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(tmp_path)
    output_root = tmp_path / "queues"
    summary_path = tmp_path / "candidate-queue-summary.json"
    execution_record_path = tmp_path / "execution-record.json"
    before = {path: _sha256(path) for path in PROTECTED_PATHS}
    category_manifest_before = json.loads(
        (
            ROOT
            / "data/guide_category_facts/category_facts_v1_manifest.json"
        ).read_text(encoding="utf-8")
    )
    production_fact_count = category_manifest_before["fact_count"]
    category_facts_path = (
        ROOT
        / "data/guide_category_facts"
        / category_manifest_before["facts_file"]
    )
    category_facts_sha256_before = _sha256(category_facts_path)
    review_manifest_before = json.loads(
        (
            ROOT
            / "data/guide_review_sources"
            / "approved_tmall_feed_reviews_v1_manifest.json"
        ).read_text(encoding="utf-8")
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.recover_candidate_queues",
            "--inventory",
            str(inventory),
            "--review-recovery",
            str(review_recovery),
            "--coverage",
            str(coverage),
            "--canonical-products",
            str(ROOT / "data/canonical/core_products_v1.jsonl"),
            "--output-root",
            str(output_root),
            "--summary",
            str(summary_path),
            "--execution-record",
            str(execution_record_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    after = {path: _sha256(path) for path in PROTECTED_PATHS}
    assert after == before
    assert review_manifest_before["approved_source_count"] == 6
    category_manifest_after = json.loads(
        (
            ROOT
            / "data/guide_category_facts/category_facts_v1_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert category_manifest_after == category_manifest_before
    assert _sha256(category_facts_path) == category_facts_sha256_before
    assert json.loads(
        (
            ROOT
            / "data/guide_review_sources"
            / "approved_tmall_feed_reviews_v1_manifest.json"
        ).read_text(encoding="utf-8")
    )["approved_source_count"] == 6

    record = json.loads(execution_record_path.read_text(encoding="utf-8"))
    assert set(record["allowed_operations"]) == {
        "build_category_fact_candidates",
        "build_review_candidates",
        "initialize_empty_queues",
    }
    assert all(
        operation["name"] in record["allowed_operations"]
        for operation in record["operations"]
    )
    assert all(
        set(operation["capabilities"])
        <= {"candidate_build", "queue_initialize"}
        for operation in record["operations"]
    )
    assert stat.S_IMODE(execution_record_path.stat().st_mode) == 0o600

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["automatic_reviewers"] == 0
    assert summary["automatic_approvals"] == 0
    assert summary["promotion_invocations"] == 0
    assert summary["production_fact_count"] == production_fact_count
    assert summary["approved_review_sources"] == 6
    assert summary["locked_review_sources"] == {
        "duplicate": 0,
        "found": 0,
        "missing": 3,
    }
    assert summary["provenance"] == "source_incomplete"

    recovery_source = (
        ROOT / "tools/guide_data/recover_candidate_queues.py"
    )
    tree = ast.parse(recovery_source.read_text(encoding="utf-8"))
    forbidden = {"approve", "promote", "reviewer"}
    imported_or_called = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported_or_called.append(ast.unparse(node).casefold())
        elif isinstance(node, ast.Call):
            imported_or_called.append(_call_name(node.func).casefold())
    assert all(
        not any(token in name for token in forbidden)
        for name in imported_or_called
    )

    for path in output_root.rglob("*"):
        if path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.sep not in completed.stdout


def test_candidate_queue_summary_is_order_stable_and_aggregate_only(
    tmp_path: Path,
) -> None:
    first_inputs = _recovery_inputs(tmp_path / "first-inputs")
    second_inputs = _recovery_inputs(tmp_path / "second-inputs")
    second_inventory, second_recovery, second_coverage = second_inputs
    second_inventory.write_text(
        "".join(
            reversed(
                second_inventory.read_text(
                    encoding="utf-8"
                ).splitlines(keepends=True)
            )
        ),
        encoding="utf-8",
    )
    recovery_payload = json.loads(
        second_recovery.read_text(encoding="utf-8")
    )
    recovery_payload["results"].reverse()
    _write_json(second_recovery, recovery_payload)
    coverage_payload = json.loads(
        second_coverage.read_text(encoding="utf-8")
    )
    coverage_payload["products"].reverse()
    _write_json(second_coverage, coverage_payload)

    summary_paths: list[Path] = []
    for label, inputs in (
        ("first", first_inputs),
        ("second", second_inputs),
    ):
        inventory, review_recovery, coverage = inputs
        summary_path = tmp_path / f"{label}-summary.json"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.guide_data.recover_candidate_queues",
                "--inventory",
                str(inventory),
                "--review-recovery",
                str(review_recovery),
                "--coverage",
                str(coverage),
                "--canonical-products",
                str(ROOT / "data/canonical/core_products_v1.jsonl"),
                "--output-root",
                str(tmp_path / f"{label}-queues"),
                "--summary",
                str(summary_path),
                "--execution-record",
                str(tmp_path / f"{label}-execution.json"),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        summary_paths.append(summary_path)

    first_bytes = summary_paths[0].read_bytes()
    second_bytes = summary_paths[1].read_bytes()
    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(
        second_bytes
    ).hexdigest()

    summary = json.loads(first_bytes)
    production_fact_count = json.loads(
        (
            ROOT
            / "data/guide_category_facts/category_facts_v1_manifest.json"
        ).read_text(encoding="utf-8")
    )["fact_count"]
    assert set(summary) == {
        "approved_review_sources",
        "automatic_approvals",
        "automatic_reviewers",
        "category",
        "coverage",
        "inventory_file_count",
        "inventory_sha256",
        "locked_review_sources",
        "product_ids",
        "production_fact_count",
        "publication",
        "promotion_invocations",
        "provenance",
        "review",
        "schema_version",
    }
    assert set(summary["publication"]) == {
        "pair_sha256",
        "run_id",
        "schema_version",
    }
    assert summary["publication"]["schema_version"] == (
        "guide-recovery-publication-v1"
    )
    assert len(summary["publication"]["pair_sha256"]) == 64
    assert len(summary["publication"]["run_id"]) == 64
    assert summary["product_ids"] == TARGET_PRODUCT_IDS
    assert summary["inventory_file_count"] == 2
    expected_queue_fields = {
        "pending_count",
        "pending_sha256",
        "quarantine_count",
        "quarantine_sha256",
        "queue_sha256",
    }
    assert set(summary["review"]) == expected_queue_fields
    assert set(summary["category"]) == expected_queue_fields
    assert summary["review"]["pending_count"] == 0
    assert summary["review"]["quarantine_count"] == 0
    assert summary["category"]["pending_count"] == 0
    assert summary["category"]["quarantine_count"] == 0
    assert summary["automatic_reviewers"] == 0
    assert summary["automatic_approvals"] == 0
    assert summary["promotion_invocations"] == 0
    assert summary["production_fact_count"] == production_fact_count
    assert summary["approved_review_sources"] == 6
    serialized = first_bytes.decode("utf-8")
    assert str(tmp_path) not in serialized
    assert "opaque-source" not in serialized


def test_full_hash_claim_without_inventory_or_builder_detail_fails_closed(
    tmp_path: Path,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(tmp_path)
    recovery_payload = json.loads(
        review_recovery.read_text(encoding="utf-8")
    )
    recovery_payload.update(
        {
            "found_count": 3,
            "missing_count": 0,
        }
    )
    for result in recovery_payload["results"]:
        result["matches"] = [
            {
                "source_locator": (
                    "urn:xiaoro:local-source:sha256:" + "f" * 64
                )
            }
        ]
        result["status"] = "found"
    _write_json(review_recovery, recovery_payload)
    summary_path = tmp_path / "summary.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.recover_candidate_queues",
            "--inventory",
            str(inventory),
            "--review-recovery",
            str(review_recovery),
            "--coverage",
            str(coverage),
            "--canonical-products",
            str(ROOT / "data/canonical/core_products_v1.jsonl"),
            "--output-root",
            str(tmp_path / "queues"),
            "--summary",
            str(summary_path),
            "--execution-record",
            str(tmp_path / "execution.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert not summary_path.exists()


@pytest.mark.parametrize(
    ("option", "manifest_path"),
    [
        (
            "--review-source-manifest",
            ROOT / "tests/fixtures/guide/reviews/source_manifest.json",
        ),
        (
            "--category-source-manifest",
            ROOT / "tests/fixtures/guide/category_data/source_manifest.json",
        ),
    ],
)
def test_candidate_manifest_hashes_must_be_bound_to_inventory_results(
    tmp_path: Path,
    option: str,
    manifest_path: Path,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(tmp_path)
    if option == "--review-source-manifest":
        recovery_payload = json.loads(
            review_recovery.read_text(encoding="utf-8")
        )
        recovery_payload["found_count"] = 1
        recovery_payload["missing_count"] = 2
        recovery_payload["results"][0].update(
            {
                "matches": [
                    {
                        "source_locator": (
                            "urn:xiaoro:local-source:sha256:" + "f" * 64
                        )
                    }
                ],
                "status": "found",
            }
        )
        _write_json(review_recovery, recovery_payload)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.recover_candidate_queues",
            "--inventory",
            str(inventory),
            "--review-recovery",
            str(review_recovery),
            "--coverage",
            str(coverage),
            "--canonical-products",
            str(ROOT / "data/canonical/core_products_v1.jsonl"),
            "--output-root",
            str(tmp_path / "queues"),
            "--summary",
            str(tmp_path / "summary.json"),
            "--execution-record",
            str(tmp_path / "execution.json"),
            option,
            str(manifest_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stderr) == {
        "error": "RecoveryError",
        "status": "failed",
    }
    assert not (tmp_path / "summary.json").exists()


def test_recovery_rejects_aggregate_counts_that_contradict_details(
    tmp_path: Path,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(tmp_path)
    recovery_payload = json.loads(
        review_recovery.read_text(encoding="utf-8")
    )
    recovery_payload["found_count"] = 3
    recovery_payload["missing_count"] = 0
    _write_json(review_recovery, recovery_payload)
    coverage_payload = json.loads(
        coverage.read_text(encoding="utf-8")
    )
    coverage_payload["retained_count"] = 0
    coverage_payload["quarantine_count"] = 15
    coverage_payload["unknown_field_count"] = 999
    _write_json(coverage, coverage_payload)
    summary_path = tmp_path / "summary.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.recover_candidate_queues",
            "--inventory",
            str(inventory),
            "--review-recovery",
            str(review_recovery),
            "--coverage",
            str(coverage),
            "--canonical-products",
            str(ROOT / "data/canonical/core_products_v1.jsonl"),
            "--output-root",
            str(tmp_path / "queues"),
            "--summary",
            str(summary_path),
            "--execution-record",
            str(tmp_path / "execution.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert not summary_path.exists()


def test_recovery_rejects_duplicate_inventory_detail_identity(
    tmp_path: Path,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(tmp_path)
    first_row = inventory.read_text(encoding="utf-8").splitlines()[0]
    with inventory.open("a", encoding="utf-8") as stream:
        stream.write(first_row + "\n")
    summary_path = tmp_path / "summary.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.recover_candidate_queues",
            "--inventory",
            str(inventory),
            "--review-recovery",
            str(review_recovery),
            "--coverage",
            str(coverage),
            "--canonical-products",
            str(ROOT / "data/canonical/core_products_v1.jsonl"),
            "--output-root",
            str(tmp_path / "queues"),
            "--summary",
            str(summary_path),
            "--execution-record",
            str(tmp_path / "execution.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert not summary_path.exists()


def test_recovery_rejects_missing_product_field_details(
    tmp_path: Path,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(tmp_path)
    coverage_payload = json.loads(
        coverage.read_text(encoding="utf-8")
    )
    coverage_payload["products"][0]["fields"] = {}
    _write_json(coverage, coverage_payload)
    summary_path = tmp_path / "summary.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.guide_data.recover_candidate_queues",
            "--inventory",
            str(inventory),
            "--review-recovery",
            str(review_recovery),
            "--coverage",
            str(coverage),
            "--canonical-products",
            str(ROOT / "data/canonical/core_products_v1.jsonl"),
            "--output-root",
            str(tmp_path / "queues"),
            "--summary",
            str(summary_path),
            "--execution-record",
            str(tmp_path / "execution.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert not summary_path.exists()


def test_recovery_rejects_fabricated_promotion_execution_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(tmp_path)
    real_execute_allowed = recovery_runner._execute_allowed

    def execute_with_fake_promotion(name, operations, operation):
        result = real_execute_allowed(name, operations, operation)
        if name == "initialize_empty_queues":
            operations.append(
                {
                    "capabilities": ["promotion_call"],
                    "name": "fabricated_promotion",
                    "status": "completed",
                }
            )
        return result

    monkeypatch.setattr(
        recovery_runner,
        "_execute_allowed",
        execute_with_fake_promotion,
    )
    summary_path = tmp_path / "summary.json"

    with pytest.raises(RecoveryError):
        recovery_runner.recover_candidate_queues(
            inventory_path=inventory,
            review_recovery_path=review_recovery,
            coverage_path=coverage,
            canonical_products_path=(
                ROOT / "data/canonical/core_products_v1.jsonl"
            ),
            output_root=tmp_path / "queues",
            summary_path=summary_path,
            execution_record_path=tmp_path / "execution.json",
        )
    assert not summary_path.exists()


def test_recovery_rejects_queue_rows_without_a_builder_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(tmp_path)
    real_initialize = recovery_runner._initialize_empty_queues

    def initialize_with_fabricated_candidate(output_root: Path):
        paths = real_initialize(output_root)
        paths.review_pending.write_text(
            json.dumps(
                {
                    "candidate_id": "fabricated-candidate",
                    "status": "pending",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return paths

    monkeypatch.setattr(
        recovery_runner,
        "_initialize_empty_queues",
        initialize_with_fabricated_candidate,
    )
    summary_path = tmp_path / "summary.json"

    with pytest.raises(RecoveryError):
        recovery_runner.recover_candidate_queues(
            inventory_path=inventory,
            review_recovery_path=review_recovery,
            coverage_path=coverage,
            canonical_products_path=(
                ROOT / "data/canonical/core_products_v1.jsonl"
            ),
            output_root=tmp_path / "queues",
            summary_path=summary_path,
            execution_record_path=tmp_path / "execution.json",
        )
    assert not summary_path.exists()


def test_failed_rerun_invalidates_stale_publication_and_temporary_files(
    tmp_path: Path,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(
        tmp_path / "inputs"
    )
    recovery_payload = json.loads(
        review_recovery.read_text(encoding="utf-8")
    )
    recovery_payload["found_count"] = 3
    recovery_payload["missing_count"] = 0
    _write_json(review_recovery, recovery_payload)
    output_parent = tmp_path / "publication"
    output_parent.mkdir()
    summary_path = output_parent / "summary.json"
    execution_record_path = output_parent / "execution.json"
    summary_path.write_text('{"stale":true}\n', encoding="utf-8")
    execution_record_path.write_text(
        '{"stale_execution":true}\n',
        encoding="utf-8",
    )
    for path in _recovery_temp_paths(
        summary_path,
        execution_record_path,
    ):
        path.write_text("stale temporary evidence\n", encoding="utf-8")

    completed = _run_recovery(
        inventory=inventory,
        review_recovery=review_recovery,
        coverage=coverage,
        output_root=tmp_path / "queues",
        summary_path=summary_path,
        execution_record_path=execution_record_path,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stderr) == {
        "error": "RecoveryError",
        "status": "failed",
    }
    _assert_no_recovery_publication(
        summary_path,
        execution_record_path,
    )


@pytest.mark.parametrize("opened_target", ["summary", "execution"])
@pytest.mark.parametrize(
    "failure_kind",
    ["symlink", "non_directory", "permission"],
)
def test_later_parent_open_failure_invalidates_stale_open_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opened_target: str,
    failure_kind: str,
) -> None:
    opened_parent = tmp_path / "a-open"
    opened_parent.mkdir()
    failed_parent = tmp_path / "z-failed"
    if opened_target == "summary":
        summary_path = opened_parent / "summary.json"
        execution_record_path = failed_parent / "execution.json"
        stale_index = 0
    else:
        summary_path = failed_parent / "summary.json"
        execution_record_path = opened_parent / "execution.json"
        stale_index = 1
    stale_path = (summary_path, execution_record_path)[stale_index]
    stale_path.write_text("stale formal output\n", encoding="utf-8")
    stale_temporary = _recovery_temp_paths(
        summary_path,
        execution_record_path,
    )[stale_index]
    stale_temporary.write_text(
        "stale temporary output\n",
        encoding="utf-8",
    )
    if failure_kind == "symlink":
        failed_parent.symlink_to(
            opened_parent,
            target_is_directory=True,
        )
    elif failure_kind == "non_directory":
        failed_parent.write_text("not a directory\n", encoding="utf-8")

    real_open_output_parent = recovery_runner._open_output_parent
    opened_descriptors: list[int] = []

    def open_output_parent(path: Path, *, create: bool):
        if failure_kind == "permission" and path == failed_parent:
            raise PermissionError("injected output parent denial")
        result = real_open_output_parent(path, create=create)
        opened_descriptors.append(result[0])
        return result

    monkeypatch.setattr(
        recovery_runner,
        "_open_output_parent",
        open_output_parent,
    )

    with pytest.raises(RecoveryError):
        with recovery_runner._RecoveryPublication(
            summary_path=summary_path,
            execution_record_path=execution_record_path,
        ):
            raise AssertionError("unsafe output parent was accepted")

    assert len(opened_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(opened_descriptors[0])
    assert not stale_path.exists()
    assert not stale_temporary.exists()


def test_split_parent_validation_failure_invalidates_every_open_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = tmp_path / "a-summary" / "summary.json"
    execution_record_path = (
        tmp_path / "b-execution" / "execution.json"
    )
    for path in (summary_path, execution_record_path):
        path.parent.mkdir()
        path.write_text("stale formal output\n", encoding="utf-8")
    for path in _recovery_temp_paths(
        summary_path,
        execution_record_path,
    ):
        path.write_text("stale temporary output\n", encoding="utf-8")
    real_open_output_parent = recovery_runner._open_output_parent
    opened_descriptors: list[int] = []

    def track_open_output_parent(path: Path, *, create: bool):
        result = real_open_output_parent(path, create=create)
        opened_descriptors.append(result[0])
        return result

    def fail_parent_validation(*args, **kwargs) -> None:
        raise RecoveryError("injected parent validation failure")

    monkeypatch.setattr(
        recovery_runner,
        "_open_output_parent",
        track_open_output_parent,
    )
    monkeypatch.setattr(
        recovery_runner,
        "_verify_output_parent",
        fail_parent_validation,
    )

    with pytest.raises(
        RecoveryError,
        match="injected parent validation failure",
    ):
        with recovery_runner._RecoveryPublication(
            summary_path=summary_path,
            execution_record_path=execution_record_path,
        ):
            raise AssertionError("invalid output parents were accepted")

    assert len(opened_descriptors) == 2
    for descriptor in opened_descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    _assert_no_recovery_publication(
        summary_path,
        execution_record_path,
    )


@pytest.mark.parametrize(
    "layout",
    ["same_parent", "split_parent", "same_name_split_parent"],
)
def test_publication_pair_succeeds_in_same_and_split_parents(
    tmp_path: Path,
    layout: str,
) -> None:
    if layout == "same_parent":
        summary_path = tmp_path / "shared" / "summary.json"
        execution_record_path = tmp_path / "shared" / "execution.json"
    elif layout == "split_parent":
        summary_path = tmp_path / "summary" / "summary.json"
        execution_record_path = (
            tmp_path / "execution" / "execution.json"
        )
    else:
        summary_path = tmp_path / "summary" / "result.json"
        execution_record_path = tmp_path / "execution" / "result.json"

    with recovery_runner._RecoveryPublication(
        summary_path=summary_path,
        execution_record_path=execution_record_path,
    ) as publication:
        bound_summary = publication.publish(
            summary={"summary_count": 1},
            execution_record={"operation_count": 2},
        )

    summary = json.loads(summary_path.read_bytes())
    execution = json.loads(execution_record_path.read_bytes())
    assert summary == bound_summary
    assert summary["publication"] == execution["publication"]
    assert summary["summary_count"] == 1
    assert execution["operation_count"] == 2
    assert stat.S_IMODE(summary_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(execution_record_path.stat().st_mode) == 0o600
    assert all(
        not path.exists()
        for path in _recovery_temp_paths(
            summary_path,
            execution_record_path,
        )
    )


@pytest.mark.parametrize(
    ("summary_name", "execution_name"),
    [
        ("result.json", "result.json"),
        (".execution.json.guide-recovery.tmp", "execution.json"),
        ("summary.json", ".summary.json.guide-recovery.tmp"),
    ],
)
def test_publication_rejects_duplicate_paths_and_entry_name_conflicts(
    tmp_path: Path,
    summary_name: str,
    execution_name: str,
) -> None:
    with pytest.raises(
        RecoveryError,
        match="outputs must differ|output names collide",
    ):
        recovery_runner._RecoveryPublication(
            summary_path=tmp_path / "publication" / summary_name,
            execution_record_path=(
                tmp_path / "publication" / execution_name
            ),
        )

    assert not (tmp_path / "publication").exists()


def test_cleanup_failure_is_reported_after_all_entries_and_parent_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = tmp_path / "a-summary" / "summary.json"
    execution_record_path = (
        tmp_path / "b-execution" / "execution.json"
    )
    for path in (summary_path, execution_record_path):
        path.parent.mkdir()
        path.write_text("stale formal output\n", encoding="utf-8")
    temporary_paths = _recovery_temp_paths(
        summary_path,
        execution_record_path,
    )
    for path in temporary_paths:
        path.write_text("stale temporary output\n", encoding="utf-8")
    expected_names = {
        summary_path.name,
        execution_record_path.name,
        *(path.name for path in temporary_paths),
    }
    real_open_output_parent = recovery_runner._open_output_parent
    real_unlink = recovery_runner._unlink_publication_entry
    real_fsync = recovery_runner.os.fsync
    opened_descriptors: list[int] = []
    attempted_names: list[str] = []
    synchronized_descriptors: list[int] = []

    def track_open_output_parent(path: Path, *, create: bool):
        result = real_open_output_parent(path, create=create)
        opened_descriptors.append(result[0])
        return result

    def fail_summary_cleanup(
        name: str,
        *,
        directory_descriptor: int,
    ) -> None:
        attempted_names.append(name)
        if name == summary_path.name:
            raise RecoveryError("injected cleanup failure")
        real_unlink(
            name,
            directory_descriptor=directory_descriptor,
        )

    def track_fsync(descriptor: int) -> None:
        synchronized_descriptors.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(
        recovery_runner,
        "_open_output_parent",
        track_open_output_parent,
    )
    monkeypatch.setattr(
        recovery_runner,
        "_unlink_publication_entry",
        fail_summary_cleanup,
    )
    monkeypatch.setattr(recovery_runner.os, "fsync", track_fsync)

    with pytest.raises(
        RecoveryError,
        match="outputs could not be invalidated",
    ):
        with recovery_runner._RecoveryPublication(
            summary_path=summary_path,
            execution_record_path=execution_record_path,
        ):
            raise AssertionError("cleanup failure was ignored")

    assert len(opened_descriptors) == 2
    assert expected_names <= set(attempted_names)
    assert set(opened_descriptors) <= set(synchronized_descriptors)
    for descriptor in opened_descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert summary_path.exists()
    assert not execution_record_path.exists()
    assert all(not path.exists() for path in temporary_paths)


def test_recovery_reruns_publish_only_a_bound_stable_success_pair(
    tmp_path: Path,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(
        tmp_path / "inputs"
    )
    valid_recovery = review_recovery.read_bytes()
    invalid_payload = json.loads(valid_recovery)
    invalid_payload["found_count"] = 3
    invalid_payload["missing_count"] = 0
    output_parent = tmp_path / "publication"
    summary_path = output_parent / "summary.json"
    execution_record_path = output_parent / "execution.json"

    for _ in range(2):
        _write_json(review_recovery, invalid_payload)
        failed = _run_recovery(
            inventory=inventory,
            review_recovery=review_recovery,
            coverage=coverage,
            output_root=tmp_path / "queues",
            summary_path=summary_path,
            execution_record_path=execution_record_path,
        )
        assert failed.returncode == 2
        _assert_no_recovery_publication(
            summary_path,
            execution_record_path,
        )

    successful_bytes: list[tuple[bytes, bytes]] = []
    for _ in range(2):
        review_recovery.write_bytes(valid_recovery)
        succeeded = _run_recovery(
            inventory=inventory,
            review_recovery=review_recovery,
            coverage=coverage,
            output_root=tmp_path / "queues",
            summary_path=summary_path,
            execution_record_path=execution_record_path,
        )
        assert succeeded.returncode == 0, succeeded.stderr
        summary = json.loads(summary_path.read_bytes())
        execution = json.loads(execution_record_path.read_bytes())
        assert summary["publication"] == execution["publication"]
        assert summary["publication"]["schema_version"] == (
            "guide-recovery-publication-v1"
        )
        summary_core = {
            key: value
            for key, value in summary.items()
            if key != "publication"
        }
        execution_core = {
            key: value
            for key, value in execution.items()
            if key != "publication"
        }
        pair_bytes = json.dumps(
            {
                "execution_record": execution_core,
                "summary": summary_core,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        assert summary["publication"]["pair_sha256"] == (
            hashlib.sha256(pair_bytes).hexdigest()
        )
        assert summary["publication"]["run_id"] == hashlib.sha256(
            b"guide-recovery-publication-v1\0" + pair_bytes
        ).hexdigest()
        assert stat.S_IMODE(summary_path.stat().st_mode) == 0o600
        assert (
            stat.S_IMODE(execution_record_path.stat().st_mode)
            == 0o600
        )
        assert all(
            not path.exists()
            for path in _recovery_temp_paths(
                summary_path,
                execution_record_path,
            )
        )
        successful_bytes.append(
            (
                summary_path.read_bytes(),
                execution_record_path.read_bytes(),
            )
        )

        _write_json(review_recovery, invalid_payload)
        failed = _run_recovery(
            inventory=inventory,
            review_recovery=review_recovery,
            coverage=coverage,
            output_root=tmp_path / "queues",
            summary_path=summary_path,
            execution_record_path=execution_record_path,
        )
        assert failed.returncode == 2
        _assert_no_recovery_publication(
            summary_path,
            execution_record_path,
        )

    assert successful_bytes[0] == successful_bytes[1]


def test_processing_failure_removes_stale_and_temporary_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(
        tmp_path / "inputs"
    )
    output_parent = tmp_path / "publication"
    output_parent.mkdir()
    summary_path = output_parent / "summary.json"
    execution_record_path = output_parent / "execution.json"
    summary_path.write_text("stale summary\n", encoding="utf-8")
    execution_record_path.write_text(
        "stale execution\n",
        encoding="utf-8",
    )
    for path in _recovery_temp_paths(
        summary_path,
        execution_record_path,
    ):
        path.write_text("stale temporary evidence\n", encoding="utf-8")
    real_initialize = recovery_runner._initialize_empty_queues

    def fail_after_queue_initialization(output_root: Path):
        real_initialize(output_root)
        raise RecoveryError("processing failed")

    monkeypatch.setattr(
        recovery_runner,
        "_initialize_empty_queues",
        fail_after_queue_initialization,
    )

    with pytest.raises(RecoveryError, match="processing failed"):
        recovery_runner.recover_candidate_queues(
            inventory_path=inventory,
            review_recovery_path=review_recovery,
            coverage_path=coverage,
            canonical_products_path=(
                ROOT / "data/canonical/core_products_v1.jsonl"
            ),
            output_root=tmp_path / "queues",
            summary_path=summary_path,
            execution_record_path=execution_record_path,
        )

    _assert_no_recovery_publication(
        summary_path,
        execution_record_path,
    )


def test_split_parent_second_output_publish_failure_rolls_back_the_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(
        tmp_path / "inputs"
    )
    summary_path = tmp_path / "summary" / "summary.json"
    execution_record_path = (
        tmp_path / "execution" / "execution.json"
    )
    real_link = os.link
    link_calls = 0

    def fail_second_link(*args, **kwargs):
        nonlocal link_calls
        link_calls += 1
        if link_calls == 2:
            raise OSError("injected second publication failure")
        return real_link(*args, **kwargs)

    monkeypatch.setattr(recovery_runner.os, "link", fail_second_link)

    with pytest.raises(RecoveryError):
        recovery_runner.recover_candidate_queues(
            inventory_path=inventory,
            review_recovery_path=review_recovery,
            coverage_path=coverage,
            canonical_products_path=(
                ROOT / "data/canonical/core_products_v1.jsonl"
            ),
            output_root=tmp_path / "queues",
            summary_path=summary_path,
            execution_record_path=execution_record_path,
        )

    assert link_calls == 2
    _assert_no_recovery_publication(
        summary_path,
        execution_record_path,
    )


def test_output_parent_replacement_during_validation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, review_recovery, coverage = _recovery_inputs(
        tmp_path / "inputs"
    )
    output_parent = tmp_path / "publication"
    output_parent.mkdir()
    detached_parent = tmp_path / "detached-publication"
    summary_path = output_parent / "summary.json"
    execution_record_path = output_parent / "execution.json"
    real_read_bytes = recovery_runner._read_bytes
    raced = False

    def replace_parent_on_first_input_read(
        path: Path,
        *,
        label: str,
    ) -> bytes:
        nonlocal raced
        if not raced:
            os.rename(output_parent, detached_parent)
            output_parent.mkdir()
            raced = True
        return real_read_bytes(path, label=label)

    monkeypatch.setattr(
        recovery_runner,
        "_read_bytes",
        replace_parent_on_first_input_read,
    )

    with pytest.raises(RecoveryError):
        recovery_runner.recover_candidate_queues(
            inventory_path=inventory,
            review_recovery_path=review_recovery,
            coverage_path=coverage,
            canonical_products_path=(
                ROOT / "data/canonical/core_products_v1.jsonl"
            ),
            output_root=tmp_path / "queues",
            summary_path=summary_path,
            execution_record_path=execution_record_path,
        )

    assert raced is True
    _assert_no_recovery_publication(
        summary_path,
        execution_record_path,
    )
    _assert_no_recovery_publication(
        detached_parent / summary_path.name,
        detached_parent / execution_record_path.name,
    )
