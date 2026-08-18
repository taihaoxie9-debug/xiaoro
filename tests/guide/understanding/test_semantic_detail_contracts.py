from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.guide.understanding.semantic_contracts import (
    ConcernCode,
    ObservationCode,
    ObservationQualifier,
    SemanticObservation,
    SemanticProductMention,
    SemanticReference,
)
from app.guide.understanding.semantic_detail_contracts import (
    AssessmentDetails,
    ComparisonDetails,
    FollowupDetails,
    ImageDetails,
    KnowledgeDetails,
    RecommendationDetails,
)


def _observation() -> SemanticObservation:
    return SemanticObservation(
        code=ObservationCode.TIGHTNESS,
        present=True,
        qualifier=ObservationQualifier.POST_CLEANSE,
    )


def _reference() -> SemanticReference:
    return SemanticReference(
        kind="current_item",
        ordinal=None,
        raw_text="这款",
        start=0,
        end=2,
    )


def _product_mention() -> SemanticProductMention:
    return SemanticProductMention(
        text="理肤泉防晒",
        start=0,
        end=6,
    )


@pytest.mark.parametrize(
    ("model_type", "payload", "forbidden_field", "forbidden_value"),
    [
        (
            RecommendationDetails,
            {"concerns": (), "observations": ()},
            "references",
            (),
        ),
        (
            AssessmentDetails,
            {"concerns": (), "observations": ()},
            "acts",
            (),
        ),
        (
            ComparisonDetails,
            {"references": (_reference(),)},
            "observations",
            (),
        ),
        (
            FollowupDetails,
            {"references": (_reference(),)},
            "concerns",
            (),
        ),
        (
            KnowledgeDetails,
            {"concerns": ()},
            "references",
            (),
        ),
        (
            ImageDetails,
            {"references": (_reference(),), "observations": ()},
            "acts",
            (),
        ),
    ],
)
def test_detail_contracts_isolate_stage_fields(
    model_type: type,
    payload: dict[str, object],
    forbidden_field: str,
    forbidden_value: object,
) -> None:
    proposal = model_type.model_validate(payload, strict=True)
    assert proposal is not None

    with pytest.raises(ValidationError):
        model_type.model_validate(
            {**payload, forbidden_field: forbidden_value},
            strict=True,
        )


def test_detail_contracts_accept_their_stage_specific_values() -> None:
    recommendation = RecommendationDetails(
        concerns=(ConcernCode.TEXTURE,),
        observations=(_observation(),),
    )
    assessment = AssessmentDetails(
        concerns=(ConcernCode.SKIN,),
        observations=(_observation(),),
    )
    comparison = ComparisonDetails(references=(_reference(),))
    followup = FollowupDetails(
        references=(_reference(),),
    )
    knowledge = KnowledgeDetails(concerns=(ConcernCode.EFFICACY,))
    image = ImageDetails(
        references=(
            SemanticReference(
                kind="image_ordinal",
                ordinal=1,
                raw_text="第一张",
                start=0,
                end=3,
            ),
        ),
        observations=(),
    )

    assert recommendation.concerns == (ConcernCode.TEXTURE,)
    assert assessment.observations == (_observation(),)
    assert comparison.references == (_reference(),)
    assert followup.references == (_reference(),)
    assert knowledge.concerns == (ConcernCode.EFFICACY,)
    assert image.references[0].kind == "image_ordinal"


def test_recommendation_details_drop_misplaced_observation_concern(
) -> None:
    details = RecommendationDetails.model_validate_json(
        json.dumps(
            {
                "concerns": [
                    "sun_protection",
                    "sensitivity",
                    "oiliness",
                ],
                "observations": [],
                "product_mentions": [],
                "number_candidates": [],
            }
        ),
        strict=True,
    )

    assert [concern.value for concern in details.concerns] == [
        "sun_protection",
        "sensitivity",
    ]


def test_recommendation_details_accept_source_bound_preference_candidate(
) -> None:
    details = RecommendationDetails.model_validate_json(
        json.dumps(
            {
                "concerns": ["finish"],
                "observations": [],
                "product_mentions": [],
                "number_candidates": [],
                "preference_candidates": [
                    {
                        "field": "finish",
                        "raw_text": "哑光",
                        "start": 2,
                        "end": 4,
                        "strength": "preference",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        strict=True,
    )

    assert details.preference_candidates[0].raw_text == "哑光"
    assert details.preference_candidates[0].field.value == "finish"


def test_followup_detail_accepts_product_mention_without_session_reference(
) -> None:
    details = FollowupDetails(
        references=(),
        product_mentions=(_product_mention(),),
    )

    assert details.references == ()
    assert details.product_mentions == (_product_mention(),)


def test_reference_stage_shape_does_not_decide_executability() -> None:
    comparison = ComparisonDetails(
        references=(),
        product_mentions=(),
    )
    followup = FollowupDetails(
        references=(),
        product_mentions=(),
    )

    assert comparison.references == ()
    assert comparison.product_mentions == ()
    assert followup.references == ()
    assert followup.product_mentions == ()


def test_product_question_details_keep_unrestricted_meaning_and_safety() -> None:
    knowledge = KnowledgeDetails(
        concerns=(),
        product_mentions=(_product_mention(),),
        question_meaning="询问面膜是否容易滑落",
        safety_sensitive=False,
    )
    followup = FollowupDetails(
        references=(_reference(),),
        question_meaning="追问刚才测试的样本和可靠性",
        safety_sensitive=True,
    )

    assert knowledge.question_meaning == "询问面膜是否容易滑落"
    assert not knowledge.safety_sensitive
    assert followup.question_meaning == "追问刚才测试的样本和可靠性"
    assert followup.safety_sensitive

    with pytest.raises(ValidationError):
        KnowledgeDetails(
            concerns=(),
            question_meaning="",
            safety_sensitive=False,
        )


@pytest.mark.parametrize(
    ("model_type", "field", "value"),
    [
        (
            RecommendationDetails,
            "concerns",
            (ConcernCode.SKIN, ConcernCode.SKIN),
        ),
        (
            AssessmentDetails,
            "observations",
            (_observation(), _observation()),
        ),
        (
            ComparisonDetails,
            "references",
            (_reference(), _reference()),
        ),
    ],
)
def test_detail_contracts_reject_duplicate_values(
    model_type: type,
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {
        "concerns": (),
        "observations": (),
        "references": (_reference(),),
    }
    accepted = set(model_type.model_fields)
    filtered = {
        key: item
        for key, item in payload.items()
        if key in accepted
    }
    filtered[field] = value

    with pytest.raises(ValidationError, match="unique"):
        model_type.model_validate(filtered, strict=True)


@pytest.mark.parametrize(
    "model_type",
    (ComparisonDetails, FollowupDetails, ImageDetails),
)
def test_reference_detail_contracts_require_a_reference(
    model_type: type,
) -> None:
    payload = {
        name: ()
        for name in model_type.model_fields
    }
    with pytest.raises(ValidationError):
        model_type.model_validate(payload, strict=True)
