from __future__ import annotations

import re

from app.guide.retrieval.category_profiles import category_profile_for
from app.guide.understanding.contracts import EfficacyTarget
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
)


_MACHINE_VALUE = re.compile(r"[a-z0-9_+./ -]+")
_CLOSED_EFFICACY_VALUES = frozenset(
    target.value for target in EfficacyTarget
)


def test_soft_selection_concepts_have_user_matchable_identities(
    tmp_path,
) -> None:
    runtime = build_consultation_vertical_runtime(
        state_dir=tmp_path / "state",
    ).recommendation
    catalog = runtime._decision_facts
    unresolved: list[tuple[int, str, str]] = []

    for product_id in sorted(catalog._reader.product_ids):
        product = catalog._reader.get(product_id)
        profile = category_profile_for(
            product.fields["category"].value
        )
        for fact in catalog._selection_fact_port.read(
            product_id=product_id,
            profile=profile,
        ):
            if "soft_rank" not in fact.capabilities:
                continue
            if _MACHINE_VALUE.fullmatch(fact.normalized_value) is None:
                continue
            if (
                fact.field_key == "efficacy"
                and fact.normalized_value in _CLOSED_EFFICACY_VALUES
            ):
                continue
            unresolved.append(
                (
                    fact.product_id,
                    fact.field_key,
                    fact.normalized_value,
                )
            )

    assert unresolved == []


def test_reviewed_concepts_merge_without_weakening_safety_roles(
    tmp_path,
) -> None:
    runtime = build_consultation_vertical_runtime(
        state_dir=tmp_path / "state",
    ).recommendation
    catalog = runtime._decision_facts

    def facts_for(product_id: int):
        product = catalog._reader.get(product_id)
        return catalog._selection_fact_port.read(
            product_id=product_id,
            profile=category_profile_for(
                product.fields["category"].value
            ),
        )

    product_105 = facts_for(105)
    product_106 = facts_for(106)

    assert not any(
        fact.field_key == "suitable_skin"
        and "soft_rank" in fact.capabilities
        for fact in product_105
    )
    all_skin = next(
        fact
        for fact in product_106
        if fact.field_key == "suitable_skin"
        and fact.normalized_value == "全肤质"
    )
    assert all_skin.safety_role == "merchant_positive_safety"
    smooth = next(
        fact
        for fact in product_106
        if fact.field_key == "texture"
        and fact.normalized_value == "平滑细腻"
    )
    assert smooth.attributions == frozenset(
        {"consumer_report", "merchant_claim"}
    )
    assert len(
        [
            fact
            for fact in product_106
            if fact.field_key == "texture"
            and fact.normalized_value == "清爽"
        ]
    ) == 1
