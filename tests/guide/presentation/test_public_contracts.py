from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.copywriter_contracts import (
    CopywriterTelemetry,
    PresentationSection,
)
from app.guide.presentation.public_contracts import (
    CompactTag,
    ComparisonCell,
    ComparisonRow,
    PublicPresentationContract,
)


def _telemetry() -> CopywriterTelemetry:
    return CopywriterTelemetry(
        provider="test",
        model="deterministic",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        latency_ms=0.0,
        fallback_reason="test",
    )


def _display(*product_ids: int) -> CardDisplayContract:
    if not product_ids:
        return CardDisplayContract(
            mode="none",
            visible_product_ids=(),
            max_cards=0,
            reason=None,
        )
    if len(product_ids) == 1:
        return CardDisplayContract(
            mode="single",
            visible_product_ids=product_ids,
            max_cards=1,
            reason="product",
        )
    return CardDisplayContract(
        mode="comparison",
        visible_product_ids=product_ids,
        max_cards=len(product_ids),
        reason="comparison",
    )


def _comparison_rows() -> tuple[ComparisonRow, ...]:
    return (
        ComparisonRow(
            dimension_id="brand_focus",
            label="品牌主打",
            cells=(
                ComparisonCell(
                    product_id=38,
                    value="屏障修护",
                    fact_ids=("fact:38:repair",),
                    state="known",
                ),
                ComparisonCell(
                    product_id=91,
                    value="保湿维稳",
                    fact_ids=("fact:91:hydration",),
                    state="known",
                ),
            ),
        ),
        ComparisonRow(
            dimension_id="reference_price",
            label="参考价",
            cells=(
                ComparisonCell(
                    product_id=38,
                    value="¥249 / 30ml",
                    fact_ids=("fact:38:price",),
                    state="known",
                ),
                ComparisonCell(
                    product_id=91,
                    value="¥88 / 50ml",
                    fact_ids=("fact:91:price",),
                    state="known",
                ),
            ),
        ),
    )


def test_comparison_forbids_product_sections_after_table() -> None:
    with pytest.raises(ValidationError, match="comparison layout"):
        PublicPresentationContract(
            responsibility=Responsibility.COMPARISON,
            mode="comparison",
            copy_source="fallback",
            sections=(
                PresentationSection(kind="summary", copy_text="两款路线不同。"),
                PresentationSection(kind="comparison"),
                PresentationSection(
                    kind="product",
                    slot_id="p1",
                    product_id=38,
                    copy_text="重复商品说明",
                    advisor_reason="重复推荐理由",
                ),
                PresentationSection(kind="full_cards"),
            ),
            comparison_rows=_comparison_rows(),
            visible_product_ids=(38, 91),
            compact_tags=(),
            card_display=_display(38, 91),
            telemetry=_telemetry(),
        )


def test_comparison_rows_preserve_visible_product_order() -> None:
    contract = PublicPresentationContract(
        responsibility=Responsibility.COMPARISON,
        mode="comparison",
        copy_source="fallback",
        sections=(
            PresentationSection(kind="summary", copy_text="两款路线不同。"),
            PresentationSection(kind="comparison"),
            PresentationSection(kind="full_cards"),
        ),
        comparison_rows=_comparison_rows(),
        visible_product_ids=(38, 91),
        compact_tags=(),
        card_display=_display(38, 91),
        telemetry=_telemetry(),
    )

    assert all(
        tuple(cell.product_id for cell in row.cells) == (38, 91)
        for row in contract.comparison_rows
    )


@pytest.mark.parametrize(
    ("responsibility", "mode", "sections"),
    (
        (
            Responsibility.SINGLE_PRODUCT_SUITABILITY,
            "single_product",
            (
                PresentationSection(kind="summary", copy_text="适配摘要。"),
                PresentationSection(kind="judgement", copy_text="可以尝试。"),
                PresentationSection(kind="full_cards"),
            ),
        ),
        (
            Responsibility.PRODUCT_KNOWLEDGE,
            "product_knowledge",
            (
                PresentationSection(kind="summary", copy_text="直接回答。"),
                PresentationSection(kind="answer", copy_text="商品资料。"),
                PresentationSection(kind="full_cards"),
            ),
        ),
    ),
)
def test_single_product_layouts_have_no_inline_product_section(
    responsibility: Responsibility,
    mode: str,
    sections: tuple[PresentationSection, ...],
) -> None:
    contract = PublicPresentationContract(
        responsibility=responsibility,
        mode=mode,
        copy_source="fallback",
        sections=sections,
        comparison_rows=(),
        visible_product_ids=(38,),
        compact_tags=(),
        card_display=_display(38),
        telemetry=_telemetry(),
    )

    assert all(section.kind != "product" for section in contract.sections)


def test_compact_tags_are_bounded_and_evidence_backed() -> None:
    with pytest.raises(ValidationError, match="compact tags"):
        PublicPresentationContract(
            responsibility=Responsibility.PRODUCT_KNOWLEDGE,
            mode="product_knowledge",
            copy_source="fallback",
            sections=(
                PresentationSection(kind="summary", copy_text="直接回答。"),
                PresentationSection(kind="answer", copy_text="商品资料。"),
                PresentationSection(kind="full_cards"),
            ),
            comparison_rows=(),
            visible_product_ids=(38,),
            compact_tags=tuple(
                CompactTag(
                    product_id=38,
                    label=f"标签{index}",
                    fact_ids=(f"fact:{index}",),
                )
                for index in range(4)
            ),
            card_display=_display(38),
            telemetry=_telemetry(),
        )


@pytest.mark.parametrize("label", ("修", "防水防汗强"))
def test_compact_tag_label_is_limited_to_two_to_four_characters(
    label: str,
) -> None:
    with pytest.raises(ValidationError, match="label"):
        CompactTag(
            product_id=38,
            label=label,
            fact_ids=("fact:38:tag",),
        )
