from __future__ import annotations

import pytest

from app.guide.intent.reference_admission import (
    ReferenceAdmissionError,
    admit_reference,
)
from app.guide.understanding.semantic_contracts import (
    ActiveConstraintKind,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticRouteBindingAuthority,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnReferenceMention,
)
from app.guide.understanding.contracts import TopicCode


def _authority(
    *,
    candidates: tuple[int, ...] = (),
    current_item: int | None = None,
    images: tuple[int, ...] = (),
    current_image: int | None = None,
    topic: TopicCode | None = None,
    previous: tuple[ActiveConstraintKind, ...] = (),
) -> SemanticRouteBindingAuthority:
    return SemanticRouteBindingAuthority(
        candidate_ordinals=candidates,
        current_item_ordinal=current_item,
        current_batch_available=bool(candidates),
        image_ordinals=images,
        current_image_ordinal=current_image,
        current_topic=topic,
        previous_constraint_kinds=previous,
        pending_clarification=None,
        active_dialogue=None,
        awaiting_reply=False,
    )


def _mention(
    raw_text: str,
    *,
    family: str,
    ordinal: int | None = None,
    plurality: str = "single",
    batch_size: int | None = None,
) -> TurnReferenceMention:
    payload = {
        "raw_text": raw_text,
        "object_family_hint": family,
        "ordinal_hint": ordinal,
        "plurality_hint": plurality,
    }
    if batch_size is not None:
        payload["batch_size_hint"] = batch_size
    return TurnReferenceMention.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    ("message", "mention", "authority", "kind", "ordinal"),
    [
        (
            "第二款呢",
            _mention("第二款", family="product", ordinal=2),
            _authority(candidates=(1, 2, 3)),
            "candidate_ordinal",
            2,
        ),
        (
            "候选里排二的那瓶怎么涂",
            _mention(
                "候选里排二的那瓶",
                family="product",
                ordinal=2,
            ),
            _authority(candidates=(1, 2)),
            "candidate_ordinal",
            2,
        ),
        (
            "排在二号的产品要放护肤哪一步",
            _mention("二号", family="product", ordinal=2),
            _authority(candidates=(1, 2)),
            "candidate_ordinal",
            2,
        ),
        (
            "把第②项的触感说细一点",
            _mention("第②项", family="product", ordinal=2),
            _authority(candidates=(1, 2)),
            "candidate_ordinal",
            2,
        ),
        (
            "第一张图找相似的",
            _mention("第一张图", family="image", ordinal=1),
            _authority(images=(1, 2)),
            "image_ordinal",
            1,
        ),
        (
            "这个适合我吗",
            _mention("这个", family="product"),
            _authority(candidates=(1,), current_item=1),
            "current_item",
            None,
        ),
        (
            "刚识别的这支防晒适不适合敏感肌",
            _mention("这支防晒", family="product"),
            _authority(images=(1,), current_image=1),
            "image_ordinal",
            1,
        ),
        (
            "两支怎么选",
            _mention(
                "两支",
                family="product",
                plurality="batch",
            ),
            _authority(candidates=(1, 2)),
            "current_batch",
            None,
        ),
        (
            "这个品类继续看",
            _mention("这个品类", family="topic"),
            _authority(topic=TopicCode.SUNSCREEN),
            "current_topic",
            None,
        ),
        (
            "预算改成三百",
            _mention("预算", family="constraint"),
            _authority(previous=(ActiveConstraintKind.BUDGET,)),
            "previous_constraint",
            None,
        ),
    ],
)
def test_reference_hints_are_admitted_by_current_authority(
    message,
    mention,
    authority,
    kind,
    ordinal,
) -> None:
    admitted = admit_reference(
        message=message,
        mention=mention,
        authority=authority,
    )

    assert admitted.kind == kind
    assert admitted.ordinal == ordinal
    assert message[
        admitted.source_span.start:admitted.source_span.end
    ] == mention.raw_text


def test_unknown_family_ordinal_collision_clarifies() -> None:
    with pytest.raises(ReferenceAdmissionError) as caught:
        admit_reference(
            message="第一个怎么样",
            mention=_mention(
                "第一个",
                family="unknown",
                ordinal=1,
            ),
            authority=_authority(
                candidates=(1, 2),
                images=(1, 2),
            ),
        )

    assert caught.value.code == "ambiguous"


def test_batch_plurality_overrides_non_authoritative_count_ordinal() -> None:
    admitted = admit_reference(
        message="这两款防晒怎么选",
        mention=_mention(
            "这两款",
            family="product",
            ordinal=2,
            plurality="batch",
        ),
        authority=_authority(candidates=(1, 2, 3)),
    )

    assert admitted.kind == "current_batch"
    assert admitted.ordinal is None


def test_typed_batch_size_rejects_ambiguous_subset() -> None:
    with pytest.raises(ReferenceAdmissionError) as caught:
        admit_reference(
            message="这两款防晒怎么选",
            mention=_mention(
                "这两款防晒",
                family="product",
                plurality="batch",
                batch_size=2,
            ),
            authority=_authority(candidates=(1, 2, 3)),
        )

    assert caught.value.code == "ambiguous"


def test_typed_batch_size_binds_complete_visible_batch() -> None:
    admitted = admit_reference(
        message="这两款防晒怎么选",
        mention=_mention(
            "这两款防晒",
            family="product",
            plurality="batch",
            batch_size=2,
        ),
        authority=_authority(candidates=(1, 2)),
    )

    assert admitted.kind == "current_batch"


def test_nonordinal_raw_text_cannot_invent_candidate_ordinal() -> None:
    admitted = admit_reference(
        message="它怎么样",
        mention=_mention(
            "它",
            family="product",
            ordinal=1,
        ),
        authority=_authority(
            candidates=(1, 2),
            current_item=2,
        ),
    )

    assert admitted.kind == "current_item"
    assert admitted.ordinal is None


def test_nonordinal_product_binds_only_visible_candidate_without_focus() -> None:
    admitted = admit_reference(
        message="这种适合吗",
        mention=_mention(
            "这种",
            family="product",
            ordinal=1,
        ),
        authority=_authority(candidates=(1,)),
    )

    assert admitted.kind == "current_batch"
    assert admitted.ordinal is None


def test_unbound_other_item_clarifies_instead_of_guessing_first() -> None:
    with pytest.raises(ReferenceAdmissionError) as caught:
        admit_reference(
            message="改成另一个吧",
            mention=_mention("另一个", family="product"),
            authority=_authority(candidates=(1, 2, 3)),
        )

    assert caught.value.code == "unbound"


def test_out_of_range_ordinal_clarifies() -> None:
    with pytest.raises(ReferenceAdmissionError) as caught:
        admit_reference(
            message="第三款呢",
            mention=_mention(
                "第三款",
                family="product",
                ordinal=3,
            ),
            authority=_authority(candidates=(1, 2)),
        )

    assert caught.value.code == "unbound"
