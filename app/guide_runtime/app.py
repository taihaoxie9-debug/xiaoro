from __future__ import annotations

from functools import partial
from hashlib import sha256
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import uuid4

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.guide.adapters.state import SqliteConversationState
from app.guide.adapters.state.sqlite_feedback_event_store import (
    FeedbackEventStoreCorrupt,
)
from app.guide.feedback.delivery import (
    FeedbackDeliveryTracker,
    FeedbackEventReceipt,
    FeedbackEventSubmission,
)
from app.guide.feedback.event_ports import FeedbackIdempotencyConflict
from app.guide.feedback.event_recorder import (
    FeedbackAuthorizationError,
    FeedbackReferenceError,
    ForeignFeedbackProductError,
)
from app.guide.feedback.target_ports import FeedbackTargetStoreCorrupt
from app.guide.application.contracts import (
    ImageBundleDeleteRequest,
    ImageBundleUploadReceipt,
)
from app.guide.application.chat_api_adapter import (
    GuidePublicEventError,
    PublicEventCommitConversationState,
    collect_guide_chat_response,
    commit_http_event_delivery,
    discard_http_event_delivery,
)
from app.guide.session_contract import SessionId
from app.guide_runtime.composition import (
    REPO_ROOT,
    build_consultation_vertical_runtime,
    build_feedback_service,
    build_image_bundle_service,
    build_image_recommendation_runtime,
    build_runtime_orchestrator,
)
from app.guide_runtime.contracts import ChatStreamRequest
from app.guide_runtime.feedback_http import (
    resolve_feedback_actor_session,
    set_feedback_session_cookie,
)
from app.guide_runtime.image_http import (
    create_image_bundle_from_uploads,
    delete_image_bundle,
)
from app.guide_runtime.llm_config import GuideRuntimeFlags
from app.guide_runtime.request_limits import ChatBodyLimitRoute
from app.guide_runtime.sse import (
    DeliveryStreamingResponse,
    encode_sse,
    iterate_http_events_in_threadpool,
    iterate_terminal_delivery_chunks,
    iter_finalized_http_events,
    iter_http_events,
)

logger = logging.getLogger(__name__)

RUNTIME_SCOPE = "slice1_text_skincare"
RUNTIME_CAPABILITIES = [
    "sunscreen",
    "repair_serum",
    "scenario_guidance",
    "recent_candidate_followup",
    "budget_revision_followup",
    "skin_revision_followup",
    "secure_image_bundle_input",
    "single_image_similarity",
    "single_image_suitability",
    "two_image_comparison",
    "multi_image_comparison",
    "rapidocr_observation",
    "light_consultation",
    "confirmed_profile_fill",
    "trusted_feedback",
]


def _conversation_state_health(
    orchestrator,
) -> tuple[str, dict[str, str] | None]:
    state = getattr(orchestrator, "_conversation_state", None)
    if isinstance(state, PublicEventCommitConversationState):
        state = state._delegate
    if not isinstance(state, SqliteConversationState):
        return "custom", None
    database_path = state.database_path
    return (
        "sqlite_cas",
        {
            "database": database_path.name,
            "sha256": sha256(os.fsencode(database_path)).hexdigest(),
        },
    )


def create_app(
    *,
    orchestrator=None,
    consultation_runtime=None,
    image_bundle_service=None,
    image_runtime=None,
    feedback_service=None,
    repo_root: Path = REPO_ROOT,
) -> FastAPI:
    runtime_flags = GuideRuntimeFlags.from_environment()
    runtime_orchestrator = orchestrator or build_runtime_orchestrator(
        repo_root
    )
    (
        conversation_state_kind,
        conversation_state_path,
    ) = _conversation_state_health(runtime_orchestrator)
    runtime_image_bundles = (
        image_bundle_service or build_image_bundle_service()
    )
    static_root = repo_root / "app" / "static"
    chat_path = static_root / "chat.html"
    demo_path = static_root / "demo.html"
    app = FastAPI(
        title="XiaoRo Guide Runtime",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.router.route_class = ChatBodyLimitRoute
    app.state.orchestrator = runtime_orchestrator
    app.state.conversation_state_kind = conversation_state_kind
    app.state.conversation_state_path = conversation_state_path
    app.state.runtime_flags = runtime_flags
    app.state.consultation_runtime = consultation_runtime
    app.state.image_bundle_service = runtime_image_bundles
    app.state.feedback_service = feedback_service
    feedback_service_lock = Lock()

    def get_feedback_service():
        current = app.state.feedback_service
        if current is not None:
            return current
        with feedback_service_lock:
            if app.state.feedback_service is None:
                app.state.feedback_service = build_feedback_service()
            return app.state.feedback_service

    app.mount("/static", StaticFiles(directory=static_root), name="static")
    consultation_runtime_lock = Lock()

    def get_consultation_runtime():
        current = app.state.consultation_runtime
        if current is not None:
            return current
        with consultation_runtime_lock:
            if app.state.consultation_runtime is None:
                app.state.consultation_runtime = (
                    build_consultation_vertical_runtime(repo_root)
                )
            return app.state.consultation_runtime

    app.state.image_runtime = (
        build_image_recommendation_runtime(
            repo_root=repo_root,
            image_bundle_service=runtime_image_bundles,
            consultation_runtime_provider=get_consultation_runtime,
        )
        if image_runtime is None
        else image_runtime
    )

    def active_consultation_for(payload: ChatStreamRequest):
        if payload.has_legacy_image_payload:
            return None
        if (
            payload.has_image_bundle_reference
            and not app.state.runtime_flags.unified_router
        ):
            return None
        return get_consultation_runtime()

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse(url="/chat", status_code=307)

    @app.get("/health")
    def health() -> JSONResponse:
        image_health = app.state.image_runtime.health()
        payload = {
            "status": (
                "healthy" if image_health.healthy else "unhealthy"
            ),
            "runtime": "guide",
            "scope": RUNTIME_SCOPE,
            "turn_router": (
                "unified_v1"
                if app.state.runtime_flags.unified_router
                else "legacy"
            ),
            "capabilities": list(RUNTIME_CAPABILITIES),
            "conversation_state": app.state.conversation_state_kind,
            "conversation_state_path": (
                app.state.conversation_state_path
            ),
            "consultation_state": "sqlite_cas",
            "profile_state": "sqlite_fill_only_cas",
            "image_runtime": (
                "healthy" if image_health.healthy else "unhealthy"
            ),
            "image_model": image_health.model_name,
            "image_preprocessing_version": (
                image_health.preprocessing_version
            ),
            "image_index_sha256": image_health.index_sha256,
        }
        return JSONResponse(
            payload,
            status_code=(
                status.HTTP_200_OK
                if image_health.healthy
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
        )

    @app.get("/chat")
    def chat(request: Request) -> HTMLResponse:
        html = chat_path.read_text(encoding="utf-8")
        scope = (
            '<script>window.__XIAORO_RUNTIME_SCOPE__='
            f'"{RUNTIME_SCOPE}";</script>'
        )
        html = html.replace("</head>", f"{scope}\n</head>", 1)
        response = HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            },
        )
        actor_session = resolve_feedback_actor_session(
            request,
            authorized_session_id="feedback-cookie-bootstrap",
        )
        set_feedback_session_cookie(
            response,
            actor_session,
            secure=request.url.scheme == "https",
        )
        return response

    @app.get("/demo")
    def demo() -> HTMLResponse:
        return HTMLResponse(
            demo_path.read_text(encoding="utf-8"),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    @app.post("/api/v1/chat/stream")
    async def chat_stream(
        request: Request,
        payload: ChatStreamRequest,
    ) -> DeliveryStreamingResponse:
        session_id = payload.session_id or f"guide-{uuid4().hex}"
        normalized_payload = payload.model_copy(
            update={"session_id": session_id},
            deep=True,
        )
        actor_session = resolve_feedback_actor_session(
            request,
            authorized_session_id=session_id,
        )

        async def generate():
            tracker = FeedbackDeliveryTracker()
            events = iter_finalized_http_events(
                iter_http_events(
                    app.state.orchestrator,
                    normalized_payload,
                    app.state.image_bundle_service,
                    app.state.image_runtime,
                    active_consultation_for(normalized_payload),
                    profile_owner=actor_session.actor.owner,
                    unified_router_enabled=(
                        app.state.runtime_flags.unified_router
                    ),
                )
            )
            async for public_event in iterate_http_events_in_threadpool(
                events
            ):
                event, data = public_event
                if await request.is_disconnected():
                    discard_http_event_delivery(public_event)
                    return
                tracker.observe(event, data)
                if event == "end":
                    async for chunk in (
                        iterate_terminal_delivery_chunks(
                            public_event,
                            actor=actor_session.actor,
                            completion=tracker.completion(),
                            feedback_service_provider=(
                                get_feedback_service
                            ),
                            logger=logger,
                        )
                    ):
                        yield chunk
                    return
                yield encode_sse(event, data)

        response = DeliveryStreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        set_feedback_session_cookie(
            response,
            actor_session,
            secure=request.url.scheme == "https",
        )
        return response

    @app.delete(
        "/api/v1/chat/sessions/{session_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_chat_session(
        request: Request,
        session_id: SessionId,
    ) -> Response:
        actor_session = resolve_feedback_actor_session(
            request,
            authorized_session_id=session_id,
        )
        conversation_state = getattr(
            app.state.orchestrator,
            "_conversation_state",
            None,
        )
        delete = getattr(conversation_state, "delete", None)
        if not callable(delete):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "CONVERSATION_STATE_UNAVAILABLE",
                    "message": "会话状态暂时不可用，请稍后重试。",
                },
            )
        await run_in_threadpool(
            partial(
                delete,
                session_id,
                expected_owner=actor_session.actor.owner,
            )
        )
        response = Response(
            status_code=status.HTTP_204_NO_CONTENT
        )
        set_feedback_session_cookie(
            response,
            actor_session,
            secure=request.url.scheme == "https",
        )
        return response

    @app.post(
        "/api/v1/chat/sessions/{session_id}/feedback",
        response_model=FeedbackEventReceipt,
    )
    async def record_feedback(
        request: Request,
        session_id: SessionId,
        payload: FeedbackEventSubmission,
    ) -> FeedbackEventReceipt:
        actor_session = resolve_feedback_actor_session(
            request,
            authorized_session_id=session_id,
        )
        try:
            service = await run_in_threadpool(get_feedback_service)
            return await run_in_threadpool(
                partial(
                    service.record,
                    payload,
                    actor=actor_session.actor,
                )
            )
        except FeedbackIdempotencyConflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "FEEDBACK_IDEMPOTENCY_CONFLICT",
                    "message": "该反馈请求与首次提交不一致。",
                },
            ) from None
        except (
            FeedbackAuthorizationError,
            FeedbackReferenceError,
            ForeignFeedbackProductError,
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "FEEDBACK_TARGET_UNAVAILABLE",
                    "message": "该反馈目标不可用。",
                },
            ) from None
        except (
            FeedbackEventStoreCorrupt,
            FeedbackTargetStoreCorrupt,
            OSError,
            ValueError,
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "FEEDBACK_UNAVAILABLE",
                    "message": "反馈服务暂时不可用，请稍后重试。",
                },
            ) from None

    @app.post("/api/v1/chat/message")
    async def chat_message(
        request: Request,
        payload: ChatStreamRequest,
    ) -> JSONResponse:
        session_id = payload.session_id or f"guide-{uuid4().hex}"
        normalized_payload = payload.model_copy(
            update={"session_id": session_id},
            deep=True,
        )
        actor_session = resolve_feedback_actor_session(
            request,
            authorized_session_id=session_id,
        )

        def collect_events():
            return list(
                iter_finalized_http_events(
                    iter_http_events(
                        app.state.orchestrator,
                        normalized_payload,
                        app.state.image_bundle_service,
                        app.state.image_runtime,
                        active_consultation_for(normalized_payload),
                        profile_owner=actor_session.actor.owner,
                        unified_router_enabled=(
                            app.state.runtime_flags.unified_router
                        ),
                    )
                )
            )

        events = await run_in_threadpool(collect_events)
        try:
            response_payload = collect_guide_chat_response(
                events,
                session_id=session_id,
                conversation_version=payload.conversation_version,
            )
            await run_in_threadpool(
                commit_http_event_delivery,
                events[-1],
            )
        except GuidePublicEventError as error:
            unavailable = error.code in {
                "GUIDE_INTERNAL_ERROR",
                "GUIDE_EVENT_CONTRACT_INVALID",
                "IMAGE_RETRIEVAL_UNAVAILABLE",
            }
            response = JSONResponse(
                {
                    "detail": {
                        "code": error.code,
                        "message": error.message,
                    }
                },
                status_code=(
                    status.HTTP_503_SERVICE_UNAVAILABLE
                    if unavailable
                    else status.HTTP_400_BAD_REQUEST
                ),
            )
        except Exception:
            response = JSONResponse(
                {
                    "detail": {
                        "code": "GUIDE_INTERNAL_ERROR",
                        "message": "推荐暂时不可用，请稍后重试。",
                    }
                },
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        else:
            tracker = FeedbackDeliveryTracker()
            for event, data in events:
                tracker.observe(event, data)
            receipt = None
            completion = tracker.completion()
            if completion is not None:
                try:
                    service = await run_in_threadpool(
                        get_feedback_service
                    )
                    receipt = await run_in_threadpool(
                        partial(
                            service.register_completed,
                            actor=actor_session.actor,
                            completion=completion,
                        )
                    )
                except Exception:
                    logger.exception(
                        "feedback target registration failed"
                    )
            response_payload["feedback_target"] = (
                receipt.model_dump(mode="json")
                if receipt is not None
                else None
            )
            response = JSONResponse(response_payload)
        set_feedback_session_cookie(
            response,
            actor_session,
            secure=request.url.scheme == "https",
        )
        return response

    @app.post(
        "/api/v1/chat/image-bundles",
        response_model=ImageBundleUploadReceipt,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_image_bundle(
        session_id: Annotated[
            SessionId,
            Form(),
        ],
        images: Annotated[list[UploadFile], File()],
    ) -> ImageBundleUploadReceipt:
        return await create_image_bundle_from_uploads(
            app.state.image_bundle_service,
            session_id=session_id,
            uploads=images,
        )

    @app.delete(
        "/api/v1/chat/image-bundles/{bundle_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_image_bundle(
        bundle_id: str,
        payload: ImageBundleDeleteRequest,
    ) -> Response:
        delete_image_bundle(
            app.state.image_bundle_service,
            bundle_id=bundle_id,
            version=payload.version,
            session_id=payload.session_id,
            owner_token=payload.owner_token,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


app = create_app()
