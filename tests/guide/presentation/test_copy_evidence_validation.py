from __future__ import annotations

import pytest

from app.guide.presentation.copy_evidence_validation import (
    CopyEvidenceError,
    validate_copy_evidence,
)
from app.guide.presentation.copywriter_contracts import (
    ApprovedConstraint,
    ApprovedSoftFact,
    CopyLengthBudget,
    CopySlot,
    PresentationPacket,
    PresentationSectionSpec,
)


def _slot(slot_id: str, product_id: int) -> CopySlot:
    return CopySlot(
        slot_id=slot_id,
        product_id=product_id,
        name=f"商品{product_id}",
        category_profile="skincare",
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id=f"product:{product_id}:texture",
                product_id=product_id,
                field_key="texture",
                plain_meaning="轻盈乳液质地",
                attribution="verified_fact",
                source_refs=(f"source:{product_id}:texture",),
            ),
        ),
    )


def _slot_with_variant_restricted_fact(
    slot_id: str,
    product_id: int,
) -> CopySlot:
    return CopySlot(
        slot_id=slot_id,
        product_id=product_id,
        name=f"商品{product_id}",
        category_profile="skincare",
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id=f"evidence:{product_id}:variant",
                product_id=product_id,
                field_key="product_evidence",
                plain_meaning="当前页面将该商品描述为30ml版本并主打修护。",
                attribution="merchant_claim",
                source_refs=(f"source:{product_id}:variant",),
                generic_copy_allowed=False,
            ),
        ),
    )


def _packet() -> PresentationPacket:
    return PresentationPacket(
        mode="comparison",
        user_need_summary="预算300元，比较两款质地",
        winner_status="NOT_APPLICABLE",
        slots=(_slot("p1", 38), _slot("p2", 91)),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="comparison"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        approved_constraints=(
            ApprovedConstraint(
                constraint_id="turn:budget:300",
                kind="budget",
                display_value="预算上限300元",
            ),
        ),
        copy_budget=CopyLengthBudget(
            summary_max_chars=180,
            positioning_max_chars=150,
            advisor_reason_max_chars=120,
            closing_max_chars=180,
        ),
    )


def test_variant_restricted_fact_cannot_enter_recommendation_copy() -> None:
    packet = PresentationPacket(
        mode="recommendation",
        recommendation_mode="explore",
        user_need_summary="推荐一款修护精华",
        winner_status="NOT_APPLICABLE",
        slots=(
            _slot_with_variant_restricted_fact("p1", 38),
        ),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="product", slot_id="p1"),
            PresentationSectionSpec(kind="closing"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        copy_budget=CopyLengthBudget(
            summary_max_chars=180,
            positioning_max_chars=150,
            advisor_reason_max_chars=120,
            closing_max_chars=180,
        ),
    )

    with pytest.raises(CopyEvidenceError, match="generic recommendation"):
        validate_copy_evidence(
            packet=packet,
            location="recommendation.advisor_reason",
            slot_product_id=38,
            used_fact_ids=("evidence:38:variant",),
            used_constraint_ids=(),
        )


def test_variant_restricted_fact_can_answer_product_knowledge() -> None:
    packet = PresentationPacket(
        mode="product_knowledge",
        user_need_summary="这个商品页面怎么描述",
        winner_status="NOT_APPLICABLE",
        slots=(
            _slot_with_variant_restricted_fact("p1", 38),
        ),
        section_order=(
            PresentationSectionSpec(kind="summary"),
            PresentationSectionSpec(kind="answer"),
            PresentationSectionSpec(kind="full_cards"),
        ),
        copy_budget=CopyLengthBudget(
            summary_max_chars=180,
            positioning_max_chars=150,
            advisor_reason_max_chars=120,
            closing_max_chars=180,
        ),
    )

    validate_copy_evidence(
        packet=packet,
        location="product_knowledge.answer",
        used_fact_ids=("evidence:38:variant",),
        used_constraint_ids=(),
    )


def test_product_fact_cannot_enter_multi_product_summary() -> None:
    with pytest.raises(CopyEvidenceError, match="location"):
        validate_copy_evidence(
            packet=_packet(),
            location="comparison.summary",
            used_fact_ids=("product:38:texture",),
            used_constraint_ids=(),
        )


def test_product_38_fact_cannot_enter_product_91_block() -> None:
    packet = _packet().model_copy(
        update={"responsibility": "recommendation"}
    )

    with pytest.raises(CopyEvidenceError, match="ownership"):
        validate_copy_evidence(
            packet=packet,
            location="recommendation.product",
            slot_product_id=91,
            used_fact_ids=("product:38:texture",),
            used_constraint_ids=(),
        )


def test_budget_constraint_can_enter_recommendation_summary() -> None:
    packet = _packet().model_copy(
        update={"responsibility": "recommendation"}
    )

    validate_copy_evidence(
        packet=packet,
        location="recommendation.summary",
        used_fact_ids=(),
        used_constraint_ids=("turn:budget:300",),
    )


def test_unknown_fact_id_is_rejected_before_text_validation() -> None:
    with pytest.raises(CopyEvidenceError, match="authority"):
        validate_copy_evidence(
            packet=_packet(),
            location="comparison.summary",
            used_fact_ids=("product:999:made-up",),
            used_constraint_ids=(),
        )
