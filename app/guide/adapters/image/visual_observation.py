from app.guide.adapters.image.index_runtime import (
    ImageRetrievalUnavailableError,
)
from app.guide.adapters.image.openclip_adapter import OpenClipModelError
from app.guide.retrieval.image_contracts import ImageRetrievalRequest
from app.guide.retrieval.ports import ImageRetrievalPort
from app.guide.understanding.image_contracts import (
    VisualCandidateObservation,
    VisualObservationState,
)


class ImageRetrievalVisualObservationAdapter:
    def __init__(self, *, retrieval: ImageRetrievalPort) -> None:
        self._retrieval = retrieval

    def observe(
        self,
        request: ImageRetrievalRequest,
    ) -> VisualCandidateObservation:
        try:
            result = self._retrieval.retrieve(request)
        except (ImageRetrievalUnavailableError, OpenClipModelError):
            return VisualCandidateObservation(
                state=VisualObservationState.UNAVAILABLE,
                result=None,
            )
        return VisualCandidateObservation(
            state=VisualObservationState.OBSERVED,
            result=result,
        )
