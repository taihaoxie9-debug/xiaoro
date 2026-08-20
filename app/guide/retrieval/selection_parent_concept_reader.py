from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from app.guide.retrieval.selection_fact_contracts import SelectionFact
from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptFact,
    SelectionConceptProjection,
)


class SelectionParentConceptReader:
    def __init__(
        self,
        projections: Sequence[SelectionConceptProjection],
    ) -> None:
        index: dict[
            tuple[str, str, str],
            SelectionConceptProjection,
        ] = {}
        for projection in projections:
            if not isinstance(
                projection,
                SelectionConceptProjection,
            ):
                raise TypeError(
                    "projections must contain "
                    "SelectionConceptProjection"
                )
            key = (
                projection.profile.value,
                projection.field_key,
                projection.normalized_value.casefold(),
            )
            if key in index:
                raise ValueError("duplicate concept projection source")
            index[key] = projection
        self._index = index

    def project(
        self,
        facts: Sequence[SelectionFact],
    ) -> tuple[SelectionConceptFact, ...]:
        grouped: dict[str, list[
            tuple[SelectionFact, SelectionConceptProjection]
        ]] = defaultdict(list)
        product_ids: set[int] = set()
        for fact in facts:
            if not isinstance(fact, SelectionFact):
                raise TypeError(
                    "facts must contain SelectionFact instances"
                )
            product_ids.add(fact.product_id)
            if (
                fact.subject_scope != "exact_product"
                or fact.variant_scope is not None
                or fact.rank_strength is None
                or "soft_rank" not in fact.capabilities
            ):
                continue
            projection = self._index.get(
                (
                    fact.category_profile.value,
                    fact.field_key,
                    fact.normalized_value.casefold(),
                )
            )
            if projection is None:
                continue
            _validate_source_binding(fact, projection)
            grouped[projection.concept_id].append(
                (fact, projection)
            )
        if len(product_ids) > 1:
            raise ValueError(
                "concept projection accepts one product at a time"
            )

        projected: list[SelectionConceptFact] = []
        for concept_id, rows in sorted(grouped.items()):
            facts_for_concept = tuple(row[0] for row in rows)
            projections = tuple(row[1] for row in rows)
            stances = {item.stance for item in projections}
            if len(stances) != 1:
                raise ValueError(
                    "conflicting concept stance for one product concept"
                )
            comparison_keys = {
                (item.comparability, item.order_value)
                for item in projections
            }
            if len(comparison_keys) != 1:
                raise ValueError(
                    "conflicting concept comparability"
                )
            comparability, order_value = next(
                iter(comparison_keys)
            )
            first = facts_for_concept[0]
            projected.append(
                SelectionConceptFact(
                    product_id=first.product_id,
                    profile=first.category_profile,
                    field_key=first.field_key,
                    concept_id=concept_id,
                    stance=next(iter(stances)),
                    comparability=comparability,
                    order_value=order_value,
                    rank_strength=max(
                        fact.rank_strength or 0
                        for fact in facts_for_concept
                    ),
                    safety_roles={
                        fact.safety_role
                        for fact in facts_for_concept
                    },
                    source_values=tuple(
                        sorted(
                            {
                                fact.normalized_value
                                for fact in facts_for_concept
                            },
                            key=str.casefold,
                        )
                    ),
                    source_refs=tuple(sorted({
                        reference
                        for fact in facts_for_concept
                        for reference in fact.source_refs
                    })),
                    attributions={
                        attribution
                        for fact in facts_for_concept
                        for attribution in fact.attributions
                    },
                )
            )
        return tuple(projected)


def _validate_source_binding(
    fact: SelectionFact,
    projection: SelectionConceptProjection,
) -> None:
    if fact.product_id not in projection.product_ids:
        raise ValueError("concept projection product drift")
    if fact.rank_strength not in projection.rank_strengths:
        raise ValueError("concept projection strength drift")
    if not set(fact.source_refs).issubset(projection.source_refs):
        raise ValueError("concept projection source ref drift")


__all__ = ["SelectionParentConceptReader"]
