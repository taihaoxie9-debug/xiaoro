from __future__ import annotations

import json
from pathlib import Path

from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    CopywriterSection,
    SourceTaggedCopy,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
from tools.guide_gates.presentation_copy_gate import (
    load_copy_gate_cases,
)
from tools.guide_gates.replay_presentation_copy_contract import (
    replay_copywriter_contract_results,
)


FIXTURE = Path(
    "tests/fixtures/guide/presentation/copy_gate_v3_production.jsonl"
)


def _write_results(path: Path, drafts: list[dict[str, object]]) -> None:
    cases = load_copy_gate_cases(FIXTURE)[: len(drafts)]
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "case_id": case.case_id,
                    "draft": draft,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for case, draft in zip(cases, drafts, strict=True)
        )
        + "\n",
        encoding="utf-8",
    )


def test_contract_replay_separates_legacy_and_section_drafts(
    tmp_path: Path,
) -> None:
    cases = load_copy_gate_cases(FIXTURE)
    legacy = {
        "mode": cases[0].mode,
        "summary_copy": {
            "text": "旧格式摘要。",
            "used_fact_ids": [],
            "used_constraint_ids": [],
        },
        "product_copy": [],
        "closing_copy": None,
    }
    section = CopywriterDraft(
        mode=cases[1].mode,
        sections=(
            CopywriterSection(
                kind="summary",
                content=SourceTaggedCopy(
                    text="两款路线不同，直接看对比表。"
                ),
            ),
        ),
    ).model_dump(mode="json")
    source = tmp_path / "results.jsonl"
    output = tmp_path / "replay.json"
    _write_results(source, [legacy, section])

    report = replay_copywriter_contract_results(
        cases=cases[:2],
        results_path=source,
        output_path=output,
    )

    assert report.provider_call_count == 0
    assert report.legacy_universal_count == 1
    assert report.section_draft_count == 1
    assert report.parser_invalid_count == 0
    assert report.rows[0].classification == "legacy_universal_contract"
    assert report.rows[1].classification == "section_contract"
    assert output.is_file()


def test_contract_replay_rejects_section_without_winner_claim(
    tmp_path: Path,
) -> None:
    case = load_copy_gate_cases(FIXTURE)[0]
    draft = CopywriterDraft.model_validate(
        {
            "mode": case.mode,
            "sections": [
                {
                    "kind": "summary",
                    "slot_id": None,
                    "content": {
                        "text": "先按需求看清使用取舍。",
                        "used_fact_ids": [],
                        "used_constraint_ids": [],
                    },
                    "advisor_reason": None,
                },
                *[
                    section.model_dump(mode="json")
                    for section in fallback_copy(case.packet).sections[1:]
                ],
            ],
        },
        strict=True,
    ).model_dump(mode="json")
    del draft["sections"][0]["content"]["winner_claim"]
    source = tmp_path / "results.jsonl"
    output = tmp_path / "replay.json"
    _write_results(source, [draft])

    report = replay_copywriter_contract_results(
        cases=(case,),
        results_path=source,
        output_path=output,
    )

    assert report.parser_invalid_count == 1
    assert report.rows[0].classification == "parser_invalid"
