from __future__ import annotations

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.compact_tag_planning import plan_compact_tags
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CompactTagEvidence,
    CopySlot,
    LockedFact,
)


def _slot() -> CopySlot:
    return CopySlot(
        slot_id="p1",
        product_id=38,
        name="理肤泉新B5多效修护精华",
        category_profile="skincare",
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id="fact:38:repair",
                product_id=38,
                field_key="efficacy",
                plain_meaning="屏障修护",
                attribution="verified_fact",
                source_refs=("source:repair",),
            ),
            ApprovedSoftFact(
                fact_id="fact:38:texture",
                product_id=38,
                field_key="texture",
                plain_meaning="轻盈乳液质地",
                attribution="verified_fact",
                source_refs=("source:texture",),
            ),
            ApprovedSoftFact(
                fact_id="fact:38:ingredient",
                product_id=38,
                field_key="claimed_ingredients",
                plain_meaning="泛醇",
                attribution="merchant_claim",
                source_refs=("source:ingredient",),
            ),
            ApprovedSoftFact(
                fact_id="fact:38:usage",
                product_id=38,
                field_key="usage",
                plain_meaning="薄涂使用",
                attribution="verified_fact",
                source_refs=("source:usage",),
            ),
        ),
        locked_facts=(
            LockedFact(
                fact_id="fact:38:price",
                product_id=38,
                kind="price",
                label="参考价",
                display_value="¥249 / 30ml",
                source_refs=("source:price",),
            ),
        ),
        required_cautions=(),
        compact_tag_evidence=(
            CompactTagEvidence(
                product_id=38,
                fact_id="fact:38:repair",
                field_key="efficacy",
                label="屏障修护",
                source_refs=("source:repair",),
                attribution="verified_fact",
            ),
            CompactTagEvidence(
                product_id=38,
                fact_id="fact:38:texture",
                field_key="texture",
                label="轻盈乳液质地",
                source_refs=("source:texture",),
                attribution="verified_fact",
            ),
            CompactTagEvidence(
                product_id=38,
                fact_id="fact:38:ingredient",
                field_key="claimed_ingredients",
                label="泛醇",
                source_refs=("source:ingredient",),
                attribution="merchant_claim",
            ),
            CompactTagEvidence(
                product_id=38,
                fact_id="fact:38:usage",
                field_key="usage",
                label="薄涂使用",
                source_refs=("source:usage",),
                attribution="verified_fact",
            ),
        ),
    )


def test_compact_tags_are_bounded_and_evidence_backed() -> None:
    tags = plan_compact_tags(
        responsibility=Responsibility.RECOMMENDATION,
        slot=_slot(),
        requested_concepts=("efficacy.repair",),
    )

    assert 0 < len(tags) <= 3
    assert all(tag.product_id == 38 for tag in tags)
    assert all(tag.fact_ids for tag in tags)
    assert tags[0].fact_ids == ("fact:38:repair",)


def test_product_knowledge_tags_do_not_include_fit_status() -> None:
    tags = plan_compact_tags(
        responsibility=Responsibility.PRODUCT_KNOWLEDGE,
        slot=_slot(),
        requested_concepts=(),
    )

    assert "适配待确认" not in {tag.label for tag in tags}
    assert "推荐理由" not in {tag.label for tag in tags}


def test_comparison_tags_do_not_repeat_exact_price() -> None:
    tags = plan_compact_tags(
        responsibility=Responsibility.COMPARISON,
        slot=_slot(),
        requested_concepts=("texture",),
    )

    assert all("¥" not in tag.label for tag in tags)
    assert all("249" not in tag.label for tag in tags)


def test_compact_tag_uses_structured_label_not_copy_text() -> None:
    payload = _slot().model_dump(mode="python")
    payload["compact_tag_evidence"] = [
        {
            "product_id": 38,
            "fact_id": "fact:38:repair",
            "field_key": "efficacy",
            "label": "屏障修护",
            "source_refs": ("source:repair",),
            "attribution": "verified_fact",
        }
    ]
    slot = CopySlot.model_validate(payload, strict=True)

    tags = plan_compact_tags(
        responsibility=Responsibility.RECOMMENDATION,
        slot=slot,
        requested_concepts=("efficacy.repair",),
    )

    assert [tag.label for tag in tags] == ["屏障修护"]


def test_compact_tags_reject_long_fact_copy_instead_of_truncating_it() -> None:
    payload = _slot().model_dump(mode="python")
    payload["compact_tag_evidence"] = [
        {
            "product_id": 38,
            "fact_id": "fact:38:long_claim",
            "field_key": "efficacy",
            "label": "医院皮肤科验证改善敏感肌修护受损肌五大问题",
            "source_refs": ("source:long_claim",),
            "attribution": "merchant_claim",
        },
        {
            "product_id": 38,
            "fact_id": "fact:38:ingredient",
            "field_key": "claimed_ingredients",
            "label": "泛醇",
            "source_refs": ("source:ingredient",),
            "attribution": "merchant_claim",
        },
    ]
    slot = CopySlot.model_validate(payload, strict=True)

    tags = plan_compact_tags(
        responsibility=Responsibility.RECOMMENDATION,
        slot=slot,
        requested_concepts=("efficacy.repair",),
    )

    assert [tag.label for tag in tags] == ["泛醇"]


def test_compact_tags_use_only_two_to_four_character_labels() -> None:
    payload = _slot().model_dump(mode="python")
    payload["compact_tag_evidence"] = [
        {
            "product_id": 38,
            "fact_id": "fact:38:single",
            "field_key": "efficacy",
            "label": "修",
            "source_refs": ("source:single",),
            "attribution": "verified_fact",
        },
        {
            "product_id": 38,
            "fact_id": "fact:38:four",
            "field_key": "texture",
            "label": "轻薄清爽",
            "source_refs": ("source:four",),
            "attribution": "verified_fact",
        },
        {
            "product_id": 38,
            "fact_id": "fact:38:five",
            "field_key": "finish",
            "label": "防水防汗强",
            "source_refs": ("source:five",),
            "attribution": "verified_fact",
        },
    ]
    slot = CopySlot.model_validate(payload, strict=True)

    tags = plan_compact_tags(
        responsibility=Responsibility.RECOMMENDATION,
        slot=slot,
        requested_concepts=("efficacy.repair",),
    )

    assert [tag.label for tag in tags] == ["轻薄清爽"]
    assert all(2 <= len(tag.label) <= 4 for tag in tags)
