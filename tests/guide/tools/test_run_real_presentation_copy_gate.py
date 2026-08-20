from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticTokenUsage,
)
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
from app.guide.presentation.copywriter_contracts import (
    CopywriterSection,
    SourceTaggedCopy,
)
from tools.guide_gates.presentation_copy_gate import load_copy_gate_cases
from tools.guide_gates.run_real_presentation_copy_gate import (
    replay_real_copy_gate_results,
    run_real_copy_gate,
    validate_copywriter_call_budget,
)
from tools.guide_gates import run_real_presentation_copy_gate as runner


FIXTURE = Path(
    "tests/fixtures/guide/presentation/copy_gate_v3_production.jsonl"
)


def test_real_copy_gate_uses_production_token_limit() -> None:
    assert getattr(runner, "COPY_GATE_MAX_TOKENS", None) == 1536


def test_real_copy_gate_defaults_to_production_v3_fixture() -> None:
    assert Path(runner.DEFAULT_CASES).resolve() == FIXTURE.resolve()


def test_copywriter_budget_guard_preserves_browser_reserve() -> None:
    with pytest.raises(ValueError, match="call cap"):
        validate_copywriter_call_budget(
            prior_calls=20,
            requested_calls=20,
            reserved_future_calls=15,
            call_cap=35,
        )

    assert validate_copywriter_call_budget(
        prior_calls=20,
        requested_calls=20,
        reserved_future_calls=15,
        call_cap=55,
    ) == 55


def test_cli_rejects_call_cap_before_key_or_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "must-not-exist"
    result = subprocess.run(
        [
            sys.executable,
            "tools/guide_gates/run_real_presentation_copy_gate.py",
            "--cases",
            str(FIXTURE),
            "--output-dir",
            str(output),
            "--run-id",
            "budget-rejected",
            "--key-path",
            str(tmp_path / "missing-key"),
            "--prior-call-count",
            "20",
            "--copywriter-call-cap",
            "35",
            "--reserved-future-calls",
            "15",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 6
    assert "copywriter_call_cap_rejected" in result.stdout
    assert "key_precheck_failed" not in result.stdout
    assert not output.exists()


def _qualifying_draft(packet):
    draft = fallback_copy(packet)
    slots_by_id = {slot.slot_id: slot for slot in packet.slots}
    sections = []
    for section in draft.sections:
        slot = (
            slots_by_id[section.slot_id]
            if section.slot_id is not None
            else None
        )
        if section.kind == "product":
            assert slot is not None
            merchant_ids = tuple(
                fact.fact_id
                for fact in slot.approved_soft_facts
                if fact.attribution == "merchant_claim"
            )
            consumer_ids = tuple(
                fact.fact_id
                for fact in slot.approved_soft_facts
                if fact.attribution == "consumer_report"
            )
            sections.append(
                section.model_copy(
                    update={
                        "content": SourceTaggedCopy(
                            text=(
                                "品牌主打的功效、肤感与使用场景各有侧重。"
                            ),
                            used_fact_ids=merchant_ids,
                        ),
                        "advisor_reason": SourceTaggedCopy(
                            text=(
                                "限定样本的用户反馈只作体验参考。"
                                if consumer_ids
                                else "未给出的部分不作推断。"
                            ),
                            used_fact_ids=consumer_ids,
                        ),
                    }
                )
            )
        elif slot is not None:
            merchant_ids = tuple(
                fact.fact_id
                for fact in slot.approved_soft_facts
                if fact.attribution == "merchant_claim"
            )
            consumer_ids = tuple(
                fact.fact_id
                for fact in slot.approved_soft_facts
                if fact.attribution == "consumer_report"
            )
            sections.append(
                section.model_copy(
                    update={
                        "content": SourceTaggedCopy(
                            text=(
                                "品牌主打的相关方向可作参考。"
                                + (
                                    "限定样本的用户反馈只作体验参考。"
                                    if consumer_ids
                                    else ""
                                )
                            ),
                            used_fact_ids=(
                                *merchant_ids,
                                *consumer_ids,
                            ),
                        )
                    }
                )
            )
        else:
            sections.append(section)
    return draft.model_copy(update={"sections": tuple(sections)})


def _replace_section(
    draft,
    replacement: CopywriterSection,
):
    return draft.model_copy(
        update={
            "sections": tuple(
                replacement
                if (
                    section.kind,
                    section.slot_id,
                )
                == (
                    replacement.kind,
                    replacement.slot_id,
                )
                else section
                for section in draft.sections
            )
        }
    )


class RecordingAdapter:
    provider = "offline"
    model = "offline/copywriter"

    def __init__(self) -> None:
        self.calls = []

    def write(self, packet):
        self.calls.append(packet)
        draft = _qualifying_draft(packet)
        return CopywriterCallResult(
            draft=draft,
            usage=SemanticTokenUsage(
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
                cached_tokens=0,
            ),
            provider=self.provider,
            model=self.model,
            latency_ms=12.0,
            raw_content=draft.model_dump_json(),
            trace_id="offline-copy-trace",
        )


class InvalidAdapter:
    provider = "offline"
    model = "offline/invalid"

    def __init__(self) -> None:
        self.calls = 0

    def write(self, packet):
        del packet
        self.calls += 1
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_OUTPUT,
            raw_content="{not-json",
            trace_id="copy-invalid-trace",
            usage=SemanticTokenUsage(
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
                cached_tokens=0,
            ),
        )


class DurabilityRecordingAdapter(RecordingAdapter):
    def __init__(self, output: Path) -> None:
        super().__init__()
        self._output = output
        self.persisted_before_calls: list[tuple[int, int]] = []

    def write(self, packet):
        results = self._output / "results.jsonl"
        partial = self._output / "partial-summary.json"
        result_count = (
            len(results.read_text(encoding="utf-8").splitlines())
            if results.exists()
            else 0
        )
        partial_count = (
            json.loads(partial.read_text(encoding="utf-8"))[
                "provider_call_count"
            ]
            if partial.exists()
            else 0
        )
        self.persisted_before_calls.append(
            (result_count, partial_count)
        )
        return super().write(packet)


class OneTerseAdapter(RecordingAdapter):
    def write(self, packet):
        result = super().write(packet)
        if len(self.calls) != 1:
            return result
        summary = next(
            section
            for section in result.draft.sections
            if section.kind == "summary"
        )
        return result.model_copy(
            update={
                "draft": _replace_section(
                    result.draft,
                    summary.model_copy(
                        update={
                            "content": summary.content.model_copy(
                                update={
                                    "text": "过短。",
                                    "used_fact_ids": (),
                                }
                            )
                        }
                    ),
                )
            }
        )


class ThreeTerseAdapter(RecordingAdapter):
    def write(self, packet):
        result = super().write(packet)
        if len(self.calls) > 3:
            return result
        summary = next(
            section
            for section in result.draft.sections
            if section.kind == "summary"
        )
        return result.model_copy(
            update={
                "draft": _replace_section(
                    result.draft,
                    summary.model_copy(
                        update={
                            "content": summary.content.model_copy(
                                update={
                                    "text": "过短。",
                                    "used_fact_ids": (),
                                }
                            )
                        }
                    ),
                )
            }
        )


class HardFailureAdapter(RecordingAdapter):
    def write(self, packet):
        result = super().write(packet)
        product = next(
            section
            for section in result.draft.sections
            if section.kind == "product"
        )
        return result.model_copy(
            update={
                "draft": _replace_section(
                    result.draft,
                    product.model_copy(
                        update={
                            "content": product.content.model_copy(
                                update={
                                    "used_fact_ids": ("unknown-fact",),
                                }
                            )
                        }
                    ),
                )
            }
        )


def test_real_runner_calls_once_and_writes_content_addressed_evidence(
    tmp_path: Path,
) -> None:
    cases = load_copy_gate_cases(FIXTURE)[:3]
    adapter = RecordingAdapter()
    output = tmp_path / "official-run-1"

    report = run_real_copy_gate(
        adapter=adapter,
        cases=cases,
        output_dir=output,
        run_id="official-run-1",
    )

    assert len(adapter.calls) == len(cases)
    assert report.case_count == len(cases)
    assert report.provider_call_count == len(cases)
    assert report.prompt_version == runner.PRESENTATION_COPY_PROMPT_VERSION
    assert len(report.cases_sha256) == 64
    assert report.schema_valid_rate == 1.0
    assert report.readability_rate == 1.0
    assert report.fact_coverage_rate == 1.0
    assert report.minimum_fact_coverage >= 0.8
    assert report.internal_language_rate == 1.0
    assert report.hard_violation_count == 0
    assert report.total_tokens == len(cases) * 30
    assert report.passed
    checksums = {
        name: digest
        for digest, name in (
            line.split()
            for line in (output / "SHA256SUMS")
            .read_text(encoding="ascii")
            .splitlines()
        )
    }
    for name in ("results.jsonl", "summary.json"):
        assert checksums[name] == sha256(
            (output / name).read_bytes()
        ).hexdigest()
    first = json.loads(
        (output / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert first["raw_provider_output"]
    assert first["trace_id"] == "offline-copy-trace"


def test_zero_api_replay_rescores_immutable_real_results(
    tmp_path: Path,
) -> None:
    cases = load_copy_gate_cases(FIXTURE)[:3]
    source = tmp_path / "source"
    run_real_copy_gate(
        adapter=RecordingAdapter(),
        cases=cases,
        output_dir=source,
        run_id="source",
    )
    destination = tmp_path / "replay.json"

    report = replay_real_copy_gate_results(
        cases=cases,
        results_path=source / "results.jsonl",
        output_path=destination,
    )

    assert report.case_count == 3
    assert report.replayed_case_count == 3
    assert report.provider_call_count == 0
    assert report.passed_count == 3
    assert report.passed
    assert len(report.source_results_sha256) == 64
    assert len(report.cases_sha256) == 64
    assert destination.is_file()
    persisted = json.loads(destination.read_text(encoding="utf-8"))
    assert persisted["provider_call_count"] == 0
    assert len(persisted["rows"]) == 3


def test_real_runner_allows_two_ordinary_misses(tmp_path: Path) -> None:
    cases = load_copy_gate_cases(FIXTURE)

    report = run_real_copy_gate(
        adapter=OneTerseAdapter(),
        cases=cases,
        output_dir=tmp_path / "nineteen-of-twenty",
        run_id="nineteen-of-twenty",
    )

    assert report.case_count == 20
    assert report.passed_count == 19
    assert report.hard_violation_count == 0
    assert report.passed


def test_real_runner_rejects_below_eighteen_of_twenty(
    tmp_path: Path,
) -> None:
    cases = load_copy_gate_cases(FIXTURE)

    report = run_real_copy_gate(
        adapter=ThreeTerseAdapter(),
        cases=cases,
        output_dir=tmp_path / "seventeen-of-twenty",
        run_id="seventeen-of-twenty",
    )

    assert report.case_count == 20
    assert report.passed_count == 17
    assert report.hard_violation_count == 0
    assert not report.passed


def test_real_runner_stops_after_first_hard_failure(
    tmp_path: Path,
) -> None:
    cases = load_copy_gate_cases(FIXTURE)[:3]
    adapter = HardFailureAdapter()
    output = tmp_path / "hard-stop"

    report = run_real_copy_gate(
        adapter=adapter,
        cases=cases,
        output_dir=output,
        run_id="hard-stop",
    )

    assert len(adapter.calls) == 1
    assert report.case_count == 3
    assert report.completed_case_count == 1
    assert report.provider_call_count == 1
    assert report.stopped_early
    assert report.stop_reason == "hard_violation"
    assert not report.passed
    assert len(
        (output / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ) == 1


def test_real_copy_gate_persists_and_reports_after_each_attempt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases = load_copy_gate_cases(FIXTURE)[:3]
    output = tmp_path / "durable"
    adapter = DurabilityRecordingAdapter(output)

    run_real_copy_gate(
        adapter=adapter,
        cases=cases,
        output_dir=output,
        run_id="durable",
    )

    assert adapter.persisted_before_calls == [
        (0, 0),
        (1, 1),
        (2, 2),
    ]
    progress = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("progress ")
    ]
    assert len(progress) == 3
    assert "case_id=" in progress[0]
    assert "attempted_calls=1" in progress[0]
    assert "total_tokens=30" in progress[0]
    assert all("authorization" not in line.casefold() for line in progress)
    assert all("api_key" not in line.casefold() for line in progress)


def test_invalid_output_is_counted_without_retry(tmp_path: Path) -> None:
    case = load_copy_gate_cases(FIXTURE)[0]
    adapter = InvalidAdapter()
    output = tmp_path / "invalid"

    report = run_real_copy_gate(
        adapter=adapter,
        cases=(case,),
        output_dir=output,
        run_id="invalid",
    )

    assert adapter.calls == 1
    assert report.provider_call_count == 1
    assert report.schema_valid_count == 0
    assert report.total_tokens == 30
    assert not report.passed
    row = json.loads(
        (output / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert row["status"] == "invalid_output"
    assert len(row["input_sha256"]) == 64
    assert row["raw_provider_output"] == "{not-json"
    assert row["trace_id"] == "copy-invalid-trace"
    assert row["earliest_failure_layer"] == "public_presentation"
    assert row["total_tokens"] == 30
    assert row["evaluation"]["schema_valid"] is False


def test_real_runner_refuses_to_overwrite_evidence_directory(
    tmp_path: Path,
) -> None:
    case = load_copy_gate_cases(FIXTURE)[0]
    output = tmp_path / "immutable"
    run_real_copy_gate(
        adapter=RecordingAdapter(),
        cases=(case,),
        output_dir=output,
        run_id="immutable",
    )

    try:
        run_real_copy_gate(
            adapter=RecordingAdapter(),
            cases=(case,),
            output_dir=output,
            run_id="immutable",
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("gate evidence directory must be immutable")


def test_real_runner_rejects_duplicate_case_ids_before_call(
    tmp_path: Path,
) -> None:
    case = load_copy_gate_cases(FIXTURE)[0]
    adapter = RecordingAdapter()

    try:
        run_real_copy_gate(
            adapter=adapter,
            cases=(case, case),
            output_dir=tmp_path / "duplicate",
            run_id="duplicate",
        )
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("duplicate case IDs must fail")

    assert adapter.calls == []


def test_direct_cli_entrypoint_can_import_project_modules() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "tools/guide_gates/run_real_presentation_copy_gate.py",
            "--help",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--output-dir" in result.stdout
