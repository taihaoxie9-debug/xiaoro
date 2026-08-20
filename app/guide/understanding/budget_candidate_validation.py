from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

from app.guide.understanding.colloquial_budget import (
    chinese_integer,
    parse_colloquial_budget,
)
from app.guide.understanding.contracts import (
    BudgetDraft,
    ExactConstraintDraft,
    UnderstandingIssue,
)
from app.guide.understanding.semantic_contracts import (
    SemanticNumberCandidate,
)


@dataclass(frozen=True)
class BudgetCandidateValidation:
    budget: BudgetDraft | None
    issue: UnderstandingIssue | None
    resolution: Literal[
        "no_candidate",
        "exact_wins",
        "semantic_fills",
        "clarify",
    ]


_SOURCE_NUMBER = re.compile(
    r"[0-9０-９]+(?:\.[0-9０-９]+)?|"
    r"[零〇一二两三四五六七八九十百千万]+"
)


def validate_budget_candidates(
    *,
    message: str,
    candidates: Sequence[SemanticNumberCandidate],
    exact_constraints: Sequence[ExactConstraintDraft],
    exact_issues: Sequence[UnderstandingIssue],
) -> BudgetCandidateValidation:
    if not candidates:
        return BudgetCandidateValidation(
            budget=None,
            issue=None,
            resolution="no_candidate",
        )
    if any(
        isinstance(item, BudgetDraft)
        for item in exact_constraints
    ) or any(
        issue.code in {"invalid_budget", "unsupported_budget_format"}
        for issue in exact_issues
    ):
        return BudgetCandidateValidation(
            budget=None,
            issue=None,
            resolution="exact_wins",
        )
    if len(candidates) != 1:
        return _clarify(
            "我识别到不止一个预算范围，请确认你想按哪个预算。"
        )

    candidate = candidates[0]
    if (
        candidate.end > len(message)
        or message[candidate.start:candidate.end]
        != candidate.raw_text
    ):
        return _clarify(
            "我没能准确对应你说的预算，请换一种更明确的说法。"
        )
    proposed = _candidate_bounds(candidate)
    if proposed is None:
        return _clarify(
            "预算需要是大于 0 的有效金额，请再确认一下。"
        )
    proposed_minimum, proposed_maximum = proposed
    parsed = parse_colloquial_budget(candidate.raw_text)
    if (
        parsed is None
        or parsed.start != 0
        or parsed.end != len(candidate.raw_text)
    ):
        contextual = parse_colloquial_budget(message)
        if (
            contextual is None
            or contextual.start > candidate.start
            or contextual.end < candidate.end
        ):
            if _source_supports_proposal(
                candidate,
                minimum=proposed_minimum,
                maximum=proposed_maximum,
            ):
                return BudgetCandidateValidation(
                    budget=BudgetDraft(
                        minimum=proposed_minimum,
                        maximum=proposed_maximum,
                    ),
                    issue=None,
                    resolution="semantic_fills",
                )
            return _clarify(
                "这个预算说法我暂时没理解清楚，请给一个明确数字或范围。"
            )
        parsed = contextual

    if (
        proposed_minimum != parsed.minimum
        or proposed_maximum != parsed.maximum
        or candidate.relation != _relation_for(parsed)
    ):
        return _clarify(
            "我理解的预算范围和你的原话不一致，请重新说一下预算。"
        )
    if parsed.clarification is not None:
        return BudgetCandidateValidation(
            budget=None,
            issue=UnderstandingIssue(
                code="unsupported_budget_format",
                detail=parsed.clarification,
            ),
            resolution="clarify",
        )
    return BudgetCandidateValidation(
        budget=BudgetDraft(
            minimum=parsed.minimum,
            maximum=parsed.maximum,
        ),
        issue=None,
        resolution="semantic_fills",
    )


def _source_supports_proposal(
    candidate: SemanticNumberCandidate,
    *,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> bool:
    expected_shape = {
        "maximum": (False, True),
        "minimum": (True, False),
        "range": (True, True),
        "approximate": (False, False),
    }[candidate.relation]
    actual_shape = (minimum is not None, maximum is not None)
    if actual_shape != expected_shape:
        return False
    source_values: set[Decimal] = set()
    for match in _SOURCE_NUMBER.finditer(candidate.raw_text):
        raw_value = match.group()
        try:
            value = (
                Decimal(
                    raw_value.translate(
                        str.maketrans(
                            "０１２３４５６７８９",
                            "0123456789",
                        )
                    )
                )
                if raw_value[0].isdigit()
                or raw_value[0] in "０１２３４５６７８９"
                else Decimal(chinese_integer(raw_value))
            )
        except (InvalidOperation, ValueError):
            continue
        source_values.add(value)
    proposed_values = {
        value
        for value in (minimum, maximum)
        if value is not None
    }
    return bool(proposed_values) and proposed_values <= source_values


def _candidate_bounds(
    candidate: SemanticNumberCandidate,
) -> tuple[Decimal | None, Decimal | None] | None:
    try:
        minimum = (
            Decimal(candidate.minimum)
            if candidate.minimum is not None
            else None
        )
        maximum = (
            Decimal(candidate.maximum)
            if candidate.maximum is not None
            else None
        )
    except InvalidOperation:
        return None
    values = [
        value
        for value in (minimum, maximum)
        if value is not None
    ]
    if (
        any(not value.is_finite() or value <= 0 for value in values)
        or (
            minimum is not None
            and maximum is not None
            and minimum > maximum
        )
    ):
        return None
    return minimum, maximum


def _relation_for(parsed) -> str:
    if parsed.clarification is not None:
        return "approximate"
    if parsed.minimum is not None and parsed.maximum is not None:
        return "range"
    if parsed.minimum is not None:
        return "minimum"
    return "maximum"


def _clarify(detail: str) -> BudgetCandidateValidation:
    return BudgetCandidateValidation(
        budget=None,
        issue=UnderstandingIssue(
            code="invalid_budget",
            detail=detail,
        ),
        resolution="clarify",
    )


__all__ = [
    "BudgetCandidateValidation",
    "validate_budget_candidates",
]
