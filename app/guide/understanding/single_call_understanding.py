from __future__ import annotations

import logging
from typing import Protocol

from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.text_understanding import (
    exact_fallback_turn_meaning,
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

    @property
    def concept_catalog(self) -> ConceptPreferenceCatalog:
        return self._concept_catalog

    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> TurnMeaning:
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
            return exact_fallback_turn_meaning(text)
        if type(meaning) is not TurnMeaning:
            raise TypeError("semantic provider must return TurnMeaning")
        return meaning

__all__ = ["SingleCallUnderstanding", "TurnMeaningPort"]
