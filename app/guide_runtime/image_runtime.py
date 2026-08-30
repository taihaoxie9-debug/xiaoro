from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from app.guide.retrieval.image_contracts import (
    ImageIndexRuntimeLock,
    ImageRetrievalRequest,
)
from app.guide.understanding.image_contracts import (
    ImageIdentityObservation,
    ImageIdentityTrace,
)


class ImageIndexHealthPort(Protocol):
    def check(self) -> Any: ...


class ImageRuntimeHealth(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )

    healthy: bool
    issues: tuple[str, ...]
    model_name: str
    preprocessing_version: str
    index_sha256: str


class ImageRuntimeUnavailable(RuntimeError):
    def __init__(self, issues: tuple[str, ...]) -> None:
        self.code = "image_runtime_unavailable"
        self.issues = issues
        super().__init__(self.code)


class ImageRecommendationRuntime:
    def __init__(
        self,
        *,
        processor: object,
        evidence_collector: object,
        ensure_model_ready: Callable[[], None],
        health_check: ImageIndexHealthPort,
        runtime_lock: ImageIndexRuntimeLock,
    ) -> None:
        if processor is evidence_collector:
            raise TypeError(
                "image processor and evidence collector must be distinct"
            )
        self._processor = processor
        self._evidence_collector = evidence_collector
        self._ensure_model_ready = ensure_model_ready
        self._health_check = health_check
        self._runtime_lock = runtime_lock
        self._model_ready: bool | None = None
        self._lock = RLock()

    @property
    def processor(self) -> object:
        return self._processor

    @property
    def evidence_collector(self) -> object:
        return self._evidence_collector

    def _check_model(self) -> None:
        if self._model_ready is True:
            return
        if self._model_ready is False:
            raise ImageRuntimeUnavailable(
                ("image_runtime_unavailable",)
            )
        with self._lock:
            if self._model_ready is True:
                return
            if self._model_ready is False:
                raise ImageRuntimeUnavailable(
                    ("image_runtime_unavailable",)
                )
            try:
                self._ensure_model_ready()
            except Exception:
                self._model_ready = False
                raise ImageRuntimeUnavailable(
                    ("image_runtime_unavailable",)
                ) from None
            self._model_ready = True

    def health(self) -> ImageRuntimeHealth:
        index_health = self._health_check.check()
        if not index_health.healthy:
            return self._health(
                healthy=False,
                issues=tuple(index_health.issues),
            )
        try:
            self._check_model()
        except ImageRuntimeUnavailable as error:
            return self._health(
                healthy=False,
                issues=error.issues,
            )
        return self._health(healthy=True, issues=())

    def trace_identity_request(
        self,
        request: ImageRetrievalRequest,
    ) -> tuple[ImageIdentityObservation, ImageIdentityTrace]:
        trace = getattr(
            self._evidence_collector,
            "trace_identity_request",
            None,
        )
        if not callable(trace):
            raise TypeError(
                "image evidence collector must expose "
                "trace_identity_request"
            )
        return trace(request)

    def _health(
        self,
        *,
        healthy: bool,
        issues: tuple[str, ...],
    ) -> ImageRuntimeHealth:
        return ImageRuntimeHealth(
            healthy=healthy,
            issues=issues,
            model_name=self._runtime_lock.model_name,
            preprocessing_version=(
                self._runtime_lock.preprocessing_version
            ),
            index_sha256=self._runtime_lock.index_sha256,
        )
