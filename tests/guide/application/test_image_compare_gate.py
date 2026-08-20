from __future__ import annotations

import importlib
from decimal import Decimal

import pytest

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.ports import CategoryRecord
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.image_contracts import IdentityState
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)


def _subject():
    try:
        return importlib.import_module(
            "app.guide.application.image_compare_gate"
        )
    except ModuleNotFoundError:
        pytest.fail("image compare application gate is missing")


def _decision():
    try:
        return importlib.import_module(
            "app.guide.decision.image_compare"
        )
    except ModuleNotFoundError:
        pytest.fail("image compare decision foundation is missing")


def _facts(product_id: int, price: str = "100") -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        price=Decimal(price),
        price_state=FactState.KNOWN,
        efficacy=("防晒",),
        efficacy_state=FactState.KNOWN,
        suitable_skin=("多种肤质",),
        suitable_skin_state=FactState.KNOWN,
        ingredients_present=("水",),
        ingredients_present_state=FactState.KNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
    )


def _context(
    *,
    states: tuple[IdentityState, ...] = (
        IdentityState.CONFIRMED,
        IdentityState.CONFIRMED,
    ),
    product_ids: tuple[int, ...] = (53, 55),
) -> MultiImageTaskContext:
    references = [
        ImageTaskReference(
            image_id=f"image_{ordinal:032d}",
            ordinal=ordinal,
            identity_state=state,
            confirmed_product_id=(
                product_ids[ordinal - 1]
                if state is IdentityState.CONFIRMED
                else None
            ),
        )
        for ordinal, state in enumerate(states, start=1)
    ]
    return MultiImageTaskContext(
        mode="compare" if len(references) > 1 else "identify",
        bundle_id="bundle_" + "a" * 32,
        references=references,
    )


class RecordingCategories:
    def __init__(self, records: list[CategoryRecord]) -> None:
        self.records = records
        self.calls = 0

    def iter_category_records(self):
        self.calls += 1
        return tuple(
            record.model_copy(deep=True)
            for record in self.records
        )


class RecordingFacts:
    def __init__(self, records: list[DecisionProductFacts]) -> None:
        self.records = {record.product_id: record for record in records}
        self.calls: list[int] = []

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        self.calls.append(product_id)
        return self.records[product_id].model_copy(deep=True)


class RecordingDecision:
    def __init__(self) -> None:
        self.calls = []
        self._foundation = _decision().ImageCompareDecisionFoundation()

    def decide(self, request):
        self.calls.append(request)
        return self._foundation.decide(request)


class SwappingDecision(RecordingDecision):
    def decide(self, request):
        result = super().decide(request)
        payload = result.model_dump()
        payload["references"][0]["product_id"] = request.items[1].product_id
        payload["references"][1]["product_id"] = request.items[0].product_id
        payload["ordered_product_ids"] = tuple(
            reversed(result.ordered_product_ids)
        )
        payload["outcome"]["evaluated_price_facts"][0]["reference"] = (
            payload["references"][0]
        )
        payload["outcome"]["evaluated_price_facts"][1]["reference"] = (
            payload["references"][1]
        )
        return type(result).model_validate(payload)


def _service(
    *,
    categories: list[CategoryRecord] | None = None,
    facts: list[DecisionProductFacts] | None = None,
    decision: RecordingDecision | None = None,
):
    category_port = RecordingCategories(
        categories
        if categories is not None
        else [
            CategoryRecord(product_id=53, value="防晒乳", state="known"),
            CategoryRecord(product_id=55, value="防晒霜", state="known"),
        ]
    )
    fact_port = RecordingFacts(
        facts if facts is not None else [_facts(53), _facts(55, "88.11")]
    )
    decision_port = decision if decision is not None else RecordingDecision()
    service = _subject().TwoImageCompareGate(
        category_catalog=category_port,
        decision_facts=fact_port,
        decision=decision_port,
    )
    return service, category_port, fact_port, decision_port


@pytest.mark.parametrize("count", [1, 3])
def test_requires_exactly_two_references_before_any_port_call(
    count: int,
) -> None:
    service, categories, facts, decision = _service()

    result = service.prepare(
        _context(
            states=(IdentityState.CONFIRMED,) * count,
            product_ids=tuple(range(53, 53 + count)),
        )
    )

    assert result.kind == "clarification"
    assert result.code == "exactly_two_images_required"
    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


@pytest.mark.parametrize(
    ("state", "code"),
    [
        (
            IdentityState.AMBIGUOUS_CANDIDATES,
            "image_identity_ambiguous",
        ),
        (IdentityState.LOW_CONFIDENCE, "image_identity_low_confidence"),
        (IdentityState.OCR_CONFLICT, "image_identity_ocr_conflict"),
        (
            IdentityState.VISUAL_UNAVAILABLE,
            "image_visual_unavailable",
        ),
        (IdentityState.NO_CANDIDATE, "image_identity_unconfirmed"),
        (
            IdentityState.INSUFFICIENT_CANDIDATES,
            "image_identity_unconfirmed",
        ),
        (
            IdentityState.NON_CANONICAL_CANDIDATE,
            "image_identity_unconfirmed",
        ),
        (
            IdentityState.CANONICAL_IDENTITY_UNAVAILABLE,
            "image_identity_unconfirmed",
        ),
    ],
)
def test_unconfirmed_identity_clarifies_without_loading_facts_or_deciding(
    state: IdentityState,
    code: str,
) -> None:
    service, categories, facts, decision = _service()

    result = service.prepare(
        _context(states=(state, IdentityState.CONFIRMED))
    )

    assert result.kind == "clarification"
    assert result.code == code
    assert result.ordinal == 1
    assert result.image_id == "image_" + "1".zfill(32)
    assert result.identity_state is state
    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


def test_second_unconfirmed_identity_stops_before_any_port_call() -> None:
    service, categories, facts, decision = _service()

    result = service.prepare(
        _context(
            states=(
                IdentityState.CONFIRMED,
                IdentityState.NO_CANDIDATE,
            )
        )
    )

    assert result.kind == "clarification"
    assert result.code == "image_identity_unconfirmed"
    assert result.ordinal == 2
    assert result.image_id == "image_" + "2".zfill(32)
    assert result.identity_state is IdentityState.NO_CANDIDATE
    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


def test_duplicate_confirmed_product_is_not_a_comparison() -> None:
    service, categories, facts, decision = _service()

    result = service.prepare(_context(product_ids=(53, 53)))

    assert result.kind == "clarification"
    assert result.code == "duplicate_product_identity"
    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


def test_missing_canonical_product_stops_before_fact_loading() -> None:
    service, categories, facts, decision = _service(
        categories=[
            CategoryRecord(product_id=53, value="防晒乳", state="known")
        ]
    )

    result = service.prepare(_context())

    assert result.kind == "clarification"
    assert result.code == "canonical_product_unavailable"
    assert result.ordinal == 2
    assert categories.calls == 1
    assert facts.calls == []
    assert decision.calls == []


@pytest.mark.parametrize("state", ["unknown", "conflict", "not_applicable"])
def test_unusable_canonical_category_stops_before_fact_loading(
    state: str,
) -> None:
    service, categories, facts, decision = _service(
        categories=[
            CategoryRecord(product_id=53, value="防晒乳", state="known"),
            CategoryRecord(product_id=55, value=None, state=state),
        ]
    )

    result = service.prepare(_context())

    assert result.kind == "clarification"
    assert result.code == "canonical_category_unavailable"
    assert result.ordinal == 2
    assert categories.calls == 1
    assert facts.calls == []
    assert decision.calls == []


def test_duplicate_canonical_record_stops_before_fact_loading() -> None:
    service, categories, facts, decision = _service(
        categories=[
            CategoryRecord(product_id=53, value="防晒乳", state="known"),
            CategoryRecord(product_id=55, value="防晒霜", state="known"),
            CategoryRecord(product_id=55, value="防晒霜", state="known"),
        ]
    )

    result = service.prepare(_context())

    assert result.kind == "clarification"
    assert result.code == "canonical_product_unavailable"
    assert result.ordinal == 2
    assert categories.calls == 1
    assert facts.calls == []
    assert decision.calls == []


def test_cross_category_products_stop_before_fact_loading() -> None:
    service, categories, facts, decision = _service(
        categories=[
            CategoryRecord(product_id=53, value="防晒乳", state="known"),
            CategoryRecord(product_id=55, value="精华液", state="known"),
        ]
    )

    result = service.prepare(_context())

    assert result.kind == "clarification"
    assert result.code == "cross_category_products"
    assert categories.calls == 1
    assert facts.calls == []
    assert decision.calls == []


def test_missing_canonical_facts_never_calls_decision() -> None:
    service, categories, facts, decision = _service(
        facts=[_facts(53)]
    )

    result = service.prepare(_context())

    assert result.kind == "clarification"
    assert result.code == "canonical_facts_unavailable"
    assert result.ordinal == 2
    assert categories.calls == 1
    assert facts.calls == [53, 55]
    assert decision.calls == []


def test_mismatched_canonical_facts_never_call_decision() -> None:
    service, categories, facts, decision = _service()
    facts.records[53] = _facts(55)

    result = service.prepare(_context())

    assert result.kind == "error"
    assert result.code == "canonical_fact_mismatch"
    assert result.ordinal == 1
    assert categories.calls == 1
    assert facts.calls == [53]
    assert decision.calls == []


def test_success_loads_facts_in_ordinal_order_and_returns_exact_ids() -> None:
    service, categories, facts, decision = _service()

    result = service.prepare(_context())

    assert result.kind == "ready"
    assert result.code is None
    assert result.decision_input.topic is TopicCode.SUNSCREEN
    assert tuple(
        (item.ordinal, item.product_id)
        for item in result.decision_input.items
    ) == ((1, 53), (2, 55))
    assert result.decision_result.ordered_product_ids == (53, 55)
    assert tuple(
        (item.ordinal, item.product_id)
        for item in result.decision_result.references
    ) == ((1, 53), (2, 55))
    assert categories.calls == 1
    assert facts.calls == [53, 55]
    assert len(decision.calls) == 1


def test_decision_cannot_swap_the_two_confirmed_product_ids() -> None:
    swapped_decision = SwappingDecision()
    service, categories, facts, decision = _service(
        decision=swapped_decision
    )

    result = service.prepare(_context())

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert categories.calls == 1
    assert facts.calls == [53, 55]
    assert decision is swapped_decision
    assert len(decision.calls) == 1
