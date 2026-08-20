from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.guide.understanding.contracts import (
    ImageBundle,
    OpaqueBundleId,
    OpaqueImageId,
)
from app.guide.understanding.image_contracts import (
    ImageIdentityObservation,
)
from app.guide.understanding.image_reference_parsing import (
    ImageReferenceDraft,
)
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)


TaskMode = Literal["identify", "similar", "suitability", "compare"]
ContextResultCode = Literal[
    "no_current_bundle",
    "identity_record_bundle_mismatch",
    "invalid_image_task",
]
ReferenceResultCode = Literal[
    "no_current_bundle",
    "image_reference_not_understood",
    "ambiguous_image_reference",
    "ordinal_out_of_range",
    "stale_bundle_context",
    "identity_record_bundle_mismatch",
]


class _StrictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MultiImageContextResult(_StrictResult):
    kind: Literal["ready", "clarification", "error"]
    code: ContextResultCode | None = None
    message: str | None = None
    context: MultiImageTaskContext | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.kind == "ready":
            if (
                self.context is None
                or self.code is not None
                or self.message is not None
            ):
                raise ValueError("ready result requires only context")
            return self
        if (
            self.context is not None
            or self.code is None
            or not self.message
        ):
            raise ValueError(
                "non-ready result requires code and message only"
            )
        return self


class ImageReferenceResolution(_StrictResult):
    kind: Literal["resolved", "clarification", "error"]
    code: ReferenceResultCode | None = None
    message: str | None = None
    bundle_id: OpaqueBundleId | None = None
    ordinal: int | None = None
    image_id: OpaqueImageId | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.kind == "resolved":
            if (
                self.code is not None
                or self.message is not None
                or self.bundle_id is None
                or self.ordinal is None
                or self.image_id is None
            ):
                raise ValueError(
                    "resolved result requires bundle, ordinal, and image"
                )
            return self
        if self.code is None or not self.message or self.image_id is not None:
            raise ValueError(
                "unresolved result requires code and message without image"
            )
        return self


def build_multi_image_context(
    *,
    mode: TaskMode,
    bundle: ImageBundle | None,
    identity_observations: Sequence[ImageIdentityObservation],
) -> MultiImageContextResult:
    if bundle is None:
        return MultiImageContextResult(
            kind="clarification",
            code="no_current_bundle",
            message="当前没有可引用的图片，请重新上传。",
        )

    observations_by_id = {
        observation.image_id: observation
        for observation in identity_observations
    }
    bundle_image_ids = {image.image_id for image in bundle.images}
    if (
        len(observations_by_id) != len(identity_observations)
        or set(observations_by_id) != bundle_image_ids
    ):
        return MultiImageContextResult(
            kind="error",
            code="identity_record_bundle_mismatch",
            message="图片身份记录与当前图片批次不一致。",
        )

    references = [
        ImageTaskReference(
            image_id=image.image_id,
            ordinal=image.ordinal,
            identity_state=observations_by_id[image.image_id].identity_state,
            confirmed_product_id=(
                observations_by_id[image.image_id].confirmed_product_id
            ),
        )
        for image in bundle.images
    ]
    try:
        context = MultiImageTaskContext(
            mode=mode,
            bundle_id=bundle.bundle_id,
            references=references,
        )
    except ValueError:
        return MultiImageContextResult(
            kind="error",
            code="invalid_image_task",
            message="图片数量与当前任务不匹配。",
        )
    return MultiImageContextResult(kind="ready", context=context)


def resolve_image_reference(
    draft: ImageReferenceDraft | None,
    *,
    bundle: ImageBundle | None,
    context: MultiImageTaskContext | None,
) -> ImageReferenceResolution:
    if bundle is None or context is None:
        return ImageReferenceResolution(
            kind="clarification",
            code="no_current_bundle",
            message="当前没有可引用的图片，请重新上传。",
        )
    if draft is None:
        return ImageReferenceResolution(
            kind="clarification",
            code="image_reference_not_understood",
            message="请明确说第一张、第二张、第三张或第四张。",
        )
    if draft.issue is not None:
        return ImageReferenceResolution(
            kind="clarification",
            code="ambiguous_image_reference",
            message="请一次明确指定一张图片。",
        )
    if context.bundle_id != bundle.bundle_id:
        return ImageReferenceResolution(
            kind="error",
            code="stale_bundle_context",
            message="图片批次已经变化，请基于当前图片重试。",
        )
    if not _context_matches_bundle(context, bundle):
        return ImageReferenceResolution(
            kind="error",
            code="identity_record_bundle_mismatch",
            message="图片引用与当前图片批次不一致。",
        )

    reference = next(
        (
            item
            for item in context.references
            if item.ordinal == draft.ordinal
        ),
        None,
    )
    if reference is None:
        return ImageReferenceResolution(
            kind="clarification",
            code="ordinal_out_of_range",
            message=(
                f"当前只有 {len(context.references)} 张图片，"
                f"没有第 {draft.ordinal} 张。"
            ),
            bundle_id=bundle.bundle_id,
            ordinal=draft.ordinal,
        )
    return ImageReferenceResolution(
        kind="resolved",
        bundle_id=bundle.bundle_id,
        ordinal=reference.ordinal,
        image_id=reference.image_id,
    )


def _context_matches_bundle(
    context: MultiImageTaskContext,
    bundle: ImageBundle,
) -> bool:
    return [
        (reference.image_id, reference.ordinal)
        for reference in context.references
    ] == [
        (image.image_id, image.ordinal)
        for image in bundle.images
    ]
