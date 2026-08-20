from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.understanding.image_contracts import CanonicalIdentity


_UNUSABLE_IDENTITY_VALUES = frozenset({"", "无"})


class CanonicalIdentityCatalog:
    def __init__(self, reader: CanonicalProductReader) -> None:
        self._reader = reader

    @property
    def product_ids(self) -> frozenset[int]:
        return self._reader.product_ids

    def get_identity(
        self,
        product_id: int,
    ) -> CanonicalIdentity | None:
        if product_id not in self._reader.product_ids:
            return None
        product = self._reader.get(product_id)
        brand = _known_identity_value(product.fields.get("brand"))
        product_name = _known_identity_value(
            product.fields.get("product_identity")
        )
        if brand is None and product_name is None:
            return None
        return CanonicalIdentity(
            product_id=product_id,
            brand=brand,
            product_name=product_name,
        )


def _known_identity_value(field) -> str | None:
    if field is None or field.resolved_state != "known":
        return None
    if not isinstance(field.value, str):
        return None
    value = field.value.strip()
    if value in _UNUSABLE_IDENTITY_VALUES:
        return None
    return value
