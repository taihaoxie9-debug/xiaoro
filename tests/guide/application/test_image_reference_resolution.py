from __future__ import annotations

import importlib
import inspect
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.guide.understanding.contracts import ImageBundle, ImageObservation
from app.guide.understanding.image_contracts import (
    IdentityEvidenceConsistency,
    IdentityState,
    ImageIdentityObservation,
    ObservationState,
    OcrObservationState,
    VisualObservationState,
)


def _subject():
    try:
        return importlib.import_module(
            "app.guide.application.image_reference_resolution"
        )
    except ModuleNotFoundError:
        pytest.fail("image reference resolution module is missing")


def _parsing():
    try:
        return importlib.import_module(
            "app.guide.understanding.image_reference_parsing"
        )
    except ModuleNotFoundError:
        pytest.fail("image reference parsing module is missing")


def _bundle(
    count: int,
    *,
    bundle_suffix: str = "a",
    image_suffix_start: int = 1,
    focused_image_ordinal: object = None,
) -> ImageBundle:
    created_at = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
    return ImageBundle(
        bundle_id="bundle_" + bundle_suffix * 32,
        session_id="session-current",
        owner_token_sha256="f" * 64,
        version=1,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=15),
        images=[
            ImageObservation(
                image_id=f"image_{index:032d}",
                ordinal=ordinal,
                content_sha256=f"{index:x}".rjust(64, "0"),
                media_type="image/jpeg",
                image_format="JPEG",
                width=4,
                height=3,
                byte_size=631,
            )
            for ordinal, index in enumerate(
                range(image_suffix_start, image_suffix_start + count),
                start=1,
            )
        ],
        focused_image_ordinal=focused_image_ordinal,
    )


def _identity(
    image_id: str,
    product_id: int,
) -> ImageIdentityObservation:
    return ImageIdentityObservation(
        image_id=image_id,
        observation_state=ObservationState.PARTIAL,
        visual_state=VisualObservationState.OBSERVED,
        ocr_state=OcrObservationState.NOT_CONFIGURED,
        identity_state=IdentityState.CONFIRMED,
        confirmed_product_id=product_id,
        candidate_product_ids=(product_id, product_id + 1000),
        visual_confidence=0.95,
        similarity_margin=0.2,
        model_name="approved-openclip",
        weights_sha256="a" * 64,
        preprocessing_version="openclip-preprocess-v1",
        vector_dimension=512,
        index_sha256="b" * 64,
        ocr_brand_consistency=IdentityEvidenceConsistency.NOT_CHECKED,
        ocr_product_name_consistency=(
            IdentityEvidenceConsistency.NOT_CHECKED
        ),
    )


def _build(bundle: ImageBundle):
    observations = [
        _identity(image.image_id, 50 + image.ordinal)
        for image in reversed(bundle.images)
    ]
    return _subject().build_multi_image_context(
        mode="identify" if len(bundle.images) == 1 else "compare",
        bundle=bundle,
        identity_observations=observations,
    )


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_builds_stable_contiguous_references_from_current_bundle_records(
    count: int,
) -> None:
    bundle = _bundle(count)

    result = _build(bundle)

    assert result.kind == "ready"
    assert result.context.bundle_id == bundle.bundle_id
    assert [item.ordinal for item in result.context.references] == list(
        range(1, count + 1)
    )
    assert [
        item.image_id for item in result.context.references
    ] == [item.image_id for item in bundle.images]
    assert [
        item.confirmed_product_id for item in result.context.references
    ] == list(range(51, 51 + count))


def test_image_focus_is_explicit_and_round_trips_without_defaulting_to_one(
) -> None:
    unfocused = _bundle(1)
    payload = _bundle(2).model_dump(mode="python")
    payload["focused_image_ordinal"] = 2
    focused = ImageBundle.model_validate(payload)

    assert unfocused.focused_image_ordinal is None
    assert focused.focused_image_ordinal == 2
    assert ImageBundle.model_validate_json(focused.model_dump_json()) == focused


@pytest.mark.parametrize("focus", [0, 2, True, "1"])
def test_image_focus_rejects_non_strict_or_out_of_range_ordinal(
    focus: object,
) -> None:
    payload = _bundle(1).model_dump(mode="python")
    payload["focused_image_ordinal"] = focus

    with pytest.raises(ValidationError):
        ImageBundle.model_validate(payload)


def test_context_builder_has_no_client_product_id_input() -> None:
    subject = _subject()
    bundle = _bundle(1)
    observations = [_identity(bundle.images[0].image_id, 51)]

    assert "product_ids" not in inspect.signature(
        subject.build_multi_image_context
    ).parameters
    with pytest.raises(TypeError):
        subject.build_multi_image_context(
            mode="identify",
            bundle=bundle,
            identity_observations=observations,
            product_ids=[999],
        )


def test_missing_bundle_clarifies_and_foreign_identity_record_errors() -> None:
    subject = _subject()
    missing = subject.build_multi_image_context(
        mode="identify",
        bundle=None,
        identity_observations=[],
    )
    current = _bundle(2)
    foreign = _bundle(
        1,
        bundle_suffix="z",
        image_suffix_start=9,
    )
    mismatched = subject.build_multi_image_context(
        mode="compare",
        bundle=current,
        identity_observations=[
            _identity(current.images[0].image_id, 51),
            _identity(foreign.images[0].image_id, 59),
        ],
    )

    assert missing.kind == "clarification"
    assert missing.code == "no_current_bundle"
    assert mismatched.kind == "error"
    assert mismatched.code == "identity_record_bundle_mismatch"
    assert mismatched.context is None


@pytest.mark.parametrize(
    ("message", "ordinal"),
    [
        ("第一张", 1),
        ("第二张", 2),
        ("第三张", 3),
        ("第四张", 4),
    ],
)
def test_resolves_chinese_ordinal_only_to_current_context_image(
    message: str,
    ordinal: int,
) -> None:
    subject = _subject()
    bundle = _bundle(4)
    context = _build(bundle).context

    result = subject.resolve_image_reference(
        _parsing().parse_image_reference(message),
        bundle=bundle,
        context=context,
    )

    assert result.kind == "resolved"
    assert result.bundle_id == bundle.bundle_id
    assert result.ordinal == ordinal
    assert result.image_id == bundle.images[ordinal - 1].image_id


def test_out_of_range_and_missing_current_bundle_are_typed_clarifications(
) -> None:
    subject = _subject()
    bundle = _bundle(2)
    context = _build(bundle).context

    out_of_range = subject.resolve_image_reference(
        _parsing().parse_image_reference("第三张"),
        bundle=bundle,
        context=context,
    )
    missing = subject.resolve_image_reference(
        _parsing().parse_image_reference("第一张"),
        bundle=None,
        context=None,
    )

    assert out_of_range.kind == "clarification"
    assert out_of_range.code == "ordinal_out_of_range"
    assert out_of_range.image_id is None
    assert missing.kind == "clarification"
    assert missing.code == "no_current_bundle"
    assert missing.image_id is None


def test_stale_or_foreign_bundle_context_never_resolves() -> None:
    subject = _subject()
    current = _bundle(2, bundle_suffix="a", image_suffix_start=1)
    stale = _bundle(2, bundle_suffix="b", image_suffix_start=3)
    stale_context = _build(stale).context
    stale_result = subject.resolve_image_reference(
        _parsing().parse_image_reference("第一张"),
        bundle=current,
        context=stale_context,
    )

    foreign_context = stale_context.model_copy(
        update={"bundle_id": current.bundle_id},
        deep=True,
    )
    foreign_result = subject.resolve_image_reference(
        _parsing().parse_image_reference("第一张"),
        bundle=current,
        context=foreign_context,
    )

    assert stale_result.kind == "error"
    assert stale_result.code == "stale_bundle_context"
    assert stale_result.image_id is None
    assert foreign_result.kind == "error"
    assert foreign_result.code == "identity_record_bundle_mismatch"
    assert foreign_result.image_id is None
