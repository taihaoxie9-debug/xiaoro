from __future__ import annotations

import importlib
from pathlib import Path
from textwrap import dedent
from types import ModuleType

import pytest


CHECKER_MODULE = "tools.guide_gates.check_single_path_architecture"
FLOW_MODULE = "app.guide.application.flow"
FLOW_OWNER = f"{FLOW_MODULE}:run_turn"
PROCESSOR_MODULE = "app.guide.application.processors"
STREAM_ROOT = "app.guide_runtime.app:chat_stream"
MESSAGE_ROOT = "app.guide_runtime.app:chat_message"

CANONICAL_CALLS = {
    "compiler": ("compile_turn_meaning", FLOW_OWNER),
    "router": ("route_unified_turn", FLOW_OWNER),
    "reducer": ("reduce_conversation_state", FLOW_OWNER),
    "cas": ("compare_and_swap", FLOW_OWNER),
    "encoder": ("encode_sse_envelope", FLOW_OWNER),
}

FLOW_SOURCE = """
from app.guide.application.processors import (
    ProcessorExecutionInput,
    processor_registry,
)
from app.guide.application.reducer import reduce_conversation_state
from app.guide.application.wire import encode_sse_envelope
from app.guide.intent.compiler import compile_turn_meaning
from app.guide.intent.router import route_unified_turn


def run_turn(request, state_store):
    current = state_store.load(request.session_id)
    compiled = compile_turn_meaning(request.turn_meaning)
    decision = route_unified_turn(compiled)
    execution_input = ProcessorExecutionInput(
        turn_identity=request.turn_identity,
        understanding=compiled,
        decision=decision,
        current_snapshot=current,
        routing_evidence=request.routing_evidence,
    )
    result = processor_registry[decision.processor].execute(execution_input)
    snapshot = reduce_conversation_state(
        current=current,
        decision=decision,
        delta=result.state_delta,
    )
    envelope = encode_sse_envelope(result, snapshot)
    state_store.compare_and_swap(
        request.session_id,
        request.version,
        snapshot,
    )
    return envelope
"""

PROCESSOR_SOURCE = """
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessorExecutionInput:
    turn_identity: object
    understanding: object
    decision: object
    current_snapshot: object
    routing_evidence: object


class RecommendationProcessor:
    def execute(self, execution_input):
        return execution_input


class SafetyProcessor:
    def execute(self, execution_input):
        return execution_input


def build_execution_input(**values):
    return ProcessorExecutionInput(**values)


processor_registry = {
    "recommendation": RecommendationProcessor(),
    "safety": SafetyProcessor(),
}
"""

SNAPSHOT_SOURCE = """
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


ProductId = int
EvidenceId = str
ConsultationSubstate = str
ClarificationProgress = str
PendingTurn = str


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProfileOwnerRef(_StrictFrozen):
    value: str


class SessionProfile(_StrictFrozen):
    value: str


class RecommendationQueryContext(_StrictFrozen):
    value: str


class DisplayedCandidateRef(_StrictFrozen):
    product_id: ProductId


class ConfirmedImageProductRef(_StrictFrozen):
    product_id: ProductId


class RecommendationSlotState(_StrictFrozen):
    kind: Literal["recommendation"] = "recommendation"
    query_context: RecommendationQueryContext
    candidates: tuple[DisplayedCandidateRef, ...]
    empty_result: bool
    focused_candidate_ordinal: int | None


class ProductSlotState(_StrictFrozen):
    kind: Literal["product"] = "product"
    products: tuple[DisplayedCandidateRef, ...]
    focused_product_id: ProductId | None
    focused_evidence_ids: tuple[EvidenceId, ...]


class ImageSlotState(_StrictFrozen):
    kind: Literal["image"] = "image"
    confirmed_products: tuple[ConfirmedImageProductRef, ...]
    focused_image_ordinal: int | None


class ConsultationSlotState(_StrictFrozen):
    kind: Literal["consultation"] = "consultation"
    state: ConsultationSubstate


class KnowledgeSlotState(_StrictFrozen):
    kind: Literal["knowledge"] = "knowledge"
    question: str
    evidence_ids: tuple[EvidenceId, ...]


class PendingClarificationSlot(_StrictFrozen):
    kind: Literal["clarification"] = "clarification"
    value: ClarificationProgress


class PendingReplySlot(_StrictFrozen):
    kind: Literal["pending_reply"] = "pending_reply"
    value: PendingTurn


ReplySlotState = Annotated[
    PendingClarificationSlot | PendingReplySlot,
    Field(discriminator="kind"),
]


class ActiveFocus(_StrictFrozen):
    slot: Literal[
        "recommendation",
        "product",
        "image",
        "consultation",
        "knowledge",
        "reply",
    ]
    object_id: ProductId | EvidenceId | None
    ordinal: int | None


class ConversationSnapshot(_StrictFrozen):
    session_id: str
    version: int
    profile_owner: ProfileOwnerRef
    session_profile: SessionProfile
    active_owner: str
    active_focus: ActiveFocus | None
    recommendation_slot: RecommendationSlotState | None
    product_slot: ProductSlotState | None
    image_slot: ImageSlotState | None
    consultation_slot: ConsultationSlotState | None
    knowledge_slot: KnowledgeSlotState | None
    reply_slot: ReplySlotState | None
"""


def _checker() -> ModuleType:
    try:
        return importlib.import_module(CHECKER_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name == CHECKER_MODULE:
            pytest.fail(
                "Task11 r5 checker is not implemented: "
                f"{CHECKER_MODULE}",
                pytrace=False,
            )
        raise


def _write_source(root: Path, relative_path: str, source: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(source).lstrip(), encoding="utf-8")
    return path


def _replace_source(
    root: Path,
    relative_path: str,
    old: str,
    new: str,
) -> None:
    path = root / relative_path
    source = path.read_text(encoding="utf-8")
    assert old in source, f"synthetic fixture marker missing: {old!r}"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _legal_repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _write_source(
        root,
        "app/guide_runtime/app.py",
        """
        from fastapi import FastAPI

        from app.guide.application.flow import run_turn
        from app.guide_runtime.contracts import ChatStreamRequest

        app = FastAPI()


        @app.post("/api/v1/chat/stream")
        async def chat_stream(request: ChatStreamRequest):
            return run_turn(request)
        """,
    )
    _write_source(
        root,
        "app/guide_runtime/contracts.py",
        """
        from pydantic import BaseModel, ConfigDict


        class ChatStreamRequest(BaseModel):
            model_config = ConfigDict(extra="forbid")

            session_id: str
            message: str
            request_id: str
            conversation_version: int
            image_bundle_id: str | None = None
        """,
    )
    _write_source(
        root,
        "app/guide/application/flow.py",
        FLOW_SOURCE,
    )
    _write_source(
        root,
        "app/guide/application/processors.py",
        PROCESSOR_SOURCE,
    )
    _write_source(
        root,
        "app/guide/application/reducer.py",
        """
        def reduce_conversation_state(*, current, decision, delta):
            return (current, decision, delta)
        """,
    )
    _write_source(
        root,
        "app/guide/intent/compiler.py",
        """
        def compile_turn_meaning(meaning):
            return meaning
        """,
    )
    _write_source(
        root,
        "app/guide/intent/router.py",
        """
        def route_unified_turn(understanding):
            return understanding
        """,
    )
    _write_source(
        root,
        "app/guide/application/wire.py",
        """
        def encode_sse_envelope(result, snapshot):
            return b"data: terminal\\n\\n"
        """,
    )
    _write_source(
        root,
        "app/guide/adapters/http.py",
        """
        def forward_sse_frames(frames):
            yield from frames
        """,
    )
    _write_source(
        root,
        "app/guide/feedback/contracts.py",
        SNAPSHOT_SOURCE,
    )
    return root


def _manifest(
    checker: ModuleType,
    *,
    production_roots: tuple[str, ...] = (STREAM_ROOT,),
):
    return checker.ArchitectureManifest(
        production_roots=production_roots,
        canonical_calls=CANONICAL_CALLS,
        processor_roots=(
            f"{PROCESSOR_MODULE}:RecommendationProcessor.execute",
            f"{PROCESSOR_MODULE}:SafetyProcessor.execute",
        ),
        post_router_roots=(
            f"{PROCESSOR_MODULE}:RecommendationProcessor.execute",
            f"{PROCESSOR_MODULE}:SafetyProcessor.execute",
        ),
        adapter_packages=("app.guide.adapters",),
        snapshot_contract=(
            "app.guide.feedback.contracts:ConversationSnapshot"
        ),
        request_contract="app.guide_runtime.contracts:ChatStreamRequest",
    )


def _check(
    root: Path,
    *,
    production_roots: tuple[str, ...] = (STREAM_ROOT,),
):
    checker = _checker()
    return checker.check_single_path_architecture(
        root,
        manifest=_manifest(
            checker,
            production_roots=production_roots,
        ),
    )


def _assert_violation(
    report,
    rule: str,
    *,
    detail: str | None = None,
) -> None:
    assert report.passed is False
    matches = tuple(
        violation
        for violation in report.violations
        if violation.rule == rule
    )
    assert matches, (
        f"missing {rule}; observed "
        f"{[violation.rule for violation in report.violations]}"
    )
    assert all(violation.file for violation in matches)
    assert all(violation.line >= 1 for violation in matches)
    assert all(violation.detail for violation in matches)
    if detail is not None:
        assert any(detail in violation.detail for violation in matches)


def test_valid_single_path_architecture_passes(tmp_path: Path) -> None:
    root = _legal_repository(tmp_path)

    report = _check(root)

    assert report.passed is True
    assert report.violations == ()
    assert {
        "app.guide_runtime.app",
        FLOW_MODULE,
        PROCESSOR_MODULE,
        "app.guide.feedback.contracts",
    } <= set(report.inspected_modules)


def test_default_manifest_scopes_only_public_transport_adapters() -> None:
    checker = _checker()

    assert checker.default_manifest().adapter_packages == (
        "app.guide.application.chat_api_adapter",
        "app.guide_runtime.sse",
    )


def test_discovered_fastapi_route_omitted_from_manifest_fails(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)

    report = _check(root, production_roots=())

    _assert_violation(
        report,
        "UNLISTED_PRODUCTION_ROOT",
        detail=STREAM_ROOT,
    )


def test_second_chat_message_route_fails_even_when_manifested(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide_runtime/app.py",
        '@app.post("/api/v1/chat/stream")',
        """
@app.post("/api/v1/chat/message")
async def chat_message(request: ChatStreamRequest):
    return run_turn(request)


@app.post("/api/v1/chat/stream")
""".strip(),
    )

    report = _check(
        root,
        production_roots=(STREAM_ROOT, MESSAGE_ROOT),
    )

    _assert_violation(
        report,
        "MULTIPLE_CHAT_ROUTES",
        detail="/api/v1/chat/message",
    )


@pytest.mark.parametrize(
    ("boundary", "old", "missing", "duplicate"),
    (
        (
            "compiler",
            "    compiled = compile_turn_meaning(request.turn_meaning)\n",
            "    compiled = request.turn_meaning\n",
            (
                "    compiled = compile_turn_meaning(request.turn_meaning)\n"
                "    compiled = compile_turn_meaning(compiled)\n"
            ),
        ),
        (
            "router",
            "    decision = route_unified_turn(compiled)\n",
            "    decision = request.decision\n",
            (
                "    decision = route_unified_turn(compiled)\n"
                "    decision = route_unified_turn(compiled)\n"
            ),
        ),
        (
            "reducer",
            "    snapshot = reduce_conversation_state(\n"
            "        current=current,\n"
            "        decision=decision,\n"
            "        delta=result.state_delta,\n"
            "    )\n",
            "    snapshot = current\n",
            (
                "    snapshot = reduce_conversation_state(\n"
                "        current=current,\n"
                "        decision=decision,\n"
                "        delta=result.state_delta,\n"
                "    )\n"
                "    snapshot = reduce_conversation_state(\n"
                "        current=snapshot,\n"
                "        decision=decision,\n"
                "        delta=result.state_delta,\n"
                "    )\n"
            ),
        ),
        (
            "cas",
            "    state_store.compare_and_swap(\n"
            "        request.session_id,\n"
            "        request.version,\n"
            "        snapshot,\n"
            "    )\n",
            "    saved = True\n",
            (
                "    state_store.compare_and_swap(\n"
                "        request.session_id,\n"
                "        request.version,\n"
                "        snapshot,\n"
                "    )\n"
                "    state_store.compare_and_swap(\n"
                "        request.session_id,\n"
                "        request.version + 1,\n"
                "        snapshot,\n"
                "    )\n"
            ),
        ),
        (
            "encoder",
            "    envelope = encode_sse_envelope(result, snapshot)\n",
            "    envelope = result\n",
            (
                "    envelope = encode_sse_envelope(result, snapshot)\n"
                "    envelope = encode_sse_envelope(result, snapshot)\n"
            ),
        ),
    ),
)
@pytest.mark.parametrize("cardinality", (0, 2))
def test_canonical_call_site_cardinality_is_exactly_one(
    tmp_path: Path,
    boundary: str,
    old: str,
    missing: str,
    duplicate: str,
    cardinality: int,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        old,
        missing if cardinality == 0 else duplicate,
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail=boundary,
    )


def test_canonical_call_outside_named_owner_fails(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide/application/compiler_bridge.py",
        """
        from app.guide.intent.compiler import compile_turn_meaning


        def compile_again(meaning):
            return compile_turn_meaning(meaning)
        """,
    )

    report = _check(root)

    _assert_violation(
        report,
        "NONCANONICAL_OWNER_CALLSITE",
        detail="compiler",
    )


def test_processor_cannot_delegate_directly_to_another_processor(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        (
            "class RecommendationProcessor:\n"
            "    def execute(self, execution_input):\n"
            "        return execution_input\n"
        ),
        (
            "class RecommendationProcessor:\n"
            "    def execute(self, execution_input):\n"
            "        return SafetyProcessor().execute(execution_input)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_TO_PROCESSOR_REACHABILITY",
        detail="SafetyProcessor",
    )


def test_processor_cannot_reach_delegation_through_helper_factory(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        """
def build_safety_processor():
    return SafetyProcessor()


def delegate_to_safety(execution_input):
    return build_safety_processor().execute(execution_input)


class RecommendationProcessor:
""".lstrip(),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        (
            "class RecommendationProcessor:\n"
            "    def execute(self, execution_input):\n"
            "        return execution_input\n"
        ),
        (
            "class RecommendationProcessor:\n"
            "    def execute(self, execution_input):\n"
            "        return delegate_to_safety(execution_input)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_TO_PROCESSOR_REACHABILITY",
        detail="build_safety_processor",
    )


def test_source_dependent_processor_registry_replacement_fails(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "    result = processor_registry["
            "decision.processor].execute(execution_input)\n"
        ),
        (
            "    selected_registry = {\n"
            "        **runtime.processor_registry,\n"
            '        "comparison": image_processor,\n'
            "    }\n"
            "    result = selected_registry["
            "decision.processor].execute(execution_input)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "SOURCE_DEPENDENT_PROCESSOR_REGISTRY",
        detail="selected_registry",
    )


def test_source_dependent_processor_registry_update_fails(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "    result = processor_registry["
            "decision.processor].execute(execution_input)\n"
        ),
        (
            "    selected_registry = processor_registry.copy()\n"
            "    selected_registry.update(\n"
            '        {"comparison": image_processor}\n'
            "    )\n"
            "    result = selected_registry["
            "decision.processor].execute(execution_input)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "SOURCE_DEPENDENT_PROCESSOR_REGISTRY",
        detail="selected_registry",
    )


def test_request_path_cannot_resolve_processor_from_runtime(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide_runtime/app.py",
        "return run_turn(request)",
        (
            "image_processor = image_runtime.get_orchestrator()\n"
            "    return run_turn(request, image_processor)"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "SOURCE_DEPENDENT_PROCESSOR_REGISTRY",
        detail="get_orchestrator",
    )


@pytest.mark.parametrize(
    "symbol",
    (
        "ChatOwner",
        "classify_chat_owner",
        "collect_guide_chat_response",
    ),
)
def test_legacy_public_collector_capability_fails(
    tmp_path: Path,
    symbol: str,
) -> None:
    root = _legal_repository(tmp_path)
    source = (
        f"class {symbol}:\n    pass\n"
        if symbol == "ChatOwner"
        else f"def {symbol}():\n    return {{}}\n"
    )
    _write_source(
        root,
        "app/guide/application/public_event_envelope.py",
        source,
    )

    report = _check(root)

    _assert_violation(
        report,
        "LEGACY_PUBLIC_COLLECTOR",
        detail=symbol,
    )


def test_legacy_guide_orchestrator_protocol_fails(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide/application/orchestrator.py",
        "class GuideOrchestrator:\n    pass\n",
    )

    report = _check(root)

    _assert_violation(
        report,
        "LEGACY_PUBLIC_COLLECTOR",
        detail="GuideOrchestrator",
    )


@pytest.mark.parametrize(
    "relative_path",
    (
        "app/guide/understanding/parallel_understanding.py",
        "app/guide/understanding/semantic_detail_contracts.py",
        "app/guide/understanding/two_stage_semantic.py",
        "app/guide/adapters/llm/deepseek_two_stage_intent.py",
        "app/guide/adapters/llm/intent_detail_prompt.py",
        "app/guide/adapters/llm/intent_route_prompt.py",
        "app/guide/adapters/llm/siliconflow_two_stage_intent.py",
        "app/guide/intent/budget_revision_planning.py",
        "app/guide/intent/consultation_planning.py",
        "app/guide/intent/skin_revision_planning.py",
        "tools/guide_gates/two_stage_intent_gate.py",
    ),
)
def test_forbidden_legacy_production_module_fails(
    tmp_path: Path,
    relative_path: str,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(root, relative_path, "VALUE = 'legacy'\n")

    report = _check(root)

    _assert_violation(
        report,
        "FORBIDDEN_LEGACY_MODULE",
        detail=relative_path,
    )


@pytest.mark.parametrize(
    "symbol",
    (
        "bind_execution_profile_owner",
        "from_user_turn",
        "understand_text",
    ),
)
def test_dormant_compatibility_capability_fails(
    tmp_path: Path,
    symbol: str,
) -> None:
    root = _legal_repository(tmp_path)
    source = (
        "@classmethod\n"
        f"def {symbol}(cls, turn):\n"
        "    return cls(turn)\n"
        if symbol == "from_user_turn"
        else f"def {symbol}(result, owner):\n    return result\n"
    )
    _write_source(
        root,
        "app/guide/application/compatibility.py",
        source,
    )

    report = _check(root)

    _assert_violation(
        report,
        "DORMANT_COMPATIBILITY_CAPABILITY",
        detail=symbol,
    )


def test_processor_result_cannot_be_post_wrapped(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        (
            "class RecommendationProcessor:\n"
            "    def execute(self, execution_input):\n"
            "        return execution_input\n"
        ),
        (
            "class RecommendationProcessor:\n"
            "    def execute(self, execution_input):\n"
            "        result = self._execute_core(execution_input)\n"
            "        result = bind_profile_owner(result)\n"
            "        return result\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_EXECUTION_RESULT_REWRITE",
        detail="bind_profile_owner",
    )


def test_session_version_derived_turn_identity_fails(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "    current = state_store.load(request.session_id)\n",
        (
            "    current = state_store.load(request.session_id)\n"
            "    turn_id = (\n"
            '        f"{request.session_id}:turn:{request.version + 1}"\n'
            "    )\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "SYNTHETIC_TURN_IDENTITY",
        detail="turn_id",
    )


def test_production_module_cannot_import_test_migration_seam(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "from app.guide.application.processors import (\n",
        (
            "from tests.guide.semantic_test_port import FrozenMeaning\n"
            "from app.guide.application.processors import (\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PRODUCTION_TEST_SEAM_IMPORT",
        detail="tests.guide.semantic_test_port",
    )


def test_processor_execution_input_rejects_raw_request_carrier(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "    routing_evidence: object\n",
        "    routing_evidence: object\n    user_turn: object\n",
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_EXECUTION_INPUT_SCHEMA",
        detail="user_turn",
    )


def test_selected_processor_call_requires_one_execution_input(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "    result = processor_registry["
            "decision.processor].execute(execution_input)\n"
        ),
        (
            "    result = processor_registry["
            "decision.processor].execute(\n"
            "        request,\n"
            "        decision=decision,\n"
            "    )\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_CALL_SIGNATURE",
        detail="run_turn",
    )


def test_processor_execute_accepts_only_execution_input(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "    def execute(self, execution_input):\n",
        "    def execute(self, execution_input, *, decision):\n",
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_EXECUTE_SIGNATURE",
        detail="RecommendationProcessor.execute",
    )


@pytest.mark.parametrize(
    ("parameter", "annotation"),
    (
        ("processor", "SafetyProcessor"),
        ("execution_callback", "object"),
    ),
)
def test_processor_constructor_rejects_processor_or_result_callable(
    tmp_path: Path,
    parameter: str,
    annotation: str,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        (
            "class RecommendationProcessor:\n"
            f"    def __init__(self, {parameter}: {annotation}):\n"
            f"        self._{parameter} = {parameter}\n\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_DEPENDENCY",
        detail=parameter,
    )


def test_processor_module_cannot_import_state_store(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "from dataclasses import dataclass\n",
        (
            "from dataclasses import dataclass\n"
            "from app.guide.feedback.ports import ConversationStatePort\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_STATE_STORE_IMPORT",
        detail="ConversationStatePort",
    )


def test_post_router_graph_cannot_access_raw_request_text(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        """
def build_retrieval_query(execution_input):
    return execution_input.user_turn.message


class RecommendationProcessor:
""".lstrip(),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "        return execution_input\n",
        "        return build_retrieval_query(execution_input)\n",
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_ROUTER_RAW_TEXT_ACCESS",
        detail="message",
    )


def test_post_router_typed_result_message_is_not_raw_request(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "        return execution_input\n",
        "        return execution_input.result.message\n",
    )

    report = _check(root)

    assert report.passed is True


def test_post_router_graph_cannot_call_semantic_parser(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "from dataclasses import dataclass\n",
        (
            "from dataclasses import dataclass\n\n"
            "from app.guide.understanding.scenario_parsing "
            "import parse_scenarios\n"
        ),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        """
def rebuild_scenarios(execution_input):
    return parse_scenarios(execution_input.understanding.opaque_query)


class RecommendationProcessor:
""".lstrip(),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "        return execution_input\n",
        "        return rebuild_scenarios(execution_input)\n",
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_ROUTER_SEMANTIC_PARSER",
        detail="parse_scenarios",
    )


@pytest.mark.parametrize(
    "business_import",
    (
        "from app.guide.intent.router import route_unified_turn",
        (
            "from app.guide.application.reducer "
            "import reduce_conversation_state"
        ),
        (
            "from app.guide.intent.responsibility_matrix "
            "import decision_for_responsibility"
        ),
    ),
)
def test_adapter_cannot_import_business_routing_or_state_constructor(
    tmp_path: Path,
    business_import: str,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/adapters/http.py",
        "def forward_sse_frames",
        f"{business_import}\n\n\ndef forward_sse_frames",
    )

    report = _check(root)

    _assert_violation(
        report,
        "ADAPTER_BUSINESS_PROJECTION",
        detail=business_import.split(" import ")[-1],
    )


def test_sse_encoding_after_cas_fails(tmp_path: Path) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "    envelope = encode_sse_envelope(result, snapshot)\n"
            "    state_store.compare_and_swap(\n"
            "        request.session_id,\n"
            "        request.version,\n"
            "        snapshot,\n"
            "    )\n"
        ),
        (
            "    state_store.compare_and_swap(\n"
            "        request.session_id,\n"
            "        request.version,\n"
            "        snapshot,\n"
            "    )\n"
            "    envelope = encode_sse_envelope(result, snapshot)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_CAS_SERIALIZATION_CAPABILITY",
        detail="encode_sse_envelope",
    )


def test_adapter_cannot_retain_alternate_serialization_capability(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/adapters/http.py",
        "def forward_sse_frames",
        (
            "def encode_terminal_sse_chunk(event):\n"
            "    return event.model_dump_json()\n\n\n"
            "def forward_sse_frames"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_CAS_SERIALIZATION_CAPABILITY",
        detail="encode_terminal_sse_chunk",
    )


def test_adapter_cannot_call_application_materializer(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/adapters/http.py",
        "    yield from frames",
        "    yield from materialize_error_frames(frames)",
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_CAS_SERIALIZATION_CAPABILITY",
        detail="materialize_error_frames",
    )


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (
            "    reply_slot: ReplySlotState | None\n",
            (
                "    reply_slot: ReplySlotState | None\n"
                "    candidates: tuple[DisplayedCandidateRef, ...] = ()\n"
            ),
        ),
        (
            "    knowledge_slot: KnowledgeSlotState | None\n",
            "",
        ),
    ),
    ids=("legacy-extra-field", "missing-current-slot"),
)
def test_snapshot_top_level_schema_is_exact(
    tmp_path: Path,
    old: str,
    new: str,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/feedback/contracts.py",
        old,
        new,
    )

    report = _check(root)

    _assert_violation(report, "SNAPSHOT_TOP_LEVEL_SCHEMA")


@pytest.mark.parametrize(
    ("old", "new", "detail"),
    (
        (
            "    focused_candidate_ordinal: int | None\n",
            (
                "    focused_candidate_ordinal: int | None\n"
                "    product_slot: ProductSlotState | None = None\n"
            ),
            "RecommendationSlotState",
        ),
        (
            "    focused_evidence_ids: tuple[EvidenceId, ...]\n",
            (
                "    focused_evidence_ids: tuple[EvidenceId, ...]\n"
                "    candidates: tuple[DisplayedCandidateRef, ...] = ()\n"
            ),
            "ProductSlotState",
        ),
        (
            "    focused_image_ordinal: int | None\n",
            (
                "    focused_image_ordinal: int | None\n"
                "    query_context: RecommendationQueryContext | None = None\n"
            ),
            "ImageSlotState",
        ),
        (
            "    state: ConsultationSubstate\n",
            (
                "    state: ConsultationSubstate\n"
                "    pending_turn: PendingTurn | None = None\n"
            ),
            "ConsultationSlotState",
        ),
        (
            "    evidence_ids: tuple[EvidenceId, ...]\n",
            (
                "    evidence_ids: tuple[EvidenceId, ...]\n"
                "    focused_product_id: ProductId | None = None\n"
            ),
            "KnowledgeSlotState",
        ),
        (
            "class PendingClarificationSlot(_StrictFrozen):\n"
            '    kind: Literal["clarification"] = "clarification"\n'
            "    value: ClarificationProgress\n",
            (
                "class PendingClarificationSlot(_StrictFrozen):\n"
                '    kind: Literal["clarification"] = "clarification"\n'
                "    value: ClarificationProgress\n"
                "    clarification: str | None = None\n"
            ),
            "PendingClarificationSlot",
        ),
        (
            "class PendingReplySlot(_StrictFrozen):\n"
            '    kind: Literal["pending_reply"] = "pending_reply"\n'
            "    value: PendingTurn\n",
            (
                "class PendingReplySlot(_StrictFrozen):\n"
                '    kind: Literal["pending_reply"] = "pending_reply"\n'
                "    value: PendingTurn\n"
                "    pending_turn: PendingTurn | None = None\n"
            ),
            "PendingReplySlot",
        ),
        (
            (
                "ReplySlotState = Annotated[\n"
                "    PendingClarificationSlot | PendingReplySlot,\n"
                '    Field(discriminator="kind"),\n'
                "]\n"
            ),
            (
                "ReplySlotState = Annotated[\n"
                "    PendingClarificationSlot | PendingReplySlot | dict,\n"
                '    Field(discriminator="kind"),\n'
                "]\n"
            ),
            "ReplySlotState",
        ),
        (
            "    ordinal: int | None\n",
            (
                "    ordinal: int | None\n"
                "    query_context: RecommendationQueryContext | None = None\n"
            ),
            "ActiveFocus",
        ),
    ),
    ids=(
        "recommendation",
        "product",
        "image",
        "consultation",
        "knowledge",
        "clarification-reply",
        "pending-reply",
        "reply-union",
        "active-focus",
    ),
)
def test_snapshot_nested_slot_schema_is_exact(
    tmp_path: Path,
    old: str,
    new: str,
    detail: str,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/feedback/contracts.py",
        old,
        new,
    )

    report = _check(root)

    _assert_violation(
        report,
        "SNAPSHOT_NESTED_SLOT_SCHEMA",
        detail=detail,
    )


@pytest.mark.parametrize(
    "legacy_field",
    ("image_results", "image_context", "images"),
)
def test_request_contract_rejects_legacy_image_payload_fields(
    tmp_path: Path,
    legacy_field: str,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide_runtime/contracts.py",
        "    image_bundle_id: str | None = None\n",
        (
            "    image_bundle_id: str | None = None\n"
            f"    {legacy_field}: object | None = None\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "LEGACY_REQUEST_FIELD",
        detail=legacy_field,
    )
