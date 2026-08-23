from __future__ import annotations

import re
from typing import Literal

from app.guide.understanding.contracts import ReferenceDraft, SourceSpan
from app.guide.understanding.semantic_route_contracts import (
    SemanticRouteBindingAuthority,
)
from app.guide.understanding.source_grounding import (
    SourceGroundingError,
    ground_unique_text,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnReferenceMention,
)


class ReferenceAdmissionError(ValueError):
    def __init__(
        self,
        code: Literal[
            "missing_source",
            "ambiguous_source",
            "ambiguous",
            "unbound",
        ],
    ) -> None:
        self.code = code
        super().__init__(f"reference admission failed: {code}")


_ORDINAL_VALUE = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "①": 1,
    "②": 2,
    "③": 3,
    "④": 4,
}
_EXPLICIT_ORDINAL = re.compile(
    r"(?:第(?P<standard>[一二两三四1-4①②③④])"
    r"(?:款|个|张|支|瓶|项)?|图(?P<image>[一二两三四1-4])|"
    r"(?P<numbered>[一二两三四1-4])号|"
    r"(?:候选(?:里|中)?(?:排)?|排(?:在)?)"
    r"(?P<rank>[一二两三四1-4])(?:的)?)"
)


def admit_reference(
    *,
    message: str,
    mention: TurnReferenceMention,
    authority: SemanticRouteBindingAuthority,
) -> ReferenceDraft:
    if not isinstance(mention, TurnReferenceMention):
        raise TypeError("mention must be TurnReferenceMention")
    if not isinstance(authority, SemanticRouteBindingAuthority):
        raise TypeError(
            "authority must be SemanticRouteBindingAuthority"
        )
    try:
        grounded = ground_unique_text(message, mention.raw_text)
    except SourceGroundingError as failure:
        raise ReferenceAdmissionError(
            "missing_source"
            if failure.code == "missing"
            else "ambiguous_source"
        ) from None
    span = SourceSpan(start=grounded.start, end=grounded.end)
    ordinal = _explicit_ordinal(mention.raw_text)
    family = mention.object_family_hint

    if (
        family in {"product", "unknown", "topic"}
        and mention.plurality_hint == "batch"
    ):
        if not authority.current_batch_available:
            raise ReferenceAdmissionError("unbound")
        if (
            mention.batch_size_hint is not None
            and mention.batch_size_hint
            != len(authority.candidate_ordinals)
        ):
            raise ReferenceAdmissionError("ambiguous")
        return ReferenceDraft(
            kind="current_batch",
            ordinal=None,
            source_span=span,
        )

    if ordinal is not None:
        if family == "product":
            return _admit_ordinal(
                kind="candidate_ordinal",
                ordinal=ordinal,
                admitted=authority.candidate_ordinals,
                span=span,
            )
        if family == "image":
            return _admit_ordinal(
                kind="image_ordinal",
                ordinal=ordinal,
                admitted=authority.image_ordinals,
                span=span,
            )
        if family == "unknown":
            product_admitted = ordinal in authority.candidate_ordinals
            image_admitted = ordinal in authority.image_ordinals
            if product_admitted == image_admitted:
                raise ReferenceAdmissionError(
                    "ambiguous" if product_admitted else "unbound"
                )
            return ReferenceDraft(
                kind=(
                    "candidate_ordinal"
                    if product_admitted
                    else "image_ordinal"
                ),
                ordinal=ordinal,
                source_span=span,
            )
        raise ReferenceAdmissionError("unbound")

    if family == "product":
        if mention.plurality_hint == "batch":
            if not authority.current_batch_available:
                raise ReferenceAdmissionError("unbound")
            return ReferenceDraft(
                kind="current_batch",
                ordinal=None,
                source_span=span,
            )
        if not authority.current_item_available:
            if (
                not authority.candidate_ordinals
                and authority.current_image_ordinal is not None
            ):
                return ReferenceDraft(
                    kind="image_ordinal",
                    ordinal=authority.current_image_ordinal,
                    source_span=span,
                )
            if len(authority.candidate_ordinals) == 1:
                return ReferenceDraft(
                    kind="current_batch",
                    ordinal=None,
                    source_span=span,
                )
            raise ReferenceAdmissionError("unbound")
        return ReferenceDraft(
            kind="current_item",
            ordinal=None,
            source_span=span,
        )
    if family == "image":
        image_ordinal = authority.current_image_ordinal
        if (
            image_ordinal is None
            and len(authority.confirmed_image_ordinals) == 1
        ):
            image_ordinal = authority.confirmed_image_ordinals[0]
        if image_ordinal is None:
            raise ReferenceAdmissionError("unbound")
        return ReferenceDraft(
            kind="image_ordinal",
            ordinal=image_ordinal,
            source_span=span,
        )
    if family == "topic":
        if authority.current_topic is None:
            raise ReferenceAdmissionError("unbound")
        return ReferenceDraft(
            kind="current_topic",
            ordinal=None,
            source_span=span,
        )
    if family == "constraint":
        if not authority.previous_constraint_kinds:
            raise ReferenceAdmissionError("unbound")
        return ReferenceDraft(
            kind="previous_constraint",
            ordinal=None,
            source_span=span,
        )

    candidates: list[ReferenceDraft] = []
    if (
        mention.plurality_hint == "batch"
        and authority.current_batch_available
    ):
        candidates.append(
            ReferenceDraft(
                kind="current_batch",
                ordinal=None,
                source_span=span,
            )
        )
    if (
        mention.plurality_hint != "batch"
        and authority.current_item_available
    ):
        candidates.append(
            ReferenceDraft(
                kind="current_item",
                ordinal=None,
                source_span=span,
            )
        )
    if (
        mention.plurality_hint != "batch"
        and authority.current_image_ordinal is not None
    ):
        candidates.append(
            ReferenceDraft(
                kind="image_ordinal",
                ordinal=authority.current_image_ordinal,
                source_span=span,
            )
        )
    if authority.current_topic is not None:
        candidates.append(
            ReferenceDraft(
                kind="current_topic",
                ordinal=None,
                source_span=span,
            )
        )
    if len(candidates) != 1:
        raise ReferenceAdmissionError(
            "unbound" if not candidates else "ambiguous"
        )
    return candidates[0]


def _explicit_ordinal(raw_text: str) -> int | None:
    match = _EXPLICIT_ORDINAL.search(raw_text)
    if match is None:
        return None
    value = (
        match.group("standard")
        or match.group("image")
        or match.group("numbered")
        or match.group("rank")
    )
    return _ORDINAL_VALUE[value]


def _admit_ordinal(
    *,
    kind: Literal["candidate_ordinal", "image_ordinal"],
    ordinal: int,
    admitted: tuple[int, ...],
    span: SourceSpan,
) -> ReferenceDraft:
    if ordinal not in admitted:
        raise ReferenceAdmissionError("unbound")
    return ReferenceDraft(
        kind=kind,
        ordinal=ordinal,
        source_span=span,
    )


__all__ = [
    "ReferenceAdmissionError",
    "admit_reference",
]
