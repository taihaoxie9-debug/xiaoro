from __future__ import annotations

import re

from app.guide.understanding.contracts import (
    CategoryDraft,
    FollowupAction,
    FollowupDraft,
    SourceSpan,
)
from app.guide.understanding.exact_parsing import parse_exact_constraints


_ORDINAL_OPERATION = re.compile(
    r"^(?:那\s*)?"
    r"第\s*(?P<value>[1-9一二三四五六七八九])\s*(?:款|个)"
    r"(?:\s*(?:呢|怎么样))?"
    r"\s*[？?。]?$"
)
_ORDINALS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHEAPEST_OPERATION = re.compile(
    r"^(?:哪个|哪款)(?:更|最)便宜(?:呢|吗)?\s*[？?。]?$"
)


def parse_followup(message: str) -> FollowupDraft | None:
    text = message.strip()
    constraints, _ = parse_exact_constraints(text)
    if any(isinstance(item, CategoryDraft) for item in constraints):
        return None
    ordinal = _ORDINAL_OPERATION.fullmatch(text)
    if ordinal:
        raw = ordinal.group("value")
        value = int(raw) if raw.isdigit() else _ORDINALS[raw]
        return FollowupDraft(
            action=FollowupAction.ORDINAL_REFERENCE,
            ordinal=value,
            source_span=SourceSpan(start=0, end=len(text)),
        )
    if _CHEAPEST_OPERATION.fullmatch(text):
        return FollowupDraft(
            action=FollowupAction.CHEAPEST,
            source_span=SourceSpan(start=0, end=len(text)),
        )
    return None
