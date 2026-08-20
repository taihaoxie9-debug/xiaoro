from decimal import Decimal

import pytest

from app.guide.understanding.budget_revision_parsing import (
    parse_budget_revision,
)


@pytest.mark.parametrize(
    "message",
    [
        "预算降到100元呢",
        "预算改成 100 元",
        "改成100元以内",
        "控制在 100 块以内",
    ],
)
def test_parses_explicit_budget_maximum_revision(message: str) -> None:
    draft = parse_budget_revision(message)

    assert draft is not None
    assert draft.maximum == Decimal("100")
    assert draft.issue is None


@pytest.mark.parametrize(
    ("message", "maximum"),
    (
        ("预算改成三百以内", Decimal("300")),
        ("预算降到两百五十元呢", Decimal("250")),
    ),
)
def test_parses_clear_chinese_budget_revision(
    message: str,
    maximum: Decimal,
) -> None:
    draft = parse_budget_revision(message)

    assert draft is not None
    assert draft.maximum == maximum
    assert draft.issue is None


@pytest.mark.parametrize(
    ("message", "issue"),
    [
        ("预算改成0元", "invalid_budget"),
        ("预算改成-1元", "invalid_budget"),
        ("预算改成100到200元", None),
        ("预算改成100", None),
        ("预算改成三百以内，而且还是不要含酒精的呢", None),
        ("便宜一点", None),
        ("100元呢", None),
    ],
)
def test_only_message_bound_budget_revisions_are_pre_routed(
    message: str,
    issue: str | None,
) -> None:
    draft = parse_budget_revision(message)

    if issue is None:
        assert draft is None
    else:
        assert draft is not None
        assert draft.maximum is None
        assert draft.issue == issue


def test_explicit_category_query_wins_over_revision_parser() -> None:
    assert parse_budget_revision(
        "预算改成100元的修护精华"
    ) is None
    assert parse_budget_revision(
        "预算改成100元的防晒"
    ) is None


def test_candidate_followups_are_not_budget_revisions() -> None:
    assert parse_budget_revision("第二款呢") is None
    assert parse_budget_revision("哪个更便宜") is None
