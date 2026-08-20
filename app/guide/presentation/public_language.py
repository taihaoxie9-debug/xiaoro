from __future__ import annotations

import re


class PublicLanguageError(ValueError):
    pass


_INTERNAL_PUBLIC_PATTERNS = (
    re.compile(
        r"(?<![A-Za-z])Canonical(?![A-Za-z])",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:texture|efficacy|suitable_skin|skin_concern)"
        r"\.[a-z0-9_]+\b",
        re.IGNORECASE,
    ),
    re.compile(r"已审核证据支持"),
    re.compile(
        r"代码核对|硬条件|证据等级|放行|页面记录版本|"
        r"本轮筛选"
    ),
)


def validate_public_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("public text must be a string")
    if not text.strip():
        raise PublicLanguageError("public text must be nonempty")
    if any(
        pattern.search(text)
        for pattern in _INTERNAL_PUBLIC_PATTERNS
    ):
        raise PublicLanguageError(
            "public text contains internal language"
        )
    return text


__all__ = [
    "PublicLanguageError",
    "validate_public_text",
]
