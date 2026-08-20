from __future__ import annotations

import pytest


def scenario_api():
    from app.guide.understanding.scenario_parsing import (
        ScenarioCode,
        parse_scenarios,
    )

    return ScenarioCode, parse_scenarios


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("每天通勤想找一款防晒", "commute"),
        ("下周出差旅行带什么精华", "travel"),
        ("周末长时间户外徒步用什么防晒", "outdoor"),
        ("最近屏障受损，正在修护", "repair"),
        ("这几天处于敏感期", "sensitive_period"),
    ],
)
def test_natural_language_maps_to_fixed_scenario_enum(
    message: str,
    expected: str,
) -> None:
    ScenarioCode, parse_scenarios = scenario_api()

    observations = parse_scenarios(message)

    assert [item.scenario for item in observations] == [
        ScenarioCode(expected)
    ]
    assert observations[0].source == "user_explicit"
    assert observations[0].matched_text in message


def test_multiple_scenarios_are_deduplicated_in_enum_order() -> None:
    ScenarioCode, parse_scenarios = scenario_api()

    observations = parse_scenarios(
        "敏感期准备旅行，旅行期间还会长时间户外徒步"
    )

    assert [item.scenario for item in observations] == [
        ScenarioCode.TRAVEL,
        ScenarioCode.OUTDOOR,
        ScenarioCode.SENSITIVE_PERIOD,
    ]


def test_non_scenario_language_does_not_invent_a_scenario() -> None:
    _, parse_scenarios = scenario_api()

    assert parse_scenarios("500 元内干性肌肤的防晒") == []


def test_scenario_enum_is_closed_to_the_five_supported_values() -> None:
    ScenarioCode, _ = scenario_api()

    assert {item.value for item in ScenarioCode} == {
        "commute",
        "travel",
        "outdoor",
        "repair",
        "sensitive_period",
    }
