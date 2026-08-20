from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app.guide.decision.contracts import DecisionProductFacts
from app.guide.decision.image_suitability import (
    ImageSuitabilityDecisionFoundation,
    ImageSuitabilityDecisionPort,
    resolve_suitability_context,
)
from app.guide.decision.image_suitability_contracts import (
    ContextValue,
    ImageSuitabilityDecisionInput,
    ImageSuitabilityDecisionReference,
    ImageSuitabilityDecisionResult,
    SuitabilityCardIntent,
    SuitabilityContextClaims,
    SuitabilityContextSource,
)
from app.guide.decision.ports import DecisionFactPort
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.session_contract import SessionId
from app.guide.understanding.contracts import (
    OpaqueBundleId,
    OpaqueImageId,
)
from app.guide.understanding.image_contracts import IdentityState
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)


SuitabilityIdentityClarificationCode = Literal[
    "image_identity_ambiguous",
    "image_identity_low_confidence",
    "image_identity_ocr_conflict",
    "image_visual_unavailable",
    "image_identity_unconfirmed",
]
SuitabilityClarificationCode = Literal[
    "exactly_one_image_required",
    "image_identity_ambiguous",
    "image_identity_low_confidence",
    "image_identity_ocr_conflict",
    "image_visual_unavailable",
    "image_identity_unconfirmed",
    "suitability_context_required",
    "suitability_context_unsupported",
    "canonical_facts_unavailable",
]
SuitabilityErrorCode = Literal[
    "canonical_fact_mismatch",
    "canonical_evidence_invalid",
    "decision_contract_mismatch",
    "suitability_adapter_failure",
    "suitability_provenance_mismatch",
]
ImageSuitabilityResultCode = (
    SuitabilityClarificationCode | SuitabilityErrorCode
)
IssueMessage = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=240,
    ),
]
ProvenanceMismatches = Annotated[
    tuple[
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True,
                min_length=1,
                max_length=64,
            ),
        ],
        ...,
    ],
    Field(min_length=1, max_length=16),
]


_IDENTITY_CODES: dict[
    IdentityState,
    SuitabilityIdentityClarificationCode,
] = {
    IdentityState.AMBIGUOUS_CANDIDATES: "image_identity_ambiguous",
    IdentityState.LOW_CONFIDENCE: "image_identity_low_confidence",
    IdentityState.OCR_CONFLICT: "image_identity_ocr_conflict",
    IdentityState.VISUAL_UNAVAILABLE: "image_visual_unavailable",
}
_IDENTITY_CLARIFICATION_CODES = frozenset(
    {
        "image_identity_ambiguous",
        "image_identity_low_confidence",
        "image_identity_ocr_conflict",
        "image_visual_unavailable",
        "image_identity_unconfirmed",
    }
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SuitabilityAuthoritativeProfile(_StrictFrozen):
    """Server-read profile authority; never construct from client payloads."""

    owner: ProfileOwnerRef
    profile_version: int = Field(ge=1)
    confirmed: bool


class SuitabilityAuthoritativeInputs(_StrictFrozen):
    """Trusted current server state used to authenticate context claims."""

    current_bundle_id: OpaqueBundleId
    current_image_id: OpaqueImageId
    current_ordinal: Literal[1]
    identity_state: IdentityState
    confirmed_product_id: int | None = Field(default=None, ge=1)
    session_id: SessionId
    conversation_version: int = Field(ge=0)
    authoritative_context_claims: SuitabilityContextClaims
    profile: SuitabilityAuthoritativeProfile | None = None

    @model_validator(mode="after")
    def validate_identity_shape(self) -> Self:
        if self.identity_state is IdentityState.CONFIRMED:
            if self.confirmed_product_id is None:
                raise ValueError(
                    "confirmed authority requires a product identity"
                )
        elif self.confirmed_product_id is not None:
            raise ValueError(
                "unconfirmed authority forbids a product identity"
            )
        return self


class AssessedSuitabilityPreparation(_StrictFrozen):
    kind: Literal["assessed"] = "assessed"
    identity_state: Literal[IdentityState.CONFIRMED] = (
        IdentityState.CONFIRMED
    )
    decision_input: ImageSuitabilityDecisionInput
    decision_result: ImageSuitabilityDecisionResult
    card_intent: SuitabilityCardIntent

    @model_validator(mode="after")
    def validate_card_intent(self) -> Self:
        if self.card_intent != self.decision_result.card_intent:
            raise ValueError(
                "suitability card intent must match decision result"
            )
        return self


class SuitabilityClarification(_StrictFrozen):
    kind: Literal["clarification"] = "clarification"
    code: SuitabilityClarificationCode
    message: IssueMessage
    ordinal: Literal[1] | None = None
    image_id: OpaqueImageId | None = None
    identity_state: IdentityState | None = None
    context_source: SuitabilityContextSource | None = None
    unsupported_context_value: ContextValue | None = None

    @model_validator(mode="after")
    def validate_code_metadata(self) -> Self:
        image_metadata = (
            self.ordinal,
            self.image_id,
            self.identity_state,
        )
        context_metadata = (
            self.context_source,
            self.unsupported_context_value,
        )
        if self.code in _IDENTITY_CLARIFICATION_CODES:
            if any(value is None for value in image_metadata):
                raise ValueError(
                    "identity clarification requires ordinal, image, and "
                    "identity state"
                )
            expected_code = _IDENTITY_CODES.get(
                self.identity_state,
                "image_identity_unconfirmed",
            )
            if self.code != expected_code:
                raise ValueError(
                    "identity clarification code must match identity state"
                )
            if any(value is not None for value in context_metadata):
                raise ValueError(
                    "identity clarification forbids context metadata"
                )
            return self
        if self.code == "canonical_facts_unavailable":
            if (
                self.ordinal is None
                or self.image_id is None
                or self.identity_state is not None
            ):
                raise ValueError(
                    "Canonical facts clarification requires image reference"
                )
            if any(value is not None for value in context_metadata):
                raise ValueError(
                    "Canonical facts clarification forbids context metadata"
                )
            return self
        if self.code == "suitability_context_unsupported":
            if any(value is not None for value in image_metadata):
                raise ValueError(
                    "unsupported context forbids image issue metadata"
                )
            if any(value is None for value in context_metadata):
                raise ValueError(
                    "unsupported context requires source and value"
                )
            return self
        if any(value is not None for value in image_metadata):
            raise ValueError(
                "clarification code forbids image issue metadata"
            )
        if any(value is not None for value in context_metadata):
            raise ValueError(
                "clarification code forbids context issue metadata"
            )
        return self


class SuitabilityPreparationError(_StrictFrozen):
    kind: Literal["error"] = "error"
    code: SuitabilityErrorCode
    message: IssueMessage
    ordinal: Literal[1]
    image_id: OpaqueImageId
    provenance_mismatches: ProvenanceMismatches | None = None

    @model_validator(mode="after")
    def validate_code_metadata(self) -> Self:
        if self.code == "suitability_provenance_mismatch":
            if not self.provenance_mismatches:
                raise ValueError(
                    "provenance mismatch requires mismatch metadata"
                )
            if len(self.provenance_mismatches) != len(
                set(self.provenance_mismatches)
            ):
                raise ValueError(
                    "provenance mismatch metadata must be unique"
                )
            return self
        if self.provenance_mismatches is not None:
            raise ValueError(
                "only provenance mismatch accepts mismatch metadata"
            )
        return self


ImageSuitabilityPreparationResult = Annotated[
    AssessedSuitabilityPreparation
    | SuitabilityClarification
    | SuitabilityPreparationError,
    Field(discriminator="kind"),
]


class SingleImageSuitabilityGate:
    def __init__(
        self,
        *,
        decision_facts: DecisionFactPort,
        decision: ImageSuitabilityDecisionPort,
    ) -> None:
        self._decision_facts = decision_facts
        self._decision = decision

    def prepare(
        self,
        context: MultiImageTaskContext,
        *,
        context_claims: SuitabilityContextClaims,
        authority: SuitabilityAuthoritativeInputs,
    ) -> ImageSuitabilityPreparationResult:
        if context.mode != "suitability" or len(context.references) != 1:
            return _clarification(
                code="exactly_one_image_required",
                message="单图适配需要当前图片批次中恰好一张图片。",
            )
        reference = context.references[0]
        provenance_mismatches = _provenance_mismatches(
            context,
            reference,
            context_claims,
            authority,
        )
        if provenance_mismatches:
            return SuitabilityPreparationError(
                kind="error",
                code="suitability_provenance_mismatch",
                message=(
                    "单图适配上下文与服务器当前会话、图片或画像状态"
                    "不一致。"
                ),
                ordinal=reference.ordinal,
                image_id=reference.image_id,
                provenance_mismatches=provenance_mismatches,
            )
        if reference.identity_state is not IdentityState.CONFIRMED:
            return _identity_clarification(reference)
        resolution = resolve_suitability_context(context_claims)
        if resolution.kind == "absent":
            return _clarification(
                code="suitability_context_required",
                message="请明确提供本轮肤质，或先确认会话/长期画像肤质。",
            )
        if resolution.kind == "unsupported":
            return _clarification(
                code="suitability_context_unsupported",
                message="当前肤质信息不在已支持的适配范围内，请明确肤质。",
                context_source=resolution.source,
                unsupported_context_value=resolution.unsupported_value,
            )
        assert resolution.context is not None
        assert reference.confirmed_product_id is not None
        try:
            facts = self._decision_facts.get_decision_facts(
                reference.confirmed_product_id
            )
        except LookupError:
            return _clarification(
                code="canonical_facts_unavailable",
                message="图片对应商品缺少可审计的 Canonical 适配事实。",
                ordinal=reference.ordinal,
                image_id=reference.image_id,
            )
        except Exception:
            return _adapter_failure(reference)
        try:
            if not isinstance(facts, DecisionProductFacts):
                return _adapter_failure(reference)
            facts = DecisionProductFacts.model_validate(
                facts.model_dump(mode="python")
            )
        except Exception:
            return _adapter_failure(reference)
        if facts.product_id != reference.confirmed_product_id:
            return SuitabilityPreparationError(
                kind="error",
                code="canonical_fact_mismatch",
                message="Canonical 商品事实与图片确认身份不一致。",
                ordinal=reference.ordinal,
                image_id=reference.image_id,
            )
        try:
            decision_input = ImageSuitabilityDecisionInput(
                reference=ImageSuitabilityDecisionReference(
                    ordinal=1,
                    image_id=reference.image_id,
                    product_id=reference.confirmed_product_id,
                ),
                context=resolution.context,
                facts=facts,
            )
        except ValidationError:
            return SuitabilityPreparationError(
                kind="error",
                code="canonical_evidence_invalid",
                message=(
                    "Canonical 适配事实包含未批准或商品不匹配的"
                    "证据引用。"
                ),
                ordinal=reference.ordinal,
                image_id=reference.image_id,
            )
        except Exception:
            return _adapter_failure(reference)
        adapter_input = ImageSuitabilityDecisionInput.model_validate(
            decision_input.model_dump(mode="python")
        )
        try:
            adapter_result = self._decision.decide(adapter_input)
        except Exception:
            return _adapter_failure(reference)
        try:
            if not isinstance(
                adapter_result,
                ImageSuitabilityDecisionResult,
            ):
                return _adapter_failure(reference)
            decision_result = ImageSuitabilityDecisionResult.model_validate(
                adapter_result.model_dump(mode="python")
            )
        except Exception:
            return _adapter_failure(reference)
        expected_result = ImageSuitabilityDecisionFoundation().decide(
            decision_input
        )
        if decision_result != expected_result:
            return SuitabilityPreparationError(
                kind="error",
                code="decision_contract_mismatch",
                message="单图适配决策结果与确认身份或 Canonical 事实不一致。",
                ordinal=reference.ordinal,
                image_id=reference.image_id,
            )
        return AssessedSuitabilityPreparation(
            kind="assessed",
            decision_input=decision_input,
            decision_result=decision_result,
            card_intent=decision_result.card_intent,
        )


def _adapter_failure(
    reference: ImageTaskReference,
) -> SuitabilityPreparationError:
    return SuitabilityPreparationError(
        kind="error",
        code="suitability_adapter_failure",
        message="单图适配服务暂时不可用，请稍后重试。",
        ordinal=reference.ordinal,
        image_id=reference.image_id,
    )


def _identity_clarification(
    reference: ImageTaskReference,
) -> ImageSuitabilityPreparationResult:
    return _clarification(
        code=_IDENTITY_CODES.get(
            reference.identity_state,
            "image_identity_unconfirmed",
        ),
        message="图片身份尚未确认，不能判断单图适配。",
        ordinal=reference.ordinal,
        image_id=reference.image_id,
        identity_state=reference.identity_state,
    )


def _clarification(
    *,
    code: SuitabilityClarificationCode,
    message: str,
    ordinal: int | None = None,
    image_id: str | None = None,
    identity_state: IdentityState | None = None,
    context_source: SuitabilityContextSource | None = None,
    unsupported_context_value: str | None = None,
) -> ImageSuitabilityPreparationResult:
    return SuitabilityClarification(
        kind="clarification",
        code=code,
        message=message,
        ordinal=ordinal,
        image_id=image_id,
        identity_state=identity_state,
        context_source=context_source,
        unsupported_context_value=unsupported_context_value,
    )


def _provenance_mismatches(
    context: MultiImageTaskContext,
    reference: ImageTaskReference,
    claims: SuitabilityContextClaims,
    authority: SuitabilityAuthoritativeInputs,
) -> tuple[str, ...]:
    mismatches: list[str] = []
    if context.bundle_id != authority.current_bundle_id:
        mismatches.append("current_bundle_id")
    if reference.image_id != authority.current_image_id:
        mismatches.append("current_image_id")
    if reference.ordinal != authority.current_ordinal:
        mismatches.append("current_ordinal")
    if reference.identity_state is not authority.identity_state:
        mismatches.append("identity_state")
    if (
        reference.confirmed_product_id
        != authority.confirmed_product_id
    ):
        mismatches.append("confirmed_product_id")

    candidate_by_source = {
        claim.provenance.source_kind: claim
        for claim in claims.claims
    }
    authoritative_by_source = {
        claim.provenance.source_kind: claim
        for claim in authority.authoritative_context_claims.claims
    }
    if candidate_by_source.keys() != authoritative_by_source.keys():
        mismatches.append("claim.source_kind")

    for source, claim in candidate_by_source.items():
        provenance = claim.provenance
        authoritative_claim = authoritative_by_source.get(source)
        if authoritative_claim is not None:
            _append_mismatch(
                mismatches,
                "claim.skin_target",
                claim.skin_target,
                authoritative_claim.skin_target,
            )
            authoritative_provenance = (
                authoritative_claim.provenance
            )
            for field_name in (
                "current_bundle_id",
                "current_image_id",
                "session_id",
                "conversation_version",
                "evidence_ref",
                "profile_owner",
                "profile_version",
                "profile_confirmed",
            ):
                _append_mismatch(
                    mismatches,
                    f"claim.{field_name}",
                    getattr(provenance, field_name),
                    getattr(authoritative_provenance, field_name),
                )

        for field_name, expected in (
            ("current_bundle_id", authority.current_bundle_id),
            ("current_image_id", authority.current_image_id),
            ("session_id", authority.session_id),
            (
                "conversation_version",
                authority.conversation_version,
            ),
        ):
            _append_mismatch(
                mismatches,
                f"claim.{field_name}",
                getattr(provenance, field_name),
                expected,
            )

        if source is SuitabilityContextSource.LONG_TERM_PROFILE:
            profile = authority.profile
            if profile is None:
                mismatches.append("claim.profile_authority")
            else:
                _append_mismatch(
                    mismatches,
                    "claim.profile_owner",
                    provenance.profile_owner,
                    profile.owner,
                )
                _append_mismatch(
                    mismatches,
                    "claim.profile_version",
                    provenance.profile_version,
                    profile.profile_version,
                )
                _append_mismatch(
                    mismatches,
                    "claim.profile_confirmed",
                    provenance.profile_confirmed,
                    profile.confirmed,
                )
                if (
                    provenance.profile_confirmed is not True
                    or profile.confirmed is not True
                ):
                    mismatches.append("claim.profile_confirmed")

    return tuple(dict.fromkeys(mismatches))


def _append_mismatch(
    mismatches: list[str],
    label: str,
    actual,
    expected,
) -> None:
    if actual != expected:
        mismatches.append(label)
