from __future__ import annotations

import pytest

from app.guide.understanding.source_grounding import (
    SourceGroundingError,
    ground_unique_text,
)


def test_unique_source_text_is_grounded_without_model_offsets() -> None:
    grounded = ground_unique_text(
        "换个更清爽的，预算三百以内",
        "更清爽",
    )

    assert grounded.raw_text == "更清爽"
    assert grounded.start == 2
    assert grounded.end == 5


def test_missing_source_text_is_rejected() -> None:
    with pytest.raises(SourceGroundingError) as caught:
        ground_unique_text("推荐清爽防晒", "高遮瑕")

    assert caught.value.code == "missing"


def test_repeated_source_text_is_ambiguous() -> None:
    with pytest.raises(SourceGroundingError) as caught:
        ground_unique_text("这个和这个哪个好", "这个")

    assert caught.value.code == "ambiguous"
