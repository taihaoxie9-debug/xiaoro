from __future__ import annotations

from app.guide.presentation.public_language import (
    PublicLanguageError,
    validate_public_text,
)


_FORBIDDEN_PUBLIC_FRAGMENTS = (
    "当前资料",
    "已审核",
    "已核验",
    "页面",
    "证据",
    "原文",
    "商家宣传",
    "营销长图",
    "没有可核验",
    "内部规则",
    "候选 id",
    "事实 id",
)


def validate_final_public_text(text: str) -> str:
    validated = validate_public_text(text)
    lowered = validated.casefold()
    if any(
        fragment.casefold() in lowered
        for fragment in _FORBIDDEN_PUBLIC_FRAGMENTS
    ):
        raise PublicLanguageError(
            "public text contains mechanical audit language"
        )
    return validated


__all__ = [
    "PublicLanguageError",
    "validate_final_public_text",
]
