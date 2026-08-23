from __future__ import annotations

from collections.abc import Iterable, Iterator


def iter_guide_public_events(
    frames: Iterable[bytes],
    *,
    session_id: str,
) -> Iterator[bytes]:
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be nonempty")
    for frame in frames:
        if type(frame) is not bytes:
            raise TypeError(
                "public adapter accepts only pre-encoded SSE bytes"
            )
        yield frame


__all__ = ["iter_guide_public_events"]
