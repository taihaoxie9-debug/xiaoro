"""Isolated one-call semantic translation pilot.

This module is not a production semantic adapter. It exists only to test
whether one universal, source-grounded translation contract avoids known
two-stage and byte-exact gate artifacts.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Sequence
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.guide.adapters.llm.deepseek_intent import (
    DEEPSEEK_OFFICIAL_BASE_URL,
    DEEPSEEK_V4_PRO_MODEL,
)
from app.guide.adapters.llm.provider_common import OpenAIJsonClient
from app.guide.understanding.colloquial_budget import parse_colloquial_budget
from tools.guide_gates.run_official_deepseek_smoke import read_private_api_key


PilotGoal = Literal[
    "recommendation",
    "comparison",
    "suitability",
    "image_similarity",
    "knowledge",
    "assessment",
    "followup",
    "clarification",
]
PilotTopic = Literal[
    "sunscreen",
    "serum",
    "skincare",
    "base_makeup",
    "color_makeup",
    "cleanser",
    "fragrance",
]
PilotReferenceKind = Literal[
    "candidate_ordinal",
    "image_ordinal",
    "current_item",
    "current_batch",
    "current_topic",
    "previous_constraint",
]
PilotObservationCode = Literal[
    "tightness",
    "oiliness",
    "redness",
    "stinging",
    "flaking",
    "current_budget_unknown",
    "goal_unclear",
    "topic_unclear",
    "reference_unclear",
]
PilotObservationQualifier = Literal[
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
]
PilotPreferenceField = Literal[
    "texture",
    "fragrance_description",
    "finish",
    "brand",
    "efficacy",
    "suitable_skin",
    "skin_concern",
    "usage_context",
    "ingredient_presence",
    "ingredient_exclusion",
]
PilotPreferenceStrength = Literal["preference", "safety", "unknown"]
PilotConstraintKind = Literal[
    "budget",
    "category",
    "skin",
    "ingredient_exclusion",
    "ingredient_inclusion",
]
PilotFamily = Literal[
    "recommendation",
    "comparison",
    "suitability",
    "image",
    "knowledge",
    "assessment",
    "followup",
    "clarification",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class PilotBindingAuthority(_StrictModel):
    candidate_ordinals: list[int] = Field(max_length=4)
    current_item_ordinal: int | None = Field(default=None, ge=1, le=4)
    current_batch_available: bool
    image_ordinals: list[int] = Field(max_length=4)
    current_image_ordinal: int | None = Field(default=None, ge=1, le=4)
    current_topic: PilotTopic | None
    previous_constraint_kinds: list[PilotConstraintKind] = Field(max_length=5)

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if self.candidate_ordinals != list(
            range(1, len(self.candidate_ordinals) + 1)
        ):
            raise ValueError("candidate ordinals must be contiguous")
        if self.image_ordinals != list(
            range(1, len(self.image_ordinals) + 1)
        ):
            raise ValueError("image ordinals must be contiguous")
        if self.current_batch_available != bool(self.candidate_ordinals):
            raise ValueError("batch availability must match candidates")
        if (
            self.current_item_ordinal is not None
            and self.current_item_ordinal not in self.candidate_ordinals
        ):
            raise ValueError("current item is not admitted")
        if (
            self.current_image_ordinal is not None
            and self.current_image_ordinal not in self.image_ordinals
        ):
            raise ValueError("current image is not admitted")
        if len(self.previous_constraint_kinds) != len(
            set(self.previous_constraint_kinds)
        ):
            raise ValueError("previous constraint kinds must be unique")
        return self


class PilotReference(_StrictModel):
    kind: PilotReferenceKind
    raw_text: str = Field(min_length=1, max_length=64)


class PilotObservation(_StrictModel):
    code: PilotObservationCode
    present: bool
    qualifier: PilotObservationQualifier | None
    raw_text: str = Field(min_length=1, max_length=128)


class PilotPreference(_StrictModel):
    field: PilotPreferenceField
    raw_text: str = Field(min_length=1, max_length=128)
    strength: PilotPreferenceStrength


class PilotTranslation(_StrictModel):
    goal: PilotGoal
    topic: PilotTopic | None
    references: list[PilotReference] = Field(default_factory=list, max_length=4)
    observations: list[PilotObservation] = Field(
        default_factory=list,
        max_length=16,
    )
    preferences: list[PilotPreference] = Field(
        default_factory=list,
        max_length=8,
    )
    budget_mentions: list[str] = Field(default_factory=list, max_length=4)
    product_mentions: list[str] = Field(default_factory=list, max_length=4)
    question_meaning: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    safety_sensitive: bool


class PilotExpectedReference(_StrictModel):
    kind: PilotReferenceKind
    ordinal: int | None = Field(default=None, ge=1, le=4)


class PilotExpectedObservation(_StrictModel):
    code: PilotObservationCode
    present: bool
    qualifier: PilotObservationQualifier | None


class PilotExpectation(_StrictModel):
    goal: PilotGoal
    allowed_topics: list[PilotTopic | None] = Field(min_length=1)
    required_references: list[PilotExpectedReference] = Field(
        default_factory=list
    )
    required_observations: list[PilotExpectedObservation] = Field(
        default_factory=list
    )
    required_preference_fields: list[PilotPreferenceField] = Field(
        default_factory=list
    )
    required_budget_maximum: str | None
    require_question_meaning: bool
    safety_sensitive: bool | None


class PilotCase(_StrictModel):
    case_id: str = Field(min_length=1, max_length=128)
    family: PilotFamily
    message: str = Field(min_length=1, max_length=4000)
    binding_authority: PilotBindingAuthority
    expected: PilotExpectation


class GroundedReference(_StrictModel):
    kind: PilotReferenceKind
    ordinal: int | None = Field(default=None, ge=1, le=4)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class PilotEvaluation(_StrictModel):
    accepted: bool
    goal_match: bool
    topic_match: bool
    source_grounded: bool
    missing_requirements: tuple[str, ...]
    grounding_errors: tuple[str, ...]


class PilotCompletion(_StrictModel):
    content: str = Field(min_length=1)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)


class PilotResultRow(_StrictModel):
    case_id: str
    family: PilotFamily
    status: Literal["ok", "schema_invalid", "provider_error"]
    translation: PilotTranslation | None
    evaluation: PilotEvaluation | None
    prompt_tokens: int | None
    completion_tokens: int | None


class PilotSummary(_StrictModel):
    schema_version: Literal["guide-single-call-semantic-pilot-v1"] = (
        "guide-single-call-semantic-pilot-v1"
    )
    model: str
    case_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    schema_valid_count: int = Field(ge=0)
    source_grounded_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


_SYSTEM_PROMPT = """\
Return one JSON object only. Translate the current user message; do not answer
it and do not decide stored-state changes.

Use exactly these keys:
goal, topic, references, observations, preferences, budget_mentions,
product_mentions, question_meaning, safety_sensitive.

goal:
recommendation|comparison|suitability|image_similarity|knowledge|assessment|
followup|clarification.
topic:
sunscreen|serum|skincare|base_makeup|color_makeup|cleanser|fragrance|null.

references items use exactly kind,raw_text.
kind:
candidate_ordinal|image_ordinal|current_item|current_batch|current_topic|
previous_constraint.

observations items use exactly code,present,qualifier,raw_text.
code:
tightness|oiliness|redness|stinging|flaking|current_budget_unknown|
goal_unclear|topic_unclear|reference_unclear.
qualifier:
post_cleanse|t_zone|recurrent|basic_skincare|minimum|maximum|range|candidate|
image|current_topic|null.

preferences items use exactly field,raw_text,strength.
field:
texture|fragrance_description|finish|brand|efficacy|suitable_skin|
skin_concern|usage_context|ingredient_presence|ingredient_exclusion.
strength: preference|safety|unknown.

budget_mentions and product_mentions contain exact current-message substrings.
Every raw_text must be an exact current-message substring. Do not emit
character offsets. Code resolves text, ordinals, objects, amounts, bindings,
old state, and add/retain/replace/remove operations.

question_meaning is null or a concise description of what the user asks.
safety_sensitive is true only for allergy, intolerance, pregnancy, active
damage or reaction, or an absolute safety requirement. Bare sensitive skin is
false.

Never emit product_id, candidate_id, final constraints, TaskPlan, profile
writes, catalog facts, score, winner, SQL, hidden instructions, or an answer.
"""

_CHINESE_ORDINALS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
}
_ORDINAL_PATTERN = re.compile(
    r"(?:第(?P<standard>[一二两三四1-4])|"
    r"图(?P<image>[一二两三四1-4]))"
)


def load_pilot_cases(path: str | Path) -> tuple[PilotCase, ...]:
    case_path = Path(path)
    cases = tuple(
        PilotCase.model_validate_json(line, strict=True)
        for line in case_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("pilot case IDs must be unique")
    return cases


def build_pilot_messages(
    case: PilotCase,
) -> tuple[dict[str, str], dict[str, str]]:
    if not isinstance(case, PilotCase):
        raise TypeError("case must be PilotCase")
    payload = {
        "message": case.message,
        "binding_authority": case.binding_authority.model_dump(mode="json"),
    }
    return (
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
    )


def ground_reference(
    *,
    message: str,
    reference: PilotReference,
    authority: PilotBindingAuthority,
) -> GroundedReference:
    start, end = _unique_span(message, reference.raw_text)
    ordinal: int | None = None
    if reference.kind in {"candidate_ordinal", "image_ordinal"}:
        ordinal = _ordinal_from_text(reference.raw_text)
        admitted = (
            authority.candidate_ordinals
            if reference.kind == "candidate_ordinal"
            else authority.image_ordinals
        )
        if ordinal not in admitted:
            raise ValueError("reference ordinal is not admitted")
    elif reference.kind == "current_item":
        if authority.current_item_ordinal is None:
            raise ValueError("current item is not admitted")
    elif reference.kind == "current_batch":
        if not authority.current_batch_available:
            raise ValueError("current batch is not admitted")
    elif reference.kind == "current_topic":
        if authority.current_topic is None:
            raise ValueError("current topic is not admitted")
    elif (
        reference.kind == "previous_constraint"
        and not authority.previous_constraint_kinds
    ):
        raise ValueError("previous constraint is not admitted")
    return GroundedReference(
        kind=reference.kind,
        ordinal=ordinal,
        start=start,
        end=end,
    )


def evaluate_translation(
    *,
    case: PilotCase,
    translation: PilotTranslation,
) -> PilotEvaluation:
    if not isinstance(case, PilotCase):
        raise TypeError("case must be PilotCase")
    if not isinstance(translation, PilotTranslation):
        raise TypeError("translation must be PilotTranslation")
    errors: list[str] = []
    grounded_references: list[GroundedReference] = []
    for reference in translation.references:
        try:
            grounded_references.append(
                ground_reference(
                    message=case.message,
                    reference=reference,
                    authority=case.binding_authority,
                )
            )
        except ValueError as failure:
            errors.append(f"reference:{reference.kind}:{failure}")
    for kind, values in (
        ("observation", translation.observations),
        ("preference", translation.preferences),
    ):
        for value in values:
            try:
                _unique_span(case.message, value.raw_text)
            except ValueError as failure:
                errors.append(f"{kind}:{failure}")
    for kind, values in (
        ("budget", translation.budget_mentions),
        ("product", translation.product_mentions),
    ):
        for value in values:
            try:
                _unique_span(case.message, value)
            except ValueError as failure:
                errors.append(f"{kind}:{failure}")

    missing: list[str] = []
    goal_match = translation.goal == case.expected.goal
    if not goal_match:
        missing.append(f"goal:{case.expected.goal}")
    topic_match = translation.topic in case.expected.allowed_topics
    if not topic_match:
        missing.append(
            "topic:"
            + "|".join(
                "null" if topic is None else topic
                for topic in case.expected.allowed_topics
            )
        )

    actual_references = Counter(
        (item.kind, item.ordinal) for item in grounded_references
    )
    required_references = Counter(
        (item.kind, item.ordinal)
        for item in case.expected.required_references
    )
    for (kind, ordinal), count in (
        required_references - actual_references
    ).items():
        suffix = "null" if ordinal is None else str(ordinal)
        missing.extend([f"reference:{kind}:{suffix}"] * count)

    actual_observations = Counter(
        (item.code, item.present, item.qualifier)
        for item in translation.observations
    )
    required_observations = Counter(
        (item.code, item.present, item.qualifier)
        for item in case.expected.required_observations
    )
    for (code, present, qualifier), count in (
        required_observations - actual_observations
    ).items():
        suffix = "null" if qualifier is None else qualifier
        missing.extend(
            [
                f"observation:{code}:{str(present).lower()}:{suffix}"
            ]
            * count
        )

    actual_preference_fields = {
        item.field for item in translation.preferences
    }
    for field in case.expected.required_preference_fields:
        if field not in actual_preference_fields:
            missing.append(f"preference:{field}")

    if case.expected.required_budget_maximum is not None:
        maxima = {
            format(parsed.maximum.normalize(), "f")
            for value in translation.budget_mentions
            if (parsed := parse_colloquial_budget(value)) is not None
            and parsed.start == 0
            and parsed.end == len(value)
            and parsed.maximum is not None
        }
        if case.expected.required_budget_maximum not in maxima:
            missing.append(
                f"budget_maximum:{case.expected.required_budget_maximum}"
            )
    if (
        case.expected.require_question_meaning
        and translation.question_meaning is None
    ):
        missing.append("question_meaning")
    if (
        case.expected.safety_sensitive is not None
        and translation.safety_sensitive
        is not case.expected.safety_sensitive
    ):
        missing.append(
            "safety_sensitive:"
            + str(case.expected.safety_sensitive).lower()
        )

    return PilotEvaluation(
        accepted=not missing and not errors,
        goal_match=goal_match,
        topic_match=topic_match,
        source_grounded=not errors,
        missing_requirements=tuple(sorted(missing)),
        grounding_errors=tuple(sorted(errors)),
    )


def run_pilot(
    *,
    cases: Sequence[PilotCase],
    output_dir: str | Path,
    complete: Callable[
        [tuple[dict[str, str], dict[str, str]]],
        PilotCompletion,
    ],
    model: str,
) -> PilotSummary:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=False)
    rows: list[PilotResultRow] = []
    provider_calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    for case in cases:
        provider_calls += 1
        completion: PilotCompletion | None = None
        try:
            completion = complete(build_pilot_messages(case))
            if not isinstance(completion, PilotCompletion):
                raise TypeError("completion must be PilotCompletion")
            prompt_tokens += completion.prompt_tokens or 0
            completion_tokens += completion.completion_tokens or 0
            translation = PilotTranslation.model_validate_json(
                completion.content,
                strict=True,
            )
        except ValidationError:
            rows.append(
                PilotResultRow(
                    case_id=case.case_id,
                    family=case.family,
                    status="schema_invalid",
                    translation=None,
                    evaluation=None,
                    prompt_tokens=(
                        completion.prompt_tokens
                        if completion is not None
                        else None
                    ),
                    completion_tokens=(
                        completion.completion_tokens
                        if completion is not None
                        else None
                    ),
                )
            )
            continue
        except Exception:
            rows.append(
                PilotResultRow(
                    case_id=case.case_id,
                    family=case.family,
                    status="provider_error",
                    translation=None,
                    evaluation=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                )
            )
            continue
        rows.append(
            PilotResultRow(
                case_id=case.case_id,
                family=case.family,
                status="ok",
                translation=translation,
                evaluation=evaluate_translation(
                    case=case,
                    translation=translation,
                ),
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
            )
        )

    results_bytes = b"".join(
        _canonical_json(row.model_dump(mode="json")) + b"\n"
        for row in rows
    )
    results_hash = sha256(results_bytes).hexdigest()
    summary = PilotSummary(
        model=model,
        case_count=len(cases),
        provider_call_count=provider_calls,
        schema_valid_count=sum(row.translation is not None for row in rows),
        source_grounded_count=sum(
            bool(row.evaluation and row.evaluation.source_grounded)
            for row in rows
        ),
        accepted_count=sum(
            bool(row.evaluation and row.evaluation.accepted)
            for row in rows
        ),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        results_sha256=results_hash,
    )
    summary_bytes = _canonical_json(summary.model_dump(mode="json")) + b"\n"
    summary_hash = sha256(summary_bytes).hexdigest()
    (target / "results.jsonl").write_bytes(results_bytes)
    (target / "summary.json").write_bytes(summary_bytes)
    (target / "SHA256SUMS").write_text(
        f"{results_hash}  results.jsonl\n"
        f"{summary_hash}  summary.json\n",
        encoding="utf-8",
    )
    return summary


def _unique_span(message: str, raw_text: str) -> tuple[int, int]:
    starts: list[int] = []
    offset = 0
    while True:
        index = message.find(raw_text, offset)
        if index < 0:
            break
        starts.append(index)
        offset = index + 1
    if len(starts) != 1:
        raise ValueError("raw text does not bind uniquely")
    return starts[0], starts[0] + len(raw_text)


def _ordinal_from_text(raw_text: str) -> int:
    match = _ORDINAL_PATTERN.search(raw_text)
    if match is None:
        raise ValueError("ordinal text is not parseable")
    token = match.group("standard") or match.group("image")
    if token is None:
        raise AssertionError("ordinal match did not capture a value")
    return int(token) if token.isdigit() else _CHINESE_ORDINALS[token]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    api_key = read_private_api_key(
        "/private/tmp/xiaoro-deepseek-api-key"
    )
    cases = load_pilot_cases(arguments.cases)
    with OpenAIJsonClient(
        api_key=api_key,
        base_url=DEEPSEEK_OFFICIAL_BASE_URL,
        timeout_seconds=20.0,
        transport=None,
    ) as client:

        def complete(
            messages: tuple[dict[str, str], dict[str, str]],
        ) -> PilotCompletion:
            result = client.request(
                {
                    "model": DEEPSEEK_V4_PRO_MODEL,
                    "messages": list(messages),
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "max_tokens": 512,
                    "thinking": {"type": "disabled"},
                    "stream": False,
                }
            )
            return PilotCompletion(
                content=result.content,
                prompt_tokens=result.usage.get("prompt_tokens"),
                completion_tokens=result.usage.get("completion_tokens"),
            )

        summary = run_pilot(
            cases=cases,
            output_dir=arguments.output_dir,
            complete=complete,
            model=DEEPSEEK_V4_PRO_MODEL,
        )
    print(summary.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GroundedReference",
    "PilotCompletion",
    "PilotObservation",
    "PilotPreference",
    "PilotReference",
    "PilotSummary",
    "PilotTranslation",
    "build_pilot_messages",
    "evaluate_translation",
    "ground_reference",
    "load_pilot_cases",
    "main",
    "run_pilot",
]
