from __future__ import annotations

import re

from app.guide.understanding.turn_meaning_contracts import TurnMeaning


_ALTERNATIVE_COUNT = {
    "2": 2,
    "二": 2,
    "两": 2,
    "3": 3,
    "三": 3,
}
_ALTERNATIVE_COUNT_PATTERN = re.compile(
    r"([二两三2-3])\s*(?:款|个|支|瓶)"
)


def requested_recommendation_result_count(
    meaning: TurnMeaning | None,
    *,
    message: str,
) -> int:
    source_texts = [message]
    if meaning is not None:
        source_texts.extend(
            mention.raw_text
            for mention in meaning.reference_mentions
            if (
                mention.object_family_hint == "product"
                and mention.plurality_hint == "batch"
                and mention.ordinal_hint is None
            )
        )
    counts: set[int] = set()
    for source_text in source_texts:
        for match in _ALTERNATIVE_COUNT_PATTERN.finditer(
            source_text
        ):
            if source_text[: match.start(1)].rstrip().endswith("第"):
                continue
            counts.add(_ALTERNATIVE_COUNT[match.group(1)])
    return next(iter(counts)) if len(counts) == 1 else 3


def requested_image_alternative_count(
    meaning: TurnMeaning | None,
    *,
    message: str,
) -> int:
    return requested_recommendation_result_count(
        meaning,
        message=message,
    )


__all__ = [
    "requested_image_alternative_count",
    "requested_recommendation_result_count",
]
