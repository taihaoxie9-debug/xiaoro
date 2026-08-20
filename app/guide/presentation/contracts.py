from decimal import Decimal
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    CategoryFactValue,
    revalidate_authorized_category_fact,
)
from app.guide.retrieval.category_profiles import CategoryProfile


_UNUSABLE_PRODUCT_NAMES = frozenset({"", "无", "未知", "未命名"})


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProductCardFacts(_StrictContract):
    product_id: int
    category_profile: CategoryProfile
    category_fields: tuple[AuthorizedCategoryFact, ...]
    price_specification_alignment: Literal[
        "aligned",
        "unresolved",
        "conflict",
    ] = "aligned"
    variant_scope: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    specification: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    name: str | None
    brand: str | None
    category: str | None
    price: Decimal | None
    efficacy: tuple[str, ...] | None = None
    efficacy_state: Literal[
        "known",
        "unknown",
        "conflict",
        "not_applicable",
    ] = "unknown"
    suitable_skin: tuple[str, ...] | None = None
    suitable_skin_state: Literal[
        "known",
        "unknown",
        "conflict",
        "not_applicable",
    ] = "unknown"
    ingredients_present: tuple[str, ...] | None = None
    ingredients_present_state: Literal[
        "known",
        "unknown",
        "conflict",
        "not_applicable",
    ] = "unknown"
    image_url: str | None = None
    detail_url: str | None = None
    platform: str | None = None
    image_source_sha256: str | None = None
    fact_warnings: list[str]

    @field_validator(
        "efficacy",
        "suitable_skin",
        "ingredients_present",
        mode="before",
    )
    @classmethod
    def freeze_direct_display_values(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_category_fields(self) -> Self:
        category_fields = tuple(
            revalidate_authorized_category_fact(item)
            for item in self.category_fields
        )
        if any(
            item.category_profile is not self.category_profile
            for item in category_fields
        ):
            raise ValueError(
                "category fact profile must match presentation product profile"
            )
        object.__setattr__(self, "category_fields", category_fields)
        field_keys = tuple(
            item.field_key for item in category_fields
        )
        if field_keys != tuple(sorted(set(field_keys))):
            raise ValueError(
                "category fields must be sorted and unique"
            )
        for value, state, field_name in (
            (
                self.efficacy,
                self.efficacy_state,
                "efficacy",
            ),
            (
                self.suitable_skin,
                self.suitable_skin_state,
                "suitable_skin",
            ),
            (
                self.ingredients_present,
                self.ingredients_present_state,
                "ingredients_present",
            ),
        ):
            if state == "known":
                if value is None:
                    raise ValueError(
                        f"{field_name} requires value when known"
                    )
                if not value or any(
                    type(item) is not str
                    or not item
                    or item != item.strip()
                    for item in value
                ):
                    raise ValueError(
                        f"{field_name} values must be nonempty strings"
                    )
            elif value is not None:
                raise ValueError(
                    f"{field_name} forbids value unless known"
                )
        if self.display_name is None and self.name is not None:
            object.__setattr__(
                self,
                "display_name",
                self.name.strip() or None,
            )
        return self


class DisplayCategoryFact(_StrictContract):
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str = Field(min_length=1, max_length=32)
    value: CategoryFactValue
    state: Literal["known", "unavailable", "conflict"]

    @field_validator("value", mode="before")
    @classmethod
    def freeze_string_list_value(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_state_value(self) -> Self:
        if self.state == "known" and self.value is None:
            raise ValueError(
                "known display category fact requires a value"
            )
        if self.state != "known" and self.value is not None:
            raise ValueError(
                "unavailable or conflict display fact forbids a value"
            )
        return self


class ProductCard(_StrictContract):
    type: Literal["product_card"] = "product_card"
    product_id: int
    category_profile: CategoryProfile
    category_facts: tuple[DisplayCategoryFact, ...]
    price_specification_alignment: Literal[
        "aligned",
        "unresolved",
        "conflict",
    ] = "aligned"
    variant_scope: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    specification: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    name: str | None
    brand: str | None
    category: str | None
    price: Decimal | None
    image_url: str | None = None
    detail_url: str | None = None
    platform: str | None = None
    image_source_sha256: str | None = None
    skin_match: Literal[
        "matched",
        "unknown",
        "not_applicable",
    ]
    matched_efficacies: list[str]
    fact_warnings: list[str]

    @field_validator("category_facts", mode="before")
    @classmethod
    def freeze_category_facts(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_category_facts(self) -> Self:
        keys = tuple(fact.field_key for fact in self.category_facts)
        if keys != tuple(sorted(set(keys))):
            raise ValueError(
                "display category facts must be sorted and unique"
            )
        current_name = (self.name or "").strip()
        if current_name in _UNUSABLE_PRODUCT_NAMES:
            parts = []
            for value in (self.brand, self.category):
                normalized = (value or "").strip()
                if (
                    normalized
                    and normalized not in _UNUSABLE_PRODUCT_NAMES
                    and normalized not in parts
                ):
                    parts.append(normalized)
            object.__setattr__(
                self,
                "name",
                " ".join(parts) or f"商品 {self.product_id}",
            )
        current_display_name = (self.display_name or "").strip()
        if current_display_name in _UNUSABLE_PRODUCT_NAMES:
            object.__setattr__(self, "display_name", self.name)
        return self


class CardDisplayContract(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    mode: Literal[
        "none",
        "single",
        "recommendation",
        "comparison",
    ]
    visible_product_ids: tuple[int, ...] = Field(max_length=3)
    max_cards: int = Field(ge=0, le=3)
    reason: Literal[
        "product",
        "recommendation",
        "comparison",
    ] | None = None

    @field_validator("visible_product_ids", mode="before")
    @classmethod
    def freeze_visible_product_ids(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        count = len(self.visible_product_ids)
        if count != len(set(self.visible_product_ids)):
            raise ValueError("visible product IDs must be unique")
        if self.max_cards != count:
            raise ValueError(
                "max_cards must equal visible product count"
            )
        if self.mode == "none":
            if count != 0 or self.reason is not None:
                raise ValueError(
                    "none mode forbids products and reason"
                )
            return self
        if self.mode == "single" and count != 1:
            raise ValueError("single mode requires one product")
        if (
            self.mode == "recommendation"
            and not 1 <= count <= 3
        ):
            raise ValueError(
                "recommendation requires one to three products"
            )
        if self.mode == "comparison" and not 2 <= count <= 3:
            raise ValueError(
                "comparison requires two or three products"
            )
        allowed_reasons = {
            "single": {"product", "recommendation"},
            "recommendation": {"recommendation"},
            "comparison": {"comparison"},
        }
        if self.reason not in allowed_reasons[self.mode]:
            raise ValueError("mode and reason must be legally paired")
        return self


class ResponsePlan(_StrictContract):
    sections: list[Literal["recommendation"]]
    structured_events: list[ProductCard]
    text_generation_context: dict[str, JsonValue]
    followup_actions: list[dict[str, JsonValue]]
