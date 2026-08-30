"""Score state-transition outcomes without weakening path assertions."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import sys
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.guide.feedback.contracts import (
    ConsultationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    KnowledgeSlotState,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import route_unified_turn
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.understanding.contracts import (
    ReferenceDraft,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnMeaning,
    TurnRecommendationModeBasis,
)
from tools.guide_gates.build_transition_matrix import CORE_STATES


_STATE_PROCESSORS = {
    "recommendation_batch": "recommendation",
    "single_product_focus": "product_knowledge",
    "comparison_batch": "comparison",
    "consultation": "consultation",
    "general_knowledge": "general_knowledge",
    "confirmed_image_product": "image_identity",
}
_PROCESSOR_STATES = {
    processor: state
    for state, processor in _STATE_PROCESSORS.items()
}
_BATCH_PRODUCT_IDS = (38, 91)
_IMAGE_PRODUCT = ConfirmedImageProductRef(
    image_ordinal=1,
    product_id=53,
)

@dataclass(frozen=True, slots=True)
class TransitionOutcome:
    processor_family: str
    product_ids: tuple[int, ...]
    image_ordinals: tuple[int, ...]
    card_type: str | None
    card_product_ids: tuple[int, ...]
    active_state: str | None
    safety_state: str | None
    expected_state_change: bool

    def __post_init__(self) -> None:
        if not self.processor_family.strip():
            raise ValueError("processor_family must be non-empty")
        if any(type(value) is not int or value < 1 for value in self.product_ids):
            raise ValueError("product_ids must contain positive integers")
        if any(
            type(value) is not int or value < 1
            for value in self.image_ordinals
        ):
            raise ValueError(
                "image_ordinals must contain positive integers"
            )
        if any(
            type(value) is not int or value < 1
            for value in self.card_product_ids
        ):
            raise ValueError(
                "card_product_ids must contain positive integers"
            )

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
    ) -> "TransitionOutcome":
        return cls(
            processor_family=str(payload["processor_family"]),
            product_ids=tuple(payload["product_ids"]),
            image_ordinals=tuple(payload["image_ordinals"]),
            card_type=payload.get("card_type"),
            card_product_ids=tuple(payload["card_product_ids"]),
            active_state=payload.get("active_state"),
            safety_state=payload.get("safety_state"),
            expected_state_change=bool(
                payload["expected_state_change"]
            ),
        )


def compare_outcomes(
    left: TransitionOutcome,
    right: TransitionOutcome,
) -> dict[str, object]:
    if type(left) is not TransitionOutcome or type(right) is not TransitionOutcome:
        raise TypeError("compare_outcomes requires exact TransitionOutcome values")
    differences = [
        field_name
        for field_name in (
            "processor_family",
            "product_ids",
            "image_ordinals",
            "card_type",
            "card_product_ids",
            "active_state",
            "safety_state",
            "expected_state_change",
        )
        if getattr(left, field_name) != getattr(right, field_name)
    ]
    return {
        "path_independent": not differences,
        "expected_state_change": (
            left.expected_state_change
            or right.expected_state_change
        ),
        "differences": differences,
    }


def score_outcomes(
    outcomes: list[dict[str, Any]],
) -> dict[str, object]:
    ordinary_path_pollution = 0
    expected_state_changes = 0
    serious_failures = 0
    reports: list[dict[str, object]] = []
    for row in outcomes:
        left = TransitionOutcome.from_mapping(row["left"])
        right = TransitionOutcome.from_mapping(row["right"])
        comparison = compare_outcomes(left, right)
        if comparison["expected_state_change"]:
            expected_state_changes += 1
        elif not comparison["path_independent"]:
            ordinary_path_pollution += 1
        if row.get("serious_failure") is True:
            serious_failures += 1
        reports.append(
            {
                "comparison_id": row.get("comparison_id"),
                **comparison,
            }
        )
    return {
        "comparison_count": len(outcomes),
        "ordinary_path_pollution": ordinary_path_pollution,
        "expected_state_changes": expected_state_changes,
        "serious_failures": serious_failures,
        "reports": reports,
        "passed": (
            ordinary_path_pollution == 0
            and serious_failures == 0
        ),
    }


def run_typed_router_matrix() -> dict[str, object]:
    """Execute all matrix routes against typed router inputs.

    This validates deterministic state/routing behavior only. It deliberately
    does not claim to validate natural-language translation by a provider.
    """
    edge_outcomes: dict[str, dict[str, object]] = {}
    triple_outcomes: dict[str, dict[str, object]] = {}
    ordinary_path_pollution = 0
    serious_failures = 0
    expected_state_changes = 0
    edge_baselines: dict[str, TransitionOutcome] = {}
    triple_baselines: dict[str, TransitionOutcome] = {}

    for source in CORE_STATES:
        for target in CORE_STATES:
            decision, image_ordinals = _execute_transition(
                snapshot=_snapshot_for_state(source),
                target=target,
            )
            outcome = _outcome_from_decision(
                decision=decision,
                image_ordinals=image_ordinals,
            )
            edge_id = f"{source}->{target}"
            edge_outcomes[edge_id] = _outcome_mapping(outcome)
            if _PROCESSOR_STATES.get(decision.processor) != target:
                serious_failures += 1
                continue
            baseline = edge_baselines.setdefault(target, outcome)
            comparison = compare_outcomes(baseline, outcome)
            if comparison["expected_state_change"]:
                expected_state_changes += 1
            elif not comparison["path_independent"]:
                ordinary_path_pollution += 1

    for first in CORE_STATES:
        for second in CORE_STATES:
            for third in CORE_STATES:
                first_snapshot = _snapshot_for_state(first)
                middle, _ = _execute_transition(
                    snapshot=first_snapshot,
                    target=second,
                )
                second_snapshot = _snapshot_from_decision(middle)
                final, image_ordinals = _execute_transition(
                    snapshot=second_snapshot,
                    target=third,
                )
                outcome = _outcome_from_decision(
                    decision=final,
                    image_ordinals=image_ordinals,
                )
                path_id = f"{first}->{second}->{third}"
                triple_outcomes[path_id] = _outcome_mapping(outcome)
                if (
                    _PROCESSOR_STATES.get(middle.processor) != second
                    or _PROCESSOR_STATES.get(final.processor) != third
                ):
                    serious_failures += 1
                    continue
                baseline = triple_baselines.setdefault(third, outcome)
                comparison = compare_outcomes(baseline, outcome)
                if comparison["expected_state_change"]:
                    expected_state_changes += 1
                elif not comparison["path_independent"]:
                    ordinary_path_pollution += 1

    return {
        "schema_version": "guide-typed-router-transition-matrix-v1",
        "pairwise_edges": len(edge_outcomes),
        "triple_paths": len(triple_outcomes),
        "ordinary_path_pollution": ordinary_path_pollution,
        "expected_state_changes": expected_state_changes,
        "serious_failures": serious_failures,
        "edge_outcomes": edge_outcomes,
        "triple_outcomes": triple_outcomes,
        "passed": (
            ordinary_path_pollution == 0
            and serious_failures == 0
        ),
    }


def _execute_transition(
    *,
    snapshot: ConversationSnapshot,
    target: str,
) -> tuple[object, tuple[int, ...]]:
    meaning, understanding, bindings, images = _target_request(target)
    task_plan = plan_task(
        understanding,
        resolved_product_ids=tuple(
            dict.fromkeys(
                (
                    *(binding.product_id for binding in bindings),
                    *(image.product_id for image in images),
                )
            )
        ),
    )
    decision = route_unified_turn(
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        product_bindings=bindings,
        current_image_products=images,
        task_plan=task_plan,
    )
    return (
        decision,
        tuple(item.image_ordinal for item in images),
    )


def _target_request(
    target: str,
) -> tuple[
    TurnMeaning,
    StructuredUnderstanding,
    tuple[ResolvedProductBinding, ...],
    tuple[ConfirmedImageProductRef, ...],
]:
    if target == "recommendation_batch":
        return (
            _meaning("recommendation", continuity="new_task"),
            _understanding(UnderstandingGoal.RECOMMENDATION),
            (),
            (),
        )
    if target == "single_product_focus":
        return (
            _meaning("knowledge", continuity="new_task"),
            _understanding(UnderstandingGoal.KNOWLEDGE),
            (_binding(38),),
            (),
        )
    if target == "comparison_batch":
        return (
            _meaning("suitability", continuity="return_to_focus"),
            _understanding(
                UnderstandingGoal.SUITABILITY,
                references=(_reference("current_batch"),),
            ),
            tuple(_binding(product_id) for product_id in _BATCH_PRODUCT_IDS),
            (),
        )
    if target == "consultation":
        return (
            _meaning("assessment"),
            _understanding(UnderstandingGoal.ASSESSMENT),
            (),
            (),
        )
    if target == "general_knowledge":
        return (
            _meaning("knowledge"),
            _understanding(UnderstandingGoal.KNOWLEDGE),
            (),
            (),
        )
    if target == "confirmed_image_product":
        return (
            _meaning("image_identity"),
            _understanding(UnderstandingGoal.IMAGE_IDENTITY),
            (_binding(_IMAGE_PRODUCT.product_id),),
            (_IMAGE_PRODUCT,),
        )
    raise ValueError(f"unsupported matrix state: {target}")


def _meaning(
    operation: str,
    *,
    continuity: str = "continue",
) -> TurnMeaning:
    recommendation_fields: dict[str, object] = {}
    if operation == "recommendation":
        recommendation_fields = {
            "recommendation_mode": "explore",
            "recommendation_mode_basis": TurnRecommendationModeBasis(
                basis="bounded_exploration",
                source_text="状态转换验证",
            ),
            "recommendation_count": 2,
        }
    return TurnMeaning.model_validate(
        {
            "operation_hint": operation,
            "topic_hint": "serum",
            "continuity_hint": continuity,
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "状态转换验证",
            "safety_language": "ordinary",
            **recommendation_fields,
        },
        strict=True,
    )


def _understanding(
    goal: UnderstandingGoal,
    *,
    references: tuple[ReferenceDraft, ...] = (),
) -> StructuredUnderstanding:
    recommendation_fields: dict[str, object] = {}
    if goal is UnderstandingGoal.RECOMMENDATION:
        recommendation_fields = {
            "recommendation_mode": "explore",
            "recommendation_mode_basis": "bounded_exploration",
            "recommendation_count": 2,
        }
    return StructuredUnderstanding(
        goal=goal,
        topic=TopicCode.SERUM,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        relative_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=list(references),
        product_mentions=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning="状态转换验证",
        **recommendation_fields,
    )


def _reference(kind: str) -> ReferenceDraft:
    return ReferenceDraft(
        kind=kind,
        source_span=SourceSpan(start=0, end=2),
    )


def _binding(product_id: int) -> ResolvedProductBinding:
    return ResolvedProductBinding(
        product_id=product_id,
        variant_scope=None,
        source_text=f"matrix_product:{product_id}",
        source_kind="explicit_product",
    )


def _snapshot_for_state(state: str) -> ConversationSnapshot:
    if state not in _STATE_PROCESSORS:
        raise ValueError(f"unsupported matrix state: {state}")
    batch = tuple(
        DisplayedCandidateRef(
            product_id=product_id,
            ordinal=index,
            skin_match="unknown",
            matched_efficacies=("修护",),
        )
        for index, product_id in enumerate(
            _BATCH_PRODUCT_IDS,
            start=1,
        )
    )
    recommendation_slot = RecommendationSlotState(
        query_context=RecommendationQueryContext(
            category="serum",
            recommendation_mode="explore",
            recommendation_mode_basis="bounded_exploration",
            recommendation_count=2,
            budget_minimum=None,
            budget_maximum=Decimal("300"),
            skin="oily_sensitive",
            efficacy="repair",
            exclusions=(),
        ),
        candidates=batch,
    )
    owner = Responsibility(_STATE_PROCESSORS[state])
    active_focus = {
        "recommendation_batch": ActiveFocus(
            slot="recommendation",
        ),
        "single_product_focus": ActiveFocus(
            slot="product",
            object_id=38,
        ),
        "comparison_batch": ActiveFocus(slot="product"),
        "consultation": ActiveFocus(slot="consultation"),
        "general_knowledge": ActiveFocus(slot="knowledge"),
        "confirmed_image_product": ActiveFocus(
            slot="image",
            object_id=_IMAGE_PRODUCT.product_id,
            ordinal=_IMAGE_PRODUCT.image_ordinal,
        ),
    }[state]
    return ConversationSnapshot(
        session_id="transition-matrix",
        version=1,
        active_owner=owner,
        active_focus=active_focus,
        recommendation_slot=recommendation_slot,
        product_slot=ProductSlotState(
            products=(
                batch
                if state == "comparison_batch"
                else batch[:1]
            ),
            focused_product_id=38,
        ),
        image_slot=(
            ImageSlotState(
                confirmed_products=(_IMAGE_PRODUCT,),
                focused_image_ordinal=1,
            )
            if state == "confirmed_image_product"
            else None
        ),
        consultation_slot=(
            ConsultationSlotState(state=ConsultationSubstate())
            if state == "consultation"
            else None
        ),
        knowledge_slot=(
            KnowledgeSlotState(question="精华")
            if state == "general_knowledge"
            else None
        ),
    )


def _snapshot_from_decision(
    decision: object,
) -> ConversationSnapshot:
    processor = getattr(decision, "processor")
    actual_state = _PROCESSOR_STATES.get(processor)
    if actual_state is None:
        raise ValueError(
            f"matrix route produced unsupported processor: {processor}"
        )
    return _snapshot_for_state(actual_state)


def _outcome_from_decision(
    *,
    decision: object,
    image_ordinals: tuple[int, ...],
) -> TransitionOutcome:
    bindings = tuple(getattr(decision, "product_bindings"))
    product_ids = tuple(item.product_id for item in bindings)
    processor = str(getattr(decision, "processor"))
    return TransitionOutcome(
        processor_family=processor,
        product_ids=product_ids,
        image_ordinals=image_ordinals,
        card_type=processor,
        card_product_ids=product_ids,
        active_state=_PROCESSOR_STATES.get(processor),
        safety_state=(
            "escalated"
            if processor == "safety_escalation"
            else None
        ),
        expected_state_change=False,
    )


def _outcome_mapping(outcome: TransitionOutcome) -> dict[str, object]:
    return {
        "processor_family": outcome.processor_family,
        "product_ids": list(outcome.product_ids),
        "image_ordinals": list(outcome.image_ordinals),
        "card_type": outcome.card_type,
        "card_product_ids": list(outcome.card_product_ids),
        "active_state": outcome.active_state,
        "safety_state": outcome.safety_state,
        "expected_state_change": outcome.expected_state_change,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path)
    parser.add_argument("--outcome-scoring", action="store_true")
    parser.add_argument("--execute-typed-router", action="store_true")
    args = parser.parse_args(argv)
    fixture_root = args.fixture_root
    manifest = json.loads(
        (fixture_root / "manifest.json").read_text(encoding="utf-8")
    )
    result: dict[str, object] = {
        "schema_version": "guide-transition-matrix-score-v1",
        "fixture_manifest": manifest,
    }
    if args.execute_typed_router:
        result["typed_router"] = run_typed_router_matrix()
        result["passed"] = result["typed_router"]["passed"]
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "score.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["passed"] is True else 3
    if args.outcome_scoring and args.outcomes is None:
        result.update({
            "scoring_status": "missing_outcomes",
            "passed": False,
        })
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "score.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False))
        return 3
    if args.outcomes is not None:
        result.update(
            score_outcomes(_load_jsonl(args.outcomes))
        )
    else:
        result.update({
            "scoring_status": "coverage_only",
            "passed": False,
        })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "score.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("passed") is True else 3


__all__ = [
    "TransitionOutcome",
    "compare_outcomes",
    "score_outcomes",
]


if __name__ == "__main__":
    raise SystemExit(main())
