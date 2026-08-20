from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import importlib
from pathlib import Path

from app.guide.application.pending_turn import classify_pending_reply
from app.guide.understanding.contracts import BudgetDraft, CategoryDraft
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_revision_confirmations,
)
from tools.guide_gates.run_real_unified_router_gate import (
    load_real_unified_router_cases,
)
from tools.guide_gates.unified_router_gate import load_replay_cases


def _module():
    return importlib.import_module(
        "tools.guide_gates.unified_router_blind_fixture"
    )


def _final_module():
    return importlib.import_module(
        "tools.guide_gates.unified_router_final_blind_fixture"
    )


def _qualification_module():
    return importlib.import_module(
        "tools.guide_gates.unified_router_qualification_fixture"
    )


def _replays():
    return load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )


def test_blind_a_builder_freezes_independent_hundred_case_shape() -> None:
    module = _module()

    first = module.build_unified_router_blind_a_cases(_replays())
    second = module.build_unified_router_blind_a_cases(_replays())

    assert first == second
    assert len(first) == 100
    assert len({case.case_id for case in first}) == 100
    assert len({case.message for case in first}) == 100
    assert sum(case.starting_snapshot is None for case in first) == 55
    assert sum(case.starting_snapshot is not None for case in first) == 45
    category_counts = Counter(case.category for case in first)
    assert set(category_counts) == {
        "recommendation",
        "comparison",
        "product_knowledge",
        "general_knowledge",
        "image",
        "consultation",
        "clarification",
        "safety",
        "state_transition",
    }
    assert min(category_counts.values()) >= 4
    smoke = load_real_unified_router_cases(
        "tests/fixtures/guide/intent/unified_router_smoke_v3.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_smoke_v3_manifest.json"
        ),
    )
    assert not (
        {case.message for case in first}
        & {case.message for case in smoke}
    )


def test_frozen_blind_a_matches_builder() -> None:
    module = _module()
    generated = (
        b"\n".join(
            case.model_dump_json().encode("utf-8")
            for case in module.build_unified_router_blind_a_cases(
                _replays()
            )
        )
        + b"\n"
    )

    assert (
        Path(
            "tests/fixtures/guide/intent/"
            "unified_router_blind_a_v1.jsonl"
        ).read_bytes()
        == generated
    )
    cases = load_real_unified_router_cases(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_a_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_blind_a_v1_manifest.json"
        ),
    )
    assert len(cases) == 100


def test_final_blind_builders_freeze_two_independent_batches() -> None:
    module = _final_module()
    blind_a2 = module.build_unified_router_blind_a2_cases(_replays())
    blind_b1 = module.build_unified_router_blind_b1_cases(_replays())

    for cases in (blind_a2, blind_b1):
        assert len(cases) == 100
        assert len({case.case_id for case in cases}) == 100
        assert len({case.message for case in cases}) == 100
        assert sum(case.starting_snapshot is None for case in cases) == 55
        assert sum(case.starting_snapshot is not None for case in cases) == 45
        category_counts = Counter(case.category for case in cases)
        assert len(category_counts) == 9
        assert min(category_counts.values()) >= 4

    smoke = load_real_unified_router_cases(
        "tests/fixtures/guide/intent/unified_router_smoke_v3.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_smoke_v3_manifest.json"
        ),
    )
    development_a = load_real_unified_router_cases(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_a_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_blind_a_v1_manifest.json"
        ),
    )
    prior_messages = {
        case.message for case in (*smoke, *development_a)
    }
    a2_messages = {case.message for case in blind_a2}
    b1_messages = {case.message for case in blind_b1}
    assert not a2_messages & prior_messages
    assert not b1_messages & prior_messages
    assert not a2_messages & b1_messages


def test_frozen_final_blind_batches_match_builders() -> None:
    module = _final_module()
    for fixture_name, cases in (
        (
            "unified_router_blind_a_v2",
            module.build_unified_router_blind_a2_cases(_replays()),
        ),
        (
            "unified_router_blind_b_v1",
            module.build_unified_router_blind_b1_cases(_replays()),
        ),
    ):
        generated = (
            b"\n".join(
                case.model_dump_json().encode("utf-8")
                for case in cases
            )
            + b"\n"
        )
        fixture_path = Path(
            f"tests/fixtures/guide/intent/{fixture_name}.jsonl"
        )
        manifest_path = Path(
            f"tests/fixtures/guide/intent/{fixture_name}_manifest.json"
        )
        assert fixture_path.read_bytes() == generated
        frozen = load_real_unified_router_cases(
            fixture_path,
            manifest_path=manifest_path,
        )
        assert frozen == cases


def test_qualification_builders_freeze_two_unseen_independent_batches(
) -> None:
    module = _qualification_module()
    blind_a3 = module.build_unified_router_blind_a3_cases(_replays())
    blind_b2 = module.build_unified_router_blind_b2_cases(_replays())

    for cases in (blind_a3, blind_b2):
        assert len(cases) == 100
        assert len({case.case_id for case in cases}) == 100
        assert len({case.message for case in cases}) == 100
        assert sum(case.starting_snapshot is None for case in cases) == 55
        assert sum(case.starting_snapshot is not None for case in cases) == 45
        category_counts = Counter(case.category for case in cases)
        assert len(category_counts) == 9
        assert min(category_counts.values()) >= 4

    prior_messages = set()
    for fixture_name in (
        "unified_router_smoke_v3",
        "unified_router_blind_a_v1",
        "unified_router_blind_a_v2",
    ):
        prior_messages.update(
            case.message
            for case in load_real_unified_router_cases(
                f"tests/fixtures/guide/intent/{fixture_name}.jsonl",
                manifest_path=(
                    "tests/fixtures/guide/intent/"
                    f"{fixture_name}_manifest.json"
                ),
            )
        )
    a3_messages = {case.message for case in blind_a3}
    b2_messages = {case.message for case in blind_b2}
    assert not a3_messages & prior_messages
    assert not b2_messages & prior_messages
    assert not a3_messages & b2_messages
    assert max(
        SequenceMatcher(None, left, right).ratio()
        for left in a3_messages
        for right in b2_messages
    ) < 0.70


def test_frozen_qualification_batches_match_builders() -> None:
    module = _qualification_module()
    for fixture_name, cases in (
        (
            "unified_router_blind_a_v3",
            module.build_unified_router_blind_a3_cases(_replays()),
        ),
        (
            "unified_router_blind_b_v2",
            module.build_unified_router_blind_b2_cases(_replays()),
        ),
    ):
        generated = (
            b"\n".join(
                case.model_dump_json().encode("utf-8")
                for case in cases
            )
            + b"\n"
        )
        fixture_path = Path(
            f"tests/fixtures/guide/intent/{fixture_name}.jsonl"
        )
        manifest_path = Path(
            f"tests/fixtures/guide/intent/{fixture_name}_manifest.json"
        )
        assert fixture_path.read_bytes() == generated
        frozen = load_real_unified_router_cases(
            fixture_path,
            manifest_path=manifest_path,
        )
        assert frozen == cases


def test_requalified_a4_batch_is_unseen_and_well_formed() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_a4_cases(_replays())

    assert len(cases) == 100
    assert len({case.case_id for case in cases}) == 100
    assert len({case.message for case in cases}) == 100
    assert sum(case.starting_snapshot is None for case in cases) == 55
    assert sum(case.starting_snapshot is not None for case in cases) == 45
    counts = Counter(case.category for case in cases)
    assert len(counts) == 9
    assert min(counts.values()) >= 4

    prior_messages = set()
    for fixture_name in (
        "unified_router_smoke_v3",
        "unified_router_blind_a_v1",
        "unified_router_blind_a_v2",
        "unified_router_blind_a_v3",
    ):
        prior_messages.update(
            case.message
            for case in load_real_unified_router_cases(
                f"tests/fixtures/guide/intent/{fixture_name}.jsonl",
                manifest_path=(
                    "tests/fixtures/guide/intent/"
                    f"{fixture_name}_manifest.json"
                ),
            )
        )
    assert not {case.message for case in cases} & prior_messages


def test_frozen_a4_batch_matches_builder() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_a4_cases(_replays())
    generated = (
        b"\n".join(
            case.model_dump_json().encode("utf-8")
            for case in cases
        )
        + b"\n"
    )
    fixture_path = Path(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_a_v4.jsonl"
    )
    manifest_path = Path(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_a_v4_manifest.json"
    )

    assert fixture_path.read_bytes() == generated
    assert load_real_unified_router_cases(
        fixture_path,
        manifest_path=manifest_path,
    ) == cases


def test_second_qualification_b3_is_independent_from_a4() -> None:
    module = _qualification_module()
    a4 = module.build_unified_router_blind_a4_cases(_replays())
    b3 = module.build_unified_router_blind_b3_cases(_replays())

    assert len(b3) == 100
    assert len({case.case_id for case in b3}) == 100
    assert len({case.message for case in b3}) == 100
    assert sum(case.starting_snapshot is None for case in b3) == 55
    assert sum(case.starting_snapshot is not None for case in b3) == 45
    counts = Counter(case.category for case in b3)
    assert len(counts) == 9
    assert min(counts.values()) >= 4

    prior_messages = set()
    for fixture_name in (
        "unified_router_smoke_v3",
        "unified_router_blind_a_v1",
        "unified_router_blind_a_v2",
        "unified_router_blind_a_v3",
        "unified_router_blind_a_v4",
    ):
        prior_messages.update(
            case.message
            for case in load_real_unified_router_cases(
                f"tests/fixtures/guide/intent/{fixture_name}.jsonl",
                manifest_path=(
                    "tests/fixtures/guide/intent/"
                    f"{fixture_name}_manifest.json"
                ),
            )
        )
    b3_messages = {case.message for case in b3}
    assert not b3_messages & prior_messages
    assert max(
        SequenceMatcher(None, left.message, right.message).ratio()
        for left in a4
        for right in b3
    ) < 0.70


def test_b3_fixture_messages_pass_deterministic_protocol_preflight() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_b3_cases(_replays())

    recommendation_cases = tuple(
        case
        for case in cases
        if case.case_id.startswith("blind-b3-nh-recommend-")
    )
    for case in recommendation_cases:
        drafts, issues = parse_exact_constraints(case.message)
        budgets = tuple(
            draft
            for draft in drafts
            if isinstance(draft, BudgetDraft)
        )
        assert not issues
        assert len(budgets) == 1, case.case_id
        assert budgets[0].maximum == 500, case.case_id

    withdrawal_cases = tuple(
        case
        for case in cases
        if case.case_id.startswith("blind-b3-ctx-withdraw-")
    )
    for case in withdrawal_cases:
        proofs = parse_exact_revision_confirmations(case.message)
        assert len(proofs) == 1, case.case_id
        assert proofs[0].affected_value == "酒精", case.case_id

    pending_cases = tuple(
        case
        for case in cases
        if (
            case.case_id.startswith("blind-b3-ctx-affirm-")
            or case.case_id.startswith("blind-b3-ctx-reject-")
        )
    )
    for case in pending_cases:
        assert case.starting_snapshot is not None
        assert case.starting_snapshot.pending_turn is not None
        reply = classify_pending_reply(
            message=case.message,
            pending=case.starting_snapshot.pending_turn,
        )
        expected_kind = (
            "affirm"
            if "-ctx-affirm-" in case.case_id
            else "reject"
        )
        assert reply.kind == expected_kind, case.case_id

    comparison_cases = tuple(
        case for case in cases if case.category == "comparison"
    )
    for case in comparison_cases:
        bindings = case.expected_bindings
        assert tuple(
            binding.product_id for binding in bindings
        ) == case.expected_card_ids, case.case_id
        assert [
            case.message.index(binding.source_text)
            for binding in bindings
        ] == sorted(
            case.message.index(binding.source_text)
            for binding in bindings
        ), case.case_id


def test_frozen_b3_batch_matches_builder() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_b3_cases(_replays())
    generated = (
        b"\n".join(
            case.model_dump_json().encode("utf-8")
            for case in cases
        )
        + b"\n"
    )
    fixture_path = Path(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_b_v3.jsonl"
    )
    manifest_path = Path(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_b_v3_manifest.json"
    )

    assert fixture_path.read_bytes() == generated
    assert load_real_unified_router_cases(
        fixture_path,
        manifest_path=manifest_path,
    ) == cases


def test_release_b4_builder_is_unseen_and_well_formed() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_b4_cases(_replays())

    assert len(cases) == 100
    assert len({case.case_id for case in cases}) == 100
    assert len({case.message for case in cases}) == 100
    assert sum(case.starting_snapshot is None for case in cases) == 55
    assert sum(case.starting_snapshot is not None for case in cases) == 45
    counts = Counter(case.category for case in cases)
    assert len(counts) == 9
    assert min(counts.values()) >= 4

    prior_cases = []
    for fixture_name in (
        "unified_router_smoke_v3",
        "unified_router_blind_a_v1",
        "unified_router_blind_a_v2",
        "unified_router_blind_a_v3",
        "unified_router_blind_a_v4",
        "unified_router_blind_b_v1",
        "unified_router_blind_b_v2",
        "unified_router_blind_b_v3",
    ):
        prior_cases.extend(
            load_real_unified_router_cases(
                f"tests/fixtures/guide/intent/{fixture_name}.jsonl",
                manifest_path=(
                    "tests/fixtures/guide/intent/"
                    f"{fixture_name}_manifest.json"
                ),
            )
        )
    messages = {case.message for case in cases}
    prior_messages = {case.message for case in prior_cases}
    assert not messages & prior_messages
    assert max(
        SequenceMatcher(None, left, right).ratio()
        for left in messages
        for right in prior_messages
    ) < 0.70


def test_b4_fixture_messages_pass_deterministic_protocol_preflight() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_b4_cases(_replays())

    for case in cases:
        if case.case_id.startswith((
            "blind-b4-nh-recommend-",
            "blind-b4-nh-friend-",
            "blind-b4-ctx-profile-",
            "blind-b4-ctx-friend-",
        )):
            drafts, issues = parse_exact_constraints(case.message)
            budgets = tuple(
                draft
                for draft in drafts
                if isinstance(draft, BudgetDraft)
            )
            assert not issues, case.case_id
            assert len(budgets) == 1, case.case_id
            assert budgets[0].maximum == 500, case.case_id
        if case.case_id.startswith("blind-b4-ctx-budget-"):
            drafts, issues = parse_exact_constraints(case.message)
            budgets = tuple(
                draft
                for draft in drafts
                if isinstance(draft, BudgetDraft)
            )
            assert not issues, case.case_id
            assert len(budgets) == 1, case.case_id
            assert budgets[0].maximum == 100, case.case_id
        if case.case_id.startswith("blind-b4-ctx-withdraw-"):
            proofs = parse_exact_revision_confirmations(case.message)
            assert len(proofs) == 1, case.case_id
            assert proofs[0].affected_value == "酒精", case.case_id
        if (
            case.case_id.startswith("blind-b4-ctx-affirm-")
            or case.case_id.startswith("blind-b4-ctx-reject-")
        ):
            assert case.starting_snapshot is not None
            assert case.starting_snapshot.pending_turn is not None
            reply = classify_pending_reply(
                message=case.message,
                pending=case.starting_snapshot.pending_turn,
            )
            expected_kind = (
                "affirm"
                if "-ctx-affirm-" in case.case_id
                else "reject"
            )
            assert reply.kind == expected_kind, case.case_id
        if case.category == "comparison":
            assert tuple(
                binding.product_id
                for binding in case.expected_bindings
            ) == case.expected_card_ids, case.case_id
            positions = [
                case.message.index(binding.source_text)
                for binding in case.expected_bindings
            ]
            assert positions == sorted(positions), case.case_id
        if case.category == "safety":
            drafts, _ = parse_exact_constraints(case.message)
            exact_topics = {
                draft.value.value
                for draft in drafts
                if isinstance(draft, CategoryDraft)
            }
            assert exact_topics <= set(
                case.acceptable_semantic.topic_hints
            ), case.case_id


def test_frozen_b4_batch_matches_builder() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_b4_cases(_replays())
    generated = (
        b"\n".join(
            case.model_dump_json().encode("utf-8")
            for case in cases
        )
        + b"\n"
    )
    fixture_path = Path(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_b_v4.jsonl"
    )
    manifest_path = Path(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_b_v4_manifest.json"
    )

    assert fixture_path.read_bytes() == generated
    assert load_real_unified_router_cases(
        fixture_path,
        manifest_path=manifest_path,
    ) == cases


def test_release_b5_builder_is_unseen_and_well_formed() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_b5_cases(_replays())

    assert len(cases) == 100
    assert len({case.case_id for case in cases}) == 100
    assert len({case.message for case in cases}) == 100
    assert sum(case.starting_snapshot is None for case in cases) == 55
    assert sum(case.starting_snapshot is not None for case in cases) == 45
    counts = Counter(case.category for case in cases)
    assert len(counts) == 9
    assert min(counts.values()) >= 4

    prior_cases = []
    for fixture_name in (
        "unified_router_smoke_v3",
        "unified_router_blind_a_v1",
        "unified_router_blind_a_v2",
        "unified_router_blind_a_v3",
        "unified_router_blind_a_v4",
        "unified_router_blind_b_v1",
        "unified_router_blind_b_v2",
        "unified_router_blind_b_v3",
        "unified_router_blind_b_v4",
    ):
        prior_cases.extend(
            load_real_unified_router_cases(
                f"tests/fixtures/guide/intent/{fixture_name}.jsonl",
                manifest_path=(
                    "tests/fixtures/guide/intent/"
                    f"{fixture_name}_manifest.json"
                ),
            )
        )
    messages = {case.message for case in cases}
    prior_messages = {case.message for case in prior_cases}
    assert not messages & prior_messages
    assert max(
        SequenceMatcher(None, left, right).ratio()
        for left in messages
        for right in prior_messages
    ) < 0.70


def test_b5_fixture_messages_pass_deterministic_protocol_preflight() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_b5_cases(_replays())

    for case in cases:
        if case.case_id.startswith((
            "blind-b5-nh-recommend-",
            "blind-b5-nh-friend-",
            "blind-b5-ctx-profile-",
            "blind-b5-ctx-friend-",
        )):
            drafts, issues = parse_exact_constraints(case.message)
            budgets = tuple(
                draft
                for draft in drafts
                if isinstance(draft, BudgetDraft)
            )
            assert not issues, case.case_id
            assert len(budgets) == 1, case.case_id
            assert budgets[0].maximum == 500, case.case_id
        if case.case_id.startswith("blind-b5-ctx-budget-"):
            drafts, issues = parse_exact_constraints(case.message)
            budgets = tuple(
                draft
                for draft in drafts
                if isinstance(draft, BudgetDraft)
            )
            assert not issues, case.case_id
            assert len(budgets) == 1, case.case_id
            assert budgets[0].maximum == 100, case.case_id
        if case.case_id.startswith("blind-b5-ctx-withdraw-"):
            proofs = parse_exact_revision_confirmations(case.message)
            assert len(proofs) == 1, case.case_id
            assert proofs[0].affected_value == "酒精", case.case_id
        if (
            case.case_id.startswith("blind-b5-ctx-affirm-")
            or case.case_id.startswith("blind-b5-ctx-reject-")
        ):
            assert case.starting_snapshot is not None
            assert case.starting_snapshot.pending_turn is not None
            reply = classify_pending_reply(
                message=case.message,
                pending=case.starting_snapshot.pending_turn,
            )
            expected_kind = (
                "affirm"
                if "-ctx-affirm-" in case.case_id
                else "reject"
            )
            assert reply.kind == expected_kind, case.case_id
        if case.category == "comparison":
            assert tuple(
                binding.product_id
                for binding in case.expected_bindings
            ) == case.expected_card_ids, case.case_id
            positions = [
                case.message.index(binding.source_text)
                for binding in case.expected_bindings
            ]
            assert positions == sorted(positions), case.case_id
        if case.category == "safety":
            drafts, _ = parse_exact_constraints(case.message)
            exact_topics = {
                draft.value.value
                for draft in drafts
                if isinstance(draft, CategoryDraft)
            }
            assert exact_topics <= set(
                case.acceptable_semantic.topic_hints
            ), case.case_id


def test_frozen_b5_batch_matches_builder() -> None:
    module = _qualification_module()
    cases = module.build_unified_router_blind_b5_cases(_replays())
    generated = (
        b"\n".join(
            case.model_dump_json().encode("utf-8")
            for case in cases
        )
        + b"\n"
    )
    fixture_path = Path(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_b_v5.jsonl"
    )
    manifest_path = Path(
        "tests/fixtures/guide/intent/"
        "unified_router_blind_b_v5_manifest.json"
    )

    assert fixture_path.read_bytes() == generated
    assert load_real_unified_router_cases(
        fixture_path,
        manifest_path=manifest_path,
    ) == cases
