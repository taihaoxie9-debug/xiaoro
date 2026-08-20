from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.product_evidence_assets import SubjectScope


SelectionCapability = Literal[
    "compare",
    "soft_rank",
    "hard_filter",
    "safety_gate",
]
SelectionSafetyRole = Literal[
    "ordinary",
    "merchant_positive_safety",
    "verified_warning",
]
SelectionAttribution = Literal[
    "verified_fact",
    "merchant_claim",
    "consumer_report",
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SelectionFact(_StrictFrozenModel):
    product_id: int = Field(gt=0)
    category_profile: CategoryProfile
    subject_scope: SubjectScope
    variant_scope: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    normalized_value: str = Field(min_length=1, max_length=512)
    rank_strength: Literal[1, 2] | None = None
    safety_role: SelectionSafetyRole = "ordinary"
    capabilities: frozenset[SelectionCapability] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    attributions: frozenset[SelectionAttribution] = Field(min_length=1)

    @field_validator("category_profile", mode="before")
    @classmethod
    def parse_category_profile(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return CategoryProfile(value)
            except ValueError:
                return value
        return value

    @field_validator("capabilities", "attributions", mode="before")
    @classmethod
    def freeze_capabilities(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @field_validator("source_refs", mode="before")
    @classmethod
    def freeze_source_refs(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_selection_fact(self) -> Self:
        if self.subject_scope == "exact_variant" and self.variant_scope is None:
            raise ValueError("exact variant selection requires variant scope")
        if self.normalized_value != self.normalized_value.strip():
            raise ValueError("normalized selection value must be trimmed")
        if self.source_refs != tuple(sorted(set(self.source_refs))):
            raise ValueError(
                "selection source references must be sorted and unique"
            )
        if any(
            not value or value != value.strip()
            for value in self.source_refs
        ):
            raise ValueError(
                "selection source references must be nonempty"
            )
        if "soft_rank" in self.capabilities:
            if self.rank_strength is None:
                raise ValueError("soft rank requires rank strength")
        elif self.rank_strength is not None:
            raise ValueError("rank strength requires soft rank")
        if (
            self.safety_role == "merchant_positive_safety"
            and self.rank_strength == 2
        ):
            raise ValueError(
                "merchant positive safety evidence is weak only"
            )
        definitions = {
            definition.key: definition
            for definition in category_field_registry().definitions
        }
        definition = definitions.get(self.field_key)
        if definition is None:
            raise ValueError("unknown selection field")
        if self.category_profile not in definition.profiles:
            raise ValueError(
                "selection field is not applicable to category profile"
            )
        return self

    @property
    def selection_key(self) -> tuple[object, ...]:
        return (
            self.product_id,
            self.subject_scope,
            self.variant_scope,
            self.field_key,
            self.normalized_value.casefold(),
        )


def merge_selection_facts(
    facts: Iterable[SelectionFact],
) -> tuple[SelectionFact, ...]:
    merged: dict[tuple[object, ...], SelectionFact] = {}
    for item in facts:
        if not isinstance(item, SelectionFact):
            raise TypeError("selection facts must be SelectionFact instances")
        previous = merged.get(item.selection_key)
        if previous is None:
            merged[item.selection_key] = item
            continue
        if previous.category_profile is not item.category_profile:
            raise ValueError("duplicate selection fact profile mismatch")
        strengths = tuple(
            value
            for value in (previous.rank_strength, item.rank_strength)
            if value is not None
        )
        roles = {previous.safety_role, item.safety_role}
        safety_role: SelectionSafetyRole = (
            "verified_warning"
            if "verified_warning" in roles
            else (
                "ordinary"
                if "ordinary" in roles
                else "merchant_positive_safety"
            )
        )
        merged[item.selection_key] = previous.model_copy(
            update={
                "rank_strength": max(strengths) if strengths else None,
                "safety_role": safety_role,
                "capabilities": (
                    previous.capabilities | item.capabilities
                ),
                "source_refs": tuple(
                    sorted(
                        {
                            *previous.source_refs,
                            *item.source_refs,
                        }
                    )
                ),
                "attributions": (
                    previous.attributions | item.attributions
                ),
            },
            deep=True,
        )
    return tuple(
        sorted(
            merged.values(),
            key=lambda item: (
                item.product_id,
                item.subject_scope,
                item.variant_scope or "",
                item.field_key,
                item.normalized_value.casefold(),
            ),
        )
    )


__all__ = [
    "SelectionCapability",
    "SelectionAttribution",
    "SelectionFact",
    "SelectionSafetyRole",
    "merge_selection_facts",
]
