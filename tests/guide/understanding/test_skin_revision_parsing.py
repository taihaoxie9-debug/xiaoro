from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.understanding.contracts import (
    SkinRevisionDraft,
    SkinTarget,
)
from app.guide.understanding.skin_revision_parsing import (
    parse_skin_revision,
)


@pytest.mark.parametrize(
    ("message", "target"),
    [
        ("改成油敏肌呢", SkinTarget.OILY_SENSITIVE),
        ("改成油敏", SkinTarget.OILY_SENSITIVE),
        ("改成敏感肌呢", SkinTarget.SENSITIVE),
        ("换成敏感性肤质", SkinTarget.SENSITIVE),
        ("改为敏皮", SkinTarget.SENSITIVE),
        ("按混合肌重新看", SkinTarget.COMBINATION),
        ("改成混合", SkinTarget.COMBINATION),
        ("改为中性肌", SkinTarget.NORMAL),
        ("换成中性", SkinTarget.NORMAL),
        ("换成油皮", SkinTarget.OILY),
        ("改成油性", SkinTarget.OILY),
        ("那干皮呢", SkinTarget.DRY),
        ("按干性重新看", SkinTarget.DRY),
    ],
)
def test_parses_only_explicit_skin_revision_aliases(
    message: str,
    target: SkinTarget,
) -> None:
    draft = parse_skin_revision(message)

    assert draft is not None
    assert draft.target is target
    assert draft.issue is None


def test_longest_skin_alias_wins() -> None:
    draft = parse_skin_revision("改成油敏肌呢")

    assert draft is not None
    assert draft.target is SkinTarget.OILY_SENSITIVE


@pytest.mark.parametrize(
    ("message", "target"),
    [
        ("从敏感肌换成油皮", SkinTarget.OILY),
        ("从油皮改成敏感肌", SkinTarget.SENSITIVE),
        ("从油皮换成油敏肌", SkinTarget.OILY_SENSITIVE),
        ("从油敏肌改成油皮", SkinTarget.OILY),
    ],
)
def test_source_and_target_skin_revision_uses_the_new_target(
    message: str,
    target: SkinTarget,
) -> None:
    draft = parse_skin_revision(message)

    assert draft is not None
    assert draft.target is target
    assert draft.issue is None


@pytest.mark.parametrize(
    "message",
    [
        "换个肤质",
        "换成适合我的肤质",
    ],
)
def test_ambiguous_skin_revision_is_not_pre_routed(
    message: str,
) -> None:
    assert parse_skin_revision(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "我最近有点敏感",
        "那敏感呢",
        "最近泛红",
        "最近出油",
        "最近有点干",
    ],
)
def test_temporary_symptoms_do_not_infer_skin_revision(
    message: str,
) -> None:
    assert parse_skin_revision(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "那第二款呢",
        "那这个呢",
        "那敏感肌适合用什么呢",
        "那敏感肌应该怎么选呢",
    ],
)
def test_general_ne_followup_is_not_a_skin_revision(
    message: str,
) -> None:
    assert parse_skin_revision(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "预算改成300元，肤质改成敏感肌",
        "改成100元以内的油皮",
        "肤质改成油敏肌后它还适合吗",
        "肤质改成油敏肌后呢",
    ],
)
def test_compound_or_open_skin_revision_is_not_pre_routed(
    message: str,
) -> None:
    assert parse_skin_revision(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "改成敏感肌的修护精华",
        "换成油皮防晒",
        "预算改成300元，肤质改成敏感肌的修护精华",
    ],
)
def test_complete_category_query_wins_over_skin_revision(
    message: str,
) -> None:
    assert parse_skin_revision(message) is None


def test_skin_description_without_revision_signal_is_not_revision() -> None:
    assert parse_skin_revision("我是敏感肌") is None


def test_skin_revision_draft_forbids_target_with_issue() -> None:
    with pytest.raises(ValidationError, match="target"):
        SkinRevisionDraft(
            target=SkinTarget.SENSITIVE,
            issue="unsupported_skin_revision",
        )
