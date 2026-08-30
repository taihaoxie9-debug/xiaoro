from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from tools.guide_gates.run_general_knowledge_recall_gate import (
    GeneralKnowledgeRecallGateError,
    load_recall_cases,
    run_general_knowledge_recall_gate,
)


ROOT = Path(__file__).resolve().parents[3]
CASES = (
    ROOT
    / "tests"
    / "fixtures"
    / "guide"
    / "general_knowledge"
    / "general_knowledge_recall_v1.jsonl"
)


EXPECTED_TOPIC_MATRIX = (
    ("敏感肌护肤品应该怎么选？", "怎么选"),
    ("混油皮日常护肤怎么安排？", "怎么选"),
    ("干皮怎么做好保湿和修护？", "怎么选"),
    ("痘肌选护肤品要避开什么？", "避雷与注意"),
    ("皮肤屏障受损后怎么修护？", "怎么选"),
    ("防晒为什么过几个小时还要补涂？", "避雷与注意"),
    ("不同功效的精华应该怎么选？", "怎么选"),
    ("油皮夏天应该怎么选面霜？", "怎么选"),
    ("洁面产品应该怎么选？", "怎么选"),
    ("卸妆油和卸妆水怎么选？", "怎么选"),
    ("眼霜怎么按眼周问题选择？", "怎么选"),
    ("补水面膜和医用敷料有什么区别？", "怎么选"),
    ("烟酰胺有什么作用？", "关键成分/原理"),
    ("A醇怎么建立耐受？", "避雷与注意"),
    ("水杨酸适合什么人？", "适合谁"),
    ("玻色因和肽类有什么区别？", "关键成分/原理"),
    ("维C白天到底能不能用？", "避雷与注意"),
    ("油皮应该怎么选粉底液？", "怎么选"),
    ("散粉、粉饼和定妆喷雾怎么选？", "怎么选"),
    ("日常通勤口红怎么选？", "怎么选"),
    ("干敏肌怎么温和抗初老？", "适合谁"),
    ("怎么判断自己是不是敏感肌？", "怎么判断是不是敏感肌"),
)


def _write_cases(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _case_rows() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in CASES.read_text(encoding="utf-8").splitlines()
    ]


def test_recall_fixture_covers_all_sources_and_targeted_variants() -> None:
    cases = load_recall_cases(CASES)

    assert len(cases) == 28
    topic_cases = tuple(
        case for case in cases if case.case_id.startswith("gk-topic-")
    )
    assert tuple(
        (case.query, case.expected_section_titles[0])
        for case in topic_cases
    ) == EXPECTED_TOPIC_MATRIX
    assert len({
        source
        for case in topic_cases
        for source in case.expected_source_paths
    }) == 22
    assert {
        "gk-multi-niacinamide-retinol",
        "gk-alias-niacinamide-retinol",
        "gk-alias-vc-daytime",
        "gk-alias-ascorbic-daytime",
        "gk-direct-vitamin-c-retinol-compatibility",
        "gk-no-hit-weather",
    } <= {case.case_id for case in cases}


def test_recall_fixture_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    first = CASES.read_text(encoding="utf-8").splitlines()[0]
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(f"{first}\n{first}\n", encoding="utf-8")

    with pytest.raises(
        GeneralKnowledgeRecallGateError,
        match="duplicate case",
    ):
        load_recall_cases(duplicate)


def test_gate_rejects_missing_source_topic_representation(
    tmp_path: Path,
) -> None:
    rows = _case_rows()
    incomplete = tmp_path / "incomplete.jsonl"
    _write_cases(incomplete, rows[1:])

    report = run_general_knowledge_recall_gate(
        cases_path=incomplete,
        output_dir=tmp_path / "missing-source-result",
    )

    assert not report.passed
    assert report.represented_source_count == 21


def test_gate_rejects_unlisted_citation_paths(tmp_path: Path) -> None:
    rows = _case_rows()
    rows[0]["expected_source_paths"] = [
        "data/knowledge_docs/02-油皮与混油皮护肤方案.md"
    ]
    rows[0]["allowed_source_paths"] = [
        "data/knowledge_docs/02-油皮与混油皮护肤方案.md"
    ]
    unlisted = tmp_path / "unlisted.jsonl"
    _write_cases(unlisted, rows)

    report = run_general_knowledge_recall_gate(
        cases_path=unlisted,
        output_dir=tmp_path / "unlisted-result",
    )

    assert not report.passed
    assert report.wrong_topic_citation_count >= 1


def test_gate_rejects_non_deterministic_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = GeneralKnowledgeRetriever.retrieve
    invocation_count = 0

    def unstable_retrieve(self, query):
        nonlocal invocation_count
        packet = original(self, query)
        invocation_count += 1
        if invocation_count % 2 == 0 and packet.hits:
            first = packet.hits[0].model_copy(
                update={"score": packet.hits[0].score + 0.001}
            )
            return packet.model_copy(
                update={"hits": (first, *packet.hits[1:])}
            )
        return packet

    monkeypatch.setattr(
        GeneralKnowledgeRetriever,
        "retrieve",
        unstable_retrieve,
    )
    report = run_general_knowledge_recall_gate(
        cases_path=CASES,
        output_dir=tmp_path / "unstable-result",
    )

    assert not report.passed
    assert report.deterministic_mismatch_count > 0


def test_gate_replaces_its_own_deterministic_outputs(
    tmp_path: Path,
) -> None:
    output = tmp_path / "repeatable-result"
    first = run_general_knowledge_recall_gate(
        cases_path=CASES,
        output_dir=output,
    )
    first_bytes = {
        path.name: path.read_bytes()
        for path in output.iterdir()
    }

    second = run_general_knowledge_recall_gate(
        cases_path=CASES,
        output_dir=output,
    )

    assert second == first
    assert {
        path.name: path.read_bytes()
        for path in output.iterdir()
    } == first_bytes


def test_production_recall_matrix_is_green(tmp_path: Path) -> None:
    report = run_general_knowledge_recall_gate(
        cases_path=CASES,
        output_dir=tmp_path / "recall",
    )

    assert report.passed
    assert report.case_count == 28
    assert report.represented_source_count == 22
    assert report.recall_at_3 == 1.0
    assert report.wrong_topic_citation_count == 0
    assert report.wrong_section_citation_count == 0
    assert report.entity_coverage_failure_count == 0
    assert report.relation_coverage_failure_count == 0
    assert report.deterministic_mismatch_count == 0
    assert (tmp_path / "recall" / "results.jsonl").is_file()
    assert (tmp_path / "recall" / "summary.json").is_file()
    assert (tmp_path / "recall" / "SHA256SUMS").is_file()
