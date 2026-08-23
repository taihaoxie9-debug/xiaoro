from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_LARGE_UNITS = {"万": 10000}
_CHINESE_NUMBER = r"[零〇一二两三四五六七八九十百千万]+"
_ARABIC_NUMBER = (
    r"(?<![0-9０-９.．])"
    r"[0-9０-９]+(?:[.．][0-9０-９]+)?"
)
_ARABIC_NUMBER_TRANSLATION = str.maketrans(
    "０１２３４５６７８９．",
    "0123456789.",
)

_CHINESE_RANGE = re.compile(
    rf"(?:预算\s*)?"
    rf"(?P<minimum>{_CHINESE_NUMBER})\s*(?:元|块)?\s*"
    rf"(?:到|至)\s*"
    rf"(?P<maximum>{_CHINESE_NUMBER})\s*(?:元|块)?"
)
_CHINESE_BOUND = re.compile(
    rf"(?P<budget_prefix>预算\s*)?"
    rf"(?P<value>{_CHINESE_NUMBER})\s*"
    rf"(?P<currency>元|块)?\s*"
    rf"(?P<direction>以内|以下|内|封顶|以上|起)"
)
_CHINESE_PREFIX_BOUND = re.compile(
    rf"(?:预算\s*)?"
    rf"(?P<direction>最多|最高|不超过|别超过|不超|别超|别过|"
    rf"上限(?:只留)?|至少|最低|不低于)\s*"
    rf"(?P<value>{_CHINESE_NUMBER})\s*(?:元|块)?"
)
_ARABIC_BOUND = re.compile(
    r"(?:预算\s*)?"
    rf"(?P<value>{_ARABIC_NUMBER})\s*(?:元|块)?\s*"
    r"(?P<direction>以内|以下|内|封顶|以上|起)"
)
_ARABIC_PREFIX_BOUND = re.compile(
    r"(?:预算\s*)?"
    r"(?P<direction>最多|最高|不超过|别超过|不超|别超|别过|"
    r"上限(?:只留)?|至少|最低|不低于)\s*"
    rf"(?P<value>{_ARABIC_NUMBER})\s*(?:元|块)?"
)
_CHINESE_BUDGET_SUFFIX = re.compile(
    rf"(?P<value>{_CHINESE_NUMBER})\s*(?:元|块)?\s*预算"
)
_ARABIC_BUDGET_SUFFIX = re.compile(
    rf"(?P<value>{_ARABIC_NUMBER})\s*(?:元|块)?\s*预算"
)
_CHINESE_BUDGET_PREFIX = re.compile(
    rf"预算\s*(?P<value>{_CHINESE_NUMBER})\s*(?:元|块)?"
)
_CHINESE_CURRENCY = re.compile(
    rf"(?P<value>{_CHINESE_NUMBER})\s*(?:元|块)"
)
_HUNDRED_ODD = re.compile(r"(?:预算\s*)?百来块")
_HUNDREDS_AROUND = re.compile(r"(?:预算\s*)?几百(?:块)?上下")
_ADJACENT_HUNDREDS_AROUND = re.compile(
    r"(?:预算\s*)?"
    r"(?P<minimum>[一二两三四五六七八])\s*"
    r"(?P<maximum>[二三四五六七八九])\s*"
    r"百\s*(?:元|块)?\s*(?:左右|上下)"
)
_ARABIC_APPROXIMATE = re.compile(
    rf"(?:预算\s*)?(?P<value>{_ARABIC_NUMBER})\s*"
    r"(?:元|块)?\s*左右"
)
_CHINESE_APPROXIMATE = re.compile(
    rf"(?:预算\s*)?(?:大概|大约|约|差不多)\s*"
    rf"(?P<value>{_CHINESE_NUMBER})\s*(?:元|块)?"
)
_CHINESE_POSTFIX_BOUND = re.compile(
    rf"(?P<value>{_CHINESE_NUMBER})\s*(?:元|块)?\s*"
    r"(?:就是|作为|算作)?\s*(?P<direction>上限|下限)"
)
_ARABIC_POSTFIX_BOUND = re.compile(
    rf"(?P<value>{_ARABIC_NUMBER})\s*(?:元|块)?\s*"
    r"(?:就是|作为|算作)?\s*(?P<direction>上限|下限)"
)
_COLLOQUIAL_HUNDREDS_MAXIMUM = re.compile(
    r"(?:预算\s*)?(?P<value>[一二两三四五六七八九])"
    r"\s*张\s*(?:以内|以下|内)"
)


@dataclass(frozen=True)
class ColloquialBudget:
    minimum: Decimal | None
    maximum: Decimal | None
    start: int
    end: int
    clarification: str | None = None


def parse_colloquial_budget(text: str) -> ColloquialBudget | None:
    match = _CHINESE_RANGE.search(text)
    if match is not None:
        return ColloquialBudget(
            minimum=Decimal(
                chinese_integer(match.group("minimum"))
            ),
            maximum=Decimal(
                chinese_integer(match.group("maximum"))
            ),
            start=match.start(),
            end=match.end(),
        )

    match = _COLLOQUIAL_HUNDREDS_MAXIMUM.search(text)
    if match is not None:
        maximum = _CHINESE_DIGITS[match.group("value")] * 100
        return ColloquialBudget(
            minimum=None,
            maximum=Decimal(maximum),
            start=match.start(),
            end=match.end(),
            clarification=(
                f"你说的“{match.group(0)}”是指 "
                f"{maximum} 元以内吗？"
            ),
        )

    match = next(
        (
            candidate
            for candidate in _CHINESE_BOUND.finditer(text)
            if not (
                candidate.group("direction") == "起"
                and candidate.group("budget_prefix") is None
                and candidate.group("currency") is None
                and candidate.group("value") in _CHINESE_DIGITS
            )
        ),
        None,
    )
    if match is not None:
        value = Decimal(chinese_integer(match.group("value")))
        if match.group("direction") in {"以上", "起"}:
            return ColloquialBudget(
                minimum=value,
                maximum=None,
                start=match.start(),
                end=match.end(),
            )
        return ColloquialBudget(
            minimum=None,
            maximum=value,
            start=match.start(),
            end=match.end(),
        )

    match = _CHINESE_PREFIX_BOUND.search(text)
    if match is not None:
        value = Decimal(chinese_integer(match.group("value")))
        if match.group("direction") in {"至少", "最低", "不低于"}:
            return ColloquialBudget(
                minimum=value,
                maximum=None,
                start=match.start(),
                end=match.end(),
            )
        return ColloquialBudget(
            minimum=None,
            maximum=value,
            start=match.start(),
            end=match.end(),
        )

    for pattern in (_ARABIC_BOUND, _ARABIC_PREFIX_BOUND):
        match = pattern.search(text)
        if match is None:
            continue
        value = _arabic_decimal(match.group("value"))
        if match.group("direction") in {"以上", "起", "至少", "最低", "不低于"}:
            return ColloquialBudget(
                minimum=value,
                maximum=None,
                start=match.start(),
                end=match.end(),
            )
        return ColloquialBudget(
            minimum=None,
            maximum=value,
            start=match.start(),
            end=match.end(),
        )

    match = _CHINESE_BUDGET_SUFFIX.search(text)
    if match is not None:
        return ColloquialBudget(
            minimum=None,
            maximum=Decimal(chinese_integer(match.group("value"))),
            start=match.start(),
            end=match.end(),
        )

    match = _ARABIC_BUDGET_SUFFIX.search(text)
    if match is not None:
        return ColloquialBudget(
            minimum=None,
            maximum=_arabic_decimal(match.group("value")),
            start=match.start(),
            end=match.end(),
        )

    match = _HUNDRED_ODD.search(text)
    if match is not None:
        return ColloquialBudget(
            minimum=Decimal("100"),
            maximum=Decimal("199"),
            start=match.start(),
            end=match.end(),
            clarification=(
                "你说的“百来块”是指 100 到 199 元吗？"
            ),
        )

    match = _HUNDREDS_AROUND.search(text)
    if match is not None:
        return ColloquialBudget(
            minimum=Decimal("200"),
            maximum=Decimal("900"),
            start=match.start(),
            end=match.end(),
            clarification=(
                f"“{match.group(0)}”通常可能指 200 到 900 元，"
                "请确认具体下限和上限。"
            ),
        )

    match = _ADJACENT_HUNDREDS_AROUND.search(text)
    if match is not None:
        minimum = _CHINESE_DIGITS[match.group("minimum")] * 100
        maximum = _CHINESE_DIGITS[match.group("maximum")] * 100
        if maximum == minimum + 100:
            return ColloquialBudget(
                minimum=Decimal(minimum),
                maximum=Decimal(maximum),
                start=match.start(),
                end=match.end(),
                clarification=(
                    f"你说的“{match.group(0)}”"
                    f"是指 {minimum} 到 {maximum} 元吗？"
                ),
            )

    match = _ARABIC_APPROXIMATE.search(text)
    if match is not None:
        value = _arabic_decimal(match.group("value"))
        lower = _format_decimal(value * Decimal("0.9"))
        upper = _format_decimal(value * Decimal("1.1"))
        return ColloquialBudget(
            minimum=value * Decimal("0.9"),
            maximum=value * Decimal("1.1"),
            start=match.start(),
            end=match.end(),
            clarification=(
                f"你说的“{_format_decimal(value)} 左右”"
                f"是指 {lower} 到 {upper} 元吗？"
            ),
        )

    match = _CHINESE_APPROXIMATE.search(text)
    if match is not None:
        value = Decimal(chinese_integer(match.group("value")))
        lower = _format_decimal(value * Decimal("0.9"))
        upper = _format_decimal(value * Decimal("1.1"))
        return ColloquialBudget(
            minimum=value * Decimal("0.9"),
            maximum=value * Decimal("1.1"),
            start=match.start(),
            end=match.end(),
            clarification=(
                f"你说的“{match.group(0)}”"
                f"是指 {lower} 到 {upper} 元吗？"
            ),
        )

    for pattern in (_CHINESE_POSTFIX_BOUND, _ARABIC_POSTFIX_BOUND):
        match = pattern.search(text)
        if match is None:
            continue
        raw_value = match.group("value")
        value = (
            Decimal(chinese_integer(raw_value))
            if pattern is _CHINESE_POSTFIX_BOUND
            else _arabic_decimal(raw_value)
        )
        return ColloquialBudget(
            minimum=(
                value if match.group("direction") == "下限" else None
            ),
            maximum=(
                value if match.group("direction") == "上限" else None
            ),
            start=match.start(),
            end=match.end(),
        )

    for pattern in (_CHINESE_BUDGET_PREFIX, _CHINESE_CURRENCY):
        match = pattern.search(text)
        if match is not None:
            return ColloquialBudget(
                minimum=None,
                maximum=Decimal(
                    chinese_integer(match.group("value"))
                ),
                start=match.start(),
                end=match.end(),
            )
    return None


def _arabic_decimal(raw_value: str) -> Decimal:
    return Decimal(raw_value.translate(_ARABIC_NUMBER_TRANSLATION))


def chinese_integer(raw_value: str) -> int:
    if not raw_value or any(
        character not in _CHINESE_DIGITS
        and character not in _SMALL_UNITS
        and character not in _LARGE_UNITS
        for character in raw_value
    ):
        raise ValueError("invalid Chinese integer")

    if all(character in _CHINESE_DIGITS for character in raw_value):
        return int(
            "".join(
                str(_CHINESE_DIGITS[character])
                for character in raw_value
            )
        )

    colloquial_tail = _colloquial_tail_value(raw_value)
    if colloquial_tail is not None:
        prefix, tail_value = colloquial_tail
        return _standard_chinese_integer(prefix) + tail_value
    return _standard_chinese_integer(raw_value)


def _colloquial_tail_value(
    raw_value: str,
) -> tuple[str, int] | None:
    if (
        len(raw_value) < 2
        or raw_value[-1] not in _CHINESE_DIGITS
        or raw_value[-2] == "零"
    ):
        return None
    unit_positions = [
        (index, _SMALL_UNITS.get(character)
         or _LARGE_UNITS.get(character))
        for index, character in enumerate(raw_value[:-1])
        if (
            character in _SMALL_UNITS
            or character in _LARGE_UNITS
        )
    ]
    if not unit_positions:
        return None
    _, last_unit = unit_positions[-1]
    assert last_unit is not None
    return (
        raw_value[:-1],
        _CHINESE_DIGITS[raw_value[-1]] * (last_unit // 10),
    )


def _standard_chinese_integer(raw_value: str) -> int:
    total = 0
    section = 0
    number = 0
    for character in raw_value:
        if character in _CHINESE_DIGITS:
            number = _CHINESE_DIGITS[character]
            continue
        if character in _SMALL_UNITS:
            unit = _SMALL_UNITS[character]
            section += (number or 1) * unit
            number = 0
            continue
        unit = _LARGE_UNITS[character]
        section += number
        total += (section or 1) * unit
        section = 0
        number = 0
    return total + section + number


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


__all__ = [
    "ColloquialBudget",
    "chinese_integer",
    "parse_colloquial_budget",
]
