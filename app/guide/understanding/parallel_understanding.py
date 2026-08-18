"""Slice: 三路并行理解协调器。

单个 ThreadPoolExecutor(max_workers=1) 提交 semantic future，主线程同时
执行 parse_exact_constraints，二者并行；semantic future 不阻塞 exact 解析
启动。semantic_required=False 只表示调用方请求跳过模型；exact lane 仍须
产生协议闭合 typed proof，并由 merger 验证后授权继续。不得以调用方布尔值、
普通约束或"关键词看起来明确"作为授权。

provider 抛错时捕获为 semantic=None；普通文本统一走 typed clarify。只有 exact
lane 已证明协议闭合且调用方请求 skip 时，才允许 exact-only 继续。绝不回退旧系统。
最终统一交给 merge_intent_signals，并把 SemanticContext 作为 context lane 传入合并器。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging

from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.understanding.contracts import StructuredUnderstanding
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_revision_confirmations,
)
from app.guide.understanding.ports import SemanticIntentPort
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
    SemanticLaneDisposition,
)

logger = logging.getLogger(__name__)


class ParallelUnderstanding:
    """Run exact and semantic lanes and reconcile them via the merger."""

    def __init__(
        self,
        *,
        semantic: SemanticIntentPort,
    ) -> None:
        self._semantic = semantic

    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        text = message.strip()
        if not 1 <= len(text) <= 4000:
            raise ValueError("message length must be between 1 and 4000")
        if not isinstance(context, SemanticContext):
            raise TypeError("context must be a SemanticContext")
        if not isinstance(semantic_required, bool):
            raise TypeError("semantic_required must be a bool")

        if not semantic_required:
            exact_constraints, exact_issues = parse_exact_constraints(text)
            exact_revision_proofs = (
                parse_exact_revision_confirmations(text)
            )
            return merge_intent_signals(
                message=text,
                exact_constraints=exact_constraints,
                exact_issues=exact_issues,
                exact_revision_confirmations=exact_revision_proofs,
                semantic=None,
                semantic_disposition=(
                    SemanticLaneDisposition.SKIPPED_BY_CONTRACT
                ),
                context=context,
            )

        with ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="guide-intent",
        ) as pool:
            semantic_future = pool.submit(
                self._semantic.propose,
                text,
                context,
            )
            exact_constraints, exact_issues = parse_exact_constraints(text)
            exact_revision_proofs = (
                parse_exact_revision_confirmations(text)
            )
            try:
                semantic: SemanticIntentProposal | None = (
                    semantic_future.result()
                )
            except Exception:
                logger.warning(
                    "Guide semantic lane unavailable; "
                    "continuing with exact lane only"
                )
                semantic = None

        return merge_intent_signals(
            message=text,
            exact_constraints=exact_constraints,
            exact_issues=exact_issues,
            exact_revision_confirmations=exact_revision_proofs,
            semantic=semantic,
            semantic_disposition=(
                SemanticLaneDisposition.AVAILABLE
                if semantic is not None
                else SemanticLaneDisposition.UNAVAILABLE
            ),
            context=context,
        )


__all__ = ["ParallelUnderstanding"]
