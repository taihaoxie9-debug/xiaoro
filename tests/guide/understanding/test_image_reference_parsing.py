from __future__ import annotations

import importlib

import pytest


def _subject():
    try:
        return importlib.import_module(
            "app.guide.understanding.image_reference_parsing"
        )
    except ModuleNotFoundError:
        pytest.fail("image reference parsing module is missing")


@pytest.mark.parametrize(
    ("message", "ordinal"),
    [
        ("第一张", 1),
        ("看看第二张", 2),
        ("第 三 张适合我吗", 3),
        ("我说的是第四张图片", 4),
    ],
)
def test_parses_supported_chinese_image_ordinals(
    message: str,
    ordinal: int,
) -> None:
    draft = _subject().parse_image_reference(message)

    assert draft is not None
    assert draft.ordinal == ordinal
    assert draft.issue is None


def test_multiple_distinct_image_ordinals_are_ambiguous() -> None:
    draft = _subject().parse_image_reference("第一张和第二张")

    assert draft is not None
    assert draft.ordinal is None
    assert draft.issue == "ambiguous_image_reference"


@pytest.mark.parametrize("message", ["第二款", "这张", "第六张"])
def test_does_not_claim_unsupported_or_product_references(
    message: str,
) -> None:
    assert _subject().parse_image_reference(message) is None
