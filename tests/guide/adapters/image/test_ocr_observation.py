from __future__ import annotations

import hashlib

import pytest

import app.guide.adapters.image.ocr_observation as adapter_module
from app.guide.retrieval.image_contracts import ImageRetrievalRequest
from app.guide.understanding.image_contracts import (
    CanonicalIdentity,
    IdentityEvidenceConsistency,
    OcrObservationState,
)


def _request() -> ImageRetrievalRequest:
    content = b"validated-product-image"
    return ImageRetrievalRequest(
        image_id="image_" + "a" * 32,
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        max_results=3,
    )


def _line(text: str, confidence: float) -> list[object]:
    return [
        [[0, 0], [1, 0], [1, 1], [0, 1]],
        text,
        confidence,
    ]


def test_rapidocr_trace_preserves_all_lines_from_one_engine_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bytes] = []

    class Engine:
        def __call__(self, content: bytes) -> object:
            calls.append(content)
            return [
                _line("品牌：LA ROCHE-POSAY", 0.99),
                _line("低置信度包装文字", 0.42),
            ]

    monkeypatch.setattr(
        adapter_module,
        "_build_approved_engine",
        lambda: Engine(),
    )
    adapter = adapter_module.RapidOcrObservationAdapter()

    observation, trace = adapter.observe_with_trace(
        _request(),
        CanonicalIdentity(
            product_id=38,
            brand="LA ROCHE-POSAY",
            product_name="B5 SERUM",
        ),
    )

    assert calls == [_request().content]
    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )
    assert trace.engine == "rapidocr-onnxruntime"
    assert trace.engine_version == "1.3.0"
    assert trace.minimum_evidence_confidence == pytest.approx(0.9)
    assert [(line.text, line.confidence) for line in trace.lines] == [
        ("品牌：LA ROCHE-POSAY", 0.99),
        ("低置信度包装文字", 0.42),
    ]
    assert trace.evidence_line_count == 1


def test_not_configured_ocr_returns_explicit_empty_trace() -> None:
    observation, trace = (
        adapter_module.NotConfiguredOcrObservationAdapter()
        .observe_with_trace(
            _request(),
            CanonicalIdentity(
                product_id=38,
                brand="LA ROCHE-POSAY",
                product_name="B5 SERUM",
            ),
        )
    )

    assert observation.state is OcrObservationState.NOT_CONFIGURED
    assert trace.engine == "not_configured"
    assert trace.lines == ()
    assert trace.evidence_line_count == 0
