from __future__ import annotations

import re

from app.guide.understanding.contracts import (
    CategoryDraft,
    SkinRevisionDraft,
    SkinTarget,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
)


_SKIN_ALIASES = (
    ("敏感性肤质", SkinTarget.SENSITIVE),
    ("油敏肌", SkinTarget.OILY_SENSITIVE),
    ("敏感肌", SkinTarget.SENSITIVE),
    ("混合肌", SkinTarget.COMBINATION),
    ("中性肌", SkinTarget.NORMAL),
    ("油敏", SkinTarget.OILY_SENSITIVE),
    ("敏皮", SkinTarget.SENSITIVE),
    ("混合", SkinTarget.COMBINATION),
    ("中性", SkinTarget.NORMAL),
    ("油皮", SkinTarget.OILY),
    ("油性", SkinTarget.OILY),
    ("干皮", SkinTarget.DRY),
    ("干性", SkinTarget.DRY),
)
_ALIAS_PATTERN = "|".join(
    re.escape(alias) for alias, _ in _SKIN_ALIASES
)
_SUPPORTED_REVISION = re.compile(
    r"^\s*(?:"
    rf"(?:肤质\s*)?"
    rf"(?:从\s*(?:{_ALIAS_PATTERN})\s*)?"
    rf"(?:改成|换成|改为)\s*"
    rf"(?P<direct>{_ALIAS_PATTERN})\s*(?:呢|吗)?"
    rf"|那\s*(?P<followup>{_ALIAS_PATTERN})\s*呢"
    rf"|按\s*(?P<rerun>{_ALIAS_PATTERN})\s*重新看"
    r")\s*$"
)


def parse_skin_revision(
    message: str,
) -> SkinRevisionDraft | None:
    text = message.strip()
    constraints, _ = parse_exact_constraints(text)
    if any(isinstance(item, CategoryDraft) for item in constraints):
        return None

    match = _SUPPORTED_REVISION.fullmatch(text)
    if match is not None:
        matched_alias = next(
            value
            for value in match.groupdict().values()
            if value is not None
        )
        return SkinRevisionDraft(
            target=_target_for_alias(matched_alias)
        )
    return None


def _target_for_alias(alias: str) -> SkinTarget:
    for candidate, target in _SKIN_ALIASES:
        if candidate == alias:
            return target
    raise AssertionError(f"unknown skin alias: {alias}")
