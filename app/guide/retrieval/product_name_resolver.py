from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.retrieval.controlled_product_aliases import (
    ControlledProductAliasRegistry,
)
from app.guide.understanding.ports import CanonicalIdentityCatalogPort
from app.guide.understanding.semantic_contracts import (
    SemanticProductMention,
)

_IDENTITY_ALIAS_SEPARATOR = re.compile(r"\s*[/／]\s*")
ProductResolutionIssue = Literal[
    "missing_reference",
    "ambiguous_reference",
    "invalid_source_span",
]


class ResolvedProductBinding(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    product_id: int = Field(gt=0)
    variant_scope: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    source_text: str = Field(min_length=1, max_length=160)


class ProductMentionResolution(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    bindings: tuple[ResolvedProductBinding, ...]
    issue: ProductResolutionIssue | None = None

    @property
    def product_ids(self) -> tuple[int, ...]:
        return tuple(
            dict.fromkeys(
                binding.product_id for binding in self.bindings
            )
        )

    def variant_scope_for(self, product_id: int) -> str | None:
        if (
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id <= 0
        ):
            raise TypeError("product_id must be a positive integer")
        matching = tuple(
            binding
            for binding in self.bindings
            if binding.product_id == product_id
        )
        return (
            matching[0].variant_scope
            if len(matching) == 1
            else None
        )

    @model_validator(mode="after")
    def validate_resolution(self) -> ProductMentionResolution:
        if self.issue is None:
            if len(self.bindings) > 4:
                raise ValueError(
                    "resolved mentions allow at most four bindings"
                )
            keys = tuple(
                (binding.product_id, binding.variant_scope)
                for binding in self.bindings
            )
            if len(keys) != len(set(keys)):
                raise ValueError(
                    "resolved product bindings must be unique"
                )
        elif self.bindings:
            raise ValueError(
                "failed mention resolution forbids product bindings"
            )
        return self


class ProductNameResolver:
    def __init__(
        self,
        catalog: CanonicalIdentityCatalogPort,
        *,
        aliases: Mapping[str, int] | None = None,
        controlled_aliases: ControlledProductAliasRegistry | None = None,
    ) -> None:
        self._catalog = catalog
        self._aliases = dict(aliases or {})
        self._controlled_aliases = controlled_aliases
        self._index: dict[str, set[int]] | None = None
        self._surfaces: set[str] | None = None

    def find_explicit_mentions(
        self,
        message: str,
    ) -> tuple[SemanticProductMention, ...]:
        if not isinstance(message, str):
            raise TypeError("message must be str")
        self._ensure_index()
        assert self._surfaces is not None
        matches: list[tuple[int, int, str]] = []
        for surface in sorted(
            self._surfaces,
            key=lambda value: (-len(value), value.casefold()),
        ):
            for match in re.finditer(
                re.escape(surface),
                message,
                flags=re.IGNORECASE,
            ):
                matches.append(
                    (match.start(), match.end(), match.group())
                )
        selected: list[tuple[int, int, str]] = []
        for start, end, text in sorted(
            matches,
            key=lambda item: (
                item[0],
                -(item[1] - item[0]),
                item[2].casefold(),
            ),
        ):
            if any(
                start < selected_end and selected_start < end
                for selected_start, selected_end, _ in selected
            ):
                continue
            selected.append((start, end, text))
        return tuple(
            SemanticProductMention(
                text=text,
                start=start,
                end=end,
            )
            for start, end, text in sorted(selected)
        )

    def product_names(
        self,
        product_ids: Sequence[int],
    ) -> tuple[str, ...]:
        if (
            isinstance(product_ids, (str, bytes))
            or not isinstance(product_ids, Sequence)
            or any(
                not isinstance(product_id, int)
                or isinstance(product_id, bool)
                or product_id <= 0
                for product_id in product_ids
            )
        ):
            raise TypeError(
                "product_ids must contain positive integers"
            )
        names: list[str] = []
        for product_id in product_ids:
            identity = self._catalog.get_identity(product_id)
            if identity is None or identity.product_name is None:
                return ()
            names.append(identity.product_name)
        return tuple(names)

    def resolve(
        self,
        *,
        message: str,
        mentions: Sequence[SemanticProductMention],
    ) -> ProductMentionResolution:
        if not isinstance(message, str):
            raise TypeError("message must be str")
        if (
            isinstance(mentions, (str, bytes))
            or not isinstance(mentions, Sequence)
            or any(
                not isinstance(item, SemanticProductMention)
                for item in mentions
            )
        ):
            raise TypeError(
                "mentions must contain SemanticProductMention values"
            )
        if not mentions:
            return ProductMentionResolution(
                bindings=(),
                issue="missing_reference",
            )
        self._ensure_index()
        assert self._index is not None

        bindings: list[ResolvedProductBinding] = []
        for mention in mentions:
            if (
                mention.end > len(message)
                or message[mention.start:mention.end] != mention.text
            ):
                return ProductMentionResolution(
                    bindings=(),
                    issue="invalid_source_span",
                )
            controlled_record = (
                self._controlled_aliases.record_for(mention.text)
                if self._controlled_aliases is not None
                else None
            )
            if (
                self._controlled_aliases is not None
                and self._controlled_aliases.requires_clarification(
                    alias=mention.text,
                    message=message,
                )
            ):
                return ProductMentionResolution(
                    bindings=(),
                    issue="ambiguous_reference",
                )
            normalized_mention = _normalize_name(mention.text)
            candidates = self._index.get(
                normalized_mention,
                set(),
            )
            if not candidates:
                candidates = self._prefix_candidates(
                    normalized_mention
                )
            if not candidates:
                return ProductMentionResolution(
                    bindings=(),
                    issue="missing_reference",
                )
            if len(candidates) != 1:
                return ProductMentionResolution(
                    bindings=(),
                    issue="ambiguous_reference",
                )
            bindings.append(
                ResolvedProductBinding(
                    product_id=next(iter(candidates)),
                    variant_scope=(
                        controlled_record.variant_scope
                        if controlled_record is not None
                        and controlled_record.identity_scope
                        == "exact_variant"
                        else None
                    ),
                    source_text=mention.text,
                )
            )

        unique_bindings: dict[
            tuple[int, str | None],
            ResolvedProductBinding,
        ] = {}
        for binding in bindings:
            unique_bindings.setdefault(
                (binding.product_id, binding.variant_scope),
                binding,
            )
        return ProductMentionResolution(
            bindings=tuple(unique_bindings.values()),
        )

    def _prefix_candidates(self, normalized: str) -> set[int]:
        assert self._index is not None
        if len(normalized.replace(" ", "")) < 4:
            return set()
        candidates: set[int] = set()
        for indexed_name, product_ids in self._index.items():
            if (
                indexed_name.startswith(normalized)
                or normalized.startswith(indexed_name)
            ):
                candidates.update(product_ids)
        return candidates

    def _add_index(self, name: str, product_id: int) -> None:
        assert self._index is not None
        assert self._surfaces is not None
        normalized = _normalize_name(name)
        if not normalized:
            raise ValueError("product identity must not be empty")
        self._index.setdefault(normalized, set()).add(product_id)
        self._surfaces.add(name)

    def _ensure_index(self) -> None:
        if self._index is not None:
            return
        self._index = {}
        self._surfaces = set()
        for product_id in sorted(self._catalog.product_ids):
            identity = self._catalog.get_identity(product_id)
            if identity is None or identity.product_name is None:
                continue
            for surface in _identity_surfaces(identity.product_name):
                self._add_index(surface, product_id)
        for alias, product_id in self._aliases.items():
            if product_id not in self._catalog.product_ids:
                raise ValueError(
                    f"alias references unknown product_id {product_id}"
                )
            self._add_index(alias, product_id)
        if self._controlled_aliases is not None:
            for record in self._controlled_aliases.records:
                self._surfaces.add(record.alias)
                if record.default_product_id is not None:
                    self._add_index(
                        record.alias,
                        record.default_product_id,
                    )


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _identity_surfaces(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            surface
            for surface in (
                value,
                *(
                    part.strip()
                    for part in _IDENTITY_ALIAS_SEPARATOR.split(value)
                ),
            )
            if surface
        )
    )


__all__ = [
    "ProductMentionResolution",
    "ProductNameResolver",
    "ResolvedProductBinding",
]
