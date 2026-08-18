from __future__ import annotations

from app.guide.presentation.copywriter_contracts import ApprovedSoftFact


def _fact(
    fact_id: str,
    field_key: str,
    meaning: str,
    attribution: str,
) -> ApprovedSoftFact:
    return ApprovedSoftFact(
        fact_id=fact_id,
        product_id=55,
        field_key=field_key,
        plain_meaning=meaning,
        attribution=attribution,
        source_refs=(f"source:{fact_id}",),
    )


def _build(
    facts: tuple[ApprovedSoftFact, ...],
    *,
    preferred_fields: set[str],
    distinctive_fields: set[str],
) -> tuple[ApprovedSoftFact, ...]:
    from app.guide.presentation.narrative_atoms import (
        build_narrative_atoms,
    )

    return build_narrative_atoms(
        facts,
        preferred_fields=preferred_fields,
        distinctive_fields=distinctive_fields,
    )


def test_same_field_and_attribution_merge_into_one_atom() -> None:
    atoms = _build(
        (
            _fact("a", "texture", "轻薄", "merchant_claim"),
            _fact("b", "texture", "清爽不油腻", "merchant_claim"),
        ),
        preferred_fields={"texture"},
        distinctive_fields={"texture"},
    )

    assert len(atoms) == 1
    assert atoms[0].field_key == "texture"
    assert atoms[0].plain_meaning == "轻薄；清爽不油腻"
    assert atoms[0].source_refs == ("source:a", "source:b")


def test_different_attributions_never_merge() -> None:
    atoms = _build(
        (
            _fact("a", "texture", "轻薄", "merchant_claim"),
            _fact("b", "texture", "清爽", "consumer_report"),
        ),
        preferred_fields={"texture"},
        distinctive_fields=set(),
    )

    assert [item.attribution for item in atoms] == [
        "consumer_report",
        "merchant_claim",
    ]


def test_atoms_prioritize_need_then_distinctive_fields_stably() -> None:
    atoms = _build(
        (
            _fact("finish", "finish", "自然哑光", "merchant_claim"),
            _fact("texture", "texture", "清爽", "merchant_claim"),
            _fact("efficacy", "efficacy", "提亮", "merchant_claim"),
        ),
        preferred_fields={"texture"},
        distinctive_fields={"finish"},
    )

    assert [item.field_key for item in atoms] == [
        "texture",
        "finish",
        "efficacy",
    ]


def test_atoms_keep_approved_merchant_efficacy_and_ingredient_claims() -> None:
    atoms = _build(
        (
            _fact(
                "efficacy",
                "efficacy",
                "品牌主打：12周充盈凹陷，堪比玻尿酸填充",
                "merchant_claim",
            ),
            _fact(
                "ingredients",
                "ingredients_present",
                "品牌主打：12%玻色因溶液、超小分子透明质酸",
                "merchant_claim",
            ),
            _fact(
                "texture",
                "texture",
                "轻盈滋润、快速吸收、不粘腻",
                "merchant_claim",
            ),
        ),
        preferred_fields={"efficacy"},
        distinctive_fields={"ingredients_present"},
    )

    assert [item.field_key for item in atoms] == [
        "efficacy",
        "ingredients_present",
        "texture",
    ]
    assert "12周充盈凹陷" in atoms[0].plain_meaning
    assert "12%玻色因溶液" in atoms[1].plain_meaning


def test_atoms_drop_usage_numeric_and_mechanism_copy() -> None:
    atoms = _build(
        (
            _fact("usage", "usage", "每天使用两次", "merchant_claim"),
            _fact("numeric", "texture", "持续16小时", "merchant_claim"),
            _fact("mechanism", "mechanism", "调控ROS通路", "merchant_claim"),
            _fact("texture", "texture", "轻薄清透", "merchant_claim"),
        ),
        preferred_fields=set(),
        distinctive_fields=set(),
    )

    assert len(atoms) == 1
    assert atoms[0].field_key == "texture"
    assert atoms[0].plain_meaning == "轻薄清透"
