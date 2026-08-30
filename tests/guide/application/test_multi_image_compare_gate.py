from __future__ import annotations

import hashlib
import importlib
import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import permutations
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.decision.multi_image_compare_contracts import (
    MultiImageCompareDecisionResult,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.ports import CategoryRecord
from app.guide.understanding.contracts import ImageBundle, ImageObservation
from app.guide.understanding.image_contracts import IdentityState
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)


_PRODUCT_IDS = (53, 55, 57, 54)
_CATEGORIES = ("防晒乳", "防晒霜", "防晒", "防晒乳液")
_BUNDLE_ID = "bundle_" + "a" * 32
_OWNER_TOKEN = "owner_" + "o" * 43
_SESSION_ID = "session-multi-image-compare"
_PRIVATE_FACT_SERIALIZATION_DETAIL = "private fact serialization failure"
_PRIVATE_DECISION_SERIALIZATION_DETAIL = (
    "private decision serialization failure"
)


class FatalAdapterSignal(BaseException):
    pass


class SerializationFailingDecisionProductFacts(DecisionProductFacts):
    def model_dump(self, *args, **kwargs):
        raise RuntimeError(_PRIVATE_FACT_SERIALIZATION_DETAIL)


class FatalSerializationDecisionProductFacts(DecisionProductFacts):
    def model_dump(self, *args, **kwargs):
        raise FatalAdapterSignal("decision facts serialization")


class SerializationFailingDecisionResult(MultiImageCompareDecisionResult):
    def model_dump(self, *args, **kwargs):
        raise RuntimeError(_PRIVATE_DECISION_SERIALIZATION_DETAIL)


def _subject():
    try:
        return importlib.import_module(
            "app.guide.application.multi_image_compare_gate"
        )
    except ModuleNotFoundError:
        pytest.fail("three/four-image compare gate is missing")


def _decision():
    try:
        return importlib.import_module(
            "app.guide.decision.multi_image_compare"
        )
    except ModuleNotFoundError:
        pytest.fail("three/four-image compare decision is missing")


def _bundle(
    count: int,
    *,
    bundle_id: str = _BUNDLE_ID,
) -> ImageBundle:
    created_at = datetime(2026, 8, 9, tzinfo=UTC)
    return ImageBundle(
        bundle_id=bundle_id,
        session_id=_SESSION_ID,
        owner_token_sha256=hashlib.sha256(
            _OWNER_TOKEN.encode("utf-8")
        ).hexdigest(),
        version=1,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=30),
        images=[
            ImageObservation(
                image_id=f"image_{ordinal:032d}",
                ordinal=ordinal,
                content_sha256=f"{ordinal:064x}",
                media_type="image/jpeg",
                image_format="JPEG",
                width=640,
                height=640,
                byte_size=1024,
            )
            for ordinal in range(1, count + 1)
        ],
    )


def _context(
    count: int,
    *,
    states: tuple[IdentityState, ...] | None = None,
    product_ids: tuple[int, ...] | None = None,
    bundle_id: str = _BUNDLE_ID,
) -> MultiImageTaskContext:
    identity_states = states or (IdentityState.CONFIRMED,) * count
    confirmed_ids = product_ids or _PRODUCT_IDS[:count]
    return MultiImageTaskContext(
        mode="compare",
        bundle_id=bundle_id,
        references=[
            ImageTaskReference(
                image_id=f"image_{ordinal:032d}",
                ordinal=ordinal,
                identity_state=state,
                confirmed_product_id=(
                    confirmed_ids[ordinal - 1]
                    if state is IdentityState.CONFIRMED
                    else None
                ),
            )
            for ordinal, state in enumerate(identity_states, start=1)
        ],
    )


def _facts(
    product_id: int,
    price: str | None = "100",
    *,
    state: FactState = FactState.KNOWN,
    source_refs: tuple[str, ...] | None = None,
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        price=Decimal(price) if price is not None else None,
        price_state=state,
        efficacy=("防晒",),
        efficacy_state=FactState.KNOWN,
        suitable_skin=("多种肤质",),
        suitable_skin_state=FactState.KNOWN,
        ingredients_present=("水",),
        ingredients_present_state=FactState.KNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
        price_source_refs=(
            source_refs
            if source_refs is not None
            else (f"price-source:{product_id}",)
        ),
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


class FailingCategories(RecordingCategories):
    def __init__(self, failure: BaseException) -> None:
        super().__init__([])
        self.failure = failure

    def iter_category_records(self):
        self.calls += 1
        raise self.failure


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


class FailingFacts(RecordingFacts):
    def __init__(self, failure: BaseException) -> None:
        super().__init__([])
        self.failure = failure

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        self.calls.append(product_id)
        raise self.failure


class RecordingDecision:
    def __init__(self) -> None:
        self.calls = []
        self._foundation = _decision().MultiImageCompareDecisionFoundation()

    def decide(self, request):
        self.calls.append(request)
        return self._foundation.decide(request)


class ForgedSemanticDecision(RecordingDecision):
    def decide(self, request):
        self.calls.append(request)
        payload = request.model_dump(mode="python")
        payload["items"][0]["facts"]["price"] = Decimal("1")
        forged_request = type(request).model_validate(payload)
        forged_result = self._foundation.decide(forged_request)
        return SimpleNamespace(
            model_dump=lambda **_: forged_result.model_dump(mode="python")
        )


class MutatingDecision(RecordingDecision):
    def decide(self, request):
        self.calls.append(request)
        result = self._foundation.decide(request)
        request.items[0].facts.product_id = 999
        return result


class FailingDecision(RecordingDecision):
    def __init__(self, failure: BaseException) -> None:
        super().__init__()
        self.failure = failure

    def decide(self, request):
        self.calls.append(request)
        raise self.failure


class SerializationFailingDecision(RecordingDecision):
    def decide(self, request):
        self.calls.append(request)
        result = self._foundation.decide(request)
        return SerializationFailingDecisionResult.model_validate(
            result.model_dump(mode="python")
        )


class FrozenBypassDecision(RecordingDecision):
    def decide(self, request):
        self.calls.append(request)
        result = self._foundation.decide(request)
        object.__setattr__(request.items[0].facts, "product_id", 999)
        return result


def _service(
    count: int,
    *,
    bundle: ImageBundle | None = None,
    category_catalog: RecordingCategories | None = None,
    categories: list[CategoryRecord] | None = None,
    decision_facts: RecordingFacts | None = None,
    facts: list[DecisionProductFacts] | None = None,
    decision: RecordingDecision | None = None,
):
    category_port = category_catalog or RecordingCategories(
        (
            categories
            if categories is not None
            else [
                CategoryRecord(
                    product_id=product_id,
                    value=category,
                    state="known",
                )
                for product_id, category in zip(
                    _PRODUCT_IDS[:count],
                    _CATEGORIES[:count],
                    strict=True,
                )
            ]
        )
    )
    fact_port = decision_facts or RecordingFacts(
        (
            facts
            if facts is not None
            else [
                _facts(product_id, str(80 + ordinal * 10))
                for ordinal, product_id in enumerate(
                    _PRODUCT_IDS[:count],
                    start=1,
                )
            ]
        )
    )
    decision_port = decision if decision is not None else RecordingDecision()
    authorized_bundle = bundle if bundle is not None else _bundle(count)
    gate = _subject().ThreeToFourImageCompareGate(
        category_catalog=category_port,
        decision_facts=fact_port,
        decision=decision_port,
    )
    return (
        gate,
        authorized_bundle,
        category_port,
        fact_port,
        decision_port,
    )


def _prepare(gate, context, authorized_bundle=None):
    return gate.prepare(
        context,
        authorized_bundle=(
            authorized_bundle
            if authorized_bundle is not None
            else _bundle(len(context.references))
        ),
    )


def test_gate_accepts_only_pre_authorized_bundle_evidence() -> None:
    subject = _subject()
    signature = inspect.signature(
        subject.ThreeToFourImageCompareGate.prepare
    )

    assert "authorized_bundle" in signature.parameters
    assert "authorization" not in signature.parameters
    assert "bundle_authorizer" not in inspect.signature(
        subject.ThreeToFourImageCompareGate
    ).parameters
    assert not hasattr(
        subject,
        "MultiImageCompareBundleAuthorizationRequest",
    )


def test_gate_rejects_legacy_authorization_arguments() -> None:
    subject = _subject()
    gate, _, categories, facts, decision = _service(3)

    assert not hasattr(subject, "MultiImageCompareBundleAuthority")
    assert not hasattr(subject, "MultiImageCompareAuthorityImage")
    with pytest.raises(TypeError, match="authorization"):
        gate.prepare(
            _context(3),
            authorization=object(),
        )

    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


@pytest.mark.parametrize("count", [3, 4])
def test_success_uses_authorized_bundle_ordinal_order_and_exact_cards(
    count: int,
) -> None:
    gate, authorized_bundle, categories, facts, decision = _service(count)

    result = _prepare(
        gate,
        _context(count),
        authorized_bundle,
    )

    expected_ids = _PRODUCT_IDS[:count]
    assert result.kind == "ready"
    assert tuple(
        (item.ordinal, item.image_id, item.product_id)
        for item in result.decision_input.items
    ) == tuple(
        (ordinal, f"image_{ordinal:032d}", product_id)
        for ordinal, product_id in enumerate(expected_ids, start=1)
    )
    assert result.decision_result.ordered_product_ids == expected_ids
    assert result.card_intent.mode == "comparison"
    assert result.card_intent.visible_product_ids == expected_ids
    assert result.card_intent.reason == "comparison"
    assert categories.calls == 1
    assert facts.calls == list(expected_ids)
    assert len(decision.calls) == 1


@pytest.mark.parametrize("count", [2, 5])
def test_requires_exactly_three_or_four_before_any_port_call(
    count: int,
) -> None:
    gate, _, categories, facts, decision = _service(3)
    context = MultiImageTaskContext.model_construct(
        mode="compare",
        bundle_id=_BUNDLE_ID,
        references=[
            ImageTaskReference(
                image_id=f"image_{ordinal:032d}",
                ordinal=min(ordinal, 4),
                identity_state=IdentityState.CONFIRMED,
                confirmed_product_id=50 + ordinal,
            )
            for ordinal in range(1, count + 1)
        ],
    )

    result = _prepare(gate, context, _bundle(3))

    assert result.kind == "clarification"
    assert result.code == "three_or_four_images_required"
    assert not hasattr(result, "card_intent")
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
            IdentityState.CANONICAL_IDENTITY_UNAVAILABLE,
            "image_identity_unconfirmed",
        ),
    ],
)
def test_any_unconfirmed_identity_fails_closed_before_port_calls(
    state: IdentityState,
    code: str,
) -> None:
    gate, _, categories, facts, decision = _service(3)
    context = _context(
        3,
        states=(
            IdentityState.CONFIRMED,
            state,
            IdentityState.CONFIRMED,
        ),
    )

    result = _prepare(gate, context)

    assert result.kind == "clarification"
    assert result.code == code
    assert result.ordinal == 2
    assert result.image_id == "image_" + "2".zfill(32)
    assert result.identity_state is state
    assert not hasattr(result, "card_intent")
    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


def test_duplicate_confirmed_product_fails_closed() -> None:
    gate, _, categories, facts, decision = _service(3)

    result = _prepare(
        gate,
        _context(3, product_ids=(53, 55, 53)),
    )

    assert result.kind == "clarification"
    assert result.code == "duplicate_product_identity"
    assert not hasattr(result, "card_intent")
    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


def test_non_contiguous_context_fails_closed_before_port_calls() -> None:
    gate, _, categories, facts, decision = _service(3)
    context = _context(3)
    context.references[1].ordinal = 3
    context.references[2].ordinal = 2

    result = _prepare(gate, context)

    assert result.kind == "error"
    assert result.code == "non_contiguous_image_ordinals"
    assert not hasattr(result, "card_intent")
    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


@pytest.mark.parametrize(
    "context",
    [
        _context(3, bundle_id="bundle_" + "b" * 32),
        MultiImageTaskContext(
            mode="compare",
            bundle_id=_BUNDLE_ID,
            references=[
                ImageTaskReference(
                    image_id=(
                        "image_" + "9" * 32
                        if ordinal == 2
                        else f"image_{ordinal:032d}"
                    ),
                    ordinal=ordinal,
                    identity_state=IdentityState.CONFIRMED,
                    confirmed_product_id=product_id,
                )
                for ordinal, product_id in enumerate(
                    _PRODUCT_IDS[:3],
                    start=1,
                )
            ],
        ),
    ],
)
def test_context_must_match_server_bundle_authority_exactly(
    context: MultiImageTaskContext,
) -> None:
    gate, _, categories, facts, decision = _service(3)

    result = _prepare(gate, context)

    assert result.kind == "error"
    assert result.code == "bundle_authority_mismatch"
    assert not hasattr(result, "card_intent")
    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


def test_authorized_bundle_must_be_exact_typed_evidence() -> None:
    gate, _, categories, facts, decision = _service(3)

    with pytest.raises(TypeError, match="exact ImageBundle"):
        gate.prepare(
            _context(3),
            authorized_bundle=SimpleNamespace(),
        )

    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


@pytest.mark.parametrize("count", [3, 4])
def test_authoritative_bundle_rejects_every_context_image_id_permutation(
    count: int,
) -> None:
    gate, authorized_bundle, categories, facts, decision = _service(count)
    canonical_order = tuple(range(1, count + 1))

    for image_order in permutations(canonical_order):
        if image_order == canonical_order:
            continue
        context = _context(count)
        for reference, source_ordinal in zip(
            context.references,
            image_order,
            strict=True,
        ):
            reference.image_id = f"image_{source_ordinal:032d}"

        result = _prepare(gate, context, authorized_bundle)

        assert result.kind == "error"
        assert result.code == "bundle_authority_mismatch"
        assert not hasattr(result, "card_intent")

    assert categories.calls == 0
    assert facts.calls == []
    assert decision.calls == []


def test_category_adapter_runtime_error_is_typed_and_does_not_leak() -> None:
    private_detail = "private category adapter failure"
    category_catalog = FailingCategories(RuntimeError(private_detail))
    gate, _, categories, facts, decision = _service(
        3,
        category_catalog=category_catalog,
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert private_detail not in result.model_dump_json()
    assert not hasattr(result, "card_intent")
    assert categories is category_catalog
    assert categories.calls == 1
    assert facts.calls == []
    assert decision.calls == []


@pytest.mark.parametrize("state", ["unknown", "conflict", "not_applicable"])
def test_unusable_canonical_category_fails_closed_before_facts(
    state: str,
) -> None:
    gate, _, categories, facts, decision = _service(
        3,
        categories=[
            CategoryRecord(product_id=53, value="防晒乳", state="known"),
            CategoryRecord(product_id=55, value="防晒霜", state="known"),
            CategoryRecord(product_id=57, value=None, state=state),
        ],
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "clarification"
    assert result.code == "canonical_category_unavailable"
    assert result.ordinal == 3
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == []
    assert decision.calls == []


def test_cross_category_products_fail_closed_before_facts() -> None:
    gate, _, categories, facts, decision = _service(
        3,
        categories=[
            CategoryRecord(product_id=53, value="防晒乳", state="known"),
            CategoryRecord(product_id=55, value="防晒霜", state="known"),
            CategoryRecord(product_id=57, value="精华液", state="known"),
        ],
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "clarification"
    assert result.code == "cross_category_products"
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == []
    assert decision.calls == []


def test_missing_canonical_decision_facts_fail_closed() -> None:
    gate, _, categories, facts, decision = _service(
        3,
        facts=[_facts(53), _facts(55)],
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "clarification"
    assert result.code == "canonical_facts_unavailable"
    assert result.ordinal == 3
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == [53, 55, 57]
    assert decision.calls == []


def test_decision_fact_adapter_runtime_error_is_typed_and_does_not_leak() -> None:
    private_detail = "private decision fact adapter failure"
    decision_facts = FailingFacts(RuntimeError(private_detail))
    gate, _, categories, facts, decision = _service(
        3,
        decision_facts=decision_facts,
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert private_detail not in result.model_dump_json()
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts is decision_facts
    assert facts.calls == [53]
    assert decision.calls == []


def test_decision_fact_serialization_runtime_error_is_typed_and_does_not_leak(
) -> None:
    hostile_facts = SerializationFailingDecisionProductFacts.model_validate(
        _facts(53).model_dump(mode="python")
    )
    assert isinstance(hostile_facts, DecisionProductFacts)
    gate, _, categories, facts, decision = _service(
        3,
        facts=[hostile_facts, _facts(55), _facts(57)],
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert _PRIVATE_FACT_SERIALIZATION_DETAIL not in result.model_dump_json()
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == [53]
    assert decision.calls == []


def test_decision_fact_serialization_base_exception_is_not_swallowed() -> None:
    hostile_facts = FatalSerializationDecisionProductFacts.model_validate(
        _facts(53).model_dump(mode="python")
    )
    gate, _, categories, facts, decision = _service(
        3,
        facts=[hostile_facts, _facts(55), _facts(57)],
    )

    with pytest.raises(
        FatalAdapterSignal,
        match="decision facts serialization",
    ):
        _prepare(gate, _context(3))

    assert categories.calls == 1
    assert facts.calls == [53]
    assert decision.calls == []


def test_unaudited_decision_fact_fails_closed_with_zero_cards() -> None:
    gate, _, categories, facts, decision = _service(
        3,
        facts=[
            _facts(53),
            _facts(55, source_refs=()),
            _facts(57),
        ],
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "clarification"
    assert result.code == "canonical_decision_facts_unaudited"
    assert result.ordinal == 2
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == [53, 55]
    assert decision.calls == []


def test_audited_unknown_price_produces_insufficient_outcome() -> None:
    gate, _, categories, facts, decision = _service(
        3,
        facts=[
            _facts(53, "80"),
            _facts(55, "100"),
            _facts(
                57,
                None,
                state=FactState.UNKNOWN,
                source_refs=("price-state-source:57:unknown",),
            ),
        ],
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "ready"
    assert result.decision_result.outcome.status == "insufficient_evidence"
    assert result.card_intent.visible_product_ids == (53, 55, 57)
    assert categories.calls == 1
    assert facts.calls == [53, 55, 57]
    assert len(decision.calls) == 1


@pytest.mark.parametrize(
    ("price", "state", "expected_status"),
    [
        ("120", FactState.KNOWN, "winner"),
        (None, FactState.UNKNOWN, "insufficient_evidence"),
    ],
)
def test_long_valid_evidence_ref_preserves_decision_semantics(
    price: str | None,
    state: FactState,
    expected_status: str,
) -> None:
    long_ref = "canonical-price-source:" + "x" * 300
    gate, _, categories, facts, decision = _service(
        3,
        facts=[
            _facts(53, "80"),
            _facts(55, "100"),
            _facts(
                57,
                price,
                state=state,
                source_refs=(long_ref,),
            ),
        ],
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "ready"
    assert result.decision_result.outcome.status == expected_status
    assert result.decision_result.outcome.evidence_refs[-1] == long_ref
    assert categories.calls == 1
    assert facts.calls == [53, 55, 57]
    assert len(decision.calls) == 1


def test_ready_decision_facts_are_deeply_immutable_and_consistent() -> None:
    gate, _, _, _, _ = _service(3)
    result = _prepare(gate, _context(3))
    ready_facts = result.decision_input.items[0].facts
    original_result = result.model_copy(deep=True)

    assert isinstance(ready_facts, DecisionProductFacts)
    assert type(ready_facts) is not DecisionProductFacts
    assert ready_facts.model_config["frozen"] is True
    with pytest.raises(ValidationError, match="frozen"):
        ready_facts.product_id = 999
    with pytest.raises(ValidationError, match="frozen"):
        ready_facts.price_source_refs += ("forged-source",)

    assert result == original_result
    assert result.decision_result.ordered_product_ids == (53, 55, 57)
    assert result.card_intent.visible_product_ids == (53, 55, 57)


def test_invalid_canonical_fact_contract_fails_closed_with_zero_cards() -> None:
    invalid = _facts(55).model_copy(
        update={"price_source_refs": ("duplicate", "duplicate")}
    )
    gate, _, categories, facts, decision = _service(
        3,
        facts=[_facts(53), invalid, _facts(57)],
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == [53, 55]
    assert decision.calls == []


def test_mismatched_canonical_fact_identity_is_zero_card_error() -> None:
    mismatched = _facts(55)
    facts = [_facts(53), mismatched, _facts(57)]
    fact_port = RecordingFacts(facts)
    fact_port.records[53] = mismatched
    categories = RecordingCategories(
        [
            CategoryRecord(product_id=53, value="防晒乳", state="known"),
            CategoryRecord(product_id=55, value="防晒霜", state="known"),
            CategoryRecord(product_id=57, value="防晒", state="known"),
        ]
    )
    decision = RecordingDecision()
    gate = _subject().ThreeToFourImageCompareGate(
        category_catalog=categories,
        decision_facts=fact_port,
        decision=decision,
    )

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "canonical_fact_mismatch"
    assert result.ordinal == 1
    assert not hasattr(result, "card_intent")
    assert fact_port.calls == [53]
    assert decision.calls == []


def test_semantically_forged_decision_fails_closed_with_zero_cards() -> None:
    forged = ForgedSemanticDecision()
    gate, _, categories, facts, decision = _service(3, decision=forged)

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == [53, 55, 57]
    assert decision is forged
    assert len(decision.calls) == 1


def test_mutating_decision_input_fails_closed_with_zero_cards() -> None:
    mutating = MutatingDecision()
    gate, _, categories, facts, decision = _service(3, decision=mutating)

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == [53, 55, 57]
    assert decision is mutating
    assert len(decision.calls) == 1
    assert decision.calls[0].items[0].facts.product_id == 53


@pytest.mark.parametrize("failure_type", [RuntimeError, ValueError])
def test_decision_adapter_ordinary_exception_is_typed_and_does_not_leak(
    failure_type: type[Exception],
) -> None:
    private_detail = "private decision adapter failure"
    failing = FailingDecision(failure_type(private_detail))
    gate, _, categories, facts, decision = _service(3, decision=failing)

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert private_detail not in result.model_dump_json()
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == [53, 55, 57]
    assert decision is failing
    assert len(decision.calls) == 1


def test_decision_result_serialization_runtime_error_is_typed_and_does_not_leak(
) -> None:
    failing = SerializationFailingDecision()
    gate, _, categories, facts, decision = _service(3, decision=failing)

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert _PRIVATE_DECISION_SERIALIZATION_DETAIL not in result.model_dump_json()
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == [53, 55, 57]
    assert decision is failing
    assert len(decision.calls) == 1


def test_adapter_frozen_bypass_mutates_only_copy_and_is_detected() -> None:
    bypass = FrozenBypassDecision()
    gate, _, categories, facts, decision = _service(3, decision=bypass)

    result = _prepare(gate, _context(3))

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert not hasattr(result, "card_intent")
    assert categories.calls == 1
    assert facts.calls == [53, 55, 57]
    assert facts.records[53].product_id == 53
    assert decision is bypass
    assert decision.calls[0].items[0].facts.product_id == 999


@pytest.mark.parametrize(
    "boundary",
    ["category_catalog", "decision_facts", "decision"],
)
def test_adapter_base_exception_is_not_swallowed(boundary: str) -> None:
    signal = FatalAdapterSignal(boundary)
    arguments = {
        "category_catalog": None,
        "decision_facts": None,
        "decision": None,
    }
    if boundary == "category_catalog":
        arguments["category_catalog"] = FailingCategories(signal)
    elif boundary == "decision_facts":
        arguments["decision_facts"] = FailingFacts(signal)
    else:
        arguments["decision"] = FailingDecision(signal)
    gate, _, _, _, _ = _service(3, **arguments)

    with pytest.raises(FatalAdapterSignal, match=boundary):
        _prepare(gate, _context(3))


def test_preparation_result_is_discriminated_and_failures_forbid_cards() -> None:
    subject = _subject()
    gate, _, _, _, _ = _service(3)
    ready = _prepare(gate, _context(3))

    parsed = TypeAdapter(
        subject.MultiImageComparePreparationResult
    ).validate_python(ready.model_dump(mode="python"))

    assert isinstance(parsed, subject.PreparedMultiImageComparison)
    assert parsed.card_intent.visible_product_ids == (53, 55, 57)

    clarification = subject.MultiImageCompareClarification(
        kind="clarification",
        code="three_or_four_images_required",
        message="需要三到四张图片。",
    )
    error = subject.MultiImageComparePreparationError(
        kind="error",
        code="bundle_authority_mismatch",
        message="当前图片批次与服务器授权不一致。",
    )
    assert not hasattr(clarification, "card_intent")
    assert not hasattr(error, "card_intent")
    with pytest.raises(ValidationError):
        subject.MultiImageCompareClarification.model_validate(
            {
                **clarification.model_dump(mode="python"),
                "card_intent": {
                    "mode": "comparison",
                    "visible_product_ids": (53, 55, 57),
                    "reason": "comparison",
                },
            }
        )
