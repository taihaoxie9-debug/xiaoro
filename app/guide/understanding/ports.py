from typing import Protocol

from app.guide.retrieval.image_contracts import ImageRetrievalRequest
from app.guide.understanding.contracts import StructuredUnderstanding
from app.guide.understanding.image_contracts import (
    CanonicalIdentity,
    OcrIdentityTrace,
    OcrIdentityObservation,
    VisualCandidateObservation,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


class SemanticIntentPort(Protocol):
    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal: ...


class TextUnderstandingPort(Protocol):
    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding: ...


class UnifiedUnderstandingPort(Protocol):
    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> TurnMeaning: ...


class VisualObservationPort(Protocol):
    def observe(
        self,
        request: ImageRetrievalRequest,
    ) -> VisualCandidateObservation: ...


class OcrObservationPort(Protocol):
    def observe(
        self,
        request: ImageRetrievalRequest,
        canonical_identity: CanonicalIdentity,
    ) -> OcrIdentityObservation: ...

    def observe_with_trace(
        self,
        request: ImageRetrievalRequest,
        canonical_identity: CanonicalIdentity,
    ) -> tuple[OcrIdentityObservation, OcrIdentityTrace]: ...


class CanonicalIdentityCatalogPort(Protocol):
    @property
    def product_ids(self) -> frozenset[int]: ...

    def get_identity(
        self,
        product_id: int,
    ) -> CanonicalIdentity | None: ...
