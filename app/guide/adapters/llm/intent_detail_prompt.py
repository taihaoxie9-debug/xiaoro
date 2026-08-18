from __future__ import annotations

import json

from app.guide.adapters.llm.contracts import (
    SemanticSchemaDiagnosticKind,
    SemanticSchemaDiagnosticPath,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.semantic_route_contracts import (
    SemanticDetailStage,
    SemanticRouteProposal,
)


DETAIL_PROMPT_VERSION = "guide-semantic-detail-prompt-v10"

_COMMON = (
    "Return JSON only and use exactly the stage keys below. "
    "Interpret intent; do not answer the user. "
    "Typed context is authoritative for current objects. "
    "Never emit product_id, candidate_id, catalog claims, final price "
    "conclusions, catalog data, score, winner, SQL, profile writes, or a "
    "user-facing answer. Normalized budget strings are allowed only in the "
    "number candidate field when that field belongs to the stage.\n"
    "Translate only current-message meaning. Do not decide whether stored "
    "state is added, retained, replaced, or removed; code owns transitions.\n"
)
_CONCERNS = (
    "concerns values: skin|sensitivity|efficacy|texture|sun_protection|"
    "water_resistance|shade|finish|coverage|longevity|cleansing|fragrance|"
    "sillage|price|budget.\n"
)
_OBSERVATIONS = (
    "observations items use exactly code,present,qualifier. "
    "code: tightness|oiliness|redness|stinging|flaking|"
    "current_budget_unknown|goal_unclear|topic_unclear|reference_unclear. "
    "qualifier: post_cleanse|t_zone|recurrent|basic_skincare|minimum|"
    "maximum|range|candidate|image|current_topic|null.\n"
)
_REFERENCES = (
    "references items use exactly kind,ordinal,raw_text,start,end. "
    "kind: candidate_ordinal|image_ordinal|current_item|current_batch|"
    "current_topic|previous_constraint. Ordinal is 1..4 only for ordinal "
    "kinds and null otherwise. raw_text and offsets must bind the exact "
    "current-message referring expression. Do not invent a reference absent "
    "from text or typed context.\n"
)
_REFERENCE_SUFFICIENCY = (
    "Execution sufficiency is decided by code after schema validation. "
    "Do not invent a reference to satisfy the schema; use an empty references "
    "list when no referring expression is source-bound in the current "
    "message.\n"
)
_PRODUCT_MENTIONS = (
    "product_mentions items use exactly text,start,end. text must be an exact "
    "current-message substring and offsets must bind it. Nominate at most four "
    "full identities or controlled aliases in source order. Never emit a "
    "product_id or candidate_id; code alone resolves the Canonical ID.\n"
)
_NUMBER_CANDIDATES = (
    "number_candidates items use exactly kind,relation,raw_text,start,end,"
    "minimum,maximum. kind is budget. relation is maximum|minimum|range|"
    "approximate. raw_text and offsets must bind current-message text. Bounds "
    "are decimal strings or null and are non-authoritative; code revalidates "
    "Decimal, direction, range and conflicts. Ambiguous colloquial budget "
    "wording may leave number_candidates empty because exact code will request "
    "a typed BUDGET confirmation.\n"
)
_PREFERENCE_CANDIDATES = (
    "preference_candidates items use exactly field,raw_text,start,end,strength. "
    "field: texture|fragrance_description|finish|brand|efficacy|"
    "suitable_skin|skin_concern|usage_context|ingredient_presence|"
    "ingredient_exclusion. "
    "strength is preference|safety|unknown. preference means a soft want or "
    "lean; safety means allergy, intolerance, or an absolute must-not; unknown "
    "means a bare exclusion whose tone is not explicit. raw_text and offsets "
    "must bind current-message text. Nominate the concrete value only; never "
    "emit a product fact or field outside this enum. A bare sensitive-skin "
    "identity is an ordinary preference. An ordinary post-procedure preference "
    "is not safety-sensitive unless active damage, an adverse reaction, or an "
    "absolute safety requirement is stated. For ingredient_presence, code must "
    "confirm absolute ingredient inclusion from the current text; the model "
    "cannot promote a preference into a hard requirement. Unknown soft fields "
    "are omitted.\n"
)
_QUESTION_TRANSLATION = (
    "question_meaning is null or a concise unrestricted description of what "
    "the user wants to know; it is not an enum, answer, product fact, ID, or "
    "catalog claim. safety_sensitive is true for allergy, intolerance, "
    "pregnancy, active adverse reaction, active skin damage, or an absolute "
    "safety requirement; unknown severity is safety-sensitive. Bare sensitive "
    "skin and ordinary post-procedure requests are false.\n"
)
_SAFETY_CONCERN_BOUNDARY = (
    "safety_sensitive is a separate "
    "boolean and MUST NOT appear in concerns; use sensitivity or leave "
    "concerns empty.\n"
)

_PROMPT_BY_STAGE = {
    SemanticDetailStage.RECOMMENDATION: (
        _COMMON
        + "Use exactly keys: concerns, observations, product_mentions, "
        "number_candidates, preference_candidates, question_meaning, "
        "safety_sensitive.\n"
        + '{"concerns":[],"observations":[],'
        '"product_mentions":[],"number_candidates":[],'
        '"preference_candidates":[],"question_meaning":null,'
        '"safety_sensitive":false}\n'
        + _CONCERNS
        + _OBSERVATIONS
        + _PRODUCT_MENTIONS
        + _NUMBER_CANDIDATES
        + _PREFERENCE_CANDIDATES
        + _QUESTION_TRANSLATION
        + _SAFETY_CONCERN_BOUNDARY
    ),
    SemanticDetailStage.ASSESSMENT: (
        _COMMON
        + "Use exactly keys: concerns, observations, product_mentions, "
        "question_meaning, safety_sensitive.\n"
        + '{"concerns":[],"observations":[],"product_mentions":[],'
        '"question_meaning":null,"safety_sensitive":false}\n'
        + _CONCERNS
        + _OBSERVATIONS
        + _PRODUCT_MENTIONS
        + _QUESTION_TRANSLATION
        + _SAFETY_CONCERN_BOUNDARY
    ),
    SemanticDetailStage.COMPARISON: (
        _COMMON
        + "Use exactly keys: references, product_mentions, question_meaning, "
        "safety_sensitive.\n"
        + '{"references":[],"product_mentions":[],"question_meaning":null,'
        '"safety_sensitive":false}\n'
        + _REFERENCES
        + _REFERENCE_SUFFICIENCY
        + _PRODUCT_MENTIONS
        + _QUESTION_TRANSLATION
    ),
    SemanticDetailStage.FOLLOWUP: (
        _COMMON
        + "Use exactly keys: references, product_mentions, "
        "number_candidates, preference_candidates, question_meaning, "
        "safety_sensitive.\n"
        + '{"references":[],"product_mentions":[],'
        '"number_candidates":[],"preference_candidates":[],'
        '"question_meaning":null,"safety_sensitive":false}\n'
        + _REFERENCES
        + _REFERENCE_SUFFICIENCY
        + _PRODUCT_MENTIONS
        + _NUMBER_CANDIDATES
        + _PREFERENCE_CANDIDATES
        + _QUESTION_TRANSLATION
    ),
    SemanticDetailStage.KNOWLEDGE: (
        _COMMON
        + "Use exactly keys: concerns, product_mentions, question_meaning, "
        "safety_sensitive.\n"
        + '{"concerns":[],"product_mentions":[],"question_meaning":null,'
        '"safety_sensitive":false}\n'
        + _CONCERNS
        + _PRODUCT_MENTIONS
        + _QUESTION_TRANSLATION
        + _SAFETY_CONCERN_BOUNDARY
    ),
    SemanticDetailStage.IMAGE: (
        _COMMON
        + "Use exactly keys: references, observations, question_meaning, "
        "safety_sensitive. "
        + "At least one reference item is required.\n"
        + (
            '{"references":[{"kind":"image_ordinal","ordinal":1,'
            '"raw_text":"第一张","start":0,"end":3}],'
            '"observations":[],"question_meaning":null,'
            '"safety_sensitive":false}\n'
        )
        + _REFERENCES
        + _OBSERVATIONS
        + _QUESTION_TRANSLATION
    ),
}


def build_detail_messages(
    message: str,
    context: SemanticContext,
    route: SemanticRouteProposal,
    *,
    format_repair: bool = False,
    repair_kind: SemanticSchemaDiagnosticKind | None = None,
    repair_path: SemanticSchemaDiagnosticPath | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    if (
        not isinstance(message, str)
        or not message.strip()
        or len(message) > 4000
    ):
        raise ValueError("message must contain 1 to 4000 characters")
    if not isinstance(context, SemanticContext):
        raise TypeError("context must be a SemanticContext")
    if not isinstance(route, SemanticRouteProposal):
        raise TypeError("route must be a SemanticRouteProposal")
    if format_repair != (
        isinstance(repair_kind, SemanticSchemaDiagnosticKind)
        and isinstance(repair_path, SemanticSchemaDiagnosticPath)
    ):
        raise ValueError(
            "format repair and repair diagnostic must be supplied together"
        )
    try:
        system_prompt = _PROMPT_BY_STAGE[route.detail_stage]
    except KeyError:
        raise ValueError("detail stage does not have details") from None
    user_payload = json.dumps(
        {
            "message": message,
            "context": context.model_dump(mode="json"),
            "route": route.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        {
            "role": "system",
            "content": (
                system_prompt
                + (
                    "\nFormat repair: return a fresh strict JSON object. "
                    f"failure kind={repair_kind.value}; "
                    f"path={repair_path.value}."
                    if format_repair
                    and repair_kind is not None
                    and repair_path is not None
                    else ""
                )
            ),
        },
        {"role": "user", "content": user_payload},
    )


__all__ = [
    "DETAIL_PROMPT_VERSION",
    "build_detail_messages",
]
