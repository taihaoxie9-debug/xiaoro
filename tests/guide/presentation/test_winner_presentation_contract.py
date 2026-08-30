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
    ComparisonCell,
    ComparisonRow,
    PublicPresentationContract,
    WinnerPresentation,
)


def _display() -> CardDisplayContract:
    return CardDisplayContract(
        mode="comparison",
        visible_product_ids=(38, 91),
        max_cards=2,
        reason="comparison",
    )


def _rows() -> tuple[ComparisonRow, ...]:
    return (
        ComparisonRow(
            dimension_id="brand_main",
            label="品牌主打",
            cells=(
                ComparisonCell(
                    product_id=38,
                    value="尚未确认",
                    state="unknown",
                ),
                ComparisonCell(
                    product_id=91,
                    value="尚未确认",
                    state="unknown",
                ),
            ),
        ),
        ComparisonRow(
            dimension_id="texture.refreshing",
            label="清爽",
            cells=(
                ComparisonCell(
                    product_id=38,
                    value="清爽",
                    fact_ids=("fact:38:texture",),
                    state="known",
                ),
                ComparisonCell(
                    product_id=91,
                    value="水润",
                    fact_ids=("fact:91:texture",),
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
                    value="尚未确认",
                    state="unknown",
                ),
                ComparisonCell(
                    product_id=91,
                    value="尚未确认",
                    state="unknown",
                ),
            ),
        ),
    )


def _contract(winner: WinnerPresentation) -> PublicPresentationContract:
    return PublicPresentationContract(
        responsibility=Responsibility.COMPARISON,
        mode="comparison",
        copy_source="fallback",
        sections=(
            PresentationSection(kind="summary", copy_text="对比结论。"),
            PresentationSection(kind="comparison"),
            PresentationSection(kind="full_cards"),
        ),
        requested_comparison_dimensions=("texture.refreshing",),
        comparison_rows=_rows(),
        winner=winner,
        visible_product_ids=(38, 91),
        compact_tags=(),
        card_display=_display(),
        telemetry=CopywriterTelemetry(
            provider="test",
            model="deterministic",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            fallback_reason="test",
        ),
    )


def test_selected_winner_is_public_and_fact_backed() -> None:
    contract = _contract(
        WinnerPresentation(
            status="selected",
            winner_product_id=91,
            reason="第二款在清爽维度更贴合本轮需求。",
            fact_ids=("fact:91:texture",),
            dimension_ids=("texture.refreshing",),
        )
    )

    assert contract.winner.winner_product_id == 91
    assert contract.winner.fact_ids == ("fact:91:texture",)


def test_winner_outside_visible_comparison_is_rejected() -> None:
    with pytest.raises(ValidationError, match="visible"):
        _contract(
            WinnerPresentation(
                status="selected",
                winner_product_id=55,
                reason="不应绑定到当前对比之外的商品。",
                fact_ids=("fact:55:texture",),
                dimension_ids=("texture.refreshing",),
            )
        )
