from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide_runtime.contracts import ChatStreamRequest


class DeliveryStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                with anyio.CancelScope(shield=True):
                    await close()


async def iterate_http_events_in_threadpool(
    events: Iterator[bytes],
) -> AsyncIterator[bytes]:
    iterator = iter(events)
    next_task = None
    try:
        while True:
            next_task = asyncio.create_task(
                run_in_threadpool(_next_http_event, iterator)
            )
            try:
                event = await asyncio.shield(next_task)
            except asyncio.CancelledError as cancelled:
                try:
                    with anyio.CancelScope(shield=True):
                        cancelled_event = await next_task
                except BaseException as error:
                    raise error from cancelled
                del cancelled_event
                raise
            next_task = None
            if event is _HTTP_EVENT_ITERATION_DONE:
                return
            yield event
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            with anyio.CancelScope(shield=True):
                if next_task is not None and not next_task.done():
                    await next_task
                await run_in_threadpool(close)


_HTTP_EVENT_ITERATION_DONE = object()


def _next_http_event(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return _HTTP_EVENT_ITERATION_DONE


def iter_http_events(
    unified_orchestrator,
    payload: ChatStreamRequest,
    *,
    profile_owner=None,
) -> Iterator[bytes]:
    session_id = payload.session_id or f"guide-{uuid4().hex}"
    identity = TurnIdentity(
        session_id=session_id,
        request_id=f"request_{uuid4().hex}",
        turn_id=f"turn_{uuid4().hex}",
    )
    if payload.has_image_bundle_reference:
        turn = UserTurn(
            identity=identity,
            session_id=session_id,
            message=payload.message,
            image_action=payload.image_action,
            profile_owner=profile_owner,
            image_bundle_id=payload.image_bundle_id,
            image_bundle_version=payload.image_bundle_version,
            image_bundle_token=payload.image_bundle_token,
            conversation_version=payload.conversation_version,
        )
        yield from _validated_frames(
            unified_orchestrator.stream_image(turn)
        )
        return

    turn = UserTurn(
        identity=identity,
        session_id=session_id,
        message=payload.message,
        profile_owner=profile_owner,
        image_bundle_id=None,
        image_bundle_version=None,
        image_bundle_token=None,
        conversation_version=payload.conversation_version,
    )
    yield from _validated_frames(
        unified_orchestrator.stream(turn)
    )


def _validated_frames(frames) -> Iterator[bytes]:
    for frame in frames:
        if type(frame) is not bytes:
            raise TypeError(
                "unified flow must emit pre-encoded SSE bytes"
            )
        yield frame
