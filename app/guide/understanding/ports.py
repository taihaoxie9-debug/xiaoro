from typing import Protocol

from app.guide.retrieval.image_contracts import ImageRetrievalRequest
from app.guide.understanding.contracts import StructuredUnderstanding
from app.guide.understanding.image_contracts import (
    CanonicalIdentity,
    OcrIdentityObservation,
    VisualCandidateObservation,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
)
from app.guide.understanding.semantic_detail_contracts import (
    SemanticDetailsProposal,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticRouteProposal,
)


class SemanticIntentPort(Protocol):
    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal: ...


class SemanticRoutePort(Protocol):
    def route(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticRouteProposal: ...


class SemanticDetailsPort(Protocol):
    def extract(
        self,
        message: str,
        context: SemanticContext,
        route: SemanticRouteProposal,
    ) -> SemanticDetailsProposal: ...


class TextUnderstandingPort(Protocol):
    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding: ...


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


class CanonicalIdentityCatalogPort(Protocol):
    @property
    def product_ids(self) -> frozenset[int]: ...

    def get_identity(
        self,
        product_id: int,
    ) -> CanonicalIdentity | None: ...
