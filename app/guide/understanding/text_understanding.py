"""Slice 1 文本理解层：把自然语言拆成结构化理解草稿。

原则：数字、品类、肤质、否定由代码精确抽取，进 exact_constraints；
模糊偏好进 semantic_proposals。不发明商品事实、不排序、不判 winner。
"""
from __future__ import annotations

from app.guide.understanding.contracts import (
    ReferenceDraft,
    StructuredUnderstanding,
    UnderstandingGoal,
)
from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.understanding.exact_parsing import parse_exact_constraints
from app.guide.understanding.exact_parsing import (
    parse_exact_revision_confirmations,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticLaneDisposition,
)


def understand_text(message: str) -> StructuredUnderstanding:
    text = message.strip()
    if not 1 <= len(text) <= 4000:
        raise ValueError("message length must be between 1 and 4000")
    exact_constraints, uncertainties = parse_exact_constraints(text)
    topic = next(
        (
            item.value
            for item in exact_constraints
            if item.kind == "category"
        ),
        None,
    )

    return StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        topic=topic,
        observations=[f"raw_message={text}"] if text else [],
        exact_constraints=exact_constraints,
        semantic_proposals=[],
        signal_trace=[],
        references=[
            item
            for item in exact_constraints
            if isinstance(item, ReferenceDraft)
        ],
        image_references=[],
        uncertainties=uncertainties,
        confidence=1.0 if exact_constraints and not uncertainties else 0.0,
    )


class ExactOnlyTextUnderstanding:
    """TextUnderstandingPort backed only by the exact parser.

    Used when no semantic provider is configured. Ordinary text fails closed.
    ``semantic_required=False`` still requires a typed closed-operation proof.
    """

    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding:
        if not isinstance(semantic_required, bool):
            raise TypeError("semantic_required must be a bool")
        text = message.strip()
        if not 1 <= len(text) <= 4000:
            raise ValueError("message length must be between 1 and 4000")
        exact_constraints, exact_issues = parse_exact_constraints(text)
        exact_revision_proofs = parse_exact_revision_confirmations(text)
        return merge_intent_signals(
            message=text,
            exact_constraints=exact_constraints,
            exact_issues=exact_issues,
            exact_revision_confirmations=exact_revision_proofs,
            semantic=None,
            semantic_disposition=(
                SemanticLaneDisposition.UNAVAILABLE
                if semantic_required
                else SemanticLaneDisposition.SKIPPED_BY_CONTRACT
            ),
            context=context,
        )


__all__ = ["understand_text", "ExactOnlyTextUnderstanding"]
