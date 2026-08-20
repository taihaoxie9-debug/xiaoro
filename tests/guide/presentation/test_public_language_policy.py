from __future__ import annotations

import pytest

from app.guide.presentation.public_language_policy import (
    PublicLanguageError,
    validate_final_public_text,
)


@pytest.mark.parametrize(
    "text",
    (
        "当前资料没有覆盖质地。",
        "已审核商品记录显示这款清爽。",
        "页面主打修护。",
        "商家宣传改善泛红。",
        "原文是一抹灭火。",
        "没有可核验数据。",
        "内部规则不允许展示。",
        "候选 ID 是 p1。",
        "事实 ID 已通过。",
    ),
)
def test_internal_mechanical_language_is_not_public(text: str) -> None:
    with pytest.raises(PublicLanguageError):
        validate_final_public_text(text)


def test_brand_focus_remains_public_language() -> None:
    assert validate_final_public_text(
        "品牌主打屏障修护，质地偏轻盈。"
    ) == "品牌主打屏障修护，质地偏轻盈。"
