from __future__ import annotations

from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptProjection,
)
from app.guide.understanding.contracts import PreferenceDraft
from app.guide.understanding.source_grounding import ground_unique_text
from app.guide.understanding.turn_meaning_contracts import (
    TurnPreferenceCandidate,
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ConceptCatalogEntry(_StrictFrozenModel):
    profile: CategoryProfile
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    concept_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$"
    )
    source_values: tuple[str, ...] = ()

    @field_validator("source_values", mode="before")
    @classmethod
    def freeze_source_values(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_entry(self) -> Self:
        if not self.concept_id.startswith(f"{self.field_key}."):
            raise ValueError("catalog concept must be field-scoped")
        definitions = {
            definition.key: definition
            for definition in category_field_registry().definitions
        }
        definition = definitions.get(self.field_key)
        if (
            definition is None
            or self.profile not in definition.profiles
        ):
            raise ValueError(
                "catalog field is not applicable to profile"
            )
        if (
            any(
                not value
                or value != value.strip()
                for value in self.source_values
            )
            or self.source_values
            != tuple(sorted(set(self.source_values), key=str.casefold))
        ):
            raise ValueError(
                "catalog source values must be trimmed, sorted, and unique"
            )
        return self


class ConceptPreferenceCatalog(_StrictFrozenModel):
    entries: tuple[ConceptCatalogEntry, ...] = Field(min_length=1)

    @field_validator("entries", mode="before")
    @classmethod
    def freeze_entries(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_entries(self) -> Self:
        keys = tuple(
            (
                item.profile.value,
                item.field_key,
                item.concept_id,
            )
            for item in self.entries
        )
        if keys != tuple(sorted(set(keys))):
            raise ValueError(
                "concept catalog entries must be sorted and unique"
            )
        return self

    @classmethod
    def from_projections(
        cls,
        projections: Sequence[SelectionConceptProjection],
    ) -> ConceptPreferenceCatalog:
        entries: dict[
            tuple[CategoryProfile, str, str],
            set[str],
        ] = {}
        for item in projections:
            key = (
                item.profile,
                item.field_key,
                item.concept_id,
            )
            entries.setdefault(key, set()).add(
                item.normalized_value
            )
        return cls(
            entries=tuple(
                ConceptCatalogEntry(
                    profile=profile,
                    field_key=field_key,
                    concept_id=concept_id,
                    source_values=tuple(
                        sorted(
                            entries[
                                (profile, field_key, concept_id)
                            ],
                            key=str.casefold,
                        )
                    ),
                )
                for profile, field_key, concept_id in sorted(
                    entries,
                    key=lambda item: (
                        item[0].value,
                        item[1],
                        item[2],
                    ),
                )
            )
        )

    def admits(
        self,
        *,
        profile: CategoryProfile,
        field_key: str,
        concept_id: str,
    ) -> bool:
        return any(
            item.profile is profile
            and item.field_key == field_key
            and item.concept_id == concept_id
            for item in self.entries
        )

    def resolve_source_value(
        self,
        *,
        profile: CategoryProfile,
        field_key: str,
        raw_text: str,
    ) -> str | None:
        if not isinstance(profile, CategoryProfile):
            raise TypeError("profile must be a CategoryProfile")
        if not isinstance(field_key, str) or not field_key:
            raise ValueError("field_key must be nonempty")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ValueError("raw_text must be nonempty")
        normalized = raw_text.strip().casefold()
        matches = {
            item.concept_id
            for item in self.entries
            if (
                item.profile is profile
                and item.field_key == field_key
                and normalized
                in {
                    value.casefold()
                    for value in item.source_values
                }
            )
        }
        return next(iter(matches)) if len(matches) == 1 else None


def compile_concept_preferences(
    *,
    message: str,
    candidates: Sequence[TurnPreferenceCandidate],
    profile: CategoryProfile,
    catalog: ConceptPreferenceCatalog,
) -> tuple[PreferenceDraft, ...]:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be nonempty")
    if isinstance(candidates, (str, bytes)) or not isinstance(
        candidates,
        Sequence,
    ):
        raise TypeError(
            "candidates must be TurnPreferenceCandidate instances"
        )
    if not isinstance(profile, CategoryProfile):
        raise TypeError("profile must be CategoryProfile")
    if not isinstance(catalog, ConceptPreferenceCatalog):
        raise TypeError(
            "catalog must be ConceptPreferenceCatalog"
        )

    unique: dict[tuple[str, str, str, str], PreferenceDraft] = {}
    for candidate in candidates:
        if not isinstance(candidate, TurnPreferenceCandidate):
            raise TypeError(
                "candidates must be TurnPreferenceCandidate instances"
            )
        ground_unique_text(message, candidate.raw_text)
        if candidate.strength != "ordinary":
            continue
        resolved_concept_id = catalog.resolve_source_value(
            profile=profile,
            field_key=candidate.field_key,
            raw_text=candidate.raw_text,
        )
        concept_id = resolved_concept_id or candidate.concept_id
        if (
            concept_id is not None
            and catalog.admits(
                profile=profile,
                field_key=candidate.field_key,
                concept_id=concept_id,
            )
        ):
            key = (
                "concept",
                candidate.field_key,
                concept_id,
                candidate.polarity,
            )
            unique.setdefault(
                key,
                PreferenceDraft(
                    field_key=candidate.field_key,
                    value=candidate.raw_text,
                    preference_kind="concept",
                    concept_id=concept_id,
                    polarity=candidate.polarity,
                ),
            )
            continue
        key = (
            "free_descriptor",
            candidate.field_key,
            candidate.raw_text.casefold(),
            candidate.polarity,
        )
        unique.setdefault(
            key,
            PreferenceDraft(
                field_key=candidate.field_key,
                value=candidate.raw_text,
                preference_kind="free_descriptor",
                polarity=candidate.polarity,
            ),
        )
    return tuple(unique.values())


__all__ = [
    "ConceptCatalogEntry",
    "ConceptPreferenceCatalog",
    "compile_concept_preferences",
]
