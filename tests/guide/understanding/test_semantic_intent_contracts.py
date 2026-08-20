from __future__ import annotations

import ast
import inspect
import json
import subprocess
import sys
from pathlib import Path
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from app.guide.understanding import semantic_contracts
from app.guide.understanding.contracts import (
    ReferenceDraft,
    SignalTrace,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.ports import (
    SemanticIntentPort,
    TextUnderstandingPort,
)
from app.guide.understanding.semantic_contracts import (
    ActiveConstraintKind,
    ClarificationCode,
    ConcernCode,
    ConfirmedProfileField,
    ObservationCode,
    ObservationQualifier,
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
    SemanticObservation,
    SemanticPreferenceCandidate,
    SemanticPreferenceField,
    SemanticPreferenceStrength,
    SemanticReference,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def valid_proposal_payload() -> dict[str, object]:
    return {
        "goal": UnderstandingGoal.RECOMMENDATION,
        "topic": TopicCode.FRAGRANCE,
        "concerns": (ConcernCode.TEXTURE,),
        "observations": (),
        "references": (),
        "confidence": 0.96,
        "clarification_hint": None,
    }


def raw_json_proposal_payload() -> dict[str, object]:
    return {
        "goal": "recommendation",
        "topic": "fragrance",
        "concerns": [],
        "observations": [],
        "references": [],
        "confidence": 0.96,
        "clarification_hint": None,
    }


def test_semantic_codes_are_closed_to_supported_guide_dimensions() -> None:
    assert {item.value for item in ConcernCode} == {
        "skin",
        "sensitivity",
        "efficacy",
        "texture",
        "sun_protection",
        "water_resistance",
        "shade",
        "finish",
        "coverage",
        "longevity",
        "cleansing",
        "fragrance",
        "sillage",
        "price",
        "budget",
    }
    assert {item.value for item in ObservationCode} == {
        "tightness",
        "oiliness",
        "redness",
        "stinging",
        "flaking",
        "current_budget_unknown",
        "goal_unclear",
        "topic_unclear",
        "reference_unclear",
    }
    assert {item.value for item in ObservationQualifier} == {
        "post_cleanse",
        "t_zone",
        "recurrent",
        "basic_skincare",
        "minimum",
        "maximum",
        "range",
        "candidate",
        "image",
        "current_topic",
    }
    assert {item.value for item in ClarificationCode} == {
        "goal",
        "topic",
        "reference",
        "budget",
        "concern",
    }
    assert {item.value for item in ConfirmedProfileField} == {
        "skin_type",
        "skin_concern",
        "ingredient_exclusion",
        "preferred_brand",
        "preferred_category",
    }


def test_semantic_goal_is_the_shared_closed_enum() -> None:
    assert SemanticGoal is UnderstandingGoal
    assert {goal.value for goal in SemanticGoal} == {
        "recommendation",
        "comparison",
        "suitability",
        "image_identity",
        "image_similarity",
        "knowledge",
        "assessment",
        "followup",
        "clarification",
    }

    payload = valid_proposal_payload()
    payload["goal"] = "unsupported_goal"
    with pytest.raises(ValidationError) as exc_info:
        SemanticIntentProposal.model_validate(payload, strict=True)
    assert any(error["loc"] == ("goal",) for error in exc_info.value.errors())


def test_semantic_contract_has_no_model_owned_constraint_mutations() -> None:
    fields = SemanticIntentProposal.model_fields

    assert "acts" not in fields
    assert not hasattr(semantic_contracts, "SemanticAct")
    assert not hasattr(semantic_contracts, "SemanticActKind")
    assert not hasattr(semantic_contracts, "SemanticActTarget")


def test_semantic_models_are_strict_frozen_and_extra_forbid() -> None:
    for model in (
        SemanticReference,
        SemanticContext,
        SemanticIntentProposal,
        SemanticObservation,
    ):
        assert model.model_config["strict"] is True
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"


def test_semantic_proposal_accepts_typed_bounded_values() -> None:
    proposal = SemanticIntentProposal(
        goal=SemanticGoal.RECOMMENDATION,
        topic=TopicCode.FRAGRANCE,
        concerns=(ConcernCode.TEXTURE,),
        observations=(
            SemanticObservation(
                code=ObservationCode.OILINESS,
                present=True,
                qualifier=ObservationQualifier.T_ZONE,
            ),
        ),
        references=(
            SemanticReference(
                kind="candidate_ordinal",
                ordinal=2,
                raw_text="第二款",
                start=0,
                end=3,
            ),
        ),
        confidence=0.96,
        clarification_hint=None,
    )

    assert proposal.schema_version == "guide-semantic-intent-v7"
    assert proposal.references[0].ordinal == 2
    assert proposal.observations[0].present is True


def test_legacy_model_owned_acts_are_rejected() -> None:
    payload = raw_json_proposal_payload()
    payload["acts"] = []

    with pytest.raises(ValidationError):
        SemanticIntentProposal.model_validate_json(
            json.dumps(payload, ensure_ascii=False),
            strict=True,
        )


def test_misplaced_observation_concern_is_dropped_without_losing_known(
) -> None:
    payload = raw_json_proposal_payload()
    payload["concerns"] = [
        "sun_protection",
        "sensitivity",
        "oiliness",
    ]

    proposal = SemanticIntentProposal.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )

    assert [concern.value for concern in proposal.concerns] == [
        "sun_protection",
        "sensitivity",
    ]


def test_semantic_proposal_accepts_typed_budget_and_price_meaning() -> None:
    payload = raw_json_proposal_payload()
    payload["concerns"] = ["budget", "price"]
    payload["observations"] = [
        {
            "code": "current_budget_unknown",
            "present": True,
            "qualifier": "maximum",
        }
    ]
    payload["clarification_hint"] = "budget"

    proposal = SemanticIntentProposal.model_validate_json(
        json.dumps(payload),
        strict=True,
    )

    assert tuple(item.value for item in proposal.concerns) == (
        "budget",
        "price",
    )
    assert proposal.observations[0].code.value == "current_budget_unknown"
    assert proposal.observations[0].qualifier.value == "maximum"


@pytest.mark.parametrize(
    "forbidden",
    (
        "product_id",
        "product_ids",
        "candidate_id",
        "candidate_ids",
        "product_facts",
        "score",
        "winner",
        "sql",
        "profile_updates",
    ),
)
def test_semantic_proposal_rejects_privileged_fields(
    forbidden: str,
) -> None:
    payload = valid_proposal_payload()
    payload[forbidden] = []

    with pytest.raises(ValidationError) as exc_info:
        SemanticIntentProposal.model_validate(payload, strict=True)

    assert any(
        error["loc"] == (forbidden,)
        and error["type"] == "extra_forbidden"
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    "field",
    ("concerns", "observations"),
)
@pytest.mark.parametrize(
    "unrepresentable_text",
    (
        "product identifier=42",
        "candidate identifier=slot-2",
        "SELECT 1",
        "TRUNCATE products",
        "用户希望了解价格范围",
        "The budget maximum is still unclear",
    ),
)
def test_semantic_proposal_rejects_all_free_text_meaning(
    field: str,
    unrepresentable_text: str,
) -> None:
    payload = raw_json_proposal_payload()
    payload[field] = [unrepresentable_text]

    with pytest.raises(ValidationError):
        SemanticIntentProposal.model_validate_json(
            json.dumps(payload),
            strict=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("clarification_hint", "请确认更关注保湿还是清爽"),
        (
            "observations",
            [
                {
                    "code": "oiliness",
                    "present": True,
                    "qualifier": "product identifier=42",
                }
            ],
        ),
        (
            "observations",
            [
                {
                    "code": "product_identifier",
                    "present": True,
                    "qualifier": None,
                }
            ],
        ),
    ),
)
def test_semantic_proposal_rejects_text_outside_closed_codes(
    field: str,
    value: object,
) -> None:
    payload = raw_json_proposal_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        SemanticIntentProposal.model_validate_json(
            json.dumps(payload),
            strict=True,
        )


def test_semantic_observation_rejects_type_coercion_and_extra_facts() -> None:
    valid = {
        "code": ObservationCode.FLAKING,
        "present": True,
        "qualifier": None,
    }
    with pytest.raises(ValidationError):
        SemanticObservation.model_validate(
            {**valid, "present": "true"},
            strict=True,
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        SemanticObservation.model_validate(
            {**valid, "fact": "product identifier=42"},
            strict=True,
        )


def test_semantic_context_is_minimal_and_rejects_product_facts() -> None:
    context = SemanticContext(
        conversation_version=2,
        active_topic=TopicCode.SUNSCREEN,
        visible_candidate_count=3,
        focused_candidate_ordinal=2,
        image_count=2,
        focused_image_ordinal=1,
        active_constraint_kinds=(
            ActiveConstraintKind.BUDGET,
            ActiveConstraintKind.CATEGORY,
        ),
        confirmed_profile_fields=(ConfirmedProfileField.SKIN_TYPE,),
    )
    assert "product" not in context.model_dump_json().casefold()
    assert context.pending_clarification is None

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SemanticContext.model_validate(
            {
                **context.model_dump(),
                "product_facts": {"42": {"price": 100}},
            },
            strict=True,
        )


def test_semantic_context_v3_focus_and_constraint_kinds_are_closed() -> None:
    context = SemanticContext(
        conversation_version=2,
        active_topic=TopicCode.SUNSCREEN,
        visible_candidate_count=3,
        focused_candidate_ordinal=2,
        image_count=4,
        focused_image_ordinal=3,
        active_constraint_kinds=tuple(ActiveConstraintKind),
        confirmed_profile_fields=(),
    )

    assert {item.value for item in ActiveConstraintKind} == {
        "budget",
        "category",
        "skin",
        "ingredient_exclusion",
        "efficacy",
    }
    assert SemanticContext.model_validate_json(
        context.model_dump_json()
    ) == context


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("focused_candidate_ordinal", 4),
        ("focused_candidate_ordinal", True),
        ("focused_image_ordinal", 3),
        ("focused_image_ordinal", "1"),
    ),
)
def test_semantic_context_v3_rejects_invalid_focus(
    field: str,
    value: object,
) -> None:
    payload = {
        "conversation_version": 2,
        "active_topic": "sunscreen",
        "visible_candidate_count": 3,
        "focused_candidate_ordinal": None,
        "image_count": 2,
        "focused_image_ordinal": None,
        "active_constraint_kinds": [],
        "confirmed_profile_fields": [],
        "pending_clarification": None,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        SemanticContext.model_validate_json(json.dumps(payload))


def test_semantic_context_v3_rejects_duplicate_constraint_kinds() -> None:
    with pytest.raises(ValidationError, match="unique"):
        SemanticContext(
            conversation_version=2,
            active_topic=TopicCode.SUNSCREEN,
            visible_candidate_count=0,
            active_constraint_kinds=(
                ActiveConstraintKind.BUDGET,
                ActiveConstraintKind.BUDGET,
            ),
            confirmed_profile_fields=(),
        )


def test_semantic_context_accepts_only_closed_profile_fields() -> None:
    context = SemanticContext(
        conversation_version=2,
        active_topic=TopicCode.SUNSCREEN,
        visible_candidate_count=3,
        confirmed_profile_fields=tuple(
            ConfirmedProfileField[member]
            for member in (
                "SKIN_TYPE",
                "SKIN_CONCERN",
                "INGREDIENT_EXCLUSION",
                "PREFERRED_BRAND",
                "PREFERRED_CATEGORY",
            )
        ),
    )

    assert {item.value for item in context.confirmed_profile_fields} == {
        "skin_type",
        "skin_concern",
        "ingredient_exclusion",
        "preferred_brand",
        "preferred_category",
    }

    with pytest.raises(ValidationError):
        SemanticContext.model_validate_json(
            json.dumps(
                {
                    "conversation_version": 2,
                    "active_topic": "sunscreen",
                    "visible_candidate_count": 3,
                    "confirmed_profile_fields": ["product_facts"],
                }
            ),
            strict=True,
        )


def test_semantic_context_profile_fields_cannot_carry_values() -> None:
    with pytest.raises(ValidationError):
        SemanticContext.model_validate_json(
            json.dumps(
                {
                    "conversation_version": 2,
                    "active_topic": "sunscreen",
                    "visible_candidate_count": 3,
                    "confirmed_profile_fields": {
                        "skin_concern": "product identifier=42",
                    },
                }
            ),
            strict=True,
        )


def test_semantic_contracts_contain_no_free_text_denylist() -> None:
    source_path = Path(inspect.getsourcefile(semantic_contracts) or "")
    tree = ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
    )
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "re" not in imported_modules
    assert "_FORBIDDEN_SEMANTIC_PATTERNS" not in vars(semantic_contracts)
    assert "_has_forbidden_semantics" not in vars(semantic_contracts)


def test_semantic_context_rejects_duplicate_profile_fields() -> None:
    with pytest.raises(ValidationError, match="unique"):
        SemanticContext(
            conversation_version=2,
            active_topic=TopicCode.SUNSCREEN,
            visible_candidate_count=3,
            confirmed_profile_fields=(
                ConfirmedProfileField.SKIN_TYPE,
                ConfirmedProfileField.SKIN_TYPE,
            ),
        )


@pytest.mark.parametrize(
    ("kind", "ordinal"),
    (
        ("candidate_ordinal", None),
        ("image_ordinal", None),
        ("current_item", 2),
        ("current_batch", 2),
        ("current_topic", 2),
        ("previous_constraint", 2),
    ),
)
def test_semantic_reference_rejects_inconsistent_kind_and_ordinal(
    kind: str,
    ordinal: int | None,
) -> None:
    with pytest.raises(ValidationError):
        SemanticReference.model_validate(
            {
                "kind": kind,
                "ordinal": ordinal,
                "raw_text": "这个",
                "start": 0,
                "end": 2,
            },
            strict=True,
        )


def test_semantic_reference_requires_current_message_source_binding() -> None:
    with pytest.raises(ValidationError):
        SemanticReference.model_validate(
            {
                "kind": "image_ordinal",
                "ordinal": 1,
            },
            strict=True,
        )

    reference = SemanticReference(
        kind="image_ordinal",
        ordinal=1,
        raw_text="第一张",
        start=0,
        end=3,
    )

    assert reference.raw_text == "第一张"
    assert (reference.start, reference.end) == (0, 3)


def test_semantic_reference_accepts_consistent_kind_and_ordinal() -> None:
    assert SemanticReference(
        kind="image_ordinal",
        ordinal=4,
        raw_text="第四张",
        start=0,
        end=3,
    ).ordinal == 4
    for kind in (
        "current_item",
        "current_batch",
        "current_topic",
        "previous_constraint",
    ):
        assert SemanticReference(
            kind=kind,
            raw_text="这个",
            start=0,
            end=2,
        ).ordinal is None
        assert ReferenceDraft(kind=kind).ordinal is None


def test_reference_contract_covers_all_authoritative_kinds() -> None:
    kinds = {
        "current_item",
        "current_batch",
        "candidate_ordinal",
        "image_ordinal",
        "current_topic",
        "previous_constraint",
    }

    assert {
        SemanticReference(
            kind=kind,
            ordinal=1,
            raw_text="第一项",
            start=0,
            end=3,
        ).kind
        for kind in ("candidate_ordinal", "image_ordinal")
    } == {"candidate_ordinal", "image_ordinal"}
    assert {
        SemanticReference(
            kind=kind,
            raw_text="这个",
            start=0,
            end=2,
        ).kind
        for kind in kinds - {"candidate_ordinal", "image_ordinal"}
    } == kinds - {"candidate_ordinal", "image_ordinal"}


def test_structured_understanding_keeps_redacted_public_contract() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.FRAGRANCE,
        observations=[],
        exact_constraints=[],
        semantic_proposals=["concern=texture"],
        signal_trace=[
            SignalTrace(
                field="goal",
                exact_value=None,
                semantic_value="recommendation",
                resolution="semantic_fills",
            )
        ],
        image_references=[],
        uncertainties=[],
        confidence=0.8,
    )

    assert understanding.goal is UnderstandingGoal.RECOMMENDATION
    assert understanding.semantic_proposals == ["concern=texture"]
    assert understanding.signal_trace[0].resolution == "semantic_fills"


def test_understanding_ports_expose_typed_compatible_signatures() -> None:
    assert SemanticIntentPort._is_protocol
    assert TextUnderstandingPort._is_protocol
    assert get_type_hints(SemanticIntentPort.propose) == {
        "message": str,
        "context": SemanticContext,
        "return": SemanticIntentProposal,
    }
    assert get_type_hints(TextUnderstandingPort.understand) == {
        "message": str,
        "context": SemanticContext,
        "semantic_required": bool,
        "return": StructuredUnderstanding,
    }

    signature = inspect.signature(TextUnderstandingPort.understand)
    assert signature.parameters["context"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["semantic_required"].default is True


def test_contract_import_direction_is_acyclic() -> None:
    contracts_path = (
        REPO_ROOT / "app/guide/understanding/contracts.py"
    )
    tree = ast.parse(
        contracts_path.read_text(encoding="utf-8"),
        filename=str(contracts_path),
    )
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert (
        "app.guide.understanding.semantic_contracts"
        not in imported_modules
    )

    modules = (
        "app.guide.understanding.contracts",
        "app.guide.understanding.semantic_contracts",
    )
    for first, second in (modules, tuple(reversed(modules))):
        completed = subprocess.run(
            [sys.executable, "-c", f"import {first}; import {second}"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == ""
        assert completed.stderr == ""


def test_semantic_product_mention_contains_only_text_and_source_span() -> None:
    payload = valid_proposal_payload()
    payload["product_mentions"] = (
        {
            "text": "理肤泉特护清盈防晒乳",
            "start": 2,
            "end": 12,
        },
    )

    proposal = SemanticIntentProposal.model_validate(
        payload,
        strict=True,
    )

    assert [
        mention.model_dump()
        for mention in proposal.product_mentions
    ] == [
        {
            "text": "理肤泉特护清盈防晒乳",
            "start": 2,
            "end": 12,
        }
    ]

    invalid = valid_proposal_payload()
    invalid["product_mentions"] = (
        {
            "text": "理肤泉特护清盈防晒乳",
            "start": 2,
            "end": 12,
            "product_id": 53,
        },
    )
    with pytest.raises(ValidationError):
        SemanticIntentProposal.model_validate(invalid, strict=True)


def test_semantic_number_candidate_is_nomination_not_budget_authority() -> None:
    payload = valid_proposal_payload()
    payload["number_candidates"] = (
        {
            "kind": "budget",
            "relation": "maximum",
            "raw_text": "三百以内",
            "start": 2,
            "end": 6,
            "minimum": None,
            "maximum": "300",
        },
    )

    proposal = SemanticIntentProposal.model_validate(
        payload,
        strict=True,
    )

    assert proposal.number_candidates[0].model_dump() == {
        "kind": "budget",
        "relation": "maximum",
        "raw_text": "三百以内",
        "start": 2,
        "end": 6,
        "minimum": None,
        "maximum": "300",
    }

    invalid = valid_proposal_payload()
    invalid["number_candidates"] = (
        {
            "kind": "budget",
            "relation": "maximum",
            "raw_text": "三百以内",
            "start": 2,
            "end": 6,
            "minimum": None,
            "maximum": "300",
            "product_id": 53,
        },
    )
    with pytest.raises(ValidationError):
        SemanticIntentProposal.model_validate(invalid, strict=True)


def test_approximate_number_candidate_allows_partial_nomination() -> None:
    payload = valid_proposal_payload()
    payload["number_candidates"] = (
        {
            "kind": "budget",
            "relation": "approximate",
            "raw_text": "百来块",
            "start": 0,
            "end": 3,
            "minimum": None,
            "maximum": "199",
        },
    )

    proposal = SemanticIntentProposal.model_validate(
        payload,
        strict=True,
    )

    assert proposal.number_candidates[0].relation == "approximate"
    assert proposal.number_candidates[0].maximum == "199"


def test_ambiguous_number_candidate_allows_span_only_nomination() -> None:
    payload = valid_proposal_payload()
    payload["number_candidates"] = (
        {
            "kind": "budget",
            "relation": "range",
            "raw_text": "几百块上下",
            "start": 0,
            "end": 5,
            "minimum": None,
            "maximum": None,
        },
    )

    proposal = SemanticIntentProposal.model_validate(
        payload,
        strict=True,
    )

    assert proposal.number_candidates[0].raw_text == "几百块上下"
    assert proposal.number_candidates[0].minimum is None
    assert proposal.number_candidates[0].maximum is None


def test_semantic_preference_candidate_is_source_bound_and_typed() -> None:
    candidate = SemanticPreferenceCandidate.model_validate_json(
        json.dumps(
            {
                "field": "finish",
                "raw_text": "哑光",
                "start": 2,
                "end": 4,
                "strength": "preference",
            },
            ensure_ascii=False,
        ),
        strict=True,
    )

    assert candidate.field is SemanticPreferenceField.FINISH
    assert candidate.strength is SemanticPreferenceStrength.PREFERENCE
    assert candidate.raw_text == "哑光"


def test_unknown_soft_preference_candidate_is_dropped_but_safety_is_strict(
) -> None:
    payload = raw_json_proposal_payload()
    payload["preference_candidates"] = [
        {
            "field": "cold_unknown_field",
            "raw_text": "冷门偏好",
            "start": 0,
            "end": 4,
            "strength": "preference",
        },
        {
            "field": "finish",
            "raw_text": "哑光",
            "start": 5,
            "end": 7,
            "strength": "preference",
        },
    ]

    proposal = SemanticIntentProposal.model_validate_json(
        json.dumps(payload, ensure_ascii=False),
        strict=True,
    )

    assert [
        candidate.field.value
        for candidate in proposal.preference_candidates
    ] == ["finish"]

    payload["preference_candidates"] = [
        {
            "field": "cold_unknown_field",
            "raw_text": "绝对不能",
            "start": 0,
            "end": 4,
            "strength": "safety",
        },
    ]
    with pytest.raises(ValidationError):
        SemanticIntentProposal.model_validate_json(
            json.dumps(payload, ensure_ascii=False),
            strict=True,
        )
