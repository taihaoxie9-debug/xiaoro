from __future__ import annotations

import logging
from typing import Protocol

from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.understanding.contracts import StructuredUnderstanding
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.text_understanding import (
    ExactOnlyTextUnderstanding,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


logger = logging.getLogger(__name__)


class TurnMeaningPort(Protocol):
    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> TurnMeaning: ...


class SingleCallUnderstanding:
    def __init__(
        self,
        *,
        semantic: TurnMeaningPort,
        concept_catalog: ConceptPreferenceCatalog,
    ) -> None:
        if not isinstance(
            concept_catalog,
            ConceptPreferenceCatalog,
        ):
            raise TypeError(
                "concept_catalog must be ConceptPreferenceCatalog"
            )
        self._semantic = semantic
        self._concept_catalog = concept_catalog
        self._exact_only = ExactOnlyTextUnderstanding()

    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        text = message.strip()
        if not 1 <= len(text) <= 4000:
            raise ValueError("message length must be between 1 and 4000")
        if not isinstance(context, SemanticContext):
            raise TypeError("context must be a SemanticContext")
        if not isinstance(semantic_required, bool):
            raise TypeError("semantic_required must be a bool")

        if not semantic_required:
            return self._exact_only.understand(
                text,
                context=context,
                semantic_required=False,
            )

        return self.translate(text, context=context)[1]

    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> tuple[TurnMeaning, StructuredUnderstanding]:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        text = message.strip()
        if not 1 <= len(text) <= 4000:
            raise ValueError("message length must be between 1 and 4000")
        if not isinstance(context, SemanticContext):
            raise TypeError("context must be a SemanticContext")
        try:
            meaning = self._semantic.propose(text, context)
        except Exception:
            logger.warning(
                "Guide turn meaning lane unavailable; "
                "continuing with exact lane only"
            )
            exact = self._exact_only.understand(
                text,
                context=context,
                semantic_required=True,
            )
            return _fallback_meaning(exact, text=text), exact

        return (
            meaning,
            compile_turn_meaning(
                message=text,
                meaning=meaning,
                context=context,
                concept_catalog=self._concept_catalog,
            ),
        )


def _fallback_meaning(
    understanding: StructuredUnderstanding,
    *,
    text: str,
) -> TurnMeaning:
    return TurnMeaning(
        operation_hint=understanding.goal.value,
        topic_hint=(
            understanding.topic.value
            if understanding.topic is not None
            else None
        ),
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
        safety_language=(
            "safety"
            if understanding.safety_sensitive
            else "unknown"
        ),
    )


__all__ = ["SingleCallUnderstanding", "TurnMeaningPort"]
