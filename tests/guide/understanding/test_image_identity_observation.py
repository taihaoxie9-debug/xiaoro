from __future__ import annotations

import hashlib
import importlib
import inspect
from pathlib import Path
from typing import Any, get_type_hints

import pytest
from pydantic import ValidationError

import app.guide.adapters.image.ocr_observation as ocr_adapter_module
from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.retrieval.image_contracts import (
    ImageRetrievalCandidate,
    ImageRetrievalRequest,
    ImageRetrievalResult,
)


ROOT = Path(__file__).resolve().parents[3]
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _task12_module(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError:
        pytest.fail(f"Task12 module is missing: {module_name}")


def _contracts():
    return _task12_module("app.guide.understanding.image_contracts")


def _ports():
    return _task12_module("app.guide.understanding.ports")


def _identity():
    return _task12_module("app.guide.understanding.image_identity")


def _request(*, max_results: int = 3) -> ImageRetrievalRequest:
    content = b"decoded-and-validated-image"
    return ImageRetrievalRequest(
        image_id="image_" + "a" * 32,
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        max_results=max_results,
    )


def _retrieval_result(
    *candidate_values: tuple[int, float],
) -> ImageRetrievalResult:
    return ImageRetrievalResult(
        candidates=tuple(
            ImageRetrievalCandidate(
                rank=rank,
                product_id=product_id,
                similarity=similarity,
            )
            for rank, (product_id, similarity) in enumerate(
                candidate_values,
                start=1,
            )
        ),
        model_name="approved-openclip",
        weights_sha256=SHA_A,
        preprocessing_version="openclip-preprocess-v1",
        vector_dimension=512,
        index_sha256=SHA_B,
    )


class FakeVisualObservationPort:
    def __init__(self, observation: Any) -> None:
        self.observation = observation
        self.requests: list[ImageRetrievalRequest] = []

    def observe(self, request: ImageRetrievalRequest):
        self.requests.append(request)
        return self.observation


class FakeOcrObservationPort:
    def __init__(self, observation: Any) -> None:
        self.observation = observation
        self.calls: list[tuple[ImageRetrievalRequest, Any]] = []

    def observe(
        self,
        request: ImageRetrievalRequest,
        canonical_identity: Any,
    ):
        self.calls.append((request, canonical_identity))
        return self.observation

    def observe_with_trace(
        self,
        request: ImageRetrievalRequest,
        canonical_identity: Any,
    ):
        self.calls.append((request, canonical_identity))
        contracts = _contracts()
        return (
            self.observation,
            contracts.OcrIdentityTrace(
                engine="fake-ocr",
                engine_version="test",
                minimum_evidence_confidence=0.9,
                lines=(
                    contracts.OcrTraceLine(
                        text="Canonical Brand",
                        confidence=0.99,
                    ),
                ),
                evidence_line_count=1,
            ),
        )


class FakeCanonicalIdentityCatalog:
    def __init__(
        self,
        identities: dict[int, Any],
        *,
        extra_product_ids: set[int] | None = None,
    ) -> None:
        self._identities = identities
        self.product_ids = frozenset(identities) | frozenset(
            extra_product_ids or set()
        )

    def get_identity(self, product_id: int):
        return self._identities.get(product_id)


def _canonical_identity(product_id: int = 1):
    contracts = _contracts()
    return contracts.CanonicalIdentity(
        product_id=product_id,
        brand="Canonical Brand",
        product_name="Canonical Product",
    )


def _ocr_observation(
    *,
    brand: str = "consistent",
    product_name: str = "consistent",
):
    contracts = _contracts()
    return contracts.OcrIdentityObservation(
        state=contracts.OcrObservationState.OBSERVED,
        brand_consistency=contracts.IdentityEvidenceConsistency(brand),
        product_name_consistency=(
            contracts.IdentityEvidenceConsistency(product_name)
        ),
    )


def _visual_observation(
    *candidate_values: tuple[int, float],
):
    contracts = _contracts()
    return contracts.VisualCandidateObservation(
        state=contracts.VisualObservationState.OBSERVED,
        result=_retrieval_result(*candidate_values),
    )


def _observer(
    *,
    visual_observation: Any,
    ocr_observation: Any,
    identities: dict[int, Any] | None = None,
    extra_product_ids: set[int] | None = None,
    minimum_similarity: float = 0.8,
    minimum_margin: float = 0.1,
):
    contracts = _contracts()
    identity = _identity()
    canonical_identities = (
        {1: _canonical_identity(1)}
        if identities is None
        else identities
    )
    visual_port = FakeVisualObservationPort(visual_observation)
    ocr_port = FakeOcrObservationPort(ocr_observation)
    observer = identity.ImageIdentityObserver(
        visual_observation=visual_port,
        ocr_observation=ocr_port,
        canonical_identities=FakeCanonicalIdentityCatalog(
            canonical_identities,
            extra_product_ids=extra_product_ids,
        ),
        policy=contracts.IdentityBindingPolicy(
            minimum_similarity=minimum_similarity,
            minimum_margin=minimum_margin,
        ),
    )
    return observer, visual_port, ocr_port


def test_observation_ports_have_strong_typed_signatures() -> None:
    contracts = _contracts()
    ports = _ports()

    visual_signature = inspect.signature(
        ports.VisualObservationPort.observe
    )
    visual_hints = get_type_hints(
        ports.VisualObservationPort.observe
    )
    assert tuple(visual_signature.parameters) == ("self", "request")
    assert visual_hints["request"] is ImageRetrievalRequest
    assert visual_hints["return"] is contracts.VisualCandidateObservation

    ocr_signature = inspect.signature(ports.OcrObservationPort.observe)
    ocr_hints = get_type_hints(ports.OcrObservationPort.observe)
    assert tuple(ocr_signature.parameters) == (
        "self",
        "request",
        "canonical_identity",
    )
    assert ocr_hints["request"] is ImageRetrievalRequest
    assert ocr_hints["canonical_identity"] is contracts.CanonicalIdentity
    assert ocr_hints["return"] is contracts.OcrIdentityObservation


def test_task12_contracts_and_adapters_are_exported_by_their_owners() -> None:
    understanding = importlib.import_module("app.guide.understanding")
    catalog_adapters = importlib.import_module(
        "app.guide.adapters.catalog"
    )
    image_adapters = importlib.import_module("app.guide.adapters.image")

    for name in (
        "CanonicalIdentity",
        "IdentityBindingPolicy",
        "IdentityEvidenceConsistency",
        "IdentityState",
        "ImageIdentityObservation",
        "ImageIdentityObserver",
        "ObservationState",
        "OcrIdentityObservation",
        "OcrObservationPort",
        "OcrObservationState",
        "VisualCandidateObservation",
        "VisualObservationPort",
        "VisualObservationState",
    ):
        assert hasattr(understanding, name), name
    assert hasattr(catalog_adapters, "CanonicalIdentityCatalog")
    assert hasattr(
        image_adapters,
        "NotConfiguredOcrObservationAdapter",
    )


def test_public_observation_schema_contains_only_safe_typed_fields() -> None:
    contracts = _contracts()

    assert set(contracts.ImageIdentityObservation.model_fields) == {
        "image_id",
        "observation_state",
        "visual_state",
        "ocr_state",
        "identity_state",
        "confirmed_product_id",
        "candidate_product_ids",
        "visual_confidence",
        "similarity_margin",
        "model_name",
        "weights_sha256",
        "preprocessing_version",
        "vector_dimension",
        "index_sha256",
        "ocr_brand_consistency",
        "ocr_product_name_consistency",
    }
    forbidden_tokens = {
        "raw",
        "text",
        "brand",
        "product_name",
        "facts",
        "winner",
    }
    public_fields = set(contracts.ImageIdentityObservation.model_fields)
    assert not public_fields & forbidden_tokens


def test_identity_policy_is_explicit_strict_and_bounded() -> None:
    contracts = _contracts()

    with pytest.raises(ValidationError):
        contracts.IdentityBindingPolicy(
            minimum_similarity="0.8",
            minimum_margin=0.1,
        )
    with pytest.raises(ValidationError):
        contracts.IdentityBindingPolicy(
            minimum_similarity=0.8,
            minimum_margin=0.0,
        )
    with pytest.raises(ValidationError):
        contracts.IdentityBindingPolicy(
            minimum_similarity=1.1,
            minimum_margin=0.1,
        )


def test_clear_top_candidate_at_threshold_confirms_canonical_identity() -> None:
    contracts = _contracts()
    second_identity = _canonical_identity(2)
    observer, visual_port, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.8), (2, 0.7)),
        ocr_observation=_ocr_observation(),
        identities={1: _canonical_identity(1), 2: second_identity},
    )

    observation = observer.observe(_request())

    assert observation.observation_state is contracts.ObservationState.COMPLETE
    assert observation.identity_state is contracts.IdentityState.CONFIRMED
    assert observation.confirmed_product_id == 1
    assert observation.candidate_product_ids == (1, 2)
    assert observation.visual_confidence == pytest.approx(0.8)
    assert observation.similarity_margin == pytest.approx(0.1)
    assert observation.model_name == "approved-openclip"
    assert observation.index_sha256 == SHA_B
    assert len(visual_port.requests) == 1
    assert len(ocr_port.calls) == 1
    assert ocr_port.calls[0][1].product_id == 1


def test_trace_reuses_one_visual_and_one_ocr_observation() -> None:
    contracts = _contracts()
    observer, visual_port, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.91), (2, 0.82)),
        ocr_observation=_ocr_observation(),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )

    observation, trace = observer.observe_with_trace(_request())

    assert trace.observation == observation
    assert trace.visual == visual_port.observation
    assert trace.ocr_observation == ocr_port.observation
    assert trace.ocr_diagnostic.engine == "fake-ocr"
    assert trace.minimum_similarity == pytest.approx(0.8)
    assert trace.minimum_margin == pytest.approx(0.1)
    assert len(visual_port.requests) == 1
    assert len(ocr_port.calls) == 1
    assert observation.identity_state is contracts.IdentityState.CONFIRMED


def test_pre_ocr_failure_still_returns_complete_private_trace() -> None:
    contracts = _contracts()
    observer, visual_port, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.79), (2, 0.70)),
        ocr_observation=_ocr_observation(),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )

    observation, trace = observer.observe_with_trace(_request())

    assert observation.identity_state is contracts.IdentityState.LOW_CONFIDENCE
    assert trace.observation == observation
    assert trace.visual == visual_port.observation
    assert trace.ocr_observation.state is contracts.OcrObservationState.NOT_RUN
    assert trace.ocr_diagnostic.engine == "not_run"
    assert trace.ocr_diagnostic.lines == ()
    assert len(visual_port.requests) == 1
    assert ocr_port.calls == []


def test_private_trace_rejects_mismatched_ocr_observation() -> None:
    contracts = _contracts()
    observer, _, _ = _observer(
        visual_observation=_visual_observation((1, 0.91), (2, 0.70)),
        ocr_observation=_ocr_observation(),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )
    observation, trace = observer.observe_with_trace(_request())

    with pytest.raises(ValidationError, match="OCR observation"):
        contracts.ImageIdentityTrace(
            visual=trace.visual,
            ocr_observation=contracts.OcrIdentityObservation(
                state=contracts.OcrObservationState.OBSERVED,
                brand_consistency=(
                    contracts.IdentityEvidenceConsistency.CONFLICT
                ),
                product_name_consistency=(
                    contracts.IdentityEvidenceConsistency.CONSISTENT
                ),
            ),
            ocr_diagnostic=trace.ocr_diagnostic,
            observation=observation,
            minimum_similarity=trace.minimum_similarity,
            minimum_margin=trace.minimum_margin,
        )


def test_decimal_threshold_equality_confirms_canonical_identity() -> None:
    contracts = _contracts()
    observer, _, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.9), (2, 0.8)),
        ocr_observation=_ocr_observation(),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )

    observation = observer.observe(_request())

    assert observation.similarity_margin == pytest.approx(0.1)
    assert observation.identity_state is contracts.IdentityState.CONFIRMED
    assert observation.confirmed_product_id == 1
    assert len(ocr_port.calls) == 1


def test_near_candidates_without_ocr_corroboration_remain_ambiguous() -> None:
    contracts = _contracts()
    observer, _, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.899999), (2, 0.8)),
        ocr_observation=_ocr_observation(
            brand="indeterminate",
            product_name="indeterminate",
        ),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )

    observation = observer.observe(_request())

    assert observation.similarity_margin == pytest.approx(0.099999)
    assert (
        observation.identity_state
        is contracts.IdentityState.AMBIGUOUS_CANDIDATES
    )
    assert observation.confirmed_product_id is None
    assert len(ocr_port.calls) == 1


def test_ocr_not_configured_is_explicit_and_never_fakes_success() -> None:
    contracts = _contracts()
    adapter_module = _task12_module(
        "app.guide.adapters.image.ocr_observation"
    )
    adapter = adapter_module.NotConfiguredOcrObservationAdapter()

    observation = adapter.observe(_request(), _canonical_identity())

    assert (
        observation.state
        is contracts.OcrObservationState.NOT_CONFIGURED
    )
    assert (
        observation.brand_consistency
        is contracts.IdentityEvidenceConsistency.NOT_CHECKED
    )
    assert (
        observation.product_name_consistency
        is contracts.IdentityEvidenceConsistency.NOT_CHECKED
    )


def test_not_configured_ocr_does_not_add_weight_or_block_clear_visual_id(
) -> None:
    contracts = _contracts()
    adapter_module = _task12_module(
        "app.guide.adapters.image.ocr_observation"
    )
    observer = _identity().ImageIdentityObserver(
        visual_observation=FakeVisualObservationPort(
            _visual_observation((1, 0.91), (2, 0.7))
        ),
        ocr_observation=(
            adapter_module.NotConfiguredOcrObservationAdapter()
        ),
        canonical_identities=FakeCanonicalIdentityCatalog(
            {
                1: _canonical_identity(1),
                2: _canonical_identity(2),
            }
        ),
        policy=contracts.IdentityBindingPolicy(
            minimum_similarity=0.8,
            minimum_margin=0.1,
        ),
    )

    observation = observer.observe(_request())

    assert observation.identity_state is contracts.IdentityState.CONFIRMED
    assert observation.confirmed_product_id == 1
    assert observation.observation_state is contracts.ObservationState.PARTIAL
    assert observation.ocr_state is contracts.OcrObservationState.NOT_CONFIGURED
    assert observation.visual_confidence == pytest.approx(0.91)


def test_public_observation_rejects_complete_state_without_observed_ocr(
) -> None:
    contracts = _contracts()
    adapter_module = _task12_module(
        "app.guide.adapters.image.ocr_observation"
    )
    observer = _identity().ImageIdentityObserver(
        visual_observation=FakeVisualObservationPort(
            _visual_observation((1, 0.91))
        ),
        ocr_observation=(
            adapter_module.NotConfiguredOcrObservationAdapter()
        ),
        canonical_identities=FakeCanonicalIdentityCatalog(
            {1: _canonical_identity(1)}
        ),
        policy=contracts.IdentityBindingPolicy(
            minimum_similarity=0.8,
            minimum_margin=0.1,
        ),
    )
    payload = observer.observe(_request()).model_dump()
    payload["observation_state"] = contracts.ObservationState.COMPLETE

    with pytest.raises(ValidationError, match="observation_state"):
        contracts.ImageIdentityObservation.model_validate(payload)


def test_public_observation_rejects_confirmed_identity_with_ocr_conflict(
) -> None:
    contracts = _contracts()
    observer, _, _ = _observer(
        visual_observation=_visual_observation((1, 0.91), (2, 0.7)),
        ocr_observation=_ocr_observation(),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )
    payload = observer.observe(_request()).model_dump()
    payload["ocr_brand_consistency"] = (
        contracts.IdentityEvidenceConsistency.CONFLICT
    )

    with pytest.raises(ValidationError, match="OCR conflict"):
        contracts.ImageIdentityObservation.model_validate(payload)


@pytest.mark.parametrize(
    "invalid_identity_state",
    ["visual_unavailable", "ocr_conflict"],
)
def test_public_observation_rejects_identity_state_without_matching_evidence(
    invalid_identity_state: str,
) -> None:
    contracts = _contracts()
    observer, _, _ = _observer(
        visual_observation=_visual_observation((1, 0.91)),
        ocr_observation=_ocr_observation(),
    )
    payload = observer.observe(_request()).model_dump()
    payload["identity_state"] = contracts.IdentityState(
        invalid_identity_state
    )
    payload["confirmed_product_id"] = None

    with pytest.raises(ValidationError, match="identity_state"):
        contracts.ImageIdentityObservation.model_validate(payload)


def test_public_observation_rejects_confirmed_identity_with_one_candidate(
) -> None:
    contracts = _contracts()
    observer, _, _ = _observer(
        visual_observation=_visual_observation((1, 0.91), (2, 0.7)),
        ocr_observation=_ocr_observation(),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )
    payload = observer.observe(_request()).model_dump()
    payload["candidate_product_ids"] = (1,)
    payload["similarity_margin"] = None

    with pytest.raises(ValidationError, match="multiple candidates"):
        contracts.ImageIdentityObservation.model_validate(payload)


@pytest.mark.parametrize(
    (
        "identity_state",
        "candidate_product_ids",
        "visual_confidence",
        "similarity_margin",
    ),
    [
        ("no_candidate", (1,), 0.95, None),
        ("ambiguous_candidates", (), None, None),
        ("low_confidence", (), None, None),
        ("non_canonical_candidate", (), None, None),
        ("canonical_identity_unavailable", (), None, None),
    ],
)
def test_public_observation_rejects_unconfirmed_state_evidence_mismatch(
    identity_state: str,
    candidate_product_ids: tuple[int, ...],
    visual_confidence: float | None,
    similarity_margin: float | None,
) -> None:
    contracts = _contracts()
    observer, _, _ = _observer(
        visual_observation=_visual_observation(),
        ocr_observation=_ocr_observation(),
    )
    payload = observer.observe(_request()).model_dump()
    payload["identity_state"] = contracts.IdentityState(identity_state)
    payload["candidate_product_ids"] = candidate_product_ids
    payload["visual_confidence"] = visual_confidence
    payload["similarity_margin"] = similarity_margin

    with pytest.raises(ValidationError, match="evidence shape"):
        contracts.ImageIdentityObservation.model_validate(payload)


def test_public_observation_rejects_ocr_conflict_without_candidates() -> None:
    contracts = _contracts()
    observer, _, _ = _observer(
        visual_observation=_visual_observation((1, 0.95), (2, 0.6)),
        ocr_observation=_ocr_observation(brand="conflict"),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )
    payload = observer.observe(_request()).model_dump()
    payload["candidate_product_ids"] = ()
    payload["visual_confidence"] = None
    payload["similarity_margin"] = None

    with pytest.raises(ValidationError, match="evidence shape"):
        contracts.ImageIdentityObservation.model_validate(payload)


def test_public_observation_rejects_pre_ocr_state_with_observed_ocr() -> None:
    contracts = _contracts()
    observer, _, _ = _observer(
        visual_observation=_visual_observation(),
        ocr_observation=_ocr_observation(),
    )
    payload = observer.observe(_request()).model_dump()
    payload["observation_state"] = contracts.ObservationState.COMPLETE
    payload["ocr_state"] = contracts.OcrObservationState.OBSERVED
    payload["ocr_brand_consistency"] = (
        contracts.IdentityEvidenceConsistency.CONSISTENT
    )
    payload["ocr_product_name_consistency"] = (
        contracts.IdentityEvidenceConsistency.INDETERMINATE
    )

    with pytest.raises(ValidationError, match="pre-OCR"):
        contracts.ImageIdentityObservation.model_validate(payload)


def test_low_confidence_candidate_fails_closed_without_running_ocr() -> None:
    contracts = _contracts()
    observer, _, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.79)),
        ocr_observation=_ocr_observation(),
    )

    observation = observer.observe(_request())

    assert (
        observation.identity_state
        is contracts.IdentityState.LOW_CONFIDENCE
    )
    assert observation.confirmed_product_id is None
    assert ocr_port.calls == []


def test_near_scored_candidates_confirm_with_independent_ocr_support() -> None:
    contracts = _contracts()
    observer, _, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.91), (2, 0.82)),
        ocr_observation=_ocr_observation(),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )

    observation = observer.observe(_request())

    assert observation.identity_state is contracts.IdentityState.CONFIRMED
    assert observation.confirmed_product_id == 1
    assert observation.candidate_product_ids == (1, 2)
    assert observation.similarity_margin == pytest.approx(0.09)
    assert len(ocr_port.calls) == 1


def test_no_candidates_fails_closed() -> None:
    contracts = _contracts()
    observer, _, ocr_port = _observer(
        visual_observation=_visual_observation(),
        ocr_observation=_ocr_observation(),
    )

    observation = observer.observe(_request())

    assert (
        observation.identity_state
        is contracts.IdentityState.NO_CANDIDATE
    )
    assert observation.confirmed_product_id is None
    assert observation.candidate_product_ids == ()
    assert ocr_port.calls == []


def test_single_candidate_fails_closed_without_running_ocr() -> None:
    contracts = _contracts()
    observer, _, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.95)),
        ocr_observation=_ocr_observation(),
    )

    observation = observer.observe(_request(max_results=1))

    assert (
        observation.identity_state
        is contracts.IdentityState.INSUFFICIENT_CANDIDATES
    )
    assert observation.confirmed_product_id is None
    assert observation.candidate_product_ids == (1,)
    assert observation.visual_confidence == pytest.approx(0.95)
    assert observation.similarity_margin is None
    assert ocr_port.calls == []


def test_any_noncanonical_visual_candidate_fails_closed() -> None:
    contracts = _contracts()
    observer, _, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.95), (999, 0.5)),
        ocr_observation=_ocr_observation(),
    )

    observation = observer.observe(_request())

    assert (
        observation.identity_state
        is contracts.IdentityState.NON_CANONICAL_CANDIDATE
    )
    assert observation.confirmed_product_id is None
    assert ocr_port.calls == []


def test_missing_canonical_identity_fails_closed_before_ocr() -> None:
    contracts = _contracts()
    observer, _, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.95)),
        ocr_observation=_ocr_observation(),
        identities={},
        extra_product_ids={1},
    )

    observation = observer.observe(_request())

    assert (
        observation.identity_state
        is contracts.IdentityState.CANONICAL_IDENTITY_UNAVAILABLE
    )
    assert observation.confirmed_product_id is None
    assert ocr_port.calls == []


@pytest.mark.parametrize("conflicting_field", ["brand", "product_name"])
def test_ocr_identity_conflict_vetoes_visual_confirmation(
    conflicting_field: str,
) -> None:
    contracts = _contracts()
    consistency = {
        "brand": "consistent",
        "product_name": "consistent",
    }
    consistency[conflicting_field] = "conflict"
    observer, _, ocr_port = _observer(
        visual_observation=_visual_observation((1, 0.95), (2, 0.6)),
        ocr_observation=_ocr_observation(**consistency),
        identities={1: _canonical_identity(1), 2: _canonical_identity(2)},
    )

    observation = observer.observe(_request())

    assert (
        observation.identity_state
        is contracts.IdentityState.OCR_CONFLICT
    )
    assert observation.confirmed_product_id is None
    assert len(ocr_port.calls) == 1


@pytest.mark.parametrize(
    ("ocr_line", "conflicting_field"),
    (
        ("Brand Name: OTHER BRAND", "brand"),
        ("Product Name: OTHER GEL", "product_name"),
    ),
)
def test_spaced_english_label_conflict_vetoes_visual_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    ocr_line: str,
    conflicting_field: str,
) -> None:
    class Engine:
        def __call__(self, content: bytes) -> object:
            del content
            return [
                [
                    [[0, 0], [1, 0], [1, 1], [0, 1]],
                    ocr_line,
                    0.90,
                ]
            ]

    monkeypatch.setattr(
        ocr_adapter_module,
        "_build_approved_engine",
        lambda: Engine(),
    )
    contracts = _contracts()
    canonical_identities = {
        1: contracts.CanonicalIdentity(
            product_id=1,
            brand="ANESSA",
            product_name="ANESSA GEL",
        ),
        2: _canonical_identity(2),
    }
    observer = _identity().ImageIdentityObserver(
        visual_observation=FakeVisualObservationPort(
            _visual_observation((1, 0.95), (2, 0.6))
        ),
        ocr_observation=(
            ocr_adapter_module.RapidOcrObservationAdapter()
        ),
        canonical_identities=FakeCanonicalIdentityCatalog(
            canonical_identities
        ),
        policy=contracts.IdentityBindingPolicy(
            minimum_similarity=0.8,
            minimum_margin=0.1,
        ),
    )

    observation = observer.observe(_request())

    assert (
        getattr(observation, f"ocr_{conflicting_field}_consistency")
        is contracts.IdentityEvidenceConsistency.CONFLICT
    )
    assert (
        observation.identity_state
        is contracts.IdentityState.OCR_CONFLICT
    )
    assert observation.confirmed_product_id is None


def test_visual_unavailable_fails_closed() -> None:
    contracts = _contracts()
    visual_observation = contracts.VisualCandidateObservation(
        state=contracts.VisualObservationState.UNAVAILABLE,
        result=None,
    )
    observer, _, ocr_port = _observer(
        visual_observation=visual_observation,
        ocr_observation=_ocr_observation(),
    )

    observation = observer.observe(_request())

    assert (
        observation.observation_state
        is contracts.ObservationState.UNAVAILABLE
    )
    assert (
        observation.identity_state
        is contracts.IdentityState.VISUAL_UNAVAILABLE
    )
    assert observation.confirmed_product_id is None
    assert ocr_port.calls == []


def test_canonical_identity_adapter_reads_only_authoritative_fields() -> None:
    adapter_module = _task12_module(
        "app.guide.adapters.catalog.canonical_identity_catalog"
    )
    canonical = ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    catalog = adapter_module.CanonicalIdentityCatalog(reader)

    identity = catalog.get_identity(55)

    assert 55 in catalog.product_ids
    assert identity.product_id == 55
    assert identity.brand == "Winona/薇诺娜"
    assert identity.product_name == "清透防晒乳"
