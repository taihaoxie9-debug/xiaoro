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
    decision = route_unified_turn(compiled, task_plan=request.task_plan)
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

from app.guide.application.execution_contracts import notify_processor_entry


@dataclass(frozen=True)
class ProcessorExecutionInput:
    turn_identity: object
    understanding: object
    decision: object
    current_snapshot: object
    routing_evidence: object


class RecommendationProcessor:
    def execute(self, execution_input):
        notify_processor_entry(
            None,
            execution_input=execution_input,
            implementation=type(self).__qualname__,
            processor_instance=self,
        )
        return execution_input


class SafetyProcessor:
    def execute(self, execution_input):
        notify_processor_entry(
            None,
            execution_input=execution_input,
            implementation=type(self).__qualname__,
            processor_instance=self,
        )
        return execution_input


def build_execution_input(**values):
    return ProcessorExecutionInput(**values)


processor_registry = {
    "recommendation": RecommendationProcessor(),
    "safety": SafetyProcessor(),
}
"""
RECOMMENDATION_EXECUTE_SOURCE = """
class RecommendationProcessor:
    def execute(self, execution_input):
        notify_processor_entry(
            None,
            execution_input=execution_input,
            implementation=type(self).__qualname__,
            processor_instance=self,
        )
        return execution_input
""".lstrip()

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
        "app/guide/application/execution_contracts.py",
        """
        def notify_processor_entry(
            observer,
            *,
            execution_input,
            implementation,
            processor_instance,
        ):
            return None
        """,
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
        def route_unified_turn(understanding, *, task_plan):
            return understanding, task_plan
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
    composition_roots: tuple[str, ...] = (),
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
        composition_roots=composition_roots,
    )


def _check(
    root: Path,
    *,
    production_roots: tuple[str, ...] = (STREAM_ROOT,),
    composition_roots: tuple[str, ...] = (),
):
    checker = _checker()
    return checker.check_single_path_architecture(
        root,
        manifest=_manifest(
            checker,
            production_roots=production_roots,
            composition_roots=composition_roots,
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
    "mount_source",
    (
        "app.mount('/static', object(), name='static')",
        "app.mount('/static/', object(), name='static')",
        "app.mount(path='/static', app=object(), name='static')",
        "STATIC_ROOT = '/static'\napp.mount(STATIC_ROOT, object())",
        "app.mount('/sta' + 'tic', object())",
        "app.mount(f\"/{'static'}\", object())",
        "app.mount('{}{}'.format('/sta', 'tic'), object())",
        "app.mount('%s%s' % ('/sta', 'tic'), object())",
        (
            "def mount_assets():\n"
            "    static_root = '/static'\n"
            "    app.mount(static_root, object())"
        ),
        (
            "STATIC_ROOT = '/static'\n"
            "app.mount(STATIC_ROOT, object())\n"
            "STATIC_ROOT = '/static/vendor'"
        ),
        (
            "STATIC_ROOT = '/static/vendor'\n"
            "def mount_assets():\n"
            "    STATIC_ROOT = '/static'\n"
            "    app.mount(STATIC_ROOT, object())"
        ),
    ),
)
def test_public_static_root_mount_is_rejected(
    tmp_path: Path,
    mount_source: str,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide_runtime/app.py",
        "app = FastAPI()",
        f"app = FastAPI()\n{mount_source}",
    )

    report = _check(root)

    _assert_violation(
        report,
        "PUBLIC_STATIC_HTML_BYPASS",
        detail="/static",
    )


def test_public_route_cannot_expose_fixture_transport(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    app_path = root / "app/guide_runtime/app.py"
    with app_path.open("a", encoding="utf-8") as stream:
        stream.write(
            "\n\n@app.get('/static/guide-demo-fixture.js')\n"
            "def fixture_transport():\n"
            "    return 'fixture'\n"
        )

    report = _check(root)

    _assert_violation(
        report,
        "PUBLIC_FIXTURE_TRANSPORT",
        detail="/static/guide-demo-fixture.js",
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
            (
                "    decision = route_unified_turn("
                "compiled, task_plan=request.task_plan)\n"
            ),
            "    decision = request.decision\n",
            (
                "    decision = route_unified_turn("
                "compiled, task_plan=request.task_plan)\n"
                "    decision = route_unified_turn("
                "compiled, task_plan=request.task_plan)\n"
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


def test_dead_canonical_call_does_not_satisfy_cardinality(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "    compiled = compile_turn_meaning(request.turn_meaning)\n",
        (
            "    if False:\n"
            "        compiled = compile_turn_meaning(request.turn_meaning)\n"
            "    compiled = request.turn_meaning\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compiler",
    )


def test_canonical_call_after_true_return_does_not_satisfy_cardinality(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "    compiled = compile_turn_meaning(request.turn_meaning)\n",
        (
            "    if True:\n"
            "        return request.turn_meaning\n"
            "    compiled = compile_turn_meaning(request.turn_meaning)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compiler",
    )


@pytest.mark.parametrize(
    ("module_import", "condition"),
    (
        ("", "1 == 0"),
        ("from typing import TYPE_CHECKING\n", "TYPE_CHECKING"),
        ("import typing\n", "typing.TYPE_CHECKING"),
        ("import typing as typing_alias\n", "typing_alias.TYPE_CHECKING"),
    ),
)
def test_statically_false_canonical_call_does_not_satisfy_cardinality(
    tmp_path: Path,
    module_import: str,
    condition: str,
) -> None:
    root = _legal_repository(tmp_path)
    if module_import:
        _replace_source(
            root,
            "app/guide/application/flow.py",
            "from app.guide.application.processors import (\n",
            (
                module_import
                + "from app.guide.application.processors import (\n"
            ),
        )
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "    compiled = compile_turn_meaning(request.turn_meaning)\n",
        (
            f"    if {condition}:\n"
            "        compiled = compile_turn_meaning(request.turn_meaning)\n"
            "    compiled = request.turn_meaning\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compiler",
    )


@pytest.mark.parametrize(
    "shadow",
    (
        (
            "    try:\n"
            "        pass\n"
            "    except Exception as compile_turn_meaning:\n"
            "        pass\n"
        ),
        (
            "    match None:\n"
            "        case compile_turn_meaning:\n"
            "            pass\n"
        ),
    ),
)
def test_non_name_store_shadowed_canonical_call_is_rejected(
    tmp_path: Path,
    shadow: str,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "    compiled = compile_turn_meaning(request.turn_meaning)\n",
        (
            shadow
            + "    compiled = compile_turn_meaning("
            "request.turn_meaning)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compiler",
    )


def test_locally_shadowed_canonical_call_does_not_satisfy_cardinality(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "    compiled = compile_turn_meaning(request.turn_meaning)\n",
        (
            "    compile_turn_meaning = lambda meaning: meaning\n"
            "    compiled = compile_turn_meaning(request.turn_meaning)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compiler",
    )


def test_module_shadowed_canonical_call_does_not_satisfy_cardinality(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "from app.guide.intent.compiler "
            "import compile_turn_meaning\n"
        ),
        (
            "from app.guide.intent.compiler "
            "import compile_turn_meaning\n"
            "compile_turn_meaning = lambda meaning: meaning\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compiler",
    )


def test_canonical_call_after_raise_in_try_does_not_satisfy_cardinality(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "    compiled = compile_turn_meaning(request.turn_meaning)\n",
        (
            "    try:\n"
            "        raise RuntimeError('stop')\n"
            "        compiled = compile_turn_meaning(request.turn_meaning)\n"
            "    except RuntimeError:\n"
            "        compiled = request.turn_meaning\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compiler",
    )


@pytest.mark.parametrize(
    "replacement",
    (
        (
            "    while True:\n"
            "        break\n"
            "        compiled = compile_turn_meaning(request.turn_meaning)\n"
            "    compiled = request.turn_meaning\n"
        ),
        (
            "    for _ in (1,):\n"
            "        continue\n"
            "        compiled = compile_turn_meaning(request.turn_meaning)\n"
            "    compiled = request.turn_meaning\n"
        ),
    ),
)
def test_canonical_call_after_loop_exit_does_not_satisfy_cardinality(
    tmp_path: Path,
    replacement: str,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "    compiled = compile_turn_meaning(request.turn_meaning)\n",
        replacement,
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compiler",
    )


def test_conditionally_shadowed_module_call_does_not_satisfy_cardinality(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "from app.guide.intent.compiler "
            "import compile_turn_meaning\n"
        ),
        (
            "from app.guide.intent.compiler "
            "import compile_turn_meaning\n"
            "if True:\n"
            "    compile_turn_meaning = lambda meaning: meaning\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compiler",
    )


def test_processor_cannot_delegate_directly_to_another_processor(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        RECOMMENDATION_EXECUTE_SOURCE,
        RECOMMENDATION_EXECUTE_SOURCE.replace(
            "        return execution_input\n",
            "        return SafetyProcessor().execute(execution_input)\n",
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_TO_PROCESSOR_REACHABILITY",
        detail="SafetyProcessor",
    )


def test_processor_cannot_delegate_through_untyped_instance_attribute(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        (
            "class RecommendationProcessor:\n"
            "    def __init__(self, delegate):\n"
            "        self.delegate = delegate\n"
            "\n"
        ),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "        return execution_input\n",
        "        return self.delegate.execute(execution_input)\n",
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_TO_PROCESSOR_REACHABILITY",
        detail="delegate.execute",
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
        RECOMMENDATION_EXECUTE_SOURCE,
        RECOMMENDATION_EXECUTE_SOURCE.replace(
            "        return execution_input\n",
            "        return delegate_to_safety(execution_input)\n",
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_TO_PROCESSOR_REACHABILITY",
        detail="build_safety_processor",
    )


def test_processor_cannot_delegate_through_local_callable_alias(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        """
def delegate_to_safety(execution_input):
    return SafetyProcessor().execute(execution_input)


class RecommendationProcessor:
""".lstrip(),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        RECOMMENDATION_EXECUTE_SOURCE,
        RECOMMENDATION_EXECUTE_SOURCE.replace(
            "        return execution_input\n",
            (
                "        bridge = delegate_to_safety\n"
                "        return bridge(execution_input)\n"
            ),
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_TO_PROCESSOR_REACHABILITY",
        detail="delegate_to_safety",
    )


def test_processor_alias_resolution_uses_definition_at_call_site(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        """
def delegate_to_safety(execution_input):
    return SafetyProcessor().execute(execution_input)


def harmless(execution_input):
    return execution_input


class RecommendationProcessor:
""".lstrip(),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        RECOMMENDATION_EXECUTE_SOURCE,
        RECOMMENDATION_EXECUTE_SOURCE.replace(
            "        return execution_input\n",
            (
                "        bridge = delegate_to_safety\n"
                "        result = bridge(execution_input)\n"
                "        bridge = harmless\n"
                "        return result\n"
            ),
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_TO_PROCESSOR_REACHABILITY",
        detail="delegate_to_safety",
    )


def test_processor_cannot_delegate_through_module_callable_alias(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        """
def delegate_to_safety(execution_input):
    return SafetyProcessor().execute(execution_input)


bridge = delegate_to_safety


class RecommendationProcessor:
""".lstrip(),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        RECOMMENDATION_EXECUTE_SOURCE,
        RECOMMENDATION_EXECUTE_SOURCE.replace(
            "        return execution_input\n",
            "        return bridge(execution_input)\n",
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_TO_PROCESSOR_REACHABILITY",
        detail="delegate_to_safety",
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
        RECOMMENDATION_EXECUTE_SOURCE,
        RECOMMENDATION_EXECUTE_SOURCE.replace(
            "        return execution_input\n",
            "        result = self._execute_core(execution_input)\n"
            "        result = bind_profile_owner(result)\n"
            "        return result\n",
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


def test_runtime_registration_writer_has_one_launcher_owner(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "tools/guide_gates/attempt_ledger.py",
        """
        def register_runtime_bound_attempt(*args, **kwargs):
            return {}
        """,
    )
    _write_source(
        root,
        "tools/guide_gates/run_bound_runtime.py",
        """
        from tools.guide_gates.attempt_ledger import (
            register_runtime_bound_attempt,
        )

        def run_bound_runtime():
            return register_runtime_bound_attempt()
        """,
    )

    assert _check(root).passed

    _write_source(
        root,
        "tools/guide_gates/rogue_runtime.py",
        """
        from tools.guide_gates.attempt_ledger import (
            register_runtime_bound_attempt as register_runtime,
        )

        def start_unbound_runtime():
            return register_runtime()
        """,
    )

    _assert_violation(
        _check(root),
        "NONCANONICAL_RUNTIME_REGISTRATION",
        detail="rogue_runtime.py",
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


def test_processor_execute_requires_concrete_entry_observation(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        (
            "        notify_processor_entry(\n"
            "            None,\n"
            "            execution_input=execution_input,\n"
            "            implementation=type(self).__qualname__,\n"
            "            processor_instance=self,\n"
            "        )\n"
        ),
        "",
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_CONCRETE_ENTRY_OBSERVATION",
        detail="RecommendationProcessor.execute",
    )


def test_processor_execute_rejects_duplicate_entry_observation(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    call = (
        "        notify_processor_entry(\n"
        "            None,\n"
        "            execution_input=execution_input,\n"
        "            implementation=type(self).__qualname__,\n"
        "            processor_instance=self,\n"
        "        )\n"
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        call,
        call + call,
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_CONCRETE_ENTRY_OBSERVATION",
        detail="RecommendationProcessor.execute",
    )


def test_dispatcher_cannot_claim_concrete_processor_entry(
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
            "    notify_processor_entry(\n"
            "        None,\n"
            "        execution_input=execution_input,\n"
            "        implementation='dispatcher',\n"
            "        processor_instance=processor_registry["
            "decision.processor],\n"
            "    )\n"
            "    result = processor_registry["
            "decision.processor].execute(execution_input)\n"
        ),
    )
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "from app.guide.application.wire import encode_sse_envelope\n",
        (
            "from app.guide.application.wire import encode_sse_envelope\n"
            "from app.guide.application.execution_contracts import "
            "notify_processor_entry\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_CONCRETE_ENTRY_OBSERVATION",
        detail="run_turn",
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


def test_processor_constructor_rejects_pre_routing_authority_dependency(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        (
            "class RecommendationProcessor:\n"
            "    def __init__(self, image_bundles: ImageBundleService):\n"
            "        self._image_bundles = image_bundles\n\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_PRE_ROUTING_DEPENDENCY",
        detail="image_bundles",
    )


def test_processor_constructor_rejects_aliased_bundle_authority(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        (
            "class RecommendationProcessor:\n"
            "    def __init__(self, access: BundleAuthorizationPort):\n"
            "        self._access = access\n\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_PRE_ROUTING_DEPENDENCY",
        detail="BundleAuthorizationPort",
    )


def test_processor_constructor_resolves_imported_authority_alias(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "from dataclasses import dataclass\n",
        (
            "from dataclasses import dataclass\n"
            "from app.guide.application.image_bundle_service "
            "import ImageBundleService as IBS\n"
        ),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        (
            "class RecommendationProcessor:\n"
            "    def __init__(self, access: IBS):\n"
            "        self._access = access\n\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_PRE_ROUTING_DEPENDENCY",
        detail="ImageBundleService",
    )


def test_image_routing_evidence_cannot_retain_owner_credential(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide/application/execution_contracts.py",
        """
        from dataclasses import dataclass


        @dataclass(frozen=True)
        class ImageRoutingEvidence:
            bundle: object
            owner_token: str
            payloads: tuple[object, ...]
            observations: tuple[object, ...]
            anchor_topic: object | None
        """,
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_ROUTER_PRE_ROUTING_AUTHORITY",
        detail="owner_token",
    )


def test_post_router_parser_alias_is_rejected(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide/intent/semantic.py",
        """
        def parse_scenarios(value):
            return value
        """,
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "from dataclasses import dataclass\n",
        (
            "from dataclasses import dataclass\n"
            "from app.guide.intent.semantic import parse_scenarios as decode\n"
        ),
    )
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "        return execution_input\n",
        "        return decode(execution_input)\n",
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_ROUTER_SEMANTIC_PARSER",
        detail="parse_scenarios",
    )


def test_canonical_call_import_alias_is_counted(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "from app.guide.intent.compiler "
            "import compile_turn_meaning\n"
        ),
        (
            "from app.guide.intent.compiler "
            "import compile_turn_meaning\n"
            "from app.guide.intent.compiler "
            "import compile_turn_meaning as hidden_compile\n"
        ),
    )
    _replace_source(
        root,
        "app/guide/application/flow.py",
        "    compiled = compile_turn_meaning(request.turn_meaning)\n",
        (
            "    hidden_compile(request.turn_meaning)\n"
            "    compiled = compile_turn_meaning(request.turn_meaning)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "CANONICAL_CALL_CARDINALITY",
        detail="compile_turn_meaning",
    )


def test_processor_dispatch_rejects_hidden_constant_selection(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "    result = "
            "processor_registry[decision.processor].execute(execution_input)\n"
        ),
        (
            "    selected = processor_registry['recommendation']\n"
            "    result = selected.execute(execution_input)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_CALL_SIGNATURE",
        detail="recommendation",
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


def test_post_router_query_contract_rejects_raw_text_fields(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide/retrieval/product_evidence_retrieval.py",
        """
        from dataclasses import dataclass


        @dataclass(frozen=True)
        class EvidenceQuery:
            product_ids: tuple[int, ...]
            raw_question: str
            question_meaning: str
            product_mention_spans: tuple[tuple[int, int], ...]
            safety_sensitive: bool
        """,
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_ROUTER_RAW_TEXT_ACCESS",
        detail="EvidenceQuery",
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


def test_processor_cannot_also_collect_pre_routing_evidence(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        (
            "class RecommendationProcessor:\n"
            "    def prepare_routing_evidence(self, request):\n"
            "        return request\n\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_COLLECTOR_ROLE_ALIAS",
        detail="RecommendationProcessor",
    )


@pytest.mark.parametrize(
    "method_name",
    (
        "resolve_product_resolution",
        "resolve_product_bindings",
    ),
)
def test_processor_cannot_expose_pre_routing_product_resolution(
    tmp_path: Path,
    method_name: str,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        (
            "class RecommendationProcessor:\n"
            f"    def {method_name}(self, request):\n"
            "        return request\n\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_PRE_ROUTING_PRODUCT_RESOLUTION",
        detail=method_name,
    )


def test_processor_cannot_retain_product_name_resolver(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "class RecommendationProcessor:\n",
        (
            "class RecommendationProcessor:\n"
            "    def __init__(\n"
            "        self,\n"
            "        product_name_resolver: ProductNameResolver,\n"
            "    ):\n"
            "        self._product_name_resolver = product_name_resolver\n\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PROCESSOR_PRE_ROUTING_PRODUCT_RESOLUTION",
        detail="product_name_resolver",
    )


def test_pre_routing_evidence_must_follow_compile_and_precede_router(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "    compiled = compile_turn_meaning(request.turn_meaning)\n"
            "    decision = route_unified_turn("
            "compiled, task_plan=request.task_plan)\n"
        ),
        (
            "    routing_evidence = prepare_routing_evidence(request)\n"
            "    compiled = compile_turn_meaning(request.turn_meaning)\n"
            "    decision = route_unified_turn("
            "compiled, task_plan=request.task_plan)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "PRE_ROUTING_EVIDENCE_ORDER",
        detail="prepare_routing_evidence",
    )


def test_composition_cannot_bind_processor_as_evidence_collector(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide_runtime/composition.py",
        """
        def build_runtime(image_processor):
            return UnifiedGuideFlow(
                image_processor=image_processor,
                image_evidence_collector=image_processor,
            )
        """,
    )

    report = _check(
        root,
        composition_roots=(
            "app.guide_runtime.composition:build_runtime",
        ),
    )

    _assert_violation(
        report,
        "PROCESSOR_COLLECTOR_ROLE_ALIAS",
        detail="image_processor",
    )


def test_composition_cannot_hide_processor_behind_local_alias(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide_runtime/composition.py",
        """
        def build_runtime(image_processor):
            alias = image_processor
            return UnifiedGuideFlow(
                image_processor=image_processor,
                image_evidence_collector=alias,
            )
        """,
    )

    report = _check(
        root,
        composition_roots=(
            "app.guide_runtime.composition:build_runtime",
        ),
    )

    _assert_violation(
        report,
        "PROCESSOR_COLLECTOR_ROLE_ALIAS",
        detail="alias",
    )


def test_production_composition_rejects_encoder_override(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide_runtime/composition.py",
        """
        def build_runtime(*, image_encoder=None):
            return image_encoder
        """,
    )

    report = _check(
        root,
        composition_roots=(
            "app.guide_runtime.composition:build_runtime",
        ),
    )

    _assert_violation(
        report,
        "PRODUCTION_ENCODER_OVERRIDE",
        detail="image_encoder",
    )


def test_presentation_responsibility_cannot_be_optional(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide/presentation/presentation_packet.py",
        """
        class PresentationPacket:
            mode: object
            responsibility: object | None = None


        def build_presentation_packet(
            *,
            mode,
            responsibility=None,
        ):
            return PresentationPacket()
        """,
    )

    report = _check(root)

    _assert_violation(
        report,
        "PRESENTATION_RESPONSIBILITY_INFERENCE",
        detail="responsibility",
    )


def test_unified_flow_rejects_parallel_image_stream_entrypoint(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide/application/unified_guide_flow.py",
        """
        class UnifiedGuideFlow:
            def stream(self, turn):
                return turn

            def stream_image(self, turn):
                return turn
        """,
    )

    report = _check(root)

    _assert_violation(
        report,
        "PARALLEL_UNIFIED_FLOW_ENTRYPOINT",
        detail="stream_image",
    )


def test_presentation_compiler_cannot_rederive_route_mode(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _write_source(
        root,
        "app/guide/presentation/presentation_compiler.py",
        """
        from app.guide.intent.responsibility_matrix import (
            decision_for_responsibility,
        )


        def compile_presentation(inputs):
            return decision_for_responsibility(
                inputs.packet.responsibility
            ).presentation_mode
        """,
    )

    report = _check(root)

    _assert_violation(
        report,
        "PRESENTATION_MODE_REDERIVATION",
        detail="decision_for_responsibility",
    )


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


def test_flow_cannot_rebuild_task_after_router(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/flow.py",
        (
            "    decision = route_unified_turn("
            "compiled, task_plan=request.task_plan)\n"
        ),
        (
            "    decision = route_unified_turn("
            "compiled, task_plan=request.task_plan)\n"
            "    task = plan_task(compiled)\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_ROUTER_TASK_MUTATION",
        detail="plan_task",
    )


def test_router_cannot_make_pre_routing_task_optional_or_replan(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/intent/router.py",
        (
            "def route_unified_turn(understanding, *, task_plan):\n"
            "    return understanding, task_plan\n"
        ),
        (
            "def route_unified_turn(understanding, *, task_plan=None):\n"
            "    if task_plan is None:\n"
            "        task_plan = plan_task(understanding)\n"
            "    return understanding, task_plan\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "ROUTER_TASK_AUTHORITY",
        detail="task_plan",
    )
    _assert_violation(
        report,
        "ROUTER_TASK_AUTHORITY",
        detail="plan_task",
    )


def test_processor_cannot_revalidate_router_owned_task(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "        return execution_input\n",
        (
            "        return revalidate_task_plan(\n"
            "            execution_input.decision.task_plan,\n"
            "            update={'mode': 'recommend'},\n"
            "        )\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_ROUTER_SEMANTIC_PARSER",
        detail="revalidate_task_plan",
    )


def test_processor_cannot_copy_router_owned_task(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/application/processors.py",
        "        return execution_input\n",
        (
            "        task = execution_input.decision.task_plan\n"
            "        return task.model_copy(\n"
            "            update={'constraints': []},\n"
            "            deep=True,\n"
            "        )\n"
        ),
    )

    report = _check(root)

    _assert_violation(
        report,
        "POST_ROUTER_TASK_MUTATION",
        detail="model_copy",
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


def test_adapter_may_hash_session_identity_without_serializing_sse(
    tmp_path: Path,
) -> None:
    root = _legal_repository(tmp_path)
    _replace_source(
        root,
        "app/guide/adapters/http.py",
        "def forward_sse_frames",
        (
            "from hashlib import sha256\n\n\n"
            "def session_lock_name(session_id):\n"
            "    return sha256(session_id.encode('utf-8')).hexdigest()\n\n\n"
            "def forward_sse_frames"
        ),
    )

    assert _check(root).passed


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


def test_architecture_report_publication_cannot_overwrite_racing_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checker = _checker()
    output = tmp_path / "architecture.json"
    output.write_bytes(b"existing-authority\n")
    original_exists = Path.exists

    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: (
            False if path == output else original_exists(path)
        ),
    )

    with pytest.raises(FileExistsError, match="already exists"):
        checker._write_report(
            output,
            checker.ArchitectureReport(
                inspected_modules=("app.guide.example",),
                violations=(),
            ),
        )

    assert output.read_bytes() == b"existing-authority\n"
