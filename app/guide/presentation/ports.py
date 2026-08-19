from typing import Protocol

from app.guide.presentation.contracts import ProductCardFacts


class PresentationFactPort(Protocol):
    def get_presentation_facts(
        self,
        product_id: int,
        *,
        variant_scope: str | None = None,
    ) -> ProductCardFacts: ...
