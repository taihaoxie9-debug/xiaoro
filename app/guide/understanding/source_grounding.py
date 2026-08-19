from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class GroundedSourceText:
    raw_text: str
    start: int
    end: int


class SourceGroundingError(ValueError):
    def __init__(
        self,
        code: Literal["missing", "ambiguous"],
    ) -> None:
        self.code = code
        super().__init__(f"source grounding failed: {code}")


def ground_unique_text(
    message: str,
    raw_text: str,
) -> GroundedSourceText:
    if (
        not isinstance(message, str)
        or not isinstance(raw_text, str)
        or not raw_text
    ):
        raise TypeError("message and raw_text must be nonempty strings")
    starts: list[int] = []
    offset = 0
    while True:
        index = message.find(raw_text, offset)
        if index < 0:
            break
        starts.append(index)
        offset = index + 1
    if not starts:
        raise SourceGroundingError("missing")
    if len(starts) != 1:
        raise SourceGroundingError("ambiguous")
    return GroundedSourceText(
        raw_text=raw_text,
        start=starts[0],
        end=starts[0] + len(raw_text),
    )


__all__ = [
    "GroundedSourceText",
    "SourceGroundingError",
    "ground_unique_text",
]
