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
    WinnerPresentation,
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
            dimension_id="brand_main",
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
        ComparisonRow(
            dimension_id="profile_match",
            label="当前画像匹配",
            cells=(
                ComparisonCell(
                    product_id=38,
                    value="适合当前肤质需求",
                    fact_ids=("fact:38:profile",),
                    state="known",
                ),
                ComparisonCell(
                    product_id=91,
                    value="尚未确认",
                    state="unknown",
                ),
            ),
        ),
    )


def _recommendation_fields(
    *,
    visible_product_ids: tuple[int, ...],
    closing_copy: str | None,
) -> dict[str, object]:
    return {
        "responsibility": Responsibility.RECOMMENDATION,
        "mode": "recommendation",
        "copy_source": "fallback",
        "sections": (
            PresentationSection(kind="summary", copy_text="先看产品路线。"),
            *(
                PresentationSection(
                    kind="product",
                    slot_id=f"p{index}",
                    product_id=product_id,
                    copy_text="品牌主打清晰。",
                    advisor_reason="结合当前需求取舍。",
                )
                for index, product_id in enumerate(
                    visible_product_ids,
                    start=1,
                )
            ),
            PresentationSection(
                kind="closing",
                copy_text=closing_copy,
            ),
            PresentationSection(kind="full_cards"),
        ),
        "comparison_rows": (),
        "visible_product_ids": visible_product_ids,
        "compact_tags": (),
        "card_display": CardDisplayContract(
            mode="recommendation",
            visible_product_ids=visible_product_ids,
            max_cards=len(visible_product_ids),
            reason="recommendation",
        ),
        "telemetry": _telemetry(),
    }


def test_explore_recommendation_forbids_selected_product() -> None:
    with pytest.raises(ValidationError, match="explore recommendation"):
        PublicPresentationContract(
            recommendation_mode="explore",
            winner=WinnerPresentation(
                status="selected",
                winner_product_id=38,
                reason="当前条件下更贴合。",
                fact_ids=("fact:38:fit",),
                dimension_ids=("skin_fit",),
            ),
            **_recommendation_fields(
                visible_product_ids=(38, 91),
                closing_copy="可以按优先级继续收窄。",
            ),
        )


def test_fit_recommendation_requires_one_fact_backed_product() -> None:
    contract = PublicPresentationContract(
        recommendation_mode="fit",
        winner=WinnerPresentation(
            status="selected",
            winner_product_id=38,
            reason="换季泛红优先时更贴修护舒缓方向。",
            fact_ids=("fact:38:fit",),
            dimension_ids=("repair", "skin_fit"),
        ),
        **_recommendation_fields(
            visible_product_ids=(38,),
            closing_copy=None,
        ),
    )

    assert contract.recommendation_mode == "fit"
    assert contract.visible_product_ids == (38,)


def test_fit_recommendation_forbids_multiple_visible_products() -> None:
    with pytest.raises(ValidationError, match="fit recommendation"):
        PublicPresentationContract(
            recommendation_mode="fit",
            winner=WinnerPresentation(
                status="selected",
                winner_product_id=38,
                reason="当前条件下更贴合。",
                fact_ids=("fact:38:fit",),
                dimension_ids=("skin_fit",),
            ),
            **_recommendation_fields(
                visible_product_ids=(38, 91),
                closing_copy=None,
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
            requested_comparison_dimensions=("reference_price",),
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
        requested_comparison_dimensions=("reference_price",),
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


def test_comparison_rejects_rows_outside_current_question() -> None:
    with pytest.raises(
        ValidationError,
        match="comparison rows must match current question",
    ):
        PublicPresentationContract(
            responsibility=Responsibility.COMPARISON,
            mode="comparison",
            requested_comparison_dimensions=("texture",),
            copy_source="fallback",
            sections=(
                PresentationSection(
                    kind="summary",
                    copy_text="两款路线不同。",
                ),
                PresentationSection(kind="comparison"),
                PresentationSection(kind="full_cards"),
            ),
            comparison_rows=_comparison_rows(),
            visible_product_ids=(38, 91),
            compact_tags=(),
            card_display=_display(38, 91),
            telemetry=_telemetry(),
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
