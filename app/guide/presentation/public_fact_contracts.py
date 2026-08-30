from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )


class ProjectedPublicFact(_StrictFrozen):
    fact_id: str = Field(min_length=1, max_length=160)
    product_id: int = Field(gt=0)
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str = Field(min_length=1, max_length=64)
    display_value: str = Field(min_length=1, max_length=512)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=8)
    source_kind: Literal[
        "category",
        "evidence",
        "merchant",
        "review",
    ]
    attribution: Literal[
        "verified_fact",
        "merchant_claim",
        "consumer_report",
    ]

    @field_validator("source_refs", mode="before")
    @classmethod
    def freeze_source_refs(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_source_refs(self) -> Self:
        if self.source_refs != tuple(dict.fromkeys(self.source_refs)):
            raise ValueError(
                "projected public fact source refs must be unique"
            )
        return self


class ProductPublicFactProjection(_StrictFrozen):
    product_id: int = Field(gt=0)
    facts: tuple[ProjectedPublicFact, ...] = Field(
        default_factory=tuple,
        max_length=128,
    )

    @field_validator("facts", mode="before")
    @classmethod
    def freeze_facts(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_facts(self) -> Self:
        if any(
            fact.product_id != self.product_id
            for fact in self.facts
        ):
            raise ValueError(
                "projected public facts must belong to projection product"
            )
        fact_ids = tuple(fact.fact_id for fact in self.facts)
        if fact_ids != tuple(dict.fromkeys(fact_ids)):
            raise ValueError("projected public fact IDs must be unique")
        return self


__all__ = [
    "ProductPublicFactProjection",
    "ProjectedPublicFact",
]
