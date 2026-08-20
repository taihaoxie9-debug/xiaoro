from __future__ import annotations

import re


_ASCII_TERM = re.compile(r"[A-Za-z0-9]+(?:[.+-][A-Za-z0-9]+)*")
_HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def general_knowledge_terms(*parts: str) -> tuple[str, ...]:
    if any(not isinstance(part, str) for part in parts):
        raise TypeError("knowledge term parts must be strings")
    terms: set[str] = set()
    for part in parts:
        terms.update(
            match.group(0).casefold()
            for match in _ASCII_TERM.finditer(part)
        )
        for match in _HAN_RUN.finditer(part):
            run = match.group(0)
            terms.add(run)
            terms.update(run)
            terms.update(
                run[index:index + 2]
                for index in range(len(run) - 1)
            )
    return tuple(sorted(terms))


__all__ = ["general_knowledge_terms"]
