from importlib import import_module
from importlib.util import find_spec
import hashlib
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from app.guide.adapters.llm.contracts import (
    SemanticStageUsage,
    SemanticTokenUsage,
)
from tools.guide_gates import real_ab_evidence
from tools.guide_gates.private_output_io import OutputBindingError
from tools.guide_gates.real_ab_evidence import (
    EVIDENCE_FILENAMES,
    EvidenceBundle,
    PrivateEvidenceWriter,
    SensitiveEvidenceError,
    build_evidence_bundle,
    canonical_json_bytes,
    execute_supervised_runner,
    load_frozen_inputs,
    mapping_usage_complete,
    nearest_rank,
    sum_token_fields,
    two_stage_phase_runtime,
    two_stage_usage_complete,
)


_FIXTURE_ROOT = Path("tests/fixtures/guide/intent")
_CASES_PATH = _FIXTURE_ROOT / "semantic_intent_ab_v2.jsonl"
_SMOKE_PATH = _FIXTURE_ROOT / "two_stage_smoke_v1.jsonl"
_SMOKE_MANIFEST_PATH = (
    _FIXTURE_ROOT / "two_stage_smoke_v1_manifest.json"
)


def test_shared_real_ab_evidence_module_exists() -> None:
    assert find_spec("tools.guide_gates.real_ab_evidence") is not None


def test_shared_real_ab_evidence_exposes_public_contract() -> None:
    module = import_module("tools.guide_gates.real_ab_evidence")

    assert {
        "CANONICAL_INTENT_INPUTS",
        "CollectedLaneEvidence",
        "EvidenceBundle",
        "FrozenInputSpec",
        "FrozenInputs",
        "PrivateEvidenceWriter",
        "SensitiveEvidenceError",
        "SingleStageControlReport",
        "build_evidence_bundle",
        "build_supervised_evidence",
        "canonical_json_bytes",
        "collect_supervised_lane_evidence",
        "load_frozen_inputs",
        "mapping_usage_complete",
        "nearest_rank",
        "run_single_stage_control",
        "sum_token_fields",
        "two_stage_phase_runtime",
        "two_stage_usage_complete",
    } <= set(module.__all__)


def test_frozen_loader_returns_only_canonical_full_and_smoke_inputs() -> None:
    frozen = load_frozen_inputs(
        cases_path=_CASES_PATH,
        smoke_cases_path=_SMOKE_PATH,
        smoke_manifest_path=_SMOKE_MANIFEST_PATH,
    )

    assert len(frozen.cases) == 128
    assert len(frozen.smoke_cases) == 32
    assert [case.case_id for case in frozen.smoke_cases] == [
        json.loads(line)["case_id"]
        for line in _SMOKE_PATH.read_text(encoding="utf-8").splitlines()
    ]


def test_shared_usage_and_nearest_rank_keep_cached_tokens_optional() -> None:
    usage = SemanticTokenUsage(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cached_tokens=None,
    )
    stages = (
        SemanticStageUsage(
            stage="route",
            usage=usage,
            repair_used=False,
        ),
    )
    report = SimpleNamespace(
        runtime_rows=(
            SimpleNamespace(latency_ms=5.0, stage_usage=stages),
            SimpleNamespace(latency_ms=10.0, stage_usage=stages),
        )
    )

    assert nearest_rank([10.0, 5.0], 0.95) == 10.0
    assert mapping_usage_complete(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_tokens": None,
        }
    )
    assert not mapping_usage_complete(
        {
            "prompt_tokens": True,
            "completion_tokens": 5,
            "total_tokens": 6,
        }
    )
    assert two_stage_usage_complete(report)
    assert sum_token_fields([usage, usage]) == {
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
        "cached_tokens": None,
    }
    assert two_stage_phase_runtime(report) == {
        "case_count": 2,
        "latency_p95_ms": 10.0,
        "usage_complete": True,
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
            "cached_tokens": None,
        },
    }


def test_evidence_bundle_preserves_canonical_hash_contract() -> None:
    normalized_rows = (
        {"case_id": "b", "model": "second"},
        {"case_id": "a", "model": "first"},
    )
    runtime_payload = {"rows": [{"case_id": "runtime"}], "version": 1}

    bundle = build_evidence_bundle(
        normalized_rows=normalized_rows,
        normalized_sort_key=lambda row: str(row["case_id"]),
        runtime_payload=runtime_payload,
        summary_builder=lambda normalized_sha, runtime_sha: {
            "normalized_results_sha256": normalized_sha,
            "runtime_metrics_sha256": runtime_sha,
        },
    )

    normalized_bytes = (
        canonical_json_bytes(normalized_rows[1])
        + b"\n"
        + canonical_json_bytes(normalized_rows[0])
        + b"\n"
    )
    runtime_bytes = canonical_json_bytes(runtime_payload) + b"\n"
    normalized_sha = hashlib.sha256(normalized_bytes).hexdigest()
    runtime_sha = hashlib.sha256(runtime_bytes).hexdigest()
    summary_payload = {
        "normalized_results_sha256": normalized_sha,
        "runtime_metrics_sha256": runtime_sha,
    }
    summary_bytes = canonical_json_bytes(summary_payload) + b"\n"
    summary_sha = hashlib.sha256(summary_bytes).hexdigest()

    assert bundle == EvidenceBundle(
        payloads={
            "normalized_results.jsonl": normalized_bytes,
            "runtime_metrics.json": runtime_bytes,
            "summary.json": summary_bytes,
            "SHA256SUMS": (
                f"{normalized_sha}  normalized_results.jsonl\n"
                f"{runtime_sha}  runtime_metrics.json\n"
                f"{summary_sha}  summary.json\n"
            ).encode("ascii"),
        },
        normalized_sha256=normalized_sha,
        runtime_sha256=runtime_sha,
        summary_sha256=summary_sha,
    )


def test_private_writer_scans_all_payloads_before_first_write(
    tmp_path: Path,
) -> None:
    secret = 'canonical-"secret"\\value'
    bundle = build_evidence_bundle(
        normalized_rows=({"case_id": "safe"},),
        normalized_sort_key=lambda row: str(row["case_id"]),
        runtime_payload={"status": "safe"},
        summary_builder=lambda normalized_sha, runtime_sha: {
            "normalized_sha": normalized_sha,
            "runtime_sha": runtime_sha,
            "nested": {"unsafe": secret},
        },
    )
    destination = tmp_path / "sensitive"
    writer = PrivateEvidenceWriter.create(destination)
    try:
        with pytest.raises(SensitiveEvidenceError):
            writer.write(bundle, sensitive_values=(secret,))
        assert list(destination.iterdir()) == []
    finally:
        writer.close(remove_if_empty=True)
    assert not destination.exists()


def test_private_writer_holds_directory_binding_for_every_write(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "bound"
    moved = tmp_path / "moved"
    writer = PrivateEvidenceWriter.create(destination)
    destination.rename(moved)
    destination.mkdir()
    bundle = build_evidence_bundle(
        normalized_rows=({"case_id": "safe"},),
        normalized_sort_key=lambda row: str(row["case_id"]),
        runtime_payload={"status": "safe"},
        summary_builder=lambda normalized_sha, runtime_sha: {
            "normalized_sha": normalized_sha,
            "runtime_sha": runtime_sha,
        },
    )
    try:
        with pytest.raises(OutputBindingError):
            writer.write(bundle)
    finally:
        writer.close()

    assert list(destination.iterdir()) == []
    assert list(moved.iterdir()) == []


def test_private_writer_creates_only_private_regular_evidence(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "private"
    bundle = build_evidence_bundle(
        normalized_rows=({"case_id": "safe"},),
        normalized_sort_key=lambda row: str(row["case_id"]),
        runtime_payload={"status": "safe"},
        summary_builder=lambda normalized_sha, runtime_sha: {
            "normalized_sha": normalized_sha,
            "runtime_sha": runtime_sha,
        },
    )
    writer = PrivateEvidenceWriter.create(destination)
    try:
        writer.write(bundle)
    finally:
        writer.close()

    assert set(path.name for path in destination.iterdir()) == set(
        bundle.payloads
    )
    assert all(
        path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in destination.iterdir()
    )


def _safe_bundle() -> EvidenceBundle:
    return build_evidence_bundle(
        normalized_rows=({"case_id": "safe"},),
        normalized_sort_key=lambda row: str(row["case_id"]),
        runtime_payload={"status": "safe"},
        summary_builder=lambda normalized_sha, runtime_sha: {
            "normalized_sha": normalized_sha,
            "runtime_sha": runtime_sha,
        },
    )


class _ClosableAdapter:
    def __init__(
        self,
        name: str,
        closed: list[str],
        *,
        raise_on_close: bool = False,
    ) -> None:
        self.name = name
        self._closed = closed
        self._raise_on_close = raise_on_close

    def close(self) -> None:
        self._closed.append(self.name)
        if self._raise_on_close:
            raise OSError(f"{self.name} close failed")


def test_private_writer_publishes_final_evidence_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "atomic"
    bundle = _safe_bundle()
    writer = PrivateEvidenceWriter.create(destination)
    real_fsync = real_ab_evidence.os.fsync
    calls = {"count": 0}

    def failing_fsync(descriptor: int) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("durability failure before atomic publish")
        return real_fsync(descriptor)

    monkeypatch.setattr(real_ab_evidence.os, "fsync", failing_fsync)
    try:
        with pytest.raises(OSError):
            writer.write(bundle)
        assert calls["count"] == 1
        # A durability failure before publish must leave no final-named
        # evidence file and no scratch behind for a reader to observe.
        assert not (
            destination / real_ab_evidence.NORMALIZED_RESULTS_NAME
        ).exists()
        assert set(EVIDENCE_FILENAMES).isdisjoint(
            path.name for path in destination.iterdir()
        )
        assert list(destination.iterdir()) == []
    finally:
        monkeypatch.setattr(real_ab_evidence.os, "fsync", real_fsync)
        writer.close(remove_if_empty=True)

    assert not destination.exists()


def test_supervised_runner_closes_every_adapter_even_when_one_close_fails(
    tmp_path: Path,
) -> None:
    closed: list[str] = []
    adapters = {
        "flash": _ClosableAdapter("flash", closed, raise_on_close=True),
        "pro": _ClosableAdapter("pro", closed),
    }
    output_dir = tmp_path / "close-failure"

    def lane_runner(frozen, built):
        del frozen, built
        raise ValueError("lane failure forces teardown")

    result = execute_supervised_runner(
        cases_path=_CASES_PATH,
        smoke_cases_path=_SMOKE_PATH,
        smoke_manifest_path=_SMOKE_MANIFEST_PATH,
        output_dir=output_dir,
        sensitive_value="runner-sensitive-nonce",
        adapter_builder=lambda: adapters,
        lane_runner=lane_runner,
        control_runner=lambda frozen, built: pytest.fail(
            "control must not run after lane failure"
        ),
        evidence_builder=lambda built, reports, control: pytest.fail(
            "evidence must not build after lane failure"
        ),
    )

    assert result == 2
    assert sorted(closed) == ["flash", "pro"]
    assert not output_dir.exists()


def test_supervised_runner_cleans_scratch_and_empty_dir_when_publish_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    closed: list[str] = []
    adapters = {"only": _ClosableAdapter("only", closed)}
    bundle = _safe_bundle()
    output_dir = tmp_path / "publish-failure"
    real_fsync = real_ab_evidence.os.fsync
    state = {"count": 0}

    def failing_fsync(descriptor: int) -> None:
        state["count"] += 1
        if state["count"] == 1:
            raise OSError("publish durability failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(real_ab_evidence.os, "fsync", failing_fsync)
    result = execute_supervised_runner(
        cases_path=_CASES_PATH,
        smoke_cases_path=_SMOKE_PATH,
        smoke_manifest_path=_SMOKE_MANIFEST_PATH,
        output_dir=output_dir,
        sensitive_value="runner-sensitive-nonce",
        adapter_builder=lambda: adapters,
        lane_runner=lambda frozen, built: {},
        control_runner=lambda frozen, built: None,
        evidence_builder=lambda built, reports, control: (bundle, 0),
    )

    assert result == 2
    assert closed == ["only"]
    assert not output_dir.exists()
