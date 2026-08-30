from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.guide.adapters.state.in_memory_image_bundle_state import (
    InMemoryImageBundleState,
)
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide.presentation.presentation_compiler import PresentationCompiler
from app.guide.retrieval.image_contracts import (
    ImageRetrievalCandidate,
    ImageRetrievalResult,
)
from app.guide.understanding.image_contracts import (
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ImageIdentityTrace,
    ObservationState,
    OcrIdentityTrace,
    OcrIdentityObservation,
    OcrObservationState,
    VisualCandidateObservation,
    VisualObservationState,
)
from app.guide_runtime.composition import (
    build_image_recommendation_runtime,
)
from tools.guide_gates.trace_image_identity_pipeline import (
    trace_image_identity_pipeline,
)


ROOT = Path(__file__).resolve().parents[3]
INDEX_CONTROL = (
    ROOT
    / "tests/fixtures/guide/images/product-38-index-control.png"
)
MISLABELED_SOURCE = (
    ROOT / "tests/fixtures/guide/images/product-38-original.png"
)
LOW_RESOLUTION = (
    ROOT
    / "tests/fixtures/guide/images/product-38-low-resolution.jpg"
)


class StaticTraceRuntime:
    def __init__(self, trace: ImageIdentityTrace) -> None:
        self.trace = trace
        self.requests = []

    def trace_identity_request(self, request):
        self.requests.append(request)
        observation = self.trace.observation.model_copy(
            update={"image_id": request.image_id}
        )
        trace = self.trace.model_copy(
            update={"observation": observation}
        )
        return observation, trace


def _runtime(
    *candidates: tuple[int, float],
    identity_state: IdentityState,
) -> StaticTraceRuntime:
    result = ImageRetrievalResult(
        candidates=tuple(
            ImageRetrievalCandidate(
                rank=rank,
                product_id=product_id,
                similarity=similarity,
            )
            for rank, (product_id, similarity) in enumerate(
                candidates,
                start=1,
            )
        ),
        model_name="approved-openclip",
        weights_sha256="a" * 64,
        preprocessing_version="openclip-preprocess-v1",
        vector_dimension=512,
        index_sha256="b" * 64,
    )
    visual = VisualCandidateObservation(
        state=VisualObservationState.OBSERVED,
        result=result,
    )
    ocr = OcrIdentityObservation(
        state=OcrObservationState.NOT_RUN,
        brand_consistency=IdentityEvidenceConsistency.NOT_CHECKED,
        product_name_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
    )
    candidate_ids = tuple(item.product_id for item in result.candidates)
    margin = (
        result.candidates[0].similarity
        - result.candidates[1].similarity
        if len(result.candidates) >= 2
        else None
    )
    observation = ImageIdentityObservation(
        image_id="image_" + "a" * 32,
        observation_state=ObservationState.PARTIAL,
        visual_state=VisualObservationState.OBSERVED,
        ocr_state=OcrObservationState.NOT_RUN,
        identity_state=identity_state,
        confirmed_product_id=(
            candidate_ids[0]
            if identity_state is IdentityState.CONFIRMED
            else None
        ),
        candidate_product_ids=candidate_ids,
        visual_confidence=(
            result.candidates[0].similarity
            if result.candidates
            else None
        ),
        similarity_margin=margin,
        model_name=result.model_name,
        weights_sha256=result.weights_sha256,
        preprocessing_version=result.preprocessing_version,
        vector_dimension=result.vector_dimension,
        index_sha256=result.index_sha256,
        ocr_brand_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
        ocr_product_name_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
    )
    trace = ImageIdentityTrace(
        visual=visual,
        ocr_observation=ocr,
        ocr_diagnostic=OcrIdentityTrace(
            engine="not_run",
            engine_version=None,
            minimum_evidence_confidence=0.9,
            lines=(),
            evidence_line_count=0,
        ),
        observation=observation,
        minimum_similarity=0.8,
        minimum_margin=0.1,
    )
    return StaticTraceRuntime(trace)


def _bundle_service() -> ImageBundleService:
    return ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=4)
    )


@pytest.fixture(scope="module")
def production_trace_services():
    image_bundles = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=8)
    )
    runtime = build_image_recommendation_runtime(
        image_bundle_service=image_bundles,
        presentation_compiler=PresentationCompiler(copywriter=None),
        device="cpu",
    )
    return image_bundles, runtime


def test_trace_fixture_manifest_binds_exact_immutable_bytes() -> None:
    manifest = json.loads(
        (
            ROOT
            / "tests/fixtures/guide/images/product-38-trace-manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest["schema_version"] == "guide-image-trace-fixtures-v1"
    assert manifest["product_id"] == 38
    assert {
        row["file_name"] for row in manifest["fixtures"]
    } == {
        "product-38-index-control.png",
        "product-38-original.png",
        "product-38-low-resolution.jpg",
    }
    for row in manifest["fixtures"]:
        content = (
            ROOT / "tests/fixtures/guide/images" / row["file_name"]
        ).read_bytes()
        assert hashlib.sha256(content).hexdigest() == row["sha256"]


def test_trace_records_every_identity_stage(tmp_path: Path) -> None:
    runtime = _runtime(
        (38, 0.93),
        (91, 0.70),
        identity_state=IdentityState.CONFIRMED,
    )
    output_path = tmp_path / "trace.json"

    result = trace_image_identity_pipeline(
        image_path=INDEX_CONTROL,
        output_path=output_path,
        image_bundles=_bundle_service(),
        runtime=runtime,
    )

    assert result["input"]["sha256"] == (
        "7916573dc1cc11239edea3229f145f00ccfc7716f98d81d220197413cef2d98b"
    )
    assert result["validated_input"]["width"] == 800
    assert result["validated_input"]["height"] == 800
    assert result["validated_input"]["bytes_unchanged"] is True
    assert result["visual"]["preprocessing_version"]
    assert result["ocr_diagnostic"]["engine"] == "not_run"
    assert result["visual_candidates"][0]["product_id"] == 38
    assert result["identity"]["confirmed_product_id"] == 38
    assert result["earliest_failure_layer"] is None
    assert len(runtime.requests) == 1
    assert json.loads(output_path.read_text(encoding="utf-8")) == result


def test_mislabeled_source_trace_does_not_pretend_to_confirm_product_38(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        (94, 0.734),
        (145, 0.707),
        identity_state=IdentityState.LOW_CONFIDENCE,
    )

    result = trace_image_identity_pipeline(
        image_path=MISLABELED_SOURCE,
        output_path=tmp_path / "mislabeled-source-trace.json",
        image_bundles=_bundle_service(),
        runtime=runtime,
    )

    assert result["visual_candidates"][0]["product_id"] == 94
    assert result["identity"]["confirmed_product_id"] is None
    assert result["earliest_failure_layer"] == "visual_retrieval"


def test_low_resolution_trace_names_earliest_failure(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        identity_state=IdentityState.NO_CANDIDATE,
    )

    result = trace_image_identity_pipeline(
        image_path=LOW_RESOLUTION,
        output_path=tmp_path / "low-resolution-trace.json",
        image_bundles=_bundle_service(),
        runtime=runtime,
    )

    assert result["validated_input"]["width"] == 250
    assert result["validated_input"]["height"] == 250
    assert result["identity"]["confirmed_product_id"] is None
    assert result["earliest_failure_layer"] == "visual_retrieval"


def test_trace_persists_input_validation_failure(
    tmp_path: Path,
) -> None:
    mismatched = tmp_path / "declared-png.png"
    mismatched.write_bytes(LOW_RESOLUTION.read_bytes())
    runtime = _runtime(
        identity_state=IdentityState.NO_CANDIDATE,
    )
    output_path = tmp_path / "input-failure.json"

    result = trace_image_identity_pipeline(
        image_path=mismatched,
        output_path=output_path,
        image_bundles=_bundle_service(),
        runtime=runtime,
    )

    assert result["validated_input"] is None
    assert result["input_error_code"] == "magic_format_mismatch"
    assert result["earliest_failure_layer"] == "input_validation"
    assert runtime.requests == []
    assert json.loads(output_path.read_text(encoding="utf-8")) == result


def test_trace_persists_undecodable_input_failure(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "broken.png"
    invalid.write_bytes(b"not-an-image")
    runtime = _runtime(
        identity_state=IdentityState.NO_CANDIDATE,
    )

    result = trace_image_identity_pipeline(
        image_path=invalid,
        output_path=tmp_path / "undecodable-input.json",
        image_bundles=_bundle_service(),
        runtime=runtime,
    )

    assert result["input"]["width"] == 0
    assert result["input"]["height"] == 0
    assert result["input_error_code"] == "invalid_image_data"
    assert result["earliest_failure_layer"] == "input_validation"
    assert runtime.requests == []


def test_production_trace_matches_reviewed_fixture_truth(
    tmp_path: Path,
    production_trace_services,
) -> None:
    image_bundles, runtime = production_trace_services
    manifest = json.loads(
        (
            ROOT
            / "tests/fixtures/guide/images/product-38-trace-manifest.json"
        ).read_text(encoding="utf-8")
    )

    for row in manifest["fixtures"]:
        result = trace_image_identity_pipeline(
            image_path=(
                ROOT
                / "tests/fixtures/guide/images"
                / row["file_name"]
            ),
            output_path=tmp_path / f"{row['file_name']}.trace.json",
            image_bundles=image_bundles,
            runtime=runtime,
        )

        assert result["identity"]["state"] == (
            row["expected_identity_state"]
        )
        assert result["visual_candidates"][0]["product_id"] == (
            row["expected_top_product_id"]
        )
        assert result["earliest_failure_layer"] == (
            row["expected_earliest_failure_layer"]
        )
