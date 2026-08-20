from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Literal, Self
import unicodedata

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.understanding.ports import CanonicalIdentityCatalogPort


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ControlledProductAliasRecord(_StrictFrozen):
    alias: str = Field(min_length=2, max_length=80)
    identity_scope: Literal[
        "exact_product",
        "exact_variant",
        "ambiguous_family",
    ]
    product_ids: tuple[int, ...] = Field(
        min_length=1,
        max_length=8,
    )
    default_product_id: int | None = Field(default=None, gt=0)
    variant_scope: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    clarify_terms: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    source_refs: tuple[str, ...] = Field(
        min_length=1,
        max_length=8,
    )
    review_status: str = Field(pattern=r"^approved$")
    review_rationale: str = Field(min_length=1, max_length=512)

    @field_validator(
        "product_ids",
        "clarify_terms",
        "source_refs",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if self.alias != self.alias.strip():
            raise ValueError("controlled alias must be trimmed")
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError(
                "controlled alias product IDs must be unique"
            )
        if self.identity_scope == "ambiguous_family":
            if (
                self.default_product_id is not None
                or self.variant_scope is not None
                or len(self.product_ids) < 2
                or self.clarify_terms
            ):
                raise ValueError(
                    "ambiguous family aliases require multiple products "
                    "without a default, variant, or contextual terms"
                )
        elif self.default_product_id not in self.product_ids:
            raise ValueError(
                "exact aliases require a default listed in product IDs"
            )
        elif self.identity_scope == "exact_variant":
            if len(self.product_ids) != 1 or self.variant_scope is None:
                raise ValueError(
                    "exact variant aliases require one product and scope"
                )
        elif self.variant_scope is not None:
            raise ValueError(
                "exact product aliases forbid variant scope"
            )
        if any(
            term != term.strip() or not term
            for term in self.clarify_terms
        ):
            raise ValueError("controlled alias clarify terms must be trimmed")
        if len(self.clarify_terms) != len(set(self.clarify_terms)):
            raise ValueError("controlled alias clarify terms must be unique")
        if any(
            len(source_ref) != 64
            or any(character not in "0123456789abcdef" for character in source_ref)
            for source_ref in self.source_refs
        ):
            raise ValueError("controlled alias source refs must be SHA256 IDs")
        return self


class ControlledProductAliasManifest(_StrictFrozen):
    schema_version: str = Field(
        pattern=r"^guide-controlled-product-aliases-v1$"
    )
    aliases_file: str = Field(
        pattern=r"^controlled_product_aliases_v1\.jsonl$"
    )
    aliases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(gt=0)


class ControlledProductAliasRegistry:
    def __init__(
        self,
        records: tuple[ControlledProductAliasRecord, ...],
    ) -> None:
        if not records:
            raise ValueError("controlled alias registry must not be empty")
        by_alias: dict[str, ControlledProductAliasRecord] = {}
        for record in records:
            if not isinstance(record, ControlledProductAliasRecord):
                raise TypeError(
                    "controlled alias registry requires typed records"
                )
            normalized = normalize_product_alias(record.alias)
            if normalized in by_alias:
                raise ValueError(
                    f"duplicate controlled product alias {record.alias!r}"
                )
            by_alias[normalized] = record
        self._records = tuple(records)
        self._by_alias = by_alias

    @property
    def records(self) -> tuple[ControlledProductAliasRecord, ...]:
        return self._records

    @property
    def surfaces(self) -> tuple[str, ...]:
        return tuple(record.alias for record in self._records)

    def record_for(
        self,
        alias: str,
    ) -> ControlledProductAliasRecord | None:
        return self._by_alias.get(normalize_product_alias(alias))

    def default_product_id(self, alias: str) -> int | None:
        record = self.record_for(alias)
        return record.default_product_id if record is not None else None

    def candidate_product_ids(self, alias: str) -> tuple[int, ...]:
        record = self.record_for(alias)
        return record.product_ids if record is not None else ()

    def requires_clarification(
        self,
        *,
        alias: str,
        message: str,
    ) -> bool:
        record = self.record_for(alias)
        if record is None:
            return False
        if record.identity_scope == "ambiguous_family":
            return True
        normalized_message = normalize_product_alias(message)
        return any(
            normalize_product_alias(term) in normalized_message
            for term in record.clarify_terms
        )


def load_controlled_product_aliases(
    *,
    manifest_path: Path,
    aliases_path: Path,
    catalog: CanonicalIdentityCatalogPort,
    canonical_sha256: str,
) -> ControlledProductAliasRegistry:
    if not isinstance(manifest_path, Path) or not isinstance(
        aliases_path,
        Path,
    ):
        raise TypeError("controlled alias paths must be pathlib.Path values")
    manifest = ControlledProductAliasManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8"),
        strict=True,
    )
    if aliases_path.name != manifest.aliases_file:
        raise ValueError("controlled alias manifest file binding mismatch")
    if canonical_sha256 != manifest.canonical_sha256:
        raise ValueError(
            "controlled alias Canonical SHA256 binding mismatch"
        )
    payload = aliases_path.read_bytes()
    if sha256(payload).hexdigest() != manifest.aliases_sha256:
        raise ValueError("controlled alias asset SHA256 mismatch")
    records = tuple(
        ControlledProductAliasRecord.model_validate(
            json.loads(line),
            strict=True,
        )
        for line in payload.decode("utf-8").splitlines()
        if line.strip()
    )
    if len(records) != manifest.record_count:
        raise ValueError("controlled alias record count mismatch")
    product_ids = catalog.product_ids
    for record in records:
        bound_ids = set(record.product_ids)
        if not bound_ids.issubset(product_ids):
            missing = sorted(bound_ids - product_ids)
            raise ValueError(
                f"controlled alias references unknown products {missing}"
            )
    return ControlledProductAliasRegistry(records)


def normalize_product_alias(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("product alias must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(normalized.split())


__all__ = [
    "ControlledProductAliasManifest",
    "ControlledProductAliasRecord",
    "ControlledProductAliasRegistry",
    "load_controlled_product_aliases",
    "normalize_product_alias",
]
