from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.guide.understanding.contracts import (
    BudgetRevisionDraft,
    CategoryDraft,
)
from app.guide.understanding.colloquial_budget import (
    parse_colloquial_budget,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
)


_SUPPORTED_REVISION = re.compile(
    r"^\s*"
    r"(?:(?:预算\s*)?(?:降到|改成|调整到)|控制在)"
    r"\s*(?P<maximum>-?\d+(?:\.\d+)?)\s*(?:元|块)"
    r"(?:\s*(?:以内|以下))?\s*(?:呢|吗)?\s*$"
)
_CHINESE_REVISION = re.compile(
    r"^\s*"
    r"(?:(?:预算\s*)?(?:降到|改成|调整到)|控制在)"
    r"\s*(?P<expression>.+?)\s*(?:呢|吗)?\s*$"
)


def parse_budget_revision(
    message: str,
) -> BudgetRevisionDraft | None:
    text = message.strip()
    constraints, _ = parse_exact_constraints(text)
    if any(isinstance(item, CategoryDraft) for item in constraints):
        return None
    match = _SUPPORTED_REVISION.fullmatch(text)
    if match is not None:
        try:
            maximum = Decimal(match.group("maximum"))
        except InvalidOperation:
            return BudgetRevisionDraft(issue="invalid_budget")
    else:
        chinese_match = _CHINESE_REVISION.fullmatch(text)
        if chinese_match is None:
            return None
        expression = chinese_match.group("expression")
        colloquial = parse_colloquial_budget(expression)
        if (
            colloquial is None
            or colloquial.clarification is not None
            or colloquial.minimum is not None
            or colloquial.maximum is None
            or colloquial.start != 0
            or colloquial.end != len(expression)
        ):
            return None
        maximum = colloquial.maximum
    if not maximum.is_finite() or maximum <= 0:
        return BudgetRevisionDraft(issue="invalid_budget")
    return BudgetRevisionDraft(maximum=maximum)
