from __future__ import annotations

from typing import Annotated, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.guide.application.contracts import OwnerToken
from app.guide.decision.multi_image_compare import (
    MultiImageCompareDecisionFoundation,
    MultiImageCompareDecisionPort,
)
from app.guide.decision.multi_image_compare_contracts import (
    MultiImageCompareDecisionInput,
    MultiImageCompareDecisionItem,
    MultiImageCompareDecisionResult,
    MultiImageComparisonCardIntent,
)
from app.guide.decision.ports import DecisionFactPort
from app.guide.retrieval.category_taxonomy import canonical_categories_for
from app.guide.retrieval.ports import CategoryCatalogPort, CategoryRecord
from app.guide.session_contract import SessionId
from app.guide.understanding.contracts import (
    ImageBundle,
    OpaqueBundleId,
    OpaqueImageId,
    TopicCode,
)
from app.guide.understanding.image_contracts import IdentityState
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)


IdentityClarificationCode = Literal[
    "image_identity_ambiguous",
    "image_identity_low_confidence",
    "image_identity_ocr_conflict",
    "image_visual_unavailable",
    "image_identity_unconfirmed",
]
MultiImageCompareClarificationCode = Literal[
    "three_or_four_images_required",
    "image_identity_ambiguous",
    "image_identity_low_confidence",
    "image_identity_ocr_conflict",
    "image_visual_unavailable",
    "image_identity_unconfirmed",
    "duplicate_product_identity",
    "canonical_product_unavailable",
    "canonical_category_unavailable",
    "canonical_facts_unavailable",
    "canonical_decision_facts_unaudited",
    "cross_category_products",
]
MultiImageCompareErrorCode = Literal[
    "non_contiguous_image_ordinals",
    "bundle_authority_mismatch",
    "canonical_fact_mismatch",
    "decision_contract_mismatch",
]
IssueMessage = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=240,
    ),
]


_IDENTITY_CODES: dict[IdentityState, IdentityClarificationCode] = {
    IdentityState.AMBIGUOUS_CANDIDATES: "image_identity_ambiguous",
    IdentityState.LOW_CONFIDENCE: "image_identity_low_confidence",
    IdentityState.OCR_CONFLICT: "image_identity_ocr_conflict",
    IdentityState.VISUAL_UNAVAILABLE: "image_visual_unavailable",
}
_IDENTITY_CLARIFICATION_CODES = frozenset(_IDENTITY_CODES.values()) | {
    "image_identity_unconfirmed"
}
_REFERENCE_CLARIFICATION_CODES = frozenset(
    {
        "canonical_product_unavailable",
        "canonical_category_unavailable",
        "canonical_facts_unavailable",
        "canonical_decision_facts_unaudited",
    }
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MultiImageCompareBundleAuthorizationRequest(_StrictFrozen):
    session_id: SessionId
    bundle_id: OpaqueBundleId
    version: int = Field(ge=1)
    owner_token: OwnerToken = Field(repr=False)


class MultiImageCompareBundleAuthorizationPort(Protocol):
    def authorize(
        self,
        *,
        bundle_id: str,
        version: int,
        session_id: str,
        owner_token: str,
    ) -> ImageBundle: ...


class PreparedMultiImageComparison(_StrictFrozen):
    kind: Literal["ready"] = "ready"
    decision_input: MultiImageCompareDecisionInput
    decision_result: MultiImageCompareDecisionResult
    card_intent: MultiImageComparisonCardIntent

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.card_intent != self.decision_result.card_intent:
            raise ValueError(
                "multi-image card intent must match decision result"
            )
        return self


class MultiImageCompareClarification(_StrictFrozen):
    kind: Literal["clarification"] = "clarification"
    code: MultiImageCompareClarificationCode
    message: IssueMessage
    ordinal: int | None = Field(default=None, ge=1, le=4)
    image_id: OpaqueImageId | None = None
    identity_state: IdentityState | None = None

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        if self.code in _IDENTITY_CLARIFICATION_CODES:
            if (
                self.ordinal is None
                or self.image_id is None
                or self.identity_state is None
            ):
                raise ValueError(
                    "identity clarification requires image metadata"
                )
            expected = _IDENTITY_CODES.get(
                self.identity_state,
                "image_identity_unconfirmed",
            )
            if self.code != expected:
                raise ValueError(
                    "identity clarification code must match state"
                )
            return self
        if self.code in _REFERENCE_CLARIFICATION_CODES:
            if (
                self.ordinal is None
                or self.image_id is None
                or self.identity_state is not None
            ):
                raise ValueError(
                    "Canonical clarification requires image reference"
                )
            return self
        if any(
            value is not None
            for value in (
                self.ordinal,
                self.image_id,
                self.identity_state,
            )
        ):
            raise ValueError(
                "comparison clarification forbids image metadata"
            )
        return self


class MultiImageComparePreparationError(_StrictFrozen):
    kind: Literal["error"] = "error"
    code: MultiImageCompareErrorCode
    message: IssueMessage
    ordinal: int | None = Field(default=None, ge=1, le=4)
    image_id: OpaqueImageId | None = None

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        if self.code == "canonical_fact_mismatch":
            if self.ordinal is None or self.image_id is None:
                raise ValueError(
                    "Canonical fact mismatch requires image reference"
                )
            return self
        if self.ordinal is not None or self.image_id is not None:
            raise ValueError(
                "comparison error code forbids image reference"
            )
        return self


MultiImageComparePreparationResult = Annotated[
    PreparedMultiImageComparison
    | MultiImageCompareClarification
    | MultiImageComparePreparationError,
    Field(discriminator="kind"),
]


class ThreeToFourImageCompareGate:
    def __init__(
        self,
        *,
        bundle_authorizer: MultiImageCompareBundleAuthorizationPort,
        category_catalog: CategoryCatalogPort,
        decision_facts: DecisionFactPort,
        decision: MultiImageCompareDecisionPort,
    ) -> None:
        self._bundle_authorizer = bundle_authorizer
        self._category_catalog = category_catalog
        self._decision_facts = decision_facts
        self._decision = decision

    def prepare(
        self,
        context: MultiImageTaskContext,
        *,
        authorization: MultiImageCompareBundleAuthorizationRequest,
    ) -> MultiImageComparePreparationResult:
        count = len(context.references)
        if context.mode != "compare" or count not in (3, 4):
            return _clarification(
                code="three_or_four_images_required",
                message="多图比较需要当前图片批次中恰好三到四张图片。",
            )
        if [item.ordinal for item in context.references] != list(
            range(1, count + 1)
        ):
            return MultiImageComparePreparationError(
                code="non_contiguous_image_ordinals",
                message="图片序号必须从第一张开始连续并保持上传顺序。",
            )
        try:
            authorized = self._bundle_authorizer.authorize(
                bundle_id=authorization.bundle_id,
                version=authorization.version,
                session_id=authorization.session_id,
                owner_token=authorization.owner_token,
            )
            current_bundle = ImageBundle.model_validate(
                authorized.model_dump(mode="python")
            )
        except Exception:
            return MultiImageComparePreparationError(
                code="bundle_authority_mismatch",
                message="图片比较上下文与服务器授权图片批次不一致。",
            )
        if not _matches_authorized_bundle(
            context,
            current_bundle,
            authorization,
        ):
            return MultiImageComparePreparationError(
                code="bundle_authority_mismatch",
                message="图片比较上下文与服务器授权图片批次不一致。",
            )

        for reference in context.references:
            if reference.identity_state is not IdentityState.CONFIRMED:
                return _identity_clarification(reference)

        product_ids = tuple(
            _confirmed_product_id(reference)
            for reference in context.references
        )
        if len(set(product_ids)) != count:
            return _clarification(
                code="duplicate_product_identity",
                message="多张图片指向同一商品，不能伪装成商品比较。",
            )

        try:
            category_result = self._load_categories(
                context.references,
                product_ids,
            )
        except Exception:
            return _decision_contract_error()
        if isinstance(
            category_result,
            MultiImageCompareClarification,
        ):
            return category_result
        topic, category_records = category_result

        items: list[MultiImageCompareDecisionItem] = []
        for reference, product_id, category in zip(
            context.references,
            product_ids,
            category_records,
            strict=True,
        ):
            try:
                facts = self._decision_facts.get_decision_facts(product_id)
            except LookupError:
                return _reference_clarification(
                    code="canonical_facts_unavailable",
                    message="图片对应商品缺少可用于比较的 Canonical 事实。",
                    reference=reference,
                )
            except Exception:
                return _decision_contract_error()
            try:
                if facts.product_id != product_id:
                    return MultiImageComparePreparationError(
                        code="canonical_fact_mismatch",
                        message="Canonical 商品事实与图片确认身份不一致。",
                        ordinal=reference.ordinal,
                        image_id=reference.image_id,
                    )
                if not facts.price_source_refs:
                    return _reference_clarification(
                        code="canonical_decision_facts_unaudited",
                        message="图片对应商品缺少可审计的 Canonical 比较事实。",
                        reference=reference,
                    )
                item = MultiImageCompareDecisionItem(
                    ordinal=reference.ordinal,
                    image_id=reference.image_id,
                    product_id=product_id,
                    canonical_category=category.value,
                    facts=facts,
                )
            except Exception:
                return _decision_contract_error()
            items.append(item)

        try:
            canonical_decision_input = MultiImageCompareDecisionInput(
                bundle_id=context.bundle_id,
                topic=topic,
                items=tuple(items),
            ).model_copy(deep=True)
            adapter_input = canonical_decision_input.model_copy(deep=True)
            adapter_result = self._decision.decide(adapter_input)
            adapter_input_unchanged = adapter_input == canonical_decision_input
            decision_result = (
                MultiImageCompareDecisionResult.model_validate(
                    adapter_result.model_dump(mode="python")
                )
            )
            expected_result = MultiImageCompareDecisionFoundation().decide(
                canonical_decision_input.model_copy(deep=True)
            )
            prepared = PreparedMultiImageComparison(
                decision_input=canonical_decision_input.model_copy(deep=True),
                decision_result=decision_result,
                card_intent=decision_result.card_intent,
            )
        except Exception:
            return _decision_contract_error()
        if (
            not adapter_input_unchanged
            or decision_result != expected_result
        ):
            return _decision_contract_error()
        return prepared

    def _load_categories(
        self,
        references: list[ImageTaskReference],
        product_ids: tuple[int, ...],
    ) -> (
        tuple[TopicCode, tuple[CategoryRecord, ...]]
        | MultiImageCompareClarification
    ):
        selected: dict[int, CategoryRecord] = {}
        duplicates: set[int] = set()
        for record in self._category_catalog.iter_category_records():
            if record.product_id not in product_ids:
                continue
            if record.product_id in selected:
                duplicates.add(record.product_id)
            selected[record.product_id] = record

        records: list[CategoryRecord] = []
        topics: list[TopicCode] = []
        for reference, product_id in zip(
            references,
            product_ids,
            strict=True,
        ):
            record = selected.get(product_id)
            if record is None or product_id in duplicates:
                return _reference_clarification(
                    code="canonical_product_unavailable",
                    message="图片对应商品缺少唯一可审计的 Canonical 记录。",
                    reference=reference,
                )
            topic = _topic_for_record(record)
            if topic is None:
                return _reference_clarification(
                    code="canonical_category_unavailable",
                    message="商品缺少可用于比较的 Canonical 品类。",
                    reference=reference,
                )
            records.append(record)
            topics.append(topic)

        if len(set(topics)) != 1:
            return _clarification(
                code="cross_category_products",
                message="多张图片属于不同商品品类，不能直接比较。",
            )
        return topics[0], tuple(records)


def _confirmed_product_id(reference: ImageTaskReference) -> int:
    assert reference.confirmed_product_id is not None
    return reference.confirmed_product_id


def _identity_clarification(
    reference: ImageTaskReference,
) -> MultiImageCompareClarification:
    return _clarification(
        code=_IDENTITY_CODES.get(
            reference.identity_state,
            "image_identity_unconfirmed",
        ),
        message="图片身份尚未确认，不能进入多图比较。",
        ordinal=reference.ordinal,
        image_id=reference.image_id,
        identity_state=reference.identity_state,
    )


def _reference_clarification(
    *,
    code: Literal[
        "canonical_product_unavailable",
        "canonical_category_unavailable",
        "canonical_facts_unavailable",
        "canonical_decision_facts_unaudited",
    ],
    message: str,
    reference: ImageTaskReference,
) -> MultiImageCompareClarification:
    return _clarification(
        code=code,
        message=message,
        ordinal=reference.ordinal,
        image_id=reference.image_id,
    )


def _clarification(
    *,
    code: MultiImageCompareClarificationCode,
    message: str,
    ordinal: int | None = None,
    image_id: str | None = None,
    identity_state: IdentityState | None = None,
) -> MultiImageCompareClarification:
    return MultiImageCompareClarification(
        code=code,
        message=message,
        ordinal=ordinal,
        image_id=image_id,
        identity_state=identity_state,
    )


def _decision_contract_error() -> MultiImageComparePreparationError:
    return MultiImageComparePreparationError(
        code="decision_contract_mismatch",
        message="多图比较决策结果与确认身份或 Canonical 事实不一致。",
    )


def _matches_authorized_bundle(
    context: MultiImageTaskContext,
    bundle: ImageBundle,
    authorization: MultiImageCompareBundleAuthorizationRequest,
) -> bool:
    return (
        bundle.session_id == authorization.session_id
        and bundle.bundle_id == authorization.bundle_id
        and bundle.version == authorization.version
        and context.bundle_id == bundle.bundle_id
        and tuple(
            (reference.image_id, reference.ordinal)
            for reference in context.references
        )
        == tuple(
            (image.image_id, image.ordinal)
            for image in bundle.images
        )
    )


def _topic_for_record(record: CategoryRecord) -> TopicCode | None:
    if record.state != "known" or record.value is None:
        return None
    return next(
        (
            topic
            for topic in TopicCode
            if record.value in canonical_categories_for(topic)
        ),
        None,
    )
