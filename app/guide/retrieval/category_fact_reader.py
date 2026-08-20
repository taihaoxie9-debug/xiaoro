from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    CategoryFieldDefinition,
    CategoryFieldRegistry,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile

if TYPE_CHECKING:
    from app.guide.retrieval.category_fact_assets import (
        ApprovedCategoryFact,
        CategoryFactAssets,
        CategoryFactManifest,
    )


_CANONICAL_CORE_FIELDS = frozenset(
    {"product_identity", "brand", "category", "price"}
)


class CategoryFactReaderIntegrityError(RuntimeError):
    pass


class CategoryFactProfileMismatchError(LookupError):
    pass


class CategoryFactReader:
    __slots__ = (
        "_facts_by_product_field",
        "_field_registry",
        "_product_profiles",
    )

    def __init__(
        self,
        *,
        assets: CategoryFactAssets,
        field_registry: CategoryFieldRegistry,
    ) -> None:
        manifest, facts = _validate_assets(
            assets,
            field_registry=field_registry,
        )
        self._field_registry = field_registry
        product_profiles: dict[int, CategoryProfile] = {}
        facts_by_product_field: dict[
            tuple[int, str],
            list[ApprovedCategoryFact],
        ] = defaultdict(list)

        for binding in manifest.pilot_bindings:
            _bind_product_profile(
                product_profiles,
                product_id=binding.product_id,
                profile=binding.category_profile,
            )
        for fact in facts:
            _validate_asset_fact(fact, field_registry)
            _bind_product_profile(
                product_profiles,
                product_id=fact.product_id,
                profile=fact.category_profile,
            )
            facts_by_product_field[
                (fact.product_id, fact.field_key)
            ].append(fact)

        self._product_profiles = product_profiles
        self._facts_by_product_field = {
            key: tuple(sorted(value, key=lambda item: item.fact_id))
            for key, value in facts_by_product_field.items()
        }

    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[AuthorizedCategoryFact, ...]:
        _validate_request(product_id=product_id, profile=profile)
        expected_profile = self._product_profiles.get(product_id)
        if (
            expected_profile is not None
            and expected_profile is not profile
        ):
            raise CategoryFactProfileMismatchError(
                "category fact product/profile mismatch: "
                f"product={product_id}, expected={expected_profile.value}, "
                f"requested={profile.value}"
            )

        return tuple(
            self._resolve_field(
                product_id=product_id,
                category_profile=profile,
                definition=definition,
            )
            for definition in _projected_definitions(
                self._field_registry,
                profile,
            )
        )

    def _resolve_field(
        self,
        *,
        product_id: int,
        category_profile: CategoryProfile,
        definition: CategoryFieldDefinition,
    ) -> AuthorizedCategoryFact:
        facts = self._facts_by_product_field.get(
            (product_id, definition.key),
            (),
        )
        if not facts:
            return _unknown_fact(
                category_profile=category_profile,
                field_key=definition.key,
            )

        policies = {
            policy.source_class: policy
            for policy in definition.source_policies
        }
        for fact in facts:
            if fact.source_class not in policies:
                raise CategoryFactReaderIntegrityError(
                    "category fact source is not authorized for field: "
                    f"{definition.key}.{fact.source_class.value}"
                )

        source_classes = tuple(
            sorted(
                {fact.source_class for fact in facts},
                key=lambda item: item.value,
            )
        )
        source_refs = tuple(
            sorted(
                {
                    reference
                    for fact in facts
                    for reference in fact.source_refs
                }
            )
        )
        values: dict[str, object] = {}
        for fact in facts:
            key = json.dumps(
                fact.value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            values[key] = fact.value
        if len(values) != 1:
            return AuthorizedCategoryFact(
                category_profile=category_profile,
                field_key=definition.key,
                value=None,
                resolved_state="conflict",
                source_classes=source_classes,
                source_refs=source_refs,
                capabilities=frozenset({"evidence"}),
            )

        capabilities = set(
            policies[facts[0].source_class].capabilities
        )
        if facts[0].capability_limit is not None:
            capabilities.intersection_update(
                facts[0].capability_limit
            )
        for fact in facts[1:]:
            capabilities.intersection_update(
                policies[fact.source_class].capabilities
            )
            if fact.capability_limit is not None:
                capabilities.intersection_update(
                    fact.capability_limit
                )
        value = next(iter(values.values()))
        if definition.value_type == "string_list":
            value = tuple(value)
        return AuthorizedCategoryFact(
            category_profile=category_profile,
            field_key=definition.key,
            value=value,
            resolved_state="known",
            source_classes=source_classes,
            source_refs=source_refs,
            capabilities=frozenset(capabilities),
        )


class EmptyCategoryFactReader:
    __slots__ = ("_field_registry",)

    def __init__(self, field_registry: CategoryFieldRegistry) -> None:
        self._field_registry = field_registry

    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[AuthorizedCategoryFact, ...]:
        _validate_request(product_id=product_id, profile=profile)
        return tuple(
            _unknown_fact(
                category_profile=profile,
                field_key=definition.key,
            )
            for definition in _projected_definitions(
                self._field_registry,
                profile,
            )
        )


def _projected_definitions(
    field_registry: CategoryFieldRegistry,
    profile: CategoryProfile,
) -> tuple[CategoryFieldDefinition, ...]:
    return tuple(
        sorted(
            (
                definition
                for definition in field_registry.for_profile(profile)
                if definition.key not in _CANONICAL_CORE_FIELDS
            ),
            key=lambda definition: definition.key,
        )
    )


def _unknown_fact(
    *,
    category_profile: CategoryProfile,
    field_key: str,
) -> AuthorizedCategoryFact:
    return AuthorizedCategoryFact(
        category_profile=category_profile,
        field_key=field_key,
        value=None,
        resolved_state="unknown",
        source_classes=(SourceClass.UNKNOWN,),
        source_refs=(),
        capabilities=frozenset({"evidence"}),
    )


def _bind_product_profile(
    product_profiles: dict[int, CategoryProfile],
    *,
    product_id: int,
    profile: CategoryProfile,
) -> None:
    previous = product_profiles.setdefault(product_id, profile)
    if previous is not profile:
        raise CategoryFactReaderIntegrityError(
            "conflicting category fact product profiles: "
            f"product={product_id}, first={previous.value}, "
            f"second={profile.value}"
        )


def _validate_asset_fact(
    fact: ApprovedCategoryFact,
    field_registry: CategoryFieldRegistry,
) -> None:
    definitions = {
        definition.key: definition
        for definition in field_registry.for_profile(
            fact.category_profile
        )
    }
    definition = definitions.get(fact.field_key)
    if definition is None:
        raise CategoryFactReaderIntegrityError(
            "category fact field is not applicable to profile: "
            f"{fact.category_profile.value}.{fact.field_key}"
        )
    if fact.field_key in _CANONICAL_CORE_FIELDS:
        raise CategoryFactReaderIntegrityError(
            "canonical core field is forbidden in category fact sidecar: "
            f"{fact.field_key}"
        )
    policies = {
        policy.source_class for policy in definition.source_policies
    }
    if (
        fact.source_class
        in {SourceClass.CANONICAL_CORE, SourceClass.UNKNOWN}
        or fact.source_class not in policies
    ):
        raise CategoryFactReaderIntegrityError(
            "category fact source is not authorized for field: "
            f"{fact.field_key}.{fact.source_class.value}"
        )
    _validate_fact_value(
        value=fact.value,
        value_type=definition.value_type,
        field_key=fact.field_key,
    )


def _validate_assets(
    assets: object,
    *,
    field_registry: CategoryFieldRegistry,
) -> tuple[CategoryFactManifest, tuple[ApprovedCategoryFact, ...]]:
    from app.guide.retrieval.category_fact_assets import CategoryFactAssets

    if not isinstance(field_registry, CategoryFieldRegistry):
        raise CategoryFactReaderIntegrityError(
            "field_registry must be a CategoryFieldRegistry"
        )
    if not isinstance(assets, CategoryFactAssets):
        raise CategoryFactReaderIntegrityError(
            "assets must be a CategoryFactAssets instance"
        )
    manifest = _revalidate_manifest(assets.manifest)
    if type(assets.facts) is not tuple:
        raise CategoryFactReaderIntegrityError(
            "CategoryFactAssets facts must be a strict tuple"
        )
    if (
        type(manifest.fact_count) is not int
        or manifest.fact_count < 0
        or manifest.fact_count != len(assets.facts)
    ):
        raise CategoryFactReaderIntegrityError(
            "category fact manifest fact_count must equal facts length"
        )
    facts = tuple(
        _revalidate_approved_fact(fact) for fact in assets.facts
    )
    return manifest, facts


def _revalidate_manifest(manifest: object) -> CategoryFactManifest:
    from app.guide.retrieval.category_fact_assets import (
        CategoryFactManifest,
        PilotBinding,
    )

    if not isinstance(manifest, CategoryFactManifest):
        raise CategoryFactReaderIntegrityError(
            "manifest must be a CategoryFactManifest instance"
        )
    if type(manifest.fact_count) is not int:
        raise CategoryFactReaderIntegrityError(
            "category fact manifest fact_count must be an integer"
        )
    if type(manifest.pilot_bindings) is not tuple or any(
        not isinstance(binding, PilotBinding)
        for binding in manifest.pilot_bindings
    ):
        raise CategoryFactReaderIntegrityError(
            "invalid CategoryFactManifest pilot bindings"
        )
    payload = {
        field_name: getattr(manifest, field_name)
        for field_name in CategoryFactManifest.model_fields
    }
    try:
        return CategoryFactManifest.model_validate(payload)
    except (AttributeError, TypeError, ValidationError, ValueError) as exc:
        raise CategoryFactReaderIntegrityError(
            "invalid CategoryFactManifest"
        ) from exc


def _revalidate_approved_fact(fact: object) -> ApprovedCategoryFact:
    from app.guide.retrieval.category_fact_assets import ApprovedCategoryFact

    if not isinstance(fact, ApprovedCategoryFact):
        raise CategoryFactReaderIntegrityError(
            "fact must be an ApprovedCategoryFact instance"
        )
    if getattr(fact, "evidence_status", None) != "approved_fact":
        raise CategoryFactReaderIntegrityError(
            "approved category fact evidence_status must be approved_fact"
        )
    if (
        type(getattr(fact, "product_id", None)) is not int
        or not isinstance(
            getattr(fact, "category_profile", None),
            CategoryProfile,
        )
        or type(getattr(fact, "field_key", None)) is not str
        or not isinstance(
            getattr(fact, "source_class", None),
            SourceClass,
        )
        or type(getattr(fact, "source_refs", None)) is not tuple
        or any(
            type(reference) is not str
            for reference in getattr(fact, "source_refs", ())
        )
    ):
        raise CategoryFactReaderIntegrityError(
            "invalid approved category fact runtime types"
        )
    try:
        payload = {
            field_name: getattr(fact, field_name)
            for field_name in ApprovedCategoryFact.model_fields
            if hasattr(fact, field_name)
        }
        validated = ApprovedCategoryFact.model_validate(payload)
    except (AttributeError, TypeError, ValidationError, ValueError) as exc:
        raise CategoryFactReaderIntegrityError(
            "invalid approved category fact"
        ) from exc
    if validated.source_refs != tuple(
        sorted(set(validated.source_refs))
    ):
        raise CategoryFactReaderIntegrityError(
            "invalid approved category fact source_refs"
        )
    return validated


def _validate_fact_value(
    *,
    value: object,
    value_type: str,
    field_key: str,
) -> None:
    valid = False
    if value_type == "string":
        valid = (
            type(value) is str
            and bool(value)
            and value == value.strip()
        )
    elif value_type == "string_list":
        valid = (
            type(value) is list
            and bool(value)
            and all(
                type(item) is str
                and bool(item)
                and item == item.strip()
                for item in value
            )
        )
    elif value_type == "number":
        valid = type(value) in {int, float} and (
            type(value) is int or math.isfinite(value)
        )
    elif value_type == "boolean":
        valid = type(value) is bool
    if not valid:
        raise CategoryFactReaderIntegrityError(
            "invalid approved category fact: "
            f"value type mismatch for field {field_key}"
        )


def _validate_request(
    *,
    product_id: int,
    profile: CategoryProfile,
) -> None:
    if type(product_id) is not int or product_id <= 0:
        raise ValueError("category fact product_id must be a positive integer")
    if not isinstance(profile, CategoryProfile):
        raise TypeError("category fact profile must be CategoryProfile")
