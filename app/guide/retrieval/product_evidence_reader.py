from __future__ import annotations

from collections import defaultdict

from app.guide.retrieval.product_evidence_assets import (
    ProductEvidenceAssets,
    ProductEvidenceBlock,
)


class ProductEvidenceReader:
    def __init__(self, assets: ProductEvidenceAssets) -> None:
        if not isinstance(assets, ProductEvidenceAssets):
            raise TypeError("assets must be ProductEvidenceAssets")
        by_product: dict[int, list[ProductEvidenceBlock]] = defaultdict(list)
        for block in assets.evidence:
            by_product[block.product_id].append(block)
        self._by_product = {
            product_id: tuple(
                sorted(blocks, key=lambda item: item.evidence_id)
            )
            for product_id, blocks in by_product.items()
        }
        self.manifest = assets.manifest

    def read(self, *, product_id: int) -> tuple[ProductEvidenceBlock, ...]:
        if (
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id <= 0
        ):
            raise TypeError("product_id must be a positive integer")
        return tuple(self._by_product.get(product_id, ()))

    def read_answerable(
        self,
        *,
        product_id: int,
    ) -> tuple[ProductEvidenceBlock, ...]:
        return tuple(
            block
            for block in self.read(product_id=product_id)
            if (
                block.review_status == "accepted"
                and "answer" in block.allowed_uses
            )
        )


__all__ = ["ProductEvidenceReader"]
