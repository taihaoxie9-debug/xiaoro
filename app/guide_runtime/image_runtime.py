from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from app.guide.retrieval.image_contracts import ImageIndexRuntimeLock


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
        builder: Callable[[], object],
        health_check: ImageIndexHealthPort,
        runtime_lock: ImageIndexRuntimeLock,
    ) -> None:
        self._builder = builder
        self._health_check = health_check
        self._runtime_lock = runtime_lock
        self._orchestrator: object | None = None
        self._build_failed = False
        self._lock = RLock()

    def get_orchestrator(self):
        index_health = self._health_check.check()
        if not index_health.healthy:
            raise ImageRuntimeUnavailable(
                tuple(index_health.issues)
            )
        with self._lock:
            if self._orchestrator is not None:
                return self._orchestrator
            if self._build_failed:
                raise ImageRuntimeUnavailable(
                    ("image_runtime_unavailable",)
                )
            try:
                orchestrator = self._builder()
            except Exception:
                self._build_failed = True
                raise ImageRuntimeUnavailable(
                    ("image_runtime_unavailable",)
                ) from None
            self._orchestrator = orchestrator
            return orchestrator

    def health(self) -> ImageRuntimeHealth:
        index_health = self._health_check.check()
        if not index_health.healthy:
            return self._health(
                healthy=False,
                issues=tuple(index_health.issues),
            )
        try:
            self.get_orchestrator()
        except ImageRuntimeUnavailable as error:
            return self._health(
                healthy=False,
                issues=error.issues,
            )
        return self._health(healthy=True, issues=())

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
