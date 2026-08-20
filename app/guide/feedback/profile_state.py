from __future__ import annotations

from enum import Enum
from typing import Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
    ProfileOwnerRef,
)


class ProfileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    owner: ProfileOwnerRef
    version: int = Field(ge=1)
    facts: tuple[ConfirmedProfileFact, ...] = Field(
        min_length=1,
        max_length=5,
    )

    @field_validator("facts", mode="before")
    @classmethod
    def freeze_facts(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_facts(self) -> Self:
        fields = [fact.field for fact in self.facts]
        if len(fields) != len(set(fields)):
            raise ValueError("profile facts must have unique fields")
        if any(fact.owner != self.owner for fact in self.facts):
            raise ValueError("profile facts must share the snapshot owner")
        if any(
            fact.profile_version > self.version for fact in self.facts
        ):
            raise ValueError(
                "profile fact version cannot exceed profile version"
            )
        if not any(
            fact.profile_version == self.version for fact in self.facts
        ):
            raise ValueError(
                "profile version must be represented by a fact"
            )
        return self


class ProfileStateConflict(RuntimeError):
    pass


class ProfileStateCorrupt(RuntimeError):
    pass


class ProfileWriteDisposition(str, Enum):
    CREATED = "created"
    IDEMPOTENT = "idempotent"
    CONFLICT = "conflict"


class ProfileWriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    disposition: ProfileWriteDisposition
    snapshot: ProfileSnapshot
    stored_fact: ConfirmedProfileFact

    @model_validator(mode="after")
    def validate_stored_fact(self) -> Self:
        if self.stored_fact.owner != self.snapshot.owner:
            raise ValueError("stored fact must share the snapshot owner")
        if self.stored_fact not in self.snapshot.facts:
            raise ValueError("stored fact must belong to the snapshot")
        return self


class ProfileStatePort(Protocol):
    def load(self, owner: ProfileOwnerRef) -> ProfileSnapshot | None: ...

    def write_once(
        self,
        fact: ConfirmedProfileFact,
        *,
        expected_version: int,
    ) -> ProfileWriteResult: ...

    def save(
        self,
        fact: ConfirmedProfileFact,
        *,
        expected_version: int,
    ) -> ProfileSnapshot: ...
