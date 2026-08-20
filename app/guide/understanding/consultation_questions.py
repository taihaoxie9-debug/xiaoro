from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


ObservationCode = Literal[
    "post_cleanse_tightness",
    "t_zone_oiliness",
    "recurrent_redness",
    "stinging",
    "flaking",
    "location",
    "persistence_or_trigger",
    "ordinary_product_tolerance",
    "active_damage_risk",
    "confirmation",
]
ObservationAnswer = Literal["yes", "no", "sometimes", "unknown"]


class ConsultationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code: ObservationCode
    prompt: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=160,
        ),
    ]
    accepted_answers: tuple[
        Literal["yes"],
        Literal["no"],
        Literal["sometimes"],
        Literal["unknown"],
    ] = ("yes", "no", "sometimes", "unknown")


_QUESTIONS = (
    ConsultationQuestion(
        code="post_cleanse_tightness",
        prompt="洁面后不涂护肤品时，皮肤会紧绷吗？",
    ),
    ConsultationQuestion(
        code="t_zone_oiliness",
        prompt="到中午或下午，额头和鼻子（T 区）会明显出油吗？",
    ),
    ConsultationQuestion(
        code="recurrent_redness",
        prompt="皮肤是否会反复泛红？",
    ),
    ConsultationQuestion(
        code="stinging",
        prompt="使用基础护肤品时，皮肤是否会刺痛？",
    ),
    ConsultationQuestion(
        code="flaking",
        prompt="皮肤是否会脱屑或起皮？",
    ),
)


def observable_questions() -> tuple[ConsultationQuestion, ...]:
    return _QUESTIONS
