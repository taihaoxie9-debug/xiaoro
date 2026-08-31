from __future__ import annotations

from pathlib import Path

import pytest

from app.guide.application.product_evidence_answer import (
    ProductKnowledgeAnswerPlan,
)
from app.guide.presentation.public_fact_contracts import (
    ProjectedPublicFact,
)
from app.guide.retrieval.product_evidence_assets import (
    ProductEvidenceAssets,
    ProductEvidenceBlock,
    ProductEvidenceManifest,
    product_evidence_id,
)
from app.guide.retrieval.product_evidence_reader import (
    ProductEvidenceReader,
)
from app.guide.retrieval.product_evidence_retrieval import (
    EvidenceSelection,
    ProductEvidenceRetriever,
)
from app.guide_runtime.composition import build_product_evidence_reader
from tools.guide_gates.run_product_knowledge_coverage_gate import (
    ProductKnowledgeCoverageGateError,
    ProductKnowledgeFaqCase,
    load_faq_cases,
    run_product_knowledge_coverage_gate,
    validate_faq_case_inventory,
)


ROOT = Path(__file__).resolve().parents[3]
CASES = (
    ROOT
    / "tests"
    / "fixtures"
    / "guide"
    / "product_knowledge"
    / "product_knowledge_faq_rewrites_v1.jsonl"
)


def _source(product_id: int, index: int) -> dict[str, object]:
    source_sha = f"{product_id:064x}"[-64:]
    image_sha = f"{product_id * 100 + index:064x}"[-64:]
    return {
        "source_file": f"detail_{product_id}_ocr.json",
        "source_sha256": source_sha,
        "image_file": f"{index:03d}.jpg",
        "image_index": index,
        "image_sha256": image_sha,
        "source_locator": (
            "urn:xiaoro:product-detail-image:"
            f"pid:{product_id}:source-sha256:{source_sha}:"
            f"image-sha256:{image_sha}"
        ),
        "source_url": f"https://example.com/{product_id}/{index}.jpg",
        "recovery_status": "source_record",
        "resolved_image_file": f"{index:03d}.jpg",
        "image_region": [0, 0, 790, 1000],
    }


def _block(
    *,
    product_id: int,
    index: int,
    meaning: str,
    subject: str,
    object_value: str,
    predicate: str = "merchant_faq_answer",
    label: str = "faq",
    review_status: str = "accepted",
    subject_scope: str = "exact_product",
    variant_scope: str | None = None,
) -> ProductEvidenceBlock:
    accepted = review_status == "accepted"
    payload: dict[str, object] = {
        "product_id": product_id,
        "subject_scope": subject_scope,
        "variant_scope": variant_scope,
        "management_label": label,
        "transcription_basis": "visual_transcription",
        "exact_text": f"{subject}：{object_value}",
        "plain_meaning": meaning,
        "relations": [
            {
                "subject": subject,
                "predicate": predicate,
                "object": object_value,
            }
        ],
        "qualifiers": {
            "sample_size": None,
            "population": None,
            "method": None,
            "baseline": None,
            "duration": None,
            "disclaimer": "测试边界说明。",
            "footnotes": [],
        },
        "free_descriptors": [subject, object_value],
        "review_status": review_status,
        "allowed_uses": ["answer", "display"] if accepted else [],
        "forbidden_uses": ["hard_filter", "safety_guarantee"],
        "review_rationale": "商品知识门禁测试证据。",
        "selection_review": (
            {
                "decision": "answer_only",
                "visual_confirmed": True,
                "rationale": "只用于回答。",
                "projections": [],
            }
            if accepted
            else None
        ),
        "source": _source(product_id, index),
        "supporting_sources": [],
    }
    return ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )


def _reader(*blocks: ProductEvidenceBlock) -> ProductEvidenceReader:
    allowed_use_counts: dict[str, int] = {}
    for block in blocks:
        for allowed_use in block.allowed_uses:
            allowed_use_counts[allowed_use] = (
                allowed_use_counts.get(allowed_use, 0) + 1
            )
    manifest = ProductEvidenceManifest(
        asset_version="test",
        evidence_file=f"product_evidence_v1.{'1' * 64}.jsonl",
        evidence_sha256="1" * 64,
        audit_file=f"image_audit_v1.{'2' * 64}.jsonl",
        audit_sha256="2" * 64,
        evidence_count=len(blocks),
        product_count=len({block.product_id for block in blocks}),
        image_count=0,
        status_counts={},
        allowed_use_counts=allowed_use_counts,
        manifest_sha256="3" * 64,
    )
    return ProductEvidenceReader(
        ProductEvidenceAssets(
            manifest=manifest,
            evidence=blocks,
            audit=(),
        )
    )


def _case(
    block: ProductEvidenceBlock,
    *,
    case_id: str,
    direct_question: str,
    question_meaning: str,
    paraphrases: tuple[str, ...] = (),
    expected_dimensions: tuple[str, ...] = (),
    product_name: str = "测试商品",
) -> ProductKnowledgeFaqCase:
    return ProductKnowledgeFaqCase(
        case_id=case_id,
        category="usage",
        product_id=block.product_id,
        product_name=product_name,
        evidence_id=block.evidence_id,
        direct_question=direct_question,
        question_meaning=question_meaning,
        paraphrases=paraphrases,
        expected_dimensions=expected_dimensions,
        safety_sensitive=False,
    )


def _write_cases(
    path: Path,
    cases: tuple[ProductKnowledgeFaqCase, ...],
) -> None:
    path.write_text(
        "".join(
            case.model_dump_json() + "\n"
            for case in cases
        ),
        encoding="utf-8",
    )


def _run_with_reader(
    tmp_path: Path,
    *,
    reader: ProductEvidenceReader,
    cases: tuple[ProductKnowledgeFaqCase, ...],
):
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, cases)
    return run_product_knowledge_coverage_gate(
        repo_root=ROOT,
        cases_path=cases_path,
        output_dir=tmp_path / "output",
        reader=reader,
    )


def test_reviewed_fixture_covers_exact_runtime_faq_inventory() -> None:
    reader = build_product_evidence_reader(ROOT)
    cases = load_faq_cases(CASES)

    validate_faq_case_inventory(cases, reader=reader)

    assert len(cases) == 47
    assert len({case.case_id for case in cases}) == 47
    assert len({case.evidence_id for case in cases}) == 47
    assert {
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
    } == {case.category for case in cases}
    assert all(case.paraphrases for case in cases)


def test_fixture_inventory_rejects_missing_or_duplicate_faq_rows() -> None:
    reader = build_product_evidence_reader(ROOT)
    cases = load_faq_cases(CASES)

    with pytest.raises(
        ProductKnowledgeCoverageGateError,
        match="exactly once",
    ):
        validate_faq_case_inventory(cases[:-1], reader=reader)

    duplicate = cases[-1].model_copy(
        update={"case_id": f"{cases[-1].case_id}-duplicate"}
    )
    with pytest.raises(
        ProductKnowledgeCoverageGateError,
        match="exactly once",
    ):
        validate_faq_case_inventory(
            (*cases[:-1], cases[-1], duplicate),
            reader=reader,
        )


def test_gate_counts_direct_and_paraphrase_top5_misses(
    tmp_path: Path,
) -> None:
    target = _block(
        product_id=57,
        index=1,
        meaning="商家说明防晒应在出门前提前涂抹。",
        subject="防晒涂抹时点",
        object_value="出门前15分钟",
    )
    distractor = _block(
        product_id=57,
        index=2,
        meaning="商家说明防晒运输后应静置再开盖。",
        subject="运输后开盖",
        object_value="瓶口朝上静置2小时",
        label="packaging_information",
    )
    case = _case(
        target,
        case_id="faq-057-usage",
        direct_question="运输后打开前要静置多久？",
        question_meaning="询问运输后开盖处理",
        paraphrases=("刚收到是不是先放两个小时？",),
        expected_dimensions=("usage",),
    )

    report = _run_with_reader(
        tmp_path,
        reader=_reader(target, distractor),
        cases=(case,),
    )

    assert not report.passed
    assert report.faq_direct_top5_count == 0
    assert report.faq_paraphrase_top5_count == 0


def test_gate_counts_answerable_and_non_answer_permission_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answerable = _block(
        product_id=57,
        index=1,
        meaning="商家说明出门前15分钟涂防晒。",
        subject="防晒涂抹时点",
        object_value="出门前15分钟",
    )
    non_answer = _block(
        product_id=57,
        index=2,
        meaning="未通过审核的包装说法。",
        subject="未审核包装",
        object_value="不可回答",
        review_status="ambiguous",
    )
    reader = _reader(answerable, non_answer)
    original = ProductEvidenceRetriever.retrieve

    def leak_non_answer(self, query):
        packet = original(self, query)
        leaked = EvidenceSelection(
            evidence=non_answer,
            score=0.1,
            reasons=("injected_permission_leak",),
        )
        return packet.model_copy(
            update={"selected": (*packet.selected, leaked)}
        )

    monkeypatch.setattr(
        ProductEvidenceRetriever,
        "retrieve",
        leak_non_answer,
    )
    report = _run_with_reader(
        tmp_path,
        reader=reader,
        cases=(
            _case(
                answerable,
                case_id="faq-057-usage",
                direct_question="这款防晒要提前多久涂？",
                question_meaning="询问防晒涂抹时点",
                expected_dimensions=("usage",),
            ),
        ),
    )

    assert not report.passed
    assert report.non_answer_selection_count > 0


def test_gate_counts_cross_product_and_wrong_variant_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _block(
        product_id=57,
        index=1,
        meaning="第三代比第二代更轻薄。",
        subject="第三代相对第二代",
        object_value="更轻薄",
        predicate="merchant_version_comparison_claim",
        subject_scope="exact_variant",
        variant_scope="第三代",
    )
    wrong_variant = _block(
        product_id=57,
        index=2,
        meaning="第二代质地偏滋润。",
        subject="第二代",
        object_value="偏滋润",
        predicate="merchant_version_comparison_claim",
        subject_scope="exact_variant",
        variant_scope="第二代",
    )
    other_product = _block(
        product_id=58,
        index=1,
        meaning="另一款产品的版本说明。",
        subject="另一款版本",
        object_value="不属于当前商品",
        predicate="merchant_version_comparison_claim",
    )
    reader = _reader(target, wrong_variant, other_product)
    original = ProductEvidenceRetriever.retrieve

    def inject_out_of_scope(self, query):
        packet = original(self, query)
        additions = (
            EvidenceSelection(
                evidence=wrong_variant,
                score=0.2,
                reasons=("injected_wrong_variant",),
                covered_dimensions=("variant_difference",),
            ),
            EvidenceSelection(
                evidence=other_product,
                score=0.1,
                reasons=("injected_cross_product",),
                covered_dimensions=("variant_difference",),
            ),
        )
        return packet.model_copy(
            update={"selected": (*packet.selected, *additions)}
        )

    monkeypatch.setattr(
        ProductEvidenceRetriever,
        "retrieve",
        inject_out_of_scope,
    )
    report = _run_with_reader(
        tmp_path,
        reader=reader,
        cases=(
            _case(
                target,
                case_id="faq-057-version",
                direct_question="第三代比第二代改了什么？",
                question_meaning="询问第三代相对第二代的版本差异",
                expected_dimensions=("variant_difference",),
                product_name="测试商品第三代",
            ),
            _case(
                wrong_variant,
                case_id="faq-057-version-two",
                direct_question="第二代质地有什么特点？",
                question_meaning="询问第二代质地",
                expected_dimensions=("variant_difference",),
                product_name="测试商品第二代",
            ),
            _case(
                other_product,
                case_id="faq-058-version",
                direct_question="另一款版本有什么变化？",
                question_meaning="询问另一款版本变化",
                expected_dimensions=("variant_difference",),
            ),
        ),
    )

    assert not report.passed
    assert report.cross_product_selection_count > 0
    assert report.wrong_variant_selection_count > 0


def test_gate_counts_nondeterministic_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block = _block(
        product_id=57,
        index=1,
        meaning="商家说明出门前15分钟涂防晒。",
        subject="防晒涂抹时点",
        object_value="出门前15分钟",
    )
    original = ProductEvidenceRetriever.retrieve
    invocation_count = 0

    def unstable_retrieve(self, query):
        nonlocal invocation_count
        packet = original(self, query)
        invocation_count += 1
        if invocation_count % 2 == 0 and packet.selected:
            first = packet.selected[0].model_copy(
                update={"score": packet.selected[0].score + 0.001}
            )
            return packet.model_copy(
                update={"selected": (first, *packet.selected[1:])}
            )
        return packet

    monkeypatch.setattr(
        ProductEvidenceRetriever,
        "retrieve",
        unstable_retrieve,
    )
    report = _run_with_reader(
        tmp_path,
        reader=_reader(block),
        cases=(
            _case(
                block,
                case_id="faq-057-usage",
                direct_question="这款防晒要提前多久涂？",
                question_meaning="询问防晒涂抹时点",
                expected_dimensions=("usage",),
            ),
        ),
    )

    assert not report.passed
    assert report.deterministic_mismatch_count > 0


def test_gate_counts_missing_multi_aspect_and_unrelated_single_aspect_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    multi = _block(
        product_id=75,
        index=1,
        meaning="低温时可能析出白色结晶。",
        subject="低温结晶",
        object_value="低温析出白色结晶",
        predicate="merchant_storage_faq",
    )
    unrelated = _block(
        product_id=75,
        index=2,
        meaning="商家说明质地偏水润。",
        subject="使用肤感",
        object_value="偏水润",
    )
    original = (
        __import__(
            "tools.guide_gates.run_product_knowledge_coverage_gate",
            fromlist=["build_product_knowledge_answer_plan"],
        ).build_product_knowledge_answer_plan
    )

    def incomplete_plan(**kwargs):
        plan = original(**kwargs)
        if tuple(kwargs["requested_dimensions"]) == (
            "packaging_information",
            "storage",
        ):
            return ProductKnowledgeAnswerPlan(
                answer_text="使用问答：低温时可能析出白色结晶。",
                direct_facts=plan.direct_facts[:1],
                used_fact_ids=plan.used_fact_ids[:1],
                requested_dimensions=(
                    "packaging_information",
                    "storage",
                ),
                covered_dimensions=("packaging_information",),
                missing_dimensions=("storage",),
            )
        if tuple(kwargs["requested_dimensions"]) == ("texture",):
            unrelated_fact = ProjectedPublicFact(
                fact_id=f"evidence:{multi.evidence_id}",
                product_id=75,
                field_key="faq",
                label="使用问答",
                display_value="低温时可能析出白色结晶。",
                source_refs=("urn:test:unrelated-fact",),
                source_kind="merchant",
                attribution="merchant_claim",
            )
            return ProductKnowledgeAnswerPlan(
                answer_text="使用问答：低温时可能析出白色结晶。",
                direct_facts=(unrelated_fact,),
                used_fact_ids=(unrelated_fact.fact_id,),
                requested_dimensions=("texture",),
                covered_dimensions=("texture",),
                missing_dimensions=(),
            )
        return plan

    monkeypatch.setattr(
        "tools.guide_gates.run_product_knowledge_coverage_gate."
        "build_product_knowledge_answer_plan",
        incomplete_plan,
    )
    report = _run_with_reader(
        tmp_path,
        reader=_reader(multi, unrelated),
        cases=(
            ProductKnowledgeFaqCase(
                case_id="faq-075-crystal",
                category="storage",
                product_id=75,
                product_name="测试修复贴",
                evidence_id=multi.evidence_id,
                direct_question="低温出现结晶是什么情况？",
                question_meaning="询问低温结晶原因",
                paraphrases=(),
                expected_dimensions=(
                    "packaging_information",
                    "storage",
                ),
                safety_sensitive=True,
            ),
            ProductKnowledgeFaqCase(
                case_id="faq-075-texture",
                category="texture",
                product_id=75,
                product_name="测试修复贴",
                evidence_id=unrelated.evidence_id,
                direct_question="这款肤感水润吗？",
                question_meaning="询问产品质地肤感",
                paraphrases=(),
                expected_dimensions=("texture",),
                safety_sensitive=False,
            ),
        ),
    )

    assert not report.passed
    assert report.answer_coverage_failure_count == 2
    assert {
        "faq:faq-075-crystal:direct",
        "faq:faq-075-texture:direct",
    } <= set(report.failed_query_ids)


def test_gate_requires_top5_target_to_reach_public_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _block(
        product_id=120,
        index=1,
        meaning="刚喷时酒精味较浓，等待几分钟再闻。",
        subject="刚喷时酒精味较浓",
        object_value="等待几分钟再闻",
    )
    distractor = _block(
        product_id=120,
        index=2,
        meaning="香水包装文字说明。",
        subject="包装文字",
        object_value="英国梨与小苍兰",
    )
    original = (
        __import__(
            "tools.guide_gates.run_product_knowledge_coverage_gate",
            fromlist=["build_product_knowledge_answer_plan"],
        ).build_product_knowledge_answer_plan
    )

    def omit_target(**kwargs):
        plan = original(**kwargs)
        if not kwargs["requested_dimensions"]:
            fact = ProjectedPublicFact(
                fact_id=f"evidence:{distractor.evidence_id}",
                product_id=120,
                field_key="faq",
                label="使用问答",
                display_value="包装文字：英国梨与小苍兰。",
                source_refs=("urn:test:distractor",),
                source_kind="merchant",
                attribution="merchant_claim",
            )
            return ProductKnowledgeAnswerPlan(
                answer_text=fact.display_value,
                direct_facts=(fact,),
                used_fact_ids=(fact.fact_id,),
            )
        return plan

    monkeypatch.setattr(
        "tools.guide_gates.run_product_knowledge_coverage_gate."
        "build_product_knowledge_answer_plan",
        omit_target,
    )
    report = _run_with_reader(
        tmp_path,
        reader=_reader(target, distractor),
        cases=(
            _case(
                target,
                case_id="faq-120-opening-smell",
                direct_question="刚喷时为什么酒精味比较重？",
                question_meaning="询问刚喷时酒精味和等待时间",
            ),
            _case(
                distractor,
                case_id="faq-120-package",
                direct_question="包装写的是什么香型？",
                question_meaning="询问包装文字和香型",
            ),
        ),
    )

    assert report.answer_coverage_failure_count >= 1
    assert "faq:faq-120-opening-smell:direct" in (
        report.failed_query_ids
    )


def test_gate_replaces_identical_output_bytes(tmp_path: Path) -> None:
    block = _block(
        product_id=57,
        index=1,
        meaning="商家说明出门前15分钟涂防晒。",
        subject="防晒涂抹时点",
        object_value="出门前15分钟",
    )
    cases = (
        _case(
            block,
            case_id="faq-057-usage",
            direct_question="这款防晒要提前多久涂？",
            question_meaning="询问防晒涂抹时点",
            paraphrases=("出门前多久抹比较合适？",),
            expected_dimensions=("usage",),
        ),
    )
    cases_path = tmp_path / "cases.jsonl"
    output = tmp_path / "output"
    reader = _reader(block)
    _write_cases(cases_path, cases)

    first = run_product_knowledge_coverage_gate(
        repo_root=ROOT,
        cases_path=cases_path,
        output_dir=output,
        reader=reader,
    )
    first_bytes = {
        path.name: path.read_bytes()
        for path in output.iterdir()
    }
    second = run_product_knowledge_coverage_gate(
        repo_root=ROOT,
        cases_path=cases_path,
        output_dir=output,
        reader=reader,
    )

    assert second == first
    assert set(first_bytes) == {
        "results.jsonl",
        "summary.json",
        "SHA256SUMS",
    }
    assert {
        path.name: path.read_bytes()
        for path in output.iterdir()
    } == first_bytes


def test_production_product_knowledge_coverage_is_green(
    tmp_path: Path,
) -> None:
    report = run_product_knowledge_coverage_gate(
        repo_root=ROOT,
        cases_path=CASES,
        output_dir=tmp_path / "coverage",
    )

    assert report.answerable_count == 1079
    assert report.answerable_top5_count == 1079
    assert report.faq_count == 47
    assert report.faq_direct_top5_count == 47
    assert report.faq_paraphrase_count >= 12
    assert (
        report.faq_paraphrase_top5_count
        == report.faq_paraphrase_count
    )
    assert report.non_answer_selection_count == 0
    assert report.cross_product_selection_count == 0
    assert report.wrong_variant_selection_count == 0
    assert report.answer_coverage_failure_count == 0
    assert report.deterministic_mismatch_count == 0
    assert report.passed
    assert {
        path.name
        for path in (tmp_path / "coverage").iterdir()
    } == {
        "results.jsonl",
        "summary.json",
        "SHA256SUMS",
    }
