from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import importlib
from importlib import metadata as importlib_metadata
import math
from pathlib import Path
import re
from threading import Lock
from typing import Protocol
import unicodedata

from app.guide.adapters.image.inference_limiter import (
    image_inference_slot,
)
from app.guide.retrieval.image_contracts import ImageRetrievalRequest
from app.guide.understanding.image_contracts import (
    CanonicalIdentity,
    IdentityEvidenceConsistency,
    OcrIdentityTrace,
    OcrIdentityObservation,
    OcrObservationState,
    OcrTraceLine,
)


APPROVED_RAPIDOCR_DISTRIBUTION = "rapidocr-onnxruntime"
APPROVED_RAPIDOCR_VERSION = "1.3.0"

# OCR can veto a visually confirmed identity, so only lines at or above this
# deliberately conservative threshold may contribute identity evidence.
MINIMUM_IDENTITY_EVIDENCE_CONFIDENCE = 0.90

_BRAND_LABELS = (
    "品牌名称",
    "品牌",
    "brand name",
    "brandname",
    "brand",
)
_PRODUCT_NAME_LABELS = (
    "产品名称",
    "商品名称",
    "product name",
    "productname",
    "品名",
)
_MINIMUM_LATIN_SUBSTRING_LENGTH = 4
_MINIMUM_ENGLISH_TOKEN_LENGTH = 3
_MINIMUM_TOKEN_COVERAGE_COUNT = 2
_ENGLISH_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class _RapidOcrEngine(Protocol):
    def __call__(self, content: bytes) -> object: ...


@dataclass(frozen=True, slots=True)
class _ParsedOcrLine:
    text: str
    confidence: float


class RapidOcrObservationAdapter:
    """Approved OCR evidence adapter with no raw-text output surface."""

    def __init__(self) -> None:
        self._engine: _RapidOcrEngine | None = None
        self._engine_unavailable = False
        self._engine_lock = Lock()

    def observe(
        self,
        request: ImageRetrievalRequest,
        canonical_identity: CanonicalIdentity,
    ) -> OcrIdentityObservation:
        observation, _ = self.observe_with_trace(
            request,
            canonical_identity,
        )
        return observation

    def observe_with_trace(
        self,
        request: ImageRetrievalRequest,
        canonical_identity: CanonicalIdentity,
    ) -> tuple[OcrIdentityObservation, OcrIdentityTrace]:
        try:
            with image_inference_slot():
                engine = self._get_engine()
                if engine is None:
                    return (
                        _unavailable_observation(),
                        _rapidocr_trace(()),
                    )
                output = engine(request.content)
            lines = _parse_rapidocr_text_lines(output)
        except Exception:
            return (
                _unavailable_observation(),
                _rapidocr_trace(()),
            )

        evidence_lines = tuple(
            line
            for line in lines
            if line.confidence >= MINIMUM_IDENTITY_EVIDENCE_CONFIDENCE
        )
        trace = _rapidocr_trace(lines)
        if not evidence_lines:
            return _unavailable_observation(), trace

        return (
            OcrIdentityObservation(
                state=OcrObservationState.OBSERVED,
                brand_consistency=_identity_consistency(
                    canonical_identity.brand,
                    evidence_lines,
                    labels=_BRAND_LABELS,
                ),
                product_name_consistency=_identity_consistency(
                    canonical_identity.product_name,
                    evidence_lines,
                    labels=_PRODUCT_NAME_LABELS,
                ),
            ),
            trace,
        )

    def _get_engine(self) -> _RapidOcrEngine | None:
        if self._engine_unavailable:
            return None
        if self._engine is not None:
            return self._engine
        with self._engine_lock:
            if self._engine_unavailable:
                return None
            if self._engine is not None:
                return self._engine
            try:
                self._engine = _build_approved_engine()
            except Exception:
                self._engine_unavailable = True
                return None
            return self._engine


class NotConfiguredOcrObservationAdapter:
    """Production-safe default until a separate OCR adapter is approved."""

    def observe(
        self,
        request: ImageRetrievalRequest,
        canonical_identity: CanonicalIdentity,
    ) -> OcrIdentityObservation:
        observation, _ = self.observe_with_trace(
            request,
            canonical_identity,
        )
        return observation

    def observe_with_trace(
        self,
        request: ImageRetrievalRequest,
        canonical_identity: CanonicalIdentity,
    ) -> tuple[OcrIdentityObservation, OcrIdentityTrace]:
        del request, canonical_identity
        return (
            OcrIdentityObservation(
                state=OcrObservationState.NOT_CONFIGURED,
                brand_consistency=(
                    IdentityEvidenceConsistency.NOT_CHECKED
                ),
                product_name_consistency=(
                    IdentityEvidenceConsistency.NOT_CHECKED
                ),
            ),
            OcrIdentityTrace(
                engine="not_configured",
                engine_version=None,
                minimum_evidence_confidence=(
                    MINIMUM_IDENTITY_EVIDENCE_CONFIDENCE
                ),
                lines=(),
                evidence_line_count=0,
            ),
        )


def _rapidocr_trace(
    lines: tuple[_ParsedOcrLine, ...],
) -> OcrIdentityTrace:
    return OcrIdentityTrace(
        engine=APPROVED_RAPIDOCR_DISTRIBUTION,
        engine_version=APPROVED_RAPIDOCR_VERSION,
        minimum_evidence_confidence=(
            MINIMUM_IDENTITY_EVIDENCE_CONFIDENCE
        ),
        lines=tuple(
            OcrTraceLine(
                text=line.text,
                confidence=line.confidence,
            )
            for line in lines
        ),
        evidence_line_count=sum(
            line.confidence >= MINIMUM_IDENTITY_EVIDENCE_CONFIDENCE
            for line in lines
        ),
    )


def _build_approved_engine() -> _RapidOcrEngine:
    distribution = importlib_metadata.distribution(
        APPROVED_RAPIDOCR_DISTRIBUTION
    )
    if distribution.version != APPROVED_RAPIDOCR_VERSION:
        raise RuntimeError("unapproved RapidOCR distribution version")
    module = importlib.import_module("rapidocr_onnxruntime")
    _require_distribution_owned_module(module, distribution)
    engine_type = getattr(module, "RapidOCR", None)
    if not callable(engine_type):
        raise RuntimeError("approved RapidOCR engine is unavailable")
    engine = engine_type()
    if not callable(engine):
        raise RuntimeError("approved RapidOCR engine is not callable")
    return engine


def _require_distribution_owned_module(
    module: object,
    distribution: importlib_metadata.Distribution,
) -> None:
    distribution_files = distribution.files
    if not distribution_files:
        raise RuntimeError("approved RapidOCR distribution files unavailable")

    try:
        distribution_root = Path(
            distribution.locate_file("")
        ).resolve(strict=True)
        owned_files = {
            Path(distribution.locate_file(path)).resolve(strict=True)
            for path in distribution_files
        }
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            "approved RapidOCR distribution files unavailable"
        ) from exc

    module_file = getattr(module, "__file__", None)
    module_spec = getattr(module, "__spec__", None)
    spec_origin = getattr(module_spec, "origin", None)
    if not isinstance(module_file, str) or not isinstance(spec_origin, str):
        raise RuntimeError("approved RapidOCR module origin unavailable")

    try:
        module_origins = {
            Path(module_file).resolve(strict=True),
            Path(spec_origin).resolve(strict=True),
        }
    except OSError as exc:
        raise RuntimeError(
            "approved RapidOCR module origin unavailable"
        ) from exc

    if any(
        origin not in owned_files
        or not origin.is_relative_to(distribution_root)
        for origin in module_origins
    ):
        raise RuntimeError(
            "RapidOCR module is not owned by the approved distribution"
        )


def _parse_rapidocr_text_lines(
    output: object,
) -> tuple[_ParsedOcrLine, ...]:
    lines: object = output
    if (
        isinstance(output, tuple)
        and len(output) == 2
        and not _is_rapidocr_line(output[0])
    ):
        lines = output[0]

    if lines is None:
        return ()
    if (
        not isinstance(lines, Sequence)
        or isinstance(lines, (str, bytes, bytearray))
    ):
        raise ValueError("RapidOCR result lines are malformed")

    parsed: list[_ParsedOcrLine] = []
    for line in lines:
        if not _is_rapidocr_line(line):
            raise ValueError("RapidOCR result line is malformed")
        text = line[1]
        confidence = line[2]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("RapidOCR text is malformed")
        if isinstance(confidence, bool):
            raise ValueError("RapidOCR confidence is malformed")
        try:
            numeric_confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("RapidOCR confidence is malformed") from exc
        if (
            not math.isfinite(numeric_confidence)
            or not 0.0 <= numeric_confidence <= 1.0
        ):
            raise ValueError("RapidOCR confidence is out of range")
        parsed.append(
            _ParsedOcrLine(
                text=text.strip(),
                confidence=numeric_confidence,
            )
        )
    return tuple(parsed)


def _is_rapidocr_line(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 3
        and _is_rapidocr_box(value[0])
        and isinstance(value[1], str)
    )


def _is_rapidocr_box(value: object) -> bool:
    box = value
    if not isinstance(box, Sequence):
        to_list = getattr(box, "tolist", None)
        if not callable(to_list):
            return False
        try:
            box = to_list()
        except Exception:
            return False
    if (
        not isinstance(box, Sequence)
        or isinstance(box, (str, bytes, bytearray))
        or len(box) != 4
    ):
        return False
    for point in box:
        if (
            not isinstance(point, Sequence)
            or isinstance(point, (str, bytes, bytearray))
            or len(point) != 2
        ):
            return False
        for coordinate in point:
            if (
                isinstance(coordinate, bool)
                or not isinstance(coordinate, (int, float))
                or not math.isfinite(float(coordinate))
            ):
                return False
    return True


def _identity_consistency(
    canonical_value: str | None,
    lines: tuple[_ParsedOcrLine, ...],
    *,
    labels: tuple[str, ...],
) -> IdentityEvidenceConsistency:
    if canonical_value is None:
        return IdentityEvidenceConsistency.NOT_CHECKED

    canonical = _normalize_observed_text(canonical_value)
    if not canonical:
        return IdentityEvidenceConsistency.INDETERMINATE
    explicit_values = _explicit_label_values(lines, labels)
    if explicit_values:
        if any(
            not _identity_values_overlap(
                canonical,
                _normalize_observed_text(value),
            )
            for value in explicit_values
        ):
            return IdentityEvidenceConsistency.CONFLICT
        return IdentityEvidenceConsistency.CONSISTENT

    unlabelled_lines = tuple(
        line for line in lines if not _is_labelled_text(line.text)
    )
    if any(
        _identity_values_overlap(
            canonical,
            _normalize_observed_text(line.text),
        )
        for line in unlabelled_lines
    ):
        return IdentityEvidenceConsistency.CONSISTENT
    if _has_meaningful_english_token_coverage(
        canonical_value,
        tuple(line.text for line in unlabelled_lines),
    ):
        return IdentityEvidenceConsistency.CONSISTENT
    return IdentityEvidenceConsistency.INDETERMINATE


def _explicit_label_values(
    lines: tuple[_ParsedOcrLine, ...],
    labels: tuple[str, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    for line in lines:
        folded_line = _fold_observed_text(line.text).strip()
        for label in labels:
            folded_label = _fold_observed_text(label)
            if not folded_line.startswith(folded_label):
                continue
            suffix = folded_line[len(folded_label) :].lstrip()
            if suffix.startswith(":") and suffix[1:].strip():
                values.append(suffix[1:].strip())
                break
    return tuple(values)


def _is_labelled_text(value: str) -> bool:
    label, separator, content = _fold_observed_text(value).partition(":")
    return bool(separator and label.strip() and content.strip())


def _identity_values_overlap(canonical: str, observed: str) -> bool:
    if not canonical or not observed:
        return False
    if canonical == observed:
        return True
    shorter = canonical if len(canonical) <= len(observed) else observed
    if not _is_meaningful_substring(shorter):
        return False
    return canonical in observed or observed in canonical


def _is_meaningful_substring(value: str) -> bool:
    if value.isascii():
        return len(value) >= _MINIMUM_LATIN_SUBSTRING_LENGTH
    return len(value) >= 2


def _has_meaningful_english_token_coverage(
    canonical_value: str,
    observed_lines: tuple[str, ...],
) -> bool:
    canonical_tokens = _meaningful_english_tokens(canonical_value)
    if len(canonical_tokens) < _MINIMUM_TOKEN_COVERAGE_COUNT:
        return False
    observed_tokens = {
        token
        for line in observed_lines
        for token in _meaningful_english_tokens(line)
    }
    return canonical_tokens <= observed_tokens


def _meaningful_english_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _ENGLISH_TOKEN_PATTERN.findall(
            _fold_observed_text(value)
        )
        if len(token) >= _MINIMUM_ENGLISH_TOKEN_LENGTH
    )


def _normalize_observed_text(value: str) -> str:
    return "".join(
        character
        for character in _fold_observed_text(value)
        if character.isalnum()
    )


def _fold_observed_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )


def _unavailable_observation() -> OcrIdentityObservation:
    return OcrIdentityObservation(
        state=OcrObservationState.UNAVAILABLE,
        brand_consistency=IdentityEvidenceConsistency.NOT_CHECKED,
        product_name_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
    )
