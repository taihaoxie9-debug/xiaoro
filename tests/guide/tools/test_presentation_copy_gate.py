from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from app.guide.presentation.copywriter_fallback import fallback_copy
from tools.guide_gates.presentation_copy_gate import (
    CopyReadabilityRubric,
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


def test_twenty_case_fixture_exists() -> None:
    assert FIXTURE.is_file()
    assert MANIFEST.is_file()


def _cases():
    return load_copy_gate_cases(FIXTURE)


def _case(mode: str):
    return next(case for case in _cases() if case.packet.mode == mode)


def _qualified_copy(case):
    draft = fallback_copy(case.packet)
    product_copy = []
    for item, slot in zip(
        draft.product_copy,
        case.slots,
        strict=True,
    ):
        has_consumer_report = any(
            fact.attribution == "consumer_report"
            for fact in slot.soft_facts
        )
        product_copy.append(
            item.model_copy(
                update={
                    "positioning": (
                        "按商家资料，这款的功效、肤感与使用场景"
                        "以已审核事实为准。"
                    ),
                    "advisor_reason": (
                        "结合当前需求可以比较这些信息；"
                        + (
                            "限定样本的用户反馈只作体验参考。"
                            if has_consumer_report
                            else "未给出的部分不作推断。"
                        )
                    ),
                    "used_soft_fact_ids": tuple(
                        fact.fact_id for fact in slot.soft_facts
                    ),
                }
            )
        )
    return draft.model_copy(
        update={"product_copy": tuple(product_copy)}
    )


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
                elif fact.attribution == "consumer_report":
                    assert (
                        fact.fact_id,
                        slot.product_id,
                        fact.plain_meaning,
                    ) in consumer_facts
                else:
                    raise AssertionError(
                        "production gate facts require reviewed attribution"
                    )

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

    assert len(cases) == 20
    assert len({case.case_id for case in cases}) == len(cases)
    assert {case.packet.mode for case in cases} == {
        "recommendation",
        "comparison",
        "single_product",
        "product_knowledge",
        "general_knowledge",
        "followup",
        "revision",
        "image_identity",
        "image_recommendation",
        "image_suitability",
        "image_comparison",
        "consultation",
        "clarification",
    }
    counts = Counter(case.packet.mode for case in cases)
    assert counts["recommendation"] == 3
    assert counts["comparison"] == 2
    assert sum(
        counts[mode]
        for mode in (
            "single_product",
            "product_knowledge",
            "followup",
        )
    ) == 4
    assert counts["general_knowledge"] == 2
    assert counts["consultation"] == 3
    assert sum(
        counts[mode]
        for mode in (
            "image_identity",
            "image_recommendation",
            "image_suitability",
            "image_comparison",
        )
    ) == 4
    assert counts["revision"] + counts["clarification"] == 2
    assert all(case.dont_care_wording for case in cases)
    assert len(_case("recommendation").slots[0].soft_facts) == 5
    assert len(_case("revision").slots[0].soft_facts) == 5


def test_clarification_gate_uses_current_question_only_contract() -> None:
    case = _case("clarification")

    assert tuple(
        section.kind for section in case.packet.section_order
    ) == ("question",)
    assert _qualified_copy(case).closing_copy is None


def test_three_product_packet_is_complete_and_schema_valid() -> None:
    case = next(
        item
        for item in _cases()
        if item.case_id == "copy-013-recommendation-three-products"
    )
    draft = _qualified_copy(case)
    row = evaluate_copy_gate_output(
        case=case,
        output=draft,
        provider_call_count=1,
    )

    assert len(case.slots) == 3
    assert len(draft.product_copy) == 3
    assert row.schema_valid
    assert row.fact_coverage_passed
    assert row.passed


def test_fixture_inputs_are_public_facing_and_category_consistent() -> None:
    internal_terms = (
        "候选",
        "已核验商品记录",
        "现有目录",
        "原字段边界",
    )
    category_terms = {
        "精华": "skincare",
        "防晒": "suncare",
        "底妆": "base_makeup",
        "洁面": "cleanser",
    }

    for case in _cases():
        source_text = " ".join(
            (
                case.user_need_summary,
                *(
                    fact.plain_meaning
                    for slot in case.slots
                    for fact in slot.soft_facts
                ),
            )
        )
        assert not any(term in source_text for term in internal_terms), (
            case.case_id
        )
        named_profiles = {
            profile
            for term, profile in category_terms.items()
            if term in case.user_need_summary
        }
        if named_profiles and case.slots:
            assert {
                slot.category_profile for slot in case.slots
            }.issubset(named_profiles), case.case_id


def test_fixture_does_not_duplicate_winner_policy_as_fact_claim() -> None:
    winner_terms = {
        "最佳",
        "首选",
        "最适合",
        "唯一推荐",
        "闭眼入",
        "稳赢",
        "第一选择",
    }

    for case in _cases():
        assert not any(
            term in claim
            for claim in case.forbidden_factual_claims
            for term in winner_terms
        ), case.case_id


def test_valid_paraphrases_pass_without_exact_paragraph_matching() -> None:
    case = _case("recommendation")
    draft = _qualified_copy(case)
    product = draft.product_copy[0]
    paraphrased = draft.model_copy(
        update={
            "summary_copy": (
                "先按已确认的信息把选择范围收紧，再结合自己的使用节奏做决定。"
            ),
            "product_copy": (
                product.model_copy(
                    update={
                        "positioning": (
                            "按商家资料，整体更偏轻盈、利落的日常路线。"
                        ),
                        "advisor_reason": (
                            "需要快速完成晨间步骤时，这种取向会更顺手。"
                        ),
                    }
                ),
            ),
            "closing_copy": (
                "最后再对照下方列出的价格、规格和注意事项即可。"
            ),
        }
    )

    row = evaluate_copy_gate_output(
        case=case,
        output=paraphrased.model_dump(mode="json"),
        provider_call_count=1,
    )

    assert row.schema_valid
    assert row.slot_binding_passed
    assert row.fact_grounding_passed
    assert row.hard_atoms_passed
    assert row.winner_language_passed
    assert row.attribution_passed
    assert row.fact_coverage_passed
    assert row.minimum_fact_coverage >= 0.8
    assert row.internal_language_passed
    assert row.readability_passed
    assert row.passed


def test_gate_separates_schema_readability_and_hard_failures() -> None:
    case = _case("recommendation")
    draft = _qualified_copy(case)

    invalid_schema = evaluate_copy_gate_output(
        case=case,
        output={"mode": case.packet.mode},
        provider_call_count=1,
    )
    terse = evaluate_copy_gate_output(
        case=case,
        output=draft.model_copy(
            update={
                "summary_copy": "可以考虑。",
                "closing_copy": "再看看。",
            }
        ),
        provider_call_count=1,
    )
    hard_fact = evaluate_copy_gate_output(
        case=case,
        output=draft.model_copy(
            update={
                "summary_copy": "它只要88元，还额外含有烟酰胺。",
            }
        ),
        provider_call_count=1,
    )

    assert not invalid_schema.schema_valid
    assert invalid_schema.hard_violation_count == 0
    assert terse.schema_valid
    assert not terse.readability_passed
    assert terse.hard_violation_count == 0
    assert hard_fact.schema_valid
    assert hard_fact.hard_atom_violation_count == 1
    assert not hard_fact.passed


def test_gate_rejects_slot_fact_winner_attribution_and_second_call() -> None:
    comparison = _case("comparison")
    comparison_draft = _qualified_copy(comparison)
    reordered = comparison_draft.model_copy(
        update={
            "product_copy": tuple(
                reversed(comparison_draft.product_copy)
            )
        }
    )
    recommendation = _case("recommendation")
    recommendation_draft = _qualified_copy(recommendation)
    unknown_fact = recommendation_draft.model_copy(
        update={
            "product_copy": (
                recommendation_draft.product_copy[0].model_copy(
                    update={"used_soft_fact_ids": ("unknown-fact",)}
                ),
            )
        }
    )
    winner = recommendation_draft.model_copy(
        update={"summary_copy": "这就是最适合你的唯一首选。"}
    )
    unattributed = recommendation_draft.model_copy(
        update={
            "product_copy": (
                recommendation_draft.product_copy[0].model_copy(
                    update={
                        "positioning": "这款更偏轻盈路线。",
                        "advisor_reason": "这种肤感更轻盈利落。",
                    }
                ),
            )
        }
    )

    slot_row = evaluate_copy_gate_output(
        case=comparison,
        output=reordered,
        provider_call_count=1,
    )
    fact_row = evaluate_copy_gate_output(
        case=recommendation,
        output=unknown_fact,
        provider_call_count=1,
    )
    winner_row = evaluate_copy_gate_output(
        case=recommendation,
        output=winner,
        provider_call_count=1,
    )
    attribution_row = evaluate_copy_gate_output(
        case=recommendation,
        output=unattributed,
        provider_call_count=1,
    )
    second_call_row = evaluate_copy_gate_output(
        case=recommendation,
        output=recommendation_draft,
        provider_call_count=2,
    )

    assert slot_row.slot_binding_violation_count == 1
    assert fact_row.fact_grounding_violation_count == 1
    assert winner_row.winner_language_violation_count == 1
    assert attribution_row.attribution_violation_count == 1
    assert second_call_row.provider_call_violation_count == 1
    assert not any(
        row.passed
        for row in (
            slot_row,
            fact_row,
            winner_row,
            attribution_row,
            second_call_row,
        )
    )


def test_gate_rejects_fixture_specific_unsupported_claim() -> None:
    case = _case("recommendation")
    draft = _qualified_copy(case).model_copy(
        update={"summary_copy": "它还能额外补水，可以直接拍板。"}
    )

    row = evaluate_copy_gate_output(
        case=case,
        output=draft,
        provider_call_count=1,
    )

    assert row.fact_grounding_violation_count == 1
    assert not row.passed


def test_gate_rejects_low_coverage_and_internal_ranking_language() -> None:
    case = _case("recommendation")
    draft = _qualified_copy(case)
    product = draft.product_copy[0]
    low_coverage = draft.model_copy(
        update={
            "product_copy": (
                product.model_copy(
                    update={
                        "used_soft_fact_ids": tuple(
                            case.allowed_soft_fact_ids["p1"][:3]
                        )
                    }
                ),
            )
        }
    )
    internal_language = draft.model_copy(
        update={
            "summary_copy": (
                "内部候选集按预算利用度和约束优先级完成同档排序。"
            )
        }
    )

    coverage_row = evaluate_copy_gate_output(
        case=case,
        output=low_coverage,
        provider_call_count=1,
    )
    internal_row = evaluate_copy_gate_output(
        case=case,
        output=internal_language,
        provider_call_count=1,
    )

    assert coverage_row.fact_coverage_violation_count == 1
    assert coverage_row.minimum_fact_coverage == 0.6
    assert not coverage_row.fact_coverage_passed
    assert coverage_row.hard_violation_count == 0
    assert not coverage_row.passed
    assert internal_row.fact_coverage_passed
    assert not internal_row.internal_language_passed
    assert not internal_row.passed


def test_gate_records_validator_internal_language_failure() -> None:
    case = _case("followup")
    draft = _qualified_copy(case).model_copy(
        update={
            "summary_copy": (
                "沿用上一轮候选，再结合你补充的清爽偏好继续判断。"
            )
        }
    )

    row = evaluate_copy_gate_output(
        case=case,
        output=draft,
        provider_call_count=1,
    )

    assert row.validation_error_code == "internal_language"
    assert row.internal_language_violation_count == 1
    assert not row.internal_language_passed
    assert not row.passed


def test_short_positioning_with_substantive_reason_is_readable() -> None:
    case = _case("revision")
    draft = _qualified_copy(case)
    concise = draft.model_copy(
        update={
            "product_copy": (
                draft.product_copy[0].model_copy(
                    update={
                        "positioning": "品牌主打偏柔润路线。",
                        "advisor_reason": (
                            "预算调整后，可以把它理解为更重视包裹感的选择。"
                        ),
                    }
                ),
            )
        }
    )

    row = evaluate_copy_gate_output(
        case=case,
        output=concise,
        provider_call_count=1,
    )

    assert row.readability_passed
    assert row.passed


def test_concise_positioning_can_be_supported_by_substantive_reason() -> None:
    case = _case("recommendation").model_copy(
        update={
            "readability": CopyReadabilityRubric(
                summary_min_chars=12,
                product_field_min_chars=10,
                closing_min_chars=10,
                require_closing=True,
                require_soft_fact_use=True,
            )
        }
    )
    draft = _qualified_copy(case)
    product = draft.product_copy[0]
    concise = draft.model_copy(
        update={
            "product_copy": (
                product.model_copy(
                    update={
                        "positioning": "品牌主打轻薄清爽。",
                        "advisor_reason": (
                            "成膜节奏较快，也更贴合偏油肤感和通勤安排。"
                        ),
                    }
                ),
            )
        }
    )

    row = evaluate_copy_gate_output(
        case=case,
        output=concise,
        provider_call_count=1,
    )

    assert len(concise.product_copy[0].positioning) < 10
    assert row.readability_passed
    assert row.passed


def test_summary_uses_layered_admission_thresholds() -> None:
    rows = [
        evaluate_copy_gate_output(
            case=case,
            output=_qualified_copy(case),
            provider_call_count=1,
        )
        for case in _cases()
    ]

    summary = summarize_copy_gate(rows)

    assert summary.schema_valid_rate == 1.0
    assert summary.readability_rate == 1.0
    assert summary.fact_coverage_rate == 1.0
    assert summary.internal_language_rate == 1.0
    assert summary.minimum_fact_coverage >= 0.8
    assert summary.hard_violation_count == 0
    assert summary.passed
