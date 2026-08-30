from __future__ import annotations

import importlib

from app.guide.retrieval.image_contracts import ImageIndexRuntimeLock


LOCK = ImageIndexRuntimeLock(
    manifest_sha256="a" * 64,
    model_name="approved-openclip",
    weights_sha256="b" * 64,
    preprocessing_version="openclip-preprocess-v1",
    vector_dimension=512,
    index_sha256="c" * 64,
)


class FakeIndexHealth:
    def __init__(self, *, healthy: bool) -> None:
        self.healthy = healthy
        self.issues = () if healthy else ("index_integrity_drift",)


class FakeHealthCheck:
    def __init__(self, *, healthy: bool) -> None:
        self.healthy = healthy
        self.calls = 0

    def check(self):
        self.calls += 1
        return FakeIndexHealth(healthy=self.healthy)


def _runtime_module():
    return importlib.import_module("app.guide_runtime.image_runtime")


def test_image_runtime_owns_fixed_processor_and_checks_model_once() -> None:
    module = _runtime_module()
    orchestrator = object()
    calls = 0

    def ensure_model_ready() -> None:
        nonlocal calls
        calls += 1

    runtime = module.ImageRecommendationRuntime(
        processor=orchestrator,
        evidence_collector=object(),
        ensure_model_ready=ensure_model_ready,
        health_check=FakeHealthCheck(healthy=True),
        runtime_lock=LOCK,
    )

    first = runtime.health()
    second = runtime.health()

    assert first.healthy is True
    assert first.issues == ()
    assert first.model_name == LOCK.model_name
    assert first.preprocessing_version == LOCK.preprocessing_version
    assert first.index_sha256 == LOCK.index_sha256
    assert second == first
    assert runtime.processor is orchestrator
    assert not hasattr(runtime, "get_orchestrator")
    assert calls == 1


def test_image_runtime_delegates_private_identity_trace() -> None:
    module = _runtime_module()

    class Orchestrator:
        def trace_identity_request(self, request):
            return request, "trace"

    collector = Orchestrator()
    runtime = module.ImageRecommendationRuntime(
        processor=object(),
        evidence_collector=collector,
        ensure_model_ready=lambda: None,
        health_check=FakeHealthCheck(healthy=True),
        runtime_lock=LOCK,
    )

    assert runtime.trace_identity_request("request") == (
        "request",
        "trace",
    )


def test_image_runtime_unhealthy_index_blocks_model_check() -> None:
    module = _runtime_module()
    calls = 0

    def ensure_model_ready() -> None:
        nonlocal calls
        calls += 1

    runtime = module.ImageRecommendationRuntime(
        processor=object(),
        evidence_collector=object(),
        ensure_model_ready=ensure_model_ready,
        health_check=FakeHealthCheck(healthy=False),
        runtime_lock=LOCK,
    )

    health = runtime.health()

    assert health.healthy is False
    assert health.issues == ("index_integrity_drift",)
    assert calls == 0


def test_image_runtime_model_failure_is_cached_and_sanitized() -> None:
    module = _runtime_module()
    calls = 0

    def ensure_model_ready() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("/secret/model/path")

    runtime = module.ImageRecommendationRuntime(
        processor=object(),
        evidence_collector=object(),
        ensure_model_ready=ensure_model_ready,
        health_check=FakeHealthCheck(healthy=True),
        runtime_lock=LOCK,
    )

    first = runtime.health()
    second = runtime.health()

    assert first.healthy is False
    assert first.issues == ("image_runtime_unavailable",)
    assert "/secret" not in repr(first)
    assert second == first
    assert calls == 1
