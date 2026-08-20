from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide.retrieval.category_taxonomy import (
    category_profile_for_topic,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.source_grounding import (
    SourceGroundingError,
    ground_unique_text,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnMeaning,
    TurnPreferenceCandidate,
)


AdmissionDisposition = Literal[
    "admitted",
    "retained_free",
    "deferred_until_topic",
    "rejected_protocol",
]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AdmissionOutcome(_StrictFrozen):
    atom_kind: str = Field(min_length=1, max_length=64)
    raw_text: str = Field(min_length=1, max_length=256)
    disposition: AdmissionDisposition
    normalized_value: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    reason: str = Field(min_length=1, max_length=256)


class SemanticAdmissionResult(_StrictFrozen):
    outcomes: tuple[AdmissionOutcome, ...]

    @field_validator("outcomes", mode="before")
    @classmethod
    def freeze_outcomes(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    def for_kind(self, atom_kind: str) -> tuple[AdmissionOutcome, ...]:
        return tuple(
            item
            for item in self.outcomes
            if item.atom_kind == atom_kind
        )


def admit_turn_meaning(
    *,
    message: str,
    meaning: TurnMeaning,
    topic: TopicCode | None,
    active_topic: TopicCode | None = None,
    concept_catalog: ConceptPreferenceCatalog | None,
) -> SemanticAdmissionResult:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be nonempty")
    if type(meaning) is not TurnMeaning:
        raise TypeError("meaning must be an exact TurnMeaning")
    if topic is not None and not isinstance(topic, TopicCode):
        raise TypeError("topic must be a TopicCode or None")
    if active_topic is not None and not isinstance(
        active_topic,
        TopicCode,
    ):
        raise TypeError("active_topic must be a TopicCode or None")
    if (
        concept_catalog is not None
        and not isinstance(concept_catalog, ConceptPreferenceCatalog)
    ):
        raise TypeError(
            "concept_catalog must be a ConceptPreferenceCatalog or None"
        )

    outcomes = [
        AdmissionOutcome(
            atom_kind="task_focus",
            raw_text=meaning.operation_hint,
            disposition="admitted",
            normalized_value=meaning.operation_hint,
            reason="closed operation protocol value",
        ),
        AdmissionOutcome(
            atom_kind="task_focus",
            raw_text=meaning.continuity_hint,
            disposition="admitted",
            normalized_value=meaning.continuity_hint,
            reason="closed continuity protocol value",
        ),
        AdmissionOutcome(
            atom_kind="subject_scope",
            raw_text=meaning.subject_scope_hint,
            disposition="admitted",
            normalized_value=meaning.subject_scope_hint,
            reason="closed subject-scope protocol value",
        ),
    ]
    if meaning.topic_hint is not None:
        outcomes.append(
            AdmissionOutcome(
                atom_kind="task_focus",
                raw_text=meaning.topic_hint,
                disposition="admitted",
                normalized_value=meaning.topic_hint,
                reason="closed topic protocol value",
            )
        )

    for item in meaning.reference_mentions:
        if (
            item.object_family_hint == "topic"
            and meaning.continuity_hint == "return_to_focus"
            and meaning.product_mentions
            and topic is not None
            and active_topic is topic
        ):
            outcomes.append(
                AdmissionOutcome(
                    atom_kind="reference",
                    raw_text=item.raw_text,
                    disposition="admitted",
                    normalized_value=item.object_family_hint,
                    reason="typed current topic matches active context",
                )
            )
            continue
        outcomes.append(
            _source_bound_outcome(
                message,
                atom_kind="reference",
                raw_text=item.raw_text,
                normalized_value=item.object_family_hint,
            )
        )
    outcomes.extend(
        _source_bound_outcome(
            message,
            atom_kind="product_mention",
            raw_text=item.raw_text,
            normalized_value=item.raw_text,
        )
        for item in meaning.product_mentions
    )
    outcomes.extend(
        _source_bound_outcome(
            message,
            atom_kind="budget",
            raw_text=item.raw_text,
            normalized_value=item.relation,
        )
        for item in meaning.budget_candidates
    )
    outcomes.extend(
        _preference_outcome(
            message,
            candidate=item,
            topic=topic,
            concept_catalog=concept_catalog,
        )
        for item in meaning.preference_candidates
    )
    outcomes.extend(
        _source_bound_outcome(
            message,
            atom_kind="constraint_change",
            raw_text=item.raw_text,
            normalized_value=(
                f"{item.parent_concept}:{item.requested_change}"
            ),
        )
        for item in meaning.constraint_changes
    )
    if meaning.pending_response_hint != "unknown":
        outcomes.append(
            AdmissionOutcome(
                atom_kind="pending_response",
                raw_text=meaning.pending_response_hint,
                disposition="admitted",
                normalized_value=meaning.pending_response_hint,
                reason="closed pending response hint",
            )
        )
    outcomes.extend(
        _source_bound_outcome(
            message,
            atom_kind="relative_preference",
            raw_text=item.raw_text,
            normalized_value=item.concept_id or item.raw_text,
        )
        for item in meaning.relative_candidates
    )

    observation_outcomes = [
        _source_bound_outcome(
            message,
            atom_kind="consultation_observation",
            raw_text=item.raw_text,
            normalized_value=item.code,
        )
        for item in meaning.observation_candidates
    ]
    outcomes.extend(observation_outcomes)

    if meaning.consultation_hypothesis is not None:
        hypothesis = meaning.consultation_hypothesis
        admitted_ids = {
            candidate.observation_id
            for candidate, outcome in zip(
                meaning.observation_candidates,
                observation_outcomes,
                strict=True,
            )
            if (
                candidate.observation_id is not None
                and outcome.disposition == "admitted"
            )
        }
        support_ids = set(hypothesis.supporting_observation_ids)
        supported = bool(support_ids) and support_ids <= admitted_ids
        outcomes.append(
            AdmissionOutcome(
                atom_kind="consultation_hypothesis",
                raw_text=",".join(
                    hypothesis.supporting_observation_ids
                ) or "no_support",
                disposition=(
                    "admitted" if supported else "rejected_protocol"
                ),
                normalized_value=(
                    hypothesis.base_skin_direction
                    or ",".join(hypothesis.stable_tendencies)
                    or ",".join(hypothesis.current_conditions)
                    or None
                ),
                reason=(
                    "all hypothesis support is source-bound"
                    if supported
                    else "hypothesis references unadmitted observations"
                ),
            )
        )
    if meaning.next_observation_gap is not None:
        outcomes.append(
            AdmissionOutcome(
                atom_kind="next_observation_gap",
                raw_text=meaning.next_observation_gap,
                disposition="admitted",
                normalized_value=meaning.next_observation_gap,
                reason="closed consultation-gap protocol value",
            )
        )
    return SemanticAdmissionResult(outcomes=tuple(outcomes))


def _source_bound_outcome(
    message: str,
    *,
    atom_kind: str,
    raw_text: str,
    normalized_value: str | None,
) -> AdmissionOutcome:
    try:
        ground_unique_text(message.strip(), raw_text)
    except SourceGroundingError:
        return AdmissionOutcome(
            atom_kind=atom_kind,
            raw_text=raw_text,
            disposition="rejected_protocol",
            normalized_value=None,
            reason="raw_text is not uniquely source-bound",
        )
    return AdmissionOutcome(
        atom_kind=atom_kind,
        raw_text=raw_text,
        disposition="admitted",
        normalized_value=normalized_value,
        reason="raw_text is uniquely source-bound",
    )


def _preference_outcome(
    message: str,
    *,
    candidate: TurnPreferenceCandidate,
    topic: TopicCode | None,
    concept_catalog: ConceptPreferenceCatalog | None,
) -> AdmissionOutcome:
    source = _source_bound_outcome(
        message,
        atom_kind="preference",
        raw_text=candidate.raw_text,
        normalized_value=(
            candidate.concept_id or candidate.raw_text
        ),
    )
    if source.disposition == "rejected_protocol":
        return source
    if (
        candidate.field_key == "ingredient"
        and candidate.polarity == "avoid"
    ):
        return AdmissionOutcome(
            atom_kind="preference",
            raw_text=candidate.raw_text,
            disposition="rejected_protocol",
            normalized_value=None,
            reason="ingredient exclusions require ingredient_exclusion",
        )
    if candidate.strength != "ordinary":
        return AdmissionOutcome(
            atom_kind="preference",
            raw_text=candidate.raw_text,
            disposition="admitted",
            normalized_value=candidate.raw_text,
            reason="non-ordinary preference is retained for safety handling",
        )
    if concept_catalog is None:
        return AdmissionOutcome(
            atom_kind="preference",
            raw_text=candidate.raw_text,
            disposition="retained_free",
            normalized_value=candidate.raw_text,
            reason="open descriptor has no reviewed concept identity",
        )
    effective_concept_id = candidate.concept_id
    if topic is not None:
        effective_concept_id = (
            concept_catalog.resolve_source_value(
                profile=category_profile_for_topic(topic),
                field_key=candidate.field_key,
                raw_text=candidate.raw_text,
            )
            or effective_concept_id
        )
    if effective_concept_id is None:
        return AdmissionOutcome(
            atom_kind="preference",
            raw_text=candidate.raw_text,
            disposition="retained_free",
            normalized_value=candidate.raw_text,
            reason="open descriptor has no reviewed concept identity",
        )
    known_concept = any(
        item.field_key == candidate.field_key
        and item.concept_id == effective_concept_id
        for item in concept_catalog.entries
    )
    if not known_concept:
        return AdmissionOutcome(
            atom_kind="preference",
            raw_text=candidate.raw_text,
            disposition="retained_free",
            normalized_value=candidate.raw_text,
            reason="concept identity is outside the reviewed catalog",
        )
    if topic is None:
        return AdmissionOutcome(
            atom_kind="preference",
            raw_text=candidate.raw_text,
            disposition="deferred_until_topic",
            normalized_value=effective_concept_id,
            reason="reviewed concept awaits a product topic",
        )
    if concept_catalog.admits(
        profile=category_profile_for_topic(topic),
        field_key=candidate.field_key,
        concept_id=effective_concept_id,
    ):
        return AdmissionOutcome(
            atom_kind="preference",
            raw_text=candidate.raw_text,
            disposition="admitted",
            normalized_value=effective_concept_id,
            reason=(
                "reviewed source value resolved the product concept"
                if effective_concept_id != candidate.concept_id
                else "reviewed concept is valid for the product topic"
            ),
        )
    return AdmissionOutcome(
        atom_kind="preference",
        raw_text=candidate.raw_text,
        disposition="retained_free",
        normalized_value=candidate.raw_text,
        reason="reviewed concept is not applicable to the product topic",
    )


__all__ = [
    "AdmissionOutcome",
    "SemanticAdmissionResult",
    "admit_turn_meaning",
]
