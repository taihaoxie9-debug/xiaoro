from __future__ import annotations

import hashlib
from importlib.machinery import ModuleSpec
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

import app.guide.adapters.image.ocr_observation as adapter_module
from app.guide.retrieval.image_contracts import ImageRetrievalRequest
from app.guide.understanding.image_contracts import (
    CanonicalIdentity,
    IdentityEvidenceConsistency,
    OcrObservationState,
)


def _request() -> ImageRetrievalRequest:
    content = b"validated-packaging-or-ingredient-label"
    return ImageRetrievalRequest(
        image_id="image_" + "a" * 32,
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        max_results=3,
    )


def _identity(
    *,
    brand: str | None = "ANESSA",
    product_name: str | None = "ANESSA MEN UV SUNSCREEN GEL",
) -> CanonicalIdentity:
    return CanonicalIdentity(
        product_id=53,
        brand=brand,
        product_name=product_name,
    )


def _line(
    text: str,
    confidence: float | str = 0.99,
    *,
    box: object | None = None,
) -> list[Any]:
    return [
        box
        if box is not None
        else [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        text,
        confidence,
    ]


class _Engine:
    def __init__(self, result: object) -> None:
        self.result = result
        self.contents: list[bytes] = []

    def __call__(self, content: bytes) -> object:
        self.contents.append(content)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _install_engine(
    monkeypatch: pytest.MonkeyPatch,
    result: object,
) -> _Engine:
    engine = _Engine(result)
    monkeypatch.setattr(
        adapter_module,
        "_build_approved_engine",
        lambda: engine,
        raising=False,
    )
    return engine


class _Distribution:
    def __init__(
        self,
        root: Path,
        *,
        version: str = "1.3.0",
        files: tuple[Path, ...] | None = None,
    ) -> None:
        self.version = version
        self.files = files
        self._root = root

    def locate_file(self, path: object) -> Path:
        return self._root / Path(path)


def _module_at(path: Path, engine_type: type[object]) -> ModuleType:
    module = ModuleType("rapidocr_onnxruntime")
    module.__file__ = str(path)
    module.__spec__ = ModuleSpec(
        name="rapidocr_onnxruntime",
        loader=None,
        origin=str(path),
    )
    module.RapidOCR = engine_type
    return module


def test_approved_adapter_is_exported_by_image_adapters() -> None:
    from app.guide.adapters import image

    assert (
        image.RapidOcrObservationAdapter
        is adapter_module.RapidOcrObservationAdapter
    )


def test_approved_rapidocr_observation_returns_only_consistency_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _install_engine(
        monkeypatch,
        (
            [
                _line("ANESSA MEN"),
                _line("UV SUNSCREEN GEL"),
                _line("成分：氧化锌、甘油"),
            ],
            [0.1, 0.2, 0.3],
        ),
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )
    assert engine.contents == [_request().content]
    assert set(observation.model_dump()) == {
        "state",
        "brand_consistency",
        "product_name_consistency",
    }
    assert "ANESSA" not in str(observation.model_dump())
    assert "氧化锌" not in str(observation.model_dump())


def test_parser_preserves_confidence_from_approved_wrapped_result_shape() -> None:
    parsed = adapter_module._parse_rapidocr_text_lines(
        (
            [
                [
                    [
                        [10.0, 20.0],
                        [110.0, 20.0],
                        [110.0, 50.0],
                        [10.0, 50.0],
                    ],
                    "LANCÔME",
                    "0.91",
                ]
            ],
            [0.01, 0.0, 0.02],
        )
    )

    assert len(parsed) == 1
    assert parsed[0].text == "LANCÔME"
    assert parsed[0].confidence == pytest.approx(0.91)


def test_parser_supports_approved_direct_result_lines() -> None:
    parsed = adapter_module._parse_rapidocr_text_lines(
        [
            (
                (
                    (10, 20),
                    (110, 20),
                    (110, 50),
                    (10, 50),
                ),
                "ANESSA",
                0.99,
            )
        ]
    )

    assert len(parsed) == 1
    assert parsed[0].text == "ANESSA"
    assert parsed[0].confidence == pytest.approx(0.99)


def test_parser_supports_numpy_box_with_four_finite_2d_points() -> None:
    parsed = adapter_module._parse_rapidocr_text_lines(
        [
            _line(
                "ANESSA",
                box=np.asarray(
                    [
                        [10.0, 20.0],
                        [110.0, 20.0],
                        [110.0, 50.0],
                        [10.0, 50.0],
                    ],
                    dtype=np.float32,
                ),
            )
        ]
    )

    assert len(parsed) == 1
    assert parsed[0].text == "ANESSA"
    assert parsed[0].confidence == pytest.approx(0.99)


def test_direct_rapidocr_lines_are_supported_without_exposing_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        [
            _line("品牌：ANESSA"),
            _line("产品名称：ANESSA MEN UV SUNSCREEN GEL"),
        ],
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )


def test_low_confidence_labeled_conflict_is_indeterminate_and_cannot_veto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        (
            [
                _line("品牌：OTHER BRAND", confidence=0.0),
                _line(
                    "产品名称：UV SUNSCREEN GEL",
                    confidence=0.99,
                ),
            ],
            [0.1, 0.2, 0.3],
        ),
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(product_name="UV SUNSCREEN GEL"),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.INDETERMINATE
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )


def test_confidence_threshold_is_inclusive_at_ninety_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        [_line("品牌：ANESSA", confidence=0.90)],
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(product_name=None),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )


@pytest.mark.parametrize(
    "result",
    (
        None,
        [],
        (None, [0.0, 0.0, 0.0]),
        ([], [0.0, 0.0, 0.0]),
        ([_line("品牌：OTHER BRAND", confidence=0.899)], [0.1]),
    ),
)
def test_empty_or_all_filtered_results_are_unavailable_and_not_checked(
    monkeypatch: pytest.MonkeyPatch,
    result: object,
) -> None:
    _install_engine(monkeypatch, result)

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.UNAVAILABLE
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.NOT_CHECKED
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.NOT_CHECKED
    )


def test_explicit_label_conflict_wins_over_unlabelled_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        (
            [
                _line("ANESSA"),
                _line("品牌：OTHER BRAND"),
                _line("产品名称：ANESSA MEN UV SUNSCREEN GEL"),
            ],
            [0.1, 0.2, 0.3],
        ),
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.CONFLICT
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )


def test_spaced_english_labels_are_authoritative_conflict_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        [
            _line("Brand Name: OTHER BRAND", confidence=0.90),
            _line("Product Name: OTHER GEL", confidence=0.90),
        ],
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.CONFLICT
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.CONFLICT
    )


def test_separate_single_character_lines_do_not_match_combined_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        [_line("A"), _line("B")],
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(brand="AB", product_name=None),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.INDETERMINATE
    )


def test_short_canonical_token_does_not_match_incidental_substring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(monkeypatch, [_line("ANESSA")])

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(brand="AN", product_name=None),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.INDETERMINATE
    )


def test_brand_story_narrative_is_not_an_explicit_brand_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(monkeypatch, [_line("品牌故事：OTHER BRAND")])

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(product_name=None),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.INDETERMINATE
    )


def test_brand_story_match_is_not_authoritative_brand_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(monkeypatch, [_line("品牌故事：ANESSA")])

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(product_name=None),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.INDETERMINATE
    )


def test_accented_brand_matches_ascii_canonical_without_short_token_widening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(monkeypatch, [_line("LANCÔME")])

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(brand="LANCOME", product_name=None),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )


def test_split_english_product_name_uses_meaningful_token_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        [
            _line("LANCÔME ADVANCED"),
            _line("GÉNIFIQUE SERUM"),
        ],
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(
            brand=None,
            product_name="LANCOME ADVANCED GENIFIQUE SERUM",
        ),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )


def test_unlabelled_nonmatch_is_indeterminate_not_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        ([_line("成分：水、甘油、烟酰胺")], [0.1, 0.2, 0.3]),
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.INDETERMINATE
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.INDETERMINATE
    )


def test_missing_canonical_field_remains_not_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        ([_line("ANESSA")], [0.1, 0.2, 0.3]),
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(product_name=None),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.CONSISTENT
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.NOT_CHECKED
    )


def test_noncomparable_canonical_field_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_engine(
        monkeypatch,
        ([_line("ANESSA")], [0.1, 0.2, 0.3]),
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(brand="——"),
    )

    assert observation.state is OcrObservationState.OBSERVED
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.INDETERMINATE
    )


@pytest.mark.parametrize(
    "result",
    (
        RuntimeError("model unavailable"),
        ("malformed", "result"),
        ([_line("ANESSA", confidence="not-a-number")], [0.1]),
    ),
)
def test_engine_or_result_failure_is_unavailable_and_not_checked(
    monkeypatch: pytest.MonkeyPatch,
    result: object,
) -> None:
    _install_engine(monkeypatch, result)

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.UNAVAILABLE
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.NOT_CHECKED
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.NOT_CHECKED
    )


@pytest.mark.parametrize(
    "line",
    (
        [None, "ANESSA", 0.99],
        [
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
            "ANESSA",
            0.99,
        ],
        [
            [[0.0, 0.0], [1.0], [1.0, 1.0], [0.0, 1.0]],
            "ANESSA",
            0.99,
        ],
        [
            [
                [0.0, 0.0],
                [float("inf"), 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            "ANESSA",
            0.99,
        ],
        [
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            "ANESSA",
            0.99,
            "unexpected",
        ],
        _line(
            "ANESSA",
            box=np.asarray(
                [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
                dtype=np.float32,
            ),
        ),
        _line(
            "ANESSA",
            box=np.asarray(
                [
                    [0.0, 0.0],
                    [float("inf"), 0.0],
                    [1.0, 1.0],
                    [0.0, 1.0],
                ],
                dtype=np.float32,
            ),
        ),
    ),
)
def test_malformed_line_geometry_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    line: object,
) -> None:
    _install_engine(monkeypatch, [line])

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.UNAVAILABLE
    assert (
        observation.brand_consistency
        is IdentityEvidenceConsistency.NOT_CHECKED
    )
    assert (
        observation.product_name_consistency
        is IdentityEvidenceConsistency.NOT_CHECKED
    )


def test_missing_distribution_fails_closed_without_importing_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_distribution(distribution_name: str) -> object:
        raise PackageNotFoundError(distribution_name)

    imported: list[str] = []
    monkeypatch.setattr(
        adapter_module.importlib_metadata,
        "distribution",
        missing_distribution,
        raising=False,
    )
    monkeypatch.setattr(
        adapter_module.importlib,
        "import_module",
        lambda name: imported.append(name),
        raising=False,
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.UNAVAILABLE
    assert imported == []


def test_shadow_module_outside_distribution_files_fails_before_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    distribution_root = tmp_path / "installed"
    approved_module = (
        distribution_root / "rapidocr_onnxruntime" / "__init__.py"
    )
    approved_module.parent.mkdir(parents=True)
    approved_module.write_text("", encoding="utf-8")

    shadow_module = tmp_path / "shadow" / "rapidocr_onnxruntime.py"
    shadow_module.parent.mkdir()
    shadow_module.write_text("", encoding="utf-8")
    constructed: list[bool] = []

    class ShadowRapidOCR:
        def __init__(self) -> None:
            constructed.append(True)

        def __call__(self, content: bytes) -> object:
            del content
            return [_line("ANESSA")]

    distribution = _Distribution(
        distribution_root,
        files=(Path("rapidocr_onnxruntime/__init__.py"),),
    )
    monkeypatch.setattr(
        adapter_module.importlib_metadata,
        "distribution",
        lambda distribution_name: distribution,
        raising=False,
    )
    monkeypatch.setattr(
        adapter_module.importlib,
        "import_module",
        lambda name: _module_at(shadow_module, ShadowRapidOCR),
        raising=False,
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.UNAVAILABLE
    assert constructed == []


def test_distribution_owned_module_can_be_constructed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    distribution_root = tmp_path / "installed"
    module_file = distribution_root / "rapidocr_onnxruntime" / "__init__.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")

    class ApprovedRapidOCR:
        def __call__(self, content: bytes) -> object:
            del content
            return [_line("ANESSA")]

    distribution = _Distribution(
        distribution_root,
        files=(Path("rapidocr_onnxruntime/__init__.py"),),
    )
    monkeypatch.setattr(
        adapter_module.importlib_metadata,
        "distribution",
        lambda distribution_name: distribution,
        raising=False,
    )
    monkeypatch.setattr(
        adapter_module.importlib,
        "import_module",
        lambda name: _module_at(module_file, ApprovedRapidOCR),
        raising=False,
    )

    engine = adapter_module._build_approved_engine()

    assert isinstance(engine, ApprovedRapidOCR)


def test_unapproved_distribution_version_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    imported: list[str] = []
    monkeypatch.setattr(
        adapter_module.importlib_metadata,
        "distribution",
        lambda distribution_name: _Distribution(
            tmp_path,
            version="1.3.1",
        ),
        raising=False,
    )
    monkeypatch.setattr(
        adapter_module.importlib,
        "import_module",
        lambda name: imported.append(name),
        raising=False,
    )

    observation = adapter_module.RapidOcrObservationAdapter().observe(
        _request(),
        _identity(),
    )

    assert observation.state is OcrObservationState.UNAVAILABLE
    assert imported == []
