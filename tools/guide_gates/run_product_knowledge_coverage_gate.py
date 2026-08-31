#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Collection, Sequence
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.application.product_evidence_answer import (
    build_product_knowledge_answer_plan,
    render_product_evidence_fact,
)
from app.guide.presentation.public_fact_contracts import (
    ProductPublicFactProjection,
    ProjectedPublicFact,
)
from app.guide.retrieval.product_evidence_assets import ProductEvidenceBlock
from app.guide.retrieval.product_evidence_reader import (
    ProductEvidenceReader,
)
from app.guide.retrieval.product_evidence_retrieval import (
    EvidencePacket,
    EvidenceQuery,
    ProductEvidenceRetriever,
    prepare_evidence_search,
    product_evidence_dimensions,
)
from app.guide_runtime.composition import build_product_evidence_reader


REPORT_SCHEMA = "guide-product-knowledge-coverage-v1"
_PRODUCTION_ANSWERABLE_COUNT = 1079
_PRODUCTION_FAQ_COUNT = 47
_PRODUCTION_NON_ANSWER_COUNT = 183
_FAQ_CATEGORIES = frozenset({
    "ingredients",
    "usage",
    "specification",
    "skin_fit",
    "texture",
    "version",
    "packaging",
    "storage",
    "batch",
    "authenticity",
    "safety",
    "other",
})
_FIELD_KEY_BY_LABEL = {
    "merchant_claim": "brand_main",
    "brand_research": "brand_main",
    "usage": "usage",
    "product_specification": "net_content",
    "packaging_information": "packaging_information",
    "faq": "faq",
    "consumer_self_report": "consumer_report",
    "merchant_cited_test": "merchant_test",
    "safety_transcript": "safety_information",
    "unclassified": "product_information",
}
_LABEL_BY_FIELD = {
    "brand_main": "品牌主打",
    "usage": "使用方法",
    "net_content": "商品信息",
    "packaging_information": "包装信息",
    "faq": "使用问答",
    "consumer_report": "使用反馈",
    "merchant_test": "品牌测试",
    "safety_information": "使用提醒",
    "product_information": "商品信息",
}


class ProductKnowledgeCoverageGateError(ValueError):
    pass


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class ProductKnowledgeFaqCase(_StrictFrozenModel):
    case_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    category: Literal[
        "ingredients",
        "usage",
        "specification",
        "skin_fit",
        "texture",
        "version",
        "packaging",
        "storage",
        "batch",
        "authenticity",
        "safety",
        "other",
    ]
    product_id: int = Field(gt=0)
    product_name: str = Field(min_length=1, max_length=160)
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    direct_question: str = Field(min_length=1, max_length=256)
    question_meaning: str = Field(min_length=1, max_length=256)
    paraphrases: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    expected_dimensions: tuple[str, ...] = ()
    safety_sensitive: bool = False

    @field_validator(
        "paraphrases",
        "expected_dimensions",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        if (
            self.paraphrases != tuple(dict.fromkeys(self.paraphrases))
            or any(
                not value.strip() or len(value) > 256
                for value in self.paraphrases
            )
            or self.direct_question in self.paraphrases
        ):
            raise ValueError(
                "FAQ paraphrases must be ordered unique questions"
            )
        if (
            self.expected_dimensions
            != tuple(dict.fromkeys(self.expected_dimensions))
            or any(
                re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value) is None
                for value in self.expected_dimensions
            )
        ):
            raise ValueError(
                "expected dimensions must be ordered unique keys"
            )
        return self


class ProductKnowledgeCoverageQueryResult(_StrictFrozenModel):
    query_id: str
    query_kind: Literal[
        "answerable_self",
        "non_answer",
        "faq_direct",
        "faq_paraphrase",
    ]
    product_id: int
    expected_evidence_id: str
    query_text: str
    selected_evidence_ids: tuple[str, ...]
    top5_match: bool
    non_answer_evidence_ids: tuple[str, ...]
    cross_product_evidence_ids: tuple[str, ...]
    wrong_variant_evidence_ids: tuple[str, ...]
    requested_dimensions: tuple[str, ...]
    covered_dimensions: tuple[str, ...]
    used_fact_ids: tuple[str, ...]
    safety_caveats: tuple[str, ...]
    answer_coverage_passed: bool
    deterministic: bool
    passed: bool


class ProductKnowledgeCoverageReport(_StrictFrozenModel):
    schema_version: Literal[
        "guide-product-knowledge-coverage-v1"
    ] = REPORT_SCHEMA
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_count: int = Field(ge=0)
    answerable_count: int = Field(ge=0)
    answerable_top5_count: int = Field(ge=0)
    non_answer_count: int = Field(ge=0)
    faq_count: int = Field(ge=0)
    faq_direct_top5_count: int = Field(ge=0)
    faq_paraphrase_count: int = Field(ge=0)
    faq_paraphrase_top5_count: int = Field(ge=0)
    faq_category_count: int = Field(ge=0)
    non_answer_selection_count: int = Field(ge=0)
    cross_product_selection_count: int = Field(ge=0)
    wrong_variant_selection_count: int = Field(ge=0)
    answer_coverage_failure_count: int = Field(ge=0)
    deterministic_mismatch_count: int = Field(ge=0)
    failed_query_ids: tuple[str, ...]
    passed: bool


def load_faq_cases(
    path: Path,
) -> tuple[ProductKnowledgeFaqCase, ...]:
    source = Path(path)
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ProductKnowledgeCoverageGateError(
            "product knowledge FAQ fixture is unavailable"
        ) from exc
    if not lines or any(not line for line in lines):
        raise ProductKnowledgeCoverageGateError(
            "product knowledge FAQ fixture is empty or malformed"
        )
    cases: list[ProductKnowledgeFaqCase] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            cases.append(
                ProductKnowledgeFaqCase.model_validate_json(
                    line,
                    strict=True,
                )
            )
        except ValueError as exc:
            raise ProductKnowledgeCoverageGateError(
                f"invalid product knowledge FAQ case line {line_number}"
            ) from exc
    case_ids = tuple(case.case_id for case in cases)
    if case_ids != tuple(dict.fromkeys(case_ids)):
        raise ProductKnowledgeCoverageGateError(
            "product knowledge FAQ fixture has duplicate case IDs"
        )
    return tuple(cases)


def validate_faq_case_inventory(
    cases: Collection[ProductKnowledgeFaqCase],
    *,
    reader: ProductEvidenceReader,
) -> None:
    frozen = tuple(cases)
    if any(
        not isinstance(case, ProductKnowledgeFaqCase)
        for case in frozen
    ):
        raise TypeError(
            "cases must contain ProductKnowledgeFaqCase values"
        )
    blocks = _all_evidence_blocks(reader)
    faq_by_id = {
        block.evidence_id: block
        for block in blocks
        if (
            block.review_status == "accepted"
            and "answer" in block.allowed_uses
            and block.management_label == "faq"
        )
    }
    case_ids = tuple(case.evidence_id for case in frozen)
    case_counts = {
        evidence_id: case_ids.count(evidence_id)
        for evidence_id in set(case_ids)
    }
    if (
        set(case_ids) != set(faq_by_id)
        or any(count != 1 for count in case_counts.values())
    ):
        raise ProductKnowledgeCoverageGateError(
            "every accepted FAQ evidence ID must appear exactly once"
        )
    for case in frozen:
        block = faq_by_id[case.evidence_id]
        if block.product_id != case.product_id:
            raise ProductKnowledgeCoverageGateError(
                f"{case.case_id} product ID does not match evidence"
            )
        block_dimensions = set(product_evidence_dimensions(block))
        if not set(case.expected_dimensions) <= block_dimensions:
            raise ProductKnowledgeCoverageGateError(
                f"{case.case_id} expected dimensions exceed evidence"
            )


def _all_evidence_blocks(
    reader: ProductEvidenceReader,
) -> tuple[ProductEvidenceBlock, ...]:
    if not isinstance(reader, ProductEvidenceReader):
        raise TypeError("reader must be ProductEvidenceReader")
    return tuple(
        block
        for product_id in reader.product_ids
        for block in reader.read(product_id=product_id)
    )


def _safety_sensitive(block: ProductEvidenceBlock) -> bool:
    return (
        block.management_label == "safety_transcript"
        or (
            block.selection_review is not None
            and block.selection_review.decision == "safety_gate"
        )
    )


def _identity_name(
    *,
    product_name: str | None,
    block: ProductEvidenceBlock,
) -> tuple[str, ...]:
    values = tuple(
        value.strip()
        for value in (product_name, block.variant_scope)
        if isinstance(value, str) and value.strip()
    )
    if not values:
        return ()
    return (" ".join(dict.fromkeys(values)),)


def _query(
    *,
    block: ProductEvidenceBlock,
    source_text: str,
    question_meaning: str,
    requested_dimensions: tuple[str, ...],
    safety_sensitive: bool,
    product_name: str | None = None,
) -> EvidenceQuery:
    return EvidenceQuery(
        product_ids=(block.product_id,),
        search=prepare_evidence_search(
            source_text=source_text,
            question_meaning=question_meaning,
        ),
        safety_sensitive=safety_sensitive,
        requested_dimensions=requested_dimensions,
        product_identity_names=_identity_name(
            product_name=product_name,
            block=block,
        ),
    )


def _project_packet(
    packet: EvidencePacket,
    *,
    product_name: str,
) -> ProductPublicFactProjection:
    facts: list[ProjectedPublicFact] = []
    for selection in packet.selected:
        block = selection.evidence
        field_key = _FIELD_KEY_BY_LABEL[block.management_label]
        attribution: Literal[
            "verified_fact",
            "merchant_claim",
            "consumer_report",
        ]
        source_kind: Literal[
            "category",
            "evidence",
            "merchant",
            "review",
        ]
        if block.management_label == "consumer_self_report":
            attribution = "consumer_report"
            source_kind = "review"
        elif block.management_label in {
            "merchant_claim",
            "merchant_cited_test",
            "safety_transcript",
            "faq",
            "brand_research",
        }:
            attribution = "merchant_claim"
            source_kind = "merchant"
        else:
            attribution = "verified_fact"
            source_kind = "evidence"
        facts.append(
            ProjectedPublicFact(
                fact_id=f"evidence:{block.evidence_id}",
                product_id=block.product_id,
                field_key=field_key,
                label=_LABEL_BY_FIELD[field_key],
                display_value=render_product_evidence_fact(
                    block,
                    product_name=product_name,
                ),
                source_refs=(block.source.source_locator,),
                source_kind=source_kind,
                attribution=attribution,
            )
        )
    return ProductPublicFactProjection(
        product_id=packet.query.product_ids[0],
        facts=tuple(facts),
    )


def _wrong_variant_ids(
    packet: EvidencePacket,
    *,
    target: ProductEvidenceBlock,
) -> tuple[str, ...]:
    if (
        target.subject_scope != "exact_variant"
        or target.variant_scope is None
    ):
        return ()
    target_predicates = {
        relation.predicate for relation in target.relations
    }
    return tuple(
        selection.evidence.evidence_id
        for selection in packet.selected
        if (
            selection.evidence.evidence_id != target.evidence_id
            and selection.evidence.subject_scope == "exact_variant"
            and selection.evidence.variant_scope is not None
            and selection.evidence.variant_scope
            != target.variant_scope
            and bool(
                target_predicates
                & {
                    relation.predicate
                    for relation in selection.evidence.relations
                }
            )
        )
    )


def _coverage_result(
    *,
    packet: EvidencePacket,
    target: ProductEvidenceBlock,
    product_name: str,
    question: str,
    requested_dimensions: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    evidence_dimensions = {
        f"evidence:{selection.evidence.evidence_id}": (
            selection.covered_dimensions
        )
        for selection in packet.selected
    }
    plan = build_product_knowledge_answer_plan(
        projection=_project_packet(
            packet,
            product_name=product_name,
        ),
        question=question,
        requested_dimensions=requested_dimensions,
        evidence_dimensions=evidence_dimensions,
    )
    unrelated_used = tuple(
        fact_id
        for fact_id in plan.used_fact_ids
        if (
            requested_dimensions
            and
            fact_id.startswith("evidence:")
            and not (
                set(
                    evidence_dimensions.get(fact_id, ())
                )
                & set(requested_dimensions)
            )
        )
    )
    target_fact_id = f"evidence:{target.evidence_id}"
    passed = (
        set(requested_dimensions) <= set(plan.covered_dimensions)
        and not unrelated_used
        and target_fact_id in plan.used_fact_ids
        and (
            not packet.query.safety_sensitive
            or bool(packet.safety_caveats)
        )
    )
    return plan.covered_dimensions, plan.used_fact_ids, passed


def _query_result(
    *,
    query_id: str,
    query_kind: Literal[
        "answerable_self",
        "non_answer",
        "faq_direct",
        "faq_paraphrase",
    ],
    target: ProductEvidenceBlock,
    query: EvidenceQuery,
    query_text: str,
    retriever: ProductEvidenceRetriever,
    non_answer_ids: frozenset[str],
    product_name: str,
    check_answer_coverage: bool,
    check_wrong_variant: bool,
) -> ProductKnowledgeCoverageQueryResult:
    packet = retriever.retrieve(query)
    repeated = retriever.retrieve(query)
    deterministic = (
        packet.model_dump_json() == repeated.model_dump_json()
    )
    selected_ids = tuple(
        selection.evidence.evidence_id
        for selection in packet.selected
    )
    selected_non_answer = tuple(
        evidence_id
        for evidence_id in selected_ids
        if evidence_id in non_answer_ids
    )
    cross_product = tuple(
        selection.evidence.evidence_id
        for selection in packet.selected
        if selection.evidence.product_id not in query.product_ids
    )
    wrong_variant = (
        ()
        if not check_wrong_variant
        else _wrong_variant_ids(packet, target=target)
    )
    top5_match = target.evidence_id in selected_ids[:5]
    if (
        check_answer_coverage
        and not selected_non_answer
        and not cross_product
        and not wrong_variant
    ):
        covered, used_fact_ids, coverage_passed = _coverage_result(
            packet=packet,
            target=target,
            product_name=product_name,
            question=query_text,
            requested_dimensions=query.requested_dimensions,
        )
    else:
        covered = ()
        used_fact_ids = ()
        coverage_passed = not check_answer_coverage
    expected_selected = query_kind != "non_answer"
    passed = (
        (top5_match is expected_selected)
        and not selected_non_answer
        and not cross_product
        and not wrong_variant
        and coverage_passed
        and deterministic
    )
    return ProductKnowledgeCoverageQueryResult(
        query_id=query_id,
        query_kind=query_kind,
        product_id=target.product_id,
        expected_evidence_id=target.evidence_id,
        query_text=query_text,
        selected_evidence_ids=selected_ids,
        top5_match=top5_match,
        non_answer_evidence_ids=selected_non_answer,
        cross_product_evidence_ids=cross_product,
        wrong_variant_evidence_ids=wrong_variant,
        requested_dimensions=query.requested_dimensions,
        covered_dimensions=covered,
        used_fact_ids=used_fact_ids,
        safety_caveats=packet.safety_caveats,
        answer_coverage_passed=coverage_passed,
        deterministic=deterministic,
        passed=passed,
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


def _write_outputs(
    *,
    output_dir: Path,
    results: tuple[ProductKnowledgeCoverageQueryResult, ...],
    report: ProductKnowledgeCoverageReport,
) -> None:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    results_path = destination / "results.jsonl"
    results_bytes = "".join(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for result in results
    ).encode("utf-8")
    results_path.write_bytes(results_bytes)
    summary_path = destination / "summary.json"
    _write_json(summary_path, report.model_dump(mode="json"))
    (destination / "SHA256SUMS").write_text(
        (
            f"{sha256(results_bytes).hexdigest()}  results.jsonl\n"
            f"{sha256(summary_path.read_bytes()).hexdigest()}  summary.json\n"
        ),
        encoding="utf-8",
    )


def run_product_knowledge_coverage_gate(
    *,
    repo_root: Path,
    cases_path: Path,
    output_dir: Path,
    reader: ProductEvidenceReader | None = None,
) -> ProductKnowledgeCoverageReport:
    root = Path(repo_root).resolve()
    evidence_reader = (
        reader
        if reader is not None
        else build_product_evidence_reader(root)
    )
    if not isinstance(evidence_reader, ProductEvidenceReader):
        raise TypeError("reader must be ProductEvidenceReader")
    cases = load_faq_cases(cases_path)
    validate_faq_case_inventory(cases, reader=evidence_reader)
    blocks = _all_evidence_blocks(evidence_reader)
    block_by_id = {
        block.evidence_id: block
        for block in blocks
    }
    answerable = tuple(
        block
        for block in blocks
        if (
            block.review_status == "accepted"
            and "answer" in block.allowed_uses
        )
    )
    non_answer = tuple(
        block
        for block in blocks
        if not (
            block.review_status == "accepted"
            and "answer" in block.allowed_uses
        )
    )
    non_answer_ids = frozenset(
        block.evidence_id for block in non_answer
    )
    retriever = ProductEvidenceRetriever(evidence_reader)
    results: list[ProductKnowledgeCoverageQueryResult] = []

    for block in answerable:
        dimensions = product_evidence_dimensions(block)
        query = _query(
            block=block,
            source_text=block.plain_meaning,
            question_meaning=block.plain_meaning,
            requested_dimensions=dimensions,
            safety_sensitive=_safety_sensitive(block),
        )
        results.append(
            _query_result(
                query_id=f"answerable:{block.evidence_id}",
                query_kind="answerable_self",
                target=block,
                query=query,
                query_text=block.plain_meaning,
                retriever=retriever,
                non_answer_ids=non_answer_ids,
                product_name=f"商品{block.product_id}",
                check_answer_coverage=False,
                check_wrong_variant=False,
            )
        )

    for block in non_answer:
        dimensions = product_evidence_dimensions(block)
        query = _query(
            block=block,
            source_text=block.plain_meaning,
            question_meaning=block.plain_meaning,
            requested_dimensions=dimensions,
            safety_sensitive=_safety_sensitive(block),
        )
        results.append(
            _query_result(
                query_id=f"non-answer:{block.evidence_id}",
                query_kind="non_answer",
                target=block,
                query=query,
                query_text=block.plain_meaning,
                retriever=retriever,
                non_answer_ids=non_answer_ids,
                product_name=f"商品{block.product_id}",
                check_answer_coverage=False,
                check_wrong_variant=False,
            )
        )

    for case in cases:
        block = block_by_id[case.evidence_id]
        questions = (
            ("direct", case.direct_question),
            *tuple(
                (f"paraphrase:{index}", paraphrase)
                for index, paraphrase in enumerate(
                    case.paraphrases,
                    start=1,
                )
            ),
        )
        for query_suffix, question in questions:
            query_kind: Literal[
                "faq_direct",
                "faq_paraphrase",
            ] = (
                "faq_direct"
                if query_suffix == "direct"
                else "faq_paraphrase"
            )
            query = _query(
                block=block,
                source_text=question,
                question_meaning=case.question_meaning,
                requested_dimensions=case.expected_dimensions,
                safety_sensitive=case.safety_sensitive,
                product_name=case.product_name,
            )
            results.append(
                _query_result(
                    query_id=f"faq:{case.case_id}:{query_suffix}",
                    query_kind=query_kind,
                    target=block,
                    query=query,
                    query_text=question,
                    retriever=retriever,
                    non_answer_ids=non_answer_ids,
                    product_name=case.product_name,
                    check_answer_coverage=True,
                    check_wrong_variant=True,
                )
            )

    frozen_results = tuple(results)
    answerable_results = tuple(
        result
        for result in frozen_results
        if result.query_kind == "answerable_self"
    )
    direct_results = tuple(
        result
        for result in frozen_results
        if result.query_kind == "faq_direct"
    )
    paraphrase_results = tuple(
        result
        for result in frozen_results
        if result.query_kind == "faq_paraphrase"
    )
    non_answer_selection_count = sum(
        len(result.non_answer_evidence_ids)
        for result in frozen_results
    )
    cross_product_selection_count = sum(
        len(result.cross_product_evidence_ids)
        for result in frozen_results
    )
    wrong_variant_selection_count = sum(
        len(result.wrong_variant_evidence_ids)
        for result in frozen_results
    )
    answer_coverage_failure_count = sum(
        not result.answer_coverage_passed
        for result in (*direct_results, *paraphrase_results)
    )
    deterministic_mismatch_count = sum(
        not result.deterministic
        for result in frozen_results
    )
    answerable_top5_count = sum(
        result.top5_match for result in answerable_results
    )
    faq_direct_top5_count = sum(
        result.top5_match for result in direct_results
    )
    faq_paraphrase_top5_count = sum(
        result.top5_match for result in paraphrase_results
    )
    faq_categories = {
        case.category for case in cases
    }
    failed_query_ids = tuple(
        result.query_id
        for result in frozen_results
        if not result.passed
    )
    production_inventory = (
        len(answerable) == _PRODUCTION_ANSWERABLE_COUNT
        and len(non_answer) == _PRODUCTION_NON_ANSWER_COUNT
        and len(cases) == _PRODUCTION_FAQ_COUNT
        and faq_categories == _FAQ_CATEGORIES
    )
    passed = (
        production_inventory
        and answerable_top5_count == len(answerable)
        and faq_direct_top5_count == len(cases)
        and faq_paraphrase_top5_count == len(paraphrase_results)
        and non_answer_selection_count == 0
        and cross_product_selection_count == 0
        and wrong_variant_selection_count == 0
        and answer_coverage_failure_count == 0
        and deterministic_mismatch_count == 0
        and not failed_query_ids
    )
    report = ProductKnowledgeCoverageReport(
        manifest_sha256=evidence_reader.manifest.manifest_sha256,
        evidence_count=len(blocks),
        answerable_count=len(answerable),
        answerable_top5_count=answerable_top5_count,
        non_answer_count=len(non_answer),
        faq_count=len(cases),
        faq_direct_top5_count=faq_direct_top5_count,
        faq_paraphrase_count=len(paraphrase_results),
        faq_paraphrase_top5_count=faq_paraphrase_top5_count,
        faq_category_count=len(faq_categories),
        non_answer_selection_count=non_answer_selection_count,
        cross_product_selection_count=cross_product_selection_count,
        wrong_variant_selection_count=wrong_variant_selection_count,
        answer_coverage_failure_count=answer_coverage_failure_count,
        deterministic_mismatch_count=deterministic_mismatch_count,
        failed_query_ids=failed_query_ids,
        passed=passed,
    )
    _write_outputs(
        output_dir=output_dir,
        results=frozen_results,
        report=report,
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_product_knowledge_coverage_gate(
        repo_root=args.repo_root,
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
    "ProductKnowledgeCoverageGateError",
    "ProductKnowledgeCoverageQueryResult",
    "ProductKnowledgeCoverageReport",
    "ProductKnowledgeFaqCase",
    "load_faq_cases",
    "main",
    "run_product_knowledge_coverage_gate",
    "validate_faq_case_inventory",
]
