from collections.abc import Iterator
from typing import Protocol

from app.guide.application.contracts import UserTurn
from app.guide.presentation.contracts import ResponsePlan
from app.guide.presentation.sse_events import SseEvent


class GuideOrchestrator(Protocol):
    def orchestrate(self, turn: UserTurn) -> ResponsePlan: ...
    def stream(self, turn: UserTurn) -> Iterator[SseEvent]: ...
