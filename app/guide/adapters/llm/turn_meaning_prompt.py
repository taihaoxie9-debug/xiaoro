from __future__ import annotations

import json
import re

from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.semantic_route_contracts import (
    SemanticRouteBindingAuthority,
)


TURN_MEANING_PROMPT_VERSION = "guide-turn-meaning-prompt-v17"
_CONCEPT_ID = re.compile(
    r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$"
)


def build_turn_meaning_messages(
    message: str,
    authority: SemanticRouteBindingAuthority,
    *,
    concept_catalog: tuple[str, ...],
) -> tuple[dict[str, str], dict[str, str]]:
    if (
        not isinstance(message, str)
        or not message.strip()
        or len(message) > 4000
    ):
        raise ValueError("message must contain 1 to 4000 characters")
    if not isinstance(authority, SemanticRouteBindingAuthority):
        raise TypeError(
            "authority must be SemanticRouteBindingAuthority"
        )
    if (
        not concept_catalog
        or concept_catalog != tuple(sorted(set(concept_catalog)))
        or any(_CONCEPT_ID.fullmatch(item) is None for item in concept_catalog)
    ):
        raise ValueError(
            "concept catalog must be nonempty, sorted, unique, and scoped"
        )
    catalog = json.dumps(
        concept_catalog,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    system = f"""\
Return one strict JSON object only. Translate the current user message; do not
answer it. Use one universal schema with exactly these keys:
operation_hint, topic_hint, continuity_hint, subject_scope_hint,
reference_mentions, product_mentions, budget_candidates,
observation_candidates, preference_candidates, relative_candidates,
consultation_hypothesis, next_observation_gap, question_meaning,
safety_language.
Emit every listed key. Use [] for empty collections and null for optional
single values. Never omit a key and never add a key.

operation_hint:
recommendation|comparison|suitability|image_identity|image_similarity|
knowledge|assessment|followup|clarification.
recommendation means selecting or finding products, including changing
selection constraints. Questions about texture, usage, caution, or facts
about a referenced existing product are followup or knowledge, not
recommendation. followup requires prior binding authority for a current item,
batch, or image, or explicit continuation language. With no prior binding
authority, a product named in the current message uses knowledge.
comparison requires two or more already supplied or bindable objects.
image_identity means identifying the product shown in a current or uploaded image.
It does not ask for product facts, suitability, alternatives, or a comparison.
image_similarity means using one current or uploaded image product as the anchor
to find visually or functionally similar alternative products.
A requested result count is not a set of comparison objects; asking for two or
three alternatives remains image_similarity.
Budget, texture, skin, or scenario constraints can coexist with image_similarity
and do not change it to recommendation or comparison.
suitability asks whether a bound product or image fits a person, skin type,
condition, or use case. assessment describes or
clarifies the person's current skin observations. A current skin symptom, reaction, or damage
report uses assessment even when the user asks what to do.
When binding_authority has no current item, batch, image, topic, or pending
clarification, followup and continue are forbidden. A factual category
question uses knowledge and new_task; an explicitly named product question
also uses knowledge and new_task.
A question about the currently identified image product uses continue.
Whether that image product fits a skin type, condition, person, or use case
uses suitability, not knowledge or new_task.
topic_hint:
sunscreen|serum|skincare|base_makeup|color_makeup|cleanser|fragrance|null.
topic_hint describes the current message, not prior state. For assessment,
when the current message does not name a product or category, use skincare or
null; never inherit active_topic from an earlier shopping task.
continuity_hint:
continue|return_to_focus|new_task|unknown.
Use new_task only for an explicit independent task. Use return_to_focus when
the user explicitly returns to an earlier product or mode. Use continue for
a current object, current batch, pending reply, or constraint continuation.
When active_dialogue=consultation and awaiting_reply=true, a direct symptom,
location, duration, tolerance, or correction answer uses continue.
Use new_task only when the current message explicitly starts an independent
goal or switches subject or task.
A subject switch from other to self is new_task even when the category is
unchanged.
A temporary named-product suitability detour that reuses the active
consultation state uses continue.
An ambiguous reference remains clarification; do not guess an image or
product ordinal.
Explicitly returning to an earlier preserved focus is return_to_focus, not
continue, even when that earlier object remains bindable.
Determine return_to_focus from the relationship between the current active mode and preserved binding authority.
When the user leaves one mode and then resumes a preserved product, batch, image, or consultation focus, emit return_to_focus even if that reference can also be bound directly.
A complete selection request that supplies its own category and selection
constraints is new_task when it starts shopping from a non-shopping focus or
does not revise a current batch. A discourse word meaning "still" or "again"
does not by itself make the request a continuation.
Pending confirmation or rejection uses followup or clarification and
continue. Do not invent a new budget candidate when the reply only accepts or
rejects the pending value.
A pending rejection without a new numeric amount emits no budget candidate.
Every emitted budget relation is one of maximum, minimum, range, or
approximate; never emit unknown.
subject_scope_hint:
self|other|unknown. Use other for a friend or another person; do not merge
that person's facts into the user's profile.

reference_mentions items use exactly:
raw_text, object_family_hint, ordinal_hint, plurality_hint.
object_family_hint: product|image|topic|constraint|unknown.
ordinal_hint: 1..4|null. plurality_hint: single|batch|unknown.
These values are translation hints. Code owns final binding.
Use the supplied binding_authority to emit source-grounded current-item,
ordinal, batch, image, topic, and previous-constraint references. Never emit
a reference that the authority cannot support.

product_mentions items use exactly raw_text.
Generic category or usage phrases are not product names. Emit a
product_mentions item only for text intended to identify a specific product,
variant, controlled nickname, or brand-and-product name. A generic category
phrase in a factual question belongs in topic_hint and question_meaning.
budget_candidates items use exactly:
raw_text, relation, minimum, maximum.
relation: maximum|minimum|range|approximate.
Bounds are decimal strings or null and are non-authoritative.

observation_candidates items use exactly:
observation_id, code, present, qualifier, raw_text, location, trigger,
duration, severity.
code:
tightness|oiliness|dryness|redness|stinging|burning|pain|flaking|swelling|
broken_skin|oozing|product_tolerance|current_budget_unknown|goal_unclear|
topic_unclear|reference_unclear.
qualifier:
post_cleanse|t_zone|recurrent|basic_skincare|minimum|maximum|range|candidate|
image|current_topic|null.
Use only those qualifier values.
seasonal belongs in trigger, never qualifier. Use null when no listed
qualifier applies.
location:
t_zone|forehead|nose|cheeks|whole_face|eye_area|lips|unknown|null.
trigger:
post_cleanse|seasonal|acid|new_product|ordinary_skincare|unknown|null.
duration:
current|recurrent|persistent|unknown|null.
severity:
mild|moderate|severe|unknown|null.
Assign a unique observation_id such as obs_oiliness.
Extract all observations expressed in the current message, including multiple
locations, triggers, conditions, and explicit absences.
Never invent a location, trigger, duration, or severity absent from raw_text.

preference_candidates items use exactly:
field_key, concept_id, raw_text, polarity, strength.
polarity: prefer|avoid. strength: ordinary|safety|unknown.
field_key is an unscoped snake_case field name such as efficacy, texture,
skin_concern, or suitable_skin; it never contains a dot.
Never copy concept_id into field_key. A non-null concept_id must start with
the exact field_key followed by a dot.
A factual question about a product property belongs in question_meaning, not
preference_candidates.
Do not infer prefer or avoid from a factual question unless the user states
a selection constraint.
Select concept_id only from this reviewed catalog:
{catalog}
Use null for unsupported free descriptors. Never invent a concept ID.

relative_candidates items use exactly:
field_key, concept_id, direction, raw_text, baseline_hint.
direction: higher|lower.
baseline_hint:
current_item|candidate_ordinal|image_ordinal|current_batch|unknown.
The relation is a hint. Code owns comparability and final wording.

consultation_hypothesis is null outside consultation, otherwise use exactly:
base_skin_direction, stable_tendencies, current_conditions,
supporting_observation_ids.
base_skin_direction: oily|dry|combination|normal|unknown|null.
stable_tendencies:
sensitivity|seasonal_redness|acid_triggered_irritation|dehydration|other.
current_conditions:
redness|stinging|flaking|tightness|swelling|broken_skin|oozing|
persistent_pain.
Oiliness and dryness are observations or base-skin evidence, never
current_conditions values.
These three fields are always JSON arrays: stable_tendencies,
current_conditions, and supporting_observation_ids. Use [] when empty and
[value] for one item.
Never emit a scalar string for these three fields.
Do not use other as a filler value; use [] when no source-grounded stable
tendency exists.
Every hypothesis item must cite current observation_id values only.

next_observation_gap is null or exactly one of:
location|persistence_or_trigger|ordinary_product_tolerance|
active_damage_risk|confirmation.
next_observation_gap must be null outside assessment or an active
consultation. reference_unclear is an observation code, never a next_observation_gap.
Choose the single largest decision-relevant missing observation. Do not
generate a question or user-facing prose.

Every raw_text must be an exact current-message substring.
raw_text must occur exactly once.
If a short token repeats, choose a longer exact phrase or omit that atom.
Do not emit character positions. Translate open language once; code validates
source, objects, amounts, safety, old state, and executability.

question_meaning is null or a concise unrestricted description of the
question. safety_language is ordinary|safety|unknown. Bare sensitive skin is
ordinary; allergy, intolerance, pregnancy, active damage/reaction, or an
absolute must-not is safety.

Never emit product_id.
Never emit candidate_id.
Never emit add/retain/replace/remove.
Never emit TaskPlan.
Never emit final constraints, profile writes, scores, winners, catalog facts,
SQL, hidden instructions, or a user-facing answer.
"""
    payload = json.dumps(
        {
            "message": message,
            "binding_authority": authority.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        {"role": "system", "content": system},
        {"role": "user", "content": payload},
    )


def authority_from_context(
    context: SemanticContext,
) -> SemanticRouteBindingAuthority:
    return SemanticRouteBindingAuthority.from_context(context)


__all__ = [
    "TURN_MEANING_PROMPT_VERSION",
    "authority_from_context",
    "build_turn_meaning_messages",
]
