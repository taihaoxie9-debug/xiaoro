from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Mapping

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.adapters.catalog.seed_product_assets import SeedProductAsset
from app.guide.decision.contracts import (
    DecisionProductFacts,
    FactState,
)
from app.guide.presentation.contracts import ProductCardFacts
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_fact_reader import (
    EmptyCategoryFactReader,
)
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from app.guide.retrieval.card_specification import (
    resolve_card_specification,
)
from app.guide.retrieval.ports import CategoryFactPort, CategoryRecord
from app.guide.retrieval.product_display_assets import (
    ProductDisplayBindingReader,
)
from app.guide.retrieval.scenario_contracts import (
    ScenarioEvidenceRecord,
    ScenarioEvidenceRequirement,
)
from app.guide.retrieval.scenario_evidence import (
    project_scenario_evidence,
)
from app.guide.retrieval.selection_fact_reader import SelectionFactReader

_UNUSABLE_NAMES = frozenset({"", "无"})


class CategoryProfileUnavailableError(LookupError):
    pass


class CanonicalGuideCatalog:
    def __init__(
        self,
        reader: CanonicalProductReader,
        *,
        product_assets: Mapping[int, SeedProductAsset] | None = None,
        category_fact_port: CategoryFactPort | None = None,
        selection_fact_port: SelectionFactReader | None = None,
        product_display_bindings: (
            ProductDisplayBindingReader | None
        ) = None,
    ) -> None:
        self._reader = reader
        self._product_assets = product_assets or {}
        self._category_fact_port = (
            category_fact_port
            if category_fact_port is not None
            else EmptyCategoryFactReader(category_field_registry())
        )
        self._selection_fact_port = selection_fact_port
        self._product_display_bindings = product_display_bindings

    def iter_category_records(self) -> Iterable[CategoryRecord]:
        for product_id in sorted(self._reader.product_ids):
            field = self._reader.get(product_id).fields.get("category")
            yield CategoryRecord(
                product_id=product_id,
                value=field.value if field is not None else None,
                state=(
                    field.resolved_state
                    if field is not None
                    else "unknown"
                ),
            )

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        product = self._reader.get(product_id)
        category_profile = _category_profile(product)
        category_fields = self._category_fact_port.read(
            product_id=product_id,
            profile=category_profile,
        )
        selection_facts = (
            self._selection_fact_port.read(
                product_id=product_id,
                profile=category_profile,
            )
            if self._selection_fact_port is not None
            else ()
        )
        price_field = product.fields.get("price")
        price, price_state = _decimal_value(price_field)
        efficacy, efficacy_state = _tuple_value(
            product.fields.get("efficacy")
        )
        skin_field = product.fields.get("suitable_skin")
        skin, skin_state = _tuple_value(skin_field)
        present, present_state = _tuple_value(
            product.fields.get("ingredients_present")
        )
        absent, absent_state = _tuple_value(
            product.fields.get("verified_absences")
        )
        return DecisionProductFacts(
            product_id=product_id,
            category_profile=category_profile,
            category_fields=category_fields,
            price=price,
            price_state=price_state,
            efficacy=efficacy,
            efficacy_state=efficacy_state,
            suitable_skin=skin,
            suitable_skin_state=skin_state,
            ingredients_present=present,
            ingredients_present_state=present_state,
            verified_absences=absent,
            verified_absences_state=absent_state,
            price_source_refs=(
                tuple(price_field.source_refs)
                if price_field is not None
                else ()
            ),
            suitable_skin_source_refs=(
                tuple(skin_field.source_refs)
                if skin_field is not None
                else ()
            ),
            selection_facts=selection_facts,
        )

    def get_scenario_evidence(
        self,
        product_id: int,
        requirements: list[ScenarioEvidenceRequirement],
    ) -> list[ScenarioEvidenceRecord]:
        return project_scenario_evidence(
            self._reader.get(product_id),
            requirements,
        )

    def get_presentation_facts(
        self,
        product_id: int,
        *,
        variant_scope: str | None = None,
    ) -> ProductCardFacts:
        product = self._reader.get(product_id)
        category_profile = _category_profile(product)
        category_fields = self._category_fact_port.read(
            product_id=product_id,
            profile=category_profile,
        )
        selection_facts = (
            self._selection_fact_port.read(
                product_id=product_id,
                profile=category_profile,
            )
            if self._selection_fact_port is not None
            else ()
        )
        name_field = product.fields.get("product_identity")
        brand_field = product.fields.get("brand")
        category_field = product.fields.get("category")
        price, price_state = _decimal_value(product.fields.get("price"))
        name = (
            str(name_field.value)
            if name_field is not None
            and name_field.resolved_state == "known"
            else None
        )
        brand = (
            str(brand_field.value)
            if brand_field is not None
            and brand_field.resolved_state == "known"
            else None
        )
        category = (
            str(category_field.value)
            if category_field is not None
            and category_field.resolved_state == "known"
            else None
        )
        efficacy, efficacy_state = _tuple_value(
            product.fields.get("efficacy")
        )
        skin_field = product.fields.get("suitable_skin")
        skin, skin_state = _tuple_value(skin_field)
        present, present_state = _tuple_value(
            product.fields.get("ingredients_present")
        )
        warnings: list[str] = []
        if name is None or name.strip() in _UNUSABLE_NAMES:
            warnings.append("product_identity_unusable")
        if brand is None:
            warnings.append("brand_missing")
        if price_state is not FactState.KNOWN:
            warnings.append("price_missing")
        asset = self._product_assets.get(product_id)
        if asset is None:
            warnings.append("image_missing")
        display_binding = (
            self._product_display_bindings.get_optional(product_id)
            if self._product_display_bindings is not None
            else None
        )
        public_name = (
            display_binding.display_name
            if display_binding is not None
            else name
        )
        return ProductCardFacts(
            product_id=product_id,
            category_profile=category_profile,
            category_fields=category_fields,
            price_specification_alignment=(
                display_binding.price_specification_alignment
                if display_binding is not None
                else "unresolved"
            ),
            variant_scope=variant_scope,
            specification=(
                self._product_display_bindings.price_bound_specification(
                    product_id
                )
                if display_binding is not None
                and self._product_display_bindings is not None
                else resolve_card_specification(
                    selection_facts,
                    variant_scope=variant_scope,
                )
            ),
            display_name=(
                display_binding.display_name
                if display_binding is not None
                else name
            ),
            name=public_name,
            brand=brand,
            category=category,
            price=price,
            efficacy=efficacy,
            efficacy_state=efficacy_state.value,
            suitable_skin=skin,
            suitable_skin_state=skin_state.value,
            ingredients_present=present,
            ingredients_present_state=present_state.value,
            image_url=asset.image_url if asset is not None else None,
            detail_url=asset.detail_url if asset is not None else None,
            platform=asset.platform if asset is not None else None,
            image_source_sha256=(
                asset.source_image_sha256 if asset is not None else None
            ),
            fact_warnings=warnings,
        )


def _category_profile(product) -> CategoryProfile:
    field = product.fields.get("category")
    if (
        field is None
        or field.resolved_state != "known"
        or not isinstance(field.value, str)
    ):
        raise CategoryProfileUnavailableError(
            f"canonical category is unavailable for product {product.product_id}"
        )
    try:
        return category_profile_for(field.value)
    except KeyError as exc:
        raise CategoryProfileUnavailableError(
            "canonical category is unmapped for product "
            f"{product.product_id}: {field.value}"
        ) from exc


def _fact_state(field) -> FactState:
    if field is None:
        return FactState.UNKNOWN
    try:
        return FactState(field.resolved_state)
    except ValueError:
        return FactState.CONFLICT


def _decimal_value(field) -> tuple[Decimal | None, FactState]:
    state = _fact_state(field)
    if state is not FactState.KNOWN:
        return None, state
    value = field.value
    if isinstance(value, bool):
        return None, FactState.CONFLICT
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, FactState.CONFLICT
    if not decimal_value.is_finite() or decimal_value < 0:
        return None, FactState.CONFLICT
    return decimal_value, FactState.KNOWN


def _tuple_value(field) -> tuple[tuple[str, ...] | None, FactState]:
    state = _fact_state(field)
    if state is not FactState.KNOWN:
        return None, state
    value = field.value
    if isinstance(value, str) and value.strip():
        return (value,), FactState.KNOWN
    if isinstance(value, list) and value and all(
        isinstance(item, str) for item in value
    ):
        return tuple(value), FactState.KNOWN
    return None, FactState.CONFLICT
