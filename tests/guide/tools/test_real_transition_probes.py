from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal

from app.guide.adapters.llm.contracts import (
    SemanticTokenUsage,
    TurnMeaningCallResult,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from tools.guide_gates import real_transition_probes
from tools.guide_gates.real_transition_probes import (
    TransitionProbeCase,
    load_transition_probes,
    run_transition_probes,
)


def _meaning(
    *,
    operation: str = "suitability",
    topic: str = "serum",
    reference_mentions: list[dict[str, object]] | None = None,
) -> TurnMeaning:
    return TurnMeaning.model_validate(
        {
            "operation_hint": operation,
            "topic_hint": topic,
            "continuity_hint": "return_to_focus",
            "subject_scope_hint": "self",
            "reference_mentions": reference_mentions or [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "回到当前批次做适配比较",
            "safety_language": "ordinary",
        },
        strict=True,
    )


def _case() -> TransitionProbeCase:
    return TransitionProbeCase.model_validate_json(
        json.dumps(
            {
            "case_id": "comparison-batch-001",
            "state": "comparison_batch",
            "message": "回到刚才两款精华，按我这个状态哪款更适合？",
            "context": {
                "conversation_version": 2,
                "active_topic": "serum",
                "active_dialogue": "consultation",
                "visible_candidate_count": 2,
                "focused_candidate_ordinal": None,
                "image_count": 0,
                "confirmed_image_ordinals": [],
                "focused_image_ordinal": None,
                "active_constraint_kinds": [],
                "confirmed_profile_fields": [],
            },
            "allowed_operations": ["comparison", "suitability"],
            "allowed_topics": ["serum"],
            "required_reference": "product_batch",
            "forbidden_operations": ["image_identity"],
            },
            ensure_ascii=False,
        ),
        strict=True,
    )


class _RecordingAdapter:
    model = "offline/transition-probe"

    def __init__(self, meaning: TurnMeaning) -> None:
        self.meaning = meaning
        self.calls: list[str] = []

    def propose_with_result(self, message, context):
        del context
        self.calls.append(message)
        return TurnMeaningCallResult(
            meaning=self.meaning,
            usage=SemanticTokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cached_tokens=0,
            ),
        )


def test_probe_runner_calls_once_and_persists_hashed_evidence(
    tmp_path: Path,
) -> None:
    case = _case()
    adapter = _RecordingAdapter(
        _meaning(
            operation="suitability",
            reference_mentions=[
                {
                    "raw_text": "刚才两款",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "batch",
                    "batch_size_hint": 2,
                },
            ],
        )
    )

    report = run_transition_probes(
        adapter=adapter,
        cases=(case,),
        output_dir=tmp_path / "evidence",
    )

    assert adapter.calls == [case.message]
    assert report.case_count == 1
    assert report.provider_call_count == 1
    assert report.passed_count == 1
    assert report.passed
    assert (tmp_path / "evidence" / "results.jsonl").is_file()
    assert (tmp_path / "evidence" / "summary.json").is_file()


def test_probe_runner_rejects_batch_suitability_without_batch_reference(
    tmp_path: Path,
) -> None:
    adapter = _RecordingAdapter(_meaning(operation="suitability"))

    report = run_transition_probes(
        adapter=adapter,
        cases=(_case(),),
        output_dir=tmp_path / "missing-reference",
    )

    assert report.passed_count == 0
    assert not report.passed
    row = json.loads(
        (tmp_path / "missing-reference" / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert row["failures"] == ["required_reference"]


def test_probe_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    path = tmp_path / "probes.jsonl"
    row = _case().model_dump(mode="json")
    path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for _ in range(2)
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        load_transition_probes(path)
    except ValueError as error:
        assert str(error) == "transition probe case IDs must be unique"
    else:
        raise AssertionError("duplicate transition probe IDs were accepted")


def test_production_probe_sheet_has_three_cases_for_each_core_state() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "tests/fixtures/guide/intent/transition_probes_3x6_v1.jsonl"
    )
    cases = load_transition_probes(path)
    counts = {
        state: sum(case.state == state for case in cases)
        for state in {
            "recommendation_batch",
            "single_product_focus",
            "comparison_batch",
            "consultation",
            "general_knowledge",
            "confirmed_image_product",
        }
    }

    assert len(cases) == 18
    assert counts == {
        "recommendation_batch": 3,
        "single_product_focus": 3,
        "comparison_batch": 3,
        "consultation": 3,
        "general_knowledge": 3,
        "confirmed_image_product": 3,
    }


def test_single_product_suitability_is_a_valid_return_operation() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "tests/fixtures/guide/intent/transition_probes_3x6_v1.jsonl"
    )
    cases = load_transition_probes(path)
    case = next(
        item
        for item in cases
        if item.case_id == "single-product-002-return"
    )

    assert set(case.allowed_operations) == {
        "knowledge",
        "followup",
        "suitability",
    }


def test_transition_probe_budget_covers_the_full_real_sheet() -> None:
    assert real_transition_probes.DEFAULT_PROBE_DAILY_BUDGET_CNY >= Decimal(
        "100.00"
    )
