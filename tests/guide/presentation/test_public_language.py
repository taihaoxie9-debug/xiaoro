from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.presentation.copywriter_contracts import (
    PresentationSection,
)
from app.guide.presentation.public_language import (
    PublicLanguageError,
    validate_public_text,
)
from app.guide.presentation.sse_events import (
    CitationData,
    MessageData,
)


@pytest.mark.parametrize(
    "text",
    (
        "已按审核后的 Canonical 商品事实检查该商品。",
        "这款对 texture.lightweight 有已审核证据支持。",
        "代码核对后满足硬条件，可以放行。",
    ),
)
def test_public_language_rejects_internal_vocabulary(
    text: str,
) -> None:
    with pytest.raises(PublicLanguageError):
        validate_public_text(text)


def test_message_data_rejects_internal_public_language() -> None:
    with pytest.raises(ValidationError):
        MessageData(
            content="已按 Canonical 商品事实检查。",
        )


def test_citation_rejects_internal_public_language() -> None:
    with pytest.raises(ValidationError):
        CitationData(
            id="product:53",
            title="Canonical 商品事实 #53",
            snippet="商品事实以 Canonical 审核数据为准。",
            source_kind="canonical",
        )


def test_presentation_section_rejects_internal_public_language() -> None:
    with pytest.raises(ValidationError):
        PresentationSection(
            kind="summary",
            copy_text=(
                "这款对 texture.lightweight 有已审核证据支持。"
            ),
        )


def test_public_language_accepts_natural_advisor_copy() -> None:
    assert validate_public_text(
        "现有资料还不足以判断它一定适合你现在的状态。"
    ) == "现有资料还不足以判断它一定适合你现在的状态。"
