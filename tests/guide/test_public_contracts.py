from __future__ import annotations

import importlib
import importlib.util
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from pydantic import TypeAdapter


CONTRACT_MODULES = {
    "UserTurn": "application",
    "PublicImageError": "application",
    "StructuredUnderstanding": "understanding",
    "BudgetRevisionDraft": "understanding",
    "SkinRevisionDraft": "understanding",
    "FollowupDraft": "understanding",
    "ImageBundle": "understanding",
    "ImageObservation": "understanding",
    "TaskPlan": "intent",
    "BudgetRevisionPlan": "intent",
    "SkinRevisionPlan": "intent",
    "FollowupPlan": "intent",
    "CandidateRef": "retrieval",
    "CanonicalField": "retrieval",
    "CanonicalProduct": "retrieval",
    "RetrievalResult": "retrieval",
    "WinnerStatus": "decision",
    "DecisionResult": "decision",
    "FollowupDecisionResult": "decision",
    "ResponsePlan": "presentation",
    "ConversationVersionRef": "feedback",
    "FeedbackEventRef": "feedback",
    "RecommendationQueryContext": "feedback",
    "DisplayedCandidateRef": "feedback",
    "ConversationSnapshot": "feedback",
}


def contract(name: str) -> type[Any]:
    module = importlib.import_module(f"app.guide.{CONTRACT_MODULES[name]}")
    return getattr(module, name)


def image_payload(image_id: str = "image-1", ordinal: int = 1) -> dict[str, Any]:
    return {
        "image_id": image_id,
        "ordinal": ordinal,
        "content_sha256": "a" * 64,
        "media_type": "image/jpeg",
        "image_format": "JPEG",
        "width": 4,
        "height": 3,
        "byte_size": 631,
    }


def valid_payloads() -> dict[str, dict[str, Any]]:
    created_at = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    canonical_field = {
        "key": "price",
        "value": 329.0,
        "field_origin": "base_product_row",
        "resolved_state": "known",
        "source_classes": ["base_product_row"],
        "source_refs": ["data/seed_dump.sql#product=26"],
        "evidence_status": None,
    }
    conversation_version = {
        "session_id": "session-1",
        "conversation_version": 3,
    }
    return {
        "UserTurn": {
            "identity": {
                "session_id": "session-1",
                "request_id": "request_session_1_0003",
                "turn_id": "turn_session_1_0003",
            },
            "session_id": "session-1",
            "message": "compare the products in these two images",
            "image_bundle_id": "bundle_" + "a" * 32,
            "image_bundle_version": 1,
            "image_bundle_token": "owner_" + "b" * 43,
            "conversation_version": 3,
        },
        "PublicImageError": {
            "code": importlib.import_module(
                "app.guide.application"
            ).ImageErrorCode.IMAGE_BUNDLE_UNAVAILABLE,
            "message": "图片引用不可用，请重新上传。",
            "ordinal": None,
        },
        "StructuredUnderstanding": {
            "goal": importlib.import_module(
                "app.guide.understanding"
            ).UnderstandingGoal.RECOMMENDATION,
            "topic": importlib.import_module(
                "app.guide.understanding"
            ).TopicCode.SUNSCREEN,
            "observations": ["user supplied two images"],
            "exact_constraints": [
                {
                    "kind": "budget",
                    "minimum": None,
                    "maximum": Decimal("500"),
                },
                {
                    "kind": "category",
                    "value": importlib.import_module(
                        "app.guide.understanding"
                    ).TopicCode.SUNSCREEN,
                },
            ],
            "semantic_proposals": ["prefer lightweight texture"],
            "signal_trace": [
                {
                    "field": "goal",
                    "exact_value": "recommendation",
                    "semantic_value": "recommendation",
                    "resolution": "agree",
                }
            ],
            "image_references": ["image-1", "image-2"],
            "uncertainties": [
                {
                    "code": "missing_category",
                    "detail": "needs category",
                }
            ],
            "confidence": 0.8,
        },
        "BudgetRevisionDraft": {
            "maximum": Decimal("100"),
            "issue": None,
        },
        "SkinRevisionDraft": {
            "target": importlib.import_module(
                "app.guide.understanding"
            ).SkinTarget.SENSITIVE,
            "issue": None,
        },
        "FollowupDraft": {
            "action": importlib.import_module(
                "app.guide.understanding"
            ).FollowupAction.ORDINAL_REFERENCE,
            "ordinal": 2,
            "issue": None,
            "source_span": {"start": 0, "end": 4},
        },
        "ImageObservation": image_payload(
            "image_" + "c" * 32
        ),
        "ImageBundle": {
            "bundle_id": "bundle_" + "a" * 32,
            "session_id": "session-1",
            "owner_token_sha256": "b" * 64,
            "version": 1,
            "created_at": created_at,
            "expires_at": created_at + timedelta(minutes=5),
            "images": [
                image_payload("image_" + "c" * 32),
                image_payload("image_" + "d" * 32, 2),
            ],
        },
        "TaskPlan": {
            "mode": "recommend",
            "recommendation_mode": "explore",
            "recommendation_mode_basis": "bounded_exploration",
            "recommendation_count": 3,
            "referenced_image_ids": ["image-1", "image-2"],
            "constraints": [
                {
                    "kind": "category",
                    "value": importlib.import_module(
                        "app.guide.understanding"
                    ).TopicCode.SUNSCREEN,
                },
                {
                    "kind": "budget",
                    "minimum": None,
                    "maximum": Decimal("500"),
                },
            ],
            "required_evidence": ["canonical_product"],
            "clarification": None,
        },
        "BudgetRevisionPlan": {
            "mode": "revise",
            "recommendation_mode": "explore",
            "recommendation_mode_basis": "bounded_exploration",
            "recommendation_count": 3,
            "constraints": [
                {
                    "kind": "category",
                    "value": importlib.import_module(
                        "app.guide.understanding"
                    ).TopicCode.SERUM,
                },
                {
                    "kind": "budget",
                    "minimum": None,
                    "maximum": Decimal("100"),
                },
                {
                    "kind": "skin",
                    "value": importlib.import_module(
                        "app.guide.understanding"
                    ).SkinTarget.SENSITIVE,
                },
                {
                    "kind": "efficacy",
                    "value": importlib.import_module(
                        "app.guide.understanding"
                    ).EfficacyTarget.REPAIR,
                },
            ],
            "clarification": None,
        },
        "SkinRevisionPlan": {
            "mode": "revise",
            "recommendation_mode": "explore",
            "recommendation_mode_basis": "bounded_exploration",
            "recommendation_count": 3,
            "constraints": [
                {
                    "kind": "category",
                    "value": importlib.import_module(
                        "app.guide.understanding"
                    ).TopicCode.SERUM,
                },
                {
                    "kind": "budget",
                    "minimum": None,
                    "maximum": Decimal("500"),
                },
                {
                    "kind": "skin",
                    "value": importlib.import_module(
                        "app.guide.understanding"
                    ).SkinTarget.SENSITIVE,
                },
                {
                    "kind": "efficacy",
                    "value": importlib.import_module(
                        "app.guide.understanding"
                    ).EfficacyTarget.REPAIR,
                },
                {
                    "kind": "exclude",
                    "value": "酒精",
                },
            ],
            "clarification": None,
        },
        "FollowupPlan": {
            "mode": "followup",
            "action": importlib.import_module(
                "app.guide.understanding"
            ).FollowupAction.ORDINAL_REFERENCE,
            "ordinal": 2,
            "clarification": None,
        },
        "CandidateRef": {
            "product_id": 26,
            "source": "canonical",
            "canonical_category": "防晒",
            "retrieval_reason": "matched image reference",
        },
        "CanonicalField": canonical_field,
        "CanonicalProduct": {
            "product_id": 26,
            "schema_version": "canonical-decision-product-v1",
            "fields": {"price": canonical_field},
        },
        "RetrievalResult": {
            "candidates": [
                {
                    "product_id": 26,
                    "source": "canonical",
                    "canonical_category": "防晒",
                    "retrieval_reason": "matched image reference",
                }
            ],
            "knowledge_evidence": [{"evidence_id": "knowledge-1"}],
            "review_evidence": [],
            "memory_evidence": [],
            "missing_sources": ["reviews"],
        },
        "DecisionResult": {
            "ordered_product_ids": [26],
            "winner_status": contract("WinnerStatus").SELECTED,
            "winner_product_id": 26,
            "evaluations": [
                {
                    "product_id": 26,
                    "disposition": "eligible",
                    "price": Decimal("329.0"),
                    "skin_match": "matched",
                    "efficacy_match": "not_applicable",
                    "matched_efficacies": [],
                    "reasons": ["hard_constraints_passed"],
                }
            ],
            "comparison_dimensions": ["price"],
            "risk_findings": [],
            "evidence_refs": ["data/seed_dump.sql#product=26"],
            "tie_reason": None,
        },
        "FollowupDecisionResult": {
            "action": importlib.import_module(
                "app.guide.understanding"
            ).FollowupAction.ORDINAL_REFERENCE,
            "ordinal": 2,
            "status": "selected",
            "source_candidate_ids": [91, 38],
            "selected_product_ids": [38],
            "evidence_refs": ["ordinal=2"],
        },
        "ResponsePlan": {
            "sections": ["recommendation"],
            "structured_events": [
                {
                    "type": "product_card",
                    "product_id": 26,
                    "category_profile": importlib.import_module(
                        "app.guide.retrieval.category_profiles"
                    ).CategoryProfile.SUNCARE,
                    "category_facts": [],
                    "name": "测试商品",
                    "brand": "测试品牌",
                    "category": "防晒",
                    "price": None,
                    "skin_match": "not_applicable",
                    "matched_efficacies": [],
                    "fact_warnings": [],
                }
            ],
            "text_generation_context": {"winner_product_id": 26},
            "followup_actions": [{"type": "ask_clarification"}],
        },
        "ConversationVersionRef": conversation_version,
        "FeedbackEventRef": {
            "event_id": "feedback-event-1",
            "conversation_version": conversation_version,
        },
        "RecommendationQueryContext": {
            "category": "serum",
            "recommendation_mode_basis": "bounded_exploration",
            "budget_minimum": None,
            "budget_maximum": Decimal("500"),
            "skin": "sensitive",
            "efficacy": "repair",
            "exclusions": ["酒精"],
        },
        "DisplayedCandidateRef": {
            "product_id": 91,
            "ordinal": 1,
            "skin_match": "unknown",
            "matched_efficacies": ["修护"],
        },
        "ConversationSnapshot": {
            "session_id": "session-1",
            "version": 1,
            "active_owner": importlib.import_module(
                "app.guide.intent.responsibility_matrix"
            ).Responsibility.RECOMMENDATION,
            "active_focus": {
                "slot": "recommendation",
                "object_id": None,
                "ordinal": None,
            },
            "recommendation_slot": {
                "kind": "recommendation",
                "query_context": {
                    "category": "serum",
                    "recommendation_mode_basis": "bounded_exploration",
                    "budget_minimum": None,
                    "budget_maximum": Decimal("500"),
                    "skin": "sensitive",
                    "efficacy": "repair",
                    "exclusions": [],
                },
                "candidates": [
                    {
                        "product_id": 91,
                        "ordinal": 1,
                        "skin_match": "unknown",
                        "matched_efficacies": ["修护"],
                    }
                ],
                "empty_result": False,
                "focused_candidate_ordinal": None,
            },
        },
    }


@pytest.mark.parametrize("name", CONTRACT_MODULES)
def test_public_contract_is_exported_by_its_owning_layer(name: str) -> None:
    exported = contract(name)

    if name == "WinnerStatus":
        assert issubclass(exported, Enum)
    else:
        assert issubclass(exported, BaseModel)
        assert exported.model_config["strict"] is True
        assert exported.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "name",
    [name for name in CONTRACT_MODULES if name != "WinnerStatus"],
)
def test_public_contract_has_deterministic_json_round_trip(name: str) -> None:
    model = contract(name)
    instance = model.model_validate(valid_payloads()[name])

    encoded = instance.model_dump_json()
    restored = model.model_validate_json(encoded, strict=False)

    assert restored == instance
    assert restored.model_dump(mode="json") == instance.model_dump(mode="json")


@pytest.mark.parametrize(
    "name",
    [name for name in CONTRACT_MODULES if name != "WinnerStatus"],
)
def test_public_contract_rejects_extra_fields(name: str) -> None:
    model = contract(name)
    payload = deepcopy(valid_payloads()[name])
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("name", "field", "invalid_value"),
    [
        ("UserTurn", "conversation_version", "3"),
        ("UserTurn", "image_bundle_version", "1"),
        ("StructuredUnderstanding", "goal", "recommendation"),
        ("StructuredUnderstanding", "confidence", "0.8"),
        ("ImageObservation", "ordinal", "1"),
        ("TaskPlan", "referenced_image_ids", "image-1"),
        ("CandidateRef", "product_id", "26"),
        ("CanonicalField", "source_classes", "base_product_row"),
        ("CanonicalProduct", "fields", []),
        ("RetrievalResult", "missing_sources", "reviews"),
        ("DecisionResult", "ordered_product_ids", ["26"]),
        ("ResponsePlan", "sections", "summary"),
        ("ConversationVersionRef", "conversation_version", "3"),
        (
            "FeedbackEventRef",
            "conversation_version",
            {
                "session_id": "session-1",
                "conversation_version": "3",
            },
        ),
    ],
)
def test_public_contract_rejects_type_coercion(
    name: str,
    field: str,
    invalid_value: Any,
) -> None:
    model = contract(name)
    payload = deepcopy(valid_payloads()[name])
    payload[field] = invalid_value

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_structured_understanding_normalizes_frozen_legacy_payload() -> None:
    model = contract("StructuredUnderstanding")
    legacy_payload = deepcopy(valid_payloads()["StructuredUnderstanding"])
    legacy_payload["goal"] = "recommend"
    legacy_payload.pop("signal_trace")

    understanding = model.model_validate(legacy_payload)

    assert (
        understanding.goal
        is importlib.import_module(
            "app.guide.understanding"
        ).UnderstandingGoal.RECOMMENDATION
    )
    assert understanding.signal_trace == []
    assert understanding.model_dump(mode="json")["goal"] == "recommendation"
    assert understanding.model_dump(mode="json")["signal_trace"] == []

    legacy_json_payload = understanding.model_dump(mode="json")
    legacy_json_payload["goal"] = "recommend"
    legacy_json_payload.pop("signal_trace")
    restored = model.model_validate_json(json.dumps(legacy_json_payload))
    assert restored.goal is understanding.goal
    assert restored.signal_trace == []


def test_typed_ordinal_reference_is_public_from_understanding_to_task() -> None:
    source_span = {"start": 14, "end": 17}
    understanding_payload = deepcopy(
        valid_payloads()["StructuredUnderstanding"]
    )
    understanding_payload["references"] = [
        {
            "kind": "candidate_ordinal",
            "ordinal": 2,
            "source_span": source_span,
        }
    ]
    task_payload = deepcopy(valid_payloads()["TaskPlan"])
    task_payload["references"] = [
        {
            "kind": "candidate_ordinal",
            "ordinal": 2,
            "source_span": source_span,
        }
    ]

    understanding = contract("StructuredUnderstanding").model_validate(
        understanding_payload
    )
    task = contract("TaskPlan").model_validate(task_payload)

    assert understanding.references[0].ordinal == 2
    assert understanding.references[0].source_span.model_dump() == source_span
    assert task.references[0].ordinal == 2
    assert task.references[0].source_span.model_dump() == source_span


def test_public_reference_fields_default_empty_for_legacy_payloads() -> None:
    understanding = contract("StructuredUnderstanding").model_validate(
        valid_payloads()["StructuredUnderstanding"]
    )
    task = contract("TaskPlan").model_validate(
        valid_payloads()["TaskPlan"]
    )

    assert understanding.references == []
    assert task.references == []


def test_structured_understanding_rejects_unprojected_exact_reference() -> None:
    payload = deepcopy(valid_payloads()["StructuredUnderstanding"])
    payload["exact_constraints"].append(
        {
            "kind": "candidate_ordinal",
            "ordinal": 2,
            "source_span": {"start": 14, "end": 17},
        }
    )

    with pytest.raises(ValidationError, match="exact references"):
        contract("StructuredUnderstanding").model_validate(payload)


@pytest.mark.parametrize(
    ("contract_name", "payload_name"),
    (
        ("StructuredUnderstanding", "StructuredUnderstanding"),
        ("TaskPlan", "TaskPlan"),
    ),
)
def test_public_ordinal_reference_rejects_string_or_untyped_bypass(
    contract_name: str,
    payload_name: str,
) -> None:
    payload = deepcopy(valid_payloads()[payload_name])
    payload["references"] = [
        {
            "kind": "candidate_ordinal",
            "ordinal": "2",
            "source_span": {"start": 14, "end": 17},
        }
    ]

    with pytest.raises(ValidationError):
        contract(contract_name).model_validate(payload)


@pytest.mark.parametrize(
    "forbidden_field",
    ["candidate_ids", "product_facts", "score", "winner", "sql"],
)
def test_structured_understanding_rejects_privileged_fields(
    forbidden_field: str,
) -> None:
    model = contract("StructuredUnderstanding")
    payload = valid_payloads()["StructuredUnderstanding"]
    payload[forbidden_field] = "not allowed"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate(payload)


def test_winner_status_has_exactly_the_frozen_values() -> None:
    winner_status = contract("WinnerStatus")

    assert {status.value for status in winner_status} == {
        "SELECTED",
        "TIED_BY_BUSINESS_EVIDENCE",
        "INSUFFICIENT_FOR_WINNER",
        "NO_CANDIDATE",
    }


@pytest.mark.parametrize(
    ("winner_status", "winner_product_id"),
    [
        ("SELECTED", None),
        ("TIED_BY_BUSINESS_EVIDENCE", 26),
        ("INSUFFICIENT_FOR_WINNER", 26),
        ("NO_CANDIDATE", 26),
    ],
)
def test_decision_result_rejects_inconsistent_winner(
    winner_status: str,
    winner_product_id: int | None,
) -> None:
    model = contract("DecisionResult")
    payload = valid_payloads()["DecisionResult"]
    payload["winner_status"] = contract("WinnerStatus")(winner_status)
    payload["winner_product_id"] = winner_product_id

    with pytest.raises(ValidationError, match="winner_product_id"):
        model.model_validate(payload)


@pytest.mark.parametrize("image_count", [0, 5])
def test_image_bundle_rejects_image_count_outside_one_to_four(
    image_count: int,
) -> None:
    model = contract("ImageBundle")
    created_at = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    payload = {
        "bundle_id": "bundle_" + "a" * 32,
        "session_id": "session-1",
        "owner_token_sha256": "b" * 64,
        "version": 1,
        "created_at": created_at,
        "expires_at": created_at + timedelta(minutes=5),
        "images": [
            image_payload(f"image_{index:032d}", index)
            for index in range(1, image_count + 1)
        ],
    }

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_image_bundle_rejects_duplicate_image_ids() -> None:
    model = contract("ImageBundle")
    payload = valid_payloads()["ImageBundle"]
    payload["images"][1]["image_id"] = "image_" + "c" * 32

    with pytest.raises(ValidationError, match="image_id"):
        model.model_validate(payload)


def test_image_bundle_rejects_duplicate_ordinals() -> None:
    model = contract("ImageBundle")
    payload = valid_payloads()["ImageBundle"]
    payload["images"][1]["ordinal"] = 1

    with pytest.raises(ValidationError, match="ordinal"):
        model.model_validate(payload)


@pytest.mark.parametrize("ordinals", [[2, 3], [1, 3], [2, 1]])
def test_image_bundle_rejects_non_contiguous_or_reordered_ordinals(
    ordinals: list[int],
) -> None:
    model = contract("ImageBundle")
    payload = valid_payloads()["ImageBundle"]
    for image, ordinal in zip(payload["images"], ordinals, strict=True):
        image["ordinal"] = ordinal

    with pytest.raises(ValidationError, match="ordinal"):
        model.model_validate(payload)


def test_image_observation_rejects_inference_fields_before_models_are_enabled(
) -> None:
    payload = valid_payloads()["ImageObservation"]

    for field in (
        "ocr_evidence",
        "visual_candidates",
        "identity_status",
        "confidence",
        "candidate_ids",
        "winner",
    ):
        with pytest.raises(
            ValidationError,
            match="Extra inputs are not permitted",
        ):
            contract("ImageObservation").model_validate(
                {**payload, field: "untrusted"}
            )


def test_image_bundle_requires_absolute_expiry_after_creation() -> None:
    payload = valid_payloads()["ImageBundle"]
    payload["expires_at"] = payload["created_at"]

    with pytest.raises(ValidationError, match="expires_at"):
        contract("ImageBundle").model_validate(payload)


@pytest.mark.parametrize(
    "missing_field",
    ["owner_token_sha256", "version", "created_at", "expires_at"],
)
def test_image_bundle_requires_state_contract_fields(
    missing_field: str,
) -> None:
    payload = valid_payloads()["ImageBundle"]
    del payload[missing_field]

    with pytest.raises(ValidationError):
        contract("ImageBundle").model_validate(payload)


@pytest.mark.parametrize(
    "contract_name",
    ["UserTurn", "ImageBundle", "ConversationSnapshot"],
)
def test_session_contracts_reject_101_characters(
    contract_name: str,
) -> None:
    payload = valid_payloads()[contract_name]
    payload["session_id"] = "s" * 101

    with pytest.raises(ValidationError, match="at most 100"):
        contract(contract_name).model_validate(payload)


def test_image_upload_unavailable_has_a_typed_public_error_code() -> None:
    application = importlib.import_module("app.guide.application")

    assert (
        application.ImageErrorCode.IMAGE_UPLOAD_UNAVAILABLE.value
        == "image_upload_unavailable"
    )


def test_application_session_id_type_has_exact_100_character_boundary(
) -> None:
    application = importlib.import_module("app.guide.application")
    adapter = TypeAdapter(application.SessionId)

    assert adapter.validate_python("s" * 100) == "s" * 100
    with pytest.raises(ValidationError, match="at most 100"):
        adapter.validate_python("s" * 101)


def test_retired_consultation_state_authority_is_not_public() -> None:
    retired_names = {
        "ConsultationSnapshot",
        "ConsultationStateConflict",
        "ConsultationStatePort",
        "InMemoryConsultationState",
    }
    public_modules = (
        importlib.import_module("app.guide.feedback"),
        importlib.import_module(
            "app.guide.feedback.consultation_state"
        ),
        importlib.import_module("app.guide.adapters.state"),
    )

    for module in public_modules:
        assert retired_names.isdisjoint(vars(module))
        assert retired_names.isdisjoint(getattr(module, "__all__", ()))
    assert (
        importlib.util.find_spec(
            "app.guide.adapters.state.in_memory_consultation_state"
        )
        is None
    )
