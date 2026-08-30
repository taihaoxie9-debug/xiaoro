#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Sequence
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.retrieval.general_knowledge_query import (
    build_knowledge_query_spec,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.knowledge_relation_contracts import (
    KnowledgeRelationIntent,
)
from app.guide_runtime.composition import build_general_knowledge_assets


REPORT_SCHEMA = "guide-general-knowledge-recall-v1"


class GeneralKnowledgeRecallGateError(ValueError):
    pass


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class GeneralKnowledgeRecallCase(_StrictFrozenModel):
    case_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    query: str = Field(min_length=1, max_length=4000)
    question_meaning: str = Field(min_length=1, max_length=512)
    topic: TopicCode | None
    relation_hints: tuple[KnowledgeRelationIntent, ...]
    expected_source_paths: tuple[str, ...]
    allowed_source_paths: tuple[str, ...]
    expected_section_titles: tuple[str, ...]
    allowed_section_titles: tuple[str, ...]
    expected_missing_relations: tuple[KnowledgeRelationIntent, ...] = ()
    expected_no_hit: bool = False
    safety_sensitive: bool = False

    @field_validator(
        "relation_hints",
        "expected_source_paths",
        "allowed_source_paths",
        "expected_section_titles",
        "allowed_section_titles",
        "expected_missing_relations",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_expectations(self) -> Self:
        for name in (
            "relation_hints",
            "expected_source_paths",
            "allowed_source_paths",
            "expected_section_titles",
            "allowed_section_titles",
            "expected_missing_relations",
        ):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be ordered unique")
        if not set(self.expected_source_paths) <= set(
            self.allowed_source_paths
        ):
            raise ValueError(
                "expected sources must be allowed"
            )
        if not set(self.expected_section_titles) <= set(
            self.allowed_section_titles
        ):
            raise ValueError(
                "expected sections must be allowed"
            )
        if self.expected_no_hit:
            if (
                self.expected_source_paths
                or self.allowed_source_paths
                or self.expected_section_titles
                or self.allowed_section_titles
            ):
                raise ValueError(
                    "no-hit case forbids citation expectations"
                )
        elif (
            not self.expected_source_paths
            or not self.allowed_source_paths
            or not self.expected_section_titles
            or not self.allowed_section_titles
        ):
            raise ValueError(
                "hit case requires source and section expectations"
            )
        return self


class GeneralKnowledgeRecallCaseResult(_StrictFrozenModel):
    case_id: str
    passed: bool
    actual_source_paths: tuple[str, ...]
    actual_section_titles: tuple[str, ...]
    missing_expected_sources: tuple[str, ...]
    missing_expected_sections: tuple[str, ...]
    wrong_source_paths: tuple[str, ...]
    wrong_section_titles: tuple[str, ...]
    missing_entity_ids: tuple[str, ...]
    missing_relation_intents: tuple[KnowledgeRelationIntent, ...]
    deterministic: bool


class GeneralKnowledgeRecallReport(_StrictFrozenModel):
    schema_version: Literal[
        "guide-general-knowledge-recall-v1"
    ] = REPORT_SCHEMA
    passed: bool
    case_count: int = Field(ge=0)
    represented_source_count: int = Field(ge=0)
    recall_at_3: float = Field(ge=0.0, le=1.0)
    wrong_topic_citation_count: int = Field(ge=0)
    wrong_section_citation_count: int = Field(ge=0)
    entity_coverage_failure_count: int = Field(ge=0)
    relation_coverage_failure_count: int = Field(ge=0)
    deterministic_mismatch_count: int = Field(ge=0)
    failed_case_ids: tuple[str, ...]


def load_recall_cases(
    path: Path,
) -> tuple[GeneralKnowledgeRecallCase, ...]:
    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise GeneralKnowledgeRecallGateError(
            "general knowledge recall fixture is unavailable"
        ) from exc
    if not lines or any(not line for line in lines):
        raise GeneralKnowledgeRecallGateError(
            "general knowledge recall fixture is empty or malformed"
        )
    cases: list[GeneralKnowledgeRecallCase] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            cases.append(
                GeneralKnowledgeRecallCase.model_validate_json(
                    line,
                    strict=True,
                )
            )
        except ValueError as exc:
            raise GeneralKnowledgeRecallGateError(
                f"invalid recall case line {line_number}"
            ) from exc
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise GeneralKnowledgeRecallGateError(
            "general knowledge recall fixture has duplicate case IDs"
        )
    return tuple(cases)


def _case_result(
    *,
    case: GeneralKnowledgeRecallCase,
    retriever: GeneralKnowledgeRetriever,
) -> GeneralKnowledgeRecallCaseResult:
    query = build_knowledge_query_spec(
        raw_query=case.query,
        question_meaning=case.question_meaning,
        topic=case.topic,
        relation_hints=case.relation_hints,
        safety_sensitive=case.safety_sensitive,
        prior_knowledge_ids=(),
        top_k=3,
    )
    packet = retriever.retrieve(query)
    repeated = retriever.retrieve(query)
    deterministic = (
        packet.model_dump_json() == repeated.model_dump_json()
    )
    actual_sources = tuple(
        dict.fromkeys(hit.block.source_path for hit in packet.hits)
    )
    actual_sections = tuple(
        dict.fromkeys(hit.block.section_title for hit in packet.hits)
    )
    missing_sources = tuple(
        source
        for source in case.expected_source_paths
        if source not in actual_sources
    )
    missing_sections = tuple(
        section
        for section in case.expected_section_titles
        if section not in actual_sections
    )
    wrong_sources = tuple(
        source
        for source in actual_sources
        if source not in case.allowed_source_paths
    )
    wrong_sections = tuple(
        section
        for section in actual_sections
        if section not in case.allowed_section_titles
    )
    coverage = packet.coverage
    if coverage is None:
        raise GeneralKnowledgeRecallGateError(
            "typed retriever omitted knowledge coverage"
        )
    no_hit_matches = bool(packet.hits) is not case.expected_no_hit
    relation_matches = (
        coverage.missing_relation_intents
        == case.expected_missing_relations
    )
    passed = (
        no_hit_matches
        and not missing_sources
        and not missing_sections
        and not wrong_sources
        and not wrong_sections
        and not coverage.missing_entity_ids
        and relation_matches
        and deterministic
    )
    return GeneralKnowledgeRecallCaseResult(
        case_id=case.case_id,
        passed=passed,
        actual_source_paths=actual_sources,
        actual_section_titles=actual_sections,
        missing_expected_sources=missing_sources,
        missing_expected_sections=missing_sections,
        wrong_source_paths=wrong_sources,
        wrong_section_titles=wrong_sections,
        missing_entity_ids=coverage.missing_entity_ids,
        missing_relation_intents=coverage.missing_relation_intents,
        deterministic=deterministic,
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def run_general_knowledge_recall_gate(
    *,
    cases_path: Path,
    output_dir: Path,
) -> GeneralKnowledgeRecallReport:
    cases = load_recall_cases(cases_path)
    assets = build_general_knowledge_assets()
    retriever = GeneralKnowledgeRetriever(assets.blocks)
    results = tuple(
        _case_result(case=case, retriever=retriever)
        for case in cases
    )
    represented_sources = {
        source
        for case in cases
        if case.case_id.startswith("gk-topic-")
        for source in case.expected_source_paths
    }
    expected_source_count = sum(
        len(case.expected_source_paths)
        for case in cases
        if not case.expected_no_hit
    )
    recovered_source_count = sum(
        len(case.expected_source_paths)
        - len(result.missing_expected_sources)
        for case, result in zip(cases, results, strict=True)
        if not case.expected_no_hit
    )
    recall_at_3 = (
        recovered_source_count / expected_source_count
        if expected_source_count
        else 0.0
    )
    wrong_topic_count = sum(
        len(result.wrong_source_paths) for result in results
    )
    wrong_section_count = sum(
        len(result.wrong_section_titles) for result in results
    )
    entity_failures = sum(
        bool(result.missing_entity_ids) for result in results
    )
    relation_failures = sum(
        result.missing_relation_intents
        != case.expected_missing_relations
        for case, result in zip(cases, results, strict=True)
    )
    deterministic_failures = sum(
        not result.deterministic for result in results
    )
    failed_case_ids = tuple(
        result.case_id for result in results if not result.passed
    )
    report = GeneralKnowledgeRecallReport(
        passed=(
            len(represented_sources) == 22
            and recall_at_3 == 1.0
            and wrong_topic_count == 0
            and wrong_section_count == 0
            and entity_failures == 0
            and relation_failures == 0
            and deterministic_failures == 0
            and not failed_case_ids
        ),
        case_count=len(cases),
        represented_source_count=len(represented_sources),
        recall_at_3=recall_at_3,
        wrong_topic_citation_count=wrong_topic_count,
        wrong_section_citation_count=wrong_section_count,
        entity_coverage_failure_count=entity_failures,
        relation_coverage_failure_count=relation_failures,
        deterministic_mismatch_count=deterministic_failures,
        failed_case_ids=failed_case_ids,
    )

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    results_path = destination / "results.jsonl"
    results_bytes = (
        "".join(
            json.dumps(
                result.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for result in results
        )
    ).encode("utf-8")
    results_path.write_bytes(results_bytes)
    summary_path = destination / "summary.json"
    _write_json(summary_path, report.model_dump(mode="json"))
    checksums = (
        f"{sha256(results_bytes).hexdigest()}  results.jsonl\n"
        f"{sha256(summary_path.read_bytes()).hexdigest()}  summary.json\n"
    )
    (destination / "SHA256SUMS").write_text(
        checksums,
        encoding="utf-8",
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_general_knowledge_recall_gate(
        cases_path=args.cases,
        output_dir=args.output,
    )
    print(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return int(not report.passed)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GeneralKnowledgeRecallCase",
    "GeneralKnowledgeRecallGateError",
    "GeneralKnowledgeRecallReport",
    "load_recall_cases",
    "main",
    "run_general_knowledge_recall_gate",
]
