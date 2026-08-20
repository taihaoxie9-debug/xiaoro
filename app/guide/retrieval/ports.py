from collections.abc import Iterable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.image_contracts import (
    ImageRetrievalRequest,
    ImageRetrievalResult,
)
from app.guide.retrieval.scenario_contracts import (
    ScenarioEvidenceRecord,
    ScenarioEvidenceRequirement,
)


class CategoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    product_id: int
    value: str | None
    state: Literal["known", "unknown", "conflict", "not_applicable"]


class CategoryCatalogPort(Protocol):
    def iter_category_records(self) -> Iterable[CategoryRecord]: ...


class CategoryFactPort(Protocol):
    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[AuthorizedCategoryFact, ...]: ...


class ScenarioEvidencePort(Protocol):
    def get_scenario_evidence(
        self,
        product_id: int,
        requirements: list[ScenarioEvidenceRequirement],
    ) -> list[ScenarioEvidenceRecord]: ...


class ImageRetrievalPort(Protocol):
    def retrieve(
        self,
        request: ImageRetrievalRequest,
    ) -> ImageRetrievalResult: ...
