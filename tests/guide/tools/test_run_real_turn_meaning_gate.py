from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticTokenUsage,
    TurnMeaningCallResult,
)
from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import build_selection_concept_assets
from tools.guide_gates.run_real_turn_meaning_gate import (
    run_real_gate,
)
from tools.guide_gates.turn_meaning_gate import load_gate_cases


_CASES = Path(
    "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
)


def _catalog() -> ConceptPreferenceCatalog:
    return ConceptPreferenceCatalog.from_projections(
        build_selection_concept_assets().projections
    )


def _meaning(case) -> TurnMeaning:
    operation = (
        case.translation.allowed_operation_hints[0].value
    )
    recommendation_mode = (
        case.execution.expected_recommendation_mode
        if operation in {"recommendation", "image_similarity"}
        else None
    )
    recommendation_basis = (
        case.execution.expected_recommendation_mode_basis
        if recommendation_mode is not None
        else None
    )
    return TurnMeaning.model_validate(
        {
            "operation_hint": operation,
            "recommendation_mode": recommendation_mode,
            "recommendation_count": (
                1 if recommendation_mode == "fit" else None
            ),
            "recommendation_mode_basis": (
                {
                    "basis": recommendation_basis,
                    "source_text": case.message,
                }
                if recommendation_basis is not None
                else None
            ),
            "topic_hint": (
                case.translation.allowed_topic_hints[0].value
                if case.translation.allowed_topic_hints[0] is not None
                else None
            ),
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [
                {
                    "code": item.code,
                    "present": item.present,
                    "qualifier": item.qualifier,
                    "raw_text": _observation_source(
                        case.message,
                        item.code,
                    ),
                }
                for item in case.translation.required_observations
            ],
            "preference_candidates": [],
            "relative_candidates": [],
            "question_meaning": (
                "当前问题的简要语义"
                if case.translation.require_question_meaning
                else None
            ),
            "safety_language": "ordinary",
        },
        strict=True,
    )


def _observation_source(message: str, code: str) -> str:
    markers = {
        "tightness": ("紧绷", "发紧", "干巴巴"),
        "flaking": ("起皮", "卡粉"),
        "oiliness": ("油",),
        "redness": ("泛红", "脸红"),
        "stinging": ("刺痛",),
        "current_budget_unknown": ("不知道该花多少预算",),
    }[code]
    return next(marker for marker in markers if marker in message)


class RecordingAdapter:
    model = "offline/turn-meaning"

    def __init__(self, meanings: dict[str, TurnMeaning]) -> None:
        self.meanings = meanings
        self.calls: list[str] = []

    def propose_with_result(self, message, context):
        del context
        self.calls.append(message)
        return TurnMeaningCallResult(
            meaning=self.meanings[message],
            usage=SemanticTokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cached_tokens=0,
            ),
        )


class InvalidAdapter:
    model = "offline/invalid"

    def __init__(self) -> None:
        self.calls = 0

    def propose_with_result(self, message, context):
        del message, context
        self.calls += 1
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_OUTPUT
        )


class MostlyValidAdapter:
    model = "offline/mostly-valid"

    def __init__(
        self,
        *,
        meaning: TurnMeaning,
        invalid_call_count: int,
    ) -> None:
        self.meaning = meaning
        self.invalid_call_count = invalid_call_count
        self.calls = 0

    def propose_with_result(self, message, context):
        del message, context
        self.calls += 1
        if self.calls <= self.invalid_call_count:
            raise SemanticProviderFailure(
                SemanticProviderFailureCode.INVALID_OUTPUT
            )
        return TurnMeaningCallResult(
            meaning=self.meaning,
            usage=SemanticTokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cached_tokens=0,
            ),
        )


def test_runner_calls_provider_once_per_case_and_writes_hashed_evidence(
    tmp_path: Path,
) -> None:
    cases = tuple(
        case
        for case in load_gate_cases(_CASES)
        if not case.binding.expected_objects
        and not case.translation.required_preferences
        and case.translation.required_budget is None
    )[:4]
    adapter = RecordingAdapter({
        case.message: _meaning(case)
        for case in cases
    })

    report = run_real_gate(
        adapter=adapter,
        cases=cases,
        concept_catalog=_catalog(),
        output_dir=tmp_path / "evidence",
    )

    assert len(adapter.calls) == len(cases)
    assert len(set(adapter.calls)) == len(cases)
    assert report.provider_call_count == len(cases)
    assert report.schema_valid_count == len(cases)
    assert report.total_tokens == len(cases) * 15
    assert report.results_sha256
    assert (tmp_path / "evidence" / "results.jsonl").is_file()
    assert (tmp_path / "evidence" / "summary.json").is_file()
    assert (tmp_path / "evidence" / "SHA256SUMS").is_file()
    recorded_hashes = {
        name: digest
        for digest, name in (
            line.split()
            for line in (
                tmp_path / "evidence" / "SHA256SUMS"
            ).read_text(encoding="ascii").splitlines()
        )
    }
    for name in ("results.jsonl", "summary.json"):
        assert recorded_hashes[name] == sha256(
            (tmp_path / "evidence" / name).read_bytes()
        ).hexdigest()


def test_invalid_output_is_not_retried_or_compiled(
    tmp_path: Path,
) -> None:
    case = load_gate_cases(_CASES)[0]
    adapter = InvalidAdapter()

    report = run_real_gate(
        adapter=adapter,
        cases=(case,),
        concept_catalog=_catalog(),
        output_dir=tmp_path / "invalid",
    )

    assert adapter.calls == 1
    assert report.provider_call_count == 1
    assert report.schema_valid_count == 0
    assert report.passed_count == 0
    row = json.loads(
        (tmp_path / "invalid" / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert row["status"] == "invalid_output"
    assert row["evaluation"] is None


def test_schema_failures_count_against_end_to_end_rate_without_requiring_100_percent_schema_validity(
    tmp_path: Path,
) -> None:
    prototype = load_gate_cases(_CASES)[0]
    cases = tuple(
        prototype.model_copy(
            update={
                "case_id": f"schema-rate-{index:03d}",
                "message": f"{prototype.message} {index}",
            },
            deep=True,
        )
        for index in range(128)
    )
    adapter = MostlyValidAdapter(
        meaning=_meaning(prototype),
        invalid_call_count=7,
    )

    report = run_real_gate(
        adapter=adapter,
        cases=cases,
        concept_catalog=_catalog(),
        output_dir=tmp_path / "schema-rate",
    )

    assert adapter.calls == 128
    assert report.schema_valid_count == 121
    assert report.passed_count == 121
    assert report.end_to_end_rate == 121 / 128
    assert report.passed


def test_runner_rejects_duplicate_case_ids_before_provider_call(
    tmp_path: Path,
) -> None:
    case = load_gate_cases(_CASES)[0]
    adapter = RecordingAdapter({case.message: _meaning(case)})

    try:
        run_real_gate(
            adapter=adapter,
            cases=(case, case),
            concept_catalog=_catalog(),
            output_dir=tmp_path / "duplicate",
        )
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("duplicate gate cases must fail")

    assert adapter.calls == []
