from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


class ScenarioCode(str, Enum):
    COMMUTE = "commute"
    TRAVEL = "travel"
    OUTDOOR = "outdoor"
    REPAIR = "repair"
    SENSITIVE_PERIOD = "sensitive_period"


class ScenarioObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scenario: ScenarioCode
    source: Literal["user_explicit"] = "user_explicit"
    matched_text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
    ]


_ALIASES: dict[ScenarioCode, tuple[str, ...]] = {
    ScenarioCode.COMMUTE: (
        "日常通勤",
        "上下班通勤",
        "上班路上",
        "通勤",
    ),
    ScenarioCode.TRAVEL: (
        "出差旅行",
        "出门旅行",
        "旅行",
        "旅游",
        "出差",
        "出游",
    ),
    ScenarioCode.OUTDOOR: (
        "长时间户外",
        "户外运动",
        "户外",
        "露营",
        "徒步",
        "海边",
    ),
    ScenarioCode.REPAIR: (
        "屏障受损",
        "修护阶段",
        "修护期",
        "正在修护",
        "修护",
    ),
    ScenarioCode.SENSITIVE_PERIOD: (
        "皮肤状态不稳定",
        "敏感期",
        "反复泛红刺痛",
    ),
}


def parse_scenarios(message: str) -> list[ScenarioObservation]:
    text = message.strip()
    if not text:
        return []

    observations: list[ScenarioObservation] = []
    for scenario in ScenarioCode:
        matched_text = next(
            (
                alias
                for alias in _ALIASES[scenario]
                if alias in text
            ),
            None,
        )
        if matched_text is not None:
            observations.append(
                ScenarioObservation(
                    scenario=scenario,
                    matched_text=matched_text,
                )
            )
    return observations
