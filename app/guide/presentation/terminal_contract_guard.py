from __future__ import annotations

from typing import Literal

from app.guide.presentation.sse_events import (
    ClarifyEvent,
    EndEvent,
    ErrorEvent,
    MessageEvent,
    PresentationContractEvent,
    SseEvent,
    StartEvent,
)


class GuideTerminalContractError(RuntimeError):
    pass


class GuideTerminalContractGuard:
    def __init__(self) -> None:
        self._start_count = 0
        self._presentation_count = 0
        self._clarification_count = 0
        self._error_count = 0
        self._terminal_kind: Literal[
            "guide",
            "clarification",
            "error",
            None,
        ] = None
        self._ended = False

    def observe(self, event: SseEvent) -> None:
        if self._ended:
            raise GuideTerminalContractError(
                "event observed after terminal event"
            )
        if isinstance(event, MessageEvent):
            raise GuideTerminalContractError(
                "Guide terminal contract forbids MessageEvent"
            )
        if (
            self._start_count == 0
            and not isinstance(event, StartEvent)
        ):
            raise GuideTerminalContractError(
                "Guide stream must start with StartEvent"
            )
        if (
            self._terminal_kind is not None
            and not isinstance(event, EndEvent)
        ):
            raise GuideTerminalContractError(
                "event observed after terminal body"
            )
        if isinstance(event, StartEvent):
            self._start_count += 1
            if self._start_count != 1:
                raise GuideTerminalContractError(
                    "Guide stream requires one StartEvent"
                )
            return
        if isinstance(event, PresentationContractEvent):
            self._presentation_count += 1
            self._terminal_kind = "guide"
            if self._presentation_count != 1:
                raise GuideTerminalContractError(
                    "Guide stream requires one presentation contract"
                )
            return
        if isinstance(event, ClarifyEvent):
            self._clarification_count += 1
            self._terminal_kind = "clarification"
            if self._clarification_count != 1:
                raise GuideTerminalContractError(
                    "clarification requires one ClarifyEvent"
                )
            return
        if isinstance(event, ErrorEvent):
            self._error_count += 1
            self._terminal_kind = "error"
            self._validate_terminal_shape()
            self._ended = True
            return
        if isinstance(event, EndEvent):
            self._validate_terminal_shape()
            self._ended = True

    def finish(self) -> None:
        if not self._ended:
            raise GuideTerminalContractError(
                "stream ended before terminal event"
            )

    def _validate_terminal_shape(self) -> None:
        if self._start_count != 1:
            raise GuideTerminalContractError(
                "Guide stream requires one StartEvent"
            )
        if self._terminal_kind == "clarification":
            if self._presentation_count or self._error_count:
                raise GuideTerminalContractError(
                    "clarification forbids presentation or error"
                )
            return
        if self._terminal_kind == "error":
            if (
                self._error_count != 1
                or self._presentation_count
                or self._clarification_count
            ):
                raise GuideTerminalContractError(
                    "error terminal shape is invalid"
                )
            return
        if self._presentation_count != 1:
            raise GuideTerminalContractError(
                "Guide terminal turn is missing contract"
            )
        if self._clarification_count or self._error_count:
            raise GuideTerminalContractError(
                "Guide presentation forbids clarification or error"
            )


__all__ = [
    "GuideTerminalContractError",
    "GuideTerminalContractGuard",
]
