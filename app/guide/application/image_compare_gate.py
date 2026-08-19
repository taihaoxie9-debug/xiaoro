from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.decision.image_compare import ImageCompareDecisionPort
from app.guide.decision.image_compare_contracts import (
    ImageCompareDecisionInput,
    ImageCompareDecisionItem,
    ImageCompareDecisionResult,
)
from app.guide.decision.ports import DecisionFactPort
from app.guide.retrieval.category_taxonomy import canonical_categories_for
from app.guide.retrieval.ports import CategoryCatalogPort, CategoryRecord
from app.guide.understanding.contracts import OpaqueImageId, TopicCode
from app.guide.understanding.image_contracts import IdentityState
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)


ImageCompareResultCode = Literal[
    "exactly_two_images_required",
    "image_identity_ambiguous",
    "image_identity_low_confidence",
    "image_identity_ocr_conflict",
    "image_visual_unavailable",
    "image_identity_unconfirmed",
    "duplicate_product_identity",
    "canonical_product_unavailable",
    "canonical_category_unavailable",
    "canonical_facts_unavailable",
    "cross_category_products",
    "canonical_fact_mismatch",
    "decision_contract_mismatch",
]


class ImageComparePreparationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: Literal["ready", "clarification", "error"]
    code: ImageCompareResultCode | None = None
    message: str | None = None
    ordinal: int | None = Field(default=None, ge=1, le=2)
    image_id: OpaqueImageId | None = None
    identity_state: IdentityState | None = None
    decision_input: ImageCompareDecisionInput | None = None
    decision_result: ImageCompareDecisionResult | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        issue_metadata = (
            self.code,
            self.message,
            self.ordinal,
            self.image_id,
            self.identity_state,
        )
        if self.kind == "ready":
            if (
                self.decision_input is None
                or self.decision_result is None
                or any(value is not None for value in issue_metadata)
            ):
                raise ValueError(
                    "ready image comparison requires only decision data"
                )
            return self
        if (
            self.code is None
            or not self.message
            or self.decision_input is not None
            or self.decision_result is not None
        ):
            raise ValueError(
                "failed image comparison requires only issue data"
            )
        return self


_IDENTITY_CODES: dict[IdentityState, ImageCompareResultCode] = {
    IdentityState.AMBIGUOUS_CANDIDATES: "image_identity_ambiguous",
    IdentityState.LOW_CONFIDENCE: "image_identity_low_confidence",
    IdentityState.OCR_CONFLICT: "image_identity_ocr_conflict",
    IdentityState.VISUAL_UNAVAILABLE: "image_visual_unavailable",
}


class TwoImageCompareGate:
    def __init__(
        self,
        *,
        category_catalog: CategoryCatalogPort,
        decision_facts: DecisionFactPort,
        decision: ImageCompareDecisionPort,
    ) -> None:
        self._category_catalog = category_catalog
        self._decision_facts = decision_facts
        self._decision = decision

    def prepare(
        self,
        context: MultiImageTaskContext,
    ) -> ImageComparePreparationResult:
        if context.mode != "compare" or len(context.references) != 2:
            return _clarification(
                code="exactly_two_images_required",
                message="两图比较需要当前图片批次中恰好两张图片。",
            )

        for reference in context.references:
            if reference.identity_state is not IdentityState.CONFIRMED:
                return _identity_clarification(reference)

        product_ids = tuple(
            _confirmed_product_id(reference)
            for reference in context.references
        )
        if len(set(product_ids)) != 2:
            return _clarification(
                code="duplicate_product_identity",
                message="两张图片指向同一商品，不能伪装成商品比较。",
            )

        category_result = self._load_categories(
            context.references,
            product_ids,
        )
        if isinstance(category_result, ImageComparePreparationResult):
            return category_result
        topic, category_records = category_result

        items: list[ImageCompareDecisionItem] = []
        for reference, product_id, category in zip(
            context.references,
            product_ids,
            category_records,
            strict=True,
        ):
            try:
                facts = self._decision_facts.get_decision_facts(product_id)
            except LookupError:
                return _canonical_facts_unavailable(reference)
            if facts.product_id != product_id:
                return ImageComparePreparationResult(
                    kind="error",
                    code="canonical_fact_mismatch",
                    message="Canonical 商品事实与图片身份不一致。",
                    ordinal=reference.ordinal,
                    image_id=reference.image_id,
                )
            items.append(
                ImageCompareDecisionItem(
                    ordinal=reference.ordinal,
                    image_id=reference.image_id,
                    product_id=product_id,
                    canonical_category=category.value,
                    facts=facts,
                )
            )

        decision_input = ImageCompareDecisionInput(
            bundle_id=context.bundle_id,
            topic=topic,
            items=(items[0], items[1]),
        )
        decision_result = self._decision.decide(decision_input)
        if not _decision_matches_input(decision_input, decision_result):
            return ImageComparePreparationResult(
                kind="error",
                code="decision_contract_mismatch",
                message="两图比较决策结果与输入不一致。",
            )
        return ImageComparePreparationResult(
            kind="ready",
            decision_input=decision_input,
            decision_result=decision_result,
        )

    def _load_categories(
        self,
        references: list[ImageTaskReference],
        product_ids: tuple[int, int],
    ) -> (
        tuple[TopicCode, tuple[CategoryRecord, CategoryRecord]]
        | ImageComparePreparationResult
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
                return _canonical_unavailable(reference)
            topic = _topic_for_record(record)
            if topic is None:
                return _clarification(
                    code="canonical_category_unavailable",
                    message="商品缺少可用于比较的 Canonical 品类。",
                    ordinal=reference.ordinal,
                    image_id=reference.image_id,
                )
            records.append(record)
            topics.append(topic)

        if topics[0] is not topics[1]:
            return _clarification(
                code="cross_category_products",
                message="两张图片属于不同商品品类，不能直接比较。",
            )
        return topics[0], (records[0], records[1])


def _confirmed_product_id(reference: ImageTaskReference) -> int:
    assert reference.confirmed_product_id is not None
    return reference.confirmed_product_id


def _identity_clarification(
    reference: ImageTaskReference,
) -> ImageComparePreparationResult:
    return _clarification(
        code=_IDENTITY_CODES.get(
            reference.identity_state,
            "image_identity_unconfirmed",
        ),
        message="图片身份尚未确认，不能进入两图比较。",
        ordinal=reference.ordinal,
        image_id=reference.image_id,
        identity_state=reference.identity_state,
    )


def _canonical_unavailable(
    reference: ImageTaskReference,
) -> ImageComparePreparationResult:
    return _clarification(
        code="canonical_product_unavailable",
        message="图片对应商品缺少可审计的 Canonical 记录。",
        ordinal=reference.ordinal,
        image_id=reference.image_id,
    )


def _canonical_facts_unavailable(
    reference: ImageTaskReference,
) -> ImageComparePreparationResult:
    return _clarification(
        code="canonical_facts_unavailable",
        message="图片对应商品缺少可用于比较的 Canonical 事实。",
        ordinal=reference.ordinal,
        image_id=reference.image_id,
    )


def _clarification(
    *,
    code: ImageCompareResultCode,
    message: str,
    ordinal: int | None = None,
    image_id: str | None = None,
    identity_state: IdentityState | None = None,
) -> ImageComparePreparationResult:
    return ImageComparePreparationResult(
        kind="clarification",
        code=code,
        message=message,
        ordinal=ordinal,
        image_id=image_id,
        identity_state=identity_state,
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


def _decision_matches_input(
    request: ImageCompareDecisionInput,
    result: ImageCompareDecisionResult,
) -> bool:
    expected_references = tuple(
        (item.ordinal, item.image_id, item.product_id)
        for item in request.items
    )
    actual_references = tuple(
        (item.ordinal, item.image_id, item.product_id)
        for item in result.references
    )
    return (
        result.bundle_id == request.bundle_id
        and result.topic is request.topic
        and result.ordered_product_ids
        == tuple(item.product_id for item in request.items)
        and actual_references == expected_references
    )
