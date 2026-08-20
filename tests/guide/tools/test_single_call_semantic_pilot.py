from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tools.guide_gates.single_call_semantic_pilot import (
    PilotCompletion,
    PilotObservation,
    PilotPreference,
    PilotReference,
    PilotTranslation,
    build_pilot_messages,
    evaluate_translation,
    ground_reference,
    load_pilot_cases,
    run_pilot,
)


_CASES = Path(
    "tests/fixtures/guide/intent/"
    "single_call_semantic_pilot_v1.jsonl"
)


def _translation(
    case_id: str,
) -> PilotTranslation:
    payloads = {
        "rec-006-paraphrase-sunscreen": {
            "goal": "recommendation",
            "topic": "sunscreen",
            "preferences": [
                {
                    "field": "usage_context",
                    "raw_text": "通勤",
                    "strength": "preference",
                },
                {
                    "field": "texture",
                    "raw_text": "不搓泥",
                    "strength": "preference",
                },
            ],
        },
        "cmp-002-two-serums": {
            "goal": "comparison",
            "topic": "serum",
            "references": [
                {"kind": "current_batch", "raw_text": "两支"}
            ],
        },
        "suit-001-sensitive-sunscreen": {
            "goal": "suitability",
            "topic": "sunscreen",
            "references": [
                {"kind": "current_item", "raw_text": "这个防晒"}
            ],
            "preferences": [
                {
                    "field": "suitable_skin",
                    "raw_text": "敏感肌",
                    "strength": "preference",
                }
            ],
            "safety_sensitive": False,
        },
        "img-001-find-similar-first": {
            "goal": "image_similarity",
            "topic": None,
            "references": [
                {"kind": "image_ordinal", "raw_text": "第一张图"}
            ],
        },
        "know-006-fragrance-notes": {
            "goal": "knowledge",
            "topic": "fragrance",
            "question_meaning": "询问香水前中后调变化的原因",
        },
        "assess-001-post-cleanse-tight": {
            "goal": "assessment",
            "topic": "cleanser",
            "observations": [
                {
                    "code": "tightness",
                    "present": True,
                    "qualifier": "post_cleanse",
                    "raw_text": "洗完脸紧绷",
                },
                {
                    "code": "flaking",
                    "present": True,
                    "qualifier": "post_cleanse",
                    "raw_text": "起皮",
                },
            ],
        },
        "follow-009-budget-revision": {
            "goal": "followup",
            "topic": "sunscreen",
            "references": [
                {"kind": "previous_constraint", "raw_text": "预算"}
            ],
            "preferences": [
                {
                    "field": "ingredient_exclusion",
                    "raw_text": "不要含酒精",
                    "strength": "unknown",
                }
            ],
            "budget_mentions": ["三百以内"],
        },
        "clar-015-revision-missing-target": {
            "goal": "clarification",
            "topic": "sunscreen",
        },
    }
    payload = {
        "references": [],
        "observations": [],
        "preferences": [],
        "budget_mentions": [],
        "product_mentions": [],
        "question_meaning": None,
        "safety_sensitive": False,
        **payloads[case_id],
    }
    return PilotTranslation.model_validate(payload, strict=True)


def test_loads_eight_unique_business_families() -> None:
    cases = load_pilot_cases(_CASES)

    assert len(cases) == 8
    assert len({case.case_id for case in cases}) == 8
    assert {case.family for case in cases} == {
        "assessment",
        "clarification",
        "comparison",
        "followup",
        "image",
        "knowledge",
        "recommendation",
        "suitability",
    }


def test_reference_contract_forbids_model_offsets() -> None:
    with pytest.raises(ValidationError):
        PilotReference.model_validate(
            {
                "kind": "image_ordinal",
                "raw_text": "第一张",
                "start": 2,
                "end": 5,
            },
            strict=True,
        )


@pytest.mark.parametrize("raw_text", ["第一张", "第一张图"])
def test_equivalent_image_spans_resolve_to_same_binding(
    raw_text: str,
) -> None:
    case = next(
        case
        for case in load_pilot_cases(_CASES)
        if case.case_id == "img-001-find-similar-first"
    )

    grounded = ground_reference(
        message=case.message,
        reference=PilotReference(
            kind="image_ordinal",
            raw_text=raw_text,
        ),
        authority=case.binding_authority,
    )

    assert grounded.kind == "image_ordinal"
    assert grounded.ordinal == 1
    assert case.message[grounded.start:grounded.end] == raw_text


def test_invented_reference_is_rejected() -> None:
    case = next(
        case
        for case in load_pilot_cases(_CASES)
        if case.case_id == "img-001-find-similar-first"
    )

    with pytest.raises(ValueError, match="uniquely"):
        ground_reference(
            message=case.message,
            reference=PilotReference(
                kind="image_ordinal",
                raw_text="第二张",
            ),
            authority=case.binding_authority,
        )


def test_other_candidate_text_is_not_an_ordinal() -> None:
    case = next(
        case
        for case in load_pilot_cases(_CASES)
        if case.case_id == "clar-015-revision-missing-target"
    )

    with pytest.raises(ValueError, match="not parseable"):
        ground_reference(
            message=case.message,
            reference=PilotReference(
                kind="candidate_ordinal",
                raw_text="另一个",
            ),
            authority=case.binding_authority,
        )


def test_evaluator_accepts_required_meaning_without_full_json_equality() -> None:
    case = next(
        case
        for case in load_pilot_cases(_CASES)
        if case.case_id == "suit-001-sensitive-sunscreen"
    )
    proposal = _translation(case.case_id).model_copy(
        update={
            "preferences": (
                *_translation(case.case_id).preferences,
                PilotPreference(
                    field="usage_context",
                    raw_text="用",
                    strength="preference",
                ),
            )
        }
    )

    result = evaluate_translation(case=case, translation=proposal)

    assert result.accepted is True
    assert result.missing_requirements == ()


def test_evaluator_rejects_missing_required_observation() -> None:
    case = next(
        case
        for case in load_pilot_cases(_CASES)
        if case.case_id == "assess-001-post-cleanse-tight"
    )
    proposal = _translation(case.case_id).model_copy(
        update={
            "observations": (
                PilotObservation(
                    code="tightness",
                    present=True,
                    qualifier="post_cleanse",
                    raw_text="洗完脸紧绷",
                ),
            )
        }
    )

    result = evaluate_translation(case=case, translation=proposal)

    assert result.accepted is False
    assert "observation:flaking:true:post_cleanse" in (
        result.missing_requirements
    )


def test_prompt_is_one_universal_schema_without_offsets() -> None:
    case = load_pilot_cases(_CASES)[0]

    system, user = build_pilot_messages(case)

    assert '"start"' not in system["content"]
    assert '"end"' not in system["content"]
    assert "route stage" not in system["content"].lower()
    assert "detail stage" not in system["content"].lower()
    assert json.loads(user["content"])["message"] == case.message


def test_fake_run_invokes_completion_exactly_once_per_case(
    tmp_path: Path,
) -> None:
    cases = load_pilot_cases(_CASES)
    by_message = {case.message: case for case in cases}
    calls: list[str] = []

    def complete(messages) -> PilotCompletion:
        message = json.loads(messages[1]["content"])["message"]
        calls.append(message)
        proposal = _translation(by_message[message].case_id)
        return PilotCompletion(
            content=proposal.model_dump_json(),
            prompt_tokens=100,
            completion_tokens=50,
        )

    summary = run_pilot(
        cases=cases,
        output_dir=tmp_path / "evidence",
        complete=complete,
        model="test-model",
    )

    assert len(calls) == 8
    assert len(set(calls)) == 8
    assert summary.case_count == 8
    assert summary.provider_call_count == 8
    assert summary.accepted_count == 8
    assert summary.total_tokens == 1200
    assert (tmp_path / "evidence" / "results.jsonl").is_file()
    assert (tmp_path / "evidence" / "summary.json").is_file()
    assert (tmp_path / "evidence" / "SHA256SUMS").is_file()
