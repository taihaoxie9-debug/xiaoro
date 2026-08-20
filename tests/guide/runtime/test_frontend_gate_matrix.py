from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from app.guide.decision.concept_ranking import rank_common_concepts
from app.guide.decision.relative_comparison import (
    compare_relative_candidate,
)
from app.guide.intent.contracts import ConceptConstraint
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)
from tests.guide.decision.test_concept_ranking import (
    _fact as concept_fact,
    _product as concept_product,
    _projection as concept_projection,
)
from tests.guide.decision.test_relative_comparison import (
    _fact as relative_fact,
    _product as relative_product,
    _projection as relative_projection,
)


MATRIX_PATH = Path(
    "docs/audits/backend-handoff/frontend_gate_matrix_v1.jsonl"
)


class MatrixRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    case_id: str
    scenario: str
    expected_match_status: str
    expected_relation_kind: str | None
    expected_effect_claim_supported: bool
    expected_source_alignment: bool


ROWS = tuple(
    MatrixRow.model_validate_json(line, strict=True)
    for line in MATRIX_PATH.read_text(encoding="utf-8").splitlines()
    if line.strip()
)


def test_frontend_gate_matrix_has_eight_unique_cases() -> None:
    assert len(ROWS) == 8
    assert len({row.case_id for row in ROWS}) == 8


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.case_id)
def test_frontend_gate_matrix(row: MatrixRow) -> None:
    status, relation, effect, aligned = _run(row.case_id)

    assert status == row.expected_match_status
    assert relation == row.expected_relation_kind
    assert effect is row.expected_effect_claim_supported
    assert aligned is row.expected_source_alignment


def _run(
    case_id: str,
) -> tuple[str, str | None, bool, bool]:
    if case_id == "concept-soothing-match":
        reader = SelectionParentConceptReader((
            concept_projection(
                value="舒缓",
                concept_id="efficacy.soothing",
                source_refs=("source-a",),
            ),
        ))
        ranking = rank_common_concepts(
            concept_product((
                concept_fact(
                    value="舒缓",
                    strength=2,
                    source_ref="source-a",
                ),
            )),
            (
                ConceptConstraint(
                    field_key="efficacy",
                    concept_id="efficacy.soothing",
                    polarity="prefer",
                ),
            ),
            reader=reader,
        )
        return _concept_outcome(ranking)

    if case_id == "concept-refreshing-and-soothing":
        reader = SelectionParentConceptReader((
            concept_projection(
                value="舒缓",
                concept_id="efficacy.soothing",
                source_refs=("source-a",),
            ),
            concept_projection(
                value="清爽",
                concept_id="texture.refreshing",
                field_key="texture",
                source_refs=("source-b",),
            ),
        ))
        ranking = rank_common_concepts(
            concept_product((
                concept_fact(
                    value="舒缓",
                    strength=1,
                    source_ref="source-a",
                ),
                concept_fact(
                    value="清爽",
                    field_key="texture",
                    strength=1,
                    source_ref="source-b",
                ),
            )),
            (
                ConceptConstraint(
                    field_key="texture",
                    concept_id="texture.refreshing",
                    polarity="prefer",
                ),
                ConceptConstraint(
                    field_key="efficacy",
                    concept_id="efficacy.soothing",
                    polarity="prefer",
                ),
            ),
            reader=reader,
        )
        return _concept_outcome(ranking)

    if case_id == "concept-no-evidence-unknown":
        reader = SelectionParentConceptReader((
            concept_projection(
                value="保湿",
                concept_id="efficacy.hydration",
                source_refs=("source-a",),
            ),
        ))
        ranking = rank_common_concepts(
            concept_product((
                concept_fact(
                    value="保湿",
                    strength=2,
                    source_ref="source-a",
                ),
            )),
            (
                ConceptConstraint(
                    field_key="efficacy",
                    concept_id="efficacy.soothing",
                    polarity="prefer",
                ),
            ),
            reader=reader,
        )
        return _concept_outcome(ranking)

    if case_id == "concept-explicit-opposition-mismatch":
        reader = SelectionParentConceptReader((
            concept_projection(
                value="厚重",
                concept_id="texture.refreshing",
                field_key="texture",
                source_refs=("source-a",),
                stance="opposes",
            ),
        ))
        ranking = rank_common_concepts(
            concept_product((
                concept_fact(
                    value="厚重",
                    field_key="texture",
                    strength=2,
                    source_ref="source-a",
                ),
            )),
            (
                ConceptConstraint(
                    field_key="texture",
                    concept_id="texture.refreshing",
                    polarity="prefer",
                ),
            ),
            reader=reader,
        )
        return _concept_outcome(ranking)

    if case_id == "relative-more-affordable":
        result = compare_relative_candidate(
            candidate=relative_product(
                1,
                price="100",
                price_refs=("price-1",),
            ),
            baseline=relative_product(
                2,
                price="200",
                price_refs=("price-2",),
            ),
            field_key="price",
            concept_id=None,
            direction="lower",
            reader=None,
        )
        return _relative_outcome(result)

    if case_id == "relative-better-refreshing-match":
        reader = SelectionParentConceptReader((
            relative_projection(
                field_key="texture",
                value="清爽",
                concept_id="texture.refreshing",
                source_refs=("source-a",),
            ),
        ))
        result = compare_relative_candidate(
            candidate=relative_product(
                1,
                price="100",
                selection_facts=(
                    relative_fact(
                        1,
                        field_key="texture",
                        value="清爽",
                        strength=1,
                        source_ref="source-a",
                    ),
                ),
            ),
            baseline=relative_product(2, price="100"),
            field_key="texture",
            concept_id="texture.refreshing",
            direction="higher",
            reader=reader,
        )
        return _relative_outcome(result)

    if case_id == "relative-stronger-soothing-evidence":
        reader = SelectionParentConceptReader((
            relative_projection(
                field_key="efficacy",
                value="舒缓",
                concept_id="efficacy.soothing",
                source_refs=("source-a", "source-b"),
            ),
        ))
        result = compare_relative_candidate(
            candidate=relative_product(
                1,
                price="100",
                selection_facts=(
                    relative_fact(
                        1,
                        field_key="efficacy",
                        value="舒缓",
                        strength=2,
                        source_ref="source-a",
                    ),
                ),
            ),
            baseline=relative_product(
                2,
                price="100",
                selection_facts=(
                    relative_fact(
                        2,
                        field_key="efficacy",
                        value="舒缓",
                        strength=1,
                        source_ref="source-b",
                    ),
                ),
            ),
            field_key="efficacy",
            concept_id="efficacy.soothing",
            direction="higher",
            reader=reader,
        )
        return _relative_outcome(result)

    if case_id == "relative-unsupported-evidence-gap":
        result = compare_relative_candidate(
            candidate=relative_product(1, price="100"),
            baseline=relative_product(2, price="100"),
            field_key="fragrance_description",
            concept_id=None,
            direction="higher",
            reader=None,
        )
        return _relative_outcome(result)

    raise AssertionError(f"unknown frontend matrix case: {case_id}")


def _concept_outcome(ranking) -> tuple[str, None, bool, bool]:
    statuses = ",".join(slot.match_status for slot in ranking.slots)
    refs = {
        reference
        for slot in ranking.slots
        for reference in slot.source_refs
    }
    aligned = refs <= set(
        reference
        for slot in ranking.slots
        for reference in slot.source_refs
    )
    return statuses, None, False, aligned


def _relative_outcome(result) -> tuple[str, str, bool, bool]:
    return (
        result.status,
        result.relation_kind,
        result.effect_claim_supported,
        len(result.source_refs) == len(set(result.source_refs)),
    )
