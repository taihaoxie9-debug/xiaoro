from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)
from app.guide.understanding.consultation_questions import (
    ConsultationQuestion,
    observable_questions,
)
from app.guide.understanding.contracts import SkinTarget


class ConsultationCollectionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    mode: Literal["consultation_collection"] = "consultation_collection"
    next_question: ConsultationQuestion | None


def plan_unknown_skin_consultation(
    *,
    skin_target: SkinTarget | None,
    observations: Sequence[ConsultationObservation],
) -> ConsultationCollectionPlan | None:
    if skin_target is not None:
        return None
    return plan_consultation_collection(observations)


def plan_consultation_collection(
    observations: Sequence[ConsultationObservation],
) -> ConsultationCollectionPlan:
    questions = observable_questions()
    actual_codes = tuple(item.code for item in observations)
    expected_codes = tuple(
        question.code for question in questions[: len(actual_codes)]
    )
    if actual_codes != expected_codes:
        raise ValueError(
            "consultation observations must follow question order"
        )
    if len(observations) > len(questions):
        raise ValueError("consultation has too many observations")
    next_question = (
        questions[len(observations)]
        if len(observations) < len(questions)
        else None
    )
    return ConsultationCollectionPlan(next_question=next_question)
