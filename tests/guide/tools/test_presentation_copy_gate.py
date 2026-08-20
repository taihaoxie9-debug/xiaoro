from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    CopywriterSection,
    SourceTaggedCopy,
    build_copywriter_section_specs,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
from tools.guide_gates.presentation_copy_gate import (
    CopyReadabilityRubric,
    GateSoftFact,
    GateSlot,
    PresentationCopyGateCase,
    evaluate_copy_gate_output,
    load_copy_gate_cases,
    summarize_copy_gate,
)


FIXTURE = Path(
    "tests/fixtures/guide/presentation/copy_gate_v3_production.jsonl"
)
MANIFEST = Path(
    "tests/fixtures/guide/presentation/"
    "copy_gate_v3_production_manifest.json"
)
CANONICAL = Path("data/canonical/core_products_v1.jsonl")
FACT_AUDIT = Path(
    "docs/audits/continuous-conversation/"
    "presentation-fact-admission-v1.json"
)


def _cases():
    return load_copy_gate_cases(FIXTURE)


def _case(mode: str):
    return next(case for case in _cases() if case.packet.mode == mode)


def test_gate_soft_fact_preserves_child_dimension_identity() -> None:
    fact = GateSoftFact(
        fact_id="fact:repair",
        field_key="efficacy",
        dimension_ids=("efficacy.repair",),
        plain_meaning="修护屏障",
        attribution="verified_fact",
    )

    assert fact.dimension_ids == ("efficacy.repair",)
    slot = GateSlot(
        slot_id="p1",
        product_id=55,
        name="测试精华",
        category_profile="skincare",
        soft_facts=(fact,),
    )
    assert slot.to_copy_slot().approved_soft_facts[0].dimension_ids == (
        "efficacy.repair",
    )


def test_gate_rejects_external_section_without_winner_claim() -> None:
    case = _case("general_knowledge")
    output = fallback_copy(case.packet).model_dump(mode="json")
    del output["sections"][0]["content"]["winner_claim"]

    row = evaluate_copy_gate_output(
        case=case,
        output=output,
        provider_call_count=1,
    )

    assert not row.schema_valid
    assert row.validation_error_code == "schema_invalid"


def test_gate_does_not_count_a_different_child_dimension_as_coverage() -> None:
    slot = GateSlot(
        slot_id="p1",
        product_id=55,
        name="测试精华",
        category_profile="skincare",
        soft_facts=(
            GateSoftFact(
                fact_id="fact:repair",
                field_key="efficacy",
                dimension_ids=("efficacy.repair",),
                plain_meaning="修护屏障",
                attribution="verified_fact",
            ),
            GateSoftFact(
                fact_id="fact:anti-age",
                field_key="efficacy",
                dimension_ids=("efficacy.anti_age",),
                plain_meaning="紧致淡纹",
                attribution="verified_fact",
            ),
        ),
    )
    case = PresentationCopyGateCase(
        case_id="child-dimension-coverage",
        mode="product_knowledge",
        user_need_summary="这款的修护方向怎么样",
        slots=(slot,),
        required_slots=("p1",),
        allowed_soft_fact_ids={
            "p1": ("fact:repair", "fact:anti-age"),
        },
        required_dimensions=("efficacy.repair",),
        locked_atoms=(),
        winner_language_policy="forbidden",
        required_attribution=(),
        forbidden_factual_claims=(),
        readability=CopyReadabilityRubric(
            summary_min_chars=1,
            product_field_min_chars=1,
            closing_min_chars=0,
            require_closing=False,
            require_soft_fact_use=True,
        ),
        dont_care_wording=("punctuation",),
    )
    draft = CopywriterDraft(
        mode="product_knowledge",
        sections=(
            CopywriterSection(
                kind="answer",
                slot_id="p1",
                content=SourceTaggedCopy(
                    text="主要看紧致淡纹方向。",
                    used_fact_ids=("fact:anti-age",),
                ),
            ),
        ),
    )

    row = evaluate_copy_gate_output(
        case=case,
        output=draft,
        provider_call_count=1,
    )

    assert row.minimum_fact_coverage == 0.0
    assert row.fact_coverage_violation_count == 1
    assert not row.passed


def _section(
    draft: CopywriterDraft,
    kind: str,
    slot_id: str | None = None,
) -> CopywriterSection:
    return next(
        section
        for section in draft.sections
        if (section.kind, section.slot_id) == (kind, slot_id)
    )


def _replace_section(
    draft: CopywriterDraft,
    replacement: CopywriterSection,
) -> CopywriterDraft:
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


def _qualified_copy(case) -> CopywriterDraft:
    draft = fallback_copy(case.packet)
    slots_by_id = {slot.slot_id: slot for slot in case.slots}
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
                for fact in slot.soft_facts
                if fact.attribution == "merchant_claim"
            )
            consumer_ids = tuple(
                fact.fact_id
                for fact in slot.soft_facts
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
                for fact in slot.soft_facts
                if fact.attribution == "merchant_claim"
            )
            consumer_ids = tuple(
                fact.fact_id
                for fact in slot.soft_facts
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


def test_twenty_case_fixture_exists() -> None:
    assert FIXTURE.is_file()
    assert MANIFEST.is_file()


def test_fixture_uses_canonical_products_and_production_fact_inventory() -> None:
    cases = _cases()
    canonical = {
        row["product_id"]: row
        for row in (
            json.loads(line)
            for line in CANONICAL.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    audit = json.loads(FACT_AUDIT.read_text(encoding="utf-8"))
    merchant_facts = {
        (
            row["packet_fact_id"],
            row["product_id"],
            row["field_key"],
            row["plain_meaning"],
        )
        for row in audit["rows"]
        if (
            row["disposition"] == "positioning"
            and row["packet_fact_id"] is not None
        )
    }
    consumer_facts = {
        (
            f"consumer-report:{row['content_sha256']}",
            row["product_id"],
            f"限定样本的用户反馈：{row['content']}",
        )
        for row in audit["review_inventory"]
    }

    for case in cases:
        for slot in case.slots:
            product = canonical[slot.product_id]
            assert slot.name == product["fields"]["product_identity"]["value"]
            for fact in slot.soft_facts:
                if fact.attribution == "merchant_claim":
                    assert (
                        fact.fact_id,
                        slot.product_id,
                        fact.field_key,
                        fact.plain_meaning,
                    ) in merchant_facts
                else:
                    assert (
                        fact.fact_id,
                        slot.product_id,
                        fact.plain_meaning,
                    ) in consumer_facts

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["case_count"] == len(cases) == 20
    assert manifest["fixture_sha256"] == sha256(
        FIXTURE.read_bytes()
    ).hexdigest()
    assert manifest["canonical_sha256"] == sha256(
        CANONICAL.read_bytes()
    ).hexdigest()
    assert manifest["fact_admission_sha256"] == sha256(
        FACT_AUDIT.read_bytes()
    ).hexdigest()


def test_fixture_covers_every_copywriter_eligible_mode() -> None:
    cases = _cases()
    counts = Counter(case.packet.mode for case in cases)

    assert len(cases) == 20
    assert len({case.case_id for case in cases}) == len(cases)
    assert counts["recommendation"] == 3
    assert counts["comparison"] == 2
    assert counts["consultation"] == 3
    assert counts["general_knowledge"] == 2
    assert all(case.dont_care_wording for case in cases)


def test_fixture_closing_requirement_matches_public_section_contract() -> None:
    for case in _cases():
        has_closing = any(
            section.kind == "closing"
            for section in case.packet.section_order
        )
        assert case.readability.require_closing is has_closing, (
            case.case_id
        )


def test_comparison_fixture_has_one_model_owned_summary_section() -> None:
    case = _case("comparison")

    assert [
        (spec.kind, spec.slot_id)
        for spec in build_copywriter_section_specs(case.packet)
    ] == [("summary", None)]
    assert _qualified_copy(case).sections[0].kind == "summary"


def test_qualified_fixture_drafts_pass_the_new_gate() -> None:
    rows = [
        evaluate_copy_gate_output(
            case=case,
            output=_qualified_copy(case),
            provider_call_count=1,
        )
        for case in _cases()
    ]
    summary = summarize_copy_gate(rows)

    assert all(row.schema_valid for row in rows)
    assert all(row.slot_binding_passed for row in rows)
    assert all(row.fact_grounding_passed for row in rows)
    assert all(row.attribution_passed for row in rows)
    assert summary.hard_violation_count == 0
    assert summary.passed


def test_gate_rejects_nonrendered_section_unknown_fact_and_second_call() -> None:
    comparison = _case("comparison")
    comparison_draft = _qualified_copy(comparison)
    invalid_comparison = comparison_draft.model_copy(
        update={
            "sections": (
                *comparison_draft.sections,
                CopywriterSection(
                    kind="product",
                    slot_id="p1",
                    content=SourceTaggedCopy(
                        text="不该出现的商品段。",
                        used_fact_ids=(
                            "185145165558ab5a1d833e590ab450044"
                            "bf010afc0cdc62d6f4cbaff797250d3",
                        ),
                    ),
                    advisor_reason=SourceTaggedCopy(
                        text="不该出现的使用判断。"
                    ),
                ),
            )
        }
    )
    recommendation = _case("recommendation")
    draft = _qualified_copy(recommendation)
    product = _section(draft, "product", "p1")
    unknown_fact = _replace_section(
        draft,
        product.model_copy(
            update={
                "content": product.content.model_copy(
                    update={"used_fact_ids": ("unknown-fact",)}
                )
            }
        ),
    )

    slot_row = evaluate_copy_gate_output(
        case=comparison,
        output=invalid_comparison,
        provider_call_count=1,
    )
    fact_row = evaluate_copy_gate_output(
        case=recommendation,
        output=unknown_fact,
        provider_call_count=1,
    )
    second_call_row = evaluate_copy_gate_output(
        case=recommendation,
        output=draft,
        provider_call_count=2,
    )

    assert slot_row.slot_binding_violation_count == 1
    assert fact_row.fact_grounding_violation_count == 1
    assert second_call_row.provider_call_violation_count == 1
    assert not any(
        row.passed
        for row in (slot_row, fact_row, second_call_row)
    )


def test_gate_rejects_internal_language_and_unsupported_claim() -> None:
    case = _case("recommendation")
    draft = _qualified_copy(case)
    summary = _section(draft, "summary")
    internal = _replace_section(
        draft,
        summary.model_copy(
            update={
                "content": summary.content.model_copy(
                    update={
                        "text": (
                            "内部候选集按预算利用度和约束优先级完成同档排序。"
                        )
                    }
                )
            }
        ),
    )
    unsupported = _replace_section(
        draft,
        summary.model_copy(
            update={
                "content": summary.content.model_copy(
                    update={"text": "它还能额外补水，可以直接拍板。"}
                )
            }
        ),
    )

    internal_row = evaluate_copy_gate_output(
        case=case,
        output=internal,
        provider_call_count=1,
    )
    unsupported_row = evaluate_copy_gate_output(
        case=case,
        output=unsupported,
        provider_call_count=1,
    )

    assert internal_row.internal_language_violation_count == 1
    assert not internal_row.passed
    assert unsupported_row.fact_grounding_violation_count == 1
    assert not unsupported_row.passed


def test_gate_uses_required_dimensions_not_all_allowed_facts() -> None:
    case = _case("recommendation").model_copy(
        update={
            "required_dimensions": ("texture",),
            "readability": CopyReadabilityRubric(
                summary_min_chars=12,
                product_field_min_chars=8,
                closing_min_chars=10,
                require_closing=True,
                require_soft_fact_use=True,
            ),
        }
    )
    draft = _qualified_copy(case)
    product = _section(draft, "product", "p1")
    texture_fact_id = next(
        fact.fact_id
        for fact in case.slots[0].soft_facts
        if fact.field_key == "texture"
    )
    focused = _replace_section(
        draft,
        product.model_copy(
            update={
                "content": product.content.model_copy(
                    update={"used_fact_ids": (texture_fact_id,)}
                ),
                "advisor_reason": product.advisor_reason.model_copy(
                    update={"used_fact_ids": ()}
                ),
            }
        ),
    )

    row = evaluate_copy_gate_output(
        case=case,
        output=focused,
        provider_call_count=1,
    )

    assert row.minimum_fact_coverage == 1.0
    assert row.fact_coverage_passed
    assert row.passed


def test_gate_does_not_charge_backend_owned_comparison_dimensions_to_model() -> None:
    case = _case("comparison").model_copy(
        update={"required_dimensions": ("efficacy", "texture")}
    )
    draft = _qualified_copy(case)

    row = evaluate_copy_gate_output(
        case=case,
        output=draft,
        provider_call_count=1,
    )

    assert row.minimum_fact_coverage == 1.0
    assert row.fact_coverage_passed
    assert row.passed
