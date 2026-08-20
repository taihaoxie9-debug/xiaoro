from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator
from functools import partial
from typing import Any, Callable
from uuid import uuid4

import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.guide.application.chat_api_adapter import (
    commit_http_event_delivery,
    discard_http_event_delivery,
    iter_guide_public_events,
)
from app.guide.application.contracts import UserTurn
from app.guide.application.image_bundle_service import (
    ImageBundleService,
)
from app.guide.feedback.delivery import FeedbackCompletion
from app.guide.feedback.event_contracts import FeedbackActorContext
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide_runtime.contracts import ChatStreamRequest
from app.guide_runtime.image_runtime import ImageRuntimeUnavailable


class _UnifiedImageFlowAdapter:
    def __init__(self, unified, image_processor) -> None:
        self._unified = unified
        self._image_processor = image_processor
        self._conversation_state = getattr(
            image_processor,
            "_conversation_state",
            None,
        )

    def stream(self, turn: UserTurn):
        yield from self._unified.stream_image(
            turn,
            image_processor=self._image_processor,
        )


class DeliveryStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                with anyio.CancelScope(shield=True):
                    await close()


def encode_sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event}\ndata: {payload}\n\n"


def encode_terminal_sse_chunk(
    end_data: dict[str, Any],
    *,
    feedback_target: dict[str, Any] | None = None,
    encode_event: Callable[
        [str, dict[str, Any]],
        str,
    ] = encode_sse,
) -> str:
    events = []
    if feedback_target is not None:
        events.append(("feedback_target", feedback_target))
    events.append(("end", end_data))
    return "".join(
        encode_event(event, data)
        for event, data in events
    )


async def iterate_terminal_delivery_chunks(
    public_event: tuple[str, dict[str, Any]],
    *,
    actor: FeedbackActorContext,
    completion: FeedbackCompletion | None,
    feedback_service_provider: Callable[[], Any],
    encode_event: Callable[
        [str, dict[str, Any]],
        str,
    ] = encode_sse,
    logger: logging.Logger | None = None,
) -> AsyncIterator[str]:
    event, end_data = public_event
    if event != "end":
        raise ValueError("terminal delivery requires an end event")

    service = None
    prepared = None
    feedback_target = None
    if completion is not None:
        try:
            service = await run_in_threadpool(
                feedback_service_provider
            )
            prepared = await run_in_threadpool(
                partial(
                    service.prepare_completed,
                    actor=actor,
                    completion=completion,
                )
            )
        except Exception:
            if logger is not None:
                logger.exception(
                    "feedback target preparation failed"
                )
        else:
            if prepared is not None:
                feedback_target = prepared.receipt.model_dump(
                    mode="json"
                )

    # The generator resumes here only after the terminal ASGI send returns.
    yield encode_terminal_sse_chunk(
        end_data,
        feedback_target=feedback_target,
        encode_event=encode_event,
    )

    conversation_commit_failed = False
    feedback_persist_failed = False
    with anyio.CancelScope(shield=True):
        try:
            await run_in_threadpool(
                commit_http_event_delivery,
                public_event,
            )
        except Exception:
            conversation_commit_failed = True
            if logger is not None:
                logger.exception(
                    "conversation delivery commit failed"
                )
        else:
            if prepared is not None:
                try:
                    await run_in_threadpool(
                        service.persist_prepared,
                        prepared,
                    )
                except Exception:
                    feedback_persist_failed = True
                    if logger is not None:
                        logger.exception(
                            "feedback target persistence failed"
                        )

    if conversation_commit_failed:
        yield encode_event(
            "delivery_control",
            {
                "status": "conversation_commit_failed",
                "fatal": True,
            },
        )
    elif feedback_persist_failed:
        yield encode_event(
            "delivery_control",
            {
                "status": "feedback_target_persist_failed",
                "fatal": False,
            },
        )


async def iterate_http_events_in_threadpool(
    events: Iterator[tuple[str, dict[str, Any]]],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
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
                discard_http_event_delivery(cancelled_event)
                raise
            next_task = None
            if event is _HTTP_EVENT_ITERATION_DONE:
                return
            try:
                yield event
            except BaseException:
                discard_http_event_delivery(event)
                raise
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


def iter_finalized_http_events(
    events: Iterator[tuple[str, dict[str, Any]]],
) -> Iterator[tuple[str, dict[str, Any]]]:
    pending_end: tuple[str, dict[str, Any]] | None = None
    try:
        for public_event in events:
            event, data = public_event
            if pending_end is not None:
                discard_http_event_delivery(pending_end)
                if event == "error":
                    yield event, data
                else:
                    yield "error", {
                        "error": "GUIDE_EVENT_CONTRACT_INVALID",
                        "message": "推荐响应不完整，请稍后重试。",
                    }
                return
            if event == "end":
                pending_end = public_event
                continue
            yield event, data
            if event == "error":
                return
    except Exception:
        if pending_end is not None:
            discard_http_event_delivery(pending_end)
        yield "error", {
            "error": "GUIDE_INTERNAL_ERROR",
            "message": "推荐暂时不可用，请稍后重试。",
        }
        return
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            close()

    if pending_end is not None:
        yield pending_end
        return
    yield "error", {
        "error": "GUIDE_EVENT_CONTRACT_INVALID",
        "message": "推荐响应不完整，请稍后重试。",
    }


def iter_http_events(
    orchestrator,
    payload: ChatStreamRequest,
    image_bundle_service: ImageBundleService,
    image_runtime=None,
    consultation_runtime=None,
    *,
    profile_owner: ProfileOwnerRef | None = None,
    unified_router_enabled: bool = False,
) -> Iterator[tuple[str, dict[str, Any]]]:
    if not isinstance(unified_router_enabled, bool):
        raise TypeError("unified_router_enabled must be bool")
    session_id = payload.session_id or f"guide-{uuid4().hex}"
    if payload.has_image_bundle_reference:
        del image_bundle_service
        try:
            if image_runtime is None:
                raise ImageRuntimeUnavailable(
                    ("image_runtime_unavailable",)
                )
            image_orchestrator = image_runtime.get_orchestrator()
        except ImageRuntimeUnavailable:
            yield "start", {"session_id": session_id}
            yield "error", {
                "error": "IMAGE_RETRIEVAL_UNAVAILABLE",
                "message": "图片检索暂时不可用，请稍后重试。",
            }
            return
        active_profile_owner = profile_owner
        active_orchestrator = image_orchestrator
        if unified_router_enabled:
            if consultation_runtime is None:
                yield "start", {"session_id": session_id}
                yield "error", {
                    "error": "GUIDE_INTERNAL_ERROR",
                    "message": "推荐暂时不可用，请稍后重试。",
                }
                return
            if active_profile_owner is None:
                active_profile_owner = (
                    consultation_runtime.profile_owner(session_id)
                )
            active_orchestrator = _UnifiedImageFlowAdapter(
                consultation_runtime.unified,
                image_orchestrator,
            )
        turn = UserTurn(
            session_id=session_id,
            message=payload.message,
            profile_owner=active_profile_owner,
            image_bundle_id=payload.image_bundle_id,
            image_bundle_version=payload.image_bundle_version,
            image_bundle_token=payload.image_bundle_token,
            conversation_version=payload.conversation_version,
        )
        yield from iter_guide_public_events(
            active_orchestrator,
            turn,
        )
        return

    if payload.has_legacy_image_payload:
        yield "start", {"session_id": session_id}
        yield "error", {
            "error": "IMAGE_BUNDLE_UNAVAILABLE",
            "message": "图片引用不可用，请重新上传。",
        }
        return

    if unified_router_enabled:
        if consultation_runtime is None:
            yield "start", {"session_id": session_id}
            yield "error", {
                "error": "GUIDE_INTERNAL_ERROR",
                "message": "推荐暂时不可用，请稍后重试。",
            }
            return
        active_profile_owner = (
            profile_owner
            if profile_owner is not None
            else consultation_runtime.profile_owner(session_id)
        )
        yield from iter_guide_public_events(
            consultation_runtime.unified,
            UserTurn(
                session_id=session_id,
                message=payload.message,
                profile_owner=active_profile_owner,
                image_bundle_id=None,
                image_bundle_version=None,
                image_bundle_token=None,
                conversation_version=payload.conversation_version,
            ),
        )
        return

    vertical_turn = None
    has_consultation_session = False
    if consultation_runtime is not None:
        active_profile_owner = (
            profile_owner
            if profile_owner is not None
            else consultation_runtime.profile_owner(session_id)
        )
        vertical_turn = UserTurn(
            session_id=session_id,
            message=payload.message,
            profile_owner=active_profile_owner,
            image_bundle_id=None,
            image_bundle_version=None,
            image_bundle_token=None,
            conversation_version=payload.conversation_version,
        )
        try:
            consultation_claimed = (
                consultation_runtime.consultation.claims(vertical_turn)
            )
            has_consultation_session = (
                consultation_runtime.consultation.has_session(
                    vertical_turn
                )
            )
        except Exception:
            yield "start", {"session_id": session_id}
            yield "error", {
                "error": "CONSULTATION_INTERNAL_ERROR",
                "message": "轻问诊暂时不可用，请稍后重试。",
            }
            return
        if consultation_claimed:
            yield from iter_guide_public_events(
                consultation_runtime.consultation,
                vertical_turn,
            )
            return

    active_orchestrator = (
        consultation_runtime.recommendation
        if has_consultation_session
        else orchestrator
    )
    turn = vertical_turn or UserTurn(
        session_id=session_id,
        message=payload.message,
        profile_owner=profile_owner,
        image_bundle_id=None,
        image_bundle_version=None,
        image_bundle_token=None,
        conversation_version=payload.conversation_version,
    )
    yield from iter_guide_public_events(
        active_orchestrator,
        turn,
    )
