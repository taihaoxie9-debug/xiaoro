from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.application.consultation_confirmation import (
    ConsultationConfirmationRejected,
    SkinTargetValue,
    validate_explicit_confirmation,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationTrigger,
)
from app.guide.understanding.consultation_questions import (
    ConsultationQuestion,
)
from app.guide.understanding.source_grounding import (
    SourceGroundingError,
    ground_unique_text,
)
from app.guide.understanding.safety_admission import (
    SafetyObservation,
    classify_safety_observations,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnConsultationCondition,
    TurnConsultationHypothesis,
    TurnConsultationTendency,
    TurnMeaning,
    TurnNextObservationGap,
    TurnObservationCandidate,
    TurnPendingResponseHint,
)


_DYNAMIC_DIMENSIONS = frozenset(
    {
        "oiliness",
        "dryness",
        "tightness",
        "flaking",
        "redness",
        "stinging",
        "burning",
        "pain",
        "swelling",
        "broken_skin",
        "oozing",
        "product_tolerance",
    }
)
_BASE_DIMENSIONS = frozenset(
    {"oiliness", "dryness", "tightness", "flaking"}
)
_DRY_DIMENSIONS = frozenset(
    {"dryness", "tightness", "flaking"}
)
_REACTION_DIMENSIONS = frozenset(
    {"redness", "stinging", "burning", "pain"}
)
_ACTIVE_RISK_DIMENSIONS = frozenset(
    {"burning", "pain", "swelling", "broken_skin", "oozing"}
)
_SKIN_LABELS = {
    "oily": "油性肤质",
    "dry": "干性肤质",
    "combination": "混合性肤质",
    "normal": "中性肤质",
}


class DynamicConsultationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    conversation_version: int = Field(ge=1)
    observations: tuple[ConsultationObservation, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    conclusion: ProvisionalConsultationConclusion | None = None
    stable_tendencies: tuple[TurnConsultationTendency, ...] = Field(
        default_factory=tuple,
        max_length=5,
    )
    current_conditions: tuple[TurnConsultationCondition, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    next_gap: TurnNextObservationGap | None = None
    next_question: ConsultationQuestion | None = None
    ready_for_confirmation: bool
    escalation_triggers: tuple[
        ConsultationEscalationTrigger,
        ...,
    ] = Field(default_factory=tuple, max_length=3)
    stop_skincare_advice: bool
    next_consultation: ConsultationSubstate

    @field_validator(
        "observations",
        "stable_tendencies",
        "current_conditions",
        "escalation_triggers",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.next_consultation.observations != self.observations:
            raise ValueError(
                "dynamic result must bind its exact observations"
            )
        if self.stop_skincare_advice != bool(
            self.escalation_triggers
        ):
            raise ValueError(
                "stop_skincare_advice must match escalation triggers"
            )
        if self.stop_skincare_advice and (
            self.next_gap is not None
            or self.next_question is not None
            or self.ready_for_confirmation
        ):
            raise ValueError(
                "safety escalation cannot ask a consultation question"
            )
        if self.ready_for_confirmation:
            if (
                self.conclusion is None
                or self.conclusion.skin_target is None
                or self.next_gap != "confirmation"
                or self.next_question is None
                or self.next_question.code != "confirmation"
            ):
                raise ValueError(
                    "confirmation readiness requires a supported conclusion"
                )
        elif self.next_gap == "confirmation":
            raise ValueError(
                "confirmation gap requires confirmation readiness"
            )
        if (self.next_gap is None) != (self.next_question is None):
            raise ValueError(
                "next gap and next question must be emitted together"
            )
        return self


class PreparedConsultationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    observations: tuple[ConsultationObservation, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    hypothesis: TurnConsultationHypothesis | None = None
    next_observation_gap: TurnNextObservationGap | None = None
    pending_response_hint: TurnPendingResponseHint = "unknown"
    confirmation_status: Literal[
        "not_applicable",
        "affirmed",
        "rejected",
        "unresolved",
    ] = "not_applicable"

    @field_validator("observations", mode="before")
    @classmethod
    def freeze_observations(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


def prepare_dynamic_consultation_evidence(
    *,
    message: str,
    meaning: TurnMeaning,
    source_turn_id: str,
    expected_skin_target: SkinTargetValue | None = None,
) -> PreparedConsultationEvidence:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be nonempty")
    if type(meaning) is not TurnMeaning:
        raise TypeError("meaning must be an exact TurnMeaning")
    if not isinstance(source_turn_id, str) or not source_turn_id:
        raise ValueError("source_turn_id must be nonempty")
    confirmation_status: Literal[
        "not_applicable",
        "affirmed",
        "rejected",
        "unresolved",
    ] = "not_applicable"
    if meaning.pending_response_hint == "reject":
        confirmation_status = "rejected"
    elif meaning.pending_response_hint == "affirm":
        if expected_skin_target is None:
            confirmation_status = "unresolved"
        else:
            try:
                validate_explicit_confirmation(
                    message,
                    expected_skin_target=expected_skin_target,
                )
            except ConsultationConfirmationRejected:
                confirmation_status = "unresolved"
            else:
                confirmation_status = "affirmed"
    return PreparedConsultationEvidence(
        observations=_admit_observations(
            message=message,
            candidates=meaning.observation_candidates,
            source_turn_id=source_turn_id,
        ),
        hypothesis=meaning.consultation_hypothesis,
        next_observation_gap=meaning.next_observation_gap,
        pending_response_hint=meaning.pending_response_hint,
        confirmation_status=confirmation_status,
    )


def advance_dynamic_consultation(
    *,
    previous: ConsultationSubstate | None,
    evidence: PreparedConsultationEvidence,
    source_turn_id: str,
    conversation_version: int,
) -> DynamicConsultationResult:
    if previous is not None and type(previous) is not ConsultationSubstate:
        raise TypeError("previous must be a ConsultationSubstate or None")
    if type(evidence) is not PreparedConsultationEvidence:
        raise TypeError(
            "evidence must be PreparedConsultationEvidence"
        )
    if not isinstance(source_turn_id, str) or not source_turn_id:
        raise ValueError("source_turn_id must be nonempty")
    if (
        not isinstance(conversation_version, int)
        or isinstance(conversation_version, bool)
        or conversation_version < 1
    ):
        raise ValueError("conversation_version must be positive")
    if previous is not None and previous.medical_escalation is not None:
        raise ValueError("terminal consultation cannot advance")

    admitted = evidence.observations
    observations = _merge_observations(
        previous.observations if previous is not None else (),
        admitted,
    )
    admitted_ids = {
        item.observation_id
        for item in admitted
        if item.observation_id is not None
    }
    hypothesis = _admit_hypothesis(
        evidence.hypothesis,
        admitted_ids=admitted_ids,
    )
    base_skin = _accepted_base_skin(
        hypothesis,
        observations=observations,
        admitted_ids=admitted_ids,
    )
    if base_skin is None:
        base_skin = _infer_base_skin(observations)
    tendencies = _accepted_tendencies(
        hypothesis,
        observations=observations,
    )
    conditions = _accepted_conditions(
        hypothesis,
        observations=observations,
    )
    escalation_triggers = _safety_triggers(
        observations,
        source_turn_id=source_turn_id,
    )
    stop_skincare_advice = bool(escalation_triggers)
    next_gap = None
    next_question = None
    ready_for_confirmation = False
    if not stop_skincare_advice:
        next_gap = _select_next_gap(
            evidence.next_observation_gap,
            observations=observations,
            base_skin=base_skin,
        )
        if next_gap is not None:
            next_question = _question_for_gap(
                next_gap,
                base_skin=base_skin,
            )
            ready_for_confirmation = next_gap == "confirmation"

    conclusion = _build_conclusion(
        observations=observations,
        base_skin=base_skin,
        stable_tendencies=tendencies,
        current_conditions=conditions,
        next_gap=next_gap,
        ready_for_confirmation=ready_for_confirmation,
        escalation_triggers=escalation_triggers,
    )
    started_at = (
        previous.started_at_conversation_version
        if previous is not None
        else conversation_version
    )
    next_consultation = ConsultationSubstate(
        started_at_conversation_version=started_at,
        observations=observations,
    )
    return DynamicConsultationResult(
        conversation_version=conversation_version,
        observations=observations,
        conclusion=conclusion,
        stable_tendencies=tendencies,
        current_conditions=conditions,
        next_gap=next_gap,
        next_question=next_question,
        ready_for_confirmation=ready_for_confirmation,
        escalation_triggers=escalation_triggers,
        stop_skincare_advice=stop_skincare_advice,
        next_consultation=next_consultation,
    )


def _admit_observations(
    *,
    message: str,
    candidates: Sequence[TurnObservationCandidate],
    source_turn_id: str,
) -> tuple[ConsultationObservation, ...]:
    observations: list[ConsultationObservation] = []
    for candidate in candidates:
        if (
            candidate.observation_id is None
            or candidate.code not in _DYNAMIC_DIMENSIONS
        ):
            continue
        try:
            ground_unique_text(message.strip(), candidate.raw_text)
        except SourceGroundingError:
            continue
        observations.append(
            ConsultationObservation(
                observation_id=candidate.observation_id,
                dimension=candidate.code,
                state=(
                    "present" if candidate.present else "absent"
                ),
                location=candidate.location,
                trigger=candidate.trigger,
                duration=candidate.duration,
                severity=candidate.severity,
                source_text=candidate.raw_text,
                source_turn_id=source_turn_id,
            )
        )
    return _collapse_current_turn_dimensions(observations)


def _collapse_current_turn_dimensions(
    observations: Sequence[ConsultationObservation],
) -> tuple[ConsultationObservation, ...]:
    selected: list[ConsultationObservation] = []
    index_by_dimension: dict[str, int] = {}
    for observation in observations:
        dimension = observation.dimension
        if dimension is None:
            selected.append(observation)
            continue
        if dimension not in index_by_dimension:
            index_by_dimension[dimension] = len(selected)
            selected.append(observation)
            continue
        index = index_by_dimension[dimension]
        if _observation_information_rank(
            observation
        ) > _observation_information_rank(selected[index]):
            selected[index] = observation
    return tuple(selected)


def _observation_information_rank(
    observation: ConsultationObservation,
) -> tuple[int, int, int, int, int]:
    return (
        {
            "unknown": 0,
            "absent": 1,
            "sometimes": 2,
            "present": 3,
        }[observation.state],
        int(observation.location not in {None, "unknown"}),
        int(observation.trigger not in {None, "unknown"}),
        int(observation.duration not in {None, "unknown"}),
        len(observation.source_text),
    )


def _merge_observations(
    previous: Sequence[ConsultationObservation],
    admitted: Sequence[ConsultationObservation],
) -> tuple[ConsultationObservation, ...]:
    merged = [item.model_copy(deep=True) for item in previous]
    for observation in admitted:
        merged = [
            item
            for item in merged
            if (
                item.observation_id != observation.observation_id
                and (
                    item.dimension is None
                    or item.dimension != observation.dimension
                )
            )
        ]
        merged.append(observation)
    return tuple(merged)


def _admit_hypothesis(
    hypothesis: TurnConsultationHypothesis | None,
    *,
    admitted_ids: set[str | None],
) -> TurnConsultationHypothesis | None:
    if hypothesis is None:
        return None
    support_ids = set(hypothesis.supporting_observation_ids)
    if not support_ids or not support_ids <= admitted_ids:
        return None
    return hypothesis


def _accepted_base_skin(
    hypothesis: TurnConsultationHypothesis | None,
    *,
    observations: Sequence[ConsultationObservation],
    admitted_ids: set[str | None],
) -> str | None:
    if hypothesis is None:
        return None
    direction = hypothesis.base_skin_direction
    if direction in {None, "unknown"}:
        return None
    support = tuple(
        item
        for item in observations
        if (
            item.observation_id in admitted_ids
            and item.observation_id
            in hypothesis.supporting_observation_ids
        )
    )
    return (
        direction
        if _direction_is_supported(direction, support)
        else None
    )


def _infer_base_skin(
    observations: Sequence[ConsultationObservation],
) -> str | None:
    if _direction_is_supported("combination", observations):
        return "combination"
    if _direction_is_supported("dry", observations):
        return "dry"
    if _direction_is_supported("oily", observations):
        return "oily"
    if _direction_is_supported("normal", observations):
        return "normal"
    return None


def _direction_is_supported(
    direction: str,
    observations: Sequence[ConsultationObservation],
) -> bool:
    relevant = [
        item
        for item in observations
        if item.dimension in _BASE_DIMENSIONS
    ]
    positive = {
        item.dimension
        for item in relevant
        if item.state in {"present", "sometimes"}
    }
    absent = {
        item.dimension
        for item in relevant
        if item.state == "absent"
    }
    if len(relevant) < 2:
        return False
    if direction == "combination":
        return (
            "oiliness" in positive
            and bool(positive & _DRY_DIMENSIONS)
        )
    if direction == "dry":
        return (
            len(positive & _DRY_DIMENSIONS) >= 2
            or (
                bool(positive & _DRY_DIMENSIONS)
                and "oiliness" in absent
            )
        )
    if direction == "oily":
        return (
            "oiliness" in positive
            and bool(absent & _DRY_DIMENSIONS)
        )
    if direction == "normal":
        return not positive and len(absent) >= 2
    return False


def _accepted_tendencies(
    hypothesis: TurnConsultationHypothesis | None,
    *,
    observations: Sequence[ConsultationObservation],
) -> tuple[TurnConsultationTendency, ...]:
    if hypothesis is None:
        return ()
    present = {
        item.dimension
        for item in observations
        if item.state in {"present", "sometimes"}
    }
    triggers = {
        item.trigger
        for item in observations
        if item.state in {"present", "sometimes"}
    }
    admitted: list[TurnConsultationTendency] = []
    for tendency in hypothesis.stable_tendencies:
        supported = (
            tendency == "sensitivity"
            and bool(present & _REACTION_DIMENSIONS)
        ) or (
            tendency == "seasonal_redness"
            and "redness" in present
            and "seasonal" in triggers
        ) or (
            tendency == "acid_triggered_irritation"
            and bool(present & _REACTION_DIMENSIONS)
            and "acid" in triggers
        ) or (
            tendency == "dehydration"
            and bool(present & _DRY_DIMENSIONS)
        ) or tendency == "other"
        if supported:
            admitted.append(tendency)
    return tuple(admitted)


def _accepted_conditions(
    hypothesis: TurnConsultationHypothesis | None,
    *,
    observations: Sequence[ConsultationObservation],
) -> tuple[TurnConsultationCondition, ...]:
    if hypothesis is None:
        return ()
    present = {
        item.dimension: item
        for item in observations
        if item.state in {"present", "sometimes"}
    }
    admitted: list[TurnConsultationCondition] = []
    for condition in hypothesis.current_conditions:
        dimension = (
            "pain" if condition == "persistent_pain" else condition
        )
        observation = present.get(dimension)
        if observation is None:
            continue
        if (
            condition == "persistent_pain"
            and observation.duration != "persistent"
        ):
            continue
        admitted.append(condition)
    return tuple(admitted)


def _safety_triggers(
    observations: Sequence[ConsultationObservation],
    *,
    source_turn_id: str,
) -> tuple[ConsultationEscalationTrigger, ...]:
    safety_dimensions = {
        "burning",
        "pain",
        "swelling",
        "broken_skin",
        "oozing",
    }
    signal = classify_safety_observations(tuple(
        SafetyObservation(
            code=item.dimension,
            present=item.state in {"present", "sometimes"},
            trigger=item.trigger,
            duration=item.duration,
            severity=item.severity,
        )
        for item in observations
        if item.dimension in safety_dimensions
    ))
    if not signal.trigger_codes:
        return ()
    return (
        ConsultationEscalationTrigger(
            code=signal.trigger_codes[0],
            source_turn_id=source_turn_id,
        ),
    )


def _select_next_gap(
    proposed: TurnNextObservationGap | None,
    *,
    observations: Sequence[ConsultationObservation],
    base_skin: str | None,
) -> TurnNextObservationGap | None:
    ready = _has_tolerance_status(observations) and (
        _has_active_risk_status(observations)
    ) and base_skin is not None
    if proposed == "confirmation" and ready:
        return "confirmation"
    if (
        proposed is not None
        and proposed != "confirmation"
        and _gap_is_missing(
            proposed,
            observations=observations,
            base_skin=base_skin,
        )
    ):
        return proposed
    for gap in (
        "location",
        "persistence_or_trigger",
        "ordinary_product_tolerance",
        "active_damage_risk",
    ):
        if _gap_is_missing(
            gap,
            observations=observations,
            base_skin=base_skin,
        ):
            return gap
    return "confirmation" if ready else None


def _gap_is_missing(
    gap: TurnNextObservationGap,
    *,
    observations: Sequence[ConsultationObservation],
    base_skin: str | None,
) -> bool:
    if gap == "location":
        base = [
            item
            for item in observations
            if (
                item.dimension in _BASE_DIMENSIONS
                and item.state in {"present", "sometimes"}
            )
        ]
        if base_skin is None:
            return True
        known_oily_location = any(
            item.dimension == "oiliness"
            and item.location not in {None, "unknown"}
            for item in base
        )
        known_dry_location = any(
            item.dimension in _DRY_DIMENSIONS
            and item.location not in {None, "unknown"}
            for item in base
        )
        if base_skin == "combination":
            return not (
                known_oily_location and known_dry_location
            )
        if base_skin == "oily":
            return not known_oily_location
        if base_skin == "dry":
            return not known_dry_location
        return False
    if gap == "persistence_or_trigger":
        reactions = [
            item
            for item in observations
            if (
                item.dimension in _REACTION_DIMENSIONS
                and item.state in {"present", "sometimes"}
            )
        ]
        return not reactions or any(
            item.trigger in {None, "unknown"}
            and item.duration in {None, "unknown"}
            for item in reactions
        )
    if gap == "ordinary_product_tolerance":
        return not _has_tolerance_status(observations)
    if gap == "active_damage_risk":
        return not _has_active_risk_status(observations)
    return False


def _has_tolerance_status(
    observations: Sequence[ConsultationObservation],
) -> bool:
    return any(
        item.dimension == "product_tolerance"
        and item.state in {"present", "absent", "sometimes"}
        for item in observations
    )


def _has_active_risk_status(
    observations: Sequence[ConsultationObservation],
) -> bool:
    return any(
        item.dimension in _ACTIVE_RISK_DIMENSIONS
        and item.state in {"present", "absent", "sometimes"}
        for item in observations
    )


def _question_for_gap(
    gap: TurnNextObservationGap,
    *,
    base_skin: str | None,
) -> ConsultationQuestion:
    if gap == "location":
        prompt = "平时哪里容易出油，哪里更容易干燥或紧绷？"
    elif gap == "persistence_or_trigger":
        prompt = "通常什么时候更容易泛红或刺痛，比如换季或使用新产品后？"
    elif gap == "ordinary_product_tolerance":
        prompt = "平时使用基础保湿产品时，会不会刺痛、发热或不舒服？"
    elif gap == "active_damage_risk":
        prompt = "现在有没有持续红肿、明显疼痛、破皮或渗出？"
    else:
        label = _SKIN_LABELS[base_skin]
        prompt = f"目前看更接近{label}，这个判断和你的感受一致吗？"
    return ConsultationQuestion(code=gap, prompt=prompt)


def _build_conclusion(
    *,
    observations: Sequence[ConsultationObservation],
    base_skin: str | None,
    stable_tendencies: Sequence[TurnConsultationTendency],
    current_conditions: Sequence[TurnConsultationCondition],
    next_gap: TurnNextObservationGap | None,
    ready_for_confirmation: bool,
    escalation_triggers: Sequence[ConsultationEscalationTrigger],
) -> ProvisionalConsultationConclusion | None:
    if not observations:
        return None
    evidence = tuple(
        item.source_text
        for item in observations
        if item.source_text is not None
    )[:8]
    if not evidence:
        return None
    if escalation_triggers:
        labels = {
            "persistent_swelling": "持续红肿",
            "persistent_burning": "持续灼痛",
            "pain": "明显疼痛",
            "broken_skin": "破皮",
            "oozing": "渗出",
        }
        finding = "、".join(
            labels[item.code] for item in escalation_triggers
        )
        escalation = (
            f"目前提到{finding}，先暂停新产品和刺激性护肤，"
            "尽快请皮肤科医生判断。"
        )
    else:
        escalation = (
            "如果出现持续红肿、明显疼痛、破皮或渗出，"
            "先暂停新产品并及时就医。"
        )
    return ProvisionalConsultationConclusion(
        skin_target=base_skin,
        stable_tendencies=tuple(stable_tendencies),
        current_conditions=tuple(current_conditions),
        confidence=(
            "high"
            if ready_for_confirmation
            else "medium"
            if base_skin is not None
            else "low"
        ),
        evidence=evidence,
        uncertainties=(
            ()
            if ready_for_confirmation or escalation_triggers
            else (next_gap,)
            if next_gap is not None
            else ()
        ),
        escalation=escalation,
        confirmed_by_user=False,
    )


__all__ = [
    "DynamicConsultationResult",
    "PreparedConsultationEvidence",
    "advance_dynamic_consultation",
    "prepare_dynamic_consultation_evidence",
]
