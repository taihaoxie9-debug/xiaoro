from __future__ import annotations

import math
from collections.abc import Iterable
from enum import Enum
from types import MappingProxyType
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.retrieval.category_profiles import CategoryProfile


class SourceClass(str, Enum):
    CANONICAL_CORE = "canonical_core"
    STRUCTURED_OFFICIAL = "structured_official"
    OFFICIAL_REGISTRATION = "official_registration"
    OFFICIAL_PACKAGING = "official_packaging"
    OFFICIAL_DESCRIPTION = "official_description"
    MERCHANT_PARAMETER = "merchant_parameter"
    MERCHANT_TITLE_CLAIM = "merchant_title_claim"
    MERCHANT_DESCRIPTION = "merchant_description"
    MERCHANT_DESCRIPTION_OCR = "merchant_description_ocr"
    OCR_PACKAGING = "ocr_packaging"
    PACKAGE_OCR = "package_ocr"
    OCR_INGREDIENT_LIST = "ocr_ingredient_list"
    APPROVED_CONSUMER_REVIEW = "approved_consumer_review"
    CONSUMER_REVIEW = "consumer_review"
    QA = "qa"
    PROMOTION_OR_RECOMMENDATION_BLOCK = (
        "promotion_or_recommendation_block"
    )
    UNKNOWN = "unknown"


Capability = Literal[
    "evidence",
    "display",
    "compare",
    "hard_filter",
    "soft_rank",
]
ValueType = Literal["string", "string_list", "number", "boolean"]
UnknownPolicy = Literal["preserve_unknown"]
ConflictPolicy = Literal["record"]
ResolvedState = Literal[
    "known",
    "unknown",
    "conflict",
    "not_applicable",
]
CategoryFactValue = str | tuple[str, ...] | int | float | bool | None

_EVIDENCE_ONLY = frozenset({"evidence"})
_EVIDENCE_DISPLAY = frozenset({"evidence", "display"})
_EVIDENCE_DISPLAY_COMPARE = frozenset(
    {"evidence", "display", "compare"}
)
_EVIDENCE_DISPLAY_COMPARE_FILTER = frozenset(
    {"evidence", "display", "compare", "hard_filter"}
)
_EVIDENCE_DISPLAY_COMPARE_RANK = frozenset(
    {"evidence", "display", "compare", "soft_rank"}
)
_EVIDENCE_DISPLAY_COMPARE_FILTER_RANK = frozenset(
    {
        "evidence",
        "display",
        "compare",
        "hard_filter",
        "soft_rank",
    }
)

_CORE_FIELDS = frozenset(
    {"product_identity", "brand", "category", "price"}
)
_EXPERIENTIAL_REVIEW_FIELDS = frozenset(
    {
        "texture",
        "finish",
        "coverage",
        "longevity",
        "cleansing_power",
        "rinse_behavior",
        "sillage",
        "film_speed",
        "fragrance_description",
        "color_payoff",
        "makeup_effect",
        "makeup_style",
        "cleansing_requirement",
        "friction_resistance",
    }
)
_SOURCE_PRECEDENCE = MappingProxyType(
    {
        SourceClass.CANONICAL_CORE: 0,
        SourceClass.STRUCTURED_OFFICIAL: 1,
        SourceClass.OFFICIAL_REGISTRATION: 2,
        SourceClass.OFFICIAL_PACKAGING: 3,
        SourceClass.MERCHANT_PARAMETER: 4,
        SourceClass.MERCHANT_TITLE_CLAIM: 5,
        SourceClass.OFFICIAL_DESCRIPTION: 6,
        SourceClass.MERCHANT_DESCRIPTION: 7,
        SourceClass.MERCHANT_DESCRIPTION_OCR: 8,
        SourceClass.OCR_PACKAGING: 9,
        SourceClass.PACKAGE_OCR: 10,
        SourceClass.OCR_INGREDIENT_LIST: 11,
        SourceClass.APPROVED_CONSUMER_REVIEW: 12,
        SourceClass.CONSUMER_REVIEW: 13,
        SourceClass.QA: 14,
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK: 15,
        SourceClass.UNKNOWN: 16,
    }
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AuthorizedCategoryFact(_StrictFrozenModel):
    category_profile: CategoryProfile
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: CategoryFactValue
    resolved_state: ResolvedState
    source_classes: tuple[SourceClass, ...] = Field(min_length=1)
    source_refs: tuple[str, ...]
    capabilities: frozenset[Capability] = Field(min_length=1)

    @field_validator("value", mode="before")
    @classmethod
    def reject_mutable_string_lists(cls, value: object) -> object:
        if isinstance(value, list):
            raise ValueError(
                "category fact string_list requires strict tuple"
            )
        return value

    @field_validator("source_classes", "source_refs", mode="before")
    @classmethod
    def freeze_ordered_values(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("capabilities", mode="before")
    @classmethod
    def freeze_capabilities(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @model_validator(mode="after")
    def validate_authorized_fact(self) -> Self:
        if "evidence" not in self.capabilities:
            raise ValueError("authorized facts require evidence capability")
        if self.source_classes != tuple(
            sorted(set(self.source_classes), key=lambda item: item.value)
        ):
            raise ValueError("source classes must be sorted and unique")
        if self.source_refs != tuple(sorted(set(self.source_refs))):
            raise ValueError("source references must be sorted and unique")
        if any(
            not reference or reference != reference.strip()
            for reference in self.source_refs
        ):
            raise ValueError(
                "source references must be non-empty and trimmed"
            )

        definition = self._registry_definition()
        policies = {
            policy.source_class: policy
            for policy in definition.source_policies
        }
        if any(
            source_class not in policies
            for source_class in self.source_classes
        ):
            raise ValueError(
                "category fact source is not authorized for field"
            )
        allowed_capabilities = set(
            policies[self.source_classes[0]].capabilities
        )
        for source_class in self.source_classes[1:]:
            allowed_capabilities.intersection_update(
                policies[source_class].capabilities
            )
        if not self.capabilities <= allowed_capabilities:
            raise ValueError(
                "category fact capabilities exceed registry source policy"
            )

        if self.resolved_state == "known":
            if self.value is None:
                raise ValueError("known category fact requires a value")
            if any(
                source_class
                in {SourceClass.CANONICAL_CORE, SourceClass.UNKNOWN}
                for source_class in self.source_classes
            ):
                raise ValueError(
                    "known category fact requires approved source"
                )
            if not self.source_refs:
                raise ValueError(
                    "known category fact requires source references"
                )
            self._validate_known_value(definition.value_type)
            return self

        if self.value is not None:
            raise ValueError(
                "non-known category fact must preserve a null value"
            )
        forbidden = {
            "display",
            "compare",
            "hard_filter",
            "soft_rank",
        }
        if not self.capabilities.isdisjoint(forbidden):
            raise ValueError(
                "non-known category fact forbids public capabilities"
            )
        if self.resolved_state == "conflict":
            if SourceClass.UNKNOWN in self.source_classes:
                raise ValueError("conflict forbids unknown source")
            if not self.source_refs:
                raise ValueError("conflict requires source references")
        elif (
            self.source_classes != (SourceClass.UNKNOWN,)
            or self.source_refs
        ):
            raise ValueError(
                "unknown and not-applicable facts require unknown source"
            )
        return self

    def _registry_definition(self) -> CategoryFieldDefinition:
        definitions = {
            definition.key: definition
            for definition in category_field_registry().definitions
        }
        definition = definitions.get(self.field_key)
        if definition is None:
            raise ValueError(
                f"unknown category fact field: {self.field_key}"
            )
        if self.field_key in _CORE_FIELDS:
            raise ValueError(
                "canonical core field is forbidden in authorized "
                "category facts"
            )
        if self.category_profile not in definition.profiles:
            raise ValueError(
                "category fact field is not applicable to profile: "
                f"{self.category_profile.value}.{self.field_key}"
            )
        return definition

    def _validate_known_value(self, value_type: ValueType) -> None:
        value = self.value
        if value_type == "string":
            if type(value) is not str:
                raise ValueError(
                    f"category fact value type mismatch for {self.field_key}"
                )
            if not value or value != value.strip():
                raise ValueError(
                    "category fact strings must be non-empty and trimmed"
                )
            return
        if value_type == "string_list":
            if type(value) is not tuple:
                raise ValueError(
                    f"category fact value type mismatch for {self.field_key}"
                )
            if not value or any(
                type(item) is not str
                or not item
                or item != item.strip()
                for item in value
            ):
                raise ValueError(
                    "category fact string lists must be non-empty and trimmed"
                )
            return
        if value_type == "number":
            if type(value) not in {int, float}:
                raise ValueError(
                    f"category fact value type mismatch for {self.field_key}"
                )
            if type(value) is float and not math.isfinite(value):
                raise ValueError("category fact numbers must be finite")
            return
        if value_type == "boolean" and type(value) is not bool:
            raise ValueError(
                f"category fact value type mismatch for {self.field_key}"
            )


def revalidate_authorized_category_fact(
    fact: AuthorizedCategoryFact,
) -> AuthorizedCategoryFact:
    if not isinstance(fact, AuthorizedCategoryFact):
        raise TypeError(
            "category fact must be an AuthorizedCategoryFact instance"
        )
    payload = {
        field_name: getattr(fact, field_name)
        for field_name in AuthorizedCategoryFact.model_fields
        if hasattr(fact, field_name)
    }
    return AuthorizedCategoryFact.model_validate(payload)


def filter_category_facts_by_capability(
    facts: Iterable[AuthorizedCategoryFact],
    capability: Capability,
) -> tuple[AuthorizedCategoryFact, ...]:
    allowed = {
        "evidence",
        "display",
        "compare",
        "hard_filter",
        "soft_rank",
    }
    if capability not in allowed:
        raise ValueError(f"unknown category fact capability: {capability}")
    validated = tuple(
        revalidate_authorized_category_fact(fact) for fact in facts
    )
    return tuple(
        fact for fact in validated if capability in fact.capabilities
    )


class SourcePolicy(_StrictFrozenModel):
    source_class: SourceClass
    capabilities: frozenset[Capability] = Field(min_length=1)

    @field_validator("capabilities", mode="before")
    @classmethod
    def freeze_capabilities(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if "evidence" not in self.capabilities:
            raise ValueError("every source policy requires evidence")
        if (
            self.source_class is SourceClass.UNKNOWN
            and self.capabilities != _EVIDENCE_ONLY
        ):
            raise ValueError("unknown source is evidence-only")
        if self.source_class in {
            SourceClass.OCR_PACKAGING,
            SourceClass.PACKAGE_OCR,
            SourceClass.OCR_INGREDIENT_LIST,
            SourceClass.QA,
            SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
        } and self.capabilities != _EVIDENCE_ONLY:
            raise ValueError("OCR sources are evidence-only")
        if (
            self.source_class is SourceClass.MERCHANT_DESCRIPTION_OCR
            and not self.capabilities <= _EVIDENCE_DISPLAY_COMPARE_RANK
        ):
            raise ValueError(
                "merchant description OCR cannot authorize hard filters"
            )
        if (
            self.source_class
            in {
                SourceClass.APPROVED_CONSUMER_REVIEW,
                SourceClass.CONSUMER_REVIEW,
            }
            and not self.capabilities <= _EVIDENCE_DISPLAY
        ):
            raise ValueError(
                "approved consumer review is evidence/display-only"
            )
        if (
            self.source_class
            in {
                SourceClass.MERCHANT_PARAMETER,
                SourceClass.MERCHANT_TITLE_CLAIM,
                SourceClass.MERCHANT_DESCRIPTION,
            }
            and not self.capabilities
            <= _EVIDENCE_DISPLAY_COMPARE_RANK
        ):
            raise ValueError(
                "merchant claims cannot authorize hard filters"
            )
        if (
            self.source_class is SourceClass.OFFICIAL_DESCRIPTION
            and not self.capabilities <= _EVIDENCE_DISPLAY
        ):
            raise ValueError(
                "official description is evidence/display-only"
            )
        return self


class CategoryFieldDefinition(_StrictFrozenModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str = Field(min_length=1, max_length=32)
    aliases: tuple[str, ...] = Field(min_length=1)
    value_type: ValueType
    profiles: frozenset[CategoryProfile] = Field(min_length=1)
    source_policies: tuple[SourcePolicy, ...] = Field(min_length=1)
    unknown_policy: UnknownPolicy
    conflict_policy: ConflictPolicy

    @field_validator("aliases", "source_policies", mode="before")
    @classmethod
    def freeze_ordered_values(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("profiles", mode="before")
    @classmethod
    def freeze_profiles(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if self.label != self.label.strip():
            raise ValueError("field label must be trimmed")

        stripped_aliases = tuple(alias.strip() for alias in self.aliases)
        normalized_aliases = tuple(
            alias.casefold() for alias in stripped_aliases
        )
        if any(not alias for alias in stripped_aliases):
            raise ValueError("field aliases must be non-empty")
        if any(
            alias != stripped
            for alias, stripped in zip(self.aliases, stripped_aliases)
        ):
            raise ValueError("field aliases must be trimmed")
        if len(normalized_aliases) != len(set(normalized_aliases)):
            raise ValueError("duplicate field alias")

        source_classes = tuple(
            policy.source_class for policy in self.source_policies
        )
        if len(source_classes) != len(set(source_classes)):
            raise ValueError("duplicate source policy")
        if tuple(
            _SOURCE_PRECEDENCE[source_class]
            for source_class in source_classes
        ) != tuple(
            sorted(
                _SOURCE_PRECEDENCE[source_class]
                for source_class in source_classes
            )
        ):
            raise ValueError("source policies must follow source precedence")

        if self.key in _CORE_FIELDS:
            if source_classes != (SourceClass.CANONICAL_CORE,):
                raise ValueError(
                    "canonical core fields only allow canonical_core"
                )
        elif SourceClass.CANONICAL_CORE in source_classes:
            raise ValueError(
                "canonical_core may only author canonical core fields"
            )

        if (
            SourceClass.OCR_INGREDIENT_LIST in source_classes
            and self.key != "ingredients_present"
        ):
            raise ValueError(
                "OCR ingredient list may only observe ingredients_present"
            )
        if (
            any(
                source_class
                in {
                    SourceClass.APPROVED_CONSUMER_REVIEW,
                    SourceClass.CONSUMER_REVIEW,
                }
                for source_class in source_classes
            )
            and self.key not in _EXPERIENTIAL_REVIEW_FIELDS
        ):
            raise ValueError(
                "approved consumer review may only author experiential fields"
            )
        return self


class CategoryFieldRegistry:
    __slots__ = ("_by_profile", "_definitions")

    def __init__(
        self,
        *,
        definitions: tuple[CategoryFieldDefinition, ...],
    ) -> None:
        frozen_definitions = tuple(definitions)
        keys = tuple(definition.key for definition in frozen_definitions)
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate field key")

        aliases: dict[str, str] = {}
        for definition in frozen_definitions:
            source_classes = tuple(
                policy.source_class
                for policy in definition.source_policies
            )
            if len(source_classes) != len(set(source_classes)):
                raise ValueError(
                    f"duplicate source policy for {definition.key}"
                )
            for alias in definition.aliases:
                normalized = alias.casefold()
                previous = aliases.get(normalized)
                if previous is not None:
                    raise ValueError(
                        "duplicate field alias "
                        f"{alias!r} for {previous!r} and {definition.key!r}"
                    )
                aliases[normalized] = definition.key

        self._definitions = frozen_definitions
        self._by_profile = MappingProxyType(
            {
                profile: tuple(
                    definition
                    for definition in frozen_definitions
                    if profile in definition.profiles
                )
                for profile in CategoryProfile
            }
        )

    @property
    def definitions(self) -> tuple[CategoryFieldDefinition, ...]:
        return self._definitions

    def for_profile(
        self,
        profile: CategoryProfile,
    ) -> tuple[CategoryFieldDefinition, ...]:
        return self._by_profile[profile]


def _source_policy(
    source_class: SourceClass,
    capabilities: frozenset[str],
) -> SourcePolicy:
    return SourcePolicy(
        source_class=source_class,
        capabilities=capabilities,
    )


def _source_policies(
    *items: tuple[SourceClass, frozenset[str]],
) -> tuple[SourcePolicy, ...]:
    return tuple(
        _source_policy(source_class, capabilities)
        for source_class, capabilities in items
    )


def _field(
    *,
    key: str,
    label: str,
    aliases: tuple[str, ...],
    value_type: ValueType,
    profiles: frozenset[CategoryProfile],
    source_policies: tuple[SourcePolicy, ...],
) -> CategoryFieldDefinition:
    return CategoryFieldDefinition(
        key=key,
        label=label,
        aliases=aliases,
        value_type=value_type,
        profiles=profiles,
        source_policies=source_policies,
        unknown_policy="preserve_unknown",
        conflict_policy="record",
    )


_ALL_PROFILES = frozenset(CategoryProfile)
_SKINCARE = frozenset({CategoryProfile.SKINCARE})
_SUNCARE = frozenset({CategoryProfile.SUNCARE})
_EFFICACY_PROFILES = frozenset(
    {
        CategoryProfile.SKINCARE,
        CategoryProfile.SUNCARE,
        CategoryProfile.BASE_MAKEUP,
        CategoryProfile.COLOR_MAKEUP,
        CategoryProfile.CLEANSER,
    }
)
_SKIN_CONCERN_PROFILES = _EFFICACY_PROFILES
_MECHANISM_PROFILES = _EFFICACY_PROFILES
_SPF_PROFILES = frozenset(
    {
        CategoryProfile.SUNCARE,
        CategoryProfile.BASE_MAKEUP,
    }
)
_BASE_AND_COLOR = frozenset(
    {CategoryProfile.BASE_MAKEUP, CategoryProfile.COLOR_MAKEUP}
)
_FINISH_PROFILES = _BASE_AND_COLOR | _SUNCARE
_VARIANT_OPTION_PROFILES = frozenset(
    {
        CategoryProfile.SUNCARE,
        CategoryProfile.BASE_MAKEUP,
        CategoryProfile.COLOR_MAKEUP,
    }
)
_TEXTURE_PROFILES = frozenset(
    {
        CategoryProfile.SKINCARE,
        CategoryProfile.SUNCARE,
        CategoryProfile.BASE_MAKEUP,
        CategoryProfile.COLOR_MAKEUP,
        CategoryProfile.CLEANSER,
    }
)
_SUITABLE_SKIN_PROFILES = frozenset(
    {
        CategoryProfile.SKINCARE,
        CategoryProfile.SUNCARE,
        CategoryProfile.BASE_MAKEUP,
        CategoryProfile.COLOR_MAKEUP,
        CategoryProfile.CLEANSER,
    }
)
_APPLICATION_AREA_PROFILES = frozenset(
    {
        CategoryProfile.SKINCARE,
        CategoryProfile.SUNCARE,
        CategoryProfile.BASE_MAKEUP,
        CategoryProfile.COLOR_MAKEUP,
        CategoryProfile.CLEANSER,
    }
)
_PRODUCT_FORM_PROFILES = _APPLICATION_AREA_PROFILES
_FRAGRANCE_DESCRIPTION_PROFILES = frozenset(
    {
        CategoryProfile.SKINCARE,
        CategoryProfile.CLEANSER,
    }
)
_LONGEVITY_PROFILES = frozenset(
    {
        CategoryProfile.BASE_MAKEUP,
        CategoryProfile.COLOR_MAKEUP,
        CategoryProfile.FRAGRANCE,
    }
)
_CLEANSER = frozenset({CategoryProfile.CLEANSER})
_FRAGRANCE = frozenset({CategoryProfile.FRAGRANCE})

_CANONICAL_DISPLAY_COMPARE = _source_policies(
    (SourceClass.CANONICAL_CORE, _EVIDENCE_DISPLAY_COMPARE),
)
_CANONICAL_FILTER = _source_policies(
    (SourceClass.CANONICAL_CORE, _EVIDENCE_DISPLAY_COMPARE_FILTER),
)
_CANONICAL_PRICE = _source_policies(
    (
        SourceClass.CANONICAL_CORE,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
)
_INGREDIENT_POLICIES = _source_policies(
    (
        SourceClass.STRUCTURED_OFFICIAL,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (
        SourceClass.OFFICIAL_REGISTRATION,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (
        SourceClass.OFFICIAL_PACKAGING,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (
        SourceClass.OCR_INGREDIENT_LIST,
        _EVIDENCE_ONLY,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_VERIFIED_ABSENCE_POLICIES = _source_policies(
    (
        SourceClass.STRUCTURED_OFFICIAL,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (
        SourceClass.OFFICIAL_REGISTRATION,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (
        SourceClass.OFFICIAL_PACKAGING,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_SAFETY_POLICIES = _source_policies(
    (
        SourceClass.STRUCTURED_OFFICIAL,
        _EVIDENCE_DISPLAY_COMPARE_FILTER,
    ),
    (
        SourceClass.OFFICIAL_REGISTRATION,
        _EVIDENCE_DISPLAY_COMPARE_FILTER,
    ),
    (
        SourceClass.OFFICIAL_PACKAGING,
        _EVIDENCE_DISPLAY_COMPARE_FILTER,
    ),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_USAGE_POLICIES = _source_policies(
    (SourceClass.STRUCTURED_OFFICIAL, _EVIDENCE_DISPLAY_COMPARE),
    (
        SourceClass.OFFICIAL_REGISTRATION,
        _EVIDENCE_DISPLAY_COMPARE,
    ),
    (SourceClass.OFFICIAL_PACKAGING, _EVIDENCE_DISPLAY_COMPARE),
    (SourceClass.MERCHANT_PARAMETER, _EVIDENCE_DISPLAY_COMPARE),
    (SourceClass.OFFICIAL_DESCRIPTION, _EVIDENCE_DISPLAY),
    (SourceClass.MERCHANT_DESCRIPTION, _EVIDENCE_DISPLAY),
    (SourceClass.MERCHANT_DESCRIPTION_OCR, _EVIDENCE_DISPLAY_COMPARE),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_CLAIM_RANK_POLICIES = _source_policies(
    (
        SourceClass.STRUCTURED_OFFICIAL,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (
        SourceClass.OFFICIAL_REGISTRATION,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (SourceClass.OFFICIAL_PACKAGING, _EVIDENCE_DISPLAY_COMPARE),
    (
        SourceClass.MERCHANT_PARAMETER,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_TITLE_CLAIM,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OFFICIAL_DESCRIPTION, _EVIDENCE_DISPLAY),
    (
        SourceClass.MERCHANT_DESCRIPTION,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_DESCRIPTION_OCR,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (SourceClass.QA, _EVIDENCE_ONLY),
    (
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
        _EVIDENCE_ONLY,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_MERCHANT_CLAIM_ONLY_POLICIES = _source_policies(
    (
        SourceClass.MERCHANT_PARAMETER,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_TITLE_CLAIM,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_DESCRIPTION,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_DESCRIPTION_OCR,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_CLAIM_COMPARE_POLICIES = _source_policies(
    (SourceClass.STRUCTURED_OFFICIAL, _EVIDENCE_DISPLAY_COMPARE),
    (
        SourceClass.OFFICIAL_REGISTRATION,
        _EVIDENCE_DISPLAY_COMPARE,
    ),
    (SourceClass.OFFICIAL_PACKAGING, _EVIDENCE_DISPLAY),
    (SourceClass.MERCHANT_PARAMETER, _EVIDENCE_DISPLAY_COMPARE),
    (
        SourceClass.MERCHANT_TITLE_CLAIM,
        _EVIDENCE_DISPLAY_COMPARE,
    ),
    (SourceClass.OFFICIAL_DESCRIPTION, _EVIDENCE_DISPLAY),
    (SourceClass.MERCHANT_DESCRIPTION, _EVIDENCE_DISPLAY_COMPARE),
    (SourceClass.MERCHANT_DESCRIPTION_OCR, _EVIDENCE_DISPLAY_COMPARE),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (SourceClass.QA, _EVIDENCE_ONLY),
    (
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
        _EVIDENCE_ONLY,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_EXPERIENTIAL_RANK_POLICIES = _source_policies(
    (
        SourceClass.STRUCTURED_OFFICIAL,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OFFICIAL_PACKAGING, _EVIDENCE_DISPLAY_COMPARE),
    (
        SourceClass.MERCHANT_PARAMETER,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_TITLE_CLAIM,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OFFICIAL_DESCRIPTION, _EVIDENCE_DISPLAY),
    (
        SourceClass.MERCHANT_DESCRIPTION,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_DESCRIPTION_OCR,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (
        SourceClass.APPROVED_CONSUMER_REVIEW,
        _EVIDENCE_DISPLAY,
    ),
    (SourceClass.CONSUMER_REVIEW, _EVIDENCE_DISPLAY),
    (SourceClass.QA, _EVIDENCE_ONLY),
    (
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
        _EVIDENCE_ONLY,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_STRUCTURED_SPEC_POLICIES = _source_policies(
    (
        SourceClass.STRUCTURED_OFFICIAL,
        _EVIDENCE_DISPLAY_COMPARE_FILTER,
    ),
    (
        SourceClass.OFFICIAL_REGISTRATION,
        _EVIDENCE_DISPLAY_COMPARE_FILTER,
    ),
    (
        SourceClass.OFFICIAL_PACKAGING,
        _EVIDENCE_DISPLAY_COMPARE_FILTER,
    ),
    (SourceClass.MERCHANT_PARAMETER, _EVIDENCE_DISPLAY_COMPARE),
    (
        SourceClass.MERCHANT_TITLE_CLAIM,
        _EVIDENCE_DISPLAY_COMPARE,
    ),
    (SourceClass.OFFICIAL_DESCRIPTION, _EVIDENCE_DISPLAY),
    (SourceClass.MERCHANT_DESCRIPTION, _EVIDENCE_DISPLAY_COMPARE),
    (SourceClass.MERCHANT_DESCRIPTION_OCR, _EVIDENCE_DISPLAY_COMPARE),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (SourceClass.QA, _EVIDENCE_ONLY),
    (
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
        _EVIDENCE_ONLY,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_STRUCTURED_RANK_POLICIES = _source_policies(
    (
        SourceClass.STRUCTURED_OFFICIAL,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (
        SourceClass.OFFICIAL_REGISTRATION,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (
        SourceClass.OFFICIAL_PACKAGING,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (
        SourceClass.MERCHANT_PARAMETER,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_TITLE_CLAIM,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OFFICIAL_DESCRIPTION, _EVIDENCE_DISPLAY),
    (
        SourceClass.MERCHANT_DESCRIPTION,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_DESCRIPTION_OCR,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (SourceClass.QA, _EVIDENCE_ONLY),
    (
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
        _EVIDENCE_ONLY,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_EXPERIENTIAL_FILTER_RANK_POLICIES = _source_policies(
    (
        SourceClass.STRUCTURED_OFFICIAL,
        _EVIDENCE_DISPLAY_COMPARE_FILTER_RANK,
    ),
    (SourceClass.OFFICIAL_PACKAGING, _EVIDENCE_DISPLAY_COMPARE),
    (
        SourceClass.MERCHANT_PARAMETER,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_TITLE_CLAIM,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OFFICIAL_DESCRIPTION, _EVIDENCE_DISPLAY),
    (
        SourceClass.MERCHANT_DESCRIPTION,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_DESCRIPTION_OCR,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (
        SourceClass.APPROVED_CONSUMER_REVIEW,
        _EVIDENCE_DISPLAY,
    ),
    (SourceClass.CONSUMER_REVIEW, _EVIDENCE_DISPLAY),
    (SourceClass.QA, _EVIDENCE_ONLY),
    (
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
        _EVIDENCE_ONLY,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_EXPERIENTIAL_COMPARE_POLICIES = _source_policies(
    (SourceClass.STRUCTURED_OFFICIAL, _EVIDENCE_DISPLAY_COMPARE),
    (SourceClass.OFFICIAL_PACKAGING, _EVIDENCE_DISPLAY_COMPARE),
    (
        SourceClass.MERCHANT_PARAMETER,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_TITLE_CLAIM,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OFFICIAL_DESCRIPTION, _EVIDENCE_DISPLAY),
    (
        SourceClass.MERCHANT_DESCRIPTION,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_DESCRIPTION_OCR,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (
        SourceClass.APPROVED_CONSUMER_REVIEW,
        _EVIDENCE_DISPLAY,
    ),
    (SourceClass.CONSUMER_REVIEW, _EVIDENCE_DISPLAY),
    (SourceClass.QA, _EVIDENCE_ONLY),
    (
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
        _EVIDENCE_ONLY,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)
_FRAGRANCE_NOTE_POLICIES = _source_policies(
    (SourceClass.STRUCTURED_OFFICIAL, _EVIDENCE_DISPLAY_COMPARE),
    (SourceClass.OFFICIAL_PACKAGING, _EVIDENCE_DISPLAY_COMPARE),
    (
        SourceClass.MERCHANT_PARAMETER,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_TITLE_CLAIM,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OFFICIAL_DESCRIPTION, _EVIDENCE_DISPLAY),
    (
        SourceClass.MERCHANT_DESCRIPTION,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (
        SourceClass.MERCHANT_DESCRIPTION_OCR,
        _EVIDENCE_DISPLAY_COMPARE_RANK,
    ),
    (SourceClass.OCR_PACKAGING, _EVIDENCE_ONLY),
    (SourceClass.PACKAGE_OCR, _EVIDENCE_ONLY),
    (SourceClass.QA, _EVIDENCE_ONLY),
    (
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
        _EVIDENCE_ONLY,
    ),
    (SourceClass.UNKNOWN, _EVIDENCE_ONLY),
)

_FIELD_DEFINITIONS = (
    _field(
        key="product_identity",
        label="商品身份",
        aliases=("商品名称", "产品名称"),
        value_type="string",
        profiles=_ALL_PROFILES,
        source_policies=_CANONICAL_DISPLAY_COMPARE,
    ),
    _field(
        key="brand",
        label="品牌",
        aliases=("品牌名称", "商品品牌"),
        value_type="string",
        profiles=_ALL_PROFILES,
        source_policies=_CANONICAL_FILTER,
    ),
    _field(
        key="category",
        label="品类",
        aliases=("商品品类", "产品类别"),
        value_type="string",
        profiles=_ALL_PROFILES,
        source_policies=_CANONICAL_FILTER,
    ),
    _field(
        key="price",
        label="价格",
        aliases=("售价", "价位"),
        value_type="number",
        profiles=_ALL_PROFILES,
        source_policies=_CANONICAL_PRICE,
    ),
    _field(
        key="ingredients_present",
        label="确认含有成分",
        aliases=("含有成分", "已确认成分"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_INGREDIENT_POLICIES,
    ),
    _field(
        key="claimed_ingredients",
        label="商家宣称含有",
        aliases=("宣称含有成分", "商家成分卖点"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_MERCHANT_CLAIM_ONLY_POLICIES,
    ),
    _field(
        key="claimed_absences",
        label="商家宣称未添加",
        aliases=("宣称未添加", "商家未添加声明"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_MERCHANT_CLAIM_ONLY_POLICIES,
    ),
    _field(
        key="verified_absences",
        label="确认未添加",
        aliases=("已验证未添加", "未添加成分"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_VERIFIED_ABSENCE_POLICIES,
    ),
    _field(
        key="safety",
        label="安全信息",
        aliases=("安全提示", "注意事项"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_SAFETY_POLICIES,
    ),
    _field(
        key="usage",
        label="使用方法",
        aliases=("用法", "使用说明"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_USAGE_POLICIES,
    ),
    _field(
        key="net_content",
        label="净含量",
        aliases=("容量规格", "内容量"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="shelf_life",
        label="保质期",
        aliases=("货架期", "保存期限"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="origin",
        label="产地",
        aliases=("原产地", "生产地"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="target_audience",
        label="适用人群",
        aliases=("适用对象", "适用性别"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_CLAIM_RANK_POLICIES,
    ),
    _field(
        key="usage_context",
        label="使用场景",
        aliases=("适用场景", "适用场合", "适用季节"),
        value_type="string_list",
        profiles=_ALL_PROFILES,
        source_policies=_CLAIM_RANK_POLICIES,
    ),
    _field(
        key="application_area",
        label="适用部位",
        aliases=("使用部位", "涂抹部位"),
        value_type="string_list",
        profiles=_APPLICATION_AREA_PROFILES,
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="product_form",
        label="产品形态",
        aliases=("商品形态", "剂型形态"),
        value_type="string_list",
        profiles=_PRODUCT_FORM_PROFILES,
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="variant_option",
        label="规格选项",
        aliases=("颜色规格", "商品选项"),
        value_type="string_list",
        profiles=_VARIANT_OPTION_PROFILES,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="efficacy",
        label="功效",
        aliases=("护肤功效", "核心功效"),
        value_type="string_list",
        profiles=_EFFICACY_PROFILES,
        source_policies=_CLAIM_RANK_POLICIES,
    ),
    _field(
        key="suitable_skin",
        label="适用肤质",
        aliases=("适合肤质", "肤质适配"),
        value_type="string_list",
        profiles=_SUITABLE_SKIN_PROFILES,
        source_policies=_CLAIM_RANK_POLICIES,
    ),
    _field(
        key="skin_concern",
        label="肤质问题",
        aliases=("针对肤质问题", "肌肤问题"),
        value_type="string_list",
        profiles=_SKIN_CONCERN_PROFILES,
        source_policies=_CLAIM_RANK_POLICIES,
    ),
    _field(
        key="texture",
        label="质地",
        aliases=("产品质地", "使用肤感"),
        value_type="string_list",
        profiles=_TEXTURE_PROFILES,
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="fragrance_description",
        label="香味描述",
        aliases=("香味", "香型描述"),
        value_type="string_list",
        profiles=_FRAGRANCE_DESCRIPTION_PROFILES,
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="mechanism",
        label="作用机制",
        aliases=("功效机制", "作用原理"),
        value_type="string_list",
        profiles=_MECHANISM_PROFILES,
        source_policies=_CLAIM_COMPARE_POLICIES,
    ),
    _field(
        key="clinical_evidence",
        label="临床证据",
        aliases=("临床研究", "临床数据"),
        value_type="string_list",
        profiles=_SKINCARE,
        source_policies=_CLAIM_COMPARE_POLICIES,
    ),
    _field(
        key="mask_material",
        label="膜布材质",
        aliases=("面膜材质", "膜布类型"),
        value_type="string",
        profiles=_SKINCARE,
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="package_quantity",
        label="包装数量",
        aliases=("内装数量", "单盒数量"),
        value_type="string_list",
        profiles=_SKINCARE,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="spf_pa",
        label="防晒指数",
        aliases=("SPF和PA", "防护指数"),
        value_type="string",
        profiles=_SPF_PROFILES,
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="water_resistance",
        label="防水性",
        aliases=("防水能力", "耐水性"),
        value_type="string",
        profiles=_SUNCARE,
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="friction_resistance",
        label="耐摩擦性",
        aliases=("耐摩擦", "抗摩擦表现"),
        value_type="string",
        profiles=_SUNCARE,
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="cleansing_requirement",
        label="清洁要求",
        aliases=("防晒清洁方式", "防晒卸除方式"),
        value_type="string",
        profiles=_SUNCARE,
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="reapplication",
        label="补涂建议",
        aliases=("补涂", "补涂频率"),
        value_type="string",
        profiles=_SUNCARE,
        source_policies=_USAGE_POLICIES,
    ),
    _field(
        key="film_speed",
        label="成膜速度",
        aliases=("成膜快慢", "成膜表现"),
        value_type="string",
        profiles=_SUNCARE,
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="sun_protection_spectrum",
        label="防晒光谱",
        aliases=("防护光谱", "光谱范围"),
        value_type="string",
        profiles=_SUNCARE,
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="tone_effect",
        label="修色效果",
        aliases=("修色提亮", "提亮效果"),
        value_type="string",
        profiles=_SUNCARE,
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="sun_protection_claim",
        label="底妆防晒",
        aliases=("是否含防晒", "防晒能力"),
        value_type="string",
        profiles=frozenset({CategoryProfile.BASE_MAKEUP}),
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="shade",
        label="色号",
        aliases=("颜色编号", "妆容色彩"),
        value_type="string_list",
        profiles=_BASE_AND_COLOR,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="color_count",
        label="颜色数量",
        aliases=("颜色数", "色彩数量"),
        value_type="string",
        profiles=frozenset({CategoryProfile.COLOR_MAKEUP}),
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="color_family",
        label="色系",
        aliases=("色彩家族", "颜色家族"),
        value_type="string_list",
        profiles=frozenset({CategoryProfile.COLOR_MAKEUP}),
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="color_payoff",
        label="显色度",
        aliases=("显色表现", "上色表现"),
        value_type="string",
        profiles=frozenset({CategoryProfile.COLOR_MAKEUP}),
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="makeup_effect",
        label="妆容效果",
        aliases=("妆容表现", "上脸效果"),
        value_type="string_list",
        profiles=_BASE_AND_COLOR,
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="makeup_style",
        label="妆容风格",
        aliases=("适合妆容", "妆容风格适配"),
        value_type="string_list",
        profiles=frozenset({CategoryProfile.COLOR_MAKEUP}),
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="finish",
        label="妆效",
        aliases=("妆面效果", "上妆效果"),
        value_type="string_list",
        profiles=_FINISH_PROFILES,
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="coverage",
        label="遮瑕力",
        aliases=("遮盖力", "遮盖程度"),
        value_type="string",
        profiles=frozenset({CategoryProfile.BASE_MAKEUP}),
        source_policies=_EXPERIENTIAL_FILTER_RANK_POLICIES,
    ),
    _field(
        key="longevity",
        label="持久度",
        aliases=("持妆时长", "留香时长"),
        value_type="string",
        profiles=_LONGEVITY_PROFILES,
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
    _field(
        key="cleansing_form",
        label="清洁形态",
        aliases=("洁面形态", "卸妆形态"),
        value_type="string",
        profiles=_CLEANSER,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="cleansing_power",
        label="清洁力",
        aliases=("卸妆力", "清洁能力"),
        value_type="string",
        profiles=_CLEANSER,
        source_policies=_EXPERIENTIAL_FILTER_RANK_POLICIES,
    ),
    _field(
        key="surfactant_type",
        label="表活类型",
        aliases=("表面活性剂类型", "清洁体系"),
        value_type="string_list",
        profiles=_CLEANSER,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="rinse_behavior",
        label="冲洗表现",
        aliases=("洗后感", "冲洗感受"),
        value_type="string",
        profiles=_CLEANSER,
        source_policies=_EXPERIENTIAL_COMPARE_POLICIES,
    ),
    _field(
        key="double_cleanse",
        label="二次清洁",
        aliases=("是否需要二次清洁", "是否需要复洗"),
        value_type="boolean",
        profiles=_CLEANSER,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="concentration",
        label="香水浓度类型",
        aliases=("香水浓度", "浓度类型"),
        value_type="string",
        profiles=_FRAGRANCE,
        source_policies=_STRUCTURED_RANK_POLICIES,
    ),
    _field(
        key="fragrance_family",
        label="香调家族",
        aliases=("香调", "香型家族"),
        value_type="string_list",
        profiles=_FRAGRANCE,
        source_policies=_STRUCTURED_SPEC_POLICIES,
    ),
    _field(
        key="top_notes",
        label="前调",
        aliases=("头香", "前段香调"),
        value_type="string_list",
        profiles=_FRAGRANCE,
        source_policies=_FRAGRANCE_NOTE_POLICIES,
    ),
    _field(
        key="heart_notes",
        label="中调",
        aliases=("心调", "中段香调"),
        value_type="string_list",
        profiles=_FRAGRANCE,
        source_policies=_FRAGRANCE_NOTE_POLICIES,
    ),
    _field(
        key="base_notes",
        label="后调",
        aliases=("基调", "尾调"),
        value_type="string_list",
        profiles=_FRAGRANCE,
        source_policies=_FRAGRANCE_NOTE_POLICIES,
    ),
    _field(
        key="sillage",
        label="扩香度",
        aliases=("扩散度", "香气扩散"),
        value_type="string",
        profiles=_FRAGRANCE,
        source_policies=_EXPERIENTIAL_RANK_POLICIES,
    ),
)

_CATEGORY_FIELD_REGISTRY = CategoryFieldRegistry(
    definitions=_FIELD_DEFINITIONS
)


def category_field_registry() -> CategoryFieldRegistry:
    return _CATEGORY_FIELD_REGISTRY
