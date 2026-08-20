from __future__ import annotations

from collections import Counter
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.intent.responsibility_matrix import (
    Responsibility,
    ResponsibilityPresentationMode,
    decision_for_responsibility,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.presentation.copywriter_contracts import (
    CopywriterTelemetry,
    PresentationSection,
)
from app.guide.presentation.public_language_policy import (
    validate_final_public_text,
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class FactRef(_StrictFrozen):
    fact_id: str = Field(min_length=1, max_length=256)
    product_id: int | None = Field(default=None, gt=0)
    source_refs: tuple[str, ...] = ()

    @field_validator("source_refs", mode="before")
    @classmethod
    def freeze_source_refs(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ComparisonCell(_StrictFrozen):
    product_id: int = Field(gt=0)
    value: str = Field(min_length=1, max_length=512)
    fact_ids: tuple[str, ...] = ()
    state: Literal["known", "unknown", "conflict"]

    @field_validator("fact_ids", mode="before")
    @classmethod
    def freeze_fact_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_fact_ids(self) -> Self:
        if self.fact_ids != tuple(dict.fromkeys(self.fact_ids)):
            raise ValueError(
                "comparison cell fact IDs must be ordered and unique"
            )
        if self.state == "known" and not self.fact_ids:
            raise ValueError("known comparison cell requires fact IDs")
        if self.state == "unknown" and self.fact_ids:
            raise ValueError("unknown comparison cell forbids fact IDs")
        return self


class ComparisonRow(_StrictFrozen):
    dimension_id: str = Field(
        pattern=r"^[a-z][a-z0-9_.]{1,95}$"
    )
    label: str = Field(min_length=1, max_length=32)
    cells: tuple[ComparisonCell, ...] = Field(min_length=2, max_length=3)

    @field_validator("cells", mode="before")
    @classmethod
    def freeze_cells(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_cells(self) -> Self:
        product_ids = tuple(cell.product_id for cell in self.cells)
        if len(product_ids) != len(set(product_ids)):
            raise ValueError(
                "comparison row product IDs must be unique"
            )
        return self


class CompactTag(_StrictFrozen):
    product_id: int = Field(gt=0)
    label: str = Field(min_length=2, max_length=4)
    fact_ids: tuple[str, ...] = Field(min_length=1, max_length=3)

    @field_validator("fact_ids", mode="before")
    @classmethod
    def freeze_fact_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_fact_ids(self) -> Self:
        if self.fact_ids != tuple(dict.fromkeys(self.fact_ids)):
            raise ValueError("compact tag fact IDs must be unique")
        return self


class PublicPresentationContract(_StrictFrozen):
    responsibility: Responsibility
    mode: ResponsibilityPresentationMode
    copy_source: Literal["model", "fallback"]
    sections: tuple[PresentationSection, ...] = Field(min_length=1)
    comparison_rows: tuple[ComparisonRow, ...] = ()
    visible_product_ids: tuple[int, ...] = Field(max_length=3)
    compact_tags: tuple[CompactTag, ...] = ()
    card_display: CardDisplayContract
    telemetry: CopywriterTelemetry

    @field_validator("responsibility", mode="before")
    @classmethod
    def parse_responsibility(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return Responsibility(value)
            except ValueError:
                return value
        return value

    @field_validator(
        "sections",
        "comparison_rows",
        "visible_product_ids",
        "compact_tags",
        mode="before",
    )
    @classmethod
    def freeze_collections(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_public_contract(self) -> Self:
        expected = decision_for_responsibility(self.responsibility)
        if self.mode != expected.presentation_mode:
            raise ValueError(
                "public mode must match terminal responsibility"
            )
        if self.visible_product_ids != tuple(
            self.card_display.visible_product_ids
        ):
            raise ValueError(
                "visible product IDs must match card display"
            )
        if self.visible_product_ids != tuple(
            dict.fromkeys(self.visible_product_ids)
        ):
            raise ValueError("visible product IDs must be unique")
        self._validate_tags()
        self._validate_comparison_rows()
        self._validate_layout()
        self._validate_public_language()
        if self.copy_source == "model" and self.telemetry.fallback_reason:
            raise ValueError("model copy forbids fallback reason")
        if self.copy_source == "fallback" and not (
            self.telemetry.fallback_reason
        ):
            raise ValueError("fallback copy requires fallback reason")
        return self

    def _validate_public_language(self) -> None:
        visible_text = [
            *(
                text
                for section in self.sections
                for text in (
                    section.copy_text,
                    section.advisor_reason,
                    *(
                        fact.display_value
                        for fact in section.direct_facts
                    ),
                )
                if text is not None
            ),
            *(
                cell.value
                for row in self.comparison_rows
                for cell in row.cells
            ),
            *(tag.label for tag in self.compact_tags),
        ]
        for text in visible_text:
            validate_final_public_text(text)

    def _validate_tags(self) -> None:
        if any(
            tag.product_id not in self.visible_product_ids
            for tag in self.compact_tags
        ):
            raise ValueError(
                "compact tags must belong to visible products"
            )
        counts = Counter(tag.product_id for tag in self.compact_tags)
        if any(count > 3 for count in counts.values()):
            raise ValueError(
                "compact tags are limited to three per product"
            )
        keys = tuple(
            (tag.product_id, tag.label.casefold())
            for tag in self.compact_tags
        )
        if len(keys) != len(set(keys)):
            raise ValueError("compact tags must be unique per product")

    def _validate_comparison_rows(self) -> None:
        if self.responsibility is Responsibility.COMPARISON:
            if not self.comparison_rows:
                raise ValueError(
                    "comparison responsibility requires rows"
                )
            if any(
                tuple(cell.product_id for cell in row.cells)
                != self.visible_product_ids
                for row in self.comparison_rows
            ):
                raise ValueError(
                    "comparison row cells must preserve visible product order"
                )
            dimension_ids = tuple(
                row.dimension_id for row in self.comparison_rows
            )
            if len(dimension_ids) != len(set(dimension_ids)):
                raise ValueError(
                    "comparison dimension IDs must be unique"
                )
        elif self.comparison_rows:
            raise ValueError(
                "non-comparison responsibility forbids comparison rows"
            )

    def _validate_layout(self) -> None:
        kinds = tuple(section.kind for section in self.sections)
        product_ids = tuple(
            section.product_id
            for section in self.sections
            if section.kind == "product"
        )
        expected: tuple[str, ...]
        if self.responsibility is Responsibility.RECOMMENDATION:
            expected = (
                ("summary", "closing")
                if not self.visible_product_ids
                else (
                    "summary",
                    *("product" for _ in self.visible_product_ids),
                    "closing",
                    "full_cards",
                )
            )
            if product_ids != self.visible_product_ids:
                raise ValueError(
                    "recommendation products must match visible order"
                )
        elif self.responsibility is Responsibility.COMPARISON:
            expected = ("summary", "comparison", "full_cards")
        elif (
            self.responsibility
            is Responsibility.SINGLE_PRODUCT_SUITABILITY
        ):
            expected = ("summary", "judgement", "full_cards")
        elif self.responsibility is Responsibility.PRODUCT_KNOWLEDGE:
            expected = ("summary", "answer", "full_cards")
        elif self.responsibility is Responsibility.GENERAL_KNOWLEDGE:
            expected = ("general_knowledge",)
        elif self.responsibility is Responsibility.CONSULTATION:
            expected = ("observation", "summary")
        elif self.responsibility is Responsibility.IMAGE_IDENTITY:
            expected = ("observation", "full_cards")
        elif self.responsibility is Responsibility.CLARIFICATION:
            expected = (
                ("error",)
                if kinds == ("error",)
                else ("question",)
            )
        else:
            expected = ("observation", "summary")
        if kinds != expected:
            raise ValueError(
                f"{self.responsibility.value} layout does not match "
                "the public contract"
            )
        if (
            self.responsibility
            in {
                Responsibility.COMPARISON,
                Responsibility.SINGLE_PRODUCT_SUITABILITY,
                Responsibility.PRODUCT_KNOWLEDGE,
            }
            and product_ids
        ):
            raise ValueError(
                f"{self.responsibility.value} layout forbids inline products"
            )


__all__ = [
    "CompactTag",
    "ComparisonCell",
    "ComparisonRow",
    "FactRef",
    "PublicPresentationContract",
]
