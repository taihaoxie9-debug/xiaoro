from __future__ import annotations

import asyncio
import importlib

import pytest
from pydantic import TypeAdapter, ValidationError

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.decision.image_suitability import (
    ImageSuitabilityDecisionFoundation,
)
from app.guide.decision.image_suitability_contracts import (
    ImageSuitabilityDecisionInput,
    ImageSuitabilityDecisionReference,
    ImageSuitabilityDecisionResult,
    SuitabilityContextClaim,
    SuitabilityContextClaims,
    SuitabilityContextProvenance,
    SuitabilityContextSource,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.image_contracts import IdentityState
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)


def _subject():
    try:
        return importlib.import_module(
            "app.guide.application.image_suitability_gate"
        )
    except ModuleNotFoundError:
        pytest.fail("single-image suitability gate is missing")


def _context(
    *,
    state: IdentityState = IdentityState.CONFIRMED,
    product_id: int = 53,
    mode: str = "suitability",
) -> MultiImageTaskContext:
    return MultiImageTaskContext(
        mode=mode,
        bundle_id="bundle_" + "a" * 32,
        references=[
            ImageTaskReference(
                image_id="image_" + "1" * 32,
                ordinal=1,
                identity_state=state,
                confirmed_product_id=(
                    product_id
                    if state is IdentityState.CONFIRMED
                    else None
                ),
            )
        ],
    )


_BUNDLE_ID = "bundle_" + "a" * 32
_IMAGE_ID = "image_" + "1" * 32
_SESSION_ID = "session-current"
_CONVERSATION_VERSION = 7
_PROFILE_OWNER = ProfileOwnerRef(
    scope="local_demo",
    subject_id="profile_0123456789abcdef",
)


def _claim(
    *,
    source: SuitabilityContextSource,
    skin_target: str = "sensitive",
    current_bundle_id: str = _BUNDLE_ID,
    current_image_id: str = _IMAGE_ID,
    session_id: str = _SESSION_ID,
    conversation_version: int = _CONVERSATION_VERSION,
    evidence_ref: str = "turn-fact:skin_type",
    profile_owner: ProfileOwnerRef = _PROFILE_OWNER,
    profile_version: int = 3,
    profile_confirmed: bool = True,
) -> SuitabilityContextClaim:
    profile_data = (
        {
            "profile_owner": profile_owner,
            "profile_version": profile_version,
            "profile_confirmed": profile_confirmed,
        }
        if source is SuitabilityContextSource.LONG_TERM_PROFILE
        else {}
    )
    return SuitabilityContextClaim(
        skin_target=skin_target,
        provenance=SuitabilityContextProvenance(
            current_bundle_id=current_bundle_id,
            current_image_id=current_image_id,
            session_id=session_id,
            conversation_version=conversation_version,
            source_kind=source,
            evidence_ref=evidence_ref,
            **profile_data,
        ),
    )


def _claims(
    *,
    skin_target: str = "sensitive",
    source: SuitabilityContextSource = (
        SuitabilityContextSource.CURRENT_EXPLICIT_INPUT
    ),
    **provenance_overrides,
) -> SuitabilityContextClaims:
    return SuitabilityContextClaims(
        claims=(
            _claim(
                source=source,
                skin_target=skin_target,
                **provenance_overrides,
            ),
        )
    )


def _authority(
    *,
    context_claims: SuitabilityContextClaims | None = None,
    current_bundle_id: str = _BUNDLE_ID,
    current_image_id: str = _IMAGE_ID,
    identity_state: IdentityState = IdentityState.CONFIRMED,
    confirmed_product_id: int | None = 53,
    session_id: str = _SESSION_ID,
    conversation_version: int = _CONVERSATION_VERSION,
    profile_owner: ProfileOwnerRef | None = None,
    profile_version: int = 3,
    profile_confirmed: bool = True,
):
    subject = _subject()
    profile = (
        subject.SuitabilityAuthoritativeProfile(
            owner=profile_owner,
            profile_version=profile_version,
            confirmed=profile_confirmed,
        )
        if profile_owner is not None
        else None
    )
    return subject.SuitabilityAuthoritativeInputs(
        current_bundle_id=current_bundle_id,
        current_image_id=current_image_id,
        current_ordinal=1,
        identity_state=identity_state,
        confirmed_product_id=confirmed_product_id,
        session_id=session_id,
        conversation_version=conversation_version,
        authoritative_context_claims=(
            context_claims
            if context_claims is not None
            else _claims()
        ),
        profile=profile,
    )


class NeverFacts:
    def get_decision_facts(self, product_id: int):
        raise AssertionError("facts must not be read")


class NeverDecision:
    def decide(self, request):
        raise AssertionError("decision must not run")


def _facts(
    product_id: int = 53,
    *,
    suitable_skin: tuple[str, ...] | None = ("敏感肌适用",),
    suitable_skin_state: FactState = FactState.KNOWN,
    suitable_skin_source_refs: tuple[str, ...] | None = None,
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        price=None,
        price_state=FactState.UNKNOWN,
        efficacy=None,
        efficacy_state=FactState.UNKNOWN,
        suitable_skin=suitable_skin,
        suitable_skin_state=suitable_skin_state,
        ingredients_present=None,
        ingredients_present_state=FactState.UNKNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
        suitable_skin_source_refs=(
            suitable_skin_source_refs
            if suitable_skin_source_refs is not None
            else (f"data/seed_dump.sql#product={product_id}",)
        ),
    )


class RecordingFacts:
    def __init__(self, facts: DecisionProductFacts) -> None:
        self.facts = facts
        self.calls: list[int] = []

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        self.calls.append(product_id)
        if product_id != self.facts.product_id:
            raise LookupError(product_id)
        return self.facts.model_copy(deep=True)


class RecordingDecision:
    def __init__(self) -> None:
        self.calls = []
        self._foundation = ImageSuitabilityDecisionFoundation()

    def decide(self, request):
        self.calls.append(request)
        return self._foundation.decide(request)


class SwappingDecision:
    def decide(self, request):
        swapped = ImageSuitabilityDecisionInput(
            reference=ImageSuitabilityDecisionReference(
                ordinal=1,
                image_id=request.reference.image_id,
                product_id=55,
            ),
            context=request.context,
            facts=_facts(product_id=55),
        )
        return ImageSuitabilityDecisionFoundation().decide(swapped)


class ForgedSemanticDecision:
    def decide(self, request):
        expected = ImageSuitabilityDecisionFoundation().decide(request)
        payload = expected.model_dump(mode="python")
        payload.update(
            {
                "status": "insufficient_evidence",
                "reason": "canonical_skin_indeterminate",
            }
        )
        return ImageSuitabilityDecisionResult.model_validate(payload)


class AssigningFactsDecision:
    def __init__(self) -> None:
        self.mutation_error: ValidationError | None = None

    def decide(self, request):
        try:
            request.facts.suitable_skin = ("敏感肌不适用",)
        except ValidationError as exc:
            self.mutation_error = exc
        return ImageSuitabilityDecisionFoundation().decide(request)


class BypassingFrozenFactsDecision:
    def decide(self, request):
        clean_result = ImageSuitabilityDecisionFoundation().decide(
            request
        )
        object.__setattr__(
            request.facts,
            "suitable_skin",
            ("敏感肌不适用",),
        )
        return clean_result


class MissingFacts:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def get_decision_facts(self, product_id: int):
        self.calls.append(product_id)
        raise LookupError(product_id)


class MismatchedFacts:
    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        return _facts(product_id=55)


class RaisingFacts:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def get_decision_facts(self, product_id: int):
        raise self.error


class ReturningFacts:
    def __init__(self, value: object) -> None:
        self.value = value

    def get_decision_facts(self, product_id: int):
        return self.value


class RaisingDecision:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def decide(self, request):
        raise self.error


class ReturningDecision:
    def __init__(self, value: object) -> None:
        self.value = value

    def decide(self, request):
        return self.value


class DumpRaisingFacts(DecisionProductFacts):
    def model_dump(self, *args, **kwargs):
        raise RuntimeError("facts payload secret")


class ReturningDumpRaisingFacts:
    def get_decision_facts(self, product_id: int):
        return DumpRaisingFacts.model_validate(
            _facts(product_id=product_id).model_dump(mode="python")
        )


class InterruptingDumpFacts(DecisionProductFacts):
    def model_dump(self, *args, **kwargs):
        raise KeyboardInterrupt("facts normalization interrupted")


class ReturningInterruptingDumpFacts:
    def get_decision_facts(self, product_id: int):
        return InterruptingDumpFacts.model_validate(
            _facts(product_id=product_id).model_dump(mode="python")
        )


class DumpRaisingDecisionResult(ImageSuitabilityDecisionResult):
    def model_dump(self, *args, **kwargs):
        raise RuntimeError("decision payload secret")


class ReturningDumpRaisingDecision:
    def decide(self, request):
        result = ImageSuitabilityDecisionFoundation().decide(request)
        return DumpRaisingDecisionResult.model_validate(
            result.model_dump(mode="python")
        )


class InterruptingDumpDecisionResult(ImageSuitabilityDecisionResult):
    def model_dump(self, *args, **kwargs):
        raise KeyboardInterrupt("decision normalization interrupted")


class ReturningInterruptingDumpDecision:
    def decide(self, request):
        result = ImageSuitabilityDecisionFoundation().decide(request)
        return InterruptingDumpDecisionResult.model_validate(
            result.model_dump(mode="python")
        )


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
def test_unconfirmed_identity_clarifies_before_port_calls(
    state: IdentityState,
    code: str,
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=NeverFacts(),
        decision=NeverDecision(),
    )

    result = gate.prepare(
        _context(state=state),
        context_claims=_claims(),
        authority=_authority(
            identity_state=state,
            confirmed_product_id=None,
        ),
    )

    assert result.kind == "clarification"
    assert result.code == code
    assert result.ordinal == 1
    assert result.image_id == "image_" + "1" * 32
    assert result.identity_state is state
    assert not hasattr(result, "card_intent")


def test_non_suitability_task_clarifies_before_port_calls() -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=NeverFacts(),
        decision=NeverDecision(),
    )

    result = gate.prepare(
        _context(mode="identify"),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "clarification"
    assert result.code == "exactly_one_image_required"
    assert not hasattr(result, "card_intent")


def test_absent_authorized_context_clarifies_with_zero_cards() -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=NeverFacts(),
        decision=NeverDecision(),
    )

    claims = SuitabilityContextClaims(claims=())
    result = gate.prepare(
        _context(),
        context_claims=claims,
        authority=_authority(context_claims=claims),
    )

    assert result.kind == "clarification"
    assert result.code == "suitability_context_required"
    assert not hasattr(result, "card_intent")


def test_unsupported_higher_precedence_context_does_not_fall_back() -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=NeverFacts(),
        decision=NeverDecision(),
    )
    claims = SuitabilityContextClaims(
        claims=(
            _claim(
                source=SuitabilityContextSource.LONG_TERM_PROFILE,
                skin_target="sensitive",
                evidence_ref="profile:test:version=3#skin_type",
            ),
            _claim(
                source=(
                    SuitabilityContextSource.CURRENT_EXPLICIT_INPUT
                ),
                skin_target="very_dry",
                evidence_ref="turn:current#skin",
            ),
        )
    )

    result = gate.prepare(
        _context(),
        context_claims=claims,
        authority=_authority(
            context_claims=claims,
            profile_owner=_PROFILE_OWNER,
        ),
    )

    assert result.kind == "clarification"
    assert result.code == "suitability_context_unsupported"
    assert (
        result.context_source
        is SuitabilityContextSource.CURRENT_EXPLICIT_INPUT
    )
    assert result.unsupported_context_value == "very_dry"
    assert not hasattr(result, "card_intent")


@pytest.mark.parametrize(
    ("claim_kwargs", "mismatch"),
    [
        (
            {"current_bundle_id": "bundle_" + "b" * 32},
            "claim.current_bundle_id",
        ),
        (
            {"current_image_id": "image_" + "2" * 32},
            "claim.current_image_id",
        ),
        ({"session_id": "session-forged"}, "claim.session_id"),
        (
            {"conversation_version": _CONVERSATION_VERSION + 1},
            "claim.conversation_version",
        ),
        (
            {
                "source": (
                    SuitabilityContextSource.CONFIRMED_SESSION
                )
            },
            "claim.source_kind",
        ),
    ],
)
def test_context_claim_mismatch_fails_closed_before_port_calls(
    claim_kwargs: dict,
    mismatch: str,
) -> None:
    authoritative_claims = _claims()
    candidate_claims = _claims(**claim_kwargs)
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=NeverFacts(),
        decision=NeverDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=candidate_claims,
        authority=_authority(context_claims=authoritative_claims),
    )

    assert result.kind == "error"
    assert result.code == "suitability_provenance_mismatch"
    assert mismatch in result.provenance_mismatches
    assert not hasattr(result, "card_intent")


@pytest.mark.parametrize(
    ("candidate_profile", "mismatch"),
    [
        (
            {
                "profile_owner": ProfileOwnerRef(
                    scope="local_demo",
                    subject_id="profile_fedcba9876543210",
                )
            },
            "claim.profile_owner",
        ),
        ({"profile_version": 4}, "claim.profile_version"),
        ({"profile_confirmed": False}, "claim.profile_confirmed"),
    ],
)
def test_profile_claim_mismatch_fails_closed_before_port_calls(
    candidate_profile: dict,
    mismatch: str,
) -> None:
    authoritative_claims = _claims(
        source=SuitabilityContextSource.LONG_TERM_PROFILE,
        evidence_ref="canonical-profile-fact:skin_type",
    )
    candidate_claims = _claims(
        source=SuitabilityContextSource.LONG_TERM_PROFILE,
        evidence_ref="canonical-profile-fact:skin_type",
        **candidate_profile,
    )
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=NeverFacts(),
        decision=NeverDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=candidate_claims,
        authority=_authority(
            context_claims=authoritative_claims,
            profile_owner=_PROFILE_OWNER,
        ),
    )

    assert result.kind == "error"
    assert result.code == "suitability_provenance_mismatch"
    assert mismatch in result.provenance_mismatches
    assert not hasattr(result, "card_intent")


def test_profile_owner_mutation_cannot_hide_provenance_mismatch() -> None:
    candidate_owner = ProfileOwnerRef(
        scope="local_demo",
        subject_id="profile_0123456789abcdef",
    )
    authority_owner = ProfileOwnerRef(
        scope="local_demo",
        subject_id="profile_fedcba9876543210",
    )
    candidate_claims = _claims(
        source=SuitabilityContextSource.LONG_TERM_PROFILE,
        evidence_ref="canonical-profile-fact:skin_type",
        profile_owner=candidate_owner,
    )
    authoritative_claims = _claims(
        source=SuitabilityContextSource.LONG_TERM_PROFILE,
        evidence_ref="canonical-profile-fact:skin_type",
        profile_owner=authority_owner,
    )
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=NeverFacts(),
        decision=NeverDecision(),
    )

    with pytest.raises(ValidationError, match="frozen"):
        candidate_owner.subject_id = authority_owner.subject_id

    result = gate.prepare(
        _context(),
        context_claims=candidate_claims,
        authority=_authority(
            context_claims=authoritative_claims,
            profile_owner=authority_owner,
        ),
    )

    assert candidate_owner.subject_id == "profile_0123456789abcdef"
    assert result.kind == "error"
    assert result.code == "suitability_provenance_mismatch"
    assert "claim.profile_owner" in result.provenance_mismatches
    assert not hasattr(result, "card_intent")


def test_current_bundle_authority_mismatch_fails_closed() -> None:
    authoritative_claims = _claims(
        current_bundle_id="bundle_" + "b" * 32,
    )
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=NeverFacts(),
        decision=NeverDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=authoritative_claims,
        authority=_authority(
            current_bundle_id="bundle_" + "b" * 32,
            context_claims=authoritative_claims,
        ),
    )

    assert result.kind == "error"
    assert result.code == "suitability_provenance_mismatch"
    assert "current_bundle_id" in result.provenance_mismatches
    assert not hasattr(result, "card_intent")


def test_current_identity_authority_mismatch_fails_closed() -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=NeverFacts(),
        decision=NeverDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(confirmed_product_id=55),
    )

    assert result.kind == "error"
    assert result.code == "suitability_provenance_mismatch"
    assert "confirmed_product_id" in result.provenance_mismatches
    assert not hasattr(result, "card_intent")


def test_confirmed_identity_and_authorized_context_assess_exact_product(
) -> None:
    facts = RecordingFacts(_facts())
    decision = RecordingDecision()
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=facts,
        decision=decision,
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "assessed"
    assert result.decision_result.status == "suitable"
    assert result.decision_result.context.source is (
        SuitabilityContextSource.CURRENT_EXPLICIT_INPUT
    )
    assert result.card_intent.visible_product_ids == (53,)
    assert facts.calls == [53]
    assert len(decision.calls) == 1
    assert decision.calls[0].reference.product_id == 53


@pytest.mark.parametrize(
    ("source", "evidence_ref", "precedence"),
    [
        (
            SuitabilityContextSource.CURRENT_EXPLICIT_INPUT,
            "turn:current#skin",
            1,
        ),
        (
            SuitabilityContextSource.CONFIRMED_SESSION,
            "session:test:version=7#confirmed_skin",
            2,
        ),
        (
            SuitabilityContextSource.LONG_TERM_PROFILE,
            "profile:test:version=3#skin_type",
            3,
        ),
    ],
)
def test_each_authorized_context_source_is_typed_with_fixed_precedence(
    source: SuitabilityContextSource,
    evidence_ref: str,
    precedence: int,
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(_facts()),
        decision=RecordingDecision(),
    )
    claims = SuitabilityContextClaims(
        claims=(
            _claim(
                source=source,
                skin_target="sensitive",
                evidence_ref=evidence_ref,
            ),
        )
    )

    result = gate.prepare(
        _context(),
        context_claims=claims,
        authority=_authority(
            context_claims=claims,
            profile_owner=(
                _PROFILE_OWNER
                if source is SuitabilityContextSource.LONG_TERM_PROFILE
                else None
            ),
        ),
    )

    assert result.kind == "assessed"
    assert result.decision_result.context.source is source
    assert result.decision_result.context.precedence == precedence
    assert result.decision_result.context.evidence_ref == evidence_ref


def test_missing_canonical_facts_clarifies_without_decision() -> None:
    facts = MissingFacts()
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=facts,
        decision=NeverDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "clarification"
    assert result.code == "canonical_facts_unavailable"
    assert result.ordinal == 1
    assert result.image_id == "image_" + "1" * 32
    assert not hasattr(result, "card_intent")
    assert facts.calls == [53]


def test_mismatched_canonical_fact_identity_is_typed_error() -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=MismatchedFacts(),
        decision=NeverDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "error"
    assert result.code == "canonical_fact_mismatch"
    assert result.ordinal == 1
    assert result.image_id == "image_" + "1" * 32
    assert not hasattr(result, "card_intent")


def test_decision_cannot_swap_confirmed_product_or_card_intent() -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(_facts()),
        decision=SwappingDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert not hasattr(result, "card_intent")


def test_semantically_forged_decision_is_rejected() -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(_facts()),
        decision=ForgedSemanticDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "error"
    assert result.code == "decision_contract_mismatch"
    assert not hasattr(result, "card_intent")


def test_adapter_cannot_assign_nested_suitability_facts() -> None:
    decision = AssigningFactsDecision()
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(_facts()),
        decision=decision,
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert decision.mutation_error is not None
    assert result.kind == "assessed"
    assert result.decision_result.status == "suitable"
    assert result.decision_input.facts.suitable_skin == ("敏感肌适用",)


def test_adapter_request_is_isolated_from_local_recomputation() -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(_facts()),
        decision=BypassingFrozenFactsDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "assessed"
    assert result.decision_input.facts.suitable_skin == ("敏感肌适用",)
    assert result.decision_result.status == "suitable"
    assert result.decision_result.evaluated_skin_fact.values == (
        "敏感肌适用",
    )


def test_unknown_canonical_skin_fact_is_assessed_as_insufficient_one_card(
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(
            _facts(
                suitable_skin=None,
                suitable_skin_state=FactState.UNKNOWN,
            )
        ),
        decision=RecordingDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "assessed"
    assert result.decision_result.status == "insufficient_evidence"
    assert result.decision_result.status != "not_suitable"
    assert result.card_intent.visible_product_ids == (53,)


@pytest.mark.parametrize(
    "source_ref",
    [
        "ocr:upload-1#suitable_skin",
        "user-upload:image-1#suitable_skin",
        "model:skin-classifier-v1",
        "canonical:53#suitable_skin",
        "data/seed_dump.sql#product=53:suitable_skin",
    ],
)
def test_unapproved_suitability_evidence_fails_closed_with_zero_cards(
    source_ref: str,
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(
            _facts(suitable_skin_source_refs=(source_ref,))
        ),
        decision=RecordingDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "error"
    assert result.code == "canonical_evidence_invalid"
    assert not hasattr(result, "card_intent")


@pytest.mark.parametrize(
    ("adapter_side", "error"),
    [
        ("facts", RuntimeError("facts adapter secret")),
        ("facts", ValueError("facts adapter malformed")),
        ("decision", RuntimeError("decision adapter secret")),
        ("decision", OSError("decision adapter unavailable")),
    ],
)
def test_ordinary_adapter_exception_is_typed_sanitized_zero_card_error(
    adapter_side: str,
    error: Exception,
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=(
            RaisingFacts(error)
            if adapter_side == "facts"
            else RecordingFacts(_facts())
        ),
        decision=(
            RaisingDecision(error)
            if adapter_side == "decision"
            else RecordingDecision()
        ),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "error"
    assert result.code == "suitability_adapter_failure"
    assert "secret" not in result.message
    assert "malformed" not in result.message
    assert "unavailable" not in result.message
    assert not hasattr(result, "card_intent")


@pytest.mark.parametrize("adapter_side", ["facts", "decision"])
def test_ordinary_adapter_payload_exception_is_typed_zero_card_error(
    adapter_side: str,
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=(
            ReturningDumpRaisingFacts()
            if adapter_side == "facts"
            else RecordingFacts(_facts())
        ),
        decision=(
            ReturningDumpRaisingDecision()
            if adapter_side == "decision"
            else RecordingDecision()
        ),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "error"
    assert result.code == "suitability_adapter_failure"
    assert "secret" not in result.message
    assert not hasattr(result, "card_intent")


@pytest.mark.parametrize(
    "malformed_facts",
    [
        pytest.param(None, id="none"),
        pytest.param(object(), id="plain-object"),
        pytest.param(
            {"product_id": 53, "secret": "facts payload secret"},
            id="mapping",
        ),
    ],
)
def test_malformed_facts_adapter_return_is_sanitized_zero_card_error(
    malformed_facts: object,
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=ReturningFacts(malformed_facts),
        decision=NeverDecision(),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "error"
    assert result.code == "suitability_adapter_failure"
    assert "secret" not in result.message
    assert not hasattr(result, "card_intent")


@pytest.mark.parametrize(
    "malformed_decision",
    [
        pytest.param(None, id="none"),
        pytest.param(object(), id="plain-object"),
        pytest.param(
            {"status": "suitable", "secret": "decision payload secret"},
            id="mapping",
        ),
    ],
)
def test_malformed_decision_adapter_return_is_sanitized_zero_card_error(
    malformed_decision: object,
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(_facts()),
        decision=ReturningDecision(malformed_decision),
    )

    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    assert result.kind == "error"
    assert result.code == "suitability_adapter_failure"
    assert "secret" not in result.message
    assert not hasattr(result, "card_intent")


def test_process_control_exception_during_facts_normalization_propagates(
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=ReturningInterruptingDumpFacts(),
        decision=NeverDecision(),
    )

    with pytest.raises(KeyboardInterrupt):
        gate.prepare(
            _context(),
            context_claims=_claims(),
            authority=_authority(),
        )


def test_process_control_exception_during_decision_normalization_propagates(
) -> None:
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(_facts()),
        decision=ReturningInterruptingDumpDecision(),
    )

    with pytest.raises(KeyboardInterrupt):
        gate.prepare(
            _context(),
            context_claims=_claims(),
            authority=_authority(),
        )


@pytest.mark.parametrize("adapter_side", ["facts", "decision"])
@pytest.mark.parametrize(
    "error_type",
    [
        KeyboardInterrupt,
        SystemExit,
        GeneratorExit,
        asyncio.CancelledError,
    ],
)
def test_process_control_adapter_exception_propagates(
    adapter_side: str,
    error_type: type[BaseException],
) -> None:
    error = error_type()
    gate = _subject().SingleImageSuitabilityGate(
        decision_facts=(
            RaisingFacts(error)
            if adapter_side == "facts"
            else RecordingFacts(_facts())
        ),
        decision=(
            RaisingDecision(error)
            if adapter_side == "decision"
            else RecordingDecision()
        ),
    )

    with pytest.raises(error_type):
        gate.prepare(
            _context(),
            context_claims=_claims(),
            authority=_authority(),
        )


def test_preparation_result_is_a_discriminated_union() -> None:
    subject = _subject()
    gate = subject.SingleImageSuitabilityGate(
        decision_facts=RecordingFacts(_facts()),
        decision=RecordingDecision(),
    )
    result = gate.prepare(
        _context(),
        context_claims=_claims(),
        authority=_authority(),
    )

    parsed = TypeAdapter(
        subject.ImageSuitabilityPreparationResult
    ).validate_python(result.model_dump(mode="python"))

    assert isinstance(parsed, subject.AssessedSuitabilityPreparation)
    assert parsed.kind == "assessed"
    assert parsed.identity_state is IdentityState.CONFIRMED
    assert parsed.card_intent.visible_product_ids == (53,)
    assert parsed.decision_input.reference.product_id == 53


def test_preparation_variants_reject_cross_kind_codes() -> None:
    subject = _subject()

    with pytest.raises(ValidationError):
        subject.SuitabilityClarification(
            kind="clarification",
            code="canonical_fact_mismatch",
            message="wrong kind",
        )
    with pytest.raises(ValidationError):
        subject.SuitabilityPreparationError(
            kind="error",
            code="suitability_context_required",
            message="wrong kind",
            ordinal=1,
            image_id=_IMAGE_ID,
        )


def test_identity_clarification_requires_image_identity_metadata() -> None:
    subject = _subject()

    with pytest.raises(
        ValidationError,
        match="identity clarification requires",
    ):
        subject.SuitabilityClarification(
            kind="clarification",
            code="image_identity_ambiguous",
            message="需要确认图片身份。",
        )


def test_provenance_error_requires_exact_mismatch_metadata() -> None:
    subject = _subject()

    with pytest.raises(
        ValidationError,
        match="provenance mismatch requires",
    ):
        subject.SuitabilityPreparationError(
            kind="error",
            code="suitability_provenance_mismatch",
            message="上下文不一致。",
            ordinal=1,
            image_id=_IMAGE_ID,
        )


def test_clarification_and_error_variants_have_no_card_field() -> None:
    subject = _subject()
    clarification = subject.SuitabilityClarification(
        kind="clarification",
        code="suitability_context_required",
        message="请提供肤质。",
    )
    error = subject.SuitabilityPreparationError(
        kind="error",
        code="canonical_fact_mismatch",
        message="Canonical 事实不一致。",
        ordinal=1,
        image_id=_IMAGE_ID,
    )

    assert not hasattr(clarification, "card_intent")
    assert not hasattr(error, "card_intent")
    with pytest.raises(ValidationError):
        subject.SuitabilityClarification.model_validate(
            {
                **clarification.model_dump(mode="python"),
                "card_intent": {
                    "mode": "single",
                    "visible_product_ids": (53,),
                    "reason": "product",
                },
            }
        )
