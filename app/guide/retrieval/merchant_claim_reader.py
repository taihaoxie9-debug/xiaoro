from __future__ import annotations

from collections import defaultdict

from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    CategoryFactValue,
    CategoryFieldDefinition,
    CategoryFieldRegistry,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.merchant_claim_assets import (
    MerchantClaim,
    MerchantClaimAssets,
)


class MerchantClaimReader:
    def __init__(self, assets: MerchantClaimAssets) -> None:
        by_product: dict[int, list[MerchantClaim]] = defaultdict(list)
        for claim in assets.claims:
            by_product[claim.product_id].append(claim)
        self._by_product = {
            product_id: tuple(
                sorted(claims, key=lambda item: item.claim_id)
            )
            for product_id, claims in by_product.items()
        }
        self.manifest = assets.manifest

    def read(self, *, product_id: int) -> tuple[MerchantClaim, ...]:
        if (
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id <= 0
        ):
            raise TypeError("product_id must be a positive integer")
        return tuple(self._by_product.get(product_id, ()))


class ClaimAugmentedCategoryFactReader:
    def __init__(
        self,
        *,
        base,
        claims: MerchantClaimReader,
        field_registry: CategoryFieldRegistry,
    ) -> None:
        self._base = base
        self._claims = claims
        self._definitions = {
            item.key: item for item in field_registry.definitions
        }

    @property
    def claims(self) -> MerchantClaimReader:
        return self._claims

    @property
    def base(self):
        return self._base

    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[AuthorizedCategoryFact, ...]:
        base_facts = self._base.read(
            product_id=product_id,
            profile=profile,
        )
        claims_by_field: dict[str, list[MerchantClaim]] = defaultdict(list)
        for claim in self._claims.read(product_id=product_id):
            if (
                claim.claim_scope == "ordinary"
                and "soft_rank" in claim.capabilities
                and claim.category_profile is profile
                and claim.field_key in self._definitions
            ):
                claims_by_field[claim.field_key].append(claim)
        return tuple(
            self._augment(
                fact,
                claims_by_field.get(fact.field_key, ()),
            )
            for fact in base_facts
        )

    def _augment(
        self,
        fact: AuthorizedCategoryFact,
        claims: list[MerchantClaim] | tuple[()],
    ) -> AuthorizedCategoryFact:
        if not claims or fact.resolved_state == "conflict":
            return fact
        definition = self._definitions[fact.field_key]
        values = _merged_values(fact, claims, definition)
        if values is None:
            return fact
        include_base = fact.resolved_state == "known"
        source_classes = tuple(
            sorted(
                {
                    *(fact.source_classes if include_base else ()),
                    SourceClass.MERCHANT_DESCRIPTION_OCR,
                },
                key=lambda item: item.value,
            )
        )
        source_refs = tuple(
            sorted(
                {
                    *(fact.source_refs if include_base else ()),
                    *(claim.source_locator for claim in claims),
                }
            )
        )
        claim_capabilities = set(claims[0].capabilities)
        for claim in claims[1:]:
            claim_capabilities.intersection_update(claim.capabilities)
        capabilities = claim_capabilities
        if include_base:
            capabilities.intersection_update(fact.capabilities)
        return AuthorizedCategoryFact(
            category_profile=fact.category_profile,
            field_key=fact.field_key,
            value=values,
            resolved_state="known",
            source_classes=source_classes,
            source_refs=source_refs,
            capabilities=frozenset(capabilities),
        )


def _merged_values(
    fact: AuthorizedCategoryFact,
    claims: list[MerchantClaim] | tuple[()],
    definition: CategoryFieldDefinition,
) -> CategoryFactValue | None:
    claim_values = sorted({claim.normalized_value for claim in claims})
    if definition.value_type == "string_list":
        existing: tuple[str, ...] = ()
        if fact.resolved_state == "known":
            if isinstance(fact.value, str):
                existing = (fact.value,)
            elif isinstance(fact.value, tuple):
                existing = fact.value
            else:
                return None
        return tuple(sorted({*existing, *claim_values}))
    if definition.value_type == "string":
        if fact.resolved_state == "known":
            return fact.value
        return claim_values[0] if len(claim_values) == 1 else None
    return None


__all__ = [
    "ClaimAugmentedCategoryFactReader",
    "MerchantClaimReader",
]
