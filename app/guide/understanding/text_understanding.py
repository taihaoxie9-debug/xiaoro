"""Slice 1 文本理解层：把自然语言拆成结构化理解草稿。

原则：数字、品类、肤质、否定由代码精确抽取，进 exact_constraints；
模糊偏好进 semantic_proposals。不发明商品事实、不排序、不判 winner。
"""
from __future__ import annotations

from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


class ExactOnlyTextUnderstanding:
    """Fail-closed TurnMeaning provider used without an LLM."""

    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> TurnMeaning:
        if not isinstance(context, SemanticContext):
            raise TypeError("context must be a SemanticContext")
        return exact_fallback_turn_meaning(message)


def exact_fallback_turn_meaning(message: str) -> TurnMeaning:
    if not isinstance(message, str):
        raise TypeError("message must be a string")
    text = message.strip()
    if not 1 <= len(text) <= 4000:
        raise ValueError("message length must be between 1 and 4000")
    return TurnMeaning(
        operation_hint="clarification",
        topic_hint=None,
        continuity_hint="unknown",
        subject_scope_hint="unknown",
        reference_mentions=(),
        product_mentions=(),
        budget_candidates=(),
        observation_candidates=(),
        preference_candidates=(),
        relative_candidates=(),
        consultation_hypothesis=None,
        next_observation_gap=None,
        question_meaning=text,
        safety_language="unknown",
    )


__all__ = [
    "ExactOnlyTextUnderstanding",
    "exact_fallback_turn_meaning",
]
