from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
    ProfileOwnerRef,
)
from app.guide.understanding.consultation_contracts import (
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.image_contracts import IdentityState
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)


def _profile_payload() -> dict[str, object]:
    return {
        "owner": ProfileOwnerRef(
            scope="local_demo",
            subject_id="profile_0123456789abcdef",
        ),
        "field": "skin_type",
        "value": "sensitive",
        "source_turn_id": "turn_0123456789abcdef",
        "source_kind": "confirmed_consultation",
        "confirmed_at": datetime(2026, 8, 9, tzinfo=timezone.utc),
        "profile_version": 1,
    }


def _conclusion_payload() -> dict[str, object]:
    return {
        "skin_target": "sensitive",
        "confidence": "medium",
        "evidence": ["recurrent_redness"],
        "uncertainties": ["stinging_unknown"],
        "escalation": "如持续红肿、疼痛或渗出，请停止护肤建议并就医。",
        "confirmed_by_user": False,
    }


def _reference(
    suffix: str,
    ordinal: int,
    *,
    identity_state: IdentityState = IdentityState.CONFIRMED,
    confirmed_product_id: int | None = 53,
) -> ImageTaskReference:
    return ImageTaskReference(
        image_id="image_" + suffix * 32,
        ordinal=ordinal,
        confirmed_product_id=confirmed_product_id,
        identity_state=identity_state,
    )


def _multi_image_payload() -> dict[str, object]:
    return {
        "mode": "compare",
        "bundle_id": "bundle_" + "a" * 32,
        "references": [
            _reference("b", 1, confirmed_product_id=53),
            _reference("c", 2, confirmed_product_id=55),
        ],
    }


@pytest.mark.parametrize(
    "source_kind",
    ["explicit_user", "confirmed_consultation"],
)
def test_confirmed_profile_fact_records_allowed_source_and_version(
    source_kind: str,
) -> None:
    payload = _profile_payload()
    payload["source_kind"] = source_kind

    fact = ConfirmedProfileFact(**payload)

    assert fact.source_kind == source_kind
    assert fact.profile_version == 1
    assert fact.confirmed_at.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "source_kind",
    ["model_inference", "temporary_budget", "short_term_symptom"],
)
def test_unconfirmed_or_temporary_data_is_not_a_profile_source(
    source_kind: str,
) -> None:
    payload = _profile_payload()
    payload["source_kind"] = source_kind

    with pytest.raises(ValidationError):
        ConfirmedProfileFact(**payload)


@pytest.mark.parametrize(
    "field",
    [
        "budget",
        "price_sensitivity",
        "transient_symptom",
        "unconfirmed_inference",
    ],
)
def test_profile_contract_has_no_non_durable_fact_field(
    field: str,
) -> None:
    payload = _profile_payload()
    payload["field"] = field

    with pytest.raises(ValidationError):
        ConfirmedProfileFact(**payload)


def test_profile_contracts_are_strict_and_forbid_extra_fields() -> None:
    payload = _profile_payload()
    payload["profile_version"] = "1"
    with pytest.raises(ValidationError):
        ConfirmedProfileFact(**payload)

    with pytest.raises(ValidationError):
        ProfileOwnerRef(
            scope="local_demo",
            subject_id="profile_0123456789abcdef",
            inferred=True,
        )


def test_profile_contracts_are_frozen_after_validation() -> None:
    owner = ProfileOwnerRef(
        scope="local_demo",
        subject_id="profile_0123456789abcdef",
    )
    fact = ConfirmedProfileFact(**_profile_payload())

    with pytest.raises(ValidationError, match="frozen"):
        owner.subject_id = "profile_changed_0123456789"
    with pytest.raises(ValidationError, match="frozen"):
        fact.value = "dry"
    assert owner.subject_id == "profile_0123456789abcdef"


@pytest.mark.parametrize(
    "confirmed_at",
    [
        datetime(2026, 8, 9, 12, 0),
        datetime(
            2026,
            8,
            9,
            12,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    ],
)
def test_confirmed_profile_fact_requires_utc_confirmation_time(
    confirmed_at: datetime,
) -> None:
    payload = _profile_payload()
    payload["confirmed_at"] = confirmed_at

    with pytest.raises(ValidationError, match="UTC"):
        ConfirmedProfileFact(**payload)


def test_consultation_conclusion_keeps_required_safety_context() -> None:
    conclusion = ProvisionalConsultationConclusion(**_conclusion_payload())

    assert conclusion.evidence == ("recurrent_redness",)
    assert conclusion.uncertainties == ("stinging_unknown",)
    assert conclusion.confidence == "medium"
    assert conclusion.escalation
    assert conclusion.confirmed_by_user is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", "certain"),
        ("evidence", []),
        ("escalation", "  "),
        ("confirmed_by_user", 0),
    ],
)
def test_consultation_conclusion_rejects_incomplete_or_untyped_safety_context(
    field: str,
    value: object,
) -> None:
    payload = _conclusion_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        ProvisionalConsultationConclusion(**payload)


def test_consultation_conclusion_forbids_unknown_fields() -> None:
    payload = _conclusion_payload()
    payload["diagnosis"] = "sensitive_skin"

    with pytest.raises(ValidationError):
        ProvisionalConsultationConclusion(**payload)


def test_multi_image_task_accepts_unique_contiguous_ordinals() -> None:
    task = MultiImageTaskContext(**_multi_image_payload())

    assert [item.ordinal for item in task.references] == [1, 2]
    assert [item.confirmed_product_id for item in task.references] == [53, 55]


@pytest.mark.parametrize(
    "mode",
    ["identify", "similar", "suitability"],
)
def test_single_image_task_modes_reject_multiple_images(
    mode: str,
) -> None:
    payload = _multi_image_payload()
    payload["mode"] = mode

    with pytest.raises(ValidationError, match="exactly one image"):
        MultiImageTaskContext(**payload)


@pytest.mark.parametrize(
    "ordinals",
    [[2, 3], [1, 3], [2, 1], [1, 1]],
)
def test_multi_image_task_rejects_non_contiguous_ordinals(
    ordinals: list[int],
) -> None:
    payload = _multi_image_payload()
    references = payload["references"]
    assert isinstance(references, list)
    for reference, ordinal in zip(references, ordinals, strict=True):
        reference.ordinal = ordinal

    with pytest.raises(ValidationError, match="ordinal"):
        MultiImageTaskContext(**payload)


def test_multi_image_task_rejects_duplicate_image_ids() -> None:
    payload = _multi_image_payload()
    references = payload["references"]
    assert isinstance(references, list)
    references[1] = references[1].model_copy(
        update={"image_id": references[0].image_id}
    )

    with pytest.raises(ValidationError, match="unique"):
        MultiImageTaskContext(**payload)


def test_confirmed_identity_requires_product_id() -> None:
    payload = _multi_image_payload()
    references = payload["references"]
    assert isinstance(references, list)
    references[0] = references[0].model_copy(
        update={"confirmed_product_id": None}
    )

    with pytest.raises(ValidationError, match="requires product ID"):
        MultiImageTaskContext(**payload)


@pytest.mark.parametrize(
    "identity_state",
    [state for state in IdentityState if state is not IdentityState.CONFIRMED],
)
def test_unconfirmed_identity_forbids_product_id(
    identity_state: IdentityState,
) -> None:
    payload = _multi_image_payload()
    references = payload["references"]
    assert isinstance(references, list)
    references[0] = references[0].model_copy(
        update={"identity_state": identity_state}
    )

    with pytest.raises(ValidationError, match="forbids product ID"):
        MultiImageTaskContext(**payload)


def test_compare_requires_at_least_two_images() -> None:
    payload = _multi_image_payload()
    payload["references"] = [payload["references"][0]]

    with pytest.raises(ValidationError, match="at least two"):
        MultiImageTaskContext(**payload)


def test_multi_image_contracts_are_strict_and_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ImageTaskReference(
            image_id="image_" + "b" * 32,
            ordinal="1",
            confirmed_product_id=53,
            identity_state=IdentityState.CONFIRMED,
        )

    payload = deepcopy(_multi_image_payload())
    payload["inferred_winner"] = 53
    with pytest.raises(ValidationError):
        MultiImageTaskContext(**payload)
